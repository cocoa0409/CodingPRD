"""Plant warranty claims: payout floor, eligibility, terminal lockdown, expiry.

Difficulty: warranty_payout_single_final_floor.
Corner: warranty_claim_not_offered_when_warranty_days_zero, deny_already_denied_claim_rejected,
error_warranty_expired_on_approve.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    factories as F, fixtures as X,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INV = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["sales_clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: warranty_payout_single_final_floor
# ---------------------------------------------------------------------------
def _fulfilled_promo_line_with_refund_claim():
    """ACTIVE 15% LIVE_PLANT promo; LIVE_PLANT @ 999 warranty 60/100%; order one
    line qty=2 confirmed/paid/allocated/fulfilled; a REFUND claim filed for qty=2.
    Returns (claim_id, line_id, account_id)."""
    X.set_clock("2026-04-10T09:00:00Z")
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_live_plant(nursery["id"], sku="PL-W", name="Oak",
                                  hardiness_min_zone=1, hardiness_max_zone=13,
                                  unit_price_cents=999, warranty_days=60, warranty_pct=100)
    X.create_active_promotion(nursery["id"], name="Spring Days", category_scope="LIVE_PLANT",
                              discount_pct=15, starts_at="2026-04-01T00:00:00Z", ends_at="2026-05-01T00:00:00Z")
    lot = X.create_released_lot(product["id"], received_qty=10, unit_cost_cents=400)
    order = X.create_order(account["id"])
    line = X.add_line(order["id"], product["id"], qty=2)
    c = X.confirm(order["id"], order["version"])
    a = X.allocate(order["id"], c["version"])
    p = X.pay(order["id"], a["version"])
    X.fulfill(order["id"], p["version"])
    claim = X.file_claim(line["id"], claim_qty=2, resolution="REFUND")
    return claim["id"], line["id"], account["id"]


def test_refund_claim_payout_uses_single_final_floor(api):
    """PRD §3.10: "it takes the claimed line's promo-adjusted unit value as the
    line's net amount divided by the line quantity (an exact division kept rational),
    multiplies by the claim quantity and by the product's warranty percentage,
    divides by 100, and floors the single final result to whole cents".

    Design: Difficulty/combinatorial_formula/warranty_payout_single_final_floor
    """
    claim_id, _line_id, _acc = _fulfilled_promo_line_with_refund_claim()
    approved = validate_success(api.approve_warranty_claim(claim_id, CLERK))
    assert approved["status"] == "APPROVED"
    # floor(2 * (1699/2) * 100 / 100) = 1699; floor-per-unit-first would wrongly give 1698.
    assert approved["payout_cents"] == 1699


def test_promo_line_net_feeds_payout(api):
    """PRD §3.3: "Each line's net is then its quantity times its unit price, minus
    its line discount."

    Design: Difficulty/combinatorial_formula/warranty_payout_single_final_floor
    """
    _claim_id, line_id, _acc = _fulfilled_promo_line_with_refund_claim()
    line = validate_success(api.get_order_line(line_id, CLERK))
    # gross 2*999=1998; promo floor(1998*0.15)=299; line_net = 1998-299 = 1699.
    assert line["line_net_cents"] == 1699


# ---------------------------------------------------------------------------
# Corner: warranty eligibility / lockdown / expiry
# ---------------------------------------------------------------------------
def test_claim_on_zero_warranty_product_not_offered(api):
    """PRD §3.10: "A claim is eligible only if the product actually offers a
    guarantee — its `warranty_days` must be greater than 0, otherwise the claim is
    rejected with `ERR_WARRANTY_NOT_OFFERED`".

    Design: Corner/validations/warranty_claim_not_offered_when_warranty_days_zero
    """
    X.set_clock("2026-04-01T09:00:00Z")
    ctx = X.setup_fulfilled_order(unit_price_cents=800, qty=2,
                                  product_overrides={"sku": "DG-NW", "name": "Pebbles"})
    resp = api.create_warranty_claim(ctx["line"]["id"],
                                     F.create_warranty_claim_payload(claim_qty=1, resolution="REFUND"), CLERK)
    validate_error(resp, ApiErrorId.ERR_WARRANTY_NOT_OFFERED.value)


def test_deny_already_denied_claim_rejected(api):
    """PRD §3.10: "Denying a claim moves it from `FILED` to the terminal `DENIED`
    status, again requiring the claim to be in `FILED` status (otherwise
    `ERR_CLAIM_NOT_FILED`)".

    Design: Corner/state_machines/deny_already_denied_claim_rejected
    """
    X.set_clock("2026-04-01T09:00:00Z")
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_live_plant(nursery["id"], sku="PL-D", name="Daisy",
                                  hardiness_min_zone=3, hardiness_max_zone=9,
                                  unit_price_cents=1000, warranty_days=60, warranty_pct=100)
    X.create_released_lot(product["id"], received_qty=4, unit_cost_cents=300)
    order = X.create_order(account["id"])
    line = X.add_line(order["id"], product["id"], qty=2)
    c = X.confirm(order["id"], order["version"])
    a = X.allocate(order["id"], c["version"])
    p = X.pay(order["id"], a["version"])
    X.fulfill(order["id"], p["version"])
    claim = X.file_claim(line["id"], claim_qty=1, resolution="REPLACEMENT")
    validate_success(api.deny_warranty_claim(claim["id"], CLERK))
    resp = api.deny_warranty_claim(claim["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FILED.value)


def test_approve_claim_after_warranty_window_expired(api):
    """PRD §3.10: "and only if it is filed within `warranty_days` days of the parent
    order's fulfillment timestamp, otherwise `ERR_WARRANTY_EXPIRED`."
    PRD §3.10: "it requires the claim to be in `FILED` status (otherwise
    `ERR_CLAIM_NOT_FILED`) and the claim to still be within the product's warranty
    window measured from the parent order's fulfillment time (otherwise
    `ERR_WARRANTY_EXPIRED`)."

    Design: Corner/errors/error_warranty_expired_on_approve
    """
    X.set_clock("2026-04-01T09:00:00Z")
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_live_plant(nursery["id"], sku="PL-EX", name="Lily",
                                  hardiness_min_zone=3, hardiness_max_zone=9,
                                  unit_price_cents=1000, warranty_days=30, warranty_pct=50)
    X.create_released_lot(product["id"], received_qty=4, unit_cost_cents=300)
    order = X.create_order(account["id"])
    line = X.add_line(order["id"], product["id"], qty=1)
    c = X.confirm(order["id"], order["version"])
    a = X.allocate(order["id"], c["version"])
    p = X.pay(order["id"], a["version"])
    X.fulfill(order["id"], p["version"])
    claim = X.file_claim(line["id"], claim_qty=1, resolution="REFUND")
    X.set_clock("2026-06-01T09:00:00Z")  # > 30 days past the 2026-04-01 fulfill
    resp = api.approve_warranty_claim(claim["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED.value)
