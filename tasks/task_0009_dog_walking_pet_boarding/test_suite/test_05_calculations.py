"""Calculation tests: booking_quote, sitter_payout (provisional vs final),
claim_payout (provisional vs final), sitter_tier_score (pinned rounding
order), tier boundary at SILVER_MIN=40, and the empty-collection list
boundary on GpsTrack.

Covers queue A: dual_variant_calc (2 instances), combinatorial_formula (2
instances), boundary_precision_check (2 instances). Covers queue B
calculations / consistency-model corner instances.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_paginated,
    create_booking_payload,
    create_meet_and_greet_payload,
    create_key_handoff_payload,
    TEST_USERS,
    make_owner_headers,
    make_sitter_headers,
    setup_owner_sitter_pet,
    setup_approved_meet_and_greet,
    setup_confirmed_booking,
    setup_in_progress_booking,
    setup_completed_booking,
    setup_submitted_claim,
    setup_under_review_claim,
    setup_approved_claim,
    pin_clock,
    register_owner,
    register_sitter,
    create_pet,
    setup_cleared_sitter,
)


PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CLAIMS_ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ---- Queue A: dual_variant_calc — sitter_payout provisional vs final --------

def test_sitter_payout_provisional_and_final_diverge_with_tip(api):
    """PRD §3.6: "The `sitter_payout` calculation has two variants. Both
    share the platform-fee derivation: `platform_fee_cents` is the
    booking's `booking_quote_cents` multiplied by the platform-fee rate
    of `0.15` and rounded half-up to the nearest cent. The provisional
    variant — fired at confirmation, when tip and incident inputs are
    not yet known — sets `provisional_sitter_payout_cents` to
    `booking_quote_cents` minus `platform_fee_cents`. The final variant
    — fired at completion — adds `tip_cents`, subtracts
    `incident_deduction_cents`, and floors the result at zero:
    `final_sitter_payout_cents` is the maximum of zero and the quantity
    (`booking_quote_cents` minus `platform_fee_cents`) plus `tip_cents`
    minus `incident_deduction_cents`."

    Design: Difficulty/dual_variant_calc/sitter_payout_provisional_vs_final_on_booking
    """
    # WALK_60MIN BRONZE STANDARD NONE → booking_quote = 3500 cents.
    # platform_fee = round(3500 * 0.15) = round(525.0) = 525.
    # provisional = 3500 - 525 = 2975.
    # final with tip=300, incident=0: max(0, (3500-525) + 300 - 0) = 3275.
    owner, sitter, pet, mg, booking, kh = setup_completed_booking(
        clock_iso="2026-06-01T08:00:00Z",
        mg_scheduled_at="2026-06-01T07:30:00Z",
        booking_start_at="2026-06-01T09:00:00Z",
        booking_end_at="2026-06-01T10:00:00Z",
        service_type="WALK_60MIN", time_of_day="STANDARD",
        recurring_cadence="NONE",
        tip_cents=300, incident_deduction_cents=0, owner_rating=5,
    )
    assert booking["status"] == "COMPLETED"
    assert booking["booking_quote_cents"] == 3500
    assert booking["provisional_sitter_payout_cents"] == 2975
    assert booking["final_sitter_payout_cents"] == 3275
    assert booking["final_sitter_payout_cents"] != booking["provisional_sitter_payout_cents"]


def test_sitter_payout_final_with_incident_can_fall_below_provisional(api):
    """PRD §3.6: "The two variants may diverge in either direction — a
    generous tip raises the final payout above the provisional, while a
    significant incident deduction may drop it below, possibly to zero."

    The same dual-variant invariant, exercised on the negative side: an
    incident_deduction larger than the platform-fee-net amount drops the
    final to zero. The two variants must still diverge after a COMPLETE
    that involves a non-zero incident deduction.

    Design: Difficulty/dual_variant_calc/sitter_payout_provisional_vs_final_on_booking
    """
    # WALK_60MIN BRONZE STANDARD NONE: quote=3500, provisional=2975.
    # With incident_deduction=5000: final = max(0, 2975 + 0 - 5000) = 0.
    owner, sitter, pet, mg, booking, kh = setup_completed_booking(
        clock_iso="2026-06-01T08:00:00Z",
        mg_scheduled_at="2026-06-01T07:30:00Z",
        booking_start_at="2026-06-01T09:00:00Z",
        booking_end_at="2026-06-01T10:00:00Z",
        service_type="WALK_60MIN", time_of_day="STANDARD", recurring_cadence="NONE",
        tip_cents=0, incident_deduction_cents=5000, owner_rating=3,
    )
    assert booking["booking_quote_cents"] == 3500
    assert booking["provisional_sitter_payout_cents"] == 2975
    assert booking["final_sitter_payout_cents"] == 0
    assert booking["final_sitter_payout_cents"] < booking["provisional_sitter_payout_cents"]


# ---- Queue A: dual_variant_calc — claim_payout provisional vs final ---------

def test_claim_payout_provisional_uses_claim_amount_then_final_uses_approved_amount(api):
    """PRD §3.8: "The provisional variant uses the owner-declared
    `claim_amount_cents`; the final variant uses the adjuster-set
    `approved_amount_cents`."
    PRD §3.8: "In both variants the formula is the same: first take the
    minimum of the relevant amount and the maximum payout of `500000`
    (so a runaway claim is capped at the platform limit), then subtract
    the tier-specific deductible from the constants table (keyed on
    `sitter_tier_snapshot`, not the current `Sitter.tier`), then take
    the maximum of zero and that difference."
    PRD §3.8: "The `claim_payout` calculation uses a tier-keyed
    deductible table — `10000` cents for `BRONZE`, `5000` cents for
    `SILVER`, `2500` cents for `GOLD` — and a single platform-wide
    maximum payout of `500000` cents."

    Design: Difficulty/dual_variant_calc/claim_payout_provisional_vs_final_on_insurance_claim
    """
    # Sitter is BRONZE (fresh defaults are BRONZE/tier_score=10).
    # claim_amount_cents=15000, BRONZE deductible=10000 → provisional = 5000.
    # approved_amount_cents=12000, BRONZE deductible=10000 → final = 2000.
    # File claim against IN_PROGRESS booking so the sitter has 0 completed
    # bookings — no tier_score recompute event has fired, sitter_tier remains
    # BRONZE/10 (its registration default). Filing a claim itself does not
    # trigger sitter_tier_score recompute (only completion and claim payment do
    # per PRD §3.7), so sitter_tier_snapshot pinned at submit must be BRONZE.
    owner, sitter, pet, mg, booking, kh, claim = setup_approved_claim(
        claim_amount_cents=15000,
        approved_amount_cents=12000,
        booking_phase="in_progress",
        completed_kwargs={"clock_iso": "2026-06-01T08:00:00Z",
                          "mg_scheduled_at": "2026-06-01T07:30:00Z",
                          "booking_start_at": "2026-06-01T09:00:00Z",
                          "booking_end_at": "2026-06-01T10:00:00Z"},
    )
    assert claim["status"] == "APPROVED"
    assert claim["sitter_tier_snapshot"] == "BRONZE"
    assert claim["provisional_payout_cents"] == 5000
    assert claim["final_payout_cents"] == 2000
    # Final must not exceed provisional — PRD: "the final claim payout is
    # always less than or equal to the provisional payout."
    assert claim["final_payout_cents"] <= claim["provisional_payout_cents"]


def test_claim_payout_final_at_submit_is_zero_before_approval(api):
    """PRD §3.8: "The claim's `provisional_payout_cents` is computed via
    the provisional variant of `claim_payout`. `approved_amount_cents`
    is null, `final_payout_cents` is 0, `adjuster_notes` defaults to
    the empty string when omitted at intake, and `denied_reason` is null."

    A complementary aspect of the dual-variant claim: at SUBMIT, only the
    provisional variant has fired — final_payout_cents starts at 0 and
    approved_amount_cents at null. Different variant timing, same
    InsuranceClaim domain.

    Design: Difficulty/dual_variant_calc/claim_payout_provisional_vs_final_on_insurance_claim
    """
    # File claim against IN_PROGRESS booking so total_completed_bookings stays
    # at 0 and no sitter_tier_score recompute has fired — sitter stays BRONZE
    # (registration default tier_score=10). sitter_tier_snapshot pinned at
    # submit is BRONZE, deductible 10000.
    owner, sitter, pet, mg, booking, kh, claim = setup_submitted_claim(
        claim_amount_cents=15000,
        booking_phase="in_progress",
        completed_kwargs={"clock_iso": "2026-06-01T08:00:00Z",
                          "mg_scheduled_at": "2026-06-01T07:30:00Z",
                          "booking_start_at": "2026-06-01T09:00:00Z",
                          "booking_end_at": "2026-06-01T10:00:00Z"},
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["provisional_payout_cents"] == 5000  # BRONZE: max(0, 15000-10000)
    assert claim["final_payout_cents"] == 0
    assert claim["approved_amount_cents"] is None


# ---- Queue A: combinatorial_formula — booking_quote three-input mode (a) ----

def test_booking_quote_bronze_walk60_standard_none_yields_3500(api):
    """PRD §3.4: "The base rate, in cents, is `2000` for `WALK_30MIN`,
    `3500` for `WALK_60MIN`, `8000` for `BOARDING_OVERNIGHT`, and `5000`
    for `DAYCARE`."
    PRD §3.4: "The tier multiplier is `1.00` for `BRONZE`, `1.15` for
    `SILVER`, and `1.30` for `GOLD`, snapshotted from the sitter's
    current `tier` at compute time."
    PRD §3.4: "The time-of-day factor is `1.00` for `STANDARD`, `1.20`
    for `PEAK`, and `1.30` for `OVERNIGHT`."
    PRD §3.4: "The recurring discount is `0.00` for `NONE`, `0.10` for
    `WEEKLY`, and `0.05` for `BIWEEKLY` — note that `BIWEEKLY` carries
    a smaller discount than `WEEKLY` because every-other-week recurrence
    is less valuable to the platform than weekly recurrence."

    Design: Difficulty/combinatorial_formula/booking_quote_three_inputs_nonlinear_mode_a
    """
    # BRONZE * WALK_60MIN * STANDARD * NONE:
    # step1 = round(3500 * 1.00) = 3500
    # step2 = round(3500 * 1.00) = 3500
    # discount = round(3500 * 0.00) = 0
    # quote = 3500 - 0 + 0 = 3500.
    owner, sitter, pet, mg = setup_approved_meet_and_greet(
        clock_iso="2026-06-02T08:00:00Z", mg_scheduled_at="2026-06-02T07:30:00Z",
    )
    booking = validate_success(api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet["id"],
                                "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z",
                                service_type="WALK_60MIN", time_of_day="STANDARD",
                                recurring_cadence="NONE"),
        make_owner_headers(owner["id"]),
    ), expected_status=201)
    assert booking["booking_quote_cents"] == 3500


def test_booking_quote_bronze_boarding_overnight_weekly_yields_9360(api):
    """PRD §3.4: "The calculation proceeds in this exact order: first,
    the base rate in cents is multiplied by the tier multiplier and
    rounded half-up to the nearest cent to produce the first
    intermediate; second, that intermediate is multiplied by the
    time-of-day factor and rounded half-up to the nearest cent to
    produce the second intermediate; third, the discount amount in cents
    is the second intermediate multiplied by the recurring discount rate
    and rounded half-up to the nearest cent; finally, the booking's
    `booking_quote_cents` is the second intermediate minus the discount
    amount, plus the caller-supplied `emergency_surcharge_cents`."

    Same Sitter (BRONZE) but DIFFERENT (service_type, time_of_day,
    recurring_cadence) inputs produce a non-linearly-divergent quote.

    Design: Difficulty/combinatorial_formula/booking_quote_three_inputs_nonlinear_mode_a
    """
    # BRONZE * BOARDING_OVERNIGHT * OVERNIGHT * WEEKLY:
    # step1 = round(8000 * 1.00) = 8000
    # step2 = round(8000 * 1.30) = 10400
    # discount = round(10400 * 0.10) = 1040
    # quote = 10400 - 1040 + 0 = 9360.
    owner, sitter, pet, mg = setup_approved_meet_and_greet(
        clock_iso="2026-06-03T08:00:00Z", mg_scheduled_at="2026-06-03T07:30:00Z",
    )
    booking = validate_success(api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet["id"],
                                "2026-06-03T20:00:00Z", "2026-06-04T08:00:00Z",
                                service_type="BOARDING_OVERNIGHT",
                                time_of_day="OVERNIGHT", recurring_cadence="WEEKLY"),
        make_owner_headers(owner["id"]),
    ), expected_status=201)
    assert booking["booking_quote_cents"] == 9360


# ---- Queue A: combinatorial_formula — sitter_tier_score rounding-order ------

def test_sitter_tier_score_pinned_rounding_yields_40_after_first_rated_booking(api):
    """PRD §3.7: "When `total_rating_count` is zero, the rating component
    is the neutral default of `60` (representing roughly a 3-star
    average on the 0-to-100 scale used here). Otherwise, the
    floating-point average rating is `total_rating_sum` divided by
    `total_rating_count`, that average is multiplied by `20` to project
    the 1-to-5 rating into the 0-to-100 score range, and the result is
    rounded half-up to an integer — this is the first pinned round."
    PRD §3.7: "The components are combined as follows. The weighted sum
    is the rating component times the rating weight (`0.5`), plus the
    bookings component times the bookings weight (`0.3`), plus the
    additive base of `10`. The weighted sum is rounded half-up to an
    integer — this is the second pinned round. The penalty is then
    subtracted, and the final `tier_score` is the maximum of zero and
    that difference."

    Design: Difficulty/combinatorial_formula/sitter_tier_score_rounding_order_matters_mode_b
    """
    # After one COMPLETED booking with owner_rating=3:
    # avg = 3/1 = 3.0; rating_score = round(3.0 * 20) = 60.
    # bookings_score = min(1, 40) = 1.
    # weighted_sum = 60 * 0.5 + 1 * 0.3 + 10 = 30 + 0.3 + 10 = 40.3.
    # raw = round(40.3) = 40.
    # claim_penalty = 0.
    # tier_score = max(0, 40 - 0) = 40 → SILVER.
    owner, sitter, pet, mg, booking, kh = setup_completed_booking(
        clock_iso="2026-06-04T08:00:00Z",
        mg_scheduled_at="2026-06-04T07:30:00Z",
        booking_start_at="2026-06-04T09:00:00Z",
        booking_end_at="2026-06-04T09:30:00Z",
        service_type="WALK_30MIN", owner_rating=3,
    )
    s_after = validate_success(api.get_sitter(sitter["id"], PLATFORM_ADMIN), 200)
    assert s_after["total_completed_bookings"] == 1
    assert s_after["total_rating_sum"] == 3
    assert s_after["total_rating_count"] == 1
    assert s_after["tier_score"] == 40
    assert s_after["tier"] == "SILVER"


def test_sitter_tier_score_neutral_default_when_no_ratings(api):
    """PRD §3.7: "When `total_rating_count` is zero, the rating component
    is the neutral default of `60` (representing roughly a 3-star average
    on the 0-to-100 scale used here)."
    PRD §3.7: "The weighted sum is the rating component times the rating
    weight (`0.5`), plus the bookings component times the bookings
    weight (`0.3`), plus the additive base of `10`. The weighted sum is
    rounded half-up to an integer — this is the second pinned round.
    The penalty is then subtracted, and the final `tier_score` is the
    maximum of zero and that difference."

    Different code path through the same formula (the no-rating branch
    of mode-b nested rounding). After one COMPLETED booking with
    owner_rating=null:
      rating_score = 60 (neutral default, no first round).
      bookings_score = min(1, 40) = 1.
      weighted_sum = 60*0.5 + 1*0.3 + 10 = 40.3 → round to 40.
      tier_score = max(0, 40 - 0) = 40 → SILVER.

    Design: Difficulty/combinatorial_formula/sitter_tier_score_rounding_order_matters_mode_b
    """
    owner, sitter, pet, mg, booking, kh = setup_completed_booking(
        clock_iso="2026-06-04T08:00:00Z",
        mg_scheduled_at="2026-06-04T07:30:00Z",
        booking_start_at="2026-06-04T09:00:00Z",
        booking_end_at="2026-06-04T09:30:00Z",
        service_type="WALK_30MIN", owner_rating=None,
    )
    s_after = validate_success(api.get_sitter(sitter["id"], PLATFORM_ADMIN), 200)
    assert s_after["total_completed_bookings"] == 1
    assert s_after["total_rating_count"] == 0
    # neutral 60 used: weighted_sum = 60*0.5 + 1*0.3 + 10 = 40.3 → 40 → SILVER.
    assert s_after["tier_score"] == 40
    assert s_after["tier"] == "SILVER"


# ---- Queue A: boundary_precision_check — tier_score == SILVER_MIN ----------

def test_tier_score_exactly_at_silver_min_is_silver(api):
    """PRD §3.7: "The derived `tier` is `GOLD` when `tier_score` is at
    least `70`, `SILVER` when `tier_score` is at least `40` and below
    `70`, and `BRONZE` otherwise."

    Design: Difficulty/boundary_precision_check/tier_score_exactly_40_silver_boundary
    """
    # Same setup as sitter_tier_score_pinned_rounding test: 1 booking,
    # owner_rating=3 → tier_score = 40 == SILVER_MIN → tier == SILVER.
    owner, sitter, pet, mg, booking, kh = setup_completed_booking(
        clock_iso="2026-06-09T08:00:00Z",
        mg_scheduled_at="2026-06-09T07:30:00Z",
        booking_start_at="2026-06-09T09:00:00Z",
        booking_end_at="2026-06-09T09:30:00Z",
        service_type="WALK_30MIN", owner_rating=3,
    )
    s_after = validate_success(api.get_sitter(sitter["id"], PLATFORM_ADMIN), 200)
    assert s_after["tier_score"] == 40
    assert s_after["tier"] == "SILVER"


def test_tier_score_below_silver_min_is_bronze(api):
    """PRD §3.7: "The derived `tier` is `GOLD` when `tier_score` is at
    least `70`, `SILVER` when `tier_score` is at least `40` and below
    `70`, and `BRONZE` otherwise."

    The boundary's other side: when `tier_score` is strictly below 40
    (the SILVER threshold), the tier must be BRONZE. Using owner_rating=2:
      avg = 2.0; rating_score = round(2.0 * 20) = 40.
      bookings_score = min(1, 40) = 1.
      weighted_sum = 40*0.5 + 1*0.3 + 10 = 30.3 → round → 30.
      tier_score = max(0, 30 - 0) = 30 < SILVER_MIN(40) → BRONZE.

    Design: Difficulty/boundary_precision_check/tier_score_exactly_40_silver_boundary
    """
    owner, sitter, pet, mg, booking, kh = setup_completed_booking(
        clock_iso="2026-06-09T08:00:00Z",
        mg_scheduled_at="2026-06-09T07:30:00Z",
        booking_start_at="2026-06-09T09:00:00Z",
        booking_end_at="2026-06-09T09:30:00Z",
        service_type="WALK_30MIN", owner_rating=2,
    )
    s_after = validate_success(api.get_sitter(sitter["id"], PLATFORM_ADMIN), 200)
    assert s_after["tier_score"] == 30
    assert s_after["tier"] == "BRONZE"


# ---- Queue A: boundary_precision_check — empty GpsTrack list ----------------

def test_gps_tracks_list_empty_for_never_started_booking(api):
    """PRD §2.3: "All list endpoints accept two query parameters, `limit`
    and `offset`."
    PRD §2.3: "The pagination block in `meta` exposes the four pagination
    fields `limit`, `offset`, `total_count` (the total number of records
    that satisfy the request's filters, irrespective of pagination), and
    `has_more` (a boolean that is true exactly when
    `offset + limit < total_count`)."
    PRD §3.5: "During an `IN_PROGRESS` booking, the sitter may append GPS
    samples one at a time; each sample carries the `booking_id`, a
    `latitude` between -90 and 90 in decimal degrees, a `longitude`
    between -180 and 180 in decimal degrees, and the `recorded_at`
    instant of the sample."

    The empty-collection boundary: a booking that has never reached
    IN_PROGRESS has zero GpsTrack rows, and the list endpoint must return
    an empty array with total_count==0 and has_more==false.

    Design: Difficulty/boundary_precision_check/gps_tracks_empty_list_for_unstarted_booking_endpoint
    """
    owner, sitter, pet, mg, booking = setup_confirmed_booking(
        clock_iso="2026-06-10T08:00:00Z",
        mg_scheduled_at="2026-06-10T07:30:00Z",
        booking_start_at="2026-06-10T09:00:00Z",
        booking_end_at="2026-06-10T10:00:00Z",
    )
    assert booking["status"] == "CONFIRMED"
    res = api.list_gps_tracks(make_owner_headers(owner["id"]),
                               params={"booking_id": booking["id"]})
    data, meta = validate_paginated(res)
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_gps_tracks_list_has_one_after_single_in_progress_post(api):
    """PRD §3.5: "During an `IN_PROGRESS` booking, the sitter may append
    GPS samples one at a time; each sample carries the `booking_id`, a
    `latitude` between -90 and 90 in decimal degrees, a `longitude`
    between -180 and 180 in decimal degrees, and the `recorded_at`
    instant of the sample."

    Complement of the empty-list boundary: after exactly one GPS write
    on an IN_PROGRESS booking, the collection cardinality is 1 and
    has_more is false at the default page size.

    Design: Difficulty/boundary_precision_check/gps_tracks_empty_list_for_unstarted_booking_endpoint
    """
    owner, sitter, pet, mg, booking, kh = setup_in_progress_booking(
        clock_iso="2026-06-10T08:00:00Z",
        mg_scheduled_at="2026-06-10T07:30:00Z",
        booking_start_at="2026-06-10T09:00:00Z",
        booking_end_at="2026-06-10T10:00:00Z",
    )
    # Post one GPS sample.
    validate_success(api.create_gps_track(
        {"booking_id": booking["id"], "latitude": 40.7128,
         "longitude": -74.0060, "recorded_at": "2026-06-10T09:05:00Z"},
        make_sitter_headers(sitter["id"]),
    ), expected_status=201)
    res = api.list_gps_tracks(make_owner_headers(owner["id"]),
                               params={"booking_id": booking["id"]})
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ---- Queue B: corner — booking_quote / sitter_payout / claim_payout ---------

def test_booking_quote_walk30_bronze_standard_none_yields_2000(api):
    """PRD §3.4: "The base rate, in cents, is `2000` for `WALK_30MIN`,
    `3500` for `WALK_60MIN`, `8000` for `BOARDING_OVERNIGHT`, and `5000`
    for `DAYCARE`."
    PRD §3.4: "The recurring discount is `0.00` for `NONE`, `0.10` for
    `WEEKLY`, and `0.05` for `BIWEEKLY` — note that `BIWEEKLY` carries
    a smaller discount than `WEEKLY` because every-other-week recurrence
    is less valuable to the platform than weekly recurrence."

    Design: Corner/calculations/booking_quote_below_deductible_recurring_zero_discount
    """
    # WALK_30MIN BRONZE STANDARD NONE: base 2000 * 1.00 = 2000; * 1.00 = 2000;
    # discount 0; surcharge 0 → 2000.
    owner, sitter, pet, mg = setup_approved_meet_and_greet(
        clock_iso="2026-06-24T08:00:00Z", mg_scheduled_at="2026-06-24T07:30:00Z",
    )
    booking = validate_success(api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet["id"],
                                "2026-06-24T09:00:00Z", "2026-06-24T09:30:00Z",
                                service_type="WALK_30MIN", time_of_day="STANDARD",
                                recurring_cadence="NONE"),
        make_owner_headers(owner["id"]),
    ), expected_status=201)
    assert booking["booking_quote_cents"] == 2000


def test_booking_quote_with_peak_and_surcharge(api):
    """PRD §3.4: "the booking's `booking_quote_cents` is the second
    intermediate minus the discount amount, plus the caller-supplied
    `emergency_surcharge_cents`."
    PRD §3.4: "The time-of-day factor is `1.00` for `STANDARD`, `1.20`
    for `PEAK`, and `1.30` for `OVERNIGHT`."

    Design: Corner/calculations/booking_quote_with_peak_and_surcharge_constants_applied
    """
    # WALK_30MIN BRONZE PEAK NONE + surcharge=500:
    # step1 = 2000 * 1.00 = 2000
    # step2 = 2000 * 1.20 = 2400
    # discount = 0
    # quote = 2400 + 500 = 2900.
    owner, sitter, pet, mg = setup_approved_meet_and_greet(
        clock_iso="2026-06-25T08:00:00Z", mg_scheduled_at="2026-06-25T07:30:00Z",
    )
    booking = validate_success(api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet["id"],
                                "2026-06-25T09:00:00Z", "2026-06-25T09:30:00Z",
                                service_type="WALK_30MIN", time_of_day="PEAK",
                                recurring_cadence="NONE",
                                emergency_surcharge_cents=500),
        make_owner_headers(owner["id"]),
    ), expected_status=201)
    assert booking["booking_quote_cents"] == 2900


def test_claim_payout_below_deductible_floors_at_zero(api):
    """PRD §3.8: "In both variants the formula is the same: first take
    the minimum of the relevant amount and the maximum payout of
    `500000` (so a runaway claim is capped at the platform limit), then
    subtract the tier-specific deductible from the constants table
    (keyed on `sitter_tier_snapshot`, not the current `Sitter.tier`),
    then take the maximum of zero and that difference."
    PRD §3.8: "The `claim_payout` calculation uses a tier-keyed
    deductible table — `10000` cents for `BRONZE`, `5000` cents for
    `SILVER`, `2500` cents for `GOLD` — and a single platform-wide
    maximum payout of `500000` cents."

    Design: Corner/calculations/claim_payout_below_deductible_floors_at_zero
    """
    # BRONZE deductible=10000; claim_amount=4000 →
    #   provisional = max(0, min(4000, 500000) - 10000) = max(0, -6000) = 0.
    # File claim against IN_PROGRESS booking so total_completed_bookings stays
    # 0 and no sitter_tier_score recompute has fired — sitter remains BRONZE.
    owner, sitter, pet, mg, booking, kh, claim = setup_submitted_claim(
        claim_amount_cents=4000,
        booking_phase="in_progress",
        completed_kwargs={"clock_iso": "2026-06-26T08:00:00Z",
                          "mg_scheduled_at": "2026-06-26T07:30:00Z",
                          "booking_start_at": "2026-06-26T09:00:00Z",
                          "booking_end_at": "2026-06-26T10:00:00Z"},
    )
    assert claim["sitter_tier_snapshot"] == "BRONZE"
    assert claim["provisional_payout_cents"] == 0


def test_sitter_payout_provisional_for_boarding_overnight_bronze_yields_8840(api):
    """PRD §3.6: "`platform_fee_cents` is the booking's
    `booking_quote_cents` multiplied by the platform-fee rate of `0.15`
    and rounded half-up to the nearest cent. The provisional variant —
    fired at confirmation, when tip and incident inputs are not yet
    known — sets `provisional_sitter_payout_cents` to
    `booking_quote_cents` minus `platform_fee_cents`."

    Design: Corner/calculations/sitter_payout_provisional_with_rounding
    """
    # BRONZE BOARDING_OVERNIGHT OVERNIGHT NONE:
    # step1 = 8000 * 1.00 = 8000; step2 = 8000 * 1.30 = 10400; discount 0;
    # quote = 10400. platform_fee = round(10400 * 0.15) = round(1560.0) = 1560.
    # provisional = 10400 - 1560 = 8840.
    owner, sitter, pet, mg, booking = setup_confirmed_booking(
        clock_iso="2026-06-27T08:00:00Z",
        mg_scheduled_at="2026-06-27T07:30:00Z",
        booking_start_at="2026-06-27T20:00:00Z",
        booking_end_at="2026-06-28T08:00:00Z",
        service_type="BOARDING_OVERNIGHT",
        time_of_day="OVERNIGHT",
        recurring_cadence="NONE",
    )
    assert booking["booking_quote_cents"] == 10400
    assert booking["provisional_sitter_payout_cents"] == 8840


def test_booking_quote_present_on_create_response(api):
    """PRD §3.4: "On a successful create, the booking is persisted with
    `status` `REQUESTED`, `booking_quote_cents` set to the computed
    quote, `provisional_sitter_payout_cents` and
    `final_sitter_payout_cents` initialised to 0, `tip_cents` and
    `incident_deduction_cents` initialised to 0, `owner_rating`
    initialised to null, and `cancellation_reason` initialised to null."
    PRD §2.4: "an integer `version` field that starts at 1 on creation
    and increments by exactly 1 on every mutation that changes the row."

    Design: Corner/consistency_model/immediate_consistency_booking_quote_visible_on_create_response
    """
    # WALK_60MIN BRONZE STANDARD NONE → 3500 immediately on the create
    # response (no eventual-consistency delay).
    owner, sitter, pet, mg = setup_approved_meet_and_greet(
        clock_iso="2026-07-06T08:00:00Z", mg_scheduled_at="2026-07-06T07:30:00Z",
    )
    booking = validate_success(api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet["id"],
                                "2026-07-06T09:00:00Z", "2026-07-06T10:00:00Z",
                                service_type="WALK_60MIN", time_of_day="STANDARD",
                                recurring_cadence="NONE"),
        make_owner_headers(owner["id"]),
    ), expected_status=201)
    assert booking["booking_quote_cents"] == 3500
    assert booking["version"] == 1
