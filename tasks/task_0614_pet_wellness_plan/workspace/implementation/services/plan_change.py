"""Plan-change with proration and OCC (PRD §2.8, §3.6)."""
from db import db, clock_now, parse_iso
from common import touch, stamp_new, public
from errors import (
    err, ERR_REFERENCE_NOT_FOUND, ERR_STALE_MEMBERSHIP_VERSION,
    ERR_INVALID_PLAN_CHANGE, ERR_PLAN_RETIRED,
)
from services.calculations import compute_plan_change_proration


def _current_active_cycle(membership):
    """The membership's most recent BillingCycle (the current cycle window)."""
    cycles = [b for b in db.billing_cycles.values()
              if b["membership_id"] == membership["id"]]
    if not cycles:
        return None
    cycles.sort(key=lambda b: (b["created_at"], b["_seq"]))
    return cycles[-1]


def apply_plan_change(membership, to_plan_id, expected_version):
    """Apply a plan change. Validation order per PRD §2.9:
      - body FK existence (to_plan_id)          -> ERR_REFERENCE_NOT_FOUND
      - OCC version check                        -> ERR_STALE_MEMBERSHIP_VERSION
      - business: target != current & ACTIVE     -> ERR_INVALID_PLAN_CHANGE
        (a retired target specifically           -> ERR_PLAN_RETIRED)
    """
    # Body FK existence.
    to_plan = db.plans.get(to_plan_id)
    if to_plan is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "Referenced plan does not exist")

    # OCC (priority 7, before business constraints per §2.9).
    if expected_version != membership["version"]:
        raise err(ERR_STALE_MEMBERSHIP_VERSION,
                  "expected_membership_version is stale")

    from_plan_id = membership["plan_id"]
    from_plan = db.plans.get(from_plan_id)

    # Business constraints (priority 11).
    if to_plan_id == from_plan_id:
        raise err(ERR_INVALID_PLAN_CHANGE, "Target plan equals current plan")
    if to_plan["status"] != "ACTIVE":
        # A retired target specifically -> ERR_PLAN_RETIRED (PRD §3.6).
        if to_plan["status"] == "RETIRED":
            raise err(ERR_PLAN_RETIRED, "Target plan is RETIRED")
        raise err(ERR_INVALID_PLAN_CHANGE, "Target plan is not ACTIVE")

    from_fee = from_plan["monthly_fee_cents"]
    to_fee = to_plan["monthly_fee_cents"]

    # Proration over the current billing cycle window.
    cycle = _current_active_cycle(membership)
    if cycle is not None:
        period_start = parse_iso(cycle["period_start"])
        period_end = parse_iso(cycle["period_end"])
        delta = compute_plan_change_proration(
            from_fee, to_fee, period_start, period_end, clock_now())
    else:
        delta = 0

    change_kind = "UPGRADE" if to_fee > from_fee else "DOWNGRADE"

    # Supersede any prior APPLIED plan-change request on this membership.
    for pcr in db.plan_change_requests.values():
        if pcr["membership_id"] == membership["id"] and pcr["status"] == "APPLIED":
            pcr["status"] = "SUPERSEDED"
            touch(pcr)

    request_rec = {
        "membership_id": membership["id"],
        "from_plan_id": from_plan_id,
        "to_plan_id": to_plan_id,
        "change_kind": change_kind,
        "proration_delta_cents": delta,
        "status": "APPLIED",
    }
    stamp_new(request_rec)
    db.plan_change_requests[request_rec["id"]] = request_rec

    # Apply proration delta to wallet (PRD §3.6): a positive delta (upgrade) is
    # an additional charge that debits the wallet now; a negative delta
    # (downgrade) is a credit that adds its absolute value to the wallet now.
    account = db.member_accounts[membership["member_account_id"]]
    if delta > 0:
        account["wallet_credit_cents"] -= delta
    elif delta < 0:
        account["wallet_credit_cents"] += (-delta)
    touch(account)

    # Update membership plan_id + monthly_fee snapshot; bump version.
    membership["plan_id"] = to_plan_id
    membership["monthly_fee_cents"] = to_fee
    touch(membership)

    return request_rec
