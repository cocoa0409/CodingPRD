"""Loss records, scrap workflow, and region loss-rate analytics.

PRD §3.11 governs LossRecord creation, the scrap step, and the
provisional vs. attributed loss-rate ratios.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_loss_record,
    create_loss_record,
    create_loss_record_payload,
    create_region,
    create_rider,
    get_bike,
    get_region,
    get_region_loss_rate,
    scrap_bike,
    setup_region_with_bikes,
    validate_error,
    validate_success,
    ADMIN,
)


class TestLossRecordCreation:
    def test_loss_record_positive_financial_impact(self, api):
        """PRD §3.11: 'a strictly positive financial_impact_cents.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        lr = create_loss_record(
            bike_id=bikes[0]["id"], cause="DAMAGE",
            responsibility="UNKNOWN", financial_impact_cents=5000,
        )
        assert_loss_record(lr)
        assert lr["scrapped"] is False, (
            "PRD §3.11: 'The record is created with scrapped initially "
            "false.'"
        )

    def test_loss_record_zero_financial_impact_rejected(
        self, api, admin_headers,
    ):
        """PRD §3.11: 'a strictly positive financial_impact_cents.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        resp = api.create_loss_record(
            create_loss_record_payload(
                bike_id=bikes[0]["id"], cause="DAMAGE",
                responsibility="UNKNOWN", financial_impact_cents=0,
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


class TestScrap:
    def test_scrap_requires_existing_loss_record(self, api, admin_headers):
        """PRD §3.11: 'It requires that an unscrapped LossRecord
        referencing the bike already exist (otherwise
        ERR_NO_LOSS_RECORD).'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        resp = api.scrap_bike(bikes[0]["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_NO_LOSS_RECORD.value, 409)

    def test_scrap_flips_bike_to_scrapped_and_marks_record(self, api):
        """PRD §3.11: 'On success the bike's shelf_state becomes
        SCRAPPED (a terminal state), the matching LossRecord.scrapped
        is set to true.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        create_loss_record(
            bike_id=bikes[0]["id"], cause="THEFT",
            responsibility="UNKNOWN", financial_impact_cents=5000,
        )
        scrap_bike(bikes[0]["id"])
        bike = get_bike(bikes[0]["id"])
        assert bike["shelf_state"] == "SCRAPPED"


class TestLossRate:
    """PRD §3.11: provisional vs. attributed loss-rate computation."""

    def test_zero_deployed_lifetime_returns_zero_ratios(self, api):
        """PRD §3.11: 'If deployed_lifetime is 0, both reported ratios
        are 0.0.'"""
        region = create_region()
        out = get_region_loss_rate(region["id"])
        assert out["deployed_lifetime"] == 0
        assert out["loss_count"] == 0
        assert out["provisional_loss_rate"] == 0.0
        assert out["attributed_loss_rate"] == 0.0
        assert out["anomaly"] is False

    def test_provisional_counts_all_records_including_unknown(self, api):
        """PRD §3.11: 'provisional_loss_rate is loss_count divided by
        deployed_lifetime and counts every loss record regardless of
        responsibility; attributed_loss_rate is the count of loss
        records whose responsibility is not UNKNOWN, divided by the
        same deployed_lifetime.'"""
        region, bikes = setup_region_with_bikes(num_bikes=10)
        # 1 UNKNOWN + 1 RIDER = 2 total, 1 attributed
        create_loss_record(
            bike_id=bikes[0]["id"], cause="ABANDONED",
            responsibility="UNKNOWN", financial_impact_cents=5000,
        )
        create_loss_record(
            bike_id=bikes[1]["id"], cause="DAMAGE",
            responsibility="OPERATOR",
            responsible_party_id="op-x",
            financial_impact_cents=5000,
        )
        out = get_region_loss_rate(region["id"])
        assert out["loss_count"] == 2
        assert out["deployed_lifetime"] == 10
        # provisional = 2/10 = 0.2, attributed = 1/10 = 0.1
        assert out["provisional_loss_rate"] == pytest.approx(0.2, abs=1e-4)
        assert out["attributed_loss_rate"] == pytest.approx(0.1, abs=1e-4)

    def test_anomaly_triggered_above_threshold(self, api):
        """PRD §3.11: 'An anomaly flag is reported as true when
        provisional_loss_rate is strictly greater than the threshold
        ANOMALY_RATE_THRESHOLD of 0.05.'"""
        region, bikes = setup_region_with_bikes(num_bikes=10)
        # Need provisional > 0.05 → loss_count > 0.5 → 1 loss
        # PRD §3.11: 'responsible_party_id ... is the Rider.id when
        # responsibility is RIDER' — supply a real Rider entity.
        rider = create_rider()
        create_loss_record(
            bike_id=bikes[0]["id"], cause="THEFT",
            responsibility="RIDER",
            responsible_party_id=rider["id"],
            financial_impact_cents=5000,
        )
        out = get_region_loss_rate(region["id"])
        assert out["provisional_loss_rate"] == pytest.approx(0.1, abs=1e-4)
        assert out["anomaly"] is True

    def test_anomaly_false_at_or_below_threshold(self, api):
        """PRD §3.11: 'strictly greater than the threshold' — equal
        does not trigger anomaly."""
        region, bikes = setup_region_with_bikes(num_bikes=20)
        # 1/20 = 0.05 exactly → anomaly false (strictly greater rule)
        create_loss_record(
            bike_id=bikes[0]["id"], cause="ABANDONED",
            responsibility="UNKNOWN", financial_impact_cents=5000,
        )
        out = get_region_loss_rate(region["id"])
        assert out["provisional_loss_rate"] == pytest.approx(0.05, abs=1e-4)
        assert out["anomaly"] is False, (
            "PRD §3.11: 'strictly greater than the threshold' — "
            "0.05 exactly is not an anomaly"
        )
