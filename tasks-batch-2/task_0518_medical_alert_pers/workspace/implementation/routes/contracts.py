"""Contract endpoints: lifecycle, billing, cancellation (PRD 3.2-3.4, 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

from clock import clock
from db import store
from errors import err
from middleware import get_auth, require_role
from models import new_record, touch, serialize_contract, serialize_device, serialize_equipment_return
from response import object_response, array_response
from services.lookup import (get_contract, get_subscriber, get_plan, devices_for_contract,
                             require_owner_subscriber)
from services import contract_service as cs
from services.calculations import prorated_cancellation_refund
from services.contract_service import any_device_fall_detection, compute_etf
from util import (get_json_body, require_fields, parse_pagination, paginate, sort_by_created,
                  add_months, require_nonneg_int)

bp = Blueprint("contracts", __name__)


@bp.route("/pers/contracts", methods=["POST"])
def create_contract():
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["subscriber_id", "plan_id"])
    # existence resolution left-to-right (priority 3)
    get_subscriber(body["subscriber_id"])
    get_plan(body["plan_id"])

    r = new_record()
    r.update({
        "subscriber_id": body["subscriber_id"],
        "plan_id": body["plan_id"],
        "pinned_monthly_fee_cents": None,
        "pinned_addon_cents": None,
        "pinned_etf_cents": None,
        "pinned_min_commitment_months": None,
        "billing_status": "CURRENT",
        "service_status": "PENDING_ACTIVATION",
        "activated_at_dt": None,
        "paid_through_at_dt": None,
        "cancellation_effective_at_dt": None,
        "refund_cents": 0,
        "etf_charged_cents": 0,
        "outstanding_balance_cents": 0,
    })
    store.contracts[r["id"]] = r
    return object_response(serialize_contract(r), 201)


@bp.route("/pers/contracts/<cid>", methods=["GET"])
def get_contract_route(cid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    r = get_contract(cid)
    return object_response(serialize_contract(r), 200)


@bp.route("/pers/contracts", methods=["GET"])
def list_contracts():
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    limit, offset = parse_pagination()
    items = list(store.contracts.values())
    if "subscriber_id" in request.args:
        items = [c for c in items if c["subscriber_id"] == request.args.get("subscriber_id")]
    if "plan_id" in request.args:
        items = [c for c in items if c["plan_id"] == request.args.get("plan_id")]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_contract(c) for c in page], limit, offset, total)


@bp.route("/pers/contracts/<cid>/devices", methods=["GET"])
def list_contract_devices(cid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    get_contract(cid)
    items = sort_by_created(devices_for_contract(cid))
    limit, offset = parse_pagination()
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_device(d) for d in page], limit, offset, total)


@bp.route("/pers/contracts/<cid>/equipment-returns", methods=["GET"])
def list_contract_returns(cid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    get_contract(cid)
    items = sort_by_created([r for r in store.equipment_returns.values() if r["contract_id"] == cid])
    limit, offset = parse_pagination()
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_equipment_return(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Service-dimension transitions
# ---------------------------------------------------------------------------
@bp.route("/pers/contracts/<cid>/activate", methods=["POST"])
def activate_contract(cid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    c = get_contract(cid)
    # state precondition (priority 5)
    if c["service_status"] != "PENDING_ACTIVATION":
        raise err("ERR_INVALID_STATE", "Contract is not PENDING_ACTIVATION")
    plan = get_plan(c["plan_id"])
    if plan["archived"]:
        raise err("ERR_INVALID_STATE", "Plan is archived")
    devices = devices_for_contract(cid)
    if not any(d["status"] == "ENROLLED" for d in devices):
        raise err("ERR_INVALID_STATE", "No ENROLLED device under this contract")
    subscriber = get_subscriber(c["subscriber_id"])
    if subscriber["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Subscriber is not ACTIVE")

    now = clock.now()
    c["service_status"] = "ACTIVE"
    cs.pin_plan_terms(c, plan)
    c["activated_at_dt"] = now
    c["paid_through_at_dt"] = add_months(now, 1)
    cs.cascade_activate(c)
    touch(c)
    return object_response(serialize_contract(c), 200)


@bp.route("/pers/contracts/<cid>/suspend", methods=["POST"])
def suspend_contract(cid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    c = get_contract(cid)
    if not (c["service_status"] == "ACTIVE" and c["billing_status"] == "PAST_DUE"):
        raise err("ERR_INVALID_STATE", "Suspend requires ACTIVE service and PAST_DUE billing")
    c["service_status"] = "SUSPENDED"
    cs.cascade_suspend(c)
    touch(c)
    return object_response(serialize_contract(c), 200)


@bp.route("/pers/contracts/<cid>/reinstate", methods=["POST"])
def reinstate_contract(cid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    c = get_contract(cid)
    if not (c["service_status"] == "SUSPENDED" and c["billing_status"] == "CURRENT"):
        raise err("ERR_INVALID_STATE", "Reinstate requires SUSPENDED service and CURRENT billing")
    c["service_status"] = "ACTIVE"
    cs.cascade_reinstate(c)
    touch(c)
    return object_response(serialize_contract(c), 200)


@bp.route("/pers/contracts/<cid>/request-cancellation", methods=["POST"])
def request_cancellation(cid):
    uid, role = get_auth()
    require_role(role, {"Subscriber"})
    c = get_contract(cid)
    # ownership (priority 4) before state
    require_owner_subscriber(role, uid, c["subscriber_id"])
    body = get_json_body()
    require_fields(body, ["expected_contract_version"])
    expected = body["expected_contract_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", "expected_contract_version must be an integer")

    # state legality (priority 5)
    if c["service_status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Cancellation can only be requested from ACTIVE or SUSPENDED")

    # OCC (priority 18) — checked after state per scaffold priority ordering
    if expected != c["version"]:
        raise err("ERR_STALE_VERSION", "expected_contract_version does not match current version")

    now = clock.now()
    starting = c["service_status"]
    variant = "STANDARD" if starting == "ACTIVE" else "IMMEDIATE"

    monthly_cents = c.get("pinned_monthly_fee_cents", 0)
    if any_device_fall_detection(c):
        monthly_cents += c.get("pinned_addon_cents", 0)

    refund = prorated_cancellation_refund(variant, monthly_cents, c.get("paid_through_at_dt"), now)
    etf = compute_etf(c)

    c["service_status"] = "CANCELLATION_REQUESTED"
    c["refund_cents"] = refund
    c["etf_charged_cents"] = etf
    if variant == "STANDARD":
        c["cancellation_effective_at_dt"] = c.get("paid_through_at_dt")
    else:
        c["cancellation_effective_at_dt"] = now
    c["outstanding_balance_cents"] = etf - refund
    touch(c)
    return object_response(serialize_contract(c), 200)


@bp.route("/pers/contracts/<cid>/finalize-cancellation", methods=["POST"])
def finalize_cancellation(cid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    c = get_contract(cid)
    if c["service_status"] != "CANCELLATION_REQUESTED":
        raise err("ERR_INVALID_STATE", "Contract is not CANCELLATION_REQUESTED")
    # temporal gate (priority 17)
    eff = c.get("cancellation_effective_at_dt")
    if eff is None or clock.now() < eff:
        raise err("ERR_TEMPORAL_NOT_DUE", "cancellation_effective_at not reached")
    # life-safety gate (priority 7)
    devices = devices_for_contract(cid)
    for d in devices:
        if d["status"] in ("ACTIVE", "NEEDS_TEST"):
            raise err("ERR_LIVE_MONITORING_BLOCKS_CANCEL", "A device is still ACTIVE or NEEDS_TEST")
    device_ids = {d["id"] for d in devices}
    for a in store.alarm_events.values():
        if a["device_id"] in device_ids and a["status"] not in ("RESOLVED_OK", "FALSE_ALARM", "DISPATCHED_911"):
            raise err("ERR_LIVE_MONITORING_BLOCKS_CANCEL", "A non-terminal alarm exists")

    c["service_status"] = "CANCELLED"
    cs.cascade_finalize(c)
    touch(c)
    return object_response(serialize_contract(c), 200)


# ---------------------------------------------------------------------------
# Billing-dimension transitions (PRD 3.3)
# ---------------------------------------------------------------------------
@bp.route("/pers/contracts/<cid>/billing/mark-past-due", methods=["POST"])
def mark_past_due(cid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    c = get_contract(cid)
    if c["billing_status"] != "CURRENT":
        raise err("ERR_INVALID_STATE", "billing_status is not CURRENT")
    paid_through = c.get("paid_through_at_dt")
    if paid_through is None or not (clock.now() > paid_through):
        raise err("ERR_TEMPORAL_NOT_DUE", "paid_through_at not yet elapsed")
    c["billing_status"] = "PAST_DUE"
    touch(c)
    return object_response(serialize_contract(c), 200)


@bp.route("/pers/contracts/<cid>/billing/record-payment", methods=["POST"])
def record_payment(cid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    c = get_contract(cid)
    if c["billing_status"] != "PAST_DUE":
        raise err("ERR_INVALID_STATE", "billing_status is not PAST_DUE")
    c["billing_status"] = "CURRENT"
    if c.get("paid_through_at_dt") is not None:
        c["paid_through_at_dt"] = add_months(c["paid_through_at_dt"], 1)
    touch(c)
    return object_response(serialize_contract(c), 200)


@bp.route("/pers/contracts/<cid>/billing/write-off", methods=["POST"])
def write_off(cid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    c = get_contract(cid)
    if not (c["billing_status"] == "PAST_DUE" and c["service_status"] == "CANCELLED"):
        raise err("ERR_INVALID_STATE", "write-off requires PAST_DUE billing and CANCELLED service")
    c["billing_status"] = "WRITTEN_OFF"
    touch(c)
    return object_response(serialize_contract(c), 200)
