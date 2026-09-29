"""Formulae probed at their band edges, their filters and their tie-breaks.

Every number asserted here is derived from the published formula and the
reference constants, and each test isolates one variable so a single flipped
comparison changes exactly one figure.
"""

import pytest

from test_helpers import (
    ADJUDICATOR_1_ID,
    ADJUDICATOR_2_ID,
    ApiErrorId,
    add_assessment,
    adjudicate_payload,
    assert_lab_deviation,
    assert_pack_shipment,
    assert_packaging_requirement_follows_classification,
    assert_reman_stock,
    assert_same_instant,
    assert_settlement_waterfall,
    assert_soh_assessment,
    claim_payload,
    file_dispute,
    ingest_snapshot,
    list_claims,
    list_snapshots,
    make_adjudicator_headers,
    read_center,
    read_claim,
    read_pack,
    read_program,
    read_vehicle,
    record_lab_result,
    file_notification,
    report_thermal_event,
    resolve_dispute,
    setup_adjudicated_claim_world,
    setup_base_world,
    setup_center,
    setup_submitted_claim_world,
    shipment_payload,
    stock_reman_packs,
    tender_payload,
    validate_error,
    validate_success,
)

# One identical reported capacity at all four band edges, so only the coolant
# temperature can move the corrected figure.
BAND_EDGE_ROWS = [
    ("2026-07-20T00:00:00Z", 71000, -0.1, 59.360),
    ("2026-07-21T00:00:00Z", 71100, 0.0, 57.680),
    ("2026-07-22T00:00:00Z", 71200, 15.0, 56.000),
    ("2026-07-23T00:00:00Z", 71300, 35.0, 56.000),
    ("2026-07-24T00:00:00Z", 71400, 35.0001, 54.320),
]


class TestTemperatureCorrectionBands:
    """The step function is probed on every boundary it declares."""

    def test_one_capacity_at_five_temperatures_gives_five_corrected_figures(self, api):
        """56.000 kWh becomes 59.360, 57.680, 56.000, 56.000 and 54.320.

        PRD 3.2: "The correction is a step function on `coolant_temp_c` with exact
        boundaries: below 0.0 degrees the factor is 1.06, from 0.0 up to but not
        including 15.0 degrees it is 1.03, from 15.0 through 35.0 degrees inclusive it
        is 1.00, and above 35.0 degrees it is 0.97. A reading of exactly 0.0 therefore
        takes 1.03, exactly 15.0 takes 1.00, exactly 35.0 still takes 1.00, and
        anything even fractionally above 35.0 takes 0.97."

        PRD 3.3: "When the window holds exactly `snapshot_window_size` rows, the values
        are sorted ascending, the single lowest and the single highest are dropped, and
        the remainder are averaged."

        PRD 3.3: "`qualifies_for_claim` is true when `diagnostic_validity` is `VALID`,
        `coverage_position` is either `IN_COVERAGE` or `GOODWILL_BAND`, and
        `retention_pct` is at or below `applicable_min_retention_pct` — retention
        exactly at the threshold qualifies."

        Design: Corner/calculations/snapshot_correction_factor_at_every_temperature_band_edge
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000301"},
            pack_overrides={"serial_number": "PK-C101"},
            snapshots=None,
        )

        for captured_at, odometer, coolant_temp_c, expected in BAND_EDGE_ROWS:
            row = ingest_snapshot(
                api,
                world["vehicle_id"],
                captured_at,
                odometer,
                56.000,
                coolant_temp_c=coolant_temp_c,
            )
            assert row["validity_flag"] == "VALID"
            assert row["corrected_capacity_kwh"] == pytest.approx(expected, abs=0.001), (
                f"coolant {coolant_temp_c} must correct 56.000 to {expected}"
            )

        assessment = add_assessment(api, world)
        assert_soh_assessment(assessment)
        assert assessment["diagnostic_validity"] == "VALID"
        assert assessment["window_snapshot_count"] == 5
        # Only 54.320 and 59.360 are trimmed: (57.680 + 56.000 + 56.000) / 3.
        assert assessment["estimated_capacity_kwh"] == pytest.approx(56.560, abs=0.001)
        assert assessment["nominal_basis_kwh"] == pytest.approx(80.000, abs=0.001)
        assert assessment["retention_pct"] == pytest.approx(70.70, abs=0.01)
        assert assessment["coverage_position"] == "IN_COVERAGE"
        assert assessment["applicable_min_retention_pct"] == pytest.approx(70.00, abs=0.01)
        # 70.70 is strictly above the 70.00 promise, so nothing qualifies.
        assert assessment["qualifies_for_claim"] is False


class TestInvalidRowsNeverEnterTheWindow:
    """A stored invalid row is readable and inert."""

    def test_a_future_dated_row_is_kept_but_starves_the_window_of_its_third_reading(
        self, api
    ):
        """Two valid rows against a minimum of three: INSUFFICIENT_DATA.

        PRD 3.2: "A `captured_at` later than the current logical clock flags the row
        `INVALID_FUTURE_CAPTURE`."

        PRD 3.2: "The corrected figure is the reported capacity multiplied by that
        factor, rounded half up to three decimals, and it is written for every row
        including the invalid ones."

        PRD 3.2: "Invalid rows are stored and are readable — a vehicle's snapshot list
        may be filtered by `validity_flag` — but they never contribute to an odometer
        read, a cell-delta read, or any capacity estimate."

        PRD 3.3: "Third, for the `TELEMATICS_FLEET` variant only, a window holding
        fewer rows than `snapshot_min_count` yields `INSUFFICIENT_DATA`."

        PRD 3.3: "Both `estimated_capacity_kwh` and `retention_pct` are null whenever
        `diagnostic_validity` is anything other than `VALID`."

        PRD 3.4: "one whose `diagnostic_validity` is `STALE_TELEMETRY`,
        `INSUFFICIENT_DATA` or `BENCH_OUT_OF_RANGE` is refused with
        `ERR_DIAGNOSTIC_NOT_VALID`."

        Design: Corner/calculations/invalid_snapshots_are_excluded_and_starve_the_window
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000311"},
            pack_overrides={"serial_number": "PK-C111"},
            snapshots=None,
        )
        first = ingest_snapshot(
            api, world["vehicle_id"], "2026-07-20T00:00:00Z", 71000, 55.000
        )
        second = ingest_snapshot(
            api, world["vehicle_id"], "2026-07-22T00:00:00Z", 71200, 56.000
        )
        assert first["validity_flag"] == "VALID"
        assert second["validity_flag"] == "VALID"

        # Captured a day after the logical clock: stored, corrected, and excluded.
        future = ingest_snapshot(
            api, world["vehicle_id"], "2026-08-02T00:00:00Z", 99000, 57.000
        )
        assert future["validity_flag"] == "INVALID_FUTURE_CAPTURE"
        assert future["corrected_capacity_kwh"] == pytest.approx(57.000, abs=0.001)

        assert read_vehicle(api, world["vehicle_id"])["odometer_miles"] == 71200

        assessment = add_assessment(api, world)
        assert assessment["diagnostic_validity"] == "INSUFFICIENT_DATA"
        assert assessment["window_snapshot_count"] == 2
        assert assessment["assessed_odometer_miles"] == 71200
        assert assessment["max_cell_delta_mv"] == 40
        assert assessment["estimated_capacity_kwh"] is None
        assert assessment["retention_pct"] is None
        # PRD 3.3 nulls only `estimated_capacity_kwh` and `retention_pct` on a
        # non-VALID verdict; it nulls `applicable_min_retention_pct` only when
        # `coverage_position` reads `OUT_OF_COVERAGE`, so nothing is asserted here.
        assert assessment["qualifies_for_claim"] is False

        validate_error(
            api.create_claim(
                claim_payload(
                    world["vehicle_id"],
                    world["center_id"],
                    assessment["id"],
                    world["technician_id"],
                ),
                world["tech_headers"],
            ),
            ApiErrorId.ERR_DIAGNOSTIC_NOT_VALID.value,
            expected_status=409,
        )
        _, claim_meta = list_claims(api, vehicle_id=world["vehicle_id"])
        assert claim_meta["total_count"] == 0

        rows, snapshot_meta = list_snapshots(api, world["vehicle_id"], limit=100)
        assert snapshot_meta["total_count"] == 3
        assert future["id"] in [row["id"] for row in rows]


class TestFreshnessBoundaryRevivesTheWindow:
    """Staleness is a property of the window, never of the row."""

    def test_june_rows_are_stale_and_a_row_exactly_on_the_boundary_counts(self, api):
        """Three June rows yield STALE_TELEMETRY; a 2026-07-02 row makes it VALID.

        PRD 3.3: "Otherwise narrow to the fresh subset — those whose `captured_at`
        falls at or after the logical clock less `snapshot_freshness_days` days, with
        the lower bound inclusive so a snapshot captured exactly on the boundary
        instant still counts as fresh. Second, if the fresh subset is empty, the verdict
        is `STALE_TELEMETRY`: the vehicle has reported at some point, but not recently
        enough."

        PRD 3.3: "The window's size is recorded as `window_snapshot_count`, and the
        newest row in it supplies both `assessed_odometer_miles` and the assessment's
        own `max_cell_delta_mv`; both read 0 when the window is empty."

        PRD 3.3: "When the window is smaller than that — three or four rows — no
        trimming happens and all of the values are averaged."

        Design: Corner/calculations/stale_telemetry_then_freshness_boundary_row_revives_the_window
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000321"},
            pack_overrides={"serial_number": "PK-C121"},
            snapshots=None,
        )
        june_rows = [
            ingest_snapshot(api, world["vehicle_id"], captured_at, odometer, 56.000)
            for captured_at, odometer in (
                ("2026-06-25T00:00:00Z", 70000),
                ("2026-06-26T00:00:00Z", 70100),
                ("2026-06-27T00:00:00Z", 70200),
            )
        ]
        assert [row["validity_flag"] for row in june_rows] == ["VALID"] * 3

        # 2026-08-01 less thirty days is 2026-07-02, so every June row is outside.
        stale = add_assessment(api, world)
        assert stale["diagnostic_validity"] == "STALE_TELEMETRY"
        assert stale["window_snapshot_count"] == 0
        assert stale["assessed_odometer_miles"] == 0
        assert stale["max_cell_delta_mv"] == 0
        assert stale["retention_pct"] is None
        assert stale["estimated_capacity_kwh"] is None

        for captured_at, odometer in (
            ("2026-07-02T00:00:00Z", 70300),
            ("2026-07-03T00:00:00Z", 70400),
            ("2026-07-04T00:00:00Z", 70500),
        ):
            fresh_row = ingest_snapshot(
                api, world["vehicle_id"], captured_at, odometer, 56.000
            )
            assert fresh_row["validity_flag"] == "VALID"

        revived = add_assessment(api, world)
        assert revived["diagnostic_validity"] == "VALID"
        # The 2026-07-02T00:00:00Z row sits exactly on the inclusive lower bound.
        assert revived["window_snapshot_count"] == 3
        # A window below five rows is a plain mean with nothing trimmed.
        assert revived["estimated_capacity_kwh"] == pytest.approx(56.000, abs=0.001)
        assert revived["retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert revived["assessed_odometer_miles"] == 70500
        assert revived["qualifies_for_claim"] is True

        # The June rows never lost their validity; they simply aged out of the window.
        june_listing, _ = list_snapshots(
            api, world["vehicle_id"], validity_flag="VALID", limit=100
        )
        assert len(june_listing) == 6
        assert all(row["validity_flag"] == "VALID" for row in june_listing)


class TestGoodwillBandNeedsBothAxes:
    """One axis inside the band is not enough."""

    def test_a_car_inside_the_month_band_but_past_the_mileage_band_is_out_of_coverage(
        self, api
    ):
        """76 months against 96 + 12, but 116400 miles against 100000 + 15000.

        PRD 3.3: "When no row matches, the goodwill test runs: if `elapsed_months` is at
        or below `coverage_months` plus `goodwill_months` *and* `assessed_odometer_miles`
        is at or below `coverage_miles` plus `goodwill_miles` — both axes must be inside
        the band — then `coverage_position` reads `GOODWILL_BAND` and
        `applicable_min_retention_pct` takes the `min_retention_pct` of the schedule's
        last row. Failing that, `coverage_position` reads `OUT_OF_COVERAGE` and
        `applicable_min_retention_pct` is null."

        PRD 3.3: "`elapsed_months` is the whole number of months from the vehicle's
        `in_service_date` to the current logical clock, floored on the day of month."

        PRD 3.4: "an assessment whose `coverage_position` reads `OUT_OF_COVERAGE` is
        refused with `ERR_OUT_OF_COVERAGE`."

        Design: Corner/calculations/coverage_position_out_of_coverage_on_the_mileage_axis_blocks_the_claim
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000331"},
            pack_overrides={"serial_number": "PK-C131"},
            snapshots=[
                ("2026-07-20T00:00:00Z", 116000, 32.000),
                ("2026-07-22T00:00:00Z", 116100, 32.000),
                ("2026-07-24T00:00:00Z", 116200, 32.000),
                ("2026-07-26T00:00:00Z", 116300, 32.000),
                ("2026-07-28T00:00:00Z", 116400, 32.000),
            ],
        )

        assessment = add_assessment(api, world)
        assert assessment["diagnostic_validity"] == "VALID"
        # 2020-03-10 to 2026-08-01: 6 * 12 + 5 months, less one for the day of month.
        assert assessment["elapsed_months"] == 76
        assert assessment["assessed_odometer_miles"] == 116400
        # Capacity is catastrophically low, so only coverage can be refusing this claim.
        assert assessment["retention_pct"] == pytest.approx(40.00, abs=0.01)
        assert assessment["coverage_position"] == "OUT_OF_COVERAGE"
        assert assessment["applicable_min_retention_pct"] is None
        assert assessment["qualifies_for_claim"] is False

        validate_error(
            api.create_claim(
                claim_payload(
                    world["vehicle_id"],
                    world["center_id"],
                    assessment["id"],
                    world["technician_id"],
                ),
                world["tech_headers"],
            ),
            ApiErrorId.ERR_OUT_OF_COVERAGE.value,
            expected_status=409,
        )
        _, claim_meta = list_claims(api, vehicle_id=world["vehicle_id"])
        assert claim_meta["total_count"] == 0


class TestModulesOnlyDeclarationOfADamagedPack:
    """Damage classifies the box; the module roster weighs it."""

    def test_air_is_forbidden_and_the_ground_declaration_weighs_nothing(self, api):
        """UN3536 beats UN3481, and nought REPLACED modules make a 0.000 kg line.

        PRD 3.10: "`hazmat_classification` is `UN3536` whenever the pack's
        `damaged_defective` flag is true, whatever `shipment_contents` says. Only if the
        pack is undamaged does the contents decide: `UN3480` for a `FULL_PACK` shipment
        of batteries alone, `UN3481` for a `MODULES_ONLY` shipment. A `MODULES_ONLY`
        shipment of a damaged pack is therefore `UN3536`, not `UN3481`."

        PRD 3.10: "One safety rule bites at creation rather than at tender: air transport
        of a damaged pack is prohibited outright. If `hazmat_classification` is `UN3536`
        and `transport_mode` is `AIR`, the creation is refused with
        `ERR_AIR_TRANSPORT_FORBIDDEN`."

        PRD 3.10: "For a `MODULES_ONLY` shipment it is the pack's `gross_weight_kg`
        scaled by the number of that pack's modules whose `status` is `REPLACED` over the
        pack's `module_count`, rounded half up to three decimals — so the box's declared
        weight tracks how many modules actually came out."

        PRD 3.10: "And `state_of_charge_pct` must be at or below `soc_limit_pct`, or the
        tender is refused with `ERR_SOC_LIMIT_EXCEEDED`; the boundary value is accepted,
        so exactly 30.00 against a 30.00 limit passes."

        Design: Corner/calculations/modules_only_shipment_of_a_damaged_pack_is_un3536_with_a_zero_weight_line
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000341"},
            pack_overrides={"serial_number": "PK-C141"},
            snapshots=None,
        )
        report_thermal_event(
            api,
            world,
            severity="S3",
            detected_at="2026-07-31T00:00:00Z",
            affected_module_positions=[5],
        )
        damaged = read_pack(api, world["pack_id"])
        assert damaged["status"] == "QUARANTINED"
        assert damaged["damaged_defective"] is True
        assert damaged["hazmat_classification"] == "UN3536"
        assert damaged["module_count"] == 16
        assert damaged["gross_weight_kg"] == pytest.approx(483.296, abs=0.001)

        by_air = shipment_payload(
            world["pack_id"],
            world["center_id"],
            world["technician_id"],
            shipment_contents="MODULES_ONLY",
            packaging_spec="SP376_STRONG_OUTER",
            state_of_charge_pct=30.00,
            transport_mode="AIR",
        )
        validate_error(
            api.create_shipment(by_air, world["tech_headers"]),
            ApiErrorId.ERR_AIR_TRANSPORT_FORBIDDEN.value,
            expected_status=409,
        )

        shipment = validate_success(
            api.create_shipment(
                shipment_payload(
                    world["pack_id"],
                    world["center_id"],
                    world["technician_id"],
                    shipment_contents="MODULES_ONLY",
                    packaging_spec="SP376_STRONG_OUTER",
                    state_of_charge_pct=30.00,
                ),
                world["tech_headers"],
            ),
            expected_status=201,
        )
        assert_pack_shipment(shipment)
        # The pack's damage outranks the MODULES_ONLY contents that would say UN3481.
        assert shipment["hazmat_classification"] == "UN3536"
        assert_packaging_requirement_follows_classification(shipment)
        assert shipment["required_packaging_spec"] == "SP376_STRONG_OUTER"
        assert shipment["soc_limit_pct"] == pytest.approx(30.00, abs=0.01)
        # No module has reached REPLACED, so 483.296 * 0 / 16 rounds to 0.000.
        assert shipment["gross_weight_kg"] == pytest.approx(0.000, abs=0.001)
        assert shipment["hazmat_fee_cents"] == 0
        assert shipment["status"] == "DRAFT"
        assert shipment["tendered_at"] is None

        tendered = validate_success(
            api.tender_shipment(
                shipment["id"], tender_payload("CAR-0001"), world["tech_headers"]
            )
        )
        assert tendered["status"] == "TENDERED"
        assert_same_instant(
            tendered["tendered_at"], "2026-08-01T00:00:00Z", "tendered_at"
        )


class TestLateFilingPenaltyLandsOnOneCenter:
    """Forty points, one centre, and nothing else moves."""

    def test_a_filing_two_days_past_an_s4_deadline_scores_the_reporting_center_sixty(
        self, api
    ):
        """LATE_FILED costs the reporting centre 40 points; the sibling centre keeps 100.

        PRD 3.7: "A late filing sets `notification_status` to `LATE_FILED` and damages
        exactly one center: the one named by `reporting_service_center_id`, whose
        `late_notification_count` rises by one. That center's `compliance_score` is then
        recomputed from scratch as one hundred less fifteen for each rejected shipment
        less forty for each late notification, floored at zero, and if and only if the
        recomputed score is at or below twenty the center's `status` moves to
        `DECERTIFIED`... A single late filing at a center with no rejected shipments
        yields a score of sixty and does not decertify. No other center is touched — not
        the pack's origin center, not the center handling containment, only the reporting
        center."

        PRD 3.7: "`notification_deadline_at` is `detected_at` plus twenty-four hours for
        an `S4` and `detected_at` plus seventy-two hours for an `S3`"

        Design: Corner/calculations/late_regulatory_filing_applies_the_notification_weight_to_one_center
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000351"},
            pack_overrides={"serial_number": "PK-C151"},
            snapshots=None,
        )
        east = setup_center(api, name="East HV Center", region_code="US-EAST")

        event = report_thermal_event(
            api,
            world,
            severity="S4",
            detected_at="2026-07-29T00:00:00Z",
            affected_module_positions=[2, 3],
        )
        assert event["notification_status"] == "PENDING"
        assert_same_instant(
            event["notification_deadline_at"],
            "2026-07-30T00:00:00Z",
            "notification_deadline_at",
        )

        filed = file_notification(api, world, regulator_reference="REG-2026-0099")
        # The clock stands two days past the deadline, so the filing is strictly late.
        assert filed["notification_status"] == "LATE_FILED"
        assert_same_instant(
            filed["notification_filed_at"],
            "2026-08-01T00:00:00Z",
            "notification_filed_at",
        )
        assert filed["reporting_service_center_id"] == world["center_id"]

        reporting = read_center(api, world["center_id"])
        assert reporting["late_notification_count"] == 1
        assert reporting["rejected_shipment_count"] == 0
        # MAX(0, 100 - 15 * 0 - 40 * 1) == 60, which is above the decert threshold.
        assert reporting["compliance_score"] == 60
        assert reporting["status"] == "ACTIVE"

        untouched = read_center(api, east["id"])
        assert untouched["late_notification_count"] == 0
        assert untouched["rejected_shipment_count"] == 0
        assert untouched["compliance_score"] == 100
        assert untouched["status"] == "ACTIVE"

        # The S4 safety cascade is unaffected by how the regulatory dimension settled.
        vehicle = read_vehicle(api, world["vehicle_id"])
        assert vehicle["status"] == "IMMOBILIZED"
        assert vehicle["warranty_hold"] is True
        pack = read_pack(api, world["pack_id"])
        assert pack["status"] == "QUARANTINED"
        assert pack["hazmat_classification"] == "UN3536"


class TestLabDeviationExactlyAtTolerance:
    """Both dispute boundaries fall on the upheld side."""

    def test_a_plus_two_point_deviation_neither_retests_nor_disturbs_the_claim(self, api):
        """57.600 kWh against 80.000 is 72.00, exactly 2.00 above the OEM's 70.00.

        PRD 3.9: "If the absolute value of `deviation_pct` exceeds the program's
        `lab_tolerance_pct` *and* `retest_count` is still 0, the result is stored but the
        dispute does not advance... In every other case — the deviation is within
        tolerance, or `retest_count` is already 1 — the dispute moves to
        `LAB_RESULT_RECEIVED`."

        PRD 3.9: "A `deviation_pct` strictly below the negative of `lab_tolerance_pct`
        yields `RESOLVED_OVERTURNED`. A `deviation_pct` strictly above
        `lab_tolerance_pct` yields `RESOLVED_DOWNGRADED`. Everything in between,
        boundaries included, yields `RESOLVED_UPHELD` — so with the default tolerance of
        2.00 a deviation of exactly minus 2.00 or exactly plus 2.00 upholds the original
        decision, and only minus 2.01 or plus 2.01 disturbs it."

        PRD 3.9: "`RESOLVED_UPHELD` touches the claim not at all: no state change, no
        settlement change, no ledger movement."

        Design: Corner/calculations/lab_deviation_exactly_at_the_positive_tolerance_upholds_the_decision
        """
        world = setup_adjudicated_claim_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000361"},
            pack_overrides={"serial_number": "PK-C161"},
            adjudicator_id=ADJUDICATOR_1_ID,
        )
        assert world["claim"]["adjudication_status"] == "APPROVED_MODULE"
        assert world["claim"]["oem_total_cents"] == 370592

        dispute = file_dispute(
            api,
            world,
            lab_name="Statewide Cell Lab",
            owner_statement="capacity is worse than measured",
        )
        assert dispute["dispute_status"] == "LAB_ASSIGNED"
        assert dispute["nominal_basis_kwh"] == pytest.approx(80.000, abs=0.001)
        assert dispute["oem_retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert dispute["retest_count"] == 0

        result = record_lab_result(api, world, 57.600, lab_report_reference="LAB-0001")
        # 57.600 / 80.000 == 72.00 %, and 72.00 - 70.00 is exactly the tolerance.
        assert result["lab_retention_pct"] == pytest.approx(72.00, abs=0.01)
        assert result["deviation_pct"] == pytest.approx(2.00, abs=0.01)
        assert_lab_deviation(result)
        # ABS(2.00) does not exceed 2.00, so no mandatory retest is ordered.
        assert result["retest_count"] == 0
        assert result["dispute_status"] == "LAB_RESULT_RECEIVED"

        resolved = resolve_dispute(
            api,
            world,
            adjudicator_id=ADJUDICATOR_2_ID,
            resolution_note="OEM measurement stands",
        )
        assert resolved["dispute_status"] == "RESOLVED_UPHELD"
        assert resolved["resolved_by_user_id"] == ADJUDICATOR_2_ID

        untouched = read_claim(api, world["claim_id"])
        assert untouched["adjudication_status"] == "APPROVED_MODULE"
        assert untouched["approved_remedy"] == "MODULE_REPLACEMENT"
        assert untouched["oem_total_cents"] == 370592
        assert untouched["reopened_count"] == 0
        assert untouched["denial_reason"] is None
        assert read_program(api, world["program_id"])["accrued_liability_cents"] == 370592


class TestRemanSelectorRanking:
    """Three ineligible packs, then a tie broken by the refurbishment count."""

    def test_the_ninety_percent_pack_with_one_refurbishment_wins_over_its_twin(self, api):
        """84.99, US-EAST and twelve modules are all invisible; then 1 beats 2.

        PRD 3.5: "Its eligibility predicate is evaluated against the pack being removed
        and the claim's service center, and every clause must hold: the candidate's
        `pack_type` is `REMANUFACTURED`; its `status` is `STOCK`; its
        `installed_vehicle_id` is null; its `stock_region_code` equals the center's
        `region_code`; its `module_count` equals the removed pack's `module_count`; its
        `nominal_capacity_kwh` is at least the removed pack's `nominal_capacity_kwh`; and
        its `refurb_soh_pct` is at or above the program's `reman_min_soh_pct`, with the
        boundary value accepted."

        PRD 3.5: "Surviving candidates are ranked by `refurb_soh_pct` descending, then by
        `remanufacture_count` ascending, then by `created_at` ascending, and the first row
        is taken. Because `created_at` is the final key the order is total and ties are
        impossible."

        Design: Corner/calculations/reman_selector_ranks_by_soh_then_fewest_remanufactures_within_the_region
        """
        world = setup_submitted_claim_world(
            api,
            center_overrides={"name": "West HV Center", "has_pack_lift": True},
            vehicle_overrides={"vin": "5YJ3E1EA7KF000371"},
            pack_overrides={"serial_number": "PK-C171"},
        )
        assert world["program"]["reman_min_soh_pct"] == pytest.approx(85.00, abs=0.01)

        stock = stock_reman_packs(
            api,
            [
                # Below the inclusive 85.00 floor by a hundredth of a point.
                {"serial_number": "PK-R01", "refurb_soh_pct": 84.99, "remanufacture_count": 1},
                {"serial_number": "PK-R02", "refurb_soh_pct": 90.00, "remanufacture_count": 2},
                {"serial_number": "PK-R03", "refurb_soh_pct": 90.00, "remanufacture_count": 1},
                # Sits in the wrong region, however healthy it is.
                {
                    "serial_number": "PK-R04",
                    "refurb_soh_pct": 92.00,
                    "remanufacture_count": 0,
                    "stock_region_code": "US-EAST",
                },
                # Carries twelve modules against the removed pack's sixteen.
                {
                    "serial_number": "PK-R05",
                    "refurb_soh_pct": 95.00,
                    "remanufacture_count": 0,
                    "module_count": 12,
                },
            ],
        )
        by_serial = {pack["serial_number"]: pack for pack in stock}
        assert all(pack["status"] == "STOCK" for pack in stock)
        # The mirror counts remanufactured stock, eligible or not.
        assert_reman_stock(read_program(api, world["program_id"]), 5, "AVAILABLE")

        approved = validate_success(
            api.adjudicate_claim(
                world["claim_id"],
                adjudicate_payload(
                    "PACK_REPLACEMENT",
                    override_justification="owner requested full pack swap",
                ),
                make_adjudicator_headers(ADJUDICATOR_1_ID),
            )
        )
        assert approved["adjudication_status"] == "APPROVED_PACK"
        # Two survivors both read 90.00, so the refurbishment count decides.
        assert approved["replacement_pack_id"] == by_serial["PK-R03"]["id"]

        reserved = read_pack(api, by_serial["PK-R03"]["id"])
        assert reserved["status"] == "RESERVED"
        assert reserved["installed_vehicle_id"] is None
        for serial in ("PK-R01", "PK-R02", "PK-R04", "PK-R05"):
            assert read_pack(api, by_serial[serial]["id"])["status"] == "STOCK"

        # 890000 + 119165 + 19332 + 12000
        assert approved["remedy_cost_cents"] == 1040497
        assert approved["owner_share_cents"] == 0
        assert approved["oem_share_cents"] == 1040497
        assert approved["admin_fee_cents"] == 15000
        assert approved["oem_total_cents"] == 1055497
        assert_settlement_waterfall(approved)

        program = read_program(api, world["program_id"])
        assert_reman_stock(program, 4, "AVAILABLE")
        assert program["accrued_liability_cents"] == 1055497
