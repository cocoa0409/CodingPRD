"""Calculation rules (scaffold §1.3, PRD §3.x).

Every monetary value is integer cents. Half-up rounding via Decimal.
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple

import db


# ---- Constants (scaffold §1.3) ----------------------------------------------

SPOT_TIER1_PER_MILE_CENTS = 320   # distance_miles <= 250
SPOT_TIER2_PER_MILE_CENTS = 235   # 251 <= distance_miles <= 750
SPOT_TIER3_PER_MILE_CENTS = 195   # distance_miles >= 751
SPOT_FUEL_SURCHARGE_PER_MILE_CENTS = 65

EQUIPMENT_UPLIFT_PCT = {
    "DRY_VAN": Decimal("0"),
    "REEFER": Decimal("18"),
    "FLATBED": Decimal("10"),
}

SPOT_DETENTION_FREE_MINUTES = 120
SPOT_DETENTION_RATE_PER_HOUR_CENTS = 7500

FACTORING_BASE_PCT = Decimal("2.0")

# Credit-risk scoring
W_UTIL = Decimal("0.6")
W_LATE = 5
W_DISPUTE = 8
LATE_AGE_DAYS = 30

# SmartWay thresholds
SMARTWAY_PASS_THRESHOLD = Decimal("0.60")
SMARTWAY_AT_RISK_THRESHOLD = Decimal("0.40")

SAFETY_REJECT_THRESHOLD = Decimal("75.0")


def round_half_up_cents(value: Decimal) -> int:
    """Round a Decimal cent value to whole cents using half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_decimals(value: Decimal, places: int) -> Decimal:
    """Round a Decimal value to `places` decimal places using half-up."""
    q = Decimal("1").scaleb(-places)  # 10^-places
    return value.quantize(q, rounding=ROUND_HALF_UP)


# ---- Quote total at request (scaffold §1.3.quote_total_at_request) ----------

def find_covering_contract_rate(
    shipper_id: str,
    lane_origin: str,
    lane_destination: str,
    pickup_window_start_utc: str,
) -> Optional[Dict[str, Any]]:
    """Earliest-created ACTIVE ContractRate covering this lane and window."""
    pickup_dt = db.parse_iso_dt(pickup_window_start_utc)
    candidates = []
    for cr in db.contract_rates.values():
        if cr.get("status") != "ACTIVE":
            continue
        if cr.get("shipper_id") != shipper_id:
            continue
        if cr.get("lane_origin") != lane_origin:
            continue
        if cr.get("lane_destination") != lane_destination:
            continue
        eff_from = db.parse_iso_dt(cr["effective_from_utc"])
        eff_until = db.parse_iso_dt(cr["effective_until_utc"])
        if not (eff_from <= pickup_dt < eff_until):
            continue
        candidates.append(cr)
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x.get("created_at", ""), x.get("id", "")))
    return candidates[0]


def compute_quote_total(
    *,
    shipper_id: str,
    lane_origin: str,
    lane_destination: str,
    distance_miles: int,
    pickup_window_start_utc: str,
    requested_equipment: str,
) -> Dict[str, Any]:
    """Return dict with rate_mode, contract_rate_id, contract_rate_version, quoted_total_cents.

    Uses CONTRACT pricing when a covering ContractRate exists, else SPOT pricing
    with tiered per-mile + equipment uplift. Equipment uplift is rounded
    half-up to the nearest cent BEFORE being summed into quoted_total_cents.
    """
    cov = find_covering_contract_rate(
        shipper_id, lane_origin, lane_destination, pickup_window_start_utc
    )
    if cov is not None:
        linehaul = int(cov["rate_per_mile_cents"]) * distance_miles
        fuel = int(cov["fuel_surcharge_per_mile_cents"]) * distance_miles
        total = linehaul + fuel
        return {
            "rate_mode": "CONTRACT",
            "contract_rate_id": cov["id"],
            "contract_rate_version": int(cov["version"]),
            "quoted_total_cents": total,
        }
    # SPOT mode
    if distance_miles <= 250:
        base = SPOT_TIER1_PER_MILE_CENTS
    elif distance_miles <= 750:
        base = SPOT_TIER2_PER_MILE_CENTS
    else:
        base = SPOT_TIER3_PER_MILE_CENTS
    linehaul = base * distance_miles
    fuel = SPOT_FUEL_SURCHARGE_PER_MILE_CENTS * distance_miles
    uplift_pct = EQUIPMENT_UPLIFT_PCT.get(requested_equipment, Decimal("0"))
    raw_uplift = (uplift_pct / Decimal("100")) * Decimal(linehaul)
    uplift_cents = round_half_up_cents(raw_uplift)
    total = linehaul + fuel + uplift_cents
    return {
        "rate_mode": "SPOT",
        "contract_rate_id": None,
        "contract_rate_version": None,
        "quoted_total_cents": total,
    }


def estimate_quote_for_credit_guard(
    distance_miles: int,
    requested_equipment: str,
) -> int:
    """Conservative SPOT-mode estimate used for the credit guard (PRD §3.3, scaffold §1.4 #17).

    SPOT tier with NONE smartway (no equipment uplift) per the validation
    description: "estimated quote computed using SPOT tier with NONE smartway
    and distance_miles for fast preflight". We omit equipment uplift to
    deliberately produce a conservative figure.
    """
    if distance_miles <= 250:
        base = SPOT_TIER1_PER_MILE_CENTS
    elif distance_miles <= 750:
        base = SPOT_TIER2_PER_MILE_CENTS
    else:
        base = SPOT_TIER3_PER_MILE_CENTS
    linehaul = base * distance_miles
    fuel = SPOT_FUEL_SURCHARGE_PER_MILE_CENTS * distance_miles
    return linehaul + fuel


# ---- Detention charge (scaffold §1.3.detention_charge) ----------------------

def compute_detention_charge(load: Dict[str, Any]) -> int:
    """Pickup-detention only.

    detention_minutes_at_pickup = floor((actual_pickup - pickup_window_start) / 60)
        clipped at 0.
    free_min depends on rate_mode (CONTRACT vs SPOT).
    billable_minutes = max(0, detention_minutes_at_pickup - free_min)
    billable_hours   = ceil(billable_minutes / 60)
    detention_charge_cents = billable_hours * rate_per_hour_cents
    """
    quote = db.quote_requests.get(load["quote_request_id"])
    if quote is None:
        return 0
    pickup_start = db.parse_iso_dt(quote["pickup_window_start_utc"])
    actual_pickup = db.parse_iso_dt(load["actual_pickup_at_utc"])
    if pickup_start is None or actual_pickup is None:
        return 0
    delta_seconds = (actual_pickup - pickup_start).total_seconds()
    raw_minutes = math.floor(delta_seconds / 60)
    raw_minutes = max(0, raw_minutes)

    if quote.get("rate_mode") == "CONTRACT" and quote.get("contract_rate_id"):
        contract = db.contract_rates.get(quote["contract_rate_id"])
        if contract is None:
            # Defensive fallback — contract must still exist post-pin.
            free_min = SPOT_DETENTION_FREE_MINUTES
            rate_per_hour = SPOT_DETENTION_RATE_PER_HOUR_CENTS
        else:
            free_min = int(contract["detention_free_minutes"])
            rate_per_hour = int(contract["detention_rate_per_hour_cents"])
    else:
        free_min = SPOT_DETENTION_FREE_MINUTES
        rate_per_hour = SPOT_DETENTION_RATE_PER_HOUR_CENTS

    billable_minutes = max(0, raw_minutes - free_min)
    billable_hours = math.ceil(billable_minutes / 60)
    return billable_hours * rate_per_hour


# ---- Invoice total (scaffold §1.3.invoice_total_cents) ----------------------

def compute_invoice_total(load: Dict[str, Any], invoice_id: Optional[str]) -> int:
    """Invoice.total_cents = load.agreed_rate_cents + load.detention_charge_cents
       + sum(Accessorial.amount_cents on this load)
       - sum(RESOLVED+PARTIAL DisputeClaim.resolution_amount_cents on this invoice)
    """
    base = int(load.get("agreed_rate_cents", 0))
    detention = int(load.get("detention_charge_cents", 0))
    acc_total = sum(
        int(a["amount_cents"]) for a in db.accessorials.values()
        if a.get("load_id") == load["id"]
    )
    partial_credit = 0
    if invoice_id is not None:
        for dc in db.dispute_claims.values():
            if (
                dc.get("invoice_id") == invoice_id
                and dc.get("status") == "RESOLVED"
                and dc.get("resolution_kind") == "PARTIAL"
            ):
                partial_credit += int(dc.get("resolution_amount_cents") or 0)
    return base + detention + acc_total - partial_credit


def recompute_load_accessorial_total(load: Dict[str, Any]) -> int:
    total = sum(
        int(a["amount_cents"]) for a in db.accessorials.values()
        if a.get("load_id") == load["id"]
    )
    load["accessorial_total_cents"] = total
    return total


# ---- Factoring advance (scaffold §1.3.factoring_advance) --------------------

def factoring_floor_pct(safety_score: float) -> Decimal:
    """Safety-tiered floor for factoring_fee_pct.
       < 25 -> 2.0
       25..50 -> 2.5
       50..75 -> 3.5
       Carriers with safety_score >= 75 cannot be QUALIFIED.
    """
    if safety_score < 25:
        return FACTORING_BASE_PCT
    if safety_score < 50:
        return FACTORING_BASE_PCT + Decimal("0.5")
    if safety_score < 75:
        return FACTORING_BASE_PCT + Decimal("1.5")
    return FACTORING_BASE_PCT + Decimal("1.5")


def compute_factoring_advance(
    invoice_total_cents: int, requested_fee_pct: Decimal, safety_score: float
) -> int:
    floor = factoring_floor_pct(safety_score)
    actual_pct = max(floor, requested_fee_pct)
    raw = Decimal(invoice_total_cents) * (Decimal("100") - actual_pct) / Decimal("100")
    return round_half_up_cents(raw)


# ---- Shipper open AR invariant ----------------------------------------------

def shipper_loads(shipper_id: str):
    """Return all Loads whose quote_request -> shipper_id matches."""
    for ld in db.loads.values():
        q = db.quote_requests.get(ld.get("quote_request_id"))
        if q and q.get("shipper_id") == shipper_id:
            yield ld


def recompute_shipper_open_ar(shipper_id: str) -> int:
    """Sum of (Invoice.total_cents - Invoice.amount_paid_cents) over invoices
    whose load chain terminates at shipper_id and whose status is one of
    {ISSUED, PARTIALLY_PAID, DISPUTED}.
    """
    open_ar = 0
    load_ids = {ld["id"] for ld in shipper_loads(shipper_id)}
    for inv in db.invoices.values():
        if inv.get("load_id") not in load_ids:
            continue
        if inv.get("status") not in {"ISSUED", "PARTIALLY_PAID", "DISPUTED"}:
            continue
        open_ar += int(inv["total_cents"]) - int(inv.get("amount_paid_cents", 0))
    shipper = db.shippers.get(shipper_id)
    if shipper is not None:
        shipper["open_ar_cents"] = open_ar
        db.bump(shipper)
    return open_ar


# ---- Shipper credit-risk (scaffold §1.3.shipper_credit_risk_score) ----------

def compute_credit_risk(shipper_id: str) -> Dict[str, Any]:
    shipper = db.shippers.get(shipper_id)
    if shipper is None:
        return {"score": 0, "utilization_ratio": 0.0, "late_count": 0, "dispute_count": 0}

    credit_limit = int(shipper.get("credit_limit_cents", 0))
    open_ar = int(shipper.get("open_ar_cents", 0))
    util_ratio_raw = Decimal(open_ar) / Decimal(max(credit_limit, 1))

    now_dt = db.parse_iso_dt(db.get_current_utc())
    load_ids = {ld["id"] for ld in shipper_loads(shipper_id)}

    late_count = 0
    for inv in db.invoices.values():
        if inv.get("load_id") not in load_ids:
            continue
        if inv.get("status") != "PARTIALLY_PAID":
            continue
        inv_created = db.parse_iso_dt(inv.get("created_at"))
        if inv_created is None:
            continue
        if (now_dt - inv_created) > timedelta(days=LATE_AGE_DAYS):
            late_count += 1

    invoice_ids = {inv["id"] for inv in db.invoices.values() if inv.get("load_id") in load_ids}
    dispute_count = 0
    for dc in db.dispute_claims.values():
        if dc.get("invoice_id") not in invoice_ids:
            continue
        if dc.get("status") != "RESOLVED":
            continue
        if dc.get("resolution_kind") == "DENIED":
            continue
        dispute_count += 1

    # min(util, 1.0) * 100, no intermediate rounding on this term.
    util_capped = util_ratio_raw if util_ratio_raw < Decimal("1") else Decimal("1")
    score_raw = W_UTIL * util_capped * Decimal("100") + Decimal(W_LATE * late_count) + Decimal(W_DISPUTE * dispute_count)
    score = int(score_raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # Surface utilization_ratio as float for JSON. PRD does not specify
    # rounding for this field — keep raw value.
    return {
        "score": score,
        "utilization_ratio": float(util_ratio_raw),
        "late_count": late_count,
        "dispute_count": dispute_count,
    }


# ---- SmartWay audit (scaffold §1.3.smartway_quarterly_audit) ----------------

def parse_quarter(label: str) -> Tuple[datetime, datetime]:
    """Return [start, end) UTC for label like '2026Q2'."""
    year = int(label[:4])
    q = int(label[5])
    start_month = (q - 1) * 3 + 1
    start = datetime(year, start_month, 1, tzinfo=timezone.utc)
    end_month = start_month + 3
    end_year = year
    if end_month > 12:
        end_month -= 12
        end_year += 1
    end = datetime(end_year, end_month, 1, tzinfo=timezone.utc)
    return start, end


def compute_smartway_audit(shipper_id: str, quarter_label: str) -> Dict[str, Any]:
    qstart, qend = parse_quarter(quarter_label)
    shipper_load_ids = {ld["id"] for ld in shipper_loads(shipper_id)}
    eligible = []
    for ld in db.loads.values():
        if ld["id"] not in shipper_load_ids:
            continue
        if ld.get("status") not in {"DELIVERED", "INVOICED", "CLOSED"}:
            continue
        ad = ld.get("actual_delivery_at_utc")
        if not ad:
            continue
        ad_dt = db.parse_iso_dt(ad)
        if ad_dt is None:
            continue
        if not (qstart <= ad_dt < qend):
            continue
        eligible.append(ld)

    total_loads = len(eligible)
    smartway_loads = 0
    for ld in eligible:
        carrier = db.carriers.get(ld.get("carrier_id"))
        if carrier and carrier.get("smartway_tier") in {"BRONZE", "SILVER", "GOLD"}:
            smartway_loads += 1

    if total_loads == 0:
        ratio = Decimal("0")
        ratio_rounded = Decimal("0.0000")
        compliance = "FAILING"
    else:
        ratio = Decimal(smartway_loads) / Decimal(total_loads)
        ratio_rounded = round_half_up_decimals(ratio, 4)
        if ratio_rounded >= SMARTWAY_PASS_THRESHOLD:
            compliance = "PASSING"
        elif ratio_rounded >= SMARTWAY_AT_RISK_THRESHOLD:
            compliance = "AT_RISK"
        else:
            compliance = "FAILING"

    return {
        "total_loads": total_loads,
        "smartway_loads": smartway_loads,
        "smartway_ratio": float(ratio_rounded),
        "compliance_status": compliance,
    }
