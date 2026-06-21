"""Calculation corners: tier straddle, estimate variant selection, LOST exclusion."""
import test_helpers as th


def test_wash_fold_tier_straddle_no_rush(api):
    """PRD §3.3: "the first 5 kilograms are priced at 400 cents per kilogram, and
    any weight beyond the first 5 kilograms is priced at 300 cents per kilogram,
    so a garment at or under 5 kilograms is simply its kilogram weight times 400
    cents, and a heavier garment is 5 kilograms times 400 cents plus the excess
    kilograms times 300 cents."

    7kg WASH_FOLD, no rush/sub: 5*400 + 2*300 = 2600.

    Design: Corner/calculations/wash_fold_tier_straddle_no_rush
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 7000}],
        actuals=[{"actual_weight_grams": 7000}],
        order_overrides={"rush": False},
    )
    finished = th.validate_success(
        api.finish_clean(order["id"], garments[0]["id"], th.plant_headers()))
    assert finished["final_line_cents"] == 2600, \
        f"7kg straddle line should be 2600, got {finished['final_line_cents']}"


def test_estimate_line_uses_declared_values(api):
    """PRD §3.3: "each garment's `estimate_line_cents` is computed from its
    declared measurements"
    PRD §3.3: "For a `DRY_CLEAN` garment, the base is the piece count times 900
    cents per piece."

    DRY_CLEAN declared 3 pieces, no sub/rush: estimate line 2700, order estimate
    total 2700.

    Design: Corner/calculations/estimate_line_uses_declared_values
    """
    customer, pickup, delivery, order, garments = th.create_order_with_garments(
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 3}])
    th.schedule_order(order, customer)
    garment = th.validate_success(
        api.get_garment(order["id"], garments[0]["id"], th.make_customer_headers(customer["id"])))
    assert garment["estimate_line_cents"] == 2700, \
        f"estimate line for 3 pieces is 2700, got {garment['estimate_line_cents']}"
    refreshed = th.get_order(order["id"], customer["id"])
    assert refreshed["estimate_total_cents"] == 2700, \
        f"estimate total is 2700, got {refreshed['estimate_total_cents']}"


def test_lost_garment_excluded_from_final_total(api):
    """PRD §3.5: "Entering `QC_HOLD` recomputes the order's `final_total_cents` as
    the sum of the `final_line_cents` of all garments on the order that are not
    lost - lost garments are excluded entirely"

    Two DRY_CLEAN (2 pieces each = 1800); one finished, one LOST: final total =
    1800 (the LOST garment contributes 0).

    Design: Corner/calculations/lost_garment_excluded_from_final_total
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[
            {"service_type": "DRY_CLEAN", "declared_piece_count": 2},
            {"service_type": "DRY_CLEAN", "declared_piece_count": 2},
        ],
        actuals=[{"actual_piece_count": 2}, {"actual_piece_count": 2}],
    )
    th.finish_clean(order, garments[0])
    th.mark_lost(order, garments[1])
    held = th.validate_success(api.qc_hold(order["id"], th.plant_headers()))
    assert held["final_total_cents"] == 1800, \
        f"only surviving garment counts -> 1800, got {held['final_total_cents']}"
