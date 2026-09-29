"""Executing the reduction and freezing the vacated seats."""

from test_helpers import (
    NY_NOTICE_CONTENT,
    PRIYA,
    TEST_USERS,
    USER_IDS,
    ApiErrorId,
    assert_position_restriction,
    assert_site_headcount_identity,
    create_employee_payload,
    deliver_notice,
    draft_warn_notice,
    execute_plan,
    issue_warn_notice,
    list_restrictions,
    make_counsel_headers,
    read_employee,
    read_restriction,
    read_selection,
    read_site,
    render_legal_decision,
    run_and_clear_analysis,
    setup_executed_scenario,
    setup_ny_triggered_scenario,
    submit_for_review,
    validate_error,
    validate_paginated,
    validate_success,
)

LEAD = TEST_USERS["lead_headers"]
COUNSEL = TEST_USERS["counsel_headers"]


class TestExecutionCascadeDepth:
    """One execute reaches selections, employees, seats and site counters."""

    @staticmethod
    def _ready_to_execute():
        scn = setup_ny_triggered_scenario()
        plan_id = scn["plan"]["id"]
        run_and_clear_analysis(plan_id, justification="Both eliminated roles documented.")
        submit_for_review(plan_id)
        render_legal_decision(plan_id, "APPROVE")
        deliver_notice(scn["selection_by_index"][0]["id"], "MANAGER_SCRIPT_UNION")
        deliver_notice(scn["selection_by_index"][2]["id"], "MANAGER_SCRIPT_UNION")
        notice = draft_warn_notice(
            plan_id, scn["site"]["id"], "STATE", NY_NOTICE_CONTENT
        )
        issue_warn_notice(notice["id"])
        return scn

    def test_selections_and_employees_reach_separated_together(self, api):
        """PRD 3.10: "Execution advances `approval_status` from `APPROVED` to
        `EXECUTED` and runs a three-hop cascade. In the first hop every selection
        of the plan in `SELECTED` status moves to `SEPARATED`, each incrementing
        its own `version` by 1. In the second hop, because a selection entered
        `SEPARATED`, its employee moves from `PENDING_SEPARATION` to
        `SEPARATED`."
        PRD 3.10: "On the compliance axis, `warn_status` becomes
        `NOTICE_PERIOD_SATISFIED` in the same request, arriving there from
        `NOTICES_ISSUED` on a plan that had triggered sites, and directly from
        `NOT_ASSESSED` on a plan no site of which was ever triggered."

        Design: Difficulty/transitive_cascade/plan_execute_chains_selection_then_employee_then_position_restriction
        """
        scn = self._ready_to_execute()

        executed = execute_plan(scn["plan"]["id"])
        assert executed["approval_status"] == "EXECUTED"
        assert executed["warn_status"] == "NOTICE_PERIOD_SATISFIED"

        assert read_selection(scn["selection_by_index"][0]["id"])["status"] == "SEPARATED"
        assert read_selection(scn["selection_by_index"][2]["id"])["status"] == "SEPARATED"
        assert read_employee(scn["employees"][0]["id"])["employment_status"] == "SEPARATED"
        assert read_employee(scn["employees"][2]["id"])["employment_status"] == "SEPARATED"
        assert read_employee(scn["employees"][1]["id"])["employment_status"] == "ACTIVE"

    def test_each_separated_seat_is_frozen_and_the_partition_rebalances(self, api):
        """PRD 3.10: "In the third hop, because an employee entered `SEPARATED`,
        a position restriction is created for that person in status `RESTRICTED`
        with `restricted_until_utc` set to the current logical clock plus 90
        days, and that employee's site recomputes its counters —
        `pending_separation_count` falls by one and `separated_count` rises by
        one, with `roster_count` unchanged throughout, exactly as the headcount
        identity of §2.9 requires."
        PRD 3.10: "Restrictions may be listed with optional `employee_id`,
        `site_id`, `job_title` and `restriction_status` filters — that listing is
        the only discovery channel for rows the cascade created."

        Design: Difficulty/transitive_cascade/plan_execute_chains_selection_then_employee_then_position_restriction
        """
        scn = self._ready_to_execute()

        execute_plan(scn["plan"]["id"])

        site = read_site(scn["site"]["id"])
        assert_site_headcount_identity(site)
        assert site["roster_count"] == 3
        assert site["active_headcount"] == 1
        assert site["pending_separation_count"] == 0
        assert site["separated_count"] == 2

        rows, _meta = validate_paginated(
            api.list_position_restrictions(
                COUNSEL, params={"site_id": scn["site"]["id"]}
            )
        )
        assert len(rows) == 2
        for restriction in rows:
            assert_position_restriction(restriction)
            assert restriction["restriction_status"] == "RESTRICTED"
            assert restriction["restricted_until_utc"] == "2026-10-30T00:00:00.000Z"
            assert restriction["waiver_reason"] is None
            assert restriction["waived_by_user_id"] is None


def test_waiving_a_restriction_unblocks_the_frozen_seat(api):
    """PRD 3.10: "`EmploymentCounsel` may waive it (`RESTRICTED → WAIVED`) with a
    `waiver_reason` that is supplied and non-empty, recording that reason
    together with `waived_by_user_id` from the acting `X-User-ID` and
    incrementing the restriction's `version` by 1; waiving a restriction that is
    not `RESTRICTED` is refused with `ERR_INVALID_RESTRICTION_STATE`."
    PRD 3.10: "Either route unblocks hiring for that `site_id` and `job_title`
    pair."
    PRD 3.10: "Each restriction records the separated incumbent as `employee_id`,
    copies that person's `site_id` and `job_title` at creation, and holds
    `restriction_status` of `RESTRICTED` with `waiver_reason` and
    `waived_by_user_id` null."

    Design: Corner/state_machines/waive_position_restriction_unblocks_the_frozen_seat
    """
    scn = setup_executed_scenario()
    restrictions = list_restrictions(employee_id=scn["employees"][0]["id"])
    assert len(restrictions) == 1
    restriction = restrictions[0]
    assert restriction["restriction_status"] == "RESTRICTED"

    waived = validate_success(
        api.waive_position_restriction(
            restriction["id"],
            {"waiver_reason": "Business-critical requisition approved by the CHRO."},
            make_counsel_headers(USER_IDS["COUNSEL_2"]),
        )
    )
    assert waived["restriction_status"] == "WAIVED"
    assert waived["waived_by_user_id"] == USER_IDS["COUNSEL_2"]

    stored = read_restriction(restriction["id"])
    assert stored["waiver_reason"] == (
        "Business-critical requisition approved by the CHRO."
    )
    assert stored["restricted_until_utc"] == "2026-10-30T00:00:00.000Z"

    backfill = validate_success(
        api.create_employee(
            create_employee_payload(scn["site"]["id"], PRIYA), LEAD
        ),
        201,
    )
    assert backfill["job_title"] == "Senior Analyst"
    assert backfill["employment_status"] == "ACTIVE"

    site = read_site(scn["site"]["id"])
    assert site["roster_count"] == 3
    assert site["active_headcount"] == 2
    assert site["separated_count"] == 1


def test_the_restriction_key_is_the_site_and_job_title_pair(api):
    """PRD 3.2: "Before a hire is admitted — whether individually or through a
    roster import — the system checks whether any position restriction in status
    `RESTRICTED` matches the incoming person's `site_id` and `job_title` pair. If
    one does, the hire is refused with `ERR_BACKFILL_RESTRICTED`."
    PRD 3.10: "`EmploymentCounsel` may waive it (`RESTRICTED → WAIVED`) with a
    `waiver_reason` that is supplied and non-empty, recording that reason
    together with `waived_by_user_id` from the acting `X-User-ID` and
    incrementing the restriction's `version` by 1; waiving a restriction that is
    not `RESTRICTED` is refused with `ERR_INVALID_RESTRICTION_STATE`."

    Design: Corner/errors/error_backfill_restricted_and_a_second_waiver_are_rejected
    """
    scn = setup_executed_scenario()
    restrictions = list_restrictions(
        site_id=scn["site"]["id"], restriction_status="RESTRICTED"
    )
    assert len(restrictions) == 1
    restriction = restrictions[0]
    assert restriction["job_title"] == "Senior Analyst"

    blocked = api.create_employee(
        create_employee_payload(scn["site"]["id"], PRIYA), LEAD
    )
    validate_error(blocked, ApiErrorId.ERR_BACKFILL_RESTRICTED.value)
    assert blocked.status_code == 409

    admitted = validate_success(
        api.create_employee(
            create_employee_payload(scn["site"]["id"], PRIYA, job_title="Analyst II"),
            LEAD,
        ),
        201,
    )
    assert admitted["job_title"] == "Analyst II"

    waived = validate_success(
        api.waive_position_restriction(
            restriction["id"], {"waiver_reason": "Regulatory coverage gap."}, COUNSEL
        )
    )
    assert waived["restriction_status"] == "WAIVED"

    second = api.waive_position_restriction(
        restriction["id"],
        {"waiver_reason": "Second attempt."},
        make_counsel_headers(USER_IDS["COUNSEL_2"]),
    )
    validate_error(second, ApiErrorId.ERR_INVALID_RESTRICTION_STATE.value)
    assert second.status_code == 409

    stored = read_restriction(restriction["id"])
    assert stored["waived_by_user_id"] == USER_IDS["COUNSEL"]
    assert stored["waiver_reason"] == "Regulatory coverage gap."
    assert read_site(scn["site"]["id"])["roster_count"] == 3
