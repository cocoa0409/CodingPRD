"""Serialized cases and units (PRD §3.3): commissioning and aggregation."""
from flask import Blueprint

import db
import errors
from db import store
from errors import ApiError
from middleware import endpoint, ALL_ROLES
from response import ok, created, Paginator
from validation import (get_body, req_str, req_datetime, body_fk, path_entity)

bp = Blueprint("serialization", __name__)


@bp.route("/wholesale/serialized-cases", methods=["POST"])
@endpoint(["WarehouseOperator"])
def create_case():
    body = get_body()
    sscc = req_str(body, "sscc")
    product = body_fk(body, "product_id", store.products, "Product")
    lot_number = req_str(body, "lot_number")
    expiry_date = req_datetime(body, "expiry_date")
    if any(c["sscc"] == sscc for c in store.serialized_cases.values()):
        raise ApiError(errors.ERR_DUPLICATE_UNIQUE_FIELD[0], errors.ERR_DUPLICATE_UNIQUE_FIELD[1],
                       "sscc must be unique across SerializedCase")
    case = {
        "id": db.new_id(),
        "sscc": sscc,
        "product_id": product["id"],
        "lot_number": lot_number,
        "expiry_date": expiry_date,
        "case_status": "COMMISSIONED",
        "quarantine_link_id": None,
        "_pre_quarantine_status": None,
    }
    db.new_common(case)
    store.serialized_cases[case["id"]] = case
    return created(case)


@bp.route("/wholesale/serialized-cases", methods=["GET"])
@endpoint(ALL_ROLES)
def list_cases():
    pg = Paginator()
    rows = list(store.serialized_cases.values())
    rows = pg.filter(rows, "product_id")
    rows = pg.filter(rows, "case_status")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.route("/wholesale/serialized-cases/<caseId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_case(caseId):
    case = path_entity(store.serialized_cases, caseId, "SerializedCase")
    return ok(case)


@bp.route("/wholesale/serialized-cases/<caseId>/units", methods=["GET"])
@endpoint(ALL_ROLES)
def list_case_units(caseId):
    case = path_entity(store.serialized_cases, caseId, "SerializedCase")
    pg = Paginator()
    rows = [u for u in store.serialized_units.values() if u["case_id"] == case["id"]]
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.route("/wholesale/serialized-units", methods=["POST"])
@endpoint(["WarehouseOperator"])
def create_unit():
    body = get_body()
    sni = req_str(body, "sni")
    case = body_fk(body, "case_id", store.serialized_cases, "SerializedCase")
    if any(u["sni"] == sni for u in store.serialized_units.values()):
        raise ApiError(errors.ERR_DUPLICATE_UNIQUE_FIELD[0], errors.ERR_DUPLICATE_UNIQUE_FIELD[1],
                       "sni must be unique across SerializedUnit")
    unit = {
        "id": db.new_id(),
        "sni": sni,
        "case_id": case["id"],
        "unit_status": "COMMISSIONED",
    }
    db.new_common(unit)
    store.serialized_units[unit["id"]] = unit
    return created(unit)


@bp.route("/wholesale/serialized-units", methods=["GET"])
@endpoint(ALL_ROLES)
def list_units():
    pg = Paginator()
    rows = list(store.serialized_units.values())
    rows = pg.filter(rows, "case_id")
    rows = pg.filter(rows, "unit_status")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.route("/wholesale/serialized-units/<unitId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_unit(unitId):
    unit = path_entity(store.serialized_units, unitId, "SerializedUnit")
    return ok(unit)
