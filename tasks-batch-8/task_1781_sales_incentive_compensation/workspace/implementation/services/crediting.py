"""Credit posting, reversal, and cascade logic per scaffold state machines."""
from db import db
from util import new_id, now_ts, touch
from services.calculations import (
    compute_rollup_amount,
    recompute_assignment_indicators,
)


def get_program_for_assignment(assignment):
    return db["programs"][assignment["program_id"]]


def post_credit_entry(entry, program):
    """Run the full POSTED side effects for a credit entry.

    1. Set status=POSTED, posted_period_index=current period
    2. Increment assignment earned (raw for both types; track rollup portion)
    3. For DIRECT entries: spawn ROLLUP if conditions met
    4. Recompute assignment indicators
    """
    entry["status"] = "POSTED"
    entry["posted_period_index"] = program["current_period_index"]
    touch(entry)

    assignment = db["assignments"][entry["assignment_id"]]
    assignment["current_period_earned_cents"] += entry["credit_amount_cents"]
    if entry["credit_type"] == "ROLLUP":
        assignment["_rollup_earned_cents"] = (
            assignment.get("_rollup_earned_cents", 0) + entry["credit_amount_cents"]
        )
    touch(assignment)

    # Spawn rollup for DIRECT entries only (one level)
    if entry["credit_type"] == "DIRECT":
        plan = db["plans"][assignment["plan_id"]]
        maybe_spawn_rollup(entry, assignment, plan, program)

    recompute_assignment_indicators(assignment)


def maybe_spawn_rollup(source_entry, source_assignment, plan, program):
    """Spawn a ROLLUP credit entry for the direct manager, if applicable.

    Conditions: credited rep has manager_id; manager has ACTIVE assignment
    on the SAME plan. Rollup lands POSTED if manager's assignment is ACCEPTED,
    else PENDING.
    """
    rep = db["reps"].get(source_entry["rep_id"])
    if rep is None or not rep.get("manager_id"):
        return

    manager_id = rep["manager_id"]

    # Find manager's ACTIVE assignment on the same plan
    manager_asg = None
    for a in db["assignments"].values():
        if (
            a["rep_id"] == manager_id
            and a["plan_id"] == plan["id"]
            and a["status"] == "ACTIVE"
        ):
            manager_asg = a
            break

    if manager_asg is None:
        return

    rollup_amount = compute_rollup_amount(
        source_entry["credit_amount_cents"], plan["rollup_rate_bps"]
    )

    rollup_status = (
        "POSTED" if manager_asg["acceptance_status"] == "ACCEPTED" else "PENDING"
    )
    posted_period = (
        program["current_period_index"] if rollup_status == "POSTED" else None
    )

    ts = now_ts()
    rollup_entry = {
        "id": new_id(),
        "transaction_id": source_entry["transaction_id"],
        "assignment_id": manager_asg["id"],
        "rep_id": manager_id,
        "parent_credit_id": source_entry["id"],
        "credit_type": "ROLLUP",
        "credit_amount_cents": rollup_amount,
        "posted_period_index": posted_period,
        "status": rollup_status,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db["credit_entries"][rollup_entry["id"]] = rollup_entry

    if rollup_status == "POSTED":
        # Run posting side effects for manager's assignment
        manager_asg["current_period_earned_cents"] += rollup_amount
        manager_asg["_rollup_earned_cents"] = (
            manager_asg.get("_rollup_earned_cents", 0) + rollup_amount
        )
        touch(manager_asg)
        recompute_assignment_indicators(manager_asg)
    else:
        # A PENDING rollup is still a credit change on the manager's
        # assignment and counts toward its provisional estimate.
        recompute_assignment_indicators(manager_asg)


def reverse_credit_entry(entry, program):
    """Reverse a credit entry with appropriate side effects.

    - PENDING -> REVERSED: no earned impact
    - POSTED (current period) -> REVERSED: decrement earned
    - LOCKED -> REVERSED: create CLAWBACK adjustment
    - Cascade: ROLLUP children in {PENDING, POSTED} also reversed
    """
    old_status = entry["status"]
    entry["status"] = "REVERSED"
    touch(entry)

    assignment = db["assignments"][entry["assignment_id"]]

    if old_status == "PENDING":
        # Held credit withdrawn from the provisional estimate.
        recompute_assignment_indicators(assignment)
    elif old_status == "POSTED":
        if entry["posted_period_index"] == program["current_period_index"]:
            assignment["current_period_earned_cents"] -= entry["credit_amount_cents"]
            if entry["credit_type"] == "ROLLUP":
                assignment["_rollup_earned_cents"] = (
                    assignment.get("_rollup_earned_cents", 0)
                    - entry["credit_amount_cents"]
                )
            touch(assignment)
            recompute_assignment_indicators(assignment)

    elif old_status == "LOCKED":
        # Create CLAWBACK adjustment
        ts = now_ts()
        adjustment = {
            "id": new_id(),
            "assignment_id": entry["assignment_id"],
            "dispute_id": None,
            "amount_cents": -entry["credit_amount_cents"],
            "source": "CLAWBACK",
            "reason": f"Clawback: locked credit {entry['id']} reversed",
            "period_index": program["current_period_index"],
            "created_by_user_id": "system",
            "status": "APPROVED",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db["adjustments"][adjustment["id"]] = adjustment

    # Cascade: reverse ROLLUP children in {PENDING, POSTED}
    if entry["credit_type"] == "DIRECT":
        children = [
            c
            for c in db["credit_entries"].values()
            if c.get("parent_credit_id") == entry["id"]
            and c["status"] in ("PENDING", "POSTED")
        ]
        for child in children:
            reverse_credit_entry(child, program)


def reverse_assignment_credits(assignment, program):
    """Reverse credits on assignment terminate.

    PENDING entries -> REVERSED (no earned impact).
    Current-period POSTED entries -> REVERSED with earned compensation.
    LOCKED entries survive termination untouched.
    """
    entries = [
        c
        for c in db["credit_entries"].values()
        if c["assignment_id"] == assignment["id"]
        and c["status"] in ("PENDING", "POSTED")
    ]
    for entry in entries:
        if entry["status"] == "PENDING":
            reverse_credit_entry(entry, program)
        elif (
            entry["status"] == "POSTED"
            and entry["posted_period_index"] == program["current_period_index"]
        ):
            reverse_credit_entry(entry, program)


def accept_assignment_cascade(assignment, program):
    """Post all PENDING credits of this assignment (acceptance cascade).

    Each posting runs full POSTED side effects (earned + rollup spawn).
    """
    pending = [
        c
        for c in db["credit_entries"].values()
        if c["assignment_id"] == assignment["id"] and c["status"] == "PENDING"
    ]
    # Sort by creation time for deterministic order
    pending.sort(key=lambda c: (c["created_at"], c["id"]))
    for entry in pending:
        post_credit_entry(entry, program)
