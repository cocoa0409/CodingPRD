"""Public records requests: the disclosure axis and the money axis."""
from flask import Blueprint

import calc
import domain
from core import (ROLE_ANONYMOUS, ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK,
                  ROLE_RECORDS, ROLE_REQUESTER, ApiError, authorize, body_dict,
                  db, fetch, fk, invalid, listing, new_record, now_date, ok,
                  opt_bool, opt_str, q, req_enum, req_int, req_list, req_str,
                  touch)

bp = Blueprint("records", __name__)

VARIANTS = ("ACTUAL_COST", "FLAT_SCHEDULE")
MEDIUMS = ("PAPER", "ELECTRONIC")
DISPOSITIONS = ("FULL_RELEASE", "PARTIAL_RELEASE", "DENIAL")
CLOSED_AXIS = ("CLOSED", "WITHDRAWN")


def _read_fee_lines(body):
    """fee_lines[] with { page_count, staff_minutes, delivery_medium }."""
    raw = req_list(body, "fee_lines")
    lines = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise invalid("Each fee line must be an object.")
        lines.append({
            "page_count": req_int(entry, "page_count", minimum=0),
            "staff_minutes": req_int(entry, "staff_minutes", minimum=0),
            "delivery_medium": req_enum(entry, "delivery_medium", MEDIUMS),
        })
    return lines


def _settle_fee_status(request_rec):
    """After a money movement: balance 0 means PAID when cash was taken."""
    domain.recompute_ledger(request_rec)
    if request_rec["fee_balance_cents"] == 0:
        request_rec["fee_status"] = ("PAID" if request_rec["net_cash_cents"] > 0
                                    else "WAIVED")
    return request_rec


@bp.route("/clerk/records-requests", methods=["POST"])
def create_request():
    authorize((ROLE_ANONYMOUS, ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK))
    body = body_dict()
    series = fk(body, "target_series_id", db.record_series, "ERR_SERIES_NOT_FOUND")
    requester_name = req_str(body, "requester_name")
    requester_email = req_str(body, "requester_email")
    subject = req_str(body, "subject_description")
    commercial = opt_bool(body, "commercial_purpose", default=False)
    intake_on = now_date()
    record = new_record()
    record.update({
        "requester_name": requester_name,
        "requester_email": requester_email,
        "subject_description": subject,
        "target_series_id": series["id"] if series is not None else None,
        "commercial_purpose": commercial,
        "intake_on": intake_on,
        "due_on": calc.records_request_due_date(intake_on),
        "fulfillment_status": "RECEIVED",
        "fee_status": "NOT_ASSESSED",
        "fee_schedule_variant": None,
        "exemption_count": 0,
        "total_assessed_cents": 0,
        "total_waived_cents": 0,
        "total_collected_cents": 0,
        "refunded_cents": 0,
        "fee_balance_cents": 0,
        "net_cash_cents": 0,
        "closed_on": None,
        "denial_basis": None,
    })
    db.requests[record["id"]] = record
    return ok(record, 201)


@bp.route("/clerk/records-requests/<request_id>", methods=["GET"])
def get_request(request_id):
    authorize((ROLE_REQUESTER, ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK, ROLE_RECORDS),
              owner_request_id=request_id)
    return ok(fetch(db.requests, request_id, "ERR_REQUEST_NOT_FOUND"))


@bp.route("/clerk/records-requests", methods=["GET"])
def list_requests():
    authorize((ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK, ROLE_RECORDS))
    return listing(list(db.requests.values()), {
        "target_series_id": q("target_series_id"),
        "fulfillment_status": q("fulfillment_status"),
        "fee_status": q("fee_status"),
    })


# ---------------------------------------------------- disclosure axis
@bp.route("/clerk/records-requests/<request_id>/begin-review", methods=["POST"])
def begin_review(request_id):
    authorize((ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK))
    record = fetch(db.requests, request_id, "ERR_REQUEST_NOT_FOUND")
    if record["fulfillment_status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_REQUEST_STATE", 409)
    record["fulfillment_status"] = "UNDER_REVIEW"
    touch(record)
    return ok(record)


@bp.route("/clerk/records-requests/<request_id>/exemption-review",
          methods=["POST"])
def exemption_review(request_id):
    authorize((ROLE_RECORDS,))
    record = fetch(db.requests, request_id, "ERR_REQUEST_NOT_FOUND")
    body = body_dict()
    claims = req_list(body, "exemption_claims")
    if record["fulfillment_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_REQUEST_STATE", 409)
    record["fulfillment_status"] = "EXEMPTION_REVIEW"
    record["exemption_count"] = len(claims)
    touch(record)
    return ok(record)


@bp.route("/clerk/records-requests/<request_id>/disposition", methods=["POST"])
def record_disposition(request_id):
    authorize((ROLE_CITY_CLERK, ROLE_RECORDS))
    record = fetch(db.requests, request_id, "ERR_REQUEST_NOT_FOUND")
    body = body_dict()
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    denial_basis = opt_str(body, "denial_basis", allow_empty=False)
    if disposition == "DENIAL" and denial_basis is None:
        raise invalid("denial_basis is required for a DENIAL.")
    if disposition == "DENIAL":
        if record["fulfillment_status"] != "EXEMPTION_REVIEW":
            raise ApiError("ERR_INVALID_REQUEST_STATE", 409)
    elif record["fulfillment_status"] not in ("UNDER_REVIEW", "EXEMPTION_REVIEW"):
        raise ApiError("ERR_INVALID_REQUEST_STATE", 409)
    if disposition != "FULL_RELEASE" and record["exemption_count"] < 1:
        raise ApiError("ERR_DENIAL_WITHOUT_EXEMPTION", 422)
    if disposition == "FULL_RELEASE":
        record["fulfillment_status"] = "RELEASED"
    elif disposition == "PARTIAL_RELEASE":
        record["fulfillment_status"] = "PARTIALLY_RELEASED"
    else:
        record["fulfillment_status"] = "DENIED"
        record["denial_basis"] = denial_basis
    touch(record)
    return ok(record)


@bp.route("/clerk/records-requests/<request_id>/withdraw", methods=["POST"])
def withdraw_request(request_id):
    authorize((ROLE_REQUESTER, ROLE_CITY_CLERK), owner_request_id=request_id)
    record = fetch(db.requests, request_id, "ERR_REQUEST_NOT_FOUND")
    if record["fulfillment_status"] in CLOSED_AXIS:
        raise ApiError("ERR_INVALID_REQUEST_STATE", 409)
    record["fulfillment_status"] = "WITHDRAWN"
    # compensating action: the ledger is unwound, never deleted
    record["total_waived_cents"] = record["total_assessed_cents"]
    record["refunded_cents"] = record["total_collected_cents"]
    domain.recompute_ledger(record)
    if record["total_collected_cents"] > 0:
        record["fee_status"] = "REFUNDED"
    elif record["total_assessed_cents"] > 0:
        record["fee_status"] = "WAIVED"
    touch(record)
    return ok(record)


@bp.route("/clerk/records-requests/<request_id>/close", methods=["POST"])
def close_request(request_id):
    authorize((ROLE_CITY_CLERK,))
    record = fetch(db.requests, request_id, "ERR_REQUEST_NOT_FOUND")
    if record["fulfillment_status"] not in ("RELEASED", "PARTIALLY_RELEASED",
                                           "DENIED"):
        raise ApiError("ERR_REQUEST_NOT_CLOSABLE", 409)
    if record["fee_balance_cents"] != 0:
        raise ApiError("ERR_FEE_BALANCE_OUTSTANDING", 409)
    record["fulfillment_status"] = "CLOSED"
    record["closed_on"] = now_date()
    touch(record)
    series = db.record_series.get(record["target_series_id"])
    if series is not None and series["retention_trigger"] == "REQUEST_CLOSURE":
        domain.recompute_series_eligibility(series)
    return ok(record)


# --------------------------------------------------------- money axis
@bp.route("/clerk/records-requests/<request_id>/assess-fee", methods=["POST"])
def assess_fee(request_id):
    authorize((ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK))
    record = fetch(db.requests, request_id, "ERR_REQUEST_NOT_FOUND")
    body = body_dict()
    variant = req_enum(body, "fee_schedule_variant", VARIANTS)
    fee_lines = _read_fee_lines(body)
    if record["fulfillment_status"] in CLOSED_AXIS:
        raise ApiError("ERR_INVALID_REQUEST_STATE", 409)
    if record["fee_status"] != "NOT_ASSESSED":
        raise ApiError("ERR_FEE_ALREADY_ASSESSED", 422)
    record["fee_schedule_variant"] = variant
    record["total_assessed_cents"] = calc.records_request_fee_assessment(
        variant, fee_lines, record["commercial_purpose"])
    record["fee_status"] = "ASSESSED"
    domain.recompute_ledger(record)
    touch(record)
    return ok(record)


@bp.route("/clerk/records-requests/<request_id>/waive-fee", methods=["POST"])
def waive_fee(request_id):
    authorize((ROLE_RECORDS,))
    record = fetch(db.requests, request_id, "ERR_REQUEST_NOT_FOUND")
    body = body_dict()
    waived_cents = req_int(body, "waived_cents", minimum=0)
    reason = req_str(body, "waiver_reason")
    # PRD 3.8 states exactly one gate on a waiver: "The waived amount may not
    # exceed the current `fee_balance_cents`".  No fee-status precondition is
    # declared, so none is imposed.
    if waived_cents > record["fee_balance_cents"]:
        raise ApiError("ERR_WAIVER_EXCEEDS_BALANCE", 422)
    record["total_waived_cents"] = record["total_waived_cents"] + waived_cents
    record["_waiver_reason"] = reason  # kept for the file, not part of the schema
    _settle_fee_status(record)
    touch(record)
    return ok(record)


@bp.route("/clerk/records-requests/<request_id>/payments", methods=["POST"])
def record_payment(request_id):
    authorize((ROLE_REQUESTER, ROLE_CITY_CLERK), owner_request_id=request_id)
    record = fetch(db.requests, request_id, "ERR_REQUEST_NOT_FOUND")
    body = body_dict()
    amount_cents = req_int(body, "amount_cents", minimum=0)
    # PRD 3.8 states exactly two gates on a payment: the fee must already have
    # been assessed, and the amount may not exceed the current balance.  A
    # settled request is caught by the balance gate, not by a state gate.
    if record["fee_status"] == "NOT_ASSESSED":
        raise ApiError("ERR_FEE_NOT_ASSESSED", 422)
    if amount_cents > record["fee_balance_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", 422)
    record["total_collected_cents"] = record["total_collected_cents"] + amount_cents
    domain.recompute_ledger(record)
    record["fee_status"] = ("PAID" if record["fee_balance_cents"] == 0
                            else "DEPOSIT_HELD")
    touch(record)
    return ok(record)
