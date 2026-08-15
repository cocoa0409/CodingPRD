"""Customer audits and CAPA findings: window rules, open/close gating, and the
finding lifecycle."""
from test_helpers import (
    QA,
    ApiErrorId,
    add_audit_finding,
    assert_audit,
    assert_audit_finding,
    create_audit,
    create_audit_payload,
    create_room,
    get_success_data,
    open_audit,
    set_clock,
    setup_audit_in_progress,
    validate_error,
    validate_success,
)


def _room(room_code):
    return create_room(room_code=room_code, iso_class="ISO_8",
                       particle_alert_limit=3500000, particle_action_limit=3520000,
                       viable_alert_limit=100, viable_action_limit=200)


class TestAuditWindow:
    def test_audit_window_end_not_after_start_rejected(self, api):
        """PRD §3.8: "the window must be non-empty, with `window_end` strictly
        after `window_start`, otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/audit_window_end_not_after_start_rejected
        """
        room = _room("CR-E7")
        resp = api.create_audit(
            create_audit_payload(room["id"], customer_code="CUST-E7",
                                 window_start="2026-08-02T00:00:00Z",
                                 window_end="2026-08-02T00:00:00Z"),
            QA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_audit_open_window_boundary(self, api):
        """PRD §3.8: "Opening the audit requires it to stand `SCHEDULED`
        (`ERR_AUDIT_NOT_SCHEDULED`) and requires the logical clock to have
        reached or passed `window_start` (`ERR_AUDIT_WINDOW_NOT_STARTED`)."

        Design: Corner/state_machines/audit_open_before_window_start_rejected
        """
        room = _room("CR-S8")
        audit = create_audit(room["id"], customer_code="CUST-S8",
                             window_start="2026-08-10T00:00:00Z",
                             window_end="2026-08-20T00:00:00Z")

        set_clock("2026-08-09T23:59:59Z")
        resp = api.open_audit(audit["id"], QA)
        validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_NOT_STARTED)

        set_clock("2026-08-10T00:00:00Z")
        opened = validate_success(api.open_audit(audit["id"], QA), 200)
        assert_audit(opened)
        assert opened["status"] == "IN_PROGRESS", (
            "at exactly window_start the clock has reached the window (>=)")


class TestAuditCloseGating:
    def test_audit_close_blocked_by_unverified_finding(self, api):
        """PRD §3.8: "Closing the audit requires it to stand `IN_PROGRESS`
        (`ERR_AUDIT_NOT_IN_PROGRESS`) and requires every finding of the audit
        to stand at `CAPA_VERIFIED`; if any finding is still short of verified,
        the close is rejected with `ERR_AUDIT_FINDINGS_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/audit_close_gated_on_finding_states
        """
        room = _room("CR-N")
        audit = setup_audit_in_progress(room["id"], customer_code="CUST-N")
        finding1 = add_audit_finding(audit["id"], severity="MINOR",
                                     description="Log gap on second shift")
        finding2 = add_audit_finding(audit["id"], severity="MAJOR",
                                     description="Missing wipe-down record")
        get_success_data(api.submit_finding_capa(finding1["id"], QA))
        get_success_data(api.verify_finding_capa(finding1["id"], QA))
        get_success_data(api.submit_finding_capa(finding2["id"], QA))

        resp = api.close_audit(audit["id"], QA)
        # finding2 stands at CAPA_SUBMITTED, short of CAPA_VERIFIED
        validate_error(resp, ApiErrorId.ERR_AUDIT_FINDINGS_OPEN)
        assert get_success_data(api.get_audit(audit["id"], QA))["status"] == (
            "IN_PROGRESS")

    def test_audit_close_succeeds_when_all_findings_verified(self, api):
        """PRD §3.8: "Closing the audit requires it to stand `IN_PROGRESS`
        (`ERR_AUDIT_NOT_IN_PROGRESS`) and requires every finding of the audit
        to stand at `CAPA_VERIFIED`; if any finding is still short of verified,
        the close is rejected with `ERR_AUDIT_FINDINGS_OPEN`. A successful
        close moves the audit to terminal `CLOSED`."
        PRD §3.8: "Verifying the audit's last unverified finding does not
        itself close the audit; the audit remains `IN_PROGRESS` until
        explicitly closed."

        Design: Difficulty/cross_entity_state_dependency/audit_close_gated_on_finding_states
        """
        room = _room("CR-N")
        audit = setup_audit_in_progress(room["id"], customer_code="CUST-N")
        finding1 = add_audit_finding(audit["id"], severity="MINOR",
                                     description="Log gap on second shift")
        finding2 = add_audit_finding(audit["id"], severity="MAJOR",
                                     description="Missing wipe-down record")
        for finding in (finding1, finding2):
            get_success_data(api.submit_finding_capa(finding["id"], QA))
            get_success_data(api.verify_finding_capa(finding["id"], QA))

        assert get_success_data(api.get_audit(audit["id"], QA))["status"] == (
            "IN_PROGRESS"), "verifying the last finding does not close the audit"
        closed = validate_success(api.close_audit(audit["id"], QA), 200)
        assert closed["status"] == "CLOSED"


class TestFindingLifecycle:
    def test_submit_capa_on_submitted_finding_rejected(self, api):
        """PRD §3.8: "A finding's CAPA lifecycle advances from `OPEN` to
        `CAPA_SUBMITTED` when QA submits the corrective action — only from
        `OPEN`, otherwise `ERR_FINDING_NOT_OPEN` — and from `CAPA_SUBMITTED` to
        terminal `CAPA_VERIFIED` when QA verifies the submitted action — only
        from `CAPA_SUBMITTED`, otherwise `ERR_FINDING_NOT_CAPA_SUBMITTED`."

        Design: Corner/errors/error_finding_not_open_on_submit
        """
        room = _room("CR-ER3")
        audit = setup_audit_in_progress(room["id"], customer_code="CUST-ER3")
        finding = add_audit_finding(audit["id"], severity="MINOR",
                                    description="Finding for ER3")
        submitted = validate_success(api.submit_finding_capa(finding["id"], QA), 200)
        assert submitted["status"] == "CAPA_SUBMITTED"

        resp = api.submit_finding_capa(finding["id"], QA)
        validate_error(resp, ApiErrorId.ERR_FINDING_NOT_OPEN)

    def test_verify_capa_on_open_finding_rejected(self, api):
        """PRD §3.8: "A finding's CAPA lifecycle advances from `OPEN` to
        `CAPA_SUBMITTED` when QA submits the corrective action — only from
        `OPEN`, otherwise `ERR_FINDING_NOT_OPEN` — and from `CAPA_SUBMITTED` to
        terminal `CAPA_VERIFIED` when QA verifies the submitted action — only
        from `CAPA_SUBMITTED`, otherwise `ERR_FINDING_NOT_CAPA_SUBMITTED`."

        Design: Corner/errors/error_finding_not_capa_submitted_on_verify
        """
        room = _room("CR-ER4")
        audit = setup_audit_in_progress(room["id"], customer_code="CUST-ER4")
        finding = add_audit_finding(audit["id"], severity="OBSERVATION",
                                    description="Finding for ER4")
        assert_audit_finding(finding)
        assert finding["status"] == "OPEN"

        resp = api.verify_finding_capa(finding["id"], QA)
        validate_error(resp, ApiErrorId.ERR_FINDING_NOT_CAPA_SUBMITTED)


class TestAuditStateGuards:
    def test_close_scheduled_audit_rejected(self, api):
        """PRD §3.8: "Closing the audit requires it to stand `IN_PROGRESS`
        (`ERR_AUDIT_NOT_IN_PROGRESS`) and requires every finding of the audit
        to stand at `CAPA_VERIFIED`; if any finding is still short of verified,
        the close is rejected with `ERR_AUDIT_FINDINGS_OPEN`."

        Design: Corner/errors/error_audit_not_in_progress_on_close
        """
        room = _room("CR-ER5")
        audit = create_audit(room["id"], customer_code="CUST-ER5")
        assert audit["status"] == "SCHEDULED"

        resp = api.close_audit(audit["id"], QA)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_IN_PROGRESS)

    def test_reopen_in_progress_audit_rejected(self, api):
        """PRD §3.8: "Opening the audit requires it to stand `SCHEDULED`
        (`ERR_AUDIT_NOT_SCHEDULED`) and requires the logical clock to have
        reached or passed `window_start` (`ERR_AUDIT_WINDOW_NOT_STARTED`)."

        Design: Corner/errors/error_audit_not_scheduled_on_reopen
        """
        room = _room("CR-ER9")
        audit = create_audit(room["id"], customer_code="CUST-ER9")
        open_audit(audit["id"])

        resp = api.open_audit(audit["id"], QA)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_SCHEDULED)
