"""Business logic: crediting, tiers, statements, supervision allocation,
reversals, true-up, modeling (PRD section 3; scaffold calculations)."""
from decimal import Decimal

from db import db
from services.core import new_record, touch
from util import (
    dec, f2, round_half_up_decimal, round_half_up_int,
    parse_date_strict, period_str,
)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def plan_of(agreement):
    return db["comp_plans"].get(agreement["plan_id"])


def physician_of(agreement):
    return db["physicians"].get(agreement["physician_id"])


def find_effective_agreement(physician_id, plan_id):
    for a in db["physician_agreements"].values():
        if (a["physician_id"] == physician_id and a["plan_id"] == plan_id
                and a["status"] == "EFFECTIVE"):
            return a
    return None


def resolve_rate(plan_id, cpt_code, service_date):
    """Unique CptRate row covering (cpt_code, service_date) under the half-open
    window [effective_from, effective_to)."""
    sd = parse_date_strict(service_date)
    for r in db["cpt_rates"].values():
        if r["plan_id"] == plan_id and r["cpt_code"] == cpt_code:
            if parse_date_strict(r["effective_from"]) <= sd < parse_date_strict(r["effective_to"]):
                return r
    return None


# ---------------------------------------------------------------------------
# Agreement ledger recomputation (PRD 2.10 bubble-up)
# ---------------------------------------------------------------------------

def recompute_ytd(agreement):
    total = Decimal("0")
    for c in db["production_captures"].values():
        if c["agreement_id"] == agreement["id"] and c["credit_status"] == "CREDITED":
            total += dec(c["credited_wrvu"])
    agreement["ytd_wrvu_credited"] = f2(total)


def recompute_lifetime_paid(agreement):
    agreement["lifetime_paid_cents"] = sum(
        s["net_payment_cents"]
        for s in db["comp_statements"].values()
        if s["agreement_id"] == agreement["id"] and s["status"] == "FINALIZED"
    )


# ---------------------------------------------------------------------------
# Tiered productivity pricing (calculation productivity_payout)
# ---------------------------------------------------------------------------

def tiers_sorted(plan):
    return sorted(plan["tiers"], key=lambda t: dec(t["threshold_wrvu"]))


def tiered_earnings_cents(y_wrvu, tiers, fte) -> int:
    """Marginal tiered earnings on YTD wRVU with fte-prorated thresholds."""
    tiers = sorted(tiers, key=lambda t: dec(t["threshold_wrvu"]))
    Y = dec(y_wrvu)
    F = dec(fte)
    earned = Decimal("0")
    for i, t in enumerate(tiers):
        floor_i = dec(t["threshold_wrvu"]) * F
        cap_i = dec(tiers[i + 1]["threshold_wrvu"]) * F if i + 1 < len(tiers) else None
        upper = Y if cap_i is None else min(Y, cap_i)
        in_tier = upper - floor_i
        if in_tier > 0:
            earned += in_tier * dec(t["conversion_factor_cents"])
    return round_half_up_int(earned)


def tier_attainment(y_wrvu, tiers, fte):
    """(tier_code, rank) of the highest tier whose prorated threshold <= Y."""
    tiers = sorted(tiers, key=lambda t: dec(t["threshold_wrvu"]))
    Y = dec(y_wrvu)
    F = dec(fte)
    rank = 0
    for i, t in enumerate(tiers):
        if dec(t["threshold_wrvu"]) * F <= Y:
            rank = i
    return tiers[rank]["tier_code"], rank


def tier_rank(plan, tier_code):
    for i, t in enumerate(tiers_sorted(plan)):
        if t["tier_code"] == tier_code:
            return i
    return -1


# ---------------------------------------------------------------------------
# Statement computation (calculations productivity_payout + statement_net_settlement)
# ---------------------------------------------------------------------------

def _finalized_periods(agreement_id):
    return {
        period_str(s["period_year"], s["period_month"])
        for s in db["comp_statements"].values()
        if s["agreement_id"] == agreement_id and s["status"] == "FINALIZED"
    }


def ytd_basis(agreement, period) -> Decimal:
    """Locked basis: FINALIZED statements' period_wrvu (frozen) plus live
    CREDITED captures in non-finalized periods <= this period."""
    fin_periods = _finalized_periods(agreement["id"])
    total = Decimal("0")
    for s in db["comp_statements"].values():
        if s["agreement_id"] == agreement["id"] and s["status"] == "FINALIZED":
            total += dec(s["period_wrvu"])
    for c in db["production_captures"].values():
        if (c["agreement_id"] == agreement["id"]
                and c["credit_status"] == "CREDITED"
                and c["credited_period"] is not None
                and c["credited_period"] <= period
                and c["credited_period"] not in fin_periods):
            total += dec(c["credited_wrvu"])
    return round_half_up_decimal(total, 2)


def _tier_bonus(agreement, plan, attained_rank, year, month) -> int:
    """Flat bonus of the attained tier, paid only if no prior non-VOIDED
    statement attained the same or a higher tier; else 0."""
    for s in db["comp_statements"].values():
        if s["agreement_id"] != agreement["id"] or s["status"] == "VOIDED":
            continue
        if (s["period_year"], s["period_month"]) >= (year, month):
            continue
        if tier_rank(plan, s["tier_attained"]) >= attained_rank:
            return 0
    return int(tiers_sorted(plan)[attained_rank]["tier_bonus_cents"])


def compute_statement_fields(agreement, year, month, trueup_snapshot, draw_snapshot):
    """Pinned evaluation order (statement_net_settlement): the true-up snapshot
    is taken by the caller before this runs; everything else is derived live."""
    plan = plan_of(agreement)
    phys = physician_of(agreement)
    period = period_str(year, month)

    caps = [c for c in db["production_captures"].values()
            if c["agreement_id"] == agreement["id"]
            and c["credit_status"] == "CREDITED"
            and c["credited_period"] == period]
    caps.sort(key=lambda c: (c["created_at"], c["id"]))
    capture_ids = [c["id"] for c in caps]
    period_wrvu = round_half_up_decimal(
        sum((dec(c["credited_wrvu"]) for c in caps), Decimal("0")), 2)

    Y = ytd_basis(agreement, period)
    fte = phys["fte"]
    earned_ytd = tiered_earnings_cents(Y, plan["tiers"], fte)
    code, rank = tier_attainment(Y, plan["tiers"], fte)
    bonus = _tier_bonus(agreement, plan, rank, year, month)
    prior_prod = sum(
        s["period_productivity_cents"]
        for s in db["comp_statements"].values()
        if s["agreement_id"] == agreement["id"] and s["status"] != "VOIDED"
        and (s["period_year"], s["period_month"]) < (year, month)
    )
    period_productivity = earned_ytd - prior_prod

    qb = 0
    for sc in db["quality_scorecards"].values():
        if (sc["agreement_id"] == agreement["id"] and sc["period"] == period
                and sc["status"] == "FINALIZED"):
            qb = sc["quality_bonus_cents"]
            break

    net = period_productivity + bonus + qb + trueup_snapshot - draw_snapshot
    return {
        "capture_ids": capture_ids,
        "period_wrvu": float(period_wrvu),
        "ytd_wrvu_at_close": float(Y),
        "tier_attained": code,
        "tier_bonus_cents": bonus,
        "productivity_earned_ytd_cents": earned_ytd,
        "period_productivity_cents": period_productivity,
        "quality_bonus_cents": qb,
        "trueup_adjustment_cents": trueup_snapshot,
        "period_draw_cents": draw_snapshot,
        "net_payment_cents": net,
    }


def refresh_draft_statements(agreement, period):
    """Recompute DRAFT statements whose period matches (reversal cascade)."""
    for s in db["comp_statements"].values():
        if (s["agreement_id"] == agreement["id"] and s["status"] == "DRAFT"
                and period_str(s["period_year"], s["period_month"]) == period):
            fields = compute_statement_fields(
                agreement, s["period_year"], s["period_month"],
                s["trueup_adjustment_cents"], s["period_draw_cents"])
            s.update(fields)
            touch("comp_statements", s)


# ---------------------------------------------------------------------------
# Capture crediting, supervision allocation, reversal (PRD 3.4 / 3.5 / 3.8)
# ---------------------------------------------------------------------------

def credit_capture(capture, agreement, wrvu_applied):
    plan = plan_of(agreement)
    capture["wrvu_value_applied"] = wrvu_applied
    capture["credited_wrvu"] = f2(dec(capture["units"]) * dec(wrvu_applied))
    if plan["credit_attribution_mode"] == "SERVICE_DATE":
        capture["credited_period"] = capture["service_date"][:7]
    else:
        capture["credited_period"] = capture["posting_date"][:7]
    capture["capture_status"] = "VALIDATED"
    capture["credit_status"] = "CREDITED"


def allocate_supervision(app_capture, app_agreement):
    """Waterfall allocation (calculation supervision_credit_allocation):
    per-assignment round_half_up to 2dp, pinned order start_date then created_at,
    no remainder redistribution."""
    phys = physician_of(app_agreement)
    if phys is None or phys["provider_type"] != "APP":
        return
    sd = parse_date_strict(app_capture["service_date"])
    eligible = [
        a for a in db["supervision_assignments"].values()
        if a["app_physician_id"] == phys["id"] and a["status"] == "ACTIVE"
        and parse_date_strict(a["start_date"]) <= sd <= parse_date_strict(a["end_date"])
    ]
    eligible.sort(key=lambda a: (a["start_date"], a["created_at"]))
    for asg in eligible:
        amount = round_half_up_decimal(
            dec(app_capture["credited_wrvu"]) * dec(asg["credit_pct"]), 2)
        sup_agr = find_effective_agreement(asg["supervisor_physician_id"],
                                           app_agreement["plan_id"])
        if sup_agr is None:
            continue
        sup_plan = plan_of(sup_agr)
        if sup_plan["credit_attribution_mode"] == "SERVICE_DATE":
            period = app_capture["service_date"][:7]
        else:
            period = app_capture["posting_date"][:7]
        new_record("production_captures", {
            "agreement_id": sup_agr["id"],
            "capture_kind": "SUPERVISION_CREDIT",
            "cpt_code": "SUPV",
            "units": 1,
            "service_date": app_capture["service_date"],
            "posting_date": app_capture["posting_date"],
            "wrvu_value_applied": None,
            "credited_wrvu": float(amount),
            "credited_period": period,
            "capture_status": "VALIDATED",
            "credit_status": "CREDITED",
            "reversal_of_capture_id": None,
            "source_capture_id": app_capture["id"],
            "reversed_reason": None,
            "created_by_user_id": None,
        })
        recompute_ytd(sup_agr)
        touch("physician_agreements", sup_agr)


def reverse_capture(capture, reason):
    """CREDITED -> REVERSED: ledger recompute, supervision-children reversal,
    DRAFT statement refresh (owning agreement only)."""
    agreement = db["physician_agreements"][capture["agreement_id"]]
    capture["credit_status"] = "REVERSED"
    capture["reversed_reason"] = reason
    touch("production_captures", capture)
    recompute_ytd(agreement)
    touch("physician_agreements", agreement)
    if capture["capture_kind"] == "CLINICAL":
        for child in db["production_captures"].values():
            if (child["source_capture_id"] == capture["id"]
                    and child["credit_status"] == "CREDITED"):
                child["credit_status"] = "REVERSED"
                child["reversed_reason"] = reason
                touch("production_captures", child)
                sup_agr = db["physician_agreements"][child["agreement_id"]]
                recompute_ytd(sup_agr)
                touch("physician_agreements", sup_agr)
    if capture["credited_period"]:
        refresh_draft_statements(agreement, capture["credited_period"])


def create_replacement_capture(orig, agreement, corrected_units, corrected_cpt_code):
    """Replacement CLINICAL capture born VALIDATED/CREDITED (dispute accept from
    DATA_CORRECTION); re-runs supervision allocation for APP physicians."""
    plan = plan_of(agreement)
    units = corrected_units if corrected_units is not None else orig["units"]
    cpt = corrected_cpt_code if corrected_cpt_code is not None else orig["cpt_code"]
    rate = resolve_rate(plan["id"], cpt, orig["service_date"])
    wrvu = rate["wrvu_value"] if rate is not None else None
    repl = new_record("production_captures", {
        "agreement_id": agreement["id"],
        "capture_kind": "CLINICAL",
        "cpt_code": cpt,
        "units": units,
        "service_date": orig["service_date"],
        "posting_date": orig["posting_date"],
        "wrvu_value_applied": wrvu,
        "credited_wrvu": f2(dec(units) * dec(wrvu)) if wrvu is not None else None,
        "credited_period": (orig["service_date"][:7]
                            if plan["credit_attribution_mode"] == "SERVICE_DATE"
                            else orig["posting_date"][:7]),
        "capture_status": "VALIDATED",
        "credit_status": "CREDITED",
        "reversal_of_capture_id": orig["id"],
        "source_capture_id": None,
        "reversed_reason": None,
        "created_by_user_id": None,
    })
    recompute_ytd(agreement)
    touch("physician_agreements", agreement)
    allocate_supervision(repl, agreement)
    if repl["credited_period"]:
        refresh_draft_statements(agreement, repl["credited_period"])
    return repl


def void_statement_cascade(stmt):
    """FINALIZED -> VOIDED: unlock included CREDITED captures, lifetime rollback."""
    for cid in stmt["capture_ids"]:
        c = db["production_captures"].get(cid)
        if c is not None and c["capture_status"] == "LOCKED" and c["credit_status"] == "CREDITED":
            c["capture_status"] = "VALIDATED"
            touch("production_captures", c)
    agreement = db["physician_agreements"][stmt["agreement_id"]]
    recompute_lifetime_paid(agreement)
    touch("physician_agreements", agreement)


def void_draft_statements(agreement):
    """System cascade: DRAFT -> VOIDED (no cash impact)."""
    for s in db["comp_statements"].values():
        if s["agreement_id"] == agreement["id"] and s["status"] == "DRAFT":
            s["status"] = "VOIDED"
            touch("comp_statements", s)


# ---------------------------------------------------------------------------
# Quality bonus (calculation quality_bonus)
# ---------------------------------------------------------------------------

def compute_quality_bonus(plan, measures) -> int:
    total_weight = sum(int(m["weight"]) for m in measures)
    if plan["quality_model"] == "ALL_OR_NOTHING":
        earned = Decimal(sum(
            int(m["weight"]) for m in measures
            if dec(m["score"]) >= dec(m["threshold_score"])
        ))
    else:  # SLIDING_SCALE
        earned = Decimal("0")
        for m in measures:
            thr = dec(m["threshold_score"])
            if thr == 0:
                ratio = Decimal("1")
            else:
                ratio = min(Decimal("1"), dec(m["score"]) / thr)
            earned += dec(m["weight"]) * ratio
    bonus = dec(plan["quality_pool_cents"]) * earned / Decimal(total_weight)
    return round_half_up_int(bonus)


# ---------------------------------------------------------------------------
# True-up variance (calculation trueup_variance)
# ---------------------------------------------------------------------------

def compute_trueup_adjustments(plan, as_of_period):
    ay, am = parse_date_safe_period(as_of_period)
    adjustments = []
    agreements = [a for a in db["physician_agreements"].values()
                  if a["plan_id"] == plan["id"]
                  and a["status"] in ("EFFECTIVE", "AMENDMENT_REQUIRED")]
    agreements.sort(key=lambda a: (a["created_at"], a["id"]))
    for a in agreements:
        closed = [s for s in db["comp_statements"].values()
                  if s["agreement_id"] == a["id"] and s["status"] == "FINALIZED"
                  and (s["period_year"], s["period_month"]) <= (ay, am)]
        closed.sort(key=lambda s: (s["period_year"], s["period_month"]))
        closed_periods = {period_str(s["period_year"], s["period_month"]) for s in closed}
        caps = [c for c in db["production_captures"].values()
                if c["agreement_id"] == a["id"] and c["credit_status"] == "CREDITED"
                and c["credited_period"] in closed_periods]
        caps.sort(key=lambda c: (c["service_date"], c["created_at"]))
        Y = round_half_up_decimal(
            sum((dec(c["credited_wrvu"]) for c in caps), Decimal("0")), 2)
        phys = physician_of(a)
        recomputed = tiered_earnings_cents(Y, plan["tiers"], phys["fte"])
        recognized = sum(s["period_productivity_cents"] for s in closed)
        adjustments.append({
            "agreement_id": a["id"],
            "variance_cents": recomputed - recognized,
        })
    return adjustments


def parse_date_safe_period(period):
    from util import parse_period_strict
    return parse_period_strict(period)


# ---------------------------------------------------------------------------
# Plan-change modeling (calculation plan_change_modeling)
# ---------------------------------------------------------------------------

def compute_modeled_delta(pcr) -> int:
    cur_plan = db["comp_plans"][pcr["plan_id"]]
    suc_plan = db["comp_plans"][pcr["successor_plan_id"]]
    total = 0
    agreements = [a for a in db["physician_agreements"].values()
                  if a["plan_id"] == cur_plan["id"]
                  and a["status"] in ("EFFECTIVE", "AMENDMENT_REQUIRED")]
    agreements.sort(key=lambda a: (a["created_at"], a["id"]))
    for a in agreements:
        fin = [s for s in db["comp_statements"].values()
               if s["agreement_id"] == a["id"] and s["status"] == "FINALIZED"]
        if not fin:
            continue
        avg = sum((dec(s["period_wrvu"]) for s in fin), Decimal("0")) / Decimal(len(fin))
        annualized = avg * Decimal(12)
        fte = physician_of(a)["fte"]
        proj_current = tiered_earnings_cents(annualized, cur_plan["tiers"], fte)
        proj_successor = tiered_earnings_cents(annualized, suc_plan["tiers"], fte)
        total += proj_successor - proj_current
    return total


# ---------------------------------------------------------------------------
# FMV cap projection (validation 30)
# ---------------------------------------------------------------------------

def projected_annual_productivity_cents(agreement, plan, phys, clock_today) -> int:
    from util import months_elapsed
    months = months_elapsed(parse_date_strict(agreement["effective_date"]), clock_today)
    if months <= 0:
        months = 1
    ytd = dec(agreement["ytd_wrvu_credited"])
    annualized = ytd * Decimal(12) / Decimal(months)
    return tiered_earnings_cents(annualized, plan["tiers"], phys["fte"])
