"""Roster, patients, rooms, procedure catalogue, scope registry, lots and the clock."""

from flask import Blueprint, g

import constants
import db
import response
import util
import validate
from db import store
from errors import ApiError
from middleware import ALL, authenticate
from services import calc, query, serialize

bp = Blueprint("reference", __name__)

ADMIN = [constants.ROLE_PRACTICE_ADMIN]


def _resolve(table, row_id, error_id):
    row = store.get(table, row_id)
    if row is None:
        raise ApiError(error_id)
    return row


# ------------------------------------------------------------------- providers
@bp.route("/providers", methods=["POST"])
@authenticate(ADMIN, resolve_identity=False)
def create_provider():
    body = validate.get_body()
    fields = {
        "full_name": validate.str_field(body, "full_name"),
        "npi": validate.str_field(body, "npi"),
        "role_type": validate.enum_field(body, "role_type", constants.PROVIDER_ROLE_TYPES),
        # credential_status is never client-supplied; it always begins as ACTIVE.
        "credential_status": "ACTIVE",
        "hld_certified": validate.bool_field(body, "hld_certified", required=False, default=False),
        "ultrasound_accreditation_expires_on": validate.date_field(
            body, "ultrasound_accreditation_expires_on", required=False, default=None
        ),
    }
    row = db.new_row("providers", fields)
    return response.created_response(serialize.dump("providers", row))


@bp.route("/providers/<provider_id>", methods=["PATCH"])
@authenticate(ADMIN)
def update_provider(provider_id):
    body = validate.get_body()
    credential_status = validate.enum_field(
        body, "credential_status", constants.CREDENTIAL_STATUSES, required=False, default=None
    )
    hld_certified = validate.bool_field(body, "hld_certified", required=False, default=None)
    has_accreditation = "ultrasound_accreditation_expires_on" in body
    accreditation = validate.date_field(
        body, "ultrasound_accreditation_expires_on", required=False, default=None
    )
    row = _resolve("providers", provider_id, "ERR_PROVIDER_NOT_FOUND")
    if credential_status is not None:
        row["credential_status"] = credential_status
    if hld_certified is not None:
        row["hld_certified"] = hld_certified
    if has_accreditation:
        row["ultrasound_accreditation_expires_on"] = accreditation
    db.touch(row)
    return response.object_response(serialize.dump("providers", row))


@bp.route("/providers/<provider_id>", methods=["GET"])
@authenticate(ALL)
def read_provider(provider_id):
    row = _resolve("providers", provider_id, "ERR_PROVIDER_NOT_FOUND")
    return response.object_response(serialize.dump("providers", row))


@bp.route("/providers", methods=["GET"])
@authenticate(ALL)
def list_providers():
    return query.collection(
        "providers",
        {
            "role_type": validate.query_enum("role_type", constants.PROVIDER_ROLE_TYPES),
            "credential_status": validate.query_enum(
                "credential_status", constants.CREDENTIAL_STATUSES
            ),
            "hld_certified": validate.query_bool("hld_certified"),
        },
    )


# -------------------------------------------------------------------- patients
@bp.route("/patients", methods=["POST"])
@authenticate([constants.ROLE_PRACTICE_ADMIN, constants.ROLE_SCHEDULER])
def create_patient():
    body = validate.get_body()
    fields = {
        "mrn": validate.str_field(body, "mrn"),
        "full_name": validate.str_field(body, "full_name"),
        "date_of_birth": validate.date_field(body, "date_of_birth"),
        "primary_urologist_id": validate.str_field(body, "primary_urologist_id"),
        "egfr": validate.number_field(body, "egfr"),
        "anticoagulant_flag": validate.bool_field(
            body, "anticoagulant_flag", required=False, default=False
        ),
        "antibiotic_allergy_class": validate.enum_field(
            body,
            "antibiotic_allergy_class",
            constants.ANTIBIOTIC_ALLERGY_CLASSES,
            required=False,
            default="NONE",
        ),
    }
    # Priority 10 — the reference must resolve to a Provider whose role_type is UROLOGIST.
    urologist = store.get("providers", fields["primary_urologist_id"])
    if urologist is None or urologist["role_type"] != "UROLOGIST":
        raise ApiError("ERR_PROVIDER_NOT_FOUND")
    # Priority 18 — mrn is unique across all patients.
    for existing in store.table("patients").values():
        if existing["mrn"] == fields["mrn"]:
            raise ApiError("ERR_DUPLICATE_MRN")
    row = db.new_row("patients", fields)
    return response.created_response(serialize.dump("patients", row))


@bp.route("/patients/<patient_id>", methods=["PATCH"])
@authenticate([constants.ROLE_PRACTICE_ADMIN, constants.ROLE_UROLOGIST])
def update_patient(patient_id):
    body = validate.get_body()
    egfr = validate.number_field(body, "egfr", required=False, default=None)
    anticoagulant_flag = validate.bool_field(
        body, "anticoagulant_flag", required=False, default=None
    )
    allergy = validate.enum_field(
        body, "antibiotic_allergy_class", constants.ANTIBIOTIC_ALLERGY_CLASSES,
        required=False, default=None,
    )
    row = _resolve("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    if egfr is not None:
        row["egfr"] = egfr
    if anticoagulant_flag is not None:
        row["anticoagulant_flag"] = anticoagulant_flag
    if allergy is not None:
        row["antibiotic_allergy_class"] = allergy
    db.touch(row)
    return response.object_response(serialize.dump("patients", row))


@bp.route("/patients/<patient_id>", methods=["GET"])
@authenticate(ALL)
def read_patient(patient_id):
    row = _resolve("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    return response.object_response(serialize.dump("patients", row))


@bp.route("/patients", methods=["GET"])
@authenticate(ALL)
def list_patients():
    return query.collection(
        "patients",
        {
            "primary_urologist_id": validate.query_str("primary_urologist_id"),
            "mrn": validate.query_str("mrn"),
        },
    )


# ------------------------------------------------------------- procedure rooms
@bp.route("/procedure-rooms", methods=["POST"])
@authenticate(ADMIN)
def create_room():
    body = validate.get_body()
    fields = {
        "name": validate.str_field(body, "name"),
        "room_type": validate.enum_field(body, "room_type", constants.ROOM_TYPES),
        "turnover_minutes": validate.int_field(
            body, "turnover_minutes", required=False, default=10
        ),
        # room_status is not an input: a newly commissioned room is OPEN.
        "room_status": "OPEN",
        "accreditation_body": validate.str_field(
            body, "accreditation_body", required=False, default=None
        ),
        "accreditation_expires_on": validate.date_field(
            body, "accreditation_expires_on", required=False, default=None
        ),
    }
    for existing in store.table("rooms").values():
        if existing["name"] == fields["name"]:
            raise ApiError("ERR_DUPLICATE_ROOM_NAME")
    row = db.new_row("rooms", fields)
    return response.created_response(serialize.dump("rooms", row))


@bp.route("/procedure-rooms/<room_id>", methods=["PATCH"])
@authenticate(ADMIN)
def update_room(room_id):
    body = validate.get_body()
    room_status = validate.enum_field(
        body, "room_status", constants.ROOM_STATUSES, required=False, default=None
    )
    turnover_minutes = validate.int_field(
        body, "turnover_minutes", required=False, default=None
    )
    has_accreditation_body = "accreditation_body" in body
    accreditation_body = validate.str_field(
        body, "accreditation_body", required=False, default=None
    )
    has_expiry = "accreditation_expires_on" in body
    expiry = validate.date_field(body, "accreditation_expires_on", required=False, default=None)

    row = _resolve("rooms", room_id, "ERR_ROOM_NOT_FOUND")
    if room_status is not None:
        row["room_status"] = room_status
    if turnover_minutes is not None:
        row["turnover_minutes"] = turnover_minutes
    if has_accreditation_body:
        row["accreditation_body"] = accreditation_body
    if has_expiry:
        row["accreditation_expires_on"] = expiry
    db.touch(row)
    return response.object_response(serialize.dump("rooms", row))


@bp.route("/procedure-rooms/<room_id>", methods=["GET"])
@authenticate(ALL)
def read_room(room_id):
    row = _resolve("rooms", room_id, "ERR_ROOM_NOT_FOUND")
    return response.object_response(serialize.dump("rooms", row))


@bp.route("/procedure-rooms", methods=["GET"])
@authenticate(ALL)
def list_rooms():
    return query.collection(
        "rooms",
        {
            "room_type": validate.query_enum("room_type", constants.ROOM_TYPES),
            "room_status": validate.query_enum("room_status", constants.ROOM_STATUSES),
        },
    )


# ------------------------------------------------------------- procedure types
@bp.route("/procedure-types", methods=["POST"])
@authenticate(ADMIN)
def create_procedure_type():
    body = validate.get_body()
    fields = {
        "code": validate.enum_field(body, "code", constants.PROCEDURE_TYPE_CODES),
        "base_minutes": validate.int_field(body, "base_minutes", minimum=1),
        "cleanup_class": validate.enum_field(body, "cleanup_class", constants.CLEANUP_CLASSES),
        "allowed_room_type": validate.enum_field(
            body, "allowed_room_type", constants.ROOM_TYPES
        ),
        "requires_scope": validate.bool_field(body, "requires_scope", required=False, default=False),
        "requires_specimen": validate.bool_field(
            body, "requires_specimen", required=False, default=False
        ),
        "requires_antibiotic": validate.bool_field(
            body, "requires_antibiotic", required=False, default=False
        ),
        "consignment_required": validate.bool_field(
            body, "consignment_required", required=False, default=False
        ),
        "single_use_device_sku": validate.str_field(
            body, "single_use_device_sku", required=False, default=None
        ),
        "required_prep_codes": validate.enum_array_field(
            body, "required_prep_codes", constants.PREP_CODES, required=False, default=[]
        ),
    }
    for existing in store.table("procedure_types").values():
        if existing["code"] == fields["code"]:
            raise ApiError("ERR_DUPLICATE_PROCEDURE_TYPE_CODE")
    row = db.new_row("procedure_types", fields)
    return response.created_response(serialize.dump("procedure_types", row))


@bp.route("/procedure-types/<type_id>", methods=["GET"])
@authenticate(ALL)
def read_procedure_type(type_id):
    row = _resolve("procedure_types", type_id, "ERR_PROCEDURE_TYPE_NOT_FOUND")
    return response.object_response(serialize.dump("procedure_types", row))


@bp.route("/procedure-types", methods=["GET"])
@authenticate(ALL)
def list_procedure_types():
    return query.collection(
        "procedure_types",
        {
            "code": validate.query_enum("code", constants.PROCEDURE_TYPE_CODES),
            "allowed_room_type": validate.query_enum("allowed_room_type", constants.ROOM_TYPES),
            "requires_scope": validate.query_bool("requires_scope"),
        },
    )


# ----------------------------------------------------------------- scope assets
@bp.route("/scope-assets", methods=["POST"])
@authenticate([constants.ROLE_PRACTICE_ADMIN, constants.ROLE_STERILE_TECH])
def create_scope():
    body = validate.get_body()
    fields = {
        "serial_number": validate.str_field(body, "serial_number"),
        "scope_model": validate.str_field(body, "scope_model"),
        "channel_count": validate.int_field(body, "channel_count", minimum=1),
        "status": "AVAILABLE",
        "cycles_since_leak_test": 0,
        "leak_test_required": False,
        "hld_pass_at": None,
        "reprocess_due_at": None,
        "_soiled_at": None,
    }
    for existing in store.table("scopes").values():
        if existing["serial_number"] == fields["serial_number"]:
            raise ApiError("ERR_DUPLICATE_SCOPE_SERIAL")
    row = db.new_row("scopes", fields)
    return response.created_response(serialize.dump("scopes", row))


@bp.route("/scope-assets/<scope_id>/commissioning", methods=["POST"])
@authenticate([constants.ROLE_STERILE_TECH])
def commission_scope(scope_id):
    body = validate.get_body()
    attesting_provider_id = validate.str_field(body, "attesting_provider_id")
    scope = _resolve("scopes", scope_id, "ERR_SCOPE_NOT_FOUND")
    _resolve("providers", attesting_provider_id, "ERR_PROVIDER_NOT_FOUND")
    # One-shot: only a never-used scope sitting on the shelf may be commissioned.
    if scope["status"] != "AVAILABLE" or scope["hld_pass_at"] is not None:
        raise ApiError("ERR_INVALID_REPROCESSING_TRANSITION")
    scope["hld_pass_at"] = store.now()
    db.touch(scope)
    return response.object_response(serialize.dump("scopes", scope))


@bp.route("/scope-assets/<scope_id>", methods=["GET"])
@authenticate(ALL)
def read_scope(scope_id):
    row = _resolve("scopes", scope_id, "ERR_SCOPE_NOT_FOUND")
    return response.object_response(serialize.dump("scopes", row))


@bp.route("/scope-assets", methods=["GET"])
@authenticate(ALL)
def list_scopes():
    return query.collection(
        "scopes",
        {
            "status": validate.query_enum("status", constants.SCOPE_STATUSES),
            "leak_test_required": validate.query_bool("leak_test_required"),
            "serial_number": validate.query_str("serial_number"),
        },
    )


# ------------------------------------------------------------- consignment lots
@bp.route("/consignment-lots", methods=["POST"])
@authenticate(ADMIN)
def create_lot():
    body = validate.get_body()
    quantity_received = validate.int_field(body, "quantity_received", minimum=1)
    fields = {
        "supplier_name": validate.str_field(body, "supplier_name"),
        "sku": validate.str_field(body, "sku"),
        "device_class": validate.enum_field(body, "device_class", constants.DEVICE_CLASSES),
        "quantity_received": quantity_received,
        "quantity_available": quantity_received,
        "quantity_reserved": 0,
        "quantity_consumed": 0,
        "quantity_returned": 0,
        "quantity_wasted": 0,
        "unit_price_cents": validate.int_field(body, "unit_price_cents"),
        "lot_expires_on": validate.date_field(body, "lot_expires_on"),
        "billed_amount_cents": 0,
        "billing_basis": "PROVISIONAL",
        "billing_status": "CONSIGNED",
    }
    row = db.new_row("lots", fields)
    return response.created_response(serialize.dump("lots", row))


@bp.route("/consignment-lots/<lot_id>/return", methods=["POST"])
@authenticate(ADMIN)
def return_lot_units(lot_id):
    body = validate.get_body()
    quantity = validate.int_field(body, "quantity")
    lot = _resolve("lots", lot_id, "ERR_LOT_NOT_FOUND")
    # Priority 72 — reserved and consumed units cannot be returned.
    if quantity > lot["quantity_available"]:
        raise ApiError("ERR_CONSIGNMENT_RETURN_EXCEEDS_AVAILABLE")
    lot["quantity_available"] -= quantity
    lot["quantity_returned"] += quantity
    calc.rebill(lot, "FINAL")
    db.touch(lot)
    return response.object_response(serialize.dump("lots", lot))


@bp.route("/consignment-lots/<lot_id>", methods=["GET"])
@authenticate(ALL)
def read_lot(lot_id):
    row = _resolve("lots", lot_id, "ERR_LOT_NOT_FOUND")
    return response.object_response(serialize.dump("lots", row))


@bp.route("/consignment-lots", methods=["GET"])
@authenticate(ALL)
def list_lots():
    return query.collection(
        "lots",
        {
            "sku": validate.query_str("sku"),
            "device_class": validate.query_enum("device_class", constants.DEVICE_CLASSES),
            "billing_status": validate.query_enum("billing_status", constants.BILLING_STATUSES),
        },
    )


# ------------------------------------------------------------------ logical clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
@authenticate(ADMIN, resolve_identity=False)
def set_clock():
    body = validate.get_body()
    instant = validate.instant_field(body, "to_iso8601")
    store.clock = instant
    return response.object_response({"current_utc": util.format_instant(store.clock)})
