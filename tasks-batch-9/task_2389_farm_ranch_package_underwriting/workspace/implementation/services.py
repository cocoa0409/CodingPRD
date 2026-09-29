"""Row lookups, the premium ledger, capacity bookkeeping and every cascade."""

import uuid
from datetime import timedelta

import calc
import db
from db import by_created, fmt_datetime, new_row, now_dt, now_str, store, touch
from errors import ApiError

TERMINAL_UW = ("DECLINED", "CANCELLED")


# ----------------------------------------------------------------- collections

def policies_of_account(account_id):
    return [p for p in store.policies.values() if p["account_id"] == account_id]


def items_of_policy(policy_id):
    return by_created([r for r in store.scheduled_items.values() if r["policy_id"] == policy_id])


def active_items_of_policy(policy_id):
    return [r for r in items_of_policy(policy_id) if r["status"] == "ACTIVE"]


def livestock_of_policy(policy_id):
    return by_created([r for r in store.livestock_groups.values() if r["policy_id"] == policy_id])


def liability_of_policy(policy_id):
    return by_created([r for r in store.liability_exposures.values() if r["policy_id"] == policy_id])


def endorsements_of_policy(policy_id):
    return by_created([r for r in store.endorsements.values() if r["policy_id"] == policy_id])


def labor_profile_of_policy(policy_id):
    rows = by_created([r for r in store.labor_profiles.values() if r["policy_id"] == policy_id])
    return rows[0] if rows else None


def inspections_of_policy(policy_id):
    return by_created([r for r in store.inspections.values() if r["policy_id"] == policy_id])


def recommendations_of_inspection(inspection_id):
    rows = [r for r in store.recommendations.values() if r["inspection_id"] == inspection_id]
    return sorted(rows, key=lambda r: (r["sequence_no"], r["_seq"]))


def recommendations_of_policy(policy_id):
    rows = []
    for inspection in inspections_of_policy(policy_id):
        rows.extend(recommendations_of_inspection(inspection["id"]))
    return sorted(rows, key=lambda r: (r["sequence_no"], r["created_at"], r["_seq"]))


def reservations_of_policy(policy_id):
    return by_created([r for r in store.reservations.values() if r["policy_id"] == policy_id])


def ledger_of_policy(policy_id):
    rows = [r for r in store.premium_txns.values() if r["policy_id"] == policy_id]
    return sorted(rows, key=lambda r: r["sequence_no"])


def pool_for(zone_code, peril):
    for pool in store.pools.values():
        if pool["zone_code"] == zone_code and pool["peril"] == peril:
            return pool
    return None


def account_of_policy(policy):
    return store.accounts.get(policy["account_id"])


def policy_of_inspection(inspection):
    return store.policies.get(inspection["policy_id"])


def inspection_of_recommendation(recommendation):
    return store.inspections.get(recommendation["inspection_id"])


def latest_completed_inspection(policy_id):
    completed = [r for r in inspections_of_policy(policy_id) if r["status"] == "COMPLETED"]
    if not completed:
        return None
    return sorted(
        completed,
        key=lambda r: (r["completed_at"] or "", r["created_at"], r["_seq"]),
    )[-1]


# ------------------------------------------------------------------ lookup gate

def require(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def guard_policy_open(policy):
    if policy["uw_status"] in TERMINAL_UW:
        raise ApiError("ERR_POLICY_TERMINAL")


# ---------------------------------------------------------------- pool figures

def recompute_pool(pool, bump=True):
    reserved = 0
    committed = 0
    for reservation in store.reservations.values():
        if reservation["pool_id"] != pool["id"]:
            continue
        if reservation["status"] == "RESERVED":
            reserved += reservation["amount_cents"]
        elif reservation["status"] == "COMMITTED":
            committed += reservation["amount_cents"]
    pool["reserved_cents"] = reserved
    pool["committed_cents"] = committed
    pool["available_cents"] = pool["total_capacity_cents"] - reserved - committed
    if bump:
        touch(pool)
    return pool


# --------------------------------------------------------------------- ledger

def next_sequence_no(policy_id):
    entries = ledger_of_policy(policy_id)
    return (entries[-1]["sequence_no"] + 1) if entries else 1


def append_txn(policy, txn_type, reason_code, amount_cents, reverses_sequence_no=None):
    row = {
        "id": str(uuid.uuid4()),
        "_seq": store.next_seq(),
        "policy_id": policy["id"],
        "sequence_no": next_sequence_no(policy["id"]),
        "txn_type": txn_type,
        "reason_code": reason_code,
        "amount_cents": int(amount_cents),
        "reverses_sequence_no": reverses_sequence_no,
        "created_at": now_str(),
    }
    store.premium_txns[row["id"]] = row
    return row


def reversal_batch(policy, reason_code):
    """One REVERSAL per prior non-reversed entry, replayed in sequence_no order."""
    entries = ledger_of_policy(policy["id"])
    already_reversed = {
        e["reverses_sequence_no"] for e in entries if e["reverses_sequence_no"] is not None
    }
    sources = [
        e for e in entries
        if e["txn_type"] != "REVERSAL" and e["sequence_no"] not in already_reversed
    ]
    for source in sources:
        append_txn(
            policy,
            "REVERSAL",
            reason_code,
            -source["amount_cents"],
            reverses_sequence_no=source["sequence_no"],
        )


def ledger_sum(policy_id):
    return sum(e["amount_cents"] for e in ledger_of_policy(policy_id))


# --------------------------------------------------------------- premium fields

PREMIUM_FIELDS = (
    "property_premium_cents",
    "livestock_premium_cents",
    "liability_premium_cents",
    "endorsement_premium_cents",
    "base_premium_cents",
    "cat_load_cents",
    "total_premium_cents",
)


def zero_premiums(policy):
    for field in PREMIUM_FIELDS:
        policy[field] = 0
    policy["exposed_tiv_cents"] = 0


def rollup(policy):
    policy["base_premium_cents"] = (
        policy["property_premium_cents"]
        + policy["livestock_premium_cents"]
        + policy["liability_premium_cents"]
        + policy["endorsement_premium_cents"]
    )
    policy["total_premium_cents"] = policy["base_premium_cents"] + policy["cat_load_cents"]


def shift_endorsement_premium(policy, delta):
    policy["endorsement_premium_cents"] += delta
    rollup(policy)


# ------------------------------------------------------------ capacity release

def release_reservations(policy, statuses):
    touched_pools = []
    for reservation in reservations_of_policy(policy["id"]):
        if reservation["status"] not in statuses:
            continue
        reservation["status"] = "RELEASED"
        touch(reservation)
        pool = store.pools.get(reservation["pool_id"])
        if pool is not None and pool["id"] not in [p["id"] for p in touched_pools]:
            touched_pools.append(pool)
    for pool in touched_pools:
        recompute_pool(pool)
    return touched_pools


# ------------------------------------------------------ endorsement cascades

def suspend_inspection_endorsements(policy):
    """Compliance axis left the clean states: suspend inspection-backed forms."""
    removed = 0
    for endorsement in endorsements_of_policy(policy["id"]):
        if endorsement["status"] != "APPROVED" or not endorsement["requires_inspection"]:
            continue
        endorsement["status"] = "SUSPENDED"
        touch(endorsement)
        amount = endorsement["premium_cents"]
        if amount:
            append_txn(policy, "ENDORSEMENT_REMOVE", "COMPLIANCE_SUSPENSION", -amount)
        removed += amount
    if removed:
        shift_endorsement_premium(policy, -removed)
    return removed


def suspend_all_endorsements(policy):
    """RATED -> DRAFT: every APPROVED endorsement is suspended, premium retained."""
    for endorsement in endorsements_of_policy(policy["id"]):
        if endorsement["status"] != "APPROVED":
            continue
        endorsement["status"] = "SUSPENDED"
        touch(endorsement)


def reinstate_endorsements(policy):
    """Compliance axis returned to COMPLIANT: SUSPENDED -> APPROVED."""
    added = 0
    for endorsement in endorsements_of_policy(policy["id"]):
        if endorsement["status"] != "SUSPENDED":
            continue
        endorsement["status"] = "APPROVED"
        touch(endorsement)
        amount = endorsement["premium_cents"]
        if amount:
            append_txn(policy, "ENDORSEMENT_ADD", "COMPLIANCE_REINSTATEMENT", amount)
        added += amount
    if added:
        shift_endorsement_premium(policy, added)
    return added


def unresolved_recommendations(policy_id):
    return [
        r for r in recommendations_of_policy(policy_id)
        if r["status"] in ("OPEN", "OVERDUE", "SUBMITTED")
    ]


def move_to_compliant(policy):
    """Compliance axis -> COMPLIANT with the reinstatement mirror cascade."""
    policy["compliance_status"] = "COMPLIANT"
    reinstate_endorsements(policy)


# ------------------------------------------------------------- revert / closure

def revert_to_draft(policy, reason_code):
    """The RATED -> DRAFT (or REFERRED -> DRAFT) unwind of PRD §3.6."""
    release_reservations(policy, ("RESERVED",))
    reversal_batch(policy, reason_code)
    zero_premiums(policy)
    policy["quote_expires_at"] = None
    policy["rating_valuation_date"] = None
    suspend_all_endorsements(policy)
    policy["referred_at"] = None
    policy["referred_by_user_id"] = None
    policy["referral_reason_code"] = None
    policy["uw_status"] = "DRAFT"
    touch(policy)


def cancel_scheduled_inspections(policy):
    for inspection in inspections_of_policy(policy["id"]):
        if inspection["status"] == "SCHEDULED":
            inspection["status"] = "CANCELLED"
            touch(inspection)


def decline_policy(policy, closure_reason):
    release_reservations(policy, ("RESERVED",))
    reversal_batch(policy, "POLICY_DECLINE")
    zero_premiums(policy)
    policy["quote_expires_at"] = None
    cancel_scheduled_inspections(policy)
    policy["closure_reason"] = closure_reason
    policy["uw_status"] = "DECLINED"
    touch(policy)


def cancel_policy(policy, closure_reason):
    policy["uw_status"] = "CANCELLED"
    policy["closure_reason"] = closure_reason
    release_reservations(policy, ("COMMITTED",))
    reversal_batch(policy, "POLICY_CANCELLATION")
    zero_premiums(policy)
    for endorsement in endorsements_of_policy(policy["id"]):
        if endorsement["status"] in ("APPROVED", "SUSPENDED"):
            endorsement["status"] = "RESCINDED"
            endorsement["premium_cents"] = 0
            touch(endorsement)
    cancel_scheduled_inspections(policy)
    touch(policy)


def revert_if_rated(policy):
    """An exposure mutation invalidates a struck price."""
    if policy["uw_status"] == "RATED":
        revert_to_draft(policy, "RATING_REVERT")


# ------------------------------------------------------------------- valuation

def revalue_item(item, valuation_dt):
    item["insured_value_cents"] = calc.scheduled_item_insured_value(item, valuation_dt)
    item["valued_at"] = fmt_datetime(valuation_dt)


# ------------------------------------------------------------------ rating plan

class RatingPlan(object):
    def __init__(self):
        self.valuation_dt = None
        self.item_values = []
        self.exposed_tiv_cents = 0
        self.property_premium_cents = 0
        self.livestock_premium_cents = 0
        self.liability_premium_cents = 0
        self.endorsement_premium_cents = 0
        self.cat_load_cents = 0
        self.perils = []


def build_rating_plan(policy, account):
    """Compute the whole quote before a single row is mutated."""
    plan = RatingPlan()
    plan.valuation_dt = now_dt()

    items = active_items_of_policy(policy["id"])
    groups = livestock_of_policy(policy["id"])
    exposures = liability_of_policy(policy["id"])

    for item in items:
        plan.item_values.append((item, calc.scheduled_item_insured_value(item, plan.valuation_dt)))

    credit = calc.deductible_credit(policy["deductible_cents"])
    plan.property_premium_cents = sum(
        calc.property_line_cents(item["item_class"], value, credit)
        for item, value in plan.item_values
    )
    plan.livestock_premium_cents = sum(calc.livestock_line_cents(g, credit) for g in groups)
    plan.liability_premium_cents = sum(e["exposure_premium_cents"] for e in exposures)
    plan.endorsement_premium_cents = sum(
        e["premium_cents"] for e in endorsements_of_policy(policy["id"]) if e["status"] == "APPROVED"
    )
    plan.exposed_tiv_cents = sum(v for _, v in plan.item_values) + sum(
        g["covered_limit_cents"] for g in groups
    )

    own_reserved = {}
    for reservation in reservations_of_policy(policy["id"]):
        if reservation["status"] == "RESERVED":
            own_reserved[reservation["pool_id"]] = (
                own_reserved.get(reservation["pool_id"], 0) + reservation["amount_cents"]
            )

    for peril in calc.PERIL_ORDER:
        pool = pool_for(account["cat_zone_code"], peril)
        reserved = pool["reserved_cents"] - own_reserved.get(pool["id"], 0)
        committed = pool["committed_cents"]
        amount = calc.cat_amount_cents(plan.exposed_tiv_cents, pool["participation_pct"])
        utilization = calc.prospective_utilization(
            reserved, committed, amount, pool["total_capacity_cents"]
        )
        factor = calc.scarcity_factor(utilization)
        if factor is None:
            raise ApiError("ERR_CAT_CAPACITY_EXCEEDED")
        load = calc.cat_load_cents(amount, peril, factor)
        plan.perils.append(
            {
                "peril": peril,
                "pool": pool,
                "amount_cents": amount,
                "utilization": utilization,
                "scarcity_factor": factor,
                "load_cents": load,
            }
        )
        plan.cat_load_cents += load
    return plan


def referral_reason(policy, plan):
    if plan.exposed_tiv_cents > calc.TIV_REFERRAL_LIMIT_CENTS:
        return "TIV_ABOVE_LIMIT"
    visitor_counts = [
        e["annual_visitor_count"]
        for e in liability_of_policy(policy["id"])
        if e["exposure_type"] == "AGRITOURISM" and e["annual_visitor_count"] is not None
    ]
    if visitor_counts and max(visitor_counts) > calc.AGRITOURISM_VISITOR_LIMIT:
        return "AGRITOURISM_VISITORS"
    for entry in plan.perils:
        if entry["utilization"] is not None and entry["utilization"] > calc.CAT_UTILIZATION_LIMIT:
            return "CAT_UTILIZATION_HIGH"
    inspection = latest_completed_inspection(policy["id"])
    if inspection is not None and inspection["hazard_score"] >= calc.HAZARD_SCORE_LIMIT:
        return "HAZARD_SCORE_HIGH"
    return None


def commit_rating(policy, plan, actor_id):
    # First: release this policy's own stale holds.
    release_reservations(policy, ("RESERVED",))

    # Second: valuation at the rating instant.
    policy["rating_valuation_date"] = fmt_datetime(plan.valuation_dt)
    for item, value in plan.item_values:
        item["insured_value_cents"] = value
        item["valued_at"] = fmt_datetime(plan.valuation_dt)
        item["updated_at"] = now_str()

    # Third through eighth: the premium build-up.
    policy["property_premium_cents"] = plan.property_premium_cents
    policy["livestock_premium_cents"] = plan.livestock_premium_cents
    policy["liability_premium_cents"] = plan.liability_premium_cents
    policy["endorsement_premium_cents"] = plan.endorsement_premium_cents
    policy["exposed_tiv_cents"] = plan.exposed_tiv_cents
    policy["cat_load_cents"] = plan.cat_load_cents
    rollup(policy)

    # Seventh: the reservations themselves, peril by peril.
    for entry in plan.perils:
        reservation = new_row(
            policy_id=policy["id"],
            pool_id=entry["pool"]["id"],
            peril=entry["peril"],
            amount_cents=entry["amount_cents"],
            utilization_at_rating=calc.rhu6(entry["utilization"]),
            scarcity_factor=entry["scarcity_factor"],
            load_cents=entry["load_cents"],
            status="RESERVED",
        )
        store.reservations[reservation["id"]] = reservation
        recompute_pool(entry["pool"])

    # Ninth: the ledger.
    for txn_type, amount in (
        ("BASE_PROPERTY", plan.property_premium_cents),
        ("BASE_LIVESTOCK", plan.livestock_premium_cents),
        ("BASE_LIABILITY", plan.liability_premium_cents),
        ("CAT_LOAD", plan.cat_load_cents),
    ):
        if amount:
            append_txn(policy, txn_type, "RATING", amount)

    # Tenth: the referral test.
    reason = referral_reason(policy, plan)
    if reason is None:
        policy["uw_status"] = "RATED"
        policy["quote_expires_at"] = fmt_datetime(
            plan.valuation_dt + timedelta(days=calc.QUOTE_VALID_DAYS)
        )
        policy["referred_at"] = None
        policy["referred_by_user_id"] = None
        policy["referral_reason_code"] = None
    else:
        policy["uw_status"] = "REFERRED"
        policy["quote_expires_at"] = None
        policy["referred_at"] = now_str()
        policy["referred_by_user_id"] = actor_id
        policy["referral_reason_code"] = reason
    touch(policy)
    return policy


def commit_bind(policy, actor_id):
    touched_pools = []
    for reservation in reservations_of_policy(policy["id"]):
        if reservation["status"] != "RESERVED":
            continue
        reservation["status"] = "COMMITTED"
        touch(reservation)
        pool = store.pools.get(reservation["pool_id"])
        if pool is not None and pool["id"] not in [p["id"] for p in touched_pools]:
            touched_pools.append(pool)
    for pool in touched_pools:
        recompute_pool(pool)
    policy["bound_at"] = now_str()
    policy["bound_by_user_id"] = actor_id
    policy["uw_status"] = "BOUND"
    touch(policy)
    return policy


# ---------------------------------------------------------- inspector calendar

def window_conflict(inspector_id, start_dt, duration_minutes, exclude_id=None):
    buffer_minutes = calc.INSPECTION_TRAVEL_BUFFER_MINUTES
    requested_end = start_dt + timedelta(minutes=duration_minutes)
    requested_buffered_end = requested_end + timedelta(minutes=buffer_minutes)
    for inspection in store.inspections.values():
        if inspection["inspector_id"] != inspector_id or inspection["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and inspection["id"] == exclude_id:
            continue
        existing_start = inspection["_scheduled_for"]
        existing_buffered_end = (
            existing_start
            + timedelta(minutes=inspection["duration_minutes"])
            + timedelta(minutes=buffer_minutes)
        )
        if start_dt < existing_buffered_end and requested_buffered_end > existing_start:
            return True
    return False


def day_load(inspector_id, start_dt, exclude_id=None):
    booked = 0
    target_date = start_dt.date()
    for inspection in store.inspections.values():
        if inspection["inspector_id"] != inspector_id or inspection["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and inspection["id"] == exclude_id:
            continue
        if inspection["_scheduled_for"].date() == target_date:
            booked += inspection["duration_minutes"]
    return booked
