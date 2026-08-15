"""Brokerages, agents, clients."""
from flask import Blueprint, request
from db import db
from middleware import (get_caller, require_roles, get_json_body, require_fields,
                        check_enum, check_int, check_str, check_bool,
                        parse_pagination, paginate)
from response import success_object, success_list
from services.common import (new_entity, get_or_404, serialize_brokerage,
                             serialize_agent, serialize_client)
from services.events import emit

bp = Blueprint("onboarding", __name__)

US_STATES = {"FL", "CA", "WA", "NY", "TX", "RI", "MD", "NC", "SC", "MA", "GA", "NJ"}
TIER_CODES = {"STANDARD", "PREMIER", "BOUTIQUE"}
CLIENT_KINDS = {"SELLER", "BUYER", "BOTH"}
RESIDENCY_STATES = US_STATES | {"NON_US"}


@bp.route("/yacht/brokerages", methods=["POST"])
def create_brokerage():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    body = get_json_body()
    require_fields(body, ["legal_name", "home_state_code", "escrow_account_ref", "license_no"])
    check_str(body, "legal_name")
    check_enum(body, "home_state_code", US_STATES)
    check_str(body, "escrow_account_ref")
    check_str(body, "license_no")
    check_enum(body, "default_commission_tier_code", TIER_CODES, required=False)

    b = new_entity()
    b["legal_name"] = body["legal_name"]
    b["home_state_code"] = body["home_state_code"]
    b["default_commission_tier_code"] = body.get("default_commission_tier_code", "STANDARD")
    b["escrow_account_ref"] = body["escrow_account_ref"]
    b["license_no"] = body["license_no"]
    db.brokerages[b["id"]] = b
    emit("Brokerage", b["id"], "BROKERAGE_REGISTERED", caller.role, caller.user_id,
         {"legal_name": b["legal_name"]})
    return success_object(serialize_brokerage(b), 201)


@bp.route("/yacht/brokerages/<bid>", methods=["GET"])
def get_brokerage(bid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    b = get_or_404(db.brokerages, bid, "Brokerage")
    return success_object(serialize_brokerage(b))


@bp.route("/yacht/agents", methods=["POST"])
def create_agent():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    body = get_json_body()
    require_fields(body, ["brokerage_id", "full_name", "license_no", "split_pct_basis"])
    # Body FK existence (priority 4)
    get_or_404(db.brokerages, body["brokerage_id"], "Brokerage")
    check_str(body, "full_name")
    check_str(body, "license_no")
    check_int(body, "split_pct_basis", min_v=0, max_v=9000)

    a = new_entity()
    a["brokerage_id"] = body["brokerage_id"]
    a["full_name"] = body["full_name"]
    a["license_no"] = body["license_no"]
    a["split_pct_basis"] = body["split_pct_basis"]
    a["status"] = "ACTIVE"
    db.agents[a["id"]] = a
    return success_object(serialize_agent(a), 201)


@bp.route("/yacht/agents/<aid>", methods=["GET"])
def get_agent(aid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    a = get_or_404(db.agents, aid, "BrokerAgent")
    return success_object(serialize_agent(a))


@bp.route("/yacht/agents", methods=["GET"])
def list_agents():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    limit, offset = parse_pagination()
    items = sorted(db.agents.values(), key=lambda x: x["created_at"])
    brokerage_id = request.args.get("brokerage_id")
    if brokerage_id is not None:
        items = [a for a in items if a["brokerage_id"] == brokerage_id]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_agent(a) for a in page], limit, offset, total)


@bp.route("/yacht/clients", methods=["POST"])
def create_client():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent"])
    body = get_json_body()
    require_fields(body, ["kind", "full_name", "residency_state_code", "tax_id_last4"])
    check_enum(body, "kind", CLIENT_KINDS)
    check_str(body, "full_name")
    check_enum(body, "residency_state_code", RESIDENCY_STATES)
    check_str(body, "tax_id_last4")
    check_bool(body, "is_entity_buyer", required=False)

    c = new_entity()
    c["kind"] = body["kind"]
    c["full_name"] = body["full_name"]
    c["residency_state_code"] = body["residency_state_code"]
    c["tax_id_last4"] = body["tax_id_last4"]
    c["is_entity_buyer"] = body.get("is_entity_buyer", False)
    db.clients[c["id"]] = c
    return success_object(serialize_client(c), 201)


@bp.route("/yacht/clients/<cid>", methods=["GET"])
def get_client(cid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    c = get_or_404(db.clients, cid, "Client")
    return success_object(serialize_client(c))
