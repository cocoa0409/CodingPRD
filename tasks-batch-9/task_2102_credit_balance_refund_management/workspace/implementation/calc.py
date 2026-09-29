"""The nine calculation rules (PRD 3.2, 3.4, 3.6, 3.8, 3.10, 3.11, 3.12, 3.13)."""
import clock
import db
import derive
from errors import ApiError

# ------------------------------------------------------------------ constants
CREDIT_IDENTIFICATION_FLOOR_CENTS = 1

TIER_1_MAX_CENTS = 25000
TIER_2_MAX_CENTS = 250000
AGED_ESCALATION_DAYS = 181
SMALL_PATIENT_REFUND_CENTS = 5000

FEE_BAND_1_MAX_CENTS = 5000
FEE_BAND_2_MAX_CENTS = 50000
FEE_CAP_CENTS = 2500
MIN_CHECK_CENTS = 200
MIN_REFUND_CENTS = 100

WRITE_OFF_MAX_CENTS = 1000
MAX_REVISION_ROUNDS = 2

CHECK_STALE_DAYS = 180
DISPUTE_WINDOW_DAYS = 45
DISPUTE_RESOLUTION_GRACE_DAYS = 30
REPORT_PERIOD_BUFFER_DAYS = 7
MEDICARE_REPAYMENT_WINDOW_DAYS = 60

STATE_DORMANCY_DAYS = {"CA": 1095, "TX": 1095, "NY": 1825, "FL": 1825}
DUE_DILIGENCE_LEAD_DAYS = 120


# ------------------------------------------- 2. credit_balance_attribution_split
def attribution_split(cb, method):
    """PRD 3.4. Returns (patient_portion, payer_portion, attribution)."""
    credit = int(cb["credit_amount_cents"])
    payments = [t for t in db.txns_for_account(cb["account_id"])
                if t["txn_type"] == "PAYMENT"
                and not derive.txn_is_reversed(t)
                and t["reversal_of_transaction_id"] is None
                and t["posted_at"] <= cb["identified_at"]]
    total_paid = sum(abs(int(p["amount_cents"])) for p in payments)
    if total_paid == 0:
        return 0, 0, "UNDETERMINED"

    if method == "PROPORTIONAL":
        patient_paid = sum(abs(int(p["amount_cents"])) for p in payments
                           if p["source"] == "PATIENT")
        patient_portion = clock.round_half_up(credit * patient_paid, total_paid)
        payer_portion = credit - patient_portion
    else:  # REVERSE_CHRONOLOGICAL
        ordered = sorted(payments, key=lambda p: (p["posted_at"], p["_seq"]), reverse=True)
        remaining = credit
        patient_portion = 0
        payer_portion = 0
        for p in ordered:
            take = min(remaining, abs(int(p["amount_cents"])))
            if p["source"] == "PATIENT":
                patient_portion += take
            else:
                payer_portion += take
            remaining -= take
            if remaining == 0:
                break

    if patient_portion > 0 and payer_portion > 0:
        attribution = "SPLIT"
    elif patient_portion > 0:
        attribution = "PATIENT"
    else:
        attribution = "PAYER"
    return patient_portion, payer_portion, attribution


# ----------------------------------------------------- 5. refund_approval_tier
def approval_tier(requested_amount_cents, cb, payee_type):
    """PRD 3.6. Returns (required_approval_tier, required_approval_count)."""
    amount = int(requested_amount_cents)
    if amount <= TIER_1_MAX_CENTS:
        base_tier = 1
    elif amount <= TIER_2_MAX_CENTS:
        base_tier = 2
    else:
        base_tier = 3

    payer = db.payers.get(cb["payer_id"])
    payer_type = payer["payer_type"] if payer else None

    escalations = 0
    if payer_type in ("MEDICARE", "MEDICAID"):
        escalations += 1
    if derive.cb_aging_days(cb) >= AGED_ESCALATION_DAYS:
        escalations += 1
    if not derive.cb_root_cause_confirmed(cb):
        escalations += 1

    de_escalations = 1 if (payee_type == "PATIENT" and amount <= SMALL_PATIENT_REFUND_CENTS) else 0

    tier = min(3, max(base_tier, base_tier + escalations - de_escalations))
    return tier, (2 if tier == 3 else 1)


# --------------------------------------------------- 6. refund_net_disbursement
def net_disbursement(gross):
    """PRD 3.8. Band on GROSS only; round once, then cap; then the floor guard."""
    gross = int(gross)
    if gross <= FEE_BAND_1_MAX_CENTS:
        fee_bp, flat_fee_cents = 0, 0
    elif gross <= FEE_BAND_2_MAX_CENTS:
        fee_bp, flat_fee_cents = 150, 100
    else:
        fee_bp, flat_fee_cents = 75, 500
    processing_fee_cents = min(clock.round_half_up(gross * fee_bp, 10000) + flat_fee_cents,
                               FEE_CAP_CENTS)
    net_check_amount_cents = gross - processing_fee_cents
    if net_check_amount_cents < MIN_CHECK_CENTS:
        raise ApiError("ERR_NET_BELOW_MIN_CHECK")
    return processing_fee_cents, net_check_amount_cents


# ------------------------------------------------ 7. offset_waterfall_allocation
def offset_waterfall(notice, target_account_ids):
    """PRD 3.10. Returns a list of {credit_balance, applied_cents,
    admin_fee_share_cents} in waterfall order."""
    eligible = [cb for cb in db.credit_balances.values()
                if cb["account_id"] in target_account_ids
                and cb["payer_id"] == notice["payer_id"]
                and cb["status"] in ("ATTRIBUTED", "REFUND_PENDING")
                and int(cb["payer_portion_cents"]) > 0
                and derive.cb_outstanding_cents(cb) > 0]
    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_CREDIT")

    ordered = sorted(eligible, key=lambda c: (c["identified_at"], c["created_at"], c["_seq"]))
    pool = derive.notice_remaining_cents(notice)
    lines = []
    for cb in ordered:
        if pool == 0:
            break
        capacity = min(int(cb["payer_portion_cents"]), derive.cb_outstanding_cents(cb))
        line = min(pool, capacity)
        if line == 0:
            continue
        lines.append({"credit_balance": cb, "applied_cents": line, "admin_fee_share_cents": 0})
        pool -= line

    if not lines:
        return lines

    applied_total = sum(l["applied_cents"] for l in lines)
    admin_fee = int(notice["admin_fee_cents"])
    for l in lines:
        l["admin_fee_share_cents"] = clock.round_half_up(admin_fee * l["applied_cents"],
                                                         applied_total)
    residual = admin_fee - sum(l["admin_fee_share_cents"] for l in lines)
    lines[-1]["admin_fee_share_cents"] += residual
    return lines


# -------------------------------------------------- 8. escheat_dormancy_clock
def dormancy_clock(chk, basis):
    """PRD 3.12. Returns (state_code, dormancy_days, dormancy_start_at,
    escheat_due_at, due_diligence_open_at)."""
    state_code = chk["payee_state_code"]
    dormancy_days = STATE_DORMANCY_DAYS.get(state_code, 1095)
    if basis == "LAST_CONTACT":
        dormancy_start_at = chk["issued_at"]
        req = db.refund_requests.get(chk["refund_request_id"])
        cb = db.credit_balances.get(req["credit_balance_id"]) if req else None
        if cb is not None:
            last_contact = derive.account_last_activity_at(cb["account_id"])
            if last_contact is not None and last_contact > dormancy_start_at:
                dormancy_start_at = last_contact
    else:
        dormancy_start_at = chk["issued_at"]
    escheat_due_at = clock.add_days(dormancy_start_at, dormancy_days)
    due_diligence_open_at = clock.add_days(escheat_due_at, -DUE_DILIGENCE_LEAD_DAYS)
    return state_code, dormancy_days, dormancy_start_at, escheat_due_at, due_diligence_open_at


# ------------------------------------------- 9. credit_balance_liability_report
def liability_report(scope_code, as_of):
    """PRD 3.13. Every total is valued at as_of_at, not at the logical clock."""
    included = []
    for cb in db.credit_balances.values():
        if cb["identified_at"] > as_of:
            continue
        if cb["status"] not in derive.OPEN_CREDIT_STATUSES:
            continue
        if scope_code != "ALL":
            payer = db.payers.get(cb["payer_id"])
            if payer is None or payer["payer_type"] != scope_code:
                continue
        included.append(cb)
    included.sort(key=lambda c: (c["identified_at"], c["created_at"], c["_seq"]))

    included_ids = set(c["id"] for c in included)
    medicare_at_risk = 0
    for ob in db.medicare_obligations.values():
        if ob["state"] in ("OPEN", "LATE") and ob["due_at"] <= as_of \
                and ob["credit_balance_id"] in included_ids:
            medicare_at_risk += int(ob["reportable_amount_cents"])

    return {
        "line_count": len(included),
        "total_liability_cents": sum(int(c["credit_amount_cents"]) for c in included),
        "patient_liability_cents": sum(int(c["patient_portion_cents"]) for c in included),
        "payer_liability_cents": sum(int(c["payer_portion_cents"]) for c in included),
        "over_180_count": len([c for c in included
                               if clock.whole_days(as_of, c["identified_at"]) >= 181]),
        "medicare_at_risk_cents": medicare_at_risk,
    }
