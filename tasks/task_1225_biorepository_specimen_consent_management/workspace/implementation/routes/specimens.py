"""Specimen accession + aliquot endpoints."""
from flask import Blueprint, request

import db
from clock import parse_iso8601, now
from errors import raise_error
from middleware import (
    require_roles,
    get_json_body,
    check_known_fields,
    require_fields,
    validate_enum,
    validate_string,
    validate_number,
    validate_positive_number,
    parse_pagination,
    ALL_ROLES,
)
from response import success_object, success_list
from serializers import specimen_out, aliquot_out
from services.common import make_record, get_or_404, touch
from services.specimen import recompute_volumes, consent_is_effective
from routes.kits import append_custody_event

bp = Blueprint("specimens", __name__)

SPECIMEN_TYPES = {"BLOOD", "SALIVA", "TISSUE", "PLASMA"}


@bp.route("/biobank/specimens", methods=["POST"])
def accession_specimen():
    user_id, _ = require_roles({"LabTechnician"})
    body = get_json_body()
    check_known_fields(body, {
        "donor_id", "kit_id", "consent_record_id", "specimen_type",
        "initial_volume_ml", "collected_at", "storage_slot_id",
    })
    require_fields(body, ["donor_id", "kit_id", "consent_record_id", "specimen_type", "initial_volume_ml", "collected_at"])
    donor_id = validate_string(body["donor_id"], "donor_id")
    kit_id = validate_string(body["kit_id"], "kit_id")
    consent_record_id = validate_string(body["consent_record_id"], "consent_record_id")
    specimen_type = validate_enum(body["specimen_type"], SPECIMEN_TYPES, "specimen_type")
    initial_volume_ml = validate_positive_number(body["initial_volume_ml"], "initial_volume_ml")
    collected_at = parse_iso8601(body["collected_at"], "collected_at")
    storage_slot_id = body.get("storage_slot_id")
    if storage_slot_id is not None:
        validate_string(storage_slot_id, "storage_slot_id")

    # Existence of referenced entities (left-to-right after path params; body refs here).
    donor = db.donors.get(donor_id)
    if donor is None:
        raise_error("ERR_NOT_FOUND", f"donor not found: {donor_id}")
    kit = db.collection_kits.get(kit_id)
    if kit is None:
        raise_error("ERR_NOT_FOUND", f"collection kit not found: {kit_id}")
    consent = db.consent_records.get(consent_record_id)
    if consent is None:
        raise_error("ERR_NOT_FOUND", f"consent record not found: {consent_record_id}")
    slot = None
    if storage_slot_id is not None:
        slot = db.storage_slots.get(storage_slot_id)
        if slot is None:
            raise_error("ERR_NOT_FOUND", f"storage slot not found: {storage_slot_id}")

    # Business checks in PRD order: kit RETURNED, consent ACTIVE+effective,
    # donor coherence, kit unexpired, slot AVAILABLE.
    if kit["status"] != "RETURNED":
        raise_error("ERR_KIT_NOT_RETURNED", "Kit is not RETURNED")
    if not consent_is_effective(consent):
        raise_error("ERR_CONSENT_NOT_ACTIVE", "Consent is not ACTIVE or not yet effective")
    if kit["donor_id"] != donor_id or consent["donor_id"] != donor_id:
        raise_error("ERR_DONOR_MISMATCH", "kit.donor_id or consent.donor_id differs from specimen.donor_id")
    if now() >= kit["expires_at"]:
        raise_error("ERR_KIT_EXPIRED", "Kit is expired")
    if slot is not None and slot["status"] != "AVAILABLE":
        raise_error("ERR_SLOT_NOT_AVAILABLE", "Slot is not AVAILABLE")

    # Consume the kit.
    kit["status"] = "CONSUMED"
    touch(kit)
    append_custody_event(kit, "CONSUMED", user_id, None, None)

    specimen = make_record(db.specimens, {
        "donor_id": donor_id,
        "kit_id": kit_id,
        "consent_record_id": consent_record_id,
        "storage_slot_id": storage_slot_id,
        "specimen_type": specimen_type,
        "collected_at": collected_at,
        "initial_volume_ml": initial_volume_ml,
        "residual_volume_ml": initial_volume_ml,
        "committed_volume_book_ml": 0,
        "committed_volume_physical_ml": 0,
        "lifecycle_status": "IN_STORAGE" if storage_slot_id else "ACCESSIONED",
        "viability_status": "USABLE",
    })
    return success_object(specimen_out(specimen), status=201)


@bp.route("/biobank/specimens", methods=["GET"])
def list_specimens():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.specimens.values())
    for param in ("donor_id", "kit_id", "consent_record_id", "storage_slot_id", "lifecycle_status", "viability_status"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s.get(param) == value]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([specimen_out(s) for s in page], limit, offset, total)


@bp.route("/biobank/specimens/<specimenId>", methods=["GET"])
def get_specimen(specimenId):
    require_roles(ALL_ROLES)
    specimen = get_or_404(db.specimens, specimenId, "specimen")
    return success_object(specimen_out(specimen))


@bp.route("/biobank/specimens/<specimenId>/aliquots", methods=["POST"])
def create_aliquot(specimenId):
    require_roles({"LabTechnician"})
    specimen = get_or_404(db.specimens, specimenId, "specimen")
    body = get_json_body()
    check_known_fields(body, {"initial_volume_ml", "expected_specimen_version", "storage_slot_id"})
    require_fields(body, ["initial_volume_ml", "expected_specimen_version"])
    expected = body["expected_specimen_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error("ERR_INVALID_REQUEST", "expected_specimen_version must be an integer")
    # OCC guard runs before any state or business rule.
    if expected != specimen["version"]:
        raise_error("ERR_STALE_VERSION", "expected_specimen_version does not match current version")
    initial_volume_ml = validate_number(body["initial_volume_ml"], "initial_volume_ml")
    storage_slot_id = body.get("storage_slot_id")
    slot = None
    if storage_slot_id is not None:
        validate_string(storage_slot_id, "storage_slot_id")
        slot = db.storage_slots.get(storage_slot_id)
        if slot is None:
            raise_error("ERR_NOT_FOUND", f"storage slot not found: {storage_slot_id}")
    # State: specimen must be aliquotable.
    if specimen["lifecycle_status"] not in ("ACCESSIONED", "IN_STORAGE") or specimen["viability_status"] == "QUARANTINED":
        raise_error("ERR_SPECIMEN_NOT_ALIQUOTABLE", "Specimen is not aliquotable")
    if slot is not None and slot["status"] != "AVAILABLE":
        raise_error("ERR_SLOT_NOT_AVAILABLE", "Slot is not AVAILABLE")
    if initial_volume_ml <= 0 or initial_volume_ml > specimen["residual_volume_ml"]:
        raise_error("ERR_INSUFFICIENT_SPECIMEN_VOLUME", "Aliquot volume exceeds specimen residual volume")

    first_slot_placement = (
        specimen["lifecycle_status"] == "ACCESSIONED" and storage_slot_id is not None
    )
    aliquot = make_record(db.aliquots, {
        "specimen_id": specimen["id"],
        "storage_slot_id": storage_slot_id,
        "initial_volume_ml": initial_volume_ml,
        "remaining_volume_ml": initial_volume_ml,
        "status": "IN_STORAGE",
        "reserved_for_request_id": None,
    })
    if first_slot_placement:
        specimen["lifecycle_status"] = "IN_STORAGE"
    recompute_volumes(specimen)  # debits residual and bumps version
    return success_object(aliquot_out(aliquot), status=201)


@bp.route("/biobank/specimens/<specimenId>/aliquots", methods=["GET"])
def list_specimen_aliquots(specimenId):
    require_roles(ALL_ROLES)
    specimen = get_or_404(db.specimens, specimenId, "specimen")
    limit, offset = parse_pagination()
    items = [a for a in db.aliquots.values() if a["specimen_id"] == specimen["id"]]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([aliquot_out(a) for a in page], limit, offset, total)


@bp.route("/biobank/aliquots", methods=["GET"])
def list_aliquots():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.aliquots.values())
    for param in ("specimen_id", "storage_slot_id", "reserved_for_request_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [a for a in items if a.get(param) == value]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([aliquot_out(a) for a in page], limit, offset, total)


@bp.route("/biobank/aliquots/<aliquotId>", methods=["GET"])
def get_aliquot(aliquotId):
    require_roles(ALL_ROLES)
    aliquot = get_or_404(db.aliquots, aliquotId, "aliquot")
    return success_object(aliquot_out(aliquot))


@bp.route("/biobank/aliquots/<aliquotId>/void", methods=["POST"])
def void_aliquot(aliquotId):
    require_roles({"LabTechnician"})
    aliquot = get_or_404(db.aliquots, aliquotId, "aliquot")
    get_json_body()
    if aliquot["status"] != "IN_STORAGE":
        raise_error("ERR_INVALID_STATE", "Only an IN_STORAGE aliquot can be voided")
    aliquot["status"] = "VOID"
    aliquot["remaining_volume_ml"] = 0
    touch(aliquot)
    specimen = db.specimens[aliquot["specimen_id"]]
    recompute_volumes(specimen)  # VOID excluded from residual sum -> restores volume
    return success_object(aliquot_out(aliquot))


ALIQUOT_TERMINAL_STATUSES = {"DISTRIBUTED", "DESTROYED", "VOID"}


@bp.route("/biobank/aliquots/<aliquotId>/checkout", methods=["POST"])
def checkout_aliquot(aliquotId):
    require_roles({"LabTechnician"})
    aliquot = get_or_404(db.aliquots, aliquotId, "aliquot")
    body = get_json_body()
    check_known_fields(body, {"request_id"})
    require_fields(body, ["request_id"])
    request_id = validate_string(body["request_id"], "request_id")

    # PRD §2.6 tier 6 (state preconditions) fires before tier 7 (business rules
    # including referential existence of body-supplied ids). Attempting an action
    # on a terminal-state aliquot reports ERR_ALREADY_TERMINAL.
    if aliquot["status"] in ALIQUOT_TERMINAL_STATUSES:
        raise_error("ERR_ALREADY_TERMINAL", f"Aliquot is in terminal state {aliquot['status']}")

    req = db.sample_requests.get(request_id)
    if req is None:
        raise_error("ERR_NOT_FOUND", f"sample request not found: {request_id}")

    # Checks in PRD order.
    if aliquot["status"] != "RESERVED" or aliquot["reserved_for_request_id"] != request_id:
        raise_error("ERR_ALIQUOT_NOT_RESERVED_FOR_REQUEST", "Aliquot is not RESERVED for this request")
    if req["status"] != "APPROVED":
        raise_error("ERR_REQUEST_NOT_APPROVED", "Sample request is not APPROVED")
    specimen = db.specimens[aliquot["specimen_id"]]
    consent = db.consent_records.get(specimen["consent_record_id"])
    if consent is None or not consent_is_effective(consent):
        raise_error("ERR_CONSENT_NOT_ACTIVE", "Consent is not ACTIVE")
    from services.specimen import scope_covers
    if not scope_covers(consent, req["required_uses"]):
        raise_error("ERR_CONSENT_SCOPE_VIOLATION", "Consent scope does not cover required uses")
    slot = db.storage_slots.get(aliquot["storage_slot_id"])
    if slot is not None:
        unit = db.storage_units.get(slot["storage_unit_id"])
        if unit is not None and unit["posture"] != "OPERATIONAL":
            raise_error("ERR_UNIT_NOT_OPERATIONAL", "Storage unit is not OPERATIONAL")

    # Settle.
    aliquot["status"] = "DISTRIBUTED"
    aliquot["remaining_volume_ml"] = 0
    aliquot["checked_out_for_request_id"] = request_id
    aliquot["reserved_for_request_id"] = None
    touch(aliquot)

    agreement = db.sharing_agreements.get(req["sharing_agreement_id"])
    if agreement is not None:
        # Aliquot's share of the request's charge, proportional to its volume.
        selected_volume = sum(
            a2["initial_volume_ml"]
            for a2 in db.aliquots.values()
            if a2.get("fulfill_request_id") == req["id"]
        )
        if selected_volume and selected_volume > 0:
            share = req["charged_volume_ml"] * (aliquot["initial_volume_ml"] / selected_volume)
        else:
            share = aliquot["initial_volume_ml"]
        share = round(share, 3)
        agreement["reserved_volume_ml"] = round(agreement["reserved_volume_ml"] - share, 3)
        agreement["fulfilled_volume_ml"] = round(agreement["fulfilled_volume_ml"] + share, 3)
        touch(agreement)

    req["fulfilled_volume_ml"] = round(req["fulfilled_volume_ml"] + aliquot["initial_volume_ml"], 3)
    if req["fulfilled_volume_ml"] >= req["volume_needed_ml"] and req["status"] == "APPROVED":
        req["status"] = "FULFILLED"
    touch(req)
    recompute_volumes(specimen)
    return success_object(aliquot_out(aliquot))
