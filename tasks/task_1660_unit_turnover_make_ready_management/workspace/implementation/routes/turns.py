"""Turn endpoints, inspections, and replacement decisions (PRD §3.2-§3.9)."""
from datetime import timedelta

from flask import Blueprint

import db
import services
from db import store
from errors import ApiError
from middleware import authenticate, require_roles
from response import created, ok, paged
from validation import get_body, validate_schema

bp = Blueprint("turns", __name__)

READ_ROLES = ["RegionalManager", "PropertyManager", "TurnCoordinator",
              "Inspector"]

TURN_SCHEMA = {
    "unit_id": ("string", True, None),
    "notice_date": ("date", True, None),
    "move_out_date": ("date", True, None),
}

INSPECTION_SCHEMA = {
    "result": ("enum", True, ["PASS", "FAIL"]),
    "failed_scope_item_ids": ("str_list", False, None),
    "notes": ("string", False, None),
}

DECISION_SCHEMA = {
    "scope_item_id": ("string", True, None),
    "repair_estimate_cents": ("integer", True, None),
    "replace_estimate_cents": ("integer", True, None),
    "repair_life_years": ("integer", True, None),
    "remaining_life_years": ("integer", True, None),
    "decision": ("enum", True, ["REPAIR", "REPLACE"]),
}


def _get_turn_or_404(turn_id):
    turn = store.turns.get(turn_id)
    if turn is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Turn not found")
    return turn


# ---------------------------------------------------------------------------
# Turn lifecycle
# ---------------------------------------------------------------------------

@bp.post("/make-ready/turns")
def create_turn():
    authenticate()
    require_roles(["TurnCoordinator"])
    body = get_body()
    validate_schema(body, TURN_SCHEMA)
    if db.parse_date(body["move_out_date"]) < db.parse_date(body["notice_date"]):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "move_out_date must be on or after notice_date")
    unit = store.units.get(body["unit_id"])
    if unit is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Unit not found")
    if unit["status"] != "OCCUPIED":
        raise ApiError("ERR_UNIT_NOT_OCCUPIED", 409,
                       "Unit is not OCCUPIED; a unit already in NOTICE, "
                       "IN_TURN, or READY refuses a new turn")
    turn = {
        "id": db.new_id(),
        "unit_id": body["unit_id"],
        "notice_date": body["notice_date"],
        "move_out_date": body["move_out_date"],
        "status": "OPEN",
        "started_on": None,
        "target_ready_date": None,
        "actual_ready_date": None,
        "projected_ready_date": None,
        "approved_budget_cents": 0,
        "estimated_cost_cents": 0,
        "expense_actual_cents": 0,
        "capital_actual_cents": 0,
        "total_actual_cents": 0,
        "booked_expense_cents": 0,
    }
    db.new_common(turn)
    store.turns[turn["id"]] = turn
    unit["status"] = "NOTICE"
    db.touch(unit)
    return created(turn)


@bp.get("/make-ready/turns/<turn_id>")
def get_turn(turn_id):
    authenticate()
    require_roles(READ_ROLES)
    return ok(_get_turn_or_404(turn_id))


@bp.get("/make-ready/turns")
def list_turns():
    authenticate()
    require_roles(READ_ROLES)
    page, pg = paged(list(store.turns.values()), ("unit_id", "status"))
    return ok(page, rtype="array", pagination=pg)


@bp.post("/make-ready/turns/<turn_id>/finalize-scope")
def finalize_scope(turn_id):
    authenticate()
    require_roles(["TurnCoordinator"])
    validate_schema(get_body(), {})
    turn = _get_turn_or_404(turn_id)
    if turn["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OPEN turn can be finalized")
    planned = [i for i in services.items_of_turn(turn_id)
               if i["status"] == "PLANNED"]
    if not planned:
        raise ApiError("ERR_NO_SCOPE_ITEMS", 422,
                       "Finalize requires at least one PLANNED scope item")
    unit = store.units[turn["unit_id"]]
    prop = store.properties[unit["property_id"]]
    started = db.logical_date()
    turn["approved_budget_cents"] = turn["estimated_cost_cents"]
    turn["started_on"] = started.isoformat()
    turn["target_ready_date"] = (
        started + timedelta(days=prop["days_to_ready_target"])).isoformat()
    turn["status"] = "SCOPED"
    db.touch(turn)  # version += 1 (PRD §3.3)
    turn["projected_ready_date"] = services.compute_projection(turn).isoformat()
    services.evaluate_commitment_risk(turn)
    unit["status"] = "IN_TURN"
    db.touch(unit)
    return ok(turn)


@bp.post("/make-ready/turns/<turn_id>/close")
def close_turn(turn_id):
    authenticate()
    require_roles(["PropertyManager"])
    validate_schema(get_body(), {})
    turn = _get_turn_or_404(turn_id)
    if turn["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a READY turn can be closed")
    turn["status"] = "CLOSED"
    db.touch(turn)  # version += 1 (PRD §3.9)
    unit = store.units.get(turn["unit_id"])
    if unit is not None:
        services.recompute_property_benchmark(unit["property_id"])
    return ok(turn)


@bp.post("/make-ready/turns/<turn_id>/cancel")
def cancel_turn(turn_id):
    authenticate()
    require_roles(["PropertyManager"])
    validate_schema(get_body(), {})
    turn = _get_turn_or_404(turn_id)
    if turn["status"] not in ("OPEN", "SCOPED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OPEN or SCOPED turn can be cancelled")
    unit = store.units.get(turn["unit_id"])
    # Scope items: PLANNED/SCHEDULED -> VOIDED, PENDING_APPROVAL -> REJECTED.
    for item in services.items_of_turn(turn_id):
        if item["status"] in ("PLANNED", "SCHEDULED"):
            item["status"] = "VOIDED"
            db.touch(item)
            services.cancel_item_assignments(item)
        elif item["status"] == "PENDING_APPROVAL":
            item["status"] = "REJECTED"
            db.touch(item)
    # Open lease commitments on the unit are cancelled.
    for c in services.commitments_of_unit(turn["unit_id"]):
        if c["status"] in ("ACTIVE", "AT_RISK"):
            c["status"] = "CANCELLED"
            db.touch(c)
    # Unit returns to OCCUPIED (NOTICE from OPEN, IN_TURN from SCOPED).
    if unit is not None and unit["status"] in ("NOTICE", "IN_TURN"):
        unit["status"] = "OCCUPIED"
        db.touch(unit)
    turn["status"] = "CANCELLED"
    db.touch(turn)  # version += 1
    return ok(turn)


# ---------------------------------------------------------------------------
# Inspections (nested under Turn; PRD §3.7)
# ---------------------------------------------------------------------------

@bp.post("/make-ready/turns/<turn_id>/inspections")
def submit_inspection(turn_id):
    authenticate()
    require_roles(["Inspector"])
    body = get_body()
    validate_schema(body, INSPECTION_SCHEMA)
    failed_ids = body.get("failed_scope_item_ids")
    if body["result"] == "FAIL":
        if not failed_ids:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400,
                "failed_scope_item_ids is required and non-empty when "
                "result is FAIL")
    else:
        if failed_ids:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400,
                "failed_scope_item_ids must be absent or empty when "
                "result is PASS")
    turn = _get_turn_or_404(turn_id)
    if turn["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Inspections may only be submitted while the turn is "
                       "IN_PROGRESS")
    failed_items = []
    if body["result"] == "FAIL":
        seen = set()
        for item_id in failed_ids:
            if item_id in seen:
                continue
            seen.add(item_id)
            item = store.scope_items.get(item_id)
            if (item is None or item["turn_id"] != turn_id
                    or item["status"] != "COMPLETED"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Inspection-failed items must be COMPLETED "
                               "scope items of this turn")
            failed_items.append(item)

    record = {
        "id": db.new_id(),
        "turn_id": turn_id,
        "result": body["result"],
        "failed_scope_item_ids": list(failed_ids) if failed_ids else None,
        "notes": body.get("notes"),
        "created_at": db.wall_now(),
        "_seq": db.next_seq(),
    }
    store.inspections[record["id"]] = record

    unit = store.units.get(turn["unit_id"])
    if body["result"] == "PASS":
        turn["actual_ready_date"] = db.logical_date().isoformat()
        turn["status"] = "READY"
        db.touch(turn)  # version += 1 (PRD §3.7)
        if unit is not None and unit["status"] == "IN_TURN":
            unit["status"] = "READY"
            db.touch(unit)
        # The projection machinery runs once more with risk re-evaluated.
        turn["projected_ready_date"] = (
            services.compute_projection(turn).isoformat())
        services.evaluate_commitment_risk(turn)
    else:
        # FAIL: each listed item COMPLETED -> FAILED; each spawns a rework item.
        for item in failed_items:
            item["status"] = "FAILED"
            db.touch(item)
        for item in failed_items:
            rework = {
                "id": db.new_id(),
                "turn_id": turn_id,
                "category": item["category"],
                "description": "Rework of failed item: %s"
                               % item.get("description", ""),
                "estimated_cost_cents": item["actual_cost_cents"],
                "actual_cost_cents": None,
                "classification": "EXPENSE",
                "sequence_rank": services.SEQUENCE_RANK[item["category"]],
                "approval_tier": "NONE",
                "status": "PLANNED",
                "rework_of_item_id": item["id"],
            }
            db.new_common(rework)
            store.scope_items[rework["id"]] = rework
        turn["status"] = "REWORK"
        db.touch(turn)  # version += 1 (PRD §3.7)
        services.sync_turn(turn)
    return created(record)


@bp.get("/make-ready/turns/<turn_id>/inspections")
def list_inspections(turn_id):
    authenticate()
    require_roles(READ_ROLES)
    _get_turn_or_404(turn_id)
    rows = [i for i in store.inspections.values() if i["turn_id"] == turn_id]
    page, pg = paged(rows)
    return ok(page, rtype="array", pagination=pg)


# ---------------------------------------------------------------------------
# Replacement decisions (nested under Turn; PRD §3.6)
# ---------------------------------------------------------------------------

@bp.post("/make-ready/turns/<turn_id>/replacement-decisions")
def create_replacement_decision(turn_id):
    authenticate()
    require_roles(["TurnCoordinator"])
    body = get_body()
    validate_schema(body, DECISION_SCHEMA)
    if body["repair_life_years"] < 1 or body["remaining_life_years"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "repair_life_years and remaining_life_years must be "
                       "at least 1")
    turn = _get_turn_or_404(turn_id)
    item = store.scope_items.get(body["scope_item_id"])
    if item is None or item["turn_id"] != turn_id:
        raise ApiError("ERR_NOT_FOUND", 404, "Scope item not found")
    if item["status"] in ("VOIDED", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Replacement decisions do not apply to VOIDED or "
                       "REJECTED items")
    if item["category"] not in ("APPLIANCE", "FIXTURE"):
        raise ApiError("ERR_DECISION_NOT_APPLICABLE", 422,
                       "Replacement decisions apply only to APPLIANCE or "
                       "FIXTURE items")
    if any(d["scope_item_id"] == item["id"] for d in store.decisions.values()):
        raise ApiError("ERR_DECISION_ALREADY_EXISTS", 422,
                       "A replacement decision already exists for this item")
    prop = services.property_of_turn(turn)
    if body["decision"] == "REPAIR" and not services.repair_economical(
            prop, body["repair_estimate_cents"], body["replace_estimate_cents"],
            body["repair_life_years"], body["remaining_life_years"]):
        raise ApiError("ERR_UNECONOMICAL_REPAIR", 422,
                       "REPAIR decision rejected by the property's "
                       "replacement policy")
    if body["decision"] == "REPLACE":
        classification = ("CAPITAL" if body["replace_estimate_cents"]
                          >= prop["capital_threshold_cents"] else "EXPENSE")
        chosen_estimate = body["replace_estimate_cents"]
    else:
        classification = "EXPENSE"
        chosen_estimate = body["repair_estimate_cents"]
    record = {
        "id": db.new_id(),
        "turn_id": turn_id,
        "scope_item_id": item["id"],
        "repair_estimate_cents": body["repair_estimate_cents"],
        "replace_estimate_cents": body["replace_estimate_cents"],
        "repair_life_years": body["repair_life_years"],
        "remaining_life_years": body["remaining_life_years"],
        "decision": body["decision"],
        "policy_applied": prop["replacement_policy"],
        "resulting_classification": classification,
        "created_at": db.wall_now(),
        "_seq": db.next_seq(),
    }
    store.decisions[record["id"]] = record
    # The decision rewrites the item it judged (PRD §3.6).
    item["estimated_cost_cents"] = chosen_estimate
    item["classification"] = classification
    db.touch(item)
    services.sync_turn(turn)
    return created(record)


@bp.get("/make-ready/turns/<turn_id>/replacement-decisions")
def list_turn_replacement_decisions(turn_id):
    authenticate()
    require_roles(["RegionalManager", "PropertyManager", "TurnCoordinator"])
    _get_turn_or_404(turn_id)
    rows = [d for d in store.decisions.values() if d["turn_id"] == turn_id]
    page, pg = paged(rows)
    return ok(page, rtype="array", pagination=pg)
