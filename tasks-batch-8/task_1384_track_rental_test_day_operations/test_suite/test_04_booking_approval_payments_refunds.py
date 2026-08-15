"""Booking approval gates, payment ordering, and cancellation refunds."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_track, make_open_track_day, make_block, make_booking, make_coach,
    approve_booking, pay_booking, get_block, get_booking, block_version,
    set_clock, setup_open_day_with_block, setup_suspended_day_via_noise,
    setup_approved_paid_booking, make_garage_assignment, assign_coach,
    FEE_PER_DRIVER_CENTS, WEATHER_FACILITY_FEE_CENTS,
    TEST_USERS, make_organizer_headers,
)

OPS = TEST_USERS["trackops_headers"]


def _setup_paid_booking_on_day(tid, date, organizer, driver_count=2):
    """Open a day, create a block [540,600), approve + capture a booking."""
    day = make_open_track_day(tid, date)
    block = make_block(tid, day["id"], start_minute=540, end_minute=600)
    booking = make_booking(tid, day["id"], block["id"], organizer,
                           driver_count=driver_count)
    approve_booking(tid, day["id"], block["id"], booking["id"])
    pay_booking(booking["id"], capture=True)
    return day, block, booking


def test_insurance_missing_blocks_approve(api):
    """PRD §3.3: "Only then come the fiscal checks, in this order: seating,
    where a `driver_count` exceeding the block's current `seats_available` is
    rejected with `ERR_BLOCK_FULL` (409); and insurance, where a missing or
    empty `insurance_policy_ref` is rejected with `ERR_INSURANCE_MISSING`
    (422)."

    Design: Corner/validations/insurance_missing_blocks_approve
    """
    env = setup_open_day_with_block("2026-09-22")
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    booking = make_booking(tid, tdid, rbid, "oV3", insurance_policy_ref="")
    resp = api.approve_booking(
        tid, tdid, rbid, booking["id"],
        {"expected_rental_block_version": block_version(tid, tdid, rbid)}, OPS)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_MISSING)


def test_payments_capture_from_unpaid_rejected(api):
    """PRD §3.3: "The `payment_status` vocabulary is `UNPAID`, `AUTHORIZED`,
    `CAPTURED`, `REFUNDED`, and `FORFEITED`, and the simulation walks it in
    steps: outcome `AUTHORIZE` moves `UNPAID` to `AUTHORIZED`; `CAPTURE` moves
    `AUTHORIZED` to `CAPTURED`, and capturing from any other state is rejected
    with `ERR_INVALID_STATE` (409); `VOID` drops an `AUTHORIZED` payment back
    to `UNPAID`; `REFUND` moves `CAPTURED` to `REFUNDED`."

    Design: Corner/endpoints/payments_simulate_invalid_state_unpaid_to_capture
    """
    env = setup_open_day_with_block("2026-09-29")
    booking = make_booking(env["track"]["id"], env["day"]["id"],
                           env["block"]["id"], "oE1")
    assert booking["payment_status"] == "UNPAID"
    resp = api.simulate_payment({"booking_id": booking["id"],
                                 "outcome": "CAPTURE"}, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_approve_on_suspended_day_rejected(api):
    """PRD §2.7: "Posture gates forward progress: while a day's `posture` is
    `SUSPENDED`, booking approvals, session starts, garage assignment
    creation, and coach assignments are rejected with `ERR_TRACK_SUSPENDED`
    (409)." PRD §3.3: "Fourth, posture: a `SUSPENDED` day rejects with
    `ERR_TRACK_SUSPENDED` (409)."

    Design: Difficulty/cross_entity_state_dependency/booking_approve_gated_by_trackday_posture
    """
    env = setup_suspended_day_via_noise("2026-09-04")
    tid, tdid = env["track"]["id"], env["day"]["id"]
    assert env["day"]["posture"] == "SUSPENDED"
    booking = make_booking(tid, tdid, env["block"]["id"], "org13")
    resp = api.approve_booking(
        tid, tdid, env["block"]["id"], booking["id"],
        {"expected_rental_block_version": block_version(
            tid, tdid, env["block"]["id"])}, OPS)
    validate_error(resp, ApiErrorId.ERR_TRACK_SUSPENDED)


def test_rejected_approve_leaves_booking_and_block_untouched(api):
    """PRD §3.3: "A successful approval stamps `approval_status` `APPROVED`,
    adds the booking's `driver_count` to the block's `seats_reserved` —
    flipping the block to `FULL` when the seats exactly fill — freezes the
    cancellation-policy thresholds into `cancel_policy_snapshot`, and advances
    the block's `version` by one." PRD §2.7: "Posture gates forward progress:
    while a day's `posture` is `SUSPENDED`, booking approvals, session starts,
    garage assignment creation, and coach assignments are rejected with
    `ERR_TRACK_SUSPENDED` (409)."

    Design: Difficulty/cross_entity_state_dependency/booking_approve_gated_by_trackday_posture
    """
    env = setup_suspended_day_via_noise("2026-09-04")
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    booking = make_booking(tid, tdid, rbid, "org13")
    resp = api.approve_booking(
        tid, tdid, rbid, booking["id"],
        {"expected_rental_block_version": block_version(tid, tdid, rbid)}, OPS)
    validate_error(resp, ApiErrorId.ERR_TRACK_SUSPENDED)
    booking_after = get_booking(tid, tdid, rbid, booking["id"])
    assert booking_after["approval_status"] == "PENDING"
    block_after = get_block(tid, tdid, rbid)
    assert block_after["seats_reserved"] == 0, \
        "a rejected approval must not consume seats"


def test_customer_cancel_inside_24h_window_refunds_zero(api):
    """PRD §3.9: "The refund math runs on the fee — 35,000 cents per declared
    driver, multiplied by the booking's `driver_count` — and on the notice
    window: the whole-hour difference, rounded down, between the current
    logical time and the block's start (its `start_minute` on the track day's
    `date`)." and "The chronological variant, used for `CUSTOMER`, pays the
    full fee when at least 72 hours of notice remain, half the fee when at
    least 24 but fewer than 72 hours remain, and nothing when fewer than 24
    hours remain, with the applicable percentage applied to the fee and
    rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/cancel_refund_chronological_vs_weather
    """
    set_clock("2026-08-01T00:00:00Z")
    track = make_track(name="Laguna", noise_limit_db=95)
    day, block, booking = _setup_paid_booking_on_day(
        track["id"], "2026-08-15", "org1", driver_count=2)
    # Block starts 2026-08-15 09:00 UTC (minute 540); 12h notice < 24h band.
    set_clock("2026-08-14T21:00:00Z")
    resp = api.cancel_booking(track["id"], day["id"], block["id"],
                              booking["id"], {"reason": "CUSTOMER"},
                              make_organizer_headers("org1"))
    data = validate_success(resp)
    assert data["approval_status"] == "CANCELLED"
    assert data["refund_cents"] == 0, \
        "fewer than 24 hours of notice pays nothing under CUSTOMER"


def test_weather_day_cancel_refunds_three_quarters_minus_fee(api):
    """PRD §3.9: "The weather variant, forced by `WEATHER`, pays three
    quarters of the fee — rounded half-up — minus a flat 5,000-cent facility
    fee, floored at zero, independent of notice." and "Every door writes
    `cancelled_reason`, sets the day `CANCELLED`, and cascades all bookings on
    the day to `CANCELLED` with refunds computed under the variant the reason
    forces". PRD §3.9: "From `WEATHER_HOLD`, the day may be cancelled with
    `reason` `WEATHER`."

    Design: Difficulty/dual_variant_calc/cancel_refund_chronological_vs_weather
    """
    set_clock("2026-08-01T00:00:00Z")
    track = make_track(name="Laguna", noise_limit_db=95)
    # Identical booking on two separate days: fee = 2 * 35000 = 70000 each.
    day_a, block_a, booking_a = _setup_paid_booking_on_day(
        track["id"], "2026-08-15", "org1", driver_count=2)
    day_b, block_b, booking_b = _setup_paid_booking_on_day(
        track["id"], "2026-08-16", "org2", driver_count=2)
    # Booking A: CUSTOMER cancel with 12h notice -> chronological 0% band.
    set_clock("2026-08-14T21:00:00Z")
    cancelled_a = validate_success(api.cancel_booking(
        track["id"], day_a["id"], block_a["id"], booking_a["id"],
        {"reason": "CUSTOMER"}, make_organizer_headers("org1")))
    # Day B: weather hold, then WEATHER cancel forces the weather variant.
    validate_success(api.weather_hold(track["id"], day_b["id"], OPS))
    validate_success(api.cancel_track_day(track["id"], day_b["id"],
                                          {"reason": "WEATHER"}, OPS))
    cancelled_b = get_booking(track["id"], day_b["id"], block_b["id"],
                              booking_b["id"])
    assert cancelled_b["approval_status"] == "CANCELLED"
    expected_weather = round(2 * FEE_PER_DRIVER_CENTS * 0.75) \
        - WEATHER_FACILITY_FEE_CENTS  # 52500 - 5000
    assert cancelled_b["refund_cents"] == expected_weather
    assert cancelled_a["refund_cents"] == 0
    assert cancelled_a["refund_cents"] != cancelled_b["refund_cents"], \
        "identical fee inputs must price differently across the two variants"


def test_weather_refund_rounds_then_subtracts_fee_single_driver(api):
    """PRD §3.9: "The weather variant, forced by `WEATHER`, pays three
    quarters of the fee — rounded half-up — minus a flat 5,000-cent facility
    fee, floored at zero, independent of notice." PRD §2.8: "All monetary
    amounts in the system are integer cents — no fractional cents appear
    anywhere. Refund computations that would produce a fractional cent round
    half-up to the nearest whole cent."

    Design: Difficulty/combinatorial_formula/cancel_refund_nested_rounding
    """
    env = setup_approved_paid_booking("2026-08-25", "org4",
                                      booking_overrides={"driver_count": 1})
    tid, tdid = env["track"]["id"], env["day"]["id"]
    validate_success(api.weather_hold(tid, tdid, OPS))
    validate_success(api.cancel_track_day(tid, tdid, {"reason": "WEATHER"}, OPS))
    booking = get_booking(tid, tdid, env["block"]["id"], env["booking"]["id"])
    # round_half_up(35000 * 0.75) = 26250 first, then minus the 5000 fee.
    assert booking["refund_cents"] == 26250 - WEATHER_FACILITY_FEE_CENTS


def test_weather_refund_rounds_then_subtracts_fee_three_drivers(api):
    """PRD §3.9: "The refund math runs on the fee — 35,000 cents per declared
    driver, multiplied by the booking's `driver_count`". PRD §3.9: "The
    weather variant, forced by `WEATHER`, pays three quarters of the fee —
    rounded half-up — minus a flat 5,000-cent facility fee, floored at zero,
    independent of notice."

    Design: Difficulty/combinatorial_formula/cancel_refund_nested_rounding
    """
    env = setup_approved_paid_booking(
        "2026-08-25", "org4", block_overrides={"max_group_size": 5},
        booking_overrides={"driver_count": 3})
    tid, tdid = env["track"]["id"], env["day"]["id"]
    validate_success(api.weather_hold(tid, tdid, OPS))
    validate_success(api.cancel_track_day(tid, tdid, {"reason": "WEATHER"}, OPS))
    booking = get_booking(tid, tdid, env["block"]["id"], env["booking"]["id"])
    # round_half_up(105000 * 0.75) = 78750 first, then minus the 5000 fee.
    assert booking["refund_cents"] == 78750 - WEATHER_FACILITY_FEE_CENTS


def test_booking_cancel_reopens_full_block(api):
    """PRD §3.9: "Cancellation unwinds everything the booking held:
    `approval_status` becomes `CANCELLED`; the block's `seats_reserved` drops
    by the booking's `driver_count` and the block's status is recomputed, so a
    `FULL` block with freed seats returns to `OPEN`". PRD §3.9: "An `APPROVED`
    booking can be cancelled by `TrackOps`, or by the `Organizer` who owns it
    — the caller's `X-User-ID` must match the booking's `organizer_user_id`."

    Design: Difficulty/transitive_cascade/booking_cancel_to_coach_unassign_to_block_reopen
    """
    track = make_track(name="Barber")
    coach = make_coach(track["id"], cert_level="INTERMEDIATE")
    day = make_open_track_day(track["id"], "2026-08-29")
    block = make_block(track["id"], day["id"], max_group_size=2)
    booking = make_booking(track["id"], day["id"], block["id"], "org8",
                           run_group_class="NOVICE", driver_count=2,
                           coach_id=coach["id"])
    assign_coach(track["id"], day["id"], block["id"], booking["id"], coach["id"])
    approve_booking(track["id"], day["id"], block["id"], booking["id"])
    assert get_block(track["id"], day["id"], block["id"])["status"] == "FULL"
    resp = api.cancel_booking(track["id"], day["id"], block["id"],
                              booking["id"], {"reason": "CUSTOMER"},
                              make_organizer_headers("org8"))
    data = validate_success(resp)
    assert data["approval_status"] == "CANCELLED"
    block_after = get_block(track["id"], day["id"], block["id"])
    assert block_after["seats_reserved"] == 0
    assert block_after["status"] == "OPEN", "freed seats return FULL to OPEN"


def test_booking_cancel_detaches_coach(api):
    """PRD §3.9: "the assigned coach, if any, is detached — the booking's
    `coach_id` is nulled and the coach's `assigned_booking_ids` refreshed".
    PRD §3.1: "A coach's `assigned_booking_ids` is a computed roll of the
    bookings currently attached to that coach — bookings whose `coach_id`
    references the coach and whose `approval_status` stands at `APPROVED`."

    Design: Difficulty/transitive_cascade/booking_cancel_to_coach_unassign_to_block_reopen
    """
    track = make_track(name="Barber")
    coach = make_coach(track["id"], cert_level="INTERMEDIATE")
    day = make_open_track_day(track["id"], "2026-08-29")
    block = make_block(track["id"], day["id"], max_group_size=2)
    booking = make_booking(track["id"], day["id"], block["id"], "org8",
                           run_group_class="NOVICE", driver_count=2,
                           coach_id=coach["id"])
    assign_coach(track["id"], day["id"], block["id"], booking["id"], coach["id"])
    approve_booking(track["id"], day["id"], block["id"], booking["id"])
    validate_success(api.cancel_booking(
        track["id"], day["id"], block["id"], booking["id"],
        {"reason": "CUSTOMER"}, make_organizer_headers("org8")))
    booking_after = get_booking(track["id"], day["id"], block["id"],
                                booking["id"])
    assert booking_after["coach_id"] is None
    coach_after = validate_success(api.get_coach(track["id"], coach["id"], OPS))
    assert booking["id"] not in coach_after["assigned_booking_ids"]


def test_trackday_cancel_releases_assignments_and_cascades_bookings(api):
    """PRD §3.9: "Every door writes `cancelled_reason`, sets the day
    `CANCELLED`, and cascades all bookings on the day to `CANCELLED` with
    refunds computed under the variant the reason forces". PRD §3.9:
    "Cancellation unwinds everything the booking held: `approval_status`
    becomes `CANCELLED`; the block's `seats_reserved` drops by the booking's
    `driver_count` and the block's status is recomputed, so a `FULL` block
    with freed seats returns to `OPEN`; every garage and paddock assignment on
    the booking flips to `RELEASED`". PRD §3.9: "The weather variant, forced
    by `WEATHER`, pays three quarters of the fee — rounded half-up — minus a
    flat 5,000-cent facility fee, floored at zero, independent of notice."

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_trackday_cancel_cascades_all
    """
    env = setup_approved_paid_booking("2026-10-07", "oX3")
    tid, tdid = env["track"]["id"], env["day"]["id"]
    garage = make_garage_assignment(tid, tdid, env["booking"]["id"],
                                    bay_number=1, power_hookups=1)
    validate_success(api.weather_hold(tid, tdid, OPS))
    validate_success(api.cancel_track_day(tid, tdid, {"reason": "WEATHER"}, OPS))
    booking = get_booking(tid, tdid, env["block"]["id"], env["booking"]["id"])
    assert booking["approval_status"] == "CANCELLED"
    assert booking["refund_cents"] == 26250 - WEATHER_FACILITY_FEE_CENTS
    garage_after = validate_success(api.get_garage_assignment(
        tid, tdid, garage["id"], OPS))
    assert garage_after["status"] == "RELEASED"
