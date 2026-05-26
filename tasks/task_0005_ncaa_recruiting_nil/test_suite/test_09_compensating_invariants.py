"""Compensating-action invariants: scholarship slot count restored after
SEND→WITHDRAW; NIL deal review_round monotonic across submit/revision
cycles (PRD §3.4, §3.5).
"""
from test_helpers import (
    validate_success,
    ApiErrorId,
    setup_program_with_certified_athlete, setup_certified_athlete,
    create_draft_offer, send_offer,
    create_nil_deal, submit_nil_deal, request_nil_deal_revision,
    make_coach_headers, make_nil_reviewer_headers,
    reject_nil_deal_payload,
    TEST_USERS,
)


# ─── Difficulty: compensating_invariant / slots (Rule 9, instance 1) ───


def test_send_then_withdraw_restores_slots_committed(api):
    """PRD §3.4: "The coach who issued the offer may also withdraw it
    from the `SENT` state, transitioning `status` from `SENT` to
    `WITHDRAWN`; this withdrawal likewise decrements `slots_committed`,
    refreshes the program's `updated_at`, and increments the program's
    `version`, plus increments the offer's `version`."
    PRD §3.4: "On a successful send, the offer's `sent_at` is stamped
    with the current UTC instant from the system clock, the offer's
    `version` is incremented, and the issuing program's
    `slots_committed` is incremented by 1"

    Design: Difficulty/compensating_invariant/send_then_withdraw_keeps_slots_invariant
    """
    program, athlete = setup_program_with_certified_athlete(
        sport_code="FOOTBALL", scholarship_slot_cap=85,
    )
    pre_slots = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )["slots_committed"]
    assert pre_slots == 0

    offer = create_draft_offer(
        program["id"], athlete["id"], annual_value_cents=5_000_000,
    )
    sent = send_offer(offer["id"], program["version"])
    assert sent["status"] == "SENT"

    mid = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert mid["slots_committed"] == 1

    withdraw_res = api.withdraw_scholarship_offer(
        offer["id"], TEST_USERS["coach_headers"],
    )
    withdrawn = validate_success(withdraw_res, 200)
    assert withdrawn["status"] == "WITHDRAWN"

    final = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert final["slots_committed"] == 0


def test_draft_withdraw_does_not_change_slots_committed(api):
    """PRD §3.4: "The coach may additionally withdraw an offer while it
    is still `DRAFT`, transitioning `status` from `DRAFT` to
    `WITHDRAWN`; this case applies no slot change because the draft was
    never committed, but it still increments the offer's `version`."

    Design: Difficulty/compensating_invariant/send_then_withdraw_keeps_slots_invariant
    """
    program, athlete = setup_program_with_certified_athlete(
        sport_code="FOOTBALL", scholarship_slot_cap=85,
    )
    offer = create_draft_offer(
        program["id"], athlete["id"], annual_value_cents=5_000_000,
    )
    assert offer["status"] == "DRAFT"

    withdraw_res = api.withdraw_scholarship_offer(
        offer["id"], TEST_USERS["coach_headers"],
    )
    withdrawn = validate_success(withdraw_res, 200)
    assert withdrawn["status"] == "WITHDRAWN"

    program_after = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert program_after["slots_committed"] == 0


# ─── Difficulty: compensating_invariant / review_round (Rule 9, instance 2) ──


def test_nil_revision_cycle_review_round_monotonic(api):
    """PRD §3.5: "The reviewer may request a revision, transitioning
    `status` from `UNDER_REVIEW` back to `PROPOSED`; this side path
    increments `review_round` by 1 and increments the deal's `version`,
    but is permitted only if the resulting `review_round` after the
    increment would be no larger than 3 — the system caps the number of
    revision cycles at three."

    Design: Difficulty/compensating_invariant/nil_revision_cycle_preserves_review_round_monotonicity
    """
    athlete = setup_certified_athlete(sport_code="WBB", full_name="Athlete L")
    deal = create_nil_deal(athlete, gross_value_cents=200_000, agent_fee_pct=0.0)
    assert deal["review_round"] == 0

    rr0_state = validate_success(
        api.submit_nil_deal_for_review(deal["id"], TEST_USERS["nil_reviewer_headers"]), 200,
    )
    assert rr0_state["review_round"] == 0
    assert rr0_state["status"] == "UNDER_REVIEW"

    rr1_state = validate_success(
        api.request_nil_deal_revision(deal["id"], TEST_USERS["nil_reviewer_headers"]), 200,
    )
    assert rr1_state["review_round"] == 1
    assert rr1_state["status"] == "PROPOSED"

    rr1_re = validate_success(
        api.submit_nil_deal_for_review(deal["id"], TEST_USERS["nil_reviewer_headers"]), 200,
    )
    # PRD §3.5: submit-for-review increments version but does not modify
    # review_round; review_round only advances on request-revision.
    assert rr1_re["review_round"] == 1

    rr2_state = validate_success(
        api.request_nil_deal_revision(deal["id"], TEST_USERS["nil_reviewer_headers"]), 200,
    )
    assert rr2_state["review_round"] == 2

    rr2_re = validate_success(
        api.submit_nil_deal_for_review(deal["id"], TEST_USERS["nil_reviewer_headers"]), 200,
    )
    assert rr2_re["review_round"] == 2

    # Reject at review_round=2 — review_round must not change.
    rej_res = api.reject_nil_deal(
        deal["id"],
        reject_nil_deal_payload(rejection_reason="BRAND_PROHIBITED"),
        TEST_USERS["nil_reviewer_headers"],
    )
    rejected = validate_success(rej_res, 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["review_round"] == 2


def test_nil_revision_round_advances_only_on_request_revision(api):
    """PRD §3.5: "Submitting for review transitions `status` from
    `PROPOSED` to `UNDER_REVIEW`; the precondition is that the deal's
    athlete has `eligibility_status` equal to `CERTIFIED`, with a
    violation rejected as `ERR_ATHLETE_NOT_CERTIFIED`."
    PRD §3.5: "this side path increments `review_round` by 1 and
    increments the deal's `version`"

    Design: Difficulty/compensating_invariant/nil_revision_cycle_preserves_review_round_monotonicity
    """
    athlete = setup_certified_athlete(sport_code="WBB")
    deal = create_nil_deal(athlete, gross_value_cents=100_000)
    assert deal["review_round"] == 0

    # First submit: review_round must remain 0 (only request-revision bumps it).
    after_submit = validate_success(
        api.submit_nil_deal_for_review(deal["id"], TEST_USERS["nil_reviewer_headers"]),
        200,
    )
    assert after_submit["review_round"] == 0

    # Now request-revision: review_round → 1.
    after_rev = validate_success(
        api.request_nil_deal_revision(deal["id"], TEST_USERS["nil_reviewer_headers"]),
        200,
    )
    assert after_rev["review_round"] == 1
