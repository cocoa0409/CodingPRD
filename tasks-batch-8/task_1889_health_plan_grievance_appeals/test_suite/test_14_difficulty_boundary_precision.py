"""Difficulty queue: boundary precision (PRD §3.6, §3.7, §3.9).

X-1 / X / X+1 on the effectuation timeliness percentage, the CTM tier counts,
and the IRE forwarding window.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    assert_same_instant,
    TEST_USERS, make_intake_specialist_headers, make_medical_director_headers,
    create_member, create_provider, create_policy, set_clock,
    intake_case, triage_case, begin_review, create_in_review_case,
    decide_grievance_from_in_review, request_clinical_review,
    walk_review_to_determined, decide_case_clinical,
    create_and_send_decision_notification, get_case_effectuation,
    start_effectuation, get_effectuation_fresh,
    setup_member_with_ctm_cases, get_ctm_exposure, get_member_fresh,
    link_case_to_ctm,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]


def _setup_grievance_effectuation(member_ref, npi, decide_at):
    """GRIEVANCE decided FULLY_FAVORABLE at ``decide_at`` with a 72h
    effectuation window; returns (case, effectuation)."""
    member = create_member(member_ref, full_name="Boundary Test",
                           program="MEDICARE")
    provider = create_provider(npi, legal_name="Boundary Clinic",
                               w9_on_file=True)
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = create_in_review_case(member["id"], case_kind="GRIEVANCE",
                                 provider_id=provider["id"])
    set_clock(decide_at)
    case = decide_grievance_from_in_review(
        case["id"], decision_outcome="FULLY_FAVORABLE",
        payment_amount_cents=1000)
    return case, get_case_effectuation(case["id"])


def test_effectuation_completion_at_exact_window_end_is_timely(api):
    """PRD §3.7: "The timeliness boundary is inclusive: a consumed interval exactly equal to
    the window yields 100.00 and is timely, while 100.01 is late — any
    completion after `effectuation_due_at` produces a value above 100.00."

    Design: Difficulty/boundary_precision_check/effectuation_timeliness_exactly_100_percent_is_timely
    """
    case, eff = _setup_grievance_effectuation("MBR-BP1", "2468013579",
                                              "2026-08-02T00:00:00Z")
    assert_same_instant(case["effectuation_due_at"], "2026-08-05T00:00:00Z")
    start_effectuation(eff["id"])
    # Complete at exactly the window end: consumed == window == 72h.
    set_clock("2026-08-05T00:00:00Z")
    fresh = get_effectuation_fresh(eff["id"])
    data = validate_success(api.complete_effectuation(
        eff["id"], {"expected_effectuation_version": fresh["version"]}, CLAIMS))
    assert data["timeliness_percent"] == 100.00, (
        f"Exactly 72h of a 72h window must yield 100.00; got "
        f"{data['timeliness_percent']}")
    assert data["status"] == "EFFECTUATED"


def test_effectuation_completion_one_hour_late_exceeds_boundary(api):
    """PRD §3.7: "The timeliness percentage measures window consumption: one hundred times
    the consumed hours divided by the window hours, where the window runs
    from the case's `decided_at` to its `effectuation_due_at` and the
    consumed hours run from `decided_at` to the effectuation's
    `completed_at`, the result rounded half-up to two decimal places."
PRD §3.7: "The timeliness boundary is inclusive: a consumed interval exactly equal to
    the window yields 100.00 and is timely, while 100.01 is late — any
    completion after `effectuation_due_at` produces a value above 100.00."
PRD §3.7: "Completion is permitted from `IN_PROGRESS`, `OVERDUE`, or `ESCALATED` and
    is guarded per §2.7: the request must carry
    `expected_effectuation_version` matching the effectuation's current
    `version`, else `ERR_STALE_VERSION`."

    Design: Difficulty/boundary_precision_check/effectuation_timeliness_exactly_100_percent_is_timely
    """
    case, eff = _setup_grievance_effectuation("MBR-BP1B", "2468013580",
                                              "2026-08-02T00:00:00Z")
    start_effectuation(eff["id"])
    # One hour past the window end: 73h consumed of 72h -> 101.39.
    set_clock("2026-08-05T01:00:00Z")
    fresh = get_effectuation_fresh(eff["id"])
    data = validate_success(api.complete_effectuation(
        eff["id"], {"expected_effectuation_version": fresh["version"]}, CLAIMS))
    assert data["timeliness_percent"] == 101.39, (
        f"73h of a 72h window must yield 101.39; got {data['timeliness_percent']}")


def _build_triaged_linked_cases(member, count, start_index=0):
    """Intake + CTM-link + triage ``count`` identical GRIEVANCE cases.

    The intakes are identical (same member/kind/provider), so each one is
    spaced two hours past the previous to stay outside the duplicate-intake
    guard's prior-one-hour look-back (PRD §3.2); triage immediately follows
    each intake, well inside the 24-hour acknowledgement window (§3.3).
    """
    cases = []
    for i in range(count):
        if start_index + i > 0:
            set_clock(f"2026-08-01T{2 * (start_index + i):02d}:00:00Z")
        case = intake_case(member["id"], case_kind="GRIEVANCE")
        link_case_to_ctm(case["id"], body=str(start_index + i + 1))
        cases.append(triage_case(case["id"]))
    return cases


def test_ctm_tier_boundary_two_is_low_three_is_medium(api):
    """PRD §3.9: "The member's CTM exposure tier derives from that count: zero linked cases
    is tier `NONE` with weight 0; one or two is `LOW` with weight 1; three
    to five is `MEDIUM` with weight 2; six or more is `HIGH` with weight 3
    — so a count of exactly three is `MEDIUM` and exactly six is `HIGH`."

    Design: Difficulty/boundary_precision_check/ctm_tier_boundary_count_2_vs_3_and_5_vs_6
    """
    member = create_member("MBR-BP2", full_name="Ben Ito", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    _build_triaged_linked_cases(member, 2)
    exposure = get_ctm_exposure(member["id"])
    assert exposure["ctm_linked_case_count"] == 2
    assert exposure["tier"] == "LOW", "count 2 is inside the 1..2 band"
    _build_triaged_linked_cases(member, 1, start_index=2)
    exposure = get_ctm_exposure(member["id"])
    assert exposure["ctm_linked_case_count"] == 3
    assert exposure["tier"] == "MEDIUM", "count 3 crosses the >= 3 boundary"


def test_ctm_tier_boundary_five_is_medium_six_is_high(api):
    """PRD §3.9: "The member's CTM exposure tier derives from that count: zero linked cases
    is tier `NONE` with weight 0; one or two is `LOW` with weight 1; three
    to five is `MEDIUM` with weight 2; six or more is `HIGH` with weight 3
    — so a count of exactly three is `MEDIUM` and exactly six is `HIGH`."

    Design: Difficulty/boundary_precision_check/ctm_tier_boundary_count_2_vs_3_and_5_vs_6
    """
    member = create_member("MBR-BP2B", full_name="Ben Ito Six",
                           program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    _build_triaged_linked_cases(member, 5)
    exposure = get_ctm_exposure(member["id"])
    assert exposure["ctm_linked_case_count"] == 5
    assert exposure["tier"] == "MEDIUM", "count 5 is still inside 3..5"
    _build_triaged_linked_cases(member, 1, start_index=5)
    exposure = get_ctm_exposure(member["id"])
    assert exposure["ctm_linked_case_count"] == 6
    assert exposure["tier"] == "HIGH", "count 6 crosses the >= 6 boundary"
    assert exposure["weight"] == 3


def _setup_notified_unfavorable_appeal(decide_at="2026-08-01T01:00:00Z"):
    member = create_member("MBR-BP3", full_name="Cora Lin", program="MEDICARE")
    provider = create_provider("9876543210", legal_name="Lin Group",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    triage_case(case["id"],
                headers=make_intake_specialist_headers("intake-bp3"))
    begin_review(case["id"])
    review = request_clinical_review(case["id"])
    walk_review_to_determined(review["id"], "md-601",
                              determination="UPHOLD_SERVICE")
    set_clock(decide_at)
    case = decide_case_clinical(case["id"], decision_outcome="UNFAVORABLE",
                                decider_id="md-602")
    create_and_send_decision_notification(case["id"])
    return case


def test_ire_referral_at_exactly_72h_succeeds(api):
    """PRD §3.6: "A `ComplianceOfficer` forwards a `NOTIFIED` case to the IRE by supplying
    the `ire_organization_code` of the contracted independent review
    organization — but only for an `APPEAL` whose `decision_outcome` is
    not `FULLY_FAVORABLE`, since fully favorable outcomes leave nothing to
    dispute externally, and only within 72 hours of `decided_at`; a
    forwarding attempted after that window is rejected with
    `ERR_IRE_WINDOW_MISSED`."
PRD §3.6: "Forwarding moves the case `NOTIFIED` → `IRE_REFERRED`, creates the
    referral in `FORWARDED` status with `forwarded_at` stamped by the
    server, appends an `IRE_FORWARDED` event, and increments the case's
    `version`."

    Design: Difficulty/boundary_precision_check/ire_forwarding_window_exactly_72h_vs_72h_plus
    """
    case = _setup_notified_unfavorable_appeal()
    # decided_at 2026-08-01T01:00:00Z + 72h == 2026-08-04T01:00:00Z (within).
    set_clock("2026-08-04T01:00:00Z")
    referral = validate_success(api.create_ire_referral(
        case["id"], {"ire_organization_code": "IRE-EDGE"}, COMPLIANCE),
        expected_status=201)
    assert referral["status"] == "FORWARDED"
    after = get_success_data(api.get_case(case["id"], COMPLIANCE))
    assert after["status"] == "IRE_REFERRED"


def test_ire_referral_one_second_past_72h_fails(api):
    """PRD §3.6: "A `ComplianceOfficer` forwards a `NOTIFIED` case to the IRE by supplying
    the `ire_organization_code` of the contracted independent review
    organization — but only for an `APPEAL` whose `decision_outcome` is
    not `FULLY_FAVORABLE`, since fully favorable outcomes leave nothing to
    dispute externally, and only within 72 hours of `decided_at`; a
    forwarding attempted after that window is rejected with
    `ERR_IRE_WINDOW_MISSED`."

    Design: Difficulty/boundary_precision_check/ire_forwarding_window_exactly_72h_vs_72h_plus
    """
    case = _setup_notified_unfavorable_appeal()
    # 2026-08-04T01:00:01Z is one second past decided_at + 72h.
    set_clock("2026-08-04T01:00:01Z")
    validate_error(
        api.create_ire_referral(case["id"], {"ire_organization_code": "IRE-EDGE"},
                                COMPLIANCE),
        ApiErrorId.ERR_IRE_WINDOW_MISSED)
    after = get_success_data(api.get_case(case["id"], COMPLIANCE))
    assert after["status"] == "NOTIFIED"
