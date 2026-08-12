"""Role-based access control: role denial, ownership scoping, Manager override,
and authentication precedence."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_equipment_item_payload,
    declare_capacity,
    make_customer,
    make_customer_headers,
    make_damage_assessment,
    make_reservation,
    make_tune_ticket,
    set_clock,
    setup_returned_reservation,
    validate_error,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]
TECH = TEST_USERS["technician_headers"]
MGR = TEST_USERS["manager_headers"]


class TestAuthentication:
    def test_missing_headers_rejected_before_existence_check(self, api):
        """PRD User and Role-Based Access Control: "A request missing either header, or
        presenting a role outside this declared set, is rejected with
        `ERR_UNAUTHENTICATED`."
        PRD Request Validation Precedence: "Authentication comes first: missing or
        malformed identity headers produce `ERR_UNAUTHENTICATED` before anything else
        is examined."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        # Even though the id does not exist, the 401 fires before any 404 check.
        resp = api.get_customer(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenial:
    def test_customer_cannot_create_equipment(self, api):
        """PRD Building and Maintaining the Fleet: "A `Manager` adds each unit to the
        fleet" and PRD User and Role-Based Access Control: "A request whose role is not
        in the endpoint's authorized list is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/customer_cannot_create_equipment
        """
        customer = make_customer()
        resp = api.create_equipment_item(
            create_equipment_item_payload(), make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_technician_cannot_resolve_dispute(self, api):
        """PRD Damage Assessments: "Disputes are resolved by a `Manager` supplying a
        `resolution`" and PRD User and Role-Based Access Control: "A request whose role
        is not in the endpoint's authorized list is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/technician_cannot_resolve_damage
        """
        ctx = setup_returned_reservation(rate=3000, price=20000,
                                         deposit_authorized_cents=5000)
        assessment = make_damage_assessment(ctx["reservation"], ctx["units"][0],
                                            severity="COSMETIC")
        validate_success(api.invoice_damage_assessment(assessment["id"], FD))
        disputed = validate_success(api.dispute_damage_assessment(
            assessment["id"], make_customer_headers(ctx["customer"]["id"])))
        assert disputed["status"] == "DISPUTED"

        resp = api.resolve_damage_assessment(assessment["id"],
                                             {"resolution": "WAIVED"}, TECH)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = validate_success(api.get_damage_assessment(assessment["id"], FD))
        assert after["status"] == "DISPUTED"


class TestOwnershipScoping:
    def test_customer_cannot_read_others_reservation(self, api):
        """PRD User and Role-Based Access Control: "A customer acting on a resource
        owned by a different customer is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/rbac/customer_cannot_read_others_reservation
        """
        owner = make_customer(full_name="Own Er", email="oa@example.com")
        peer = make_customer(full_name="Pee Per", email="pb@example.com",
                             date_of_birth="1992-05-20")
        reservation = make_reservation(owner)

        resp = api.get_reservation(reservation["id"],
                                   make_customer_headers(peer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


class TestManagerOverride:
    def test_manager_performs_technician_quote(self, api):
        """PRD User and Role-Based Access Control: "`Manager` is a hierarchical
        override role: a superset of everything `FrontDesk` and `Technician` can do"

        Design: Corner/rbac/manager_override_performs_technician_quote
        """
        set_clock("2026-12-01T09:00:00Z")
        declare_capacity("2026-12-01", base_labor_minutes=480, rush_reserved_minutes=120)
        customer = make_customer()
        ticket = make_tune_ticket(customer, services=("WAX",))

        resp = api.quote_tune_ticket(ticket["id"], {}, MGR)
        quoted = validate_success(resp)
        assert quoted["status"] == "QUOTED"
        # WAX base price 2500, no parts, no rush, no junior lease.
        assert quoted["quoted_price_cents"] == 2500
