"""Domain pricing and fqdn availability (PRD 3.2, calculations.domain_base_price)."""

import math

import config
import db


def is_premium(domain_name):
    return len(domain_name) <= config.PREMIUM_MAX_LABEL_LEN


def base_year_price(domain_name, tld):
    price = config.TLD_BASE_PRICE_CENTS[tld]
    if is_premium(domain_name):
        price *= config.PREMIUM_MULTIPLIER
    return price


def make_fqdn(domain_name, tld):
    return "%s.%s" % (domain_name, tld)


def fqdn_holder(fqdn):
    """The live Domain holding this fqdn, if any (DELETED / TRANSFERRED_OUT release it)."""
    for domain in db.ordered(db.domains):
        if (
            domain["fqdn"] == fqdn
            and domain["lifecycle_status"] not in config.FQDN_RELEASED_STATES
        ):
            return domain
    return None


def is_available(fqdn):
    return fqdn_holder(fqdn) is None


def ssl_price(plan):
    return 0 if plan["included_ssl"] else config.SSL_PRICE_CENTS


def mailbox_price(storage_mb_quota):
    gigabytes = math.ceil(storage_mb_quota / float(config.MB_PER_GB))
    return config.MAILBOX_PRICE_CENTS_PER_GB * int(gigabytes)
