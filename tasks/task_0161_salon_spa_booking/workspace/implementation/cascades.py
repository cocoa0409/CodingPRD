"""Shared cascade side-effects (PRD §3.4-§3.6).

These are the second-order mutations that fan out of appointment/checkout
transitions. Each cascade independently refreshes the touched entity's
updated_at and bumps its version (PRD §2.4).
"""
import db
from calculations import no_show_forfeit
from util import touch


def restore_package_session(package_purchase_id):
    """Restore one prepaid session to a purchase (cancel / no-show / void).

    sessions_remaining += 1; EXHAUSTED -> ACTIVE if lifted off zero; version +1.
    """
    if not package_purchase_id:
        return
    purchase = db.package_purchases.get(package_purchase_id)
    if purchase is None:
        return
    purchase["sessions_remaining"] += 1
    if purchase["status"] == "EXHAUSTED" and purchase["sessions_remaining"] > 0:
        purchase["status"] = "ACTIVE"
    touch(purchase)


def redeem_package_session(package_purchase_id):
    """Consume one prepaid session at checkout completion.

    sessions_remaining -= 1; flips to EXHAUSTED at zero; version +1.
    """
    if not package_purchase_id:
        return
    purchase = db.package_purchases.get(package_purchase_id)
    if purchase is None:
        return
    purchase["sessions_remaining"] -= 1
    if purchase["sessions_remaining"] <= 0:
        purchase["sessions_remaining"] = max(0, purchase["sessions_remaining"])
        purchase["status"] = "EXHAUSTED"
    touch(purchase)


def apply_no_show_cascade(appointment, salon, client):
    """The full no-show deposit/strike/suspend cascade (PRD §3.4).

    Mutates `client` in place:
      * forfeit min(fee, deposit); refund remainder to wallet_credit_cents
      * no_show_strikes += 1
      * conditional auto-suspend (ACTIVE -> SUSPENDED at threshold)
    Client.version is advanced exactly once for the whole batch.
    """
    _forfeited, refund = no_show_forfeit(
        appointment["quoted_service_price_cents"],
        appointment["deposit_held_cents"],
        salon["no_show_fee_pct"],
    )
    client["wallet_credit_cents"] = client["wallet_credit_cents"] + refund
    client["no_show_strikes"] = client["no_show_strikes"] + 1
    if (
        client["no_show_strikes"] >= salon["no_show_suspend_threshold"]
        and client["status"] == "ACTIVE"
    ):
        client["status"] = "SUSPENDED"
    touch(client)  # single version bump for the entire no-show update batch
