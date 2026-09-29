"""BrandInspection scheduling, performance and completion sign-off (PRD 3.6)."""

from flask import g

import calc
import domain
import guards
import repo
import validation as v
from db import clock_date, clock_iso
from errors import ApiError
from middleware import ANY_ROLE, BRAND_INSPECTOR, BRAND_MANAGER
from routing import route


@route("/pip/inspections", ["POST"], (BRAND_MANAGER,))
def create_inspection():
    body = v.body_json()
    plan = guards.resolve_body_fk(body, "plan_id", "plans")

    v.require(body, "plan_id", "inspection_type", "inspector_user_id", "scheduled_date")
    inspection_type = v.get_enum(body, "inspection_type", calc.INSPECTION_TYPES)
    inspector = v.get_str(body, "inspector_user_id", min_len=1, max_len=64)
    scheduled_raw = v.get_str(body, "scheduled_date", min_len=1)
    if calc.parse_date(scheduled_raw) is None:
        raise ApiError("ERR_VALIDATION", "scheduled_date must be an ISO date")

    row = repo.new_row(
        {
            "plan_id": plan["id"],
            "inspection_type": inspection_type,
            "inspector_user_id": inspector,
            "scheduled_date": scheduled_raw,
            "performed_at": None,
            "signed_off_at": None,
            "signed_off_by_user_id": None,
            "status": "SCHEDULED",
            "punch_open_count": 0,
        }
    )
    repo.insert("inspections", row)
    return repo.single(row, 201)


@route("/pip/inspections/<row_id>", ["GET"], ANY_ROLE)
def get_inspection(row_id):
    return repo.single(repo.must_find("inspections", row_id))


@route("/pip/inspections", ["GET"], ANY_ROLE)
def list_inspections():
    limit, offset = v.pagination()
    rows = repo.rows("inspections")
    for field in ("plan_id", "inspection_type", "status"):
        value = v.query_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return repo.page(rows, limit, offset)


@route("/pip/inspections/<row_id>/perform", ["POST"], (BRAND_INSPECTOR,))
def perform_inspection(row_id):
    inspection = repo.must_find("inspections", row_id)

    if inspection["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INSPECTION_NOT_PERFORMABLE",
            "only a SCHEDULED inspection may be recorded as performed",
        )

    # band 6 — the visit may not be recorded before its scheduled date.
    scheduled = calc.parse_date(inspection["scheduled_date"])
    if scheduled is not None and clock_date() < scheduled:
        raise ApiError(
            "ERR_INSPECTION_TOO_EARLY",
            "the inspection is scheduled for %s" % inspection["scheduled_date"],
        )

    # band 8
    guards.require_assigned_inspector(inspection)

    inspection["status"] = "PERFORMED"
    inspection["performed_at"] = clock_iso()
    domain.recompute_inspection_punch_count(inspection)
    repo.touch(inspection)
    return repo.single(inspection)


@route("/pip/inspections/<row_id>/sign-off", ["POST"], (BRAND_INSPECTOR,))
def sign_off_inspection(row_id):
    inspection = repo.must_find("inspections", row_id)
    plan = repo.find("plans", inspection["plan_id"])

    # band 4 — the inspection's own state, then the governing plan's window.
    if inspection["status"] != "PERFORMED":
        raise ApiError(
            "ERR_INSPECTION_NOT_SIGNABLE",
            "only a PERFORMED inspection may be signed off",
        )
    if plan is None or plan["status"] != "READY_FOR_COMPLETION_INSPECTION":
        raise ApiError(
            "ERR_PLAN_NOT_READY_FOR_SIGNOFF",
            "the plan is not READY_FOR_COMPLETION_INSPECTION",
        )
    if inspection["inspection_type"] != "COMPLETION":
        raise ApiError(
            "ERR_INSPECTION_TYPE_NOT_SIGNABLE",
            "only a COMPLETION inspection may be signed off",
        )

    # band 6
    domain.recompute_inspection_punch_count(inspection)
    if inspection["punch_open_count"] != 0:
        raise ApiError(
            "ERR_PUNCH_LIST_OPEN",
            "%d defect(s) of this inspection are still open"
            % inspection["punch_open_count"],
        )

    # band 8
    guards.require_assigned_inspector(inspection)
    if g.user_id == plan["issued_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the user who issued the plan may not certify its completion",
        )
    if plan["dispute_state"] == "DISPUTE_OPEN":
        raise ApiError(
            "ERR_DISPUTE_OPEN_BLOCKS_SIGNOFF",
            "an open scope dispute blocks completion sign-off",
        )

    inspection["status"] = "SIGNED_OFF"
    inspection["signed_off_at"] = clock_iso()
    inspection["signed_off_by_user_id"] = g.user_id
    repo.touch(inspection)

    domain.complete_plan_cascade(plan, inspection)
    return repo.single(inspection)
