"""Domain services: deposit assessment, cost allocation, forfeiture, queue
compaction, withdrawal pipeline with the restudy cascade, and cluster closure.

All money is integer cents; every multiplicative component is rounded half-up
to whole cents first and only then summed (PRD section 2.5)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

from clock import CLOCK, format_clock, parse_iso
from db import (DB, new_id, next_seq, pub, sort_key, stamp_new,
                stamp_new_immutable, touch)

getcontext().prec = 50

# ---- calculation constants (scaffold section 1.3) ----
TIER1_MW = Decimal("20")
TIER1_RATE_CENTS = Decimal("100000")
TIER2_RATE_CENTS = Decimal("250000")
CAPACITY_MULTIPLIER = Decimal("1.2")
EXPEDITED_MAX_MW = Decimal("5")
EXPEDITED_FLAT_CENTS = 300000

FORFEIT_PCT_EARLY = Decimal("0.10")    # SUBMITTED | QUEUED | READY
FORFEIT_PCT_STUDY = Decimal("0.50")    # IN_STUDY | STUDY_COMPLETE | RESTUDY_REQUIRED
FORFEIT_PCT_AGREEMENT = Decimal("1.00")  # AGREEMENT_PENDING | AGREEMENT_EXECUTED

EXECUTION_DEADLINE_DAYS = 90
EXTENSION_LIMIT = 2
EXTENSION_MAX_DAYS = 365
EXTENSION_NOTICE_DAYS = 30

REQUIRED_MILESTONE_TYPES = ("SITE_CONTROL", "TECHNICAL_DATA")

# Included set for study cost allocation (scaffold calculations.study_cost_allocation).
INCLUDED_STATUSES = (
    "IN_STUDY", "STUDY_COMPLETE", "RESTUDY_REQUIRED",
    "AGREEMENT_PENDING", "AGREEMENT_EXECUTED",
)
# Transparency snapshot "queued" set (scaffold calculations.transparency_snapshot).
QUEUED_STATUSES = (
    "SUBMITTED", "QUEUED", "READY", "IN_STUDY", "STUDY_COMPLETE",
    "RESTUDY_REQUIRED", "AGREEMENT_PENDING", "AGREEMENT_EXECUTED",
)
TERMINAL_STATUSES = ("WITHDRAWN", "COMMERCIAL_OPERATION")


def rhu(value):
    """Round a Decimal half-up to zero decimal places (integer cents)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _num(d):
    """Decimal -> int when integral, else float (MW figures are never rounded)."""
    return int(d) if d == d.to_integral_value() else float(d)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def members_of(cluster_id):
    items = [p for p in DB["projects"].values() if p["cluster_group_id"] == cluster_id]
    return sorted(items, key=sort_key)


def study_of_cluster(cluster_id):
    for s in DB["studies"].values():
        if s["cluster_group_id"] == cluster_id:
            return s
    return None


def agreements_of(project_id):
    items = [a for a in DB["agreements"].values() if a["project_id"] == project_id]
    return sorted(items, key=sort_key)


def submissions_of(project_id):
    items = [s for s in DB["milestone_submissions"].values() if s["project_id"] == project_id]
    return sorted(items, key=sort_key)


def ledger_of(project_id):
    items = [t for t in DB["deposit_transactions"].values() if t["project_id"] == project_id]
    return sorted(items, key=sort_key)


def cost_shares_of_study(study_id):
    items = [c for c in DB["cost_shares"].values() if c["study_id"] == study_id]
    return sorted(items, key=sort_key)


def cost_shares_of_project(project_id):
    items = [c for c in DB["cost_shares"].values() if c["project_id"] == project_id]
    return sorted(items, key=sort_key)


def limits_of(project_id):
    items = [c for c in DB["curtailment_limits"].values() if c["project_id"] == project_id]
    return sorted(items, key=sort_key)


# ---------------------------------------------------------------------------
# Deposit assessment (calculations.deposit_assessment)
# ---------------------------------------------------------------------------

def assess_deposit(technology, capacity_mw, service_type):
    """Variant selection is evaluated first: STORAGE at or below 5 MW is the
    EXPEDITED flat 300000 cents; every other project is STANDARD tiered pricing
    times the service-type multiplier, rounded half-up to whole cents."""
    cap = Decimal(str(capacity_mw))
    if technology == "STORAGE" and cap <= EXPEDITED_MAX_MW:
        return EXPEDITED_FLAT_CENTS
    base = min(cap, TIER1_MW) * TIER1_RATE_CENTS
    if cap > TIER1_MW:
        base = base + (cap - TIER1_MW) * TIER2_RATE_CENTS
    multiplier = Decimal("1.0") if service_type == "ENERGY_ONLY" else CAPACITY_MULTIPLIER
    return rhu(base * multiplier)


# ---------------------------------------------------------------------------
# Deposit ledger
# ---------------------------------------------------------------------------

def post_ledger(project, tx_type, amount_cents):
    """Append a ledger entry; balance_after_cents is the running
    deposit_posted_cents immediately after the entry is applied."""
    if tx_type == "DEPOSIT":
        project["deposit_posted_cents"] += amount_cents
    else:  # REFUND and FORFEIT both reduce the posted balance
        project["deposit_posted_cents"] -= amount_cents
    tx = {
        "id": new_id(),
        "_seq": next_seq(),
        "project_id": project["id"],
        "tx_type": tx_type,
        "amount_cents": amount_cents,
        "balance_after_cents": project["deposit_posted_cents"],
    }
    stamp_new_immutable(tx)
    DB["deposit_transactions"][tx["id"]] = tx
    return tx


def forfeiture_pct(status):
    if status in ("SUBMITTED", "QUEUED", "READY"):
        return FORFEIT_PCT_EARLY
    if status in ("IN_STUDY", "STUDY_COMPLETE", "RESTUDY_REQUIRED"):
        return FORFEIT_PCT_STUDY
    return FORFEIT_PCT_AGREEMENT


# ---------------------------------------------------------------------------
# Study cost allocation (calculations.study_cost_allocation)
# ---------------------------------------------------------------------------

def recompute_cost_shares(study):
    """Reallocate the study's total cost over the included member set under the
    study's current basis. Rounding order is pinned: each component is rounded
    half-up to integer cents first, then summed. Residual reconciliation adds
    the difference to the included project with the largest capacity_mw
    (ties broken by earliest created_at). Rows of projects that have left the
    included set are zeroed."""
    basis = study["_basis"]
    total = study["total_cost_cents"]
    included = [p for p in members_of(study["cluster_group_id"])
                if p["status"] in INCLUDED_STATUSES]
    rows = cost_shares_of_study(study["id"])
    by_project = {r["project_id"]: r for r in rows}
    included_ids = set()

    if included:
        n = len(included)
        cap_total = sum(Decimal(str(p["capacity_mw"])) for p in included)
        t = Decimal(total)
        shares = {}
        if basis == "PROVISIONAL":
            # Pure pro-rata by capacity_mw.
            for p in included:
                shares[p["id"]] = rhu(t * Decimal(str(p["capacity_mw"])) / cap_total)
        else:
            # FINAL: 50% equal headcount split + 50% pro-rata capacity split,
            # each component rounded half-up to integer cents before summing.
            head = rhu(Decimal("0.5") * t / Decimal(n))
            for p in included:
                cap_part = rhu(Decimal("0.5") * t * Decimal(str(p["capacity_mw"])) / cap_total)
                shares[p["id"]] = head + cap_part
        residual = total - sum(shares.values())
        if residual != 0:
            # Largest capacity; tie-break earliest created_at (members list is
            # already ordered by (created_at, seq), so strictly-greater keeps
            # the earliest among equals).
            target = None
            for p in included:
                if target is None or Decimal(str(p["capacity_mw"])) > Decimal(str(target["capacity_mw"])):
                    target = p
            shares[target["id"]] += residual
        for p in included:
            row = by_project.get(p["id"])
            if row is not None:
                row["allocated_cents"] = shares[p["id"]]
                row["basis"] = basis
                touch(row)
                included_ids.add(p["id"])

    for row in rows:
        if row["project_id"] not in included_ids:
            row["allocated_cents"] = 0
            row["basis"] = basis
            touch(row)


def create_cost_share(study, project):
    row = {
        "id": new_id(),
        "_seq": next_seq(),
        "study_id": study["id"],
        "project_id": project["id"],
        "basis": study["_basis"],
        "allocated_cents": 0,
    }
    stamp_new(row)
    DB["cost_shares"][row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# Withdrawal pipeline (PRD section 3.7)
# ---------------------------------------------------------------------------

def withdraw_project(project, scoping=False):
    """Runs the full withdrawal pipeline: forfeiture schedule, committed_mw
    reconciliation, queue compaction, ISSUED-agreement expiry, and — unless
    this is the scoping-time readiness enforcement — the restudy cascade.
    Finally re-checks cluster closure (withdrawal is a terminal transition)."""
    cluster = DB["cluster_groups"][project["cluster_group_id"]]

    # 1. Deposit forfeiture schedule against the status at withdrawal.
    posted = project["deposit_posted_cents"]
    if posted > 0:
        forfeit = rhu(Decimal(posted) * forfeiture_pct(project["status"]))
        refund = posted - forfeit
        post_ledger(project, "FORFEIT", forfeit)
        if refund > 0:
            post_ledger(project, "REFUND", refund)
    # deposit_posted_cents is now 0 (posted == 0 leaves the ledger untouched).

    old_position = project["queue_position"]
    project["status"] = "WITHDRAWN"
    touch(project)

    # 2. committed_mw reconciliation: -capacity_mw on withdrawal.
    cluster["committed_mw"] = _num(
        Decimal(str(cluster["committed_mw"])) - Decimal(str(project["capacity_mw"])))
    touch(cluster)

    # 3. Queue compaction: every non-withdrawn member behind the withdrawn
    #    position decrements by exactly one; positions stay dense 1..N.
    if old_position is not None:
        for m in members_of(cluster["id"]):
            if (m["status"] != "WITHDRAWN" and m["queue_position"] is not None
                    and m["queue_position"] > old_position):
                m["queue_position"] -= 1
                touch(m)

    # 4. Any ISSUED agreement of this project transitions to EXPIRED.
    for ag in agreements_of(project["id"]):
        if ag["status"] == "ISSUED":
            ag["status"] = "EXPIRED"
            touch(ag)

    # 5. Restudy cascade — suppressed for the scoping-time readiness
    #    enforcement (the study has only just been created).
    if not scoping:
        study = study_of_cluster(cluster["id"])
        if study is not None and study["status"] in ("IN_PROGRESS", "RESULTS_PUBLISHED"):
            if study["status"] == "RESULTS_PUBLISHED":
                # Reopen and demote every sibling sitting in STUDY_COMPLETE.
                study["status"] = "IN_PROGRESS"
                touch(study)
                for m in members_of(cluster["id"]):
                    if m["id"] != project["id"] and m["status"] == "STUDY_COMPLETE":
                        m["status"] = "RESTUDY_REQUIRED"
                        touch(m)
            # Recompute over the surviving included set under the current
            # basis; the withdrawn project's row is zeroed.
            recompute_cost_shares(study)

    # 6. Bubble-up closure check (a withdrawal is a terminal transition).
    maybe_close_cluster(cluster)


def maybe_close_cluster(cluster):
    """Cluster STUDY_COMPLETE -> CLOSED once every member project sits in a
    terminal state (WITHDRAWN or COMMERCIAL_OPERATION)."""
    if cluster["status"] != "STUDY_COMPLETE":
        return
    members = members_of(cluster["id"])
    if members and all(m["status"] in TERMINAL_STATUSES for m in members):
        cluster["status"] = "CLOSED"
        touch(cluster)


# ---------------------------------------------------------------------------
# Transparency snapshot (calculations.transparency_snapshot)
# ---------------------------------------------------------------------------

def transparency_snapshot():
    projects = list(DB["projects"].values())
    queued = [p for p in projects if p["status"] in QUEUED_STATUSES]
    queued_mw = sum((Decimal(str(p["capacity_mw"])) for p in queued), Decimal(0))
    return {
        "queued_project_count": len(queued),
        "queued_mw": _num(queued_mw),
        "withdrawn_project_count": sum(1 for p in projects if p["status"] == "WITHDRAWN"),
        "commercial_operation_project_count": sum(
            1 for p in projects if p["status"] == "COMMERCIAL_OPERATION"),
    }


__all__ = [name for name in dir() if not name.startswith("__")] + ["pub", "format_clock", "parse_iso", "timedelta", "CLOCK"]
