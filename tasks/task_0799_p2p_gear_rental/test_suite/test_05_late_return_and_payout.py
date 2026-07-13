"""Late-return detection, return settlement (provisional vs final), payouts and release gating."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, make_renter_headers,
    platform_headers as _platform_headers,
    create_owner, create_verified_renter, create_active_listing, create_requested_booking,
    setup_active_booking, setup_returned_booking, setup_open_claim, setup_claim_under_review,
    schedule_and_complete_handoff, add_condition_report,
)


# --- Late fee: round-per-day-then-sum (Difficulty/combinatorial_formula) ------

def _late_booking(api, owner_email, renter_email, base_rate, late_to):
    sc = setup_active_booking(api, base_daily_rate_cents=base_rate, quantity=1)
    api.set_clock({"to_iso8601": late_to}, _platform_headers())
    api.detect_late_returns(_platform_headers())
    return sc, get_success_data(api.get_booking(sc["booking_id"], sc["owner_headers"]))


def test_late_fee_rounds_per_day_then_multiplies(api):
    """PRD §3.6: "The late fee accrual rule computes a per-day penalty as the listing's
    base_daily_rate_cents multiplied by 15000 basis points divided by 10000 (one hundred
    fifty percent of the base daily rate), rounded to whole cents using round half up
    exactly once; late_fee_cents is then that rounded per-day penalty multiplied by
    late_days."

    Design: Difficulty/combinatorial_formula/late_fee_round_per_day_then_sum_mode_b
    """
    sc, booking = _late_booking(api, "owner_lf_a@x.com", "renter_lf_a@x.com", 333,
                                "2026-06-11T00:00:00Z")
    assert booking["late_fee_cents"] == 1500, booking["late_fee_cents"]


def test_late_sweep_sets_status_and_late_days(api):
    """PRD §3.6: "the Platform-driven late-return sweep marks it late, transitioning
    ACTIVE → LATE. On that transition the system sets late_days to the number of whole
    days between the booking's end_date and the current logical clock ..."

    Design: Difficulty/combinatorial_formula/late_fee_round_per_day_then_sum_mode_b
    """
    sc, booking = _late_booking(api, "owner_lf_b@x.com", "renter_lf_b@x.com", 333,
                                "2026-06-11T00:00:00Z")
    assert booking["status"] == "LATE", booking["status"]
    assert booking["late_days"] == 3, booking["late_days"]


# --- Late-detection cascade to renter trust (Difficulty/transitive_cascade) ---

def test_late_detection_accrues_fee_and_marks_late(api):
    """PRD §3.6: "the Platform-driven late-return sweep marks it late, transitioning
    ACTIVE → LATE. On that transition the system sets late_days to the number of whole
    days between the booking's end_date and the current logical clock, accrues the late
    fee, increments the renter's late_return_count by 1, and recomputes the renter's
    trust_score."

    Design: Difficulty/transitive_cascade/late_detection_cascade_depth2
    """
    sc, booking = _late_booking(api, "owner_ld_a@x.com", "renter_ld_a@x.com", 10000,
                                "2026-06-10T00:00:00Z")
    assert booking["status"] == "LATE"
    assert booking["late_fee_cents"] == 30000, booking["late_fee_cents"]


def test_late_detection_penalizes_renter_trust(api):
    """PRD §3.6: "increments the renter's late_return_count by 1, and recomputes the
    renter's trust_score."
    PRD §3.9: "From that running figure, subtract 25 points for each late return the user
    has as a renter (late_return_count) and subtract 40 points for each upheld claim
    against them as a renter (upheld_claim_count)."

    Design: Difficulty/transitive_cascade/late_detection_cascade_depth2
    """
    sc, booking = _late_booking(api, "owner_ld_b@x.com", "renter_ld_b@x.com", 10000,
                                "2026-06-10T00:00:00Z")
    profile = get_success_data(api.get_user(sc["renter_id"], _platform_headers()))
    assert profile["late_return_count"] == 1, profile["late_return_count"]
    assert profile["trust_score"] == 275, profile["trust_score"]


# --- Provisional vs final settlement on the Booking domain (Difficulty) -------

def test_final_total_diverges_from_provisional_after_late_return(api):
    """PRD §3.3: "provisional_total_cents is rental_subtotal_cents plus
    renter_service_fee_cents. The provisional form carries no late fee."
    PRD §3.6: "the final form of the booking settlement charge is computed: final_total_cents
    is rental_subtotal_cents plus renter_service_fee_cents plus late_fee_cents."

    Design: Difficulty/dual_variant_calc/booking_settlement_provisional_vs_final_on_booking
    """
    sc = setup_returned_booking(api, base_daily_rate_cents=10000, deposit_cents=50000,
                                declared_value_cents=90000,
                                late_to="2026-06-10T00:00:00Z")
    booking = sc["booking"]
    assert booking["provisional_total_cents"] == 74592, booking["provisional_total_cents"]
    assert booking["final_total_cents"] == 104592, booking["final_total_cents"]


def test_final_total_adds_accrued_late_fee(api):
    """PRD §3.6: "the final form of the booking settlement charge is computed:
    final_total_cents is rental_subtotal_cents plus renter_service_fee_cents plus
    late_fee_cents. The final total therefore adds the accrued late fee ..."

    Design: Difficulty/dual_variant_calc/booking_settlement_provisional_vs_final_on_booking
    """
    sc = setup_returned_booking(api, base_daily_rate_cents=10000, deposit_cents=50000,
                                declared_value_cents=90000,
                                late_to="2026-06-10T00:00:00Z")
    booking = sc["booking"]
    assert booking["late_fee_cents"] == 30000, booking["late_fee_cents"]
    assert (booking["final_total_cents"]
            == booking["provisional_total_cents"] + booking["late_fee_cents"])


# --- Owner payout with no damage (Corner/calculations) -----------------------

def test_owner_payout_no_damage_net_correct(api):
    """PRD §3.6: "owner_commission_cents is gross_earnings_cents multiplied by 1500 basis
    points divided by 10000 (fifteen percent), rounded to whole cents using round half up.
    damage_reimbursement_cents starts at 0 for a freshly created payout. net_payout_cents
    is gross_earnings_cents minus owner_commission_cents plus damage_reimbursement_cents."

    Design: Corner/calculations/owner_payout_no_damage_net_correct
    """
    sc = setup_returned_booking(api, base_daily_rate_cents=10000, deposit_cents=50000, quantity=1)
    payout = sc["payout"]
    assert payout["gross_earnings_cents"] == 66600, payout["gross_earnings_cents"]
    assert payout["owner_commission_cents"] == 9990, payout["owner_commission_cents"]
    assert payout["net_payout_cents"] == 56610, payout["net_payout_cents"]


# --- Payout release gated on claim state (Difficulty/cross_entity) ------------

def test_payout_release_blocked_by_open_claim(api):
    """PRD §3.8: "Releasing the payout requires that the booking's Payout be PENDING or
    HELD and that no Claim on the booking remain OPEN or UNDER_REVIEW; an attempt while any
    claim is still unresolved is rejected with ERR_CLAIM_UNRESOLVED."

    Design: Difficulty/cross_entity_state_dependency/payout_release_depends_on_claim_resolved
    """
    sc = setup_open_claim(api, claimed_amount_cents=20000, deposit_cents=50000)
    resp = api.release_payout(sc["payout_id"], _platform_headers())
    validate_error(resp, ApiErrorId.ERR_CLAIM_UNRESOLVED.value)


def test_payout_release_blocked_by_under_review_claim(api):
    """PRD §3.8: "Releasing the payout requires that the booking's Payout be PENDING or
    HELD and that no Claim on the booking remain OPEN or UNDER_REVIEW; an attempt while any
    claim is still unresolved is rejected with ERR_CLAIM_UNRESOLVED."

    Design: Difficulty/cross_entity_state_dependency/payout_release_depends_on_claim_resolved
    """
    sc = setup_claim_under_review(api, claimed_amount_cents=20000, deposit_cents=50000)
    resp = api.release_payout(sc["payout_id"], _platform_headers())
    validate_error(resp, ApiErrorId.ERR_CLAIM_UNRESOLVED.value)


# --- Return condition-photo requirement (Difficulty/boundary) ----------------

def test_return_without_condition_photos_rejected(api):
    """PRD §3.6: "Return requires the acting owner to own the listing, the booking to be
    ACTIVE or LATE, a COMPLETED RETURN handoff appointment to exist (or ERR_HANDOFF_MISSING),
    and a RETURN condition report with at least one photo to exist (or
    ERR_CONDITION_PHOTOS_REQUIRED)."

    Design: Difficulty/boundary_precision_check/empty_return_photo_set_rejected
    """
    sc = setup_active_booking(api, base_daily_rate_cents=10000, quantity=1)
    schedule_and_complete_handoff(api, sc["booking_id"], sc["owner_id"], "RETURN",
                                  "2026-06-08T09:00:00Z", "2026-06-08T09:30:00Z")
    resp = api.return_booking(sc["booking_id"], sc["owner_headers"])
    validate_error(resp, ApiErrorId.ERR_CONDITION_PHOTOS_REQUIRED.value)


def test_return_with_condition_photos_succeeds(api):
    """PRD §3.6: "Return requires the acting owner to own the listing, the booking to be
    ACTIVE or LATE, a COMPLETED RETURN handoff appointment to exist (or ERR_HANDOFF_MISSING),
    and a RETURN condition report with at least one photo to exist (or
    ERR_CONDITION_PHOTOS_REQUIRED)."

    Design: Difficulty/boundary_precision_check/empty_return_photo_set_rejected
    """
    sc = setup_active_booking(api, base_daily_rate_cents=10000, quantity=1)
    schedule_and_complete_handoff(api, sc["booking_id"], sc["owner_id"], "RETURN",
                                  "2026-06-08T09:00:00Z", "2026-06-08T09:30:00Z")
    add_condition_report(api, sc["booking_id"], sc["owner_id"], "RETURN")
    data = validate_success(api.return_booking(sc["booking_id"], sc["owner_headers"]))
    assert data["status"] == "RETURNED", data["status"]


# --- Booking list pagination envelope (Corner/endpoints) ---------------------

def test_list_bookings_returns_paginated_envelope(api):
    """PRD §2.3: "Every list response carries the pagination fields limit, offset,
    total_count, and has_more in the meta object, where total_count is the number of items
    matching the query before pagination and has_more indicates whether items remain beyond
    the current page."

    Design: Corner/endpoints/list_bookings_returns_paginated_envelope
    """
    owner = create_owner(api, email="owner_listpag@x.com")
    renter = create_verified_renter(api, email="renter_listpag@x.com")
    listing = create_active_listing(api, owner["id"], quantity=1)
    create_requested_booking(api, listing["id"], renter["id"],
                             "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    resp = api.list_bookings(make_renter_headers(renter["id"]), params={"renter_id": renter["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta["total_count"]
    assert meta["has_more"] is False, meta["has_more"]
    assert len(data) == 1
