"""Inspection endpoints (PRD §3.3)."""

from flask import Blueprint, request

from clock import clock
from db import db, common_fields, touch
from errors import err
from middleware import require_roles
from response import success, list_success
from services import domain, serialize
from services.helpers import (
    get_body,
    lookup,
    pagination_params,
    paginate,
    require_enum,
    resolve_ref,
    sort_by_created,
)

bp = Blueprint("inspections", __name__)

KINDS = {"INITIAL", "REINSPECTION"}
OUTCOMES = {"VIOLATION_FOUND", "NO_VIOLATION", "COMPLIANT", "NON_COMPLIANT"}


@bp.post("/inspections")
@require_roles("CodeOfficer")
def create_inspection():
    body = get_body()
    if "case_id" not in body or body["case_id"] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: case_id")
    require_enum(body, "kind", KINDS)
    case = resolve_ref(db.cases, body["case_id"])

    notice_id = body.get("notice_id")
    if body["kind"] == "REINSPECTION":
        # notice_id must reference an ISSUED/OVERDUE notice on the same case.
        if notice_id is None:
            raise err("ERR_REINSPECTION_TARGET_INVALID", "REINSPECTION requires notice_id")
        notice = db.notices.get(notice_id)
        if notice is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "notice_id does not resolve")
        domain.evaluate_notice(notice)
        if notice["case_id"] != case["id"] or notice["status"] not in ("ISSUED", "OVERDUE"):
            raise err("ERR_REINSPECTION_TARGET_INVALID",
                      "notice_id must be an ISSUED/OVERDUE notice on the same case")
    else:
        # INITIAL carries no notice reference.
        notice_id = None

    record = common_fields()
    record.update({
        "case_id": case["id"],
        "kind": body["kind"],
        "notice_id": notice_id,
        "outcome": "PENDING",
        "inspected_on": None,
    })
    db.inspections[record["id"]] = record
    return success(serialize.inspection_out(record), status=201)


@bp.get("/inspections/<iid>")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk", "Registrant")
def get_inspection(iid):
    record = lookup(db.inspections, iid)
    return success(serialize.inspection_out(record), status=200)


@bp.get("/inspections")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk")
def list_inspections():
    limit, offset = pagination_params()
    items = list(db.inspections.values())
    case_id = request.args.get("case_id")
    notice_id = request.args.get("notice_id")
    if case_id is not None:
        items = [i for i in items if i["case_id"] == case_id]
    if notice_id is not None:
        items = [i for i in items if i["notice_id"] == notice_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize.inspection_out(i) for i in page], limit, offset, total)


@bp.post("/inspections/<iid>/submit")
@require_roles("CodeOfficer")
def submit_inspection(iid):
    insp = lookup(db.inspections, iid)
    body = get_body()
    require_enum(body, "outcome", OUTCOMES)
    if insp["outcome"] != "PENDING":
        raise err("ERR_INVALID_STATE", "inspection outcome already submitted")
    insp["outcome"] = body["outcome"]
    insp["inspected_on"] = clock.now()
    touch(insp)
    return success(serialize.inspection_out(insp), status=200)
