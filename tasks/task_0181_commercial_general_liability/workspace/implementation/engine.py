"""Calculations & cascades (PRD §2.7, §2.9, §3.2, §3.6, §3.8).

All money is integer cents — no floats.
"""
from db import db
from common import touch, parse_dt

BASIS_DIVISOR = 1000
IMPAIRED_FRACTION_NUM = 1
IMPAIRED_FRACTION_DEN = 4


# ---------------------------------------------------------------------------
# Premium rating (PRD §2.9, §3.2, §3.8) — truncate-then-multiply, then floor.
# ---------------------------------------------------------------------------
def rate_premium(exposure_units, rate_per_unit_cents, minimum_premium_cents):
    raw = (exposure_units // BASIS_DIVISOR) * rate_per_unit_cents
    return max(raw, minimum_premium_cents)


# ---------------------------------------------------------------------------
# Claim incurred (PRD §3.6, calc claim_incurred)
# ---------------------------------------------------------------------------
def claim_transactions(claim_id):
    txns = [t for t in db.claim_transactions.values() if t["claim_id"] == claim_id]
    return sorted(txns, key=lambda t: t["posted_sequence"])


def compute_open_reserve(claim_id):
    reserve_set = 0
    reserve_release = 0
    for t in claim_transactions(claim_id):
        if t["txn_type"] == "RESERVE_SET":
            reserve_set += t["amount_cents"]
        elif t["txn_type"] == "RESERVE_RELEASE":
            reserve_release += t["amount_cents"]
    return max(reserve_set - reserve_release, 0)


def compute_incurred(claim_id):
    open_reserve = compute_open_reserve(claim_id)
    payments = 0
    recoveries = 0
    for t in claim_transactions(claim_id):
        if t["txn_type"] == "PAYMENT":
            payments += t["amount_cents"]
        elif t["txn_type"] == "RECOVERY":
            recoveries += t["amount_cents"]
    return max(open_reserve + payments - recoveries, 0)


def first_reserve_sequence(claim_id):
    """posted_sequence of the claim's first RESERVE_SET, or None."""
    for t in claim_transactions(claim_id):
        if t["txn_type"] == "RESERVE_SET":
            return t["posted_sequence"]
    return None


# ---------------------------------------------------------------------------
# Aggregate erosion (PRD §3.6, calc aggregate_erosion)
# ---------------------------------------------------------------------------
def recompute_aggregates_and_posture(policy):
    """Recompute every claim's recognized_incurred_cents, the two aggregate-
    remaining figures, and the policy posture. Touch each mutated claim and the
    policy. Returns nothing; mutates records in place.
    """
    policy_id = policy["id"]
    each_occ = policy["each_occurrence_limit_cents"]
    gen_limit = policy["general_aggregate_limit_cents"]
    prod_limit = policy["products_aggregate_limit_cents"]

    # Non-DENIED claims of this policy, ordered by (first RESERVE_SET seq ASC,
    # then claim created_at ASC). Claims with no RESERVE_SET sort after those
    # that have one (their incurred is 0 anyway).
    claims = [c for c in db.claims.values()
              if c["policy_id"] == policy_id and c["status"] != "DENIED"]

    def order_key(c):
        seq = first_reserve_sequence(c["id"])
        seq_key = seq if seq is not None else float("inf")
        return (seq_key, c.get("_seq", 0))

    claims.sort(key=order_key)

    cumulative = {"GENERAL": 0, "PRODUCTS": 0}

    for c in claims:
        incurred = c["incurred_cents"]
        per_occ_capped = min(incurred, each_occ)
        bucket = c["aggregate_bucket"]
        limit = gen_limit if bucket == "GENERAL" else prod_limit
        room = limit - cumulative[bucket]
        recognized = min(per_occ_capped, max(room, 0))
        if recognized < 0:
            recognized = 0
        if c["recognized_incurred_cents"] != recognized:
            c["recognized_incurred_cents"] = recognized
            touch(c)
        cumulative[bucket] += recognized

    new_gen_remaining = max(gen_limit - cumulative["GENERAL"], 0)
    new_prod_remaining = max(prod_limit - cumulative["PRODUCTS"], 0)
    policy["general_aggregate_remaining_cents"] = new_gen_remaining
    policy["products_aggregate_remaining_cents"] = new_prod_remaining

    # Posture (PRD §3.6, calc policy_posture)
    g = new_gen_remaining
    p = new_prod_remaining
    if g == 0 and p == 0:
        posture = "EXHAUSTED"
    else:
        gen_threshold = (gen_limit * IMPAIRED_FRACTION_NUM) // IMPAIRED_FRACTION_DEN
        prod_threshold = (prod_limit * IMPAIRED_FRACTION_NUM) // IMPAIRED_FRACTION_DEN
        if g <= gen_threshold or p <= prod_threshold:
            posture = "IMPAIRED"
        else:
            posture = "HEALTHY"
    policy["posture"] = posture


def recompute_claim_and_cascade(claim, policy, bump_policy_version=True):
    """Recompute the claim's incurred, then cascade erosion + posture onto the
    policy. The claim is touched, every recognized-changed sibling claim is
    touched, and the policy is touched (which is the policy version bump).
    """
    new_incurred = compute_incurred(claim["id"])
    claim["incurred_cents"] = new_incurred
    touch(claim)
    recompute_aggregates_and_posture(policy)
    if bump_policy_version:
        touch(policy)
