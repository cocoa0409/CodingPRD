"""Take-out investor routes, including the deepest cascade in the system (PRD 3.2)."""

from flask import Blueprint

from clock import clock
from db import db, touch
from errors import ApiError
from middleware import (
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    INVESTOR,
    own_investor,
    require_auth,
)
from response import ok
from routes.common import filter_by, get_investor, list_response
from serializers import bailee_letter_out, commitment_out, investor_out
from services import computed
from services.states import orphan_cascade
from validation import body, v_string

bp = Blueprint("investors", __name__)


@bp.get("/investors/<investor_id>")
def read_investor(investor_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, INVESTOR])
    investor = get_investor(investor_id)
    return ok(investor_out(investor))


@bp.post("/investors/<investor_id>/approve")
def approve_investor(investor_id):
    require_auth([CREDIT_OFFICER])
    investor = get_investor(investor_id)
    body()
    facility = db.facilities[investor["facility_id"]]
    if facility["status"] not in ("PENDING_APPROVAL", "ACTIVE", "RESTRICTED"):
        raise ApiError("ERR_FACILITY_NOT_ACTIVE",
                       "The owning facility is SUSPENDED.")
    # priority 44
    if investor["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVESTOR_INVALID_STATE",
                       "Only a PENDING_APPROVAL investor may be approved.")
    investor["status"] = "APPROVED"
    investor["approved_at"] = clock.now()
    touch(investor)
    return ok(investor_out(investor))


@bp.post("/investors/<investor_id>/suspend")
def suspend_investor(investor_id):
    require_auth([CREDIT_OFFICER])
    investor = get_investor(investor_id)
    data = body()
    v_string(data, "reason", max_len=500)
    # priority 44
    if investor["status"] != "APPROVED":
        raise ApiError("ERR_INVESTOR_INVALID_STATE",
                       "Only an APPROVED investor may be suspended.")
    facility = db.facilities[investor["facility_id"]]

    investor["status"] = "SUSPENDED"
    touch(investor)

    # first hop: withdraw the investor's live commitments
    withdrawn = []
    for commitment in computed.investor_commitments(investor["id"]):
        if commitment["status"] not in ("OPEN", "PARTIALLY_ALLOCATED",
                                       "FULLY_ALLOCATED"):
            continue
        commitment["status"] = "WITHDRAWN"
        touch(commitment)
        withdrawn.append(commitment)

    # hops two through four
    orphan_cascade(facility, withdrawn)

    # separately: revoke every live bailee letter naming this investor
    for letter in computed.investor_bailee_letters(investor["id"]):
        if letter["status"] != "ISSUED":
            continue
        letter["status"] = "REVOKED"
        touch(letter)

    return ok(investor_out(investor))


@bp.get("/investors/<investor_id>/commitments")
def list_investor_commitments(investor_id):
    user_id, role = require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, INVESTOR])
    investor = get_investor(investor_id)
    own_investor(user_id, role, investor["id"])
    rows = computed.investor_commitments(investor["id"])
    rows = filter_by(rows, "status")
    return list_response(rows, commitment_out)


@bp.get("/investors/<investor_id>/bailee-letters")
def list_investor_bailee_letters(investor_id):
    user_id, role = require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, INVESTOR])
    investor = get_investor(investor_id)
    own_investor(user_id, role, investor["id"])
    rows = computed.investor_bailee_letters(investor["id"])
    rows = filter_by(rows, "status")
    return list_response(rows, bailee_letter_out)
