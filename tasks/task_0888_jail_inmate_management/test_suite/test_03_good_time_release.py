"""Good-time credit (statutory vs earned), forfeiture recompute, and release eligibility."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, fixtures,
)
from test_helpers import factories as f

INTAKE = TEST_USERS["intake_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / release_statutory_vs_earned_release_date
# ---------------------------------------------------------------------------
def test_release_projection_statutory_figures(api):
    """PRD §3.8: "`statutory_good_time_days` is the `sentence_days` multiplied by the statutory
    rate of 0.10, floored to a whole number of days, and `statutory_release_date` is the
    `sentence_start_date` advanced by the `sentence_days` minus the `statutory_good_time_days`."

    Design: Difficulty/dual_variant_calc/release_statutory_vs_earned_release_date
    """
    _inmate, booking = fixtures.create_classified_booking(
        api, sex="MALE", charge_severity="MISDEMEANOR", prior_bookings_count=0, sentence_days=100
    )
    assert booking["classification_level"] == "MIN"
    proj = validate_success(api.get_release_projection(booking["id"], SUPERVISOR))
    assert proj["statutory_good_time_days"] == 10, f"expected 10, got {proj['statutory_good_time_days']}"
    assert proj["statutory_release_date"] == "2026-07-30", (
        f"expected 2026-07-30, got {proj['statutory_release_date']}"
    )


def test_release_projection_earned_diverges_from_statutory(api):
    """PRD §3.8: "the two release dates diverge for identical `sentence_days`; the earned
    projection is the one that governs release eligibility." and "a `MIN` booking accrues at
    0.25 ... the cap is the `sentence_days` multiplied by 0.20 and floored to whole days."

    Design: Difficulty/dual_variant_calc/release_statutory_vs_earned_release_date
    """
    _inmate, booking = fixtures.create_classified_booking(
        api, sex="MALE", charge_severity="MISDEMEANOR", prior_bookings_count=0, sentence_days=100
    )
    proj = validate_success(api.get_release_projection(booking["id"], SUPERVISOR))
    assert proj["earned_good_time_days"] == 20, f"expected 20, got {proj['earned_good_time_days']}"
    assert proj["projected_release_date"] == "2026-07-20", (
        f"expected 2026-07-20, got {proj['projected_release_date']}"
    )
    assert proj["statutory_release_date"] != proj["projected_release_date"], (
        "statutory and earned release dates must diverge"
    )


# ---------------------------------------------------------------------------
# calculations / statutory_good_time_computed_at_booking_create
# ---------------------------------------------------------------------------
def test_statutory_computed_before_classification(api):
    """PRD §3.8: "This figure ignores classification and behavior and is computed at booking
    time." and "an unclassified booking accrues at a rate of 0, so its earned credit is 0."

    Design: Corner/calculations/statutory_good_time_computed_at_booking_create
    """
    inmate = fixtures.create_inmate(api)
    booking = fixtures.create_booking(api, inmate["id"], charge_severity="FELONY", sentence_days=100)
    proj = validate_success(api.get_release_projection(booking["id"], SUPERVISOR))
    assert proj["statutory_good_time_days"] == 10, f"got {proj['statutory_good_time_days']}"
    assert proj["statutory_release_date"] == "2026-07-30", f"got {proj['statutory_release_date']}"
    assert proj["earned_good_time_days"] == 0, f"got {proj['earned_good_time_days']}"
    assert proj["projected_release_date"] == "2026-08-09", f"got {proj['projected_release_date']}"


# ---------------------------------------------------------------------------
# combinatorial_formula / earned_good_time_min_max_rate_mode_a
# ---------------------------------------------------------------------------
def test_earned_good_time_forfeit_floors_at_zero(api):
    """PRD §3.8: "A successful uphold moves the infraction from `REPORTED` to `UPHELD`, adds
    its `good_time_forfeit_days` to the booking's `total_forfeited_days`, recomputes the
    booking's earned good-time credit and projected release date, and increments the booking's
    `version`."

    Design: Difficulty/combinatorial_formula/earned_good_time_min_max_rate_mode_a
    """
    booking, infraction = fixtures.setup_classified_with_reported_infraction(
        api, forfeit_days=30, sentence_days=100
    )
    fixtures.uphold_infraction(api, infraction["id"], upholder_user_id="supervisor-1")
    booking_now = get_success_data(api.get_booking(booking["id"], SUPERVISOR))
    assert booking_now["total_forfeited_days"] == 30, (
        f"expected 30, got {booking_now['total_forfeited_days']}"
    )


def test_earned_good_time_clamped_to_zero_projection(api):
    """PRD §3.8: "`earned_good_time_days` is the accrued-minus-forfeited amount but never below
    0 and never above the cap. The `projected_release_date` is the `sentence_start_date`
    advanced by the `sentence_days` minus the `earned_good_time_days`."

    Design: Difficulty/combinatorial_formula/earned_good_time_min_max_rate_mode_a
    """
    booking, infraction = fixtures.setup_classified_with_reported_infraction(
        api, forfeit_days=30, sentence_days=100
    )
    fixtures.uphold_infraction(api, infraction["id"], upholder_user_id="supervisor-1")
    booking_now = get_success_data(api.get_booking(booking["id"], SUPERVISOR))
    assert booking_now["earned_good_time_days"] == 0, (
        f"expected 0 (max(0, min(20, 25-30))), got {booking_now['earned_good_time_days']}"
    )
    assert booking_now["projected_release_date"] == "2026-08-09", (
        f"expected 2026-08-09, got {booking_now['projected_release_date']}"
    )


# ---------------------------------------------------------------------------
# boundary_precision_check / earned_good_time_cap_boundary
# ---------------------------------------------------------------------------
def test_earned_good_time_at_cap_boundary(api):
    """PRD §3.8: "`earned_good_time_days` is the accrued-minus-forfeited amount but never below
    0 and never above the cap." with the cap "the `sentence_days` multiplied by 0.20 and
    floored to whole days".

    Design: Difficulty/boundary_precision_check/earned_good_time_cap_boundary
    """
    booking, infraction = fixtures.setup_classified_with_reported_infraction(
        api, forfeit_days=5, sentence_days=100
    )
    fixtures.uphold_infraction(api, infraction["id"], upholder_user_id="supervisor-1")
    booking_now = get_success_data(api.get_booking(booking["id"], SUPERVISOR))
    assert booking_now["earned_good_time_days"] == 20, (
        f"expected 20 (25-5=20 == cap 20, inclusive), got {booking_now['earned_good_time_days']}"
    )


def test_earned_good_time_cap_boundary_projection(api):
    """PRD §3.8: "The `projected_release_date` is the `sentence_start_date` advanced by the
    `sentence_days` minus the `earned_good_time_days`."

    Design: Difficulty/boundary_precision_check/earned_good_time_cap_boundary
    """
    booking, infraction = fixtures.setup_classified_with_reported_infraction(
        api, forfeit_days=5, sentence_days=100
    )
    fixtures.uphold_infraction(api, infraction["id"], upholder_user_id="supervisor-1")
    booking_now = get_success_data(api.get_booking(booking["id"], SUPERVISOR))
    assert booking_now["projected_release_date"] == "2026-07-20", (
        f"expected 2026-07-20, got {booking_now['projected_release_date']}"
    )


# ---------------------------------------------------------------------------
# transitive_cascade / uphold_forfeit_recompute_release
# ---------------------------------------------------------------------------
def test_uphold_adds_forfeited_days(api):
    """PRD §3.8: "A successful uphold moves the infraction from `REPORTED` to `UPHELD`, adds
    its `good_time_forfeit_days` to the booking's `total_forfeited_days`, recomputes the
    booking's earned good-time credit and projected release date, and increments the booking's
    `version`."

    Design: Difficulty/transitive_cascade/uphold_forfeit_recompute_release
    """
    booking, infraction = fixtures.setup_classified_with_reported_infraction(
        api, forfeit_days=6, sentence_days=100
    )
    fixtures.uphold_infraction(api, infraction["id"], upholder_user_id="supervisor-1")
    booking_now = get_success_data(api.get_booking(booking["id"], SUPERVISOR))
    assert booking_now["total_forfeited_days"] == 6, (
        f"expected 6, got {booking_now['total_forfeited_days']}"
    )


def test_uphold_recomputes_earned_and_projected(api):
    """PRD §3.8: "The earned credit is computed by taking the `sentence_days` multiplied by that
    accrual rate and floored to whole days, subtracting the booking's `total_forfeited_days`,
    and then clamping the result to lie between 0 and a cap".

    Design: Difficulty/transitive_cascade/uphold_forfeit_recompute_release
    """
    booking, infraction = fixtures.setup_classified_with_reported_infraction(
        api, forfeit_days=6, sentence_days=100
    )
    fixtures.uphold_infraction(api, infraction["id"], upholder_user_id="supervisor-1")
    booking_now = get_success_data(api.get_booking(booking["id"], SUPERVISOR))
    assert booking_now["earned_good_time_days"] == 19, (
        f"expected 19 (min(20, 25-6)), got {booking_now['earned_good_time_days']}"
    )
    assert booking_now["projected_release_date"] == "2026-07-21", (
        f"expected 2026-07-21, got {booking_now['projected_release_date']}"
    )


# ---------------------------------------------------------------------------
# validations / release_eligibility (TIME_SERVED)
# ---------------------------------------------------------------------------
def test_time_served_release_before_projected_date_rejected(api):
    """PRD §3.8: "A `TIME_SERVED` release is eligible only when the current date drawn from the
    logical clock has reached or passed the booking's `projected_release_date` ... ; a
    `TIME_SERVED` request before that date is rejected with `ERR_NOT_RELEASE_ELIGIBLE`."

    Design: Corner/validations/release_time_served_before_date_not_eligible
    """
    _inmate, booking = fixtures.create_classified_booking(
        api, sex="MALE", charge_severity="MISDEMEANOR", prior_bookings_count=0, sentence_days=100
    )
    # Clock is at its default 2026-05-01, before projected 2026-07-20.
    resp = api.release_booking(booking["id"], f.release_payload("TIME_SERVED"), SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_NOT_RELEASE_ELIGIBLE.value)


def test_time_served_release_on_projected_date_succeeds(api):
    """PRD §3.8: "the comparison is at day granularity and inclusive of the projected date
    itself" and "Release drives the booking to the terminal `RELEASED`".

    Design: Corner/validations/release_time_served_after_projected_date_succeeds
    """
    _inmate, booking = fixtures.create_classified_booking(
        api, sex="MALE", charge_severity="MISDEMEANOR", prior_bookings_count=0, sentence_days=100
    )
    fixtures.set_clock(api, "2026-07-20T00:00:00Z")  # == projected_release_date, inclusive
    resp = api.release_booking(booking["id"], f.release_payload("TIME_SERVED"), SUPERVISOR)
    data = validate_success(resp)
    assert data["booking_status"] == "RELEASED", f"expected RELEASED, got {data['booking_status']}"
