"""Covenant calculations: DSCR, LTV, assessment creation, auto-cure."""
import db
from services.common import now_iso, round_ratio_4dp, stamp_new, touch, within_months, quarter_of
from services import posture


def accepted_op_statements(loan):
    return [
        s for s in db.financial_statements.values()
        if s["loan_id"] == loan["id"]
        and s["statement_type"] == "OPERATING_STATEMENT"
        and s["status"] == "ACCEPTED"
        and s["period_start_dt"] >= loan["origination_date_dt"]
    ]


def _quarter_key(dt):
    qs, _ = quarter_of(dt)
    return (qs.year, (qs.month - 1) // 3)


def _prev_quarters(qs, n):
    """Yield the n quarter-start datetimes ending at qs's quarter (inclusive), walking back."""
    out = []
    year, q = qs.year, (qs.month - 1) // 3
    for _ in range(n):
        out.append((year, q))
        q -= 1
        if q < 0:
            q = 3
            year -= 1
    return out


def run_dscr_assessment(loan, statement):
    """calculations.dscr_calculation. Returns assessment or None when not computable."""
    from decimal import Decimal, ROUND_HALF_UP
    annual_debt_service = int(
        (Decimal(loan["original_principal_cents"]) * Decimal(str(loan["note_rate"])))
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    if annual_debt_service <= 0:
        return None
    stmts = accepted_op_statements(loan)
    by_quarter = {}
    for s in stmts:
        by_quarter.setdefault(_quarter_key(s["period_start_dt"]), s)

    qs, _ = quarter_of(statement["period_start_dt"])
    qkey = (qs.year, (qs.month - 1) // 3)

    if loan["dscr_basis"] == "TTM":
        needed = _prev_quarters(qs, 4)
        if any(k not in by_quarter for k in needed):
            return None  # not computable; no assessment row
        noi_annualized = sum(by_quarter[k]["net_operating_income_cents"] for k in needed)
    else:  # T3_ANNUALIZED
        if qkey not in by_quarter:
            return None
        noi_annualized = by_quarter[qkey]["net_operating_income_cents"] * 4

    dscr = round_ratio_4dp(noi_annualized, annual_debt_service)
    breach = dscr < loan["dscr_covenant_threshold"]
    a = _create_assessment(
        loan, "DSCR", statement_id=statement["id"], basis=loan["dscr_basis"],
        computed_value=dscr, threshold_value=loan["dscr_covenant_threshold"], breach=breach,
    )
    loan["current_dscr"] = dscr
    touch(loan)
    if not breach:
        _auto_cure(loan, "DSCR", exclude_id=a["id"])
    posture.reevaluate_servicing(loan)
    posture.reevaluate_risk(loan)
    posture.reevaluate_servicing(loan)
    return a


def run_ltv_assessment(loan):
    """calculations.ltv_calculation."""
    clock = db.get_clock()
    collateral = 0
    for p in db.properties.values():
        if p["loan_id"] != loan["id"]:
            continue
        # In-date iff appraisal_date >= clock - 24 months.
        if within_months(p["appraisal_date_dt"], clock, 24):
            collateral += p["appraised_value_cents"]
    if collateral == 0:
        computed = None
        breach = True
    else:
        computed = round_ratio_4dp(loan["current_balance_cents"], collateral)
        breach = computed > loan["ltv_covenant_threshold"]
    a = _create_assessment(
        loan, "LTV", statement_id=None, basis=None,
        computed_value=computed, threshold_value=loan["ltv_covenant_threshold"], breach=breach,
    )
    loan["current_ltv"] = computed
    touch(loan)
    if not breach:
        _auto_cure(loan, "LTV", exclude_id=a["id"])
    posture.reevaluate_servicing(loan)
    posture.reevaluate_risk(loan)
    posture.reevaluate_servicing(loan)
    return a


def _create_assessment(loan, atype, statement_id, basis, computed_value, threshold_value, breach):
    a = {
        "id": db.new_id(),
        "loan_id": loan["id"],
        "statement_id": statement_id,
        "assessment_type": atype,
        "basis": basis,
        "computed_value": computed_value,
        "threshold_value": threshold_value,
        "breach": breach,
        "status": "OPEN" if breach else "CONFORMING",
        "assessed_at": now_iso(),
        "assessed_at_dt": db.get_clock(),
        "waived_by_user_id": None,
        "waiver_reason": None,
    }
    stamp_new(a)
    db.covenant_assessments[a["id"]] = a
    return a


def _auto_cure(loan, atype, exclude_id):
    for other in db.covenant_assessments.values():
        if (
            other["loan_id"] == loan["id"]
            and other["assessment_type"] == atype
            and other["status"] == "OPEN"
            and other["id"] != exclude_id
        ):
            other["status"] = "CURED"
            touch(other)
