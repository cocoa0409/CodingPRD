"""PostingBatch lifecycle: invalid transitions, date uniqueness, business-day
rule, settle ordering, cancellation, and fee listing (PRD §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    SATURDAY,
    SUNDAY,
    authorize,
    get_batch,
    list_fees,
    make_opted_in_account,
    make_program,
    open_batch,
    seal_batch,
    set_clock,
    settle_batch,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK


class TestSealSettledBatchRejected:
    def test_seal_only_valid_from_open(self, api):
        """PRD §3.4: "When the clerk seals an `OPEN` batch — sealing from any
        other status is rejected with `ERR_INVALID_STATE_TRANSITION`".

        Design: Corner/state_machines/seal_settled_batch_returns_invalid_state
        """
        program = make_program(name="OD-SM1")
        batch = open_batch(program["id"], "2026-08-03")
        seal_batch(batch["id"])
        settle_batch(batch["id"])

        resp = api.seal_batch(batch["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_batch(batch["id"])
        assert after["status"] == "SETTLED"
        assert after["fees_assessed_count"] == 0


class TestSettleOpenBatchRejected:
    def test_settle_requires_sealed(self, api):
        """PRD §3.5: "An `OperationsClerk` settles a `SEALED` batch — settling
        from any other status is an invalid transition".

        Design: Corner/state_machines/settle_open_batch_returns_invalid_state
        """
        program = make_program(name="OD-SM2")
        batch = open_batch(program["id"], "2026-08-03")
        resp = api.settle_batch(batch["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestDuplicateBatchDateRejected:
    def test_one_batch_per_program_per_business_date(self, api):
        """PRD §3.4: "at most one non-`CANCELLED` batch may exist per program
        per business date: a duplicate is rejected with
        `ERR_BATCH_ALREADY_EXISTS`, though a `CANCELLED` batch frees its date
        for reuse."

        Design: Corner/validations/duplicate_batch_date_rejected
        """
        program = make_program(name="OD-V7")
        open_batch(program["id"], "2026-08-03")
        resp = api.create_batch(
            {"program_id": program["id"], "business_date": "2026-08-03"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_BATCH_ALREADY_EXISTS)
        other = validate_success(
            api.create_batch(
                {"program_id": program["id"], "business_date": "2026-08-04"},
                CLERK),
            201)
        assert other["status"] == "OPEN"


class TestWeekendBatchDateRejected:
    def test_saturday_and_sunday_dates_rejected(self, api):
        """PRD §2.4: "A batch creation naming a Saturday or Sunday date is
        rejected with `ERR_NON_BUSINESS_DAY` (HTTP 422)."

        Design: Corner/validations/weekend_batch_date_rejected
        """
        program = make_program(name="OD-V8")
        for weekend_date in (SATURDAY, SUNDAY):
            resp = api.create_batch(
                {"program_id": program["id"], "business_date": weekend_date},
                CLERK)
            validate_error(resp, ApiErrorId.ERR_NON_BUSINESS_DAY)


class TestSettleWithEarlierUnsettledBatchRejected:
    def test_batches_must_settle_in_business_date_order(self, api):
        """PRD §3.5: "but only once every earlier-dated batch of the same
        program has reached `SETTLED` or `CANCELLED`; if an earlier batch is
        still open or sealed, the settle is rejected with
        `ERR_EARLIER_BATCH_UNSETTLED`."

        Design: Corner/validations/settle_with_earlier_unsettled_batch_rejected
        """
        program = make_program(name="OD-V9")
        batch1 = open_batch(program["id"], "2026-08-03")
        batch2 = open_batch(program["id"], "2026-08-04")
        seal_batch(batch1["id"])
        seal_batch(batch2["id"])

        resp = api.settle_batch(batch2["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_EARLIER_BATCH_UNSETTLED)

        assert settle_batch(batch1["id"])["status"] == "SETTLED"
        assert settle_batch(batch2["id"])["status"] == "SETTLED"


class TestCancelOpenBatchFreesDate:
    def test_cancel_frees_date_and_cancels_terminal_for_settle(self, api):
        """PRD §3.4: "An `OPEN` batch that has not yet had any transaction
        assigned to it may be cancelled outright, moving it to `CANCELLED`;
        once a seal has consumed the batch, cancellation is no longer a valid
        transition."
        PRD §3.4: "a duplicate is rejected with `ERR_BATCH_ALREADY_EXISTS`,
        though a `CANCELLED` batch frees its date for reuse."

        Design: Corner/endpoints/cancel_open_batch_frees_date
        """
        program = make_program(name="OD-EP5")
        batch = open_batch(program["id"], "2026-08-03")

        cancelled = validate_success(api.cancel_batch(batch["id"], CLERK))
        assert cancelled["status"] == "CANCELLED"

        reopened = validate_success(
            api.create_batch(
                {"program_id": program["id"], "business_date": "2026-08-03"},
                CLERK),
            201)
        assert reopened["status"] == "OPEN"

        resp = api.settle_batch(batch["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestFeeStartsAssessedUntilSettle:
    def test_fee_born_assessed_with_null_posted_date_then_posted(self, api):
        """PRD §3.4: "`waived_cents` starts at zero, `outstanding_cents` is the
        amount minus the waived portion, and `posted_date` remains null until
        settle."
        PRD §3.5: "Settlement first moves every `ASSESSED` fee created by the
        seal to `POSTED`, stamping `posted_date` with the batch's business
        date".

        Design: Corner/state_machines/fee_starts_assessed_until_settle
        """
        program = make_program(name="OD-SM10")
        account, _ = make_opted_in_account(program["id"], holder_name="H SM10")
        batch = open_batch(program["id"], "2026-08-03")
        authorize(account["id"], "DEBIT_ONE_TIME", 2000)
        seal_batch(batch["id"])

        fee = list_fees(account_id=account["id"])[0]
        assert fee["status"] == "ASSESSED"
        assert fee["posted_date"] is None

        settle_batch(batch["id"])
        settled_fee = api.get_fee(fee["id"], ADMIN)
        data = validate_success(settled_fee)
        assert data["status"] == "POSTED"
        assert data["posted_date"] == "2026-08-03"


class TestFeesListPagination:
    def test_limit_offset_windowing_over_three_fees(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return." and "The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated list-based responses include the following fields
        in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/fees_list_pagination_limit_offset
        """
        program = make_program(name="OD-EP1", de_minimis_threshold_cents=100)
        account, _ = make_opted_in_account(program["id"], holder_name="H EP1")
        batch = open_batch(program["id"], "2026-08-03")
        for clock in ("2026-08-03T09:00:00Z", "2026-08-03T09:01:00Z",
                      "2026-08-03T09:02:00Z"):
            set_clock(clock)
            authorize(account["id"], "DEBIT_ONE_TIME", 1000)
        seal_batch(batch["id"])
        assert len(list_fees(account_id=account["id"])) == 3

        page1, meta1 = validate_paginated(api.list_fees(
            ADMIN, params={"account_id": account["id"], "limit": 2,
                           "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_fees(
            ADMIN, params={"account_id": account["id"], "limit": 2,
                           "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestFeesListFilterByStatus:
    def test_status_filter_partitions_fees_across_settle(self, api):
        """PRD §3.4: "The fee ledger can be queried with optional
        `account_id`, `batch_id`, `transaction_id` (a filter returning an array
        of zero or one element), `status`, and `fee_type` filters."
        PRD §3.5: "Settlement first moves every `ASSESSED` fee created by the
        seal to `POSTED`".

        Design: Corner/endpoints/fees_list_filter_by_status
        """
        program = make_program(name="OD-EP2")
        account, _ = make_opted_in_account(program["id"], holder_name="H EP2")
        batch = open_batch(program["id"], "2026-08-03")
        authorize(account["id"], "DEBIT_ONE_TIME", 2000)
        seal_batch(batch["id"])

        assessed = list_fees(account_id=account["id"], status="ASSESSED")
        posted = list_fees(account_id=account["id"], status="POSTED")
        assert len(assessed) == 1
        assert posted == []

        settle_batch(batch["id"])
        assessed_after = list_fees(account_id=account["id"], status="ASSESSED")
        posted_after = list_fees(account_id=account["id"], status="POSTED")
        assert assessed_after == []
        assert len(posted_after) == 1
