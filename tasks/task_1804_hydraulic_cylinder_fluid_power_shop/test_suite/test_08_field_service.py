"""Field service scheduling windows, hose-crimp pricing variants, and crimp
tolerance (PRD §3.9)."""
from test_helpers import (
    ADMIN,
    ADVISOR,
    ApiErrorId,
    create_field_service_job_payload,
    get_success_data,
    hose_assembly,
    make_technician_headers,
    schedule_field_job,
    setup_field_job,
    setup_field_job_dispatched,
    validate_error,
    validate_success,
)


def _schedule(api, job, tech, window_start, window_end, expected_version=None):
    return schedule_field_job(job, tech, window_start, window_end, expected_version)


class TestTechnicianWindowSemantics:
    def test_adjacent_windows_touching_at_endpoint_accepted(self, api):
        """PRD §3.9: "Field windows are half-open intervals, including their
        start and excluding their end, so two windows that merely touch at an
        endpoint do not collide; any true overlap with another `SCHEDULED` or
        `DISPATCHED` job of the same technician is rejected with
        `ERR_TECHNICIAN_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/technician_half_open_window_adjacency
        """
        sc = setup_field_job(distance_km=60)
        job2 = get_success_data(
            api.create_field_service_job(
                create_field_service_job_payload(
                    sc.customer["id"], site_address="8 Mill St", distance_km=40,
                    assemblies=[hose_assembly(hose_type="THERMOPLASTIC", length_m=1.5,
                                              fitting_price_cents=1200, crimp_spec_mm=19.5)],
                ),
                ADVISOR,
            )
        )
        validate_success(
            _schedule(api, sc.job, sc.field_tech,
                      "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z")
        )
        tech = get_success_data(api.get_technician(sc.field_tech["id"], ADVISOR))
        # [12:00, 14:00) touches [10:00, 12:00) at the endpoint only: no collision.
        scheduled2 = validate_success(
            _schedule(api, job2, sc.field_tech,
                      "2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z",
                      expected_version=tech["version"])
        )
        assert scheduled2["status"] == "SCHEDULED"
        assert scheduled2["technician_id"] == sc.field_tech["id"]

    def test_true_overlap_rejected(self, api):
        """PRD §3.9: "Field windows are half-open intervals, including their
        start and excluding their end, so two windows that merely touch at an
        endpoint do not collide; any true overlap with another `SCHEDULED` or
        `DISPATCHED` job of the same technician is rejected with
        `ERR_TECHNICIAN_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/technician_half_open_window_adjacency
        """
        sc = setup_field_job(distance_km=60)
        job2 = get_success_data(
            api.create_field_service_job(
                create_field_service_job_payload(sc.customer["id"], site_address="8 Mill St",
                                                 distance_km=40),
                ADVISOR,
            )
        )
        job3 = get_success_data(
            api.create_field_service_job(
                create_field_service_job_payload(sc.customer["id"], site_address="3 Dock Ln",
                                                 distance_km=20),
                ADVISOR,
            )
        )
        validate_success(_schedule(api, sc.job, sc.field_tech,
                                   "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z"))
        tech = get_success_data(api.get_technician(sc.field_tech["id"], ADVISOR))
        validate_success(_schedule(api, job2, sc.field_tech,
                                   "2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z",
                                   expected_version=tech["version"]))
        tech = get_success_data(api.get_technician(sc.field_tech["id"], ADVISOR))
        # [11:00, 13:00) truly intersects both existing windows.
        resp = _schedule(api, job3, sc.field_tech,
                         "2026-08-03T11:00:00Z", "2026-08-03T13:00:00Z",
                         expected_version=tech["version"])
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_WINDOW_OVERLAP)
        job3_after = get_success_data(api.get_field_service_job(job3["id"], ADVISOR))
        assert job3_after["status"] == "REQUESTED"


class TestFieldPricingVariants:
    def test_provisional_vs_final_with_emergency_callout(self, api):
        """PRD §3.9: "The provisional variant at creation assumes a non-emergency
        callout; the final variant at completion uses the `emergency_callout`
        flag as computed at schedule time."
        PRD §3.9: "Scheduling moves the job from `REQUESTED` to `SCHEDULED`, sets
        `technician_id` and the window, computes `emergency_callout` — true
        exactly when the gap between the job's `created_at` and its
        `window_start` is at most `emergency_callout_window_hours` (4 hours by
        default), the boundary inclusive — and increments the technician's
        `version` by one."

        Design: Corner/calculations/field_service_pricing_variants
        """
        assemblies = [
            hose_assembly(hose_type="WIRE_BRAID_2SN", length_m=2.0,
                          fitting_price_cents=1800, crimp_spec_mm=27.0),
            hose_assembly(hose_type="THERMOPLASTIC", length_m=1.5,
                          fitting_price_cents=1200, crimp_spec_mm=19.5),
        ]
        sc = setup_field_job(assemblies=assemblies, distance_km=80)
        # Provisional (non-emergency): 25000 + (4500+6400+3600) + (4500+2700+2400)
        #                              + (80-50)x250 = 56600.
        assert sc.job["provisional_price_cents"] == 56600
        # Window starts 3h after the 2026-08-01T00:00Z creation: emergency.
        scheduled = validate_success(
            _schedule(api, sc.job, sc.field_tech,
                      "2026-08-01T03:00:00Z", "2026-08-01T05:00:00Z")
        )
        assert scheduled["emergency_callout"] is True
        dispatched = get_success_data(
            api.dispatch_field_service_job(
                sc.job["id"], make_technician_headers(sc.field_tech["id"])
            )
        )
        assert dispatched["status"] == "DISPATCHED"
        completed = validate_success(
            api.complete_field_service_job(
                sc.job["id"],
                {"crimp_measurements": [
                    {"index": 0, "crimp_measured_mm": 27.0},
                    {"index": 1, "crimp_measured_mm": 19.5},
                ]},
                make_technician_headers(sc.field_tech["id"]),
            )
        )
        assert completed["status"] == "COMPLETED"
        # Final: callout 25000 x 2.0 = 50000 + 14500 + 9600 + 7500 = 81600.
        assert completed["final_price_cents"] == 81600


class TestCrimpTolerance:
    def test_out_of_tolerance_completion_rejected_and_persists_measurement(self, api):
        """PRD §3.9: "When any assembly is out of tolerance the completion is
        rejected with `ERR_CRIMP_OUT_OF_TOLERANCE` — and the measurements still
        persist, the out-of-tolerance assemblies are marked `FAIL`, and the job
        remains `DISPATCHED` for correction and a later completion attempt."

        Design: Corner/calculations/crimp_tolerance_inclusive_boundary
        """
        sc = setup_field_job_dispatched(distance_km=60)
        # |26.69 - 27.0| = 0.31 > 0.3 tolerance.
        resp = api.complete_field_service_job(
            sc.job["id"],
            {"crimp_measurements": [{"index": 0, "crimp_measured_mm": 26.69}]},
            make_technician_headers(sc.field_tech["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CRIMP_OUT_OF_TOLERANCE)
        job = get_success_data(api.get_field_service_job(sc.job["id"], ADVISOR))
        assert job["status"] == "DISPATCHED"
        assert job["assemblies"][0]["crimp_measured_mm"] == 26.69
        assert job["assemblies"][0]["assembly_result"] == "FAIL"

    def test_within_tolerance_completion_succeeds_with_final_price(self, api):
        """PRD §3.9: "Each measurement is written to its assembly's
        `crimp_measured_mm` and judged against the assembly's `crimp_spec_mm`: a
        deviation of at most `crimp_tolerance_mm` (0.3 millimetres by default),
        inclusive, passes. When every assembly is within tolerance, the
        assemblies resolve to `PASS`, the job moves from `DISPATCHED` to the
        terminal `COMPLETED` state, and `final_price_cents` is computed under the
        final pricing variant."

        Design: Corner/calculations/crimp_tolerance_inclusive_boundary
        """
        sc = setup_field_job_dispatched(distance_km=60)
        # |26.71 - 27.0| = 0.29 <= 0.3: within tolerance.
        completed = validate_success(
            api.complete_field_service_job(
                sc.job["id"],
                {"crimp_measurements": [{"index": 0, "crimp_measured_mm": 26.71}]},
                make_technician_headers(sc.field_tech["id"]),
            )
        )
        assert completed["status"] == "COMPLETED"
        assert completed["assemblies"][0]["assembly_result"] == "PASS"
        # Non-emergency: 25000 + (4500 + 6400 + 3600) + (60-50)x250 = 42000.
        assert completed["final_price_cents"] == 42000


class TestScheduleGuards:
    def test_field_schedule_window_in_past_rejected(self, api):
        """PRD §3.9: "The `window_start` must not lie before the current logical
        clock — a window starting exactly now is acceptable — otherwise
        `ERR_WINDOW_IN_PAST`."

        Design: Corner/validations/field_schedule_window_in_past_rejected
        """
        sc = setup_field_job(distance_km=40)
        get_success_data(api.set_clock({"to_iso8601": "2026-08-10T00:00:00Z"}, ADMIN))
        resp = _schedule(api, sc.job, sc.field_tech,
                         "2026-08-09T10:00:00Z", "2026-08-09T12:00:00Z")
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)
        job = get_success_data(api.get_field_service_job(sc.job["id"], ADVISOR))
        assert job["status"] == "REQUESTED"

    def test_field_schedule_stale_technician_version_rejected(self, api):
        """PRD §2.6: "Scheduling a field service job requires
        `expected_technician_version`, compared against the `Technician`'s
        current `version`. A rejection means the schedule view the client planned
        against is stale, even when the requested window itself is free."
        PRD §2.6: "If that value does not equal the parent entity's current
        `version` — because another write has advanced the entity since the
        client last read it — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/field_schedule_stale_technician_version_rejected
        """
        sc = setup_field_job(distance_km=60)
        stale_version = sc.field_tech["version"]
        job2 = get_success_data(
            api.create_field_service_job(
                create_field_service_job_payload(sc.customer["id"], site_address="8 Mill St",
                                                 distance_km=40),
                ADVISOR,
            )
        )
        # Scheduling job 1 advances the technician's version.
        validate_success(_schedule(api, sc.job, sc.field_tech,
                                   "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z",
                                   expected_version=stale_version))
        # Job 2's window is free and disjoint, but the carried version is stale.
        resp = _schedule(api, job2, sc.field_tech,
                         "2026-08-04T10:00:00Z", "2026-08-04T12:00:00Z",
                         expected_version=stale_version)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        job2_after = get_success_data(api.get_field_service_job(job2["id"], ADVISOR))
        assert job2_after["status"] == "REQUESTED"
