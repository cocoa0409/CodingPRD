"""Nutrition coaching: the entitlement pool, the coach calendar and the credit-back."""

from test_helpers import (
    assert_coaching_session,
    assert_credit_split,
    billing_admin_headers,
    book_coaching_session,
    complete_coaching_session,
    create_coaching_session_payload,
    make_coach_headers,
    make_patient_headers,
    platform_admin_headers,
    read_patient,
    read_subscription,
    setup_coaching_subscription,
    validate_error,
    validate_paginated,
    validate_success,
)

COACHING_MEMBER = {"weight_kg": 86.7}
COACHING_SCREENING = {"recorded_weight_kg": 86.7, "egfr": 92.0}


def _coaching_scenario(email, name):
    return setup_coaching_subscription(
        patient={"email": email, "full_name": name, **COACHING_MEMBER},
        screening=COACHING_SCREENING,
        prescription={"units_per_cycle": 2},
    )


def test_booking_gate_counts_a_scheduled_session_as_already_spent(api):
    """PRD §3.10: "Under the **reservation-inclusive** reading,
    `coaching_credits_available` equals `coaching_credits_granted` less
    `coaching_credits_reserved` less `coaching_credits_consumed` less
    `coaching_credits_forfeited`, and a booking is permitted only while that figure is
    at least 1. A member holding four granted credits with one session already
    scheduled therefore sees three available."
    PRD §3.10: "Completion sets `completed_at` to the clock and moves one credit from
    `coaching_credits_reserved` to `coaching_credits_consumed`."

    Design: Difficulty/dual_variant_calc/coaching_credit_booking_gate_versus_settle_refund
    """
    scenario = _coaching_scenario("cam@example.com", "Cam Diaz")
    first = book_coaching_session(
        scenario["patient"]["id"],
        scenario["subscription"]["id"],
        scenario["coach"]["id"],
        scheduled_start_at="2026-06-10T16:00:00Z",
        scheduled_end_at="2026-06-10T17:00:00Z",
    )
    book_coaching_session(
        scenario["patient"]["id"],
        scenario["subscription"]["id"],
        scenario["coach"]["id"],
        scheduled_start_at="2026-06-12T16:00:00Z",
        scheduled_end_at="2026-06-12T17:00:00Z",
    )

    completed = validate_success(
        api.complete_coaching_session(
            first["id"], {}, make_coach_headers(scenario["coach"]["id"])
        )
    )
    assert completed["status"] == "COMPLETED"

    subscription = read_subscription(scenario["subscription"]["id"])
    assert_credit_split(
        subscription, granted=4, available=2, reserved=1, consumed=1, forfeited=0
    )


def test_settlement_refund_ignores_the_still_scheduled_session(api):
    """PRD §3.10: "The **completed-only** reading ignores reservations entirely:
    unused credits are `coaching_credits_granted` less `coaching_credits_consumed`,
    floored at zero. That count is multiplied by a refund rate of 1,000 cents per
    credit, and the result is capped at 4,900 cents — the add-on fee itself, so the
    credit-back can never exceed what was charged for the add-on."
    PRD §3.10: "Because this reading ignores reservations while the booking gate
    honours them, the same member with four granted credits, one consumed and one still
    scheduled is refunded for three unused credits even though one of those three is
    already committed to a session that has not yet been delivered."

    Design: Difficulty/dual_variant_calc/coaching_credit_booking_gate_versus_settle_refund
    """
    scenario = _coaching_scenario("cam2@example.com", "Cam Diaz")
    first = book_coaching_session(
        scenario["patient"]["id"],
        scenario["subscription"]["id"],
        scenario["coach"]["id"],
        scheduled_start_at="2026-06-10T16:00:00Z",
        scheduled_end_at="2026-06-10T17:00:00Z",
    )
    book_coaching_session(
        scenario["patient"]["id"],
        scenario["subscription"]["id"],
        scenario["coach"]["id"],
        scheduled_start_at="2026-06-12T16:00:00Z",
        scheduled_end_at="2026-06-12T17:00:00Z",
    )
    complete_coaching_session(first)

    priced = validate_success(
        api.invoice_billing_cycle(scenario["cycle"]["id"], {}, billing_admin_headers())
    )
    assert priced["medication_charge_cents"] == 34000
    assert priced["coaching_addon_fee_cents"] == 4900
    assert priced["dispensing_fee_cents"] == 0
    assert priced["total_due_cents"] == 38900

    settled = validate_success(
        api.settle_billing_cycle(
            scenario["cycle"]["id"], {"payment_reference": "PAY-0002"}, billing_admin_headers()
        )
    )

    assert settled["coaching_unused_credit_cents"] == 3000, (
        "granted 4 less consumed 1 refunds three credits, not the two a "
        "reservation-inclusive reading would give"
    )
    assert settled["settled_amount_cents"] == 35900
    assert read_patient(scenario["patient"]["id"])["lifetime_charged_cents"] == 35900


def test_coaching_session_abutting_the_previous_one_is_accepted(api):
    """PRD §3.10: "Coaching uses a plain half-open overlap test with no buffer
    whatsoever: a collision exists when the new session's `scheduled_start_at` falls
    earlier than the other session's `scheduled_end_at` *and* the other session's
    `scheduled_start_at` falls earlier than the new session's `scheduled_end_at`. Two
    sessions that exactly abut — one ending at the instant the next begins — therefore
    do not collide, in deliberate contrast to the buffered consult rule of §3.3."
    PRD §3.10: "A successful booking lands the session in `SCHEDULED` with
    `completed_at` null and moves one credit from `coaching_credits_available` to
    `coaching_credits_reserved`."

    Design: Difficulty/resource_temporal_overlap/coaching_zero_buffer_adjacency_on_coach_calendar
    """
    scenario = _coaching_scenario("ada@example.com", "Ada Wren")
    book_coaching_session(
        scenario["patient"]["id"],
        scenario["subscription"]["id"],
        scenario["coach"]["id"],
        scheduled_start_at="2026-06-05T16:00:00Z",
        scheduled_end_at="2026-06-05T17:00:00Z",
    )

    response = api.create_coaching_session(
        create_coaching_session_payload(
            scenario["subscription"]["id"],
            scenario["coach"]["id"],
            scheduled_start_at="2026-06-05T17:00:00Z",
            scheduled_end_at="2026-06-05T18:00:00Z",
        ),
        make_patient_headers(scenario["patient"]["id"]),
    )
    abutting = validate_success(response, 201)

    assert_coaching_session(abutting)
    assert abutting["status"] == "SCHEDULED"
    assert abutting["completed_at"] is None

    subscription = read_subscription(scenario["subscription"]["id"])
    assert_credit_split(
        subscription, granted=4, available=2, reserved=2, consumed=0, forfeited=0
    )


def test_coaching_session_overlapping_by_one_minute_collides(api):
    """PRD §3.10: "A collision is refused with `ERR_COACH_SLOT_CONFLICT` (409)."
    PRD §3.10: "3. The window must not collide with another `SCHEDULED` session of the
    same coach."

    Design: Difficulty/resource_temporal_overlap/coaching_zero_buffer_adjacency_on_coach_calendar
    """
    scenario = _coaching_scenario("ada2@example.com", "Ada Wren")
    book_coaching_session(
        scenario["patient"]["id"],
        scenario["subscription"]["id"],
        scenario["coach"]["id"],
        scheduled_start_at="2026-06-05T16:00:00Z",
        scheduled_end_at="2026-06-05T17:00:00Z",
    )
    book_coaching_session(
        scenario["patient"]["id"],
        scenario["subscription"]["id"],
        scenario["coach"]["id"],
        scheduled_start_at="2026-06-05T17:00:00Z",
        scheduled_end_at="2026-06-05T18:00:00Z",
    )

    response = api.create_coaching_session(
        create_coaching_session_payload(
            scenario["subscription"]["id"],
            scenario["coach"]["id"],
            scheduled_start_at="2026-06-05T16:59:00Z",
            scheduled_end_at="2026-06-05T17:59:00Z",
        ),
        make_patient_headers(scenario["patient"]["id"]),
    )
    validate_error(response, "ERR_COACH_SLOT_CONFLICT")

    rows, meta = validate_paginated(
        api.list_coaching_sessions(
            platform_admin_headers(), params={"coach_provider_id": scenario["coach"]["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_slot_conflict_pre_empts_the_exhausted_entitlement(api):
    """PRD §3.10: "Four gates run, in this order:"
    PRD §3.10: "A collision is refused with `ERR_COACH_SLOT_CONFLICT` (409)."
    PRD §3.10: "A booking attempted with zero available is refused with
    `ERR_COACHING_CREDITS_EXHAUSTED` (402)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_coaching_session_booking
    """
    scenario = _coaching_scenario("noa@example.com", "Noa Bell")
    for day in ("05", "06", "07", "08"):
        book_coaching_session(
            scenario["patient"]["id"],
            scenario["subscription"]["id"],
            scenario["coach"]["id"],
            scheduled_start_at=f"2026-06-{day}T16:00:00Z",
            scheduled_end_at=f"2026-06-{day}T17:00:00Z",
        )
    exhausted = read_subscription(scenario["subscription"]["id"])
    assert_credit_split(
        exhausted, granted=4, available=0, reserved=4, consumed=0, forfeited=0
    )

    response = api.create_coaching_session(
        create_coaching_session_payload(
            scenario["subscription"]["id"],
            scenario["coach"]["id"],
            scheduled_start_at="2026-06-05T16:30:00Z",
            scheduled_end_at="2026-06-05T17:30:00Z",
        ),
        make_patient_headers(scenario["patient"]["id"]),
    )

    validate_error(response, "ERR_COACH_SLOT_CONFLICT")
    assert response.json()["data"]["error_id"] != "ERR_COACHING_CREDITS_EXHAUSTED", (
        "the calendar gate runs ahead of the entitlement gate"
    )


def test_refused_overlapping_booking_reserves_no_further_credit(api):
    """PRD §3.10: "A successful booking lands the session in `SCHEDULED` with
    `completed_at` null and moves one credit from `coaching_credits_available` to
    `coaching_credits_reserved`."
    PRD §2.7: "Rules are evaluated in a strict ascending order, and the first rule that
    fails determines the response — no later rule runs, and no partial mutation is
    persisted."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_coaching_session_booking
    """
    scenario = _coaching_scenario("noa2@example.com", "Noa Bell")
    for day in ("05", "06", "07", "08"):
        book_coaching_session(
            scenario["patient"]["id"],
            scenario["subscription"]["id"],
            scenario["coach"]["id"],
            scheduled_start_at=f"2026-06-{day}T16:00:00Z",
            scheduled_end_at=f"2026-06-{day}T17:00:00Z",
        )

    validate_error(
        api.create_coaching_session(
            create_coaching_session_payload(
                scenario["subscription"]["id"],
                scenario["coach"]["id"],
                scheduled_start_at="2026-06-05T16:30:00Z",
                scheduled_end_at="2026-06-05T17:30:00Z",
            ),
            make_patient_headers(scenario["patient"]["id"]),
        ),
        "ERR_COACH_SLOT_CONFLICT",
    )

    subscription = read_subscription(scenario["subscription"]["id"])
    assert_credit_split(
        subscription, granted=4, available=0, reserved=4, consumed=0, forfeited=0
    )


def test_booking_then_cancelling_restores_the_credit_split(api):
    """PRD §2.10: "Booking a session moves one credit from available to reserved;
    cancelling that booking moves the same credit from reserved back to available."
    PRD §3.10: "Either the member or the coach may instead cancel a scheduled session,
    moving it `SCHEDULED → CANCELLED` and moving one credit from
    `coaching_credits_reserved` back to `coaching_credits_available` — restoring the
    pre-booking split exactly."

    Design: Difficulty/compensating_invariant/coaching_credits_conserved_across_book_then_cancel
    """
    scenario = _coaching_scenario("dax@example.com", "Dax Neil")
    session = book_coaching_session(
        scenario["patient"]["id"],
        scenario["subscription"]["id"],
        scenario["coach"]["id"],
        scheduled_start_at="2026-06-05T16:00:00Z",
        scheduled_end_at="2026-06-05T17:00:00Z",
    )
    booked = read_subscription(scenario["subscription"]["id"])
    assert_credit_split(booked, granted=4, available=3, reserved=1, consumed=0, forfeited=0)

    cancelled = validate_success(
        api.cancel_coaching_session(
            session["id"], {}, make_patient_headers(scenario["patient"]["id"])
        )
    )
    assert cancelled["status"] == "CANCELLED"

    restored = read_subscription(scenario["subscription"]["id"])
    assert_credit_split(
        restored, granted=4, available=4, reserved=0, consumed=0, forfeited=0
    )


def test_coaching_credit_identity_holds_at_every_observation(api):
    """PRD §2.10: "For every subscription, `coaching_credits_granted` always equals
    `coaching_credits_available` plus `coaching_credits_reserved` plus
    `coaching_credits_consumed` plus `coaching_credits_forfeited`."
    PRD §3.9: "When `coaching_addon_enabled` is true, opening that cycle also grants 4
    coaching credits, raising `coaching_credits_granted` and
    `coaching_credits_available` to 4."

    Design: Difficulty/compensating_invariant/coaching_credits_conserved_across_book_then_cancel
    """
    scenario = _coaching_scenario("dax2@example.com", "Dax Neil")
    opening = read_subscription(scenario["subscription"]["id"])
    assert_credit_split(opening, granted=4, available=4, reserved=0, consumed=0, forfeited=0)

    session = book_coaching_session(
        scenario["patient"]["id"],
        scenario["subscription"]["id"],
        scenario["coach"]["id"],
        scheduled_start_at="2026-06-05T16:00:00Z",
        scheduled_end_at="2026-06-05T17:00:00Z",
    )
    mid = read_subscription(scenario["subscription"]["id"])
    assert mid["coaching_credits_granted"] == 4
    assert mid["coaching_credits_reserved"] == 1

    validate_success(
        api.cancel_coaching_session(
            session["id"], {}, make_coach_headers(scenario["coach"]["id"])
        )
    )
    closing = read_subscription(scenario["subscription"]["id"])
    assert closing["coaching_credits_granted"] == 4
    assert closing["coaching_credits_available"] == 4


def test_fifth_booking_without_credits_is_refused(api):
    """PRD §3.10: "4. The entitlement must cover it. Under the
    **reservation-inclusive** reading, `coaching_credits_available` equals
    `coaching_credits_granted` less `coaching_credits_reserved` less
    `coaching_credits_consumed` less `coaching_credits_forfeited`, and a booking is
    permitted only while that figure is at least 1. A member holding four granted
    credits with one session already scheduled therefore sees three available. A
    booking attempted with zero available is refused with
    `ERR_COACHING_CREDITS_EXHAUSTED` (402)."

    Design: Corner/validations/coaching_booking_blocked_when_credits_exhausted_and_when_subscription_paused
    """
    scenario = _coaching_scenario("val3@example.com", "Val Three")
    for day in ("05", "06", "07", "08"):
        book_coaching_session(
            scenario["patient"]["id"],
            scenario["subscription"]["id"],
            scenario["coach"]["id"],
            scheduled_start_at=f"2026-06-{day}T16:00:00Z",
            scheduled_end_at=f"2026-06-{day}T17:00:00Z",
        )

    response = api.create_coaching_session(
        create_coaching_session_payload(
            scenario["subscription"]["id"],
            scenario["coach"]["id"],
            scheduled_start_at="2026-06-09T16:00:00Z",
            scheduled_end_at="2026-06-09T17:00:00Z",
        ),
        make_patient_headers(scenario["patient"]["id"]),
    )

    validate_error(response, "ERR_COACHING_CREDITS_EXHAUSTED")


def test_paused_subscription_pre_empts_the_entitlement_gate(api):
    """PRD §3.10: "1. The subscription must be `ACTIVE`; a `PAUSED` or `CANCELLED`
    subscription is refused with `ERR_SUBSCRIPTION_NOT_ACTIVE` (409)."
    PRD §3.9: "hop three moves every coaching session citing that voided cycle's
    `billing_cycle_id` and still in `SCHEDULED` to `FORFEITED`."
    PRD §2.10: "Forfeiture is deliberately *not* a compensating action: it moves the
    credit from reserved to forfeited, which preserves the identity while permanently
    removing the credit from availability."

    Design: Corner/validations/coaching_booking_blocked_when_credits_exhausted_and_when_subscription_paused
    """
    scenario = _coaching_scenario("val3b@example.com", "Val Three B")
    for day in ("05", "06", "07", "08"):
        book_coaching_session(
            scenario["patient"]["id"],
            scenario["subscription"]["id"],
            scenario["coach"]["id"],
            scheduled_start_at=f"2026-06-{day}T16:00:00Z",
            scheduled_end_at=f"2026-06-{day}T17:00:00Z",
        )

    validate_success(
        api.pause_subscription(
            scenario["subscription"]["id"],
            {},
            make_patient_headers(scenario["patient"]["id"]),
        )
    )
    paused = read_subscription(scenario["subscription"]["id"])
    assert paused["status"] == "PAUSED"
    assert_credit_split(paused, granted=4, available=0, reserved=0, consumed=0, forfeited=4)

    response = api.create_coaching_session(
        create_coaching_session_payload(
            scenario["subscription"]["id"],
            scenario["coach"]["id"],
            scheduled_start_at="2026-06-09T16:00:00Z",
            scheduled_end_at="2026-06-09T17:00:00Z",
        ),
        make_patient_headers(scenario["patient"]["id"]),
    )
    validate_error(response, "ERR_SUBSCRIPTION_NOT_ACTIVE")


def test_clinician_named_as_the_coach_is_refused(api):
    """PRD §3.10: "2. The named practitioner must have `provider_type` `COACH` and
    `status` `ACTIVE`; a clinician or a suspended coach is refused with
    `ERR_PROVIDER_NOT_ELIGIBLE` (422)."

    Design: Corner/validations/coaching_session_with_clinician_as_coach_rejected
    """
    scenario = _coaching_scenario("val5@example.com", "Val Five")

    response = api.create_coaching_session(
        create_coaching_session_payload(
            scenario["subscription"]["id"],
            scenario["clinician"]["id"],
            scheduled_start_at="2026-06-05T16:00:00Z",
            scheduled_end_at="2026-06-05T17:00:00Z",
        ),
        make_patient_headers(scenario["patient"]["id"]),
    )

    validate_error(response, "ERR_PROVIDER_NOT_ELIGIBLE")

    subscription = read_subscription(scenario["subscription"]["id"])
    assert_credit_split(
        subscription, granted=4, available=4, reserved=0, consumed=0, forfeited=0
    )
    rows, meta = validate_paginated(
        api.list_coaching_sessions(
            platform_admin_headers(),
            params={"subscription_id": scenario["subscription"]["id"]},
        )
    )
    assert meta["total_count"] == 0
