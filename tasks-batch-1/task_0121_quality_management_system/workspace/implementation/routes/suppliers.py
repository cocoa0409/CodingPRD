"""Supplier routes and supplier-scoped reverse-lookup lists (PRD 3.1, 2.6)."""
from decimal import Decimal

from flask import Blueprint, request

from common import require_fields, require_string, stamp_create
from db import db
from middleware import (ROLE_INSPECTOR, ROLE_QUALITY_ENGINEER,
                        ROLE_QUALITY_MANAGER, ROLE_SUPPLIER_USER,
                        authenticate, require_role)
from response import list_success, success
from services.helpers import get_or_404, paginate, paginate_args
from services.serializers import (deviation_out, inspection_lot_out, scar_out,
                                  supplier_out)

bp = Blueprint("suppliers", __name__)

OPEN_SCAR_STATUSES = {"OPEN", "ACK", "RESPONDED", "REJECTED_RESPONSE"}


@bp.route("/suppliers", methods=["POST"])
def create_supplier():
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER})
    body = request.get_json(silent=True) or {}
    require_fields(body, ["name", "code"])
    require_string(body["name"], "name")
    require_string(body["code"], "code")

    rec = {
        "name": body["name"],
        "code": body["code"],
        # Pristine quality posture (PRD 3.1).
        "quality_rating": Decimal("100.00"),
        "approval_status": "APPROVED",
        "open_scar_count": 0,
        "lots_inspected": 0,
        "lots_rejected": 0,
        "ncrs_attributed": 0,
    }
    stamp_create(rec)
    db.suppliers[rec["id"]] = rec
    return success(supplier_out(rec), status=201)


@bp.route("/suppliers/<rid>", methods=["GET"])
def get_supplier(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_QUALITY_ENGINEER,
                        ROLE_INSPECTOR, ROLE_SUPPLIER_USER})
    rec = get_or_404(db.suppliers, rid)
    return success(supplier_out(rec))


@bp.route("/suppliers/<rid>/scars", methods=["GET"])
def list_supplier_scars(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_SUPPLIER_USER})
    get_or_404(db.suppliers, rid)
    limit, offset = paginate_args()
    matches = [s for s in db.scars.values() if s["supplier_id"] == rid]
    page, total = paginate(matches, limit, offset)
    return list_success([scar_out(s) for s in page], limit, offset, total)


@bp.route("/suppliers/<rid>/inspection-lots", methods=["GET"])
def list_supplier_lots(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_INSPECTOR})
    get_or_404(db.suppliers, rid)
    limit, offset = paginate_args()
    matches = [l for l in db.inspection_lots.values() if l["supplier_id"] == rid]
    page, total = paginate(matches, limit, offset)
    return list_success([inspection_lot_out(l) for l in page], limit, offset, total)


@bp.route("/suppliers/<rid>/deviations", methods=["GET"])
def list_supplier_deviations(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_QUALITY_ENGINEER})
    get_or_404(db.suppliers, rid)
    limit, offset = paginate_args()
    matches = [d for d in db.deviations.values() if d["supplier_id"] == rid]
    page, total = paginate(matches, limit, offset)
    return list_success([deviation_out(d) for d in page], limit, offset, total)
