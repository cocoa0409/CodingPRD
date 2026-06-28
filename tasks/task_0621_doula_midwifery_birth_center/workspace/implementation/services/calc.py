"""Calculations and derived-field reconciliation (PRD §3.6, §3.7, §3.10, §2.10).

All monetary quantities are integer cents; the only fractional multiply is the
self-pay estimate, rounded half up (§2.7).
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db
from common import touch

# Constants (scaffold §1.3)
SELF_PAY_ESTIMATE_PCT = Decimal("0.20")
BP_ELEVATED_THRESHOLD = 140
BP_TRANSFER_THRESHOLD = 160
WATCH_ESCALATION_COUNT = 2
TRANSFER_FEE_CENTS = 75000

_FLAG_ORDER = {"NONE": 0, "WATCH": 1, "TRANSFER": 2}


# ---------------------------------------------------------------------------
# charge_client_responsibility (dual/tri-variant) — §3.6
# ---------------------------------------------------------------------------
def estimate_responsibility(amount_cents):
    """ESTIMATE variant: amount * 0.20, rounded half up to a whole cent."""
    product = (Decimal(amount_cents) * SELF_PAY_ESTIMATE_PCT).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(product)


def claim_for_charge(charge):
    cid = charge.get("claim_id") or ""
    if not cid:
        return None
    return db.insurance_claims.get(cid)


def compute_charge_responsibility(charge):
    """Compute client_responsibility_cents for a charge given its linked claim.

    GLOBAL_FEE:
      ESTIMATE   (no claim, or claim SUBMITTED): amount * 0.20 round_half_up
      ADJUDICATED (claim ADJUDICATED): allowed - paid
      DENIED      (claim DENIED): full amount
      (claim VOID): reverts to ESTIMATE
    EXTRA_VISIT / SUPPLY / TRANSFER_FEE: always full amount.
    """
    if charge["charge_kind"] != "GLOBAL_FEE":
        return charge["amount_cents"]
    claim = claim_for_charge(charge)
    if claim is None or claim["status"] in ("SUBMITTED", "VOID"):
        return estimate_responsibility(charge["amount_cents"])
    if claim["status"] == "ADJUDICATED":
        return claim["allowed_amount_cents"] - claim["paid_amount_cents"]
    if claim["status"] == "DENIED":
        return charge["amount_cents"]
    return estimate_responsibility(charge["amount_cents"])


def recompute_global_charge(episode):
    """Recompute the episode's GLOBAL_FEE charge responsibility in place.

    Returns True if the charge value changed (so the charge's own version may
    be bumped by the caller if it is treated as a mutation)."""
    for ch in db.charges.values():
        if ch["episode_id"] == episode["id"] and ch["charge_kind"] == "GLOBAL_FEE":
            new_val = compute_charge_responsibility(ch)
            if ch["client_responsibility_cents"] != new_val:
                ch["client_responsibility_cents"] = new_val
                return True
    return False


# ---------------------------------------------------------------------------
# episode_balance_due (pinned two-step order) — §3.10
# ---------------------------------------------------------------------------
def episode_plan(episode):
    """Return the episode's PaymentPlan if present (any status)."""
    for p in db.payment_plans.values():
        if p["episode_id"] == episode["id"]:
            return p
    return None


def compute_balance_due(episode):
    # STEP 1: sum client responsibility across DRAFT/BILLED charges.
    gross = 0
    for ch in db.charges.values():
        if ch["episode_id"] == episode["id"] and ch["status"] in ("DRAFT", "BILLED"):
            gross += ch["client_responsibility_cents"]
    # STEP 2: consult the plan only if one in {OPEN, PAID_OFF} exists.
    plan = episode_plan(episode)
    if plan is not None and plan["status"] in ("OPEN", "PAID_OFF"):
        return max(0, plan["total_cents"] - plan["paid_cents"])
    return gross


def rederive_balance(episode):
    """Recompute balance_due_cents on the episode in place; return change flag."""
    new_bal = compute_balance_due(episode)
    if episode["balance_due_cents"] != new_bal:
        episode["balance_due_cents"] = new_bal
        return True
    return False


# ---------------------------------------------------------------------------
# episode_risk_tier (combinatorial weighted scoring) — §3.7
# ---------------------------------------------------------------------------
def compute_risk_tier(episode):
    completed = [v for v in db.prenatal_visits.values()
                 if v["episode_id"] == episode["id"] and v["status"] == "COMPLETED"]
    if not completed:
        return "LOW"
    worst = max((_FLAG_ORDER.get(v.get("risk_flag"), 0) for v in completed), default=0)
    systolics = [v["blood_pressure_systolic"] for v in completed
                 if v.get("blood_pressure_systolic") is not None]
    max_sys = max(systolics) if systolics else 0
    watch_count = sum(1 for v in completed if v.get("risk_flag") == "WATCH")

    if worst == _FLAG_ORDER["TRANSFER"]:
        return "TRANSFER_REQUIRED"
    if max_sys >= BP_TRANSFER_THRESHOLD:
        return "TRANSFER_REQUIRED"
    if worst == _FLAG_ORDER["WATCH"] and watch_count >= WATCH_ESCALATION_COUNT:
        return "TRANSFER_REQUIRED"
    if worst == _FLAG_ORDER["WATCH"]:
        return "ELEVATED"
    if max_sys >= BP_ELEVATED_THRESHOLD:
        return "ELEVATED"
    return "LOW"


def rederive_risk_tier(episode):
    new_tier = compute_risk_tier(episode)
    if episode["risk_tier"] != new_tier:
        episode["risk_tier"] = new_tier
        return True
    return False


def completed_visit_count(episode):
    return sum(1 for v in db.prenatal_visits.values()
               if v["episode_id"] == episode["id"] and v["status"] == "COMPLETED")


# ---------------------------------------------------------------------------
# supply_kit_counters (derived-field reconciliation) — §2.10, §1.3
# ---------------------------------------------------------------------------
def episodes_reserving_kit(sku):
    out = []
    for ep in db.episodes.values():
        if not ep.get("_kit_sku"):
            continue
        if ep["_kit_sku"] == sku:
            out.append(ep)
    return out


def reconcile_kit(kit):
    """Recompute reserved_count/consumed_count from episode clinical_status."""
    sku = kit["sku"]
    reserved = 0
    consumed = 0
    for ep in episodes_reserving_kit(sku):
        if ep["clinical_status"] in ("PLANNING", "ACTIVE"):
            reserved += 1
        elif ep["clinical_status"] in ("BORN", "COMPLETED", "TRANSFERRED"):
            consumed += 1
    changed = (kit["reserved_count"] != reserved) or (kit["consumed_count"] != consumed)
    kit["reserved_count"] = reserved
    kit["consumed_count"] = consumed
    return changed


def kit_available(kit):
    return kit["on_hand_count"] - kit["reserved_count"]


# ---------------------------------------------------------------------------
# provider_capacity_load (dual-variant) — §3.4
# ---------------------------------------------------------------------------
def primary_load(provider_id):
    """PRIMARY-LOAD: PRIMARY rows in {ASSIGNED, ON_DUTY} plus BACKUP rows PROMOTED."""
    load = 0
    for a in db.on_call_assignments.values():
        if a["provider_id"] != provider_id:
            continue
        if a["coverage_role"] == "PRIMARY" and a["status"] in ("ASSIGNED", "ON_DUTY"):
            load += 1
        elif a["coverage_role"] == "BACKUP" and a["status"] == "PROMOTED":
            load += 1
    return load


def sync_provider_active_count(provider):
    """Persist the PRIMARY-LOAD variant into active_assignment_count."""
    new_count = primary_load(provider["id"])
    if provider["active_assignment_count"] != new_count:
        provider["active_assignment_count"] = new_count
        return True
    return False
