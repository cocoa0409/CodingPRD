"""Scheduling pipeline: state legality, shoot window, delivery gates (PRD §3.2, §3.6)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    make_client_agent_headers, make_photographer_headers, make_coordinator_headers,
    make_ops_admin_headers,
    create_market, create_photographer, create_agent, create_booking, set_clock,
    create_ready_booking, create_confirmed_booking, create_shot_booking,
    assign_booking, confirm_booking, get_booking,
)


def _pipeline_to_confirmed(api, start="2026-08-05T14:00:00Z", order_ref="ORD-P", **market_kw):
    market = create_market(market_code="DEN", display_name="Denver",
                           pricing_multiplier_bps=10000, standard_turnaround_hours=48)
    photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                 equipment_packages=["STANDARD"])
    agent = create_agent(market["id"])
    booking = create_confirmed_booking(agent, photog, market["id"],
                                       order_ref=order_ref, property_address="9 State St",
                                       equipment_package="STANDARD", photo_count=20,
                                       scheduled_start_utc=start)
    return market, photog, agent, booking


class TestStateLegality:
    def test_deliver_from_confirmed_returns_invalid_state(self, api):
        """PRD §3.6: "Delivery requires the booking to be `IN_EDIT` or
        `REVISION_REQUESTED` (otherwise `ERR_BOOKING_NOT_IN_EDIT`) ..."

        Design: Corner/state_machines/deliver_from_confirmed_returns_invalid_state
        """
        set_clock()
        market, photog, agent, booking = _pipeline_to_confirmed(api)

        resp = api_client.deliver(booking["id"], {"photo_asset_count": 20},
                                  make_photographer_headers(photog["id"]))
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_IN_EDIT)
        # no AssetBundle materialized by the rejected delivery
        bundles = get_success_data(api_client.list_bundles(booking["id"], make_coordinator_headers()))
        assert bundles == [], f"expected no bundles, got {bundles!r}"


class TestReadinessRegression:
    def test_uncheck_flips_ready_back_to_draft(self, api):
        """PRD §3.2: "If a required item that was checked is flipped back to unchecked
        while the booking is `AWAITING_READINESS`, the booking regresses to `DRAFT`; if
        a checked required item is unchecked while the booking is `READY`, it likewise
        regresses to `DRAFT`."
        PRD §3.2: "when the number of checked required items equals the total number of
        required items on the booking, readiness is complete, and a booking sitting in
        `AWAITING_READINESS` advances automatically to `READY` ..."

        Design: Corner/state_machines/readiness_regression_uncheck_flips_ready_back_to_draft
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        booking = create_booking(agent, market["id"], order_ref="ORD-REGR",
                                 property_address="5 Regress Rd",
                                 scheduled_start_utc="2026-08-10T14:00:00Z")
        headers = make_client_agent_headers(agent["id"])
        get_success_data(api_client.submit_booking(booking["id"], headers))
        items = get_success_data(api_client.list_checklist_items(booking["id"], headers,
                                                                 params={"limit": 100}))
        for item in items:
            get_success_data(api_client.patch_checklist_item(booking["id"], item["id"], True, headers))

        ready = get_booking(booking["id"])
        assert ready["state"] == "READY", "all five required items checked must auto-advance to READY"

        target = items[2]
        patched = validate_success(api_client.patch_checklist_item(
            booking["id"], target["id"], False, headers))
        assert patched["checked"] is False
        assert patched["checked_at_utc"] is None

        regressed = get_booking(booking["id"])
        assert regressed["state"] == "DRAFT"


class TestShootWindow:
    def test_markshot_window_enforcement(self, api):
        """PRD §3.6: "requires the current moment to fall inside the shoot window — no
        earlier than two hours before `scheduled_start_utc` and no later than
        twenty-four hours after `scheduled_end_utc` (otherwise `ERR_OUTSIDE_SHOOT_WINDOW`,
        HTTP 422)."

        Design: Corner/endpoints/markshot_window_enforcement
        """
        set_clock()
        market, photog, agent, booking = _pipeline_to_confirmed(
            api, start="2026-08-10T14:00:00Z", order_ref="ORD-WIN")
        photog_headers = make_photographer_headers(photog["id"])

        # 2h1m before the start — outside the window
        set_clock("2026-08-10T11:59:00Z")
        resp = api_client.mark_shot(booking["id"], photog_headers)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SHOOT_WINDOW)

        # exactly start - 2h — inside the window (closed lower bound)
        set_clock("2026-08-10T12:00:00Z")
        marked = validate_success(api_client.mark_shot(booking["id"], photog_headers))
        assert marked["state"] == "IN_EDIT"
        bundles = get_success_data(api_client.list_bundles(booking["id"], make_coordinator_headers()))
        assert len(bundles) == 1 and bundles[0]["state"] == "EDITING"
        assert bundles[0]["round_number"] == 1


class TestDeliveryGates:
    def test_quality_guarantee_shortfall_blocks_delivery(self, api):
        """PRD §3.6: "the bundle's `photo_asset_count` must meet or exceed the booking's
        contracted `photo_count` — the quality guarantee — or the delivery is rejected
        with `ERR_QUALITY_GUARANTEE_SHORTFALL` (HTTP 422) ..."

        Design: Corner/validations/quality_guarantee_shortfall_blocks_delivery
        """
        set_clock()
        market, photog, agent, booking = _pipeline_to_confirmed(api, order_ref="ORD-QG")
        photog_headers = make_photographer_headers(photog["id"])
        set_clock("2026-08-05T14:30:00Z")
        get_success_data(api_client.mark_shot(booking["id"], photog_headers))

        # one photo short of the contracted count
        resp = api_client.deliver(booking["id"], {"photo_asset_count": 19}, photog_headers)
        validate_error(resp, ApiErrorId.ERR_QUALITY_GUARANTEE_SHORTFALL)
        assert get_booking(booking["id"])["state"] == "IN_EDIT"

        # exactly the contracted count meets the guarantee
        delivered = validate_success(api_client.deliver(
            booking["id"], {"photo_asset_count": 20}, photog_headers))
        assert delivered["state"] == "DELIVERED"
        assert get_booking(booking["id"])["state"] == "DELIVERED"

    def test_tour_asset_required_only_when_wants_virtual_tour(self, api):
        """PRD §3.6: "when `wants_virtual_tour` is true, a non-null `tour_asset_url` is
        mandatory, or the delivery fails with `ERR_TOUR_ASSET_MISSING` (HTTP 422)."

        Design: Corner/validations/tour_asset_required_only_when_wants_virtual_tour
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        photog_headers = make_photographer_headers(photog["id"])

        # tour booking
        bt = create_confirmed_booking(agent, photog, market["id"], order_ref="ORD-VT",
                                      property_address="1 Tour Ct", photo_count=20,
                                      scheduled_start_utc="2026-08-05T08:00:00Z",
                                      wants_virtual_tour=True, tour_variant="BRANDED")
        set_clock("2026-08-05T08:30:00Z")
        get_success_data(api_client.mark_shot(bt["id"], photog_headers))

        # non-tour booking (next day so the windows do not collide); the slot
        # must be ≥24h from the live clock per PRD §3.1 submission gate.
        bn = create_confirmed_booking(agent, photog, market["id"], order_ref="ORD-NVT",
                                      property_address="2 Plain Ct", photo_count=20,
                                      scheduled_start_utc="2026-08-07T08:00:00Z")
        set_clock("2026-08-07T08:30:00Z")
        get_success_data(api_client.mark_shot(bn["id"], photog_headers))

        resp = api_client.deliver(bt["id"], {"photo_asset_count": 20}, photog_headers)
        validate_error(resp, ApiErrorId.ERR_TOUR_ASSET_MISSING)

        delivered = validate_success(api_client.deliver(
            bn["id"], {"photo_asset_count": 20}, photog_headers))
        assert delivered["state"] == "DELIVERED"
