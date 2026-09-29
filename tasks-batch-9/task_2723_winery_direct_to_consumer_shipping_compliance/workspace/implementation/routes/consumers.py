"""Consumers, identity verification, the volume summary and the volume ledger."""
from flask import Blueprint

import clock
import response
import validate
from errors import ApiError
from middleware import require, own_consumer
from rounding import dec, liters_out
from routes import common
from services import derive, serialize, volume
from store import db, base_row, touch

bp = Blueprint("consumers", __name__)

VERIFICATION_METHODS = ("DOCUMENT", "DATABASE")
TIERS = ("STANDARD", "ELEVATED")
EVENT_TYPES = ("SHIPMENT_ACCEPTED", "RETURN_CREDIT", "MANUAL_ADJUSTMENT")


@bp.route("/dtc/consumers", methods=["POST"])
def create_consumer():
    require("PlatformAdmin", "ComplianceOfficer")
    b = validate.body()
    full_name = validate.field_str(b, "full_name")
    email = validate.field_str(b, "email")
    birth_raw, _birth = validate.field_date(b, "birthdate")
    address = validate.field_str(b, "address_line")
    city = validate.field_str(b, "city")
    code = validate.state_code(b, "state_code")
    zip_value = validate.zip_code(b, "zip_code")
    for existing in db.consumers.values():
        if existing["email"] == email:
            validate.bad("email must be unique across consumers.")
    row = base_row()
    row.update({
        "full_name": full_name,
        "email": email,
        "birthdate": birth_raw,
        "address_line": address,
        "city": city,
        "state_code": code,
        "zip_code": zip_value,
        "id_verification_method": "NONE",
        "id_verified_at": None,
    })
    db.consumers[row["id"]] = row
    return response.obj(serialize.consumer(row), 201)


@bp.route("/dtc/consumers/<cid>", methods=["GET"])
def read_consumer(cid):
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator", "Consumer")
    own_consumer(uid, role, cid)
    return response.obj(serialize.consumer(common.consumer(cid)))


@bp.route("/dtc/consumers", methods=["GET"])
def list_consumers():
    require("PlatformAdmin", "ComplianceOfficer")
    code = common.arg("state_code")
    tier = validate.query_enum("screening_tier", TIERS)
    rows = []
    for row in db.consumers.values():
        if code is not None and row["state_code"] != code:
            continue
        if tier is not None and volume.screening_tier(row) != tier:
            continue
        rows.append(row)
    return common.listing(rows, serialize.consumer)


@bp.route("/dtc/consumers/<cid>/id-verification", methods=["POST"])
def verify_consumer(cid):
    require("ComplianceOfficer")
    consumer = common.consumer(cid)
    b = validate.body()
    method = validate.field_enum(b, "id_verification_method", VERIFICATION_METHODS)
    consumer["id_verification_method"] = method
    consumer["id_verified_at"] = clock.now_iso()
    touch(consumer)
    return response.obj(serialize.consumer(consumer))


@bp.route("/dtc/consumers/<cid>/volume-summary", methods=["GET"])
def volume_summary(cid):
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "Consumer")
    own_consumer(uid, role, cid)
    consumer = common.consumer(cid)
    only = common.arg("state_code")
    derived = volume.consumer_derived(consumer)
    per_state = {}
    for state, liters in derived["rolling_liters_by_state"].items():
        if only is not None and state != only:
            continue
        rule = volume.state_rule_for(state)
        limit = dec(rule["per_consumer_limit_liters"]) if rule is not None else None
        remaining = None
        if limit is not None:
            remaining = limit - dec(liters)
            if remaining < 0:
                remaining = dec(0)
        per_state[state] = {
            "rolling_liters": liters,
            "limit_liters": liters_out(limit) if limit is not None else None,
            "remaining_liters": liters_out(remaining) if remaining is not None else None,
            "per_consumer_limit_liters": liters_out(limit) if limit is not None else None,
            "headroom_liters": liters_out(remaining) if remaining is not None else None,
        }
    return response.obj({
        "consumer_id": consumer["id"],
        "as_of": clock.now_iso(),
        "per_state": per_state,
        "risk_score_screening": derived["risk_score_screening"],
        "risk_score_audit": derived["risk_score_audit"],
        "screening_tier": derived["screening_tier"],
        "return_credit_count": derived["return_credit_count"],
        "denied_exception_count": derived["denied_exception_count"],
    })


# ---- volume ledger --------------------------------------------------------
@bp.route("/dtc/volume-ledger-entries", methods=["POST"])
def create_ledger_entry():
    require("ComplianceOfficer")
    b = validate.body()
    consumer_id = validate.field_str(b, "consumer_id")
    winery_id = validate.field_str(b, "winery_id")
    order_id = validate.field_str(b, "order_id", required=False)
    shipment_id = validate.field_str(b, "shipment_id", required=False)
    code = validate.state_code(b, "state_code")
    liters = validate.field_num(b, "liters")
    occurred_raw, occurred_dt = validate.field_instant(b, "occurred_at", required=False)
    reason = validate.field_str(b, "reason")

    consumer = common.consumer(consumer_id)
    common.winery(winery_id)
    if order_id is not None:
        common.order(order_id)
    if shipment_id is not None:
        common.shipment(shipment_id)
    rule = common.rule_for_state(code)

    if occurred_dt is None:
        occurred_dt = clock.now()
        occurred_raw = clock.now_iso()

    if liters > 0:
        projected = volume.rolling_state_liters(consumer_id, code, extra=liters)
        if projected > dec(rule["per_consumer_limit_liters"]):
            raise ApiError("ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED",
                           "The adjustment would exceed the per-consumer limit for %s." % code)
        winery_projected = volume.winery_annual_liters(winery_id, code, extra=liters)
        if winery_projected > dec(rule["per_winery_annual_limit_liters"]):
            raise ApiError("ERR_WINERY_VOLUME_LIMIT_EXCEEDED",
                           "The adjustment would exceed the winery's annual limit for %s." % code)

    row = volume.append_entry(consumer_id, winery_id, code, liters, "MANUAL_ADJUSTMENT",
                              order_id=order_id, shipment_id=shipment_id,
                              occurred_raw=occurred_raw, occurred_dt=occurred_dt,
                              reason=reason)
    derive.bump_consumer(consumer)
    return response.obj(serialize.ledger_entry(row), 201)


@bp.route("/dtc/volume-ledger-entries/<lid>", methods=["GET"])
def read_ledger_entry(lid):
    require("PlatformAdmin", "ComplianceOfficer")
    return response.obj(serialize.ledger_entry(common.ledger_entry(lid)))


@bp.route("/dtc/volume-ledger-entries", methods=["GET"])
def list_ledger_entries():
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator")
    winery_id = common.scope_winery(common.arg("winery_id"), uid, role)
    consumer_id = common.arg("consumer_id")
    order_id = common.arg("order_id")
    shipment_id = common.arg("shipment_id")
    code = common.arg("state_code")
    event_type = validate.query_enum("event_type", EVENT_TYPES)
    rows = [e for e in db.ledger_entries.values()
            if (winery_id is None or e["winery_id"] == winery_id)
            and (consumer_id is None or e["consumer_id"] == consumer_id)
            and (order_id is None or e["order_id"] == order_id)
            and (shipment_id is None or e["shipment_id"] == shipment_id)
            and (code is None or e["state_code"] == code)
            and (event_type is None or e["event_type"] == event_type)]
    return common.listing(rows, serialize.ledger_entry)
