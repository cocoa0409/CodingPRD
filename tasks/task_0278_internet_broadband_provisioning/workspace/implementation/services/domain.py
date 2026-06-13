"""Domain cascade logic: activation, disconnect, transfer, billing close/finalize.

These are the multi-entity side-effect chains. Each touched entity records its
own mutation (updated_at refreshed + version bumped) per PRD §2.7.
"""
import db
from clock import get_clock
from db import touch
from timeutil import parse_iso, format_iso
from services import calculations as calc


CANONICAL_CYCLE_MINUTES = 43200  # 30 days (PRD §2.8); informational.


# ---------------------------------------------------------------------------
# AccountCredit emission and balance recompute
# ---------------------------------------------------------------------------

def emit_credit(account_id, source_type, source_id, amount_cents):
    """Create an AccountCredit (lean entity: id + created_at only)."""
    rec = db.make_record({
        "account_id": account_id,
        "source_type": source_type,
        "source_id": source_id,
        "amount_cents": amount_cents,
        "applied": False,
    }, versioned=db.LEAN)
    db.account_credits[rec["id"]] = rec
    recompute_credit_balance(account_id)
    return rec


def recompute_credit_balance(account_id):
    """Account.credit_balance_cents = sum of un-applied credits (§3.11)."""
    acct = db.accounts.get(account_id)
    if acct is None:
        return
    total = sum(c["amount_cents"] for c in db.account_credits.values()
                if c["account_id"] == account_id and not c["applied"])
    acct["credit_balance_cents"] = total


# ---------------------------------------------------------------------------
# Billing cycle lookups
# ---------------------------------------------------------------------------

def open_cycle_for_account(account_id):
    """Return the account's OPEN billing cycle, or None."""
    candidates = [c for c in db.billing_cycles.values()
                  if c["account_id"] == account_id and c["billing_state"] == "OPEN"]
    if not candidates:
        return None
    # Most-recently created open cycle.
    candidates.sort(key=lambda c: (c["created_at"], c["id"]))
    return candidates[-1]


def frozen_usage_gb(cycle):
    """Sum of UsageRecord.gb whose posted_at_iso is within the cycle window."""
    start = parse_iso(cycle["cycle_start_iso"])
    end = parse_iso(cycle["cycle_end_iso"])
    total = 0
    for u in db.usage_records.values():
        if u["billing_cycle_id"] != cycle["id"]:
            continue
        posted = parse_iso(u["posted_at_iso"])
        if posted is None:
            continue
        if start <= posted < end:
            total += u["gb"]
    return total


# ---------------------------------------------------------------------------
# Equipment lease proration on return (cascaded from disconnect/transfer)
# ---------------------------------------------------------------------------

def cascade_equipment_to_return_pending(account, cycle, now):
    """LEASED -> RETURN_PENDING, emitting the LEASE_PRORATE credit (§3.7).

    Returns (unit_or_None, lease_proration_credit_cents).
    """
    unit_id = account.get("equipment_unit_id")
    if not unit_id:
        return None, 0
    unit = db.equipment_units.get(unit_id)
    if unit is None or unit["status"] != "LEASED":
        return None, 0

    cycle_days = calc.whole_days_in_window(
        parse_iso(cycle["cycle_start_iso"]), parse_iso(cycle["cycle_end_iso"]))
    days_used = calc.whole_days_used(parse_iso(cycle["cycle_start_iso"]), now)
    days_remaining = max(0, cycle_days - days_used)
    refund = calc.lease_proration_credit_cents(
        unit["lease_fee_cents_per_cycle"], days_remaining, cycle_days)

    unit["status"] = "RETURN_PENDING"
    touch(unit)
    credit = emit_credit(account["id"], "LEASE_PRORATE", unit["id"], refund)
    return unit, refund


# ---------------------------------------------------------------------------
# Billing close / finalize
# ---------------------------------------------------------------------------

def close_cycle(cycle):
    """OPEN -> CLOSED (PRD §3.10).

    Freeze usage_gb, run FINAL overage, set throttle_state per cap crossing.
    """
    acct = db.accounts.get(cycle["account_id"])
    plan = db.service_plans.get(acct["plan_id"]) if acct else None

    usage = frozen_usage_gb(cycle)
    cycle["usage_gb"] = usage

    if plan is not None:
        cycle["overage_charge_cents"] = calc.overage_charge_cents(usage, plan)
        # set throttle_state according to whether the data cap was crossed.
        if usage > plan["included_gb"]:
            cycle["throttle_state"] = "THROTTLED"
        # crossing not reached -> leave throttle_state as-is (PRD §2.6: close
        # does not by itself clear throttle).
    cycle["billing_state"] = "CLOSED"
    touch(cycle)


def finalize_cycle(cycle):
    """CLOSED -> FINALIZED, computing total_due_cents (PRD §3.10)."""
    acct = db.accounts.get(cycle["account_id"])
    plan = db.service_plans.get(acct["plan_id"]) if acct else None

    plan_fee = plan["monthly_fee_cents"] if plan else 0

    # Lease fee: lease_fee_cents_per_cycle of the currently-leased unit, or zero.
    # On a disconnect/transfer cycle, the lease fee is the days-used charge =
    # full cycle lease fee reduced by the lease-proration credit.
    lease_fee = 0
    disconnect_meta = cycle.get("_disconnect_meta")
    if disconnect_meta is not None:
        full_lease = disconnect_meta.get("full_lease_cents", 0)
        prorate = disconnect_meta.get("lease_proration_cents", 0)
        lease_fee = full_lease - prorate
    else:
        unit_id = acct.get("equipment_unit_id") if acct else None
        if unit_id:
            unit = db.equipment_units.get(unit_id)
            if unit is not None:
                lease_fee = unit["lease_fee_cents_per_cycle"]

    overage = cycle.get("overage_charge_cents", 0)

    etf = 0
    if disconnect_meta is not None:
        etf = disconnect_meta.get("etf_cents", 0)

    subtotal_pre = plan_fee + lease_fee
    promo = calc.promo_discount_cents(subtotal_pre)

    applied_credits = sum(c["amount_cents"] for c in db.account_credits.values()
                          if c["account_id"] == cycle["account_id"]
                          and not c["applied"])

    total = plan_fee + lease_fee + overage + etf - applied_credits - promo
    cycle["total_due_cents"] = total
    cycle["billing_state"] = "FINALIZED"
    touch(cycle)

    # Mark consumed credits applied = true.
    for c in db.account_credits.values():
        if c["account_id"] == cycle["account_id"] and not c["applied"]:
            c["applied"] = True
    recompute_credit_balance(cycle["account_id"])


# ---------------------------------------------------------------------------
# Disconnect cascade (PRD §3.8)
# ---------------------------------------------------------------------------

def disconnect_account(account):
    now = get_clock().now()
    plan = db.service_plans.get(account["plan_id"])
    cycle = open_cycle_for_account(account["id"])

    # Account -> DISCONNECTED, service_state OFFLINE.
    account["status"] = "DISCONNECTED"
    account["service_state"] = "OFFLINE"

    # 1. Compute the ETF on the currently-provisioned plan.
    etf_cents = 0
    if plan is not None and account.get("contract_start_iso"):
        months_elapsed = calc.whole_months_between(
            parse_iso(account["contract_start_iso"]), now)
        etf_cents = calc.early_termination_fee_cents(plan, months_elapsed)

    # Capture full lease fee before the unit transitions, for the days-used charge.
    full_lease_cents = 0
    unit_id = account.get("equipment_unit_id")
    if unit_id:
        unit = db.equipment_units.get(unit_id)
        if unit is not None and unit["status"] == "LEASED":
            full_lease_cents = unit["lease_fee_cents_per_cycle"]

    # 2. Cascade equipment LEASED -> RETURN_PENDING (emits lease-prorate credit).
    lease_proration_cents = 0
    if cycle is not None:
        _unit, lease_proration_cents = cascade_equipment_to_return_pending(
            account, cycle, now)

    # 3. Close then finalize the open cycle (charge ETF on it).
    if cycle is not None:
        cycle["_disconnect_meta"] = {
            "etf_cents": etf_cents,
            "full_lease_cents": full_lease_cents,
            "lease_proration_cents": lease_proration_cents,
        }
        close_cycle(cycle)
        finalize_cycle(cycle)

    # 4. version bump handled by caller via touch(account).


# ---------------------------------------------------------------------------
# Transfer completion cascade (PRD §3.9)
# ---------------------------------------------------------------------------

def complete_transfer_cascade(account, transfer):
    now = get_clock().now()
    plan = db.service_plans.get(account["plan_id"])
    cycle = open_cycle_for_account(account["id"])

    account["status"] = "TRANSFERRED"
    account["service_state"] = "OFFLINE"

    # ETF that would otherwise apply.
    etf_cents = 0
    if plan is not None and account.get("contract_start_iso"):
        months_elapsed = calc.whole_months_between(
            parse_iso(account["contract_start_iso"]), now)
        etf_cents = calc.early_termination_fee_cents(plan, months_elapsed)

    full_lease_cents = 0
    unit_id = account.get("equipment_unit_id")
    if unit_id:
        unit = db.equipment_units.get(unit_id)
        if unit is not None and unit["status"] == "LEASED":
            full_lease_cents = unit["lease_fee_cents_per_cycle"]

    lease_proration_cents = 0
    if cycle is not None:
        _unit, lease_proration_cents = cascade_equipment_to_return_pending(
            account, cycle, now)

    waive = transfer.get("waive_etf", True)
    charged_etf = 0
    if waive:
        # No ETF charge; emit a TRANSFER_WAIVER credit equal to the ETF.
        emit_credit(account["id"], "TRANSFER_WAIVER", transfer["id"], etf_cents)
    else:
        # ETF is charged on the cycle.
        charged_etf = etf_cents

    if cycle is not None:
        cycle["_disconnect_meta"] = {
            "etf_cents": charged_etf,
            "full_lease_cents": full_lease_cents,
            "lease_proration_cents": lease_proration_cents,
        }
        close_cycle(cycle)
        finalize_cycle(cycle)
