"""Guards taken one clause at a time: order, conditionality and inclusivity.

Each test isolates a single validation so that nothing else in the request can be
the reason it was refused, and then makes the very same request good.
"""

import pytest

from test_helpers import (
    ADJUDICATOR_1_ID,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_assessment,
    add_claim,
    add_sibling_vehicle,
    adjudicate,
    assert_module_statuses,
    assert_same_instant,
    assert_soh_assessment,
    assert_thermal_event,
    bench_assessment_payload,
    claim_payload,
    dispute_payload,
    file_dispute,
    fulfil_payload,
    list_claim_disputes,
    list_claims,
    list_modules,
    battery_pack_payload,
    campaign_payload,
    create_campaign,
    list_campaigns,
    list_packs,
    list_vehicles,
    read_assessment,
    make_technician_headers,
    read_claim,
    read_pack,
    read_technician,
    read_vehicle_version,
    set_clock,
    setup_adjudicated_claim_world,
    setup_base_world,
    setup_center,
    setup_pack,
    setup_program,
    setup_technician,
    setup_vehicle,
    telematics_assessment_payload,
    validate_error,
    vehicle_payload,
    validate_success,
)

# Three identical fresh rows: enough for a fleet window, and a fixed retention.
ADMIN_HEADERS = TEST_USERS["program_admin_headers"]

THREE_ROWS = [
    ("2026-07-20T00:00:00Z", 71000, 56.000),
    ("2026-07-22T00:00:00Z", 71200, 56.000),
    ("2026-07-24T00:00:00Z", 71400, 56.000),
]


class TestBodyForeignKeyResolutionOrder:
    """Four dangling references, resolved in the order the payload declares them."""

    def test_each_repaired_reference_uncovers_the_next_error_in_declaration_order(
        self, api
    ):
        """VEHICLE, then CENTER, then ASSESSMENT, then TECHNICIAN — never out of turn.

        PRD 2.7: "The same discipline applies to foreign keys supplied in a request
        body: they are resolved in the order their fields are declared on the owning
        entity, so the first unresolvable reference determines the error."

        PRD 3.4: "The payload names four things: the `vehicle_id`, the
        `service_center_id` of the center that will act as the center of record for both
        diagnosis and fulfilment, the `assessment_id` of the backing diagnostic, and the
        `diagnosing_technician_id` of the technician standing behind it."

        Design: Corner/validations/body_fk_resolution_walks_the_declared_field_order
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000401"},
            pack_overrides={"serial_number": "PK-C201"},
            snapshots=THREE_ROWS,
        )
        assessment = add_assessment(api, world, module_fault_positions=[3, 7])
        assert assessment["qualifies_for_claim"] is True

        # PRD 2.1 binds a ServiceTechnician's `X-User-ID` to the payload's
        # `diagnosing_technician_id` as a plain value comparison, so every probe below
        # acts as the (dangling) technician it names. That satisfies the identity
        # binding and leaves the body-foreign-key ladder as the only thing under test.
        dangling_tech_headers = make_technician_headers(NON_EXISTENT_UUID)

        # All four references dangle: only the leftmost declared one may be reported.
        validate_error(
            api.create_claim(
                claim_payload(
                    NON_EXISTENT_UUID,
                    NON_EXISTENT_UUID,
                    NON_EXISTENT_UUID,
                    NON_EXISTENT_UUID,
                ),
                dangling_tech_headers,
            ),
            ApiErrorId.ERR_VEHICLE_NOT_FOUND.value,
            expected_status=404,
        )

        validate_error(
            api.create_claim(
                claim_payload(
                    world["vehicle_id"],
                    NON_EXISTENT_UUID,
                    NON_EXISTENT_UUID,
                    NON_EXISTENT_UUID,
                ),
                dangling_tech_headers,
            ),
            ApiErrorId.ERR_CENTER_NOT_FOUND.value,
            expected_status=404,
        )

        validate_error(
            api.create_claim(
                claim_payload(
                    world["vehicle_id"],
                    world["center_id"],
                    NON_EXISTENT_UUID,
                    NON_EXISTENT_UUID,
                ),
                dangling_tech_headers,
            ),
            ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value,
            expected_status=404,
        )

        validate_error(
            api.create_claim(
                claim_payload(
                    world["vehicle_id"],
                    world["center_id"],
                    assessment["id"],
                    NON_EXISTENT_UUID,
                ),
                dangling_tech_headers,
            ),
            ApiErrorId.ERR_TECHNICIAN_NOT_FOUND.value,
            expected_status=404,
        )

        _, meta = list_claims(api, vehicle_id=world["vehicle_id"])
        assert meta["total_count"] == 0


class TestBenchCapacityIsConditionalBothWays:
    """Missing for a bench test and present for a fleet test fail identically."""

    def test_both_directions_are_refused_then_the_derated_ceiling_screens_the_figure(
        self, api
    ):
        """One error for two opposite mistakes, then 73.500 as the plausibility ceiling.

        PRD 3.3: "`BENCH_CAPACITY_TEST` uses a capacity the technician measured on a
        bench, supplied as `bench_measured_capacity_kwh`; that field is required for the
        bench variant and must be absent for the fleet variant, and either mistake is
        refused with `ERR_BENCH_CAPACITY_REQUIRED`."

        PRD 3.3: "Fourth, for the `BENCH_CAPACITY_TEST` variant only, a
        `bench_measured_capacity_kwh` greater than the variant's own denominator
        multiplied by 1.05 yields `BENCH_OUT_OF_RANGE`."

        PRD 3.3: "Count the pack's children in `FAULTED` *after* this assessment's
        `module_fault_positions` have been written, then take the pack's
        `nominal_capacity_kwh`, multiply it by the module count less that faulted count,
        divide by the module count, and round half up to three decimals."

        Design: Corner/validations/bench_capacity_field_is_conditionally_required_in_both_directions
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000411"},
            pack_overrides={"serial_number": "PK-C211"},
            snapshots=THREE_ROWS,
        )
        first_version = read_vehicle_version(
            api, world["vehicle_id"], world["technician_id"]
        )

        # A bench variant with no bench figure at all.
        missing = telematics_assessment_payload(
            world["vehicle_id"],
            world["pack_id"],
            world["technician_id"],
            first_version,
            variant="BENCH_CAPACITY_TEST",
            module_fault_positions=[3, 7],
        )
        validate_error(
            api.create_assessment(missing, world["tech_headers"]),
            ApiErrorId.ERR_BENCH_CAPACITY_REQUIRED.value,
            expected_status=400,
        )
        # A refused assessment writes no module statuses.
        assert_module_statuses(
            list_modules(api, world["pack_id"], limit=100)[0],
            {3: "HEALTHY", 7: "HEALTHY"},
        )

        # A fleet variant carrying a bench figure it must not have.
        surplus = telematics_assessment_payload(
            world["vehicle_id"],
            world["pack_id"],
            world["technician_id"],
            first_version,
            bench_measured_capacity_kwh=63.000,
        )
        validate_error(
            api.create_assessment(surplus, world["tech_headers"]),
            ApiErrorId.ERR_BENCH_CAPACITY_REQUIRED.value,
            expected_status=400,
        )

        out_of_range = validate_success(
            api.create_assessment(
                bench_assessment_payload(
                    world["vehicle_id"],
                    world["pack_id"],
                    world["technician_id"],
                    first_version,
                    90.000,
                    module_fault_positions=[3, 7],
                ),
                world["tech_headers"],
            ),
            expected_status=201,
        )
        assert_soh_assessment(out_of_range)
        # 80.000 * (16 - 2) / 16 == 70.000, and 70.000 * 1.05 == 73.500.
        assert out_of_range["nominal_basis_kwh"] == pytest.approx(70.000, abs=0.001)
        assert out_of_range["diagnostic_validity"] == "BENCH_OUT_OF_RANGE"
        assert out_of_range["retention_pct"] is None
        assert out_of_range["estimated_capacity_kwh"] is None
        assert out_of_range["qualifies_for_claim"] is False

        second_version = read_vehicle_version(
            api, world["vehicle_id"], world["technician_id"]
        )
        # Only the accepted write moved the vehicle; the two refusals did not.
        assert second_version == first_version + 1

        in_range = validate_success(
            api.create_assessment(
                bench_assessment_payload(
                    world["vehicle_id"],
                    world["pack_id"],
                    world["technician_id"],
                    second_version,
                    63.000,
                ),
                world["tech_headers"],
            ),
            expected_status=201,
        )
        # Modules 3 and 7 are still FAULTED, so the denominator is still derated.
        assert in_range["nominal_basis_kwh"] == pytest.approx(70.000, abs=0.001)
        assert in_range["diagnostic_validity"] == "VALID"
        assert in_range["estimated_capacity_kwh"] == pytest.approx(63.000, abs=0.001)
        assert in_range["retention_pct"] == pytest.approx(90.00, abs=0.01)


class TestClockAndDetectionInclusivity:
    """Two comparisons with opposite strictness, one instant apart."""

    def test_the_clock_may_be_reset_to_its_own_instant_but_detection_may_not_pass_it(
        self, api
    ):
        """A rewind is refused, an identical re-set is allowed, and one second ahead is not.

        PRD 2.2: "A `ProgramAdmin` may advance it to a supplied instant through an
        administrative test-driving capability; the clock never rewinds, and a request
        naming an instant earlier than the current one is refused with
        `ERR_CLOCK_REWIND_FORBIDDEN` (HTTP 409). Setting the clock to the instant it
        already holds is permitted."

        PRD 3.7: "The `detected_at` instant must be at or before the current logical
        clock, or the report is refused with `ERR_DETECTED_AT_IN_FUTURE`; an instant
        exactly equal to the clock is accepted."

        PRD 3.7: "An `S1` or `S2` report fires none of this: the pack stays `IN_SERVICE`,
        the vehicle stays `ACTIVE`, consents are untouched, and
        `affected_module_positions` records the implicated positions without changing any
        module's status or flag."

        Design: Corner/validations/clock_never_rewinds_and_a_future_detection_is_rejected
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000421"},
            pack_overrides={"serial_number": "PK-C221"},
            snapshots=None,
        )

        validate_success(
            api.set_clock("2026-08-05T00:00:00Z", world["admin_headers"])
        )

        # One second earlier is still earlier.
        validate_error(
            api.set_clock("2026-08-04T23:59:59Z", world["admin_headers"]),
            ApiErrorId.ERR_CLOCK_REWIND_FORBIDDEN.value,
            expected_status=409,
        )

        # The identical instant satisfies the inclusive comparison.
        validate_success(
            api.set_clock("2026-08-05T00:00:00Z", world["admin_headers"])
        )

        ahead = {
            "vehicle_id": world["vehicle_id"],
            "pack_id": world["pack_id"],
            "severity": "S2",
            "detected_at": "2026-08-05T00:00:01Z",
            "source": "TELEMATICS",
        }
        validate_error(
            api.create_thermal_event(ahead, world["gateway_headers"]),
            ApiErrorId.ERR_DETECTED_AT_IN_FUTURE.value,
            expected_status=400,
        )

        event = validate_success(
            api.create_thermal_event(
                dict(ahead, detected_at="2026-08-05T00:00:00Z"),
                world["gateway_headers"],
            ),
            expected_status=201,
        )
        assert_thermal_event(event)
        assert_same_instant(event["detected_at"], "2026-08-05T00:00:00Z", "detected_at")
        assert event["notification_status"] == "NOT_REQUIRED"
        assert event["notification_deadline_at"] is None
        assert read_pack(api, world["pack_id"])["status"] == "IN_SERVICE"


class TestDisputeWindowBoundaryDay:
    """Two identical claims, adjudicated together, disputed a day apart."""

    def test_thirty_days_after_adjudication_is_admissible_and_thirty_one_is_not(self, api):
        """Only the clock differs between the accepted filing and the refused one.

        PRD 3.9: "Finally the current logical clock must be at or before the claim's
        adjudication instant plus the program's `dispute_window_days` days, or the filing
        is refused with `ERR_DISPUTE_WINDOW_EXPIRED`; the boundary instant is inclusive,
        so a filing exactly thirty days after adjudication under the default window is
        accepted."

        PRD 3.9: "An accepted filing creates the dispute in `LAB_ASSIGNED` with
        `retest_count` 0, and snapshots two numbers from the claim's backing assessment:
        `nominal_basis_kwh`, which becomes the denominator for every later lab
        computation, and `retention_pct`, stored as `oem_retention_pct`... The filing also
        raises the claim's `version` by one."

        Design: Corner/validations/dispute_window_accepts_the_boundary_day_and_rejects_the_next
        """
        first = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000431"},
            pack_overrides={"serial_number": "PK-C231"},
            snapshots=THREE_ROWS,
        )
        second = add_sibling_vehicle(
            api,
            first,
            vin="5YJ3E1EA7KF000432",
            serial_number="PK-C232",
            snapshots=THREE_ROWS,
        )
        for world in (first, second):
            add_assessment(api, world, module_fault_positions=[3, 7])
            add_claim(api, world)
            adjudicate(api, world, "MODULE_REPLACEMENT", adjudicator_id=ADJUDICATOR_1_ID)
            assert world["claim"]["adjudication_status"] == "APPROVED_MODULE"
        version_before = read_claim(api, second["claim_id"])["version"]

        # Adjudication happened at 2026-08-01T00:00:00Z; this is that instant plus 30 days.
        set_clock(api, "2026-08-31T00:00:00Z")
        on_the_boundary = file_dispute(
            api,
            first,
            lab_name="Statewide Cell Lab",
            owner_statement="filed on the last admissible day",
        )
        assert on_the_boundary["dispute_status"] == "LAB_ASSIGNED"
        assert on_the_boundary["nominal_basis_kwh"] == pytest.approx(80.000, abs=0.001)
        assert on_the_boundary["oem_retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert on_the_boundary["retest_count"] == 0
        assert read_claim(api, first["claim_id"])["version"] == version_before + 1

        set_clock(api, "2026-09-01T00:00:00Z")
        validate_error(
            api.create_dispute(
                dispute_payload(
                    second["claim_id"],
                    version_before,
                    lab_name="Statewide Cell Lab",
                    owner_statement="filed one day late",
                ),
                second["owner_headers"],
            ),
            ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED.value,
            expected_status=409,
        )
        _, meta = list_claim_disputes(api, second["claim_id"])
        assert meta["total_count"] == 0
        assert read_claim(api, second["claim_id"])["version"] == version_before


class TestTechnicianBelongsToTheCenterOfRecord:
    """Both rows exist and the actor matches the body; only the relation is wrong."""

    def test_filing_at_another_center_is_a_relation_error_then_the_home_center_admits_it(
        self, api
    ):
        """422, not 404 — and the identical filing at the technician's own centre lands.

        PRD 3.4: "The acting `X-User-ID` must equal that `diagnosing_technician_id`, and
        that technician must belong to the named center — a mismatch is refused with
        `ERR_TECHNICIAN_CENTER_MISMATCH` — and must not be `CERT_LAPSED`."

        PRD 2.7: "38. Technician-to-center coherence on claim filing, fulfilment and
        shipment creation — `ERR_TECHNICIAN_CENTER_MISMATCH`."

        Design: Corner/validations/technician_from_another_center_is_a_cross_entity_mismatch
        """
        world = setup_base_world(
            api,
            center_overrides={"name": "East HV Center", "region_code": "US-EAST"},
            technician_overrides={"full_name": "Tech B"},
            vehicle_overrides={"vin": "5YJ3E1EA7KF000441"},
            pack_overrides={"serial_number": "PK-C241"},
            snapshots=THREE_ROWS,
        )
        # A second centre with no technicians of its own.
        west = setup_center(api, name="West HV Center")
        assessment = add_assessment(api, world, module_fault_positions=[3, 7])

        validate_error(
            api.create_claim(
                claim_payload(
                    world["vehicle_id"],
                    west["id"],
                    assessment["id"],
                    world["technician_id"],
                ),
                world["tech_headers"],
            ),
            ApiErrorId.ERR_TECHNICIAN_CENTER_MISMATCH.value,
            expected_status=422,
        )

        claim = validate_success(
            api.create_claim(
                claim_payload(
                    world["vehicle_id"],
                    world["center_id"],
                    assessment["id"],
                    world["technician_id"],
                ),
                world["tech_headers"],
            ),
            expected_status=201,
        )
        assert claim["service_center_id"] == world["center_id"]
        assert claim["adjudication_status"] == "SUBMITTED"
        assert claim["recommended_remedy"] == "MODULE_REPLACEMENT"

        _, meta = list_claims(api, vehicle_id=world["vehicle_id"])
        assert meta["total_count"] == 1


class TestSupersessionOutranksInvalidity:
    """One assessment that breaks two rules must answer with the earlier one."""

    def test_the_superseded_and_invalid_assessment_reports_supersession_only(self, api):
        """Two rungs race on assessment 1; assessment 2 proves the lower rung is live.

        PRD 3.4: "an assessment whose `superseded` flag is true is refused with
        `ERR_ASSESSMENT_SUPERSEDED`; one already cited by another claim that is not
        `CLOSED` is refused with `ERR_ASSESSMENT_ALREADY_CLAIMED`; and one whose
        `diagnostic_validity` is `STALE_TELEMETRY`, `INSUFFICIENT_DATA` or
        `BENCH_OUT_OF_RANGE` is refused with `ERR_DIAGNOSTIC_NOT_VALID`."

        PRD 3.3: "Third, for the `TELEMATICS_FLEET` variant only, a window holding fewer
        rows than `snapshot_min_count` yields `INSUFFICIENT_DATA`."

        PRD 3.3: "Finally, writing an assessment closes the book on the vehicle's earlier
        ones: every prior assessment on the same `vehicle_id` has `superseded` set to
        true, and a superseded assessment can no longer back a claim."

        Design: Corner/validations/supersession_check_runs_before_the_diagnostic_validity_check
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000451"},
            pack_overrides={"serial_number": "PK-C251"},
            snapshots=[
                ("2026-07-20T00:00:00Z", 71000, 56.000),
                ("2026-07-22T00:00:00Z", 71200, 56.000),
            ],
        )
        first = add_assessment(api, world)
        second = add_assessment(api, world)
        for assessment in (first, second):
            assert assessment["diagnostic_validity"] == "INSUFFICIENT_DATA"
            assert assessment["window_snapshot_count"] == 2
        assert read_assessment(api, first["id"])["superseded"] is True
        assert read_assessment(api, second["id"])["superseded"] is False

        # Assessment 1 is superseded *and* diagnostically invalid; supersession is earlier.
        validate_error(
            api.create_claim(
                claim_payload(
                    world["vehicle_id"],
                    world["center_id"],
                    first["id"],
                    world["technician_id"],
                ),
                world["tech_headers"],
            ),
            ApiErrorId.ERR_ASSESSMENT_SUPERSEDED.value,
            expected_status=409,
        )

        # Assessment 2 is invalid but current, so the later rung answers.
        validate_error(
            api.create_claim(
                claim_payload(
                    world["vehicle_id"],
                    world["center_id"],
                    second["id"],
                    world["technician_id"],
                ),
                world["tech_headers"],
            ),
            ApiErrorId.ERR_DIAGNOSTIC_NOT_VALID.value,
            expected_status=409,
        )

        _, meta = list_claims(api, vehicle_id=world["vehicle_id"])
        assert meta["total_count"] == 0


class TestNaturalKeyUniqueness:
    """Three natural keys, three dedicated codes, and no shadow rows.

    PRD 3.1: "Registering one requires a `vin` of exactly seventeen uppercase
    alphanumeric characters, unique across the whole fleet — a collision is refused
    with `ERR_DUPLICATE_VIN`"
    """

    def test_a_duplicate_vin_serial_and_campaign_code_each_answer_with_their_own_code(
        self, api
    ):
        """Each collision keeps its own identifier and creates nothing.

        PRD 3.1: "A pack needs a `serial_number` unique across the program, with a
        collision refused as `ERR_DUPLICATE_PACK_SERIAL`."

        PRD 3.8: "`campaign_code` must be unique across all campaigns, or the creation is
        refused with `ERR_DUPLICATE_CAMPAIGN_CODE`."

        Design: Corner/validations/uniqueness_guards_reject_duplicate_vin_serial_and_campaign_code
        """
        program = setup_program(api)
        vehicle = setup_vehicle(api, program["id"], vin="5YJ3E1EA7KF000461")
        pack = setup_pack(api, serial_number="PK-C261")
        campaign = create_campaign(
            api,
            campaign_code="CMP-DUP-01",
            target_defect="CHARGING",
            software_version="bms-4.2.1",
            applies_to_pack_type="ANY",
            applies_to_model_code="MX-90",
        )
        assert vehicle["vin"] == "5YJ3E1EA7KF000461"
        assert pack["status"] == "STOCK"
        assert campaign["status"] == "DRAFT"

        # The same VIN under a different in-service date is still the same VIN.
        validate_error(
            api.create_vehicle(
                vehicle_payload(
                    program["id"], vin="5YJ3E1EA7KF000461", in_service_date="2021-01-01"
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_VIN.value,
            expected_status=409,
        )

        validate_error(
            api.create_battery_pack(
                battery_pack_payload(serial_number="PK-C261", nominal_capacity_kwh=75.000),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_PACK_SERIAL.value,
            expected_status=409,
        )

        validate_error(
            api.create_campaign(
                campaign_payload(
                    campaign_code="CMP-DUP-01",
                    target_defect="THERMAL_MANAGEMENT",
                    software_version="bms-9.9.9",
                    applies_to_pack_type="NEW",
                    applies_to_model_code="MX-70",
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_CAMPAIGN_CODE.value,
            expected_status=409,
        )

        _, pack_meta = list_packs(api)
        assert pack_meta["total_count"] == 1
        _, vehicle_meta = list_vehicles(api)
        assert vehicle_meta["total_count"] == 1
        _, campaign_meta = list_campaigns(api)
        assert campaign_meta["total_count"] == 1


class TestOverdueInsulationTester:
    """An otherwise flawless centre still cannot open a pack."""

    def test_a_calibration_a_month_past_due_refuses_a_module_replacement(self, api):
        """ACTIVE, L3, free bay, current technician — and still refused on tooling.

        PRD 3.6: "For either hardware remedy the center's
        `insulation_tester_cal_due_at` must be strictly later than the current logical
        clock, or `ERR_INSULATION_TESTER_OVERDUE`; a calibration falling due exactly at
        the current instant is overdue and rejects."

        PRD 3.6: "A **module replacement** moves every module of the pack whose `status`
        is `FAULTED` to `REPLACED` and stamps each one's `replaced_at` with the current
        logical clock; because those rows changed status, the pack's
        `module_replacements_to_date` rises by the number of modules just replaced and its
        `faulted_module_count` is re-derived, which leaves it at zero."

        Design: Corner/validations/hardware_fulfilment_is_blocked_by_an_overdue_insulation_tester
        """
        world = setup_adjudicated_claim_world(
            api,
            center_overrides={
                "name": "West HV Center",
                "insulation_tester_cal_due_at": "2026-07-01T00:00:00Z",
            },
            vehicle_overrides={"vin": "5YJ3E1EA7KF000471"},
            pack_overrides={"serial_number": "PK-C271"},
        )
        assert world["center"]["status"] == "ACTIVE"
        assert world["center"]["hv_certification_level"] == "L3"
        assert world["claim"]["adjudication_status"] == "APPROVED_MODULE"

        validate_error(
            api.fulfil_claim(
                world["claim_id"],
                fulfil_payload(
                    world["technician_id"],
                    hv_bay_window_start="2026-08-01T10:00:00Z",
                    hv_bay_window_end="2026-08-01T14:00:00Z",
                ),
                world["tech_headers"],
            ),
            ApiErrorId.ERR_INSULATION_TESTER_OVERDUE.value,
            expected_status=409,
        )

        refused = read_claim(api, world["claim_id"])
        assert refused["adjudication_status"] == "APPROVED_MODULE"
        assert refused["fulfilment_technician_id"] is None
        assert refused["hv_bay_window_start"] is None
        assert refused["hv_bay_window_end"] is None
        assert refused["pack_shipment_required"] is False

        # Nothing was swapped, so the roster counters are exactly as adjudication left them.
        pack = read_pack(api, world["pack_id"])
        assert pack["faulted_module_count"] == 2
        assert pack["module_replacements_to_date"] == 0
        assert_module_statuses(
            list_modules(api, world["pack_id"], limit=100)[0],
            {3: "FAULTED", 7: "FAULTED"},
        )
        assert (
            read_technician(api, world["center_id"], world["technician_id"])[
                "last_hv_window_end_at"
            ]
            is None
        )


class TestLapsedTechnicianCannotFulfil:
    """Two technicians at one centre, differing only in their certificate date."""

    def test_the_lapsed_technician_is_refused_and_the_current_one_runs_the_cascade(
        self, api
    ):
        """CERT_LAPSED is derived from the clock, and the same call then succeeds.

        PRD 3.6: "The named technician's `cert_expires_at` must be strictly later than
        the current logical clock — equivalently, the technician's derived `status` must
        be `ACTIVE` and not `CERT_LAPSED` — or the request is refused with
        `ERR_TECHNICIAN_CERT_EXPIRED`."

        PRD 3.1: "Their `status` is derived rather than stored — `ACTIVE` while
        `cert_expires_at` remains later than the logical clock, `CERT_LAPSED` from that
        instant onward — and is re-evaluated on every read. Their
        `last_hv_window_end_at` starts null."

        PRD 3.6: "The technician's `last_hv_window_end_at` is raised to the later of its
        current value and the submitted `hv_bay_window_end`."

        Design: Corner/validations/fulfilment_rejects_a_lapsed_technician_then_accepts_a_current_one
        """
        world = setup_adjudicated_claim_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000481"},
            pack_overrides={"serial_number": "PK-C281"},
        )
        lapsed = setup_technician(
            api,
            world["center_id"],
            full_name="Tech B",
            cert_expires_at="2026-07-01T00:00:00Z",
        )
        assert read_technician(api, world["center_id"], lapsed["id"])["status"] == "CERT_LAPSED"
        assert (
            read_technician(api, world["center_id"], world["technician_id"])["status"]
            == "ACTIVE"
        )

        booking_window = ("2026-08-01T10:00:00Z", "2026-08-01T14:00:00Z")
        validate_error(
            api.fulfil_claim(
                world["claim_id"],
                fulfil_payload(lapsed["id"], *booking_window),
                make_technician_headers(lapsed["id"]),
            ),
            ApiErrorId.ERR_TECHNICIAN_CERT_EXPIRED.value,
            expected_status=409,
        )

        fulfilled = validate_success(
            api.fulfil_claim(
                world["claim_id"],
                fulfil_payload(world["technician_id"], *booking_window),
                world["tech_headers"],
            )
        )
        assert fulfilled["adjudication_status"] == "FULFILLED"
        assert fulfilled["fulfilment_technician_id"] == world["technician_id"]
        assert_same_instant(
            fulfilled["hv_bay_window_start"], "2026-08-01T10:00:00Z", "hv_bay_window_start"
        )
        assert fulfilled["pack_shipment_required"] is True

        modules, _ = list_modules(api, world["pack_id"], limit=100)
        replaced = [row for row in modules if row["status"] == "REPLACED"]
        assert len(replaced) == 2
        assert sorted(row["position_index"] for row in replaced) == [3, 7]
        for row in replaced:
            assert_same_instant(row["replaced_at"], "2026-08-01T00:00:00Z", "replaced_at")

        pack = read_pack(api, world["pack_id"])
        assert pack["faulted_module_count"] == 0
        assert pack["module_replacements_to_date"] == 2

        assert_same_instant(
            read_technician(api, world["center_id"], world["technician_id"])[
                "last_hv_window_end_at"
            ],
            "2026-08-01T14:00:00Z",
            "technician.last_hv_window_end_at",
        )
        assert (
            read_technician(api, world["center_id"], lapsed["id"])["last_hv_window_end_at"]
            is None
        )
