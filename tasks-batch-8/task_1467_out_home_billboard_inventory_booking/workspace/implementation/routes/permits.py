"""Permit endpoints (PRD 3.2)."""
from flask import Blueprint, request

import db
import domain
from errors import ApiError, err_invalid_request, err_invalid_state
from middleware import require_roles
from response import success, paginate, sort_created
from serializers import permit_out
from util import clock_now, req_str, parse_dt

bp = Blueprint("permits", __name__, url_prefix="/api")


def get_permit_or_404(permit_id):
    p = db.permits.get(permit_id)
    if p is None:
        raise ApiError("ERR_PERMIT_NOT_FOUND", 404, "Permit not found")
    return p


@bp.route("/permits", methods=["POST"])
def create_permit():
    require_roles("ComplianceOfficer")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    # Family 3: body FK existence for present ids
    face_id = body.get("face_id")
    if isinstance(face_id, str) and face_id not in db.faces:
        raise ApiError("ERR_FACE_NOT_FOUND", 404, "Face not found")
    supersedes_id = body.get("supersedes_permit_id")
    if isinstance(supersedes_id, str) and supersedes_id not in db.permits:
        raise ApiError("ERR_PERMIT_NOT_FOUND", 404, "Permit not found")

    # Family 4: shape
    face_id = req_str(body, "face_id")
    permit_number = req_str(body, "permit_number")
    jurisdiction = req_str(body, "jurisdiction")
    issued_on = parse_dt(body.get("issued_on"), "issued_on")
    expires_on = parse_dt(body.get("expires_on"), "expires_on")
    if not expires_on > issued_on:
        raise err_invalid_request("expires_on must be strictly after issued_on")
    if supersedes_id is not None and not isinstance(supersedes_id, str):
        raise err_invalid_request("supersedes_permit_id must be a string")

    face = db.faces[face_id]
    supersedes = db.permits.get(supersedes_id) if supersedes_id else None

    # Family 12: supersession shape
    if supersedes is not None:
        if supersedes["status"] not in ("ACTIVE", "RENEWAL_PENDING"):
            raise err_invalid_state(
                "A superseded permit must be ACTIVE or RENEWAL_PENDING")
    else:
        if face["current_permit_id"] is not None:
            raise err_invalid_state(
                "Face already has a current permit; file with "
                "supersedes_permit_id instead")

    # Family 9: clock-relative temporal rule
    if not expires_on > clock_now():
        raise err_invalid_request(
            "expires_on must be strictly later than the current clock reading")

    permit = db.new_resource()
    permit.update({
        "face_id": face["id"],
        "supersedes_permit_id": supersedes_id,
        "permit_number": permit_number,
        "jurisdiction": jurisdiction,
        "issued_on": issued_on,
        "expires_on": expires_on,
        "status": "ACTIVE",
    })
    db.permits[permit["id"]] = permit

    if supersedes is not None:
        supersedes["status"] = "SUPERSEDED"
        db.touch(supersedes)

    domain.restore_face_for_permit(face, permit)
    return success(permit_out(permit), code=201)


@bp.route("/permits/<permit_id>", methods=["GET"])
def get_permit(permit_id):
    require_roles("ComplianceOfficer", "InventoryManager")
    p = get_permit_or_404(permit_id)
    return success(permit_out(p))


@bp.route("/permits/<permit_id>", methods=["PUT"])
def update_permit(permit_id):
    require_roles("ComplianceOfficer")
    p = get_permit_or_404(permit_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    new_status = body.get("status")
    if not isinstance(new_status, str) or new_status not in (
            "ACTIVE", "RENEWAL_PENDING", "EXPIRED", "SUPERSEDED", "REVOKED"):
        raise err_invalid_request("status is required and must be a valid "
                                  "permit status")
    new_expires = None
    if "expires_on" in body and body["expires_on"] is not None:
        new_expires = parse_dt(body["expires_on"], "expires_on")

    face = db.faces.get(p["face_id"])

    if new_status == "ACTIVE":
        if p["status"] != "EXPIRED":
            raise err_invalid_state(
                "Only an EXPIRED permit may be reinstated to ACTIVE")
        if new_expires is None:
            raise err_invalid_request(
                "Reinstatement requires a new expires_on")
        if not new_expires > clock_now():
            raise err_invalid_request(
                "expires_on must be strictly later than the current clock "
                "reading")
        p["expires_on"] = new_expires
        p["status"] = "ACTIVE"
        db.touch(p)
        if face is not None:
            domain.restore_face_for_permit(face, p)
    elif new_status == "REVOKED":
        if p["status"] not in ("ACTIVE", "RENEWAL_PENDING", "EXPIRED"):
            raise err_invalid_state(
                "Permit cannot transition %s -> REVOKED" % p["status"])
        was_current = p["status"] in ("ACTIVE", "RENEWAL_PENDING")
        p["status"] = "REVOKED"
        db.touch(p)
        if was_current and face is not None \
                and face["current_permit_id"] == p["id"]:
            domain.suspend_face_for_permit(face)
        # Revoking an already-EXPIRED permit leaves the face as it stands.
    else:
        raise err_invalid_state(
            "Permit cannot transition %s -> %s" % (p["status"], new_status))

    return success(permit_out(p))


@bp.route("/permits/<permit_id>/successors", methods=["GET"])
def permit_successors(permit_id):
    require_roles("ComplianceOfficer", "InventoryManager")
    p = get_permit_or_404(permit_id)
    items = sort_created([q for q in db.permits.values()
                          if q["supersedes_permit_id"] == p["id"]])
    page, meta = paginate(items)
    return success([permit_out(q) for q in page], response_type="array",
                   page_meta=meta)
