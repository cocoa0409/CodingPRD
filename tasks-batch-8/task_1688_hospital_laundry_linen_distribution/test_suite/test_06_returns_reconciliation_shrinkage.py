"""Vendor returns, wash-life retirement, shrinkage investigation, and the
complaint auto-resolution on manifest reconcile (PRD 3.5, 3.7)."""
from test_helpers import (
    base_scenario,
    collect_soiled,
    create_complaint,
    create_gown_stock,
    create_manifest,
    create_par,
    fill_unit_to_par,
    read_complaint,
    read_facility,
    read_stock,
    reconcile_manifest,
    return_manifest,
    setup_returned_manifest,
    validate_success,
)


def create_manifest_pair(ctx):
    """Two-line manifest: 40.00 lbs of sheets and 10.00 lbs of isolation
    gowns (20 expected pieces each at 2.00 / 0.50 lbs per piece)."""
    return create_manifest(
        ctx["facility"]["id"],
        [ctx["collect_run"]["id"]],
        [
            {"stock_id": ctx["stock"]["id"], "weight_lbs": 40.00,
             "isolation_flag": False},
            {"stock_id": ctx["gown"]["id"], "weight_lbs": 10.00,
             "isolation_flag": True},
        ],
        isolation_protocol_ack=True,
    )


def test_wash_life_retirement_boundary_crossing(api):
    """PRD 3.5: "Wash-life retirement follows a first-in-first-out rotation
    approximation: the number of multiples of `max_wash_cycles` reached by the
    new cumulative wash count minus the number reached by the prior cumulative
    count — each count divided by `max_wash_cycles` and rounded down — gives
    the pieces retired at this crossing, capped at the line's returned
    pieces."
    PRD 3.5: "`retired_pieces` increases by the condemned pieces plus these
    newly retired pieces."
    PRD 3.5: "`in_circulation` increases by the returned pieces minus the
    newly retired ones, since retired pieces leave circulation."

    Design: Corner/calculations/wash_life_retirement_boundary_crossing
    """
    ctx = setup_returned_manifest(
        soiled_pieces=5,
        weight_lbs=10.00,
        returned_pieces=5,
        condemned=0,
        par_quantity=10,
        stock_overrides={
            "max_wash_cycles": 5,
            "reorder_point_pieces": 5,
            "opening_pieces": 50,
            "opening_reserve_pieces": 10,
        },
    )
    stock = read_stock(ctx["stock"]["id"])
    assert stock["wash_cycles_completed"] == 5
    # floor(5/5) - floor(0/5) = 1 piece crosses the wash-life multiple.
    assert stock["retired_pieces"] == 1, (
        f"the 5th cumulative wash must retire exactly 1 piece, got {stock['retired_pieces']}"
    )
    # Fill run: 100... opening 50 -> 40 in circulation after fill (par 10);
    # collection of 5 -> 35; return of 5 with 1 retired -> 39.
    assert stock["in_circulation"] == 39, (
        f"35 + 5 returned - 1 retired = 39, got {stock['in_circulation']}"
    )


class TestLossRateThreshold:
    """Cumulative loss at exactly 5.00 percent trips INVESTIGATION (the
    comparison is >=), while a zero-loss sibling stays NORMAL."""

    def _setup_two_stock_manifest(self):
        ctx = base_scenario()
        gown = create_gown_stock(ctx["facility"]["id"])
        create_par(ctx["unit"]["id"], gown["id"], 30, "DAILY")
        ctx["gown"] = gown
        ctx["fill_run"] = fill_unit_to_par(ctx)
        ctx["collect_run"] = collect_soiled(
            ctx,
            [
                {"stock_id": ctx["stock"]["id"], "pieces": 20},
                {"stock_id": gown["id"], "pieces": 20},
            ],
        )
        manifest = create_manifest_pair(ctx)
        return_manifest(
            manifest["id"],
            [
                {"stock_id": ctx["stock"]["id"], "pieces": 19,
                 "condemned_pieces": 0},
                {"stock_id": gown["id"], "pieces": 19, "condemned_pieces": 1},
            ],
        )
        ctx["manifest"] = manifest
        return ctx

    def test_exactly_five_percent_flags_investigation(self, api):
        """PRD 3.5: "The stock's cumulative loss rate is then recomputed
        across all `RECONCILED` manifests of the facility — manifests still
        `DISPATCHED` or `RETURNED` are excluded — as one hundred times the
        total lost pieces divided by the total expected pieces, rounded half
        up to two decimal places."
        PRD 3.5: "When that rate reaches or exceeds 5.00 percent, the stock's
        `shrinkage_status` flips from `NORMAL` to `INVESTIGATION`; this flag
        is sticky and never returns to `NORMAL` automatically."

        Design: Difficulty/boundary_precision_check/loss_rate_exactly_5pct_flags_investigation
        """
        ctx = self._setup_two_stock_manifest()
        reconcile_manifest(ctx["manifest"]["id"])

        stock = read_stock(ctx["stock"]["id"])
        assert stock["lost_pieces"] == 1, (
            f"20 expected - 19 returned - 0 condemned = 1 lost, got {stock['lost_pieces']}"
        )
        assert stock["shrinkage_status"] == "INVESTIGATION", (
            "100 * 1 / 20 = 5.00 reaches the threshold (>=), so the stock "
            f"must be under investigation, got {stock['shrinkage_status']}"
        )

    def test_zero_loss_sibling_stays_normal(self, api):
        """PRD 3.5: "The stock's cumulative loss rate is then recomputed
        across all `RECONCILED` manifests of the facility — manifests still
        `DISPATCHED` or `RETURNED` are excluded — as one hundred times the
        total lost pieces divided by the total expected pieces, rounded half
        up to two decimal places."
        PRD 3.5: "`retired_pieces` increases by the condemned pieces plus
        these newly retired pieces."

        Design: Difficulty/boundary_precision_check/loss_rate_exactly_5pct_flags_investigation
        """
        ctx = self._setup_two_stock_manifest()
        reconcile_manifest(ctx["manifest"]["id"])

        gown = read_stock(ctx["gown"]["id"])
        assert gown["lost_pieces"] == 0, (
            "20 expected - 19 returned - 1 condemned = 0 lost, "
            f"got {gown['lost_pieces']}"
        )
        assert gown["shrinkage_status"] == "NORMAL"
        assert gown["retired_pieces"] == 1, (
            f"the condemned piece must be retired, got {gown['retired_pieces']}"
        )


def test_complaint_auto_resolved_on_manifest_reconcile(api, linen_manager_headers):
    """PRD 3.5: "Reconciliation also resolves quality fallout: every complaint
    referencing this manifest that is currently `VERIFIED` automatically
    transitions to `RESOLVED`, rewash resolution being implied by the
    reconciliation itself."
    PRD 3.7: "When the manifest sits on a `SETTLED` invoice or on no invoice
    at all, the facility's `credit_balance_cents` increases instead."

    Design: Corner/state_machines/complaint_auto_resolved_on_manifest_reconcile
    """
    ctx = setup_returned_manifest(soiled_pieces=8, weight_lbs=16.00,
                                  returned_pieces=7)
    complaint = create_complaint(
        ctx["unit"]["id"], ctx["manifest"]["id"], ctx["stock"]["id"],
        complaint_type="ODOR", pieces_affected=1,
    )
    verified = validate_success(
        api.verify_complaint(complaint["id"], linen_manager_headers), 200
    )
    assert verified["status"] == "VERIFIED"

    reconcile_manifest(ctx["manifest"]["id"])

    after = read_complaint(complaint["id"])
    assert after["status"] == "RESOLVED", (
        f"manifest reconcile must auto-resolve the verified complaint, got {after['status']}"
    )
    facility = read_facility(ctx["facility"]["id"])
    assert facility["credit_balance_cents"] == 80, (
        "1 piece x 80 cents per-piece rate routes to the facility pool "
        f"(manifest uninvoiced), got {facility['credit_balance_cents']}"
    )
