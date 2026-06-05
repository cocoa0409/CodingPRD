"""ReviewCycle, RatingBand, and Employee routes."""
from flask import Blueprint

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_BAND_COVERAGE_INVALID,
    ERR_DISTRIBUTION_NOT_NORMALIZED, ERR_VALIDATION,
)
from middleware import get_caller, require_role
from response import ok_object, ok_array
from services.common import (
    init_common, touch, public, paginate, get_body, require_fields,
    as_number, as_str,
)

bp = Blueprint("cycles", __name__)


# ---------------- serialization ----------------

def cycle_view(c):
    v = public(c)
    return v


def band_view(b):
    # RatingBand carries only id + created_at (no updated_at/version).
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "cycle_id": b["cycle_id"],
        "label": b["label"],
        "min_score": b["min_score"],
        "max_score": b["max_score"],
        "merit_pct": b["merit_pct"],
        "pip_eligible": b["pip_eligible"],
    }


# ---------------- ReviewCycle ----------------

@bp.route("/cycles", methods=["POST"])
def create_cycle():
    _, role = get_caller()
    require_role(role, {"HrAdmin"})
    body = get_body()
    require_fields(body, ["name", "cadence", "merit_budget_pct",
                          "equity_refresh_pool", "bell_curve_target"])
    name = as_str(body["name"], "name")
    if len(name) == 0 or len(name) > 120:
        raise err(ERR_VALIDATION, "name must be non-empty and <= 120 chars")
    cadence = body["cadence"]
    if cadence not in ("ANNUAL", "SEMI_ANNUAL"):
        raise err(ERR_VALIDATION, "cadence must be ANNUAL or SEMI_ANNUAL")
    merit_budget_pct = as_number(body["merit_budget_pct"], "merit_budget_pct")
    if not (0 <= merit_budget_pct <= 0.5):
        raise err(ERR_VALIDATION, "merit_budget_pct must be in [0, 0.5]")
    equity_refresh_pool = as_number(body["equity_refresh_pool"], "equity_refresh_pool")
    if equity_refresh_pool < 0:
        raise err(ERR_VALIDATION, "equity_refresh_pool must be >= 0")
    bell = body["bell_curve_target"]
    if not isinstance(bell, dict) or not bell:
        raise err(ERR_VALIDATION, "bell_curve_target must be a non-empty object")
    for k, val in bell.items():
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise err(ERR_VALIDATION, "bell_curve_target values must be numbers")
        if not (0 <= val <= 1):
            raise err(ERR_VALIDATION, "bell_curve_target values must be in [0,1]")
    distribution_tolerance = 0.05
    if body.get("distribution_tolerance") is not None:
        distribution_tolerance = as_number(body["distribution_tolerance"],
                                           "distribution_tolerance")
        if not (0 <= distribution_tolerance <= 1):
            raise err(ERR_VALIDATION, "distribution_tolerance must be in [0,1]")

    c = {
        "name": name,
        "cadence": cadence,
        "merit_budget_pct": merit_budget_pct,
        "equity_refresh_pool": equity_refresh_pool,
        "status": "DRAFT",
        "bell_curve_target": bell,
        "distribution_tolerance": distribution_tolerance,
        "merit_committed_total": 0,
        "equity_committed_total": 0,
    }
    init_common(c)
    db.cycles[c["id"]] = c
    return ok_object(cycle_view(c), 201)


@bp.route("/cycles", methods=["GET"])
def list_cycles():
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "CompApprover"})
    from flask import request
    status = request.args.get("status")
    items = [c for c in db.cycles.values()
             if status is None or c["status"] == status]
    page, limit, offset, total, has_more = paginate(items)
    return ok_array([cycle_view(c) for c in page], limit, offset, total, has_more)


@bp.route("/cycles/<cid>", methods=["GET"])
def get_cycle(cid):
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "CompApprover"})
    c = db.cycles.get(cid)
    if not c:
        raise err(ERR_NOT_FOUND, "Cycle not found")
    return ok_object(cycle_view(c))


# ---------------- RatingBand ----------------

@bp.route("/cycles/<cid>/rating-bands", methods=["POST"])
def add_band(cid):
    _, role = get_caller()
    require_role(role, {"HrAdmin"})
    c = db.cycles.get(cid)
    if not c:
        raise err(ERR_NOT_FOUND, "Cycle not found")
    if c["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Bands may only be added to a DRAFT cycle")
    body = get_body()
    require_fields(body, ["label", "min_score", "max_score", "merit_pct"])
    label = as_str(body["label"], "label")
    if len(label) == 0:
        raise err(ERR_VALIDATION, "label must be non-empty")
    # unique within cycle
    for b in db.rating_bands.values():
        if b["cycle_id"] == cid and b["label"] == label:
            raise err(ERR_VALIDATION, "label must be unique within the cycle")
    min_score = as_number(body["min_score"], "min_score")
    max_score = as_number(body["max_score"], "max_score")
    if not (0 <= min_score <= 100):
        raise err(ERR_VALIDATION, "min_score must be in [0,100]")
    if not (min_score < max_score <= 100):
        raise err(ERR_VALIDATION, "max_score must be > min_score and <= 100")
    merit_pct = as_number(body["merit_pct"], "merit_pct")
    if merit_pct < 0:
        raise err(ERR_VALIDATION, "merit_pct must be >= 0")
    pip_eligible = body.get("pip_eligible", False)
    if not isinstance(pip_eligible, bool):
        raise err(ERR_VALIDATION, "pip_eligible must be a boolean")

    from db import new_id, now_iso
    b = {
        "id": new_id(),
        "created_at": now_iso(),
        "cycle_id": cid,
        "label": label,
        "min_score": min_score,
        "max_score": max_score,
        "merit_pct": merit_pct,
        "pip_eligible": pip_eligible,
        "_seq": db.next_seq(),
    }
    db.rating_bands[b["id"]] = b
    return ok_object(band_view(b), 201)


@bp.route("/cycles/<cid>/rating-bands", methods=["GET"])
def list_bands(cid):
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "CompApprover"})
    c = db.cycles.get(cid)
    if not c:
        raise err(ERR_NOT_FOUND, "Cycle not found")
    items = [b for b in db.rating_bands.values() if b["cycle_id"] == cid]
    page, limit, offset, total, has_more = paginate(items)
    return ok_array([band_view(b) for b in page], limit, offset, total, has_more)


def bands_for_cycle(cid):
    return [b for b in db.rating_bands.values() if b["cycle_id"] == cid]


# ---------------- cycle transitions ----------------

def _bands_tile_0_100(bands):
    if not bands:
        return False
    ordered = sorted(bands, key=lambda b: b["min_score"])
    if ordered[0]["min_score"] != 0:
        return False
    if ordered[-1]["max_score"] != 100:
        return False
    for i in range(len(ordered) - 1):
        if ordered[i]["max_score"] != ordered[i + 1]["min_score"]:
            return False
    return True


@bp.route("/cycles/<cid>/open", methods=["POST"])
def open_cycle(cid):
    _, role = get_caller()
    require_role(role, {"HrAdmin"})
    c = db.cycles.get(cid)
    if not c:
        raise err(ERR_NOT_FOUND, "Cycle not found")
    if c["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Cycle is not in DRAFT")
    bands = bands_for_cycle(cid)
    if len(bands) < 1:
        raise err(ERR_BAND_COVERAGE_INVALID, "Cycle must have >= 1 rating band")
    if not _bands_tile_0_100(bands):
        raise err(ERR_BAND_COVERAGE_INVALID, "Bands must tile [0,100] with no gaps/overlaps")
    band_labels = set(b["label"] for b in bands)
    target_keys = set(c["bell_curve_target"].keys())
    if band_labels != target_keys:
        raise err(ERR_BAND_COVERAGE_INVALID,
                  "bell_curve_target keys must equal RatingBand label set")
    total = sum(c["bell_curve_target"].values())
    if abs(total - 1.0) > 0.0005:
        raise err(ERR_DISTRIBUTION_NOT_NORMALIZED,
                  "bell_curve_target must sum to 1.000 +/- 0.0005")
    c["status"] = "OPEN"
    touch(c)
    return ok_object(cycle_view(c))


@bp.route("/cycles/<cid>/start-calibration", methods=["POST"])
def start_calibration(cid):
    _, role = get_caller()
    require_role(role, {"HrAdmin"})
    c = db.cycles.get(cid)
    if not c:
        raise err(ERR_NOT_FOUND, "Cycle not found")
    if c["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Cycle is not OPEN")
    later = {"SUBMITTED", "RETURNED", "CALIBRATED", "FINALIZED"}
    for r in db.reviews.values():
        if r["cycle_id"] == cid and r["status"] not in later:
            raise err(ERR_INVALID_STATE,
                      "Every review must be SUBMITTED or later")
    c["status"] = "CALIBRATION"
    touch(c)
    return ok_object(cycle_view(c))


@bp.route("/cycles/<cid>/start-comp-planning", methods=["POST"])
def start_comp_planning(cid):
    _, role = get_caller()
    require_role(role, {"HrAdmin"})
    c = db.cycles.get(cid)
    if not c:
        raise err(ERR_NOT_FOUND, "Cycle not found")
    if c["status"] != "CALIBRATION":
        raise err(ERR_INVALID_STATE, "Cycle is not in CALIBRATION")
    for s in db.calibration_sessions.values():
        if s["cycle_id"] == cid and s["status"] != "FINALIZED":
            raise err(ERR_INVALID_STATE,
                      "Every calibration session must be FINALIZED")
    c["status"] = "COMP_PLANNING"
    touch(c)
    return ok_object(cycle_view(c))


@bp.route("/cycles/<cid>/close", methods=["POST"])
def close_cycle(cid):
    _, role = get_caller()
    require_role(role, {"HrAdmin"})
    c = db.cycles.get(cid)
    if not c:
        raise err(ERR_NOT_FOUND, "Cycle not found")
    if c["status"] != "COMP_PLANNING":
        raise err(ERR_INVALID_STATE, "Cycle is not in COMP_PLANNING")
    for p in db.comp_plans.values():
        if p["cycle_id"] == cid and p["status"] not in ("APPROVED", "REJECTED"):
            raise err(ERR_INVALID_STATE,
                      "Every comp plan must be APPROVED or REJECTED")
    finalized_salary = sum(
        r["base_salary"] for r in db.reviews.values()
        if r["cycle_id"] == cid and r["status"] == "FINALIZED"
    )
    if c["merit_committed_total"] > c["merit_budget_pct"] * finalized_salary:
        raise err(ERR_INVALID_STATE, "merit_committed_total exceeds merit budget")
    c["status"] = "CLOSED"
    touch(c)
    return ok_object(cycle_view(c))


# ---------------- Employee ----------------

def employee_view(e):
    return public(e)


@bp.route("/employees", methods=["POST"])
def create_employee():
    _, role = get_caller()
    require_role(role, {"HrAdmin"})
    body = get_body()
    require_fields(body, ["full_name", "department", "hire_date"])
    full_name = as_str(body["full_name"], "full_name")
    if len(full_name) == 0:
        raise err(ERR_VALIDATION, "full_name must be non-empty")
    manager_id = body.get("manager_id")
    if manager_id is not None:
        if manager_id not in db.employees:
            raise err(ERR_NOT_FOUND, "manager_id not found")
    is_active = body.get("is_active", True)
    if not isinstance(is_active, bool):
        raise err(ERR_VALIDATION, "is_active must be a boolean")

    e = {
        "full_name": full_name,
        "manager_id": manager_id,
        "department": body["department"],
        "hire_date": body["hire_date"],
        "is_active": is_active,
    }
    init_common(e)
    # must not equal own id (cannot since id is minted now and manager pre-exists)
    if manager_id == e["id"]:
        raise err(ERR_VALIDATION, "manager_id must not equal own id")
    db.employees[e["id"]] = e
    return ok_object(employee_view(e), 201)


@bp.route("/employees/<eid>", methods=["GET"])
def get_employee(eid):
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "CompApprover", "Manager", "Employee"})
    e = db.employees.get(eid)
    if not e:
        raise err(ERR_NOT_FOUND, "Employee not found")
    return ok_object(employee_view(e))


@bp.route("/employees", methods=["GET"])
def list_employees():
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "CompApprover"})
    from flask import request
    manager_id = request.args.get("manager_id")
    department = request.args.get("department")
    items = [
        e for e in db.employees.values()
        if (manager_id is None or e.get("manager_id") == manager_id)
        and (department is None or e.get("department") == department)
    ]
    page, limit, offset, total, has_more = paginate(items)
    return ok_array([employee_view(e) for e in page], limit, offset, total, has_more)
