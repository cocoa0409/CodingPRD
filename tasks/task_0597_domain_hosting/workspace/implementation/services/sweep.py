"""The expiry sweep (PRD 3.4, calculations.domain_expiry_sweep)."""

import config
import db
from services import activation, cascades, money, pricing

LADDER_STATES = ("ACTIVE", "EXPIRED", "REDEMPTION", "PENDING_DELETE")


def _auto_renew(domain, account, counts):
    """Extend by exactly one year, raise an invoice and settle it immediately."""
    domain["_expires_at"] = domain["_expires_at"] + db.years(1)
    db.touch(domain)
    invoice = money.create_invoice(
        account["id"],
        [
            {
                "item_type": "DOMAIN_RENEWAL",
                "reference_id": domain["id"],
                "description": "Automatic renewal of %s for 1 year" % domain["fqdn"],
                "quantity": 1,
                "unit_price_cents": pricing.base_year_price(
                    domain["domain_name"], domain["tld"]
                ),
            }
        ],
    )
    money.settle_invoice(invoice, account, use_credit=True)
    counts["auto_renewed_count"] += 1


def run_expiry_sweep():
    now = db.clock_now()
    counts = {
        "auto_renewed_count": 0,
        "expired_count": 0,
        "redemption_count": 0,
        "pending_delete_count": 0,
        "deleted_count": 0,
        "addon_expired_count": 0,
    }

    domains = db.ordered(db.domains, lambda d: d["lifecycle_status"] in LADDER_STATES)
    for domain in domains:
        account = db.accounts.get(domain["account_id"])
        expires_at = domain["_expires_at"]

        if (
            domain["lifecycle_status"] == "ACTIVE"
            and expires_at is not None
            and expires_at <= now
        ):
            eligible = (
                domain["auto_renew_enabled"]
                and account is not None
                and account["status"] == "ACTIVE"
                and account["payment_method_token"] is not None
            )
            if eligible:
                _auto_renew(domain, account, counts)
            else:
                domain["lifecycle_status"] = "EXPIRED"
                db.touch(domain)
                counts["expired_count"] += 1
                cascades.cascade_domain_expired(domain)

        expires_at = domain["_expires_at"]

        if domain["lifecycle_status"] == "EXPIRED" and now >= expires_at + db.days(
            config.EXPIRY_GRACE_DAYS
        ):
            domain["lifecycle_status"] = "REDEMPTION"
            db.touch(domain)
            counts["redemption_count"] += 1

        if domain["lifecycle_status"] == "REDEMPTION" and now >= expires_at + db.days(
            config.EXPIRY_GRACE_DAYS + config.REDEMPTION_DAYS
        ):
            domain["lifecycle_status"] = "PENDING_DELETE"
            domain["auto_renew_enabled"] = False
            db.touch(domain)
            counts["pending_delete_count"] += 1

        if domain["lifecycle_status"] == "PENDING_DELETE" and now >= expires_at + db.days(
            config.EXPIRY_GRACE_DAYS + config.REDEMPTION_DAYS + config.PENDING_DELETE_DAYS
        ):
            domain["lifecycle_status"] = "DELETED"
            db.touch(domain)
            counts["deleted_count"] += 1
            cascades.cascade_domain_terminal(domain)

    # Add-ons whose validity window has elapsed.
    for add_on in db.ordered(db.add_ons, lambda a: a["status"] == "ACTIVE"):
        if add_on["_ends_at"] is not None and add_on["_ends_at"] <= now:
            add_on["status"] = "EXPIRED"
            db.touch(add_on)
            counts["addon_expired_count"] += 1
            subscription = db.subscriptions.get(add_on["subscription_id"])
            if subscription is not None:
                cascades.recompute_storage(subscription)

    # Risk-score decay refresh.
    for account in db.ordered(db.accounts):
        cascades.refresh_risk_score(account)

    return counts
