"""SiteOrder endpoints (PRD Sections 3.6, 3.7)."""
from flask import Blueprint

import validate
from db import db, insert, touch, ordered
from errors import ApiError
from middleware import authorize, chain_scope
from response import ok, created, ok_list
from routes.helpers import find, maybe, filter_by, require_reason, unique_code
from services import derive

bp = Blueprint("site_orders", __name__)

FULFILLMENT_STATUSES = ("PENDING", "SCHEDULED", "IN_BUILD", "BUILT", "SHIPPED", "DELIVERED")
COMMITMENT_STATUSES = ("UNSCHEDULED", "COMMITTED", "AT_RISK", "BREACHED", "WAIVED")
ROLES = ("ChainAdmin", "ProductionPlanner", "ConnectedOpsEngineer", "PlatformAdmin")


def owning_account_id(site_order):
    if site_order is None:
        return None
    program = db.construction_programs.get(site_order["construction_program_id"])
    return program["chain_account_id"] if program else None


@bp.post("/site-orders")
def create_site_order():
    actor = authorize("ChainAdmin", "PlatformAdmin")
    payload = validate.body()
    raw_program_id = payload.get("construction_program_id")
    program_probe = maybe(db.construction_programs, raw_program_id)
    chain_scope(actor, program_probe["chain_account_id"] if program_probe else None)

    construction_program_id = validate.string_field(payload, "construction_program_id")
    chain_configuration_id = validate.string_field(payload, "chain_configuration_id")
    site_code = validate.string_field(payload, "site_code", min_len=1, max_len=32)
    committed_delivery_date = validate.datetime_field(payload, "committed_delivery_date")
    unit_count = validate.int_field(payload, "unit_count", minimum=1)

    program = find(db.construction_programs, construction_program_id,
                   "ERR_CHAIN_RESOURCE_NOT_FOUND")
    config = find(db.chain_configurations, chain_configuration_id,
                  "ERR_CHAIN_RESOURCE_NOT_FOUND")

    if config["status"] != "RELEASED":
        raise ApiError("ERR_CONFIGURATION_NOT_RELEASED",
                       "the configuration is %s, not RELEASED" % config["status"])

    unique_code(db.site_orders, construction_program_id=construction_program_id,
                site_code=site_code)

    existing = [so for so in db.site_orders.values()
                if so["construction_program_id"] == construction_program_id]
    if len(existing) >= program["site_count_planned"]:
        raise ApiError("ERR_PROGRAM_SITE_CAPACITY_EXCEEDED",
                       "the programme already holds %d site orders" % len(existing))

    site_order = insert(db.site_orders, {
        "construction_program_id": construction_program_id,
        "chain_configuration_id": chain_configuration_id,
        "site_code": site_code,
        "committed_delivery_date": committed_delivery_date,
        "unit_count": unit_count,
        "fulfillment_status": "PENDING",
        "commitment_status": "UNSCHEDULED",
        "projected_delivery_date": None,
        "slack_days": None,
        "waiver_reason": None,
    })
    derive.recompute_program_posture(program)
    return created(site_order)


@bp.get("/site-orders")
def list_site_orders():
    actor = authorize(*ROLES)
    construction_program_id = validate.str_arg("construction_program_id")
    if construction_program_id is not None:
        program_probe = maybe(db.construction_programs, construction_program_id)
        if program_probe is not None:
            chain_scope(actor, program_probe["chain_account_id"])
    limit, offset = validate.pagination()
    chain_configuration_id = validate.str_arg("chain_configuration_id")
    fulfillment_status = validate.enum_arg("fulfillment_status", FULFILLMENT_STATUSES)
    commitment_status = validate.enum_arg("commitment_status", COMMITMENT_STATUSES)

    items = ordered(db.site_orders)
    if actor.is_chain_admin:
        items = [so for so in items if owning_account_id(so) == actor.user_id]
    items = filter_by(items, "construction_program_id", construction_program_id)
    items = filter_by(items, "chain_configuration_id", chain_configuration_id)
    items = filter_by(items, "fulfillment_status", fulfillment_status)
    items = filter_by(items, "commitment_status", commitment_status)
    return ok_list(items, limit, offset)


@bp.get("/site-orders/<site_order_id>")
def get_site_order(site_order_id):
    actor = authorize(*ROLES)
    chain_scope(actor, owning_account_id(maybe(db.site_orders, site_order_id)))
    site_order = find(db.site_orders, site_order_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")
    return ok(site_order)


@bp.post("/site-orders/<site_order_id>/commitment-waiver")
def waive_commitment(site_order_id):
    actor = authorize("ChainAdmin", "PlatformAdmin")
    chain_scope(actor, owning_account_id(maybe(db.site_orders, site_order_id)))
    payload = validate.body()
    waiver_reason = require_reason(payload, "waiver_reason")

    site_order = find(db.site_orders, site_order_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")
    if site_order["commitment_status"] not in ("AT_RISK", "BREACHED"):
        raise ApiError("ERR_PRODUCTION_STATE_INVALID",
                       "only an AT_RISK or BREACHED commitment can be waived")

    site_order["commitment_status"] = "WAIVED"
    site_order["waiver_reason"] = waiver_reason
    touch(site_order)

    program = db.construction_programs.get(site_order["construction_program_id"])
    if program is not None:
        derive.recompute_program_posture(program)
    return ok(site_order)


@bp.post("/site-orders/<site_order_id>/fulfillment-events")
def fulfillment_event(site_order_id):
    authorize("ProductionPlanner", "PlatformAdmin")
    payload = validate.body()
    event = validate.enum_field(payload, "event", ("SHIP", "DELIVER"))

    site_order = find(db.site_orders, site_order_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")
    required = "BUILT" if event == "SHIP" else "SHIPPED"
    if site_order["fulfillment_status"] != required:
        raise ApiError("ERR_PRODUCTION_STATE_INVALID",
                       "%s is not permitted from %s" % (event, site_order["fulfillment_status"]))

    site_order["fulfillment_status"] = "SHIPPED" if event == "SHIP" else "DELIVERED"
    touch(site_order)

    if event == "DELIVER":
        derive.refresh_site_order(site_order)
    return ok(site_order)
