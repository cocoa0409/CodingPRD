"""Carrier audits (gap rule, window gate, close gate, escalation cascade) and
loss-ratio evaluations (insufficient data, inclusive thresholds, paid-vs-
incurred divergence, termination-review auto-suspension)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_appointment,
    create_audit_payload,
    create_carrier,
    create_claim_under_review,
    create_issued_policy,
    create_paid_claim,
    create_program,
    create_tpa,
    get_claim_fresh,
    get_policy_fresh,
    get_program_fresh,
    make_carrier_underwriter_headers,
    make_tpa_adjuster_headers,
    quote_policy,
    report_claim,
    set_clock,
    setup_active_program,
    setup_program_with_issued_policy_and_tpa,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["mga_underwriter_headers"]
FIN = TEST_USERS["mga_finance_headers"]
AUD = TEST_USERS["carrier_auditor_headers"]


def _create_audit(api, program, **overrides):
    return validate_success(
        api.create_audit(program["id"], create_audit_payload(**overrides), AUD),
        expected_status=201)


class TestAuditGapAndWindow:
    def test_audit_gap_29_days_rejected_30_days_accepted(self, api):
        """PRD §3.8: "its window must sit at least thirty days clear of every
        non-terminal audit of the same program — one in `SCHEDULED`,
        `IN_PROGRESS`, `FINDINGS_ISSUED`, or `REMEDIATION` — measured in
        either direction between the scheduled windows; a tighter spacing is
        rejected with `ERR_AUDIT_WINDOW_GAP`."

        Design: Difficulty/resource_temporal_overlap/audit_window_gap_boundary
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        _create_audit(api, program, scheduled_start="2026-09-01T00:00:00Z",
                      scheduled_end="2026-09-15T00:00:00Z")

        # 29 days after the incumbent's end -> conflict.
        resp = api.create_audit(program["id"], create_audit_payload(
            scope="CLAIMS", scheduled_start="2026-10-14T00:00:00Z",
            scheduled_end="2026-10-20T00:00:00Z"), AUD)
        validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_GAP)

        # Exactly 30 days after the incumbent's end -> accepted.
        ok = _create_audit(api, program, scope="CLAIMS",
                           scheduled_start="2026-10-15T00:00:00Z",
                           scheduled_end="2026-10-25T00:00:00Z")
        assert ok["status"] == "SCHEDULED"

    def test_terminal_audit_does_not_occupy_the_calendar(self, api):
        """PRD §3.8: "its window must sit at least thirty days clear of every
        non-terminal audit of the same program — one in `SCHEDULED`,
        `IN_PROGRESS`, `FINDINGS_ISSUED`, or `REMEDIATION`" — a `CLOSED` audit
        is terminal and leaves the calendar free.

        Design: Difficulty/resource_temporal_overlap/audit_window_gap_boundary
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        first = _create_audit(api, program, scheduled_start="2026-09-01T00:00:00Z",
                              scheduled_end="2026-09-15T00:00:00Z")
        set_clock("2026-09-01T00:00:00Z")
        validate_success(api.start_audit(first["id"], AUD))
        validate_success(api.issue_findings(first["id"], {"findings": []}, AUD))
        closed = validate_success(api.close_audit(
            first["id"], {"outcome": "SATISFACTORY"}, AUD))
        assert closed["status"] == "CLOSED"

        # A window directly adjacent to the CLOSED audit is permitted.
        ok = _create_audit(api, program, scope="CLAIMS",
                           scheduled_start="2026-09-16T00:00:00Z",
                           scheduled_end="2026-09-20T00:00:00Z")
        assert ok["status"] == "SCHEDULED"

    def test_audit_start_before_window_rejected(self, api):
        """PRD §3.8: "Starting the audit (`SCHEDULED → IN_PROGRESS`) requires
        the clock to have reached `scheduled_start`, failing with
        `ERR_AUDIT_WINDOW_NOT_OPEN` before then."

        Design: Corner/state_machines/audit_start_before_window_rejected
        """
        carrier = create_carrier()
        program = create_program(carrier)
        audit = _create_audit(api, program,
                              scheduled_start="2026-09-01T00:00:00Z",
                              scheduled_end="2026-09-15T00:00:00Z")
        # Startup clock is 2026-08-01 < scheduled_start.
        resp = api.start_audit(audit["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_NOT_OPEN)
        fresh = validate_success(api.get_audit(audit["id"], AUD))
        assert fresh["status"] == "SCHEDULED"


class TestAuditCloseGate:
    def test_close_blocked_by_unresolved_critical_then_succeeds(self, api):
        """PRD §3.8: "The auditor closes from either `FINDINGS_ISSUED` or
        `REMEDIATION` into `CLOSED`, setting the `outcome` from the request ...
        but closure is barred while any finding of `MAJOR` or `CRITICAL`
        severity remains unresolved, failing with
        `ERR_UNRESOLVED_CRITICAL_FINDINGS`." and "The MGA underwriter answers
        with remediation (`FINDINGS_ISSUED → REMEDIATION`), supplying
        `resolved_finding_ids`; every finding whose `finding_id` appears in
        that list is marked with `resolved` set to true."

        Design: Corner/state_machines/audit_close_blocked_by_unresolved_critical_then_succeeds
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        audit = _create_audit(api, program, scope="TRUST_ACCOUNTING",
                              scheduled_start="2026-08-01T00:00:00Z",
                              scheduled_end="2026-08-20T00:00:00Z")
        validate_success(api.start_audit(audit["id"], AUD))
        validate_success(api.issue_findings(audit["id"], {"findings": [
            {"finding_id": "F1", "severity": "CRITICAL",
             "description": "unreconciled trust", "resolved": False}]}, AUD))

        blocked = api.close_audit(audit["id"], {"outcome": "CORRECTIVE_ACTION"}, AUD)
        validate_error(blocked, ApiErrorId.ERR_UNRESOLVED_CRITICAL_FINDINGS)
        fresh = validate_success(api.get_audit(audit["id"], AUD))
        assert fresh["status"] == "FINDINGS_ISSUED"

        remediated = validate_success(api.submit_remediation(
            audit["id"], {"resolved_finding_ids": ["F1"]}, UW))
        assert remediated["status"] == "REMEDIATION"
        f1 = [f for f in remediated["findings"] if f["finding_id"] == "F1"][0]
        assert f1["resolved"] is True

        closed = validate_success(api.close_audit(
            audit["id"], {"outcome": "CORRECTIVE_ACTION"}, AUD))
        assert closed["status"] == "CLOSED"
        assert closed["outcome"] == "CORRECTIVE_ACTION"

    def test_escalate_without_critical_rejected(self, api):
        """PRD §3.8: "From `FINDINGS_ISSUED` or `REMEDIATION`, the auditor may
        escalate to `ESCALATED`, but only when at least one `CRITICAL` finding
        remains unresolved — otherwise the attempt fails with
        `ERR_NO_CRITICAL_FINDING`."

        Design: Corner/state_machines/audit_escalate_without_critical_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        audit = _create_audit(api, program, scope="UNDERWRITING",
                              scheduled_start="2026-08-01T00:00:00Z",
                              scheduled_end="2026-08-20T00:00:00Z")
        validate_success(api.start_audit(audit["id"], AUD))
        validate_success(api.issue_findings(audit["id"], {"findings": [
            {"finding_id": "F1", "severity": "MAJOR",
             "description": "missing TPA oversight memo", "resolved": False}]}, AUD))

        resp = api.escalate_audit(audit["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_NO_CRITICAL_FINDING)
        fresh = validate_success(api.get_audit(audit["id"], AUD))
        assert fresh["status"] == "FINDINGS_ISSUED"
        prog = get_program_fresh(program["id"])
        assert prog["status"] == "ACTIVE"


class TestAuditEscalationCascade:
    def test_escalation_suspends_program_with_depth3_cascade(self, api):
        """PRD §3.8: "Escalation sets the audit's `outcome` to
        `TERMINATION_RECOMMENDED` and, if the program is `ACTIVE`, suspends it
        on the spot, firing the full suspension cascade of §2.10: quotes
        withdrawn, appointments suspended with their under-review claims
        referred, and draft bordereaux cancelled." PRD §2.10: "Suspending a
        program ... withdraws every `QUOTED` policy of the program ...,
        suspends every `ACTIVE` TPA appointment, and cancels every `DRAFT`
        bordereau. The appointment-level suspension itself cascades one level
        further: every claim assigned to the suspended TPA that is sitting in
        `UNDER_REVIEW` moves to `REFERRED` with `referral_reason` recorded as
        `APPOINTMENT_SUSPENDED`."

        Design: Difficulty/transitive_cascade/audit_escalation_cascade_depth3
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        set_clock("2026-08-12T00:00:00Z")
        claim = create_claim_under_review(program, policy, tpa,
                                          occurrence_date="2026-08-10T00:00:00Z",
                                          amount_claimed_cents=80000)
        qpol = quote_policy(program, insured_name="Quote Co", exposure_units=10,
                            coverage_limit_cents=100000,
                            effective_from="2026-09-01T00:00:00Z")
        bor = validate_success(api.create_bordereau(program["id"], {
            "bordereau_type": "PREMIUM", "period_label": "2026-08",
            "due_date": "2026-09-15T00:00:00Z"}, FIN), expected_status=201)

        audit = _create_audit(api, program,
                              scheduled_start="2026-09-01T00:00:00Z",
                              scheduled_end="2026-09-15T00:00:00Z")
        set_clock("2026-09-01T00:00:00Z")
        validate_success(api.start_audit(audit["id"], AUD))
        validate_success(api.issue_findings(audit["id"], {"findings": [
            {"finding_id": "F1", "severity": "CRITICAL",
             "description": "trust account shortfall", "resolved": False}]}, AUD))

        escalated = validate_success(api.escalate_audit(audit["id"], AUD))
        assert escalated["status"] == "ESCALATED"
        assert escalated["outcome"] == "TERMINATION_RECOMMENDED"

        prog = get_program_fresh(program["id"])
        assert prog["status"] == "SUSPENDED"
        appt_fresh = validate_success(api.get_appointment(
            appt["id"], make_carrier_underwriter_headers(carrier["id"])))
        assert appt_fresh["status"] == "SUSPENDED"
        claim_fresh = get_claim_fresh(claim["id"])
        assert claim_fresh["status"] == "REFERRED"
        assert claim_fresh["referral_reason"] == "APPOINTMENT_SUSPENDED"
        assert get_policy_fresh(qpol["id"])["status"] == "WITHDRAWN"
        bor_fresh = validate_success(api.get_bordereau(bor["id"], FIN))
        assert bor_fresh["status"] == "CANCELLED"
        # In-force policies are untouched by a suspension.
        assert get_policy_fresh(policy["id"])["status"] == "ISSUED"

    def test_escalation_from_remediation_also_cascades(self, api):
        """PRD §3.8: "From `FINDINGS_ISSUED` or `REMEDIATION`, the auditor may
        escalate to `ESCALATED`, but only when at least one `CRITICAL` finding
        remains unresolved" — the escalation transition exists from both
        from-states and fires the same cascade.

        Design: Difficulty/transitive_cascade/audit_escalation_cascade_depth3
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        audit = _create_audit(api, program,
                              scheduled_start="2026-08-01T00:00:00Z",
                              scheduled_end="2026-08-20T00:00:00Z")
        validate_success(api.start_audit(audit["id"], AUD))
        validate_success(api.issue_findings(audit["id"], {"findings": [
            {"finding_id": "F1", "severity": "CRITICAL",
             "description": "trust account shortfall", "resolved": False},
            {"finding_id": "F2", "severity": "MINOR",
             "description": "memo", "resolved": False}]}, AUD))
        validate_success(api.submit_remediation(
            audit["id"], {"resolved_finding_ids": ["F2"]}, UW))

        escalated = validate_success(api.escalate_audit(audit["id"], AUD))
        assert escalated["status"] == "ESCALATED"
        assert escalated["outcome"] == "TERMINATION_RECOMMENDED"
        assert get_program_fresh(program["id"])["status"] == "SUSPENDED"


class TestLossEvaluations:
    def test_insufficient_data_below_earned_floor(self, api):
        """PRD §3.8: "When the earned basis falls below the program's
        `min_earned_premium_for_ratio_cents`, the outcome is
        `INSUFFICIENT_DATA`." PRD §3.4: "the earned basis of a loss
        evaluation ... earns the plain pro-rata figure."

        Design: Corner/calculations/loss_eval_insufficient_data_below_earned_floor
        """
        carrier, program, _g, _a, _f = setup_active_program()
        policy = create_issued_policy(program, insured_name="Small Earn")
        set_clock("2026-08-12T00:00:00Z")  # 11 of 365 days elapsed
        cu = make_carrier_underwriter_headers(carrier["id"])
        evaluation = validate_success(api.create_loss_evaluation(
            program["id"], {"period_label": "2026-08"}, cu), expected_status=201)
        # earned = round_half_up(155000*11/365) = 4671 < floor 50000.
        assert evaluation["earned_premium_cents"] == 4671
        assert evaluation["outcome"] == "INSUFFICIENT_DATA"
        prog = get_program_fresh(program["id"])
        assert prog["status"] == "ACTIVE", "INSUFFICIENT_DATA fires no cascade"

    def test_corrective_action_at_exact_threshold(self, api):
        """PRD §3.8: "The `outcome` turns the ratios into consequences, with
        inclusive thresholds compared against the rounded incurred ratio. ...
        failing that, an incurred ratio at or above `corrective_threshold_pct`
        yields `CORRECTIVE_ACTION`; anything lower yields `OK`."

        Design: Corner/calculations/loss_eval_corrective_action_at_exact_threshold
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa(
                program_overrides={"aggregate_limit_cents": 1000000},
                policy_overrides={"exposure_units": 240,
                                  "coverage_limit_cents": 900000},
                guideline_overrides={"max_policy_premium_cents": 500000},
                allocation_overrides={"allocated_cents": 500000})
        set_clock("2026-08-12T00:00:00Z")
        create_paid_claim(program, policy, tpa, 40000,
                          occurrence_date="2026-08-10T00:00:00Z",
                          amount_claimed_cents=40000)
        cl2 = create_claim_under_review(program, policy, tpa,
                                        occurrence_date="2026-08-12T00:00:00Z",
                                        amount_claimed_cents=50000)
        validate_success(api.set_claim_reserve(
            cl2["id"], {"case_reserve_cents": 30000},
            make_tpa_adjuster_headers(tpa["id"])))
        set_clock("2026-11-09T00:00:00Z")  # earned = 365000*100/365 = 100000

        cu = make_carrier_underwriter_headers(carrier["id"])
        evaluation = validate_success(api.create_loss_evaluation(
            program["id"], {"period_label": "2026-11"}, cu), expected_status=201)
        # incurred = (40000 + 30000) / 100000 = 70.00 exactly.
        assert evaluation["incurred_loss_ratio_pct"] == 70.00
        assert evaluation["outcome"] == "CORRECTIVE_ACTION"
        prog = get_program_fresh(program["id"])
        assert prog["status"] == "ACTIVE", "corrective action does not suspend"

    def test_paid_vs_incurred_divergence_drives_termination_review(self, api):
        """PRD §3.8: "The paid-basis ratio is informational only — for
        identical data it never exceeds the incurred basis and may clear
        thresholds the incurred basis breaches — and only the incurred basis
        drives outcomes." and "an incurred ratio at or above
        `termination_threshold_pct` yields `TERMINATION_REVIEW`" and "A
        `TERMINATION_REVIEW` outcome auto-suspends the program, firing the
        same full suspension cascade as an audit escalation."

        Design: Difficulty/dual_variant_calc/loss_ratio_paid_vs_incurred_divergence
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa(
                program_overrides={"aggregate_limit_cents": 1000000},
                policy_overrides={"exposure_units": 240,
                                  "coverage_limit_cents": 900000},
                guideline_overrides={"max_policy_premium_cents": 500000},
                allocation_overrides={"allocated_cents": 500000})
        set_clock("2026-08-12T00:00:00Z")
        create_paid_claim(program, policy, tpa, 60000,
                          occurrence_date="2026-08-10T00:00:00Z",
                          amount_claimed_cents=60000)
        cl2 = create_claim_under_review(program, policy, tpa,
                                        occurrence_date="2026-08-12T00:00:00Z",
                                        amount_claimed_cents=50000)
        validate_success(api.set_claim_reserve(
            cl2["id"], {"case_reserve_cents": 30000},
            make_tpa_adjuster_headers(tpa["id"])))
        set_clock("2026-11-09T00:00:00Z")

        cu = make_carrier_underwriter_headers(carrier["id"])
        evaluation = validate_success(api.create_loss_evaluation(
            program["id"], {"period_label": "2026-11"}, cu), expected_status=201)
        assert evaluation["earned_premium_cents"] == 100000
        assert evaluation["paid_losses_cents"] == 60000
        assert evaluation["case_reserves_cents"] == 30000
        assert evaluation["paid_loss_ratio_pct"] == 60.00
        assert evaluation["incurred_loss_ratio_pct"] == 90.00
        # paid 60.00 would be OK; the incurred basis drives TERMINATION_REVIEW.
        assert evaluation["outcome"] == "TERMINATION_REVIEW"

        prog = get_program_fresh(program["id"])
        assert prog["status"] == "SUSPENDED"
        assert prog["latest_incurred_loss_ratio_pct"] == 90.00

    def test_termination_review_cascade_reaches_appointments_and_claims(self, api):
        """PRD §3.8: "A `TERMINATION_REVIEW` outcome auto-suspends the
        program, firing the same full suspension cascade as an audit
        escalation." PRD §2.10: "Suspending a program ... withdraws every
        `QUOTED` policy of the program ..., suspends every `ACTIVE` TPA
        appointment, and cancels every `DRAFT` bordereau. The
        appointment-level suspension itself cascades one level further: every
        claim assigned to the suspended TPA that is sitting in `UNDER_REVIEW`
        moves to `REFERRED` with `referral_reason` recorded as
        `APPOINTMENT_SUSPENDED`."

        Design: Difficulty/transitive_cascade/loss_eval_termination_cascade_depth3
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa(
                program_overrides={"aggregate_limit_cents": 1000000},
                policy_overrides={"exposure_units": 240,
                                  "coverage_limit_cents": 900000},
                guideline_overrides={"max_policy_premium_cents": 500000},
                allocation_overrides={"allocated_cents": 500000})
        set_clock("2026-08-12T00:00:00Z")
        cl1 = create_paid_claim(program, policy, tpa, 60000,
                                occurrence_date="2026-08-10T00:00:00Z",
                                amount_claimed_cents=60000)
        cl2 = create_claim_under_review(program, policy, tpa,
                                        occurrence_date="2026-08-12T00:00:00Z",
                                        amount_claimed_cents=50000)
        validate_success(api.set_claim_reserve(
            cl2["id"], {"case_reserve_cents": 30000},
            make_tpa_adjuster_headers(tpa["id"])))
        qpol = quote_policy(program, insured_name="Late Quote", exposure_units=10,
                            coverage_limit_cents=100000,
                            effective_from="2026-08-12T00:00:00Z")
        set_clock("2026-11-09T00:00:00Z")

        cu = make_carrier_underwriter_headers(carrier["id"])
        evaluation = validate_success(api.create_loss_evaluation(
            program["id"], {"period_label": "2026-11"}, cu), expected_status=201)
        assert evaluation["outcome"] == "TERMINATION_REVIEW"

        assert get_program_fresh(program["id"])["status"] == "SUSPENDED"
        appt_fresh = validate_success(api.get_appointment(appt["id"], cu))
        assert appt_fresh["status"] == "SUSPENDED"
        cl2_fresh = get_claim_fresh(cl2["id"])
        assert cl2_fresh["status"] == "REFERRED"
        assert cl2_fresh["referral_reason"] == "APPOINTMENT_SUSPENDED"
        assert get_policy_fresh(qpol["id"])["status"] == "WITHDRAWN"
        # Only UNDER_REVIEW claims are referred; the PAID claim is untouched.
        assert get_claim_fresh(cl1["id"])["status"] == "PAID"

    def test_termination_review_cascade_cancels_draft_bordereau(self, api):
        """PRD §3.8: "A `TERMINATION_REVIEW` outcome auto-suspends the
        program, firing the same full suspension cascade as an audit
        escalation." PRD §2.10: "Suspending a program ... cancels every
        `DRAFT` bordereau."

        Design: Difficulty/transitive_cascade/loss_eval_termination_cascade_depth3
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa(
                program_overrides={"aggregate_limit_cents": 1000000},
                policy_overrides={"exposure_units": 240,
                                  "coverage_limit_cents": 900000},
                guideline_overrides={"max_policy_premium_cents": 500000},
                allocation_overrides={"allocated_cents": 500000})
        set_clock("2026-08-12T00:00:00Z")
        create_paid_claim(program, policy, tpa, 60000,
                          occurrence_date="2026-08-10T00:00:00Z",
                          amount_claimed_cents=60000)
        cl2 = create_claim_under_review(program, policy, tpa,
                                        occurrence_date="2026-08-12T00:00:00Z",
                                        amount_claimed_cents=50000)
        validate_success(api.set_claim_reserve(
            cl2["id"], {"case_reserve_cents": 30000},
            make_tpa_adjuster_headers(tpa["id"])))
        bor = validate_success(api.create_bordereau(program["id"], {
            "bordereau_type": "PREMIUM", "period_label": "2026-08",
            "due_date": "2026-12-15T00:00:00Z"}, FIN), expected_status=201)
        set_clock("2026-11-09T00:00:00Z")

        cu = make_carrier_underwriter_headers(carrier["id"])
        evaluation = validate_success(api.create_loss_evaluation(
            program["id"], {"period_label": "2026-11"}, cu), expected_status=201)
        assert evaluation["outcome"] == "TERMINATION_REVIEW"
        bor_fresh = validate_success(api.get_bordereau(bor["id"], FIN))
        assert bor_fresh["status"] == "CANCELLED"

    def test_paid_ratio_alone_below_threshold_does_not_suspend(self, api):
        """PRD §3.8: "only the incurred basis drives outcomes" — a scenario
        whose paid ratio (60.00) clears the corrective threshold while the
        incurred ratio (90.00) breaches termination still produces exactly the
        incurred-driven outcome and cascade; the paid figure is recorded but
        inert.

        Design: Difficulty/dual_variant_calc/loss_ratio_paid_vs_incurred_divergence
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa(
                program_overrides={"aggregate_limit_cents": 1000000},
                policy_overrides={"exposure_units": 240,
                                  "coverage_limit_cents": 900000},
                guideline_overrides={"max_policy_premium_cents": 500000},
                allocation_overrides={"allocated_cents": 500000})
        set_clock("2026-08-12T00:00:00Z")
        create_paid_claim(program, policy, tpa, 60000,
                          occurrence_date="2026-08-10T00:00:00Z",
                          amount_claimed_cents=60000)
        cl2 = create_claim_under_review(program, policy, tpa,
                                        occurrence_date="2026-08-12T00:00:00Z",
                                        amount_claimed_cents=50000)
        validate_success(api.set_claim_reserve(
            cl2["id"], {"case_reserve_cents": 30000},
            make_tpa_adjuster_headers(tpa["id"])))
        set_clock("2026-11-09T00:00:00Z")
        cu = make_carrier_underwriter_headers(carrier["id"])
        evaluation = validate_success(api.create_loss_evaluation(
            program["id"], {"period_label": "2026-11"}, cu), expected_status=201)
        # Same inputs, two variants: paid clears (60.00 < 70), incurred
        # breaches (90.00 >= 85). The outcome follows the incurred basis only.
        assert evaluation["paid_loss_ratio_pct"] == 60.00
        assert evaluation["incurred_loss_ratio_pct"] == 90.00
        assert evaluation["outcome"] == "TERMINATION_REVIEW"
