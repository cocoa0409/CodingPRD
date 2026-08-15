"""Enforcement sweep, lapse cascade, due/overdue boundary, cure cascade, and
the void-driven plan-reopen cascade."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT,
    complete_enrollment,
    create_approved_content,
    create_assignment,
    create_enrollment,
    create_rep,
    get_certification_for,
    get_pending_attestation,
    get_success_data,
    make_rep_headers,
    set_clock,
    setup_certified_rep,
    setup_closed_plan_with_attestation,
    setup_lapsed_rep,
    setup_lapsed_rep_with_certified_product,
    start_enrollment,
    validate_error,
    validate_success,
    void_enrollment,
    TEST_USERS,
)

OFFICER = TEST_USERS["officer_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestLapseCascade:
    """Sweep-driven assignment LAPSED -> rep INACTIVE_CE -> cert SUSPENDED."""

    def test_sweep_reports_lapse(self, api):
        """PRD §3.9: "The sweep's response reports, in order, how many records
        each phase moved: `sessions_marked_delivered`, `enrollments_expired`,
        `assignments_marked_overdue`, `assignments_lapsed`, and
        `licenses_lapsed`."
        PRD §3.5: "An assignment in `ASSIGNED` or `OVERDUE` once the clock is
        strictly later than `lapse_after` moves to `LAPSED`."

        Design: Difficulty/transitive_cascade/lapse_cascade_assignment_to_certification
        """
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(crd_number="CRD-LC0")
        assignment = create_assignment(rep["id"], cycle_year=2026)
        set_clock("2026-12-30T00:00:00Z")
        summary = get_success_data(api.run_enforcement_sweep(OFFICER))
        assert summary["assignments_lapsed"] == 1, (
            f"exactly one assignment must lapse, got {summary['assignments_lapsed']}")
        data = validate_success(
            api.get_regulatory_assignment(assignment["id"], OFFICER))
        assert data["assignment_status"] == "LAPSED"

    def test_lapse_flips_registration_and_suspends_cert(self, api):
        """PRD §3.5: "the representative's `registration_status` flips from
        `ACTIVE` to `INACTIVE_CE` (recorded as `REGISTRATION_STATUS_CHANGED`),
        that registration flip in turn moves every one of the rep's product
        certifications in `CERTIFIED` to `SUSPENDED` with `suspended_reason`
        set to `REGISTRATION_INACTIVE` (each recorded as
        `CERTIFICATION_STATUS_CHANGED`), and an `ASSIGNMENT_LAPSED` event is
        written."

        Design: Difficulty/transitive_cascade/lapse_cascade_assignment_to_certification
        """
        rep, _content, product, _cert, assignment = (
            setup_lapsed_rep_with_certified_product())

        rep_data = validate_success(api.get_representative(rep["id"], OFFICER))
        assert rep_data["registration_status"] == "INACTIVE_CE", (
            f"lapse cascade must flip the rep to INACTIVE_CE, "
            f"got {rep_data['registration_status']}")

        cert = get_certification_for(rep["id"], product["id"])
        assert cert["cert_status"] == "SUSPENDED", (
            f"CERTIFIED cert must be suspended by the registration flip, "
            f"got {cert['cert_status']}")
        assert cert["suspended_reason"] == "REGISTRATION_INACTIVE", (
            f"suspended_reason must be REGISTRATION_INACTIVE, "
            f"got {cert.get('suspended_reason')!r}")


class TestDueBoundary:
    """Completing exactly at due_at is on time (inclusive boundary)."""

    def _setup_at_due_instant(self, api):
        """Assignment created at T0 = 2026-08-01 (due 2026-11-29T00:00:00Z).
        Enrollment created at T0+60d (2026-09-30), started; clock set to
        exactly 2026-11-29T00:00:00Z."""
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(crd_number="CRD-BD2")
        content = create_approved_content(
            code="RE-BD", ce_category="REGULATORY_ELEMENT", credit_hours=1.0)
        assignment = create_assignment(rep["id"], cycle_year=2026)
        # 120 days after 2026-08-01T00:00:00Z = 2026-11-29T00:00:00Z.
        set_clock("2026-09-30T00:00:00Z")
        enr = create_enrollment(rep["id"], content_id=content["id"])
        start_enrollment(enr["id"], rep["id"])
        set_clock("2026-11-29T00:00:00Z")
        return rep, content, assignment, enr

    def test_completion_at_due_at_completes_assignment(self, api):
        """PRD §3.5: "Completion at or before `due_at` counts as on time — the
        boundary is inclusive, so finishing exactly at `due_at` is on time."
        PRD §3.5: "The selected assignment moves to `COMPLETED` with
        `enrollment_id` and `completed_at` set, and an `ASSIGNMENT_COMPLETED`
        event is written."

        Design: Difficulty/boundary_precision_check/assignment_due_boundary_inclusive_completion
        """
        rep, _content, assignment, enr = self._setup_at_due_instant(api)
        data = validate_success(api.complete_enrollment(
            enr["id"], {"score": 85}, make_rep_headers(rep["id"])))
        assert data["enrollment_status"] == "COMPLETED"

        asg = validate_success(
            api.get_regulatory_assignment(assignment["id"], OFFICER))
        assert asg["assignment_status"] == "COMPLETED", (
            f"completion exactly at due_at must fulfill the assignment, "
            f"got {asg['assignment_status']}")
        # PRD pins the instant (completed_at stamped from the logical clock,
        # §3.4), not the fractional-digit rendering — compare parsed instants.
        completed_at = datetime.fromisoformat(
            asg["completed_at"].replace("Z", "+00:00"))
        assert completed_at == datetime(2026, 11, 29, tzinfo=timezone.utc), (
            f"completed_at must equal the due instant, got {asg['completed_at']}")

    def test_rep_stays_active_after_on_time_completion(self, api):
        """PRD §3.5: "Completion at or before `due_at` counts as on time — the
        boundary is inclusive, so finishing exactly at `due_at` is on time."
        PRD §3.1: "Every new representative begins with `registration_status`
        set to `ACTIVE`."

        Design: Difficulty/boundary_precision_check/assignment_due_boundary_inclusive_completion
        """
        rep, _content, assignment, enr = self._setup_at_due_instant(api)
        validate_success(api.complete_enrollment(
            enr["id"], {"score": 85}, make_rep_headers(rep["id"])))
        rep_data = validate_success(api.get_representative(rep["id"], OFFICER))
        assert rep_data["registration_status"] == "ACTIVE", (
            f"on-time completion leaves the rep ACTIVE, "
            f"got {rep_data['registration_status']}")


class TestOverdueBoundary:
    """One second AFTER due_at: sweep marks OVERDUE (not LAPSED); rep ACTIVE."""

    def test_sweep_marks_overdue_after_due(self, api):
        """PRD §3.5: "An `ASSIGNED` assignment whose `due_at` is earlier than
        the logical clock, while the clock has not yet passed `lapse_after`,
        moves to `OVERDUE`."
        PRD §3.9: "The sweep's response reports, in order, how many records
        each phase moved: `sessions_marked_delivered`, `enrollments_expired`,
        `assignments_marked_overdue`, `assignments_lapsed`, and
        `licenses_lapsed`."

        Design: Corner/state_machines/c_sweep_marks_overdue_one_second_after_due
        """
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(crd_number="CRD-C13")
        assignment = create_assignment(rep["id"], cycle_year=2026)
        # One second past due_at (2026-11-29T00:00:00Z), well within grace.
        set_clock("2026-11-29T00:00:01Z")
        summary = get_success_data(api.run_enforcement_sweep(OFFICER))
        assert summary["assignments_marked_overdue"] == 1, (
            f"exactly one assignment must move to OVERDUE, "
            f"got {summary['assignments_marked_overdue']}")
        assert summary["assignments_lapsed"] == 0, (
            f"no assignment may lapse inside the grace window, "
            f"got {summary['assignments_lapsed']}")

    def test_overdue_rep_stays_active(self, api):
        """PRD §3.5: "An assignment in `ASSIGNED` or `OVERDUE` once the clock
        is strictly later than `lapse_after` moves to `LAPSED`, and lapsing is
        the most consequential automated transition in the system: the
        representative's `registration_status` flips from `ACTIVE` to
        `INACTIVE_CE`."

        Design: Corner/state_machines/c_sweep_marks_overdue_one_second_after_due
        """
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(crd_number="CRD-C13b")
        assignment = create_assignment(rep["id"], cycle_year=2026)
        set_clock("2026-11-29T00:00:01Z")
        get_success_data(api.run_enforcement_sweep(OFFICER))

        asg = validate_success(
            api.get_regulatory_assignment(assignment["id"], OFFICER))
        assert asg["assignment_status"] == "OVERDUE"
        rep_data = validate_success(api.get_representative(rep["id"], OFFICER))
        assert rep_data["registration_status"] == "ACTIVE", (
            f"OVERDUE does not flip registration; got "
            f"{rep_data['registration_status']}")


class TestSweepIdempotence:
    def test_second_sweep_is_noop(self, api):
        """PRD §3.9: "Remember that the sweep is the only clock-driven actor in
        the system: setting the logical clock to a future instant changes no
        record until a sweep is run."
        PRD §3.9: "The sweep's response reports, in order, how many records
        each phase moved: `sessions_marked_delivered`, `enrollments_expired`,
        `assignments_marked_overdue`, `assignments_lapsed`, and
        `licenses_lapsed`."

        Design: Corner/cross_cutting_layers/c_sweep_second_run_noop
        """
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(crd_number="CRD-C38")
        create_assignment(rep["id"], cycle_year=2026)
        get_success_data(api.run_enforcement_sweep(OFFICER))
        summary = get_success_data(api.run_enforcement_sweep(OFFICER))
        assert summary["sessions_marked_delivered"] == 0
        assert summary["enrollments_expired"] == 0
        assert summary["assignments_marked_overdue"] == 0
        assert summary["assignments_lapsed"] == 0
        assert summary["licenses_lapsed"] == 0, (
            f"second sweep with nothing past deadline must be all zeros, "
            f"got {summary}")


class TestVoidCascadeToAttestation:
    """Void COMPLETED enrollment -> CLOSED plan reopens -> ATTESTED attestation
    VOIDED."""

    def test_void_reopens_closed_plan(self, api, admin_headers):
        """PRD §3.4: "For `FIRM_ELEMENT` content, the matching plan's hours are
        recomputed; if that plan was `CLOSED` and the recomputed
        `certified_hours` now fall below its `required_hours`, the plan reopens
        — `CLOSED` back to `PLAN_PUBLISHED`, with `closed_at` cleared — and its
        annual attestation, if `ATTESTED`, is `VOIDED`; `PLAN_REOPENED` and
        `ATTESTATION_VOIDED` events are written."

        Design: Difficulty/transitive_cascade/void_cascade_enrollment_to_attestation
        """
        rep, plan, attestation, enrollment, _content = (
            setup_closed_plan_with_attestation(content_hours=13.0))
        void_enrollment(
            enrollment["id"], justification="score recording error found in audit")

        plan_data = validate_success(
            api.get_firm_element_plan(plan["id"], admin_headers))
        assert plan_data["plan_status"] == "PLAN_PUBLISHED", (
            f"recomputed certified 0 < required 12 must reopen the plan, "
            f"got {plan_data['plan_status']}")
        assert plan_data["certified_hours"] == pytest.approx(0, abs=0.01), (
            f"the voided 13.0h must leave certified_hours at 0, "
            f"got {plan_data['certified_hours']}")
        assert plan_data.get("closed_at") in (None, ""), (
            "reopened plan must have closed_at cleared")

    def test_void_voids_attested_attestation(self, api, officer_headers):
        """PRD §3.4: "if that plan was `CLOSED` and the recomputed
        `certified_hours` now fall below its `required_hours`, the plan reopens
        — `CLOSED` back to `PLAN_PUBLISHED`, with `closed_at` cleared — and its
        annual attestation, if `ATTESTED`, is `VOIDED`; `PLAN_REOPENED` and
        `ATTESTATION_VOIDED` events are written."
        PRD §3.6: "The reopen loop keeps closed plans honest."

        Design: Difficulty/transitive_cascade/void_cascade_enrollment_to_attestation
        """
        rep, plan, attestation, enrollment, _content = (
            setup_closed_plan_with_attestation(content_hours=13.0))
        void_enrollment(
            enrollment["id"], justification="score recording error found in audit")

        enr_data = validate_success(
            api.get_enrollment(enrollment["id"], officer_headers))
        assert enr_data["enrollment_status"] == "VOIDED"
        att_data = validate_success(
            api.get_attestation(attestation["id"], officer_headers))
        assert att_data["attestation_status"] == "VOIDED", (
            f"plan reopen must void the ATTESTED attestation, "
            f"got {att_data['attestation_status']}")


class TestReinstatementGuard:
    def test_reinstate_blocked_while_rep_inactive(self, api):
        """PRD §3.7: "A `ComplianceOfficer` may reinstate a certification that
        is `SUSPENDED` — otherwise `ERR_CERTIFICATION_NOT_SUSPENDED` — and only
        when all three gates hold: the representative's `registration_status`
        is `ACTIVE`, the product is `LAUNCHED`, and the certification's
        `enrollment_id` is set and names an enrollment that is `COMPLETED`
        whose content is still `APPROVED`. Failing any of those gates rejects
        the request with `ERR_REINSTATEMENT_BLOCKED`."

        Design: Corner/state_machines/c_reinstate_blocked_while_rep_inactive_returns_409
        """
        rep, _content, product, _cert, _asg = (
            setup_lapsed_rep_with_certified_product())
        cert = get_certification_for(rep["id"], product["id"])
        assert cert["cert_status"] == "SUSPENDED"

        resp = api.reinstate_certification(cert["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_REINSTATEMENT_BLOCKED)
