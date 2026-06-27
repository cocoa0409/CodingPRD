"""Shared business operations: invoice line management, fee recompute,
diligence, reliability recompute, and cascading side effects."""
from db import db, new_id, now_iso, touch
import fees


# --------------------------------------------------------------------------
# Invoice lines & fee recompute
# --------------------------------------------------------------------------
def add_invoice_line(sr_id, kind, amount_cents):
    line = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "service_request_id": sr_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "voided": False,
    }
    db.invoice_lines[line["id"]] = line
    return line


def _sync_attempt_line(sr):
    """Maintain a single ATTEMPT invoice line reflecting the current tiered
    per-attempt labor (PRD 3.12). The line is created when billable attempts
    first incur a charge and updated in place thereafter."""
    n = fees.billable_attempt_count(sr["id"])
    amount = fees._attempt_line(n)
    existing = None
    for line in db.invoice_lines.values():
        if line["service_request_id"] == sr["id"] and line["kind"] == "ATTEMPT":
            existing = line
            break
    if amount == 0:
        # No attempt charge yet: leave any existing line at 0 (or none).
        if existing is not None and existing["amount_cents"] != 0:
            existing["amount_cents"] = 0
            existing["voided"] = False
            touch(existing)
        return
    if existing is None:
        add_invoice_line(sr["id"], "ATTEMPT", amount)
    elif existing["amount_cents"] != amount or existing["voided"]:
        existing["amount_cents"] = amount
        existing["voided"] = False
        touch(existing)


def recompute_final_fee(sr):
    """Recompute final_fee_cents (final variant) and mark the request mutated."""
    _sync_attempt_line(sr)
    new_fee = fees.compute_fee(sr, "final")
    if sr["final_fee_cents"] != new_fee:
        sr["final_fee_cents"] = new_fee
        touch(sr)
    return new_fee


def recompute_distinct_attempt_days(sr):
    """Distinct UTC calendar days bearing a non-superseded attempt (PRD 3.4)."""
    days = set()
    for a in db.attempts.values():
        if a["service_request_id"] != sr["id"]:
            continue
        if a["superseded"]:
            continue
        # attempted_at_utc is stored ISO 8601; the calendar day is the date part.
        days.add(a["attempted_at_utc"][:10])
    new_count = len(days)
    if sr["distinct_attempt_days"] != new_count:
        sr["distinct_attempt_days"] = new_count
        touch(sr)
    return new_count


# --------------------------------------------------------------------------
# Server reliability
# --------------------------------------------------------------------------
def recompute_reliability(server):
    new_score = fees.realized_score(server["id"])
    if server["reliability_score"] != new_score:
        server["reliability_score"] = new_score
        touch(server)


# --------------------------------------------------------------------------
# Assignment terminal helpers
# --------------------------------------------------------------------------
def complete_assignment(assignment, request_terminal):
    """Bubble an ACTIVE assignment to COMPLETED (PRD 3.5).

    Decrements active count, increments completed count, records which terminal
    request state credited this completion, recomputes reliability.
    """
    assignment["status"] = "COMPLETED"
    assignment["request_terminal"] = request_terminal
    touch(assignment)
    server = db.servers[assignment["server_id"]]
    server["active_assignment_count"] -= 1
    server["completed_count"] += 1
    touch(server)
    recompute_reliability(server)


def supersede_attempts(assignment_id, sr):
    """Mark every attempt under an assignment superseded (PRD 3.3)."""
    for a in db.attempts.values():
        if a["assignment_id"] == assignment_id and not a["superseded"]:
            a["superseded"] = True
            touch(a)


def cancel_stakeout_line(stakeout, sr):
    """Void a stakeout's STAKEOUT invoice line (PRD 3.6)."""
    for line in db.invoice_lines.values():
        if line.get("stakeout_id") == stakeout["id"] and not line["voided"]:
            line["voided"] = True
            touch(line)


def cancel_assignment_cascade(assignment, sr):
    """ACTIVE assignment cancelled as part of request cancellation (PRD 3.10).

    L1: assignment ACTIVE -> CANCELLED.
    L2: server.active_assignment_count -= 1; reliability recomputed; every
        SCHEDULED stakeout under this assignment -> CANCELLED.
    L3: each cancelled stakeout voids its STAKEOUT invoice line.
    (L4 fee recompute is done by the caller after the cascade.)
    """
    assignment["status"] = "CANCELLED"
    touch(assignment)
    server = db.servers[assignment["server_id"]]
    server["active_assignment_count"] -= 1
    touch(server)
    recompute_reliability(server)
    for stk in db.stakeouts.values():
        if stk["assignment_id"] == assignment["id"] and stk["status"] == "SCHEDULED":
            stk["status"] = "CANCELLED"
            touch(stk)
            cancel_stakeout_line(stk, sr)
