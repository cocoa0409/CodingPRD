"""Composite state builders.

Every builder drives the API through the endpoints the PRD declares - nothing is
written to storage behind the server's back.  Builders use the lenient
``get_success_data`` so that a precondition failure surfaces as a helper error
rather than as a confusing assertion inside a test body.

The single-argument ``api`` is always the client fixture.  Stage builders accept
``world=`` so that a caller can insert its own earlier stage, and forward any
remaining keyword arguments to the stage below them, so a test may write::

    world = world_agreement_executed(api, project_overrides={"reimbursement_authority_cents": 1})
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    AGREEMENT_NOT_TO_EXCEED_CENTS,
    CERTIFICATION_NOTE,
    COMPLETION_NOTE,
)
from .test_users import (
    ADJUDICATOR_USER_ID,
    AUDITOR_USER_ID,
    OFFICER_USER_ID,
    make_agreement_officer_headers,
    make_construction_engineer_headers,
    make_external_auditor_headers,
    make_program_admin_headers,
    make_right_of_way_adjudicator_headers,
    make_utility_coordinator_headers,
    make_utility_owner_rep_headers,
)

# ---------------------------------------------------------------------------
# Single-step helpers, one per PRD write endpoint used as a precondition
# ---------------------------------------------------------------------------


def set_clock(api, current_utc: str) -> dict:
    """Move the logical clock (administrative test-driving endpoint)."""
    return get_success_data(
        api.set_clock({"current_utc": current_utc}, make_program_admin_headers())
    )


def register_project(api, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_project(
            f.project_payload(**overrides), headers or make_program_admin_headers()
        )
    )


def revise_project(api, project_id, headers=None, **payload) -> dict:
    return get_success_data(
        api.update_project(project_id, payload, headers or make_program_admin_headers())
    )


def register_owner(api, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_utility_owner(
            f.owner_payload(**overrides), headers or make_program_admin_headers()
        )
    )


def release_owner_hold(api, owner_id, release_note: str, headers=None) -> dict:
    return get_success_data(
        api.release_hold(
            owner_id, {"release_note": release_note}, headers or make_program_admin_headers()
        )
    )


def register_facility(api, owner_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_facility(
            f.facility_payload(owner_id, **overrides),
            headers or make_utility_coordinator_headers(),
        )
    )


def record_investigation(api, project_id, facility_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_investigation(
            f.investigation_payload(project_id, facility_id, **overrides),
            headers or make_utility_coordinator_headers(),
        )
    )


def identify_conflict(api, project_id, facility_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_conflict(
            f.conflict_payload(project_id, facility_id, **overrides),
            headers or make_utility_coordinator_headers(),
        )
    )


def select_resolution(api, conflict_id, resolution_type="RELOCATE", headers=None) -> dict:
    return get_success_data(
        api.set_conflict_resolution(
            conflict_id,
            {"resolution_type": resolution_type},
            headers or make_utility_coordinator_headers(),
        )
    )


def certify_cleared(api, conflict_id, certification_note=CERTIFICATION_NOTE, headers=None) -> dict:
    return get_success_data(
        api.certify_conflict_cleared(
            conflict_id,
            {"certification_note": certification_note},
            headers or make_utility_coordinator_headers(),
        )
    )


def draft_determination(api, conflict_id, adjudicator_id=ADJUDICATOR_USER_ID, **overrides) -> dict:
    return get_success_data(
        api.create_prior_rights(
            f.prior_rights_payload(conflict_id, **overrides),
            make_right_of_way_adjudicator_headers(adjudicator_id),
        )
    )


def issue_determination(api, determination_id, adjudicator_id=ADJUDICATOR_USER_ID) -> dict:
    """Submit a drafted determination for review and issue it."""
    headers = make_right_of_way_adjudicator_headers(adjudicator_id)
    get_success_data(api.submit_prior_rights_for_review(determination_id, headers))
    return get_success_data(api.issue_prior_rights(determination_id, headers))


def apply_permit(api, conflict_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_permit(
            f.permit_payload(conflict_id, **overrides),
            headers or make_utility_coordinator_headers(),
        )
    )


def decide_permit(api, permit_id, decision="GRANT", headers=None) -> dict:
    return get_success_data(
        api.decide_permit(
            permit_id, {"decision": decision}, headers or make_utility_coordinator_headers()
        )
    )


def grant_permit(api, conflict_id, headers=None, **overrides) -> dict:
    """Open a permit on the conflict and grant it."""
    permit = apply_permit(api, conflict_id, headers=headers, **overrides)
    return decide_permit(api, permit["id"], "GRANT", headers=headers)


def open_slot(api, project_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_joint_trench_slot(
            f.joint_trench_slot_payload(project_id, **overrides),
            headers or make_construction_engineer_headers(),
        )
    )


def read_conflict(api, conflict_id, headers=None) -> dict:
    return get_success_data(
        api.get_conflict(conflict_id, headers or make_utility_coordinator_headers())
    )


def read_plan(api, plan_id, headers=None) -> dict:
    return get_success_data(
        api.get_relocation_plan(plan_id, headers or make_utility_coordinator_headers())
    )


def read_project(api, project_id, headers=None) -> dict:
    return get_success_data(
        api.get_project(project_id, headers or make_program_admin_headers())
    )


def read_owner(api, owner_id, headers=None) -> dict:
    return get_success_data(
        api.get_utility_owner(owner_id, headers or make_program_admin_headers())
    )


def read_agreement(api, agreement_id, headers=None) -> dict:
    return get_success_data(
        api.get_agreement(agreement_id, headers or make_agreement_officer_headers())
    )


def read_commitment(api, commitment_id, headers=None) -> dict:
    return get_success_data(
        api.get_commitment(commitment_id, headers or make_utility_coordinator_headers())
    )


def read_determination(api, determination_id, headers=None) -> dict:
    return get_success_data(
        api.get_prior_rights(determination_id, headers or make_right_of_way_adjudicator_headers())
    )


def read_slot(api, slot_id, headers=None) -> dict:
    return get_success_data(
        api.get_joint_trench_slot(slot_id, headers or make_construction_engineer_headers())
    )


def read_cost_document(api, document_id, headers=None) -> dict:
    return get_success_data(
        api.get_cost_document(document_id, headers or make_agreement_officer_headers())
    )


def read_permit_record(api, permit_id, headers=None) -> dict:
    return get_success_data(
        api.get_permit(permit_id, headers or make_utility_coordinator_headers())
    )


def read_audit_finding(api, finding_id, headers=None) -> dict:
    return get_success_data(
        api.get_audit_finding(finding_id, headers or make_external_auditor_headers())
    )


def read_delay_claim(api, claim_id, headers=None) -> dict:
    return get_success_data(
        api.get_delay_claim(claim_id, headers or make_construction_engineer_headers())
    )


def read_facility(api, facility_id, headers=None) -> dict:
    return get_success_data(
        api.get_facility(facility_id, headers or make_utility_coordinator_headers())
    )


def read_investigation(api, investigation_id, headers=None) -> dict:
    return get_success_data(
        api.get_investigation(investigation_id, headers or make_utility_coordinator_headers())
    )


def read_clearance_summary(api, project_id, headers=None) -> dict:
    return get_success_data(
        api.get_clearance_summary(project_id, headers or make_program_admin_headers())
    )


def read_settlement_preview(api, agreement_id, headers=None) -> dict:
    return get_success_data(
        api.get_settlement_preview(agreement_id, headers or make_agreement_officer_headers())
    )


def submit_plan(api, conflict_id, headers=None, expected_conflict_version=None, **overrides) -> dict:
    """Submit a relocation plan, reading the conflict's current version first."""
    if expected_conflict_version is None:
        expected_conflict_version = read_conflict(api, conflict_id)["version"]
    return get_success_data(
        api.create_relocation_plan(
            f.plan_payload(conflict_id, expected_conflict_version, **overrides),
            headers or make_utility_coordinator_headers(),
        )
    )


def start_plan_review(api, plan_id, headers=None) -> dict:
    return get_success_data(
        api.start_plan_review(plan_id, headers or make_utility_coordinator_headers())
    )


def approve_plan(api, plan_id, headers=None) -> dict:
    """Take a submitted plan into review and approve it."""
    coordinator = headers or make_utility_coordinator_headers()
    start_plan_review(api, plan_id, coordinator)
    return get_success_data(api.approve_plan(plan_id, coordinator))


def commit_window(api, plan_id, owner_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_commitment(
            f.commitment_payload(plan_id, **overrides),
            headers or make_utility_owner_rep_headers(owner_id),
        )
    )


def start_work(api, commitment_id, owner_id) -> dict:
    return get_success_data(
        api.start_commitment_work(commitment_id, make_utility_owner_rep_headers(owner_id))
    )


def report_complete(api, commitment_id, owner_id, completion_note=COMPLETION_NOTE) -> dict:
    return get_success_data(
        api.report_commitment_complete(
            commitment_id,
            {"completion_note": completion_note},
            make_utility_owner_rep_headers(owner_id),
        )
    )


def cancel_commitment(api, commitment_id, owner_id, cancellation_reason) -> dict:
    return get_success_data(
        api.cancel_commitment(
            commitment_id,
            {"cancellation_reason": cancellation_reason},
            make_utility_owner_rep_headers(owner_id),
        )
    )


def draft_agreement(
    api,
    plan_id,
    not_to_exceed_cents=AGREEMENT_NOT_TO_EXCEED_CENTS,
    officer_id=OFFICER_USER_ID,
    expected_plan_version=None,
    **overrides,
) -> dict:
    """Draft a reimbursement agreement, reading the plan's current version first."""
    if expected_plan_version is None:
        expected_plan_version = read_plan(api, plan_id)["version"]
    return get_success_data(
        api.create_agreement(
            f.agreement_payload(
                plan_id, expected_plan_version, not_to_exceed_cents, **overrides
            ),
            make_agreement_officer_headers(officer_id),
        )
    )


def circulate_agreement(api, agreement_id, officer_id=OFFICER_USER_ID) -> dict:
    return get_success_data(
        api.circulate_agreement(agreement_id, make_agreement_officer_headers(officer_id))
    )


def execute_agreement(api, agreement_id, officer_id=OFFICER_USER_ID) -> dict:
    """Circulate a drafted agreement and execute it."""
    circulate_agreement(api, agreement_id, officer_id)
    return get_success_data(
        api.execute_agreement(agreement_id, make_agreement_officer_headers(officer_id))
    )


def open_final_billing(api, agreement_id, officer_id=OFFICER_USER_ID) -> dict:
    return get_success_data(
        api.open_final_billing(agreement_id, make_agreement_officer_headers(officer_id))
    )


def void_agreement(api, agreement_id, void_reason, officer_id=OFFICER_USER_ID) -> dict:
    return get_success_data(
        api.void_agreement(
            agreement_id, {"void_reason": void_reason}, make_agreement_officer_headers(officer_id)
        )
    )


def settle_agreement(api, agreement_id, as_built_reference, officer_id=OFFICER_USER_ID) -> dict:
    return get_success_data(
        api.final_settlement(
            agreement_id,
            {"as_built_reference": as_built_reference},
            make_agreement_officer_headers(officer_id),
        )
    )


def submit_cost_document(api, agreement_id, owner_id, **overrides) -> dict:
    return get_success_data(
        api.create_cost_document(
            f.cost_document_payload(agreement_id, **overrides),
            make_utility_owner_rep_headers(owner_id),
        )
    )


def accept_cost_document(api, document_id, officer_id=OFFICER_USER_ID) -> dict:
    return get_success_data(
        api.review_cost_document(
            document_id, {"disposition": "ACCEPT"}, make_agreement_officer_headers(officer_id)
        )
    )


def disallow_cost_document(
    api, document_id, exclusion_reason="NOT_SUPPORTED", officer_id=OFFICER_USER_ID
) -> dict:
    return get_success_data(
        api.review_cost_document(
            document_id,
            {"disposition": "DISALLOW", "exclusion_reason": exclusion_reason},
            make_agreement_officer_headers(officer_id),
        )
    )


def raise_audit_finding(api, agreement_id, auditor_id=AUDITOR_USER_ID, **overrides) -> dict:
    return get_success_data(
        api.create_audit_finding(
            f.audit_finding_payload(agreement_id, **overrides),
            make_external_auditor_headers(auditor_id),
        )
    )


def resolve_audit_finding(
    api, finding_id, disposition="WITHDRAWN", auditor_id=AUDITOR_USER_ID
) -> dict:
    return get_success_data(
        api.resolve_audit_finding(
            finding_id, {"disposition": disposition}, make_external_auditor_headers(auditor_id)
        )
    )


def lodge_delay_claim(api, commitment_id, project_id, **overrides) -> dict:
    return get_success_data(
        api.create_delay_claim(
            f.delay_claim_payload(commitment_id, project_id, **overrides),
            make_construction_engineer_headers(),
        )
    )


def analyze_delay_claim(api, claim_id, delay_cause="UTILITY_OWNER") -> dict:
    return get_success_data(
        api.analyze_delay_claim(
            claim_id, {"delay_cause": delay_cause}, make_construction_engineer_headers()
        )
    )


def allocate_delay_claim(api, claim_id) -> dict:
    return get_success_data(
        api.allocate_delay_claim(claim_id, make_construction_engineer_headers())
    )


# ---------------------------------------------------------------------------
# Tier 1-2: project, owner, facility and conflict skeleton
# ---------------------------------------------------------------------------


def world_registry(
    api, *, project_overrides=None, owner_overrides=None, facility_overrides=None
) -> dict:
    """A project, an owner and one facility of record for that owner."""
    project = register_project(api, **(project_overrides or {}))
    owner = register_owner(api, **(owner_overrides or {}))
    facility = register_facility(api, owner["id"], **(facility_overrides or {}))
    return {
        "project": project,
        "owner": owner,
        "facility": facility,
        "project_id": project["id"],
        "owner_id": owner["id"],
        "facility_id": facility["id"],
        "rep_headers": make_utility_owner_rep_headers(owner["id"]),
    }


def world_conflict(api, *, conflict_overrides=None, world=None, **kw) -> dict:
    """A conflict opened against the facility of record, still ``IDENTIFIED``."""
    world = world or world_registry(api, **kw)
    conflict = identify_conflict(
        api, world["project_id"], world["facility_id"], **(conflict_overrides or {})
    )
    world["conflict"] = conflict
    world["conflict_id"] = conflict["id"]
    return world


def world_resolution_selected(api, *, resolution_type="RELOCATE", world=None, **kw) -> dict:
    world = world or world_conflict(api, **kw)
    world["conflict"] = select_resolution(api, world["conflict_id"], resolution_type)
    return world


# ---------------------------------------------------------------------------
# Tier 3: the relocate branch up to an approved plan
# ---------------------------------------------------------------------------


def world_determination_drafted(
    api, *, determination_overrides=None, adjudicator_id=ADJUDICATOR_USER_ID, world=None, **kw
) -> dict:
    world = world or world_resolution_selected(api, **kw)
    determination = draft_determination(
        api, world["conflict_id"], adjudicator_id, **(determination_overrides or {})
    )
    world["determination"] = determination
    world["determination_id"] = determination["id"]
    return world


def world_determination_issued(
    api, *, adjudicator_id=ADJUDICATOR_USER_ID, world=None, **kw
) -> dict:
    """Prior rights issued, so the conflict carries a frozen state share."""
    world = world or world_determination_drafted(api, adjudicator_id=adjudicator_id, **kw)
    world["determination"] = issue_determination(
        api, world["determination_id"], adjudicator_id
    )
    world["conflict"] = read_conflict(api, world["conflict_id"])
    return world


def world_plan_submitted(api, *, plan_overrides=None, plan_headers=None, world=None, **kw) -> dict:
    world = world or world_determination_issued(api, **kw)
    plan = submit_plan(
        api, world["conflict_id"], headers=plan_headers, **(plan_overrides or {})
    )
    world["plan"] = plan
    world["plan_id"] = plan["id"]
    world["conflict"] = read_conflict(api, world["conflict_id"])
    return world


def world_permit_granted(api, *, permit_overrides=None, world=None, **kw) -> dict:
    world = world or world_plan_submitted(api, **kw)
    world["permit"] = grant_permit(api, world["conflict_id"], **(permit_overrides or {}))
    world["permit_id"] = world["permit"]["id"]
    return world


def world_plan_approved(api, *, world=None, **kw) -> dict:
    """An approved plan: prior rights issued and every permit of the conflict granted."""
    world = world or world_permit_granted(api, **kw)
    world["plan"] = approve_plan(api, world["plan_id"])
    world["conflict"] = read_conflict(api, world["conflict_id"])
    return world


# ---------------------------------------------------------------------------
# Tier 3-4: the agreement and settlement track
# ---------------------------------------------------------------------------


def world_agreement_drafted(
    api,
    *,
    not_to_exceed_cents=AGREEMENT_NOT_TO_EXCEED_CENTS,
    officer_id=OFFICER_USER_ID,
    world=None,
    **kw,
) -> dict:
    world = world or world_plan_approved(api, **kw)
    agreement = draft_agreement(
        api, world["plan_id"], not_to_exceed_cents, officer_id
    )
    world["agreement"] = agreement
    world["agreement_id"] = agreement["id"]
    world["officer_id"] = officer_id
    world["plan"] = read_plan(api, world["plan_id"])
    return world


def world_agreement_circulated(api, *, world=None, **kw) -> dict:
    world = world or world_agreement_drafted(api, **kw)
    world["agreement"] = circulate_agreement(
        api, world["agreement_id"], world.get("officer_id", OFFICER_USER_ID)
    )
    return world


def world_agreement_executed(api, *, world=None, **kw) -> dict:
    """An executed agreement, so its state share sits in the committed ledger."""
    world = world or world_agreement_circulated(api, **kw)
    world["agreement"] = get_success_data(
        api.execute_agreement(
            world["agreement_id"],
            make_agreement_officer_headers(world.get("officer_id", OFFICER_USER_ID)),
        )
    )
    return world


def world_final_billing_open(api, *, world=None, **kw) -> dict:
    world = world or world_agreement_executed(api, **kw)
    world["agreement"] = open_final_billing(
        api, world["agreement_id"], world.get("officer_id", OFFICER_USER_ID)
    )
    return world


DEFAULT_ACCEPTED_DOCUMENT = {
    "doc_type": "LABOR",
    "amount_cents": 12_345_678,
    "incurred_on": "2027-04-02T00:00:00Z",
    "support_reference": "PR-1001",
    "review": "ACCEPT",
}


def world_cost_documents(api, *, documents=None, world=None, **kw) -> dict:
    """Submit and review a list of cost documents under an agreement in final billing.

    Each entry is a cost-document body plus an optional ``review`` key of
    ``"ACCEPT"``, ``"DISALLOW"`` or ``None`` (leave it ``SUBMITTED``).  A
    ``DISALLOW`` entry may also carry ``disallowed_amount_cents`` and
    ``exclusion_reason``.
    """
    world = world or world_final_billing_open(api, **kw)
    specs = [dict(spec) for spec in (documents or [DEFAULT_ACCEPTED_DOCUMENT])]
    rows = []
    for spec in specs:
        review = spec.pop("review", "ACCEPT")
        reason = spec.pop("exclusion_reason", "NOT_SUPPORTED")
        row = submit_cost_document(api, world["agreement_id"], world["owner_id"], **spec)
        if review == "ACCEPT":
            row = accept_cost_document(api, row["id"], world.get("officer_id", OFFICER_USER_ID))
        elif review == "DISALLOW":
            row = disallow_cost_document(
                api, row["id"], reason, world.get("officer_id", OFFICER_USER_ID)
            )
        rows.append(row)
    world["documents"] = rows
    world["document_ids"] = [row["id"] for row in rows]
    world["agreement"] = read_agreement(api, world["agreement_id"])
    return world


# ---------------------------------------------------------------------------
# Tier 4: the scheduling track
# ---------------------------------------------------------------------------


def world_commitment(api, *, commitment_overrides=None, world=None, **kw) -> dict:
    """A committed relocation window against an approved plan."""
    world = world or world_plan_approved(api, **kw)
    commitment = commit_window(
        api, world["plan_id"], world["owner_id"], **(commitment_overrides or {})
    )
    world["commitment"] = commitment
    world["commitment_id"] = commitment["id"]
    world["conflict"] = read_conflict(api, world["conflict_id"])
    return world


def world_slot_and_commitment(
    api, *, slot_overrides=None, commitment_overrides=None, world=None, **kw
) -> dict:
    """A joint trench slot with one commitment occupying it."""
    world = world or world_plan_approved(api, **kw)
    slot = open_slot(api, world["project_id"], **(slot_overrides or {}))
    world["slot"] = slot
    world["slot_id"] = slot["id"]
    overrides = dict(commitment_overrides or {})
    overrides["joint_trench_slot_id"] = slot["id"]
    commitment = commit_window(api, world["plan_id"], world["owner_id"], **overrides)
    world["commitment"] = commitment
    world["commitment_id"] = commitment["id"]
    world["slot"] = read_slot(api, slot["id"])
    return world


def world_commitment_breached(
    api, *, completion_clock="2027-04-28T00:00:00Z", world=None, **kw
) -> dict:
    """A commitment reported complete after its window closed, so it is ``BREACHED``."""
    world = world or world_commitment(api, **kw)
    set_clock(api, completion_clock)
    world["commitment"] = report_complete(
        api, world["commitment_id"], world["owner_id"]
    )
    world["owner"] = read_owner(api, world["owner_id"])
    return world


def add_second_relocate_chain(
    api,
    world,
    *,
    facility_overrides=None,
    conflict_overrides=None,
    plan_overrides=None,
    adjudicator_id=ADJUDICATOR_USER_ID,
    approve=True,
) -> dict:
    """Add a second facility, conflict, determination and plan for the same owner.

    Keys are stored with a ``_b`` suffix.  A second facility keeps the two
    commitments off one another's facility-occupancy window.
    """
    from .constants import SECOND_FACILITY_PAYLOAD

    facility_body = dict(SECOND_FACILITY_PAYLOAD)
    facility_body.update(facility_overrides or {})
    facility_b = register_facility(api, world["owner_id"], **facility_body)
    conflict_body = {"conflict_station": 220.0, "clearance_deficiency_in": 12}
    conflict_body.update(conflict_overrides or {})
    conflict_b = identify_conflict(
        api, world["project_id"], facility_b["id"], **conflict_body
    )
    select_resolution(api, conflict_b["id"], "RELOCATE")
    determination_b = draft_determination(api, conflict_b["id"], adjudicator_id)
    determination_b = issue_determination(api, determination_b["id"], adjudicator_id)
    plan_b = submit_plan(api, conflict_b["id"], **(plan_overrides or {}))
    grant_permit(api, conflict_b["id"])
    if approve:
        plan_b = approve_plan(api, plan_b["id"])
    world.update(
        {
            "facility_b": facility_b,
            "facility_b_id": facility_b["id"],
            "conflict_b": read_conflict(api, conflict_b["id"]),
            "conflict_b_id": conflict_b["id"],
            "determination_b": determination_b,
            "determination_b_id": determination_b["id"],
            "plan_b": plan_b,
            "plan_b_id": plan_b["id"],
        }
    )
    return world


def world_owner_on_hold(api, *, world=None, **kw) -> dict:
    """Two breached commitments on one owner, so the delinquency hold is imposed.

    The first window closes on 20 April 2027 and the second on 20 May 2027; the
    clock is advanced eight days past each in turn, giving two strikes.  The
    owner also carries an executed agreement in final billing with one submitted
    cost document, so the hold cascade has rows to suspend.
    """
    world = world or world_final_billing_open(api, **kw)
    commitment_a = commit_window(api, world["plan_id"], world["owner_id"])
    world["commitment"] = commitment_a
    world["commitment_id"] = commitment_a["id"]
    add_second_relocate_chain(api, world)
    commitment_b = commit_window(
        api,
        world["plan_b_id"],
        world["owner_id"],
        window_start="2027-05-05T00:00:00Z",
        window_end="2027-05-20T00:00:00Z",
    )
    world["commitment_b"] = commitment_b
    world["commitment_b_id"] = commitment_b["id"]
    document = submit_cost_document(api, world["agreement_id"], world["owner_id"])
    world["documents"] = [document]
    world["document_ids"] = [document["id"]]

    set_clock(api, "2027-04-28T00:00:00Z")
    world["commitment"] = report_complete(api, commitment_a["id"], world["owner_id"])
    set_clock(api, "2027-05-28T00:00:00Z")
    world["commitment_b"] = report_complete(api, commitment_b["id"], world["owner_id"])

    world["owner"] = read_owner(api, world["owner_id"])
    world["agreement"] = read_agreement(api, world["agreement_id"])
    world["documents"] = [read_cost_document(api, document["id"])]
    return world


# ---------------------------------------------------------------------------
# Tier 5: terminal states
# ---------------------------------------------------------------------------


def world_conflict_cleared(api, *, world=None, **kw) -> dict:
    """The relocate branch carried all the way to a certified-cleared conflict.

    Reporting completion while the clock still reads its startup default keeps
    the commitment on time, so nothing in the delinquency cascade fires.
    """
    world = world or world_commitment(api, **kw)
    world["commitment"] = start_work(api, world["commitment_id"], world["owner_id"])
    world["commitment"] = report_complete(
        api,
        world["commitment_id"],
        world["owner_id"],
        "Relocation finished inside the committed window.",
    )
    world["conflict"] = certify_cleared(api, world["conflict_id"])
    world["project"] = read_project(api, world["project_id"])
    world["determination"] = read_determination(api, world["determination_id"])
    return world


def world_project_closed(api, *, closure_note, world=None, **kw) -> dict:
    """A closed project: every conflict cleared and no unsettled agreement."""
    world = world or world_conflict_cleared(api, **kw)
    world["project"] = get_success_data(
        api.close_project(
            world["project_id"], {"closure_note": closure_note}, make_program_admin_headers()
        )
    )
    return world


__all__ = [
    "set_clock",
    "register_project",
    "revise_project",
    "register_owner",
    "release_owner_hold",
    "register_facility",
    "record_investigation",
    "identify_conflict",
    "select_resolution",
    "certify_cleared",
    "draft_determination",
    "issue_determination",
    "apply_permit",
    "decide_permit",
    "grant_permit",
    "open_slot",
    "read_conflict",
    "read_plan",
    "read_project",
    "read_owner",
    "read_agreement",
    "read_commitment",
    "read_determination",
    "read_slot",
    "read_cost_document",
    "read_permit_record",
    "read_audit_finding",
    "read_delay_claim",
    "read_facility",
    "read_investigation",
    "read_clearance_summary",
    "read_settlement_preview",
    "submit_plan",
    "start_plan_review",
    "approve_plan",
    "commit_window",
    "start_work",
    "report_complete",
    "cancel_commitment",
    "draft_agreement",
    "circulate_agreement",
    "execute_agreement",
    "open_final_billing",
    "void_agreement",
    "settle_agreement",
    "submit_cost_document",
    "accept_cost_document",
    "disallow_cost_document",
    "raise_audit_finding",
    "resolve_audit_finding",
    "lodge_delay_claim",
    "analyze_delay_claim",
    "allocate_delay_claim",
    "world_registry",
    "world_conflict",
    "world_resolution_selected",
    "world_determination_drafted",
    "world_determination_issued",
    "world_plan_submitted",
    "world_permit_granted",
    "world_plan_approved",
    "world_agreement_drafted",
    "world_agreement_circulated",
    "world_agreement_executed",
    "world_final_billing_open",
    "world_cost_documents",
    "world_commitment",
    "world_slot_and_commitment",
    "world_commitment_breached",
    "add_second_relocate_chain",
    "world_owner_on_hold",
    "world_conflict_cleared",
    "world_project_closed",
    "DEFAULT_ACCEPTED_DOCUMENT",
]
