"""Test reports and arc-flash compliance labels (PRD 3.6)."""
from flask import Blueprint

import calc
import clock
import common
import envelope
import posture
import rbac
import store
import validation
from errors import ApiError
from validation import INTEGER, NUMBER, STRING, f

bp = Blueprint("reports", __name__)


def _verdict(report):
    fat = store.get("fat", report.get("factory_acceptance_test_id"))
    verdict, failed = calc.report_verdict(report, fat)
    report["pass_result"] = verdict
    report["failed_criteria"] = failed
    return report


def _check_label_fresh(label, order):
    """Rung 43."""
    if label.get("status") == "STALE":
        raise ApiError("ERR_LABEL_STALE", "the label is stale")
    if label.get("pinned_drawing_revision") != order.get("released_drawing_revision"):
        raise ApiError("ERR_LABEL_STALE",
                       "the pinned revision no longer matches the released revision")


def _check_report_issued(report):
    """Rung 45."""
    if report.get("status") != "ISSUED" or report.get("pass_result") != "PASS":
        raise ApiError("ERR_TEST_REPORT_NOT_ISSUED",
                       "the pinned test report must be ISSUED with a PASS verdict")


# --------------------------------------------------------------------------- #
# test reports
# --------------------------------------------------------------------------- #

@bp.route("/factory-acceptance-tests/<fid>/test-reports", methods=["POST"])
def create_report(fid):
    rbac.authenticate("POST /factory-acceptance-tests/{id}/test-reports")
    fat = common.resolve("fat", fid)
    order = common.resolve("order", fat.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [
        f("winding_temp_rise_c", NUMBER, required=True, minimum=0),
        f("temp_rise_limit_c", NUMBER, required=True),
        f("short_circuit_current_ka", NUMBER, required=True),
        f("arc_duration_ms", INTEGER, required=True, minimum=1, maximum=2000),
        f("working_distance_mm", INTEGER, minimum=100, maximum=2000, default=455),
        f("impulse_withstand_kv", NUMBER, minimum=0),
        f("impulse_required_kv", NUMBER, minimum=0),
    ])
    if data["temp_rise_limit_c"] <= 0:
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE", "temp_rise_limit_c must be above zero")
    if data["short_circuit_current_ka"] <= 0:
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE",
                       "short_circuit_current_ka must be above zero")
    common.check_order_not_cancelled(order)
    report = {
        "factory_acceptance_test_id": fid,
        "status": "DRAFT",
        "winding_temp_rise_c": data["winding_temp_rise_c"],
        "temp_rise_limit_c": data["temp_rise_limit_c"],
        "impulse_withstand_kv": data.get("impulse_withstand_kv"),
        "impulse_required_kv": data.get("impulse_required_kv"),
        "short_circuit_current_ka": data["short_circuit_current_ka"],
        "arc_duration_ms": data["arc_duration_ms"],
        "working_distance_mm": data["working_distance_mm"],
        "pass_result": None,
        "failed_criteria": [],
        "issued_at": None,
    }
    _verdict(report)
    store.insert("report", report)
    return envelope.created(store.public(report))


@bp.route("/factory-acceptance-tests/<fid>/test-reports", methods=["GET"])
def list_fat_reports(fid):
    rbac.authenticate("GET /factory-acceptance-tests/{id}/test-reports")
    common.resolve("fat", fid)
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.where("report", factory_acceptance_test_id=fid),
                               {"status": common.qstr("status")})
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/test-reports/<rid>", methods=["GET"])
def get_report(rid):
    rbac.authenticate("GET /test-reports/{id}")
    return envelope.ok(store.public(common.resolve("report", rid)))


@bp.route("/test-reports/<rid>/issue", methods=["POST"])
def issue_report(rid):
    actor = rbac.authenticate("POST /test-reports/{id}/issue")
    report = common.resolve("report", rid)
    fat = common.resolve("fat", report.get("factory_acceptance_test_id"))
    if fat.get("run_by_user_id") is not None and actor.user_id != fat.get("run_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "only the operator recorded in run_by_user_id may issue the report")
    common.check_state("report", report, ("DRAFT",))
    if fat.get("status") != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the parent test is %s" % fat.get("status"))
    for name in ("winding_temp_rise_c", "temp_rise_limit_c", "short_circuit_current_ka",
                 "arc_duration_ms", "working_distance_mm"):
        if report.get(name) is None:
            raise ApiError("ERR_TEST_REPORT_INCOMPLETE", "%s is missing" % name)
    if fat.get("requires_impulse"):
        if report.get("impulse_withstand_kv") is None or report.get("impulse_required_kv") is None:
            raise ApiError("ERR_TEST_REPORT_INCOMPLETE",
                           "impulse readings are mandatory on an impulse test")
        if not report.get("impulse_required_kv") > 0:
            raise ApiError("ERR_TEST_REPORT_INCOMPLETE",
                           "impulse_required_kv must be above zero")
    report["status"] = "ISSUED"
    report["issued_at"] = clock.now_str()
    _verdict(report)
    store.touch("report", report)
    for other in store.where("report", factory_acceptance_test_id=fat["id"]):
        if other["id"] == rid or other.get("status") != "ISSUED":
            continue
        other["status"] = "SUPERSEDED"
        store.touch("report", other)
        for label in store.where("label", test_report_id=other["id"]):
            if label.get("status") in ("GENERATED", "VERIFIED"):
                label["status"] = "STALE"
                label["void_reason"] = "REPORT_SUPERSEDED"
                store.touch("label", label)
    posture.refresh_by_id(fat.get("engineered_order_id"))
    return envelope.ok(store.public(report))


# --------------------------------------------------------------------------- #
# compliance labels
# --------------------------------------------------------------------------- #

@bp.route("/engineered-orders/<oid>/compliance-labels", methods=["POST"])
def create_label(oid):
    rbac.authenticate("POST /engineered-orders/{id}/compliance-labels")
    order = common.resolve("order", oid)
    payload = validation.body()
    drawing = None
    if payload.get("submittal_drawing_id") is not None:
        if not isinstance(payload["submittal_drawing_id"], str):
            raise ApiError("ERR_FIELD_TYPE_INVALID", "submittal_drawing_id must be of type string")
        drawing = common.resolve("drawing", payload["submittal_drawing_id"],
                                 "engineered_order_id", oid)
    report = None
    if payload.get("test_report_id") is not None:
        report = common.resolve_body_ref("report", payload, "test_report_id")
    data = validation.validate(payload, [
        f("submittal_drawing_id", STRING, required=True),
        f("test_report_id", STRING, required=True),
        f("generated_by_user_id", STRING, required=True),
        f("expected_engineered_order_version", INTEGER, required=True),
    ])
    validation.check_order_version(data, order)
    common.check_order_not_cancelled(order)
    _check_report_issued(report)
    label = {
        "engineered_order_id": oid,
        "submittal_drawing_id": drawing["id"],
        "test_report_id": report["id"],
        "pinned_drawing_revision": drawing.get("revision_round"),
        "status": "DRAFT",
        "incident_energy_cal_cm2": None,
        "ppe_category": None,
        "arc_flash_boundary_mm": None,
        "rating_text": None,
        "generated_by_user_id": data["generated_by_user_id"],
        "verified_by_user_id": None,
        "void_reason": None,
    }
    store.insert("label", label)
    store.touch("order", order)
    posture.refresh(order)
    return envelope.created(store.public(label))


@bp.route("/engineered-orders/<oid>/compliance-labels", methods=["GET"])
def list_order_labels(oid):
    rbac.authenticate("GET /engineered-orders/{id}/compliance-labels")
    common.resolve("order", oid)
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.where("label", engineered_order_id=oid),
                               {"status": common.qstr("status")})
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/compliance-labels", methods=["GET"])
def list_labels():
    rbac.authenticate("GET /compliance-labels")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("label"), {
        "engineered_order_id": common.qstr("engineered_order_id"),
        "submittal_drawing_id": common.qstr("submittal_drawing_id"),
        "test_report_id": common.qstr("test_report_id"),
        "status": common.qstr("status"),
        "ppe_category": common.qint("ppe_category"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/compliance-labels/<lid>", methods=["GET"])
def get_label(lid):
    rbac.authenticate("GET /compliance-labels/{id}")
    return envelope.ok(store.public(common.resolve("label", lid)))


@bp.route("/compliance-labels/<lid>/generate", methods=["POST"])
def generate_label(lid):
    actor = rbac.authenticate("POST /compliance-labels/{id}/generate")
    label = common.resolve("label", lid)
    order = common.resolve("order", label.get("engineered_order_id"))
    report = common.resolve("report", label.get("test_report_id"))
    drawing = common.resolve("drawing", label.get("submittal_drawing_id"))
    common.check_state("label", label, ("DRAFT",))
    common.check_order_not_cancelled(order)
    common.check_design_released(order)
    energy, category, boundary, rating = calc.arc_flash_values(order, report)
    if category is None:
        raise ApiError("ERR_ARC_ENERGY_UNLABELABLE",
                       "incident energy reaches 40.0 cal/cm2; no label may be produced")
    _check_label_fresh(label, order)
    _check_report_issued(report)
    if drawing.get("status") not in ("APPROVED", "APPROVED_AS_NOTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the pinned drawing is %s" % drawing.get("status"))
    label["status"] = "GENERATED"
    label["incident_energy_cal_cm2"] = energy
    label["ppe_category"] = category
    label["arc_flash_boundary_mm"] = boundary
    label["rating_text"] = rating
    if not label.get("generated_by_user_id"):
        label["generated_by_user_id"] = actor.user_id
    store.touch("label", label)
    posture.refresh(order)
    return envelope.ok(store.public(label))


@bp.route("/compliance-labels/<lid>/verify", methods=["POST"])
def verify_label(lid):
    actor = rbac.authenticate("POST /compliance-labels/{id}/verify")
    label = common.resolve("label", lid)
    order = common.resolve("order", label.get("engineered_order_id"))
    drawing = common.resolve("drawing", label.get("submittal_drawing_id"))
    rbac.check_sod(actor, label.get("generated_by_user_id"))
    rbac.check_sod(actor, drawing.get("authored_by_user_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("verified_by_user_id", STRING, required=True)])
    if data["verified_by_user_id"] in (label.get("generated_by_user_id"),
                                      drawing.get("authored_by_user_id")):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the verifier must differ from the generator and the drawing author")
    common.check_state("label", label, ("GENERATED",))
    common.check_order_not_cancelled(order)
    _check_label_fresh(label, order)
    label["status"] = "VERIFIED"
    label["verified_by_user_id"] = data["verified_by_user_id"]
    store.touch("label", label)
    posture.refresh(order)
    return envelope.ok(store.public(label))


@bp.route("/compliance-labels/<lid>/issue", methods=["POST"])
def issue_label(lid):
    rbac.authenticate("POST /compliance-labels/{id}/issue")
    label = common.resolve("label", lid)
    order = common.resolve("order", label.get("engineered_order_id"))
    common.check_state("label", label, ("VERIFIED",))
    common.check_order_not_cancelled(order)
    posture.check_posture_blocked(order)
    _check_label_fresh(label, order)
    if (label.get("ppe_category") or 0) > 4:
        raise ApiError("ERR_ARC_ENERGY_UNLABELABLE", "ppe_category exceeds 4")
    for other in store.where("label", engineered_order_id=order["id"]):
        if other["id"] != lid and other.get("status") == "ISSUED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "label %s is already issued on this order" % other["id"])
    label["status"] = "ISSUED"
    store.touch("label", label)
    store.touch("order", order)
    posture.refresh(order)
    return envelope.ok(store.public(label))


@bp.route("/compliance-labels/<lid>/void", methods=["POST"])
def void_label(lid):
    rbac.authenticate("POST /compliance-labels/{id}/void")
    label = common.resolve("label", lid)
    order = common.resolve("order", label.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("void_reason", STRING, required=True)])
    was_stale = label.get("status") == "STALE"
    common.check_state("label", label,
                       ("DRAFT", "GENERATED", "STALE", "VERIFIED", "ISSUED"))
    label["status"] = "VOIDED"
    if not was_stale or not label.get("void_reason"):
        label["void_reason"] = data["void_reason"]
    store.touch("label", label)
    common.revert_cleared_releases(order, also_staged=True)
    posture.refresh(order)
    return envelope.ok(store.public(label))
