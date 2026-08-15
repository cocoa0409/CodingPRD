"""Shared helpers: validation primitives, calculations, serializers."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import ApiError

# ---------------------------------------------------------------------------
# Constants from the calculation rules
# ---------------------------------------------------------------------------

STYRENE_CONTENT = {
    "POLYESTER": Decimal("0.35"),
    "VINYL_ESTER": Decimal("0.40"),
    "EPOXY": Decimal("0.0"),
}
EMISSION_FACTOR = Decimal("0.10")

PROTOTYPE_TOLERANCE_PCT = Decimal("0.08")
PROTOTYPE_MAX_QUANTITY = 5

TEMP_SLACK_C = 10
TEMP_AUTOREJECT_OVER_C = 8
SOAK_WEIGHT = Decimal("1.5")
TEMP_WEIGHT = Decimal("2.0")
RAMP_SLACK = Decimal("0.5")
PASS_MAX_SCORE = Decimal("5.0")

PASS_MAX_VOID_PCT = 2.0
REPAIR_MAX_VOID_PCT = 4.0
REPAIR_MAX_DELAM_CM2 = 25.0

RESIN_SYSTEMS = {"POLYESTER", "VINYL_ESTER", "EPOXY"}
TOOLING_PHASES = {"PROTOTYPE", "TRANSITION", "PRODUCTION"}
EQUIPMENT_KINDS = {"OVEN", "AUTOCLAVE"}
INSPECTION_METHODS = {"ULTRASONIC", "TAP_TEST", "VISUAL"}

WO_STATUSES = {
    "RELEASED", "LAYUP_IN_PROGRESS", "AWAITING_CURE", "CURE_SCHEDULED",
    "IN_CURE", "CURED", "IN_INSPECTION", "REPAIR", "ACCEPTED", "SCRAPPED",
}
SESSION_STATUSES = {"ACTIVE", "VOIDED"}
CYCLE_STATUSES = {"SCHEDULED", "RUNNING", "COMPLETED", "ABORTED"}
INSPECTION_RESULTS = {"PASS", "REPAIR_REQUIRED", "FAIL"}
REPAIR_STATUSES = {"OPEN", "CLOSED", "SUPERSEDED"}


def D(x):
    return Decimal(str(x))


def dec4(x):
    return D(x).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def dec1(x):
    return D(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def rhu_int(x):
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def bad_request(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        bad_request("Request body must be a JSON object")
    return b


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def f_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or v == "":
        bad_request("Field '%s' is required and must be a non-empty string" % name)
    return v


def f_num(b, name):
    v = b.get(name)
    if not is_num(v):
        bad_request("Field '%s' is required and must be a number" % name)
    return v


def f_int(b, name):
    v = b.get(name)
    if not is_int(v):
        bad_request("Field '%s' is required and must be an integer" % name)
    return v


def opt_num(b, name):
    v = b.get(name)
    if v is not None and not is_num(v):
        bad_request("Field '%s' must be a number" % name)
    return v


def opt_int(b, name):
    v = b.get(name)
    if v is not None and not is_int(v):
        bad_request("Field '%s' must be an integer" % name)
    return v


def parse_dt(v):
    """Parse an ISO 8601 datetime; returns aware UTC datetime or None."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def f_dt(b, name):
    raw = b.get(name)
    dt = parse_dt(raw)
    if dt is None:
        bad_request("Field '%s' is required and must be an ISO 8601 datetime" % name)
    return raw, dt


def fmt_clock(dt):
    """Normalized clock echo: no fractional part when zero."""
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return db.fmt_dt(dt)


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad_request("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            bad_request("Query parameter 'limit' must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad_request("Query parameter 'offset' must be an integer")
        if offset < 0:
            bad_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(records, serializer, filters):
    """filters: list of (query_param, record_key); equality filtering."""
    items = []
    for rec in records.values():
        ok = True
        for param, key in filters:
            val = request.args.get(param)
            if val is not None and str(rec.get(key)) != val:
                ok = False
                break
        if ok:
            items.append(rec)
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    limit, offset = pagination_params()
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return [serializer(r) for r in page], pagination


def not_found(what="Resource"):
    raise ApiError("ERR_NOT_FOUND", 404, "%s not found" % what)


def get_or_404(collection, rid, what="Resource"):
    rec = db.STORE[collection].get(rid)
    if rec is None:
        not_found(what)
    return rec


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def theoretical_part_weight_g(book):
    fiber = sum(D(p["areal_weight_g_m2"]) * D(book["part_area_m2"]) for p in book["plies"])
    return dec1(fiber / D(book["target_fiber_volume_pct"]))


def weight_deviation(actual, target):
    return dec4(abs(D(actual) - D(target)) / D(target))


def effective_pot_life(nominal, ambient):
    if ambient is None:
        return nominal
    factor = 0.5 ** ((float(ambient) - 20.0) / 10.0)
    return max(rhu_int(nominal * factor), 5)


def actual_ratio_pct(catalyst_mass_g, resin_mass_g):
    return dec4(D(catalyst_mass_g) / D(resin_mass_g) * 100)


def styrene_session_kg(resin_used_g, resin_system):
    return dec4(D(resin_used_g) * STYRENE_CONTENT[resin_system] * EMISSION_FACTOR / 1000)


def cure_deviation(score_cycle):
    """Returns (score: Decimal 1dp, cure_log_ok: bool)."""
    temp_term = TEMP_WEIGHT * max(Decimal("0"), abs(D(score_cycle["recorded_max_temp_c"]) - D(score_cycle["soak_temp_c"])) - TEMP_SLACK_C)
    soak_term = SOAK_WEIGHT * max(Decimal("0"), D(score_cycle["soak_minutes"]) - D(score_cycle["recorded_soak_minutes"]))
    ramp_term = Decimal("1.0") * max(Decimal("0"), abs(D(score_cycle["recorded_ramp_rate_c_per_min"]) - D(score_cycle["ramp_rate_c_per_min"])) - RAMP_SLACK)
    score = dec1(temp_term + soak_term + ramp_term)
    if D(score_cycle["recorded_max_temp_c"]) > D(score_cycle["soak_temp_c"]) + TEMP_AUTOREJECT_OVER_C:
        return score, False
    return score, score <= PASS_MAX_SCORE


def inspection_disposition(void_content_pct, delamination_area_cm2):
    if void_content_pct <= PASS_MAX_VOID_PCT and delamination_area_cm2 == 0:
        return "PASS"
    if void_content_pct <= REPAIR_MAX_VOID_PCT and delamination_area_cm2 <= REPAIR_MAX_DELAM_CM2:
        return "REPAIR_REQUIRED"
    return "FAIL"


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------

def select_permit():
    """ACTIVE permit covering now; ties: earliest period_start then created."""
    t = db.now()
    cands = [
        p for p in db.STORE["permits"].values()
        if p["status"] == "ACTIVE" and p["_period_start_dt"] <= t < p["_period_end_dt"]
    ]
    cands.sort(key=lambda p: (p["_period_start_dt"], p["_seq"]))
    return cands[0] if cands else None


def maybe_expire_batch(batch):
    """Lazy EXPIRED evaluation: only on batch reads and consumption attempts."""
    if batch["status"] in ("MIXED", "PARTIALLY_CONSUMED") and db.now() > batch["_expires_dt"]:
        batch["status"] = "EXPIRED"
        db.touch(batch)


def batch_remaining(batch):
    return batch["_total"] - batch["_consumed"] - batch["_quenched"]


def mold_occupied_by_other(wo):
    """Any other work order on the same mold currently occupying it."""
    for other in db.STORE["work_orders"].values():
        if other["id"] == wo["id"] or other["mold_id"] != wo["mold_id"]:
            continue
        if other["layup_started_at"] is not None and other["demolded_at"] is None:
            return other
    return None


def mold_currently_occupied(mold_id):
    for other in db.STORE["work_orders"].values():
        if other["mold_id"] != mold_id:
            continue
        if other["layup_started_at"] is not None and other["demolded_at"] is None:
            return other
    return None


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def permit_out(p):
    quota = D(p["styrene_quota_kg"])
    over = p["_styrene_used"] >= D(p["warning_threshold_pct"]) * quota
    return {
        "id": p["id"],
        "permit_code": p["permit_code"],
        "period_start": p["period_start"],
        "period_end": p["period_end"],
        "styrene_quota_kg": p["styrene_quota_kg"],
        "warning_threshold_pct": p["warning_threshold_pct"],
        "styrene_used_kg": float(p["_styrene_used"]),
        "status": p["status"],
        "over_warning": over,
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def mold_out(m):
    return {
        "id": m["id"],
        "mold_code": m["mold_code"],
        "tooling_phase": m["tooling_phase"],
        "maintenance_interval_cycles": m["maintenance_interval_cycles"],
        "cycles_since_maintenance": m["cycles_since_maintenance"],
        "prototype_parts_required": m["prototype_parts_required"],
        "prototype_parts_validated": m["prototype_parts_validated"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ply_book_out(b):
    return {
        "id": b["id"],
        "part_number": b["part_number"],
        "revision": b["revision"],
        "part_area_m2": b["part_area_m2"],
        "plies": b["plies"],
        "resin_system": b["resin_system"],
        "target_fiber_volume_pct": b["target_fiber_volume_pct"],
        "tolerance_pct": b["tolerance_pct"],
        "max_repair_attempts": b["max_repair_attempts"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def work_order_out(w):
    return {
        "id": w["id"],
        "work_order_no": w["work_order_no"],
        "part_number": w["part_number"],
        "mold_id": w["mold_id"],
        "ply_book_id": w["ply_book_id"],
        "pinned_ply_book_version": w["pinned_ply_book_version"],
        "quantity": w["quantity"],
        "due_date": w["due_date"],
        "target_part_weight_g": w["target_part_weight_g"],
        "actual_part_weight_g": w["actual_part_weight_g"],
        "weight_deviation_pct": w["weight_deviation_pct"],
        "layup_started_at": w["layup_started_at"],
        "demolded_at": w["demolded_at"],
        "repair_count": w["repair_count"],
        "scrap_reason": w["scrap_reason"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def resin_batch_out(b):
    return {
        "id": b["id"],
        "batch_code": b["batch_code"],
        "resin_system": b["resin_system"],
        "resin_mass_g": b["resin_mass_g"],
        "catalyst_mass_g": b["catalyst_mass_g"],
        "target_ratio_pct": b["target_ratio_pct"],
        "ratio_tolerance_pct": b["ratio_tolerance_pct"],
        "actual_ratio_pct": float(b["_actual_ratio"]),
        "nominal_pot_life_minutes": b["nominal_pot_life_minutes"],
        "ambient_temp_c": b["ambient_temp_c"],
        "effective_pot_life_minutes": b["effective_pot_life_minutes"],
        "mixed_at": b["mixed_at"],
        "expires_at": b["expires_at"],
        "total_mass_g": float(b["_total"]),
        "consumed_mass_g": float(b["_consumed"]),
        "remaining_mass_g": float(batch_remaining(b)),
        "quenched_mass_g": float(b["_quenched"]),
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def layup_session_out(s):
    return {
        "id": s["id"],
        "work_order_id": s["work_order_id"],
        "resin_batch_id": s["resin_batch_id"],
        "permit_id": s["permit_id"],
        "resin_used_g": s["resin_used_g"],
        "styrene_emitted_kg": float(s["_styrene_kg"]),
        "laminator_id": s["laminator_id"],
        "session_at": s["session_at"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def equipment_out(e):
    return {
        "id": e["id"],
        "equipment_code": e["equipment_code"],
        "kind": e["kind"],
        "max_parts_per_cycle": e["max_parts_per_cycle"],
        "turnaround_minutes": e["turnaround_minutes"],
        "max_temperature_c": e["max_temperature_c"],
        "max_pressure_bar": e["max_pressure_bar"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def cure_cycle_out(c):
    return {
        "id": c["id"],
        "work_order_id": c["work_order_id"],
        "equipment_id": c["equipment_id"],
        "ramp_rate_c_per_min": c["ramp_rate_c_per_min"],
        "soak_temp_c": c["soak_temp_c"],
        "soak_minutes": c["soak_minutes"],
        "pressure_bar": c["pressure_bar"],
        "scheduled_start": c["scheduled_start"],
        "scheduled_end": c["scheduled_end"],
        "uses_mold": c["uses_mold"],
        "recorded_min_temp_c": c["recorded_min_temp_c"],
        "recorded_max_temp_c": c["recorded_max_temp_c"],
        "recorded_soak_minutes": c["recorded_soak_minutes"],
        "recorded_ramp_rate_c_per_min": c["recorded_ramp_rate_c_per_min"],
        "cure_deviation_score": (float(c["_score"]) if c["_score"] is not None else None),
        "cure_log_ok": c["cure_log_ok"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def inspection_out(i):
    return {
        "id": i["id"],
        "work_order_id": i["work_order_id"],
        "inspector_id": i["inspector_id"],
        "method": i["method"],
        "void_content_pct": i["void_content_pct"],
        "delamination_area_cm2": i["delamination_area_cm2"],
        "result": i["result"],
        "inspected_at": i["inspected_at"],
        "created_repair_id": i["created_repair_id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def repair_out(r):
    return {
        "id": r["id"],
        "work_order_id": r["work_order_id"],
        "source_inspection_id": r["source_inspection_id"],
        "repair_seq": r["repair_seq"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
