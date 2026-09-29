"""Turnovers: creation, window derivation, offering, starting and completion."""

from flask import Blueprint

import errors
import validation as v
from db import base_fields, db, now, ordered, touch
from errors import fail
from middleware import authenticate
from response import created, ok, ok_list
from services import lookup
from services.cascade import supersede_outstanding_offer
from services.checklist import (
    UNDERWAY_STATUSES,
    all_tasks_closed,
    generate_checklist,
    turnover_tasks,
    verified_restock_chargeback,
)
from services.listing import sort_checklist_tasks, sort_turnovers
from services.matching import (
    candidate_pool,
    daily_cap_reached,
    has_schedule_conflict,
    match_score,
    rank_pool,
    serves_zone,
    zone_match_factor,
)
from services.pay import (
    LEDGER_STATUSES,
    compute_pay,
    create_pay_line,
    find_pay_line,
    recompute_pay_line,
    sync_cleaner,
    turnover_pay_lines,
)
from services.serialize import (
    assignment_view,
    checklist_task_view,
    pay_preview_view,
    turnover_view,
)
from services.window import (
    apply_window,
    preview_recompute,
    whole_minutes,
)

bp = Blueprint("turnovers", __name__)

TURNOVER_STATUSES = (
    "PENDING_ASSIGNMENT", "SCHEDULED", "IN_PROGRESS", "AWAITING_VERIFICATION",
    "REWORK_REQUIRED", "ON_HOLD", "COMPLETED", "VOID",
)
TURN_TYPES = ("SAME_DAY", "OVERNIGHT", "VACANT_GAP")
TASK_STATUSES = ("PENDING", "SUBMITTED", "VERIFIED", "REJECTED", "WAIVED")
TASK_CATEGORIES = ("CLEANING", "STAGING", "RESTOCK")
BOUNDARY_STATUSES = ("SCHEDULED", "CHECKED_OUT")


@bp.post("/turnovers")
def create_turnover():
    authenticate(("Coordinator",))
    body = v.json_body()
    outgoing_booking_id = v.req_string(body, "outgoing_booking_id", allow_empty=False)
    incoming_booking_id = v.opt_string(body, "incoming_booking_id", allow_empty=False)
    override_reason = v.opt_string(body, "override_reason")

    outgoing = lookup.get_booking(outgoing_booking_id)
    incoming = lookup.get_booking(incoming_booking_id) if incoming_booking_id else None

    if incoming is not None and incoming["property_id"] != outgoing["property_id"]:
        fail(errors.ERR_PROPERTY_MISMATCH,
             "The two nominated stays belong to different units.")

    if outgoing["status"] not in BOUNDARY_STATUSES:
        fail(errors.ERR_BOOKING_NOT_SCHEDULED,
             "A CANCELLED stay is never a turnover boundary.")
    if incoming is not None and incoming["status"] not in BOUNDARY_STATUSES:
        fail(errors.ERR_BOOKING_NOT_SCHEDULED,
             "A CANCELLED stay is never a turnover boundary.")

    prop = db.properties[outgoing["property_id"]]
    if prop["status"] != "ACTIVE":
        fail(errors.ERR_PROPERTY_NOT_ACTIVE,
             "Only an ACTIVE unit accepts a new turnover.")

    if incoming is not None and incoming["checkin_at"] < outgoing["checkout_at"]:
        fail(errors.ERR_INVALID_TIME_INTERVAL,
             "The arriving stay's checkin_at precedes the departing stay's checkout_at.")

    derived = preview_recompute(None, prop, outgoing, incoming, incoming_is_set=True)
    if derived["raw_window_minutes"] <= 0:
        fail(errors.ERR_CLEANING_WINDOW_NON_POSITIVE,
             "The derived cleaning window is not strictly positive.")
    if derived["window_minutes"] < derived["required_minutes"] and not override_reason:
        fail(errors.ERR_WINDOW_OVERRIDE_REQUIRED,
             "The window is shorter than required_minutes and no override_reason was supplied.")

    for existing in db.turnovers.values():
        if existing["outgoing_booking_id"] == outgoing["id"] and existing["status"] != "VOID":
            fail(errors.ERR_TURNOVER_ALREADY_EXISTS,
                 "This departing stay already carries a live turnover.")

    record = base_fields()
    record.update({
        "property_id": prop["id"],
        "outgoing_booking_id": outgoing["id"],
        "incoming_booking_id": incoming["id"] if incoming is not None else None,
        "blocking_repair_order_id": None,
        "window_start_at": None,
        "window_end_at": None,
        "window_minutes": 0,
        "required_minutes": 0,
        "slack_minutes": 0,
        "turn_type": None,
        "is_tight": False,
        "override_reason": override_reason,
        "escalation_required": False,
        "status": "PENDING_ASSIGNMENT",
        "pre_hold_status": None,
        "rework_round": 0,
        "rejected_review_count": 0,
        "checklist_task_count": 0,
        "restock_chargeback_cents": 0,
        "started_at": None,
        "finished_at": None,
        "late_minutes": 0,
        "_strike_applied": False,
    })
    apply_window(record, derived)
    db.turnovers[record["id"]] = record
    return created(turnover_view(record))


@bp.get("/turnovers")
def list_turnovers():
    actor = authenticate(("PlatformAdmin", "Coordinator", "QualityAuditor", "PropertyOwner"))
    limit, offset = v.pagination()
    property_id = v.query_string("property_id")
    outgoing_booking_id = v.query_string("outgoing_booking_id")
    incoming_booking_id = v.query_string("incoming_booking_id")
    blocking_repair_order_id = v.query_string("blocking_repair_order_id")
    status = v.query_enum("status", TURNOVER_STATUSES)
    turn_type = v.query_enum("turn_type", TURN_TYPES)

    lookup.owner_scope_list(actor, property_id)

    rows = list(db.turnovers.values())
    if property_id is not None:
        rows = [t for t in rows if t["property_id"] == property_id]
    if outgoing_booking_id is not None:
        rows = [t for t in rows if t["outgoing_booking_id"] == outgoing_booking_id]
    if incoming_booking_id is not None:
        rows = [t for t in rows if t.get("incoming_booking_id") == incoming_booking_id]
    if blocking_repair_order_id is not None:
        rows = [t for t in rows
                if t.get("blocking_repair_order_id") == blocking_repair_order_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    if turn_type is not None:
        rows = [t for t in rows if t["turn_type"] == turn_type]
    rows = sort_turnovers(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([turnover_view(r) for r in page], limit, offset, total)


@bp.get("/turnovers/<turnover_id>")
def read_turnover(turnover_id):
    actor = authenticate(("PlatformAdmin", "Coordinator", "Cleaner", "QualityAuditor",
                          "PropertyOwner"))
    turnover = lookup.get_turnover(turnover_id)
    lookup.owner_scope_resource(actor, turnover["property_id"])
    return ok(turnover_view(turnover))


@bp.get("/turnovers/<turnover_id>/checklist-tasks")
def list_turnover_tasks(turnover_id):
    authenticate(("PlatformAdmin", "Coordinator", "Cleaner", "QualityAuditor"))
    limit, offset = v.pagination()
    status = v.query_enum("status", TASK_STATUSES)
    category = v.query_enum("category", TASK_CATEGORIES)

    turnover = lookup.get_turnover(turnover_id)
    rows = turnover_tasks(turnover["id"])
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    if category is not None:
        rows = [t for t in rows if t["category"] == category]
    rows = sort_checklist_tasks(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([checklist_task_view(r) for r in page], limit, offset, total)


@bp.get("/turnovers/<turnover_id>/pay-preview")
def pay_preview(turnover_id):
    authenticate(("PlatformAdmin", "Coordinator", "Cleaner"))
    turnover = lookup.get_turnover(turnover_id)
    prop = db.properties[turnover["property_id"]]
    assignment = lookup.working_assignment(turnover["id"])
    cleaner = db.cleaners.get(assignment["cleaner_id"]) if assignment else None
    variant = "FINAL" if turnover["status"] == "COMPLETED" else "PROVISIONAL"

    adjustment = 0
    for pay_line in turnover_pay_lines(turnover["id"]):
        if pay_line["status"] in LEDGER_STATUSES:
            adjustment = pay_line["audit_adjustment_cents"]
            break

    numbers = compute_pay(turnover, prop, cleaner, variant, adjustment)
    return ok(pay_preview_view(numbers, turnover, assignment, cleaner))


@bp.post("/turnovers/<turnover_id>/assign")
def assign_turnover(turnover_id):
    actor = authenticate(("Coordinator",))
    body = v.json_body()
    expected_version = v.req_int(body, "expected_turnover_version")
    cleaner_id = v.opt_string(body, "cleaner_id", allow_empty=False)
    exclude_ids = v.opt_string_list(body, "exclude_cleaner_ids", None)

    turnover = lookup.get_turnover(turnover_id)

    explicit_cleaner = lookup.get_cleaner(cleaner_id) if cleaner_id else None
    for excluded in (exclude_ids or []):
        lookup.get_cleaner(excluded)

    if expected_version != turnover["version"]:
        fail(errors.ERR_STALE_TURNOVER_VERSION,
             "Expected turnover version %s but the turnover is at %s."
             % (expected_version, turnover["version"]))
    if turnover["status"] != "PENDING_ASSIGNMENT":
        fail(errors.ERR_INVALID_TURNOVER_STATE,
             "An offer may only be created on a PENDING_ASSIGNMENT turnover.")

    prop = db.properties[turnover["property_id"]]

    if explicit_cleaner is not None:
        selection_mode = "EXPLICIT"
        cleaner = explicit_cleaner
        if cleaner["status"] != "ACTIVE":
            fail(errors.ERR_CLEANER_NOT_ACTIVE, "Only an ACTIVE cleaner may be offered work.")
        if has_schedule_conflict(cleaner, turnover):
            fail(errors.ERR_CLEANER_SCHEDULE_CONFLICT,
                 "The cleaner's existing assignment windows collide with this turnover.")
        if not serves_zone(cleaner, prop) or cleaner["skill_level"] < prop["min_skill_level"]:
            fail(errors.ERR_CLEANER_NOT_ELIGIBLE,
                 "The cleaner does not serve this zone or sits below the required skill tier.")
        if daily_cap_reached(cleaner, turnover):
            fail(errors.ERR_CLEANER_DAILY_CAP_REACHED,
                 "The cleaner is already at its daily turnover ceiling.")
    else:
        selection_mode = "SELECTOR"
        pool = candidate_pool(turnover, prop, exclude_ids)
        if not pool:
            fail(errors.ERR_NO_ELIGIBLE_CLEANER,
                 "No cleaner survived the candidate filters.")
        cleaner = rank_pool(pool, turnover, prop)[0]

    supersede_outstanding_offer(turnover)

    sequence_no = len(lookup.turnover_assignments(turnover["id"])) + 1
    assignment = base_fields()
    assignment.update({
        "turnover_id": turnover["id"],
        "cleaner_id": cleaner["id"],
        "sequence_no": sequence_no,
        "match_score": match_score(cleaner, prop),
        "zone_match_factor": zone_match_factor(cleaner, prop),
        "selection_mode": selection_mode,
        "assigned_by_user_id": actor.user_id,
        "status": "OFFERED",
        "accepted_at": None,
        "declined_at": None,
        "revoked_at": None,
    })
    db.assignments[assignment["id"]] = assignment
    touch(turnover)
    return created(assignment_view(assignment))


@bp.post("/turnovers/<turnover_id>/start")
def start_turnover(turnover_id):
    actor = authenticate(("Cleaner",))
    turnover = lookup.get_turnover(turnover_id)
    lookup.cleaner_scope_turnover(actor, turnover, ("ACCEPTED", "ACTIVE"))

    if turnover["status"] != "SCHEDULED":
        fail(errors.ERR_INVALID_TURNOVER_STATE,
             "The clean may only begin from a SCHEDULED turnover.")

    outgoing = db.bookings[turnover["outgoing_booking_id"]]
    if outgoing["status"] != "CHECKED_OUT":
        fail(errors.ERR_GUEST_NOT_CHECKED_OUT,
             "The departing stay must already be CHECKED_OUT.")
    if now() < turnover["window_start_at"]:
        fail(errors.ERR_TOO_EARLY_TO_START,
             "The clock has not yet reached window_start_at.")

    assignment = lookup.turnover_assignment_in(turnover["id"], ("ACCEPTED",))
    if assignment is not None:
        assignment["status"] = "ACTIVE"
        touch(assignment)

    prop = db.properties[turnover["property_id"]]
    turnover["status"] = "IN_PROGRESS"
    turnover["started_at"] = now()
    generate_checklist(turnover, prop)
    touch(turnover)
    return ok(turnover_view(turnover))


@bp.post("/turnovers/<turnover_id>/complete")
def complete_turnover(turnover_id):
    actor = authenticate(("Cleaner", "Coordinator"))
    body = v.json_body()
    v.opt_string(body, "completion_note")

    turnover = lookup.get_turnover(turnover_id)
    lookup.cleaner_scope_turnover(actor, turnover, ("ACCEPTED", "ACTIVE"))

    if turnover["status"] != "AWAITING_VERIFICATION":
        fail(errors.ERR_INVALID_TURNOVER_STATE,
             "A clean is closed out from AWAITING_VERIFICATION.")
    if not all_tasks_closed(turnover):
        fail(errors.ERR_UNVERIFIED_TASKS_REMAIN,
             "Every checklist task must be VERIFIED or WAIVED.")

    finished_at = now()
    late = whole_minutes(finished_at - turnover["window_end_at"])
    turnover["status"] = "COMPLETED"
    turnover["finished_at"] = finished_at
    turnover["late_minutes"] = late if late > 0 else 0
    turnover["restock_chargeback_cents"] = verified_restock_chargeback(turnover)
    touch(turnover)

    prop = db.properties[turnover["property_id"]]
    prop["last_turnover_completed_at"] = finished_at
    touch(prop)

    assignment = lookup.turnover_assignment_in(turnover["id"], ("ACTIVE",))
    cleaner = None
    if assignment is not None:
        assignment["status"] = "COMPLETED"
        touch(assignment)
        cleaner = db.cleaners.get(assignment["cleaner_id"])

    pay_line = find_pay_line(turnover["id"], ("PROVISIONAL",))
    if pay_line is not None:
        pay_line["status"] = "FINAL"
        recompute_pay_line(pay_line, turnover, prop, cleaner, "FINAL")
    sync_cleaner(cleaner)

    return ok(turnover_view(turnover))
