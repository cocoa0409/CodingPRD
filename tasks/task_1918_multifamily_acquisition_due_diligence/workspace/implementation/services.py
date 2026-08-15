"""Business logic, calculations, rollups, posture derivation."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import clock
import db


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def round_half_up(value):
    """Round a Decimal-compatible numeric to integer cents, half up."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Mutation helper — bump version + updated_at on a common_fields entity
# ---------------------------------------------------------------------------

def touch(entity):
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = db.now_iso()


# ---------------------------------------------------------------------------
# Derived unit flags
# ---------------------------------------------------------------------------

def current_lease(unit_id):
    """Return the unit's current lease (status != SUPERSEDED), or None."""
    for lf in db.lease_files.values():
        if lf["unit_id"] == unit_id and lf["status"] != "SUPERSEDED":
            return lf
    return None


def compute_lease_audited(unit_id):
    lf = current_lease(unit_id)
    if lf is None:
        return False
    return lf["status"] in ("AUDITED", "RESOLVED", "WAIVED")


def compute_walk_accepted(unit_id):
    """True when the unit's latest non-cancelled inspection is QA_ACCEPTED."""
    unit_inspections = [
        i for i in db.inspections.values() if i["unit_id"] == unit_id
    ]
    if not unit_inspections:
        return False
    # latest by created_at (then id tiebreak)
    unit_inspections.sort(key=lambda i: (i["created_at"], i["id"]))
    latest = unit_inspections[-1]
    return latest["status"] == "QA_ACCEPTED"


def compute_deposit_reconciled(unit_id):
    lf = current_lease(unit_id)
    if lf is None:
        return False
    for entry in db.deposits.values():
        if entry["lease_file_id"] == lf["id"] and entry["status"] in (
            "RECONCILED", "ESCROW_QUEUED", "TRANSFERRED"
        ):
            return True
    return False


def recompute_unit(unit, *, propagate=True):
    """Recompute the unit's three readiness flags and compound status."""
    old_status = unit["status"]
    if old_status == "EXCLUDED":
        return
    unit["lease_audited"] = compute_lease_audited(unit["id"])
    unit["walk_accepted"] = compute_walk_accepted(unit["id"])
    unit["deposit_reconciled"] = compute_deposit_reconciled(unit["id"])
    any_true = unit["lease_audited"] or unit["walk_accepted"] or unit["deposit_reconciled"]
    all_true = unit["lease_audited"] and unit["walk_accepted"] and unit["deposit_reconciled"]

    new_status = old_status
    if old_status == "REGISTERED" and any_true:
        new_status = "CLEARING"
    if old_status == "CLEARING" and all_true:
        new_status = "VERIFIED"
    if old_status == "VERIFIED" and not all_true:
        new_status = "CLEARING"
    if old_status == "CLEARING" and not any_true:
        # no regression to REGISTERED defined; stay CLEARING
        new_status = "CLEARING"
    if new_status != old_status:
        unit["status"] = new_status
        touch(unit)
    if propagate:
        acq = db.acquisitions.get(unit["acquisition_id"])
        if acq is not None:
            recompute_acquisition(acq)


# ---------------------------------------------------------------------------
# Acquisition rollups + posture
# ---------------------------------------------------------------------------

SEVERITY_MULTIPLIERS = {1: Decimal("1.00"), 2: Decimal("1.00"),
                        3: Decimal("1.15"), 4: Decimal("1.25"), 5: Decimal("1.40")}
CATEGORY_LOADING = {"LIFE_SAFETY": 15000, "CODE_COMPLIANCE": 5000,
                    "MAJOR_SYSTEMS": 0, "COSMETIC": 0}
AT_RISK_PCT = Decimal("0.03")
BLOCKED_PCT = Decimal("0.05")
RENT_VARIANCE_THRESHOLD_CENTS = 500


def compute_verified_cost(acq, finding):
    basis = acq.get("maintenance_estimate_basis", "INSPECTOR_BASIS")
    base = finding["inspector_estimate_cents"] if basis == "INSPECTOR_BASIS" else finding["seller_estimate_cents"]
    mult = SEVERITY_MULTIPLIERS[finding["severity"]]
    product = round_half_up(Decimal(base) * mult)
    return product + CATEGORY_LOADING[finding["category"]]


def recompute_deferred_maintenance(acq):
    total = 0
    for f in db.findings.values():
        if f["status"] != "VERIFIED":
            continue
        insp = db.inspections.get(f["inspection_id"])
        if insp is None:
            continue
        unit = db.units.get(insp["unit_id"])
        if unit is None or unit["status"] == "EXCLUDED":
            continue
        total += f.get("verified_cost_cents") or 0
    if acq["deferred_maintenance_total_cents"] != total:
        acq["deferred_maintenance_total_cents"] = total


def recompute_rent_roll_variance(acq):
    total = 0
    for lf in db.lease_files.values():
        if lf["status"] != "DISCREPANCY_FLAGGED":
            continue
        unit = db.units.get(lf["unit_id"])
        if unit is None or unit["acquisition_id"] != acq["id"]:
            continue
        if unit["status"] == "EXCLUDED":
            continue
        total += lf.get("variance_cents") or 0
    if acq["rent_roll_variance_cents"] != total:
        acq["rent_roll_variance_cents"] = total


def recompute_deposit_variance(acq):
    total = 0
    for entry in db.deposits.values():
        if entry["status"] != "DISPUTED":
            continue
        lf = db.lease_files.get(entry["lease_file_id"])
        if lf is None:
            continue
        unit = db.units.get(lf["unit_id"])
        if unit is None or unit["acquisition_id"] != acq["id"]:
            continue
        total += entry.get("variance_cents") or 0
    if acq["deposit_variance_cents"] != total:
        acq["deposit_variance_cents"] = total


def recompute_payroll_accrual(acq):
    total = 0
    for d in db.employee_decisions.values():
        if d["acquisition_id"] != acq["id"]:
            continue
        if d["decision"] in ("TERMINATE", "TRANSFER") and d["status"] in ("APPROVED", "NOTIFIED"):
            total += (d.get("severance_cents") or 0) + (d.get("pto_payout_cents") or 0)
    if acq["payroll_accrual_cents"] != total:
        acq["payroll_accrual_cents"] = total


def recompute_net_proration(acq):
    total = 0
    for s in db.proration_statements.values():
        if s["acquisition_id"] != acq["id"]:
            continue
        if s["status"] in ("APPROVED", "SETTLED"):
            total += s.get("net_amount_cents") or 0
    if acq["net_proration_cents"] != total:
        acq["net_proration_cents"] = total


def compute_posture(acq):
    # BLOCKED conditions
    for lf in db.lease_files.values():
        if lf["status"] == "DISCREPANCY_FLAGGED":
            unit = db.units.get(lf["unit_id"])
            if unit is not None and unit["acquisition_id"] == acq["id"] and unit["status"] != "EXCLUDED":
                return "BLOCKED"
    for entry in db.deposits.values():
        if entry["status"] == "DISPUTED":
            lf = db.lease_files.get(entry["lease_file_id"])
            if lf is not None:
                unit = db.units.get(lf["unit_id"])
                if unit is not None and unit["acquisition_id"] == acq["id"]:
                    return "BLOCKED"
    blocked_threshold = round_half_up(Decimal(acq["agreed_purchase_price_cents"]) * BLOCKED_PCT)
    if acq["deferred_maintenance_total_cents"] > blocked_threshold:
        return "BLOCKED"
    # AT_RISK conditions
    at_risk_threshold = round_half_up(Decimal(acq["agreed_purchase_price_cents"]) * AT_RISK_PCT)
    if acq["deferred_maintenance_total_cents"] > at_risk_threshold:
        return "AT_RISK"
    for insp in db.inspections.values():
        if insp["status"] == "QA_REJECTED":
            unit = db.units.get(insp["unit_id"])
            if unit is not None and unit["acquisition_id"] == acq["id"]:
                return "AT_RISK"
    for c in db.concessions.values():
        if c["verification_status"] == "PENDING":
            lf = db.lease_files.get(c["lease_file_id"])
            if lf is not None:
                unit = db.units.get(lf["unit_id"])
                if unit is not None and unit["acquisition_id"] == acq["id"]:
                    return "AT_RISK"
    return "ON_TRACK"


def recompute_acquisition(acq, *, touch_if_changed=False):
    """Recompute all rollups and posture for an acquisition."""
    before = (
        acq.get("deferred_maintenance_total_cents"),
        acq.get("rent_roll_variance_cents"),
        acq.get("deposit_variance_cents"),
        acq.get("payroll_accrual_cents"),
        acq.get("net_proration_cents"),
        acq.get("readiness_posture"),
    )
    recompute_deferred_maintenance(acq)
    recompute_rent_roll_variance(acq)
    recompute_deposit_variance(acq)
    recompute_payroll_accrual(acq)
    recompute_net_proration(acq)
    acq["readiness_posture"] = compute_posture(acq)
    after = (
        acq.get("deferred_maintenance_total_cents"),
        acq.get("rent_roll_variance_cents"),
        acq.get("deposit_variance_cents"),
        acq.get("payroll_accrual_cents"),
        acq.get("net_proration_cents"),
        acq.get("readiness_posture"),
    )
    if touch_if_changed and before != after:
        touch(acq)


# ---------------------------------------------------------------------------
# Lease calculations
# ---------------------------------------------------------------------------

def recompute_lease_variance(lease):
    """Recompute lease.variance_cents from the unit's rent roll entry, if any."""
    entry = None
    for e in db.rent_roll_entries.values():
        if e["unit_id"] == lease["unit_id"]:
            entry = e
            break
    if entry is None:
        lease["variance_cents"] = None
        return
    lease["variance_cents"] = entry["reported_rent_cents"] - lease["contract_rent_cents"]


def recompute_net_effective_rent(lease):
    verified_total = 0
    for c in db.concessions.values():
        if c["lease_file_id"] == lease["id"] and c["verification_status"] == "VERIFIED":
            verified_total += c.get("verified_value_cents") or 0
    gross = lease["contract_rent_cents"] * lease["term_months"]
    net = gross - verified_total
    lease["net_effective_rent_cents"] = round_half_up(Decimal(net) / Decimal(lease["term_months"]))


# ---------------------------------------------------------------------------
# Deposits
# ---------------------------------------------------------------------------

def compute_deposit_fields(acq, entry):
    """Compute verified_amount_cents (if not set), accrued_interest_cents, variance_cents."""
    lease = db.lease_files.get(entry["lease_file_id"])
    if lease is None:
        return
    verified = entry.get("verified_amount_cents")
    if verified is None:
        verified = lease["deposit_amount_cents"]
        entry["verified_amount_cents"] = verified
    if not entry["interest_required"]:
        entry["accrued_interest_cents"] = 0
    else:
        rate = Decimal(str(entry.get("annual_interest_rate", 0)))
        start = clock.parse_iso(lease["lease_start_date"])
        close = clock.parse_iso(acq["closing_date"])
        days = clock.calendar_days_between(start, close)
        method = acq.get("interest_accrual_method", "DAILY_ACCRUAL")
        if method == "SIMPLE_ANNUAL":
            whole_years = days // 365
            acc = Decimal(verified) * rate * Decimal(whole_years)
        else:  # DAILY_ACCRUAL
            acc = Decimal(verified) * rate * Decimal(days) / Decimal(365)
        entry["accrued_interest_cents"] = round_half_up(acc)
    entry["variance_cents"] = (
        entry["verified_amount_cents"] + entry["accrued_interest_cents"]
        - entry["seller_stated_amount_cents"]
    )


# ---------------------------------------------------------------------------
# Severance and PTO
# ---------------------------------------------------------------------------

def compute_compensation(decision):
    """Compute severance_cents / pto_payout_cents / assumed_pto_liability_cents."""
    hire = clock.parse_iso(decision["hire_date"])
    effective = clock.parse_iso(decision["effective_date"])
    tenure_days = clock.calendar_days_between(hire, effective)
    tenure_years = tenure_days // 365

    weekly = round_half_up(Decimal(decision["annual_salary_cents"]) / Decimal(52))
    hourly = round_half_up(Decimal(decision["annual_salary_cents"]) / Decimal(2080))

    pto_hours = Decimal(str(decision.get("accrued_pto_hours", 0)))

    if decision["decision"] == "RETAIN":
        decision["severance_cents"] = 0
        decision["pto_payout_cents"] = 0
        decision["assumed_pto_liability_cents"] = round_half_up(pto_hours * Decimal(hourly))
    else:
        if tenure_years == 0:
            weeks = 0
        elif tenure_years in (1, 2):
            weeks = 1
        elif tenure_years in (3, 4, 5):
            weeks = 2
        else:
            weeks = 3
        severance = weeks * weekly
        pto = round_half_up(pto_hours * Decimal(hourly))
        cap = 8 * weekly
        if severance + pto > cap:
            pto = cap - severance
        decision["severance_cents"] = severance
        decision["pto_payout_cents"] = pto
        decision["assumed_pto_liability_cents"] = 0


# ---------------------------------------------------------------------------
# Insurance loss ratio
# ---------------------------------------------------------------------------

def compute_loss_ratio(policy):
    premium3 = policy["annual_premium_cents"] * 3
    if premium3 == 0:
        # avoid division by zero; treat as 0 ratio -> LOW
        policy["loss_ratio"] = 0.0
        policy["risk_tier"] = "LOW"
        return
    ratio = Decimal(policy["loss_run_total_cents"]) / Decimal(premium3)
    policy["loss_ratio"] = float(ratio)
    if ratio < Decimal("0.40"):
        policy["risk_tier"] = "LOW"
    elif ratio < Decimal("0.80"):
        policy["risk_tier"] = "ELEVATED"
    else:
        policy["risk_tier"] = "HIGH"


# ---------------------------------------------------------------------------
# Utility expense trailing window
# ---------------------------------------------------------------------------

def _trailing_window_bounds(now_dt):
    """Return (start_date, end_date) as (first day of month 12 months back, last day of prev month)."""
    y, m = now_dt.year, now_dt.month
    # window = 12 complete calendar months strictly before current month
    # end = last day of previous month
    if m == 1:
        end_year, end_month = y - 1, 12
    else:
        end_year, end_month = y, m - 1
    # start = first day of (end_month - 11)
    start_month_index = (end_year * 12 + (end_month - 1)) - 11
    start_year, start_month0 = divmod(start_month_index, 12)
    start_month = start_month0 + 1
    start = date(start_year, start_month, 1)
    # end: last day of end_month
    if end_month == 12:
        next_first = date(end_year + 1, 1, 1)
    else:
        next_first = date(end_year, end_month + 1, 1)
    end = date.fromordinal(next_first.toordinal() - 1)
    return start, end


def utility_records_in_window(acquisition_id):
    """Return list of records (any source) whose period_month lies in the trailing window."""
    now = clock.now_clock_dt()
    start, end = _trailing_window_bounds(now)
    out = []
    for r in db.utility_records.values():
        if r["acquisition_id"] != acquisition_id:
            continue
        try:
            y, m = r["period_month"].split("-")
            rd = date(int(y), int(m), 1)
        except Exception:
            continue
        if start <= rd <= end:
            out.append(r)
    return out


def compute_utility_outlier(acquisition_id, record):
    """Compute is_outlier and normalized_amount_cents for one record based on category peers."""
    # PRD §3.5: ESTIMATE rows are excluded from averages, from sums, and from
    # outlier math — the outlier test is never applied to them.
    if record["source"] == "ESTIMATE":
        record["is_outlier"] = False
        record["normalized_amount_cents"] = record["amount_cents"]
        return
    window = utility_records_in_window(acquisition_id)
    peers = [
        r for r in window
        if r["category"] == record["category"]
        and r["source"] in ("SELLER_T12", "BILL_AUDIT")
        and r["id"] != record["id"]
    ]
    if not peers:
        # no basis — not an outlier
        record["is_outlier"] = False
        record["normalized_amount_cents"] = record["amount_cents"]
        return
    avg = round_half_up(
        Decimal(sum(p["amount_cents"] for p in peers)) / Decimal(len(peers))
    )
    upper = Decimal(avg) * Decimal("1.20")
    lower = Decimal(avg) * Decimal("0.80")
    amt = Decimal(record["amount_cents"])
    outlier = (amt > upper) or (amt < lower)
    record["is_outlier"] = outlier
    record["normalized_amount_cents"] = avg if outlier else record["amount_cents"]


def expense_summary(acquisition_id):
    """Compute the trailing-12 expense summary."""
    window = utility_records_in_window(acquisition_id)
    included = [r for r in window if r["source"] in ("SELLER_T12", "BILL_AUDIT")]
    categories = ["ELECTRIC", "GAS", "WATER_SEWER", "TRASH", "OTHER"]
    by_category = []
    total_raw = 0
    total_norm = 0
    outlier_count = 0
    for cat in categories:
        rows = [r for r in included if r["category"] == cat]
        raw_sum = sum(r["amount_cents"] for r in rows)
        norm_sum = 0
        cat_outliers = 0
        for r in rows:
            # recompute against peers inside the window excluding self
            peers = [p for p in rows if p["id"] != r["id"]]
            if peers:
                avg = round_half_up(
                    Decimal(sum(p["amount_cents"] for p in peers)) / Decimal(len(peers))
                )
                upper = Decimal(avg) * Decimal("1.20")
                lower = Decimal(avg) * Decimal("0.80")
                amt = Decimal(r["amount_cents"])
                outlier = (amt > upper) or (amt < lower)
            else:
                avg = r["amount_cents"]
                outlier = False
            if outlier:
                cat_outliers += 1
                norm_sum += avg
            else:
                norm_sum += r["amount_cents"]
        total_raw += raw_sum
        total_norm += norm_sum
        outlier_count += cat_outliers
        by_category.append({
            "category": cat,
            "raw_cents": raw_sum,
            "normalized_cents": norm_sum,
            "row_count": len(rows),
            "outlier_count": cat_outliers,
        })
    return {
        "total_t12_raw_cents": total_raw,
        "total_t12_normalized_cents": total_norm,
        "outlier_count": outlier_count,
        "by_category": by_category,
    }


# ---------------------------------------------------------------------------
# Tax reassessment projection
# ---------------------------------------------------------------------------

def compute_tax_projection(acq, proj):
    if proj["method"] == "PURCHASE_PRICE_ANCHORED":
        proj["projected_value_cents"] = acq["agreed_purchase_price_cents"]
    else:  # INCOME_APPROACH
        proj["projected_value_cents"] = round_half_up(
            Decimal(proj["noi_t12_cents"]) / Decimal(str(proj["cap_rate"]))
        )
    proj["projected_assessed_value_cents"] = round_half_up(
        Decimal(proj["projected_value_cents"]) * Decimal(str(acq["assessment_ratio"]))
    )
    proj["projected_annual_tax_cents"] = round_half_up(
        Decimal(proj["projected_assessed_value_cents"])
        * Decimal(str(acq["millage_rate"])) / Decimal(1000)
    )
    proj["delta_vs_prior_cents"] = (
        proj["projected_annual_tax_cents"] - acq["prior_year_tax_cents"]
    )


# ---------------------------------------------------------------------------
# Proration statement generation
# ---------------------------------------------------------------------------

def generate_statement_lines(acq, statement):
    """Generate the GENERATED lines for a new statement per closing_proration rules."""
    lines = []
    closing = clock.parse_iso(acq["closing_date"])
    closing_date = closing.date()
    method = statement["day_count_method"]

    # --- RENT lines: one per non-EXCLUDED unit with current lease in {AUDITED, RESOLVED, WAIVED}
    rent_inputs = []
    for unit in db.units.values():
        if unit["acquisition_id"] != acq["id"]:
            continue
        if unit["status"] == "EXCLUDED":
            continue
        lf = current_lease(unit["id"])
        if lf is None:
            continue
        if lf["status"] not in ("AUDITED", "RESOLVED", "WAIVED"):
            continue
        rent_inputs.append((unit, lf))
    # order by unit_number ASC, tie-break lease created_at ASC
    rent_inputs.sort(key=lambda t: (t[0]["unit_number"], t[1]["created_at"]))

    if method == "ACTUAL_365":
        # period = closing month (first day .. last day)
        period_start = date(closing_date.year, closing_date.month, 1)
        if closing_date.month == 12:
            next_first = date(closing_date.year + 1, 1, 1)
        else:
            next_first = date(closing_date.year, closing_date.month + 1, 1)
        period_end = date.fromordinal(next_first.toordinal() - 1)
        seller_days = (closing_date - period_start).days  # period_start .. closing-1
        buyer_days = (period_end - closing_date).days + 1  # closing .. period_end incl
        for unit, lf in rent_inputs:
            daily = round_half_up(Decimal(lf["contract_rent_cents"]) * Decimal(12) / Decimal(365))
            amount = daily * buyer_days
            lines.append({
                "line_type": "RENT",
                "direction": "CREDIT_BUYER",
                "amount_cents": amount,
                "source_kind": "GENERATED",
                "source_ref_type": "LEASE_FILE",
                "source_ref_id": lf["id"],
                "memo": None,
            })
    else:  # BANKERS_30_360
        closing_dom = closing_date.day
        seller_days = closing_dom - 1
        buyer_days = 30 - closing_dom + 1
        for unit, lf in rent_inputs:
            daily = round_half_up(Decimal(lf["contract_rent_cents"]) / Decimal(30))
            amount = daily * buyer_days
            lines.append({
                "line_type": "RENT",
                "direction": "CREDIT_BUYER",
                "amount_cents": amount,
                "source_kind": "GENERATED",
                "source_ref_type": "LEASE_FILE",
                "source_ref_id": lf["id"],
                "memo": None,
            })

    # --- TAX line: requires APPROVED projection
    approved_proj = None
    for p in db.tax_projections.values():
        if p["acquisition_id"] == acq["id"] and p["status"] == "APPROVED":
            approved_proj = p
            break
    if approved_proj is not None:
        jan1 = date(closing_date.year, 1, 1)
        seller_days_ytd = (closing_date - jan1).days  # Jan 1 .. closing-1
        amount = round_half_up(
            Decimal(approved_proj["projected_annual_tax_cents"]) * Decimal(seller_days_ytd) / Decimal(365)
        )
        lines.append({
            "line_type": "TAX",
            "direction": "CREDIT_BUYER",
            "amount_cents": amount,
            "source_kind": "GENERATED",
            "source_ref_type": "TAX_PROJECTION",
            "source_ref_id": None,
            "memo": None,
        })

    # --- PREPAID_EXPENSE lines (CREDIT_SELLER), ordered by source entity created_at ASC
    prepaid_sources = []
    for c in db.service_contracts.values():
        if c["acquisition_id"] != acq["id"]:
            continue
        if c["status"] != "ASSUMED":
            continue
        ptd = c.get("prepaid_through_date")
        if not ptd:
            continue
        ptd_date = clock.parse_iso(ptd).date()
        if ptd_date > closing_date:
            prepaid_sources.append(("SERVICE_CONTRACT", c, c["created_at"]))
    for p in db.insurance_policies.values():
        if p["acquisition_id"] != acq["id"]:
            continue
        if p["status"] != "ASSUMED":
            continue
        ptd = p.get("prepaid_through_date")
        if not ptd:
            continue
        ptd_date = clock.parse_iso(ptd).date()
        if ptd_date > closing_date:
            prepaid_sources.append(("INSURANCE_POLICY", p, p["created_at"]))
    prepaid_sources.sort(key=lambda t: t[2])

    for kind, src, _created in prepaid_sources:
        ptd_date = clock.parse_iso(src["prepaid_through_date"]).date()
        days = (ptd_date - closing_date).days  # closing+1 .. prepaid_through
        if kind == "SERVICE_CONTRACT":
            daily = round_half_up(Decimal(src["monthly_cost_cents"]) * Decimal(12) / Decimal(365))
        else:
            daily = round_half_up(Decimal(src["annual_premium_cents"]) / Decimal(365))
        amount = daily * days
        lines.append({
            "line_type": "PREPAID_EXPENSE",
            "direction": "CREDIT_SELLER",
            "amount_cents": amount,
            "source_kind": "GENERATED",
            "source_ref_type": kind,
            "source_ref_id": src["id"],
            "memo": None,
        })

    # --- DEPOSIT_TRANSFER line (single, CREDIT_BUYER)
    deposit_total = 0
    has_deposit = False
    for entry in db.deposits.values():
        if entry["status"] not in ("ESCROW_QUEUED", "TRANSFERRED"):
            continue
        lf = db.lease_files.get(entry["lease_file_id"])
        if lf is None:
            continue
        unit = db.units.get(lf["unit_id"])
        if unit is None or unit["acquisition_id"] != acq["id"]:
            continue
        has_deposit = True
        deposit_total += (entry.get("verified_amount_cents") or 0) + (entry.get("accrued_interest_cents") or 0)
    if has_deposit:
        lines.append({
            "line_type": "DEPOSIT_TRANSFER",
            "direction": "CREDIT_BUYER",
            "amount_cents": deposit_total,
            "source_kind": "GENERATED",
            "source_ref_type": "DEPOSIT_ENTRY",
            "source_ref_id": None,
            "memo": None,
        })

    # --- PAYROLL line (single, CREDIT_BUYER)
    payroll_total = 0
    has_payroll = False
    for d in db.employee_decisions.values():
        if d["acquisition_id"] != acq["id"]:
            continue
        if d["decision"] == "RETAIN" and d["status"] in ("APPROVED", "NOTIFIED", "EFFECTIVE"):
            has_payroll = True
            payroll_total += d.get("assumed_pto_liability_cents") or 0
    if has_payroll:
        lines.append({
            "line_type": "PAYROLL",
            "direction": "CREDIT_BUYER",
            "amount_cents": payroll_total,
            "source_kind": "GENERATED",
            "source_ref_type": "EMPLOYEE_DECISION",
            "source_ref_id": None,
            "memo": None,
        })

    return lines


def recompute_statement_totals(statement):
    lines = [l for l in db.proration_lines.values() if l["statement_id"] == statement["id"]]
    buyer = sum(l["amount_cents"] for l in lines if l["direction"] == "CREDIT_BUYER")
    seller = sum(l["amount_cents"] for l in lines if l["direction"] == "CREDIT_SELLER")
    statement["total_buyer_credits_cents"] = buyer
    statement["total_seller_credits_cents"] = seller
    statement["net_amount_cents"] = buyer - seller


def check_statement_drift(acq, statement):
    """Recompute each of the statement's GENERATED lines from live data;
    return True if any drift exists (PRD §3.8 approve-time snapshot check).

    Only §3.8 generated line kinds participate (RENT, TAX, PREPAID_EXPENSE,
    DEPOSIT_TRANSFER, PAYROLL). Operator-appended MANUAL lines and
    apply-posted ADJUSTMENT lines (PRD §3.12) are not recomputed — a
    POST_CLOSING_TRUEUP statement created by an adjustment apply carries
    only ADJUSTMENT lines, so its drift check is vacuous and the
    §3.1 settlement flow stays reachable.
    """
    expected_lines = generate_statement_lines(acq, statement)
    expected_by_key = {}
    for e in expected_lines:
        key = (e["line_type"], e["direction"], e["source_ref_type"],
               e.get("source_ref_id"))
        expected_by_key[key] = e
    stored_generated = [
        l for l in db.proration_lines.values()
        if l["statement_id"] == statement["id"]
        and l["source_kind"] == "GENERATED"
        and l["line_type"] != "ADJUSTMENT"
    ]
    for act in stored_generated:
        key = (act["line_type"], act["direction"], act["source_ref_type"],
               act.get("source_ref_id"))
        exp = expected_by_key.get(key)
        if exp is None or exp["amount_cents"] != act["amount_cents"]:
            return True
    return False
