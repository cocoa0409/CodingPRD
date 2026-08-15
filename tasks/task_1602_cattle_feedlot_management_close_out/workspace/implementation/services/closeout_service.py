"""Close-out business logic: DRAFT -> CONFIRMED -> SUPERSEDED lifecycle."""
import store
from util import new_record, bump
from errors import raise_err, ERR_CLOSE_OUT_NOT_DRAFT, ERR_LOT_NOT_CLOSABLE, \
    ERR_ACTIVE_HEDGES_EXIST, ERR_CARCASS_COUNT_MISMATCH, ERR_STALE_VERSION, \
    ERR_LOT_NOT_FOUND
from . import lot_service
from . import calculations


def create_close_out(lot, pricing_basis, grid_base_price_cents_per_cwt, expected_lot_version):
    """Create a DRAFT close-out for a lot (OCC-guarded)."""
    lot_service.check_lot_closable(lot)

    # OCC check
    if expected_lot_version is not None and expected_lot_version != lot["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_lot_version (%d) does not match lot's current version (%d)"
                  % (expected_lot_version, lot["version"]))

    rec = new_record()
    rec.update({
        "lot_id": lot["id"],
        "pricing_basis": pricing_basis,
        "grid_base_price_cents_per_cwt": grid_base_price_cents_per_cwt,
        "carcass_records": None,
        "total_grid_value_cents": None,
        "total_cost_cents": None,
        "final_cog_cents_per_cwt": None,
        "hedge_pnl_cents": None,
        "net_result_cents": None,
        "status": "DRAFT",
    })
    store.close_outs[rec["id"]] = rec

    lot_service.bump_lot(lot)
    return rec


def confirm_close_out(close_out, carcass_records):
    """Confirm a DRAFT close-out with carcass data.

    Cascades: supersede prior CONFIRMED, lot -> CLOSED_OUT, generate invoice.
    """
    if close_out["status"] != "DRAFT":
        raise_err(ERR_CLOSE_OUT_NOT_DRAFT,
                  "Close-out %s is not DRAFT (status=%s)" % (close_out["id"], close_out["status"]))

    lot = store.lots.get(close_out["lot_id"])
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND, "Lot not found: %s" % close_out["lot_id"])

    lot_service.check_lot_closable(lot)

    # Check all hedges are OFFSET or EXPIRED
    for hedge in store.hedge_positions.values():
        if hedge["lot_id"] == lot["id"] and hedge["status"] == "OPEN":
            raise_err(ERR_ACTIVE_HEDGES_EXIST,
                      "Lot %s has OPEN hedge %s" % (lot["id"], hedge["id"]))

    # Check carcass count
    if len(carcass_records) != lot["head_shipped"]:
        raise_err(ERR_CARCASS_COUNT_MISMATCH,
                  "carcass_records count (%d) differs from lot.head_shipped (%d)"
                  % (len(carcass_records), lot["head_shipped"]))

    # Store carcass records
    close_out["carcass_records"] = carcass_records

    # Compute grid value
    if close_out["pricing_basis"] == "PER_CARCASS":
        close_out["total_grid_value_cents"] = calculations.compute_grid_value_per_carcass(
            carcass_records, close_out["grid_base_price_cents_per_cwt"]
        )
    else:  # LOT_AVERAGE
        close_out["total_grid_value_cents"] = calculations.compute_grid_value_lot_average(
            carcass_records, close_out["grid_base_price_cents_per_cwt"]
        )

    # Compute cost pool
    feed_cents = lot["total_feed_cost_cents"]
    yardage_cents, yardage_hd = calculations.yardage_cents_final(lot)
    health_cents = lot["total_health_cost_cents"]
    death_loss_cents = lot["total_death_loss_cents"]
    total_cost = (lot["purchase_cost_cents"] + feed_cents + yardage_cents
                  + health_cents + death_loss_cents)
    close_out["total_cost_cents"] = total_cost

    # Compute final COG
    close_out["final_cog_cents_per_cwt"] = calculations.compute_final_cog(
        lot, lot["out_weight_total_lbs"], lot["head_shipped"]
    )

    # Snapshot hedge P&L
    close_out["hedge_pnl_cents"] = lot["total_hedge_pnl_cents"]

    # Compute net result
    close_out["net_result_cents"] = (
        close_out["total_grid_value_cents"]
        + close_out["hedge_pnl_cents"]
        - close_out["total_cost_cents"]
    )

    # Cascade link 1: supersede prior CONFIRMED close-outs and void their OPEN invoices
    from . import invoice_service
    for co in store.close_outs.values():
        if co["lot_id"] == lot["id"] and co["status"] == "CONFIRMED" and co["id"] != close_out["id"]:
            co["status"] = "SUPERSEDED"
            bump(co)
            # Void its OPEN invoice
            for inv in store.invoices.values():
                if inv["lot_id"] == lot["id"] and inv["status"] == "OPEN":
                    invoice_service.void_invoice_system(inv)

    # Cascade link 2: lot -> CLOSED_OUT
    close_out["status"] = "CONFIRMED"
    bump(close_out)
    lot_service.close_out_lot(lot)

    # Cascade link 3 & 4: generate new invoice and update owner balance
    from . import invoice_service
    invoice_service.create_invoice_for_lot(lot)

    return close_out
