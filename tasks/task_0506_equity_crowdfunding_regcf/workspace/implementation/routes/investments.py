"""Investment endpoints (PRD 3.4, 3.5)."""
from flask import Blueprint, request

from clock import clock, parse_iso
from calculations import window_start
from db import db, new_id, now_iso
from derive import (
    touch,
    credit_wallet,
    recompute_offering_committed,
    recompute_escrow_held,
    get_escrow_for_offering,
)
from errors import err
from middleware import get_auth, require_role
from pagination import paginate
from response import success
from serializers import investment_out
from validation import require_body, require_str, require_int

bp = Blueprint("investments", __name__)


def _investor_trailing_committed(investor_id, now):
    """Sum gross amount over the investor's investments across all offerings in
    {COMMITTED, RECONFIRMED, ISSUED} created within the trailing 365-day window."""
    ws = window_start(now)
    total = 0
    for inv in db.investments.values():
        if inv["investor_id"] != investor_id:
            continue
        if inv["status"] not in ("COMMITTED", "RECONFIRMED", "ISSUED"):
            continue
        if parse_iso(inv["created_at"]) >= ws:
            total += inv["amount_cents"]
    return total


@bp.post("/investments")
def create_investment():
    uid, role = get_auth()
    require_role(role, {"Investor"})

    body = require_body()
    offering_id = require_str(body, "offering_id")
    investor_id = require_str(body, "investor_id")
    amount = require_int(body, "amount_cents", minimum=1)
    expected_version = require_int(body, "expected_offering_version")

    # Ownership: an Investor commits only for itself.
    if investor_id != uid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Caller may only invest for itself")

    # Existence (left-to-right: offering then investor).
    offering = db.offerings.get(offering_id)
    if offering is None:
        raise err("ERR_NOT_FOUND", "Offering not found")
    investor = db.investors.get(investor_id)
    if investor is None:
        raise err("ERR_NOT_FOUND", "Investor not found")

    # State: target offering must be LIVE.
    if offering["status"] != "LIVE":
        raise err("ERR_INVALID_STATE", "Offering is not LIVE")

    now = clock.now()

    # Business checks in pinned order (PRD 3.4):
    # 1) deadline
    deadline = parse_iso(offering["deadline_at"])
    if not (now < deadline):
        raise err("ERR_OFFERING_DEADLINE_PASSED", "The offering deadline has passed")

    # 2) OCC guard
    if expected_version != offering["version"]:
        raise err("ERR_STALE_OFFERING_VERSION", "expected_offering_version does not match the current offering version")

    # 3) annual-limit (UNACCREDITED only)
    if investor["accreditation_status"] == "UNACCREDITED":
        trailing = _investor_trailing_committed(investor_id, now)
        if trailing + amount > investor["annual_limit_cents"]:
            raise err("ERR_ANNUAL_LIMIT_EXCEEDED", "Commitment exceeds the investor's annual limit")

    # 4) per-investor cap (only when set on the offering)
    cap = offering.get("per_investor_cap_cents")
    if cap is not None:
        existing_to_this = sum(
            i["amount_cents"]
            for i in db.investments.values()
            if i["offering_id"] == offering_id
            and i["investor_id"] == investor_id
            and i["status"] in ("COMMITTED", "RECONFIRMED", "ISSUED")
        )
        if existing_to_this + amount > cap:
            raise err("ERR_PER_INVESTOR_CAP_EXCEEDED", "Commitment exceeds the per-investor cap for this offering")

    # 5) oversubscription
    if offering["swept_amount_cents"] + offering["committed_amount_cents"] + amount > offering["max_target_cents"]:
        raise err("ERR_OVERSUBSCRIBED", "Commitment would exceed the offering's maximum target")

    # Commit.
    ts = now_iso()
    iid = new_id()
    rec = {
        "id": iid,
        "offering_id": offering_id,
        "investor_id": investor_id,
        "amount_cents": amount,
        "expected_offering_version": expected_version,
        "status": "COMMITTED",
        "securities_issued": 0,
        "refund_amount_cents": 0,
        "reconfirm_required": False,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.investments[iid] = rec

    recompute_offering_committed(offering)
    escrow = get_escrow_for_offering(offering_id)
    if escrow is not None:
        recompute_escrow_held(escrow)
        touch(escrow)
    touch(offering)
    return success(investment_out(rec), status=201)


@bp.get("/investments/<id>")
def get_investment(id):
    uid, role = get_auth()
    require_role(role, {"Investor", "Issuer", "ComplianceOfficer"})
    rec = db.investments.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Investment not found")
    return success(investment_out(rec))


@bp.get("/investments")
def list_investments():
    uid, role = get_auth()
    require_role(role, {"Investor", "Issuer", "ComplianceOfficer"})
    rows = list(db.investments.values())
    for field in ("offering_id", "investor_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    page, meta = paginate(rows)
    return success([investment_out(r) for r in page], pagination=meta)


@bp.post("/investments/<id>/reconfirm")
def reconfirm_investment(id):
    uid, role = get_auth()
    require_role(role, {"Investor"})
    rec = db.investments.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Investment not found")
    if rec["investor_id"] != uid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Caller does not own this investment")
    if rec["status"] != "COMMITTED" or not rec["reconfirm_required"]:
        raise err("ERR_INVALID_STATE", "Only a COMMITTED investment flagged for reconfirmation may reconfirm")
    rec["status"] = "RECONFIRMED"
    rec["reconfirm_required"] = False
    touch(rec)
    return success(investment_out(rec))


@bp.post("/investments/<id>/withdraw")
def withdraw_investment(id):
    uid, role = get_auth()
    require_role(role, {"Investor"})
    rec = db.investments.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Investment not found")
    if rec["investor_id"] != uid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Caller does not own this investment")
    if rec["status"] not in ("COMMITTED", "RECONFIRMED"):
        raise err("ERR_INVALID_STATE", "Only a COMMITTED or RECONFIRMED investment may be withdrawn")
    offering = db.offerings.get(rec["offering_id"])
    deadline = parse_iso(offering["deadline_at"])
    if not (clock.now() < deadline):
        raise err("ERR_OFFERING_DEADLINE_PASSED", "The offering deadline has passed")

    rec["status"] = "CANCELLED"
    rec["refund_amount_cents"] = rec["amount_cents"]
    credit_wallet(rec["investor_id"], rec["amount_cents"])
    touch(rec)

    recompute_offering_committed(offering)
    escrow = get_escrow_for_offering(offering["id"])
    if escrow is not None:
        recompute_escrow_held(escrow)
        touch(escrow)
    touch(offering)
    return success(investment_out(rec))
