"""Domain helpers and calculations (PRD 3)."""
from datetime import timedelta
from decimal import Decimal

import clock
import store
from util import dec, rhu0, rhu2_dec


# ---------------------------------------------------------------------------
# derived fields
# ---------------------------------------------------------------------------
def stock_posture(s):
    """stock_posture calc: strict < boundaries (PRD 3.1)."""
    avail = s["in_circulation"] + s["reserve_pieces"]
    rop = s["reorder_point_pieces"]
    if avail < rop:
        return "CRITICAL"
    if avail < (3 * rop) // 2:  # floor(1.5 * reorder_point_pieces)
        return "LOW"
    return "SUFFICIENT"


def unit_quality_flag(u):
    """unit_quality_flag calc: trailing 30-day window on the logical clock,
    inclusive edge (created_at >= now - 30d), WATCH at >= 3."""
    cutoff = clock.now() - timedelta(days=30)
    n = 0
    for c in store.complaints.values():
        if (c["unit_id"] == u["id"]
                and c["status"] in ("VERIFIED", "RESOLVED")
                and c["created_at"] >= cutoff):
            n += 1
    return "WATCH" if n >= 3 else "CLEAR"


def find_par(unit_id, stock_id):
    for p in store.par_levels.values():
        if p["unit_id"] == unit_id and p["stock_id"] == stock_id:
            return p
    return None


def per_piece_rate_cents(stock, facility):
    """Computed once per stock: piece_weight_lbs * rate_per_lb_cents, RHU."""
    return rhu0(dec(stock["piece_weight_lbs"]) * dec(facility["rate_per_lb_cents"]))


def facility_of_unit(unit):
    return store.facilities.get(unit["facility_id"])


def facility_of_run(run):
    unit = store.units.get(run["unit_id"])
    if unit is None:
        return None
    return store.facilities.get(unit["facility_id"])


def pars_of_facility(facility_id):
    out = []
    for p in store.par_levels.values():
        u = store.units.get(p["unit_id"])
        if u is not None and u["facility_id"] == facility_id:
            out.append(p)
    return out


def manifests_of_invoice(invoice_id):
    return [m for m in store.manifests.values() if m.get("invoice_id") == invoice_id]


def find_manifest_line(manifest, stock_id):
    for line in manifest["lines"]:
        if line["stock_id"] == stock_id:
            return line
    return None


def find_returned_line(manifest, stock_id):
    for rl in manifest.get("returned_lines") or []:
        if rl["stock_id"] == stock_id:
            return rl
    return None


def loss_rate_reached(stock):
    """Cumulative loss rate over all RECONCILED manifests of the facility.

    Returns the 2dp round-half-up rate as a Decimal. Comparison is >= 5.00.
    """
    total_expected = 0
    for m in store.manifests.values():
        if m["facility_id"] != stock["facility_id"] or m["status"] != "RECONCILED":
            continue
        for line in m["lines"]:
            if line["stock_id"] == stock["id"]:
                total_expected += line["expected_pieces"]
    if total_expected == 0:
        return Decimal("0.00")
    return rhu2_dec(Decimal(100 * stock["lost_pieces"]) / Decimal(total_expected))
