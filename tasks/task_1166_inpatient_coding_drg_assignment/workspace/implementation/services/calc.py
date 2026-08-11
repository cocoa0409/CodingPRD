"""Calculation rules (SCAFFOLD §1.3) and cascade operations."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import now, stamp_new, store, touch
from services.core import (ACUITY_PRIORITY, ACUITY_WEIGHT,
                           NON_TERMINAL_ASSIGNMENT, active_dx_lines,
                           assignment_for_chart, bill_for_account,
                           case_for_chart, chart_for_account, proc_lines)

# ---- weight tables / constants ----
MS_WEIGHT = {
    "WITHOUT_CC_MCC": Decimal("1.0000"),
    "WITH_CC": Decimal("1.4000"),
    "WITH_MCC": Decimal("2.1000"),
}
AP_WEIGHT = {
    "SOI_1": Decimal("0.9000"),
    "SOI_2": Decimal("1.2000"),
    "SOI_3": Decimal("1.8000"),
    "SOI_4": Decimal("2.5000"),
}
BASE_RATE_CENTS = 650000
COST_CHARGE_RATIO = Decimal("0.30")
OUTLIER_FIXED_LOSS_CENTS = 500000
OUTLIER_SHARE = Decimal("0.80")

PRODUCTIVITY_BASIS_DAYS = 30
ACCURACY_FLAG_THRESHOLD = Decimal("0.9500")

DNFB_DEFAULT_THRESHOLD_DAYS = 3
TIMELY_FILING_DAYS = 120


def _round0(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- calculations.queue_priority_score ----
def compute_priority_score(account, chart):
    seconds = (now() - account["discharge_at"]).total_seconds()
    days = int(seconds // 86400)  # truncated down to whole days
    if days <= 2:
        base = 10
    elif days <= 5:
        base = 40
    elif days <= 10:
        base = 70
    else:
        base = 100
    amount_w = min(30, account["total_charges_cents"] // 100000)
    acuity_w = ACUITY_PRIORITY[chart["acuity"]]
    dnfb_boost = 25 if account["dnfb_flag"] else 0
    return min(150, base + amount_w + acuity_w + dnfb_boost)


# ---- calculations.drg_grouping ----
def compute_grouping(chart_id, variant):
    """Returns (base_partition, severity_level, relative_weight Decimal)."""
    base_partition = ("SURGICAL" if any(p["is_or"] for p in proc_lines(chart_id))
                      else "MEDICAL")
    eligible = [l for l in active_dx_lines(chart_id)
                if not l["is_principal"] and l["cc_level"] != "NONE" and l["poa"] != "N"]
    if variant == "MS_DRG":
        if any(l["cc_level"] == "MCC" for l in eligible):
            severity = "WITH_MCC"
        elif any(l["cc_level"] == "CC" for l in eligible):
            severity = "WITH_CC"
        else:
            severity = "WITHOUT_CC_MCC"
        weight = MS_WEIGHT[severity]
    else:  # AP_DRG
        pts = sum(2 if l["cc_level"] == "MCC" else 1 for l in eligible)
        if pts >= 4:
            severity = "SOI_4"
        elif pts == 3:
            severity = "SOI_3"
        elif pts >= 1:
            severity = "SOI_2"
        else:
            severity = "SOI_1"
        weight = AP_WEIGHT[severity]
    return base_partition, severity, weight


# ---- calculations.expected_reimbursement (pinned rounding order) ----
def compute_expected_reimbursement(relative_weight: Decimal, total_charges_cents: int) -> int:
    drg_payment = _round0(Decimal(BASE_RATE_CENTS) * relative_weight)
    cost_estimate = _round0(Decimal(total_charges_cents) * COST_CHARGE_RATIO)
    outlier_threshold = drg_payment + OUTLIER_FIXED_LOSS_CENTS
    outlier_payment = _round0(Decimal(max(0, cost_estimate - outlier_threshold)) * OUTLIER_SHARE)
    return drg_payment + outlier_payment


# ---- CodedCase recompute + bill mirror refresh (regroup / finding-apply / re-submit) ----
def regroup_case(case):
    chart = store.charts[case["chart_id"]]
    account = store.accounts[chart["account_id"]]
    bp, severity, weight = compute_grouping(chart["id"], case["grouper_variant"])
    case["base_partition"] = bp
    case["severity_level"] = severity
    case["relative_weight"] = weight
    case["expected_reimbursement_cents"] = compute_expected_reimbursement(
        weight, account["total_charges_cents"])
    principal = next((l for l in active_dx_lines(chart["id"]) if l["is_principal"]), None)
    if principal is not None:
        case["principal_dx_id"] = principal["id"]
    touch(case)
    bill = bill_for_account(account["id"])
    if bill is not None and bill["status"] in ("DRAFT", "READY"):
        bill["expected_reimbursement_cents"] = case["expected_reimbursement_cents"]
        touch(bill)
    return case


# ---- calculations.coder_productivity ----
def recompute_productivity(coder):
    coder["productivity_units_per_day"] = float(
        (Decimal(coder["accepted_weighted_units"]) / Decimal(PRODUCTIVITY_BASIS_DAYS))
        .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def coder_debit_workload(coder, chart):
    coder["workload_units"] += ACUITY_WEIGHT[chart["acuity"]]
    touch(coder)


def coder_credit_workload(coder, chart):
    coder["workload_units"] -= ACUITY_WEIGHT[chart["acuity"]]
    touch(coder)


def coder_record_accept(coder, chart):
    w = ACUITY_WEIGHT[chart["acuity"]]
    coder["workload_units"] -= w
    coder["accepted_count"] += 1
    coder["accepted_weighted_units"] += w
    recompute_productivity(coder)
    touch(coder)


# ---- chart readiness interlock (discharge OR last deficiency resolved) ----
# Caller is responsible for a single touch() on the chart per request.
def maybe_ready_chart(chart):
    if chart["status"] != "OPEN" or chart["open_deficiency_count"] != 0:
        return
    account = store.accounts[chart["account_id"]]
    if account["status"] == "DISCHARGED":
        chart["status"] = "READY_FOR_CODING"


# ---- calculations.dnfb_aging_scan ----
def dnfb_candidates():
    out = []
    for a in store.accounts.values():
        if a["status"] != "DISCHARGED":
            continue
        bill = bill_for_account(a["id"])
        if bill is not None and bill["status"] not in ("DRAFT", "READY"):
            continue
        out.append(a)
    return out


def dnfb_days(account, as_of):
    return (as_of - account["discharge_at"]).total_seconds() / 86400.0


def dnfb_order_key(account, as_of):
    bill = bill_for_account(account["id"])
    expected = 0
    if bill is not None and bill["expected_reimbursement_cents"] is not None:
        expected = bill["expected_reimbursement_cents"]
    return (-dnfb_days(account, as_of), -expected,
            account["created_at"], account["_seq"])


def run_sweep(threshold_days, as_of):
    """Flags newly-aged accounts; returns the created DnfbSweep resource."""
    newly = [a for a in dnfb_candidates()
             if dnfb_days(a, as_of) >= threshold_days and not a["dnfb_flag"]]
    for a in newly:
        a["dnfb_flag"] = True
        a["dnfb_flagged_at"] = as_of
        touch(a)
    newly.sort(key=lambda a: dnfb_order_key(a, as_of))
    total = 0
    for a in newly:
        bill = bill_for_account(a["id"])
        if bill is not None and bill["expected_reimbursement_cents"] is not None:
            total += bill["expected_reimbursement_cents"]
    # feed back into the coding queue: recompute priorities on flagged charts
    for a in newly:
        chart = chart_for_account(a["id"])
        if chart is None:
            continue
        asg = assignment_for_chart(chart["id"], statuses=NON_TERMINAL_ASSIGNMENT)
        if asg is not None:
            asg["priority_score"] = compute_priority_score(a, chart)
            touch(asg)
    sweep = stamp_new({
        "threshold_days": threshold_days,
        "as_of": as_of,
        "flagged_count": len(newly),
        "flagged_account_ids": [a["id"] for a in newly],
        "total_outstanding_cents": total,
    })
    store.sweeps[sweep["id"]] = sweep
    return sweep


# ---- audit sampling (§3.8) ----
def sample_cases(subject_coder_id, window_start, window_end, sample_size):
    matches = []
    for case in store.coded_cases.values():
        asg = assignment_for_chart(case["chart_id"])
        if asg is None or asg["coder_id"] != subject_coder_id:
            continue
        accepted_at = asg["accepted_at"]
        if accepted_at is None:
            continue
        if window_start <= accepted_at < window_end:
            matches.append(case)
    matches.sort(key=lambda c: (-c["expected_reimbursement_cents"],
                                c["created_at"], c["_seq"]))
    return [c["id"] for c in matches[:sample_size]]


# ---- calculations.coder_accuracy_score (both variants, at audit complete) ----
def compute_accuracy(audit):
    applied = [f for f in store.findings.values()
               if f["audit_id"] == audit["id"] and f["status"] == "APPLIED"]
    incorrect_lines = len(applied)
    delta_sum = sum(abs(f["delta_reimbursement_cents"] or 0) for f in applied)
    total_lines = 0
    corrected_expected_sum = 0
    for case_id in audit["sampled_case_ids"]:
        case = store.coded_cases.get(case_id)
        if case is None:
            continue
        chart_id = case["chart_id"]
        total_lines += len(active_dx_lines(chart_id)) + len(proc_lines(chart_id))
        corrected_expected_sum += case["expected_reimbursement_cents"] or 0
    if total_lines > 0:
        code_based = Decimal(1) - (Decimal(incorrect_lines) / Decimal(total_lines))
    else:
        code_based = Decimal(1)
    if corrected_expected_sum > 0:
        ratio = Decimal(delta_sum) / Decimal(corrected_expected_sum)
        if ratio > 1:
            ratio = Decimal(1)
        financial = Decimal(1) - ratio
    else:
        financial = Decimal(1)
    q = Decimal("0.0001")
    return (float(code_based.quantize(q, rounding=ROUND_HALF_UP)),
            float(financial.quantize(q, rounding=ROUND_HALF_UP)))


def timely_filing_deadline(paid_at):
    return paid_at + timedelta(days=TIMELY_FILING_DAYS)
