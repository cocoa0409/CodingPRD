"""QualityAudit endpoints (PRD §3.8) — AQL plan derivation, verdict recording
with the QC_FAILED cascade, and the rework loop."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_QUALITY_INSPECTOR
from response import success_object
from util import get_body, req_str, req_int, req_enum, opt_str, fk_exists
from errors import (
    invalid_state, reaudit_order_mismatch, reaudit_parent_not_reworked,
    no_completed_bundles, sod_reaudit_self_recheck, audit_not_failed,
)
from services.calc import aql_sample_plan
from services.core import (
    base_record, touch, public, get_quality_audit, get_production_order,
    order_bundles,
)
from routes.common import list_response, active_filters

bp = Blueprint("quality_audits", __name__)

INSPECTION_LEVELS = {"NORMAL", "TIGHTENED"}
AQL_LEVELS = {"AQL_2_5", "AQL_4_0"}


@bp.route("/quality-audits", methods=["POST"])
def create_quality_audit():
    require_roles([ROLE_QUALITY_INSPECTOR])
    body = get_body()
    fk_exists(body, "production_order_id", store.production_orders,
              "ProductionOrder")
    fk_exists(body, "re_audit_of_audit_id", store.quality_audits,
              "QualityAudit")
    production_order_id = req_str(body, "production_order_id")
    inspection_level = req_enum(body, "inspection_level", INSPECTION_LEVELS)
    aql_level = req_enum(body, "aql_level", AQL_LEVELS)
    re_audit_of = opt_str(body, "re_audit_of_audit_id")
    order = get_production_order(production_order_id)
    # Creation rules in fixed order (PRD §3.8).
    parent = None
    if re_audit_of is not None:
        parent = store.quality_audits[re_audit_of]
        if parent["production_order_id"] != order["id"]:
            raise reaudit_order_mismatch(
                "re-audit must reference an audit of the same production order")
        if parent["status"] != "REWORK_RECORDED":
            raise reaudit_parent_not_reworked(
                "re-audit parent must be REWORK_RECORDED")
    if not any(b["status"] == "COMPLETED" for b in order_bundles(order["id"])):
        raise no_completed_bundles(
            "quality audit requires at least one COMPLETED bundle on the order")

    lot_size = order["total_order_qty"]
    letter, sample_size, accept_max, reject_min = aql_sample_plan(
        lot_size, inspection_level, aql_level)
    rec = base_record()
    rec.update({
        "production_order_id": production_order_id,
        "re_audit_of_audit_id": re_audit_of,
        "inspection_level": inspection_level,
        "aql_level": aql_level,
        "lot_size": lot_size,
        "code_letter": letter,
        "sample_size": sample_size,
        "accept_max": accept_max,
        "reject_min": reject_min,
        "defects_found": None,
        "result": "NONE",
        "recorded_by_user_id": None,
        "status": "OPEN",
    })
    store.quality_audits[rec["id"]] = rec
    if parent is not None:
        # Chained re-audit: supersede the parent and return the order to
        # QC_PENDING (PRD §3.8).
        parent["status"] = "SUPERSEDED"
        touch(parent)
        if order["quality_status"] == "REWORK_IN_PROGRESS":
            order["quality_status"] = "QC_PENDING"
            touch(order)
    return success_object(public(rec), status=201)


@bp.route("/quality-audits", methods=["GET"])
def list_quality_audits():
    require_roles(ALL_ROLES)
    filters = active_filters([
        ("production_order_id", request.args.get("production_order_id")),
        ("re_audit_of_audit_id", request.args.get("re_audit_of_audit_id")),
    ])
    return list_response(store.quality_audits.values(), filters)


@bp.route("/quality-audits/<audit_id>", methods=["GET"])
def get_quality_audit_endpoint(audit_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_quality_audit(audit_id)))


@bp.route("/quality-audits/<audit_id>/record", methods=["POST"])
def record_quality_audit(audit_id):
    _, user_id = require_roles([ROLE_QUALITY_INSPECTOR])
    audit = get_quality_audit(audit_id)
    body = get_body()
    defects_found = req_int(body, "defects_found", min_v=0)
    if audit["status"] != "OPEN":
        raise invalid_state("quality audit must be OPEN to record")
    if audit["re_audit_of_audit_id"] is not None:
        parent = store.quality_audits[audit["re_audit_of_audit_id"]]
        if user_id == parent["recorded_by_user_id"]:
            raise sod_reaudit_self_recheck(
                "a re-audit may not be recorded by the inspector who recorded "
                "the audit it follows")
    audit["defects_found"] = defects_found
    audit["recorded_by_user_id"] = user_id
    order = get_production_order(audit["production_order_id"])
    # reject_min == accept_max + 1, so the verdict boundary is exact.
    if defects_found <= audit["accept_max"]:
        audit["result"] = "PASS"
        audit["status"] = "CLOSED_PASS"
        touch(audit)
        if order["quality_status"] == "QC_PENDING":
            order["quality_status"] = "QC_PASSED"
            touch(order)
        return success_object(public(audit))

    # FAIL: close the audit and cascade QC_PENDING -> QC_FAILED, bundles into
    # REWORK_HOLD, their LOGGED entries auto-REJECTED (PRD §3.8).
    audit["result"] = "FAIL"
    audit["status"] = "CLOSED_FAIL"
    touch(audit)
    if order["quality_status"] == "QC_PENDING":
        order["quality_status"] = "QC_FAILED"
        touch(order)
        for b in order_bundles(order["id"]):
            if b["status"] in ("RELEASED", "IN_PROGRESS", "COMPLETED"):
                b["pre_rework_status"] = b["status"]
                b["status"] = "REWORK_HOLD"
                touch(b)
                for e in store.piece_work_entries.values():
                    if e["bundle_id"] == b["id"] and e["status"] == "LOGGED":
                        e["status"] = "REJECTED"
                        e["reviewed_by_user_id"] = "system"
                        touch(e)
    return success_object(public(audit))


@bp.route("/quality-audits/<audit_id>/rework-complete", methods=["POST"])
def rework_complete(audit_id):
    require_roles([ROLE_QUALITY_INSPECTOR])
    get_body()
    audit = get_quality_audit(audit_id)
    if audit["status"] != "CLOSED_FAIL":
        raise audit_not_failed(
            "rework-complete requires the audit to be CLOSED_FAIL")
    audit["status"] = "REWORK_RECORDED"
    touch(audit)
    order = get_production_order(audit["production_order_id"])
    if order["quality_status"] == "QC_FAILED":
        order["quality_status"] = "REWORK_IN_PROGRESS"
        touch(order)
    # Bundles return to their pre-rework snapshot; verified work survives
    # (completed_through_seq untouched) (PRD §3.8).
    for b in order_bundles(order["id"]):
        if b["status"] == "REWORK_HOLD":
            b["status"] = b["pre_rework_status"]
            b["pre_rework_status"] = None
            touch(b)
    return success_object(public(audit))
