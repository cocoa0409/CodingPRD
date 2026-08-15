"""Temporal window semantics: half-open antibiogram windows; rolling 365-day isolates."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_microbiologist_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_antibiogram_payload, create_culture_report_payload,
    api_client, ApiErrorId,
)


def _setup_hospital_mb():
    hospital = create_hospital()
    mb = create_practitioner(
        hospital["id"], "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1"
    )
    return hospital, mb


def test_adjacent_antibiogram_windows_allowed(api):
    """PRD Section 3.7: "the window is half-open — inclusive at the start,
    exclusive at the end — so adjacent periods share no isolate" and "a window
    overlapping an existing antibiogram window for the same hospital fails with
    `ERR_ANTIBIOGRAM_WINDOW_OVERLAP`; windows that merely touch at an endpoint
    are allowed."

    Design: Difficulty/resource_temporal_overlap/antibiogram_half_open_window_overlap
    """
    hospital, mb = _setup_hospital_mb()
    first = validate_success(
        api.create_antibiogram(
            create_antibiogram_payload(hospital["id"]),
            make_microbiologist_headers(mb["id"]),
        ), 201,
    )
    # Touching endpoint: second window starts exactly at the first window's end.
    second = validate_success(
        api.create_antibiogram(
            create_antibiogram_payload(
                hospital["id"],
                period_start="2026-09-01T00:00:00Z",
                period_end="2026-10-01T00:00:00Z",
            ),
            make_microbiologist_headers(mb["id"]),
        ), 201,
    )
    assert second["id"] != first["id"]


def test_overlapping_antibiogram_window_rejected(api):
    """PRD Section 3.7: "a window overlapping an existing antibiogram window
    for the same hospital fails with `ERR_ANTIBIOGRAM_WINDOW_OVERLAP`;
    windows that merely touch at an endpoint are allowed."

    Design: Difficulty/resource_temporal_overlap/antibiogram_half_open_window_overlap
    """
    hospital, mb = _setup_hospital_mb()
    validate_success(
        api.create_antibiogram(
            create_antibiogram_payload(hospital["id"]),
            make_microbiologist_headers(mb["id"]),
        ), 201,
    )
    # Starts one second before the first window's end -> genuine overlap.
    res = api.create_antibiogram(
        create_antibiogram_payload(
            hospital["id"],
            period_start="2026-08-31T23:59:59Z",
            period_end="2026-10-01T00:00:00Z",
        ),
        make_microbiologist_headers(mb["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ANTIBIOGRAM_WINDOW_OVERLAP)


def _setup_first_isolate_chain():
    """C0 E_COLI/URINE collected 2026-08-01; clock then advanced a year."""
    hospital = create_hospital()
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    res = api_client.create_culture_report(
        create_culture_report_payload(patient["id"]),
        make_microbiologist_headers(mb["id"]),
    )
    c0 = get_success_data(res)
    set_clock(hid, "2027-08-01T00:00:00Z")
    return hospital, mb, patient, c0


def test_first_isolate_true_when_no_prior(api):
    """PRD Section 3.4: "at registration the server computes `is_first_isolate`
    — true when this is the patient's first isolate of that organism from that
    specimen source within the rolling 365-day window ending at `collected_at`,
    a flag on which all antibiogram counting later depends."

    Design: Difficulty/resource_temporal_overlap/first_isolate_rolling_365_day_lookback
    """
    _, _, _, c0 = _setup_first_isolate_chain()
    assert c0["is_first_isolate"] is True


def test_isolate_exactly_365_days_later_is_not_first(api):
    """PRD Section 3.4: "at registration the server computes `is_first_isolate`
    — true when this is the patient's first isolate of that organism from that
    specimen source within the rolling 365-day window ending at `collected_at`,
    a flag on which all antibiogram counting later depends."

    Design: Difficulty/resource_temporal_overlap/first_isolate_rolling_365_day_lookback
    """
    hospital, mb, patient, c0 = _setup_first_isolate_chain()
    # Exactly 365 days after C0 (2026-08-01 -> 2027-08-01): still inside the
    # rolling window ending at the new collected_at, so NOT a first isolate.
    res = api_client.create_culture_report(
        create_culture_report_payload(patient["id"], collected_at="2027-08-01T00:00:00Z"),
        make_microbiologist_headers(mb["id"]),
    )
    c365 = get_success_data(res)
    assert c365["is_first_isolate"] is False
    # One day later: C366's window still contains C365, so the chain suppresses.
    # The clock must first reach the collection time (PRD 3.4: a collected_at
    # after the hospital clock is rejected with ERR_FUTURE_SPECIMEN).
    set_clock(hospital["id"], "2027-08-02T00:00:00Z")
    res = api_client.create_culture_report(
        create_culture_report_payload(patient["id"], collected_at="2027-08-02T00:00:00Z"),
        make_microbiologist_headers(mb["id"]),
    )
    c366 = get_success_data(res)
    assert c366["is_first_isolate"] is False
