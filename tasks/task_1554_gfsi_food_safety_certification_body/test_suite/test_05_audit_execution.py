"""Audit execution: start gates, role exclusivity, findings, deadlines, fees."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    assert_money,
    get_audit,
    list_nonconformities,
    make_auditor,
    make_nonconformity,
    make_auditor_headers,
    make_decision_maker_headers,
    set_clock,
    setup_accepted_chain,
    setup_assigned_chain,
    setup_granted_chain,
    setup_reported_chain,
    setup_started_chain,
    start_second_audit,
    submit_report,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["scheme_admin_headers"]


class TestAuditStart:
    def test_audit_start_happy_path_in_window(self, api):
        """PRD §3.5: "A successful start moves `SCHEDULED → IN_PROGRESS`,
        stamps `started_at` with the current logical time, and increments
        `version`."

        Design: Corner/state_machines/audit_start_happy_path_in_window
        """
        chain = setup_assigned_chain()
        set_clock("2026-08-15T09:00:00Z")
        resp = api.start_audit(chain.audit["id"],
                               make_auditor_headers(chain.auditor["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "IN_PROGRESS"
        assert_instant_equal(data["started_at"], "2026-08-15T09:00:00Z")

    def test_start_unassigned_audit_rejected(self, api):
        """PRD §3.5: "An audit with no assignee at all cannot start: the
        request is rejected with `ERR_AUDIT_UNASSIGNED` (422), reachable
        precisely when there is no assignee to fail the ownership check."

        Design: Corner/state_machines/start_unassigned_audit_rejected
        """
        chain = setup_accepted_chain()  # auditor registered but NOT assigned
        set_clock("2026-08-15T09:00:00Z")
        resp = api.start_audit(chain.audit["id"],
                               make_auditor_headers(chain.auditor["id"]))
        validate_error(resp, ApiErrorId.ERR_AUDIT_UNASSIGNED, 422)
        assert get_audit(chain.audit["id"])["status"] == "SCHEDULED"

    def test_audit_start_before_window_rejected(self, api):
        """PRD §3.5: "the current logical time must lie within the window,
        endpoints inclusive (`ERR_OUTSIDE_AUDIT_WINDOW`)."

        Design: Corner/state_machines/audit_start_before_window_rejected
        """
        chain = setup_assigned_chain()
        # Window opens at 2026-08-15T00:00:00Z; 2026-08-10 is before it.
        set_clock("2026-08-10T00:00:00Z")
        resp = api.start_audit(chain.audit["id"],
                               make_auditor_headers(chain.auditor["id"]))
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_AUDIT_WINDOW, 422)
        assert get_audit(chain.audit["id"])["status"] == "SCHEDULED"

    def test_unassigned_auditor_cannot_start_audit(self, api):
        """PRD §3.5: "The ownership check runs first: an audit whose
        `auditor_id` is non-null and differs from the caller's `X-User-ID` is
        rejected with `ERR_FORBIDDEN_OWNERSHIP`, while a null `auditor_id`
        does not fail ownership."

        Design: Corner/rbac/unassigned_auditor_cannot_start_audit
        """
        chain = setup_assigned_chain()  # assigned to chain.auditor
        other = make_auditor(name="Second Auditor")
        set_clock("2026-08-15T09:00:00Z")
        resp = api.start_audit(chain.audit["id"],
                               make_auditor_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
        assert get_audit(chain.audit["id"])["status"] == "SCHEDULED"


class TestExecutionRbac:
    def test_decision_maker_cannot_record_nonconformity(self, api):
        """PRD §2.1: "A caller whose role is not listed among an endpoint's
        authorized roles is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.5: "While the audit is `IN_PROGRESS`, the assigned auditor
        records graded findings."

        Design: Corner/rbac/decision_maker_cannot_record_nonconformity
        """
        chain = setup_started_chain()
        resp = api.create_nonconformity(
            chain.audit["id"],
            {"grade": "MINOR", "clause_ref": "SQF 2.6.1",
             "description": "dm meddling"},
            make_decision_maker_headers(chain.dm["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert list_nonconformities(chain.audit["id"]) == []

    def test_scheme_admin_cannot_decide_audit(self, api):
        """PRD §2.1: "A caller whose role is not listed among an endpoint's
        authorized roles is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.6: "Rendering the certification decision is an independent
        `DecisionMaker`'s act on a `REPORT_SUBMITTED` audit"

        Design: Corner/rbac/scheme_admin_cannot_decide_audit
        """
        chain = setup_reported_chain()
        resp = api.decide_audit(chain.audit["id"], {"outcome": "GRANT"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert get_audit(chain.audit["id"])["status"] == "REPORT_SUBMITTED"


class TestInvalidTransitions:
    def test_audit_cancel_from_in_progress_rejected(self, api):
        """PRD §3.4: "Cancelling is also restricted to `SCHEDULED` audits
        (`ERR_INVALID_AUDIT_STATE` otherwise) and moves the audit to the
        terminal `CANCELLED` state"

        Design: Corner/state_machines/audit_cancel_from_in_progress_rejected
        """
        chain = setup_started_chain()
        resp = api.cancel_audit(chain.audit["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_AUDIT_STATE, 409)
        assert get_audit(chain.audit["id"])["status"] == "IN_PROGRESS"

    def test_audit_decision_before_report_rejected(self, api):
        """PRD §3.6: "Rendering the certification decision is an independent
        `DecisionMaker`'s act on a `REPORT_SUBMITTED` audit, supplying an
        `outcome` of `GRANT` or `DENY`; an audit in any other status is
        rejected with `ERR_INVALID_AUDIT_STATE`."

        Design: Corner/state_machines/audit_decision_before_report_rejected
        """
        chain = setup_started_chain()
        resp = api.decide_audit(chain.audit["id"], {"outcome": "GRANT"},
                                make_decision_maker_headers(chain.dm["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_AUDIT_STATE, 409)
        assert get_audit(chain.audit["id"])["status"] == "IN_PROGRESS"

    def test_decided_audit_terminal_lockdown(self, api):
        """PRD §3.4: "Cancelling is also restricted to `SCHEDULED` audits
        (`ERR_INVALID_AUDIT_STATE` otherwise)" — a DECIDED audit is terminal
        and rejects the transition.

        Design: Corner/state_machines/decided_audit_terminal_lockdown
        """
        chain = setup_granted_chain()
        resp = api.cancel_audit(chain.audit["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_AUDIT_STATE, 409)
        assert get_audit(chain.audit["id"])["status"] == "DECIDED"


class TestFindingDeadlines:
    def test_nc_deadline_constants_applied_per_grade(self, api):
        """PRD §3.5: "The new finding is tied to the audit through its
        `audit_id`, opens in `OPEN` status, and receives a computed
        `deadline`: the finding's `created_at` plus the scheme's per-grade day
        constant — `critical_nc_days`, `major_nc_days`, or `minor_nc_days` —
        applied as exact 24-hour multiples."

        Design: Corner/calculations/nc_deadline_constants_applied_per_grade
        """
        chain = setup_started_chain()  # deadlines 7/28/84 days
        # All three findings are created at the current logical time
        # 2026-08-15T09:00:00Z.
        critical = make_nonconformity(chain.audit["id"], chain.auditor["id"],
                                      grade="CRITICAL", clause_ref="SQF 2.4.3",
                                      description="critical")
        major = make_nonconformity(chain.audit["id"], chain.auditor["id"],
                                   grade="MAJOR", clause_ref="SQF 2.5.1",
                                   description="major")
        minor = make_nonconformity(chain.audit["id"], chain.auditor["id"],
                                   grade="MINOR", clause_ref="SQF 2.6.1",
                                   description="minor")
        assert critical["status"] == "OPEN"
        assert_instant_equal(critical["deadline"], "2026-08-22T09:00:00Z")
        assert_instant_equal(major["deadline"], "2026-09-12T09:00:00Z")
        assert_instant_equal(minor["deadline"], "2026-11-07T09:00:00Z")

    def test_unannounced_audit_fee_includes_uplift(self, api):
        """PRD §2.9: "a day-rate line equal to the issuing audit's
        `audit_fee` — the audit's declared `actual_days` multiplied by the
        scheme's `day_rate`, increased by the fractional
        `unannounced_uplift_pct` when the audit is `UNANNOUNCED`, rounded
        half-up to two decimals."
        PRD §3.5: "The transition `IN_PROGRESS → REPORT_SUBMITTED` freezes two
        computed values onto the audit: the `reported_score`, the reported
        variant of the audit score per §2.9 over all findings of the audit,
        and the `audit_fee`, the day-rate line of §2.9 including the
        unannounced uplift when the audit is `UNANNOUNCED`."

        Design: Corner/calculations/unannounced_audit_fee_includes_uplift
        """
        # unannounced_every_n 2 -> audit seq2 is UNANNOUNCED.
        chain = setup_granted_chain(actual_days=2,
                                    scheme_overrides={"unannounced_every_n": 2})
        # INITIAL (announced), 2 days x 1000.00 x 1.0.
        assert_money(chain.audit["audit_fee"], 2000.00)
        audit2 = start_second_audit(chain, at="2026-10-14T09:00:00Z")
        assert audit2["audit_type"] == "UNANNOUNCED"
        reported = submit_report(audit2["id"], chain.auditor["id"],
                                 actual_days=2)
        # UNANNOUNCED: 2 days x 1000.00 x (1 + 0.10).
        assert_money(reported["audit_fee"], 2200.00)
