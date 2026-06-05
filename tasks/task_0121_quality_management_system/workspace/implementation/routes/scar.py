"""SCAR routes: open, transition (PRD 3.5). Plus NCR-scoped reverse lists."""
from flask import Blueprint, request

from common import parse_iso, require_fields, require_string, stamp_create, touch
from db import db
from errors import (ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_RESOURCE_OWNER, err)
from middleware import (ROLE_QUALITY_ENGINEER, ROLE_QUALITY_MANAGER,
                        ROLE_SUPPLIER_USER, authenticate, require_role)
from response import list_success, success
from services.helpers import (get_or_404, paginate, paginate_args,
                              recompute_supplier_rating)
from services.serializers import capa_out, scar_out

bp = Blueprint("scar", __name__)

SCAR_ACTIONS = {"ACKNOWLEDGE", "RESPOND", "ACCEPT_RESPONSE",
                "REJECT_RESPONSE", "CANCEL"}


@bp.route("/scars", methods=["POST"])
def create_scar():
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER})
    body = request.get_json(silent=True) or {}

    # FK resolution (priority 4).
    ncr_id = body.get("ncr_id")
    supplier_id = body.get("supplier_id")
    if ncr_id is not None and ncr_id not in db.nonconformance_reports:
        raise err(ERR_FK_NOT_FOUND, "ncr_id does not resolve")
    if supplier_id is not None and supplier_id not in db.suppliers:
        raise err(ERR_FK_NOT_FOUND, "supplier_id does not resolve")

    # Well-formedness (priority 5).
    require_fields(body, ["ncr_id", "supplier_id", "due_at"])
    due_dt = parse_iso(body["due_at"])

    rec = {
        "ncr_id": ncr_id,
        "supplier_id": supplier_id,
        "due_at": body["due_at"],
        "due_at_dt": due_dt,
        "status": "OPEN",
        "response_narrative": None,
        "rejection_count": 0,
    }
    stamp_create(rec)
    db.scars[rec["id"]] = rec

    # Opening increments supplier open_scar_count + recompute rating (PRD 3.5).
    supplier = db.suppliers[supplier_id]
    supplier["open_scar_count"] += 1
    recompute_supplier_rating(supplier)

    return success(scar_out(rec), status=201)


@bp.route("/scars/<rid>", methods=["GET"])
def get_scar(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_SUPPLIER_USER})
    rec = get_or_404(db.scars, rid)
    # SupplierUser may read only its own SCAR (PRD 2.1 / 1.7).
    if auth.role == ROLE_SUPPLIER_USER and auth.user_id != rec["supplier_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "SCAR does not belong to this supplier")
    return success(scar_out(rec))


@bp.route("/scars/<rid>/transition", methods=["POST"])
def transition_scar(rid):
    auth = authenticate()
    require_role(auth, {ROLE_SUPPLIER_USER, ROLE_QUALITY_MANAGER})
    rec = get_or_404(db.scars, rid)
    body = request.get_json(silent=True) or {}

    require_fields(body, ["action"])
    action = body["action"]
    if action not in SCAR_ACTIONS:
        raise err(ERR_INVALID_REQUEST, "Invalid action")

    # Role-vs-action authority (per scaffold actors).
    supplier_actions = {"ACKNOWLEDGE", "RESPOND"}
    manager_actions = {"ACCEPT_RESPONSE", "REJECT_RESPONSE", "CANCEL"}
    if action in supplier_actions and auth.role != ROLE_SUPPLIER_USER:
        from errors import ERR_FORBIDDEN_ROLE
        raise err(ERR_FORBIDDEN_ROLE, "Only the supplier may perform this action")
    if action in manager_actions and auth.role != ROLE_QUALITY_MANAGER:
        from errors import ERR_FORBIDDEN_ROLE
        raise err(ERR_FORBIDDEN_ROLE, "Only a QualityManager may perform this action")

    if action == "ACKNOWLEDGE":
        if rec["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "ACKNOWLEDGE requires OPEN")
        if auth.user_id != rec["supplier_id"]:
            raise err(ERR_NOT_RESOURCE_OWNER, "Not the owning supplier")
        rec["status"] = "ACK"
        touch(rec)
        return success(scar_out(rec))

    if action == "RESPOND":
        if rec["status"] not in {"ACK", "REJECTED_RESPONSE"}:
            raise err(ERR_INVALID_STATE, "RESPOND requires ACK or REJECTED_RESPONSE")
        if auth.user_id != rec["supplier_id"]:
            raise err(ERR_NOT_RESOURCE_OWNER, "Not the owning supplier")
        narrative = body.get("response_narrative")
        if not isinstance(narrative, str) or narrative == "":
            raise err(ERR_INVALID_REQUEST, "response_narrative required")
        rec["response_narrative"] = narrative
        rec["status"] = "RESPONDED"
        touch(rec)
        return success(scar_out(rec))

    if action == "ACCEPT_RESPONSE":
        if rec["status"] != "RESPONDED":
            raise err(ERR_INVALID_STATE, "ACCEPT_RESPONSE requires RESPONDED")
        rec["status"] = "ACCEPTED_RESPONSE"
        touch(rec)
        return success(scar_out(rec))

    if action == "REJECT_RESPONSE":
        if rec["status"] != "RESPONDED":
            raise err(ERR_INVALID_STATE, "REJECT_RESPONSE requires RESPONDED")
        rec["rejection_count"] += 1
        rec["status"] = "REJECTED_RESPONSE"
        touch(rec)
        return success(scar_out(rec))

    if action == "CANCEL":
        if rec["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "CANCEL requires OPEN")
        rec["status"] = "CANCELLED"
        touch(rec)
        supplier = db.suppliers.get(rec["supplier_id"])
        if supplier is not None:
            supplier["open_scar_count"] -= 1
            recompute_supplier_rating(supplier)
        return success(scar_out(rec))

    raise err(ERR_INVALID_STATE, "Unsupported action")


# ---- NCR-scoped reverse lookups (PRD 2.6) ----
@bp.route("/nonconformance-reports/<rid>/capas", methods=["GET"])
def list_ncr_capas(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_QUALITY_ENGINEER})
    get_or_404(db.nonconformance_reports, rid)
    limit, offset = paginate_args()
    matches = [c for c in db.capas.values() if c["ncr_id"] == rid]
    page, total = paginate(matches, limit, offset)
    return list_success([capa_out(c) for c in page], limit, offset, total)


@bp.route("/nonconformance-reports/<rid>/scars", methods=["GET"])
def list_ncr_scars(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_QUALITY_ENGINEER})
    get_or_404(db.nonconformance_reports, rid)
    limit, offset = paginate_args()
    matches = [s for s in db.scars.values() if s["ncr_id"] == rid]
    page, total = paginate(matches, limit, offset)
    return list_success([scar_out(s) for s in page], limit, offset, total)
