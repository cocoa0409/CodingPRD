"""Enrollment activation, coverage-interval overlap, the ACTIVE/redetermination
coverage cycle, and the immediate ledger visibility after activation.
"""
from test_helpers import (
    api_client as api,
    TEST_USERS,
    get_success_data, validate_success, validate_error, ApiErrorId,
    setup_config, open_application,
    setup_eligible_approved_application, setup_active_enrollment,
    setup_in_redetermination,
)

CW = TEST_USERS["caseworker_headers"]
APP = TEST_USERS["applicant_headers"]


def _approve_pipeline(hh_id, name="Mem"):
    """Build a member + income + approved application under hh_id, return app id."""
    mem = get_success_data(api.add_member(
        hh_id, {"full_name": name, "age": 30, "relationship": "SELF"}, CW))
    api.add_income_source(mem["id"], {"income_type": "WAGES", "monthly_amount_cents": 120000}, CW)
    app = open_application(hh_id, magi_variant="POINT_IN_TIME")
    api.submit_application(app["id"], APP)
    api.claim_review(app["id"], CW)
    api.run_determination(app["id"], CW)
    api.verify_application(app["id"], CW)
    api.decide_application(app["id"], {"target_status": "APPROVED"}, CW)
    return app["id"]


# ===========================================================================
# Queue A — cross_entity_state_dependency (Enrollment -> Application)
# ===========================================================================
def test_enrollment_activate_requires_application_approved():
    """PRD §3.7: "It requires that the linked application's `review_status` be
    `APPROVED`; activating against an application that is not approved is rejected
    with `ERR_APPLICATION_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_requires_application_approved
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Not Approved"}, CW))
    mem = get_success_data(api.add_member(
        hh["id"], {"full_name": "Not Approved", "age": 30, "relationship": "SELF"}, CW))
    api.add_income_source(mem["id"], {"income_type": "WAGES", "monthly_amount_cents": 120000}, CW)
    app = open_application(hh["id"], magi_variant="POINT_IN_TIME")
    api.submit_application(app["id"], APP)
    api.claim_review(app["id"], CW)  # only UNDER_REVIEW, not APPROVED
    enr = get_success_data(api.create_enrollment(
        {"household_id": hh["id"], "application_id": app["id"],
         "coverage_start": "2026-01-01T00:00:00Z", "coverage_end": "2026-12-31T00:00:00Z",
         "redetermination_due": "2026-11-01T00:00:00Z"}, CW))

    resp = api.activate_enrollment(enr["id"], CW)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_APPROVED.value)
    still = validate_success(api.get_enrollment(enr["id"], CW))
    assert still["coverage_status"] == "PENDING"


def test_enrollment_activation_succeeds_when_application_approved():
    """PRD §3.7: "On success the enrollment moves from `PENDING` to `ACTIVE`, its
    `member_months` is fixed at the household's `household_size` at this moment
    multiplied by twelve".

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_requires_application_approved
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Approved A"}, CW))
    app_id = _approve_pipeline(hh["id"], "Approved A")
    enr = get_success_data(api.create_enrollment(
        {"household_id": hh["id"], "application_id": app_id,
         "coverage_start": "2026-01-01T00:00:00Z", "coverage_end": "2026-12-31T00:00:00Z",
         "redetermination_due": "2026-11-01T00:00:00Z"}, CW))
    activated = validate_success(api.activate_enrollment(enr["id"], CW))
    assert activated["coverage_status"] == "ACTIVE"
    assert activated["member_months"] == 12  # household_size 1 * 12


# ===========================================================================
# Queue A — resource_temporal_overlap (closed coverage interval)
# ===========================================================================
def test_enrollment_coverage_closed_interval_overlap_rejected():
    """PRD §3.7: "It also requires that the new coverage interval not intersect
    the closed coverage interval of any other enrollment of the same household
    whose `coverage_status` is `ACTIVE` or `IN_REDETERMINATION`; an overlapping
    activation is rejected with `ERR_COVERAGE_OVERLAP`."
    PRD §3.7: "`coverage_start` and `coverage_end` are ISO 8601 UTC dates bounding
    a closed coverage interval (both endpoints inclusive)".

    Design: Difficulty/resource_temporal_overlap/enrollment_coverage_closed_interval_overlap_rejected
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Olive Lap"}, CW))
    app1 = _approve_pipeline(hh["id"], "Olive Lap")
    enr1 = get_success_data(api.create_enrollment(
        {"household_id": hh["id"], "application_id": app1,
         "coverage_start": "2026-01-01T00:00:00Z", "coverage_end": "2026-06-30T00:00:00Z",
         "redetermination_due": "2026-06-01T00:00:00Z"}, CW))
    api.activate_enrollment(enr1["id"], CW)

    app2 = _approve_pipeline(hh["id"], "Olive Lap 2")
    enr2 = get_success_data(api.create_enrollment(
        {"household_id": hh["id"], "application_id": app2,
         "coverage_start": "2026-06-30T00:00:00Z", "coverage_end": "2026-12-31T00:00:00Z",
         "redetermination_due": "2026-11-01T00:00:00Z"}, CW))

    resp = api.activate_enrollment(enr2["id"], CW)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_OVERLAP.value)
    still = validate_success(api.get_enrollment(enr2["id"], CW))
    assert still["coverage_status"] == "PENDING"


def test_non_overlapping_coverage_intervals_both_activate():
    """PRD §3.7: "It also requires that the new coverage interval not intersect
    the closed coverage interval of any other enrollment of the same household
    whose `coverage_status` is `ACTIVE` or `IN_REDETERMINATION`".

    A second interval that starts strictly after the first ends does not collide.

    Design: Difficulty/resource_temporal_overlap/enrollment_coverage_closed_interval_overlap_rejected
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Gap G"}, CW))
    app1 = _approve_pipeline(hh["id"], "Gap G")
    enr1 = get_success_data(api.create_enrollment(
        {"household_id": hh["id"], "application_id": app1,
         "coverage_start": "2026-01-01T00:00:00Z", "coverage_end": "2026-06-30T00:00:00Z",
         "redetermination_due": "2026-06-01T00:00:00Z"}, CW))
    api.activate_enrollment(enr1["id"], CW)

    app2 = _approve_pipeline(hh["id"], "Gap G2")
    enr2 = get_success_data(api.create_enrollment(
        {"household_id": hh["id"], "application_id": app2,
         "coverage_start": "2026-07-01T00:00:00Z", "coverage_end": "2026-12-31T00:00:00Z",
         "redetermination_due": "2026-11-01T00:00:00Z"}, CW))
    activated = validate_success(api.activate_enrollment(enr2["id"], CW))
    assert activated["coverage_status"] == "ACTIVE"


# ===========================================================================
# Queue A — non_linear_state_machine (enrollment cycle)
# ===========================================================================
def test_enrollment_cyclic_active_redetermination_active():
    """PRD §3.7: "Opening a redetermination drives the enrollment from `ACTIVE`
    to `IN_REDETERMINATION`. When the redetermination's review concludes
    favorably (it reaches `RENEWED`), the system cascades the enrollment back from
    `IN_REDETERMINATION` to `ACTIVE`, closing the cycle with no ledger change."

    Design: Difficulty/non_linear_state_machine/enrollment_cyclic_active_redetermination_active
    """
    hh, app, enr, redet, _det = setup_in_redetermination(state="CA", make_ineligible=False)
    # Confirm we are mid-cycle in IN_REDETERMINATION.
    mid = validate_success(api.get_enrollment(enr["id"], CW))
    assert mid["coverage_status"] == "IN_REDETERMINATION"

    finalized = validate_success(api.finalize_redetermination(
        redet["id"], {"target_status": "RENEWED"}, CW))
    assert finalized["redet_status"] == "RENEWED"
    enr_after = validate_success(api.get_enrollment(enr["id"], CW))
    assert enr_after["coverage_status"] == "ACTIVE"


def test_renewal_closes_cycle_with_no_ledger_change():
    """PRD §3.7: "the system cascades the enrollment back from
    `IN_REDETERMINATION` to `ACTIVE`, closing the cycle with no ledger change."

    Design: Difficulty/non_linear_state_machine/enrollment_cyclic_active_redetermination_active
    """
    hh, app, enr, redet, _det = setup_in_redetermination(state="CA", make_ineligible=False)
    before = validate_success(api.get_household(hh["id"], CW))
    api.finalize_redetermination(redet["id"], {"target_status": "RENEWED"}, CW)
    after = validate_success(api.get_household(hh["id"], CW))
    assert after["covered_member_months"] == before["covered_member_months"]
    assert after["active_enrollment_count"] == before["active_enrollment_count"]


# ===========================================================================
# Queue B — consistency_model
# ===========================================================================
def test_activation_ledger_visible_in_same_response():
    """PRD §3.7: "that `member_months` quantity is credited to the household's
    `covered_member_months`, and the household's `active_enrollment_count` rises
    by one."

    Design: Corner/consistency_model/activation_ledger_visible_in_same_response
    """
    hh, app, enr, _member = setup_active_enrollment(state="CA")
    fresh = validate_success(api.get_household(hh["id"], CW))
    assert fresh["covered_member_months"] == 12  # size 1 * 12
    assert fresh["active_enrollment_count"] == 1
