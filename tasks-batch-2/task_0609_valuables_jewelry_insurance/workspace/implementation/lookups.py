"""Existence lookups (ERR_NOT_FOUND) and OCC checks (ERR_STALE_VERSION)."""
import db
from errors import err


def get_policyholder(pid):
    r = db.policyholders.get(pid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Policyholder not found")
    return r


def get_risk_zone(zid):
    r = db.risk_zones.get(zid)
    if r is None:
        raise err("ERR_NOT_FOUND", "RiskZone not found")
    return r


def get_repair_shop(sid):
    r = db.repair_shops.get(sid)
    if r is None:
        raise err("ERR_NOT_FOUND", "RepairShop not found")
    return r


def get_policy(pid):
    r = db.policies.get(pid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Policy not found")
    return r


def get_scheduled_item(iid):
    r = db.scheduled_items.get(iid)
    if r is None:
        raise err("ERR_NOT_FOUND", "ScheduledItem not found")
    return r


def get_appraisal(aid):
    r = db.appraisals.get(aid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Appraisal not found")
    return r


def get_endorsement(eid):
    r = db.endorsements.get(eid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Endorsement not found")
    return r


def get_claim(cid):
    r = db.claims.get(cid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Claim not found")
    return r


def get_repair_order(rid):
    r = db.repair_orders.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "RepairOrder not found")
    return r


def get_premium_payment(pid):
    r = db.premium_payments.get(pid)
    if r is None:
        raise err("ERR_NOT_FOUND", "PremiumPayment not found")
    return r


def repair_order_for_claim(claim_id):
    """Return the RepairOrder under a claim (or None). One per claim."""
    for ro in db.repair_orders.values():
        if ro["claim_id"] == claim_id:
            return ro
    return None


def check_version(expected, actual):
    """OCC: compare expected (request, may be string) against live version."""
    try:
        exp = int(expected)
    except (TypeError, ValueError):
        raise err("ERR_STALE_VERSION", "expected version does not match")
    if exp != int(actual):
        raise err("ERR_STALE_VERSION", "version mismatch: expected %s, actual %s" % (exp, actual))
