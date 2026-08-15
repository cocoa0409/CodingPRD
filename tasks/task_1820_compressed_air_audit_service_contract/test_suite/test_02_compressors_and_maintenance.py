"""Compressor registry, run-hours telemetry, and dryer/filter maintenance claims."""
from test_helpers import (
    ApiErrorId,
    assert_compressor,
    assert_maintenance_schedule,
    create_compressor,
    create_facility,
    create_maintenance_schedule_payload,
    get_facility,
    log_run_hours,
    make_contract_manager_headers,
    make_dealer_admin_headers,
    make_energy_engineer_headers,
    make_service_tech_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_dealer_admin_headers()
ENGINEER = make_energy_engineer_headers("eng-1")
TECH = make_service_tech_headers("tech-1")
CONTRACT_MGR = make_contract_manager_headers()


def _facility_with_compressor(name: str, run_hours: int = 4000) -> tuple:
    facility = create_facility(name=name)
    compressor = create_compressor(facility["id"])
    if run_hours:
        log_run_hours(compressor["id"], run_hours)
    return facility, compressor


class TestCompressorRegistry:
    def test_compressor_duplicate_asset_tag_rejected(self, api):
        """PRD §3.2: "Within a facility, an `asset_tag` must be unique among
        compressors that are not `DECOMMISSIONED`; a collision is rejected with
        `ERR_DUPLICATE_ASSET_TAG`."

        Design: Corner/entities/corner_compressor_duplicate_asset_tag_rejected
        """
        facility = create_facility(name="F-DUP", activate=False)
        first = create_compressor(facility["id"], asset_tag="C1")
        assert_compressor(first)

        resp = api.create_compressor(
            {
                "facility_id": facility["id"],
                "asset_tag": "C1",
                "rated_kw": 30,
                "rated_cfm": 150,
            },
            TECH,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSET_TAG, 409)

        data, meta = validate_paginated(
            api.list_compressors(TECH, params={"facility_id": facility["id"]})
        )
        assert meta["total_count"] == 1, f"duplicate must not register, got {meta['total_count']}"
        assert data[0]["id"] == first["id"]


class TestCompressorOutageCycle:
    def test_compressor_down_return_cycle_status(self, api):
        """PRD §3.2: "Marking a compressor down — permitted only while its facility
        is not `OFFBOARDED` — moves it from `IN_SERVICE` to `DOWN`, and because even
        a single `DOWN` unit forces `OUTAGE_ACTIVE`, the posture recompute and
        certificate `settlement_blocked` refresh follow immediately. Returning the
        unit to service moves it from `DOWN` back to `IN_SERVICE`; the outage clears
        when the facility's last `DOWN` unit returns, again with the full recompute
        chain."

        Design: Difficulty/non_linear_state_machine/compressor_down_return_cycle
        """
        facility, compressor = _facility_with_compressor("F-CYC", run_hours=0)

        compressor = validate_success(api.mark_down(compressor["id"], TECH))
        assert compressor["status"] == "DOWN"

        compressor = validate_success(api.return_to_service(compressor["id"], TECH))
        assert compressor["status"] == "IN_SERVICE"

        compressor = validate_success(api.mark_down(compressor["id"], TECH))
        assert compressor["status"] == "DOWN", "the outage cycle must be re-enterable"

    def test_compressor_down_return_cycle_posture(self, api):
        """PRD §2.6: "A facility's posture is `OUTAGE_ACTIVE` whenever at least one
        of its compressors is `DOWN`; otherwise it is `MAINTENANCE_DELINQUENT`
        whenever at least one of its `ACTIVE` dryer or filter schedules is
        delinquent; otherwise it is `NORMAL`."
        PRD §3.2: "Returning the unit to service moves it from `DOWN` back to
        `IN_SERVICE`; the outage clears when the facility's last `DOWN` unit
        returns, again with the full recompute chain."

        Design: Difficulty/non_linear_state_machine/compressor_down_return_cycle
        """
        facility, compressor = _facility_with_compressor("F-CYC2", run_hours=0)

        validate_success(api.mark_down(compressor["id"], TECH))
        assert get_facility(facility["id"])["posture"] == "OUTAGE_ACTIVE"

        validate_success(api.return_to_service(compressor["id"], TECH))
        assert get_facility(facility["id"])["posture"] == "NORMAL"

        validate_success(api.mark_down(compressor["id"], TECH))
        assert get_facility(facility["id"])["posture"] == "OUTAGE_ACTIVE", (
            "second outage must force OUTAGE_ACTIVE again"
        )


class TestRunHoursTelemetry:
    def test_run_hours_regression_rejected(self, api):
        """PRD §3.2: "Run-hours telemetry is monotonic. When a `ServiceTech` logs
        run-hours, the new `run_hours_total` must be at least the compressor's
        current value — a lower reading is a regression rejected with
        `ERR_RUN_HOURS_REGRESSION` (HTTP 422)."

        Design: Corner/validations/corner_run_hours_regression_rejected
        """
        _, compressor = _facility_with_compressor("F-RH", run_hours=4000)

        resp = api.log_run_hours(compressor["id"], {"run_hours_total": 3000}, TECH)
        validate_error(resp, ApiErrorId.ERR_RUN_HOURS_REGRESSION, 422)

        compressor = validate_success(
            api.log_run_hours(compressor["id"], {"run_hours_total": 4000}, TECH)
        )
        assert compressor["run_hours_total"] == 4000, "an equal re-log must be accepted"


class TestMaintenanceSchedules:
    def test_duplicate_schedule_component_rejected(self, api):
        """PRD §3.2: "only one `ACTIVE` schedule may exist per facility and
        component, and a duplicate is rejected with
        `ERR_DUPLICATE_SCHEDULE_COMPONENT`."

        Design: Corner/entities/corner_duplicate_schedule_component_rejected
        """
        facility = create_facility(name="F-DS")
        first = validate_success(
            api.create_maintenance_schedule(
                create_maintenance_schedule_payload(
                    facility_id=facility["id"], component="DRYER", interval_hours=2000
                ),
                CONTRACT_MGR,
            ),
            201,
        )
        assert_maintenance_schedule(first)

        resp = api.create_maintenance_schedule(
            create_maintenance_schedule_payload(
                facility_id=facility["id"], component="DRYER", interval_hours=1000
            ),
            CONTRACT_MGR,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCHEDULE_COMPONENT, 409)

        second = validate_success(
            api.create_maintenance_schedule(
                create_maintenance_schedule_payload(
                    facility_id=facility["id"], component="FILTER", interval_hours=1000
                ),
                CONTRACT_MGR,
            ),
            201,
        )
        assert second["status"] == "ACTIVE"
        assert second["component"] == "FILTER"

    def test_record_service_reading_bounds(self, api):
        """PRD §3.2: "Two checks guard it, evaluated in this order: the reading must
        be at least the schedule's current `anchor_run_hours` — a lower reading is
        rejected with `ERR_RUN_HOURS_REGRESSION` — and the reading must not exceed
        the facility watermark, because a technician cannot have serviced at a
        run-hour point no compressor has logged yet (`ERR_READING_EXCEEDS_LOGGED`,
        HTTP 422)."

        Design: Corner/validations/corner_record_service_reading_bounds
        """
        facility, compressor = _facility_with_compressor("F-RS", run_hours=4000)
        schedule = validate_success(
            api.create_maintenance_schedule(
                create_maintenance_schedule_payload(
                    facility_id=facility["id"], component="DRYER", interval_hours=2000
                ),
                CONTRACT_MGR,
            ),
            201,
        )

        resp = api.record_service(
            schedule["id"], {"service_date": "2026-08-05", "run_hours_reading": 4500}, TECH
        )
        validate_error(resp, ApiErrorId.ERR_READING_EXCEEDS_LOGGED, 422)

        resp = api.record_service(
            schedule["id"], {"service_date": "2026-08-05", "run_hours_reading": 3000}, TECH
        )
        validate_error(resp, ApiErrorId.ERR_RUN_HOURS_REGRESSION, 422)

        schedule = validate_success(
            api.record_service(
                schedule["id"], {"service_date": "2026-08-05", "run_hours_reading": 4000}, TECH
            )
        )
        assert schedule["anchor_run_hours"] == 4000, "both bounds are inclusive"

    def test_maintenance_delinquent_below_due_hours(self, api):
        """PRD §3.2: "A schedule's `is_delinquent` flag is true exactly when the
        schedule is `ACTIVE` and the facility watermark has reached or passed
        `next_due_run_hours`; reaching the due point precisely already counts as
        delinquent, because the comparison is inclusive."

        Design: Difficulty/boundary_precision_check/maintenance_delinquent_at_exact_due_hours
        """
        facility, compressor = _facility_with_compressor("F-B1", run_hours=4000)
        schedule = validate_success(
            api.create_maintenance_schedule(
                create_maintenance_schedule_payload(
                    facility_id=facility["id"], component="DRYER", interval_hours=2000
                ),
                CONTRACT_MGR,
            ),
            201,
        )
        assert schedule["anchor_run_hours"] == 4000
        assert schedule["next_due_run_hours"] == 6000

        log_run_hours(compressor["id"], 5999)
        schedule = validate_success(api.get_maintenance_schedule(schedule["id"], TECH))
        assert schedule["is_delinquent"] is False, (
            "5999 run-hours is below the 6000 due point and must not be delinquent"
        )

    def test_maintenance_delinquent_at_exact_due_hours(self, api):
        """PRD §3.2: "A schedule's `is_delinquent` flag is true exactly when the
        schedule is `ACTIVE` and the facility watermark has reached or passed
        `next_due_run_hours`; reaching the due point precisely already counts as
        delinquent, because the comparison is inclusive."
        PRD §2.6: "A facility's posture is `OUTAGE_ACTIVE` whenever at least one of
        its compressors is `DOWN`; otherwise it is `MAINTENANCE_DELINQUENT` whenever
        at least one of its `ACTIVE` dryer or filter schedules is delinquent;
        otherwise it is `NORMAL`."

        Design: Difficulty/boundary_precision_check/maintenance_delinquent_at_exact_due_hours
        """
        facility, compressor = _facility_with_compressor("F-B1B", run_hours=4000)
        schedule = validate_success(
            api.create_maintenance_schedule(
                create_maintenance_schedule_payload(
                    facility_id=facility["id"], component="DRYER", interval_hours=2000
                ),
                CONTRACT_MGR,
            ),
            201,
        )

        log_run_hours(compressor["id"], 6000)
        schedule = validate_success(api.get_maintenance_schedule(schedule["id"], TECH))
        assert schedule["next_due_run_hours"] == 6000
        assert schedule["is_delinquent"] is True, (
            "6000 >= 6000: the inclusive boundary makes the schedule delinquent"
        )
        assert get_facility(facility["id"])["posture"] == "MAINTENANCE_DELINQUENT"

    def test_posture_recovers_after_service(self, api):
        """PRD §3.2: "A successful recording keeps the schedule `ACTIVE` while
        resetting `anchor_run_hours` to the reading, recomputing
        `next_due_run_hours`, and recomputing `is_delinquent` — which clears when
        the lifted anchor pushes the due point beyond the watermark. Posture and
        certificate `settlement_blocked` recompute as usual."

        Design: Corner/cross_cutting_complexity_layers/corner_posture_recovers_after_service
        """
        facility, compressor = _facility_with_compressor("F-REC", run_hours=4000)
        schedule = validate_success(
            api.create_maintenance_schedule(
                create_maintenance_schedule_payload(
                    facility_id=facility["id"], component="DRYER", interval_hours=2000
                ),
                CONTRACT_MGR,
            ),
            201,
        )
        log_run_hours(compressor["id"], 6000)
        assert get_facility(facility["id"])["posture"] == "MAINTENANCE_DELINQUENT"

        schedule = validate_success(
            api.record_service(
                schedule["id"], {"service_date": "2026-08-05", "run_hours_reading": 6000}, TECH
            )
        )
        assert schedule["anchor_run_hours"] == 6000
        assert schedule["next_due_run_hours"] == 8000
        assert schedule["is_delinquent"] is False
        assert get_facility(facility["id"])["posture"] == "NORMAL", (
            "posture must reconcile to NORMAL within the record-service request"
        )
