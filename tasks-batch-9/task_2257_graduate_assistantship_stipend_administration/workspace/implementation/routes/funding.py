"""Funding sources and the encumbrance ledger (PRD 3.3)."""
from flask import Blueprint

import serialize
import validate as v
from db import db, insert, update
from errors import ApiError
from middleware import authenticate
from response import ok, created, ok_list
from services import queries

bp = Blueprint("funding", __name__)

SOURCE_TYPES = ("GRANT", "DEPARTMENTAL_BUDGET", "FELLOWSHIP")
SOURCE_STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")
SUSPENSION_REASONS = ("SPONSOR_HOLD", "OVERCOMMITMENT", "AUDIT")

READ_ROLES = ["GradSchoolAdmin", "DepartmentAdmin", "GrantAccountant"]


@bp.post("/funding-sources")
def create_source():
    authenticate(["GrantAccountant", "GradSchoolAdmin"])
    body = v.body_dict()
    department_ref = v.ref_value(body, "department_id")
    if department_ref is not None:
        queries.department_or_404(department_ref)

    department_id = v.field_id(body, "department_id")
    source_code = v.field_str(body, "source_code")
    source_type = v.field_enum(body, "source_type", SOURCE_TYPES)
    authorized = v.field_int(body, "authorized_amount_cents", minimum=1)
    budget_start = v.field_date(body, "budget_period_start")
    budget_end = v.field_date(body, "budget_period_end")
    allows_remission = v.field_bool(body, "allows_tuition_remission")
    sponsor_code = v.field_str(body, "sponsor_code", required=False, default=None)
    grant_effort_cap = v.field_int(body, "grant_effort_cap_pct", required=False,
                                  default=100, minimum=1, maximum=100)
    threshold = v.field_int(body, "auto_reinstate_threshold_cents", required=False,
                            default=0, minimum=0)
    if budget_end < budget_start:
        raise v.invalid("budget_period_end must be on or after budget_period_start")

    for row in db.funding_sources.values():
        if row["source_code"] == source_code:
            raise ApiError("ERR_DUPLICATE_FUNDING_SOURCE_CODE",
                           "source_code %s is already used" % source_code)

    row = insert(db.funding_sources, {
        "department_id": department_id,
        "source_code": source_code,
        "source_type": source_type,
        "sponsor_code": sponsor_code,
        "authorized_amount_cents": authorized,
        "budget_period_start": budget_start.isoformat(),
        "budget_period_end": budget_end.isoformat(),
        "allows_tuition_remission": allows_remission,
        "grant_effort_cap_pct": grant_effort_cap,
        "auto_reinstate_threshold_cents": threshold,
        "committed_amount_cents": 0,
        "expended_amount_cents": 0,
        "available_amount_cents": authorized,
        "status": "ACTIVE",
        "suspension_reason": None,
    })
    return created(serialize.funding_source(row))


@bp.get("/funding-sources/<source_id>")
def read_source(source_id):
    authenticate(READ_ROLES)
    source = queries.source_or_404(source_id)
    return ok(serialize.funding_source(source))


@bp.get("/funding-sources")
def list_sources():
    authenticate(READ_ROLES)
    department_id = v.query_str("department_id")
    source_type = v.query_enum("source_type", SOURCE_TYPES)
    status = v.query_enum("status", SOURCE_STATUSES)
    rows = list(db.funding_sources.values())
    if department_id:
        rows = [r for r in rows if r["department_id"] == department_id]
    if source_type:
        rows = [r for r in rows if r["source_type"] == source_type]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, meta = v.paginate(queries.by_created(rows))
    return ok_list([serialize.funding_source(r) for r in page], meta)


@bp.post("/funding-sources/<source_id>/suspend")
def suspend_source(source_id):
    authenticate(["GrantAccountant"])
    source = queries.source_or_404(source_id)
    body = v.body_dict()
    reason = v.field_enum(body, "reason", SUSPENSION_REASONS)
    if source["status"] != "ACTIVE":
        raise ApiError("ERR_FUNDING_SOURCE_NOT_ACTIVE",
                       "Only an ACTIVE funding source may be suspended, not %s"
                       % source["status"])
    update(source, status="SUSPENDED", suspension_reason=reason)
    return ok(serialize.funding_source(source))


@bp.post("/funding-sources/<source_id>/reinstate")
def reinstate_source(source_id):
    authenticate(["GrantAccountant"])
    source = queries.source_or_404(source_id)
    if source["status"] != "SUSPENDED":
        raise ApiError("ERR_FUNDING_SOURCE_NOT_ACTIVE",
                       "Only a SUSPENDED funding source may be reinstated, not %s"
                       % source["status"])
    update(source, status="ACTIVE", suspension_reason=None)
    return ok(serialize.funding_source(source))


@bp.post("/funding-sources/<source_id>/close")
def close_source(source_id):
    authenticate(["GrantAccountant"])
    source = queries.source_or_404(source_id)
    if source["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_FUNDING_SOURCE_NOT_ACTIVE",
                       "Only an ACTIVE or SUSPENDED funding source may be closed, not %s"
                       % source["status"])
    if source["committed_amount_cents"] != 0:
        raise ApiError("ERR_FUNDING_SOURCE_HAS_COMMITMENTS",
                       "The funding source still carries encumbrances")
    update(source, status="CLOSED", suspension_reason=None)
    return ok(serialize.funding_source(source))
