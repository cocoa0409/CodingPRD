"""Cascade logic: file termination, amendment voiding, clock sweep."""
from datetime import timezone

from db import store, mint, touch, fmt_dt
from util import parse_date, parse_dt
from services import calc

UTC = timezone.utc


def void_amendment(amendment):
    """Amendment -> VOIDED; all its PENDING SignatureRequests -> VOIDED."""
    amendment["status"] = "VOIDED"
    touch(amendment)
    for sr in store.signature_requests.values():
        if sr["amendment_id"] == amendment["id"] and sr["status"] == "PENDING":
            sr["status"] = "VOIDED"
            touch(sr)


def terminate_file(file_rec, reason=None):
    """The five-part termination cascade (PRD section 3.9)."""
    # Cascade 1: milestones PENDING/IN_PROGRESS/OVERDUE -> CANCELLED
    for m in store.milestones.values():
        if m["file_id"] == file_rec["id"] and m["status"] in ("PENDING", "IN_PROGRESS", "OVERDUE"):
            m["status"] = "CANCELLED"
            touch(m)
    # Cascade 2: deadlines PENDING -> CANCELLED; their QUEUED reminders -> CANCELLED
    for d in store.deadlines.values():
        if d["file_id"] == file_rec["id"] and d["status"] == "PENDING":
            d["status"] = "CANCELLED"
            touch(d)
            calc.cancel_queued_reminders(d["id"])
    # Cascade 3: amendments DRAFT/ROUTED/PARTIALLY_SIGNED/FULLY_SIGNED -> VOIDED
    for a in store.amendments.values():
        if a["file_id"] == file_rec["id"] and a["status"] in (
                "DRAFT", "ROUTED", "PARTIALLY_SIGNED", "FULLY_SIGNED"):
            void_amendment(a)
    # Documents in REQUESTED/RECEIVED/REJECTED -> CANCELLED (document cascade)
    for doc in store.documents.values():
        if doc["file_id"] == file_rec["id"] and doc["status"] in ("REQUESTED", "RECEIVED", "REJECTED"):
            doc["status"] = "CANCELLED"
            touch(doc)
    # Cascade 4: communications OPEN/ESCALATED -> RESOLVED; reset escalation counter
    for c in store.communications.values():
        if c["file_id"] == file_rec["id"] and c["status"] in ("OPEN", "ESCALATED"):
            c["status"] = "RESOLVED"
    # Cascade 5: invoice DRAFT -> VOIDED with TERMINATION_CREDIT lines (net sum 0)
    for inv in store.invoices.values():
        if inv["file_id"] == file_rec["id"] and inv["status"] == "DRAFT":
            credits = [{"label": "TERMINATION_CREDIT", "amount_cents": -l["amount_cents"]}
                       for l in inv["line_items"]]
            inv["line_items"] = inv["line_items"] + credits
            inv["subtotal_cents"] = sum(l["amount_cents"] for l in inv["line_items"])
            inv["discount_cents"] = 0
            inv["total_cents"] = inv["subtotal_cents"]
            inv["status"] = "VOIDED"
            touch(inv)
    # Slot release: SUBSCRIPTION billing and no document ever reached ACCEPTED
    if file_rec["billing_model"] == "SUBSCRIPTION":
        any_accepted = any(d["file_id"] == file_rec["id"] and d["status"] == "ACCEPTED"
                           for d in store.documents.values())
        sub = store.subscriptions.get(file_rec.get("subscription_id"))
        if not any_accepted and sub is not None:
            sub["included_files_used"] = max(0, sub["included_files_used"] - 1)
            touch(sub)
    # File itself
    file_rec["status"] = "TERMINATED"
    file_rec["open_escalation_count"] = 0
    if reason is not None:
        file_rec["terminated_reason"] = reason
    touch(file_rec)


def sweep_clock():
    """Advance-triggered transitions in the pinned order (PRD section 3.10):
    1. due reminders sent; 2. deadline expiries (+ escalation cascade);
    3. milestone overdue; 4. communication escalations."""
    counts = {"reminders_sent": 0, "deadlines_expired": 0,
              "milestones_marked_overdue": 0, "communications_escalated": 0}
    now = store.now
    today = now.date()

    # 1. Due reminders: QUEUED, scheduled_at <= now, owning deadline still PENDING.
    for r in sorted(store.reminders.values(), key=lambda x: (x["_seq"])):
        if r["status"] != "QUEUED":
            continue
        if parse_dt(r["scheduled_at"]) > now:
            continue
        deadline = store.deadlines.get(r["deadline_id"])
        if deadline is None or deadline["status"] != "PENDING":
            continue
        r["status"] = "SENT"
        r["sent_at"] = fmt_dt(now)
        touch(r)
        counts["reminders_sent"] += 1

    # 2. Deadline expiries: PENDING and current clock date > due_date.
    for d in sorted(store.deadlines.values(), key=lambda x: (x["_seq"])):
        if d["status"] != "PENDING":
            continue
        if not (today > parse_date(d["due_date"])):
            continue
        d["status"] = "EXPIRED"
        d["escalated"] = True
        touch(d)
        calc.cancel_queued_reminders(d["id"])
        file_rec = store.files.get(d["file_id"])
        if file_rec is not None:
            entry = mint({
                "file_id": file_rec["id"],
                "entry_kind": "ESCALATION",
                "author_role": "SYSTEM",
                "party": "SYSTEM",
                "direction": "SYSTEM",
                "body": f"Deadline expired: {d['kind']} (due {d['due_date']})",
                "requires_response": False,
                "response_due_at": None,
                "in_reply_to_id": None,
                "status": "ESCALATED",
            }, common=False)
            store.communications[entry["id"]] = entry
            file_rec["open_escalation_count"] += 1
            touch(file_rec)
        counts["deadlines_expired"] += 1

    # 3. Milestone overdue: PENDING/IN_PROGRESS and current clock date > due_date.
    for m in sorted(store.milestones.values(), key=lambda x: (x["_seq"])):
        if m["status"] not in ("PENDING", "IN_PROGRESS"):
            continue
        if today > parse_date(m["due_date"]):
            m["status"] = "OVERDUE"
            touch(m)
            counts["milestones_marked_overdue"] += 1

    # 4. Communication escalations: OPEN, requires_response, clock time > response_due_at.
    for c in sorted(store.communications.values(), key=lambda x: (x["_seq"])):
        if c["status"] != "OPEN" or not c.get("requires_response"):
            continue
        due = c.get("response_due_at")
        if not due:
            continue
        if now > parse_dt(due):
            c["status"] = "ESCALATED"
            file_rec = store.files.get(c["file_id"])
            if file_rec is not None:
                file_rec["open_escalation_count"] += 1
                touch(file_rec)
            counts["communications_escalated"] += 1

    return counts
