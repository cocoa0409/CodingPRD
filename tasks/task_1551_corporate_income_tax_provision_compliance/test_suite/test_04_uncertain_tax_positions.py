"""Uncertain tax positions: the >50% recognition boundary, interest accrual
in floored whole months, the disclosure gate, settlement, and statute lapse.
"""
from test_helpers import (
    ApiErrorId,
    create_measured_position,
    create_position,
    file_ready_filing,
    get_tax_year,
    mark_filing_ready_with_liability,
    set_logical_clock,
    setup_locked_year_ready_filing_and_disclosed_utp,
    setup_locked_year_with_filing,
    setup_open_year_with_jurisdiction,
    validate_error,
    validate_success,
)


class TestRecognitionThreshold:
    def test_probability_at_exactly_threshold_not_recognized(
            self, api, tax_manager_headers):
        """PRD §3.4: "Recognition uses a strict threshold: when
        `cumulative_probability_bp` is strictly greater than 5000,
        `recognized_benefit_cents` equals the full `position_amount_cents`; at
        exactly 5000 or below, nothing is recognized."
        PRD §3.4: "`liability_cents` — the unrecognized tax benefit reserve —
        is `position_amount_cents` minus `recognized_benefit_cents`, and
        `disclosure_required` is true exactly when `liability_cents` is
        greater than zero."

        Design: Difficulty/boundary_precision_check/utp_recognition_threshold_exact_50pct
        """
        ty, jur = setup_open_year_with_jurisdiction()
        utp = create_position(ty["id"], jur["id"], position_amount_cents=1000000,
                              description="position at exactly 50 percent")

        measured = validate_success(
            api.measure_position(utp["id"], 5000, tax_manager_headers), 200)
        assert measured["recognized_benefit_cents"] == 0
        assert measured["liability_cents"] == 1000000
        assert measured["disclosure_required"] is True
        assert measured["status"] == "MEASURED"

        year = get_tax_year(ty["id"])
        assert year["utp_liability_cents"] == 1000000

    def test_probability_one_bp_above_threshold_fully_recognized(
            self, api, tax_manager_headers):
        """PRD §3.4: "Recognition uses a strict threshold: when
        `cumulative_probability_bp` is strictly greater than 5000,
        `recognized_benefit_cents` equals the full `position_amount_cents`; at
        exactly 5000 or below, nothing is recognized."
        PRD §3.4: "`liability_cents` — the unrecognized tax benefit reserve —
        is `position_amount_cents` minus `recognized_benefit_cents`, and
        `disclosure_required` is true exactly when `liability_cents` is
        greater than zero."

        Design: Difficulty/boundary_precision_check/utp_recognition_threshold_exact_50pct
        """
        ty, jur = setup_open_year_with_jurisdiction()
        utp_a = create_position(ty["id"], jur["id"],
                                position_amount_cents=1000000,
                                description="position at exactly 50 percent")
        utp_b = create_position(ty["id"], jur["id"],
                                position_amount_cents=1000000,
                                description="position one bp above")
        validate_success(api.measure_position(utp_a["id"], 5000,
                                              tax_manager_headers), 200)

        measured_b = validate_success(
            api.measure_position(utp_b["id"], 5001, tax_manager_headers), 200)
        assert measured_b["recognized_benefit_cents"] == 1000000
        assert measured_b["liability_cents"] == 0
        assert measured_b["disclosure_required"] is False

        # Only the sub-threshold position contributes to the year's reserve.
        year = get_tax_year(ty["id"])
        assert year["utp_liability_cents"] == 1000000

    def test_probability_above_ceiling_rejected(self, api,
                                                tax_manager_headers):
        """PRD §3.4: "Measurement is a `TaxManager` action carrying
        `cumulative_probability_bp` — the cumulative probability that the full
        benefit is sustained, in basis points, which must lie between 0 and
        10000 inclusive or the request is rejected with
        `ERR_PROBABILITY_OUT_OF_RANGE`."

        Design: Corner/validations/measure_probability_out_of_range_rejected
        """
        ty, jur = setup_open_year_with_jurisdiction()
        utp = create_position(ty["id"], jur["id"],
                              position_amount_cents=2000000,
                              description="R&D credit")

        res = api.measure_position(utp["id"], 10001, tax_manager_headers)
        validate_error(res, ApiErrorId.ERR_PROBABILITY_OUT_OF_RANGE,
                       expected_status=422)

        after = validate_success(
            api.get_uncertain_tax_position(utp["id"], tax_manager_headers),
            200)
        assert after["status"] == "IDENTIFIED"


class TestInterestAccrual:
    def test_interest_accrues_in_floored_whole_months(
            self, api, tax_manager_headers, platform_admin_headers):
        """PRD §3.4: "Interest accrues on the unrecognized benefit:
        `interest_accrued_cents` is `liability_cents` multiplied by 500 basis
        points per annum (5%), divided by 10000, scaled by the number of whole
        calendar months from `measured_on` to the clock date (floored, never
        below zero) divided by 12, with a single round half up applied to the
        final product. Interest is recomputed on every read and every
        mutation."
        PRD §2.7: "The server runs on a logical clock whose startup default is
        exactly 2026-08-01T00:00:00Z; the clock never falls back to
        wall-clock time."

        Design: Corner/calculations/utp_interest_accrual_whole_months
        """
        ty, jur = setup_open_year_with_jurisdiction()
        # Measured on the startup-default clock date 2026-08-01 (the clock is
        # never set before this measure).
        utp = create_measured_position(ty["id"], jur["id"],
                                       position_amount_cents=1000000,
                                       cumulative_probability_bp=4000)
        assert utp["measured_on"] == "2026-08-01"

        set_logical_clock("2026-12-15T00:00:00Z")
        after = validate_success(
            api.get_uncertain_tax_position(utp["id"], tax_manager_headers),
            200)
        # 2026-08-01 -> 2026-12-15 floors to 4 whole months:
        # round_half_up(1,000,000 * 500/10000 * 4/12) = round(16,666.67)
        assert after["interest_accrued_cents"] == 16667


class TestDisclosureGate:
    def test_disclose_rejected_without_ready_filing(
            self, api, tax_manager_headers):
        """PRD §3.4: "Disclosure moves a `MEASURED` position to `DISCLOSED`,
        but only when a filing exists for the same `tax_year_id` and
        `jurisdiction_id` in `READY`, `FILED`, or `ACCEPTED` — a
        cross-aggregate gate that rejects with `ERR_RETURN_NOT_READY`
        otherwise."

        Design: Difficulty/cross_entity_state_dependency/utp_disclose_requires_ready_filing
        """
        scenario = setup_locked_year_with_filing()  # filing stays PENDING
        ty = scenario["tax_year"]
        jur = scenario["jurisdiction"]
        utp = create_measured_position(ty["id"], jur["id"],
                                       position_amount_cents=1000000,
                                       cumulative_probability_bp=4000)

        res = api.disclose_position(utp["id"], tax_manager_headers)
        validate_error(res, ApiErrorId.ERR_RETURN_NOT_READY,
                       expected_status=422)

    def test_disclose_succeeds_once_filing_ready(self, api,
                                                 tax_manager_headers):
        """PRD §3.4: "Disclosure moves a `MEASURED` position to `DISCLOSED`,
        but only when a filing exists for the same `tax_year_id` and
        `jurisdiction_id` in `READY`, `FILED`, or `ACCEPTED` — a
        cross-aggregate gate that rejects with `ERR_RETURN_NOT_READY`
        otherwise."

        Design: Difficulty/cross_entity_state_dependency/utp_disclose_requires_ready_filing
        """
        scenario = setup_locked_year_with_filing()
        ty = scenario["tax_year"]
        jur = scenario["jurisdiction"]
        utp = create_measured_position(ty["id"], jur["id"],
                                       position_amount_cents=1000000,
                                       cumulative_probability_bp=4000)

        res = api.disclose_position(utp["id"], tax_manager_headers)
        validate_error(res, ApiErrorId.ERR_RETURN_NOT_READY,
                       expected_status=422)

        mark_filing_ready_with_liability(scenario["filing"]["id"], 21100000)
        disclosed = validate_success(
            api.disclose_position(utp["id"], tax_manager_headers), 200)
        assert disclosed["status"] == "DISCLOSED"


class TestSettleAndLapse:
    def test_settle_releases_reserve(self, api, tax_manager_headers,
                                     auditor_headers):
        """PRD §3.4: "From `DISCLOSED`, a `TaxManager` settles the position by
        supplying `settled_amount_cents` (nonnegative), moving it to `SETTLED`
        and releasing the reserve: settled positions drop out of
        `utp_liability_cents`, `forecast_etr_bp` recomputes, and the year's
        `version` increments."

        Design: Corner/state_machines/utp_settle_releases_reserve
        """
        scenario = setup_locked_year_ready_filing_and_disclosed_utp(
            return_liability=21000000)
        ty = scenario["tax_year"]
        utp = scenario["position"]
        assert utp["status"] == "DISCLOSED"

        year_before = get_tax_year(ty["id"])
        assert year_before["utp_liability_cents"] == 1000000

        settled = validate_success(
            api.settle_position(utp["id"], 600000, tax_manager_headers), 200)
        assert settled["status"] == "SETTLED"
        assert settled["settled_amount_cents"] == 600000

        year_after = get_tax_year(ty["id"])
        assert year_after["utp_liability_cents"] == 0

    def test_disclosed_position_lapses_after_statute(
            self, api, auditor_headers):
        """PRD §2.7: "**Uncertain tax positions**: any position in `DISCLOSED`
        lapses to `LAPSED` once the clock date is more than three years past
        the `filed_on` date of the `FILED` or `ACCEPTED` filing sharing its
        `tax_year_id` and `jurisdiction_id`; lapsing recomputes the year's
        `utp_liability_cents` and `forecast_etr_bp`."
        PRD §2.7: "The response reports the new `current_utc` together with
        the lists `late_payment_ids`, `overdue_notice_ids`, and
        `lapsed_position_ids` naming every entity the sweeps transitioned."

        Design: Corner/state_machines/utp_auto_lapse_after_statute
        """
        scenario = setup_locked_year_ready_filing_and_disclosed_utp(
            return_liability=21100000)
        ty = scenario["tax_year"]
        utp = scenario["position"]

        set_logical_clock("2026-06-01T00:00:00Z")
        filed = file_ready_filing(scenario["filing"]["id"], ty["id"])
        assert filed["filed_on"] == "2026-06-01"

        # Statute expiry is 2029-06-01; one day later the sweep lapses it.
        clock_data = set_logical_clock("2029-06-02T00:00:00Z")
        assert utp["id"] in clock_data["lapsed_position_ids"]

        after = validate_success(
            api.get_uncertain_tax_position(utp["id"], auditor_headers), 200)
        assert after["status"] == "LAPSED"

        year = get_tax_year(ty["id"])
        assert year["utp_liability_cents"] == 0
