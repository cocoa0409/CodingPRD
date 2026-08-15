"""Business logic: case derived-field recomputation (PRD 2.10 / 3.3), pricing
calculations (Table 3), cascades, and the time-driven sweep."""

from datetime import timedelta
from decimal import Decimal

from db import db
from errors import (
    ApiError,
    ERR_NO_ACTIVE_CONTRACT,
    ERR_RATE_NOT_FOUND,
    ERR_SNAPSHOT_STALE,
    ERR_UNKNOWN_CPT_CODE,
)
from util import (
    add_business_days,
    add_calendar_month,
    base_record,
    business_days_between,
    end_of_day_iso,
    now_dt,
    now_iso,
    parse_datetime_value,
    rhu,
    pct_rhu_2dp,
    today,
    touch,
)

# Calculation constants (Table 3)
UNINSURED_DISCOUNT_PCT = 25
HIGH_DOLLAR_THRESHOLD_CENTS = 1000000
REQUIRED_DEPOSIT_PCT = 25
GFE_FULL_WINDOW_BD = 10
GFE_SHORT_WINDOW_BD = 3
GFE_FULL_DEADLINE_BD = 3
GFE_SHORT_DEADLINE_BD = 1
REFUND_FULL_WINDOW_BD = 2
REFUND_PARTIAL_PCT = 50
SNAPSHOT_TTL_DAYS = 30
FIRST_DUE_DAYS = 30
DEFAULT_GRACE_DAYS = 14
GFE_DISPUTE_THRESHOLD_CENTS = 40000
VARIANCE_TOLERANCE_PCT = Decimal("10.00")

INACTIVE_ESTIMATE_STATES = ("SUPERSEDED", "CANCELLED", "EXPIRED")


# ---------------------------------------------------------------------------
# entity lookups
# ---------------------------------------------------------------------------

def case_estimates(case_id):
    return [e for e in db.estimates.values() if e["case_id"] == case_id]


def case_deposits(case_id):
    return [d for d in db.deposits.values() if d["case_id"] == case_id]


def case_authorizations(case_id):
    return [a for a in db.authorizations.values() if a["case_id"] == case_id]


def case_escalations(case_id):
    return [e for e in db.escalations.values() if e["case_id"] == case_id]


def case_plans(case_id):
    return [p for p in db.plans.values() if p["case_id"] == case_id]


def active_estimate(case):
    """Latest estimate not in {SUPERSEDED, CANCELLED, EXPIRED}; None if none."""
    live = [e for e in case_estimates(case["id"]) if e["status"] not in INACTIVE_ESTIMATE_STATES]
    if not live:
        return None
    return max(live, key=lambda e: e["revision"])


def locked_estimate(case):
    """The ACCEPTED-or-FINALIZED estimate (acceptance locks the estimate set)."""
    locked = [e for e in case_estimates(case["id"]) if e["status"] in ("ACCEPTED", "FINALIZED")]
    if not locked:
        return None
    return max(locked, key=lambda e: e["revision"])


# ---------------------------------------------------------------------------
# case derived fields (PRD 3.3) — recomputed on every relevant child event
# ---------------------------------------------------------------------------

def recompute_case(case):
    """Recompute all derived fields in place. Returns True if anything changed."""
    before = {k: case.get(k) for k in (
        "active_estimate_id", "auth_required", "auth_satisfied",
        "required_deposit_cents", "deposit_posted_cents", "deposit_satisfied",
        "high_dollar_flag", "escalation_cleared", "clearance_posture",
    )}

    active = active_estimate(case)
    locked = locked_estimate(case)

    case["active_estimate_id"] = active["id"] if active else None

    # auth_required: active estimate INSURED and any line's CPT needs prior auth
    auth_required = False
    if active and active["pricing_mode"] == "INSURED":
        for line in active["lines"]:
            ci_id = db.cpt_index.get(line["cpt_code"])
            if ci_id and db.charge_items[ci_id]["requires_auth_prior"]:
                auth_required = True
                break
    case["auth_required"] = auth_required

    # auth_satisfied
    if not auth_required:
        case["auth_satisfied"] = True
    else:
        satisfied = False
        for a in case_authorizations(case["id"]):
            if (a["status"] == "APPROVED"
                    and a["valid_from"] is not None
                    and a["valid_from"] <= case["service_date"] <= a["valid_to"]):
                satisfied = True
                break
        case["auth_satisfied"] = satisfied

    # required_deposit_cents: 0 until an estimate is ACCEPTED, then 25% half-up
    if locked is not None:
        case["required_deposit_cents"] = rhu(REQUIRED_DEPOSIT_PCT * locked["patient_responsibility_cents"], 100)
    else:
        case["required_deposit_cents"] = 0

    # deposit ledger: sum over POSTED deposits
    posted = sum(d["amount_cents"] for d in case_deposits(case["id"]) if d["status"] == "POSTED")
    case["deposit_posted_cents"] = posted

    # deposit_satisfied
    if active is not None and active["status"] == "FINALIZED":
        case["deposit_satisfied"] = True
    elif locked is not None and posted >= case["required_deposit_cents"]:
        case["deposit_satisfied"] = True
    else:
        case["deposit_satisfied"] = False

    # high_dollar_flag tracks the active estimate's flag
    case["high_dollar_flag"] = bool(active and active["high_dollar_flag"])

    # escalation_cleared
    escs = case_escalations(case["id"])
    any_open = any(e["status"] == "OPEN" for e in escs)
    hd_ok = True
    if case["high_dollar_flag"]:
        hd_ok = any(
            e["status"] == "APPROVED"
            and e["reason"] == "HIGH_DOLLAR"
            and e["estimate_id"] == case["active_estimate_id"]
            for e in escs
        )
    case["escalation_cleared"] = (not any_open) and hd_ok

    # clearance_posture
    if case["auth_satisfied"] and case["deposit_satisfied"] and case["escalation_cleared"]:
        case["clearance_posture"] = "READY"
    else:
        case["clearance_posture"] = "BLOCKED"

    return any(before[k] != case[k] for k in before)


def regress_case_if_cleared(case):
    """CLEARED -> IN_REVIEW when a clearance gate has broken (PRD 3.9)."""
    if case["status"] == "CLEARED" and not (
        case["auth_satisfied"] and case["deposit_satisfied"] and case["escalation_cleared"]
    ):
        case["status"] = "IN_REVIEW"
        case["clearance_posture"] = "BLOCKED"
        return True
    return False


def sync_case(case, force=False):
    """Recompute derived fields; bump version/updated_at when changed (or forced)."""
    changed = recompute_case(case)
    if force or changed:
        touch(case)


# ---------------------------------------------------------------------------
# GFE delivery deadline (computed at estimate creation)
# ---------------------------------------------------------------------------

def compute_gfe_timeline(created_date, service_date_str):
    """Returns (gfe_required, gfe_delivery_deadline_iso_or_None)."""
    sd = parse_datetime_value(service_date_str).date()
    bd = business_days_between(created_date, sd)
    if bd >= GFE_FULL_WINDOW_BD:
        deadline_bd = GFE_FULL_DEADLINE_BD
    elif bd >= GFE_SHORT_WINDOW_BD:
        deadline_bd = GFE_SHORT_DEADLINE_BD
    else:
        return False, None
    deadline_date = add_business_days(created_date, deadline_bd)
    return True, end_of_day_iso(deadline_date)


# ---------------------------------------------------------------------------
# pricing (PRD 3.4)
# ---------------------------------------------------------------------------

def _find_rate(contract_id, cpt_code, service_date):
    """Half-open [effective_from, effective_to) window covering service_date."""
    for r in db.rates.values():
        if r["contract_id"] != contract_id or r["cpt_code"] != cpt_code:
            continue
        if r["effective_from"] <= service_date and (
            r["effective_to"] is None or service_date < r["effective_to"]
        ):
            return r
    return None


def price_estimate(est):
    """Run the pricing calculation for a DRAFT estimate. Raises ApiError on
    business-rule failures. Mutates the estimate in place (lines + totals)."""
    case = db.cases[est["case_id"]]
    lines = est["lines"]

    if est["pricing_mode"] == "INSURED":
        snap = db.snapshots.get(est["eligibility_snapshot_id"])
        # (10) eligibility freshness — evaluated first
        if snap is None or snap["status"] != "ACTIVE":
            raise ApiError(ERR_SNAPSHOT_STALE,
                           "linked eligibility snapshot is not ACTIVE", 409)
        verified = parse_datetime_value(snap["verified_at"])
        if now_dt() > verified + timedelta(days=SNAPSHOT_TTL_DAYS):
            raise ApiError(ERR_SNAPSHOT_STALE,
                           "linked eligibility snapshot is older than the 30-day TTL", 409)

    # (11) every line CPT must exist in the charge master
    for line in lines:
        if line["cpt_code"] not in db.cpt_index:
            raise ApiError(ERR_UNKNOWN_CPT_CODE,
                           "unknown cpt_code: %s" % line["cpt_code"], 422)

    if est["pricing_mode"] == "INSURED":
        snap = db.snapshots[est["eligibility_snapshot_id"]]
        # (12) snapshot must belong to the case's patient
        if snap["patient_id"] != case["patient_id"]:
            raise ApiError(ERR_SNAPSHOT_PATIENT_MISMATCH,
                           "eligibility snapshot belongs to a different patient", 422)
        # (13) a payer contract must exist for the snapshot's payer_code
        contract_id = db.payer_code_index.get(snap["payer_code"])
        if contract_id is None:
            raise ApiError(ERR_NO_ACTIVE_CONTRACT,
                           "no payer contract exists for payer_code %s" % snap["payer_code"], 422)
        contract = db.payer_contracts[contract_id]
        # (14) per-line contracted rate effective on service_date
        unit_rates = []
        for line in lines:
            rate = _find_rate(contract["id"], line["cpt_code"], case["service_date"])
            if rate is None:
                raise ApiError(ERR_RATE_NOT_FOUND,
                               "no contracted rate for %s effective on %s"
                               % (line["cpt_code"], case["service_date"]), 422)
            unit_rates.append(rate["rate_cents"])
        _price_insured(est, contract, lines, unit_rates, snap)
    else:
        _price_gfe(est, lines)

    # high-dollar screening (after patient responsibility is known)
    est["high_dollar_flag"] = est["patient_responsibility_cents"] >= HIGH_DOLLAR_THRESHOLD_CENTS
    if est["high_dollar_flag"]:
        already = any(
            e["reason"] == "HIGH_DOLLAR" and e["status"] == "OPEN"
            and e["estimate_id"] == est["id"]
            for e in db.escalations.values()
        )
        if not already:
            create_escalation(
                case,
                reason="HIGH_DOLLAR",
                estimate_id=est["id"],
                trigger_amount_cents=est["patient_responsibility_cents"],
                opened_by="system",
            )


def _price_insured(est, contract, lines, unit_rates, snap):
    n = len(lines)
    # bundled_contract_pricing
    if contract["bundling_rule"] == "MULTIPLE_PROCEDURE_REDUCTION":
        # rank: unit_rate DESC, cpt_code ASC, input index ASC
        order = sorted(range(n), key=lambda i: (-unit_rates[i], lines[i]["cpt_code"], i))
        adjusted = [0] * n
        for rank, idx in enumerate(order):
            if rank == 0:
                adjusted[idx] = unit_rates[idx]
            else:
                adjusted[idx] = rhu(unit_rates[idx] * contract["reduction_pct"], 100)
    else:
        adjusted = list(unit_rates)

    new_lines = []
    for i, line in enumerate(lines):
        line_amount = line["quantity"] * adjusted[i]
        new_lines.append({
            "cpt_code": line["cpt_code"],
            "quantity": line["quantity"],
            # unit_rate_cents is the contracted rate (PRD 3.4: "Each line's
            # `unit_rate_cents` is the `rate_cents` of the matching contract
            # rate"); the MPR-adjusted rate only feeds line_amount_cents.
            "unit_rate_cents": unit_rates[i],
            "line_amount_cents": line_amount,
        })
    est["lines"] = new_lines
    allowed = sum(l["line_amount_cents"] for l in new_lines)
    est["allowed_amount_cents"] = allowed

    # estimate_patient_responsibility — per line in cpt_code ASC (input index
    # ASC final tie-break), carrying a running deductible remainder
    ded_remaining = max(0, snap["deductible_total_cents"] - snap["deductible_met_cents"])
    deductible_applied = 0
    coinsurance = 0
    benefit_order = sorted(range(n), key=lambda i: (new_lines[i]["cpt_code"], i))
    for i in benefit_order:
        line_amount = new_lines[i]["line_amount_cents"]
        to_ded = min(line_amount, ded_remaining)
        ded_remaining -= to_ded
        deductible_applied += to_ded
        coinsurance += rhu((line_amount - to_ded) * snap["coinsurance_pct"], 100)
    est["deductible_applied_cents"] = deductible_applied
    est["coinsurance_cents"] = coinsurance

    oop_remaining = max(0, snap["oop_max_cents"] - snap["oop_met_cents"])
    resp = min(deductible_applied + coinsurance, oop_remaining)
    est["patient_responsibility_cents"] = resp
    est["insurance_pays_cents"] = allowed - resp
    est["gfe_total_cents"] = 0


def _price_gfe(est, lines):
    new_lines = []
    allowed = 0
    gfe_total = 0
    for line in lines:
        ci = db.charge_items[db.cpt_index[line["cpt_code"]]]
        gross = line["quantity"] * ci["list_price_cents"]
        discount = rhu(gross * UNINSURED_DISCOUNT_PCT, 100)
        allowed += gross
        gfe_total += gross - discount
        new_lines.append({
            "cpt_code": line["cpt_code"],
            "quantity": line["quantity"],
            "unit_rate_cents": ci["list_price_cents"],
            "line_amount_cents": gross,
        })
    est["lines"] = new_lines
    est["allowed_amount_cents"] = allowed
    est["gfe_total_cents"] = gfe_total
    est["deductible_applied_cents"] = 0
    est["coinsurance_cents"] = 0
    est["patient_responsibility_cents"] = gfe_total
    est["insurance_pays_cents"] = 0


# ---------------------------------------------------------------------------
# deposit refund rule (PRD 3.6)
# ---------------------------------------------------------------------------

def deposit_refund_amount(amount_cents, service_date_str):
    sd = parse_datetime_value(service_date_str).date()
    bd = business_days_between(today(), sd)
    if bd >= REFUND_FULL_WINDOW_BD:
        return amount_cents
    if bd == 1:
        return rhu(amount_cents * REFUND_PARTIAL_PCT, 100)
    return 0


# ---------------------------------------------------------------------------
# escalations
# ---------------------------------------------------------------------------

def create_escalation(case, reason, estimate_id, trigger_amount_cents, opened_by,
                      decision_note=None):
    rec = base_record()
    rec.update({
        "case_id": case["id"],
        "estimate_id": estimate_id,
        "reason": reason,
        "trigger_amount_cents": trigger_amount_cents,
        "status": "OPEN",
        "opened_by_user_id": opened_by,
        "decided_by_user_id": None,
        "decision_note": decision_note,
    })
    db.escalations[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# estimate finalize cascades (PRD 3.9)
# ---------------------------------------------------------------------------

def finalize_variance(est, actual_billed_cents):
    """Cascade link 1: create the VarianceRecord with both baselines."""
    baseline_first = est["first_presented_patient_resp_cents"]
    baseline_accepted = est["patient_responsibility_cents"]
    var_first = actual_billed_cents - baseline_first
    var_accepted = actual_billed_cents - baseline_accepted
    if baseline_accepted == 0:
        pct = Decimal("0.00") if actual_billed_cents == 0 else Decimal("100.00")
    else:
        pct = pct_rhu_2dp(abs(var_accepted) * 100, baseline_accepted)
    if pct <= VARIANCE_TOLERANCE_PCT:
        classification = "WITHIN_TOLERANCE"
    elif var_accepted > 0:
        classification = "OVER_TOLERANCE"
    else:
        classification = "UNDER_TOLERANCE"

    rec = base_record()
    rec.update({
        "estimate_id": est["id"],
        "baseline_first_presented_resp_cents": baseline_first,
        "baseline_last_accepted_resp_cents": baseline_accepted,
        "actual_billed_cents": actual_billed_cents,
        "variance_vs_first_cents": var_first,
        "variance_vs_accepted_cents": var_accepted,
        "variance_pct": float(pct),
        "classification": classification,
        "dispute_eligible": est["dispute_eligible"],
        "status": "UNREVIEWED",
        "root_cause": None,
    })
    db.variance_records[rec["id"]] = rec
    return rec


def finalize_deposit_application(case, actual_billed_cents):
    """Cascade: each POSTED deposit, oldest created_at first, applies up to the
    remaining bill; excess returns as OVERPAYMENT; zero-applied deposits refund
    in full."""
    posted = [d for d in case_deposits(case["id"]) if d["status"] == "POSTED"]
    posted.sort(key=lambda d: (d["created_at"], d["_seq"]))
    remaining = actual_billed_cents
    for dep in posted:
        applied = min(dep["amount_cents"], remaining)
        if applied == 0:
            dep["status"] = "REFUNDED"
            dep["applied_amount_cents"] = 0
            dep["refund_amount_cents"] = dep["amount_cents"]
            dep["refund_reason"] = "OVERPAYMENT"
        else:
            dep["status"] = "APPLIED"
            dep["applied_amount_cents"] = applied
            excess = dep["amount_cents"] - applied
            if excess > 0:
                dep["refund_amount_cents"] = excess
                dep["refund_reason"] = "OVERPAYMENT"
        remaining -= applied
        touch(dep)


# ---------------------------------------------------------------------------
# case cancellation cascade (PRD 3.9)
# ---------------------------------------------------------------------------

def cancel_case_cascade(case):
    for est in case_estimates(case["id"]):
        if est["status"] in ("DRAFT", "PRICED", "PRESENTED"):
            est["status"] = "CANCELLED"
            touch(est)
    for dep in case_deposits(case["id"]):
        if dep["status"] == "PLEDGED":
            dep["status"] = "CANCELLED"
            touch(dep)
        elif dep["status"] == "POSTED":
            dep["status"] = "REFUNDED"
            dep["refund_amount_cents"] = deposit_refund_amount(dep["amount_cents"], case["service_date"])
            dep["refund_reason"] = "SERVICE_CANCELLED"
            touch(dep)
    for auth in case_authorizations(case["id"]):
        if auth["status"] in ("REQUESTED", "APPEALED"):
            auth["status"] = "WITHDRAWN"
            touch(auth)
    for plan in case_plans(case["id"]):
        if plan["status"] in ("DRAFT", "ACTIVE", "DEFAULTED"):
            plan["status"] = "CANCELLED"
            touch(plan)


# ---------------------------------------------------------------------------
# payment plan schedule + waterfall (PRD 3.8)
# ---------------------------------------------------------------------------

def build_installments(principal_cents, num_installments):
    base = principal_cents // num_installments  # floor division, truncated
    installments = []
    for seq in range(1, num_installments + 1):
        if seq < num_installments:
            amount = base
        else:
            amount = principal_cents - (num_installments - 1) * base
        installments.append({
            "seq": seq,
            "due_date": None,
            "amount_cents": amount,
            "paid_cents": 0,
            "status": "PENDING",
        })
    return base, installments


def fix_due_dates(plan, activation_date):
    first = activation_date + timedelta(days=FIRST_DUE_DAYS)
    due = first
    for inst in plan["installments"]:
        inst["due_date"] = due.isoformat()
        due = add_calendar_month(due)


def plan_outstanding(plan):
    return plan["principal_cents"] - sum(i["paid_cents"] for i in plan["installments"])


def apply_payment_waterfall(plan, amount_cents):
    """Apply to installments in due_date ASC, seq ASC order."""
    remaining = amount_cents
    for inst in sorted(plan["installments"], key=lambda i: (i["due_date"], i["seq"])):
        if remaining <= 0:
            break
        take = min(remaining, inst["amount_cents"] - inst["paid_cents"])
        if take > 0:
            inst["paid_cents"] += take
            if inst["paid_cents"] == inst["amount_cents"]:
                inst["status"] = "PAID"
            remaining -= take
    plan["principal_outstanding_cents"] = plan_outstanding(plan)


def past_due_unpaid(plan, current_date):
    total = 0
    for inst in plan["installments"]:
        if inst["due_date"] is not None and inst["due_date"] < current_date.isoformat():
            total += inst["amount_cents"] - inst["paid_cents"]
    return total


def missed_payment_count(plan, current_date):
    today_s = current_date.isoformat()
    return sum(
        1 for i in plan["installments"]
        if i["status"] == "PENDING" and i["due_date"] is not None and i["due_date"] < today_s
    )


# ---------------------------------------------------------------------------
# logical-clock sweep (PRD 2.4 / 3.x)
# ---------------------------------------------------------------------------

def run_sweep():
    """Apply all four time-driven transition families; return counts."""
    now = now_dt()
    today_d = today()
    counts = {
        "staled_snapshots": 0,
        "expired_authorizations": 0,
        "expired_estimates": 0,
        "defaulted_plans": 0,
    }

    # snapshots: ACTIVE -> STALE when now strictly > verified_at + 30 days
    for snap in list(db.snapshots.values()):
        if snap["status"] != "ACTIVE":
            continue
        verified = parse_datetime_value(snap["verified_at"])
        if now > verified + timedelta(days=SNAPSHOT_TTL_DAYS):
            snap["status"] = "STALE"
            touch(snap)
            counts["staled_snapshots"] += 1

    # authorizations: APPROVED -> EXPIRED when current date strictly after valid_to
    affected_cases = set()
    for auth in list(db.authorizations.values()):
        if auth["status"] == "APPROVED" and auth["valid_to"] is not None \
                and today_d > parse_datetime_value(auth["valid_to"]).date():
            auth["status"] = "EXPIRED"
            touch(auth)
            counts["expired_authorizations"] += 1
            affected_cases.add(auth["case_id"])
    for case_id in affected_cases:
        case = db.cases.get(case_id)
        if case is None:
            continue
        recompute_case(case)
        regress_case_if_cleared(case)
        touch(case)

    # estimates: PRESENTED -> EXPIRED when current date strictly after service_date
    for est in list(db.estimates.values()):
        if est["status"] != "PRESENTED":
            continue
        case = db.cases.get(est["case_id"])
        if case is None:
            continue
        if today_d > parse_datetime_value(case["service_date"]).date():
            est["status"] = "EXPIRED"
            touch(est)
            counts["expired_estimates"] += 1
            sync_case(case)

    # payment plans: ACTIVE -> DEFAULTED when any installment is PENDING more
    # than 14 days past due (due_date + 14 strictly before current date)
    for plan in list(db.plans.values()):
        if plan["status"] != "ACTIVE":
            continue
        defaulted = False
        for inst in plan["installments"]:
            if inst["status"] == "PENDING" and inst["due_date"] is not None:
                due = parse_datetime_value(inst["due_date"]).date()
                if due + timedelta(days=DEFAULT_GRACE_DAYS) < today_d:
                    defaulted = True
                    break
        if defaulted:
            plan["status"] = "DEFAULTED"
            touch(plan)
            counts["defaulted_plans"] += 1

    return counts
