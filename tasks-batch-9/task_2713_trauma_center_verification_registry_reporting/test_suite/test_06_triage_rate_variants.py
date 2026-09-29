"""The two triage-rate variants and the empty-cohort boundary they share.

One cohort of cases answers two different questions depending on which variant is
requested, and neither answer may leak into the other or onto the center.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ApiClient,
    DesignationLevel,
    ReadinessPosture,
    TierCode,
    TriageRateVariant,
    TriageReviewStatus,
    assert_cohort_partition,
    assert_decimal,
    assert_triage_rates_read,
    fixtures as fx,
    make_trauma_program_manager_headers,
    make_verification_reviewer_headers,
)


def _adjudicated_cohort(api: ApiClient) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Four INCLUDED cases whose review outcomes and injury data disagree.

    K1 is a badly injured consult case the director judged appropriate, K2 is a minor
    injury given a full activation that the director confirmed as under-triage, K3 agrees
    with its data, and K4 has never been abstracted at all.
    """
    fx.anchor_clock(api)
    center = fx.create_center(
        api,
        name="Northgate Trauma",
        state_code="OH",
        designation_level=DesignationLevel.LEVEL_I,
    )
    tier_full = fx.create_tier(
        api,
        center["id"],
        tier_code=TierCode.TIER_1_FULL,
        surgeon_response_limit_minutes=15,
        specialty_response_limit_minutes=30,
        iss_threshold=16,
    )
    tier_consult = fx.create_tier(
        api,
        center["id"],
        tier_code=TierCode.TIER_3_CONSULT,
        surgeon_response_limit_minutes=30,
        specialty_response_limit_minutes=60,
        iss_threshold=4,
    )

    k1, _ = fx.case_validated(
        api,
        center["id"],
        tier_consult["id"],
        mrn="MRN-K1",
        arrival_at="2026-07-20T08:00:00Z",
        injury_severity_score=25,
        los_hours=96.00,
        iss_abstracted=25,
        gcs_arrival=9,
        mechanism_code="MVC",
        ed_departure_at="2026-07-20T11:00:00Z",
    )
    fx.triage_review(api, k1, TriageReviewStatus.APPROPRIATE)

    k2, _ = fx.case_validated(
        api,
        center["id"],
        tier_full["id"],
        mrn="MRN-K2",
        arrival_at="2026-07-21T08:00:00Z",
        injury_severity_score=5,
        los_hours=96.00,
        iss_abstracted=5,
        gcs_arrival=15,
        mechanism_code="FALL",
        ed_departure_at="2026-07-21T10:00:00Z",
    )
    fx.triage_review(api, k2, TriageReviewStatus.UNDER_TRIAGE_CONFIRMED)

    k3, _ = fx.case_validated(
        api,
        center["id"],
        tier_full["id"],
        mrn="MRN-K3",
        arrival_at="2026-07-22T08:00:00Z",
        injury_severity_score=20,
        los_hours=96.00,
        iss_abstracted=20,
        gcs_arrival=12,
        mechanism_code="GSW",
        ed_departure_at="2026-07-22T09:30:00Z",
    )
    fx.triage_review(api, k3, TriageReviewStatus.APPROPRIATE)

    k4 = fx.create_case(
        api,
        center["id"],
        tier_consult["id"],
        mrn="MRN-K4",
        arrival_at="2026-07-23T08:00:00Z",
        injury_severity_score=10,
        los_hours=96.00,
    )
    fx.triage_review(api, k4, TriageReviewStatus.APPROPRIATE)

    return center, {"k1": k1, "k2": k2, "k3": k3, "k4": k4}


class TestTriageRateVariantDivergence:
    """The monitoring and audit readings of one cohort."""

    def test_the_two_variants_return_different_numerators_and_denominators(
        self, api: ApiClient
    ) -> None:
        """Four cases yield 25.00/0.00 by review outcome and 33.33/33.33 by injury data.

        Design: Difficulty/dual_variant_calc/triage_rate_variants_diverge_on_identical_case_cohort
        """
        center, _ = _adjudicated_cohort(api)

        monitoring = get_success_data(
            api.get_triage_rates(
                center["id"], make_trauma_program_manager_headers(center["id"])
            )
        )
        assert_triage_rates_read(
            monitoring,
            None,
            denominator=4,
            under_numerator=1,
            over_numerator=0,
            under_rate=25.00,
            over_rate=0.00,
        )

        audit = get_success_data(
            api.get_triage_rates(
                center["id"],
                make_verification_reviewer_headers(),
                {"variant": TriageRateVariant.VERIFICATION_AUDIT},
            )
        )
        assert_triage_rates_read(
            audit,
            TriageRateVariant.VERIFICATION_AUDIT,
            denominator=3,
            under_numerator=1,
            over_numerator=1,
            under_rate=33.33,
            over_rate=33.33,
        )

    def test_only_the_monitoring_variant_reaches_the_center_record(
        self, api: ApiClient
    ) -> None:
        """Reading the audit variant leaves the persisted rates and cohort untouched.

        Design: Difficulty/dual_variant_calc/triage_rate_variants_diverge_on_identical_case_cohort
        """
        center, _ = _adjudicated_cohort(api)

        get_success_data(
            api.get_triage_rates(
                center["id"],
                make_verification_reviewer_headers(),
                {"variant": TriageRateVariant.VERIFICATION_AUDIT},
            )
        )

        after = fx.get_center(api, center["id"])
        assert_decimal(after["under_triage_rate_pct"], 25.00, "under_triage_rate_pct")
        assert_decimal(after["over_triage_rate_pct"], 0.00, "over_triage_rate_pct")
        assert_cohort_partition(after, included=4, excluded=0)


class TestTriageRatesOnAnEmptyCohort:
    """A center with no cases is a boundary, not an error."""

    def test_both_variants_report_zero_when_no_cases_exist(self, api: ApiClient) -> None:
        """A zero denominator produces 0.00 rates rather than a division failure.

        Design: Difficulty/boundary_precision_check/triage_rates_on_empty_case_cohort_return_zero
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Wind Gap Trauma",
            state_code="PA",
            designation_level=DesignationLevel.LEVEL_III,
        )

        monitoring = get_success_data(
            api.get_triage_rates(
                center["id"], make_trauma_program_manager_headers(center["id"])
            )
        )
        assert_triage_rates_read(
            monitoring,
            None,
            denominator=0,
            under_numerator=0,
            over_numerator=0,
            under_rate=0.00,
            over_rate=0.00,
        )

        audit = get_success_data(
            api.get_triage_rates(
                center["id"],
                make_verification_reviewer_headers(),
                {"variant": TriageRateVariant.VERIFICATION_AUDIT},
            )
        )
        assert_triage_rates_read(
            audit,
            TriageRateVariant.VERIFICATION_AUDIT,
            denominator=0,
            under_numerator=0,
            over_numerator=0,
            under_rate=0.00,
            over_rate=0.00,
        )

    def test_an_empty_cohort_crosses_no_alert_threshold(self, api: ApiClient) -> None:
        """Zero rates leave the center at its registration defaults.

        Design: Difficulty/boundary_precision_check/triage_rates_on_empty_case_cohort_return_zero
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Wind Gap Trauma",
            state_code="PA",
            designation_level=DesignationLevel.LEVEL_III,
        )

        get_success_data(
            api.get_triage_rates(
                center["id"], make_trauma_program_manager_headers(center["id"])
            )
        )

        after = fx.get_center(api, center["id"])
        assert_decimal(after["under_triage_rate_pct"], 0.00, "under_triage_rate_pct")
        assert_cohort_partition(after, included=0, excluded=0)
        assert after["open_pi_event_count"] == 0, "no alert event may be opened"
        assert after["readiness_posture"] == ReadinessPosture.READY
