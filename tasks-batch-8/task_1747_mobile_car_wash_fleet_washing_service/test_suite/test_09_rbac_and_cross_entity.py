"""RBAC and cross-entity guards: role denials, ownership, suspended customer/site,
paused subscription dependencies (PRD §2.1, §3.1, §3.3)."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, create_customer, create_site,
    create_subscription, create_technician, create_van, create_vehicles,
    create_wash_order, get_order, make_customer_headers, make_technician_headers,
    pause_subscription, resume_subscription, setup_customer_site_vehicles,
    validate_error, validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestConfirmBlockedBySiteSuspension:
    def test_confirm_rejected_while_site_suspended(self, api):
        """PRD §3.3: "the customer must be `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`), the
        site must be `ACTIVE` (`ERR_SITE_SUSPENDED`), a linked `subscription_id` must
        point to an `ACTIVE` subscription (`ERR_SUBSCRIPTION_NOT_ACTIVE`), and a
        `FLEET` customer must have an `ACTIVE` FleetContract
        (`ERR_CONTRACT_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_site_suspension
        """
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        order = create_wash_order(ctx["customer"]["id"], ctx["site"]["id"],
                                  ctx["vehicle_ids"])
        validate_success(api.site_event(
            ctx["site"]["id"], {"event_type": "SUSPEND"}, COMPLIANCE,
        ))
        resp = api.wash_order_event(order["id"], {"event_type": "CONFIRM"}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_SITE_SUSPENDED)
        assert get_order(order["id"])["status"] == "DRAFT"

    def test_confirm_succeeds_after_reinstate(self, api):
        """PRD §3.7: "Resolution moves `CONFIRMED` → `RESOLVED`; when no other
        incident at that site remains `CONFIRMED`, the system reinstates the site to
        `ACTIVE` and clears `suspension_reason`."
        PRD §3.3: "Confirmation moves an order `DRAFT` → `SCHEDULED` and is performed
        by the owning customer or a dispatcher."

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_site_suspension
        """
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        order = create_wash_order(ctx["customer"]["id"], ctx["site"]["id"],
                                  ctx["vehicle_ids"])
        validate_success(api.site_event(
            ctx["site"]["id"], {"event_type": "SUSPEND"}, COMPLIANCE,
        ))
        reinstated = validate_success(api.site_event(
            ctx["site"]["id"], {"event_type": "REINSTATE"}, COMPLIANCE,
        ))
        assert reinstated["status"] == "ACTIVE"
        confirmed = validate_success(api.wash_order_event(
            order["id"], {"event_type": "CONFIRM"}, DISPATCHER,
        ))
        assert confirmed["status"] == "SCHEDULED"


class TestConfirmBlockedByPausedSubscription:
    def _scenario(self):
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        sub = create_subscription(
            ctx["customer"]["id"], ctx["vehicle_ids"][0], cadence="WEEKLY",
            next_service_date="2026-08-10",
        )
        order = create_wash_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
            scheduled_window_start="2026-08-10T13:00:00Z",
            scheduled_window_end="2026-08-10T14:00:00Z",
            subscription_id=sub["id"],
        )
        ctx["subscription"] = sub
        ctx["order"] = order
        return ctx

    def test_confirm_rejected_while_subscription_paused(self, api):
        """PRD §3.3: "a linked `subscription_id` must point to an `ACTIVE`
        subscription (`ERR_SUBSCRIPTION_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_paused_subscription
        """
        ctx = self._scenario()
        pause_subscription(ctx["subscription"]["id"], 7, ctx["customer"]["id"])
        resp = api.wash_order_event(ctx["order"]["id"], {"event_type": "CONFIRM"},
                                    DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE)
        assert get_order(ctx["order"]["id"])["status"] == "DRAFT"

    def test_confirm_succeeds_after_resume(self, api):
        """PRD §3.3: "Confirmation moves an order `DRAFT` → `SCHEDULED` and is
        performed by the owning customer or a dispatcher."
        PRD §3.2: "Resuming closes the open record: `ended_at` becomes the clock date,
        the record's `days` becomes the elapsed day count, and `next_service_date`
        shifts forward by exactly that closed record's days"

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_paused_subscription
        """
        ctx = self._scenario()
        pause_subscription(ctx["subscription"]["id"], 7, ctx["customer"]["id"])
        resume_subscription(ctx["subscription"]["id"], ctx["customer"]["id"])
        confirmed = validate_success(api.wash_order_event(
            ctx["order"]["id"], {"event_type": "CONFIRM"}, DISPATCHER,
        ))
        assert confirmed["status"] == "SCHEDULED"


class TestConfirmWithSuspendedCustomer:
    def test_confirm_blocked_after_customer_suspended(self, api):
        """PRD §3.1: "Suspension is deliberately shallow — it does not cascade to
        existing orders or subscriptions, but it blocks the creation of new wash
        orders and subscriptions, and the confirmation of a booked order, with
        `ERR_CUSTOMER_SUSPENDED`."

        Design: Corner/validations/confirm_with_suspended_customer
        """
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        order = create_wash_order(ctx["customer"]["id"], ctx["site"]["id"],
                                  ctx["vehicle_ids"])
        validate_success(api.customer_event(
            ctx["customer"]["id"], {"event_type": "SUSPEND"}, ADMIN,
        ))
        resp = api.wash_order_event(order["id"], {"event_type": "CONFIRM"}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED)
        assert get_order(order["id"])["status"] == "DRAFT"


class TestCustomerCannotCreateRoute:
    def test_customer_role_denied_on_route_creation(self, api):
        """PRD §2.1: "When the role is valid but not permitted for the endpoint — or
        an ownership check fails — the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/customer_cannot_create_route
        """
        van = create_van(name="VAN-B2")
        tech = create_technician()
        resp = api.create_route(
            {"route_date": "2026-08-05", "van_id": van["id"],
             "lead_technician_id": tech["id"]},
            make_customer_headers("00000000-0000-4000-8000-000000000001"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestTechnicianCannotFileDamageClaim:
    def test_technician_role_denied_on_claim_filing(self, api):
        """PRD §2.1: "When the role is valid but not permitted for the endpoint — or
        an ownership check fails — the request is rejected with `ERR_FORBIDDEN`."
        PRD §2.6: "Authorization and ownership — the role is permitted for the
        endpoint and the ownership checks pass (a Customer acts only on its own
        resources; a Technician acts only as route lead or report filer), else
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/technician_cannot_file_damage_claim
        """
        tech = create_technician()
        resp = api.create_damage_claim(
            {"wash_order_id": NON_EXISTENT_UUID, "area": "GLASS",
             "claimed_amount_cents": 1000, "description": "x"},
            make_technician_headers(tech["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestCustomerCannotTouchOtherCustomersOrder:
    def test_other_customers_order_confirm_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the
        acting Customer; ownership checks on any resource that references a Customer —
        a site, a vehicle, a subscription, a wash order, a damage claim, or the
        invoice of the customer's own fleet contract — compare the resource's customer
        foreign key to `X-User-ID`."

        Design: Corner/rbac/customer_cannot_touch_other_customers_order
        """
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        other = create_customer(name="BB")
        order = create_wash_order(ctx["customer"]["id"], ctx["site"]["id"],
                                  ctx["vehicle_ids"])
        resp = api.wash_order_event(
            order["id"], {"event_type": "CONFIRM"},
            make_customer_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_order(order["id"])["status"] == "DRAFT"


class TestAuditorCannotReportIncident:
    def test_quality_auditor_denied_on_incident_reporting(self, api):
        """PRD §2.1: "When the role is valid but not permitted for the endpoint — or
        an ownership check fails — the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/auditor_cannot_report_incident
        """
        customer = create_customer()
        site = create_site(customer["id"], name="B5S")
        resp = api.create_compliance_incident(
            {"site_id": site["id"], "incident_type": "SPILL",
             "notes": "auditor attempt"},
            TEST_USERS["auditor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
