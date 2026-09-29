"""Specimen accession, the two state dimensions, placements, mortality and husbandry logs."""

from datetime import timedelta

from flask import Blueprint

import db
import middleware as M
import response
import serializers as S
import validators as V
from errors import ApiError
from services import calc, engine

bp = Blueprint("specimens", __name__)

DISPOSITIONS = ("QUARANTINE", "CLEARED", "ON_EXHIBIT", "TRANSFER_PENDING", "TRANSFERRED",
                "DECEASED")
HEALTH_STATUSES = ("HEALTHY", "UNDER_TREATMENT", "CRITICAL_CARE", "DECEASED_PENDING_NECROPSY",
                   "NECROPSY_COMPLETE")
LOG_TYPES = ("FEEDING", "BEHAVIOR", "TREATMENT", "WEIGHT")
BEHAVIOR_CODES = ("NORMAL", "LETHARGIC", "AGGRESSIVE", "ABNORMAL_SWIM")
QUARANTINE_STATUSES = ("ACTIVE", "EXTENDED", "CLEARED", "FAILED")
VET_STATUSES = ("OPEN", "CLOSED")
VET_CASE_TYPES = ("PREVENTIVE_EXAM", "TREATMENT", "NECROPSY")

SPECIMEN_COMPUTED = (
    "exhibit_id", "disposition_status", "health_status", "pre_transfer_disposition",
    "bioload_units", "quarantine_required_days", "welfare_score", "welfare_score_variant",
    "captive_bred", "treatment_withdrawal_until",
)
PLACEMENT_COMPUTED = tuple(f for f in SPECIMEN_COMPUTED if f != "exhibit_id")
LOG_COMPUTED = ("specimen_id", "recorded_by_user_id")


@bp.route("/aquarium/specimens", methods=["POST"])
def create_specimen():
    M.authenticate({M.CURATOR})
    body = M.json_body()
    species = M.fetch_body_fk(body, "species_id", "species")
    acq = M.fetch_body_fk(body, "acquisition_request_id", "acquisition_requests")
    sire = M.fetch_body_fk(body, "sire_specimen_id", "specimens")
    dam = M.fetch_body_fk(body, "dam_specimen_id", "specimens")

    V.reject_computed(body, SPECIMEN_COMPUTED)
    accession_code = V.as_str(body, "accession_code", required=True)
    V.as_id(body, "species_id", required=True)
    arrival_at = V.as_dt(body, "arrival_at", required=True)
    holding_area = V.as_str(body, "holding_area")
    V.as_id(body, "acquisition_request_id")
    V.as_id(body, "sire_specimen_id")
    V.as_id(body, "dam_specimen_id")

    if acq is not None and acq["status"] not in ("CLEARED", "FULFILLED"):
        raise ApiError("ERR_INVALID_STATE")
    if arrival_at > db.db.clock:
        raise ApiError("ERR_TIMESTAMP_IN_FUTURE")
    for row in db.db.specimens.values():
        if row["accession_code"] == accession_code:
            raise ApiError("ERR_DUPLICATE_CODE")
    if acq is not None and int(acq["fulfilled_count"]) >= int(acq["requested_count"]):
        raise ApiError("ERR_REQUESTED_COUNT_EXCEEDED")

    source_type = acq["source_type"] if acq is not None else None
    institution = engine.source_institution_of(acq) if acq is not None else None
    required_days = calc.quarantine_required_days(species, source_type, institution)

    row = db.new_row()
    row.update({
        "accession_code": accession_code,
        "species_id": species["id"],
        "acquisition_request_id": acq["id"] if acq is not None else None,
        "exhibit_id": None,
        "holding_area": holding_area,
        "arrival_at": arrival_at,
        "disposition_status": "QUARANTINE",
        "health_status": "HEALTHY",
        "pre_transfer_disposition": None,
        "bioload_units": species["bioload_units_per_specimen"],
        "quarantine_required_days": required_days,
        "welfare_score": None,
        "welfare_score_variant": None,
        "sire_specimen_id": sire["id"] if sire is not None else None,
        "dam_specimen_id": dam["id"] if dam is not None else None,
        "captive_bred": sire is not None and dam is not None,
        "treatment_withdrawal_until": None,
    })
    db.insert("specimens", row)

    case = db.new_row()
    case.update({
        "specimen_id": row["id"],
        "protocol_days": required_days,
        "started_at": arrival_at,
        "projected_release_at": arrival_at + timedelta(days=required_days),
        "status": "ACTIVE",
        "extension_count": 0,
        "total_extension_days": 0,
        "cleared_by_user_id": None,
        "cleared_at": None,
        "failure_reason": None,
    })
    db.insert("quarantine_cases", case)

    if acq is not None:
        acq["fulfilled_count"] = int(acq["fulfilled_count"]) + 1
        if int(acq["fulfilled_count"]) >= int(acq["requested_count"]):
            acq["status"] = "FULFILLED"
        db.touch(acq)

    return response.object_response(S.specimen(row), 201)


@bp.route("/aquarium/specimens", methods=["GET"])
def list_specimens():
    M.authenticate(M.NON_LIAISON)
    species_id = M.str_param("species_id")
    acq_id = M.str_param("acquisition_request_id")
    exhibit_id = M.str_param("exhibit_id")
    sire_id = M.str_param("sire_specimen_id")
    dam_id = M.str_param("dam_specimen_id")
    disposition = M.enum_param("disposition_status", DISPOSITIONS)
    health = M.enum_param("health_status", HEALTH_STATUSES)
    limit, offset = M.pagination()

    def keep(row):
        if species_id is not None and row["species_id"] != species_id:
            return False
        if acq_id is not None and row["acquisition_request_id"] != acq_id:
            return False
        if exhibit_id is not None and row["exhibit_id"] != exhibit_id:
            return False
        if sire_id is not None and row["sire_specimen_id"] != sire_id:
            return False
        if dam_id is not None and row["dam_specimen_id"] != dam_id:
            return False
        if disposition is not None and row["disposition_status"] != disposition:
            return False
        if health is not None and row["health_status"] != health:
            return False
        return True

    rows = db.ordered("specimens", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.specimen(r) for r in page], limit, offset, total)


@bp.route("/aquarium/specimens/<row_id>", methods=["GET"])
def get_specimen(row_id):
    M.authenticate(M.NON_LIAISON)
    row = M.fetch("specimens", row_id)
    return response.object_response(S.specimen(row))


@bp.route("/aquarium/specimens/<row_id>/exhibit-placements", methods=["POST"])
def place_specimen(row_id):
    M.authenticate({M.AQUARIST})
    specimen = M.fetch("specimens", row_id)
    body = M.json_body()
    exhibit = M.fetch_body_fk(body, "exhibit_id", "exhibits")

    V.reject_computed(body, PLACEMENT_COMPUTED)
    V.as_id(body, "exhibit_id", required=True)
    expected_version = V.as_int(body, "expected_exhibit_version", required=True, minimum=0)
    override = V.as_bool(body, "restricted_posture_override", default=False)

    if expected_version != exhibit["version"]:
        raise ApiError("ERR_STALE_EXHIBIT_VERSION")
    if specimen["disposition_status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE")
    if specimen["health_status"] != "HEALTHY":
        raise ApiError("ERR_SPECIMEN_NOT_HEALTHY")
    if exhibit["posture"] == "CLOSED":
        raise ApiError("ERR_EXHIBIT_CLOSED")
    if exhibit["posture"] == "RESTRICTED" and not override:
        raise ApiError("ERR_RESTRICTED_POSTURE_OVERRIDE_REQUIRED")

    entry = engine.approved_plan_entry(exhibit["id"], specimen["species_id"])
    if entry is None:
        raise ApiError("ERR_NO_APPROVED_PLAN_ENTRY")

    occupants = [
        sp for sp in db.db.specimens.values()
        if sp["exhibit_id"] == exhibit["id"]
        and sp["species_id"] == specimen["species_id"]
        and sp["disposition_status"] in ("ON_EXHIBIT", "TRANSFER_PENDING")
    ]
    if len(occupants) >= int(entry["planned_count"]):
        raise ApiError("ERR_PLANNED_COUNT_EXCEEDED")

    projected = exhibit["occupied_bioload_units"] + specimen["bioload_units"]
    if projected > exhibit["bioload_capacity_units"]:
        raise ApiError("ERR_BIOLOAD_CAPACITY_EXCEEDED")

    specimen["exhibit_id"] = exhibit["id"]
    specimen["holding_area"] = None
    specimen["disposition_status"] = "ON_EXHIBIT"
    db.touch(specimen)
    engine.recompute_exhibit(exhibit, force=True)
    return response.object_response(S.specimen(specimen))


@bp.route("/aquarium/specimens/<row_id>/exhibit-removals", methods=["POST"])
def remove_specimen(row_id):
    M.authenticate({M.AQUARIST})
    specimen = M.fetch("specimens", row_id)
    body = M.json_body()
    V.reject_computed(body, SPECIMEN_COMPUTED)
    expected_version = V.as_int(body, "expected_exhibit_version", required=True, minimum=0)
    holding_area = V.as_str(body, "holding_area")

    exhibit = db.db.exhibits.get(specimen["exhibit_id"]) if specimen["exhibit_id"] else None
    if exhibit is None:
        raise ApiError("ERR_INVALID_STATE")
    if expected_version != exhibit["version"]:
        raise ApiError("ERR_STALE_EXHIBIT_VERSION")
    if specimen["disposition_status"] != "ON_EXHIBIT":
        raise ApiError("ERR_INVALID_STATE")

    specimen["exhibit_id"] = None
    specimen["holding_area"] = holding_area
    specimen["disposition_status"] = "CLEARED"
    db.touch(specimen)
    engine.recompute_exhibit(exhibit, force=True)
    return response.object_response(S.specimen(specimen))


@bp.route("/aquarium/specimens/<row_id>/mortality", methods=["POST"])
def declare_mortality(row_id):
    user_id, _role = M.authenticate({M.VET})
    specimen = M.fetch("specimens", row_id)
    body = M.json_body()
    V.reject_computed(body, SPECIMEN_COMPUTED)
    occurred_at = V.as_dt(body, "occurred_at", required=True)
    V.as_str(body, "cause_note")

    if specimen["disposition_status"] in ("DECEASED", "TRANSFERRED"):
        raise ApiError("ERR_ENTITY_TERMINAL")
    if occurred_at > db.db.clock:
        raise ApiError("ERR_TIMESTAMP_IN_FUTURE")

    engine.declare_mortality(specimen, occurred_at, user_id)
    return response.object_response(S.specimen(specimen))


@bp.route("/aquarium/specimens/<row_id>/husbandry-logs", methods=["POST"])
def create_log(row_id):
    user_id, _role = M.authenticate({M.AQUARIST, M.VET})
    specimen = M.fetch("specimens", row_id)
    body = M.json_body()
    V.reject_computed(body, LOG_COMPUTED)
    log_type = V.as_enum(body, "log_type", LOG_TYPES, required=True)
    logged_at = V.as_dt(body, "logged_at", required=True)
    appetite_score = V.as_int(body, "appetite_score", minimum=0, maximum=5)
    behavior_code = V.as_enum(body, "behavior_code", BEHAVIOR_CODES)
    feed_grams = V.as_dec(body, "feed_grams", minimum=0)
    weight_grams = V.as_dec(body, "weight_grams", exclusive_minimum=0)
    note = V.as_str(body, "note")

    if log_type == "FEEDING":
        if appetite_score is None:
            V.bad("Field 'appetite_score' is required for a FEEDING log")
    elif appetite_score is not None:
        V.bad("Field 'appetite_score' is only allowed on a FEEDING log")
    if log_type == "BEHAVIOR":
        if behavior_code is None:
            V.bad("Field 'behavior_code' is required for a BEHAVIOR log")
    elif behavior_code is not None:
        V.bad("Field 'behavior_code' is only allowed on a BEHAVIOR log")
    if log_type == "WEIGHT" and weight_grams is None:
        V.bad("Field 'weight_grams' is required for a WEIGHT log")

    if logged_at > db.db.clock:
        raise ApiError("ERR_TIMESTAMP_IN_FUTURE")

    row = db.new_row(with_common=False)
    row.update({
        "specimen_id": specimen["id"],
        "log_type": log_type,
        "logged_at": logged_at,
        "appetite_score": appetite_score,
        "behavior_code": behavior_code,
        "feed_grams": feed_grams,
        "weight_grams": weight_grams,
        "note": note,
        "recorded_by_user_id": user_id,
    })
    db.insert("husbandry_logs", row)

    if engine.refresh_welfare_rolling(specimen):
        db.touch(specimen)
    return response.object_response(S.husbandry_log(row), 201)


@bp.route("/aquarium/specimens/<row_id>/husbandry-logs", methods=["GET"])
def list_logs(row_id):
    M.authenticate(M.NON_LIAISON)
    specimen = M.fetch("specimens", row_id)
    log_type = M.enum_param("log_type", LOG_TYPES)
    limit, offset = M.pagination()

    def keep(row):
        if row["specimen_id"] != specimen["id"]:
            return False
        if log_type is not None and row["log_type"] != log_type:
            return False
        return True

    rows = db.ordered("husbandry_logs", keep, reverse=True)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.husbandry_log(r) for r in page], limit, offset, total)


@bp.route("/aquarium/specimens/<row_id>/quarantine-cases", methods=["GET"])
def list_quarantine_cases(row_id):
    M.authenticate(M.NON_LIAISON)
    specimen = M.fetch("specimens", row_id)
    status = M.enum_param("status", QUARANTINE_STATUSES)
    limit, offset = M.pagination()

    def keep(row):
        if row["specimen_id"] != specimen["id"]:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    rows = db.ordered("quarantine_cases", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.quarantine_case(r) for r in page], limit, offset, total)


@bp.route("/aquarium/specimens/<row_id>/veterinary-cases", methods=["GET"])
def list_vet_cases(row_id):
    M.authenticate(M.NON_LIAISON)
    specimen = M.fetch("specimens", row_id)
    status = M.enum_param("status", VET_STATUSES)
    case_type = M.enum_param("case_type", VET_CASE_TYPES)
    limit, offset = M.pagination()

    def keep(row):
        if row["specimen_id"] != specimen["id"]:
            return False
        if status is not None and row["status"] != status:
            return False
        if case_type is not None and row["case_type"] != case_type:
            return False
        return True

    rows = db.ordered("veterinary_cases", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.veterinary_case(r) for r in page], limit, offset, total)
