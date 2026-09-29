"""Every declared state machine walked once: initial states, terminal locks, branches and cascades."""
from test_helpers import (
    accept_offer,
    add_operating_room,
    add_surgeon,
    advance_clock,
    book_theatre,
    complete_transplant,
    create_active_recipient,
    create_donor_candidate_payload,
    create_finalized_flagged_review,
    create_improvement_plan_payload,
    create_outcome_review,
    create_status_update_payload,
    file_improvement_plan,
    finalize_review,
    follow_up_by_interval,
    get_chain,
    get_donor,
    get_recipient,
    get_room_listing,
    get_segment,
    refresh_program,
    run_compliance_sweep,
    send_offer,
    setup_committed_paired_loop,
    setup_donated_donor,
    setup_offered_segment,
    setup_program_with_staff,
    setup_segment_bookings,
    setup_validated_paired_loop,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId

PLANNING_FIELDS = (
    "planned_cit_minutes",
    "planned_cross_clamp_at",
    "planned_reperfusion_at",
    "planned_transport_minutes",
    "offer_sent_at",
    "offer_response_deadline_at",
)


def _room_minutes(env, room_id):
    matches = [row for row in get_room_listing(env) if row["id"] == room_id]
    assert matches, f"expected room {room_id} in the program's room listing"
    return matches[0]["reserved_minutes_total"]


def _booking(env, booking_id):
    return validate_success(
        api_client.get_procedure_booking(booking_id, env["coordinator_headers"])
    )


def _follow_up_page(env, donor_id, params=None):
    return validate_paginated(
        api_client.list_donor_follow_ups(
            donor_id, env["coordinator_headers"], params=params
        )
    )


def _review(env, review_id):
    return validate_success(
        api_client.get_outcome_review(review_id, env["quality_headers"])
    )


def test_a_freshly_referred_donor_sits_at_the_initial_state_of_every_dimension():
    """PRD §3.3: "A new donor starts with `overall_status` `REFERRED`,
    `advocacy_status` `UNASSIGNED`, both `medical_status` and `psychosocial_status` at
    `PENDING`, `disclosure_sequence` 0, `deferral_count` 0, `medical_risk_points` and
    `psychosocial_risk_points` 0, and `screening_risk_index` 0; `advocate_staff_id`,
    `disclosure_at`, `cooling_off_ends_at`, `attestation_at`, `objection_reason_code`,
    `final_risk_index` and `donated_at` are all null."
    PRD §3.3: "A donor candidate carries **three independent state dimensions** plus a
    fourth compound one."
    PRD §3.3: "It is re-derived after any change to the three dimensions or to the
    donor's chain participation, by evaluating these clauses in exactly this order and
    taking the first that matches."

    Design: Corner/state_machines/donor_candidate_initial_state_on_all_four_dimensions
    """
    env = setup_program_with_staff()
    recipient = create_active_recipient(env, mrn="R-001")

    donor = validate_success(
        api_client.create_donor_candidate(
            create_donor_candidate_payload(
                env["program_id"],
                mrn="D-001",
                abo_blood_type="O",
                age_years=41,
                intended_recipient_id=recipient["id"],
            ),
            env["coordinator_headers"],
        ),
        expected_status=201,
    )

    assert donor["advocacy_status"] == "UNASSIGNED"
    assert donor["advocate_staff_id"] is None
    assert donor["medical_status"] == "PENDING"
    assert donor["psychosocial_status"] == "PENDING"
    assert donor["overall_status"] == "REFERRED", (
        "no evaluation row exists yet, so the compound clause falls all the way through"
    )
    assert donor["disclosure_sequence"] == 0
    assert donor["disclosure_at"] is None
    assert donor["cooling_off_ends_at"] is None, (
        "the window has no start until a disclosure opens it"
    )
    assert donor["attestation_at"] is None
    assert donor["objection_reason_code"] is None
    assert donor["donated_at"] is None
    assert donor["final_risk_index"] is None
    assert donor["medical_risk_points"] == 0
    assert donor["psychosocial_risk_points"] == 0
    assert donor["screening_risk_index"] == 0
    assert donor["deferral_count"] == 0


def test_a_broken_chain_refuses_a_second_break_and_compensates_only_once():
    """PRD §3.6: "`COMPLETED` and `BROKEN` are terminal chain states and accept no
    further transition."
    PRD §2.10: "The requested transition exists for the target's current state, and no
    transition at all is accepted out of a terminal state —
    `ERR_INVALID_STATE_TRANSITION`, 409."
    PRD §3.6: "Breaking sets the chain to `BROKEN` with the reason recorded, moves
    every non-withdrawn segment whose status is `PLANNED`, `OFFER_SENT` or `ACCEPTED`
    to `WITHDRAWN`, releases every donor of this chain whose `overall_status` is
    `CHAIN_COMMITTED` back to `APPROVED` or `CONDITIONAL_APPROVED` according to that
    donor's stored `final_risk_index`, zeroes `committed_donor_count`, and moves every
    procedure booking of this chain's segments whose status is `ACTIVE` to `CANCELLED`
    with a `cancel_reason_code` of `CHAIN_BROKEN`, decrementing each room's
    `reserved_minutes_total` by that booking's `duration_minutes`."

    Design: Corner/state_machines/broken_chain_is_terminal_and_rejects_every_further_trigger
    """
    env = setup_committed_paired_loop()
    broken = validate_success(
        api_client.break_chain(
            env["chain"]["id"],
            {"break_reason_code": "LOGISTICS_FAILURE"},
            env["coordinator_headers"],
        )
    )
    assert broken["status"] == "BROKEN"

    response = api_client.break_chain(
        env["chain"]["id"],
        {"break_reason_code": "LOGISTICS_FAILURE"},
        env["coordinator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    after = get_chain(env, env["chain"]["id"])
    assert after["status"] == "BROKEN"
    assert after["break_reason_code"] == "LOGISTICS_FAILURE"
    assert after["committed_donor_count"] == 0, (
        "the compensation ran once and the refused call did not re-run it"
    )
    assert get_donor(env, env["donor_one"]["id"])["overall_status"] == "APPROVED"
    assert get_donor(env, env["donor_two"]["id"])["overall_status"] == "APPROVED"
    assert get_segment(env, env["segment_one"]["id"])["status"] == "WITHDRAWN"
    assert get_segment(env, env["segment_two"]["id"])["status"] == "WITHDRAWN"


def test_a_second_finalization_of_a_review_is_refused_rather_than_repeated():
    """PRD §3.8: "On success `status` becomes `FINALIZED` — terminal — and
    `finalized_at` is stamped with the current logical clock."
    PRD §2.10: "The requested transition exists for the target's current state, and no
    transition at all is accepted out of a terminal state —
    `ERR_INVALID_STATE_TRANSITION`, 409."
    PRD §2.8: "Then: if an unanswered flagged review exists, the posture is `FROZEN`."

    Design: Corner/state_machines/second_finalization_of_a_review_is_not_idempotent
    """
    env = setup_program_with_staff()
    review = create_outcome_review(env, cohort_size=25, observed_survivor_count=20)
    finalized = finalize_review(env, review["id"])

    assert finalized["status"] == "FINALIZED"
    assert finalized["oe_ratio"] == 1.0, "20 observed against 25 * 0.8 expected"
    assert finalized["flag_level"] == "NONE"
    assert finalized["finalized_at"].startswith("2026-08-01T00:00:00")

    response = api_client.finalize_outcome_review(review["id"], env["quality_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    after = _review(env, review["id"])
    assert after["status"] == "FINALIZED"
    assert after["finalized_at"] == finalized["finalized_at"], (
        "the refused call did not restamp the instant"
    )
    assert after["oe_ratio"] == 1.0
    assert after["flag_level"] == "NONE"
    assert refresh_program(env)["compliance_posture"] == "OPEN"


def test_a_non_quality_decline_leaves_the_chain_committed_and_allows_a_re_offer():
    """PRD §3.6: "The decline branch then forks a second time on the reason: when
    `decline_reason_code` is `DONOR_ORGAN_QUALITY`, the parent chain additionally moves
    to `BROKEN` with a `break_reason_code` of `OFFER_DECLINED_ORGAN_QUALITY` and its
    full compensating cascade runs; for any other reason code the chain keeps its status
    and only this segment is affected."
    PRD §3.6: "Offers are reachable from `PLANNED` and, as a re-offer with a fresh plan,
    from `DECLINED`; the `OFFER_SENT` to `DECLINED` to `OFFER_SENT` cycle may repeat."
    PRD §3.6: "A successful offer sets the segment to `OFFER_SENT`, stamps
    `offer_sent_at` with the current logical clock, sets `offer_response_deadline_at` to
    six hours after `offer_sent_at`, stores the three planned fields, writes
    `planned_cit_minutes`, recomputes the chain's `total_planned_cit_minutes`, and
    increments the segment's `version`."
    PRD §3.6: "A re-offer from `DECLINED` additionally clears `decline_reason_code` and
    `offer_responded_at` back to null."

    Design: Corner/state_machines/offer_decline_on_non_quality_reason_keeps_chain_and_allows_reoffer
    """
    env = setup_offered_segment()
    segment_id = env["segment_one"]["id"]
    assert env["segment_one"]["planned_cit_minutes"] == 405

    declined = validate_success(
        api_client.record_offer_response(
            segment_id,
            {"response": "DECLINE", "decline_reason_code": "RECIPIENT_UNFIT"},
            env["coordinator_headers"],
        )
    )
    assert declined["status"] == "DECLINED"
    assert get_chain(env, env["chain"]["id"])["status"] == "COMMITTED", (
        "a non-quality decline leaves the chain alone"
    )
    assert get_chain(env, env["chain"]["id"])["total_planned_cit_minutes"] == 0

    reoffered = validate_success(
        api_client.send_segment_offer(
            segment_id,
            {
                "planned_cross_clamp_at": "2026-08-09T08:00:00Z",
                "planned_reperfusion_at": "2026-08-09T13:00:00Z",
                "planned_transport_minutes": 60,
            },
            env["coordinator_headers"],
        )
    )

    assert reoffered["status"] == "OFFER_SENT"
    assert reoffered["planned_cit_minutes"] == 345, (
        "300 clamp-to-reperfusion minutes plus the 45-minute cross-match hold, "
        "replacing the earlier 405"
    )
    assert reoffered["decline_reason_code"] is None
    assert reoffered["offer_responded_at"] is None
    assert reoffered["offer_sent_at"].startswith("2026-08-09T06:00:00")
    assert reoffered["offer_response_deadline_at"].startswith("2026-08-09T12:00:00")

    chain = get_chain(env, env["chain"]["id"])
    assert chain["status"] == "COMMITTED"
    assert chain["total_planned_cit_minutes"] == 345, (
        "the self-excluding sum never double-counts the re-offered segment"
    )


def test_an_organ_quality_decline_breaks_the_chain_and_releases_every_resource():
    """PRD §3.6: "The decline branch then forks a second time on the reason: when
    `decline_reason_code` is `DONOR_ORGAN_QUALITY`, the parent chain additionally moves
    to `BROKEN` with a `break_reason_code` of `OFFER_DECLINED_ORGAN_QUALITY` and its
    full compensating cascade runs; for any other reason code the chain keeps its status
    and only this segment is affected."
    PRD §3.6: "Declining moves the segment to `DECLINED`, stamps `offer_responded_at`,
    records the `decline_reason_code`, increments the recipient's `offer_decline_count`
    by 1, recomputes the chain's `total_planned_cit_minutes` because this segment has
    now left the sum, and increments the segment's `version`."
    PRD §3.6: "Breaking sets the chain to `BROKEN` with the reason recorded, moves
    every non-withdrawn segment whose status is `PLANNED`, `OFFER_SENT` or `ACCEPTED`
    to `WITHDRAWN`, releases every donor of this chain whose `overall_status` is
    `CHAIN_COMMITTED` back to `APPROVED` or `CONDITIONAL_APPROVED` according to that
    donor's stored `final_risk_index`, zeroes `committed_donor_count`, and moves every
    procedure booking of this chain's segments whose status is `ACTIVE` to `CANCELLED`
    with a `cancel_reason_code` of `CHAIN_BROKEN`, decrementing each room's
    `reserved_minutes_total` by that booking's `duration_minutes`."

    Design: Corner/state_machines/offer_decline_on_organ_quality_conditionally_breaks_the_chain
    """
    env = setup_offered_segment()
    recovery = env["segment_one_bookings"]["donor_recovery"]
    implant = env["segment_one_bookings"]["recipient_implant"]
    assert recovery["duration_minutes"] == 240
    assert implant["duration_minutes"] == 180

    declined = validate_success(
        api_client.record_offer_response(
            env["segment_one"]["id"],
            {"response": "DECLINE", "decline_reason_code": "DONOR_ORGAN_QUALITY"},
            env["coordinator_headers"],
        )
    )

    assert declined["status"] == "DECLINED"
    assert declined["decline_reason_code"] == "DONOR_ORGAN_QUALITY"
    assert declined["offer_responded_at"].startswith("2026-08-09T06:00:00")

    chain = get_chain(env, env["chain"]["id"])
    assert chain["status"] == "BROKEN"
    assert chain["break_reason_code"] == "OFFER_DECLINED_ORGAN_QUALITY"
    assert chain["committed_donor_count"] == 0
    assert chain["total_planned_cit_minutes"] == 0

    assert get_segment(env, env["segment_two"]["id"])["status"] == "WITHDRAWN", (
        "the sibling segment is dragged down even though its own offer never went out"
    )
    assert get_donor(env, env["donor_one"]["id"])["overall_status"] == "APPROVED"
    assert get_donor(env, env["donor_two"]["id"])["overall_status"] == "APPROVED"

    for booking in (recovery, implant):
        row = _booking(env, booking["id"])
        assert row["status"] == "CANCELLED"
        assert row["cancel_reason_code"] == "CHAIN_BROKEN"

    assert _room_minutes(env, env["room_one"]["id"]) == 0
    assert _room_minutes(env, env["room_two"]["id"]) == 0
    assert get_recipient(env, env["recipient_two"]["id"])["offer_decline_count"] == 1


def test_the_chain_reaches_completed_when_its_last_segment_transplants():
    """PRD §3.7: "And the parent chain moves from `COMMITTED` to `EXECUTING` on the
    first completion, or from `EXECUTING` to `COMPLETED` when the count of
    non-withdrawn segments at `TRANSPLANTED` has reached the chain's `segment_count`; a
    chain reaching `COMPLETED` zeroes its `committed_donor_count`."
    PRD §3.7: "On success the segment moves to `TRANSPLANTED` — a terminal segment
    state — records both actual timestamps, computes `actual_cit_minutes`, and sets
    `cit_breach` to true when `actual_cit_minutes` exceeds the eighteen-hour ceiling of
    1,080 minutes and false otherwise."
    PRD §3.7: "The segment's donor moves from `CHAIN_COMMITTED` to `DONATED` with
    `donated_at` set to the current logical clock; because the donor has now donated,
    three follow-up rows are created for that donor, each in `DUE` status, with
    `interval_code` values of `SIX_MONTH`, `ONE_YEAR` and `TWO_YEAR` and `due_on`
    values of `donated_at` plus 180, 365 and 730 days respectively; and because those
    rows now exist, the program's `follow_up_compliance_pct` is recomputed and
    `compliance_posture` re-derived."
    PRD §3.7: "Every procedure booking of this segment whose status is `ACTIVE` moves
    to `COMPLETED`, and the room's `reserved_minutes_total` is left unchanged, because
    completed bookings stay in the ledger."

    Design: Corner/state_machines/chain_bubbles_up_to_completed_when_last_segment_transplants
    """
    env = setup_donated_donor()
    assert env["chain"]["status"] == "EXECUTING", "the first completion only executed"

    segment_two_id = env["segment_two"]["id"]
    second_bookings = setup_segment_bookings(env, segment_two_id, day="2026-08-10")
    advance_clock(env, "2026-08-10T06:00:00Z")
    send_offer(env, segment_two_id, "2026-08-10T07:00:00Z", "2026-08-10T13:00:00Z")
    accept_offer(env, segment_two_id)

    completed = complete_transplant(
        env, segment_two_id, "2026-08-10T07:05:00Z", "2026-08-10T13:00:00Z"
    )

    assert completed["status"] == "TRANSPLANTED"
    assert completed["actual_cit_minutes"] == 355, "no cross-match hold is added"
    assert completed["cit_breach"] is False

    chain = get_chain(env, env["chain"]["id"])
    assert chain["status"] == "COMPLETED"
    assert chain["committed_donor_count"] == 0
    assert chain["segment_count"] == 2

    donor_two = get_donor(env, env["donor_two"]["id"])
    assert donor_two["overall_status"] == "DONATED"
    assert donor_two["donated_at"].startswith("2026-08-10T06:00:00")
    assert get_donor(env, env["donor_one"]["id"])["overall_status"] == "DONATED"
    assert get_recipient(env, env["recipient_one"]["id"])["listing_status"] == "TRANSPLANTED"

    rows, meta = _follow_up_page(env, env["donor_two"]["id"])
    assert meta["total_count"] == 3
    by_interval = {row["interval_code"]: row for row in rows}
    assert by_interval["SIX_MONTH"]["due_on"].startswith("2027-02-06")
    assert by_interval["ONE_YEAR"]["due_on"].startswith("2027-08-10")
    assert by_interval["TWO_YEAR"]["due_on"].startswith("2028-08-09")

    program = refresh_program(env)
    assert program["cit_breach_count"] == 0
    assert program["compliance_posture"] == "OPEN"

    assert _booking(env, second_bookings["donor_recovery"]["id"])["status"] == "COMPLETED"
    assert _room_minutes(env, env["room_one"]["id"]) == 480, (
        "two completed 240-minute recoveries both stay in the ledger"
    )


def test_a_suspended_chain_returns_to_validated_without_being_revalidated():
    """PRD §3.8: "Accepting moves the plan from `SUBMITTED` to `ACCEPTED`, stamps
    `decided_at` with the current logical clock, records the reason code, and re-derives
    the program's posture — the parent review's `FLAGGED` level no longer forces
    `FROZEN`, so the posture drops to `RESTRICTED` or `OPEN` and every `SUSPENDED` chain
    returns to `VALIDATED`."
    PRD §2.8: "Leaving `FROZEN` — to `RESTRICTED` when a degrading condition still
    holds, or to `OPEN` when none does — restores every `SUSPENDED` chain of that
    program to `VALIDATED` without re-running validation."
    PRD §3.8: "The cascade then runs in three further hops: because the review is now
    finalized, the program's `compliance_posture` is re-derived, where a `FLAGGED` level
    drives `FROZEN` and a `WATCH` level drives `RESTRICTED`; because the posture entered
    `FROZEN`, every chain of the program whose status is `DRAFT` or `VALIDATED` moves to
    `SUSPENDED`; and because those chains are suspended, each of their `OFFER_SENT`
    segments reverts to `PLANNED` with the offer fields cleared and every `ACTIVE`
    procedure booking of *any* of their segments moves to `CANCELLED` with a
    `cancel_reason_code` of `POSTURE_FROZEN`, decrementing each room's
    `reserved_minutes_total`."

    Design: Corner/state_machines/suspended_chain_returns_to_validated_when_plan_is_accepted
    """
    env = setup_validated_paired_loop()
    validated_at = env["chain"]["validated_at"]
    assert env["chain"]["status"] == "VALIDATED"
    assert validated_at.startswith("2026-08-08T00:00:00")

    review = create_finalized_flagged_review(
        env, cohort_size=25, observed_survivor_count=16
    )
    assert review["oe_ratio"] == 0.8, "16 observed against 25 * 0.8 expected"
    assert review["flag_level"] == "FLAGGED"
    assert refresh_program(env)["compliance_posture"] == "FROZEN"
    assert get_chain(env, env["chain"]["id"])["status"] == "SUSPENDED"

    plan = file_improvement_plan(env, review["id"])
    accepted = validate_success(
        api_client.transition_improvement_plan(
            plan["id"],
            {"action": "ACCEPT", "decision_reason_code": "PLAN_ADEQUATE"},
            env["admin_headers"],
        )
    )

    assert accepted["status"] == "ACCEPTED"
    assert accepted["decision_reason_code"] == "PLAN_ADEQUATE"
    assert accepted["decided_at"].startswith("2026-08-08T00:00:00")
    assert refresh_program(env)["compliance_posture"] == "OPEN"

    restored = get_chain(env, env["chain"]["id"])
    assert restored["status"] == "VALIDATED"
    assert restored["validated_at"] == validated_at, (
        "the restore did not re-run validation and did not restamp validated_at"
    )
    assert restored["segment_count"] == 2
    assert restored["is_closed_loop"] is True


def test_placing_the_recipient_on_hold_reverts_the_offered_segment_to_planned():
    """PRD §3.2: "Placing an active candidate on hold reverts each of that candidate's
    chain segments that currently sits at `OFFER_SENT` back to `PLANNED`, clearing that
    segment's `planned_cit_minutes`, `planned_cross_clamp_at`, `planned_reperfusion_at`,
    `planned_transport_minutes`, `offer_sent_at` and `offer_response_deadline_at` to
    null — an offer cannot stand for a recipient who is not currently listed."
    PRD §3.6: "`total_planned_cit_minutes` on a chain is the sum of
    `planned_cit_minutes` over that chain's segments whose status is `OFFER_SENT`,
    `ACCEPTED` or `TRANSPLANTED`, accumulated in `position` ascending and, for ties,
    `created_at` ascending order."
    PRD §3.2: "The seconds of every merged window are summed, and the whole-day floor
    is applied once to that total."

    Design: Corner/state_machines/recipient_hold_reverts_offer_sent_segment_to_planned
    """
    env = setup_offered_segment()
    assert get_chain(env, env["chain"]["id"])["total_planned_cit_minutes"] == 405

    held = validate_success(
        api_client.create_recipient_status_update(
            env["recipient_two"]["id"],
            create_status_update_payload(
                "INACTIVE_HOLD", "MEDICALLY_UNFIT", "2026-08-09T06:00:00Z"
            ),
            env["coordinator_headers"],
        )
    )

    assert held["listing_status"] == "INACTIVE_HOLD"
    assert held["active_days_total"] == 8, (
        "eight and a quarter days listed, floored once to 8"
    )

    segment = get_segment(env, env["segment_one"]["id"])
    assert segment["status"] == "PLANNED"
    for field in PLANNING_FIELDS:
        assert segment[field] is None, f"{field} is cleared, not merely ignored"

    chain = get_chain(env, env["chain"]["id"])
    assert chain["total_planned_cit_minutes"] == 0
    assert chain["status"] == "COMMITTED", "the chain itself is untouched by the hold"

    _rows, meta = validate_paginated(
        api_client.list_waitlist_events(
            env["recipient_two"]["id"], env["coordinator_headers"]
        )
    )
    assert meta["total_count"] == 3
    assert get_donor(env, env["donor_one"]["id"])["overall_status"] == "CHAIN_COMMITTED"


def test_removing_a_recipient_withdraws_only_its_own_segment_and_breaks_the_chain():
    """PRD §3.2: "Removing a candidate, from either `ACTIVE` or `INACTIVE_HOLD`,
    cascades in two hops: first, every chain segment of that recipient whose status is
    `PLANNED`, `OFFER_SENT` or `ACCEPTED` moves to `WITHDRAWN`; second, because those
    segments have been withdrawn, each parent chain whose status is `DRAFT`,
    `VALIDATED`, `SUSPENDED`, `COMMITTED` or `EXECUTING` moves to `BROKEN` with a
    `break_reason_code` of `RECIPIENT_REMOVED`, dragging its own compensating cascade
    behind it."
    PRD §3.2: "Waitlist events are listed for a candidate in `effective_at` order."
    PRD §3.2: "`DECLINED`, `TRANSPLANTED` and `REMOVED` are terminal and accept no
    further update."

    Design: Corner/state_machines/recipient_removal_cascades_down_to_segment_and_chain
    """
    env = setup_validated_paired_loop()

    removed = validate_success(
        api_client.create_recipient_status_update(
            env["recipient_one"]["id"],
            create_status_update_payload(
                "REMOVED", "PATIENT_WITHDREW", "2026-08-08T00:00:00Z"
            ),
            env["coordinator_headers"],
        )
    )

    assert removed["listing_status"] == "REMOVED"
    assert removed["active_days_total"] == 7

    assert get_segment(env, env["segment_two"]["id"])["status"] == "WITHDRAWN", (
        "R-001 was the recipient of the second segment"
    )
    chain = get_chain(env, env["chain"]["id"])
    assert chain["status"] == "BROKEN"
    assert chain["break_reason_code"] == "RECIPIENT_REMOVED"
    assert chain["committed_donor_count"] == 0

    assert get_donor(env, env["donor_one"]["id"])["overall_status"] == "APPROVED"
    assert get_donor(env, env["donor_two"]["id"])["overall_status"] == "APPROVED"

    events, meta = validate_paginated(
        api_client.list_waitlist_events(
            env["recipient_one"]["id"], env["coordinator_headers"]
        )
    )
    assert meta["total_count"] == 3
    assert events[2]["to_status"] == "REMOVED"
    assert get_recipient(env, env["recipient_two"]["id"])["listing_status"] == "ACTIVE"


def test_completed_bookings_keep_room_minutes_while_a_cancellation_releases_them():
    """PRD §3.7: "Every procedure booking of this segment whose status is `ACTIVE`
    moves to `COMPLETED`, and the room's `reserved_minutes_total` is left unchanged,
    because completed bookings stay in the ledger."
    PRD §3.6: "Cancellation sets `status` to `CANCELLED`, records the reason,
    decrements the room's `reserved_minutes_total` by exactly this booking's
    `duration_minutes` once, and increments the booking's `version`."
    PRD §3.6: "It is only accepted while the booking is `ACTIVE` — a booking already
    `CANCELLED` or `COMPLETED` is refused with `ERR_BOOKING_NOT_ACTIVE` — and only while
    the segment has not reached `TRANSPLANTED`."

    Design: Corner/state_machines/booking_completion_keeps_room_minutes_while_cancellation_releases_them
    """
    env = setup_committed_paired_loop()
    env["room_one"] = add_operating_room(env, "OR-1")
    surgeon_two = add_surgeon(env)
    second_segment_booking = book_theatre(
        env,
        env["room_one"]["id"],
        env["segment_two"]["id"],
        "DONOR_RECOVERY",
        "2026-08-09T12:00:00Z",
        "2026-08-09T14:00:00Z",
        surgeon_id=surgeon_two["id"],
    )
    assert second_segment_booking["duration_minutes"] == 120

    setup_donated_donor(env)
    first_recovery = env["segment_one_bookings"]["donor_recovery"]
    assert _room_minutes(env, env["room_one"]["id"]) == 360, "240 completed plus 120 active"

    cancelled = validate_success(
        api_client.cancel_procedure_booking(
            second_segment_booking["id"],
            {"cancel_reason_code": "SURGEON_UNAVAILABLE"},
            env["coordinator_headers"],
        )
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason_code"] == "SURGEON_UNAVAILABLE"
    assert cancelled["duration_minutes"] == 120
    assert _room_minutes(env, env["room_one"]["id"]) == 240, (
        "360 minus the cancelled 120, with the completed 240 still reserved"
    )
    assert _booking(env, first_recovery["id"])["status"] == "COMPLETED"
    assert _room_minutes(env, env["room_two"]["id"]) == 180, (
        "the completed implant booking also stays reserved"
    )

    segment_one = get_segment(env, env["segment_one"]["id"])
    assert segment_one["status"] == "TRANSPLANTED"
    assert segment_one["actual_cit_minutes"] == 355


def test_filing_a_newer_plan_supersedes_the_rejected_one():
    """PRD §3.8: "Creation puts the new plan in `SUBMITTED` with
    `decision_reason_code`, `decided_at` and `closed_at` all null, moves any existing
    plan of the same review whose status is `SUBMITTED` or `REJECTED` to `SUPERSEDED` —
    which the system will only do while no plan of that review has already reached
    `ACCEPTED` or `CLOSED` — and increments the parent review's `version` so that a
    competing writer holding the old value is now stale."
    PRD §3.8: "Rejecting moves the plan from `SUBMITTED` to `REJECTED`, stamps
    `decided_at`, records the reason code, and re-derives the posture, which stays
    `FROZEN` while the flagged review remains unanswered."
    PRD §3.8: "The system may nonetheless move a rejected plan to `SUPERSEDED` when a
    newer plan is filed for the same review."

    Design: Corner/state_machines/newer_improvement_plan_supersedes_the_rejected_one
    """
    env = setup_program_with_staff()
    review = create_finalized_flagged_review(
        env, cohort_size=25, observed_survivor_count=16
    )
    assert review["flag_level"] == "FLAGGED"
    assert refresh_program(env)["compliance_posture"] == "FROZEN"

    plan_one = file_improvement_plan(env, review["id"])
    version_after_first_plan = _review(env, review["id"])["version"]

    rejected = validate_success(
        api_client.transition_improvement_plan(
            plan_one["id"],
            {"action": "REJECT", "decision_reason_code": "INSUFFICIENT_DETAIL"},
            env["admin_headers"],
        )
    )
    assert rejected["status"] == "REJECTED"

    plan_two = validate_success(
        api_client.create_improvement_plan(
            create_improvement_plan_payload(
                review["id"],
                _review(env, review["id"])["version"],
                title="Second attempt",
                milestone_count=5,
                target_completion_on="2027-03-31",
            ),
            env["quality_headers"],
        ),
        expected_status=201,
    )

    assert plan_two["status"] == "SUBMITTED"
    assert plan_two["milestone_count"] == 5
    assert plan_two["decided_at"] is None
    assert plan_two["decision_reason_code"] is None
    assert plan_two["closed_at"] is None

    plans, meta = validate_paginated(
        api_client.list_review_improvement_plans(review["id"], env["quality_headers"])
    )
    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in plans}
    assert by_id[plan_one["id"]]["status"] == "SUPERSEDED", (
        "a REJECTED plan is superseded too, not only a SUBMITTED one"
    )
    assert by_id[plan_one["id"]]["decision_reason_code"] == "INSUFFICIENT_DETAIL"

    assert refresh_program(env)["compliance_posture"] == "FROZEN", (
        "only a plan at ACCEPTED or CLOSED answers a flagged review"
    )
    assert _review(env, review["id"])["version"] > version_after_first_plan


def test_waiving_a_follow_up_removes_it_from_both_sides_of_compliance():
    """PRD §3.7: "A `ProgramAdmin` may instead waive an interval by supplying a
    `waiver_reason_code`; waiver is reachable from `DUE`, `INCOMPLETE` and `DELINQUENT`,
    sets the row to `WAIVED` — a terminal state — records the reason, recomputes the
    program's compliance figure, re-derives posture, and increments the row's
    `version`."
    PRD §3.7: "A `WAIVED` row leaves **both** the numerator and the denominator, which
    means waiving a delinquent interval raises compliance without ever counting as a
    submission."
    PRD §3.7: "When the denominator is zero the figure is 100.00 — a brand-new program
    with three future-dated rows reports the vacuous 100.00 rather than 0.00."
    PRD §2.8: "Otherwise, if `follow_up_compliance_pct` is strictly below the program's
    `follow_up_compliance_threshold_pct`, or an open watch exists, or `cit_breach_count`
    is at least 2, the posture is `RESTRICTED`."

    Design: Corner/state_machines/follow_up_waiver_removes_the_row_from_both_sides_of_compliance
    """
    env = setup_donated_donor()
    donor_id = env["donor_one"]["id"]
    advance_clock(env, "2027-02-06T00:00:00Z")
    swept = run_compliance_sweep(env)
    assert swept["follow_up_compliance_pct"] == 0.0, (
        "one countable row, none submitted"
    )
    assert swept["compliance_posture"] == "RESTRICTED"

    six_month = follow_up_by_interval(env, donor_id, "SIX_MONTH")
    assert six_month["due_on"].startswith("2027-02-05")

    waived = validate_success(
        api_client.waive_follow_up(
            six_month["id"],
            {"waiver_reason_code": "DONOR_UNREACHABLE"},
            env["admin_headers"],
        )
    )

    assert waived["status"] == "WAIVED"
    assert waived["waiver_reason_code"] == "DONOR_UNREACHABLE"
    assert waived["submitted_at"] is None, "a waiver is not a submission"
    assert waived["completeness_pct"] == 0

    program = refresh_program(env)
    assert program["follow_up_compliance_pct"] == 100.0, (
        "the row left the denominator, so the figure is vacuously 100.00"
    )
    assert program["compliance_posture"] == "OPEN"

    _rows, meta = _follow_up_page(env, donor_id, params={"status": "DUE"})
    assert meta["total_count"] == 2


def test_the_sweep_marks_a_due_row_delinquent_only_once_the_grace_has_run():
    """PRD §3.7: "A compliance sweep moves any row still at `DUE` or `INCOMPLETE` to
    `DELINQUENT` once the logical clock has reached thirty days past that row's
    `due_on`."
    PRD §3.1: "The grace period is thirty days past an interval's `due_on`: the sweep
    only declares an interval delinquent once the logical clock has reached or passed
    that thirtieth day."
    PRD §3.7: "The denominator is the count of follow-up rows whose donor belongs to
    this program, whose `status` is one of `DUE`, `SUBMITTED_COMPLETE`, `INCOMPLETE` or
    `DELINQUENT`, and whose `due_on` is at or before the current logical clock."

    Design: Corner/state_machines/compliance_sweep_marks_due_follow_up_delinquent_only_after_grace
    """
    env = setup_donated_donor()
    donor_id = env["donor_one"]["id"]

    advance_clock(env, "2027-03-06T06:00:00Z")
    first = run_compliance_sweep(env)
    assert first["last_sweep_at"].startswith("2027-03-06T06:00:00")
    assert follow_up_by_interval(env, donor_id, "SIX_MONTH")["status"] == "DUE", (
        "twenty-nine days past due_on is still inside the grace period"
    )

    advance_clock(env, "2027-03-07T06:00:00Z")
    second = validate_success(
        api_client.run_compliance_sweep(env["program_id"], env["quality_headers"])
    )

    assert second["last_sweep_at"].startswith("2027-03-07T06:00:00")
    assert follow_up_by_interval(env, donor_id, "SIX_MONTH")["status"] == "DELINQUENT", (
        "exactly the thirtieth day flips the row"
    )
    assert second["follow_up_compliance_pct"] == 0.0, "denominator 1, numerator 0"
    assert second["compliance_posture"] == "RESTRICTED"

    _rows, meta = _follow_up_page(env, donor_id, params={"status": "DUE"})
    assert meta["total_count"] == 2, "the one-year and two-year rows are not yet due"
