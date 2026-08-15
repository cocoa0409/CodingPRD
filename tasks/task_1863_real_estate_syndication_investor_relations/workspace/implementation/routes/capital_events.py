"""Capital events: announce, execute (net proceeds lock), cancel (PRD 3.6)."""
from flask import Blueprint

import resolve
from db import db
from errors import raise_error
from middleware import SPONSOR, ALL_ROLES, endpoint
from response import success_list, success_object
from serializers import ser_capital_event
from services.calculations import capital_event_net_distributable
from services.domain import stamp_new, touch, sorted_items
from util import CLOCK, fmt_dt
from validate import get_body, req_enum, req_int, pagination, apply_filters

bp = Blueprint("capital_events", __name__)
RS = {"strict_slashes": False}

EVENT_KINDS = ("REFINANCE", "SALE")


@bp.route("/syndications/<syndicationId>/properties/<propertyId>/capital-events",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def create_capital_event(caller, syndicationId, propertyId):
    resolve.syndication(syndicationId)
    resolve.property_(propertyId)
    body = get_body()
    kind = req_enum(body, "event_kind", EVENT_KINDS)
    gross = req_int(body, "gross_proceeds_cents", minimum=0)
    debt = req_int(body, "debt_payoff_cents", minimum=0)
    if any(e["property_id"] == propertyId and e["status"] in ("ANNOUNCED", "EXECUTED")
           for e in db["capital_events"].values()):
        raise_error("ERR_PROPERTY_HAS_ACTIVE_CAPITAL_EVENT",
                    "property already has an active capital event")
    e = {
        "property_id": propertyId,
        "event_kind": kind,
        "gross_proceeds_cents": gross,
        "debt_payoff_cents": debt,
        "net_distributable_cents": None,
        "status": "ANNOUNCED",
        "executed_at": None,
    }
    stamp_new(e)
    db["capital_events"][e["id"]] = e
    return success_object(ser_capital_event(e), 201)


@bp.route("/syndications/<syndicationId>/properties/<propertyId>/capital-events",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def list_capital_events(caller, syndicationId, propertyId):
    resolve.syndication(syndicationId)
    resolve.property_(propertyId)
    limit, offset = pagination()
    items = [e for e in db["capital_events"].values() if e["property_id"] == propertyId]
    items = apply_filters(sorted_items(items),
                          {"status": "status", "event_kind": "event_kind"})
    page = items[offset:offset + limit]
    return success_list([ser_capital_event(o) for o in page], len(items), limit, offset)


@bp.route("/syndications/<syndicationId>/properties/<propertyId>/capital-events/<capitalEventId>",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def get_capital_event(caller, syndicationId, propertyId, capitalEventId):
    return success_object(ser_capital_event(
        resolve.capital_event(syndicationId, propertyId, capitalEventId)))


@bp.route("/syndications/<syndicationId>/properties/<propertyId>/capital-events/<capitalEventId>/execute",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def execute_capital_event(caller, syndicationId, propertyId, capitalEventId):
    prop = resolve.property_(propertyId)
    ev = resolve.capital_event(syndicationId, propertyId, capitalEventId)
    if ev["status"] != "ANNOUNCED":
        raise_error("ERR_INVALID_STATE",
                    f"cannot execute a capital event in status {ev['status']}")
    if prop["status"] not in ("OWNED", "UNDER_CONTRACT_TO_SELL"):
        raise_error("ERR_PROPERTY_NOT_TRANSACTABLE",
                    f"property in status {prop['status']} cannot execute a capital event")
    if ev["gross_proceeds_cents"] <= ev["debt_payoff_cents"]:
        raise_error("ERR_INSUFFICIENT_PROCEEDS",
                    "gross proceeds must exceed the debt payoff")
    ev["net_distributable_cents"] = capital_event_net_distributable(
        ev["gross_proceeds_cents"], ev["debt_payoff_cents"])
    ev["executed_at"] = fmt_dt(CLOCK.now())
    ev["status"] = "EXECUTED"
    touch(ev)
    if ev["event_kind"] == "SALE":
        prop["status"] = "SOLD"
        touch(prop)
    return success_object(ser_capital_event(ev))


@bp.route("/syndications/<syndicationId>/properties/<propertyId>/capital-events/<capitalEventId>/cancel",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def cancel_capital_event(caller, syndicationId, propertyId, capitalEventId):
    ev = resolve.capital_event(syndicationId, propertyId, capitalEventId)
    if ev["status"] != "ANNOUNCED":
        raise_error("ERR_INVALID_STATE",
                    f"cannot cancel a capital event in status {ev['status']}")
    ev["status"] = "CANCELLED"
    touch(ev)
    return success_object(ser_capital_event(ev))
