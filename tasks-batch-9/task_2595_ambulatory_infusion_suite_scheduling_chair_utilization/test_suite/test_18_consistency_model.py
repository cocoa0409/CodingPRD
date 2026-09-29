"""Immediate consistency read literally: the write response itself already carries the whole
derivation, the very next read of a neighbouring row already carries the cascade, and an
analytics read taken in the same breath already counts the row that has just been written."""

from test_helpers import (
    PHARMACIST,
    SCHEDULER,
    LotStatus,
    ReadinessStatus,
    ScheduleStatus,
    UtilizationVariant,
    book_appointment,
    create_lot,
    make_cancel_payload,
    make_lot_adjustment_payload,
    read_chair,
    read_nurse,
    read_utilization,
    setup_suite,
    validate_success,
)

SETUP_CLOCK = "2026-08-01T00:00:00Z"
SERVICE_DATE = "2026-08-10"


class TestEveryWriteResponseAlreadyCarriesItsDerivationAndItsCascade:
    """One centre with a single chair and a single nurse, so every derived figure in the
    estate has exactly one contributor and no settling step can hide behind averaging."""

    def _estate(self, api):
        """The standing estate with a stocked lot and nothing booked yet."""
        suite = setup_suite(
            api, clock=SETUP_CLOCK, nurse_specs=[{"acuity_capacity_points": 12}]
        )
        lot = create_lot(api, suite.drug_id, units_received=10)
        return suite, lot

    def _book(self, api, suite):
        return book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date=SERVICE_DATE,
            requested_start_minute=540,
        )

    def test_the_booking_response_already_holds_the_window_the_picks_and_the_readiness(
        self, api
    ):
        """The creation responses of the chair and the nurse already carry their zeroed
        counters, and the booking response that follows already carries the whole window
        build, the pinned template revision, the derived readiness and the two rows the
        selector chose — none of it deferred to a later read.

        Design: Corner/consistency_model/every_write_response_already_carries_its_derived_fields_and_cascades
        """
        suite, _lot = self._estate(api)
        assert suite.chair("A1")["committed_minutes"] == 0
        assert suite.nurse["assigned_acuity_points"] == 0

        booked = self._book(api, suite)
        assert booked["schedule_status"] == ScheduleStatus.TENTATIVE
        assert booked["start_minute"] == 540
        assert booked["end_minute"] == 780
        assert booked["chair_minutes"] == 240
        assert booked["acuity_points"] == 3
        assert booked["template_version_pinned"] == suite.template["version"]
        assert booked["readiness_status"] == ReadinessStatus.PENDING
        assert booked["chair_id"] == suite.chair_id("A1")
        assert booked["nurse_id"] == suite.nurse_id

    def test_the_next_reads_and_an_analytics_read_need_no_settling_step(self, api):
        """The chair's committed minutes, the nurse's carried acuity and the utilization
        report are all correct on the read immediately after the booking, and the inventory
        adjustment re-derives a figure it was never sent inside the same response.

        Design: Corner/consistency_model/every_write_response_already_carries_its_derived_fields_and_cascades
        """
        suite, lot = self._estate(api)
        self._book(api, suite)

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 3

        report = read_utilization(
            api, suite.center_id, SERVICE_DATE, UtilizationVariant.SCHEDULED
        )
        assert report["available_chair_minutes"] == 660
        assert report["occupied_chair_minutes"] == 240
        assert report["utilization_pct"] == 36.36
        assert report["appointment_count"] == 1

        adjusted = validate_success(
            api.create_lot_adjustment(
                lot["id"],
                make_lot_adjustment_payload(
                    5, lot["version"], reason="Second carton received"
                ),
                PHARMACIST,
            )
        )
        assert adjusted["units_received"] == 15
        assert adjusted["units_available"] == 15
        assert adjusted["status"] == LotStatus.AVAILABLE

    def test_the_release_is_carried_by_the_cancel_response_and_the_reads_behind_it(self, api):
        """The cancel response itself carries the terminal status and the settled charge, the
        assignment stays on the row as the audit trail of who was scheduled to do the work,
        and the released capacity is visible on the reads that follow with no lag.

        Design: Corner/consistency_model/every_write_response_already_carries_its_derived_fields_and_cascades
        """
        suite, _lot = self._estate(api)
        booked = self._book(api, suite)

        cancelled = validate_success(
            api.cancel_appointment(
                booked["id"], SCHEDULER, make_cancel_payload("Patient travelling")
            )
        )
        assert cancelled["schedule_status"] == ScheduleStatus.CANCELLED
        assert cancelled["cancellation_charge_cents"] == 0
        assert cancelled["late_cancellation"] is False
        assert cancelled["chair_id"] == suite.chair_id("A1")

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 0
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 0

        after = read_utilization(
            api, suite.center_id, SERVICE_DATE, UtilizationVariant.SCHEDULED
        )
        assert after["occupied_chair_minutes"] == 0
        assert after["utilization_pct"] == 0.00
        assert after["appointment_count"] == 0
