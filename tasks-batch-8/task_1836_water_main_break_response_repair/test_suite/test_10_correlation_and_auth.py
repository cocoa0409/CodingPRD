"""Anomaly correlation (happy path, 6-hour window, cross-segment guard) and
authentication / role-authorization basics."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_break,
    create_anomaly,
    create_break,
    create_crew,
    create_segment,
    get_break,
    make_crew_lead_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _api
from test_helpers import (
    confirm_break_report_payload,
    correlate_payload,
    create_break_report_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
SYSTEM = TEST_USERS["system_headers"]


# ---------------------------------------------------------------------------
# Corner: correlate_happy_path_links_anomaly
# ---------------------------------------------------------------------------

def test_correlate_happy_path_links_anomaly(api):
    """PRD §3.2: "A successful correlation stamps the anomaly's
    `correlated_break_report_id` with the break's id and flips its
    `correlation_status` to `CORRELATED`. The anomalies correlated to a break
    are listable under the break's nested route."

    Design: Corner/endpoints/correlate_happy_path_links_anomaly
    """
    seg = create_segment(segment_ref="MAIN-8-OAK", material="PVC",
                         diameter_inches=8, install_year=1999)
    an = create_anomaly(seg["id"], anomaly_type="PRESSURE_DROP",
                        observed_at="2026-08-01T00:00:00Z", magnitude_pct=45)
    br = create_break(location_description="12 Oak St", source="SENSOR_SCADA")
    br = confirm_break(br["id"], seg["id"], break_type="SPLIT", severity="MEDIUM")

    resp = _api.correlate_break_report(
        br["id"], correlate_payload(pressure_anomaly_id=an["id"]), DISPATCHER
    )
    anomaly = validate_success(resp, 200)
    assert anomaly["correlation_status"] == "CORRELATED"
    assert anomaly["correlated_break_report_id"] == br["id"]

    listed, _meta = validate_paginated(
        _api.list_break_pressure_anomalies(br["id"], DISPATCHER)
    )
    assert [a["id"] for a in listed] == [an["id"]], (
        "the correlated anomaly must be discoverable under the break's nested route"
    )


# ---------------------------------------------------------------------------
# Corner: correlate_outside_6h_window_rejected
# ---------------------------------------------------------------------------

def test_correlate_outside_6h_window_rejected(api):
    """PRD §3.2: "Three conditions guard this linkage, all checked at
    correlation time: the anomaly must still be `UNCORRELATED` (otherwise
    `ERR_INVALID_STATE`); the anomaly's `pipe_segment_id` must equal the
    break's `pipe_segment_id` (otherwise `ERR_CROSS_REFERENCE_MISMATCH`); and
    the absolute difference between the anomaly's `observed_at` and the break
    report's `created_at` must be no more than six hours (otherwise
    `ERR_CORRELATION_WINDOW`)."

    Design: Corner/validations/correlate_outside_6h_window_rejected
    """
    seg = create_segment(segment_ref="MAIN-8-OAK", material="PVC",
                         diameter_inches=8, install_year=1999)
    # Anomaly observed 7 hours before the report's creation (report is created
    # at the startup clock 2026-08-01T00:00:00Z).
    an = create_anomaly(seg["id"], anomaly_type="PRESSURE_DROP",
                        observed_at="2026-07-31T17:00:00Z", magnitude_pct=45)
    br = create_break(location_description="12 Oak St", source="SENSOR_SCADA")
    br = confirm_break(br["id"], seg["id"], break_type="SPLIT", severity="MEDIUM")

    resp = _api.correlate_break_report(
        br["id"], correlate_payload(pressure_anomaly_id=an["id"]), DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_CORRELATION_WINDOW)


# ---------------------------------------------------------------------------
# Corner: correlate_cross_segment_rejected
# ---------------------------------------------------------------------------

def test_correlate_cross_segment_rejected(api):
    """PRD §3.2: "Three conditions guard this linkage, all checked at
    correlation time: the anomaly must still be `UNCORRELATED` (otherwise
    `ERR_INVALID_STATE`); the anomaly's `pipe_segment_id` must equal the
    break's `pipe_segment_id` (otherwise `ERR_CROSS_REFERENCE_MISMATCH`); and
    the absolute difference between the anomaly's `observed_at` and the break
    report's `created_at` must be no more than six hours (otherwise
    `ERR_CORRELATION_WINDOW`)."

    Design: Corner/validations/correlate_cross_segment_rejected
    """
    s1 = create_segment(segment_ref="MAIN-8-OAK", material="PVC",
                        diameter_inches=8, install_year=1999)
    s2 = create_segment(segment_ref="MAIN-6-PINE", material="PVC",
                        diameter_inches=6, install_year=2001)
    an = create_anomaly(s2["id"], anomaly_type="FLOW_SPIKE",
                        observed_at="2026-08-01T00:00:00Z", magnitude_pct=60)
    br = create_break(location_description="12 Oak St", source="SENSOR_SCADA")
    br = confirm_break(br["id"], s1["id"], break_type="SPLIT", severity="MEDIUM")

    resp = _api.correlate_break_report(
        br["id"], correlate_payload(pressure_anomaly_id=an["id"]), DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH)


# ---------------------------------------------------------------------------
# Corner: missing_auth_header_returns_400
# ---------------------------------------------------------------------------

def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID` and
    `X-User-Role`. If either header is missing or empty, the request is
    rejected with `ERR_MISSING_CONTEXT_HEADER` (HTTP 400) before any other
    processing."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    resp = _api.create_break_report(
        create_break_report_payload(
            location_description="12 Oak St", source="CUSTOMER_CALL"
        ),
        headers={},  # no X-User-ID / X-User-Role
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_CONTEXT_HEADER)


def test_missing_user_id_header_returns_400(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID` and
    `X-User-Role`. If either header is missing or empty, the request is
    rejected with `ERR_MISSING_CONTEXT_HEADER` (HTTP 400) before any other
    processing."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    resp = _api.create_break_report(
        create_break_report_payload(
            location_description="12 Oak St", source="CUSTOMER_CALL"
        ),
        headers={"X-User-Role": "Dispatcher", "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_CONTEXT_HEADER)


# ---------------------------------------------------------------------------
# Corner: confirm_as_crew_lead_returns_forbidden
# ---------------------------------------------------------------------------

def test_confirm_as_crew_lead_returns_forbidden(api):
    """PRD §2.1: "If the named role is not in the endpoint's authorized role
    list — or, for the crew-ownership actions described in §3.4, the calling
    user's identity does not match the work order's assigned crew — the request
    is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.2: "A `Dispatcher` confirms a `REPORTED` report by supplying the
    `pipe_segment_id` it occurred on, the `break_type` (`CIRCUMFERENTIAL`,
    `SPLIT`, or `BLOWOUT`), and the `severity` (`LOW`, `MEDIUM`, or `HIGH`)."

    Design: Corner/validations/confirm_as_crew_lead_returns_forbidden
    """
    seg = create_segment(segment_ref="MAIN-8-OAK", material="PVC",
                         diameter_inches=8, install_year=1999)
    crew = create_crew(crew_name="Crew Oak", crew_size=3,
                       equipment_class="LIGHT", hourly_rate_cents=6000)
    br = create_break(location_description="12 Oak St", source="CUSTOMER_CALL")

    resp = _api.confirm_break_report(
        br["id"],
        confirm_break_report_payload(
            pipe_segment_id=seg["id"], break_type="SPLIT", severity="LOW"
        ),
        make_crew_lead_headers(crew["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_break(br["id"])["break_status"] == "REPORTED", (
        "a forbidden confirm must leave the report REPORTED"
    )
