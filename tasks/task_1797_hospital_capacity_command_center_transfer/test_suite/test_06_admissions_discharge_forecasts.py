"""Admissions, the discharge milestones, and the forecast staleness cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_bed,
    assert_instant_equal,
    create_admission,
    create_facility,
    create_forecast,
    get_success_data,
    publish_forecast,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["sysadmin_headers"]
BED_MGR = TEST_USERS["bed_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestAdmissionCreation:
    def test_admission_create_on_occupied_bed_rejected(self, api):
        """PRD §3.6: "The bed must belong to the same facility and be both
        `AVAILABLE` and staffed; otherwise creation is rejected with
        `ERR_BED_NOT_AVAILABLE`."

        Design: Corner/validations/admission_create_on_occupied_bed_rejected
        """
        set_clock()
        facility = create_facility(name="Occ Fac")
        bed = add_bed(facility["id"], unit="M-1", label="M1", service="MEDICAL")
        create_admission(facility["id"], bed["id"], patient_ref="POCC1")
        resp = api.create_admission(
            facility["id"],
            {"bed_id": bed["id"], "patient_ref": "POCC2",
             "acuity": "ACUITY_3_MEDICAL_SURGICAL", "isolation_need": "NONE",
             "service": "MEDICAL"},
            BED_MGR)
        validate_error(resp, ApiErrorId.ERR_BED_NOT_AVAILABLE)

    def test_admission_confirm_from_admitted_rejected(self, api):
        """PRD §3.6: "Confirming the discharge requires `PENDING_DISCHARGE`
        (`ERR_ADMISSION_INVALID_STATE`)".

        Design: Corner/errors/admission_confirm_from_admitted_rejected
        """
        set_clock()
        facility = create_facility(name="AIS Fac")
        bed = add_bed(facility["id"], unit="M-1", label="M1", service="MEDICAL")
        admission = create_admission(facility["id"], bed["id"],
                                     patient_ref="PAIS")
        resp = api.confirm_discharge(admission["id"], BED_MGR)
        validate_error(resp, ApiErrorId.ERR_ADMISSION_INVALID_STATE)
        after = validate_success(api.get_admission(admission["id"], COORD))
        assert after["status"] == "ADMITTED"


class TestRescindPendingDischarge:
    def test_rescind_pending_discharge_restores_admitted(self, api):
        """PRD §3.6: "rescinding the pending discharge requires
        `PENDING_DISCHARGE` and returns the admission to `ADMITTED`, clearing
        `pending_discharge_at`, `expected_discharge_at`, and
        `discharge_order_signed` (reset to false) and nulling the bed's
        `projected_free_at`."

        Design: Corner/state_machines/rescind_pending_discharge_restores_admitted
        """
        set_clock()
        facility = create_facility(name="Rescind Fac")
        bed = add_bed(facility["id"], unit="M-1", label="B1", service="MEDICAL")
        admission = create_admission(facility["id"], bed["id"],
                                     patient_ref="PR1")
        get_success_data(api.mark_pending_discharge(
            admission["id"],
            {"expected_discharge_at": "2026-08-01T05:00:00Z",
             "discharge_order_signed": False},
            BED_MGR))
        restored = validate_success(
            api.rescind_pending_discharge(admission["id"], BED_MGR), 200)
        assert restored["status"] == "ADMITTED"
        assert restored["pending_discharge_at"] is None
        assert restored["expected_discharge_at"] is None
        assert restored["discharge_order_signed"] is False
        bed_after = validate_success(api.get_bed(bed["id"], COORD))
        assert bed_after["projected_free_at"] is None


class TestDischargeCascade:
    def _cascade_setup(self, api, name="Cascade Facility"):
        """Facility with 4 staffed non-ED beds; one occupied by an admission
        marked PENDING_DISCHARGE (signed, expected 01:00); a PUBLISHED forecast
        whose hour-1 provisional census qualifies for the elective window."""
        facility = create_facility(name=name)
        b1 = add_bed(facility["id"], unit="M-1", label="B1", service="MEDICAL")
        add_bed(facility["id"], unit="M-1", label="B2", service="MEDICAL")
        add_bed(facility["id"], unit="M-2", label="B3", service="MEDICAL")
        add_bed(facility["id"], unit="M-3", label="B4", service="MEDICAL")
        admission = create_admission(facility["id"], b1["id"], patient_ref="P1")
        get_success_data(api.mark_pending_discharge(
            admission["id"],
            {"expected_discharge_at": "2026-08-01T01:00:00Z",
             "discharge_order_signed": True},
            BED_MGR))
        forecast = create_forecast(facility["id"], horizon_hours=4)
        publish_forecast(forecast["id"])
        return facility, b1, admission, forecast

    def test_confirm_discharge_invalidates_forecast_chain(self, api):
        """PRD §3.9: "Whenever bed availability mutates — a pending-discharge
        mark, a pending-discharge rescind, or a discharge confirmation, per
        §3.6 — the facility's latest `PUBLISHED` forecast is marked `stale`
        true".
        PRD §3.9: "Because `next_elective_window_start` reads only non-stale
        published forecasts, the same mutation also nulls it, and it remains
        null until a fresh publish."

        Design: Difficulty/transitive_cascade/confirm_discharge_invalidates_forecast_chain
        """
        set_clock()
        facility, b1, admission, forecast = self._cascade_setup(api)
        before = validate_success(api.get_facility(facility["id"], COORD))
        assert_instant_equal(before["next_elective_window_start"],
                             "2026-08-01T01:00:00Z")
        forecast_before = validate_success(
            api.get_capacity_forecast(forecast["id"], COORD))
        assert forecast_before["stale"] is False
        discharged = validate_success(
            api.confirm_discharge(admission["id"], BED_MGR), 200)
        assert discharged["status"] == "DISCHARGED"
        forecast_after = validate_success(
            api.get_capacity_forecast(forecast["id"], COORD))
        assert forecast_after["stale"] is True
        facility_after = validate_success(api.get_facility(facility["id"], COORD))
        assert facility_after["next_elective_window_start"] is None

    def test_confirm_discharge_frees_bed_with_cooling(self, api):
        """PRD §3.6: "the bed returns from `OCCUPIED` to `AVAILABLE`, its
        `projected_free_at` is cleared to null, and `cooling_until` is set to
        the confirmation time plus `turnover_minutes`".

        Design: Difficulty/transitive_cascade/confirm_discharge_invalidates_forecast_chain
        """
        set_clock()
        facility, b1, admission, _forecast = self._cascade_setup(
            api, name="Cascade Facility 2")
        validate_success(api.confirm_discharge(admission["id"], BED_MGR), 200)
        bed_after = validate_success(api.get_bed(b1["id"], COORD))
        assert bed_after["status"] == "AVAILABLE"
        assert_instant_equal(bed_after["cooling_until"], "2026-08-01T00:45:00Z")
        assert bed_after["projected_free_at"] is None
        admission_after = validate_success(
            api.get_admission(admission["id"], COORD))
        assert admission_after["status"] == "DISCHARGED"
        assert admission_after["confirmed_discharge_at"] is not None


class TestForecastStaleScope:
    def test_forecast_stale_only_on_published(self, api):
        """PRD §3.9: "Whenever bed availability mutates — a pending-discharge
        mark, a pending-discharge rescind, or a discharge confirmation, per
        §3.6 — the facility's latest `PUBLISHED` forecast is marked `stale`
        true; `PROVISIONAL` forecasts are never marked stale."

        Design: Corner/cross_cutting_layers/forecast_stale_only_on_published
        """
        set_clock()
        facility = create_facility(name="Stale Fac")
        b1 = add_bed(facility["id"], unit="M-1", label="B1", service="MEDICAL")
        add_bed(facility["id"], unit="M-1", label="B2", service="MEDICAL")
        admission = create_admission(facility["id"], b1["id"], patient_ref="PST")
        get_success_data(api.mark_pending_discharge(
            admission["id"],
            {"expected_discharge_at": "2026-08-01T02:00:00Z",
             "discharge_order_signed": True},
            BED_MGR))
        forecast1 = create_forecast(facility["id"], horizon_hours=2)
        publish_forecast(forecast1["id"])
        # The mutation: rescind the pending discharge (a bed-availability
        # mutation per the PRD's enumeration).
        get_success_data(api.rescind_pending_discharge(admission["id"], BED_MGR))
        forecast1_after = validate_success(
            api.get_capacity_forecast(forecast1["id"], COORD))
        assert forecast1_after["stale"] is True
        # A forecast created AFTER the mutation supersedes the published one
        # and must itself be untouched by staleness.
        forecast2 = create_forecast(facility["id"], horizon_hours=2)
        forecast2_after = validate_success(
            api.get_capacity_forecast(forecast2["id"], COORD))
        assert forecast2_after["stale"] is False
        assert forecast2_after["status"] == "PROVISIONAL"
        forecast1_final = validate_success(
            api.get_capacity_forecast(forecast1["id"], COORD))
        assert forecast1_final["status"] == "SUPERSEDED"


class TestForecastLifecycle:
    def test_forecast_publish_and_supersede(self, api):
        """PRD §3.9: "A new forecast starts `PROVISIONAL` with `stale` false,
        and its creation supersedes every prior `PROVISIONAL` or `PUBLISHED`
        forecast of the same facility, moving them to the terminal `SUPERSEDED`
        status. Publishing — restricted to a `PROVISIONAL` forecast, with
        attempts otherwise rejected as `ERR_FORECAST_INVALID_STATE` — moves the
        forecast to `PUBLISHED`, stamps `published_at`".

        Design: Corner/state_machines/forecast_publish_and_supersede
        """
        set_clock()
        facility = create_facility(name="Fc Fac")
        b1 = add_bed(facility["id"], unit="M-1", label="B1", service="MEDICAL")
        add_bed(facility["id"], unit="M-1", label="B2", service="MEDICAL")
        create_admission(facility["id"], b1["id"], patient_ref="PF1")
        forecast1 = create_forecast(facility["id"], horizon_hours=2)
        published = publish_forecast(forecast1["id"])
        assert published["status"] == "PUBLISHED"
        assert published["published_at"] is not None
        forecast2 = create_forecast(facility["id"], horizon_hours=2)
        f1_after = validate_success(
            api.get_capacity_forecast(forecast1["id"], COORD))
        assert f1_after["status"] == "SUPERSEDED"
        assert forecast2["status"] == "PROVISIONAL"
        resp = api.publish_capacity_forecast(forecast1["id"],
                                             TEST_USERS["capacity_planner_headers"])
        validate_error(resp, ApiErrorId.ERR_FORECAST_INVALID_STATE)


class TestForecastCensusVariants:
    def _forecast_fixture(self, api):
        """4 staffed beds (3 non-ED MEDICAL occupied + 1 ED occupied with an
        open boarding record); one signed pending discharge at 02:00 and one
        unsigned at 03:00."""
        facility = create_facility(name="Forecast Facility")
        b1 = add_bed(facility["id"], unit="M-1", label="B1", service="MEDICAL")
        b2 = add_bed(facility["id"], unit="M-1", label="B2", service="MEDICAL")
        b3 = add_bed(facility["id"], unit="M-2", label="B3", service="MEDICAL")
        b4 = add_bed(facility["id"], unit="ED-1", label="B4", service="MEDICAL")
        create_admission(facility["id"], b1["id"], patient_ref="P1")
        adm2 = create_admission(facility["id"], b2["id"], patient_ref="P2")
        adm4 = create_admission(facility["id"], b3["id"], patient_ref="P4")
        adm3 = create_admission(facility["id"], b4["id"], patient_ref="P3")
        from test_helpers import create_boarding_record_payload
        get_success_data(api.create_boarding_record(
            facility["id"], create_boarding_record_payload(adm3["id"]), COORD))
        get_success_data(api.mark_pending_discharge(
            adm2["id"],
            {"expected_discharge_at": "2026-08-01T02:00:00Z",
             "discharge_order_signed": True},
            BED_MGR))
        get_success_data(api.mark_pending_discharge(
            adm4["id"],
            {"expected_discharge_at": "2026-08-01T03:00:00Z",
             "discharge_order_signed": False},
            BED_MGR))
        forecast = create_forecast(facility["id"], horizon_hours=4)
        return facility, forecast

    def test_forecast_committed_census_subtracts_signed_only(self, api):
        """PRD §3.9: "The committed variant subtracts only pending discharges
        whose `discharge_order_signed` is true."

        Design: Difficulty/dual_variant_calc/forecast_committed_vs_provisional_census
        """
        set_clock()
        _facility, forecast = self._forecast_fixture(api)
        data = validate_success(api.get_capacity_forecast(forecast["id"], COORD))
        # base 3; signed at 02:00 counts from hour 2 on; ED conversions ignored.
        assert data["variant_snapshots"]["committed"] == [3, 2, 2, 2]
        # inpatient_bed_count == 3 (ED bed excluded); mean committed = 9/4 = 2.25
        assert data["occupancy_pct_committed"] == pytest.approx(75.0, abs=0.01)

    def test_forecast_provisional_census_adds_ed_conversions(self, api):
        """PRD §3.9: "The provisional variant additionally subtracts those with
        unsigned orders and adds back expected ED conversions: the facility's
        current `boarding_waiters` multiplied by 0.8, rounded up to a whole
        number, the same addition in every hour."
        PRD §3.9: "the two diverge whenever unsigned pending discharges or
        boarding waiters exist."

        Design: Difficulty/dual_variant_calc/forecast_committed_vs_provisional_census
        """
        set_clock()
        _facility, forecast = self._forecast_fixture(api)
        data = validate_success(api.get_capacity_forecast(forecast["id"], COORD))
        # provisional: base 3 - signed - unsigned + ceil(1*0.8)=1 each hour;
        # h1: 3+1=4; h2: 3-1+1=3; h3: 3-1-1+1=2; h4: 2
        assert data["variant_snapshots"]["provisional"] == [4, 3, 2, 2]
        # mean provisional = 11/4 = 2.75; 100 * 2.75 / 3 = 91.666... -> 91.7
        assert data["occupancy_pct_provisional"] == pytest.approx(91.7, abs=0.01)
