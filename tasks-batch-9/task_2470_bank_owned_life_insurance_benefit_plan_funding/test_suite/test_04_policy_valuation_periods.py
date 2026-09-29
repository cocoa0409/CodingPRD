"""Statement periods: interval adjacency, the mortality-charge drift band and the closure cascade."""
import pytest
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.fixtures import (
    RISK,
    TREASURY,
    in_force_policy,
    open_diligence_review,
    post_valuation,
    submit_diligence_review,
)


UMBER = {"legal_name": "Umber Life", "naic_code": "62081", "domicile_state": "NV"}
REDSTONE = {"legal_name": "Redstone Life", "naic_code": "62091", "domicile_state": "AZ"}
VANTAGE = {"legal_name": "Vantage Life", "naic_code": "62101", "domicile_state": "GA"}

VARGAS = {
    "full_name": "Pia Vargas",
    "employee_number": "E-6501",
    "annual_salary_usd": 2_000_000.00,
    "officer_flag": True,
}


class TestStatementPeriodAdjacency:
    def test_a_period_starting_where_the_previous_one_ended_is_accepted(self, api):
        """Half-open intervals make back-to-back periods legal.

        "Statement intervals are half-open — the `period_start_date` is included,
        the `as_of_date` is excluded — and no buffer is applied. Two periods on
        the same policy conflict when the new period's `period_start_date` falls
        strictly before the existing period's `as_of_date` and, at the same time,
        the existing period's `period_start_date` falls strictly before the new
        period's `as_of_date`." The second period compounds on the first, because
        "`prior_cash_value_usd` is captured as the policy's
        `cash_surrender_value_usd` immediately before this posting."

        Design: Difficulty/resource_temporal_overlap/valuation_period_accepts_adjacency_then_rejects_one_day_overlap
        """
        context = in_force_policy(
            api,
            carrier_overrides=UMBER,
            product_overrides={"product_name": "Umber GA BOLI"},
            employee_overrides=VARGAS,
            policy_overrides={"policy_number": "UM-0001"},
        )

        first = post_valuation(api, context["policy_id"])
        assert first["cash_value_usd"] == pytest.approx(1_018_000.00, abs=0.01)
        assert first["me_charge_bps"] == 20
        assert first["me_drift_bps"] == 0
        assert first["net_yield_bps"] == 180

        adjacent = post_valuation(
            api,
            context["policy_id"],
            period_start_date="2026-09-30T00:00:00Z",
            as_of_date="2026-10-31T00:00:00Z",
            credited_interest_usd=20_360.00,
            mortality_expense_charge_usd=2_036.00,
            gross_crediting_rate_bps=200,
        )
        assert adjacent["prior_cash_value_usd"] == pytest.approx(1_018_000.00, abs=0.01)
        assert adjacent["cash_value_usd"] == pytest.approx(1_036_324.00, abs=0.01)
        assert adjacent["me_charge_bps"] == 20
        assert adjacent["net_yield_bps"] == 180

        policy = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert policy["cash_surrender_value_usd"] == pytest.approx(1_036_324.00, abs=0.01), (
            "posting a period writes the new cash value back onto the policy"
        )

    def test_a_period_overlapping_by_one_day_is_rejected_and_writes_nothing(self, api):
        """A single day of overlap is a conflict and the refusal changes nothing.

        A period running from 2026-10-30 starts strictly before the existing
        period's `as_of_date` of 2026-10-31 and ends strictly after that
        period's start, so the conflict rule applies and "A conflict is rejected
        with `ERR_VALUATION_PERIOD_OVERLAP` (HTTP 409)". No third period is
        stored and the policy's cash value is untouched.

        Design: Difficulty/resource_temporal_overlap/valuation_period_accepts_adjacency_then_rejects_one_day_overlap
        """
        context = in_force_policy(
            api,
            carrier_overrides=UMBER,
            product_overrides={"product_name": "Umber GA BOLI"},
            employee_overrides=VARGAS,
            policy_overrides={"policy_number": "UM-0001"},
        )
        post_valuation(api, context["policy_id"])
        post_valuation(
            api,
            context["policy_id"],
            period_start_date="2026-09-30T00:00:00Z",
            as_of_date="2026-10-31T00:00:00Z",
            credited_interest_usd=20_360.00,
            mortality_expense_charge_usd=2_036.00,
            gross_crediting_rate_bps=200,
        )

        validate_error(
            api.create_policy_valuation(
                {
                    "policy_id": context["policy_id"],
                    "period_start_date": "2026-10-30T00:00:00Z",
                    "as_of_date": "2026-11-30T00:00:00Z",
                    "credited_interest_usd": 20_000.00,
                    "mortality_expense_charge_usd": 2_000.00,
                    "gross_crediting_rate_bps": 200,
                },
                TREASURY,
            ),
            "ERR_VALUATION_PERIOD_OVERLAP",
            409,
        )

        items, _meta = validate_paginated(
            api.list_policy_valuations(TREASURY, params={"policy_id": context["policy_id"]})
        )
        assert len(items) == 2, "the conflicting period is not stored"

        policy = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert policy["cash_surrender_value_usd"] == pytest.approx(1_036_324.00, abs=0.01)

        product = validate_success(api.get_product_type(context["product_type_id"], TREASURY))
        assert product["status"] == "OPEN"
        assert product["consecutive_low_yield_count"] == 0


class TestMortalityChargeDriftBand:
    def test_drift_of_exactly_twenty_five_basis_points_leaves_the_product_open(self, api):
        """Drift at the tolerance itself does not put the product on watch.

        "`me_drift_bps` is `me_charge_bps` minus the product's
        `disclosed_me_charge_bps`", and the posting cascade sets "the product's
        `latest_me_charge_bps` and `latest_me_drift_bps` are set from this
        posting's values" before applying the watch rule, under which "a drift of
        exactly 25 does not trip the watch". A 6,750.00 charge on 1,500,000.00
        of prior cash value measures 45 basis points against a disclosed 20, a
        drift of exactly 25, and the 155 basis point net yield is above the
        low-yield floor.

        Design: Difficulty/boundary_precision_check/me_drift_exactly_at_tolerance_does_not_trip_watch
        """
        context = in_force_policy(
            api,
            carrier_overrides=REDSTONE,
            product_overrides={"product_name": "Redstone GA BOLI"},
            employee_overrides={
                "full_name": "Iris Stone",
                "employee_number": "E-6601",
                "annual_salary_usd": 2_000_000.00,
                "officer_flag": True,
            },
            request_overrides={
                "single_premium_usd": 1_500_000.00,
                "face_amount_usd": 4_500_000.00,
            },
            policy_overrides={"policy_number": "RS-0001"},
        )

        valuation = post_valuation(
            api,
            context["policy_id"],
            credited_interest_usd=30_000.00,
            mortality_expense_charge_usd=6_750.00,
            gross_crediting_rate_bps=200,
        )
        assert valuation["cash_value_usd"] == pytest.approx(1_523_250.00, abs=0.01)
        assert valuation["me_charge_bps"] == 45
        assert valuation["me_drift_bps"] == 25
        assert valuation["net_yield_bps"] == 155

        product = validate_success(api.get_product_type(context["product_type_id"], TREASURY))
        assert product["status"] == "OPEN", "a drift of exactly 25 keeps the product open"
        assert product["latest_me_drift_bps"] == 25
        assert product["consecutive_low_yield_count"] == 0, (
            "155 basis points is not below the 150 basis point floor"
        )

    def test_drift_of_twenty_nine_basis_points_moves_the_product_to_on_watch(self, api):
        """One period past the tolerance trips the watch and counts the low yield.

        A period that credits nothing while charging 7,500.00 measures 49 basis
        points of charge, so `me_drift_bps` is 29 — strictly greater than 25 —
        and the yield is negative, a figure the requirements expect: "a figure
        that is legitimately negative when the period's charge exceeded its
        credited interest". The fifth cascade step then applies, since "the
        product's `consecutive_low_yield_count` is incremented by 1 when the
        posting's `net_yield_bps` is" under 150 basis points.

        Design: Difficulty/boundary_precision_check/me_drift_exactly_at_tolerance_does_not_trip_watch
        """
        context = in_force_policy(
            api,
            carrier_overrides=REDSTONE,
            product_overrides={"product_name": "Redstone GA BOLI"},
            employee_overrides={
                "full_name": "Iris Stone",
                "employee_number": "E-6601",
                "annual_salary_usd": 2_000_000.00,
                "officer_flag": True,
            },
            request_overrides={
                "single_premium_usd": 1_500_000.00,
                "face_amount_usd": 4_500_000.00,
            },
            policy_overrides={"policy_number": "RS-0001"},
        )
        post_valuation(
            api,
            context["policy_id"],
            credited_interest_usd=30_000.00,
            mortality_expense_charge_usd=6_750.00,
            gross_crediting_rate_bps=200,
        )

        second = post_valuation(
            api,
            context["policy_id"],
            period_start_date="2026-09-30T00:00:00Z",
            as_of_date="2026-10-31T00:00:00Z",
            credited_interest_usd=0.00,
            mortality_expense_charge_usd=7_500.00,
            gross_crediting_rate_bps=0,
        )
        assert second["prior_cash_value_usd"] == pytest.approx(1_523_250.00, abs=0.01)
        assert second["cash_value_usd"] == pytest.approx(1_515_750.00, abs=0.01)
        assert second["me_charge_bps"] == 49
        assert second["me_drift_bps"] == 29
        assert second["net_yield_bps"] == -49

        product = validate_success(api.get_product_type(context["product_type_id"], TREASURY))
        assert product["status"] == "ON_WATCH"
        assert product["latest_me_drift_bps"] == 29
        assert product["consecutive_low_yield_count"] == 1


class TestProductClosureCascade:
    def test_two_low_yield_periods_close_the_product_and_flag_the_carrier(self, api):
        """The second consecutive low yield closes the product and reaches the carrier.

        "once that count reaches 2 or more, the product is driven to
        `CLOSED_TO_NEW` — from `OPEN` or from `ON_WATCH`, with identical
        treatment on both paths — and the owning carrier's `watch_list_flag` is
        set true with the carrier's `version` incremented by 1". Both periods
        yield 50 basis points, well
        under the floor, while the charge matches the disclosed 50 exactly so
        drift never enters the picture.

        Design: Difficulty/transitive_cascade/valuation_closes_product_then_flags_carrier_then_reopens_review
        """
        context = in_force_policy(
            api,
            carrier_overrides=VANTAGE,
            product_overrides={
                "product_name": "Vantage GA BOLI",
                "disclosed_me_charge_bps": 50,
            },
            employee_overrides={
                "full_name": "Omar Vance",
                "employee_number": "E-6701",
                "annual_salary_usd": 2_000_000.00,
                "officer_flag": True,
            },
            policy_overrides={"policy_number": "VG-0001"},
        )

        first = post_valuation(
            api,
            context["policy_id"],
            credited_interest_usd=10_000.00,
            mortality_expense_charge_usd=5_000.00,
            gross_crediting_rate_bps=100,
        )
        assert first["cash_value_usd"] == pytest.approx(1_005_000.00, abs=0.01)
        assert first["net_yield_bps"] == 50
        assert first["me_drift_bps"] == 0

        second = post_valuation(
            api,
            context["policy_id"],
            period_start_date="2026-09-30T00:00:00Z",
            as_of_date="2026-10-31T00:00:00Z",
            credited_interest_usd=10_000.00,
            mortality_expense_charge_usd=5_025.00,
            gross_crediting_rate_bps=100,
        )
        assert second["cash_value_usd"] == pytest.approx(1_009_975.00, abs=0.01)
        assert second["me_charge_bps"] == 50
        assert second["me_drift_bps"] == 0
        assert second["net_yield_bps"] == 50

        policy = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert policy["cash_surrender_value_usd"] == pytest.approx(1_009_975.00, abs=0.01)

        product = validate_success(api.get_product_type(context["product_type_id"], TREASURY))
        assert product["consecutive_low_yield_count"] == 2
        assert product["status"] == "CLOSED_TO_NEW"

        carrier = validate_success(api.get_carrier(context["carrier_id"], TREASURY))
        assert carrier["watch_list_flag"] is True
        assert carrier["concentration_bps"] == 10
        assert carrier["status"] == "AUTHORIZED", (
            "the watch-list flag is separate from the carrier's own status"
        )

    def test_the_closure_reopens_the_open_annual_review_and_leaves_the_decided_one_alone(self, api):
        """The third hop of the cascade sends the live diligence file back for information.

        The seventh cascade step reaches the carrier's diligence files: "a
        carrier whose `watch_list_flag` has just turned from false to true
        drives" every "diligence review of that carrier currently in
        `UNDER_REVIEW` to `INFO_REQUESTED`, incrementing each such review's
        `info_request_count` by 1 and its `version` by 1", and "the cascaded
        information request is" not "subject to the two-round cap that governs an
        operator-driven information request". A file already decided is not in
        `UNDER_REVIEW`, so it is left exactly as it was.

        Design: Difficulty/transitive_cascade/valuation_closes_product_then_flags_carrier_then_reopens_review
        """
        context = in_force_policy(
            api,
            carrier_overrides=VANTAGE,
            product_overrides={
                "product_name": "Vantage GA BOLI",
                "disclosed_me_charge_bps": 50,
            },
            employee_overrides={
                "full_name": "Omar Vance",
                "employee_number": "E-6701",
                "annual_salary_usd": 2_000_000.00,
                "officer_flag": True,
            },
            policy_overrides={"policy_number": "VG-0001"},
        )
        next_year = open_diligence_review(api, context["carrier_id"], review_year=2027)
        submitted = submit_diligence_review(api, next_year["id"])
        assert submitted["status"] == "UNDER_REVIEW"
        assert submitted["info_request_count"] == 0

        post_valuation(
            api,
            context["policy_id"],
            credited_interest_usd=10_000.00,
            mortality_expense_charge_usd=5_000.00,
            gross_crediting_rate_bps=100,
        )
        post_valuation(
            api,
            context["policy_id"],
            period_start_date="2026-09-30T00:00:00Z",
            as_of_date="2026-10-31T00:00:00Z",
            credited_interest_usd=10_000.00,
            mortality_expense_charge_usd=5_025.00,
            gross_crediting_rate_bps=100,
        )

        reopened = validate_success(api.get_diligence_review(next_year["id"], RISK))
        assert reopened["status"] == "INFO_REQUESTED"
        assert reopened["info_request_count"] == 1

        decided = validate_success(api.get_diligence_review(context["review_id"], RISK))
        assert decided["status"] == "APPROVED", "a terminal file is not re-opened"
        assert decided["info_request_count"] == 0
