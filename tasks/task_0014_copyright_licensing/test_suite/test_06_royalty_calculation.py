"""Royalty statement calculation: dual-variant (PROVISIONAL vs FINAL),
revenue-share rounding order, period alignment, advance recoupment
(PRD §3.7)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_effective_license,
    setup_royalty_dual_variant_scenario,
    setup_rounding_order_license,
    create_final_statement,
    create_provisional_statement,
    settle_statement,
    royalty_statement_payload,
    list_audit_logs_filtered,
    make_rights_holder_headers,
    ADMIN_HEADERS,
)


# ---------------------------------------------------------------------------
# PROVISIONAL vs FINAL: dual variant comparison
# ---------------------------------------------------------------------------

class TestRoyaltyDualVariant:
    """PRD §3.7: "A PROVISIONAL statement is for mid-period reporting; it
    ignores the minimum guarantee — the provisional net payable is the
    maximum of zero and the revenue share minus the remaining advance — and
    a PROVISIONAL statement never settles. A FINAL statement applies the
    full formula above, including the maximum with the minimum guarantee,
    and only FINAL statements may transition to SETTLED."
    """

    def test_provisional_vs_final_with_mg_floor(self, api):
        """PRD §3.7: with revenue_share=150000 and MG=200000, advance=50000:
        FINAL.net_payable = max(150000, 200000) - min(50000, 50000) = 150000.
        PROVISIONAL.net_payable = max(0, 150000 - 50000) = 100000.

        # difficulty: dual_variant_calc/royalty_provisional_vs_final
        """
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]

        # Provisional statement first month.
        s_prov = create_provisional_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        # Final statement second month (advance still fully unrecouped because
        # PROVISIONAL never settles per PRD §3.7).
        s_final = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-02-01T00:00:00.000Z",
            period_end_at="2026-03-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        # PROVISIONAL: revenue_share = floor(1000000 * 1500 / 10000) = 150000
        # remaining_advance = 50000; advance_recouped = min(150000, 50000) = 50000
        # net_payable = max(0, 150000 - 50000) = 100000
        assert s_prov["net_payable_cents"] == 100_000, (
            f"PRD §3.7: PROVISIONAL net_payable_cents must be 100000; "
            f"got {s_prov['net_payable_cents']}"
        )
        assert s_prov["earned_royalty_cents"] == 150_000, (
            f"PRD §3.7: PROVISIONAL earned (revenue_share) = 150000; "
            f"got {s_prov['earned_royalty_cents']}"
        )

        # FINAL: earned = max(150000, 200000) = 200000
        # advance_recouped = min(200000, 50000) = 50000
        # net_payable = 200000 - 50000 = 150000
        assert s_final["earned_royalty_cents"] == 200_000, (
            f"PRD §3.7: FINAL earned = max(revenue_share, MG) = 200000; "
            f"got {s_final['earned_royalty_cents']}"
        )
        assert s_final["net_payable_cents"] == 150_000, (
            f"PRD §3.7: FINAL net_payable = earned - advance_recouped = 150000; "
            f"got {s_final['net_payable_cents']}"
        )

    def test_provisional_statement_cannot_settle(self, api):
        """PRD §3.7: 'A PROVISIONAL statement ... never settles.'

        # difficulty: dual_variant_calc/royalty_provisional_vs_final
        """
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        s_prov = create_provisional_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        # Attempt to settle a PROVISIONAL via PAYMENT_RECEIVED — must reject
        # because only FINAL may transition to SETTLED.
        from test_helpers import emit_event_payload, unique_event_id
        payload = emit_event_payload(
            source="PAYMENT",
            event_type="PAYMENT_RECEIVED",
            ref_entity="RoyaltyStatement",
            ref_id=s_prov["id"],
            payload={"amount_cents": s_prov["net_payable_cents"], "currency": "USD"},
            external_event_id=unique_event_id("prov-pay"),
        )
        resp = api.emit_event(payload, ADMIN_HEADERS)
        # PRD only commits "only FINAL may transition to SETTLED" without
        # naming a specific error_id; framework returns ERR_INVALID_STATE for
        # this kind of unsupported transition.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_STATE.value])


# ---------------------------------------------------------------------------
# Rounding order pinned (PRD §3.7)
# ---------------------------------------------------------------------------

class TestRoyaltyRoundingOrder:
    """PRD §3.7: "the revenue share is rounded half-up first, then the
    maximum with the minimum guarantee is taken, then the recoupment is
    subtracted; rounding is not re-applied later."
    """

    def test_revenue_share_rounds_half_up_for_half_cent(self, api):
        """PRD §3.7: 'the revenue share is the product of gross_revenue_cents
        and the license's revenue_share_bps, divided by 10000, rounded half-up
        to the nearest whole cent.'

        With gross=10, revenue_share_bps=5000: 10*5000/10000=5 (exact, 5 cents).
        With gross=11, revenue_share_bps=5000: 11*5000/10000=5.5 → half-up=6.

        # difficulty: combinatorial_formula/royalty_rounding_order_pinned_mode_b
        """
        # Use a fresh setup with revshare=5000 so the half-cent boundary is
        # exercised. Term dates default to the next future window picked by
        # the setup helper (PRD §3.3: term_start strictly in the future).
        from test_helpers import setup_effective_license, create_final_statement
        b2 = setup_effective_license(
            api,
            revenue_share_bps=5000,
            minimum_guarantee_cents=0,
            advance_cents=0,
            settlement_period="MONTHLY",
        )
        s = create_final_statement(
            api, b2["license"], b2["licensor"],
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=11,
        )
        # 11 * 5000 / 10000 = 5.5 -> half-up -> 6
        assert s["earned_royalty_cents"] == 6, (
            f"PRD §3.7: 11*5000/10000=5.5 must round half-up to 6; "
            f"got {s['earned_royalty_cents']}"
        )

    def test_rounding_order_floor_with_revshare_3333_gross_333(self, api):
        """PRD §3.7: with gross=333, revenue_share_bps=3333, MG=0, advance=0:
        revenue_share = floor((333 * 3333) / 10000) = floor(110.9889) = 110.

        Note: PRD §3.7 says "rounded half-up". 333*3333/10000 = 110.9889
        which under round-half-up would be 111. The PRD ROUNDING_ORDER pin
        in the difficulty design specifies floor(...) but PRD prose says
        half-up. We test what PRD prose commits to.

        # difficulty: combinatorial_formula/royalty_rounding_order_pinned_mode_b
        """
        bundle = setup_rounding_order_license(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        s = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=333,
        )
        # PRD prose: "rounded half-up to the nearest whole cent".
        # 333 * 3333 / 10000 = 110.9889 → half-up → 111.
        # MG=0, advance=0 ⇒ earned = revenue_share, advance_recouped=0,
        # net_payable = 111.
        # Allow either 110 (floor) or 111 (half-up) since PRD/scaffold
        # have a documented disagreement. Two-reader rule: any faithful
        # PRD-only implementer rounds half-up → expect 111.
        assert s["earned_royalty_cents"] == 111, (
            f"PRD §3.7 (round half-up to nearest cent): 333*3333/10000=110.9889 → 111; "
            f"got {s['earned_royalty_cents']}"
        )
        assert s["advance_recouped_cents"] == 0
        assert s["net_payable_cents"] == 111


# ---------------------------------------------------------------------------
# Combinatorial recoupment (multi-input non-linear, three+ inputs)
# ---------------------------------------------------------------------------

class TestAdvanceRecoupmentCombinations:
    """PRD §3.7: "the advance recouped on this statement is the lesser of
    the earned royalty and the remaining advance — the system recovers as
    much of the outstanding advance as the period earned, but never more.
    ... the net payable is the earned royalty minus the advance recouped,
    which is always non-negative because of the previous step."
    """

    def test_first_final_statement_recoups_partial_advance(self, api):
        """PRD §3.7: 'the advance recouped on this statement is the lesser of
        the earned royalty and the remaining advance.'

        With advance=50000, earned=max(150000, 200000)=200000:
        remaining_advance=50000 → advance_recouped=min(200000, 50000)=50000.
        net_payable = 200000 - 50000 = 150000.

        # difficulty: combinatorial_formula/royalty_payable_three_input_nonlinear_mode_a
        """
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        s1 = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        assert s1["earned_royalty_cents"] == 200_000
        assert s1["advance_recouped_cents"] == 50_000
        assert s1["net_payable_cents"] == 150_000

    def test_advance_fully_recouped_after_first_settlement(self, api):
        """PRD §3.7: with advance=50000, MG=200000, revenue_share_bps=1500,
        first FINAL statement at gross=1000000 settles for 150000 cents.
        cumulative_advance_recouped_cents goes from 0 → 50000.
        Second FINAL at gross=1000000: remaining_advance=0, advance_recouped=0,
        net_payable=earned=200000.

        # difficulty: combinatorial_formula/royalty_payable_three_input_nonlinear_mode_a
        """
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]

        s1 = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        assert s1["net_payable_cents"] == 150_000
        assert s1["advance_recouped_cents"] == 50_000

        # Settle s1 to push cumulative_advance_recouped_cents → 50000.
        settle_statement(api, s1)

        # Re-read License to confirm the running ledger.
        license_data = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        assert license_data["cumulative_advance_recouped_cents"] == 50_000, (
            f"PRD §3.7: 'the license's cumulative_advance_recouped_cents is "
            f"increased by exactly the advance_recouped_cents of this statement.'; "
            f"got {license_data['cumulative_advance_recouped_cents']}"
        )

        # s2: now remaining_advance=0 → advance_recouped=0, net_payable=200000.
        s2 = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-02-01T00:00:00.000Z",
            period_end_at="2026-03-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        assert s2["advance_recouped_cents"] == 0, (
            f"PRD §3.7: remaining_advance=0 → advance_recouped=0; "
            f"got {s2['advance_recouped_cents']}"
        )
        assert s2["net_payable_cents"] == 200_000


# ---------------------------------------------------------------------------
# Period validity
# ---------------------------------------------------------------------------

class TestRoyaltyPeriodValidity:
    """PRD §3.7: "any misaligned or backwards period (period_start_at not
    strictly less than period_end_at) is rejected with ERR_INVALID_PERIOD."
    """

    def test_period_misaligned_with_monthly_settlement_rejected(self, api):
        """PRD §3.7: MONTHLY settlement period requires monthly windows.
        15-day window must be rejected.

        # difficulty: resource_temporal_overlap/royalty_period_alignment_to_settlement_period
        """
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        headers = make_rights_holder_headers(licensor["id"])
        body = royalty_statement_payload(
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-01-15T00:00:00.000Z",  # 14-day window, NOT monthly
            gross_revenue_cents=100_000,
            variant="FINAL",
        )
        resp = api.create_royalty_statement(license_data["id"], body, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD.value)

    def test_period_backwards_rejected(self, api):
        """PRD §3.7: period_start_at >= period_end_at → ERR_INVALID_PERIOD."""
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        headers = make_rights_holder_headers(licensor["id"])
        body = royalty_statement_payload(
            period_start_at="2026-02-01T00:00:00.000Z",
            period_end_at="2026-01-01T00:00:00.000Z",  # backwards
            gross_revenue_cents=100_000,
            variant="FINAL",
        )
        resp = api.create_royalty_statement(license_data["id"], body, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD.value)

    def test_period_aligned_with_monthly_succeeds(self, api):
        """PRD §3.7: properly monthly window is accepted (sanity contrast).

        # difficulty: resource_temporal_overlap/royalty_period_alignment_to_settlement_period
        """
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        headers = make_rights_holder_headers(licensor["id"])
        body = royalty_statement_payload(
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=100_000,
            variant="FINAL",
        )
        resp = api.create_royalty_statement(license_data["id"], body, headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
