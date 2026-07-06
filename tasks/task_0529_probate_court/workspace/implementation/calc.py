"""Calculation rules and derived-field recomputation."""
from datetime import timedelta

from db import store, now_iso_from

# Constants
TIER1_CENTS = 1000000
TIER2_CENTS = 4000000
INDEPENDENT_MAX_CENTS = 500000
FULL_MIN_CENTS = 5000000
CLAIM_PERIOD_DAYS = 120
JUDGE_RECESS_MINUTES = 30

CLAIM_RANK = {"SECURED": 0, "FUNERAL": 1, "ADMIN": 2, "TAX": 3, "GENERAL": 4}


def supervision_level(gross):
    if gross < INDEPENDENT_MAX_CENTS:
        return "INDEPENDENT"
    elif gross < FULL_MIN_CENTS:
        return "LIMITED"
    return "FULL"


def bond_required_flag(level):
    return level in ("FULL", "LIMITED")


def bond_required_amount(gross, level):
    if level == "INDEPENDENT":
        return 0
    base = gross
    t1 = min(base, TIER1_CENTS)
    t2 = min(max(base - TIER1_CENTS, 0), TIER2_CENTS)
    t3 = max(base - TIER1_CENTS - TIER2_CENTS, 0)
    return t1 + (t2 * 50 // 100) + (t3 * 25 // 100)


def claim_bar_date(opened_at):
    return opened_at + timedelta(days=CLAIM_PERIOD_DAYS)


# ---- Estate-wide derived fields (recompute from children) ----

def estate_children(collection_name, estate_id):
    coll = store.collection(collection_name)
    return [e for e in coll.values() if e.get("estate_id") == estate_id]


def recompute_inventory_total(estate_id):
    total = 0
    for a in estate_children("assets", estate_id):
        if a["status"] in ("APPRAISED", "MARSHALED", "LIQUIDATED", "DISTRIBUTED"):
            av = a.get("appraised_value_cents")
            if av is not None:
                total += av
    return total


def recompute_allowed_claims_total(estate_id):
    total = 0
    for c in estate_children("claims", estate_id):
        if c["status"] in ("ALLOWED", "PAID"):
            av = c.get("allowed_amount_cents")
            if av is not None:
                total += av
    return total


def recompute_beneficiary_distributed(beneficiary_id, estate_id):
    total = 0
    for d in estate_children("distributions", estate_id):
        if d["status"] == "PAID" and d.get("beneficiary_id") == beneficiary_id:
            total += d.get("proposed_amount_cents", 0)
    return total


def sync_estate_derived(estate):
    """Refresh computed fields that are pure functions of children/state."""
    eid = estate["id"]
    estate["supervision_level"] = supervision_level(estate["gross_estate_value_cents"])
    estate["inventory_total_cents"] = recompute_inventory_total(eid)
    estate["allowed_claims_total_cents"] = recompute_allowed_claims_total(eid)
    # residue == marshaled_cash (the live pool)
    estate["residue_cents"] = estate["marshaled_cash_cents"]
    if estate.get("claim_period_opened_at"):
        cbd = claim_bar_date(_parse(estate["claim_period_opened_at"]))
        estate["claim_bar_date"] = now_iso_from(cbd)
    else:
        estate["claim_bar_date"] = None


def _parse(iso):
    from db import parse_iso
    return parse_iso(iso)


def accounting_balance(estate_id, marshaled_cash):
    total_cash_in = 0
    for a in estate_children("assets", estate_id):
        if a["status"] == "MARSHALED" and a["asset_class"] == "CASH":
            total_cash_in += a.get("appraised_value_cents", 0)
        if a["status"] == "LIQUIDATED":
            total_cash_in += a.get("liquidation_proceeds_cents", 0) or 0
        # A LIQUIDATED CASH asset would have been credited on MARSHAL then... but
        # once LIQUIDATED it is no longer MARSHALED, so only the liquidation branch
        # counts it. CASH assets are typically marshaled (not liquidated).
    paid_out = 0
    for c in estate_children("claims", estate_id):
        if c["status"] == "PAID":
            paid_out += c.get("paid_amount_cents", 0) or 0
    for d in estate_children("distributions", estate_id):
        if d["status"] == "PAID":
            paid_out += d.get("proposed_amount_cents", 0)
    return total_cash_in == paid_out + marshaled_cash
