"""Corner Coverage — state_machines section.

Initial-state defaults, terminal-state lockdown, auto-transitions, HEP
supersession, and the POC → VeteranReferral activation cascade.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    set_clock,
    setup_active_poc,
    setup_active_va_poc,
    setup_poc_with_grant,
    create_grant,
    schedule_visit,
    complete_visit,
    finalize_visit,
    create_patient,
    create_therapist,
    create_draft_poc,
    record_initial_evaluation,
    activate_poc,
    record_discharge_assessment,
    discharge_poc,
    create_hep,
    make_therapist_headers,
    TEST_USERS,
)


def test_poc_initial_state_is_draft_on_create(api):
    """PRD §3.2: "The plan is persisted at `status` `DRAFT` and `capped_status`
    `UNDER_CAP`"

    Design: Corner/state_machines/poc_initial_state_is_draft_on_create
    """
    set_clock("2026-06-01T00:00:00Z")
    th = create_therapist(license_state="CA", full_name="T Init")
    pt = create_patient(insurance_type="COMMERCIAL", full_name="Pat Init",
                        date_of_birth="1970-01-01")
    poc = create_draft_poc(pt["id"], th["id"])
    assert poc["status"] == "DRAFT"


def test_poc_terminal_discharged_no_further_transitions(api):
    """PRD §3.6: "Active plans can also be discharged explicitly."
    PRD §2.11: "current-state preconditions (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/poc_terminal_discharged_no_further_transitions
    """
    ctx = setup_active_poc(insurance_type="COMMERCIAL")
    th = ctx["therapist"]["id"]
    record_discharge_assessment(ctx["poc"]["id"], th,
                                final_functional_score=60, goals_met_count=5,
                                total_goals_count=10, assessed_on="2026-06-10")
    discharged = discharge_poc(ctx["poc"]["id"], th)
    assert discharged["status"] == "DISCHARGED"
    # Second discharge attempt should be ERR_INVALID_STATE.
    res = api.discharge_plan_of_care(ctx["poc"]["id"], make_therapist_headers(th))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_visit_cancel_after_finalize_returns_invalid_state(api):
    """PRD §3.5: "Once a visit reaches `FINALIZED`, `CANCELLED`, or `NO_SHOW`, no
    further transitions are available."

    Design: Corner/state_machines/visit_cancel_after_finalize_returns_invalid_state
    """
    ctx = setup_poc_with_grant(insurance_type="MEDICARE", medicare_enrolled=True,
                               total_units_granted=10)
    th = ctx["therapist"]["id"]
    v = schedule_visit(
        ctx["grant"]["id"], th,
        "2026-06-02T09:00:00Z", "2026-06-02T09:30:00Z",
        planned_minutes=30, cpt_code="CPT_97110_THER_EX",
    )
    complete_visit(v["id"], th, actual_minutes=30)
    finalize_visit(v["id"], ctx["poc"]["id"])
    # Cancel a FINALIZED visit → ERR_INVALID_STATE.
    res = api.cancel_visit(v["id"], make_therapist_headers(th))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_visit_initial_state_is_scheduled_on_create(api):
    """PRD §3.5: "A new visit is persisted at `status` `SCHEDULED` with `actual_minutes`
    left null and `billable_units` and `billed_cents` both zero."

    Design: Corner/state_machines/visit_initial_state_is_scheduled_on_create
    """
    ctx = setup_poc_with_grant(insurance_type="COMMERCIAL", total_units_granted=10)
    v = schedule_visit(
        ctx["grant"]["id"], ctx["therapist"]["id"],
        "2026-06-02T09:00:00Z", "2026-06-02T09:30:00Z",
        planned_minutes=30, cpt_code="CPT_97110_THER_EX",
    )
    assert v["status"] == "SCHEDULED"


def test_hep_supersedes_prior_active_hep_on_same_poc(api):
    """PRD §3.7: "Prescribing a new program automatically supersedes any prior
    `ACTIVE` program on the same plan: each prior `ACTIVE` row transitions to
    `SUPERSEDED` (with `updated_at` refreshed and `version` incremented), and the
    new row is persisted at `status` `ACTIVE`."

    Design: Corner/state_machines/hep_supersedes_prior_active_hep_on_same_poc
    """
    ctx = setup_active_poc(insurance_type="COMMERCIAL")
    th = ctx["therapist"]["id"]
    poc_id = ctx["poc"]["id"]
    hep1 = create_hep(poc_id, th, prescribed_on="2026-06-02",
                      exercise_count=4, weekly_frequency=3)
    hep2 = create_hep(poc_id, th, prescribed_on="2026-06-05",
                      exercise_count=6, weekly_frequency=5)
    hep1_after = validate_success(
        api.get_home_exercise_program(hep1["id"], make_therapist_headers(th)), 200,
    )
    hep2_after = validate_success(
        api.get_home_exercise_program(hep2["id"], make_therapist_headers(th)), 200,
    )
    assert hep1_after["status"] == "SUPERSEDED"
    assert hep2_after["status"] == "ACTIVE"


def test_poc_activate_cascades_va_referral_to_consumed(api):
    """PRD §3.2: "First, the linked `VeteranReferral` transitions from `ISSUED` to
    `CONSUMED` — its own `version` increments and its `updated_at` refreshes."

    Design: Corner/state_machines/poc_activate_cascades_va_referral_to_consumed
    """
    ctx = setup_active_va_poc(
        is_veteran=True,
        max_authorized_visits=20,
        referral_expires_on="2026-12-31",
    )
    referral_after = validate_success(
        api.get_veteran_referral(ctx["referral"]["id"], TEST_USERS["va_coordinator_headers"]),
        200,
    )
    assert ctx["poc"]["status"] == "ACTIVE"
    assert referral_after["status"] == "CONSUMED"


def test_poc_clock_auto_transition_active_to_recert_due(api):
    """PRD §3.6: "A plan in `ACTIVE` status reaches `RECERT_DUE` automatically when
    the server clock advances to a date strictly after `certified_end_date` minus seven
    days and on or before `certified_end_date`."

    Design: Corner/state_machines/poc_clock_auto_transition_active_to_recert_due
    """
    ctx = setup_active_poc(
        insurance_type="COMMERCIAL",
        certified_start_date="2026-06-01",
        certified_end_date="2026-06-08",
    )
    set_clock("2026-06-04T12:00:00Z")
    poc = validate_success(
        api.get_plan_of_care(ctx["poc"]["id"], make_therapist_headers(ctx["therapist"]["id"])),
        200,
    )
    assert poc["status"] == "RECERT_DUE"
