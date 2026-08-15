"""Stock adjustments, posture thresholds, and optimistic concurrency control
(PRD 2.8, 3.1, 3.2)."""
from test_helpers import (
    LM,
    ApiErrorId,
    adjust_stock,
    api_client,
    base_scenario,
    create_surge,
    fill_unit_to_par,
    read_par,
    read_stock,
    stock_adjustment_payload,
    update_par_level_payload,
    validate_error,
    validate_success,
)


class TestStockAdjustmentPair:
    """A +5 adjustment and its -5 compensation leave circulation and the
    accounted total exactly where they started (PRD 2.7, 3.1)."""

    def test_positive_adjustment_applies_and_bumps_version(
        self, api, linen_manager_headers
    ):
        """PRD 3.1: "Found linen, donations, and write-offs are recorded by a
        `LinenManager` as a stock adjustment carrying `delta_pieces`
        (positive for found or donated pieces, negative for write-offs), a
        free-text `reason`, and the OCC field `expected_linen_stock_version`
        described in §2.8. The delta is applied to `in_circulation`, and the
        stock's `version` increments by one."

        Design: Difficulty/compensating_invariant/stock_adjustment_pair_conserves_total_pieces
        """
        ctx = base_scenario()
        stock = read_stock(ctx["stock"]["id"])
        before_version = stock["version"]
        assert stock["in_circulation"] == 100

        updated = validate_success(
            api.create_stock_adjustment(
                stock["id"],
                stock_adjustment_payload(5, before_version, reason="FOUND"),
                linen_manager_headers,
            ),
            201,
        )
        assert updated["in_circulation"] == 105
        assert updated["version"] == before_version + 1
        # Total accounted pieces: 105 circulation + 10 reserve = 115.
        assert updated["in_circulation"] + updated["reserve_pieces"] == 115

    def test_compensating_adjustment_restores_total(
        self, api, linen_manager_headers
    ):
        """PRD 2.7: "Retired pieces leave circulation permanently, keeping
        the total accounted pieces conserved."
        PRD 3.1: "If applying the delta would drive any counter negative, the
        adjustment is rejected with `ERR_NEGATIVE_INVENTORY`."

        Design: Difficulty/compensating_invariant/stock_adjustment_pair_conserves_total_pieces
        """
        ctx = base_scenario()
        stock = read_stock(ctx["stock"]["id"])
        opening_total = stock["in_circulation"] + stock["reserve_pieces"]

        first = validate_success(
            api.create_stock_adjustment(
                stock["id"],
                stock_adjustment_payload(5, stock["version"], reason="FOUND"),
                linen_manager_headers,
            ),
            201,
        )
        second = validate_success(
            api.create_stock_adjustment(
                stock["id"],
                stock_adjustment_payload(
                    -5, first["version"], reason="WRITE_OFF_CORRECTION"
                ),
                linen_manager_headers,
            ),
            201,
        )
        assert second["in_circulation"] == 100
        assert second["version"] == first["version"] + 1
        assert second["in_circulation"] + second["reserve_pieces"] == opening_total, (
            "the +5/-5 pair must conserve the accounted total at "
            f"{opening_total}, got "
            f"{second['in_circulation'] + second['reserve_pieces']}"
        )


def test_stock_posture_threshold_flips(api, linen_manager_headers):
    """PRD 3.1: "When the available supply is strictly below
    `reorder_point_pieces`, posture is `CRITICAL`; otherwise, when it is
    strictly below one and a half times `reorder_point_pieces` rounded down to
    a whole piece, posture is `LOW`; otherwise it is `SUFFICIENT`."
    PRD 3.1: "A stock's `posture` is recomputed whenever `in_circulation` or
    `reserve_pieces` changes, including at creation."

    Design: Corner/calculations/stock_posture_threshold_flips
    """
    ctx = base_scenario(
        stock_overrides={
            "reorder_point_pieces": 15,
            "opening_pieces": 20,
            "opening_reserve_pieces": 0,
        }
    )
    stock = read_stock(ctx["stock"]["id"])
    # available 20: not < 15, but < floor(1.5*15) = 22 -> LOW.
    assert stock["posture"] == "LOW", (
        f"available 20 with reorder 15 must be LOW (20 < 22), got {stock['posture']}"
    )

    updated = adjust_stock(stock["id"], -6, stock["version"], reason="WRITE_OFF")
    assert updated["in_circulation"] == 14
    assert updated["posture"] == "CRITICAL", (
        f"available 14 < reorder 15 must be CRITICAL, got {updated['posture']}"
    )


def test_occ_par_update_stale_after_surge_cascade(api, linen_manager_headers):
    """PRD 2.8: "Updating a par level requires `expected_par_level_version`,
    carrying the client's last observed `version` of that par level. If the
    par level's current `version` has advanced since the client last read it
    — for example because a surge activation or closure cascade rewrote its
    effective par and bumped its version — the update is rejected with
    `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a
    par configuration it has not observed."
    PRD 3.2: "The update is OCC-guarded by `expected_par_level_version` per
    §2.8, recomputes `effective_par` when not in surge, and increments the par
    level's `version` by one."

    Design: Corner/complexity_layers/occ_par_update_stale_after_surge_cascade
    """
    ctx = base_scenario()
    stale_version = ctx["par"]["version"]

    surge = create_surge(ctx["facility"]["id"])
    validate_success(api_client.activate_surge_event(surge["id"], LM), 200)

    res = api.update_par_level(
        ctx["par"]["id"],
        update_par_level_payload(stale_version, base_par_quantity=25),
        linen_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    validate_success(api_client.close_surge_event(surge["id"], LM), 200)
    fresh_version = read_par(ctx["par"]["id"])["version"]
    updated = validate_success(
        api.update_par_level(
            ctx["par"]["id"],
            update_par_level_payload(fresh_version, base_par_quantity=25),
            linen_manager_headers,
        ),
        200,
    )
    assert updated["base_par_quantity"] == 25
    assert updated["effective_par"] == 25, (
        "post-surge recompute leaves effective_par equal to the new base"
    )
    assert updated["version"] == fresh_version + 1


def test_occ_stock_adjustment_stale(api, linen_manager_headers):
    """PRD 2.8: "Recording a stock adjustment requires
    `expected_linen_stock_version`, carrying the client's last observed
    `version` of that linen stock. If the stock's current `version` has
    advanced since the client last read it — for example because a cart-run
    completion or a manifest return mutated its counters and bumped its
    version — the adjustment is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD 3.1: "The delta is applied to `in_circulation`, and the stock's
    `version` increments by one."

    Design: Corner/complexity_layers/occ_stock_adjustment_stale
    """
    ctx = base_scenario()
    stale_version = ctx["stock"]["version"]
    # A fill-run completion moves 20 pieces and bumps the stock version.
    fill_unit_to_par(ctx)

    res = api.create_stock_adjustment(
        ctx["stock"]["id"],
        stock_adjustment_payload(5, stale_version, reason="FOUND"),
        linen_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = read_stock(ctx["stock"]["id"])["version"]
    updated = validate_success(
        api.create_stock_adjustment(
            ctx["stock"]["id"],
            stock_adjustment_payload(5, fresh_version, reason="FOUND"),
            linen_manager_headers,
        ),
        201,
    )
    assert updated["in_circulation"] == 85, (
        f"80 after the fill + 5 found = 85, got {updated['in_circulation']}"
    )
    assert updated["version"] == fresh_version + 1
