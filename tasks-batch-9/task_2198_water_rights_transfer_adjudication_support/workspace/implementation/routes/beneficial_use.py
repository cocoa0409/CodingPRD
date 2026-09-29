"""Append-only beneficial-use evidence ledger."""
from flask import Blueprint

import calc
import db
import derive
import middleware
import response
import serialize
import validate
from errors import ApiError
from routes import common

bp = Blueprint("beneficial_use", __name__)

VERIFICATION_SOURCES = ("METER", "AERIAL_IMAGERY", "AFFIDAVIT", "NONE")


@bp.route("/water-rights/<rid>/beneficial-use-records", methods=["POST"])
def create_record(rid):
    caller = middleware.authenticate(
        (middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR, middleware.ROLE_CLAIMANT)
    )
    right = common.get_right(rid)
    middleware.require_owner(caller, right["claimant_id"])

    body = validate.get_body()
    use_year = validate.req_int(body, "use_year", minimum=1850, maximum=2100)
    reported_af = validate.req_decimal(body, "reported_diversion_af", gte=0)
    irrigated_acres = validate.req_decimal(body, "irrigated_acres", gte=0)
    source = validate.req_enum(body, "verification_source", VERIFICATION_SOURCES)

    for existing in derive.use_records_for_right(right["id"]):
        if existing["use_year"] == use_year:
            raise ApiError(
                "ERR_DUPLICATE_USE_YEAR",
                "A beneficial-use record for %d already exists on this right."
                % use_year,
            )

    row = db.base_row(with_version=False)
    row.update({
        "water_right_id": right["id"],
        "use_year": use_year,
        # PRD §3.1 records "the acre-feet actually diverted and applied" and the
        # acreage "actually farmed". Unlike `requested_af`, `pod_move_miles`,
        # `return_flow_credit_af` and `claimed_af`, the PRD attaches no "at 2
        # decimal places" annotation to either of these two figures, and PRD §3.3
        # pins the per-year consumptive use at 3 decimal places computed from
        # `reported_diversion_af` itself, so the reported figure is stored as
        # supplied rather than narrowed on the way in.
        "reported_diversion_af": reported_af,
        "irrigated_acres": irrigated_acres,
        "verification_source": source,
        "reported_by_user_id": caller.user_id,
    })
    db.beneficial_use_records[row["id"]] = row

    derive.recompute_right(right)
    db.touch(right)
    return response.object_response(serialize.beneficial_use_record(row), 201)


@bp.route("/water-rights/<rid>/beneficial-use-records", methods=["GET"])
def list_records(rid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    right = common.get_right(rid)
    middleware.require_owner(caller, right["claimant_id"])

    limit, offset = validate.pagination()
    year_from = validate.query_int("use_year_from")
    year_to = validate.query_int("use_year_to")

    rows = []
    for row in derive.use_records_for_right(right["id"]):
        if year_from is not None and row["use_year"] < year_from:
            continue
        if year_to is not None and row["use_year"] > year_to:
            continue
        rows.append(row)
    rows = common.sort_by(rows, lambda r: r["use_year"])
    return common.emit(rows, serialize.beneficial_use_record, limit, offset)
