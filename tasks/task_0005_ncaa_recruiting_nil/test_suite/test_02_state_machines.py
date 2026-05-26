"""State-machine claims: initial state, terminal-state lockdown, invalid
transitions, NIL deal cyclic revision, scholarship-offer branching from
SENT (PRD §3.2, §3.4, §3.5, §3.6, §2.8).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_program, create_student_athlete, setup_certified_athlete,
    setup_program_with_certified_athlete,
    setup_program_with_sent_offer,
    setup_nil_deal_under_review,
    create_draft_offer, send_offer,
    create_nil_deal, submit_nil_deal, request_nil_deal_revision,
    enter_portal, set_clock, sweep_portal_expirations,
    make_student_athlete_headers, make_nil_reviewer_headers,
    create_scholarship_offer_payload, send_scholarship_offer_payload,
    create_nil_deal_payload,
    TEST_USERS,
)


def test_scholarship_offer_initial_state_is_draft(api):
    """PRD §3.4: "A `Coach` creates an offer by supplying the `program_id`,
    the recipient's `student_athlete_id`, and the offer's
    `annual_value_cents`. The offer is created with `status` `DRAFT`,
    `sent_at` null, and `version` 1. A draft offer does not occupy a slot."

    Design: Corner/state_machines/scholarship_offer_initial_state_is_draft
    """
    program = create_program(sport_code="FOOTBALL", scholarship_slot_cap=85)
    athlete = create_student_athlete(sport_code="FOOTBALL")
    res = api.create_scholarship_offer(
        create_scholarship_offer_payload(
            program_id=program["id"],
            student_athlete_id=athlete["id"],
            annual_value_cents=5_000_000,
        ),
        TEST_USERS["coach_headers"],
    )
    offer = validate_success(res, 201)
    assert offer["status"] == "DRAFT"
    assert offer["sent_at"] is None
    assert offer["version"] == 1

    program_after = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]),
        200,
    )
    assert program_after["slots_committed"] == 0


def test_scholarship_offer_terminal_accepted_blocks_resend(api):
    """PRD §3.4: "The recipient ... may accept the offer, transitioning
    `status` from `SENT` to `ACCEPTED`".
    PRD §2.6: "the state-machine precondition that the target row is in a
    state from which the requested transition is legal (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/scholarship_offer_terminal_state_lockdown_accept_then_send_rejected
    """
    program, athlete = setup_program_with_certified_athlete(
        sport_code="FOOTBALL", scholarship_slot_cap=85,
    )
    offer = create_draft_offer(program["id"], athlete["id"], annual_value_cents=4_000_000)
    sent = send_offer(offer["id"], program["version"])
    accept_res = api.accept_scholarship_offer(
        offer["id"], make_student_athlete_headers(athlete["id"]),
    )
    accepted = validate_success(accept_res, 200)
    assert accepted["status"] == "ACCEPTED"

    # Re-send from ACCEPTED state.
    program_after = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]),
        200,
    )
    res = api.send_scholarship_offer(
        offer["id"],
        send_scholarship_offer_payload(
            expected_program_version=program_after["version"],
        ),
        TEST_USERS["coach_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_nildeal_proposed_to_approve_rejected_invalid_state(api):
    """PRD §3.5: "Submitting for review transitions `status` from
    `PROPOSED` to `UNDER_REVIEW`".
    PRD §3.5: "The reviewer may approve the deal, transitioning `status`
    from `UNDER_REVIEW` to `APPROVED`, subject to two preconditions
    evaluated in order."
    PRD §2.6: state-machine precondition violation returns
    `ERR_INVALID_STATE`.

    Design: Corner/state_machines/nildeal_invalid_transition_proposed_to_approve_rejected
    """
    athlete = setup_certified_athlete(sport_code="WBB")
    deal = create_nil_deal(athlete, gross_value_cents=100_000)
    assert deal["status"] == "PROPOSED"

    # Skip the submit-for-review step and try to approve directly.
    res = api.approve_nil_deal(deal["id"], TEST_USERS["nil_reviewer_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_portal_expire_when_clock_advances_past_window(api):
    """PRD §2.8: "The transfer-portal expiration is itself driven by a
    separate, idempotent sweep capability that scans for any
    `TransferPortalEntry` whose `status` is `ENTERED` and whose
    `window_closes_at` is at or before `current_utc`, and transitions
    each such entry to `EXPIRED`".
    PRD §3.6: "When the sweep runs and the current clock has crossed an
    entry's `window_closes_at`, that entry transitions from `ENTERED` to
    `EXPIRED`; the athlete's `in_transfer_portal` is flipped to `false`"

    Design: Corner/state_machines/portal_expire_when_clock_advances_past_window
    """
    set_clock("2026-03-01T00:00:00Z")
    source = create_program(sport_code="MBB", school_name="Src U", scholarship_slot_cap=13)
    athlete = setup_certified_athlete(sport_code="MBB")
    entry = enter_portal(athlete, source)
    assert entry["status"] == "ENTERED"

    # Advance clock past entered_at + 45 days.
    set_clock("2026-04-20T00:00:00Z")
    sweep_portal_expirations()

    entry_after = validate_success(
        api.get_transfer_portal_entry(
            entry["id"], TEST_USERS["compliance_officer_headers"],
        ),
        200,
    )
    assert entry_after["status"] == "EXPIRED"

    athlete_after = validate_success(
        api.get_student_athlete(
            athlete["id"], TEST_USERS["compliance_officer_headers"],
        ),
        200,
    )
    assert athlete_after["in_transfer_portal"] is False


# ─── Difficulty: NILDeal cyclic revision (Rule 3, instance 1) ─────────


def test_nildeal_revision_cycle_returns_to_proposed_with_round_bump(api):
    """PRD §3.5: "The reviewer may request a revision, transitioning
    `status` from `UNDER_REVIEW` back to `PROPOSED`; this side path
    increments `review_round` by 1 and increments the deal's `version`,
    but is permitted only if the resulting `review_round` after the
    increment would be no larger than 3 — the system caps the number of
    revision cycles at three."

    Design: Difficulty/non_linear_state_machine/nildeal_cyclic_revision_loop
    """
    athlete = setup_certified_athlete(sport_code="BASEBALL")
    deal = create_nil_deal(athlete, gross_value_cents=200_000, agent_fee_pct=0.0)
    assert deal["review_round"] == 0
    submit_nil_deal(deal["id"])

    # request-revision: UNDER_REVIEW → PROPOSED, review_round 0 → 1
    rev_res = api.request_nil_deal_revision(
        deal["id"], TEST_USERS["nil_reviewer_headers"],
    )
    after_rev = validate_success(rev_res, 200)
    assert after_rev["status"] == "PROPOSED"
    assert after_rev["review_round"] == 1

    # Re-submit for review: PROPOSED → UNDER_REVIEW
    res = api.submit_nil_deal_for_review(
        deal["id"], TEST_USERS["nil_reviewer_headers"],
    )
    second_review = validate_success(res, 200)
    assert second_review["status"] == "UNDER_REVIEW"


def test_nildeal_revision_cap_three_blocks_fourth_cycle(api):
    """PRD §3.5: "permitted only if the resulting `review_round` after
    the increment would be no larger than 3 — the system caps the number
    of revision cycles at three. A request beyond this cap is rejected
    as a state-violation (`ERR_INVALID_STATE`)."

    Design: Difficulty/non_linear_state_machine/nildeal_cyclic_revision_loop
    """
    athlete = setup_certified_athlete(sport_code="BASEBALL")
    deal = create_nil_deal(athlete, gross_value_cents=200_000, agent_fee_pct=0.0)
    submit_nil_deal(deal["id"])

    # Three revision rounds (review_round 0→1, 1→2, 2→3 — all permitted).
    for expected_round in (1, 2, 3):
        rev = validate_success(api.request_nil_deal_revision(
            deal["id"], TEST_USERS["nil_reviewer_headers"]), 200)
        assert rev["review_round"] == expected_round
        submitted = validate_success(api.submit_nil_deal_for_review(
            deal["id"], TEST_USERS["nil_reviewer_headers"]), 200)
        assert submitted["status"] == "UNDER_REVIEW"

    # A 4th request would advance to review_round 4, which exceeds the cap.
    res = api.request_nil_deal_revision(
        deal["id"], TEST_USERS["nil_reviewer_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Difficulty: ScholarshipOffer branching from SENT (Rule 3, instance 2) ─


def test_scholarship_offer_sent_to_accepted_keeps_slot(api):
    """PRD §3.4: "Acceptance does not change `slots_committed`: an
    `ACCEPTED` offer continues to occupy the slot that the corresponding
    `SENT` offer was consuming."

    Design: Difficulty/non_linear_state_machine/scholarship_offer_branching_from_sent
    """
    program, athlete = setup_program_with_certified_athlete(
        sport_code="SOFTBALL", scholarship_slot_cap=12,
    )
    offer = create_draft_offer(program["id"], athlete["id"], annual_value_cents=3_000_000)
    sent = send_offer(offer["id"], program["version"])

    program_after_send = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]),
        200,
    )
    assert program_after_send["slots_committed"] == 1

    accept_res = api.accept_scholarship_offer(
        offer["id"], make_student_athlete_headers(athlete["id"]),
    )
    accepted = validate_success(accept_res, 200)
    assert accepted["status"] == "ACCEPTED"

    program_after_accept = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]),
        200,
    )
    assert program_after_accept["slots_committed"] == 1


def test_scholarship_offer_sent_to_declined_releases_slot(api):
    """PRD §3.4: "The recipient may instead decline the offer,
    transitioning `status` from `SENT` to `DECLINED`; declination releases
    the slot — the program's `slots_committed` is decremented by 1, its
    `updated_at` is refreshed, and its `version` is incremented"

    Design: Difficulty/non_linear_state_machine/scholarship_offer_branching_from_sent
    """
    program, athlete = setup_program_with_certified_athlete(
        sport_code="SOFTBALL", scholarship_slot_cap=12,
    )
    offer = create_draft_offer(program["id"], athlete["id"], annual_value_cents=3_000_000)
    send_offer(offer["id"], program["version"])

    program_mid = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]),
        200,
    )
    assert program_mid["slots_committed"] == 1

    decline_res = api.decline_scholarship_offer(
        offer["id"], make_student_athlete_headers(athlete["id"]),
    )
    declined = validate_success(decline_res, 200)
    assert declined["status"] == "DECLINED"

    program_after = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]),
        200,
    )
    assert program_after["slots_committed"] == 0
