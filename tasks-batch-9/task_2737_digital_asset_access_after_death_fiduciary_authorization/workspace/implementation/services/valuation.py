"""Appraisal, estate roll-up and beneficiary allocation
(PRD sections 3.4, 3.8 / calculations 4-6).
"""
from clock import CLOCK
from db import DB, bump, sorted_records, stamp_new
from money import round_half_up
from services import estate as estate_svc
from services import lookup

ALTERNATE_VALUATION_MONTHS = 6

DECAY_BP_PER_MONTH = {
    "FINANCIAL_ACCOUNT": 0,
    "EMAIL": 0,
    "SUBSCRIPTION": 0,
    "CLOUD_STORAGE": 50,
    "LOYALTY_PROGRAM": 150,
    "SOCIAL_PROFILE": 200,
}

TIER_1_UPPER_EXCLUSIVE_CENTS = 500000
TIER_2_UPPER_EXCLUSIVE_CENTS = 5000000
TOTAL_SHARE_BP = 10000


def is_included(asset):
    return (asset["transferability"] == "TRANSFERABLE"
            and asset["access_status"] in estate_svc.DISCLOSED_STATUSES)


def appraise(asset, platform, basis):
    """Calculation 4 -- asset_appraised_value."""
    quoted = asset["quoted_value_cents"]
    if basis == "DATE_OF_DEATH":
        gross = quoted
    else:
        decay_bp = DECAY_BP_PER_MONTH.get(asset["category"], 0) * ALTERNATE_VALUATION_MONTHS
        gross = round_half_up(quoted * (10000 - decay_bp), 10000)
    fee = platform["transfer_fee_cents"] if platform else 0
    return max(0, gross - fee)


def deduction_cap(gross_value_cents):
    if gross_value_cents < TIER_1_UPPER_EXCLUSIVE_CENTS:
        return 25000
    if gross_value_cents < TIER_2_UPPER_EXCLUSIVE_CENTS:
        return 150000
    return 400000


def claimed_costs(estate_id):
    total = 0
    for req in lookup.estate_requests(estate_id):
        if req["status"] == "APPROVED":
            platform = DB.platforms.get(req["platform_id"])
            if platform:
                total += platform["request_fee_cents"]
    for claim in lookup.estate_claims(estate_id):
        total += claim["pursuit_cost_cents"]
    return total


def execute_run(estate, basis):
    """Appraise, roll up, mirror onto the estate and plan the allocations."""
    eid = estate["id"]

    # ---- supersede every open COMPUTED run -------------------------------
    for run in sorted_records(lookup.estate_runs(eid)):
        if run["status"] == "COMPUTED":
            run["status"] = "SUPERSEDED"
            bump(run)

    run = {
        "estate_id": eid,
        "basis": basis,
        "status": "COMPUTED",
        "included_asset_count": 0,
        "gross_value_cents": 0,
        "deduction_cap_cents": 0,
        "admin_deduction_cents": 0,
        "taxable_value_cents": 0,
        "allocation_remainder_cents": 0,
        "finalized_at": None,
        "finalization_note": None,
    }
    stamp_new(run)
    DB.runs[run["id"]] = run

    # ---- calculation 4 per included asset --------------------------------
    gross = 0
    included = 0
    for asset in sorted_records(lookup.estate_assets(eid)):
        if not is_included(asset):
            continue
        platform = DB.platforms.get(asset["platform_id"])
        net = appraise(asset, platform, basis)
        asset["appraised_value_cents"] = net
        asset["appraised_basis"] = basis
        bump(asset)
        gross += net
        included += 1

    # ---- calculation 5 roll-up -------------------------------------------
    cap = deduction_cap(gross)
    costs = claimed_costs(eid)
    admin = min(cap, costs)
    taxable = max(0, gross - admin)

    run["included_asset_count"] = included
    run["gross_value_cents"] = gross
    run["deduction_cap_cents"] = cap
    run["admin_deduction_cents"] = admin
    run["taxable_value_cents"] = taxable

    designations = sorted_records(lookup.estate_designations(eid))
    received_total = sum(d["received_value_cents"] for d in designations)

    estate["gross_digital_estate_cents"] = gross
    estate["admin_deduction_cents"] = admin
    estate["taxable_digital_estate_cents"] = taxable
    estate["undistributed_value_cents"] = gross - received_total
    bump(estate)

    # ---- calculation 6 allocation plan -----------------------------------
    pool = gross
    allocated = 0
    for d in designations:
        planned = (pool * d["share_bp"]) // TOTAL_SHARE_BP
        d["planned_allocation_cents"] = planned
        allocated += planned
    run["allocation_remainder_cents"] = pool - allocated

    remainder = pool - allocated
    for d in sorted(designations, key=lambda x: x["allocation_rank"]):
        if remainder <= 0:
            break
        d["planned_allocation_cents"] += 1
        remainder -= 1
    for d in designations:
        bump(d)

    estate_svc.recompute(estate)
    return run


def finalize_run(run, estate, finalization_note=None):
    # PRD 3.8: finalization "advances it to the terminal FINALIZED, stamps
    # finalized_at and stores an optional finalization_note".
    run["status"] = "FINALIZED"
    run["finalized_at"] = CLOCK.iso()
    run["finalization_note"] = finalization_note
    bump(run)
    estate_svc.recompute(estate)
    return run
