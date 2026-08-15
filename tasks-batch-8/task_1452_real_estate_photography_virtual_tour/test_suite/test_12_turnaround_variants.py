"""Turnaround deadline dual variants: standard vs weather-extended clock (PRD §3.6)."""
from test_helpers import (
    api_client, validate_success, get_success_data, ApiErrorId,
    make_client_agent_headers, make_photographer_headers, make_coordinator_headers,
    make_ops_admin_headers,
    create_market, create_photographer, create_agent, set_clock,
    create_confirmed_booking, weather_reschedule, confirm_booking, get_booking,
)


class TestTurnaroundDeadline:
    def test_standard_vs_weather_extended_clock(self, api):
        """PRD §3.6: "The turnaround rule derives the delivery deadline from the
        market's `standard_turnaround_hours`." and "Weather history then stretches the
        result: each consumed weather reschedule adds twenty-four hours of slack, but
        only the first two weather reschedules count — a booking with three weather
        reschedules receives forty-eight hours of extension, not seventy-two. The
        resulting `delivery_due_utc` is the mark-shot instant plus the adjusted hours,
        computed to whole-second precision ..."

        Two bookings in the same 48h market are marked shot at the same instant: the
        one with no weather history gets +48h; the one with three weather reschedules
        gets +96h — exactly 48h more, not 72h more.

        Design: Difficulty/dual_variant_calc/standard_vs_weather_extended_turnaround_clock_on_assetbundle_domain
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        p1 = create_photographer(market["id"], full_name="P One", email="p1@x.com",
                                 equipment_packages=["STANDARD"])
        p2 = create_photographer(market["id"], full_name="P Two", email="p2@x.com",
                                 equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])

        # B1: no weather history
        b1 = create_confirmed_booking(agent, p1, market["id"], order_ref="ORD-B1",
                                      property_address="10 Oak", photo_count=20,
                                      scheduled_start_utc="2026-08-10T14:00:00Z")

        # B2: three consumed WEATHER reschedules
        b2 = create_confirmed_booking(agent, p2, market["id"], order_ref="ORD-B2",
                                      property_address="20 Elm", photo_count=20,
                                      scheduled_start_utc="2026-08-06T14:00:00Z")
        for new_start, reason in (("2026-08-07T14:00:00Z", "WIND"),
                                  ("2026-08-08T14:00:00Z", "WIND"),
                                  ("2026-08-10T14:00:00Z", "LOW_LIGHT")):
            b2 = weather_reschedule(b2, agent, new_start, reason)
            b2 = confirm_booking(b2["id"])

        set_clock("2026-08-10T16:00:00Z")
        get_success_data(api_client.mark_shot(b1["id"], make_photographer_headers(p1["id"])))
        get_success_data(api_client.mark_shot(b2["id"], make_photographer_headers(p2["id"])))

        b1_after = get_booking(b1["id"])
        b2_after = get_booking(b2["id"])
        assert b1_after["delivery_due_utc"] == "2026-08-12T16:00:00Z"  # 48h standard clock
        assert b2_after["delivery_due_utc"] == "2026-08-14T16:00:00Z"  # 48h + min(3,2)*24h
        # the third weather event grants no further slack: delta is 48h exactly
        from test_helpers import parse
        delta = parse(b2_after["delivery_due_utc"]) - parse(b1_after["delivery_due_utc"])
        assert delta.total_seconds() == 48 * 3600

    def test_single_weather_event_extends_by_24h(self, api):
        """PRD §3.6: "Weather history then stretches the result: each consumed weather
        reschedule adds twenty-four hours of slack, but only the first two weather
        reschedules count — a booking with three weather reschedules receives
        forty-eight hours of extension, not seventy-two."

        One consumed weather event: 48h base + 24h slack = 72h after mark-shot.

        Design: Difficulty/dual_variant_calc/standard_vs_weather_extended_turnaround_clock_on_assetbundle_domain
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="P One", email="p1@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking = create_confirmed_booking(agent, photog, market["id"], order_ref="ORD-B3",
                                           property_address="30 Elm", photo_count=20,
                                           scheduled_start_utc="2026-08-09T14:00:00Z")
        booking = weather_reschedule(booking, agent, "2026-08-10T14:00:00Z", "WIND")
        booking = confirm_booking(booking["id"])

        set_clock("2026-08-10T16:00:00Z")
        get_success_data(api_client.mark_shot(booking["id"],
                                              make_photographer_headers(photog["id"])))
        assert get_booking(booking["id"])["delivery_due_utc"] == "2026-08-13T16:00:00Z"

    def test_turnaround_rush_and_staging_stack(self, api):
        """PRD §3.6: "An `ACTIVE` `RUSH_EDIT` add-on halves that figure, rounding up to
        a whole hour; an `ACTIVE` `VIRTUAL_STAGING` add-on adds twelve hours."

        Base 49h: ceil(49/2) = 25h, plus 12h = 37h after the mark-shot instant.

        Design: Corner/calculations/turnaround_rush_and_staging_stack
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=49)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        headers = make_client_agent_headers(agent["id"])

        from test_helpers import create_booking, submit_and_prepare, assign_booking, confirm_booking
        booking = create_booking(agent, market["id"], order_ref="ORD-TURN",
                                 property_address="37 Stack Ln", photo_count=20,
                                 scheduled_start_utc="2026-08-10T08:00:00Z")
        get_success_data(api_client.create_addon(booking["id"], "RUSH_EDIT", headers))
        get_success_data(api_client.create_addon(booking["id"], "VIRTUAL_STAGING", headers))
        booking = submit_and_prepare(booking, agent)
        assign_booking(booking["id"], photog["id"])
        confirm_booking(booking["id"])

        set_clock("2026-08-10T10:00:00Z")
        shot = get_success_data(api_client.mark_shot(
            booking["id"], make_photographer_headers(photog["id"])))
        assert shot["delivery_due_utc"] == "2026-08-11T23:00:00Z"  # 37h after mark-shot
