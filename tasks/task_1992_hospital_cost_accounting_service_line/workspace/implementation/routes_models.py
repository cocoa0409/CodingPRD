"""Cost model + cost-model refresh routes (PRD §3.2, §3.6)."""

from flask import Blueprint, request

import errors
import serialize
from calc import (MIN_DATA_QUALITY, VARIANCE_THRESHOLD_PCT, apply_refresh,
                  build_variance_report)
from db import new_common_fields, store, touch
from helpers import (auth, check_period_format, check_unknown_fields,
                     get_body, get_enum, get_int, get_number, get_period,
                     get_str, occ_matches, paginate)
from response import success

bp = Blueprint("models", __name__)

READ_ROLES = ("FinanceController", "CostAnalyst", "ServiceLineManager")
FC = ("FinanceController",)
CA = ("CostAnalyst",)

ALLOCATION_BASES = ("TDABC", "RVU")


def _sorted(table):
    return sorted(table.values(), key=lambda e: e["_seq"])


def _get_or_404(table, rid, what):
    entity = table.get(rid)
    if entity is None:
        errors.not_found(what)
    return entity


def _check_overhead_center(center):
    """Family 6: the overhead pool must be ACTIVE and cost_type OVERHEAD."""
    if center["status"] != "ACTIVE" or center["cost_type"] != "OVERHEAD":
        errors.overhead_center_invalid()


def _check_supersede_target(target, service_line_id):
    """Family 6: supersession target must be ACTIVE and on the same line."""
    if target["status"] != "ACTIVE" or target["service_line_id"] != service_line_id:
        errors.supersede_target_invalid()


# ===========================================================================
# CostModel
# ===========================================================================

@bp.route("/cost-accounting/cost-models", methods=["POST"])
def create_cost_model():
    auth(*CA)
    body = get_body()
    # Family 3: body FK existence in declared input order.
    sl_id = body.get("service_line_id")
    sl = None
    if sl_id is not None:
        sl = store.service_lines.get(sl_id)
        if sl is None:
            errors.not_found("ServiceLine")
    oh_id = body.get("overhead_cost_center_id")
    oh = None
    if oh_id is not None:
        oh = store.cost_centers.get(oh_id)
        if oh is None:
            errors.not_found("CostCenter")
    sup_id = body.get("supersedes_model_id")
    sup = None
    if sup_id is not None:
        sup = store.cost_models.get(sup_id)
        if sup is None:
            errors.not_found("CostModel (supersedes_model_id)")
    # Family 6: cross-reference structural validity.
    if oh is not None:
        _check_overhead_center(oh)
    if sup is not None and sl is not None:
        _check_supersede_target(sup, sl["id"])
    # Family 9: temporal windowing.
    check_period_format(body.get("effective_period"), "effective_period")
    # Family 10: request sanity.
    check_unknown_fields(body, ["name", "service_line_id", "allocation_basis",
                                "rate_factor", "overhead_cost_center_id",
                                "effective_period", "supersedes_model_id"])
    name = get_str(body, "name")
    get_str(body, "service_line_id")
    allocation_basis = get_enum(body, "allocation_basis", ALLOCATION_BASES)
    rate_factor = get_number(body, "rate_factor", ge=0)
    get_str(body, "overhead_cost_center_id")
    effective_period = get_period(body, "effective_period")
    m = {
        **new_common_fields(),
        "_seq": store.next_seq(),
        "name": name,
        "service_line_id": sl["id"],
        "allocation_basis": allocation_basis,
        "rate_factor": rate_factor,
        "overhead_cost_center_id": oh["id"],
        "status": "DRAFT",
        "supersedes_model_id": sup["id"] if sup is not None else None,
        "effective_period": effective_period,
    }
    store.cost_models[m["id"]] = m
    return success(serialize.cost_model(m), code=201)


@bp.route("/cost-accounting/cost-models", methods=["GET"])
def list_cost_models():
    auth(*READ_ROLES)
    items = _sorted(store.cost_models)
    status = request.args.get("status")
    if status:
        items = [m for m in items if m["status"] == status]
    sl_id = request.args.get("service_line_id")
    if sl_id:
        items = [m for m in items if m["service_line_id"] == sl_id]
    oh_id = request.args.get("overhead_cost_center_id")
    if oh_id:
        items = [m for m in items if m["overhead_cost_center_id"] == oh_id]
    sup_id = request.args.get("supersedes_model_id")
    if sup_id:
        items = [m for m in items if m.get("supersedes_model_id") == sup_id]
    page, meta = paginate(items)
    return success([serialize.cost_model(m) for m in page],
                   response_type="array", pagination=meta)


@bp.route("/cost-accounting/cost-models/<rid>", methods=["GET"])
def get_cost_model(rid):
    auth(*READ_ROLES)
    m = _get_or_404(store.cost_models, rid, "CostModel")
    return success(serialize.cost_model(m))


@bp.route("/cost-accounting/cost-models/<rid>/approve", methods=["POST"])
def approve_cost_model(rid):
    auth(*FC)
    m = _get_or_404(store.cost_models, rid, "CostModel")
    body = get_body()
    check_unknown_fields(body, [])
    # Family 4: target state.
    if m["status"] != "DRAFT":
        errors.invalid_state("CostModel is not DRAFT")
    # Family 5: parent aggregate active.
    sl = store.service_lines.get(m["service_line_id"])
    if sl is None or sl["status"] != "ACTIVE":
        errors.service_line_not_active()
    # Family 6: cross-reference structural validity (re-verified at approval).
    oh = store.cost_centers.get(m["overhead_cost_center_id"])
    if oh is None:
        errors.overhead_center_invalid()
    _check_overhead_center(oh)
    sup = None
    if m.get("supersedes_model_id"):
        sup = store.cost_models.get(m["supersedes_model_id"])
        if sup is None:
            errors.supersede_target_invalid()
        _check_supersede_target(sup, m["service_line_id"])
    # Side effects: supersede target -> SUPERSEDED; this model -> ACTIVE.
    if sup is not None:
        sup["status"] = "SUPERSEDED"
        touch(sup)
    m["status"] = "ACTIVE"
    touch(m)
    return success(serialize.cost_model(m))


@bp.route("/cost-accounting/cost-models/<rid>/archive", methods=["POST"])
def archive_cost_model(rid):
    auth(*FC)
    m = _get_or_404(store.cost_models, rid, "CostModel")
    body = get_body()
    check_unknown_fields(body, [])
    if m["status"] not in ("DRAFT", "ACTIVE"):
        errors.invalid_state("CostModel is neither DRAFT nor ACTIVE")
    if m["status"] == "ACTIVE":
        for c in store.cases.values():
            if c["cost_model_id"] == m["id"] and c["status"] in ("DRAFT", "POSTED"):
                errors.model_has_open_cases()
        for r in store.refreshes.values():
            if r["model_id"] == m["id"] and r["status"] in ("PROPOSED", "APPROVED"):
                errors.model_has_open_refresh()
    m["status"] = "ARCHIVED"
    touch(m)
    return success(serialize.cost_model(m))


# ===========================================================================
# CostModelRefresh
# ===========================================================================

@bp.route("/cost-accounting/cost-model-refreshes", methods=["POST"])
def create_cost_model_refresh():
    auth(*CA)
    body = get_body()
    # Family 3: body FK existence in declared input order.
    model_id = body.get("model_id")
    model = None
    if model_id is not None:
        model = store.cost_models.get(model_id)
        if model is None:
            errors.not_found("CostModel")
    raw_rates = body.get("proposed_rates")
    if isinstance(raw_rates, list):
        for item in raw_rates:
            if not isinstance(item, dict):
                continue
            cc_id = item.get("cost_center_id")
            if cc_id is not None and cc_id not in store.cost_centers:
                errors.not_found("CostCenter (proposed_rates)")
    # Family 5: the model being refreshed must be ACTIVE.
    if model is not None and model["status"] != "ACTIVE":
        errors.model_not_active()
    # Family 9: temporal windowing.
    check_period_format(body.get("period"), "period")
    # Family 10: request sanity.
    check_unknown_fields(body, ["model_id", "period", "proposed_rates",
                                "data_quality_score"])
    get_str(body, "model_id")
    period = get_period(body, "period")
    if not isinstance(raw_rates, list):
        if raw_rates is None:
            errors.invalid_request("Missing required field: proposed_rates")
        errors.invalid_request("Field proposed_rates must be an array")
    data_quality_score = get_number(body, "data_quality_score", ge=0, le=100)

    internal_rates = []
    for item in raw_rates:
        if not isinstance(item, dict):
            errors.invalid_request("proposed_rates entries must be objects")
        check_unknown_fields(item, ["cost_center_id", "allocated_cost",
                                    "practical_capacity_minutes", "total_rvu"])
        cc_id = get_str(item, "cost_center_id")
        center = store.cost_centers.get(cc_id)
        if center is None:
            errors.not_found("CostCenter (proposed_rates)")
        allocated_cost = get_number(item, "allocated_cost", gt=0)
        entry = {"cost_center_id": cc_id, "allocated_cost": allocated_cost}
        measure = center["capacity_measure"]
        if measure == "MINUTES":
            if item.get("total_rvu") is not None:
                errors.invalid_request(
                    "total_rvu must be absent for a MINUTES-measured center")
            entry["practical_capacity_minutes"] = get_int(
                item, "practical_capacity_minutes", gt=0)
        elif measure == "RVU":
            if item.get("practical_capacity_minutes") is not None:
                errors.invalid_request(
                    "practical_capacity_minutes must be absent for an RVU-measured center")
            entry["total_rvu"] = get_number(item, "total_rvu", gt=0)
        else:  # NONE
            if item.get("practical_capacity_minutes") is not None:
                errors.invalid_request(
                    "practical_capacity_minutes must be absent for a NONE-measured center")
            if item.get("total_rvu") is not None:
                errors.invalid_request(
                    "total_rvu must be absent for a NONE-measured center")
        internal_rates.append(entry)

    variance_report = build_variance_report(internal_rates)
    # JSON-safe echo of the client-supplied proposed_rates.
    public_rates = []
    for entry in internal_rates:
        pub = {
            "cost_center_id": entry["cost_center_id"],
            "allocated_cost": float(entry["allocated_cost"]),
        }
        if "practical_capacity_minutes" in entry:
            pub["practical_capacity_minutes"] = entry["practical_capacity_minutes"]
        if "total_rvu" in entry:
            pub["total_rvu"] = float(entry["total_rvu"])
        public_rates.append(pub)

    r = {
        **new_common_fields(),
        "_seq": store.next_seq(),
        "model_id": model["id"],
        "period": period,
        "proposed_rates": public_rates,
        "_proposed_rates": internal_rates,
        "data_quality_score": data_quality_score,
        "status": "PROPOSED",
        "variance_report": variance_report,
    }
    store.refreshes[r["id"]] = r
    return success(serialize.refresh(r), code=201)


@bp.route("/cost-accounting/cost-model-refreshes", methods=["GET"])
def list_cost_model_refreshes():
    auth(*READ_ROLES)
    items = _sorted(store.refreshes)
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    model_id = request.args.get("model_id")
    if model_id:
        items = [r for r in items if r["model_id"] == model_id]
    page, meta = paginate(items)
    return success([serialize.refresh(r) for r in page],
                   response_type="array", pagination=meta)


@bp.route("/cost-accounting/cost-model-refreshes/<rid>", methods=["GET"])
def get_cost_model_refresh(rid):
    auth(*READ_ROLES)
    r = _get_or_404(store.refreshes, rid, "CostModelRefresh")
    return success(serialize.refresh(r))


@bp.route("/cost-accounting/cost-model-refreshes/<rid>/approve", methods=["POST"])
def approve_cost_model_refresh(rid):
    auth(*FC)
    r = _get_or_404(store.refreshes, rid, "CostModelRefresh")
    body = get_body()
    # Family 4: target state.
    if r["status"] != "PROPOSED":
        errors.invalid_state("CostModelRefresh is not PROPOSED")
    model = store.cost_models.get(r["model_id"])
    if model is None:
        errors.not_found("CostModel")
    # OCC (PRD §2.9): a carried stale version is rejected before the gates.
    if not occ_matches(body, model):
        errors.stale_model_version()
    # Family 5: target model must be ACTIVE.
    if model["status"] != "ACTIVE":
        errors.model_not_active()
    # Family 7: governance gates — variance threshold, then data quality.
    from decimal import Decimal
    for entry in r["variance_report"]:
        if abs(Decimal(str(entry["delta_pct"]))) > VARIANCE_THRESHOLD_PCT:
            errors.refresh_variance_exceeded()
    if r["data_quality_score"] < MIN_DATA_QUALITY:
        errors.data_quality_too_low()
    # Family 10: request sanity (expected_model_version is required).
    check_unknown_fields(body, ["expected_model_version"])
    if "expected_model_version" not in body or body.get("expected_model_version") is None:
        errors.invalid_request("Missing required field: expected_model_version")
    r["status"] = "APPROVED"
    touch(r)
    return success(serialize.refresh(r))


@bp.route("/cost-accounting/cost-model-refreshes/<rid>/reject", methods=["POST"])
def reject_cost_model_refresh(rid):
    auth(*FC)
    r = _get_or_404(store.refreshes, rid, "CostModelRefresh")
    body = get_body()
    check_unknown_fields(body, [])
    if r["status"] != "PROPOSED":
        errors.invalid_state("CostModelRefresh is not PROPOSED")
    r["status"] = "REJECTED"
    touch(r)
    return success(serialize.refresh(r))


@bp.route("/cost-accounting/cost-model-refreshes/<rid>/apply", methods=["POST"])
def apply_cost_model_refresh(rid):
    auth(*FC)
    r = _get_or_404(store.refreshes, rid, "CostModelRefresh")
    body = get_body()
    check_unknown_fields(body, [])
    # Family 4: target state.
    if r["status"] != "APPROVED":
        errors.invalid_state("CostModelRefresh is not APPROVED")
    # Family 5: target model still ACTIVE.
    model = store.cost_models.get(r["model_id"])
    if model is None or model["status"] != "ACTIVE":
        errors.model_not_active()
    apply_refresh(r)
    r["status"] = "APPLIED"
    touch(r)
    return success(serialize.refresh(r))
