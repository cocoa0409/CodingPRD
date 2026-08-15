"""Checkout: pinned totals order, tier snapshot semantics, credit gate,
compensating void (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    add_line,
    api_client as api,
    create_account,
    create_agreement,
    create_category,
    create_placed_item,
    create_sale,
    create_zone,
    finalize_sale,
    get_account,
    get_success_data,
    push_trailing_volume,
    setup_contractor_sale_with_line,
    setup_walk_in_sale_with_line,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

CASHIER = TEST_USERS["cashier_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
ADMIN = TEST_USERS["warehouse_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / sale_totals_per_line_rounding_order
# ---------------------------------------------------------------------------

def _setup_lumber_agreement_sale():
    """Category LUMBER2 + ACTIVE account + agreement (0.10 off, min 3.0 SQFT) +
    items I1 (1.5 SQFT) and I2 (2.5 SQFT) both override-priced 199 + sale with
    the agreement attached."""
    category = create_category(code="LUMBER2", display_name="Lumber 2",
                               pricing_model="PER_SQFT", base_rate_cents=200)
    account = create_account(company_name="Ctor D", contact_email="d@x.com")
    agreement = create_agreement(account["id"], category["id"], discount_pct=0.10,
                                 min_quantity=3.0, quantity_unit="SQFT")
    zone = create_zone(code="Z2", display_name="Zone 2")
    item1 = create_placed_item(category["id"], zone["id"], 199, description_text="I1",
                               measure_qty=1.5, measure_unit="SQFT", estimated_weight_lbs=5)
    item2 = create_placed_item(category["id"], zone["id"], 199, description_text="I2",
                               measure_qty=2.5, measure_unit="SQFT", estimated_weight_lbs=8)
    sale = create_sale("CONTRACTOR_ACCOUNT", contractor_id=account["id"],
                       agreement_id=agreement["id"])
    return {"category": category, "account": account, "agreement": agreement,
            "zone": zone, "item1": item1, "item2": item2, "sale": sale}


class TestSaleTotalsPerLineRoundingOrder:
    def test_sale_line_totals_rounded_per_line(self, api):
        """PRD §3.9: "Adding a line moves the item to `RESERVED` (it keeps
        occupying its zone slot), captures the item's `current_price_cents` into
        the line's `unit_price_cents` at that moment, and computes
        `line_total_cents` as the unit price multiplied by the line's `quantity`,
        rounded half-up to integer cents — per-line rounding happens before any
        subtotal summation, and summing first and rounding once is non-conformant."

        Design: Difficulty/combinatorial_formula/sale_totals_per_line_rounding_order
        """
        ctx = _setup_lumber_agreement_sale()
        line1 = add_line(ctx["sale"]["id"], ctx["item1"]["id"], quantity=1.5)
        line2 = add_line(ctx["sale"]["id"], ctx["item2"]["id"], quantity=2.5)
        assert line1["line_total_cents"] == 299, (
            f"round_half_up(199*1.5) = 299, got {line1['line_total_cents']}")
        assert line2["line_total_cents"] == 498, (
            f"round_half_up(199*2.5) = 498, got {line2['line_total_cents']}")

        sale = finalize_sale(ctx["sale"]["id"])
        assert sale["subtotal_cents"] == 797, (
            f"per-line-first subtotal 299+498 = 797 (sum-then-round would give 796), "
            f"got {sale['subtotal_cents']}")

    def test_sale_finalize_discount_and_tax_pinned_order(self, api):
        """PRD §3.9: "`bulk_discount_cents` is the subtotal multiplied by that
        chosen percentage, rounded half-up; `tax_cents` is the subtotal minus the
        bulk discount, the difference multiplied by the seven percent sales-tax
        rate, rounded half-up; and `total_cents` is the subtotal minus the bulk
        discount plus the tax."
        PRD §3.9: "The agreement percentage is the attached agreement's
        `discount_pct` when all of the following hold — the sale references an
        `agreement_id`, the agreement stands `ACTIVE`, the clock lies inside its
        validity window, and the sale's line quantities for items of the
        agreement's `category_id` sum to at least the agreement's `min_quantity` —
        and zero otherwise."

        Design: Difficulty/combinatorial_formula/sale_totals_per_line_rounding_order
        """
        ctx = _setup_lumber_agreement_sale()
        add_line(ctx["sale"]["id"], ctx["item1"]["id"], quantity=1.5)
        add_line(ctx["sale"]["id"], ctx["item2"]["id"], quantity=2.5)
        sale = finalize_sale(ctx["sale"]["id"])
        assert sale["discount_pct_applied"] == 0.10, (
            "agreement 0.10 beats the STANDARD tier's zero (qualifying 4.0 SQFT >= 3.0)")
        assert sale["bulk_discount_cents"] == 80, (
            f"round_half_up(797*0.10) = 80, got {sale['bulk_discount_cents']}")
        assert sale["tax_cents"] == 50, (
            f"round_half_up((797-80)*0.07) = 50, got {sale['tax_cents']}")
        assert sale["total_cents"] == 767, (
            f"797 - 80 + 50 = 767, got {sale['total_cents']}")


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / sale_discount_snapshot_vs_live_tier
# ---------------------------------------------------------------------------

def _setup_snapshot_divergence(code="PANELS", zone_code="Z1", company="Ctor C"):
    """Account; items BIG (override 2336449) and SMALL (override 100000) placed;
    S1 opened first (snapshot taken before any volume), S2 then finalizes BIG so
    the account's trailing volume reaches exactly 2500000 (SILVER)."""
    category = create_category(code=code, display_name=code.title(),
                               base_rate_cents=1000)
    account = create_account(company_name=company, contact_email=f"{code.lower()}@x.com")
    zone = create_zone(code=zone_code, display_name=f"Zone {zone_code}")
    big = create_placed_item(category["id"], zone["id"], 2336449,
                             description_text="big lot", estimated_weight_lbs=100)
    small = create_placed_item(category["id"], zone["id"], 100000,
                               description_text="small lot", estimated_weight_lbs=10)
    s1 = create_sale("CONTRACTOR_ACCOUNT", contractor_id=account["id"])
    s2 = create_sale("CONTRACTOR_ACCOUNT", contractor_id=account["id"])
    add_line(s2["id"], big["id"])
    s2 = finalize_sale(s2["id"])
    return {"category": category, "account": account, "zone": zone,
            "big": big, "small": small, "s1": s1, "s2": s2}


class TestSaleDiscountSnapshotVsLiveTier:
    def test_snapshot_bills_standard_despite_live_silver_tier(self, api):
        """PRD §3.9: "The tier percentage reads the pinned `tier_snapshot`:
        `STANDARD` yields zero, `SILVER` yields five percent, `GOLD` yields ten
        percent — finalize must use the snapshot, never a freshly recomputed tier,
        so a tier change produced by this very sale applies only to future sales."

        Design: Difficulty/dual_variant_calc/sale_discount_snapshot_vs_live_tier
        """
        ctx = _setup_snapshot_divergence()
        account = get_account(ctx["account"]["id"])
        assert account["discount_tier"] == "SILVER"
        assert account["trailing_volume_cents"] == 2500000

        add_line(ctx["s1"]["id"], ctx["small"]["id"])
        s1 = finalize_sale(ctx["s1"]["id"])
        assert s1["tier_snapshot"] == "STANDARD", "snapshot captured at open, before the volume"
        assert s1["discount_pct_applied"] == 0, "the STANDARD snapshot drives a zero discount"
        assert s1["subtotal_cents"] == 100000
        assert s1["total_cents"] == 107000, (
            f"100000 + round(100000*0.07) = 107000 (a live-tier recompute would give "
            f"101650), got {s1['total_cents']}")

    def test_snapshot_excludes_the_current_sale(self, api):
        """PRD §3.9: "At creation the sale pins its `tier_snapshot` — the account's
        `discount_tier` as computed from the trailing volume excluding the sale
        being created — which is null for walk-ins"

        Design: Difficulty/dual_variant_calc/sale_discount_snapshot_vs_live_tier
        """
        ctx = _setup_snapshot_divergence()
        assert ctx["s1"]["tier_snapshot"] == "STANDARD", (
            "S1 opened while trailing volume was 0: snapshot STANDARD")
        assert ctx["s2"]["total_cents"] == 2500000, (
            f"2336449 + round(2336449*0.07)=163551 -> 2500000, got {ctx['s2']['total_cents']}")
        account = get_account(ctx["account"]["id"])
        assert account["trailing_volume_cents"] == 2500000
        assert account["discount_tier"] == "SILVER"


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / discount_snapshot_evaluation_order
# ---------------------------------------------------------------------------

class TestDiscountSnapshotEvaluationOrder:
    def test_snapshot_tier_read_from_open_not_finalize(self, api):
        """PRD §3.9: "The tier percentage reads the pinned `tier_snapshot`:
        `STANDARD` yields zero, `SILVER` yields five percent, `GOLD` yields ten
        percent — finalize must use the snapshot, never a freshly recomputed tier,
        so a tier change produced by this very sale applies only to future sales."

        Design: Difficulty/combinatorial_formula/discount_snapshot_evaluation_order
        """
        ctx = _setup_snapshot_divergence(code="PANELS2", zone_code="Z3", company="Ctor E")
        assert ctx["s1"]["tier_snapshot"] == "STANDARD"
        add_line(ctx["s1"]["id"], ctx["small"]["id"])
        s1 = finalize_sale(ctx["s1"]["id"])
        assert s1["discount_pct_applied"] == 0, (
            "pinned order: snapshot (excluding this sale) -> discount; the account's "
            "live SILVER tier must not leak into this sale")

    def test_snapshot_order_produces_standard_total(self, api):
        """PRD §3.9: "`bulk_discount_cents` is the subtotal multiplied by that
        chosen percentage, rounded half-up; `tax_cents` is the subtotal minus the
        bulk discount, the difference multiplied by the seven percent sales-tax
        rate, rounded half-up; and `total_cents` is the subtotal minus the bulk
        discount plus the tax."

        Design: Difficulty/combinatorial_formula/discount_snapshot_evaluation_order
        """
        ctx = _setup_snapshot_divergence(code="PANELS2", zone_code="Z3", company="Ctor E")
        add_line(ctx["s1"]["id"], ctx["small"]["id"])
        s1 = finalize_sale(ctx["s1"]["id"])
        assert s1["bulk_discount_cents"] == 0
        assert s1["tax_cents"] == 7000
        assert s1["total_cents"] == 107000, (
            f"pinned-order total is 107000, not the 101650 a live-tier variant yields; "
            f"got {s1['total_cents']}")


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / tier_volume_exact_boundary
# ---------------------------------------------------------------------------

class TestTierVolumeExactBoundary:
    def _setup_account_at_silver_edge(self):
        category = create_category(code="BRICK", display_name="Brick",
                                   base_rate_cents=1000)
        account = create_account(company_name="Ctor H", contact_email="h@x.com")
        zone = create_zone(code="ZH", display_name="Zone H")
        sales = push_trailing_volume(account["id"], category["id"], zone["id"],
                                     [934579, 934579, 467290])
        fourth = create_placed_item(category["id"], zone["id"], 100000,
                                    description_text="p4", estimated_weight_lbs=10)
        return {"category": category, "account": account, "zone": zone,
                "sales": sales, "item4": fourth}

    def test_trailing_volume_exactly_at_silver_threshold(self, api):
        """PRD §3.9: "The trailing volume is the sum of `total_cents` over the
        account's sales standing `FINALIZED` whose `finalized_at` falls inside the
        inclusive 365-day window ending at the logical clock, and the discount tier
        re-derives from it on every change with inclusive thresholds: at least
        $100,000 (10,000,000 cents) is `GOLD`, at least $25,000 (2,500,000 cents)
        is `SILVER`, and anything less is `STANDARD`."

        Design: Difficulty/boundary_precision_check/tier_volume_exact_boundary
        """
        ctx = self._setup_account_at_silver_edge()
        assert ctx["sales"][0]["total_cents"] == 1000000, (
            f"934579 + round(934579*0.07)=65421 -> 1000000, got {ctx['sales'][0]['total_cents']}")
        account = get_account(ctx["account"]["id"])
        assert account["trailing_volume_cents"] == 2500000, (
            f"1000000 + 1000000 + 500000 lands exactly on the threshold: "
            f"{account['trailing_volume_cents']}")
        assert account["discount_tier"] == "SILVER", "threshold is inclusive (>=)"

    def test_silver_snapshot_applies_five_percent(self, api):
        """PRD §3.9: "The tier percentage reads the pinned `tier_snapshot`:
        `STANDARD` yields zero, `SILVER` yields five percent, `GOLD` yields ten
        percent — finalize must use the snapshot, never a freshly recomputed tier,
        so a tier change produced by this very sale applies only to future sales."

        Design: Difficulty/boundary_precision_check/tier_volume_exact_boundary
        """
        ctx = self._setup_account_at_silver_edge()
        sale = create_sale("CONTRACTOR_ACCOUNT", contractor_id=ctx["account"]["id"])
        assert sale["tier_snapshot"] == "SILVER"
        add_line(sale["id"], ctx["item4"]["id"])
        sale = finalize_sale(sale["id"])
        assert sale["bulk_discount_cents"] == 5000, (
            f"round(100000*0.05) = 5000, got {sale['bulk_discount_cents']}")
        assert sale["tax_cents"] == 6650, (
            f"round(95000*0.07) = 6650, got {sale['tax_cents']}")
        assert sale["total_cents"] == 101650, (
            f"100000 - 5000 + 6650 = 101650, got {sale['total_cents']}")


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / account_balance_finalize_void_invariant
# ---------------------------------------------------------------------------

class TestAccountBalanceFinalizeVoidInvariant:
    def test_finalize_accrues_balance_and_trailing(self, api):
        """PRD §3.9: "On the contractor channel the account's
        `outstanding_balance_cents` and `trailing_volume_cents` each gain the
        sale's `total_cents` and its `discount_tier` is recomputed"

        Design: Difficulty/compensating_invariant/account_balance_finalize_void_invariant
        """
        ctx = setup_contractor_sale_with_line(50000, category_overrides={
            "code": "PIPES", "display_name": "Pipes", "base_rate_cents": 50000})
        sale = finalize_sale(ctx["sale"]["id"])
        assert sale["total_cents"] == 53500, (
            f"50000 + round(50000*0.07) = 53500, got {sale['total_cents']}")
        account = get_account(ctx["account"]["id"])
        assert account["outstanding_balance_cents"] == 53500
        assert account["trailing_volume_cents"] == 53500

    def test_void_reverses_balance_and_trailing_exactly(self, api):
        """PRD §3.9: "On the contractor channel the account's outstanding balance
        and trailing volume each lose the sale's total and the discount tier is
        recomputed, so finalize followed by void leaves the outstanding balance
        exactly unchanged; the attached agreement's `fulfilled_quantity` is
        decremented by this sale's qualifying quantities."

        Design: Difficulty/compensating_invariant/account_balance_finalize_void_invariant
        """
        ctx = setup_contractor_sale_with_line(50000, category_overrides={
            "code": "PIPES", "display_name": "Pipes", "base_rate_cents": 50000})
        finalize_sale(ctx["sale"]["id"])
        validate_success(api.void_sale(ctx["sale"]["id"], {"void_reason": "order error"}, ADMIN))
        account = get_account(ctx["account"]["id"])
        assert account["outstanding_balance_cents"] == 0, (
            "finalize + void conserves the outstanding balance exactly")
        assert account["trailing_volume_cents"] == 0
        assert account["discount_tier"] == "STANDARD"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / sale_requires_active_account
# ---------------------------------------------------------------------------

class TestSaleRequiresActiveAccount:
    def test_contractor_sale_open_requires_active_account(self, api):
        """PRD §3.9: "Opening a contractor sale also requires the account to stand
        `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/sale_requires_active_account
        """
        account = create_account(approve=False, company_name="Ctor J",
                                 contact_email="j@x.com", credit_limit_cents=500000)
        assert account["status"] == "PENDING_APPROVAL"
        response = api.create_sale(
            {"sale_channel": "CONTRACTOR_ACCOUNT", "contractor_id": account["id"]}, CASHIER)
        validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)
        rows, meta = validate_paginated(
            api.list_sales(CASHIER, params={"contractor_id": account["id"]}))
        assert rows == [] and meta["total_count"] == 0, (
            "no sale row may be created for the rejected open")

    def test_contractor_sale_open_after_approval_succeeds(self, api):
        """PRD §3.9: "Approval by an administrator moves the account to `ACTIVE`
        (from any other state, `ERR_INVALID_ACCOUNT_STATE`) and records who
        approved it in `approved_by_user_id`."
        PRD §3.9: "At creation the sale pins its `tier_snapshot` — the account's
        `discount_tier` as computed from the trailing volume excluding the sale
        being created — which is null for walk-ins; every sale starts `OPEN`"

        Design: Difficulty/cross_entity_state_dependency/sale_requires_active_account
        """
        account = create_account(approve=False, company_name="Ctor J",
                                 contact_email="j@x.com", credit_limit_cents=500000)
        account = validate_success(api.approve_account(account["id"], ADMIN))
        assert account["status"] == "ACTIVE"
        sale = validate_success(api.create_sale(
            {"sale_channel": "CONTRACTOR_ACCOUNT", "contractor_id": account["id"]}, CASHIER),
            expected_status=201)
        assert sale["status"] == "OPEN"
        assert sale["tier_snapshot"] == "STANDARD"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / state_beats_fiscal_on_suspended_finalize
# ---------------------------------------------------------------------------

def _setup_suspended_zero_credit_sale():
    """Account (credit limit 0) ACTIVE at sale open with one 5000 line, then
    manually suspended before finalize."""
    ctx = setup_contractor_sale_with_line(5000, credit_limit_cents=0, category_overrides={
        "code": "SINKS", "display_name": "Sinks", "base_rate_cents": 6000})
    validate_success(api.suspend_account(ctx["account"]["id"],
                                         {"suspension_reason": "audit hold"}, ADMIN))
    return ctx


class TestStateBeatsFiscalOnSuspendedFinalize:
    def test_state_error_wins_over_credit_gate(self, api):
        """PRD §2.10: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order, and the first failing
        check produces the response."
        PRD §2.10: "7. **State** — the target resource stands in the from-state
        the transition requires, else the per-entity state error (§5), each an
        HTTP 409."
        PRD §2.10: "11. **Fiscal checks** — credit-limit breaches, payment
        sufficiency, overpayment, zero-balance on close, appraisal thresholds:
        `ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_PAYMENT_INSUFFICIENT`,
        `ERR_OVERPAYMENT`, `ERR_OUTSTANDING_BALANCE_NONZERO`,
        `ERR_APPRAISAL_REQUIRED`."
        PRD §3.9: "A contractor-channel sale re-checks that the account still
        stands `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), then faces the credit gate"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_suspended_finalize
        """
        ctx = _setup_suspended_zero_credit_sale()
        response = api.finalize_sale(ctx["sale"]["id"], {}, CASHIER)
        error = validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)
        assert error["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, (
            "the fiscal credit gate (priority 11) must not pre-empt the state check "
            "(priority 7) even with credit_limit 0")

    def test_rejected_finalize_leaves_sale_and_item_untouched(self, api):
        """PRD §3.9: "A contractor-channel sale re-checks that the account still
        stands `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`)"
        PRD §3.9: "Adding a line moves the item to `RESERVED` (it keeps occupying
        its zone slot)"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_suspended_finalize
        """
        ctx = _setup_suspended_zero_credit_sale()
        validate_error(api.finalize_sale(ctx["sale"]["id"], {}, CASHIER),
                       ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)
        sale = get_success_data(api.get_sale(ctx["sale"]["id"], CASHIER))
        assert sale["status"] == "OPEN", "rejected finalize must not move the sale"
        item = get_success_data(api.get_item(ctx["item"]["id"], MANAGER))
        assert item["sales_status"] == "RESERVED", "the line's reservation stands"


# ---------------------------------------------------------------------------
# Corner: endpoints / delete_line_unreserves_item
# ---------------------------------------------------------------------------

def test_delete_line_unreserves_item(api):
    """PRD §3.9: "Removing a line from an `OPEN` sale deletes the record outright
    and returns the item to `ON_FLOOR` with its `zone_id` retained"
    PRD §4: "The one deletion in the API — removing a sale line — returns `204 No
    Content` with no resource payload."

    Design: Corner/endpoints/delete_line_unreserves_item
    """
    ctx = setup_walk_in_sale_with_line(3000, category_overrides={
        "code": "DLCAT", "display_name": "Del Cat", "base_rate_cents": 3000})
    item = get_success_data(api.get_item(ctx["item"]["id"], MANAGER))
    assert item["sales_status"] == "RESERVED"

    response = api.delete_sale_line(ctx["line"]["id"], CASHIER)
    assert response.status_code == 204, f"line delete returns 204, got {response.status_code}"

    item = get_success_data(api.get_item(ctx["item"]["id"], MANAGER))
    assert item["sales_status"] == "ON_FLOOR"
    assert item["zone_id"] == ctx["zone"]["id"], "zone retained through un-reserve"


# ---------------------------------------------------------------------------
# Corner: validations / overpayment_rejected
# ---------------------------------------------------------------------------

def test_overpayment_rejected(api):
    """PRD §3.9: "Payments against the balance are recorded by an administrator as
    an `amount_cents`; a payment exceeding the outstanding balance is refused with
    `ERR_OVERPAYMENT`, and a recorded payment reduces `outstanding_balance_cents`
    and bumps the account's `version`."

    Design: Corner/validations/overpayment_rejected
    """
    ctx = setup_contractor_sale_with_line(50000, category_overrides={
        "code": "PAYCAT", "display_name": "Pay Cat", "base_rate_cents": 50000})
    finalize_sale(ctx["sale"]["id"])
    account = get_account(ctx["account"]["id"])
    assert account["outstanding_balance_cents"] == 53500

    response = api.record_payment(ctx["account"]["id"], {"amount_cents": 60000}, ADMIN)
    validate_error(response, ApiErrorId.ERR_OVERPAYMENT)
    account = get_account(ctx["account"]["id"])
    assert account["outstanding_balance_cents"] == 53500, "rejected payment leaves the balance"
