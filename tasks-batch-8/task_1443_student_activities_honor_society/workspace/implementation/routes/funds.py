"""FundraiserRequest and FundLedgerEntry endpoints."""

from flask import Blueprint

import db
from core import (as_int, as_str, body, caller_active_role, check_frozen,
                  create_ledger_entry, get_chapter, get_fundraiser,
                  get_ledger_entry, new_record, recompute_chapter,
                  require_fields, serialize_fundraiser, touch)
from db import now, parse_dt
from errors import (ERR_DEPOSIT_NOT_CLEARED, ERR_INSUFFICIENT_CHAPTER_FUNDS,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
                    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                    ERR_STALE_CHAPTER_VERSION, ApiError)
from middleware import auth, require_roles
from response import (apply_filters, list_response, serialize, serialize_many,
                      sorted_items, success)

bp = Blueprint("funds", __name__)

ALL = ("ActivitiesDirector", "Advisor", "Officer", "Member")


# --- FundraiserRequest ---

@bp.route("/chapters/<chapterId>/fundraiser-requests", methods=["POST"])
def create_fundraiser(chapterId):
    uid, role = auth()
    require_roles(role, ("Officer",))
    ch = get_chapter(chapterId)
    check_frozen(ch)
    caller_active_role(ch["id"], uid)
    data = body()
    require_fields(data, ["title", "description", "goal_amount_cents",
                          "upfront_cost_cents", "requested_by_officer_id",
                          "scheduled_date"])
    goal = as_int(data["goal_amount_cents"], "goal_amount_cents")
    if goal < 100:
        raise ApiError(ERR_INVALID_REQUEST, 400, "goal_amount_cents must be at least 100")
    upfront = as_int(data["upfront_cost_cents"], "upfront_cost_cents")
    if upfront < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "upfront_cost_cents must be >= 0")
    requested_by = as_str(data["requested_by_officer_id"], "requested_by_officer_id")
    sponsor = db.officer_roles.get(requested_by)
    if sponsor is None or sponsor["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"OfficerRole not found: {requested_by}")
    rec = new_record({
        "chapter_id": ch["id"],
        "title": as_str(data["title"], "title"),
        "description": as_str(data["description"], "description"),
        "goal_amount_cents": goal,
        "upfront_cost_cents": upfront,
        "requested_by_officer_id": requested_by,
        "scheduled_date": db.iso(parse_dt(data["scheduled_date"], "scheduled_date")),
        "status": "DRAFT",
        "actual_gross_cents": None,
        "actual_net_cents": None,
        "advisor_approved_by_user_id": None,
        "director_approved_by_user_id": None,
    })
    db.fundraisers[rec["id"]] = rec
    return success(serialize_fundraiser(rec), 201)


@bp.route("/chapters/<chapterId>/fundraiser-requests/<fundraiserId>", methods=["GET"])
def fetch_fundraiser(chapterId, fundraiserId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    f = get_fundraiser(ch, fundraiserId)
    return success(serialize_fundraiser(f), 200)


@bp.route("/chapters/<chapterId>/fundraiser-requests", methods=["GET"])
def list_fundraisers(chapterId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector", "Advisor", "Officer"))
    ch = get_chapter(chapterId)
    items = [f for f in db.fundraisers.values() if f["chapter_id"] == ch["id"]]
    items = apply_filters(items, ["status"])
    return list_response([serialize_fundraiser(f) for f in sorted_items(items)])


@bp.route("/chapters/<chapterId>/fundraiser-requests/<fundraiserId>/submit", methods=["POST"])
def submit_fundraiser(chapterId, fundraiserId):
    uid, role = auth()
    require_roles(role, ("Officer",))
    ch = get_chapter(chapterId)
    f = get_fundraiser(ch, fundraiserId)
    check_frozen(ch)
    caller_active_role(ch["id"], uid)
    # state legality before the fiscal rule (PRD 3.5)
    if f["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT fundraiser can be submitted")
    sponsor = db.officer_roles.get(f["requested_by_officer_id"])
    if sponsor is None or sponsor["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The sponsoring officer's role must be ACTIVE")
    if ch["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Chapter must be ACTIVE to submit a fundraiser")
    if f["upfront_cost_cents"] > ch["fund_balance_cents"]:
        raise ApiError(ERR_INSUFFICIENT_CHAPTER_FUNDS, 409,
                       "Chapter cannot front money it does not have")
    f["status"] = "SUBMITTED"
    touch(f)
    return success(serialize_fundraiser(f), 200)


@bp.route("/chapters/<chapterId>/fundraiser-requests/<fundraiserId>/advisor-approve", methods=["POST"])
def advisor_approve_fundraiser(chapterId, fundraiserId):
    uid, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    f = get_fundraiser(ch, fundraiserId)
    check_frozen(ch)
    # state legality before version freshness (PRD 3.5)
    if f["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a SUBMITTED fundraiser can be advisor-approved")
    data = body()
    if "expected_chapter_version" not in data or data["expected_chapter_version"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_chapter_version is required")
    expected = as_int(data["expected_chapter_version"], "expected_chapter_version")
    if expected != ch["version"]:
        raise ApiError(ERR_STALE_CHAPTER_VERSION, 412,
                       "expected_chapter_version does not match the chapter's current version")
    f["status"] = "ADVISOR_APPROVED"
    f["advisor_approved_by_user_id"] = uid
    touch(f)
    touch(ch)  # successful approval advances the chapter version by one
    return success(serialize_fundraiser(f), 200)


@bp.route("/chapters/<chapterId>/fundraiser-requests/<fundraiserId>/director-approve", methods=["POST"])
def director_approve_fundraiser(chapterId, fundraiserId):
    uid, role = auth()
    require_roles(role, ("ActivitiesDirector",))
    ch = get_chapter(chapterId)
    f = get_fundraiser(ch, fundraiserId)
    check_frozen(ch)
    if f["status"] != "ADVISOR_APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ADVISOR_APPROVED fundraiser can be director-approved")
    if uid == f["advisor_approved_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES_VIOLATION, 409,
                       "The director approver must differ from the advisor approver")
    f["status"] = "DIRECTOR_APPROVED"
    f["director_approved_by_user_id"] = uid
    touch(f)
    return success(serialize_fundraiser(f), 200)


@bp.route("/chapters/<chapterId>/fundraiser-requests/<fundraiserId>/reject", methods=["POST"])
def reject_fundraiser(chapterId, fundraiserId):
    _, role = auth()
    require_roles(role, ("Advisor", "ActivitiesDirector"))
    ch = get_chapter(chapterId)
    f = get_fundraiser(ch, fundraiserId)
    check_frozen(ch)
    # advisor rejects from SUBMITTED; director rejects from ADVISOR_APPROVED
    if role == "Advisor" and f["status"] == "SUBMITTED":
        pass
    elif role == "ActivitiesDirector" and f["status"] == "ADVISOR_APPROVED":
        pass
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Fundraiser cannot be rejected by this role from its current state")
    f["status"] = "REJECTED"
    touch(f)
    return success(serialize_fundraiser(f), 200)


@bp.route("/chapters/<chapterId>/fundraiser-requests/<fundraiserId>/execute", methods=["POST"])
def execute_fundraiser(chapterId, fundraiserId):
    uid, role = auth()
    require_roles(role, ("Officer",))
    ch = get_chapter(chapterId)
    f = get_fundraiser(ch, fundraiserId)
    check_frozen(ch)
    caller_active_role(ch["id"], uid)
    if f["status"] != "DIRECTOR_APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DIRECTOR_APPROVED fundraiser can be executed")
    if now() < parse_dt(f["scheduled_date"], "scheduled_date"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The fundraiser's scheduled_date has not yet been reached")
    data = body()
    if "actual_gross_cents" not in data or data["actual_gross_cents"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "actual_gross_cents is required")
    gross = as_int(data["actual_gross_cents"], "actual_gross_cents")
    net = gross - f["upfront_cost_cents"]
    f["actual_gross_cents"] = gross
    f["actual_net_cents"] = net
    f["status"] = "EXECUTED"
    touch(f)
    create_ledger_entry(ch, "FUNDRAISER_DEPOSIT", net, "PENDING",
                        fundraiser_id=f["id"],
                        description=f"Fundraiser deposit: {f['title']}")
    if f["upfront_cost_cents"] > 0:
        create_ledger_entry(ch, "UPFRONT_COST_DISBURSEMENT", -f["upfront_cost_cents"],
                            "CLEARED", fundraiser_id=f["id"],
                            description=f"Upfront cost disbursement: {f['title']}")
    recompute_chapter(ch)
    return success(serialize_fundraiser(f), 200)


@bp.route("/chapters/<chapterId>/fundraiser-requests/<fundraiserId>/close", methods=["POST"])
def close_fundraiser(chapterId, fundraiserId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    f = get_fundraiser(ch, fundraiserId)
    check_frozen(ch)
    if f["status"] != "EXECUTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an EXECUTED fundraiser can be closed")
    deposit = None
    for e in db.ledger_entries.values():
        if (e["chapter_id"] == ch["id"] and e.get("fundraiser_id") == f["id"]
                and e["entry_type"] == "FUNDRAISER_DEPOSIT"):
            deposit = e
            break
    if deposit is None or deposit["status"] != "CLEARED":
        raise ApiError(ERR_DEPOSIT_NOT_CLEARED, 409,
                       "The FUNDRAISER_DEPOSIT ledger entry must be CLEARED before close")
    f["status"] = "CLOSED"
    touch(f)
    recompute_chapter(ch)
    return success(serialize_fundraiser(f), 200)


# --- FundLedgerEntry ---

@bp.route("/chapters/<chapterId>/fund-ledger-entries", methods=["GET"])
def list_ledger_entries(chapterId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector", "Advisor", "Officer"))
    ch = get_chapter(chapterId)
    items = [e for e in db.ledger_entries.values() if e["chapter_id"] == ch["id"]]
    items = apply_filters(items, ["status", "entry_type"])
    return list_response(serialize_many(sorted_items(items)))


@bp.route("/chapters/<chapterId>/fund-ledger-entries/<entryId>", methods=["GET"])
def fetch_ledger_entry(chapterId, entryId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector", "Advisor", "Officer"))
    ch = get_chapter(chapterId)
    e = get_ledger_entry(ch, entryId)
    return success(serialize(e), 200)


@bp.route("/chapters/<chapterId>/fund-ledger-entries/<entryId>/clear", methods=["POST"])
def clear_ledger_entry(chapterId, entryId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    e = get_ledger_entry(ch, entryId)
    check_frozen(ch)
    if e["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PENDING ledger entry can be cleared")
    if ch["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Ledger entries may only be cleared while the chapter is ACTIVE")
    e["status"] = "CLEARED"
    touch(e)
    recompute_chapter(ch)
    return success(serialize(e), 200)


@bp.route("/chapters/<chapterId>/fund-ledger-entries/<entryId>/void", methods=["POST"])
def void_ledger_entry(chapterId, entryId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    e = get_ledger_entry(ch, entryId)
    check_frozen(ch)
    if e["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PENDING ledger entry can be voided")
    e["status"] = "VOIDED"
    touch(e)
    recompute_chapter(ch)
    return success(serialize(e), 200)
