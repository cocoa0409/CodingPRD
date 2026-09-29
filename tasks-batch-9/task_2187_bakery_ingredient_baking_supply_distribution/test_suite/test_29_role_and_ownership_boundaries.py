"""Header, role, ownership and duty boundaries on the write surfaces (PRD §2.1, §2.7, §4)."""

from test_helpers import (
    ApiErrorId,
    add_order_line,
    allocate_order,
    api_client,
    build_user_headers,
    create_customer,
    create_product,
    create_product_payload,
    create_zone,
    make_customer_buyer_headers,
    make_quality_manager_headers,
    open_order,
    raise_substitution_request,
    read_customer,
    read_order,
    read_silo,
    read_substitution_request,
    read_zone,
    receive_lot,
    register_silo,
    residual_reading_payload,
    zone_lockout_payload,
    set_clock,
    submit_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, PC, QM, WO, buyer_headers

EPOCH = "2026-08-01T00:00:00Z"
SERVICE_ON = "2026-09-10T00:00:00Z"

FLOUR_30 = {
    "sku": "FLR-RBAC-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 365,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


class TestTwoAuthDefectsAtOnce:
    """An empty id and an undeclared role, and only the first check may speak."""

    def test_the_empty_user_id_is_reported_before_the_unknown_role(self):
        """PRD §2.1: "Every request to every endpoint must carry two headers:
        `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role
        that principal is acting under. If either header is absent or present but empty,
        the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401). If
        `X-User-Role` carries a value that is not one of the eight roles enumerated
        below, the rejection is `ERR_UNKNOWN_ROLE`, also HTTP 401."

        PRD §2.7: "Authentication comes first: header presence, then role recognition,
        then endpoint role authorization."

        Design: Corner/rbac/corner_rbac_missing_user_id_outranks_unknown_role_rejected
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)

        response = api_client.get_customer(
            customer["id"], build_user_headers("", "BakeryManager")
        )

        validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS)
        assert response.status_code == 401, (
            f"Expected HTTP 401, got {response.status_code}"
        )

        named = api_client.get_customer(
            customer["id"], build_user_headers("someone-1", "BakeryManager")
        )

        validate_error(named, ApiErrorId.ERR_UNKNOWN_ROLE)
        assert named.status_code == 401, (
            f"With a non-empty id the second check speaks, got {named.status_code}"
        )


class TestAnUndeclaredRoleOnARestrictedWrite:
    """The role name is not recognised at all, so authorization never runs."""

    def test_the_unknown_role_is_reported_rather_than_a_permission_refusal(self):
        """PRD §2.1: "If `X-User-Role` carries a value that is not one of the eight roles
        enumerated below, the rejection is `ERR_UNKNOWN_ROLE`, also HTTP 401. When the
        headers are well-formed but the named role does not appear in the
        authorized-role list for the endpoint being called (see §4), the request is
        rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        PRD §4: "| POST | `/bakery-distribution/products` | Creates a SKU with its
        allergen class, shelf life, rotation floor, index linkage and list price. |
        PricingController |"

        Design: Corner/rbac/corner_rbac_unknown_role_outranks_role_not_permitted_rejected
        """
        set_clock(EPOCH)
        payload = create_product_payload(
            sku="FLR-RBAC-30",
            category="FLOUR",
            allergen_class="GLUTEN",
            shelf_life_days=180,
            index_code="NONE",
            list_price_cents_per_lb=30,
            min_rotation_days=0,
        )

        response = api_client.create_product(
            payload, build_user_headers("ms-1", "MillSupervisor")
        )

        validate_error(response, ApiErrorId.ERR_UNKNOWN_ROLE)
        assert response.status_code == 401, (
            f"Expected HTTP 401, got {response.status_code}"
        )

        real_but_wrong_role = api_client.create_product(payload, WO)

        validate_error(real_but_wrong_role, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
        assert real_but_wrong_role.status_code == 403, (
            f"A declared role on the wrong endpoint gets 403, got "
            f"{real_but_wrong_role.status_code}"
        )

        created = validate_success(api_client.create_product(payload, PC), 201)

        assert created["sku"] == "FLR-RBAC-30", (
            f"The SKU was free to create, so nothing was stored by the refusals, got "
            f"{created['sku']}"
        )


class TestThePlatformAdminIsNotASuperuser:
    """A read-and-clock role cannot act for the bakery that owns the order."""

    def test_the_admin_submit_is_refused_and_the_owning_buyer_then_succeeds(self):
        """PRD §2.1: "When the headers are well-formed but the named role does not appear
        in the authorized-role list for the endpoint being called (see §4), the request
        is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        PRD §4: "| POST | `/bakery-distribution/orders/{id}/submit` | Submits the order:
        prices every line at the order-date index, checks minimum drop and credit, and
        draws contract volume. | CustomerBuyer |"

        Design: Corner/rbac/corner_rbac_platform_admin_cannot_submit_a_bakerys_order
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(FLOUR_30, sku="FLR-ADM-30"))
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        add_order_line(customer, order["id"], flour["id"], 1000)

        response = api_client.submit_order(order["id"], {}, ADMIN)

        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
        assert response.status_code == 403, (
            f"Expected HTTP 403, got {response.status_code}"
        )
        untouched = read_order(order["id"])
        assert untouched["fulfillment_status"] == "NEW", (
            f"Expected NEW, got {untouched['fulfillment_status']}"
        )
        assert untouched["pricing_status"] == "UNPRICED", (
            f"Expected UNPRICED, got {untouched['pricing_status']}"
        )
        assert untouched["total_cents"] == 0, (
            f"Expected nothing priced, got {untouched['total_cents']}"
        )

        submitted = submit_order(customer, order["id"])

        assert submitted["total_cents"] == 30750, (
            f"The owning buyer's identical submit prices the order, got "
            f"{submitted['total_cents']}"
        )


class TestOwnershipIsReadFromTheTargetRow:
    """Buyer B is a perfectly valid buyer, just not this order's buyer."""

    def test_the_neighbouring_bakerys_buyer_is_refused_as_a_non_owner(self):
        """PRD §2.1: "When `X-User-Role` is `CustomerBuyer`, `X-User-ID` is the `id` of
        the acting `Customer`; ownership checks on any resource that references a
        `Customer` compare the resource's foreign-key field to `X-User-ID` — an order's
        `customer_id`, or a forward contract's `customer_id`. A `CustomerBuyer` acting on
        a resource whose owning key differs from their `X-User-ID` is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership check applies to opening an
        order, adding a line to an order, submitting an order, cancelling an order,
        countering a forward contract, and reading a single customer record."

        PRD §2.7: "then the resource-ownership check for the `CustomerBuyer` role"

        Design: Corner/rbac/corner_rbac_buyer_cannot_submit_another_bakerys_order
        """
        set_clock(EPOCH)
        bakery_a = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        bakery_b = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(FLOUR_30, sku="FLR-OWN-30"))
        order = open_order(
            bakery_a,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        add_order_line(bakery_a, order["id"], flour["id"], 1000)

        response = api_client.submit_order(
            order["id"], {}, make_customer_buyer_headers(bakery_b["id"])
        )

        validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert response.status_code == 403, (
            f"Expected HTTP 403 rather than a role refusal, got {response.status_code}"
        )
        untouched = read_order(order["id"])
        assert untouched["fulfillment_status"] == "NEW", (
            f"Expected NEW, got {untouched['fulfillment_status']}"
        )
        assert read_customer(bakery_a["id"])["open_exposure_cents"] == 0, (
            "A refused submission books no exposure at the owning bakery"
        )

        cross_read = api_client.get_customer(
            bakery_a["id"], make_customer_buyer_headers(bakery_b["id"])
        )

        validate_error(cross_read, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert cross_read.status_code == 403, (
            f"Reading a single customer record is ownership-gated too, got "
            f"{cross_read.status_code}"
        )


class TestTheOneWriteSharedWithTheBakery:
    """Operator and buyer both probe the silo, and each reading overwrites."""

    def test_the_buyers_reading_replaces_the_operators_capacity_boundary_reading(self):
        """PRD §3.6: "A level-probe reading, submitted by either a `WarehouseOperator` or
        the bakery's own `CustomerBuyer`, carries a `measured_residual_lb` that overwrites
        `residual_lb` outright rather than adjusting it; the value must be no less than
        zero and no greater than the silo's `capacity_lb`, and a reading outside that
        range is a schema failure reported as `ERR_VALIDATION`."

        PRD §3.6: "A new silo has `residual_lb` at 0 and both
        `last_fill_window_start_at` and `last_fill_window_end_at` null, since it has
        never been filled."

        Design: Corner/rbac/corner_rbac_shared_residual_reading_accepted_from_both_peer_roles
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        bulk_flour = create_product(
            dict(FLOUR_30, sku="FLR-SHR-30", bulk_capable=True)
        )
        silo = register_silo(
            customer["id"], bulk_flour["id"], silo_code="S-SHARE",
            capacity_lb=80000, min_fill_lb=4000,
        )
        assert silo["residual_lb"] == 0, (
            f"A fresh silo starts empty, got {silo['residual_lb']}"
        )
        at_capacity = validate_success(
            api_client.create_residual_reading(
                silo["id"], residual_reading_payload(80000), WO
            ),
            200,
        )
        assert at_capacity["residual_lb"] == 80000, (
            f"The capacity boundary is inside the accepted band, got "
            f"{at_capacity['residual_lb']}"
        )

        overwritten = validate_success(
            api_client.create_residual_reading(
                silo["id"], residual_reading_payload(12500), buyer_headers(customer)
            ),
            200,
        )

        assert overwritten["residual_lb"] == 12500, (
            f"The reading overwrites rather than accumulating to 92500, got "
            f"{overwritten['residual_lb']}"
        )
        assert overwritten["last_fill_window_start_at"] is None, (
            f"A probe reading is not a fill, got "
            f"{overwritten['last_fill_window_start_at']}"
        )

        over_capacity = api_client.create_residual_reading(
            silo["id"], residual_reading_payload(80001), WO
        )

        validate_error(over_capacity, ApiErrorId.ERR_VALIDATION)
        assert over_capacity.status_code == 400, (
            f"One pound past capacity is a schema failure, got "
            f"{over_capacity.status_code}"
        )
        assert read_silo(silo["id"])["residual_lb"] == 12500, (
            "The refused reading leaves the last accepted value standing"
        )


class TestTheZoneOwnerCannotLockOutTheZone:
    """Creating the zone confers no authority over its sanitation window."""

    def test_the_operator_is_refused_and_the_quality_manager_is_not(self):
        """PRD §3.1: "Zones do not stay open forever: a `QualityManager` schedules an
        allergen-changeover sanitation lockout by supplying `lockout_start_at` and
        `lockout_end_at`, or clears an existing one by passing the optional `clear` flag.
        The lockout is a **closed** interval — both endpoints belong to it. When the
        logical clock instant falls inside that closed interval the zone's `status` reads
        `SANITATION_LOCKOUT`, and otherwise `OPEN`"

        PRD §4: "| POST | `/bakery-distribution/warehouse-zones/{id}/lockout` | Schedules
        or clears the allergen-changeover sanitation lockout on a zone. |
        QualityManager |"

        Design: Corner/rbac/corner_rbac_operator_cannot_schedule_a_sanitation_lockout
        """
        set_clock(EPOCH)
        zone = create_zone(zone_code="Z-LCK", allergen_class="GLUTEN")
        payload = zone_lockout_payload(
            lockout_start_at="2026-08-01T00:00:00Z",
            lockout_end_at="2026-08-02T00:00:00Z",
        )

        response = api_client.set_zone_lockout(zone["id"], payload, WO)

        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
        assert response.status_code == 403, (
            f"Expected HTTP 403, got {response.status_code}"
        )
        open_zone = read_zone(zone["id"])
        assert open_zone["status"] == "OPEN", (
            f"Expected the zone still OPEN, got {open_zone['status']}"
        )
        assert open_zone["lockout_start_at"] is None, (
            f"Expected no window scheduled, got {open_zone['lockout_start_at']}"
        )
        assert open_zone["lockout_end_at"] is None, (
            f"Expected no window scheduled, got {open_zone['lockout_end_at']}"
        )

        locked = validate_success(
            api_client.set_zone_lockout(zone["id"], payload, QM), 200
        )

        assert locked["status"] == "SANITATION_LOCKOUT", (
            f"The clock sits on the inclusive start instant, so expected "
            f"SANITATION_LOCKOUT, got {locked['status']}"
        )
        assert locked["lockout_start_at"] == "2026-08-01T00:00:00Z", (
            f"Expected the scheduled start recorded, got {locked['lockout_start_at']}"
        )


class TestSwitchingHatsDoesNotClearTheRequesterFlag:
    """The specialist who raised the proposal cannot review it as quality."""

    def test_the_requesting_operator_id_is_refused_on_claim_and_another_id_is_not(self):
        """PRD §2.1: "Recorded operator identifiers exist to enforce segregation of
        duties: the `PricingController` who activates a contract must not be the operator
        recorded in `authored_by_user_id`, and the `QualityManager` who claims, approves,
        or rejects a substitution request must not be the operator recorded in
        `requested_by_user_id`. Either collision is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD §3.8: "Claiming a request moves it `REQUESTED → UNDER_REVIEW` and records the
        claiming manager in `decided_by_user_id`; it requires that the request is in
        `REQUESTED`, that the claimant's `X-User-ID` differs from `requested_by_user_id`,
        and that the parent order's `fulfillment_status` is still `NEW` or `ALLOCATED`."

        PRD §3.8: "The new request starts with `status` at `REQUESTED`, `revision_round`
        at 0, `requested_by_user_id` set to the acting specialist's `X-User-ID`, and
        `decided_by_user_id` null."

        Design: Corner/rbac/corner_rbac_specialist_id_reused_as_quality_manager_cannot_claim
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        ordered = create_product(dict(FLOUR_30, sku="FLR-SBA-30"))
        proposed = create_product(
            dict(FLOUR_30, sku="FLR-SBB-32", list_price_cents_per_lb=32)
        )
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        receive_lot(
            ordered["id"], zone["id"], lot_code="LOT-SBA-0001",
            manufactured_on="2026-07-15T00:00:00Z", quantity_received_lb=20000,
        )
        receive_lot(
            proposed["id"], zone["id"], lot_code="LOT-SBB-0001",
            manufactured_on="2026-07-15T00:00:00Z", quantity_received_lb=20000,
        )
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        line = add_order_line(customer, order["id"], ordered["id"], 1000)
        submit_order(customer, order["id"])
        allocated = allocate_order(order["id"])
        request = raise_substitution_request(
            line["id"], proposed["id"], allocated["version"],
            specialist_user_id="op-solo",
            rationale="Mill outage on the ordered SKU",
        )

        response = api_client.claim_substitution_request(
            request["id"], {}, make_quality_manager_headers("op-solo")
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert response.status_code == 403, (
            f"Expected HTTP 403, got {response.status_code}"
        )
        held = read_substitution_request(request["id"])
        assert held["status"] == "REQUESTED", (
            f"Expected the request still REQUESTED, got {held['status']}"
        )
        assert held["decided_by_user_id"] is None, (
            f"Expected no decider recorded, got {held['decided_by_user_id']}"
        )
        assert held["requested_by_user_id"] == "op-solo", (
            f"Expected the raising operator recorded, got "
            f"{held['requested_by_user_id']}"
        )
        assert held["revision_round"] == 0, (
            f"Expected revision_round 0, got {held['revision_round']}"
        )

        claimed = validate_success(
            api_client.claim_substitution_request(
                request["id"], {}, make_quality_manager_headers("qm-1")
            ),
            200,
        )

        assert claimed["status"] == "UNDER_REVIEW", (
            f"A different quality id may claim the same request, got "
            f"{claimed['status']}"
        )
        assert claimed["decided_by_user_id"] == "qm-1", (
            f"Expected qm-1 recorded as the claimant, got "
            f"{claimed['decided_by_user_id']}"
        )
