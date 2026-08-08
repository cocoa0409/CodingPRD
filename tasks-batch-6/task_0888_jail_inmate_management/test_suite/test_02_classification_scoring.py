"""Classification scoring, INITIAL vs REASSESSMENT, and booking-version OCC."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, fixtures,
)
from test_helpers import factories as f

INTAKE = TEST_USERS["intake_headers"]
CLASSIFICATION = TEST_USERS["classification_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def test_initial_classification_scores_min(api):
    """PRD §3.2: "a `MISDEMEANOR` scores 10 points" and "The `history_points` are the
    booking's `prior_bookings_count` multiplied by 6 points per prior booking, capped at a
    maximum of 30 points." and "a total of at least 55 yields `MAX`, otherwise a total of at
    least 25 yields `MED`, and anything below 25 yields `MIN`."

    Design: Difficulty/dual_variant_calc/classification_initial_vs_reassessment_level
    """
    inmate = fixtures.create_inmate(api)
    booking = fixtures.create_booking(api, inmate["id"], charge_severity="MISDEMEANOR",
                                      prior_bookings_count=2, sentence_days=100)
    resp = api.create_classification(
        booking["id"], f.create_classification_payload("INITIAL", booking["version"]), CLASSIFICATION
    )
    data = validate_success(resp, expected_status=201)
    assert data["total_score"] == 22, f"expected 22 (10 severity + 12 history + 0 behavior), got {data['total_score']}"
    assert data["resulting_level"] == "MIN", f"expected MIN, got {data['resulting_level']}"


def test_reassessment_behavior_points_raise_level_to_med(api):
    """PRD §3.2: "for an `INITIAL` assessment they are forced to 0, while for a `REASSESSMENT`
    they add 15 points for each infraction on the booking that has been upheld." and
    "Because a `REASSESSMENT` adds behavior points that an `INITIAL` ignores, the same charge
    severity and history can produce a higher level after infractions accumulate."

    Design: Difficulty/dual_variant_calc/classification_initial_vs_reassessment_level
    """
    inmate = fixtures.create_inmate(api)
    booking = fixtures.create_booking(api, inmate["id"], charge_severity="MISDEMEANOR",
                                      prior_bookings_count=2, sentence_days=100)
    init = get_success_data(
        api.create_classification(
            booking["id"], f.create_classification_payload("INITIAL", booking["version"]), CLASSIFICATION
        )
    )
    infraction = fixtures.report_infraction(api, booking["id"], "CONTRABAND", 3,
                                            reporter_user_id="officer-intake-1")
    fixtures.uphold_infraction(api, infraction["id"], upholder_user_id="supervisor-1")
    booking_now = get_success_data(api.get_booking(booking["id"], SUPERVISOR))
    resp = api.create_classification(
        booking["id"], f.create_classification_payload("REASSESSMENT", booking_now["version"]),
        CLASSIFICATION,
    )
    data = validate_success(resp, expected_status=201)
    assert data["total_score"] == 37, f"expected 37 (10 + 12 + 15), got {data['total_score']}"
    assert data["resulting_level"] == "MED", f"expected MED, got {data['resulting_level']}"
    assert init["resulting_level"] != data["resulting_level"], "INITIAL and REASSESSMENT levels must diverge"


def test_reassessment_off_stale_booking_version_rejected(api):
    """PRD §2.5: "If that value does not equal the booking's current `version` — for example
    because an earlier assessment or an upheld infraction has already advanced it — the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412), rather than silently producing a second
    superseding assessment off a stale view."

    Design: Corner/cross_cutting/classification_stale_booking_version_conflict
    """
    inmate = fixtures.create_inmate(api)
    booking = fixtures.create_booking(api, inmate["id"], sentence_days=60)
    stale_version = booking["version"]  # version 1 at create
    fixtures.classify_initial(api, booking["id"], stale_version)  # advances version to 2
    resp = api.create_classification(
        booking["id"], f.create_classification_payload("REASSESSMENT", stale_version), CLASSIFICATION
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
