"""Habitat composite score and the weighted training-compliance rollup."""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    create_airport,
    create_biologist,
    make_biologist_headers,
)


def test_composite_habitat_score_multiplication(api):
    """PRD §3.3: "The server immediately computes `composite_score` as the
    product of the two scores, an integer in the range 1 to 100."

    Design: Corner/calculations/composite_habitat_score_multiplication
    """
    set_clock()
    airport = create_airport(icao_code="KGGG", name="Golf Airport")
    b1 = create_biologist(airport["id"], is_senior=True, certification_id="CERT-G01")
    assessment = validate_success(
        api.create_habitat_assessment(
            {
                "airport_id": airport["id"],
                "assessed_by_biologist_id": b1["id"],
                "assessed_at": "2026-07-15T10:00:00Z",
                "habitat_feature": "STANDING_WATER",
                "attractiveness_score": 7,
                "severity_score": 8,
            },
            make_biologist_headers(b1["id"]),
        ),
        201,
    )
    assert assessment["composite_score"] == 56, (
        f"7 * 8 must yield 56, got {assessment['composite_score']}"
    )


def test_training_currency_score_weighted(api, admin_headers):
    """PRD §3.6: "Each biologist's score is the average of their
    training-record contributions — `VALID` records contribute one,
    `EXPIRING_SOON` records contribute one-half, and `EXPIRED` or `REVOKED`
    records contribute zero — averaged across that biologist's records, with a
    biologist who has no records counting as a zero contribution over a
    denominator of one. The airport-level `airport_compliance_pct` is the mean
    of the per-biologist scores multiplied by one hundred, rounded half-up to
    two decimal places"
    PRD §3.6: "The system moves a `VALID` record to `EXPIRING_SOON` when the
    logical clock reaches thirty days before `expires_at`"

    Design: Corner/calculations/training_currency_score_weighted
    """
    set_clock()
    airport = create_airport(icao_code="KHHH", name="Hotel Airport")
    b1 = create_biologist(airport["id"], is_senior=True, certification_id="CERT-H01")
    b1h = make_biologist_headers(b1["id"])

    # VALID: expires 2027-01-01, far beyond the 30-day warning window.
    validate_success(
        api.create_training_record(
            {"biologist_id": b1["id"], "course_code": "WHA-101",
             "completed_at": "2026-01-01", "expires_at": "2027-01-01"},
            b1h,
        ),
        201,
    )
    # EXPIRING_SOON: expires 2026-08-15, within 30 days of clock 2026-08-01.
    validate_success(
        api.create_training_record(
            {"biologist_id": b1["id"], "course_code": "WHA-102",
             "completed_at": "2025-08-01", "expires_at": "2026-08-15"},
            b1h,
        ),
        201,
    )
    # Re-set the clock to force evaluation of pending time-driven transitions.
    set_clock()

    data = validate_success(api.get_training_compliance(airport["id"], admin_headers), 200)
    # (1.0 + 0.5) / 2 records = 0.75 per-biologist; single biologist ->
    # airport_compliance_pct == 75.00
    assert data["airport_compliance_pct"] == pytest.approx(75.00, abs=0.005), (
        f"expected 75.00, got {data['airport_compliance_pct']}"
    )
