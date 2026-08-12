"""Disbursement instructions: file-state gate, seller-net computation, fiscal
exactness gates, and the conditional lien_id field (PRD §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_disbursement,
    assert_disbursement,
    complete_title_search,
    create_disbursement_payload,
    draft_disbursement,
    get_escrow_file,
    get_statement,
    lien_by_amount,
    make_finding,
    make_manager_headers,
    order_title_search,
    release_disbursement,
    set_clock,
    setup_cleared_file,
    setup_closed_file,
    setup_closed_file_with_released_lien,
    setup_funded_file,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]

DUE_HIGH = 250_560_553  # price 250,000,000 / annual 120,000 / DAILY 2026-06-30
HIGH_PRICE_OVERRIDES = {
    "purchase_price_cents": 250_000_000,
    "annual_registration_fee_cents": 120_000,
}


class TestReleaseRequiresFileClosed:
    def test_release_on_funded_file_rejected_invalid_transition(self, api):
        """PRD §3.6: "An `EscrowManager` releases an `APPROVED` instruction, but
        only while the parent file is in `CLOSED` or `RECORDED`, and only when
        three checks pass."

        A FUNDED file does not satisfy the state gate even though the balance is
        sufficient.

        Design: Difficulty/cross_entity_state_dependency/x2_disbursement_release_requires_file_closed
        """
        ctx = setup_funded_file(file_overrides=dict(HIGH_PRICE_OVERRIDES))
        instruction = draft_disbursement(
            ctx["file"]["id"], ctx["seller"]["id"], 100_000, "SELLER_PROCEEDS",
        )
        approve_disbursement(instruction["id"], "mgr-1")
        res = api.release_disbursement(instruction["id"], make_manager_headers("mgr-1"))
        validate_error(res, ApiErrorId.ERR_INVALID_TRANSITION, expected_status=409)

    def test_failed_release_leaves_instruction_and_balance_untouched(self, api):
        """PRD §3.6: "An `EscrowManager` releases an `APPROVED` instruction, but
        only while the parent file is in `CLOSED` or `RECORDED`, and only when
        three checks pass."
        PRD §3.6: "A successful release moves the instruction to `RELEASED` and
        recomputes the file's `escrow_balance_cents` and
        `seller_net_proceeds_cents`."

        With the state gate failing there is no release, so no recompute.

        Design: Difficulty/cross_entity_state_dependency/x2_disbursement_release_requires_file_closed
        """
        ctx = setup_funded_file(file_overrides=dict(HIGH_PRICE_OVERRIDES))
        instruction = draft_disbursement(
            ctx["file"]["id"], ctx["seller"]["id"], 100_000, "SELLER_PROCEEDS",
        )
        approve_disbursement(instruction["id"], "mgr-1")
        api.release_disbursement(instruction["id"], make_manager_headers("mgr-1"))

        after = validate_success(api.get_disbursement(instruction["id"], OFFICER), 200)
        assert after["status"] == "APPROVED"
        assert get_escrow_file(ctx["file"]["id"])["escrow_balance_cents"] == DUE_HIGH


class TestSellerNetAfterPayoff:
    def test_released_lien_payoff_updates_balance_and_seller_net(self, api):
        """PRD §3.6: "The seller's net figure is `purchase_price_cents +
        proration_amount_cents - escrow_fee_cents`, minus the sum of `RELEASED`
        disbursements whose purpose is `LIEN_PAYOFF`, minus the sum of `RELEASED`
        disbursements whose purpose is `TAX_REMITTANCE`."
        PRD §3.5: "Its arrival triggers two recomputations: `total_funded_cents`
        becomes the sum of `amount_cents` across all `RECEIVED` deposits on the
        file, and `escrow_balance_cents` becomes that total minus the sum of
        `amount_cents` across all `RELEASED` disbursements on the file."

        Price 250,000,000 / annual 0 -> fee 500,000, due 250,500,000. Paying off
        the 500,000 lien: balance 250,000,000; net 250,000,000 + 0 - 500,000
        (fee) - 500,000 (payoff) = 249,000,000.

        Design: Corner/calculations/c_seller_net_after_payoff
        """
        ctx = setup_closed_file_with_released_lien(amount_cents=500_000,
                                                   quoted_payoff_cents=500_000)
        instruction = draft_disbursement(
            ctx["file"]["id"], ctx["lender"]["id"], 500_000, "LIEN_PAYOFF",
            lien_id=ctx["lien"]["id"],
        )
        approve_disbursement(instruction["id"], "mgr-1")
        released = release_disbursement(instruction["id"], "mgr-1")
        assert_disbursement(released)
        assert released["status"] == "RELEASED"

        statement = get_statement(ctx["file"]["id"])
        assert statement["escrow_balance_cents"] == 250_000_000
        assert statement["seller_net_proceeds_cents"] == 249_000_000


class TestFiscalExactnessGates:
    def test_payoff_amount_must_equal_frozen_payoff(self, api):
        """PRD §3.6: "Third, when the purpose is `LIEN_PAYOFF`, the instruction's
        `amount_cents` must equal the lien's frozen `amount_paid_cents` exactly;
        a mismatch is rejected with `ERR_PAYOFF_MISMATCH`."

        499,999 against a frozen 500,000 payoff.

        Design: Corner/errors/er_payoff_amount_mismatch
        """
        ctx = setup_closed_file_with_released_lien(amount_cents=500_000,
                                                   quoted_payoff_cents=500_000)
        instruction = draft_disbursement(
            ctx["file"]["id"], ctx["lender"]["id"], 499_999, "LIEN_PAYOFF",
            lien_id=ctx["lien"]["id"],
        )
        approve_disbursement(instruction["id"], "mgr-1")
        res = api.release_disbursement(instruction["id"], make_manager_headers("mgr-1"))
        validate_error(res, ApiErrorId.ERR_PAYOFF_MISMATCH, expected_status=422)

        after = validate_success(api.get_disbursement(instruction["id"], OFFICER), 200)
        assert after["status"] == "APPROVED"
        assert get_escrow_file(ctx["file"]["id"])["escrow_balance_cents"] == 250_500_000

    def test_shortfall_and_exact_zero_boundary(self, api):
        """PRD §3.6: "First, the instruction's `amount_cents` must not exceed the
        file's current `escrow_balance_cents` — equality is allowed, so an
        exact-zero balance is reachable; a shortfall is rejected with
        `ERR_ESCROW_SHORTFALL`."

        250,560,554 over a 250,560,553 balance shortfalls; releasing exactly the
        balance succeeds and drives the balance to exactly 0.

        Design: Corner/errors/er_shortfall_on_release_and_exact_zero_boundary
        """
        ctx = setup_closed_file(file_overrides=dict(HIGH_PRICE_OVERRIDES))
        file_id = ctx["file"]["id"]

        over = draft_disbursement(file_id, ctx["seller"]["id"], DUE_HIGH + 1,
                                  "SELLER_PROCEEDS")
        approve_disbursement(over["id"], "mgr-1")
        res = api.release_disbursement(over["id"], make_manager_headers("mgr-1"))
        validate_error(res, ApiErrorId.ERR_ESCROW_SHORTFALL, expected_status=422)

        exact = draft_disbursement(file_id, ctx["seller"]["id"], DUE_HIGH,
                                   "SELLER_PROCEEDS")
        approve_disbursement(exact["id"], "mgr-2")
        released = release_disbursement(exact["id"], "mgr-2")
        assert released["status"] == "RELEASED"
        assert get_statement(file_id)["escrow_balance_cents"] == 0


class TestLienReleasedGateOnPayoff:
    def test_payoff_release_against_unreleased_lien_rejected(self, api):
        """PRD §3.6: "Second, when the purpose is `LIEN_PAYOFF`, the referenced
        lien must be in `RELEASED`; otherwise the release is rejected with
        `ERR_LIEN_NOT_RELEASED`."
        PRD §3.3: "Ordering is permitted while the file is in `OPENED`,
        `SEARCH_ORDERED`, `SEARCH_COMPLETE`, `CLEARED`, `FUNDED`, `CLOSED`, or
        `RECORDED`."

        A post-close re-search discovers a new lien that is still DISCOVERED; the
        referential gate fires before the fiscal match check.

        Design: Corner/errors/er_lien_not_released_on_payoff
        """
        ctx = setup_closed_file(with_lender=True,
                                file_overrides=dict(HIGH_PRICE_OVERRIDES))
        file_id = ctx["file"]["id"]

        set_clock("2026-07-02T00:00:00Z")
        search = order_title_search(file_id)
        complete_title_search(search["id"], [
            make_finding(ctx["lender"]["id"], 75_000, lien_type="STATE",
                         filed_at="2026-06-15"),
        ])
        lien = lien_by_amount(file_id, 75_000)
        assert lien["status"] == "DISCOVERED"

        instruction = draft_disbursement(
            file_id, ctx["lender"]["id"], 1, "LIEN_PAYOFF", lien_id=lien["id"],
        )
        approve_disbursement(instruction["id"], "mgr-1")
        res = api.release_disbursement(instruction["id"], make_manager_headers("mgr-1"))
        validate_error(res, ApiErrorId.ERR_LIEN_NOT_RELEASED, expected_status=409)

        after = validate_success(api.get_disbursement(instruction["id"], OFFICER), 200)
        assert after["status"] == "APPROVED"


class TestConditionalLienIdField:
    def test_lien_payoff_without_lien_id_rejected(self, api):
        """PRD §3.6: "When `purpose` is `LIEN_PAYOFF`, a `lien_id` must also be
        supplied, and it must reference a lien belonging to the same file; for any
        other purpose, `lien_id` is omitted."

        Omitting the conditionally required `lien_id` is a malformed request.

        Design: Corner/validations/v_lien_payoff_without_lien_id_returns_invalid_request
        """
        ctx = setup_cleared_file()
        version = get_escrow_file(ctx["file"]["id"])["version"]
        payload = create_disbursement_payload(
            ctx["seller"]["id"], 1_000, "LIEN_PAYOFF", version,
        )
        res = api.create_disbursement(ctx["file"]["id"], payload, OFFICER)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
