"""ScoreSheet routes."""

from flask import Blueprint, request

from db import DB, new_id, now_ts
from errors import (
    err_not_found, err_not_owner, err_invalid_state, err_forbidden,
    err_judge_conflict, err_duplicate_scoresheet, err_validation,
)
from middleware import require_roles
from response import success
from services.calculations import sheet_total
from services.cascades import tabulation_reopen_cascade
from services.helpers import body_json, req_str, req_int, req_enum
from services.serializers import scoresheet_view, paginate

bp = Blueprint("scoresheets", __name__)

READ_ROLES = ("ContestLead", "Judge")
PHASES = {"CRAFTSMANSHIP", "STAGE"}
NON_TERMINAL_ENTRY = ("SUBMITTED", "SAFETY_REJECTED", "SAFETY_APPROVED", "PREJUDGED",
                      "STAGE_QUEUED", "PERFORMED", "PLACED")


@bp.route("/scoresheets", methods=["POST"])
def create_scoresheet():
    user_id, _ = require_roles("Judge")
    body = body_json()
    entry_id = req_str(body, "entry_id")
    phase = req_enum(body, "phase", PHASES)
    craftsmanship = req_int(body, "craftsmanship", minimum=0, maximum=10)
    accuracy = req_int(body, "accuracy", minimum=0, maximum=10)
    presentation = req_int(body, "presentation", minimum=0, maximum=10)

    entry = DB.entries.get(entry_id)
    if entry is None:
        raise err_not_found("Entry not found")
    judge = DB.judges.get(user_id)
    if judge is None:
        raise err_not_found("Judge not found")

    # Phase gate (state tier): CRAFTSMANSHIP requires PREJUDGED; STAGE requires
    # STAGE_QUEUED or PERFORMED.
    if phase == "CRAFTSMANSHIP" and entry["status"] != "PREJUDGED":
        raise err_invalid_state("CRAFTSMANSHIP scoresheet requires entry PREJUDGED")
    if phase == "STAGE" and entry["status"] not in ("STAGE_QUEUED", "PERFORMED"):
        raise err_invalid_state("STAGE scoresheet requires entry STAGE_QUEUED or PERFORMED")

    # Referential 1: judge panel assignment.
    if entry["category_id"] not in judge["category_ids"]:
        raise err_forbidden("Judge not assigned to entry's category")

    # Referential 2: conflict of interest via linked contestant.
    linked = judge.get("linked_contestant_id")
    if linked:
        for e in DB.entries.values():
            if (
                e["contestant_id"] == linked
                and e["category_id"] == entry["category_id"]
                and e["status"] in NON_TERMINAL_ENTRY
            ):
                raise err_judge_conflict()

    # Referential 3: no non-VOID sheet for (judge, entry, phase).
    for s in DB.scoresheets.values():
        if (
            s["judge_id"] == user_id
            and s["entry_id"] == entry_id
            and s["phase"] == phase
            and s["status"] != "VOID"
        ):
            raise err_duplicate_scoresheet()

    ts = now_ts()
    sheet = {
        "id": new_id(),
        "entry_id": entry_id,
        "judge_id": user_id,
        "category_id": entry["category_id"],
        "phase": phase,
        "craftsmanship": craftsmanship,
        "accuracy": accuracy,
        "presentation": presentation,
        "sheet_total": sheet_total(craftsmanship, accuracy, presentation),
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB.scoresheets[sheet["id"]] = sheet
    return success(scoresheet_view(sheet), status=201)


@bp.route("/scoresheets", methods=["GET"])
def list_scoresheets():
    require_roles(*READ_ROLES)
    items = list(DB.scoresheets.values())
    entry_id = request.args.get("entry_id")
    judge_id = request.args.get("judge_id")
    category_id = request.args.get("category_id")
    status = request.args.get("status")
    if entry_id is not None:
        items = [s for s in items if s["entry_id"] == entry_id]
    if judge_id is not None:
        items = [s for s in items if s["judge_id"] == judge_id]
    if category_id is not None:
        items = [s for s in items if s["category_id"] == category_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: s["created_at"])
    page, pag = paginate([scoresheet_view(s) for s in items], request.args)
    return success(page, response_type="array", pagination=pag)


@bp.route("/scoresheets/<sid>", methods=["GET"])
def get_scoresheet(sid):
    require_roles(*READ_ROLES)
    sheet = DB.scoresheets.get(sid)
    if sheet is None:
        raise err_not_found("ScoreSheet not found")
    return success(scoresheet_view(sheet))


@bp.route("/scoresheets/<sid>/submit", methods=["POST"])
def submit_scoresheet(sid):
    user_id, _ = require_roles("Judge")
    sheet = DB.scoresheets.get(sid)
    if sheet is None:
        raise err_not_found("ScoreSheet not found")
    if sheet["judge_id"] != user_id:
        raise err_not_owner("Judge may only submit own scoresheets")
    if sheet["status"] != "DRAFT":
        raise err_invalid_state("Only DRAFT scoresheets can be submitted")
    sheet["status"] = "SUBMITTED"
    sheet["updated_at"] = now_ts()
    sheet["version"] += 1
    return success(scoresheet_view(sheet))


@bp.route("/scoresheets/<sid>/reopen", methods=["POST"])
def reopen_scoresheet(sid):
    require_roles("ContestLead")
    sheet = DB.scoresheets.get(sid)
    if sheet is None:
        raise err_not_found("ScoreSheet not found")
    if sheet["status"] != "LOCKED":
        raise err_invalid_state("Only LOCKED scoresheets can be reopened")

    sheet["status"] = "SUBMITTED"
    sheet["updated_at"] = now_ts()
    sheet["version"] += 1

    # Reopen cascade: a TABULATED category reverts to SCORING (placements
    # cleared), which may bubble the contest TABULATION -> JUDGING.
    category = DB.categories.get(sheet["category_id"])
    if category is not None:
        tabulation_reopen_cascade(category)

    return success(scoresheet_view(sheet))
