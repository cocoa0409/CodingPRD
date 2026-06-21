"""Calculation correctness: settlement variance, cash-ledger input filtering, 1099 constants.

Corner queue: calculations section instances.
"""
from test_helpers import validate_success
from test_helpers.fixtures import (
    publish_price,
    register_seller,
    stage_container,
    open_ticket,
    add_line,
    create_released_ticket,
    dispatch_container,
    WM, PC, YM, SA,
)
from test_helpers.api_client import api_client


def test_settlement_variance_unfavorable_negative(api):
    """PRD §3.7: "The system records the `settlement_variance_cents` as the
    `final_settlement_cents` minus the frozen `expected_settlement_cents` — a plain
    integer subtraction, positive when the actual exceeds the estimate (favorable to
    the yard) and negative when it falls short (unfavorable)."

    Two CU lines (10.1, 20.1 @ mill 410) -> expected 12382; final 11000 -> variance -1382.

    Design: Corner/calculations/settlement_variance_unfavorable_negative
    """
    publish_price("CU_BARE_BRIGHT", "NON_FERROUS", spot=375, mill=410)
    seller = register_seller(legal_name="Var Co", id_type="STATE_ID", id_number="SID-VAR")
    container = stage_container("NON_FERROUS", capacity_lb=100000)
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    add_line(ticket["id"], "CU_BARE_BRIGHT", 10.1)
    add_line(ticket["id"], "CU_BARE_BRIGHT", 20.1)
    validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 200}, WM))
    validate_success(api.release_ticket(ticket["id"], {"container_id": container["id"]}, WM))
    dispatch_container(container["id"])
    ship = validate_success(api.create_mill_shipment({"container_id": container["id"]}, YM), 201)
    assert ship["expected_settlement_cents"] == 12382, \
        f"expected 12382, got {ship['expected_settlement_cents']}"
    data = validate_success(api.settle_mill_shipment(ship["id"], {"final_settlement_cents": 11000}, SA))
    assert data["settlement_variance_cents"] == -1382, \
        f"expected variance -1382, got {data['settlement_variance_cents']}"
    assert data["status"] == "SETTLED", f"expected SETTLED, got {data['status']}"


def test_check_payout_does_not_increment_cash_ledger(api):
    """PRD §3.5: "A `CHECK` payout never touches the cumulative cash ledger and
    always leaves `form_1099_issued` false."

    A CHECK payout of 1100c settles but leaves ytd_cash_paid_cents 0.

    Design: Corner/calculations/check_payout_does_not_increment_cash_ledger
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="Check Co", id_type="STATE_ID", id_number="SID-CK")
    built = create_released_ticket(
        grade_code="SHRED_STEEL", category="FERROUS", spot=11, mill=14,
        weight_lb=100, capacity_lb=5000, seller_id=seller["id"],
    )
    payout = validate_success(
        api.create_payout({"ticket_id": built["ticket"]["id"], "method": "CHECK"}, PC), 201
    )
    settled = validate_success(api.settle_payout(payout["id"], PC))
    assert settled["status"] == "SETTLED"
    assert settled["form_1099_issued"] is False, \
        f"CHECK must leave form_1099_issued False, got {settled['form_1099_issued']}"
    seller_after = validate_success(api.get_seller(seller["id"], WM))
    assert seller_after["ytd_cash_paid_cents"] == 0, \
        f"CHECK must not move the cash ledger, got {seller_after['ytd_cash_paid_cents']}"


def test_tin_threshold_just_below_60000_no_1099(api):
    """PRD §3.5: "The boundary is inclusive: a cumulative post-increment total of
    exactly 60000 cents triggers the requirement, while 59999 cents does not."

    A CASH payout of exactly 59999c leaves requires_1099 false.

    Design: Corner/calculations/tin_threshold_just_below_60000_no_1099
    """
    publish_price("ODD_GRADE", "NON_FERROUS", spot=59999, mill=60000)
    seller = register_seller(legal_name="Below Co", id_type="STATE_ID",
                             id_number="SID-BLW", tin="55-5555555")
    built = create_released_ticket(
        grade_code="ODD_GRADE", category="NON_FERROUS", spot=59999, mill=60000,
        weight_lb=1, capacity_lb=5000, seller_id=seller["id"],
    )
    payout = validate_success(
        api.create_payout({"ticket_id": built["ticket"]["id"], "method": "CASH"}, PC), 201
    )
    settled = validate_success(api.settle_payout(payout["id"], PC))
    seller_after = validate_success(api.get_seller(seller["id"], WM))
    assert seller_after["ytd_cash_paid_cents"] == 59999, \
        f"expected ytd 59999, got {seller_after['ytd_cash_paid_cents']}"
    assert seller_after["requires_1099"] is False, \
        f"59999 must not trigger requires_1099, got {seller_after['requires_1099']}"
    assert settled["form_1099_issued"] is False


def test_cumulative_cash_two_payouts_crosses_threshold(api):
    """PRD §3.5: "When `method` is `CASH`, the seller's `ytd_cash_paid_cents` ... is
    increased by the payout's `amount_cents`. After that increment, if the seller's
    `ytd_cash_paid_cents` is at or above the cumulative cash threshold of $600.00
    (that is, 60000 cents), the seller's `requires_1099` flag is set true."

    35000c then 30000c accumulate to 65000c; requires_1099 flips true on the second settle.

    Design: Corner/calculations/cumulative_cash_two_payouts_crosses_threshold
    """
    publish_price("BRASS", "NON_FERROUS", spot=100, mill=110)
    seller = register_seller(legal_name="Cum Co", id_type="STATE_ID",
                             id_number="SID-CUM", tin="66-6666666")
    container = stage_container("NON_FERROUS", capacity_lb=100000)
    # First payout: 350 lb @ 100 = 35000c.
    built1 = create_released_ticket(
        grade_code="BRASS", category="NON_FERROUS", spot=100, mill=110,
        weight_lb=350, capacity_lb=100000, seller_id=seller["id"],
        container_id=container["id"],
    )
    p1 = validate_success(
        api.create_payout({"ticket_id": built1["ticket"]["id"], "method": "CASH"}, PC), 201
    )
    validate_success(api.settle_payout(p1["id"], PC))
    # Second payout: 300 lb @ 100 = 30000c -> cumulative 65000c.
    built2 = create_released_ticket(
        grade_code="BRASS", category="NON_FERROUS", spot=100, mill=110,
        weight_lb=300, capacity_lb=100000, seller_id=seller["id"],
        container_id=container["id"],
    )
    p2 = validate_success(
        api.create_payout({"ticket_id": built2["ticket"]["id"], "method": "CASH"}, PC), 201
    )
    settled2 = validate_success(api.settle_payout(p2["id"], PC))
    seller_after = validate_success(api.get_seller(seller["id"], WM))
    assert seller_after["ytd_cash_paid_cents"] == 65000, \
        f"expected cumulative 65000, got {seller_after['ytd_cash_paid_cents']}"
    assert seller_after["requires_1099"] is True, \
        f"requires_1099 must flip true at 65000, got {seller_after['requires_1099']}"
    assert settled2["form_1099_issued"] is True, \
        f"second payout form_1099_issued must be True, got {settled2['form_1099_issued']}"
