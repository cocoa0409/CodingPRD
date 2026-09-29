"""Reversals that must restore the quantity their forward action moved.

Voiding an approved warranty claim gives the reserved bearing back to the shelf
and unwinds the distributor credit, and deleting a quote line re-derives the
package money identity from the surviving lines.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    CHANNEL_MANAGER,
    WARRANTY_ANALYST,
    make_distributor_headers,
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp so two instants compare exactly."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _one_unit_of_stock_and_two_claims(api):
    """A bearing stocked to exactly one unit against a reorder point of 2, with
    two SUBMITTED claims filed by the same authorised distributor."""
    env = fx.make_warranty_environment(api, on_hand_qty=1)
    first = fx.make_submitted_claim(api, env)
    second = fx.make_submitted_claim(
        api,
        env,
        failure_cycle_count=9000,
        in_service_months=9,
        diagnostics_code="DX-BRG-08",
    )
    return env, first, second


class TestClaimVoidRestoresPartUnitsAndCredit:
    """on_hand_qty + reserved_qty stays at 1 through the approval and the void."""

    def test_01_void_returns_the_reserved_unit_and_reverses_the_credit(self, api):
        """Approving a claim swaps the single bearing from on-hand to reserved and
        voiding it swaps it back, taking the 42000-cent credit with it.

        PRD: "The part's `on_hand_qty` increases by 1 and its `reserved_qty` decreases by 1, again conserving their sum, and the part's `version` advances by 1."
        Design: Difficulty/compensating_invariant/claim_void_restores_part_unit_conservation_and_credit
        """
        env, first, _second = _one_unit_of_stock_and_two_claims(api)
        assert env["part"]["on_hand_qty"] == 1
        assert env["part"]["reserved_qty"] == 0
        a.assert_unit_conservation(env["part"], 1)

        fx.adjudicate_claim(api, first["id"], env["part"]["id"], "APPROVE")

        reserved = validate_success(
            api.get_service_part(env["part"]["id"], WARRANTY_ANALYST),
            expected_status=200,
        )
        assert reserved["on_hand_qty"] == 0
        assert reserved["reserved_qty"] == 1
        a.assert_unit_conservation(reserved, 1)
        assert reserved["stock_state"] == "BACKORDERED"

        voided = validate_success(
            api.void_warranty_claim(
                first["id"], f.void_payload("CUSTOMER_WITHDREW"), WARRANTY_ANALYST
            ),
            expected_status=200,
        )
        a.assert_claim_state(voided, "VOIDED")
        a.assert_cents(voided["covered_amount_cents"], 42000)
        assert _instant(voided["voided_at"]) == _instant("2026-08-01T00:00:00Z")

        restored = validate_success(
            api.get_service_part(env["part"]["id"], WARRANTY_ANALYST),
            expected_status=200,
        )
        assert restored["on_hand_qty"] == 1
        assert restored["reserved_qty"] == 0
        a.assert_unit_conservation(restored, 1)
        assert restored["stock_state"] == "LOW"

        distributor = validate_success(
            api.get_distributor(env["distributor"]["id"], CHANNEL_MANAGER),
            expected_status=200,
        )
        a.assert_cents(distributor["warranty_credit_cents"], 0)

    def test_02_void_releases_the_claim_the_shortage_had_blocked(self, api):
        """The approval that emptied the shelf blocked the second claim, and the
        void that refills the shelf returns that claim to SUBMITTED.

        PRD: "The part's `stock_state` is re-projected, and if the part has just left `BACKORDERED`, every claim on it sitting in `FULFILLMENT_BLOCKED` with `block_reason` of `PART_BACKORDERED` whose claimed unit has `integrity_hold` false returns to `SUBMITTED` with `block_reason` reset to `NONE`."
        Design: Difficulty/compensating_invariant/claim_void_restores_part_unit_conservation_and_credit
        """
        env, first, second = _one_unit_of_stock_and_two_claims(api)

        fx.adjudicate_claim(api, first["id"], env["part"]["id"], "APPROVE")

        blocked = validate_success(
            api.get_warranty_claim(second["id"], WARRANTY_ANALYST), expected_status=200
        )
        a.assert_claim_state(blocked, "FULFILLMENT_BLOCKED")
        assert blocked["block_reason"] == "PART_BACKORDERED"

        validate_success(
            api.void_warranty_claim(
                first["id"], f.void_payload("CUSTOMER_WITHDREW"), WARRANTY_ANALYST
            ),
            expected_status=200,
        )

        released = validate_success(
            api.get_warranty_claim(second["id"], WARRANTY_ANALYST), expected_status=200
        )
        a.assert_claim_state(released, "SUBMITTED")
        assert released["block_reason"] == "NONE"

        distributor = validate_success(
            api.get_distributor(env["distributor"]["id"], CHANNEL_MANAGER),
            expected_status=200,
        )
        assert distributor["open_claim_count"] == 1


def _quote_with_two_lines(api):
    """A DRAFT package quote discounting 5.00% over freight of 250000 cents, with
    a three-unit card-equipped vended line and a two-unit on-premises line."""
    vended = fx.make_vended_model(api)
    on_premises = fx.make_model(api)
    distributor = fx.make_distributor(api)
    env = {
        "distributor": distributor,
        "headers": make_distributor_headers(distributor["id"]),
    }
    quote = fx.make_quote(api, env, package_discount_pct=5.00, freight_cents=250000)
    first = fx.add_quote_line(
        api,
        quote["id"],
        env,
        vended["id"],
        quantity=3,
        payment_module="CARD",
        line_discount_pct=2.50,
    )
    second = fx.add_quote_line(api, quote["id"], env, on_premises["id"], quantity=2)
    return env, quote, first, second


class TestQuoteLineDeleteRestoresTheMoneyIdentity:
    """total_cents is line_subtotal_cents minus discount_cents plus freight_cents."""

    def test_01_the_identity_holds_over_both_lines(self, api):
        """Before any deletion the package rolls up the two stored line totals and
        re-rounds the 5.00% package discount over their sum.

        PRD: "After every line create and every line delete, two identities must hold: `line_subtotal_cents` equals the sum of the surviving `line_total_cents` values, and `total_cents` equals `line_subtotal_cents` minus `discount_cents` plus `freight_cents`."
        Design: Difficulty/compensating_invariant/quote_line_delete_restores_money_identity
        """
        env, quote, first, second = _quote_with_two_lines(api)

        before = validate_success(
            api.get_quote(quote["id"], env["headers"]), expected_status=200
        )
        assert before["line_count"] == 2
        a.assert_cents(before["line_subtotal_cents"], 4818063)
        a.assert_cents(before["discount_cents"], 240903)
        a.assert_cents(before["total_cents"], 4827160)
        a.assert_money_identity(before)

        first_line = validate_success(
            api.get_quote_line(first["id"], env["headers"]), expected_status=200
        )
        a.assert_cents(first_line["line_total_cents"], 2318063)
        second_line = validate_success(
            api.get_quote_line(second["id"], env["headers"]), expected_status=200
        )
        a.assert_cents(second_line["line_total_cents"], 2500000)

    def test_02_deletion_recomputes_the_identity_from_the_surviving_line(self, api):
        """Removing the vended line re-derives the subtotal from the one surviving
        line, re-rounds the package discount against it and passes freight through.

        PRD: "`total_cents` is `line_subtotal_cents` minus `discount_cents` plus `freight_cents` — the package discount applies to the subtotal only and **never** to freight, which is passed through at cost."
        Design: Difficulty/compensating_invariant/quote_line_delete_restores_money_identity
        """
        env, quote, first, second = _quote_with_two_lines(api)
        current_version = fx.read_quote_version(api, quote["id"], env)

        after = validate_success(
            api.delete_quote_line(
                quote["id"], first["id"], current_version, env["headers"]
            ),
            expected_status=200,
        )
        assert after["line_count"] == 1
        a.assert_cents(after["line_subtotal_cents"], 2500000)
        a.assert_cents(after["discount_cents"], 125000)
        a.assert_cents(after["total_cents"], 2625000)
        a.assert_quote_state(after, "DRAFT")
        a.assert_cents(after["origination_fee_cents"], 0)
        a.assert_money_identity(after)

        survivor = validate_success(
            api.get_quote_line(second["id"], env["headers"]), expected_status=200
        )
        a.assert_cents(survivor["line_total_cents"], 2500000)

        rows, _ = validate_paginated(
            api.list_quote_lines(env["headers"], quote_id=quote["id"])
        )
        assert len(rows) == 1

    def test_03_a_stale_expected_quote_version_writes_nothing(self, api):
        """A deletion presenting a version the quote has already moved past is
        refused, and the two-line money rollup is left exactly as it was.

        PRD: "If `expected_quote_version` does not equal the quote's current `version`, the request is rejected with `ERR_STALE_QUOTE_VERSION` and HTTP 412, and nothing is written."
        Design: Difficulty/compensating_invariant/quote_line_delete_restores_money_identity
        """
        env, quote, first, _second = _quote_with_two_lines(api)
        current_version = fx.read_quote_version(api, quote["id"], env)

        response = api.delete_quote_line(
            quote["id"], first["id"], current_version - 1, env["headers"]
        )
        validate_error(response, E.ERR_STALE_QUOTE_VERSION, expected_status=412)

        after = validate_success(
            api.get_quote(quote["id"], env["headers"]), expected_status=200
        )
        assert after["line_count"] == 2
        a.assert_cents(after["line_subtotal_cents"], 4818063)
        a.assert_cents(after["discount_cents"], 240903)
        a.assert_cents(after["total_cents"], 4827160)
        a.assert_money_identity(after)

        rows, _ = validate_paginated(
            api.list_quote_lines(env["headers"], quote_id=quote["id"])
        )
        assert len(rows) == 2
