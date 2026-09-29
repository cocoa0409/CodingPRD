"""Shared derivations and cascades (PRD 2.8, 3.x)."""

from db import db, make_entity, now, ordered, touch
from services import calculations as calc

LIVE_PARTICIPANT_STATUSES = ("IN_PLAN", "ASSIGNED")
AUDIT_CLEAN_STATUSES = ("PASSED_CLOSED", "CORRECTED")


# --------------------------------------------------------------------------
# collection helpers
# --------------------------------------------------------------------------


def plan_participants(plan_id):
    return ordered([p for p in db.participants.values() if p["plan_id"] == plan_id])


def plan_windows(plan_id):
    return ordered([w for w in db.windows.values() if w["plan_id"] == plan_id])


def plan_tranches(plan_id):
    return ordered([t for t in db.tranches.values() if t["plan_id"] == plan_id])


def plan_strategies(plan_id):
    return ordered([s for s in db.strategies.values() if s["plan_id"] == plan_id])


def plan_experts(plan_id):
    return ordered([e for e in db.experts.values() if e["plan_id"] == plan_id])


def participant_audits(participant_id):
    return sorted(
        [a for a in db.audits.values() if a["participant_id"] == participant_id],
        key=lambda a: a["audit_sequence"],
    )


def participant_complaints(participant_id):
    return ordered([c for c in db.complaints.values() if c["participant_id"] == participant_id])


def plan_complaints(plan_id):
    ids = set(p["id"] for p in db.participants.values() if p["plan_id"] == plan_id)
    return ordered([c for c in db.complaints.values() if c["participant_id"] in ids])


def window_elections(window_id):
    return ordered([e for e in db.elections.values() if e["window_id"] == window_id])


def tranche_quotes(tranche_id):
    return ordered([q for q in db.quotes.values() if q["tranche_id"] == tranche_id])


def tranche_transfers(tranche_id):
    return ordered([t for t in db.transfers.values() if t["tranche_id"] == tranche_id])


def tranche_assigned_participants(tranche):
    return ordered(
        [
            p
            for p in db.participants.values()
            if p.get("tranche_id") == tranche["id"] and p["participant_status"] == "ASSIGNED"
        ]
    )


def tranche_member_count(tranche):
    return len(
        [
            p
            for p in db.participants.values()
            if p.get("tranche_id") == tranche["id"]
            and p["participant_status"] in ("ASSIGNED", "TRANSFERRED_TO_INSURER")
        ]
    )


def latest_live_audit(participant_id):
    audits = [a for a in participant_audits(participant_id) if a["audit_status"] != "SUPERSEDED"]
    return audits[-1] if audits else None


# --------------------------------------------------------------------------
# participant derivations
# --------------------------------------------------------------------------


def refresh_participant(participant, bump=True):
    participant["accounting_liability_cents"] = calc.participant_accounting_liability(participant)
    participant["settlement_liability_cents"] = calc.participant_settlement_liability(participant)
    score = calc.data_confidence_score(participant)
    participant["data_confidence_score"] = score
    participant["data_status"] = calc.data_status_for(score)
    if bump:
        touch(participant)
    return participant


def refresh_participant_confidence(participant, bump=True):
    score = calc.data_confidence_score(participant)
    participant["data_confidence_score"] = score
    participant["data_status"] = calc.data_status_for(score)
    if bump:
        touch(participant)
    return participant


# --------------------------------------------------------------------------
# plan derivations
# --------------------------------------------------------------------------


def recompute_plan_participant_liability(plan):
    total = 0
    for participant in db.participants.values():
        if participant["plan_id"] != plan["id"]:
            continue
        if participant["participant_status"] in LIVE_PARTICIPANT_STATUSES:
            total += participant["accounting_liability_cents"] or 0
    plan["participant_liability_total_cents"] = total
    return total


def recompute_plan_accounting_funded_status(plan):
    figures = calc.funded_status(
        plan["total_liability_cents"],
        plan["plan_assets_cents"],
        plan["participant_liability_total_cents"],
    )
    plan["accounting_funded_status_bp"] = figures["accounting_funded_status_bp"]
    return figures


def live_participant_liability_total(plan_id):
    total = 0
    for participant in db.participants.values():
        if participant["plan_id"] != plan_id:
            continue
        if participant["participant_status"] in LIVE_PARTICIPANT_STATUSES:
            total += participant["accounting_liability_cents"] or 0
    return total


def plan_funded_status(plan):
    """Computed read — persists nothing."""
    return calc.funded_status(
        plan["total_liability_cents"],
        plan["plan_assets_cents"],
        live_participant_liability_total(plan["id"]),
    )


# --------------------------------------------------------------------------
# tranche derivations
# --------------------------------------------------------------------------


def derive_readiness(tranche):
    assigned = tranche_assigned_participants(tranche)
    if not assigned:
        return "BLOCKED"
    for participant in assigned:
        if participant["data_status"] != "CLEAN":
            return "BLOCKED"
        if participant["mortality_status"] != "ALIVE_CONFIRMED":
            return "BLOCKED"
        if participant["benefit_audit_status"] not in AUDIT_CLEAN_STATUSES:
            return "BLOCKED"
    return "READY"


def recompute_tranche_liabilities(tranche):
    assigned = tranche_assigned_participants(tranche)
    tranche["accounting_liability_cents"] = sum(
        p["accounting_liability_cents"] or 0 for p in assigned
    )
    tranche["settlement_liability_cents"] = sum(
        p["settlement_liability_cents"] or 0 for p in assigned
    )
    return tranche


def recompute_tranche(tranche, readiness=None, count=True, liabilities=True, bump=True):
    if count:
        tranche["assigned_participant_count"] = tranche_member_count(tranche)
    if liabilities:
        recompute_tranche_liabilities(tranche)
    tranche["data_readiness_flag"] = readiness if readiness else derive_readiness(tranche)
    if bump:
        touch(tranche)
    return tranche


def participant_open_tranche(participant):
    """The tranche a participant belongs to, when it is still pre-settlement."""
    tranche_id = participant.get("tranche_id")
    if not tranche_id:
        return None
    tranche = db.tranches.get(tranche_id)
    if tranche is None:
        return None
    if tranche["tranche_status"] in ("DRAFT", "QUOTING", "INSURER_SELECTED"):
        return tranche
    return None


# --------------------------------------------------------------------------
# insurer capacity
# --------------------------------------------------------------------------

COMMITTED_TRANCHE_STATUSES = ("PRICING_LOCKED", "ASSETS_TRANSFERRED", "SETTLED")


def committed_capacity(insurer_id, exclude_tranche_id=None, window_start=None, window_end=None):
    total = 0
    for tranche in db.tranches.values():
        if tranche.get("selected_insurer_id") != insurer_id:
            continue
        if tranche["tranche_status"] not in COMMITTED_TRANCHE_STATUSES:
            continue
        if exclude_tranche_id and tranche["id"] == exclude_tranche_id:
            continue
        if window_start is not None and window_end is not None:
            lock_start = tranche.get("lock_start_at")
            lock_end = tranche.get("lock_expires_at")
            if lock_start is None or lock_end is None:
                continue
            # Closed intersection: touching locks do overlap.
            if not (lock_start <= window_end and lock_end >= window_start):
                continue
        total += tranche.get("locked_premium_cents") or 0
    return total


def recompute_insurer_capacity(insurer, bump=True, window_start=None, window_end=None):
    committed = committed_capacity(
        insurer["id"], window_start=window_start, window_end=window_end
    )
    insurer["committed_capacity_cents"] = committed
    insurer["available_capacity_cents"] = insurer["capacity_cents"] - committed
    if bump:
        touch(insurer)
    return insurer


# --------------------------------------------------------------------------
# settlement ledger
# --------------------------------------------------------------------------


def append_settlement_entry(plan, entry_type, amount_cents, deferred_amount_cents,
                            gain_loss_cents, pbo_settled_cents, source_reference,
                            tranche_id=None, window_id=None):
    entry = make_entity(versioned=False)
    entry["plan_id"] = plan["id"]
    entry["tranche_id"] = tranche_id
    entry["window_id"] = window_id
    entry["entry_type"] = entry_type
    entry["amount_cents"] = amount_cents
    entry["deferred_amount_cents"] = deferred_amount_cents
    entry["gain_loss_cents"] = gain_loss_cents
    entry["pbo_settled_cents"] = pbo_settled_cents
    entry["source_reference"] = source_reference
    entry["posted_at"] = now()
    db.entries[entry["id"]] = entry
    plan["cumulative_settlement_charge_cents"] = (
        plan["cumulative_settlement_charge_cents"] + amount_cents
    )
    plan["deferred_settlement_charge_cents"] = (
        plan["deferred_settlement_charge_cents"] + deferred_amount_cents
    )
    return entry


# --------------------------------------------------------------------------
# residual bubble-up (PRD 3.9)
# --------------------------------------------------------------------------


def maybe_transition_to_residual(plan):
    if plan["plan_status"] != "SETTLEMENT_AUTHORIZED":
        return False
    windows = plan_windows(plan["id"])
    tranches = plan_tranches(plan["id"])
    for window in windows:
        if window["window_status"] not in ("SETTLED", "VOIDED"):
            return False
    for tranche in tranches:
        if tranche["tranche_status"] not in ("SETTLED", "ABANDONED"):
            return False
    settled_window = any(w["window_status"] == "SETTLED" for w in windows)
    settled_tranche = any(t["tranche_status"] == "SETTLED" for t in tranches)
    if not (settled_window or settled_tranche):
        return False

    plan["plan_status"] = "RESIDUAL"
    plan["residual_effective_at"] = now()
    recompute_plan_participant_liability(plan)
    recompute_plan_accounting_funded_status(plan)
    for strategy in plan_strategies(plan["id"]):
        if strategy["strategy_status"] == "APPROVED":
            strategy["strategy_status"] = "EXECUTED"
            touch(strategy)
    touch(plan)
    return True
