"""Working a review case: staffing it, escalating it, and closing it out.

The escalation cycle is the interesting shape here — a case leaves an analyst,
comes back re-priced, and has to land on a lead — and the analyst capacity
ledger has to survive the whole round trip.
"""

from __future__ import annotations

from test_helpers import (
    ADMIN,
    AnalystStatus,
    ApiClient,
    ApiErrorId,
    AssessmentState,
    CaseAction,
    CaseState,
    Decision,
    DecisionReason,
    FinalDisposition,
    LARGE_ORDER_CENTS,
    STANDARD_ORDER_CENTS,
    Seniority,
    SignalFamily,
    assign_case_payload,
    assign_case_to,
    assert_net_approved_ledger,
    assert_review_capacity_ledger,
    assert_score,
    build_behavioral_roster,
    build_reviewed_assessment,
    build_roster,
    build_scoring_env,
    escalate_case,
    make_review_lead_headers,
    make_risk_analyst_headers,
    move_analyst_off_shift,
    read_analyst,
    read_assessment,
    read_case,
    read_customer,
    resolve_case_as_analyst,
    resolve_case_as_lead,
    resolve_case_payload,
    validate_error,
)


def _one_capacity_roster(api: ApiClient):
    """Two junior behavioural analysts who may each hold a single case, plus a lead."""
    return build_roster(
        api,
        {
            "an1": {
                "display_name": "AN1",
                "seniority": Seniority.JUNIOR,
                "skill_families": [SignalFamily.BEHAVIORAL],
                "shift_capacity_cases": 1,
            },
            "an2": {
                "display_name": "AN2",
                "seniority": Seniority.JUNIOR,
                "skill_families": [SignalFamily.BEHAVIORAL],
                "shift_capacity_cases": 1,
            },
            "lead": {
                "display_name": "LEAD1",
                "seniority": Seniority.LEAD,
                "skill_families": [SignalFamily.BEHAVIORAL],
                "shift_capacity_cases": 3,
            },
        },
    )


class TestEscalationCycle:
    """A case can leave an analyst and come back to ASSIGNED through a lead."""

    def test_escalation_clears_the_assignment_and_re_prices_the_case(
        self, api: ApiClient
    ) -> None:
        """An escalated case drops its assignee and picks up the 15.00 boost.

        PRD: "`ASSIGNED → ESCALATED` records the acting analyst as
        `escalated_by_analyst_id`, clears `assigned_analyst_id` back to null,
        increments `escalation_count` by one, decrements the previously assigned
        analyst's `open_case_count` by one and increments that analyst's `version`
        by one, and recomputes `priority_score` — which now picks up the escalation
        boost."
        PRD: "an escalation boost of 15.00 when the case's `escalation_count` is
        greater than zero and 0.00 otherwise"

        Design: Difficulty/non_linear_state_machine/review_case_escalation_cycle_returns_to_assigned
        """
        env = build_scoring_env(api)
        roster = build_behavioral_roster(api)
        assessment, case = build_reviewed_assessment(api, env, LARGE_ORDER_CENTS)
        assert_score(assessment["blended_score"], 50.00, "blended_score")
        assert_score(case["priority_score"], 32.50, "priority_score when queued")

        assigned = assign_case_to(
            api, case["id"], roster["junior"], roster.id_of("lead")
        )
        assert assigned["state"] == CaseState.ASSIGNED
        assert assigned["assigned_analyst_id"] == roster.id_of("junior")

        escalated = escalate_case(
            api, case["id"], roster.id_of("junior"), note="Needs a lead's judgement"
        )
        assert escalated["state"] == CaseState.ESCALATED
        assert escalated["assigned_analyst_id"] is None, (
            "escalation clears the assignment"
        )
        assert escalated["escalated_by_analyst_id"] == roster.id_of("junior")
        assert escalated["escalation_count"] == 1
        assert_score(
            escalated["priority_score"], 47.50, "priority_score after escalation"
        )

        junior = read_analyst(api, roster.id_of("junior"))
        assert junior["open_case_count"] == 0, (
            "the escalating analyst no longer holds the case"
        )

    def test_reassigning_an_escalated_case_to_a_lead_returns_it_to_assigned(
        self, api: ApiClient
    ) -> None:
        """The cycle closes on a LEAD, leaving escalation_count at one.

        PRD: "A successful assignment — `QUEUED → ASSIGNED` or
        `ESCALATED → ASSIGNED`, the latter closing the escalation cycle — sets
        `assigned_analyst_id` and stamps `assigned_at` at the current instant,
        increments the analyst's `open_case_count` by one and the analyst's
        `version` by one, and increments the case's own `version` by one."
        PRD: "for an `ESCALATED` case, the analyst's `seniority` must be `LEAD`
        (`ERR_ESCALATED_REQUIRES_LEAD`)"

        Design: Difficulty/non_linear_state_machine/review_case_escalation_cycle_returns_to_assigned
        """
        env = build_scoring_env(api)
        roster = build_behavioral_roster(api)
        assessment, case = build_reviewed_assessment(api, env, LARGE_ORDER_CENTS)
        assign_case_to(api, case["id"], roster["junior"], roster.id_of("lead"))
        escalate_case(api, case["id"], roster.id_of("junior"))

        reassigned = assign_case_to(
            api, case["id"], roster["lead"], roster.id_of("lead")
        )
        assert reassigned["state"] == CaseState.ASSIGNED
        assert reassigned["assigned_analyst_id"] == roster.id_of("lead")
        assert reassigned["assigned_at"] is not None
        assert reassigned["escalation_count"] == 1, (
            "closing the cycle does not reset the escalation counter"
        )
        assert reassigned["escalated_by_analyst_id"] == roster.id_of("junior"), (
            "the escalating analyst stays on the record"
        )

        assert read_analyst(api, roster.id_of("lead"))["open_case_count"] == 1
        assert read_analyst(api, roster.id_of("junior"))["open_case_count"] == 0
        assert read_assessment(api, assessment["id"])["state"] == (
            AssessmentState.IN_REVIEW
        ), "the assessment stays in review until the case is resolved"


class TestReviewCapacityLedgerAcrossEscalation:
    """``open_case_count`` must come back to where it started, with no drift."""

    def test_assign_escalate_reassign_resolve_returns_both_analysts_to_zero(
        self, api: ApiClient
    ) -> None:
        """A full cycle leaves one resolution on the lead and nothing open anywhere.

        PRD: "A full cycle of assign, escalate, reassign and resolve must return the
        analyst to the count they started at, with no drift."
        PRD: "It decrements the analyst's `open_case_count` by one, increments their
        `resolved_case_count` by one and their `version` by one."

        Design: Difficulty/compensating_invariant/review_capacity_ledger_returns_to_zero_across_escalation_cycle
        """
        env = build_scoring_env(api)
        roster = build_behavioral_roster(api)
        assessment, case = build_reviewed_assessment(api, env, LARGE_ORDER_CENTS)

        assign_case_to(api, case["id"], roster["junior"], roster.id_of("lead"))
        escalate_case(api, case["id"], roster.id_of("junior"))
        assign_case_to(api, case["id"], roster["lead"], roster.id_of("lead"))
        resolved = resolve_case_as_lead(
            api, case["id"], roster.id_of("lead"), CaseAction.APPROVE
        )

        assert resolved["state"] == CaseState.RESOLVED_APPROVE
        assert resolved["escalation_count"] == 1
        assert resolved["resolved_at"] is not None
        assert resolved["resolved_late"] is False, (
            "the clock never advanced past the four-hour SLA"
        )

        junior = read_analyst(api, roster.id_of("junior"))
        lead = read_analyst(api, roster.id_of("lead"))
        assert junior["open_case_count"] == 0
        assert junior["resolved_case_count"] == 0, (
            "escalating is not resolving, so the junior earns no resolution"
        )
        assert lead["open_case_count"] == 0
        assert lead["resolved_case_count"] == 1

        final = read_assessment(api, assessment["id"])
        assert final["state"] == AssessmentState.DECIDED_APPROVE
        assert final["decision"] == Decision.REVIEW, (
            "manual review never rewrites the frozen decision"
        )
        assert final["decision_reason"] == DecisionReason.MANUAL_REVIEW
        assert final["final_disposition"] == FinalDisposition.APPROVED

        customer = read_customer(api, env.customer_id)
        assert customer["approved_count"] == 1
        assert customer["lifetime_net_approved_cents"] == LARGE_ORDER_CENTS

    def test_open_case_count_matches_the_assigned_cases_at_every_step(
        self, api: ApiClient
    ) -> None:
        """The ledger identity is reconciled after each transition of the cycle.

        PRD: "An analyst's `open_case_count` must always equal the number of review
        cases whose `assigned_analyst_id` is that analyst and whose `state` is
        `ASSIGNED`."
        PRD: "It rises by one when a case becomes `ASSIGNED`, falls by one when an
        assigned case is resolved either way, falls by one when an assigned case is
        escalated (because the assignment is cleared), and is set to zero outright
        by the shift-release cascade that requeues every case the analyst was
        holding."

        Design: Difficulty/compensating_invariant/review_capacity_ledger_returns_to_zero_across_escalation_cycle
        """
        env = build_scoring_env(api)
        roster = build_behavioral_roster(api)
        _assessment, case = build_reviewed_assessment(api, env, LARGE_ORDER_CENTS)
        junior_id = roster.id_of("junior")
        lead_id = roster.id_of("lead")

        assert assert_review_capacity_ledger(api, junior_id, ADMIN) == 0

        assign_case_to(api, case["id"], roster["junior"], lead_id)
        assert assert_review_capacity_ledger(api, junior_id, ADMIN) == 1

        escalate_case(api, case["id"], junior_id)
        assert assert_review_capacity_ledger(api, junior_id, ADMIN) == 0

        assign_case_to(api, case["id"], roster["lead"], lead_id)
        assert assert_review_capacity_ledger(api, lead_id, ADMIN) == 1
        assert assert_review_capacity_ledger(api, junior_id, ADMIN) == 0

        resolve_case_as_lead(api, case["id"], lead_id, CaseAction.APPROVE)
        assert assert_review_capacity_ledger(api, lead_id, ADMIN) == 0
        assert assert_review_capacity_ledger(api, junior_id, ADMIN) == 0


class TestEscalatedLeadRequirementBeatsCapacity:
    """When both apply, the lead requirement is reported, not the capacity failure."""

    def test_escalated_case_assigned_to_a_full_junior_reports_the_lead_requirement(
        self, api: ApiClient
    ) -> None:
        """A junior who is both non-lead and at capacity reports ERR_ESCALATED_REQUIRES_LEAD.

        PRD: "On the explicit-assignment path, the escalated-requires-lead check
        (band 7) **outranks** the analyst-capacity check (band 9): assigning an
        escalated case to a non-lead analyst who is also at capacity reports
        `ERR_ESCALATED_REQUIRES_LEAD`, not `ERR_ANALYST_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/escalated_lead_requirement_outranks_analyst_capacity
        """
        env = build_scoring_env(api)
        roster = _one_capacity_roster(api)
        lead_id = roster.id_of("lead")

        _first, case_one = build_reviewed_assessment(api, env, LARGE_ORDER_CENTS)
        _second, case_two = build_reviewed_assessment(api, env, LARGE_ORDER_CENTS)

        assign_case_to(api, case_one["id"], roster["an1"], lead_id)
        escalate_case(api, case_one["id"], roster.id_of("an1"))

        assign_case_to(api, case_two["id"], roster["an2"], lead_id)
        an2 = read_analyst(api, roster.id_of("an2"))
        assert an2["open_case_count"] == an2["shift_capacity_cases"], (
            "AN2 must be exactly at capacity for the collision to be observable"
        )

        response = api.assign_case(
            case_one["id"],
            assign_case_payload(an2["id"], int(an2["version"])),
            make_review_lead_headers(lead_id),
        )
        validate_error(response, ApiErrorId.ERR_ESCALATED_REQUIRES_LEAD, 422)

        unchanged = read_case(api, case_one["id"])
        assert unchanged["state"] == CaseState.ESCALATED
        assert unchanged["assigned_analyst_id"] is None
        assert read_analyst(api, roster.id_of("an2"))["open_case_count"] == 1, (
            "the rejected assignment must not consume AN2's headroom"
        )

    def test_capacity_failure_is_still_reported_for_a_queued_case(
        self, api: ApiClient
    ) -> None:
        """The same full junior offered a QUEUED case reports the capacity failure.

        PRD: "and finally the analyst's `open_case_count` must be strictly below
        their `shift_capacity_cases` (`ERR_ANALYST_CAPACITY_EXCEEDED`)"

        Design: Difficulty/priority_pair_validation_conflict/escalated_lead_requirement_outranks_analyst_capacity
        """
        env = build_scoring_env(api)
        roster = _one_capacity_roster(api)
        lead_id = roster.id_of("lead")

        _held, case_held = build_reviewed_assessment(api, env, LARGE_ORDER_CENTS)
        _queued, case_queued = build_reviewed_assessment(api, env, LARGE_ORDER_CENTS)

        assign_case_to(api, case_held["id"], roster["an2"], lead_id)
        an2 = read_analyst(api, roster.id_of("an2"))

        response = api.assign_case(
            case_queued["id"],
            assign_case_payload(an2["id"], int(an2["version"])),
            make_review_lead_headers(lead_id),
        )
        validate_error(response, ApiErrorId.ERR_ANALYST_CAPACITY_EXCEEDED, 409)
        assert read_case(api, case_queued["id"])["state"] == CaseState.QUEUED


class TestAssignmentRequiresAnAvailableAnalyst:
    """An analyst who has left AVAILABLE cannot be handed a case."""

    def test_assigning_to_an_off_shift_analyst_is_rejected(
        self, api: ApiClient
    ) -> None:
        """A fresh version of an OFF_SHIFT analyst still fails the availability check.

        PRD: "the case's `primary_signal_family` must be among the analyst's
        `skill_families` (`ERR_ANALYST_SKILL_MISMATCH`); the analyst's `status` must be
        `AVAILABLE` (`ERR_ANALYST_NOT_AVAILABLE`)"
        PRD: "The roster's `status` axis moves among `AVAILABLE`, `OFF_SHIFT` and
        `SUSPENDED`, and only `AVAILABLE` analysts are assignment-eligible."

        Design: Difficulty/cross_entity_state_dependency/case_assignment_rejected_when_analyst_off_shift
        """
        env = build_scoring_env(api)
        roster = build_behavioral_roster(api)
        _assessment, case = build_reviewed_assessment(api, env, LARGE_ORDER_CENTS)

        off_shift = move_analyst_off_shift(api, roster.id_of("junior"))
        assert off_shift["status"] == AnalystStatus.OFF_SHIFT
        assert off_shift["open_case_count"] == 0

        response = api.assign_case(
            case["id"],
            assign_case_payload(off_shift["id"], int(off_shift["version"])),
            make_review_lead_headers(roster.id_of("lead")),
        )
        validate_error(response, ApiErrorId.ERR_ANALYST_NOT_AVAILABLE, 409)

        assert read_case(api, case["id"])["state"] == CaseState.QUEUED
        assert read_analyst(api, roster.id_of("junior"))["open_case_count"] == 0

    def test_a_stale_analyst_version_is_reported_before_the_availability_check(
        self, api: ApiClient
    ) -> None:
        """Presenting the pre-shift version reports the stale read, not availability.

        PRD: "The checks run in this order: the case's state must permit
        assignment, meaning `QUEUED` or `ESCALATED` (`ERR_CASE_STATE_INVALID`); the
        stale-analyst-version check (`ERR_STALE_ANALYST_VERSION`); for an
        `ESCALATED` case, the analyst must not be the one recorded in
        `escalated_by_analyst_id` (`ERR_ESCALATION_SEGREGATION_VIOLATION`); for an
        `ESCALATED` case, the analyst's `seniority` must be `LEAD`
        (`ERR_ESCALATED_REQUIRES_LEAD`); the case's `primary_signal_family` must be
        among the analyst's `skill_families` (`ERR_ANALYST_SKILL_MISMATCH`); the
        analyst's `status` must be `AVAILABLE` (`ERR_ANALYST_NOT_AVAILABLE`); and
        finally the analyst's `open_case_count` must be strictly below their
        `shift_capacity_cases` (`ERR_ANALYST_CAPACITY_EXCEEDED`)."

        Design: Difficulty/cross_entity_state_dependency/case_assignment_rejected_when_analyst_off_shift
        """
        env = build_scoring_env(api)
        roster = build_behavioral_roster(api)
        _assessment, case = build_reviewed_assessment(api, env, LARGE_ORDER_CENTS)
        stale_version = roster.version_of("junior")

        off_shift = move_analyst_off_shift(api, roster.id_of("junior"))
        assert int(off_shift["version"]) > stale_version, (
            "the shift move must have advanced the analyst's version"
        )

        response = api.assign_case(
            case["id"],
            assign_case_payload(off_shift["id"], stale_version),
            make_review_lead_headers(roster.id_of("lead")),
        )
        validate_error(response, ApiErrorId.ERR_STALE_ANALYST_VERSION, 412)
        assert read_case(api, case["id"])["state"] == CaseState.QUEUED


class TestAnalystOwnershipOnTheResolvePath:
    """For a `RiskAnalyst` the resolve endpoint is scoped to the case they hold."""

    def test_a_second_analyst_is_refused_and_the_owner_closes_the_case(
        self, api: ApiClient
    ) -> None:
        """The stranger's APPROVE is a 403; the owner's identical APPROVE lands both terminals.

        PRD: "Ownership is then enforced asymmetrically: a `RiskAnalyst` may act only on a
        case whose `assigned_analyst_id` equals their own `X-User-ID`, and otherwise
        receives `ERR_NOT_CASE_OWNER`, whereas a `ReviewLead` may resolve any `ASSIGNED`
        case."
        PRD: "It then cascades the assessment `IN_REVIEW → DECIDED_APPROVE`:
        `decision_reason` becomes `MANUAL_REVIEW` while `decision` **stays** `REVIEW`,
        `final_disposition` becomes `APPROVED`, `decided_at` is stamped, the customer's
        `approved_count` rises by one and `lifetime_net_approved_cents` by the order's
        `amount_cents`"

        Design: Corner/errors/case_resolution_by_a_non_owning_analyst_rejected
        """
        env = build_scoring_env(api)
        roster = _one_capacity_roster(api)
        assessment, case = build_reviewed_assessment(api, env, STANDARD_ORDER_CENTS)
        assert_score(assessment["blended_score"], 50.00, "blended_score")

        held = assign_case_to(api, case["id"], roster["an1"], roster.id_of("lead"))
        assert held["state"] == CaseState.ASSIGNED
        assert held["assigned_analyst_id"] == roster.id_of("an1")

        stranger = api.resolve_case(
            case["id"],
            resolve_case_payload(CaseAction.APPROVE, resolution_note="looks fine to me"),
            make_risk_analyst_headers(roster.id_of("an2")),
        )
        validate_error(stranger, ApiErrorId.ERR_NOT_CASE_OWNER, 403)

        assert read_case(api, case["id"])["state"] == CaseState.ASSIGNED
        assert read_analyst(api, roster.id_of("an1"))["open_case_count"] == 1, (
            "the refused resolution leaves the case where it was"
        )

        resolved = resolve_case_as_analyst(
            api,
            case["id"],
            roster.id_of("an1"),
            CaseAction.APPROVE,
            resolution_note="verified by owner",
        )
        assert resolved["state"] == CaseState.RESOLVED_APPROVE
        assert resolved["resolved_at"] is not None
        assert resolved["resolved_late"] is False

        owner = read_analyst(api, roster.id_of("an1"))
        assert owner["open_case_count"] == 0
        assert owner["resolved_case_count"] == 1
        bystander = read_analyst(api, roster.id_of("an2"))
        assert bystander["open_case_count"] == 0
        assert bystander["resolved_case_count"] == 0, (
            "the analyst who was refused is credited with nothing"
        )

        decided = read_assessment(api, assessment["id"])
        assert decided["state"] == AssessmentState.DECIDED_APPROVE
        assert decided["decision"] == Decision.REVIEW
        assert decided["decision_reason"] == DecisionReason.MANUAL_REVIEW
        assert decided["final_disposition"] == FinalDisposition.APPROVED

        customer = read_customer(api, env.customer_id)
        assert customer["approved_count"] == 1
        assert customer["lifetime_net_approved_cents"] == STANDARD_ORDER_CENTS
        assert assert_net_approved_ledger(api, env.customer_id, ADMIN) == (
            STANDARD_ORDER_CENTS
        )
