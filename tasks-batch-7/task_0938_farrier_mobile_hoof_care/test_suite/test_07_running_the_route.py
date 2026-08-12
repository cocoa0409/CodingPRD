"""Running the route: arrival order, performed work, cancellations and no-shows."""

from test_helpers import *  # noqa: F401,F403


def test_arriving_out_of_sequence_is_rejected(api):
    """PRD §3.7: "Arriving moves a stop from `PENDING` to `ARRIVED`, and it requires
    the route to be `DISPATCHED` and every stop on the same route with a lower
    `sequence_index` to be already `COMPLETED` or `VOIDED`; an out-of-order arrival
    is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_arriving_out_of_sequence_is_rejected
    """
    world = setup_reference(with_sku=False)
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    second_stop = add_stop(world["route"]["id"], world["barn"]["id"], 2, 700)
    setup_scheduled_visit(
        world, limbs=("LF",), service_type="TRIM", scheduled_date="2026-05-06"
    )
    plan_route(world["route"]["id"])
    dispatch_route(world["route"]["id"])

    response = api.arrive_route_stop(
        second_stop["id"], make_farrier_headers(world["farrier"]["id"])
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert response.status_code == 409
    assert read_stop(second_stop["id"])["status"] == "PENDING"
    assert read_stop(world["stop"]["id"])["status"] == "PENDING"


def test_a_performed_glue_on_line_moves_only_its_own_limb_to_glued(api):
    """PRD §3.7: "`GLUE_ON` leaves the limb `GLUED` and writes its SKU code into
    `current_sku_code`."
    PRD §3.7: "Every performed line, of every type, also sets its limb's
    `last_serviced_on` to the logical clock date."
    PRD §3.5: "`RESERVED` becomes `COMMITTED` when the visit completes —
    `on_hand_pairs` and `reserved_pairs` both fall by `pairs` while
    `available_pairs` is untouched — and `COMMITTED` is final."

    Design: Corner/state_machines/corner_limb_state_moves_barefoot_to_glued_when_a_glue_on_line_is_performed
    """
    world = setup_reference(clock="2026-05-06T08:00:00Z", van_pairs=6)
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    setup_completed_visit(
        world,
        limbs=("LF",),
        service_type="GLUE_ON",
        use_sku=True,
        scheduled_date="2026-05-06",
    )

    limbs = limb_state_rows(world["horse"]["id"])
    assert limbs["LF"]["shoeing_state"] == "GLUED"
    assert limbs["LF"]["current_sku_code"] == "ST-1"
    assert_same_date(limbs["LF"]["last_serviced_on"], "2026-05-06")
    for token in ("RF", "LH", "RH"):
        assert limbs[token]["shoeing_state"] == "BAREFOOT"
        assert limbs[token]["current_sku_code"] is None

    reservations = reservations_for(world["appointment"]["id"])
    assert len(reservations) == 1
    assert reservations[0]["status"] == "COMMITTED"
    assert reservations[0]["pairs"] == 1
    bucket = read_bucket(world["van"]["id"])
    assert bucket["on_hand_pairs"] == 5
    assert bucket["available_pairs"] == 5
    assert bucket["reserved_pairs"] == 0
    assert_bucket_balance(bucket)


def test_second_consecutive_reset_on_one_limb_is_rejected(api, dispatcher):
    """PRD §3.5: "That limb's `consecutive_reset_count` must be strictly below 1
    (`MAX_CONSECUTIVE_RESETS`) — a limb may be reset once before the shoe must be
    replaced, and a second consecutive reset is `ERR_RESET_LIMIT_REACHED`."
    PRD §3.7: "A performed `RESET` increases the limb's `consecutive_reset_count` by
    1; a performed `TRIM`, `NEW_SHOES`, `CORRECTIVE` or `GLUE_ON` resets it to 0."

    Design: Corner/validations/corner_second_consecutive_reset_on_one_limb_is_rejected
    """
    world = setup_reference()
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    setup_completed_visit(
        world,
        limbs=("LF",),
        service_type="NEW_SHOES",
        use_sku=True,
        scheduled_date="2026-05-06",
    )

    second_route = create_route(world["farrier"]["id"], "2026-05-13")
    second_stop = add_stop(second_route["id"], world["barn"]["id"], 1, 480)
    world["route"], world["stop"] = second_route, second_stop
    setup_completed_visit(
        world, limbs=("LF",), service_type="RESET", scheduled_date="2026-05-13"
    )

    limb = limb_state_rows(world["horse"]["id"])["LF"]
    assert limb["shoeing_state"] == "SHOD"
    assert limb["consecutive_reset_count"] == MAX_CONSECUTIVE_RESETS

    third = create_appointment(world["horse"]["id"], "2026-05-20")
    response = api.add_service_lines(
        third["id"],
        service_lines_payload(
            [service_line(world["limbs"]["LF"], "RESET")], third["version"]
        ),
        dispatcher,
    )

    validate_error(response, ApiErrorId.ERR_RESET_LIMIT_REACHED.value)
    assert response.status_code == 409
    assert service_lines_for(third["id"]) == []


def test_warranty_revisit_after_the_window_is_rejected(api):
    """PRD §3.7: "The origin visit must have `status` `COMPLETED`, and the whole-day
    difference between the logical clock date and the origin's `completed_on` must
    be at least 0 and at most 21 days (`WARRANTY_WINDOW_DAYS`); the boundary is
    inclusive, so exactly twenty-one days later is still eligible and one day more
    is `ERR_WARRANTY_WINDOW_EXPIRED`."

    Design: Corner/errors/corner_warranty_revisit_after_the_window_is_rejected
    """
    world = setup_reference(clock="2026-05-06T08:00:00Z", with_sku=False)
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    setup_completed_visit(
        world, limbs=("LF",), service_type="TRIM", scheduled_date="2026-05-06"
    )
    origin = read_appointment(world["appointment"]["id"])
    assert origin["status"] == "COMPLETED"
    assert_same_date(origin["completed_on"], "2026-05-06")
    # 2026-05-06 plus 22 elapsed days is 2026-05-28, one past the inclusive window.
    assert plus_days("2026-05-06", WARRANTY_WINDOW_DAYS + 1) == "2026-05-28"
    set_clock("2026-05-28T08:00:00Z")

    response = api.create_warranty_revisit(
        origin["id"],
        {"warranty_reason": "SPRUNG_SHOE", "scheduled_date": "2026-05-29"},
        make_client_headers(world["client"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_WARRANTY_WINDOW_EXPIRED.value)
    assert response.status_code == 422
    rows, _meta = validate_paginated(
        api.list_appointments(
            dispatcher_headers(), params={"origin_appointment_id": origin["id"]}
        )
    )
    assert rows == [], "no revisit was opened"


def test_cancelling_a_cancelled_appointment_is_not_eligible(api):
    """PRD §2.6: "**Gate 5 — the appointment is in an eligible status.**
    `Appointment.status` must be inside the eligible set the endpoint declares, and
    the refusal is `ERR_APPOINTMENT_NOT_ELIGIBLE` (HTTP 409)."
    PRD §2.6: "cancellation accepts `UNROUTED`, `SCHEDULED` and `CONFIRMED`"
    PRD §3.7: "**`ADVANCE`** sets `cancellation_fee_cents` to 0, moves the
    appointment to `CANCELLED_ADVANCE`, detaches it from its stop and releases every
    `RESERVED` reservation with the route's committed totals falling accordingly,
    moves every `PENDING` and `SENT` reminder of the appointment to `FAILED`, mints
    **no** invoice at all, and increments the appointment's `version` by 1."

    Design: Corner/errors/corner_cancelling_a_cancelled_appointment_is_not_eligible
    """
    set_clock("2026-05-04T08:00:00Z")
    barn = create_barn()
    client = create_client(barn["id"])
    horse = create_horse(client["id"], barn["id"])
    # Rung 53 names "appointment cancellation" without qualifying the tier, so
    # the first cancellation needs a card effective for the service date before
    # gate 5 can be the thing the second one trips on.
    create_active_rate_card()
    appointment = create_appointment(horse["id"], "2026-05-13")
    # A lead of nine whole days is comfortably inside the ADVANCE tier.
    assert lead_days("2026-05-13", "2026-05-04") == 9
    cancel_visit(appointment["id"], client["id"])

    response = api.cancel_appointment(
        appointment["id"], make_client_headers(client["id"])
    )

    validate_error(response, ApiErrorId.ERR_APPOINTMENT_NOT_ELIGIBLE.value)
    assert response.status_code == 409
    after = read_appointment(appointment["id"])
    assert after["status"] == "CANCELLED_ADVANCE"
    assert after["cancellation_fee_cents"] == 0


# ---------------------------------------------------------------------------
# Cancellation exactly on the ADVANCE boundary
# ---------------------------------------------------------------------------


def _setup_visit_scheduled_three_days_out():
    """A NEW_SHOES visit on 2026-05-13 attached to a PLANNED route, clock 2026-05-10."""
    world = setup_reference()
    setup_route_with_stop(world, route_date="2026-05-13", planned_start_minute=480)
    setup_scheduled_visit(
        world, service_type="NEW_SHOES", use_sku=True, scheduled_date="2026-05-13"
    )
    plan_route(world["route"]["id"])
    set_clock("2026-05-10T08:00:00Z")
    return world


def test_cancel_with_exactly_three_days_lead_lands_in_the_advance_tier(api):
    """PRD §3.7: "Let the lead be the whole-calendar-day difference between the
    appointment's `scheduled_date` and the logical clock date. A lead of at least 3
    days (`ADVANCE_CANCEL_MIN_LEAD_DAYS`) is the `ADVANCE` tier — exactly three days
    of notice still counts as advance notice, and two days does not."
    PRD §3.7: "**`ADVANCE`** sets `cancellation_fee_cents` to 0, moves the
    appointment to `CANCELLED_ADVANCE`, detaches it from its stop and releases every
    `RESERVED` reservation with the route's committed totals falling accordingly,
    moves every `PENDING` and `SENT` reminder of the appointment to `FAILED`, mints
    **no** invoice at all, and increments the appointment's `version` by 1."

    Design: Difficulty/boundary_precision_check/cancel_with_exactly_three_days_lead_lands_in_the_advance_tier
    """
    world = _setup_visit_scheduled_three_days_out()
    assert lead_days("2026-05-13", "2026-05-10") == ADVANCE_CANCEL_MIN_LEAD_DAYS

    data = validate_success(
        api.cancel_appointment(
            world["appointment"]["id"], make_client_headers(world["client"]["id"])
        )
    )

    assert_appointment(data)
    assert data["status"] == "CANCELLED_ADVANCE"
    assert data["cancellation_fee_cents"] == 0
    assert data["billing_status"] == "UNBILLED"
    assert invoices_for(world["appointment"]["id"]) == [], "the ADVANCE tier mints no invoice"


def test_advance_cancellation_detaches_and_gives_back_every_reserved_pair(api):
    """PRD §3.7: "**`ADVANCE`** sets `cancellation_fee_cents` to 0, moves the
    appointment to `CANCELLED_ADVANCE`, detaches it from its stop and releases every
    `RESERVED` reservation with the route's committed totals falling accordingly,
    moves every `PENDING` and `SENT` reminder of the appointment to `FAILED`, mints
    **no** invoice at all, and increments the appointment's `version` by 1."
    PRD §3.5: "`RESERVED` becomes `RELEASED` on detachment, on cancellation, on a
    no-show, on route cancellation and on the lameness chain's fourth hop."

    Design: Difficulty/boundary_precision_check/cancel_with_exactly_three_days_lead_lands_in_the_advance_tier
    """
    world = _setup_visit_scheduled_three_days_out()

    cancel_visit(world["appointment"]["id"], world["client"]["id"])

    after = read_appointment(world["appointment"]["id"])
    assert after["route_stop_id"] is None
    bucket = read_bucket(world["van"]["id"])
    assert bucket["available_pairs"] == 10
    assert bucket["reserved_pairs"] == 0
    assert_bucket_balance(bucket)
    assert read_route(world["route"]["id"])["committed_units"] == 0
    reservations = reservations_for(world["appointment"]["id"])
    assert len(reservations) == 1
    assert reservations[0]["status"] == "RELEASED"


# ---------------------------------------------------------------------------
# Three no-shows tip the client into prepayment
# ---------------------------------------------------------------------------


def _record_three_no_shows(world):
    """One TRIM visit per horse at one ARRIVED stop, all three marked absent."""
    horses = [(world["horse"], world["limbs"])]
    for name in ("Dusty", "Echo"):
        horses.append(add_horse(world, name=name))

    setup_route_with_stop(world, route_date="2026-05-04", planned_start_minute=480)
    appointments = []
    for horse, limb_map in horses:
        appointment = create_appointment(horse["id"], "2026-05-04")
        add_lines(appointment["id"], [service_line(limb_map["LF"], "TRIM")])
        attach(world["stop"]["id"], appointment["id"], world["route"]["id"])
        appointments.append(appointment)

    dispatch_and_arrive(world)
    for appointment in appointments:
        record_no_show(appointment["id"], world["farrier"]["id"])
    world["no_show_appointments"] = appointments
    return world


def test_prepay_required_client_cannot_book_a_new_appointment(api, dispatcher):
    """PRD §3.9: "A count of 3 or more (`NO_SHOW_PREPAY_THRESHOLD`) but fewer than
    5, together with a `deposit_balance_cents` below 10000
    (`PREPAY_DEPOSIT_MIN_CENTS`), gives `PREPAY_REQUIRED` — so the **third** strike
    inside the window is what tips a client into prepayment."
    PRD §2.6: "**Gate 3 — the client may be booked.** The `Client` that owns the
    horse in scope must have `billing_standing` `ACTIVE`, or `PREPAY_REQUIRED`
    together with a `deposit_balance_cents` of at least 10000
    (`PREPAY_DEPOSIT_MIN_CENTS`). A `SUSPENDED` client never passes, whatever
    deposit is held. The refusal is `ERR_CLIENT_PREPAY_REQUIRED` (HTTP 402)."
    PRD §3.7: "It sets `cancellation_fee_cents` to 6500 (`NO_SHOW_FEE_CENTS`), moves
    the appointment to `NO_SHOW`, **keeps it attached** so that it too bears a
    trip-fee share, releases every `RESERVED` reservation, mints a `DRAFT` invoice
    carrying the no-show-fee line and moves `billing_status` to `INVOICED`, sets the
    appointment's `completed_on` to the logical clock date, recomputes the client's
    rolling no-show count and re-derives that client's `billing_standing`, and
    increments both the appointment's `version` and the client's `version` by 1."

    Design: Corner/errors/corner_prepay_required_client_cannot_book_a_new_appointment
    """
    world = _record_three_no_shows(setup_reference(with_sku=False))

    client = read_client(world["client"]["id"])
    assert client["no_show_count_rolling"] == NO_SHOW_PREPAY_THRESHOLD
    assert client["billing_standing"] == "PREPAY_REQUIRED"
    for appointment in world["no_show_appointments"]:
        row = read_appointment(appointment["id"])
        assert row["status"] == "NO_SHOW"
        assert row["cancellation_fee_cents"] == NO_SHOW_FEE_CENTS
        assert row["billing_status"] == "INVOICED"

    response = api.create_appointment(
        {"horse_id": world["horse"]["id"], "scheduled_date": "2026-05-13"}, dispatcher
    )

    validate_error(response, ApiErrorId.ERR_CLIENT_PREPAY_REQUIRED.value)
    assert response.status_code == 402


def test_deposit_at_the_minimum_clears_the_prepay_gate(api, dispatcher, billing):
    """PRD §3.9: "A deposit carries an `amount_cents` that must be strictly
    positive; it raises the client's `deposit_balance_cents` by that amount,
    re-derives the client's `billing_standing`, and increments the client's
    `version` by 1."
    PRD §3.9: "`PREPAY_REQUIRED` becomes `ACTIVE` when a deposit lifts
    `deposit_balance_cents` to at least 10000 while the rolling count is still below
    5, and it also becomes `ACTIVE` when a clock advance ages strikes out of the
    window until the rolling count falls below 3."

    Design: Corner/errors/corner_deposit_at_the_minimum_clears_the_prepay_gate
    """
    world = _record_three_no_shows(setup_reference(with_sku=False))
    assert read_client(world["client"]["id"])["billing_standing"] == "PREPAY_REQUIRED"

    data = validate_success(
        api.post_deposit(
            world["client"]["id"],
            {"amount_cents": PREPAY_DEPOSIT_MIN_CENTS},
            billing,
        )
    )

    assert_client(data)
    assert data["deposit_balance_cents"] == 10000
    assert data["billing_standing"] == "ACTIVE"
    assert data["no_show_count_rolling"] == 3, "the strikes are still on file"

    booked = validate_success(
        api.create_appointment(
            {"horse_id": world["horse"]["id"], "scheduled_date": "2026-05-13"},
            dispatcher,
        ),
        201,
    )
    assert booked["status"] == "UNROUTED"


# ---------------------------------------------------------------------------
# Gate 1b outranks gate 3
# ---------------------------------------------------------------------------


def _setup_lapsed_farrier_and_prepay_client():
    """A second farrier whose certificate lapses on 2026-05-05 owns a route holding
    an appointment prepared while the client was still `ACTIVE`; three no-shows then
    push the client into `PREPAY_REQUIRED` and the clock moves to 2026-05-06."""
    world = setup_reference(with_sku=False)
    lapsing = create_farrier(display_name="Rina Sato", cert_expires_on="2026-05-05")
    later_route = create_route(lapsing["id"], "2026-05-13")
    later_stop = add_stop(later_route["id"], world["barn"]["id"], 1, 480)
    prepared = create_appointment(world["horse"]["id"], "2026-05-13")
    add_lines(prepared["id"], [service_line(world["limbs"]["RF"], "TRIM")])

    _record_three_no_shows(world)
    set_clock("2026-05-06T08:00:00Z")

    world["lapsing_farrier"] = lapsing
    world["later_route"] = later_route
    world["later_stop"] = later_stop
    world["prepared"] = prepared
    return world


def test_lapsed_certificate_pre_empts_the_client_prepay_refusal(api, dispatcher):
    """PRD §2.6: "**Gate 1 — the farrier may work at all.** The `Farrier` that owns
    the `Route` in scope must have `status` `ACTIVE`, and that farrier's
    `cert_expires_on` must be on or after the logical clock date."
    PRD §2.6: "The gate is really two rungs in sequence: an `INACTIVE` or
    `DECERTIFIED` farrier yields `ERR_FARRIER_INACTIVE` (HTTP 409), and only if the
    status is `ACTIVE` does the server look at the certificate, a lapsed one
    yielding `ERR_FARRIER_CERT_EXPIRED` (HTTP 409)."
    PRD §2.7: "When more than one rung would fire for a single request, the
    **lowest-numbered rung wins** and its code is returned; later rungs are not
    evaluated and their side conditions are irrelevant."

    Design: Difficulty/priority_pair_validation_conflict/farrier_cert_expired_state_preempts_client_prepay_required_fiscal
    """
    world = _setup_lapsed_farrier_and_prepay_client()
    client = read_client(world["client"]["id"])
    assert client["no_show_count_rolling"] == 3
    assert client["billing_standing"] == "PREPAY_REQUIRED"
    assert client["deposit_balance_cents"] == 0

    response = attach_response(
        world["later_stop"]["id"],
        world["prepared"]["id"],
        world["later_route"]["id"],
    )

    validate_error(response, ApiErrorId.ERR_FARRIER_CERT_EXPIRED.value)
    assert response.status_code == 409


def test_the_pre_empted_prepay_attach_leaves_the_appointment_unrouted(api, dispatcher):
    """PRD §2.7: "**Rungs 28–33, the five gates.** (28) Gate 1a —
    `ERR_FARRIER_INACTIVE`. (29) Gate 1b — `ERR_FARRIER_CERT_EXPIRED`. (30) Gate 2 —
    `ERR_ROUTE_NOT_OPEN`. (31) Gate 3 — `ERR_CLIENT_PREPAY_REQUIRED`. (32) Gate 4 —
    `ERR_HORSE_ON_HOLD`. (33) Gate 5 — `ERR_APPOINTMENT_NOT_ELIGIBLE`."
    PRD §3.5: "Attaching a horse to a stop is the busiest operation in the system.
    It supplies `appointment_id` and `expected_route_version`, and it moves the
    appointment from `UNROUTED` to `SCHEDULED`."

    Design: Difficulty/priority_pair_validation_conflict/farrier_cert_expired_state_preempts_client_prepay_required_fiscal
    """
    world = _setup_lapsed_farrier_and_prepay_client()

    response = attach_response(
        world["later_stop"]["id"],
        world["prepared"]["id"],
        world["later_route"]["id"],
    )
    assert response.status_code != 402, "the fiscal gate never speaks"
    validate_error(response, ApiErrorId.ERR_FARRIER_CERT_EXPIRED.value)

    after = read_appointment(world["prepared"]["id"])
    assert after["status"] == "UNROUTED"
    assert after["route_stop_id"] is None
