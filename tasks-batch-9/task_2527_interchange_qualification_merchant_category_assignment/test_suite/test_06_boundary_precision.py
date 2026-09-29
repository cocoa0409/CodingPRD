"""Inclusive and zero-cardinality edges of the pricing and scoring arithmetic."""
from test_helpers.fixtures import (
    add_record,
    board_merchant,
    canonical_environment,
    create_incentive_program,
    enrol_merchant,
    evaluate_enrollment,
    finalize_batch,
    open_batch,
    read_batch,
    read_enrollment,
    read_merchant,
    read_record,
    set_clock,
    submit_batch,
)

TWO_ELEMENTS = ["AUTH_CODE", "TERMINAL_ID"]
FOUR_ELEMENTS = ["AUTH_CODE", "TERMINAL_ID", "TRANSACTION_DATE", "CARDHOLDER_ZIP"]


def _batch_straddling_the_small_ticket_ceiling():
    """Two otherwise identical records, one at 1500 cents and one at 1501."""
    env = canonical_environment("2026-09-03T00:00:00Z")
    acquirer_id = env["acquirer"]["id"]
    merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
    batch = open_batch(acquirer_id, "2026-09-02", "USD")
    at_ceiling = add_record(
        batch["id"],
        merchant["id"],
        1500,
        acquirer_id,
        expected_batch_version=batch["version"],
        auth_code="A00070",
        auth_timestamp="2026-09-01T00:00:00Z",
        clearing_timestamp="2026-09-01T01:00:00Z",
        data_elements=TWO_ELEMENTS,
    )
    over_ceiling = add_record(
        batch["id"],
        merchant["id"],
        1501,
        acquirer_id,
        auth_code="A00071",
        auth_timestamp="2026-09-01T00:00:00Z",
        clearing_timestamp="2026-09-01T01:00:00Z",
        data_elements=TWO_ELEMENTS,
    )
    submit_batch(batch["id"], acquirer_id)
    finalize_batch(batch["id"])
    return {
        "batch": batch,
        "merchant": merchant,
        "programs": env["programs"],
        "at_ceiling": at_ceiling,
        "over_ceiling": over_ceiling,
    }


class TestSmallTicketCeilingIsInclusive:
    def test_a_record_exactly_at_the_ceiling_reaches_the_small_ticket_program(self):
        """1500 cents is at most 1500, so the small-ticket tier stays a candidate
        and prices the record at 25 cents of rate plus its 4-cent item fee.

        PRD 3.5: "Fourth, either the program's `category` is not `SMALL_TICKET`,
        or the record's `amount_cents` is at most the small-ticket ceiling of 1500
        cents — fifteen dollars — so a large ticket cannot reach a small-ticket
        program."

        Design: Difficulty/boundary_precision_check/boundary_small_ticket_max_cents_inclusive_at_1500_exclusive_at_1501
        """
        state = _batch_straddling_the_small_ticket_ceiling()
        assert state["at_ceiling"]["provisional_assessed_cents"] == 29

        record = read_record(state["at_ceiling"]["id"])
        assert record["qualification_status"] == "QUALIFIED"
        assert record["qualified_rate_program_id"] == state["programs"]["SMALL_TICKET"]["id"]
        assert record["assessed_interchange_cents"] == 29
        assert record["downgrade_reason"] is None

    def test_one_cent_over_the_ceiling_falls_to_the_standard_fallback(self):
        """1501 cents cannot reach the small-ticket tier and has only two of the
        four elements the retail tier demands, so it lands on `STANDARD` at 48
        cents and reports the missing elements.

        PRD 3.6: "Against that reference the service then applies five checks **in
        this fixed order**, stopping at the first one that fires: if any element of
        the reference's `requires_data_elements` is missing from the record's
        `data_elements`, the reason is `MISSING_DATA_ELEMENTS`; otherwise if the
        record's `clearing_delay_hours` is greater than the reference's
        `max_clearing_delay_hours`, the reason is `LATE_CLEARING`; otherwise if the
        reference's `category` is `SMALL_TICKET` and the record's `amount_cents`
        exceeds the small-ticket ceiling of 1500 cents, the reason is
        `TICKET_SIZE_INELIGIBLE`; otherwise if the record's `authorization_status`
        is anything other than `AUTH_APPROVED`, the reason is `AUTH_MISSING`;
        otherwise the reason is `MCC_INELIGIBLE`."

        Design: Difficulty/boundary_precision_check/boundary_small_ticket_max_cents_inclusive_at_1500_exclusive_at_1501
        """
        state = _batch_straddling_the_small_ticket_ceiling()
        assert state["over_ceiling"]["provisional_assessed_cents"] == 48

        record = read_record(state["over_ceiling"]["id"])
        assert record["qualification_status"] == "DOWNGRADED"
        assert record["qualified_rate_program_id"] == state["programs"]["STANDARD"]["id"]
        assert record["assessed_interchange_cents"] == 48
        assert record["downgrade_reason"] == "MISSING_DATA_ELEMENTS"

        assert read_batch(state["batch"]["id"])["total_assessed_cents"] == 77
        assert read_merchant(state["merchant"]["id"])["downgrade_count_current_quarter"] == 1


def _submitted_empty_batch():
    """A batch that reaches `SUBMITTED` holding no clearing records at all."""
    env = canonical_environment("2026-09-03T00:00:00Z", program_keys=("STANDARD",))
    acquirer_id = env["acquirer"]["id"]
    batch = open_batch(acquirer_id, "2026-09-02", "USD")
    submit_batch(batch["id"], acquirer_id)
    return {"acquirer": env["acquirer"], "batch": batch}


class TestEmptyBatchFinalizesToZero:
    def test_finalizing_a_record_less_batch_succeeds_and_stamps_the_clock(self):
        """The zero-cardinality aggregation is legal, not an error: the batch
        advances to `FINALIZED` and takes the current logical instant.

        PRD 3.6: "On success the batch advances `SUBMITTED → FINALIZED`,
        `finalized_at` is stamped with the current logical-clock instant, and
        `SettlementBatch.version` advances by 1."

        Design: Difficulty/boundary_precision_check/boundary_empty_batch_finalizes_to_zero_total_and_zero_record_count
        """
        state = _submitted_empty_batch()
        finalized = finalize_batch(state["batch"]["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["finalized_at"] == "2026-09-03T00:00:00.000Z"
        assert state["acquirer"]["compliance_status"] == "COMPLIANT"

    def test_the_finalized_empty_batch_reports_zero_records_and_a_zero_total(self):
        """Summing over no rows yields exactly 0 rather than null, and the record
        count stays at the 0 the batch opened with.

        PRD 3.6: "Once every member record has been assessed, the batch's
        `total_assessed_cents` is re-derived as the sum of
        `assessed_interchange_cents` over the batch's records whose
        `qualification_status` is `QUALIFIED` or `DOWNGRADED`, traversed in
        ascending `created_at` order; records still in `PENDING` and records in
        `REVERSED` are excluded."

        Design: Difficulty/boundary_precision_check/boundary_empty_batch_finalizes_to_zero_total_and_zero_record_count
        """
        state = _submitted_empty_batch()
        finalize_batch(state["batch"]["id"])

        after = read_batch(state["batch"]["id"])
        assert after["status"] == "FINALIZED"
        assert after["record_count"] == 0
        assert after["total_assessed_cents"] == 0


def _enrollment_scoring_exactly_at_the_threshold():
    """Committed 5000000 against 4000000 of completed-quarter volume — a score of
    exactly the program's 80.00 threshold."""
    env = canonical_environment(None)
    acquirer_id = env["acquirer"]["id"]
    program = create_incentive_program(
        program_name="Threshold Exact 2026",
        eligible_mcc_codes=["5411"],
        total_capacity_cents=100000000,
        min_commitment_cents=5000000,
        reopen_threshold_cents=5000000,
        performance_threshold_pct=80.00,
    )
    merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
    set_clock("2026-05-01T00:00:00Z")
    enrollment = enrol_merchant(
        program["id"],
        merchant["id"],
        5000000,
        acquirer_id,
        expected_incentive_program_version=program["version"],
    )
    batch = open_batch(acquirer_id, "2026-05-15", "USD")
    add_record(
        batch["id"],
        merchant["id"],
        4000000,
        acquirer_id,
        expected_batch_version=batch["version"],
        auth_code="A00080",
        auth_timestamp="2026-05-15T00:00:00Z",
        clearing_timestamp="2026-05-15T01:00:00Z",
        data_elements=FOUR_ELEMENTS,
    )
    submit_batch(batch["id"], acquirer_id)
    finalize_batch(batch["id"])
    set_clock("2026-08-16T00:00:00Z")
    return {"enrollment": enrollment}


class TestPerformanceThresholdEqualityPasses:
    def test_a_score_equal_to_the_threshold_keeps_the_enrollment_enrolled(self):
        """80.00 against a threshold of 80.00 reaches it, so no probation
        transition happens and the lifetime probation counter stays at zero.

        PRD 3.8: "Routing against the program's `performance_threshold_pct` uses
        at-or-above as the passing comparison, so equality passes."

        Design: Difficulty/boundary_precision_check/boundary_performance_score_exactly_at_threshold_keeps_enrollment_enrolled
        """
        state = _enrollment_scoring_exactly_at_the_threshold()
        scored = evaluate_enrollment(state["enrollment"]["id"], "TRAILING")

        assert scored["achieved_volume_cents"] == 4000000
        assert float(scored["performance_score_pct"]) == 80.00
        assert scored["status"] == "ENROLLED"
        assert scored["probation_count"] == 0
        assert scored["last_evaluated_basis"] == "TRAILING"

    def test_the_same_scoring_call_resolves_the_lowest_tier_and_no_credit(self):
        """The 58010 cents of assessed volume behind that score sits below the
        5000000 breakpoint, so the tier is `TIER_0` and the credit is 0.

        PRD 3.8: "Second, `tier_code` is resolved from that gross figure and from
        nothing else: `TIER_3` when the gross reaches 50000000 cents, otherwise
        `TIER_2` when it reaches 20000000 cents, otherwise `TIER_1` when it reaches
        5000000 cents, otherwise `TIER_0`."

        Design: Difficulty/boundary_precision_check/boundary_performance_score_exactly_at_threshold_keeps_enrollment_enrolled
        """
        state = _enrollment_scoring_exactly_at_the_threshold()
        evaluate_enrollment(state["enrollment"]["id"], "TRAILING")

        after = read_enrollment(state["enrollment"]["id"])
        assert after["gross_assessed_volume_cents"] == 58010
        assert after["tier_code"] == "TIER_0"
        assert after["incentive_credit_cents"] == 0
