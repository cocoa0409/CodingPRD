"""Reference estate routes (PRD §3.1): service lines, cost centers,
physicians, DRGs, payer contracts."""

from decimal import Decimal

from flask import Blueprint, request

import errors
import serialize
from db import new_common_fields, store, touch
from helpers import (auth, check_period_format, check_unknown_fields, get_body,
                     get_enum, get_int, get_number, get_period, get_str,
                     paginate)
from response import success

bp = Blueprint("reference", __name__)

READ_ROLES = ("FinanceController", "CostAnalyst", "ServiceLineManager")
FC = ("FinanceController",)

COST_TYPES = ("DIRECT", "INDIRECT", "OVERHEAD")
COST_BEHAVIORS = ("FIXED", "VARIABLE")
CAPACITY_MEASURES = ("MINUTES", "RVU", "NONE")
PAYER_TYPES = ("MEDICARE", "MEDICAID", "COMMERCIAL", "SELF_PAY")


def _sorted(table):
    return sorted(table.values(), key=lambda e: e["_seq"])


def _get_or_404(table, rid, what):
    entity = table.get(rid)
    if entity is None:
        errors.not_found(what)
    return entity


# ===========================================================================
# ServiceLine
# ===========================================================================

@bp.route("/cost-accounting/service-lines", methods=["POST"])
def create_service_line():
    auth(*FC)
    body = get_body()
    check_unknown_fields(body, ["name", "code", "base_direct_cost", "budgeted_volume"])
    name = get_str(body, "name")
    code = get_str(body, "code")
    base_direct_cost = get_number(body, "base_direct_cost", ge=0)
    budgeted_volume = get_int(body, "budgeted_volume", gt=0)
    for sl in store.service_lines.values():
        if sl["code"] == code:
            errors.invalid_request("code '%s' is already in use" % code)
    sl = {
        **new_common_fields(),
        "_seq": store.next_seq(),
        "name": name,
        "code": code,
        "base_direct_cost": base_direct_cost,
        "budgeted_volume": budgeted_volume,
        "total_direct_cost": Decimal("0"),
        "total_revenue": Decimal("0"),
        "contribution_margin": Decimal("0"),
        "status": "ACTIVE",
    }
    store.service_lines[sl["id"]] = sl
    return success(serialize.service_line(sl), code=201)


@bp.route("/cost-accounting/service-lines", methods=["GET"])
def list_service_lines():
    auth(*READ_ROLES)
    items = _sorted(store.service_lines)
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items)
    return success([serialize.service_line(s) for s in page],
                   response_type="array", pagination=meta)


@bp.route("/cost-accounting/service-lines/<rid>", methods=["GET"])
def get_service_line(rid):
    auth(*READ_ROLES)
    sl = _get_or_404(store.service_lines, rid, "ServiceLine")
    return success(serialize.service_line(sl))


@bp.route("/cost-accounting/service-lines/<rid>/archive", methods=["POST"])
def archive_service_line(rid):
    auth(*FC)
    sl = _get_or_404(store.service_lines, rid, "ServiceLine")
    body = get_body()
    check_unknown_fields(body, [])
    if sl["status"] != "ACTIVE":
        errors.invalid_state("ServiceLine is not ACTIVE")
    for c in store.cases.values():
        if c["service_line_id"] == sl["id"] and c["status"] in ("DRAFT", "POSTED"):
            errors.service_line_has_open_cases()
    for m in store.cost_models.values():
        if m["service_line_id"] == sl["id"] and m["status"] == "ACTIVE":
            errors.service_line_has_active_model()
    # Cascade: every non-terminal cost model of the line -> ARCHIVED, every
    # ACTIVE payer contract -> TERMINATED.
    for m in store.cost_models.values():
        if m["service_line_id"] == sl["id"] and m["status"] in ("DRAFT", "ACTIVE"):
            m["status"] = "ARCHIVED"
            touch(m)
    for pc in store.payer_contracts.values():
        if pc["service_line_id"] == sl["id"] and pc["status"] == "ACTIVE":
            pc["status"] = "TERMINATED"
            touch(pc)
    sl["status"] = "ARCHIVED"
    touch(sl)
    return success(serialize.service_line(sl))


# ===========================================================================
# CostCenter
# ===========================================================================

@bp.route("/cost-accounting/cost-centers", methods=["POST"])
def create_cost_center():
    auth(*FC)
    body = get_body()
    check_unknown_fields(body, ["name", "code", "cost_type", "cost_behavior",
                                "allocated_cost", "capacity_measure",
                                "practical_capacity_minutes", "total_rvu"])
    name = get_str(body, "name")
    code = get_str(body, "code")
    cost_type = get_enum(body, "cost_type", COST_TYPES)
    cost_behavior = get_enum(body, "cost_behavior", COST_BEHAVIORS)
    allocated_cost = get_number(body, "allocated_cost", gt=0)
    capacity_measure = get_enum(body, "capacity_measure", CAPACITY_MEASURES)
    if capacity_measure == "NONE" and cost_type != "OVERHEAD":
        errors.invalid_request("capacity_measure NONE is valid only for OVERHEAD centers")
    pcm = None
    total_rvu = None
    if capacity_measure == "MINUTES":
        if "total_rvu" in body and body["total_rvu"] is not None:
            errors.invalid_request(
                "total_rvu must be absent when capacity_measure is MINUTES")
        pcm = get_int(body, "practical_capacity_minutes", gt=0)
    elif capacity_measure == "RVU":
        if "practical_capacity_minutes" in body and body["practical_capacity_minutes"] is not None:
            errors.invalid_request(
                "practical_capacity_minutes must be absent when capacity_measure is RVU")
        total_rvu = get_number(body, "total_rvu", gt=0)
    else:  # NONE
        if "practical_capacity_minutes" in body and body["practical_capacity_minutes"] is not None:
            errors.invalid_request(
                "practical_capacity_minutes must be absent when capacity_measure is NONE")
        if "total_rvu" in body and body["total_rvu"] is not None:
            errors.invalid_request(
                "total_rvu must be absent when capacity_measure is NONE")
    for cc in store.cost_centers.values():
        if cc["code"] == code:
            errors.invalid_request("code '%s' is already in use" % code)
    cc = {
        **new_common_fields(),
        "_seq": store.next_seq(),
        "name": name,
        "code": code,
        "cost_type": cost_type,
        "cost_behavior": cost_behavior,
        "allocated_cost": allocated_cost,
        "capacity_measure": capacity_measure,
        "practical_capacity_minutes": pcm,
        "total_rvu": total_rvu,
        "status": "ACTIVE",
    }
    store.cost_centers[cc["id"]] = cc
    return success(serialize.cost_center(cc), code=201)


@bp.route("/cost-accounting/cost-centers", methods=["GET"])
def list_cost_centers():
    auth(*READ_ROLES)
    items = _sorted(store.cost_centers)
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    cost_type = request.args.get("cost_type")
    if cost_type:
        items = [c for c in items if c["cost_type"] == cost_type]
    page, meta = paginate(items)
    return success([serialize.cost_center(c) for c in page],
                   response_type="array", pagination=meta)


@bp.route("/cost-accounting/cost-centers/<rid>", methods=["GET"])
def get_cost_center(rid):
    auth(*READ_ROLES)
    cc = _get_or_404(store.cost_centers, rid, "CostCenter")
    return success(serialize.cost_center(cc))


@bp.route("/cost-accounting/cost-centers/<rid>/archive", methods=["POST"])
def archive_cost_center(rid):
    auth(*FC)
    cc = _get_or_404(store.cost_centers, rid, "CostCenter")
    body = get_body()
    check_unknown_fields(body, [])
    if cc["status"] != "ACTIVE":
        errors.invalid_state("CostCenter is not ACTIVE")
    for m in store.cost_models.values():
        if (m["overhead_cost_center_id"] == cc["id"]
                and m["status"] not in ("SUPERSEDED", "ARCHIVED")):
            errors.cost_center_in_use()
    for line in store.activity_lines.values():
        if line["cost_center_id"] != cc["id"]:
            continue
        case = store.cases.get(line["case_id"])
        if case is not None and case["status"] in ("DRAFT", "POSTED"):
            errors.cost_center_in_use()
    cc["status"] = "ARCHIVED"
    touch(cc)
    return success(serialize.cost_center(cc))


@bp.route("/cost-accounting/cost-centers/<rid>/activity-lines", methods=["GET"])
def list_cost_center_activity_lines(rid):
    auth(*READ_ROLES)
    cc = _get_or_404(store.cost_centers, rid, "CostCenter")
    items = [l for l in _sorted(store.activity_lines)
             if l["cost_center_id"] == cc["id"]]
    page, meta = paginate(items)
    return success([serialize.activity_line(l) for l in page],
                   response_type="array", pagination=meta)


# ===========================================================================
# Physician
# ===========================================================================

@bp.route("/cost-accounting/physicians", methods=["POST"])
def create_physician():
    auth(*FC)
    body = get_body()
    check_unknown_fields(body, ["npi", "full_name", "specialty"])
    npi = get_str(body, "npi")
    full_name = get_str(body, "full_name")
    specialty = get_str(body, "specialty")
    for p in store.physicians.values():
        if p["npi"] == npi:
            errors.invalid_request("npi '%s' is already in use" % npi)
    p = {
        **new_common_fields(),
        "_seq": store.next_seq(),
        "npi": npi,
        "full_name": full_name,
        "specialty": specialty,
        "status": "ACTIVE",
    }
    store.physicians[p["id"]] = p
    return success(serialize.physician(p), code=201)


@bp.route("/cost-accounting/physicians", methods=["GET"])
def list_physicians():
    auth(*READ_ROLES)
    items = _sorted(store.physicians)
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items)
    return success([serialize.physician(p) for p in page],
                   response_type="array", pagination=meta)


@bp.route("/cost-accounting/physicians/<rid>", methods=["GET"])
def get_physician(rid):
    auth(*READ_ROLES)
    p = _get_or_404(store.physicians, rid, "Physician")
    return success(serialize.physician(p))


@bp.route("/cost-accounting/physicians/<rid>/deactivate", methods=["POST"])
def deactivate_physician(rid):
    auth(*FC)
    p = _get_or_404(store.physicians, rid, "Physician")
    body = get_body()
    check_unknown_fields(body, [])
    if p["status"] != "ACTIVE":
        errors.invalid_state("Physician is not ACTIVE")
    for c in store.cases.values():
        if c["physician_id"] == p["id"] and c["status"] in ("DRAFT", "POSTED"):
            errors.physician_has_open_cases()
    p["status"] = "INACTIVE"
    touch(p)
    return success(serialize.physician(p))


@bp.route("/cost-accounting/physicians/<rid>/reactivate", methods=["POST"])
def reactivate_physician(rid):
    auth(*FC)
    p = _get_or_404(store.physicians, rid, "Physician")
    body = get_body()
    check_unknown_fields(body, [])
    if p["status"] != "INACTIVE":
        errors.invalid_state("Physician is not INACTIVE")
    p["status"] = "ACTIVE"
    touch(p)
    return success(serialize.physician(p))


# ===========================================================================
# Drg
# ===========================================================================

@bp.route("/cost-accounting/drgs", methods=["POST"])
def create_drg():
    auth(*FC)
    body = get_body()
    check_unknown_fields(body, ["drg_code", "description", "target_cost", "base_rate"])
    drg_code = get_str(body, "drg_code")
    description = get_str(body, "description")
    target_cost = get_number(body, "target_cost", ge=0)
    base_rate = get_number(body, "base_rate", ge=0)
    for d in store.drgs.values():
        if d["drg_code"] == drg_code:
            errors.invalid_request("drg_code '%s' is already in use" % drg_code)
    d = {
        **new_common_fields(),
        "_seq": store.next_seq(),
        "drg_code": drg_code,
        "description": description,
        "target_cost": target_cost,
        "base_rate": base_rate,
    }
    store.drgs[d["id"]] = d
    return success(serialize.drg(d), code=201)


@bp.route("/cost-accounting/drgs", methods=["GET"])
def list_drgs():
    auth(*READ_ROLES)
    items = _sorted(store.drgs)
    page, meta = paginate(items)
    return success([serialize.drg(d) for d in page],
                   response_type="array", pagination=meta)


@bp.route("/cost-accounting/drgs/<rid>", methods=["GET"])
def get_drg(rid):
    auth(*READ_ROLES)
    d = _get_or_404(store.drgs, rid, "Drg")
    return success(serialize.drg(d))


# ===========================================================================
# PayerContract
# ===========================================================================

@bp.route("/cost-accounting/payer-contracts", methods=["POST"])
def create_payer_contract():
    auth(*FC)
    body = get_body()
    # Family 3: body FK existence in declared input order.
    sl_id = body.get("service_line_id")
    sl = None
    if sl_id is not None:
        sl = store.service_lines.get(sl_id)
        if sl is None:
            errors.not_found("ServiceLine")
    # Family 9: temporal windowing.
    check_period_format(body.get("effective_period"), "effective_period")
    # Family 10: request sanity.
    check_unknown_fields(body, ["service_line_id", "payer_name", "payer_type",
                                "contracted_rate", "effective_period"])
    get_str(body, "service_line_id")
    payer_name = get_str(body, "payer_name")
    payer_type = get_enum(body, "payer_type", PAYER_TYPES)
    contracted_rate = get_number(body, "contracted_rate", gt=0)
    effective_period = get_period(body, "effective_period")
    pc = {
        **new_common_fields(),
        "_seq": store.next_seq(),
        "service_line_id": sl["id"],
        "payer_name": payer_name,
        "payer_type": payer_type,
        "contracted_rate": contracted_rate,
        "effective_period": effective_period,
        "status": "ACTIVE",
    }
    store.payer_contracts[pc["id"]] = pc
    return success(serialize.payer_contract(pc), code=201)


@bp.route("/cost-accounting/payer-contracts", methods=["GET"])
def list_payer_contracts():
    auth(*READ_ROLES)
    items = _sorted(store.payer_contracts)
    sl_id = request.args.get("service_line_id")
    if sl_id:
        items = [p for p in items if p["service_line_id"] == sl_id]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items)
    return success([serialize.payer_contract(p) for p in page],
                   response_type="array", pagination=meta)


@bp.route("/cost-accounting/payer-contracts/<rid>", methods=["GET"])
def get_payer_contract(rid):
    auth(*READ_ROLES)
    pc = _get_or_404(store.payer_contracts, rid, "PayerContract")
    return success(serialize.payer_contract(pc))
