"""Domain helpers: entity touch, serialization, expiry sweep, posture evaluation."""

from datetime import date

import db
from services import calc


# ---------------------------------------------------------------------------
# Mutation bookkeeping (PRD §2.5, §2.10)
# ---------------------------------------------------------------------------

def touch(entity: dict) -> None:
    """Refresh updated_at and increment version on a mutated resource."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = int(entity["version"]) + 1


def stamp_new(entity: dict) -> dict:
    """Populate common system fields on a fresh entity."""
    entity["id"] = db.new_id()
    ts = db.now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


# ---------------------------------------------------------------------------
# Serialization — Decimal -> JSON-friendly numbers
# ---------------------------------------------------------------------------

def _jsonify_value(v):
    from decimal import Decimal
    if isinstance(v, Decimal):
        return calc._dec4_to_jsonable(v)
    return v


def serialize(entity: dict) -> dict:
    return {k: _jsonify_value(v) for k, v in entity.items()}


def serialize_list(entities) -> list:
    return [serialize(e) for e in entities]


# ---------------------------------------------------------------------------
# Expiry sweep (PRD §2.4, §3.5): on read, BOUND policies whose policy_end_date
# has passed relative to the logical clock move to EXPIRED.
# ---------------------------------------------------------------------------

def run_expiry_sweep() -> None:
    today = db.get_logical_clock().date()
    affected_programs = set()
    for p in db.policies.values():
        if p["lifecycle_status"] != "BOUND":
            continue
        end = date.fromisoformat(p["policy_end_date"])
        if today > end:
            p["lifecycle_status"] = "EXPIRED"
            touch(p)
            # still-open invoice? expiry after binding means invoice was PAID; nothing to void
            affected_programs.add(p["program_id"])
    for pid in affected_programs:
        prog = db.programs.get(pid)
        if prog:
            calc.recompute_net_retained_exposure(prog)
            touch(prog)


# ---------------------------------------------------------------------------
# Settlement posture re-evaluation (PRD §3.5 parallel dimension)
# ---------------------------------------------------------------------------

_TERMINAL_CLAIM_STATES = {"PAID", "RECOVERY_CEDED", "DECLINED", "VOIDED"}


def reevaluate_policy_posture(policy: dict) -> None:
    """Re-derive settlement_posture from the policy's claims (PRD §3.5).

    - Any claim in APPROVED or FRAUD_HOLD -> PAYMENT_PENDING
    - Else if at least one claim exists and all claims terminal -> SETTLED_QUIET
    - Else if a claim exists in GENERATED/ADJUSTED and posture was SETTLED_QUIET
      -> PAYMENT_PENDING (late event after quiet)
    - Else leave as-is (claims GENERATED alone do not disturb CLEAR posture).
    """
    policy_claims = [c for c in db.claims.values() if c["policy_id"] == policy["id"]]
    new_posture = policy["settlement_posture"]
    if any(c["status"] in ("APPROVED", "FRAUD_HOLD") for c in policy_claims):
        new_posture = "PAYMENT_PENDING"
    elif policy_claims and all(c["status"] in _TERMINAL_CLAIM_STATES for c in policy_claims):
        new_posture = "SETTLED_QUIET"
    elif policy["settlement_posture"] == "SETTLED_QUIET" and any(
        c["status"] in ("GENERATED", "ADJUSTED") for c in policy_claims
    ):
        new_posture = "PAYMENT_PENDING"
    if new_posture != policy["settlement_posture"]:
        policy["settlement_posture"] = new_posture
        touch(policy)


# ---------------------------------------------------------------------------
# Program aggregate reconciliation
# ---------------------------------------------------------------------------

def reconcile_program_aggregates(program: dict) -> None:
    calc.recompute_net_retained_exposure(program)
    calc.recompute_fraud_alert_count(program)
