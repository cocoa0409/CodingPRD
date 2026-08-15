"""Reverse-FK reachability, market policy gates, and admin lifecycle guards
(PRD §2.4, §2.9, §3.1, §3.3)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    make_client_agent_headers, make_photographer_headers, make_coordinator_headers,
    make_ops_admin_headers,
    create_market, create_photographer, create_agent, create_booking, set_clock,
    create_ready_booking, create_confirmed_booking, assign_booking, get_booking,
    confirm_booking,
)


class TestReverseReachability:
    def test_photographer_bookings_reverse_fk(self, api):
        """PRD §3.3: "a reverse listing exposes the bookings assigned to a
        photographer, filterable by `state`."
        PRD §3.3: "Unassignment releases the photographer: the committed minutes for
        the day are decremented by the released window, `assigned_photographer_id`
        returns to null ..."

        Design: Corner/endpoints/fk_reverse_reachability_photographer_bookings
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking = create_ready_booking(agent, market["id"], order_ref="ORD-FK",
                                       property_address="8 FK St",
                                       scheduled_start_utc="2026-08-10T14:00:00Z")
        assign_booking(booking["id"], photog["id"])

        data, _meta = validate_paginated(api_client.list_photographer_bookings(
            photog["id"], make_coordinator_headers()))
        assert len(data) == 1
        assert data[0]["id"] == booking["id"]

        get_success_data(api_client.unassign_booking(booking["id"], make_coordinator_headers()))
        data, _meta = validate_paginated(api_client.list_photographer_bookings(
            photog["id"], make_coordinator_headers()))
        assert data == []

    def test_client_agent_bookings_reverse_fk(self, api):
        """PRD §3.1: "The server stamps the booking's `client_agent_id` from the
        caller's `X-User-ID`, so an agent's bookings are always attributable to the
        account that created them."

        Design: Corner/endpoints/fk_reverse_reachability_client_agent_bookings
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent_a = create_agent(market["id"], full_name="Agent Ann", email="ann@x.com")
        agent_b = create_agent(market["id"], full_name="Agent Bob", email="bob@x.com")
        bk_a = create_booking(agent_a, market["id"], order_ref="ORD-A",
                              property_address="1 A St",
                              scheduled_start_utc="2026-08-10T14:00:00Z")
        bk_b = create_booking(agent_b, market["id"], order_ref="ORD-B",
                              property_address="2 B St",
                              scheduled_start_utc="2026-08-10T14:00:00Z")

        data, _meta = validate_paginated(api_client.list_agent_bookings(
            agent_a["id"], make_client_agent_headers(agent_a["id"])))
        ids = [b["id"] for b in data]
        assert bk_a["id"] in ids
        assert bk_b["id"] not in ids
        assert all(b["client_agent_id"] == agent_a["id"] for b in data)


class TestMarketPolicy:
    def test_submit_inside_24h_slot_rejected(self, api):
        """PRD §3.1: "requires the scheduled start to be no sooner than twenty-four
        hours from now (otherwise `ERR_SLOT_TOO_SOON`)."

        Design: Corner/validations/submit_inside_24h_slot_rejected
        """
        set_clock("2026-08-01T12:00:00Z")
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        headers = make_client_agent_headers(agent["id"])
        too_soon = create_booking(agent, market["id"], order_ref="ORD-S1",
                                  property_address="1 Soon St",
                                  scheduled_start_utc="2026-08-02T11:00:00Z")  # 23h ahead
        exact = create_booking(agent, market["id"], order_ref="ORD-S2",
                               property_address="2 Ok St",
                               scheduled_start_utc="2026-08-02T12:00:00Z")  # exactly 24h

        resp = api_client.submit_booking(too_soon["id"], headers)
        validate_error(resp, ApiErrorId.ERR_SLOT_TOO_SOON)

        submitted = validate_success(api_client.submit_booking(exact["id"], headers))
        assert submitted["state"] == "AWAITING_READINESS"

    def test_quarter_hour_alignment_enforced(self, api):
        """PRD §3.1: "a committed `scheduled_start_utc` that must land on a
        quarter-hour boundary; a start that is not aligned to a quarter hour is
        rejected with `ERR_INVALID_SLOT_ALIGNMENT`."

        Design: Corner/validations/quarter_hour_alignment_enforced
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        resp = api_client.create_booking(
            {"order_ref": "ORD-ALN", "market_id": market["id"],
             "property_address": "7 Crooked St", "equipment_package": "STANDARD",
             "photo_count": 20, "scheduled_start_utc": "2026-08-10T14:07:00Z"},
            make_client_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_SLOT_ALIGNMENT)

    def test_market_suspended_blocks_submit(self, api):
        """PRD §2.4: "Suspending a market blocks new booking submissions for that
        market — a submission into a `SUSPENDED` market fails with
        `ERR_MARKET_SUSPENDED` — while bookings already in flight are entirely
        unaffected."

        Design: Corner/errors/error_market_suspended_blocks_submit
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        booking = create_booking(agent, market["id"], order_ref="ORD-SUSP",
                                 property_address="6 Suspend St",
                                 scheduled_start_utc="2026-08-10T14:00:00Z")
        get_success_data(api_client.patch_market(market["id"], {"status": "SUSPENDED"},
                                                 make_ops_admin_headers()))

        resp = api_client.submit_booking(booking["id"], make_client_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_MARKET_SUSPENDED)
        assert get_booking(booking["id"])["state"] == "DRAFT"


class TestAdminLifecycleGuards:
    def test_photographer_deactivate_with_open_commitments(self, api):
        """PRD §3.3: "An OpsAdmin may deactivate a photographer — moving `status` from
        `ACTIVE` to `INACTIVE` — only while that photographer holds zero bookings in
        `ASSIGNED`, `AUTHORIZATION_PENDING`, or `CONFIRMED`; any open commitment blocks
        the change with `ERR_PHOTOGRAPHER_HAS_OPEN_COMMITMENTS` (HTTP 409)."

        Design: Corner/errors/error_photographer_deactivate_with_open_commitments
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking = create_confirmed_booking(agent, photog, market["id"], order_ref="ORD-DEACT",
                                           property_address="8 Commit Ct",
                                           scheduled_start_utc="2026-08-10T14:00:00Z")
        ops = make_ops_admin_headers()

        resp = api_client.patch_photographer(photog["id"], {"status": "INACTIVE"}, ops)
        validate_error(resp, ApiErrorId.ERR_PHOTOGRAPHER_HAS_OPEN_COMMITMENTS)

        # client cancel (clock is 2026-08-01, well outside the 12h cutoff) releases the
        # commitment; deactivation then succeeds
        get_success_data(api_client.cancel_booking(
            booking["id"], make_client_agent_headers(agent["id"])))
        patched = validate_success(api_client.patch_photographer(
            photog["id"], {"status": "INACTIVE"}, ops))
        assert patched["status"] == "INACTIVE"

    def test_drone_cert_error_masks_capacity_failure_on_assign(self, api):
        """PRD §2.8: "the server evaluates them in a fixed precedence order and reports
        only the first applicable failure; an earlier tier masks every later tier."
        Tier 6 is "6. **Airspace-safety rules** — drone certification,
        authorization attempt caps, lapsed authorization windows, and the unbranded-tier
        rule, typified by `ERR_DRONE_CERT_REQUIRED` (422)." and tier 7 is "7.
        **Resource constraints** — overlap, day-capacity, equipment-match,
        duplicate-drone, reschedule-cap, revision-cap, and readiness-completeness
        checks, typified by `ERR_PHOTOGRAPHER_DOUBLE_BOOKED` (409)."

        An assign where the photographer lacks drone certification AND the new minutes
        would exceed the day cap reports only the safety error.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_assign
        """
        from test_helpers import create_ready_booking, submit_and_prepare
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48,
                               travel_buffer_minutes=0)
        # cap 120; the drone booking's window is 90 minutes (60 shoot + 30 drone)
        p_uncert = create_photographer(market["id"], full_name="Uncert Uma", email="uma@x.com",
                                       equipment_packages=["STANDARD"], drone_certified=False,
                                       max_shoot_minutes_per_day=120)
        agent = create_agent(market["id"])

        b1 = create_ready_booking(agent, market["id"], order_ref="ORD-S1X",
                                  property_address="1 Safety St", photo_count=20,
                                  scheduled_start_utc="2026-08-10T08:00:00Z")
        assign_booking(b1["id"], p_uncert["id"])  # 60 of 120 used

        b2 = create_booking(agent, market["id"], order_ref="ORD-S2X",
                            property_address="2 Safety St", photo_count=20,
                            scheduled_start_utc="2026-08-10T13:00:00Z")
        headers = make_client_agent_headers(agent["id"])
        get_success_data(api_client.create_addon(b2["id"], "DRONE_STILLS", headers))
        submit_and_prepare(b2, agent)
        # assigning would land 60 + 90 = 150 > 120 (capacity) AND the photographer is
        # uncertified (safety): safety is tier 6 and wins
        resp = api_client.assign_booking(b2["id"], p_uncert["id"], make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_DRONE_CERT_REQUIRED)
        assert get_booking(b2["id"])["state"] == "READY"

    def test_duplicate_drone_addon_rejected(self, api):
        """PRD §3.4: "A drone add-on requires that the booking not already carry
        another `ACTIVE` drone add-on; a second one is refused with
        `ERR_DUPLICATE_DRONE_ADDON` (HTTP 409)."

        Design: Corner/errors/error_duplicate_drone_addon
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        booking = create_booking(agent, market["id"], order_ref="ORD-DUP",
                                 property_address="9 Dup Dr",
                                 scheduled_start_utc="2026-08-10T14:00:00Z")
        headers = make_client_agent_headers(agent["id"])
        get_success_data(api_client.create_addon(booking["id"], "DRONE_STILLS", headers))

        resp = api_client.create_addon(booking["id"], "DRONE_VIDEO", headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DRONE_ADDON)
        addons = get_success_data(api_client.list_addons(booking["id"], headers))
        active = [a for a in addons if a["state"] == "ACTIVE"]
        assert len(active) == 1

    def test_checklist_frozen_after_markshot(self, api):
        """PRD §3.2: "Checklist items remain client-editable while the booking is in
        `DRAFT`, `AWAITING_READINESS`, `READY`, `ASSIGNED`, `AUTHORIZATION_PENDING`, or
        `CONFIRMED`, precisely so that readiness can be re-attested after a reschedule
        wipes it. Once the booking reaches `SHOT` or any later state, the items are
        frozen, and any further patch is rejected with `ERR_CHECKLIST_ITEM_IMMUTABLE`
        (HTTP 409)."

        Design: Corner/errors/error_checklist_frozen_after_markshot
        """
        from test_helpers import create_shot_booking, submit_and_prepare
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        headers = make_client_agent_headers(agent["id"])
        booking = create_booking(agent, market["id"], order_ref="ORD-FRZ",
                                 property_address="3 Frozen Ln",
                                 scheduled_start_utc="2026-08-10T14:00:00Z")
        booking = submit_and_prepare(booking, agent)
        assign_booking(booking["id"], photog["id"])
        confirm_booking(booking["id"])
        items = get_success_data(api_client.list_checklist_items(booking["id"], headers,
                                                                 params={"limit": 100}))
        set_clock("2026-08-10T14:30:00Z")
        get_success_data(api_client.mark_shot(booking["id"],
                                              make_photographer_headers(photog["id"])))

        resp = api_client.patch_checklist_item(booking["id"], items[0]["id"], False, headers)
        validate_error(resp, ApiErrorId.ERR_CHECKLIST_ITEM_IMMUTABLE)
        items_after = get_success_data(api_client.list_checklist_items(
            booking["id"], headers, params={"limit": 100}))
        item0 = next(i for i in items_after if i["id"] == items[0]["id"])
        assert item0["checked"] is True  # frozen value preserved
