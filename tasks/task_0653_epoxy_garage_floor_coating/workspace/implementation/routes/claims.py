"""Warranty claim endpoints: get, review, resubmit, schedule-callback, close
(SCAFFOLD §1.5 / PRD §3.7)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_role
from response import success
from services import serialize
from services.calc import warranty_proration
from services.common import get_body, require_enum, touch

bp = Blueprint("claims", __name__)

NON_TERMINAL_CLAIM = ("SUBMITTED", "NEEDS_INFO", "APPROVED", "CALLBACK_SCHEDULED")


def _rearm_warranty(warranty, exclude_claim_id):
    """Bubble Warranty CLAIM_OPEN -> ACTIVE when no other non-terminal claim
    remains on the warranty."""
    others = [c for c in db.warranty_claims.values()
              if c["warranty_id"] == warranty["id"]
              and c["id"] != exclude_claim_id
              and c["status"] in NON_TERMINAL_CLAIM]
    if not others and warranty["status"] == "CLAIM_OPEN":
        warranty["status"] = "ACTIVE"
        touch(warranty)


@bp.route("/claims/<id>", methods=["GET"])
def get_claim(id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "WarrantyAgent", "Customer"})
    row = db.warranty_claims.get(id)
    if row is None:
        raise err("ERR_NOT_FOUND", "Claim not found")
    return success(serialize.warranty_claim(row), 200)


@bp.route("/claims/<id>/review", methods=["POST"])
def review_claim(id):
    _, role = authenticate()
    require_role(role, {"WarrantyAgent"})
    claim = db.warranty_claims.get(id)
    if claim is None:
        raise err("ERR_NOT_FOUND", "Claim not found")

    body = get_body()
    action = require_enum(body, "action", {"REQUEST_INFO", "APPROVE", "REJECT"})

    # state guard: review acts only on SUBMITTED claims
    if claim["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Claim is not SUBMITTED")

    if action == "REQUEST_INFO":
        claim["status"] = "NEEDS_INFO"
        touch(claim)

    elif action == "APPROVE":
        # priority 18: only HOT_TIRE / PEEL payable
        if claim["defect_type"] not in ("HOT_TIRE", "PEEL"):
            raise err("ERR_DEFECT_NOT_COVERED", "OTHER defects cannot be approved")
        warranty = db.warranties.get(claim["warranty_id"])
        claim["prorated_credit_cents"] = warranty_proration(
            warranty["covered_install_price_cents"],
            claim["months_elapsed"],
            warranty["term_months"],
            claim["defect_type"],
        )
        claim["status"] = "APPROVED"
        touch(claim)

    elif action == "REJECT":
        claim["status"] = "REJECTED"
        touch(claim)
        warranty = db.warranties.get(claim["warranty_id"])
        _rearm_warranty(warranty, claim["id"])

    return success(serialize.warranty_claim(claim), 200)


@bp.route("/claims/<id>/resubmit", methods=["POST"])
def resubmit_claim(id):
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    claim = db.warranty_claims.get(id)
    if claim is None:
        raise err("ERR_NOT_FOUND", "Claim not found")

    # priority 3: ownership via owning project's customer_id
    warranty = db.warranties.get(claim["warranty_id"])
    project = db.projects.get(warranty["project_id"])
    if project["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customer does not own this claim")

    # state guard
    if claim["status"] != "NEEDS_INFO":
        raise err("ERR_INVALID_STATE", "Claim is not NEEDS_INFO")

    claim["status"] = "SUBMITTED"
    claim["revision_rounds"] += 1
    touch(claim)
    return success(serialize.warranty_claim(claim), 200)


@bp.route("/claims/<id>/schedule-callback", methods=["POST"])
def schedule_callback(id):
    _, role = authenticate()
    require_role(role, {"WarrantyAgent"})
    claim = db.warranty_claims.get(id)
    if claim is None:
        raise err("ERR_NOT_FOUND", "Claim not found")

    if claim["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Claim is not APPROVED")

    claim["status"] = "CALLBACK_SCHEDULED"
    touch(claim)
    return success(serialize.warranty_claim(claim), 200)


@bp.route("/claims/<id>/close", methods=["POST"])
def close_claim(id):
    _, role = authenticate()
    require_role(role, {"WarrantyAgent"})
    claim = db.warranty_claims.get(id)
    if claim is None:
        raise err("ERR_NOT_FOUND", "Claim not found")

    if claim["status"] != "CALLBACK_SCHEDULED":
        raise err("ERR_INVALID_STATE", "Claim is not CALLBACK_SCHEDULED")

    claim["status"] = "CLOSED"
    touch(claim)
    warranty = db.warranties.get(claim["warranty_id"])
    _rearm_warranty(warranty, claim["id"])
    return success(serialize.warranty_claim(claim), 200)
