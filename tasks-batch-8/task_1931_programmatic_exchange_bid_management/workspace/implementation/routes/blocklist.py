"""Brand-safety blocklist endpoints (PRD §3.4)."""

from flask import Blueprint, request

from db import store
from errors import (
    not_found, unauthorized, ApiError,
    ERR_BLOCKLIST_SCOPE_MISMATCH, ERR_ENTRY_ALREADY_LIFTED,
)
from middleware import (
    require_roles, ALL_ROLES, ROLE_EXCHANGE_ADMIN, ROLE_PUBLISHER_MANAGER,
)
from response import success_object, success_list, paginate
from util import get_body, req_str, req_enum, opt_str
from services.core import (
    BLOCKLIST_SCOPES, RULE_TYPES, base_record, touch, serialize_entry, _sorted,
)

bp = Blueprint("blocklist", __name__)


@bp.route("/blocklist-entries", methods=["POST"])
def create_entry():
    role, user_id = require_roles([ROLE_EXCHANGE_ADMIN, ROLE_PUBLISHER_MANAGER])
    body = get_body()
    scope = req_enum(body, "scope", BLOCKLIST_SCOPES)
    rule_type = req_enum(body, "rule_type", RULE_TYPES)
    value = req_str(body, "value")
    publisher_id = opt_str(body, "publisher_id")
    deal_id = opt_str(body, "deal_id")
    # existence (stage 5) for any supplied FK, left to right
    if publisher_id is not None and publisher_id not in store.publishers:
        raise not_found("Publisher not found")
    if deal_id is not None and deal_id not in store.deals:
        raise not_found("Deal not found")
    # ownership for the entity-backed role (stage 6): a PublisherManager may
    # create PUBLISHER entries on their own publisher or DEAL entries on their
    # own deals only — never EXCHANGE entries
    if role == ROLE_PUBLISHER_MANAGER:
        if scope == "EXCHANGE":
            raise unauthorized("PublisherManager may not create EXCHANGE-scope entries")
        if scope == "PUBLISHER" and publisher_id is not None and publisher_id != user_id:
            raise unauthorized("Entry targets a different publisher")
        if scope == "DEAL" and deal_id is not None:
            deal = store.deals.get(deal_id)
            if deal is not None and deal["publisher_id"] != user_id:
                raise unauthorized("Entry targets a deal of a different publisher")
    # scope consistency (stage 8)
    if value == "":
        raise ApiError(ERR_BLOCKLIST_SCOPE_MISMATCH, 422, "value must be non-empty")
    if scope == "PUBLISHER":
        if publisher_id is None or deal_id is not None:
            raise ApiError(ERR_BLOCKLIST_SCOPE_MISMATCH, 422,
                           "PUBLISHER scope requires publisher_id and forbids deal_id")
    elif scope == "DEAL":
        if deal_id is None or publisher_id is not None:
            raise ApiError(ERR_BLOCKLIST_SCOPE_MISMATCH, 422,
                           "DEAL scope requires deal_id and forbids publisher_id")
    else:  # EXCHANGE
        if publisher_id is not None or deal_id is not None:
            raise ApiError(ERR_BLOCKLIST_SCOPE_MISMATCH, 422,
                           "EXCHANGE scope carries neither publisher_id nor deal_id")
    entry = base_record()
    entry.update({
        "scope": scope,
        "publisher_id": publisher_id,
        "deal_id": deal_id,
        "rule_type": rule_type,
        "value": value,
        "status": "ACTIVE",
    })
    store.blocklist[entry["id"]] = entry
    return success_object(serialize_entry(entry), 201)


@bp.route("/blocklist-entries", methods=["GET"])
def list_entries():
    require_roles(ALL_ROLES)
    scope = request.args.get("scope")
    publisher_id = request.args.get("publisher_id")
    deal_id = request.args.get("deal_id")
    status = request.args.get("status")
    items = list(store.blocklist.values())
    if scope is not None:
        items = [e for e in items if e["scope"] == scope]
    if publisher_id is not None:
        items = [e for e in items if e["publisher_id"] == publisher_id]
    if deal_id is not None:
        items = [e for e in items if e["deal_id"] == deal_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, limit, offset, total = paginate(_sorted(items), request.args)
    return success_list([serialize_entry(e) for e in page], limit, offset, total)


@bp.route("/blocklist-entries/<entryId>", methods=["GET"])
def get_entry(entryId):
    require_roles(ALL_ROLES)
    e = store.blocklist.get(entryId)
    if e is None:
        raise not_found("BlocklistEntry not found")
    return success_object(serialize_entry(e))


@bp.route("/blocklist-entries/<entryId>/lift", methods=["POST"])
def lift_entry(entryId):
    require_roles([ROLE_EXCHANGE_ADMIN])
    e = store.blocklist.get(entryId)
    if e is None:
        raise not_found("BlocklistEntry not found")
    if e["status"] != "ACTIVE":
        raise ApiError(ERR_ENTRY_ALREADY_LIFTED, 409,
                       "BlocklistEntry is already LIFTED")
    e["status"] = "LIFTED"
    touch(e)
    return success_object(serialize_entry(e))
