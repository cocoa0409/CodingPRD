"""Substitute proposals and contractor decisions on backordered lines (PRD §2.8, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_submitted_order,
    get_order_line,
    get_stock_row,
    make_account,
    make_branch,
    make_contractor_headers,
    make_product,
    make_stock,
    receive_stock,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["sales_headers"]


def _substitute_world(stock_substitute=5):
    """Branch + P1 (group G1, no stock) + PS1 (group G1, stocked) + GOLD account
    + a submitted order whose P1 x2 line is BACKORDERED.

    Returns (branch, p1, ps1, account, order, line_id).
    """
    branch = make_branch()
    p1 = make_product(sku="P1", substitute_group="G1")
    ps1 = make_product(sku="PS1", description="Alt pipe", list_price_cents=8000,
                       cost_cents=4000, cubes_per_unit=10, substitute_group="G1")
    account = make_account()
    make_stock(branch["id"], p1["id"], 0)
    make_stock(branch["id"], ps1["id"], stock_substitute)
    order, line_ids = create_submitted_order(account["id"], branch["id"], [(p1["id"], 2)])
    return branch, p1, ps1, account, order, line_ids[0]


class TestSubstituteEligibility:
    def test_substitute_group_mismatch_rejected(self, api, sales_headers):
        """PRD §3.7: "The substitute must share the original product's non-null
        `substitute_group`; a mismatch is rejected with
        `ERR_SUBSTITUTE_GROUP_MISMATCH`."

        The original line's product is in group G1; the proposed product is in
        group G2, so the proposal is refused and the line stays NONE.

        Design: Corner/validations/substitute_group_mismatch_rejected
        """
        branch = make_branch()
        p1 = make_product(sku="P1", substitute_group="G1")
        px = make_product(sku="PX", description="Other valve", category="VALVE",
                          list_price_cents=9000, cost_cents=4000, cubes_per_unit=5,
                          substitute_group="G2")
        account = make_account()
        make_stock(branch["id"], p1["id"], 0)
        order, line_ids = create_submitted_order(account["id"], branch["id"], [(p1["id"], 2)])

        res = api.propose_substitute(line_ids[0], {"substitute_product_id": px["id"]}, sales_headers)
        validate_error(res, ApiErrorId.ERR_SUBSTITUTE_GROUP_MISMATCH)
        line = get_order_line(line_ids[0], order["id"])
        assert line["substitute_status"] == "NONE"


class TestSubstituteDecision:
    def test_occ_stale_substitute_decision_rejected(self, api):
        """PRD §2.8: "Deciding a proposed substitute on an order line requires
        `expected_order_line_version` matching the line's current `version`. A
        mismatch is rejected with `ERR_STALE_LINE_VERSION` (HTTP 412), because a
        prior decision or a backorder-allocation event has already legitimately
        moved the line, and a stale expectation carries no authority over its
        current state."

        The proposal itself advanced the line's version, so the pre-proposal
        version is stale; the rejection changes nothing.

        Design: Corner/cross_cutting_layers/occ_stale_substitute_decision_rejected
        """
        _, p1, ps1, account, order, line_id = _substitute_world()
        proposed = validate_success(api.propose_substitute(
            line_id, {"substitute_product_id": ps1["id"]}, SALES
        ))
        assert proposed["substitute_status"] == "PROPOSED"

        res = api.substitute_decision(
            line_id,
            {"decision": "APPROVE", "expected_order_line_version": proposed["version"] - 1},
            make_contractor_headers(account["id"]),
        )
        validate_error(res, ApiErrorId.ERR_STALE_LINE_VERSION)
        line = get_order_line(line_id, order["id"])
        assert line["substitute_status"] == "PROPOSED"
        assert line["product_id"] == p1["id"]

    def test_substitute_approve_swaps_and_reallocates(self, api, sales_headers):
        """PRD §3.7: "An `APPROVE` decision moves `substitute_status` from
        `PROPOSED` to `APPROVED`: the line's `product_id` is swapped to the
        proposed product, `proposed_substitute_product_id` is cleared, the
        `unit_price_cents` is re-resolved through the counter price rules of
        §3.6 (quote-locked lines never reach this path), the reservation is
        retried against the substitute product's stock — which may land the line
        `ALLOCATED` through the same waterfall mechanics — and line and order
        totals are recomputed."

        PS1 list 8000 with GOLD 10% re-resolves to 7200; the substitute's stock
        covers the line, which lands ALLOCATED and waves the order to PICKING.

        Design: Corner/cross_cutting_layers/substitute_approve_swaps_and_reallocates
        """
        _, _, ps1, account, order, line_id = _substitute_world()
        proposed = validate_success(api.propose_substitute(
            line_id, {"substitute_product_id": ps1["id"]}, SALES
        ))
        decided = validate_success(api.substitute_decision(
            line_id,
            {"decision": "APPROVE", "expected_order_line_version": proposed["version"]},
            make_contractor_headers(account["id"]),
        ))
        assert decided["product_id"] == ps1["id"]
        assert decided["proposed_substitute_product_id"] is None
        assert decided["substitute_status"] == "APPROVED"
        assert decided["unit_price_cents"] == 7200, (
            f"GOLD tier on list 8000 must re-resolve to 7200, got {decided['unit_price_cents']}"
        )
        assert decided["status"] == "ALLOCATED" and decided["qty_allocated"] == 2

        order_after = validate_success(api.get_order(order["id"], sales_headers))
        assert order_after["fulfillment_status"] == "PICKING"
        assert order_after["total_cents"] == 16900, (
            f"2 x 7200 = 14400 + 2500 freight, got {order_after['total_cents']}"
        )
        row = get_stock_row(order_after["branch_id"], ps1["id"])
        assert (row["reserved"], row["available"]) == (2, 3)

    def test_substitute_reject_returns_line_to_backorder_pool(self, api):
        """PRD §3.7: "A `REJECT` decision moves `substitute_status` to
        `REJECTED`, clears `proposed_substitute_product_id`, and leaves the line
        in the backorder pool at its original queue position, its `created_at`
        unchanged."

        After the rejection the line still waits on the ORIGINAL product, and a
        receipt of that product fills it.

        Design: Corner/cross_cutting_layers/substitute_reject_returns_line_to_backorder_pool
        """
        branch, p1, ps1, account, order, line_id = _substitute_world()
        proposed = validate_success(api.propose_substitute(
            line_id, {"substitute_product_id": ps1["id"]}, SALES
        ))
        rejected = validate_success(api.substitute_decision(
            line_id,
            {"decision": "REJECT", "expected_order_line_version": proposed["version"]},
            make_contractor_headers(account["id"]),
        ))
        assert rejected["substitute_status"] == "REJECTED"
        assert rejected["proposed_substitute_product_id"] is None
        assert rejected["product_id"] == p1["id"]
        assert rejected["status"] == "BACKORDERED"

        receive_stock(branch["id"], p1["id"], 2, 5000)
        line = get_order_line(line_id, order["id"])
        assert line["status"] == "ALLOCATED" and line["qty_allocated"] == 2, (
            "the rejected line keeps its backorder pool position and fills from the original product"
        )
