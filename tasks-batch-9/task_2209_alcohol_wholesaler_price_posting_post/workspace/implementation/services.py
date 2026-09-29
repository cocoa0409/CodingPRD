"""Cascade discipline, rollups and shared domain lookups (PRD sections 2.8, 2.9)."""

import calc
from store import bump, bump_if_changed, db, snapshot


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def schedule_of_item(item):
    return db.price_schedules[item["schedule_id"]]


def program_of_schedule(schedule):
    return db.state_programs.get(schedule["state_program_id"])


def wholesaler_of_schedule(schedule):
    return db.wholesalers.get(schedule["wholesaler_id"])


def program_of_wholesaler(wholesaler):
    return db.state_programs.get(wholesaler["state_program_id"])


def items_of_schedule(schedule_id):
    return [i for i in db.price_schedule_items.values() if i["schedule_id"] == schedule_id]


def tiers_of_item(item_id):
    return [t for t in db.quantity_discount_tiers.values() if t["item_id"] == item_id]


def combos_containing_item(item_id):
    return [
        c
        for c in db.combination_sales.values()
        if item_id in c["member_item_ids"]
    ]


def lines_of_invoice(invoice_id):
    return [l for l in db.invoice_lines.values() if l["invoice_id"] == invoice_id]


def findings_of_audit(audit_id):
    return [f for f in db.audit_findings.values() if f["audit_id"] == audit_id]


def invoices_of_audit(audit_id):
    return [i for i in db.retailer_invoices.values() if i["audit_id"] == audit_id]


def member_items(combo):
    out = []
    for item_id in combo["member_item_ids"]:
        item = db.price_schedule_items.get(item_id)
        if item is not None:
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# wholesaler penalty buckets (section 2.9)
# ---------------------------------------------------------------------------
def recompute_exposure(wholesaler):
    wholesaler["penalty_exposure_cents"] = calc.accrued_exposure(wholesaler)


# ---------------------------------------------------------------------------
# derived price cascades (section 2.8)
# ---------------------------------------------------------------------------
def recompute_active_tiers(item):
    """Re-derive discounted_case_price_cents on every ACTIVE tier of the item."""
    for tier in tiers_of_item(item["id"]):
        if tier["status"] != "ACTIVE":
            continue
        before = snapshot(tier)
        tier["discounted_case_price_cents"] = calc.tier_discounted_case_price(
            item["case_price_cents"], tier["discount_pct"]
        )
        bump_if_changed(tier, before)


def recompute_combos_after_amendment_accepted(item):
    """ACTIVE combinations only; a combination that now falls below its floor voids."""
    for combo in combos_containing_item(item["id"]):
        if combo["status"] != "ACTIVE":
            continue
        before = snapshot(combo)
        floor_price, minimum = calc.combination_sale_min_price(member_items(combo))
        combo["floor_price_cents"] = floor_price
        combo["min_allowed_price_cents"] = minimum
        if combo["combined_case_price_cents"] < minimum:
            combo["status"] = "VOID"
        bump_if_changed(combo, before)


def recompute_combos_after_amendment_revoked(item):
    """Every combination containing the item; a VOID one may return to ACTIVE."""
    for combo in combos_containing_item(item["id"]):
        before = snapshot(combo)
        floor_price, minimum = calc.combination_sale_min_price(member_items(combo))
        combo["floor_price_cents"] = floor_price
        combo["min_allowed_price_cents"] = minimum
        if combo["status"] == "VOID" and combo["combined_case_price_cents"] >= minimum:
            combo["status"] = "ACTIVE"
        bump_if_changed(combo, before)


# ---------------------------------------------------------------------------
# invoice validation (sections 3.8)
# ---------------------------------------------------------------------------
def revalidate_invoice(invoice):
    """Reprice every line and recompute every rollup; returns the new status."""
    wholesaler = db.wholesalers[invoice["wholesaler_id"]]
    program = program_of_wholesaler(wholesaler)
    invoice_date = _dt(invoice["invoice_date"])
    lines = sorted_lines(invoice["id"])
    for line in lines:
        item = db.price_schedule_items[line["item_id"]]
        before = snapshot(line)
        priced = calc.price_invoice_line(line, item, program)
        line.update(priced)
        detection, _resolved = calc.detect_off_posted(line, item, priced, invoice_date)
        line.update(detection)
        bump_if_changed(line, before)

    rollups = calc.settle_invoice(lines)
    invoice.update(rollups)
    invoice["validation_status"] = (
        "FLAGGED" if rollups["off_posted_line_count"] > 0 else "VALIDATED"
    )
    if invoice["validation_status"] == "VALIDATED":
        # The FLAGGED -> VALIDATED branch clears the exposure rollups explicitly so
        # that no residue of an earlier finding survives.
        invoice["off_posted_line_count"] = 0
        invoice["total_variance_cents"] = 0
    bump(invoice)
    return invoice["validation_status"]


def sorted_lines(invoice_id):
    from store import sorted_records

    return sorted_records(lines_of_invoice(invoice_id))


def _dt(value):
    from store import dt_of

    return dt_of(value)
