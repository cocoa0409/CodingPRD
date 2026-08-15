"""VendorContract endpoints (PRD §3.3)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_CONTRACT_NOT_FOUND,
    ERR_INVALID_TRANSITION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one
from services.core import touch
from services.serializers import serialize_contract
from util import CLOCK, new_id, next_seq
from validate import get_body, reject_unknown_fields, req_int, req_str, require_path

bp = Blueprint("vendor_contracts", __name__)

RATE_FIELDS = (
    "phone_per_minute_cents",
    "video_per_minute_cents",
    "in_person_per_minute_cents",
    "translation_per_word_cents",
    "in_person_travel_flat_cents",
)


@bp.post("/vendor-contracts")
def create_contract():
    authorized(["LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(body, {"vendor_name", "ceiling_cents"} | set(RATE_FIELDS))
    vendor_name = req_str(body, "vendor_name")
    ceiling_cents = req_int(body, "ceiling_cents", positive=True)
    rates = {f: req_int(body, f, non_negative=True) for f in RATE_FIELDS}

    now = CLOCK.now_iso()
    rec = {
        "id": new_id(),
        "vendor_name": vendor_name,
        "ceiling_cents": ceiling_cents,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
        **rates,
    }
    db["vendor_contracts"][rec["id"]] = rec
    return success_object(serialize_contract(rec), status=201)


@bp.get("/vendor-contracts/<rid>")
def get_contract(rid):
    return get_one("vendor_contracts", rid, ERR_CONTRACT_NOT_FOUND, serialize_contract)


@bp.post("/vendor-contracts/<rid>/activate")
def activate_contract(rid):
    authorized(["LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(body, set())
    rec = require_path("vendor_contracts", rid, ERR_CONTRACT_NOT_FOUND)
    if rec["status"] != "DRAFT":
        raise_error(ERR_INVALID_TRANSITION, "only a DRAFT contract may be activated")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success_object(serialize_contract(rec))
