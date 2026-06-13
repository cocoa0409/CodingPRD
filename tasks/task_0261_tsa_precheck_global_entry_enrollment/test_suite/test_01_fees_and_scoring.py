"""Fee assessment, risk scoring, and redress-offset calculations.

Covers the deterministic numeric rules in PRD §3.2 (fee due), §3.3 (risk score
and effective-score ordering), §3.4 (adjudication bands), and §3.7 (redress
offset). Tests in this file translate difficulty queue A instances for
dual_variant_calc, combinatorial_formula, and boundary_precision_check, plus
corner queue B calculation instances.
"""
from test_helpers import (
    validate_success, get_success_data,
    make_applicant_headers, TEST_USERS,
    pay_payload, background_check_payload, redress_payload,
    appointment_payload, biometric_payload,
    create_application_payload,
    setup_program_and_applicant, setup_submitted_application,
    setup_vetting_application, setup_vetting_with_redress_filed,
    setup_approved_application, get_application, app_version,
    create_program, create_applicant, create_draft_application,
    set_clock,
)

ADMIN = TEST_USERS["scheduling_admin_headers"]
VETTING = TEST_USERS["vetting_officer_headers"]
APPEALS = TEST_USERS["appeals_officer_headers"]
ENROLLMENT = TEST_USERS["enrollment_officer_headers"]


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc
# ---------------------------------------------------------------------------

def test_new_enrollment_fee_is_full_base(api):
    """PRD §3.2: "For a fresh enrollment - one whose `renews_from_application_id`
    is null - the fee owed is the program's full `base_fee_cents`."

    Design: Difficulty/dual_variant_calc/fee_due_new_vs_renewal_on_application
    """
    set_clock()
    program = create_program(base_fee_cents=7800, validity_years=5)
    applicant = create_applicant(full_name="Ada New")
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    submitted = get_success_data(api.submit_application(app["id"], headers))
    assert submitted["fee_due_cents"] == 7800, (
        f"new enrollment fee should be full base 7800, got {submitted['fee_due_cents']}"
    )


def test_renewal_fee_applies_twenty_percent_discount(api):
    """PRD §3.2: "For a renewal, a discount of twenty percent is applied: the fee
    owed is the `base_fee_cents` multiplied by 0.80, with the discount applied to
    the base first and the result then rounded to the nearest whole cent using
    round-half-up."

    Design: Difficulty/dual_variant_calc/fee_due_new_vs_renewal_on_application
    """
    program, applicant, prior, _center, _slot, _appt, _ktn = setup_approved_application(
        program_overrides={"base_fee_cents": 7800, "validity_years": 5}
    )
    # Move clock inside the renewal window (KTN expires 2031-06-09).
    set_clock("2031-03-01T00:00:00Z")
    headers = make_applicant_headers(applicant["id"])
    renewal = create_draft_application(
        applicant["id"], renews_from_application_id=prior["id"]
    )
    submitted = get_success_data(api.submit_application(renewal["id"], headers))
    assert submitted["fee_due_cents"] == 6240, (
        f"renewal fee should be round_half_up(7800*0.80)=6240, got {submitted['fee_due_cents']}"
    )


def test_risk_score_stored_raw_at_creation(api):
    """PRD §3.3: "The raw score is the sum of `criminal_hits` weighted by fifteen,
    `watchlist_hits` weighted by sixty, and `prior_revocations` weighted by
    twenty-five; because the watchlist weight is the largest, watchlist matches
    dominate the score."

    Design: Difficulty/dual_variant_calc/risk_score_raw_vs_post_redress_on_background_check
    """
    program, applicant, app = setup_submitted_application()
    bc = validate_success(
        api.create_background_check(
            app["id"], background_check_payload(criminal_hits=1, watchlist_hits=1),
            VETTING,
        ),
        expected_status=201,
    )
    assert bc["risk_score"] == 75, (
        f"risk_score should be 15*1 + 60*1 = 75, got {bc['risk_score']}"
    )


def test_cleared_redress_subtracts_full_watchlist_weight_from_effective(api):
    """PRD §3.7: "the `resolution` is `CLEARED` and the `risk_offset` removes the
    full watchlist contribution: sixty points for every one of the background
    check's `watchlist_hits`."
    PRD §3.3: "A separate `redress_offset_applied` field on the check starts at 0
    and is later increased only by a cleared redress case (see §3.7)."

    Design: Difficulty/dual_variant_calc/risk_score_raw_vs_post_redress_on_background_check
    """
    program, applicant, app, bc, redress = setup_vetting_with_redress_filed(
        watchlist_hits=1, match_strength_score=20
    )
    # The check was created with criminal_hits=0 watchlist_hits=1 by the helper's
    # background_check_payload override; bring criminal up is unnecessary — risk=60.
    resolved = get_success_data(api.resolve_redress_case(redress["id"], APPEALS))
    assert resolved["resolution"] == "CLEARED"
    assert resolved["risk_offset"] == 60, (
        f"offset should be 60*1 watchlist hit, got {resolved['risk_offset']}"
    )
    final_bc = get_success_data(api.get_background_check(bc["id"], VETTING))
    assert final_bc["risk_score"] == 60, "stored risk_score is unchanged by redress"
    assert final_bc["redress_offset_applied"] == 60, (
        f"redress_offset_applied should be 60, got {final_bc['redress_offset_applied']}"
    )


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula
# ---------------------------------------------------------------------------

def test_risk_score_clamps_raw_above_100(api):
    """PRD §3.3: "The raw sum is then clamped into the inclusive range 0 to 100,
    and that clamped value is stored as `risk_score`."

    Design: Difficulty/combinatorial_formula/risk_score_three_input_weighted_with_clamp
    """
    program, applicant, app = setup_submitted_application()
    bc = validate_success(
        api.create_background_check(
            app["id"], background_check_payload(watchlist_hits=2),
            VETTING,
        ),
        expected_status=201,
    )
    # raw = 60*2 = 120 -> clamp to 100.
    assert bc["risk_score"] == 100, (
        f"raw 120 must clamp to 100, got {bc['risk_score']}"
    )


def test_effective_score_clamps_before_offset_subtraction(api):
    """PRD §3.3: "the weighted raw is computed, then clamped to the range 0 to 100,
    and only then is the redress offset subtracted and the result re-floored at 0.
    Subtracting the offset before clamping would be incorrect."
    PRD §3.4: "If the effective score is at or below the program's
    `vetting_risk_threshold`, the check moves from `PENDING` to `CLEARED`."

    Design: Difficulty/combinatorial_formula/effective_risk_clamp_before_offset_order_pinned
    """
    set_clock()
    program = create_program(
        vetting_risk_threshold=40, vetting_deny_threshold=70, redress_min_score=30
    )
    applicant = create_applicant(full_name="Dan Order")
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    get_success_data(api.pay_application(app["id"], pay_payload(7800), headers))
    get_success_data(api.submit_application(app["id"], headers))
    # raw = 15*4 + 60*1 = 120 -> clamp 100.
    bc = get_success_data(
        api.create_background_check(
            app["id"], background_check_payload(criminal_hits=4, watchlist_hits=1),
            VETTING,
        )
    )
    assert bc["risk_score"] == 100
    redress = get_success_data(
        api.create_redress_case(redress_payload(app["id"], 20), headers)
    )
    resolved = get_success_data(api.resolve_redress_case(redress["id"], APPEALS))
    assert resolved["risk_offset"] == 60
    # effective = clamp(120)=100, then 100-60=40 <= threshold 40 -> CLEARED.
    # Subtract-before-clamp would give 120-60=60 -> NOT cleared.
    adjudicated = get_success_data(api.adjudicate(app["id"], VETTING))
    assert adjudicated["status"] == "CLEARED", (
        f"effective 40 (clamp-then-subtract) must CLEAR, got {adjudicated['status']}"
    )
    assert adjudicated["redress_offset_applied"] == 60


def test_risk_score_three_input_combination(api):
    """PRD §3.3: "The raw score is the sum of `criminal_hits` weighted by fifteen,
    `watchlist_hits` weighted by sixty, and `prior_revocations` weighted by
    twenty-five; because the watchlist weight is the largest, watchlist matches
    dominate the score."

    Design: Difficulty/combinatorial_formula/risk_score_three_input_weighted_with_clamp
    """
    program, applicant, app = setup_submitted_application()
    # criminal 1 + watchlist 1 + revocation 1 = 15 + 60 + 25 = 100 (exactly at cap).
    bc = validate_success(
        api.create_background_check(
            app["id"],
            background_check_payload(criminal_hits=1, watchlist_hits=1, prior_revocations=1),
            VETTING,
        ),
        expected_status=201,
    )
    assert bc["risk_score"] == 100, (
        f"15*1 + 60*1 + 25*1 = 100, got {bc['risk_score']}"
    )


def test_effective_clamp_then_offset_floors_at_zero(api):
    """PRD §3.3: "the weighted raw is computed, then clamped to the range 0 to 100,
    and only then is the redress offset subtracted and the result re-floored at 0."
    PRD §3.4: "If the effective score is at or below the program's
    `vetting_risk_threshold`, the check moves from `PENDING` to `CLEARED`."

    Design: Difficulty/combinatorial_formula/effective_risk_clamp_before_offset_order_pinned
    """
    set_clock()
    program = create_program(
        vetting_risk_threshold=40, vetting_deny_threshold=70, redress_min_score=30
    )
    applicant = create_applicant(full_name="Flo Floor")
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    get_success_data(api.pay_application(app["id"], pay_payload(7800), headers))
    get_success_data(api.submit_application(app["id"], headers))
    # raw = 60*1 = 60 (no clamp needed); redress removes 60 -> effective floored at 0.
    bc = get_success_data(
        api.create_background_check(
            app["id"], background_check_payload(watchlist_hits=1), VETTING
        )
    )
    assert bc["risk_score"] == 60
    redress = get_success_data(
        api.create_redress_case(redress_payload(app["id"], 20), headers)
    )
    resolved = get_success_data(api.resolve_redress_case(redress["id"], APPEALS))
    assert resolved["risk_offset"] == 60
    # effective = 60 - 60 = 0 <= threshold 40 -> CLEARED, offset never drives below 0.
    adjudicated = get_success_data(api.adjudicate(app["id"], VETTING))
    assert adjudicated["status"] == "CLEARED"
    assert adjudicated["redress_offset_applied"] == 60


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check (redress match strength)
# ---------------------------------------------------------------------------

def test_redress_match_strength_equal_to_threshold_clears(api):
    """PRD §3.7: "When the case's `match_strength_score` is at or below
    `redress_min_score`, the match is judged weak - a mis-identification - so the
    `resolution` is `CLEARED` and the `risk_offset` removes the full watchlist
    contribution: sixty points for every one of the background check's
    `watchlist_hits`. The boundary is inclusive: a `match_strength_score` exactly
    equal to `redress_min_score` clears."

    Design: Difficulty/boundary_precision_check/redress_match_strength_equal_threshold_clears
    """
    program, applicant, app, bc, redress = setup_vetting_with_redress_filed(
        watchlist_hits=1, match_strength_score=30,
        program_overrides={"redress_min_score": 30},
    )
    resolved = get_success_data(api.resolve_redress_case(redress["id"], APPEALS))
    assert resolved["resolution"] == "CLEARED", (
        "match_strength_score == redress_min_score must CLEAR (inclusive <=)"
    )
    assert resolved["risk_offset"] == 60
    final_bc = get_success_data(api.get_background_check(bc["id"], VETTING))
    assert final_bc["redress_offset_applied"] == 60


def test_redress_match_strength_above_threshold_confirms(api):
    """PRD §3.7: "When the `match_strength_score` is strictly above
    `redress_min_score`, the match is judged a true one, so the `resolution` is
    `CONFIRMED` and the `risk_offset` is 0."

    Design: Difficulty/boundary_precision_check/redress_match_strength_equal_threshold_clears
    """
    program, applicant, app, bc, redress = setup_vetting_with_redress_filed(
        watchlist_hits=1, match_strength_score=31,
        program_overrides={"redress_min_score": 30},
    )
    resolved = get_success_data(api.resolve_redress_case(redress["id"], APPEALS))
    assert resolved["resolution"] == "CONFIRMED", (
        "match_strength_score 31 > redress_min_score 30 must CONFIRM"
    )
    assert resolved["risk_offset"] == 0
    final_bc = get_success_data(api.get_background_check(bc["id"], VETTING))
    assert final_bc["redress_offset_applied"] == 0


# ---------------------------------------------------------------------------
# Queue B — calculations section
# ---------------------------------------------------------------------------

def test_renewal_fee_discount_applied_corner(api):
    """PRD §3.2: "For a renewal, a discount of twenty percent is applied: the fee
    owed is the `base_fee_cents` multiplied by 0.80, with the discount applied to
    the base first and the result then rounded to the nearest whole cent using
    round-half-up."

    Design: Corner/calculations/renewal_fee_discount_applied
    """
    program, applicant, prior, _center, _slot, _appt, _ktn = setup_approved_application(
        program_overrides={"base_fee_cents": 7800, "validity_years": 5}
    )
    set_clock("2031-03-01T00:00:00Z")
    headers = make_applicant_headers(applicant["id"])
    renewal = create_draft_application(
        applicant["id"], renews_from_application_id=prior["id"]
    )
    submitted = get_success_data(api.submit_application(renewal["id"], headers))
    assert submitted["fee_due_cents"] == 6240


def test_ktn_expiry_five_years_from_issue(api):
    """PRD §3.6: "the `expires_at` is computed as the issuance instant advanced by
    the program's `validity_years` calendar years - the same month and day, except
    that a February-29 issuance maps to February 28 in a non-leap target year."

    Design: Corner/calculations/ktn_expiry_five_years_from_issue
    """
    program, applicant, app, _center, _slot, _appt, ktn = setup_approved_application(
        program_overrides={"validity_years": 5}
    )
    assert ktn["status"] == "ACTIVE"
    assert ktn["expires_at"] == "2031-06-09T12:00:00.000Z", (
        f"issued 2026-06-09T12:00:00Z + 5y must expire 2031-06-09T12:00:00.000Z, "
        f"got {ktn['expires_at']}"
    )


def test_partial_refund_retains_processing_fee(api):
    """PRD §3.8: "While it is in `VETTING` or `INTERVIEW_SCHEDULED`, a partial
    refund is given: the `fee_paid_cents` less a retained processing fee of 1,175
    cents, floored at 0 so it never goes negative."

    Design: Corner/calculations/partial_refund_retains_processing_fee
    """
    program, applicant, app, bc = setup_vetting_application(
        bg_overrides={"criminal_hits": 1}, pay_amount=7800
    )
    headers = make_applicant_headers(applicant["id"])
    version = app_version(app["id"])
    from test_helpers import withdraw_payload
    result = get_success_data(
        api.withdraw_application(app["id"], withdraw_payload(version), headers)
    )
    assert result["status"] == "WITHDRAWN"
    assert result["fee_paid_cents"] == 1175, (
        f"refund 7800-1175=6625; fee_paid_cents should drop to 1175, "
        f"got {result['fee_paid_cents']}"
    )


def test_review_band_routes_to_manual_review(api):
    """PRD §3.4: "If the effective score is strictly greater than
    `vetting_risk_threshold` and strictly less than `vetting_deny_threshold`, the
    check moves from `PENDING` to `REVIEW`, where it awaits a manual decision."

    Design: Corner/calculations/review_band_routes_to_manual_review
    """
    program, applicant, app = setup_submitted_application(
        program_overrides={"vetting_risk_threshold": 40, "vetting_deny_threshold": 70}
    )
    bc = get_success_data(
        api.create_background_check(
            app["id"], background_check_payload(prior_revocations=2), VETTING
        )
    )
    assert bc["risk_score"] == 50, "25*2 prior_revocations = 50"
    adjudicated = get_success_data(api.adjudicate(app["id"], VETTING))
    assert adjudicated["status"] == "REVIEW", (
        "effective 50 (40 < 50 < 70) must route to REVIEW"
    )
    final_app = get_application(app["id"])
    assert final_app["status"] == "VETTING", "application stays VETTING on REVIEW"
