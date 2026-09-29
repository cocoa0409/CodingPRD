"""Credit exposure: the invoice-triggered utilization freeze chain and hold precedence.

Every test builds its own world from published endpoints against an empty database.
"""

from test_helpers import (
    ApiErrorId,
    CREDIT_MANAGER,
    SKU_SHINGLE_BUNDLE,
    create_credit_line,
    create_draft_order,
    create_pro_account,
    create_store,
    create_store_stock,
    freeze_credit_line,
    make_contractor_admin_headers,
    read_credit_line,
    read_pro_account,
    read_pro_order,
    setup_fulfilled_will_call_order,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Shared world builders (inlined per test; no cross-test state)                 #
# --------------------------------------------------------------------------- #


def _store_for_credit_tests(will_call_bay_slots: int = 1):
    store = create_store(
        store_code="HD-101",
        region_code="MIDWEST",
        state_code="IL",
        distance_rank=1,
        will_call_bay_slots=will_call_bay_slots,
        lift_gate_available=True,
        tax_rate_pct=0.0825,
        max_stage_hours=48,
    )
    stock = create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    return store, stock


def _gold_account(home_store_id: str):
    return create_pro_account(
        home_store_id,
        business_name="Ridgeline Roofing",
        po_required=False,
        job_name_required=False,
        tier_review_mode="PINNED_AT_REVIEW",
        baseline_volume_cents=6_000_000,
    )


def _fulfilled_order_at_high_utilization():
    """GOLD account on a 500000-cent line with a fulfilled 220-unit credit-line order."""
    store, _ = _store_for_credit_tests()
    account = _gold_account(store["id"])
    credit_line = create_credit_line(account["id"], limit_cents=500_000, terms_days=30)
    bundle = setup_fulfilled_will_call_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 220)],
        stage_start="2026-08-01T08:00:00Z",
        stage_hours=6,
        payment_method="CREDIT_LINE",
        lift_gate_required=False,
        job_lot_required=False,
        resale_purchase=False,
    )
    return store, account, credit_line, bundle["order"]


def _draft_order_over_headroom_on_a_frozen_line():
    """A DRAFT 300-unit credit-line order (total 616700) on a manually frozen 500000 line."""
    store, _ = _store_for_credit_tests(will_call_bay_slots=2)
    account = _gold_account(store["id"])
    credit_line = create_credit_line(account["id"], limit_cents=500_000, terms_days=30)
    order, _ = create_draft_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 300)],
        payment_method="CREDIT_LINE",
        delivery_mode="WILL_CALL",
        lift_gate_required=False,
        job_lot_required=False,
        resale_purchase=False,
    )
    freeze_credit_line(credit_line["id"], "MANUAL_REVIEW")
    return store, account, credit_line, order


# --------------------------------------------------------------------------- #
# Invoicing a fulfilled order: exposure -> freeze -> account hold                #
# --------------------------------------------------------------------------- #


class TestInvoiceUtilizationFreezeChain:
    def test_invoice_recomputed_exposure_freezes_the_credit_line(self, api):
        """PRD §3.9: "A `CreditManager` **invoices** a fulfilled order, moving `credit_status` from `AUTHORIZED` to `INVOICED`."
        PRD §3.9: "Hop one recomputes the credit line's `exposure_cents` and `available_cents`."
        PRD §3.9: "Hop two puts that freshly recomputed exposure through the **credit-utilization review**: when `exposure_cents` reaches or exceeds the limit multiplied by 90 percent — rounded half up to a whole cent — the credit line takes its own `ACTIVE` to `FROZEN` transition with `frozen_reason_code` set to `UTILIZATION_REVIEW`."
        PRD §3.3: "Its threshold is 90 percent of the limit: the freeze threshold in cents is `limit_cents` multiplied by nine tenths, rounded half up to a whole cent."
        PRD §3.3: "It is the sum of `total_cents` across the account's orders whose `credit_status` is `AUTHORIZED` or `INVOICED`, less the sum of `credited_refund_cents` across those same orders."

        Design: Difficulty/transitive_cascade/invoice_utilization_freeze_cascades_credit_line_then_account_hold
        """
        store, account, credit_line, order = _fulfilled_order_at_high_utilization()

        invoiced = validate_success(api.invoice_pro_order(order["id"], CREDIT_MANAGER))
        assert invoiced["credit_status"] == "INVOICED"

        line_after = read_credit_line(credit_line["id"])
        assert line_after["exposure_cents"] == 452247
        assert line_after["available_cents"] == 47753
        assert line_after["status"] == "FROZEN"
        assert line_after["frozen_reason_code"] == "UTILIZATION_REVIEW"

    def test_utilization_freeze_cascades_the_account_onto_hold(self, api):
        """PRD §3.9: "Hop three follows from that freeze: the owning account's `status` moves from `ACTIVE` to `HOLD`."
        PRD §3.3: "Both paths do the same three things — they move `status` from `ACTIVE` to `FROZEN`, they increment the line's `version`, and they cascade into the owning account, driving its `status` from `ACTIVE` to `HOLD`."
        PRD §3.9: "Invoicing also constitutes a **tier review event**, recomputing the account's `trailing_volume_cents`, `tier_code` and `tier_discount_pct` and stamping `tier_reviewed_at`."
        PRD §3.2: "`trailing_volume_cents` is then the account's `baseline_volume_cents` plus the sum of `net_volume_cents` across the account's in-window orders, where an order's `net_volume_cents` is its `subtotal_cents` less its `credited_gross_refund_cents` — returns net out at their gross refund value, before any restocking fee."
        PRD §2.9: "Remember that trailing volume is stored in cents, so the `GOLD` opening figure is five million cents, `PLATINUM`'s is twenty million cents and `DIAMOND`'s is fifty million cents."

        Design: Difficulty/transitive_cascade/invoice_utilization_freeze_cascades_credit_line_then_account_hold
        """
        store, account, credit_line, order = _fulfilled_order_at_high_utilization()

        validate_success(api.invoice_pro_order(order["id"], CREDIT_MANAGER))

        account_after = read_pro_account(account["id"])
        assert account_after["status"] == "HOLD"
        assert account_after["trailing_volume_cents"] == 6417780
        assert account_after["tier_code"] == "GOLD"

    def test_cascaded_account_hold_blocks_an_unrelated_order_submission(self, api):
        """PRD §3.9: "Hop three follows from that freeze: the owning account's `status` moves from `ACTIVE` to `HOLD`."
        PRD §3.3: "An account on `HOLD` is barred from five operations, each rejected with `ERR_ACCOUNT_ON_HOLD`: submitting a job quote, revising a job quote, approving a job quote, accepting a job quote, and submitting a pro order."
        PRD §3.6: "A new order sits at `fulfillment_status` `DRAFT` and `credit_status` `UNBILLED`, with every money field null until it is priced."

        Design: Difficulty/transitive_cascade/invoice_utilization_freeze_cascades_credit_line_then_account_hold
        """
        store, account, credit_line, order = _fulfilled_order_at_high_utilization()
        second_order, _ = create_draft_order(
            account["id"],
            store["id"],
            [(SKU_SHINGLE_BUNDLE, 2)],
            payment_method="CARD",
            delivery_mode="WILL_CALL",
            lift_gate_required=False,
            job_lot_required=False,
            resale_purchase=False,
        )

        validate_success(api.invoice_pro_order(order["id"], CREDIT_MANAGER))

        validate_error(
            api.submit_pro_order(
                second_order["id"], make_contractor_admin_headers(account["id"])
            ),
            ApiErrorId.ERR_ACCOUNT_ON_HOLD.value,
            expected_status=409,
        )
        assert (
            read_pro_order(second_order["id"], account["id"])["fulfillment_status"]
            == "DRAFT"
        )


# --------------------------------------------------------------------------- #
# Which failure surfaces when a submit breaks both the hold rung and headroom    #
# --------------------------------------------------------------------------- #


class TestAccountHoldOutranksCreditHeadroom:
    def test_submit_on_held_account_over_headroom_reports_account_on_hold(self, api):
        """PRD §2.11: "When a single request could fail several checks, the server must report the failure that comes first in the following ladder."
        PRD §2.11: "The ladder is global: it holds across every endpoint, and where a rung applies to only some endpoints, its scope is stated."
        PRD §2.11: "**Account hold** — the owning `ProAccount` has `status` `ACTIVE`, otherwise `ERR_ACCOUNT_ON_HOLD`. Applies to five operations: submitting a job quote, revising a job quote, approving a job quote, accepting a job quote, and submitting a pro order."
        PRD §2.11: "**Credit headroom** — for an order paying on terms, the order's `total_cents` is no greater than the credit line's `available_cents`, otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). Applies to submitting an order."
        PRD §2.11: "Because the account-hold rung (14) precedes the credit-line rung (15), an order submitted for an account on hold whose credit line is also frozen reports `ERR_ACCOUNT_ON_HOLD`."
        PRD §3.3: "Both paths do the same three things — they move `status` from `ACTIVE` to `FROZEN`, they increment the line's `version`, and they cascade into the owning account, driving its `status` from `ACTIVE` to `HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/account_hold_state_outranks_credit_limit_fiscal
        """
        store, account, credit_line, order = _draft_order_over_headroom_on_a_frozen_line()
        admin_headers = make_contractor_admin_headers(account["id"])

        validate_error(
            api.submit_pro_order(order["id"], admin_headers),
            ApiErrorId.ERR_ACCOUNT_ON_HOLD.value,
            expected_status=409,
        )

        order_after = read_pro_order(order["id"], account["id"])
        assert order_after["fulfillment_status"] == "DRAFT"
        assert order_after["credit_status"] == "UNBILLED"

    def test_same_submit_reports_credit_limit_exceeded_once_the_hold_is_lifted(self, api):
        """PRD §2.11: "**Credit headroom** — for an order paying on terms, the order's `total_cents` is no greater than the credit line's `available_cents`, otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). Applies to submitting an order."
        PRD §3.3: "When the order's `payment_method` is `CREDIT_LINE`, its `total_cents` must be no greater than the line's `available_cents`; the comparison is inclusive, so an order landing exactly on the remaining headroom is accepted, and one cent beyond it is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."
        PRD §3.3: "Reinstating the line does **not** by itself lift the account's hold."
        PRD §3.3: "That is a separate act on the **account**, moving its `status` from `HOLD` to `ACTIVE` and incrementing its `version`, and it is refused with `ERR_CREDIT_LINE_FROZEN` while the account's credit line is still frozen."

        Design: Difficulty/priority_pair_validation_conflict/account_hold_state_outranks_credit_limit_fiscal
        """
        store, account, credit_line, order = _draft_order_over_headroom_on_a_frozen_line()
        admin_headers = make_contractor_admin_headers(account["id"])

        validate_error(
            api.submit_pro_order(order["id"], admin_headers),
            ApiErrorId.ERR_ACCOUNT_ON_HOLD.value,
            expected_status=409,
        )

        reinstated_line = validate_success(
            api.reinstate_credit_line(credit_line["id"], CREDIT_MANAGER)
        )
        assert reinstated_line["status"] == "ACTIVE"
        reinstated_account = validate_success(
            api.reinstate_pro_account(account["id"], CREDIT_MANAGER)
        )
        assert reinstated_account["status"] == "ACTIVE"

        validate_error(
            api.submit_pro_order(order["id"], admin_headers),
            ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value,
            expected_status=402,
        )

        order_after = read_pro_order(order["id"], account["id"])
        assert order_after["fulfillment_status"] == "DRAFT"
        assert order_after["credit_status"] == "UNBILLED"
