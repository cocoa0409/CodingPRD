"""Stale versions, cross-bakery links, duplicate keys and the negotiation cap (PRD §2.1, §2.6, §3.2, §3.6, §3.11)."""

from test_helpers import (
    ApiErrorId,
    add_contract_line,
    add_order_line,
    allocate_order,
    api_client,
    append_stop,
    attach_engagement_payload,
    create_customer,
    create_product,
    create_route,
    create_route_stop_payload,
    create_silo_payload,
    create_zone,
    counter_contract,
    draft_contract,
    log_hours,
    make_account_manager_headers,
    make_pricing_controller_headers,
    offer_contract,
    open_engagement,
    open_order,
    read_contract,
    read_contract_line,
    read_engagement,
    read_order,
    read_route,
    read_silo,
    receive_lot,
    register_silo,
    set_clock,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import LP, TS, WO

EPOCH = "2026-08-01T00:00:00Z"
SERVICE_ON = "2026-09-10T00:00:00Z"

FLOUR_30 = {
    "sku": "FLR-ERR-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 180,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}
INDEXED_FLOUR = dict(FLOUR_30, sku="FLR-IDX-30", index_code="HRW_WHEAT")


def _allocated(customer, product_id, quantity_lb, requested_delivery_on=SERVICE_ON):
    order = open_order(
        customer,
        delivery_mode="BAGGED",
        requested_delivery_on=requested_delivery_on,
    )
    add_order_line(customer, order["id"], product_id, quantity_lb)
    submit_order(customer, order["id"])
    allocate_order(order["id"])
    return order


class TestReplayingTheRouteVersionReadBeforeTheFirstStop:
    """The body is legal in every other respect, so only the version guard can speak."""

    def test_the_second_append_against_the_original_version_is_refused(self):
        """PRD §2.6: "A value that differs from the route's current `version` is
        rejected with `ERR_STALE_ROUTE_VERSION` (HTTP 412). Appending a stop is always
        permissible while the route's status is `PLANNING` and the trailer is under
        capacity, so no state check rejects it; optimistic concurrency on the route's
        `version` is what prevents a planner from appending against a stale view of
        `planned_load_lb`, `utilization_pct` and `allergen_class_lock`."

        Design: Corner/errors/corner_err_stale_route_version_rejected_after_sibling_stop_bumped_it
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(FLOUR_30, sku="FLR-OCC-30"))
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        receive_lot(
            flour["id"], zone["id"], lot_code="LOT-OCC-0001",
            manufactured_on="2026-07-01T00:00:00Z", quantity_received_lb=40000,
        )
        first_order = _allocated(customer, flour["id"], 1000)
        second_order = _allocated(customer, flour["id"], 2000)
        route = create_route(
            route_code="R-OCC",
            service_on=SERVICE_ON,
            vehicle_capacity_lb=48000,
            service_buffer_minutes=30,
        )
        stale_version = route["version"]
        append_stop(
            route["id"], first_order["id"],
            "2026-09-10T08:00:00Z", "2026-09-10T09:00:00Z",
            expected_route_version=stale_version,
        )
        current_version = read_route(route["id"])["version"]

        response = api_client.create_route_stop(
            route["id"],
            create_route_stop_payload(
                second_order["id"],
                stale_version,
                window_start_at="2026-09-10T11:00:00Z",
                window_end_at="2026-09-10T12:00:00Z",
            ),
            LP,
        )

        validate_error(response, ApiErrorId.ERR_STALE_ROUTE_VERSION)
        assert response.status_code == 412, (
            f"Expected HTTP 412, got {response.status_code}"
        )
        unchanged = read_route(route["id"])
        assert unchanged["stop_count"] == 1, (
            f"Expected stop_count 1, got {unchanged['stop_count']}"
        )
        assert unchanged["planned_load_lb"] == 1000, (
            f"Expected only the first stop's pounds, got {unchanged['planned_load_lb']}"
        )
        assert unchanged["version"] == current_version, (
            f"A rejected call mutates nothing, expected version {current_version}, got "
            f"{unchanged['version']}"
        )
        assert read_order(second_order["id"])["fulfillment_status"] == "ALLOCATED", (
            "The refused order must not advance to ROUTED"
        )
        stops, _meta = validate_paginated(
            api_client.list_route_stops(LP, params={"order_id": second_order["id"]})
        )
        assert stops == [], (
            f"Expected no stop for the refused order, got {len(stops)}"
        )


class TestAttachingAnEngagementToAnotherBakerysOrder:
    """Both rows are individually attachable; only the bakery link is wrong."""

    def test_the_attach_is_refused_and_neither_the_fee_nor_the_order_moves(self):
        """PRD §3.11: "The target order is named by an `order_id` in the request, must
        belong to the same bakery as the engagement — a mismatch between the
        engagement's `customer_id` and the order's `customer_id` is rejected with
        `ERR_ENTITY_LINK_MISMATCH` — and must have `pricing_status` exactly
        `PROVISIONAL`."

        PRD §3.6: "One referential check accompanies the fill plan: the silo's
        `product_id` must agree with the order line's `product_id`, and a disagreement
        is reported as `ERR_ENTITY_LINK_MISMATCH` (HTTP 409). The same error code covers
        two sibling mismatches elsewhere — a support engagement whose `customer_id`
        differs from the target order's `customer_id` at attach time"

        Design: Corner/errors/corner_err_engagement_attach_to_other_bakerys_order_link_mismatch
        """
        set_clock(EPOCH)
        bakery_a = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        bakery_b = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(FLOUR_30, sku="FLR-LNK-30"))
        order = open_order(
            bakery_b,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        add_order_line(bakery_b, order["id"], flour["id"], 1000)
        submitted = submit_order(bakery_b, order["id"])
        engagement = open_engagement(bakery_a, flour["id"])
        billable = log_hours(
            engagement["id"], 6.0, work_note="Crumb structure trials for bakery A"
        )
        assert billable["status"] == "BILLABLE", (
            f"The engagement must be attachable on its own terms, got {billable['status']}"
        )
        assert submitted["pricing_status"] == "PROVISIONAL", (
            f"The order must be attachable on its own terms, got "
            f"{submitted['pricing_status']}"
        )

        response = api_client.attach_tech_engagement(
            engagement["id"], attach_engagement_payload(order["id"]), TS
        )

        validate_error(response, ApiErrorId.ERR_ENTITY_LINK_MISMATCH)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        held = read_engagement(engagement["id"])
        assert held["status"] == "BILLABLE", (
            f"Expected the engagement still BILLABLE, got {held['status']}"
        )
        assert held["order_id"] is None, (
            f"Expected no order bound, got {held['order_id']}"
        )
        untouched = read_order(order["id"])
        assert untouched["tech_attach_fee_cents"] == 0, (
            f"Expected no fee on the other bakery's order, got "
            f"{untouched['tech_attach_fee_cents']}"
        )
        assert untouched["total_cents"] == 30750, (
            f"Expected the settlement unchanged at 30750, got {untouched['total_cents']}"
        )


class TestTheSiloKeyIsBakeryAndSkuTogether:
    """A second code at the same bakery duplicates; the same SKU elsewhere does not."""

    def test_a_differently_coded_silo_for_the_same_pairing_is_refused(self):
        """PRD §3.6: "At most one silo may exist per pairing of bakery and SKU; a second
        registration for the same pairing is rejected with `ERR_DUPLICATE_RESOURCE`."

        PRD §3.6: "A `WarehouseOperator` registers such a silo from a `silo_code` of 2
        to 16 characters that is globally unique, the `customer_id` whose site hosts it,
        the `product_id` it is dedicated to — which must be a SKU whose `bulk_capable`
        is true — and a `capacity_lb` of at least 1000 pounds."

        Design: Corner/errors/corner_err_second_silo_for_same_customer_sku_pair_rejected
        """
        set_clock(EPOCH)
        bakery_a = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        bakery_b = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        bulk_flour = create_product(
            dict(FLOUR_30, sku="FLR-BLK-30", bulk_capable=True)
        )
        first_silo = register_silo(
            bakery_a["id"], bulk_flour["id"], silo_code="S-A1",
            capacity_lb=80000, min_fill_lb=4000,
        )
        other_bakerys_silo = register_silo(
            bakery_b["id"], bulk_flour["id"], silo_code="S-B1",
            capacity_lb=80000, min_fill_lb=4000,
        )

        response = api_client.create_silo(
            create_silo_payload(
                bakery_a["id"], bulk_flour["id"], silo_code="S-A2",
                capacity_lb=50000, min_fill_lb=4000,
            ),
            WO,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        silos, _meta = validate_paginated(
            api_client.list_silos(WO, params={"customer_id": bakery_a["id"]})
        )
        assert len(silos) == 1, (
            f"Expected the one registered silo at that bakery, got {len(silos)}"
        )
        assert silos[0]["id"] == first_silo["id"], (
            f"Expected S-A1 to be the survivor, got {silos[0]['id']}"
        )
        assert read_silo(other_bakerys_silo["id"])["silo_code"] == "S-B1", (
            "The same SKU at a second bakery was never a duplicate"
        )


class TestSegregationIsEnforcedOnTheOperatorIdNotTheRole:
    """One human wearing two role hats is still one human."""

    def test_the_authoring_operator_may_not_activate_even_as_pricing_controller(self):
        """PRD §3.2: "Only a `PricingController` may move a contract from `OFFERED` to
        `ACTIVE`, and four conditions must hold: the contract is in `OFFERED`; the
        acting operator's `X-User-ID` differs from the contract's
        `authored_by_user_id`" ... "A same-operator collision returns
        `ERR_SEGREGATION_OF_DUTIES`" ... "Activation records the acting controller in
        `approved_by_user_id` and increments `version` by 1; that field is null on every
        contract that has not yet been activated."

        PRD §3.2: "The offer records the acting operator in `authored_by_user_id`,
        recomputes `committed_volume_lb` from the contract's lines, and increments
        `version` by 1."

        PRD §3.2: "A freshly drafted contract has `status` equal to `DRAFT`,
        `negotiation_round` at 0, and both `committed_volume_lb` and `drawn_volume_lb`
        at 0."

        Design: Corner/errors/corner_err_same_operator_id_across_two_roles_breaks_segregation
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(INDEXED_FLOUR, sku="FLR-SOD-30"))
        contract = draft_contract(
            customer,
            term_start_on="2026-09-01T00:00:00Z",
            term_end_on="2026-12-31T00:00:00Z",
            pricing_mode="ORDER_DATE_INDEX",
        )
        add_contract_line(
            contract["id"], flour["id"],
            volume_committed_lb=50000,
            basis_cents_per_lb=12,
            cap_cents_per_lb=160,
        )
        offer_contract(contract["id"], author_user_id="op-dual")

        response = api_client.activate_forward_contract(
            contract["id"], {}, make_pricing_controller_headers("op-dual")
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert response.status_code == 403, (
            f"Expected HTTP 403, got {response.status_code}"
        )
        offered = read_contract(contract["id"])
        assert offered["status"] == "OFFERED", (
            f"Expected the contract still OFFERED, got {offered['status']}"
        )
        assert offered["approved_by_user_id"] is None, (
            f"Expected no approver recorded, got {offered['approved_by_user_id']}"
        )
        assert offered["authored_by_user_id"] == "op-dual", (
            f"Expected the offering operator recorded, got "
            f"{offered['authored_by_user_id']}"
        )
        assert offered["negotiation_round"] == 0, (
            f"The opening offer is not a re-offer, got {offered['negotiation_round']}"
        )

        activated = validate_success(
            api_client.activate_forward_contract(
                contract["id"], {}, make_pricing_controller_headers("pc-1")
            ),
            200,
        )

        assert activated["status"] == "ACTIVE", (
            f"A different operator in the same role may activate, got "
            f"{activated['status']}"
        )
        assert activated["approved_by_user_id"] == "pc-1", (
            f"Expected pc-1 recorded as approver, got {activated['approved_by_user_id']}"
        )


class TestTheNegotiationCapCountsReOffersOnly:
    """Three re-offers land; the fourth is refused and the buyer's basis stands."""

    def test_the_fifth_offer_is_refused_while_the_contract_stays_countered(self):
        """PRD §3.2: "Re-offering a `COUNTERED` contract is permitted only while
        `negotiation_round` is strictly less than 3; the re-offer increments
        `negotiation_round` by 1, re-records `authored_by_user_id` as the operator who
        re-offered, and increments `version` by 1. A fourth attempt — that is, an
        attempt made when `negotiation_round` has already reached 3 — is rejected with
        `ERR_ROUND_LIMIT_REACHED` (HTTP 409)."

        PRD §3.2: "The counter carries a single `counter_basis_cents_per_lb`, and that
        value replaces `basis_cents_per_lb` on **every** line of the contract, not
        merely on one."

        Design: Corner/errors/corner_err_fourth_negotiation_round_rejected_at_round_three
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(INDEXED_FLOUR, sku="FLR-RND-30"))
        contract = draft_contract(
            customer,
            term_start_on="2026-09-01T00:00:00Z",
            term_end_on="2026-12-31T00:00:00Z",
            pricing_mode="ORDER_DATE_INDEX",
        )
        contract_line = add_contract_line(
            contract["id"], flour["id"],
            volume_committed_lb=50000,
            basis_cents_per_lb=20,
            cap_cents_per_lb=160,
        )
        offer_contract(contract["id"])
        for counter_basis in (18, 15, 11):
            counter_contract(customer, contract["id"], counter_basis)
            offer_contract(contract["id"])
        countered = counter_contract(customer, contract["id"], 7)
        assert countered["negotiation_round"] == 3, (
            f"Three re-offers exhaust the cap, got {countered['negotiation_round']}"
        )

        response = api_client.offer_forward_contract(
            contract["id"], {}, make_account_manager_headers("am-1")
        )

        validate_error(response, ApiErrorId.ERR_ROUND_LIMIT_REACHED)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        stuck = read_contract(contract["id"])
        assert stuck["status"] == "COUNTERED", (
            f"Expected the contract still COUNTERED, got {stuck['status']}"
        )
        assert stuck["negotiation_round"] == 3, (
            f"The refused re-offer increments nothing, got {stuck['negotiation_round']}"
        )
        assert read_contract_line(contract_line["id"])["basis_cents_per_lb"] == 7, (
            "The buyer's last counter stands on the line"
        )
