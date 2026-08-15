"""Compliance audits: window overlap, outcome computation, new-entrant
pass/fail, corrective-action gating, posture derivation, and the rating
cascade on close."""
from test_helpers import (
    ApiErrorId,
    audit_to_findings,
    close_audit,
    create_audit_case_payload,
    get_carrier,
    get_premium_model,
    make_audit_case,
    make_carrier,
    setup_audit_close_cascade_case,
    setup_posture_first_match_case,
    validate_error,
    validate_success,
)


class TestAuditWindowOverlap:
    def test_audit_window_overlap_inside_window_rejected(self, api, admin_headers):
        """PRD §3.8: "The window is half-open: it covers `scheduled_date`
        inclusive up to but excluding `scheduled_date` plus the duration, and it
        may not intersect the window of any other non-closed audit case for the
        same carrier (`ERR_AUDIT_WINDOW_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/audit_window_half_open_adjacency
        """
        carrier = make_carrier(dot_number="DOT-1015")
        make_audit_case(
            carrier["id"], audit_type="COMPLIANCE_REVIEW",
            scheduled_date="2026-09-01T00:00:00Z", field_work_duration_days=14,
        )
        # Window B [09-14, 09-21) intersects A's [09-01, 09-15).
        resp = api.create_audit_case(
            create_audit_case_payload(
                carrier["id"], audit_type="COMPLIANCE_REVIEW",
                scheduled_date="2026-09-14T00:00:00Z", field_work_duration_days=7,
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_OVERLAP)

    def test_audit_window_adjacent_at_exclusive_end_allowed(self, api, admin_headers):
        """PRD §3.8: "The window is half-open: it covers `scheduled_date`
        inclusive up to but excluding `scheduled_date` plus the duration, and it
        may not intersect the window of any other non-closed audit case for the
        same carrier (`ERR_AUDIT_WINDOW_OVERLAP`)." — a window starting exactly
        at the first window's exclusive end is adjacent, not intersecting.

        Design: Difficulty/resource_temporal_overlap/audit_window_half_open_adjacency
        """
        carrier = make_carrier(dot_number="DOT-1015")
        make_audit_case(
            carrier["id"], audit_type="COMPLIANCE_REVIEW",
            scheduled_date="2026-09-01T00:00:00Z", field_work_duration_days=14,
        )
        # Window C starts at 09-15 == A's exclusive end.
        resp = api.create_audit_case(
            create_audit_case_payload(
                carrier["id"], audit_type="COMPLIANCE_REVIEW",
                scheduled_date="2026-09-15T00:00:00Z", field_work_duration_days=7,
            ),
            admin_headers,
        )
        assert validate_success(resp, 201)["status"] == "SCHEDULED"


class TestAuditOutcomeComputation:
    def test_audit_outcome_boundary_matrix(self, api, admin_headers):
        """PRD §3.8: "For a `COMPLIANCE_REVIEW` the outcome is `UNSATISFACTORY`
        when at least two acute or at least four critical violations were found;
        otherwise `SATISFACTORY` when no acute and at most one critical
        violation were found; otherwise `CONDITIONAL`."

        Design: Corner/calculations/audit_outcome_boundary_matrix
        """
        expected = {
            (0, 1): "SATISFACTORY",
            (0, 2): "CONDITIONAL",
            (1, 0): "CONDITIONAL",
            (0, 4): "UNSATISFACTORY",
        }
        for index, ((acute, critical), outcome) in enumerate(expected.items()):
            carrier = make_carrier(dot_number=f"DOT-2205{chr(65 + index)}")
            case = audit_to_findings(carrier["id"], acute, critical)
            assert case["proposed_outcome"] == outcome, (
                f"({acute} acute, {critical} critical) must propose {outcome}, "
                f"got {case['proposed_outcome']}"
            )

    def test_corrective_action_on_pass_rejected(self, api, manager_headers):
        """PRD §3.8: "When the proposed outcome is adverse — `FAIL`,
        `CONDITIONAL`, or `UNSATISFACTORY` — a `SafetyManager` may move the case
        `FINDINGS_ISSUED` → `CORRECTIVE_ACTION_PHASE`; when it is `PASS` or
        `SATISFACTORY` there is nothing to correct and the request is rejected
        with `ERR_CORRECTIVE_ACTION_NOT_APPLICABLE`."

        Design: Corner/validations/corrective_action_on_pass_rejected
        """
        carrier = make_carrier(dot_number="DOT-2337", fleet_size=1)
        case = audit_to_findings(carrier["id"], 0, 1)
        assert case["proposed_outcome"] == "SATISFACTORY"

        resp = api.begin_corrective_action(case["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_CORRECTIVE_ACTION_NOT_APPLICABLE)

    def test_audit_actions_from_wrong_state_rejected(
        self, api, admin_headers, director_headers
    ):
        """PRD §3.8: "Findings are issued by a `SafetyAdmin` from `FIELD_WORK`
        (`ERR_AUDIT_INVALID_STATE` otherwise)" and "Closing the audit belongs to
        the `SafetyDirector` and is permitted from either `FINDINGS_ISSUED` or
        `CORRECTIVE_ACTION_PHASE` — from anywhere else, including the terminal
        states, it is rejected with `ERR_AUDIT_INVALID_STATE`."

        Design: Corner/validations/audit_actions_from_wrong_state_rejected
        """
        carrier = make_carrier(dot_number="DOT-2328")
        case = make_audit_case(
            carrier["id"], audit_type="COMPLIANCE_REVIEW",
            scheduled_date="2026-09-01T00:00:00Z", field_work_duration_days=7,
        )
        assert case["status"] == "SCHEDULED"

        findings = api.issue_findings(
            case["id"], {"acute_count": 0, "critical_count": 0}, admin_headers
        )
        validate_error(findings, ApiErrorId.ERR_AUDIT_INVALID_STATE)

        close = api.close_audit_case(case["id"], director_headers)
        validate_error(close, ApiErrorId.ERR_AUDIT_INVALID_STATE)


class TestNewEntrantAudits:
    def test_new_entrant_audit_pass_clears_status(self, api, director_headers):
        """PRD §3.8: "For a `NEW_ENTRANT` audit the outcome is `FAIL` when at
        least one acute violation or at least three critical violations were
        found, and `PASS` otherwise."
        PRD §3.8: "A new-entrant `PASS` moves the carrier's `new_entrant_status`
        from `PENDING_AUDIT` to `PASSED`, recomputes its posture, and increments
        its `version`."
        PRD §3.1: "its `new_entrant_status` is `PENDING_AUDIT` when registered
        as a new entrant and `NOT_NEW_ENTRANT` otherwise."

        Design: Corner/state_machines/new_entrant_audit_pass_clears_status
        """
        carrier = make_carrier(
            dot_number="DOT-2109", is_new_entrant=True,
            safety_audit_due_date="2026-12-01T00:00:00Z",
        )
        assert carrier["new_entrant_status"] == "PENDING_AUDIT"

        case = audit_to_findings(
            carrier["id"], 0, 2, audit_type="NEW_ENTRANT", field_work_duration_days=7
        )
        assert case["proposed_outcome"] == "PASS"

        closed = close_audit(case["id"])
        assert closed["status"] == "CLOSED_PASSED"
        assert get_carrier(carrier["id"])["new_entrant_status"] == "PASSED"

    def test_new_entrant_audit_fail_proposes_out_of_service(self, api, director_headers):
        """PRD §3.8: "A new-entrant `FAIL` moves it to `FAILED`, forces the
        carrier's `posture` to `OUT_OF_SERVICE_PROPOSED`, sweeps its `QUOTED`
        premium models to `STALE`, and increments `version`."

        Design: Corner/state_machines/new_entrant_audit_fail_proposes_out_of_service
        """
        carrier = make_carrier(
            dot_number="DOT-2110", is_new_entrant=True,
            safety_audit_due_date="2026-12-01T00:00:00Z",
        )
        case = audit_to_findings(
            carrier["id"], 1, 0, audit_type="NEW_ENTRANT", field_work_duration_days=7
        )
        assert case["proposed_outcome"] == "FAIL"

        closed = close_audit(case["id"])
        assert closed["status"] == "CLOSED_FAILED"
        after = get_carrier(carrier["id"])
        assert after["new_entrant_status"] == "FAILED"
        assert after["posture"] == "OUT_OF_SERVICE_PROPOSED"

    def test_new_entrant_audit_scheduled_past_due_rejected(self, api, admin_headers):
        """PRD §3.8: "A `NEW_ENTRANT` audit may be created only for a carrier
        that is a new entrant whose `new_entrant_status` is `PENDING_AUDIT`
        (`ERR_AUDIT_TYPE_NOT_APPLICABLE`), and its `scheduled_date` may not fall
        after the carrier's `safety_audit_due_date`
        (`ERR_AUDIT_SCHEDULED_PAST_DUE`)."

        Design: Corner/validations/new_entrant_audit_scheduled_past_due_rejected
        """
        carrier = make_carrier(
            dot_number="DOT-2332", is_new_entrant=True,
            safety_audit_due_date="2026-12-01T00:00:00Z",
        )
        resp = api.create_audit_case(
            create_audit_case_payload(
                carrier["id"], audit_type="NEW_ENTRANT",
                scheduled_date="2027-01-01T00:00:00Z", field_work_duration_days=7,
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_SCHEDULED_PAST_DUE)

    def test_audit_start_before_scheduled_date_rejected(self, api, admin_headers):
        """PRD §3.8: "Field work begins at a `SafetyAdmin`'s hand, but only once
        three gates pass: the case is `SCHEDULED` (`ERR_AUDIT_INVALID_STATE`),
        the clock has reached `scheduled_date`
        (`ERR_AUDIT_BEFORE_SCHEDULED_DATE`), and the carrier's computed
        audit-readiness summary reports `ready` as true
        (`ERR_AUDIT_READINESS_INCOMPLETE`)."

        Design: Corner/validations/audit_start_before_scheduled_date_rejected
        """
        carrier = make_carrier(dot_number="DOT-2333")
        case = make_audit_case(
            carrier["id"], audit_type="COMPLIANCE_REVIEW",
            scheduled_date="2026-09-01T00:00:00Z", field_work_duration_days=7,
        )
        resp = api.start_field_work(case["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_AUDIT_BEFORE_SCHEDULED_DATE)

    def test_new_entrant_audit_on_regular_carrier_rejected(self, api, admin_headers):
        """PRD §3.8: "A `NEW_ENTRANT` audit may be created only for a carrier
        that is a new entrant whose `new_entrant_status` is `PENDING_AUDIT`
        (`ERR_AUDIT_TYPE_NOT_APPLICABLE`)".

        Design: Corner/validations/new_entrant_audit_on_regular_carrier_rejected
        """
        carrier = make_carrier(dot_number="DOT-2338", legal_name="Regular Carrier")
        resp = api.create_audit_case(
            create_audit_case_payload(
                carrier["id"], audit_type="NEW_ENTRANT",
                scheduled_date="2026-08-01T00:00:00Z", field_work_duration_days=7,
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_TYPE_NOT_APPLICABLE)


class TestPostureFirstMatchWins:
    def test_two_alerted_categories_yield_intervention_priority(self, api):
        """PRD §3.10: "(2) otherwise, if at least two categories carry
        `alerted_official` in the latest cycle, or the
        `CONTROLLED_SUBSTANCES_ALCOHOL` category carries it, the posture is
        `INTERVENTION_PRIORITY`" — with the rating still `NONE`, rule (1) does
        not fire.

        Design: Difficulty/combinatorial_formula/posture_first_match_wins
        """
        env = setup_posture_first_match_case()
        assert env["cycle"]["posture_after"] == "INTERVENTION_PRIORITY", (
            "two alerted categories (HOS and VM) at threshold 65 with "
            "percentile 75 each"
        )
        assert get_carrier(env["carrier"]["id"])["posture"] == "INTERVENTION_PRIORITY"

    def test_unsatisfactory_rating_dominates_alerted_categories(self, api):
        """PRD §3.10: "evaluated as an ordered ladder where the first matching
        rule wins: (1) if `safety_rating` is `UNSATISFACTORY` or
        `new_entrant_status` is `FAILED`, the posture is
        `OUT_OF_SERVICE_PROPOSED`" — rule (1) dominates the two-alerted-category
        rule (2) after the audit close.
        PRD §3.8: "A compliance review writes the `proposed_outcome` into the
        carrier's `safety_rating` — from whatever rating it held before,
        including `NONE` — increments `version`, recomputes posture, sweeps
        `QUOTED` premium models to `STALE`".

        Design: Difficulty/combinatorial_formula/posture_first_match_wins
        """
        env = setup_posture_first_match_case()
        assert env["case"]["proposed_outcome"] == "UNSATISFACTORY"

        closed = close_audit(env["case"]["id"])
        assert closed["status"] == "CLOSED_FAILED"

        carrier = get_carrier(env["carrier"]["id"])
        assert carrier["safety_rating"] == "UNSATISFACTORY"
        assert carrier["posture"] == "OUT_OF_SERVICE_PROPOSED"


class TestAuditCloseCascade:
    def test_audit_close_applies_rating_and_posture(self, api, director_headers):
        """PRD §3.8: "A compliance review writes the `proposed_outcome` into the
        carrier's `safety_rating` — from whatever rating it held before,
        including `NONE` — increments `version`, recomputes posture, sweeps
        `QUOTED` premium models to `STALE`".
        PRD §3.8: "a `FAIL`, `CONDITIONAL`, or `UNSATISFACTORY` outcome closes
        it as `CLOSED_FAILED`."
        PRD §3.10: "(1) if `safety_rating` is `UNSATISFACTORY` or
        `new_entrant_status` is `FAILED`, the posture is
        `OUT_OF_SERVICE_PROPOSED`".

        Design: Difficulty/transitive_cascade/cascade_audit_close_unsatisfactory
        """
        env = setup_audit_close_cascade_case()
        assert env["case"]["proposed_outcome"] == "UNSATISFACTORY"
        assert env["model"]["computed_premium_cents"] == 210000

        closed = close_audit(env["case"]["id"])
        assert closed["status"] == "CLOSED_FAILED"

        carrier = get_carrier(env["carrier"]["id"])
        assert carrier["safety_rating"] == "UNSATISFACTORY"
        assert carrier["posture"] == "OUT_OF_SERVICE_PROPOSED"

    def test_audit_close_sweeps_quoted_premium_stale(self, api, director_headers):
        """PRD §2.8: "An insurance premium model in `QUOTED` status is swept to
        `STALE` — a derived-field reconciliation marker — whenever any of the
        following occurs for its carrier: the carrier profile is updated, the
        carrier's safety rating changes by audit close or upgrade approval, a
        new-entrant audit fails, a measurement cycle runs for the carrier, or
        one of the carrier's drivers changes `risk_tier`."

        Design: Difficulty/transitive_cascade/cascade_audit_close_unsatisfactory
        """
        env = setup_audit_close_cascade_case()
        close_audit(env["case"]["id"])
        model = get_premium_model(env["model"]["id"])
        assert model["status"] == "STALE", (
            "rating changed by audit close, so the QUOTED model is swept"
        )
