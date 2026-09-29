"""Read surfaces for the two immutable evidence records (PRD section 3.5)."""

from flask import Blueprint, request

from auth import auth
from db import db, sort_created
from response import jsonable, ok, ok_list
from validate import lookup, page, pagination

bp = Blueprint("findings", __name__, url_prefix="/fire-district")

READERS = ("ProgramAdmin", "FireMarshal", "Inspector")


@bp.get("/zone-evaluations/<zone_evaluation_id>")
def read_zone_evaluation(zone_evaluation_id):
    auth(*READERS)
    return ok(jsonable(
        lookup("zone_evaluations", zone_evaluation_id, "ERR_ZONE_EVALUATION_NOT_FOUND")
    ))


@bp.get("/zone-evaluations")
def list_zone_evaluations():
    auth(*READERS)
    limit, offset = pagination()
    records = sort_created(list(db.zone_evaluations.values()))
    inspection_id = request.args.get("inspection_id")
    zone = request.args.get("zone")
    if inspection_id is not None:
        records = [r for r in records if r["inspection_id"] == inspection_id]
    if zone is not None:
        records = [r for r in records if r["zone"] == zone]
    return ok_list(
        [jsonable(r) for r in page(records, limit, offset)], limit, offset, len(records)
    )


@bp.get("/hardening-findings/<hardening_finding_id>")
def read_hardening_finding(hardening_finding_id):
    auth(*READERS)
    return ok(jsonable(
        lookup("hardening_findings", hardening_finding_id, "ERR_FINDING_NOT_FOUND")
    ))


@bp.get("/hardening-findings")
def list_hardening_findings():
    auth(*READERS)
    limit, offset = pagination()
    records = sort_created(list(db.hardening_findings.values()))
    inspection_id = request.args.get("inspection_id")
    item_code = request.args.get("item_code")
    if inspection_id is not None:
        records = [r for r in records if r["inspection_id"] == inspection_id]
    if item_code is not None:
        records = [r for r in records if r["item_code"] == item_code]
    return ok_list(
        [jsonable(r) for r in page(records, limit, offset)], limit, offset, len(records)
    )
