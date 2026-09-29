"""Branching and cyclic state machines: the matching loop, offer terminals, the
counter-negotiation cycle and the rework cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_scoped_request,
    api_client,
    current_engagement_version,
    drive_review_to_outcome,
    get_success_data,
    read_agreement,
    read_cycle,
    read_deliverables,
    read_engagement,
    read_offer,
    read_request,
    read_scope,
    read_volunteer,
    read_window,
    set_clock,
    setup_selector_world,
    setup_submitted_engagement,
    validate_error,
    validate_success,
)

STRONG_CANDIDATE = {
    "seniority": "SENIOR",
    "professional_rate_usd_per_hour": 150.00,
    "proficiency": 5,
    "verify_skill": True,
    "years_experience": 12.0,
    "window_overrides": {
        "starts_at": "2026-08-01T00:00:00Z",
        "ends_at": "2026-11-01T00:00:00Z",
        "window_kind": "HARD",
        "hours_offered": 300.00,
    },
}
WEAKER_CANDIDATE = {
    "seniority": "SENIOR",
    "professional_rate_usd_per_hour": 150.00,
    "proficiency": 3,
    "verify_skill": False,
    "years_experience": 6.0,
    "window_overrides": {
        "starts_at": "2026-08-01T00:00:00Z",
        "ends_at": "2026-11-01T00:00:00Z",
        "window_kind": "HARD",
        "hours_offered": 300.00,
    },
}

LEASE_DELIVERABLE = [
    {
        "title": "Redlined lease set",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 40.00,
        "acceptance_criteria": "All leases redlined",
    }
]

TWENTY_HOUR_DELIVERABLE = [
    {
        "title": "Memo",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 20.00,
        "acceptance_criteria": "Memo accepted",
    }
]

POLICY_DELIVERABLES = [
    {
        "title": "Policy A",
        "sequence_no": 1,
        "weight_pct": 50.00,
        "hours_estimate": 20.00,
        "acceptance_criteria": "Policy A adopted",
    },
    {
        "title": "Policy B",
        "sequence_no": 2,
        "weight_pct": 50.00,
        "hours_estimate": 20.00,
        "acceptance_criteria": "Policy B adopted",
    },
]

FORTY_DELIVERY_HOURS = [
    {"work_date": "2026-08-12T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-13T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-14T00:00:00Z", "hours": 10.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-15T00:00:00Z", "hours": 6.00, "activity_class": "DELIVERY"},
]


# ---------------------------------------------------------------------------
# MATCHING is a three-way branch point
# ---------------------------------------------------------------------------
def _two_candidate_scoped_request():
    return setup_selector_world(
        [STRONG_CANDIDATE, WEAKER_CANDIDATE],
        clock="2026-08-10T00:00:00Z",
        deliverables=LEASE_DELIVERABLE,
        title="Lease portfolio review",
    )


def _decline_round(world, decline_reason):
    offer = get_success_data(
        api_client.match_project_request(world["request"]["id"], world["spec_headers"])
    )
    volunteer_headers = None
    for candidate in world["candidates"]:
        if candidate["volunteer"]["id"] == offer["volunteer_id"]:
            volunteer_headers = candidate["volunteer_headers"]
    assert volunteer_headers is not None, "The offer must name one of the seeded candidates"
    validate_success(
        api_client.decline_match_offer(
            offer["id"], {"decline_reason": decline_reason}, volunteer_headers
        )
    )
    return offer


def test_first_failed_match_round_returns_the_request_to_scoped(api):
    """PRD §3.5: "If the request's `failed_match_rounds` plus one is still below 2, the
    request returns to `SCOPED` (`MATCHING → SCOPED`) and the specialist may run the
    selector again, which will now skip every volunteer already approached."
    PRD §3.5: "The offer moves `OFFERED → DECLINED` with `responded_at` and the reason
    stamped, the holding window's `hours_committed` drops by the offer's `reserved_hours`,
    the cycle's `slots_reserved` drops by one and the posture recomputes, and the request's
    `failed_match_rounds` rises by one before the request advances as described below."

    Design: Difficulty/non_linear_state_machine/project_request_matching_three_way_branch
    """
    world = _two_candidate_scoped_request()

    first_offer = _decline_round(world, "SCHEDULE_CONFLICT")

    offer = read_offer(world, first_offer["id"])
    assert offer["status"] == "DECLINED", f"Expected DECLINED, got {offer['status']}"
    assert offer["decline_reason"] == "SCHEDULE_CONFLICT", (
        f"Expected decline_reason SCHEDULE_CONFLICT, got {offer['decline_reason']}"
    )
    request = read_request(world)
    assert request["status"] == "SCOPED", (
        f"Expected the request back at SCOPED after round one, got {request['status']}"
    )
    assert request["failed_match_rounds"] == 1, (
        f"Expected failed_match_rounds 1, got {request['failed_match_rounds']}"
    )
    assert request["rescope_count"] == 0, (
        f"Expected rescope_count still 0, got {request['rescope_count']}"
    )
    scope = read_scope(world)
    assert scope["status"] == "APPROVED", (
        f"Round one must leave the approved revision intact, got {scope['status']}"
    )
    assert request["active_scope_revision_no"] == 1, (
        f"Expected active_scope_revision_no 1, got {request['active_scope_revision_no']}"
    )


def test_second_failed_match_round_drives_the_request_into_rescoping(api):
    """PRD §3.5: "If `failed_match_rounds` plus one has reached 2 while `rescope_count` is
    still below 3, the request moves `MATCHING → RESCOPING`: the same offer-release effects
    run, `failed_match_rounds` is incremented and then reset to 0, `rescope_count` rises by
    one, the currently `APPROVED` revision moves to `SUPERSEDED`, and
    `active_scope_revision_no` resets to 0."

    Design: Difficulty/non_linear_state_machine/project_request_matching_three_way_branch
    """
    world = _two_candidate_scoped_request()

    _decline_round(world, "SCHEDULE_CONFLICT")
    second_offer = _decline_round(world, "SCOPE_TOO_LARGE")

    offer = read_offer(world, second_offer["id"])
    assert offer["status"] == "DECLINED", f"Expected DECLINED, got {offer['status']}"
    assert offer["decline_reason"] == "SCOPE_TOO_LARGE", (
        f"Expected decline_reason SCOPE_TOO_LARGE, got {offer['decline_reason']}"
    )
    request = read_request(world)
    assert request["status"] == "RESCOPING", (
        f"Expected RESCOPING after the second failed round, got {request['status']}"
    )
    assert request["failed_match_rounds"] == 0, (
        f"Expected failed_match_rounds reset to 0, got {request['failed_match_rounds']}"
    )
    assert request["rescope_count"] == 1, (
        f"Expected rescope_count 1, got {request['rescope_count']}"
    )
    assert request["active_scope_revision_no"] == 0, (
        f"Expected active_scope_revision_no 0, got {request['active_scope_revision_no']}"
    )
    scope = read_scope(world)
    assert scope["status"] == "SUPERSEDED", (
        f"Entering RESCOPING must supersede the approved revision, got {scope['status']}"
    )


def test_two_declines_return_every_hour_and_slot_to_the_ledgers(api):
    """PRD §2.8: "Offers in `ACCEPTED`, `DECLINED`, `EXPIRED` or `WITHDRAWN` status hold
    nothing, and engagements in `HANDED_OFF` or `TERMINATED` have released their slot."
    PRD §2.9: "Declining an offer, the expiry sweep, termination and handoff are all
    release paths, and each subtracts the current held amount rather than a remembered one."
    PRD §3.2: "A volunteer with no terminal engagement at all reads 0.7500 in both fields."

    Design: Difficulty/non_linear_state_machine/project_request_matching_three_way_branch
    """
    world = _two_candidate_scoped_request()

    _decline_round(world, "SCHEDULE_CONFLICT")
    _decline_round(world, "SCOPE_TOO_LARGE")

    for candidate in world["candidates"]:
        window = read_window(
            world,
            window_id=candidate["window"]["id"],
            volunteer_id=candidate["volunteer"]["id"],
        )
        assert window["hours_committed"] == pytest.approx(0.00, abs=0.01), (
            f"Expected hours_committed 0.00 after release, got {window['hours_committed']}"
        )
        assert window["hours_remaining"] == pytest.approx(300.00, abs=0.01), (
            f"Expected hours_remaining 300.00 after release, got "
            f"{window['hours_remaining']}"
        )
        volunteer = read_volunteer(world, candidate["volunteer"]["id"])
        assert volunteer["reliability_score"] == pytest.approx(0.7500, abs=1e-4), (
            f"A declined offer must not touch reliability, got "
            f"{volunteer['reliability_score']}"
        )
        assert volunteer["terminal_engagement_count"] == 0, (
            f"Expected terminal_engagement_count 0, got "
            f"{volunteer['terminal_engagement_count']}"
        )
    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved 0, got {cycle['slots_reserved']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.0000, abs=1e-4), (
        f"Expected utilization_ratio 0.0000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", f"Expected posture OPEN, got {cycle['posture']}"


# ---------------------------------------------------------------------------
# The four offer terminals and their divergent side effects
# ---------------------------------------------------------------------------
def _three_offers_on_sibling_requests():
    world = setup_selector_world(
        [STRONG_CANDIDATE],
        clock="2026-08-10T00:00:00Z",
        requested_hours=20.00,
        estimated_hours=20.00,
        deliverables=TWENTY_HOUR_DELIVERABLE,
        title="Request A",
    )
    world["request_b"] = add_scoped_request(
        world,
        skill_code="LEGAL_CONTRACTS",
        estimated_hours=20.00,
        deliverables=TWENTY_HOUR_DELIVERABLE,
        title="Request B",
    )
    world["request_c"] = add_scoped_request(
        world,
        skill_code="LEGAL_CONTRACTS",
        estimated_hours=20.00,
        deliverables=TWENTY_HOUR_DELIVERABLE,
        title="Request C",
    )
    world["offer_a"] = get_success_data(
        api_client.match_project_request(world["request"]["id"], world["spec_headers"])
    )
    world["offer_b"] = get_success_data(
        api_client.match_project_request(
            world["request_b"]["request"]["id"], world["spec_headers"]
        )
    )
    world["offer_c"] = get_success_data(
        api_client.match_project_request(
            world["request_c"]["request"]["id"], world["spec_headers"]
        )
    )
    return world


def test_decline_for_ip_terms_charges_a_failed_round_to_its_request(api):
    """PRD §3.5: "A decline requires a `decline_reason` of `SCOPE_TOO_LARGE`,
    `SCHEDULE_CONFLICT`, `OUTSIDE_EXPERTISE` or `IP_TERMS_UNACCEPTABLE`, and is only
    accepted while the clock is still strictly before `expires_at`."
    PRD §3.5: "One reason carries an extra consequence that no other outcome shares: a
    decline for `IP_TERMS_UNACCEPTABLE` bars that volunteer from every later matching round
    on that request, over and above the ordinary retry exclusion."

    Design: Difficulty/non_linear_state_machine/match_offer_four_terminals_diverge
    """
    world = _three_offers_on_sibling_requests()
    candidate = world["candidates"][0]

    validate_success(
        api_client.decline_match_offer(
            world["offer_a"]["id"],
            {"decline_reason": "IP_TERMS_UNACCEPTABLE"},
            candidate["volunteer_headers"],
        )
    )

    offer = read_offer(world, world["offer_a"]["id"])
    assert offer["status"] == "DECLINED", f"Expected DECLINED, got {offer['status']}"
    assert offer["decline_reason"] == "IP_TERMS_UNACCEPTABLE", (
        f"Expected decline_reason IP_TERMS_UNACCEPTABLE, got {offer['decline_reason']}"
    )
    assert offer["responded_at"] is not None, "A decline must stamp responded_at"
    request = read_request(world)
    assert request["status"] == "SCOPED", f"Expected SCOPED, got {request['status']}"
    assert request["failed_match_rounds"] == 1, (
        f"A decline charges one failed round, got {request['failed_match_rounds']}"
    )


def test_admin_withdrawal_releases_the_hold_without_charging_a_failed_round(api):
    """PRD §3.5: "The offer moves `OFFERED → WITHDRAWN` with `responded_at` and the reason
    stamped, and the same hour and slot releases run."
    PRD §3.5: "The difference from a decline is conditional: `failed_match_rounds` rises
    only when `withdraw_reason` is something other than `ADMIN`."

    Design: Difficulty/non_linear_state_machine/match_offer_four_terminals_diverge
    """
    world = _three_offers_on_sibling_requests()

    validate_success(
        api_client.withdraw_match_offer(
            world["offer_b"]["id"], world["spec_headers"], {"withdraw_reason": "ADMIN"}
        )
    )

    offer = read_offer(world, world["offer_b"]["id"])
    assert offer["status"] == "WITHDRAWN", f"Expected WITHDRAWN, got {offer['status']}"
    assert offer["withdraw_reason"] == "ADMIN", (
        f"Expected withdraw_reason ADMIN, got {offer['withdraw_reason']}"
    )
    request_b = read_request(world, world["request_b"]["request"]["id"])
    assert request_b["status"] == "SCOPED", f"Expected SCOPED, got {request_b['status']}"
    assert request_b["failed_match_rounds"] == 0, (
        f"An ADMIN withdrawal must not charge a failed round, got "
        f"{request_b['failed_match_rounds']}"
    )


def test_expiry_sweep_expires_the_untouched_offer_and_leaves_reliability_alone(api):
    """PRD §3.1: "First it sweeps expiry: every match offer in the cycle still in `OFFERED`
    whose `expires_at` is at or before the logical clock moves to `EXPIRED`, releasing its
    reserved hours and its reserved slot and incrementing the owning request's
    `failed_match_rounds`, with each increment advancing that request to `SCOPED`,
    `RESCOPING` or `ABANDONED` exactly as §3.5 prescribes."
    PRD §3.5: "Expiry is the only terminal outcome that leaves the volunteer's reliability
    inputs entirely untouched — the program does not attribute an unanswered offer to the
    volunteer."

    Design: Difficulty/non_linear_state_machine/match_offer_four_terminals_diverge
    """
    world = _three_offers_on_sibling_requests()
    candidate = world["candidates"][0]
    validate_success(
        api_client.decline_match_offer(
            world["offer_a"]["id"],
            {"decline_reason": "IP_TERMS_UNACCEPTABLE"},
            candidate["volunteer_headers"],
        )
    )
    validate_success(
        api_client.withdraw_match_offer(
            world["offer_b"]["id"], world["spec_headers"], {"withdraw_reason": "ADMIN"}
        )
    )
    set_clock("2026-08-15T00:00:00Z", world["pm_headers"])

    validate_success(
        api_client.recalculate_program_cycle(world["cycle"]["id"], world["pm_headers"])
    )

    offer_c = read_offer(world, world["offer_c"]["id"])
    assert offer_c["status"] == "EXPIRED", (
        f"Expected the untouched offer to be EXPIRED, got {offer_c['status']}"
    )
    assert offer_c["responded_at"].startswith("2026-08-15T00:00:00"), (
        f"Expected responded_at stamped from the clock, got {offer_c['responded_at']}"
    )
    request_c = read_request(world, world["request_c"]["request"]["id"])
    assert request_c["status"] == "SCOPED", f"Expected SCOPED, got {request_c['status']}"
    assert request_c["failed_match_rounds"] == 1, (
        f"Expiry charges one failed round, got {request_c['failed_match_rounds']}"
    )
    volunteer = read_volunteer(world, candidate["volunteer"]["id"])
    assert volunteer["reliability_score"] == pytest.approx(0.7500, abs=1e-4), (
        f"Expected reliability_score untouched at 0.7500, got "
        f"{volunteer['reliability_score']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.7500, abs=1e-4), (
        f"Expected reliability_score_lifetime untouched at 0.7500, got "
        f"{volunteer['reliability_score_lifetime']}"
    )
    window = read_window(
        world,
        window_id=candidate["window"]["id"],
        volunteer_id=candidate["volunteer"]["id"],
    )
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.01), (
        f"All three terminals release their hold, got {window['hours_committed']}"
    )
    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved 0, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_committed"] == 0, (
        f"Expected slots_committed 0, got {cycle['slots_committed']}"
    )
    assert cycle["posture"] == "OPEN", f"Expected posture OPEN, got {cycle['posture']}"


# ---------------------------------------------------------------------------
# The SENT -> COUNTERED -> SENT negotiation cycle
# ---------------------------------------------------------------------------
def _negotiated_agreement(counters=3):
    """An engagement whose agreement has been signed once by the volunteer and then
    countered `counters` times, alternating partner and volunteer, re-sent each time."""
    world = setup_selector_world(
        [STRONG_CANDIDATE],
        clock="2026-08-10T00:00:00Z",
        deliverables=LEASE_DELIVERABLE,
        title="Vendor terms rewrite",
    )
    offer = get_success_data(
        api_client.match_project_request(world["request"]["id"], world["spec_headers"])
    )
    world["volunteer_headers"] = world["candidates"][0]["volunteer_headers"]
    world["volunteer"] = world["candidates"][0]["volunteer"]
    world["engagement"] = get_success_data(
        api_client.accept_match_offer(offer["id"], world["volunteer_headers"])
    )
    world["agreement"] = get_success_data(
        api_client.create_agreement(
            world["engagement"]["id"],
            {
                "expected_engagement_version": current_engagement_version(world),
                "ip_disposition": "ASSIGN_TO_PARTNER",
                "confidentiality_tier": "STANDARD",
                "indemnity_cap_usd": 10000.00,
            },
            world["pm_headers"],
        )
    )
    get_success_data(api_client.send_agreement(world["agreement"]["id"], world["pm_headers"]))
    world["first_signature"] = get_success_data(
        api_client.execute_agreement(world["agreement"]["id"], world["volunteer_headers"])
    )
    caps = [25000.00, 20000.00, 18000.00]
    parties = [world["partner_headers"], world["volunteer_headers"], world["partner_headers"]]
    for index in range(counters):
        get_success_data(
            api_client.counter_agreement(
                world["agreement"]["id"],
                {
                    "ip_disposition": "ASSIGN_TO_PARTNER",
                    "confidentiality_tier": "STANDARD",
                    "indemnity_cap_usd": caps[index],
                },
                parties[index],
            )
        )
        get_success_data(
            api_client.send_agreement(world["agreement"]["id"], world["pm_headers"])
        )
    return world


def test_first_execute_call_stamps_one_slot_and_leaves_the_agreement_sent(api):
    """PRD §3.6: "Each party calls it once for itself; the caller's own signature slot must
    currently be null, and the transition to `EXECUTED` only happens when the *other*
    party's slot is already stamped for the current `terms_revision_no`."
    PRD §3.6: "In practice the first call stamps one slot — `volunteer_signed_at` for the
    volunteer, `partner_signed_at` for the partner contact — and leaves the agreement in
    `SENT`; the countersign by the other party stamps the second slot and completes
    `SENT → EXECUTED`."

    Design: Difficulty/non_linear_state_machine/agreement_sent_countered_cycle_exhausts_rounds
    """
    world = _negotiated_agreement(counters=0)

    agreement = world["first_signature"]
    assert agreement["status"] == "SENT", (
        f"One signature must leave the agreement SENT, got {agreement['status']}"
    )
    assert agreement["volunteer_signed_at"] is not None, (
        "The volunteer's own slot must be stamped by her execute call"
    )
    assert agreement["partner_signed_at"] is None, (
        f"The partner slot must stay null, got {agreement['partner_signed_at']}"
    )


def test_three_alternating_counters_advance_the_terms_revision_and_clear_signatures(api):
    """PRD §3.6: "A counter moves the agreement `SENT → COUNTERED`, raises `counter_round`
    by one, sets `terms_revision_no` to `counter_round` plus one, overwrites the three
    negotiated fields with the countered values, clears both signature timestamps to null so
    that nothing signed against the old revision survives, and records `last_countered_by`
    as `VOLUNTEER` or `PARTNER` according to who countered."
    PRD §3.6: "The manager then re-sends, moving the agreement `COUNTERED → SENT` —
    permitted while `counter_round` has not passed 3 — again clearing both signature slots,
    and the cycle `SENT → COUNTERED → SENT` may run up to three times in total."

    Design: Difficulty/non_linear_state_machine/agreement_sent_countered_cycle_exhausts_rounds
    """
    world = _negotiated_agreement(counters=3)

    agreement = read_agreement(world)
    assert agreement["status"] == "SENT", (
        f"Expected the third re-send to leave the agreement SENT, got {agreement['status']}"
    )
    assert agreement["counter_round"] == 3, (
        f"Expected counter_round 3, got {agreement['counter_round']}"
    )
    assert agreement["terms_revision_no"] == 4, (
        f"Expected terms_revision_no 4, got {agreement['terms_revision_no']}"
    )
    assert agreement["indemnity_cap_usd"] == pytest.approx(18000.00, abs=0.01), (
        f"Expected the last countered cap 18000.00, got {agreement['indemnity_cap_usd']}"
    )
    assert agreement["last_countered_by"] == "PARTNER", (
        f"Expected last_countered_by PARTNER, got {agreement['last_countered_by']}"
    )
    assert agreement["volunteer_signed_at"] is None, (
        "Every counter and re-send clears the volunteer signature slot"
    )
    assert agreement["partner_signed_at"] is None, (
        "Every counter and re-send clears the partner signature slot"
    )
    engagement = read_engagement(world)
    assert engagement["work_status"] == "NOT_STARTED", (
        f"Negotiation must not start the work, got {engagement['work_status']}"
    )
    request = read_request(world)
    assert request["status"] == "ENGAGED", (
        f"Expected the request to sit at ENGAGED, got {request['status']}"
    )


def test_fourth_counter_is_refused_once_the_round_allowance_is_exhausted(api):
    """PRD §3.6: "Two conditions guard it: `counter_round` must be below 3, and the
    countering party must differ from `last_countered_by`, so the same side cannot counter
    twice in a row. A violation of either is refused with `ERR_COUNTER_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/agreement_sent_countered_cycle_exhausts_rounds
    """
    world = _negotiated_agreement(counters=3)

    response = api_client.counter_agreement(
        world["agreement"]["id"],
        {
            "ip_disposition": "ASSIGN_TO_PARTNER",
            "confidentiality_tier": "STANDARD",
            "indemnity_cap_usd": 16000.00,
        },
        world["volunteer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_COUNTER_LIMIT_EXCEEDED)


def test_same_party_cannot_counter_twice_in_a_row(api):
    """PRD §3.6: "Two conditions guard it: `counter_round` must be below 3, and the
    countering party must differ from `last_countered_by`, so the same side cannot counter
    twice in a row. A violation of either is refused with `ERR_COUNTER_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/agreement_sent_countered_cycle_exhausts_rounds
    """
    world = _negotiated_agreement(counters=1)

    response = api_client.counter_agreement(
        world["agreement"]["id"],
        {
            "ip_disposition": "ASSIGN_TO_PARTNER",
            "confidentiality_tier": "STANDARD",
            "indemnity_cap_usd": 24000.00,
        },
        world["partner_headers"],
    )

    validate_error(response, ApiErrorId.ERR_COUNTER_LIMIT_EXCEEDED)


# ---------------------------------------------------------------------------
# The OPEN -> SCORED -> REWORK_REQUESTED -> OPEN review cycle
# ---------------------------------------------------------------------------
def _review_returned_for_rework():
    world = setup_submitted_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=POLICY_DELIVERABLES,
        time_logs=FORTY_DELIVERY_HOURS,
        reported_cumulative_hours=40.00,
        title="Policy suite",
    )
    first, second = world["deliverables"]
    world["scores"] = {first["id"]: 4, second["id"]: 3}
    review = drive_review_to_outcome(world, world["scores"])
    world["round_one"] = validate_success(
        api_client.decide_quality_review(
            review["id"], world["reviewer_headers"], {"request_rework": True}
        )
    )
    return world


def test_rework_decision_pushes_the_engagement_back_and_clears_every_score(api):
    """PRD §3.8: "A decision carrying `request_rework` set to true moves the review
    `SCORED → REWORK_REQUESTED` instead, and is only available when the `outcome` is exactly
    `CONDITIONAL` and the review's `round_no` is still below 2 — on the second round a
    `CONDITIONAL` outcome can no longer ask for rework and must simply be decided."
    PRD §3.8: "The transition stamps `decided_at` and sets `rework_deadline_at` to that
    instant plus one week, the rework window being 168 hours."
    PRD §3.8: "The engagement moves back `SUBMITTED → IN_PROGRESS`, and every non-`WAIVED`
    deliverable has its `review_score` reset to null and its `review_status` reset to
    `PENDING`, so the second round scores a clean set."

    Design: Difficulty/non_linear_state_machine/quality_review_rework_cycle_returns_to_open
    """
    world = _review_returned_for_rework()

    review = world["round_one"]
    assert review["status"] == "REWORK_REQUESTED", (
        f"Expected REWORK_REQUESTED, got {review['status']}"
    )
    assert review["round_no"] == 1, f"Expected round_no 1, got {review['round_no']}"
    assert review["weighted_score"] == pytest.approx(70.00, abs=0.01), (
        f"Expected weighted_score 70.00 from 40.00 + 30.00, got {review['weighted_score']}"
    )
    assert review["outcome"] == "CONDITIONAL", (
        f"Expected outcome CONDITIONAL, got {review['outcome']}"
    )
    assert review["rework_deadline_at"].startswith("2026-08-26T00:00:00"), (
        f"Expected a 168-hour rework deadline at 2026-08-26T00:00:00Z, got "
        f"{review['rework_deadline_at']}"
    )
    engagement = read_engagement(world)
    assert engagement["work_status"] == "IN_PROGRESS", (
        f"Expected the engagement back at IN_PROGRESS, got {engagement['work_status']}"
    )
    for deliverable in read_deliverables(world):
        assert deliverable["review_score"] is None, (
            f"Expected review_score cleared, got {deliverable['review_score']}"
        )
        assert deliverable["review_status"] == "PENDING", (
            f"Expected review_status PENDING, got {deliverable['review_status']}"
        )


def test_second_review_round_decides_the_conditional_outcome_to_accepted(api):
    """PRD §3.8: "A `QualityReviewer` opens a review round on an engagement that has reached
    `SUBMITTED`. The new review is created in `status` `OPEN` with a `round_no` one greater
    than the highest among its siblings on that engagement, a `reviewer_user_id` recording
    the opening operator's `X-User-ID`, a `scored_deliverable_count` of 0, a null
    `weighted_score`, an `outcome` of `PENDING`, and null `rework_deadline_at` and
    `decided_at`."
    PRD §3.8: "A decision on a `PASS` or `CONDITIONAL` outcome without rework moves the
    review `SCORED → DECIDED` with `decided_at` stamped, sets the engagement's
    `quality_gate` to `PASSED` when the outcome was `PASS` and to `CONDITIONAL` when it was
    `CONDITIONAL`, moves the engagement `SUBMITTED → ACCEPTED`, and settles each
    deliverable: every non-`WAIVED` deliverable whose `review_score` is 3 or higher moves to
    `review_status` `ACCEPTED`, and every remaining one moves to `REJECTED`."

    Design: Difficulty/non_linear_state_machine/quality_review_rework_cycle_returns_to_open
    """
    world = _review_returned_for_rework()
    validate_success(
        api_client.submit_engagement(world["engagement"]["id"], world["volunteer_headers"])
    )

    second_round = drive_review_to_outcome(world, world["scores"])
    assert second_round["round_no"] == 2, (
        f"Expected the reopened round to be round_no 2, got {second_round['round_no']}"
    )
    decided = validate_success(
        api_client.decide_quality_review(second_round["id"], world["reviewer_headers"], {})
    )

    assert decided["status"] == "DECIDED", (
        f"On round two the rework edge is closed, so the review must be DECIDED; got "
        f"{decided['status']}"
    )
    assert decided["outcome"] == "CONDITIONAL", (
        f"Expected outcome CONDITIONAL, got {decided['outcome']}"
    )
    assert decided["scored_deliverable_count"] == 2, (
        f"Expected scored_deliverable_count 2, got {decided['scored_deliverable_count']}"
    )
    engagement = read_engagement(world)
    assert engagement["work_status"] == "ACCEPTED", (
        f"Expected the engagement at ACCEPTED, got {engagement['work_status']}"
    )
    assert engagement["quality_gate"] == "CONDITIONAL", (
        f"Expected quality_gate CONDITIONAL, got {engagement['quality_gate']}"
    )
    request = read_request(world)
    assert request["status"] == "IN_DELIVERY", (
        f"Expected the request to stay IN_DELIVERY, got {request['status']}"
    )


def test_conditional_decision_accepts_every_deliverable_scored_three_or_better(api):
    """PRD §3.8: "A decision on a `PASS` or `CONDITIONAL` outcome without rework moves the
    review `SCORED → DECIDED` with `decided_at` stamped, sets the engagement's
    `quality_gate` to `PASSED` when the outcome was `PASS` and to `CONDITIONAL` when it was
    `CONDITIONAL`, moves the engagement `SUBMITTED → ACCEPTED`, and settles each
    deliverable: every non-`WAIVED` deliverable whose `review_score` is 3 or higher moves to
    `review_status` `ACCEPTED`, and every remaining one moves to `REJECTED`."

    Design: Difficulty/non_linear_state_machine/quality_review_rework_cycle_returns_to_open
    """
    world = _review_returned_for_rework()
    validate_success(
        api_client.submit_engagement(world["engagement"]["id"], world["volunteer_headers"])
    )
    second_round = drive_review_to_outcome(world, world["scores"])
    validate_success(
        api_client.decide_quality_review(second_round["id"], world["reviewer_headers"], {})
    )

    deliverables = {d["sequence_no"]: d for d in read_deliverables(world)}
    assert deliverables[1]["review_score"] == 4, (
        f"Expected the first deliverable to carry review_score 4, got "
        f"{deliverables[1]['review_score']}"
    )
    assert deliverables[1]["review_status"] == "ACCEPTED", (
        f"A score of 4 settles as ACCEPTED, got {deliverables[1]['review_status']}"
    )
    assert deliverables[2]["review_score"] == 3, (
        f"Expected the second deliverable to carry review_score 3, got "
        f"{deliverables[2]['review_score']}"
    )
    assert deliverables[2]["review_status"] == "ACCEPTED", (
        f"A score of exactly 3 settles as ACCEPTED, got {deliverables[2]['review_status']}"
    )
