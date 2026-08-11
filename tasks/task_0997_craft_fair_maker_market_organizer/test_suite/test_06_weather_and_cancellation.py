"""Weather-hold and cancellation cascades across zones, assignments, tickets,
and load slots."""
from test_helpers import (
    validate_success, get_success_data,
    ApiErrorId, TEST_USERS,
    charge_by_kind, list_charges,
    reserve_slot, sell_ticket, post_sale,
    setup_two_zone_live_ctx, setup_live_ctx,
    api_client,
)


def test_severe_weather_forfeits_only_open_air_assignments(api):
    """PRD §3.6: "The coordinator sets the event's `weather_flag`, and setting it to
    `SEVERE` while the event is `LIVE` slams the event into `WEATHER_HOLD` with a
    four-part cascade: ticket redemption is suspended; every BoothAssignment in an
    `OPEN_AIR` zone whose status is `ACTIVE` is moved to `FORFEITED`; each forfeited
    assignment releases its booth, clearing `assigned_application_id`; and each
    forfeiture mints a `REFUND` BoothFeeCharge per the weather refund policy."

    Design: Difficulty/transitive_cascade/weather_hold_open_air_cascade_depth2
    """
    ctx = setup_two_zone_live_ctx()
    event_id = ctx["event"]["id"]

    event = validate_success(
        api_client.set_weather(event_id, "SEVERE", ctx["coordinator_headers"]), 200
    )
    assert event["posture"] == "WEATHER_HOLD", (
        f"SEVERE while LIVE must move posture to WEATHER_HOLD, got {event['posture']}"
    )

    open_after = get_success_data(api_client.get_assignment(
        event_id, ctx["open"]["assignment"]["id"], ctx["coordinator_headers"]))
    in_after = get_success_data(api_client.get_assignment(
        event_id, ctx["in"]["assignment"]["id"], ctx["coordinator_headers"]))
    assert open_after["status"] == "FORFEITED", (
        f"OPEN_AIR ACTIVE assignment must be forfeited, got {open_after['status']}"
    )
    assert in_after["status"] == "ACTIVE", (
        f"INDOOR assignment must be untouched by the cascade, got {in_after['status']}"
    )


def test_severe_weather_releases_booth_and_mints_refund(api):
    """PRD §3.6: "The coordinator sets the event's `weather_flag`, and setting it to
    `SEVERE` while the event is `LIVE` slams the event into `WEATHER_HOLD` with a
    four-part cascade: ticket redemption is suspended; every BoothAssignment in an
    `OPEN_AIR` zone whose status is `ACTIVE` is moved to `FORFEITED`; each forfeited
    assignment releases its booth, clearing `assigned_application_id`; and each
    forfeiture mints a `REFUND` BoothFeeCharge per the weather refund policy."

    Design: Difficulty/transitive_cascade/weather_hold_open_air_cascade_depth2
    """
    ctx = setup_two_zone_live_ctx()
    event_id = ctx["event"]["id"]
    validate_success(
        api_client.set_weather(event_id, "SEVERE", ctx["coordinator_headers"]), 200
    )

    booth = get_success_data(
        api_client.get_booth(ctx["open"]["booth"]["id"], ctx["coordinator_headers"])
    )
    assert booth.get("assigned_application_id") is None, (
        "the forfeited OPEN_AIR assignment must release its booth"
    )
    charges = list_charges(event_id, ctx["open"]["assignment"]["id"])
    refunds = charge_by_kind(charges, "REFUND")
    assert len(refunds) == 1, (
        f"each weather forfeiture mints a REFUND BoothFeeCharge, got {charges}"
    )
    # The INDOOR branch mints no refund and keeps its booth.
    in_charges = list_charges(event_id, ctx["in"]["assignment"]["id"])
    assert charge_by_kind(in_charges, "REFUND") == []
    in_booth = get_success_data(
        api_client.get_booth(ctx["in"]["booth"]["id"], ctx["coordinator_headers"])
    )
    assert in_booth.get("assigned_application_id") == ctx["in"]["app"]["id"]


def _setup_weather_hold_ctx(api):
    """LIVE event with one ACTIVE COVERED-zone assignment (survives SEVERE), one
    load slot, and one ticket; then SEVERE -> WEATHER_HOLD."""
    ctx = setup_live_ctx(zone_overrides={"weather_exposure": "COVERED"})
    event_id = ctx["event"]["id"]
    slot = validate_success(reserve_slot(
        event_id, ctx["assignment"]["id"], ctx["vendor"]["id"],
        kind="LOAD_IN", starts_at="2026-06-01T07:00:00Z",
        ends_at="2026-06-01T09:00:00Z", bay="NORTH",
    ), 201)
    ctx["slot"] = slot
    ctx["ticket"] = sell_ticket(event_id, kind="GA", price_cents=1500)
    validate_success(
        api_client.set_weather(event_id, "SEVERE", ctx["coordinator_headers"]), 200
    )
    return ctx


def test_cancel_from_weather_hold_cascades(api):
    """PRD §3.6: "Cancelling from `WEATHER_HOLD` moves the event to `CANCELLED` and
    resolves everything outstanding: every ticket in `ISSUED` or `REDEEMED` is
    refunded at full face value to `REFUNDED`; every assignment in `PENDING_PAYMENT`
    or `ACTIVE` becomes `FORFEITED`; every settlement in `PENDING` or `COMPUTED`
    becomes `CANCELLED`; and every LoadInSlot is deleted outright."

    Design: Difficulty/transitive_cascade/event_cancel_cascade_depth3
    """
    ctx = _setup_weather_hold_ctx(api)
    event_id = ctx["event"]["id"]

    event = validate_success(
        api_client.cancel_event(event_id, ctx["coordinator_headers"],
                                payload={"reason": "weather"}),
        200,
    )
    assert event["posture"] == "CANCELLED"

    ticket = get_success_data(api_client.get_ticket(
        event_id, ctx["ticket"]["id"], ctx["coordinator_headers"]))
    assert ticket["state"] == "REFUNDED", (
        f"ISSUED ticket must be refunded on cancel, got {ticket['state']}"
    )

    assignment = get_success_data(api_client.get_assignment(
        event_id, ctx["assignment"]["id"], ctx["coordinator_headers"]))
    assert assignment["status"] == "FORFEITED"

    slots = get_success_data(api_client.list_load_slots(
        event_id, ctx["coordinator_headers"]))
    assert slots == [], f"every LoadInSlot must be deleted outright, got {slots}"


def test_cancel_from_weather_hold_refunds_redeemed_ticket_and_releases_booth(api):
    """PRD §3.6: "Cancelling from `WEATHER_HOLD` moves the event to `CANCELLED` and
    resolves everything outstanding: every ticket in `ISSUED` or `REDEEMED` is
    refunded at full face value to `REFUNDED`; every assignment in `PENDING_PAYMENT`
    or `ACTIVE` becomes `FORFEITED`; every settlement in `PENDING` or `COMPUTED`
    becomes `CANCELLED`; and every LoadInSlot is deleted outright."
    PRD §3.5: "A forfeited assignment mints a `REFUND` charge returning whatever was
    paid (zero when nothing was), clears the booth's `assigned_application_id`,
    cancels any Settlement tied to the assignment, and runs the waitlist promotion
    scan."

    Design: Difficulty/transitive_cascade/event_cancel_cascade_depth3
    """
    ctx = setup_live_ctx(zone_overrides={"weather_exposure": "COVERED"})
    event_id = ctx["event"]["id"]
    # Redeem the ticket while LIVE so the cancel cascade hits a REDEEMED ticket.
    ticket = sell_ticket(event_id, kind="GA", price_cents=1500)
    redeemed = validate_success(
        api_client.redeem_ticket(event_id, ticket["id"],
                                 TEST_USERS["gate_agent_headers"]),
        200,
    )
    assert redeemed["state"] == "REDEEMED"
    validate_success(
        api_client.set_weather(event_id, "SEVERE", ctx["coordinator_headers"]), 200
    )

    event = validate_success(
        api_client.cancel_event(event_id, ctx["coordinator_headers"]), 200
    )
    assert event["posture"] == "CANCELLED"

    ticket_after = get_success_data(api_client.get_ticket(
        event_id, ticket["id"], ctx["coordinator_headers"]))
    assert ticket_after["state"] == "REFUNDED", (
        f"REDEEMED ticket must be refunded at full face value, got "
        f"{ticket_after['state']}"
    )

    assignment = get_success_data(api_client.get_assignment(
        event_id, ctx["assignment"]["id"], ctx["coordinator_headers"]))
    assert assignment["status"] == "FORFEITED"
    booth = get_success_data(
        api_client.get_booth(ctx["booths"][0]["id"], ctx["coordinator_headers"])
    )
    assert booth.get("assigned_application_id") is None, (
        "a forfeited assignment clears the booth's assigned_application_id"
    )
