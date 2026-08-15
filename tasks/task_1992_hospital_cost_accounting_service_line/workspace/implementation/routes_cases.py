"""Case routes (PRD §3.3, §3.4): capture, ledger lines, post/void/lock."""

from decimal import Decimal

from flask import Blueprint, request

import errors
import serialize
from calc import (case_activity_lines, price_case, sync_ledgers_for_case)
from db import new_common_fields, new_id, store, touch
from helpers import (PERIOD_RE, auth, check_period_format, check_unknown_fields,
                     get_body, get_int, get_number, get_period, get_str,
                     get_bool, occ_matches, paginate)
from response import success

bp = Blueprint("cases", __name__)

READ_ROLES = ("FinanceController", "CostAnalyst", "ServiceLineManager")
FC = ("FinanceController",)
CA = ("CostAnalyst",)


def _sorted(table):
    return sorted(table.values(), key=lambda e: e["_seq"])


def _get_case_or_404(rid):
    case = store.cases.get(rid)
    if case is None:
        errors.not_found("Case")
    return case


# ===========================================================================
# Case CRUD
# ===========================================================================

@bp.route("/cost-accounting/cases", methods=["POST"])
def create_case():
    auth(*CA)
    body = get_body()
    # Family 3: body FK existence in declared input order.
    sl = None
    if body.get("service_line_id") is not None:
        sl = store.service_lines.get(body["service_line_id"])
        if sl is None:
            errors.not_found("ServiceLine")
    physician = None
    if body.get("physician_id") is not None:
        physician = store.physicians.get(body["physician_id"])
        if physician is None:
            errors.not_found("Physician")
    drg = None
    if body.get("drg_id") is not None:
        drg = store.drgs.get(body["drg_id"])
        if drg is None:
            errors.not_found("Drg")
    model = None
    if body.get("cost_model_id") is not None:
        model = store.cost_models.get(body["cost_model_id"])
        if model is None:
            errors.not_found("CostModel")
    # Family 5: parent aggregates active — the service line (§3.1) and the
    # pricing model (§3.3: "the cost model must be `ACTIVE`").
    if sl is not None and sl["status"] != "ACTIVE":
        errors.service_line_not_active()
    if model is not None and model["status"] != "ACTIVE":
        errors.model_not_active()
    # Family 6: cross-reference structural validity.
    if physician is not None and physician["status"] != "ACTIVE":
        errors.physician_not_active()
    if model is not None and sl is not None and model["service_line_id"] != sl["id"]:
        errors.invalid_request(
            "cost_model_id must belong to the case's service line")
    # Family 6/9: the case period must respect the model's effective window —
    # verified at creation and again at post (PRD §2.7). A malformed period is
    # left for the family-9 format check below.
    if (model is not None and isinstance(body.get("period"), str)
            and PERIOD_RE.match(body["period"])
            and body["period"] < model["effective_period"]):
        errors.case_period_before_model()
    # Family 9: temporal windowing (period format).
    check_period_format(body.get("period"), "period")
    # Family 10: request sanity.
    check_unknown_fields(body, ["service_line_id", "physician_id", "drg_id",
                                "cost_model_id", "period",
                                "expected_reimbursement"])
    get_str(body, "service_line_id")
    get_str(body, "physician_id")
    get_str(body, "drg_id")
    get_str(body, "cost_model_id")
    period = get_period(body, "period")
    expected_reimbursement = get_number(body, "expected_reimbursement", ge=0)
    c = {
        **new_common_fields(),
        "_seq": store.next_seq(),
        "service_line_id": sl["id"],
        "physician_id": physician["id"],
        "drg_id": drg["id"],
        "cost_model_id": model["id"],
        "period": period,
        "expected_reimbursement": expected_reimbursement,
        "status": "DRAFT",
        "total_direct_cost": Decimal("0"),
        "total_indirect_allocated": Decimal("0"),
        "total_cost": Decimal("0"),
        "margin": Decimal("0"),
        "version_at_post": None,
        "_activity_total": Decimal("0"),
        "_overhead_pool_amount": Decimal("0"),
    }
    store.cases[c["id"]] = c
    return success(serialize.case(c), code=201)


@bp.route("/cost-accounting/cases", methods=["GET"])
def list_cases():
    auth(*READ_ROLES)
    items = _sorted(store.cases)
    for param in ("status", "service_line_id", "physician_id", "drg_id",
                  "period", "cost_model_id"):
        value = request.args.get(param)
        if value:
            items = [c for c in items if c.get(param) == value]
    page, meta = paginate(items)
    return success([serialize.case(c) for c in page],
                   response_type="array", pagination=meta)


@bp.route("/cost-accounting/cases/<rid>", methods=["GET"])
def get_case(rid):
    auth(*READ_ROLES)
    c = _get_case_or_404(rid)
    return success(serialize.case(c))


# ===========================================================================
# Ledger lines: activity lines, implants, supply lines
# ===========================================================================

@bp.route("/cost-accounting/cases/<rid>/activity-lines", methods=["POST"])
def add_activity_line(rid):
    auth(*CA)
    case = _get_case_or_404(rid)
    body = get_body()
    # Family 3 (body FK) precedes family 4 (state).
    center = None
    if body.get("cost_center_id") is not None:
        center = store.cost_centers.get(body["cost_center_id"])
        if center is None:
            errors.not_found("CostCenter")
    # Family 4: case must be DRAFT.
    if case["status"] != "DRAFT":
        errors.invalid_state("Case is not DRAFT")
    # Family 6: the center must be eligible for the case's model.
    if center is not None:
        model = store.cost_models.get(case["cost_model_id"])
        if center["status"] != "ACTIVE" or center["cost_type"] == "DIRECT":
            errors.activity_center_invalid()
        elif center["cost_type"] not in ("INDIRECT", "OVERHEAD"):
            errors.activity_center_invalid()
        elif model is not None and center["id"] != model["overhead_cost_center_id"]:
            expected_measure = ("MINUTES" if model["allocation_basis"] == "TDABC"
                                else "RVU")
            if center["capacity_measure"] != expected_measure:
                errors.activity_center_invalid()
    # Family 10: request sanity.
    check_unknown_fields(body, ["cost_center_id", "quantity", "is_overhead_line"])
    get_str(body, "cost_center_id")
    quantity = get_number(body, "quantity", gt=0)
    flag_input = get_bool(body, "is_overhead_line")
    model = store.cost_models.get(case["cost_model_id"])
    is_overhead = bool(flag_input) or (
        model is not None and center["id"] == model["overhead_cost_center_id"])
    line = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "_seq": store.next_seq(),
        "case_id": case["id"],
        "cost_center_id": center["id"],
        "quantity": quantity,
        "is_overhead_line": is_overhead,
        "allocated_amount": Decimal("0"),
        "_overhead_amount": Decimal("0"),
    }
    store.activity_lines[line["id"]] = line
    return success(serialize.activity_line(line), code=201)


@bp.route("/cost-accounting/cases/<rid>/activity-lines", methods=["GET"])
def list_activity_lines(rid):
    auth(*READ_ROLES)
    case = _get_case_or_404(rid)
    page, meta = paginate(case_activity_lines(case["id"]))
    return success([serialize.activity_line(l) for l in page],
                   response_type="array", pagination=meta)


@bp.route("/cost-accounting/cases/<rid>/implants", methods=["POST"])
def add_implant(rid):
    auth(*CA)
    case = _get_case_or_404(rid)
    body = get_body()
    if case["status"] != "DRAFT":
        errors.invalid_state("Case is not DRAFT")
    check_unknown_fields(body, ["item_code", "vendor", "unit_cost", "quantity"])
    item_code = get_str(body, "item_code")
    vendor = get_str(body, "vendor")
    unit_cost = get_number(body, "unit_cost", gt=0)
    quantity = get_int(body, "quantity", gt=0)
    im = {
        **new_common_fields(),
        "_seq": store.next_seq(),
        "case_id": case["id"],
        "item_code": item_code,
        "vendor": vendor,
        "unit_cost": unit_cost,
        "quantity": quantity,
    }
    store.implants[im["id"]] = im
    return success(serialize.implant(im), code=201)


@bp.route("/cost-accounting/cases/<rid>/implants", methods=["GET"])
def list_implants(rid):
    auth(*READ_ROLES)
    case = _get_case_or_404(rid)
    items = [i for i in _sorted(store.implants) if i["case_id"] == case["id"]]
    page, meta = paginate(items)
    return success([serialize.implant(i) for i in page],
                   response_type="array", pagination=meta)


@bp.route("/cost-accounting/cases/<rid>/supply-lines", methods=["POST"])
def add_supply_line(rid):
    auth(*CA)
    case = _get_case_or_404(rid)
    body = get_body()
    if case["status"] != "DRAFT":
        errors.invalid_state("Case is not DRAFT")
    check_unknown_fields(body, ["supply_code", "unit_cost", "quantity"])
    supply_code = get_str(body, "supply_code")
    unit_cost = get_number(body, "unit_cost", gt=0)
    quantity = get_int(body, "quantity", gt=0)
    sl = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "_seq": store.next_seq(),
        "case_id": case["id"],
        "supply_code": supply_code,
        "unit_cost": unit_cost,
        "quantity": quantity,
    }
    store.supply_lines[sl["id"]] = sl
    return success(serialize.supply_line(sl), code=201)


@bp.route("/cost-accounting/cases/<rid>/supply-lines", methods=["GET"])
def list_supply_lines(rid):
    auth(*READ_ROLES)
    case = _get_case_or_404(rid)
    items = [s for s in _sorted(store.supply_lines) if s["case_id"] == case["id"]]
    page, meta = paginate(items)
    return success([serialize.supply_line(s) for s in page],
                   response_type="array", pagination=meta)


# ===========================================================================
# State transitions: post / void / lock
# ===========================================================================

@bp.route("/cost-accounting/cases/<rid>/post", methods=["POST"])
def post_case(rid):
    auth(*CA)
    case = _get_case_or_404(rid)
    body = get_body()
    # Family 4: posting requires DRAFT (state beats the OCC failure).
    if case["status"] != "DRAFT":
        errors.invalid_state("Case is not DRAFT")
    model = store.cost_models.get(case["cost_model_id"])
    if model is None:
        errors.not_found("CostModel")
    # OCC (PRD §2.9): carried stale version rejected before the further gates.
    if not occ_matches(body, model):
        errors.stale_model_version()
    # Family 5: the pricing model must be ACTIVE.
    if model["status"] != "ACTIVE":
        errors.model_not_active()
    # Family 6: the case period must respect the model's window.
    if case["period"] < model["effective_period"]:
        errors.case_period_before_model()
    # Family 8: completeness — at least one activity line.
    if not case_activity_lines(case["id"]):
        errors.case_no_activity()
    # Family 10: request sanity (expected_model_version is required).
    check_unknown_fields(body, ["expected_model_version"])
    if "expected_model_version" not in body or body.get("expected_model_version") is None:
        errors.invalid_request("Missing required field: expected_model_version")
    # Pinned costing pipeline + ledger cascades (hops 1-2), all in-request.
    price_case(case, model)
    case["status"] = "POSTED"
    case["version_at_post"] = model["version"]
    touch(case)
    sync_ledgers_for_case(case)
    return success(serialize.case(case))


@bp.route("/cost-accounting/cases/<rid>/void", methods=["POST"])
def void_case(rid):
    auth(*CA)
    case = _get_case_or_404(rid)
    body = get_body()
    check_unknown_fields(body, [])
    if case["status"] != "POSTED":
        errors.invalid_state("Case is not POSTED")
    case["status"] = "VOIDED"
    touch(case)
    # Compensation: service-line rollups and budget-period flex recompute with
    # the case removed from every aggregate.
    sync_ledgers_for_case(case)
    return success(serialize.case(case))


@bp.route("/cost-accounting/cases/<rid>/lock", methods=["POST"])
def lock_case(rid):
    auth(*FC)
    case = _get_case_or_404(rid)
    body = get_body()
    check_unknown_fields(body, [])
    if case["status"] != "POSTED":
        errors.invalid_state("Case is not POSTED")
    model = store.cost_models.get(case["cost_model_id"])
    if model is None:
        errors.not_found("CostModel")
    if case["version_at_post"] != model["version"]:
        errors.case_stale_model()
    case["status"] = "LOCKED"
    touch(case)
    return success(serialize.case(case))
