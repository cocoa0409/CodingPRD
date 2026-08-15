"""Difficulty queue: priority-pair validation conflicts (PRD §2.8).

PRD §2.8 fixes the validation sequence: authentication, authorization, path
existence, body references, transition validity, terminal-state lockdown, and
only then endpoint-specific business rules in their named order.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, api_client,
    TEST_USERS, make_intake_specialist_headers, make_medical_director_headers,
    make_member_services_rep_headers,
    create_member, create_provider, create_policy, set_clock,
    intake_case, triage_case, begin_review, request_clinical_review,
    walk_review_to_determined, create_notification_payload,
    create_and_send_decision_notification, decide_case_clinical,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]


def _setup_triaged_appeal_triaged_by(user_id: str):
    member = create_member("MBR-PP1", full_name="Xia Ren", program="MEDICARE")
    provider = create_provider("9012345678", legal_name="Ren Practice",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    triage_case(case["id"], headers=make_intake_specialist_headers(user_id))
    return case


def test_decide_wrong_state_reports_invalid_state_not_duty_segregation(api):
    """PRD §2.8: "Fifth, transition validity: if the requested action is not declared from
    the resource's current state, the request is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."
PRD §2.8: "Only after those six generic gates do endpoint-specific business rules
    apply, and they too have a fixed relative order: segregation of duties
    (`ERR_DUTY_SEGREGATION`); clinical routing
    (`ERR_CLINICAL_REVIEW_REQUIRED`); the three temporal windows —
    acknowledgement (`ERR_ACK_WINDOW_MISSED`), IRE forwarding
    (`ERR_IRE_WINDOW_MISSED`), and reopening (`ERR_REOPEN_WINDOW_MISSED`);
    the one-live-clinical-review constraint (`ERR_REVIEW_IN_FLIGHT`); the
    single-extension constraint (`ERR_EXTENSION_CONSUMED`); expedited
    eligibility (`ERR_EXPEDITED_NOT_ALLOWED`); policy configuration
    (`ERR_POLICY_NOT_CONFIGURED`); notification completeness
    (`ERR_NOTIFICATION_INCOMPLETE`); the W-9 payment gate
    (`ERR_W9_REQUIRED`); the waiver gate (`ERR_WAIVER_NOT_ALLOWED`); the
    payment allowance rule (`ERR_PAYMENT_NOT_ALLOWED`); and finally the
    duplicate-intake guard (`ERR_DUPLICATE_CASE`)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_decide_wrong_state_and_sod
    """
    case = _setup_triaged_appeal_triaged_by("intake-9")
    # The caller doubles as the triager (a duty-segregation violation) AND the
    # case is in TRIAGED (a state violation). The state gate fires first.
    validate_error(
        api.decide_case(case["id"], {"decision_outcome": "UNFAVORABLE"},
                        make_medical_director_headers("intake-9")),
        ApiErrorId.ERR_INVALID_STATE)


def test_decide_wrong_state_leaves_case_untouched(api):
    """PRD §2.8: "Every request is checked against a fixed, prioritized validation sequence,
    and an earlier failure masks every later one."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_decide_wrong_state_and_sod
    """
    case = _setup_triaged_appeal_triaged_by("intake-9")
    validate_error(
        api.decide_case(case["id"], {"decision_outcome": "UNFAVORABLE"},
                        make_medical_director_headers("intake-9")),
        ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_case(case["id"], COMPLIANCE))
    assert after["status"] == "TRIAGED"
    assert after["decision_outcome"] is None
    assert after["decided_at"] is None


def _setup_notified_appeal_past_ire_window():
    """UNFAVORABLE APPEAL decided 2026-08-01T01:00, notified; clock then moved
    to 2026-08-05T00:00 (past the 72h window); an incomplete PROVIDER DECISION
    notification left QUEUED. Returns (case, incomplete_notification)."""
    member = create_member("MBR-PP2", full_name="Yusuf Ali", program="MEDICARE")
    provider = create_provider("0123456789", legal_name="Ali Care",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    triage_case(case["id"],
                headers=make_intake_specialist_headers("intake-pp2"))
    begin_review(case["id"])
    review = request_clinical_review(case["id"])
    walk_review_to_determined(review["id"], "md-401",
                              determination="UPHOLD_SERVICE")
    set_clock("2026-08-01T01:00:00Z")
    case = decide_case_clinical(case["id"], decision_outcome="UNFAVORABLE",
                                decider_id="md-402")
    create_and_send_decision_notification(case["id"])
    incomplete = get_success_data(api_client.create_notification(
        case["id"],
        {"recipient_kind": "PROVIDER", "notification_kind": "DECISION",
         "supplied_elements": ["citation_of_criteria"]},
        MSR), expected_status=201)
    set_clock("2026-08-05T00:00:00Z")
    return case, incomplete


def test_ire_referral_past_window_reports_window_missed(api):
    """PRD §3.6: "A `ComplianceOfficer` forwards a `NOTIFIED` case to the IRE by supplying
    the `ire_organization_code` of the contracted independent review
    organization — but only for an `APPEAL` whose `decision_outcome` is
    not `FULLY_FAVORABLE`, since fully favorable outcomes leave nothing to
    dispute externally, and only within 72 hours of `decided_at`; a
    forwarding attempted after that window is rejected with
    `ERR_IRE_WINDOW_MISSED`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_ire_window_and_notification
    """
    case, _incomplete = _setup_notified_appeal_past_ire_window()
    validate_error(
        api.create_ire_referral(case["id"], {"ire_organization_code": "IRE-MAX"},
                                COMPLIANCE),
        ApiErrorId.ERR_IRE_WINDOW_MISSED)


def test_incomplete_notification_reports_incomplete_on_own_endpoint(api):
    """PRD §3.5: "A `QUEUED` notification is marked sent only when its `completeness_score`
    is exactly 1.00 — every required element supplied — else
    `ERR_NOTIFICATION_INCOMPLETE`; the first transition into `SENT` stamps
    `sent_at`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_ire_window_and_notification
    """
    _case, incomplete = _setup_notified_appeal_past_ire_window()
    assert incomplete["completeness_score"] < 1.00
    validate_error(api.mark_notification_sent(incomplete["id"], MSR),
                   ApiErrorId.ERR_NOTIFICATION_INCOMPLETE)


def _setup_extended_case_pending_clinical():
    """APPEAL STANDARD case, extension consumed once, in PENDING_CLINICAL with
    a DETERMINED review. Returns (case, review)."""
    member = create_member("MBR-PP3", full_name="Zara Bi", program="MEDICARE")
    provider = create_provider("1357924680", legal_name="Bi Clinic",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=24, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    triaged = triage_case(case["id"],
                          headers=make_intake_specialist_headers("intake-pp3"))
    extended = get_success_data(api_client.extend_case(
        case["id"], {"expected_case_version": triaged["version"]}, MSR))
    assert extended["extension_applied"] is True
    begin_review(case["id"])
    review = request_clinical_review(case["id"])
    walk_review_to_determined(review["id"], "md-501",
                              determination="UPHOLD_SERVICE")
    return get_success_data(api_client.get_case(case["id"], COMPLIANCE)), review


def test_second_extension_reports_extension_consumed(api):
    """PRD §3.3: "The member-requested extension, applied by a `MemberServicesRep` from
    `TRIAGED`, `IN_REVIEW`, or `PENDING_CLINICAL`, consumes the case's
    single extension allowance: it is permitted only while
    `extension_applied` is `false` and the governing policy grants
    `extension_hours` greater than zero — otherwise
    `ERR_EXTENSION_CONSUMED`."

    Design: Difficulty/priority_pair_validation_conflict/constraint_vs_fiscal_extension_and_payment
    """
    case, _review = _setup_extended_case_pending_clinical()
    fresh = get_success_data(api.get_case(case["id"], MSR))
    validate_error(
        api.extend_case(case["id"],
                        {"expected_case_version": fresh["version"]}, MSR),
        ApiErrorId.ERR_EXTENSION_CONSUMED)


def test_payment_on_unfavorable_decision_rejected_without_mutation(api):
    """PRD §3.5: "An `UNFAVORABLE` outcome carries no such obligation —
    `effectuation_due_at` stays null and no effectuation is created — and
    fiscal discipline bars payment in that direction:
    `payment_amount_cents` must never be negative, and supplying a payment
    alongside an `UNFAVORABLE` outcome is rejected with
    `ERR_PAYMENT_NOT_ALLOWED`."

    Design: Difficulty/priority_pair_validation_conflict/constraint_vs_fiscal_extension_and_payment
    """
    case, _review = _setup_extended_case_pending_clinical()
    validate_error(
        api.decide_case(case["id"],
                        {"decision_outcome": "UNFAVORABLE",
                         "payment_amount_cents": 5000},
                        make_medical_director_headers("md-502")),
        ApiErrorId.ERR_PAYMENT_NOT_ALLOWED)
    after = get_success_data(api.get_case(case["id"], COMPLIANCE))
    assert after["status"] == "PENDING_CLINICAL", "No partial mutation"
    assert after["decision_outcome"] is None
