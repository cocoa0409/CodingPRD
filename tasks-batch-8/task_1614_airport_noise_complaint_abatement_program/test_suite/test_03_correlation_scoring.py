"""Complaint-to-flight correlation: the STRICT/RELAXED dual variants, the
substantiation confidence boundary, correlation request guards, and the
optimistic-concurrency stale-version rejection."""
import pytest

from test_helpers import (
    ApiErrorId,
    begin_review,
    create_complaint,
    create_complainant,
    create_operated_flight,
    create_operator,
    create_flight,
    TEST_USERS,
    validate_error,
    validate_success,
)

LIAISON = TEST_USERS["community_liaison_headers"]
ANALYST = TEST_USERS["noise_analyst_headers"]


def _setup_zone_flight_and_complaints(api, occurred_ats):
    """Complainant in Z1 + OPERATED flight at 12:00:00Z in Z1 + one complaint
    per occurred_at, each walked to UNDER_REVIEW. Returns ids and versions."""
    complainant = create_complainant(full_name="Corr One", email="corr1@x.com", zone_code="Z1")
    operator = create_operator(name="Air One")
    flight = create_operated_flight(
        operator["id"],
        "2026-07-15T12:00:00Z",
        scheduled_at="2026-07-15T11:55:00Z",
        zone_code="Z1",
    )
    complaints = []
    for occurred_at in occurred_ats:
        complaint = create_complaint(
            complainant["id"], occurred_at, disturbance_type="LOUD_EVENT"
        )
        version = begin_review(complaint["id"])
        complaints.append({"id": complaint["id"], "version": version})
    return complainant, flight, complaints


def test_strict_variant_correlation_at_two_minutes(api):
    """PRD 3.4: "The `STRICT` variant is tried first and applies when the elapsed
    time is at most 300 seconds: the score starts at 100, decays by 40 points
    proportionally across the 300-second window, subtracts a 10-point penalty when
    the flight's `zone_code` differs from the complainant's, and adds a 15-point
    bonus when a linked event is `CLASSIFIED_AIRCRAFT` or `VERIFIED`."
    PRD 3.4: "sets `substantiation_eligible` to `true` exactly when the confidence
    is at least 60.0".

    Design: Difficulty/dual_variant_calc/correlation_strict_and_relaxed_variants_diverge
    """
    _complainant, flight, complaints = _setup_zone_flight_and_complaints(
        api, ["2026-07-15T12:02:00Z"]
    )
    # dt = 120s, zones match: STRICT score = 100 - 40*(120/300) = 84.0.
    response = api.correlate_complaint(
        complaints[0]["id"],
        {"flight_id": flight["id"], "expected_complaint_version": complaints[0]["version"]},
        ANALYST,
    )
    correlated = validate_success(response, 200)
    assert correlated["status"] == "CORRELATED"
    assert correlated["correlation_variant_used"] == "STRICT"
    assert correlated["correlation_confidence"] == pytest.approx(84.0, abs=1e-6)
    assert correlated["substantiation_eligible"] is True
    assert correlated["correlated_flight_id"] == flight["id"]


def test_relaxed_variant_correlation_beyond_strict_window(api):
    """PRD 3.4: "When no `STRICT`-eligible flight exists, the `RELAXED` variant
    applies while the elapsed time is at most 1200 seconds: the score starts at 85,
    decays by 55 points proportionally across the 1200-second window, subtracts a
    15-point zone penalty, and adds a 10-point event bonus under the same condition."
    PRD 3.4: "the newly linked flight's increments by one."

    Design: Difficulty/dual_variant_calc/correlation_strict_and_relaxed_variants_diverge
    """
    _complainant, flight, complaints = _setup_zone_flight_and_complaints(
        api, ["2026-07-15T12:02:00Z", "2026-07-15T12:05:01Z"]
    )
    first = validate_success(
        api.correlate_complaint(
            complaints[0]["id"],
            {"flight_id": flight["id"], "expected_complaint_version": complaints[0]["version"]},
            ANALYST,
        ),
        200,
    )
    assert first["correlation_variant_used"] == "STRICT"

    # dt = 301s: outside the 300s STRICT window, inside the 1200s RELAXED window.
    second = validate_success(
        api.correlate_complaint(
            complaints[1]["id"],
            {"flight_id": flight["id"], "expected_complaint_version": complaints[1]["version"]},
            ANALYST,
        ),
        200,
    )
    assert second["correlation_variant_used"] == "RELAXED"
    assert second["correlation_confidence"] == pytest.approx(71.2, abs=1e-6)
    assert second["substantiation_eligible"] is True

    reread_flight = validate_success(api.get_flight(flight["id"], ANALYST))
    assert reread_flight["linked_complaint_count"] == 2


def test_substantiation_confidence_exactly_60_boundary(api):
    """PRD 3.4: "Closing with `outcome` `SUBSTANTIATED` requires the complaint to be
    `CORRELATED` and its `correlation_confidence` to be at least 60.0 (else
    `ERR_CONFIDENCE_BELOW_THRESHOLD`)".
    PRD 3.4: "subtracts a 10-point penalty when the flight's `zone_code` differs
    from the complainant's".

    Design: Corner/calculations/substantiation_confidence_exactly_60_boundary
    """
    complainant = create_complainant(full_name="BC One", email="bc1@x.com", zone_code="Z1")
    operator = create_operator(name="Air Bound")
    flight_match = create_operated_flight(
        operator["id"], "2026-07-15T12:00:00Z",
        scheduled_at="2026-07-15T11:55:00Z", zone_code="Z1",
    )
    flight_mismatch = create_operated_flight(
        operator["id"], "2026-07-15T12:00:00Z",
        scheduled_at="2026-07-15T11:55:00Z", runway_code="27R", zone_code="Z2",
    )

    c1 = create_complaint(complainant["id"], "2026-07-15T12:05:00Z",
                          disturbance_type="LOUD_EVENT")
    c2 = create_complaint(complainant["id"], "2026-07-15T12:05:00Z",
                          disturbance_type="LOUD_EVENT")
    v1 = begin_review(c1["id"])
    v2 = begin_review(c2["id"])

    # dt = 300s (boundary of the STRICT window), zones match: 100 - 40 = 60.0.
    corr1 = validate_success(
        api.correlate_complaint(
            c1["id"], {"flight_id": flight_match["id"], "expected_complaint_version": v1}, ANALYST
        ),
        200,
    )
    assert corr1["correlation_confidence"] == pytest.approx(60.0, abs=1e-6)
    assert corr1["substantiation_eligible"] is True

    # Same dt with a zone mismatch: 100 - 40 - 10 = 50.0.
    corr2 = validate_success(
        api.correlate_complaint(
            c2["id"],
            {"flight_id": flight_mismatch["id"], "expected_complaint_version": v2},
            ANALYST,
        ),
        200,
    )
    assert corr2["correlation_confidence"] == pytest.approx(50.0, abs=1e-6)
    assert corr2["substantiation_eligible"] is False

    closed = validate_success(
        api.close_complaint(c1["id"], {"outcome": "SUBSTANTIATED"}, ANALYST), 200
    )
    assert closed["status"] == "CLOSED_SUBSTANTIATED"

    rejected = api.close_complaint(c2["id"], {"outcome": "SUBSTANTIATED"}, ANALYST)
    validate_error(rejected, ApiErrorId.ERR_CONFIDENCE_BELOW_THRESHOLD)


def test_correlate_without_any_target_rejected(api):
    """PRD 3.4: "a `NoiseAnalyst` correlates the complaint, supplying a `flight_id`,
    a `noise_event_id`, or both; supplying neither is rejected with
    `ERR_CORRELATION_TARGET_REQUIRED`."

    Design: Corner/validations/correlate_without_any_target_rejected
    """
    complainant = create_complainant(full_name="VT One", email="vt1@x.com")
    complaint = create_complaint(complainant["id"], "2026-07-15T09:00:00Z")
    version = begin_review(complaint["id"])

    response = api.correlate_complaint(
        complaint["id"], {"expected_complaint_version": version}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_CORRELATION_TARGET_REQUIRED)


def test_correlate_beyond_relaxed_window_rejected(api):
    """PRD 3.4: "If neither variant yields an eligible correlation, the request is
    rejected with `ERR_CORRELATION_WINDOW_EXCEEDED`."

    Design: Corner/validations/correlate_beyond_relaxed_window_rejected
    """
    complainant = create_complainant(full_name="VT Two", email="vt2@x.com", zone_code="Z1")
    operator = create_operator(name="Air Win")
    flight = create_operated_flight(
        operator["id"], "2026-07-15T12:00:00Z",
        scheduled_at="2026-07-15T11:55:00Z", zone_code="Z1",
    )
    # dt = 1201s: beyond the 1200-second RELAXED ceiling.
    complaint = create_complaint(
        complainant["id"], "2026-07-15T12:20:01Z", disturbance_type="LOUD_EVENT"
    )
    version = begin_review(complaint["id"])

    response = api.correlate_complaint(
        complaint["id"],
        {"flight_id": flight["id"], "expected_complaint_version": version},
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_CORRELATION_WINDOW_EXCEEDED)


def test_correlate_unoperated_flight_rejected(api):
    """PRD 3.4: "A supplied flight must be `OPERATED` (else
    `ERR_FLIGHT_NOT_OPERATED`)".

    Design: Corner/validations/correlate_unoperated_flight_rejected
    """
    complainant = create_complainant(full_name="VT Three", email="vt3@x.com")
    operator = create_operator(name="Air Sched")
    flight = validate_success(
        api.create_flight(
            {
                "flight_number": "AS1",
                "operator_id": operator["id"],
                "aircraft_type": "B738",
                "engine_class": "STAGE_4",
                "operation_type": "DEPARTURE",
                "runway_code": "09L",
                "scheduled_at": "2026-07-15T11:55:00Z",
                "zone_code": "Z1",
            },
            TEST_USERS["noise_office_admin_headers"],
        ),
        201,
    )
    assert flight["status"] == "SCHEDULED"
    complaint = create_complaint(
        complainant["id"], "2026-07-15T12:02:00Z", disturbance_type="LOUD_EVENT"
    )
    version = begin_review(complaint["id"])

    response = api.correlate_complaint(
        complaint["id"],
        {"flight_id": flight["id"], "expected_complaint_version": version},
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_FLIGHT_NOT_OPERATED)


def test_occ_stale_correlation_version_rejected(api):
    """PRD 2.6: "correlating a complaint to flight or event evidence — the correlate
    endpoint (`POST /noise-program/noise-complaints/{complaintId}/correlate`) —
    requires `expected_complaint_version` matching the complaint's current
    `version`."
    PRD 2.6: "A mismatch means a prior correlation or another mutation has advanced
    the complaint's version, and the new correlation would supersede data the client
    never saw; the request is rejected with `ERR_STALE_CORRELATION_VERSION`
    (HTTP 412)."

    Design: Corner/complexity_layers/occ_stale_correlation_version_rejected
    """
    complainant = create_complainant(full_name="Occ One", email="occ1@x.com", zone_code="Z1")
    operator = create_operator(name="Air Occ")
    flight_a = create_operated_flight(
        operator["id"], "2026-07-15T12:00:00Z",
        scheduled_at="2026-07-15T11:55:00Z", zone_code="Z1",
    )
    flight_b = create_operated_flight(
        operator["id"], "2026-07-15T12:01:00Z",
        scheduled_at="2026-07-15T11:56:00Z", zone_code="Z1",
    )
    complaint = create_complaint(
        complainant["id"], "2026-07-15T12:02:00Z", disturbance_type="LOUD_EVENT"
    )
    version = begin_review(complaint["id"])

    first = validate_success(
        api.correlate_complaint(
            complaint["id"],
            {"flight_id": flight_a["id"], "expected_complaint_version": version},
            ANALYST,
        ),
        200,
    )
    assert first["status"] == "CORRELATED"

    # Re-correlation from CORRELATED is legal; only the stale version rejects.
    replayed = api.correlate_complaint(
        complaint["id"],
        {"flight_id": flight_b["id"], "expected_complaint_version": version},
        ANALYST,
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_CORRELATION_VERSION)
