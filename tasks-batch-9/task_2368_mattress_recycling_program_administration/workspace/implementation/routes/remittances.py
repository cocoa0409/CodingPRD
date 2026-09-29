"""Registrants, quarterly remittances, exemption claims and the audit cycle."""

from flask import Blueprint, g

import calc
import response
import services
from db import clock, db
from errors import ApiError
from middleware import (ADMIN, AUDITOR, REGISTRANT, auth, get_claim, get_program,
                        get_registrant, get_remittance, own)
from util import (F, apply_filters, base_record, iso_ms, pagination, paginate,
                  parse_dt, public, sort_records, touch, validate_body)

bp = Blueprint("remittances", __name__)

QUARTER_BOUNDS = {
    "1": ((1, 1), (3, 31)),
    "2": ((4, 1), (6, 30)),
    "3": ((7, 1), (9, 30)),
    "4": ((10, 1), (12, 31)),
}


def _period_window(period_code):
    year = int(period_code[0:4])
    quarter = period_code[5]
    (sm, sd), (em, ed) = QUARTER_BOUNDS[quarter]
    start = "%04d-%02d-%02dT00:00:00.000Z" % (year, sm, sd)
    end = "%04d-%02d-%02dT23:59:59.999Z" % (year, em, ed)
    return start, end


# --------------------------------------------------------------------------
# Registrants
# --------------------------------------------------------------------------
@bp.post("/registrants")
def create_registrant():
    auth([ADMIN])
    body = validate_body([
        F("legal_name", "string"),
        F("registrant_type", "enum", enum=["MANUFACTURER", "RETAILER", "BOTH"]),
        F("home_state_code", "string", pattern=r"^[A-Z]{2}$"),
    ])
    rec = base_record()
    rec.update({
        "legal_name": body["legal_name"],
        "registrant_type": body["registrant_type"],
        "home_state_code": body["home_state_code"],
        "compliance_status": "COMPLIANT",
        "delinquent_balance_cents": 0,
        "takeback_breach_count": 0,
    })
    db.registrants[rec["id"]] = rec
    return response.obj(public(rec), 201)


@bp.get("/registrants/<registrant_id>")
def read_registrant(registrant_id):
    auth([ADMIN, AUDITOR, REGISTRANT])
    registrant = get_registrant(registrant_id)
    if g.role == REGISTRANT:
        own(registrant["id"])
    return response.obj(public(registrant))


# --------------------------------------------------------------------------
# Remittances
# --------------------------------------------------------------------------
@bp.post("/sales-remittances")
def create_remittance():
    auth([REGISTRANT])
    body = validate_body([
        F("registrant_id", "string"),
        F("state_program_id", "string"),
        F("period_code", "string", pattern=r"^[0-9]{4}Q[1-4]$"),
        F("units_sold_mattress", "int", minimum=0),
        F("units_sold_foundation", "int", minimum=0),
    ])
    registrant = get_registrant(body["registrant_id"])
    program = get_program(body["state_program_id"])
    own(registrant["id"])

    for existing in db.sales_remittances.values():
        if (existing["registrant_id"] == registrant["id"]
                and existing["state_program_id"] == program["id"]
                and existing["period_code"] == body["period_code"]
                and existing["amends_remittance_id"] is None):
            raise ApiError("ERR_DUPLICATE_REMITTANCE_PERIOD")

    rec = _new_remittance(registrant["id"], program["id"], body["period_code"],
                          body["units_sold_mattress"], body["units_sold_foundation"], None)
    return response.obj(public(rec), 201)


def _new_remittance(registrant_id, program_id, period_code, units_mattress,
                    units_foundation, amends_id):
    start, end = _period_window(period_code)
    rec = base_record()
    rec.update({
        "registrant_id": registrant_id,
        "state_program_id": program_id,
        "amends_remittance_id": amends_id,
        "period_code": period_code,
        "period_start": start,
        "period_end": end,
        "units_sold_mattress": units_mattress,
        "units_sold_foundation": units_foundation,
        "amendment_round": 0,
        "filed_at": None,
        "early_filing_qualified": False,
        "fee_self_assessed_cents": 0,
        "fee_reconciled_cents": None,
        "fee_paid_cents": 0,
        "fee_refunded_cents": 0,
        "balance_due_cents": 0,
        "status": "DRAFT",
        "audit_opened_by_user_id": None,
        "amendment_requested_by_user_id": None,
    })
    db.sales_remittances[rec["id"]] = rec
    return rec


@bp.get("/sales-remittances/<remittance_id>")
def read_remittance(remittance_id):
    auth([ADMIN, AUDITOR, REGISTRANT])
    remittance = get_remittance(remittance_id)
    if g.role == REGISTRANT:
        own(remittance["registrant_id"])
    return response.obj(public(remittance))


@bp.get("/sales-remittances")
def list_remittances():
    auth([ADMIN, AUDITOR, REGISTRANT])
    limit, offset = pagination()
    records = sort_records(list(db.sales_remittances.values()))
    records = apply_filters(records, [
        ("registrant_id", "registrant_id"),
        ("state_program_id", "state_program_id"),
        ("amends_remittance_id", "amends_remittance_id"),
        ("status", "status"),
        ("period_code", "period_code"),
    ])
    window, total = paginate(records, limit, offset)
    return response.arr([public(r) for r in window], limit, offset, total)


# --------------------------------------------------------------------------
# Exemption claims
# --------------------------------------------------------------------------
@bp.post("/sales-remittances/<remittance_id>/exemption-claims")
def create_claim(remittance_id):
    auth([REGISTRANT])
    body = validate_body([
        F("claim_type", "enum", enum=["EXEMPT_SALE", "OUT_OF_STATE_SHIPMENT"]),
        F("unit_class", "enum", enum=["MATTRESS", "FOUNDATION"]),
        F("units", "int", minimum=1),
        F("documentation_reference", "string", required=False, nullable=True),
    ])
    remittance = get_remittance(remittance_id)
    own(remittance["registrant_id"])

    if remittance["status"] != "DRAFT":
        raise ApiError("ERR_REMITTANCE_NOT_DRAFT")

    units_sold = (remittance["units_sold_foundation"] if body["unit_class"] == "FOUNDATION"
                  else remittance["units_sold_mattress"])
    already = sum(c["units"] for c in calc.claims_of(remittance["id"])
                  if c["unit_class"] == body["unit_class"]
                  and c["status"] in ("PENDING", "SUBSTANTIATED"))
    if already + body["units"] > units_sold:
        raise ApiError("ERR_EXEMPT_UNITS_EXCEED_SALES")

    rec = base_record()
    rec.update({
        "remittance_id": remittance["id"],
        "claim_type": body["claim_type"],
        "unit_class": body["unit_class"],
        "units": body["units"],
        "documentation_reference": body.get("documentation_reference"),
        "status": "PENDING",
        "adjudicated_by_user_id": None,
        "disallow_reason": None,
    })
    db.exemption_claims[rec["id"]] = rec
    return response.obj(public(rec), 201)


@bp.get("/sales-remittances/<remittance_id>/exemption-claims")
def list_claims(remittance_id):
    auth([ADMIN, AUDITOR, REGISTRANT])
    limit, offset = pagination()
    remittance = get_remittance(remittance_id)
    if g.role == REGISTRANT:
        own(remittance["registrant_id"])
    records = sort_records(calc.claims_of(remittance["id"]))
    records = apply_filters(records, [("status", "status")])
    window, total = paginate(records, limit, offset)
    return response.arr([public(r) for r in window], limit, offset, total)


@bp.post("/exemption-claims/<claim_id>/adjudicate")
def adjudicate(claim_id):
    auth([AUDITOR])
    body = validate_body([
        F("decision", "enum", enum=["SUBSTANTIATE", "DISALLOW"]),
        F("disallow_reason", "enum", required=False, nullable=True,
          enum=["MISSING_DOCUMENTATION", "UNITS_UNSUPPORTED", "OUT_OF_SCOPE"]),
    ])
    claim = get_claim(claim_id)
    remittance = db.sales_remittances[claim["remittance_id"]]

    if body["decision"] == "DISALLOW" and not body.get("disallow_reason"):
        raise ApiError("ERR_INVALID_REQUEST",
                       "disallow_reason is required when disallowing a claim.")

    if claim["status"] != "PENDING" or remittance["status"] != "UNDER_AUDIT":
        raise ApiError("ERR_CLAIM_ALREADY_ADJUDICATED")

    if body["decision"] == "SUBSTANTIATE":
        if claim["documentation_reference"] is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "An undocumented claim cannot be substantiated.")
        claim["status"] = "SUBSTANTIATED"
        claim["adjudicated_by_user_id"] = g.user_id
    else:
        claim["status"] = "DISALLOWED"
        claim["adjudicated_by_user_id"] = g.user_id
        claim["disallow_reason"] = body["disallow_reason"]
    touch(claim)
    return response.obj(public(claim))


# --------------------------------------------------------------------------
# Remittance lifecycle
# --------------------------------------------------------------------------
@bp.post("/sales-remittances/<remittance_id>/file")
def file_remittance(remittance_id):
    auth([REGISTRANT])
    remittance = get_remittance(remittance_id)
    own(remittance["registrant_id"])

    if remittance["status"] != "DRAFT":
        raise ApiError("ERR_REMITTANCE_NOT_DRAFT")

    registrant = db.registrants[remittance["registrant_id"]]
    if registrant["compliance_status"] == "SUSPENDED":
        raise ApiError("ERR_REGISTRANT_SUSPENDED")

    if not calc.remittance_rate_available(remittance):
        raise ApiError("ERR_NO_APPLICABLE_RATE")

    remittance["filed_at"] = clock.stamp()
    remittance["early_filing_qualified"] = calc.is_early_filing(
        clock.now(), parse_dt(remittance["period_end"]))
    remittance["fee_self_assessed_cents"] = calc.remittance_fee_assessment(
        remittance, "SELF_ASSESSED")
    remittance["status"] = "FILED"
    touch(remittance)
    return response.obj(public(remittance))


@bp.post("/sales-remittances/<remittance_id>/pay")
def pay(remittance_id):
    auth([REGISTRANT])
    body = validate_body([F("amount_cents", "int")])
    remittance = get_remittance(remittance_id)
    own(remittance["registrant_id"])

    if remittance["status"] != "FILED":
        raise ApiError("ERR_REMITTANCE_NOT_PAYABLE")

    if body["amount_cents"] != remittance["fee_self_assessed_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")

    remittance["fee_paid_cents"] = body["amount_cents"]
    remittance["status"] = "PAID"
    touch(remittance)
    services.refresh_program_and_touch(db.state_programs[remittance["state_program_id"]])
    return response.obj(public(remittance))


@bp.post("/sales-remittances/<remittance_id>/refund")
def refund(remittance_id):
    auth([ADMIN])
    body = validate_body([F("amount_cents", "int"), F("reason", "string")])
    remittance = get_remittance(remittance_id)

    if remittance["status"] != "PAID":
        raise ApiError("ERR_REMITTANCE_NOT_PAID")

    program = db.state_programs[remittance["state_program_id"]]
    if program["enforcement_posture"] != "NORMAL":
        raise ApiError("ERR_PROGRAM_POSTURE_ELEVATED")

    net = remittance["fee_paid_cents"] - remittance["fee_refunded_cents"]
    if body["amount_cents"] > net:
        raise ApiError("ERR_REFUND_EXCEEDS_PAYMENT")

    remittance["fee_refunded_cents"] += body["amount_cents"]
    remittance["status"] = "REFUNDED"
    touch(remittance)
    services.refresh_program_and_touch(program)
    return response.obj(public(remittance))


@bp.post("/sales-remittances/<remittance_id>/audit-open")
def audit_open(remittance_id):
    auth([AUDITOR])
    remittance = get_remittance(remittance_id)
    if remittance["status"] != "PAID":
        raise ApiError("ERR_REMITTANCE_NOT_PAID")
    remittance["status"] = "UNDER_AUDIT"
    remittance["audit_opened_by_user_id"] = g.user_id
    touch(remittance)
    return response.obj(public(remittance))


@bp.post("/sales-remittances/<remittance_id>/request-amendment")
def request_amendment(remittance_id):
    auth([AUDITOR])
    body = validate_body([F("note", "string")])
    remittance = get_remittance(remittance_id)

    if remittance["status"] != "UNDER_AUDIT":
        raise ApiError("ERR_REMITTANCE_NOT_UNDER_AUDIT")
    if remittance["amendment_round"] >= 2:
        raise ApiError("ERR_AMENDMENT_LIMIT_EXCEEDED")

    del body
    remittance["status"] = "AMENDMENT_REQUIRED"
    remittance["amendment_requested_by_user_id"] = g.user_id
    touch(remittance)
    return response.obj(public(remittance))


@bp.post("/sales-remittances/<remittance_id>/amendments")
def submit_amendment(remittance_id):
    auth([REGISTRANT])
    body = validate_body([
        F("units_sold_mattress", "int", minimum=0),
        F("units_sold_foundation", "int", minimum=0),
        F("expected_remittance_version", "int"),
    ])
    remittance = get_remittance(remittance_id)
    own(remittance["registrant_id"])

    if body["expected_remittance_version"] != remittance["version"]:
        raise ApiError("ERR_STALE_REMITTANCE_VERSION")

    if remittance["status"] != "AMENDMENT_REQUIRED":
        raise ApiError("ERR_REMITTANCE_NOT_UNDER_AUDIT")
    if remittance["amendment_round"] >= 2:
        raise ApiError("ERR_AMENDMENT_LIMIT_EXCEEDED")

    remittance["amendment_round"] += 1
    remittance["status"] = "UNDER_AUDIT"
    touch(remittance)

    _new_remittance(remittance["registrant_id"], remittance["state_program_id"],
                    remittance["period_code"], body["units_sold_mattress"],
                    body["units_sold_foundation"], remittance["id"])
    return response.obj(public(remittance), 201)


@bp.post("/sales-remittances/<remittance_id>/audit-close")
def audit_close(remittance_id):
    auth([AUDITOR])
    remittance = get_remittance(remittance_id)

    requester = remittance["amendment_requested_by_user_id"]
    if requester is not None and g.user_id == requester:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The auditor that requested the amendment may not close this audit.")

    if remittance["status"] != "UNDER_AUDIT":
        raise ApiError("ERR_REMITTANCE_NOT_UNDER_AUDIT")

    if any(c["status"] == "PENDING" for c in calc.claims_of(remittance["id"])):
        raise ApiError("ERR_PENDING_EXEMPTION_CLAIMS")

    reconciled = calc.remittance_fee_assessment(remittance, "AUDIT_RECONCILED")
    net_cash = remittance["fee_paid_cents"] - remittance["fee_refunded_cents"]
    balance_due = max(0, reconciled - net_cash)

    remittance["fee_reconciled_cents"] = reconciled
    remittance["balance_due_cents"] = balance_due
    remittance["status"] = "AUDIT_CLOSED"
    touch(remittance)

    if balance_due > 0:
        registrant = db.registrants[remittance["registrant_id"]]
        services.refresh_registrant(registrant)
        touch(registrant)
        services.refresh_program_and_touch(
            db.state_programs[remittance["state_program_id"]])

    return response.obj(public(remittance))
