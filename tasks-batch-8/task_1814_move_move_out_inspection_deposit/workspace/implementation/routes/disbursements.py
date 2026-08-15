"""Disbursement endpoints (PRD §3.7): create/reserve, cash, reverse, escheat."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_AMOUNT_EXCEEDS_BALANCE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STATEMENT_SUPERSEDED,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import (
    current_statement, evaluate_settlement, new_record, public,
    recompute_tenancy_money, touch,
)
from util import CLOCK
from validate import (
    get_body, req_enum, req_int, req_str, require_body_ref,
    require_path_resource,
)

bp = Blueprint("disbursements", __name__)


@bp.post("/pm/disbursements")
def create_disbursement():
    authorized(["PropertyManager"])
    body = get_body()
    tenancy_id = req_str(body, "tenancy_id")
    statement_id = req_str(body, "statement_id")
    kind = req_enum(body, "kind", ("REFUND", "PENALTY"))
    amount_cents = req_int(body, "amount_cents", non_negative=True)
    payee_name = req_str(body, "payee_name")
    # Priority 4: referenced ids exist, validated left-to-right.
    tenancy = require_body_ref("tenancies", tenancy_id, "tenancy_id")
    statement = require_body_ref("statements", statement_id, "statement_id")
    # Priority 5: when the referenced statement IS the tenancy's current
    # statement it must be ISSUED or SETTLED (a DRAFT or dispute-locked
    # current statement is a state error)...
    current = current_statement(tenancy["id"])
    is_current = (
        current is not None
        and statement["id"] == current["id"]
        and statement["tenancy_id"] == tenancy["id"]
    )
    if is_current:
        if statement["status"] not in ("ISSUED", "SETTLED"):
            raise_error(ERR_INVALID_STATE_TRANSITION,
                        "the current statement must be ISSUED or SETTLED to "
                        "create a disbursement")
    else:
        # ...priority 7: a non-current reference is the referential concern.
        raise_error(ERR_STATEMENT_SUPERSEDED,
                    "statement_id is not the tenancy's current non-superseded "
                    "statement")
    # Priority 10: a REFUND may not exceed the remaining balance; PENALTY is
    # paid outside the deposit ledger and is exempt.
    if kind == "REFUND" and amount_cents > tenancy["balance_remaining_cents"]:
        raise_error(ERR_AMOUNT_EXCEEDS_BALANCE,
                    "REFUND disbursement exceeds the tenancy's "
                    "balance_remaining_cents")
    rec = new_record("disbursements", {
        "tenancy_id": tenancy["id"],
        "statement_id": statement["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "payee_name": payee_name,
        "sent_at": CLOCK.now_iso(),
        "cashed_at": None,
        "escheatment_reference": None,
        "status": "SENT",
    })
    # A REFUND reserves its amount immediately (funds in flight).
    recompute_tenancy_money(tenancy["id"])
    touch(tenancy)
    return success_object(public(rec), status=201)


@bp.get("/pm/disbursements/<rid>")
def get_disbursement(rid):
    return get_one("disbursements", rid)


@bp.get("/pm/disbursements")
def list_disbursements():
    return list_response("disbursements", {
        "tenancy_id": request.args.get("tenancy_id"),
        "statement_id": request.args.get("statement_id"),
        "status": request.args.get("status"),
    })


@bp.post("/pm/disbursements/<rid>/mark_cashed")
def mark_cashed(rid):
    authorized(["PropertyManager"])
    get_body()
    disb = require_path_resource("disbursements", rid)
    if disb["status"] != "SENT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"mark_cashed requires SENT, got {disb['status']}")
    disb["status"] = "CASHED"
    disb["cashed_at"] = CLOCK.now_iso()
    touch(disb)
    tenancy = db["tenancies"].get(disb["tenancy_id"])
    # Releasing the reservation and posting the payment are both aggregate
    # effects of the status flip.
    recompute_tenancy_money(tenancy["id"])
    touch(tenancy)
    if disb["kind"] == "REFUND":
        evaluate_settlement(db["statements"].get(disb["statement_id"]))
    return success_object(public(disb))


@bp.post("/pm/disbursements/<rid>/reverse")
def reverse_disbursement(rid):
    authorized(["PropertyManager"])
    get_body()
    disb = require_path_resource("disbursements", rid)
    if disb["status"] != "CASHED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"reverse requires CASHED, got {disb['status']}")
    disb["status"] = "REVERSED"
    touch(disb)
    tenancy = db["tenancies"].get(disb["tenancy_id"])
    recompute_tenancy_money(tenancy["id"])
    touch(tenancy)
    # Settlement unwinds when the reversal drags refund_paid_cents back below
    # the statement's refund_due_cents.
    if disb["kind"] == "REFUND":
        statement = db["statements"].get(disb["statement_id"])
        if (statement is not None
                and statement["status"] == "SETTLED"
                and tenancy["refund_paid_cents"] < statement["refund_due_cents"]):
            statement["status"] = "ISSUED"
            touch(statement)
            if tenancy["status"] == "SETTLED":
                tenancy["status"] = "VACATED"
    return success_object(public(disb))


@bp.post("/pm/disbursements/<rid>/escheat")
def escheat_disbursement(rid):
    authorized(["PropertyManager"])
    body = get_body()
    reference = req_str(body, "escheatment_reference", non_empty=True)
    disb = require_path_resource("disbursements", rid)
    if disb["status"] != "STALE_DATED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"escheat requires STALE_DATED, got {disb['status']}")
    disb["status"] = "ESCHEATED"
    disb["escheatment_reference"] = reference
    touch(disb)
    tenancy = db["tenancies"].get(disb["tenancy_id"])
    recompute_tenancy_money(tenancy["id"])
    touch(tenancy)
    # When the escheat leaves the balance at exactly zero and nothing remains
    # SENT, the tenancy itself closes out as ESCHEATED.
    if tenancy["status"] == "VACATED" and tenancy["balance_remaining_cents"] == 0:
        any_sent = any(
            x["tenancy_id"] == tenancy["id"] and x["status"] == "SENT"
            for x in db["disbursements"].values()
        )
        if not any_sent:
            tenancy["status"] = "ESCHEATED"
    return success_object(public(disb))
