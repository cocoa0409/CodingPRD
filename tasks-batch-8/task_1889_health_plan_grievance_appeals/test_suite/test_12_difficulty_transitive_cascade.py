"""Difficulty queue: transitive cascades (PRD §3.6, §3.7, §3.8, §3.9).

Multi-hop cascades where each link is caused by the previous link.
"""
from test_helpers import (
    validate_success, get_success_data, ApiErrorId, api_client,
    TEST_USERS, make_intake_specialist_headers, make_medical_director_headers,
    create_member, create_provider, create_policy, set_clock,
    intake_case, triage_case, begin_review, request_clinical_review,
    walk_review_to_determined, decide_case_clinical,
    create_and_send_decision_notification, setup_notified_case,
    create_and_review_reopening, get_member_fresh, get_ctm_exposure,
    link_case_to_ctm, create_in_review_case, decide_grievance_from_in_review,
    get_case_effectuation, start_effectuation, complete_effectuation,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]


def _setup_closed_appeal_with_determined_review():
    """APPEAL decided UNFAVORABLE via the clinical path, notified, closed; the
    DETERMINED review still attached. Returns (member, case, review, reopening)."""
    member = create_member("MBR-TC1", full_name="Uma Vail", program="MEDICARE")
    provider = create_provider("7894561230", legal_name="Vail Ortho",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    triage_case(case["id"],
                headers=make_intake_specialist_headers("intake-tc1"))
    begin_review(case["id"])
    review = request_clinical_review(case["id"])
    walk_review_to_determined(review["id"], "md-201",
                              determination="UPHOLD_SERVICE")
    case = decide_case_clinical(case["id"], decision_outcome="UNFAVORABLE",
                                decider_id="md-202")
    create_and_send_decision_notification(case["id"])
    # Close path for an UNFAVORABLE APPEAL requires an IRE referral or the
    # 72-hour forwarding window lapsed unexercised, documented by a NOTE
    # (PRD §3.8). decided_at is the pinned default clock, so move past
    # decided_at + 72h before recording the lapse and closing.
    set_clock("2026-08-04T01:00:00Z")
    get_success_data(api_client.append_case_event(
        case["id"],
        {"event_type": "NOTE",
         "body": "IRE forwarding window lapsed unexercised"},
        COMPLIANCE), expected_status=201)
    closed = get_success_data(api_client.close_case(case["id"], COMPLIANCE))
    reopening = create_and_review_reopening(
        closed["id"], request_reason="FRAUD_OR_SIMILAR_FAULT")
    return member, closed, review, reopening


def test_reopening_grant_cascade_case_states(api):
    """PRD §3.8: "On grant, the reopening's `decided_at` is stamped and its
    `spawned_case_id` is set to a newly created case — status `RECEIVED`,
    `reopened_from_case_id` pointing at the source case, `case_kind` and
    `priority_track` copied from it — while the source case
    auto-transitions `CLOSED` → `REOPENED` as a marker, the member's
    `open_case_count` increments by one for the spawned case, any
    `DETERMINED` clinical review on the source case transitions to
    `SUPERSEDED`, and a `REOPEN_GRANTED` event is appended on the source
    case."

    Design: Difficulty/transitive_cascade/reopening_grant_four_hop_cascade
    """
    member, closed, review, reopening = \
        _setup_closed_appeal_with_determined_review()
    fresh = get_success_data(api.get_case(closed["id"], COMPLIANCE))
    granted = validate_success(api.grant_reopening(
        reopening["id"], {"expected_case_version": fresh["version"]},
        COMPLIANCE))
    # hop 1: the reopening itself.
    assert granted["status"] == "GRANTED"
    assert granted["spawned_case_id"]
    # hop 2: source case flips to the REOPENED marker.
    source = get_success_data(api.get_case(closed["id"], COMPLIANCE))
    assert source["status"] == "REOPENED"
    # hop 3: the spawned replacement case.
    spawned = get_success_data(api.get_case(granted["spawned_case_id"], COMPLIANCE))
    assert spawned["status"] == "RECEIVED"
    assert spawned["reopened_from_case_id"] == closed["id"]
    assert spawned["case_kind"] == "APPEAL"


def test_reopening_grant_cascade_supersedes_review_and_counts_member(api):
    """PRD §3.8: "On grant, the reopening's `decided_at` is stamped and its
    `spawned_case_id` is set to a newly created case — status `RECEIVED`,
    `reopened_from_case_id` pointing at the source case, `case_kind` and
    `priority_track` copied from it — while the source case
    auto-transitions `CLOSED` → `REOPENED` as a marker, the member's
    `open_case_count` increments by one for the spawned case, any
    `DETERMINED` clinical review on the source case transitions to
    `SUPERSEDED`, and a `REOPEN_GRANTED` event is appended on the source
    case."
PRD §3.4: "A determined review is terminal with one systemic exception: when a newer
    clinical review is created for the same case after a reopening, the
    prior `DETERMINED` review is marked `SUPERSEDED`, and its
    `superseded_by_review_id` points at the newer review's `id`."

    Design: Difficulty/transitive_cascade/reopening_grant_four_hop_cascade
    """
    member, closed, review, reopening = \
        _setup_closed_appeal_with_determined_review()
    oc_before = get_member_fresh(member["id"])["open_case_count"]
    fresh = get_success_data(api.get_case(closed["id"], COMPLIANCE))
    granted = validate_success(api.grant_reopening(
        reopening["id"], {"expected_case_version": fresh["version"]},
        COMPLIANCE))
    # hop 4: the prior DETERMINED review is superseded.
    review_after = get_success_data(api.get_clinical_review(review["id"], COMPLIANCE))
    assert review_after["status"] == "SUPERSEDED"
    # Member counter per the §3.1 definition: open_case_count counts every
    # case whose status is in the open set, which includes REOPENED. The
    # grant therefore moves the count by +2 from the post-close baseline:
    # +1 for the spawned RECEIVED case (§3.8) and +1 for the source case
    # re-entering the open set via the CLOSED -> REOPENED marker.
    oc_after = get_member_fresh(member["id"])["open_case_count"]
    assert oc_after == oc_before + 2, (
        f"open_case_count counts both the RECEIVED spawn and the REOPENED "
        f"source (PRD §3.1 open-status list); before={oc_before} "
        f"after={oc_after}")


def _setup_ire_acknowledged_appeal():
    """APPEAL decided PARTIALLY_FAVORABLE (payment 12000), notified, referred
    to the IRE within the window, referral ACKNOWLEDGED_BY_IRE.
    Returns (member, case, referral)."""
    member = create_member("MBR-TC2", full_name="Vic Ames", program="MEDICARE")
    provider = create_provider("8901234567", legal_name="Ames Surgical",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    triage_case(case["id"],
                headers=make_intake_specialist_headers("intake-tc2"))
    begin_review(case["id"])
    review = request_clinical_review(case["id"])
    walk_review_to_determined(review["id"], "md-301", determination="PARTIAL")
    case = decide_case_clinical(case["id"],
                                decision_outcome="PARTIALLY_FAVORABLE",
                                payment_amount_cents=12000,
                                decider_id="md-302")
    create_and_send_decision_notification(case["id"])
    referral = get_success_data(api_client.create_ire_referral(
        case["id"], {"ire_organization_code": "IRE-MAX"}, COMPLIANCE),
        expected_status=201)
    referral = get_success_data(api_client.ire_acknowledge(referral["id"], COMPLIANCE))
    return member, case, referral


def test_ire_overturn_spawns_referral_linked_effectuation(api):
    """PRD §3.6: "When the IRE overturns the plan in whole or in part, the recording
    simultaneously creates an Effectuation on the parent case in `PENDING`
    status whose `referral_id` points back to this referral; an
    `UPHOLD_PLAN` outcome creates nothing."

    Design: Difficulty/transitive_cascade/ire_overturn_effectuation_referral_cascade
    """
    member, case, referral = _setup_ire_acknowledged_appeal()
    data = validate_success(api.ire_record_decision(
        referral["id"],
        {"ire_decision": "OVERTURN_PLAN", "payment_amount_cents": 12000},
        COMPLIANCE))
    assert data["status"] == "DECISION_RECEIVED"
    linked = get_success_data(api.list_effectuations(
        CLAIMS, params={"referral_id": referral["id"]}))
    assert len(linked) == 1, "Exactly one effectuation must carry this referral_id"
    assert linked[0]["status"] == "PENDING"
    assert linked[0]["case_id"] == case["id"]


def test_ire_effectuation_completion_cascades_referral_to_effectuated(api):
    """PRD §3.6: "Later, when that linked effectuation completes, the referral
    auto-transitions `DECISION_RECEIVED` → `EFFECTUATED`."
PRD §3.7: "Completing stamps `completed_at`, computes `timeliness_percent`, appends
    an `EFFECTUATION_COMPLETED` event on the parent case, and — when the
    effectuation's `referral_id` is set — fires the linked referral's
    auto-transition to `EFFECTUATED`."

    Design: Difficulty/transitive_cascade/ire_overturn_effectuation_referral_cascade
    """
    member, case, referral = _setup_ire_acknowledged_appeal()
    validate_success(api.ire_record_decision(
        referral["id"],
        {"ire_decision": "OVERTURN_PLAN", "payment_amount_cents": 12000},
        COMPLIANCE))
    linked = get_success_data(api.list_effectuations(
        CLAIMS, params={"referral_id": referral["id"]}))
    eff_id = linked[0]["id"]
    start_effectuation(eff_id)
    completed = complete_effectuation(eff_id)
    assert completed["status"] == "EFFECTUATED"
    referral_after = get_success_data(api.get_ire_referral(referral["id"], COMPLIANCE))
    assert referral_after["status"] == "EFFECTUATED", (
        "The referral auto-transition must be caused by the effectuation "
        "completion, not by the decision recording")


def _setup_one_ctm_linked_notified_grievance():
    member = create_member("MBR-TC3", full_name="Wen Xu", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="GRIEVANCE")
    link_case_to_ctm(case["id"], body="ctm-x")
    triage_case(case["id"])
    begin_review(case["id"])
    case = decide_grievance_from_in_review(case["id"],
                                           decision_outcome="UNFAVORABLE")
    create_and_send_decision_notification(case["id"])
    return member, case


def test_ctm_close_decrements_member_counters(api):
    """PRD §3.8: "Either closure stamps `closed_at`, decrements the member's
    `open_case_count` by one (and `ctm_linked_case_count` when the case
    was CTM-linked), appends a `NOTE` event whose `body` reads `CLOSED`,
    and increments the case's `version`."

    Design: Difficulty/transitive_cascade/ctm_link_close_count_decrement_cascade
    """
    member, case = _setup_one_ctm_linked_notified_grievance()
    before = get_member_fresh(member["id"])
    assert before["open_case_count"] == 1
    assert before["ctm_linked_case_count"] == 1
    validate_success(api.close_case(case["id"], COMPLIANCE))
    after = get_member_fresh(member["id"])
    assert after["open_case_count"] == 0
    assert after["ctm_linked_case_count"] == 0


def test_ctm_close_cascade_moves_tier_to_none(api):
    """PRD §3.9: "The member's CTM exposure tier derives from that count: zero linked cases
    is tier `NONE` with weight 0; one or two is `LOW` with weight 1; three
    to five is `MEDIUM` with weight 2; six or more is `HIGH` with weight 3
    — so a count of exactly three is `MEDIUM` and exactly six is `HIGH`."

    Design: Difficulty/transitive_cascade/ctm_link_close_count_decrement_cascade
    """
    member, case = _setup_one_ctm_linked_notified_grievance()
    assert get_ctm_exposure(member["id"])["tier"] == "LOW"
    validate_success(api.close_case(case["id"], COMPLIANCE))
    exposure = get_ctm_exposure(member["id"])
    assert exposure["tier"] == "NONE"
    assert exposure["weight"] == 0
    assert exposure["ctm_linked_case_count"] == 0
