"""Automatic clock transitions and atomic side-effect cascades (PRD §2.5/§3)."""
from datetime import timedelta

from db import store, touch
from services import calc


def suspend_agent(agent):
    """Agent -> SUSPENDED plus the cascade: cancel its live assignments."""
    if agent["status"] == "SUSPENDED":
        return
    agent["status"] = "SUSPENDED"
    touch(agent)
    for a in calc.agent_assignments(agent["id"]):
        if a["status"] in ("ASSIGNED", "ACCEPTED"):
            a["status"] = "CANCELLED"
            touch(a)


def maybe_auto_suspend(agent_id):
    """After a terminal assignment transition: rolling < 40 -> SUSPENDED."""
    agent = store.repo_agents[agent_id]
    if agent["status"] != "ACTIVE":
        return
    _lifetime, rolling = calc.agent_scores(agent_id)
    if rolling < calc.SUSPENSION_THRESHOLD:
        suspend_agent(agent)


def _expire_cure_notices(now):
    """Link 1: SENT cure notices past their case deadline -> EXPIRED, then the
    owning CURE_PENDING case -> CURE_EXPIRED."""
    for case in sorted(
            (c for c in store.recovery_cases.values() if c["status"] == "CURE_PENDING"),
            key=lambda c: (c["created_at"], c["_seq"])):
        if case["cure_deadline"] is None or not (now > case["cure_deadline"]):
            continue
        notice = store.cure_notices.get(case.get("current_cure_notice_id") or "")
        if notice is not None and notice["status"] == "SENT":
            notice["status"] = "EXPIRED"
            touch(notice)
        case["status"] = "CURE_EXPIRED"
        touch(case)


def _expire_redemption_quotes(now):
    """Link 2: ISSUED quotes past the redemption deadline -> EXPIRED, then the
    REDEMPTION_OPEN case -> CONSIGNMENT_PENDING. Cases frozen in
    COMPLAINT_REVIEW (and their quotes) are left untouched."""
    for case in sorted(
            (c for c in store.recovery_cases.values()
             if c["status"] == "REDEMPTION_OPEN"),
            key=lambda c: (c["created_at"], c["_seq"])):
        deadline = case["redemption_deadline"]
        if deadline is None or not (now > deadline):
            continue
        for q in store.redemption_quotes.values():
            if q["recovery_case_id"] == case["id"] and q["status"] == "ISSUED":
                q["status"] = "EXPIRED"
                touch(q)
        case["status"] = "CONSIGNMENT_PENDING"
        touch(case)


def _expire_assignments(now):
    """Link 3: ASSIGNED assignments older than 48h -> EXPIRED, with score
    recompute and the suspension cascade where the rolling score warrants."""
    for a in sorted(
            (a for a in store.repo_assignments.values() if a["status"] == "ASSIGNED"),
            key=lambda a: (a["created_at"], a["_seq"])):
        if not (now > a["created_at"] + timedelta(days=calc.ACCEPT_WINDOW_DAYS)):
            continue
        a["status"] = "EXPIRED"
        touch(a)
        maybe_auto_suspend(a["agent_id"])


def apply_clock_transitions():
    """Apply every due automatic transition atomically, in dependency order."""
    now = store.clock
    _expire_cure_notices(now)
    _expire_redemption_quotes(now)
    _expire_assignments(now)


def new_ledger_entry(case_id, kind, amount_cents, memo="", reverses_entry_id=None):
    """Append an immutable ledger row (id + created_at only; no version)."""
    from db import new_id  # local to avoid circulars at import time

    entry = {
        "id": new_id(),
        "created_at": store.clock,
        "recovery_case_id": case_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "memo": memo,
        "reverses_entry_id": reverses_entry_id,
        "_seq": store.next_seq(),
    }
    store.ledger_entries[entry["id"]] = entry
    return entry


def record_payment(case, loan, amount_cents):
    """System PAYMENT entry plus the loan's running payment total."""
    entry = new_ledger_entry(case["id"], "PAYMENT", amount_cents)
    loan["paid_to_date_cents"] += amount_cents
    touch(loan)
    return entry


def restitution_cascade(case, complaint, resolver_id):
    """Complaint UPHELD four-link cascade, applied atomically (PRD §3.8)."""
    # link 1: complaint -> UPHELD
    complaint["status"] = "UPHELD"
    complaint["resolved_by_user_id"] = resolver_id
    touch(complaint)
    # link 2: void notices / sales, withdraw consignments
    for n in store.deficiency_notices.values():
        if (n["recovery_case_id"] == case["id"]
                and n["status"] in ("DRAFT", "SENT", "DISPUTED")):
            n["status"] = "VOID"
            touch(n)
    consignment_ids = {c["id"] for c in calc.case_consignments(case["id"])}
    for s in store.sale_records.values():
        if (s["consignment_id"] in consignment_ids
                and s["status"] in ("PENDING_CERTIFICATION", "CERTIFIED")):
            s["status"] = "VOID"
            touch(s)
    for c in store.consignments.values():
        if (c["recovery_case_id"] == case["id"]
                and c["status"] in ("DRAFT", "LISTED", "UNSOLD")):
            c["status"] = "WITHDRAWN"
            touch(c)
    # link 3: reverse every PAYMENT entry of the case
    total_reversed = 0
    for e in calc.case_entries(case["id"]):
        if e["kind"] != "PAYMENT":
            continue
        new_ledger_entry(case["id"], "REVERSAL", e["amount_cents"],
                         reverses_entry_id=e["id"])
        total_reversed += e["amount_cents"]
    # link 4: loan restored as if the case's payments never happened
    loan = store.loan_accounts[case["loan_account_id"]]
    loan["paid_to_date_cents"] -= total_reversed
    loan["status"] = "CURRENT"
    touch(loan)
    case["status"] = "RESTITUTION"
    touch(case)
