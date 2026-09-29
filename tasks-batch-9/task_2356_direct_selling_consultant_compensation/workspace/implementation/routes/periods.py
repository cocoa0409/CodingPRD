"""Qualification periods and qualification rows."""

from flask import Blueprint

from common import (
    clock_str,
    new_row,
    pagination,
    paginate,
    parse_dt,
    q_enum,
    q_str,
    raw_body,
    req_dt_str,
    req_int,
    req_str,
    touch,
)
from db import db
from errors import ApiError
from middleware import auth, own_consultant
from response import created, ok, ok_list
from services import planlib
from services.genealogy import by_created
from services.lookup import fetch, peek
from services.qual import (
    lock_period,
    recompute_group_fields_for_period,
    refresh_period_totals,
    rows_of_period,
)

bp = Blueprint("periods", __name__)

PERIOD_STATUSES = ("OPEN", "LOCKED", "CLOSED", "REOPENED")

READ_ROLES = [
    "Consultant",
    "ComplianceOfficer",
    "CommissionAnalyst",
    "FinanceController",
    "PlatformAdmin",
]


def period_sort_key(period):
    return (period["_period_start_dt"], period["created_at"], period["_seq"])


@bp.post("/qualification-periods")
def create_period():
    auth(["CommissionAnalyst", "PlatformAdmin"])
    body = raw_body()
    compensation_plan_id = req_str(body, "compensation_plan_id", min_len=1)
    period_code = req_str(body, "period_code", min_len=1)
    period_start = req_dt_str(body, "period_start")
    period_end = req_dt_str(body, "period_end")

    plan = fetch("plan", compensation_plan_id)

    for existing in db.periods.values():
        if existing["compensation_plan_id"] == plan["id"] and existing["period_code"] == period_code:
            raise ApiError("ERR_DUPLICATE_PERIOD_CODE")

    start_dt = parse_dt(period_start)
    end_dt = parse_dt(period_end)
    if not (end_dt > start_dt):
        raise ApiError("ERR_PERIOD_BOUNDS_INVALID")

    for existing in db.periods.values():
        if existing["compensation_plan_id"] != plan["id"]:
            continue
        if start_dt < existing["_period_end_dt"] and existing["_period_start_dt"] < end_dt:
            raise ApiError("ERR_PERIOD_OVERLAP")

    row = new_row()
    row.update(
        {
            "compensation_plan_id": plan["id"],
            "period_code": period_code,
            "period_start": period_start,
            "period_end": period_end,
            "status": "OPEN",
            "locked_at": None,
            "closed_at": None,
            "reopen_count": 0,
            "correction_pending": False,
            "qualification_count": 0,
            "total_net_personal_volume_points": 0,
            "_period_start_dt": start_dt,
            "_period_end_dt": end_dt,
        }
    )
    db.periods[row["id"]] = row
    return created(row)


@bp.get("/qualification-periods")
def list_periods():
    auth(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "compensation_plan_id": q_str("compensation_plan_id"),
        "period_code": q_str("period_code"),
        "status": q_enum("status", PERIOD_STATUSES),
    }
    rows = sorted(db.periods.values(), key=period_sort_key)
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/qualification-periods/<period_id>")
def read_period(period_id):
    auth(READ_ROLES)
    return ok(fetch("period", period_id))


@bp.post("/qualification-periods/<period_id>/lock")
def lock(period_id):
    auth(["CommissionAnalyst"])
    period = fetch("period", period_id)
    if period["status"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_PERIOD_NOT_OPEN")

    plan = db.plans.get(period["compensation_plan_id"])
    lock_period(period, plan)

    # Expire lapsed suspensions; highest_sanction_order is never reduced.
    now = parse_dt(clock_str())
    for consultant in db.consultants.values():
        if consultant["compensation_plan_id"] != plan["id"]:
            continue
        if consultant["status"] != "SUSPENDED":
            continue
        until = parse_dt(consultant.get("active_sanction_until") or "")
        if until is not None and now is not None and until < now:
            consultant["status"] = "ACTIVE"
            consultant["active_sanction_level"] = None
            consultant["active_sanction_until"] = None
            touch(consultant)

    period["status"] = "LOCKED"
    period["locked_at"] = clock_str()
    rows = rows_of_period(period["id"])
    period["qualification_count"] = len(rows)
    period["total_net_personal_volume_points"] = sum(
        int(r["net_personal_volume_points"]) for r in rows
    )
    touch(period)
    return ok(period)


@bp.post("/qualification-periods/<period_id>/close")
def close(period_id):
    auth(["CommissionAnalyst"])
    period = fetch("period", period_id)
    if period["status"] != "LOCKED":
        raise ApiError("ERR_PERIOD_NOT_LOCKED")

    plan = db.plans.get(period["compensation_plan_id"])
    highest = planlib.max_rank_order(plan) if plan else 1
    grace_limit = int(plan["maintenance_grace_periods"]) if plan else 0
    needed = int(plan["consecutive_qualifying_periods"]) if plan else 0

    for row in rows_of_period(period["id"]):
        consultant = db.consultants.get(row["consultant_id"])
        if consultant is None:
            continue
        grace_before = int(consultant["grace_periods_used"])
        qualified_order = int(row["qualified_rank_order"])
        held_order = int(consultant["rank_order"])
        changed = False

        if qualified_order > held_order:
            consultant["consecutive_qualified_count"] = (
                int(consultant["consecutive_qualified_count"]) + 1
            )
            if int(consultant["consecutive_qualified_count"]) >= needed:
                new_order = min(held_order + 1, highest)
                rung = planlib.rung_by_order(plan, new_order)
                if rung is not None:
                    consultant["rank_code"] = rung["rank_code"]
                    consultant["rank_order"] = rung["rank_order"]
                    consultant["rank_source"] = "EARNED"
                consultant["consecutive_qualified_count"] = 0
            changed = True
        else:
            if int(consultant["consecutive_qualified_count"]) != 0:
                consultant["consecutive_qualified_count"] = 0
                changed = True

        if qualified_order < held_order:
            consultant["grace_periods_used"] = int(consultant["grace_periods_used"]) + 1
            if int(consultant["grace_periods_used"]) > grace_limit:
                new_order = max(1, held_order - 1)
                rung = planlib.rung_by_order(plan, new_order)
                if rung is not None:
                    consultant["rank_code"] = rung["rank_code"]
                    consultant["rank_order"] = rung["rank_order"]
                    consultant["rank_source"] = "MAINTENANCE_DEMOTION"
            changed = True

        if (
            consultant["status"] in ("ACTIVE", "PROBATION")
            and row["qualified_rank_code"] is None
            and grace_before >= grace_limit
        ):
            consultant["status"] = "INACTIVE"
            base = planlib.base_rung(plan) if plan else None
            if base is not None:
                consultant["rank_code"] = base["rank_code"]
                consultant["rank_order"] = base["rank_order"]
            consultant["rank_source"] = "MAINTENANCE_DEMOTION"
            consultant["grace_periods_used"] = 0
            changed = True
        elif consultant["status"] == "INACTIVE" and row["qualified_rank_code"] is not None:
            consultant["status"] = "ACTIVE"
            changed = True

        if changed:
            touch(consultant)

    period["status"] = "CLOSED"
    period["closed_at"] = clock_str()
    period["correction_pending"] = False
    touch(period)
    return ok(period)


@bp.post("/qualification-periods/<period_id>/reopen")
def reopen(period_id):
    auth(["PlatformAdmin"])
    body = raw_body()
    req_str(body, "reason", min_len=1)

    period = fetch("period", period_id)
    if period["status"] != "CLOSED":
        raise ApiError("ERR_PERIOD_NOT_CLOSED")
    for run in db.runs.values():
        if run["qualification_period_id"] == period["id"] and run["status"] in (
            "DRAFT",
            "CALCULATED",
            "APPROVED",
            "PAID",
        ):
            raise ApiError("ERR_ACTIVE_RUN_BLOCKS_REOPEN")

    period["status"] = "REOPENED"
    period["reopen_count"] = int(period["reopen_count"]) + 1
    period["correction_pending"] = False
    touch(period)

    recompute_group_fields_for_period(period)
    refresh_period_totals(period)
    return ok(period)


# --------------------------------------------------------------------------
# Qualification rows
# --------------------------------------------------------------------------

@bp.get("/period-qualifications")
def list_qualifications():
    auth(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "consultant_id": q_str("consultant_id"),
        "qualification_period_id": q_str("qualification_period_id"),
        "period_code": q_str("period_code"),
        "qualified_rank_code": q_str("qualified_rank_code"),
    }
    rows = by_created(list(db.qualifications.values()))
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/period-qualifications/<period_qualification_id>")
def read_qualification(period_qualification_id):
    auth(READ_ROLES)
    existing = peek("qualification", period_qualification_id)
    if existing is not None:
        own_consultant(existing["consultant_id"])
    return ok(fetch("qualification", period_qualification_id))


@bp.post("/period-qualifications/<period_qualification_id>/personal-use-attestation")
def attest(period_qualification_id):
    auth(["Consultant", "PlatformAdmin"])
    existing = peek("qualification", period_qualification_id)
    if existing is not None:
        own_consultant(existing["consultant_id"])

    body = raw_body()
    points = req_int(body, "attested_personal_use_points", minimum=0)

    row = fetch("qualification", period_qualification_id)
    period = db.periods.get(row["qualification_period_id"])
    if period is None or period["status"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_PERIOD_NOT_ACCEPTING_VOLUME")
    if points > int(row["inventory_volume_points"]):
        raise ApiError("ERR_ATTESTATION_EXCEEDS_INVENTORY")

    row["attested_personal_use_points"] = points
    touch(row)
    return ok(row)
