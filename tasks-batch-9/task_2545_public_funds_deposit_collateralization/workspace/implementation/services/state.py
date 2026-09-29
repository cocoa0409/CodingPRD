"""Derivation chains, recomputation and cascades (PRD 2.9, 3.1-3.5).

Every derived field in the service is a function of primitives. `recompute_all`
re-derives the whole graph in the pinned propagation order -- requirement, then
assigned value, then coverage, then the owning public unit's exposure -- and is
called inside every request before the response is rendered.

Derived values are refreshed without touching `version`; version increments
happen only at the explicit mutation points the PRD names. The one state machine
that is itself derived, `DepositAccount.collateral_status`, advances only when
the caller passes apply_status=True, i.e. from the operations PRD 3.2 lists as
its recomputation triggers.
"""

import db
from constants import (
    IN_FLIGHT_SUBSTITUTION_STATUSES,
    OPEN_MARGIN_CALL_STATUSES,
    RESTRICTED_REASON_DEPOSITORY_SUSPENDED,
)
from services import calc


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------
def rows(collection):
    return db.rows(collection)


def accounts_of_depository(depository_id):
    return [a for a in rows("deposit_accounts") if a["depository_id"] == depository_id]


def accounts_of_unit(public_unit_id):
    return [a for a in rows("deposit_accounts") if a["public_unit_id"] == public_unit_id]


def agreements_of_depository(depository_id):
    return [a for a in rows("pledge_agreements") if a["depository_id"] == depository_id]


def allocations_of_agreement(agreement_id):
    return [a for a in rows("pledge_allocations") if a["pledge_agreement_id"] == agreement_id]


def allocations_of_asset(asset_id):
    return [a for a in rows("pledge_allocations") if a["collateral_asset_id"] == asset_id]


def assets_of_depository(depository_id):
    return [a for a in rows("collateral_assets") if a["depository_id"] == depository_id]


def margin_calls_of_depository(depository_id):
    return [m for m in rows("margin_calls") if m["depository_id"] == depository_id]


def forecasts_of_account(account_id):
    return [f for f in rows("runoff_forecasts") if f["deposit_account_id"] == account_id]


def substitutions_of_agreement(agreement_id):
    return [s for s in rows("substitution_requests") if s["pledge_agreement_id"] == agreement_id]


def has_inflight_substitution_for_allocation(allocation_id):
    for request in rows("substitution_requests"):
        if request["outgoing_allocation_id"] != allocation_id:
            continue
        if request["status"] in IN_FLIGHT_SUBSTITUTION_STATUSES:
            return True
    return False


def has_inflight_substitution_for_agreement(agreement_id):
    for request in substitutions_of_agreement(agreement_id):
        if request["status"] in IN_FLIGHT_SUBSTITUTION_STATUSES:
            return True
    return False


# ---------------------------------------------------------------------------
# The full recomputation chain
# ---------------------------------------------------------------------------
def recompute_all(apply_status=False, counter_override=None):
    _recompute_assets()
    _recompute_allocations()
    _recompute_agreements()
    _recompute_requirements(counter_override or {})
    _recompute_assigned_and_pools()
    _recompute_coverage(apply_status)
    _recompute_depositories()
    _recompute_units()


def _recompute_assets():
    moment = db.clock()
    pledged = {}
    for allocation in rows("pledge_allocations"):
        if allocation["status"] != "ACTIVE":
            continue
        if not calc.covers(allocation, moment):
            continue
        key = allocation["collateral_asset_id"]
        pledged[key] = pledged.get(key, 0) + allocation["allocated_par_cents"]
    for asset in rows("collateral_assets"):
        asset["haircut_bps"] = calc.haircut_for(asset["asset_type"])
        asset["market_value_cents"] = calc.market_value(
            asset["par_value_cents"], asset["market_price_bps"]
        )
        if asset["eligibility_status"] == "INELIGIBLE":
            asset["collateral_value_cents"] = 0
        else:
            asset["collateral_value_cents"] = calc.scale_bps(
                asset["market_value_cents"], 10000 - asset["haircut_bps"]
            )
        occupied = pledged.get(asset["id"], 0)
        asset["pledged_par_cents"] = occupied
        asset["available_par_cents"] = max(0, asset["par_value_cents"] - occupied)
        if occupied <= 0:
            asset["pledge_status"] = "UNPLEDGED"
        elif occupied >= asset["par_value_cents"]:
            asset["pledge_status"] = "FULLY_PLEDGED"
        else:
            asset["pledge_status"] = "PARTIALLY_PLEDGED"


def _recompute_allocations():
    for allocation in rows("pledge_allocations"):
        asset = db.get("collateral_assets", allocation["collateral_asset_id"])
        if asset is None:
            continue
        if asset["eligibility_status"] == "INELIGIBLE":
            allocation["allocated_collateral_value_cents"] = 0
        else:
            allocation["allocated_collateral_value_cents"] = calc.asset_value_of_par(
                asset, allocation["allocated_par_cents"]
            )


def _recompute_agreements():
    for agreement in rows("pledge_agreements"):
        par_total = 0
        value_total = 0
        active = 0
        for allocation in allocations_of_agreement(agreement["id"]):
            if allocation["status"] != "ACTIVE":
                continue
            active += 1
            par_total += allocation["allocated_par_cents"]
            asset = db.get("collateral_assets", allocation["collateral_asset_id"])
            if asset is not None and asset["eligibility_status"] == "ELIGIBLE":
                value_total += allocation["allocated_collateral_value_cents"]
        agreement["total_pledged_par_cents"] = par_total
        agreement["total_collateral_value_cents"] = value_total
        agreement["active_allocation_count"] = active
        agreement["signature_count"] = sum(
            1
            for field in ("depository_signed_at", "public_unit_signed_at", "custodian_signed_at")
            if agreement[field] is not None
        )


def _recompute_requirements(counter_override):
    groups = {}
    for account in rows("deposit_accounts"):
        if account["funding_status"] not in ("PENDING_FUNDING", "FUNDED", "RESTRICTED"):
            continue
        key = (account["public_unit_id"], account["depository_id"], account["deposit_class"])
        groups.setdefault(key, []).append(account)
    for key, members in groups.items():
        depository = db.get("depositories", key[1])
        members.sort(key=lambda a: (a["group_sequence"], a["created_at"].dt, a["_seq"]))
        basis = depository["insurance_determination_basis"] if depository else "AGGREGATED_BY_UNIT"
        calc.apply_insurance(members, basis)
        counter = 0
        if depository is not None:
            counter = counter_override.get(
                depository["id"], depository["consecutive_deficiency_runs"]
            )
        for account in members:
            if depository is None:
                continue
            pct = calc.required_pct_bps(depository, account["pledging_mode"], counter)
            account["required_collateral_pct_bps"] = pct
            account["required_collateral_cents"] = calc.required_collateral_cents(
                account["uninsured_amount_cents"], pct
            )


def _recompute_assigned_and_pools():
    moment = db.clock()
    # Dedicated accounts read their own executed paperwork.
    dedicated = {}
    for agreement in rows("pledge_agreements"):
        if agreement["status"] != "EXECUTED":
            continue
        if agreement["beneficiary_type"] != "DEPOSIT_ACCOUNT":
            continue
        target = agreement["deposit_account_id"]
        for allocation in allocations_of_agreement(agreement["id"]):
            if allocation["status"] != "ACTIVE":
                continue
            asset = db.get("collateral_assets", allocation["collateral_asset_id"])
            if asset is None or asset["eligibility_status"] != "ELIGIBLE":
                continue
            dedicated[target] = dedicated.get(target, 0) + allocation[
                "allocated_collateral_value_cents"
            ]
    for account in rows("deposit_accounts"):
        if account["pledging_mode"] == "DEDICATED":
            account["pooled_allocated_collateral_cents"] = 0
            account["assigned_collateral_value_cents"] = dedicated.get(account["id"], 0)
        else:
            account["pooled_allocated_collateral_cents"] = 0
            account["assigned_collateral_value_cents"] = 0

    # Pooled pots.
    pots = {}
    for agreement in rows("pledge_agreements"):
        if agreement["status"] != "EXECUTED":
            continue
        if agreement["beneficiary_type"] != "POOLED_PROGRAM":
            continue
        pool_id = agreement["pooled_program_id"]
        for allocation in allocations_of_agreement(agreement["id"]):
            if allocation["status"] != "ACTIVE":
                continue
            if not calc.covers(allocation, moment):
                continue
            asset = db.get("collateral_assets", allocation["collateral_asset_id"])
            if asset is None or asset["eligibility_status"] != "ELIGIBLE":
                continue
            pots[pool_id] = pots.get(pool_id, 0) + allocation["allocated_collateral_value_cents"]

    for pool in rows("pooled_programs"):
        pot = pots.get(pool["id"], 0)
        participants = _pool_participants(pool["id"])
        remainder = pot
        for account in participants:
            share = min(remainder, account["required_collateral_cents"])
            account["pooled_allocated_collateral_cents"] = share
            account["assigned_collateral_value_cents"] = share
            remainder -= share
        pool["aggregate_collateral_value_cents"] = pot
        pool["aggregate_required_collateral_cents"] = sum(
            a["required_collateral_cents"] for a in participants
        )
        pool["unallocated_collateral_cents"] = remainder
        pool["participant_account_count"] = len(participants)
        if pool["aggregate_collateral_value_cents"] * 10000 < (
            pool["aggregate_required_collateral_cents"] * pool["minimum_pool_pct_bps"]
        ):
            pool["pool_posture"] = "SHORTFALL"
        else:
            pool["pool_posture"] = "ADEQUATE"


ACCOUNT_DERIVED_FIELDS = (
    "insured_amount_cents",
    "uninsured_amount_cents",
    "required_collateral_pct_bps",
    "required_collateral_cents",
    "assigned_collateral_value_cents",
    "pooled_allocated_collateral_cents",
    "coverage_ratio_bps",
    "collateral_status",
)


def snapshot_accounts():
    """Freeze the stored derived fields of every account before a balance moves."""
    return dict(
        (a["id"], tuple(a[f] for f in ACCOUNT_DERIVED_FIELDS))
        for a in rows("deposit_accounts")
    )


def version_changed_accounts(before, skip_ids=()):
    """Version the collateral accounts a balance move actually rewrote (PRD 2.9).

    A deposit re-runs insured-amount determination across the whole insurance
    group and the pool waterfall across every participant, so accounts other
    than the written one can come out of the recomputation with different stored
    figures. Those entities changed and are versioned; accounts merely read
    during the recomputation come out byte-identical and are left alone.
    """
    for account in rows("deposit_accounts"):
        if account["id"] in skip_ids:
            continue
        prior = before.get(account["id"])
        if prior is None:
            continue
        if prior != tuple(account[f] for f in ACCOUNT_DERIVED_FIELDS):
            db.touch(account)


def _pool_participants(pool_id):
    members = []
    for account in rows("deposit_accounts"):
        if account["pledging_mode"] != "POOLED":
            continue
        if account["funding_status"] not in ("FUNDED", "RESTRICTED"):
            continue
        depository = db.get("depositories", account["depository_id"])
        if depository is None or depository["pooled_program_id"] != pool_id:
            continue
        members.append(account)
    members.sort(
        key=lambda a: (
            a["pool_priority_rank"],
            -a["required_collateral_cents"],
            a["created_at"].dt,
            a["_seq"],
        )
    )
    return members


def _recompute_coverage(apply_status):
    for account in rows("deposit_accounts"):
        assigned = account["assigned_collateral_value_cents"]
        required = account["required_collateral_cents"]
        ratio = calc.coverage_ratio_bps(assigned, required)
        account["coverage_ratio_bps"] = ratio
        if apply_status:
            account["collateral_status"] = calc.next_collateral_status(
                account["collateral_status"], assigned, required, ratio
            )


def _recompute_depositories():
    moment = db.clock()
    for depository in rows("depositories"):
        depository["capital_tier"] = calc.capital_tier(depository["capital_ratio_bps"])
        required_total = 0
        for account in accounts_of_depository(depository["id"]):
            if account["funding_status"] in ("FUNDED", "RESTRICTED"):
                required_total += account["required_collateral_cents"]
        depository["total_required_collateral_cents"] = required_total
        value_total = 0
        par_total = 0
        for agreement in agreements_of_depository(depository["id"]):
            if agreement["status"] != "EXECUTED":
                continue
            value_total += agreement["total_collateral_value_cents"]
            for allocation in allocations_of_agreement(agreement["id"]):
                if allocation["status"] != "ACTIVE":
                    continue
                if calc.covers(allocation, moment):
                    par_total += allocation["allocated_par_cents"]
        depository["total_pledged_collateral_value_cents"] = value_total
        depository["total_pledged_par_cents"] = par_total
        depository["open_margin_call_count"] = sum(
            1
            for call in margin_calls_of_depository(depository["id"])
            if call["status"] in OPEN_MARGIN_CALL_STATUSES
        )
        depository["collateral_posture"] = derive_posture(depository)


def derive_posture(depository):
    if depository["consecutive_deficiency_runs"] >= 3 or depository.get("_frozen_by_breach"):
        return "FROZEN"
    if depository["open_margin_call_count"] >= 1:
        return "MARGIN_DEFICIENT"
    return "COMPLIANT"


def _recompute_units():
    for unit in rows("public_units"):
        members = [
            a
            for a in accounts_of_unit(unit["id"])
            if a["funding_status"] in ("PENDING_FUNDING", "FUNDED", "RESTRICTED")
        ]
        unit["total_deposit_balance_cents"] = sum(a["ledger_balance_cents"] for a in members)
        unit["total_uninsured_cents"] = sum(a["uninsured_amount_cents"] for a in members)
        unit["exposure_status"] = calc.exposure_status(accounts_of_unit(unit["id"]))


# ---------------------------------------------------------------------------
# Value-at-custodian, used by the concentration rung (PRD 3.4)
# ---------------------------------------------------------------------------
def collateral_value_at_custodian(depository_id, custodian_id):
    total = 0
    for agreement in agreements_of_depository(depository_id):
        if agreement["status"] != "EXECUTED":
            continue
        if agreement["custodian_id"] != custodian_id:
            continue
        total += agreement["total_collateral_value_cents"]
    return total


# ---------------------------------------------------------------------------
# Par capacity (PRD 3.4) — every instant of the requested half-open interval
# ---------------------------------------------------------------------------
def par_capacity_available(asset, new_from, new_to, new_par, exclude_ids=()):
    existing = [
        a
        for a in allocations_of_asset(asset["id"])
        if a["status"] == "ACTIVE" and a["id"] not in exclude_ids
    ]
    instants = [new_from]
    for allocation in existing:
        start = allocation["effective_from"].dt
        if new_from < start < new_to:
            instants.append(start)
    for instant in instants:
        occupied = new_par
        for allocation in existing:
            if allocation["effective_from"].dt <= instant < allocation["effective_to"].dt:
                occupied += allocation["allocated_par_cents"]
        if occupied > asset["par_value_cents"]:
            return False
    return True


# ---------------------------------------------------------------------------
# Allocation release, shared by officer release and the two cascades
# ---------------------------------------------------------------------------
def release_allocation(allocation, reason):
    allocation["status"] = "RELEASED"
    allocation["released_at"] = db.now_ts()
    allocation["release_reason"] = reason
    db.touch(allocation)


# ---------------------------------------------------------------------------
# Depository suspension cascade (PRD 3.1) — four hops
# ---------------------------------------------------------------------------
def suspend_depository_cascade(depository):
    # Hop one.
    depository["approval_status"] = "SUSPENDED"
    db.touch(depository)
    # Hop two.
    restricted = []
    for account in accounts_of_depository(depository["id"]):
        if account["funding_status"] in ("PENDING_FUNDING", "FUNDED"):
            account["funding_status"] = "RESTRICTED"
            account["restricted_reason"] = RESTRICTED_REASON_DEPOSITORY_SUSPENDED
            db.touch(account)
            restricted.append(account)
    # Hop three.
    unit_ids = []
    for account in restricted:
        if account["public_unit_id"] not in unit_ids:
            unit_ids.append(account["public_unit_id"])
    escalated = []
    for unit_id in unit_ids:
        unit = db.get("public_units", unit_id)
        if unit is None:
            continue
        unit["exposure_status"] = calc.exposure_status(accounts_of_unit(unit_id))
        if unit["exposure_status"] == "ESCALATED":
            escalated.append(unit)
    # Hop four.
    for unit in escalated:
        for account in accounts_of_unit(unit["id"]):
            for forecast in forecasts_of_account(account["id"]):
                if forecast["status"] != "OPEN":
                    continue
                forecast["status"] = "STALE"
                forecast["requires_reforecast"] = True
                db.touch(forecast)
