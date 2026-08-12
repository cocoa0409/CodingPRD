"""AuthorityNotification endpoints."""
from flask import Blueprint, request

import db
from errors import invalid_request, invalid_state, not_found, raise_err
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.serializers import serialize, serialize_many
from utils import new_entity, paginate, pagination_args, sort_created, touch

bp = Blueprint("authority_notifications", __name__)


def _get_or_404(nid):
    ent = domain.get("authority_notifications", nid)
    if ent is None:
        not_found("authority notification")
    return ent


@bp.post("/authority-notifications")
def create_notification():
    require_roles(["AgencyOps"])
    body = request.get_json(silent=True) or {}
    call = None
    pcid = body.get("port_call_id")
    if isinstance(pcid, str):
        call = domain.get("port_calls", pcid)
        if call is None:
            not_found("port call")
    atype = body.get("authority_type")
    if call is not None and isinstance(atype, str):
        # per-call uniqueness among non-WITHDRAWN notifications
        for n in domain.all_of("authority_notifications"):
            if (n["port_call_id"] == pcid and n["authority_type"] == atype
                    and n["status"] != "WITHDRAWN"):
                raise_err("ERR_DUPLICATE_NOTIFICATION_TYPE",
                          "A notification of this authority_type already exists for the call")
    if call is not None:
        domain.require_call_editable(call)
    if (call is None
            or atype not in domain.AUTHORITY_TYPES
            or not isinstance(body.get("payload_summary"), str)):
        invalid_request("port_call_id, a valid authority_type and payload_summary are required")
    ent = new_entity("authority_notifications", {
        "port_call_id": pcid,
        "authority_type": atype,
        "payload_summary": body["payload_summary"],
        "status": "DRAFT",
        "authority_reference": None,
        "rejection_reason": None,
        "revision_count": 0,
        "submitted_at": None,
    })
    return ok_object(serialize(ent), status=201)


@bp.get("/authority-notifications")
def list_notifications():
    require_roles(ANY_ROLE)
    items = list(domain.all_of("authority_notifications"))
    for param in ("port_call_id", "status", "authority_type"):
        value = request.args.get(param)
        if value is not None:
            items = [n for n in items if n[param] == value]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/authority-notifications/<nid>")
def get_notification(nid):
    require_roles(ANY_ROLE)
    return ok_object(serialize(_get_or_404(nid)))


def _submittable_phase(ent):
    call = domain.get("port_calls", ent["port_call_id"])
    if call is not None and call["ops_status"] not in ("NOMINATED", "PRE_ARRIVAL_FILED"):
        raise_err("ERR_PORT_CALL_NOT_EDITABLE",
                  "The port call is past the filing phase")


@bp.post("/authority-notifications/<nid>/submit")
def submit_notification(nid):
    require_roles(["AgencyOps"])
    ent = _get_or_404(nid)
    if ent["status"] != "DRAFT":
        invalid_state("Only a DRAFT notification can be submitted")
    _submittable_phase(ent)
    ent["status"] = "SUBMITTED"
    ent["submitted_at"] = db.now()
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/authority-notifications/<nid>/acknowledge")
def acknowledge_notification(nid):
    require_roles(["PortAuthority"])
    ent = _get_or_404(nid)
    if ent["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED notification can be acknowledged")
    body = request.get_json(silent=True) or {}
    ref = body.get("authority_reference")
    if not isinstance(ref, str) or not ref:
        invalid_request("authority_reference is required")
    ent["status"] = "ACKNOWLEDGED"
    ent["authority_reference"] = ref
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/authority-notifications/<nid>/reject")
def reject_notification(nid):
    require_roles(["PortAuthority"])
    ent = _get_or_404(nid)
    if ent["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED notification can be rejected")
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason:
        invalid_request("reason is required")
    ent["status"] = "REJECTED"
    ent["rejection_reason"] = reason
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/authority-notifications/<nid>/resubmit")
def resubmit_notification(nid):
    require_roles(["AgencyOps"])
    ent = _get_or_404(nid)
    if ent["status"] != "REJECTED":
        invalid_state("Only a REJECTED notification can be resubmitted")
    _submittable_phase(ent)
    ent["status"] = "SUBMITTED"
    ent["revision_count"] += 1
    ent["submitted_at"] = db.now()
    touch(ent)
    return ok_object(serialize(ent))
