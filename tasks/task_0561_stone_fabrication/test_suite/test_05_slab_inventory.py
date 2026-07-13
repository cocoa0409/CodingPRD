"""Slab intake defaults, the estimated-yield vs actual-consumed dual variant, slab-area
conservation across reserve-then-release, and slab-filtered fabrication listing."""
import pytest

from test_helpers import (
    validate_success, validate_paginated,
    create_slab_payload,
    setup_scheduled_fab,
)


# --------------------------------------------------------------------------
# Corner/entities — fresh slab defaults
# --------------------------------------------------------------------------
def test_slab_intake_defaults_computed(api, fabricator_headers):
    """PRD §3.4: "A fresh slab is `IN_STOCK` with `reserved_sqft` of 0 and `remaining_sqft`
    equal to `nominal_sqft`, and its `status` moves through `IN_STOCK`, `RESERVED`, and
    `CONSUMED` as described in §2.7."

    Design: Corner/entities/slab_intake_defaults_computed
    """
    resp = api.create_slab(
        create_slab_payload(slab_label="SL9", material_grade="PREMIUM", nominal_sqft=50),
        fabricator_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "IN_STOCK"
    assert data["reserved_sqft"] == pytest.approx(0, abs=0.005)
    assert data["remaining_sqft"] == pytest.approx(50.00, abs=0.005)


# --------------------------------------------------------------------------
# Difficulty/dual_variant_calc — estimated_yield vs actual_consumed on the slab
# --------------------------------------------------------------------------
def test_actual_consumed_and_reserved_on_reserve(api, fabricator_headers):
    """PRD §3.5: "The order's `actual_consumed_sqft` is computed as the sum of every piece's
    `sqft` plus a kerf allowance of 0.10 square feet per piece (that is, 0.10 multiplied by the
    number of pieces), rounded half up to two decimal places."
    PRD §2.7: "When a fabrication order allocates the slab it becomes `RESERVED`, its
    `reserved_sqft` is set to the order's computed consumption, and its `remaining_sqft` is
    reduced accordingly."

    pieces [25, 15] -> 25 + 15 + 0.10*2 = 40.20.

    Design: Difficulty/dual_variant_calc/estimated_yield_vs_actual_consumed_on_slab
    """
    ctx = setup_scheduled_fab(nominal_sqft=50)
    assert ctx["fab"]["actual_consumed_sqft"] == pytest.approx(40.20, abs=0.005)
    slab = validate_success(api.get_slab(ctx["sl_id"], fabricator_headers))
    assert slab["reserved_sqft"] == pytest.approx(40.20, abs=0.005)


def test_actual_consumed_diverges_from_estimated_yield(api, fabricator_headers):
    """PRD §3.4: "its `nominal_sqft` multiplied by the complement of a 15 percent standard waste
    factor — that is, `nominal_sqft` times 0.85 — rounded half up to two decimal places,
    surfaced as `estimated_yield_sqft`. This slab-intrinsic estimate is distinct from the
    job-specific `actual_consumed_sqft` computed when a fabrication order allocates the slab
    (see §3.5); the two are expected to diverge."

    remaining is 9.80; the actual consumed (40.20) diverges from the estimated yield
    (50 * 0.85 = 42.50).

    Design: Difficulty/dual_variant_calc/estimated_yield_vs_actual_consumed_on_slab
    """
    ctx = setup_scheduled_fab(nominal_sqft=50)
    slab = validate_success(api.get_slab(ctx["sl_id"], fabricator_headers))
    assert slab["remaining_sqft"] == pytest.approx(9.80, abs=0.005)
    estimated_yield = 42.50  # round_half_up(50 * 0.85, 2)
    assert slab["reserved_sqft"] != pytest.approx(estimated_yield, abs=0.005)


# --------------------------------------------------------------------------
# Difficulty/compensating_invariant — slab area conserved on reserve-then-release
# --------------------------------------------------------------------------
def test_cancel_releases_slab_to_in_stock(api, fabricator_headers):
    """PRD §3.5: "Cancelling a fabrication order is permitted from any non-terminal state —
    `SCHEDULED`, `CUTTING`, `RECUTTING`, or `QC_PASSED` — and moves it to `CANCELLED` while
    releasing its slab back to `IN_STOCK` with `reserved_sqft` reset to 0 and `remaining_sqft`
    restored to `nominal_sqft`."

    Design: Difficulty/compensating_invariant/slab_area_conserved_reserve_then_release
    """
    ctx = setup_scheduled_fab(nominal_sqft=50)
    cancelled = validate_success(api.cancel_fabrication_order(ctx["f_id"], fabricator_headers))
    assert cancelled["status"] == "CANCELLED"
    slab = validate_success(api.get_slab(ctx["sl_id"], fabricator_headers))
    assert slab["status"] == "IN_STOCK"


def test_cancel_restores_slab_area_to_nominal(api, fabricator_headers):
    """PRD §2.7: "If the allocating order is cancelled, the slab returns to `IN_STOCK` with
    `reserved_sqft` reset to 0 and `remaining_sqft` restored to the full `nominal_sqft`."
    PRD §2.7: "At every reserve, release, or consume transition, `remaining_sqft` is reconciled
    against `nominal_sqft` and `reserved_sqft` so that reserved-plus-remaining always equals
    nominal."

    Design: Difficulty/compensating_invariant/slab_area_conserved_reserve_then_release
    """
    ctx = setup_scheduled_fab(nominal_sqft=50)
    api.cancel_fabrication_order(ctx["f_id"], fabricator_headers)
    slab = validate_success(api.get_slab(ctx["sl_id"], fabricator_headers))
    assert slab["reserved_sqft"] == pytest.approx(0, abs=0.005)
    assert slab["remaining_sqft"] == pytest.approx(50.00, abs=0.005)


# --------------------------------------------------------------------------
# Corner/endpoints — fabrication orders filtered by slab (reverse reachability)
# --------------------------------------------------------------------------
def test_fabrication_orders_filtered_by_slab_reverse_reach(api, fabricator_headers):
    """PRD §2.3: "Unless otherwise specified, all list endpoints return resources sorted by
    their creation timestamp in ascending order."
    PRD Endpoint table: "GET /fabrication-orders — List/filter fabrication orders." The order
    reserving a given slab is reachable from that slab id.

    Design: Corner/endpoints/fabrication_orders_filtered_by_slab_reverse_reach
    """
    ctx = setup_scheduled_fab(nominal_sqft=50)
    resp = api.list_fabrication_orders(fabricator_headers, params={"slab_id": ctx["sl_id"]})
    data, _meta = validate_paginated(resp)
    matching = [f for f in data if f["slab_id"] == ctx["sl_id"]]
    assert any(f["id"] == ctx["f_id"] for f in matching), "the order reserving the slab must be listed"
