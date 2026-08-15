"""Composite setup helpers for multi-step test prerequisites.

The test runner restarts the API server before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() so a failed precondition surfaces as a
clear "setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import WINDOW_COVERING_DEFAULT_CLOCK
from .factories import (
    create_after_action_report_payload,
    create_alternate_care_site_payload,
    create_callback_request_payload,
    create_command_assignment_payload,
    create_exercise_payload,
    create_external_report_payload,
    create_family_inquiry_payload,
    create_hazard_assessment_payload,
    create_improvement_task_payload,
    create_incident_payload,
    create_patient_record_payload,
    create_plan_revision_payload,
    create_site_commitment_payload,
    create_staff_member_payload,
    create_stock_transaction_payload,
    create_supply_item_payload,
)
from .test_users import (
    TEST_USERS,
    make_emergency_manager_headers,
    make_hospital_administrator_headers,
    make_liaison_officer_headers,
    make_on_call_staff_headers,
)

EM = TEST_USERS["emergency_manager_headers"]
IC = TEST_USERS["incident_commander_headers"]
PC = TEST_USERS["planning_chief_headers"]
LC = TEST_USERS["logistics_chief_headers"]
PIO = TEST_USERS["public_information_officer_headers"]
LO = TEST_USERS["liaison_officer_headers"]
HA = TEST_USERS["hospital_administrator_headers"]
PA = TEST_USERS["platform_admin_headers"]


# ─── Clock ────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server-side logical clock (PRD §2.5). Returns the sweep report."""
    return get_success_data(api_client.set_clock(to_iso8601, PA))


# ─── Tier 1: single-entity creation ───────────────────

def create_staff_member(**overrides):
    return get_success_data(
        api_client.create_staff_member(create_staff_member_payload(**overrides), HA), 201
    )


def create_callback_eligible_staff(score=0, department="EMERGENCY", **overrides):
    """A staff member who is active (default) and call-back eligible (PRD §3.5)."""
    overrides.setdefault("callback_eligible", True)
    overrides.setdefault("callback_seniority_score", score)
    overrides.setdefault("department", department)
    return create_staff_member(**overrides)


def create_command_qualified_staff(command_role, **overrides):
    overrides["role_qualifications"] = [command_role]
    overrides.setdefault("department", "ADMINISTRATION")
    return create_staff_member(**overrides)


def create_incident(**overrides):
    """Declare an incident; creation is itself the first activation (PRD §3.4)."""
    return get_success_data(
        api_client.create_incident(create_incident_payload(**overrides), IC), 201
    )


def create_and_demobilize_incident(**overrides):
    incident = create_incident(**overrides)
    return get_success_data(api_client.demobilize_incident(incident["id"], IC))


def assess_surge(incident_id, staffed_bed_count, projected_census, headers=None):
    return get_success_data(
        api_client.assess_surge(
            incident_id,
            {"staffed_bed_count": staffed_bed_count, "projected_census": projected_census},
            headers or IC,
        )
    )


def create_hazard_assessment(**overrides):
    return get_success_data(
        api_client.create_hazard_assessment(create_hazard_assessment_payload(**overrides), EM),
        201,
    )


def create_finalized_hva(entries, scoring_model="TWO_FACTOR", **overrides):
    hva = create_hazard_assessment(
        scoring_model=scoring_model, hazard_entries=entries, **overrides
    )
    return get_success_data(api_client.finalize_hazard_assessment(hva["id"], EM))


def create_supply_item(**overrides):
    return get_success_data(
        api_client.create_supply_item(create_supply_item_payload(**overrides), LC), 201
    )


def post_stock(supply_item_id, transaction_type, quantity,
               occurred_at="2026-07-30T09:00:00Z", **overrides):
    return get_success_data(
        api_client.create_stock_transaction(
            create_stock_transaction_payload(
                supply_item_id, transaction_type, quantity, occurred_at, **overrides
            ),
            LC,
        ),
        201,
    )


def create_site(**overrides):
    return get_success_data(
        api_client.create_alternate_care_site(create_alternate_care_site_payload(**overrides), LC),
        201,
    )


def commit_site(site_id, incident_id, window_start="2026-07-31T00:00:00Z",
                window_end="2026-08-05T00:00:00Z"):
    return get_success_data(
        api_client.commit_site_window(
            site_id,
            create_site_commitment_payload(incident_id, window_start, window_end),
            IC,
        )
    )


def create_patient(incident_id, patient_ref, **overrides):
    return get_success_data(
        api_client.create_patient_record(
            create_patient_record_payload(incident_id, patient_ref, **overrides), PC
        ),
        201,
    )


def create_inquiry(incident_id, sought_patient_ref, **overrides):
    return get_success_data(
        api_client.create_family_inquiry(
            create_family_inquiry_payload(incident_id, sought_patient_ref, **overrides), PIO
        ),
        201,
    )


# ─── Tier 2: identity pairs for segregation-of-duties flows ──

def create_manager_admin_pair():
    """Two roster-anchored identities: a drafting EmergencyManager and an
    approving HospitalAdministrator (PRD §2.7 SoD participants)."""
    manager = create_staff_member(full_name="Duty Manager", department="ADMINISTRATION")
    admin = create_staff_member(full_name="Duty Administrator", department="ADMINISTRATION")
    return manager, admin


def create_plan_draft(creator_id=None, **overrides):
    headers = make_emergency_manager_headers(creator_id) if creator_id else EM
    return get_success_data(
        api_client.create_plan_revision(create_plan_revision_payload(**overrides), headers), 201
    )


def submit_plan_for_review(plan_id, user_id=None):
    headers = make_emergency_manager_headers(user_id) if user_id else EM
    return get_success_data(api_client.submit_plan_review(plan_id, headers))


def approve_plan(plan_id, approver_id):
    return get_success_data(
        api_client.approve_plan_revision(
            plan_id, make_hospital_administrator_headers(approver_id)
        )
    )


def create_approved_plan(**overrides):
    """Full plan cycle through APPROVED. Returns (plan, context) where context
    carries the creator and approver staff rows."""
    manager, admin = create_manager_admin_pair()
    plan = create_plan_draft(creator_id=manager["id"], **overrides)
    submit_plan_for_review(plan["id"], user_id=manager["id"])
    approved = approve_plan(plan["id"], admin["id"])
    return approved, {"creator": manager, "approver": admin}


# ─── Tier 3: exercises ────────────────────────────────

def create_exercise_for_plan(plan_id, **overrides):
    return get_success_data(
        api_client.create_exercise(create_exercise_payload(plan_id, **overrides), EM), 201
    )


def create_started_exercise(**overrides):
    """Approved plan + exercise started (IN_PROGRESS)."""
    plan, ctx = create_approved_plan()
    exercise = create_exercise_for_plan(plan["id"], **overrides)
    started = get_success_data(api_client.start_exercise(exercise["id"], EM))
    return started, plan, ctx


# ─── Tier 4: after-action reports & improvement tasks ──

def create_incident_aar(summary="after-action findings"):
    """Demobilized incident + DRAFT AAR covering it. Returns (aar, incident)."""
    incident = create_and_demobilize_incident()
    aar = get_success_data(
        api_client.create_after_action_report(
            create_after_action_report_payload("INCIDENT", incident["id"], summary=summary), IC
        ),
        201,
    )
    return aar, incident


def create_open_task(**overrides):
    """DRAFT AAR on a demobilized incident + one OPEN improvement task.
    Returns (task, aar, incident)."""
    aar, incident = create_incident_aar()
    task = get_success_data(
        api_client.create_improvement_task(
            create_improvement_task_payload(aar["id"], **overrides), EM
        ),
        201,
    )
    return task, aar, incident


# ─── Tier 5: incidents with sites, patients, callbacks ──

def setup_incident_with_activated_site(bed_capacity=40, incident_overrides=None,
                                       window=WINDOW_COVERING_DEFAULT_CLOCK):
    """ACTIVATED incident + site COMMITTED (window covering the startup clock)
    and ACTIVATED in service of the incident. Returns (incident, site)."""
    incident = create_incident(**(incident_overrides or {}))
    site = create_site(bed_capacity=bed_capacity)
    commit_site(site["id"], incident["id"], window[0], window[1])
    activated = get_success_data(api_client.activate_site(site["id"], IC))
    return incident, activated


def create_explicit_callback(incident_id, staff_id, **overrides):
    """Explicit-mode call-back create; response is always an array (PRD §3.5),
    so the single created request is returned."""
    data = get_success_data(
        api_client.create_callback_request(
            create_callback_request_payload(incident_id, staff_member_id=staff_id, **overrides),
            PC,
        ),
        201,
    )
    assert isinstance(data, list) and len(data) == 1, "explicit create must return one request"
    return data[0]


def accept_callback(request_id, staff_id):
    return get_success_data(
        api_client.respond_callback_request(
            request_id, {"outcome": "ACCEPT"}, make_on_call_staff_headers(staff_id)
        )
    )


def create_transferred_patient(incident_id, site_id, patient_ref, **overrides):
    patient = create_patient(incident_id, patient_ref, **overrides)
    return get_success_data(
        api_client.transfer_patient(patient["id"], {"site_id": site_id}, PC)
    )


def create_matched_inquiry(incident_id, patient_ref, **patient_overrides):
    """TRACKED patient + OPEN inquiry + successful match.
    Returns (inquiry, patient)."""
    patient = create_patient(incident_id, patient_ref, **patient_overrides)
    inquiry = create_inquiry(incident_id, patient_ref)
    matched = get_success_data(
        api_client.match_family_inquiry(inquiry["id"], {"patient_record_id": patient["id"]}, PIO)
    )
    return matched, patient


# ─── Tier 6: burn-rate / surge scenarios ──────────────

def setup_item_with_in_window_ledger(reorder_min_days=13, receipts=((10, "2026-07-30T10:00:00Z"),),
                                     issues=((3, "2026-07-30T11:00:00Z"),), **item_overrides):
    """Supply item with a known in-window ledger. Default: RECEIVE 10 + ISSUE 3,
    netting to an observed daily burn of round_half_up(3/7, 4) = 0.4286."""
    item_overrides.setdefault("item_name", "N95 respirator")
    item_overrides.setdefault("category", "PPE")
    item_overrides.setdefault("unit", "box")
    item_overrides.setdefault("reorder_min_days", reorder_min_days)
    item = create_supply_item(**item_overrides)
    for qty, when in receipts:
        post_stock(item["id"], "RECEIVE", qty, when)
    for qty, when in issues:
        post_stock(item["id"], "ISSUE", qty, when)
    return item


def setup_item_under_yellow_tier():
    """Item with RECEIVE 10 / ISSUE 3 in-window plus an ACTIVATED incident
    assessed to YELLOW (surge multiplier 1.25). Returns (item, incident)."""
    item = setup_item_with_in_window_ledger()
    incident = create_incident(incident_name="MCI-burn", incident_type="INFECTIOUS")
    # 200 staffed beds, census 170: 100*170 = 17000 >= 85*200 → YELLOW.
    assess_surge(incident["id"], 200, 170)
    return item, incident


def setup_site_cascade_scenario():
    """Full capacity-cascade stage: item with observed burn 0.4286; incident
    ACTIVATED; 40-bed site ACTIVATED for it; assessment 200/170 yields
    operational capacity 240 and tier GREEN. Returns (item, incident, site)."""
    item = setup_item_with_in_window_ledger()
    incident, site = setup_incident_with_activated_site(
        bed_capacity=40, incident_overrides={"incident_name": "MCI-cascade"}
    )
    assessed = assess_surge(incident["id"], 200, 170)
    return item, assessed, site


# ─── Tier 7: reporting ────────────────────────────────

def create_external_report(creator_id=None, **overrides):
    headers = make_liaison_officer_headers(creator_id) if creator_id else LO
    return get_success_data(
        api_client.create_external_report(create_external_report_payload(**overrides), headers),
        201,
    )


def create_command_assignment(incident_id, staff_id, command_role, expected_version):
    return get_success_data(
        api_client.create_command_assignment(
            create_command_assignment_payload(
                incident_id, staff_id, command_role, expected_version
            ),
            IC,
        ),
        201,
    )
