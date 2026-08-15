"""Validation-order and business-rule claims: priority pairs, referential
integrity, parent mismatch, auth/role checks, timing rules, and template rules."""
import pytest

from test_helpers import (
    TEST_USERS,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_cast,
    add_employee,
    create_org_unit,
    create_employee,
    create_coaching_entries,
    create_and_submit_concern,
    create_and_accept_concern,
    create_and_publish_template,
    create_draft_pip,
    create_and_issue_pip,
    setup_concern_and_template,
    setup_issued_pip,
    setup_active_pip,
    create_check_in_payload,
    create_mark_held_payload,
    create_pip_template_payload,
    create_rating_cycle_payload,
    create_legal_review_payload,
    submit_legal_review_payload,
    propose_outcome,
    approve_outcome,
    get_pip,
    get_employee,
    get_goals,
    set_clock,
    make_hrbp_headers,
    make_manager_headers,
    make_counsel_headers,
    make_director_headers,
    make_employee_headers,
)


class TestValidationPriorityPairs:
    def test_invalid_state_reported_before_segregation(self, api):
        """PRD §2.6: "then target-state validity (`ERR_INVALID_STATE`), then
        segregation of duties (`ERR_SEGREGATION_OF_DUTIES`)".
        PRD §3.2: "Acceptance moves the concern `SUBMITTED` → `ACCEPTED`" — a DRAFT
        concern is not in the required state, and §2.6 fixes state validity ahead
        of segregation.

        Design: Difficulty/priority_pair_validation_conflict/state_invalid_vs_sod_segregation_state_wins
        """
        cast = setup_cast()
        entry_ids = create_coaching_entries(cast)
        # Concern stays DRAFT (never submitted).
        resp = api.create_concern(
            cast["ou_id"], cast["emp_id"],
            {"category": "QUALITY", "summary": "Quality below bar for level",
             "coaching_log_entry_ids": entry_ids},
            make_manager_headers(cast["mgr_id"]),
        )
        concern = validate_success(resp, expected_status=201)
        # Caller carries the HRBP role but IS the raising manager: both the state
        # check (concern is DRAFT) and the SoD check would fire; state wins.
        resp = api.accept_concern(
            cast["ou_id"], cast["emp_id"], concern["id"],
            make_hrbp_headers(cast["mgr_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_segregation_reported_before_attainment_guard(self, api):
        """PRD §2.6: "then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), and
        only then the business, temporal, referential, and constraint rules
        detailed throughout §3".
        PRD §3.6: "The proposer is recorded as `proposed_by_hrbp_id` and must
        differ from the plan's issuing HRBP whenever the plan still runs under
        the policy version in force at its issuance ... A violation is rejected
        with `ERR_SEGREGATION_OF_DUTIES`." — the attainment guard is a §3
        constraint rule and so surfaces after the §2.6 segregation check.

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_attainment_threshold_sod_wins
        """
        ctx = setup_active_pip()
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        # No evidence admitted -> final attainment 0, below the 0.80 guard; the
        # policy version has not advanced since issuance, so the issuing HRBP
        # proposing also violates segregation of duties. Both rules fail; the
        # §2.6 chain surfaces segregation first.
        resp = propose_outcome(
            ctx, "SUCCESS", proposer_hrbp_id=ctx["hrbp_id"],
            rationale="Attempted self-proposed success without supporting evidence.",
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestReferentialIntegrity:
    def test_pip_create_with_unaccepted_concern_rejected(self, api):
        """PRD §3.3: "The referenced concern must be `ACCEPTED` and not already
        bound to another non-terminal plan, and the referenced template must be
        `PUBLISHED` — template-state failures are rejected with
        `ERR_TEMPLATE_NOT_PUBLISHED`, while body references that resolve but fail
        their state filters are rejected with `ERR_REFERENTIAL_INTEGRITY`
        (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/pip_issue_requires_concern_accepted
        """
        cast = setup_cast()
        entry_ids = create_coaching_entries(cast)
        # Concern SUBMITTED but never ACCEPTED.
        concern = create_and_submit_concern(cast, entry_ids)
        template = create_and_publish_template(cast)
        resp = api.create_pip(
            cast["ou_id"], cast["emp_id"],
            {"concern_id": concern["id"], "template_id": template["id"],
             "start_date": "2026-08-01T00:00:00Z"},
            make_hrbp_headers(cast["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)

    def test_pip_create_with_unpublished_template_rejected(self, api):
        """PRD §3.3: "template-state failures are rejected with
        `ERR_TEMPLATE_NOT_PUBLISHED`".

        Design: Difficulty/cross_entity_state_dependency/pip_issue_requires_concern_accepted
        """
        cast = setup_cast()
        entry_ids = create_coaching_entries(cast)
        concern = create_and_accept_concern(cast, entry_ids)
        # Template created but never published (stays DRAFT).
        resp = api.create_pip_template(
            cast["ou_id"], create_pip_template_payload(),
            make_hrbp_headers(cast["hrbp_id"]),
        )
        template = validate_success(resp, expected_status=201)
        resp = api.create_pip(
            cast["ou_id"], cast["emp_id"],
            {"concern_id": concern["id"], "template_id": template["id"],
             "start_date": "2026-08-01T00:00:00Z"},
            make_hrbp_headers(cast["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TEMPLATE_NOT_PUBLISHED)


class TestParentMismatch:
    def test_pip_read_through_wrong_employee_returns_parent_mismatch(self, api):
        """PRD §2.6: "When every identifier exists but a child does not belong to
        its declared parent — a plan under the wrong employee, an evidence item
        under the wrong check-in — the request fails with `ERR_PARENT_MISMATCH`
        (HTTP 404)."

        Design: Corner/validations/nested_resource_parent_mismatch_returns_404
        """
        cast = setup_cast()
        emp2 = create_employee(
            cast["ou_id"], full_name="E2", email="e2@x.com",
            job_family="ENGINEERING", job_level=5, manager_id=cast["mgr_id"],
        )
        concern, template = setup_concern_and_template(cast)
        pip = create_draft_pip(cast, concern["id"], template["id"])
        resp = api.get_pip(
            cast["ou_id"], emp2["id"], pip["id"],
            make_hrbp_headers(cast["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARENT_MISMATCH)


class TestAuthAndRoleChecks:
    def test_missing_user_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring their operational
        capacity. A request missing either header, or carrying a malformed value,
        is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        ou = create_org_unit()
        resp = api.get_org_unit(ou["id"], headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_manager_cannot_create_pip_template(self, api):
        """PRD §2.1: "A caller whose role is not permitted for an endpoint — or who
        is not the designated actor for that step, such as the wrong manager, the
        wrong HRBP, the wrong counsel, or the wrong employee — is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /hr-org-units/{ouId}/pip-templates is HRBusinessPartner-only.

        Design: Corner/validations/role_not_permitted_returns_403
        """
        cast = setup_cast()
        resp = api.create_pip_template(
            cast["ou_id"], create_pip_template_payload(),
            make_manager_headers(cast["mgr_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestTimingRules:
    def test_mark_held_before_scheduled_for_rejected(self, api):
        """PRD §3.4: "the clock must have reached `scheduled_for`
        (`ERR_CHECKIN_TOO_EARLY`)".

        Design: Corner/validations/checkin_mark_held_before_scheduled_for_returns_too_early
        """
        ctx = setup_active_pip(clock_to="2026-08-05T10:00:00Z")
        # Clock at 2026-08-05 is past start_date (2026-08-01) but before the
        # check-in's scheduled_for (2026-08-11).
        resp = api.mark_check_in_held(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"],
            create_mark_held_payload(notes="Too early: this must fail."),
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CHECKIN_TOO_EARLY)


class TestTemplateGeometry:
    def test_template_with_weight_sum_not_100_rejected(self, api):
        """PRD §3.3: "each blueprint a `metric_key`, `target_value`, `unit`, and
        `weight`, with the weights summing to exactly 100 ... These geometry rules
        are enforced at authoring and re-checked at publication: a weight-sum or
        range failure surfaces `ERR_TEMPLATE_WEIGHT_SUM`".

        Design: Corner/validations/template_publish_with_weight_sum_not_100_returns_422
        """
        cast = setup_cast()
        resp = api.create_pip_template(
            cast["ou_id"],
            create_pip_template_payload(goal_blueprints=[
                {"metric_key": "defects", "target_value": 2, "unit": "count", "weight": 60},
                {"metric_key": "review_turnaround", "target_value": 24, "unit": "hours", "weight": 30},
            ]),
            make_hrbp_headers(cast["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TEMPLATE_WEIGHT_SUM)

    def test_retire_template_referenced_by_inflight_pip_rejected(self, api):
        """PRD §3.3: "Retirement moves a `PUBLISHED` template to `RETIRED`, but is
        refused while any plan in `DRAFT`, `ISSUED`, `ACTIVE`, or `EXTENDED` still
        references it (`ERR_TEMPLATE_IN_USE`)."

        Design: Corner/validations/template_retire_with_active_pip_returns_409
        """
        ctx = setup_issued_pip()
        resp = api.retire_pip_template(
            ctx["ou_id"], ctx["template_id"], make_hrbp_headers(ctx["hrbp_id"])
        )
        validate_error(resp, ApiErrorId.ERR_TEMPLATE_IN_USE)


class TestCoachingHistoryGate:
    def test_submit_with_fewer_than_two_entries_rejected(self, api):
        """PRD §3.2: "at least two coaching entries must be referenced
        (`ERR_INSUFFICIENT_COACHING_HISTORY`)".

        Design: Corner/validations/concern_submit_with_fewer_than_2_formal_entries_returns_422
        """
        cast = setup_cast()
        entry_ids = create_coaching_entries(cast, count=1)
        resp = api.create_concern(
            cast["ou_id"], cast["emp_id"],
            {"category": "QUALITY", "summary": "Quality below bar for level",
             "coaching_log_entry_ids": entry_ids},
            make_manager_headers(cast["mgr_id"]),
        )
        concern = validate_success(resp, expected_status=201)
        resp = api.submit_concern(
            cast["ou_id"], cast["emp_id"], concern["id"],
            make_manager_headers(cast["mgr_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COACHING_HISTORY)


class TestCheckInQuorum:
    def test_mark_held_without_hrbp_attendance_rejected(self, api):
        """PRD §3.4: "both `manager_attended` and `hrbp_attended`, each defaulting
        to false when omitted, must be true — a one-sided meeting is no check-in
        (`ERR_CHECKIN_QUORUM`)".

        Design: Corner/validations/checkin_mark_held_without_quorum_returns_422
        """
        ctx = setup_active_pip()
        resp = api.mark_check_in_held(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"],
            create_mark_held_payload(manager_attended=True, hrbp_attended=False,
                                     notes="HRBP did not attend this session."),
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CHECKIN_QUORUM)


class TestExtensionLimit:
    def test_extension_proposal_at_limit_rejected(self, api):
        """PRD §3.6: "an `EXTENSION` requires the plan's `extension_count` — the
        count of extension cycles already consumed, starting at zero — to still be
        below its single allowance of one (`ERR_EXTENSION_LIMIT_EXCEEDED`)".

        Design: Corner/validations/outcome_decision_extension_at_limit_returns_409
        """
        cast = setup_cast()
        proposer = add_employee(cast["ou_id"], "Proposer", "h1@x.com", job_level=7)
        director = add_employee(cast["ou_id"], "Director", "d@x.com", job_level=9)
        ctx = setup_issued_pip(cast=cast)
        resp = api.create_check_in(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_check_in_payload(scheduled_for="2026-08-11T00:00:00Z"),
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        validate_success(resp, expected_status=201)
        ctx["proposer_id"] = proposer["id"]
        ctx["director_id"] = director["id"]
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "EXTENSION", proposer_hrbp_id=proposer["id"],
                               rationale="First extension granted; progress observed.")
        d1 = validate_success(resp, expected_status=201)
        validate_success(approve_outcome(ctx, d1["id"], director_id=director["id"]))
        set_clock(ctx["ou_id"], "2026-09-16T00:00:00Z")  # past extended end_date
        resp = propose_outcome(ctx, "EXTENSION", proposer_hrbp_id=proposer["id"],
                               rationale="Attempting a second extension; must be rejected.")
        validate_error(resp, ApiErrorId.ERR_EXTENSION_LIMIT_EXCEEDED)


class TestEmployeeNotActive:
    def test_accept_concern_on_terminated_employee_rejected(self, api):
        """PRD §3.2: "Acceptance moves the concern `SUBMITTED` → `ACCEPTED` and
        additionally requires the employee to still be `ACTIVE`
        (`ERR_EMPLOYEE_NOT_ACTIVE`)".

        Design: Corner/validations/concern_accept_on_terminated_employee_returns_employee_not_active
        """
        ctx = setup_cast()
        counsel = add_employee(ctx["ou_id"], "Counsel", "l@x.com", job_level=8)
        director = add_employee(ctx["ou_id"], "Director", "d@x.com", job_level=9)
        proposer = add_employee(ctx["ou_id"], "Proposer", "p@x.com", job_level=7)
        ctx["counsel_id"] = counsel["id"]
        ctx["director_id"] = director["id"]
        # Concern 1 drives E1 to TERMINATED via an approved TERMINATION outcome.
        conduct_entries = create_coaching_entries(
            ctx, count=2, severity="ESCALATED", category="CONDUCT"
        )
        concern1 = create_and_accept_concern(ctx, conduct_entries, category="CONDUCT",
                                             summary="Conduct escalation pattern observed")
        template = create_and_publish_template(
            ctx, category="CONDUCT",
            goal_blueprints=[
                {"metric_key": "incidents", "target_value": 1, "unit": "count", "weight": 100},
            ],
        )
        pip = create_and_issue_pip(ctx, concern1["id"], template["id"])
        ctx["pip_id"] = pip["id"]
        resp = api.create_check_in(
            ctx["ou_id"], ctx["emp_id"], pip["id"],
            create_check_in_payload(scheduled_for="2026-08-11T00:00:00Z"),
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        validate_success(resp, expected_status=201)
        # Second concern (SUBMITTED, never accepted) — will outlive the employee.
        quality_entries = create_coaching_entries(ctx, count=2, category="QUALITY")
        concern2 = create_and_submit_concern(ctx, quality_entries, category="QUALITY",
                                             summary="Quality concern (pending)")
        from test_helpers import create_and_submit_legal_review, propose_outcome, approve_outcome
        create_and_submit_legal_review(ctx, hrbp_id=ctx["hrbp_id"],
                                       rationale="No legal risk factors; proceed with termination.")
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "TERMINATION", proposer_hrbp_id=proposer["id"],
                               rationale="No improvement over the plan window; terminating.")
        decision = validate_success(resp, expected_status=201)
        validate_success(approve_outcome(ctx, decision["id"], director_id=director["id"]))
        set_clock(ctx["ou_id"], "2026-09-07T00:00:00Z")  # rebuttal window lapses
        emp = get_employee(ctx)
        assert emp["employment_status"] == "TERMINATED"

        resp = api.accept_concern(
            ctx["ou_id"], ctx["emp_id"], concern2["id"],
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_ACTIVE)


class TestRatingCycleGuards:
    def test_calibrate_before_window_end_rejected(self, api, admin_headers):
        """PRD §3.1: "Moving a cycle from `OPEN` to `CALIBRATION` is an HRBP action
        permitted only once the window has closed — a clock reading earlier than
        `window_end` is rejected with `ERR_CYCLE_STILL_OPEN`."

        Design: Corner/validations/rating_cycle_calibrate_before_window_end_returns_409
        """
        cast = setup_cast()
        resp = api.create_rating_cycle(
            cast["ou_id"],
            create_rating_cycle_payload(
                label="2026", window_start="2026-01-01T00:00:00Z",
                window_end="2026-12-31T00:00:00Z",
            ),
            make_hrbp_headers(cast["hrbp_id"]),
        )
        cycle = validate_success(resp, expected_status=201)
        # Clock still at 2026-08-01 < window_end.
        resp = api.calibrate_rating_cycle(
            cast["ou_id"], cycle["id"], make_hrbp_headers(cast["hrbp_id"])
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_STILL_OPEN)

    def test_archive_before_365_days_rejected(self, api, admin_headers):
        """PRD §3.1: "Archival (`PUBLISHED` → `ARCHIVED`) is also a director action,
        permitted only once the clock has reached at least 365 days past
        `window_end`; earlier attempts fail with `ERR_CYCLE_TOO_RECENT`."

        Design: Corner/validations/rating_cycle_archive_before_365_days_returns_409
        """
        cast = setup_cast()
        director = add_employee(cast["ou_id"], "Director", "d@x.com", job_level=9)
        resp = api.create_rating_cycle(
            cast["ou_id"],
            create_rating_cycle_payload(
                label="2025-H2", window_start="2025-07-01T00:00:00Z",
                window_end="2026-07-01T00:00:00Z",
            ),
            make_hrbp_headers(cast["hrbp_id"]),
        )
        cycle = validate_success(resp, expected_status=201)
        # Boot clock (2026-08-01) is already past window_end: calibrate/publish OK.
        # (The logical clock is monotonically non-decreasing per PRD §2.5, so the
        # window must end before the initial clock reading.)
        validate_success(api.calibrate_rating_cycle(
            cast["ou_id"], cycle["id"], make_hrbp_headers(cast["hrbp_id"])))
        validate_success(api.publish_rating_cycle(
            cast["ou_id"], cycle["id"], make_director_headers(director["id"])))
        # 2026-11-15 is only ~137 days past window_end (< 365); archive too early.
        set_clock(cast["ou_id"], "2026-11-15T00:00:00Z")
        resp = api.archive_rating_cycle(
            cast["ou_id"], cycle["id"], make_director_headers(director["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_TOO_RECENT)


class TestWithdrawGuard:
    def test_withdraw_blocked_by_proposed_outcome(self, api):
        """PRD §3.3: "only while no outcome decision for the plan stands in
        `PROPOSED` or `APPROVED` (`ERR_OUTCOME_ALREADY_PROPOSED`)".

        Design: Corner/validations/outcome_already_proposed_blocks_withdraw
        """
        ctx = setup_active_pip()
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "EXTENSION", proposer_hrbp_id=proposer["id"],
                               rationale="Proposing an extension of the plan window.")
        validate_success(resp, expected_status=201)
        resp = api.withdraw_pip(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OUTCOME_ALREADY_PROPOSED)


class TestEvidenceAdjudicationTiming:
    def test_admit_on_held_checkin_rejected(self, api):
        """PRD §3.4: "Admissibility is adjudicated by an HRBP while the check-in
        remains `SCHEDULED` — once the check-in stands `HELD`, adjudication
        attempts fail with `ERR_CHECKIN_ALREADY_HELD`."

        Design: Corner/validations/evidence_admit_on_held_checkin_returns_409
        """
        ctx = setup_active_pip()
        goals = get_goals(ctx)
        from test_helpers import create_evidence_payload
        resp = api.submit_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"],
            create_evidence_payload(goals[0]["id"], observed_value=1,
                                    source="SYSTEM_REPORT"),
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        ev = validate_success(resp, expected_status=201)["id"]
        # Hold the check-in BEFORE adjudicating the evidence.
        validate_success(api.mark_check_in_held(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"],
            create_mark_held_payload(notes="Held before evidence adjudicated."),
            make_hrbp_headers(ctx["hrbp_id"]),
        ))
        resp = api.admit_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"], ev,
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CHECKIN_ALREADY_HELD)
