"""Account aggregate operations: recompute, lifecycle transitions, cascades.

All recomputations of derived account fields are mutations of the account:
they refresh updated_at and bump version (PRD §2.4, §2.5).
"""

import db
import errors
from services import calculations as calc


def recompute_account(account):
    """Recompute regional_sports_fee_cents then monthly_recurring_cents in place.

    Per PRD §3.7/§3.8 the regional sports fee is recomputed where rank may have
    changed; monthly_recurring depends on it, so it is computed second. This
    function only writes the derived figures; the caller is responsible for the
    version/updated_at bump on the account for the triggering operation.
    """
    account["regional_sports_fee_cents"] = calc.regional_sports_fee(account)
    account["monthly_recurring_cents"] = calc.monthly_recurring_charge(account)


def recompute_recurring_only(account):
    """Recompute only monthly_recurring_cents (rsf unchanged)."""
    account["monthly_recurring_cents"] = calc.monthly_recurring_charge(account)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------
def suspend(account):
    if account["lifecycle_status"] != "ACTIVE":
        raise errors.invalid_state("Account must be ACTIVE to suspend")
    account["lifecycle_status"] = "SUSPENDED"
    recompute_recurring_only(account)  # -> 0 because SUSPENDED short-circuits
    db.touch(account)
    return account


def reactivate(account):
    if account["lifecycle_status"] != "SUSPENDED":
        raise errors.invalid_state("Account must be SUSPENDED to reactivate")
    account["lifecycle_status"] = "ACTIVE"
    recompute_recurring_only(account)
    db.touch(account)
    return account


def cancel(account):
    """Cancel cascade (PRD §3.3). Permitted from ACTIVE or SUSPENDED."""
    if account["lifecycle_status"] not in ("ACTIVE", "SUSPENDED"):
        raise errors.invalid_state("Account must be ACTIVE or SUSPENDED to cancel")

    account_id = account["id"]
    # Snapshot tenure at cancellation.
    account["cancellation_effective_cycle"] = account["tenure_months"]
    account["etf_tenure_at_cancel"] = account["tenure_months"]

    # Terminate the current ACTIVE/DOWNGRADED subscription.
    sub = calc.current_subscription(account_id)
    if sub is not None:
        sub["status"] = "TERMINATED"
        db.touch(sub)

    # Drop every ACTIVE add-on -> DROPPED (CANCELLED).
    for addon in db.add_on_subscriptions.values():
        if addon["account_id"] == account_id and addon["status"] == "ACTIVE":
            addon["status"] = "DROPPED"
            addon["drop_reason"] = "CANCELLED"
            db.touch(addon)

    # Strand every still-ASSIGNED lease -> UNRETURNED with replacement charge.
    for lease in db.equipment_leases.values():
        if lease["account_id"] == account_id and lease["status"] == "ASSIGNED":
            model = db.equipment_models.get(lease["equipment_model_id"])
            replacement = model["replacement_cost_cents"] if model else 0
            lease["status"] = "UNRETURNED"
            lease["unreturned_charge_cents"] = replacement * lease["quantity"]
            db.touch(lease)

    # Lifecycle -> CANCELLED; recurring -> 0 (no live recurring line items).
    account["lifecycle_status"] = "CANCELLED"
    recompute_recurring_only(account)  # CANCELLED short-circuits to 0
    db.touch(account)
    return account


def advance_cycle(account):
    """Advance one billing cycle (PRD §3.10): tenure += 1, fire time-based rollback."""
    account["tenure_months"] += 1
    pa = calc.active_promotion_application(account["id"])
    if pa is not None and account["tenure_months"] >= pa["rollback_at_tenure"]:
        pa["status"] = "ROLLED_BACK"
        pa["discount_cents_snapshot"] = 0
        db.touch(pa)
        account["promo_status"] = "ROLLED_BACK"
        recompute_recurring_only(account)
    db.touch(account)
    return account
