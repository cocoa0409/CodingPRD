"""DeferralRequest endpoints (PRD 3.8 disaster relief track)."""
from datetime import timedelta

from flask import Blueprint

from db import STORE, get_clock
from errors import raise_err
from middleware import ALL_ROLES, auth, require_owner, require_role
from response import ok_list, ok_object
from serialize import list_response, ser_deferral
from services.core import (active_disaster_declaration, deferrals_of_loan,
                           stamp_new, touch)
from util import as_dt, as_str, body, need, new_id

bp = Blueprint("deferrals", __name__)

GAP_MIN = timedelta(days=30)
BLOCKING_STATES = ("APPROVED", "IN_EFFECT")


def get_deferral_or_404(did):
    d = STORE.deferrals.get(did)
    if d is None:
        raise_err("ERR_NOT_FOUND", "Deferral request not found")
    return d


@bp.route("/deferral-requests", methods=["POST"])
def create_deferral():
    uid, role = auth()
    require_role(role, ["Borrower"])
    b = body()
    loan_account_id = as_str(need(b, "loan_account_id"), "loan_account_id")
    disaster_ref = as_str(need(b, "disaster_ref"), "disaster_ref")
    requested_start = as_dt(need(b, "requested_start"), "requested_start")
    requested_end = as_dt(need(b, "requested_end"), "requested_end")
    if requested_end <= requested_start:
        raise_err("ERR_INVALID_REQUEST", "requested_end must be after requested_start")
    clock = get_clock()
    if requested_start.date() < clock.date():
        raise_err("ERR_INVALID_REQUEST",
                  "requested_start must not be before the clock date")
    loan = STORE.loans.get(loan_account_id)
    if loan is None:
        raise_err("ERR_NOT_FOUND", "Loan account not found")
    require_owner(loan["borrower_id"] == uid)
    if loan["status"] != "ACTIVE":
        raise_err("ERR_LOAN_NOT_ACTIVE", "Deferral creation requires an ACTIVE loan")
    borrower = STORE.borrowers.get(loan["borrower_id"])
    if borrower is not None and borrower["status"] == "SUSPENDED":
        raise_err("ERR_BORROWER_SUSPENDED",
                  "Suspended borrowers cannot create deferral requests")
    association = STORE.associations.get(loan["association_id"])
    if association is None or borrower is None or \
            active_disaster_declaration(association, borrower["county"],
                                        ref=disaster_ref) is None:
        raise_err("ERR_DISASTER_NOT_FOUND",
                  "No active disaster declaration covers the borrower's county")
    deferral = stamp_new({
        "id": new_id(),
        "loan_account_id": loan["id"],
        "disaster_ref": disaster_ref,
        "requested_start": requested_start,
        "requested_end": requested_end,
        "status": "SUBMITTED",
    })
    STORE.deferrals[deferral["id"]] = deferral
    return ok_object(ser_deferral(deferral), code=201)


@bp.route("/deferral-requests/<did>", methods=["GET"])
def get_deferral(did):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return ok_object(ser_deferral(get_deferral_or_404(did)))


@bp.route("/deferral-requests", methods=["GET"])
def list_deferrals():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.deferrals.values(), ser_deferral,
        [("loan_account_id", lambda e: e["loan_account_id"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.route("/deferral-requests/<did>/approve", methods=["POST"])
def approve_deferral(did):
    auth_uid, role = auth()
    require_role(role, ["CreditCommittee"])
    deferral = get_deferral_or_404(did)
    if deferral["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a SUBMITTED deferral can be approved")
    s, e = deferral["requested_start"], deferral["requested_end"]
    existing = [d for d in deferrals_of_loan(deferral["loan_account_id"])
                if d["id"] != deferral["id"] and d["status"] in BLOCKING_STATES]
    # Overlap checked first, then the 30-day gap in both directions.
    for d in existing:
        if s < d["requested_end"] and d["requested_start"] < e:
            raise_err("ERR_DEFERRAL_OVERLAP",
                      "Window overlaps another APPROVED/IN_EFFECT deferral")
    for d in existing:
        if s >= d["requested_end"]:
            if s - d["requested_end"] < GAP_MIN:
                raise_err("ERR_DEFERRAL_GAP_TOO_SMALL",
                          "Window starts less than 30 days after another deferral")
        elif e <= d["requested_start"]:
            if d["requested_start"] - e < GAP_MIN:
                raise_err("ERR_DEFERRAL_GAP_TOO_SMALL",
                          "Window ends less than 30 days before another deferral")
    deferral["status"] = "APPROVED"
    touch(deferral)
    return ok_object(ser_deferral(deferral))


@bp.route("/deferral-requests/<did>/deny", methods=["POST"])
def deny_deferral(did):
    auth_uid, role = auth()
    require_role(role, ["CreditCommittee"])
    deferral = get_deferral_or_404(did)
    if deferral["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a SUBMITTED deferral can be denied")
    deferral["status"] = "DENIED"
    touch(deferral)
    return ok_object(ser_deferral(deferral))


@bp.route("/deferral-requests/<did>/end_early", methods=["POST"])
def end_early_deferral(did):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    deferral = get_deferral_or_404(did)
    if deferral["status"] != "IN_EFFECT":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only an IN_EFFECT deferral can be ended early")
    deferral["status"] = "ENDED_EARLY"
    touch(deferral)
    return ok_object(ser_deferral(deferral))
