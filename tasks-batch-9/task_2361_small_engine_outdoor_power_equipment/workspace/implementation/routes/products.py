"""Finished-goods models and immutable safety bench-test records."""

from collections import OrderedDict

from flask import Blueprint

import calc
import store
import svc
import validation as v
from auth import endpoint, READ_ROLES, user_id
from errors import ApiError
from response import list_response, object_response
from store import db, set_fields

bp = Blueprint("products", __name__)

CHANNELS = ("DEALER", "MASS_RETAIL", "DUAL")
BLADE_BRAKES = ("BLADE_BRAKE_CLUTCH", "ENGINE_KILL", "NONE")
OPC_TYPES = ("BAIL", "SEAT_SWITCH", "TWO_HAND", "CO_SHUTOFF")
STANDARD_CODES = ("ANSI_B71_1", "ANSI_B71_3", "UL_2201")


@bp.route("/product-models", methods=["POST"])
@endpoint(["PlantAdmin"])
def create_model():
    payload = v.body()
    platform_id = v.id_field(payload, "engine_platform_id")
    model_code = v.string_field(payload, "model_code", 1, 30)
    product_line = v.enum_field(payload, "product_line", calc.PRODUCT_LINES)
    channel = v.enum_field(payload, "channel", CHANNELS)
    blade_brake_type = v.enum_field(payload, "blade_brake_type", BLADE_BRAKES)
    operator_presence_type = v.enum_field(payload, "operator_presence_type", OPC_TYPES)
    warranty_months = v.int_field(payload, "warranty_months", 12, 120)
    standard_cost_cents = v.int_field(payload, "standard_cost_cents", 1)
    msrp_cents = v.int_field(payload, "msrp_cents", 0)
    if msrp_cents < standard_cost_cents:
        v.bad("msrp_cents must be at least standard_cost_cents.")
    dealer_share_pct = v.number_field(payload, "dealer_share_pct", "0.00", "1.00")
    dealer_cap_units = v.int_field(payload, "dealer_cap_units", 0)
    mass_retail_cap_units = v.int_field(payload, "mass_retail_cap_units", 0)

    platform = svc.get_platform(platform_id)
    svc.require_unique(db.product_models, "model_code", model_code)

    # Control configuration coherence (ladder priority 33).
    if operator_presence_type != calc.REQUIRED_OPC[product_line]:
        raise ApiError(
            "ERR_SAFETY_CONTROL_REQUIRED",
            "operator_presence_type must be %s for a %s."
            % (calc.REQUIRED_OPC[product_line], product_line),
        )
    if product_line == "GENERATOR":
        if blade_brake_type != "NONE":
            raise ApiError(
                "ERR_SAFETY_CONTROL_REQUIRED",
                "blade_brake_type must be NONE for a GENERATOR.",
            )
    elif blade_brake_type not in ("BLADE_BRAKE_CLUTCH", "ENGINE_KILL"):
        raise ApiError(
            "ERR_SAFETY_CONTROL_REQUIRED",
            "blade_brake_type must be BLADE_BRAKE_CLUTCH or ENGINE_KILL for a %s."
            % product_line,
        )
    if channel in ("DEALER", "DUAL"):
        if warranty_months < 36:
            raise ApiError(
                "ERR_SAFETY_CONTROL_REQUIRED",
                "warranty_months must be at least 36 for a dealer-channel model.",
            )
    elif warranty_months < 24:
        raise ApiError(
            "ERR_SAFETY_CONTROL_REQUIRED",
            "warranty_months must be at least 24 for a mass-retail model.",
        )

    # Channel share coherence (ladder priority 47).
    share = calc.dec(dealer_share_pct)
    if channel == "DEALER" and share != calc.dec("1.00"):
        raise ApiError("ERR_CHANNEL_SHARE_MISMATCH",
                       "dealer_share_pct must be 1.00 for a DEALER model.")
    if channel == "MASS_RETAIL" and share != calc.dec("0.00"):
        raise ApiError("ERR_CHANNEL_SHARE_MISMATCH",
                       "dealer_share_pct must be 0.00 for a MASS_RETAIL model.")
    if channel == "DUAL" and not (calc.dec("0.00") < share < calc.dec("1.00")):
        raise ApiError("ERR_CHANNEL_SHARE_MISMATCH",
                       "dealer_share_pct must be strictly between 0.00 and 1.00 for a DUAL model.")

    model = store.new_record(OrderedDict([
        ("engine_platform_id", platform["id"]),
        ("model_code", model_code),
        ("product_line", product_line),
        ("channel", channel),
        ("blade_brake_type", blade_brake_type),
        ("operator_presence_type", operator_presence_type),
        ("warranty_months", warranty_months),
        ("standard_cost_cents", standard_cost_cents),
        ("msrp_cents", msrp_cents),
        ("dealer_share_pct", dealer_share_pct),
        ("dealer_cap_units", dealer_cap_units),
        ("mass_retail_cap_units", mass_retail_cap_units),
        ("status", "DRAFT"),
        ("released_at", None),
    ]))
    db.product_models[model["id"]] = model
    return object_response(store.public(model), 201)


@bp.route("/product-models/<model_id>", methods=["GET"])
@endpoint(READ_ROLES)
def read_model(model_id):
    model = svc.get_model(model_id)
    return object_response(store.public(model), 200)


@bp.route("/product-models/<model_id>/safety-certifications", methods=["GET"])
@endpoint(READ_ROLES)
def list_model_certifications(model_id):
    limit, offset = v.pagination()
    model = svc.get_model(model_id)
    rows = [
        c for c in db.safety_certifications.values()
        if c["product_model_id"] == model["id"]
    ]
    rows.sort(key=lambda c: (c["tested_on"], c["created_at"], c["_seq"]), reverse=True)
    page, total = v.paginate(rows, limit, offset)
    return list_response([store.public(r) for r in page], limit, offset, total)


@bp.route("/safety-certifications", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def create_safety_certification():
    payload = v.body()
    model_id = v.id_field(payload, "product_model_id")
    standard_code = v.enum_field(payload, "standard_code", STANDARD_CODES)
    blade_present = "blade_stop_time_ms" in payload and payload["blade_stop_time_ms"] is not None
    blade_stop_time_ms = v.int_field(
        payload, "blade_stop_time_ms", 1, 10000, required=False, default=None
    )
    opc_stop_time_ms = v.int_field(payload, "opc_stop_time_ms", 1, 10000)
    tested_on = v.date_field(payload, "tested_on")
    expires_on = v.date_field(payload, "expires_on")
    if expires_on <= tested_on:
        v.bad("expires_on must be strictly after tested_on.")

    model = svc.get_model(model_id)

    if standard_code != calc.REQUIRED_STANDARD[model["product_line"]]:
        raise ApiError(
            "ERR_SAFETY_STANDARD_MISMATCH",
            "standard_code must be %s for a %s."
            % (calc.REQUIRED_STANDARD[model["product_line"]], model["product_line"]),
        )
    if model["product_line"] == "GENERATOR":
        if blade_present:
            raise ApiError(
                "ERR_SAFETY_CONTROL_REQUIRED",
                "blade_stop_time_ms must be absent or null for a GENERATOR model.",
            )
    elif not blade_present:
        raise ApiError(
            "ERR_SAFETY_CONTROL_REQUIRED",
            "blade_stop_time_ms is required for a %s model." % model["product_line"],
        )

    cert = store.new_record(OrderedDict([
        ("product_model_id", model["id"]),
        ("standard_code", standard_code),
        ("blade_stop_time_ms", blade_stop_time_ms),
        ("opc_stop_time_ms", opc_stop_time_ms),
        ("tested_on", tested_on.isoformat()),
        ("expires_on", expires_on.isoformat()),
        ("result", calc.safety_result(blade_stop_time_ms, opc_stop_time_ms)),
        ("tested_by_user_id", user_id()),
    ]), versioned=False)
    db.safety_certifications[cert["id"]] = cert
    return object_response(store.public(cert), 201)


@bp.route("/product-models/<model_id>/release", methods=["POST"])
@endpoint(["PlantAdmin"])
def release_model(model_id):
    v.body()
    model = svc.get_model(model_id)
    if model["status"] not in ("DRAFT", "SUSPENDED"):
        raise ApiError(
            "ERR_MODEL_STATE_INVALID",
            "Only a DRAFT or SUSPENDED model may be released.",
        )
    was_suspended = model["status"] == "SUSPENDED"
    svc.check_safety_certification(model)
    if was_suspended:
        platform = svc.model_platform(model)
        if platform is None or platform["certification_posture"] != "OPEN":
            raise ApiError(
                "ERR_FAMILY_NOT_CERTIFIED",
                "The model's platform is not certified for production.",
            )
    set_fields(model, status="RELEASED", released_at=store.now_clock())
    return object_response(store.public(model), 200)
