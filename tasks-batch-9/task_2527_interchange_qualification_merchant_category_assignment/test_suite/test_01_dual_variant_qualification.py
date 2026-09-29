"""The two qualification passes and the two performance bases.

Both exercise the same principle: one stored row, two declared evaluation
variants, two different answers.
"""
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
    read_record,
    set_clock,
    submit_batch,
)

ALL_FOUR_ELEMENTS = ["AUTH_CODE", "TERMINAL_ID", "TRANSACTION_DATE", "CARDHOLDER_ZIP"]


def _late_clearing_record():
    """A single 8000-cent record carrying every data element CPS Retail demands
    but presented 30 hours after authorization."""
    env = canonical_environment("2026-09-03T00:00:00Z")
    merchant = board_merchant(
        env["acquirer"]["id"], "GROCERY", headers=env["acquirer_headers"]
    )
    batch = open_batch(
        env["acquirer"]["id"], "2026-09-02", "USD", headers=env["acquirer_headers"]
    )
    record = add_record(
        batch["id"],
        merchant["id"],
        8000,
        env["acquirer"]["id"],
        expected_batch_version=batch["version"],
        headers=env["acquirer_headers"],
        auth_code="A00001",
        auth_timestamp="2026-09-01T00:00:00Z",
        clearing_timestamp="2026-09-02T06:00:00Z",
        data_elements=ALL_FOUR_ELEMENTS,
    )
    env["merchant"] = merchant
    env["batch"] = batch
    env["record"] = record
    return env


class TestProvisionalVersusDefinitiveQualification:
    def test_intake_ignores_the_clearing_delay_and_prices_the_record_at_cps_retail(self):
        """Intake admits CPS Retail for a record cleared 30 hours late, because
        the program's delay tolerance is not consulted at intake.

        PRD 3.5: "At intake, and only at intake, the program's clearing-delay
        tolerance is **not** consulted at all: clearing timing is not yet treated
        as an acquirer commitment, so a program remains a candidate no matter how
        large the record's `clearing_delay_hours` is."

        Design: Difficulty/dual_variant_calc/dual_variant_qualification_provisional_auth_based_vs_final_clearing_based
        """
        env = _late_clearing_record()
        record = env["record"]

        assert record["clearing_delay_hours"] == 30
        assert record["provisional_rate_program_id"] == env["programs"]["CPS_RETAIL"]["id"]
        assert record["provisional_assessed_cents"] == 126
        assert record["qualification_status"] == "PENDING"
        assert record["assessed_interchange_cents"] == 0

    def test_finalization_enforces_the_delay_and_reprices_the_record_on_standard(self):
        """The definitive pass drops CPS Retail because 30 hours exceeds its
        24-hour tolerance, and the record lands on the fallback tier at a
        different cent amount from the provisional estimate.

        PRD 3.6: "Second, the clearing-timing condition that intake omitted is
        now enforced: a program remains a candidate only if its `category` is
        `STANDARD`, or the record's `clearing_delay_hours` is at most that
        program's `max_clearing_delay_hours`."

        Design: Difficulty/dual_variant_calc/dual_variant_qualification_provisional_auth_based_vs_final_clearing_based
        """
        env = _late_clearing_record()
        submit_batch(env["batch"]["id"], headers=env["acquirer_headers"])
        finalize_batch(env["batch"]["id"])

        record = read_record(env["record"]["id"])
        assert record["qualification_status"] == "DOWNGRADED"
        assert record["qualified_rate_program_id"] == env["programs"]["STANDARD"]["id"]
        assert record["assessed_interchange_cents"] == 213
        assert record["provisional_assessed_cents"] == 126
        assert (
            record["provisional_assessed_cents"] != record["assessed_interchange_cents"]
        )

    def test_the_downgrade_reason_names_the_late_clearing_and_the_batch_total_follows(
        self,
    ):
        """The record is downgraded for late clearing rather than for missing
        data, and the batch total is the definitive figure, not the provisional
        one.

        PRD 3.6: "Against that reference the service then applies five checks
        **in this fixed order**, stopping at the first one that fires: if any
        element of the reference's `requires_data_elements` is missing from the
        record's `data_elements`, the reason is `MISSING_DATA_ELEMENTS`;
        otherwise if the record's `clearing_delay_hours` is greater than the
        reference's `max_clearing_delay_hours`, the reason is `LATE_CLEARING`;
        otherwise if the reference's `category` is `SMALL_TICKET` and the
        record's `amount_cents` exceeds the small-ticket ceiling of 1500 cents,
        the reason is `TICKET_SIZE_INELIGIBLE`; otherwise if the record's
        `authorization_status` is anything other than `AUTH_APPROVED`, the reason
        is `AUTH_MISSING`; otherwise the reason is `MCC_INELIGIBLE`."

        Design: Difficulty/dual_variant_calc/dual_variant_qualification_provisional_auth_based_vs_final_clearing_based
        """
        env = _late_clearing_record()
        submit_batch(env["batch"]["id"], headers=env["acquirer_headers"])
        finalize_batch(env["batch"]["id"])

        record = read_record(env["record"]["id"])
        assert record["downgrade_reason"] == "LATE_CLEARING"

        batch = read_batch(env["batch"]["id"])
        assert batch["total_assessed_cents"] == 213


def _scored_enrollment():
    """One enrollment committed to 10000000 cents against a 50.00 threshold,
    with 4000000 cents booked in the prior quarter and 1000000 cents booked in
    the current one, evaluated on day 47 of a 92-day third quarter."""
    env = canonical_environment("2026-04-01T00:00:00Z")
    program = create_incentive_program(
        program_name="Grocery Growth 2026",
        eligible_mcc_codes=["5411"],
        total_capacity_cents=100000000,
        min_commitment_cents=5000000,
        reopen_threshold_cents=5000000,
        performance_threshold_pct=50.00,
    )
    merchant = board_merchant(
        env["acquirer"]["id"], "GROCERY", headers=env["acquirer_headers"]
    )
    set_clock("2026-05-01T00:00:00Z")
    enrollment = enrol_merchant(
        program["id"],
        merchant["id"],
        10000000,
        env["acquirer"]["id"],
        expected_incentive_program_version=program["version"],
        headers=env["acquirer_headers"],
    )
    for batch_date, amount, auth_code, auth_ts, clearing_ts in (
        ("2026-05-15", 4000000, "A00010", "2026-05-15T00:00:00Z", "2026-05-15T01:00:00Z"),
        ("2026-07-10", 1000000, "A00011", "2026-07-10T00:00:00Z", "2026-07-10T01:00:00Z"),
    ):
        batch = open_batch(
            env["acquirer"]["id"], batch_date, "USD", headers=env["acquirer_headers"]
        )
        add_record(
            batch["id"],
            merchant["id"],
            amount,
            env["acquirer"]["id"],
            expected_batch_version=batch["version"],
            headers=env["acquirer_headers"],
            auth_code=auth_code,
            auth_timestamp=auth_ts,
            clearing_timestamp=clearing_ts,
            data_elements=ALL_FOUR_ELEMENTS,
        )
        submit_batch(batch["id"], headers=env["acquirer_headers"])
        finalize_batch(batch["id"])
    set_clock("2026-08-16T00:00:00Z")
    env["program"] = program
    env["merchant"] = merchant
    env["enrollment"] = enrollment
    return env


class TestTrailingVersusProjectedPerformanceBasis:
    def test_trailing_discards_the_current_quarter_and_sends_the_enrollment_to_probation(
        self,
    ):
        """Under `TRAILING` only the completed quarter counts, so 4000000 of a
        10000000 commitment scores 40.00 and falls below the 50.00 threshold.

        PRD 3.8: "Under the `TRAILING` basis, `achieved_volume_cents` is the
        prior aggregate alone — volume booked in the current, still-incomplete
        quarter is discarded entirely, so only completed quarters count."

        Design: Difficulty/dual_variant_calc/dual_variant_performance_score_trailing_vs_projected_on_incentive_enrollment
        """
        env = _scored_enrollment()

        scored = evaluate_enrollment(env["enrollment"]["id"], "TRAILING")
        assert scored["achieved_volume_cents"] == 4000000
        assert float(scored["performance_score_pct"]) == 40.00
        assert scored["status"] == "PROBATION"
        assert scored["last_evaluated_basis"] == "TRAILING"
        assert read_enrollment(env["enrollment"]["id"])["probation_count"] == 1

    def test_projected_annualises_the_partial_quarter_and_recovers_the_enrollment(self):
        """Under `PROJECTED` the 1000000 cents booked in 47 of the quarter's 92
        days scales to 1957447, lifting the same stored rows to 59.57 and
        recovering the enrollment without decrementing its probation counter.

        PRD 3.8: "Under the `PROJECTED` basis, the current partial quarter is
        scaled up to a whole quarter and added: take the number of calendar days
        in the current quarter, which is 90, 91 or 92 depending on which quarter
        it is; take the number of whole days elapsed from the first day of that
        quarter through the current logical clock's date, counting both ends, so
        that the first day of a quarter yields one elapsed day rather than zero;
        multiply the current-quarter aggregate by the days in the quarter, divide
        by the elapsed days, round half up to whole cents, and add that
        projection to the prior aggregate."

        Design: Difficulty/dual_variant_calc/dual_variant_performance_score_trailing_vs_projected_on_incentive_enrollment
        """
        env = _scored_enrollment()

        trailing = evaluate_enrollment(env["enrollment"]["id"], "TRAILING")
        projected = evaluate_enrollment(env["enrollment"]["id"], "PROJECTED")

        assert projected["achieved_volume_cents"] == 5957447
        assert float(projected["performance_score_pct"]) == 59.57
        assert projected["status"] == "ENROLLED"
        assert projected["last_evaluated_basis"] == "PROJECTED"
        assert projected["probation_count"] == 1
        assert (
            trailing["achieved_volume_cents"] != projected["achieved_volume_cents"]
        )
