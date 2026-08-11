"""Business logic: serializers, calculations (SCAFFOLD 1.3), cascades."""
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from db import STORE, now, touch
from helpers import fmt_dt

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------
SCC_LIMIT = 750000
TEMP_LIMIT_F = 45
TIER1_CWT = Decimal(1000)
TIER2_DISCOUNT_PROVISIONAL = Decimal(80)
TIER2_DISCOUNT_FINAL = Decimal(75)
OVER_ORDER_TIER_CENTS = {"STANDARD": 150, "PREMIUM": 250, "PROBATION": 0}
CLASS_TIER_HIGH = 2400
CLASS_TIER_MID = 2100
CLASS_TIER_LOW = 1800
MAX_SHELF_LIFE = {
    "WHOLE_MILK": 21,
    "TWO_PERCENT": 21,
    "SKIM": 21,
    "HEAVY_CREAM": 30,
    "BUTTER": 180,
    "CONDENSED_SKIM": 270,
}
PRODUCT_CODES = set(MAX_SHELF_LIFE)
TEST_TYPES = {"ANTIBIOTIC", "SCC", "TEMPERATURE_RECHECK"}

_CENT = Decimal("1")
_TWO_DP = Decimal("0.01")


def dec(value):
    return Decimal(str(value))


def round_int(value):
    return int(value.quantize(_CENT, rounding=ROUND_HALF_UP))


def num_out(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


# ---------------------------------------------------------------------------
# Serializers (entity fields per SCAFFOLD 1.1; internal _-prefixed fields and
# OCC input-only fields are never serialized)
# ---------------------------------------------------------------------------
def ser_producer(p):
    return {
        "id": p["id"],
        "producer_code": p["producer_code"],
        "farm_name": p["farm_name"],
        "base_hauling_rate_cents_per_cwt": p["base_hauling_rate_cents_per_cwt"],
        "quality_flag": p["quality_flag"],
        "rolling_rejection_count_30d": p["rolling_rejection_count_30d"],
        "status": p["status"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_hauler(h):
    return {
        "id": h["id"],
        "hauler_code": h["hauler_code"],
        "company_name": h["company_name"],
        "license_expires_at": fmt_dt(h["license_expires_at"]),
        "status": h["status"],
        "created_at": fmt_dt(h["created_at"]),
        "updated_at": fmt_dt(h["updated_at"]),
        "version": h["version"],
    }


def ser_receipt(r):
    return {
        "id": r["id"],
        "producer_id": r["producer_id"],
        "hauler_id": r["hauler_id"],
        "arrived_at": fmt_dt(r["arrived_at"]),
        "gross_weight_lbs": r["gross_weight_lbs"],
        "tare_weight_lbs": r["tare_weight_lbs"],
        "net_weight_lbs": r["net_weight_lbs"],
        "temperature_f": r["temperature_f"],
        "antibiotic_result": r["antibiotic_result"],
        "scc_cells_per_ml": r["scc_cells_per_ml"],
        "rejection_reason": r["rejection_reason"],
        "disposition": r["disposition"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_lab_test(t):
    return {
        "id": t["id"],
        "tanker_receipt_id": t["tanker_receipt_id"],
        "test_type": t["test_type"],
        "result_value": t["result_value"],
        "result_disposition": t["result_disposition"],
        "completed_at": fmt_dt(t["completed_at"]),
        "lab_technician_id": t["lab_technician_id"],
        "status": t["status"],
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def ser_assay(a):
    return {
        "id": a["id"],
        "tanker_receipt_id": a["tanker_receipt_id"],
        "butterfat_pct": num_out(a["butterfat_pct"]),
        "protein_pct": num_out(a["protein_pct"]),
        "other_solids_pct": num_out(a["other_solids_pct"]),
        "butterfat_lbs": num_out(a["butterfat_lbs"]),
        "protein_lbs": num_out(a["protein_lbs"]),
        "other_solids_lbs": num_out(a["other_solids_lbs"]),
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def ser_settlement(s):
    return {
        "id": s["id"],
        "producer_id": s["producer_id"],
        "period_start_date": fmt_dt(s["period_start_date"]),
        "period_end_date": fmt_dt(s["period_end_date"]),
        "gross_pool_credit_cents": s["gross_pool_credit_cents"],
        "over_order_premium_cents": s["over_order_premium_cents"],
        "hauling_deduction_cents": s["hauling_deduction_cents"],
        "net_payment_cents": s["net_payment_cents"],
        "pricing_variant": s["pricing_variant"],
        "status": s["status"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_run(r):
    return {
        "id": r["id"],
        "pasteurizer_id": r["pasteurizer_id"],
        "scheduled_start_at": fmt_dt(r["scheduled_start_at"]),
        "scheduled_end_at": fmt_dt(r["scheduled_end_at"]),
        "actual_start_at": fmt_dt(r["actual_start_at"]),
        "actual_end_at": fmt_dt(r["actual_end_at"]),
        "flow_rate_gph": r["flow_rate_gph"],
        "min_hold_temp_f": r["min_hold_temp_f"],
        "status": r["status"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_cip(c):
    return {
        "id": c["id"],
        "pasteurizer_run_id": c["pasteurizer_run_id"],
        "started_at": fmt_dt(c["started_at"]),
        "completed_at": fmt_dt(c["completed_at"]),
        "caustic_conductivity_ms": c["caustic_conductivity_ms"],
        "rinse_ph": c["rinse_ph"],
        "validation_outcome": c["validation_outcome"],
        "status": c["status"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_batch(b):
    return {
        "id": b["id"],
        "pasteurizer_run_id": b["pasteurizer_run_id"],
        "product_code": b["product_code"],
        "quantity_gallons": b["quantity_gallons"],
        "shelf_life_days": b["shelf_life_days"],
        "code_date": fmt_dt(b["code_date"]),
        "status": b["status"],
        "created_at": fmt_dt(b["created_at"]),
        "updated_at": fmt_dt(b["updated_at"]),
        "version": b["version"],
    }


def ser_route(r):
    return {
        "id": r["id"],
        "route_code": r["route_code"],
        "destination_zip": r["destination_zip"],
        "transit_days": r["transit_days"],
        "min_days_of_code_required": r["min_days_of_code_required"],
        "status": r["status"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_permit(p):
    return {
        "id": p["id"],
        "permit_number": p["permit_number"],
        "issued_at": fmt_dt(p["issued_at"]),
        "expires_at": fmt_dt(p["expires_at"]),
        "inspection_score": p["inspection_score"],
        "violation_count_12mo": p["violation_count_12mo"],
        "status": p["status"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_pool(p):
    return {
        "id": p["id"],
        "pool_month": p["pool_month"],
        "announced_class_i_price_cents": p["announced_class_i_price_cents"],
        "butterfat_price_cents_per_lb": p["butterfat_price_cents_per_lb"],
        "protein_price_cents_per_lb": p["protein_price_cents_per_lb"],
        "other_solids_price_cents_per_lb": p["other_solids_price_cents_per_lb"],
        "producer_price_differential_cents": p["producer_price_differential_cents"],
        "total_pooled_lbs": num_out(pool_total_pooled_lbs(p)),
        "status": p["status"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def assays_of_receipt(receipt_id):
    return [a for a in STORE["assays"].values()
            if a["tanker_receipt_id"] == receipt_id]


def receipts_in_month(month):
    return [r for r in STORE["receipts"].values()
            if r["arrived_at"].strftime("%Y-%m") == month]


def released_receipts_in_month(month):
    return [r for r in receipts_in_month(month)
            if r["disposition"] == "RELEASED_FOR_PROCESSING"]


def latest_permit():
    permits = list(STORE["permits"].values())
    if not permits:
        return None
    return max(permits, key=lambda p: p["_seq"])


def pool_for_month(month):
    pools = [p for p in STORE["pools"].values() if p["pool_month"] == month]
    if not pools:
        return None
    return max(pools, key=lambda p: p["_seq"])


def pool_total_pooled_lbs(pool):
    """Read-only sum of net_weight_lbs over RELEASED_FOR_PROCESSING receipts
    in the pool month (computed live so release/divert cascades stay exact)."""
    total = 0
    for r in released_receipts_in_month(pool["pool_month"]):
        total += r["net_weight_lbs"]
    return total


def component_value_cents(receipts, pool):
    """Sum over receipts of per-component rounded pounds times prices."""
    cv = Decimal(0)
    if pool is None:
        return cv
    for r in receipts:
        for a in assays_of_receipt(r["id"]):
            cv += a["butterfat_lbs"] * pool["butterfat_price_cents_per_lb"]
            cv += a["protein_lbs"] * pool["protein_price_cents_per_lb"]
            cv += a["other_solids_lbs"] * pool["other_solids_price_cents_per_lb"]
    return cv


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def component_lbs(net_weight_lbs, pct):
    """round_half_up(net * pct / 100, 2) — per component, never on the sum."""
    return (dec(net_weight_lbs) * pct / Decimal(100)).quantize(
        _TWO_DP, rounding=ROUND_HALF_UP
    )


def quantize_pct(value):
    return dec(value).quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def compute_ppd(pool):
    """pool_blend_price_calc — pinned evaluation order (SCAFFOLD 1.3).

    Step 1: utilization from raw class volumes. The API surface records no
    Class I volume, so class_i_lbs is 0 and utilization is 0% -> LOW tier.
    """
    month = pool["pool_month"]
    receipts = released_receipts_in_month(month)
    total = sum(dec(r["net_weight_lbs"]) for r in receipts)
    class_i_lbs = Decimal(0)
    utilization_pct = (class_i_lbs / total * Decimal(100)) if total > 0 else Decimal(0)
    if utilization_pct >= 60:
        blend = CLASS_TIER_HIGH
    elif utilization_pct >= 40:
        blend = CLASS_TIER_MID
    else:
        blend = CLASS_TIER_LOW
    if total <= 0:
        return 0
    cv = component_value_cents(receipts, pool)
    per_cwt = (cv * 100 / total).to_integral_value(rounding=ROUND_FLOOR)
    return int(blend - per_cwt)


def recompute_settlement(s, pool=None):
    """producer_provisional_settlement_calc (PROVISIONAL and FINAL variants).

    Returns True when any financial line changed (a mutating update).
    """
    if pool is None:
        pool = pool_for_month(s["period_start_date"].strftime("%Y-%m"))
    receipts = [
        r for r in STORE["receipts"].values()
        if r["producer_id"] == s["producer_id"]
        and r["disposition"] == "RELEASED_FOR_PROCESSING"
        and s["period_start_date"] <= r["arrived_at"] <= s["period_end_date"]
    ]
    total_lbs = sum(dec(r["net_weight_lbs"]) for r in receipts)
    total_cwt = total_lbs / Decimal(100)
    cv = component_value_cents(receipts, pool)

    gross = cv
    if (
        s["pricing_variant"] == "FINAL"
        and pool is not None
        and pool["producer_price_differential_cents"] is not None
    ):
        gross = cv + dec(pool["producer_price_differential_cents"]) * total_cwt

    producer = STORE["producers"].get(s["producer_id"])
    flag = producer["quality_flag"] if producer else "STANDARD"
    premium = total_cwt * dec(OVER_ORDER_TIER_CENTS.get(flag, 0))

    rate = dec(producer["base_hauling_rate_cents_per_cwt"]) if producer else Decimal(0)
    discount = (
        TIER2_DISCOUNT_FINAL
        if s["pricing_variant"] == "FINAL"
        else TIER2_DISCOUNT_PROVISIONAL
    )
    if total_cwt <= TIER1_CWT:
        hauling = total_cwt * rate
    else:
        hauling = TIER1_CWT * rate + (total_cwt - TIER1_CWT) * (rate * discount / 100)

    gross_i = round_int(gross)
    premium_i = round_int(premium)
    hauling_i = round_int(hauling)
    net_i = gross_i + premium_i - hauling_i

    changed = (
        s["gross_pool_credit_cents"] != gross_i
        or s["over_order_premium_cents"] != premium_i
        or s["hauling_deduction_cents"] != hauling_i
        or s["net_payment_cents"] != net_i
    )
    s["gross_pool_credit_cents"] = gross_i
    s["over_order_premium_cents"] = premium_i
    s["hauling_deduction_cents"] = hauling_i
    s["net_payment_cents"] = net_i
    return changed


def recompute_draft_settlements():
    """Triggered on any receipt transitioning to RELEASED_FOR_PROCESSING or
    DIVERTED: refresh draft settlements so they reflect the current pool."""
    for s in STORE["settlements"].values():
        if s["status"] == "DRAFT":
            if recompute_settlement(s):
                touch(s)


def apply_rejection_cascade(producer):
    """producer_quality_flag_calc — trailing 30-day window, both endpoints
    inclusive, evaluated against the logical clock."""
    clock = now()
    window_start = clock - timedelta(days=30)
    count = 0
    for r in STORE["receipts"].values():
        if (
            r["producer_id"] == producer["id"]
            and r["disposition"] == "REJECTED"
            and r.get("_rejected_at") is not None
            and window_start <= r["_rejected_at"] <= clock
        ):
            count += 1
    producer["rolling_rejection_count_30d"] = count
    if count >= 4:
        producer["status"] = "SUSPENDED"
    elif count >= 2:
        producer["quality_flag"] = "PROBATION"
    elif count >= 1:
        producer["quality_flag"] = "STANDARD"
    else:
        producer["quality_flag"] = "PREMIUM"
