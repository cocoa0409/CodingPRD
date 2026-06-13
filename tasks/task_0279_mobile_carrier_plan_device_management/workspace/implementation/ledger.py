"""Charge ledger + line cancel cascade + cycle-close settlement.

Traces to PRD §3.5 (cancel cascade), §3.10 (settlement & money math), and the
two line_cancel_settlement variants.
"""
import db
import domain
from common import stamp_create, touch, parse_dt, public, clock_iso


def post_charge(billing_cycle_id, line_id, charge_type, amount_cents, memo):
    """Append an immutable Charge ledger event (PRD §2.5, §3.10).

    Charge carries only id + created_at (append-only), plus its system fields.
    """
    charge = {
        "billing_cycle_id": billing_cycle_id,
        "line_id": line_id,
        "charge_type": charge_type,
        "amount_cents": amount_cents,
        "memo": memo,
    }
    stamp_create(charge, common=False)
    db.charges[charge["id"]] = charge
    return charge


# ===========================================================================
# Calculation 5: line_cancel_settlement — FORWARD provisional variant.
# Runs at POST /lines/{lineId}/cancel (PRD §3.5, §3.10).
# ===========================================================================
def cancel_line_cascade(line, account):
    """Atomic cancel cascade. Caller has already validated preconditions.

    Drives the line to CANCELLED and fans out: settlement, EIP acceleration,
    add-on cancellation, SIM deactivation, number release, account recompute.
    """
    cycle = domain.open_cycle_for_account(account["id"])

    # --- FORWARD provisional settlement (only when an OPEN cycle exists) ---
    if cycle is not None and line.get("activated_at"):
        discount_pct = account["group_discount_pct"]
        plan = db.plans.get(line["plan_id"])
        if plan is not None:
            disc_base = domain.discounted_base_cents(plan, discount_pct)
            days_in_cycle = cycle["days_in_cycle"]
            active_days = domain.line_active_days(line, cycle)
            unused_days = days_in_cycle - active_days
            if unused_days > 0 and days_in_cycle > 0:
                from common import round_half_up
                forward_credit = round_half_up(
                    disc_base * unused_days, days_in_cycle)
                if forward_credit > 0:
                    post_charge(cycle["id"], line["id"], "CREDIT",
                                -forward_credit,
                                "Provisional unused-base credit on cancel")

    # --- Accelerate ACTIVE installment plans: post EIP_PAYOFF, drive PAID_OFF
    for ip in db.installment_plans.values():
        if ip["line_id"] == line["id"] and ip["status"] == "ACTIVE":
            payoff = ip["remaining_balance_cents"]
            if cycle is not None and payoff > 0:
                post_charge(cycle["id"], line["id"], "EIP_PAYOFF", payoff,
                            "Accelerated device payoff on line cancel")
            ip["remaining_balance_cents"] = 0
            ip["status"] = "PAID_OFF"
            touch(ip)

    # --- Cancel SCHEDULED/ACTIVE add-ons on the line ---
    for a in db.addons.values():
        if a["line_id"] == line["id"] and a["status"] in ("SCHEDULED", "ACTIVE"):
            a["status"] = "CANCELLED"
            touch(a)

    # --- Deactivate the linked SIM assignment ---
    for sim in db.sim_assignments.values():
        if sim["line_id"] == line["id"] and sim["status"] != "DEACTIVATED":
            sim["status"] = "DEACTIVATED"
            touch(sim)

    # --- Release the number, drive line CANCELLED ---
    line["phone_number"] = None
    line["status"] = "CANCELLED"
    line["_cancelled_at"] = clock_iso()
    line["_cancelled_in_cycle"] = cycle["id"] if cycle else None
    touch(line)

    # --- Recompute account derived fields; bump version (PRD §3.5) ---
    domain.recompute_account_derived(account, bump_version=True)


# ===========================================================================
# Cycle close settlement — CHRONOLOGICAL final variant + account_cycle_total.
# Runs at POST /billing-cycles/{cycleId}/close (PRD §3.10).
# ===========================================================================
def close_cycle(cycle, account):
    """Post all charges, set total_charges_cents, open a successor cycle.

    account_cycle_total: group discount computed once; per-line parts each
    rounded to whole cents, summed per line, then summed across lines
    (round-per-line-then-sum).
    """
    # STEP 1: group discount from the active set (already maintained on account)
    discount_pct = account["group_discount_pct"]
    days_in_cycle = cycle["days_in_cycle"]

    total_charges = 0

    # Settle each line that billed into this cycle: lines currently ACTIVE or
    # SUSPENDED, plus lines that were CANCELLED during this cycle (chronological
    # final variant bills only their active days + one normal EIP installment).
    for line in domain.account_lines(account["id"]):
        bills_here = line["status"] in ("ACTIVE", "SUSPENDED")
        cancelled_here = (line["status"] == "CANCELLED"
                          and line.get("_cancelled_in_cycle") == cycle["id"])
        if not (bills_here or cancelled_here):
            continue

        plan = db.plans.get(line["plan_id"])
        if plan is None:
            continue

        # PLAN_BASE: discounted, prorated (round-then-prorate)
        disc_base = domain.discounted_base_cents(plan, discount_pct)
        active_days = domain.line_active_days(line, cycle)
        prorated = domain.prorated_base_cents(disc_base, active_days, days_in_cycle)
        if prorated != 0:
            post_charge(cycle["id"], line["id"], "PLAN_BASE", prorated,
                        "Prorated discounted plan base")
        total_charges += prorated

        # OVERAGE: tiered (skip for lines cancelled this cycle? They still had
        # usage; PRD §3.10 says for each ACTIVE/SUSPENDED line. Cancelled-this-
        # cycle lines bill the chronological-final base + one EIP installment.)
        if bills_here:
            overage = domain.line_overage_cents(line, plan)
            if overage != 0:
                post_charge(cycle["id"], line["id"], "OVERAGE", overage,
                            "Tiered data overage")
            total_charges += overage

            # ADDON
            addon_cents = domain.line_addon_cents(line, cycle)
            if addon_cents != 0:
                post_charge(cycle["id"], line["id"], "ADDON", addon_cents,
                            "Add-on fees for cycle")
            total_charges += addon_cents

        # EIP_INSTALLMENT: one normal monthly installment for the cycle.
        # For cancelled-this-cycle lines the EIP was already accelerated &
        # PAID_OFF by the cancel cascade, so no ACTIVE EIP remains -> 0.
        eip_total = 0
        for ip in db.installment_plans.values():
            if ip["line_id"] != line["id"] or ip["status"] != "ACTIVE":
                continue
            inst = ip["monthly_installment_cents"]
            new_remaining = max(0, ip["remaining_balance_cents"] - inst)
            actual = ip["remaining_balance_cents"] - new_remaining  # final clamps
            ip["remaining_balance_cents"] = new_remaining
            ip["installments_paid"] = ip.get("installments_paid", 0) + 1
            if new_remaining == 0:
                ip["status"] = "PAID_OFF"
            touch(ip)
            eip_total += inst  # charge is the scheduled installment
        if eip_total != 0:
            post_charge(cycle["id"], line["id"], "EIP_INSTALLMENT", eip_total,
                        "Device installment for cycle")
        total_charges += eip_total

    # Apply wallet credit against the total (PRD §3.10)
    wallet = account.get("wallet_credit_cents", 0)
    if wallet:
        post_charge(cycle["id"], None, "CREDIT", -wallet,
                    "Wallet credit applied")
        total_charges -= wallet

    cycle["total_charges_cents"] = total_charges
    cycle["status"] = "CLOSED"
    touch(cycle)

    # Recompute EIP outstanding (some plans may have paid off)
    domain.recompute_account_derived(account, bump_version=False)

    # Open a successor OPEN cycle (PRD §3.10): starts at this cycle's end.
    successor = {
        "account_id": account["id"],
        "cycle_start": cycle["cycle_end"],
        "cycle_end": _successor_end(cycle),
        "days_in_cycle": _successor_days(cycle),
        "total_charges_cents": 0,
        "status": "OPEN",
    }
    stamp_create(successor, common=True)
    db.billing_cycles[successor["id"]] = successor
    return cycle


def _successor_end(cycle):
    """Successor cycle spans the same number of days as the closed cycle."""
    start = parse_dt(cycle["cycle_end"], "cycle_end")
    prev_start = parse_dt(cycle["cycle_start"], "cycle_start")
    span = parse_dt(cycle["cycle_end"], "cycle_end") - prev_start
    end = start + span
    return end.strftime("%Y-%m-%dT%H:%M:%S.") + f"{end.microsecond // 1000:03d}Z"


def _successor_days(cycle):
    from common import whole_utc_days
    prev_start = parse_dt(cycle["cycle_start"], "cycle_start")
    prev_end = parse_dt(cycle["cycle_end"], "cycle_end")
    return whole_utc_days(prev_start, prev_end)
