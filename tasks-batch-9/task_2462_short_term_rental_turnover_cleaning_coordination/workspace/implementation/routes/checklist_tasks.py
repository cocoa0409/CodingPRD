"""Checklist submission, photo verification and the rework cycle."""

from flask import Blueprint

import errors
import validation as v
from db import db, now, touch
from errors import fail
from middleware import authenticate
from response import ok
from services import lookup
from services.checklist import UNDERWAY_STATUSES, rederive_turnover
from services.pay import find_pay_line, recompute_pay_line, sync_cleaner
from services.serialize import checklist_task_view
from services.stock import book_restock_use, reverse_restock_use
from services.window import MAX_REWORK_ROUNDS

bp = Blueprint("checklist_tasks", __name__)

REVIEW_ACTIONS = ("APPROVE", "REJECT", "WAIVE")


def _turnover_underway(turnover):
    if turnover["status"] not in UNDERWAY_STATUSES:
        fail(errors.ERR_INVALID_TURNOVER_STATE,
             "The turnover is not currently underway.")


@bp.post("/checklist-tasks/<task_id>/submit")
def submit_task(task_id):
    actor = authenticate(("Cleaner",))
    body = v.json_body()
    photo_uri = v.opt_string(body, "photo_uri", allow_empty=False)
    note = v.opt_string(body, "note")
    entries = v.opt_restock_entries(body)

    task = lookup.get_checklist_task(task_id)

    lines = []
    for entry in (entries or []):
        lines.append(lookup.get_supply_line(entry["supply_line_id"]))

    turnover = db.turnovers[task["turnover_id"]]
    lookup.cleaner_scope_turnover(actor, turnover, ("ACCEPTED", "ACTIVE"))

    for line in lines:
        if line["property_id"] != turnover["property_id"]:
            fail(errors.ERR_PROPERTY_MISMATCH,
                 "Every restock entry's supply line must belong to the turnover's property.")

    if task["status"] not in ("PENDING", "REJECTED"):
        fail(errors.ERR_INVALID_TASK_STATE,
             "A task is submitted from PENDING or REJECTED only.")
    _turnover_underway(turnover)

    if task["requires_photo"] and not photo_uri:
        fail(errors.ERR_PHOTO_REQUIRED, "This task requires photographic evidence.")

    if task["category"] == "RESTOCK":
        if not entries:
            fail(errors.ERR_RESTOCK_ENTRIES_REQUIRED,
                 "A RESTOCK task must carry at least one restock entry.")
    elif entries:
        fail(errors.ERR_RESTOCK_ENTRIES_NOT_ALLOWED,
             "A CLEANING or STAGING task may not carry restock entries.")

    for entry, line in zip(entries or [], lines):
        if entry["qty_used"] > line["on_hand_qty"]:
            fail(errors.ERR_INSUFFICIENT_ON_HAND,
                 "qty_used exceeds the supply line's on_hand_qty.")

    task["photo_uri"] = photo_uri
    task["note"] = note
    task["status"] = "SUBMITTED"
    task["submitted_at"] = now()
    task["restock_line_count"] = len(entries or [])
    task["_restock_entries"] = list(entries or [])
    touch(task)

    # No stock moves at submission time: consumption is booked at APPROVE.
    rederive_turnover(turnover)
    return ok(checklist_task_view(task))


@bp.post("/checklist-tasks/<task_id>/review")
def review_task(task_id):
    actor = authenticate(("Coordinator",))
    body = v.json_body()
    action = v.req_enum(body, "action", REVIEW_ACTIONS)
    reject_reason = v.opt_string(body, "reject_reason")

    task = lookup.get_checklist_task(task_id)
    turnover = db.turnovers[task["turnover_id"]]

    if action in ("APPROVE", "REJECT"):
        if task["status"] != "SUBMITTED":
            fail(errors.ERR_INVALID_TASK_STATE,
                 "Only a SUBMITTED task may be approved or rejected.")
    else:
        if task["status"] not in ("PENDING", "REJECTED", "VERIFIED"):
            fail(errors.ERR_INVALID_TASK_STATE,
                 "A WAIVED task may not be waived again.")
    _turnover_underway(turnover)

    prop = db.properties[turnover["property_id"]]
    task["reviewed_by_user_id"] = actor.user_id

    if action == "APPROVE":
        task["status"] = "VERIFIED"
        if task["category"] == "RESTOCK":
            task["restock_charge_cents"] = book_restock_use(
                task, turnover, task.get("_restock_entries") or [])
        touch(task)
        rederive_turnover(turnover)

    elif action == "REJECT":
        task["status"] = "REJECTED"
        task["reject_count"] += 1
        task["reject_reason"] = reject_reason
        touch(task)

        turnover["rejected_review_count"] += 1
        turnover["rework_round"] += 1

        assignment = lookup.working_assignment(turnover["id"])
        cleaner = db.cleaners.get(assignment["cleaner_id"]) if assignment else None

        struck = False
        if turnover["rework_round"] > MAX_REWORK_ROUNDS and not turnover.get("_strike_applied"):
            turnover["escalation_required"] = True
            turnover["_strike_applied"] = True
            if cleaner is not None:
                cleaner["strike_count"] += 1
                struck = True

        # Exactly one turnover version bump for the whole rejection.
        rederive_turnover(turnover, force_bump=True)

        pay_line = find_pay_line(turnover["id"], ("PROVISIONAL",))
        if pay_line is not None:
            recompute_pay_line(pay_line, turnover, prop, cleaner, "PROVISIONAL")
        sync_cleaner(cleaner, force=struck)

    else:
        was_verified_restock = (task["status"] == "VERIFIED"
                               and task["category"] == "RESTOCK")
        task["status"] = "WAIVED"
        if was_verified_restock:
            reverse_restock_use(task, turnover)
            task["restock_charge_cents"] = 0
        touch(task)
        rederive_turnover(turnover)

    return ok(checklist_task_view(task))
