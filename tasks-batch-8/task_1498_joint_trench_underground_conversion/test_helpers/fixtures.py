"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch through the public API —
the test runner restarts the server before each test, so nothing persists.
Setup calls use get_success_data() so a failure here surfaces as a clear
"Setup failed" assertion rather than a confusing downstream mismatch.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_project_payload,
    create_participation_payload,
    create_trench_segment_payload,
    schedule_segment_payload,
    create_occupancy_slot_payload,
    create_parcel_payload,
    create_easement_payload,
    create_permit_payload,
    create_service_conversion_payload,
    create_actual_cost_entry_payload,
    create_restoration_task_payload,
)
from .test_users import (
    TEST_USERS,
    make_coordinator_headers,
    make_pm_headers,
    make_finance_headers,
)

PM = TEST_USERS["pm_headers"]
ROW = TEST_USERS["row_headers"]
CONTRACTOR = TEST_USERS["contractor_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation + state progression
# ---------------------------------------------------------------------------

def create_project(**overrides):
    """Create a project (PLANNING / CLEAR). Returns the project dict."""
    resp = api_client.create_project(create_project_payload(**overrides), PM)
    return get_success_data(resp)


def invite_participation(project_id, utility_name, utility_type, cost_share_bp,
                         sequence_order, has_separation_waiver=None):
    """Invite one utility. Returns the INVITED participation dict."""
    payload = create_participation_payload(
        project_id,
        utility_name=utility_name,
        utility_type=utility_type,
        cost_share_bp=cost_share_bp,
        sequence_order=sequence_order,
    )
    if has_separation_waiver is not None:
        payload["has_separation_waiver"] = has_separation_waiver
    resp = api_client.create_participation(payload, PM)
    return get_success_data(resp)


def commit_participation(participation_id):
    """INVITED -> COMMITTED by the owning coordinator (project must be PLANNING)."""
    resp = api_client.transition_participation(
        participation_id, {"to": "COMMITTED"}, make_coordinator_headers(participation_id)
    )
    return get_success_data(resp)


def mobilize_participation(participation_id):
    """COMMITTED -> MOBILIZED by the owning coordinator."""
    resp = api_client.transition_participation(
        participation_id, {"to": "MOBILIZED"}, make_coordinator_headers(participation_id)
    )
    return get_success_data(resp)


def install_participation(participation_id):
    """MOBILIZED -> INSTALLED (requires all of its slots VERIFIED|RELEASED)."""
    resp = api_client.transition_participation(
        participation_id, {"to": "INSTALLED"}, make_coordinator_headers(participation_id)
    )
    return get_success_data(resp)


def mobilize_project(project_id):
    """Project lifecycle PLANNING -> MOBILIZED."""
    resp = api_client.project_lifecycle(project_id, {"action": "MOBILIZE"}, PM)
    return get_success_data(resp)


def lifecycle(project_id, action):
    resp = api_client.project_lifecycle(project_id, {"action": action}, PM)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy (project + participations)
# ---------------------------------------------------------------------------

def create_project_with_committed_participants(participant_specs, **project_overrides):
    """Project + N participations, each INVITED -> COMMITTED.

    participant_specs: list of dicts with keys utility_name, utility_type,
        cost_share_bp, sequence_order (has_separation_waiver optional).
    Returns (project, participations) in spec order.
    """
    project = create_project(**project_overrides)
    participations = []
    for spec in participant_specs:
        p = invite_participation(project["id"], **spec)
        participations.append(commit_participation(p["id"]))
    return project, participations


def setup_mobilized_project(participant_specs, **project_overrides):
    """Project + committed participations + MOBILIZE. Returns (project, participations)."""
    project, participations = create_project_with_committed_participants(
        participant_specs, **project_overrides
    )
    project = mobilize_project(project["id"])
    return project, participations


# ---------------------------------------------------------------------------
# Tier 2: right-of-way chain (parcel + easement + permit)
# ---------------------------------------------------------------------------

def create_parcel(project_id, **overrides):
    resp = api_client.create_parcel(create_parcel_payload(project_id, **overrides), ROW)
    return get_success_data(resp)


def create_parcel_with_recorded_easement(project_id, easement_type="TRENCH", **parcel_overrides):
    """Parcel + TRENCH easement driven DRAFT -> REQUESTED -> SIGNED -> RECORDED."""
    parcel = create_parcel(project_id, **parcel_overrides)
    es = get_success_data(api_client.create_easement(
        create_easement_payload(parcel["id"], easement_type=easement_type), ROW))
    es = get_success_data(api_client.transition_easement(es["id"], {"to": "REQUESTED"}, ROW))
    es = get_success_data(api_client.transition_easement(es["id"], {"to": "SIGNED"}, ROW))
    es = get_success_data(api_client.transition_easement(es["id"], {"to": "RECORDED"}, ROW))
    return parcel, es


def create_issued_permit(project_id, **overrides):
    """Permit driven APPLICATION -> SUBMITTED -> ISSUED."""
    perm = get_success_data(api_client.create_permit(
        create_permit_payload(project_id, **overrides), ROW))
    perm = get_success_data(api_client.transition_permit(perm["id"], {"to": "SUBMITTED"}, ROW))
    perm = get_success_data(api_client.transition_permit(perm["id"], {"to": "ISSUED"}, ROW))
    return perm


# ---------------------------------------------------------------------------
# Tier 2/3: trench segment scheduling and progression
# ---------------------------------------------------------------------------

def create_scheduled_segment(project_id, excavation_start_on="2026-09-01T00:00:00Z",
                             excavation_end_on="2026-09-10T00:00:00Z", **overrides):
    """Segment created PLANNED then scheduled (OCC-correct). Returns scheduled segment."""
    seg = get_success_data(api_client.create_trench_segment(
        create_trench_segment_payload(project_id, **overrides), PM))
    seg = get_success_data(api_client.schedule_trench_segment(
        seg["id"],
        schedule_segment_payload(
            excavation_start_on=excavation_start_on,
            excavation_end_on=excavation_end_on,
            expected_trench_segment_version=seg["version"],
        ),
        PM,
    ))
    return seg


def transition_segment(segment_id, to):
    resp = api_client.transition_trench_segment(segment_id, {"to": to}, PM)
    return get_success_data(resp)


def reserve_slot(segment_id, participation_id, **overrides):
    """Create an occupancy slot as the owning coordinator. Returns RESERVED slot."""
    resp = api_client.create_occupancy_slot(
        create_occupancy_slot_payload(segment_id, participation_id, **overrides),
        make_coordinator_headers(participation_id),
    )
    return get_success_data(resp)


def transition_slot(slot_id, to, participation_id=None, as_pm=False):
    headers = PM if as_pm else make_coordinator_headers(participation_id)
    resp = api_client.transition_occupancy_slot(slot_id, {"to": to}, headers)
    return get_success_data(resp)


def verify_slot(slot_id):
    """INSTALLED -> VERIFIED (ProgramManager)."""
    return transition_slot(slot_id, "VERIFIED", as_pm=True)


def drive_slot_to_verified(slot_id, participation_id):
    """RESERVED -> INSTALLING -> INSTALLED -> VERIFIED."""
    transition_slot(slot_id, "INSTALLING", participation_id)
    transition_slot(slot_id, "INSTALLED", participation_id)
    return verify_slot(slot_id)


# ---------------------------------------------------------------------------
# Tier 3: conversion + restoration lifecycles
# ---------------------------------------------------------------------------

def create_service_conversion(parcel_id, project_id):
    resp = api_client.create_service_conversion(
        create_service_conversion_payload(parcel_id, project_id), CONTRACTOR)
    return get_success_data(resp)


def work_transition(conversion_id, to, **extra):
    payload = {"to": to}
    payload.update(extra)
    resp = api_client.work_transition(conversion_id, payload, CONTRACTOR)
    return get_success_data(resp)


def temp_transition(conversion_id, to):
    resp = api_client.temp_service_transition(conversion_id, {"to": to}, CONTRACTOR)
    return get_success_data(resp)


def drive_conversion_to_complete(parcel_id, project_id, panel_capacity_amps=125):
    """Conversion PLANNED -> ... -> COMPLETE (PASS inspection, no temp service)."""
    conv = create_service_conversion(parcel_id, project_id)
    work_transition(conv["id"], "ROUGH_IN")
    work_transition(conv["id"], "PANEL_SET", panel_capacity_amps=panel_capacity_amps)
    work_transition(conv["id"], "READY_TO_ENERGIZE")
    work_transition(conv["id"], "ENERGIZED")
    work_transition(conv["id"], "INSPECTED", outcome="PASS")
    return work_transition(conv["id"], "COMPLETE")


def drive_restoration_to_accepted(segment_id, parcel_id, task_type="HARDSCAPE"):
    """Restoration task OPEN -> IN_WORK -> COMPLETE -> ACCEPTED."""
    rt = get_success_data(api_client.create_restoration_task(
        create_restoration_task_payload(segment_id, parcel_id, task_type=task_type), CONTRACTOR))
    rt = get_success_data(api_client.transition_restoration_task(rt["id"], {"to": "IN_WORK"}, CONTRACTOR))
    rt = get_success_data(api_client.transition_restoration_task(rt["id"], {"to": "COMPLETE"}, CONTRACTOR))
    rt = get_success_data(api_client.transition_restoration_task(rt["id"], {"to": "ACCEPTED"}, PM))
    return rt


# ---------------------------------------------------------------------------
# Tier 4/5: full golden path to RECONCILIATION and true-up publication
# ---------------------------------------------------------------------------

def setup_reconciliation_project(
    participant_specs,
    project_overrides=None,
    with_slots=None,
    task_type="HARDSCAPE",
    install_indexes=None,
    mobilize_only_indexes=(),
):
    """Full golden path: project -> committed participants -> MOBILIZE ->
    parcel + RECORDED TRENCH easement -> ISSUED encroachment permit ->
    segment scheduled -> TRENCHING -> EXCAVATING -> (optional slots verified)
    -> participants INSTALLED -> BACKFILLING -> BACKFILLED -> conversion
    COMPLETE -> restoration ACCEPTED -> segment CLOSED -> CONVERTING ->
    RECONCILIATION.

    participant_specs: list of dicts (utility_name, utility_type, cost_share_bp,
        sequence_order, has_separation_waiver?).
    with_slots: optional list of slot dicts {participation_index, depth_top_inches,
        depth_bottom_inches, install_start_at, install_end_at}; each slot is
        reserved and driven to VERIFIED before the participants are INSTALLED.
    install_indexes: which participants to drive COMMITTED -> MOBILIZED ->
        INSTALLED (default: all). Others are left COMMITTED.
    mobilize_only_indexes: participants to drive COMMITTED -> MOBILIZED only
        (must run while the project is MOBILIZED..CONVERTING).
    Returns dict with project, participations, parcel, easement, permit, segment,
    conversion, restoration_task.
    """
    project_overrides = project_overrides or {}
    project, participations = create_project_with_committed_participants(
        participant_specs, **project_overrides
    )
    project = mobilize_project(project["id"])
    parcel, easement = create_parcel_with_recorded_easement(project["id"])
    permit = create_issued_permit(project["id"])
    segment = create_scheduled_segment(project["id"], parcel_ids=[parcel["id"]])
    project = lifecycle(project["id"], "START_TRENCHING")
    segment = transition_segment(segment["id"], "EXCAVATING")

    slots = []
    for slot_spec in (with_slots or []):
        spec = dict(slot_spec)
        owner = participations[spec.pop("participation_index")]
        slot = reserve_slot(segment["id"], owner["id"], **spec)
        slots.append(drive_slot_to_verified(slot["id"], owner["id"]))

    indexes = range(len(participations)) if install_indexes is None else install_indexes
    participations = [
        install_participation(mobilize_participation(p["id"])["id"])
        if i in indexes
        else (mobilize_participation(p["id"]) if i in mobilize_only_indexes else p)
        for i, p in enumerate(participations)
    ]

    segment = transition_segment(segment["id"], "BACKFILLING")
    segment = transition_segment(segment["id"], "BACKFILLED")
    conversion = drive_conversion_to_complete(parcel["id"], project["id"])
    restoration_task = drive_restoration_to_accepted(segment["id"], parcel["id"], task_type=task_type)
    segment = transition_segment(segment["id"], "CLOSED")
    project = lifecycle(project["id"], "START_CONVERSION")
    project = lifecycle(project["id"], "START_RECONCILIATION")
    return {
        "project": project,
        "participations": participations,
        "parcel": parcel,
        "easement": easement,
        "permit": permit,
        "segment": segment,
        "conversion": conversion,
        "restoration_task": restoration_task,
        "slots": slots,
    }


def post_actual_costs(project_id, entries, submitter="fin-1"):
    """Append actual cost entries as a FinanceAnalyst. entries: list of dicts
    (cost_code, amount_cents, incurred_on, participation_id?)."""
    headers = make_finance_headers(submitter)
    created = []
    for entry in entries:
        resp = api_client.create_actual_cost_entry(
            create_actual_cost_entry_payload(project_id, **entry), headers)
        created.append(get_success_data(resp))
    return created


def create_true_up_run(project_id, creator="fin-1"):
    """Create a DRAFT true-up run (OCC on the live project version)."""
    project = get_success_data(api_client.get_project(project_id, PM))
    resp = api_client.create_true_up_run(
        {"project_id": project_id, "expected_project_version": project["version"]},
        make_finance_headers(creator),
    )
    return get_success_data(resp)


def publish_true_up_run(run_id, publisher="pm-1"):
    """DRAFT -> PUBLISHED as a ProgramManager distinct from the creator."""
    resp = api_client.transition_true_up_run(
        run_id, {"to": "PUBLISHED"}, make_pm_headers(publisher))
    return get_success_data(resp)


def list_run_invoices(run_id):
    """Invoices of a run in participation order (ascending sequence_order)."""
    data, _meta = validate_paginated(
        api_client.list_invoices(PM, params={"true_up_run_id": run_id}))
    return data
