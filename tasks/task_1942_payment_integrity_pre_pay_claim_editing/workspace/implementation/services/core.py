"""Core business logic: state machines, cascades, bubble-ups, recomputes."""

from datetime import timedelta
from decimal import Decimal

import db
from errors import raise_err
from services.calc import (
    FP_MIN_SAMPLE,
    FP_SUSPEND_THRESHOLD,
    IBR_DOCUMENTS_DUE_DAYS,
    TRAILING_DAYS,
    WEIGHT_FP,
    WEIGHT_OVERTURN,
    TIER_HIGH_MIN,
    TIER_MEDIUM_MIN,
    drg_payment,
    round4,
)

OPEN_IBR_STATUSES = {"REQUESTED", "DOCUMENTS_RECEIVED", "IN_AUDIT"}
OPEN_INPATIENT_STATUSES = {"OPEN", "FINDINGS_RECORDED"}
TERMINAL_TASK_STATUSES = {"DECIDED", "CANCELLED"}
RESOLVED_HIT_STATUSES = {"CONFIRMED", "OVERRIDDEN", "RELEASED_FALSE_POSITIVE", "SUPERSEDED"}


# ---------------------------------------------------------------------------
# EditRule helpers
# ---------------------------------------------------------------------------

def recompute_rule_active_count(rule: dict) -> None:
    count = 0
    for v in db.all_records("edit_versions"):
        if v["edit_rule_id"] == rule["id"] and v["status"] == "ACTIVE":
            count += 1
    rule["active_version_count"] = count
    db.touch(rule)


def windows_overlap(a_from, a_to, b_from, b_to) -> bool:
    """Half-open [from, to) overlap; adjacency (a.from == b.to) allowed."""
    a_end = a_to if a_to is not None else None
    b_end = b_to if b_to is not None else None
    if a_end is not None and b_from >= a_end:
        return False
    if b_end is not None and a_from >= b_end:
        return False
    return True


# ---------------------------------------------------------------------------
# EditVersion quality stats + auto-suspension
# ---------------------------------------------------------------------------

def recompute_version_stats(version: dict) -> None:
    resolved = 0
    fp = 0
    for h in db.all_records("edit_hits"):
        if h["edit_version_id"] != version["id"]:
            continue
        if h["status"] in ("CONFIRMED", "RELEASED_FALSE_POSITIVE"):
            resolved += 1
            if h["status"] == "RELEASED_FALSE_POSITIVE":
                fp += 1
    version["resolved_hits_count"] = resolved
    version["fp_hits_count"] = fp
    if resolved == 0:
        version["fp_rate"] = 0
    else:
        version["fp_rate"] = round4(Decimal(fp) / Decimal(resolved))
    db.touch(version)


def maybe_auto_suspend(version: dict, visited=None) -> None:
    """Auto-suspension: fp_rate >= 0.25 (inclusive) with resolved >= 4."""
    if version["status"] != "ACTIVE":
        return
    if (
        Decimal(str(version["fp_rate"])) >= FP_SUSPEND_THRESHOLD
        and version["resolved_hits_count"] >= FP_MIN_SAMPLE
    ):
        suspend_version(version, visited=visited)


# ---------------------------------------------------------------------------
# EditVersion suspension cascade (manual or auto)
# ---------------------------------------------------------------------------

def suspend_version(version: dict, visited=None) -> None:
    """ACTIVE -> SUSPENDED with full cascade per PRD 3.2."""
    version["status"] = "SUSPENDED"
    db.touch(version)
    rule = db.get("edit_rules", version["edit_rule_id"])
    if rule is not None:
        recompute_rule_active_count(rule)
    # Cascade: cancel open tasks pinned to this version; their hits SUPERSEDED
    for task in db.all_records("review_tasks"):
        if task["status"] not in ("PENDING", "IN_REVIEW"):
            continue
        hit = db.get("edit_hits", task["edit_hit_id"])
        if hit is None or hit["edit_version_id"] != version["id"]:
            continue
        task["status"] = "CANCELLED"
        db.touch(task)
        if hit["status"] == "FIRED":
            _resolve_hit_supersede(hit, visited=visited)


# ---------------------------------------------------------------------------
# Claim ledger + bubble-up
# ---------------------------------------------------------------------------

def rebalance_claim_for_release(claim: dict, hit: dict, released: int) -> None:
    """Move `released` cents from denied back to allowed on claim and line."""
    if released <= 0:
        return
    claim["allowed_amount_cents"] = claim["allowed_amount_cents"] + released
    claim["denied_amount_cents"] = claim["denied_amount_cents"] - released
    if claim["denied_amount_cents"] < 0:
        claim["denied_amount_cents"] = 0
    line = db.get("claim_lines", hit["claim_line_id"])
    if line is not None:
        line["allowed_cents"] = line.get("allowed_cents", 0) + released
        line["denied_cents"] = line.get("denied_cents", 0) - released
        if line["denied_cents"] < 0:
            line["denied_cents"] = 0
        db.touch(line)


def claim_gates_terminal(claim: dict) -> bool:
    """No open IBR and no open inpatient review on the claim."""
    for ibr in db.all_records("ibrs"):
        if ibr["claim_id"] == claim["id"] and ibr["status"] in OPEN_IBR_STATUSES:
            return False
    for rev in db.all_records("inpatient_reviews"):
        if rev["claim_id"] == claim["id"] and rev["status"] in OPEN_INPATIENT_STATUSES:
            return False
    return True


def claim_tasks_terminal(claim: dict) -> bool:
    for task in db.all_records("review_tasks"):
        if task["claim_id"] == claim["id"] and task["status"] not in TERMINAL_TASK_STATUSES:
            return False
    return True


def claim_bubble_up(claim: dict, visited=None) -> None:
    """Claim state machine bubble-up per PRD 3.5 (PENDED -> DETERMINED ->
    READY_TO_PAY|DENIED; DENIED -> READY_TO_PAY compensation)."""
    if visited is None:
        visited = set()
    if claim["id"] in visited:
        return
    visited.add(claim["id"])

    status = claim["status"]
    if status == "PENDED":
        if claim_tasks_terminal(claim):
            claim["status"] = "DETERMINED"
            if claim.get("determined_at") is None:
                claim["determined_at"] = db.now()
            db.touch(claim)
            status = claim["status"]
            # Immediate gate re-evaluation
            if claim_gates_terminal(claim):
                if claim["allowed_amount_cents"] > 0:
                    claim["status"] = "READY_TO_PAY"
                else:
                    claim["status"] = "DENIED"
                db.touch(claim)
    elif status == "DETERMINED":
        if claim_gates_terminal(claim):
            if claim["allowed_amount_cents"] > 0:
                claim["status"] = "READY_TO_PAY"
            else:
                claim["status"] = "DENIED"
            db.touch(claim)
    elif status == "DENIED":
        # Compensation path: release lifted allowed above zero, gates terminal
        if claim["allowed_amount_cents"] > 0 and claim_gates_terminal(claim):
            claim["status"] = "READY_TO_PAY"
            db.touch(claim)


# ---------------------------------------------------------------------------
# Abrasion profile recompute (PRD 3.1)
# ---------------------------------------------------------------------------

def recompute_abrasion(provider_id: str) -> None:
    profile = None
    for p in db.all_records("abrasion_profiles"):
        if p["provider_id"] == provider_id:
            profile = p
            break
    if profile is None:
        return

    now = db.now()
    window_start = now - timedelta(days=TRAILING_DAYS)

    confirmed = overridden = fp = superseded = 0
    denied_lifetime = 0
    released_lifetime = 0
    for hit in db.all_records("edit_hits"):
        if hit["status"] not in RESOLVED_HIT_STATUSES:
            continue
        claim = db.get("claims", hit["claim_id"])
        if claim is None or claim["provider_id"] != provider_id:
            continue
        # Lifetime dollars (all resolved hits, no time bound)
        denied_lifetime += hit.get("attributed_savings_cents", 0)
        released_lifetime += hit.get("released_cents", 0)
        # Trailing 90-day counts by resolved_at
        resolved_at = hit.get("resolved_at")
        if resolved_at is not None and window_start <= resolved_at <= now:
            if hit["status"] == "CONFIRMED":
                confirmed += 1
            elif hit["status"] == "OVERRIDDEN":
                overridden += 1
            elif hit["status"] == "RELEASED_FALSE_POSITIVE":
                fp += 1
            elif hit["status"] == "SUPERSEDED":
                superseded += 1

    open_ibr = 0
    for ibr in db.all_records("ibrs"):
        if ibr["provider_id"] == provider_id and ibr["status"] in OPEN_IBR_STATUSES:
            open_ibr += 1

    profile["confirmed_count"] = confirmed
    profile["overridden_count"] = overridden
    profile["fp_count"] = fp
    profile["superseded_count"] = superseded
    profile["denied_cents_lifetime"] = denied_lifetime
    profile["released_cents_lifetime"] = released_lifetime
    profile["open_ibr_count"] = open_ibr

    resolved = confirmed + overridden + fp + superseded
    if resolved == 0:
        profile["standard_index"] = 0
    else:
        overturn_rate = Decimal(overridden + fp) / Decimal(resolved)
        fp_rate = Decimal(fp) / Decimal(resolved)
        idx = WEIGHT_OVERTURN * overturn_rate + WEIGHT_FP * fp_rate
        profile["standard_index"] = round4(idx)

    if denied_lifetime == 0:
        profile["regulatory_index"] = round4(Decimal(released_lifetime) / Decimal(1))
    else:
        profile["regulatory_index"] = round4(Decimal(released_lifetime) / Decimal(denied_lifetime))

    std = Decimal(str(profile["standard_index"]))
    if std >= TIER_HIGH_MIN:
        profile["tier"] = "HIGH"
    elif std >= TIER_MEDIUM_MIN:
        profile["tier"] = "MEDIUM"
    else:
        profile["tier"] = "LOW"
    profile["monitor_only"] = profile["tier"] == "HIGH"
    db.touch(profile)


# ---------------------------------------------------------------------------
# EditHit resolutions
# ---------------------------------------------------------------------------

def _after_hit_resolved(hit: dict, visited=None) -> None:
    """Shared ripple after any hit leaves FIRED/CONFIRMED for a terminal
    state: version stats (+ auto-suspension checkpoint), abrasion recompute,
    claim bubble-up. Claim version bump is the caller's responsibility where
    the endpoint contract specifies it."""
    version = db.get("edit_versions", hit["edit_version_id"])
    if version is not None:
        recompute_version_stats(version)
        maybe_auto_suspend(version, visited=visited)
    claim = db.get("claims", hit["claim_id"])
    if claim is not None:
        recompute_abrasion(claim["provider_id"])
        db.touch(claim)
        claim_bubble_up(claim, visited=visited)


def resolve_hit_uphold(hit: dict, confirmer_user_id: str, visited=None) -> None:
    hit["status"] = "CONFIRMED"
    hit["confirmed_by_user_id"] = confirmer_user_id
    hit["resolved_at"] = db.now()
    db.touch(hit)
    _after_hit_resolved(hit, visited=visited)


def resolve_hit_override(hit: dict, released: int, visited=None) -> None:
    hit["status"] = "OVERRIDDEN"
    hit["released_cents"] = released
    hit["resolved_at"] = db.now()
    db.touch(hit)
    claim = db.get("claims", hit["claim_id"])
    if claim is not None:
        rebalance_claim_for_release(claim, hit, released)
    _after_hit_resolved(hit, visited=visited)


def resolve_hit_false_positive(hit: dict, visited=None) -> None:
    hit["status"] = "RELEASED_FALSE_POSITIVE"
    hit["released_cents"] = hit["attributed_savings_cents"]
    hit["resolved_at"] = db.now()
    db.touch(hit)
    claim = db.get("claims", hit["claim_id"])
    if claim is not None:
        rebalance_claim_for_release(claim, hit, hit["released_cents"])
    _after_hit_resolved(hit, visited=visited)


def _resolve_hit_supersede(hit: dict, visited=None) -> None:
    hit["status"] = "SUPERSEDED"
    hit["released_cents"] = hit["attributed_savings_cents"]
    hit["resolved_at"] = db.now()
    db.touch(hit)
    claim = db.get("claims", hit["claim_id"])
    if claim is not None:
        rebalance_claim_for_release(claim, hit, hit["released_cents"])
        recompute_abrasion(claim["provider_id"])
        db.touch(claim)
        claim_bubble_up(claim, visited=visited)
    version = db.get("edit_versions", hit["edit_version_id"])
    if version is not None:
        recompute_version_stats(version)


# ---------------------------------------------------------------------------
# IBR occupancy (PRD 3.7)
# ---------------------------------------------------------------------------

def provider_ibr_overlap(provider_id: str, now) -> bool:
    """True iff the provider has another IBR whose occupancy interval
    [requested_at, completed_at + 14d] (closed; open IBRs end at now)
    contains now."""
    for ibr in db.all_records("ibrs"):
        if ibr["provider_id"] != provider_id:
            continue
        if ibr["status"] in OPEN_IBR_STATUSES:
            interval_end = now
        elif ibr["status"] == "COMPLETED":
            interval_end = ibr["completed_at"] + timedelta(days=14)
        else:  # EXPIRED — occupancy ends... treat as ending at updated_at
            interval_end = ibr["updated_at"]
        if ibr["requested_at"] <= now <= interval_end:
            return True
    return False
