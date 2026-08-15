"""Platform bootstrap + factory registry: buyers, agents, inspectors, factories."""

from flask import Blueprint

from db import new_id, public, stamp_new, store
from middleware import (
    ALL_ROLES,
    body_json,
    get_or_404,
    req_int,
    req_str,
    require_roles,
)
from response import success_object
from services.domain import agent_commission_ytd_cents, buyer_ytd_gmv_cents

bp = Blueprint("registry", __name__)


def buyer_view(buyer):
    view = public(buyer)
    view["ytd_gmv_cents"] = buyer_ytd_gmv_cents(buyer["id"])
    return view


def agent_view(agent):
    view = public(agent)
    view["commission_ytd_cents"] = agent_commission_ytd_cents(agent["id"])
    return view


@bp.route("/sourcing/buyers", methods=["POST"])
def create_buyer():
    require_roles("PlatformAdmin")
    data = body_json()
    name = req_str(data, "name")
    country_code = req_str(data, "country_code")
    buyer = stamp_new(
        {
            "id": new_id(),
            "name": name,
            "country_code": country_code,
            "credit_balance_cents": 0,
            "status": "ACTIVE",
        }
    )
    store.buyers[buyer["id"]] = buyer
    return success_object(buyer_view(buyer), 201)


@bp.route("/sourcing/buyers/<buyerId>", methods=["GET"])
def get_buyer(buyerId):
    require_roles(*ALL_ROLES)
    buyer = get_or_404(store.buyers, buyerId, "ERR_BUYER_NOT_FOUND", "Buyer")
    return success_object(buyer_view(buyer))


@bp.route("/sourcing/agents", methods=["POST"])
def create_agent():
    require_roles("PlatformAdmin")
    data = body_json()
    name = req_str(data, "name")
    agency_name = req_str(data, "agency_name")
    agent = stamp_new(
        {
            "id": new_id(),
            "name": name,
            "agency_name": agency_name,
        }
    )
    store.agents[agent["id"]] = agent
    return success_object(agent_view(agent), 201)


@bp.route("/sourcing/agents/<agentId>", methods=["GET"])
def get_agent(agentId):
    require_roles(*ALL_ROLES)
    agent = get_or_404(store.agents, agentId, "ERR_AGENT_NOT_FOUND", "Agent")
    return success_object(agent_view(agent))


@bp.route("/sourcing/inspectors", methods=["POST"])
def create_inspector():
    require_roles("PlatformAdmin")
    data = body_json()
    name = req_str(data, "name")
    region = req_str(data, "region")
    inspector = stamp_new(
        {
            "id": new_id(),
            "name": name,
            "region": region,
        }
    )
    store.inspectors[inspector["id"]] = inspector
    return success_object(public(inspector), 201)


@bp.route("/sourcing/inspectors/<inspectorId>", methods=["GET"])
def get_inspector(inspectorId):
    require_roles(*ALL_ROLES)
    inspector = get_or_404(
        store.inspectors, inspectorId, "ERR_INSPECTOR_NOT_FOUND", "Inspector"
    )
    return success_object(public(inspector))


@bp.route("/sourcing/factories", methods=["POST"])
def create_factory():
    require_roles("SourcingAgent")
    data = body_json()
    name = req_str(data, "name")
    country_code = req_str(data, "country_code")
    monthly_capacity_units = req_int(data, "monthly_capacity_units", lo=1)
    factory = stamp_new(
        {
            "id": new_id(),
            "name": name,
            "country_code": country_code,
            "monthly_capacity_units": monthly_capacity_units,
            "status": "ACTIVE",
            "compliance_posture": "COMPLIANT",
            "debit_balance_cents": 0,
            "latest_audit_grade": "NONE",
            "audit_score": 0,
            "_grade_source": None,
        }
    )
    store.factories[factory["id"]] = factory
    return success_object(public(factory), 201)


@bp.route("/sourcing/factories/<factoryId>", methods=["GET"])
def get_factory(factoryId):
    require_roles(*ALL_ROLES)
    factory = get_or_404(store.factories, factoryId, "ERR_FACTORY_NOT_FOUND", "Factory")
    return success_object(public(factory))
