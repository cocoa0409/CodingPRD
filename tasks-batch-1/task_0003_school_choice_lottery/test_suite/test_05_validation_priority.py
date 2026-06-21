"""Tests for the fixed validation precedence (PRD §2.6): the first failing
rule dictates the rejection's `error_id`, and no later rule is evaluated for
that request. Two different priority pairs are exercised.
"""
from test_helpers import (
    set_clock,
    create_district,
    create_school,
    create_window,
    open_window,
    register_family,
    create_student,
    get_window,
    api_client,
    TEST_USERS,
    make_guardian_headers,
    validate_error,
    ApiErrorId,
)
from test_helpers.factories import (
    run_lottery_payload,
    create_application_payload,
)


# =====================================================================
# Difficulty rule 5 / instance 1 — state (priority 4) vs business_temporal
# (priority 5). State wins → ERR_INVALID_STATE.
# =====================================================================

def test_run_lottery_on_open_window_before_lottery_runs_at_returns_invalid_state(api):
    """PRD §2.6: "Authentication (the presence and validity of `X-User-ID`
    and `X-User-Role`) is checked first, then role authorization, then
    existence of every referenced id, then the resource state for
    state-transition endpoints, then temporal preconditions on
    enrollment-window timing, then district-archived checks against
    referenced districts, then ownership for guardian-initiated operations,
    then per-window application uniqueness, then grade-range fit, then
    optimistic-concurrency version checks, then request-body schema and
    range checks for school capacity, and finally district data-sanity
    checks at window-open time. The first rule that fails dictates the
    rejection's `error_id` and HTTP status, and no subsequent rule is
    evaluated for that request."
    PRD §3.2: "Running the lottery transitions the window from `CLOSED` to
    `LOTTERY_RUN`. The operation requires the clock to have reached
    `lottery_runs_at` and the window to be in `CLOSED`; either failure
    surfaces as `ERR_INVALID_STATE` or `ERR_WINDOW_TIMING` as appropriate."

    With a window in OPEN (not CLOSED) and the clock before lottery_runs_at,
    both the state precondition AND the timing precondition fail. The
    precedence order says state (priority 4) is checked before
    business_temporal (priority 5), so the response must carry
    ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_run_lottery_before_lottery_runs_at
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DPRI1", name="Prio1", poverty_index_pct=0.00)
    window = create_window(district["id"], cycle_label="2026-27-PRI1")
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    w = get_window(window["id"])
    res = api.run_lottery(
        window["id"],
        run_lottery_payload(w["version"]),
        TEST_USERS["district_admin_headers"],
    )
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] == ApiErrorId.ERR_INVALID_STATE.value


# =====================================================================
# Difficulty rule 5 / instance 2 — business_referential (priority 7) vs
# business_constraint (priority 8). Ownership wins → ERR_FORBIDDEN_OWNERSHIP.
# =====================================================================

def test_guardian_applying_on_another_familys_student_returns_forbidden_ownership(api):
    """PRD §2.6: "the first rule that fails dictates the rejection's
    `error_id` and HTTP status, and no subsequent rule is evaluated for
    that request."
    PRD §2.1: "Concretely, a `Guardian` may only create or act upon an
    `Application` whose `student_id` points to a `Student` whose
    `family_id` equals `X-User-ID`; a guardian who attempts to submit,
    withdraw, accept, or decline on behalf of another family's student is
    rejected with `ERR_FORBIDDEN_OWNERSHIP` and HTTP 403."

    Guardian for family A creates an Application using family B's student.
    The ownership check (priority 7) fires before the per-window-uniqueness
    / choice_rank check (priority 8); the response is
    ERR_FORBIDDEN_OWNERSHIP.

    Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_constraint_apply_for_other_family_with_duplicate
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DPRI2", name="Prio2", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SPRI2", name="P2s",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=3)
    window = create_window(district["id"], cycle_label="2026-27-PRI2")
    fam_a = register_family(district["id"], guardian_email="pa@x.com",
                            residence_zone_code="ZPRI", poverty_flag=False)
    fam_b = register_family(district["id"], guardian_email="pb@x.com",
                            residence_zone_code="ZPRI", poverty_flag=False)
    stu_b = create_student(fam_b["id"], grade_for_cycle=7)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    # Guardian A POSTs an application using B's student id.
    payload = create_application_payload(window["id"], stu_b["id"], school["id"],
                                         choice_rank=1)
    res = api.create_application(payload, make_guardian_headers(fam_a["id"]))
    err = validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)
    assert err["error_id"] == ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value
