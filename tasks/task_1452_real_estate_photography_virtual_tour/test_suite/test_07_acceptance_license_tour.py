"""Acceptance, invoicing, licensing, and tour hosting (PRD §3.6, §3.8)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    make_client_agent_headers, make_photographer_headers, make_coordinator_headers,
    make_ops_admin_headers,
    create_market, create_photographer, create_agent, create_booking, set_clock,
    create_confirmed_booking, create_accepted_booking, weather_reschedule,
    get_booking, get_agent, submit_and_prepare, assign_booking, confirm_booking,
)


class TestUnbrandedTierGate:
    def test_unbranded_tour_requires_mls_tier_at_acceptance(self, api):
        """PRD §3.8: "if the booking's `tour_variant` is `UNBRANDED`, its `license_tier`
        must be `MLS_COMPLIANT` at this moment, or acceptance fails with
        `ERR_UNBRANDED_REQUIRES_MLS_TIER` (HTTP 422). This tier check is enforced here —
        at acceptance — and not at creation or delivery."

        Design: Corner/validations/unbranded_tour_requires_mls_tier_at_acceptance
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking = create_confirmed_booking(
            agent, photog, market["id"], order_ref="ORD-UGATE",
            property_address="77 Brand Blvd", photo_count=20,
            scheduled_start_utc="2026-08-05T14:00:00Z",
            wants_virtual_tour=True, tour_variant="UNBRANDED",
            license_tier="STANDARD_MARKETING")
        set_clock("2026-08-05T14:30:00Z")
        photog_headers = make_photographer_headers(photog["id"])
        get_success_data(api_client.mark_shot(booking["id"], photog_headers))
        get_success_data(api_client.deliver(
            booking["id"], {"photo_asset_count": 20,
                            "tour_asset_url": "https://tour.example.com/u/77"},
            photog_headers))
        # delivery succeeded with the non-MLS tier: the gate lives at acceptance
        assert get_booking(booking["id"])["state"] == "DELIVERED"

        resp = api_client.accept_booking(booking["id"], make_client_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_UNBRANDED_REQUIRES_MLS_TIER)
        assert get_booking(booking["id"])["state"] == "DELIVERED"
        grants = get_success_data(api_client.get_license(booking["id"],
                                                         make_client_agent_headers(agent["id"])))
        assert grants[0]["state"] == "DORMANT"

    def test_license_fee_unbranded_surcharge_applied(self, api):
        """PRD §3.8: "its `fee_cents` resolves from the tier and tour variant — zero
        cents for `MLS_COMPLIANT`, 5000 for `STANDARD_MARKETING`, and 15000 for
        `EXTENDED`, plus a 4000-cent unbranded surcharge when the booking's
        `tour_variant` is `UNBRANDED`."

        Design: Corner/calculations/license_fee_unbranded_surcharge_applied
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking, _bundle = create_accepted_booking(
            agent, photog, market["id"], "2026-08-05T14:30:00Z",
            order_ref="ORD-UNB", property_address="44 MLS Row", photo_count=20,
            scheduled_start_utc="2026-08-05T14:00:00Z",
            wants_virtual_tour=True, tour_variant="UNBRANDED",
            license_tier="MLS_COMPLIANT",
            tour_asset_url="https://tour.example.com/u/44")
        assert booking["state"] == "ACCEPTED"

        headers = make_client_agent_headers(agent["id"])
        grants = get_success_data(api_client.get_license(booking["id"], headers))
        assert grants[0]["state"] == "ACTIVE"
        assert grants[0]["tier"] == "MLS_COMPLIANT"
        assert grants[0]["fee_cents"] == 0 + 4000  # base 0 + unbranded surcharge

        tours = get_success_data(api_client.get_virtual_tour(booking["id"], headers))
        assert tours[0]["variant"] == "UNBRANDED"
        assert tours[0]["state"] == "PUBLISHED"


class TestLicenseTourCascade:
    def test_license_suspend_cascade_depth2_tour_gated(self, api):
        """PRD §3.8: "Suspending a license requires it to be `ACTIVE` ... and moves it
        to `SUSPENDED`; if the tour is `PUBLISHED` at that moment, the tour cascades to
        `SUSPENDED` with it. Reinstating requires the license to be `SUSPENDED` ... and
        returns it to `ACTIVE` — but the tour is deliberately not auto-resumed and stays
        `SUSPENDED` until separately resumed."

        Design: Difficulty/transitive_cascade/license_suspend_cascade_depth2_tour_gated
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking, _bundle = create_accepted_booking(
            agent, photog, market["id"], "2026-08-05T14:30:00Z",
            order_ref="ORD-LIC", property_address="8 View Ct", photo_count=20,
            scheduled_start_utc="2026-08-05T14:00:00Z",
            wants_virtual_tour=True, tour_variant="BRANDED",
            license_tier="STANDARD_MARKETING",
            tour_asset_url="https://tour.example.com/t/8")
        headers = make_client_agent_headers(agent["id"])
        ops = make_ops_admin_headers()
        tour_before = get_success_data(api_client.get_virtual_tour(booking["id"], headers))[0]
        assert tour_before["state"] == "PUBLISHED"
        published_at = tour_before["published_at_utc"]

        # hop 1 -> hop 2: license suspension cascades the tour to SUSPENDED
        get_success_data(api_client.suspend_license(booking["id"], ops))
        grant = get_success_data(api_client.get_license(booking["id"], headers))[0]
        tour = get_success_data(api_client.get_virtual_tour(booking["id"], headers))[0]
        assert grant["state"] == "SUSPENDED"
        assert tour["state"] == "SUSPENDED"

        # reinstate returns the license to ACTIVE but deliberately leaves the tour down
        get_success_data(api_client.reinstate_license(booking["id"], ops))
        grant = get_success_data(api_client.get_license(booking["id"], headers))[0]
        tour = get_success_data(api_client.get_virtual_tour(booking["id"], headers))[0]
        assert grant["state"] == "ACTIVE"
        assert tour["state"] == "SUSPENDED"
        assert tour["published_at_utc"] == published_at

    def test_tour_resume_gated_by_license_pair(self, api):
        """PRD §3.8: "may later resume a suspended tour, which requires the tour to be
        `SUSPENDED` (otherwise `ERR_TOUR_NOT_SUSPENDED`) and additionally requires the
        booking to be `ACCEPTED` with its license `ACTIVE` (otherwise
        `ERR_LICENSE_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/virtualtour_resume_gated_by_licensegrant_pair
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking, _bundle = create_accepted_booking(
            agent, photog, market["id"], "2026-08-05T14:30:00Z",
            order_ref="ORD-X2", property_address="15 Lens Ln", photo_count=20,
            scheduled_start_utc="2026-08-05T14:00:00Z",
            wants_virtual_tour=True, tour_variant="BRANDED",
            license_tier="EXTENDED",
            tour_asset_url="https://tour.example.com/t/15")
        ops = make_ops_admin_headers()
        headers = make_client_agent_headers(agent["id"])

        # license suspension cascades the tour to SUSPENDED
        get_success_data(api_client.suspend_license(booking["id"], ops))

        # resume is gated on the license: still SUSPENDED -> rejected
        resp = api_client.resume_tour(booking["id"], ops)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)
        tour = get_success_data(api_client.get_virtual_tour(booking["id"], headers))[0]
        assert tour["state"] == "SUSPENDED"

        # reinstate the license, then resume succeeds
        get_success_data(api_client.reinstate_license(booking["id"], ops))
        resumed = validate_success(api_client.resume_tour(booking["id"], ops))
        assert resumed["state"] == "PUBLISHED"


    def test_license_revocation_unpublishes_tour(self, api):
        """PRD §3.8: "Revocation moves a license from `ACTIVE` or `SUSPENDED` to the
        terminal `REVOKED` — attempting it in any other state fails with
        `ERR_LICENSE_NOT_ACTIVE` — and sends the tour to `UNPUBLISHED` if it is not
        already there."

        Design: Difficulty/transitive_cascade/license_suspend_cascade_depth2_tour_gated
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking, _bundle = create_accepted_booking(
            agent, photog, market["id"], "2026-08-05T14:30:00Z",
            order_ref="ORD-LIC2", property_address="9 View Ct", photo_count=20,
            scheduled_start_utc="2026-08-05T14:00:00Z",
            wants_virtual_tour=True, tour_variant="BRANDED",
            license_tier="STANDARD_MARKETING",
            tour_asset_url="https://tour.example.com/t/9")
        headers = make_client_agent_headers(agent["id"])
        ops = make_ops_admin_headers()

        # suspend cascades to the tour; revocation from SUSPENDED then unpublishes it
        get_success_data(api_client.suspend_license(booking["id"], ops))
        grant = get_success_data(api_client.get_license(booking["id"], headers))[0]
        assert grant["state"] == "SUSPENDED"

        revoked = validate_success(api_client.revoke_license(booking["id"], ops))
        assert revoked["state"] == "REVOKED"
        tour = get_success_data(api_client.get_virtual_tour(booking["id"], headers))[0]
        assert tour["state"] == "UNPUBLISHED"

    def test_resume_requires_suspended_tour(self, api):
        """PRD §3.8: "may later resume a suspended tour, which requires the tour to be
        `SUSPENDED` (otherwise `ERR_TOUR_NOT_SUSPENDED`) and additionally requires the
        booking to be `ACCEPTED` with its license `ACTIVE` (otherwise
        `ERR_LICENSE_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/virtualtour_resume_gated_by_licensegrant_pair
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking, _bundle = create_accepted_booking(
            agent, photog, market["id"], "2026-08-05T14:30:00Z",
            order_ref="ORD-X3", property_address="16 Lens Ln", photo_count=20,
            scheduled_start_utc="2026-08-05T14:00:00Z",
            wants_virtual_tour=True, tour_variant="BRANDED",
            license_tier="EXTENDED",
            tour_asset_url="https://tour.example.com/t/16")
        ops = make_ops_admin_headers()

        # the tour is PUBLISHED (not SUSPENDED): resume is not a legal transition
        resp = api_client.resume_tour(booking["id"], ops)
        validate_error(resp, ApiErrorId.ERR_TOUR_NOT_SUSPENDED)
        headers = make_client_agent_headers(agent["id"])
        tour = get_success_data(api_client.get_virtual_tour(booking["id"], headers))[0]
        assert tour["state"] == "PUBLISHED"


class TestFinalInvoiceOrder:
    def test_final_invoice_circular_dependency_pinned_order(self, api):
        """PRD §3.8: "Acceptance computes `final_invoice_cents` in a pinned evaluation
        order." The pinned order is: locked quote as base; add-on delta; "If a
        `RUSH_EDIT` add-on is `ACTIVE` and the delivery landed after `delivery_due_utc`,
        the rush fee is refunded in full: the entire `RUSH_EDIT` add-on price is
        subtracted as a rush discount."; paid revision fees; "When delivery was late, a
        late penalty of fifteen percent of the provisional quote (1500 basis points),
        rounded half-up to whole cents, is subtracted ..."; "The accumulated
        `weather_credit_cents` — never more than thirty percent of the provisional
        quote — is subtracted."; "Finally, the license fee resolved at activation is
        added."

        A late RUSH_EDIT delivery after one weather reschedule:
        20625 quote + (18750 - 0) add-on delta - 18750 rush discount - 3094 late
        penalty [rhu(20625 * 0.15)] - 2063 weather credit + 0 license fee = 15468.

        Design: Difficulty/combinatorial_formula/final_invoice_circular_dependency_pinned_order
        """
        set_clock()
        market = create_market(market_code="ATX", display_name="Austin",
                               pricing_multiplier_bps=12500, standard_turnaround_hours=48,
                               weather_reschedule_credit_bps=1000)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        headers = make_client_agent_headers(agent["id"])
        photog_headers = make_photographer_headers(photog["id"])

        booking = create_confirmed_booking(
            agent, photog, market["id"], order_ref="ORD-CIRC",
            property_address="9 Loop Ct", equipment_package="STANDARD", photo_count=30,
            scheduled_start_utc="2026-08-05T14:00:00Z", license_tier="MLS_COMPLIANT")
        # quote locked at submit: base rhu(15000*1.25)=18750 + overage rhu(5*300*1.25)=1875
        assert booking["provisional_quote_cents"] == 20625

        booking = weather_reschedule(booking, agent, "2026-08-06T14:00:00Z", "PRECIPITATION")
        assert booking["weather_credit_cents"] == 2063  # rhu(20625 * 0.10)
        booking = confirm_booking(booking["id"])

        rush = get_success_data(api_client.create_addon(booking["id"], "RUSH_EDIT", headers))
        assert rush["price_cents"] == 18750  # rhu(15000 * 1.25)

        set_clock("2026-08-06T14:30:00Z")
        shot = get_success_data(api_client.mark_shot(booking["id"], photog_headers))
        # rush halves 48h -> 24h; one weather event adds 24h -> due = marked + 48h
        assert shot["delivery_due_utc"] == "2026-08-08T14:30:00Z"

        # deliver 30 minutes late: both the rush refund and the late penalty apply
        set_clock("2026-08-08T15:00:00Z")
        get_success_data(api_client.deliver(booking["id"], {"photo_asset_count": 30},
                                            photog_headers))
        accepted = validate_success(api_client.accept_booking(booking["id"], headers))
        assert accepted["delivered_at_utc"] == "2026-08-08T15:00:00Z"
        assert accepted["state"] == "ACCEPTED"
        assert accepted["final_invoice_cents"] == 15468

    def test_final_invoice_on_time_variant_no_penalty_no_refund(self, api):
        """PRD §3.8: "an on-time delivery carries neither the late penalty nor the
        rush refund, and a late rush delivery deliberately receives both reliefs."
        PRD §3.8: "The invoice is the resulting total floored at zero ..."

        The same RUSH_EDIT booking delivered before its delivery_due_utc: the rush fee
        stays charged and no fifteen-percent penalty applies.

        Design: Difficulty/combinatorial_formula/final_invoice_circular_dependency_pinned_order
        """
        set_clock()
        market = create_market(market_code="ATX", display_name="Austin",
                               pricing_multiplier_bps=12500, standard_turnaround_hours=48,
                               weather_reschedule_credit_bps=1000)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        headers = make_client_agent_headers(agent["id"])
        photog_headers = make_photographer_headers(photog["id"])

        booking = create_confirmed_booking(
            agent, photog, market["id"], order_ref="ORD-CIRC2",
            property_address="10 Loop Ct", equipment_package="STANDARD", photo_count=30,
            scheduled_start_utc="2026-08-05T14:00:00Z", license_tier="MLS_COMPLIANT")
        assert booking["provisional_quote_cents"] == 20625

        booking = weather_reschedule(booking, agent, "2026-08-06T14:00:00Z", "PRECIPITATION")
        booking = confirm_booking(booking["id"])
        get_success_data(api_client.create_addon(booking["id"], "RUSH_EDIT", headers))

        set_clock("2026-08-06T14:30:00Z")
        get_success_data(api_client.mark_shot(booking["id"], photog_headers))
        # on-time delivery well before the 2026-08-08T14:30:00Z deadline
        set_clock("2026-08-07T12:00:00Z")
        get_success_data(api_client.deliver(booking["id"], {"photo_asset_count": 30},
                                            photog_headers))
        accepted = validate_success(api_client.accept_booking(booking["id"], headers))
        # 20625 quote + (18750 - 0) add-on delta - 0 rush - 0 late - 2063 credit + 0 license
        assert accepted["final_invoice_cents"] == 37312

    def test_agent_credit_conserved_across_credit_and_invoice(self, api):
        """PRD §3.9: "the booking's `weather_credit_cents` becomes the smaller of the
        old accumulation plus the raw credit and the cap; and the event's
        `credit_applied_cents` records only the marginal amount this event actually
        contributed ..."
        PRD §3.8: "The accumulated `weather_credit_cents` — never more than thirty
        percent of the provisional quote — is subtracted." and "The accumulated weather
        credit, having been deducted from the invoice, is then zeroed off the booking's
        `weather_credit_cents` ..."

        Design: Difficulty/compensating_invariant/agent_credit_balance_conserved_across_weather_credit_and_invoice_application
        """
        set_clock()
        market = create_market(market_code="ATX", display_name="Austin",
                               pricing_multiplier_bps=12500, standard_turnaround_hours=48,
                               weather_reschedule_credit_bps=1000)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        headers = make_client_agent_headers(agent["id"])

        booking = create_confirmed_booking(
            agent, photog, market["id"], order_ref="ORD-CONS",
            property_address="21 Ledger Ln", equipment_package="STANDARD", photo_count=30,
            scheduled_start_utc="2026-08-05T14:00:00Z", license_tier="MLS_COMPLIANT")
        booking = weather_reschedule(booking, agent, "2026-08-06T14:00:00Z", "PRECIPITATION")
        assert booking["weather_credit_cents"] == 2063
        assert get_agent(agent["id"])["credit_balance_cents"] == 0  # parked on the booking
        booking = confirm_booking(booking["id"])

        set_clock("2026-08-06T14:30:00Z")
        photog_headers = make_photographer_headers(photog["id"])
        get_success_data(api_client.mark_shot(booking["id"], photog_headers))
        get_success_data(api_client.deliver(booking["id"], {"photo_asset_count": 30},
                                            photog_headers))

        accepted = validate_success(api_client.accept_booking(booking["id"], headers))
        # credit applied exactly once: 20625 - 2063 + 0 license fee
        assert accepted["final_invoice_cents"] == 20625 - 2063
        # the ledger entry equals the invoice deduction exactly
        events = get_success_data(api_client.list_reschedule_events(booking["id"], headers))
        assert events[0]["credit_applied_cents"] == 2063
        # the deducted credit is zeroed off the booking — money conserved, not duplicated
        assert accepted["weather_credit_cents"] == 0

    def test_weather_credit_parked_on_booking_until_acceptance(self, api):
        """PRD §3.9: "the booking's `weather_credit_cents` becomes the smaller of the
        old accumulation plus the raw credit and the cap ..."
        PRD §3.8: "The accumulated weather credit, having been deducted from the
        invoice, is then zeroed off the booking's `weather_credit_cents`; the agent's
        prepaid `credit_balance_cents` ledger is the standing destination where weather
        credits and refunds accrue."

        Two weather reschedules accumulate on the booking (2063 + 2063 = 4126 at a 10%
        market credit rate) while the agent's ledger stays at zero until acceptance.

        Design: Difficulty/compensating_invariant/agent_credit_balance_conserved_across_weather_credit_and_invoice_application
        """
        set_clock()
        market = create_market(market_code="ATX", display_name="Austin",
                               pricing_multiplier_bps=12500, standard_turnaround_hours=48,
                               weather_reschedule_credit_bps=1000)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        headers = make_client_agent_headers(agent["id"])

        booking = create_confirmed_booking(
            agent, photog, market["id"], order_ref="ORD-CONS2",
            property_address="22 Ledger Ln", equipment_package="STANDARD", photo_count=30,
            scheduled_start_utc="2026-08-05T14:00:00Z", license_tier="MLS_COMPLIANT")
        booking = weather_reschedule(booking, agent, "2026-08-06T14:00:00Z", "WIND")
        booking = confirm_booking(booking["id"])
        booking = weather_reschedule(booking, agent, "2026-08-07T14:00:00Z", "LOW_LIGHT")
        assert booking["weather_credit_cents"] == 4126  # two raw applications of 2063
        # nothing has reached the agent's standing ledger before acceptance
        assert get_agent(agent["id"])["credit_balance_cents"] == 0

        events = get_success_data(api_client.list_reschedule_events(booking["id"], headers))
        assert [e["credit_applied_cents"] for e in events] == [2063, 2063]


class TestTerminalLockdown:
    def test_terminal_booking_rejects_all_further_transitions(self, api):
        """PRD §3.9: "The owning agent may cancel from `DRAFT`, `AWAITING_READINESS`,
        `READY`, `ASSIGNED`, `AUTHORIZATION_PENDING`, or `CONFIRMED`; from any other
        state the attempt fails with `ERR_BOOKING_NOT_CANCELLABLE`."
        PRD §3.9: "The booking must be in `ASSIGNED`, `AUTHORIZATION_PENDING`, or
        `CONFIRMED` (otherwise `ERR_BOOKING_NOT_RESCHEDULABLE`) ..."
        PRD §3.9: "Together with `ACCEPTED`, `CANCELLED_WEATHER`, and clock-driven
        `EXPIRED`, these are the four terminal states in which a booking's story ends."

        Design: Corner/state_machines/terminal_booking_rejects_all_further_transitions
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking, _bundle = create_accepted_booking(
            agent, photog, market["id"], "2026-08-05T14:30:00Z",
            order_ref="ORD-TERM", property_address="4 Final Ct", photo_count=20,
            scheduled_start_utc="2026-08-05T14:00:00Z")
        headers = make_client_agent_headers(agent["id"])

        resp1 = api_client.cancel_booking(booking["id"], headers)
        validate_error(resp1, ApiErrorId.ERR_BOOKING_NOT_CANCELLABLE)

        version = get_booking(booking["id"])["version"]
        resp2 = api_client.reschedule_booking(
            booking["id"],
            {"expected_booking_version": version, "kind": "CLIENT",
             "new_start_utc": "2026-08-20T14:00:00Z", "reason_code": "SELLER_DELAY"},
            headers)
        validate_error(resp2, ApiErrorId.ERR_BOOKING_NOT_RESCHEDULABLE)
        assert get_booking(booking["id"])["state"] == "ACCEPTED"
