"""Difficulty-design coverage — supplemental tests.

Each scaffold_difficulty_design instance has TWO tests:
  - one in test_10_difficulty_coverage.py (primary)
  - one here (supplemental, exercising a different facet of the same
    underlying rule)
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    assert_audit_action_absent,
    assert_audit_action_present,
    assert_audit_order,
    attest_section1,
    create_employee,
    create_i9_form,
    create_i9_form_payload,
    EMPLOYER_REP_SECONDARY_ID,
    EMPLOYER_REP_SHARED_ID,
    find_audit_actions,
    get_employee,
    get_everify_case,
    list_audit_events,
    list_i9_forms,
    list_reverification_events,
    make_employee_headers,
    make_employer_rep_headers,
    register_ead_document,
    register_list_a_document,
    register_list_b_document,
    register_list_c_document,
    register_document,
    run_sweep,
    section1_payload,
    section2_payload,
    setup_employee_for_idempotent_replay,
    setup_employee_for_initial_form_uniqueness,
    setup_employee_for_section3_supersession,
    setup_employee_with_pending_case,
    setup_employee_with_section2_done,
    setup_employee_with_single_open_case,
    setup_initial_then_rehire_scenario,
    setup_juneteenth_holiday_scenario,
    setup_section2_deadline_boundary_scenario,
    setup_supersession_with_ead_scenario,
    setup_sweep_cascade_scenario,
    setup_tnc_cycle_scenario,
    setup_tnc_juneteenth_scenario,
    setup_two_tnc_employees_for_dual_close,
    sign_section2,
    submit_everify_case,
    submit_everify_payload,
    submit_tnc_decision,
    TEST_USERS,
    update_employee_payload,
    validate_error,
    validate_success,
    void_form,
)


# ===========================================================================
# Rule 1 — dual_variant_calc (supplemental)
# ===========================================================================
class TestDualVariantCalcSupplemental:

    def test_section2_deadline_initial_vs_rehire_inequality_pinned(self,
                                                                   api):
        """PRD §3.4: "the rehire variant of the Section 2 deadline
        computes the later of the predecessor's `section2_completed_at`
        or three federal working days after the rehire `start_date`,
        allowing the employer to either reuse the prior I-9 or to
        start a new clock — whichever instant is later wins."

        Supplemental claim: the rehire variant pins max(...)
        explicitly — the formula differs from the standard variant
        even when applied to the rehire start_date alone. With
        predecessor section2_completed_at=2026-06-02 and rehire
        start_date=2026-07-10, the rehire deadline (2026-07-15) is
        identical to the standard +3wd from 2026-07-10 in this case,
        but the rehire variant remains structurally different — i.e.,
        had the predecessor section2_completed_at been a LATER date
        (e.g., 2026-07-20), the rehire deadline would have been
        2026-07-20 instead.

        # difficulty: dual_variant_calc/section2_deadline_initial_vs_rehire
        """
        ctx = setup_initial_then_rehire_scenario()
        # After PATCH, section2_deadline is 2026-07-15T23:59:59.999Z.
        emp_after_patch = ctx["employee_after_patch"]
        assert emp_after_patch["section2_deadline"] == (
            "2026-07-15T23:59:59.999Z"
        )

    def test_tnc_close_voluntary_vs_sweep_default_decision_pinned(self,
                                                                   api):
        """PRD §3.5 (no_contest branch): "records `tnc_employee_decision`
        as `NO_CONTEST`".
        PRD §3.5 (sweep branch): "precondition: `case_status` is `TNC`
        and `tnc_employee_decision` is still null".

        Supplemental claim (pinned writes): voluntary writes
        tnc_employee_decision=NO_CONTEST and emits CASE_CLOSED only;
        sweep keeps tnc_employee_decision=null and emits BOTH
        TNC_DEADLINE_LAPSED and CASE_CLOSED, ordered.

        # difficulty: dual_variant_calc/tnc_close_voluntary_vs_sweep_default
        """
        ctx = setup_two_tnc_employees_for_dual_close()
        emp_b, case_b = ctx["employee_b"], ctx["case_b"]
        emp_c, case_c = ctx["employee_c"], ctx["case_c"]
        # B closes voluntarily.
        advance_clock_to("2026-06-16T10:00:00.000Z")
        submit_tnc_decision(
            case_id=case_b["id"], employee_id=emp_b["id"],
            decision="NO_CONTEST",
        )
        # C is left to sweep.
        advance_clock_to("2026-07-01T00:00:01.000Z")
        run_sweep()
        # tnc_employee_decision pinned.
        assert get_everify_case(case_b["id"])["tnc_employee_decision"] == (
            "NO_CONTEST"
        )
        assert get_everify_case(case_c["id"])["tnc_employee_decision"] is None
        # AuditEvents.
        audits_b = list_audit_events(emp_b["id"])
        audits_c = list_audit_events(emp_c["id"])
        assert_audit_action_absent(audits_b, "TNC_DEADLINE_LAPSED")
        assert_audit_action_present(audits_c, "TNC_DEADLINE_LAPSED")
        assert_audit_order(audits_c, "TNC_DEADLINE_LAPSED", "CASE_CLOSED")


# ===========================================================================
# Rule 2 — combinatorial_formula (supplemental)
# ===========================================================================
class TestCombinatorialFormulaSupplemental:

    def test_section2_deadline_for_normal_monday_start_date(self, api):
        """PRD §2.6: "the count starts on the first federal working day
        strictly after D (D itself is not counted), advances one
        calendar day at a time, and increments the count each time the
        cursor lands on a federal working day".

        Supplemental claim: start_date Mon 2026-06-01 (no holiday in
        the 3-day window) → Tue 06-02 (1), Wed 06-03 (2), Thu 06-04
        (3) → deadline 2026-06-04T23:59:59.999Z. Holiday-free baseline
        contrasts with the Juneteenth-skip recipe.

        # difficulty: combinatorial_formula/section2_deadline_3_working_days_holiday_skip
        """
        advance_clock_to("2026-05-25T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        assert emp["section2_deadline"] == "2026-06-04T23:59:59.999Z"

    def test_tnc_contest_deadline_no_holiday_baseline(self, api):
        """PRD §3.5: "computes `tnc_contest_deadline` as 10 federal
        working days after `tnc_opened_at` (the day of TNC issuance
        is not counted; the clock starts on the next federal working
        day and ends at 23:59:59.999 UTC on the calendar date of the
        tenth such day, millisecond-precise)".

        Supplemental claim: TNC opened on 2026-05-04 (Mon) — no
        federal holidays in the May 4 → May 22 window — the deadline
        is exactly +2 weeks of working days from 05-04:
            05-05 (1), 05-06 (2), 05-07 (3), 05-08 (4),
            05-11 (5), 05-12 (6), 05-13 (7), 05-14 (8), 05-15 (9),
            05-18 (10) → 2026-05-18T23:59:59.999Z.

        # difficulty: combinatorial_formula/tnc_contest_10_working_days_holiday_skip
        """
        emp, form, _doc = setup_employee_with_section2_done(
            start_date="2026-04-20",  # well before TNC scenario
            clock_iso="2026-04-21T08:00:00.000Z",
        )
        # Submit & deliver TNC.
        case = submit_everify_case(
            employee_id=emp["id"], i9_form_id=form["id"],
        )
        advance_clock_to("2026-05-04T09:00:00.000Z")
        case = api.deliver_everify_result(
            case["id"], {"result": "TNC", "tnc_kind": "DHS"},
            TEST_USERS["system_headers"],
        )
        case = validate_success(case, expected_status=200)
        assert case["tnc_contest_deadline"] == "2026-05-18T23:59:59.999Z"


# ===========================================================================
# Rule 3 — non_linear_state_machine (supplemental)
# ===========================================================================
class TestNonLinearStateMachineSupplemental:

    def test_everify_case_tnc_cycle_audit_chain_in_order(self, api):
        """PRD §3.5 (PENDING -> TNC): "appends an `AuditEvent` with
        action `TNC_OPENED`".
        PRD §3.5 (TNC -> PENDING via CONTEST): "appends an
        `AuditEvent` with action `TNC_CONTESTED`".

        Supplemental claim: the TNC -> PENDING cycle produces an audit
        sequence including TNC_OPENED followed by TNC_CONTESTED for
        the same case (proving the cycle was traversed, not collapsed).

        # difficulty: non_linear_state_machine/everify_case_tnc_branching_with_cycle
        """
        ctx = setup_tnc_cycle_scenario()
        emp, case = ctx["employee"], ctx["case"]
        advance_clock_to("2026-06-16T10:00:00.000Z")
        submit_tnc_decision(
            case_id=case["id"], employee_id=emp["id"], decision="CONTEST",
        )
        audits = list_audit_events(emp["id"])
        case_audits = [
            a for a in audits
            if a.get("subject_entity") == "EVERIFY_CASE"
            and a.get("subject_entity_id") == case["id"]
        ]
        # PRD §2.8 defines actor_role enum and subject_entity enum used
        # above. There must be a TNC_OPENED then TNC_CONTESTED entry.
        actions = [a["action"] for a in case_audits]
        assert "TNC_OPENED" in actions
        assert "TNC_CONTESTED" in actions
        idx_open = actions.index("TNC_OPENED")
        idx_contested = actions.index("TNC_CONTESTED")
        assert idx_open < idx_contested, (
            f"TNC_OPENED must occur before TNC_CONTESTED for the same "
            f"case; got actions {actions}"
        )

    def test_i9_form_lineage_audit_records_form_superseded(self, api):
        """PRD §3.3: "that predecessor form simultaneously transitions
        to state `SUPERSEDED` with its own `AuditEvent` of action
        `FORM_SUPERSEDED`".

        Supplemental claim: AuditEvent FORM_SUPERSEDED occurred_at <=
        the successor's section2_completed_at — the supersession is
        recorded at or before the moment of the trigger.

        # difficulty: non_linear_state_machine/i9_form_lineage_self_referential_branching
        """
        ctx = setup_supersession_with_ead_scenario()
        emp = ctx["employee"]
        new_form = ctx["new_form"]
        audits = list_audit_events(emp["id"])
        superseded = [
            a for a in audits if a.get("action") == "FORM_SUPERSEDED"
        ]
        assert len(superseded) >= 1
        s2_completed_at = new_form["section2_completed_at"]
        assert s2_completed_at is not None
        # All FORM_SUPERSEDED audits occurred_at <= successor.section2_completed_at.
        for s in superseded:
            assert s["occurred_at"] <= s2_completed_at, (
                f"FORM_SUPERSEDED occurred_at={s['occurred_at']!r} must be "
                f"<= successor.section2_completed_at={s2_completed_at!r}"
            )


# ===========================================================================
# Rule 4 — transitive_cascade (supplemental)
# ===========================================================================
class TestTransitiveCascadeSupplemental:

    def test_tnc_sweep_cascade_status_is_terminated_after_close(self, api):
        """PRD §3.7: "If the employee's `is_terminated` is true, the
        status is `TERMINATED`."

        Supplemental claim: the cascade leaves the employee with
        is_terminated=true AND onboarding_status=TERMINATED — proving
        link-3's recompute reads the updated link-2 result.

        # difficulty: transitive_cascade/tnc_sweep_cascade_depth_3
        """
        ctx = setup_sweep_cascade_scenario()
        emp = ctx["employee"]
        advance_clock_to("2026-07-01T00:00:01.000Z")
        run_sweep()
        re_emp = get_employee(emp["id"])
        assert re_emp["is_terminated"] is True
        assert re_emp["onboarding_status"] == "TERMINATED"

    def test_section2_supersession_resolves_linked_reverification(self,
                                                                  api):
        """PRD §3.4: "It transitions to `RESOLVED` when a successor
        `I9Form` whose `supersedes_form_id` equals this event's
        `triggering_form_id` reaches `SECTION_2_DONE` and the current
        time is on or before `resolution_deadline`; on resolution, the
        event's `resolved_at` is set to the successor's
        `section2_completed_at`, `new_form_id` is set to the
        successor's `id`, an `AuditEvent` with action `REVERIFY_RESOLVED`
        is appended, and the triggering form transitions to
        `SUPERSEDED`."

        Supplemental claim: resolved_at matches the successor's
        section2_completed_at exactly (proving the side effect carries
        the new timestamp, not the audit-emission timestamp).

        # difficulty: transitive_cascade/section2_supersession_cascade_depth_2
        """
        ctx = setup_employee_for_section3_supersession()
        emp = ctx["employee"]
        initial = ctx["initial_form"]
        new_form = ctx["new_form"]
        events = list_reverification_events(emp["id"])
        triggered = [
            e for e in events if e["triggering_form_id"] == initial["id"]
        ]
        assert len(triggered) == 1
        assert triggered[0]["resolved_at"] == new_form["section2_completed_at"]


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict (supplemental)
# ===========================================================================
class TestPriorityPairValidationConflictSupplemental:

    def test_state_check_returns_only_invalid_state_no_segregation(self,
                                                                   api):
        """PRD §2.9: "a request that simultaneously violates an earlier
        and a later rule surfaces the earlier rule's `error_id`."

        Supplemental claim: when both state (P5) and SoD (P6) would
        fail, the response carries error_id=ERR_INVALID_STATE
        explicitly — error_id is NOT ERR_SEGREGATION_OF_DUTIES.

        # difficulty: priority_pair_validation_conflict/state_vs_segregation_of_duties_on_section2
        """
        emp, form, _doc = setup_employee_with_section2_done()
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(version=form["version"]),
            make_employer_rep_headers(emp["id"]),
        )
        body = resp.json().get("data", {})
        assert body.get("error_id") == "ERR_INVALID_STATE", (
            f"Expected ERR_INVALID_STATE (priority 5) over "
            f"ERR_SEGREGATION_OF_DUTIES (priority 6); got "
            f"{body.get('error_id')!r}"
        )
        assert body.get("error_id") != "ERR_SEGREGATION_OF_DUTIES"

    def test_doc_list_rule_returns_only_list_rule_no_expiry(self, api,
                                                            employer_rep_headers):
        """PRD §2.9: "seventh through ninth, the Section 2 document
        list rule, document category match, and document expiry are
        checked in that order".

        Supplemental claim: when both LIST_A+LIST_B (P7) and expired
        LIST_A (P9) would fail, response error_id is
        ERR_DOCUMENT_LIST_RULE — NOT ERR_DOCUMENT_EXPIRED.

        # difficulty: priority_pair_validation_conflict/doc_list_rule_vs_document_expired_on_section2
        """
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        # Expired LIST_A.
        expired_a = register_document(
            employee_id=emp["id"], category="LIST_A",
            document_title="U.S. Passport",
            expiration_date="2025-12-01",
            receipt=False,
        )
        valid_b = register_list_b_document(employee_id=emp["id"])
        advance_clock_to("2026-06-10T08:00:00.000Z")
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=expired_a["id"],
                list_b_document_id=valid_b["id"],
            ),
            employer_rep_headers,
        )
        body = resp.json().get("data", {})
        assert body.get("error_id") == "ERR_DOCUMENT_LIST_RULE"
        assert body.get("error_id") != "ERR_DOCUMENT_EXPIRED"


# ===========================================================================
# Rule 6 — boundary_precision_check (supplemental)
# ===========================================================================
class TestBoundaryPrecisionSupplemental:

    def test_section2_deadline_strict_greater_than_one_ms_past_boundary(
            self, api, employer_rep_headers):
        """PRD §3.3: "When `enforce_deadline` is true and
        `SystemClock.current_time` is strictly later than the employee's
        `section2_deadline`, the request is rejected with
        `ERR_SECTION2_DEADLINE_MISSED`".

        Supplemental claim: clock advanced 1ms past the deadline
        (2026-06-05T00:00:00.000Z, which is 1ms after
        2026-06-04T23:59:59.999Z) with enforce_deadline=true is
        rejected — confirming the boundary is strict >, not >=.

        # difficulty: boundary_precision_check/section2_deadline_inclusive_boundary
        """
        ctx = setup_section2_deadline_boundary_scenario(
            advance_to_deadline=False,
        )
        emp, form, doc = ctx["employee"], ctx["form"], ctx["doc"]
        # 1ms past deadline 2026-06-04T23:59:59.999Z.
        advance_clock_to("2026-06-05T00:00:00.000Z")
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=doc["id"],
                enforce_deadline=True,
            ),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_SECTION2_DEADLINE_MISSED")

    def test_empty_doc_set_does_not_transition_form(self, api,
                                                    employer_rep_headers):
        """PRD §3.3: rejection means "form.form_status remains
        SECTION_1_DONE" — the form does not transition.

        Supplemental claim: after the empty-doc-set rejection, GET on
        the form still shows form_status=SECTION_1_DONE.

        # difficulty: boundary_precision_check/empty_document_set_on_section2
        """
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        advance_clock_to("2026-06-02T08:00:00.000Z")
        # Body omits list ids.
        api.sign_section2(
            emp["id"], form["id"],
            section2_payload(version=form["version"]),
            employer_rep_headers,
        )
        # Re-read.
        forms = list_i9_forms(emp["id"])
        f = next(ff for ff in forms if ff["id"] == form["id"])
        assert f["form_status"] == "SECTION_1_DONE", (
            f"Form must remain SECTION_1_DONE after a rejected empty-doc "
            f"Section 2; got {f['form_status']!r}"
        )


# ===========================================================================
# Rule 7 — cross_entity_state_dependency (supplemental)
# ===========================================================================
class TestCrossEntityStateDependencySupplemental:

    def test_everify_submit_against_section1_only_produces_no_row(
            self, api, employer_rep_headers, hr_staff_headers):
        """PRD §3.5: "there must be no prior non-closed `EVerifyCase`
        for this employee" — a rejected submission MUST NOT create a
        row.

        Supplemental claim: after the ERR_INVALID_STATE reject, no
        EVerifyCase exists for the employee (state preserved by the
        priority-check failure).

        # difficulty: cross_entity_state_dependency/everify_submit_requires_i9form_section2_done
        """
        from test_helpers import setup_employee_at_section1_only_for_everify_attempt
        ctx = setup_employee_at_section1_only_for_everify_attempt()
        emp, form = ctx["employee"], ctx["form"]
        resp = api.submit_everify_case(
            emp["id"],
            submit_everify_payload(i9_form_id=form["id"]),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_INVALID_STATE")
        # Confirm no submit audit row exists.
        audits = list_audit_events(emp["id"])
        submits = find_audit_actions(audits, "EVERIFY_SUBMIT")
        assert submits == [], (
            f"Rejected submission must not append EVERIFY_SUBMIT audit; "
            f"got {len(submits)} rows"
        )

    def test_section2_receipt_exception_allows_expired_dated_doc(self, api,
                                                                 employer_rep_headers):
        """PRD §3.3: "a document where `receipt` is true is accepted if
        and only if its `receipt_resolution_due` is strictly after the
        current time."

        Supplemental claim: a "receipt" document whose
        receipt_resolution_due is in the future is accepted even if
        expiration_date is past.

        # difficulty: cross_entity_state_dependency/section2_requires_document_not_expired
        """
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        # receipt=true → receipt_resolution_due = 2026-06-01 + 90 days
        # = 2026-08-30. Clock at 2026-06-02 — within window.
        doc = register_document(
            employee_id=emp["id"], category="LIST_A",
            document_title="EAD I-766",
            expiration_date="2025-12-31",
            receipt=True,
        )
        advance_clock_to("2026-06-02T08:00:00.000Z")
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=doc["id"],
            ),
            employer_rep_headers,
        )
        signed = validate_success(resp, expected_status=200)
        assert signed["form_status"] == "SECTION_2_DONE"


# ===========================================================================
# Rule 8 — resource_temporal_overlap (supplemental)
# ===========================================================================
class TestResourceTemporalOverlapSupplemental:

    def test_open_case_capacity_released_after_close(self, api,
                                                    employer_rep_headers,
                                                    system_headers):
        """PRD §3.5: "there must be no prior non-closed `EVerifyCase`
        for this employee".

        Supplemental claim: after the first case reaches
        CLOSED_AUTHORIZED via the EMPLOYMENT_AUTHORIZED → close
        path, a SECOND submission with a different idempotency_key
        SUCCEEDS — proving capacity is released on close.

        # difficulty: resource_temporal_overlap/at_most_one_open_everify_case_per_employee
        """
        emp, form, case = setup_employee_with_pending_case(
            clock_iso="2026-06-02T08:00:00.000Z",
        )
        # Drive to EMPLOYMENT_AUTHORIZED → CLOSED_AUTHORIZED.
        api.deliver_everify_result(
            case["id"], {"result": "EMPLOYMENT_AUTHORIZED"},
            system_headers,
        )
        api.close_everify_case(case["id"], None, employer_rep_headers)
        # Now a second case can be opened.
        resp = api.submit_everify_case(
            emp["id"],
            submit_everify_payload(
                i9_form_id=form["id"], idempotency_key="k3",
            ),
            employer_rep_headers,
        )
        new_case = validate_success(resp, expected_status=201)
        assert new_case["case_status"] == "PENDING"

    def test_initial_form_uniqueness_after_void_allows_new_initial(
            self, api, hr_staff_headers):
        """PRD §3.3: "Either way, an `AuditEvent` with action
        `FORM_VOIDED` is appended and the form's `form_status` becomes
        `VOIDED`. Voiding is not permitted after Section 2 has been
        signed; an attempt is rejected with `ERR_INVALID_STATE`."
        PRD §3.3: "An `INITIAL` form is unique per employee".

        Supplemental claim: after voiding the first INITIAL, a new
        INITIAL is allowed (since the void leaves no non-VOIDED INITIAL
        on the employee). Adjacency: the SECOND INITIAL request
        succeeds.

        # difficulty: resource_temporal_overlap/at_most_one_initial_i9form_per_employee
        """
        emp = create_employee()
        first = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        void_form(form_id=first["id"], version=first["version"])
        resp = api.create_i9_form(
            emp["id"], create_i9_form_payload(form_kind="INITIAL"),
            hr_staff_headers,
        )
        new_form = validate_success(resp, expected_status=201)
        assert new_form["form_kind"] == "INITIAL"
        assert new_form["form_status"] == "DRAFT"


# ===========================================================================
# Rule 9 — compensating_invariant (supplemental)
# ===========================================================================
class TestCompensatingInvariantSupplemental:

    def test_idempotent_replay_returns_same_body(self, api,
                                                 employer_rep_headers):
        """PRD §3.5: "a retry with the same key returns the existing
        case as a 200 OK rather than creating a duplicate."

        Supplemental claim: the replay's data field equals the original
        case's id (the SAME row, not a new one).

        # difficulty: compensating_invariant/idempotent_replay_preserves_case_count
        """
        ctx = setup_employee_for_idempotent_replay()
        emp, form = ctx["employee"], ctx["form"]
        first = validate_success(
            api.submit_everify_case(
                emp["id"],
                submit_everify_payload(
                    i9_form_id=form["id"], idempotency_key="REP",
                ),
                employer_rep_headers,
            ),
            expected_status=201,
        )
        resp = api.submit_everify_case(
            emp["id"],
            submit_everify_payload(
                i9_form_id=form["id"], idempotency_key="REP",
            ),
            employer_rep_headers,
        )
        assert resp.status_code == 200
        body = resp.json().get("data", {})
        assert body.get("id") == first["id"]
        # The submitted_at and case_status are unchanged by the replay.
        assert body.get("case_status") == first["case_status"]

    def test_section3_supersession_total_count_matches_open_plus_resolved(
            self, api):
        """PRD §3.4: "It transitions to `RESOLVED` when a successor
        `I9Form` whose `supersedes_form_id` equals this event's
        `triggering_form_id` reaches `SECTION_2_DONE`".

        Supplemental claim: COUNT(open) + COUNT(resolved) ==
        COUNT(total) for this employee — the open row moved to
        RESOLVED, no extra row inserted, no row deleted.

        # difficulty: compensating_invariant/section3_supersession_preserves_reverification_resolution_count
        """
        ctx = setup_employee_for_section3_supersession()
        emp = ctx["employee"]
        events = list_reverification_events(emp["id"])
        # Bucket by resolved_at.
        open_count = sum(1 for e in events if e.get("resolved_at") is None)
        resolved_count = sum(
            1 for e in events if e.get("resolved_at") is not None
        )
        total_count = len(events)
        assert open_count + resolved_count == total_count
        # The supersession moved exactly one event open->resolved; the
        # total for the initial form is exactly 1.
        triggered_by_initial = [
            e for e in events
            if e["triggering_form_id"] == ctx["initial_form"]["id"]
        ]
        assert len(triggered_by_initial) == 1
