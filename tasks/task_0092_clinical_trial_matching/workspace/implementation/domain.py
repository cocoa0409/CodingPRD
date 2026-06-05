"""Domain helpers: resource creation, mutation/version bookkeeping, derived
field reconciliation (PRD §2.4 / §2.5), and the arm-selection policy (PRD §3.4).

Every mutation refreshes updated_at and increments the owning resource's
version (PRD §2.4 / §2.5). Derived counters and trial posture are recomputed
from the underlying facts whenever they change — never set directly.
"""
from decimal import Decimal

import clock
import db


def touch(rec):
    """Record a mutation: refresh updated_at and bump version (PRD §2.4)."""
    rec["updated_at"] = clock.now()
    rec["version"] = rec["version"] + 1


def make_base():
    """Common fields for a freshly created resource (PRD §2.4)."""
    from util import new_id

    now = clock.now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


# --- collection helpers ----------------------------------------------------

def trial_criteria(trial_id):
    return [c for c in db.criteria.values() if c["trial_id"] == trial_id]


def trial_arms(trial_id):
    return [a for a in db.arms.values() if a["trial_id"] == trial_id]


def trial_consents(trial_id):
    return [d for d in db.consent_documents.values() if d["trial_id"] == trial_id]


def trial_enrollments(trial_id):
    return [e for e in db.enrollments.values() if e["trial_id"] == trial_id]


def enrollment_visits(enrollment_id):
    return [v for v in db.visits.values() if v["enrollment_id"] == enrollment_id]


def enrollment_adverse_events(enrollment_id):
    return [ae for ae in db.adverse_events.values() if ae["enrollment_id"] == enrollment_id]


def enrollment_payments(enrollment_id):
    return [p for p in db.payments.values() if p["enrollment_id"] == enrollment_id]


def active_consent(trial_id):
    """The trial's current ACTIVE ConsentDocument, or None (PRD §3.2)."""
    for d in trial_consents(trial_id):
        if d["status"] == "ACTIVE":
            return d
    return None


def sorted_by_created(records):
    """Stable created_at ASC ordering using the monotonic insertion seq."""
    return sorted(records, key=lambda r: r["_seq"])


# --- derived state reconciliation (PRD §2.5) -------------------------------

def recompute_enrolled_count(trial):
    n = sum(
        1 for e in trial_enrollments(trial["id"])
        if e["enrollment_status"] in ("RANDOMIZED", "ACTIVE", "COMPLETED")
    )
    trial["enrolled_count"] = n


def recompute_active_safety_holds(trial):
    n = sum(1 for e in trial_enrollments(trial["id"]) if e["safety_status"] == "HOLD")
    trial["active_safety_holds"] = n


def recompute_arm_assigned_count(arm):
    n = sum(
        1 for e in db.enrollments.values()
        if e["arm_id"] == arm["id"]
        and e["enrollment_status"] in ("RANDOMIZED", "ACTIVE", "COMPLETED")
    )
    arm["assigned_count"] = n


def compute_posture(trial):
    """Derive the trial's posture from irb_status, arms, active consent, and
    safety holds (PRD §2.5).

    FROZEN when one or more active safety holds. Otherwise OPEN when the protocol
    is APPROVED, >=1 arm exists, and an ACTIVE consent exists. Otherwise SETUP.
    """
    if trial["active_safety_holds"] >= 1:
        return "FROZEN"
    if (trial["irb_status"] == "APPROVED"
            and len(trial_arms(trial["id"])) >= 1
            and active_consent(trial["id"]) is not None):
        return "OPEN"
    return "SETUP"


def recompute_trial_posture(trial):
    """Recompute and store the trial's posture from current derived facts.

    This only writes the derived field; it does NOT bump the trial's version.
    Every workflow that recomputes posture (IRB decision, consent activation,
    randomize, withdraw, hold place/lift) performs exactly one explicit trial
    version bump for the whole logical operation per PRD §3 — the scaffold lists
    "recompute Trial.posture; increments Trial.version by 1" as a single bump.
    Callers that must record a trial mutation call `touch(trial)` themselves.
    """
    trial["posture"] = compute_posture(trial)


# --- arm selection policy (PRD §3.4) ---------------------------------------

def _pick_largest_deficit(arms_ordered, fair_share_by_id, assigned_by_id):
    """Greedy pick: largest deficit = fair_share - assigned; ties go to the arm
    earlier in created_at order (arms_ordered is already created_at ASC)."""
    best = None
    best_deficit = None
    for a in arms_ordered:
        deficit = fair_share_by_id[a["id"]] - Decimal(assigned_by_id[a["id"]])
        if best_deficit is None or deficit > best_deficit:
            best = a
            best_deficit = deficit
    return best


def select_arm(trial):
    """Deterministic randomization-arm selector (PRD §3.4 / SCAFFOLD selector
    arm_selection). Pick the arm most under its fair share (largest deficit);
    ties broken by smaller created_at (insertion seq), never id.

    For PERMUTED_BLOCK the fair share is computed within the current block of
    size block_size (block index = floor(enrolled_count / block_size)) and
    deficits reset at each block boundary. Within-block per-arm counts are
    reconstructed deterministically by replaying the same greedy rule from the
    start of the current block — the scheme has no RNG, so the replay reproduces
    exactly how the block filled up to the current position.
    """
    arms = trial_arms(trial["id"])
    if not arms:
        return None

    arms_ordered = sorted_by_created(arms)
    sum_weights = sum(a["allocation_weight"] for a in arms)
    method = trial["randomization_method"]
    block_size = trial.get("block_size")

    if method == "PERMUTED_BLOCK" and block_size:
        base = block_size
        position_in_block = trial["enrolled_count"] % block_size
    else:
        base = trial["target_enrollment"]
        position_in_block = None

    fair_share_by_id = {
        a["id"]: Decimal(base) * Decimal(a["allocation_weight"]) / Decimal(sum_weights)
        for a in arms_ordered
    }

    if position_in_block is None:
        # SIMPLE (or PERMUTED_BLOCK without a block_size): deficit against the
        # arm's live cumulative assigned_count.
        assigned_by_id = {a["id"]: a["assigned_count"] for a in arms_ordered}
        return _pick_largest_deficit(arms_ordered, fair_share_by_id, assigned_by_id)

    # PERMUTED_BLOCK: replay the greedy fill for the current block from 0 up to
    # position_in_block, then return the arm that would be chosen next.
    within_block = {a["id"]: 0 for a in arms_ordered}
    for _ in range(position_in_block):
        chosen = _pick_largest_deficit(arms_ordered, fair_share_by_id, within_block)
        within_block[chosen["id"]] += 1
    return _pick_largest_deficit(arms_ordered, fair_share_by_id, within_block)
