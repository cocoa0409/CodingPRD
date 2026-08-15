"""Cascade chains and shared workflows (PRD 2.7, 3.3-3.9).

Cascade A: payment RETURN -> REVERSE allocations -> charge recompute ->
DRAFT notice demand recompute -> NSF_FEE charge -> referral recompute/create.
Cascade B: lease MOVE_OUT -> cancel DRAFT notices and DRAFT/ACTIVE plans ->
chronological reconciliation -> PENDING referral when balance > 0.
Cascade C: dispute RESOLVE ADJUSTED -> charge amount corrected -> outstanding
recompute -> DRAFT notice demand + PENDING referral recompute -> auto-recall.
"""

import db
import errors
from services import calc

OPEN_CHARGE_STATES = ("OPEN", "PARTIALLY_PAID")


# ---------------------------------------------------------------------------
# Charge recompute and downstream recomputes
# ---------------------------------------------------------------------------

def recompute_charge(charge, touch=True):
    """Recompute outstanding_cents = amount - waived - net applied, and flip
    status among OPEN/PARTIALLY_PAID/PAID per PRD 3.2. WAIVED keeps its status
    (terminal) but its outstanding figure still tracks the ledger; VOID is
    frozen at zero (a dispute adjustment to zero voids the charge)."""
    if charge["status"] == "VOID":
        return
    net = calc.net_applied_cents(charge["id"])
    outstanding = charge["amount_cents"] - charge["waived_cents"] - net
    if charge["status"] == "WAIVED":
        if outstanding != charge["outstanding_cents"]:
            charge["outstanding_cents"] = outstanding
            if touch:
                db.touch(charge)
        return
    if net == 0:
        status = "OPEN"
    elif outstanding == 0:
        status = "PAID"
    else:
        status = "PARTIALLY_PAID"
    if outstanding != charge["outstanding_cents"] or status != charge["status"]:
        charge["outstanding_cents"] = outstanding
        charge["status"] = status
        if touch:
            db.touch(charge)


def recompute_draft_notices(charge):
    """Every DRAFT notice covering this charge recomputes its demanded amount
    (PRD 3.7); the value freezes at ISSUE because only DRAFT notices recompute."""
    for n in db.notices.values():
        if n["status"] == "DRAFT" and charge["id"] in n["charge_ids"]:
            demand = calc.notice_demand(n)
            if demand != n["amount_demanded_cents"]:
                n["amount_demanded_cents"] = demand
                db.touch(n)


def recompute_pending_referrals(lease):
    """A PENDING referral recomputes its chronological balance whenever a
    charge on the lease changes (PRD 3.9); a recomputation that drives the
    balance below the collections threshold auto-recalls the referral with
    recall_reason BALANCE_RESOLVED."""
    prop = calc.property_of(lease)
    for r in db.referrals.values():
        if r["lease_id"] != lease["id"] or r["status"] != "PENDING":
            continue
        bal = calc.move_out_balances(lease)[1]
        if bal != r["referred_balance_cents"]:
            r["referred_balance_cents"] = bal
            if bal < prop["collections_threshold_cents"]:
                r["status"] = "RECALLED"
                r["recall_reason"] = "BALANCE_RESOLVED"
            db.touch(r)


def cascade_charge_changed(charge):
    """Shared downstream of allocation / reversal / waiver / adjustment."""
    recompute_draft_notices(charge)
    recompute_pending_referrals(db.leases[charge["lease_id"]])


def new_charge(lease, kind, source, period_start, period_end, due_date,
               amount_cents, created_by):
    charge = db.init_common({
        "lease_id": lease["id"],
        "kind": kind,
        "source": source,
        "period_start_date": period_start,
        "period_end_date": period_end,
        "due_date": due_date,
        "amount_cents": amount_cents,
        "waived_cents": 0,
        "outstanding_cents": amount_cents,
        "status": "OPEN",
        "created_by_user_id": created_by,
    })
    db.charges[charge["id"]] = charge
    return charge


def new_referral(lease, balance):
    ref = db.init_common({
        "lease_id": lease["id"],
        "referred_balance_cents": balance,
        "status": "PENDING",
        "agency_name": None,
        "referred_date": None,
        "recall_reason": None,
    })
    db.referrals[ref["id"]] = ref
    return ref


# ---------------------------------------------------------------------------
# Payment waterfall posting and the NSF return cascade
# ---------------------------------------------------------------------------

def run_waterfall(payment, lease, prop):
    """PRD 3.3: walk candidates in policy order, allocating the lesser of the
    remaining money and the charge's outstanding; stop when nothing remains.
    Each allocation is an append-only APPLY row with a 1-based order."""
    remaining = payment["amount_cents"]
    order = 0
    run_ids = []
    for charge in calc.waterfall_candidates(lease["id"], prop["posting_priority_policy"]):
        if remaining <= 0:
            break
        amount = min(remaining, charge["outstanding_cents"])
        order += 1
        alloc = db.init_allocation({
            "payment_id": payment["id"],
            "charge_id": charge["id"],
            "direction": "APPLY",
            "amount_cents": amount,
            "allocation_order": order,
            "note": "",
        })
        db.allocations[alloc["id"]] = alloc
        run_ids.append(alloc["id"])
        recompute_charge(charge)
        cascade_charge_changed(charge)
        remaining -= amount
    payment["_current_run"] = run_ids


def post_payment(payment):
    """Payment POST transition (initial posting and re-presentment). Caller has
    already applied the lease gate and the transition precondition."""
    lease = db.leases[payment["lease_id"]]
    prop = calc.property_of(lease)
    total = calc.total_outstanding(lease["id"])
    amount = payment["amount_cents"]
    # PRD 3.3: overpayment first, then the partial-minimum floor.
    if amount > total:
        errors.fail(
            errors.ERR_OVERPAYMENT_REJECTED,
            "Payment amount %d exceeds total outstanding %d." % (amount, total),
        )
    if amount != total:
        floor = -(-total * prop["min_partial_payment_percent"] // 100)  # ceil
        if amount < floor:
            errors.fail(
                errors.ERR_PARTIAL_BELOW_MINIMUM,
                "Partial payment %d is below the minimum %d." % (amount, floor),
            )
    run_waterfall(payment, lease, prop)
    payment["status"] = "POSTED"
    payment["posted_date"] = db.today_str()
    db.touch(payment)


def return_payment(payment, reason_code, nsf_fee_cents):
    """Payment RETURN transition — Cascade A (PRD 3.4), in the fixed order."""
    lease = db.leases[payment["lease_id"]]
    prop = calc.property_of(lease)
    # Link 1: the payment itself flips and the return count increases.
    payment["status"] = "RETURNED"
    payment["return_count"] += 1
    payment["return_reason_code"] = reason_code
    if nsf_fee_cents is not None:
        payment["nsf_fee_cents"] = nsf_fee_cents
    db.touch(payment)
    # Link 2: every APPLY allocation of the current posting run is reversed by
    # an equal REVERSE allocation bearing the note 'nsf-reversal'.
    affected = []
    for aid in payment.get("_current_run", []):
        orig = db.allocations[aid]
        rev = db.init_allocation({
            "payment_id": payment["id"],
            "charge_id": orig["charge_id"],
            "direction": "REVERSE",
            "amount_cents": orig["amount_cents"],
            "allocation_order": orig["allocation_order"],
            "note": "nsf-reversal",
        })
        db.allocations[rev["id"]] = rev
        affected.append(db.charges[orig["charge_id"]])
    # Link 3: each affected charge recomputes and flips back toward OPEN.
    for charge in affected:
        recompute_charge(charge)
    # Link 4: DRAFT notices covering affected charges recompute; the
    # returned-payment fee is assessed at min(requested, property cap), due and
    # period-stamped on the current date, source RETURN, created by 'system'.
    for charge in affected:
        recompute_draft_notices(charge)
    if nsf_fee_cents is not None:
        fee = min(nsf_fee_cents, prop["nsf_fee_cap_cents"])
        if fee > 0:
            today = db.today_str()
            new_charge(lease, "NSF_FEE", "RETURN", today, today, today, fee, "system")
    # Link 5: a PENDING referral recomputes; on an ENDED lease with no referral
    # at all and a positive post-reversal chronological balance, a PENDING
    # referral is created on the spot.
    existing = [r for r in db.referrals.values() if r["lease_id"] == lease["id"]]
    if existing:
        recompute_pending_referrals(lease)
    elif lease["status"] == "ENDED":
        bal = calc.move_out_balances(lease)[1]
        if bal > 0:
            new_referral(lease, bal)


# ---------------------------------------------------------------------------
# Cascade B: lease move-out
# ---------------------------------------------------------------------------

def move_out_lease(lease, move_out_date):
    """PRD 3.9 Cascade B. Existing charges are NOT voided or prorated here;
    proration lives only inside the chronological balance variant."""
    lease["status"] = "ENDED"
    lease["move_out_date"] = move_out_date
    db.touch(lease)
    for n in db.notices.values():
        if n["lease_id"] == lease["id"] and n["status"] == "DRAFT":
            n["status"] = "CANCELLED"
            n["cancel_reason"] = "MOVE_OUT"
            db.touch(n)
    for p in db.plans.values():
        if p["lease_id"] == lease["id"] and p["status"] in ("DRAFT", "ACTIVE"):
            p["status"] = "CANCELLED"
            p["cancel_reason"] = "MOVE_OUT"
            db.touch(p)
    bal = calc.move_out_balances(lease)[1]
    if bal > 0:
        new_referral(lease, bal)


# ---------------------------------------------------------------------------
# Cascade C: dispute resolution with adjustment
# ---------------------------------------------------------------------------

def apply_dispute_adjustment(dispute, adjusted_amount_cents):
    charge = db.charges[dispute["charge_id"]]
    # Link 1: the face amount is corrected in place; zero voids the charge.
    charge["amount_cents"] = adjusted_amount_cents
    if adjusted_amount_cents == 0:
        charge["status"] = "VOID"
        charge["outstanding_cents"] = 0
    else:
        # Link 2: outstanding recompute; a partial adjustment keeps the status.
        charge["outstanding_cents"] = (
            adjusted_amount_cents - charge["waived_cents"] - calc.net_applied_cents(charge["id"])
        )
    db.touch(charge)
    # Link 3: covering DRAFT notices and the PENDING referral recompute.
    recompute_draft_notices(charge)
    recompute_pending_referrals(db.leases[charge["lease_id"]])


# ---------------------------------------------------------------------------
# Delinquency sweep (PRD 3.6) — ops-run checkpoint over the logical clock
# ---------------------------------------------------------------------------

def run_sweep():
    today = db.clock_date()
    counts = {
        "late_fees_assessed_count": 0,
        "installments_marked_missed_count": 0,
        "plans_defaulted_count": 0,
        "plans_cured_count": 0,
        "notices_cured_count": 0,
        "notices_expired_count": 0,
    }

    # Duty 1: late-fee assessment (final variant, as_of = run date). At most
    # one non-VOID LATE_FEE per (lease, period), which makes a repeated run at
    # an unchanged clock a no-op.
    for charge in sorted(db.charges.values(), key=lambda c: c["created_at"]):
        if charge["kind"] != "RENT" or charge["status"] not in OPEN_CHARGE_STATES:
            continue
        lease = db.leases[charge["lease_id"]]
        if lease["status"] != "ACTIVE":
            continue
        if calc.has_late_fee_for_period(lease["id"], charge):
            continue
        prop = calc.property_of(lease)
        fee = calc.late_fee_cents(lease, charge, prop, today)
        if fee <= 0:
            continue
        new_charge(
            lease, "LATE_FEE", "SWEEP",
            charge["period_start_date"], charge["period_end_date"],
            today.isoformat(), fee, "system",
        )
        counts["late_fees_assessed_count"] += 1
        # The assessed fee removes the provisional component from any DRAFT
        # notice covering the rent charge.
        recompute_draft_notices(charge)

    # Duty 2: installment evaluation of ACTIVE plans (PRD 3.6/3.8).
    for plan in sorted(db.plans.values(), key=lambda p: p["created_at"]):
        if plan["status"] != "ACTIVE":
            continue
        covered = set(plan["charge_ids"])
        covered_paid = 0
        for a in db.allocations.values():
            if a["charge_id"] not in covered:
                continue
            payment = db.payments[a["payment_id"]]
            posted = payment["posted_date"]
            if posted is None or posted < plan["_activated_date"]:
                continue
            covered_paid += a["amount_cents"] if a["direction"] == "APPLY" else -a["amount_cents"]
        cumulative = 0
        missed = 0
        changed = False
        for inst in sorted(plan["installments"], key=lambda i: i["sequence_number"]):
            cumulative += inst["amount_cents"]
            if covered_paid >= cumulative:
                new_status = "PAID"
            elif today > calc.parse_d(inst["due_date"]):
                new_status = "MISSED"
            else:
                new_status = "PENDING"
            if new_status == "MISSED":
                missed += 1
                if inst["status"] != "MISSED":
                    counts["installments_marked_missed_count"] += 1
            if inst["status"] != new_status:
                inst["status"] = new_status
                changed = True
        if plan["missed_installment_count"] != missed:
            plan["missed_installment_count"] = missed
            changed = True
        if missed >= 2:
            plan["status"] = "DEFAULTED"
            plan["defaulted_date"] = today.isoformat()
            counts["plans_defaulted_count"] += 1
            changed = True
        elif all(i["status"] == "PAID" for i in plan["installments"]):
            plan["status"] = "CURED"
            counts["plans_cured_count"] += 1
            changed = True
        if changed:
            db.touch(plan)

    # Duty 3: cure or expire notices in ISSUED or SERVED status (PRD 3.6/3.7).
    for notice in sorted(db.notices.values(), key=lambda n: n["created_at"]):
        if notice["status"] not in ("ISSUED", "SERVED"):
            continue
        all_zero = all(
            db.charges[cid]["outstanding_cents"] == 0 for cid in notice["charge_ids"]
        )
        deadline = calc.parse_d(notice["cure_deadline_date"])
        if all_zero and today <= deadline:
            notice["status"] = "CURED"
            counts["notices_cured_count"] += 1
            db.touch(notice)
        elif not all_zero and today > deadline:
            notice["status"] = "EXPIRED"
            counts["notices_expired_count"] += 1
            db.touch(notice)

    return counts
