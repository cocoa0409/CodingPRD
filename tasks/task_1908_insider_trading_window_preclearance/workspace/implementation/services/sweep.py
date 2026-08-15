"""The compliance sweep (PRD section 2.10): pinned eight-step order."""
from db import STORE
from services.core import (touch, sort_created, apply_flags, void_cascade,
                           matching_pass)


def run_sweep():
    now = STORE.clock
    counts = {
        "windows_activated": 0,
        "windows_lifted": 0,
        "approvals_expired": 0,
        "approvals_voided": 0,
        "exceptions_expired": 0,
        "plans_activated": 0,
        "attestations_overdue": 0,
        "persons_reinstated": 0,
        "confirmations_remanaged": 0,
    }

    # 1. SCHEDULED -> ACTIVE windows (start_at reached, end_at not yet),
    #    ascending start_at, ties by created_at; each fires the void cascade.
    due = [w for w in STORE.blackout_windows.values()
           if w["status"] == "SCHEDULED" and w["_start_dt"] <= now < w["_end_dt"]]
    due.sort(key=lambda w: (w["_start_dt"], w["_created_dt"], w["_seq"]))
    for w in due:
        w["status"] = "ACTIVE"
        touch(w)
        counts["windows_activated"] += 1
        counts["approvals_voided"] += void_cascade(w)

    # 2. ACTIVE -> LIFTED windows whose end_at has been reached or passed.
    for w in sort_created(STORE.blackout_windows.values()):
        if w["status"] == "ACTIVE" and now >= w["_end_dt"]:
            w["status"] = "LIFTED"
            touch(w)
            counts["windows_lifted"] += 1

    # 3. APPROVED -> EXPIRED preclearance requests past the validity horizon.
    for r in sort_created(STORE.preclearance_requests.values()):
        if r["status"] == "APPROVED" and now > r["_approval_valid_until_dt"]:
            r["status"] = "EXPIRED"
            r["remaining_quantity"] = 0  # forfeited; matched confirmations stay matched
            touch(r)
            counts["approvals_expired"] += 1

    # 4. SUBMITTED -> EXPIRED exception requests past the decision window.
    for x in sort_created(STORE.exception_requests.values()):
        if x["status"] == "SUBMITTED" and now > x["_decision_window_end_dt"]:
            x["status"] = "EXPIRED"
            touch(x)
            counts["exceptions_expired"] += 1

    # 5. APPROVED -> ACTIVE plans whose cooling-off has elapsed.
    for p in sort_created(STORE.tenb5_plans.values()):
        if p["status"] == "APPROVED" and now >= p["_cooling_off_end_dt"]:
            p["status"] = "ACTIVE"
            touch(p)
            counts["plans_activated"] += 1

    # 6. ASSIGNED -> OVERDUE attestations past due_date; recompute training
    #    currency for each affected person.
    affected = set()
    for a in sort_created(STORE.attestations.values()):
        if a["status"] == "ASSIGNED" and a["_due_dt"] < now:
            a["status"] = "OVERDUE"
            touch(a)
            counts["attestations_overdue"] += 1
            affected.add(a["covered_person_id"])
    for pid in affected:
        person = STORE.covered_persons.get(pid)
        if person is not None:
            apply_flags(person)

    # 7. SUSPENDED -> ACTIVE persons whose suspension has elapsed.
    for p in sort_created(STORE.covered_persons.values()):
        if p["status"] == "SUSPENDED" and p["_suspended_until_dt"] is not None \
                and now >= p["_suspended_until_dt"]:
            p["status"] = "ACTIVE"
            p["suspended_until"] = None
            p["_suspended_until_dt"] = None
            touch(p)
            counts["persons_reinstated"] += 1

    # 8. Re-match pass over RECEIVED confirmations, trade_date ASC then
    #    created_at ASC.
    pending = [c for c in STORE.trade_confirmations.values() if c["status"] == "RECEIVED"]
    pending.sort(key=lambda c: (c["_trade_date_dt"], c["_created_dt"], c["_seq"]))
    for c in pending:
        touch(c)
        matching_pass(c)
        counts["confirmations_remanaged"] += 1

    return counts
