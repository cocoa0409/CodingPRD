"""Entity record helpers: common-fields minting, versioned mutation, lookups,
and derived-field recomputation (PRD §2.4, §2.8, §3.x).

Every entity carries id (UUID, no prefix), created_at (ISO8601, 3 frac digits),
updated_at, and integer version. version starts at 1 on creation and increments
by one on every mutation; updated_at refreshes on every mutation.
"""
import db
from errors import err

import calc
import constants


# --------------------------------------------------------------------------
# Record creation / mutation with common fields and versioning
# --------------------------------------------------------------------------
def new_record(fields):
    """Create a record dict with common fields stamped. version starts at 1."""
    now = db.now_iso()
    rec = dict(fields)
    rec["id"] = db.new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Mark a record mutated: bump version and refresh updated_at (PRD §2.4)."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = db.now_iso()


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
def get_or_404(table, rid):
    rec = table.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


# --------------------------------------------------------------------------
# Derived-field recomputation
# --------------------------------------------------------------------------
def recompute_coverage_line(cl):
    """remaining_limit_cents = limit_cents - settled_cents, never below 0 (PRD §3.6)."""
    remaining = cl["limit_cents"] - cl["settled_cents"]
    if remaining < 0:
        remaining = 0
    cl["remaining_limit_cents"] = remaining


def recompute_invoice(inv):
    """paid_cents = sum of CLEARED payments; balance_due_cents = amount - paid (PRD §3.3)."""
    paid = 0
    for p in db.payments.values():
        if p["invoice_id"] == inv["id"] and p["status"] == "CLEARED":
            paid += p["amount_cents"]
    inv["paid_cents"] = paid
    inv["balance_due_cents"] = inv["amount_cents"] - paid


# --------------------------------------------------------------------------
# Bundle membership / discount recomputation (PRD §3.1)
# --------------------------------------------------------------------------
def recompute_bundle(bundle):
    """Recompute active_member_count + discount_active, drive FORMING/ACTIVE/DISSOLVED
    bubble-up/down with premium cascade. Returns True if mutated."""
    count = 0
    for pol in db.policies.values():
        if pol.get("bundle_id") == bundle["id"] and pol["status"] in ("ACTIVE", "LAPSED"):
            count += 1
    old_count = bundle["active_member_count"]
    old_discount = bundle["discount_active"]
    old_status = bundle["status"]

    new_discount = count >= constants.MIN_BUNDLE_MEMBERS
    new_status = old_status
    if old_status == "FORMING" and count >= constants.MIN_BUNDLE_MEMBERS:
        new_status = "ACTIVE"
    elif old_status == "ACTIVE" and count < constants.MIN_BUNDLE_MEMBERS:
        new_status = "DISSOLVED"

    changed = (count != old_count or new_discount != old_discount or new_status != old_status)
    if not changed:
        return False

    bundle["active_member_count"] = count
    discount_flipped = new_discount != old_discount
    bundle["discount_active"] = new_discount
    bundle["status"] = new_status
    touch(bundle)

    # Cascade: when discount eligibility flips, re-run premium on member policies.
    if discount_flipped:
        for pol in db.policies.values():
            if pol.get("bundle_id") == bundle["id"]:
                recompute_premium(pol)
    return True


def bundle_discount_active(policy):
    """Whether the policy's bundle currently grants the discount multiplier."""
    bid = policy.get("bundle_id")
    if not bid:
        return False
    bundle = db.bundles.get(bid)
    if bundle is None:
        return False
    return bool(bundle["discount_active"])


# --------------------------------------------------------------------------
# Premium recomputation for a policy (PRD §3.2 premium_calculation)
# --------------------------------------------------------------------------
def recompute_premium(policy):
    """Recompute annual_premium_cents from current coverage lines + scheduled items."""
    pp_limit = 0
    liab_limit = 0
    lou_limit = 0
    for cl in db.coverage_lines.values():
        if cl["policy_id"] != policy["id"]:
            continue
        if cl["coverage_type"] == "PERSONAL_PROPERTY":
            pp_limit = cl["limit_cents"]
        elif cl["coverage_type"] == "LIABILITY":
            liab_limit = cl["limit_cents"]
        elif cl["coverage_type"] == "LOSS_OF_USE":
            lou_limit = cl["limit_cents"]
    sched_sum = 0
    for si in db.scheduled_items.values():
        if si["policy_id"] == policy["id"] and si["status"] != "REMOVED":
            sched_sum += si["appraised_value_cents"]

    premium = calc.compute_premium(
        pp_limit, liab_limit, lou_limit, sched_sum,
        policy["territory_code"], bundle_discount_active(policy),
    )
    policy["annual_premium_cents"] = premium
    touch(policy)
    return premium


# --------------------------------------------------------------------------
# Serialization — strip internal fields (_seq, pre-suspension status)
# --------------------------------------------------------------------------
_INTERNAL_PREFIX = "_"


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith(_INTERNAL_PREFIX)}
