"""Establishment warranty and watering compliance: claim gates, credit tiers,
evaluation verdicts, terminal lockdown, one-claim-per-order, log window and
uniqueness (PRD §3.9)."""
from test_helpers import (
    TEST_USERS,
    assert_money_eq,
    factories,
    get_order,
    get_success_data,
    make_customer_headers,
    mini_chain,
    pay,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def _log(api, claim_id, headers, log_date, moisture):
    return get_success_data(api.create_watering_log(
        claim_id, factories.create_watering_log_payload(log_date, moisture), headers
    ))


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency /
#   warranty_claim_gated_by_order_state_and_payment
# ---------------------------------------------------------------------------

def test_claim_rejected_when_order_not_settled(api):
    """PRD §3.9: "The order must have completed installation (its `installed_at` recorded), must be fully settled — a claim while `payment_status` is not `PAID` is rejected with `ERR_ORDER_NOT_SETTLED` — and must be claimed within thirty days of `installed_at`, otherwise `ERR_CLAIM_WINDOW_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/warranty_claim_gated_by_order_state_and_payment
    """
    bundle = mini_chain(api, stage="installed")  # INSTALLED, nothing paid
    o_id = bundle["o"]["id"]

    resp = api.create_warranty_claim(
        o_id, factories.create_warranty_claim_payload("W1"),
        bundle["customer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SETTLED, 409)

    order = get_order(api, o_id)
    assert order["status"] == "INSTALLED", "rejected claim changes nothing"
    data, meta = validate_paginated(
        api.list_order_warranty_claims(o_id, SALES)
    )
    assert data == [] and meta["total_count"] == 0, "no claim was created"


def test_claim_accepted_once_order_installed_and_paid(api):
    """PRD §3.9: "The claim is anchored to its order (`order_id`), copies `customer_id` from it, snapshots `eligible_turf_sqft` from the order's `delivered_sqft`, and starts `SUBMITTED`. The weather case sets the compliance bar: `target_credits` is 500 for `W1`, 400 for `W2`, and 300 for `W3`."
    PRD §3.6: "The symmetric join also holds: when a payment flips an `INSTALLED` order to `PAID`, the order auto-transitions to `CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/warranty_claim_gated_by_order_state_and_payment
    """
    bundle = mini_chain(api, stage="installed")
    o_id = bundle["o"]["id"]

    pay(api, o_id, 175.47)  # INSTALLED + PAID -> auto-joins CLOSED
    assert get_order(api, o_id)["status"] == "CLOSED"

    set_clock(api, "2026-08-20T09:00:00Z")  # within thirty days of installed_at
    claim = validate_success(api.create_warranty_claim(
        o_id, factories.create_warranty_claim_payload("W1"),
        bundle["customer_headers"],
    ), 201)
    assert claim["status"] == "SUBMITTED"
    assert claim["order_id"] == o_id
    assert claim["customer_id"] == bundle["c"]["id"]
    assert_money_eq(claim["eligible_turf_sqft"], 200,
                    "snapshotted from delivered_sqft")
    assert claim["target_credits"] == 500, "W1 target"


# ---------------------------------------------------------------------------
# Corner: calculations / watering_credit_tier_boundaries
# ---------------------------------------------------------------------------

def test_watering_credit_tier_boundaries(api):
    """PRD §3.9: "Each log earns `credits_awarded` by soil moisture: a reading of at least 40 earns 140 credits, a reading of at least 30 but below 40 earns 120, and below 30 earns 60. The claim's `total_credits` is the running sum across its logs."

    Design: Corner/calculations/watering_credit_tier_boundaries
    """
    bundle = mini_chain(api, stage="claim")
    w_id = bundle["w"]["id"]
    cust = bundle["customer_headers"]

    l1 = _log(api, w_id, cust, "2026-08-04", 40.0)
    l2 = _log(api, w_id, cust, "2026-08-05", 39.99)
    l3 = _log(api, w_id, cust, "2026-08-06", 29.99)
    assert l1["credits_awarded"] == 140, "40.0 >= 40: inclusive green boundary"
    assert l2["credits_awarded"] == 120, "39.99 in [30, 40)"
    assert l3["credits_awarded"] == 60, "29.99 < 30"

    claim = get_success_data(api.get_warranty_claim(w_id, SALES))
    assert claim["total_credits"] == 320


# ---------------------------------------------------------------------------
# Corner: calculations / warranty_evaluate_compliant_issues_credit
# ---------------------------------------------------------------------------

def test_warranty_evaluate_compliant_issues_credit(api):
    """PRD §3.9: "Evaluation is the verdict. A `FarmManager` evaluates a `SUBMITTED` claim — at least one watering log must exist, otherwise `ERR_INVALID_STATE`. When `total_credits` reaches `target_credits`, the claim becomes `COMPLIANT`: `resolution` is set to `CREDIT_ISSUED` and `credit_amount` to the `eligible_turf_sqft` at fifty cents per square foot, rounded half-up to two decimals."

    Design: Corner/calculations/warranty_evaluate_compliant_issues_credit
    """
    bundle = mini_chain(api, stage="claim")
    w_id, cust = bundle["w"]["id"], bundle["customer_headers"]
    assert_money_eq(bundle["w"]["eligible_turf_sqft"], 200, "eligible_turf_sqft")
    assert bundle["w"]["target_credits"] == 500

    for day in ("2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"):
        _log(api, w_id, cust, day, 45)  # 4 x 140 = 560

    evaluated = get_success_data(api.evaluate_warranty_claim(w_id, FARM))
    assert evaluated["status"] == "COMPLIANT", "560 >= 500"
    assert evaluated["resolution"] == "CREDIT_ISSUED"
    assert_money_eq(evaluated["credit_amount"], 100.00, "200 sqft at 0.50")
    assert evaluated.get("evaluated_at"), "evaluated_at is stamped"


# ---------------------------------------------------------------------------
# Corner: calculations / warranty_evaluate_insufficient_issues_zero
# ---------------------------------------------------------------------------

def test_warranty_evaluate_insufficient_issues_zero(api):
    """PRD §3.9: "Below target, the claim becomes `INSUFFICIENT` with `resolution` `REJECTED` and `credit_amount` 0.00. Either way `evaluated_at` is stamped and the claim is terminal; claims and their watering logs can be listed per order, and claims can be listed farm-wide with `customer_id` and `status` filters."

    Design: Corner/calculations/warranty_evaluate_insufficient_issues_zero
    """
    bundle = mini_chain(api, stage="claim")
    w_id, cust = bundle["w"]["id"], bundle["customer_headers"]
    _log(api, w_id, cust, "2026-08-04", 45)
    _log(api, w_id, cust, "2026-08-05", 45)
    _log(api, w_id, cust, "2026-08-06", 45)
    _log(api, w_id, cust, "2026-08-07", 25)  # 420 + 60 = 480 < 500

    evaluated = get_success_data(api.evaluate_warranty_claim(w_id, FARM))
    assert evaluated["total_credits"] == 480
    assert evaluated["status"] == "INSUFFICIENT"
    assert evaluated["resolution"] == "REJECTED"
    assert_money_eq(evaluated["credit_amount"], 0.00, "no credit below target")


# ---------------------------------------------------------------------------
# Corner: state_machines / claim_evaluate_twice_returns_already_terminal
# ---------------------------------------------------------------------------

def test_claim_evaluate_twice_returns_already_terminal(api):
    """PRD §3.9: "Either way `evaluated_at` is stamped and the claim is terminal; claims and their watering logs can be listed per order, and claims can be listed farm-wide with `customer_id` and `status` filters."
    PRD §2.9: "6. **Terminal guard** — the target entity is not in a terminal state for this action; otherwise `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/claim_evaluate_twice_returns_already_terminal
    """
    bundle = mini_chain(api, stage="claim")
    w_id, cust = bundle["w"]["id"], bundle["customer_headers"]
    for day in ("2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"):
        _log(api, w_id, cust, day, 45)
    evaluated = get_success_data(api.evaluate_warranty_claim(w_id, FARM))
    assert evaluated["status"] == "COMPLIANT"

    resp = api.evaluate_warranty_claim(w_id, FARM)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)


# ---------------------------------------------------------------------------
# Corner: errors / second_claim_returns_duplicate_claim
# ---------------------------------------------------------------------------

def test_second_claim_returns_duplicate_claim(api):
    """PRD §3.9: "An order still carrying a set `delivery_flagged` cannot open a claim until a later in-window delivery check clears it (§3.7), and each order supports exactly one claim — a second is rejected with `ERR_DUPLICATE_CLAIM`."

    Design: Corner/errors/second_claim_returns_duplicate_claim
    """
    bundle = mini_chain(api, stage="claim")
    resp = api.create_warranty_claim(
        bundle["o"]["id"], factories.create_warranty_claim_payload("W2"),
        bundle["customer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM, 409)


# ---------------------------------------------------------------------------
# Corner: errors / watering_log_window_and_duplicate_date
# ---------------------------------------------------------------------------

def test_watering_log_window_and_duplicate_date(api):
    """PRD §3.9: "The `log_date` must lie within the claim window, from the `installed_at` date through thirty days after it inclusive, and only one log is accepted per calendar date per claim; a date outside the window or a duplicated date is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/errors/watering_log_window_and_duplicate_date
    """
    bundle = mini_chain(api, stage="claim")  # installed 2026-08-03
    w_id, cust = bundle["w"]["id"], bundle["customer_headers"]
    _log(api, w_id, cust, "2026-08-04", 45)

    dup = api.create_watering_log(
        w_id, factories.create_watering_log_payload("2026-08-04", 50), cust
    )
    validate_error(dup, ApiErrorId.ERR_INVALID_REQUEST, 400)

    # installed_at date + 30 days is 2026-09-02; 2026-09-05 is outside.
    outside = api.create_watering_log(
        w_id, factories.create_watering_log_payload("2026-09-05", 45), cust
    )
    validate_error(outside, ApiErrorId.ERR_INVALID_REQUEST, 400)


# ---------------------------------------------------------------------------
# Corner: errors / evaluate_without_logs_returns_invalid_state
# ---------------------------------------------------------------------------

def test_evaluate_without_logs_returns_invalid_state(api):
    """PRD §3.9: "Evaluation is the verdict. A `FarmManager` evaluates a `SUBMITTED` claim — at least one watering log must exist, otherwise `ERR_INVALID_STATE`."

    Design: Corner/errors/evaluate_without_logs_returns_invalid_state
    """
    bundle = mini_chain(api, stage="claim")
    resp = api.evaluate_warranty_claim(bundle["w"]["id"], FARM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


# ---------------------------------------------------------------------------
# Corner: validations / claim_after_30_day_window_returns_claim_window_expired
# ---------------------------------------------------------------------------

def test_claim_after_30_day_window_returns_claim_window_expired(api):
    """PRD §3.9: "The order must have completed installation (its `installed_at` recorded), must be fully settled — a claim while `payment_status` is not `PAID` is rejected with `ERR_ORDER_NOT_SETTLED` — and must be claimed within thirty days of `installed_at`, otherwise `ERR_CLAIM_WINDOW_EXPIRED`."

    Design: Corner/validations/claim_after_30_day_window_returns_claim_window_expired
    """
    bundle = mini_chain(api, stage="closed")  # installed 2026-08-03T11:00
    # 30 days and 22 hours after installed_at: the claim window is hard.
    set_clock(api, "2026-09-03T09:00:00Z")
    resp = api.create_warranty_claim(
        bundle["o"]["id"], factories.create_warranty_claim_payload("W1"),
        bundle["customer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED, 409)


# ---------------------------------------------------------------------------
# Corner: errors / delivered_paid_but_not_installed_claim_returns_invalid_state
# ---------------------------------------------------------------------------

def test_delivered_paid_but_not_installed_claim_returns_invalid_state(api):
    """PRD §3.9: "After installation, the farm stands behind establishment. The owning `Customer` files a warranty claim on their order with a `weather_case` of `W1`, `W2`, or `W3`. The order must have completed installation (its `installed_at` recorded), must be fully settled — a claim while `payment_status` is not `PAID` is rejected with `ERR_ORDER_NOT_SETTLED` — and must be claimed within thirty days of `installed_at`, otherwise `ERR_CLAIM_WINDOW_EXPIRED`."

    Design: Corner/errors/delivered_paid_but_not_installed_claim_returns_invalid_state
    """
    bundle = mini_chain(api, stage="delivered")
    o_id = bundle["o"]["id"]
    pay(api, o_id, 175.47)  # PAID while DELIVERED (no auto-join)
    order = get_order(api, o_id)
    assert order["status"] == "DELIVERED"
    assert order["payment_status"] == "PAID"

    resp = api.create_warranty_claim(
        o_id, factories.create_warranty_claim_payload("W1"),
        bundle["customer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
