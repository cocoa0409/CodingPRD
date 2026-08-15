"""Remediation lifecycle: create gate, decide/verify SoD, overdue/extend cycle, closure cascade."""
from test_helpers import (
    ApiErrorId,
    create_remediation_action_payload,
    get_case,
    make_admin_headers,
    setup_case_in_remediation,
    setup_case_determination_review,
    setup_remediation_action,
    validate_error,
    validate_success,
    api_client,
)


class TestRemediationCreateGate:
    def test_create_on_submitted_determination_rejected(self, api):
        """PRD §3.6: "An officer proposes a remediation action on an `APPROVED`
        determination whose finding is `SUBSTANTIATED` — any other determination
        fails with `ERR_DETERMINATION_NOT_APPROVED`".

        Design: Corner/errors/remediation_create_on_unapproved_determination_rejected
        """
        ctx = setup_case_determination_review(finding="SUBSTANTIATED")
        staff = ctx["staff"]
        resp = api.create_remediation_action(
            ctx["determination"]["id"], create_remediation_action_payload(), staff["h_off"],
        )
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_NOT_APPROVED)


class TestRemediationSoD:
    def test_decide_by_creator_rejected(self, api):
        """PRD §3.6: "a different officer than the creator (`ERR_SOD_SELF_VERIFY`)
        decides the action".

        Design: Corner/errors/sod_self_verify_on_remediation_decide
        """
        ctx = setup_case_in_remediation()
        staff = ctx["staff"]
        # propose as off1, attempt decide as off1
        resp = api.create_remediation_action(ctx["determination"]["id"],
                                             create_remediation_action_payload(), staff["h_off"])
        action = validate_success(resp, expected_status=201)
        resp2 = api.decide_remediation_action(action["id"], {"decision": "APPROVE"}, staff["h_off"])
        validate_error(resp2, ApiErrorId.ERR_SOD_SELF_VERIFY)

    def test_verify_proposed_action_rejected(self, api):
        """PRD §3.6: "Verification — by an officer other than the creator
        (`ERR_SOD_SELF_VERIFY`), and only from `IN_PROGRESS` (otherwise
        `ERR_REMEDIATION_INVALID_STATE`)".

        Design: Corner/errors/verify_proposed_action_rejected
        """
        ctx = setup_case_in_remediation()
        staff = ctx["staff"]
        resp = api.create_remediation_action(ctx["determination"]["id"],
                                             create_remediation_action_payload(), staff["h_off"])
        action = validate_success(resp, expected_status=201)
        resp2 = api.verify_remediation_action(action["id"], staff["h_off2"])
        validate_error(resp2, ApiErrorId.ERR_REMEDIATION_INVALID_STATE)


class TestExtensionWindow:
    def test_extension_beyond_30_days_rejected(self, api):
        """PRD §3.6: "the new `due_date` must be strictly later than now and no later
        than 30 days from now, otherwise `ERR_EXTENSION_WINDOW_EXCEEDED`".

        Design: Corner/errors/extension_beyond_30_days_rejected
        """
        ctx = setup_case_in_remediation()
        staff = ctx["staff"]
        action = setup_remediation_action(ctx, due_date="2026-08-10T00:00:00Z")
        api.set_clock("2026-08-11T00:00:00Z", make_admin_headers())
        # action is OVERDUE after sweep (due 08-10 < now 08-11)
        resp = api.extend_remediation_action(action["id"],
                                             {"due_date": "2026-09-11T00:00:00Z"},
                                             staff["h_off"])
        validate_error(resp, ApiErrorId.ERR_EXTENSION_WINDOW_EXCEEDED)


class TestOverdueExtensionCycle:
    """Difficulty: remediation_overdue_extension_cycle (2 tests)."""

    def _setup_overdue_loops(self, api):
        """One IN_PROGRESS action, driven OVERDUE -> IN_PROGRESS twice."""
        ctx = setup_case_in_remediation()
        staff = ctx["staff"]
        action = setup_remediation_action(ctx, due_date="2026-08-10T00:00:00Z")
        # first overdue + extend
        api.set_clock("2026-08-11T00:00:00Z", make_admin_headers())
        api.extend_remediation_action(action["id"], {"due_date": "2026-08-20T00:00:00Z"}, staff["h_off"])
        # second overdue + extend
        api.set_clock("2026-08-25T00:00:00Z", make_admin_headers())
        api.extend_remediation_action(action["id"], {"due_date": "2026-09-01T00:00:00Z"}, staff["h_off2"])
        return ctx, action

    def test_extension_count_after_two_cycles(self, api):
        """PRD §3.6: "An `OVERDUE` action can be brought back to `IN_PROGRESS` by
        extending it ... each successful extension increments the action's
        `extension_count`".

        Design: Difficulty/non_linear_state_machine/remediation_overdue_extension_cycle
        """
        ctx, action = self._setup_overdue_loops(api)
        staff = ctx["staff"]
        resp = api.verify_remediation_action(action["id"], staff["h_off2"])
        data = validate_success(resp)
        assert data["status"] == "VERIFIED"
        assert data["extension_count"] == 2, "cycle IN_PROGRESS -> OVERDUE -> IN_PROGRESS traversed twice"

    def test_verify_cascades_case_to_closure_ready(self, api):
        """PRD §3.6: "When the rule fires, the case moves to `CLOSURE_READY`,
        `closure_ready_at` is stamped, a closure notice is created in `SENT`
        status".

        Design: Difficulty/non_linear_state_machine/remediation_overdue_extension_cycle
        """
        ctx, action = self._setup_overdue_loops(api)
        staff = ctx["staff"]
        api.verify_remediation_action(action["id"], staff["h_off2"])
        case = get_case(ctx["case"]["id"], staff["h_off"])
        assert case["status"] == "CLOSURE_READY"
        notices = api.list_closure_notices(ctx["case"]["id"], staff["h_off"]).json()["data"]
        assert len(notices) == 1
        assert notices[0]["status"] == "SENT"


class TestVerifyClosureCascade:
    """Difficulty: remediation_verify_closure_notice_cascade (2 tests)."""

    def _setup_single_in_progress_action(self, api):
        ctx = setup_case_in_remediation()
        staff = ctx["staff"]
        action = setup_remediation_action(
            ctx, action_type="POLICY_CHANGE", description="Tighten expense approval policy",
            due_date="2026-09-15T00:00:00Z",
        )
        return ctx, action

    def test_verify_moves_action_and_case(self, api):
        """PRD §3.6: "Verification ... moves the action to `VERIFIED`" and "When the
        rule fires, the case moves to `CLOSURE_READY`, `closure_ready_at` is
        stamped".

        Design: Difficulty/transitive_cascade/remediation_verify_closure_notice_cascade
        """
        ctx, action = self._setup_single_in_progress_action(api)
        staff = ctx["staff"]
        resp = api.verify_remediation_action(action["id"], staff["h_off2"])
        data = validate_success(resp)
        assert data["status"] == "VERIFIED"
        case = get_case(ctx["case"]["id"], staff["h_off"])
        assert case["status"] == "CLOSURE_READY"
        assert case["closure_ready_at"] == "2026-08-01T00:00:00Z"

    def test_verify_creates_sent_notice_and_event(self, api):
        """PRD §3.6: "When the rule fires, the case moves to `CLOSURE_READY`,
        `closure_ready_at` is stamped, a closure notice is created in `SENT`
        status, a `CLOSURE_READY` event is appended".

        Design: Difficulty/transitive_cascade/remediation_verify_closure_notice_cascade
        """
        ctx, action = self._setup_single_in_progress_action(api)
        staff = ctx["staff"]
        api.verify_remediation_action(action["id"], staff["h_off2"])
        notices = api.list_closure_notices(ctx["case"]["id"], staff["h_off"]).json()["data"]
        assert len(notices) == 1
        assert notices[0]["status"] == "SENT"
        assert notices[0]["sent_at"] == "2026-08-01T00:00:00Z"
        events = api.list_case_status_events(ctx["case"]["id"], staff["h_off"]).json()["data"]
        assert any(e["event_type"] == "CLOSURE_READY" for e in events)
