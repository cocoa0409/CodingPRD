"""Optimistic concurrency on parent versions, pagination composed with filters,
and the immediacy of the finalization cascade.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    make_incentive_enrollment_payload,
    make_reclassification_request_payload,
    make_transaction_record_payload,
)
from test_helpers.fixtures import (
    add_record,
    board_merchant,
    canonical_environment,
    create_acquirer,
    create_incentive_program,
    create_mcc,
    create_platform,
    create_rate_program,
    enrol_merchant,
    finalize_batch,
    open_batch,
    read_batch,
    read_incentive_program,
    read_merchant,
    read_record,
    set_clock,
    submit_batch,
    verify_merchant,
)
from test_helpers.test_users import TEST_USERS, make_acquirer_ops_headers

NETWORK_ADMIN = TEST_USERS["network_admin_headers"]
CLOCK = "2026-09-03T00:00:00Z"
TWO_ELEMENTS = ["AUTH_CODE", "TERMINAL_ID"]


def _total_count(response):
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def _batch_environment(batch_date="2026-09-02"):
    """One grocery merchant under the SMALL_TICKET/STANDARD pair, plus one OPEN
    batch."""
    env = canonical_environment(CLOCK, program_keys=("SMALL_TICKET", "STANDARD"))
    acquirer_id = env["acquirer"]["id"]
    merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
    batch = open_batch(acquirer_id, batch_date, "USD")
    assert batch["status"] == "OPEN"
    assert batch["record_count"] == 0
    return {
        "acquirer_id": acquirer_id,
        "acquirer_headers": env["acquirer_headers"],
        "programs": env["programs"],
        "merchant": merchant,
        "batch": batch,
    }


def _records_in_batch(batch_id):
    listing = api_client.list_transaction_records(
        NETWORK_ADMIN, params={"settlement_batch_id": batch_id}
    )
    return validate_paginated(listing)


def _enrollments_in_program(program_id):
    listing = api_client.list_incentive_enrollments(
        NETWORK_ADMIN, params={"incentive_program_id": program_id}
    )
    return validate_paginated(listing)


class TestBatchVersionGuardsRecordAddition:
    def test_a_second_record_pinned_to_the_pre_first_record_version_is_refused(self):
        """Nothing about the batch's state rejects a second record — the batch is
        still `OPEN` and the payload is well formed — so the only defect is the
        version the caller carried.

        PRD 2.8: "Its value must equal the current `version` of the
        `SettlementBatch` named in the path; if some other writer has advanced that
        batch's `version` since the client last read it, the addition is rejected
        with `ERR_STALE_VERSION` and HTTP 412."

        PRD 2.8: "Because every accepted record recomputes `record_count` and
        advances `SettlementBatch.version`, a client adding several records in
        sequence must re-read the batch between additions to obtain the new version."

        Design: Corner/cross-cutting complexity layers/layer_occ_record_add_with_a_stale_batch_version_is_rejected_with_412
        """
        state = _batch_environment()
        batch = state["batch"]
        first = add_record(
            batch["id"],
            state["merchant"]["id"],
            1200,
            state["acquirer_id"],
            expected_batch_version=batch["version"],
            auth_code="A00600",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=TWO_ELEMENTS,
        )

        response = api_client.add_transaction_record(
            batch["id"],
            make_transaction_record_payload(
                state["merchant"]["id"],
                1300,
                batch["version"],
                auth_code="A00601",
                auth_timestamp="2026-09-02T02:00:00Z",
                clearing_timestamp="2026-09-02T03:00:00Z",
                data_elements=TWO_ELEMENTS,
            ),
            state["acquirer_headers"],
        )
        assert response.status_code == 412
        validate_error(response, "ERR_STALE_VERSION", 412)

        after = read_batch(batch["id"])
        assert after["record_count"] == 1
        assert after["status"] == "OPEN"

        rows, meta = _records_in_batch(batch["id"])
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]

    def test_re_reading_between_writes_lands_both_records_one_version_apart(self):
        """The positive half of the guard: each accepted write advances the parent by
        exactly one, so a client that re-reads between additions is never refused.

        PRD 2.4: "`version` is an integer that starts at 1 when the row is created
        and increments by exactly 1 on every mutation of that row."

        PRD 3.5: "Accepting the record advances `record_count` by 1 and advances
        `SettlementBatch.version` by 1; because the response body is the record
        rather than the batch, a client adding a second record must re-read the batch
        to learn its new version."

        PRD 3.5: "Neither figure is ever posted to any ledger:
        `qualification_status` stays `PENDING`, `assessed_interchange_cents` stays at
        its default of 0, and neither the batch total nor the merchant's lifetime
        figure moves."

        Design: Corner/cross-cutting complexity layers/layer_occ_matching_version_succeeds_and_the_parent_version_increments_on_every_write
        """
        state = _batch_environment()
        batch = state["batch"]
        version_at_open = batch["version"]

        first_response = api_client.add_transaction_record(
            batch["id"],
            make_transaction_record_payload(
                state["merchant"]["id"],
                1200,
                version_at_open,
                auth_code="A00700",
                auth_timestamp="2026-09-02T00:00:00Z",
                clearing_timestamp="2026-09-02T01:00:00Z",
                data_elements=TWO_ELEMENTS,
            ),
            state["acquirer_headers"],
        )
        assert first_response.status_code == 201
        first = validate_success(first_response, 201)

        after_first = read_batch(batch["id"])
        assert after_first["version"] == version_at_open + 1
        assert after_first["record_count"] == 1

        second_response = api_client.add_transaction_record(
            batch["id"],
            make_transaction_record_payload(
                state["merchant"]["id"],
                1300,
                after_first["version"],
                auth_code="A00701",
                auth_timestamp="2026-09-02T02:00:00Z",
                clearing_timestamp="2026-09-02T03:00:00Z",
                data_elements=TWO_ELEMENTS,
            ),
            state["acquirer_headers"],
        )
        assert second_response.status_code == 201
        second = validate_success(second_response, 201)
        assert second["id"] != first["id"]

        after_second = read_batch(batch["id"])
        assert after_second["version"] == version_at_open + 2
        assert after_second["record_count"] == 2
        assert after_second["status"] == "OPEN"
        assert after_second["total_assessed_cents"] == 0


class TestMerchantVersionGuardsReclassificationFiling:
    def test_a_request_filed_against_a_pre_verification_snapshot_is_refused(self):
        """The merchant's version moved through a different actor's write — an
        analyst's verification — so the acquirer holding the pre-verification
        snapshot is refused even though the merchant is now in the more permissive
        `VERIFIED` posture: the guard is version identity, not state.

        PRD 2.8: "Creating a reclassification request requires
        `expected_merchant_version` in the request body, matching the current
        `version` of the target `Merchant`."

        PRD 2.8: "This is the guard that catches the client whose view of the
        merchant predates a newer request having already superseded the prior one, or
        predates a category verification or an audit cascade having rewritten the
        merchant's category posture."

        PRD 3.3: "On success the supplied value is stored as `documentation_ref`, the
        acting operator's identity is recorded as `verified_by_user_id`, and
        `Merchant.version` advances by 1."

        Design: Corner/cross-cutting complexity layers/layer_occ_reclassification_create_with_a_stale_merchant_version_is_rejected_with_412
        """
        set_clock(CLOCK)
        platform = create_platform()
        acquirer = create_acquirer(platform["id"])
        create_mcc(
            "5411",
            "GROCERY",
            description="Grocery Stores",
            program_eligibility=["SMALL_TICKET"],
            requires_documentation=True,
        )
        create_mcc(
            "5812", "RESTAURANT", description="Eating Places", program_eligibility=[]
        )
        create_rate_program(
            "STANDARD_FALLBACK",
            "STANDARD",
            ["5411", "5812"],
            name="Standard",
            base_rate_bps=254,
            per_item_fee_cents=10,
            requires_data_elements=[],
            max_clearing_delay_hours=720,
        )
        merchant = board_merchant(
            acquirer["id"], "GROCERY", legal_name="Corner Grocer"
        )
        assert merchant["mcc_status"] == "PENDING_VERIFICATION"

        verified = verify_merchant(
            merchant["id"], "DOC-5411-0002", analyst_user_id="analyst-7"
        )
        assert verified["mcc_status"] == "VERIFIED"
        assert verified["version"] > merchant["version"]

        response = api_client.create_reclassification_request(
            make_reclassification_request_payload(
                merchant["id"],
                "5812",
                merchant["version"],
                justification="Filed against a pre-verification snapshot.",
            ),
            make_acquirer_ops_headers(acquirer["id"]),
        )
        assert response.status_code == 412
        validate_error(response, "ERR_STALE_VERSION", 412)

        assert (
            _total_count(
                api_client.list_reclassification_requests(
                    NETWORK_ADMIN, params={"merchant_id": merchant["id"]}
                )
            )
            == 0
        )
        assert read_merchant(merchant["id"])["version"] == verified["version"]


class TestProgramVersionGuardsEnrollmentCreation:
    def test_a_second_enrollment_pinned_to_the_pre_debit_version_is_refused(self):
        """Capacity still remains and the second merchant is fully eligible, so the
        refusal is the concurrency guard rather than a closed pool, and the rejected
        call leaves the pool exactly as the first enrollment left it.

        PRD 2.8: "Creating an incentive enrollment requires
        `expected_incentive_program_version` in the request body, matching the current
        `version` of the target `IncentiveProgram`."

        PRD 2.8: "Every accepted enrollment — and every waitlist parking — redraws
        `uncommitted_capacity_cents`, `enrolled_count` and `enrollment_state`, and
        advances `IncentiveProgram.version`, so the version a client read before the
        previous enrollment landed is no longer usable."

        PRD 3.8: "It resolves to `ENROLLED` when the program's `enrollment_state` is
        `OPEN` and the requested `committed_volume_cents` is at most the program's
        `uncommitted_capacity_cents`; `enrolled_at` is then stamped with the current
        logical-clock instant, `uncommitted_capacity_cents` is debited by the
        committed volume, `enrolled_count` rises by 1, and `IncentiveProgram.version`
        advances by 1."

        Design: Corner/cross-cutting complexity layers/layer_occ_enrollment_create_with_a_stale_program_version_is_rejected_with_412
        """
        env = canonical_environment(CLOCK, program_keys=("STANDARD",))
        acquirer_id = env["acquirer"]["id"]
        merchant_a = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
        merchant_b = board_merchant(acquirer_id, "GROCERY", legal_name="Second Grocer")
        assert merchant_a["mcc_status"] == "VERIFIED"
        assert merchant_b["mcc_status"] == "VERIFIED"

        program = create_incentive_program(
            program_name="Grocery Growth 2026",
            eligible_mcc_codes=["5411"],
            total_capacity_cents=20000000,
            min_commitment_cents=1000000,
            reopen_threshold_cents=5000000,
            performance_threshold_pct=80.00,
        )
        enrollment_a = enrol_merchant(
            program["id"],
            merchant_a["id"],
            6000000,
            acquirer_id,
            expected_incentive_program_version=program["version"],
        )

        response = api_client.create_incentive_enrollment(
            make_incentive_enrollment_payload(
                program["id"], merchant_b["id"], 4000000, program["version"]
            ),
            env["acquirer_headers"],
        )
        assert response.status_code == 412
        error = validate_error(response, "ERR_STALE_VERSION", 412)
        assert error["error_id"] != "ERR_ENROLLMENT_CLOSED"
        assert error["error_id"] != "ERR_INCENTIVE_CAPACITY_EXCEEDED"

        after = read_incentive_program(program["id"])
        assert after["uncommitted_capacity_cents"] == 14000000
        assert after["enrolled_count"] == 1
        assert after["enrollment_state"] == "OPEN"

        rows, meta = _enrollments_in_program(program["id"])
        assert meta["total_count"] == 1
        assert rows[0]["id"] == enrollment_a["id"]


class TestPaginationComposesWithFilters:
    def test_a_batch_scoped_status_query_pages_two_then_one_and_never_leaks(self):
        """`total_count` describes the filtered population rather than the whole
        table, and the record belonging to the other batch is unreachable from the
        scoped query at any offset.

        PRD 2.3: "For list responses, `response_type` is `"array"` and the `meta`
        object additionally carries `limit` (the effective page size), `offset` (the
        effective skip), `total_count` (the number of rows matching the filters before
        pagination) and `has_more` (true when rows remain beyond the current page)."

        PRD 2.3: "Filters, where an endpoint offers them, narrow the matched set
        before `total_count` is computed."

        PRD 2.3: "Unless a specific collection states otherwise, results are ordered
        by `created_at` ascending, so a client paging through a collection sees rows in
        the order the network recorded them."

        PRD 3.5: "Batches can be listed and narrowed by `acquirer_id`, `status` and
        `batch_date`; records can be listed and narrowed by `settlement_batch_id`,
        `merchant_id`, `provisional_rate_program_id`, `qualified_rate_program_id`,
        `qualification_status` and `authorization_status`."

        Design: Corner/cross-cutting complexity layers/layer_pagination_with_filtering_status_filter_and_offset_compose_over_the_record_list
        """
        state = _batch_environment(batch_date="2026-09-01")
        acquirer_id = state["acquirer_id"]
        merchant_id = state["merchant"]["id"]
        batch_x = state["batch"]
        x1 = add_record(
            batch_x["id"],
            merchant_id,
            1200,
            acquirer_id,
            expected_batch_version=batch_x["version"],
            auth_code="A00800",
            auth_timestamp="2026-09-01T00:00:00Z",
            clearing_timestamp="2026-09-01T01:00:00Z",
            data_elements=TWO_ELEMENTS,
        )
        x2 = add_record(
            batch_x["id"],
            merchant_id,
            1300,
            acquirer_id,
            auth_code="A00801",
            auth_timestamp="2026-09-01T02:00:00Z",
            clearing_timestamp="2026-09-01T03:00:00Z",
            data_elements=TWO_ELEMENTS,
        )
        x3 = add_record(
            batch_x["id"],
            merchant_id,
            1400,
            acquirer_id,
            auth_code="A00802",
            auth_timestamp="2026-09-01T04:00:00Z",
            clearing_timestamp="2026-09-01T05:00:00Z",
            data_elements=TWO_ELEMENTS,
        )
        batch_y = open_batch(acquirer_id, "2026-09-02", "USD")
        y1 = add_record(
            batch_y["id"],
            merchant_id,
            1500,
            acquirer_id,
            expected_batch_version=batch_y["version"],
            auth_code="A00810",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=TWO_ELEMENTS,
        )

        scoped = {
            "settlement_batch_id": batch_x["id"],
            "qualification_status": "PENDING",
            "limit": 2,
        }
        first_page = api_client.list_transaction_records(
            NETWORK_ADMIN, params=dict(scoped, offset=0)
        )
        assert first_page.status_code == 200
        page_one_rows, page_one_meta = validate_paginated(first_page)
        assert len(page_one_rows) == 2
        assert page_one_meta["total_count"] == 3
        assert page_one_meta["has_more"] is True
        assert [row["id"] for row in page_one_rows] == [x1["id"], x2["id"]]

        second_page = api_client.list_transaction_records(
            NETWORK_ADMIN, params=dict(scoped, offset=2)
        )
        page_two_rows, page_two_meta = validate_paginated(second_page)
        assert len(page_two_rows) == 1
        assert page_two_meta["total_count"] == 3
        assert page_two_meta["has_more"] is False
        assert page_two_rows[0]["id"] == x3["id"]

        unfiltered = api_client.list_transaction_records(
            NETWORK_ADMIN,
            params={"qualification_status": "PENDING", "limit": 10, "offset": 0},
        )
        all_rows, all_meta = validate_paginated(unfiltered)
        assert all_meta["total_count"] == 4
        assert all_rows[0]["id"] == x1["id"]
        assert y1["id"] in [row["id"] for row in all_rows]

        scoped_ids = [row["id"] for row in page_one_rows + page_two_rows]
        assert y1["id"] not in scoped_ids


class TestFinalizationIsImmediatelyVisible:
    def test_the_finalize_response_body_already_carries_the_whole_cascade(self):
        """No read-after-write lag anywhere: the finalize response itself shows the
        re-derived batch total, and the very next reads of the record and the merchant
        show the qualified outcome and the rolled-up ledger with no intervening call,
        retry or clock advance.

        PRD 2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."

        PRD 3.6: "On success the batch advances `SUBMITTED → FINALIZED`,
        `finalized_at` is stamped with the current logical-clock instant, and
        `SettlementBatch.version` advances by 1."

        PRD 3.6: "Once every member record has been assessed, the batch's
        `total_assessed_cents` is re-derived as the sum of `assessed_interchange_cents`
        over the batch's records whose `qualification_status` is `QUALIFIED` or
        `DOWNGRADED`, traversed in ascending `created_at` order; records still in
        `PENDING` and records in `REVERSED` are excluded."

        PRD 3.6: "For every merchant touched by the batch,
        `lifetime_net_assessed_cents` is re-derived as the sum of
        `assessed_interchange_cents` over that merchant's records in `QUALIFIED` or
        `DOWNGRADED` across all batches, and `downgrade_count_current_quarter` is
        re-derived as the count of that merchant's records whose
        `qualification_status` is `DOWNGRADED`, whose batch is in `FINALIZED`, and
        whose batch's `batch_date` falls in the same calendar quarter as the current
        logical clock."

        Design: Corner/consistency model/consistency_immediate_the_finalize_response_already_carries_every_cascade_effect
        """
        state = _batch_environment()
        merchant = state["merchant"]
        assert merchant["lifetime_net_assessed_cents"] == 0
        batch = state["batch"]
        record = add_record(
            batch["id"],
            merchant["id"],
            1200,
            state["acquirer_id"],
            expected_batch_version=batch["version"],
            auth_code="A00900",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=TWO_ELEMENTS,
        )
        assert record["qualification_status"] == "PENDING"
        submit_batch(batch["id"], state["acquirer_id"])

        finalized = finalize_batch(batch["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["total_assessed_cents"] == 24
        assert finalized["record_count"] == 1

        assessed = read_record(record["id"])
        assert assessed["qualification_status"] == "QUALIFIED"
        assert assessed["qualified_rate_program_id"] == state["programs"]["SMALL_TICKET"]["id"]
        assert assessed["assessed_interchange_cents"] == 24

        rolled_up = read_merchant(merchant["id"])
        assert rolled_up["lifetime_net_assessed_cents"] == 24
        assert rolled_up["downgrade_count_current_quarter"] == 0
