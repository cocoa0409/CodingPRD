"""Producer commission (PRD 3.6) — the catastrophe surcharge is never
commissionable, and ytd_commission_cents is a conserved quantity recomputed
after every credit and every return."""

from db import db, touch
from util import D, rhu_cents


def commissionable_premium(policy):
    return policy["annual_premium_cents"] - policy["cat_surcharge_cents"]


def credit_for(policy, producer):
    rate_bps = producer["commission_rate_bps"] if producer else 0
    return rhu_cents(D(commissionable_premium(policy)) * D(rate_bps) / D(10000))


def return_for(policy, unearned_fraction):
    return rhu_cents(D(policy["commission_credited_cents"]) * D(unearned_fraction))


def recompute_ytd(producer, bump_version=True):
    if producer is None:
        return None
    total = 0
    for policy in db.policies.values():
        if policy["producer_id"] == producer["id"]:
            total += (policy["commission_credited_cents"]
                      - policy["commission_returned_cents"])
    producer["ytd_commission_cents"] = total
    if bump_version:
        touch(producer)
    return producer
