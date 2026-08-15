"""Role-based access control: role gates, entity-backed ownership scope, and
segregation of duties."""
from test_helpers import (
    TEST_USERS,
    advance_clock,
    approve_estimate,
    create_estimate,
    create_fleet,
    create_fleet_account_payload,
    create_invoice_for_call,
    create_standard_rate_card,
    create_technician,
    create_vehicle,
    diagnose_call,
    drive_call_on_site,
    issue_invoice,
    make_billing_clerk_headers,
    make_fleet_manager_headers,
    make_ops_admin_headers,
    open_triaged_call,
    setup_s1_completed_job,
    submit_estimate,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


class TestRoleGates:
    def test_technician_cannot_create_fleet_account(self, api):
        """PRD: "An attempt to perform an action outside the roles declared
        for that endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`." — fleet
        master data is OpsAdmin-only per the endpoint table.

        Design: Corner/rbac/technician_cannot_create_fleet_account
        """
        tech, tech_headers = create_technician()
        resp = api.create_fleet_account(
            create_fleet_account_payload(account_number="ACCT-7001"),
            tech_headers)
        assert resp.status_code == 403
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_billing_clerk_cannot_void_invoice_role_level(self, api):
        """PRD: "invoices are drafted and issued by a `BillingClerk` but
        voided or written off only by an `OpsAdmin`" — the clerk is refused at
        the role gate regardless of which user id they present.

        Design: Corner/rbac/billing_clerk_cannot_void_invoice_role_level
        """
        ctx = setup_s1_completed_job()
        invoice = create_invoice_for_call(ctx["call"]["id"])
        issue_invoice(invoice["id"],
                      headers=make_billing_clerk_headers("bc-1"))
        resp = api.void_invoice(invoice["id"], {"reason": "billing error"},
                                make_billing_clerk_headers("bc-9"))
        assert resp.status_code == 403
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOwnershipScope:
    def test_fleet_manager_cannot_approve_other_fleets_estimate(self, api):
        """PRD: "When `X-User-Role` is `FleetManager`, `X-User-ID` is the
        `id` of the acting `FleetAccount`; ownership checks on fleet-scoped
        resources (estimates of that fleet's calls, the fleet's own account
        record, the fleet's invoices) compare the resource's fleet reference
        to `X-User-ID`."

        Design: Corner/rbac/fleet_manager_cannot_approve_other_fleets_estimate
        """
        create_standard_rate_card()
        fleet_a = create_fleet(
            per_call_authorization_limit_cents=200000,
            monthly_spend_cap_cents=900000, account_number="ACCT-A")
        fleet_b = create_fleet(
            per_call_authorization_limit_cents=200000,
            monthly_spend_cap_cents=900000, account_number="ACCT-B")
        veh = create_vehicle(fleet_account_id=fleet_a["id"],
                             odometer_miles=120000)
        tech, tech_headers = create_technician()
        advance_clock("2026-08-05T09:00:00Z")
        call = open_triaged_call(veh["id"], severity="DEFERRED",
                                 received_at=None)
        call, _d = drive_call_on_site(
            call, tech["id"], tech_headers, "2026-08-05T09:00:00Z",
            "2026-08-05T13:00:00Z", arrive_at="2026-08-05T09:45:00Z",
            actual_travel_miles=20)
        diagnose_call(call["id"], tech_headers,
                      diagnosis_summary="glow plugs")
        estimate = create_estimate(call["id"], labor_hours_est=1.0,
                                   travel_miles_est=20,
                                   parts_estimate_cents=30000,
                                   headers=tech_headers)
        submit_estimate(estimate["id"], headers=tech_headers)

        resp = api.approve_estimate(
            estimate["id"], {}, make_fleet_manager_headers(fleet_b["id"]))
        assert resp.status_code == 403
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

        approved = approve_estimate(
            estimate["id"], make_fleet_manager_headers(fleet_a["id"]))
        assert approved["status"] == "APPROVED", (
            "46675 <= 200000: the fleet's own manager approves")


class TestSegregationOfDuties:
    def test_segregation_of_duties_issuer_cannot_void_own_invoice(self, api):
        """PRD: "an operator who issued an invoice may never void that same
        invoice — such an attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_issuer_cannot_void_own_invoice
        """
        ctx = setup_s1_completed_job()
        invoice = create_invoice_for_call(ctx["call"]["id"])
        issue_invoice(invoice["id"],
                      headers=make_ops_admin_headers("ops-1"))

        resp = api.void_invoice(invoice["id"], {"reason": "self void attempt"},
                                make_ops_admin_headers("ops-1"))
        assert resp.status_code == 403
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        voided = validate_success(api.void_invoice(
            invoice["id"], {"reason": "independent void"},
            make_ops_admin_headers("ops-2")))
        assert voided["issue_status"] == "VOID"
