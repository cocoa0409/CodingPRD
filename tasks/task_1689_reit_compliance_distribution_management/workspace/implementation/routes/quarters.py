"""Quarter endpoints with date-range and overlap validation."""

from flask import Blueprint, request

import errors
from db import db
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.common import get_json_body, make_entity, parse_date, req_date, req_string

bp = Blueprint("quarters", __name__)
ALL = ("ComplianceOfficer", "TaxDirector", "BoardDirector")


@bp.route("/reit-compliance/quarters", methods=["POST"])
def create_quarter():
    require_roles("ComplianceOfficer")
    body = get_json_body()
    reit_id = body.get("reit_id")
    if not isinstance(reit_id, str) or not reit_id:
        raise errors.validation("Field 'reit_id' is required")
    reit = db.reits.get(reit_id)
    if reit is None:
        raise errors.not_found("reit_id does not resolve to an existing REIT")

    label = req_string(body, "label")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")

    # Uniqueness: label unique within reit (priority 6, before state/date checks)
    for q in db.quarters.values():
        if q["reit_id"] == reit_id and q["label"] == label:
            raise errors.duplicate("Quarter label must be unique within the REIT")

    # Date sanity: period_end >= period_start
    if parse_date(period_end) < parse_date(period_start):
        raise errors.invalid_date_range("period_end must not precede period_start")

    # Overlap: closed intervals must not intersect; adjacency allowed
    new_start, new_end = parse_date(period_start), parse_date(period_end)
    for q in db.quarters.values():
        if q["reit_id"] != reit_id:
            continue
        ex_start, ex_end = parse_date(q["period_start"]), parse_date(q["period_end"])
        if new_start <= ex_end and ex_start <= new_end:
            raise errors.quarter_overlap(
                "New quarter's interval intersects an existing quarter of the same REIT"
            )

    quarter = make_entity({
        "reit_id": reit_id,
        "label": label,
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "gross_asset_total_cents": 0,
        "gross_income_total_cents": 0,
    })
    db.quarters[quarter["id"]] = quarter
    return success_object(dict(quarter), status=201)


@bp.route("/reit-compliance/quarters/<qid>", methods=["GET"])
def get_quarter(qid):
    require_roles(*ALL)
    quarter = db.quarters.get(qid)
    if quarter is None:
        raise errors.not_found("Quarter not found")
    return success_object(dict(quarter))


@bp.route("/reit-compliance/quarters", methods=["GET"])
def list_quarters():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    rows = list(db.quarters.values())
    reit_id = request.args.get("reit_id")
    if reit_id is not None:
        rows = [q for q in rows if q["reit_id"] == reit_id]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(q) for q in page], limit, offset, total)
