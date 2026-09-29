"""Competing rejections: which of two simultaneously violated rules wins
(PRD §2.9).
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_field,
    assert_no_write,
    assert_state,
    assert_two_decimals,
    draft_statement,
    notices_for_incident,
    open_incident,
    queue_notice,
    read_incident,
    read_notice,
    read_statement,
    read_task,
    refresh,
    set_clock,
    setup_activated_incident,
    setup_published_statement,
    submit_for_review,
    validate_error,
    validate_success,
)

# ---------------------------------------------------------------------------
# Existence (6) outranks incident response state (11) on notice creation
# ---------------------------------------------------------------------------


def test_an_unresolvable_statement_reference_outranks_the_monitoring_incident(api):
    """PRD §2.9: "checks are evaluated in the order below and the **first failure
    wins**" — "6. Every foreign key in the body resolves — the resource-specific
    not-found error (404)" comes before "11. The owning incident sits in the
    response dimension the operation requires ... giving
    `ERR_INCIDENT_NOT_ACTIVATED`".

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_outranks_incident_state_on_notice_create
    """
    set_clock("2026-08-10T09:00:00Z")
    scenario = setup_activated_incident(
        tier="SEV2", scenario_code="PRODUCT_RECALL", title="Battery supplier audit"
    )
    monitoring = open_incident(
        scenario["headers"]["lead"],
        title="Unverified rumour about a supplier",
        scenario_code="PRODUCT_RECALL",
    )

    validate_error(
        api.create_stakeholder_notice(
            {
                "incident_id": monitoring["id"],
                "statement_id": NON_EXISTENT_UUID,
                "audience": "EMPLOYEE",
                "estimated_reach": 1000,
            },
            scenario["headers"]["comms"],
        ),
        ApiErrorId.ERR_STATEMENT_NOT_FOUND,
        404,
    )

    assert notices_for_incident(monitoring["id"]) == [], (
        "a rejected notice creation must leave no row behind"
    )
    after = read_incident(monitoring["id"])
    assert_field(after, "response_state", "MONITORING", "incident")
    assert_no_write(monitoring, after, "incident")


def test_a_resolvable_statement_reference_lets_the_state_check_surface(api):
    """PRD §2.9 orders the foreign-key check ahead of the response-state check, so
    once the reference resolves the lower-ranked rule is the one that answers:
    PRD §3.6 requires that for notice creation "The incident must be
    `ACTIVATED`".

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_outranks_incident_state_on_notice_create
    """
    scenario = setup_published_statement(clock="2026-08-10T09:00:00Z", tier="SEV2")
    monitoring = open_incident(
        scenario["headers"]["lead"],
        title="Unverified rumour about a supplier",
        scenario_code="PRODUCT_RECALL",
    )

    validate_error(
        api.create_stakeholder_notice(
            {
                "incident_id": monitoring["id"],
                "statement_id": scenario["statement"]["id"],
                "audience": "EMPLOYEE",
                "estimated_reach": 1000,
            },
            scenario["headers"]["comms"],
        ),
        ApiErrorId.ERR_INCIDENT_NOT_ACTIVATED,
        409,
    )

    assert notices_for_incident(monitoring["id"]) == [], (
        "a rejected notice creation must leave no row behind"
    )
    assert_field(read_incident(monitoring["id"]), "response_state", "MONITORING", "incident")


# ---------------------------------------------------------------------------
# Task from-state (10) outranks the review deadline (20) on a decision
# ---------------------------------------------------------------------------


def _one_approval_recorded_then_the_deadline_passes():
    """A SEV2 statement submitted at 09:05 (deadline 09:35) whose incident-lead
    task was approved at 09:05, with the clock then moved to 09:40."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="REGULATORY_PROBE",
        title="Regulator letter leaked",
        seat_roles=["INCIDENT_LEAD", "LEGAL_COUNSEL"],
    )
    set_clock("2026-08-10T09:05:00Z")
    draft_statement(
        scenario,
        statement_type="HOLDING",
        body="We are cooperating with the authority and will not comment further today.",
    )
    statement = submit_for_review(scenario)
    assert statement["review_deadline_at"].startswith("2026-08-10T09:35:00"), (
        f"review_deadline_at must be 09:35, got {statement['review_deadline_at']}"
    )
    scenario["lead_task"] = next(
        task for task in scenario["tasks"] if task["required_team_role"] == "INCIDENT_LEAD"
    )
    scenario["counsel_task"] = next(
        task for task in scenario["tasks"] if task["required_team_role"] == "LEGAL_COUNSEL"
    )
    validate_success(
        api_decide(scenario["lead_task"]["id"], scenario["headers"]["lead"])
    )
    set_clock("2026-08-10T09:40:00Z")
    return scenario


def api_decide(task_id, headers):
    """Record an APPROVE decision through the declared decide endpoint."""
    return api_client.decide_approval_task(task_id, {"decision": "APPROVE"}, headers)


def test_an_already_decided_task_reports_its_state_not_the_missed_deadline(api):
    """PRD §2.9: "10. The target resource sits in a from-state the requested
    transition declares — one of ... `ERR_APPROVAL_TASK_NOT_PENDING` ... This
    check applies to every action endpoint" is evaluated before "20. The review
    deadline has not passed — `ERR_REVIEW_DEADLINE_PASSED` (409)".

    Design: Difficulty/priority_pair_validation_conflict/priority_task_state_outranks_review_deadline_on_decide
    """
    scenario = _one_approval_recorded_then_the_deadline_passes()
    before = read_task(scenario["lead_task"]["id"])

    validate_error(
        api_decide(scenario["lead_task"]["id"], scenario["headers"]["lead"]),
        ApiErrorId.ERR_APPROVAL_TASK_NOT_PENDING,
        409,
    )

    after = read_task(scenario["lead_task"]["id"])
    assert_state(after, "APPROVED", "incident-lead task")
    assert_no_write(before, after, "incident-lead task")
    statement = read_statement(scenario["statement"]["id"])
    assert_state(statement, "IN_REVIEW", "statement")
    assert_field(statement, "approvals_recorded", 1, "statement")
    assert statement["review_deadline_at"].startswith("2026-08-10T09:35:00")


def test_a_still_pending_sibling_reports_the_missed_deadline_on_the_same_clock(api):
    """PRD §2.9 orders the from-state check ahead of the deadline check, so on the
    very same clock reading the deadline rule is what answers for a task that is
    still `PENDING`: "20. The review deadline has not passed —
    `ERR_REVIEW_DEADLINE_PASSED` (409)".

    Design: Difficulty/priority_pair_validation_conflict/priority_task_state_outranks_review_deadline_on_decide
    """
    scenario = _one_approval_recorded_then_the_deadline_passes()
    before = read_task(scenario["counsel_task"]["id"])

    validate_error(
        api_decide(scenario["counsel_task"]["id"], scenario["headers"]["counsel"]),
        ApiErrorId.ERR_REVIEW_DEADLINE_PASSED,
        409,
    )

    after = read_task(scenario["counsel_task"]["id"])
    assert_state(after, "PENDING", "counsel task")
    assert_no_write(before, after, "counsel task")
    statement = read_statement(scenario["statement"]["id"])
    assert_state(statement, "IN_REVIEW", "statement")
    assert_field(statement, "approvals_recorded", 1, "statement")


# ---------------------------------------------------------------------------
# The embargo (21) outranks the audience sequence (26) on release
# ---------------------------------------------------------------------------


def _embargoed_customer_notice_behind_a_queued_employee_notice():
    """A SEV2 incident carrying a PUBLISHED HOLDING statement, a QUEUED EMPLOYEE
    notice at rank 1 and a QUEUED CUSTOMER notice at rank 2 embargoed until
    12:00, with the clock still at 09:00."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="PRODUCT_RECALL",
        title="Store closure rumours",
    )
    setup_published_statement(
        scenario,
        statement_type="HOLDING",
        body="No closure decisions have been made.",
    )
    queue_notice(scenario, audience="EMPLOYEE", estimated_reach=1000)
    queue_notice(
        scenario,
        audience="CUSTOMER",
        estimated_reach=800,
        embargo_until="2026-08-10T12:00:00Z",
    )
    return scenario


def test_an_unreached_embargo_outranks_the_unsettled_lower_rank(api):
    """PRD §2.9: "21. The notice embargo has been reached —
    `ERR_EMBARGO_NOT_REACHED` (409)" is evaluated before "26. The audience
    sequence is satisfied — `ERR_NOTICE_SEQUENCE_VIOLATION` (409)".

    Releasing the rank-2 CUSTOMER notice at 09:00 violates both rules at once —
    its embargo runs to 12:00 and the rank-1 EMPLOYEE notice is still QUEUED — and
    the embargo is the one that answers.

    Design: Difficulty/priority_pair_validation_conflict/priority_embargo_outranks_notice_sequence_on_release
    """
    scenario = _embargoed_customer_notice_behind_a_queued_employee_notice()
    customer = scenario["notices"]["CUSTOMER"]
    before = read_notice(customer["id"])

    validate_error(
        api.release_stakeholder_notice(customer["id"], scenario["headers"]["comms"], {}),
        ApiErrorId.ERR_EMBARGO_NOT_REACHED,
        409,
    )

    after = read_notice(customer["id"])
    assert_state(after, "QUEUED", "customer notice")
    assert_field(after, "sequence_rank", 2, "customer notice")
    assert_no_write(before, after, "customer notice")
    assert_state(
        read_notice(scenario["notices"]["EMPLOYEE"]["id"]), "QUEUED", "employee notice"
    )
    assert_two_decimals(
        refresh(scenario)["stakeholder_reach_index"], 0.00, "stakeholder_reach_index"
    )


def test_once_the_embargo_is_reached_the_sequence_rule_answers(api):
    """PRD §2.9 orders the embargo check ahead of the sequencing check, so once
    the embargo instant arrives the lower-ranked rule is what answers: PRD §3.6
    requires that "every notice on the same incident whose `sequence_rank` is
    strictly lower must already be settled, meaning in `RELEASED` or `CANCELLED`;
    otherwise the release is refused with `ERR_NOTICE_SEQUENCE_VIOLATION`".

    Design: Difficulty/priority_pair_validation_conflict/priority_embargo_outranks_notice_sequence_on_release
    """
    scenario = _embargoed_customer_notice_behind_a_queued_employee_notice()
    customer = scenario["notices"]["CUSTOMER"]
    set_clock("2026-08-10T12:00:00Z")
    before = read_notice(customer["id"])

    validate_error(
        api.release_stakeholder_notice(customer["id"], scenario["headers"]["comms"], {}),
        ApiErrorId.ERR_NOTICE_SEQUENCE_VIOLATION,
        409,
    )

    after = read_notice(customer["id"])
    assert_state(after, "QUEUED", "customer notice")
    assert_no_write(before, after, "customer notice")
    assert_state(
        read_notice(scenario["notices"]["EMPLOYEE"]["id"]), "QUEUED", "employee notice"
    )
    assert_two_decimals(
        refresh(scenario)["stakeholder_reach_index"], 0.00, "stakeholder_reach_index"
    )
