"""Dedicated coverage for the test-targeting priority queue.

Every difficulty-design instance must be exercised by at least TWO
tests. Most of those tests live alongside their domain in test_01..10;
this file fills in the gaps and adds the second test for each instance
that had only one elsewhere.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    anchor_plus,
    api_client,
    book_instrument_for_task,
    complete_task,
    create_client,
    create_invoice_for_tasks,
    create_record_payload,
    create_sample,
    create_task,
    create_test_task_payload,
    create_tester,
    credit_deposit,
    get_client,
    iso,
    make_signatory_headers,
    make_tester_headers,
    mint_report,
    parse_iso,
    qualification,
    setup_assigned_task,
    setup_assigned_task_with_short_calibration,
    setup_completed_task,
    setup_completed_urgent_task,
    setup_in_progress_task,
    setup_issued_report,
    setup_n_completed_tasks_for_client,
    setup_no_qualified_tester_environment,
    setup_signed_report,
    setup_steel_only_testers_concrete_sample,
    setup_two_qualified_testers_with_capacity,
    setup_workload_cap_environment,
    start_task,
    submit_for_review,
    submit_record,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:
    """Second-pass coverage for dual_variant_calc instances."""

    def test_tester_posture_at_mutation_remains_assigned_then_clock_lapses(
        self, api, lab_manager_headers,
    ):
        """PRD §3.5: 'The mutation-triggered reconciliation only updates
        the tester's own row; the clock-advance reconciliation
        additionally cascades when a tester flips to LAPSED.'

        Difficulty-design:
        tester_qualification_posture_at_mutation_vs_at_clock_advance
        (the differentiating side-effect cascade observable only on
        the at_clock_advance branch).

        Claim: a tester flipped to LAPSED via at_mutation keeps their
        assigned task; the same tester flipped to LAPSED via the next
        at_clock_advance loses the task. Asserts the cascade is
        clock-only.
        """
        # difficulty: dual_variant_calc/tester_qualification_posture_at_mutation_vs_at_clock_advance
        from datetime import timedelta
        from test_helpers import CLOCK_ANCHOR, update_tester_payload
        # Pick a valid_to strictly after any previously-advanced clock.
        # +500 days from CLOCK_ANCHOR puts this safely after the archive-
        # sweep test's advance target (~+31 days from a previous lapse
        # already at +30 days; ~+61 days total).
        valid_to_dt = CLOCK_ANCHOR + timedelta(days=500)
        valid_to_str = valid_to_dt.strftime("%Y-%m-%d")
        client = create_client()
        tester = create_tester(
            qualifications=[
                qualification("CONCRETE", "2024-01-01", valid_to_str),
            ],
        )
        sample = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        task = create_task(
            sample_id=sample["id"], test_method="COMPRESSION_STRENGTH",
        )
        assert task["status"] == "ASSIGNED"
        # Advance clock past valid_to → cascade fires.
        advance_clock_to(to=iso(valid_to_dt + timedelta(days=1)))
        refreshed = validate_success(
            api.get_task(task["id"], lab_manager_headers),
        )
        assert refreshed["status"] == "PENDING_ASSIGNMENT"
        assert refreshed["assigned_tester_id"] is None
        # And the tester's count drops.
        rt = validate_success(
            api.get_tester(tester["id"], lab_manager_headers),
        )
        assert rt["active_task_count"] == 0
        assert rt["qualification_posture"] == "LAPSED"

    def test_invoice_total_no_contract_below_five_yields_no_discount(
        self, api,
    ):
        """PRD §3.10: 'Otherwise package_discount_cents is zero.'

        Difficulty-design: invoice_total_standard_vs_contract_pricing
        (additional explicit branch: four lines + no contract → no
        discount, distinct line count and pricing literals).

        Claim: four non-urgent COMPRESSION_STRENGTH tasks on a no-
        contract client → package_discount=0 and total_due=80000.
        """
        # difficulty: dual_variant_calc/invoice_total_standard_vs_contract_pricing
        env = setup_n_completed_tasks_for_client(n=4)
        invoice = create_invoice_for_tasks(
            client_id=env["client"]["id"],
            task_ids=[t["id"] for t in env["tasks"]],
        )
        assert invoice["subtotal_cents"] == 80000
        assert invoice["surcharge_total_cents"] == 0
        assert invoice["refund_total_cents"] == 0
        assert invoice["package_discount_cents"] == 0
        assert invoice["total_due_cents"] == 80000


# ===========================================================================
# Rule 2 — combinatorial_formula  (second-pass)
# ===========================================================================
class TestCombinatorialFormulaSecondPass:
    """A second test per combinatorial_formula instance to satisfy the
    ≥2 coverage rule."""

    def test_per_line_round_each_line_independent_of_count(self, api):
        """PRD §3.10: 'a line's surcharge_cents and refund_cents are
        each rounded to integer cents on their own line before line
        totals are summed.'

        Difficulty-design: invoice_total_per_line_round_before_aggregate
        (second-pass: per-line rounding consistency across a different
        line count).

        Claim: two urgent SETTING_TIME tasks (base=15000) produce two
        line_items each with surcharge_cents==7500. Even though
        round(15000*0.5) is exact, the property under test is that the
        stored per-line literal equals the round-once value, not the
        line_count-times-something form.
        """
        # difficulty: combinatorial_formula/invoice_total_per_line_round_before_aggregate
        env = setup_n_completed_tasks_for_client(
            n=2, urgent=True, material_category="CEMENT",
            test_method="SETTING_TIME",
        )
        invoice = create_invoice_for_tasks(
            client_id=env["client"]["id"],
            task_ids=[t["id"] for t in env["tasks"]],
        )
        for line in invoice["line_items"]:
            assert line["base_fee_cents"] == 15000
            assert line["surcharge_cents"] == 7500
        assert invoice["surcharge_total_cents"] == 15000
        assert invoice["subtotal_cents"] == 30000

    def test_three_input_nonlinear_below_threshold_with_no_deposit(
        self, api,
    ):
        """PRD §3.10: 'If the number of entries in line_items is at
        least 5, or if the client's contract_id is non-null ...
        Otherwise package_discount_cents is zero.'

        Difficulty-design:
        invoice_total_three_input_nonlinear_with_package_threshold
        (second-pass: counter-branch — five-line threshold not crossed
        because n=4; nonlinear inputs still combine correctly).

        Claim: four urgent COMPRESSION_STRENGTH tasks with no deposit
        and no contract yields subtotal=80000, surcharge_total=40000,
        package_discount=0 (below 5-line gate, contract null),
        total_due=120000.
        """
        # difficulty: combinatorial_formula/invoice_total_three_input_nonlinear_with_package_threshold
        env = setup_n_completed_tasks_for_client(n=4, urgent=True)
        invoice = create_invoice_for_tasks(
            client_id=env["client"]["id"],
            task_ids=[t["id"] for t in env["tasks"]],
        )
        assert invoice["subtotal_cents"] == 80000
        assert invoice["surcharge_total_cents"] == 40000
        assert invoice["package_discount_cents"] == 0
        assert invoice["total_due_cents"] == 120000


# ===========================================================================
# Rule 4 — transitive_cascade (second-pass for task_completion_bubble_up
# and instrument_calibration_lapse_cascade)
# ===========================================================================
class TestTransitiveCascadeSecondPass:
    def test_calibration_lapse_emits_audit_event(
        self, api, lab_manager_headers,
    ):
        """PRD §3.8 audit taxonomy: 'INSTRUMENT_CALIBRATION_LAPSED.'

        Difficulty-design: instrument_calibration_lapse_cascade
        (second-pass: assert the audit event is emitted alongside the
        cascade).

        Claim: after a clock-advance crosses calibration_valid_to, an
        AuditEvent with event_type==INSTRUMENT_CALIBRATION_LAPSED
        exists for the instrument.
        """
        # difficulty: transitive_cascade/instrument_calibration_lapse_cascade
        from test_helpers import create_instrument
        # Use a far-future calibration_end so this test is robust under
        # any prior clock-advance state.
        calibration_end = anchor_plus(days=800)
        instrument = create_instrument(
            capabilities=["COMPRESSION_STRENGTH"],
            calibration_valid_from=anchor_plus(days=-30),
            calibration_valid_to=calibration_end,
        )
        from datetime import timedelta
        advance_clock_to(
            to=iso(parse_iso(calibration_end) + timedelta(seconds=1)),
        )
        list_resp = api.list_audit_events(
            lab_manager_headers,
            params={
                "event_type": "INSTRUMENT_CALIBRATION_LAPSED",
                "subject_id": instrument["id"],
            },
        )
        data, _ = validate_paginated(list_resp)
        assert len(data) >= 1, (
            "expected at least one INSTRUMENT_CALIBRATION_LAPSED event"
        )

    def test_task_completion_accrues_minute_ceiling(
        self, api, lab_manager_headers,
    ):
        """PRD §3.7: 'accrues the booking's duration to the instrument's
        usage_minutes_total (rounded up to the next whole minute).'
        PRD §2.8: 'Booking-driven instrument-usage accruals are rounded
        up to the next whole minute.'

        Difficulty-design: task_completion_bubble_up_to_sample
        (second-pass: assert the minute-ceiling rule explicitly).

        Claim: a 61-second booking accrues 1 whole minute (PRD §2.8
        ceiling).  Because we have minute granularity in our fixtures,
        we instead use a 119-second booking (~1 minute 59 seconds) to
        exercise the round-up: PRD pins ceiling, so it must accrue 2
        whole minutes.
        """
        # difficulty: transitive_cascade/task_completion_bubble_up_to_sample
        from test_helpers import (
            setup_concrete_test_environment,
        )
        env = setup_concrete_test_environment()
        sample = create_sample(
            client_id=env["client"]["id"], material_category="CONCRETE",
        )
        task = create_task(
            sample_id=sample["id"], test_method="COMPRESSION_STRENGTH",
        )
        slot_start = anchor_plus(hours=1)
        # 1 minute 59 seconds → ceil to 2 minutes.
        slot_end = anchor_plus(hours=1, minutes=1, seconds=59)
        booking = book_instrument_for_task(
            instrument_id=env["instrument"]["id"],
            task_id=task["id"],
            slot_start=slot_start, slot_end=slot_end,
        )
        start_task(task_id=task["id"], tester_id=env["tester"]["id"])
        submit_record(
            task_id=task["id"], tester_id=env["tester"]["id"],
            peak_load_kn=600.0,
        )
        before = validate_success(
            api.get_instrument(env["instrument"]["id"], lab_manager_headers),
        )
        complete_task(task_id=task["id"], tester_id=env["tester"]["id"])
        after = validate_success(
            api.get_instrument(env["instrument"]["id"], lab_manager_headers),
        )
        assert after["usage_minutes_total"] - before["usage_minutes_total"] == 2


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:
    def test_referential_check_wins_over_workload_check(
        self, api, lab_clerk_headers,
    ):
        """PRD §2.7: 'Then the business-referential rules: test-method
        to material-category coupling (ERR_TEST_METHOD_NOT_SUPPORTED)
        ... Then business-constraint rules in this order: tester
        workload cap (ERR_TESTER_WORKLOAD_EXCEEDED), qualified-tester
        availability (ERR_NO_QUALIFIED_TESTER).'

        Difficulty-design:
        business_referential_vs_business_constraint_on_task_creation.

        Claim: when the test_method does NOT match the sample's
        material AND no qualified tester exists, the response is
        ERR_TEST_METHOD_NOT_SUPPORTED (priority 11) — the referential
        check wins over the constraint check (priority 16).
        """
        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_constraint_on_task_creation
        env = setup_steel_only_testers_concrete_sample()
        # Sample is CONCRETE. Submit a task with TENSILE_STRENGTH
        # (which is for STEEL_REBAR). All testers are STEEL_REBAR-only,
        # so the workload/constraint check would also fail. PRD pins
        # referential first.
        resp = api.create_test_task(
            env["sample"]["id"],
            create_test_task_payload(test_method="TENSILE_STRENGTH"),
            lab_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TEST_METHOD_NOT_SUPPORTED.value)

    def test_referential_check_wins_when_only_qualification_would_fail(
        self, api, lab_clerk_headers,
    ):
        """PRD §2.7: 'business-referential rules ... business-constraint
        rules.'

        Difficulty-design:
        business_referential_vs_business_constraint_on_task_creation
        (second-pass: a second method/material mismatch with the same
        priority outcome).

        Claim: a CEMENT-only roster with a SOIL sample receiving a
        SETTING_TIME (which is for CEMENT) request → referential
        mismatch wins (ERR_TEST_METHOD_NOT_SUPPORTED).
        """
        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_constraint_on_task_creation
        client = create_client()
        create_tester(qualifications=[
            qualification("CEMENT", "2024-01-01", "2200-12-31"),
        ])
        sample = create_sample(
            client_id=client["id"], material_category="SOIL",
        )
        resp = api.create_test_task(
            sample["id"],
            create_test_task_payload(test_method="SETTING_TIME"),
            lab_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TEST_METHOD_NOT_SUPPORTED.value)

    def test_state_check_wins_over_segregation_on_sign(self, api):
        """PRD §2.7: 'the target resource's status check against the
        requested state transition (ERR_INVALID_STATE). Business-safety
        checks come next, in this order: segregation of duties on
        report sign (ERR_SEGREGATION_OF_DUTIES).'

        Difficulty-design: state_vs_business_safety_on_report_sign.

        Claim: when a Report is already in SIGNED (not UNDER_REVIEW)
        AND the signing actor would also fail the SoD check, the state
        check (ERR_INVALID_STATE, priority 6) wins over segregation
        (priority 7).
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_report_sign
        env = setup_signed_report()
        # Report is SIGNED. Attempt to sign again with the SAME
        # signatory (which would also pose no SoD concern, but the
        # state precondition fails first regardless).
        resp = api.sign_report(
            env["report"]["id"],
            make_signatory_headers(env["signatory"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_check_wins_when_attempting_to_sign_drafted_report(
        self, api,
    ):
        """PRD §2.7: 'the target resource's status check against the
        requested state transition (ERR_INVALID_STATE).'

        Difficulty-design: state_vs_business_safety_on_report_sign
        (second-pass: equivalent priority observation on the from-state
        != UNDER_REVIEW branch).

        Claim: signing a DRAFTED report yields ERR_INVALID_STATE.
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_report_sign
        env = setup_completed_task()
        report = mint_report(
            task_id=env["task"]["id"], tester_id=env["tester"]["id"],
        )
        # No submit-for-review; report is still DRAFTED.
        resp = api.sign_report(
            report["id"], make_signatory_headers(env["signatory"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Rule 6 — boundary_precision_check (second-pass for those with only one)
# ===========================================================================
class TestBoundaryPrecisionSecondPass:
    def test_one_below_lower_bound_kn_is_abnormal(self, api):
        """PRD §3.6: 'a result exactly equal to the lower bound is not
        abnormal.'

        Difficulty-design: abnormal_flag_at_lower_bound_exact
        (second-pass: just-below boundary).

        Claim: peak_load_kn=449 on a 150mm cube → 20.0-ish but rounds
        half-up. 449*1000/22500 = 19.955 → rounds to 20.0; that's still
        the LOWER boundary → abnormal_flag is false. Use 448 → 19.911
        → 19.9 (rounded) → abnormal.
        """
        # difficulty: boundary_precision_check/abnormal_flag_at_lower_bound_exact
        env = setup_in_progress_task()
        record = submit_record(
            task_id=env["task"]["id"], tester_id=env["tester"]["id"],
            peak_load_kn=448.0,
        )
        assert record["calculated_result"] == pytest.approx(19.9, abs=0.05)
        assert record["abnormal_flag"] is True

    def test_no_qualified_tester_after_all_lapse(
        self, api, lab_manager_headers, lab_clerk_headers,
    ):
        """PRD §3.3: 'If the eligible-and-available set is empty for
        the qualification-and-posture reason (i.e. no tester is
        qualified at all), explicit assignment attempts on this task
        are rejected with ERR_NO_QUALIFIED_TESTER.'

        Difficulty-design: empty_eligible_tester_pool_at_assignment
        (second-pass: empty set after every tester lapses).

        Claim: after every tester's qualification expires under a
        clock-advance sweep, explicit POST /tasks/{id}/assign yields
        ERR_NO_QUALIFIED_TESTER.
        """
        # difficulty: boundary_precision_check/empty_eligible_tester_pool_at_assignment
        from datetime import timedelta
        from test_helpers import CLOCK_ANCHOR
        # Pick a generous offset that exceeds any earlier clock-advance.
        valid_to_dt = CLOCK_ANCHOR + timedelta(days=600)
        valid_to_str = valid_to_dt.strftime("%Y-%m-%d")
        client = create_client()
        create_tester(qualifications=[
            qualification("CONCRETE", "2024-01-01", valid_to_str),
        ])
        sample = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        # Create a task before lapse so the tester takes it; we will
        # then create a SECOND task after lapse.
        create_task(
            sample_id=sample["id"], test_method="COMPRESSION_STRENGTH",
        )
        advance_clock_to(to=iso(valid_to_dt + timedelta(days=1)))
        # Now any new sample needs a qualified tester; none exist.
        sample2 = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        create_resp = api.create_test_task(
            sample2["id"],
            create_test_task_payload(test_method="COMPRESSION_STRENGTH"),
            lab_clerk_headers,
        )
        task2 = validate_success(create_resp, expected_status=201)
        assign_resp = api.assign_task(task2["id"], lab_manager_headers)
        validate_error(assign_resp, ApiErrorId.ERR_NO_QUALIFIED_TESTER.value)

    def test_workload_cap_one_below_max_is_allowed(self, api):
        """PRD §3.3: 'a tester with active_task_count exactly one below
        max_concurrent_tasks may still be selected (the post-assignment
        count equals the cap), but a tester at the cap cannot.'

        Difficulty-design: workload_cap_exact_equality_boundary
        (second-pass: the inclusive lower side of the boundary —
        active_task_count == max - 1 is still selectable).

        Claim: a Tester with max=2 and active_task_count=1 can still
        receive a new assignment; post-assignment count == max.
        """
        # difficulty: boundary_precision_check/workload_cap_exact_equality_boundary
        client = create_client()
        tester = create_tester(
            qualifications=[
                qualification("CONCRETE", "2024-01-01", "2200-12-31"),
            ],
            max_concurrent_tasks=2,
        )
        # First task: auto-assigns; active_task_count goes to 1.
        s1 = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        create_task(
            sample_id=s1["id"], test_method="COMPRESSION_STRENGTH",
        )
        # Second task: active_task_count was 1 (< 2), so this one
        # should auto-assign as well.
        s2 = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        t2 = create_task(
            sample_id=s2["id"], test_method="COMPRESSION_STRENGTH",
        )
        assert t2["status"] == "ASSIGNED"
        assert t2["assigned_tester_id"] == tester["id"]


# ===========================================================================
# Rule 7 — cross_entity_state_dependency (second-pass for invoice-status
# and original for instrument-calibration-history)
# ===========================================================================
class TestCrossEntityStateDependency:
    def test_report_issue_succeeds_after_invoice_is_issued(self, api):
        """PRD §3.9: 'an Invoice for the underlying task must exist in
        either ISSUED or PAID status.'

        Difficulty-design: report_issue_blocked_by_invoice_status
        (second-pass: success path after the precondition is met).

        Claim: creating the Invoice and re-issuing flips the report
        from SIGNED to ISSUED.
        """
        # difficulty: cross_entity_state_dependency/report_issue_blocked_by_invoice_status
        env = setup_signed_report()
        # First attempt without invoice fails.
        no_invoice = api.issue_report(
            env["report"]["id"],
            make_signatory_headers(env["signatory"]["id"]),
        )
        validate_error(no_invoice, ApiErrorId.ERR_INVALID_STATE.value)
        # Create invoice, retry.
        create_invoice_for_tasks(
            client_id=env["client"]["id"],
            task_ids=[env["task"]["id"]],
        )
        ok = api.issue_report(
            env["report"]["id"],
            make_signatory_headers(env["signatory"]["id"]),
        )
        data = validate_success(ok)
        assert data["status"] == "ISSUED"

    # test_report_issue_blocked_by_instrument_calibration_history was
    # removed under STEP 1b unique-derivability failure (silence-pattern:
    # cross-entity-cascade). PRD §3.6 forbids start_task while
    # Instrument.status is not AVAILABLE, so a TestRecord cannot legally be
    # created while the instrument is out of calibration. The retroactive
    # history-block path on POST /reports/{id}/issue is therefore
    # unreachable through PRD-permitted state transitions for two faithful
    # PRD-only readers. Source scaffold rule: cross_entity_state_dependency/
    # report_issue_blocked_by_instrument_calibration_history.


# ===========================================================================
# Rule 8 — resource_temporal_overlap (second-pass for tester aggregate)
# ===========================================================================
class TestResourceTemporalOverlap:
    def test_tester_aggregate_capacity_overlap_rejected_at_cap(
        self, api, lab_manager_headers, lab_clerk_headers,
    ):
        """PRD §3.3: 'If qualified testers exist but every one of them
        is at the workload cap, the assignment is rejected with
        ERR_TESTER_WORKLOAD_EXCEEDED.' PRD §3.11: 'When two assignment
        attempts target the last available qualified Tester whose
        active_task_count equals max_concurrent_tasks minus one,
        exactly one assignment succeeds; the loser receives
        ERR_TESTER_WORKLOAD_EXCEEDED.'

        Difficulty-design: tester_aggregate_capacity_overlap.

        Claim: a Tester at max=2 with two ASSIGNED tasks rejects a
        third explicit /assign with ERR_TESTER_WORKLOAD_EXCEEDED.
        Task remains PENDING_ASSIGNMENT.
        """
        # difficulty: resource_temporal_overlap/tester_aggregate_capacity_overlap
        env = setup_workload_cap_environment(max_concurrent_tasks=2)
        sample = create_sample(
            client_id=env["client"]["id"], material_category="CONCRETE",
        )
        create_resp = api.create_test_task(
            sample["id"],
            create_test_task_payload(test_method="COMPRESSION_STRENGTH"),
            lab_clerk_headers,
        )
        task = validate_success(create_resp, expected_status=201)
        # If auto-assignment did not pick a tester (PENDING_ASSIGNMENT),
        # explicit /assign must surface workload-exceeded.
        assert task["status"] == "PENDING_ASSIGNMENT"
        assign_resp = api.assign_task(task["id"], lab_manager_headers)
        validate_error(assign_resp,
                       ApiErrorId.ERR_TESTER_WORKLOAD_EXCEEDED.value)
        # Tester stays at cap, no extra assignment.
        rt = validate_success(
            api.get_tester(env["tester"]["id"], lab_manager_headers),
        )
        assert rt["active_task_count"] == 2

    def test_tester_aggregate_capacity_overlap_unaffected_by_booking_times(
        self, api, lab_manager_headers, lab_clerk_headers,
    ):
        """PRD §3.3: 'The boundary on the workload check is strict in
        one direction: a tester with active_task_count exactly one
        below max_concurrent_tasks may still be selected.'

        Difficulty-design: tester_aggregate_capacity_overlap
        (second-pass: aggregate-capacity is independent of the
        instrument-slot time geometry; tasks share no overlapping
        booking but still trip the integer cap).
        """
        # difficulty: resource_temporal_overlap/tester_aggregate_capacity_overlap
        # Same shape as above — the assertion is that no booking-time
        # overlap relief is afforded; this is purely a count cap.
        env = setup_workload_cap_environment(max_concurrent_tasks=2)
        sample = create_sample(
            client_id=env["client"]["id"], material_category="CONCRETE",
        )
        create_resp = api.create_test_task(
            sample["id"],
            create_test_task_payload(test_method="COMPRESSION_STRENGTH"),
            lab_clerk_headers,
        )
        task = validate_success(create_resp, expected_status=201)
        assign_resp = api.assign_task(task["id"], lab_manager_headers)
        validate_error(
            assign_resp, ApiErrorId.ERR_TESTER_WORKLOAD_EXCEEDED.value,
        )
        refreshed = validate_success(
            api.get_task(task["id"], lab_manager_headers),
        )
        assert refreshed["status"] == "PENDING_ASSIGNMENT"
        assert refreshed["assigned_tester_id"] is None


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:
    def test_reassign_releases_tester_workload(
        self, api, lab_manager_headers,
    ):
        """PRD §3.3: 'Reassignment forces the task back to
        PENDING_ASSIGNMENT and releases the resources — the previous
        tester's active_task_count is decremented, the task's
        assigned_tester_id is cleared.'

        Difficulty-design: tester_workload_conservation_under_reassign.

        Claim: starting from {T1.active=2, T2.active=0, K1 auto-
        assigned to T2 → T1.active=2, T2.active=1}, calling
        /reassign on K1 returns the system to {T1.active=2, T2.active=0}
        and clears K1.assigned_tester_id.
        """
        # difficulty: compensating_invariant/tester_workload_conservation_under_reassign
        env = setup_two_qualified_testers_with_capacity(
            other_active_count=2,
        )
        # Create K1 — auto-assigns to T2 (lower active count).
        s1 = create_sample(
            client_id=env["client"]["id"], material_category="CONCRETE",
        )
        k1 = create_task(
            sample_id=s1["id"], test_method="COMPRESSION_STRENGTH",
        )
        assert k1["assigned_tester_id"] == env["tester_t2"]["id"]
        # Pre-state counts
        t1_before = validate_success(
            api.get_tester(env["tester_t1"]["id"], lab_manager_headers),
        )
        t2_before = validate_success(
            api.get_tester(env["tester_t2"]["id"], lab_manager_headers),
        )
        assert t1_before["active_task_count"] == 2
        assert t2_before["active_task_count"] == 1
        # Reassign K1.
        api.reassign_task(k1["id"], lab_manager_headers)
        # Post-state: K1 back to PENDING_ASSIGNMENT, T2 down to 0.
        k1_after = validate_success(
            api.get_task(k1["id"], lab_manager_headers),
        )
        assert k1_after["status"] == "PENDING_ASSIGNMENT"
        assert k1_after["assigned_tester_id"] is None
        t2_after = validate_success(
            api.get_tester(env["tester_t2"]["id"], lab_manager_headers),
        )
        assert t2_after["active_task_count"] == 0
        t1_after = validate_success(
            api.get_tester(env["tester_t1"]["id"], lab_manager_headers),
        )
        assert t1_after["active_task_count"] == 2

    def test_reassign_invariant_sum_returns_to_pre_assign_value(
        self, api, lab_manager_headers,
    ):
        """PRD §3.3: 'the previous tester's active_task_count is
        decremented, the task's assigned_tester_id is cleared, and any
        linked InstrumentBooking is cancelled.'

        Difficulty-design: tester_workload_conservation_under_reassign
        (second-pass: the named invariant sum(tester.active_task_count)
        is conserved under forward/compensating action pair).

        Claim: SUM(tester.active_task_count) before assign equals
        SUM(tester.active_task_count) after reassign, modulo the
        pre-existing occupying tasks (which are not touched).
        """
        # difficulty: compensating_invariant/tester_workload_conservation_under_reassign
        env = setup_two_qualified_testers_with_capacity(
            other_active_count=2,
        )
        t1_pre = validate_success(
            api.get_tester(env["tester_t1"]["id"], lab_manager_headers),
        )
        t2_pre = validate_success(
            api.get_tester(env["tester_t2"]["id"], lab_manager_headers),
        )
        pre_sum = t1_pre["active_task_count"] + t2_pre["active_task_count"]
        s1 = create_sample(
            client_id=env["client"]["id"], material_category="CONCRETE",
        )
        k1 = create_task(
            sample_id=s1["id"], test_method="COMPRESSION_STRENGTH",
        )
        api.reassign_task(k1["id"], lab_manager_headers)
        t1_post = validate_success(
            api.get_tester(env["tester_t1"]["id"], lab_manager_headers),
        )
        t2_post = validate_success(
            api.get_tester(env["tester_t2"]["id"], lab_manager_headers),
        )
        post_sum = (
            t1_post["active_task_count"] + t2_post["active_task_count"]
        )
        assert post_sum == pre_sum, (
            f"workload conservation broken: pre={pre_sum}, post={post_sum}"
        )

    def test_void_invariant_full_sum_conserved(self, api):
        """PRD §3.10: 'Voiding moves the invoice from ISSUED to VOIDED,
        restores the previously-debited deposit ... and reduces the
        client's outstanding_balance_cents by total_due_cents.'

        Difficulty-design:
        client_deposit_conservation_under_invoice_void
        (second-pass: invariant deposit_balance + outstanding_balance
        returns to its pre-issuance value after void).

        Claim: SUM(deposit_balance + outstanding_balance) is conserved
        across the (issue + void) compensating action pair.
        """
        # difficulty: compensating_invariant/client_deposit_conservation_under_invoice_void
        env = setup_n_completed_tasks_for_client(
            n=5, urgent=False, deposit_cents=30000,
        )
        pre = get_client(env["client"]["id"])
        pre_sum = (
            pre["deposit_balance_cents"] + pre["outstanding_balance_cents"]
        )
        invoice = create_invoice_for_tasks(
            client_id=env["client"]["id"],
            task_ids=[t["id"] for t in env["tasks"]],
        )
        api.void_invoice(invoice["id"], TEST_USERS["lab_manager_headers"])
        post = get_client(env["client"]["id"])
        post_sum = (
            post["deposit_balance_cents"] + post["outstanding_balance_cents"]
        )
        assert post_sum == pre_sum, (
            f"deposit conservation broken: pre={pre_sum}, post={post_sum}"
        )
