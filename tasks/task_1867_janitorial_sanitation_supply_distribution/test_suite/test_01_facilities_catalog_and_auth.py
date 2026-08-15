"""Facility onboarding, product catalog guards, authentication and RBAC."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_facility,
    assert_product,
    award_bid,
    bid_to_under_review,
    create_contract_bid,
    create_dispenser,
    create_facility,
    create_facility_payload,
    create_order_draft,
    create_product,
    create_product_payload,
    create_technician,
    make_facility_manager_headers,
    make_field_technician_headers,
    order_line,
    place_order,
    setup_facility_with_product,
    setup_placed_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["distributor_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
MISSING_UUID = "00000000-0000-4000-8000-000000000000"


class TestFacilityOnboarding:
    def test_create_facility_applies_system_defaults(self, api):
        """PRD: "New facilities are born `ACTIVE` with `committed_cents` and
        `outstanding_cents` at zero and `closed_loop_enrolled` false."

        Design: Corner/entities/create_facility_applies_system_defaults
        """
        facility = create_facility(
            name="Fac Q", credit_limit_cents=500000, service_zone="Z9")
        assert_facility(facility)
        assert facility["status"] == "ACTIVE", "New facilities are born ACTIVE"
        assert facility["committed_cents"] == 0
        assert facility["outstanding_cents"] == 0
        assert facility["closed_loop_enrolled"] is False

        fetched = validate_success(api.get_facility(facility["id"], ADMIN))
        assert fetched["status"] == "ACTIVE"
        assert fetched["committed_cents"] == 0
        assert fetched["outstanding_cents"] == 0
        assert fetched["closed_loop_enrolled"] is False

    def test_get_facility_not_found_returns_404(self, api):
        """PRD: "The first identifier that does not correspond to an existing
        resource produces an `ERR_NOT_FOUND` rejection, and no further
        validation or business logic runs after that point."

        Design: Corner/entities/get_facility_not_found_returns_404
        """
        resp = api.get_facility(MISSING_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_create_facility_missing_required_returns_validation(self, api):
        """PRD: "Required fields are present, types are valid, enum members are
        valid, quantities are at least 1, `period_end` is on or after
        `period_start`, `install_end` is strictly after `install_start`,
        `protection_end` is strictly after `protection_start`, and `score_pct`
        lies within 0 to 100 inclusive; otherwise `ERR_VALIDATION` (400)."
        PRD: "A `DistributorAdmin` onboards a facility by providing its display
        `name`, the `facility_group_code` that ties it to a GPO or co-op
        purchasing group, a `credit_limit_cents` ceiling"

        Design: Corner/entities/create_facility_missing_required_returns_validation
        """
        payload = create_facility_payload(name="Fac NoCredit")
        del payload["credit_limit_cents"]
        resp = api.create_facility(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_archive_blocked_returns_error(self, api):
        """PRD: "An `ACTIVE` facility may move to `ARCHIVED` only when it
        carries no order in `DRAFT`, `PLACED`, `PARTIALLY_BLOCKED`, or
        `DELIVERED` and no standing order in `DRAFT`, `ACTIVE`, or `PAUSED`;
        otherwise the attempt is rejected with `ERR_ARCHIVE_BLOCKED`."

        Design: Corner/validations/archive_blocked_returns_error
        """
        facility, _product, order = setup_placed_order(qty=1)
        assert order["status"] == "PLACED"
        resp = api.archive_facility(facility["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ARCHIVE_BLOCKED)
        after = validate_success(api.get_facility(facility["id"], ADMIN))
        assert after["status"] == "ACTIVE", (
            "The facility remains ACTIVE after the blocked archive")


class TestProductCatalog:
    def test_create_product_invalid_enum_returns_validation(self, api):
        """PRD: "Required fields are present, types are valid, enum members are
        valid, quantities are at least 1, `period_end` is on or after
        `period_start`, `install_end` is strictly after `install_start`,
        `protection_end` is strictly after `protection_start`, and `score_pct`
        lies within 0 to 100 inclusive; otherwise `ERR_VALIDATION` (400)."
        PRD: "a `category` of `CHEMICAL`, `PAPER`, `EQUIPMENT`,
        `DISPENSER_SUPPLY`, or `OTHER`"

        Design: Corner/entities/create_product_invalid_enum_returns_validation
        """
        payload = create_product_payload(sku="SKU-BAD", name="Bad",
                                         category="FOOD")
        resp = api.create_product(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_create_product_system_fields_input_ignored(self, api):
        """PRD: "`id` (string): a unique, server-generated identifier formatted
        as a UUID, with no type prefix."

        Design: Corner/entities/create_product_system_fields_input_ignored
        """
        supplied_id = "11111111-2222-4333-8444-555555555555"
        payload = create_product_payload(sku="SKU-SYS", name="Sys",
                                         base_price_cents=100, qty_on_hand=10)
        payload["id"] = supplied_id
        payload["version"] = 9
        resp = api.create_product(payload, ADMIN)
        product = validate_success(resp, 201)
        assert_product(product)
        assert product["id"] != supplied_id, (
            "The server mints its own id; the client-supplied id is ignored")

    def test_discontinue_blocked_returns_error(self, api):
        """PRD: "Discontinuation is terminal: a product in `ACTIVE` or
        `SHORTAGE` may move to `DISCONTINUED` only when none of its order lines
        remains `PENDING`, `ALLOCATED`, or `SUBSTITUTION_PENDING`; if any such
        line exists the attempt is rejected with `ERR_DISCONTINUE_BLOCKED`."

        Design: Corner/validations/discontinue_blocked_returns_error
        """
        facility, product, order = setup_placed_order(qty=1)
        assert order["status"] == "PLACED"
        resp = api.discontinue_product(product["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_DISCONTINUE_BLOCKED)
        after = validate_success(api.get_product(product["id"], ADMIN))
        assert after["status"] == "ACTIVE", (
            "The product remains ACTIVE after the blocked discontinue")


class TestAuthentication:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD: "A request missing either header, or carrying a role outside
        this declared set, is rejected with `ERR_UNAUTHENTICATED`."
        PRD: "When several checks could reject the same request, the system
        evaluates them in the following fixed order, and the first failing
        check determines the response: 1. **Authentication.** The
        `X-User-Role` and `X-User-ID` headers are present and the role is one
        of the declared roles; otherwise `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/errors/missing_auth_header_returns_unauthenticated
        """
        resp = api.get_facility(MISSING_UUID, {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleAuthorization:
    def test_sales_rep_cannot_create_product_returns_forbidden(self, api):
        """PRD: "A request whose role is valid but not listed among the roles
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN`."
        PRD endpoint table: "POST /jansan/products | Create a product with
        initial stock | DistributorAdmin".

        Design: Corner/rbac/sales_rep_cannot_create_product_returns_forbidden
        """
        payload = create_product_payload(sku="SKU-RB2", name="RB2",
                                         qty_on_hand=10)
        resp = api.create_product(payload, SALES)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_facility_manager_cannot_award_bid_returns_forbidden(self, api):
        """PRD: "A request whose role is valid but not listed among the roles
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN`."
        PRD: "The award decision belongs to a `DistributorAdmin` and is guarded
        by the window-overlap rule"

        Design: Corner/rbac/facility_manager_cannot_award_bid_returns_forbidden
        """
        product = create_product(sku="SKU-RB1", name="RB1")
        bid = create_contract_bid(product, facility_group_code="GPO-9",
                                  bid_reference="BID-RB")
        bid = bid_to_under_review(bid)
        assert bid["status"] == "UNDER_REVIEW"
        resp = api.award_bid(bid["id"],
                             TEST_USERS["facility_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        after = validate_success(api.get_contract_bid(bid["id"], ADMIN))
        assert after["status"] == "UNDER_REVIEW", (
            "The bid remains UNDER_REVIEW after the forbidden award attempt")

    def test_technician_cannot_complete_other_technicians_dispenser(self, api):
        """PRD: "Completion belongs to the field: only a `FieldTechnician` may
        complete an install, and only the one whose `technician_id` matches
        their `X-User-ID` — anyone else draws `ERR_FORBIDDEN`."

        Design: Corner/rbac/technician_cannot_complete_other_technicians_dispenser_returns_forbidden
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac RB", category="CHEMICAL", base_price_cents=2500,
            qty_on_hand=50, chemical_family="NEUTRAL", unit_of_measure="GAL")
        tech_one = create_technician(name="Tech One")
        tech_two = create_technician(name="Tech Two")
        dispenser = create_dispenser(facility, product, tech_one, zone="dock")
        resp = api.complete_dispenser(
            dispenser["id"], make_field_technician_headers(tech_two["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_dispenser(dispenser["id"], ADMIN))
        assert after["status"] == "SCHEDULED", (
            "The dispenser stays SCHEDULED after the forbidden completion")

    def test_facility_manager_cannot_act_on_other_facility(self, api):
        """PRD: "When `X-User-Role` is `FacilityManager`, `X-User-ID` is the
        `id` of the acting Facility; ownership checks on any resource that
        references a facility compare the resource's `facility_id` field to
        `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/facility_manager_cannot_act_on_other_facility_returns_forbidden
        """
        fac_a = create_facility(name="Fac RA")
        fac_b = create_facility(name="Fac RB2")
        product = create_product(sku="SKU-RB4", name="RB4")
        order = create_order_draft(
            fac_a, [order_line(product["id"], 1)], as_admin=True)
        resp = api.place_order(
            order["id"], make_facility_manager_headers(fac_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_order(order["id"], ADMIN))
        assert after["status"] == "DRAFT", (
            "The order stays DRAFT after the cross-facility place attempt")
