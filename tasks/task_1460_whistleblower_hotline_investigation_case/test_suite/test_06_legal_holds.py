"""Legal holds: overlap geometry, terminal-case gate, freeze gates, release SoD, posture."""
from test_helpers import (
    ApiErrorId,
    create_case,
    create_legal_hold_payload,
    create_staff,
    get_case,
    make_intake_headers,
    make_officer_headers,
    setup_case_determination_review,
    setup_case_triaged,
    setup_case_under_investigation,
    setup_case_with_active_hold,
    setup_standard_staff,
    triage_case,
    validate_error,
    validate_success,
    api_client,
)


class TestHoldIntervalGeometry:
    """Difficulty: legal_hold_closed_interval_touch (2 tests)."""

    def test_touching_closed_intervals_rejected(self, api):
        """PRD §3.8: "a new hold's closed interval may not touch or overlap the
        closed interval of any `ACTIVE` hold — a violation fails with
        `ERR_LEGAL_HOLD_OVERLAP`" (closed interval, "both ends inclusive").

        Design: Difficulty/resource_temporal_overlap/legal_hold_closed_interval_touch
        """
        s_off = create_staff("Olivia Officer", "officer@corp.example", ["OFFICER"])
        case, _ = create_case()
        api.create_legal_hold(create_legal_hold_payload(
            case["id"], start_at="2026-08-10T00:00:00Z", end_at="2026-08-20T00:00:00Z",
        ), make_officer_headers(s_off["id"]))
        resp = api.create_legal_hold(create_legal_hold_payload(
            case["id"], start_at="2026-08-20T00:00:00Z", end_at="2026-08-25T00:00:00Z",
            reason="Touching second hold",
        ), make_officer_headers(s_off["id"]))
        validate_error(resp, ApiErrorId.ERR_LEGAL_HOLD_OVERLAP)

    def test_one_second_after_end_accepted(self, api):
        """PRD §3.8: "a new hold's closed interval may not touch or overlap the
        closed interval of any `ACTIVE` hold" — starting one second after the
        inclusive end is disjoint and therefore legal.

        Design: Difficulty/resource_temporal_overlap/legal_hold_closed_interval_touch
        """
        s_off = create_staff("Olivia Officer", "officer@corp.example", ["OFFICER"])
        case, _ = create_case()
        api.create_legal_hold(create_legal_hold_payload(
            case["id"], start_at="2026-08-10T00:00:00Z", end_at="2026-08-20T00:00:00Z",
        ), make_officer_headers(s_off["id"]))
        resp = api.create_legal_hold(create_legal_hold_payload(
            case["id"], start_at="2026-08-20T00:00:01Z", end_at="2026-08-25T00:00:00Z",
            reason="Adjacent second hold",
        ), make_officer_headers(s_off["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"


class TestHoldValidation:
    def test_end_before_start_returns_invalid_interval(self, api):
        """PRD §3.8: "both ends inclusive, with `end_at` no earlier than `start_at`
        or the request fails with `ERR_INVALID_INTERVAL`".

        Design: Corner/validations/invalid_interval_hold_end_before_start
        """
        s_off = create_staff("Olivia Officer", "officer@corp.example", ["OFFICER"])
        case, _ = create_case()
        resp = api.create_legal_hold(create_legal_hold_payload(
            case["id"], start_at="2026-08-20T00:00:00Z", end_at="2026-08-10T00:00:00Z",
            reason="Backwards window hold",
        ), make_officer_headers(s_off["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL)

    def test_hold_on_terminal_case_rejected(self, api):
        """PRD §3.8: "placing a hold on a `CLOSED`, `REJECTED`, or `WITHDRAWN` case
        fails with `ERR_CASE_TERMINAL`".

        Design: Corner/errors/hold_on_terminal_case_rejected
        """
        staff = setup_standard_staff()
        case, _ = create_case(category="OTHER", description="Out of scope complaint about payroll",
                              region="WEST")
        triage_case(case["id"], staff["h_int"], confirmed_category="OTHER",
                    subject_seniority="UNKNOWN", triage_decision="REJECT",
                    reject_reason="Out of scope")
        resp = api.create_legal_hold(create_legal_hold_payload(
            case["id"], reason="Late litigation hold attempt",
        ), staff["h_off"])
        validate_error(resp, ApiErrorId.ERR_CASE_TERMINAL)


class TestHoldRelease:
    def test_release_by_placer_rejected(self, api):
        """PRD §3.8: "a `ComplianceOfficer` other than the placer
        (`ERR_SOD_HOLD_RELEASE`) releases an `ACTIVE` hold".

        Design: Corner/errors/sod_hold_release_by_placer
        """
        ctx = setup_case_with_active_hold()
        staff = ctx["staff"]
        resp = api.release_legal_hold(ctx["hold"]["id"], staff["h_off"])
        validate_error(resp, ApiErrorId.ERR_SOD_HOLD_RELEASE)

    def test_release_twice_rejected(self, api):
        """PRD §3.8: "releasing from any other state fails with
        `ERR_HOLD_NOT_ACTIVE`".

        Design: Corner/errors/hold_release_twice_rejected
        """
        ctx = setup_case_with_active_hold()
        staff = ctx["staff"]
        api.release_legal_hold(ctx["hold"]["id"], staff["h_off2"])
        resp = api.release_legal_hold(ctx["hold"]["id"], staff["h_off2"])
        validate_error(resp, ApiErrorId.ERR_HOLD_NOT_ACTIVE)


class TestPostureReconciliation:
    def test_posture_frozen_on_place(self, api):
        """PRD §2.7: "Every case has a derived `posture`, which is `FROZEN` whenever
        at least one `LegalHold` referencing the case has `status` equal to
        `ACTIVE`".

        Design: Corner/cross_cutting_layers/posture_recomputed_on_hold_place_and_release
        """
        ctx = setup_case_with_active_hold()
        assert ctx["case"]["posture"] == "FROZEN"

    def test_posture_normal_after_release(self, api):
        """PRD §3.8: "recomputes the case posture — which returns to `NORMAL` if no
        other `ACTIVE` hold remains".

        Design: Corner/cross_cutting_layers/posture_recomputed_on_hold_place_and_release
        """
        ctx = setup_case_with_active_hold()
        staff = ctx["staff"]
        api.release_legal_hold(ctx["hold"]["id"], staff["h_off2"])
        case = get_case(ctx["case"]["id"], staff["h_off"])
        assert case["posture"] == "NORMAL"


class TestFreezeGates:
    def test_closure_ready_entry_blocked_while_frozen(self, api):
        """PRD §2.7: "A `FROZEN` posture gates ... a case's entry into
        `CLOSURE_READY` — whether that entry is attempted through determination
        approval".

        Design: Difficulty/cross_entity_state_dependency/closure_entry_gated_by_active_legal_hold
        """
        ctx = setup_case_determination_review()
        staff = ctx["staff"]
        api.create_legal_hold(create_legal_hold_payload(
            ctx["case"]["id"], start_at="2026-08-06T00:00:00Z", end_at="2026-08-12T00:00:00Z",
        ), staff["h_off"])
        resp = api.review_determination(ctx["determination"]["id"], {
            "decision": "APPROVE", "review_notes": "Reviewed and accepted.",
            "notice_summary": "Case closed with no findings disclosed.",
        }, staff["h_off2"])
        validate_error(resp, ApiErrorId.ERR_LEGAL_HOLD_FREEZE)
        # failed review leaves determination SUBMITTED
        det = api.get_determination(ctx["determination"]["id"], staff["h_off"]).json()["data"]
        assert det["status"] == "SUBMITTED"

    def test_closure_entry_proceeds_after_release(self, api):
        """PRD §3.8: "If the case had been sitting in `REMEDIATION` with its
        close-out deferred by the freeze, the close-out rule of §3.6 is re-evaluated
        at this point" and §3.6: approve(UNSUBSTANTIATED) "moves the case directly
        to `CLOSURE_READY` ... but only while the case posture is `NORMAL`".

        Design: Difficulty/cross_entity_state_dependency/closure_entry_gated_by_active_legal_hold
        """
        ctx = setup_case_determination_review()
        staff = ctx["staff"]
        hold = validate_success(api.create_legal_hold(create_legal_hold_payload(
            ctx["case"]["id"], start_at="2026-08-06T00:00:00Z", end_at="2026-08-12T00:00:00Z",
        ), staff["h_off"]), expected_status=201)
        api.release_legal_hold(hold["id"], staff["h_off2"])
        resp = api.review_determination(ctx["determination"]["id"], {
            "decision": "APPROVE", "review_notes": "Reviewed and accepted.",
            "notice_summary": "Case closed with no findings disclosed.",
        }, staff["h_off2"])
        det = validate_success(resp)
        assert det["status"] == "APPROVED"
        case = get_case(ctx["case"]["id"], staff["h_off"])
        assert case["status"] == "CLOSURE_READY"
        notices = api.list_closure_notices(ctx["case"]["id"], staff["h_off"]).json()["data"]
        assert len(notices) == 1
        assert notices[0]["status"] == "SENT"


class TestFreezeVsSodPriority:
    """Difficulty: assignment_freeze_vs_sod_priority (2 tests)."""

    def _setup_frozen_triaged_by_dual(self, api):
        s_intd = create_staff("Dana Dual", "dual@corp.example", ["INTAKE", "INVESTIGATION"])
        s_off = create_staff("Olivia Officer", "officer@corp.example", ["OFFICER"])
        case, _ = create_case()
        triage_case(case["id"], make_intake_headers(s_intd["id"]))
        api.create_legal_hold(create_legal_hold_payload(
            case["id"], start_at="2026-08-10T00:00:00Z", end_at="2026-08-20T00:00:00Z",
            reason="Litigation review hold",
        ), make_officer_headers(s_off["id"]))
        frozen = get_case(case["id"], make_officer_headers(s_off["id"]))
        return s_intd, s_off, case, frozen

    def test_freeze_error_wins_over_triager_sod(self, api):
        """PRD §2.11: "Ninth, the legal-hold freeze gate (`ERR_LEGAL_HOLD_FREEZE`).
        Tenth, segregation-of-duties rules (the `ERR_SOD_*` family)."

        Design: Difficulty/priority_pair_validation_conflict/assignment_freeze_vs_sod_priority
        """
        s_intd, s_off, case, frozen = self._setup_frozen_triaged_by_dual(api)
        assert frozen["posture"] == "FROZEN"
        # override naming the triager — violates BOTH freeze (p9) and triager SoD (p10)
        resp = api.create_assignment(case["id"], {
            "expected_case_version": frozen["version"], "investigator_id": s_intd["id"],
            "override_reason": "Only qualified investigator",
        }, make_officer_headers(s_off["id"]))
        validate_error(resp, ApiErrorId.ERR_LEGAL_HOLD_FREEZE)

    def test_failed_dual_violation_creates_no_assignment(self, api):
        """PRD §2.4: "every mutation in this system is applied atomically within the
        request that triggered it" — a rejected proposal creates nothing.

        Design: Difficulty/priority_pair_validation_conflict/assignment_freeze_vs_sod_priority
        """
        s_intd, s_off, case, frozen = self._setup_frozen_triaged_by_dual(api)
        api.create_assignment(case["id"], {
            "expected_case_version": frozen["version"], "investigator_id": s_intd["id"],
            "override_reason": "Only qualified investigator",
        }, make_officer_headers(s_off["id"]))
        rows = api.list_assignments(case["id"], make_officer_headers(s_off["id"])).json()["data"]
        assert rows == []
