"""Non-standard term review workflow and review-task pagination (PRD §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    create_customer, create_contract, create_ssp, add_pob, add_clause,
    submit_contract, make_reviewer_headers,
    setup_contract_in_review_with_clause,
)


class TestTaskClaimingAndOwnership:
    def test_claim_stamps_reviewer_and_moves_in_review(self, api):
        """PRD §3.2: "Claiming a task moves it `ASSIGNED → IN_REVIEW` and stamps
        `reviewer_user_id` with the claimant's `X-User-ID`."

        Design: Difficulty/non_linear_state_machine/review_task_rework_cycle
        """
        setup = setup_contract_in_review_with_clause({"clause_code": "NS-1"})
        rev1 = make_reviewer_headers("rev-1")
        task = validate_success(api.start_review_task(setup["task"]["id"], rev1))
        assert task["status"] == "IN_REVIEW"
        assert task["reviewer_user_id"] == "rev-1"

    def test_other_reviewer_cannot_recommend_unclaimed_task(self, api):
        """PRD §3.2: "The claiming reviewer — and only that reviewer — then
        submits a `recommendation` of `APPROVE` or `REJECT`, optionally
        accompanied by a free-text `note`; a recommendation attempted by anyone
        other than the claiming reviewer is rejected with `ERR_NOT_TASK_OWNER`
        (HTTP 403)."

        Design: Corner/rbac/other_reviewer_cannot_recommend_unclaimed_task
        """
        setup = setup_contract_in_review_with_clause(
            {"clause_code": "NS-1", "clause_type": "PENALTY"}
        )
        task_id = setup["task"]["id"]
        validate_success(api.start_review_task(task_id, make_reviewer_headers("rev-1")))
        resp = api.recommend_review_task(
            task_id, {"recommendation": "APPROVE"}, make_reviewer_headers("rev-2")
        )
        validate_error(resp, ApiErrorId.ERR_NOT_TASK_OWNER, 403)

    def test_rejected_recommendation_keeps_task_in_review(self, api):
        """PRD §3.2: "a recommendation attempted by anyone other than the
        claiming reviewer is rejected with `ERR_NOT_TASK_OWNER` (HTTP 403)."

        Design: Corner/rbac/other_reviewer_cannot_recommend_unclaimed_task
        """
        setup = setup_contract_in_review_with_clause({"clause_code": "NS-1"})
        task_id = setup["task"]["id"]
        validate_success(api.start_review_task(task_id, make_reviewer_headers("rev-1")))
        validate_error(
            api.recommend_review_task(task_id, {"recommendation": "REJECT"},
                                      make_reviewer_headers("rev-2")),
            ApiErrorId.ERR_NOT_TASK_OWNER, 403,
        )
        task = validate_success(api.get_review_task(task_id, make_reviewer_headers("rev-1")))
        assert task["status"] == "IN_REVIEW"
        assert task.get("recommendation") is None
        assert task.get("recommended_by_user_id") is None


class TestReworkCycle:
    def _recommended_task(self, api):
        setup = setup_contract_in_review_with_clause({
            "clause_code": "NS-1",
            "clause_type": "TERMINATION_FOR_CONVENIENCE",
            "clause_text": "customer may terminate for convenience",
        })
        task_id = setup["task"]["id"]
        rev1 = make_reviewer_headers("rev-1")
        validate_success(api.start_review_task(task_id, rev1))
        validate_success(api.recommend_review_task(
            task_id, {"recommendation": "APPROVE", "note": "looks fine"}, rev1))
        return setup, task_id, rev1

    def test_return_decision_loops_back_and_clears_recommendation(self, api):
        """PRD §3.2: "A decision of `RETURN` is the rework loop: the task moves
        back `RECOMMENDED → IN_REVIEW`, the `recommendation` and
        `recommended_by_user_id` are cleared, and the original reviewer keeps
        the task."

        Design: Difficulty/non_linear_state_machine/review_task_rework_cycle
        """
        _, task_id, _ = self._recommended_task(api)
        rev2 = make_reviewer_headers("rev-2")
        task = validate_success(api.decide_review_task(
            task_id, {"decision": "RETURN", "note": "need legal wording check"}, rev2))
        assert task["status"] == "IN_REVIEW"
        assert task.get("recommendation") is None
        assert task.get("recommended_by_user_id") is None
        assert task["reviewer_user_id"] == "rev-1", "original reviewer keeps the task"

    def test_second_round_reaches_decided_and_approves_clause(self, api):
        """PRD §3.2: "A decision of `APPROVED` or `REJECTED` moves the task
        `RECOMMENDED → DECIDED`, records `decided_by_user_id`, and sets the
        reviewed clause's `status` to `APPROVED` or `REJECTED` accordingly."

        Design: Difficulty/non_linear_state_machine/review_task_rework_cycle
        """
        setup, task_id, rev1 = self._recommended_task(api)
        rev2 = make_reviewer_headers("rev-2")
        validate_success(api.decide_review_task(task_id, {"decision": "RETURN"}, rev2))
        validate_success(api.recommend_review_task(
            task_id, {"recommendation": "APPROVE", "note": "wording confirmed"}, rev1))
        final = validate_success(api.decide_review_task(task_id, {"decision": "APPROVED"}, rev2))
        assert final["status"] == "DECIDED"
        assert final["decided_by_user_id"] == "rev-2"
        clauses = validate_paginated(api.list_clauses(setup["contract"]["id"], rev2))[0]
        clause = next(c for c in clauses if c["id"] == setup["clause"]["id"])
        assert clause["status"] == "APPROVED"

    def test_recommender_cannot_decide(self, api):
        """PRD §3.2: "segregation of duties forbids the recommender from
        deciding, so a decider whose `X-User-ID` equals `recommended_by_user_id`
        is rejected with `ERR_SOD_VIOLATION` (§2.10)."

        Design: Difficulty/non_linear_state_machine/review_task_rework_cycle
        """
        _, task_id, rev1 = self._recommended_task(api)
        resp = api.decide_review_task(task_id, {"decision": "APPROVED"}, rev1)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 409)
        task = validate_success(api.get_review_task(task_id, rev1))
        assert task["status"] == "RECOMMENDED"

    def test_rejected_decision_marks_clause_rejected(self, api):
        """PRD §3.2: "A decision of `APPROVED` or `REJECTED` moves the task
        `RECOMMENDED → DECIDED`, records `decided_by_user_id`, and sets the
        reviewed clause's `status` to `APPROVED` or `REJECTED` accordingly."

        Design: Difficulty/non_linear_state_machine/review_task_rework_cycle
        """
        setup, task_id, rev1 = self._recommended_task(api)
        rev2 = make_reviewer_headers("rev-2")
        validate_success(api.decide_review_task(task_id, {"decision": "REJECTED"}, rev2))
        clauses = validate_paginated(
            api.list_clauses(setup["contract"]["id"], rev2))[0]
        clause = next(c for c in clauses if c["id"] == setup["clause"]["id"])
        assert clause["status"] == "REJECTED"


class TestSubmitSpawnsTasks:
    def test_submit_spawns_one_task_per_pending_nonstandard_clause(self, api, reviewer_headers):
        """PRD §3.2: "As the contract enters review, the system spawns one
        review task per clause that is non-standard and still `PENDING_REVIEW`;
        each task is created in `ASSIGNED` status with its `clause_id` pointing
        at the clause under review, its `contract_id` pointing at the owning
        contract, and its `reviewer_user_id` still null."

        Design: Corner/endpoints/review_tasks_list_paginates_with_limit_offset
        """
        create_ssp("WIDGET", region="US", ssp_cents=100000)
        customer = create_customer(legal_name="Page Co", external_ref="PAGE-1")
        contract = create_contract(customer["id"], contract_ref="C-PAGE")
        add_pob(contract["id"], pob_ref="P1")
        add_clause(contract["id"], clause_code="N1", clause_type="PENALTY", is_non_standard=True)
        add_clause(contract["id"], clause_code="N2", clause_type="RIGHT_OF_RETURN", is_non_standard=True)
        add_clause(contract["id"], clause_code="N3", clause_type="MOST_FAVORED_CUSTOMER", is_non_standard=True)
        submit_contract(contract["id"])
        tasks = validate_paginated(
            api.list_review_tasks(reviewer_headers, params={"contract_id": contract["id"]})
        )[0]
        assert len(tasks) == 3
        for task in tasks:
            assert task["status"] == "ASSIGNED"
            assert task["contract_id"] == contract["id"]
            assert task["reviewer_user_id"] is None
        assert {t["clause_id"] for t in tasks} == {
            c["id"] for c in validate_paginated(api.list_clauses(contract["id"], reviewer_headers))[0]
        }


class TestPagination:
    def test_review_tasks_paginate_with_limit_and_offset(self, api, reviewer_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return" and "The `offset` parameter specifies the number of
        items to skip".
        PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/review_tasks_list_paginates_with_limit_offset
        """
        create_ssp("WIDGET", region="US", ssp_cents=100000)
        customer = create_customer(legal_name="Page Co", external_ref="PAGE-2")
        contract = create_contract(customer["id"], contract_ref="C-PAGE2")
        add_pob(contract["id"], pob_ref="P1")
        for code, ctype in (("N1", "PENALTY"), ("N2", "RIGHT_OF_RETURN"),
                            ("N3", "MOST_FAVORED_CUSTOMER")):
            add_clause(contract["id"], clause_code=code, clause_type=ctype, is_non_standard=True)
        submit_contract(contract["id"])

        page1, meta1 = validate_paginated(api.list_review_tasks(
            reviewer_headers,
            params={"contract_id": contract["id"], "limit": 2, "offset": 0},
        ))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_review_tasks(
            reviewer_headers,
            params={"contract_id": contract["id"], "limit": 2, "offset": 2},
        ))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        # Pages partition the spawned task set.
        all_ids = [t["id"] for t in page1 + page2]
        assert len(set(all_ids)) == 3
