"""Entry routes: registration, OCC-guarded edit, safety check, withdraw,
disqualify (full cascade)."""

from flask import Blueprint, request

from db import DB, new_id, now_ts
from errors import (
    err_not_found, err_not_owner, err_invalid_state, err_registration_not_open,
    err_prop_banned, err_stale_version, err_validation, err_category_full,
    err_duplicate_entry, err_division_age,
)
from middleware import require_roles
from response import success
from services.calculations import (
    BANNED_PROP_TYPES, junior_eligible, category_entry_count,
)
from services.cascades import withdraw_cascade, disqualify_cascade
from services.helpers import body_json, req_str, opt_str, opt_bool, req_list, req_enum
from services.serializers import entry_view, paginate

bp = Blueprint("entries", __name__)

READ_ROLES = ("ContestLead", "Treasurer", "StageManager", "Judge", "SafetyOfficer", "Contestant")
NON_TERMINAL = ("SUBMITTED", "SAFETY_REJECTED", "SAFETY_APPROVED", "PREJUDGED",
                "STAGE_QUEUED", "PERFORMED", "PLACED")


def _check_banned(props):
    for p in props:
        if p in BANNED_PROP_TYPES:
            raise err_prop_banned(f"Banned prop type declared: {p}")


@bp.route("/entries", methods=["POST"])
def create_entry():
    user_id, _ = require_roles("Contestant")
    body = body_json()
    contestant_id = req_str(body, "contestant_id")
    category_id = req_str(body, "category_id")
    title = req_str(body, "title")
    prop_declarations = req_list(body, "prop_declarations")
    character_source = opt_str(body, "character_source", default="")
    requires_prejudging = opt_bool(body, "requires_prejudging", default=True)

    # FK resolution (left-to-right).
    contestant = DB.contestants.get(contestant_id)
    if contestant is None:
        raise err_not_found("Contestant not found")
    category = DB.categories.get(category_id)
    if category is None:
        raise err_not_found("Category not found")

    # Ownership.
    if contestant_id != user_id:
        raise err_not_owner("contestant_id must equal caller X-User-ID")

    # State: contest REGISTRATION_OPEN and category OPEN.
    contest = DB.contest_events.get(category["contest_id"])
    if contest is None or contest["status"] != "REGISTRATION_OPEN" or category["status"] != "OPEN":
        raise err_registration_not_open()

    # Safety screen of declared props.
    _check_banned(prop_declarations)

    # Capacity: entry_count == max_entries rejects (inclusive boundary).
    if category_entry_count(category_id) >= category["max_entries"]:
        raise err_category_full()

    # Per-contestant limits.
    contest_id = category["contest_id"]
    my_active = [
        e for e in DB.entries.values()
        if e["contestant_id"] == contestant_id
        and e["contest_id"] == contest_id
        and e["status"] in NON_TERMINAL
    ]
    if any(e["category_id"] == category_id for e in my_active):
        raise err_duplicate_entry("Contestant already has a non-terminal entry in this category")
    if len(my_active) >= contest["max_entries_per_contestant"]:
        raise err_duplicate_entry("max_entries_per_contestant reached")

    # JUNIOR division age gate.
    if category["skill_division"] == "JUNIOR":
        if not junior_eligible(contestant["birth_date"], contest["start_at"]):
            raise err_division_age()

    ts = now_ts()
    entry = {
        "id": new_id(),
        "contestant_id": contestant_id,
        "category_id": category_id,
        "contest_id": contest_id,
        "title": title,
        "character_source": character_source,
        "prop_declarations": list(prop_declarations),
        "requires_prejudging": requires_prejudging,
        "status": "SUBMITTED",
        "safety_status": "PENDING",
        "rejected_props": [],
        "placement_rank": None,
        "final_score": None,
        "craftsmanship_mean": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB.entries[entry["id"]] = entry
    return success(entry_view(entry), status=201)


@bp.route("/entries", methods=["GET"])
def list_entries():
    require_roles(*READ_ROLES)
    items = list(DB.entries.values())
    category_id = request.args.get("category_id")
    contestant_id = request.args.get("contestant_id")
    contest_id = request.args.get("contest_id")
    status = request.args.get("status")
    if category_id is not None:
        items = [e for e in items if e["category_id"] == category_id]
    if contestant_id is not None:
        items = [e for e in items if e["contestant_id"] == contestant_id]
    if contest_id is not None:
        items = [e for e in items if e["contest_id"] == contest_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: e["created_at"])
    page, pag = paginate([entry_view(e) for e in items], request.args)
    return success(page, response_type="array", pagination=pag)


@bp.route("/entries/<eid>", methods=["GET"])
def get_entry(eid):
    require_roles(*READ_ROLES)
    entry = DB.entries.get(eid)
    if entry is None:
        raise err_not_found("Entry not found")
    return success(entry_view(entry))


@bp.route("/entries/<eid>", methods=["PATCH"])
def patch_entry(eid):
    user_id, _ = require_roles("Contestant")
    body = body_json()

    if "title" in body and (not isinstance(body["title"], str) or not body["title"]):
        raise err_validation("title must be a non-empty string")
    if "character_source" in body and not isinstance(body["character_source"], str):
        raise err_validation("character_source must be a string")
    if "prop_declarations" in body:
        v = body["prop_declarations"]
        if not isinstance(v, list) or any(not isinstance(p, str) for p in v):
            raise err_validation("prop_declarations must be a list of strings")
    if "expected_entry_version" in body:
        v = body["expected_entry_version"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err_validation("expected_entry_version must be an integer")

    entry = DB.entries.get(eid)
    if entry is None:
        raise err_not_found("Entry not found")

    if entry["contestant_id"] != user_id:
        raise err_not_owner("Contestant may only edit own entries")

    # OCC (§2.6).
    expected = body.get("expected_entry_version")
    if expected is not None and expected != entry["version"]:
        raise err_stale_version("Entry version mismatch")

    if entry["status"] not in ("SUBMITTED", "SAFETY_REJECTED"):
        raise err_invalid_state("Entry editable only while SUBMITTED or SAFETY_REJECTED")

    if "prop_declarations" in body:
        _check_banned(body["prop_declarations"])

    props_changed = (
        "prop_declarations" in body
        and body["prop_declarations"] != entry["prop_declarations"]
    )

    if "title" in body:
        entry["title"] = body["title"]
    if "character_source" in body:
        entry["character_source"] = body["character_source"]
    if "prop_declarations" in body:
        entry["prop_declarations"] = list(body["prop_declarations"])

    # SAFETY_REJECTED + prop change -> cycle back to SUBMITTED (§3.3).
    if entry["status"] == "SAFETY_REJECTED" and props_changed:
        entry["status"] = "SUBMITTED"
        entry["safety_status"] = "PENDING"
        entry["rejected_props"] = []

    entry["updated_at"] = now_ts()
    entry["version"] += 1
    return success(entry_view(entry))


@bp.route("/entries/<eid>/withdraw", methods=["POST"])
def withdraw_entry(eid):
    user_id, _ = require_roles("Contestant")
    entry = DB.entries.get(eid)
    if entry is None:
        raise err_not_found("Entry not found")
    if entry["contestant_id"] != user_id:
        raise err_not_owner("Contestant may only withdraw own entries")
    if entry["status"] not in ("SUBMITTED", "SAFETY_REJECTED", "SAFETY_APPROVED",
                               "PREJUDGED", "STAGE_QUEUED"):
        raise err_invalid_state(f"Cannot withdraw entry in state {entry['status']}")

    withdraw_cascade(entry)
    entry["status"] = "WITHDRAWN"
    entry["updated_at"] = now_ts()
    entry["version"] += 1
    return success(entry_view(entry))


@bp.route("/entries/<eid>/disqualify", methods=["POST"])
def disqualify_entry(eid):
    require_roles("ContestLead")
    body_json()  # optional reason; accepted but not persisted
    entry = DB.entries.get(eid)
    if entry is None:
        raise err_not_found("Entry not found")
    if entry["status"] in ("WITHDRAWN", "DISQUALIFIED"):
        raise err_invalid_state(f"Cannot disqualify entry in state {entry['status']}")

    disqualify_cascade(entry)
    entry["status"] = "DISQUALIFIED"
    entry["updated_at"] = now_ts()
    entry["version"] += 1
    return success(entry_view(entry))


@bp.route("/entries/<eid>/safety-check", methods=["POST"])
def safety_check(eid):
    require_roles("SafetyOfficer")
    body = body_json()
    verdict = req_enum(body, "verdict", {"APPROVED", "REJECTED"})
    rejected_props = body.get("rejected_props", [])
    if not isinstance(rejected_props, list) or any(not isinstance(p, str) for p in rejected_props):
        raise err_validation("rejected_props must be a list of strings")

    entry = DB.entries.get(eid)
    if entry is None:
        raise err_not_found("Entry not found")

    if verdict == "APPROVED":
        if entry["status"] != "SUBMITTED":
            raise err_invalid_state("Safety approval requires entry SUBMITTED")
        entry["status"] = "SAFETY_APPROVED"
        entry["safety_status"] = "APPROVED"
        entry["rejected_props"] = []
    else:  # REJECTED
        if entry["status"] not in ("SUBMITTED", "SAFETY_APPROVED"):
            raise err_invalid_state(
                "Safety rejection requires entry SUBMITTED or SAFETY_APPROVED"
            )
        entry["status"] = "SAFETY_REJECTED"
        entry["safety_status"] = "REJECTED"
        entry["rejected_props"] = list(rejected_props)
        # Re-inspection: force-release any BOOKED pre-judging slot.
        ts = now_ts()
        for slot in DB.prejudging_slots.values():
            if slot["status"] == "BOOKED" and slot.get("booked_entry_id") == entry["id"]:
                slot["status"] = "OPEN"
                slot["booked_entry_id"] = None
                slot["updated_at"] = ts
                slot["version"] += 1

    entry["updated_at"] = now_ts()
    entry["version"] += 1
    return success(entry_view(entry))
