"""Scorecards: snapshot generation, recompute, publish (PRD 3.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SCORECARD_LOCKED,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import (
    BASES,
    make_record,
    touch,
    pub_scorecard,
    compute_scorecard_fields,
)
from util import parse_period
from validate import get_body, req_str, req_enum, get_resource

bp = Blueprint("scorecards", __name__)

GENERATORS = ["DiversityAdmin", "DiversityAnalyst"]
READERS = ["DiversityAdmin", "DiversityAnalyst", "BusinessUnitLead", "Auditor"]


@bp.route("/api/v1/business-units/<rid>/scorecards", methods=["POST"])
def generate_scorecard(rid):
    authorized(GENERATORS)
    bu = get_resource("business_units", rid)
    body = get_body()
    reporting_period = req_str(body, "reporting_period")
    if parse_period(reporting_period) is None:
        raise_error(ERR_INVALID_REQUEST, "reporting_period must match 'YYYY-Qn'")
    attribution_basis = req_enum(body, "attribution_basis", BASES)
    fields = compute_scorecard_fields(bu["id"], reporting_period, attribution_basis)
    rec = make_record({
        "business_unit_id": bu["id"],
        "reporting_period": reporting_period,
        "attribution_basis": attribution_basis,
        **fields,
        "status": "GENERATED",
    })
    db["scorecards"][rec["id"]] = rec
    return success_object(pub_scorecard(rec), status=201)


@bp.route("/api/v1/business-units/<rid>/scorecards", methods=["GET"])
def list_bu_scorecards(rid):
    authorized(READERS)
    bu = get_resource("business_units", rid)
    filters = {
        "reporting_period": request.args.get("reporting_period"),
        "status": request.args.get("status"),
    }
    records = [s for s in db["scorecards"].values() if s["business_unit_id"] == bu["id"]]
    return list_response(records, filters, pub_scorecard)


@bp.route("/api/v1/scorecards", methods=["GET"])
def list_scorecards():
    authorized(READERS)
    filters = {
        "business_unit_id": request.args.get("business_unit_id"),
        "goal_id": request.args.get("goal_id"),
        "reporting_period": request.args.get("reporting_period"),
        "status": request.args.get("status"),
    }
    return list_response(list(db["scorecards"].values()), filters, pub_scorecard)


@bp.route("/api/v1/scorecards/<rid>", methods=["GET"])
def get_scorecard(rid):
    authorized(READERS)
    rec = get_resource("scorecards", rid)
    return success_object(pub_scorecard(rec))


@bp.route("/api/v1/scorecards/<rid>/recompute", methods=["POST"])
def recompute_scorecard(rid):
    authorized(GENERATORS)
    rec = get_resource("scorecards", rid)
    if rec["status"] == "PUBLISHED":
        raise_error(ERR_SCORECARD_LOCKED, "PUBLISHED scorecards are locked snapshots")
    fields = compute_scorecard_fields(
        rec["business_unit_id"], rec["reporting_period"], rec["attribution_basis"]
    )
    rec.update(fields)
    touch(rec)
    return success_object(pub_scorecard(rec))


@bp.route("/api/v1/scorecards/<rid>/publish", methods=["POST"])
def publish_scorecard(rid):
    authorized(["DiversityAdmin"])
    rec = get_resource("scorecards", rid)
    if rec["status"] != "GENERATED":
        raise_error(ERR_INVALID_STATE, "publish requires status GENERATED")
    rec["status"] = "PUBLISHED"
    touch(rec)
    return success_object(pub_scorecard(rec))
