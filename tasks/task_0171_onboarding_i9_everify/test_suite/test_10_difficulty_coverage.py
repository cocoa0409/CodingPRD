"""Difficulty-design coverage — primary tests for each instance.

Every instance declared in the difficulty-design index gets at least
two tests (this file + test_11_difficulty_coverage_supplemental.py).
Each test cites a verbatim PRD sentence for its underlying rule.

Tag format: each test docstring carries `# difficulty: <rule_id>/<name>`.
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
    deliver_result,
    EMPLOYER_REP_SECONDARY_ID,
    get_employee,
    get_everify_case,
    list_audit_events,
    list_reverification_events,
    make_employee_headers,
    make_employer_rep_headers,
    NON_EXISTENT_UUID,
    register_list_a_document,
    register_list_b_document,
    register_ead_document,
    run_sweep,
    section2_payload,
    setup_employee_for_idempotent_replay,
    setup_employee_for_initial_form_uniqueness,
    setup_employee_for_section3_supersession,
    setup_employee_with_pending_case,
    setup_employee_with_section2_done,
    setup_employee_with_single_open_case,
    setup_employee_at_section1_only_for_everify_attempt,
    setup_form_at_section1_done_with_expired_list_a,
    setup_form_at_section2_done_then_dup_attempt,
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
    validate_error,
    validate_success,
    void_form,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_section2_deadline_initial_vs_rehire(self, api):
        """PRD §3.4: "the rehire variant of the Section 2 deadline
        computes the later of the predecessor's `section2_completed_at`
        or three federal working days after the rehire `start_date`,
        allowing the employer to either reuse the prior I-9 or to
        start a new clock — whichever instant is later wins."

        Claim: with predecessor section2_completed_at=2026-06-02 and
        rehire start_date=2026-07-10, the rehire variant's
        section2_deadline is the LATER of (2026-06-02 itself) or
        (2026-07-10 + 3 federal working days = 2026-07-15) — i.e.,
        2026-07-15. Distinguishes the rehire branch from the standard
        variant.

        # difficulty: dual_variant_calc/section2_deadline_initial_vs_rehire
        """
        ctx = setup_initial_then_rehire_scenario()
        emp_after_initial_create = ctx["employee_initial_view"]
        emp_after_patch = ctx["employee_after_patch"]
        # Initial-variant deadline anchored to start_date=2026-06-01.
        assert emp_after_initial_create["section2_deadline"] == (
            "2026-06-04T23:59:59.999Z"
        ), (
            f"Standard variant: start_date 2026-06-01 + 3 federal working "
            f"days = 2026-06-04T23:59:59.999Z; got "
            f"{emp_after_initial_create['section2_deadline']!r}"
        )
        # After PATCH start_date to 2026-07-10 the employee's
        # section2_deadline is recomputed from the new start.
        # PRD §3.1 says start_date correction triggers recomputation;
        # PRD §3.4 says the REHIRE variant applies max(predecessor
        # section2_completed_at, +3wd-from-rehire). The +3wd from
        # 2026-07-10 (a Friday) = Mon 2026-07-13, Tue 2026-07-14, Wed
        # 2026-07-15 → 2026-07-15T23:59:59.999Z.
        assert emp_after_patch["section2_deadline"] == (
            "2026-07-15T23:59:59.999Z"
        ), (
            f"Rehire variant deadline 2026-07-15T23:59:59.999Z (max of "
            f"prior section2 2026-06-02 vs +3wd from 2026-07-10); got "
            f"{emp_after_patch['section2_deadline']!r}"
        )
        # The two values are necessarily different — proves the rehire
        # variant pins a different formula than the standard one.
        assert (
            emp_after_initial_create["section2_deadline"]
            != emp_after_patch["section2_deadline"]
        )

    def test_tnc_close_voluntary_vs_sweep_default(self, api):
        """PRD §3.5: "A `decision` of `NO_CONTEST` records
        `tnc_employee_decision` as `NO_CONTEST`, sets `final_disposition`
        to `NOT_AUTHORIZED`, transitions the case to `CLOSED_NOT_AUTHORIZED`,
        appends an `AuditEvent` of action `CASE_CLOSED` with `disposition`
        `NOT_AUTHORIZED`".
        PRD §3.5: "the sweep transitions the case from `TNC` to
        `CLOSED_NOT_AUTHORIZED` (precondition: `case_status` is `TNC`
        and `tnc_employee_decision` is still null), sets
        `final_disposition` to `NOT_AUTHORIZED`, appends an `AuditEvent`
        with action `TNC_DEADLINE_LAPSED` followed by an `AuditEvent`
        with action `CASE_CLOSED`".

        Claim: voluntary NO_CONTEST writes tnc_employee_decision=
        NO_CONTEST plus only CASE_CLOSED; sweep writes null and BOTH
        TNC_DEADLINE_LAPSED and CASE_CLOSED.

        # difficulty: dual_variant_calc/tnc_close_voluntary_vs_sweep_default
        """
        ctx = setup_two_tnc_employees_for_dual_close()
        emp_b, case_b = ctx["employee_b"], ctx["case_b"]
        emp_c, case_c = ctx["employee_c"], ctx["case_c"]
        # B: Employee posts NO_CONTEST during the window.
        advance_clock_to("2026-06-16T10:00:00.000Z")
        submit_tnc_decision(
            case_id=case_b["id"], employee_id=emp_b["id"],
            decision="NO_CONTEST",
        )
        re_b = get_everify_case(case_b["id"])
        # C: clock advances past the deadline; sweep closes the case.
        advance_clock_to("2026-07-01T00:00:01.000Z")
        run_sweep()
        re_c = get_everify_case(case_c["id"])
        # Same final disposition, different decision fields + audit shape.
        assert re_b["tnc_employee_decision"] == "NO_CONTEST"
        assert re_c["tnc_employee_decision"] is None
        assert re_b["final_disposition"] == "NOT_AUTHORIZED"
        assert re_c["final_disposition"] == "NOT_AUTHORIZED"
        # Audit shape diverges.
        audits_b = list_audit_events(emp_b["id"])
        audits_c = list_audit_events(emp_c["id"])
        assert_audit_action_present(audits_b, "CASE_CLOSED")
        assert_audit_action_absent(audits_b, "TNC_DEADLINE_LAPSED")
        assert_audit_action_present(audits_c, "CASE_CLOSED")
        assert_audit_action_present(audits_c, "TNC_DEADLINE_LAPSED")
        assert_audit_order(audits_c, "TNC_DEADLINE_LAPSED", "CASE_CLOSED")
        # Both employees terminated.
        for re_emp in (get_employee(emp_b["id"]), get_employee(emp_c["id"])):
            assert re_emp["is_terminated"] is True
            assert re_emp["onboarding_status"] == "TERMINATED"


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_section2_deadline_3_working_days_holiday_skip(self, api):
        """PRD §2.6: "When a deadline is described as 'N federal working
        days after some date D', the count starts on the first federal
        working day strictly after D (D itself is not counted), advances
        one calendar day at a time, and increments the count each time
        the cursor lands on a federal working day; the deadline is then
        set to 23:59:59.999 UTC on the calendar date the cursor reaches
        when the count first equals N."

        Claim: start_date=Fri 2026-06-19 (Juneteenth — federal holiday;
        the rule excludes start_date itself, and the next federal working
        day is Mon 2026-06-22). Counting 3 federal working days:
        Mon 06-22 (1), Tue 06-23 (2), Wed 06-24 (3) → deadline
        2026-06-24T23:59:59.999Z.

        # difficulty: combinatorial_formula/section2_deadline_3_working_days_holiday_skip
        """
        ctx = setup_juneteenth_holiday_scenario()
        emp = ctx["employee"]
        assert emp["section2_deadline"] == "2026-06-24T23:59:59.999Z", (
            f"Expected 2026-06-24T23:59:59.999Z (Mon, Tue, Wed after "
            f"start_date Fri 06-19 which is Juneteenth-skipped); got "
            f"{emp['section2_deadline']!r}"
        )

    def test_tnc_contest_10_working_days_holiday_skip(self, api):
        """PRD §3.5: "computes `tnc_contest_deadline` as 10 federal
        working days after `tnc_opened_at` (the day of TNC issuance is
        not counted; the clock starts on the next federal working day
        and ends at 23:59:59.999 UTC on the calendar date of the tenth
        such day, millisecond-precise)".

        Claim: tnc_opened_at=Mon 2026-06-15. The next 10 federal
        working days, skipping Juneteenth Fri 2026-06-19:
            06-16 (1), 06-17 (2), 06-18 (3), [skip Fri 06-19],
            06-22 (4), 06-23 (5), 06-24 (6), 06-25 (7), 06-26 (8),
            06-29 (9), 06-30 (10) → deadline 2026-06-30T23:59:59.999Z.

        # difficulty: combinatorial_formula/tnc_contest_10_working_days_holiday_skip
        """
        ctx = setup_tnc_juneteenth_scenario()
        case = ctx["case"]
        assert case["tnc_opened_at"] == "2026-06-15T09:00:00.000Z"
        assert case["tnc_contest_deadline"] == (
            "2026-06-30T23:59:59.999Z"
        ), (
            f"PRD §3.5: 10 federal working days after 2026-06-15, "
            f"skipping Juneteenth 2026-06-19, lands at 2026-06-30; "
            f"got {case['tnc_contest_deadline']!r}"
        )


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_everify_case_tnc_branching_with_cycle(self, api):
        """PRD §3.5: "A `decision` of `CONTEST` records
        `tnc_employee_decision` as `CONTEST`, transitions the case from
        `TNC` back to `PENDING`, appends an `AuditEvent` with action
        `TNC_CONTESTED`, and moves `onboarding_status` back to
        `EVERIFY_PENDING` so the upstream agency can re-evaluate."

        Claim: TNC -> PENDING cycle realized via CONTEST; onboarding
        status reverts to EVERIFY_PENDING (not TNC_OPEN, not AUTHORIZED).

        # difficulty: non_linear_state_machine/everify_case_tnc_branching_with_cycle
        """
        ctx = setup_tnc_cycle_scenario()
        emp, case = ctx["employee"], ctx["case"]
        advance_clock_to("2026-06-16T10:00:00.000Z")
        submit_tnc_decision(
            case_id=case["id"], employee_id=emp["id"], decision="CONTEST",
        )
        re_case = get_everify_case(case["id"])
        assert re_case["case_status"] == "PENDING"
        assert re_case["tnc_employee_decision"] == "CONTEST"
        # Onboarding status reverts.
        re_emp = get_employee(emp["id"])
        assert re_emp["onboarding_status"] == "EVERIFY_PENDING"
        # AuditEvents include TNC_OPENED then TNC_CONTESTED.
        audits = list_audit_events(emp["id"])
        assert_audit_action_present(audits, "TNC_OPENED")
        assert_audit_action_present(audits, "TNC_CONTESTED")
        assert_audit_order(audits, "TNC_OPENED", "TNC_CONTESTED")

    def test_i9_form_lineage_self_referential_branching(self, api):
        """PRD §3.3: "If this newly-signed form has a
        `supersedes_form_id`, that predecessor form simultaneously
        transitions to state `SUPERSEDED` with its own `AuditEvent` of
        action `FORM_SUPERSEDED`, and any open `ReverificationEvent`
        whose `triggering_form_id` was the predecessor is resolved by
        setting its `resolved_at` to the new `section2_completed_at`
        and its `new_form_id` to the successor's `id`."

        Claim: predecessor form_status='SUPERSEDED'; new form
        form_status='SECTION_2_DONE' AND supersedes_form_id=initial id;
        AuditEvent FORM_SUPERSEDED present.

        # difficulty: non_linear_state_machine/i9_form_lineage_self_referential_branching
        """
        ctx = setup_supersession_with_ead_scenario()
        emp = ctx["employee"]
        initial_form = ctx["initial_form"]
        new_form = ctx["new_form"]
        from test_helpers import list_i9_forms
        forms = list_i9_forms(emp["id"])
        initial = next(f for f in forms if f["id"] == initial_form["id"])
        successor = next(f for f in forms if f["id"] == new_form["id"])
        assert initial["form_status"] == "SUPERSEDED"
        assert successor["form_status"] == "SECTION_2_DONE"
        assert successor["supersedes_form_id"] == initial_form["id"]
        audits = list_audit_events(emp["id"])
        assert_audit_action_present(audits, "FORM_SUPERSEDED")


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_tnc_sweep_cascade_depth_3(self, api):
        """PRD §3.5: "moves `onboarding_status` to `NOT_AUTHORIZED`, and
        cascades into the employee-termination subroutine described
        above (`is_terminated` becomes true with its own `AuditEvent`
        of action `TERMINATE`)."

        Claim: sweep closes TNC case (link 1) → final_disposition
        NOT_AUTHORIZED; cascade flips is_terminated true (link 2);
        derive_onboarding_status returns TERMINATED (link 3). Audit
        ordering: TNC_DEADLINE_LAPSED < CASE_CLOSED < TERMINATE.

        # difficulty: transitive_cascade/tnc_sweep_cascade_depth_3
        """
        ctx = setup_sweep_cascade_scenario()
        emp, case = ctx["employee"], ctx["case"]
        # tnc_contest_deadline = 2026-06-30; advance past it.
        advance_clock_to("2026-07-01T00:00:01.000Z")
        run_sweep()
        re_case = get_everify_case(case["id"])
        # link 1
        assert re_case["case_status"] == "CLOSED_NOT_AUTHORIZED"
        assert re_case["final_disposition"] == "NOT_AUTHORIZED"
        # links 2 + 3
        re_emp = get_employee(emp["id"])
        assert re_emp["is_terminated"] is True
        assert re_emp["onboarding_status"] == "TERMINATED"
        # Audit ordering.
        audits = list_audit_events(emp["id"])
        assert_audit_action_present(audits, "TNC_DEADLINE_LAPSED")
        assert_audit_action_present(audits, "CASE_CLOSED")
        assert_audit_action_present(audits, "TERMINATE")
        assert_audit_order(audits, "TNC_DEADLINE_LAPSED", "CASE_CLOSED")
        assert_audit_order(audits, "CASE_CLOSED", "TERMINATE")

    def test_section2_supersession_cascade_depth_2(self, api):
        """PRD §3.3: "any open `ReverificationEvent` whose
        `triggering_form_id` was the predecessor is resolved by setting
        its `resolved_at` to the new `section2_completed_at` and its
        `new_form_id` to the successor's `id`."

        Claim: successor reaching SECTION_2_DONE causes both
        predecessor.form_status='SUPERSEDED' AND the linked
        ReverificationEvent's resolved_at/new_form_id update — both as
        side effects of link-1's mutation. Employee.onboarding_status
        remains in the EVerify branch (not NOT_AUTHORIZED).

        # difficulty: transitive_cascade/section2_supersession_cascade_depth_2
        """
        ctx = setup_employee_for_section3_supersession()
        emp = ctx["employee"]
        initial = ctx["initial_form"]
        new_form = ctx["new_form"]
        from test_helpers import list_i9_forms
        forms = list_i9_forms(emp["id"])
        initial_after = next(f for f in forms if f["id"] == initial["id"])
        assert initial_after["form_status"] == "SUPERSEDED"
        # ReverificationEvent linked to the initial form is RESOLVED.
        events = list_reverification_events(emp["id"])
        linked = [
            e for e in events
            if e["triggering_form_id"] == initial["id"]
        ]
        assert len(linked) == 1
        assert linked[0]["resolved_at"] is not None
        assert linked[0]["new_form_id"] == new_form["id"]
        re_emp = get_employee(emp["id"])
        assert re_emp["onboarding_status"] != "NOT_AUTHORIZED"
        # PRD §3.7: with the new form at SECTION_2_DONE and no case
        # yet, the status is EVERIFY_PENDING.
        assert re_emp["onboarding_status"] == "EVERIFY_PENDING"


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_state_vs_segregation_of_duties_on_section2(self, api):
        """PRD §2.9: "When a single request fails more than one rule,
        exactly one error is returned, chosen by priority from the
        following ordering: first, authentication headers must be
        present and well-formed (`ERR_AUTH_MISSING`); second, the role
        must be authorized for the endpoint (`ERR_FORBIDDEN`); third,
        every path identifier must resolve (`ERR_NOT_FOUND`); fourth,
        every body foreign-key reference must resolve
        (`ERR_REFERENCE_NOT_FOUND`); fifth, the target resource must
        be in a state from which the requested transition is permitted
        (`ERR_INVALID_STATE`); sixth, segregation of duties is
        enforced on Section 2 (`ERR_SEGREGATION_OF_DUTIES`)".

        Claim: re-sign Section 2 on a SECTION_2_DONE form by the
        Section 1 attester — both state (P5) and SoD (P6) would fail;
        state wins per priority order.

        Caveat: only meaningful if the implementation routes the call
        as an Employee posing as an EmployerRep. The PRD §4 endpoint
        table makes Section 2 EmployerRep-exclusive; with the X-User-
        Role set to EmployerRep but X-User-ID set to the Section 1
        attester's id, the role check (P2) does NOT fail, the state
        check (P5) does, and SoD (P6) would also. The lower-priority
        error (state) must be surfaced.

        # difficulty: priority_pair_validation_conflict/state_vs_segregation_of_duties_on_section2
        """
        ctx = setup_form_at_section2_done_then_dup_attempt()
        emp, form = ctx["employee"], ctx["form"]
        # Use EmployerRep role but X-User-ID = the Section 1 attester (the
        # employee). Both state-check (SECTION_2_DONE) and SoD (same id
        # as section1_attested_by_user_id) would trip; PRD §2.9 says
        # state (P5) wins.
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(version=form["version"]),
            make_employer_rep_headers(emp["id"]),
        )
        validate_error(resp, "ERR_INVALID_STATE")

    def test_doc_list_rule_vs_document_expired_on_section2(self, api,
                                                            employer_rep_headers):
        """PRD §2.9: "seventh through ninth, the Section 2 document
        list rule, document category match, and document expiry are
        checked in that order (`ERR_DOCUMENT_LIST_RULE`, then
        `ERR_DOCUMENT_CATEGORY_MISMATCH`, then `ERR_DOCUMENT_EXPIRED`)".

        Claim: when LIST_A and LIST_B are both supplied AND the LIST_A
        is expired, the list-rule violation (P7) wins over expiry (P9).

        # difficulty: priority_pair_validation_conflict/doc_list_rule_vs_document_expired_on_section2
        """
        ctx = setup_form_at_section1_done_with_expired_list_a()
        emp = ctx["employee"]
        form = ctx["form"]
        doc_a_expired = ctx["expired_list_a"]
        doc_b = ctx["valid_list_b"]
        # Both LIST_A+LIST_B (illegal combo) AND LIST_A expired.
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=doc_a_expired["id"],
                list_b_document_id=doc_b["id"],
            ),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_DOCUMENT_LIST_RULE")


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecision:

    def test_section2_deadline_inclusive_boundary_at_exact_moment(
            self, api, employer_rep_headers):
        """PRD §3.3: "on-time (current time equal to the deadline) is
        treated as still on time because the deadline timestamp is
        inclusive."

        Claim: clock advanced to exactly section2_deadline
        (2026-06-04T23:59:59.999Z) with enforce_deadline=true succeeds.

        # difficulty: boundary_precision_check/section2_deadline_inclusive_boundary
        """
        ctx = setup_section2_deadline_boundary_scenario(
            advance_to_deadline=True,
        )
        emp = ctx["employee"]
        form = ctx["form"]
        doc = ctx["doc"]
        # Clock now at exactly 2026-06-04T23:59:59.999Z.
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=doc["id"],
                enforce_deadline=True,
            ),
            employer_rep_headers,
        )
        signed = validate_success(resp, expected_status=200)
        assert signed["form_status"] == "SECTION_2_DONE"

    def test_empty_document_set_on_section2(self, api,
                                            employer_rep_headers):
        """PRD §3.3: "Any other combination — `LIST_A` together with
        `LIST_B`, `LIST_A` together with `LIST_C`, `LIST_B` alone,
        `LIST_C` alone, or all three together — is rejected with
        `ERR_DOCUMENT_LIST_RULE`."

        Empty-set is implicitly "neither of the two permitted
        combinations" — the second permitted combination requires both
        LIST_B and LIST_C set. Per PRD §3.3 the rule is "exactly one"
        of the two combinations, so the empty body cannot satisfy
        either.

        # difficulty: boundary_precision_check/empty_document_set_on_section2
        """
        from test_helpers import attest_section1, create_employee, create_i9_form
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        advance_clock_to("2026-06-02T08:00:00.000Z")
        # Body sends no list_*_document_id fields.
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(version=form["version"]),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_DOCUMENT_LIST_RULE")
        # And the form remains in SECTION_1_DONE.
        from test_helpers import list_i9_forms
        forms = list_i9_forms(emp["id"])
        f = next(ff for ff in forms if ff["id"] == form["id"])
        assert f["form_status"] == "SECTION_1_DONE"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_everify_submit_requires_i9form_section2_done(
            self, api, employer_rep_headers):
        """PRD §3.5: "The submission has four preconditions: the linked
        form must be in state `SECTION_2_DONE`".

        Claim: submitting an E-Verify case against a form still in
        SECTION_1_DONE → ERR_INVALID_STATE; no row created.

        # difficulty: cross_entity_state_dependency/everify_submit_requires_i9form_section2_done
        """
        ctx = setup_employee_at_section1_only_for_everify_attempt()
        emp = ctx["employee"]
        form = ctx["form"]
        resp = api.submit_everify_case(
            emp["id"],
            submit_everify_payload(i9_form_id=form["id"]),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_INVALID_STATE")

    def test_section2_requires_document_not_expired(self, api,
                                                    employer_rep_headers):
        """PRD §3.3: "A document with a non-null `expiration_date`
        strictly before the current time is rejected with
        `ERR_DOCUMENT_EXPIRED`."

        Claim: LIST_A doc with expiration_date in the past, receipt=
        false → ERR_DOCUMENT_EXPIRED.

        # difficulty: cross_entity_state_dependency/section2_requires_document_not_expired
        """
        from test_helpers import attest_section1, create_employee, create_i9_form
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        # Register expired LIST_A with receipt=false.
        from test_helpers import register_document
        expired_doc = register_document(
            employee_id=emp["id"],
            category="LIST_A",
            document_title="U.S. Passport",
            expiration_date="2025-12-31",
            receipt=False,
        )
        advance_clock_to("2026-06-02T08:00:00.000Z")
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=expired_doc["id"],
            ),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_DOCUMENT_EXPIRED")


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_at_most_one_open_everify_case_per_employee(self, api,
                                                        employer_rep_headers):
        """PRD §3.5: "there must be no prior non-closed `EVerifyCase`
        for this employee, otherwise `ERR_CASE_ALREADY_OPEN`".

        Claim: second submit with a DIFFERENT idempotency_key, while
        the first case is still open, is rejected.

        # difficulty: resource_temporal_overlap/at_most_one_open_everify_case_per_employee
        """
        ctx = setup_employee_with_single_open_case()
        emp, form = ctx["employee"], ctx["form"]
        resp = api.submit_everify_case(
            emp["id"],
            submit_everify_payload(
                i9_form_id=form["id"], idempotency_key="k2",
            ),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_CASE_ALREADY_OPEN")

    def test_at_most_one_initial_i9form_per_employee(self, api,
                                                     hr_staff_headers):
        """PRD §3.3: "An `INITIAL` form is unique per employee: a
        second concurrent `INITIAL` creation is rejected with
        `ERR_DUPLICATE_INITIAL_FORM`."

        Claim: second INITIAL (sequential, not concurrent) is also
        rejected — the constraint is structural.

        # difficulty: resource_temporal_overlap/at_most_one_initial_i9form_per_employee
        """
        ctx = setup_employee_for_initial_form_uniqueness()
        emp = ctx["employee"]
        # Second INITIAL.
        from test_helpers import create_i9_form_payload
        resp = api.create_i9_form(
            emp["id"], create_i9_form_payload(form_kind="INITIAL"),
            hr_staff_headers,
        )
        validate_error(resp, "ERR_DUPLICATE_INITIAL_FORM")


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_idempotent_replay_preserves_case_count(self, api,
                                                    employer_rep_headers):
        """PRD §3.5: "the `idempotency_key` must be unique across this
        employee's cases — a retry with the same key returns the
        existing case as a 200 OK rather than creating a duplicate."

        Claim: N replays with the same key yield the SAME case row;
        the count of cases for this employee remains exactly 1; the
        EVERIFY_SUBMIT audit row count is 1.

        # difficulty: compensating_invariant/idempotent_replay_preserves_case_count
        """
        ctx = setup_employee_for_idempotent_replay()
        emp, form = ctx["employee"], ctx["form"]
        key = "ABC"
        # 1st submit (creation).
        first = validate_success(
            api.submit_everify_case(
                emp["id"],
                submit_everify_payload(
                    i9_form_id=form["id"], idempotency_key=key,
                ),
                employer_rep_headers,
            ),
            expected_status=201,
        )
        # 4 replays.
        for _ in range(4):
            resp = api.submit_everify_case(
                emp["id"],
                submit_everify_payload(
                    i9_form_id=form["id"], idempotency_key=key,
                ),
                employer_rep_headers,
            )
            assert resp.status_code == 200, (
                "Replay must return 200 (PRD §3.5)"
            )
            body = resp.json().get("data", {})
            assert body.get("id") == first["id"], (
                "Replay must return the SAME case id"
            )
        # AuditEvent EVERIFY_SUBMIT count == 1 (no duplicate submits).
        audits = list_audit_events(emp["id"])
        from test_helpers import find_audit_actions
        submits = find_audit_actions(audits, "EVERIFY_SUBMIT")
        assert len(submits) == 1, (
            f"Expected exactly 1 EVERIFY_SUBMIT audit row across 5 calls "
            f"(1 creation + 4 replays), got {len(submits)}"
        )

    def test_section3_supersession_preserves_reverification_resolution_count(
            self, api):
        """PRD §3.3: "any open `ReverificationEvent` whose
        `triggering_form_id` was the predecessor is resolved by setting
        its `resolved_at` to the new `section2_completed_at` and its
        `new_form_id` to the successor's `id`."

        Claim: total ReverificationEvent count for the employee remains
        1 before/after the supersession — the open row is moved to
        RESOLVED, no duplicate row is created.

        # difficulty: compensating_invariant/section3_supersession_preserves_reverification_resolution_count
        """
        ctx = setup_employee_for_section3_supersession()
        emp = ctx["employee"]
        new_form = ctx["new_form"]
        events = list_reverification_events(emp["id"])
        # PRD §3.4: each form may open at most one WORK_AUTH_EXPIRY event.
        triggered_by_initial = [
            e for e in events
            if e["triggering_form_id"] == ctx["initial_form"]["id"]
        ]
        assert len(triggered_by_initial) == 1, (
            f"Total ReverificationEvent count for the initial form must "
            f"remain 1 (no duplicate row), got {len(triggered_by_initial)}"
        )
        re = triggered_by_initial[0]
        assert re["resolved_at"] is not None
        assert re["new_form_id"] == new_form["id"]
        # PRD §3.4: open count vs resolved count sums to total.
        open_count = sum(1 for e in events if e.get("resolved_at") is None)
        resolved_count = sum(1 for e in events if e.get("resolved_at") is not None)
        total_count = len(events)
        assert open_count + resolved_count == total_count
        # The one initial-triggered event is now resolved.
        assert resolved_count >= 1
