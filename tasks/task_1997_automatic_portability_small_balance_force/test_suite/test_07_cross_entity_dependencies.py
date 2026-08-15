"""Queue A difficulty tests: cross-entity state dependencies."""
from test_helpers import (
    api_client,
    validate_error,
    validate_success,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_participant_headers,
    make_provider_ops_headers,
    make_fiduciary_reviewer_headers,
    create_active_recordkeeper,
    create_plan,
    create_participant,
    create_open_batch,
    create_case,
    setup_transfer_ready_ira,
    setup_executed_batch_elected_ira,
    setup_reconciled_batch,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


class TestCaseCreateRequiresBatchOpen:
    def test_attach_to_locked_batch_rejected(self):
        """PRD §3.3: "the batch must still be `OPEN`, otherwise `ERR_INVALID_STATE`"

        Design: Difficulty/cross_entity_state_dependency/case_create_requires_batch_open
        """
        rk = create_active_recordkeeper()
        plan = create_plan(rk["id"])
        p_a = create_participant(ssn_hash="hash-a", full_name="Ann A")
        p_b = create_participant(ssn_hash="hash-b", full_name="Bob B")
        batch = create_open_batch(plan["id"])
        create_case(batch["id"], plan["id"], p_a["id"],
                    separation_date_balance_cents=50000,
                    processing_date_balance_cents=50000)
        get_success_data(api_client.lock_distribution_batch(batch["id"], SPONSOR))

        res = api_client.create_distribution_case({
            "distribution_batch_id": batch["id"],
            "plan_id": plan["id"],
            "participant_id": p_b["id"],
            "separation_date": "2026-07-16T00:00:00Z",
            "separation_date_balance_cents": 60000,
            "processing_date_balance_cents": 60000,
        }, SPONSOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_attach_to_locked_batch_creates_nothing(self):
        """PRD §3.3: "While the batch is `OPEN`, the sponsor attaches one distribution case
        per separated participant"
        PRD §3.3: "the batch must still be `OPEN`, otherwise `ERR_INVALID_STATE`"

        Design: Difficulty/cross_entity_state_dependency/case_create_requires_batch_open
        """
        rk = create_active_recordkeeper()
        plan = create_plan(rk["id"])
        p_a = create_participant(ssn_hash="hash-a", full_name="Ann A")
        p_b = create_participant(ssn_hash="hash-b", full_name="Bob B")
        batch = create_open_batch(plan["id"])
        create_case(batch["id"], plan["id"], p_a["id"],
                    separation_date_balance_cents=50000,
                    processing_date_balance_cents=50000)
        get_success_data(api_client.lock_distribution_batch(batch["id"], SPONSOR))
        res = api_client.create_distribution_case({
            "distribution_batch_id": batch["id"],
            "plan_id": plan["id"],
            "participant_id": p_b["id"],
            "separation_date": "2026-07-16T00:00:00Z",
            "separation_date_balance_cents": 60000,
            "processing_date_balance_cents": 60000,
        }, SPONSOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        # Still exactly one case in the batch.
        cases, meta = validate_paginated(api_client.list_distribution_cases(
            OPS, params={"distribution_batch_id": batch["id"]}))
        assert meta["total_count"] == 1


class TestTransferRequiresRecordkeeperActive:
    def _setup(self):
        """IRA MATCHED, prenotice delivered 2026-08-01 and window elapsed (clock
        2026-09-01); then RK-B SUSPENDED."""
        ctx = setup_transfer_ready_ira(balance=300000, clock="2026-09-01T00:00:00Z")
        get_success_data(api_client.suspend_recordkeeper(ctx["rk_b"]["id"], OPS))
        ctx["ira"] = get_success_data(
            api_client.get_safe_harbor_ira(ctx["ira"]["id"], OPS))
        return ctx

    def test_transfer_blocked_when_recordkeeper_suspended(self):
        """PRD §3.7: "The match's recordkeeper must still be `ACTIVE`
        (`ERR_RECORDKEEPER_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/transfer_requires_recordkeeper_active
        """
        ctx = self._setup()
        res = api_client.create_transfer(
            ctx["ira"]["id"],
            {"expected_ira_version": ctx["ira"]["version"]},
            OPS,
        )
        validate_error(res, ApiErrorId.ERR_RECORDKEEPER_NOT_ACTIVE, 422)

    def test_failed_transfer_leaves_ira_matched(self):
        """PRD §3.7: "The match's recordkeeper must still be `ACTIVE`
        (`ERR_RECORDKEEPER_NOT_ACTIVE`)."
        PRD §3.7: "With a unique `CONFIRMED` match in hand and the IRA `MATCHED`,
        `ProviderOps` initiates the plan-to-plan transfer"

        Design: Difficulty/cross_entity_state_dependency/transfer_requires_recordkeeper_active
        """
        ctx = self._setup()
        res = api_client.create_transfer(
            ctx["ira"]["id"],
            {"expected_ira_version": ctx["ira"]["version"]},
            OPS,
        )
        validate_error(res, ApiErrorId.ERR_RECORDKEEPER_NOT_ACTIVE)
        ira = get_success_data(api_client.get_safe_harbor_ira(ctx["ira"]["id"], OPS))
        assert ira["ira_status"] == "MATCHED"


class TestReviewRequiresBatchReconciled:
    def test_review_on_executed_batch_rejected(self):
        """PRD §3.9: "A `FiduciaryReviewer` opens a review by naming the
        `distribution_batch_id` and a coverage window — `period_start` inclusive,
        `period_end` exclusive. The batch must be `RECONCILED`, otherwise
        `ERR_INVALID_STATE`"

        Design: Difficulty/cross_entity_state_dependency/review_requires_batch_reconciled
        """
        ctx = setup_executed_batch_elected_ira(balance=300000)
        # Settle the case (IRA established) but do NOT reconcile the batch.
        get_success_data(api_client.create_safe_harbor_ira(
            {"distribution_case_id": ctx["case"]["id"]}, OPS))
        res = api_client.create_fiduciary_review(
            {"distribution_batch_id": ctx["batch"]["id"],
             "period_start": "2026-08-01T00:00:00Z",
             "period_end": "2026-09-01T00:00:00Z"},
            make_fiduciary_reviewer_headers("fid_rev_1"),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_rejected_review_creates_no_row(self):
        """PRD §3.9: "The batch must be `RECONCILED`, otherwise `ERR_INVALID_STATE`"

        Design: Difficulty/cross_entity_state_dependency/review_requires_batch_reconciled
        """
        ctx = setup_executed_batch_elected_ira(balance=300000)
        get_success_data(api_client.create_safe_harbor_ira(
            {"distribution_case_id": ctx["case"]["id"]}, OPS))
        res = api_client.create_fiduciary_review(
            {"distribution_batch_id": ctx["batch"]["id"],
             "period_start": "2026-08-01T00:00:00Z",
             "period_end": "2026-09-01T00:00:00Z"},
            make_fiduciary_reviewer_headers("fid_rev_1"),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        reviews, meta = validate_paginated(api_client.list_fiduciary_reviews(
            OPS, params={"distribution_batch_id": ctx["batch"]["id"]}))
        assert meta["total_count"] == 0
        assert reviews == []
