"""Derived-ledger recomputations and cross-aggregate helpers (PRD §3.4, §3.5).

These functions mutate stored entities and bump versions as the PRD's automatic
propagation rules require (PRD §2.5).
"""
import db
from services import calculations as calc
from services.common import touch


# ---- Lookups across aggregates ---------------------------------------------
def units_of_election(election_id):
    return [u for u in db.units.values() if u["coverage_election_id"] == election_id]


def elections_of_policy(policy_id):
    return [e for e in db.coverage_elections.values() if e["policy_id"] == policy_id]


def reports_of_unit(unit_id):
    return [r for r in db.acreage_reports.values() if r["unit_id"] == unit_id]


def loss_claims_of_unit(unit_id):
    return [c for c in db.loss_claims.values() if c["unit_id"] == unit_id]


def pp_claims_of_unit(unit_id):
    return [c for c in db.prevented_planting_claims.values() if c["unit_id"] == unit_id]


def commissions_of_election(election_id):
    return [c for c in db.agent_commissions.values()
            if c["coverage_election_id"] == election_id]


def program_of_election(election):
    return db.commodity_programs.get(election["commodity_program_id"])


def election_of_unit(unit):
    return db.coverage_elections.get(unit["coverage_election_id"])


def policy_of_election(election):
    return db.policies.get(election["policy_id"])


# ---- Election premium recompute (PRD §3.4) ---------------------------------
def recompute_election_premium(election, bump=True):
    """Recompute total_premium_cents, subsidy_factor, subsidy_cents,
    producer_premium_cents for one election from its live units."""
    program = program_of_election(election)
    plan_type = election["plan_type"]
    liability = election["dollar_liability_per_acre_cents"]
    per_acre = calc.per_acre_premium_cents(
        liability, program["base_premium_rate"], plan_type)

    total = 0
    for u in units_of_election(election["id"]):
        if u["status"] in ("PENDING", "REPORTED", "ACTIVE"):
            total += calc.unit_premium_cents(per_acre, u["acres"], u["share"])

    subsidy_cents, producer_premium_cents = calc.subsidy_split(
        total, election["coverage_level"])

    changed = (
        election["total_premium_cents"] != total
        or election["subsidy_cents"] != subsidy_cents
        or election["producer_premium_cents"] != producer_premium_cents
    )
    election["total_premium_cents"] = total
    election["subsidy_cents"] = subsidy_cents
    election["producer_premium_cents"] = producer_premium_cents
    if bump and changed:
        touch(election)


# ---- Policy ledger recompute (PRD §3.4) ------------------------------------
def recompute_policy_premium(policy, bump=True):
    """Roll up live elections (ELECTED/REPORTED/INDEMNIFIED)."""
    total = 0
    producer = 0
    subsidy = 0
    for e in elections_of_policy(policy["id"]):
        if e["status"] in ("ELECTED", "REPORTED", "INDEMNIFIED"):
            total += e["total_premium_cents"]
            producer += e["producer_premium_cents"]
            subsidy += e["subsidy_cents"]
    changed = (
        policy["total_premium_cents"] != total
        or policy["producer_premium_cents"] != producer
        or policy["subsidy_cents"] != subsidy
    )
    policy["total_premium_cents"] = total
    policy["producer_premium_cents"] = producer
    policy["subsidy_cents"] = subsidy
    if bump and changed:
        touch(policy)


def recompute_policy_insured_acres(policy, bump=True):
    """total_insured_acres = sum of acres for units REPORTED or ACTIVE (PRD §3.5)."""
    total = 0
    for e in elections_of_policy(policy["id"]):
        for u in units_of_election(e["id"]):
            if u["status"] in ("REPORTED", "ACTIVE"):
                total += u["acres"]
    if policy["total_insured_acres"] != total:
        policy["total_insured_acres"] = total
        if bump:
            touch(policy)


def add_policy_indemnity(policy, amount_cents):
    policy["total_indemnity_cents"] += amount_cents
    touch(policy)
