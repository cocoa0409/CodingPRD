"""Business logic: calculations, coverage/readiness resolution, cascades."""
from decimal import Decimal

from store import store
from common import (
    D, round_half_up, ceil_div, pct_4dp, touch, add_days, date_le, date_lt,
    days_between,
)

# --- Enum domains ---------------------------------------------------------
DISCIPLINES = {"RN", "NP", "PHYSICIAN", "CRNA", "THERAPIST"}
SPECIALTIES = {"ICU", "ER", "MED_SURG", "OR", "L_AND_D", "TELEMETRY", "PSYCH", "HOSPITALIST"}
EMPLOYMENT_TYPES = {"W2_EMPLOYEE", "CONTRACTOR_1099"}
LICENSE_TYPES = {"RN", "NP", "PHYSICIAN", "CRNA", "THERAPIST"}
SHIFTS = {"DAY", "NIGHT", "ROTATING"}
ITEM_TYPES = {"BLS_CERT", "IMMUNIZATION_RECORD", "BACKGROUND_CHECK", "DRUG_SCREEN",
              "LICENSE_VERIFICATION", "TB_TEST", "FIT_TEST"}
REQUIRED_TYPES = ["BLS_CERT", "IMMUNIZATION_RECORD", "BACKGROUND_CHECK",
                  "DRUG_SCREEN", "LICENSE_VERIFICATION"]

# --- Constants ------------------------------------------------------------
OT_MULT = Decimal("1.5")
CALLBACK_MULT = Decimal("2.0")
BURDEN = Decimal("0.185")
STIPEND_CAP = 250000
CANCELLATION_NOTICE_DAYS = 30
MAX_TERM_WEEKS = 26


# ---------------------------------------------------------------------------
# Per-diem selection
# ---------------------------------------------------------------------------
def per_diem_select(facility, basis_date):
    code = facility["per_diem_locality_code"]
    cands = [p for p in store.per_diem.values()
             if p["locality_code"] == code and date_le(p["effective_from"], basis_date)]
    if not cands:
        return 0, 0, False
    cands.sort(key=lambda p: (p["created_at"], p["_seq"]))           # created_at ASC tie-break
    cands.sort(key=lambda p: p["effective_from"], reverse=True)      # effective_from DESC
    w = cands[0]
    return w["daily_lodging_cents"], w["daily_mie_cents"], True


# ---------------------------------------------------------------------------
# License coverage resolution
# ---------------------------------------------------------------------------
def license_coverage(assignment, coverage_end_date):
    clinician = store.clinicians[assignment["clinician_id"]]
    facility = store.facilities[assignment["facility_id"]]
    req_type = assignment["required_license_type"]
    cands = []
    for lic in store.licenses.values():
        if lic["clinician_id"] != assignment["clinician_id"]:
            continue
        if lic["license_type"] != req_type:
            continue
        if lic["status"] != "VERIFIED":
            continue
        if date_lt(lic["expires_on"], coverage_end_date):   # need expires_on >= end (inclusive)
            continue
        direct = lic["state_code"] == facility["state_code"]
        compact = (lic["is_compact"] and facility["is_compact_member"]
                   and lic["state_code"] == clinician["primary_residence_state"])
        if direct:
            kind = 0
        elif compact:
            kind = 1
        else:
            continue
        cands.append((kind, lic))
    if not cands:
        return None
    cands.sort(key=lambda t: (t[1]["created_at"], t[1]["_seq"]))     # created_at ASC
    cands.sort(key=lambda t: t[1]["expires_on"], reverse=True)       # expires_on DESC
    cands.sort(key=lambda t: t[0])                                   # kind ASC (direct first)
    return cands[0][1]["id"]


# ---------------------------------------------------------------------------
# Projected (whole-term) economics
# ---------------------------------------------------------------------------
def compute_projected(assignment):
    contract = _contract_of(assignment)
    clinician = store.clinicians[assignment["clinician_id"]]
    facility = store.facilities[assignment["facility_id"]]
    lodging, mie, _ = per_diem_select(facility, assignment["start_date"])
    wgh = D(contract["weekly_guaranteed_hours"])
    stipend = min((lodging + mie) * 7, STIPEND_CAP) if wgh >= 32 else 0
    base = contract["base_pay_rate_cents_per_hour"]
    bill = contract["bill_rate_cents_per_hour"]
    taxable = round_half_up(wgh * base) + (0 if clinician["tax_home_verified"] else stipend)
    burden = round_half_up(D(taxable) * BURDEN) if clinician["employment_type"] == "W2_EMPLOYEE" else 0
    nontax = stipend if clinician["tax_home_verified"] else 0
    weekly_pay = taxable + nontax + burden
    weekly_bill = round_half_up(wgh * bill)
    tw = contract["term_weeks"]
    assignment["projected_pay_cost_cents"] = weekly_pay * tw
    assignment["projected_gross_bill_cents"] = weekly_bill * tw
    assignment["projected_margin_cents"] = (
        assignment["projected_gross_bill_cents"] - assignment["projected_pay_cost_cents"])
    assignment["projected_margin_pct"] = pct_4dp(
        assignment["projected_margin_cents"], assignment["projected_gross_bill_cents"])


def _contract_of(assignment):
    for c in store.contracts.values():
        if c["assignment_id"] == assignment["id"]:
            return c
    return None


# ---------------------------------------------------------------------------
# Credential packet readiness (dual basis)
# ---------------------------------------------------------------------------
def compute_readiness(packet):
    assignment = store.assignments[packet["assignment_id"]]
    items = [it for it in store.items.values() if it["packet_id"] == packet["id"]]

    def satisfied(basis):
        n = 0
        for t in REQUIRED_TYPES:
            for it in items:
                if (it["item_type"] == t and it["status"] == "VERIFIED"
                        and (it["expires_on"] is None or not date_lt(it["expires_on"], basis))):
                    n += 1
                    break
        return n

    s1 = satisfied(assignment["start_date"])
    packet["readiness_score_start_basis"] = round_half_up(D(100 * s1) / D(5))
    packet["blocking_item_count_start_basis"] = 5 - s1
    s2 = satisfied(assignment["end_date"])
    packet["readiness_score_full_term_basis"] = round_half_up(D(100 * s2) / D(5))
    packet["blocking_item_count_full_term_basis"] = 5 - s2


# ---------------------------------------------------------------------------
# Weekly hour classification
# ---------------------------------------------------------------------------
def classify_hours(daily_hours, callback):
    total = sum(daily_hours, Decimal("0"))
    daily_ot = sum((max(Decimal("0"), h - 12) for h in daily_hours), Decimal("0"))
    weekly_ot = max(Decimal("0"), total - 40)
    overtime = max(daily_ot, weekly_ot)
    regular = total - overtime
    days_worked = sum(1 for h in daily_hours if h > 0)
    return {
        "total_raw_hours": total,
        "overtime_hours": overtime,
        "regular_hours": regular,
        "days_worked": days_worked,
    }


# ---------------------------------------------------------------------------
# Weekly earnings statement (Cascade B link 2)
# ---------------------------------------------------------------------------
def build_weekly_statement(timesheet, assignment):
    from common import new_common
    contract = _contract_of(assignment)
    clinician = store.clinicians[assignment["clinician_id"]]
    facility = store.facilities[assignment["facility_id"]]

    regular = timesheet["regular_hours"]
    overtime = timesheet["overtime_hours"]
    callback = timesheet["callback_hours"]
    days_worked = timesheet["days_worked"]
    worked = regular + overtime

    lodging, mie, found = per_diem_select(facility, timesheet["week_start_date"])
    daily_total = lodging + mie
    if not found:
        stipend = 0
        variant = "NONE"
    elif worked >= 32:
        variant = "FULL_WEEK_ACCRUAL"
        stipend = min(daily_total * 7, STIPEND_CAP)
    else:
        variant = "DAILY_PRORATED"
        stipend = min(daily_total * days_worked, STIPEND_CAP)

    if clinician["tax_home_verified"]:
        non_taxable = stipend
        stipend_to_wages = 0
    else:
        non_taxable = 0
        stipend_to_wages = stipend

    base = contract["base_pay_rate_cents_per_hour"]
    bill = contract["bill_rate_cents_per_hour"]
    regular_pay = round_half_up(regular * base)
    ot_pay = round_half_up(overtime * base * OT_MULT)
    cb_pay = round_half_up(callback * base * CALLBACK_MULT)
    taxable = regular_pay + ot_pay + cb_pay + stipend_to_wages
    burden = round_half_up(D(taxable) * BURDEN) if clinician["employment_type"] == "W2_EMPLOYEE" else 0
    total_pay = taxable + non_taxable + burden

    contracted_bill = (round_half_up(regular * bill)
                       + round_half_up(overtime * bill * OT_MULT)
                       + round_half_up(callback * bill * CALLBACK_MULT))
    required_bill = ceil_div(total_pay * 100, 78)
    gross_bill = max(contracted_bill, required_bill)
    uplift = gross_bill > contracted_bill
    gross_margin = gross_bill - total_pay
    margin_pct = pct_4dp(gross_margin, gross_bill)

    st = new_common(True)
    st["id"] = _uuid()
    st.update({
        "timesheet_id": timesheet["id"],
        "assignment_id": assignment["id"],
        "clinician_id": clinician["id"],
        "payroll_run_id": None,
        "kind": "WEEKLY",
        "period_key_date": timesheet["week_start_date"],
        "billable_hours": worked,
        "stipend_variant": variant,
        "taxable_wages_cents": taxable,
        "non_taxable_stipend_cents": non_taxable,
        "burden_cents": burden,
        "total_pay_cost_cents": total_pay,
        "contracted_bill_cents": contracted_bill,
        "gross_bill_cents": gross_bill,
        "margin_uplift_applied": uplift,
        "gross_margin_cents": gross_margin,
        "margin_pct": margin_pct,
        "status": "FINALIZED",
    })
    store.statements[st["id"]] = st
    return st


def _uuid():
    import uuid
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Assignment realized ledger roll-up
# ---------------------------------------------------------------------------
def ledger_rollup(assignment):
    S = [st for st in store.statements.values()
         if st["assignment_id"] == assignment["id"] and st["status"] in ("FINALIZED", "POSTED")]
    assignment["realized_gross_bill_cents"] = sum(st["gross_bill_cents"] for st in S)
    assignment["realized_pay_cost_cents"] = sum(st["total_pay_cost_cents"] for st in S)
    assignment["realized_margin_cents"] = sum(st["gross_margin_cents"] for st in S)
    g = assignment["realized_gross_bill_cents"]
    assignment["realized_margin_pct"] = Decimal("0") if g == 0 else pct_4dp(
        assignment["realized_margin_cents"], g)


def recompute_clinician(clinician):
    cid = clinician["id"]
    count = sum(1 for a in store.assignments.values()
                if a["clinician_id"] == cid and a["staffing_status"] in ("PENDING_START", "ACTIVE"))
    clinician["active_assignment_count"] = count
    clinician["status"] = "ON_ASSIGNMENT" if count > 0 else "AVAILABLE"
    stmts = [st for st in store.statements.values()
             if st["clinician_id"] == cid and st["status"] in ("FINALIZED", "POSTED")]
    clinician["ytd_taxable_wages_cents"] = sum(st["taxable_wages_cents"] for st in stmts)
    clinician["ytd_nontaxable_stipend_cents"] = sum(st["non_taxable_stipend_cents"] for st in stmts)


def recompute_end_date(assignment):
    assignment["end_date"] = add_days(assignment["start_date"], assignment["term_weeks"] * 7 - 1)


def _readiness_snapshot(packet):
    return (packet["readiness_score_start_basis"], packet["blocking_item_count_start_basis"],
            packet["readiness_score_full_term_basis"], packet["blocking_item_count_full_term_basis"])


def apply_readiness(packet):
    """Recompute readiness; bump packet version only when a value actually changed."""
    before = _readiness_snapshot(packet)
    compute_readiness(packet)
    if _readiness_snapshot(packet) != before:
        touch(packet)
        return True
    return False


# ---------------------------------------------------------------------------
# Extension withdrawal cascade
# ---------------------------------------------------------------------------
def withdraw_open_extensions(assignment):
    for ext in store.extensions.values():
        if ext["assignment_id"] == assignment["id"] and ext["status"] in ("PROPOSED", "COUNTERED"):
            ext["status"] = "WITHDRAWN"
            ext["resolved_at"] = store.now_ts()
            touch(ext)


def apply_clinician_recompute(clinician):
    before = (clinician["active_assignment_count"], clinician["status"],
              clinician["ytd_taxable_wages_cents"], clinician["ytd_nontaxable_stipend_cents"])
    recompute_clinician(clinician)
    after = (clinician["active_assignment_count"], clinician["status"],
             clinician["ytd_taxable_wages_cents"], clinician["ytd_nontaxable_stipend_cents"])
    if before != after:
        touch(clinician)


def perform_cancellation(assignment, effective_date, reason):
    """Runs the full cancellation cascade. Assumes staffing state already validated."""
    from common import new_common
    contract = _contract_of(assignment)
    clinician = store.clinicians[assignment["clinician_id"]]

    clock_date = store.clock_date().isoformat()
    notice_days = days_between(clock_date, effective_date)
    if notice_days >= CANCELLATION_NOTICE_DAYS:
        shortfall_weeks = 0
    else:
        shortfall_weeks = ceil_div(CANCELLATION_NOTICE_DAYS - notice_days, 7)

    remaining = assignment["guaranteed_hours_remaining"]
    wgh = D(contract["weekly_guaranteed_hours"])
    shortfall_hours = min(wgh * shortfall_weeks, remaining)

    assignment["guaranteed_hours_consumed"] = assignment["guaranteed_hours_consumed"] + shortfall_hours
    assignment["guaranteed_hours_waived"] = assignment["guaranteed_hours_waived"] + (remaining - shortfall_hours)
    assignment["guaranteed_hours_remaining"] = Decimal("0")

    penalty = 0
    if shortfall_hours > 0:
        base = contract["base_pay_rate_cents_per_hour"]
        bill = contract["bill_rate_cents_per_hour"]
        taxable = round_half_up(shortfall_hours * base)
        burden = round_half_up(D(taxable) * BURDEN) if clinician["employment_type"] == "W2_EMPLOYEE" else 0
        total_pay = taxable + burden
        contracted_bill = round_half_up(shortfall_hours * bill)
        required_bill = ceil_div(total_pay * 100, 78)
        gross_bill = max(contracted_bill, required_bill)
        gross_margin = gross_bill - total_pay
        penalty = gross_bill
        st = new_common(True)
        st["id"] = _uuid()
        st.update({
            "timesheet_id": None,
            "assignment_id": assignment["id"],
            "clinician_id": clinician["id"],
            "payroll_run_id": None,
            "kind": "CANCELLATION_PENALTY",
            "period_key_date": effective_date,
            "billable_hours": shortfall_hours,
            "stipend_variant": "NONE",
            "taxable_wages_cents": taxable,
            "non_taxable_stipend_cents": 0,
            "burden_cents": burden,
            "total_pay_cost_cents": total_pay,
            "contracted_bill_cents": contracted_bill,
            "gross_bill_cents": gross_bill,
            "margin_uplift_applied": gross_bill > contracted_bill,
            "gross_margin_cents": gross_margin,
            "margin_pct": pct_4dp(gross_margin, gross_bill),
            "status": "FINALIZED",
        })
        store.statements[st["id"]] = st

    assignment["staffing_status"] = "CANCELLED"
    assignment["cancellation_effective_date"] = effective_date
    assignment["cancellation_notice_days"] = notice_days
    assignment["cancellation_penalty_cents"] = penalty
    ledger_rollup(assignment)
    touch(assignment)

    # Cascade: void the contract
    if contract and contract["status"] in ("DRAFT", "SENT_FOR_SIGNATURE",
                                            "COUNTERSIGN_REQUESTED", "FULLY_EXECUTED"):
        contract["status"] = "VOIDED"
        contract["voided_reason"] = reason
        touch(contract)

    # Cascade: release clinician
    apply_clinician_recompute(clinician)

    # Cascade: withdraw open extensions
    withdraw_open_extensions(assignment)


def accept_extension(ext, assignment):
    """Applies an accepted extension's effects to the assignment and contract."""
    contract = _contract_of(assignment)
    add_weeks = ext["proposed_additional_weeks"]
    assignment["term_weeks"] = assignment["term_weeks"] + add_weeks
    recompute_end_date(assignment)
    assignment["extension_round_count"] = assignment["extension_round_count"] + 1
    delta = D(contract["weekly_guaranteed_hours"]) * add_weeks
    assignment["guaranteed_hours_total"] = assignment["guaranteed_hours_total"] + delta
    assignment["guaranteed_hours_remaining"] = assignment["guaranteed_hours_remaining"] + delta

    contract["term_weeks"] = assignment["term_weeks"]
    contract["base_pay_rate_cents_per_hour"] = ext["proposed_pay_rate_cents_per_hour"]
    contract["bill_rate_cents_per_hour"] = ext["proposed_bill_rate_cents_per_hour"]
    touch(contract)

    assignment["covering_license_id"] = license_coverage(assignment, assignment["end_date"])
    compute_projected(assignment)
    touch(assignment)
