"""Annual procedure audits: scheduling guards, double-booking, verification
sample minimum, completion side effects, and the audit-due boundary."""
from test_helpers import (
    ApiErrorId,
    apply_lock,
    assert_instant_equal,
    assert_procedure_audit,
    bootstrap_manager,
    create_approved_survey,
    create_draft_procedure,
    create_lockout_session_payload,
    create_machine,
    create_procedure_audit_payload,
    create_session,
    get_procedure,
    issue_lock,
    lock_session,
    make_authorized_employee_headers,
    make_ehs_auditor_headers,
    make_ehs_manager_headers,
    register_employee,
    register_qualified_employee,
    run_session_to_released,
    schedule_audit,
    set_logical_clock,
    setup_machine_with_active_procedure,
    validate_error,
    validate_success,
)


class TestAuditSchedulingGuards:
    def test_auditor_conflict_with_period_applier_rejected(self, api):
        """PRD §3.7: "Scheduling is guarded, in this order: the auditor must be a
        currently qualified authorized employee (`ERR_TRAINING_NOT_CURRENT`); the
        auditor must be independent — they must not appear among the employees
        who applied locks under this procedure within the audit period
        (`ERR_AUDITOR_CONFLICT`); and the auditor must not be double-booked — no
        other `SCHEDULED` audit of the same auditor may have a window overlapping
        the new one, with both windows treated as closed intervals so that
        touching endpoints do conflict and back-to-back audits are rejected
        (`ERR_AUDITOR_DOUBLE_BOOKED`)."

        Design: Corner/validations/auditor_conflict_with_period_applier_rejected
        """
        mgr = bootstrap_manager("E-MGR-AC", "Mgr AC")
        primary = register_qualified_employee(mgr, "E-W1-AC", "W1 AC")
        conflicted = register_qualified_employee(mgr, "E-W2-AC", "W2 AC")
        independent = register_qualified_employee(mgr, "E-W3-AC", "W3 AC")
        machine, survey, procedure = setup_machine_with_active_procedure(
            mgr, primary, asset_tag="A-AC-1", isolation_points=2)
        session = create_session(primary, machine["id"], procedure["id"], "GROUP")
        lock = issue_lock(conflicted, session["id"], "L-AC-2", "T-AC-2")
        apply_lock(conflicted, lock["id"])

        resp = api.create_procedure_audit(
            create_procedure_audit_payload(
                procedure["id"], scheduled_start="2026-09-05T09:00:00Z",
                scheduled_end="2026-09-05T12:00:00Z"),
            make_ehs_auditor_headers(conflicted["id"]))
        validate_error(resp, ApiErrorId.ERR_AUDITOR_CONFLICT)

        audit = validate_success(api.create_procedure_audit(
            create_procedure_audit_payload(
                procedure["id"], scheduled_start="2026-09-05T09:00:00Z",
                scheduled_end="2026-09-05T12:00:00Z"),
            make_ehs_auditor_headers(independent["id"])), expected_status=201)
        assert_procedure_audit(audit)
        assert audit["status"] == "SCHEDULED"
        assert audit["auditor_employee_id"] == independent["id"]


class TestAuditorDoubleBooking:
    def _setup_auditor_with_first_audit(self, api, suffix):
        mgr = bootstrap_manager(f"E-MGR-DB{suffix}", "Mgr DB")
        surveyor = register_employee(mgr, f"E-W1-DB{suffix}", "W1 DB")
        auditor = register_qualified_employee(mgr, f"E-W2-DB{suffix}", "W2 DB")
        machine, survey, procedure = setup_machine_with_active_procedure(
            mgr, surveyor, asset_tag=f"A-DB{suffix}-100")
        first = schedule_audit(auditor, procedure["id"],
                               scheduled_start="2026-09-01T09:00:00Z",
                               scheduled_end="2026-09-01T12:00:00Z")
        return mgr, auditor, procedure, first

    def test_touching_audit_window_rejected(self, api):
        """PRD §3.7: "the auditor must not be double-booked — no other
        `SCHEDULED` audit of the same auditor may have a window overlapping the
        new one, with both windows treated as closed intervals so that touching
        endpoints do conflict and back-to-back audits are rejected
        (`ERR_AUDITOR_DOUBLE_BOOKED`)."

        Design: Difficulty/resource_temporal_overlap/auditor_double_booking_closed_interval
        """
        mgr, auditor, procedure, first = self._setup_auditor_with_first_audit(api, "A")
        assert first["status"] == "SCHEDULED"

        resp = api.create_procedure_audit(
            create_procedure_audit_payload(
                procedure["id"], scheduled_start="2026-09-01T12:00:00Z",
                scheduled_end="2026-09-01T15:00:00Z"),
            make_ehs_auditor_headers(auditor["id"]))
        validate_error(resp, ApiErrorId.ERR_AUDITOR_DOUBLE_BOOKED)

    def test_one_second_gap_between_audit_windows_accepted(self, api):
        """PRD §3.7: "the auditor must not be double-booked — no other
        `SCHEDULED` audit of the same auditor may have a window overlapping the
        new one, with both windows treated as closed intervals so that touching
        endpoints do conflict and back-to-back audits are rejected
        (`ERR_AUDITOR_DOUBLE_BOOKED`)."

        Design: Difficulty/resource_temporal_overlap/auditor_double_booking_closed_interval
        """
        mgr, auditor, procedure, first = self._setup_auditor_with_first_audit(api, "B")
        assert first["status"] == "SCHEDULED"

        audit = validate_success(api.create_procedure_audit(
            create_procedure_audit_payload(
                procedure["id"], scheduled_start="2026-09-01T12:00:01Z",
                scheduled_end="2026-09-01T15:00:00Z"),
            make_ehs_auditor_headers(auditor["id"])), expected_status=201)
        assert audit["status"] == "SCHEDULED", \
            "one second after the closed window's end is disjoint"


class TestAuditSampleMinimum:
    def test_sample_minimum_enforced_then_completion_succeeds(self, api):
        """PRD §3.7: "`employees_sampled` must be a subset of that population,
        and its size must meet the minimum: zero when the population is empty,
        and otherwise the larger of one and one quarter of the population rounded
        up to a whole person. A sample that violates the subset rule or falls
        below the minimum is rejected with `ERR_SAMPLE_TOO_SMALL` (HTTP 422)."
        PRD §3.7: "Completion stamps `completed_at`, records the `result`, moves
        the audit to its terminal `COMPLETED` state, sets the procedure's
        `last_completed_audit_at` to the clock, and recomputes `audit_due_at` as
        365 days after it."
        PRD §2.4: "Before the clock has been explicitly set, it reads exactly
        2026-08-01T00:00:00Z; the server must never fall back to wall-clock time."

        Design: Corner/calculations/audit_sample_minimum_enforced
        """
        mgr = bootstrap_manager("E-MGR-AS", "Mgr AS")
        w1 = register_qualified_employee(mgr, "E-W1-AS", "W1 AS")
        auditor = register_qualified_employee(mgr, "E-W2-AS", "W2 AS")
        w3 = register_qualified_employee(mgr, "E-W3-AS", "W3 AS")
        machine, survey, procedure = setup_machine_with_active_procedure(
            mgr, w1, asset_tag="A-AS-1")

        # First applier: W1 runs a full session cycle under the procedure.
        s1 = create_session(w1, machine["id"], procedure["id"], "INDIVIDUAL")
        l1 = issue_lock(w1, s1["id"], "L-AS-1", "T-AS-1")
        apply_lock(w1, l1["id"])
        lock_session(w1, s1["id"])
        run_session_to_released(w1, s1["id"], l1["id"])

        # Second applier: W3 applies a lock under the same procedure.
        s2 = create_session(w3, machine["id"], procedure["id"], "INDIVIDUAL")
        l2 = issue_lock(w3, s2["id"], "L-AS-2", "T-AS-2")
        apply_lock(w3, l2["id"])

        audit = schedule_audit(auditor, procedure["id"])
        auditor_headers = make_ehs_auditor_headers(auditor["id"])

        resp = api.complete_procedure_audit(
            audit["id"], {"result": "PASS", "employees_sampled": []},
            auditor_headers)
        validate_error(resp, ApiErrorId.ERR_SAMPLE_TOO_SMALL)

        completed = validate_success(api.complete_procedure_audit(
            audit["id"], {"result": "PASS", "employees_sampled": [w1["id"]]},
            auditor_headers))
        assert completed["status"] == "COMPLETED"
        assert completed["result"] == "PASS"

        procedure_after = get_procedure(mgr, procedure["id"])
        assert_instant_equal(procedure_after["last_completed_audit_at"],
                             "2026-08-01T00:00:00Z")
        assert_instant_equal(procedure_after["audit_due_at"], "2027-08-01T00:00:00Z")


class TestAuditDueInstantBoundary:
    def _setup_procedure_activated_2026_01_01(self, api, suffix):
        """Procedure activated at 2026-01-01T00:00:00Z, so audit_due_at is
        2027-01-01T00:00:00Z; primary's IN_PERSON training (completed at the
        default clock 2026-08-01) stays valid until 2027-08-01."""
        mgr = bootstrap_manager(f"E-MGR-AD{suffix}", "Mgr AD")
        primary = register_qualified_employee(mgr, f"E-W1-AD{suffix}", "W1 AD")
        machine = create_machine(mgr, asset_tag=f"A-AD{suffix}-100",
                                 name="Press AD", area="Line 10")
        survey = create_approved_survey(mgr, primary, machine["id"])
        procedure = create_draft_procedure(mgr, machine["id"], survey["id"])
        set_logical_clock(mgr, "2026-01-01T00:00:00Z")
        procedure = validate_success(api.activate_lockout_procedure(
            procedure["id"], {}, make_ehs_manager_headers(mgr["id"])))
        return mgr, primary, machine, procedure

    def test_session_create_at_audit_due_instant_passes(self, api):
        """PRD §3.5: "the procedure's audit must not be overdue, with the clock
        exactly equal to `audit_due_at` still passing (`ERR_AUDIT_OVERDUE`)"
        PRD §2.6: "Wherever this document defines an expiry or overdue predicate,
        the comparison is strictly greater-than against the clock: a training
        record has expired only when the clock has moved past its `expires_at`,
        an audit is overdue only when the clock is strictly later than the
        procedure's `audit_due_at`, and contractor insurance is expired when
        `insurance_valid_until` is not strictly later than the clock."

        Design: Difficulty/boundary_precision_check/audit_due_instant_boundary
        """
        mgr, primary, machine, procedure = \
            self._setup_procedure_activated_2026_01_01(api, "A")
        assert_instant_equal(procedure["audit_due_at"], "2027-01-01T00:00:00Z")

        set_logical_clock(mgr, "2027-01-01T00:00:00Z")
        session = validate_success(api.create_lockout_session(
            create_lockout_session_payload(machine["id"], procedure["id"],
                                           session_type="INDIVIDUAL"),
            make_authorized_employee_headers(primary["id"])), expected_status=201)
        assert session["status"] == "SETUP", \
            "the boundary instant itself still passes the overdue predicate"

    def test_session_create_one_second_past_audit_due_rejected(self, api):
        """PRD §2.6: "Wherever this document defines an expiry or overdue
        predicate, the comparison is strictly greater-than against the clock: a
        training record has expired only when the clock has moved past its
        `expires_at`, an audit is overdue only when the clock is strictly later
        than the procedure's `audit_due_at`, and contractor insurance is expired
        when `insurance_valid_until` is not strictly later than the clock."
        PRD §2.6: "A request landing exactly on a boundary instant therefore
        still passes — a session planned at the exact `audit_due_at` moment is
        not overdue, and insurance expiring exactly now is already expired."

        Design: Difficulty/boundary_precision_check/audit_due_instant_boundary
        """
        mgr, primary, machine, procedure = \
            self._setup_procedure_activated_2026_01_01(api, "B")
        assert_instant_equal(procedure["audit_due_at"], "2027-01-01T00:00:00Z")

        set_logical_clock(mgr, "2027-01-01T00:00:01Z")
        resp = api.create_lockout_session(
            create_lockout_session_payload(machine["id"], procedure["id"],
                                           session_type="INDIVIDUAL"),
            make_authorized_employee_headers(primary["id"]))
        validate_error(resp, ApiErrorId.ERR_AUDIT_OVERDUE)
