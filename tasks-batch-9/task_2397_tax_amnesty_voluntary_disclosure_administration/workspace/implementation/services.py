"""Derived-field maintenance, serializers and the multi-row cascades.

Derived counters (PRD 2.9) are recomputed from their definitions rather than
stored as free-standing state, so they can never drift.  Stateful money fields
on an agreement (which breach zeroes and rescission restores) are stored.
"""

import calc
import clock
import db
from errors import err

WAIVER_QUALIFYING = ("FILED", "ASSESSED", "SETTLED")
TOTAL_QUALIFYING = ("FILED", "ASSESSED", "SETTLED", "REINSTATED")
PARTICIPANT_STATUSES = ("EXECUTED", "FULFILLED", "BREACHED", "SUPERSEDED")
WAIVED_TOTAL_STATUSES = ("EXECUTED", "FULFILLED", "SUPERSEDED")
ADJUSTED_AGREEMENT_STATUSES = ("EXECUTED", "FULFILLED", "SUPERSEDED")


# =============================================================================
# collection helpers
# =============================================================================
def program_terms(program_id):
    return db.ordered([t for t in db.tax_type_terms.values() if t["program_id"] == program_id])


def find_term(program_id, tax_type):
    for term in program_terms(program_id):
        if term["tax_type"] == tax_type:
            return term
    return None


def terms_for_tax_type(program_id, tax_type):
    return [t for t in program_terms(program_id) if t["tax_type"] == tax_type]


def program_agreements(program_id):
    return db.ordered([a for a in db.agreements.values() if a["program_id"] == program_id])


def program_pre_clearances(program_id):
    return db.ordered([p for p in db.pre_clearances.values() if p["program_id"] == program_id])


def agreement_returns(agreement_id):
    return db.ordered([r for r in db.returns.values() if r["agreement_id"] == agreement_id])


def agreement_plans(agreement_id):
    return db.ordered([p for p in db.payment_plans.values() if p["agreement_id"] == agreement_id])


def agreement_payments(agreement_id):
    return db.ordered([p for p in db.payments.values() if p["agreement_id"] == agreement_id])


def plan_installments(plan_id):
    rows = [i for i in db.installments.values() if i["payment_plan_id"] == plan_id]
    return sorted(rows, key=lambda r: r["seq_index"])


def active_plan(agreement_id):
    for plan in agreement_plans(agreement_id):
        if plan["status"] == "ACTIVE":
            return plan
    return None


def taxpayer_agreements(taxpayer_id):
    return db.ordered([a for a in db.agreements.values() if a["taxpayer_id"] == taxpayer_id])


def taxpayer_cases(taxpayer_id):
    return db.ordered([c for c in db.enforcement_cases.values() if c["taxpayer_id"] == taxpayer_id])


def taxpayer_actions(taxpayer_id):
    return db.ordered([a for a in db.enforcement_actions.values() if a["taxpayer_id"] == taxpayer_id])


def program_of(agreement):
    return db.programs.get(agreement["program_id"])


def agreement_of_return(ret):
    return db.agreements.get(ret["agreement_id"])


# =============================================================================
# AmnestyProgram derived counters (PRD 2.9)
# =============================================================================
def program_collected_cents(program):
    agreement_ids = {a["id"] for a in program_agreements(program["id"])}
    total = 0
    for payment in db.payments.values():
        if payment["status"] == "APPLIED" and payment["agreement_id"] in agreement_ids:
            total += payment["amount_cents"]
    return total


def program_waived_total_cents(program):
    return sum(a["waived_amount_cents"] for a in program_agreements(program["id"])
               if a["status"] in WAIVED_TOTAL_STATUSES)


def program_reinstated_total_cents(program):
    return sum(a["reinstated_amount_cents"] for a in program_agreements(program["id"])
               if a["status"] == "BREACHED")


def program_participant_ids(program):
    return {a["taxpayer_id"] for a in program_agreements(program["id"])
            if a["status"] in PARTICIPANT_STATUSES}


def program_participant_count(program):
    return len(program_participant_ids(program))


def program_nonparticipant_count(program):
    return len(program["_nonparticipant_ids"])


def program_revenue_realization(program):
    collected = program_collected_cents(program)
    pct = calc.realization_pct(collected, program["revenue_forecast_cents"])
    participants = [db.taxpayers[tid] for tid in program_participant_ids(program)
                    if tid in db.taxpayers]
    participants.sort(key=lambda t: (t["created_at"], t["_seq"]))
    historical = [historical_score(t) for t in participants]
    adjusted = [program_adjusted_score(t, program["id"]) for t in participants]
    return {
        "collected_cents": collected,
        "revenue_forecast_cents": program["revenue_forecast_cents"],
        "realization_pct": float(pct),
        "forecast_status": calc.forecast_status(pct),
        "waived_total_cents": program_waived_total_cents(program),
        "reinstated_total_cents": program_reinstated_total_cents(program),
        "participant_count": len(participants),
        "nonparticipant_count": program_nonparticipant_count(program),
        "avg_historical_score": calc.mean_score(historical),
        "avg_program_adjusted_score": calc.mean_score(adjusted),
    }


# =============================================================================
# Taxpayer derived counters and scores
# =============================================================================
def open_case_count(taxpayer_id):
    return sum(1 for c in taxpayer_cases(taxpayer_id) if c["status"] == "OPEN")


def referred_case_count(taxpayer_id):
    return sum(1 for c in taxpayer_cases(taxpayer_id) if c["status"] == "REFERRED")


def open_action_count(taxpayer_id):
    return sum(1 for a in taxpayer_actions(taxpayer_id) if a["status"] == "ISSUED")


def taxpayer_returns(taxpayer_id):
    rows = []
    for agreement in taxpayer_agreements(taxpayer_id):
        rows.extend(agreement_returns(agreement["id"]))
    return rows


def nonfiler_period_count(taxpayer_id):
    return sum(1 for r in taxpayer_returns(taxpayer_id)
               if r["is_nonfiler_period"] and r["status"] in TOTAL_QUALIFYING)


def fulfilled_agreement_count(taxpayer_id):
    return sum(1 for a in taxpayer_agreements(taxpayer_id) if a["status"] == "FULFILLED")


def escalation_tier(taxpayer):
    if taxpayer["nonparticipant_flag"] and open_case_count(taxpayer["id"]) >= calc.T2_MIN_OPEN_CASES:
        return "T2"
    if taxpayer["nonparticipant_flag"]:
        return "T1"
    return "T0"


def historical_score(taxpayer):
    taxpayer_id = taxpayer["id"]
    score = calc.SCORE_BASE
    score -= calc.OPEN_CASE_PENALTY * open_case_count(taxpayer_id)
    score -= calc.REFERRED_CASE_PENALTY * referred_case_count(taxpayer_id)
    score -= calc.NONFILER_PERIOD_PENALTY * nonfiler_period_count(taxpayer_id)
    score -= calc.NONPARTICIPANT_PENALTY * (1 if taxpayer["nonparticipant_flag"] else 0)
    score -= calc.ISSUED_ACTION_PENALTY * open_action_count(taxpayer_id)
    score += calc.FULFILLED_AGREEMENT_CREDIT * fulfilled_agreement_count(taxpayer_id)
    return calc.clamp_score(score)


def _adjusted_agreements(taxpayer_id, program_id):
    rows = []
    for agreement in taxpayer_agreements(taxpayer_id):
        if agreement["status"] not in ADJUSTED_AGREEMENT_STATUSES:
            continue
        if program_id is not None and agreement["program_id"] != program_id:
            continue
        rows.append(agreement)
    return rows


def forgiven_nonfiler_period_count(taxpayer_id, program_id):
    forgiven = 0
    for agreement in _adjusted_agreements(taxpayer_id, program_id):
        start = agreement["lookback_start_date"]
        for ret in agreement_returns(agreement["id"]):
            if ret["is_nonfiler_period"] and ret["period_start_date"] >= start:
                forgiven += 1
    return forgiven


def program_adjusted_score(taxpayer, program_id):
    taxpayer_id = taxpayer["id"]
    score = historical_score(taxpayer)
    score += calc.NONFILER_PERIOD_PENALTY * forgiven_nonfiler_period_count(taxpayer_id, program_id)
    if _adjusted_agreements(taxpayer_id, program_id):
        score += calc.PROGRAM_PARTICIPATION_CREDIT
    return calc.clamp_score(score)


def compliance_behavior_report(taxpayer):
    taxpayer_id = taxpayer["id"]
    return {
        "taxpayer_id": taxpayer_id,
        "historical_score": historical_score(taxpayer),
        "program_adjusted_score": program_adjusted_score(taxpayer, None),
        "open_case_count": open_case_count(taxpayer_id),
        "referred_case_count": referred_case_count(taxpayer_id),
        "nonfiler_period_count": nonfiler_period_count(taxpayer_id),
        "forgiven_nonfiler_period_count": forgiven_nonfiler_period_count(taxpayer_id, None),
        "open_enforcement_action_count": open_action_count(taxpayer_id),
        "nonparticipant_flag": taxpayer["nonparticipant_flag"],
        "escalation_tier": escalation_tier(taxpayer),
    }


# =============================================================================
# Agreement money: waiver resolution, rollup, cash
# =============================================================================
def resolve_base_waiver(agreement, basis_return):
    """Step 1 of agreement_effective_waiver_resolution, in precedence order."""
    program = program_of(agreement)
    base_penalty = program["base_penalty_waiver_pct"]
    base_interest = program["base_interest_waiver_pct"]

    if agreement["liability_variant"] == "VDA_NEGOTIATED":
        pre_clearance = db.pre_clearances.get(agreement["pre_clearance_id"])
        if pre_clearance is not None:
            offered_penalty = pre_clearance["current_offer_penalty_waiver_pct"]
            offered_interest = pre_clearance["current_offer_interest_waiver_pct"]
            if offered_penalty is not None:
                base_penalty = offered_penalty
            if offered_interest is not None:
                base_interest = offered_interest
        return base_penalty, base_interest

    term = None
    if basis_return is not None:
        term = db.tax_type_terms.get(basis_return.get("_term_id"))
        if term is None:
            term = find_term(agreement["program_id"], basis_return["tax_type"])
    if term is not None:
        if term["penalty_waiver_pct"] is not None:
            base_penalty = term["penalty_waiver_pct"]
        if term["interest_waiver_pct"] is not None:
            base_interest = term["interest_waiver_pct"]
    return base_penalty, base_interest


def refresh_effective_waiver(agreement, basis_return):
    """Steps 1-4: aggregate pre-waiver gross, select the haircut, apply it."""
    base_penalty, base_interest = resolve_base_waiver(agreement, basis_return)

    gross_liability = 0
    for ret in agreement_returns(agreement["id"]):
        if ret["status"] in WAIVER_QUALIFYING:
            gross_liability += (ret["reported_tax_cents"]
                                + ret["gross_penalty_cents"]
                                + ret["gross_interest_cents"])
    agreement["gross_liability_cents"] = gross_liability

    haircut = calc.haircut_for(gross_liability)
    agreement["haircut_pct"] = calc.pct_out(haircut)

    penalty_pct, interest_pct = calc.effective_waivers(base_penalty, base_interest, haircut)
    agreement["effective_penalty_waiver_pct"] = calc.pct_out(penalty_pct)
    agreement["effective_interest_waiver_pct"] = calc.pct_out(interest_pct)


def waiver_rollup(agreement):
    """Recompute per-return waiver figures and the agreement rollups.

    Returns the list of returns whose stored figures actually changed, so the
    caller can advance exactly those versions (PRD 2.9).
    """
    penalty_pct = calc.dec(agreement["effective_penalty_waiver_pct"])
    interest_pct = calc.dec(agreement["effective_interest_waiver_pct"])
    revised = []
    waived_total = 0

    for ret in agreement_returns(agreement["id"]):
        if ret["status"] not in WAIVER_QUALIFYING:
            continue
        waived_penalty = calc.rhu_cents(calc.dec(ret["gross_penalty_cents"]) * penalty_pct)
        waived_interest = calc.rhu_cents(calc.dec(ret["gross_interest_cents"]) * interest_pct)
        payable_penalty = ret["gross_penalty_cents"] - waived_penalty
        payable_interest = ret["gross_interest_cents"] - waived_interest
        balance_due = ret["reported_tax_cents"] + payable_penalty + payable_interest
        changed = (ret["waived_penalty_cents"] != waived_penalty
                   or ret["waived_interest_cents"] != waived_interest
                   or ret["payable_penalty_cents"] != payable_penalty
                   or ret["payable_interest_cents"] != payable_interest
                   or ret["balance_due_cents"] != balance_due)
        ret["waived_penalty_cents"] = waived_penalty
        ret["waived_interest_cents"] = waived_interest
        ret["payable_penalty_cents"] = payable_penalty
        ret["payable_interest_cents"] = payable_interest
        ret["balance_due_cents"] = balance_due
        waived_total += waived_penalty + waived_interest
        if changed:
            revised.append(ret)

    agreement["waived_amount_cents"] = waived_total
    recompute_total_due(agreement)
    return revised


def recompute_total_due(agreement):
    agreement["total_due_cents"] = sum(r["balance_due_cents"] for r in agreement_returns(agreement["id"])
                                       if r["status"] in TOTAL_QUALIFYING)


def recompute_paid_total(agreement):
    agreement["paid_total_cents"] = sum(p["amount_cents"] for p in agreement_payments(agreement["id"])
                                        if p["status"] == "APPLIED")


def recompute_payment_status(agreement):
    """The second, independent state dimension; four tests in order."""
    if agreement["paid_total_cents"] >= agreement["total_due_cents"]:
        agreement["payment_status"] = "PAID_IN_FULL"
        return
    for plan in agreement_plans(agreement["id"]):
        if plan["status"] == "DEFAULTED":
            agreement["payment_status"] = "DELINQUENT"
            return
    if agreement["paid_total_cents"] > 0:
        agreement["payment_status"] = "PARTIAL"
        return
    agreement["payment_status"] = "UNPAID"


# =============================================================================
# Eligibility screens
# =============================================================================
def open_criminal_case(taxpayer_id):
    for case in taxpayer_cases(taxpayer_id):
        if case["status"] == "OPEN" and case["case_type"] == "CRIMINAL_INVESTIGATION":
            return case
    return None


def open_audit_case(taxpayer_id, tax_types):
    for case in taxpayer_cases(taxpayer_id):
        if (case["status"] == "OPEN"
                and case["case_type"] in ("FIELD_AUDIT", "DESK_AUDIT")
                and case["tax_type"] in tax_types):
            return case
    return None


def check_program_eligibility(taxpayer_id, tax_types):
    """Precedence rules 19 then 20."""
    if open_criminal_case(taxpayer_id) is not None:
        raise err("ERR_TAXPAYER_UNDER_CRIMINAL_INVESTIGATION")
    if open_audit_case(taxpayer_id, tax_types) is not None:
        raise err("ERR_TAXPAYER_UNDER_AUDIT_FOR_TAX_TYPE")


def check_window_live(program):
    """Precedence rule 23 for the participation endpoints."""
    now = clock.now()
    if now >= program["_close_dt"]:
        raise err("ERR_PROGRAM_WINDOW_CLOSED")
    if now < program["_open_dt"]:
        raise err("ERR_PROGRAM_WINDOW_NOT_OPEN")


def check_program_open(program):
    if program["status"] != "OPEN":
        raise err("ERR_PROGRAM_NOT_OPEN")


# =============================================================================
# Cascades
# =============================================================================
def close_program_cascade(program):
    """PRD 3.8: the primary chain (4 hops) then the secondary chain (2 hops)."""
    program["status"] = "CLOSED"
    program["closed_at"] = clock.now_iso()
    db.touch(program)

    touched_taxpayers = []
    for request_row in program_pre_clearances(program["id"]):
        if request_row["status"] not in ("SUBMITTED", "UNDER_REVIEW", "TERMS_OFFERED", "COUNTERED"):
            continue
        request_row["status"] = "EXPIRED"
        db.touch(request_row)
        taxpayer_id = request_row["disclosed_taxpayer_id"]
        if not taxpayer_id:
            continue
        taxpayer = db.taxpayers.get(taxpayer_id)
        if taxpayer is None:
            continue
        taxpayer["nonparticipant_flag"] = True
        program["_nonparticipant_ids"].add(taxpayer_id)
        if taxpayer_id not in [t["id"] for t in touched_taxpayers]:
            touched_taxpayers.append(taxpayer)

    # hops 3 and 4 read escalation_tier / compliance_behavior_score, which are
    # resolved from their definitions on read; the touched rows still version.
    for taxpayer in touched_taxpayers:
        db.touch(taxpayer)

    for agreement in program_agreements(program["id"]):
        if agreement["status"] != "DRAFTED":
            continue
        agreement["status"] = "LAPSED"
        db.touch(agreement)
        for ret in agreement_returns(agreement["id"]):
            if ret["status"] == "DRAFT":
                ret["status"] = "VOIDED"
                db.touch(ret)


def declare_breach_cascade(agreement, breach_reason):
    """PRD 3.7: five hops in order."""
    agreement["status"] = "BREACHED"
    agreement["breach_reason"] = breach_reason

    # hop 1
    qualifying = [r for r in agreement_returns(agreement["id"]) if r["status"] in WAIVER_QUALIFYING]
    reinstated = sum(r["waived_penalty_cents"] + r["waived_interest_cents"] for r in qualifying)
    agreement["reinstated_amount_cents"] = reinstated
    agreement["waived_amount_cents"] = 0

    # hop 2
    for ret in qualifying:
        ret["payable_penalty_cents"] = ret["gross_penalty_cents"]
        ret["payable_interest_cents"] = ret["gross_interest_cents"]
        ret["waived_penalty_cents"] = 0
        ret["waived_interest_cents"] = 0
        ret["balance_due_cents"] = (ret["reported_tax_cents"]
                                    + ret["payable_penalty_cents"]
                                    + ret["payable_interest_cents"])
        ret["status"] = "REINSTATED"
        db.touch(ret)
    recompute_total_due(agreement)

    # hop 3
    plan = active_plan(agreement["id"])
    if plan is not None and agreement["total_due_cents"] > (agreement["down_payment_applied_cents"]
                                                            + plan["scheduled_total_cents"]):
        plan["status"] = "DEFAULTED"
        plan["default_reason"] = "BREACH_CASCADE"
        db.touch(plan)
        for installment in plan_installments(plan["id"]):
            if installment["status"] in ("SCHEDULED", "LATE"):
                installment["status"] = "VOIDED"
                db.touch(installment)
        agreement["payment_status"] = "DELINQUENT"

    # hop 4 — the taxpayer snapshot is taken before hop 5 runs
    taxpayer = db.taxpayers.get(agreement["taxpayer_id"])
    program = program_of(agreement)
    tier = escalation_tier(taxpayer)
    score = historical_score(taxpayer)
    multiplier = program["post_program_penalty_multiplier"] if taxpayer["nonparticipant_flag"] else 1.00
    adjustment = calc.BEHAVIOR_ADJUSTMENT_RATE if score < calc.BEHAVIOR_SCORE_FLOOR else calc.dec(0)
    penalty = calc.post_program_penalty(reinstated, tier, adjustment, multiplier)
    db.insert(db.enforcement_actions, {
        "taxpayer_id": taxpayer["id"],
        "program_id": program["id"],
        "agreement_id": agreement["id"],
        "action_type": "ASSESSMENT",
        "base_tax_cents": reinstated,
        "escalation_tier_applied": tier,
        "multiplier_applied": float(calc.dec(multiplier)),
        "behavior_adjustment_applied": calc.pct_out(adjustment),
        "assessed_penalty_cents": penalty,
        "status": "ISSUED",
        "origin": "BREACH_CASCADE",
        "created_by_user_id": None,
        "issued_by_user_id": "SYSTEM",
        "issued_at": clock.now_iso(),
        "abatement_reason": None,
    })

    # hop 5 and the program rollups are derived on read.
    db.touch(agreement)


def rescind_breach_cascade(agreement):
    """PRD 3.7: an exact compensation of the breach cascade, in four hops."""
    agreement["status"] = "EXECUTED"
    agreement["breach_reason"] = None

    # hop 1 + hop 2 — restore the waiver first, then decide each return's state
    reinstated_returns = [r for r in agreement_returns(agreement["id"]) if r["status"] == "REINSTATED"]
    for ret in reinstated_returns:
        ret["status"] = "FILED"
    waiver_rollup(agreement)
    agreement["reinstated_amount_cents"] = 0
    paid_in_full = agreement["paid_total_cents"] >= agreement["total_due_cents"]
    for ret in reinstated_returns:
        ret["status"] = "SETTLED" if paid_in_full else "FILED"
        db.touch(ret)

    # hop 3 — only plans the cascade itself defaulted come back
    restored_any = False
    for plan in agreement_plans(agreement["id"]):
        if plan["status"] != "DEFAULTED" or plan["default_reason"] != "BREACH_CASCADE":
            continue
        plan["status"] = "ACTIVE"
        plan["default_reason"] = None
        db.touch(plan)
        restored_any = True
        for installment in plan_installments(plan["id"]):
            if installment["status"] == "VOIDED":
                installment["status"] = "SCHEDULED"
                db.touch(installment)
    if restored_any:
        recompute_payment_status(agreement)

    # hop 4
    for action in db.ordered(list(db.enforcement_actions.values())):
        if (action["agreement_id"] == agreement["id"]
                and action["origin"] == "BREACH_CASCADE"
                and action["status"] == "ISSUED"):
            action["status"] = "ABATED"
            action["abatement_reason"] = "BREACH_RESCINDED"
            db.touch(action)

    db.touch(agreement)


def default_plan(plan, agreement, default_reason):
    """Shared by the auditor's motion and the sweep."""
    plan["status"] = "DEFAULTED"
    plan["default_reason"] = default_reason
    db.touch(plan)
    defaulted = 0
    for installment in plan_installments(plan["id"]):
        if installment["status"] in ("SCHEDULED", "LATE"):
            installment["status"] = "DEFAULTED"
            db.touch(installment)
            defaulted += 1
    agreement["payment_status"] = "DELINQUENT"
    db.touch(agreement)
    return defaulted


def installment_sweep(program):
    """PRD 3.6: three steps, program-scoped."""
    today = clock.today()
    agreement_ids = {a["id"] for a in program_agreements(program["id"])}
    plans = [p for p in db.ordered(list(db.payment_plans.values()))
             if p["agreement_id"] in agreement_ids]

    marked_late = 0
    defaulted_installments = 0
    defaulted_plans = 0

    # step 1
    for plan in plans:
        for installment in plan_installments(plan["id"]):
            if installment["status"] != "SCHEDULED":
                continue
            if clock.parse_date(installment["due_date"]) < today:
                installment["status"] = "LATE"
                db.touch(installment)
                marked_late += 1

    # steps 2 and 3
    for plan in plans:
        if plan["status"] != "ACTIVE":
            continue
        expired = [i for i in plan_installments(plan["id"])
                   if i["status"] == "LATE"
                   and clock.parse_date(i["due_date"])
                   + _grace() < today]
        if not expired:
            continue
        for installment in expired:
            installment["status"] = "DEFAULTED"
            db.touch(installment)
            defaulted_installments += 1
        plan["status"] = "DEFAULTED"
        plan["default_reason"] = "SWEEP_GRACE_EXPIRED"
        db.touch(plan)
        defaulted_plans += 1
        for installment in plan_installments(plan["id"]):
            if installment["status"] in ("SCHEDULED", "LATE"):
                installment["status"] = "DEFAULTED"
                db.touch(installment)
                defaulted_installments += 1
        agreement = db.agreements.get(plan["agreement_id"])
        if agreement is not None:
            agreement["payment_status"] = "DELINQUENT"
            db.touch(agreement)

    return {
        "marked_late_count": marked_late,
        "defaulted_installment_count": defaulted_installments,
        "defaulted_plan_count": defaulted_plans,
    }


def _grace():
    from datetime import timedelta
    return timedelta(days=calc.INSTALLMENT_GRACE_DAYS_LATE)


def apply_payment(agreement, payment):
    """payment_waterfall_allocation plus its two downstream cascades."""
    remaining = payment["amount_cents"]
    allocations = []
    plan = active_plan(agreement["id"])

    if plan is not None:
        for installment in plan_installments(plan["id"]):
            if remaining <= 0:
                break
            if installment["status"] in ("PAID", "VOIDED", "DEFAULTED"):
                continue
            take = min(remaining, installment["amount_cents"] - installment["paid_cents"])
            if take > 0:
                installment["paid_cents"] += take
                allocations.append({"installment_id": installment["id"], "amount_cents": take})
                remaining -= take
                if installment["paid_cents"] >= installment["amount_cents"]:
                    installment["status"] = "PAID"
                db.touch(installment)

    payment["allocations"] = allocations
    payment["unapplied_delta_cents"] = remaining
    agreement["unapplied_credit_cents"] += remaining

    recompute_paid_total(agreement)
    recompute_payment_status(agreement)

    if agreement["paid_total_cents"] >= agreement["total_due_cents"]:
        for ret in agreement_returns(agreement["id"]):
            if ret["status"] == "ASSESSED":
                ret["status"] = "SETTLED"
                db.touch(ret)

    if plan is not None and plan["status"] == "ACTIVE":
        rows = plan_installments(plan["id"])
        if rows and all(i["status"] == "PAID" for i in rows):
            plan["status"] = "COMPLETED"
            db.touch(plan)

    db.touch(agreement)


def reverse_payment(agreement, payment, reversal_reason):
    """The exact inverse of apply_payment."""
    for entry in reversed(payment["allocations"]):
        installment = db.installments.get(entry["installment_id"])
        if installment is None:
            continue
        installment["paid_cents"] -= entry["amount_cents"]
        if installment["status"] == "PAID":
            installment["status"] = "SCHEDULED"
        db.touch(installment)

    agreement["unapplied_credit_cents"] -= payment["unapplied_delta_cents"]
    payment["status"] = "REVERSED"
    payment["reversal_reason"] = reversal_reason

    recompute_paid_total(agreement)
    recompute_payment_status(agreement)

    if agreement["paid_total_cents"] < agreement["total_due_cents"]:
        for ret in agreement_returns(agreement["id"]):
            if ret["status"] != "SETTLED":
                continue
            ret["status"] = "ASSESSED" if ret["assessed_by_user_id"] else "FILED"
            db.touch(ret)

    db.touch(payment)
    db.touch(agreement)


# =============================================================================
# Serializers
# =============================================================================
def _audit(rec, out, versioned=True):
    out["created_at"] = rec["created_at"]
    if versioned:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def program_out(rec):
    return _audit(rec, {
        "id": rec["id"],
        "name": rec["name"],
        "window_open_at": rec["window_open_at"],
        "window_close_at": rec["window_close_at"],
        "lookback_months": rec["lookback_months"],
        "base_penalty_waiver_pct": rec["base_penalty_waiver_pct"],
        "base_interest_waiver_pct": rec["base_interest_waiver_pct"],
        "post_program_penalty_multiplier": rec["post_program_penalty_multiplier"],
        "prospective_compliance_months": rec["prospective_compliance_months"],
        "revenue_forecast_cents": rec["revenue_forecast_cents"],
        "installment_max_count": rec["installment_max_count"],
        "status": rec["status"],
        "closed_at": rec["closed_at"],
        "collected_cents": program_collected_cents(rec),
        "waived_total_cents": program_waived_total_cents(rec),
        "reinstated_total_cents": program_reinstated_total_cents(rec),
        "participant_count": program_participant_count(rec),
        "nonparticipant_count": program_nonparticipant_count(rec),
        "final_realization_pct": rec["final_realization_pct"],
    })


def term_out(rec):
    return _audit(rec, {
        "id": rec["id"],
        "program_id": rec["program_id"],
        "tax_type": rec["tax_type"],
        "eligible_period_start": rec["eligible_period_start"],
        "eligible_period_end": rec["eligible_period_end"],
        "penalty_waiver_pct": rec["penalty_waiver_pct"],
        "interest_waiver_pct": rec["interest_waiver_pct"],
        "min_liability_cents": rec["min_liability_cents"],
        "requires_prior_nonfiler": rec["requires_prior_nonfiler"],
    })


def taxpayer_out(rec):
    return _audit(rec, {
        "id": rec["id"],
        "legal_name": rec["legal_name"],
        "taxpayer_type": rec["taxpayer_type"],
        "tin_last4": rec["tin_last4"],
        "is_registered": rec["is_registered"],
        "open_case_count": open_case_count(rec["id"]),
        "open_enforcement_action_count": open_action_count(rec["id"]),
        "nonfiler_period_count": nonfiler_period_count(rec["id"]),
        "nonparticipant_flag": rec["nonparticipant_flag"],
        "escalation_tier": escalation_tier(rec),
        "compliance_behavior_score": historical_score(rec),
    })


def case_out(rec):
    return _audit(rec, {
        "id": rec["id"],
        "taxpayer_id": rec["taxpayer_id"],
        "case_type": rec["case_type"],
        "tax_type": rec["tax_type"],
        "opened_at": rec["opened_at"],
        "status": rec["status"],
        "closed_at": rec["closed_at"],
        "opened_by_user_id": rec["opened_by_user_id"],
    })


def representative_out(rec):
    return _audit(rec, {
        "id": rec["id"],
        "firm_name": rec["firm_name"],
        "bar_number": rec["bar_number"],
        "status": rec["status"],
    })


def pre_clearance_out(rec):
    return _audit(rec, {
        "id": rec["id"],
        "program_id": rec["program_id"],
        "representative_id": rec["representative_id"],
        "disclosed_taxpayer_id": rec["disclosed_taxpayer_id"],
        "tax_type": rec["tax_type"],
        "anonymous_alias": rec["anonymous_alias"],
        "estimated_liability_cents": rec["estimated_liability_cents"],
        "self_reported_under_audit": rec["self_reported_under_audit"],
        "earliest_unfiled_period_start": rec["earliest_unfiled_period_start"],
        "status": rec["status"],
        "screening_result": rec["screening_result"],
        "rejection_reason": rec["rejection_reason"],
        "round_index": rec["round_index"],
        "counter_count": rec["counter_count"],
        "current_offer_lookback_months": rec["current_offer_lookback_months"],
        "current_offer_penalty_waiver_pct": rec["current_offer_penalty_waiver_pct"],
        "current_offer_interest_waiver_pct": rec["current_offer_interest_waiver_pct"],
        "last_offer_officer_user_id": rec["last_offer_officer_user_id"],
    })


def round_out(rec):
    # A negotiation round is append-only: id and created_at only, no version.
    return _audit(rec, {
        "id": rec["id"],
        "pre_clearance_id": rec["pre_clearance_id"],
        "round_index": rec["round_index"],
        "proposed_by": rec["proposed_by"],
        "lookback_months": rec["lookback_months"],
        "penalty_waiver_pct": rec["penalty_waiver_pct"],
        "interest_waiver_pct": rec["interest_waiver_pct"],
        "note": rec["note"],
        "actor_user_id": rec["actor_user_id"],
    }, versioned=False)


def agreement_out(rec):
    return _audit(rec, {
        "id": rec["id"],
        "program_id": rec["program_id"],
        "taxpayer_id": rec["taxpayer_id"],
        "pre_clearance_id": rec["pre_clearance_id"],
        "amends_agreement_id": rec["amends_agreement_id"],
        "tax_types": list(rec["tax_types"]),
        "lookback_start_date": rec["lookback_start_date"],
        "lookback_end_date": rec["lookback_end_date"],
        "prospective_compliance_months": rec["prospective_compliance_months"],
        "liability_variant": rec["liability_variant"],
        "status": rec["status"],
        "payment_status": rec["payment_status"],
        "gross_liability_cents": rec["gross_liability_cents"],
        "haircut_pct": rec["haircut_pct"],
        "effective_penalty_waiver_pct": rec["effective_penalty_waiver_pct"],
        "effective_interest_waiver_pct": rec["effective_interest_waiver_pct"],
        "waived_amount_cents": rec["waived_amount_cents"],
        "reinstated_amount_cents": rec["reinstated_amount_cents"],
        "total_due_cents": rec["total_due_cents"],
        "paid_total_cents": rec["paid_total_cents"],
        "unapplied_credit_cents": rec["unapplied_credit_cents"],
        "down_payment_applied_cents": rec["down_payment_applied_cents"],
        "drafted_by_user_id": rec["drafted_by_user_id"],
        "executed_by_user_id": rec["executed_by_user_id"],
        "executed_at": rec["executed_at"],
        "compliance_due_at": rec["compliance_due_at"],
        "breach_reason": rec["breach_reason"],
    })


def return_out(rec):
    return _audit(rec, {
        "id": rec["id"],
        "agreement_id": rec["agreement_id"],
        "tax_type": rec["tax_type"],
        "period_start_date": rec["period_start_date"],
        "period_end_date": rec["period_end_date"],
        "original_due_date": rec["original_due_date"],
        "reported_tax_cents": rec["reported_tax_cents"],
        "is_nonfiler_period": rec["is_nonfiler_period"],
        "accrual_end_date": rec["accrual_end_date"],
        "days_late": rec["days_late"],
        "penalty_rate_applied": rec["penalty_rate_applied"],
        "gross_penalty_cents": rec["gross_penalty_cents"],
        "gross_interest_cents": rec["gross_interest_cents"],
        "waived_penalty_cents": rec["waived_penalty_cents"],
        "waived_interest_cents": rec["waived_interest_cents"],
        "payable_penalty_cents": rec["payable_penalty_cents"],
        "payable_interest_cents": rec["payable_interest_cents"],
        "balance_due_cents": rec["balance_due_cents"],
        "status": rec["status"],
        "filed_at": rec["filed_at"],
        "assessed_by_user_id": rec["assessed_by_user_id"],
    })


def plan_out(rec):
    return _audit(rec, {
        "id": rec["id"],
        "agreement_id": rec["agreement_id"],
        "plan_type": rec["plan_type"],
        "installment_count": rec["installment_count"],
        "down_payment_cents": rec["down_payment_cents"],
        "scheduled_total_cents": rec["scheduled_total_cents"],
        "status": rec["status"],
        "approved_at": rec["approved_at"],
        "rejection_reason": rec["rejection_reason"],
        "default_reason": rec["default_reason"],
        "proposed_by_user_id": rec["proposed_by_user_id"],
    })


def installment_out(rec):
    return _audit(rec, {
        "id": rec["id"],
        "payment_plan_id": rec["payment_plan_id"],
        "seq_index": rec["seq_index"],
        "due_date": rec["due_date"],
        "amount_cents": rec["amount_cents"],
        "paid_cents": rec["paid_cents"],
        "status": rec["status"],
    })


def payment_out(rec):
    return _audit(rec, {
        "id": rec["id"],
        "agreement_id": rec["agreement_id"],
        "amount_cents": rec["amount_cents"],
        "payment_reference": rec["payment_reference"],
        "received_at": rec["received_at"],
        "status": rec["status"],
        "allocations": [dict(entry) for entry in rec["allocations"]],
        "unapplied_delta_cents": rec["unapplied_delta_cents"],
        "reversal_reason": rec["reversal_reason"],
    })


def action_out(rec):
    return _audit(rec, {
        "id": rec["id"],
        "taxpayer_id": rec["taxpayer_id"],
        "program_id": rec["program_id"],
        "agreement_id": rec["agreement_id"],
        "action_type": rec["action_type"],
        "base_tax_cents": rec["base_tax_cents"],
        "escalation_tier_applied": rec["escalation_tier_applied"],
        "multiplier_applied": rec["multiplier_applied"],
        "behavior_adjustment_applied": rec["behavior_adjustment_applied"],
        "assessed_penalty_cents": rec["assessed_penalty_cents"],
        "status": rec["status"],
        "origin": rec["origin"],
        "created_by_user_id": rec["created_by_user_id"],
        "issued_by_user_id": rec["issued_by_user_id"],
        "issued_at": rec["issued_at"],
        "abatement_reason": rec["abatement_reason"],
    })
