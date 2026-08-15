"""Quality metric reports (STRICT/EXPANDED) and room-utilization computed read."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_clock,
    assert_quality_report,
    assert_rate,
    cancel_booking,
    check_in,
    confirm_prep,
    create_booking,
    create_egd_type,
    create_patient,
    create_provider,
    create_quality_report,
    create_room,
    create_scope,
    create_colono_type,
    run_procedure_to_complete,
    setup_quality_metrics_scenario,
    setup_utilization_scenario,
    collect_specimen,
    assess_prep,
    complete_procedure,
    start_procedure,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["unit_admin_headers"]
QO = TEST_USERS["quality_officer_headers"]
SCHED = TEST_USERS["scheduler_headers"]


class TestAdrVariants:
    def test_adr_strict_denominator_filters(self, api):
        """PRD §3.9: "Under the `STRICT` variant, the denominator admits only
        those candidates that additionally satisfy all four auditing filters:
        `indication` of `SCREENING`, a patient at least 45 years old at the
        scheduled start (the same full-calendar-years age rule as §3.2),
        `cecum_intubated` true, and prep axis `PREP_ADEQUATE`."
        PRD §3.9: "the `adenoma_detection_rate` is null when the denominator is
        zero, otherwise one hundred times the numerator divided by the
        denominator, rounded half-up to one decimal place."

        Design: Difficulty/dual_variant_calc/adr_screening_strict_vs_expanded_denominators
        """
        fx = setup_quality_metrics_scenario()
        report = create_quality_report(fx["provider"]["id"], "2026-08-03T00:00:00Z",
                                       "2026-08-03T23:59:59Z", "STRICT")
        assert_quality_report(report)
        assert report["adr_denominator"] == 3, "B1, B2, B7 survive all four filters"
        assert report["adr_numerator"] == 1, "only B1 has adenomas_detected >= 1"
        assert_rate(report["adenoma_detection_rate"], 33.3, "STRICT ADR")

    def test_adr_expanded_denominator_diverges(self, api):
        """PRD §3.9: "Under the `EXPANDED` variant, the denominator is the whole
        candidate set with no further filtering — the operational denominator,
        which routinely yields a different rate from the same underlying data."

        Design: Difficulty/dual_variant_calc/adr_screening_strict_vs_expanded_denominators
        """
        fx = setup_quality_metrics_scenario()
        report = create_quality_report(fx["provider"]["id"], "2026-08-03T00:00:00Z",
                                       "2026-08-03T23:59:59Z", "EXPANDED")
        assert report["adr_denominator"] == 6, "all completed adr_relevant colonoscopies"
        assert report["adr_numerator"] == 3, "B1, B3, B4"
        assert_rate(report["adenoma_detection_rate"], 50.0, "EXPANDED ADR")

    def test_variant_invariant_metrics_on_same_fixture(self, api):
        """PRD §3.9: "Its inclusion set is the provider's `COMPLETED` bookings
        whose procedure type is in the `colonoscopy_family`, with `actual_end` in
        the period, `cecum_intubated` true, `adenomas_detected` exactly zero, and
        zero Specimen rows linked through `booking_id` — a specimen in any status
        counts as taken and excludes the booking."
        PRD §3.9: "The `cecal_intubation_rate` divides the provider's `COMPLETED`,
        `colonoscopy_family`, in-period bookings into those with `cecum_intubated`
        true".
        PRD §3.9: "The `prep_adequacy_rate` takes the provider's bookings with
        `actual_end` in the period whose prep axis has been assessed —
        `PREP_ADEQUATE` or `PREP_INADEQUATE` — and expresses the `PREP_ADEQUATE`
        share the same way".

        Design: Difficulty/dual_variant_calc/adr_screening_strict_vs_expanded_denominators
        """
        fx = setup_quality_metrics_scenario()
        for variant in ("STRICT", "EXPANDED"):
            report = create_quality_report(fx["provider"]["id"],
                                           "2026-08-03T00:00:00Z",
                                           "2026-08-03T23:59:59Z", variant)
            assert report["withdrawal_sample_size"] == 1, "B2 alone"
            assert_rate(report["withdrawal_time_avg_seconds"], 480.0,
                        f"withdrawal avg ({variant})")
            assert_rate(report["cecal_intubation_rate"], 83.3,
                        f"5 of 6 completed colonoscopy-family ({variant})")
            assert_rate(report["prep_adequacy_rate"], 71.4,
                        f"5 adequate of 7 assessed ({variant})")


class TestEmptyDenominators:
    def _egd_only_day(self):
        patient = create_patient(mrn="M6001", date_of_birth="1990-05-05")
        drz = create_provider("Dr Zed")
        t_egd = create_egd_type()
        room = create_room(name="RZ")
        sg1 = create_scope(serial_number="SG-1", scope_type="GASTROSCOPE")
        b1 = create_booking(patient["id"], drz["id"], t_egd["id"], room["id"],
                            scheduled_start="2026-08-03T08:00:00Z",
                            indication="DIAGNOSTIC")
        confirm_prep(b1["id"])
        run_procedure_to_complete(b1["id"], drz["id"], sg1["id"],
                                  "2026-08-03T08:00:00Z", "2026-08-03T08:25:00Z",
                                  cecum_intubated=False, withdrawal_time_seconds=200,
                                  adenomas_detected=0)
        return drz

    def test_adr_null_when_denominator_zero(self, api):
        """PRD §3.9: "the `adenoma_detection_rate` is null when the denominator is
        zero".

        Design: Difficulty/boundary_precision_check/adr_null_when_denominator_zero
        """
        drz = self._egd_only_day()
        report = create_quality_report(drz["id"], "2026-08-03T00:00:00Z",
                                       "2026-08-03T23:59:59Z", "STRICT")
        assert report["adr_denominator"] == 0, "EGD is not adr_relevant"
        assert report["adenoma_detection_rate"] is None, "empty denominator is null, not 0.0"

    def test_withdrawal_and_cir_null_prep_rate_100(self, api):
        """
        PRD §3.9: "The `withdrawal_time_avg_seconds` is null when the set is empty,
        otherwise the mean of `withdrawal_time_seconds` across the set, rounded
        half-up to one decimal place; `withdrawal_sample_size` reports the set's
        size."

        PRD §3.9: "The `cecal_intubation_rate` divides the provider's `COMPLETED`,
        `colonoscopy_family`, in-period bookings into those with `cecum_intubated`
        true, is null when that denominator is zero, and otherwise expresses the
        percentage with one half-up-rounded decimal."

        PRD §3.9: "The `prep_adequacy_rate` takes the provider's bookings with
        `actual_end` in the period whose prep axis has been assessed —
        `PREP_ADEQUATE` or `PREP_INADEQUATE` — and expresses the `PREP_ADEQUATE`
        share the same way, null when the denominator is zero."

        Design: Difficulty/boundary_precision_check/adr_null_when_denominator_zero
        """
        drz = self._egd_only_day()
        report = create_quality_report(drz["id"], "2026-08-03T00:00:00Z",
                                       "2026-08-03T23:59:59Z", "STRICT")
        assert report["withdrawal_sample_size"] == 0, "EGD is not colonoscopy_family"
        assert report["withdrawal_time_avg_seconds"] is None
        assert report["cecal_intubation_rate"] is None
        assert_rate(report["prep_adequacy_rate"], 100.0, "1 assessed adequate of 1")


class TestUtilization:
    def test_utilization_per_room_figures(self, api):
        """PRD §3.9: "For every Room regardless of `status`, the occupied minutes
        are the sum of block minutes — `scheduled_start` to `room_block_end` —
        over bookings whose `scheduled_start` falls on that UTC date and whose
        booking axis is `SCHEDULED`, `CHECKED_IN`, `IN_PROGRESS`, `COMPLETED`, or
        `ABORTED_PREP_INADEQUATE`".
        PRD §3.9: "The response carries the `date`, the `open_minutes_per_room`
        constant (480), the `unit_utilization_pct`, and a `rooms` array with each
        room's occupied minutes and percentage".

        Design: Difficulty/combinatorial_formula/unit_utilization_round_per_room_then_average_mode_b
        """
        fx = setup_utilization_scenario()
        report = validate_success(api.get_room_utilization(QO, "2026-08-05"), 200)
        assert report["open_minutes_per_room"] == 480
        rows = {r.get("room_id"): r for r in report["rooms"]}
        assert rows[fx["ru1"]["id"]]["occupied_minutes"] == 200, "65+65+70"
        assert_rate(rows[fx["ru1"]["id"]]["utilization_pct"], 41.7)
        assert rows[fx["ru2"]["id"]]["occupied_minutes"] == 115, "65+50"
        assert_rate(rows[fx["ru2"]["id"]]["utilization_pct"], 24.0)

    def test_utilization_unit_round_per_room_then_average(self, api):
        """PRD §3.9: "the rounding order is pinned: each room is rounded first,
        the unit figure `unit_utilization_pct` is then the average of those
        per-room percentages, itself rounded half-up to one decimal place.
        Computing the unit figure from raw summed minutes instead is a different,
        non-conformant algorithm."

        Design: Difficulty/combinatorial_formula/unit_utilization_round_per_room_then_average_mode_b
        """
        setup_utilization_scenario()
        report = validate_success(api.get_room_utilization(QO, "2026-08-05"), 200)
        # round-half-up(avg(41.7, 24.0), 1) == 32.9; the sum-then-round order
        # (315/960 == 32.8) is non-conformant.
        assert_rate(report["unit_utilization_pct"], 32.9, "unit utilization")

    def test_utilization_excludes_cancelled_and_noshow(self, api):
        """PRD §3.9: "`CANCELLED`, `NO_SHOW`, and `RESCHEDULED` bookings are
        excluded."

        Design: Corner/calculations/utilization_excludes_cancelled_and_noshow
        """
        patient = create_patient(mrn="MRN-UX")
        provider = create_provider("Dr Ux")
        t_col = create_colono_type()
        room = create_room(name="R-U3")
        create_booking(patient["id"], provider["id"], t_col["id"], room["id"],
                       scheduled_start="2026-08-06T08:00:00Z")
        by = create_booking(patient["id"], provider["id"], t_col["id"], room["id"],
                            scheduled_start="2026-08-06T09:00:00Z")
        cancel_booking(by["id"])
        report = validate_success(api.get_room_utilization(ADMIN, "2026-08-06"), 200)
        rows = {r.get("room_id"): r for r in report["rooms"]}
        assert rows[room["id"]]["occupied_minutes"] == 55, "only the live booking"
        assert_rate(rows[room["id"]]["utilization_pct"], 11.5)
        assert_rate(report["unit_utilization_pct"], 11.5, "single-room unit figure")


class TestReportPeriodAndImmutability:
    def test_report_period_inclusive_bounds(self, api):
        """PRD §3.9: "The period bounds are both inclusive against bookings'
        `actual_end`".

        Design: Corner/calculations/report_period_inclusive_bounds
        """
        patient = create_patient(mrn="MRN-PB", date_of_birth="1976-03-10")
        drb = create_provider("Dr Pb")
        t_col = create_colono_type()
        room = create_room(name="R-PB")
        scopes = [create_scope(serial_number=f"SP-{i}") for i in (1, 2, 3)]
        bx = create_booking(patient["id"], drb["id"], t_col["id"], room["id"],
                            scheduled_start="2026-08-09T23:30:00Z")
        by = create_booking(patient["id"], drb["id"], t_col["id"], room["id"],
                            scheduled_start="2026-08-10T23:00:00Z")
        bz = create_booking(patient["id"], drb["id"], t_col["id"], room["id"],
                            scheduled_start="2026-08-11T00:30:00Z")
        for b in (bx, by, bz):
            confirm_prep(b["id"])
        # BX completes exactly at period_start.
        run_procedure_to_complete(bx["id"], drb["id"], scopes[0]["id"],
                                  "2026-08-09T23:30:00Z", "2026-08-10T00:00:00Z",
                                  withdrawal_time_seconds=500, adenomas_detected=1)
        # BY completes exactly at period_end.
        run_procedure_to_complete(by["id"], drb["id"], scopes[1]["id"],
                                  "2026-08-10T23:00:00Z", "2026-08-10T23:59:59Z",
                                  withdrawal_time_seconds=450, adenomas_detected=0)
        # BZ completes just past period_end.
        run_procedure_to_complete(bz["id"], drb["id"], scopes[2]["id"],
                                  "2026-08-11T00:30:00Z", "2026-08-11T01:00:00Z",
                                  withdrawal_time_seconds=480, adenomas_detected=1)
        report = create_quality_report(drb["id"], "2026-08-10T00:00:00Z",
                                       "2026-08-10T23:59:59Z", "STRICT")
        assert report["adr_denominator"] == 2, "both boundary completions included"
        assert report["adr_numerator"] == 1
        assert_rate(report["adenoma_detection_rate"], 50.0)
        assert report["withdrawal_sample_size"] == 1, "BY only (BX has adenomas)"
        assert_rate(report["withdrawal_time_avg_seconds"], 450.0)

    def test_quality_report_snapshot_unchanged_by_later_activity(self, api):
        """PRD §3.9: "The report is computed exactly once, at creation, into an
        immutable snapshot — recall from §2.5 that it carries only `id` and
        `created_at`, with no `updated_at` and no `version`, so later bookings can
        never retroactively alter a published figure."

        Design: Corner/entities/quality_report_snapshot_unchanged_by_later_activity
        """
        patient = create_patient(mrn="MRN-SNAP", date_of_birth="1976-03-10")
        drq = create_provider("Dr Snap")
        t_col = create_colono_type()
        room = create_room(name="RQ")
        qs1 = create_scope(serial_number="QS-1")
        qs2 = create_scope(serial_number="QS-2")
        b1 = create_booking(patient["id"], drq["id"], t_col["id"], room["id"],
                            scheduled_start="2026-08-03T08:00:00Z")
        b2 = create_booking(patient["id"], drq["id"], t_col["id"], room["id"],
                            scheduled_start="2026-08-03T09:00:00Z")
        confirm_prep(b1["id"])
        confirm_prep(b2["id"])
        run_procedure_to_complete(b1["id"], drq["id"], qs1["id"],
                                  "2026-08-03T08:00:00Z", "2026-08-03T08:40:00Z",
                                  withdrawal_time_seconds=500, adenomas_detected=1)
        report = create_quality_report(drq["id"], "2026-08-03T00:00:00Z",
                                       "2026-08-03T23:59:59Z", "STRICT")
        assert report["adr_denominator"] == 1
        assert_rate(report["adenoma_detection_rate"], 100.0)
        # A second procedure completes AFTER the snapshot.
        run_procedure_to_complete(b2["id"], drq["id"], qs2["id"],
                                  "2026-08-03T09:00:00Z", "2026-08-03T09:40:00Z",
                                  withdrawal_time_seconds=600, adenomas_detected=0)
        after = validate_success(api.get_quality_report(report["id"], QO), 200)
        assert_quality_report(after)
        assert after["adr_denominator"] == 1, "immutable snapshot"
        assert_rate(after["adenoma_detection_rate"], 100.0)

    def test_quality_report_invalid_period_rejected(self, api):
        """PRD §3.9: "`period_start` must not fall after `period_end`
        (`ERR_INVALID_PERIOD`)."

        Design: Corner/validations/quality_report_invalid_period_rejected
        """
        provider = create_provider("Dr Ip")
        resp = api.create_quality_report(
            {"provider_id": provider["id"], "period_start": "2026-08-05T00:00:00Z",
             "period_end": "2026-08-04T00:00:00Z", "metric_variant": "STRICT"}, QO)
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD)

    def test_quality_report_not_found_returns_404(self, api):
        """
        PRD §2.6: "Each unresolved reference maps to its own error:
        `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` (also raised for an
        unresolvable `new_room_id`), `ERR_ANESTHESIA_PROVIDER_NOT_FOUND`,
        `ERR_SCOPE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SCOPE_USAGE_NOT_FOUND`,
        `ERR_REPROCESSING_CYCLE_NOT_FOUND`, `ERR_CULTURE_TEST_NOT_FOUND`,
        `ERR_QUARANTINE_CASE_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
        `ERR_QUALITY_REPORT_NOT_FOUND`, and `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND`,
        all HTTP 404."

        Design: Corner/errors/quality_report_not_found_returns_404
        """
        resp = api.get_quality_report(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_QUALITY_REPORT_NOT_FOUND)
