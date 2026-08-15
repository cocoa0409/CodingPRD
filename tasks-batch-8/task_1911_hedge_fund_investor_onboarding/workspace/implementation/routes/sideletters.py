"""SideLetter and MfnClause endpoints (PRD 3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_INVALID_SUPERSESSION,
    ERR_CLAUSE_RETIRED, ERR_BELOW_CAPACITY_THRESHOLD, ERR_STALE_VERSION,
)
from middleware import require_roles, check_investor_owns
from response import success_object, success_list
from services.core import (
    stamp_new, touch, serialize, paginate, filter_by,
    get_fund, get_subscription, get_side_letter, get_mfn_clause, child_of,
    recompute_fees_for_subscription, recompute_effective_fee,
)
from validate import get_body, req_str, req_int, req_enum, opt_int, opt_nullable_str

bp = Blueprint("sideletters", __name__)

LETTER_READERS = ("FundAdmin", "ComplianceOfficer", "PortfolioManager")
CLAUSE_TAGS = {"FEE_REBATE", "LIQUIDITY", "INFORMATION_RIGHTS", "CAPACITY_RIGHTS", "CO_INVEST"}


def _load_letter_under_fund(fund_id, letter_id):
    fund = get_fund(fund_id)
    letter = get_side_letter(letter_id)
    child_of(letter, "_fund_id", fund["id"])
    return fund, letter


# ---------------------------------------------------------------------------
# SideLetter
# ---------------------------------------------------------------------------


@bp.post("/funds/<fund_id>/side-letters")
def create_side_letter(fund_id):
    require_roles("FundAdmin")
    fund = get_fund(fund_id)
    body = get_body()
    subscription_id = req_str(body, "subscription_id")
    terms_document_id = req_str(body, "terms_document_id")
    supersedes_id = opt_nullable_str(body, "supersedes_side_letter_id")

    sub = db["subscriptions"].get(subscription_id)
    if sub is None or sub["_fund_id"] != fund["id"]:
        raise_error(ERR_NOT_FOUND, "subscription_id does not belong to this fund")

    if supersedes_id is not None:
        prior = db["side_letters"].get(supersedes_id)
        if (prior is None or prior["status"] != "EXECUTED"
                or prior["investor_id"] != sub["investor_id"]):
            raise_error(ERR_INVALID_SUPERSESSION,
                        "supersedes_side_letter_id must reference an EXECUTED side letter of the same investor")

    letter = stamp_new({
        "subscription_id": sub["id"],
        "investor_id": sub["investor_id"],
        "share_class_id": sub["share_class_id"],
        "terms_document_id": terms_document_id,
        "supersedes_side_letter_id": supersedes_id,
        "mfn_election_active": False,
        "elected_clause_ids": [],
        "status": "DRAFT",
        "_fund_id": fund["id"],
    })
    db["side_letters"][letter["id"]] = letter
    return success_object(serialize(letter), 201)


@bp.get("/funds/<fund_id>/side-letters")
def list_side_letters(fund_id):
    require_roles(*LETTER_READERS)
    fund = get_fund(fund_id)
    items = filter_by(db["side_letters"].values(),
                      _fund_id=fund["id"],
                      investor_id=request.args.get("investor_id"),
                      subscription_id=request.args.get("subscription_id"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/funds/<fund_id>/side-letters/<letter_id>")
def get_side_letter_route(fund_id, letter_id):
    caller = require_roles(*LETTER_READERS, "Investor")
    fund, letter = _load_letter_under_fund(fund_id, letter_id)
    check_investor_owns(caller, letter["investor_id"])
    return success_object(serialize(letter))


@bp.post("/funds/<fund_id>/side-letters/<letter_id>/execute")
def execute_side_letter(fund_id, letter_id):
    require_roles("FundAdmin")
    fund, letter = _load_letter_under_fund(fund_id, letter_id)
    body = get_body()
    if letter["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "side letter is not DRAFT")
    sub = get_subscription(letter["subscription_id"])
    if sub["status"] != "ACCEPTED":
        raise_error(ERR_INVALID_STATE, "parent subscription is not ACCEPTED")
    expected = opt_int(body, "expected_subscription_version")
    if expected is not None and expected != sub["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_subscription_version does not match subscription version")

    letter["status"] = "EXECUTED"
    touch(letter)
    if letter["supersedes_side_letter_id"]:
        prior = db["side_letters"].get(letter["supersedes_side_letter_id"])
        if prior is not None and prior["status"] == "EXECUTED":
            prior["status"] = "SUPERSEDED"
            touch(prior)
    # Execution bumps the parent subscription's version (OCC target).
    touch(sub)
    # Re-evaluate MFN fee terms (prior letter's elections no longer apply).
    recompute_fees_for_subscription(sub["id"])
    return success_object(serialize(letter))


@bp.post("/funds/<fund_id>/side-letters/<letter_id>/elect-mfn")
def elect_mfn(fund_id, letter_id):
    caller = require_roles("Investor")
    fund, letter = _load_letter_under_fund(fund_id, letter_id)
    check_investor_owns(caller, letter["investor_id"])
    body = get_body()
    if letter["status"] != "EXECUTED":
        raise_error(ERR_INVALID_STATE, "side letter is not EXECUTED")
    clause_id = req_str(body, "mfn_clause_id")
    clause = db["mfn_clauses"].get(clause_id)
    if clause is None or clause["fund_id"] != fund["id"]:
        raise_error(ERR_NOT_FOUND, "mfn clause not found in this fund")
    sub = get_subscription(letter["subscription_id"])

    # Priority 14 (capacity) before priority 15 (clause retired).
    if sub["commitment_amount_cents"] < clause["capacity_threshold_cents"]:
        raise_error(ERR_BELOW_CAPACITY_THRESHOLD,
                    "commitment below clause capacity threshold")
    if clause["status"] != "ACTIVE":
        raise_error(ERR_CLAUSE_RETIRED, "clause is RETIRED")

    if clause["id"] not in letter["elected_clause_ids"]:
        letter["elected_clause_ids"].append(clause["id"])
    letter["mfn_election_active"] = True
    touch(letter)
    recompute_fees_for_subscription(sub["id"])
    return success_object(serialize(letter))


@bp.post("/funds/<fund_id>/side-letters/<letter_id>/terminate")
def terminate_side_letter(fund_id, letter_id):
    require_roles("FundAdmin")
    fund, letter = _load_letter_under_fund(fund_id, letter_id)
    get_body()
    if letter["status"] != "EXECUTED":
        raise_error(ERR_INVALID_STATE, "side letter is not EXECUTED")
    letter["status"] = "TERMINATED"
    letter["elected_clause_ids"] = []
    letter["mfn_election_active"] = False
    touch(letter)
    # Fee schedule on the capital account reverts to base share class terms.
    recompute_fees_for_subscription(letter["subscription_id"])
    return success_object(serialize(letter))


# ---------------------------------------------------------------------------
# MfnClause
# ---------------------------------------------------------------------------


@bp.post("/funds/<fund_id>/mfn-clauses")
def create_mfn_clause(fund_id):
    require_roles("FundAdmin")
    fund = get_fund(fund_id)
    body = get_body()
    clause = stamp_new({
        "fund_id": fund["id"],
        "clause_tag": req_enum(body, "clause_tag", CLAUSE_TAGS),
        "clause_text": req_str(body, "clause_text"),
        "capacity_threshold_cents": req_int(body, "capacity_threshold_cents", minimum=0),
        "fee_rebate_bps": req_int(body, "fee_rebate_bps", minimum=0),
        "notice_days_reduction": req_int(body, "notice_days_reduction", minimum=0),
        "status": "ACTIVE",
    })
    db["mfn_clauses"][clause["id"]] = clause
    return success_object(serialize(clause), 201)


@bp.get("/funds/<fund_id>/mfn-clauses")
def list_mfn_clauses(fund_id):
    require_roles(*LETTER_READERS, "Investor")
    fund = get_fund(fund_id)
    items = filter_by(db["mfn_clauses"].values(),
                      fund_id=fund["id"],
                      status=request.args.get("status"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/funds/<fund_id>/mfn-clauses/<clause_id>")
def get_mfn_clause_route(fund_id, clause_id):
    require_roles(*LETTER_READERS, "Investor")
    fund = get_fund(fund_id)
    clause = get_mfn_clause(clause_id)
    child_of(clause, "fund_id", fund["id"])
    return success_object(serialize(clause))


@bp.post("/funds/<fund_id>/mfn-clauses/<clause_id>/retire")
def retire_mfn_clause(fund_id, clause_id):
    require_roles("FundAdmin")
    fund = get_fund(fund_id)
    clause = get_mfn_clause(clause_id)
    child_of(clause, "fund_id", fund["id"])
    get_body()
    if clause["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "clause is not ACTIVE")
    clause["status"] = "RETIRED"
    touch(clause)
    return success_object(serialize(clause))
