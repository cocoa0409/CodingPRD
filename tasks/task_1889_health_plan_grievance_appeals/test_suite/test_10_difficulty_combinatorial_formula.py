"""Difficulty queue: combinatorial formulas (PRD §2.6, §3.3, §3.5, §3.9)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    assert_same_instant,
    TEST_USERS, make_intake_specialist_headers, make_medical_director_headers,
    make_member_services_rep_headers,
    create_member, create_provider, create_policy, set_clock,
    intake_case, triage_case, begin_review, request_clinical_review,
    walk_review_to_determined, decide_case_clinical,
    decide_grievance_from_in_review,
    create_and_send_decision_notification, get_case_effectuation,
    setup_member_with_ctm_cases, get_ctm_exposure, get_member_fresh,
    setup_notified_case, link_case_to_ctm,
    DECISION_ELEMENTS_MINUS_APPEAL_RIGHTS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]


def _setup_unfavorable_appeal():
    """MEDICARE APPEAL decided UNFAVORABLE (clinical path). Returns the case."""
    member = create_member("MBR-CF1", full_name="Nina Fox", program="MEDICARE")
    provider = create_provider("1029384756", legal_name="Fox Medical",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=168,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    triage_case(case["id"],
                headers=make_intake_specialist_headers("intake-cf1"))
    begin_review(case["id"])
    review = request_clinical_review(case["id"])
    walk_review_to_determined(review["id"], "md-101",
                              determination="UPHOLD_SERVICE")
    return decide_case_clinical(case["id"], decision_outcome="UNFAVORABLE",
                                decider_id="md-102")


def test_notification_completeness_missing_element_score(api):
    """PRD §3.5: "Each required element carries a fixed weight: `citation_of_criteria` at
    0.25, `appeal_rights` at 0.25, `decision_rationale` at 0.20,
    `expedited_availability` at 0.10, `ire_notice` at 0.10,
    `contact_information` at 0.05, and `language_assistance` at 0.05, the
    weights summing to exactly 1.00."
PRD §2.6: "The notification completeness score does the opposite: each matched
    element's contribution is rounded to 4 decimal places first, the
    contributions are then summed, and only the total is rounded half-up
    to 2 decimals (per-element-then-sum)."

    Design: Difficulty/combinatorial_formula/notification_completeness_per_element_round_then_sum
    """
    case = _setup_unfavorable_appeal()
    data = validate_success(api.create_notification(
        case["id"],
        {"recipient_kind": "MEMBER", "notification_kind": "DECISION",
         "supplied_elements": list(DECISION_ELEMENTS_MINUS_APPEAL_RIGHTS)},
        MSR), expected_status=201)
    # All required elements except appeal_rights (0.25): 1.00 - 0.25 = 0.75.
    assert data["completeness_score"] == 0.75, (
        f"Expected 0.75, got {data['completeness_score']}")


def test_notification_completeness_incomplete_blocks_mark_sent(api):
    """PRD §3.5: "A `QUEUED` notification is marked sent only when its `completeness_score`
    is exactly 1.00 — every required element supplied — else
    `ERR_NOTIFICATION_INCOMPLETE`; the first transition into `SENT` stamps
    `sent_at`."

    Design: Difficulty/combinatorial_formula/notification_completeness_per_element_round_then_sum
    """
    case = _setup_unfavorable_appeal()
    notif = validate_success(api.create_notification(
        case["id"],
        {"recipient_kind": "MEMBER", "notification_kind": "DECISION",
         "supplied_elements": list(DECISION_ELEMENTS_MINUS_APPEAL_RIGHTS)},
        MSR), expected_status=201)
    assert notif["completeness_score"] < 1.00
    validate_error(api.mark_notification_sent(notif["id"], MSR),
                   ApiErrorId.ERR_NOTIFICATION_INCOMPLETE)


def _setup_appeal_standard_then_expedite():
    """APPEAL case triaged STANDARD (168h) then expedited in place (72h)."""
    member = create_member("MBR-CF2", full_name="Omar Ray", program="MEDICARE")
    provider = create_provider("5647382910", legal_name="Ray Health",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=168,
                  extension_hours=24, effectuation_hours=72)
    create_policy("MEDICARE", "APPEAL", "EXPEDITED", resolution_hours=72,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    triaged = triage_case(case["id"])
    return triaged


def test_case_deadline_standard_then_expedited_reanchor(api):
    """PRD §3.3: "The deadline computation anchors at `received_at` and adds the active
    policy's `resolution_hours` for the case's (`program`, `case_kind`,
    `priority_track`) triple; when an extension has been applied, the
    policy's `extension_hours` are added on top."
PRD §3.3: "The upgrade sets `priority_track` to `EXPEDITED` and recomputes
    `resolution_due_at` under the expedited policy's smaller
    `resolution_hours` — crucially, the anchor remains the original
    `received_at`, not the moment of the upgrade, so a mid-flight upgrade
    shortens the remaining window rather than restarting it."

    Design: Difficulty/combinatorial_formula/case_deadline_multivariate_threshold_selection
    """
    triaged = _setup_appeal_standard_then_expedite()
    assert_same_instant(triaged["resolution_due_at"], "2026-08-08T00:00:00Z")
    upgraded = validate_success(api.expedite_case(triaged["id"], MD))
    assert upgraded["priority_track"] == "EXPEDITED"
    # EXPEDITED 72h re-anchored at received_at, not at the upgrade time.
    assert_same_instant(upgraded["resolution_due_at"], "2026-08-04T00:00:00Z")


def test_case_deadline_expedited_policy_without_extension_hours(api):
    """PRD §3.3: "The member-requested extension, applied by a `MemberServicesRep` from
    `TRIAGED`, `IN_REVIEW`, or `PENDING_CLINICAL`, consumes the case's
    single extension allowance: it is permitted only while
    `extension_applied` is `false` and the governing policy grants
    `extension_hours` greater than zero — otherwise
    `ERR_EXTENSION_CONSUMED`."

    Design: Difficulty/combinatorial_formula/case_deadline_multivariate_threshold_selection
    """
    triaged = _setup_appeal_standard_then_expedite()
    upgraded = validate_success(api.expedite_case(triaged["id"], MD))
    # The EXPEDITED policy carries extension_hours = 0, so the single-extension
    # allowance cannot be consumed on this track.
    validate_error(
        api.extend_case(upgraded["id"],
                        {"expected_case_version": upgraded["version"]}, MSR),
        ApiErrorId.ERR_EXTENSION_CONSUMED)


def _setup_three_triaged_ctm_grievances():
    member, cases = setup_member_with_ctm_cases("MBR-CF3", 3, triage=False)
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    return member, [triage_case(c["id"]) for c in cases]


def test_ctm_tier_medium_before_close(api):
    """PRD §3.9: "The member's CTM exposure tier derives from that count: zero linked cases
    is tier `NONE` with weight 0; one or two is `LOW` with weight 1; three
    to five is `MEDIUM` with weight 2; six or more is `HIGH` with weight 3
    — so a count of exactly three is `MEDIUM` and exactly six is `HIGH`."

    Design: Difficulty/combinatorial_formula/ctm_tier_threshold_circular_count_dependency
    """
    member, _cases = _setup_three_triaged_ctm_grievances()
    exposure = get_ctm_exposure(member["id"])
    assert exposure["ctm_linked_case_count"] == 3
    assert exposure["tier"] == "MEDIUM"
    assert exposure["weight"] == 2


def test_ctm_tier_recomputed_after_close_decrements_count(api):
    """PRD §3.8: "Either closure stamps `closed_at`, decrements the member's
    `open_case_count` by one (and `ctm_linked_case_count` when the case
    was CTM-linked), appends a `NOTE` event whose `body` reads `CLOSED`,
    and increments the case's `version`."
PRD §3.9: "The member's CTM exposure tier derives from that count: zero linked cases
    is tier `NONE` with weight 0; one or two is `LOW` with weight 1; three
    to five is `MEDIUM` with weight 2; six or more is `HIGH` with weight 3
    — so a count of exactly three is `MEDIUM` and exactly six is `HIGH`."

    Design: Difficulty/combinatorial_formula/ctm_tier_threshold_circular_count_dependency
    """
    member, cases = _setup_three_triaged_ctm_grievances()
    target = begin_review(cases[0]["id"])
    target = decide_grievance_from_in_review(target["id"],
                                             decision_outcome="UNFAVORABLE")
    create_and_send_decision_notification(target["id"])
    # Close the CTM-linked case; the count that defines the tier drops first.
    validate_success(api.close_case(target["id"], COMPLIANCE))
    member_after = get_member_fresh(member["id"])
    assert member_after["ctm_linked_case_count"] == 2
    exposure = get_ctm_exposure(member["id"])
    assert exposure["tier"] == "LOW", (
        "Tier must reflect the post-close count of 2, not the pre-close 3")
    assert exposure["weight"] == 1
