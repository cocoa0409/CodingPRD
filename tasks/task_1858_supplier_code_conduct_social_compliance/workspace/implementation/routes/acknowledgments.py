"""CodeAcknowledgment endpoints (OCC on Supplier.version)."""
from flask import Blueprint, request
import db
from middleware import require_roles, ALL_BUSINESS_ROLES, get_pagination
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_VIOLATION,
    ERR_STALE_VERSION,
    ERR_CODE_VERSION_NOT_PUBLISHED,
)
from services.utils import new_uuid

bp = Blueprint("acknowledgments", __name__)


def serialize(a):
    return {
        "id": a["id"],
        "supplier_id": a["supplier_id"],
        "code_version_id": a["code_version_id"],
        "signer_name": a["signer_name"],
        "signer_title": a["signer_title"],
        "acknowledged_at": a["acknowledged_at"],
        "supersedes_acknowledgment_id": a["supersedes_acknowledgment_id"],
        "created_at": a["created_at"],
    }


def _latest_ack(supplier_id):
    acks = [a for a in db.acknowledgments.values() if a["supplier_id"] == supplier_id]
    if not acks:
        return None
    def key(a):
        return (a["acknowledged_at"], a["created_at"])
    return max(acks, key=key)


@bp.route("/code-acknowledgments", methods=["POST"])
def create_acknowledgment():
    user_id, _ = require_roles("SupplierContact")
    body = request.get_json(silent=True) or {}
    supplier_id = body.get("supplier_id")
    code_version_id = body.get("code_version_id")
    signer_name = body.get("signer_name")
    signer_title = body.get("signer_title")
    expected_supplier_version = body.get("expected_supplier_version")
    if not isinstance(supplier_id, str) or not supplier_id:
        raise_err(ERR_INVALID_REQUEST, "supplier_id is required")
    if not isinstance(code_version_id, str) or not code_version_id:
        raise_err(ERR_INVALID_REQUEST, "code_version_id is required")
    if not isinstance(signer_name, str) or not signer_name:
        raise_err(ERR_INVALID_REQUEST, "signer_name is required")
    if not isinstance(signer_title, str) or not signer_title:
        raise_err(ERR_INVALID_REQUEST, "signer_title is required")
    if not isinstance(expected_supplier_version, int):
        raise_err(ERR_INVALID_REQUEST, "expected_supplier_version is required and must be integer")
    # Existence (left-to-right: supplier then code_version)
    supplier = db.suppliers.get(supplier_id)
    if not supplier:
        raise_err(ERR_NOT_FOUND, "supplier not found")
    cv = db.code_versions.get(code_version_id)
    if not cv:
        raise_err(ERR_NOT_FOUND, "code version not found")
    # Ownership: X-User-ID == supplier_id
    if user_id != supplier_id:
        raise_err(ERR_OWNERSHIP_VIOLATION,
                  "SupplierContact may only acknowledge on behalf of its own supplier")
    # OCC
    if expected_supplier_version != supplier["version"]:
        raise_err(ERR_STALE_VERSION,
                  f"expected_supplier_version {expected_supplier_version} does not match current version {supplier['version']}")
    # State: code version must be PUBLISHED
    if cv["status"] != "PUBLISHED":
        raise_err(ERR_CODE_VERSION_NOT_PUBLISHED,
                  f"code version status is {cv['status']}")
    # Build ack
    prior = _latest_ack(supplier_id)
    ack = {
        "id": new_uuid(),
        "supplier_id": supplier_id,
        "code_version_id": code_version_id,
        "signer_name": signer_name,
        "signer_title": signer_title,
        "acknowledged_at": db.get_clock(),
        "supersedes_acknowledgment_id": prior["id"] if prior else None,
        "created_at": db.get_clock(),
    }
    db.acknowledgments[ack["id"]] = ack
    # Side effects on supplier
    supplier["current_code_version_id"] = code_version_id
    if supplier["status"] == "ONBOARDING":
        supplier["status"] = "ACTIVE"
    supplier["version"] += 1
    supplier["updated_at"] = db.get_clock()
    return success_object(serialize(ack), 201)


@bp.route("/code-acknowledgments", methods=["GET"])
def list_acknowledgments():
    require_roles(*ALL_BUSINESS_ROLES)
    limit, offset = get_pagination()
    sid = request.args.get("supplier_id")
    cvid = request.args.get("code_version_id")
    supersedes = request.args.get("supersedes_acknowledgment_id")
    items = list(db.acknowledgments.values())
    if sid is not None:
        items = [a for a in items if a["supplier_id"] == sid]
    if cvid is not None:
        items = [a for a in items if a["code_version_id"] == cvid]
    if supersedes is not None:
        if supersedes == "" or supersedes.lower() == "null":
            items = [a for a in items if a["supersedes_acknowledgment_id"] is None]
        else:
            items = [a for a in items if a["supersedes_acknowledgment_id"] == supersedes]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_array([serialize(a) for a in page], total, limit, offset)


@bp.route("/code-acknowledgments/<aid>", methods=["GET"])
def get_acknowledgment(aid):
    require_roles(*ALL_BUSINESS_ROLES)
    a = db.acknowledgments.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, "acknowledgment not found")
    return success_object(serialize(a))
