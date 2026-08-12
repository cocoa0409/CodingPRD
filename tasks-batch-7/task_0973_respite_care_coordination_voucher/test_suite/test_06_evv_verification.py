"""EVV visit math: quarter-hour rounding, overage cap, evening boundary,
provisional-vs-final claim amounts, verification cascade, reject-resubmit."""
from test_helpers import (
    COORD,
    assert_hours,
    book_and_confirm,
    decide_visit,
    get_claim_for_voucher,
    make_provider_headers,
    run_visit_through_checkout,
    setup_service_world,
    setup_verified_service,
    validate_success,
)


def test_quarter_hour_rounding_74_to_75(api):
    """PRD §3.9: "`verified_minutes` is that elapsed time rounded up to the nearest
    15-minute unit — that is, 15 multiplied by the round-half-up of the elapsed minutes
    divided by 15. `payable_minutes` is the smaller of `verified_minutes` and the floor
    of the booking's `committed_minutes` multiplied by the program's `max_overage_pct`."
    PRD §3.10: "The claim's `amount_cents` is then the base minutes multiplied by the
    program's `standard_rate_cents_per_hour`, multiplied by all three applicable
    multipliers, divided by 60, and rounded half up to integer cents."

    Design: Corner/calculations/evv_quarter_hour_rounding_74_to_75
    """
    ctx = setup_service_world(window_start="2026-05-06T08:00:00Z",
                              window_end="2026-05-06T20:00:00Z",
                              window_capacity=1)
    booking = book_and_confirm(ctx, "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z")
    # 74 elapsed minutes round half-up to 75 (round_half_up(74/15) = 5 units).
    visit = run_visit_through_checkout(ctx, booking,
                                       "2026-05-06T10:00:00Z", "2026-05-06T11:14:00Z")
    assert visit["verified_minutes"] == 75
    assert visit["payable_minutes"] == 75
    decide_visit(visit["id"], "VERIFY")
    claim = get_claim_for_voucher(ctx["voucher"]["id"])
    # Wednesday daytime, STANDARD credential, non-emergency: 75 x 3000 / 60 = 3750.
    assert claim["amount_cents"] == 3750


def test_overage_cap_enforced_at_110_percent(api):
    """PRD §3.9: "`payable_minutes` is the smaller of `verified_minutes` and the floor
    of the booking's `committed_minutes` multiplied by the program's
    `max_overage_pct`."
    PRD §2.7: "`max_overage_pct` (default 1.10) caps the payable minutes of a visit as
    a fraction of the booking's committed minutes."

    Design: Corner/calculations/overage_cap_enforced_at_110_percent
    """
    ctx = setup_service_world(window_start="2026-05-06T08:00:00Z",
                              window_end="2026-05-06T20:00:00Z",
                              window_capacity=1)
    booking = book_and_confirm(ctx, "2026-05-06T10:00:00Z", "2026-05-06T11:00:00Z")
    # 90 verified minutes against a 60-minute commitment: floor(60 x 1.10) = 66.
    visit = run_visit_through_checkout(ctx, booking,
                                       "2026-05-06T10:00:00Z", "2026-05-06T11:30:00Z")
    assert visit["verified_minutes"] == 90
    assert visit["payable_minutes"] == 66
    decide_visit(visit["id"], "VERIFY")
    claim = get_claim_for_voucher(ctx["voucher"]["id"])
    # Weekday daytime STANDARD: 66 x 3000 / 60 = 3300.
    assert claim["amount_cents"] == 3300


def test_evening_boundary_checkin_exactly_1800(api):
    """PRD §2.7: "`evening_multiplier` (default 1.25) applies when the visit's
    `check_in_at` hour in UTC is at or after `evening_start_hour` (default 18) on a
    Monday-through-Friday."

    Design: Corner/calculations/evening_boundary_checkin_exactly_1800
    """
    # Monday 2026-05-04, check-in at exactly 18:00:00 UTC -> evening multiplier applies.
    ctx = setup_verified_service(booking_start="2026-05-04T18:00:00Z",
                                 booking_end="2026-05-04T19:00:00Z")
    # 60 payable minutes x 3000 x 1.25 / 60 = 3750.
    assert ctx["claim"]["amount_cents"] == 3750


class TestProvisionalVsFinalEvening:
    def test_provisional_ignores_multipliers(self, api):
        """PRD §3.7: "Confirming computes the booking's `provisional_amount_cents` as
        the `committed_minutes` multiplied by the program's
        `standard_rate_cents_per_hour`, divided by 60, and rounded half up to integer
        cents."
        PRD §3.9: "the claim records the visit on its `visit_record_id` field, carries
        the voucher on `voucher_id` and the billing provider on `provider_id`, takes
        its `provisional_amount_cents` from the booking, and computes its `amount_cents`
        per the final-amount calculation described in §3.10."

        Design: Difficulty/dual_variant_calc/claim_payment_provisional_vs_final_evening
        """
        ctx = setup_service_world()
        booking = book_and_confirm(ctx, "2026-05-04T19:00:00Z", "2026-05-04T21:00:00Z")
        # 120 committed minutes x 3000 / 60 = 6000 — no day/credential/emergency terms.
        assert booking["provisional_amount_cents"] == 6000
        run_visit_through_checkout(ctx, booking,
                                   "2026-05-04T19:00:00Z", "2026-05-04T21:00:00Z")
        decide_visit(ctx["visit"]["id"], "VERIFY")
        claim = get_claim_for_voucher(ctx["voucher"]["id"])
        assert claim["provisional_amount_cents"] == 6000

    def test_final_applies_evening_multiplier(self, api):
        """PRD §3.10: "otherwise if the UTC hour of `check_in_at` is at or after the
        program's `evening_start_hour` the multiplier is the program's
        `evening_multiplier`"
        PRD §3.10: "the provisional uses only `committed_minutes` and the standard
        rate, with no day, credential, or emergency multipliers and no payable-minute
        capping, so identical service can yield different provisional and final
        figures."

        Design: Difficulty/dual_variant_calc/claim_payment_provisional_vs_final_evening
        """
        # Monday 19:00-21:00: evening x1.25 on 120 payable minutes.
        ctx = setup_verified_service()
        claim = ctx["claim"]
        assert claim["amount_cents"] == 7500
        assert claim["amount_cents"] - claim["provisional_amount_cents"] == 1500


class TestVisitVerificationCascade:
    def test_verify_creates_claim_and_moves_entities(self, api):
        """PRD §3.9: "A `Claim` is created in `DRAFT` status for the visit (exactly one
        claim per visit)"
        PRD §3.9: "The visit's booking transitions from `IN_SERVICE` to `COMPLETED`.
        The voucher transitions from `COMMITTED` to `REDEEMED`: its `consumed_hours` is
        increased by the verified hours, its `committed_hours` is reset to 0, and its
        `released_hours` is set to `authorized_hours` minus `consumed_hours` minus
        `forfeited_hours`."

        Design: Difficulty/transitive_cascade/visit_verification_claim_voucher_budget_cascade
        """
        ctx = setup_verified_service()
        claim = ctx["claim"]
        assert claim["status"] == "DRAFT"
        # Monday evening: 120 payable x 3000 x 1.25 / 60 = 7500.
        assert claim["amount_cents"] == 7500

        voucher = validate_success(api.get_voucher(ctx["voucher"]["id"], COORD), 200)
        assert voucher["status"] == "REDEEMED"
        assert_hours(voucher["consumed_hours"], 2.00, "voucher consumed_hours")
        assert_hours(voucher["committed_hours"], 0.00, "voucher committed_hours")
        assert_hours(voucher["released_hours"], 18.00, "voucher released_hours")

        booking = validate_success(api.get_booking(ctx["booking"]["id"], COORD), 200)
        assert booking["status"] == "COMPLETED"

    def test_verify_moves_allocation_buckets_and_budget(self, api):
        """PRD §3.9: "its `reserved_hours` is decremented by the voucher's
        `authorized_hours`, its `consumed_hours` is incremented by the verified hours,
        and its `available_hours` is incremented by the voucher's `released_hours`."
        PRD §3.9: "On the budget side, the voucher's provisional encumbrance is
        released (a `RELEASE` ledger entry) and the claim's `amount_cents` is
        encumbered (an `ENCUMBER` ledger entry)."

        Design: Difficulty/transitive_cascade/visit_verification_claim_voucher_budget_cascade
        """
        ctx = setup_verified_service()
        alloc = validate_success(api.get_allocation(ctx["allocation"]["id"], COORD), 200)
        assert_hours(alloc["available_hours"], 78.00, "allocation available_hours")
        assert_hours(alloc["reserved_hours"], 0.00, "allocation reserved_hours")
        assert_hours(alloc["consumed_hours"], 2.00, "allocation consumed_hours")

        program = validate_success(api.get_program(ctx["program"]["id"], COORD), 200)
        # Provisional 60000 released; claim 7500 encumbered.
        assert program["encumbered_cents"] == 7500


def test_visit_reject_resubmit_recomputes_minutes(api):
    """PRD §3.9: "A `REJECT` decision sets the visit's `rejection_reason` to the
    supplied reason, moves the visit to `REJECTED`"
    PRD §3.9: "When times are supplied they replace the originals, and
    `verified_minutes` and `payable_minutes` are recomputed by the same formulas. The
    `rejection_reason` is cleared to null, the visit moves from `REJECTED` back to
    `SUBMITTED`, and its `version` increments by 1."

    Design: Corner/state_machines/visit_reject_resubmit_recomputes_minutes
    """
    ctx = setup_service_world()
    booking = book_and_confirm(ctx, "2026-05-04T19:00:00Z", "2026-05-04T21:00:00Z")
    visit = run_visit_through_checkout(ctx, booking,
                                       "2026-05-04T19:00:00Z", "2026-05-04T21:00:00Z")
    rejected = decide_visit(visit["id"], "REJECT", reason="checkout looks early")
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "checkout looks early"

    resubmitted = validate_success(
        api.resubmit_visit(visit["id"],
                           {"check_out_at": "2026-05-04T21:30:00Z", "notes": "corrected"},
                           make_provider_headers(ctx["provider"]["id"])),
        200)
    assert resubmitted["status"] == "SUBMITTED"
    # 19:00 -> 21:30 is 150 elapsed minutes; verified 150, capped at floor(120x1.10)=132.
    assert resubmitted["verified_minutes"] == 150
    assert resubmitted["payable_minutes"] == 132
    assert resubmitted["rejection_reason"] is None
