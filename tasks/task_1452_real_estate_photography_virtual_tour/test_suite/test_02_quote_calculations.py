"""Provisional quote + shoot-duration calculations (PRD §3.1, §3.4)."""
from test_helpers import (
    api_client, validate_success, get_success_data, ApiErrorId,
    make_client_agent_headers, make_photographer_headers, make_coordinator_headers,
    make_ops_admin_headers,
    create_market, create_agent, create_booking, set_clock, submit_and_prepare,
    create_booking_payload,
)


class TestShootDuration:
    def test_overage_step_boundary_25_vs_26(self, api):
        """PRD §3.1: "The base length depends on the package: sixty minutes for
        `STANDARD` ... Each package includes a photo allotment — twenty-five, forty,
        and sixty photos respectively — and every started group of five photos beyond
        the allotment adds ten minutes, so a partial group still contributes the full ten."

        Design: Corner/calculations/shoot_duration_overage_step_boundary_25_vs_26
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])

        b25 = create_booking(agent, market["id"], order_ref="ORD-D25",
                             property_address="25 Boundary St", photo_count=25,
                             scheduled_start_utc="2026-08-10T14:00:00Z")
        b26 = create_booking(agent, market["id"], order_ref="ORD-D26",
                             property_address="26 Boundary St", photo_count=26,
                             scheduled_start_utc="2026-08-10T14:00:00Z")

        assert b25["shoot_duration_minutes"] == 60
        assert b25["scheduled_end_utc"] == "2026-08-10T15:00:00Z"
        # 1 photo over the allotment = one started group of five -> +10 minutes
        assert b26["shoot_duration_minutes"] == 70
        assert b26["scheduled_end_utc"] == "2026-08-10T15:10:00Z"

    def test_twilight_booking_duration_overrides_package_math(self, api):
        """PRD §3.1: "A twilight booking ignores this arithmetic entirely: its duration
        is simply the market's `twilight_slot_minutes`, occupying exactly one twilight slot."

        Design: Corner/calculations/twilight_booking_duration_overrides_package_math
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48,
                               twilight_slot_minutes=60)
        agent = create_agent(market["id"])

        booking = create_booking(agent, market["id"], order_ref="ORD-TWD",
                                 property_address="60 Dusk Ct", equipment_package="LUXURY",
                                 photo_count=100, scheduled_start_utc="2026-08-10T19:00:00Z",
                                 is_twilight=True)
        # LUXURY/100 would otherwise be 120 + ceil(40/5)*10 = 200 minutes
        assert booking["shoot_duration_minutes"] == 60
        assert booking["scheduled_end_utc"] == "2026-08-10T20:00:00Z"


class TestProvisionalQuote:
    def test_nested_rounding_per_line_then_sum(self, api):
        """PRD §3.1: "The locked quote is computed line by line, and the order of
        operations is pinned: each money line is computed in isolation and rounded
        half-up to whole cents, and only then are the lines summed."

        With multiplier 10033 the per-line-then-sum order (15050 + 1806 = 16856)
        diverges by one cent from sum-then-round (16855); the pinned order wins.

        Design: Difficulty/combinatorial_formula/provisional_quote_nested_rounding_per_line_then_sum
        """
        set_clock()
        market = create_market(market_code="RND", display_name="Rounding Market",
                               pricing_multiplier_bps=10033, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        booking = create_booking(agent, market["id"], order_ref="ORD-RND",
                                 property_address="5 Fraction Ln",
                                 equipment_package="STANDARD", photo_count=31,
                                 scheduled_start_utc="2026-08-10T14:00:00Z")

        headers = make_client_agent_headers(agent["id"])
        resp = api_client.submit_booking(booking["id"], headers)
        submitted = validate_success(resp)
        # base: rhu(15000 * 10033/10000) = rhu(15049.5) = 15050
        # overage: 6 photos * 300 = 1800; rhu(1800 * 1.0033) = rhu(1805.94) = 1806
        assert submitted["provisional_quote_cents"] == 15050 + 1806
        # locked at submit: the same figure survives the DRAFT -> AWAITING_READINESS move
        reread = get_success_data(api_client.get_booking(booking["id"], headers))
        assert reread["provisional_quote_cents"] == submitted["provisional_quote_cents"]

    def test_quote_locked_at_submit_not_at_create(self, api):
        """PRD §3.1: "Submission locks the booking's `provisional_quote_cents` and
        spawns the property-readiness checklist ..."
        PRD §3.1: "The locked quote is computed line by line, and the order of
        operations is pinned: each money line is computed in isolation and rounded
        half-up to whole cents, and only then are the lines summed."

        Design: Difficulty/combinatorial_formula/provisional_quote_nested_rounding_per_line_then_sum
        """
        set_clock()
        market = create_market(market_code="RND", display_name="Rounding Market",
                               pricing_multiplier_bps=10033, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        booking = create_booking(agent, market["id"], order_ref="ORD-RND2",
                                 property_address="6 Fraction Ln",
                                 equipment_package="STANDARD", photo_count=31,
                                 scheduled_start_utc="2026-08-10T14:00:00Z")
        # before submission there is no locked quote
        assert booking.get("provisional_quote_cents") is None

        headers = make_client_agent_headers(agent["id"])
        submitted = validate_success(api_client.submit_booking(booking["id"], headers))
        assert submitted["state"] == "AWAITING_READINESS"
        assert submitted["provisional_quote_cents"] == 16856

    def test_volume_discount_floor_exact_and_below(self, api):
        """PRD §3.1: "When those add-on lines together reach or exceed 50000 cents,
        a volume discount of ten percent of the add-on lines (1000 basis points),
        rounded half-up, is subtracted — and the discount never touches the base,
        overage, tour, or twilight lines."

        Design: Corner/calculations/volume_discount_floor_49999_vs_50000
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        headers = make_client_agent_headers(agent["id"])

        # K1: DRONE_VIDEO(35000) + RUSH_EDIT(15000) = exactly 50000 -> discount 5000
        k1 = create_booking(agent, market["id"], order_ref="ORD-K1",
                            property_address="50 Exact St", photo_count=20,
                            scheduled_start_utc="2026-08-10T08:00:00Z")
        get_success_data(api_client.create_addon(k1["id"], "DRONE_VIDEO", headers))
        get_success_data(api_client.create_addon(k1["id"], "RUSH_EDIT", headers))
        # K2: DRONE_VIDEO alone = 35000 -> below the floor, no discount
        k2 = create_booking(agent, market["id"], order_ref="ORD-K2",
                            property_address="35 Under St", photo_count=20,
                            scheduled_start_utc="2026-08-11T08:00:00Z")
        get_success_data(api_client.create_addon(k2["id"], "DRONE_VIDEO", headers))
        # K3: DRONE_VIDEO + RUSH_EDIT + VIRTUAL_STAGING = 60000 -> discount 6000
        k3 = create_booking(agent, market["id"], order_ref="ORD-K3",
                            property_address="60 Over St", photo_count=20,
                            scheduled_start_utc="2026-08-12T08:00:00Z")
        get_success_data(api_client.create_addon(k3["id"], "DRONE_VIDEO", headers))
        get_success_data(api_client.create_addon(k3["id"], "RUSH_EDIT", headers))
        get_success_data(api_client.create_addon(k3["id"], "VIRTUAL_STAGING", headers))

        q1 = validate_success(api_client.submit_booking(k1["id"], headers))
        q2 = validate_success(api_client.submit_booking(k2["id"], headers))
        q3 = validate_success(api_client.submit_booking(k3["id"], headers))

        assert q1["provisional_quote_cents"] == 15000 + 50000 - 5000  # 60000
        assert q2["provisional_quote_cents"] == 15000 + 35000          # 50000
        assert q3["provisional_quote_cents"] == 15000 + 60000 - 6000   # 69000

    def test_quote_vs_invoice_on_shootbooking_money_domain(self, api):
        """PRD §3.1: "Once the booking leaves `DRAFT`, the quote is locked and is not
        recomputed, even if the booking later regresses to `DRAFT`."
        PRD §3.8: "Acceptance computes `final_invoice_cents` in a pinned evaluation
        order. The locked `provisional_quote_cents` is taken as the stable base ..."

        The locked quote (35625: base 18750 + overage 1875 + BRANDED tour 15000) and
        the final invoice (62062: +25000 drone delta, -3563 weather credit, +5000
        STANDARD_MARKETING license fee) are two valid algorithms over the same
        booking and must differ once a drone add-on and a weather credit accrue
        after submit.

        Design: Difficulty/dual_variant_calc/quote_vs_invoice_on_shootbooking_money_domain
        """
        from test_helpers import (
            create_photographer, create_ready_booking, assign_booking, confirm_booking,
            weather_reschedule, first_authorization, get_booking,
        )
        set_clock()
        market = create_market(market_code="ATX", display_name="Austin",
                               pricing_multiplier_bps=12500, standard_turnaround_hours=48,
                               travel_buffer_minutes=45, weather_reschedule_credit_bps=1000)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"], drone_certified=True)
        agent = create_agent(market["id"])
        headers = make_client_agent_headers(agent["id"])

        booking = create_ready_booking(
            agent, market["id"], order_ref="ORD-1", property_address="1 Main St",
            equipment_package="STANDARD", photo_count=30,
            scheduled_start_utc="2026-08-10T14:00:00Z",
            wants_virtual_tour=True, tour_variant="BRANDED",
            license_tier="STANDARD_MARKETING")
        assign_booking(booking["id"], photog["id"])
        booking = confirm_booking(booking["id"])

        # weather reschedule: 10% of the 35625-cent locked quote = rhu(3562.5) = 3563
        booking = weather_reschedule(booking, agent, "2026-08-12T14:00:00Z", "PRECIPITATION")
        assert booking["weather_credit_cents"] == 3563
        booking = confirm_booking(booking["id"])

        # drone add-on attached AFTER the quote locked: 20000 * 1.25 = 25000
        drone = get_success_data(api_client.create_addon(booking["id"], "DRONE_STILLS", headers))
        assert drone["price_cents"] == 25000
        auth = first_authorization(booking["id"])
        get_success_data(api_client.approve_authorization(booking["id"], auth["id"], make_ops_admin_headers()))

        set_clock("2026-08-12T14:00:00Z")
        get_success_data(api_client.mark_shot(booking["id"], make_photographer_headers(photog["id"])))
        get_success_data(api_client.deliver(
            booking["id"], {"photo_asset_count": 30, "tour_asset_url": "https://tour.example.com/t/1"},
            make_photographer_headers(photog["id"])))

        resp = api_client.accept_booking(booking["id"], headers)
        accepted = validate_success(resp)

        assert accepted["provisional_quote_cents"] == 35625
        assert accepted["state"] == "ACCEPTED"
        # pinned order: 35625 + (25000 - 0) addon delta - 0 rush - 0 late - 3563 credit + 5000 license
        assert accepted["final_invoice_cents"] == 62062
        assert accepted["final_invoice_cents"] != accepted["provisional_quote_cents"]

        license_list = get_success_data(api_client.get_license(booking["id"], headers))
        assert license_list[0]["tier"] == "STANDARD_MARKETING"
        assert license_list[0]["fee_cents"] == 5000

    def test_quote_immutable_after_addon_activation_post_submit(self, api):
        """PRD §3.1: "Once the booking leaves `DRAFT`, the quote is locked and is not
        recomputed, even if the booking later regresses to `DRAFT`."
        PRD §3.8: "The locked `provisional_quote_cents` is taken as the stable base;
        its line decomposition is not recomputed, even though it already reflects the
        add-ons and volume discount priced at submit time. The add-on set is then
        re-delta'd: the sum of `price_cents` over the add-ons `ACTIVE` at acceptance is
        compared against the add-on total baked into the locked quote ..."

        A drone add-on attached after submission reprices the acceptance (via the
        add-on delta) but never the locked quote.

        Design: Difficulty/dual_variant_calc/quote_vs_invoice_on_shootbooking_money_domain
        """
        from test_helpers import create_photographer, create_ready_booking
        set_clock()
        market = create_market(market_code="ATX", display_name="Austin",
                               pricing_multiplier_bps=12500, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        booking = create_ready_booking(
            agent, market["id"], order_ref="ORD-1B", property_address="2 Main St",
            equipment_package="STANDARD", photo_count=30,
            scheduled_start_utc="2026-08-10T14:00:00Z")
        # locked quote: base 18750 + overage 1875 = 20625, no add-ons at submit time
        assert booking["provisional_quote_cents"] == 20625

        headers = make_client_agent_headers(agent["id"])
        drone = get_success_data(api_client.create_addon(booking["id"], "DRONE_STILLS", headers))
        assert drone["price_cents"] == 25000  # rhu(20000 * 1.25)

        after = get_success_data(api_client.get_booking(booking["id"], headers))
        assert after["provisional_quote_cents"] == 20625  # locked, not recomputed
