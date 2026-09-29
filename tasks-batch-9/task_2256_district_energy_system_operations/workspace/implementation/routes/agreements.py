"""ConnectionAgreement endpoints, activation sweep and the two state dimensions."""

from flask import Blueprint, g

import calc
import enums
import services as svc
from db import base_record, store, touch
from errors import fail
from middleware import ALL_STAFF, endpoint, paginate
from validators import (bad, get_dt, get_enum, get_num, get_str, json_body,
                        present, query_enum, query_str)

bp = Blueprint("agreements", __name__, url_prefix="/district-energy")

GET_READERS = ALL_STAFF + ("CustomerAccount",)

LEGAL_CONTRACT = (
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "TERMINATED"),
    ("SUSPENDED", "TERMINATED"),
    ("PENDING_CAPACITY", "TERMINATED"),
)


def new_agreement(loop, rate, customer_name, customer_class, reserved_capacity_kw,
                  service_mode, start_raw, start_dt, end_raw, end_dt):
    """The shared PENDING_CAPACITY row used by create and by project conversion."""
    agreement = base_record()
    agreement.update({
        "loop_id": loop["id"],
        "rate_schedule_id": rate["id"],
        "customer_name": customer_name,
        "customer_class": customer_class,
        "reserved_capacity_kw": reserved_capacity_kw,
        "service_mode": service_mode,
        "service_start_date": start_raw,
        "_service_start_date": start_dt,
        "service_end_date": end_raw,
        "_service_end_date": end_dt,
        "billed_demand_ratchet_kw": 0.0,
        "balance_due": 0.0,
        "contract_state": "PENDING_CAPACITY",
        "billing_state": "CURRENT",
    })
    store.agreements[agreement["id"]] = agreement
    return agreement


def require_ownership(agreement):
    """Admission ladder step 6 for the CustomerAccount identity."""
    if g.role == "CustomerAccount" and g.user_id != agreement["id"]:
        fail("ERR_FORBIDDEN_AGREEMENT",
             "a CustomerAccount may only read its own agreement")


@endpoint(bp, "/connection-agreements", ["POST"], ["BillingAnalyst"], status=201)
def create_agreement():
    body = json_body()
    loop_id = get_str(body, "loop_id")
    rate_schedule_id = get_str(body, "rate_schedule_id")
    customer_name = get_str(body, "customer_name")
    customer_class = get_enum(body, "customer_class", enums.CUSTOMER_CLASS)
    reserved_capacity_kw = get_num(body, "reserved_capacity_kw", gt=0)
    service_mode = get_enum(body, "service_mode", enums.SERVICE_MODE)
    start_raw, start_dt = get_dt(body, "service_start_date")
    end_raw, end_dt = get_dt(body, "service_end_date")
    if not end_dt > start_dt:
        bad("service_end_date must be after service_start_date")

    loop = svc.fk_get("loops", loop_id)
    rate = svc.fk_get("rate_schedules", rate_schedule_id)

    if customer_class != rate["customer_class"]:
        fail("ERR_CUSTOMER_CLASS_MISMATCH",
             "the tariff serves customer class '%s'" % rate["customer_class"])
    if service_mode != loop["service_mode"] and loop["service_mode"] != "DUAL":
        fail("ERR_SERVICE_MODE_MISMATCH",
             "the loop runs in '%s' mode" % loop["service_mode"])

    return new_agreement(loop, rate, customer_name, customer_class,
                         reserved_capacity_kw, service_mode,
                         start_raw, start_dt, end_raw, end_dt)


@endpoint(bp, "/connection-agreements", ["GET"], ALL_STAFF)
def list_agreements():
    filters = {}
    loop_id = query_str("loop_id")
    rate_schedule_id = query_str("rate_schedule_id")
    contract_state = query_enum("contract_state", enums.AGREEMENT_CONTRACT_STATE)
    billing_state = query_enum("billing_state", enums.BILLING_STATE)
    customer_class = query_enum("customer_class", enums.CUSTOMER_CLASS)
    if loop_id is not None:
        filters["loop_id"] = loop_id
    if rate_schedule_id is not None:
        filters["rate_schedule_id"] = rate_schedule_id
    if contract_state is not None:
        filters["contract_state"] = contract_state
    if billing_state is not None:
        filters["billing_state"] = billing_state
    if customer_class is not None:
        filters["customer_class"] = customer_class
    return paginate(svc.where("agreements", **filters))


@endpoint(bp, "/connection-agreements/<agreement_id>", ["GET"], GET_READERS)
def get_agreement(agreement_id):
    agreement = svc.path_get("agreements", agreement_id)
    require_ownership(agreement)
    return agreement


@endpoint(bp, "/connection-agreements/<agreement_id>/activate", ["POST"],
          ["BillingAnalyst"])
def activate_agreement(agreement_id):
    agreement = svc.path_get("agreements", agreement_id)
    if agreement["contract_state"] != "PENDING_CAPACITY":
        fail("ERR_AGREEMENT_STATE_INVALID",
             "only a PENDING_CAPACITY agreement can be activated")

    loop = store.loops[agreement["loop_id"]]
    if loop["posture"] == "ISOLATED":
        fail("ERR_LOOP_ISOLATED",
             "the loop is ISOLATED and cannot take on a new connection")

    peers = [a for a in svc.rows("agreements")
             if a["loop_id"] == loop["id"] and a["id"] != agreement["id"]
             and a["contract_state"] in ("ACTIVE", "SUSPENDED")]
    if not calc.loop_capacity_reservation_sweep(loop, agreement, peers):
        fail("ERR_LOOP_CAPACITY_EXCEEDED",
             "the reservation sweep breaches the loop oversubscription ceiling")

    agreement["contract_state"] = "ACTIVE"
    touch(agreement)
    svc.add_committed_reserved(loop, agreement["reserved_capacity_kw"])
    touch(loop)
    return agreement


@endpoint(bp, "/connection-agreements/<agreement_id>/status", ["POST"],
          ["BillingAnalyst"])
def set_agreement_status(agreement_id):
    body = json_body()
    target = get_enum(body, "contract_state", enums.AGREEMENT_CONTRACT_STATE)
    if present(body, "reason"):
        get_str(body, "reason", min_len=0)

    agreement = svc.path_get("agreements", agreement_id)
    current = agreement["contract_state"]
    if (current, target) not in LEGAL_CONTRACT:
        fail("ERR_AGREEMENT_STATE_INVALID",
             "an agreement in state '%s' cannot move to '%s'" % (current, target))

    agreement["contract_state"] = target
    touch(agreement)

    if target != "TERMINATED":
        return agreement

    if current in ("ACTIVE", "SUSPENDED"):
        loop = store.loops.get(agreement["loop_id"])
        if loop is not None:
            svc.add_committed_reserved(loop, -agreement["reserved_capacity_kw"])
            touch(loop)
    svc.cascade_agreement_terminated(agreement)
    return agreement
