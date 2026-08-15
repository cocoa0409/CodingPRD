"""Validation-cascade priority pairs and optimistic concurrency (PRD §2.6, §2.7)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_stop_to_route, confirm_order, create_confirmed_order,
    create_customer,
    create_fleet_contract, create_route, create_site, create_technician, create_van,
    create_vehicles, create_wash_order, generate_invoice, get_order, get_route,
    order_event, set_clock, setup_completed_order, setup_customer_site_vehicles,
    validate_error, validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]

CONTRACT_RATES = {
    "sedan_rate_cents": 3000,
    "suv_pickup_rate_cents": 4000,
    "van_boxtruck_rate_cents": 6000,
    "heavy_fleet_rate_cents": 10000,
}


class TestConfirmCancelledOrderAtNoncontainedSite:
    def _noncontained_site(self, customer_id):
        return create_site(
            customer_id, name="BARE", containment_type="NONE",
            water_reclaim_required=True, max_discharge_gal=100,
        )

    def test_state_error_beats_containment_error(self, api):
        """PRD §2.6: "Requests are validated in a fixed cascade, and the cascade's
        ordering is part of the contract: a request that would fail several checks is
        rejected with the error from the earliest check."
        PRD §2.6: "State eligibility — the target entity is in a valid from-state for
        the requested transition, else `ERR_INVALID_STATE`"

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_order_at_noncontained_site_state_beats_safety
        """
        customer = create_customer()
        site = self._noncontained_site(customer["id"])
        vehicle_ids = create_vehicles(customer["id"], site["id"], 1, "SEDAN")
        order = create_wash_order(customer["id"], site["id"], vehicle_ids)
        order_event(order["id"], "CANCEL", DISPATCHER,
                    cancel_reason="CUSTOMER_REQUEST")
        resp = api.wash_order_event(order["id"], {"event_type": "CONFIRM"}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(order["id"])["status"] == "CANCELLED"

    def test_containment_error_fires_in_isolation(self, api):
        """PRD §3.3: "containment adequacy first — when the site requires reclamation
        (`water_reclaim_required` true) yet its `containment_type` is `NONE`,
        confirmation is rejected with `ERR_CONTAINMENT_REQUIRED`"

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_order_at_noncontained_site_state_beats_safety
        """
        customer = create_customer()
        site = self._noncontained_site(customer["id"])
        vehicle_ids = create_vehicles(customer["id"], site["id"], 1, "SEDAN")
        order = create_wash_order(customer["id"], site["id"], vehicle_ids)
        resp = api.wash_order_event(order["id"], {"event_type": "CONFIRM"}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_CONTAINMENT_REQUIRED)
        assert get_order(order["id"])["status"] == "DRAFT"


class TestInvoiceGenerateSuspendedContract:
    def _fleet_with_completed_order(self):
        ctx = setup_completed_order(
            customer_type="FLEET",
            contract_overrides={"monthly_minimum_cents": 50000, **CONTRACT_RATES},
        )
        return ctx

    def test_referential_guard_beats_duplicate_invoice_guard(self, api):
        """PRD §2.6: "Requests are validated in a fixed cascade, and the cascade's
        ordering is part of the contract: a request that would fail several checks is
        rejected with the error from the earliest check."
        PRD §2.6: "Referential guards, in order: customer active
        (`ERR_CUSTOMER_SUSPENDED`), site active (`ERR_SITE_SUSPENDED`), subscription
        active (`ERR_SUBSCRIPTION_NOT_ACTIVE`), contract active
        (`ERR_CONTRACT_NOT_ACTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/invoice_generate_suspended_contract_referential_beats_fiscal
        """
        ctx = self._fleet_with_completed_order()
        invoice = generate_invoice(ctx["contract"]["id"], "2026-08", "FINAL")
        assert invoice["status"] == "DRAFT"
        validate_success(api.fleet_contract_event(
            ctx["contract"]["id"], {"event_type": "SUSPEND"}, ADMIN,
        ))
        resp = api.generate_invoice(
            {"fleet_contract_id": ctx["contract"]["id"], "period_month": "2026-08",
             "variant": "FINAL"},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
        existing = validate_success(api.get_invoice(invoice["id"], DISPATCHER))
        assert existing["status"] == "DRAFT"

    def test_suspended_contract_alone_rejected(self, api):
        """PRD §3.9: "An administrator or dispatcher generates an invoice by naming
        the `fleet_contract_id`, the `period_month` in YYYY-MM form, and a `variant`
        of `PROJECTION` or `FINAL`; the contract must be `ACTIVE`
        (`ERR_CONTRACT_NOT_ACTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/invoice_generate_suspended_contract_referential_beats_fiscal
        """
        customer = create_customer(customer_type="FLEET")
        contract = create_fleet_contract(customer["id"], monthly_minimum_cents=50000,
                                         **CONTRACT_RATES)
        validate_success(api.fleet_contract_event(
            contract["id"], {"event_type": "SUSPEND"}, ADMIN,
        ))
        resp = api.generate_invoice(
            {"fleet_contract_id": contract["id"], "period_month": "2026-08",
             "variant": "FINAL"},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)


class TestStopAddContainmentBeatsTechnicianBuffer:
    def _reclaim_site(self, customer_id):
        return create_site(
            customer_id, name="RECLAIM", lot_size_sqft=60000,
            containment_type="BERMS", water_reclaim_required=True,
            max_discharge_gal=1000,
        )

    def test_containment_error_wins_when_both_violated(self, api):
        """PRD §2.6: "Safety rules, in order: containment adequacy
        (`ERR_CONTAINMENT_REQUIRED`), then the discharge cap
        (`ERR_DISCHARGE_CAP_EXCEEDED`), then reclaim certification
        (`ERR_CERTIFICATION_REQUIRED`)."
        PRD §2.6: "Requests are validated in a fixed cascade, and the cascade's
        ordering is part of the contract: a request that would fail several checks is
        rejected with the error from the earliest check."

        Design: Difficulty/priority_pair_validation_conflict/stop_add_containment_safety_beats_technician_buffer
        """
        customer = create_customer()
        plain = create_site(customer["id"], name="PLAIN")
        reclaim = self._reclaim_site(customer["id"])
        sedans = create_vehicles(customer["id"], plain["id"], 3, "SEDAN")
        tech = create_technician()
        van_basic = create_van(name="VAN-B1", reclaim_system="BASIC", load_gallons=96)
        van_none = create_van(name="VAN-B3", reclaim_system="NONE", load_gallons=100)
        o0 = create_confirmed_order(
            customer["id"], plain["id"], sedans,
            scheduled_window_start="2026-08-05T13:00:00Z",
            scheduled_window_end="2026-08-05T14:00:00Z",
        )
        ox = create_confirmed_order(
            customer["id"], reclaim["id"], [sedans[0]],
            scheduled_window_start="2026-08-05T15:00:00Z",
            scheduled_window_end="2026-08-05T16:00:00Z",
        )
        r0 = create_route("2026-08-05", van_basic["id"], tech["id"])
        add_stop_to_route(r0["id"], o0["id"])  # plans 08:00-09:15
        r3 = create_route("2026-08-05", van_none["id"], tech["id"],
                          shift_start_at="2026-08-05T09:30:00Z")
        route_now = get_route(r3["id"])
        resp = api.add_route_stop(
            r3["id"],
            {"wash_order_id": ox["id"],
             "expected_route_version": route_now["version"]},
            DISPATCHER,
        )
        # recovery 0.00 < 0.60 at a reclaim-required site AND a 15-minute buffer gap;
        # the safety rule wins
        validate_error(resp, ApiErrorId.ERR_CONTAINMENT_REQUIRED)
        assert get_order(ox["id"])["status"] == "SCHEDULED"
        assert get_route(r3["id"])["assigned_vehicle_count"] == 0

    def test_containment_error_fires_without_buffer_violation(self, api):
        """PRD §3.4: "Before any reservation lands, the discharge check runs when the
        site's `water_reclaim_required` is true: equipment adequacy is checked first,
        so a van whose recovery fraction is below sixty percent is rejected with
        `ERR_CONTAINMENT_REQUIRED`"

        Design: Difficulty/priority_pair_validation_conflict/stop_add_containment_safety_beats_technician_buffer
        """
        customer = create_customer()
        reclaim = self._reclaim_site(customer["id"])
        sedans = create_vehicles(customer["id"], reclaim["id"], 1, "SEDAN")
        ox = create_confirmed_order(customer["id"], reclaim["id"], sedans)
        tech = create_technician()  # no other route this date: no buffer violation
        van_none = create_van(name="VAN-SOLO", reclaim_system="NONE", load_gallons=100)
        route = create_route("2026-08-05", van_none["id"], tech["id"])
        route_now = get_route(route["id"])
        resp = api.add_route_stop(
            route["id"],
            {"wash_order_id": ox["id"],
             "expected_route_version": route_now["version"]},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_CONTAINMENT_REQUIRED)


class TestOccStaleStopAddRejected:
    def test_stale_version_rejected_replay_with_current_succeeds(self, api):
        """PRD §2.7: "Appending a stop to a route requires the request to carry
        `expected_route_version`, the client's last observed `version` of that Route.
        If the route's version has advanced since the client last read it, the append
        is rejected with `ERR_STALE_VERSION` (HTTP 412)"
        PRD §2.4: "`version` (integer): starts at 1 when the resource is created and
        increments by one on every mutation."

        Design: Corner/cross_cutting_layers/occ_stale_stop_add_rejected
        """
        ctx = setup_customer_site_vehicles(num_vehicles=2, vehicle_class="SEDAN")
        oa = create_confirmed_order(
            ctx["customer"]["id"], ctx["site"]["id"], [ctx["vehicle_ids"][0]],
            scheduled_window_start="2026-08-05T13:00:00Z",
            scheduled_window_end="2026-08-05T14:00:00Z",
        )
        ob = create_confirmed_order(
            ctx["customer"]["id"], ctx["site"]["id"], [ctx["vehicle_ids"][1]],
            scheduled_window_start="2026-08-05T14:00:00Z",
            scheduled_window_end="2026-08-05T15:00:00Z",
        )
        van = create_van(load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-05", van["id"], tech["id"])
        stale_version = route["version"]
        add_stop_to_route(route["id"], oa["id"])
        resp = api.add_route_stop(
            route["id"],
            {"wash_order_id": ob["id"], "expected_route_version": stale_version},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        current = get_route(route["id"])
        stop_b = validate_success(api.add_route_stop(
            route["id"],
            {"wash_order_id": ob["id"], "expected_route_version": current["version"]},
            DISPATCHER,
        ), expected_status=201)
        assert stop_b["sequence"] == 2
        assert get_route(route["id"])["version"] == current["version"] + 1


class TestOccStaleContractAmendRejected:
    def test_stale_amend_rejected_current_version_applies(self, api):
        """PRD §2.7: "Amending a fleet contract requires
        `expected_fleet_contract_version`, the client's last observed `version` of
        that FleetContract. A mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412), since the new rate card supersedes whatever terms the client
        read."

        Design: Corner/cross_cutting_layers/occ_stale_contract_amend_rejected
        """
        customer = create_customer(customer_type="FLEET")
        contract = create_fleet_contract(customer["id"], activate=False,
                                         **CONTRACT_RATES)
        stale_version = contract["version"]
        validate_success(api.fleet_contract_event(
            contract["id"], {"event_type": "ACTIVATE"}, ADMIN,
        ))
        resp = api.amend_fleet_contract(
            contract["id"],
            {"expected_fleet_contract_version": stale_version,
             "monthly_minimum_cents": 250000},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        current = validate_success(api.get_fleet_contract(contract["id"], ADMIN))
        amended = validate_success(api.amend_fleet_contract(
            contract["id"],
            {"expected_fleet_contract_version": current["version"],
             "monthly_minimum_cents": 250000},
            ADMIN,
        ))
        assert amended["monthly_minimum_cents"] == 250000
        assert amended["version"] == current["version"] + 1


class TestWindowInvertedRejected:
    def test_window_end_before_start_rejected(self, api):
        """PRD §2.6: "Body shape — required fields are present, and types, enum
        members, and ranges are valid (dates parse, a window's end is strictly after
        its start, gallons are positive, audit scores lie between 0 and 20
        inclusive), else `ERR_VALIDATION`."

        Design: Corner/validations/window_inverted_rejected
        """
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        resp = api.create_wash_order(
            {
                "customer_id": ctx["customer"]["id"],
                "site_id": ctx["site"]["id"],
                "vehicle_ids": ctx["vehicle_ids"],
                "scheduled_window_start": "2026-08-06T14:00:00Z",
                "scheduled_window_end": "2026-08-06T13:00:00Z",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestMissingRoleHeaderUnauthenticated:
    def test_request_without_role_header_rejected(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or does not name
        one of these six roles is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_role_header_unauthenticated
        """
        resp = api.create_customer(
            {"name": "NoRole", "email": "norole@example.com"},
            {"X-User-ID": "norole-1"},  # no X-User-Role header sent
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
