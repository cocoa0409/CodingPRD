"""Derived figures at their declared boundaries.

The foundry index is a derived score with a banded status over it, and the test envelope
is derived from the design's pressure class and bore rather than from the operator.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    CertStatus,
    ErrorId,
    FoundryStatus,
    assert_foundry_band,
    assert_index_band_consistent,
    assert_unit_dimensions,
    factories,
    fixtures,
    make_test_technician_headers,
)


def test_01_an_index_of_exactly_eighty_still_bands_as_active(api):
    """One rejection out of two lots costs twenty points and lands the works exactly on the
    boundary, which belongs to the upper band.

    PRD §3.2: "The index is then 100 reduced by 40 times that rate, reduced further by 8 for
    each revoked qualification, rounded half up to 2 decimal places and finally clamped into
    the range 0.00 to 100.00 after the rounding." PRD §3.2: "An index of exactly 80.00 sits on
    the boundary and belongs to `ACTIVE`."

    Design: Corner/calculations/corner_foundry_quality_index_at_eighty_boundary_stays_active
    """
    qualified = fixtures.create_qualified_foundry(
        api, foundry_code="FDY-C9", name="Corner Boundary Castings", country_code="IN"
    )
    foundry_id = qualified["foundry"]["id"]
    fixtures.create_released_lot(
        api,
        foundry_id,
        heat_number="H-C901",
        mtr_document_ref="MTR-C901",
        qty_received_kg=500.000,
    )
    second = fixtures.create_released_lot(
        api,
        foundry_id,
        heat_number="H-C902",
        mtr_document_ref="MTR-C902",
        qty_received_kg=400.000,
    )

    fixtures.dispose_lot(
        api, second["id"], "QUARANTINE", quarantine_reason="Radiography indications"
    )

    foundry = fixtures.read_foundry(api, foundry_id)
    assert foundry["total_lot_count"] == 2
    assert foundry["rejected_lot_count"] == 1
    assert foundry["revoked_qualification_count"] == 0
    assert_foundry_band(foundry, 80.00, FoundryStatus.ACTIVE)
    assert_index_band_consistent(foundry)


def test_02_a_class_six_hundred_body_takes_the_class_six_hundred_envelope(api):
    """The rated pressure of the design's own class drives both the shell minimum the
    technician must reach and the seat minimum that refuses an under-pressure run.

    PRD §3.4: "Each pressure class has a rated pressure in bar: class 150 is rated 19.6,
    class 300 is 51.1, class 600 is 102.1, class 900 is 153.2, class 1500 is 255.3 and class
    2500 is 425.5. A shell test must reach 1.5 times that rated pressure; a seat test must
    reach 1.1 times it". PRD §3.4: "A record whose `test_pressure_bar` falls below the computed
    `required_pressure_bar` is refused with `ERR_TEST_PRESSURE_BELOW_STANDARD`".

    Design: Corner/calculations/corner_required_test_envelope_uses_class_600_rated_pressure
    """
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-C10",
        foundry_name="Corner Envelope Castings",
        heat_number="H-C1001",
        mtr_document_ref="MTR-C1001",
        qty_received_kg=600.000,
        model_code="BV-600-ENV",
        pressure_class=600,
        bore_size_mm=200,
        base_break_torque_nm=900.0,
        net_weight_kg=240.000,
        license_code="MON-C10",
        scope_valve_types=["BALL"],
        grant_license=False,
    )
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-C10-1",
    )
    fixtures.advance_to_assembled(api, unit["id"], technician_user_id="tech-c10")

    shell = fixtures.record_test(
        api,
        unit["id"],
        "SHELL",
        test_bench_code="BENCH-C10",
        started_at="2026-08-01T08:00:00Z",
        ended_at="2026-08-01T09:00:00Z",
        test_pressure_bar=160.0,
        hold_seconds=120,
        technician_user_id="tech-c10",
    )

    # 1.5 times the class-600 rated 102.1 is 153.15, which rounds half up to 153.2.
    assert float(shell["required_pressure_bar"]) == 153.2
    # A 200 millimetre bore sits in the band above 150 up to and including 300.
    assert shell["required_hold_seconds"] == 120

    response = api.create_test_record(
        unit["id"],
        factories.test_record_payload(
            "SEAT",
            "BENCH-C10",
            "2026-08-01T09:00:00Z",
            "2026-08-01T10:00:00Z",
            100.0,
            120,
            "PASS",
        ),
        make_test_technician_headers("tech-c10"),
    )

    # 1.1 times 102.1 is 112.31, which rounds half up to 112.3 — above the applied 100.0.
    validate_error(response, ErrorId.TEST_PRESSURE_BELOW_STANDARD, 422)
    assert_unit_dimensions(
        fixtures.read_unit(api, unit["id"]), cert_status=CertStatus.TESTS_IN_PROGRESS
    )
