"""Utility/expense normalization: trailing window, outlier band, ESTIMATE exclusion."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_acquisition,
    create_utility_record_payload,
    get_success_data,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]


class TestUtilityOutlierBoundary:
    def test_utility_outlier_boundary_and_normalized_totals(self, api):
        """PRD §3.5: "The row's `is_outlier` flag is true when its
        `amount_cents` is strictly more than 1.20 times that average or
        strictly less than 0.80 times it — the comparisons are strict, so a row
        exactly twenty percent above or below the average is not an outlier.
        The row's `normalized_amount_cents` is its own `amount_cents` when not
        an outlier and the rounded category average when it is."
        PRD §3.5: "The expense summary read returns the trailing-12 picture:
        `total_t12_raw_cents` and `total_t12_normalized_cents` across the
        window's included rows, an `outlier_count`, and a `by_category`
        breakdown giving each category its raw sum, its normalized sum, and its
        totals."
        PRD §2.7: "At startup, before any operator intervention, the logical
        clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to
        wall-clock time."

        Design: Corner/calculations/utility_outlier_boundary_and_normalized_totals
        """
        acq = create_acquisition(property_name="Util Deal")
        # Default clock is 2026-08-01; trailing window covers 2025-08..2026-07.
        for month in ("2026-04", "2026-05"):
            get_success_data(api.create_utility_record(
                create_utility_record_payload(acq["id"], period_month=month),
                ANALYST), 201)
        get_success_data(api.create_utility_record(
            create_utility_record_payload(acq["id"], period_month="2026-06",
                                          source="BILL_AUDIT"),
            ANALYST), 201)
        # Average of the other three ELECTRIC rows is 100000; 120001 > 120000.
        rec_e = validate_success(api.create_utility_record(
            create_utility_record_payload(acq["id"], period_month="2026-07",
                                          amount_cents=120_001),
            ANALYST), 201)
        assert rec_e["is_outlier"] is True
        assert rec_e["normalized_amount_cents"] == 100_000

        for month in ("2026-04", "2026-05", "2026-06"):
            get_success_data(api.create_utility_record(
                create_utility_record_payload(acq["id"], period_month=month,
                                              category="GAS"),
                ANALYST), 201)
        # Exactly 1.20x the average is NOT an outlier (strict >).
        rec_g = validate_success(api.create_utility_record(
            create_utility_record_payload(acq["id"], period_month="2026-07",
                                          category="GAS", amount_cents=120_000),
            ANALYST), 201)
        assert rec_g["is_outlier"] is False
        assert rec_g["normalized_amount_cents"] == 120_000

        summary = get_success_data(api.get_expense_summary(acq["id"], ANALYST))
        assert summary["total_t12_raw_cents"] == 840_001
        assert summary["total_t12_normalized_cents"] == 820_000
        assert summary["outlier_count"] == 1


class TestEstimateRowsExcluded:
    def test_estimate_rows_excluded_from_expense_summary(self, api):
        """PRD §3.5: "Within the window, only rows whose source is `SELLER_T12`
        or `BILL_AUDIT` participate — `ESTIMATE` rows are excluded from
        averages, from sums, and from outlier math."
        PRD §3.5: "A category with no included rows in the window contributes
        zero."

        Design: Corner/calculations/estimate_rows_excluded_from_expense_summary
        """
        acq = create_acquisition(property_name="Est Deal")
        for month in ("2026-04", "2026-05"):
            get_success_data(api.create_utility_record(
                create_utility_record_payload(acq["id"], period_month=month,
                                              category="OTHER", amount_cents=200_000),
                ANALYST), 201)
        get_success_data(api.create_utility_record(
            create_utility_record_payload(acq["id"], period_month="2026-06",
                                          category="OTHER", amount_cents=200_000,
                                          source="BILL_AUDIT"),
            ANALYST), 201)
        est = validate_success(api.create_utility_record(
            create_utility_record_payload(acq["id"], period_month="2026-07",
                                          category="OTHER", amount_cents=999_999,
                                          source="ESTIMATE"),
            ANALYST), 201)
        assert est["is_outlier"] is False, "ESTIMATE rows skip the outlier test"

        summary = get_success_data(api.get_expense_summary(acq["id"], ANALYST))
        assert summary["total_t12_raw_cents"] == 600_000
        assert summary["total_t12_normalized_cents"] == 600_000
        assert summary["outlier_count"] == 0


class TestUtilityRecordUniqueness:
    def test_duplicate_utility_record_rejected(self, api):
        """PRD §3.5: "The triple of acquisition, `period_month`, and `category`
        is unique; a duplicate is rejected with `ERR_UTILITY_RECORD_EXISTS`."

        Design: Corner/validations/duplicate_utility_record_rejected
        """
        acq = create_acquisition(property_name="Dup Util")
        get_success_data(api.create_utility_record(
            create_utility_record_payload(acq["id"]), ANALYST), 201)

        resp = api.create_utility_record(
            create_utility_record_payload(acq["id"], amount_cents=111_111,
                                          source="BILL_AUDIT"),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_UTILITY_RECORD_EXISTS, 409)
