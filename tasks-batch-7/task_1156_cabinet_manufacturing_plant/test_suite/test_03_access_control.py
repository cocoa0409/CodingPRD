"""Role-based access control, entity-backed ownership, and path existence."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_box_line_payload,
    create_dealer_payload,
    create_delivery_route_payload,
    create_finish_spec_payload,
    create_modification_payload,
    get_success_data,
    make_dealer_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
FINISH = TEST_USERS["finish_supervisor_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
SHIPPING = TEST_USERS["shipping_coordinator_headers"]


class TestRoleDenials:
    def test_dealer_cannot_review_modification(self, api):
        """PRD §2.1: "`Engineer` reviews modification requests."
        PRD §2.1: "A request whose authenticated role is not in the endpoint's
        permitted set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/dealer_cannot_review_modification
        """
        dealer = get_success_data(api.create_dealer(create_dealer_payload(), ADMIN))
        finish = get_success_data(api.create_finish_spec(create_finish_spec_payload(), ADMIN))
        order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
        line = get_success_data(
            api.create_order_line(
                order["id"], create_box_line_payload(finish["id"]), make_dealer_headers(dealer["id"])
            )
        )
        mod = get_success_data(
            api.create_modification(
                line["id"],
                create_modification_payload(mod_code="TOE_KICK_NOTCH", new_dimension_in=4),
                make_dealer_headers(dealer["id"]),
            )
        )
        # Even the owning dealer cannot perform the Engineer's review verb.
        resp = api.review_modification(mod["id"], {"decision": "APPROVE"}, make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_engineer_cannot_create_finish_batch(self, api):
        """PRD §2.1: "`FinishSupervisor` runs the finish room: batches, QC
        recording, door line assignment, and remixing."
        PRD §2.1: "A request whose authenticated role is not in the endpoint's
        permitted set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/engineer_cannot_create_finish_batch
        """
        finish = get_success_data(
            api.create_finish_spec(
                create_finish_spec_payload(finish_code="FS-QC", sheen="SEMI_GLOSS", upcharge_pct=0.12),
                ADMIN,
            )
        )
        resp = api.create_finish_batch(
            {"finish_id": finish["id"], "sheen_lot_no": "LOT-X", "capacity_doors": 10},
            ENGINEER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_planner_cannot_dispatch_route(self, api):
        """PRD §2.1: "`ShippingCoordinator` builds delivery routes, assigns orders,
        and locks and dispatches routes."
        PRD §2.1: "A request whose authenticated role is not in the endpoint's
        permitted set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/planner_cannot_dispatch_route
        """
        route = get_success_data(
            api.create_delivery_route(
                create_delivery_route_payload(route_code="RT-R", route_date="2026-05-06", capacity_cu_ft=100.0),
                SHIPPING,
            )
        )
        resp = api.dispatch_route(route["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_plant_admin_cannot_create_order(self, api):
        """PRD §2.1: "`Dealer` places and manages its own orders, lines,
        modification requests, and replacement claims."
        PRD §2.1: "A request whose authenticated role is not in the endpoint's
        permitted set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/plant_admin_cannot_create_order
        """
        resp = api.create_order(ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestOwnership:
    def test_dealer_b_cannot_submit_dealer_a_order(self, api):
        """PRD §2.1: "ownership checks on any resource that references a dealer
        compare the resource's dealer foreign key — an order's `dealer_id`, a
        claim's `dealer_id`, or the owning order's `dealer_id` for operations on
        lines and modification requests — against `X-User-ID`. A mismatch is
        rejected with `ERR_RESOURCE_OWNERSHIP_MISMATCH` (HTTP 403); this applies to
        submitting and cancelling orders, adding lines, creating or resubmitting
        modification requests, and filing replacement claims against one's own
        orders."

        Design: Corner/rbac/dealer_b_cannot_submit_dealer_a_order
        """
        dealer_a = get_success_data(
            api.create_dealer(
                create_dealer_payload(name="Dealer A", dealer_code="DA", price_level="L3"), ADMIN
            )
        )
        dealer_b = get_success_data(
            api.create_dealer(
                create_dealer_payload(name="Dealer B", dealer_code="DB", price_level="L1"), ADMIN
            )
        )
        finish = get_success_data(api.create_finish_spec(create_finish_spec_payload(), ADMIN))
        order = get_success_data(api.create_order(make_dealer_headers(dealer_a["id"])))
        get_success_data(
            api.create_order_line(
                order["id"], create_box_line_payload(finish["id"]), make_dealer_headers(dealer_a["id"])
            )
        )
        resp = api.submit_order(order["id"], make_dealer_headers(dealer_b["id"]))
        validate_error(resp, ApiErrorId.ERR_RESOURCE_OWNERSHIP_MISMATCH)
        reread = validate_success(api.get_order(order["id"], ADMIN))
        assert reread["status"] == "DRAFT", "order must stay DRAFT after a foreign submit attempt"


class TestNotFound:
    def test_dealer_update_not_found(self, api, plant_admin_headers):
        """PRD §2.7: "Existence of path-templated resource ids, validated left to
        right along the URL; the first missing segment produces the corresponding
        not-found error (for example `ERR_ORDER_NOT_FOUND` before
        `ERR_ORDER_LINE_NOT_FOUND` on a nested path)."

        Design: Corner/errors/dealer_update_not_found
        """
        resp = api.update_dealer(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", {"credit_limit_cents": 1000}, plant_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_DEALER_NOT_FOUND)

    def test_route_not_found_on_assign(self, api, plant_admin_headers):
        """PRD §2.7: "Existence of path-templated resource ids, validated left to
        right along the URL; the first missing segment produces the corresponding
        not-found error (for example `ERR_ORDER_NOT_FOUND` before
        `ERR_ORDER_LINE_NOT_FOUND` on a nested path). The per-resource not-found
        errors are `ERR_DEALER_NOT_FOUND`, `ERR_DOOR_STYLE_NOT_FOUND`,
        `ERR_FINISH_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_ORDER_LINE_NOT_FOUND`, `ERR_MODIFICATION_NOT_FOUND`,
        `ERR_BATCH_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
        `ERR_PART_NOT_FOUND`, `ERR_ASSEMBLY_LINE_NOT_FOUND`,
        `ERR_SUB_LOT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, and
        `ERR_HOLD_NOT_FOUND`, each at HTTP 404."
        PRD §2.7: "5. Existence of foreign keys supplied in the request body
        (`door_style_id`, `finish_id`, `order_line_id`, `assembly_line_id`,
        `station_id`, `sheet_component_id`, `order_id`, `original_order_line_id`),
        each yielding the matching not-found error from the same catalogue."

        Design: Corner/errors/route_not_found_on_assign
        """
        dealer = get_success_data(
            api.create_dealer(
                create_dealer_payload(dealer_code="DL1", price_level="L1", credit_limit_cents=1000000),
                plant_admin_headers,
            )
        )
        resp = api.assign_order_to_route(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            {
                "order_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                "expected_order_version": dealer["version"],
            },
            SHIPPING,
        )
        # Path ids are validated left to right before body foreign keys, so the
        # unknown route id wins over the unknown order id.
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_FOUND)
