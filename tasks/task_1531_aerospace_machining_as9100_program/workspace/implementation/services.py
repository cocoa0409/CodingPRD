"""Business logic: calculations, cascade helpers, shared predicates."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, fmt_ts, base_record, touch
from errors import (
    ApiError,
    ERR_ESCAPE_REPORT_NOT_FOUND,
)

# Constants pinned by the calculation rules
SPECIAL_PROCESS_SURCHARGE_PCT = Decimal("0.10")
LABOR_RATE_CENTS_PER_HOUR = Decimal("12500")
MIN_MEASUREMENTS = 5
SPC_WINDOW = 25
CPK_THRESHOLD = Decimal("1.33")
READY_MIN = 100
MARGINAL_MIN = 80
SUSPEND_AFTER = 2
ESCAPE_WINDOW_HOURS = 48

D_1 = Decimal("1")
D_001 = Decimal("0.001")
D_0001 = Decimal("0.0001")


def dec(v):
    """Exact Decimal from a JSON number."""
    return Decimal(str(v))


def round_cents(d):
    return int(d.quantize(D_1, rounding=ROUND_HALF_UP))


def num_out(d):
    """JSON-friendly number: int when integral, else float."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# po_unit_price (tiered pricing, surcharge, annual escalation; single rounding)
# ---------------------------------------------------------------------------
def compute_po_pricing(lta, quantity, requires_special_process, delivery_year):
    tiers = sorted(lta["pricing_tiers"], key=lambda t: t["min_qty"])
    eligible = [t for t in tiers if quantity >= t["min_qty"]]
    tier = eligible[-1] if eligible else tiers[0]
    unit = dec(tier["unit_price_cents"])
    if requires_special_process:
        unit = unit * (D_1 + SPECIAL_PROCESS_SURCHARGE_PCT)
    esc = dec(lta["escalation_pct_per_year"])
    years = int(delivery_year) - int(lta["award_year"])
    unit = unit * ((D_1 + esc) ** years)
    unit_price_cents = round_cents(unit)
    return unit_price_cents, int(quantity) * unit_price_cents


# ---------------------------------------------------------------------------
# ncr_disposition_cost (round each unit first, then multiply)
# ---------------------------------------------------------------------------
def ncr_cost_cents(hours_per_unit, material_cents_per_unit, quantity_affected):
    per_unit_raw = dec(hours_per_unit) * LABOR_RATE_CENTS_PER_HOUR + dec(
        material_cents_per_unit
    )
    per_unit = round_cents(per_unit_raw)
    return per_unit * int(quantity_affected)


# ---------------------------------------------------------------------------
# spc_capability_index (provisional: n-1; final: n)
# ---------------------------------------------------------------------------
def spc_measurements_for(wo_id, characteristic_id):
    ms = [
        m
        for m in db.spc_measurements.values()
        if m["wo_id"] == wo_id and m["characteristic_id"] == characteristic_id
    ]
    ms.sort(key=lambda m: (m["_created_dt"], m["_seq"]))
    return ms


def compute_cpk(values, usl_d, lsl_d, final):
    """values: list of Decimals (already windowed). Returns rounded 3-dp cpk."""
    n = len(values)
    mean = sum(values) / n
    if n == 1:
        var = Decimal(0)
    elif final:
        var = sum((v - mean) ** 2 for v in values) / n
    else:
        var = sum((v - mean) ** 2 for v in values) / (n - 1)
    sd = var.sqrt()
    margin = min(usl_d - mean, mean - lsl_d)
    if sd == 0:
        cpk = Decimal("999.999") if margin >= 0 else Decimal("0")
    else:
        cpk = margin / (Decimal(3) * sd)
    return cpk.quantize(D_001, rounding=ROUND_HALF_UP)


def evaluate_characteristic(char, wo_id, final):
    """Recompute cpk for (wo, char) from the last 25 measurements.

    Returns (new_status_or_None, cpk_or_None). new_status is None when fewer
    than MIN_MEASUREMENTS exist (caller then leaves/sets MONITORING).
    """
    ms = spc_measurements_for(wo_id, char["id"])
    window = ms[-SPC_WINDOW:]
    if len(window) < MIN_MEASUREMENTS:
        return None, None
    values = [dec(m["measured_value"]) for m in window]
    cpk = compute_cpk(values, char["_usl_d"], char["_lsl_d"], final)
    status = "CAPABLE" if cpk >= CPK_THRESHOLD else "INCAPABLE"
    return status, cpk


# ---------------------------------------------------------------------------
# Aggregate recomputes
# ---------------------------------------------------------------------------
def recompute_fai_completeness(fai):
    chars = [c for c in db.characteristics.values() if c["fai_id"] == fai["id"]]
    fai["characteristic_count"] = len(chars)
    fai["measured_count"] = sum(1 for c in chars if c["result"] in ("PASS", "FAIL"))
    fai["characteristics_complete"] = (
        len(chars) >= 1 and fai["measured_count"] == len(chars)
    )
    touch(fai)


def recompute_wo_counters(wo, bump=True):
    serials = [s for s in db.serials.values() if s["wo_id"] == wo["id"]]
    wo["serials_created_count"] = len(serials)
    wo["good_quantity"] = sum(
        1 for s in serials if s["status"] in ("CREATED", "SHIPPED", "QUARANTINED")
    )
    wo["scrapped_quantity"] = sum(1 for s in serials if s["status"] == "SCRAPPED")
    if bump:
        touch(wo)


def recompute_wo_spc_status(wo):
    counts = {}
    chars = {}
    for m in db.spc_measurements.values():
        if m["wo_id"] == wo["id"]:
            counts[m["characteristic_id"]] = counts.get(m["characteristic_id"], 0) + 1
            c = db.characteristics.get(m["characteristic_id"])
            if c is not None:
                chars[c["id"]] = c
    if any(c["spc_eval_status"] == "INCAPABLE" for c in chars.values()):
        wo["spc_status"] = "INCAPABLE"
        return
    evaluated = [cid for cid in chars if counts.get(cid, 0) >= MIN_MEASUREMENTS]
    if evaluated and all(chars[cid]["spc_eval_status"] == "CAPABLE" for cid in evaluated):
        wo["spc_status"] = "CAPABLE"
    else:
        wo["spc_status"] = "MONITORING"


# ---------------------------------------------------------------------------
# NCR / escape helpers
# ---------------------------------------------------------------------------
def create_ncr(
    wo_id,
    defect_code,
    description,
    quantity_affected,
    affected_serial_ids,
    detected_post_shipment,
    origin,
    discovered_by_user_id,
):
    rec = base_record(db.new_id())
    rec.update(
        {
            "wo_id": wo_id,
            "defect_code": defect_code,
            "description": description,
            "quantity_affected": quantity_affected,
            "affected_serial_ids": list(affected_serial_ids),
            "detected_post_shipment": bool(detected_post_shipment),
            "origin": origin,
            "discovered_by_user_id": discovered_by_user_id,
            "disposition": None,
            "disposition_by_user_id": None,
            "estimated_cost_cents": None,
            "actual_cost_cents": None,
            "concession_approved": False,
            "status": "OPEN",
        }
    )
    db.ncrs[rec["id"]] = rec
    if detected_post_shipment:
        create_escape_report(rec)
    return rec


def create_escape_report(ncr):
    due_dt = ncr["_created_dt"] + timedelta(hours=ESCAPE_WINDOW_HOURS)
    rec = base_record(db.new_id())
    rec.update(
        {
            "ncr_id": ncr["id"],
            "due_at": fmt_ts(due_dt),
            "submitted_at": None,
            "status": "DRAFT",
            "_due_dt": due_dt,
        }
    )
    db.escape_reports[rec["id"]] = rec
    return rec


def open_ncr_blocks_serial(serial_id):
    for n in db.ncrs.values():
        if n["status"] in ("OPEN", "MRB_REVIEW") and serial_id in n["affected_serial_ids"]:
            return True
    return False


def wo_has_open_ncr(wo_id):
    return any(
        n["wo_id"] == wo_id and n["status"] in ("OPEN", "MRB_REVIEW")
        for n in db.ncrs.values()
    )


# ---------------------------------------------------------------------------
# Shipment shared logic (single ship and atomic ship-all)
# ---------------------------------------------------------------------------
def check_serial_shippable(serial):
    """State/business preconditions shared by ship and ship-all.

    The caller checks serial.status == CREATED first where applicable.
    Returns (wo, po, cert).
    """
    from errors import (
        ERR_MATERIAL_CERT_REVOKED,
        ERR_SERIAL_UNDER_NCR,
        ERR_WO_NOT_ACCEPTABLE,
    )

    wo = db.work_orders[serial["wo_id"]]
    po = db.purchase_orders[wo["po_id"]]
    if wo["status"] != "COMPLETED":
        raise ApiError(ERR_WO_NOT_ACCEPTABLE, 409, "Work order is not COMPLETED")
    cert = db.material_certs[serial["material_cert_id"]]
    if cert["status"] != "ACCEPTED":
        raise ApiError(ERR_MATERIAL_CERT_REVOKED, 422, "Material cert is not ACCEPTED")
    if open_ncr_blocks_serial(serial["id"]):
        raise ApiError(ERR_SERIAL_UNDER_NCR, 422, "Serial is listed on an open NCR")
    return wo, po, cert


def ship_serial(serial):
    wo, po, _cert = check_serial_shippable(serial)
    serial["status"] = "SHIPPED"
    serial["shipped_at"] = db.now_iso()
    serial["_shipped_dt"] = db.now()
    touch(serial)
    po["delivered_quantity"] += 1
    if po["delivered_quantity"] == po["quantity"] and po["status"] == "RELEASED":
        po["status"] = "CLOSED"
        po["_closed_dt"] = db.now()
    touch(po)
    return wo, po


# ---------------------------------------------------------------------------
# lta_annual_volume_rebate
# ---------------------------------------------------------------------------
def rebate_preview(lta, year):
    gross = 0
    for po in db.purchase_orders.values():
        if po["lta_id"] != lta["id"] or po["status"] != "CLOSED":
            continue
        closed_dt = po.get("_closed_dt")
        if closed_dt is not None and closed_dt.year == year:
            gross += po["total_cents"]
    tier = None
    for t in sorted(lta["rebate_tiers"], key=lambda x: x["min_invoiced_cents"]):
        if gross >= t["min_invoiced_cents"]:
            tier = t
    rebate_pct = tier["rebate_pct"] if tier is not None else 0
    rebate_cents = round_cents(Decimal(gross) * dec(rebate_pct))
    return {
        "year": year,
        "gross_invoiced_cents": gross,
        "rebate_pct": rebate_pct,
        "rebate_cents": rebate_cents,
        "net_cents": gross - rebate_cents,
    }


# ---------------------------------------------------------------------------
# rate_readiness_score
# ---------------------------------------------------------------------------
def run_rate_audit(lta):
    month = db.current_month()
    demonstrated = 0
    for wo in db.work_orders.values():
        if wo["status"] != "COMPLETED":
            continue
        po = db.purchase_orders.get(wo["po_id"])
        if po is None or po["lta_id"] != lta["id"]:
            continue
        cdt = wo.get("_completed_dt")
        if cdt is not None and cdt.strftime("%Y-%m") == month:
            demonstrated += wo["quantity"]
    pct = round_cents(
        (Decimal(100) * Decimal(demonstrated))
        / Decimal(lta["committed_monthly_rate_units"])
    )
    if pct >= READY_MIN:
        result = "READY"
    elif pct >= MARGINAL_MIN:
        result = "MARGINAL"
    else:
        result = "NOT_READY"

    # Re-run within the same month replaces the stored result: undo the
    # previous contribution of this month's audit before applying the new one.
    if lta["last_audit_month"] == month and lta.get("_audit_month_counted"):
        lta["consecutive_not_ready_count"] -= 1
        lta["_audit_month_counted"] = False

    if result == "NOT_READY":
        lta["consecutive_not_ready_count"] += 1
        lta["_audit_month_counted"] = True
    else:
        lta["consecutive_not_ready_count"] = 0
        lta["_audit_month_counted"] = False

    lta["last_audit_month"] = month
    lta["last_audit_result"] = result

    if (
        lta["consecutive_not_ready_count"] >= SUSPEND_AFTER
        and lta["status"] == "ACTIVE"
    ):
        lta["status"] = "SUSPENDED"
    touch(lta)
    return lta
