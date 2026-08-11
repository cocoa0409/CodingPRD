"""Boxes: intake, custody events, returns, destruction, shelf assignments."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_MAX_BOXES_EXCEEDED,
    ERR_CLIENT_SUSPENDED,
    ERR_CUSTODY_FLAGGED,
    ERR_SHELF_OVER_CAPACITY,
    ERR_VAULT_ZONE_REQUIRED,
    ERR_BOX_RETURN_COMMITTED,
    ERR_BOX_NOT_RETURN_COMMITTED,
    ERR_RETURN_WINDOW_EXPIRED,
    ERR_WITNESS_SEGREGATION,
)
from middleware import require_roles, check_client_user_scope
from response import success_object, success_list, parse_pagination, iso_ts
from util import (
    get_body,
    require_fields,
    reject_unknown,
    as_str,
    as_int,
    new_id,
    make_entity,
    bump,
    now_iso,
)
from services.serializers import (
    box_view,
    custody_event_view,
    destruction_certificate_view,
    shelf_assignment_view,
    document_view,
    get_agreement_for_client,
)
from services.custody import (
    append_custody_event,
    check_custody_segregation,
    check_custody_flag,
    release_active_assignment,
    destruction_cascade,
)

bp = Blueprint("boxes", __name__)

ALL_ROLES = (
    "PlatformAdmin", "IntakeClerk", "PrepTechnician", "ScanOperator", "QAReviewer",
    "Indexer", "DestructionSpecialist", "ComplianceOfficer", "BillingClerk", "ClientUser",
)


def get_box_or_404(box_id):
    b = db.boxes.get(box_id)
    if not b:
        raise ApiError(ERR_NOT_FOUND, "Box not found", 404)
    return b


def box_client_id(box):
    batch = db.batches.get(box["batch_id"])
    return batch["client_id"] if batch else None


def check_client_active_for_box(box):
    batch = db.batches.get(box["batch_id"])
    if batch:
        client = db.clients.get(batch["client_id"])
        if client and client["status"] == "SUSPENDED":
            raise ApiError(ERR_CLIENT_SUSPENDED, "Client is suspended", 403)


@bp.route("/batches/<id>/boxes", methods=["POST"])
@require_roles("IntakeClerk")
def intake_box(id, _user_id, _role):
    batch = db.batches.get(id)
    if not batch:
        raise ApiError(ERR_NOT_FOUND, "Batch not found", 404)
    body = get_body()
    require_fields(body, ["box_label", "intake_weight_grams"])
    reject_unknown(body, {"box_label", "intake_weight_grams"})
    box_label = as_str(body["box_label"], "box_label")
    weight = as_int(body["intake_weight_grams"], "intake_weight_grams", minimum=1)
    # Client suspension check (state category, before business ceilings)
    client = db.clients.get(batch["client_id"])
    if client and client["status"] == "SUSPENDED":
        raise ApiError(ERR_CLIENT_SUSPENDED, "Client is suspended", 403)
    if batch["status"] != "INTAKE":
        raise ApiError(ERR_INVALID_STATE, "Batch is not in INTAKE", 409)
    # Label unique within batch
    for b in db.boxes.values():
        if b["batch_id"] == id and b["box_label"] == box_label:
            raise ApiError(ERR_INVALID_REQUEST, "box_label already exists in this batch", 400)
    # Capacity ceiling
    agreement = get_agreement_for_client(batch["client_id"])
    if agreement:
        count = sum(1 for b in db.boxes.values() if b["batch_id"] == id)
        if count + 1 > agreement["max_boxes_per_batch"]:
            raise ApiError(ERR_MAX_BOXES_EXCEEDED, "Batch box capacity exceeded", 409)
    box = make_entity(
        {
            "batch_id": id,
            "box_label": box_label,
            "intake_weight_grams": weight,
            "status": "RECEIVED",
            "return_requested": False,
            "custody_flagged": False,
        }
    )
    db.boxes[box["id"]] = box
    # Auto-intake custody event (from_stage=INTAKE, to_stage=INTAKE)
    append_custody_event(box["id"], "INTAKE", "INTAKE", _user_id, _role, None)
    return success_object(box_view(box), status=201)


@bp.route("/boxes/<id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_box(id, _user_id, _role):
    box = get_box_or_404(id)
    check_client_user_scope(_user_id, _role, box_client_id(box))
    return success_object(box_view(box))


@bp.route("/boxes/<id>/request-return", methods=["POST"])
@require_roles("ClientUser")
def request_return(id, _user_id, _role):
    box = get_box_or_404(id)
    get_body()
    check_client_user_scope(_user_id, _role, box_client_id(box))
    check_client_active_for_box(box)
    batch = db.batches.get(box["batch_id"])
    # Temporal window: rejected once batch is DISPOSITION_PENDING or CLOSED
    if batch["status"] in ("DISPOSITION_PENDING", "CLOSED"):
        raise ApiError(ERR_RETURN_WINDOW_EXPIRED, "Return window has expired", 409)
    box["return_requested"] = True
    # When batch already DELIVERED: STORED/SCAN_COMPLETE box moves to AWAITING_DISPOSITION
    if batch["status"] == "DELIVERED" and box["status"] in ("STORED", "SCAN_COMPLETE"):
        if box["status"] == "STORED":
            release_active_assignment(box, now_iso())
        box["status"] = "AWAITING_DISPOSITION"
    bump(box)
    return success_object(box_view(box))


@bp.route("/boxes/<id>/custody-events", methods=["POST"])
@require_roles("PrepTechnician", "ScanOperator", "IntakeClerk")
def record_custody_event(id, _user_id, _role):
    box = get_box_or_404(id)
    body = get_body()
    require_fields(body, ["to_stage"])
    reject_unknown(body, {"to_stage", "notes"})
    to_stage = as_str(body["to_stage"], "to_stage")
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ApiError(ERR_INVALID_REQUEST, "notes must be a string", 400)
    check_client_active_for_box(box)
    # Role/stage pairing and state machine per to_stage
    if to_stage == "PREP":
        if _role != "PrepTechnician":
            from errors import ERR_FORBIDDEN

            raise ApiError(ERR_FORBIDDEN, "Only PrepTechnician records PREP hand-offs", 403)
        if box["status"] != "STORED":
            raise ApiError(ERR_INVALID_STATE, "Box is not STORED", 409)
    elif to_stage == "SCAN":
        if _role != "ScanOperator":
            from errors import ERR_FORBIDDEN

            raise ApiError(ERR_FORBIDDEN, "Only ScanOperator records SCAN hand-offs", 403)
        if box["status"] != "IN_PREP":
            raise ApiError(ERR_INVALID_STATE, "Box is not IN_PREP", 409)
    elif to_stage == "STORAGE":
        if _role != "IntakeClerk":
            from errors import ERR_FORBIDDEN

            raise ApiError(ERR_FORBIDDEN, "Only IntakeClerk records STORAGE hand-offs", 403)
        if box["status"] != "IN_SCAN":
            raise ApiError(ERR_INVALID_STATE, "Box is not IN_SCAN", 409)
    else:
        raise ApiError(
            ERR_INVALID_REQUEST, "to_stage must be one of PREP, SCAN, STORAGE", 400
        )
    # Business-safety checks: segregation then custody flag
    check_custody_segregation(box["id"], _user_id)
    check_custody_flag(box)
    from_stage = {
        "PREP": "STORAGE",
        "SCAN": "PREP",
        "STORAGE": "SCAN",
    }[to_stage]
    # Side effects
    if to_stage == "PREP":
        release_active_assignment(box, now_iso())
        box["status"] = "IN_PREP"
    elif to_stage == "SCAN":
        box["status"] = "IN_SCAN"
    else:  # STORAGE
        box["status"] = "SCAN_COMPLETE"
    bump(box)
    evt = append_custody_event(box["id"], from_stage, to_stage, _user_id, _role, notes)
    return success_object(custody_event_view(evt), status=201)


@bp.route("/boxes/<id>/custody-events", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_custody_events(id, _user_id, _role):
    box = get_box_or_404(id)
    check_client_user_scope(_user_id, _role, box_client_id(box))
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.custody_events.values() if e["box_id"] == id]
    items.sort(key=lambda e: e.get("_seq", 0))  # append-only, chronological
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([custody_event_view(e) for e in page], limit, offset, total)


@bp.route("/boxes/<id>/clear-custody-flag", methods=["POST"])
@require_roles("ComplianceOfficer")
def clear_custody_flag(id, _user_id, _role):
    box = get_box_or_404(id)
    get_body()
    box["custody_flagged"] = False
    bump(box)
    return success_object(box_view(box))


@bp.route("/boxes/<id>/begin-destruction", methods=["POST"])
@require_roles("DestructionSpecialist")
def begin_destruction(id, _user_id, _role):
    box = get_box_or_404(id)
    get_body()
    check_client_active_for_box(box)
    if box["status"] != "AWAITING_DISPOSITION":
        raise ApiError(ERR_INVALID_STATE, "Box is not AWAITING_DISPOSITION", 409)
    check_custody_flag(box)
    if box.get("return_requested"):
        raise ApiError(ERR_BOX_RETURN_COMMITTED, "Box is committed to return", 409)
    box["status"] = "IN_DESTRUCTION"
    bump(box)
    append_custody_event(box["id"], "STORAGE", "DESTRUCTION", _user_id, _role, None)
    return success_object(box_view(box))


@bp.route("/boxes/<id>/destruction-certificates", methods=["POST"])
@require_roles("DestructionSpecialist")
def record_destruction_certificate(id, _user_id, _role):
    box = get_box_or_404(id)
    body = get_body()
    require_fields(body, ["witness_user_id", "method"])
    reject_unknown(body, {"witness_user_id", "method"})
    witness = as_str(body["witness_user_id"], "witness_user_id")
    from util import as_enum

    method = as_enum(body["method"], "method", {"SHRED", "INCINERATE", "PULP"})
    check_client_active_for_box(box)
    if box["status"] != "IN_DESTRUCTION":
        raise ApiError(ERR_INVALID_STATE, "Box is not IN_DESTRUCTION", 409)
    check_custody_flag(box)
    # Custody adjacency segregation applies to this recording
    check_custody_segregation(box["id"], _user_id)
    # Witness segregation
    if witness == _user_id:
        raise ApiError(
            ERR_WITNESS_SEGREGATION,
            "Witness must differ from the recording actor",
            422,
        )
    batch = db.batches.get(box["batch_id"])
    cert = make_entity(
        {
            "box_id": box["id"],
            "batch_id": box["batch_id"],
            "witness_user_id": witness,
            "method": method,
            "certificate_code": "CERT-" + new_id().replace("-", "")[:16].upper(),
            "destroyed_at": now_iso(),
        }
    )
    db.destruction_certificates[cert["id"]] = cert
    box["status"] = "DESTROYED"
    bump(box)
    # Client-wide custody-flag cascade
    destruction_cascade(box, now_iso())
    return success_object(destruction_certificate_view(cert), status=201)


@bp.route("/boxes/<id>/destruction-certificates", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_box_certificate(id, _user_id, _role):
    box = get_box_or_404(id)
    check_client_user_scope(_user_id, _role, box_client_id(box))
    limit, offset = parse_pagination(request.args)
    items = [c for c in db.destruction_certificates.values() if c["box_id"] == id]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(
        [destruction_certificate_view(c) for c in page], limit, offset, total
    )


@bp.route("/boxes/<id>/mark-returned", methods=["POST"])
@require_roles("IntakeClerk")
def mark_returned(id, _user_id, _role):
    box = get_box_or_404(id)
    get_body()
    check_client_active_for_box(box)
    if box["status"] != "AWAITING_DISPOSITION":
        raise ApiError(ERR_INVALID_STATE, "Box is not AWAITING_DISPOSITION", 409)
    if not box.get("return_requested"):
        raise ApiError(ERR_BOX_NOT_RETURN_COMMITTED, "Box is not committed to return", 409)
    box["status"] = "RETURNED"
    bump(box)
    append_custody_event(box["id"], "STORAGE", "RETURN", _user_id, _role, None)
    return success_object(box_view(box))


# ---------------- Shelf assignments ----------------

@bp.route("/boxes/<id>/shelf-assignments", methods=["POST"])
@require_roles("IntakeClerk")
def create_shelf_assignment(id, _user_id, _role):
    box = get_box_or_404(id)
    body = get_body()
    require_fields(body, ["shelf_slot_id"])
    reject_unknown(body, {"shelf_slot_id"})
    slot_id = as_str(body["shelf_slot_id"], "shelf_slot_id")
    slot = db.shelf_slots.get(slot_id)
    if not slot:
        raise ApiError(ERR_NOT_FOUND, "Shelf slot not found", 404)
    check_client_active_for_box(box)
    if box["status"] != "RECEIVED":
        raise ApiError(ERR_INVALID_STATE, "Box is not RECEIVED", 409)
    check_custody_flag(box)
    # Vault zone rule: PHI box of HIPAA client must go to VAULT
    batch = db.batches.get(box["batch_id"])
    client = db.clients.get(batch["client_id"]) if batch else None
    if client and client.get("hipaa_covered"):
        has_phi = any(
            d["box_id"] == box["id"] and d.get("contains_phi")
            for d in db.documents.values()
        )
        if has_phi and slot["zone"] != "VAULT":
            raise ApiError(
                ERR_VAULT_ZONE_REQUIRED, "PHI box requires a VAULT shelf", 422
            )
    # Capacity: strictly greater rejects; equality admitted
    if slot["occupied_weight_grams"] + box["intake_weight_grams"] > slot["capacity_grams"]:
        raise ApiError(ERR_SHELF_OVER_CAPACITY, "Shelf capacity would be exceeded", 409)
    assignment = make_entity(
        {
            "box_id": box["id"],
            "shelf_slot_id": slot["id"],
            "placed_at": now_iso(),
            "released_at": None,
            "status": "ACTIVE",
        }
    )
    db.shelf_assignments[assignment["id"]] = assignment
    slot["occupied_weight_grams"] += box["intake_weight_grams"]
    bump(slot)
    box["status"] = "STORED"
    bump(box)
    append_custody_event(box["id"], "INTAKE", "STORAGE", _user_id, _role, None)
    return success_object(shelf_assignment_view(assignment), status=201)


@bp.route("/boxes/<id>/shelf-assignments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_box_shelf_assignments(id, _user_id, _role):
    box = get_box_or_404(id)
    check_client_user_scope(_user_id, _role, box_client_id(box))
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [a for a in db.shelf_assignments.values() if a["box_id"] == id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([shelf_assignment_view(a) for a in page], limit, offset, total)


@bp.route("/shelf-assignments/<id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_shelf_assignment(id, _user_id, _role):
    a = db.shelf_assignments.get(id)
    if not a:
        raise ApiError(ERR_NOT_FOUND, "Shelf assignment not found", 404)
    box = db.boxes.get(a["box_id"])
    if box:
        check_client_user_scope(_user_id, _role, box_client_id(box))
    return success_object(shelf_assignment_view(a))


@bp.route("/shelf-assignments/<id>/release", methods=["POST"])
@require_roles("IntakeClerk")
def release_shelf_assignment(id, _user_id, _role):
    a = db.shelf_assignments.get(id)
    if not a:
        raise ApiError(ERR_NOT_FOUND, "Shelf assignment not found", 404)
    get_body()
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Shelf assignment is not ACTIVE", 409)
    box = db.boxes.get(a["box_id"])
    slot = db.shelf_slots.get(a["shelf_slot_id"])
    a["status"] = "RELEASED"
    a["released_at"] = now_iso()
    bump(a)
    if slot and box:
        slot["occupied_weight_grams"] = max(
            0, slot["occupied_weight_grams"] - box["intake_weight_grams"]
        )
        bump(slot)
    return success_object(shelf_assignment_view(a))


# ---------------- Documents (nested under boxes) ----------------

@bp.route("/boxes/<id>/documents", methods=["POST"])
@require_roles("IntakeClerk", "PrepTechnician")
def register_document(id, _user_id, _role):
    box = get_box_or_404(id)
    body = get_body()
    require_fields(body, ["doc_type", "pages", "contains_phi", "ocr_confidence"])
    reject_unknown(body, {"doc_type", "pages", "contains_phi", "ocr_confidence"})
    from util import as_bool, as_enum

    doc_type = as_enum(
        body["doc_type"],
        "doc_type",
        {"MEDICAL_RECORD", "INVOICE", "CONTRACT", "CORRESPONDENCE", "OTHER"},
    )
    pages = as_int(body["pages"], "pages", minimum=1)
    contains_phi = as_bool(body["contains_phi"], "contains_phi")
    ocr_confidence = as_int(body["ocr_confidence"], "ocr_confidence", minimum=0, maximum=100)
    check_client_active_for_box(box)
    batch = db.batches.get(box["batch_id"])
    if batch["status"] not in ("INTAKE", "PREPPING"):
        raise ApiError(ERR_INVALID_STATE, "Batch is not in INTAKE or PREPPING", 409)
    doc = make_entity(
        {
            "box_id": box["id"],
            "batch_id": box["batch_id"],
            "doc_type": doc_type,
            "pages": pages,
            "contains_phi": contains_phi,
            "ocr_confidence": ocr_confidence,
            "status": "REGISTERED",
            "delivered_at": None,
        }
    )
    db.documents[doc["id"]] = doc
    return success_object(document_view(doc), status=201)


@bp.route("/boxes/<id>/documents", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_box_documents(id, _user_id, _role):
    box = get_box_or_404(id)
    check_client_user_scope(_user_id, _role, box_client_id(box))
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [d for d in db.documents.values() if d["box_id"] == id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([document_view(d) for d in page], limit, offset, total)
