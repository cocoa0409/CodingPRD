"""CrewChange endpoints with visa/shore-pass branch rules and lazy expiry."""
from flask import Blueprint, request

import db
from errors import invalid_request, invalid_state, not_found, raise_err
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.serializers import serialize, serialize_many
from utils import new_entity, paginate, pagination_args, parse_dt, sort_created, touch

bp = Blueprint("crew_changes", __name__)

DIRECTIONS = {"ON_SIGNER", "OFF_SIGNER"}


def _get_or_404(cid):
    ent = domain.get("crew_changes", cid)
    if ent is None:
        not_found("crew change")
    domain.lazy_expire_crew(ent)
    return ent


@bp.post("/crew-changes")
def create_crew_change():
    require_roles(["CrewingAgent"])
    body = request.get_json(silent=True) or {}
    call = None
    pcid = body.get("port_call_id")
    if isinstance(pcid, str):
        call = domain.get("port_calls", pcid)
        if call is None:
            not_found("port call")
    if call is not None:
        domain.require_call_editable(call)
    expiry = parse_dt(body.get("passport_expiry"))
    if (call is None
            or not isinstance(body.get("full_name"), str) or not body.get("full_name")
            or not isinstance(body.get("nationality"), str) or not body.get("nationality")
            or not isinstance(body.get("passport_no"), str) or not body.get("passport_no")
            or expiry is None
            or body.get("direction") not in DIRECTIONS
            or not isinstance(body.get("requires_visa"), bool)):
        invalid_request("invalid crew change payload")
    ent = new_entity("crew_changes", {
        "port_call_id": pcid,
        "full_name": body["full_name"],
        "nationality": body["nationality"],
        "passport_no": body["passport_no"],
        "passport_expiry": expiry,
        "direction": body["direction"],
        "requires_visa": body["requires_visa"],
        "status": "REQUESTED",
        "visa_reference": None,
        "shore_pass_expires_at": None,
    })
    return ok_object(serialize(ent), status=201)


@bp.get("/crew-changes")
def list_crew_changes():
    require_roles(ANY_ROLE)
    domain.lazy_expire_all_crew()
    items = list(domain.all_of("crew_changes"))
    for param in ("port_call_id", "status", "direction"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/crew-changes/<cid>")
def get_crew_change(cid):
    require_roles(ANY_ROLE)
    return ok_object(serialize(_get_or_404(cid)))


@bp.post("/crew-changes/<cid>/verify-docs")
def verify_docs(cid):
    require_roles(["CrewingAgent"])
    ent = _get_or_404(cid)
    if ent["status"] != "REQUESTED":
        invalid_state("Only a REQUESTED crew change can be document-verified")
    call = domain.get("port_calls", ent["port_call_id"])
    if call is not None and not ent["passport_expiry"] > call["etd"]:
        raise_err("ERR_PASSPORT_EXPIRY_INVALID",
                  "passport_expiry must be strictly after the port call etd")
    if call is not None:
        domain.require_call_editable(call)
    ent["status"] = "DOCS_VERIFIED"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/crew-changes/<cid>/request-visa")
def request_visa(cid):
    require_roles(["CrewingAgent"])
    ent = _get_or_404(cid)
    if ent["status"] != "DOCS_VERIFIED":
        invalid_state("Only a DOCS_VERIFIED crew change can request a visa")
    if not ent["requires_visa"]:
        raise_err("ERR_VISA_NOT_REQUIRED", "This crew change does not require a visa")
    ent["status"] = "VISA_PENDING"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/crew-changes/<cid>/grant-visa")
def grant_visa(cid):
    require_roles(["PortAuthority"])
    ent = _get_or_404(cid)
    if ent["status"] != "VISA_PENDING":
        invalid_state("Only a VISA_PENDING crew change can be granted a visa")
    body = request.get_json(silent=True) or {}
    ref = body.get("visa_reference")
    if not isinstance(ref, str) or not ref:
        invalid_request("visa_reference is required")
    ent["status"] = "VISA_GRANTED"
    ent["visa_reference"] = ref
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/crew-changes/<cid>/issue-shore-pass")
def issue_shore_pass(cid):
    require_roles(["CrewingAgent"])
    ent = _get_or_404(cid)
    if ent["status"] not in ("DOCS_VERIFIED", "VISA_GRANTED", "PASS_EXPIRED"):
        invalid_state("A shore pass cannot be issued from the current state")
    body = request.get_json(silent=True) or {}
    expires = parse_dt(body.get("shore_pass_expires_at"))
    if expires is not None and not expires > db.now():
        raise_err("ERR_SHORE_PASS_EXPIRED", "shore_pass_expires_at must lie in the future")
    if ent["status"] == "DOCS_VERIFIED" and ent["requires_visa"]:
        raise_err("ERR_VISA_REQUIRED", "A visa is required before a shore pass can be issued")
    if expires is None:
        invalid_request("shore_pass_expires_at is required")
    ent["status"] = "SHORE_PASS_ISSUED"
    ent["shore_pass_expires_at"] = expires
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/crew-changes/<cid>/complete")
def complete_crew_change(cid):
    require_roles(["CrewingAgent"])
    ent = _get_or_404(cid)
    if ent["status"] != "SHORE_PASS_ISSUED":
        invalid_state("Only a crew change with a valid issued shore pass can be completed")
    ent["status"] = "COMPLETED"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/crew-changes/<cid>/cancel")
def cancel_crew_change(cid):
    require_roles(["CrewingAgent"])
    ent = _get_or_404(cid)
    if ent["status"] not in ("REQUESTED", "DOCS_VERIFIED", "VISA_PENDING"):
        invalid_state("The crew change cannot be cancelled from its current state")
    ent["status"] = "CANCELLED"
    touch(ent)
    return ok_object(serialize(ent))
