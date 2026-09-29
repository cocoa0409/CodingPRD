"""Carrier registration and reads (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import db
import lookup
from consts import ALL_ROLES, CAPACITY_STATES, CHRONIC_STATES, CIRCUIT_OPERATIONAL_STATES, MONITORING_STATES, REVIEW_DECISIONS
from db import base_record, rows
from errors import fail
from middleware import authenticate, scope_read
from routes._common import send, send_list
from valid import body, opt_decimal, opt_int, q_enum, req_string

bp = Blueprint("carriers", __name__)


@bp.post("/carriers")
def create_carrier():
    authenticate("PlatformAdmin")
    payload = body()
    name = req_string(payload, "name")
    carrier_code = req_string(payload, "carrier_code")
    if not (2 <= len(carrier_code) <= 12):
        fail("ERR_INVALID_REQUEST", "carrier_code must be between 2 and 12 characters.")
    escalation_tier_count = opt_int(payload, "escalation_tier_count", 3, 1, 3)
    sla_critical = opt_int(payload, "sla_restore_minutes_critical", 240, 1)
    sla_standard = opt_int(payload, "sla_restore_minutes_standard", 480, 1)
    credit_pct_per_breach_hour = opt_decimal(
        payload, "credit_pct_per_breach_hour", Decimal("5.0"), 0, 25, exclusive_min=True
    )
    credit_pct_cap = opt_decimal(
        payload, "credit_pct_cap", Decimal("50.0"), 0, 100, exclusive_min=True
    )
    min_claim_amount_cents = opt_int(payload, "min_claim_amount_cents", 5000, 0)
    tier_escalation_min_minutes = opt_int(payload, "tier_escalation_min_minutes", 60, 0)
    watchlist_threshold = opt_int(payload, "watchlist_exposure_threshold_cents", 100000, 1)

    for existing in db.db.carriers.values():
        if existing["carrier_code"] == carrier_code:
            fail("ERR_CARRIER_CODE_DUPLICATE")

    carrier = base_record()
    carrier.update(
        {
            "name": name,
            "carrier_code": carrier_code,
            "escalation_tier_count": escalation_tier_count,
            "sla_restore_minutes_critical": sla_critical,
            "sla_restore_minutes_standard": sla_standard,
            "credit_pct_per_breach_hour": credit_pct_per_breach_hour,
            "credit_pct_cap": credit_pct_cap,
            "min_claim_amount_cents": min_claim_amount_cents,
            "tier_escalation_min_minutes": tier_escalation_min_minutes,
            "watchlist_exposure_threshold_cents": watchlist_threshold,
            "open_credit_exposure_cents": 0,
            "committed_upgrade_mbps": 0,
            "watchlist_state": "ACTIVE",
            "chronic_circuit_count": 0,
        }
    )
    db.db.carriers[carrier["id"]] = carrier
    return send(carrier, 201)


@bp.get("/carriers/<id>")
def get_carrier(id):
    authenticate(ALL_ROLES)
    carrier = lookup.carrier(id)
    scope_read(carrier["id"])
    return send(carrier)


@bp.get("/carriers/<id>/circuits")
def list_carrier_circuits(id):
    authenticate(ALL_ROLES)
    carrier = lookup.carrier(id)
    scope_read(carrier["id"])
    monitoring_state = q_enum("monitoring_state", MONITORING_STATES)
    operational_state = q_enum("operational_state", CIRCUIT_OPERATIONAL_STATES)
    chronic_state = q_enum("chronic_state", CHRONIC_STATES)
    capacity_state = q_enum("capacity_state", CAPACITY_STATES)
    result = []
    for circuit in rows(db.db.circuits):
        if circuit["carrier_id"] != carrier["id"]:
            continue
        if monitoring_state and circuit["monitoring_state"] != monitoring_state:
            continue
        if operational_state and circuit["operational_state"] != operational_state:
            continue
        if chronic_state and circuit["chronic_state"] != chronic_state:
            continue
        if capacity_state and circuit["capacity_state"] != capacity_state:
            continue
        result.append(circuit)
    return send_list(result)


@bp.get("/carriers/<id>/vendor-reviews")
def list_carrier_reviews(id):
    authenticate("NocShiftLead", "VendorManager", "PlatformAdmin")
    carrier = lookup.carrier(id)
    decision = q_enum("decision", REVIEW_DECISIONS)
    result = [
        review
        for review in rows(db.db.reviews)
        if review["carrier_id"] == carrier["id"]
        and (decision is None or review["decision"] == decision)
    ]
    return send_list(result)
