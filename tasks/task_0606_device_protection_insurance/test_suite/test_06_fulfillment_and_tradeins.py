"""Replace-branch fulfillment: sweep/non-return fee, trade-in grading/credit/recycle,
the late-credit cascade that reverses the non-return fee, and terminal-state lockdown.

Covers difficulty rule transitive_cascade (credit reverses fee depth 2) and corner
calculations / state_machines / validations instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, SKU_BOOK,
)
from test_helpers import fixtures as fx


# --------------------------------------------------------------------------
# Corner: trade-in grade A credit on book value
# --------------------------------------------------------------------------
def test_trade_in_grade_a_credit_on_book_value(api, admin_headers, logistics_headers):
    """PRD 3.12: "The credit is that basis multiplied by a grade factor and divided by
    10000, rounded half up to whole cents, where the grade factor in basis points is 6000
    for grade `A`, 4000 for grade `B`, 2000 for grade `C`, and 0 for `EWASTE`."
    PRD 3.12: "The basis for the credit is the same depreciated value used by replacement
    value but taken before the plan cap is applied — the greater of the raw depreciated
    figure and the 5000-cent minimum residual floor".

    Design: Corner/calculations/tradein_grade_a_credit_on_book_value
    """
    fx.set_clock()
    base = fx.setup_delivered_exchange(carrier="CA-CN-13")
    ti = validate_success(api.create_trade_in(
        {"advanced_exchange_id": base["exchange"]["id"], "condition_grade": "A"}, logistics_headers), 201)
    graded = validate_success(api.grade_trade_in(ti["id"], logistics_headers))
    # depreciated = 79200; credit = round(79200 * 6000/10000) = 47520
    assert graded["credit_cents"] == 47520, f"expected 47520, got {graded['credit_cents']}"


# --------------------------------------------------------------------------
# Corner: nonreturn fee assessed on sweep
# --------------------------------------------------------------------------
def test_nonreturn_fee_assessed_on_sweep(api, admin_headers, logistics_headers):
    """PRD 3.11: "For each exchange where the current logical clock is strictly past
    `return_due_at` and no trade-in exists for that exchange, the sweep moves the
    exchange to `RETURN_DUE`, assesses the non-return fee".
    PRD 3.11: "the SKU's `msrp_cents` multiplied by 3500 basis points and divided by
    10000 — that is, thirty-five percent of MSRP — rounded half up to whole cents,
    recorded as `nonreturn_fee_cents`."

    Design: Corner/calculations/nonreturn_fee_assessed_on_sweep
    """
    fx.set_clock()
    base = fx.setup_delivered_exchange(carrier="CA-CN-14")
    ax = base["exchange"]
    fx.set_clock("2026-07-15T00:00:00Z")
    validate_success(api.run_return_sweep(admin_headers))
    after = validate_success(api.get_advanced_exchange(ax["id"], logistics_headers))
    assert after["status"] == "RETURN_DUE"
    # round(90000 * 3500/10000) = 31500
    assert after["nonreturn_fee_cents"] == 31500, \
        f"expected 31500, got {after['nonreturn_fee_cents']}"


# --------------------------------------------------------------------------
# transitive_cascade: trade-in credit reverses non-return fee (depth 2)
# --------------------------------------------------------------------------
def test_credit_reverses_nonreturn_fee_and_restores_delivered(api, admin_headers, logistics_headers):
    """PRD 3.12: "As a compensating cascade, if the parent advanced exchange is in
    `RETURN_DUE` status when the credit is applied, the exchange's `nonreturn_fee_cents`
    is reset to zero and the exchange returns to `DELIVERED` status — a late return
    reverses the non-return fee."
    PRD 3.11: "the SKU's `msrp_cents` multiplied by 3500 basis points and divided by
    10000 ... recorded as `nonreturn_fee_cents`."

    Design: Difficulty/transitive_cascade/tradein_credit_reverses_nonreturn_fee_depth2
    """
    fx.set_clock()
    base = fx.setup_delivered_exchange(carrier="CA-DV-8")
    ax = base["exchange"]
    # No trade-in exists yet, so the sweep assesses the non-return fee and moves the
    # exchange to RETURN_DUE; the late trade-in then arrives and is credited.
    fx.set_clock("2026-07-15T00:00:00Z")
    validate_success(api.run_return_sweep(admin_headers))
    swept = validate_success(api.get_advanced_exchange(ax["id"], logistics_headers))
    assert swept["status"] == "RETURN_DUE"
    assert swept["nonreturn_fee_cents"] == 31500, \
        f"fee expected 31500 after sweep, got {swept['nonreturn_fee_cents']}"
    ti = validate_success(api.create_trade_in(
        {"advanced_exchange_id": ax["id"], "condition_grade": "B"}, logistics_headers), 201)
    validate_success(api.grade_trade_in(ti["id"], logistics_headers))
    credited = validate_success(api.credit_trade_in(ti["id"], logistics_headers))
    assert credited["status"] == "CREDITED"
    after = validate_success(api.get_advanced_exchange(ax["id"], logistics_headers))
    assert after["nonreturn_fee_cents"] == 0, "fee must reset to 0 after late credit"
    assert after["status"] == "DELIVERED", "exchange must return to DELIVERED after late credit"


def test_credit_late_trade_in_resets_fee(api, admin_headers, logistics_headers):
    """PRD 3.12: "if the parent advanced exchange is in `RETURN_DUE` status when the
    credit is applied, the exchange's `nonreturn_fee_cents` is reset to zero and the
    exchange returns to `DELIVERED` status".

    Design: Difficulty/transitive_cascade/tradein_credit_reverses_nonreturn_fee_depth2
    """
    fx.set_clock()
    base = fx.setup_delivered_exchange(carrier="CA-DV-8B")
    ax = base["exchange"]
    fx.set_clock("2026-07-15T00:00:00Z")
    validate_success(api.run_return_sweep(admin_headers))
    ti = validate_success(api.create_trade_in(
        {"advanced_exchange_id": ax["id"], "condition_grade": "B"}, logistics_headers), 201)
    validate_success(api.grade_trade_in(ti["id"], logistics_headers))
    credited = validate_success(api.credit_trade_in(ti["id"], logistics_headers))
    assert credited["status"] == "CREDITED"
    after = validate_success(api.get_advanced_exchange(ax["id"], logistics_headers))
    assert after["nonreturn_fee_cents"] == 0
    assert after["status"] == "DELIVERED"


# --------------------------------------------------------------------------
# Corner: e-waste recycle path + credit-on-ewaste mismatch
# --------------------------------------------------------------------------
def test_ewaste_trade_in_recycles_with_zero_credit(api, admin_headers, logistics_headers):
    """PRD 3.12: "the grade factor in basis points is 6000 for grade `A`, 4000 for grade
    `B`, 2000 for grade `C`, and 0 for `EWASTE`."
    PRD 3.12: "Recycling moves the trade-in to `RECYCLED` and is permitted only when the
    `condition_grade` is `EWASTE` ... The e-waste path earns no credit".

    Design: Corner/state_machines/tradein_recycle_ewaste_path
    """
    fx.set_clock()
    base = fx.setup_delivered_exchange(carrier="CA-CN-11")
    ti = validate_success(api.create_trade_in(
        {"advanced_exchange_id": base["exchange"]["id"], "condition_grade": "EWASTE"},
        logistics_headers), 201)
    graded = validate_success(api.grade_trade_in(ti["id"], logistics_headers))
    assert graded["credit_cents"] == 0, f"EWASTE credit must be 0, got {graded['credit_cents']}"
    recycled = validate_success(api.recycle_trade_in(ti["id"], logistics_headers))
    assert recycled["status"] == "RECYCLED"


def test_credit_on_ewaste_grade_rejected(api, admin_headers, logistics_headers):
    """PRD 3.12: "Crediting moves the trade-in to `CREDITED` and is permitted only when
    the `condition_grade` is not `EWASTE`; attempting to credit an `EWASTE` trade-in is
    rejected with `ERR_GRADE_PATH_MISMATCH`."

    Design: Corner/validations/tradein_credit_on_ewaste_returns_grade_mismatch
    """
    fx.set_clock()
    base = fx.setup_delivered_exchange(carrier="CA-CN-19")
    ti = validate_success(api.create_trade_in(
        {"advanced_exchange_id": base["exchange"]["id"], "condition_grade": "EWASTE"},
        logistics_headers), 201)
    validate_success(api.grade_trade_in(ti["id"], logistics_headers))
    resp = api.credit_trade_in(ti["id"], logistics_headers)
    validate_error(resp, ApiErrorId.ERR_GRADE_PATH_MISMATCH.value, 409)


# --------------------------------------------------------------------------
# Corner: terminal-state lockdown (withdraw after fulfilled)
# --------------------------------------------------------------------------
def test_withdraw_fulfilled_claim_rejected(api, admin_headers, adjuster_headers, logistics_headers):
    """PRD 3.9: "On success the repair order moves to `COMPLETED`, the parent claim
    bubbles up from `ROUTED_REPAIR` to `FULFILLED`".
    PRD 3.2: "Any attempt to drive a state transition from a status where it is not
    defined is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/withdraw_after_fulfilled_returns_invalid_state
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-9", sku_overrides=dict(SKU_BOOK))
    enr = base["enrollment"]
    cust_id = base["customer"]["id"]
    cl = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z",
                         as_headers=fx.make_subscriber_headers(cust_id))
    fx.screen_claim(cl["id"])
    fx.approve_claim(cl["id"], enr["id"])
    fx.route_claim(cl["id"], repair_cost_cents=20000)
    ro = fx.repair_order_for_claim(cl["id"])
    validate_success(api.complete_repair_order(ro["id"], logistics_headers))
    fulfilled = validate_success(api.get_claim(cl["id"], adjuster_headers))
    assert fulfilled["status"] == "FULFILLED"
    resp = api.withdraw_claim(cl["id"], fx.make_subscriber_headers(cust_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
