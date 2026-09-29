"""WarrantyClaim endpoints (PRD Section 3.9)."""
from flask import Blueprint

import validate
from db import db, insert, touch, ordered
from errors import ApiError
from middleware import authorize, partner_scope
from response import ok, created, ok_list
from routes.helpers import find, maybe, filter_by, require_reason, unique_code
from services import calc, derive
from timeutil import add_days

bp = Blueprint("warranty_claims", __name__)

STATUSES = ("SUBMITTED", "APPROVED", "DENIED", "REVERSED")
READ_ROLES = ("ServicePartnerUser", "WarrantyAdjudicator", "ChannelManager", "PlatformAdmin")
LIVE_COVERAGE = ("ACTIVE", "EXTENDED")


def _require_live_coverage(unit):
    derive.refresh_unit_coverage(unit)
    if unit["service_program_status"] not in LIVE_COVERAGE:
        raise ApiError("ERR_UNIT_COVERAGE_NOT_ACTIVE",
                       "the unit's coverage is %s" % unit["service_program_status"])


def _require_claim_authority(partner, unit):
    authorized = derive.compute_authorized_model_ids(partner)
    if partner["status"] != "AUTHORIZED" or unit["equipment_model_id"] not in authorized:
        raise ApiError("ERR_PARTNER_NOT_AUTHORIZED_FOR_CLAIMS",
                       "the partner is not authorized to file claims for this model")


@bp.post("/warranty-claims")
def file_claim():
    actor = authorize("ServicePartnerUser", "PlatformAdmin")
    payload = validate.body()
    raw_partner_id = payload.get("service_partner_id")
    if isinstance(raw_partner_id, str) and raw_partner_id:
        partner_scope(actor, raw_partner_id)

    connected_unit_id = validate.string_field(payload, "connected_unit_id")
    service_partner_id = validate.string_field(payload, "service_partner_id")
    technician_certification_id = validate.string_field(payload, "technician_certification_id")
    claim_code = validate.string_field(payload, "claim_code", min_len=1, max_len=32)
    parts_cost_cents = validate.int_field(payload, "parts_cost_cents", minimum=0)
    labor_hours = validate.number_field(payload, "labor_hours", gt=0)

    unit = find(db.connected_units, connected_unit_id, "ERR_CONNECTED_RESOURCE_NOT_FOUND")
    partner = find(db.service_partners, service_partner_id, "ERR_CHANNEL_RESOURCE_NOT_FOUND")
    cert = find(db.technician_certifications, technician_certification_id,
                "ERR_CHANNEL_RESOURCE_NOT_FOUND")

    _require_live_coverage(unit)
    _require_claim_authority(partner, unit)

    certified = (cert["service_partner_id"] == service_partner_id
                 and cert["status"] == "PASSED"
                 and cert["expires_on"] is not None
                 and db.clock < cert["expires_on"]
                 and cert["equipment_model_id"] == unit["equipment_model_id"])
    if not certified:
        raise ApiError("ERR_TECHNICIAN_NOT_CERTIFIED",
                       "the named certification does not cover this partner, model or period")

    unique_code(db.warranty_claims, claim_code=claim_code)

    claim = insert(db.warranty_claims, {
        "connected_unit_id": connected_unit_id,
        "service_partner_id": service_partner_id,
        "technician_certification_id": technician_certification_id,
        "claim_code": claim_code,
        "parts_cost_cents": parts_cost_cents,
        "labor_hours": labor_hours,
        "status": "SUBMITTED",
        "coinsurance_pct": None,
        "adjudicated_amount_cents": None,
        "denial_reason": None,
        "adjudicated_by_user_id": None,
    })
    return created(claim)


@bp.get("/warranty-claims")
def list_claims():
    actor = authorize(*READ_ROLES)
    service_partner_id = validate.str_arg("service_partner_id")
    if service_partner_id is not None:
        partner_scope(actor, service_partner_id)
    limit, offset = validate.pagination()
    connected_unit_id = validate.str_arg("connected_unit_id")
    technician_certification_id = validate.str_arg("technician_certification_id")
    status = validate.enum_arg("status", STATUSES)

    items = ordered(db.warranty_claims)
    if actor.is_partner_user:
        items = [c for c in items if c["service_partner_id"] == actor.user_id]
    items = filter_by(items, "connected_unit_id", connected_unit_id)
    items = filter_by(items, "service_partner_id", service_partner_id)
    items = filter_by(items, "technician_certification_id", technician_certification_id)
    items = filter_by(items, "status", status)
    return ok_list(items, limit, offset)


@bp.get("/warranty-claims/<claim_id>")
def get_claim(claim_id):
    actor = authorize(*READ_ROLES)
    probe = maybe(db.warranty_claims, claim_id)
    partner_scope(actor, probe["service_partner_id"] if probe else None)
    claim = find(db.warranty_claims, claim_id, "ERR_WARRANTY_CLAIM_NOT_FOUND")
    return ok(claim)


@bp.post("/warranty-claims/<claim_id>/adjudication")
def adjudicate_claim(claim_id):
    actor = authorize("WarrantyAdjudicator", "PlatformAdmin")
    payload = validate.body()
    decision = validate.enum_field(payload, "decision", ("APPROVE", "DENY"))
    denial_reason = None
    if decision == "DENY":
        denial_reason = require_reason(payload, "denial_reason")

    claim = find(db.warranty_claims, claim_id, "ERR_WARRANTY_CLAIM_NOT_FOUND")
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_STATE_INVALID",
                       "a %s claim cannot be adjudicated" % claim["status"])

    if decision == "DENY":
        claim["status"] = "DENIED"
        claim["denial_reason"] = denial_reason
        claim["adjudicated_by_user_id"] = actor.user_id
        touch(claim)
        return ok(claim)

    unit = db.connected_units[claim["connected_unit_id"]]
    partner = db.service_partners[claim["service_partner_id"]]

    _require_live_coverage(unit)
    _require_claim_authority(partner, unit)

    # pinned evaluation order: utilisation is measured on the PRE-claim ledger
    coinsurance_pct = calc.coinsurance_for(unit["claims_paid_cents"], unit["reserve_initial_cents"])
    amount = calc.adjudicated_amount(claim["parts_cost_cents"], claim["labor_hours"],
                                     unit["service_tier"], coinsurance_pct)
    if amount > unit["reserve_balance_cents"]:
        raise ApiError("ERR_WARRANTY_RESERVE_EXHAUSTED",
                       "the payout %d exceeds the remaining reserve %d"
                       % (amount, unit["reserve_balance_cents"]))

    claim["status"] = "APPROVED"
    claim["coinsurance_pct"] = coinsurance_pct
    claim["adjudicated_amount_cents"] = amount
    claim["adjudicated_by_user_id"] = actor.user_id
    touch(claim)

    unit["reserve_balance_cents"] -= amount
    unit["claims_paid_cents"] += amount
    if unit["reserve_balance_cents"] == 0 and unit["service_program_status"] in LIVE_COVERAGE:
        unit["service_program_status"] = "GRACE"
        unit["grace_expires_on"] = add_days(db.clock, calc.GRACE_PERIOD_DAYS)
        # private bookkeeping: only a reversal of *this* claim can undo the grace hop
        unit["_grace_caused_by_claim_id"] = claim["id"]
    touch(unit)
    return ok(claim)


@bp.post("/warranty-claims/<claim_id>/reversal")
def reverse_claim(claim_id):
    authorize("WarrantyAdjudicator", "PlatformAdmin")
    payload = validate.body()
    require_reason(payload, "reversal_reason")

    claim = find(db.warranty_claims, claim_id, "ERR_WARRANTY_CLAIM_NOT_FOUND")
    if claim["status"] != "APPROVED":
        raise ApiError("ERR_CLAIM_STATE_INVALID",
                       "a %s claim cannot be reversed" % claim["status"])

    unit = db.connected_units[claim["connected_unit_id"]]
    derive.refresh_unit_coverage(unit)
    if unit["service_program_status"] == "VOIDED":
        raise ApiError("ERR_CLAIM_STATE_INVALID",
                       "the unit's coverage has been VOIDED")

    amount = claim["adjudicated_amount_cents"] or 0
    claim["status"] = "REVERSED"
    touch(claim)

    unit["reserve_balance_cents"] += amount
    unit["claims_paid_cents"] -= amount
    # PRD Section 3.9: the GRACE -> ACTIVE return applies only when the unit "had been
    # pushed into GRACE by the very claim now being reversed".
    if unit["service_program_status"] == "GRACE" \
            and unit.get("_grace_caused_by_claim_id") == claim["id"] \
            and unit["reserve_balance_cents"] > 0 \
            and unit["grace_expires_on"] is not None and db.clock < unit["grace_expires_on"]:
        unit["service_program_status"] = "ACTIVE"
        unit["grace_expires_on"] = None
        unit["_grace_caused_by_claim_id"] = None
    touch(unit)
    return ok(claim)
