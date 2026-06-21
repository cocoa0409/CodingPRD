"""Interval-overlap rejection (waiting periods, coverage spans) and validation-priority
conflict resolution where two rules could fire on the same request.

Covers Difficulty/resource_temporal_overlap, Difficulty/priority_pair_validation_conflict,
and Corner/validations (dependent-verified, not-found ordering).
"""
from test_helpers import (
    get_success_data, validate_error, validate_success, ApiErrorId,
    create_employee, setup_eligible_employee,
    create_offering, create_tier, create_draft_enrollment, employee_version,
    setup_verified_dependent_on_active_enrollment,
    create_waiting_period,
    api_client as api,
    build_user_headers, TEST_USERS,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]


def test_waiting_period_overlap_rejected():
    """PRD §3.1: "A new window of any window_type may not overlap an existing window for
    the same employee; because the interval is half-open, two windows that merely abut —
    where one window's end_date equals the next window's start_date — are permitted, but
    any genuine overlap is rejected with ERR_WAITING_PERIOD_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/waiting_period_half_open_overlap_rejected_adjacency_allowed
    """
    emp = create_employee()
    create_waiting_period(emp["id"], window_type="INITIAL",
                          start_date="2026-01-01", end_date="2026-02-01")
    resp = api.create_waiting_period(emp["id"], {
        "window_type": "REINSTATEMENT", "start_date": "2026-01-15", "end_date": "2026-03-01",
    }, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_WAITING_PERIOD_OVERLAP.value)


def test_waiting_period_adjacency_allowed():
    """PRD §3.1: "two windows that merely abut — where one window's end_date equals the
    next window's start_date — are permitted, but any genuine overlap is rejected with
    ERR_WAITING_PERIOD_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/waiting_period_half_open_overlap_rejected_adjacency_allowed
    """
    emp = create_employee()
    create_waiting_period(emp["id"], window_type="INITIAL",
                          start_date="2026-01-01", end_date="2026-02-01")
    # New window starts exactly at the prior window's exclusive end_date.
    data = validate_success(api.create_waiting_period(emp["id"], {
        "window_type": "REINSTATEMENT", "start_date": "2026-02-01", "end_date": "2026-03-01",
    }, _ADMIN), expected_status=201)
    assert data["start_date"][:10] == "2026-02-01", data


def test_coverage_span_closed_overlap_rejected():
    """PRD §3.4: "the enrollment's closed coverage interval must not overlap any existing
    ACTIVE enrollment of the same benefit_type for that employee. The coverage interval
    runs inclusively from coverage_start_date to coverage_end_date; two intervals that
    merely abut — where a prior interval's end plus one day equals the new interval's
    start — are allowed, but any genuine overlap is rejected with ERR_COVERAGE_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/coverage_span_closed_overlap_rejected_adjacency_allowed
    """
    emp = setup_eligible_employee(clock_after="2026-02-10T00:00:00Z")
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=60000, employer_contribution_pct=0.70)
    enr1 = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01")
    ev1 = employee_version(emp["id"])
    get_success_data(api.activate_enrollment(enr1["id"], {"expected_employee_version": ev1}, _ADMIN))
    enr2 = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-15")
    ev2 = employee_version(emp["id"])
    resp = api.activate_enrollment(enr2["id"], {"expected_employee_version": ev2}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_OVERLAP.value)
    after = get_success_data(api.get_enrollment(enr2["id"], _ADMIN))
    assert after["status"] == "DRAFT", after


def test_coverage_span_adjacency_allowed():
    """PRD §3.4: "two intervals that merely abut — where a prior interval's end plus one
    day equals the new interval's start — are allowed, but any genuine overlap is rejected
    with ERR_COVERAGE_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/coverage_span_closed_overlap_rejected_adjacency_allowed
    """
    # First enrollment is superseded (closed end set), then a second enrollment whose start
    # is prev_end + 1 day abuts it and may activate. We supersede via a life-event move so
    # the first interval acquires a closed coverage_end_date.
    emp = setup_eligible_employee(clock_after="2026-02-10T00:00:00Z")
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=60000, employer_contribution_pct=0.70)
    enr1 = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01")
    ev1 = employee_version(emp["id"])
    get_success_data(api.activate_enrollment(enr1["id"], {"expected_employee_version": ev1}, _ADMIN))
    # Approve a life event to a same-benefit tier with coverage_start 2026-02-15: this sets
    # the first enrollment's coverage_end_date to 2026-02-14 (start minus one day).
    submitter = build_user_headers("sub_adj", "BenefitsAdmin")
    le = get_success_data(api.create_life_event(emp["id"], {
        "event_type": "MARRIAGE", "event_date": "2026-02-15",
        "requested_plan_tier_id": tier["id"], "adjustment_mode": "PROSPECTIVE",
    }, submitter))
    approver = build_user_headers("appr_adj", "BenefitsAdmin")
    ev2 = employee_version(emp["id"])
    get_success_data(api.approve_life_event(le["id"], {"expected_employee_version": ev2}, approver))
    enr1_after = get_success_data(api.get_enrollment(enr1["id"], _ADMIN))
    assert enr1_after["status"] == "SUPERSEDED", enr1_after
    assert enr1_after["coverage_end_date"][:10] == "2026-02-14", enr1_after


def test_eoi_required_beats_employee_not_eligible():
    """PRD §2.10: "segregation of duties (ERR_SEGREGATION_OF_DUTIES) is checked before the
    EOI routing rule (ERR_EOI_REQUIRED), which is checked before the employee-eligibility
    rule (ERR_EMPLOYEE_NOT_ELIGIBLE)".
    PRD §3.4: "if the enrollment is voluntary life, its coverage_amount_cents must not
    exceed the offering's guaranteed_issue_amount_cents (otherwise the EOI route is
    required and ERR_EOI_REQUIRED is returned)".

    Design: Difficulty/priority_pair_validation_conflict/not_eligible_beats_eoi_required
    """
    # Employee stays WAITING (waiting period runs past the clock) AND the VOLUNTARY_LIFE
    # enrollment is over GI: both ERR_EMPLOYEE_NOT_ELIGIBLE and ERR_EOI_REQUIRED apply.
    emp = setup_eligible_employee(wp_end="2026-06-01", clock_after="2026-01-01T00:00:00Z")
    assert emp["eligibility_status"] == "WAITING", emp
    off = create_offering(benefit_type="VOLUNTARY_LIFE", name="Voluntary Life",
                          requires_eoi=True, guaranteed_issue_amount_cents=15000000)
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=1, employer_contribution_pct=0.0,
                       rate_per_1000_monthly_cents=25)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01",
                                  coverage_amount_cents=30000000)
    ev = employee_version(emp["id"])
    resp = api.activate_enrollment(enr["id"], {"expected_employee_version": ev}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_EOI_REQUIRED.value)
    after = get_success_data(api.get_enrollment(enr["id"], _ADMIN))
    assert after["status"] == "DRAFT", after


def test_eoi_required_not_eligibility_error_when_both_apply():
    """PRD §2.10: "the EOI routing rule (ERR_EOI_REQUIRED), which is checked before the
    employee-eligibility rule (ERR_EMPLOYEE_NOT_ELIGIBLE)".

    Design: Difficulty/priority_pair_validation_conflict/not_eligible_beats_eoi_required
    """
    emp = setup_eligible_employee(wp_end="2026-06-01", clock_after="2026-01-01T00:00:00Z")
    assert emp["eligibility_status"] == "WAITING", emp
    off = create_offering(benefit_type="VOLUNTARY_LIFE", name="Voluntary Life",
                          requires_eoi=True, guaranteed_issue_amount_cents=15000000)
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=1, employer_contribution_pct=0.0,
                       rate_per_1000_monthly_cents=25)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01",
                                  coverage_amount_cents=30000000)
    ev = employee_version(emp["id"])
    resp = api.activate_enrollment(enr["id"], {"expected_employee_version": ev}, _ADMIN)
    body = resp.json()
    # The lower-priority-number EOI rule pre-empts the eligibility rule.
    assert body["data"]["error_id"] == ApiErrorId.ERR_EOI_REQUIRED.value, body
    assert body["data"]["error_id"] != ApiErrorId.ERR_EMPLOYEE_NOT_ELIGIBLE.value, body


def test_invalid_state_beats_segregation_on_reapprove_life_event():
    """PRD §2.10: "for any transition endpoint, the target resource must currently be in a
    state from which the requested transition is defined; otherwise the request fails with
    ERR_INVALID_STATE. Only after these five gates pass are the operation-specific business
    rules evaluated. Among those, segregation of duties (ERR_SEGREGATION_OF_DUTIES) is
    checked before the EOI routing rule".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_on_life_event_approve
    """
    emp = setup_eligible_employee(clock_after="2026-02-10T00:00:00Z")
    silver_off = create_offering(benefit_type="MEDICAL", name="Silver PPO")
    silver_tier = create_tier(silver_off["id"], coverage_level="EMPLOYEE_ONLY",
                              monthly_premium_cents=30000, employer_contribution_pct=0.70)
    gold_off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    gold_tier = create_tier(gold_off["id"], coverage_level="EMPLOYEE_PLUS_SPOUSE",
                            monthly_premium_cents=90000, employer_contribution_pct=0.70)
    enr = create_draft_enrollment(emp["id"], silver_tier["id"], coverage_start_date="2026-02-01")
    ev1 = employee_version(emp["id"])
    get_success_data(api.activate_enrollment(enr["id"], {"expected_employee_version": ev1}, _ADMIN))
    submitter = build_user_headers("submitter_s", "BenefitsAdmin")
    le = get_success_data(api.create_life_event(emp["id"], {
        "event_type": "MARRIAGE", "event_date": "2026-02-15",
        "requested_plan_tier_id": gold_tier["id"], "adjustment_mode": "PROSPECTIVE",
    }, submitter))
    # First approval by a DIFFERENT admin succeeds -> life event becomes APPROVED.
    approver = build_user_headers("approver_t", "BenefitsAdmin")
    ev2 = employee_version(emp["id"])
    get_success_data(api.approve_life_event(le["id"], {"expected_employee_version": ev2}, approver))
    # Re-approve by the ORIGINAL submitter: both INVALID_STATE (already APPROVED) and
    # SEGREGATION apply; the state gate (priority 5) wins.
    ev3 = employee_version(emp["id"])
    resp = api.approve_life_event(le["id"], {"expected_employee_version": ev3}, submitter)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_life_event(le["id"], _ADMIN))
    assert after["status"] == "APPROVED", after


def test_invalid_state_beats_segregation_on_reject_approved_life_event():
    """PRD §2.10: "the target resource must currently be in a state from which the requested
    transition is defined; otherwise the request fails with ERR_INVALID_STATE. Only after
    these five gates pass are the operation-specific business rules evaluated. Among those,
    segregation of duties (ERR_SEGREGATION_OF_DUTIES) is checked before the EOI routing
    rule".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_on_life_event_approve
    """
    emp = setup_eligible_employee(clock_after="2026-02-10T00:00:00Z")
    silver_off = create_offering(benefit_type="MEDICAL", name="Silver PPO")
    silver_tier = create_tier(silver_off["id"], coverage_level="EMPLOYEE_ONLY",
                              monthly_premium_cents=30000, employer_contribution_pct=0.70)
    gold_off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    gold_tier = create_tier(gold_off["id"], coverage_level="EMPLOYEE_PLUS_SPOUSE",
                            monthly_premium_cents=90000, employer_contribution_pct=0.70)
    enr = create_draft_enrollment(emp["id"], silver_tier["id"], coverage_start_date="2026-02-01")
    ev1 = employee_version(emp["id"])
    get_success_data(api.activate_enrollment(enr["id"], {"expected_employee_version": ev1}, _ADMIN))
    submitter = build_user_headers("submitter_s", "BenefitsAdmin")
    le = get_success_data(api.create_life_event(emp["id"], {
        "event_type": "MARRIAGE", "event_date": "2026-02-15",
        "requested_plan_tier_id": gold_tier["id"], "adjustment_mode": "PROSPECTIVE",
    }, submitter))
    approver = build_user_headers("approver_t", "BenefitsAdmin")
    ev2 = employee_version(emp["id"])
    get_success_data(api.approve_life_event(le["id"], {"expected_employee_version": ev2}, approver))
    # Reject (also segregation-gated) by the original submitter on an already-APPROVED life
    # event: INVALID_STATE (terminal) pre-empts the segregation check.
    resp = api.reject_life_event(le["id"], submitter)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_life_event(le["id"], _ADMIN))
    assert after["status"] == "APPROVED", after


def test_add_unverified_dependent_rejected():
    """PRD §3.9: "Only a dependent whose verification_status is VERIFIED may be attached;
    attempting to attach one that is not verified is rejected with
    ERR_DEPENDENT_NOT_VERIFIED."

    Design: Corner/validations/add_unverified_dependent_rejected
    """
    ctx = setup_verified_dependent_on_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    # Register a fresh PENDING dependent (not verified) for the same employee.
    pending = get_success_data(api.create_dependent(ctx["employee"]["id"], {
        "relationship": "CHILD", "full_name": "Pe Kid", "date_of_birth": "2022-02-02",
    }, _ADMIN))
    resp = api.add_dependent_to_enrollment(enr_id, {"dependent_id": pending["id"]}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_DEPENDENT_NOT_VERIFIED.value)
    enr = get_success_data(api.get_enrollment(enr_id, _ADMIN))
    assert enr["covered_dependent_count"] == 0, enr


def test_not_found_beats_state_check_on_activate_missing_enrollment():
    """PRD §2.5: "The first identifier — in the path or, failing that, in the body — that
    does not correspond to an existing resource causes the request to be rejected with
    ERR_NOT_FOUND before any business rule is evaluated."
    PRD §2.10: "existence of every path and body-referenced resource is confirmed, failing
    with ERR_NOT_FOUND ... Fifth, for any transition endpoint, the target resource must
    currently be in a state from which the requested transition is defined".

    Design: Corner/validations/not_found_before_state_check_ordering
    """
    resp = api.activate_enrollment("00000000-0000-4000-8000-000000000abc", {}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
