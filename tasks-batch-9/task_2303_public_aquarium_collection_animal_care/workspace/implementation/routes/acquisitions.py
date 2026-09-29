"""AcquisitionRequest lifecycle: creation, submission fork, clearance, cancellation."""

from datetime import timedelta

from flask import Blueprint

import db
import middleware as M
import response
import serializers as S
import validators as V
from errors import ApiError
from services import calc, engine

bp = Blueprint("acquisitions", __name__)

SOURCE_TYPES = ("CAPTIVE_BRED", "RESCUE_STRANDING", "INSTITUTIONAL_TRANSFER", "WILD_COLLECTION")
STATUSES = ("DRAFT", "PENDING_PERMIT", "READY_FOR_CLEARANCE", "CLEARED", "FULFILLED",
            "REJECTED", "CANCELLED")
PERMIT_TYPES = ("IMPORT", "TRANSPORT", "POSSESSION")
PERMIT_STATUSES = ("DRAFT", "SUBMITTED", "INFO_REQUESTED", "ISSUED", "DENIED", "REVOKED", "EXPIRED")

ACQ_COMPUTED = (
    "status", "permit_required", "permit_deadline_at", "sustainability_score",
    "sustainability_score_variant", "quota_units_reserved", "fulfilled_count",
    "cleared_by_user_id", "cleared_at", "closure_reason",
)

ALLOWED_RATINGS = {
    "GREEN_ONLY": ("GREEN",),
    "GREEN_OR_YELLOW": ("GREEN", "YELLOW"),
    "ANY_WITH_JUSTIFICATION": ("GREEN", "YELLOW", "RED"),
}


def _check_sustainability(entry, species):
    allowed = ALLOWED_RATINGS[entry["sustainability_requirement"]]
    if species["sustainability_rating"] not in allowed:
        raise ApiError("ERR_SUSTAINABILITY_REQUIREMENT_VIOLATION")


def _required_permit_type(acq):
    return "IMPORT" if acq["source_type"] == "WILD_COLLECTION" else "POSSESSION"


@bp.route("/aquarium/acquisition-requests", methods=["POST"])
def create_request():
    M.authenticate({M.CURATOR})
    body = M.json_body()
    entry = M.fetch_body_fk(body, "collection_plan_entry_id", "collection_plan_entries")
    institution = M.fetch_body_fk(body, "source_institution_id", "institutions")

    V.reject_computed(body, ACQ_COMPUTED)
    V.as_id(body, "collection_plan_entry_id", required=True)
    source_type = V.as_enum(body, "source_type", SOURCE_TYPES, required=True)
    requested_count = V.as_int(body, "requested_count", required=True, minimum=1)
    justification = V.as_str(body, "justification")
    if source_type == "INSTITUTIONAL_TRANSFER" and institution is None:
        V.bad("Field 'source_institution_id' is required for an INSTITUTIONAL_TRANSFER source")

    species = db.db.species.get(entry["species_id"])
    _check_sustainability(entry, species)

    row = db.new_row()
    row.update({
        "collection_plan_entry_id": entry["id"],
        "source_type": source_type,
        "source_institution_id": institution["id"] if institution is not None else None,
        "requested_count": requested_count,
        "justification": justification,
        "status": "DRAFT",
        # PRD §3.5: true when the species' own `permit_required` is true **or**
        # `source_type` is `WILD_COLLECTION`.
        "permit_required": bool(species["permit_required"]) or source_type == "WILD_COLLECTION",
        "permit_deadline_at": None,
        "sustainability_score": calc.sustainability_score(
            species, source_type, institution, requested_count, "PROVISIONAL"),
        "sustainability_score_variant": "PROVISIONAL",
        "quota_units_reserved": 0,
        "fulfilled_count": 0,
        "cleared_by_user_id": None,
        "cleared_at": None,
        "closure_reason": None,
    })
    db.insert("acquisition_requests", row)
    return response.object_response(S.acquisition_request(row), 201)


@bp.route("/aquarium/acquisition-requests", methods=["GET"])
def list_requests():
    M.authenticate(M.NON_LIAISON)
    entry_id = M.str_param("collection_plan_entry_id")
    institution_id = M.str_param("source_institution_id")
    status = M.enum_param("status", STATUSES)
    source_type = M.enum_param("source_type", SOURCE_TYPES)
    limit, offset = M.pagination()

    def keep(row):
        if entry_id is not None and row["collection_plan_entry_id"] != entry_id:
            return False
        if institution_id is not None and row["source_institution_id"] != institution_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if source_type is not None and row["source_type"] != source_type:
            return False
        return True

    rows = db.ordered("acquisition_requests", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.acquisition_request(r) for r in page], limit, offset, total)


@bp.route("/aquarium/acquisition-requests/<row_id>", methods=["GET"])
def get_request(row_id):
    M.authenticate(M.NON_LIAISON)
    row = M.fetch("acquisition_requests", row_id)
    return response.object_response(S.acquisition_request(row))


@bp.route("/aquarium/acquisition-requests/<row_id>/submission", methods=["POST"])
def submit_request(row_id):
    M.authenticate({M.CURATOR})
    acq = M.fetch("acquisition_requests", row_id)
    body = M.json_body()
    V.reject_computed(body, ACQ_COMPUTED)
    justification = V.as_str(body, "justification")

    if acq["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    entry = engine.plan_entry_of(acq)
    if entry is None or entry["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")

    if justification is not None:
        acq["justification"] = justification
    if (entry["sustainability_requirement"] == "ANY_WITH_JUSTIFICATION"
            and not acq["justification"]):
        raise ApiError("ERR_JUSTIFICATION_REQUIRED")

    species = db.db.species.get(entry["species_id"])
    _check_sustainability(entry, species)

    if acq["permit_required"]:
        acq["status"] = "PENDING_PERMIT"
        acq["permit_deadline_at"] = db.db.clock + timedelta(days=engine.PERMIT_DEADLINE_DAYS)
    else:
        acq["status"] = "READY_FOR_CLEARANCE"
        acq["permit_deadline_at"] = None
    db.touch(acq)
    return response.object_response(S.acquisition_request(acq))


@bp.route("/aquarium/acquisition-requests/<row_id>/clearance", methods=["POST"])
def clear_request(row_id):
    user_id, _role = M.authenticate({M.DIRECTOR})
    acq = M.fetch("acquisition_requests", row_id)
    body = M.json_body()
    V.reject_computed(body, ACQ_COMPUTED)
    expected_species_version = V.as_int(body, "expected_species_version", required=True, minimum=0)
    V.as_str(body, "note")

    entry = engine.plan_entry_of(acq)
    species = db.db.species.get(entry["species_id"]) if entry is not None else None
    if species is None:
        raise ApiError("ERR_SPECIES_NOT_FOUND")
    if expected_species_version != species["version"]:
        raise ApiError("ERR_STALE_SPECIES_VERSION")

    if acq["status"] not in ("PENDING_PERMIT", "READY_FOR_CLEARANCE"):
        raise ApiError("ERR_INVALID_STATE")
    if entry["approved_by_user_id"] is not None and user_id == entry["approved_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION")

    has_issued_permit = False
    if acq["status"] == "PENDING_PERMIT":
        issued = [p for p in engine.permits_of_acquisition(acq["id"]) if p["status"] == "ISSUED"]
        if not issued:
            raise ApiError("ERR_PERMIT_NOT_ISSUED")
        required_type = _required_permit_type(acq)
        if not any(p["permit_type"] == required_type for p in issued):
            raise ApiError("ERR_PERMIT_TYPE_MISMATCH")
        has_issued_permit = True

    if acq["source_type"] == "WILD_COLLECTION":
        projected = int(species["wild_take_quota_reserved"]) + int(acq["requested_count"])
        if projected > int(species["wild_take_quota_annual"]):
            raise ApiError("ERR_QUOTA_EXCEEDED")

    institution = engine.source_institution_of(acq)
    final_score = calc.sustainability_score(
        species, acq["source_type"], institution, acq["requested_count"], "FINAL",
        has_issued_permit)
    if final_score < calc.MIN_CLEARANCE_SCORE:
        raise ApiError("ERR_CLEARANCE_SCORE_TOO_LOW")

    acq["sustainability_score"] = final_score
    acq["sustainability_score_variant"] = "FINAL"
    acq["status"] = "CLEARED"
    acq["cleared_by_user_id"] = user_id
    acq["cleared_at"] = db.db.clock
    if acq["source_type"] == "WILD_COLLECTION":
        acq["quota_units_reserved"] = int(acq["requested_count"])
        species["wild_take_quota_reserved"] = (
            int(species["wild_take_quota_reserved"]) + int(acq["requested_count"]))
        # PRD §3.5: the quota reservation and the species `version` increment happen
        # "for a `WILD_COLLECTION` source only" — every other channel leaves the
        # species record, and therefore its optimistic-concurrency token, untouched.
        db.touch(species)
    db.touch(acq)
    return response.object_response(S.acquisition_request(acq))


@bp.route("/aquarium/acquisition-requests/<row_id>/cancellation", methods=["POST"])
def cancel_request(row_id):
    M.authenticate({M.CURATOR})
    acq = M.fetch("acquisition_requests", row_id)
    body = M.json_body()
    V.reject_computed(body, ACQ_COMPUTED)
    V.as_str(body, "reason")

    if acq["status"] in ("FULFILLED", "REJECTED", "CANCELLED"):
        raise ApiError("ERR_ENTITY_TERMINAL")
    if acq["status"] not in engine.CANCELLABLE_ACQ_STATUSES or int(acq["fulfilled_count"]) != 0:
        raise ApiError("ERR_INVALID_STATE")

    engine.cancel_acquisition(acq, "CURATOR_CANCELLED")
    return response.object_response(S.acquisition_request(acq))


@bp.route("/aquarium/acquisition-requests/<row_id>/permits", methods=["GET"])
def list_request_permits(row_id):
    M.authenticate(M.NON_LIAISON)
    acq = M.fetch("acquisition_requests", row_id)
    status = M.enum_param("status", PERMIT_STATUSES)
    permit_type = M.enum_param("permit_type", PERMIT_TYPES)
    limit, offset = M.pagination()

    def keep(row):
        if row["acquisition_request_id"] != acq["id"]:
            return False
        if status is not None and row["status"] != status:
            return False
        if permit_type is not None and row["permit_type"] != permit_type:
            return False
        return True

    rows = db.ordered("permits", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.permit(r) for r in page], limit, offset, total)
