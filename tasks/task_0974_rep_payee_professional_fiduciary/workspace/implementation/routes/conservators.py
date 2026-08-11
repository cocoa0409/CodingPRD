"""Conservators endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CLIENT_NOT_FOUND,
    ERR_CONSERVATOR_NOT_FOUND,
    ERR_DUPLICATE_UNIQUE_FIELD,
    ERR_INVALID_STATE,
    err,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import serialize_conservator
from services.cascade import clock_now_iso
from util import (
    new_id,
    parse_date,
    parse_pagination,
    require_body,
    get_string,
    get_enum,
    reject_unexpected,
)

bp = Blueprint("conservators", __name__)

READ_ROLES = ("FiduciaryAdmin", "CaseManager", "FinancialOfficer", "ConservatorOfficer", "ComplianceAuditor")
SCOPES = ("EXCLUSIVE", "SHARED", "ADVISORY")


@bp.route("/conservators", methods=["POST"])
def create_conservator():
    require_roles("FiduciaryAdmin")
    body = require_body()
    reject_unexpected(body, {
        "client_id", "full_name", "court_case_number", "authority_scope", "appointed_date",
    })
    client_id = get_string(body, "client_id")
    full_name = get_string(body, "full_name")
    ccn = get_string(body, "court_case_number")
    scope = get_enum(body, "authority_scope", SCOPES)
    appointed = parse_date(get_string(body, "appointed_date"), "appointed_date")

    if client_id not in store.clients:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")
    for c in store.conservators.values():
        if c["court_case_number"] == ccn:
            raise err(ERR_DUPLICATE_UNIQUE_FIELD, 409, "court_case_number already in use")

    now = clock_now_iso()
    cid = new_id()
    c = {
        "id": cid,
        "client_id": client_id,
        "full_name": full_name,
        "court_case_number": ccn,
        "authority_scope": scope,
        "appointed_date": appointed,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.conservators[cid] = c
    return success_object(serialize_conservator(c), status=201)


@bp.route("/conservators", methods=["GET"])
def list_conservators():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    client_id = request.args.get("client_id")
    scope = request.args.get("authority_scope")
    status = request.args.get("status")
    items = list(store.conservators.values())
    if client_id is not None:
        items = [c for c in items if c["client_id"] == client_id]
    if scope is not None:
        items = [c for c in items if c["authority_scope"] == scope]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_conservator(c) for c in page], limit, offset, total)


def _get_or_404(cid):
    c = store.conservators.get(cid)
    if not c:
        raise err(ERR_CONSERVATOR_NOT_FOUND, 404, "conservator not found")
    return c


@bp.route("/conservators/<cid>", methods=["GET"])
def get_conservator(cid):
    require_roles(*READ_ROLES)
    c = _get_or_404(cid)
    return success_object(serialize_conservator(c))


@bp.route("/conservators/<cid>/suspend", methods=["POST"])
def suspend_conservator(cid):
    require_roles("FiduciaryAdmin")
    c = _get_or_404(cid)
    if c["status"] == "DISCHARGED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Conservator is DISCHARGED")
    if c["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, 409, "Only ACTIVE -> SUSPENDED")
    now = clock_now_iso()
    c["status"] = "SUSPENDED"
    c["updated_at"] = now
    c["version"] += 1
    return success_object(serialize_conservator(c))


@bp.route("/conservators/<cid>/discharge", methods=["POST"])
def discharge_conservator(cid):
    require_roles("FiduciaryAdmin")
    c = _get_or_404(cid)
    if c["status"] == "DISCHARGED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Conservator is DISCHARGED")
    if c["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err(ERR_INVALID_STATE, 409, "Only ACTIVE/SUSPENDED -> DISCHARGED")
    now = clock_now_iso()
    c["status"] = "DISCHARGED"
    c["updated_at"] = now
    c["version"] += 1
    # reject PENDING_CONSERVATOR disbursements of this client
    for d in store.disbursements.values():
        if d["client_id"] == c["client_id"] and d["status"] == "PENDING_CONSERVATOR":
            d["status"] = "REJECTED"
            d["updated_at"] = now
            d["version"] += 1
    return success_object(serialize_conservator(c))
