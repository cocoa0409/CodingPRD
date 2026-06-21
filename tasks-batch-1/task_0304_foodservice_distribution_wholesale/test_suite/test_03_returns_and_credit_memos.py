"""Returns: credit computation (overage fee vs fee-free), approve/reject fork,
the issue-credit transitive cascade, and the return-exceeds-delivered guard.

Covers difficulty queue dual_variant_calc (return instance), non_linear_state_machine
(return fork), transitive_cascade (depth-3), plus corner validations.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_catalog, setup_base, create_product, add_price_tier, receive_lot,
    create_customer, create_submitted_order, create_approved_order, create_delivered_order,
    setup_delivered_line_for_return, request_return, get_customer_version,
    approve_credit_payload, pod_payload, shipment_for_order,
    TEST_USERS,
)

CREDIT = TEST_USERS["credit_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
WAREHOUSE = TEST_USERS["warehouse_op_headers"]


def test_overage_return_withholds_fee_vs_damage_full_credit(api):
    """PRD §3.7: "A restocking fee applies only to an `OVERAGE` return, where the customer
    over-ordered: in that case `restock_fee_cents` is fifteen percent of the returned
    goods value, rounded half up to a whole cent."
    PRD §3.7: "For a `DAMAGED`, `QUALITY`, or `WRONG_ITEM` return there is no fee and
    `restock_fee_cents` is zero."
    PRD §3.7: "The `credit_amount_cents` is the returned goods value minus
    `restock_fee_cents`."

    Delivered SPLIT-14 line (extended 2800, allocated 14): per-split value
    round(2800/14)=200. OVERAGE 4 -> goods 800, fee round(800*0.15)=120, credit 680.
    DAMAGED 4 -> goods 800, fee 0, credit 800. Same quantity, two credit results.

    Design: Difficulty/dual_variant_calc/return_credit_overage_fee_vs_damage_full
    """
    d = setup_delivered_line_for_return(splits_per_case=12, tiers=((1, 2400),),
                                        on_hand_splits=14, uom="SPLIT", ordered_qty=14)
    cust, order, line = d["customer"], d["order"], d["line"]

    ret_over = request_return(cust["id"], order["id"], line["id"], "OVERAGE", 4)
    ret_dmg = request_return(cust["id"], order["id"], line["id"], "DAMAGED", 4)

    over = validate_success(api.approve_return(ret_over["id"], CREDIT), 200)
    dmg = validate_success(api.approve_return(ret_dmg["id"], CREDIT), 200)

    assert over["restock_fee_cents"] == 120
    assert over["credit_amount_cents"] == 680
    assert dmg["restock_fee_cents"] == 0
    assert dmg["credit_amount_cents"] == 800


def test_return_credit_quality_reason_is_fee_free(api):
    """PRD §3.7: "For a `DAMAGED`, `QUALITY`, or `WRONG_ITEM` return there is no fee and
    `restock_fee_cents` is zero."
    PRD §3.7: "The per-split delivered value is the line's `extended_price_cents` divided
    by its `allocated_splits`, rounded half up to a whole cent; the returned goods value is
    that per-split value times `return_splits`."

    Second test of the dual-variant return-credit rule via the QUALITY (fee-free) branch:
    a QUALITY 4 return on the 2800/14 line credits the full 800 with zero fee.

    Design: Difficulty/dual_variant_calc/return_credit_overage_fee_vs_damage_full
    """
    d = setup_delivered_line_for_return(splits_per_case=12, tiers=((1, 2400),),
                                        on_hand_splits=14, uom="SPLIT", ordered_qty=14)
    cust, order, line = d["customer"], d["order"], d["line"]

    ret = request_return(cust["id"], order["id"], line["id"], "QUALITY", 4)
    approved = validate_success(api.approve_return(ret["id"], CREDIT), 200)
    assert approved["restock_fee_cents"] == 0
    assert approved["credit_amount_cents"] == 800


def test_return_fork_approve_computes_credit_reject_does_not(api):
    """PRD §3.7: "A `CreditManager` approves a requested return, moving `status` from
    `REQUESTED` to `APPROVED`."
    PRD §3.7: "A `CreditManager` may instead reject a requested return, moving `status`
    from `REQUESTED` to `REJECTED` (a terminal state)."

    From REQUESTED the Return forks: approve runs return_credit (DAMAGED 2 on a 2800/14
    line -> credit 400) while reject leaves status REJECTED with no credit.

    Design: Difficulty/non_linear_state_machine/return_branching_fork_approve_vs_reject
    """
    d = setup_delivered_line_for_return(splits_per_case=12, tiers=((1, 2400),),
                                        on_hand_splits=14, uom="SPLIT", ordered_qty=14)
    cust, order, line = d["customer"], d["order"], d["line"]

    ret_a = request_return(cust["id"], order["id"], line["id"], "DAMAGED", 2)
    ret_b = request_return(cust["id"], order["id"], line["id"], "DAMAGED", 2)

    approved = validate_success(api.approve_return(ret_a["id"], CREDIT), 200)
    rejected = validate_success(api.reject_return(ret_b["id"], CREDIT), 200)

    assert approved["status"] == "APPROVED"
    assert approved["credit_amount_cents"] == 400
    assert rejected["status"] == "REJECTED"
    assert rejected["credit_amount_cents"] == 0


def test_return_fork_second_pair_approve_and_reject(api):
    """PRD §3.7: "On approval the system computes the credit."
    PRD §3.7: "A `CreditManager` may instead reject a requested return, moving `status`
    from `REQUESTED` to `REJECTED` (a terminal state)."

    Second test of the approve-vs-reject fork with a different return quantity: DAMAGED 5
    approved (credit 1000 on a 2800/14 line) versus DAMAGED 5 rejected (no credit).

    Design: Difficulty/non_linear_state_machine/return_branching_fork_approve_vs_reject
    """
    d = setup_delivered_line_for_return(splits_per_case=12, tiers=((1, 2400),),
                                        on_hand_splits=14, uom="SPLIT", ordered_qty=14)
    cust, order, line = d["customer"], d["order"], d["line"]

    ret_a = request_return(cust["id"], order["id"], line["id"], "DAMAGED", 5)
    ret_b = request_return(cust["id"], order["id"], line["id"], "DAMAGED", 5)

    approved = validate_success(api.approve_return(ret_a["id"], CREDIT), 200)
    rejected = validate_success(api.reject_return(ret_b["id"], CREDIT), 200)

    assert approved["status"] == "APPROVED"
    assert approved["credit_amount_cents"] == 1000
    assert rejected["status"] == "REJECTED"
    assert rejected["credit_amount_cents"] == 0


def test_issue_credit_cascades_return_to_customer_to_held_order(api):
    """PRD §3.7: "Issuing the credit decreases the customer's `ar_balance_cents` by the
    return's `credit_amount_cents` — the conserved-quantity compensation against the
    delivered order's original accounts-receivable debit."
    PRD §3.7: "If that decrease brings the customer's `ar_balance_cents` to at or below its
    `credit_limit_cents` while the customer's `ar_status` is `CREDIT_HOLD`, the customer is
    returned to `ACTIVE`, and then each of that customer's `ON_HOLD` orders whose
    `order_total_cents` now fits under the remaining headroom is cascaded from `ON_HOLD` to
    `PENDING`."

    Depth-3 cascade: O1 delivered (ar 11000, limit 12000); O2 (6600) ON_HOLD; manual hold.
    OVERAGE 36 return on O1 -> credit 5600; issue-credit drops ar to 5400, releases the
    hold (ACTIVE), and returns O2 (6600 <= 12000-5400) to PENDING.

    Design: Difficulty/transitive_cascade/issue_credit_cascade_return_to_customer_to_order_depth3
    """
    base = setup_base()
    dist_id, wh_id, route_id = base["distributor"]["id"], base["warehouse"]["id"], base["route"]["id"]
    prod = create_product(dist_id, splits_per_case=12, split_allowed=True, case_cost_cents=1000)
    add_price_tier(prod["id"], 1, 2200)
    receive_lot(prod["id"], wh_id, 120)
    cust = create_customer(dist_id, route_id, credit_limit_cents=12000)

    # O1: 5 cases @ 2200 = 11000, delivered.
    cust_v0 = get_customer_version(cust["id"])
    o1, o1_lines, o1_ship = create_delivered_order(
        cust["id"], prod["id"], lines=[(prod["id"], "CASE", 5)],
        expected_customer_version=cust_v0, pod_signature="Sig1")
    o1_line = o1_lines[0]
    assert o1["order_total_cents"] == 11000

    # O2: 3 cases = 6600, submitted then over-limit approve -> ON_HOLD.
    cust_v1 = get_customer_version(cust["id"])
    o2, _ = create_submitted_order(cust["id"], prod["id"],
                                   lines=[(prod["id"], "CASE", 3)],
                                   delivery_date="2026-06-24T00:00:00Z")
    o2_approved = validate_success(
        api.approve_credit(o2["id"], approve_credit_payload(cust_v1), CREDIT), 200)
    assert o2_approved["credit_status"] == "ON_HOLD"

    # Manual hold so ar_status is CREDIT_HOLD when issue-credit fires.
    validate_success(api.credit_hold(cust["id"], CREDIT), 200)

    ret = request_return(cust["id"], o1["id"], o1_line["id"], "OVERAGE", 36, headers=CREDIT)
    approved = validate_success(api.approve_return(ret["id"], CREDIT), 200)
    assert approved["credit_amount_cents"] == 5600

    credited = validate_success(api.issue_credit(ret["id"], CREDIT), 200)
    assert credited["status"] == "CREDITED"
    assert credited["credit_amount_cents"] == 5600

    cust_after = validate_success(api.get_customer(cust["id"], SALES), 200)
    assert cust_after["ar_balance_cents"] == 5400
    assert cust_after["ar_status"] == "ACTIVE"

    o2_after = validate_success(api.get_order(o2["id"], SALES), 200)
    assert o2_after["credit_status"] == "PENDING"


def test_issue_credit_reduces_ar_balance_simple(api):
    """PRD §3.7: "Issuing the credit decreases the customer's `ar_balance_cents` by the
    return's `credit_amount_cents` — the conserved-quantity compensation against the
    delivered order's original accounts-receivable debit."

    Second test of the issue-credit cascade focusing on link-1 (AR reduction): a delivered
    CASE-1 order (12 splits, 2400) with a DAMAGED 12 return (credit 2400) returns AR to 0
    when the credit memo is issued.

    Design: Difficulty/transitive_cascade/issue_credit_cascade_return_to_customer_to_order_depth3
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order, lines, ship = create_delivered_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "CASE", 1)])
    line = lines[0]

    cust_before = validate_success(api.get_customer(cat["customer"]["id"], SALES), 200)
    assert cust_before["ar_balance_cents"] == 2400

    ret = request_return(cat["customer"]["id"], order["id"], line["id"], "DAMAGED", 12)
    approved = validate_success(api.approve_return(ret["id"], CREDIT), 200)
    assert approved["credit_amount_cents"] == 2400

    validate_success(api.issue_credit(ret["id"], CREDIT), 200)
    cust_after = validate_success(api.get_customer(cat["customer"]["id"], SALES), 200)
    assert cust_after["ar_balance_cents"] == 0


def test_return_exceeds_delivered_quantity_rejected(api):
    """PRD §3.7: "that `return_splits` does not exceed the referenced line's delivered
    `allocated_splits`, or `ERR_RETURN_EXCEEDS_DELIVERED`."

    A return for 20 splits against a line that delivered only 12 (allocated_splits 12) is
    rejected at approve with ERR_RETURN_EXCEEDS_DELIVERED (422).

    Design: Corner/validations/return_exceeds_delivered_quantity_rejected
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order, lines, ship = create_delivered_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "CASE", 1)])
    line = lines[0]

    ret = request_return(cat["customer"]["id"], order["id"], line["id"], "DAMAGED", 20)
    res = api.approve_return(ret["id"], CREDIT)
    validate_error(res, "ERR_RETURN_EXCEEDS_DELIVERED")
