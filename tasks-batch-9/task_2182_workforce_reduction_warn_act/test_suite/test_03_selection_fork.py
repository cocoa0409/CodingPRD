"""Proposing selections, resolving the fork, and the compensating rescission."""

from test_helpers import (
    ALICE,
    BEN,
    CARLA,
    DAN,
    TEST_USERS,
    ApiErrorId,
    assert_selection,
    assert_site_headcount_identity,
    create_locked_plan,
    create_plan,
    create_selection_payload,
    decide,
    propose_batch,
    read_employee,
    read_plan,
    read_selection,
    read_site,
    rescind,
    setup_scenario,
    setup_site_with_roster,
    validate_error,
    validate_paginated,
    validate_success,
)

LEAD = TEST_USERS["lead_headers"]
UNKNOWN_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_unknown_selection_id_answers_the_selection_not_found_code(api):
    """PRD 2.6: "Path resource existence — identifiers in the URL are resolved
    left to right and each must exist, yielding whichever of
    `ERR_PLAN_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
    `ERR_SELECTION_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`,
    `ERR_DISCLOSURE_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`,
    `ERR_RESTRICTION_NOT_FOUND` or `ERR_WARN_RULE_NOT_FOUND` matches the missing
    segment (404). Applies to every path-parameterised endpoint."

    Design: Corner/entities/get_selection_with_unknown_id_returns_selection_not_found
    """
    response = api.get_selection(UNKNOWN_ID, LEAD)
    validate_error(response, ApiErrorId.ERR_SELECTION_NOT_FOUND.value)
    assert response.status_code == 404
    assert response.json()["response_type"] == "error"


def test_selection_against_an_unknown_plan_answers_plan_not_found(api):
    """PRD 2.6: "Body foreign-key existence — `plan_id`, `site_id`,
    `employee_id`, each element of `employee_ids`, `selection_id` and each
    element of `selection_ids` must resolve to a live record, yielding
    `ERR_PLAN_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND` or
    `ERR_SELECTION_NOT_FOUND` (404)."

    Design: Corner/entities/create_selection_with_unknown_plan_id_returns_plan_not_found
    """
    _site, employees = setup_site_with_roster((ALICE,), "TX")

    response = api.create_selection(
        {
            "plan_id": UNKNOWN_ID,
            "employee_id": employees[0]["id"],
            "proposed_separation_date": "2026-12-01",
            "criterion_scores": [{"criterion_code": "PERFORMANCE", "score": 72}],
        },
        LEAD,
    )
    validate_error(response, ApiErrorId.ERR_PLAN_NOT_FOUND.value)
    assert response.status_code == 404


def test_new_selection_starts_proposed_with_nothing_delivered(api):
    """PRD 3.3: "A newly created selection is persisted with `status` of
    `PROPOSED`, `exemption_reason` and `rescind_reason` null, `notice_status` of
    `NOT_DELIVERED`, `notice_script_code` and `notice_delivered_utc` null,
    `notice_days_before_separation` null, and `short_notice_acknowledged` false.
    Creating it recomputes the plan's `pool_count`."
    PRD 3.3: "For each criterion in the plan's locked `selection_criteria`, the
    criterion's `score` from the submitted sheet is multiplied by that
    criterion's `weight_pct` and the product is divided by 100; the resulting
    per-criterion contributions are summed across all locked criteria, and the
    sum is rounded half up to two decimal places."

    Design: Corner/state_machines/new_selection_starts_in_proposed_with_notice_not_delivered
    """
    site, employees = setup_site_with_roster((ALICE,), "TX")
    plan = create_locked_plan()

    selection = validate_success(
        api.create_selection(
            create_selection_payload(plan["id"], employees[0]["id"]), LEAD
        ),
        201,
    )
    assert_selection(selection)
    assert selection["status"] == "PROPOSED"
    assert selection["composite_score"] == 70.10
    assert selection["exemption_reason"] is None
    assert selection["rescind_reason"] is None
    assert selection["notice_status"] == "NOT_DELIVERED"
    assert selection["notice_script_code"] is None
    assert selection["notice_delivered_utc"] is None
    assert selection["notice_days_before_separation"] is None
    assert selection["short_notice_acknowledged"] is False

    assert read_employee(employees[0]["id"])["employment_status"] == "ACTIVE"
    assert read_site(site["id"])["pending_separation_count"] == 0
    plan = read_plan(plan["id"])
    assert plan["pool_count"] == 1
    assert plan["selected_count"] == 0


def test_composite_score_applies_the_locked_weights_not_a_plain_mean(api):
    """PRD 3.3: "For each criterion in the plan's locked `selection_criteria`,
    the criterion's `score` from the submitted sheet is multiplied by that
    criterion's `weight_pct` and the product is divided by 100; the resulting
    per-criterion contributions are summed across all locked criteria, and the
    sum is rounded half up to two decimal places."

    Design: Corner/calculations/selection_composite_score_applies_the_locked_criterion_weights
    """
    _site, employees = setup_site_with_roster((ALICE,), "TX")
    plan = create_locked_plan()

    selection = validate_success(
        api.create_selection(
            create_selection_payload(
                plan["id"],
                employees[0]["id"],
                criterion_scores=[
                    {"criterion_code": "PERFORMANCE", "score": 75},
                    {"criterion_code": "CRITICAL_SKILLS", "score": 63},
                    {"criterion_code": "TENURE", "score": 41},
                ],
            ),
            LEAD,
        ),
        201,
    )
    assert selection["composite_score"] == 64.60, (
        "37.5 + 18.9 + 8.2 = 64.60, not the unweighted mean 59.67"
    )
    assert selection["status"] == "PROPOSED"


def test_exempted_branch_touches_nothing_downstream(api):
    """PRD 3.3: "It touches nothing downstream at all: the employee's
    `employment_status` stays `ACTIVE`, their `separation_date` stays null, no
    site counter moves, no plan `warn_status` advances, and no disclosure or
    analysis is invalidated."
    PRD 3.3: "The only plan-level figure that changes is `pool_count` — an
    exempted person remains in the analysis pool — while `selected_count` is
    unaffected."

    Design: Corner/state_machines/exempt_branch_leaves_employee_and_site_counters_untouched
    """
    scn = setup_scenario(people=(ALICE, BEN), propose_indexes=(0,))
    selection_id = scn["selections"][0]["id"]

    exempted = validate_success(
        api.decide_selection(
            selection_id,
            {
                "decision": "EXEMPT",
                "exemption_reason": "Sole holder of a regulated certification.",
            },
            LEAD,
        )
    )
    assert exempted["status"] == "EXEMPTED"
    assert exempted["exemption_reason"] == "Sole holder of a regulated certification."

    employee = read_employee(scn["employees"][0]["id"])
    assert employee["employment_status"] == "ACTIVE"
    assert employee["separation_date"] is None

    site = read_site(scn["site"]["id"])
    assert site["active_headcount"] == 2
    assert site["pending_separation_count"] == 0
    assert site["warn_trigger_status"] == "NONE"

    plan = read_plan(scn["plan"]["id"])
    assert plan["selected_count"] == 0
    assert plan["pool_count"] == 1
    assert plan["earliest_separation_date"] is None


def test_deciding_an_exempted_selection_again_is_refused(api):
    """PRD 2.6: "Declared transition availability — the target resource must
    currently sit in a state from which the requested transition is declared,
    otherwise `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_SELECTION_STATE`,
    `ERR_INVALID_ANALYSIS_STATE`, `ERR_INVALID_NOTICE_STATE`,
    `ERR_INVALID_OFFER_STATE` or `ERR_INVALID_RESTRICTION_STATE` (409). Applies
    to every state-changing endpoint."

    Design: Corner/state_machines/decide_an_already_exempted_selection_returns_invalid_selection_state
    """
    scn = setup_scenario(people=(ALICE,), propose_indexes=(0,))
    selection_id = scn["selections"][0]["id"]
    decide(selection_id, "EXEMPT", "Sole holder of a regulated certification.")

    response = api.decide_selection(selection_id, {"decision": "SELECT"}, LEAD)
    validate_error(response, ApiErrorId.ERR_INVALID_SELECTION_STATE.value)
    assert response.status_code == 409

    assert read_selection(selection_id)["status"] == "EXEMPTED"
    assert read_employee(scn["employees"][0]["id"])["employment_status"] == "ACTIVE"


def test_second_live_proposal_for_one_employee_is_refused(api):
    """PRD 3.3: "An employee may hold at most one selection per plan in any
    status other than `RESCINDED`; a second live proposal for the same
    plan-and-employee pair is refused with `ERR_DUPLICATE_SELECTION`."

    Design: Corner/validations/duplicate_non_rescinded_selection_for_one_employee_is_rejected
    """
    scn = setup_scenario(people=(ALICE,), propose_indexes=(0,))

    response = api.create_selection(
        create_selection_payload(
            scn["plan"]["id"],
            scn["employees"][0]["id"],
            proposed_separation_date="2027-02-01",
            criterion_scores=[
                {"criterion_code": "PERFORMANCE", "score": 60},
                {"criterion_code": "CRITICAL_SKILLS", "score": 60},
                {"criterion_code": "TENURE", "score": 60},
            ],
        ),
        LEAD,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_SELECTION.value)
    assert response.status_code == 409

    assert read_plan(scn["plan"]["id"])["pool_count"] == 1
    rows, _meta = validate_paginated(
        api.list_selections(LEAD, params={"plan_id": scn["plan"]["id"]})
    )
    assert len(rows) == 1


def test_score_sheet_missing_a_locked_code_is_refused(api):
    """PRD 3.3: "neither a missing code nor an extra code is tolerated, and
    either failure is refused with `ERR_CRITERION_SCORE_MISMATCH`."

    Design: Corner/validations/criterion_scores_missing_a_locked_code_are_rejected
    """
    _site, employees = setup_site_with_roster((ALICE,), "TX")
    plan = create_locked_plan()

    response = api.create_selection(
        create_selection_payload(
            plan["id"],
            employees[0]["id"],
            criterion_scores=[
                {"criterion_code": "PERFORMANCE", "score": 72},
                {"criterion_code": "CRITICAL_SKILLS", "score": 55},
            ],
        ),
        LEAD,
    )
    validate_error(response, ApiErrorId.ERR_CRITERION_SCORE_MISMATCH.value)
    assert response.status_code == 422
    assert read_plan(plan["id"])["pool_count"] == 0


def test_selection_before_the_criteria_are_frozen_is_refused(api):
    """PRD 3.1: "Any attempt to create a selection while the plan's
    `criteria_status` is still `DRAFT` is refused with
    `ERR_CRITERIA_NOT_LOCKED`."

    Design: Corner/validations/selection_created_before_criteria_are_locked_is_rejected
    """
    _site, employees = setup_site_with_roster((ALICE,), "TX")
    plan = create_plan()

    response = api.create_selection(
        create_selection_payload(plan["id"], employees[0]["id"]), LEAD
    )
    validate_error(response, ApiErrorId.ERR_CRITERIA_NOT_LOCKED.value)
    assert response.status_code == 422
    assert read_plan(plan["id"])["criteria_status"] == "DRAFT"


def test_body_foreign_key_existence_outranks_the_criteria_lock_check(api):
    """PRD 2.6: "When a request violates more than one rule, exactly one error is
    returned, and it is always the violation with the lowest priority number in
    the ladder below."
    PRD 2.6: "Body foreign-key existence — `plan_id`, `site_id`, `employee_id`,
    each element of `employee_ids`, `selection_id` and each element of
    `selection_ids` must resolve to a live record, yielding `ERR_PLAN_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND` or `ERR_SELECTION_NOT_FOUND`
    (404)."
    PRD 2.10: "The same precedence extends to bodies: within a single request,
    path identifiers are resolved before body foreign keys, and body foreign keys
    are resolved before any business rule is evaluated."

    Design: Corner/validations/body_foreign_key_existence_outranks_criteria_not_locked
    """
    plan = create_plan()  # criteria deliberately left in DRAFT

    response = api.create_selection(
        create_selection_payload(plan["id"], UNKNOWN_ID), LEAD
    )
    error = validate_error(response, ApiErrorId.ERR_EMPLOYEE_NOT_FOUND.value)
    assert response.status_code == 404
    assert error["error_id"] != ApiErrorId.ERR_CRITERIA_NOT_LOCKED.value


def test_decide_batch_reports_selected_and_exempted_counts_separately(api):
    """PRD 3.3: "It accepts a `selection_ids` array, a shared `decision`, and an
    optional `exemption_reason`, and it processes the listed selections strictly
    in the order supplied. The full per-selection cascade described above runs
    for each row that takes the selected branch. The response reports
    `decided_count`, `selected_count` and `exempted_count`."

    Design: Corner/endpoints/decide_batch_reports_selected_and_exempted_counts_separately
    """
    site, employees = setup_site_with_roster((ALICE, BEN, CARLA, DAN), "TX")
    plan = create_locked_plan()
    batch = propose_batch(
        plan["id"],
        [employees[0]["id"], employees[2]["id"], employees[3]["id"], employees[1]["id"]],
    )
    assert batch["created_count"] == 4
    ids = batch["selection_ids"]

    first = validate_success(
        api.decide_batch(
            plan["id"], {"selection_ids": ids[:3], "decision": "SELECT"}, LEAD
        )
    )
    assert first["decided_count"] == 3
    assert first["selected_count"] == 3
    assert first["exempted_count"] == 0

    second = validate_success(
        api.decide_batch(
            plan["id"],
            {
                "selection_ids": [ids[3]],
                "decision": "EXEMPT",
                "exemption_reason": "Retained for critical skills.",
            },
            LEAD,
        )
    )
    assert second["decided_count"] == 1
    assert second["selected_count"] == 0
    assert second["exempted_count"] == 1

    plan = read_plan(plan["id"])
    assert plan["selected_count"] == 3
    assert plan["pool_count"] == 4
    site = read_site(site["id"])
    assert site["active_headcount"] == 1
    assert site["pending_separation_count"] == 3


def test_select_cascade_is_readable_immediately_after_the_same_request(api):
    """PRD 3.3: "The first hop moves the employee from `ACTIVE` to
    `PENDING_SEPARATION` and copies the selection's `proposed_separation_date`
    onto the employee's `separation_date`. The second hop, triggered by that
    employee's status change, recomputes the employee's site: `active_headcount`
    falls by one, `pending_separation_count` rises by one, and
    `window_start_date`, `federal_loss_count`, `state_loss_count`,
    `required_notice_days` and `warn_trigger_status` are all re-derived."
    PRD 3.8: "Second, the base week entitlement, tiered on the employee's
    `years_of_service` — the whole number of completed years obtained by taking
    the days from `hire_date` to `separation_date`, dividing by 365, and
    discarding any fraction."

    Design: Corner/consistency_model/select_cascade_is_visible_immediately_after_the_same_request
    """
    scn = setup_scenario(people=(ALICE, BEN), propose_indexes=(0,))

    decided = validate_success(
        api.decide_selection(
            scn["selections"][0]["id"], {"decision": "SELECT"}, LEAD
        )
    )
    assert decided["status"] == "SELECTED"

    employee = read_employee(scn["employees"][0]["id"])
    assert employee["employment_status"] == "PENDING_SEPARATION"
    assert employee["separation_date"] == "2026-12-01"
    assert employee["years_of_service"] == 11

    site = read_site(scn["site"]["id"])
    assert site["pending_separation_count"] == 1
    assert site["active_headcount"] == 1

    plan = read_plan(scn["plan"]["id"])
    assert plan["selected_count"] == 1
    assert plan["earliest_separation_date"] == "2026-12-01"


class TestHeadcountIdentityAcrossTheCompensatingAction:
    """The select/rescind pair conserves the site's headcount partition."""

    def test_partition_moves_one_unit_and_moves_it_back(self, api):
        """PRD 2.9: "at every moment, `roster_count` equals the sum of
        `active_headcount`, `pending_separation_count` and `separated_count`."
        PRD 2.9: "Deciding a selection into the selected branch and then
        rescinding it must return the site's `active_headcount` and
        `pending_separation_count` to their exact pre-decision values while
        `roster_count` never moves at all."

        Design: Difficulty/compensating_invariant/site_headcount_identity_survives_select_then_rescind
        """
        scn = setup_scenario(people=(ALICE, BEN, CARLA), propose_indexes=(0,))
        selection_id = scn["selections"][0]["id"]

        before = read_site(scn["site"]["id"])
        assert_site_headcount_identity(before)
        assert before["active_headcount"] == 3
        assert before["pending_separation_count"] == 0
        assert before["roster_count"] == 3

        decide(selection_id, "SELECT")
        mid = read_site(scn["site"]["id"])
        assert_site_headcount_identity(mid)
        assert mid["active_headcount"] == 2
        assert mid["pending_separation_count"] == 1
        assert mid["roster_count"] == 3

        rescind(selection_id, "Redeployed to a retained requisition.")
        after = read_site(scn["site"]["id"])
        assert_site_headcount_identity(after)
        assert after["active_headcount"] == before["active_headcount"] == 3
        assert after["pending_separation_count"] == 0
        assert after["separated_count"] == 0
        assert after["roster_count"] == 3

    def test_rescission_restores_the_employee_and_the_plan_rollups(self, api):
        """PRD 3.3: "First, the employee returns from `PENDING_SEPARATION` to
        `ACTIVE` and their `separation_date` is cleared to null."
        PRD 3.4: "The plan's `earliest_separation_date` is itself the earliest
        `proposed_separation_date` among its selections in `SELECTED` or
        `SEPARATED` status, and is null when that set is empty."

        Design: Difficulty/compensating_invariant/site_headcount_identity_survives_select_then_rescind
        """
        scn = setup_scenario(people=(ALICE, BEN, CARLA), propose_indexes=(0,))
        selection_id = scn["selections"][0]["id"]

        decide(selection_id, "SELECT")
        rescinded = rescind(selection_id, "Redeployed to a retained requisition.")

        assert rescinded["status"] == "RESCINDED"
        employee = read_employee(scn["employees"][0]["id"])
        assert employee["employment_status"] == "ACTIVE"
        assert employee["separation_date"] is None

        plan = read_plan(scn["plan"]["id"])
        assert plan["selected_count"] == 0
        assert plan["earliest_separation_date"] is None
