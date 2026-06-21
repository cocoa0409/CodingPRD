"""Injury-case endpoints (PRD §3.7, §3.10)."""

from flask import Blueprint, request

import errors
from db import LOCK, db
from errors import err
from middleware import authenticate, require_role
from response import object_response
from routes._helpers import get_json_body, paginated, sort_by_created
from services import lookup
from services.calculations import osha_recordability
from services.common import base_entity, parse_date, touch
from services.serialize import public

bp = Blueprint("injury_cases", __name__)

READ_ROLES = {"ClinicAdmin", "Clinician", "Collector", "MRO"}
TREATMENT_LEVELS = {"FIRST_AID", "MEDICAL_TREATMENT", "LOST_TIME", "RESTRICTED_DUTY", "FATALITY"}


@bp.route("/clinic/injury-cases", methods=["POST"])
def create_injury_case():
    caller = authenticate()
    require_role(caller, {"Clinician"})
    body = get_json_body()

    with LOCK:
        # Priority 4: body FK existence (missing OR not-found -> cross-employer).
        encounter_id = body.get("encounter_id")
        enc = db.encounters.get(encounter_id) if encounter_id is not None else None
        if enc is None:
            raise err(errors.ERR_CROSS_EMPLOYER_REFERENCE, "encounter missing or not found")

        # Priority 5: body well-formedness.
        injury_date = body.get("injury_date")
        injury_d = parse_date(injury_date) if injury_date is not None else None
        if injury_d is None:
            raise err(errors.ERR_INVALID_REQUEST, "injury_date must be a valid date")

        treatment_level = body.get("treatment_level")
        if treatment_level not in TREATMENT_LEVELS:
            raise err(errors.ERR_INVALID_REQUEST, "invalid treatment_level")

        days_away = body.get("days_away", 0)
        if days_away is None:
            days_away = 0
        if isinstance(days_away, bool) or not isinstance(days_away, int) or days_away < 0:
            raise err(errors.ERR_INVALID_REQUEST, "days_away must be a non-negative integer")

        days_restricted = body.get("days_restricted", 0)
        if days_restricted is None:
            days_restricted = 0
        if isinstance(days_restricted, bool) or not isinstance(days_restricted, int) or days_restricted < 0:
            raise err(errors.ERR_INVALID_REQUEST, "days_restricted must be a non-negative integer")

        # injury_date must be <= employer current_date.
        employer = db.employers.get(enc["employer_id"])
        current = parse_date(employer["current_date"]) if employer else None
        if current is not None and injury_d > current:
            raise err(errors.ERR_INVALID_REQUEST,
                      "injury_date must be on or before the employer current_date")

        if enc["status"] != "IN_PROGRESS":
            raise err(errors.ERR_ENCOUNTER_NOT_SCHEDULED,
                      "Encounter must be IN_PROGRESS to create an injury case")

        recordable, column = osha_recordability(treatment_level, days_away, days_restricted)

        ic = base_entity()
        ic.update({
            "encounter_id": encounter_id,
            "employer_id": enc["employer_id"],
            "injury_date": injury_date,
            "treatment_level": treatment_level,
            "days_away": days_away,
            "days_restricted": days_restricted,
            "is_osha_recordable": recordable,
            "osha_column": column,
            "status": "OPEN",
        })
        db.injury_cases[ic["id"]] = ic

        enc["status"] = "PENDING_RESULTS"
        touch(enc)

        return object_response(public(ic), 201)


@bp.route("/clinic/injury-cases", methods=["GET"])
def list_injury_cases():
    caller = authenticate()
    require_role(caller, READ_ROLES)
    args = request.args
    items = list(db.injury_cases.values())
    for key in ("encounter_id", "employer_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    return paginated(sort_by_created(items))


@bp.route("/clinic/injury-cases/<ic_id>", methods=["GET"])
def get_injury_case(ic_id):
    caller = authenticate()
    require_role(caller, READ_ROLES)
    ic = lookup.get_injury_case(ic_id)
    return object_response(public(ic), 200)


@bp.route("/clinic/injury-cases/<ic_id>/reopen", methods=["POST"])
def reopen(ic_id):
    caller = authenticate()
    require_role(caller, {"Clinician"})
    with LOCK:
        ic = lookup.get_injury_case(ic_id)
        if ic["status"] != "CLOSED":
            raise err(errors.ERR_INJURY_CASE_NOT_CLOSED_FOR_REOPEN,
                      "Injury case must be CLOSED to reopen")
        enc = db.encounters.get(ic["encounter_id"])
        if enc is not None and enc["status"] in ("COMPLETED", "VOIDED"):
            raise err(errors.ERR_ENCOUNTER_LOCKED,
                      "Parent encounter is COMPLETED/VOIDED")
        ic["status"] = "OPEN"
        touch(ic)
        return object_response(public(ic), 200)
