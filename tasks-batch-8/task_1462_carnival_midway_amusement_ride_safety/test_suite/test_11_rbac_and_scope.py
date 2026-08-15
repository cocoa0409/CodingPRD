"""Role admission and entity-backed scoping: exclusive operations reject the
wrong role, and staff identity is scoped to its own fair (PRD sections 2.1,
3.1, 3.5).

Covers design instances:
  Corner/rbac/ride_operator_cannot_create_ticket_products_returns_403
  Corner/rbac/program_admin_cannot_register_rides_returns_403
  Corner/validations/cross_fair_staff_scope_forbidden
"""
from test_helpers import (
    ApiErrorId,
    create_ride_payload,
    make_admin_headers,
    make_manager_headers,
    make_operator_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import fixtures as fx


class TestRoleExclusiveDenial:
    def test_ride_operator_cannot_create_ticket_products(self, api):
        """PRD section 2.1: "Each endpoint admits a declared set of roles
        (§4); a caller whose role is not admitted is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." PRD section 3.5: "Sellable inventory is
        configured as **TicketProducts** by the `FairManager`".

        The caller is a valid, active OPERATOR of the same fair — the role
        alone excludes them from product configuration.

        Design: Corner/rbac/ride_operator_cannot_create_ticket_products_returns_403
        """
        ctx = fx.setup_fair_with_staff("RB1")
        sup = ctx["sup"]
        op = fx.create_staff_via_manager(sup, "Op RB1", ["OPERATOR"])
        resp = api.create_product(
            {"fair_id": sup["fair_id"], "name": "Credits", "kind": "CREDIT_BUNDLE",
             "base_price_cents": 100},
            make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_program_admin_cannot_register_rides(self, api):
        """PRD section 3.1: "With a fair on file, a `FairManager` builds the
        ride inventory." PRD section 2.1: "a caller whose role is not admitted
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        The state administrator owns fairs and inspectors, not show-side ride
        inventory.

        Design: Corner/rbac/program_admin_cannot_register_rides_returns_403
        """
        fx.set_clock(fx.SETUP_DAY_ISO)
        fair = fx.create_fair(name="Midway RB4")
        resp = api.create_ride(create_ride_payload(fair["id"],
                                                   serial_number="SN-RB4-1"),
                               make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestCrossFairStaffScope:
    def test_supervisor_of_other_fair_cannot_request_permit(self, api):
        """PRD section 2.1: "its `fair_id` must match the fair of the
        endpoint's primary resource (the resource addressed by the path; for
        collection creates, the fair named by the body's `fair_id` or implied
        by a referenced ride or product). Any failure of this scoping — wrong
        function, a `RELEASED` staff member, or a cross-fair call — is
        `ERR_FORBIDDEN`."

        Design: Corner/validations/cross_fair_staff_scope_forbidden
        """
        fx.set_clock(fx.SETUP_DAY_ISO)
        fair_a = fx.create_fair(name="Fair A")
        fair_b = fx.create_fair(name="Fair B", operator_company_name="OtherCo",
                                location="Lot B")
        sup_a = fx.create_supervisor(fair_a["id"], full_name="Sup A")
        resp = api.request_permit(fair_b["id"], {}, make_manager_headers(sup_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        fair_b_after = fx.get_success_data(api.get_fair(fair_b["id"],
                                                        make_admin_headers()))
        assert fair_b_after["status"] == "SETUP"
        data, meta = validate_paginated(api.list_permits(
            make_admin_headers(), params={"fair_id": fair_b["id"]}))
        assert meta["total_count"] == 0 and data == [], (
            "no permit may be created by a cross-fair caller")
