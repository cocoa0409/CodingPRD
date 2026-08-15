"""Member, Provider, Submitter routes."""
from flask import Blueprint, request

from db import store, new_id, now_iso
from middleware import (
    get_auth, require_role, get_body, req_string, opt_string, apply_pagination,
)
from response import success_object, success_list
from errors import not_found, invalid_request, invalid_state
from services.core import parse_date, touch

bp = Blueprint("roster", __name__)

AID_CATEGORIES = {"TANF", "SSI", "DUAL", "EXPANSION", "CHIP"}


# ----------------------------------------------------------------- members ---

def member_view(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "program_id": m["program_id"],
        "medicaid_id": m["medicaid_id"],
        "aid_category": m["aid_category"],
        "enrolled_from": m["enrolled_from"],
        "enrolled_to": m["enrolled_to"],
        "status": m["status"],
    }


@bp.route("/programs/members", methods=["POST"])
def create_member():
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    body = get_body()
    program_id = req_string(body, "program_id")
    medicaid_id = req_string(body, "medicaid_id")
    aid_category = req_string(body, "aid_category")
    if aid_category not in AID_CATEGORIES:
        raise invalid_request("aid_category must be one of TANF, SSI, DUAL, EXPANSION, CHIP")
    enrolled_from_s = req_string(body, "enrolled_from")
    enrolled_to_s = opt_string(body, "enrolled_to", None)
    enrolled_from = parse_date(enrolled_from_s, "enrolled_from")
    enrolled_to = parse_date(enrolled_to_s, "enrolled_to") if enrolled_to_s else None
    # existence
    if program_id not in store.programs:
        raise not_found("program not found")
    # uniqueness of medicaid_id within program
    for m in store.members.values():
        if m["program_id"] == program_id and m["medicaid_id"] == medicaid_id:
            raise invalid_request("medicaid_id must be unique within the program")
    mid = new_id()
    m = {
        "id": mid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "program_id": program_id,
        "medicaid_id": medicaid_id,
        "aid_category": aid_category,
        "enrolled_from": enrolled_from_s,
        "enrolled_to": enrolled_to_s,
        "status": "ACTIVE",
        "_enrolled_from": enrolled_from,
        "_enrolled_to": enrolled_to,
    }
    store.members[mid] = m
    return success_object(member_view(m), 201)


@bp.route("/programs/members/<mid>", methods=["GET"])
def get_member(mid):
    get_auth()
    m = store.members.get(mid)
    if m is None:
        raise not_found()
    return success_object(member_view(m))


@bp.route("/programs/members", methods=["GET"])
def list_members():
    get_auth()
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    aid_category = request.args.get("aid_category")
    items = list(store.members.values())
    if program_id is not None:
        items = [m for m in items if m["program_id"] == program_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if aid_category is not None:
        items = [m for m in items if m["aid_category"] == aid_category]
    page, limit, offset, total = apply_pagination(items)
    return success_list([member_view(m) for m in page], limit, offset, total)


@bp.route("/programs/members/<mid>/disenroll", methods=["POST"])
def disenroll_member(mid):
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    body = get_body()
    disenrolled_date_s = req_string(body, "disenrolled_date")
    disenrolled_date = parse_date(disenrolled_date_s, "disenrolled_date")
    m = store.members.get(mid)
    if m is None:
        raise not_found()
    if m["status"] != "ACTIVE":
        raise invalid_state("Member is not ACTIVE")
    m["status"] = "DISENROLLED"
    m["enrolled_to"] = disenrolled_date_s
    m["_enrolled_to"] = disenrolled_date
    touch(m)
    return success_object(member_view(m))


# --------------------------------------------------------------- providers ---

def provider_view(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "program_id": p["program_id"],
        "npi": p["npi"],
        "taxonomy_code": p["taxonomy_code"],
        "contract_status": p["contract_status"],
        "quality_tier": p["quality_tier"],
    }


@bp.route("/programs/providers", methods=["POST"])
def create_provider():
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    body = get_body()
    program_id = req_string(body, "program_id")
    npi = req_string(body, "npi")
    taxonomy_code = req_string(body, "taxonomy_code")
    if not (npi.isdigit() and len(npi) == 10):
        raise invalid_request("npi must be exactly 10 digits")
    if program_id not in store.programs:
        raise not_found("program not found")
    for p in store.providers.values():
        if p["program_id"] == program_id and p["npi"] == npi:
            raise invalid_request("npi must be unique within the program")
    pid = new_id()
    p = {
        "id": pid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "program_id": program_id,
        "npi": npi,
        "taxonomy_code": taxonomy_code,
        "contract_status": "ACTIVE",
        "quality_tier": "GREEN",
    }
    store.providers[pid] = p
    return success_object(provider_view(p), 201)


@bp.route("/programs/providers/<pid>", methods=["GET"])
def get_provider(pid):
    get_auth()
    p = store.providers.get(pid)
    if p is None:
        raise not_found()
    return success_object(provider_view(p))


@bp.route("/programs/providers", methods=["GET"])
def list_providers():
    get_auth()
    program_id = request.args.get("program_id")
    contract_status = request.args.get("contract_status")
    quality_tier = request.args.get("quality_tier")
    items = list(store.providers.values())
    if program_id is not None:
        items = [p for p in items if p["program_id"] == program_id]
    if contract_status is not None:
        items = [p for p in items if p["contract_status"] == contract_status]
    if quality_tier is not None:
        items = [p for p in items if p["quality_tier"] == quality_tier]
    page, limit, offset, total = apply_pagination(items)
    return success_list([provider_view(p) for p in page], limit, offset, total)


@bp.route("/programs/providers/<pid>/suspend", methods=["POST"])
def suspend_provider(pid):
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    get_body(required=False)
    p = store.providers.get(pid)
    if p is None:
        raise not_found()
    if p["contract_status"] != "ACTIVE":
        raise invalid_state("Provider contract is not ACTIVE")
    p["contract_status"] = "SUSPENDED"
    touch(p)
    return success_object(provider_view(p))


# --------------------------------------------------------------- submitters ---

def submitter_view(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "program_id": s["program_id"],
        "name": s["name"],
        "trading_partner_id": s["trading_partner_id"],
        "status": s["status"],
    }


@bp.route("/programs/submitters", methods=["POST"])
def create_submitter():
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    body = get_body()
    program_id = req_string(body, "program_id")
    name = req_string(body, "name")
    trading_partner_id = req_string(body, "trading_partner_id")
    if program_id not in store.programs:
        raise not_found("program not found")
    for s in store.submitters.values():
        if s["program_id"] == program_id and s["trading_partner_id"] == trading_partner_id:
            raise invalid_request("trading_partner_id must be unique within the program")
    sid = new_id()
    s = {
        "id": sid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "program_id": program_id,
        "name": name,
        "trading_partner_id": trading_partner_id,
        "status": "ACTIVE",
    }
    store.submitters[sid] = s
    return success_object(submitter_view(s), 201)


@bp.route("/programs/submitters/<sid>", methods=["GET"])
def get_submitter(sid):
    get_auth()
    s = store.submitters.get(sid)
    if s is None:
        raise not_found()
    return success_object(submitter_view(s))


@bp.route("/programs/submitters", methods=["GET"])
def list_submitters():
    get_auth()
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(store.submitters.values())
    if program_id is not None:
        items = [s for s in items if s["program_id"] == program_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = apply_pagination(items)
    return success_list([submitter_view(s) for s in page], limit, offset, total)


@bp.route("/programs/submitters/<sid>/suspend", methods=["POST"])
def suspend_submitter(sid):
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    get_body(required=False)
    s = store.submitters.get(sid)
    if s is None:
        raise not_found()
    if s["status"] != "ACTIVE":
        raise invalid_state("Submitter is not ACTIVE")
    s["status"] = "SUSPENDED"
    touch(s)
    return success_object(submitter_view(s))
