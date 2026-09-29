"""Historical consumptive-use studies and their certification."""
from flask import Blueprint

import calc
import clock
import db
import derive
import middleware
import response
import serialize
import validate
from errors import ApiError
from routes import common

bp = Blueprint("hcu_studies", __name__)

METHODS = ("DIVERSION_BASED", "CIR_BASED")
STUDY_STATUSES = ("DRAFT", "CERTIFIED", "SUPERSEDED")
CERTIFIABLE_RIGHT_STATUSES = (
    "ACTIVE",
    "ENCUMBERED",
    "PARTIALLY_TRANSFERRED",
    "SUSPENDED",
)


@bp.route("/water-rights/<rid>/hcu-studies", methods=["POST"])
def create_study(rid):
    middleware.authenticate((middleware.ROLE_ANALYST,))
    right = common.get_right(rid)

    body = validate.get_body()
    method = validate.req_enum(body, "method", METHODS)
    start_year = validate.req_int(
        body, "study_period_start_year", minimum=1850, maximum=2100
    )
    end_year = validate.req_int(
        body, "study_period_end_year", minimum=1850, maximum=2100
    )

    if end_year < start_year:
        raise ApiError(
            "ERR_INVALID_WINDOW",
            "study_period_end_year must be greater than or equal to study_period_start_year.",
        )

    records = calc.admissible_use_records(
        derive.use_records_for_right(right["id"]), start_year, end_year
    )
    if not records:
        raise ApiError(
            "ERR_INSUFFICIENT_USE_HISTORY",
            "No admissible beneficial-use record falls inside the study period.",
        )

    result = calc.hcu_transferable_volume(
        method, records, right["authorized_diversion_af"]
    )

    row = db.base_row()
    row.update({
        "water_right_id": right["id"],
        "method": method,
        "study_period_start_year": start_year,
        "study_period_end_year": end_year,
        "qualifying_year_count": result["qualifying_year_count"],
        "average_annual_cu_af": result["average_annual_cu_af"],
        "short_history_haircut_applied": result["short_history_haircut_applied"],
        "transferable_cu_af": result["transferable_cu_af"],
        "status": "DRAFT",
        "certified_by_user_id": None,
        "certified_at": None,
    })
    db.hcu_studies[row["id"]] = row
    return response.object_response(serialize.hcu_study(row), 201)


@bp.route("/water-rights/<rid>/hcu-studies", methods=["GET"])
def list_studies(rid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    right = common.get_right(rid)
    middleware.require_owner(caller, right["claimant_id"])

    limit, offset = validate.pagination()
    status = validate.query_enum("status", STUDY_STATUSES)
    rows = [
        s
        for s in derive.studies_for_right(right["id"])
        if status is None or s["status"] == status
    ]
    rows = common.sort_created_asc(rows)
    return common.emit(rows, serialize.hcu_study, limit, offset)


@bp.route("/hcu-studies/<sid>", methods=["GET"])
def get_study(sid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    study = common.get_study(sid)
    middleware.require_owner(caller, common.study_owner(study))
    return response.object_response(serialize.hcu_study(study))


@bp.route("/hcu-studies/<sid>/certify", methods=["POST"])
def certify_study(sid):
    caller = middleware.authenticate(
        (middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR)
    )
    study = common.get_study(sid)
    right = common.get_right(study["water_right_id"])

    body = validate.get_body()
    expected = validate.req_int(body, "expected_water_right_version", minimum=0)

    derive.recompute_right(right)
    if expected != right["version"]:
        raise ApiError(
            "ERR_STALE_RIGHT_VERSION",
            "expected_water_right_version %d does not match the right's current version %d."
            % (expected, right["version"]),
        )
    if study["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a DRAFT study may be certified (status is %s)." % study["status"],
        )
    if right["status"] not in CERTIFIABLE_RIGHT_STATUSES:
        raise ApiError(
            "ERR_RIGHT_NOT_TRANSFERABLE",
            "A right in status %s cannot back a certification." % right["status"],
        )

    for other in derive.studies_for_right(right["id"]):
        if other["id"] != study["id"] and other["status"] == "CERTIFIED":
            other["status"] = "SUPERSEDED"
            db.touch(other)

    study["status"] = "CERTIFIED"
    study["certified_by_user_id"] = caller.user_id
    study["certified_at"] = clock.now_iso()
    db.touch(study)

    right["certified_hcu_af"] = calc.q2(study["transferable_cu_af"])
    derive.recompute_right(right)
    db.touch(right)

    return response.object_response(serialize.hcu_study(study))
