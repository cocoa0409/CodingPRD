"""Direct-bill invoices: ingestion fork, audit decisions, settlement."""
from flask import Blueprint, request

import db
from errors import api_error, bad_request
from middleware import ALL_ROLES, require_roles
from response import ok, paginate
from services import (audited_charge_final, bump, check_body_fk,
                      claim_of_reservation, create_communication_log,
                      create_recovery_case, get_reservation,
                      invoice_auto_approved, new_entity, need_date, need_int,
                      need_str, require_claim_open, sorted_by_creation, view)

bp = Blueprint("invoices", __name__)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def get_invoice(invoice_id):
    inv = db.invoices.get(invoice_id)
    if inv is None:
        raise api_error("ERR_INVOICE_NOT_FOUND", 404, "invoice not found: %s" % invoice_id)
    return inv


@bp.post("/invoices")
def create_invoice():
    caller = require_roles(["RentalPartner"])
    b = body()
    # rung 4: body FK existence
    check_body_fk(b, "reservation_id", db.reservations, "ERR_RESERVATION_NOT_FOUND")
    # shape
    reservation_id = b.get("reservation_id")
    if not isinstance(reservation_id, str) or not reservation_id:
        raise bad_request("reservation_id is required")
    invoice_number = need_str(b, "invoice_number")
    period_start = need_date(b, "period_start")
    period_end = need_date(b, "period_end")
    daily_rate = need_int(b, "daily_rate_cents")
    if daily_rate <= 0:
        raise bad_request("daily_rate_cents must be greater than zero")
    tax = need_int(b, "tax_cents")
    if tax < 0:
        raise bad_request("tax_cents may not be negative")
    fees = need_int(b, "fees_cents")
    if fees < 0:
        raise bad_request("fees_cents may not be negative")
    res = db.reservations[reservation_id]
    # rung 5: caller partner must own the reservation
    if res["rental_partner_id"] != caller.id:
        raise api_error("ERR_NOT_RESOURCE_OWNER", 403,
                        "caller partner does not own this reservation")
    claim = claim_of_reservation(res)
    # rung 6
    require_claim_open(claim)
    # rung 8
    if res["status"] not in ("ACTIVE", "EXTENSION_REVIEW", "RETURNED"):
        raise api_error("ERR_RESERVATION_INVALID_STATE", 409,
                        "reservation must be ACTIVE, EXTENSION_REVIEW, or RETURNED to be invoiced")
    # rung 10
    if period_end <= period_start:
        raise api_error("ERR_INVALID_PERIOD", 400,
                        "period_end must be strictly later than period_start")
    # rung 12: invoice number unique per partner
    for inv in db.invoices.values():
        if inv["rental_partner_id"] == caller.id and inv["invoice_number"] == invoice_number:
            raise api_error("ERR_DUPLICATE_INVOICE_NUMBER", 409,
                            "invoice_number already used by this rental partner")
    days = (period_end - period_start).days
    e = new_entity()
    e.update({
        "reservation_id": reservation_id,
        "rental_partner_id": caller.id,
        "invoice_number": invoice_number,
        "period_start": period_start,
        "period_end": period_end,
        "daily_rate_cents": daily_rate,
        "tax_cents": tax,
        "fees_cents": fees,
        "total_cents": days * daily_rate + tax + fees,
        "_recovery_case_id": None,
    })
    audited, unauthorized = audited_charge_final(e, res, claim)
    e["unauthorized_days"] = unauthorized
    if invoice_auto_approved(e, res, claim):
        e["status"] = "AUTO_APPROVED"
        e["audited_payable_cents"] = audited
    else:
        e["status"] = "MANUAL_REVIEW"
        e["audited_payable_cents"] = None
    db.invoices[e["id"]] = e
    return ok(view(e), status=201)


@bp.get("/invoices")
def list_invoices():
    require_roles(ALL_ROLES)
    items = list(db.invoices.values())
    partner_filter = request.args.get("rental_partner_id")
    if partner_filter is not None:
        items = [i for i in items if i["rental_partner_id"] == partner_filter]
    page, meta = paginate(sorted_by_creation(items), request.args)
    return ok([view(i) for i in page], response_type="array", pagination=meta)


@bp.get("/invoices/<iid>")
def get_one_invoice(iid):
    require_roles(ALL_ROLES)
    return ok(view(get_invoice(iid)))


@bp.post("/invoices/<iid>/audit-decision")
def audit_decision(iid):
    require_roles(["ClaimsAdjuster"])
    inv = get_invoice(iid)
    b = body()
    decision = b.get("decision")
    if decision not in ("APPROVE_AS_SUBMITTED", "ADJUST_TO_AUTHORIZED", "DISPUTE_UNNECESSARY_DAYS"):
        raise bad_request("decision must be APPROVE_AS_SUBMITTED, ADJUST_TO_AUTHORIZED, or DISPUTE_UNNECESSARY_DAYS")
    res = db.reservations[inv["reservation_id"]]
    claim = claim_of_reservation(res)
    require_claim_open(claim)
    if inv["status"] != "MANUAL_REVIEW":
        raise api_error("ERR_INVOICE_INVALID_STATE", 409,
                        "only a MANUAL_REVIEW invoice can be audited")
    if decision == "APPROVE_AS_SUBMITTED":
        inv["audited_payable_cents"] = inv["total_cents"]
        inv["status"] = "AUTO_APPROVED"
        bump(inv)
    elif decision == "ADJUST_TO_AUTHORIZED":
        audited, _ = audited_charge_final(inv, res, claim)
        inv["audited_payable_cents"] = audited
        inv["status"] = "AUTO_APPROVED"
        bump(inv)
    else:  # DISPUTE_UNNECESSARY_DAYS
        inv["status"] = "DISPUTED"
        bump(inv)
        assessed = inv["unauthorized_days"] * min(inv["daily_rate_cents"],
                                                  claim["coverage_daily_limit_cents"])
        rc = create_recovery_case(claim, res, "INVOICE_DISPUTE",
                                  inv["unauthorized_days"], assessed)
        inv["_recovery_case_id"] = rc["id"]
        bump(claim)
        create_communication_log(claim["id"], "EMAIL", "RECOVERY_NOTICE",
                                 "Invoice disputed; unnecessary-day recovery opened.")
    return ok(view(inv))


@bp.post("/invoices/<iid>/settle")
def settle_invoice(iid):
    require_roles(["SettlementApprover"])
    inv = get_invoice(iid)
    res = db.reservations[inv["reservation_id"]]
    claim = claim_of_reservation(res)
    # rung 6
    require_claim_open(claim)
    # rung 8
    if inv["status"] == "DISPUTED":
        rc = db.recovery_cases.get(inv["_recovery_case_id"] or "")
        if rc is None or rc["status"] not in ("CLOSED", "WAIVED"):
            raise api_error("ERR_INVOICE_INVALID_STATE", 409,
                            "the dispute's recovery case is not resolved")
    elif inv["status"] != "AUTO_APPROVED":
        raise api_error("ERR_INVOICE_INVALID_STATE", 409,
                        "only an AUTO_APPROVED or resolved DISPUTED invoice can be settled")
    inv["status"] = "SETTLED"
    bump(inv)
    bump(res)
    bump(claim)
    return ok(view(inv))
