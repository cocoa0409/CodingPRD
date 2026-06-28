"""Warranty endpoints: get, list, file claim, list claims
(SCAFFOLD §1.5 / PRD §3.7)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_role
from response import success
from services import serialize
from services.calc import coverage_expiry, whole_months_floor
from services.common import (get_body, new_row, parse_pagination, paginate,
                             require_enum, touch)

bp = Blueprint("warranties", __name__)

READ_ROLES = {"PlatformAdmin", "WarrantyAgent", "Customer"}


@bp.route("/warranties/<id>", methods=["GET"])
def get_warranty(id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    row = db.warranties.get(id)
    if row is None:
        raise err("ERR_NOT_FOUND", "Warranty not found")
    return success(serialize.warranty(row), 200)


@bp.route("/projects/<id>/warranties", methods=["GET"])
def list_project_warranties(id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    if db.projects.get(id) is None:
        raise err("ERR_NOT_FOUND", "Project not found")
    limit, offset = parse_pagination()
    rows = [w for w in db.warranties.values() if w["project_id"] == id]
    page, meta = paginate(rows, limit, offset)
    return success([serialize.warranty(r) for r in page], 200, pagination=meta)


@bp.route("/warranties/<id>/claims", methods=["POST"])
def file_claim(id):
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    warranty = db.warranties.get(id)
    if warranty is None:
        raise err("ERR_NOT_FOUND", "Warranty not found")
    project = db.projects.get(warranty["project_id"])

    # priority 3: ownership via owning project's customer_id
    if project["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customer does not own this warranty")

    body = get_body()
    defect_type = require_enum(body, "defect_type", {"HOT_TIRE", "PEEL", "OTHER"})

    # state guard: warranty must be ACTIVE
    if warranty["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Warranty is not ACTIVE")

    # priority 17: coverage window — now < coverage_start_at + term_months
    now = db.now()
    expiry = coverage_expiry(warranty["coverage_start_at"], warranty["term_months"])
    if now >= expiry:
        raise err("ERR_COVERAGE_EXPIRED", "Warranty coverage window has lapsed")

    months_elapsed = whole_months_floor(warranty["coverage_start_at"], now)

    claim = new_row({
        "warranty_id": id,
        "defect_type": defect_type,
        "reported_at": now,
        "months_elapsed": months_elapsed,
        "prorated_credit_cents": 0,
        "revision_rounds": 0,
        "status": "SUBMITTED",
    })
    db.warranty_claims[claim["id"]] = claim

    warranty["status"] = "CLAIM_OPEN"
    touch(warranty)

    return success(serialize.warranty_claim(claim), 201)


@bp.route("/warranties/<id>/claims", methods=["GET"])
def list_claims(id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    if db.warranties.get(id) is None:
        raise err("ERR_NOT_FOUND", "Warranty not found")
    limit, offset = parse_pagination()
    rows = [c for c in db.warranty_claims.values() if c["warranty_id"] == id]
    page, meta = paginate(rows, limit, offset)
    return success([serialize.warranty_claim(r) for r in page], 200, pagination=meta)
