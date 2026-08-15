"""Deliverable render/QC lifecycle, attempt escalation, terminal lockdown."""

from test_helpers import (
    ApiErrorId, create_deliverable, create_qc_report, enqueue_qc,
    render_complete, render_deliverable, setup_conform_ready_project,
    setup_qc_failed_deliverable, validate_error, validate_error_is_one_of,
    validate_success,
)
from test_helpers.test_users import (
    make_conform_editor_headers, make_post_supervisor_headers,
    make_qc_operator_headers,
)

CE = make_conform_editor_headers()
PS = make_post_supervisor_headers()
QC = make_qc_operator_headers()


class TestQCFailRenderCycle:
    def test_deliverable_qc_fail_render_cycle_returns_to_rendering(self, api):
        """PRD §3.7: "From `QC_FAILED`, re-rendering is permitted only while
        `qc_attempt_count` is below three attempts; once three attempts are on
        record the render request is rejected with `ERR_QC_ATTEMPTS_EXHAUSTED`."
        PRD §3.7: "with fewer than three attempts recorded, a failed deliverable
        may loop back to `RENDERING`."

        Design: Difficulty/non_linear_state_machine/deliverable_qc_fail_render_cycle
        """
        project, deliverable, _asset, _turnover, _vendor = setup_qc_failed_deliverable(
            fail_count=1,
            project_overrides={"title": "PC", "client_code": "CL005",
                               "storage_quota_gb": 100})
        resp = api.render_deliverable(
            project["id"], deliverable["id"],
            {"expected_project_version": _proj_version(api, project["id"])}, CE)
        data = validate_success(resp)
        assert data["status"] == "RENDERING", (
            f"Deliverable must cycle QC_FAILED -> RENDERING while attempts < 3; "
            f"got {data['status']}")

    def test_deliverable_qc_fail_render_cycle_preserves_attempt_count(self, api):
        """PRD §3.7: "`qc_attempt_count`, the number of QC reports recorded
        against the deliverable."
        PRD §3.7: "with fewer than three attempts recorded, a failed deliverable
        may loop back to `RENDERING`."

        Design: Difficulty/non_linear_state_machine/deliverable_qc_fail_render_cycle
        """
        project, deliverable, _asset, _turnover, _vendor = setup_qc_failed_deliverable(
            fail_count=1,
            project_overrides={"title": "PC", "client_code": "CL005",
                               "storage_quota_gb": 100})
        assert deliverable["qc_attempt_count"] == 1
        render_deliverable(project["id"], deliverable["id"])
        after = validate_success(
            api.get_deliverable(project["id"], deliverable["id"], CE))
        assert after["qc_attempt_count"] == 1, (
            f"Cycling back to RENDERING must not reset the attempt counter; "
            f"got {after['qc_attempt_count']}")
        assert after["status"] == "RENDERING"


class TestQCAttemptThreshold:
    def test_qc_attempt_threshold_boundary_exhausted_at_three(self, api):
        """PRD §3.7: "From `QC_FAILED`, re-rendering is permitted only while
        `qc_attempt_count` is below three attempts; once three attempts are on
        record the render request is rejected with `ERR_QC_ATTEMPTS_EXHAUSTED`."
        PRD §2.9 item 16: "Re-rendering a QC-failed deliverable requires fewer
        than three recorded attempts; otherwise `ERR_QC_ATTEMPTS_EXHAUSTED`
        (HTTP 422)."

        Design: Corner/calculations/qc_attempt_threshold_boundary
        """
        project, deliverable, _asset, _turnover, _vendor = setup_qc_failed_deliverable(
            fail_count=3,
            project_overrides={"title": "P", "client_code": "CL303",
                               "storage_quota_gb": 100})
        resp = api.render_deliverable(
            project["id"], deliverable["id"],
            {"expected_project_version": _proj_version(api, project["id"])}, CE)
        validate_error(resp, ApiErrorId.ERR_QC_ATTEMPTS_EXHAUSTED)
        after = validate_success(
            api.get_deliverable(project["id"], deliverable["id"], CE))
        assert after["qc_attempt_count"] == 3


class TestTerminalLockdown:
    def test_terminal_state_lockdown_deliverable(self, api):
        """PRD §3.7: "`DELIVERED` and `SUPERSEDED` are terminal; `REJECTED`
        likewise has no outgoing transitions."
        PRD §2.9 item 6: "A transition attempted on a resource that has already
        reached a terminal state of its lifecycle is instead reported as
        `ERR_ALREADY_TERMINAL` (HTTP 409)."

        Design: Corner/state_machines/terminal_state_lockdown_deliverable
        """
        project, _batch, _asset, _turnover, _vendor, _bid = setup_conform_ready_project(
            project_overrides={"title": "P", "client_code": "CL201",
                               "storage_quota_gb": 100})
        deliverable = create_deliverable(project["id"], requires_qc=False)
        render_deliverable(project["id"], deliverable["id"])
        render_complete(project["id"], deliverable["id"])
        delivered = validate_success(
            api.deliver_deliverable(project["id"], deliverable["id"], PS))
        assert delivered["status"] == "DELIVERED"
        resp = api.render_deliverable(
            project["id"], deliverable["id"],
            {"expected_project_version": _proj_version(api, project["id"])}, CE)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE.value,
                   ApiErrorId.ERR_ALREADY_TERMINAL.value])
        after = validate_success(
            api.get_deliverable(project["id"], deliverable["id"], CE))
        assert after["status"] == "DELIVERED"


def _proj_version(api, project_id):
    return validate_success(api.get_project(project_id, PS))["version"]
