"""Domain logic: lookups, calculations, cascades, audit (PRD §3).

All monetary quantities are integer cents (PRD §2.6) — no floats, no rounding.
"""
from clock import add_months
from db import store, new_common_fields, touch
from errors import err

# Calculation constants (SCAFFOLD §1.3 notary_risk_score).
CATEGORY_WEIGHT = {"FRAUD": 40, "FEE_OVERCHARGE": 20, "RECORDKEEPING": 15, "OTHER": 10}
RISK_SUSPEND_THRESHOLD = 50
SCORE_CEILING = 100

ACT_TYPES = {"ACKNOWLEDGMENT", "JURAT", "OATH", "COPY_CERTIFICATION", "SIGNATURE_WITNESS"}
ID_METHODS = {"PERSONAL_KNOWLEDGE", "CREDIBLE_WITNESS", "ID_CREDENTIAL", "KBA_PLUS_CREDENTIAL"}
COMPLAINT_CATEGORIES = {"FRAUD", "RECORDKEEPING", "FEE_OVERCHARGE", "OTHER"}
COMMISSION_TERMS = {48, 60, 96, 120}

# Sessions considered "non-terminal" for window-overlap + suspension cascade.
NON_TERMINAL_SESSION_STATES = {
    "SCHEDULED", "IDENTITY_PENDING", "ID_VERIFIED", "ID_FAILED", "ACTIVE",
}
# Subset that is torn down on notary suspension/revocation (PRD §3.9):
# SCHEDULED, IDENTITY_PENDING, ID_VERIFIED, ACTIVE (ID_FAILED is not listed).
CASCADE_TERMINATE_STATES = {"SCHEDULED", "IDENTITY_PENDING", "ID_VERIFIED", "ACTIVE"}


# ---------------------------------------------------------------------------
# Lookups (existence -> ERR_NOT_FOUND, PRD §2.8 left-to-right)
# ---------------------------------------------------------------------------

def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def find_jurisdiction(jid):
    return get_or_404(store.jurisdictions, jid)


def find_notary(nid):
    return get_or_404(store.notaries, nid)


def find_bond(bid):
    return get_or_404(store.bonds, bid)


def find_session(sid):
    return get_or_404(store.sessions, sid)


def find_signer(sid):
    return get_or_404(store.signers, sid)


def find_document(did):
    return get_or_404(store.documents, did)


def find_renewal(rid):
    return get_or_404(store.renewals, rid)


def find_entry(eid):
    return get_or_404(store.journal_entries, eid)


def find_complaint(cid):
    return get_or_404(store.complaints, cid)


def fee_schedule_for(jurisdiction_id, act_type):
    """The FeeSchedule row matching (jurisdiction_id, act_type), or None."""
    for fs in store.fee_schedules.values():
        if fs["jurisdiction_id"] == jurisdiction_id and fs["act_type"] == act_type:
            return fs
    return None


# ---------------------------------------------------------------------------
# Audit trail (PRD §2.4, append-only; id + created_at only)
# ---------------------------------------------------------------------------

def audit(notary_id, entity_type, entity_id, action, actor_role, detail=""):
    common = new_common_fields(with_version=False)
    ev = dict(common)
    ev.update({
        "notary_id": notary_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "actor_role": actor_role,
        "detail": detail,
    })
    store.audit_events[ev["id"]] = ev
    return ev


# ---------------------------------------------------------------------------
# Derived / computed field recomputation
# ---------------------------------------------------------------------------

def recompute_enotary_authorized(notary):
    """enotary_authorized true only when jurisdiction.ron_allowed AND
    enotary_requested AND bound bond is ACTIVE (PRD §3.2)."""
    juris = store.jurisdictions.get(notary["jurisdiction_id"])
    bond = store.bonds.get(notary.get("bond_id")) if notary.get("bond_id") else None
    authorized = bool(
        juris and juris.get("ron_allowed")
        and notary.get("enotary_requested")
        and bond is not None and bond["status"] == "ACTIVE"
    )
    notary["enotary_authorized"] = authorized
    return authorized


def recompute_lifetime_fees(notary):
    """Sum fee_charged_cents over this notary's POSTED journal entries
    (PRD §2.6, §3.6). Integer cents; order pinned by created_at asc."""
    entries = [
        je for je in store.journal_entries.values()
        if je["notary_id"] == notary["id"] and je["status"] == "POSTED"
    ]
    entries.sort(key=lambda e: (e["created_at"], e.get("_seq", 0)))
    total = 0
    for je in entries:
        total += je["fee_charged_cents"]
    notary["lifetime_fees_collected_cents"] = total
    return total


def recompute_risk_score(notary):
    """Weighted tally over SUBSTANTIATED/SETTLED complaints, capped at 100
    (PRD §3.8). created_at asc order (deterministic; integer sum)."""
    contributing = [
        c for c in store.complaints.values()
        if c["notary_id"] == notary["id"] and c["status"] in ("SUBSTANTIATED", "SETTLED")
    ]
    contributing.sort(key=lambda c: (c["created_at"], c.get("_seq", 0)))
    base = 0
    for c in contributing:
        base += CATEGORY_WEIGHT[c["category"]]
    score = min(SCORE_CEILING, base)
    notary["risk_score"] = score
    return score


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def terminate_sessions_cascade(notary, eligible_states):
    """Cascade: terminate the notary's sessions in eligible_states; each such
    session's PENDING documents -> REFUSED (PRD §3.9). Each affected record is
    independently mutated (updated_at + version bump, PRD §2.5)."""
    for sess in store.sessions.values():
        if sess["notary_id"] != notary["id"]:
            continue
        if sess["status"] not in eligible_states:
            continue
        sess["status"] = "TERMINATED"
        touch(sess)
        for doc in store.documents.values():
            if doc["session_id"] == sess["id"] and doc["status"] == "PENDING":
                doc["status"] = "REFUSED"
                touch(doc)


def auto_suspend_notary(notary, actor_role="SYSTEM"):
    """System-driven suspension (risk threshold / bond exhaustion). Mirrors the
    operator suspend transition: enotary off, cascade sessions, audit
    (PRD §2.5, §3.9). No-op unless currently ACTIVE."""
    if notary["status"] != "ACTIVE":
        return
    notary["status"] = "SUSPENDED"
    notary["enotary_authorized"] = False
    touch(notary)
    terminate_sessions_cascade(notary, CASCADE_TERMINATE_STATES)
    audit(notary["id"], "NOTARY", notary["id"], "NOTARY_SUSPENDED", actor_role,
          "Notary auto-suspended")


# ---------------------------------------------------------------------------
# Session completion fee calculation (PRD §3.6, SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def compute_session_fees(session):
    """Stamp capped fees + surcharge + total on COMPLETED, return notarized docs.

    Notarized docs only, ordered created_at asc. PER_ACT: each doc capped at its
    FeeSchedule cap, sum the caps. AGGREGATE: raw sum capped at
    jurisdiction.session_act_fee_cap_cents, distributed by waterfall.
    """
    juris = store.jurisdictions.get(session["jurisdiction_id"])
    notarized = [
        d for d in store.documents.values()
        if d["session_id"] == session["id"] and d["status"] == "NOTARIZED"
    ]
    notarized.sort(key=lambda d: (d["created_at"], d.get("_seq", 0)))

    if session["fee_basis"] == "PER_ACT":
        total = 0
        for d in notarized:
            sched = fee_schedule_for(session["jurisdiction_id"], d["act_type"])
            cap = sched["max_act_fee_cents"] if sched is not None else d["requested_fee_cents"]
            capped = min(d["requested_fee_cents"], cap)
            d["capped_fee_cents"] = capped
            touch(d)
            total += capped
        act_total = total
    else:  # AGGREGATE
        raw = sum(d["requested_fee_cents"] for d in notarized)
        session_cap = juris["session_act_fee_cap_cents"] if juris else raw
        act_total = min(raw, session_cap)
        remaining = act_total
        for d in notarized:
            share = min(d["requested_fee_cents"], remaining)
            d["capped_fee_cents"] = share
            touch(d)
            remaining -= share

    surcharge_cap = juris["ron_surcharge_cap_cents"] if juris else session["requested_surcharge_cents"]
    surcharge = min(session["requested_surcharge_cents"], surcharge_cap)

    session["act_fees_total_cents"] = act_total
    session["surcharge_charged_cents"] = surcharge
    session["session_total_fee_cents"] = act_total + surcharge
    return notarized


# ---------------------------------------------------------------------------
# Bond settlement draw (PRD §3.8, SCAFFOLD §1.3 bond_settlement_draw)
# ---------------------------------------------------------------------------

def settle_against_bond(complaint, bond):
    """draw = min(claim, remaining); update bond ledger; preserve invariant.

    On exhaustion (remaining == 0) bond -> EXHAUSTED and ACTIVE subject notary
    auto-suspended (three-deep cascade)."""
    draw = min(complaint["claim_amount_cents"], bond["remaining_cents"])
    complaint["settled_claim_cents"] = draw
    bond["claims_paid_cents"] += draw
    bond["remaining_cents"] -= draw
    touch(bond)
    if bond["remaining_cents"] == 0:
        bond["status"] = "EXHAUSTED"
        # touch(bond) already applied above; status change is part of same draw.
        notary = store.notaries.get(bond["notary_id"])
        if notary is not None:
            auto_suspend_notary(notary, actor_role="SYSTEM")
    return draw


# ---------------------------------------------------------------------------
# Temporal overlap helpers (PRD §3.3 closed bond, §3.4 half-open session)
# ---------------------------------------------------------------------------

def session_window_conflicts(notary_id, start, end):
    """Half-open [start,end) overlap with any non-terminal session of the
    notary. Adjacency (end == next start) allowed. created_at asc scan."""
    cand = [
        s for s in store.sessions.values()
        if s["notary_id"] == notary_id and s["status"] in NON_TERMINAL_SESSION_STATES
    ]
    cand.sort(key=lambda s: (s["created_at"], s.get("_seq", 0)))
    for s in cand:
        a_start = s["_scheduled_start_dt"]
        a_end = s["_scheduled_end_dt"]
        if start < a_end and a_start < end:  # half-open overlap
            return True
    return False


def bond_coverage_conflicts(bond, start, end):
    """Closed [start,end] overlap with any OTHER ACTIVE bond of the same
    notary. Touching endpoints conflict. created_at asc scan."""
    cand = [
        b for b in store.bonds.values()
        if b["notary_id"] == bond["notary_id"]
        and b["id"] != bond["id"]
        and b["status"] == "ACTIVE"
    ]
    cand.sort(key=lambda b: (b["created_at"], b.get("_seq", 0)))
    for b in cand:
        a_start = b["_coverage_start_dt"]
        a_end = b["_coverage_end_dt"]
        if start <= a_end and a_start <= end:  # closed overlap (endpoints conflict)
            return True
    return False


# ---------------------------------------------------------------------------
# Grace eligibility (PRD §3.10, SCAFFOLD §1.3 renewal_grace_eligibility)
# ---------------------------------------------------------------------------

def compute_filed_within_grace(notary, jurisdiction, now):
    """grace_deadline = commission_expires_at + renewal_grace_days days; within
    grace iff now <= deadline (inclusive). If no expiry stamped, treat as within
    grace (no boundary to exceed)."""
    from clock import parse_iso8601
    from datetime import timedelta
    expires = notary.get("commission_expires_at")
    if not expires:
        return True
    expires_dt = parse_iso8601(expires)
    deadline = expires_dt + timedelta(days=jurisdiction["renewal_grace_days"])
    return now <= deadline


def extend_expiry(notary, jurisdiction, base_dt):
    """commission_expires_at = base_dt + commission_term_months months."""
    from clock import to_iso8601_millis
    new_expiry = add_months(base_dt, jurisdiction["commission_term_months"])
    notary["commission_expires_at"] = to_iso8601_millis(new_expiry)
