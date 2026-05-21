"""Difficulty-design coverage — primary tests for each instance.

Every instance declared in the difficulty-design index gets at least
two tests (this file and test_11_difficulty_coverage_supplemental.py).
Each test cites a verbatim PRD sentence for its underlying rule.

Tag format: each test docstring carries `# difficulty: <rule_id>/<name>`.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BASE_FARE_CENTS,
    DAILY_CAP_CENTS,
    REDUCED_FARE_BASE_CENTS,
    advance_clock_to_iso,
    approve_low_income_verification_payload,
    claim_dispute,
    create_card_payload,
    create_dispute_payload,
    create_fsa_account_payload,
    create_fsa_contribution_payload,
    create_low_income_verification_payload,
    create_mobile_token_payload,
    create_pending_reduced_fare_certificate,
    create_active_reduced_fare_certificate,
    create_reduced_fare_certificate_payload,
    create_rider,
    create_trip_payload,
    file_dispute,
    get_card,
    get_cap_period_for_window,
    get_rider,
    get_trip,
    issue_card,
    make_employer_admin_headers,
    make_rider_headers,
    NON_EXISTENT_UUID,
    resolve_dispute_payload,
    run_sweep_settle,
    setup_backdated_divergence_scenario,
    setup_cap_cascade_scenario,
    setup_rider_with_fsa,
    setup_rider_with_funded_card,
    setup_rider_with_reduced_fare_card,
    suspend_card,
    tap_in,
    tap_in_and_out,
    unique_idempotency_key,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_trip_fare_provisional_vs_settled_diverge(self, api,
                                                      agency_officer_headers):
        """PRD §3.8: "Because the chronological walk treats earlier
        trips before later ones, and because an `INCOMPLETE_FORCED`
        force-closure between the two sweeps may retroactively raise
        an earlier trip's contribution from zero (transfer-discounted)
        to the full post-discount base, the provisional and settled
        views can legitimately diverge on the same inputs — provisional
        is a forward-looking forecast, settled is the chronological
        ground truth, and the system's compensating refunds and
        back-charges bridge the two so that wallet plus FSA together
        exactly equal the original conserved quantity per the
        rounding-order pinned in §2.8."

        Claim (forward-looking vs chronological diverge): inserting
        BACKDATED tap-ins forces the chronological settle to differ
        from the forward-looking provisional view, and the trip's
        settled_fare_cents != provisional_fare_cents.

        # difficulty: dual_variant_calc/trip_fare_provisional_vs_settled_diverge
        """
        ctx = setup_backdated_divergence_scenario(
            monthly_contribution_cap_cents=31_500,
            fsa_contribution_cents=100,
            topup_cents=1000,
        )
        trip_a = ctx["trip_a"]
        # Trip_A provisional, by recipe: 275 (STANDARD, first tap, no
        # prior on day window yet — but at 17:00 nothing has been
        # accumulated yet so cap remaining = 600 ≥ 275).
        assert trip_a["provisional_fare_cents"] == 275, (
            f"Trip_A provisional must be 275, got "
            f"{trip_a['provisional_fare_cents']}"
        )
        # Advance past DAILY window_end and settle.
        advance_clock_to_iso("2026-05-21T01:00:00.000Z")
        run_sweep_settle()
        # Re-read all three trips post-settle.
        a = get_trip(trip_a["id"])
        b = get_trip(ctx["trip_b"]["id"])
        c = get_trip(ctx["trip_c"]["id"])
        assert a["fare_status"] == "SETTLED"
        assert b["fare_status"] == "SETTLED"
        assert c["fare_status"] == "SETTLED"
        # The chronological settle orders trips by tap_in_at ASC:
        #   C (09:00, prov 50) → B (13:00, prov 275) → A (17:00, prov 275)
        # Chronological accumulator at each step:
        #   C: pre_cap=275, cap_remaining=600 → settled_C=275; running=275
        #   B: pre_cap=275, cap_remaining=600-275=325 → settled_B=275; running=550
        #   A: pre_cap=275, cap_remaining=600-550=50 → settled_A=50;  running=600
        # So Trip_A.settled_fare_cents must equal 50, NOT 275.
        assert a["settled_fare_cents"] == 50, (
            "Trip_A settled (chronological replay binds at 50) must be 50; "
            f"got {a['settled_fare_cents']}"
        )
        assert a["settled_fare_cents"] != a["provisional_fare_cents"], (
            "Provisional and settled MUST diverge on Trip_A for the "
            "backdated insert scenario"
        )

    def test_low_income_eligibility_declared_vs_verified_diverge(
            self, api, agency_officer_headers):
        """PRD §3.3: "The threshold for eligibility is three million
        cents (that is, thirty thousand US dollars), and the
        comparison is inclusive: a verified income that is at most
        three million cents qualifies ... If the verified income
        exceeds the threshold and the verification is still in
        `PENDING`, the record transitions to terminal `REJECTED` and
        the rider's `low_income_verified` remains false."

        Claim: declared income $25,000 passes a pre-check intuition
        but a verified income of $35,000 exceeds the threshold,
        driving the verification to REJECTED and leaving the rider's
        low_income_verified at false.

        # difficulty: dual_variant_calc/low_income_eligibility_declared_vs_verified_diverge
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider = create_rider()
        rh = make_rider_headers(rider["id"])
        # Declared $25,000 → 2_500_000 cents (below the threshold).
        v = validate_success(
            api.create_low_income_verification(
                create_low_income_verification_payload(
                    rider_id=rider["id"],
                    declared_annual_income_cents=2_500_000,
                ),
                rh,
            ),
            expected_status=201,
        )
        assert v["declared_annual_income_cents"] == 2_500_000
        # Verified $35,000 → 3_500_000 cents (above threshold).
        result = validate_success(
            api.approve_low_income_verification(
                v["id"],
                approve_low_income_verification_payload(
                    verified_annual_income_cents=3_500_000,
                ),
                agency_officer_headers,
            ),
            expected_status=200,
        )
        assert result["verified_annual_income_cents"] == 3_500_000
        assert result["status"] == "REJECTED"
        refreshed = get_rider(rider["id"], headers=rh)
        assert refreshed["low_income_verified"] is False


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_provisional_fare_three_input_min_max_nesting(self, api):
        """PRD §3.5: "the trip's `provisional_fare_cents` is the
        minimum of the pre-cap fare, the daily remaining, and the
        weekly remaining."
        PRD §3.5: "for `REDUCED_FARE` cards it is the base fare
        multiplied by 0.50, rounded half-up to the nearest whole cent
        (so 275 times 0.50 is 137.5, which rounds to 138 cents)."

        Claim: a REDUCED_FARE card with 4 non-transfer prior trips at
        138 each (accumulated=552) yields a 5th tap whose
        provisional_fare_cents=48 (daily_remaining=48 binds), proving
        the three-input min and the round_half_up tier selection both
        kick in.

        # difficulty: combinatorial_formula/provisional_fare_three_input_min_max_nesting
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, _cert, card = setup_rider_with_reduced_fare_card(
            topup_cents=1000,
            card_valid_from="2026-05-01T00:00:00.000Z",
            card_valid_until="2026-12-31T23:59:59.000Z",
            cert_valid_from="2026-01-01T00:00:00.000Z",
            cert_valid_until="2027-01-01T00:00:00.000Z",
        )
        # Four taps spaced >120 min apart so no transfer applies and
        # each charges 138.
        for i, ts in enumerate([
            "2026-05-20T09:00:00.000Z",
            "2026-05-20T11:30:00.000Z",  # +2h30 > 120m → no transfer
            "2026-05-20T14:00:00.000Z",  # +2h30 > 120m → no transfer
            "2026-05-20T16:30:00.000Z",  # +2h30 > 120m → no transfer
        ]):
            t = tap_in_and_out(
                card_id=card["id"], rider_id=rider["id"],
                tap_in_at=ts,
                idempotency_key=f"k-{i}-" + card["id"][:6],
            )
            assert t["provisional_fare_cents"] == REDUCED_FARE_BASE_CENTS, (
                f"Trip {i} REDUCED_FARE provisional must be 138, got "
                f"{t['provisional_fare_cents']}"
            )
        # Now accumulated_cents=4*138=552. Fifth tap, daily_remaining=48.
        trip5 = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T19:00:00.000Z",
        )
        # pre_cap_fare=138, daily_remaining=48, weekly_remaining=3300-552
        # → 48 is the minimum.
        assert trip5["provisional_fare_cents"] == 48, (
            "Cap-binding 5th REDUCED_FARE tap must be 48 cents; got "
            f"{trip5['provisional_fare_cents']}"
        )

    def test_refund_split_rounding_order_pinned(self, api,
                                                 agency_officer_headers):
        """PRD §2.8: "the wallet share absorbing any rounding remainder
        so that the sum of FSA share and wallet share equals the
        conserved total exactly."
        PRD §3.8: "When the settled amount is less than the provisional
        amount, the difference is refunded back: the FSA share is the
        difference scaled by `paid_from_fsa_cents` divided by
        `provisional_fare_cents`, rounded half-up, and credited to the
        account's `balance_cents`; the wallet share is the rest of the
        difference and is credited to the card's `wallet_balance_cents`,
        absorbing any rounding remainder so that the total credited
        equals the difference exactly."

        Claim: on the backdated-divergence scenario with FSA=100,
        provisional_A=275 (paid_from_fsa=100, wallet=175), and
        settled_A=50, the refund_total=225 splits as
        refund_to_fsa = round_half_up(225 * 100/275) = 82 cents,
        refund_to_wallet = 225 - 82 = 143 cents (wallet absorbs the
        remainder).

        # difficulty: combinatorial_formula/refund_split_rounding_order_pinned
        """
        ctx = setup_backdated_divergence_scenario(
            monthly_contribution_cap_cents=31_500,
            fsa_contribution_cents=100,
            topup_cents=1000,
        )
        # Settle.
        advance_clock_to_iso("2026-05-21T01:00:00.000Z")
        run_sweep_settle()
        # After settle:
        #   Trip_A: prov=275 (paid_from_fsa=100, wallet=175); settled=50
        #          → refund_total=225 → refund_to_fsa=82, refund_to_wallet=143
        #   Trip_B: prov=275, settled=275 → no refund/charge
        #   Trip_C: prov=50,  settled=275 → back_charge=225 (wallet→FSA order)
        # Net wallet:
        #   pre-tap-A wallet=1000;
        #   tap-A: -175 (wallet share) → 825
        #   tap-B: -275 (no FSA left) → 550
        #   tap-C: -50  → 500
        #   refund_A: +143 → 643
        #   back_charge_C: wallet 643 → take 225 from wallet first
        #                  → wallet=643-225=418
        # Net FSA:
        #   pre-tap-A balance=100; after tap-A FSA=0.
        #   refund_to_fsa=82 → FSA=82.
        c = get_card(ctx["card"]["id"])
        assert c["wallet_balance_cents"] == 418, (
            "Wallet must reflect FSA-first rounding, wallet-absorbs-"
            f"remainder semantics: expected 418, got "
            f"{c['wallet_balance_cents']}"
        )
        # FSA balance is implementation-dependent to inspect via API;
        # we assert the conserved-quantity invariant via the trip ledger
        # instead: Trip_A.settled_fare_cents=50, Trip_B.settled=275,
        # Trip_C.settled=275 sum to 600 (= cap).
        a = get_trip(ctx["trip_a"]["id"])
        b = get_trip(ctx["trip_b"]["id"])
        cc = get_trip(ctx["trip_c"]["id"])
        assert a["settled_fare_cents"] == 50
        assert b["settled_fare_cents"] == 275
        assert cc["settled_fare_cents"] == 275


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_trip_parallel_dimensions_travel_x_fare(
            self, api, agency_officer_headers):
        """PRD §3.7: "A REJECT resolution simply transitions the
        trip's `fare_status` from `DISPUTED` to `SETTLED` with
        `settled_fare_cents` set equal to `provisional_fare_cents` and
        writes no refund."
        PRD §3.6: "Success writes `tap_out_at`, transitions
        `travel_status` from `TAPPED_IN` to `COMPLETED`, and refreshes
        `updated_at`."

        Claim: a trip moves through travel_status TAPPED_IN→COMPLETED
        once at tap-out, but its fare_status independently cycles
        PROVISIONAL→DISPUTED→SETTLED via the dispute lifecycle —
        proving the two dimensions evolve independently on the same
        row.

        # difficulty: non_linear_state_machine/trip_parallel_dimensions_travel_x_fare
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        trip = tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
            tap_out_minutes=20,
        )
        assert trip["travel_status"] == "COMPLETED"
        assert trip["fare_status"] == "PROVISIONAL"
        # File dispute → fare_status DISPUTED, travel_status untouched.
        dispute = file_dispute(trip_id=trip["id"], rider_id=rider["id"])
        t1 = get_trip(trip["id"])
        assert t1["travel_status"] == "COMPLETED", (
            "travel_status must stay COMPLETED during fare-side dispute"
        )
        assert t1["fare_status"] == "DISPUTED"
        # Claim → INVESTIGATING (DisputeCase side), trip dimensions
        # untouched.
        claim_dispute(dispute_id=dispute["id"])
        t2 = get_trip(trip["id"])
        assert t2["travel_status"] == "COMPLETED"
        assert t2["fare_status"] == "DISPUTED"
        # Resolve REJECT → fare_status → SETTLED, travel_status unchanged.
        validate_success(
            api.resolve_dispute(
                dispute["id"],
                resolve_dispute_payload(decision="REJECT"),
                agency_officer_headers,
            ),
            expected_status=200,
        )
        t3 = get_trip(trip["id"])
        assert t3["travel_status"] == "COMPLETED", (
            "travel_status must remain COMPLETED across the entire "
            f"fare cycle; got {t3['travel_status']}"
        )
        assert t3["fare_status"] == "SETTLED"
        # tap_out_at set during travel transition; untouched by fare.
        assert t3.get("tap_out_at"), (
            "tap_out_at must remain set across fare transitions"
        )

    def test_dispute_case_cyclic_open_investigating(
            self, api, agency_officer_headers):
        """PRD §3.7: "From `INVESTIGATING` the officer has three
        options: request more evidence, which transitions `status`
        back to `OPEN` so the case can cycle (rider provides evidence,
        officer claims again, requests again, and so on)".

        Claim: a DisputeCase can be cycled OPEN → INVESTIGATING → OPEN
        via claim + request-evidence repeatedly, and after two full
        cycles the status is still OPEN.

        # difficulty: non_linear_state_machine/dispute_case_cyclic_open_investigating
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        trip = tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
            tap_out_minutes=20,
        )
        dispute = file_dispute(trip_id=trip["id"], rider_id=rider["id"])
        assert dispute["status"] == "OPEN"
        prior_version = dispute["version"]
        # Cycle 1.
        d1 = validate_success(
            api.claim_dispute(dispute["id"], agency_officer_headers),
            expected_status=200,
        )
        assert d1["status"] == "INVESTIGATING"
        d2 = validate_success(
            api.request_evidence_dispute(
                dispute["id"], agency_officer_headers,
            ),
            expected_status=200,
        )
        assert d2["status"] == "OPEN"
        # Cycle 2.
        d3 = validate_success(
            api.claim_dispute(dispute["id"], agency_officer_headers),
            expected_status=200,
        )
        assert d3["status"] == "INVESTIGATING"
        d4 = validate_success(
            api.request_evidence_dispute(
                dispute["id"], agency_officer_headers,
            ),
            expected_status=200,
        )
        assert d4["status"] == "OPEN", (
            "Dispute must cycle back to OPEN after the second "
            f"request-evidence; got {d4['status']}"
        )
        # Each cycle adds 2 version bumps; after 2 cycles the version
        # has advanced by at least 4.
        assert d4["version"] >= prior_version + 4, (
            "Two full cycles must produce at least 4 version bumps; "
            f"prior {prior_version}, current {d4['version']}"
        )


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_dispute_refund_depth_4_cascade(self, api,
                                            agency_officer_headers):
        """PRD §3.7: "A REFUND resolution sets `refund_amount_cents` to
        the trip's `provisional_fare_cents`, transitions the trip's
        `fare_status` from `DISPUTED` to `SETTLED` with
        `settled_fare_cents` set to zero, splits the refund
        proportionally back to the `CommuterBenefitAccount.balance_cents`
        ... and back to the card's `wallet_balance_cents` ..., and
        decrements `accumulated_cents` by `provisional_fare_cents` on
        both the daily and weekly `FareCapPeriod`."

        Claim: resolving a dispute REFUND on T1 (Link 1) cascades:
        Link 2 — T1.fare_status moves DISPUTED → SETTLED with
        settled=0; Link 3 — FareCapPeriod.accumulated_cents drops by
        275 (600 → 325). The chronological-settle implications on T3
        and T4 are exercised by the supplemental difficulty test.

        # difficulty: transitive_cascade/dispute_refund_depth_4_cascade
        """
        ctx = setup_cap_cascade_scenario(topup_cents=10_000)
        # Setup created 4 ordered taps T1..T4 with cumulative=600 then T4=0.
        rider = ctx["rider"]
        card = ctx["card"]
        t1 = ctx["t1"]
        # File and claim dispute on T1.
        d = file_dispute(trip_id=t1["id"], rider_id=rider["id"])
        d = validate_success(
            api.claim_dispute(d["id"], agency_officer_headers),
            expected_status=200,
        )
        assert d["status"] == "INVESTIGATING"
        # Trigger: REFUND.
        resolved = validate_success(
            api.resolve_dispute(
                d["id"],
                resolve_dispute_payload(decision="REFUND"),
                agency_officer_headers,
            ),
            expected_status=200,
        )
        # Link 1.
        assert resolved["status"] == "RESOLVED_REFUNDED"
        # Link 2.
        t1_after = get_trip(t1["id"])
        assert t1_after["fare_status"] == "SETTLED"
        assert t1_after["settled_fare_cents"] == 0
        # Link 3 — DAILY cap accumulated_cents drops by T1.provisional=275.
        # Original accumulated was 600 (saturated at cap); after refund,
        # 600 - 275 = 325.
        cp = get_cap_period_for_window(
            card["id"], "DAILY", "2026-05-20T10:00:00.000Z",
        )
        assert cp is not None
        assert cp["accumulated_cents"] == 325, (
            "DAILY accumulated_cents must drop by T1.provisional (275) "
            f"after refund; expected 325, got {cp['accumulated_cents']}"
        )

    def test_employer_suspend_to_fsa_freeze_to_charge_path_diverted(
            self, api, agency_officer_headers):
        """PRD §3.1: "When an `AgencyOfficer` suspends an employer,
        every `CommuterBenefitAccount` carrying that `employer_id`
        transitions from `ACTIVE` to `FROZEN`; this freezes both new
        contributions and new tap-in disbursements from those accounts
        while still permitting refunds".
        PRD §2.10: "If the rider has no `employer_id`, has no account,
        or the account's `status` is `FROZEN`, the FSA share is zero
        and the whole charge falls on `wallet_balance_cents`."

        Claim: suspending an Employer (Link 1) cascades to FROZEN on
        every CommuterBenefitAccount it sponsors (Link 2); a
        subsequent tap-in on that rider's card observes the FROZEN
        account and routes the entire fare to the wallet
        (paid_from_fsa_cents=0 even though account.balance_cents > 0).

        # difficulty: transitive_cascade/employer_suspend_to_fsa_freeze_to_charge_path_diverted
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, employer, _acct, card, _c = setup_rider_with_fsa(
            contribution_cents=1000,
            contribution_month="2026-05",
            topup_cents=1000,
            discount_class="STANDARD",
            card_valid_from="2026-05-01T00:00:00.000Z",
            card_valid_until="2026-12-31T23:59:59.000Z",
        )
        # Suspend employer.
        suspended = validate_success(
            api.suspend_employer(employer["id"], agency_officer_headers),
            expected_status=200,
        )
        assert suspended["enrollment_status"] == "SUSPENDED"
        # Tap in — FSA must be bypassed.
        trip = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        assert trip["paid_from_fsa_cents"] == 0, (
            "Frozen FSA must contribute 0 to the charge; got "
            f"paid_from_fsa_cents={trip['paid_from_fsa_cents']}"
        )
        # Wallet must have lost the entire 275.
        c_after = get_card(card["id"])
        assert c_after["wallet_balance_cents"] == 1000 - 275, (
            "Wallet must absorb the entire fare when FSA is FROZEN; "
            f"got {c_after['wallet_balance_cents']}"
        )


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_card_not_active_beats_insufficient_funds(self, api):
        """PRD §2.11: "state-eligibility of the target resource for
        the requested operation, including transitions, dispute
        resolutions, and approvals (rejection: `ERR_INVALID_STATE`);
        on a tap-in specifically, the additional state checks that
        the card is in `ACTIVE` status (rejection:
        `ERR_CARD_NOT_ACTIVE`) and that no other trip on the same
        card is currently in `TAPPED_IN` (rejection:
        `ERR_TRIP_ALREADY_OPEN`); ... and finally business fiscal
        checks — the monthly FSA contribution sum staying at or below
        the employer's monthly cap (rejection:
        `ERR_FSA_MONTHLY_CAP_EXCEEDED`) and the combined wallet plus
        FSA balance covering the provisional fare (rejection:
        `ERR_INSUFFICIENT_FUNDS`)."

        Claim: when both ERR_CARD_NOT_ACTIVE and ERR_INSUFFICIENT_FUNDS
        would apply (suspended card + empty wallet), the state check
        wins and the response carries ERR_CARD_NOT_ACTIVE.

        # difficulty: priority_pair_validation_conflict/card_not_active_beats_insufficient_funds
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=0)
        # Suspend card.
        suspend_card(card_id=card["id"])
        # Wallet=0, fare=275 → also ERR_INSUFFICIENT_FUNDS would apply.
        rh = make_rider_headers(rider["id"])
        resp = api.create_trip(
            create_trip_payload(
                card_id=card["id"],
                idempotency_key=unique_idempotency_key(),
                tap_in_at="2026-05-20T10:00:00.000Z",
            ),
            rh,
        )
        validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE.value)

    def test_reference_not_found_beats_device_already_bound(
            self, api):
        """PRD §2.11: "existence of every foreign-key resource named
        in the request body (rejection: `ERR_REFERENCE_NOT_FOUND`);
        state-eligibility of the target resource for the requested
        operation ... business constraint checks such as `(rider_id,
        device_fingerprint)` uniqueness on a mobile token (rejection:
        `ERR_DEVICE_ALREADY_BOUND`)".

        Claim: when both ERR_REFERENCE_NOT_FOUND (nonexistent
        rider_id) and ERR_DEVICE_ALREADY_BOUND (the device_fingerprint
        already in use) would apply, existence wins and the response
        carries ERR_REFERENCE_NOT_FOUND.

        # difficulty: priority_pair_validation_conflict/reference_not_found_beats_device_already_bound
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        real_rider = create_rider()
        rh_real = make_rider_headers(real_rider["id"])
        # Bind a token with a known device_fingerprint to a real rider.
        device_fp = "dev-shared-XYZ-" + real_rider["id"][:6]
        validate_success(
            api.create_mobile_token(
                create_mobile_token_payload(
                    rider_id=real_rider["id"],
                    wallet_provider="APPLE_PAY",
                    device_fingerprint=device_fp,
                ),
                rh_real,
            ),
            expected_status=201,
        )
        # Attempt a SECOND mobile token referencing a NONEXISTENT
        # rider_id + the same device_fingerprint. PRD §2.11 priority:
        # ERR_REFERENCE_NOT_FOUND fires before ERR_DEVICE_ALREADY_BOUND.
        # Note: the calling Rider must be authorized; PRD §3.4 says
        # mobile-token register requires the Rider role. We use a
        # rider-role placeholder for the call.
        # Per PRD §2.1 ownership: the rider_id in the body must equal
        # X-User-ID for the OWN-rider check. Here we test existence,
        # so the bad rider_id matches X-User-ID for the FAILING
        # rider (the rider_id is what doesn't exist). To probe
        # ERR_REFERENCE_NOT_FOUND vs ERR_DEVICE_ALREADY_BOUND
        # priority, both rules must be evaluable; the implementation
        # is expected to fail the existence check first.
        bad_rider_id = NON_EXISTENT_UUID
        rh_bad = make_rider_headers(bad_rider_id)
        resp = api.create_mobile_token(
            create_mobile_token_payload(
                rider_id=bad_rider_id,
                wallet_provider="GOOGLE_PAY",
                device_fingerprint=device_fp,
            ),
            rh_bad,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    def test_transfer_window_inclusive_120_minutes(self, api):
        """PRD §3.5: "whose elapsed minutes since that prior
        `tap_in_at` are at most one hundred twenty (the boundary at
        exactly one hundred twenty minutes counts as a transfer)".

        Claim: at exactly 120 minutes between two tap_in_at values
        the second leg is transfer-eligible with
        provisional_fare_cents=0 and transfer_link_id non-null; at
        120 min + 1 second the boundary is exceeded and the second
        leg charges 275 with transfer_link_id null.

        # difficulty: boundary_precision_check/transfer_window_inclusive_120_minutes
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        # Card 1: tap T1a at 10:00, T1b at 12:00:00 (exactly 120 min).
        r1, c1 = setup_rider_with_funded_card(topup_cents=1000)
        tap_in_and_out(
            card_id=c1["id"], rider_id=r1["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
            tap_out_minutes=20,
            idempotency_key="k1a-" + c1["id"][:6],
        )
        t1b = tap_in(
            card_id=c1["id"], rider_id=r1["id"],
            tap_in_at="2026-05-20T12:00:00.000Z",
            idempotency_key="k1b-" + c1["id"][:6],
        )
        assert t1b["provisional_fare_cents"] == 0
        assert t1b.get("transfer_link_id"), (
            "transfer_link_id must be non-null at the inclusive 120-min "
            "boundary"
        )
        # Card 2: tap T2a at 10:00, T2b at 12:00:01 (120 min + 1 sec).
        r2, c2 = setup_rider_with_funded_card(topup_cents=1000)
        tap_in_and_out(
            card_id=c2["id"], rider_id=r2["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
            tap_out_minutes=20,
            idempotency_key="k2a-" + c2["id"][:6],
        )
        t2b = tap_in(
            card_id=c2["id"], rider_id=r2["id"],
            tap_in_at="2026-05-20T12:00:01.000Z",
            idempotency_key="k2b-" + c2["id"][:6],
        )
        assert t2b["provisional_fare_cents"] == BASE_FARE_CENTS
        assert t2b.get("transfer_link_id") is None

    def test_fsa_monthly_cap_inclusive_31500(self, api):
        """PRD §3.9: "a new contribution that would push the running
        sum past `Employer.monthly_contribution_cap_cents` is rejected
        with `ERR_FSA_MONTHLY_CAP_EXCEEDED`".

        Claim: at exactly Employer.monthly_contribution_cap_cents the
        running sum is accepted (boundary inclusive); 1 cent past is
        rejected.

        # difficulty: boundary_precision_check/fsa_monthly_cap_inclusive_31500
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, employer, acct, _card, _c1 = setup_rider_with_fsa(
            monthly_contribution_cap_cents=31_500,
            contribution_cents=31_499,
            contribution_month="2026-05",
            topup_cents=0,
        )
        eh = make_employer_admin_headers(employer["id"])
        # Bring to exactly 31_500.
        ok = validate_success(
            api.create_fsa_contribution(
                create_fsa_contribution_payload(
                    account_id=acct["id"], amount_cents=1,
                    contribution_month="2026-05",
                ),
                eh,
            ),
            expected_status=201,
        )
        assert ok["status"] == "APPLIED"
        # Then attempt 1 more cent → rejected.
        resp = api.create_fsa_contribution(
            create_fsa_contribution_payload(
                account_id=acct["id"], amount_cents=1,
                contribution_month="2026-05",
            ),
            eh,
        )
        validate_error(
            resp, ApiErrorId.ERR_FSA_MONTHLY_CAP_EXCEEDED.value,
        )


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_trip_tapin_blocked_by_card_status(self, api):
        """PRD §3.5: "The system then enforces that the card's
        `status` is `ACTIVE`, that no other trip on this card has
        `travel_status` `TAPPED_IN` ..."
        PRD §3.2: "suspension blocks new tap-ins (any subsequent tap
        is rejected with `ERR_CARD_NOT_ACTIVE`)".

        Claim: when FareCard.status=SUSPENDED, any new tap-in on it
        is rejected with ERR_CARD_NOT_ACTIVE — regardless of wallet
        funding.

        # difficulty: cross_entity_state_dependency/trip_tapin_blocked_by_card_status
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        suspend_card(card_id=card["id"])
        rh = make_rider_headers(rider["id"])
        resp = api.create_trip(
            create_trip_payload(
                card_id=card["id"],
                idempotency_key=unique_idempotency_key(),
                tap_in_at="2026-05-20T10:00:00.000Z",
            ),
            rh,
        )
        validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE.value)

    def test_fsa_contribution_blocked_by_employer_status(self, api,
                                                          agency_officer_headers):
        """PRD §3.1: "When an `AgencyOfficer` suspends an employer,
        every `CommuterBenefitAccount` carrying that `employer_id`
        transitions from `ACTIVE` to `FROZEN`; this freezes both new
        contributions and new tap-in disbursements from those accounts
        while still permitting refunds".

        Claim: after suspending the Employer, a new FSAContribution
        on its account is rejected with ERR_INVALID_STATE (the
        state-eligibility check fires since the account is FROZEN).

        # difficulty: cross_entity_state_dependency/fsa_contribution_blocked_by_employer_status
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, employer, acct, _card, _c = setup_rider_with_fsa(
            contribution_cents=0, topup_cents=0,
        )
        # Suspend employer → account becomes FROZEN per cascade.
        validate_success(
            api.suspend_employer(employer["id"], agency_officer_headers),
            expected_status=200,
        )
        eh = make_employer_admin_headers(employer["id"])
        resp = api.create_fsa_contribution(
            create_fsa_contribution_payload(
                account_id=acct["id"], amount_cents=1000,
                contribution_month="2026-05",
            ),
            eh,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_trip_in_flight_blocks_concurrent_tapin(self, api):
        """PRD §3.5: "concurrent attempts serialise first-writer-wins
        on `Trip.travel_status` equal to `TAPPED_IN`, with the loser
        receiving `ERR_TRIP_ALREADY_OPEN`".

        Claim: while a Trip on a card is still TAPPED_IN, a second
        tap-in on the same card is rejected with ERR_TRIP_ALREADY_OPEN.

        # difficulty: resource_temporal_overlap/trip_in_flight_blocks_concurrent_tapin
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        rh = make_rider_headers(rider["id"])
        resp = api.create_trip(
            create_trip_payload(
                card_id=card["id"],
                idempotency_key=unique_idempotency_key(),
                tap_in_at="2026-05-20T10:30:00.000Z",
            ),
            rh,
        )
        validate_error(resp, ApiErrorId.ERR_TRIP_ALREADY_OPEN.value)

    def test_reduced_fare_certificate_window_overlap(
            self, api, agency_officer_headers):
        """PRD §3.2: "two certificates of the same `program_type` for
        the same rider may not have overlapping `[valid_from,
        valid_until]` windows."
        PRD §3.2 (continued): "Two simultaneous approvals that would
        each move a certificate to `ACTIVE` with overlapping
        `[valid_from, valid_until]` windows on the same `(rider_id,
        program_type)` resolve first-writer-wins on the `PENDING` →
        `ACTIVE` transition for that pair, and the loser is rejected
        with `ERR_CERTIFICATE_WINDOW_OVERLAP`."

        Claim: a second certificate that overlaps an existing ACTIVE
        cert on (rider, program_type) is rejected with
        ERR_CERTIFICATE_WINDOW_OVERLAP either at create or on approve.

        # difficulty: resource_temporal_overlap/reduced_fare_certificate_window_overlap
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider = create_rider()
        _cert1 = create_active_reduced_fare_certificate(
            rider_id=rider["id"], program_type="SENIOR",
            valid_from="2026-01-01T00:00:00.000Z",
            valid_until="2026-12-31T23:59:59.000Z",
        )
        overlap_payload = create_reduced_fare_certificate_payload(
            rider_id=rider["id"], program_type="SENIOR",
            valid_from="2026-06-01T00:00:00.000Z",
            valid_until="2027-06-01T00:00:00.000Z",
        )
        resp_c = api.create_reduced_fare_certificate(
            overlap_payload, agency_officer_headers,
        )
        if 200 <= resp_c.status_code < 300:
            cert2 = resp_c.json()["data"]
            resp_a = api.approve_reduced_fare_certificate(
                cert2["id"], agency_officer_headers,
            )
            validate_error(
                resp_a,
                ApiErrorId.ERR_CERTIFICATE_WINDOW_OVERLAP.value,
            )
        else:
            validate_error(
                resp_c,
                ApiErrorId.ERR_CERTIFICATE_WINDOW_OVERLAP.value,
            )


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_dispute_refund_preserves_wallet_plus_settled_total(
            self, api, agency_officer_headers):
        """PRD §2.8: "the wallet share absorbing any rounding remainder
        so that the sum of FSA share and wallet share equals the
        conserved total exactly."
        PRD §3.7: "A REFUND resolution sets `refund_amount_cents` to
        the trip's `provisional_fare_cents`, transitions the trip's
        `fare_status` from `DISPUTED` to `SETTLED` with
        `settled_fare_cents` set to zero, splits the refund
        proportionally back to the `CommuterBenefitAccount.balance_cents`
        ... and back to the card's `wallet_balance_cents` ..."

        Claim: starting wallet=10000, tap-in -275, dispute REFUND on
        the PROVISIONAL trip credits 275 back to wallet (no FSA), so
        end-state wallet=10000 and Trip.settled_fare_cents=0. The
        conserved quantity (wallet + settled total for this card) is
        invariant across the compensating action.

        Note: PRD §3.7 only permits filing a dispute while the trip's
        fare_status is PROVISIONAL, so we do NOT run the sweep before
        filing. The REFUND resolution itself transitions the trip's
        fare_status to SETTLED with settled_fare_cents=0.

        # difficulty: compensating_invariant/dispute_refund_preserves_wallet_plus_settled_total
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=10_000)
        assert card["wallet_balance_cents"] == 10_000
        trip = tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
            tap_out_minutes=20,
        )
        # Trip is PROVISIONAL with provisional_fare_cents=275; wallet=9_725.
        # File + claim + REFUND (PRD §3.7 requires PROVISIONAL to file).
        d = file_dispute(trip_id=trip["id"], rider_id=rider["id"])
        d = validate_success(
            api.claim_dispute(d["id"], agency_officer_headers),
            expected_status=200,
        )
        validate_success(
            api.resolve_dispute(
                d["id"],
                resolve_dispute_payload(decision="REFUND"),
                agency_officer_headers,
            ),
            expected_status=200,
        )
        c_after = get_card(card["id"])
        t_after = get_trip(trip["id"])
        assert c_after["wallet_balance_cents"] == 10_000, (
            f"Wallet must be restored to 10000; got "
            f"{c_after['wallet_balance_cents']}"
        )
        assert t_after["settled_fare_cents"] == 0, (
            "settled_fare_cents must be 0 after REFUND; got "
            f"{t_after['settled_fare_cents']}"
        )

    def test_fsa_reversal_preserves_employer_contribution_net(self, api):
        """PRD §3.9: "A contribution may be reversed by appending a
        new `FSAContribution` with the same `account_id`, the same
        `contribution_month`, and a negated `amount_cents`; the
        original's `status` becomes `REVERSED`. The account's
        `balance_cents` is therefore exactly the sum of `amount_cents`
        across all `APPLIED` contributions (positive original entries
        plus negative reversal entries) minus all `paid_from_fsa_cents`
        debits from trips charged from that account plus all FSA-share
        refunds credited back to the account."

        Claim: contributing 5000 then reversing brings the
        contribution-ledger sum back to 0 (no intervening trips), per
        the formula in §3.9.

        # difficulty: compensating_invariant/fsa_reversal_preserves_employer_contribution_net
        """
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, employer, acct, _card, c1 = setup_rider_with_fsa(
            contribution_cents=5000,
            contribution_month="2026-05",
            topup_cents=0,
        )
        assert c1["amount_cents"] == 5000
        assert c1["status"] == "APPLIED"
        eh = make_employer_admin_headers(employer["id"])
        # Reverse c1.
        resp = api.reverse_fsa_contribution(c1["id"], eh)
        body = resp.json()
        assert 200 <= resp.status_code < 300
        neg = body.get("data", body)
        assert neg["amount_cents"] == -5000, (
            "Reversal entry must have amount_cents=-5000; got "
            f"{neg['amount_cents']}"
        )
        # Conservation: sum of APPLIED amounts on this account in this
        # month = 5000 + (-5000) = 0.
        net = c1["amount_cents"] + neg["amount_cents"]
        assert net == 0, (
            "Contribution-ledger net must return to 0 after reversal; "
            f"got {net}"
        )
