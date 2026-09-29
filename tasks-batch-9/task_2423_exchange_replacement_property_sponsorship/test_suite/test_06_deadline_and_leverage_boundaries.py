"""Two boundaries measured to the last unit: one millisecond, one cent.

The forty-fifth day ends at a stated instant that is still inside the window,
and the leverage ceiling is an exact integer cross-multiplication that a single
cent breaks.
"""

from test_helpers import (
    CLOCK,
    QI,
    TRUSTEE,
    api_client,
    create_identification_payload,
    create_loan_facility,
    create_loan_facility_payload,
    file_identification,
    read_exchange_file,
    set_clock,
    setup_open_exchange_file_at_deadline,
    setup_trust_forming,
    validate_error,
    validate_success,
)


class TestIdentificationAtTheFortyFiveDayDeadline:
    def test_a_filing_at_the_deadline_instant_is_inside_the_window(self):
        """The boundary instant itself is accepted.

        PRD: "a filing that lands exactly on `identification_deadline` is
        accepted, and one millisecond later is refused."

        Design: Difficulty/boundary_precision_check/identification_exactly_at_45_day_deadline_inclusive
        """
        deal = setup_open_exchange_file_at_deadline()
        assert (
            deal["exchange_file"]["identification_deadline"]
            == "2026-09-19T23:59:59.999Z"
        )

        response = api_client.create_identification(
            create_identification_payload(
                deal["exchange_file"]["id"], deal["property"]["id"]
            ),
            QI,
        )
        identification = validate_success(response, 201)

        assert identification["status"] == "ACTIVE"
        assert identification["identified_at"] == "2026-09-19T23:59:59.999Z"
        assert identification["sequence_no"] == 1

    def test_the_first_active_row_advances_the_file_to_identified(self):
        """The file follows the identification set on the same request.

        PRD: "When the first `ACTIVE` identification lands on an `OPEN` file, the
        file advances `OPEN → IDENTIFIED` and that row takes `sequence_no` 1; the
        advance requires the logical clock to be at or before the
        `identification_deadline`."

        Design: Difficulty/boundary_precision_check/identification_exactly_at_45_day_deadline_inclusive
        """
        deal = setup_open_exchange_file_at_deadline()
        assert deal["exchange_file"]["status"] == "OPEN"

        file_identification(deal["exchange_file"]["id"], deal["property"]["id"])

        exchange_file = read_exchange_file(deal["exchange_file"]["id"])
        assert exchange_file["status"] == "IDENTIFIED"
        assert exchange_file["identification_deadline"] == "2026-09-19T23:59:59.999Z"
        assert exchange_file["exchange_deadline"] == "2027-02-01T23:59:59.999Z"

    def test_one_millisecond_past_the_deadline_is_refused(self):
        """Both clocks are measured from the relinquished closing date.

        PRD: "The `identification_deadline` is forty-five days after that date,
        snapped to `23:59:59.999Z` on the forty-fifth day; the `exchange_deadline`
        is one hundred eighty days after that date, snapped to `23:59:59.999Z` on
        the one-hundred-eightieth day."

        Design: Difficulty/boundary_precision_check/identification_exactly_at_45_day_deadline_inclusive
        """
        deal = setup_open_exchange_file_at_deadline()
        set_clock(CLOCK["PAST_IDENTIFICATION_DEADLINE_A"])

        response = api_client.create_identification(
            create_identification_payload(
                deal["exchange_file"]["id"], deal["property"]["id"]
            ),
            QI,
        )
        validate_error(response, "ERR_IDENTIFICATION_WINDOW_CLOSED")

        assert read_exchange_file(deal["exchange_file"]["id"])["status"] == "OPEN"


class TestLoanAtTheSeventyFivePercentLeverageCeiling:
    def test_a_facility_at_exactly_seventy_five_percent_is_committed(self):
        """The cross-multiplication is an equality here, not an excess.

        PRD: "The enforced leverage test is a different computation and never
        rounds: the `principal_cents` multiplied by ten thousand must be no
        greater than the property's `appraised_value_cents` multiplied by seven
        thousand five hundred — a ceiling of seventy-five percent expressed in
        basis points."

        Design: Difficulty/boundary_precision_check/loan_ltv_exactly_at_seventy_five_percent_boundary
        """
        deal = setup_trust_forming()

        loan = create_loan_facility(deal["trust"]["id"], principal_cents=900_000_000)

        assert loan["status"] == "COMMITTED"
        assert loan["ltv_pct"] == 75.0
        assert loan["dscr"] == 2.5359
        assert loan["recourse_type"] == "NON_RECOURSE"
        # 900,000,000 * 10,000 == 1,200,000,000 * 7,500 exactly.
        assert 900_000_000 * 10_000 == 1_200_000_000 * 7_500

    def test_one_cent_over_the_line_fails_while_the_ratio_still_reads_the_ceiling(self):
        """The reported ratio rounds and the enforced test does not.

        PRD: "A facility one cent over the line fails with
        `ERR_LTV_LIMIT_EXCEEDED` even though its reported `ltv_pct` still displays
        75.0000."

        Design: Difficulty/boundary_precision_check/loan_ltv_exactly_at_seventy_five_percent_boundary
        """
        deal = setup_trust_forming()

        response = api_client.create_loan_facility(
            create_loan_facility_payload(
                deal["trust"]["id"], principal_cents=900_000_001
            ),
            TRUSTEE,
        )
        validate_error(response, "ERR_LTV_LIMIT_EXCEEDED")

        assert 900_000_001 * 10_000 > 1_200_000_000 * 7_500

    def test_the_reported_ratio_carries_four_decimal_places(self):
        """Both reported figures are rounded to four places, not truncated.

        PRD: "The first is `ltv_pct`, the reported loan-to-value: the
        `principal_cents` multiplied by ten thousand, divided by the property's
        `appraised_value_cents`, rounded half up, and then divided by one hundred
        so the result reads as a percentage carried to four decimal places."

        Design: Difficulty/boundary_precision_check/loan_ltv_exactly_at_seventy_five_percent_boundary
        """
        deal = setup_trust_forming()

        loan = create_loan_facility(deal["trust"]["id"], principal_cents=900_000_000)

        assert round(loan["ltv_pct"], 4) == loan["ltv_pct"]
        assert round(loan["dscr"], 4) == loan["dscr"]
        # 97,000,000 / 38,250,000 = 2.535947..., which rounds half up to 2.5359.
        assert loan["dscr"] == 2.5359
