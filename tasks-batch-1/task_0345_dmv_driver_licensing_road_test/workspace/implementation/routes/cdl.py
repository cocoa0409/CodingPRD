"""CDL endorsement, medical card, and fee payment endpoints (PRD 3.8, 3.9)."""
from flask import Blueprint

from db import db as store
from db import ENDORSEMENT_CODES, FEE_PURPOSES
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import serialize
from services.common import (
    new_common, touch, get_json_body, require_fields, require_int,
)
from services.lookup import fetch

bp = Blueprint("cdl", __name__)


@bp.post("/cdl-endorsements")
def grant_endorsement():
    _, role = get_user_context()
    require_role(role, {"LicenseClerk"})
    body = get_json_body()
    require_fields(body, ["driver_record_id", "endorsement_code"])
    driver_record_id = body["driver_record_id"]
    record = fetch(store.driver_records, driver_record_id)
    endorsement_code = body["endorsement_code"]
    if endorsement_code not in ENDORSEMENT_CODES:
        raise err("ERR_INVALID_REQUEST", "invalid endorsement_code")
    cur = store.current_period
    # requires a VALID medical card covering current clock
    has_valid = any(
        m["driver_record_id"] == driver_record_id and m["status"] == "VALID"
        and m["valid_through_period"] >= cur
        for m in store.medical_cards.values()
    )
    if not has_valid:
        raise err("ERR_NO_VALID_MEDICAL_CARD", "A VALID medical card is required")
    # first endorsement cross-dimension guard: licensing_status must be ACTIVE
    if record["cdl_status"] == "NONE":
        if record["licensing_status"] != "ACTIVE":
            raise err("ERR_RECORD_NOT_ACTIVE",
                      "First endorsement requires licensing_status == ACTIVE")
    endorsement = new_common(
        driver_record_id=driver_record_id,
        endorsement_code=endorsement_code,
        status="GRANTED",
    )
    store.cdl_endorsements[endorsement["id"]] = endorsement
    if record["cdl_status"] == "NONE":
        record["cdl_status"] = "ACTIVE"
        touch(record)
    return success(serialize.cdl_endorsement(endorsement), 201, "object")


@bp.post("/cdl-endorsements/<cid>/withdraw")
def withdraw_endorsement(cid):
    _, role = get_user_context()
    require_role(role, {"LicenseClerk", "AdjudicationOfficer"})
    endorsement = fetch(store.cdl_endorsements, cid)
    endorsement["status"] = "WITHDRAWN"
    touch(endorsement)
    return success(serialize.cdl_endorsement(endorsement), 200, "object")


@bp.post("/medical-cards")
def file_medical_card():
    _, role = get_user_context()
    require_role(role, {"LicenseClerk"})
    body = get_json_body()
    require_fields(body, ["driver_record_id", "issued_period", "valid_through_period"])
    driver_record_id = body["driver_record_id"]
    fetch(store.driver_records, driver_record_id)
    issued_period = require_int(body, "issued_period")
    valid_through_period = require_int(body, "valid_through_period")
    # filing supersedes any prior VALID card for the same record
    for m in store.medical_cards.values():
        if m["driver_record_id"] == driver_record_id and m["status"] == "VALID":
            m["status"] = "SUPERSEDED"
            touch(m)
    card = new_common(
        driver_record_id=driver_record_id,
        issued_period=issued_period,
        valid_through_period=valid_through_period,
        status="VALID",
    )
    store.medical_cards[card["id"]] = card
    return success(serialize.medical_card(card), 201, "object")


@bp.post("/fee-payments")
def capture_fee():
    _, role = get_user_context()
    require_role(role, {"LicenseClerk"})
    body = get_json_body()
    require_fields(body, ["driver_record_id", "purpose", "amount_cents"])
    driver_record_id = body["driver_record_id"]
    fetch(store.driver_records, driver_record_id)
    purpose = body["purpose"]
    if purpose not in FEE_PURPOSES:
        raise err("ERR_INVALID_REQUEST", "invalid purpose")
    amount_cents = require_int(body, "amount_cents", minimum=0)
    payment = new_common(
        driver_record_id=driver_record_id,
        purpose=purpose,
        amount_cents=amount_cents,
        status="CAPTURED",
    )
    store.fee_payments[payment["id"]] = payment
    return success(serialize.fee_payment(payment), 201, "object")
