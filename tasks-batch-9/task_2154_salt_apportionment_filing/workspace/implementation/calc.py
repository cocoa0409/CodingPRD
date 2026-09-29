"""Calculation rules, derivations and cascades (PRD Sections 2.9, 3.2 - 3.9)."""
from decimal import Decimal

from errors import ApiError
from store import db
from util import D, money, factor, ZERO, midnight_utc
from web import bump, mark_dirty, new_record, sort_created

RENT_CAPITALIZATION_MULTIPLE = Decimal("8")
EXTENSION_PREPAY_PCT = Decimal("0.90")
UNDERPAYMENT_PENALTY_RATE = Decimal("0.05")
NOTICE_PENALTY_RATE = Decimal("0.10")
NOTICE_PENALTY_CAP = Decimal("2500.00")
NOTICE_INTEREST_RATE = Decimal("0.06")
DAYS_PER_YEAR = Decimal("365")
APPEAL_WINDOW_DAYS = 90
DEFAULT_RESPONSE_DUE_DAYS = 45
FULL_EXPOSURE_YEARS = 7
VDA_MAX_LOOKBACK_YEARS = 4
VDA_PENALTY_WAIVER_RATE = Decimal("0.25")
VDA_COOLING_MONTHS = 24
VDA_SHIELD_MONTHS = 24
INSTALLMENT_DUE_MONTHS = [4, 6, 9, 12]
INSTALLMENT_DUE_DAY = 15

ASSESSMENT_COUNTING_STATUSES = ("APPEAL_DENIED", "APPEAL_SUSTAINED", "CLOSED")
IN_FLIGHT_FILING_STATUSES = ("DRAFT", "FACTORS_LOCKED", "IN_REVIEW", "APPROVED")


# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------
def group_of_registration(reg):
    return db.groups[reg["group_id"]]


def registration_of_filing(filing):
    return db.registrations[filing["registration_id"]]


def group_of_filing(filing):
    return group_of_registration(registration_of_filing(filing))


def registrations_of_group(group):
    return [r for r in db.registrations.values() if r["group_id"] == group["id"]]


def filings_of_group(group):
    ids = set(r["id"] for r in registrations_of_group(group))
    return sort_created([f for f in db.filings.values() if f["registration_id"] in ids])


def filings_of_registration(reg):
    return sort_created([f for f in db.filings.values() if f["registration_id"] == reg["id"]])


def elections_of_registration(reg):
    return sort_created([e for e in db.elections.values() if e["registration_id"] == reg["id"]])


def activity_of(reg_id, tax_year=None):
    rows = [a for a in db.activity_records.values() if a["registration_id"] == reg_id]
    if tax_year is not None:
        rows = [a for a in rows if a["tax_year"] == tax_year]
    return sort_created(rows)


def modifications_of(filing):
    return sort_created([m for m in db.modifications.values() if m["filing_id"] == filing["id"]])


def claims_of(filing):
    rows = [c for c in db.credit_claims.values() if c["filing_id"] == filing["id"]]
    return sorted(rows, key=lambda c: (c["priority_order"], c["_seq"]))


def factors_of(filing):
    rows = [f for f in db.factors.values() if f["filing_id"] == filing["id"]]
    return sorted(rows, key=lambda f: f["_seq"])


def payments_of_registration(reg_id):
    return sort_created([p for p in db.payments.values() if p["registration_id"] == reg_id])


def payments_applied_to(filing):
    return sort_created([p for p in db.payments.values()
                         if p.get("applied_filing_id") == filing["id"]])


def notices_of(filing):
    return sort_created([n for n in db.notices.values() if n["filing_id"] == filing["id"]])


def extensions_of(filing):
    return sort_created([x for x in db.extensions.values() if x["filing_id"] == filing["id"]])


def vdas_of_entity(entity_id):
    return sort_created([v for v in db.vdas.values() if v["legal_entity_id"] == entity_id])


# --------------------------------------------------------------------------
# Nexus determination (PRD 3.2)
# --------------------------------------------------------------------------
def sourced_service(reg, record):
    if reg["service_sourcing_rule"] == "MARKET_BASED":
        return D(record["service_receipts"])
    if record.get("cost_of_performance_state_code") == reg["state_code"]:
        return D(record["service_receipts"])
    return ZERO


def nexus_determination(reg, as_of_tax_year):
    records = activity_of(reg["id"], as_of_tax_year)
    total_receipts = ZERO
    for record in records:
        total_receipts += D(record["destination_sales"]) + sourced_service(reg, record)
    total_receipts = money(total_receipts)
    max_days = 0
    for record in records:
        if record["employee_days_in_state"] > max_days:
            max_days = record["employee_days_in_state"]
    any_unprotected = any(
        (not r["protected_solicitation_only"])
        and (D(r["payroll_compensation"]) > 0 or D(r["property_average_value"]) > 0)
        for r in records
    )
    any_protected = any(r["protected_solicitation_only"] for r in records)

    if any_unprotected and max_days >= reg["economic_nexus_employee_days_threshold"]:
        return "PHYSICAL"
    if total_receipts >= money(reg["economic_nexus_sales_threshold"]):
        return "ECONOMIC"
    if any_protected and total_receipts > 0:
        return "PROTECTED_PL86272"
    return "NONE"


# --------------------------------------------------------------------------
# Group posture and the obligation counter (PRD 2.9)
# --------------------------------------------------------------------------
def compute_posture(group):
    for filing in filings_of_group(group):
        if (filing["preparation_status"] in ("FILED", "AMENDED")
                and D(filing["balance_due"]) > 0
                and D(filing["assessment_added_total"]) > 0):
            return "DELINQUENT"
    if group["open_registration_obligations"] >= 1:
        return "EXPOSED"
    return "COMPLIANT"


def derive_posture(group):
    previous = group["compliance_posture"]
    resolved = compute_posture(group)
    if resolved == previous:
        return
    group["compliance_posture"] = resolved
    mark_dirty(group)
    if previous == "COMPLIANT" and resolved == "EXPOSED":
        for filing in filings_of_group(group):
            if filing["preparation_status"] == "APPROVED":
                filing["preparation_status"] = "IN_REVIEW"
                filing["approver_user_id"] = None
                mark_dirty(filing)


def adjust_obligations(group, delta):
    group["open_registration_obligations"] = group["open_registration_obligations"] + delta
    mark_dirty(group)
    derive_posture(group)


# --------------------------------------------------------------------------
# Registration money pools (PRD 3.6)
# --------------------------------------------------------------------------
def recompute_registration_pools(reg):
    total = ZERO
    unapplied = ZERO
    for payment in payments_of_registration(reg["id"]):
        if payment["status"] in ("RECEIVED", "APPLIED", "UNAPPLIED", "REFUNDED"):
            total += D(payment["amount"])
        if payment["status"] in ("RECEIVED", "UNAPPLIED"):
            unapplied += D(payment["amount"])
    reg["total_payments_received"] = money(total)
    reg["unapplied_payment_balance"] = money(unapplied)


# --------------------------------------------------------------------------
# Modification total, taxable income and tax before credits (PRD 3.5)
# --------------------------------------------------------------------------
def resequence_modifications(filing):
    for index, line in enumerate(modifications_of(filing), start=1):
        line["sequence_number"] = index


def recompute_modification_total(filing):
    total = ZERO
    for line in modifications_of(filing):
        amount = D(line["line_amount"])
        total += amount if line["direction"] == "ADDITION" else -amount
    filing["modification_total"] = money(total)


def recompute_tax_before_credits(filing):
    reg = registration_of_filing(filing)
    recompute_modification_total(filing)
    apportionable = D(filing["federal_taxable_income"]) + D(filing["modification_total"])
    filing["state_taxable_income"] = money(apportionable * D(filing["apportionment_percentage"]))
    filing["tax_before_credits"] = money(D(filing["state_taxable_income"]) * D(reg["tax_rate"]))


# --------------------------------------------------------------------------
# Credit waterfall (PRD 3.5)
# --------------------------------------------------------------------------
def run_credit_waterfall(filing):
    remaining = D(filing["tax_before_credits"])
    current_year = db.clock.year
    applied_total = ZERO
    for claim in claims_of(filing):
        granted = D(claim["granted_amount"])
        if claim["refundable"]:
            applied = granted
        else:
            applied = granted if granted < remaining else remaining
            if applied < 0:
                applied = ZERO
        applied = money(applied)
        remaining = remaining - applied
        if remaining < 0:
            remaining = ZERO
        carryforward = money(granted - applied)
        expired = ZERO
        if filing["tax_year"] + claim["expires_after_years"] < current_year:
            expired = carryforward
            carryforward = ZERO
        if applied == granted:
            status = "FULLY_APPLIED"
        elif applied > 0:
            status = "PARTIALLY_APPLIED"
        elif expired > 0:
            status = "EXPIRED"
        elif carryforward > 0:
            status = "CARRIED_FORWARD"
        else:
            status = "PENDING"
        changed = (
            D(claim["applied_amount"]) != applied
            or D(claim["carryforward_amount"]) != carryforward
            or D(claim["expired_amount"]) != expired
            or claim["status"] != status
        )
        claim["applied_amount"] = applied
        claim["carryforward_amount"] = money(carryforward)
        claim["expired_amount"] = money(expired)
        claim["status"] = status
        if changed and not claim.get("_fresh"):
            mark_dirty(claim)
        applied_total += applied
    filing["credits_applied_total"] = money(applied_total)


def reverse_credit_waterfall(filing):
    """Compensating action driven by amend (PRD 3.7)."""
    for claim in claims_of(filing):
        claim["applied_amount"] = money(0)
        claim["carryforward_amount"] = money(claim["granted_amount"])
        claim["expired_amount"] = money(0)
        claim["status"] = "PENDING"
        mark_dirty(claim)
    filing["credits_applied_total"] = money(0)


# --------------------------------------------------------------------------
# Balance and the settlement axis (PRD 3.5)
# --------------------------------------------------------------------------
def recompute_balance(filing):
    estimated = ZERO
    for payment in db.payments.values():
        if payment.get("applied_filing_id") == filing["id"] and payment["status"] == "APPLIED":
            estimated += D(payment["amount"])
    assessed = ZERO
    for notice in notices_of(filing):
        if notice["status"] in ASSESSMENT_COUNTING_STATUSES:
            assessed += D(notice["assessment_final_amount"])
    filing["estimated_credits_applied"] = money(estimated)
    filing["assessment_added_total"] = money(assessed)
    filing["balance_due"] = money(
        D(filing["tax_before_credits"])
        - D(filing["credits_applied_total"])
        - D(filing["estimated_credits_applied"])
        + D(filing["assessment_added_total"])
    )
    if filing["payment_status"] == "REFUND_CLAIMED":
        return
    balance = D(filing["balance_due"])
    if balance < 0:
        filing["payment_status"] = "OVERPAID"
    elif balance == 0:
        filing["payment_status"] = "PAID"
    elif D(filing["estimated_credits_applied"]) > 0:
        filing["payment_status"] = "PARTIALLY_PAID"
    else:
        filing["payment_status"] = "UNPAID"


def recompute_liability_chain(filing):
    """LINK 2 -> LINK 3 -> LINK 4 of the compute-factors cascade."""
    recompute_tax_before_credits(filing)
    run_credit_waterfall(filing)
    recompute_balance(filing)
    derive_posture(group_of_filing(filing))


# --------------------------------------------------------------------------
# Apportionment factor computation (PRD 3.4)
# --------------------------------------------------------------------------
BASE_WEIGHTS = {
    "EQUAL_WEIGHTED_THREE": {"SALES": Decimal("1"), "PROPERTY": Decimal("1"), "PAYROLL": Decimal("1")},
    "DOUBLE_WEIGHTED_SALES": {"SALES": Decimal("2"), "PROPERTY": Decimal("1"), "PAYROLL": Decimal("1")},
    "SINGLE_SALES_FACTOR": {"SALES": Decimal("1"), "PROPERTY": Decimal("0"), "PAYROLL": Decimal("0")},
}


def included_members(filing):
    reg = registration_of_filing(filing)
    group = group_of_registration(reg)
    if filing["filing_basis"] == "SEPARATE_ENTITY":
        primary = filing.get("primary_legal_entity_id")
        return set([primary]) if primary else set()
    return set(
        e["id"] for e in db.legal_entities.values()
        if e["group_id"] == group["id"] and e["is_unitary_member"]
    )


def compute_factors(filing, variant):
    reg = registration_of_filing(filing)
    group = group_of_registration(reg)
    members = included_members(filing)
    records = [r for r in activity_of(reg["id"], filing["tax_year"])
               if r["legal_entity_id"] in members]
    if not records:
        raise ApiError("ERR_NO_ACTIVITY_RECORDS",
                       "No activity records exist for this return's members and tax year.")

    taxable_members = set(
        r["legal_entity_id"] for r in records if not r["protected_solicitation_only"]
    )
    if variant == "FINNIGAN":
        counting = list(records)
    else:
        counting = [r for r in records if r["legal_entity_id"] in taxable_members]

    nowhere_total = ZERO
    sales_receipts = ZERO
    property_numerator = ZERO
    payroll_numerator = ZERO
    for record in counting:
        sales_receipts += D(record["destination_sales"]) + sourced_service(reg, record)
        if not record["purchaser_taxable_in_state"]:
            nowhere_total += D(record["origin_sales"])
        property_numerator += (D(record["property_average_value"])
                               + RENT_CAPITALIZATION_MULTIPLE * D(record["rented_property_annual_rent"]))
        payroll_numerator += D(record["payroll_compensation"])

    throwback_added = nowhere_total if reg["throwback_rule"] == "THROWBACK" else ZERO
    throwout_removed = nowhere_total if reg["throwback_rule"] == "THROWOUT" else ZERO

    rows = {
        "SALES": {
            "numerator": sales_receipts + throwback_added,
            "denominator": D(group["everywhere_sales"]) - throwout_removed,
            "throwback_added": throwback_added,
            "throwout_removed": throwout_removed,
        },
        "PROPERTY": {
            "numerator": property_numerator,
            "denominator": D(group["everywhere_property"]),
            "throwback_added": ZERO,
            "throwout_removed": ZERO,
        },
        "PAYROLL": {
            "numerator": payroll_numerator,
            "denominator": D(group["everywhere_payroll"]),
            "throwback_added": ZERO,
            "throwout_removed": ZERO,
        },
    }

    base = BASE_WEIGHTS[reg["factor_formula"]]
    weight_denominator = ZERO
    for name, row in rows.items():
        row["included"] = row["denominator"] > 0
        row["ratio"] = factor(row["numerator"] / row["denominator"]) if row["included"] else ZERO
        if row["included"]:
            weight_denominator += base[name]
    if weight_denominator == 0:
        raise ApiError("ERR_FACTOR_DENOMINATOR_ZERO",
                       "No apportionment factor with a non-zero base weight survived exclusion.")

    percentage = ZERO
    for name, row in rows.items():
        row["weight"] = factor(base[name] / weight_denominator) if row["included"] else ZERO
        percentage += D(row["ratio"]) * D(row["weight"])
    percentage = factor(percentage)

    existing = dict((f["factor_type"], f) for f in factors_of(filing))
    for name in ("SALES", "PROPERTY", "PAYROLL"):
        row = rows[name]
        values = {
            "filing_id": filing["id"],
            "factor_type": name,
            "numerator": money(row["numerator"]),
            "denominator": money(row["denominator"]),
            "ratio": D(row["ratio"]),
            "weight": D(row["weight"]),
            "included": bool(row["included"]),
            "throwback_added": money(row["throwback_added"]),
            "throwout_removed": money(row["throwout_removed"]),
        }
        current = existing.get(name)
        if current is None:
            current = new_record()
            current.update(values)
            db.factors[current["id"]] = current
        else:
            changed = any(current.get(k) != v for k, v in values.items())
            current.update(values)
            if changed:
                mark_dirty(current)

    pool = nowhere_total if reg["throwback_rule"] == "NONE" else ZERO
    pool = money(pool)
    if D(group["nowhere_sales_pool"]) != pool:
        group["nowhere_sales_pool"] = pool
        mark_dirty(group)

    filing["apportionment_variant"] = variant
    filing["apportionment_percentage"] = percentage
    filing["_factors_seq"] = db.next_seq()
    recompute_liability_chain(filing)


def factors_are_stale(filing):
    rows = factors_of(filing)
    if not rows:
        return True
    stamp = filing.get("_factors_seq")
    if stamp is None:
        return True
    for record in activity_of(filing["registration_id"], filing["tax_year"]):
        if record["_seq"] > stamp:
            return True
    return False


# --------------------------------------------------------------------------
# Estimated payment safe harbour (PRD 3.6)
# --------------------------------------------------------------------------
def annual_required_amount(reg):
    basis = reg["safe_harbor_basis"]
    if basis == "PRIOR_YEAR_100":
        return money(D(reg["prior_year_tax"]) * Decimal("1.00"))
    if basis == "PRIOR_YEAR_110":
        return money(D(reg["prior_year_tax"]) * Decimal("1.10"))
    return money(D(reg["current_year_estimated_tax"]) * Decimal("0.90"))


def installment_due_date(tax_year, installment_number):
    return midnight_utc(tax_year, INSTALLMENT_DUE_MONTHS[installment_number - 1], INSTALLMENT_DUE_DAY)


def compute_installment_figures(reg, payment):
    annual = annual_required_amount(reg)
    number = payment["installment_number"]
    required = money(annual * Decimal(number) / Decimal(reg["estimated_installment_count"]))
    cumulative = ZERO
    for other in payments_of_registration(reg["id"]):
        if (other["tax_year"] == payment["tax_year"]
                and other["installment_number"] <= number
                and other["status"] in ("RECEIVED", "APPLIED", "UNAPPLIED")):
            cumulative += D(other["amount"])
    underpayment = money(required - cumulative)
    if underpayment < 0:
        underpayment = money(0)
    payment["safe_harbor_required_amount"] = required
    payment["underpayment_amount"] = underpayment
    payment["underpayment_penalty"] = money(underpayment * UNDERPAYMENT_PENALTY_RATE)


# --------------------------------------------------------------------------
# Notice penalty / interest / total (PRD 3.8)
# --------------------------------------------------------------------------
def compute_notice_assessment(notice, sustained_amount, clock):
    from util import days_between
    final_tax = D(notice["assessed_tax"]) - D(sustained_amount)
    penalty = final_tax * NOTICE_PENALTY_RATE
    if penalty > NOTICE_PENALTY_CAP:
        penalty = NOTICE_PENALTY_CAP
    penalty = money(penalty)
    days = days_between(clock, notice["notice_date"])
    interest = money((final_tax + penalty) * NOTICE_INTEREST_RATE * Decimal(days) / DAYS_PER_YEAR)
    notice["penalty_amount"] = penalty
    notice["interest_amount"] = interest
    notice["assessment_final_amount"] = money(final_tax + penalty + interest)


# --------------------------------------------------------------------------
# Voluntary disclosure exposure (PRD 3.9)
# --------------------------------------------------------------------------
def compute_vda_exposure(vda):
    if vda["exposure_variant"] == "LOOKBACK_LIMITED":
        effective = vda["lookback_years"]
    else:
        effective = FULL_EXPOSURE_YEARS
    vda["effective_lookback_years"] = effective
    vda["lookback_end_year"] = vda["anchor_tax_year"]
    vda["lookback_start_year"] = vda["anchor_tax_year"] - effective + 1
    if vda["exposure_variant"] == "LOOKBACK_LIMITED":
        computed = money(D(vda["estimated_exposure_tax"]) * Decimal(effective) / Decimal(FULL_EXPOSURE_YEARS))
        vda["computed_exposure_tax"] = computed
        vda["waived_penalty_amount"] = money(computed * VDA_PENALTY_WAIVER_RATE)
    else:
        vda["computed_exposure_tax"] = money(vda["estimated_exposure_tax"])
        vda["waived_penalty_amount"] = money(0)
