"""Size-recommendation algorithm, measurement range, versioning, and OCC on re-fit.

Covers queue-A combinatorial_formula (size branch selection) and several queue-B
calculation / cross-cutting instances driven by the fit endpoint.
"""
from test_helpers import (
    validate_success, validate_error,
    create_fit_payload,
    ApiErrorId,
    make_fitter_headers,
    setup_checked_in_appointment, setup_booked_appointment,
)


def test_size_recommendation_standard_branch_30d(api):
    """PRD §3.2: "for STANDARD, round the half-band to the nearest whole number using
    round-half-up and double it."
    PRD §3.2: "the cup index selects recommended_cup by position, where 1 is A, 2 is
    B, 3 is C, 4 is D, 5 is E, 6 is F, 7 is G, and 8 is H."
    PRD §3.2: "The recommended_size is the recommended_band written immediately before
    the recommended_cup letter, for example 30D."

    Design: Difficulty/combinatorial_formula/size_algo_three_input_branch
    """
    ctx = setup_checked_in_appointment()
    res = api.fit_appointment(
        ctx["appointment"]["id"],
        create_fit_payload(76, 84, ctx["version"], fit_preference="STANDARD"),
        make_fitter_headers(ctx["fitter"]["id"]),
    )
    fitted = validate_success(res, 200)
    assert fitted["recommended_band"] == 30, fitted
    assert fitted["recommended_cup"] == "D", fitted
    assert fitted["recommended_size"] == "30D", fitted


def test_size_recommendation_relaxed_branch_rounds_up(api):
    """PRD §3.2: "for RELAXED, round the half-band up to the nearest whole number and
    double it"
    PRD §3.2: "The recommended_size is the recommended_band written immediately before
    the recommended_cup letter, for example 30D."

    Design: Difficulty/combinatorial_formula/size_algo_three_input_branch
    """
    ctx = setup_checked_in_appointment()
    res = api.fit_appointment(
        ctx["appointment"]["id"],
        create_fit_payload(77, 85, ctx["version"], fit_preference="RELAXED"),
        make_fitter_headers(ctx["fitter"]["id"]),
    )
    fitted = validate_success(res, 200)
    # 77 / 2.54 = 30.31 -> half 15.16 -> ceil 16 -> band 32 (STANDARD would round to 30).
    assert fitted["recommended_band"] == 32, fitted
    assert fitted["recommended_size"] == "32D", fitted


def test_size_recommendation_snug_branch_rounds_down(api):
    """PRD §3.2: "for SNUG, round the half-band down to the nearest whole number and
    double it"

    Design: Corner/calculations/size_snug_branch_rounds_down
    """
    ctx = setup_checked_in_appointment()
    res = api.fit_appointment(
        ctx["appointment"]["id"],
        create_fit_payload(79, 90, ctx["version"], fit_preference="SNUG"),
        make_fitter_headers(ctx["fitter"]["id"]),
    )
    fitted = validate_success(res, 200)
    # 79 / 2.54 = 31.10 -> half 15.55 -> floor 15 -> band 30 (STANDARD would give 32).
    assert fitted["recommended_band"] == 30, fitted


def test_fit_measurement_out_of_range_rejected(api):
    """PRD §3.2: "Measurements must lie within range — underbust_cm from 55 to 120 and
    bust_cm from 60 to 170 — or the submission is rejected with
    ERR_MEASUREMENT_OUT_OF_RANGE."

    Design: Corner/calculations/measurement_out_of_range_on_fit
    """
    ctx = setup_checked_in_appointment()
    res = api.fit_appointment(
        ctx["appointment"]["id"],
        create_fit_payload(200, 210, ctx["version"], fit_preference="STANDARD"),
        make_fitter_headers(ctx["fitter"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_MEASUREMENT_OUT_OF_RANGE)


def test_refit_with_stale_version_rejected(api):
    """PRD §2.4: "If expected_appointment_version does not equal the appointment's
    current version — because another re-fit has already advanced it — the submission
    is rejected with ERR_STALE_APPOINTMENT_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_appointment_version_on_refit
    """
    ctx = setup_checked_in_appointment()
    stale_version = ctx["version"]
    # First fit succeeds and advances the appointment version.
    first = validate_success(
        api.fit_appointment(
            ctx["appointment"]["id"],
            create_fit_payload(76, 84, stale_version, fit_preference="STANDARD"),
            make_fitter_headers(ctx["fitter"]["id"]),
        ),
        200,
    )
    assert first["version"] == stale_version + 1
    # Second fit carrying the pre-fit (now stale) version is rejected.
    res = api.fit_appointment(
        ctx["appointment"]["id"],
        create_fit_payload(77, 85, stale_version, fit_preference="STANDARD"),
        make_fitter_headers(ctx["fitter"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_APPOINTMENT_VERSION)


def test_appointment_version_increments_on_confirm(api):
    """PRD §2.4: "version is an integer that starts at 1 and increments by one on
    every mutation of the resource; it underpins optimistic concurrency control."

    Design: Corner/cross_cutting_complexity_layers/appointment_version_increments_on_mutation
    """
    ctx = setup_booked_appointment()
    assert ctx["appointment"]["version"] == 1, ctx["appointment"]
    confirmed = validate_success(
        api.confirm_appointment(
            ctx["appointment"]["id"], make_fitter_headers(ctx["fitter"]["id"])
        ),
        200,
    )
    assert confirmed["version"] == 2, confirmed
