"""QuarterCredit routes."""

from __future__ import annotations

from flask import Blueprint, request

from app.envelope import list_response, success_response
from app.errors import invalid_pagination
from app.routes._helpers import (
    assert_claimant_self_access,
    get_json_body,
    paginate,
    parse_pagination,
    with_auth,
)
from app.serializers import serialize_quarter_credit
from app.services import quarter_credits as service


bp = Blueprint("quarter_credits", __name__)


@bp.route("/claimants/<claimant_id>/quarter-credits", methods=["POST"])
@with_auth("Claimant", "PlatformAdmin")
def append_quarter_credit(caller, claimant_id: str):
    assert_claimant_self_access(caller, claimant_id)
    body = get_json_body()
    record = service.append_quarter_credit(claimant_id, body)
    return success_response(serialize_quarter_credit(record), status=201)


@bp.route("/claimants/<claimant_id>/quarter-credits", methods=["GET"])
@with_auth("Claimant", "DDS_Examiner", "PlatformAdmin")
def list_quarter_credits(caller, claimant_id: str):
    assert_claimant_self_access(caller, claimant_id)
    limit, offset = parse_pagination()
    year_min_raw = request.args.get("year_min")
    year_max_raw = request.args.get("year_max")
    try:
        year_min = int(year_min_raw) if year_min_raw is not None else None
        year_max = int(year_max_raw) if year_max_raw is not None else None
    except ValueError:
        raise invalid_pagination("year_min/year_max must be integers")
    rows = service.list_quarter_credits(claimant_id, year_min, year_max)
    page, total = paginate(rows, limit, offset)
    return list_response(
        [serialize_quarter_credit(r) for r in page],
        limit=limit,
        offset=offset,
        total=total,
    )
