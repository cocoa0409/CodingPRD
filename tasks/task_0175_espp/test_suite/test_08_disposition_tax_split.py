"""Dispositions: classification, qualifying / disqualifying tax split,
ownership, amend, void.

References PRD §3.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_disposition,
    create_disposition_payload,
    make_participant_headers,
    new_participant_id,
    setup_purchase_after_run,
    setup_purchase_with_disposition,
    TEST_USERS,
    update_disposition_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Disposition creation: classification + tax split
# ===========================================================================
class TestDispositionClassification:
    """PRD §3.7 classification predicate."""

    def test_disqualifying_when_dispose_before_grant_plus_2y(self, api):
        """PRD §3.7: "The disposition is classified as `QUALIFYING` if
        and only if `disposition_date` is at or after the purchase's
        `grant_date` plus two years AND at or after the purchase's
        `purchase_date` plus one year; otherwise it is classified as
        `DISQUALIFYING`."

        Claim: grant=2024-01-01, purchase=2024-07-01, dispose at
        2025-12-31 (< grant+2y) -> classification==DISQUALIFYING.
        """
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2025-12-31T00:00:00.000Z",
            disposition_date_iso="2025-12-31T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        assert_disposition(disp)
        assert disp["classification"] == "DISQUALIFYING"

    def test_qualifying_when_dispose_at_or_after_grant_plus_2y(self, api):
        """PRD §3.7: "QUALIFYING if and only if `disposition_date` is
        at or after the purchase's `grant_date` plus two years AND at
        or after the purchase's `purchase_date` plus one year".

        Claim: grant=2024-01-01, purchase=2024-07-01, dispose at
        2026-01-01 (== grant+2y, > purchase+1y) -> classification==QUALIFYING.
        """
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2026-01-02T00:00:00.000Z",
            disposition_date_iso="2026-01-01T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        assert disp["classification"] == "QUALIFYING"


class TestDispositionTaxSplit:
    """PRD §3.7 ordinary_income_cents + capital_gain_cents formulas."""

    def test_disqualifying_uses_full_purchase_spread(self, api):
        """PRD §3.7: "For a `DISQUALIFYING` disposition, ... the
        per-share ordinary income is the larger of zero and the
        difference between the purchase's `purchase_date_fmv_cents` and
        `purchase_price_cents`; `ordinary_income_cents` is
        `shares_disposed` times that per-share ordinary income; the
        per-share capital basis is `purchase_price_cents` plus the
        per-share ordinary income; and `capital_gain_cents` is
        `shares_disposed` times the difference between
        `sale_price_per_share_cents` and the per-share capital basis."

        Claim: grant=1000, purchase=2000, purchase_price=850, sale=2500,
        shares=10, DISQUALIFYING:
          ordinary_per_share = max(0, 2000 - 850) = 1150
          ordinary_income = 10 * 1150 = 11500
          basis_per_share = 850 + 1150 = 2000
          capital_gain = 10 * (2500 - 2000) = 5000
        """
        # difficulty: dual_variant_calc/disposition_tax_qualifying_vs_disqualifying
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2025-12-31T00:00:00.000Z",
            disposition_date_iso="2025-12-31T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        assert disp["classification"] == "DISQUALIFYING"
        assert disp["ordinary_income_cents"] == 11_500, (
            f"Expected 10*(2000-850)=11500, got {disp['ordinary_income_cents']}"
        )
        assert disp["capital_gain_cents"] == 5_000, (
            f"Expected 10*(2500-2000)=5000, got {disp['capital_gain_cents']}"
        )

    def test_qualifying_uses_lesser_of_actual_gain_or_theoretical_discount(
        self, api,
    ):
        """PRD §3.7: "For a `QUALIFYING` disposition, the system applies
        the IRC 423(c) lesser-of test: the actual per-share gain is
        `sale_price_per_share_cents` minus the purchase's
        `purchase_price_cents`; the theoretical per-share discount is
        the purchase's `chosen_fmv_cents` multiplied by the plan's
        `discount_bp` and divided by ten thousand, rounded half-up to
        the nearest whole cent ...; the per-share ordinary income is
        the larger of zero and the smaller of the actual gain and the
        theoretical discount; `ordinary_income_cents` is
        `shares_disposed` times that per-share ordinary income; the
        per-share capital basis is the purchase's `purchase_price_cents`
        plus the per-share ordinary income; and `capital_gain_cents`
        is `shares_disposed` times the difference between
        `sale_price_per_share_cents` and the per-share capital basis."

        Claim: chosen_fmv=1000, discount_bp=1500, purchase_price=850,
        sale=2500, shares=10, QUALIFYING:
          theoretical_per_share = round_half_up(1000 * 1500/10000) = 150
          actual_gain_per_share = 2500 - 850 = 1650
          ordinary_per_share = max(0, min(1650, 150)) = 150
          ordinary_income = 10 * 150 = 1500
          basis_per_share = 850 + 150 = 1000
          capital_gain = 10 * (2500 - 1000) = 15000
        """
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2026-01-02T00:00:00.000Z",
            disposition_date_iso="2026-01-01T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        assert disp["classification"] == "QUALIFYING"
        assert disp["ordinary_income_cents"] == 1_500, (
            f"Expected 10*min(1650,150)=1500, got {disp['ordinary_income_cents']}"
        )
        assert disp["capital_gain_cents"] == 15_000, (
            f"Expected 10*(2500-1000)=15000, got {disp['capital_gain_cents']}"
        )


# ===========================================================================
# Ownership + validation rejections
# ===========================================================================
class TestDispositionGuards:

    def test_non_owner_cannot_post_disposition(self, api):
        """PRD §3.7: "`purchase_id` (the purchase being disposed against,
        which must belong to the acting participant — otherwise
        `ERR_NOT_OWNER`)".

        Claim: POST /dispositions where X-User-ID != Purchase.participant_id
        -> ERR_NOT_OWNER.
        """
        plan, _op, pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
        )
        advance_clock_to("2026-01-02T00:00:00.000Z")
        attacker = new_participant_id()
        resp = api.create_disposition(
            create_disposition_payload(
                purchase_id=purchase["id"],
                disposition_date="2026-01-01T00:00:00.000Z",
                shares_disposed=5,
                sale_price_per_share_cents=2000,
            ),
            make_participant_headers(attacker),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)

    def test_disposition_date_before_purchase_rejected(self, api):
        """PRD §3.7: "Two date-window checks are enforced:
        `disposition_date` must be at or after the purchase's
        `purchase_date` and at or before the system clock's
        `current_time`, otherwise `ERR_DISPOSITION_DATE_OUT_OF_RANGE`."

        Claim: disposition_date < Purchase.purchase_date ->
        ERR_DISPOSITION_DATE_OUT_OF_RANGE.
        """
        plan, _op, pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
        )
        advance_clock_to("2026-01-02T00:00:00.000Z")
        resp = api.create_disposition(
            create_disposition_payload(
                purchase_id=purchase["id"],
                disposition_date="2024-06-30T00:00:00.000Z",  # < purchase_date
                shares_disposed=1,
                sale_price_per_share_cents=2000,
            ),
            make_participant_headers(pid),
        )
        validate_error(
            resp, ApiErrorId.ERR_DISPOSITION_DATE_OUT_OF_RANGE.value,
        )

    def test_shares_exceeding_balance_rejected(self, api):
        """PRD §3.7: "A share-balance check is enforced: `shares_disposed`
        may not exceed the purchase's `shares_purchased` minus the sum
        of `shares_disposed` over prior dispositions ... otherwise
        `ERR_SHARES_EXCEED_BALANCE`."

        Claim: shares_disposed > shares_purchased ->
        ERR_SHARES_EXCEED_BALANCE.
        """
        plan, _op, pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        # Use the actual purchase_date so the date-window check passes
        # and we exercise only the share-balance branch.
        # shares_purchased == 10 (8500/850); request 11.
        resp = api.create_disposition(
            create_disposition_payload(
                purchase_id=purchase["id"],
                disposition_date=purchase["purchase_date"],
                shares_disposed=11,
                sale_price_per_share_cents=2000,
            ),
            make_participant_headers(pid),
        )
        validate_error(resp, ApiErrorId.ERR_SHARES_EXCEED_BALANCE.value)


# ===========================================================================
# Purchase.disposition_status side effect — PRD §3.7
# ===========================================================================
class TestPurchaseDispositionStatusFlip:

    def test_full_share_dispose_flips_purchase_status(self, api):
        """PRD §3.7: "When the supplied `shares_disposed` equals the
        remaining undisposed share count on the purchase, the system
        also flips the purchase's `disposition_status` from `HELD` to
        either `DISPOSED_QUALIFYING` or `DISPOSED_DISQUALIFYING`,
        matching the classification."

        Claim: dispose ALL shares as DISQUALIFYING -> Purchase.disposition_status
        becomes DISPOSED_DISQUALIFYING.
        """
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2025-12-31T00:00:00.000Z",
            disposition_date_iso="2025-12-31T00:00:00.000Z",
            shares_disposed=10,  # all shares
            sale_price_per_share_cents=2500,
        )
        # Re-read Purchase.
        resp = api.get_purchase(
            purchase["id"], TEST_USERS["plan_admin_headers"],
        )
        data = validate_success(resp)
        assert data["disposition_status"] == "DISPOSED_DISQUALIFYING"

    def test_partial_share_dispose_keeps_purchase_held(self, api):
        """PRD §3.7: "When the supplied `shares_disposed` equals the
        remaining undisposed share count on the purchase, the system
        also flips the purchase's `disposition_status` ..." (implying
        the flip is gated on EQUALS, not <).

        Claim: dispose 5 of 10 shares -> Purchase.disposition_status
        stays HELD (no flip).
        """
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2025-12-31T00:00:00.000Z",
            disposition_date_iso="2025-12-31T00:00:00.000Z",
            shares_disposed=5,
            sale_price_per_share_cents=2500,
        )
        resp = api.get_purchase(
            purchase["id"], TEST_USERS["plan_admin_headers"],
        )
        data = validate_success(resp)
        assert data["disposition_status"] == "HELD"


# ===========================================================================
# Amend + Void lifecycle — PRD §3.7
# ===========================================================================
class TestDispositionAmendAndVoid:

    def test_amend_recomputes_capital_gain(self, api):
        """PRD §3.7: "The owning participant may amend a `REPORTED`
        disposition through a patch ... On amendment, the system
        re-evaluates classification, recomputes `ordinary_income_cents`
        and `capital_gain_cents` from the current purchase fields, and
        updates the disposition's status to `AMENDED`."

        Claim: PATCH with new sale_price -> status==AMENDED and
        capital_gain_cents recomputed.
        """
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2025-12-31T00:00:00.000Z",
            disposition_date_iso="2025-12-31T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        h = make_participant_headers(pid)
        # Original DISQUALIFYING: cap gain = 10*(2500-2000)=5000.
        # New sale_price=3000 -> cap gain = 10*(3000-2000)=10000.
        resp = api.update_disposition(
            disp["id"],
            update_disposition_payload(
                version=disp["version"],
                sale_price_per_share_cents=3000,
            ),
            h,
        )
        data = validate_success(resp)
        assert data["status"] == "AMENDED"
        assert data["capital_gain_cents"] == 10_000

    def test_void_restores_purchase_to_held(self, api):
        """PRD §3.7: "The owning participant may also void a disposition
        through a delete operation. ... the disposition's status moves
        to `VOIDED`. As a side effect, the purchase's `disposition_status`
        is restored to `HELD` if no other non-voided disposition exists
        on the purchase."

        Claim: DELETE the only Disposition -> Purchase.disposition_status
        reverts to HELD.
        """
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2025-12-31T00:00:00.000Z",
            disposition_date_iso="2025-12-31T00:00:00.000Z",
            shares_disposed=10,
            sale_price_per_share_cents=2500,
        )
        h = make_participant_headers(pid)
        # Verify status flipped first.
        p_resp = api.get_purchase(
            purchase["id"], TEST_USERS["plan_admin_headers"],
        )
        assert p_resp.json()["data"]["disposition_status"] \
            == "DISPOSED_DISQUALIFYING"
        # DELETE.
        del_resp = api.delete_disposition(disp["id"], h)
        assert del_resp.status_code == 204, (
            f"PRD §4: DELETE /dispositions/{{id}} returns 204; got "
            f"{del_resp.status_code}: {del_resp.text}"
        )
        # Re-read purchase.
        p_resp = api.get_purchase(
            purchase["id"], TEST_USERS["plan_admin_headers"],
        )
        assert p_resp.json()["data"]["disposition_status"] == "HELD"

    def test_amend_on_voided_disposition_rejected(self, api):
        """PRD §3.7: "A patch is allowed only when the disposition's
        status is `REPORTED` (an `AMENDED` or `VOIDED` disposition is
        rejected with `ERR_INVALID_DISPOSITION_STATE`)."

        Claim: PATCH after VOID -> ERR_INVALID_DISPOSITION_STATE.
        """
        plan, _op, pid, purchase, disp = setup_purchase_with_disposition(
            purchase_kwargs=dict(
                grant_date_fmv_cents=1000,
                purchase_date_fmv_cents=2000,
                contribution_amount_cents=8500,
                contribution_rate_bp=1500,
                initial_clock_iso="2023-12-01T00:00:00.000Z",
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            advance_clock_iso="2025-12-31T00:00:00.000Z",
            disposition_date_iso="2025-12-31T00:00:00.000Z",
            shares_disposed=5,
            sale_price_per_share_cents=2500,
        )
        h = make_participant_headers(pid)
        api.delete_disposition(disp["id"], h)
        resp = api.update_disposition(
            disp["id"],
            update_disposition_payload(
                version=disp["version"] + 1,
                sale_price_per_share_cents=3000,
            ),
            h,
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_DISPOSITION_STATE.value,
        )
