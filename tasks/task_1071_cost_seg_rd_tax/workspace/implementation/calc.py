"""Calculation rules per PRD §3.3, §3.4, §3.5, §3.6."""
from decimal import Decimal
from core import D, rhu, db

MACRS_Y1_RATE = {
    "FIVE_YEAR": D("0.20"),
    "SEVEN_YEAR": D("0.1429"),
    "FIFTEEN_YEAR": D("0.05"),
    "THIRTY_NINE_YEAR": D("0.02564"),
}
BONUS_PCT_BY_YEAR = {
    2022: D("1.00"),
    2023: D("0.80"),
    2024: D("0.60"),
    2025: D("0.40"),
    2026: D("0.20"),
}
BONUS_ELIGIBLE_CLASSES = {"FIVE_YEAR", "SEVEN_YEAR", "FIFTEEN_YEAR"}

RECOVERY_PERIOD = {
    "FIVE_YEAR": 5,
    "SEVEN_YEAR": 7,
    "FIFTEEN_YEAR": 15,
    "THIRTY_NINE_YEAR": 39,
}

CONTRACT_RESEARCH_CAP = D("0.65")
ASC_RATE = D("0.14")
ASC_STARTUP_RATE = D("0.06")
REGULAR_RATE = D("0.20")
MAX_FEE_BPS = 3000
AMEND_STATUTE_YEARS = 3


def allocated_components(study_id):
    return [c for c in db.asset_components.values()
            if c["study_id"] == study_id and c["status"] == "ALLOCATED"]


def qualified_lines(study_id):
    return [q for q in db.qre_line_items.values()
            if q["study_id"] == study_id and q["status"] == "QUALIFIED"]


def cost_seg_depreciation(study):
    """Returns (with_bonus, without_bonus) first-year depreciation in cents.
    Per-component round-half-up, THEN sum (PRD §2.5)."""
    prop = db.properties.get(study.get("property_id"))
    bonus_pct = Decimal("0")
    if prop is not None:
        year = prop["placed_in_service_date"].year
        bonus_pct = BONUS_PCT_BY_YEAR.get(year, Decimal("0"))

    with_bonus_total = 0
    no_bonus_total = 0
    for c in allocated_components(study["id"]):
        cost = D(c["allocated_cost_cents"])
        macrs = MACRS_Y1_RATE[c["asset_class"]]
        # WITHOUT_BONUS
        no_bonus_total += rhu(cost * macrs)
        # WITH_BONUS
        if c["asset_class"] in BONUS_ELIGIBLE_CLASSES:
            bonus_amt = rhu(cost * bonus_pct)
            macrs_part = rhu((cost - bonus_amt) * macrs)
            with_bonus_total += bonus_amt + macrs_part
        else:
            with_bonus_total += rhu(cost * macrs)
    return with_bonus_total, no_bonus_total


def rd_credit(study):
    """Returns (regular, asc) credit in cents."""
    current_qre = sum(q["qualified_amount_cents"] for q in qualified_lines(study["id"]))
    current_qre = D(current_qre)

    # ASC
    y1 = D(study.get("prior_qre_year1_cents") or 0)
    y2 = D(study.get("prior_qre_year2_cents") or 0)
    y3 = D(study.get("prior_qre_year3_cents") or 0)
    avg_prior = (y1 + y2 + y3) / D(3)  # exact, not pre-rounded
    if avg_prior > 0:
        asc = max(0, rhu(ASC_RATE * (current_qre - D("0.5") * avg_prior)))
    else:
        asc = rhu(ASC_STARTUP_RATE * current_qre)

    # REGULAR
    fixed_base_pct = D(study.get("fixed_base_pct") or 0)
    avg_gross = D(study.get("avg_annual_gross_receipts_cents") or 0)
    base_amount = max(rhu(D("0.5") * current_qre), rhu(fixed_base_pct * avg_gross))
    regular = max(0, rhu(REGULAR_RATE * (current_qre - D(base_amount))))
    return regular, asc


def compute_benefit_fields(study):
    """Compute all benefit fields for a study (live)."""
    out = {
        "first_year_depreciation_cents": 0,
        "first_year_depreciation_no_bonus_cents": 0,
        "rd_credit_regular_cents": 0,
        "rd_credit_asc_cents": 0,
        "estimated_tax_benefit_cents": 0,
    }
    if study["study_type"] == "COST_SEGREGATION":
        wb, nb = cost_seg_depreciation(study)
        out["first_year_depreciation_cents"] = wb
        out["first_year_depreciation_no_bonus_cents"] = nb
        client = db.clients.get(study["client_id"])
        rate = D(client["marginal_tax_rate"]) if client else D(0)
        out["estimated_tax_benefit_cents"] = rhu(D(wb) * rate)
    else:  # RD_CREDIT
        reg, asc = rd_credit(study)
        out["rd_credit_regular_cents"] = reg
        out["rd_credit_asc_cents"] = asc
        out["estimated_tax_benefit_cents"] = asc if study.get("credit_method") == "ASC" else reg
    return out


def qre_qualified_amount(line):
    percent = D(line["qualified_percent"])
    if line["qre_category"] == "CONTRACT_RESEARCH":
        effective = min(percent, CONTRACT_RESEARCH_CAP)
    else:
        effective = percent
    return rhu(D(line["gross_amount_cents"]) * effective)


def study_fee(study):
    if study["fee_type"] == "FIXED":
        return study["fee_fixed_amount_cents"]
    # PERCENT
    benefit = compute_benefit_fields(study)["estimated_tax_benefit_cents"]
    return rhu(D(study["fee_percent_bps"]) / D(10000) * D(benefit))


def section_481a(study):
    prop = db.properties.get(study.get("property_id"))
    depreciable_basis = prop["depreciable_basis_cents"] if prop else 0
    as_filed = rhu(D(depreciable_basis) * MACRS_Y1_RATE["THIRTY_NINE_YEAR"])
    fy = compute_benefit_fields(study)["first_year_depreciation_cents"]
    return fy - as_filed
