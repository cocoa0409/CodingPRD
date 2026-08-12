"""Burn plan routes: create (OCC + certification gate), lifecycle actions."""
from flask import Blueprint, request

from core import (
    DB,
    ApiError,
    Validator,
    auth,
    body,
    ok,
    paginate,
    parse_date,
    require_role,
    stamp_new,
    touch,
)
from domain import (
    certification_allows,
    get_boss,
    get_parcel,
    get_plan,
    hazard_score,
    plan_cancel_cascade,
    plan_superseded_cascade,
    ser_plan,
)

bp = Blueprint("plans", __name__)

TREATMENT_CATEGORIES = {"BROADCAST", "UNDERSTORY", "PILE_BURN"}
RATE_CLASSES = {"GRASS", "BRUSH", "TIMBER"}

PLAN_FIELDS = {
    "parcel_id",
    "expected_parcel_version",
    "planned_acres",
    "planned_window_start",
    "planned_window_end",
    "max_wind_mph",
    "min_fuel_moisture_pct",
    "max_fuel_moisture_pct",
    "min_rh_pct",
    "min_temp_f",
    "max_temp_f",
    "min_mixing_height_ft",
    "treatment_lines",
    "supersedes_plan_id",
}

ACTIVE_PLAN_STATUSES = {"DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED"}


def validate_treatment_lines(v, lines, planned_acres):
    """Field-level treatment_lines validation (priority 14)."""
    if lines is None:
        return
    if not isinstance(lines, list):
        v.invalid("treatment_lines must be an array")
        return
    if len(lines) < 1:
        v.invalid("treatment_lines must contain at least one line")
        return
    total = 0
    for idx, line in enumerate(lines):
        if not isinstance(line, dict):
            v.invalid(f"treatment_lines[{idx}] must be an object")
            return
        extra = set(line.keys()) - {"category", "rate_class", "acres"}
        if extra:
            v.invalid(f"treatment_lines[{idx}] has unknown field: {sorted(extra)[0]}")
            return
        cat = line.get("category")
        rc = line.get("rate_class")
        acres = line.get("acres")
        for f in ("category", "rate_class", "acres"):
            if line.get(f) is None:
                v.invalid(f"treatment_lines[{idx}].{f} is required")
                return
        if not isinstance(cat, str) or not isinstance(rc, str):
            v.invalid(f"treatment_lines[{idx}] has an invalid type")
            return
        if cat not in TREATMENT_CATEGORIES:
            v._set("ERR_INVALID_ENUM", f"treatment_lines[{idx}].category is invalid")
            return
        if rc not in RATE_CLASSES:
            v._set("ERR_INVALID_ENUM", f"treatment_lines[{idx}].rate_class is invalid")
            return
        if not (isinstance(acres, int) and not isinstance(acres, bool)):
            v.invalid(f"treatment_lines[{idx}].acres must be an integer")
            return
        if acres <= 0:
            v.prescription(f"treatment_lines[{idx}].acres must be positive")
            return
        total += acres
    if planned_acres is not None and total != planned_acres:
        v.invalid("treatment_lines acres must sum to planned_acres")


@bp.post("/burn-plans")
def create_plan():
    data = body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    # identity: X-User-ID must be a registered BurnBoss
    boss = DB["bosses"].get(uid)
    if boss is None:
        raise ApiError("ERR_BOSS_NOT_FOUND", 404, "BurnBoss not found")
    # existence of referenced parcel / superseded plan (left to right)
    parcel_id = data.get("parcel_id")
    parcel = None
    if isinstance(parcel_id, str):
        parcel = get_parcel(parcel_id)
    supersedes_id = data.get("supersedes_plan_id")
    prior_plan = None
    if isinstance(supersedes_id, str):
        prior_plan = get_plan(supersedes_id)
    # OCC (priority 6): before business rules
    expected = data.get("expected_parcel_version")
    if expected is not None and parcel is not None:
        if isinstance(expected, int) and not isinstance(expected, bool):
            if expected != parcel["version"]:
                raise ApiError(
                    "ERR_STALE_VERSION",
                    412,
                    "expected_parcel_version does not match the parcel's current version",
                )
    # certification gate (priority 9)
    planned_acres = data.get("planned_acres")
    if (
        parcel is not None
        and isinstance(planned_acres, int)
        and not isinstance(planned_acres, bool)
    ):
        if not certification_allows(boss["certification_tier"], planned_acres, parcel["hazard_score"]):
            raise ApiError(
                "ERR_BOSS_CERTIFICATION_INSUFFICIENT",
                403,
                "Author certification tier does not cover planned_acres / hazard_score",
            )
    # uniqueness: one active plan per parcel (priority 11), supersession exception
    if parcel is not None:
        for other in DB["plans"].values():
            if other["parcel_id"] != parcel["id"] or other["status"] not in ACTIVE_PLAN_STATUSES:
                continue
            if (
                prior_plan is not None
                and other["id"] == prior_plan["id"]
                and prior_plan["status"] == "APPROVED"
            ):
                continue  # supersession exception: incumbent leaves the active set on approval
            raise ApiError(
                "ERR_ACTIVE_PLAN_EXISTS_FOR_PARCEL",
                409,
                "Parcel already has an active burn plan",
            )
    # field-level shape (priority 14)
    v = Validator(data, PLAN_FIELDS)
    v.req("parcel_id", str)
    v.req("expected_parcel_version", int)
    v.req("planned_acres", int)
    if v.typed("planned_acres", int) is not None and v.typed("planned_acres", int) <= 0:
        v.prescription("planned_acres must be a positive integer")
    if parcel is not None and v.typed("planned_acres", int) is not None:
        if v.typed("planned_acres", int) > parcel["acreage"]:
            v.prescription("planned_acres must not exceed the parcel's acreage")
    v.date("planned_window_start")
    v.date("planned_window_end")
    ws = parse_date(data.get("planned_window_start"))
    we = parse_date(data.get("planned_window_end"))
    if ws is not None and we is not None and we < ws:
        v.prescription("planned_window_end must not precede planned_window_start")
    for f in (
        "max_wind_mph",
        "min_fuel_moisture_pct",
        "max_fuel_moisture_pct",
        "min_rh_pct",
        "min_temp_f",
        "max_temp_f",
        "min_mixing_height_ft",
    ):
        v.req(f, int)
    min_fm, max_fm = v.typed("min_fuel_moisture_pct", int), v.typed("max_fuel_moisture_pct", int)
    if min_fm is not None and max_fm is not None and min_fm > max_fm:
        v.prescription("min_fuel_moisture_pct must not exceed max_fuel_moisture_pct")
    min_t, max_t = v.typed("min_temp_f", int), v.typed("max_temp_f", int)
    if min_t is not None and max_t is not None and min_t > max_t:
        v.prescription("min_temp_f must not exceed max_temp_f")
    if supersedes_id is not None and not isinstance(supersedes_id, str):
        v.invalid("supersedes_plan_id must be a string")
    if prior_plan is not None and parcel is not None and prior_plan["parcel_id"] != parcel["id"]:
        v.invalid("supersedes_plan_id must reference a plan on the same parcel")
    v.req("treatment_lines", list)
    validate_treatment_lines(v, data.get("treatment_lines"), v.typed("planned_acres", int))
    v.finish()
    plan = stamp_new(
        {
            "parcel_id": parcel["id"],
            "author_boss_id": uid,
            "supersedes_plan_id": prior_plan["id"] if prior_plan else None,
            "planned_acres": data["planned_acres"],
            "planned_window_start": ws,
            "planned_window_end": we,
            "max_wind_mph": data["max_wind_mph"],
            "min_fuel_moisture_pct": data["min_fuel_moisture_pct"],
            "max_fuel_moisture_pct": data["max_fuel_moisture_pct"],
            "min_rh_pct": data["min_rh_pct"],
            "min_temp_f": data["min_temp_f"],
            "max_temp_f": data["max_temp_f"],
            "min_mixing_height_ft": data["min_mixing_height_ft"],
            "treatment_lines": data["treatment_lines"],
            "approved_by_boss_id": None,
            "status": "DRAFT",
        }
    )
    DB["plans"][plan["id"]] = plan
    touch(parcel)  # creating a plan advances the parcel's version (OCC token)
    return ok(ser_plan(plan), 201)


@bp.get("/burn-plans/<pid>")
def get_p(pid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_plan(get_plan(pid)))


@bp.get("/burn-plans")
def list_plans():
    _, role = auth()
    require_role(role, None)
    items = list(DB["plans"].values())
    for key, field in (
        ("parcel_id", "parcel_id"),
        ("author_boss_id", "author_boss_id"),
        ("approved_by_boss_id", "approved_by_boss_id"),
        ("supersedes_plan_id", "supersedes_plan_id"),
        ("status", "status"),
    ):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p[field] == val]
    return paginate(items, ser_plan)


def _author_check(plan, uid):
    if uid != plan["author_boss_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the plan's author")


@bp.post("/burn-plans/<pid>/submit")
def submit_plan(pid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    plan = get_plan(pid)
    _author_check(plan, uid)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT", 409, "Plan must be DRAFT to submit")
    plan["status"] = "SUBMITTED"
    touch(plan)
    return ok(ser_plan(plan))


@bp.post("/burn-plans/<pid>/request-revision")
def request_revision(pid):
    body()
    _, role = auth()
    require_role(role, {"AgencyReviewer"})
    plan = get_plan(pid)
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_PLAN_NOT_SUBMITTED", 409, "Plan must be SUBMITTED")
    plan["status"] = "REVISION_REQUESTED"
    touch(plan)
    return ok(ser_plan(plan))


@bp.post("/burn-plans/<pid>/revise")
def revise_plan(pid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    plan = get_plan(pid)
    _author_check(plan, uid)
    if plan["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_PLAN_NOT_IN_REVISION", 409, "Plan must be REVISION_REQUESTED")
    plan["status"] = "DRAFT"
    touch(plan)
    return ok(ser_plan(plan))


@bp.post("/burn-plans/<pid>/approve")
def approve_plan(pid):
    body()
    uid, role = auth()
    require_role(role, {"AgencyReviewer"})
    plan = get_plan(pid)
    # segregation of duties (priority 5) before state (priority 7)
    if uid == plan["author_boss_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            403,
            "Reviewer may not approve their own authored plan",
        )
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_PLAN_NOT_SUBMITTED", 409, "Plan must be SUBMITTED")
    plan["status"] = "APPROVED"
    plan["approved_by_boss_id"] = uid
    touch(plan)
    # supersession cascade
    if plan["supersedes_plan_id"]:
        prior = DB["plans"].get(plan["supersedes_plan_id"])
        if prior is not None and prior["status"] == "APPROVED":
            plan_superseded_cascade(prior)
    return ok(ser_plan(plan))


@bp.post("/burn-plans/<pid>/cancel")
def cancel_plan(pid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    plan = get_plan(pid)
    _author_check(plan, uid)
    if plan["status"] not in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED"):
        raise ApiError("ERR_PLAN_NOT_CANCELLABLE", 409, "Plan is not cancellable")
    plan["status"] = "CANCELLED"
    touch(plan)
    plan_cancel_cascade(plan)
    return ok(ser_plan(plan))
