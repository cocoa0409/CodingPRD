"""Boundary-precision checks: shoe mileage retirement threshold and the
empty-order rejection.

Queue A (Difficulty): boundary_precision_check (mileage threshold, empty order).
Queue B (Corner): state_machines (below-threshold stays active, log-after-retire).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    fixtures as fx,
)


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / shoe_mileage_ge_threshold_retirement
# ---------------------------------------------------------------------------
def test_shoe_retires_at_exact_threshold(api, sm):
    """PRD 3.6: "If the shoe is `ACTIVE` and its cumulative `total_mileage_miles`
    reaches or exceeds its `retirement_threshold_miles` — the boundary is
    inclusive — the shoe automatically moves to `RETIREMENT_DUE`, raising the
    mileage reminder that tells the runner it is time to rotate in a new pair."

    Design: Difficulty/boundary_precision_check/shoe_mileage_ge_threshold_retirement
    """
    _m, _p, _o, shoe = fx.setup_fulfilled_shoe(mileage_life_miles=300)
    updated = validate_success(api.log_mileage(shoe["id"], {"miles": 300}, sm), 200)
    assert updated["total_mileage_miles"] == 300
    assert updated["status"] == "RETIREMENT_DUE"


def test_shoe_retires_above_threshold(api, sm):
    """PRD 3.6: "If the shoe is `ACTIVE` and its cumulative `total_mileage_miles`
    reaches or exceeds its `retirement_threshold_miles` — the boundary is
    inclusive — the shoe automatically moves to `RETIREMENT_DUE`, raising the
    mileage reminder that tells the runner it is time to rotate in a new pair."

    Design: Difficulty/boundary_precision_check/shoe_mileage_ge_threshold_retirement
    """
    _m, _p, _o, shoe = fx.setup_fulfilled_shoe(mileage_life_miles=300)
    updated = validate_success(api.log_mileage(shoe["id"], {"miles": 350}, sm), 200)
    assert updated["total_mileage_miles"] == 350
    assert updated["status"] == "RETIREMENT_DUE"


# ---------------------------------------------------------------------------
# Corner: state_machines
# ---------------------------------------------------------------------------
def test_shoe_below_threshold_stays_active(api, sm):
    """PRD 3.6: "If the shoe is `ACTIVE` and its cumulative `total_mileage_miles`
    reaches or exceeds its `retirement_threshold_miles` — the boundary is
    inclusive — the shoe automatically moves to `RETIREMENT_DUE`"

    Design: Corner/state_machines/c_shoe_below_threshold_stays_active
    """
    _m, _p, _o, shoe = fx.setup_fulfilled_shoe(mileage_life_miles=300)
    updated = validate_success(api.log_mileage(shoe["id"], {"miles": 299}, sm), 200)
    assert updated["total_mileage_miles"] == 299
    assert updated["status"] == "ACTIVE"


def test_log_mileage_after_retire_rejected(api, sm):
    """PRD 3.6: "Logging mileage against, or retiring, an already-`RETIRED` shoe
    is rejected with `ERR_SHOE_ALREADY_RETIRED`."

    Design: Corner/state_machines/c_shoe_logmileage_after_retire_returns_already_retired
    """
    _m, _p, _o, shoe = fx.setup_fulfilled_shoe()
    get_success_data(api.retire_shoe(shoe["id"], sm))
    resp = api.log_mileage(shoe["id"], {"miles": 10}, sm)
    validate_error(resp, ApiErrorId.ERR_SHOE_ALREADY_RETIRED.value, 409)


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / empty_order_zero_lines_rejected
# ---------------------------------------------------------------------------
def test_empty_order_zero_lines_rejected(api, sm):
    """PRD 3.3: "An order with no lines is rejected with `ERR_EMPTY_ORDER`."

    Design: Difficulty/boundary_precision_check/empty_order_zero_lines_rejected
    """
    member = fx.create_member()
    resp = api.create_order({"member_id": member["id"], "lines": []}, sm)
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value, 422)


def test_empty_order_with_promo_still_rejected(api, sm):
    """PRD 2.9: "A `POST /orders` request that carries zero lines is rejected
    specifically with `ERR_EMPTY_ORDER` (422)."

    Design: Difficulty/boundary_precision_check/empty_order_zero_lines_rejected
    """
    member = fx.create_member()
    resp = api.create_order(
        {"member_id": member["id"], "lines": [], "promo_code": "SPRING15"}, sm
    )
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value, 422)
