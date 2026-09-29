"""Test envelopes and the two opposite interval conventions.

The minimum hold is banded on bore with the upper edge belonging to the lower band. Two
different exclusive resources then use deliberately opposite interval semantics: a test
bench is held over a half-open interval, so touching bookings are fine, while a foundry
qualification window is closed, so touching windows collide.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    CertStatus,
    ErrorId,
    QualificationStatus,
    assert_created,
    assert_unit_dimensions,
    factories,
    fixtures,
    make_quality_manager_headers,
    make_test_technician_headers,
)


def _record_response(
    api,
    unit_id,
    test_type,
    *,
    test_bench_code,
    started_at,
    ended_at,
    test_pressure_bar,
    hold_seconds,
    technician_user_id,
):
    return api.create_test_record(
        unit_id,
        factories.test_record_payload(
            test_type,
            test_bench_code,
            started_at,
            ended_at,
            test_pressure_bar,
            hold_seconds,
            "PASS",
        ),
        make_test_technician_headers(technician_user_id),
    )


# ─── The bore band's upper edge ───


def _bore_150_unit(api):
    """A class-300 body of exactly 150 millimetres bore — the upper edge of the
    60-second hold band — assembled and ready to test."""
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-11",
        foundry_name="Lambda Castings",
        country_code="IN",
        heat_number="H-1101",
        mtr_document_ref="MTR-1101",
        qty_received_kg=600.000,
        model_code="BV-300-B150",
        bore_size_mm=150,
        base_break_torque_nm=500.0,
        net_weight_kg=180.000,
        license_code="MON-11",
        scope_valve_types=["BALL"],
        grant_license=False,
    )
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-B150-1",
    )
    fixtures.advance_to_assembled(api, unit["id"], technician_user_id="tech-3")
    return {"line": line, "unit": unit}


def test_01_a_bore_of_exactly_one_hundred_fifty_holds_for_sixty_seconds(api):
    """The upper edge of a band belongs to that band, so a 150 millimetre bore takes the
    60-second minimum and not the 120-second one of the band above.

    PRD §3.4: "a bore of 50 millimetres or less holds for 15 seconds, a bore above 50 up to
    and including 150 holds for 60 seconds, a bore above 150 up to and including 300 holds
    for 120 seconds, and a bore above 300 holds for 300 seconds — five minutes for the
    largest bodies. Each band's upper edge belongs to that band, so a bore of exactly 150
    holds 60 seconds and a bore of 151 holds 120." PRD §3.4: "A shell test must reach 1.5
    times that rated pressure".

    Design: Difficulty/boundary_precision_check/test_hold_seconds_exact_minimum_at_bore_band_upper_edge
    """
    scenario = _bore_150_unit(api)

    record = assert_created(
        _record_response(
            api,
            scenario["unit"]["id"],
            "SHELL",
            test_bench_code="BENCH-5",
            started_at="2026-08-01T08:00:00Z",
            ended_at="2026-08-01T09:00:00Z",
            test_pressure_bar=80.0,
            hold_seconds=60,
            technician_user_id="tech-3",
        )
    )

    assert record["required_hold_seconds"] == 60
    assert record["required_hold_seconds"] != 120, (
        "A 150 millimetre bore is the upper edge of the 60-second band, not the band above"
    )
    # Class 300 is rated 51.1 bar; a shell test reaches 1.5 times that, rounded to 76.7.
    assert float(record["required_pressure_bar"]) == 76.7


def test_02_one_second_under_the_minimum_hold_is_refused(api):
    """The hold minimum is inclusive, so 60 seconds passes and 59 does not.

    PRD §3.4: "one whose `hold_seconds` falls below the computed `required_hold_seconds` is
    refused with `ERR_TEST_HOLD_TIME_SHORT`. Both boundaries are inclusive: meeting the
    minimum exactly is a pass." PRD §3.4: "Writing the first record moves `cert_status` from
    `UNCERTIFIED`, `TESTS_FAILED` or `DECERTIFIED` to `TESTS_IN_PROGRESS`."

    Design: Difficulty/boundary_precision_check/test_hold_seconds_exact_minimum_at_bore_band_upper_edge
    """
    scenario = _bore_150_unit(api)
    assert_created(
        _record_response(
            api,
            scenario["unit"]["id"],
            "SHELL",
            test_bench_code="BENCH-5",
            started_at="2026-08-01T08:00:00Z",
            ended_at="2026-08-01T09:00:00Z",
            test_pressure_bar=80.0,
            hold_seconds=60,
            technician_user_id="tech-3",
        )
    )

    response = _record_response(
        api,
        scenario["unit"]["id"],
        "SEAT",
        test_bench_code="BENCH-5",
        started_at="2026-08-01T09:00:00Z",
        ended_at="2026-08-01T10:00:00Z",
        test_pressure_bar=60.0,
        hold_seconds=59,
        technician_user_id="tech-3",
    )

    validate_error(response, ErrorId.TEST_HOLD_TIME_SHORT, 422)
    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    assert_unit_dimensions(unit, cert_status=CertStatus.TESTS_IN_PROGRESS)


# ─── A test bench is held over a half-open interval ───


def _bench_7_occupied_until_nine(api):
    """An assembled unit whose shell test has BENCH-7 from 08:00 to 09:00."""
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-14",
        foundry_name="Xi Castings",
        country_code="IN",
        heat_number="H-1401",
        mtr_document_ref="MTR-1401",
        model_code="BV-300-BENCH",
        license_code="MON-14",
        scope_valve_types=["BALL"],
        lead_auditor_user_id="aud-5",
        grant_license=False,
    )
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-BENCH-1",
    )
    fixtures.advance_to_assembled(api, unit["id"], technician_user_id="tech-5")
    fixtures.record_test(
        api,
        unit["id"],
        "SHELL",
        test_bench_code="BENCH-7",
        started_at="2026-08-01T08:00:00Z",
        ended_at="2026-08-01T09:00:00Z",
        test_pressure_bar=80.0,
        hold_seconds=60,
        technician_user_id="tech-5",
    )
    return {"line": line, "unit": unit}


def test_03_a_booking_starting_when_the_previous_one_ends_is_accepted(api):
    """The bench is released at the instant a run ends, so the next run may start there.

    PRD §3.4: "A new record on the same `test_bench_code` is refused with
    `ERR_TEST_BENCH_OCCUPIED` when its interval overlaps an existing record's interval on
    that bench; intervals that merely touch, where the new record's `started_at` equals an
    existing record's `ended_at`, are accepted."

    Design: Difficulty/resource_temporal_overlap/test_bench_half_open_intervals_permit_touching_endpoints
    """
    scenario = _bench_7_occupied_until_nine(api)

    record = assert_created(
        _record_response(
            api,
            scenario["unit"]["id"],
            "SEAT",
            test_bench_code="BENCH-7",
            started_at="2026-08-01T09:00:00Z",
            ended_at="2026-08-01T10:00:00Z",
            test_pressure_bar=60.0,
            hold_seconds=60,
            technician_user_id="tech-5",
        )
    )

    assert record["test_bench_code"] == "BENCH-7"
    assert record["started_at"].startswith("2026-08-01T09:00:00")
    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    assert_unit_dimensions(unit, cert_status=CertStatus.TESTS_PASSED)


def test_04_a_booking_straddling_the_middle_of_an_existing_run_is_refused(api):
    """Touching is not overlapping: a run starting half an hour into the 09:00-to-10:00
    slot genuinely overlaps it and the bench is reported occupied.

    PRD §3.4: "A new record on the same `test_bench_code` is refused with
    `ERR_TEST_BENCH_OCCUPIED` when its interval overlaps an existing record's interval on
    that bench". PRD §3.4: "Contrast this deliberately with the closed intervals used for
    foundry qualification windows in §3.2, where touching endpoints do collide."

    Design: Difficulty/resource_temporal_overlap/test_bench_half_open_intervals_permit_touching_endpoints
    """
    scenario = _bench_7_occupied_until_nine(api)
    assert_created(
        _record_response(
            api,
            scenario["unit"]["id"],
            "SEAT",
            test_bench_code="BENCH-7",
            started_at="2026-08-01T09:00:00Z",
            ended_at="2026-08-01T10:00:00Z",
            test_pressure_bar=60.0,
            hold_seconds=60,
            technician_user_id="tech-5",
        )
    )

    response = _record_response(
        api,
        scenario["unit"]["id"],
        "SEAT",
        test_bench_code="BENCH-7",
        started_at="2026-08-01T09:30:00Z",
        ended_at="2026-08-01T10:30:00Z",
        test_pressure_bar=60.0,
        hold_seconds=60,
        technician_user_id="tech-5",
    )

    validate_error(response, ErrorId.TEST_BENCH_OCCUPIED, 409)
    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    assert_unit_dimensions(unit, cert_status=CertStatus.TESTS_PASSED)


# ─── A qualification window is a closed interval ───


def _works_qualified_through_the_year(api):
    """A works holding one CASTING/CF8M qualification granted for the whole of 2026."""
    works = fixtures.create_qualified_foundry(
        api,
        foundry_code="FDY-15",
        name="Omicron Castings",
        country_code="IN",
        process="CASTING",
        material_grade="CF8M",
        max_pressure_class=600,
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2026-12-31T00:00:00Z",
    )
    return works


def _qualify_response(api, qualification_id):
    return api.foundry_qualification_action(
        qualification_id,
        factories.qualification_action_payload("QUALIFY"),
        make_quality_manager_headers(),
    )


def test_05_a_window_beginning_on_the_incumbent_s_last_day_collides(api):
    """Both endpoints are inside a qualification window, so a successor starting on the
    incumbent's final day intersects it — the opposite of the bench convention.

    PRD §3.1: "it requires window exclusivity: no other qualification for the same
    `foundry_id`, `process` and `material_grade` in either `PENDING` or `QUALIFIED` status
    may have a closed window intersecting this one." PRD §3.4: "Contrast this deliberately
    with the closed intervals used for foundry qualification windows in §3.2, where touching
    endpoints do collide."

    Design: Difficulty/resource_temporal_overlap/qualification_closed_windows_collide_on_touching_endpoints
    """
    works = _works_qualified_through_the_year(api)
    successor = fixtures.create_qualification(
        api,
        works["foundry"]["id"],
        process="CASTING",
        material_grade="CF8M",
        max_pressure_class=600,
        valid_from="2026-12-31T00:00:00Z",
        valid_until="2027-06-30T00:00:00Z",
    )
    assert successor["status"] == QualificationStatus.PENDING

    response = _qualify_response(api, successor["id"])

    validate_error(response, ErrorId.QUALIFICATION_WINDOW_OVERLAP, 409)
    unchanged = fixtures.read_qualification(api, successor["id"])
    incumbent = fixtures.read_qualification(api, works["qualification"]["id"])
    assert unchanged["status"] == QualificationStatus.PENDING
    assert unchanged["qualified_by_user_id"] is None
    assert incumbent["status"] == QualificationStatus.QUALIFIED


def test_06_a_window_beginning_the_day_after_is_accepted(api):
    """One day clear of the incumbent's last day and the windows no longer intersect, so
    the successor is granted.

    PRD §3.1: "it requires window exclusivity: no other qualification for the same
    `foundry_id`, `process` and `material_grade` in either `PENDING` or `QUALIFIED` status
    may have a closed window intersecting this one." PRD §3.1: "Granting writes
    `qualified_by_user_id` from `X-User-ID` and triggers recomputation of the foundry's
    `quality_index` and `status`."

    Design: Difficulty/resource_temporal_overlap/qualification_closed_windows_collide_on_touching_endpoints
    """
    works = _works_qualified_through_the_year(api)
    successor = fixtures.create_qualification(
        api,
        works["foundry"]["id"],
        process="CASTING",
        material_grade="CF8M",
        max_pressure_class=600,
        valid_from="2027-01-01T00:00:00Z",
        valid_until="2027-06-30T00:00:00Z",
    )

    granted = fixtures.qualify(api, successor["id"])

    assert granted["status"] == QualificationStatus.QUALIFIED
    assert granted["valid_from"].startswith("2027-01-01T00:00:00")
    assert granted["qualified_by_user_id"] == "qm-1"
    incumbent = fixtures.read_qualification(api, works["qualification"]["id"])
    assert incumbent["status"] == QualificationStatus.QUALIFIED
