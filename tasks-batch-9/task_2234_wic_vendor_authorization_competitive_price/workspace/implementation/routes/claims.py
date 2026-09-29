"""Redemption claim and claim line endpoints (PRD §3.7)."""

from flask import Blueprint

import calc
import clock
import config as C
import envelope
import models
import services
import validators
from auth import authenticate, check_vendor_scope
from errors import ApiError
from routes.common import body_fk, listing, need
from store import db, ordered

bp = Blueprint("claims", __name__)

READ_ROLES = (C.ROLE_ANALYST, C.ROLE_SUPERVISOR, C.ROLE_VENDOR_OPERATOR)


@bp.post("/redemption-claims")
def create_claim():
    caller = authenticate(C.ROLE_VENDOR_OPERATOR)
    payload = validators.body()
    raw_vendor = payload.get("vendor_id")
    if isinstance(raw_vendor, str):
        check_vendor_scope(caller, raw_vendor)

    vendor = body_fk(payload, "vendor_id", db.vendors, "ERR_VENDOR_NOT_FOUND")
    vendor_id = validators.req_string(payload, "vendor_id")
    claim_month = validators.req_claim_month(payload, "claim_month")

    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise validators.invalid("Field 'lines' must be a non-empty array.")
    parsed = []
    seen = set()
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise validators.invalid("Each 'lines' entry must be an object.")
        line_number = validators.req_int(entry, "line_number", minimum=1)
        if line_number in seen:
            raise validators.invalid("Field 'line_number' must be unique within the claim.")
        seen.add(line_number)
        parsed.append(
            {
                "line_number": line_number,
                "upc": validators.req_string(entry, "upc"),
                "quantity": validators.req_int(entry, "quantity", minimum=0),
                "charged_unit_price_cents": validators.req_int(
                    entry, "charged_unit_price_cents", minimum=0
                ),
                "medical_doc_on_file": validators.opt_bool(
                    entry, "medical_doc_on_file", default=False
                ),
            }
        )

    if vendor["authorization_status"] not in C.MONITORABLE_STATUSES:
        raise ApiError("ERR_VENDOR_NOT_MONITORABLE")
    if services.disqualification_live(vendor):
        raise ApiError("ERR_VENDOR_DISQUALIFIED")

    claim = models.redemption_claim(vendor_id=vendor_id, claim_month=claim_month)
    db.redemption_claims[claim["id"]] = claim
    total = 0
    for entry in parsed:
        line = models.claim_line(redemption_claim_id=claim["id"], **entry)
        db.claim_lines[line["id"]] = line
        total += entry["quantity"] * entry["charged_unit_price_cents"]
    claim["line_count"] = len(parsed)
    claim["submitted_total_cents"] = total
    return envelope.success(claim, 201)


@bp.get("/redemption-claims/<entity_id>")
def read_claim(entity_id):
    caller = authenticate(*READ_ROLES)
    claim = need(db.redemption_claims, entity_id, "ERR_CLAIM_NOT_FOUND")
    check_vendor_scope(caller, claim["vendor_id"])
    return envelope.success(claim)


@bp.get("/redemption-claims")
def list_claims():
    authenticate(*READ_ROLES)
    return listing(
        ordered(db.redemption_claims),
        {
            "vendor_id": "vendor_id",
            "status": "status",
            "claim_month": "claim_month",
            "governing_price_cycle_id": "governing_price_cycle_id",
        },
    )


@bp.post("/redemption-claims/<entity_id>/adjudicate")
def adjudicate_claim(entity_id):
    authenticate(C.ROLE_ANALYST)
    claim = need(db.redemption_claims, entity_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    governing = calc.published_governing_cycle()
    if governing is None:
        raise ApiError("ERR_NO_PUBLISHED_PRICE_CYCLE")
    vendor = db.vendors.get(claim["vendor_id"])
    services.adjudicate_claim(claim, vendor, governing)
    return envelope.success(claim)


@bp.post("/redemption-claims/<entity_id>/mark-paid")
def mark_paid(entity_id):
    authenticate(C.ROLE_SUPERVISOR)
    claim = need(db.redemption_claims, entity_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] not in ("ADJUDICATED", "ADJUSTED"):
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    services.update(claim, status="PAID", paid_at=clock.now())
    return envelope.success(claim)


@bp.get("/claim-lines/<entity_id>")
def read_line(entity_id):
    caller = authenticate(*READ_ROLES)
    line = need(db.claim_lines, entity_id, "ERR_CLAIM_LINE_NOT_FOUND")
    claim = db.redemption_claims.get(line["redemption_claim_id"])
    if claim is not None:
        check_vendor_scope(caller, claim["vendor_id"])
    return envelope.success(line)


@bp.get("/claim-lines")
def list_lines():
    authenticate(*READ_ROLES)
    return listing(
        ordered(db.claim_lines),
        {
            "redemption_claim_id": "redemption_claim_id",
            "food_item_id": "food_item_id",
            "edit_code": "edit_code",
        },
    )
