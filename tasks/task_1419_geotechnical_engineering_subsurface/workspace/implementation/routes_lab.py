"""Routes: lab test orders, lab test results, foundation analyses."""

from flask import Blueprint, g, request

import calc
import serialize
from db import store
from errors import err
from helpers import (
    forbid_role,
    get_body,
    opt_enum,
    opt_num,
    paginate,
    req_enum,
    req_num,
    req_str,
    require_roles,
    sorted_items,
)
from response import success

bp = Blueprint("lab", __name__)

PRIORITIES = {"STANDARD", "RUSH"}
ORDER_STATES = {
    "REQUESTED",
    "AUTHORIZED",
    "IN_TEST",
    "RESULT_SUBMITTED",
    "ACCEPTED",
    "REJECTED",
}
ORDER_TRANSITIONS = {
    ("REQUESTED", "AUTHORIZED"): "LabManager",
    ("AUTHORIZED", "IN_TEST"): "LabTechnician",
    ("RESULT_SUBMITTED", "ACCEPTED"): "LabManager",
    ("RESULT_SUBMITTED", "REJECTED"): "LabManager",
    ("REJECTED", "IN_TEST"): "LabTechnician",
}

ANALYSIS_METHODS = {"ALLOWABLE_STRESS", "LRFD"}
ANALYSIS_STATES = {"PRELIMINARY", "VERIFIED", "SUPERSEDED"}
ANALYSIS_TRANSITIONS = {
    ("PRELIMINARY", "VERIFIED"): "SeniorEngineer",
    ("VERIFIED", "VERIFIED"): "SeniorEngineer",  # self-loop refresh after staleness
}

RESULT_FIELDS = (
    "percent_passing_200",
    "liquid_limit",
    "plasticity_index",
    "qu_psf",
    "moisture_content_pct",
)


def get_order_or_404(oid):
    rec = store.orders.get(oid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "LabTestOrder %s not found" % oid)
    return rec


def get_analysis_or_404(aid):
    rec = store.analyses.get(aid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "FoundationAnalysis %s not found" % aid)
    return rec


def _stale_verified_analyses(project_id):
    """Link 2 of the rejection cascade: VERIFIED analyses of the project go STALE."""
    for a in store.analyses.values():
        if a["project_id"] == project_id and a["status"] == "VERIFIED":
            a["data_status"] = "STALE"
            store.bump(a)


def _recompute_uscs(sample):
    """Recompute uscs_class when both SIEVE_ANALYSIS and ATTERBERG are ACCEPTED."""
    sieve = calc.latest_accepted_result(sample["id"], "SIEVE_ANALYSIS")
    atterberg = calc.latest_accepted_result(sample["id"], "ATTERBERG")
    if sieve is None or atterberg is None:
        return
    if sieve.get("percent_passing_200") is None:
        return
    if atterberg.get("liquid_limit") is None or atterberg.get("plasticity_index") is None:
        return
    new_class = calc.uscs_classify(
        sieve["percent_passing_200"],
        atterberg["liquid_limit"],
        atterberg["plasticity_index"],
    )
    if sample["uscs_class"] != new_class:
        sample["uscs_class"] = new_class
        store.bump(sample)


# --------------------------------------------------------------------------
# Lab test orders
# --------------------------------------------------------------------------
@bp.route("/geo/projects/<pid>/lab-test-orders", methods=["POST"])
@require_roles("LabManager")
def create_lab_test_order(pid):
    project = store.projects.get(pid)
    if project is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Project %s not found" % pid)
    body = get_body()
    sample_id = req_str(body, "sample_id")
    test_type = req_enum(body, "test_type", calc.TEST_TYPES)
    priority = opt_enum(body, "priority", PRIORITIES, "STANDARD")
    # Category 5: parent-state gate (errata orders during review are permitted).
    if project["status"] not in ("FIELDWORK", "LAB_ANALYSIS", "REPORT_REVIEW"):
        raise err(
            "ERR_PROJECT_STATE_FORBIDS",
            "Lab orders require the project in FIELDWORK, LAB_ANALYSIS, or REPORT_REVIEW",
        )
    # Category 9: the sample must trace back to this project.
    sample = store.samples.get(sample_id)
    owner = calc.project_of_sample(sample) if sample else None
    if owner is None or owner["id"] != pid:
        raise err(
            "ERR_SAMPLE_PROJECT_MISMATCH",
            "Sample does not belong to this project",
        )
    rec = {
        "id": store.new_id(),
        "project_id": pid,
        "sample_id": sample_id,
        "test_type": test_type,
        "priority": priority,
        "fee_cents": calc.order_fee_cents(test_type, priority),
        "status": "REQUESTED",
        "rerun_count": 0,
    }
    store.stamp(rec)
    store.orders[rec["id"]] = rec
    # testing_invoice_cents / total_fee_cents recompute; refresh the parent.
    store.touch(project)
    return success(serialize.lab_test_order(rec), code=201)


@bp.route("/geo/lab-test-orders/<oid>", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "LabManager", "LabTechnician", "SeniorEngineer")
def get_lab_test_order(oid):
    return success(serialize.lab_test_order(get_order_or_404(oid)))


@bp.route("/geo/lab-test-orders", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "LabManager", "LabTechnician", "SeniorEngineer")
def list_lab_test_orders():
    items = list(store.orders.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [o for o in items if o["project_id"] == project_id]
    sample_id = request.args.get("sample_id")
    if sample_id is not None:
        items = [o for o in items if o["sample_id"] == sample_id]
    page, meta = paginate(sorted_items(items))
    return success([serialize.lab_test_order(o) for o in page], "array", 200, meta)


@bp.route("/geo/lab-test-orders/<oid>/transition", methods=["POST"])
@require_roles("LabManager", "LabTechnician")
def lab_test_order_transition(oid):
    order = get_order_or_404(oid)
    body = get_body()
    to = req_enum(body, "to", ORDER_STATES)
    transition = (order["status"], to)
    actor = ORDER_TRANSITIONS.get(transition)
    if actor is None:
        raise err(
            "ERR_INVALID_STATE",
            "LabTestOrder in %s cannot transition to %s" % (order["status"], to),
        )
    if g.role != actor:
        raise forbid_role("Transition to %s requires role %s" % (to, actor))

    if to == "AUTHORIZED":
        sample = store.samples.get(order["sample_id"])
        if sample is None or sample["custody_status"] != "LAB_RECEIVED":
            raise err(
                "ERR_SAMPLE_NOT_IN_LAB",
                "Test authorization requires sample custody LAB_RECEIVED",
            )
    elif to == "IN_TEST":
        if order["status"] == "REJECTED":
            if order["rerun_count"] >= calc.RERUN_MAX:
                raise err("ERR_RERUN_LIMIT", "rerun_count is at the cap of 2")
            in_test = sum(1 for o in store.orders.values() if o["status"] == "IN_TEST")
            if in_test >= calc.LAB_MAX_IN_TEST:
                raise err("ERR_LAB_CAPACITY_EXCEEDED", "Six orders are already IN_TEST")
        else:
            in_test = sum(1 for o in store.orders.values() if o["status"] == "IN_TEST")
            if in_test >= calc.LAB_MAX_IN_TEST:
                raise err("ERR_LAB_CAPACITY_EXCEEDED", "Six orders are already IN_TEST")

    project = store.projects.get(order["project_id"])
    sample = store.samples.get(order["sample_id"])
    was_rejected = order["status"] == "REJECTED"

    # Apply the state change first so side effects (e.g. uscs recomputation,
    # which scans for ACCEPTED orders) observe the new status.
    order["status"] = to

    if to == "ACCEPTED":
        # Destructive tests consume the sample's material.
        if order["test_type"] in calc.DESTRUCTIVE_TYPES and sample is not None:
            if sample["custody_status"] == "LAB_RECEIVED":
                sample["custody_status"] = "CONSUMED"
                store.bump(sample)
        if order["test_type"] in ("SIEVE_ANALYSIS", "ATTERBERG") and sample is not None:
            _recompute_uscs(sample)
        if project is not None:
            store.touch(project)
    elif to == "REJECTED":
        # Link 1: classification reset on the sample.
        if sample is not None and sample["uscs_class"] is not None:
            sample["uscs_class"] = None
            store.bump(sample)
        # Link 2: every VERIFIED analysis of the project goes STALE.
        if project is not None:
            _stale_verified_analyses(project["id"])
            store.touch(project)
    elif to == "IN_TEST" and was_rejected:
        order["rerun_count"] += 1

    store.bump(order)
    return success(serialize.lab_test_order(order))


# --------------------------------------------------------------------------
# Lab test results
# --------------------------------------------------------------------------
@bp.route("/geo/lab-test-orders/<oid>/results", methods=["POST"])
@require_roles("LabTechnician")
def create_lab_test_result(oid):
    order = get_order_or_404(oid)
    body = get_body()
    values = {}
    for field in RESULT_FIELDS:
        v = opt_num(body, field, None)
        if field == "percent_passing_200" and v is not None and not (0 <= v <= 100):
            raise err(
                "ERR_VALIDATION",
                "percent_passing_200 must be between 0 and 100",
            )
        values[field] = v
    if order["status"] != "IN_TEST":
        raise err(
            "ERR_INVALID_STATE",
            "Results may only be submitted against an IN_TEST order",
        )
    rec = {"id": store.new_id(), "lab_test_order_id": oid, "submitted_by_user_id": g.user_id}
    rec.update(values)
    store.stamp(rec)
    store.results[rec["id"]] = rec
    # System transition: the order moves IN_TEST -> RESULT_SUBMITTED.
    order["status"] = "RESULT_SUBMITTED"
    store.bump(order)
    return success(serialize.lab_test_result(rec), code=201)


@bp.route("/geo/lab-test-results/<rid>", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "LabManager", "LabTechnician", "SeniorEngineer")
def get_lab_test_result(rid):
    rec = store.results.get(rid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "LabTestResult %s not found" % rid)
    return success(serialize.lab_test_result(rec))


@bp.route("/geo/lab-test-results", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "LabManager", "LabTechnician", "SeniorEngineer")
def list_lab_test_results():
    items = list(store.results.values())
    lab_test_order_id = request.args.get("lab_test_order_id")
    if lab_test_order_id is not None:
        items = [r for r in items if r["lab_test_order_id"] == lab_test_order_id]
    page, meta = paginate(sorted_items(items))
    return success([serialize.lab_test_result(r) for r in page], "array", 200, meta)


# --------------------------------------------------------------------------
# Foundation analyses
# --------------------------------------------------------------------------
@bp.route("/geo/projects/<pid>/foundation-analyses", methods=["POST"])
@require_roles("SeniorEngineer")
def create_foundation_analysis(pid):
    project = store.projects.get(pid)
    if project is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Project %s not found" % pid)
    body = get_body()
    method = req_enum(body, "method", ANALYSIS_METHODS)
    fs_required = opt_num(body, "fs_required", 3.0, strict_gt=0)
    footing_width_ft = req_num(body, "footing_width_ft", strict_gt=0)
    applied_bearing_psf = req_num(body, "applied_bearing_psf", min_v=0)
    # Category 5: analyses only under FIELDWORK or LAB_ANALYSIS.
    if project["status"] not in ("FIELDWORK", "LAB_ANALYSIS"):
        raise err(
            "ERR_PROJECT_STATE_FORBIDS",
            "Foundation analyses require the project in FIELDWORK or LAB_ANALYSIS",
        )
    n60 = calc.n60_average(pid)
    if n60 is None:
        raise err(
            "ERR_VALIDATION",
            "No DRILLED boring data exists on the active plan",
        )
    rec = {
        "id": store.new_id(),
        "project_id": pid,
        "method": method,
        "fs_required": fs_required,
        "footing_width_ft": footing_width_ft,
        "applied_bearing_psf": applied_bearing_psf,
        "bearing_capacity_provisional_psf": calc.bearing_provisional(n60),
        "bearing_capacity_final_psf": None,
        "settlement_est_in": None,
        "deep_foundation_required": None,
        "data_status": "CURRENT",
        "status": "PRELIMINARY",
    }
    store.stamp(rec)
    store.analyses[rec["id"]] = rec
    return success(serialize.foundation_analysis(rec), code=201)


@bp.route("/geo/foundation-analyses/<aid>", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "SeniorEngineer", "PrincipalEngineer")
def get_foundation_analysis(aid):
    return success(serialize.foundation_analysis(get_analysis_or_404(aid)))


@bp.route("/geo/foundation-analyses", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "SeniorEngineer", "PrincipalEngineer")
def list_foundation_analyses():
    items = list(store.analyses.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [a for a in items if a["project_id"] == project_id]
    page, meta = paginate(sorted_items(items))
    return success([serialize.foundation_analysis(a) for a in page], "array", 200, meta)


@bp.route("/geo/foundation-analyses/<aid>/transition", methods=["POST"])
@require_roles("SeniorEngineer")
def foundation_analysis_transition(aid):
    analysis = get_analysis_or_404(aid)
    body = get_body()
    to = req_enum(body, "to", ANALYSIS_STATES)
    transition = (analysis["status"], to)
    actor = ANALYSIS_TRANSITIONS.get(transition)
    if actor is None:
        raise err(
            "ERR_INVALID_STATE",
            "FoundationAnalysis in %s cannot transition to %s" % (analysis["status"], to),
        )
    if g.role != actor:
        raise forbid_role("Transition to %s requires role %s" % (to, actor))

    project = store.projects.get(analysis["project_id"])

    if transition == ("PRELIMINARY", "VERIFIED"):
        if not calc.has_accepted_uc_order(analysis["project_id"]):
            raise err(
                "ERR_ANALYSIS_NOT_VERIFIED",
                "No ACCEPTED UNCONFINED_COMPRESSION order exists on the project",
            )
        if analysis["data_status"] != "CURRENT":
            raise err("ERR_ANALYSIS_DATA_STALE", "Analysis data is STALE")
    elif transition == ("VERIFIED", "VERIFIED"):
        if analysis["data_status"] != "STALE":
            raise err(
                "ERR_INVALID_STATE",
                "The refresh self-loop requires data_status STALE",
            )

    # Compute final values from current inputs (used by both verification and
    # the VERIFIED -> VERIFIED refresh).
    qu = calc.latest_accepted_uc_qu(analysis["project_id"])
    n60 = calc.n60_average(analysis["project_id"])
    if qu is not None:
        analysis["bearing_capacity_final_psf"] = calc.bearing_final(
            qu, analysis["fs_required"]
        )
    if n60 is not None and n60 != 0:
        settlement, deep = calc.settlement_estimate(
            analysis["applied_bearing_psf"], analysis["footing_width_ft"], n60
        )
        analysis["settlement_est_in"] = settlement
        analysis["deep_foundation_required"] = deep
    analysis["data_status"] = "CURRENT"

    if transition == ("PRELIMINARY", "VERIFIED"):
        # Verification retires every other VERIFIED analysis of the project.
        for other in store.analyses.values():
            if (
                other["project_id"] == analysis["project_id"]
                and other["id"] != analysis["id"]
                and other["status"] == "VERIFIED"
            ):
                other["status"] = "SUPERSEDED"
                store.bump(other)
        analysis["status"] = "VERIFIED"
    store.bump(analysis)
    return success(serialize.foundation_analysis(analysis))
