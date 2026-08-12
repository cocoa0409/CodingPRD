"""RepairItem intake, triage (OCC + supersession), queueing, assignment,
outcome recording, and withdrawal."""

from flask import Blueprint, g

import db
import serializers as ser
import services
from errors import (
    ERR_EVENT_NOT_ACCEPTING_INTAKE,
    ERR_EVENT_NOT_FOUND,
    ERR_EVENT_PHASE_FORBIDS,
    ERR_EVENT_STATION_MISMATCH,
    ERR_FIXER_BUSY,
    ERR_FIXER_NOT_FOUND,
    ERR_FIXER_SUSPENDED,
    ERR_INTAKE_CAP_REACHED,
    ERR_INVALID_ITEM_STATE,
    ERR_ITEM_NOT_FOUND,
    ERR_NO_ELIGIBLE_FIXER,
    ERR_NOT_ASSIGNED_FIXER,
    ERR_POSTURE_RESTRICTED,
    ERR_RELIABILITY_TOO_LOW,
    ERR_SKILL_LEVEL_INSUFFICIENT,
    ERR_SKILL_MISMATCH,
    ERR_STALE_VERSION,
    ERR_STATION_NOT_FOUND,
    ERR_STATION_NOT_OPEN,
    ERR_TRIAGE_NOT_FOUND,
    ERR_VISITOR_NOT_FOUND,
    ERR_WAIVER_EXPIRED,
    ERR_WAIVER_REQUIRED,
    ERR_WAIVER_SAFETY_CLAUSE_REQUIRED,
    raise_err,
)
from middleware import require_roles
from response import success
from util import (
    as_bool,
    as_enum,
    as_int,
    as_num,
    as_str,
    body,
    list_response,
    opt,
    req,
)

bp = Blueprint("items", __name__)

ALL_ROLES = ("Coordinator", "IntakeVolunteer", "Fixer", "SafetyOfficer")
ITEM_CATEGORIES = ("ELECTRONICS", "TEXTILE", "BIKE")
OUTCOME_VALUES = ("FIXED", "PARTIALLY_FIXED", "NOT_REPAIRABLE")


def get_item_or_404(item_id):
    item = db.items.get(item_id)
    if item is None:
        raise_err(ERR_ITEM_NOT_FOUND, "RepairItem %s does not exist" % item_id)
    return item


# ------------------------------------------------------------- item intake ---

@bp.post("/api/repair-items")
@require_roles("IntakeVolunteer")
def create_item():
    b = body()
    # Existence (priority 3): body FKs in declared order.
    event_id = as_str(req(b, "event_id"), "event_id")
    event = db.events.get(event_id)
    if event is None:
        raise_err(ERR_EVENT_NOT_FOUND, "RepairEvent %s does not exist" % event_id)
    visitor_id = as_str(req(b, "visitor_id"), "visitor_id")
    if visitor_id not in db.visitors:
        raise_err(ERR_VISITOR_NOT_FOUND, "Visitor %s does not exist" % visitor_id)
    category = as_enum(req(b, "category"), "category", ITEM_CATEGORIES)
    description = as_str(req(b, "description"), "description")
    hazard_flag = as_bool(opt(b, "hazard_flag", False), "hazard_flag")
    weight = as_num(req(b, "weight_kg_estimated"), "weight_kg_estimated", lo=0.1)

    # State (priority 4): intake phase + derived posture gate.
    if event["status"] != "INTAKE_OPEN":
        raise_err(ERR_EVENT_NOT_ACCEPTING_INTAKE, "Event is not in INTAKE_OPEN status")
    if services.posture(event) != "ACCEPTING":
        raise_err(ERR_POSTURE_RESTRICTED, "Event posture is RESTRICTED")

    # Waiver gates (priority 5).
    waivers = services.waivers_of_visitor(visitor_id)
    for w in waivers:
        services.refresh_waiver(w)
    valid = [w for w in waivers if services.waiver_still_valid(w)]
    if not valid:
        if any(w["status"] == "EXPIRED" for w in waivers):
            raise_err(ERR_WAIVER_EXPIRED, "The visitor's waiver has expired")
        raise_err(ERR_WAIVER_REQUIRED, "The visitor holds no ACTIVE waiver")
    if hazard_flag and not any(w["safety_clause_accepted"] for w in valid):
        raise_err(
            ERR_WAIVER_SAFETY_CLAUSE_REQUIRED,
            "Hazardous item requires an accepted safety clause",
        )

    # Capacity / quota (priority 12, always last).
    if services.active_item_count(event_id) >= event["intake_item_cap"]:
        raise_err(ERR_INTAKE_CAP_REACHED, "Event intake item cap reached")

    rec = db.stamp_new(
        {
            "event_id": event_id,
            "visitor_id": visitor_id,
            "category": category,
            "description": description,
            "hazard_flag": hazard_flag,
            "weight_kg_estimated": weight,
            "status": "REGISTERED",
            "assigned_station_id": None,
            "assigned_fixer_id": None,
            "priority_score": 0,
            "required_skill_level": 0,
        }
    )
    db.items[rec["id"]] = rec
    return success(ser.item(rec), 201)


@bp.get("/api/repair-items")
@require_roles(*ALL_ROLES)
def list_items():
    return list_response(
        db.items.values(),
        ser.item,
        [
            ("event_id", "event_id"),
            ("visitor_id", "visitor_id"),
            ("assigned_station_id", "assigned_station_id"),
            ("assigned_fixer_id", "assigned_fixer_id"),
            ("status", "status"),
        ],
    )


@bp.get("/api/repair-items/<item_id>")
@require_roles(*ALL_ROLES)
def get_item(item_id):
    return success(ser.item(get_item_or_404(item_id)), 200)


# ------------------------------------------------------------------ triage ---

@bp.post("/api/repair-items/<item_id>/triage-records")
@require_roles("Fixer")
def create_triage(item_id):
    item = get_item_or_404(item_id)
    b = body()
    # The acting Fixer's X-User-ID is a FixerProfile id.
    fixer = db.fixers.get(g.user_id)
    if fixer is None:
        raise_err(ERR_FIXER_NOT_FOUND, "FixerProfile %s does not exist" % g.user_id)
    severity = as_int(req(b, "severity"), "severity", lo=1, hi=10)
    difficulty = as_int(req(b, "estimated_difficulty"), "estimated_difficulty", lo=1, hi=5)
    diagnosis = as_str(req(b, "diagnosis"), "diagnosis")
    expected_version = as_int(req(b, "expected_item_version"), "expected_item_version")

    # State (priority 4): triage is allowed only in REGISTERED / TRIAGED / QUEUED.
    if item["status"] not in ("REGISTERED", "TRIAGED", "QUEUED"):
        raise_err(ERR_INVALID_ITEM_STATE, "Item cannot be triaged in its current state")
    # OCC: expected_item_version must match the item's current version.
    if expected_version != item["version"]:
        raise_err(ERR_STALE_VERSION, "expected_item_version does not match item version")
    # Active-fixer requirement (priority 10).
    if fixer["status"] != "ACTIVE":
        raise_err(ERR_FIXER_SUSPENDED, "Fixer is not ACTIVE")

    previous = services.current_triage(item["id"])
    rec = db.stamp_new(
        {
            "item_id": item["id"],
            "assessor_fixer_id": g.user_id,
            "severity": severity,
            "estimated_difficulty": difficulty,
            "diagnosis": diagnosis,
            "superseded_by_id": None,
        },
        with_version=False,
    )
    db.triage_records[rec["id"]] = rec
    if previous is not None:
        previous["superseded_by_id"] = rec["id"]

    item["priority_score"] = services.priority_score(
        item["category"], severity, difficulty, item["hazard_flag"]
    )
    item["required_skill_level"] = difficulty
    if item["status"] == "REGISTERED":
        item["status"] = "TRIAGED"
    db.touch(item)

    # severity >= 8 auto-creates a CRITICAL SafetyIncident linked to item + event.
    if severity >= 8:
        inc = db.stamp_new(
            {
                "event_id": item["event_id"],
                "item_id": item["id"],
                "fixer_id": None,
                "reported_by_user_id": g.user_id,
                "severity": "CRITICAL",
                "description": "Auto-escalated from triage severity >= 8",
                "status": "REPORTED",
                "resolution_action": None,
            }
        )
        db.incidents[inc["id"]] = inc

    return success(ser.triage(rec), 201)


@bp.get("/api/triage-records")
@require_roles(*ALL_ROLES)
def list_triage():
    return list_response(
        db.triage_records.values(),
        ser.triage,
        [
            ("item_id", "item_id"),
            ("assessor_fixer_id", "assessor_fixer_id"),
            ("superseded_by_id", "superseded_by_id"),
        ],
    )


@bp.get("/api/triage-records/<triage_id>")
@require_roles(*ALL_ROLES)
def get_triage(triage_id):
    rec = db.triage_records.get(triage_id)
    if rec is None:
        raise_err(ERR_TRIAGE_NOT_FOUND, "TriageRecord %s does not exist" % triage_id)
    return success(ser.triage(rec), 200)


# -------------------------------------------------------------- queue moves ---

@bp.post("/api/repair-items/<item_id>/enqueue")
@require_roles("Coordinator")
def enqueue_item(item_id):
    item = get_item_or_404(item_id)
    if item["status"] != "TRIAGED":
        raise_err(ERR_INVALID_ITEM_STATE, "Only a TRIAGED item can be enqueued")
    item["status"] = "QUEUED"
    db.touch(item)
    return success(ser.item(item), 200)


def _skill_for(fixer_id, category):
    for sk in db.skills.values():
        if sk["fixer_id"] == fixer_id and sk["category"] == category:
            return sk
    return None


def _fixer_busy(fixer_id):
    return any(
        it["assigned_fixer_id"] == fixer_id and it["status"] in ("ASSIGNED", "IN_REPAIR")
        for it in db.items.values()
    )


def _checked_in_shift_at(fixer_id, station_ids):
    """The fixer's earliest checked-in shift among the candidate stations."""
    best = None
    for s in db.shifts.values():
        if (
            s["fixer_id"] == fixer_id
            and s["status"] == "CHECKED_IN"
            and s["station_id"] in station_ids
        ):
            if best is None or (db.parse_dt(s["checked_in_at"]), s["_seq"]) < (
                db.parse_dt(best["checked_in_at"]),
                best["_seq"],
            ):
                best = s
    return best


def _eligible(fixer, item, station_ids):
    """Silent eligibility predicate used by the auto-select pool."""
    shift = _checked_in_shift_at(fixer["id"], station_ids)
    if shift is None:
        return None
    sk = _skill_for(fixer["id"], item["category"])
    if sk is None or sk["level"] < item["required_skill_level"]:
        return None
    if services.reliability(fixer["id"]) < services.RELIABILITY_THRESHOLD:
        return None
    if fixer["status"] != "ACTIVE":
        return None
    if _fixer_busy(fixer["id"]):
        return None
    return shift


@bp.post("/api/repair-items/<item_id>/assign")
@require_roles("Coordinator")
def assign_item(item_id):
    item = get_item_or_404(item_id)
    b = body()
    fixer_id = opt(b, "fixer_id")
    station_id = opt(b, "station_id")
    if fixer_id is not None:
        as_str(fixer_id, "fixer_id")
    if station_id is not None:
        as_str(station_id, "station_id")
    # Existence (priority 3), body FKs in declared order.
    fixer = None
    if fixer_id is not None:
        fixer = db.fixers.get(fixer_id)
        if fixer is None:
            raise_err(ERR_FIXER_NOT_FOUND, "FixerProfile %s does not exist" % fixer_id)
    station = None
    if station_id is not None:
        station = db.stations.get(station_id)
        if station is None:
            raise_err(ERR_STATION_NOT_FOUND, "Station %s does not exist" % station_id)

    # State (priority 4).
    if item["status"] != "QUEUED":
        raise_err(ERR_INVALID_ITEM_STATE, "Only a QUEUED item can be assigned")
    event = db.events[item["event_id"]]
    if event["status"] not in ("INTAKE_OPEN", "REPAIR_ACTIVE"):
        raise_err(ERR_EVENT_PHASE_FORBIDS, "Event phase forbids assignment")

    if station is not None:
        if station["status"] != "OPEN":
            raise_err(ERR_STATION_NOT_OPEN, "Station is not OPEN")
        # Station-category mismatch (priority 10 error) precedes event mismatch (11).
        if station["category"] != item["category"]:
            raise_err(ERR_SKILL_MISMATCH, "Station category does not match item category")
        if station["event_id"] != item["event_id"]:
            raise_err(ERR_EVENT_STATION_MISMATCH, "Station belongs to another event")
        candidate_station_ids = {station["id"]}
    else:
        candidate_station_ids = {
            s["id"]
            for s in db.stations.values()
            if s["event_id"] == item["event_id"]
            and s["category"] == item["category"]
            and s["status"] == "OPEN"
        }

    if fixer is not None:
        # Explicit assignment: pinned eligibility order (PRD §3.4).
        shift = _checked_in_shift_at(fixer["id"], candidate_station_ids)
        if shift is None:
            raise_err(ERR_NO_ELIGIBLE_FIXER, "Fixer is not checked in at a qualifying station")
        sk = _skill_for(fixer["id"], item["category"])
        if sk is None:
            raise_err(ERR_SKILL_MISMATCH, "Fixer skill category does not match item category")
        if sk["level"] < item["required_skill_level"]:
            raise_err(ERR_SKILL_LEVEL_INSUFFICIENT, "Fixer skill level is too low")
        if services.reliability(fixer["id"]) < services.RELIABILITY_THRESHOLD:
            raise_err(ERR_RELIABILITY_TOO_LOW, "Reliability score is below 40")
        if fixer["status"] != "ACTIVE":
            raise_err(ERR_FIXER_SUSPENDED, "Fixer is not ACTIVE")
        if _fixer_busy(fixer["id"]):
            raise_err(ERR_FIXER_BUSY, "Fixer already has an item assigned or in repair")
        chosen_fixer, chosen_shift = fixer, shift
    else:
        # Auto-select: rank by reliability DESC, tie-break by checked_in_at ASC.
        pool = []
        for fx in db.fixers.values():
            shift = _eligible(fx, item, candidate_station_ids)
            if shift is not None:
                pool.append((fx, shift))
        if not pool:
            raise_err(ERR_NO_ELIGIBLE_FIXER, "No eligible fixer is available")
        pool.sort(
            key=lambda p: (
                -services.reliability(p[0]["id"]),
                db.parse_dt(p[1]["checked_in_at"]),
                p[1]["_seq"],
            )
        )
        chosen_fixer, chosen_shift = pool[0]

    item["assigned_fixer_id"] = chosen_fixer["id"]
    item["assigned_station_id"] = chosen_shift["station_id"]
    item["status"] = "ASSIGNED"
    db.touch(item)
    return success(ser.item(item), 200)


@bp.post("/api/repair-items/<item_id>/start-repair")
@require_roles("Fixer")
def start_repair(item_id):
    item = get_item_or_404(item_id)
    if g.user_id != item["assigned_fixer_id"]:
        raise_err(ERR_NOT_ASSIGNED_FIXER, "Only the assigned fixer may start the repair")
    if item["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_ITEM_STATE, "Only an ASSIGNED item can enter repair")
    item["status"] = "IN_REPAIR"
    db.touch(item)
    return success(ser.item(item), 200)


@bp.post("/api/repair-items/<item_id>/return-to-queue")
@require_roles("Coordinator", "Fixer")
def return_to_queue(item_id):
    item = get_item_or_404(item_id)
    if g.role == "Fixer" and g.user_id != item["assigned_fixer_id"]:
        raise_err(ERR_NOT_ASSIGNED_FIXER, "Only the assigned fixer may return the item")
    if item["status"] != "IN_REPAIR":
        raise_err(ERR_INVALID_ITEM_STATE, "Only an IN_REPAIR item can return to the queue")
    # RESERVED part reservations are deliberately KEPT.
    item["assigned_fixer_id"] = None
    item["assigned_station_id"] = None
    item["status"] = "QUEUED"
    db.touch(item)
    return success(ser.item(item), 200)


@bp.post("/api/repair-items/<item_id>/unassign")
@require_roles("Coordinator")
def unassign_item(item_id):
    item = get_item_or_404(item_id)
    if item["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_ITEM_STATE, "Only an ASSIGNED item can be unassigned")
    item["assigned_fixer_id"] = None
    item["assigned_station_id"] = None
    item["status"] = "QUEUED"
    db.touch(item)
    return success(ser.item(item), 200)


@bp.post("/api/repair-items/<item_id>/reopen")
@require_roles("Coordinator")
def reopen_item(item_id):
    item = get_item_or_404(item_id)
    if item["status"] != "OUTCOME_RECORDED":
        raise_err(ERR_INVALID_ITEM_STATE, "Only an OUTCOME_RECORDED item can be reopened")
    outcomes = sorted(
        (o for o in db.outcomes.values() if o["item_id"] == item["id"]),
        key=lambda o: o["_seq"],
    )
    latest = outcomes[-1] if outcomes else None
    if (
        latest is None
        or latest["outcome"] != "NOT_REPAIRABLE"
        or latest["verification_status"] != "RECORDED"
    ):
        raise_err(
            ERR_INVALID_ITEM_STATE,
            "Latest outcome must be NOT_REPAIRABLE and still RECORDED",
        )
    item["assigned_fixer_id"] = None
    item["assigned_station_id"] = None
    item["status"] = "QUEUED"
    db.touch(item)
    return success(ser.item(item), 200)


@bp.post("/api/repair-items/<item_id>/withdraw")
@require_roles("Coordinator", "IntakeVolunteer")
def withdraw_item(item_id):
    item = get_item_or_404(item_id)
    if item["status"] in ("VERIFIED", "WITHDRAWN"):
        raise_err(ERR_INVALID_ITEM_STATE, "A terminal item cannot be withdrawn")
    for r in db.reservations.values():
        if r["repair_item_id"] == item["id"] and r["status"] == "RESERVED":
            services.release_reservation(r)
    item["assigned_fixer_id"] = None
    item["assigned_station_id"] = None
    item["status"] = "WITHDRAWN"
    db.touch(item)
    return success(ser.item(item), 200)


# ------------------------------------------------------- outcome recording ---

@bp.post("/api/repair-items/<item_id>/outcomes")
@require_roles("Fixer")
def create_outcome(item_id):
    item = get_item_or_404(item_id)
    b = body()
    outcome_value = as_enum(req(b, "outcome"), "outcome", OUTCOME_VALUES)
    weight_actual = opt(b, "weight_kg_actual")
    if weight_actual is not None:
        as_num(weight_actual, "weight_kg_actual", lo=0)
    # Ownership (403) precedes the state check per the global priority order.
    if g.user_id != item["assigned_fixer_id"]:
        raise_err(ERR_NOT_ASSIGNED_FIXER, "Only the assigned fixer may record the outcome")
    if item["status"] != "IN_REPAIR":
        raise_err(ERR_INVALID_ITEM_STATE, "Only an IN_REPAIR item can receive an outcome")

    parts_cost = sum(
        r["cost_cents"]
        for r in db.reservations.values()
        if r["repair_item_id"] == item["id"] and r["status"] == "COMMITTED"
    )
    suggested = services.suggested_donation_cents(item["category"], parts_cost)
    rec = db.stamp_new(
        {
            "item_id": item["id"],
            "fixer_id": g.user_id,
            "outcome": outcome_value,
            "weight_kg_actual": weight_actual,
            "parts_cost_cents": parts_cost,
            "suggested_donation_cents": suggested,
            "verification_status": "RECORDED",
            "verified_by_user_id": None,
        }
    )
    db.outcomes[rec["id"]] = rec
    # assigned_* are null outside ASSIGNED / IN_REPAIR.
    item["assigned_fixer_id"] = None
    item["assigned_station_id"] = None
    item["status"] = "OUTCOME_RECORDED"
    db.touch(item)
    return success(ser.outcome(rec), 201)
