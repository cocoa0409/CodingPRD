from flask import Blueprint, request

import db
from errors import (
    ERR_ACTIVE_PACKET_EXISTS,
    ERR_INVALID_ITEM_STATE,
    ERR_INVALID_PACKET_STATE,
    ERR_INVALID_REQUEST,
    ERR_ITEM_EVIDENCE_INVALID,
    ERR_ITEM_NOT_WAIVABLE,
    ERR_NOT_FOUND,
    ERR_NURSE_NOT_CLEAR,
    ERR_NURSE_NOT_FOUND,
    ERR_INVALID_NURSE_STATE,
    ERR_OWNERSHIP_VIOLATION,
    ERR_PACKET_ITEMS_INCOMPLETE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNIT_NOT_FOUND,
    ApiError,
)
from middleware import auth_context, get_body, pagination_params, require_role, validate_body
from response import success_list, success_object
from services.core import all_entities, create_entity, get_or_404, serialize, touch
from services.derived import ITEM_DEFS, ITEM_ORDER, recompute_readiness

bp = Blueprint("packets", __name__)

PACKET_CREATE_SCHEMA = {
    "nurse_id": ("string", True, None),
    "target_unit_id": ("string", True, None),
}

EVIDENCE_SCHEMA = {
    "evidence_ref": ("string", True, None),
}

WAIVE_SCHEMA = {
    "waive_reason": ("string", True, None),
}

REJECT_SCHEMA = {
    "rejection_reason": ("string", True, None),
}

SUBMITTABLE_ITEM_STATES = ("SUBMITTED", "VERIFIED", "WAIVED")


def _packet_or_404(packet_id):
    return get_or_404("packets", packet_id, ERR_NOT_FOUND, "Packet not found")


def _item_or_404(item_id):
    return get_or_404("packet_items", item_id, ERR_NOT_FOUND, "Packet item not found")


def _packet_items(packet_id):
    return [i for i in all_entities("packet_items") if i["packet_id"] == packet_id]


@bp.route("/credentialing/credential-packets", methods=["POST"])
def create_packet():
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    body = validate_body(get_body(), PACKET_CREATE_SCHEMA)
    nurse = get_or_404("nurses", body["nurse_id"], ERR_NURSE_NOT_FOUND, "nurse_id does not reference an existing nurse")
    unit = get_or_404("units", body["target_unit_id"], ERR_UNIT_NOT_FOUND, "target_unit_id does not reference an existing unit")
    if any(
        p for p in all_entities("packets")
        if p["nurse_id"] == nurse["id"] and p["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW")
    ):
        raise ApiError(ERR_ACTIVE_PACKET_EXISTS, "Nurse already has an active credential packet", 409)
    packet = create_entity("packets", {
        "nurse_id": nurse["id"],
        "target_unit_id": unit["id"],
        "status": "DRAFT",
        "readiness_score": 0,
        "created_by_user_id": user_id,
        "reviewed_by_user_id": None,
        "rejection_reason": None,
    })
    # Materialize the checklist in the fixed order; ACLS only when the target
    # unit requires it.
    for item_type in ITEM_ORDER:
        if item_type == "ACLS" and "ACLS" not in unit["required_cert_types"]:
            continue
        weight, critical = ITEM_DEFS[item_type]
        create_entity("packet_items", {
            "packet_id": packet["id"],
            "item_type": item_type,
            "critical": critical,
            "weight": weight,
            "status": "MISSING",
            "evidence_ref": None,
            "submitted_by_user_id": None,
            "source_credential_id": None,
        })
    return success_object(serialize("packets", packet), 201)


@bp.route("/credentialing/credential-packets", methods=["GET"])
def list_packets():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("packets")
    for param in ("nurse_id", "target_unit_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [p for p in rows if p[param] == value]
    total = len(rows)
    return success_list([serialize("packets", p) for p in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/credential-packets/<packetId>", methods=["GET"])
def get_packet(packetId):
    auth_context()
    packet = _packet_or_404(packetId)
    return success_object(serialize("packets", packet))


def _submit_packet(packet, user_id, allowed_states):
    if packet["nurse_id"] != user_id:
        raise ApiError(ERR_OWNERSHIP_VIOLATION, "Only the owning nurse may submit this packet", 403)
    if packet["status"] not in allowed_states:
        raise ApiError(ERR_INVALID_PACKET_STATE, "Packet is not in a submittable state", 409)
    items = _packet_items(packet["id"])
    if any(i["status"] not in SUBMITTABLE_ITEM_STATES for i in items):
        raise ApiError(ERR_PACKET_ITEMS_INCOMPLETE, "Every item must be SUBMITTED, VERIFIED, or WAIVED", 409)
    packet["status"] = "SUBMITTED"
    touch(packet)
    return success_object(serialize("packets", packet))


@bp.route("/credentialing/credential-packets/<packetId>/submit", methods=["POST"])
def submit_packet(packetId):
    user_id, role = auth_context()
    require_role(role, {"Nurse"})
    packet = _packet_or_404(packetId)
    return _submit_packet(packet, user_id, ("DRAFT", "REJECTED"))


@bp.route("/credentialing/credential-packets/<packetId>/resubmit", methods=["POST"])
def resubmit_packet(packetId):
    user_id, role = auth_context()
    require_role(role, {"Nurse"})
    packet = _packet_or_404(packetId)
    return _submit_packet(packet, user_id, ("REJECTED",))


@bp.route("/credentialing/credential-packets/<packetId>/start-review", methods=["POST"])
def start_review(packetId):
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    packet = _packet_or_404(packetId)
    if packet["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_PACKET_STATE, "Only a SUBMITTED packet can enter review", 409)
    if user_id == packet["created_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Reviewer must differ from the assembler", 403)
    packet["status"] = "UNDER_REVIEW"
    touch(packet)
    return success_object(serialize("packets", packet))


@bp.route("/credentialing/credential-packets/<packetId>/approve", methods=["POST"])
def approve_packet(packetId):
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    packet = _packet_or_404(packetId)
    if packet["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_PACKET_STATE, "Only an UNDER_REVIEW packet can be approved", 409)
    if user_id == packet["created_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Approver must differ from the assembler", 403)
    items = _packet_items(packet["id"])
    if any(i["status"] not in ("VERIFIED", "WAIVED") for i in items):
        raise ApiError(ERR_PACKET_ITEMS_INCOMPLETE, "Every item must be VERIFIED or WAIVED for approval", 409)
    nurse = db.STORES["nurses"].get(packet["nurse_id"])
    if nurse is None or nurse["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_NURSE_STATE, "Packet approval requires an ACTIVE nurse", 409)
    if nurse["credential_posture"] != "CLEAR":
        raise ApiError(ERR_NURSE_NOT_CLEAR, "Packet approval requires a CLEAR credential posture", 409)
    packet["status"] = "APPROVED"
    packet["reviewed_by_user_id"] = user_id
    touch(packet)
    return success_object(serialize("packets", packet))


@bp.route("/credentialing/credential-packets/<packetId>/reject", methods=["POST"])
def reject_packet(packetId):
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    packet = _packet_or_404(packetId)
    body = validate_body(get_body(allow_empty=False), REJECT_SCHEMA)
    if packet["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_PACKET_STATE, "Only an UNDER_REVIEW packet can be rejected", 409)
    if user_id == packet["created_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Reviewer must differ from the assembler", 403)
    packet["status"] = "REJECTED"
    packet["reviewed_by_user_id"] = user_id
    packet["rejection_reason"] = body["rejection_reason"]
    touch(packet)
    return success_object(serialize("packets", packet))


# --- Packet items ----------------------------------------------------------------

@bp.route("/credentialing/packet-items", methods=["GET"])
def list_items():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("packet_items")
    for param in ("packet_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [i for i in rows if i[param] == value]
    total = len(rows)
    return success_list([serialize("packet_items", i) for i in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/packet-items/<itemId>", methods=["GET"])
def get_item(itemId):
    auth_context()
    item = _item_or_404(itemId)
    return success_object(serialize("packet_items", item))


@bp.route("/credentialing/packet-items/<itemId>/submit-evidence", methods=["POST"])
def submit_evidence(itemId):
    user_id, role = auth_context()
    require_role(role, {"Nurse"})
    item = _item_or_404(itemId)
    packet = db.STORES["packets"].get(item["packet_id"])
    if packet is None or packet["nurse_id"] != user_id:
        raise ApiError(ERR_OWNERSHIP_VIOLATION, "Only the owning nurse may submit evidence", 403)
    body = validate_body(get_body(allow_empty=False), EVIDENCE_SCHEMA)
    if item["status"] not in ("MISSING", "INVALIDATED"):
        raise ApiError(ERR_INVALID_ITEM_STATE, "Only MISSING or INVALIDATED items accept evidence", 409)
    if packet["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(ERR_INVALID_PACKET_STATE, "Parent packet must be DRAFT or REJECTED", 409)
    item["status"] = "SUBMITTED"
    item["evidence_ref"] = body["evidence_ref"]
    item["submitted_by_user_id"] = user_id
    touch(item)
    recompute_readiness(packet)
    touch(packet)
    return success_object(serialize("packet_items", item))


@bp.route("/credentialing/packet-items/<itemId>/verify", methods=["POST"])
def verify_item(itemId):
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    item = _item_or_404(itemId)
    if item["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_ITEM_STATE, "Only a SUBMITTED item can be verified", 409)
    packet = db.STORES["packets"].get(item["packet_id"])
    nurse_id = packet["nurse_id"] if packet else None
    nurse = db.STORES["nurses"].get(nurse_id) if nurse_id else None
    source_id = None
    item_type = item["item_type"]
    if item_type == "LICENSE_VERIFICATION":
        candidates = [lic for lic in all_entities("licenses")
                      if lic["nurse_id"] == nurse_id and lic["status"] == "ACTIVE"]
        if not candidates:
            raise ApiError(ERR_ITEM_EVIDENCE_INVALID, "No ACTIVE state license for the nurse", 422)
        source_id = candidates[0]["id"]
    elif item_type in ("BLS", "ACLS"):
        candidates = [c for c in all_entities("certifications")
                      if c["nurse_id"] == nurse_id and c["cert_type"] == item_type and c["status"] == "ACTIVE"]
        if not candidates:
            raise ApiError(ERR_ITEM_EVIDENCE_INVALID, f"No ACTIVE {item_type} certification for the nurse", 422)
        source_id = candidates[0]["id"]
    elif item_type == "COMPETENCY_ANNUAL":
        applicable = {r["id"] for r in all_entities("requirements")
                      if r["mandatory"] and nurse is not None and nurse["employment_type"] in r["applies_to"]}
        candidates = [cp for cp in all_entities("completions")
                      if cp["nurse_id"] == nurse_id and cp["requirement_id"] in applicable and cp["status"] == "CURRENT"]
        if not candidates:
            raise ApiError(ERR_ITEM_EVIDENCE_INVALID, "No CURRENT completion for a mandatory applicable requirement", 422)
        source_id = candidates[0]["id"]
    else:  # ATTESTATION requires only evidence_ref
        if not item["evidence_ref"]:
            raise ApiError(ERR_ITEM_EVIDENCE_INVALID, "Attestation requires evidence_ref", 422)
        source_id = None
    item["status"] = "VERIFIED"
    item["source_credential_id"] = source_id
    touch(item)
    if packet is not None:
        recompute_readiness(packet)
        touch(packet)
    return success_object(serialize("packet_items", item))


@bp.route("/credentialing/packet-items/<itemId>/waive", methods=["POST"])
def waive_item(itemId):
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    item = _item_or_404(itemId)
    body = validate_body(get_body(allow_empty=False), WAIVE_SCHEMA)
    if item["status"] not in ("MISSING", "SUBMITTED"):
        raise ApiError(ERR_INVALID_ITEM_STATE, "Only MISSING or SUBMITTED items can be waived", 409)
    if item["critical"]:
        raise ApiError(ERR_ITEM_NOT_WAIVABLE, "Critical items cannot be waived", 422)
    item["status"] = "WAIVED"
    touch(item)
    packet = db.STORES["packets"].get(item["packet_id"])
    if packet is not None:
        recompute_readiness(packet)
        touch(packet)
    return success_object(serialize("packet_items", item))
