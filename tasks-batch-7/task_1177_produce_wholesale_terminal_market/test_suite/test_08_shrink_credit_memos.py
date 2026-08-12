"""Shrink approval cascade, credit-memo amounts, and the void compensating action
(PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_shrink,
    assert_payable_invariant,
    create_approved_shrink,
    create_shrink,
    get_lot,
    get_shipper,
    get_success_data,
    list_credit_memos,
    setup_accepted_lot,
    setup_lot_with_certified_defect,
    validate_error,
)
from test_helpers import ADMIN_HEADERS, BILLING_HEADERS, RECEIVER_HEADERS


def _setup_defected_lot_with_shrink(defect_pct=20, shrink_quantity=10,
                                    reason="DUMP"):
    """Lot 100 @ 10.00 certified PASS with defect -> adjusted cost finalized; a DRAFT
    shrink record ready for approval."""
    base = setup_lot_with_certified_defect(defect_pct=defect_pct, quantity=100,
                                           unit_price=10.00)
    shrink = create_shrink(base["lot"]["id"], quantity=shrink_quantity, reason=reason)
    base["shrink"] = shrink
    return base


def test_shrink_approval_issues_credit_memo(api):
    """PRD §3.8: "Hop one: a `CreditMemo` is created in `ISSUED` status with
    `issued_at` stamped from the logical clock, its `amount_cents` computed as
    `adjusted_cost_cents` multiplied by the shrink `quantity` divided by the lot's
    `quantity_units`, rounded half-up to integer cents, and the shrink record's
    `credit_memo_id` is set to point at it."

    Design: Difficulty/transitive_cascade/shrink_approval_two_hop_credit_cascade
    """
    base = _setup_defected_lot_with_shrink(defect_pct=20, shrink_quantity=10)
    assert base["lot"]["adjusted_cost_cents"] == 85000
    approved = approve_shrink(base["shrink"]["id"])
    assert approved["status"] == "APPROVED"
    assert approved["credit_memo_id"], "approval must link the issued memo"
    memos = list_credit_memos(base["lot"]["id"])
    assert len(memos) == 1
    assert memos[0]["id"] == approved["credit_memo_id"]
    # round_half_up(85000 * 10 / 100) = 8500
    assert memos[0]["amount_cents"] == 8500
    assert memos[0]["status"] == "ISSUED"


def test_shrink_approval_recomputes_payable_and_trust_exposure(api):
    """PRD §3.8: "Hop two: the lot's `dumped_units` increases by the shrink quantity,
    `payable_cents` recomputes as `adjusted_cost_cents` minus the sum of `ISSUED`
    memos on the lot, `available_units` recomputes, and the shipper's
    `trust_exposure_cents` is recomputed."

    Design: Difficulty/transitive_cascade/shrink_approval_two_hop_credit_cascade
    """
    base = _setup_defected_lot_with_shrink(defect_pct=20, shrink_quantity=10)
    approve_shrink(base["shrink"]["id"])
    lot = get_lot(base["lot"]["id"])
    assert lot["dumped_units"] == 10
    assert lot["available_units"] == 90
    assert lot["payable_cents"] == 76500, "85000 - 8500 memo"
    shipper = get_shipper(base["shipper"]["id"])
    assert shipper["trust_exposure_cents"] == 76500, (
        "the derived shipper aggregate follows the cascade")


def test_payable_plus_issued_memos_equals_adjusted_cost(api):
    """PRD §3.8: "The reconciling invariant, maintained after every operation in this
    section, is that for any non-`REJECTED` lot, `payable_cents` plus the sum of its
    `ISSUED` memo amounts equals `adjusted_cost_cents`."

    Design: Difficulty/compensating_invariant/shrink_void_conserves_shipper_consideration
    """
    base = _setup_defected_lot_with_shrink(defect_pct=20, shrink_quantity=10)
    approve_shrink(base["shrink"]["id"])
    lot = get_lot(base["lot"]["id"])
    memos = list_credit_memos(base["lot"]["id"])
    issued_total = sum(m["amount_cents"] for m in memos if m["status"] == "ISSUED")
    # Mid-flight: 76500 payable + 8500 issued == 85000 adjusted.
    assert_payable_invariant(lot, issued_total)
    assert lot["payable_cents"] == 76500 and issued_total == 8500


def test_voiding_memo_restores_payable_exactly(api):
    """PRD §3.8: "A `BillingClerk` may void an `ISSUED` memo. Voiding stamps
    `voided_at`, flips the memo to `VOID`, increments the memo's `version`,
    recomputes the lot's `payable_cents` against the remaining `ISSUED` memos, and
    recomputes the shipper's `trust_exposure_cents`."
    PRD §3.8: "approving a shrink and then voiding its memo restores `payable_cents`
    exactly"

    Design: Difficulty/compensating_invariant/shrink_void_conserves_shipper_consideration
    """
    base = _setup_defected_lot_with_shrink(defect_pct=20, shrink_quantity=10)
    approved = approve_shrink(base["shrink"]["id"])
    memo_id = approved["credit_memo_id"]

    voided = get_success_data(api_client.void_credit_memo(memo_id, BILLING_HEADERS))
    assert voided["status"] == "VOID"
    lot = get_lot(base["lot"]["id"])
    assert lot["payable_cents"] == 85000, "void restores payable exactly, no drift"
    assert lot["adjusted_cost_cents"] == 85000, "the memo lifecycle never mutates cost"


def test_credit_memo_amount_prorated_from_adjusted_cost(api):
    """PRD §3.8: "its `amount_cents` computed as `adjusted_cost_cents` multiplied by
    the shrink `quantity` divided by the lot's `quantity_units`, rounded half-up to
    integer cents"

    Design: Corner/calculations/credit_memo_amount_prorated_from_adjusted_cost
    """
    base = setup_accepted_lot(defect_pct=0, quantity=100, unit_price=10.00)
    assert base["lot"]["adjusted_cost_cents"] == 100000
    approved = create_approved_shrink(base["lot"]["id"], quantity=3, reason="TRIM")
    memos = list_credit_memos(base["lot"]["id"])
    assert len(memos) == 1
    assert memos[0]["id"] == approved["credit_memo_id"]
    # round_half_up(100000 * 3 / 100) = 3000
    assert memos[0]["amount_cents"] == 3000
    assert memos[0]["status"] == "ISSUED"
    lot = get_lot(base["lot"]["id"])
    assert lot["payable_cents"] == 97000
    assert lot["dumped_units"] == 3


def test_receiver_cannot_approve_own_shrink_returns_forbidden(api):
    """PRD §2.1: "The `Receiver` files shrink records but may not approve them; only
    `MarketAdmin` approves."
    PRD §2.1: "If the role is recognized but is not authorized for the endpoint, or if
    a `CustomerRep` attempts to touch a resource owned by another customer, the
    request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/receiver_cannot_approve_own_shrink_returns_forbidden
    """
    base = setup_accepted_lot(defect_pct=0)
    shrink = create_shrink(base["lot"]["id"], quantity=10, reason="DUMP")

    denied = api_client.approve_shrink_record(shrink["id"], RECEIVER_HEADERS)
    validate_error(denied, ApiErrorId.ERR_FORBIDDEN)
    memos = list_credit_memos(base["lot"]["id"])
    assert memos == [], "no cascade may fire on a forbidden approve"

    approved = api_client.approve_shrink_record(shrink["id"], ADMIN_HEADERS)
    data = get_success_data(approved)
    assert data["status"] == "APPROVED"
    assert data["credit_memo_id"], "MarketAdmin approval issues the memo"
