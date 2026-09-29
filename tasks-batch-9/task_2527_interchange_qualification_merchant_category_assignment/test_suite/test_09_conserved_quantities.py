"""The two conserved quantities: the reservation pool of an incentive program and
the assessment ledger of a batch and its merchant.
"""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_batch_ledger_conserved,
    assert_capacity_pool_conserved,
    assert_enrolled_count_matches,
    assert_merchant_ledger_conserved,
)
from test_helpers.fixtures import (
    add_record,
    board_merchant,
    canonical_environment,
    create_incentive_program,
    enrol_merchant,
    finalize_batch,
    open_batch,
    read_batch,
    read_enrollment,
    read_incentive_program,
    read_merchant,
    read_record,
    reverse_record,
    submit_batch,
    withdraw_enrollment,
)
from test_helpers.test_users import TEST_USERS

NETWORK_ADMIN = TEST_USERS["network_admin_headers"]
WITHDRAWAL_REASON = "Merchant exited the program voluntarily"


def _pool_with_two_enrollments():
    """Two debits of 30000000 and 20000000 against a 100000000 pool."""
    env = canonical_environment("2026-09-03T00:00:00Z", program_keys=())
    acquirer_id = env["acquirer"]["id"]
    program = create_incentive_program(
        program_name="Pool Conservation 2026",
        eligible_mcc_codes=["5411"],
        total_capacity_cents=100000000,
        min_commitment_cents=5000000,
        reopen_threshold_cents=5000000,
        performance_threshold_pct=80.00,
    )
    merchant_a = board_merchant(acquirer_id, "GROCERY", legal_name="Grocer A")
    merchant_b = board_merchant(acquirer_id, "GROCERY", legal_name="Grocer B")
    enrollment_a = enrol_merchant(
        program["id"],
        merchant_a["id"],
        30000000,
        acquirer_id,
        expected_incentive_program_version=program["version"],
    )
    after_first = read_incentive_program(program["id"])
    enrollment_b = enrol_merchant(
        program["id"],
        merchant_b["id"],
        20000000,
        acquirer_id,
        expected_incentive_program_version=after_first["version"],
    )
    return {
        "acquirer_id": acquirer_id,
        "acquirer_headers": env["acquirer_headers"],
        "program_at_open": program,
        "program_after_first": after_first,
        "enrollment_a": enrollment_a,
        "enrollment_b": enrollment_b,
    }


def _program_enrollments(program_id):
    listing = api_client.list_incentive_enrollments(
        NETWORK_ADMIN, params={"incentive_program_id": program_id}
    )
    rows, _meta = validate_paginated(listing)
    return rows


class TestIncentiveCapacityPoolIsConserved:
    def test_each_enrollment_debits_the_pool_by_its_own_commitment(self):
        """The pool opens at its full capacity and each admission removes exactly
        the commitment it books.

        PRD 3.8: "It resolves to `ENROLLED` when the program's `enrollment_state`
        is `OPEN` and the requested `committed_volume_cents` is at most the
        program's `uncommitted_capacity_cents`; `enrolled_at` is then stamped with
        the current logical-clock instant, `uncommitted_capacity_cents` is debited
        by the committed volume, `enrolled_count` rises by 1, and
        `IncentiveProgram.version` advances by 1."

        Design: Difficulty/compensating_invariant/compensating_invariant_incentive_capacity_pool_conserved_across_withdraw
        """
        state = _pool_with_two_enrollments()
        assert state["program_at_open"]["uncommitted_capacity_cents"] == 100000000
        assert state["program_after_first"]["uncommitted_capacity_cents"] == 70000000

        program = read_incentive_program(state["program_at_open"]["id"])
        assert program["uncommitted_capacity_cents"] == 50000000
        assert program["enrolled_count"] == 2

    def test_withdrawing_credits_the_pool_back_with_no_drift(self):
        """The compensating credit returns exactly the withdrawn commitment, the
        withdrawn row stops counting toward the committed sum, and the pool
        reconciles to the cent.

        PRD 2.10: "At all times an incentive program's `total_capacity_cents` must
        equal its `uncommitted_capacity_cents` plus the sum of
        `committed_volume_cents` over its enrollments in status `ENROLLED` or
        `PROBATION`."

        Design: Difficulty/compensating_invariant/compensating_invariant_incentive_capacity_pool_conserved_across_withdraw
        """
        state = _pool_with_two_enrollments()
        withdrawn = withdraw_enrollment(
            state["enrollment_a"]["id"],
            headers=state["acquirer_headers"],
            withdrawal_reason=WITHDRAWAL_REASON,
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdrawal_reason"] == WITHDRAWAL_REASON
        assert withdrawn["committed_volume_cents"] == 30000000
        assert read_enrollment(state["enrollment_b"]["id"])["status"] == "ENROLLED"

        program = read_incentive_program(state["program_at_open"]["id"])
        assert program["uncommitted_capacity_cents"] == 80000000
        assert program["enrolled_count"] == 1
        assert program["enrollment_state"] == "OPEN"

        enrollments = _program_enrollments(program["id"])
        assert_capacity_pool_conserved(program, enrollments)
        assert_enrolled_count_matches(program, enrollments)


def _finalized_batch_of_two_downgrades():
    """Two 1200-cent records carrying only `AUTH_CODE`, each downgraded to the
    fallback tier for 40 cents."""
    env = canonical_environment("2026-09-03T00:00:00Z")
    acquirer_id = env["acquirer"]["id"]
    merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
    batch = open_batch(acquirer_id, "2026-09-02", "USD")
    first = add_record(
        batch["id"],
        merchant["id"],
        1200,
        acquirer_id,
        expected_batch_version=batch["version"],
        auth_code="A00101",
        auth_timestamp="2026-09-02T00:00:00Z",
        clearing_timestamp="2026-09-02T01:00:00Z",
        data_elements=["AUTH_CODE"],
    )
    second = add_record(
        batch["id"],
        merchant["id"],
        1200,
        acquirer_id,
        auth_code="A00102",
        auth_timestamp="2026-09-02T00:00:00Z",
        clearing_timestamp="2026-09-02T01:00:00Z",
        data_elements=["AUTH_CODE"],
    )
    submit_batch(batch["id"], acquirer_id)
    finalized = finalize_batch(batch["id"])
    return {
        "acquirer_headers": env["acquirer_headers"],
        "standard_program_id": env["programs"]["STANDARD"]["id"],
        "merchant": read_merchant(merchant["id"]),
        "batch_at_finalize": finalized,
        "first": first,
        "second": second,
    }


def _batch_records(batch_id):
    listing = api_client.list_transaction_records(
        NETWORK_ADMIN, params={"settlement_batch_id": batch_id}
    )
    rows, _meta = validate_paginated(listing)
    return rows


class TestAssessmentLedgerIsZeroedByAClearingReversal:
    def test_the_reversed_record_gives_up_its_own_money(self):
        """The reversal zeroes the record's assessment and leaves it in `REVERSED`,
        starting from a batch that had booked 80 cents over two downgrades.

        PRD 3.7: "First, the record's own money is zeroed:
        `assessed_interchange_cents`, `cross_border_surcharge_cents` and
        `fx_markup_cents` all become 0."

        Design: Difficulty/compensating_invariant/compensating_invariant_assessment_ledger_zeroed_by_clearing_reversal
        """
        state = _finalized_batch_of_two_downgrades()
        assert state["batch_at_finalize"]["total_assessed_cents"] == 80
        assert state["merchant"]["lifetime_net_assessed_cents"] == 80
        assert state["merchant"]["downgrade_count_current_quarter"] == 2

        reversed_record = reverse_record(
            state["second"]["id"],
            "CLEARING_REVERSAL",
            headers=state["acquirer_headers"],
            reversal_reason="Cardholder dispute resolved in favour of the cardholder",
        )
        assert reversed_record["qualification_status"] == "REVERSED"
        assert reversed_record["reversal_type"] == "CLEARING_REVERSAL"
        assert reversed_record["assessed_interchange_cents"] == 0

    def test_both_aggregates_and_the_downgrade_counter_are_re_derived_together(self):
        """The surviving record keeps its 40 cents while the batch total, the
        merchant's lifetime ledger and its quarterly downgrade count all drop
        together, with no cached figure left behind.

        PRD 2.10: "Finalizing a batch is the forward action that posts amounts into
        both sums; a clearing reversal is the compensating action that zeroes the
        record's amount and moves it to `REVERSED`, after which both sums must again
        equal the sum over the surviving qualified and downgraded rows exactly."

        Design: Difficulty/compensating_invariant/compensating_invariant_assessment_ledger_zeroed_by_clearing_reversal
        """
        state = _finalized_batch_of_two_downgrades()
        reverse_record(
            state["second"]["id"],
            "CLEARING_REVERSAL",
            headers=state["acquirer_headers"],
            reversal_reason="Cardholder dispute resolved in favour of the cardholder",
        )

        survivor = read_record(state["first"]["id"])
        assert survivor["qualification_status"] == "DOWNGRADED"
        assert survivor["assessed_interchange_cents"] == 40
        assert survivor["qualified_rate_program_id"] == state["standard_program_id"]

        batch = read_batch(state["batch_at_finalize"]["id"])
        merchant = read_merchant(state["merchant"]["id"])
        assert batch["total_assessed_cents"] == 40
        assert merchant["lifetime_net_assessed_cents"] == 40
        assert merchant["downgrade_count_current_quarter"] == 1

        records = _batch_records(batch["id"])
        assert_batch_ledger_conserved(batch, records)
        assert_merchant_ledger_conserved(merchant, records)
