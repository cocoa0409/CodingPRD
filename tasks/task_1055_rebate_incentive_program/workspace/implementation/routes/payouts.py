"""Payout endpoints (7) - PRD §3.8."""
from flask import Blueprint, g, request

import db
import middleware as mw
import response as resp
import serializers as ser
from errors import err
from services import budget, rebate

bp = Blueprint("payouts", __name__)

READ_ROLES = ("ProgramAdmin", "ClaimsProcessor", "FinanceOfficer", "Dealer", "Consumer")
LIVE_PAYOUT_STATES = {"PENDING", "RELEASED", "REISSUE_PENDING"}


@bp.post("/api/claims/<cid>/payouts")
@mw.require("FinanceOfficer")
def create_payout(cid):
    claim = db.get_claim(cid)
    data = mw.body()

    # (6) shape
    expected = mw.as_int(data, "expected_claim_version")
    method = mw.as_enum(data, "method", {"CHECK", "VIRTUAL_CARD"}, required=False, default=None)

    # (8) optimistic concurrency
    if expected != claim["version"]:
        raise err("ERR_STALE_CLAIM_VERSION")

    # (9) state
    if claim["adjudication_status"] != "APPROVED":
        raise err("ERR_CLAIM_NOT_REVIEWABLE", "Only an approved claim may be disbursed.")

    # (10) duplicate-payout guard
    for existing in db.payouts_of_claim(claim["id"]):
        if existing["status"] in LIVE_PAYOUT_STATES:
            raise err("ERR_PAYOUT_ALREADY_EXISTS")
    if claim["payment_status"] != "NONE":
        raise err("ERR_PAYOUT_ALREADY_EXISTS")

    claimant = db.get_claimant(claim["claimant_id"])
    gross, method, fee, net = rebate.settle_payout_amounts(claim, claimant, method)

    # (16) fiscal floor
    if net < db.PAYOUT_MIN_CENTS:
        raise err("ERR_BELOW_MIN_PAYOUT")

    rec = db.base_record()
    rec.update({
        "claim_id": claim["id"],
        "method": method,
        "gross_cents": gross,
        "fee_cents": fee,
        "net_cents": net,
        "status": "PENDING",
        "check_number": None,
        "released_at": None,
        "released_by_user_id": None,
        "void_reason": None,
        "reissue_count": 0,
    })
    db.payouts[rec["id"]] = rec

    claim["payment_status"] = "SCHEDULED"
    db.touch(claim)
    return resp.created(ser.payout(rec))


@bp.get("/api/payouts/<pid>")
@mw.require(*READ_ROLES)
def read_payout(pid):
    return resp.ok(ser.payout(db.get_payout(pid)))


@bp.get("/api/payouts")
@mw.require(*READ_ROLES)
def list_payouts():
    items = db.by_created(list(db.payouts.values()))
    for field in ("claim_id", "status", "method"):
        value = request.args.get(field)
        if value:
            items = [p for p in items if p[field] == value]
    return resp.paginated(items, ser.payout)


@bp.post("/api/payouts/<pid>/release")
@mw.require("FinanceOfficer")
def release_payout(pid):
    payout = db.get_payout(pid)
    data = mw.body()
    check_number = mw.as_string(data, "check_number", required=False, allow_empty=True)

    # (9) state
    if payout["status"] not in ("PENDING", "REISSUE_PENDING"):
        raise err("ERR_PAYOUT_NOT_RELEASABLE")

    claim = db.get_claim(payout["claim_id"])
    claimant = db.get_claimant(claim["claimant_id"])

    # (11) claimant standing
    if claimant["status"] != "ACTIVE":
        raise err("ERR_CLAIMANT_BLOCKED")

    # (12) segregation of duties
    if claim["approved_by_user_id"] is not None and g.user_id == claim["approved_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES")

    # (16) fiscal floor
    if payout["net_cents"] < db.PAYOUT_MIN_CENTS:
        raise err("ERR_BELOW_MIN_PAYOUT")

    clock = db.now()
    payout["status"] = "RELEASED"
    payout["released_at"] = clock
    payout["released_by_user_id"] = g.user_id
    if check_number is not None:
        payout["check_number"] = check_number
    db.touch(payout)

    claim["payment_status"] = "PAID"
    db.touch(claim)

    program = db.program_of_claim(claim)
    if program is not None:
        budget.append_entry(program, "PAYMENT", payout["net_cents"], claim_id=claim["id"])
        budget.recompute(program, trigger="PAYMENT")

    if payout["method"] == "VIRTUAL_CARD" and not db.cards_of_payout(payout["id"]):
        card = db.base_record()
        card.update({
            "payout_id": payout["id"],
            "initial_balance_cents": payout["net_cents"],
            "remaining_balance_cents": payout["net_cents"],
            "status": "ISSUED",
            "issued_at": clock,
            "last_activity_at": clock,
            "expires_at": db.add_days(clock, db.VIRTUAL_CARD_VALID_DAYS),
        })
        db.virtual_cards[card["id"]] = card

    return resp.ok(ser.payout(payout))


@bp.post("/api/payouts/<pid>/clear")
@mw.require("FinanceOfficer")
def clear_payout(pid):
    payout = db.get_payout(pid)
    # (9) state
    if payout["status"] != "RELEASED":
        raise err("ERR_PAYOUT_NOT_RELEASABLE")
    # (17) the check-only clearing rule
    if payout["method"] != "CHECK":
        raise err("ERR_NOT_CHECK_PAYOUT")
    payout["status"] = "CLEARED"
    db.touch(payout)
    return resp.ok(ser.payout(payout))


@bp.post("/api/payouts/<pid>/void")
@mw.require("FinanceOfficer")
def void_payout(pid):
    payout = db.get_payout(pid)
    data = mw.body()
    void_reason = mw.as_string(data, "void_reason")

    if payout["status"] not in LIVE_PAYOUT_STATES:
        raise err("ERR_PAYOUT_NOT_RELEASABLE")

    payout["status"] = "VOIDED"
    payout["void_reason"] = void_reason
    db.touch(payout)

    claim = db.claims.get(payout["claim_id"])
    if claim is not None and claim["payment_status"] in ("SCHEDULED", "PAID"):
        claim["payment_status"] = "NONE"
        db.touch(claim)
    # No BudgetEntry is appended: voiding does not release the commitment.
    return resp.ok(ser.payout(payout))


@bp.post("/api/payouts/<pid>/reissue")
@mw.require("FinanceOfficer")
def reissue_payout(pid):
    payout = db.get_payout(pid)
    if payout["status"] not in ("RELEASED", "VOIDED"):
        raise err("ERR_PAYOUT_NOT_RELEASABLE")

    claim = db.get_claim(payout["claim_id"])
    from_status = payout["status"]

    if from_status == "RELEASED":
        if claim["payment_status"] not in ("PAID", "NONE"):
            raise err("ERR_PAYOUT_NOT_RELEASABLE")
    else:  # VOIDED
        if claim["adjudication_status"] != "APPROVED":
            raise err("ERR_CLAIM_NOT_REVIEWABLE", "Only an approved claim may be reissued.")

    payout["status"] = "REISSUE_PENDING"
    payout["reissue_count"] += 1
    payout["check_number"] = None
    db.touch(payout)

    if from_status == "VOIDED" and claim["payment_status"] == "NONE":
        claim["payment_status"] = "SCHEDULED"
        db.touch(claim)

    return resp.ok(ser.payout(payout))
