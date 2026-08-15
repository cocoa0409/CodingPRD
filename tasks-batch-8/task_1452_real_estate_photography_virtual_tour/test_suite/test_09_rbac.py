"""RBAC and entity-backed ownership enforcement (PRD §2.1, §2.8, §4)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    make_client_agent_headers, make_photographer_headers, make_coordinator_headers,
    make_ops_admin_headers,
    create_market, create_photographer, create_agent, create_booking, set_clock,
    create_ready_booking, create_delivered_booking, get_booking,
    create_booking_payload,
)


class TestRoleDenial:
    def test_clientagent_cannot_assign_photographer(self, api):
        """PRD §4: `POST /shoot-bookings/{id}/assign` lists only the Coordinator role.
        PRD §2.1: "A request whose role is simply not permitted on the target endpoint
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/clientagent_cannot_assign_photographer
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking = create_ready_booking(agent, market["id"], order_ref="ORD-R1",
                                       property_address="7 Role Rd",
                                       scheduled_start_utc="2026-08-10T14:00:00Z")

        resp = api_client.assign_booking(booking["id"], photog["id"],
                                         make_client_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_photographer_cannot_accept_delivery(self, api):
        """PRD §4: `POST /shoot-bookings/{id}/accept` lists only the ClientAgent role.
        PRD §2.1: "A request whose role is simply not permitted on the target endpoint
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/photographer_cannot_accept_delivery
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking, _bundle = create_delivered_booking(
            agent, photog, market["id"], "2026-08-05T14:30:00Z",
            order_ref="ORD-R2", property_address="9 Role Rd", photo_count=20,
            scheduled_start_utc="2026-08-05T14:00:00Z")

        resp = api_client.accept_booking(booking["id"],
                                         make_photographer_headers(photog["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_opsadmin_cannot_create_booking(self, api):
        """PRD §4: `POST /shoot-bookings` lists only the ClientAgent role.
        PRD §2.1: "A request whose role is simply not permitted on the target endpoint
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/opsadmin_cannot_create_booking
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        resp = api_client.create_booking(
            create_booking_payload(market["id"], order_ref="ORD-ADM",
                                   property_address="1 Admin Way",
                                   scheduled_start_utc="2026-08-10T14:00:00Z"),
            make_ops_admin_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOwnershipEnforcement:
    def test_agent_ownership_forbidden_on_other_agents_booking(self, api):
        """PRD §2.1: "When `X-User-Role` is `ClientAgent`, `X-User-ID` is the `id` of
        the acting `ClientAgent`; ownership checks on any resource that references a
        ClientAgent — above all a booking's `client_agent_id` — compare that foreign-key
        field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/agent_ownership_forbidden_on_other_agents_booking
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent_a = create_agent(market["id"], full_name="Agent Ann", email="ann@x.com")
        agent_b = create_agent(market["id"], full_name="Agent Bob", email="bob@x.com")
        booking = create_booking(agent_a, market["id"], order_ref="ORD-OWN",
                                 property_address="4 Own Ave",
                                 scheduled_start_utc="2026-08-10T14:00:00Z")

        # B's role is permitted for submit, but B does not own the booking
        resp = api_client.submit_booking(booking["id"], make_client_agent_headers(agent_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_booking(booking["id"])["state"] == "DRAFT"

    def test_photographer_markshot_requires_assignment_identity(self, api):
        """PRD §3.6: "Marking requires the booking to be `CONFIRMED` ... requires the
        caller's `X-User-ID` to equal the booking's `assigned_photographer_id`
        (otherwise `ERR_FORBIDDEN`) ..."
        PRD §2.1: "assignment-scoped checks compare a booking's
        `assigned_photographer_id` to `X-User-ID`, again raising `ERR_FORBIDDEN` on
        mismatch."

        Design: Corner/rbac/photographer_markshot_requires_assignment_identity
        """
        from test_helpers import create_confirmed_booking
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        p1 = create_photographer(market["id"], full_name="P One", email="p1@x.com",
                                 equipment_packages=["STANDARD"])
        p2 = create_photographer(market["id"], full_name="P Two", email="p2@x.com",
                                 equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking = create_confirmed_booking(agent, p1, market["id"], order_ref="ORD-PID",
                                           property_address="6 Assignee Ave",
                                           scheduled_start_utc="2026-08-10T14:00:00Z")
        set_clock("2026-08-10T14:30:00Z")

        # P2 is a Photographer but not the assignee
        resp = api_client.mark_shot(booking["id"], make_photographer_headers(p2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_booking(booking["id"])["state"] == "CONFIRMED"
