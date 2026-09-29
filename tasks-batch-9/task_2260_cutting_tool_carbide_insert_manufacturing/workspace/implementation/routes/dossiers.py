"""Qualification dossiers and their quality decisions (PRD 3.6 / 3.7)."""

from flask import Blueprint

import calculations as calc
import db
import validation as v
from errors import ApiError
from middleware import authenticate
from response import object_response
from routes import common as c
from services import derive, serialize

bp = Blueprint("dossiers", __name__)

READ_ROLES = [
    "ApplicationEngineer",
    "QualityApprover",
    "GeometryEngineer",
    "MetallurgyEngineer",
    "CoatingEngineer",
    "ProductionPlanner",
]
OWNER = ["ApplicationEngineer"]
DECIDER = ["QualityApprover"]

MIN_REQUIRED_TRIALS = 2
MAX_REQUIRED_TRIALS = 8


def _segregation(dossier, user_id):
    if dossier.get("submitted_by_user_id") == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The deciding user submitted this dossier.",
        )
    for trial in derive.dossier_trials(dossier):
        if trial["operator_user_id"] == user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The deciding user operated a trial attached to this dossier.",
            )


@bp.route("/tooling/qualification-dossiers", methods=["POST"])
def create():
    authenticate(OWNER)
    payload = v.body(
        required=("product_id", "dossier_code"), optional=("required_trial_count",)
    )
    product_id = v.as_id(payload, "product_id")
    dossier_code = v.as_string(payload, "dossier_code")
    required = v.as_int(
        payload,
        "required_trial_count",
        minimum=MIN_REQUIRED_TRIALS,
        maximum=MAX_REQUIRED_TRIALS,
        default=MIN_REQUIRED_TRIALS,
    )

    product = derive.must_exist("products", product_id)
    derive.require_unique("dossiers", "dossier_code", dossier_code)

    if product["release_status"] != "QUALIFICATION":
        raise ApiError(
            "ERR_INVALID_PRODUCT_STATE",
            "A dossier is opened against a product in QUALIFICATION (currently %s)."
            % product["release_status"],
        )

    row = db.new_row(
        {
            "product_id": product["id"],
            "dossier_code": dossier_code,
            "required_trial_count": required,
            "status": "OPEN",
            "submitted_by_user_id": None,
            "decided_by_user_id": None,
            "decision_note": None,
        }
    )
    db.dossiers[row["id"]] = row
    return object_response(serialize.dossier(row), 201)


@bp.route("/tooling/qualification-dossiers", methods=["GET"])
def index():
    rows, limit, offset = c.listing(
        "dossiers", READ_ROLES, {"product_id": None, "status": c.DOSSIER_STATUSES}
    )
    return c.list_response("dossiers", rows, limit, offset)


@bp.route("/tooling/qualification-dossiers/<dossier_id>", methods=["GET"])
def read(dossier_id):
    return c.read_one("dossiers", dossier_id, READ_ROLES)


@bp.route("/tooling/qualification-dossiers/<dossier_id>/submit", methods=["POST"])
def submit(dossier_id):
    user_id, _role = authenticate(OWNER)
    v.no_body()
    dossier = derive.must_exist("dossiers", dossier_id)
    if dossier["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_DOSSIER_STATE",
            "Only an OPEN dossier may be submitted (currently %s)." % dossier["status"],
        )
    product = db.products.get(dossier["product_id"])
    if product is None or product["release_status"] != "QUALIFICATION":
        raise ApiError(
            "ERR_INVALID_PRODUCT_STATE",
            "The dossier's product must still be in QUALIFICATION.",
        )
    completed, _passed, _score = derive.dossier_counters(dossier)
    if completed < dossier["required_trial_count"]:
        raise ApiError(
            "ERR_INSUFFICIENT_TRIALS",
            "The dossier carries %d completed trial(s) of the %d required."
            % (completed, dossier["required_trial_count"]),
        )

    dossier["status"] = "SUBMITTED"
    dossier["submitted_by_user_id"] = user_id
    db.touch(dossier)
    return object_response(serialize.dossier(dossier))


@bp.route("/tooling/qualification-dossiers/<dossier_id>/approve", methods=["POST"])
def approve(dossier_id):
    user_id, _role = authenticate(DECIDER)
    payload = v.body(optional=("decision_note",))
    note = v.as_string(payload, "decision_note", nullable=True, max_len=400)

    dossier = derive.must_exist("dossiers", dossier_id)
    if dossier["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_DOSSIER_STATE",
            "Only a SUBMITTED dossier may be approved (currently %s)." % dossier["status"],
        )

    _completed, _passed, score = derive.dossier_counters(dossier)
    if score is None or calc.D(score) < calc.MIN_COMPOSITE_SCORE:
        raise ApiError(
            "ERR_COMPOSITE_SCORE_BELOW_MINIMUM",
            "The composite score %s is below the minimum of %s."
            % (score, calc.MIN_COMPOSITE_SCORE),
        )
    groups = derive.dossier_passed_groups(dossier)
    if len(groups) < calc.MIN_QUALIFIED_GROUPS:
        raise ApiError(
            "ERR_INSUFFICIENT_WORKPIECE_COVERAGE",
            "PASS trials cover %d workpiece group(s); %d are required."
            % (len(groups), calc.MIN_QUALIFIED_GROUPS),
        )
    _segregation(dossier, user_id)

    dossier["status"] = "APPROVED"
    dossier["decided_by_user_id"] = user_id
    dossier["decision_note"] = note
    db.touch(dossier)

    product = db.products.get(dossier["product_id"])
    if product is not None:
        derive.recompute_product_index(product)
        db.touch(product)
        grade = db.grades.get(product["grade_id"])
        if grade is not None:
            if grade["status"] == "PILOT":
                grade["status"] = "QUALIFIED"
            db.touch(grade)
    return object_response(serialize.dossier(dossier))


@bp.route("/tooling/qualification-dossiers/<dossier_id>/reject", methods=["POST"])
def reject(dossier_id):
    user_id, _role = authenticate(DECIDER)
    payload = v.body(required=("decision_note",))
    note = v.as_string(payload, "decision_note", max_len=400)

    dossier = derive.must_exist("dossiers", dossier_id)
    if dossier["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_DOSSIER_STATE",
            "Only a SUBMITTED dossier may be rejected (currently %s)." % dossier["status"],
        )
    _segregation(dossier, user_id)

    dossier["status"] = "REJECTED"
    dossier["decided_by_user_id"] = user_id
    dossier["decision_note"] = note
    db.touch(dossier)

    product = db.products.get(dossier["product_id"])
    if product is not None:
        product["release_status"] = "DEVELOPMENT"
        product["pinned_grade_revision"] = None
        product["pinned_geometry_revision"] = None
        product["pinned_coating_revision"] = None
        derive.recompute_lead_time(product)
        db.touch(product)
    return object_response(serialize.dossier(dossier))
