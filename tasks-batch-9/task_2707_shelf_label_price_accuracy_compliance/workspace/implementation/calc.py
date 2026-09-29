"""The twelve calculations. Pure functions over records; single-rounding discipline."""
from datetime import timedelta
from fractions import Fraction

from core import (
    ACTION_WEIGHTS,
    CREDIT_CAP_PCT,
    FL_OZ_PER_GAL,
    FROZEN_FAILED_AUDIT_COUNT,
    FROZEN_OPEN_FINDING_COUNT,
    MIN_CATEGORY_SAMPLE,
    OZ_PER_LB,
    PENALTY_ITEM_CAP,
    REFUND_CREDIT_RATE_BP,
    RESTRICTED_BACKLOG_COUNT,
    SEVERITY_WEIGHTS,
    TASK_WEIGHT_NUMERATOR,
    TASK_WEIGHT_OFFSET,
    num,
    pct2,
    round_frac,
)

UOM_FAMILY = {
    "OZ": "WEIGHT",
    "LB": "WEIGHT",
    "FL_OZ": "VOLUME",
    "GAL": "VOLUME",
    "CT": "COUNT",
    "EACH": "SINGLE",
}


# ---------------------------------------------------------- 1. unit price
def unit_price_basis(qty, uom, rule):
    """Step one: select the basis. Nothing is rounded here."""
    quantity = Fraction(str(qty))
    family = UOM_FAMILY[uom]
    if rule == "PER_SINGLE_ITEM":
        return Fraction(1), "EACH"
    if rule == "PER_100_COUNT" and family == "COUNT":
        return quantity / 100, "100CT"
    if family == "WEIGHT":
        return (quantity / OZ_PER_LB if uom == "OZ" else quantity), "LB"
    if family == "VOLUME":
        return (quantity / FL_OZ_PER_GAL if uom == "FL_OZ" else quantity), "GAL"
    if family == "COUNT":
        return quantity, "CT"
    return Fraction(1), "EACH"


def unit_price_display(line, jurisdiction):
    """Returns (display_cents, basis_qty, basis_uom); all None when basis is zero."""
    basis, label = unit_price_basis(
        line["net_content_qty"], line["net_content_uom"], jurisdiction["unit_price_uom_rule"]
    )
    if basis == 0:
        return None, None, None
    places = max(0, jurisdiction["unit_price_decimal_places"] - 2)
    exact = Fraction(line["new_retail_cents"], 1) / basis
    display = round_frac(exact, places, jurisdiction["unit_price_rounding"])
    return num(display), num(round_frac(basis, 6)), label


def apply_unit_price(line, jurisdiction):
    display, basis, label = unit_price_display(line, jurisdiction)
    return {
        "unit_price_display_cents": display,
        "unit_price_basis_qty": basis,
        "unit_price_basis_uom": label,
    }


def basis_resolves(line, jurisdiction):
    basis, _ = unit_price_basis(
        line["net_content_qty"], line["net_content_uom"], jurisdiction["unit_price_uom_rule"]
    )
    return basis != 0


# ---------------------------------------------------------- 2. due_at / overdue
def label_task_due_at(price_change_file, jurisdiction):
    return price_change_file["effective_date"] + timedelta(
        hours=jurisdiction["grace_period_hours"]
    )


def is_overdue(task, clock_now):
    if task["placement_status"] not in ("UNPLACED", "REJECTED"):
        return False
    if task["due_at"] is None:
        return False
    return clock_now >= task["due_at"]


# ---------------------------------------------------------- 3. audit error rates
def error_rates(sample_size, overcharge_count, undercharge_count):
    """Both variants, always computed, each rounded half up to 2 dp exactly once."""
    if sample_size == 0:
        return None, None
    gross = pct2(overcharge_count + undercharge_count, sample_size)
    net = pct2(max(0, overcharge_count - undercharge_count), sample_size)
    return gross, net


# ---------------------------------------------------------- 4. audit failure action
def audit_failure_action_type(has_issued_written_warning, error_rate_pct, threshold_pct):
    """First-match waterfall."""
    if has_issued_written_warning:
        return "SUSPENSION"
    if Fraction(str(error_rate_pct)) >= Fraction(str(threshold_pct)) * 2:
        return "WRITTEN_WARNING"
    return "COACHING"


# ---------------------------------------------------------- 5. accountability score
def accountability_score(outstanding_weights, verified_placement_count, variant):
    total = sum(outstanding_weights)
    if variant == "TASK_WEIGHTED":
        raw = Fraction(100) - Fraction(
            total * TASK_WEIGHT_NUMERATOR, verified_placement_count + TASK_WEIGHT_OFFSET
        )
        rounded = round_frac(raw, 2) if raw >= 0 else -round_frac(-raw, 2)
        return num(max(Fraction(0), rounded))
    return max(0, 100 - total)


def action_weight(action_type):
    return ACTION_WEIGHTS[action_type]


# ---------------------------------------------------------- 7. posture verdict
def posture_verdict(open_findings, escalated_findings, failed_30d, backlog, signage_violations):
    if (
        escalated_findings >= 1
        or open_findings >= FROZEN_OPEN_FINDING_COUNT
        or failed_30d >= FROZEN_FAILED_AUDIT_COUNT
    ):
        return "FROZEN"
    if (
        open_findings >= 1
        or failed_30d == 1
        or backlog >= RESTRICTED_BACKLOG_COUNT
        or signage_violations >= 1
    ):
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------- 8. penalty exposure
def penalty_components(findings, penalty_per_violation_cents):
    """severity weight x per-violation cents x min(affected_item_count, cap)."""
    parts = {}
    for finding in findings:
        parts[finding["id"]] = (
            SEVERITY_WEIGHTS[finding["severity"]]
            * penalty_per_violation_cents
            * min(finding["affected_item_count"], PENALTY_ITEM_CAP)
        )
    return parts


def penalty_tier(considered_count):
    if considered_count <= 2:
        return 100
    if considered_count <= 5:
        return 125
    return 150


def penalty_exposure(considered, penalty_per_violation_cents, audit_failed, penalty_max_cents):
    """Count -> tier -> components -> sum -> single floor -> cap."""
    parts = penalty_components(considered, penalty_per_violation_cents)
    tier = penalty_tier(len(considered))
    aggravator = 25 if audit_failed else 0
    raw = sum(parts.values())
    scaled = int((Fraction(raw) * (tier + aggravator) / 100).__floor__())
    return min(scaled, penalty_max_cents), parts


# ---------------------------------------------------------- 9. settlement
def refund_credit(refund_liability_cents, penalty_exposure_cents):
    """Two independently floored candidates, then the smaller."""
    from_liability = int(
        (Fraction(refund_liability_cents * REFUND_CREDIT_RATE_BP, 10000)).__floor__()
    )
    from_exposure = int((Fraction(penalty_exposure_cents * CREDIT_CAP_PCT, 100)).__floor__())
    return min(from_liability, from_exposure)


# ---------------------------------------------------------- 10. refund amount
def refund_claim_amount(scan_line, jurisdiction):
    policy = jurisdiction["overcharge_refund_policy"]
    variance = scan_line["register_price_cents"] - scan_line["shelf_price_cents"]
    if policy == "REFUND_DIFFERENCE_PLUS_FIXED":
        gross = variance + jurisdiction["refund_fixed_bonus_cents"]
    elif policy == "ITEM_FREE_UP_TO_CAP":
        gross = scan_line["register_price_cents"]
    else:
        gross = variance
    return min(gross, jurisdiction["refund_cap_cents"]), policy


# ---------------------------------------------------------- 11. category ranking
def category_ranking(scan_lines):
    groups = {}
    for line in scan_lines:
        bucket = groups.setdefault(
            line["category_code"], {"sample_size": 0, "error_count": 0}
        )
        bucket["sample_size"] += 1
        if line["classification"] != "MATCH":
            bucket["error_count"] += 1
    rows = []
    for code, bucket in groups.items():
        if bucket["sample_size"] < MIN_CATEGORY_SAMPLE:
            continue
        rows.append(
            {
                "category_code": code,
                "sample_size": bucket["sample_size"],
                "error_count": bucket["error_count"],
                "error_rate_pct": pct2(bucket["error_count"], bucket["sample_size"]),
            }
        )
    rows.sort(
        key=lambda row: (
            -Fraction(str(row["error_rate_pct"])),
            -row["error_count"],
            row["category_code"],
        )
    )
    return rows


# ---------------------------------------------------------- 12. signage
def missing_disclosures(sign, jurisdiction):
    """Set difference in the jurisdiction's declared order."""
    carried = set(sign["disclosure_codes"] or [])
    return [code for code in jurisdiction["signage_disclosure_codes"] if code not in carried]


SIGNAGE_STATE_PROJECTION = {
    "DRAFT": "NOT_APPLICABLE",
    "REMOVED": "NOT_APPLICABLE",
    "POSTED": "COMPLIANT",
    "EXPIRED_PENDING_REMOVAL": "EXPIRED_NOT_REMOVED",
    "NON_COMPLIANT": "MISSING_DISCLOSURE",
}


def signage_compliance_state(status):
    return SIGNAGE_STATE_PROJECTION[status]
