"""Technicians, chemical lots, catalogue parts and brewer programmes."""
from flask import Blueprint

import projections
import serializers
import settlement
import store
from common import API_PREFIX, MIN_USABLE_LITERS, ROLE_AUDITOR, ROLE_BREWER, ROLE_DISPATCH, ROLE_TECH
from envelope import object_response
from errors import raise_error
from helpers import listing, match, resolve_path
from security import guard
from shape import F, parse_body, query_bool, query_enum

bp = Blueprint("registry", __name__)

CERT_LEVELS = ["APPRENTICE", "CERTIFIED", "MASTER"]
TECH_STATUSES = ["ACTIVE", "INACTIVE"]
CHEMICAL_TYPES = ["CAUSTIC", "ACID"]
LOT_STATUSES = ["AVAILABLE", "DEPLETED", "QUARANTINED", "EXPIRED"]
COMPONENT_TYPES = ["FAUCET", "COUPLER", "FOB"]
FUNDED_SCOPES = ["CLEANING_ONLY", "CLEANING_AND_PARTS", "FULL"]
PROGRAM_STATUSES = ["ACTIVE", "EXHAUSTED", "ENDED"]


# ------------------------------------------------------------------- technicians

@bp.post(API_PREFIX + "/technicians")
@guard(ROLE_DISPATCH)
def create_technician():
    body = parse_body([
        F("full_name", "str", required=True, max_len=120),
        F("certification_level", "enum", required=True, values=CERT_LEVELS),
        F("caustic_certified", "bool"),
        F("status", "enum", values=TECH_STATUSES),
    ])
    row = store.new_row({
        "full_name": body["full_name"],
        "certification_level": body["certification_level"],
        "caustic_certified": bool(body["caustic_certified"]) if body["caustic_certified"] is not None else False,
        "status": body["status"] or "ACTIVE",
    })
    store.technicians[row["id"]] = row
    return object_response(serializers.technician(row), 201)


@bp.get(API_PREFIX + "/technicians/<technician_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH)
def read_technician(technician_id):
    return object_response(serializers.technician(
        resolve_path("technician_id", technician_id)))


@bp.get(API_PREFIX + "/technicians")
@guard(ROLE_DISPATCH, ROLE_AUDITOR)
def list_technicians():
    status = query_enum("status", TECH_STATUSES)
    level = query_enum("certification_level", CERT_LEVELS)
    caustic = query_bool("caustic_certified")
    rows = [r for r in store.technicians.values()
            if match(r, "status", status)
            and match(r, "certification_level", level)
            and match(r, "caustic_certified", caustic)]
    return listing(rows, serializers.technician)


# ----------------------------------------------------------------- chemical lots

@bp.post(API_PREFIX + "/chemical-lots")
@guard(ROLE_DISPATCH)
def create_chemical_lot():
    body = parse_body([
        F("chemical_type", "enum", required=True, values=CHEMICAL_TYPES),
        F("lot_code", "str", required=True),
        F("concentration_pct_stock", "num", required=True, min_value="1.0", max_value="100.0"),
        F("liters_initial", "num", required=True, gt=0),
        F("expires_on", "date", required=True),
    ])
    if any(r["lot_code"] == body["lot_code"] for r in store.chemical_lots.values()):
        raise_error("ERR_DUPLICATE_LOT_CODE")
    row = store.new_row({
        "chemical_type": body["chemical_type"],
        "lot_code": body["lot_code"],
        "concentration_pct_stock": body["concentration_pct_stock"],
        "liters_initial": body["liters_initial"],
        "liters_remaining": body["liters_initial"],
        "expires_on": body["expires_on"],
        "status": "AVAILABLE",
    })
    store.chemical_lots[row["id"]] = row
    return object_response(serializers.chemical_lot(row), 201)


@bp.get(API_PREFIX + "/chemical-lots/<lot_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH)
def read_chemical_lot(lot_id):
    return object_response(serializers.chemical_lot(resolve_path("lot_id", lot_id)))


@bp.get(API_PREFIX + "/chemical-lots")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH)
def list_chemical_lots():
    chemical_type = query_enum("chemical_type", CHEMICAL_TYPES)
    status = query_enum("status", LOT_STATUSES)
    rows = [r for r in store.chemical_lots.values()
            if match(r, "chemical_type", chemical_type) and match(r, "status", status)]
    return listing(rows, serializers.chemical_lot)


@bp.post(API_PREFIX + "/chemical-lots/<lot_id>/status")
@guard(ROLE_AUDITOR)
def chemical_lot_status(lot_id):
    lot = resolve_path("lot_id", lot_id)
    body = parse_body([F("to_status", "enum", required=True,
                         values=["QUARANTINED", "AVAILABLE", "EXPIRED"])])
    target = body["to_status"]
    current = lot["status"]
    if target == "QUARANTINED":
        if current not in ("AVAILABLE", "DEPLETED"):
            raise_error("ERR_CHEMICAL_LOT_UNAVAILABLE")
    elif target == "AVAILABLE":
        if current != "QUARANTINED":
            raise_error("ERR_CHEMICAL_LOT_UNAVAILABLE")
        if lot["liters_remaining"] < MIN_USABLE_LITERS:
            raise_error("ERR_LOT_RELEASE_BLOCKED")
    else:
        if current not in ("AVAILABLE", "QUARANTINED"):
            raise_error("ERR_CHEMICAL_LOT_UNAVAILABLE")
    lot["status"] = target
    store.touch(lot)
    return object_response(serializers.chemical_lot(lot))


# ---------------------------------------------------------------- catalogue parts

@bp.post(API_PREFIX + "/parts")
@guard(ROLE_DISPATCH)
def create_part():
    body = parse_body([
        F("sku", "str", required=True),
        F("component_type", "enum", required=True, values=COMPONENT_TYPES),
        F("unit_price_cents", "int", required=True, min_value=0),
        F("stock_on_hand", "int", required=True, min_value=0),
        F("brewer_funded_eligible", "bool"),
    ])
    if any(r["sku"] == body["sku"] for r in store.parts.values()):
        raise_error("ERR_INVALID_REQUEST", "sku must be unique across the catalogue.")
    row = store.new_row({
        "sku": body["sku"],
        "component_type": body["component_type"],
        "unit_price_cents": body["unit_price_cents"],
        "stock_on_hand": body["stock_on_hand"],
        "brewer_funded_eligible": bool(body["brewer_funded_eligible"]) if body["brewer_funded_eligible"] is not None else False,
    })
    store.parts[row["id"]] = row
    return object_response(serializers.part(row), 201)


@bp.get(API_PREFIX + "/parts/<part_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH)
def read_part(part_id):
    return object_response(serializers.part(resolve_path("part_id", part_id)))


@bp.get(API_PREFIX + "/parts")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH)
def list_parts():
    component_type = query_enum("component_type", COMPONENT_TYPES)
    eligible = query_bool("brewer_funded_eligible")
    rows = [r for r in store.parts.values()
            if match(r, "component_type", component_type)
            and match(r, "brewer_funded_eligible", eligible)]
    return listing(rows, serializers.part)


# --------------------------------------------------------------- brewer programs

@bp.post(API_PREFIX + "/brewer-programs")
@guard(ROLE_DISPATCH)
def create_program():
    body = parse_body([
        F("brewer_name", "str", required=True, max_len=120),
        F("funded_scope", "enum", required=True, values=FUNDED_SCOPES),
        F("co_pay_bps", "int", required=True, min_value=0, max_value=10000),
        F("funding_cap_cents", "int", required=True, gt=0),
    ])
    row = store.new_row({
        "brewer_name": body["brewer_name"],
        "funded_scope": body["funded_scope"],
        "co_pay_bps": body["co_pay_bps"],
        "funding_cap_cents": body["funding_cap_cents"],
        "consumed_cents": 0,
        "remaining_cents": body["funding_cap_cents"],
        "status": "ACTIVE",
        "end_note": None,
    })
    store.programs[row["id"]] = row
    return object_response(serializers.program(row), 201)


@bp.get(API_PREFIX + "/brewer-programs/<program_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_BREWER)
def read_program(program_id):
    return object_response(serializers.program(resolve_path("program_id", program_id)))


@bp.get(API_PREFIX + "/brewer-programs")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_BREWER)
def list_programs():
    status = query_enum("status", PROGRAM_STATUSES)
    scope = query_enum("funded_scope", FUNDED_SCOPES)
    rows = [r for r in store.programs.values()
            if match(r, "status", status) and match(r, "funded_scope", scope)]
    return listing(rows, serializers.program)


@bp.post(API_PREFIX + "/brewer-programs/<program_id>/cap-adjustment")
@guard(ROLE_BREWER)
def adjust_program_cap(program_id):
    program = resolve_path("program_id", program_id)
    body = parse_body([F("additional_cents", "int", required=True, min_value=1)])
    program["funding_cap_cents"] = int(program["funding_cap_cents"]) + body["additional_cents"]
    store.touch(program)
    settlement.refresh_program_totals(program)
    # Exhaustion is not terminal: fresh headroom revives the programme and
    # re-funds every contract naming it (PRD 3.2).
    if program["status"] == "EXHAUSTED" and int(program["remaining_cents"]) > 0:
        settlement.set_program_status(program, "ACTIVE")
    return object_response(serializers.program(program))


@bp.post(API_PREFIX + "/brewer-programs/<program_id>/end")
@guard(ROLE_BREWER)
def end_program(program_id):
    program = resolve_path("program_id", program_id)
    body = parse_body([F("end_note", "str", required=True)])
    if program["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise_error("ERR_PROGRAM_NOT_ACTIVE")
    program["end_note"] = body["end_note"]
    settlement.set_program_status(program, "ENDED")
    store.touch(program)
    return object_response(serializers.program(program))
