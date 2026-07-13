"""Existence (404) errors across path parameters and body foreign keys.

Corner (breadth) translations from the `errors` section (§2.5 left-to-right existence).
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_referred_overweight_screening,
    create_carrier,
    create_station,
    create_bay,
    create_driver,
    make_carrier_rep_headers,
    make_officer_headers,
)

ADMIN = TEST_USERS["compliance_admin_headers"]
SCREENER = TEST_USERS["screener_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]

BOGUS_BAY = "11111111-1111-4111-8111-111111111111"
BOGUS_CARRIER = "22222222-2222-4222-8222-222222222222"
BOGUS_STATION = "33333333-3333-4333-8333-333333333333"
BOGUS_DRIVER = "44444444-4444-4444-8444-444444444444"
BOGUS_SCREENING = "55555555-5555-4555-8555-555555555555"
BOGUS_INSPECTION = "66666666-6666-4666-8666-666666666666"
BOGUS_CITATION = "77777777-7777-4777-8777-777777777777"


def test_inspection_with_missing_bay_returns_404(api):
    """PRD §2.5: "A missing carrier yields `ERR_CARRIER_NOT_FOUND`, a missing station
    `ERR_STATION_NOT_FOUND`, a missing bay `ERR_BAY_NOT_FOUND`, a missing driver
    `ERR_DRIVER_NOT_FOUND`, a missing screening `ERR_SCREENING_NOT_FOUND`, a missing
    inspection `ERR_INSPECTION_NOT_FOUND`, and a missing citation
    `ERR_CITATION_NOT_FOUND`."

    Design: Corner/errors/inspection_missing_bay_returns_404
    """
    d = setup_referred_overweight_screening(
        carrier_overrides={"usdot_number": "DOT-C16", "legal_name": "Corner Sixteen"},
        station_overrides={"name": "S16", "state_code": "CA"})
    resp = api.create_inspection(
        {"screening_id": d["screening"]["id"], "bay_id": BOGUS_BAY, "level": "LEVEL_I",
         "scheduled_start": "2026-03-02T10:00:00Z", "scheduled_end": "2026-03-02T11:00:00Z"},
        INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_BAY_NOT_FOUND)


def test_screening_with_missing_carrier_returns_404(api):
    """PRD §2.5: "A missing carrier yields `ERR_CARRIER_NOT_FOUND`, a missing station
    `ERR_STATION_NOT_FOUND`, a missing bay `ERR_BAY_NOT_FOUND`, a missing driver
    `ERR_DRIVER_NOT_FOUND`, a missing screening `ERR_SCREENING_NOT_FOUND`, a missing
    inspection `ERR_INSPECTION_NOT_FOUND`, and a missing citation
    `ERR_CITATION_NOT_FOUND`."

    Design: Corner/errors/screening_missing_carrier_returns_404
    """
    carrier = create_carrier(usdot_number="DOT-C17", legal_name="Corner Seventeen")
    station = create_station(name="S17", state_code="CA")
    driver = create_driver(carrier["id"], cdl_number="CDL-C17", full_name="Cor Seventeen")
    resp = api.create_screening(
        {"station_id": station["id"], "carrier_id": BOGUS_CARRIER, "driver_id": driver["id"],
         "vehicle_plate": "PLT-C17", "axle_count": 5, "gross_weight_lbs": 86000,
         "heaviest_axle_lbs": 21000, "hazmat_placarded": False},
        SCREENER)
    validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)


def test_bays_under_missing_station_returns_404(api):
    """PRD §2.5: "The list endpoints that hang off a parent — a carrier's drivers, a
    carrier's score snapshots, a station's bays, a driver's duty logs, an inspection's
    violations — exist so that a child can be reached from its parent; each honors the
    same left-to-right existence rule for the parent in its path."

    Design: Corner/errors/bays_under_missing_station_returns_404
    """
    resp = api.create_bay(BOGUS_STATION, {"label": "Bay 1"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STATION_NOT_FOUND)


def test_duty_log_under_missing_driver_returns_404(api):
    """PRD §2.5: "A missing carrier yields `ERR_CARRIER_NOT_FOUND`, a missing station
    `ERR_STATION_NOT_FOUND`, a missing bay `ERR_BAY_NOT_FOUND`, a missing driver
    `ERR_DRIVER_NOT_FOUND`, a missing screening `ERR_SCREENING_NOT_FOUND`, a missing
    inspection `ERR_INSPECTION_NOT_FOUND`, and a missing citation
    `ERR_CITATION_NOT_FOUND`."

    Design: Corner/errors/duty_log_under_missing_driver_returns_404
    """
    resp = api.create_duty_log(
        BOGUS_DRIVER,
        {"entry_type": "DRIVING", "start_utc": "2026-03-02T00:00:00Z",
         "end_utc": "2026-03-02T02:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_FOUND)


def test_inspection_with_missing_screening_returns_404(api):
    """PRD §2.5: "A missing carrier yields `ERR_CARRIER_NOT_FOUND`, a missing station
    `ERR_STATION_NOT_FOUND`, a missing bay `ERR_BAY_NOT_FOUND`, a missing driver
    `ERR_DRIVER_NOT_FOUND`, a missing screening `ERR_SCREENING_NOT_FOUND`, a missing
    inspection `ERR_INSPECTION_NOT_FOUND`, and a missing citation
    `ERR_CITATION_NOT_FOUND`."

    Design: Corner/errors/inspection_with_missing_screening_returns_404
    """
    station = create_station(name="S25", state_code="CA")
    bay = create_bay(station["id"], label="Bay 1")
    resp = api.create_inspection(
        {"screening_id": BOGUS_SCREENING, "bay_id": bay["id"], "level": "LEVEL_I",
         "scheduled_start": "2026-03-02T10:00:00Z", "scheduled_end": "2026-03-02T11:00:00Z"},
        INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_FOUND)


def test_citation_with_missing_inspection_returns_404(api):
    """PRD §2.5: "A missing carrier yields `ERR_CARRIER_NOT_FOUND`, a missing station
    `ERR_STATION_NOT_FOUND`, a missing bay `ERR_BAY_NOT_FOUND`, a missing driver
    `ERR_DRIVER_NOT_FOUND`, a missing screening `ERR_SCREENING_NOT_FOUND`, a missing
    inspection `ERR_INSPECTION_NOT_FOUND`, and a missing citation
    `ERR_CITATION_NOT_FOUND`."

    Design: Corner/errors/citation_with_missing_inspection_returns_404
    """
    carrier = create_carrier(usdot_number="DOT-C26", legal_name="Corner TwentySix")
    resp = api.create_citation(
        {"inspection_id": BOGUS_INSPECTION, "carrier_id": carrier["id"], "kind": "OVERWEIGHT"},
        make_officer_headers("officer-1"))
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_FOUND)


def test_contest_missing_citation_returns_404(api):
    """PRD §2.5: "A missing carrier yields `ERR_CARRIER_NOT_FOUND`, a missing station
    `ERR_STATION_NOT_FOUND`, a missing bay `ERR_BAY_NOT_FOUND`, a missing driver
    `ERR_DRIVER_NOT_FOUND`, a missing screening `ERR_SCREENING_NOT_FOUND`, a missing
    inspection `ERR_INSPECTION_NOT_FOUND`, and a missing citation
    `ERR_CITATION_NOT_FOUND`."

    Design: Corner/errors/contest_missing_citation_returns_404
    """
    carrier = create_carrier(usdot_number="DOT-C27", legal_name="Corner TwentySeven")
    resp = api.contest_citation(
        BOGUS_CITATION, {"contest_reason": "n/a"}, make_carrier_rep_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_CITATION_NOT_FOUND)
