"""Tariff endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_roles
from response import success
from services import serializers as ser
from services.common import (
    check_enum,
    get_json_body,
    paginate,
    parse_pagination,
    require_fields,
    require_int,
    require_str,
)

bp = Blueprint("tariffs", __name__)

ALL_ROLES = {"BillingOperator", "Customer", "AssistanceCaseworker", "FieldDispatcher"}
TOU_KEYS = {"ON_PEAK", "MID_PEAK", "OFF_PEAK"}


def _validate_tariff_shape(breakpoints, rates, multipliers):
    """Domain-shape validation (ERR_INVALID_TARIFF_SHAPE, PRD §3.1).

    - len(rates) == len(breakpoints) + 1
    - breakpoints strictly ascending, each > 0
    - rates strictly ascending
    - tou_multipliers: ON_PEAK >= MID_PEAK >= OFF_PEAK, each > 0
    """
    if not isinstance(breakpoints, list) or not isinstance(rates, list):
        raise err("ERR_INVALID_TARIFF_SHAPE", "Tier arrays must be lists.")
    if len(rates) != len(breakpoints) + 1:
        raise err(
            "ERR_INVALID_TARIFF_SHAPE",
            "tier_rates length must equal breakpoints length + 1.",
        )
    for v in breakpoints:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise err("ERR_INVALID_TARIFF_SHAPE", "Breakpoints must be numbers.")
        if v <= 0:
            raise err("ERR_INVALID_TARIFF_SHAPE", "Each breakpoint must be > 0.")
    for v in rates:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise err("ERR_INVALID_TARIFF_SHAPE", "Rates must be numbers.")
    for i in range(1, len(breakpoints)):
        if not breakpoints[i] > breakpoints[i - 1]:
            raise err(
                "ERR_INVALID_TARIFF_SHAPE",
                "Breakpoints must be strictly ascending.",
            )
    for i in range(1, len(rates)):
        if not rates[i] > rates[i - 1]:
            raise err(
                "ERR_INVALID_TARIFF_SHAPE", "Rates must be strictly ascending."
            )
    if not isinstance(multipliers, dict) or set(multipliers.keys()) != TOU_KEYS:
        raise err(
            "ERR_INVALID_TARIFF_SHAPE",
            "tou_multipliers must have exactly keys ON_PEAK, MID_PEAK, OFF_PEAK.",
        )
    for k in TOU_KEYS:
        m = multipliers[k]
        if isinstance(m, bool) or not isinstance(m, (int, float)):
            raise err("ERR_INVALID_TARIFF_SHAPE", "Multipliers must be numbers.")
        if m <= 0:
            raise err("ERR_INVALID_TARIFF_SHAPE", "Each multiplier must be > 0.")
    if not (multipliers["ON_PEAK"] >= multipliers["MID_PEAK"] >= multipliers["OFF_PEAK"]):
        raise err(
            "ERR_INVALID_TARIFF_SHAPE",
            "Multipliers must satisfy ON_PEAK >= MID_PEAK >= OFF_PEAK.",
        )


@bp.route("/tariffs", methods=["POST"])
def create_tariff():
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    body = get_json_body()
    require_fields(
        body,
        [
            "code",
            "name",
            "fixed_charge_cents",
            "tier_breakpoints_kwh",
            "tier_rates_cents_per_kwh",
            "tou_multipliers",
            "demand_charge_cents_per_kw",
            "net_metering_credit_cents_per_kwh",
        ],
    )
    code = require_str(body, "code")
    name = require_str(body, "name")
    fixed = require_int(body, "fixed_charge_cents")
    demand = require_int(body, "demand_charge_cents_per_kw")
    nm = require_int(body, "net_metering_credit_cents_per_kwh")

    breakpoints = body["tier_breakpoints_kwh"]
    rates = body["tier_rates_cents_per_kwh"]
    multipliers = body["tou_multipliers"]

    # Range checks (priority 19) precede shape per PRD §3.10 ordering: range and
    # shape are both pre-state; PRD §3.1 lists the >= 0 charges under
    # ERR_VALIDATION_RANGE. Shape (array lengths/ordering) is a separate guard.
    if fixed < 0 or demand < 0 or nm < 0:
        raise err(
            "ERR_VALIDATION_RANGE",
            "fixed/demand/net-metering charges must each be >= 0.",
        )

    _validate_tariff_shape(breakpoints, rates, multipliers)

    # Reject a duplicate code (unique constraint).
    for t in db.tariffs.values():
        if t["code"] == code:
            raise err("ERR_INVALID_REQUEST", "Tariff code must be unique.")

    rec = base_record()
    rec.update({
        "code": code,
        "name": name,
        "status": "DRAFT",
        "fixed_charge_cents": fixed,
        "tier_breakpoints_kwh": list(breakpoints),
        "tier_rates_cents_per_kwh": list(rates),
        "tou_multipliers": dict(multipliers),
        "demand_charge_cents_per_kw": demand,
        "net_metering_credit_cents_per_kwh": nm,
    })
    db.tariffs[rec["id"]] = rec
    return success(ser.tariff(rec), status=201)


@bp.route("/tariffs/<tariff_id>/activate", methods=["POST"])
def activate_tariff(tariff_id):
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    rec = db.tariffs.get(tariff_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Tariff not found.")
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT tariff can be activated.")
    # Re-run shape validation at activation (PRD §3.1).
    _validate_tariff_shape(
        rec["tier_breakpoints_kwh"],
        rec["tier_rates_cents_per_kwh"],
        rec["tou_multipliers"],
    )
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(ser.tariff(rec), status=200)


@bp.route("/tariffs/<tariff_id>/retire", methods=["POST"])
def retire_tariff(tariff_id):
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    rec = db.tariffs.get(tariff_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Tariff not found.")
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE tariff can be retired.")
    rec["status"] = "RETIRED"
    touch(rec)
    return success(ser.tariff(rec), status=200)


@bp.route("/tariffs/<tariff_id>", methods=["GET"])
def get_tariff(tariff_id):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = db.tariffs.get(tariff_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Tariff not found.")
    return success(ser.tariff(rec), status=200)


@bp.route("/tariffs", methods=["GET"])
def list_tariffs():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    parse_pagination()
    status = request.args.get("status")
    items = list(db.tariffs.values())
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, pagination = paginate(items)
    return success([ser.tariff(t) for t in page], status=200, pagination=pagination)
