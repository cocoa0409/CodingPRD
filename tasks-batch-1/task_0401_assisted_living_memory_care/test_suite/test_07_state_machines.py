"""State-machine coverage: invalid transitions, terminal-state lockdown, valid transitions
(rescind, license reinstate, care-plan revision), initial state, the IJ poc-window calc, and
the discharge preconditions (zero balance, discontinued med orders, state-reportable escalate).

Citations are verbatim from PRD.md §2.8, §2.9, §3.1, §3.3, §3.4, §3.6, §3.8, §3.9, §3.10.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_facility, create_resident,
    create_resident_with_finalized_assessment, setup_active_agreement,
    setup_discharge_pending_resident, setup_discharged_resident,
    setup_admitted_resident, setup_resident_with_active_care_plan,
    create_care_plan, setup_incident_under_investigation, create_statement,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]
CLINICAL = TEST_USERS["clinical_director_headers"]
NURSE = TEST_USERS["nurse_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
STAFF = TEST_USERS["staff_headers"]

_LEVEL_2_ASMT = {
    "adl_bathing": 2, "adl_dressing": 2, "adl_toileting": 2,
    "adl_transferring": 2, "adl_eating": 2, "cognition_score": 0, "behavior_flags": 0,
}


def test_finalize_already_finalized_assessment_returns_invalid_state(api):
    """PRD §3.3: "Finalizing is only legal when the assessment is `DRAFT` and the owning
    resident is not `DISCHARGED`; otherwise it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/finalize_already_finalized_assessment_returns_invalid_state
    """
    fac, res, asmt = create_resident_with_finalized_assessment()
    res_now = validate_success(api.get_resident(res["id"], STAFF), 200)
    resp = api.finalize_assessment(asmt["id"], {"expected_resident_version": res_now["version"]}, CLINICAL)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_active_agreement_returns_invalid_state(api):
    """PRD §3.5: "An agreement moves through `DRAFT → ACTIVE → TERMINATED`, or
    `DRAFT → CANCELLED`."
    PRD §2.8: "an attempt to drive a transition from any other state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_active_agreement_returns_invalid_state
    """
    ctx = setup_active_agreement(care_point_rate_cents=2000, base_rent_cents=400000, move_in_date="2026-06-01")
    resp = api.cancel_move_in_agreement(ctx["agreement"]["id"], REGISTRAR)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


def test_discharged_resident_is_terminal_admit_rejected(api):
    """PRD §3.6: "`DISCHARGED` is terminal."
    PRD §2.8: "an attempt to drive a transition from any other state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/discharged_resident_is_terminal_admit_rejected
    """
    ctx = setup_discharged_resident(disposition="OTHER", care_point_rate_cents=2000,
                                    base_rent_cents=400000, move_in_date="2026-06-01")
    resp = api.admit_resident(ctx["resident"]["id"], REGISTRAR)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


def test_rescind_discharge_returns_to_admitted(api):
    """PRD §3.6: "While in `DISCHARGE_PENDING`, a `Registrar` may rescind, advancing the resident
    `DISCHARGE_PENDING → ADMITTED` with no further side effects."

    Design: Corner/state_machines/rescind_discharge_returns_to_admitted
    """
    ctx = setup_discharge_pending_resident(care_point_rate_cents=2000, base_rent_cents=400000,
                                           move_in_date="2026-06-01")
    rescinded = validate_success(api.rescind_discharge(ctx["resident"]["id"], REGISTRAR), 200)
    assert rescinded["status"] == "ADMITTED"
    unit = validate_success(api.get_unit(ctx["unit"]["id"], STAFF), 200)
    assert unit["status"] == "OCCUPIED"
    assert unit["current_resident_id"] == ctx["resident"]["id"]


def test_newly_created_resident_starts_prospect(api):
    """PRD §3.2: "A freshly registered resident begins in status `PROSPECT`, with
    `current_care_points` and `open_balance_cents` both zero and `current_care_level` null until
    the first assessment is finalized."

    Design: Corner/state_machines/newly_created_resident_starts_prospect
    """
    fac = create_facility()
    res = validate_success(api.create_resident(
        {"facility_id": fac["id"], "full_name": "Init Ida", "date_of_birth": "1948-01-01"}, REGISTRAR), 201)
    assert res["status"] == "PROSPECT"
    assert res["current_care_points"] == 0
    assert res["open_balance_cents"] == 0
    assert res["current_care_level"] is None


def test_care_plan_revision_supersedes_prior_active_self_referential(api):
    """PRD §3.4: "If the activated plan names a prior plan in its `supersedes_care_plan_id`, that
    prior plan is automatically transitioned `ACTIVE → SUPERSEDED` as part of the activation, so
    a resident has at most one active plan at a time."

    Design: Corner/state_machines/care_plan_revision_supersedes_prior_active_self_referential
    """
    ctx = setup_resident_with_active_care_plan()
    cp1 = ctx["care_plan"]
    cp2 = create_care_plan(
        ctx["resident"]["id"], ctx["assessment"]["id"], supersedes_care_plan_id=cp1["id"],
        adl_support_items=[{"task": "dressing", "frequency_per_day": 2}])
    activated2 = validate_success(api.activate_care_plan(cp2["id"], CLINICAL), 200)
    assert activated2["status"] == "ACTIVE"
    cp1_after = validate_success(api.get_care_plan(cp1["id"], STAFF), 200)
    assert cp1_after["status"] == "SUPERSEDED"


def test_poc_due_date_immediate_jeopardy_window(api):
    """PRD §3.10: "when the scope/severity band is `J_L_IMMEDIATE_JEOPARDY` the window is two
    calendar days, and for every other band the window is ten calendar days; the `poc_due_date`
    is the calendar date of `cited_at` plus the selected number of days."

    Design: Corner/state_machines/poc_due_date_immediate_jeopardy_window
    """
    fac = create_facility(creator=COMPLIANCE)
    deff = validate_success(api.create_deficiency(
        fac["id"], {"tag_code": "F-323", "scope_severity": "J_L_IMMEDIATE_JEOPARDY",
                    "cited_at": "2026-03-05T10:00:00Z"}, COMPLIANCE), 201)
    assert deff["status"] == "CITED"
    # cited 2026-03-05 + 2 IJ days = 2026-03-07.
    assert deff["poc_due_date"] == "2026-03-07"


def test_discharge_pending_requires_zero_balance(api):
    """PRD §3.6: "Initiation is only legal from `ADMITTED`, and it additionally requires that the
    resident's `open_balance_cents` be exactly zero; a resident who still owes money cannot begin
    discharge and is rejected with `ERR_OUTSTANDING_BALANCE`."

    Design: Corner/state_machines/discharge_pending_requires_zero_balance
    """
    ctx = setup_admitted_resident(care_point_rate_cents=1500, base_rent_cents=401500,
                                  move_in_date="2026-09-15", assessment_overrides=_LEVEL_2_ASMT)
    stmt = create_statement(ctx["resident"]["id"], 2026, 11, is_first_statement=False)
    validate_success(api.issue_billing_statement(stmt["id"], BILLING), 200)
    res = validate_success(api.get_resident(ctx["resident"]["id"], STAFF), 200)
    assert res["open_balance_cents"] == 446500
    resp = api.initiate_discharge(ctx["resident"]["id"], REGISTRAR)
    validate_error(resp, "ERR_OUTSTANDING_BALANCE", expected_status=409)


def test_finalize_discharge_requires_discontinued_med_orders(api):
    """PRD §3.6: "Finalization is only legal from `DISCHARGE_PENDING` and additionally requires
    that every medication order for the resident already be `DISCONTINUED`; if any order is still
    active the request is rejected with `ERR_ACTIVE_MED_ORDERS`."

    Design: Corner/state_machines/finalize_discharge_requires_discontinued_med_orders
    """
    ctx = setup_admitted_resident(care_point_rate_cents=2000, base_rent_cents=400000,
                                  move_in_date="2026-06-01")
    get_success_data(api.create_medication_order(
        {"resident_id": ctx["resident"]["id"], "drug_name": "Metformin", "dose": "500 mg",
         "schedule_times": ["09:00"]}, NURSE))
    validate_success(api.initiate_discharge(ctx["resident"]["id"], REGISTRAR), 200)
    resp = api.finalize_discharge(ctx["resident"]["id"], {"disposition": "TRANSFER_TO_SNF"}, REGISTRAR)
    validate_error(resp, "ERR_ACTIVE_MED_ORDERS", expected_status=409)


def test_escalate_non_reportable_incident_rejected(api):
    """PRD §3.9: "Escalation is only legal when the incident is `UNDER_INVESTIGATION` and
    additionally requires that `requires_state_report` be true; escalating an incident that is
    not state-reportable is rejected with `ERR_NOT_STATE_REPORTABLE`."

    Design: Corner/state_machines/escalate_non_reportable_incident_rejected
    """
    ctx = setup_incident_under_investigation(severity="MINOR", incident_type="FALL")
    resp = api.escalate_incident(
        ctx["incident"]["id"],
        {"scope_severity": "A_C_NO_HARM", "tag_code": "F-689", "cited_at": "2026-03-02T10:00:00Z"},
        COMPLIANCE)
    validate_error(resp, "ERR_NOT_STATE_REPORTABLE", expected_status=409)


def test_license_reinstate_cycle_suspended_to_active(api):
    """PRD §2.9: "reinstating it returns either `SUSPENDED` or `CONDITIONAL` to `ACTIVE`. Each
    such action increments the facility's `version` by one."

    Design: Corner/state_machines/license_reinstate_cycle_suspended_to_active
    """
    fac = create_facility(creator=COMPLIANCE)  # version 1
    suspended = validate_success(api.license_action(
        fac["id"], {"action": "SUSPEND", "expected_facility_version": fac["version"]}, COMPLIANCE), 200)  # version 2
    reinstated = validate_success(api.license_action(
        fac["id"], {"action": "REINSTATE", "expected_facility_version": suspended["version"]}, COMPLIANCE), 200)  # version 3
    assert reinstated["license_status"] == "ACTIVE"
    assert reinstated["version"] == 3
