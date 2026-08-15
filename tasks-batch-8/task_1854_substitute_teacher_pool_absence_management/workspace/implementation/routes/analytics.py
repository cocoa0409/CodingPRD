"""Fill-rate analytics (PRD 3.8): one row per (school, ISO day-of-week of
start_date); both SUB_ONLY and ANY_COVERAGE variants side by side."""

from decimal import Decimal

from flask import Blueprint, request

from db import STORE
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import auth_context, require_role, ALL_ROLES
from response import ok
from util import parse_date, round4

bp = Blueprint("analytics", __name__)

SUB_FILLED_STATUSES = ("ASSIGNED", "COMPLETED", "CLOSED")


@bp.route("/analytics/fill-rate", methods=["GET"])
def fill_rate():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    from_raw = request.args.get("from_date")
    to_raw = request.args.get("to_date")
    if from_raw is None or to_raw is None:
        raise_err(ERR_INVALID_REQUEST, "from_date and to_date are required")
    from_date = parse_date(from_raw)
    to_date = parse_date(to_raw)
    if from_date is None or to_date is None:
        raise_err(ERR_INVALID_REQUEST, "from_date and to_date must be ISO dates")
    school_filter = request.args.get("school_id")

    groups = {}
    for a in STORE.absences.values():
        start = parse_date(a["start_date"])
        if not (from_date <= start <= to_date):
            continue
        if school_filter is not None and a["school_id"] != school_filter:
            continue
        key = (a["school_id"], start.isoweekday())  # 1=Mon .. 7=Sun
        groups.setdefault(key, []).append(a)

    rows = []
    for (school_id, dow) in sorted(groups.keys()):
        members = groups[(school_id, dow)]
        # CANCELLED absences belong to the group but not the denominators.
        live = [a for a in members if a["fill_status"] != "CANCELLED"]
        denom = len(live)
        sub_filled = sum(1 for a in live if a["fill_status"] in SUB_FILLED_STATUSES)
        any_filled = sub_filled + sum(1 for a in live if a["fill_status"] == "COVERED_INTERNALLY")
        if denom == 0:
            sub_rate = None
            any_rate = None
        else:
            sub_rate = round4(Decimal(sub_filled) / Decimal(denom))
            any_rate = round4(Decimal(any_filled) / Decimal(denom))
        rows.append({
            "school_id": school_id,
            "day_of_week": dow,
            "reported_count": denom,
            "sub_only_filled_count": sub_filled,
            "sub_only_fill_rate": sub_rate,
            "any_coverage_filled_count": any_filled,
            "any_coverage_fill_rate": any_rate,
        })
    return ok({"rows": rows})
