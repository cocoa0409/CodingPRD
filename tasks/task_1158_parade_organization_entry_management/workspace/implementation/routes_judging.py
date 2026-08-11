"""JudgingScoreSheet and Award endpoints."""
from decimal import Decimal

from flask import Blueprint, request

import db
from auth import guarded, require_owner
from db import STORE, make_record, touch
from errors import api_err
from logic import (
    AWARD_CATEGORIES,
    ELIGIBLE_CATEGORIES,
    award_or_404,
    ensure_not_frozen,
    entry_or_404,
    final_score,
    finalized_sheet_count,
    parade_or_404,
    ser_award,
    ser_sheet,
    sheet_or_404,
)
from util import body, paged, req_enum, req_int, respond_object

bp = Blueprint("judging", __name__)

CA = ("CommitteeAdmin",)
JUDGE = ("Judge",)
SHEET_READERS = ("CommitteeAdmin", "Judge")
AWARD_READERS = ("CommitteeAdmin", "AgencyReviewer", "Judge", "Entrant")


def add(rule, methods, view):
    bp.add_url_rule(rule, view_func=view, methods=methods, strict_slashes=False)


# --- JudgingScoreSheet ---------------------------------------------------------

def create_sheet(uid, role, id):
    entry = entry_or_404(id)
    data = body()
    creativity = req_int(data, "creativity", minimum=0, maximum=25)
    craftsmanship = req_int(data, "craftsmanship", minimum=0, maximum=25)
    theme = req_int(data, "theme", minimum=0, maximum=25)
    crowd_appeal = req_int(data, "crowd_appeal", minimum=0, maximum=25)
    if entry["status"] not in ("APPROVED", "SUSPENDED"):
        raise api_err("ERR_INVALID_STATE", "Score sheets open only for APPROVED or SUSPENDED entries")
    if any(
        s["entry_id"] == id and s["judge_user_id"] == uid for s in STORE.score_sheets.values()
    ):
        raise api_err("ERR_DUPLICATE_SCORE_SHEET", "A score sheet already exists for this (entry, judge)")
    rec = make_record()
    rec.update(
        {
            "entry_id": id,
            "judge_user_id": uid,
            "creativity": creativity,
            "craftsmanship": craftsmanship,
            "theme": theme,
            "crowd_appeal": crowd_appeal,
            "sheet_total": creativity + craftsmanship + theme + crowd_appeal,
            "status": "DRAFT",
        }
    )
    STORE.score_sheets[rec["id"]] = rec
    return respond_object(ser_sheet(rec), 201)


def list_sheets(uid, role, id):
    entry_or_404(id)
    items = [s for s in STORE.score_sheets.values() if s["entry_id"] == id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paged(items, ser_sheet)


def get_sheet(uid, role, id):
    return respond_object(ser_sheet(sheet_or_404(id)))


def submit_sheet(uid, role, id):
    sheet = sheet_or_404(id)
    require_owner(uid, sheet["judge_user_id"])
    if sheet["status"] != "DRAFT":
        raise api_err("ERR_INVALID_STATE", "Sheet must be in DRAFT to submit")
    entry = entry_or_404(sheet["entry_id"])
    ensure_not_frozen(parade_or_404(entry["parade_id"]))
    sheet["status"] = "SUBMITTED"
    touch(sheet)
    return respond_object(ser_sheet(sheet))


def reopen_sheet(uid, role, id):
    sheet = sheet_or_404(id)
    require_owner(uid, sheet["judge_user_id"])
    if sheet["status"] != "SUBMITTED":
        raise api_err("ERR_INVALID_STATE", "Sheet must be in SUBMITTED to reopen")
    entry = entry_or_404(sheet["entry_id"])
    parade = parade_or_404(entry["parade_id"])
    if parade["status"] == "COMPLETED":
        raise api_err("ERR_INVALID_STATE", "Reopening is refused once the parade is COMPLETED")
    sheet["status"] = "DRAFT"
    touch(sheet)
    return respond_object(ser_sheet(sheet))


def finalize_sheet(uid, role, id):
    sheet = sheet_or_404(id)
    if sheet["status"] != "SUBMITTED":
        raise api_err("ERR_INVALID_STATE", "Sheet must be in SUBMITTED to finalize")
    entry = entry_or_404(sheet["entry_id"])
    ensure_not_frozen(parade_or_404(entry["parade_id"]))
    sheet["status"] = "FINALIZED"
    touch(sheet)
    return respond_object(ser_sheet(sheet))


add("/entries/<id>/score-sheets", ["POST"], guarded(JUDGE)(create_sheet))
add("/entries/<id>/score-sheets", ["GET"], guarded(SHEET_READERS)(list_sheets))
add("/score-sheets/<id>", ["GET"], guarded(SHEET_READERS)(get_sheet))
add("/score-sheets/<id>/submit", ["POST"], guarded(JUDGE)(submit_sheet))
add("/score-sheets/<id>/reopen", ["POST"], guarded(JUDGE)(reopen_sheet))
add("/score-sheets/<id>/finalize", ["POST"], guarded(CA)(finalize_sheet))


# --- Award ---------------------------------------------------------------------

def create_award(uid, role, id):
    parade_or_404(id)
    data = body()
    award_category = req_enum(data, "award_category", AWARD_CATEGORIES)
    eligible = req_enum(data, "eligible_entry_category", ELIGIBLE_CATEGORIES)
    rec = make_record()
    rec.update(
        {
            "parade_id": id,
            "award_category": award_category,
            "eligible_entry_category": eligible,
            "winner_entry_id": None,
            "status": "PENDING",
            "announced_at": None,
        }
    )
    STORE.awards[rec["id"]] = rec
    return respond_object(ser_award(rec), 201)


def _filter_awards(items):
    parade_id = request.args.get("parade_id")
    winner_entry_id = request.args.get("winner_entry_id")
    status = request.args.get("status")
    if parade_id is not None:
        items = [a for a in items if a["parade_id"] == parade_id]
    if winner_entry_id is not None:
        items = [a for a in items if a["winner_entry_id"] == winner_entry_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return items


def list_parade_awards(uid, role, id):
    parade_or_404(id)
    items = [a for a in STORE.awards.values() if a["parade_id"] == id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paged(items, ser_award)


def list_awards(uid, role):
    return paged(_filter_awards(list(STORE.awards.values())), ser_award)


def get_award(uid, role, id):
    return respond_object(ser_award(award_or_404(id)))


def announce_award(uid, role, id):
    award = award_or_404(id)
    if award["status"] != "PENDING":
        raise api_err("ERR_INVALID_STATE", "Award must be in PENDING to announce")
    parade = parade_or_404(award["parade_id"])
    if parade["status"] != "LINEUP_PUBLISHED":
        raise api_err("ERR_LINEUP_NOT_PUBLISHED", "Announce requires the parade in LINEUP_PUBLISHED")
    ensure_not_frozen(parade)
    eligible = award["eligible_entry_category"]
    pool = []
    for e in STORE.entries.values():
        if e["parade_id"] != parade["id"] or e["status"] != "APPROVED":
            continue
        if eligible != "ANY" and e["assigned_category"] != eligible:
            continue
        score = final_score(e["id"])
        if score is None:
            continue
        pool.append((e, score))
    if not pool:
        raise api_err("ERR_NO_ELIGIBLE_WINNER", "No eligible entry with a FINALIZED score sheet")
    # Deterministic selector: final_score DESC, finalized sheet count DESC,
    # org_name ASC, created_at ASC.
    winner_entry, _ = min(
        pool,
        key=lambda pair: (
            -Decimal(str(pair[1])),
            -finalized_sheet_count(pair[0]["id"]),
            pair[0]["org_name"],
            pair[0]["created_at"],
            pair[0]["_seq"],
        ),
    )
    award["winner_entry_id"] = winner_entry["id"]
    award["announced_at"] = db.now()
    award["status"] = "ANNOUNCED"
    touch(award)
    return respond_object(ser_award(award))


def present_award(uid, role, id):
    award = award_or_404(id)
    if award["status"] != "ANNOUNCED":
        raise api_err("ERR_INVALID_STATE", "Award must be in ANNOUNCED to present")
    ensure_not_frozen(parade_or_404(award["parade_id"]))
    award["status"] = "PRESENTED"
    touch(award)
    return respond_object(ser_award(award))


def cancel_award(uid, role, id):
    award = award_or_404(id)
    if award["status"] != "PENDING":
        raise api_err("ERR_INVALID_STATE", "Award must be in PENDING to cancel")
    award["status"] = "CANCELLED"
    touch(award)
    return respond_object(ser_award(award))


add("/parades/<id>/awards", ["POST"], guarded(CA)(create_award))
add("/parades/<id>/awards", ["GET"], guarded(AWARD_READERS)(list_parade_awards))
add("/awards", ["GET"], guarded(AWARD_READERS)(list_awards))
add("/awards/<id>", ["GET"], guarded(AWARD_READERS)(get_award))
add("/awards/<id>/announce", ["POST"], guarded(CA)(announce_award))
add("/awards/<id>/present", ["POST"], guarded(CA)(present_award))
add("/awards/<id>/cancel", ["POST"], guarded(CA)(cancel_award))
