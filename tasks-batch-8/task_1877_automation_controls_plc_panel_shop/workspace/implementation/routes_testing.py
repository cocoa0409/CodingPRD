"""Routes: test points and test sessions."""

from flask import Blueprint, request

from calc import recompute_asbuilt, reevaluate_job_posture
from core import (
    bump,
    envelope_object,
    err_duplicate,
    err_invalid_request,
    err_invalid_state,
    err_ref_not_found,
    err_sod,
    err_undecided,
    err_unauthorized,
    get_body,
    now_dt,
    now_iso,
    paginate,
    req_enum,
    req_int,
    req_str,
    require_roles,
    sorted_by_created,
    stamp_new,
)
from lookups import asbuilt_of_panel, get_panel, get_testsession, job_of_panel
from serializers import ser_test_point, ser_test_session
from store import db

bp = Blueprint("testing", __name__)

EXPECTED_SIGNALS = ("CONTINUITY", "VOLTAGE_24VDC", "VOLTAGE_120VAC", "ANALOG_4_20MA", "ISOLATION")
OUTCOMES = ("PASS", "FAIL", "SKIPPED")


@bp.route("/panel-shop/panels/<panel_id>/test-points", methods=["POST"])
def create_test_point(panel_id):
    require_roles("DesignEngineer")
    get_panel(panel_id)
    body = get_body()
    point_label = req_str(body, "point_label")
    expected_signal = req_enum(body, "expected_signal", EXPECTED_SIGNALS)
    sequence_no = req_int(body, "sequence_no")
    if sequence_no < 1:
        raise err_invalid_request("sequence_no must be >= 1.")
    if any(
        t["panel_id"] == panel_id and t["sequence_no"] == sequence_no
        for t in db.test_points.values()
    ):
        raise err_duplicate("sequence_no already exists within this panel.")
    t = stamp_new(
        {
            "panel_id": panel_id,
            "point_label": point_label,
            "expected_signal": expected_signal,
            "sequence_no": sequence_no,
            "result": "UNTESTED",
        },
        with_version=False,
    )
    db.test_points[t["id"]] = t
    return envelope_object(ser_test_point(t), 201)


@bp.route("/panel-shop/panels/<panel_id>/test-points", methods=["GET"])
def list_test_points(panel_id):
    require_roles("ProjectManager", "QAManager", "DesignEngineer", "TestTechnician", "ShopLead")
    get_panel(panel_id)
    points = [t for t in db.test_points.values() if t["panel_id"] == panel_id]
    if "result" in request.args:
        points = [t for t in points if t["result"] == request.args.get("result")]
    return paginate(sorted_by_created(points), ser_test_point)


@bp.route("/panel-shop/panels/<panel_id>/test-sessions", methods=["POST"])
def create_test_session(panel_id):
    require_roles("TestTechnician")
    p = get_panel(panel_id)
    body = get_body()
    technician_id = req_str(body, "technician_id")
    if p["status"] != "POINT_TO_POINT":
        raise err_invalid_state("Panel is not in POINT_TO_POINT.")
    # segregation of duties: technician must differ from the panel designer
    if technician_id == p["design_engineer_id"]:
        raise err_sod("TestTechnician must differ from the panel's design engineer.")
    s = stamp_new(
        {
            "panel_id": panel_id,
            "technician_id": technician_id,
            "status": "OPEN",
            "started_at": now_iso(),
            "completed_at": None,
            "pass_count": 0,
            "fail_count": 0,
            "_recorded_point_ids": [],
        }
    )
    db.test_sessions[s["id"]] = s
    return envelope_object(ser_test_session(s), 201)


@bp.route("/panel-shop/test-sessions/<session_id>", methods=["GET"])
def fetch_test_session(session_id):
    require_roles("ProjectManager", "QAManager", "TestTechnician", "ShopLead")
    return envelope_object(ser_test_session(get_testsession(session_id)))


@bp.route("/panel-shop/panels/<panel_id>/test-sessions", methods=["GET"])
def list_test_sessions(panel_id):
    require_roles("ProjectManager", "QAManager", "TestTechnician", "ShopLead")
    get_panel(panel_id)
    sessions = [s for s in db.test_sessions.values() if s["panel_id"] == panel_id]
    if "status" in request.args:
        sessions = [s for s in sessions if s["status"] == request.args.get("status")]
    return paginate(sorted_by_created(sessions), ser_test_session)


@bp.route("/panel-shop/test-sessions/<session_id>/record-result", methods=["POST"])
def record_result(session_id):
    require_roles("TestTechnician")
    s = get_testsession(session_id)
    body = get_body()
    test_point_id = body.get("test_point_id")
    # body-referenced FK: the point must exist and belong to the session's panel
    if not isinstance(test_point_id, str) or not test_point_id:
        raise err_invalid_request("Missing or invalid required field: test_point_id")
    t = db.test_points.get(test_point_id)
    if t is None or t["panel_id"] != s["panel_id"]:
        raise err_ref_not_found("test_point_id does not reference a test point of this panel.")
    # priority 21: parent session OPEN and point UNTESTED
    if s["status"] != "OPEN":
        raise err_undecided("TestSession is not OPEN.")
    if t["result"] != "UNTESTED":
        raise err_undecided("TestPoint is not UNTESTED.")
    outcome = req_enum(body, "outcome", OUTCOMES)
    t["result"] = outcome
    if outcome == "PASS":
        s["pass_count"] += 1
    elif outcome == "FAIL":
        s["fail_count"] += 1
    s["_recorded_point_ids"].append(t["id"])
    bump(s)
    return envelope_object(ser_test_point(t))


@bp.route("/panel-shop/test-sessions/<session_id>/complete", methods=["POST"])
def complete_test_session(session_id):
    user_id, _ = require_roles("TestTechnician")
    s = get_testsession(session_id)
    if s["status"] != "OPEN":
        raise err_invalid_state("TestSession is not OPEN.")
    points = [t for t in db.test_points.values() if t["panel_id"] == s["panel_id"]]
    if any(t["result"] == "UNTESTED" for t in points):
        raise err_undecided("Not all test points are decided.")
    # only the executing technician completes the session
    if user_id != s["technician_id"]:
        raise err_unauthorized("Only the executing technician may complete the session.")
    s["status"] = "COMPLETED"
    s["completed_at"] = now_iso()
    bump(s)
    p = db.panels[s["panel_id"]]
    if p["status"] == "POINT_TO_POINT":
        if s["fail_count"] >= 1:
            p["status"] = "TEST_FAILED"
            bump(p)
            reevaluate_job_posture(job_of_panel(p))
        elif all(t["result"] == "PASS" for t in points):
            p["status"] = "TEST_PASSED"
            bump(p)
            pkg = asbuilt_of_panel(p["id"])
            if pkg is not None and not pkg["has_test_report"]:
                pkg["has_test_report"] = True
                recompute_asbuilt(pkg)
            reevaluate_job_posture(job_of_panel(p))
        # fail_count == 0 with SKIPPED points: no panel auto-transition
    return envelope_object(ser_test_session(s))


@bp.route("/panel-shop/test-sessions/<session_id>/abort", methods=["POST"])
def abort_test_session(session_id):
    require_roles("TestTechnician")
    s = get_testsession(session_id)
    if s["status"] != "OPEN":
        raise err_invalid_state("TestSession is not OPEN.")
    for pid in s["_recorded_point_ids"]:
        t = db.test_points.get(pid)
        if t is not None and t["result"] in ("PASS", "FAIL", "SKIPPED"):
            t["result"] = "UNTESTED"
    s["pass_count"] = 0
    s["fail_count"] = 0
    s["status"] = "ABORTED"
    bump(s)
    return envelope_object(ser_test_session(s))
