"""Damage surveys: scoring on submission and claim initiation (PRD §3.2, §3.3)."""
from flask import Blueprint

import db
import validation as v
from errors import fail, invalid_state
from middleware import OPS_ROLES, ROLE_SURVEYOR, authenticate
from response import list_response, object_response
from services import calculations as calc
from services import serializers as ser
from services import state

bp = Blueprint("surveys", __name__)


@bp.route("/vpc/damage-surveys/<survey_id>", methods=["GET"])
def read_survey(survey_id):
    authenticate(OPS_ROLES)
    survey = db.must_get("surveys", survey_id)
    return object_response(ser.survey(survey))


@bp.route("/vpc/damage-surveys", methods=["GET"])
def list_surveys():
    authenticate(OPS_ROLES)
    vehicle_id = v.query_filter("vehicle_id")
    status = v.query_filter("status")
    records = db.ordered(db.surveys)
    if vehicle_id is not None:
        records = [r for r in records if r["vehicle_id"] == vehicle_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, limit, offset, total = v.paginate(records, ser.survey)
    return list_response(items, limit, offset, total)


@bp.route("/vpc/damage-surveys/<survey_id>/submit", methods=["POST"])
def submit_survey(survey_id):
    authenticate([ROLE_SURVEYOR])
    survey = db.must_get("surveys", survey_id)
    vehicle = db.vehicles.get(survey["vehicle_id"])

    if survey["status"] != "DRAFT":
        invalid_state("only a DRAFT survey can be submitted")
    if vehicle is None or vehicle["processing_status"] != "DISCHARGED":
        invalid_state("the unit must still be in DISCHARGED to accept a survey submission")

    index = calc.severity_index(survey["line_items"])
    claimed = calc.capped_line_total(survey["line_items"])
    survey["severity_index"] = index
    survey["claimed_amount_cents"] = claimed
    survey["status"] = "SUBMITTED"
    db.touch(survey)

    vehicle["processing_status"] = "SURVEYED"
    vehicle["severity_index"] = index
    vehicle["claim_mandatory"] = index >= calc.CLAIM_MANDATORY_THRESHOLD
    if index >= calc.DAMAGE_OPEN_THRESHOLD and vehicle["damage_status"] == "NONE":
        vehicle["damage_status"] = "SURVEY_DAMAGE_OPEN"
        vehicle["damage_opened_at"] = db.clock_now()
    db.touch(vehicle)
    return object_response(ser.survey(survey))


@bp.route("/vpc/damage-surveys/<survey_id>/claims", methods=["POST"])
def file_claim(survey_id):
    user_id, _role = authenticate([ROLE_SURVEYOR])
    survey = db.must_get("surveys", survey_id)
    body = v.body()
    carrier_scac = v.req_str(body, "carrier_scac")
    expected_version = v.req_int(body, "expected_damage_survey_version")

    if expected_version != survey["version"]:
        fail(
            "ERR_STALE_SURVEY_VERSION",
            "expected_damage_survey_version %s does not match the survey's current version %s"
            % (expected_version, survey["version"]),
        )

    if survey["status"] not in ("SUBMITTED", "CLAIMED"):
        invalid_state("a claim can only be filed from a SUBMITTED or CLAIMED survey")

    # Band 22: the severity threshold first, then the live-claim check.
    if (survey["severity_index"] or 0) < calc.DAMAGE_OPEN_THRESHOLD:
        fail("ERR_CLAIM_NOT_WARRANTED", "cosmetic damage is not recoverable from the carrier")
    for existing in state.claims_of_survey(survey["id"]):
        if existing["status"] in state.OPEN_CLAIM_STATUSES:
            fail("ERR_CLAIM_ALREADY_OPEN", "a claim is already live against this survey")

    claimed = survey["claimed_amount_cents"]
    record = db.base_record()
    record.update(
        {
            "damage_survey_id": survey["id"],
            "carrier_scac": carrier_scac,
            "filed_by_user_id": user_id,
            "claimed_amount_cents": claimed,
            "recoverable_amount_cents": calc.recoverable_from_basis(claimed),
            "recoverable_basis": "SURVEY_BASED",
            "disputed_amount_cents": None,
            "revision_round": 0,
            "settled_amount_cents": None,
            "settled_by_user_id": None,
            "status": "FILED",
        }
    )
    db.claims[record["id"]] = record

    survey["status"] = "CLAIMED"
    db.touch(survey)
    return object_response(ser.claim(record), 201)
