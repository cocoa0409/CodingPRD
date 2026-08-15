"""SSO events: the regulatory reporting clock, volume estimation (provisional
and final variants), and the submission deadline."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    create_sso,
    create_station,
    get_sso,
    reset_clock,
    setup_sso_report_draft,
    setup_station_with_pumps,
    validate_error,
    validate_success,
)


class TestRegulatorDeadline:
    def test_report_deadline_24h_standard(self, api, utility_admin_headers):
        """PRD §3.8: "At creation the statutory reporting deadline is fixed on
        the event as `regulator_deadline_at`: normally 24 hours after
        `started_at`, but tightened to 12 hours after `started_at` when
        `reached_surface_water` is true — the stricter tier for overflows that
        reach a water body."

        Design: Corner/calculations/report_deadline_24h_standard
        """
        reset_clock("2026-08-01T10:30:00Z")
        station = create_station()
        res_sso = create_sso(
            station["id"], started_at="2026-08-01T10:30:00Z", cause_code="DEBRIS",
            reached_surface_water=False,
        )
        assert_instant_equal(
            res_sso["regulator_deadline_at"], "2026-08-02T10:30:00Z",
        )

    def test_report_deadline_12h_surface_water(self, api, utility_admin_headers):
        """PRD §3.8: "At creation the statutory reporting deadline is fixed on
        the event as `regulator_deadline_at`: normally 24 hours after
        `started_at`, but tightened to 12 hours after `started_at` when
        `reached_surface_water` is true — the stricter tier for overflows that
        reach a water body."

        Design: Corner/calculations/report_deadline_12h_surface_water
        """
        reset_clock("2026-08-01T10:30:00Z")
        station = create_station()
        res_sso = create_sso(
            station["id"], started_at="2026-08-01T10:30:00Z",
            cause_code="GREASE_BLOCKAGE", reached_surface_water=True,
        )
        assert_instant_equal(
            res_sso["regulator_deadline_at"], "2026-08-01T22:30:00Z",
        )


class TestVolumeEstimate:
    def test_sso_volume_surface_water_multiplier(self, api, operator_headers):
        """PRD §3.8: "The volume rule measures the overflow duration in whole
        minutes — the difference between `stopped_at` and `started_at`, floored
        to integer minutes — and multiplies it by the station's
        `firm_capacity_available_gpm` as computed at `stopped_at`. When
        `reached_surface_water` is true, that base volume is then multiplied by
        the 1.20 regulatory penalty multiplier for water-body reach. The result
        is rounded half-up to whole gallons."

        Design: Corner/calculations/sso_volume_surface_water_multiplier
        """
        reset_clock()
        station, _ = setup_station_with_pumps(
            ratings=(250, 250), design_capacity_gpm=500,
        )
        sso = create_sso(
            station["id"], started_at="2026-08-01T00:00:00Z",
            cause_code="PUMP_FAILURE", reached_surface_water=True,
        )
        reset_clock("2026-08-01T01:00:00Z")
        res = api.contain_sso_event(sso["id"], operator_headers)
        contained = validate_success(res, 200)
        assert contained["status"] == "CONTAINED"
        assert contained["stopped_at"] is not None
        assert contained["estimated_volume_gal"] == pytest.approx(18000), (
            "60 min * 250 gpm firm capacity * 1.20 surface-water multiplier"
        )

    def test_provisional_volume_at_containment(self, api, operator_headers):
        """PRD §3.8: "Containment is an `Operator` action allowed only while the
        station's posture is `EMERGENCY`, moving the event `OPEN → CONTAINED`,
        stamping `stopped_at`, and computing the provisional
        `estimated_volume_gal`."
        PRD §3.8: "The volume rule measures the overflow duration in whole
        minutes — the difference between `stopped_at` and `started_at`, floored
        to integer minutes — and multiplies it by the station's
        `firm_capacity_available_gpm` as computed at `stopped_at`."

        Design: Difficulty/dual_variant_calc/sso_volume_provisional_vs_final
        """
        reset_clock()
        station, _ = setup_station_with_pumps(
            ratings=(300, 300), design_capacity_gpm=500,
        )
        sso = create_sso(
            station["id"], started_at="2026-08-01T00:00:00Z",
            cause_code="GREASE_BLOCKAGE", reached_surface_water=False,
        )
        reset_clock("2026-08-01T02:00:00Z")
        res = api.contain_sso_event(sso["id"], operator_headers)
        contained = validate_success(res, 200)
        assert contained["estimated_volume_gal"] == pytest.approx(36000), (
            "provisional variant: 120 min * 300 gpm firm capacity at stopped_at"
        )

    def test_final_volume_recomputed_and_overwritten_at_submission(
        self, api, compliance_officer_headers, operator_headers
    ):
        """PRD §3.8: "Submission also recomputes the volume estimate in its
        final variant: the same duration-times-capacity rule is re-evaluated
        using the capacity snapshot in effect at submission time, and the new
        value overwrites the provisional `estimated_volume_gal`."
        PRD §3.8: "Submission moves `REPORT_DRAFT → REPORT_SUBMITTED` and stamps
        `report_submitted_at`; submission must occur on or before
        `regulator_deadline_at`"

        With station capacity unchanged between containment and submission, the
        final variant reproduces the provisional figure for the same incident.

        Design: Difficulty/dual_variant_calc/sso_volume_provisional_vs_final
        """
        reset_clock()
        station, _ = setup_station_with_pumps(
            ratings=(300, 300), design_capacity_gpm=500,
        )
        sso = create_sso(
            station["id"], started_at="2026-08-01T00:00:00Z",
            cause_code="GREASE_BLOCKAGE", reached_surface_water=False,
        )
        reset_clock("2026-08-01T02:00:00Z")
        res = api.contain_sso_event(sso["id"], operator_headers)
        contained = validate_success(res, 200)
        provisional = contained["estimated_volume_gal"]
        assert provisional == pytest.approx(36000)
        res = api.draft_sso_report(sso["id"], compliance_officer_headers)
        validate_success(res, 200)
        res = api.submit_sso_report(sso["id"], compliance_officer_headers)
        submitted = validate_success(res, 200)
        assert submitted["status"] == "REPORT_SUBMITTED"
        assert submitted["report_submitted_at"] is not None
        assert submitted["estimated_volume_gal"] == pytest.approx(36000), (
            "final variant recomputed at submission with unchanged capacity"
        )
        stored = get_sso(sso["id"])
        assert stored["estimated_volume_gal"] == pytest.approx(36000), (
            "the final value is the value persisted on the event"
        )


class TestReportDeadlineEnforcement:
    def test_sso_submit_after_deadline_rejected(self, api, compliance_officer_headers):
        """PRD §3.8: "Submission moves `REPORT_DRAFT → REPORT_SUBMITTED` and
        stamps `report_submitted_at`; submission must occur on or before
        `regulator_deadline_at`, and a late submission is accepted only when
        the request carries an `override_note` explaining the escalation —
        otherwise it is rejected with `ERR_REPORT_DEADLINE_MISSED` (HTTP 422)."

        Design: Corner/validations/sso_submit_after_deadline_rejected
        """
        reset_clock()
        station, _ = setup_station_with_pumps(ratings=(150, 150))
        sso = setup_sso_report_draft(
            station["id"], started_at="2026-08-01T00:00:00Z",
            contained_at="2026-08-01T01:00:00Z", cause_code="DEBRIS",
        )
        reset_clock("2026-08-03T00:00:00Z")
        res = api.submit_sso_report(sso["id"], compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_REPORT_DEADLINE_MISSED)
