"""Cascade discipline (PRD 2.10, 3.1, 3.4, 3.6, 3.7, 3.9).

Every entity a cascade touches gets its own updated_at refreshed and its own
version incremented. Cascades are conditional: an entity that is not in the
state the cascade expects is left untouched.
"""

from decimal import Decimal

import config
import db
from services import money

COMMITTED_STATUSES = ("PENDING_VALIDATION", "ACTIVE", "SUSPENDED")


# ------------------------------------------------------------ small helpers
def add_ons_of_domain(domain):
    return db.ordered(db.add_ons, lambda a: a["domain_id"] == domain["id"])


def add_ons_of_subscription(subscription):
    return db.ordered(db.add_ons, lambda a: a["subscription_id"] == subscription["id"])


def subscriptions_of_domain(domain):
    return db.ordered(
        db.subscriptions, lambda s: s["primary_domain_id"] == domain["id"]
    )


def subscriptions_of_account(account):
    return db.ordered(db.subscriptions, lambda s: s["account_id"] == account["id"])


def domains_of_account(account):
    return db.ordered(db.domains, lambda d: d["account_id"] == account["id"])


def dns_records_of_domain(domain):
    return db.ordered(db.dns_records, lambda r: r["domain_id"] == domain["id"])


def recompute_storage(subscription):
    """calculations.storage_commitment."""
    total = 0
    for add_on in db.add_ons.values():
        if (
            add_on["subscription_id"] == subscription["id"]
            and add_on["add_on_type"] == "EMAIL_MAILBOX"
            and add_on["status"] in COMMITTED_STATUSES
        ):
            total += add_on["storage_mb_quota"]
    if subscription["storage_committed_mb"] != total:
        subscription["storage_committed_mb"] = total
        db.touch(subscription)
    return total


def refresh_dns_serving(domain):
    """serving_enabled is derived from the parent domain's lifecycle_status."""
    serving = domain["lifecycle_status"] not in config.SERVING_DOWN_STATES
    for record in dns_records_of_domain(domain):
        record["serving_enabled"] = serving
        db.touch(record)


# ------------------------------------------------------------------- risk
def compute_risk_score(account):
    """calculations.account_risk_score — decaying weighted sum over UPHELD reports."""
    owned = set(d["id"] for d in db.domains.values() if d["account_id"] == account["id"])
    now = db.clock_now()
    score = Decimal("0")
    for report in db.abuse_reports.values():
        if report["status"] != "UPHELD" or report["domain_id"] not in owned:
            continue
        decided_at = report["_decided_at"]
        if decided_at is None:
            continue
        age_days = int((now - decided_at).total_seconds() // 86400)
        if age_days < 0:
            age_days = 0
        half_lives = age_days // config.DECAY_HALFLIFE_DAYS
        weight = Decimal(config.SEVERITY_WEIGHT[report["severity"]])
        score += weight * (Decimal(config.DECAY_FACTOR) ** half_lives)
    return min(100, money.round_half_up(score))


def refresh_risk_score(account):
    score = compute_risk_score(account)
    if account["risk_score"] != score:
        account["risk_score"] = score
        db.touch(account)
    return score


# -------------------------------------------------- account suspend/reinstate
def suspend_account(account):
    """Account ACTIVE -> SUSPENDED (cascade L5 of the abuse uphold)."""
    if account["status"] != "ACTIVE":
        return
    account["status"] = "SUSPENDED"
    db.touch(account)
    for subscription in subscriptions_of_account(account):
        if subscription["status"] in ("ACTIVE", "OVER_QUOTA"):
            suspend_subscription(subscription)
    for domain in domains_of_account(account):
        if domain["auto_renew_enabled"]:
            domain["auto_renew_enabled"] = False
            db.touch(domain)


def reinstate_account(account):
    """SUSPENDED -> ACTIVE. Domain suspensions are NOT lifted."""
    account["status"] = "ACTIVE"
    db.touch(account)
    for subscription in subscriptions_of_account(account):
        if subscription["status"] == "SUSPENDED":
            subscription["status"] = "ACTIVE"
            db.touch(subscription)
            for add_on in add_ons_of_subscription(subscription):
                if add_on["status"] == "SUSPENDED":
                    add_on["status"] = "ACTIVE"
                    db.touch(add_on)


# ------------------------------------------------------- subscription cascade
def suspend_subscription(subscription):
    if subscription["status"] not in ("ACTIVE", "OVER_QUOTA"):
        return
    subscription["status"] = "SUSPENDED"
    db.touch(subscription)
    for add_on in add_ons_of_subscription(subscription):
        if add_on["status"] == "ACTIVE":
            add_on["status"] = "SUSPENDED"
            db.touch(add_on)
    recompute_storage(subscription)


def cancel_subscription(subscription):
    if subscription["status"] == "CANCELLED":
        return
    subscription["status"] = "CANCELLED"
    db.touch(subscription)
    for add_on in add_ons_of_subscription(subscription):
        if add_on["status"] in COMMITTED_STATUSES:
            add_on["status"] = "CANCELLED"
            db.touch(add_on)
    recompute_storage(subscription)


# ------------------------------------------------------------ domain cascades
def cascade_domain_expired(domain):
    """PRD 3.4 outage cascade (cascade B)."""
    refresh_dns_serving(domain)
    for subscription in subscriptions_of_domain(domain):
        if subscription["status"] in ("ACTIVE", "OVER_QUOTA"):
            suspend_subscription(subscription)


def cascade_domain_suspended(domain):
    """PRD 3.9 levels 3..5 (abuse uphold)."""
    refresh_dns_serving(domain)
    touched_subscriptions = set()
    for add_on in add_ons_of_domain(domain):
        if add_on["add_on_type"] == "SSL_CERT" and add_on["status"] in (
            "PENDING_VALIDATION",
            "ACTIVE",
        ):
            add_on["status"] = "REVOKED"
            db.touch(add_on)
            touched_subscriptions.add(add_on["subscription_id"])
        elif add_on["add_on_type"] == "EMAIL_MAILBOX" and add_on["status"] == "ACTIVE":
            add_on["status"] = "SUSPENDED"
            db.touch(add_on)
            touched_subscriptions.add(add_on["subscription_id"])
    for subscription_id in touched_subscriptions:
        subscription = db.subscriptions.get(subscription_id)
        if subscription is not None:
            recompute_storage(subscription)

    account = db.accounts.get(domain["account_id"])
    if account is None:
        return
    score = refresh_risk_score(account)
    if score >= config.AUTO_SUSPEND_THRESHOLD:
        suspend_account(account)


def cascade_domain_terminal(domain):
    """DELETED or TRANSFERRED_OUT: the heaviest cascade (PRD 3.4 / 3.7)."""
    refresh_dns_serving(domain)
    touched_subscriptions = set()
    for add_on in add_ons_of_domain(domain):
        if add_on["status"] in COMMITTED_STATUSES:
            add_on["status"] = "CANCELLED"
            db.touch(add_on)
            touched_subscriptions.add(add_on["subscription_id"])
    for subscription_id in touched_subscriptions:
        subscription = db.subscriptions.get(subscription_id)
        if subscription is not None:
            recompute_storage(subscription)
    for subscription in subscriptions_of_domain(domain):
        cancel_subscription(subscription)


def reinstate_domain(domain):
    """SUSPENDED -> ACTIVE. REVOKED certificates are never revived."""
    domain["lifecycle_status"] = "ACTIVE"
    domain["suspension_reason"] = None
    db.touch(domain)
    refresh_dns_serving(domain)
    touched_subscriptions = set()
    for add_on in add_ons_of_domain(domain):
        if add_on["status"] == "SUSPENDED":
            add_on["status"] = "ACTIVE"
            db.touch(add_on)
            touched_subscriptions.add(add_on["subscription_id"])
    for subscription_id in touched_subscriptions:
        subscription = db.subscriptions.get(subscription_id)
        if subscription is not None:
            recompute_storage(subscription)


def has_abuse_hold(domain):
    if domain["suspension_reason"] == "ABUSE":
        return True
    for report in db.abuse_reports.values():
        if report["domain_id"] == domain["id"] and report["status"] in (
            "UNDER_REVIEW",
            "UPHELD",
        ):
            return True
    return False
