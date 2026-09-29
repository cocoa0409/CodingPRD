"""WaterRight endpoints: documentation, listing, perfection, reinstatement,
forfeiture and the forfeiture-assessment breakdown."""
from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import clock
import db
import derive
import middleware
import response
import serialize
import validate
from errors import ApiError
from routes import common

bp = Blueprint("water_rights", __name__)

PURPOSES = ("IRRIGATION", "MUNICIPAL", "STOCKWATER", "INDUSTRIAL", "INSTREAM_FLOW")
RIGHT_STATUSES = (
    "UNADJUDICATED",
    "ACTIVE",
    "ENCUMBERED",
    "PARTIALLY_TRANSFERRED",
    "SUSPENDED",
    "FORFEITED",
)
RISK_BANDS = ("LOW", "ELEVATED", "HIGH")
ZERO2 = Decimal("0.00")


@bp.route("/water-rights", methods=["POST"])
def create_right():
    middleware.authenticate((middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR))
    body = validate.get_body()
    right_number = validate.req_str(body, "right_number", min_len=1, max_len=40)
    claimant_id = validate.req_str(body, "claimant_id")
    priority_raw, priority_dt = validate.req_date(body, "priority_date")
    source_stream_code = validate.req_str(body, "source_stream_code", 1, 24)
    purpose = validate.req_enum(body, "purpose_of_use", PURPOSES)
    place_acres = validate.req_decimal(body, "place_of_use_acres", gte=0)
    authorized_af = validate.req_decimal(body, "authorized_diversion_af", gt=0)
    authorized_cfs = validate.req_decimal(body, "authorized_rate_cfs", gt=0)
    bank_enrolled = validate.req_bool(body, "bank_enrolled", default=False)

    common.get_claimant(claimant_id)

    for existing in db.water_rights.values():
        if existing["right_number"] == right_number:
            raise ApiError(
                "ERR_DUPLICATE_RIGHT_NUMBER",
                "right_number '%s' already exists." % right_number,
            )

    row = db.base_row()
    row.update({
        "claimant_id": claimant_id,
        "right_number": right_number,
        "priority_date": priority_raw,
        "source_stream_code": source_stream_code,
        "purpose_of_use": purpose,
        "place_of_use_acres": calc.q2(place_acres),
        "authorized_diversion_af": calc.q2(authorized_af),
        "authorized_rate_cfs": calc.q3(authorized_cfs),
        "status": "UNADJUDICATED",
        "certified_hcu_af": ZERO2,
        "encumbered_af": ZERO2,
        "transferred_away_af": ZERO2,
        "transferable_af": ZERO2,
        "forfeiture_risk_score": ZERO2,
        "forfeiture_risk_band": "LOW",
        "consecutive_nonuse_years": 0,
        "bank_enrolled": bool(bank_enrolled),
        "pending_review_count": 0,
        "_activated": False,
        "_forfeiture_eligible": False,
    })
    db.water_rights[row["id"]] = row
    derive.recompute_right(row)
    return response.object_response(serialize.water_right(row), 201)


@bp.route("/water-rights", methods=["GET"])
def list_rights():
    middleware.authenticate(middleware.ALL_ROLES)
    limit, offset = validate.pagination()
    claimant_id = validate.query_str("claimant_id")
    status = validate.query_enum("status", RIGHT_STATUSES)
    band = validate.query_enum("forfeiture_risk_band", RISK_BANDS)

    rows = []
    for row in db.water_rights.values():
        # A listing is a read: PRD §3.2 does not list it among the events that
        # move the stored abandonment projection.
        derive.recompute_right(row, refresh_score=False)
        if claimant_id is not None and row["claimant_id"] != claimant_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if band is not None and row["forfeiture_risk_band"] != band:
            continue
        rows.append(row)
    rows = common.sort_created_desc(rows)
    return common.emit(rows, serialize.water_right, limit, offset)


@bp.route("/water-rights/<rid>", methods=["GET"])
def get_right(rid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    right = common.get_right(rid)
    middleware.require_owner(caller, right["claimant_id"])
    return response.object_response(serialize.water_right(right))


@bp.route("/water-rights/<rid>/activate", methods=["POST"])
def activate_right(rid):
    middleware.authenticate((middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR))
    right = common.get_right(rid)
    derive.recompute_right(right)

    if right["status"] != "UNADJUDICATED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an UNADJUDICATED right may be activated (status is %s)."
            % right["status"],
        )
    records = derive.use_records_for_right(right["id"])
    if not any(r["verification_source"] in calc.ADMISSIBLE_SOURCES for r in records):
        raise ApiError(
            "ERR_NO_VERIFIED_USE_EVIDENCE",
            "At least one METER or AERIAL_IMAGERY beneficial-use record is required.",
        )

    right["_activated"] = True
    for pod in derive.pods_for_right(right["id"]):
        if pod["status"] == "PROPOSED":
            pod["status"] = "AUTHORIZED"
            db.touch(pod)
    derive.recompute_right(right)
    db.touch(right)
    return response.object_response(serialize.water_right(right))


@bp.route("/water-rights/<rid>/reinstate", methods=["POST"])
def reinstate_right(rid):
    middleware.authenticate((middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR))
    right = common.get_right(rid)
    body = validate.get_body()
    validate.req_str(body, "reinstatement_note", min_len=1, max_len=500)

    derive.recompute_right(right)
    if right["status"] != "SUSPENDED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a SUSPENDED right may be reinstated (status is %s)." % right["status"],
        )

    for app in derive.apps_for_right(right["id"]):
        for condition in derive.conditions_for_app(app["id"]):
            if condition["status"] == "VIOLATED":
                raise ApiError(
                    "ERR_VIOLATION_UNRESOLVED",
                    "An approval condition on this right is still VIOLATED.",
                )
    if right["consecutive_nonuse_years"] >= calc.FORFEITURE_ELIGIBLE_YEARS:
        raise ApiError(
            "ERR_VIOLATION_UNRESOLVED",
            "The right has accrued %d consecutive non-use years."
            % right["consecutive_nonuse_years"],
        )

    right["status"] = "ACTIVE"
    right["_activated"] = True
    derive.recompute_right(right)
    db.touch(right)
    return response.object_response(serialize.water_right(right))


@bp.route("/water-rights/<rid>/declare-forfeiture", methods=["POST"])
def declare_forfeiture(rid):
    middleware.authenticate((middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR))
    right = common.get_right(rid)
    body = validate.get_body()
    validate.req_str(body, "finding_note", min_len=1, max_len=500)

    derive.recompute_right(right)
    if right["status"] == "FORFEITED":
        raise ApiError(
            "ERR_INVALID_STATE", "FORFEITED is terminal and sticky."
        )
    if right["consecutive_nonuse_years"] < calc.FORFEITURE_ELIGIBLE_YEARS:
        raise ApiError(
            "ERR_FORFEITURE_NOT_ELIGIBLE",
            "Forfeiture requires at least %d consecutive non-use years (found %d)."
            % (calc.FORFEITURE_ELIGIBLE_YEARS, right["consecutive_nonuse_years"]),
        )

    # link 1
    right["status"] = "FORFEITED"
    right["certified_hcu_af"] = ZERO2
    right["encumbered_af"] = ZERO2
    right["transferred_away_af"] = ZERO2
    right["transferable_af"] = ZERO2
    db.touch(right)

    # links 2 and 3
    cascades.forfeiture(right)

    derive.recompute_right(right)
    return response.object_response(serialize.water_right(right))


@bp.route("/water-rights/<rid>/forfeiture-assessment", methods=["GET"])
def forfeiture_assessment(rid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    right = common.get_right(rid)
    middleware.require_owner(caller, right["claimant_id"])

    assessment = calc.forfeiture_assessment(
        derive.use_records_for_right(right["id"]),
        right["authorized_diversion_af"],
        right["status"],
        clock.current_year(),
    )
    payload = {
        "water_right_id": right["id"],
        "lookback_start_year": assessment["lookback_start_year"],
        "lookback_end_year": assessment["lookback_end_year"],
        "nonuse_year_count": assessment["nonuse_year_count"],
        "consecutive_nonuse_years": assessment["consecutive_nonuse_years"],
        "unverified_component": serialize.num(assessment["unverified_component"]),
        "underuse_component": serialize.num(assessment["underuse_component"]),
        "nonuse_component": int(assessment["nonuse_component"]),
        "suspended_penalty": int(assessment["suspended_penalty"]),
        "meter_credit": int(assessment["meter_credit"]),
        "forfeiture_risk_score": serialize.num(assessment["forfeiture_risk_score"]),
        "forfeiture_risk_band": assessment["forfeiture_risk_band"],
        "forfeiture_eligible": assessment["forfeiture_eligible"],
    }
    return response.object_response(payload)
