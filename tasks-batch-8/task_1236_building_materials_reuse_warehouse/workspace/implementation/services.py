"""Business logic: calculations, recomputations, and cascade helpers."""
from datetime import timedelta
from decimal import Decimal

import db
from util import D, round_cents, dec1, period_of

# ---------------------------------------------------------------------------
# Constants (scaffold §1.3)
# ---------------------------------------------------------------------------

MIN_LIST_PRICE_CENTS = 100
SALES_TAX_RATE = Decimal("0.07")
THRIFT_VALUE_PCT = Decimal("0.30")
APPRAISAL_THRESHOLD_CENTS = 500000
SILVER_VOLUME_CENTS = 2500000
GOLD_VOLUME_CENTS = 10000000
SILVER_PCT = Decimal("0.05")
GOLD_PCT = Decimal("0.10")
PICKUP_FEE_CENTS = 5000
PICKUP_BUFFER_MINUTES = 60
SUPPORTER_VALUE_CENTS = 50000
BUILDER_VALUE_CENTS = 250000
CORNERSTONE_VALUE_CENTS = 1000000

CONDITION_MULT = {
    "A": Decimal("1.00"),
    "B": Decimal("0.75"),
    "C": Decimal("0.50"),
    "D": Decimal("0.25"),
}

TIER_PCT = {
    "STANDARD": Decimal("0"),
    "SILVER": SILVER_PCT,
    "GOLD": GOLD_PCT,
}


# ---------------------------------------------------------------------------
# Zone occupancy (derived; zone version bumps happen at each occupancy event)
# ---------------------------------------------------------------------------


def zone_current_count(zone):
    return sum(
        1
        for it in db.items.values()
        if it["zone_id"] == zone["id"] and it["sales_status"] in ("ON_FLOOR", "RESERVED")
    )


def zone_restock_recommended(zone):
    return zone_current_count(zone) <= zone["restock_threshold"]


# ---------------------------------------------------------------------------
# Item derived fields
# ---------------------------------------------------------------------------


def item_days_on_floor(item):
    fs = item.get("floor_since")
    if fs is None:
        return 0
    delta = db.now() - fs
    days = int(delta.total_seconds() // 86400)
    return max(days, 0)


# ---------------------------------------------------------------------------
# Pricing engine (item_list_price)
# ---------------------------------------------------------------------------


def compute_list_price(item, category, price_override_cents=None):
    if price_override_cents is not None and price_override_cents > 0:
        return price_override_cents
    if category["pricing_model"] == "FLAT":
        base = D(category["base_rate_cents"])
    else:
        base = D(category["base_rate_cents"]) * D(item["measure_qty"])
    mult = CONDITION_MULT[item["condition_grade"]]
    hazmat = (
        Decimal("1.15")
        if (category["hazmat_risk_flag"] or item["pre_1978_flag"])
        else Decimal("1.00")
    )
    return max(MIN_LIST_PRICE_CENTS, round_cents(base * mult * hazmat))


# ---------------------------------------------------------------------------
# Guidance valuation at offer accept (receipt_guidance_valuation ESTIMATED)
# ---------------------------------------------------------------------------


def guidance_valuation(offer, category):
    if category["pricing_model"] == "FLAT":
        base = D(category["base_rate_cents"])
    else:
        base = D(category["base_rate_cents"]) * D(offer["estimated_quantity"])
    mult = CONDITION_MULT[offer["condition_grade"]]
    return round_cents(base * mult * THRIFT_VALUE_PCT)


# ---------------------------------------------------------------------------
# Receipt final valuation (receipt_final_valuation)
# ---------------------------------------------------------------------------


def receipt_item_sum(offer_id):
    total = 0
    for it in db.items.values():
        if it["offer_id"] != offer_id:
            continue
        if it["pricing_status"] != "PRICED":
            continue
        if it["sales_status"] not in ("BACKROOM", "ON_FLOOR", "RESERVED", "SOLD"):
            continue
        total += it["list_price_cents"]
    return total


def receipt_requires_appraisal(offer, item_sum):
    category = db.categories.get(offer["category_id"])
    review = bool(category and category["requires_appraisal_review"])
    return item_sum >= APPRAISAL_THRESHOLD_CENTS or review


# ---------------------------------------------------------------------------
# Donor recognition (donor_recognition_tier)
# ---------------------------------------------------------------------------


def recompute_donor_standing(donor):
    now = db.now()
    lo = now - timedelta(days=365)
    superseded_ids = {
        r["supersedes_receipt_id"]
        for r in db.receipts.values()
        if r.get("supersedes_receipt_id")
    }
    total = 0
    for r in db.receipts.values():
        if r["donor_id"] != donor["id"]:
            continue
        if r["status"] not in ("ISSUED", "SUPERSEDED"):
            continue
        if r["id"] in superseded_ids:
            # only the newest receipt of a supersedes chain contributes
            continue
        issued_at = r.get("issued_at")
        if issued_at is None or not (lo <= issued_at <= now):
            continue
        total += r["valued_total_cents"]
    donor["trailing_receipt_value_cents"] = total
    if total >= CORNERSTONE_VALUE_CENTS:
        donor["recognition_tier"] = "CORNERSTONE"
    elif total >= BUILDER_VALUE_CENTS:
        donor["recognition_tier"] = "BUILDER"
    elif total >= SUPPORTER_VALUE_CENTS:
        donor["recognition_tier"] = "SUPPORTER"
    else:
        donor["recognition_tier"] = "NONE"


# ---------------------------------------------------------------------------
# Contractor trailing volume / discount tier (trailing_volume_cents)
# ---------------------------------------------------------------------------


def account_tier_for(trailing_cents):
    if trailing_cents >= GOLD_VOLUME_CENTS:
        return "GOLD"
    if trailing_cents >= SILVER_VOLUME_CENTS:
        return "SILVER"
    return "STANDARD"


def recompute_account_trailing(account):
    now = db.now()
    lo = now - timedelta(days=365)
    total = 0
    for s in db.sales.values():
        if s["contractor_id"] != account["id"]:
            continue
        if s["status"] != "FINALIZED":
            continue
        fa = s.get("finalized_at")
        if fa is None or not (lo <= fa <= now):
            continue
        total += s["total_cents"]
    account["trailing_volume_cents"] = total
    account["discount_tier"] = account_tier_for(total)


# ---------------------------------------------------------------------------
# Job tonnage ledgers (job_tonnage_estimates) and fee (crew_labor_cost)
# ---------------------------------------------------------------------------


def recompute_job_tonnage(job):
    est = Decimal("0")
    cert = Decimal("0")
    for b in db.batches.values():
        if b["job_id"] != job["id"]:
            continue
        if b["status"] != "DISPOSED_HAZARD":
            est += D(b["estimated_weight_lbs"])
        if b["status"] in ("WEIGHED", "SORTED"):
            cat = db.categories.get(b["category_id"])
            if cat and cat["divertible"]:
                cert += D(b["diverted_weight_lbs"])
    job["estimated_diverted_weight_lbs"] = dec1(est)
    job["certified_diverted_weight_lbs"] = dec1(cert)


def recompute_job_fee(job):
    labor = 0
    for a in db.assignments.values():
        if a["job_id"] == job["id"] and a["status"] == "COMPLETED":
            labor += a["labor_cost_cents"]
    job["actual_fee_cents"] = job["quoted_fee_cents"] + max(
        0, labor - job["included_labor_cents"]
    )


# ---------------------------------------------------------------------------
# Crew overlap (half-open) and vehicle buffered overlap
# ---------------------------------------------------------------------------


def crew_overlaps(member_id, start_at, end_at, exclude_id=None):
    for a in db.assignments.values():
        if a["crew_member_id"] != member_id:
            continue
        if exclude_id and a["id"] == exclude_id:
            continue
        if a["status"] not in ("ASSIGNED", "COMPLETED"):
            continue
        if a["start_at"] < end_at and a["end_at"] > start_at:
            return True
    return False


def vehicle_conflicts(vehicle_id, start, end, exclude_job_id=None):
    """Buffered overlap: no conflict iff e+buffer <= s2 or s >= e2+buffer."""
    buf = timedelta(minutes=PICKUP_BUFFER_MINUTES)
    for j in db.jobs.values():
        if j["vehicle_id"] != vehicle_id or j["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if exclude_job_id and j["id"] == exclude_job_id:
            continue
        s2, e2 = j["scheduled_start"], j["scheduled_end"]
        if s2 is None:
            continue
        if not (end + buf <= s2 or start >= e2 + buf):
            return True
    for appt in db.appointments.values():
        if appt["vehicle_id"] != vehicle_id or appt["status"] != "BOOKED":
            continue
        s2, e2 = appt["window_start"], appt["window_end"]
        if not (end + buf <= s2 or start >= e2 + buf):
            return True
    return False


# ---------------------------------------------------------------------------
# Agreement lazy expiry
# ---------------------------------------------------------------------------


def refresh_agreement(agreement):
    if (
        agreement["status"] == "ACTIVE"
        and db.now() >= agreement["valid_until"]
    ):
        agreement["status"] = "EXPIRED"
        db.touch(agreement)


def refresh_all_agreements():
    for ag in db.agreements.values():
        refresh_agreement(ag)


# ---------------------------------------------------------------------------
# Sale totals (sale_totals + contractor_discount_pct)
# ---------------------------------------------------------------------------


def sale_lines_of(sale_id):
    return [l for l in db.sale_lines.values() if l["sale_id"] == sale_id]


def agreement_qualifying_qty(sale, agreement):
    qty = Decimal("0")
    for line in sale_lines_of(sale["id"]):
        item = db.items.get(line["item_id"])
        if item and item["category_id"] == agreement["category_id"]:
            qty += D(line["quantity"])
    return qty


def agreement_pct_for(sale):
    """Agreement discount fraction, or 0 when not applicable."""
    ag_id = sale.get("agreement_id")
    if not ag_id:
        return Decimal("0")
    ag = db.agreements.get(ag_id)
    if ag is None:
        return Decimal("0")
    refresh_agreement(ag)
    if ag["status"] != "ACTIVE":
        return Decimal("0")
    if not (ag["valid_from"] <= db.now() < ag["valid_until"]):
        return Decimal("0")
    if agreement_qualifying_qty(sale, ag) < D(ag["min_quantity"]):
        return Decimal("0")
    return D(ag["discount_pct"])


def compute_sale_totals(sale):
    lines = sale_lines_of(sale["id"])
    subtotal = sum(l["line_total_cents"] for l in lines)
    tier_pct = TIER_PCT.get(sale.get("tier_snapshot"), Decimal("0"))
    pct = max(tier_pct, agreement_pct_for(sale))
    bulk_discount = round_cents(D(subtotal) * pct)
    tax = round_cents(D(subtotal - bulk_discount) * SALES_TAX_RATE)
    total = subtotal - bulk_discount + tax
    return {
        "subtotal_cents": subtotal,
        "discount_pct_applied": float(pct),
        "bulk_discount_cents": bulk_discount,
        "tax_cents": tax,
        "total_cents": total,
    }


# ---------------------------------------------------------------------------
# Diversion report totals (diversion_report_close)
# ---------------------------------------------------------------------------


def compute_report_totals(period):
    batch_diverted = Decimal("0")
    batch_landfill = Decimal("0")
    for b in db.batches.values():
        if b["report_period"] != period:
            continue
        cat = db.categories.get(b["category_id"])
        if b["status"] in ("WEIGHED", "SORTED"):
            if cat and cat["divertible"]:
                batch_diverted += D(b["diverted_weight_lbs"])
            batch_landfill += D(b["contamination_weight_lbs"])
        elif b["status"] == "DISPOSED_HAZARD":
            batch_landfill += D(b["scale_weight_lbs"])
    sold = batch_diverted
    donated = Decimal("0")
    recycled = Decimal("0")
    landfill = batch_landfill
    for it in db.items.values():
        if it["batch_id"] is not None:
            continue  # batch-derived items are never double counted
        cat = db.categories.get(it["category_id"])
        w = D(it["estimated_weight_lbs"])
        st = it["sales_status"]
        if st == "SOLD":
            sale = db.sales.get(it.get("sold_via_sale_id") or "")
            if sale and sale.get("finalized_at") is not None:
                if period_of(sale["finalized_at"]) == period:
                    if cat and cat["divertible"]:
                        sold += w
        elif st in ("DONATED_OUT", "RECYCLED", "DISPOSED"):
            da = it.get("_disposed_at")
            if da is None or period_of(da) != period:
                continue
            if st == "DONATED_OUT":
                if cat and cat["divertible"]:
                    donated += w
            elif st == "RECYCLED":
                if cat and cat["divertible"]:
                    recycled += w
            else:
                landfill += w
    return {
        "total_diverted_lbs": dec1(sold + donated + recycled),
        "sold_lbs": dec1(sold),
        "donated_lbs": dec1(donated),
        "recycled_lbs": dec1(recycled),
        "landfill_lbs": dec1(landfill),
    }


def open_report_for_period(period):
    for r in db.reports.values():
        if r["period"] == period and r["status"] == "OPEN":
            return r
    return None


# ---------------------------------------------------------------------------
# Serializers with derived fields
# ---------------------------------------------------------------------------

from util import serialize  # noqa: E402


def serialize_zone(zone):
    out = serialize(zone)
    out["current_count"] = zone_current_count(zone)
    out["restock_recommended"] = zone_restock_recommended(zone)
    return out


def serialize_item(item):
    out = serialize(item)
    out["days_on_floor"] = item_days_on_floor(item)
    return out


def serialize_donor(donor):
    recompute_donor_standing(donor)
    return serialize(donor)


def serialize_account(account):
    recompute_account_trailing(account)
    return serialize(account)


def serialize_agreement(agreement):
    refresh_agreement(agreement)
    return serialize(agreement)


def serialize_report(report):
    out = serialize(report)
    if report["status"] == "OPEN":
        out.update(compute_report_totals(report["period"]))
    return out
