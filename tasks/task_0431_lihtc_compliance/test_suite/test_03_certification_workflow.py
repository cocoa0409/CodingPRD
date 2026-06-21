"""Income-certification lifecycle: drafting, submission gates, approval, and the student rule.

Translates queue A (Difficulty) instances dual_variant_calc/income_eligibility and
priority_pair_validation_conflict/student_rule_beats_income_limit, plus queue B (Corner)
certification state-machine instances.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    setup_project_building,
    create_unit,
    create_household,
    create_approved_certification,
)
from test_helpers import api_client

OWNER = TEST_USERS["owner_agent_headers"]
HFA = TEST_USERS["state_hfa_headers"]


def _ami50_unit_with_household(student=False, exception=None):
    """Project + building + AMI_50 br1 unit (income_limit 3_840_000) + household.
    Returns (unit, household)."""
    project, building = setup_project_building()
    unit = create_unit(
        building["id"],
        unit_number="U1",
        bedroom_count=1,
        sqft=1_000,
        utility_allowance_cents=9_000,
        ami_designation="AMI_50",
    )
    hh_kwargs = {"all_full_time_students": student}
    if exception is not None:
        hh_kwargs["student_exception"] = exception
    household = create_household(project["id"], **hh_kwargs)
    return unit, household


def _create_cert(household_id, unit_id, **overrides):
    payload = {
        "household_id": household_id,
        "unit_id": unit_id,
        "cert_type": "INITIAL",
        "annual_income_cents": 3_000_000,
        "effective_date": "2026-01-15T00:00:00Z",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_certification(payload, OWNER))


# ─── Difficulty: INITIAL income limit vs RECERT 140% threshold ──

def test_initial_cert_over_income_limit_rejected_on_submit(api):
    """PRD §3.3: "Second, for an `INITIAL` certification only, the certified
    `annual_income_cents` must not exceed the unit's `income_limit_cents` for its designation
    and bedroom count; if the income is above that limit, the submission is rejected with
    `ERR_INCOME_OVER_LIMIT`."

    Design: Difficulty/dual_variant_calc/income_eligibility_initial_limit_vs_recert_140_threshold
    """
    unit, household = _ami50_unit_with_household()
    # First qualify the unit so a RECERT is later valid (and to isolate this INITIAL).
    create_approved_certification(
        household["id"], unit["id"], cert_type="INITIAL", annual_income_cents=3_000_000
    )
    cert = _create_cert(
        household["id"], unit["id"], cert_type="INITIAL",
        annual_income_cents=5_000_000, effective_date="2026-02-15T00:00:00Z",
    )
    res = api.submit_certification(cert["id"], OWNER)
    validate_error(res, "ERR_INCOME_OVER_LIMIT", expected_status=422)


def test_recert_above_initial_limit_but_below_140_submits(api):
    """PRD §3.3: "(A `RECERT` is not subject to the move-in income limit at submit;
    over-income on recertification is handled through the over-income threshold below rather
    than by blocking submission.)"
    PRD §3.3: "The `is_over_income` flag is set true only when the `cert_type` is `RECERT` and
    the certified `annual_income_cents` is strictly greater than `over_income_threshold_cents`;
    income exactly equal to 140 percent of the limit is not over-income, because the boundary
    is strict."

    Design: Difficulty/dual_variant_calc/income_eligibility_initial_limit_vs_recert_140_threshold
    """
    unit, household = _ami50_unit_with_household()
    create_approved_certification(
        household["id"], unit["id"], cert_type="INITIAL", annual_income_cents=3_000_000
    )
    cert = _create_cert(
        household["id"], unit["id"], cert_type="RECERT",
        annual_income_cents=5_000_000,  # > limit 3_840_000 but <= over140 5_376_000
        effective_date="2027-01-15T00:00:00Z",
    )
    submitted = validate_success(api.submit_certification(cert["id"], OWNER), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["over_income_threshold_cents"] == 5_376_000
    assert submitted["is_over_income"] is False


# ─── Difficulty: student rule beats income limit (explicit "First/Second") ──

def test_student_ineligible_reported_when_both_student_and_income_fail(api):
    """PRD §3.3: "First, the certified household must be student-eligible; if the household's
    `student_eligible` is false, the submission is rejected with `ERR_STUDENT_INELIGIBLE`.
    Second, for an `INITIAL` certification only, the certified `annual_income_cents` must not
    exceed the unit's `income_limit_cents` for its designation and bedroom count; if the
    income is above that limit, the submission is rejected with `ERR_INCOME_OVER_LIMIT`."

    Design: Difficulty/priority_pair_validation_conflict/student_rule_beats_income_limit_on_submit
    """
    unit, household = _ami50_unit_with_household(student=True, exception="NONE")
    cert = _create_cert(
        household["id"], unit["id"], cert_type="INITIAL",
        annual_income_cents=9_000_000,  # also over the limit 3_840_000
    )
    res = api.submit_certification(cert["id"], OWNER)
    validate_error(res, "ERR_STUDENT_INELIGIBLE", expected_status=422)
    after = get_success_data(api.get_certification(cert["id"], OWNER))
    assert after["status"] == "DRAFT"


def test_student_ineligible_blocks_submit_even_with_income_within_limit(api):
    """PRD §3.3: "First, the certified household must be student-eligible; if the household's
    `student_eligible` is false, the submission is rejected with `ERR_STUDENT_INELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/student_rule_beats_income_limit_on_submit
    """
    unit, household = _ami50_unit_with_household(student=True, exception="NONE")
    cert = _create_cert(
        household["id"], unit["id"], cert_type="INITIAL",
        annual_income_cents=3_000_000,  # within the limit 3_840_000
    )
    res = api.submit_certification(cert["id"], OWNER)
    validate_error(res, "ERR_STUDENT_INELIGIBLE", expected_status=422)
    after = get_success_data(api.get_certification(cert["id"], OWNER))
    assert after["status"] == "DRAFT"


# ─── Corner: certification state machine ──────────────

def test_certification_initial_state_is_draft(api):
    """PRD §3.3: "A new certification is created in `DRAFT` status."

    Design: Corner/state_machines/certification_initial_state_is_draft
    """
    unit, household = _ami50_unit_with_household()
    cert = _create_cert(household["id"], unit["id"])
    fetched = get_success_data(api.get_certification(cert["id"], OWNER))
    assert fetched["status"] == "DRAFT"


def test_approve_certification_in_draft_returns_invalid_state(api):
    """PRD §3.3: "A `StateHFA` decides a `SUBMITTED` certification by approving or rejecting
    it, supplying a `decision` in the request body."
    PRD §4: "All other state-changing operations — the action endpoints that drive
    transitions, and the logical-clock set — return a `200 OK` status code."

    Design: Corner/state_machines/approve_certification_in_draft_returns_invalid_state
    """
    unit, household = _ami50_unit_with_household()
    cert = _create_cert(household["id"], unit["id"])  # never submitted, still DRAFT
    res = api.approve_certification(cert["id"], {"decision": "APPROVE"}, HFA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = get_success_data(api.get_certification(cert["id"], OWNER))
    assert after["status"] == "DRAFT"


def test_revise_returns_submitted_cert_to_draft(api):
    """PRD §3.3: "An `OwnerAgent` may send a `SUBMITTED` certification back to `DRAFT` with a
    revise action, which simply returns the certification to `DRAFT` so it can be edited and
    resubmitted."

    Design: Corner/state_machines/revise_returns_submitted_cert_to_draft
    """
    unit, household = _ami50_unit_with_household()
    cert = _create_cert(household["id"], unit["id"])
    get_success_data(api.submit_certification(cert["id"], OWNER))
    revised = validate_success(api.revise_certification(cert["id"], OWNER), 200)
    assert revised["status"] == "DRAFT"


def test_certification_reject_decision_sets_rejected_unit_unchanged(api):
    """PRD §3.3: "A decision to reject moves the certification to `REJECTED` and changes no
    unit state."

    Design: Corner/state_machines/certification_reject_decision_sets_rejected
    """
    unit, household = _ami50_unit_with_household()
    cert = _create_cert(household["id"], unit["id"])
    get_success_data(api.submit_certification(cert["id"], OWNER))
    rejected = validate_success(
        api.approve_certification(cert["id"], {"decision": "REJECT"}, HFA), 200
    )
    assert rejected["status"] == "REJECTED"
    unit_after = get_success_data(api.get_unit(unit["id"], OWNER))
    assert unit_after["li_status"] == "VACANT_NEVER_OCCUPIED"
