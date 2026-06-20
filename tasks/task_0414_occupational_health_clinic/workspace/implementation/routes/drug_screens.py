"""Drug-screen endpoints (PRD §3.5, §3.6)."""

from flask import Blueprint, request

import errors
from db import LOCK, db
from errors import err
from middleware import authenticate, require_role
from response import object_response
from routes._helpers import get_json_body, paginated, sort_by_created
from services import lookup
from services.common import base_entity, touch
from services.custody import append_event
from services.serialize import public

bp = Blueprint("drug_screens", __name__)

READ_ROLES = {"ClinicAdmin", "Clinician", "Collector", "MRO"}
LAB_RESULTS = {"NEGATIVE", "NON_NEGATIVE", "REJECTED_FOR_TESTING"}
MRO_RESULTS = {"NEGATIVE", "POSITIVE", "REFUSAL", "CANCELLED"}


@bp.route("/clinic/drug-screens", methods=["POST"])
def create_drug_screen():
    caller = authenticate()
    require_role(caller, {"Clinician", "Collector"})
    body = get_json_body()

    with LOCK:
        # Priority 4: body FK existence (missing OR not-found -> cross-employer).
        encounter_id = body.get("encounter_id")
        enc = db.encounters.get(encounter_id) if encounter_id is not None else None
        if enc is None:
            raise err(errors.ERR_CROSS_EMPLOYER_REFERENCE, "encounter missing or not found")

        # Priority 5: body well-formedness.
        seal = body.get("specimen_seal_intact")
        if not isinstance(seal, bool):
            raise err(errors.ERR_INVALID_REQUEST, "specimen_seal_intact must be a boolean")

        # Creating the result entity drives IN_PROGRESS -> PENDING_RESULTS.
        if enc["status"] != "IN_PROGRESS":
            raise err(errors.ERR_ENCOUNTER_NOT_SCHEDULED,
                      "Encounter must be IN_PROGRESS to create a drug screen")

        ds = base_entity()
        ds.update({
            "encounter_id": encounter_id,
            "employer_id": enc["employer_id"],
            "is_dot": enc.get("panel_code") == "DRUG_DOT",
            "specimen_seal_intact": seal,
            "lab_result": None,
            "mro_verified_result": None,
            "mro_user_id": None,
            "recollection_count": 0,
            "status": "AWAITING_COLLECTION",
            "_custody_cycle": 0,
        })
        db.drug_screens[ds["id"]] = ds

        enc["status"] = "PENDING_RESULTS"
        touch(enc)

        return object_response(public(ds), 201)


@bp.route("/clinic/drug-screens", methods=["GET"])
def list_drug_screens():
    caller = authenticate()
    require_role(caller, READ_ROLES)
    args = request.args
    items = list(db.drug_screens.values())
    for key in ("encounter_id", "employer_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [d for d in items if d.get(key) == val]
    return paginated(sort_by_created(items))


@bp.route("/clinic/drug-screens/<ds_id>", methods=["GET"])
def get_drug_screen(ds_id):
    caller = authenticate()
    require_role(caller, READ_ROLES)
    ds = lookup.get_drug_screen(ds_id)
    return object_response(public(ds), 200)


@bp.route("/clinic/drug-screens/<ds_id>/lab-result", methods=["POST"])
def lab_result(ds_id):
    caller = authenticate()
    require_role(caller, {"Clinician"})
    body = get_json_body()
    with LOCK:
        ds = lookup.get_drug_screen(ds_id)

        lab = body.get("lab_result")
        if lab not in LAB_RESULTS:
            raise err(errors.ERR_INVALID_REQUEST, "invalid lab_result")

        if ds["status"] != "AT_LAB":
            raise err(errors.ERR_DRUG_SCREEN_NOT_AT_LAB,
                      "Screen must be AT_LAB to record lab result")

        ds["lab_result"] = lab
        ds["status"] = "LAB_REPORTED"
        touch(ds)
        append_event(ds, "LAB_REPORT", caller.user_id)
        return object_response(public(ds), 200)


@bp.route("/clinic/drug-screens/<ds_id>/mro-receive", methods=["POST"])
def mro_receive(ds_id):
    caller = authenticate()
    require_role(caller, {"MRO"})
    with LOCK:
        ds = lookup.get_drug_screen(ds_id)
        employer = db.employers.get(ds["employer_id"])
        enc = db.encounters.get(ds["encounter_id"])

        if ds["status"] != "LAB_REPORTED":
            raise err(errors.ERR_DRUG_SCREEN_NOT_LAB_REPORTED,
                      "Screen must be LAB_REPORTED for mro-receive")

        # MRO assignment (priority 9).
        if employer is None or caller.user_id != employer.get("mro_user_id"):
            raise err(errors.ERR_MRO_NOT_ASSIGNED, "Acting MRO is not the employer's assigned MRO")
        # Segregation of duties (priority 10).
        if enc is not None and caller.user_id == enc.get("clinician_user_id"):
            raise err(errors.ERR_SEGREGATION_OF_DUTIES,
                      "MRO must differ from the encounter clinician")

        ds["status"] = "MRO_REVIEW"
        ds["mro_user_id"] = caller.user_id
        touch(ds)
        append_event(ds, "MRO_RECEIVE", caller.user_id)
        return object_response(public(ds), 200)


@bp.route("/clinic/drug-screens/<ds_id>/mro-verify", methods=["POST"])
def mro_verify(ds_id):
    caller = authenticate()
    require_role(caller, {"MRO"})
    body = get_json_body()
    with LOCK:
        ds = lookup.get_drug_screen(ds_id)
        employer = db.employers.get(ds["employer_id"])
        enc = db.encounters.get(ds["encounter_id"])

        result = body.get("mro_verified_result")
        if result not in MRO_RESULTS:
            raise err(errors.ERR_INVALID_REQUEST, "invalid mro_verified_result")

        if ds["status"] != "MRO_REVIEW":
            raise err(errors.ERR_DRUG_SCREEN_NOT_IN_MRO_REVIEW,
                      "Screen must be MRO_REVIEW to verify")

        # MRO assignment + segregation of duties.
        if employer is None or caller.user_id != employer.get("mro_user_id"):
            raise err(errors.ERR_MRO_NOT_ASSIGNED, "Acting MRO is not the employer's assigned MRO")
        if enc is not None and caller.user_id == enc.get("clinician_user_id"):
            raise err(errors.ERR_SEGREGATION_OF_DUTIES,
                      "MRO must differ from the encounter clinician")

        if result == "CANCELLED":
            ds["status"] = "CANCELLED"
            ds["mro_verified_result"] = "CANCELLED"
            touch(ds)
            return object_response(public(ds), 200)

        # Non-cancelled verify: consistency with lab_result.
        lab = ds.get("lab_result")
        if lab == "NEGATIVE" and result != "NEGATIVE":
            raise err(errors.ERR_MRO_RESULT_INCONSISTENT,
                      "NEGATIVE lab result must verify as NEGATIVE")
        if lab == "REJECTED_FOR_TESTING":
            raise err(errors.ERR_MRO_RESULT_INCONSISTENT,
                      "REJECTED_FOR_TESTING must be cancelled, not verified")

        ds["status"] = "VERIFIED"
        ds["mro_verified_result"] = result
        touch(ds)
        return object_response(public(ds), 200)


@bp.route("/clinic/drug-screens/<ds_id>/order-recollection", methods=["POST"])
def order_recollection(ds_id):
    caller = authenticate()
    require_role(caller, {"MRO"})
    with LOCK:
        ds = lookup.get_drug_screen(ds_id)
        employer = db.employers.get(ds["employer_id"])

        if ds["status"] != "MRO_REVIEW":
            raise err(errors.ERR_DRUG_SCREEN_NOT_IN_MRO_REVIEW,
                      "Screen must be MRO_REVIEW to order a recollection")

        # MRO assignment applies (segregation-of-duties does NOT per §3.6).
        if employer is None or caller.user_id != employer.get("mro_user_id"):
            raise err(errors.ERR_MRO_NOT_ASSIGNED, "Acting MRO is not the employer's assigned MRO")

        justified = (ds.get("specimen_seal_intact") is False
                     or ds.get("lab_result") == "REJECTED_FOR_TESTING")
        if not justified:
            raise err(errors.ERR_RECOLLECTION_NOT_JUSTIFIED,
                      "Recollection requires a broken seal or REJECTED_FOR_TESTING")

        if ds["recollection_count"] >= 2:
            raise err(errors.ERR_RECOLLECTION_LIMIT_REACHED,
                      "Recollection limit (2) reached")

        # MRO_REVIEW -> RECOLLECT_ORDERED -> (auto) AWAITING_COLLECTION.
        ds["recollection_count"] += 1
        ds["lab_result"] = None
        ds["mro_verified_result"] = None
        ds["status"] = "AWAITING_COLLECTION"
        # New collection cycle: fresh custody chain required.
        ds["_custody_cycle"] = ds.get("_custody_cycle", 0) + 1
        touch(ds)
        return object_response(public(ds), 200)
