"""Cross-entity business services: serialization, derived-field recomputation,
reconciliation, draw rebalancing, permit clearance, warranty expiry."""
from decimal import Decimal

import calculations as calc
import clock
import db


# ---------------------------------------------------------------------------
# Serialization — strip internal fields and present money as floats with 2dp.
# ---------------------------------------------------------------------------
_INTERNAL = {"_seq"}


def _money(value):
    """Present a stored Decimal money value as a float rounded to 2dp."""
    return float(calc.r2(value))


_MONEY_FIELDS = {
    "contract_total", "draws_paid_total", "balance_due", "material_subtotal",
    "labor_subtotal", "material_tax", "reconciled_total", "amount", "total_delta",
}


def serialize(record):
    out = {}
    for k, v in record.items():
        if k in _INTERNAL:
            continue
        if isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Project lookups for children
# ---------------------------------------------------------------------------
def project_draws(project_id):
    rows = [d for d in db.draws.values() if d["project_id"] == project_id]
    rows.sort(key=lambda d: _DRAW_ORDER.get(d["milestone"], 99))
    return rows


_DRAW_ORDER = {"DEPOSIT": 0, "DELIVERY": 1, "FRAMING": 2, "FINAL": 3}


def project_permits(project_id):
    return [p for p in db.permits.values() if p["project_id"] == project_id]


def project_hoas(project_id):
    return [h for h in db.hoa_approvals.values() if h["project_id"] == project_id]


def project_material_orders(project_id):
    return [m for m in db.material_orders.values() if m["project_id"] == project_id]


def project_crew_bookings(project_id):
    return [c for c in db.crew_bookings.values() if c["project_id"] == project_id]


def project_estimates(project_id):
    return [e for e in db.estimates.values() if e["project_id"] == project_id]


def project_warranties(project_id):
    return [w for w in db.warranties.values() if w["project_id"] == project_id]


def accepted_estimate(project_id):
    for e in db.estimates.values():
        if e["project_id"] == project_id and e["status"] == "ACCEPTED":
            return e
    return None


def estimate_line_items(estimate_id):
    rows = [li for li in db.line_items.values() if li["estimate_id"] == estimate_id]
    rows.sort(key=lambda li: li["_seq"])
    return rows


def approved_site_measure(project_id):
    for sm in db.site_measures.values():
        if sm["project_id"] == project_id and sm["status"] == "APPROVED":
            return sm
    return None


# ---------------------------------------------------------------------------
# Derived field recomputation on Project (PRD §2.4 — counts as a mutation)
# ---------------------------------------------------------------------------
def recompute_project_money(project):
    """Recompute draws_paid_total and balance_due from PAID draws + contract_total."""
    paid = sum(
        (calc.D(d["amount"]) for d in project_draws(project["id"]) if d["status"] == "PAID"),
        Decimal("0.00"),
    )
    project["draws_paid_total"] = calc.r2(paid)
    project["balance_due"] = calc.r2(calc.D(project["contract_total"]) - paid)


def recompute_permit_clearance(project, customer):
    """Derive permit_clearance per scaffold permit_clearance_derivation."""
    permits = project_permits(project["id"])
    hoas = project_hoas(project["id"])
    if any(p["status"] == "DENIED" for p in permits) or any(h["status"] == "REJECTED" for h in hoas):
        clearance = "BLOCKED"
    elif any(p["status"] == "ISSUED" for p in permits) and (
        customer.get("hoa_governed") is False
        or any(h["status"] == "APPROVED" for h in hoas)
    ):
        clearance = "CLEARED"
    else:
        clearance = "PENDING"
    project["permit_clearance"] = clearance
    return clearance


# ---------------------------------------------------------------------------
# Pricing: rebuild estimate totals from its line items (estimated basis)
# ---------------------------------------------------------------------------
def price_estimate_lines(estimate):
    """Recompute each line's line_material_cost, then roll up the estimate.

    Operates on the estimate's stored quantity_units (estimate basis).
    Mutates the estimate's computed fields. Does NOT touch reconciled_total.
    """
    lines = estimate_line_items(estimate["id"])
    priced = []
    for li in lines:
        li["line_material_cost"] = calc.line_material_cost(
            li["material"], li["style"], li["quantity_units"],
            li["accessory"], li["grade_slope_pct"],
        )
        db.touch(li)
        priced.append({
            "work_type": li["work_type"],
            "quantity_units": li["quantity_units"],
            "line_material_cost": li["line_material_cost"],
        })
    ms, ls, mt, ct = calc.rollup(priced, estimate["tax_rate_pct"])
    estimate["material_subtotal"] = ms
    estimate["labor_subtotal"] = ls
    estimate["material_tax"] = mt
    estimate["contract_total"] = ct
    return ct


def rollup_on_basis(estimate, override_quantities):
    """Roll up an estimate using override quantities for selected lines.

    override_quantities: {line_item_id: quantity}. Lines not present keep their
    stored quantity_units. Used for reconciliation and measured-basis re-pricing.
    Returns contract_total (Decimal). Does NOT mutate line items.
    """
    lines = estimate_line_items(estimate["id"])
    priced = []
    for li in lines:
        qty = override_quantities.get(li["id"], li["quantity_units"])
        lmc = calc.line_material_cost(
            li["material"], li["style"], qty, li["accessory"], li["grade_slope_pct"],
        )
        priced.append({
            "work_type": li["work_type"],
            "quantity_units": qty,
            "line_material_cost": lmc,
        })
    _, _, _, ct = calc.rollup(priced, estimate["tax_rate_pct"])
    return ct


def measured_quantity_map(project_id):
    """{line_item_id: measured_units} from the project's APPROVED site measure."""
    sm = approved_site_measure(project_id)
    if sm is None:
        return {}
    out = {}
    for entry in sm.get("measured_quantities", []):
        out[entry["line_item_id"]] = entry["measured_units"]
    return out


# ---------------------------------------------------------------------------
# Draw rebalance (PRD §3.3 / §3.7) — re-derive non-PAID draws, bump each.
# ---------------------------------------------------------------------------
def rebalance_draws(project):
    rows = project_draws(project["id"])
    updates = calc.draw_rebalance(project["contract_total"], rows)
    by_milestone = {d["milestone"]: d for d in rows}
    for milestone, amt in updates.items():
        row = by_milestone[milestone]
        if calc.D(row["amount"]) != amt:
            row["amount"] = amt
            db.touch(row)
        else:
            row["amount"] = amt


def create_draws(project):
    """Create the four SCHEDULED draws on estimate acceptance."""
    schedule = calc.draw_schedule(project["contract_total"])
    for milestone, pct, amt in schedule:
        row = {
            "project_id": project["id"],
            "milestone": milestone,
            "status": "SCHEDULED",
            "pct": float(pct),
            "amount": amt,
        }
        db.stamp_create(row)
        db.draws[row["id"]] = row


# ---------------------------------------------------------------------------
# Warranty expiry (clock-driven, PRD §3.9) — surfaced lazily on read.
# ---------------------------------------------------------------------------
def apply_warranty_expiry(warranty):
    """If an ISSUED warranty's coverage term has elapsed, flip it to EXPIRED."""
    if warranty["status"] != "ISSUED":
        return
    from datetime import timezone

    issued = clock.parse_iso(warranty["created_at"])
    years = int(warranty["coverage_years"])
    # Coverage term: years added to the issue instant.
    try:
        expiry = issued.replace(year=issued.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 fallback.
        expiry = issued.replace(year=issued.year + years, day=28)
    if clock.now().astimezone(timezone.utc) >= expiry:
        warranty["status"] = "EXPIRED"
        db.touch(warranty)
