"""Plan catalogue and star-rating banding.

Covers PRD §3.3: plan CRUD, star_rating banding by composite, and the
"latest measurement_year overwrites Plan.star_rating" rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_plan,
    assert_star_rating_snapshot,
    create_plan,
    create_plan_payload,
    create_star_rating_payload,
    publish_star_rating,
    re_get_beneficiary,
    setup_clock_at,
    validate_error,
    validate_success,
)


class TestPlanCreation:
    """PRD §3.3 plan creation."""

    def test_create_part_c_plan(self, api, admin_headers):
        """PRD §3.3: "A PlanAdmin creates a plan with plan_code (1 to 40
        characters, unique), plan_type (one of PART_A, PART_B, PART_C,
        PART_D, MEDIGAP), plan_year (a four-digit year between 2020 and
        2030 inclusive), and monthly_premium_cents."

        Claim: a valid Part C plan is accepted with HTTP 201.
        """
        setup_clock_at(2026, 1, 1)
        resp = api.create_plan(
            create_plan_payload(plan_type="PART_C", plan_year=2026,
                                monthly_premium_cents=12_000,
                                star_rating=4.0),
            admin_headers,
        )
        plan = validate_success(resp, expected_status=201)
        assert_plan(plan)
        assert plan["plan_type"] == "PART_C"

    def test_plan_year_below_min_rejected(self, api, admin_headers):
        """PRD §3.3: "a four-digit year between 2020 and 2030
        inclusive".

        Claim: plan_year=2019 -> ERR_VALIDATION.
        """
        setup_clock_at(2026, 1, 1)
        resp = api.create_plan(
            create_plan_payload(plan_year=2019), admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_plan_year_above_max_rejected(self, api, admin_headers):
        """PRD §3.3: "a four-digit year between 2020 and 2030
        inclusive".

        Claim: plan_year=2031 -> ERR_VALIDATION.
        """
        setup_clock_at(2026, 1, 1)
        resp = api.create_plan(
            create_plan_payload(plan_year=2031), admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestStarRatingBanding:
    """PRD §3.3 weighted composite banding."""

    @pytest.mark.parametrize(
        "clinical, experience, service, expected_star",
        [
            # PRD §3.3: 50%*clinical + 30%*experience + 20%*service.
            # 100 raw all -> composite 100 -> 5.0
            (100.0, 100.0, 100.0, 5.0),
            # 85 raw all -> composite 85 -> band [80, 90) -> 4.5
            (85.0, 85.0, 85.0, 4.5),
            # 70 raw all -> composite 70 -> band [70, 80) -> 4.0
            (70.0, 70.0, 70.0, 4.0),
            # 55 raw all -> composite 55 -> band [50, 60) -> 3.0
            (55.0, 55.0, 55.0, 3.0),
            # 10 raw all -> composite 10 -> raw < 20 -> 1.0
            (10.0, 10.0, 10.0, 1.0),
        ],
    )
    def test_band_mapping(self, api, admin_headers, clinical, experience,
                          service, expected_star):
        """PRD §3.3: "a composite of 90 or higher maps to 5.0; from 80
        up to but excluding 90 maps to 4.5; from 70 up to but excluding
        80 maps to 4.0; from 60 up to but excluding 70 maps to 3.5;
        from 50 up to but excluding 60 maps to 3.0; from 40 up to but
        excluding 50 maps to 2.5; from 30 up to but excluding 40 maps
        to 2.0; from 20 up to but excluding 30 maps to 1.5; and
        anything below 20 maps to 1.0."

        Claim: composite raw maps deterministically to the banded
        weighted_star_rating per the inclusive-lower-bound rule.
        """
        setup_clock_at(2026, 1, 1)
        plan = create_plan(plan_type="PART_C", plan_year=2026,
                           monthly_premium_cents=10_000,
                           star_rating=3.0)
        resp = api.publish_star_rating(
            plan["id"],
            create_star_rating_payload(
                measurement_year=2026,
                clinical_quality_score=clinical,
                member_experience_score=experience,
                customer_service_score=service,
            ),
            admin_headers,
        )
        snapshot = validate_success(resp, expected_status=201)
        assert snapshot["weighted_star_rating"] == expected_star, (
            f"composite from ({clinical},{experience},{service}) should "
            f"band to {expected_star}, got "
            f"{snapshot['weighted_star_rating']}"
        )

    def test_exact_90_maps_to_five_inclusive(self, api, admin_headers):
        """PRD §3.3: "a composite exactly equal to 90.0000 is therefore
        5.0, not 4.5."

        Claim: composite_raw exactly 90.0000 -> star 5.0 (inclusive
        boundary).
        """
        setup_clock_at(2026, 1, 1)
        plan = create_plan(plan_type="PART_C", plan_year=2026,
                           monthly_premium_cents=10_000,
                           star_rating=3.0)
        # 0.5*90 + 0.3*90 + 0.2*90 = 90.0
        resp = api.publish_star_rating(
            plan["id"],
            create_star_rating_payload(
                measurement_year=2026,
                clinical_quality_score=90.0,
                member_experience_score=90.0,
                customer_service_score=90.0,
            ),
            admin_headers,
        )
        snapshot = validate_success(resp, expected_status=201)
        assert snapshot["weighted_star_rating"] == 5.0, (
            f"expected 5.0 at composite=90.0000 (inclusive), got "
            f"{snapshot['weighted_star_rating']}"
        )

    def test_just_below_80_falls_to_four(self, api, admin_headers):
        """PRD §3.3: "from 80 up to but excluding 90 maps to 4.5;
        from 70 up to but excluding 80 maps to 4.0".

        Claim: composite 79.998 falls into [70, 80) -> 4.0.
        """
        setup_clock_at(2026, 1, 1)
        plan = create_plan(plan_type="PART_C", plan_year=2026,
                           monthly_premium_cents=10_000,
                           star_rating=3.0)
        # 0.5*80 + 0.3*80 + 0.2*79.99 = 40 + 24 + 15.998 = 79.998
        resp = api.publish_star_rating(
            plan["id"],
            create_star_rating_payload(
                measurement_year=2026,
                clinical_quality_score=80.0,
                member_experience_score=80.0,
                customer_service_score=79.99,
            ),
            admin_headers,
        )
        snapshot = validate_success(resp, expected_status=201)
        assert snapshot["weighted_star_rating"] == 4.0, (
            f"expected 4.0 at composite ~79.998, got "
            f"{snapshot['weighted_star_rating']}"
        )


class TestStarRatingSideEffect:
    """PRD §3.3: plan.star_rating overwritten only when measurement_year
    is the latest."""

    def test_latest_year_overwrites_plan_star_rating(self, api,
                                                    admin_headers):
        """PRD §3.3: "if and only if this snapshot's measurement_year
        equals the maximum measurement_year among all snapshots for the
        same plan_id, the parent Plan.star_rating is overwritten with
        the new weighted_star_rating."

        Claim: publishing a snapshot with later measurement_year flips
        the plan's star_rating to the new band.
        """
        setup_clock_at(2026, 1, 1)
        plan = create_plan(plan_type="PART_C", plan_year=2026,
                           monthly_premium_cents=10_000,
                           star_rating=3.0)
        # 2026: composite 70 -> 4.0
        publish_star_rating(
            plan=plan, measurement_year=2026,
            clinical_quality_score=70.0,
            member_experience_score=70.0,
            customer_service_score=70.0,
        )
        # 2027: composite 85 -> 4.5 (latest year)
        publish_star_rating(
            plan=plan, measurement_year=2027,
            clinical_quality_score=85.0,
            member_experience_score=85.0,
            customer_service_score=85.0,
        )
        refreshed = validate_success(
            api.get_plan(plan["id"], admin_headers),
        )
        assert refreshed["star_rating"] == 4.5, (
            f"plan.star_rating should reflect the latest "
            f"measurement_year's band, got {refreshed['star_rating']}"
        )

    def test_earlier_year_does_not_overwrite_plan_star_rating(
        self, api, admin_headers,
    ):
        """PRD §3.3: "if and only if this snapshot's measurement_year
        equals the maximum measurement_year among all snapshots for the
        same plan_id, the parent Plan.star_rating is overwritten with
        the new weighted_star_rating."

        Claim: a snapshot for an EARLIER measurement_year does NOT
        change Plan.star_rating.
        """
        setup_clock_at(2026, 1, 1)
        plan = create_plan(plan_type="PART_C", plan_year=2026,
                           monthly_premium_cents=10_000,
                           star_rating=3.0)
        # 2027 first (latest yet): composite 85 -> 4.5
        publish_star_rating(
            plan=plan, measurement_year=2027,
            clinical_quality_score=85.0,
            member_experience_score=85.0,
            customer_service_score=85.0,
        )
        # 2026 (older): composite 100 -> 5.0; should NOT overwrite.
        publish_star_rating(
            plan=plan, measurement_year=2026,
            clinical_quality_score=100.0,
            member_experience_score=100.0,
            customer_service_score=100.0,
        )
        refreshed = validate_success(
            api.get_plan(plan["id"], admin_headers),
        )
        assert refreshed["star_rating"] == 4.5, (
            f"older measurement_year must NOT overwrite plan.star_rating, "
            f"got {refreshed['star_rating']}"
        )
