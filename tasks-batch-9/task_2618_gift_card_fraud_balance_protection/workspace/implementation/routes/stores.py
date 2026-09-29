"""Retail stores and card racks (PRD 3.1)."""
from flask import Blueprint

import clock
import db as dbm
import response
import validate
from db import db
from errors import fail
from routes.common import (READ_ROLES, authenticate, filter_by, listing_response,
                           require_rack, require_store, scope_record, scope_store)
from middleware import scope_body_store
from services import stores as store_svc
from services.stores import FLOOR_POSTURES, TAMPER_STATES

bp = Blueprint("stores", __name__)


@bp.post("/stores")
def create_store():
    authenticate(["PlatformAdmin"])
    body = validate.body()
    name = validate.string(body, "name", min_len=1, max_len=120)
    region_code = validate.string(body, "region_code", min_len=2, max_len=2,
                                  pattern=validate.REGION_CODE_RE)
    address_line = validate.string(body, "address_line", min_len=1, max_len=200)
    rec = dbm.record({
        "name": name,
        "region_code": region_code,
        "address_line": address_line,
        "floor_posture": "OPEN",
        "tampered_rack_count": 0,
        "suspect_rack_count": 0,
        "open_alert_count": 0,
        "declined_issuance_count": 0,
    })
    db.stores[rec["id"]] = rec
    return response.created(rec)


@bp.get("/stores")
def list_stores():
    authenticate(READ_ROLES)
    region_code = validate.query_str("region_code")
    floor_posture = validate.query_enum("floor_posture", FLOOR_POSTURES)
    rows = list(db.stores.values())
    rows = filter_by(rows, "region_code", region_code)
    rows = filter_by(rows, "floor_posture", floor_posture)
    return listing_response(rows)


@bp.get("/stores/<store_id>")
def get_store(store_id):
    caller = authenticate(READ_ROLES)
    rec = db.stores.get(store_id)
    if caller.is_store_manager and rec is not None:
        scope_store(caller, rec["id"])
    return response.ok(require_store(store_id))


@bp.post("/card-racks")
def create_rack():
    caller = authenticate(["StoreManager", "PlatformAdmin"])
    scope_body_store(caller)
    body = validate.body()
    store_id = validate.string(body, "store_id", min_len=1)
    rack_label = validate.string(body, "rack_label", min_len=1, max_len=40)
    expected = validate.integer(body, "expected_card_count", minimum=0, maximum=500)
    store = require_store(store_id)
    for existing in db.racks.values():
        if existing["store_id"] == store_id and existing["rack_label"] == rack_label:
            fail("ERR_INVALID_REQUEST", "rack_label is already used on this store.")
    rec = dbm.record({
        "store_id": store_id,
        "rack_label": rack_label,
        "expected_card_count": expected,
        "tamper_state": "INTACT",
        "observed_card_count": None,
        "seal_breaks_observed": 0,
        "missing_card_count": 0,
        "last_audit_at": None,
        "remediation_note": None,
    })
    db.racks[rec["id"]] = rec
    store_svc.touch_store(store)
    return response.created(rec)


@bp.get("/card-racks")
def list_racks():
    authenticate(READ_ROLES)
    store_id = validate.query_str("store_id")
    tamper_state = validate.query_enum("tamper_state", TAMPER_STATES)
    rows = list(db.racks.values())
    rows = filter_by(rows, "store_id", store_id)
    rows = filter_by(rows, "tamper_state", tamper_state)
    return listing_response(rows)


@bp.get("/card-racks/<rack_id>")
def get_rack(rack_id):
    caller = authenticate(READ_ROLES)
    scope_record(caller, db.racks.get(rack_id))
    return response.ok(require_rack(rack_id))


@bp.post("/card-racks/<rack_id>/audits")
def audit_rack(rack_id):
    caller = authenticate(["StoreManager", "PosAssociate"])
    scope_record(caller, db.racks.get(rack_id))
    body = validate.body()
    observed = validate.integer(body, "observed_card_count", minimum=0)
    seal_breaks = validate.integer(body, "seal_breaks_observed", minimum=0)
    rack = require_rack(rack_id)
    policy = dbm.policy()

    rack["observed_card_count"] = observed
    rack["seal_breaks_observed"] = seal_breaks
    rack["last_audit_at"] = clock.now()
    rack["missing_card_count"] = max(0, rack["expected_card_count"] - observed)
    rack["tamper_state"] = store_svc.classify_rack(
        rack["missing_card_count"], seal_breaks, policy
    )
    dbm.touch(rack)

    store = db.stores.get(rack["store_id"])
    if store is not None:
        store_svc.touch_store(store)
        if rack["tamper_state"] == "TAMPERED" and store["floor_posture"] == "SUSPENDED":
            store_svc.void_inactive_cards(store)
    return response.ok(rack)


@bp.post("/card-racks/<rack_id>/clear-tamper")
def clear_tamper(rack_id):
    caller = authenticate(["StoreManager", "RiskManager"])
    scope_record(caller, db.racks.get(rack_id))
    body = validate.body()
    note = validate.string(body, "remediation_note", min_len=None)
    rack = require_rack(rack_id)
    rack["observed_card_count"] = rack["expected_card_count"]
    rack["seal_breaks_observed"] = 0
    rack["missing_card_count"] = 0
    rack["tamper_state"] = "INTACT"
    rack["remediation_note"] = note
    dbm.touch(rack)
    store = db.stores.get(rack["store_id"])
    if store is not None:
        store_svc.touch_store(store)
    return response.ok(rack)
