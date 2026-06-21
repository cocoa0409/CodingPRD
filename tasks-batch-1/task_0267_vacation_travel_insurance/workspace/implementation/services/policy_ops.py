"""Policy domain operations: premium recompute, issuance, cancellations,
expiration, ledger recompute, and the refund cascade."""
import errors
from db import db
from services import calc, common
from services.store_helpers import (
    touch,
    covered_insured_for_policy,
    all_insured_for_policy,
    completed_refunds_for_policy,
    make_record,
)


# --------------------------------------------------------------------------
# Premium recompute (QUOTED policies only)
# --------------------------------------------------------------------------
def recompute_premium(policy):
    plan = db.plans[policy["plan_id"]]
    covered = covered_insured_for_policy(policy["id"])
    base, premium = calc.premium_quote(
        policy["trip_cost_cents"], plan, covered, policy["cfar_opted"]
    )
    policy["base_premium_cents"] = base
    policy["premium_cents"] = premium


# --------------------------------------------------------------------------
# Coverage-overlap guard (PRD §3.7)
# --------------------------------------------------------------------------
def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test. Touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end


def enforce_coverage_overlap(policy, traveler_id):
    """For the given underlying traveler, reject if this policy's half-open
    [trip_start_at, trip_end_at) interval overlaps any OTHER policy on which the
    same traveler is COVERED."""
    this_start = common.to_dt(policy["trip_start_at"])
    this_end = common.to_dt(policy["trip_end_at"])
    for it in db.insured_travelers.values():
        if it["traveler_id"] != traveler_id:
            continue
        if it["status"] != "COVERED":
            continue
        if it["policy_id"] == policy["id"]:
            continue
        other = db.policies.get(it["policy_id"])
        if other is None:
            continue
        o_start = common.to_dt(other["trip_start_at"])
        o_end = common.to_dt(other["trip_end_at"])
        if _intervals_overlap(this_start, this_end, o_start, o_end):
            raise errors.conflict(
                errors.ERR_COVERAGE_OVERLAP,
                "Trip-coverage interval overlaps another policy for the same traveler.",
            )


# --------------------------------------------------------------------------
# Ledger recompute helpers
# --------------------------------------------------------------------------
def recompute_remaining(policy):
    policy["remaining_aggregate_cents"] = (
        policy["aggregate_limit_cents"] - policy["amount_reimbursed_cents"]
    )


def recompute_net_premium(policy):
    """net = premium (when PAID) - sum(COMPLETED refunds); 0 while PENDING."""
    if policy["payment_status"] == "PENDING":
        policy["net_premium_collected_cents"] = 0
        return
    refunded = sum(r["amount_cents"] for r in completed_refunds_for_policy(policy["id"]))
    policy["net_premium_collected_cents"] = policy["premium_cents"] - refunded


# --------------------------------------------------------------------------
# Issuance (PRD §3.3)
# --------------------------------------------------------------------------
def issue_policy(policy):
    if policy["coverage_status"] != "QUOTED":
        raise errors.invalid_state("Policy is not QUOTED.")
    if policy["payment_status"] != "PAID":
        raise errors.conflict(errors.ERR_PREMIUM_NOT_PAID, "Premium has not been paid.")

    covered = covered_insured_for_policy(policy["id"])
    if len(covered) == 0:
        raise errors.conflict(errors.ERR_NO_INSURED_TRAVELER, "No COVERED insured traveler on the policy.")

    covered_sum = sum(it["covered_trip_cost_cents"] for it in covered)
    if covered_sum != policy["trip_cost_cents"]:
        raise errors.conflict(
            errors.ERR_TRIP_COST_MISMATCH,
            "Sum of covered_trip_cost_cents does not equal trip_cost_cents.",
        )

    # Re-check coverage overlap for each covered insured at issuance.
    for it in covered:
        enforce_coverage_overlap(policy, it["traveler_id"])

    plan = db.plans[policy["plan_id"]]
    clock = common.current_clock()

    policy["issued_at"] = common.iso_from_dt(clock)
    policy["_issued_at_dt"] = clock
    free_look_end = common.add_days(clock, plan["free_look_days"])
    policy["free_look_ends_at"] = common.iso_from_dt(free_look_end)
    policy["_free_look_ends_at_dt"] = free_look_end

    policy["aggregate_limit_cents"] = calc.aggregate_limit_pin(policy["trip_cost_cents"], plan)
    policy["amount_reimbursed_cents"] = 0
    recompute_remaining(policy)

    full_cost_insured = covered_sum == policy["trip_cost_cents"]
    policy["preexisting_waiver_granted"] = calc.preexisting_waiver_granted(
        clock, common.to_dt(policy["initial_deposit_at"]), plan, full_cost_insured
    )

    policy["coverage_status"] = "ACTIVE"
    touch(policy)


# --------------------------------------------------------------------------
# Claim-blocking helper for cancellations (PRD §3.5)
# --------------------------------------------------------------------------
_BLOCKING_CLAIM_STATES = {"SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "PAID"}


def _policy_has_blocking_claims(policy_id):
    for c in db.claims.values():
        if c["policy_id"] == policy_id and c["status"] in _BLOCKING_CLAIM_STATES:
            return True
    return False


# --------------------------------------------------------------------------
# Free-look cancellation (PRD §3.5)
# --------------------------------------------------------------------------
def free_look_cancel(policy):
    if policy["coverage_status"] != "ACTIVE":
        raise errors.invalid_state("Policy is not ACTIVE.")
    clock = common.current_clock()
    if clock > policy["_free_look_ends_at_dt"]:
        raise errors.conflict(errors.ERR_FREE_LOOK_EXPIRED, "Free-look window has expired.")
    if _policy_has_blocking_claims(policy["id"]):
        raise errors.conflict(errors.ERR_POLICY_HAS_CLAIMS, "Policy has open or paid claims.")

    policy["coverage_status"] = "CANCELLED"

    # CASCADE L1->L2: auto-create COMPLETED FREE_LOOK refund for full premium.
    refund = make_record()
    refund.update({
        "policy_id": policy["id"],
        "refund_type": "FREE_LOOK",
        "amount_cents": calc.refund_free_look(policy["premium_cents"]),
        "status": "COMPLETED",
    })
    db.refunds[refund["id"]] = refund

    # CASCADE L2->L3: completed refund -> payment_status REFUNDED, recompute net.
    policy["payment_status"] = "REFUNDED"
    recompute_net_premium(policy)

    # All insured travelers -> REMOVED (each is its own resource: touch it).
    for it in all_insured_for_policy(policy["id"]):
        if it["status"] != "REMOVED":
            it["status"] = "REMOVED"
            touch(it)

    touch(policy)


# --------------------------------------------------------------------------
# Post-free-look cancellation (PRD §3.5)
# --------------------------------------------------------------------------
def post_free_look_cancel(policy):
    if policy["coverage_status"] != "ACTIVE":
        raise errors.invalid_state("Policy is not ACTIVE.")
    clock = common.current_clock()
    if clock <= policy["_free_look_ends_at_dt"]:
        # Inside the free-look window: free-look-cancel is the correct op.
        raise errors.invalid_state("Use free-look-cancel inside the free-look window.")
    if clock >= policy["_trip_start_at_dt"]:
        raise errors.conflict(errors.ERR_COVERAGE_PERIOD_STARTED, "Coverage period has started.")
    if _policy_has_blocking_claims(policy["id"]):
        raise errors.conflict(errors.ERR_POLICY_HAS_CLAIMS, "Policy has open or paid claims.")

    policy["coverage_status"] = "CANCELLED"

    amount = calc.refund_short_rate(
        policy["premium_cents"],
        policy["_issued_at_dt"],
        policy["_trip_end_at_dt"],
        clock,
    )
    refund = make_record()
    refund.update({
        "policy_id": policy["id"],
        "refund_type": "SHORT_RATE",
        "amount_cents": amount,
        "status": "PENDING",
    })
    db.refunds[refund["id"]] = refund

    touch(policy)


# --------------------------------------------------------------------------
# Expiration on clock advance (PRD §3.1)
# --------------------------------------------------------------------------
def expire_policies_if_due():
    clock = common.current_clock()
    for policy in db.policies.values():
        if policy["coverage_status"] == "ACTIVE":
            trip_end = policy.get("_trip_end_at_dt")
            if trip_end is not None and clock >= trip_end:
                policy["coverage_status"] = "EXPIRED"
                touch(policy)
