"""Disbursement routes: schedule, fetch, list, send, confirm, return.

PRD §3.8 (scheduling and remitting payoffs; segregation of duties on send).
"""
from flask import Blueprint, request

import db
import serialize
from auth import authorize
from errors import err
from response import object_response, array_response
from store_helpers import get_or_404, sorted_by_created, paginate, append_audit
from validate import (
    get_json_body,
    require_str,
    require_positive_int,
    parse_pagination,
)

bp = Blueprint("disbursements", __name__)


@bp.route("/disbursements", methods=["POST"])
def create_disbursement():
    authorize(("POST", "/disbursements"))
    body = get_json_body()
    loan_id = require_str(body, "loan_id")
    prior_servicer_name = require_str(body, "prior_servicer_name")
    payoff_amount_cents = require_positive_int(body, "payoff_amount_cents")

    with db.lock():
        loan = get_or_404(db.loans, loan_id)
        # Sum of scheduled payoffs must not exceed original principal (PRD §3.8).
        existing = sum(
            d["payoff_amount_cents"]
            for d in db.disbursements.values()
            if d["loan_id"] == loan_id
        )
        if existing + payoff_amount_cents > loan["original_principal_cents"]:
            raise err("ERR_PAYOFF_EXCEEDS_PRINCIPAL", "scheduled payoffs exceed principal")
        record = {
            "loan_id": loan_id,
            "prior_servicer_name": prior_servicer_name,
            "payoff_amount_cents": payoff_amount_cents,
            "status": "SCHEDULED",
        }
        db.stamp_create(record)
        db.disbursements[record["id"]] = record
    return object_response(serialize.disbursement(record), 201)


@bp.route("/disbursements/<rid>", methods=["GET"])
def get_disbursement(rid):
    authorize(("GET", "/disbursements/{id}"))
    record = get_or_404(db.disbursements, rid)
    return object_response(serialize.disbursement(record), 200)


@bp.route("/disbursements", methods=["GET"])
def list_disbursements():
    authorize(("GET", "/disbursements"))
    limit, offset = parse_pagination()
    f_loan = request.args.get("loan_id")
    f_status = request.args.get("status")
    records = list(db.disbursements.values())
    if f_loan is not None:
        records = [r for r in records if r["loan_id"] == f_loan]
    if f_status is not None:
        records = [r for r in records if r["status"] == f_status]
    records = sorted_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serialize.disbursement(r) for r in page], limit, offset, total)


@bp.route("/disbursements/<rid>/send", methods=["POST"])
def send_disbursement(rid):
    user_id, role = authorize(("POST", "/disbursements/{id}/send"))
    with db.lock():
        disb = get_or_404(db.disbursements, rid)
        loan = get_or_404(db.loans, disb["loan_id"])
        # Defined only from SCHEDULED, only while loan CURRENT (state).
        if disb["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "send only from SCHEDULED")
        if loan["repayment_status"] != "CURRENT":
            raise err("ERR_INVALID_STATE", "loan not CURRENT")
        # Segregation of duties: officer must differ from approving underwriter.
        app = db.applications.get(loan["application_id"])
        approved_by = app["approved_underwriter_id"] if app else None
        if approved_by is not None and user_id == approved_by:
            raise err("ERR_SEGREGATION_OF_DUTIES", "officer is the approving underwriter")
        disb["status"] = "SENT"
        db.touch(disb)
        append_audit("DISBURSEMENT", disb["id"], "DISBURSEMENT_SENT", role, user_id)
    return object_response(serialize.disbursement(disb), 200)


@bp.route("/disbursements/<rid>/confirm", methods=["POST"])
def confirm_disbursement(rid):
    user_id, role = authorize(("POST", "/disbursements/{id}/confirm"))
    with db.lock():
        disb = get_or_404(db.disbursements, rid)
        if disb["status"] != "SENT":
            raise err("ERR_INVALID_STATE", "confirm only from SENT")
        disb["status"] = "CONFIRMED"
        db.touch(disb)
        append_audit("DISBURSEMENT", disb["id"], "DISBURSEMENT_CONFIRMED", role, user_id)
    return object_response(serialize.disbursement(disb), 200)


@bp.route("/disbursements/<rid>/return", methods=["POST"])
def return_disbursement(rid):
    user_id, role = authorize(("POST", "/disbursements/{id}/return"))
    with db.lock():
        disb = get_or_404(db.disbursements, rid)
        if disb["status"] != "SENT":
            raise err("ERR_INVALID_STATE", "return only from SENT")
        disb["status"] = "RETURNED"
        db.touch(disb)
        append_audit("DISBURSEMENT", disb["id"], "DISBURSEMENT_RETURNED", role, user_id)
    return object_response(serialize.disbursement(disb), 200)
