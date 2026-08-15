"""Decision-support reports (PRD §3.7). All draw exclusively on POSTED and
LOCKED cases; DRAFT and VOIDED cases never appear."""

from decimal import Decimal

from flask import Blueprint, request

import errors
import serialize
from calc import r2
from db import store
from helpers import auth, check_period_format
from response import success

bp = Blueprint("reports", __name__)

READ_ROLES = ("FinanceController", "CostAnalyst", "ServiceLineManager")

PAYER_TYPE_ORDER = ("MEDICARE", "MEDICAID", "COMMERCIAL", "SELF_PAY")

ZERO = Decimal("0")


def _params():
    return request.args


def _require_param(name):
    value = request.args.get(name)
    if value is None or value == "":
        errors.invalid_request("Missing required query parameter: %s" % name)
    return value


def _qualifying_cases(**filters):
    out = []
    for c in sorted(store.cases.values(), key=lambda e: e["_seq"]):
        if c["status"] not in ("POSTED", "LOCKED"):
            continue
        if any(c.get(k) != v for k, v in filters.items()):
            continue
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# Physician margin report
# ---------------------------------------------------------------------------

@bp.route("/cost-accounting/reports/physician-margin", methods=["GET"])
def physician_margin_report():
    auth(*READ_ROLES)
    physician_id = request.args.get("physician_id")
    if physician_id is not None and physician_id not in store.physicians:
        errors.not_found("Physician")
    physician_id = _require_param("physician_id")
    period = _require_param("period")
    check_period_format(period, "period")
    cases = _qualifying_cases(physician_id=physician_id, period=period)
    total_revenue = sum((c["expected_reimbursement"] for c in cases), ZERO)
    total_cost = sum((c["total_cost"] for c in cases), ZERO)
    margin = r2(total_revenue - total_cost)
    if cases:
        margin_per_case = r2(margin / Decimal(len(cases)))
    else:
        margin_per_case = 0
    # Worst-first ordering: margin ASC, tie-break created_at ASC.
    ordered = sorted(cases, key=lambda c: (c["margin"], c["_seq"]))
    data = {
        "physician_id": physician_id,
        "period": period,
        "case_count": len(cases),
        "total_revenue": float(r2(total_revenue)),
        "total_cost": float(r2(total_cost)),
        "margin": float(margin),
        "margin_per_case": (float(margin_per_case) if cases else 0),
        "cases": [serialize.case(c) for c in ordered],
    }
    return success(data)


# ---------------------------------------------------------------------------
# DRG margin report
# ---------------------------------------------------------------------------

@bp.route("/cost-accounting/reports/drg-margin", methods=["GET"])
def drg_margin_report():
    auth(*READ_ROLES)
    drg_id = request.args.get("drg_id")
    if drg_id is not None and drg_id not in store.drgs:
        errors.not_found("Drg")
    drg_id = _require_param("drg_id")
    period = _require_param("period")
    check_period_format(period, "period")
    drg = store.drgs[drg_id]
    cases = _qualifying_cases(drg_id=drg_id, period=period)
    if cases:
        avg_indirect = r2(
            sum((c["total_indirect_allocated"] for c in cases), ZERO)
            / Decimal(len(cases)))
    else:
        avg_indirect = ZERO
    target_variance = r2(avg_indirect - drg["target_cost"])
    if target_variance > ZERO:
        compliance = "OVER"
    elif target_variance == ZERO:
        compliance = "ON_TARGET"
    else:
        compliance = "UNDER"
    data = {
        "drg_id": drg_id,
        "period": period,
        "case_count": len(cases),
        "avg_indirect": float(r2(avg_indirect)),
        "target_cost": float(drg["target_cost"]),
        "target_variance": float(target_variance),
        "compliance": compliance,
    }
    return success(data)


# ---------------------------------------------------------------------------
# Payer-mix contribution report
# ---------------------------------------------------------------------------

def _match_contract(case):
    """Active contracts of the case's line whose window covers the case period
    and whose contracted_rate equals the case's expected_reimbursement;
    latest effective_period wins, tie-break earliest created_at."""
    candidates = [
        pc for pc in store.payer_contracts.values()
        if pc["service_line_id"] == case["service_line_id"]
        and pc["status"] == "ACTIVE"
        and pc["effective_period"] <= case["period"]
        and pc["contracted_rate"] == case["expected_reimbursement"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda pc: pc["_seq"])
    return max(candidates, key=lambda pc: pc["effective_period"])


@bp.route("/cost-accounting/reports/payer-mix", methods=["GET"])
def payer_mix_report():
    auth(*READ_ROLES)
    service_line_id = request.args.get("service_line_id")
    if service_line_id is not None and service_line_id not in store.service_lines:
        errors.not_found("ServiceLine")
    service_line_id = _require_param("service_line_id")
    period = _require_param("period")
    check_period_format(period, "period")
    cases = _qualifying_cases(service_line_id=service_line_id, period=period)
    matched = []
    unmatched_count = 0
    for c in cases:
        contract = _match_contract(c)
        if contract is None:
            unmatched_count += 1
        else:
            matched.append((c, contract))
    total_cost_all = sum((c["total_cost"] for c, _ in matched), ZERO)
    total_revenue_all = sum(
        (pc["contracted_rate"] for _, pc in matched), ZERO)
    by_type = {}
    for c, pc in matched:
        bucket = by_type.setdefault(
            pc["payer_type"], {"payer_type": pc["payer_type"], "case_count": 0,
                               "revenue": ZERO})
        bucket["case_count"] += 1
        bucket["revenue"] += pc["contracted_rate"]
    if total_revenue_all > ZERO:
        for bucket in by_type.values():
            bucket["cost_share"] = r2(
                total_cost_all * bucket["revenue"] / total_revenue_all)
        # Residual rounding difference goes to the largest-revenue payer type
        # (tie-break: fixed payer-type order).
        residual = r2(total_cost_all) - sum(
            (b["cost_share"] for b in by_type.values()), ZERO)
        if residual != ZERO and by_type:
            chosen = max(
                by_type.values(),
                key=lambda b: (b["revenue"], -PAYER_TYPE_ORDER.index(b["payer_type"])),
            )
            chosen["cost_share"] += residual
    payers = []
    for ptype in PAYER_TYPE_ORDER:
        if ptype not in by_type:
            continue
        bucket = by_type[ptype]
        revenue = r2(bucket["revenue"])
        cost_share = r2(bucket.get("cost_share", ZERO))
        payers.append({
            "payer_type": ptype,
            "case_count": bucket["case_count"],
            "revenue_pt": float(revenue),
            "cost_share_pt": float(cost_share),
            "contribution_pt": float(r2(revenue - cost_share)),
        })
    data = {
        "service_line_id": service_line_id,
        "period": period,
        "matched_case_count": len(matched),
        "unmatched_count": unmatched_count,
        "payers": payers,
    }
    return success(data)


# ---------------------------------------------------------------------------
# Implant variation report
# ---------------------------------------------------------------------------

@bp.route("/cost-accounting/reports/implant-variation", methods=["GET"])
def implant_variation_report():
    auth(*READ_ROLES)
    service_line_id = request.args.get("service_line_id")
    if service_line_id is not None and service_line_id not in store.service_lines:
        errors.not_found("ServiceLine")
    service_line_id = _require_param("service_line_id")
    item_code = _require_param("item_code")
    period = _require_param("period")
    check_period_format(period, "period")
    cases = _qualifying_cases(service_line_id=service_line_id, period=period)
    # Keep only cases carrying at least one implant with the item code, and
    # aggregate matching implant cost per physician.
    per_physician = {}
    total_cost_all = ZERO
    total_cases = 0
    for c in cases:
        matching = [
            i for i in store.implants.values()
            if i["case_id"] == c["id"] and i["item_code"] == item_code
        ]
        if not matching:
            continue
        cost = sum((i["unit_cost"] * Decimal(i["quantity"]) for i in matching), ZERO)
        bucket = per_physician.setdefault(
            c["physician_id"], {"physician_id": c["physician_id"],
                                "case_count": 0, "implant_cost": ZERO})
        bucket["case_count"] += 1
        bucket["implant_cost"] += cost
        total_cost_all += cost
        total_cases += 1
    if total_cases:
        cohort_avg = r2(total_cost_all / Decimal(total_cases))
    else:
        cohort_avg = ZERO
    physicians = []
    for bucket in per_physician.values():
        icpc = r2(bucket["implant_cost"] / Decimal(bucket["case_count"]))
        if cohort_avg == ZERO:
            variation_pct = ZERO
        else:
            variation_pct = r2((icpc - cohort_avg) / cohort_avg * Decimal("100"))
        physicians.append({
            "physician_id": bucket["physician_id"],
            "case_count": bucket["case_count"],
            "implant_cost_per_case": float(icpc),
            "variation_pct": float(variation_pct),
        })
    physicians.sort(key=lambda p: p["physician_id"])
    data = {
        "service_line_id": service_line_id,
        "item_code": item_code,
        "period": period,
        "cohort_avg": float(cohort_avg),
        "physicians": physicians,
    }
    return success(data)


# ---------------------------------------------------------------------------
# Service-line profitability report
# ---------------------------------------------------------------------------

@bp.route("/cost-accounting/reports/service-line-profitability", methods=["GET"])
def service_line_profitability_report():
    auth(*READ_ROLES)
    service_line_id = request.args.get("service_line_id")
    if service_line_id is not None and service_line_id not in store.service_lines:
        errors.not_found("ServiceLine")
    service_line_id = _require_param("service_line_id")
    period = _require_param("period")
    check_period_format(period, "period")
    sl = store.service_lines[service_line_id]
    cases = _qualifying_cases(service_line_id=service_line_id, period=period)
    total_revenue = sum((c["expected_reimbursement"] for c in cases), ZERO)
    # PRD §3.7: total_direct_cost is the sum of the cases' total_direct_cost.
    total_direct = sum((c["total_direct_cost"] for c in cases), ZERO)
    contribution = r2(total_revenue - total_direct)
    data = {
        "service_line_id": service_line_id,
        "period": period,
        "case_count": len(cases),
        "total_revenue": float(r2(total_revenue)),
        "total_direct_cost": float(r2(total_direct)),
        "contribution_margin": float(contribution),
    }
    return success(data)
