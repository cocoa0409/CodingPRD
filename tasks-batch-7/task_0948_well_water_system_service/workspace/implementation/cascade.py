"""The eight-hop work-order completion cascade and invoice construction."""

import calc
import common
from core import add_days, cents, d, db, floor_div, whole_days_between


# --------------------------------------------------------------------------
# Invoice construction (PRD 3.11)
# --------------------------------------------------------------------------

def _warranty_credit(work_order):
    """(parts_credit, labor_credit, total).  Zero in all three parts unless the
    completing work order is a remedy."""
    claim_id = work_order.get("origin_callback_claim_id")
    if not claim_id:
        return 0, 0, 0
    claim = db.get("CallbackClaim", claim_id)
    if claim is None:
        return 0, 0, 0
    original_id = claim["original_work_order_id"]

    def coverage_of(coverage_class):
        rows = [c for c in db.all("WarrantyCoverage")
                if c["work_order_id"] == original_id
                and c["coverage_class"] == coverage_class
                and c["status"] in ("ACTIVE", "SUPERSEDED")]
        return rows[0] if rows else None

    part_cov = coverage_of("PART")
    labor_cov = coverage_of("LABOR")
    parts_credit = 0
    labor_credit = 0
    if part_cov is not None:
        pdays = whole_days_between(part_cov["starts_at"], claim["submitted_at"])
        if pdays <= calc.PART_WARRANTY_DAYS:
            parts_credit = work_order["parts_charge_cents"]
    if labor_cov is not None:
        ldays = whole_days_between(labor_cov["starts_at"], claim["submitted_at"])
        if ldays <= calc.LABOR_WARRANTY_DAYS:
            labor_credit = work_order["labor_charge_cents"]
    return parts_credit, labor_credit, parts_credit + labor_credit


def _line(ctx, invoice, seq, line_type, description, amount, entry_id=None):
    ctx.new("InvoiceLine", {
        "invoice_id": invoice["id"],
        "parts_consumption_entry_id": entry_id,
        "line_type": line_type,
        "description": description,
        "amount_cents": amount,
        "sequence_no": seq,
    })


def build_invoices(ctx, work_order):
    entries = common.posted_entries(work_order["id"])
    parts = sum(e["extended_price_cents"] for e in entries)
    labor = work_order["labor_charge_cents"]

    prop = db.get("Property", work_order["property_id"])
    ticket = db.get("EmergencyTicket", work_order["emergency_ticket_id"]) \
        if work_order["emergency_ticket_id"] else None
    surcharge = 0
    trip_fee = 0
    if work_order["pipeline"] == "EMERGENCY" and ticket is not None:
        surcharge = ticket["net_dispatch_charge_cents"]
        trip_fee = calc.trip_fee_cents(prop)
    dispatch = surcharge + trip_fee

    permit_fee = common.work_order_permit_fee(work_order["id"])
    parts_credit, labor_credit, warranty_credit = _warranty_credit(work_order)

    pre_discount_pretax = parts + labor + dispatch + permit_fee - warranty_credit

    account = db.get("Account", prop["account_id"]) if prop else None
    eligible = (account is not None
                and account["membership_tier"] in calc.LOYALTY_DISCOUNT_ELIGIBLE_TIERS
                and pre_discount_pretax >= calc.LOYALTY_DISCOUNT_MIN_PRETAX_CENTS)
    loyalty = cents(d(parts) * calc.LOYALTY_DISCOUNT_PCT / d(100)) if eligible else 0

    taxable = max(0, parts - parts_credit - loyalty)
    tax = cents(d(taxable) * calc.TAX_RATE_PCT / d(100))
    undivided_total = pre_discount_pretax - loyalty + tax

    variant = "QUOTED_PINNED" if work_order["quote_id"] else "ACTUAL_FINAL"

    # ---- step 11: the shared-well split ----------------------------------
    shares = common.rows_where("SharedWellAgreement",
                               well_profile_id=work_order["well_profile_id"],
                               status="ACTIVE")
    share_total = sum((d(s["split_pct"]) for s in shares), d(0))
    if shares and share_total == d("100.00"):
        raws = [floor_div(d(undivided_total) * d(s["split_pct"]) / d(100)) for s in shares]
        remainder = undivided_total - sum(raws)
        raws[0] += remainder
        allocation = [(shares[i]["account_id"], raws[i], shares[i]["split_pct"])
                      for i in range(len(shares))]
    else:
        allocation = [(prop["account_id"], undivided_total, 100.00)]

    invoices = []
    for account_id, total, split_pct in allocation:
        invoice = ctx.new("Invoice", {
            "account_id": account_id,
            "work_order_id": work_order["id"],
            "variant": variant,
            "status": "DRAFT",
            "parts_subtotal_cents": parts,
            "labor_subtotal_cents": labor,
            "dispatch_subtotal_cents": dispatch,
            "warranty_credit_cents": warranty_credit,
            "loyalty_discount_cents": loyalty,
            "taxable_subtotal_cents": taxable,
            "tax_cents": tax,
            "total_cents": total,
            "amount_paid_cents": 0,
            "issued_at": None,
            "shared_split_pct": split_pct,
        })
        seq = 1
        for entry in entries:
            part = db.get("PartCatalogItem", entry["part_catalog_item_id"])
            label = part["part_number"] if part else "Part"
            _line(ctx, invoice, seq, "PARTS",
                  "Parts: %s x %d" % (label, entry["quantity"]),
                  entry["extended_price_cents"], entry["id"])
            seq += 1
        _line(ctx, invoice, seq, "LABOR", "Labour", labor)
        seq += 1
        if work_order["pipeline"] == "EMERGENCY":
            _line(ctx, invoice, seq, "DISPATCH_SURCHARGE", "Dispatch surcharge",
                  surcharge)
            seq += 1
            _line(ctx, invoice, seq, "TRIP_FEE", "Trip fee", trip_fee)
            seq += 1
        if permit_fee:
            _line(ctx, invoice, seq, "PERMIT_FEE", "Permit fee", permit_fee)
            seq += 1
        if warranty_credit > 0:
            _line(ctx, invoice, seq, "WARRANTY_CREDIT", "Warranty credit",
                  -warranty_credit)
            seq += 1
        if loyalty > 0:
            _line(ctx, invoice, seq, "LOYALTY_DISCOUNT", "Loyalty discount", -loyalty)
            seq += 1
        _line(ctx, invoice, seq, "TAX", "Tax", tax)
        invoices.append(invoice)
    return invoices


# --------------------------------------------------------------------------
# The completion cascade (PRD 3.9)
# --------------------------------------------------------------------------

def complete_work_order(ctx, work_order):
    ticket = db.get("EmergencyTicket", work_order["emergency_ticket_id"]) \
        if work_order["emergency_ticket_id"] else None

    # ---- hop 1: labour ---------------------------------------------------
    work_order["actual_end_at"] = db.clock
    technician = db.get("Technician", work_order["assigned_technician_id"])
    band = calc.labor_time_band(work_order["actual_start_at"])
    rate = calc.labor_rate_cents_per_hour(technician["tier"], band)
    non_well = (work_order["pipeline"] == "EMERGENCY" and ticket is not None
                and ticket["cause_class"] == "NON_WELL_CAUSE")
    minutes = calc.billable_minutes(work_order["actual_labor_minutes"], non_well)
    work_order["billable_minutes"] = minutes
    work_order["labor_rate_cents_per_hour"] = rate
    work_order["labor_charge_cents"] = calc.labor_charge_cents(rate, minutes)
    work_order["fulfillment_status"] = "COMPLETED"

    # ---- hop 2: parts finalisation (no stock moves) ----------------------
    entries = common.posted_entries(work_order["id"])
    work_order["parts_charge_cents"] = sum(e["extended_price_cents"] for e in entries)

    # ---- hop 3: warranty coverages ---------------------------------------
    minted = {"PART": None, "LABOR": None}
    for entry in entries:
        coverage = ctx.new("WarrantyCoverage", {
            "work_order_id": work_order["id"],
            "parts_consumption_entry_id": entry["id"],
            "superseded_by_id": None,
            "coverage_class": "PART",
            "starts_at": work_order["actual_end_at"],
            "expires_at": calc.coverage_expires_at(work_order["actual_end_at"], "PART"),
            "status": "ACTIVE",
            "claim_count": 0,
        })
        if minted["PART"] is None:
            minted["PART"] = coverage
    labor_coverage = ctx.new("WarrantyCoverage", {
        "work_order_id": work_order["id"],
        "parts_consumption_entry_id": None,
        "superseded_by_id": None,
        "coverage_class": "LABOR",
        "starts_at": work_order["actual_end_at"],
        "expires_at": calc.coverage_expires_at(work_order["actual_end_at"], "LABOR"),
        "status": "ACTIVE",
        "claim_count": 0,
    })
    minted["LABOR"] = labor_coverage

    claim = db.get("CallbackClaim", work_order["origin_callback_claim_id"]) \
        if work_order.get("origin_callback_claim_id") else None
    if claim is not None:
        old_coverage = db.get("WarrantyCoverage", claim["warranty_coverage_id"])
        if old_coverage is not None and old_coverage["status"] == "ACTIVE":
            replacement = minted.get(old_coverage["coverage_class"])
            old_coverage["status"] = "SUPERSEDED"
            old_coverage["superseded_by_id"] = replacement["id"] if replacement else None
            ctx.touch(old_coverage)

        # ---- hop 4: the claim resolves -----------------------------------
        if claim["status"] == "APPROVED_WARRANTY":
            claim["status"] = "RESOLVED_REPAIRED"
            ctx.touch(claim)
            original = db.get("WorkOrder", claim["original_work_order_id"])
            if original is not None:
                original["callback_eligibility"] = "CONSUMED"
                ctx.touch(original)

    # ---- hop 5: the well and one visit per ACTIVE plan --------------------
    well = db.get("WellProfile", work_order["well_profile_id"])
    filter_touched = False
    salt_units = 0
    tank_part = None
    for entry in entries:
        part = db.get("PartCatalogItem", entry["part_catalog_item_id"])
        if part is None:
            continue
        if part["category"] == "FILTRATION":
            filter_touched = True
        if part["category"] == "CONSUMABLE":
            salt_units += int(entry["quantity"])
        if part["category"] == "PRESSURE_TANK" and tank_part is None:
            tank_part = part
    salt_touched = salt_units > 0
    if filter_touched and salt_touched:
        visit_kind = "SALT_AND_FILTER"
    elif filter_touched:
        visit_kind = "FILTER_ONLY"
    elif salt_touched:
        visit_kind = "SALT_ONLY"
    else:
        visit_kind = "SERVICE_ONLY"
    salt_added = float(d(salt_units) * calc.SALT_LBS_PER_CONSUMABLE_UNIT)

    if well is not None:
        if tank_part is not None and tank_part["rated_drawdown_gallons"] is not None:
            well["pressure_tank_drawdown_gallons"] = tank_part["rated_drawdown_gallons"]
        calc.apply_duty_cycle(well)
        ctx.touch(well)

    for plan in common.active_plans_of_well(work_order["well_profile_id"]):
        ctx.new("MaintenanceVisit", {
            "maintenance_plan_id": plan["id"],
            "work_order_id": work_order["id"],
            "visit_kind": visit_kind,
            "performed_at": db.clock,
            "salt_added_lbs": salt_added,
            "filter_changed": filter_touched,
        })
        # ---- hop 6: the clocks -------------------------------------------
        plan["last_service_date"] = db.clock
        if salt_touched:
            plan["salt_remaining_lbs"] = float(min(
                d(plan["salt_remaining_lbs"]) + d(salt_added),
                calc.SALT_TANK_CAPACITY_LBS))
            plan["last_salt_delivery_date"] = db.clock
        if filter_touched:
            plan["last_filter_change_date"] = db.clock
        if well is not None:
            calc.recompute_operated_interval(plan, well)
        if visit_kind in ("SALT_AND_FILTER", "FILTER_ONLY") \
                and plan["compliance_state"] == "OVERDUE":
            plan["compliance_state"] = "COMPLIANT"
            plan["overdue_latched_at"] = None
        ctx.touch(plan)

    # ---- hop 7: the invoice ----------------------------------------------
    build_invoices(ctx, work_order)

    # ---- hop 8: the billing axis and the ticket ---------------------------
    work_order["billing_status"] = "PENDING_INVOICE"
    if ticket is not None and ticket["dispatch_status"] == "DIAGNOSED":
        ticket["dispatch_status"] = "RESOLVED"
        ctx.touch(ticket)
    ctx.touch(work_order)
