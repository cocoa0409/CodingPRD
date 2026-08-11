"""Attachment — the busiest operation: gates, capacity meters, stock and reversal."""

from test_helpers import *  # noqa: F401,F403


def _world_with_stop(**reference_overrides):
    world = setup_reference(**reference_overrides)
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    return world


def test_three_shoes_of_one_sku_draw_two_whole_pairs(api, dispatcher):
    """PRD §3.5: "For each distinct `sku_id` referenced by the appointment's lines
    whose `status` is `PLANNED` or `PERFORMED` and whose `service_type` is
    `NEW_SHOES`, `CORRECTIVE` or `GLUE_ON`, count those lines and divide by 2
    (`SHOES_PER_PAIR`), rounding **up**. Three shoes of one SKU therefore draw two
    pairs, and the odd shoe costs a whole extra pair."
    PRD §3.5: "in either case the bucket's `available_pairs` falls and its
    `reserved_pairs` rises by that reservation's `pairs`, and its
    `replenishment_flag` is recomputed"

    Design: Corner/calculations/corner_three_shoes_of_one_sku_draw_two_whole_pairs
    """
    world = _world_with_stop()
    appointment, _lines = setup_unrouted_visit(
        world,
        limbs=("LF", "RF", "LH"),
        service_type="NEW_SHOES",
        use_sku=True,
        scheduled_date="2026-05-06",
    )

    validate_success(
        api.attach_appointment(
            world["stop"]["id"],
            {
                "appointment_id": appointment["id"],
                "expected_route_version": route_version(world["route"]["id"]),
            },
            dispatcher,
        )
    )

    reservations = reservations_for(appointment["id"])
    assert len(reservations) == 1, "one reservation per distinct SKU"
    assert_shoe_reservation(reservations[0])
    assert reservations[0]["pairs"] == pairs_required(3)
    assert reservations[0]["pairs"] == 2
    assert reservations[0]["status"] == "RESERVED"
    bucket = read_bucket(world["van"]["id"])
    assert bucket["available_pairs"] == 8
    assert bucket["reserved_pairs"] == 2
    assert bucket["on_hand_pairs"] == 10
    assert_bucket_balance(bucket)
    after = read_appointment(appointment["id"])
    # 3 NEW_SHOES limbs: 3 x 3 units, 3 x 20 chair minutes + 6 handling.
    assert after["service_units"] == 9
    assert after["service_minutes"] == 66


def test_apprentice_farrier_cannot_take_a_new_shoes_appointment(api, dispatcher):
    """PRD §3.2: "The certification level is the single gate on what work that
    farrier may perform, and the mapping is exhaustive: an `APPRENTICE` may perform
    only `TRIM`; a `JOURNEYMAN` may perform `TRIM`, `RESET`, `NEW_SHOES` and
    `GLUE_ON`; and a `CERTIFIED_THERAPEUTIC` may perform all five, adding
    `CORRECTIVE`."
    PRD §3.2: "Whenever an appointment carries a service type the route's farrier
    may not perform, the operation is refused with `ERR_CREDENTIAL_INSUFFICIENT`,
    and that refusal is checked at three distinct moments — when the horse is
    attached to a stop, when work on it starts, and when the visit is completed."

    Design: Corner/validations/corner_apprentice_farrier_cannot_take_a_new_shoes_appointment
    """
    world = _world_with_stop(farrier={"certification_level": "APPRENTICE"})
    appointment, _lines = setup_unrouted_visit(
        world,
        limbs=("LF",),
        service_type="NEW_SHOES",
        use_sku=True,
        scheduled_date="2026-05-06",
    )

    response = attach_response(
        world["stop"]["id"], appointment["id"], world["route"]["id"]
    )

    validate_error(response, ApiErrorId.ERR_CREDENTIAL_INSUFFICIENT.value)
    assert response.status_code == 403
    assert read_appointment(appointment["id"])["status"] == "UNROUTED"
    bucket = read_bucket(world["van"]["id"])
    assert bucket["available_pairs"] == 10
    assert bucket["reserved_pairs"] == 0


def test_attaching_a_horse_to_another_barns_stop_is_rejected(api, dispatcher):
    """PRD §3.5: "Beyond the five gates and the stale-version rung it enforces that
    the stop's `barn_id` equals the horse's `barn_id` — several horses at one barn
    share the stop, and a horse kept elsewhere is `ERR_BARN_MISMATCH`"
    PRD §2.7: "(42) The stop's `barn_id` equals the horse's `barn_id`, else
    `ERR_BARN_MISMATCH` (HTTP 422); on attachment."

    Design: Corner/validations/corner_attaching_a_horse_to_another_barns_stop_is_rejected
    """
    world = setup_reference(with_sku=False)
    other_barn = create_barn(name="Fieldstone")
    world["route"] = create_route(world["farrier"]["id"], "2026-05-06")
    world["stop"] = add_stop(world["route"]["id"], other_barn["id"], 1, 480)
    appointment, _lines = setup_unrouted_visit(
        world, limbs=("LF",), service_type="TRIM", scheduled_date="2026-05-06"
    )

    response = attach_response(
        world["stop"]["id"], appointment["id"], world["route"]["id"]
    )

    validate_error(response, ApiErrorId.ERR_BARN_MISMATCH.value)
    assert response.status_code == 422
    assert read_appointment(appointment["id"])["route_stop_id"] is None


def test_van_stock_short_of_the_required_pairs_is_rejected(api, dispatcher):
    """PRD §3.5: "that the farrier's van bucket has at least the required `pairs`
    for every SKU on the appointment (else `ERR_VAN_STOCK_INSUFFICIENT`), and that a
    rate card exists for the appointment's `scheduled_date` (else
    `ERR_NO_EFFECTIVE_RATE_CARD`)."
    PRD §2.7: "(51) The van bucket holds enough pairs, else
    `ERR_VAN_STOCK_INSUFFICIENT` (HTTP 409); on attachment."

    Design: Corner/validations/corner_van_stock_short_of_the_required_pairs_is_rejected
    """
    world = _world_with_stop(van_pairs=1)
    appointment, _lines = setup_unrouted_visit(
        world, service_type="NEW_SHOES", use_sku=True, scheduled_date="2026-05-06"
    )

    response = attach_response(
        world["stop"]["id"], appointment["id"], world["route"]["id"]
    )

    validate_error(response, ApiErrorId.ERR_VAN_STOCK_INSUFFICIENT.value)
    assert response.status_code == 409
    bucket = read_bucket(world["van"]["id"])
    assert bucket["available_pairs"] == 1, "four shoes need two pairs; the van holds one"
    assert bucket["reserved_pairs"] == 0
    assert reservations_for(appointment["id"]) == []


def test_attach_without_any_effective_rate_card_is_rejected(api, dispatcher):
    """PRD §3.5: "that the farrier's van bucket has at least the required `pairs`
    for every SKU on the appointment (else `ERR_VAN_STOCK_INSUFFICIENT`), and that a
    rate card exists for the appointment's `scheduled_date` (else
    `ERR_NO_EFFECTIVE_RATE_CARD`)."
    PRD §3.3: "If the candidate list is empty the operation is refused with
    `ERR_NO_EFFECTIVE_RATE_CARD`."

    Design: Corner/validations/corner_attach_without_any_effective_rate_card_is_rejected
    """
    world = _world_with_stop(with_sku=False, with_rate_card=False)
    appointment, _lines = setup_unrouted_visit(
        world, limbs=("LF",), service_type="TRIM", scheduled_date="2026-05-06"
    )
    cards, _meta = validate_paginated(api.list_rate_cards(dispatcher))
    assert cards == [], "no rate card exists at all"

    response = attach_response(
        world["stop"]["id"], appointment["id"], world["route"]["id"]
    )

    validate_error(response, ApiErrorId.ERR_NO_EFFECTIVE_RATE_CARD.value)
    assert response.status_code == 422
    assert read_appointment(appointment["id"])["status"] == "UNROUTED"


def test_attach_after_dispatch_returns_route_not_open(api, dispatcher):
    """PRD §2.6: "**Gate 2 — the route is still open.** `Route.status` must be
    `DRAFT` or `PLANNED`. A route that is `DISPATCHED`, `CLOSED` or `CANCELLED` no
    longer accepts structural change, and the refusal is `ERR_ROUTE_NOT_OPEN` (HTTP
    409)."
    PRD §3.4: "From the moment a route is `DISPATCHED`, stop insertion, stop
    reordering, attachment and detachment are all refused by gate 2 with
    `ERR_ROUTE_NOT_OPEN`."

    Design: Corner/errors/corner_attach_after_dispatch_returns_route_not_open
    """
    world = _world_with_stop(with_sku=False)
    first, _lines = setup_scheduled_visit(
        world, limbs=("LF",), service_type="TRIM", scheduled_date="2026-05-06"
    )
    second_horse, second_limbs = add_horse(world)
    second = create_appointment(second_horse["id"], "2026-05-06")
    add_lines(second["id"], [service_line(second_limbs["LF"], "TRIM")])
    plan_route(world["route"]["id"])
    dispatch_route(world["route"]["id"])

    response = attach_response(
        world["stop"]["id"], second["id"], world["route"]["id"]
    )

    assert read_route(world["route"]["id"])["status"] == "DISPATCHED"
    validate_error(response, ApiErrorId.ERR_ROUTE_NOT_OPEN.value)
    assert response.status_code == 409
    assert read_appointment(second["id"])["status"] == "UNROUTED"


def test_attach_with_a_stale_route_version_is_refused(api, dispatcher):
    """PRD §2.8: "Attaching an appointment to a stop requires
    `expected_route_version` matching the current `version` of the `Route` that owns
    the stop. A mismatch is `ERR_STALE_ROUTE_VERSION` (HTTP 412)."
    PRD §3.4: "The route's `committed_minutes` rises by the stop's `travel_minutes`,
    its `stop_count` rises by 1, and its `version` increments by 1."

    Design: Corner/cross_cutting_layers/corner_occ_attach_with_a_stale_route_version_returns_412
    """
    world = setup_reference(with_sku=False)
    route = create_route(world["farrier"]["id"], "2026-05-06")
    version_at_creation = route["version"]
    world["route"] = route
    world["stop"] = add_stop(route["id"], world["barn"]["id"], 1, 480)
    appointment, _lines = setup_unrouted_visit(
        world, limbs=("LF",), service_type="TRIM", scheduled_date="2026-05-06"
    )

    response = api.attach_appointment(
        world["stop"]["id"],
        {
            "appointment_id": appointment["id"],
            "expected_route_version": version_at_creation,
        },
        dispatcher,
    )

    validate_error(response, ApiErrorId.ERR_STALE_ROUTE_VERSION.value)
    assert response.status_code == 412
    after = read_appointment(appointment["id"])
    assert after["status"] == "UNROUTED"
    assert after["route_stop_id"] is None
    assert read_route(route["id"])["committed_units"] == 0


# ---------------------------------------------------------------------------
# The two capacity meters
# ---------------------------------------------------------------------------


def _setup_three_glue_on_visits(third_limbs):
    """Three horses at one zone A stop, each carrying GLUE_ON limbs.

    The first two are attached (16 units and 110 minutes each); the third is left
    UNROUTED so that the test can drive the attach itself.
    """
    world = setup_reference()
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    horses = [(world["horse"], world["limbs"])]
    for name in ("Dusty", "Echo"):
        horses.append(add_horse(world, name=name))

    appointments = []
    for (horse, limb_map), limbs in zip(horses, [ALL_LIMBS, ALL_LIMBS, third_limbs]):
        appointment = create_appointment(horse["id"], "2026-05-06")
        add_lines(
            appointment["id"],
            lines_for_limbs(limbs, limb_map, "GLUE_ON", sku_id=world["sku"]["id"]),
        )
        appointments.append(read_appointment(appointment["id"]))

    for appointment in appointments[:2]:
        attach(world["stop"]["id"], appointment["id"], world["route"]["id"])
    return world, appointments


def test_route_units_landing_exactly_on_the_cap_is_accepted(api, dispatcher):
    """PRD §3.4: "A day may carry at most 44 shoeing units
    (`ROUTE_MAX_UNITS_PER_DAY`) and at most 480 minutes
    (`ROUTE_MAX_MINUTES_PER_DAY`)."
    PRD §3.4: "The comparison is strictly greater-than, so landing **exactly** on 44
    units or exactly on 480 minutes is accepted and only exceeding the figure is
    refused."

    Design: Difficulty/boundary_precision_check/route_units_landing_exactly_on_the_cap_is_accepted
    """
    world, appointments = _setup_three_glue_on_visits(("LF", "RF", "LH"))
    before = read_route(world["route"]["id"])
    assert before["committed_units"] == 32, "two four-limb GLUE_ON visits at 16 units"
    # 3 GLUE_ON limbs are 3 x 4 = 12 units, taking the route to exactly 44.
    assert appointments[2]["service_units"] == 12

    response = api.attach_appointment(
        world["stop"]["id"],
        {
            "appointment_id": appointments[2]["id"],
            "expected_route_version": before["version"],
        },
        dispatcher,
    )

    data = validate_success(response)
    assert_appointment(data)
    after = read_route(world["route"]["id"])
    assert after["committed_units"] == ROUTE_MAX_UNITS_PER_DAY
    assert after["committed_units"] == 44
    assert read_appointment(appointments[2]["id"])["status"] == "SCHEDULED"


def test_route_at_the_unit_cap_keeps_its_minute_and_stock_books_straight(
    api, dispatcher
):
    """PRD §3.4: "`committed_minutes` is the sum of `travel_minutes` over the
    route's non-`VOIDED` stops plus the sum of `service_minutes` over those same
    qualifying appointments."
    PRD §3.4: "its `service_minutes` starts at 0, its `end_minute` is its
    `planned_start_minute` plus its `service_minutes`"

    Design: Difficulty/boundary_precision_check/route_units_landing_exactly_on_the_cap_is_accepted
    """
    world, appointments = _setup_three_glue_on_visits(("LF", "RF", "LH"))

    attach(world["stop"]["id"], appointments[2]["id"], world["route"]["id"])

    # 15 travel + 110 + 110 + 84 service minutes.
    assert expected_service_minutes(["GLUE_ON"] * 4, False) == 110
    assert expected_service_minutes(["GLUE_ON"] * 3, False) == 84
    route = read_route(world["route"]["id"])
    assert route["committed_minutes"] == 319
    stop = read_stop(world["stop"]["id"])
    assert stop["service_minutes"] == 304
    assert stop["end_minute"] == 784
    bucket = read_bucket(world["van"]["id"])
    # Each visit draws ceil(limbs / 2) pairs: 2 + 2 + 2.
    assert bucket["reserved_pairs"] == 6
    assert bucket["available_pairs"] == 4
    assert_bucket_balance(bucket)


def test_route_unit_capacity_exceeded_on_the_third_attach(api, dispatcher):
    """PRD §3.4: "A day may carry at most 44 shoeing units
    (`ROUTE_MAX_UNITS_PER_DAY`) and at most 480 minutes
    (`ROUTE_MAX_MINUTES_PER_DAY`)."
    PRD §3.4: "Units are checked first, with `ERR_ROUTE_UNIT_CAPACITY_EXCEEDED`;
    minutes second, with `ERR_ROUTE_MINUTE_CAPACITY_EXCEEDED`."

    Design: Corner/errors/corner_route_unit_capacity_exceeded_on_the_third_attach
    """
    world, appointments = _setup_three_glue_on_visits(ALL_LIMBS)

    response = attach_response(
        world["stop"]["id"], appointments[2]["id"], world["route"]["id"]
    )

    validate_error(response, ApiErrorId.ERR_ROUTE_UNIT_CAPACITY_EXCEEDED.value)
    assert response.status_code == 409
    route = read_route(world["route"]["id"])
    # 32 + 16 = 48 would exceed the 44 cap while 235 + 110 stays under 480 minutes.
    assert route["committed_units"] == 32
    assert route["committed_minutes"] == 235
    assert read_appointment(appointments[2]["id"])["status"] == "UNROUTED"
    assert read_bucket(world["van"]["id"])["reserved_pairs"] == 4


def test_route_minute_capacity_exceeded_while_units_are_far_below_the_cap(
    api, dispatcher
):
    """PRD §3.4: "The comparison is strictly greater-than, so landing **exactly** on
    44 units or exactly on 480 minutes is accepted and only exceeding the figure is
    refused. Units are checked first, with `ERR_ROUTE_UNIT_CAPACITY_EXCEEDED`;
    minutes second, with `ERR_ROUTE_MINUTE_CAPACITY_EXCEEDED`."
    PRD §3.4: "The stop is minted `PENDING`, its `travel_minutes` is fixed from the
    barn's zone — 15 minutes for zone `A` (`STOP_TRAVEL_MINUTES_ZONE_A`), 30 for
    zone `B` (`STOP_TRAVEL_MINUTES_ZONE_B`) and 50 for zone `C`
    (`STOP_TRAVEL_MINUTES_ZONE_C`)"

    Design: Corner/errors/corner_route_minute_capacity_exceeded_while_units_are_far_below_the_cap
    """
    world = setup_reference(
        barn={"name": "Far Ridge", "zone": "C"},
        horse={"name": "Nervy", "requires_sedation": True},
    )
    world["route"] = create_route(world["farrier"]["id"], "2026-05-06")
    stops = [
        add_stop(world["route"]["id"], world["barn"]["id"], index, 420 + 50 * (index - 1))
        for index in range(1, MAX_STOPS_PER_ROUTE + 1)
    ]
    world["stop"] = stops[-1]
    appointment, _lines = setup_unrouted_visit(
        world,
        service_type="GLUE_ON",
        use_sku=True,
        scheduled_date="2026-05-06",
        appointment_overrides={"vet_present": True},
    )
    before = read_route(world["route"]["id"])
    assert before["stop_count"] == 8
    # Eight zone C stops at 50 travel minutes each.
    assert before["committed_minutes"] == 400
    assert before["committed_units"] == 0
    # 4 x 26 chair minutes + 9 sedated handling + 15 sedation = 128; 16 units.
    assert appointment["service_minutes"] == expected_service_minutes(
        ["GLUE_ON"] * 4, True
    )
    assert appointment["service_minutes"] == 128
    assert appointment["service_units"] == 16

    response = attach_response(
        world["stop"]["id"], appointment["id"], world["route"]["id"]
    )

    validate_error(response, ApiErrorId.ERR_ROUTE_MINUTE_CAPACITY_EXCEEDED.value)
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Attach then detach conserves both the van bucket and the route meters
# ---------------------------------------------------------------------------


def _setup_attached_new_shoes_visit():
    world = setup_reference()
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    setup_scheduled_visit(
        world, service_type="NEW_SHOES", use_sku=True, scheduled_date="2026-05-06"
    )
    return world


def test_detach_returns_every_reserved_pair_to_the_van_bucket(api, dispatcher):
    """PRD §3.5: "Detaching reverses all of it exactly. The appointment's
    `route_stop_id` is cleared and its `status` returns to `UNROUTED` from either
    `SCHEDULED` or `CONFIRMED`; every `RESERVED` reservation of the appointment
    moves to `RELEASED`, raising the bucket's `available_pairs` and lowering its
    `reserved_pairs` by the reservation's `pairs` with `on_hand_pairs` untouched,
    and recomputing the bucket's `replenishment_flag`"
    PRD §2.9: "**Reserve/release round trip.** Attaching an appointment and then
    detaching the same appointment leaves the van bucket's `available_pairs` and
    `reserved_pairs` at exactly their pre-attachment values."

    Design: Difficulty/compensating_invariant/attach_then_detach_conserves_van_pairs_and_route_capacity
    """
    world = _setup_attached_new_shoes_visit()
    before = read_bucket(world["van"]["id"])
    assert before["available_pairs"] == 8
    assert before["reserved_pairs"] == 2
    assert before["on_hand_pairs"] == 10

    validate_success(
        api.detach_appointment(
            world["stop"]["id"], world["appointment"]["id"], dispatcher
        )
    )

    after = read_bucket(world["van"]["id"])
    assert after["available_pairs"] == 10
    assert after["reserved_pairs"] == 0
    assert after["on_hand_pairs"] == 10, "on_hand_pairs is untouched by a release"
    assert_bucket_balance(after)
    reservations = reservations_for(world["appointment"]["id"])
    assert len(reservations) == 1
    assert reservations[0]["status"] == "RELEASED"


def test_detach_gives_back_exactly_the_capacity_the_attach_took(api, dispatcher):
    """PRD §2.9: "**Route capacity round trip.** Attaching an appointment and then
    detaching the same appointment leaves the route's `committed_units` and
    `committed_minutes` at exactly their pre-attachment values."
    PRD §3.5: "the route's `committed_units` and `committed_minutes` fall by exactly
    the amounts the attachment added; the route's `version` increments by 1; and the
    appointment's `version` increments by 1."

    Design: Difficulty/compensating_invariant/attach_then_detach_conserves_van_pairs_and_route_capacity
    """
    world = _setup_attached_new_shoes_visit()
    before = read_route(world["route"]["id"])
    assert before["committed_units"] == 12, "four NEW_SHOES limbs at 3 units each"
    assert before["committed_minutes"] == 101, "15 travel plus 86 service minutes"

    data = validate_success(
        api.detach_appointment(
            world["stop"]["id"], world["appointment"]["id"], dispatcher
        )
    )

    assert_appointment(data)
    assert data["status"] == "UNROUTED"
    assert data["route_stop_id"] is None
    after = read_route(world["route"]["id"])
    assert after["committed_units"] == 0
    assert after["committed_minutes"] == STOP_TRAVEL_MINUTES_ZONE_A
    stop = read_stop(world["stop"]["id"])
    assert stop["service_minutes"] == 0
    assert stop["end_minute"] == 480


# ---------------------------------------------------------------------------
# Gate 1 outranks gate 2
# ---------------------------------------------------------------------------


def _setup_decertified_farrier_world():
    world = setup_reference(with_sku=False)
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    setup_unrouted_visit(world, service_type="TRIM", scheduled_date="2026-05-06")
    plan_route(world["route"]["id"])
    get_success_data(
        api_client.deactivate_farrier(
            world["farrier"]["id"], {"reason": "CERT_EXPIRED"}, admin_headers()
        )
    )
    return world


def test_standing_a_farrier_down_for_cert_expiry_cancels_their_open_routes(api):
    """PRD §3.2: "A `reason` of `VOLUNTARY` moves `ACTIVE` to `INACTIVE`; a `reason`
    of `CERT_EXPIRED` moves `ACTIVE` to `DECERTIFIED`."
    PRD §3.2: "Both exits do the same collateral damage — every route of that
    farrier whose `status` is `DRAFT` or `PLANNED` moves to `CANCELLED`, which in
    turn voids that route's `PENDING` stops, detaches its appointments back to
    `UNROUTED` and releases their reservations — and both increment the farrier's
    `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/attach_refused_because_the_routes_farrier_is_decertified
    """
    world = _setup_decertified_farrier_world()

    assert read_farrier(world["farrier"]["id"])["status"] == "DECERTIFIED"
    assert read_route(world["route"]["id"])["status"] == "CANCELLED"
    assert read_stop(world["stop"]["id"])["status"] == "VOIDED"


def test_attach_on_a_decertified_farriers_cancelled_route_reports_the_farrier_code(
    api, dispatcher
):
    """PRD §2.6: "The gate is really two rungs in sequence: an `INACTIVE` or
    `DECERTIFIED` farrier yields `ERR_FARRIER_INACTIVE` (HTTP 409), and only if the
    status is `ACTIVE` does the server look at the certificate, a lapsed one
    yielding `ERR_FARRIER_CERT_EXPIRED` (HTTP 409)."
    PRD §2.6: "It deliberately sits **after** gate 1, so that a dispatched route
    belonging to a lapsed farrier reports the farrier codes rather than this one."

    Design: Difficulty/cross_entity_state_dependency/attach_refused_because_the_routes_farrier_is_decertified
    """
    world = _setup_decertified_farrier_world()

    response = attach_response(
        world["stop"]["id"], world["appointment"]["id"], world["route"]["id"]
    )

    validate_error(response, ApiErrorId.ERR_FARRIER_INACTIVE.value)
    assert response.status_code == 409
    assert read_appointment(world["appointment"]["id"])["status"] == "UNROUTED"
