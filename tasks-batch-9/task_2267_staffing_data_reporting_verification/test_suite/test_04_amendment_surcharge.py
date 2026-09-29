"""Amendment surcharge assessment on a late reopen."""

from test_helpers import (
    SubmissionStatus,
    validate_success,
)

LATE_CLOCK = "2026-08-20T12:00:00Z"


class TestAmendmentSurchargeTierFromBaseFee:
    def test_01_late_rate_is_selected_from_the_base_fee_not_the_total(
        self, api, accepted_quarter
    ):
        """PRD: "the late rate is selected from the **base fee**, not from the
        eventual total: the rate is 0.0300 when the base fee is at least 27500
        cents, 0.0200 when it is at least 25000 cents, 0.0100 when it is at least
        1 cent, and 0.0000 when the base fee is 0." PRD: "A base fee of 25000
        cents with 6 late days yields 28000 cents under the pinned order, where
        reading the tier off the total would yield 29500."

        Design: Difficulty/combinatorial_formula/amendment_surcharge_tier_keyed_on_base_fee_not_total
        """
        scenario = accepted_quarter
        scenario.universe.set_clock(LATE_CLOCK)

        data = validate_success(
            api.reopen_submission(scenario.id, scenario.universe.coord_headers)
        )

        assert data["amendment_surcharge_cents"] == 28000
        assert data["amendment_surcharge_cents"] != 29500
        assert data["waived_surcharge_cents"] == 0

    def test_02_reopening_lands_in_draft_and_advances_the_amendment_index(
        self, api, accepted_quarter
    ):
        """PRD: "Reopening a quarter for correction is available from either
        `ACCEPTED` or `REJECTED`, and in both cases it lands the submission back
        in `DRAFT`, closing the cycle `DRAFT → VALIDATED → SUBMITTED → ACCEPTED →
        DRAFT`. It requires the governing period to be `OPEN` and the logical
        clock to be at or before the period's correction window end, increments
        `amendment_index` by one, adds the assessed surcharge to
        `amendment_surcharge_cents`, refreshes the facility's
        `outstanding_surcharge_cents`, clears both `validated_by_worker_id` and
        `attested_by_worker_id` so the segregation-of-duties pairing must be
        re-established, and increments `version` by one."

        Design: Difficulty/combinatorial_formula/amendment_surcharge_tier_keyed_on_base_fee_not_total
        """
        scenario = accepted_quarter
        scenario.universe.set_clock(LATE_CLOCK)

        data = validate_success(
            api.reopen_submission(scenario.id, scenario.universe.coord_headers)
        )

        assert data["status"] == SubmissionStatus.DRAFT.value
        assert data["amendment_index"] == 1
        assert data["validated_by_worker_id"] is None
        assert data["attested_by_worker_id"] is None

    def test_03_the_facility_surcharge_balance_absorbs_the_assessed_amount(
        self, api, accepted_quarter
    ):
        """PRD: "`outstanding_surcharge_cents` is the sum, over every
        `QuarterlySubmission` of the facility whose `status` is anything other
        than `VOID`, of that submission's `amendment_surcharge_cents` less its
        `waived_surcharge_cents`."

        Design: Difficulty/combinatorial_formula/amendment_surcharge_tier_keyed_on_base_fee_not_total
        """
        scenario = accepted_quarter
        universe = scenario.universe
        universe.set_clock(LATE_CLOCK)

        validate_success(api.reopen_submission(scenario.id, universe.coord_headers))

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["outstanding_surcharge_cents"] == 28000
