"""Two four-hop teardowns: an advocate's objection and a flagged review's freeze."""
from test_helpers import (
    add_operating_room,
    book_theatre,
    create_outcome_review,
    file_improvement_plan,
    finalize_review,
    get_chain,
    get_donor,
    get_room_listing,
    get_segment,
    refresh_program,
    setup_committed_paired_loop,
    setup_offered_segment,
    setup_segment_bookings,
    setup_validated_paired_loop,
    transition_improvement_plan,
    validate_success,
)
from test_helpers.api_client import api_client


def _room(env, room_code):
    rooms = get_room_listing(env)
    matches = [row for row in rooms if row["room_code"] == room_code]
    assert matches, f"expected room {room_code} in the program's room listing"
    return matches[0]


def _booking(env, booking_id):
    return validate_success(
        api_client.get_procedure_booking(booking_id, env["coordinator_headers"])
    )


def _object_to_donor(env, donor_id, reason_code="COERCION_CONCERN"):
    return validate_success(
        api_client.record_advocacy_determination(
            donor_id,
            {"outcome": "OBJECTED", "objection_reason_code": reason_code},
            env["advocate_headers"],
        )
    )


def test_advocate_objection_tears_down_donor_segments_chain_and_theatre():
    """PRD §3.3: "It records the reason code on the donor and then runs a four-hop
    cascade. First, the donor's `overall_status` becomes `ADVOCATE_BLOCKED`. Second,
    because the donor is blocked, every chain segment naming this donor whose status
    is `PLANNED`, `OFFER_SENT` or `ACCEPTED` moves to `WITHDRAWN`. Third, because
    those segments were withdrawn, each parent chain whose status is `DRAFT`,
    `VALIDATED`, `SUSPENDED`, `COMMITTED` or `EXECUTING` moves to `BROKEN` with a
    `break_reason_code` of `ADVOCATE_OBJECTION`, and every remaining non-withdrawn
    segment of that chain whose donor is `CHAIN_COMMITTED` releases that donor back
    to `APPROVED` or `CONDITIONAL_APPROVED` according to the donor's stored
    `final_risk_index`. Fourth, because each chain broke, every procedure booking
    belonging to any segment of that chain whose status is `ACTIVE` moves to
    `CANCELLED` with a `cancel_reason_code` of `CHAIN_BROKEN`, and each affected
    room's `reserved_minutes_total` is decremented by that booking's
    `duration_minutes`."
    PRD §3.3: "When the objection came from `ATTESTED`, the donor's
    `final_risk_index` is retained for audit rather than cleared."

    Design: Difficulty/transitive_cascade/advocate_objection_four_hop_chain_teardown
    """
    env = setup_committed_paired_loop()
    bookings = setup_segment_bookings(env, env["segment_one"]["id"])
    recovery, implant = bookings["donor_recovery"], bookings["recipient_implant"]

    assert _room(env, "OR-1")["reserved_minutes_total"] == 240
    assert _room(env, "OR-2")["reserved_minutes_total"] == 180
    assert get_chain(env, env["chain"]["id"])["committed_donor_count"] == 2

    objected = _object_to_donor(env, env["donor_one"]["id"])

    assert objected["advocacy_status"] == "OBJECTED"
    assert objected["overall_status"] == "ADVOCATE_BLOCKED"
    assert objected["objection_reason_code"] == "COERCION_CONCERN"
    assert objected["final_risk_index"] == 0.0, "the final index is retained for audit"

    assert get_segment(env, env["segment_one"]["id"])["status"] == "WITHDRAWN"
    assert get_segment(env, env["segment_two"]["id"])["status"] == "WITHDRAWN"

    chain = get_chain(env, env["chain"]["id"])
    assert chain["status"] == "BROKEN"
    assert chain["break_reason_code"] == "ADVOCATE_OBJECTION"
    assert chain["committed_donor_count"] == 0

    donor_two = get_donor(env, env["donor_two"]["id"])
    assert donor_two["overall_status"] == "APPROVED", (
        "the other donor is released, not left at CHAIN_COMMITTED"
    )

    assert _booking(env, recovery["id"])["status"] == "CANCELLED"
    assert _booking(env, recovery["id"])["cancel_reason_code"] == "CHAIN_BROKEN"
    assert _booking(env, implant["id"])["status"] == "CANCELLED"
    assert _booking(env, implant["id"])["cancel_reason_code"] == "CHAIN_BROKEN"
    assert _room(env, "OR-1")["reserved_minutes_total"] == 0
    assert _room(env, "OR-2")["reserved_minutes_total"] == 0


def test_objection_withdraws_a_segment_that_already_carries_a_live_offer():
    """PRD §3.3: "Second, because the donor is blocked, every chain segment naming
    this donor whose status is `PLANNED`, `OFFER_SENT` or `ACCEPTED` moves to
    `WITHDRAWN`."
    PRD §3.3: "Objecting is reachable from either `DISCLOSED` or `ATTESTED` — an
    advocate who has already attested may still object if new information emerges —
    requires an `objection_reason_code`, and is terminal for the advocacy dimension."
    PRD §2.9: "Summed over all chains of a program, `committed_donor_count` must
    equal the number of that program's donor candidates whose `overall_status` is
    `CHAIN_COMMITTED`."

    Design: Difficulty/transitive_cascade/advocate_objection_four_hop_chain_teardown
    """
    env = setup_offered_segment()
    assert env["segment_one"]["status"] == "OFFER_SENT"
    recovery = env["segment_one_bookings"]["donor_recovery"]

    objected = _object_to_donor(env, env["donor_one"]["id"], "DONOR_AMBIVALENCE")

    assert objected["overall_status"] == "ADVOCATE_BLOCKED"
    assert get_segment(env, env["segment_one"]["id"])["status"] == "WITHDRAWN", (
        "an OFFER_SENT segment is withdrawn just as a PLANNED one is"
    )

    chain = get_chain(env, env["chain"]["id"])
    assert chain["status"] == "BROKEN"
    assert chain["break_reason_code"] == "ADVOCATE_OBJECTION"
    assert chain["committed_donor_count"] == 0

    donor_two = get_donor(env, env["donor_two"]["id"])
    assert donor_two["overall_status"] == "APPROVED"
    assert _booking(env, recovery["id"])["status"] == "CANCELLED"
    assert _room(env, "OR-1")["reserved_minutes_total"] == 0


def test_finalizing_a_flagged_review_freezes_the_program_and_empties_the_theatre():
    """PRD §3.8: "The cascade then runs in three further hops: because the review is
    now finalized, the program's `compliance_posture` is re-derived, where a
    `FLAGGED` level drives `FROZEN` and a `WATCH` level drives `RESTRICTED`; because
    the posture entered `FROZEN`, every chain of the program whose status is `DRAFT`
    or `VALIDATED` moves to `SUSPENDED`; and because those chains are suspended,
    each of their `OFFER_SENT` segments reverts to `PLANNED` with the offer fields
    cleared and every `ACTIVE` procedure booking of *any* of their segments moves to
    `CANCELLED` with a `cancel_reason_code` of `POSTURE_FROZEN`, decrementing each
    room's `reserved_minutes_total`."
    PRD §3.8: "Otherwise `oe_ratio` is `observed_survivor_count` divided by
    `expected_survivor_count`, rounded half up to **four** decimal places, and
    `flag_level` is `FLAGGED` when `oe_ratio` is strictly below 0.85, `WATCH` when
    it is strictly below 0.95 but not below 0.85, and `NONE` otherwise."

    Design: Difficulty/transitive_cascade/flagged_outcome_review_freeze_four_hop_teardown
    """
    env = setup_validated_paired_loop()
    add_operating_room(env, "OR-1")
    room_one = _room(env, "OR-1")
    recovery = book_theatre(
        env,
        room_one["id"],
        env["segment_one"]["id"],
        "DONOR_RECOVERY",
        "2026-08-09T06:00:00Z",
        "2026-08-09T10:00:00Z",
    )
    assert _room(env, "OR-1")["reserved_minutes_total"] == 240
    assert refresh_program(env)["compliance_posture"] == "OPEN", (
        "no review has been finalized yet"
    )

    review = create_outcome_review(
        env,
        period_start_on="2025-01-01",
        period_end_on="2025-12-31",
        cohort_size=25,
        observed_survivor_count=16,
    )
    assert review["status"] == "DRAFT"
    assert refresh_program(env)["compliance_posture"] == "OPEN", (
        "a draft review does not yet affect the program's posture at all"
    )

    finalized = finalize_review(env, review["id"])

    assert finalized["status"] == "FINALIZED"
    assert finalized["expected_survivor_count"] == 20.0
    assert finalized["oe_ratio"] == 0.8
    assert finalized["flag_level"] == "FLAGGED"
    assert finalized["requires_improvement_plan"] is True

    assert refresh_program(env)["compliance_posture"] == "FROZEN"

    chain = get_chain(env, env["chain"]["id"])
    assert chain["status"] == "SUSPENDED", "a VALIDATED chain is suspended, not broken"
    assert chain["committed_donor_count"] == 0

    cancelled = _booking(env, recovery["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason_code"] == "POSTURE_FROZEN"
    assert _room(env, "OR-1")["reserved_minutes_total"] == 0

    assert get_donor(env, env["donor_one"]["id"])["overall_status"] == "APPROVED"
    assert get_donor(env, env["donor_two"]["id"])["overall_status"] == "APPROVED", (
        "the freeze cascade never touches donors"
    )


def test_accepting_the_answering_plan_restores_the_suspended_chain():
    """PRD §3.8: "Accepting moves the plan from `SUBMITTED` to `ACCEPTED`, stamps
    `decided_at` with the current logical clock, records the reason code, and
    re-derives the program's posture — the parent review's `FLAGGED` level no longer
    forces `FROZEN`, so the posture drops to `RESTRICTED` or `OPEN` and every
    `SUSPENDED` chain returns to `VALIDATED`."
    PRD §2.8: "Leaving `FROZEN` — to `RESTRICTED` when a degrading condition still
    holds, or to `OPEN` when none does — restores every `SUSPENDED` chain of that
    program to `VALIDATED` without re-running validation."
    PRD §3.7: "When the denominator is zero the figure is 100.00 — a brand-new
    program with three future-dated rows reports the vacuous 100.00 rather than
    0.00."

    Design: Difficulty/transitive_cascade/flagged_outcome_review_freeze_four_hop_teardown
    """
    env = setup_validated_paired_loop()
    add_operating_room(env, "OR-1")
    recovery = book_theatre(
        env,
        _room(env, "OR-1")["id"],
        env["segment_one"]["id"],
        "DONOR_RECOVERY",
        "2026-08-09T06:00:00Z",
        "2026-08-09T10:00:00Z",
    )
    review = create_outcome_review(
        env,
        period_start_on="2025-01-01",
        period_end_on="2025-12-31",
        cohort_size=25,
        observed_survivor_count=16,
    )
    finalize_review(env, review["id"])
    assert get_chain(env, env["chain"]["id"])["status"] == "SUSPENDED"

    plan = file_improvement_plan(env, review["id"])
    assert plan["status"] == "SUBMITTED"
    accepted = transition_improvement_plan(
        env, plan["id"], "ACCEPT", decision_reason_code="PLAN_ADEQUATE"
    )

    assert accepted["status"] == "ACCEPTED"
    assert accepted["decided_at"] is not None

    program = refresh_program(env)
    assert program["compliance_posture"] == "OPEN", (
        "no watch review, compliance at the vacuous 100.00 and no CIT breach remain"
    )
    assert get_chain(env, env["chain"]["id"])["status"] == "VALIDATED", (
        "the suspension was recoverable where a break would not have been"
    )
    assert _booking(env, recovery["id"])["status"] == "CANCELLED", (
        "the cancelled booking is not resurrected by the restore"
    )
    assert _room(env, "OR-1")["reserved_minutes_total"] == 0
