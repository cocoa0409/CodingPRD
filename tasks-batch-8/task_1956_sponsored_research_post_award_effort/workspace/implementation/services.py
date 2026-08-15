"""Business-logic services: calculation rules (scaffold 1.3) and cascades.

Covers: salary_charge_with_cap, fringe_benefit_charge, fringe_trueup_adjustment,
mtdc_base_aggregation, f_and_a_accrual, drawdown_eligible_pool, receivable aging
and late interest, effort_charged_percentage, cost_transfer_timeliness,
closeout residuals, award_posture_derivation, and the FROZEN drawdown cascade.
"""
from decimal import Decimal

from db import STORES, now_clock, touch
from util import D, add_days, rhu, rhu2, whole_days

SUBAWARD_MTDC_CAP = 2500000            # 25,000 USD in cents
RETROACTIVE_DAYS = 90                  # exactly 90 days is timely
FFR_DUE_DAYS = 120
FINAL_REPORT_GRACE_DAYS = 30
GRACE_DAYS = 60
DAYS_PER_YEAR = 365
SIGNIFICANCE_PCT = 25
VARIANCE_TOLERANCE = Decimal("5.00")
KEY_FLOOR = Decimal("0.75")


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def award_lines(award_id):
    return [l for l in STORES["budget_lines"].values() if l["award_id"] == award_id]


def find_line(award_id, category):
    """First-created line of a category on an award (insertion order)."""
    for l in STORES["budget_lines"].values():
        if l["award_id"] == award_id and l["category"] == category:
            return l
    return None


def award_of(entity):
    return STORES["awards"].get(entity.get("award_id"))


# ---------------------------------------------------------------------------
# f_and_a_accrual (authorized variant) — pinned evaluation order
# ---------------------------------------------------------------------------

def fna_authorized(award):
    """Returns (f_and_a_authorized, directs_authorized, mtdc_authorized)."""
    lines = award_lines(award["id"])
    directs = sum(l["authorized_cents"] for l in lines if l["category"] != "F_AND_A")
    equip = sum(l["authorized_cents"] for l in lines if l["category"] == "EQUIPMENT")
    part = sum(l["authorized_cents"] for l in lines if l["category"] == "PARTICIPANT_SUPPORT")
    subs = sum(l["authorized_cents"] for l in lines if l["category"] == "SUBAWARDS")
    subs_mtdc = sum(l.get("mtdc_eligible_cents", 0) for l in lines if l["category"] == "SUBAWARDS")
    mtdc = directs - equip - part - subs + subs_mtdc
    fna = rhu(D(award["f_and_a_rate_bps"]) * D(mtdc) / D(10000))
    return fna, directs, mtdc


def recompute_fna_line(award):
    """Stamp the system F_AND_A line's authorized_cents over authorized bases."""
    fna, _, _ = fna_authorized(award)
    line = find_line(award["id"], "F_AND_A")
    if line is not None and line["authorized_cents"] != fna:
        line["authorized_cents"] = fna
        touch(line)


# ---------------------------------------------------------------------------
# salary_charge_with_cap + fringe_benefit_charge (per-line provisional)
# ---------------------------------------------------------------------------

def ibs_monthly(person):
    return rhu(D(person["institutional_base_salary_annual_cents"]) / D(person["appointment_months"]))


def salary_charge(person, award, effort_pct, period_months):
    """Returns (amount_cents, over_cap_cents). effort_pct/period_months are Decimal."""
    m_ibs = ibs_monthly(person)
    cap = award.get("salary_cap_annual_cents")
    if cap is None:
        billable = m_ibs
    else:
        cap_monthly = rhu(D(cap) / D(12))   # cap is always a 12-month-equivalent rate
        billable = min(m_ibs, cap_monthly)
    frac = D(effort_pct) / D(100) * D(period_months)
    amount = rhu(D(billable) * frac)
    over_cap = rhu(D(m_ibs - billable) * frac)
    return amount, over_cap


def fringe_for(award, amount_cents):
    """Per-line provisional fringe, rounded half-up per expenditure line."""
    return rhu(D(amount_cents) * D(award["fringe_rate_bps"]) / D(10000))


def exp_mtdc_eligible(expenditure_type, amount_cents, is_cost_share):
    if is_cost_share or expenditure_type in ("EQUIPMENT", "PARTICIPANT_SUPPORT"):
        return 0
    return amount_cents


# ---------------------------------------------------------------------------
# mtdc_base_aggregation + f_and_a_accrual (accrued) + drawdown_eligible_pool
# ---------------------------------------------------------------------------

def posted_nonshare_exps(award_id):
    return [e for e in STORES["expenditures"].values()
            if e["award_id"] == award_id and e["status"] == "POSTED" and not e["is_cost_share"]]


def recompute_award(award):
    """Recompute MTDC/direct/F&A aggregates and the LOC available draw pool."""
    exps = posted_nonshare_exps(award["id"])
    award["mtdc_spent_cents"] = sum(e["mtdc_eligible_cents"] for e in exps)
    award["total_direct_spent_cents"] = sum(e["amount_cents"] for e in exps)
    award["f_and_a_accrued_cents"] = rhu(D(award["f_and_a_rate_bps"]) * D(award["mtdc_spent_cents"]) / D(10000))
    if award["payment_method"] == "LETTER_OF_CREDIT":
        cash = [e for e in exps if e.get("cash_disbursed")]
        d_cash = sum(e["amount_cents"] for e in cash)
        m_cash = sum(e["mtdc_eligible_cents"] for e in cash)
        eligible = d_cash + rhu(D(award["f_and_a_rate_bps"]) * D(m_cash) / D(10000))
        reduction = award.get("_pool_reduction_cents", 0)
        award["available_draw_pool_cents"] = max(
            0, eligible - award["cumulative_drawn_cents"] - award["reserved_draw_cents"] - reduction)


# ---------------------------------------------------------------------------
# award_posture_derivation (+ FROZEN drawdown auto-cancel cascade)
# ---------------------------------------------------------------------------

def award_reports(award_id):
    return [r for r in STORES["reports"].values() if r["award_id"] == award_id]


def award_ffr(award_id):
    for f in STORES["ffrs"].values():
        if f["award_id"] == award_id:
            return f
    return None


def recompute_posture(award):
    clock = now_clock()
    old = award["posture"]
    ffr_days_overdue = 0
    if award["status"] == "CLOSEOUT_PENDING":
        ffr = award_ffr(award["id"])
        if ffr is not None and ffr["status"] != "ACCEPTED":
            due = add_days(award["current_end_date"], FFR_DUE_DAYS)
            ffr_days_overdue = max(0, whole_days(due, clock))
    reports = award_reports(award["id"])
    frozen = (any(r["report_type"] == "FINAL_TECHNICAL" and r["status"] == "OVERDUE"
                  and r["days_overdue"] > FINAL_REPORT_GRACE_DAYS for r in reports)
              or ffr_days_overdue > FINAL_REPORT_GRACE_DAYS)
    restricted = (any(r["status"] == "OVERDUE" for r in reports) or ffr_days_overdue > 0)
    new = "FROZEN" if frozen else ("RESTRICTED" if restricted else "OPEN")
    award["posture"] = new
    if new == "FROZEN" and old != "FROZEN":
        # Cascade link 3: cancel every DRAFT/SUBMITTED drawdown, release reservations.
        released = False
        for d in STORES["drawdowns"].values():
            if d["award_id"] == award["id"] and d["status"] in ("DRAFT", "SUBMITTED"):
                if d["status"] == "SUBMITTED":
                    award["reserved_draw_cents"] -= d["amount_cents"]
                    released = True
                d["status"] = "CANCELLED"
                touch(d)
        if released:
            recompute_award(award)
            touch(award)
    return new


def overdue_sweep():
    """Clock-set cascade: PENDING->OVERDUE sweep, days_overdue recompute, posture."""
    clock = now_clock()
    for r in STORES["reports"].values():
        if r["status"] == "PENDING" and clock > r["due_date"]:
            r["status"] = "OVERDUE"
            r["days_overdue"] = max(0, whole_days(r["due_date"], clock))
            touch(r)
        elif r["status"] == "OVERDUE":
            r["days_overdue"] = max(0, whole_days(r["due_date"], clock))
    for a in STORES["awards"].values():
        recompute_posture(a)


# ---------------------------------------------------------------------------
# Receivable aging + late_interest_accrual (computed on read / clock set)
# ---------------------------------------------------------------------------

def aging_bucket(days):
    if days <= 30:
        return "CURRENT"
    if days <= 60:
        return "D31_60"
    if days <= 90:
        return "D61_90"
    if days <= 120:
        return "D91_120"
    return "OVER_120"


def receivable_live(recv):
    """Returns (days_outstanding, bucket, accrued_interest_cents, outstanding_total_cents).

    While DISPUTED, accrual is frozen at the value computed when the dispute opened.
    """
    clock = now_clock()
    days_out = max(0, whole_days(recv["invoice_date"], clock))
    if recv["status"] == "DISPUTED":
        accrued = recv.get("_frozen_accrued_cents", 0)
    else:
        billable = max(0, days_out - GRACE_DAYS - recv["total_disputed_days"])
        award = STORES["awards"].get(recv["award_id"])
        apr = 0
        if award is not None:
            sponsor = STORES["sponsors"].get(award["sponsor_id"])
            if sponsor is not None:
                apr = sponsor.get("late_payment_apr_bps", 0)
        principal_out = recv["amount_cents"] - recv["principal_paid_cents"]
        accrued = rhu(D(principal_out) * D(apr) * D(billable) / D(10000 * DAYS_PER_YEAR)) if apr else 0
    outstanding = (recv["amount_cents"] + accrued
                   - recv["interest_paid_cents"] - recv["principal_paid_cents"])
    return days_out, aging_bucket(days_out), accrued, outstanding


# ---------------------------------------------------------------------------
# Effort: charged percentage and statement recompute (cascade link 4)
# ---------------------------------------------------------------------------

def charged_pct(person, award_id, cycle):
    num = 0
    for e in STORES["expenditures"].values():
        if (e["award_id"] == award_id and e.get("person_id") == person["id"]
                and e["expenditure_type"] == "SALARY" and e["status"] == "POSTED"
                and cycle["period_start"] <= e["transaction_date"] < cycle["period_end"]):
            num += e["amount_cents"]
    den = ibs_monthly(person) * cycle["cycle_months"]
    if den <= 0:
        return Decimal("0.00")
    return rhu2(D(100) * D(num) / D(den))


def recompute_statements_for(person_id, award_id, tx_date):
    """Every statement for (person, award) whose non-CLOSED cycle window covers
    tx_date recomputes charged_effort_pct and bumps its version (PRD 2.6)."""
    for s in STORES["statements"].values():
        if s["person_id"] != person_id or s.get("award_id") != award_id:
            continue
        cycle = STORES["cycles"].get(s["cycle_id"])
        if cycle is None or cycle["status"] == "CLOSED":
            continue
        if cycle["period_start"] <= tx_date < cycle["period_end"]:
            person = STORES["persons"].get(person_id)
            s["charged_effort_pct"] = float(charged_pct(person, award_id, cycle))
            touch(s)


# ---------------------------------------------------------------------------
# Subaward invoice chain (subaward_mtdc_cap_portion, chronological)
# ---------------------------------------------------------------------------

def recompute_invoice_chain(subaward):
    invs = [i for i in STORES["invoices"].values()
            if i["subaward_id"] == subaward["id"] and i["status"] != "REJECTED"]
    # chronological: period_start ASC, tie-break created_at ASC (stable, never id)
    invs.sort(key=lambda i: (i["period_start"], i["created_at"]))
    cum = 0
    for i in invs:
        cum += i["current_period_direct_cents"]
        i["cumulative_direct_cents"] = cum
        i["mtdc_portion_cents"] = (min(cum, SUBAWARD_MTDC_CAP)
                                   - min(cum - i["current_period_direct_cents"], SUBAWARD_MTDC_CAP))
    subaward["invoiced_to_date_cents"] = sum(
        i["current_period_direct_cents"] + i["current_period_f_and_a_cents"] for i in invs)


# ---------------------------------------------------------------------------
# Cost-transfer APPLY_EFFECTS (mirror ledger, money conservation)
# ---------------------------------------------------------------------------

def apply_transfer_effects(ct, actor_uid):
    src = STORES["expenditures"][ct["source_expenditure_id"]]
    src_line = STORES["budget_lines"].get(src["budget_line_id"])
    tgt_line = STORES["budget_lines"].get(ct["target_budget_line_id"])
    src_award = STORES["awards"][src["award_id"]]
    tgt_award = STORES["awards"][ct["target_award_id"]]

    # (1) source -> TRANSFERRED_OUT; its line is credited
    src["status"] = "TRANSFERRED_OUT"
    touch(src)
    if src_line is not None:
        src_line["spent_cents"] -= src["amount_cents"]
        touch(src_line)

    # (2) mirror expenditure on the target award, POSTED immediately
    from db import new_id, stamp_new, now_clock as _nc
    mirror = stamp_new({
        "id": new_id(),
        "award_id": tgt_award["id"],
        "budget_line_id": ct["target_budget_line_id"],
        "person_id": None,
        "transferred_from_id": src["id"],
        "expenditure_type": src["expenditure_type"],
        "amount_cents": src["amount_cents"],
        "fringe_cents": 0,
        "over_cap_cents": 0,
        "mtdc_eligible_cents": src["mtdc_eligible_cents"],
        "effort_pct": None,
        "period_months": None,
        "transaction_date": src["transaction_date"],
        "is_cost_share": False,
        "cash_disbursed": src.get("cash_disbursed", False),
        "is_allocable": src.get("is_allocable", True),
        "is_reasonable": src.get("is_reasonable", True),
        "is_consistent": src.get("is_consistent", True),
        "description": src.get("description"),
        "status": "POSTED",
        "disallow_reason": None,
        "posted_at": _nc(),
        "invoiced_receivable_id": None,
        "submitted_by_user_id": actor_uid,
    })
    STORES["expenditures"][mirror["id"]] = mirror

    # (3) target line debited
    if tgt_line is not None:
        tgt_line["spent_cents"] += src["amount_cents"]
        touch(tgt_line)

    # (4) both awards recompute MTDC / F&A / pools
    recompute_award(src_award)
    touch(src_award)
    recompute_award(tgt_award)
    touch(tgt_award)


# ---------------------------------------------------------------------------
# fringe_trueup_adjustment (cycle close)
# ---------------------------------------------------------------------------

def fringe_trueup(cycle):
    actual = cycle["actual_fringe_rate_bps"]
    touched = {}
    for e in STORES["expenditures"].values():
        if (e["expenditure_type"] == "SALARY" and e["status"] == "POSTED"
                and cycle["period_start"] <= e["transaction_date"] < cycle["period_end"]):
            touched.setdefault(e["award_id"], 0)
            touched[e["award_id"]] += e["amount_cents"]
    for award_id, base in touched.items():
        award = STORES["awards"].get(award_id)
        if award is None:
            continue
        adjustment = rhu(D(base) * D(actual - award["fringe_rate_bps"]) / D(10000))
        if adjustment != 0:
            line = find_line(award_id, "FRINGE_BENEFITS")
            if line is not None:
                line["spent_cents"] += adjustment
                touch(line)
