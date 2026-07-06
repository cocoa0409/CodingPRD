from flask import Blueprint

from db import db
from middleware import require_auth
from response import success
from helpers import (
    stamp_create, serialize, get_json_body, get_or_404,
    as_int, as_str, as_bool, as_enum, paginate, sorted_by_created,
)
from errors import err

bp = Blueprint("config", __name__)


# ---------------- Packages ----------------
@bp.post("/refractive/packages")
@require_auth(["Coordinator"])
def create_package():
    body = get_json_body()
    tier = as_enum(body, "tier", {"STANDARD", "PREMIUM", "LIFETIME"})
    base_price = as_int(body, "base_price_cents")
    deposit = as_int(body, "deposit_cents")
    window_days = as_int(body, "enhancement_window_days")
    guarantee = _as_num(body, "outcome_guarantee_uncorrected_va")
    refund_mode = as_enum(body, "refund_mode", {"PRO_RATA", "DEPOSIT_FORFEIT"})
    active = as_bool(body, "active", allow_missing=True, default=True)

    if base_price < 0:
        raise err("ERR_INVALID_REQUEST", "base_price_cents must be >= 0")
    if deposit < 0 or deposit > base_price:
        raise err("ERR_INVALID_REQUEST", "deposit_cents must be 0..base_price_cents")
    if window_days < 0:
        raise err("ERR_INVALID_REQUEST", "enhancement_window_days must be >= 0")
    if guarantee <= 0:
        raise err("ERR_INVALID_REQUEST", "outcome_guarantee_uncorrected_va must be > 0")

    rec = {
        "tier": tier,
        "base_price_cents": base_price,
        "deposit_cents": deposit,
        "enhancement_window_days": window_days,
        "outcome_guarantee_uncorrected_va": guarantee,
        "refund_mode": refund_mode,
        "active": active,
    }
    stamp_create(rec, tracked=False)  # TreatmentPackage: id + created_at only
    db.packages[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/refractive/packages/<pid>")
@require_auth(["Coordinator", "Surgeon", "Optometrist", "Patient"])
def get_package(pid):
    return success(serialize(get_or_404(db.packages, pid)), 200)


@bp.get("/refractive/packages")
@require_auth(["Coordinator", "Surgeon", "Optometrist", "Patient"])
def list_packages():
    from flask import request
    items = list(db.packages.values())
    tier = request.args.get("tier")
    if tier is not None:
        items = [x for x in items if x["tier"] == tier]
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [x for x in items if x["active"] == want]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([serialize(x) for x in page], 200, is_array=True, pagination=meta)


# ---------------- Suites ----------------
@bp.post("/refractive/suites")
@require_auth(["Coordinator"])
def create_suite():
    body = get_json_body()
    name = as_str(body, "name")
    buffer_min = as_int(body, "turnaround_buffer_minutes")
    cap = as_int(body, "daily_case_cap")
    status = as_enum(body, "status", {"OPEN", "MAINTENANCE"}, allow_missing=True, default="OPEN")
    if buffer_min < 0:
        raise err("ERR_INVALID_REQUEST", "turnaround_buffer_minutes must be >= 0")
    if cap < 1:
        raise err("ERR_INVALID_REQUEST", "daily_case_cap must be >= 1")
    rec = {"name": name, "turnaround_buffer_minutes": buffer_min,
           "daily_case_cap": cap, "status": status}
    stamp_create(rec)
    db.suites[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/refractive/suites/<sid>")
@require_auth(["Coordinator", "Surgeon"])
def get_suite(sid):
    return success(serialize(get_or_404(db.suites, sid)), 200)


# ---------------- Surgeons ----------------
@bp.post("/refractive/surgeons")
@require_auth(["Coordinator"])
def create_surgeon():
    body = get_json_body()
    name = as_str(body, "full_name")
    max_daily = as_int(body, "max_daily_cases")
    accepting = as_bool(body, "accepting", allow_missing=True, default=True)
    if max_daily < 1:
        raise err("ERR_INVALID_REQUEST", "max_daily_cases must be >= 1")
    rec = {"full_name": name, "max_daily_cases": max_daily, "accepting": accepting}
    stamp_create(rec)
    db.surgeons[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/refractive/surgeons/<sid>")
@require_auth(["Coordinator", "Surgeon"])
def get_surgeon(sid):
    return success(serialize(get_or_404(db.surgeons, sid)), 200)


# ---------------- Optometrists ----------------
@bp.post("/refractive/optometrists")
@require_auth(["Coordinator"])
def create_optometrist():
    body = get_json_body()
    name = as_str(body, "full_name")
    rec = {"full_name": name}
    stamp_create(rec)
    db.optometrists[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/refractive/optometrists/<oid>")
@require_auth(["Coordinator", "Optometrist"])
def get_optometrist(oid):
    return success(serialize(get_or_404(db.optometrists, oid)), 200)


def _as_num(body, field):
    from helpers import as_number
    return as_number(body, field)
