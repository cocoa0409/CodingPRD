"""The two reliability variants: the decayed rolling score and the certification review."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    api_client,
    assert_calibration_band_matches_variance,
    assert_calibration_record,
    calibration_record_payload,
    setup_shadow_calibration,
    validate_error,
    validate_success,
)


def _record_second_calibration(program):
    return validate_success(
        api_client.create_calibration_record(
            calibration_record_payload(program["second_shadow"]["id"]),
            program["reviewer_calibration_headers"],
        ),
        expected_status=201,
    )


class TestRollingReliability:
    def test_first_calibration_applies_the_unacceptable_band_at_full_weight(self):
        """The newest calibration delta counts at full strength against the baseline.

        PRD: "Weight them by recency: the newest record's `reliability_delta` counts at
        full strength, the second at six tenths, the third at three tenths."

        Design: Difficulty/dual_variant_calc/auditor_reliability_rolling_versus_certification_review_diverges
        """
        program = setup_shadow_calibration()
        record = program["calibration_records"][0]
        assert_calibration_record(record)

        assert program["primary_visit"]["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert program["first_shadow"]["composite_score"] == pytest.approx(78.80, abs=0.01), \
            "the shadow sheet drops both critical food-safety items"
        assert record["variance_points"] == pytest.approx(11.90, abs=0.01)
        assert record["band"] == "UNACCEPTABLE", "a variance above 10.00 points is UNACCEPTABLE"
        assert record["reliability_delta"] == pytest.approx(-8.00, abs=0.01)
        assert_calibration_band_matches_variance(record)
        assert record["auditor_id"] == program["auditor"]["id"], \
            "the audited party is the primary visit's auditor"
        assert record["reviewer_auditor_id"] == program["reviewer"]["id"]

        auditor = validate_success(
            api_client.get_auditor(program["auditor"]["id"], ADMIN_HEADERS)
        )
        assert auditor["reliability_score"] == pytest.approx(62.00, abs=0.01), \
            "70.00 baseline plus one full-weight debit of 8.00"
        assert auditor["status"] == "CERTIFIED", "62.00 still clears the 60.00 floor"
        assert auditor["suspension_reason"] is None

    def test_second_calibration_decays_the_older_delta_and_trips_the_floor(self):
        """The second-newest delta counts at six tenths, dropping the score below 60.00.

        PRD: "If the recomputed rolling score of a `CERTIFIED` auditor falls below 60.00,
        the system immediately suspends that auditor as a cascade, advancing
        `CERTIFIED → SUSPENDED` with `suspension_reason` `RELIABILITY_BELOW_FLOOR`."

        Design: Difficulty/dual_variant_calc/auditor_reliability_rolling_versus_certification_review_diverges
        """
        program = setup_shadow_calibration()
        second_record = _record_second_calibration(program)

        assert second_record["variance_points"] == pytest.approx(11.90, abs=0.01)
        assert second_record["reliability_delta"] == pytest.approx(-8.00, abs=0.01)

        auditor = validate_success(
            api_client.get_auditor(program["auditor"]["id"], ADMIN_HEADERS)
        )
        assert auditor["reliability_score"] == pytest.approx(57.20, abs=0.01), \
            "70.00 + 1.00 * -8.00 + 0.60 * -8.00 is 57.20, not the undecayed 54.00"
        assert auditor["status"] == "SUSPENDED"
        assert auditor["suspension_reason"] == "RELIABILITY_BELOW_FLOOR", \
            "only the reliability cascade records RELIABILITY_BELOW_FLOOR"

    def test_recertification_uses_the_undecayed_variant_and_is_refused(self):
        """Certification sums every in-period delta at full weight, so it reads lower.

        PRD: "Because nothing is dropped and nothing is decayed, this figure can read
        quite differently from the stored rolling score."

        Design: Difficulty/dual_variant_calc/auditor_reliability_rolling_versus_certification_review_diverges
        """
        program = setup_shadow_calibration()
        _record_second_calibration(program)

        validate_error(
            api_client.certify_auditor(program["auditor"]["id"], ADMIN_HEADERS, {}),
            ApiErrorId.ERR_RELIABILITY_BELOW_FLOOR,
            expected_status=409,
        )

        auditor = validate_success(
            api_client.get_auditor(program["auditor"]["id"], ADMIN_HEADERS)
        )
        assert auditor["status"] == "SUSPENDED", "the refused certification changes nothing"
        assert auditor["reliability_score"] == pytest.approx(57.20, abs=0.01), \
            "the stored score remains the rolling variant, not the review figure of 54.00"
        assert auditor["suspension_reason"] == "RELIABILITY_BELOW_FLOOR"
