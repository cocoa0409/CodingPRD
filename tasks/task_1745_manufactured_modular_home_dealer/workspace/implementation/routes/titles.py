"""TitleRecord application, issuance, conversion, surrender (PRD 3.7)."""

from flask import Blueprint

from db import bump, create_record, store
from errors import fail
from middleware import ALL_ROLES, require
from response import ok, ok_list
from services import (bubble_title_event, get_or_404, order_for_unit, ser,
                      unit_open_title_exists)
from validate import Shape, get_body, pagination_params

bp = Blueprint("titles", __name__)

TITLE_TYPES = ["MANUFACTURED_CERTIFICATE", "REAL_PROPERTY_AFFIXED"]
ISSUABLE_UNIT_STATUSES = ("AT_DEALER", "RESERVED", "ON_SITE", "INSTALLED")


def _list(rows):
    limit, offset = pagination_params()
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return ok_list([ser(r) for r in rows[offset:offset + limit]], total, limit, offset)


@bp.post("/home-units/<rid>/title-records")
@require("DealershipAdmin")
def create_title_record(rid, actor_id, actor_role):
    unit = get_or_404(store.home_units, rid, "ERR_HOME_UNIT_NOT_FOUND", "Home unit")
    shape = Shape(get_body())
    shape.req_enum("title_type", TITLE_TYPES)
    shape.req_str("state_code")
    if shape.ok("state_code") and len(shape.value("state_code")) != 2:
        shape._err("state_code", "must be a two-letter code")
    # (17) single open title record per unit
    if unit_open_title_exists(unit["id"]):
        fail("ERR_TITLE_ALREADY_ACTIVE", "Unit already has an APPLIED or ISSUED title record")
    shape.raise_if_errors()
    rec = create_record(store.title_records, {
        "home_unit_id": unit["id"],
        "title_type": shape.value("title_type"),
        "state_code": shape.value("state_code"),
        "status": "APPLIED",
    })
    return ok(ser(rec), 201)


@bp.get("/home-units/<rid>/title-records")
@require(*ALL_ROLES)
def list_title_records(rid, actor_id, actor_role):
    unit = get_or_404(store.home_units, rid, "ERR_HOME_UNIT_NOT_FOUND", "Home unit")
    return _list([t for t in store.title_records.values() if t["home_unit_id"] == unit["id"]])


@bp.get("/title-records/<rid>")
@require(*ALL_ROLES)
def get_title_record(rid, actor_id, actor_role):
    return ok(ser(get_or_404(store.title_records, rid, "ERR_TITLE_RECORD_NOT_FOUND",
                             "Title record")))


def _get_title(rid):
    return get_or_404(store.title_records, rid, "ERR_TITLE_RECORD_NOT_FOUND", "Title record")


@bp.post("/title-records/<rid>/issue")
@require("DealershipAdmin")
def issue_title(rid, actor_id, actor_role):
    rec = _get_title(rid)
    if rec["status"] != "APPLIED":
        fail("ERR_INVALID_STATE", "Only an APPLIED title record can be issued")
    unit = store.home_units.get(rec["home_unit_id"])
    if unit is None or unit["status"] not in ISSUABLE_UNIT_STATUSES:
        fail("ERR_INVALID_STATE", "Unit status does not permit title issuance")
    rec["status"] = "ISSUED"
    bump(rec)
    order = order_for_unit(unit)
    if (order is not None and order["deal_status"] == "SET_COMPLETE"
            and order["financing_type"] == "CHATTEL"):
        bubble_title_event(unit)
    return ok(ser(rec))


@bp.post("/title-records/<rid>/convert")
@require("DealershipAdmin")
def convert_title(rid, actor_id, actor_role):
    rec = _get_title(rid)
    # (7) state preconditions: ISSUED record; unit INSTALLED
    if rec["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", "Only an ISSUED title record can be converted")
    unit = store.home_units.get(rec["home_unit_id"])
    if unit is None or unit["status"] != "INSTALLED":
        fail("ERR_INVALID_STATE", "Unit must be INSTALLED for conversion")
    # (28) financing-type coherence: conversion targets real-property deals
    order = order_for_unit(unit)
    if order is None or order["financing_type"] != "REAL_PROPERTY":
        fail("ERR_FINANCING_TYPE_INCOMPATIBLE",
             "Title conversion requires a REAL_PROPERTY order")
    rec["status"] = "CONVERTED"
    rec["title_type"] = "REAL_PROPERTY_AFFIXED"
    bump(rec)
    bubble_title_event(unit)
    return ok(ser(rec))


@bp.post("/title-records/<rid>/surrender")
@require("DealershipAdmin")
def surrender_title(rid, actor_id, actor_role):
    rec = _get_title(rid)
    if rec["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", "Only an ISSUED title record can be surrendered")
    unit = store.home_units.get(rec["home_unit_id"])
    if unit is None or unit["unit_kind"] != "TRADE_IN":
        fail("ERR_INVALID_STATE", "Surrender exists for trade-in units only")
    rec["status"] = "SURRENDERED"
    bump(rec)
    return ok(ser(rec))
