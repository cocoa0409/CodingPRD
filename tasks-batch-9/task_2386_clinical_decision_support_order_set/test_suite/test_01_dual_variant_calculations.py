"""Two quantities that each have two legitimate formulas over identical inputs.

The priority score is computed once at intake from the sponsor's self-declared
grade and again at acceptance from verified citations and backlog age. A burden
window's index is computed once by counting interruptions and once by counting
people. In both pairs the same stored data yields two different numbers on
purpose, and each variant has its own storage field or its own basis marker.
"""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    validate_success,
)


# ---------------------------------------------------------------------------
# priority_score: INTAKE_PROVISIONAL versus COMMITTEE_CALIBRATED
# ---------------------------------------------------------------------------


CHEST_PAIN_CITATIONS = [
    factories.build_citation("NEJM 2025;392:1", True),
    factories.build_citation("JAMA 2025;333:9", True),
    factories.build_citation("Circulation 2025;151:44", True),
    factories.build_citation("Internal protocol memo 2025-11", False),
    factories.build_citation("Vendor white paper", False),
]


def test_intake_provisional_score_uses_declared_grade_and_no_multiplier(committee):
    """Intake scores grade B plus EXPEDITED plus the safety flag as 57.00.

    "it awards 40 points for evidence grade `A`, 30 for `B`, 18 for `C` and 8
    for `EXPERT_OPINION`; adds 0 points for urgency `ROUTINE`, 12 for
    `EXPEDITED` and 25 for `SAFETY_URGENT`; adds a further 15 points when
    `patient_safety_flag` is true", and "The provisional variant deliberately
    ignores `peer_reviewed_citation_count` and ignores how long the request has
    waited, and it applies no multiplier of any kind."

    Design: Difficulty/dual_variant_calc/dual_variant_priority_score_provisional_versus_committee_calibrated
    """
    fixtures.reset_clock()

    payload = factories.build_content_request_payload(
        committee["sponsor"]["id"],
        title="Acute chest pain order set",
        request_type="ORDER_SET",
        clinical_domain="CARDIOLOGY",
        urgency="EXPEDITED",
        evidence_grade="B",
        patient_safety_flag=True,
        evidence_citations=CHEST_PAIN_CITATIONS,
    )
    created = validate_success(
        api_client.create_content_request(payload, committee["sponsor_headers"]), 201
    )

    assertions.assert_numeric_equals(created["priority_score"], 57.00, 2)
    assertions.assert_two_decimal_places(created["priority_score"])
    assert created["priority_score_basis"] == "INTAKE_PROVISIONAL"
    assert created["peer_reviewed_citation_count"] == 3
    assert created["status"] == "INTAKE_SUBMITTED"


def test_committee_calibrated_score_replaces_grade_and_applies_age_bonus(committee):
    """Acceptance rescores the same request as 58.50, not 57.00.

    "The citation component is 6 points for each peer-reviewed citation, capped
    at 40 points however many there are." "The age bonus is 0.02 per whole day
    of backlog age, rounded half-up to four decimal places, then capped at
    0.30. The base is multiplied by one plus that age bonus, the product is
    rounded half-up to two decimal places, and `priority_score` becomes the
    lesser of that result and 100.00."

    Design: Difficulty/dual_variant_calc/dual_variant_priority_score_provisional_versus_committee_calibrated
    """
    fixtures.reset_clock()

    request = fixtures.create_request(
        committee,
        title="Acute chest pain order set",
        request_type="ORDER_SET",
        clinical_domain="CARDIOLOGY",
        urgency="EXPEDITED",
        evidence_grade="B",
        patient_safety_flag=True,
        evidence_citations=CHEST_PAIN_CITATIONS,
    )
    assertions.assert_numeric_equals(request["priority_score"], 57.00, 2)

    # 15 whole days of backlog age, so the age bonus sits exactly on its cap.
    fixtures.set_clock("2026-08-16T00:00:00Z")

    triaged = validate_success(
        api_client.triage_content_request(
            request["id"],
            factories.build_triage_payload(
                "ACCEPT", triage_note="Evidence adequate; proceed to build"
            ),
            committee["chair_headers"],
        )
    )

    # base = 3 * 6 + 12 + 15 = 45; 45 * (1 + 0.30) = 58.50
    assertions.assert_numeric_equals(triaged["priority_score"], 58.50, 2)
    assertions.assert_two_decimal_places(triaged["priority_score"])
    assert triaged["priority_score_basis"] == "COMMITTEE_CALIBRATED"
    assert triaged["status"] == "TRIAGE_ACCEPTED"
    assert float(triaged["priority_score"]) != 57.00

    reread = fixtures.read_request(committee, request["id"])
    assertions.assert_numeric_equals(reread["priority_score"], 58.50, 2)
    assert reread["priority_score_basis"] == "COMMITTEE_CALIBRATED"


# ---------------------------------------------------------------------------
# burden index: fire-weighted versus clinician-weighted
# ---------------------------------------------------------------------------


def _active_tier2_alert_with_firings(committee):
    """An ACTIVE TIER_2 alert carrying 60 hourly firings, 45 of them overrides."""
    fixtures.reset_clock()
    scenario = fixtures.setup_active_alert(
        committee,
        alert_overrides={
            "name": "Duplicate anticoagulant",
            "override_reason_codes": ["CLINICALLY_APPROPRIATE", "PATIENT_TOLERATES"],
        },
    )
    scenario["ingest"] = fixtures.ingest_firings(
        scenario["alert"]["id"],
        "2026-09-01T00:00:00Z",
        fire_count=60,
        override_count=45,
        distinct_clinician_count=12,
        interval_seconds=3600,
    )
    return scenario


def test_fire_weighted_burden_index_normalises_against_fifty_firings(committee):
    """60 firings and 45 overrides on a TIER_2 alert score 90.00.

    "Its `override_rate` is `override_count` divided by `fire_count`, rounded
    half-up to four decimal places". "Its `volume_factor` is `fire_count`
    divided by an expected 50 firings per window, rounded half-up to four
    decimal places, then capped at 2.0." "`burden_index` is then
    `override_rate` multiplied by the tier multiplier multiplied by
    `volume_factor` multiplied by 100, rounded half-up to two decimal places".

    Design: Difficulty/dual_variant_calc/dual_variant_burden_index_fire_weighted_versus_clinician_weighted
    """
    scenario = _active_tier2_alert_with_firings(committee)
    alert_id = scenario["alert"]["id"]
    assert scenario["ingest"]["last_fired_at"] == "2026-09-03T11:00:00Z"

    window = fixtures.open_window(
        committee, alert_id, "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z"
    )
    closed = validate_success(
        api_client.close_burden_window(
            alert_id,
            window["id"],
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            committee["chair_headers"],
        )
    )

    assert closed["fire_count"] == 60
    assert closed["override_count"] == 45
    assert closed["accept_count"] == 15
    assertions.assert_numeric_equals(closed["override_rate"], 0.7500, 4)
    assertions.assert_four_decimal_places(closed["override_rate"])
    assertions.assert_numeric_equals(closed["volume_factor"], 1.2000, 4)
    assertions.assert_four_decimal_places(closed["volume_factor"])
    assertions.assert_numeric_equals(closed["burden_index"], 90.00, 2)
    assertions.assert_two_decimal_places(closed["burden_index"])

    alert = fixtures.read_alert(committee, alert_id)
    assertions.assert_numeric_equals(alert["latest_burden_index"], 90.00, 2)
    assert alert["windowed_fire_count"] == 60


def test_clinician_weighted_index_normalises_against_twenty_clinicians(committee):
    """The identical window scores 60.00 when people are counted instead.

    "Its rate is `distinct_overriding_clinician_count` divided by
    `distinct_fired_clinician_count`". "Its volume factor is
    `distinct_fired_clinician_count` divided by an expected 20 clinicians per
    window, rounded half-up to four decimal places, then capped at 2.0."
    "`burden_classification` is derived from the fire-weighted `burden_index`
    alone".

    Design: Difficulty/dual_variant_calc/dual_variant_burden_index_fire_weighted_versus_clinician_weighted
    """
    scenario = _active_tier2_alert_with_firings(committee)
    alert_id = scenario["alert"]["id"]

    window = fixtures.open_window(
        committee, alert_id, "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z"
    )
    closed = validate_success(
        api_client.close_burden_window(
            alert_id,
            window["id"],
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            committee["chair_headers"],
        )
    )

    assert closed["distinct_fired_clinician_count"] == 12
    assert closed["distinct_overriding_clinician_count"] == 12
    assertions.assert_numeric_equals(closed["burden_index_clinician_weighted"], 60.00, 2)
    assertions.assert_two_decimal_places(closed["burden_index_clinician_weighted"])

    # 90.00 clears the 65.00 low-value floor; 60.00 alone would not have.
    assert closed["burden_classification"] == "LOW_VALUE"
    assertions.assert_classification_from_index(closed)
    assert float(closed["burden_index"]) != float(closed["burden_index_clinician_weighted"])
