"""What a paid invoice activates (PRD 3.8)."""

import config
import db
from services import money


def open_billing_period(subscription, start, end):
    period = db.base_record()
    period.update(
        {
            "subscription_id": subscription["id"],
            "_period_start": start,
            "_period_end": end,
            "status": "OPEN",
            "provisional_overage_cents": 0,
            "final_overage_cents": None,
        }
    )
    db.billing_periods[period["id"]] = period
    return period


def activate_domain(domain):
    now = db.clock_now()
    domain["lifecycle_status"] = "ACTIVE"
    domain["_registered_at"] = now
    domain["_expires_at"] = now + db.years(domain["term_years"])
    domain["epp_auth_code"] = db.mint_code(16)
    db.touch(domain)
    return domain


def activate_subscription(subscription):
    now = db.clock_now()
    subscription["status"] = "ACTIVE"
    db.touch(subscription)
    open_billing_period(subscription, now, now + db.days(config.BILLING_PERIOD_DAYS))
    return subscription


def activate_billed_subjects(invoice):
    for line in money.lines_of(invoice):
        if line["item_type"] == "DOMAIN_REGISTRATION":
            domain = db.domains.get(line["reference_id"])
            if domain is not None and domain["lifecycle_status"] == "PENDING_PAYMENT":
                activate_domain(domain)
        elif line["item_type"] == "HOSTING_PLAN":
            subscription = db.subscriptions.get(line["reference_id"])
            if subscription is not None and subscription["status"] == "PROVISIONING":
                activate_subscription(subscription)
