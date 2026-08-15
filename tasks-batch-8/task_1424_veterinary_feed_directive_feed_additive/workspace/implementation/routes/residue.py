"""Residue case routes."""

from flask import Blueprint, request

import errors
import util
from db import store
from middleware import require_roles
from response import success_object
from services import core
from routes.onboarding import _paginate

bp = Blueprint("residue", __name__)


@bp.post("/vfd/producers/<pid>/residue-cases")
def create_residue_case(pid):
    require_roles("Inspector")
    producer = core.get_producer(pid)
    body = util.get_json_body()
    feed_order_id = util.require_field(body, "feed_order_id")
    detected_at = util.require_field(body, "detected_at")
    util.parse_iso(detected_at, "detected_at")
    investigator_id = util.require_field(body, "investigator_id")
    residue_ppb = util.optional_int(body, "residue_ppb")
    tolerance_ppb = util.optional_int(body, "tolerance_ppb")
    core.get_feed_order(feed_order_id)
    case = util.new_entity({
        "producer_id": producer["id"],
        "feed_order_id": feed_order_id,
        "detected_at": detected_at,
        "residue_ppb": residue_ppb,
        "tolerance_ppb": tolerance_ppb,
        "investigator_id": investigator_id,
        "severity_tier": None,
        "penalty_score_deduction": 0,
        "status": "OPEN",
    })
    store.residue_cases[case["id"]] = case
    core.recompute_all_clinics_audit_ready()
    return success_object(case, 201)


@bp.get("/vfd/residue-cases/<rid>")
def get_residue_case(rid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    return success_object(core.get_residue_case(rid))


@bp.get("/vfd/producers/<pid>/residue-cases")
def list_residue_cases_for_producer(pid):
    require_roles("Inspector", "Veterinarian", "Producer")
    core.get_producer(pid)
    items = [c for c in store.residue_cases.values() if c.get("producer_id") == pid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    return _paginate(items)


@bp.get("/vfd/residue-cases")
def list_residue_cases():
    require_roles("Inspector", "Veterinarian", "Producer", "FeedMillOperator")
    items = list(store.residue_cases.values())
    for param in ("status", "producer_id", "feed_order_id"):
        val = request.args.get(param)
        if val is not None:
            items = [c for c in items if c.get(param) == val]
    return _paginate(items)


@bp.post("/vfd/residue-cases/<rid>/open-investigation")
def open_investigation(rid):
    require_roles("Inspector")
    case = core.get_residue_case(rid)
    if case["status"] != "OPEN":
        raise errors.invalid_state("ResidueCase must be OPEN to begin investigation")
    case["status"] = "UNDER_INVESTIGATION"
    util.touch(case)
    return success_object(case)


@bp.post("/vfd/residue-cases/<rid>/confirm")
def confirm_residue_case(rid):
    require_roles("Inspector")
    case = core.get_residue_case(rid)
    if case["status"] != "UNDER_INVESTIGATION":
        raise errors.invalid_state("ResidueCase must be UNDER_INVESTIGATION to confirm")
    body = util.get_json_body()
    residue_ppb = body.get("residue_ppb")
    tolerance_ppb = body.get("tolerance_ppb")
    if residue_ppb is None or tolerance_ppb is None:
        raise errors.invalid_request("residue_ppb and tolerance_ppb are required")
    if isinstance(residue_ppb, bool) or not isinstance(residue_ppb, int):
        raise errors.invalid_request("residue_ppb must be an integer")
    if isinstance(tolerance_ppb, bool) or not isinstance(tolerance_ppb, int):
        raise errors.invalid_request("tolerance_ppb must be an integer")
    case["residue_ppb"] = residue_ppb
    case["tolerance_ppb"] = tolerance_ppb
    case["severity_tier"] = core.compute_severity_tier(residue_ppb, tolerance_ppb)
    deduction = core.compute_penalty_deduction(residue_ppb, tolerance_ppb)
    case["penalty_score_deduction"] = deduction
    case["status"] = "CONFIRMED_VIOLATION"
    util.touch(case)

    # walk chronological path: order -> vfd -> vet -> clinic
    order = core.get_feed_order(case["feed_order_id"])
    vfd = core.get_vfd(order["vfd_authorization_id"])
    vet = core.get_vet(vfd["vet_id"])
    clinic = core.get_clinic(vet["clinic_id"])
    clinic["compliance_score"] = clinic.get("compliance_score", 1000) - deduction
    util.touch(clinic)
    core.recompute_audit_ready(clinic)

    return success_object(case)


@bp.post("/vfd/residue-cases/<rid>/dismiss")
def dismiss_residue_case(rid):
    require_roles("Inspector")
    case = core.get_residue_case(rid)
    if case["status"] not in ("OPEN", "UNDER_INVESTIGATION"):
        raise errors.invalid_state("ResidueCase must be OPEN or UNDER_INVESTIGATION to dismiss")
    case["status"] = "DISMISSED"
    util.touch(case)
    core.recompute_all_clinics_audit_ready()
    return success_object(case)
