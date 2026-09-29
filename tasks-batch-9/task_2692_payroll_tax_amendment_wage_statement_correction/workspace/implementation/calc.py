"""The eleven calculations of PRD section 3 plus the derived rollups of PRD 2.11.

All money arithmetic is exact integer arithmetic; every rounding goes through
``rhu`` (ROUND_HALF_UP) at exactly the point the PRD pins it.
"""

from datetime import timedelta

from common import (
    db, fail, new_row, rhu, sorted_rows, touch, whole_days, period_ordinal,
    OPEN_ENDED_ORDINAL,
)

# ---------------------------------------------------------------------------
# Scope queries
# ---------------------------------------------------------------------------

OPEN_DISCREPANCY_STATES = ("OPEN", "CATEGORIZED")
LIVE_AMENDMENT_STATES = ("DRAFT", "PREPARED", "SIGNED", "SUBMITTED")
EXPOSURE_AMENDMENT_STATES = ("PREPARED", "SIGNED", "SUBMITTED", "ACCEPTED")
WAIVER_ABATEMENT_STATES = ("GRANTED", "PARTIALLY_GRANTED")
COUNTED_STATEMENT_STATES = ("ISSUED", "ACKNOWLEDGED")
OUTSTANDING_STATEMENT_STATES = ("DRAFT", "ISSUED", "RETURNED_UNDELIVERABLE")
SETTLED_REPAYMENT_STATES = ("COLLECTED", "WRITTEN_OFF", "CANCELLED")
OPEN_REMEDIATION_STATES = ("OPEN", "SUBMITTED_FOR_VERIFICATION", "VERIFICATION_FAILED")
ACTIVE_ACCOUNT_STATES = ("ACTIVE", "RETRO_ACTIVE")
OCCUPYING_ACCOUNT_STATES = ("PENDING", "RETRO_PENDING", "ACTIVE", "RETRO_ACTIVE")


def scope_register_lines(employer_id, agency_id, tax_year, quarter):
    rows = [r for r in db.register_lines.values()
            if r["employer_id"] == employer_id and r["agency_id"] == agency_id
            and r["tax_year"] == tax_year and r["quarter"] == quarter
            and r["posting_status"] == "POSTED"]
    return sorted_rows(rows)


def case_register_lines(case):
    return scope_register_lines(case["employer_id"], case["agency_id"],
                                case["tax_year"], case["quarter"])


def case_cleared_deposits(case):
    return [r for r in db.deposit_records.values()
            if r["employer_id"] == case["employer_id"]
            and r["agency_id"] == case["agency_id"]
            and r["tax_year"] == case["tax_year"]
            and r["quarter"] == case["quarter"]
            and r["clearing_status"] == "CLEARED"]


def case_filed_returns(case):
    rows = [r for r in db.filed_returns.values()
            if r["employer_id"] == case["employer_id"]
            and r["agency_id"] == case["agency_id"]
            and r["tax_year"] == case["tax_year"]
            and r["quarter"] == case["quarter"]
            and r["status"] in ("FILED", "AMENDED")]
    return sorted_rows(rows)


def case_filed_return(case):
    rows = case_filed_returns(case)
    return rows[0] if rows else None


def case_discrepancies(case_id):
    rows = [r for r in db.discrepancies.values() if r["correction_case_id"] == case_id]
    return sorted_rows(rows)


def by_emission(rows):
    return sorted(rows, key=lambda r: r["emission_index"])


def case_amendments(case_id):
    return sorted_rows([r for r in db.amended_returns.values()
                        if r["correction_case_id"] == case_id])


def case_statements(case_id):
    return sorted_rows([r for r in db.statements.values()
                        if r["correction_case_id"] == case_id])


def case_repayments(case_id):
    return sorted_rows([r for r in db.wage_repayments.values()
                        if r["correction_case_id"] == case_id])


def case_notices(case_id):
    return sorted_rows([r for r in db.agency_notices.values()
                        if r["correction_case_id"] == case_id])


def case_remediations(case_id):
    return sorted_rows([r for r in db.control_remediations.values()
                        if r["correction_case_id"] == case_id])


def employer_cases(employer_id):
    return sorted_rows([r for r in db.correction_cases.values()
                        if r["employer_id"] == employer_id])


# ---------------------------------------------------------------------------
# Calculation 2: jurisdiction_wage_apportionment (PRD 3.2)
# Rounding happens once per line, before any summation.
# ---------------------------------------------------------------------------

def apportion_line(line):
    return rhu(line["taxable_wage_cents"] * line["workday_ratio_bps"], 10000)


# ---------------------------------------------------------------------------
# Derived rollups (PRD 2.11, 3.2, 3.9)
# ---------------------------------------------------------------------------

def compute_corrected_wage_base(case):
    base = sum(l["taxable_wage_cents"] for l in case_register_lines(case))
    adj = sum(s["wage_delta_cents"] for s in case_statements(case["id"])
              if s["status"] in COUNTED_STATEMENT_STATES)
    return base + adj


def compute_open_discrepancy_count(case):
    return sum(1 for d in case_discrepancies(case["id"])
               if d["status"] in OPEN_DISCREPANCY_STATES)


def compute_dominant_root_cause(case):
    rows = [d for d in case_discrepancies(case["id"])
            if d["status"] in ("CATEGORIZED", "RESOLVED")]
    if not rows:
        return None
    best = None
    for row in rows:
        key = (-abs(row["amount_cents"]), row["created_at"], row["_seq"])
        if best is None or key < best[0]:
            best = (key, row)
    return best[1]["root_cause_code"]


def compute_gross_exposure(case):
    return sum(a["tax_delta_cents"] + a["interest_cents"] + a["penalty_cents"]
               for a in case_amendments(case["id"])
               if a["status"] in EXPOSURE_AMENDMENT_STATES)


def compute_waived(case):
    return sum(n["waived_penalty_cents"] + n["waived_interest_cents"]
               for n in case_notices(case["id"])
               if n["abatement_status"] in WAIVER_ABATEMENT_STATES)


def compute_total_exposure(case):
    return max(0, compute_gross_exposure(case) - compute_waived(case))


def compute_repayment_recovered(case):
    return sum(r["agency_recoverable_cents"] for r in case_repayments(case["id"])
               if r["status"] == "COLLECTED")


def compute_active_statement_count(employee_id):
    return sum(1 for s in db.statements.values()
               if s["employee_id"] == employee_id
               and s["status"] in COUNTED_STATEMENT_STATES)


def sync_case(case, forced=False):
    """Recompute every derived case field; bump version when anything moved."""
    changed = forced
    for field, value in (
        ("open_discrepancy_count", compute_open_discrepancy_count(case)),
        ("dominant_root_cause_code", compute_dominant_root_cause(case)),
        ("total_exposure_cents", compute_total_exposure(case)),
        ("corrected_wage_base_cents", compute_corrected_wage_base(case)),
        ("repayment_recovered_cents", compute_repayment_recovered(case)),
    ):
        if case.get(field) != value:
            case[field] = value
            changed = True
    if changed:
        touch(case)
    return changed


def sync_employer(employer, forced=False):
    if employer is None:
        return False
    changed = forced
    open_exposure = sum(c["total_exposure_cents"] for c in employer_cases(employer["id"])
                        if c["status"] in ("OPEN", "REMEDIATION_PENDING"))
    open_remediations = 0
    for case in employer_cases(employer["id"]):
        open_remediations += sum(1 for r in case_remediations(case["id"])
                                 if r["status"] in OPEN_REMEDIATION_STATES)
    granted = sum(1 for n in db.agency_notices.values()
                  if n["employer_id"] == employer["id"]
                  and n["abatement_status"] in WAIVER_ABATEMENT_STATES)
    for field, value in (("open_exposure_cents", open_exposure),
                         ("open_remediation_count", open_remediations),
                         ("granted_abatement_count", granted)):
        if employer.get(field) != value:
            employer[field] = value
            changed = True
    if changed:
        touch(employer)
    return changed


def sync_employee(employee, forced=False):
    if employee is None:
        return False
    changed = forced
    value = compute_active_statement_count(employee["id"])
    if employee.get("active_statement_count") != value:
        employee["active_statement_count"] = value
        changed = True
    if changed:
        touch(employee)
    return changed


def sync_case_and_employer(case, forced=False):
    sync_case(case, forced=forced)
    sync_employer(db.employers.get(case["employer_id"]))


# ---------------------------------------------------------------------------
# Calculation 1: three_way_variance_detection (PRD 3.2)
# ---------------------------------------------------------------------------

def detect_variances(case, agency):
    """Return the pinned emission list [(detected_category, amount, employee_id,
    register_line_id), ...].  Raises when no filed return covers the scope."""
    lines = case_register_lines(case)
    register_wage = sum(l["taxable_wage_cents"] for l in lines)
    register_withheld = sum(l["withheld_cents"] for l in lines)

    filed = case_filed_return(case)
    if filed is None:
        fail("ERR_NO_FILED_RETURN_FOR_PERIOD",
             "no filed return in FILED or AMENDED exists on the case scope")

    deposits = case_cleared_deposits(case)
    fill_order = sorted(deposits, key=lambda d: (d["deposit_due_date"], d["created_at"], d["_seq"]))
    cash_order = sorted(deposits, key=lambda d: (d["deposit_date"], d["created_at"], d["_seq"]))
    total_obligation = sum(d["obligation_amount_cents"] for d in deposits)

    # Chronological waterfall: cash walked in cash order, obligations in fill order.
    remaining = [d["obligation_amount_cents"] for d in fill_order]
    applied = 0
    for dep in cash_order:
        cash = dep["amount_cents"]
        for k in range(len(remaining)):
            if cash <= 0:
                break
            take = min(cash, remaining[k])
            if take > 0:
                remaining[k] -= take
                cash -= take
                applied += take

    emissions = []
    if register_wage != filed["reported_taxable_wage_cents"]:
        emissions.append(("TAXABLE_WAGE",
                          register_wage - filed["reported_taxable_wage_cents"], None, None))
    if register_withheld != filed["reported_withheld_cents"]:
        emissions.append(("WITHHOLDING",
                          register_withheld - filed["reported_withheld_cents"], None, None))
    for line in lines:
        if line["work_jurisdiction_code"] != agency["jurisdiction_code"]:
            emissions.append(("JURISDICTION_ASSIGNMENT", apportion_line(line),
                              line["employee_id"], line["id"]))
    if applied < total_obligation:
        emissions.append(("DEPOSIT_SHORTFALL", total_obligation - applied, None, None))
    return emissions


def emit_discrepancies(case, emissions):
    created = []
    for index, (category, amount, employee_id, register_line_id) in enumerate(emissions):
        row = new_row({
            "correction_case_id": case["id"],
            "employee_id": employee_id,
            "register_line_id": register_line_id,
            "detected_category": category,
            "category": None,
            "root_cause_code": None,
            "amount_cents": amount,
            "emission_index": index,
            "status": "OPEN",
            "dismissal_reason": None,
            "resolved_amended_return_id": None,
            "resolved_amount_cents": None,
        })
        db.discrepancies[row["id"]] = row
        created.append(row)
    return created


# ---------------------------------------------------------------------------
# Calculation 3: amended_return_delta_rollup (PRD 3.4)
# ---------------------------------------------------------------------------

def delta_rollup(case, accrual_through, original_due_date):
    rows = by_emission([d for d in case_discrepancies(case["id"])
                        if d["status"] == "CATEGORIZED"])
    taxable_wage_delta = sum(d["amount_cents"] for d in rows
                             if d["category"] == "TAXABLE_WAGE")
    jurisdiction_removal = 0
    for d in rows:
        if d["category"] == "JURISDICTION_ASSIGNMENT":
            line = db.register_lines.get(d["register_line_id"])
            if line is not None:
                jurisdiction_removal += apportion_line(line)
    tax_delta = sum(d["amount_cents"] for d in rows if d["category"] == "WITHHOLDING")
    shortfall = sum(d["amount_cents"] for d in rows if d["category"] == "DEPOSIT_SHORTFALL")
    days_late = max(0, whole_days(original_due_date, accrual_through))
    return {
        "wage_delta_cents": taxable_wage_delta - jurisdiction_removal,
        "tax_delta_cents": tax_delta,
        "deposit_shortfall_cents": shortfall,
        "days_late": days_late,
    }


# ---------------------------------------------------------------------------
# Calculation 4: amendment_interest_accrual (PRD 3.4)
# ---------------------------------------------------------------------------

def _statutory_daily(tax_delta, rate_bps, days):
    return rhu(tax_delta * rate_bps * days, 10000 * 365)


def compute_interest(case, agency, tax_delta, days_late, accrual_through):
    rate_bps = agency["interest_rate_bps_annual"]
    variant = agency["interest_method"]
    if variant != "DEPOSIT_WEIGHTED":
        return variant, _statutory_daily(tax_delta, rate_bps, days_late)

    deposits = sorted(case_cleared_deposits(case),
                      key=lambda d: (d["deposit_due_date"], d["created_at"], d["_seq"]))
    total_obligation = sum(d["obligation_amount_cents"] for d in deposits)
    if not deposits or total_obligation == 0:
        # Falls back to STATUTORY_DAILY exactly as written; variant stays as copied.
        return variant, _statutory_daily(tax_delta, rate_bps, days_late)

    interest = 0
    running = 0
    last = len(deposits) - 1
    for index, dep in enumerate(deposits):
        if index < last:
            tranche = rhu(tax_delta * dep["obligation_amount_cents"], total_obligation)
            running += tranche
        else:
            tranche = tax_delta - running
        days_k = max(0, whole_days(dep["deposit_due_date"], accrual_through))
        interest += rhu(tranche * rate_bps * days_k, 10000 * 365)
    return variant, interest


# ---------------------------------------------------------------------------
# Calculation 5: amendment_penalty_assessment (PRD 3.4)
# Step order 3 -> 4 -> 5 is pinned.
# ---------------------------------------------------------------------------

def compute_penalty(case, agency, tax_delta, deposit_shortfall, days_late):
    if days_late <= 5:
        ftd_bps = 200
    elif days_late <= 15:
        ftd_bps = 500
    else:
        ftd_bps = 1000
    ftd = rhu(deposit_shortfall * ftd_bps, 10000)

    if days_late > 0:
        months = min(-(-days_late // 30), 5)
    else:
        months = 0
    ftf_uncapped = rhu(tax_delta * (500 * months), 10000)
    ftf_cap = rhu(tax_delta * 2500, 10000)
    ftf = min(ftf_uncapped, ftf_cap)

    gross = ftd + ftf
    if gross > 0:
        gross = max(gross, 5000)

    scaled = rhu(gross * agency["penalty_multiplier_bps"], 10000)

    voluntary = not any(
        n["employer_id"] == case["employer_id"] and n["agency_id"] == case["agency_id"]
        and n["tax_year"] == case["tax_year"] and n["quarter"] == case["quarter"]
        for n in db.agency_notices.values())
    if voluntary:
        return rhu(scaled * 7500, 10000), True
    return scaled, False


# ---------------------------------------------------------------------------
# Calculation 6: repayment_recovery_basis (PRD 3.7)
# ---------------------------------------------------------------------------

def apply_recovery_basis(repayment):
    gross = repayment["overpaid_gross_cents"]
    income_tax = repayment["overpaid_income_tax_withheld_cents"]
    fica = repayment["overpaid_fica_withheld_cents"]
    if repayment["recovery_tax_year"] == repayment["overpayment_tax_year"]:
        repayment["recovery_basis"] = "SAME_YEAR_NET"
        repayment["employee_due_cents"] = gross - income_tax - fica
        repayment["agency_recoverable_cents"] = income_tax + fica
    else:
        repayment["recovery_basis"] = "PRIOR_YEAR_GROSS"
        repayment["employee_due_cents"] = gross
        repayment["agency_recoverable_cents"] = fica


# ---------------------------------------------------------------------------
# Calculation 7: statement_box_deltas (PRD 3.6)
# ---------------------------------------------------------------------------

def compute_box_deltas(statement):
    case_id = statement["correction_case_id"]
    rows = by_emission([d for d in case_discrepancies(case_id)
                        if d["employee_id"] == statement["employee_id"]
                        and d["category"] == "JURISDICTION_ASSIGNMENT"
                        and d["status"] in ("CATEGORIZED", "RESOLVED")])
    jurisdiction_removal = sum(d["amount_cents"] for d in rows)

    candidates = [r for r in case_repayments(case_id)
                  if r["employee_id"] == statement["employee_id"]
                  and r["status"] == "COLLECTED"
                  and r["overpayment_tax_year"] == statement["tax_year"]]
    candidates.sort(key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
    repayment = candidates[0] if candidates else None

    if repayment is None:
        return -jurisdiction_removal, -jurisdiction_removal, 0
    if repayment["recovery_basis"] == "SAME_YEAR_NET":
        wage = -jurisdiction_removal - repayment["overpaid_gross_cents"]
        return wage, wage, -repayment["overpaid_income_tax_withheld_cents"]
    return (-jurisdiction_removal,
            -jurisdiction_removal - repayment["overpaid_gross_cents"],
            0)


def write_box_deltas(statement):
    wage, fica, withholding = compute_box_deltas(statement)
    statement["wage_delta_cents"] = wage
    statement["fica_wage_delta_cents"] = fica
    statement["withholding_delta_cents"] = withholding


# ---------------------------------------------------------------------------
# Calculation 8: abatement_penalty_waiver (PRD 3.8)
# ---------------------------------------------------------------------------

def compute_abatement(notice, employer, outcome):
    assessed_tax = notice["assessed_tax_cents"]
    assessed_penalty = notice["assessed_penalty_cents"]
    assessed_interest = notice["assessed_interest_cents"]
    # Step one: the tier key, evaluated exactly once and never re-evaluated.
    gross_exposure = assessed_tax + assessed_penalty + assessed_interest

    grounds = notice["abatement_grounds"]
    if outcome == "UPHELD" or grounds is None:
        return 0, 0, 0, gross_exposure

    if grounds == "FIRST_TIME":
        first_ever = (employer is not None and employer["granted_abatement_count"] == 0)
        bps = 10000 if (first_ever and gross_exposure <= 5000000) else 5000
    elif grounds == "REASONABLE_CAUSE":
        bonus = 0
        if notice["correction_case_id"]:
            for rem in case_remediations(notice["correction_case_id"]):
                if rem["control_gap_class"] == "THIRD_PARTY_FAILURE" and rem["status"] == "VERIFIED":
                    bonus = 2000
                    break
        bps = min(6000 + bonus, 10000)
    else:
        # AGENCY_ERROR and STATUTORY_EXCEPTION both waive the penalty entirely.
        bps = 10000

    # Step three: the only rounding in the whole computation.
    waived_penalty = rhu(assessed_penalty * bps, 10000)
    waived_interest = assessed_interest if grounds == "AGENCY_ERROR" else 0
    if outcome == "ABATED_PARTIAL" and notice["requested_penalty_waiver_cents"] is not None:
        waived_penalty = min(waived_penalty, notice["requested_penalty_waiver_cents"])

    # Step four: net, then the de-minimis sweep (ABATED_FULL only, exactly once).
    net = gross_exposure - waived_penalty - waived_interest
    if outcome == "ABATED_FULL" and 0 < net <= 2500:
        waived_penalty = assessed_penalty
        waived_interest = assessed_interest
        net = gross_exposure - assessed_penalty - assessed_interest
    return bps, waived_penalty, waived_interest, net


# ---------------------------------------------------------------------------
# Case dimension joins (PRD 3.5)
# ---------------------------------------------------------------------------

def join_remediation_pending(case):
    """OPEN -> REMEDIATION_PENDING once both filing and statement dimensions allow."""
    if case["status"] != "OPEN":
        return False
    if case["filing_status"] not in ("FILING_NOT_REQUIRED", "FILING_COMPLETE"):
        return False
    if case["statement_status"] not in ("STMT_NOT_REQUIRED", "STMT_ISSUED", "STMT_COMPLETE"):
        return False
    case["status"] = "REMEDIATION_PENDING"
    if not case_remediations(case["id"]):
        row = new_row({
            "correction_case_id": case["id"],
            "root_cause_code": case["dominant_root_cause_code"],
            "control_gap_class": "PROCESS_CONTROL",
            "owner_user_id": None,
            "target_date": db.now + timedelta(days=30),
            "evidence_reference": None,
            "verified_by_user_id": None,
            "verification_round": 0,
            "status": "OPEN",
            "verified_at": None,
        })
        db.control_remediations[row["id"]] = row
    return True


def advance_filing_after_discrepancy_change(case):
    """FILING_IN_PROGRESS -> FILING_COMPLETE when open_discrepancy_count hits 0."""
    if case["filing_status"] != "FILING_IN_PROGRESS":
        return False
    if compute_open_discrepancy_count(case) != 0:
        return False
    case["filing_status"] = "FILING_COMPLETE"
    join_remediation_pending(case)
    return True
