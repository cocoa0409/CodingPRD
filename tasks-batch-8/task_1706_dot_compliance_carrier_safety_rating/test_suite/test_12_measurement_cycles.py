"""The measurement epoch: time-weight boundaries, dual-variant measures,
percentile alerting, snapshot immutability, cycle summary counts, and the
logical clock."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_snapshot,
    get_coaching,
    get_document,
    get_premium_model,
    get_violation,
    list_snapshots,
    make_carrier,
    make_category,
    make_coaching,
    make_document,
    make_driver,
    make_inspection,
    make_quoted_model,
    make_violation,
    run_cycle,
    set_clock,
    setup_measure_dual_variant_case,
    setup_time_weight_six_month_case,
    validate_error,
    validate_success,
)


class TestDualVariantMeasure:
    def test_official_counts_challenged_provisional_excludes(
        self, api, analyst_headers
    ):
        """PRD §3.10: "the official variant includes violations in `ACTIVE` or
        `CHALLENGED` status, while the provisional variant counts only `ACTIVE`
        ones, and `REMOVED` violations are excluded from both." and "Each
        measure — points per power unit — is the resulting total divided by the
        carrier's `fleet_size`, rounded half-up to two decimal places, and is
        stored as `official_measure` or `provisional_measure`."

        Design: Difficulty/dual_variant_calc/category_measure_official_vs_provisional
        """
        env = setup_measure_dual_variant_case()
        run_cycle(env["carrier"]["id"])
        snap = list_snapshots(
            analyst_headers, carrier_id=env["carrier"]["id"],
            category_id=env["category"]["id"],
        )[0]
        # official: (24 + 12) / 10; provisional excludes the CHALLENGED sev-8.
        assert snap["official_measure"] == pytest.approx(3.60, abs=0.001)
        assert snap["provisional_measure"] == pytest.approx(1.20, abs=0.001)
        assert get_violation(env["v1"]["id"])["status"] == "CHALLENGED"

    def test_dual_variant_percentiles_and_alert_flags(self, api, analyst_headers):
        """PRD §3.10: "Each measure is then converted to a percentile: one
        hundred times the measure divided by the category's
        `benchmark_measure`, rounded down to a whole number, and capped at 100"
        and "A category is alerted when its percentile reaches the category's
        `intervention_threshold`, with equality alerting; the flags are stored
        as `alerted_official` and `alerted_provisional`."

        Design: Difficulty/dual_variant_calc/category_measure_official_vs_provisional
        """
        env = setup_measure_dual_variant_case()
        run_cycle(env["carrier"]["id"])
        snap = list_snapshots(
            analyst_headers, carrier_id=env["carrier"]["id"],
            category_id=env["category"]["id"],
        )[0]
        # floor(3.60 / 12.0 x 100) = 30; floor(1.20 / 12.0 x 100) = 10.
        assert snap["official_percentile"] == 30
        assert snap["provisional_percentile"] == 10
        # Both below the intervention threshold of 65.
        assert snap["alerted_official"] is False
        assert snap["alerted_provisional"] is False


class TestTimeWeightBoundaries:
    def test_time_weight_six_month_inclusive_boundary(self, api, analyst_headers):
        """PRD §3.3: "Multiplier 3 applies when the violation occurred no more
        than six calendar months before the current instant — a violation
        exactly six months old is included, as is one occurring exactly at the
        current instant. Multiplier 2 applies when it occurred more than six but
        no more than twelve months ago, with exactly twelve months old
        included."

        Design: Difficulty/boundary_precision_check/time_weight_six_month_inclusive_boundary
        """
        env = setup_time_weight_six_month_case()
        run_cycle(env["carrier"]["id"])

        va = get_violation(env["va"]["id"])
        assert va["time_weight_multiplier"] == 3, "occurred exactly as_of - 6mo"
        assert va["weighted_points"] == 15

        vb = get_violation(env["vb"]["id"])
        assert vb["time_weight_multiplier"] == 2, "one day older than 6 months"
        assert vb["weighted_points"] == 10

    def test_time_weight_six_month_snapshot_measure(self, api, analyst_headers):
        """PRD §3.10: "Each measure — points per power unit — is the resulting
        total divided by the carrier's `fleet_size`, rounded half-up to two
        decimal places" and "Each measure is then converted to a percentile: one
        hundred times the measure divided by the category's `benchmark_measure`,
        rounded down to a whole number, and capped at 100".

        Design: Difficulty/boundary_precision_check/time_weight_six_month_inclusive_boundary
        """
        env = setup_time_weight_six_month_case()
        run_cycle(env["carrier"]["id"])
        snap = list_snapshots(
            analyst_headers, carrier_id=env["carrier"]["id"],
            category_id=env["category"]["id"],
        )[0]
        # (15 + 10) / 5 = 5.00; floor(5.00 / 10.0 x 100) = 50.
        assert snap["official_measure"] == pytest.approx(5.00, abs=0.001)
        assert snap["official_percentile"] == 50

    def test_time_weight_12_24_month_boundaries(self, api, analyst_headers):
        """PRD §3.3: "Multiplier 2 applies when it occurred more than six but no
        more than twelve months ago, with exactly twelve months old included.
        Multiplier 1 applies when it occurred more than twelve but no more than
        twenty-four months ago, with exactly twenty-four months old included.
        Anything strictly older than twenty-four months takes multiplier 0 and
        drops out of every measure and every risk score."

        Design: Corner/calculations/time_weight_12_24_month_boundaries
        """
        carrier = make_carrier(dot_number="DOT-2201", fleet_size=5)
        category = make_category(
            category_code="UNSAFE_DRIVING", display_name="UD"
        )
        driver = make_driver(carrier["id"], hire_date="2024-01-01T00:00:00Z")
        inspection = make_inspection(
            carrier["id"], driver["id"], report_number="R-2201",
            inspection_date="2024-07-31T00:00:00Z", inspection_level=2, state_code="MN",
        )
        va = make_violation(
            inspection["id"], category["id"], violation_code="A",
            severity_weight=5, occurred_at="2025-08-01T00:00:00Z",
        )
        vb = make_violation(
            inspection["id"], category["id"], violation_code="B",
            severity_weight=5, occurred_at="2024-08-01T00:00:00Z",
        )
        vc = make_violation(
            inspection["id"], category["id"], violation_code="C",
            severity_weight=5, occurred_at="2024-07-31T00:00:00Z",
        )
        run_cycle(carrier["id"])

        assert get_violation(va["id"])["time_weight_multiplier"] == 2
        assert get_violation(va["id"])["weighted_points"] == 10
        assert get_violation(vb["id"])["time_weight_multiplier"] == 1
        assert get_violation(vb["id"])["weighted_points"] == 5
        assert get_violation(vc["id"])["time_weight_multiplier"] == 0
        assert get_violation(vc["id"])["weighted_points"] == 0

        snap = list_snapshots(
            analyst_headers, carrier_id=carrier["id"], category_id=category["id"]
        )[0]
        # (10 + 5 + 0) / 5 = 3.00; floor(3.00 / 10.0 x 100) = 30.
        assert snap["official_measure"] == pytest.approx(3.00, abs=0.001)
        assert snap["official_percentile"] == 30


class TestPercentileAlerting:
    def test_percentile_equality_alert_threshold(self, api, analyst_headers):
        """PRD §3.10: "A category is alerted when its percentile reaches the
        category's `intervention_threshold`, with equality alerting".

        Design: Corner/calculations/percentile_equality_alert_threshold
        """
        carrier = make_carrier(dot_number="DOT-2204", fleet_size=4)
        cat_vm = make_category(
            category_code="VEHICLE_MAINTENANCE", display_name="VM"
        )
        cat_hm = make_category(category_code="HAZMAT", display_name="HM")
        driver = make_driver(carrier["id"], hire_date="2024-01-01T00:00:00Z")
        inspection = make_inspection(
            carrier["id"], driver["id"], report_number="R-2204",
            inspection_date="2024-10-01T00:00:00Z", inspection_level=2, state_code="NE",
        )
        # VM: 24 (tw3) + 2 (tw1) = 26 points.
        make_violation(
            inspection["id"], cat_vm["id"], violation_code="V1", severity_weight=8,
            occurred_at="2026-05-01T00:00:00Z",
        )
        make_violation(
            inspection["id"], cat_vm["id"], violation_code="V2", severity_weight=2,
            occurred_at="2024-10-01T00:00:00Z",
        )
        # HM: 24 (tw3) + 1 (tw1) = 25 points.
        make_violation(
            inspection["id"], cat_hm["id"], violation_code="H1", severity_weight=8,
            occurred_at="2026-05-01T00:00:00Z",
        )
        make_violation(
            inspection["id"], cat_hm["id"], violation_code="H2", severity_weight=1,
            occurred_at="2024-10-01T00:00:00Z",
        )
        run_cycle(carrier["id"])

        vm = list_snapshots(
            analyst_headers, carrier_id=carrier["id"], category_id=cat_vm["id"]
        )[0]
        # 26 / 4 = 6.50 -> floor(6.50 / 10.0 x 100) = 65 == threshold.
        assert vm["official_measure"] == pytest.approx(6.50, abs=0.001)
        assert vm["official_percentile"] == 65
        assert vm["alerted_official"] is True

        hm = list_snapshots(
            analyst_headers, carrier_id=carrier["id"], category_id=cat_hm["id"]
        )[0]
        # 25 / 4 = 6.25 -> floor(6.25 / 10.0 x 100) = 62 < threshold.
        assert hm["official_measure"] == pytest.approx(6.25, abs=0.001)
        assert hm["official_percentile"] == 62
        assert hm["alerted_official"] is False


class TestCycleExecution:
    def test_cycle_output_summary_counts(self, api, analyst_headers, manager_headers):
        """PRD §3.10: "The cycle responds with a summary object carrying
        `cycle_date`, `carrier_id`, `snapshots_created`,
        `overdue_coaching_marked`, `documents_marked_purge_eligible`,
        `premiums_marked_stale`, `posture_before`, and `posture_after`." and "it
        emits one measurement snapshot per category for the carrier". The
        posture ladder is quoted in full at §3.10: "(3) otherwise, if exactly
        one category carries `alerted_official`, the posture is
        `INTERVENTION_WATCH`".

        Design: Corner/endpoints/cycle_output_summary_counts
        """
        carrier = make_carrier(dot_number="DOT-2402", fleet_size=1)
        cat_ud = make_category(category_code="UNSAFE_DRIVING", display_name="UD")
        cat_hm = make_category(category_code="HAZMAT", display_name="HM")
        driver = make_driver(carrier["id"], cdl_number="CDL-2402")
        inspection = make_inspection(
            carrier["id"], driver["id"], report_number="R-2402",
            inspection_level=2, state_code="OK",
        )
        make_violation(
            inspection["id"], cat_ud["id"], violation_code="392.2", severity_weight=5
        )
        coaching = make_coaching(
            driver["id"], coaching_type="TRAINING_COURSE",
            due_date="2026-07-01T00:00:00Z",
        )
        document = make_document(
            carrier["id"], document_type="INSPECTION_REPORT",
            filed_at="2025-06-01T00:00:00Z",
        )
        model = make_quoted_model(carrier["id"], base_rate_cents_per_unit=80000)

        cycle = run_cycle(carrier["id"])
        assert cycle["snapshots_created"] == 2, "one snapshot per category"
        assert cycle["overdue_coaching_marked"] == 1
        assert cycle["documents_marked_purge_eligible"] == 1
        assert cycle["premiums_marked_stale"] == 1
        assert cycle["posture_before"] == "NORMAL"
        assert cycle["posture_after"] == "INTERVENTION_WATCH", (
            "UD alerts (15.00 -> percentile 100 >= 65); HAZMAT has no violations"
        )

        assert get_coaching(coaching["id"])["status"] == "OVERDUE"
        assert get_document(document["id"])["status"] == "PURGE_ELIGIBLE"
        assert get_premium_model(model["id"])["status"] == "STALE"

    def test_cycle_twice_same_day_rejected(self, api, analyst_headers):
        """PRD §3.10: "At most one cycle may run per carrier per UTC calendar
        date; a second run on the same date is rejected with
        `ERR_CYCLE_ALREADY_RUN_TODAY`."

        Design: Corner/validations/cycle_twice_same_day_rejected
        """
        carrier_a = make_carrier(dot_number="DOT-2312A", fleet_size=1)
        carrier_b = make_carrier(dot_number="DOT-2312B", fleet_size=1)
        run_cycle(carrier_a["id"])

        again = api.run_measurement_cycle({"carrier_id": carrier_a["id"]}, analyst_headers)
        validate_error(again, ApiErrorId.ERR_CYCLE_ALREADY_RUN_TODAY)

        other = validate_success(
            api.run_measurement_cycle({"carrier_id": carrier_b["id"]}, analyst_headers),
            201,
        )
        assert str(other["cycle_date"]).startswith("2026-08-01")

    def test_clock_default_value_used_by_cycle(self, api, analyst_headers):
        """PRD §2.5: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its
        own."
        PRD §3.10: "Each **measurement snapshot** records the snapshot's
        `carrier_id` and `category_id`, the `cycle_date` (the UTC calendar date
        of the producing cycle), and the `as_of` logical-clock instant the cycle
        computed against."

        Design: Corner/endpoints/clock_default_value_used_by_cycle
        """
        carrier = make_carrier(dot_number="DOT-2403", fleet_size=1)
        category = make_category(category_code="UNSAFE_DRIVING", display_name="UD")

        cycle = run_cycle(carrier["id"])
        assert str(cycle["cycle_date"]).startswith("2026-08-01")

        snap = list_snapshots(
            analyst_headers, carrier_id=carrier["id"], category_id=category["id"]
        )[0]
        assert str(snap["as_of"]).startswith("2026-08-01T00:00:00")
        assert snap["official_measure"] == 0
        assert snap["official_percentile"] == 0

    def test_snapshot_immutable_shape(self, api, analyst_headers):
        """PRD §2.4: "A measurement snapshot is an immutable epoch artifact: it
        carries `id` and `created_at` only, and both `updated_at` and `version`
        are absent from it."

        Design: Corner/entities/snapshot_immutable_shape
        """
        carrier = make_carrier(dot_number="DOT-2007")
        category = make_category(category_code="DRIVER_FITNESS", display_name="Driver Fitness")
        driver = make_driver(carrier["id"], cdl_number="CDL-2007")
        inspection = make_inspection(carrier["id"], driver["id"], state_code="UT")
        make_violation(
            inspection["id"], category["id"], violation_code="391.11", severity_weight=4
        )
        run_cycle(carrier["id"])

        snap = list_snapshots(
            analyst_headers, carrier_id=carrier["id"], category_id=category["id"]
        )[0]
        assert_snapshot(snap)
        assert str(snap["cycle_date"]).startswith("2026-08-01")
        assert str(snap["as_of"]).startswith("2026-08-01T00:00:00")

    def test_clock_regression_rejected(self, api, admin_headers):
        """PRD §2.5: "The clock moves strictly forward: a `to_iso8601` equal to
        or earlier than the current logical clock is rejected with
        `ERR_CLOCK_REGRESSION` (HTTP 409)."

        Design: Corner/validations/clock_regression_rejected
        """
        set_clock("2026-08-03T00:00:00Z")

        backward = api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, admin_headers)
        validate_error(backward, ApiErrorId.ERR_CLOCK_REGRESSION)

        equal = api.set_clock({"to_iso8601": "2026-08-03T00:00:00Z"}, admin_headers)
        validate_error(equal, ApiErrorId.ERR_CLOCK_REGRESSION)
