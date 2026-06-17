"""ADAS recalibration: cyclic fail/retry/pass loop, bubble-up to the work order,
the cross-entity gate, and certified-technician / bay constraints (PRD 3.6)."""
from test_helpers import validate_success, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADVISOR = fx.ADVISOR
MANAGER = fx.MANAGER


# ---------------------------------------------------------------------------
# Difficulty rule 3 — recalibration_cyclic_fail_retry_loop
# ---------------------------------------------------------------------------
def test_recalibration_fail_then_retry_returns_to_scheduled(api):
    """PRD 3.6: "a Technician fails the job, moving it from SCHEDULED to FAILED".
    PRD 3.6: "a Technician may retry it, moving it back from FAILED to SCHEDULED
    (requiring the job to be FAILED and the work order still in
    AWAITING_RECALIBRATION)".

    Design: Difficulty/non_linear_state_machine/recalibration_cyclic_fail_retry_loop
    """
    ctx = fx.setup_awaiting_recalibration_with_job()
    rc = ctx["recalibration_job"]
    wo_id = ctx["work_order"]["id"]
    th = ctx["tech_headers"]
    failed = validate_success(api.fail_recalibration_job(rc["id"], th), 200)
    assert failed["status"] == "FAILED", f"fail must yield FAILED, got {failed['status']}"
    wo_mid = validate_success(api.get_work_order(wo_id, ADVISOR), 200)
    assert wo_mid["status"] == "AWAITING_RECALIBRATION", (
        f"work order must stay AWAITING_RECALIBRATION while recalibration FAILED, got {wo_mid['status']}")
    resched = validate_success(api.retry_recalibration_job(rc["id"], th), 200)
    assert resched["status"] == "SCHEDULED", f"retry must yield SCHEDULED, got {resched['status']}"


def test_recalibration_pass_after_retry_advances_work_order(api):
    """PRD 3.6: "so the job cycles through SCHEDULED → FAILED → SCHEDULED until it
    passes while the work order waits."
    PRD 3.6: "Passing bubbles up to the parent: the work order advances from
    AWAITING_RECALIBRATION to CURING".

    Design: Difficulty/non_linear_state_machine/recalibration_cyclic_fail_retry_loop
    """
    ctx = fx.setup_awaiting_recalibration_with_job()
    rc = ctx["recalibration_job"]
    wo_id = ctx["work_order"]["id"]
    th = ctx["tech_headers"]
    validate_success(api.fail_recalibration_job(rc["id"], th), 200)
    validate_success(api.retry_recalibration_job(rc["id"], th), 200)
    passed = validate_success(api.pass_recalibration_job(rc["id"], th), 200)
    assert passed["status"] == "PASSED", f"pass must yield PASSED, got {passed['status']}"
    wo_after = validate_success(api.get_work_order(wo_id, ADVISOR), 200)
    assert wo_after["status"] == "CURING", f"work order must advance to CURING, got {wo_after['status']}"


# ---------------------------------------------------------------------------
# Difficulty rule 4 — recalibration_pass_bubbles_work_order_to_curing_depth2
# ---------------------------------------------------------------------------
def test_pass_bubbles_work_order_to_curing(api):
    """PRD 3.6: "Passing bubbles up to the parent: the work order advances from
    AWAITING_RECALIBRATION to CURING, and both the recalibration job's version and
    the work order's version increment by one."

    Design: Difficulty/transitive_cascade/recalibration_pass_bubbles_work_order_to_curing_depth2
    """
    ctx = fx.setup_awaiting_recalibration_with_job()
    rc = ctx["recalibration_job"]
    wo_id = ctx["work_order"]["id"]
    passed = validate_success(api.pass_recalibration_job(rc["id"], ctx["tech_headers"]), 200)
    assert passed["status"] == "PASSED"
    wo_after = validate_success(api.get_work_order(wo_id, ADVISOR), 200)
    assert wo_after["status"] == "CURING", f"pass must bubble work order to CURING, got {wo_after['status']}"


def test_pass_sets_recalibration_job_passed(api):
    """PRD 3.6: "A Technician who is adas_certified passes it, moving it from
    SCHEDULED to PASSED".

    Design: Difficulty/transitive_cascade/recalibration_pass_bubbles_work_order_to_curing_depth2
    """
    ctx = fx.setup_awaiting_recalibration_with_job()
    rc = ctx["recalibration_job"]
    passed = validate_success(api.pass_recalibration_job(rc["id"], ctx["tech_headers"]), 200)
    assert passed["status"] == "PASSED", f"recalibration must be PASSED, got {passed['status']}"


# ---------------------------------------------------------------------------
# Difficulty rule 7 — recalibration_pass_gated_on_work_order_awaiting_recalibrationjob_to_workorder
# ---------------------------------------------------------------------------
def test_work_order_awaiting_recalibration_after_finish_install(api):
    """PRD 3.5: "when recalibration_required is true the work order moves to
    AWAITING_RECALIBRATION" — the cross-entity guard the recalibration pass depends on.

    Design: Difficulty/cross_entity_state_dependency/recalibration_pass_gated_on_work_order_awaiting_recalibrationjob_to_workorder
    """
    ctx = fx.setup_after_finish_install(adas_equipped=True, temp_c=25, humidity_pct=40)
    wo = ctx["work_order"]
    assert wo["status"] == "AWAITING_RECALIBRATION", (
        f"finish-install on ADAS REPLACE must reach AWAITING_RECALIBRATION, got {wo['status']}")


def test_recalibration_pass_requires_work_order_awaiting_then_curing(api):
    """PRD 3.6: "passing requires the job to be SCHEDULED, the linked work order to
    be in AWAITING_RECALIBRATION, and the acting technician to be adas_certified".
    PRD 3.6: "the work order advances from AWAITING_RECALIBRATION to CURING".

    Design: Difficulty/cross_entity_state_dependency/recalibration_pass_gated_on_work_order_awaiting_recalibrationjob_to_workorder
    """
    ctx = fx.setup_awaiting_recalibration_with_job()
    rc = ctx["recalibration_job"]
    wo_id = ctx["work_order"]["id"]
    before = validate_success(api.get_work_order(wo_id, ADVISOR), 200)
    assert before["status"] == "AWAITING_RECALIBRATION"
    passed = validate_success(api.pass_recalibration_job(rc["id"], ctx["tech_headers"]), 200)
    assert passed["status"] == "PASSED"
    after = validate_success(api.get_work_order(wo_id, ADVISOR), 200)
    assert after["status"] == "CURING", f"pass must advance the gated work order to CURING, got {after['status']}"


# ---------------------------------------------------------------------------
# Corner validations — uncertified_tech_recalibration_rejected
# ---------------------------------------------------------------------------
def test_uncertified_technician_cannot_open_recalibration(api):
    """PRD 3.6: "A recalibration job may only be created by a technician who is
    adas_certified; an attempt by an uncertified technician, or a STATIC calibration
    without a CALIBRATION bay, is rejected with ERR_TECH_NOT_CERTIFIED."

    Design: Corner/validations/uncertified_tech_recalibration_rejected
    """
    ctx = fx.setup_after_finish_install(adas_equipped=True, temp_c=25, humidity_pct=40)
    wo = ctx["work_order"]
    cbay = fx.create_service_bay(name="Calib Unc", bay_type="CALIBRATION")
    unc_tech = fx.create_technician(can_mobile=False, adas_certified=False, home_state="CA")
    unc_headers = fx.make_technician_headers(unc_tech["id"])
    resp = api.create_recalibration_job(
        f.create_recalibration_job_payload(
            wo["id"], unc_tech["id"], "STATIC",
            "2026-06-13T09:10:00Z", "2026-06-13T09:40:00Z", wo["version"],
            service_bay_id=cbay["id"]),
        unc_headers)
    validate_error(resp, ApiErrorId.ERR_TECH_NOT_CERTIFIED)


# ---------------------------------------------------------------------------
# Corner validations — static_recalibration_without_bay_rejected
# ---------------------------------------------------------------------------
def test_static_recalibration_without_calibration_bay_rejected(api):
    """PRD 3.6: "STATIC, which uses a fixed target board and requires a CALIBRATION
    bay (its service_bay_id must name one) ... a STATIC calibration without a
    CALIBRATION bay, is rejected with ERR_TECH_NOT_CERTIFIED."

    Design: Corner/validations/static_recalibration_without_bay_rejected
    """
    ctx = fx.setup_after_finish_install(adas_equipped=True, temp_c=25, humidity_pct=40)
    wo = ctx["work_order"]
    cert_tech_id = ctx["technician"]["id"]  # this technician is adas_certified
    cert_headers = ctx["tech_headers"]
    resp = api.create_recalibration_job(
        f.create_recalibration_job_payload(
            wo["id"], cert_tech_id, "STATIC",
            "2026-06-13T09:10:00Z", "2026-06-13T09:40:00Z", wo["version"]),
        cert_headers)
    validate_error(resp, ApiErrorId.ERR_TECH_NOT_CERTIFIED)
