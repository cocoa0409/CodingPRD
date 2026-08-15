"""Category routes."""

from flask import Blueprint

from db import DB, new_id, now_ts
from errors import (
    err_not_found, err_invalid_state, err_stale_version, err_validation,
    err_scoresheets_not_locked, err_no_eligible_entries,
)
from middleware import require_roles
from response import success
from services.calculations import purse_split, assign_placements
from services.helpers import body_json, req_str, req_int, req_enum
from services.serializers import category_view

bp = Blueprint("categories", __name__)

READ_ROLES = ("ContestLead", "Treasurer", "StageManager", "Judge", "SafetyOfficer", "Contestant")
SKILL_DIVISIONS = {"JUNIOR", "NOVICE", "JOURNEYMAN", "MASTERS"}
TABULATION_METHODS = {"WEIGHTED_MEAN", "TRIMMED_MEAN"}


@bp.route("/categories", methods=["POST"])
def create_category():
    require_roles("ContestLead")
    body = body_json()
    contest_id = req_str(body, "contest_id")
    name = req_str(body, "name")
    skill_division = req_enum(body, "skill_division", SKILL_DIVISIONS)
    max_entries = req_int(body, "max_entries", minimum=1)
    tabulation_method = req_enum(body, "tabulation_method", TABULATION_METHODS)
    prize_purse_cents = req_int(body, "prize_purse_cents", minimum=0)

    contest = DB.contest_events.get(contest_id)
    if contest is None:
        raise err_not_found("ContestEvent not found")

    r1, r2, r3 = purse_split(prize_purse_cents)
    ts = now_ts()
    cat = {
        "id": new_id(),
        "contest_id": contest_id,
        "name": name,
        "skill_division": skill_division,
        "max_entries": max_entries,
        "tabulation_method": tabulation_method,
        "prize_purse_cents": prize_purse_cents,
        "status": "DRAFT",
        "prize_rank1_cents": r1,
        "prize_rank2_cents": r2,
        "prize_rank3_cents": r3,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB.categories[cat["id"]] = cat
    return success(category_view(cat), status=201)


@bp.route("/categories/<cid>", methods=["GET"])
def get_category(cid):
    require_roles(*READ_ROLES)
    cat = DB.categories.get(cid)
    if cat is None:
        raise err_not_found("Category not found")
    return success(category_view(cat))


@bp.route("/categories/<cid>", methods=["PATCH"])
def patch_category(cid):
    require_roles("ContestLead")
    body = body_json()

    # Field-shape validation for whatever fields are present.
    if "name" in body and (not isinstance(body["name"], str) or not body["name"]):
        raise err_validation("name must be a non-empty string")
    if "skill_division" in body and body["skill_division"] not in SKILL_DIVISIONS:
        raise err_validation("skill_division invalid")
    if "max_entries" in body:
        v = body["max_entries"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise err_validation("max_entries must be an integer >= 1")
    if "tabulation_method" in body and body["tabulation_method"] not in TABULATION_METHODS:
        raise err_validation("tabulation_method invalid")
    if "prize_purse_cents" in body:
        v = body["prize_purse_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err_validation("prize_purse_cents must be an integer >= 0")
    if "expected_category_version" in body:
        v = body["expected_category_version"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err_validation("expected_category_version must be an integer")

    cat = DB.categories.get(cid)
    if cat is None:
        raise err_not_found("Category not found")

    # OCC (§2.6).
    expected = body.get("expected_category_version")
    if expected is not None and expected != cat["version"]:
        raise err_stale_version("Category version mismatch")

    # Category config editable only while parent contest is SETUP (§3.1).
    contest = DB.contest_events.get(cat["contest_id"])
    if contest is None or contest["status"] != "SETUP":
        raise err_invalid_state("Category configuration is frozen once the contest leaves SETUP")

    if "name" in body:
        cat["name"] = body["name"]
    if "skill_division" in body:
        cat["skill_division"] = body["skill_division"]
    if "max_entries" in body:
        cat["max_entries"] = body["max_entries"]
    if "tabulation_method" in body:
        cat["tabulation_method"] = body["tabulation_method"]
    if "prize_purse_cents" in body:
        cat["prize_purse_cents"] = body["prize_purse_cents"]
        r1, r2, r3 = purse_split(cat["prize_purse_cents"])
        cat["prize_rank1_cents"] = r1
        cat["prize_rank2_cents"] = r2
        cat["prize_rank3_cents"] = r3

    cat["updated_at"] = now_ts()
    cat["version"] += 1
    return success(category_view(cat))


@bp.route("/categories/<cid>/tabulate", methods=["POST"])
def tabulate_category(cid):
    require_roles("ContestLead")
    cat = DB.categories.get(cid)
    if cat is None:
        raise err_not_found("Category not found")
    if cat["status"] != "SCORING":
        raise err_invalid_state("Category must be SCORING to tabulate")

    # Precondition 1: no DRAFT/SUBMITTED scoresheets among entries of the category.
    entry_ids = {
        e["id"] for e in DB.entries.values() if e["category_id"] == cid
    }
    for sheet in DB.scoresheets.values():
        if sheet["entry_id"] in entry_ids and sheet["status"] in ("DRAFT", "SUBMITTED"):
            raise err_scoresheets_not_locked()

    # Precondition 2: at least one PERFORMED entry.
    has_performed = any(
        e["category_id"] == cid and e["status"] == "PERFORMED"
        for e in DB.entries.values()
    )
    if not has_performed:
        raise err_no_eligible_entries()

    placed_count = assign_placements(cat)

    cat["status"] = "TABULATED"
    cat["updated_at"] = now_ts()
    cat["version"] += 1
    return success({"placed_entry_count": placed_count, "category_id": cid})


@bp.route("/categories/<cid>/lock-scoresheets", methods=["POST"])
def lock_scoresheets(cid):
    require_roles("ContestLead")
    cat = DB.categories.get(cid)
    if cat is None:
        raise err_not_found("Category not found")
    if cat["status"] != "SCORING":
        raise err_invalid_state("Category must be SCORING to lock scoresheets")

    entry_ids = {
        e["id"] for e in DB.entries.values() if e["category_id"] == cid
    }
    ts = now_ts()
    locked = 0
    for sheet in DB.scoresheets.values():
        if sheet["entry_id"] in entry_ids and sheet["status"] == "SUBMITTED":
            sheet["status"] = "LOCKED"
            sheet["updated_at"] = ts
            sheet["version"] += 1
            locked += 1
    return success({"locked_count": locked})
