"""Domain services: parsing helpers, serializers, derived-field computation,
threshold verdicts, cascades, and the synchronous posture/pool sweep."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import store, logical_date, fmt_ts, touch, new_resource, by_creation
from errors import ApiError, err_not_found

GAL_PER_ACRE_FOOT = Decimal("325851")
AF_QUANT = Decimal("0.001")
MAX_WASH_CYCLES = 150
WASHER_PURGE = timedelta(minutes=30)
TARGET_DAYS = 2


# ---------------------------------------------------------------------------
# Request body / field parsing
# ---------------------------------------------------------------------------

def get_body():
    """Parse the JSON request body. Missing body -> {}; invalid JSON -> 400."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("ERR_INVALID_REQUEST", "request body must be valid JSON", 400)
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object", 400)
    return data


def as_int(v):
    if isinstance(v, bool):
        return None, False
    if isinstance(v, int):
        return v, True
    return None, False


def as_number(v):
    if isinstance(v, bool):
        return None, False
    if isinstance(v, (int, float)):
        return float(v), True
    return None, False


def as_date(v):
    if not isinstance(v, str):
        return None, False
    try:
        return datetime.strptime(v, "%Y-%m-%d").date(), True
    except ValueError:
        return None, False


def as_datetime(v):
    if not isinstance(v, str):
        return None, False
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None, False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc), True


def raise_shape(errs):
    if errs:
        raise ApiError("ERR_INVALID_REQUEST", "; ".join(errs), 400)


def get_or_404(coll, rid, what="resource"):
    r = coll.get(rid)
    if r is None:
        raise err_not_found(what)
    return r


# ---------------------------------------------------------------------------
# Derived fields (computed on read — never stored, never fed back)
# ---------------------------------------------------------------------------

def _event_ym(e):
    d = e["_date"]
    return (d.year, d.month)


def permit_aggregates(permit):
    """Provisional = RECORDED + FINALIZED; certified = FINALIZED only."""
    cur = logical_date()
    cur_ym = (cur.year, cur.month)
    tp = tc = mp = mc = 0
    for e in store.withdrawal_events.values():
        if e["permit_id"] != permit["id"] or e["status"] == "VOIDED":
            continue
        fin = e["status"] == "FINALIZED"
        d = e["_date"]
        if d == cur:
            tp += e["gallons"]
            if fin:
                tc += e["gallons"]
        if _event_ym(e) == cur_ym:
            mp += e["gallons"]
            if fin:
                mc += e["gallons"]
    return tp, tc, mp, mc


def month_provisional(permit):
    cur = logical_date()
    total = 0
    for e in store.withdrawal_events.values():
        if (
            e["permit_id"] == permit["id"]
            and e["status"] in ("RECORDED", "FINALIZED")
            and _event_ym(e) == (cur.year, cur.month)
        ):
            total += e["gallons"]
    return total


def line_free_units(line):
    return line["preform_on_hand_units"] - line["preform_reserved_units"]


def line_reorder_quantity(line):
    inbound = sum(
        d["delivered_units"]
        for d in store.deliveries.values()
        if d["line_id"] == line["id"] and d["status"] == "PENDING_QC"
    )
    target = line["daily_capacity_units"] * TARGET_DAYS
    return max(
        0,
        target
        + line["preform_reserved_units"]
        - line["preform_on_hand_units"]
        - inbound,
    )


def batch_bottle_count(batch):
    return sum(
        1
        for b in store.bottles.values()
        if b.get("current_wash_batch_id") == batch["id"]
    )


# ---------------------------------------------------------------------------
# Threshold verdicts (parameters compared exactly as recorded; a parameter
# exactly at its threshold passes)
# ---------------------------------------------------------------------------

def treatment_verdict(run):
    permit = store.permits.get(run["source_permit_id"])
    turbidity = run.get("turbidity_ntu")
    uv = run.get("uv_dose_mj_cm2")
    ozone = run.get("ozone_ct_mg_min_l")
    micro = run.get("micro_pore_micron")
    ro = run.get("ro_rejection_pct")
    if turbidity is None or uv is None or ozone is None or micro is None:
        return "FAIL"
    if turbidity > 0.3:
        return "FAIL"
    if uv < 40.0:
        return "FAIL"
    if ozone < 1.6:
        return "FAIL"
    if permit is not None and permit["source_classification"] == "SPRING":
        if micro > 0.2:
            return "FAIL"
    else:
        if ro is None or ro < 95.0:
            return "FAIL"
    return "PASS"


def wash_verdict(rinse_temp_c, sanitizer_ppm):
    if rinse_temp_c < 71.1:
        return "FAIL"
    if sanitizer_ppm < 50.0:
        return "FAIL"
    return "PASS"


# ---------------------------------------------------------------------------
# Community report volumes — per-source convert-then-round, then sum
# ---------------------------------------------------------------------------

def compute_report_volumes(plant_id, year, month):
    permits = by_creation(
        [p for p in store.permits.values() if p["plant_id"] == plant_id]
    )
    breakdown = []
    total_gallons = 0
    total_af = Decimal("0")
    for p in permits:
        g = 0
        for e in store.withdrawal_events.values():
            if (
                e["permit_id"] == p["id"]
                and e["status"] == "FINALIZED"
                and _event_ym(e) == (year, month)
            ):
                g += e["gallons"]
        af = (Decimal(g) / GAL_PER_ACRE_FOOT).quantize(AF_QUANT, rounding=ROUND_HALF_UP)
        breakdown.append({"permit_id": p["id"], "gallons": g, "acre_feet": float(af)})
        total_gallons += g
        total_af += af
    total_af = total_af.quantize(AF_QUANT, rounding=ROUND_HALF_UP)
    return total_gallons, float(total_af), breakdown


# ---------------------------------------------------------------------------
# Cascades and the synchronous posture/pool sweep
# ---------------------------------------------------------------------------

def suspend_permit(permit, reason):
    """ACTIVE -> SUSPENDED; cancels SCHEDULED treatment runs on the permit."""
    if permit["status"] != "ACTIVE":
        return False
    permit["status"] = "SUSPENDED"
    permit["suspension_reason"] = reason
    touch(permit)
    for run in by_creation(list(store.treatment_runs.values())):
        if run["source_permit_id"] == permit["id"] and run["status"] == "SCHEDULED":
            run["status"] = "CANCELLED"
            touch(run)
    return True


def compute_posture(plant):
    pid = plant["id"]
    suspended = any(
        p["plant_id"] == pid and p["status"] == "SUSPENDED"
        for p in store.permits.values()
    )
    open_recall = any(
        r["plant_id"] == pid and r["status"] in ("INITIATED", "RECOVERING")
        for r in store.recalls.values()
    )
    overdue_src = any(
        t["plant_id"] == pid
        and t["test_type"] == "SOURCE_RAW"
        and t["status"] == "OVERDUE"
        for t in store.lab_tests.values()
    )
    if suspended or open_recall or overdue_src:
        return "BREACH"
    overdue_any = any(
        t["plant_id"] == pid and t["status"] == "OVERDUE"
        for t in store.lab_tests.values()
    )
    watch_usage = any(
        p["plant_id"] == pid
        and p["status"] == "ACTIVE"
        and month_provisional(p) * 100 >= 90 * p["monthly_cap_gallons"]
        for p in store.permits.values()
    )
    if overdue_any or watch_usage:
        return "WATCH"
    return "GREEN"


def compute_pools(plant):
    gross = 0
    sanitized = 0
    for b in store.bottles.values():
        if b["plant_id"] != plant["id"]:
            continue
        if b["status"] in ("SANITIZED", "FILLED", "WITH_CUSTOMER"):
            gross += 1
        if b["status"] == "SANITIZED":
            sanitized += 1
    return gross, sanitized


def sweep():
    """Recompute every plant's posture and bottle pools; a changed derived
    value is a mutation of the plant (updated_at refresh, version +1)."""
    for plant in store.plants.values():
        posture = compute_posture(plant)
        gross, sanitized = compute_pools(plant)
        changed = False
        if posture != plant["compliance_posture"]:
            plant["compliance_posture"] = posture
            changed = True
        if gross != plant["bottle_gross_pool_units"]:
            plant["bottle_gross_pool_units"] = gross
            changed = True
        if sanitized != plant["bottle_sanitized_pool_units"]:
            plant["bottle_sanitized_pool_units"] = sanitized
            changed = True
        if changed:
            touch(plant)


def create_lab_test(plant_id, test_type, subject_field, subject_id, due_date, origin):
    due_str = due_date.isoformat()
    t = new_resource(
        {
            "plant_id": plant_id,
            "test_type": test_type,
            "subject_permit_id": None,
            "subject_lot_id": None,
            "subject_wash_batch_id": None,
            "due_date": due_str,
            "result": "PENDING",
            "status": "SCHEDULED",
            "collected_at": None,
            "origin": origin,
        }
    )
    t[subject_field] = subject_id
    t["_due"] = due_date
    store.lab_tests[t["id"]] = t
    return t


# ---------------------------------------------------------------------------
# Serializers (explicit field whitelists; internal _-prefixed keys excluded)
# ---------------------------------------------------------------------------

def plant_json(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "compliance_posture": p["compliance_posture"],
        "ops_run_index": p["ops_run_index"],
        "bottle_gross_pool_units": p["bottle_gross_pool_units"],
        "bottle_sanitized_pool_units": p["bottle_sanitized_pool_units"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def permit_json(p):
    tp, tc, mp, mc = permit_aggregates(p)
    return {
        "id": p["id"],
        "plant_id": p["plant_id"],
        "permit_number": p["permit_number"],
        "source_classification": p["source_classification"],
        "daily_cap_gallons": p["daily_cap_gallons"],
        "monthly_cap_gallons": p["monthly_cap_gallons"],
        "valid_from": p["valid_from"],
        "valid_to": p["valid_to"],
        "status": p["status"],
        "suspension_reason": p["suspension_reason"],
        "withdrawn_today_provisional_gallons": tp,
        "withdrawn_today_certified_gallons": tc,
        "withdrawn_month_provisional_gallons": mp,
        "withdrawn_month_certified_gallons": mc,
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def event_json(e):
    return {
        "id": e["id"],
        "permit_id": e["permit_id"],
        "withdrawal_date": e["withdrawal_date"],
        "gallons": e["gallons"],
        "meter_reading_start_gallons": e["meter_reading_start_gallons"],
        "meter_reading_end_gallons": e["meter_reading_end_gallons"],
        "status": e["status"],
        "supersedes_event_id": e["supersedes_event_id"],
        "finalized_at": e["finalized_at"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def run_json(r):
    return {
        "id": r["id"],
        "plant_id": r["plant_id"],
        "source_permit_id": r["source_permit_id"],
        "scheduled_start": r["scheduled_start"],
        "scheduled_end": r["scheduled_end"],
        "uv_dose_mj_cm2": r["uv_dose_mj_cm2"],
        "ozone_ct_mg_min_l": r["ozone_ct_mg_min_l"],
        "turbidity_ntu": r["turbidity_ntu"],
        "micro_pore_micron": r["micro_pore_micron"],
        "ro_rejection_pct": r["ro_rejection_pct"],
        "status": r["status"],
        "validation_round": r["validation_round"],
        "parameters_recorded_by_user_id": r["parameters_recorded_by_user_id"],
        "validated_by_user_id": r["validated_by_user_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def test_json(t):
    return {
        "id": t["id"],
        "plant_id": t["plant_id"],
        "test_type": t["test_type"],
        "subject_permit_id": t["subject_permit_id"],
        "subject_lot_id": t["subject_lot_id"],
        "subject_wash_batch_id": t["subject_wash_batch_id"],
        "due_date": t["due_date"],
        "result": t["result"],
        "status": t["status"],
        "collected_at": t["collected_at"],
        "origin": t["origin"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def line_json(l):
    return {
        "id": l["id"],
        "plant_id": l["plant_id"],
        "line_code": l["line_code"],
        "daily_capacity_units": l["daily_capacity_units"],
        "preform_on_hand_units": l["preform_on_hand_units"],
        "preform_reserved_units": l["preform_reserved_units"],
        "preform_free_units": line_free_units(l),
        "preform_reorder_quantity": line_reorder_quantity(l),
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def delivery_json(d):
    return {
        "id": d["id"],
        "line_id": d["line_id"],
        "supplier": d["supplier"],
        "delivered_units": d["delivered_units"],
        "accepted_units": d["accepted_units"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def lot_json(lot):
    return {
        "id": lot["id"],
        "line_id": lot["line_id"],
        "treatment_run_id": lot["treatment_run_id"],
        "label_classification": lot["label_classification"],
        "planned_units": lot["planned_units"],
        "produced_units": lot["produced_units"],
        "scheduled_start": lot["scheduled_start"],
        "scheduled_end": lot["scheduled_end"],
        "status": lot["status"],
        "rework_count": lot["rework_count"],
        "recall_id": lot["recall_id"],
        "completed_by_user_id": lot["completed_by_user_id"],
        "released_by_user_id": lot["released_by_user_id"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def recall_json(r):
    return {
        "id": r["id"],
        "plant_id": r["plant_id"],
        "reason": r["reason"],
        "status": r["status"],
        "units_in_scope": r["units_in_scope"],
        "units_recovered": r["units_recovered"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def bottle_json(b):
    return {
        "id": b["id"],
        "plant_id": b["plant_id"],
        "bottle_code": b["bottle_code"],
        "wash_cycle_count": b["wash_cycle_count"],
        "status": b["status"],
        "last_wash_batch_id": b["last_wash_batch_id"],
        "current_wash_batch_id": b["current_wash_batch_id"],
        "last_filled_lot_id": b["last_filled_lot_id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def batch_json(w):
    return {
        "id": w["id"],
        "plant_id": w["plant_id"],
        "washer_unit": w["washer_unit"],
        "scheduled_start": w["scheduled_start"],
        "scheduled_end": w["scheduled_end"],
        "rinse_temp_c": w["rinse_temp_c"],
        "sanitizer_ppm": w["sanitizer_ppm"],
        "status": w["status"],
        "bottle_count": batch_bottle_count(w),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def report_json(r):
    return {
        "id": r["id"],
        "plant_id": r["plant_id"],
        "period_year": r["period_year"],
        "period_month": r["period_month"],
        "status": r["status"],
        "total_withdrawn_gallons": r["total_withdrawn_gallons"],
        "total_acre_feet": r["total_acre_feet"],
        "per_source_breakdown": r["per_source_breakdown"],
        "addendum_of_report_id": r["addendum_of_report_id"],
        "published_at": r["published_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
