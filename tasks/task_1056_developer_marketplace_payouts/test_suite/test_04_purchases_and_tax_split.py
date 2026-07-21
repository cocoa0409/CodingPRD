"""Purchases: recording, the pinned tax split, capture and the provisional share."""
from test_helpers import (
    ApiErrorId,
    assert_purchase,
    assert_purchase_split_identity,
    capture_purchase,
    configure_jurisdiction,
    create_purchase_payload,
    ledger_entries,
    read_developer,
    record_and_capture,
    record_purchase,
    set_clock,
    setup_marketplace_with_live_app,
    single_line_purchase,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_vat_is_rounded_per_line_item_then_summed(api, storefront_headers):
    """PRD 2.6: "Tax is extracted from tax-inclusive prices rather than added to
    tax-exclusive ones. Given a jurisdiction whose VAT rate is a number of basis points,
    the tax contained in a tax-inclusive amount is that amount multiplied by the rate and
    divided by the sum of 10,000 and the rate, rounded half-up to a whole cent."
    PRD 3.5: "`gross_cents` is then the sum of the line grosses and `tax_cents` is the sum
    of the already-rounded per-line taxes."
    PRD 3.5: "The commissionable base, `revenue_base_cents`, is `gross_cents` less
    `tax_cents`."

    Design: Difficulty/combinatorial_formula/vat_rounded_per_line_item_then_summed_beats_sum_then_round
    """
    ctx = setup_marketplace_with_live_app(
        api,
        jurisdictions=[("DE", 1900, True), ("US", 0, True)],
        plan_overrides={"price_cents": 999},
        app_overrides={"name": "Seat Manager", "listed_countries": ["US", "DE"]},
        developer_overrides={"legal_name": "Rounding Co", "email": "r@round.test"},
    )
    payload = create_purchase_payload(
        ctx["app_id"], ctx["plan_id"], buyer_country_code="DE",
        external_order_ref="ORD-DE-ROUND",
        line_items=[
            {"sku": "seat-a", "unit_price_cents": 999, "quantity": 1},
            {"sku": "seat-b", "unit_price_cents": 999, "quantity": 1},
            {"sku": "seat-c", "unit_price_cents": 999, "quantity": 1},
        ],
    )
    data = validate_success(api.create_purchase(payload, storefront_headers), 201)
    assert_purchase(data)
    assert data["gross_cents"] == 2997
    assert data["tax_cents"] == 480, (
        "three lines of 999 each round to 160 cents of VAT and sum to 480"
    )
    assert data["revenue_base_cents"] == 2517
    assert data["tax_remitter"] == "MARKETPLACE"
    assert data["developer_tax_remittance_cents"] == 0


def test_single_line_of_the_same_gross_yields_a_different_tax(api, storefront_headers):
    """PRD 3.5: "Working through `line_items` in the order supplied in the request body,
    each line's gross is its `unit_price_cents` multiplied by its `quantity`, and that
    line's tax is the line gross multiplied by the rate and divided by the sum of ten
    thousand and the rate, rounded half-up to a whole cent"
    PRD 3.5: "The commissionable base, `revenue_base_cents`, is `gross_cents` less
    `tax_cents`."

    Design: Difficulty/combinatorial_formula/vat_rounded_per_line_item_then_summed_beats_sum_then_round
    """
    ctx = setup_marketplace_with_live_app(
        api,
        jurisdictions=[("DE", 1900, True), ("US", 0, True)],
        plan_overrides={"price_cents": 2997},
        app_overrides={"name": "Seat Manager", "listed_countries": ["US", "DE"]},
        developer_overrides={"legal_name": "Rounding Co", "email": "r@round.test"},
    )
    payload = create_purchase_payload(
        ctx["app_id"], ctx["plan_id"], buyer_country_code="DE",
        external_order_ref="ORD-DE-SINGLE",
        line_items=[{"sku": "bundle", "unit_price_cents": 2997, "quantity": 1}],
    )
    data = validate_success(api.create_purchase(payload, storefront_headers), 201)
    assert data["gross_cents"] == 2997
    assert data["tax_cents"] == 479, (
        "one line of 2997 rounds once, giving 479 rather than the 480 of three lines"
    )
    assert data["revenue_base_cents"] == 2518


def test_purchase_split_fields_are_derived_from_line_items(api, storefront_headers):
    """PRD 3.5: "Each element of `line_items` is an object with a `sku`, a
    `unit_price_cents` strictly greater than zero and a `quantity` strictly greater than
    zero, and at least one element must be present."
    PRD 3.5: "New purchases begin `AUTHORIZED` and `UNSETTLED`."

    Design: Corner/entities/corner_purchase_computed_split_fields_are_server_derived
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 2000},
        app_overrides={"name": "Computed", "category": "GAMES"},
        developer_overrides={"legal_name": "Computed Co", "email": "cc@x.test"},
    )
    payload = create_purchase_payload(
        ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-COMP",
        line_items=[{"sku": "std", "unit_price_cents": 2000, "quantity": 2}],
    )
    data = validate_success(api.create_purchase(payload, storefront_headers), 201)
    assert data["gross_cents"] == 4000
    assert data["tax_cents"] == 0
    assert data["revenue_base_cents"] == 4000
    assert data["tax_remitter"] == "MARKETPLACE"
    assert data["payment_status"] == "AUTHORIZED"
    assert data["settlement_status"] == "UNSETTLED"
    assert data["refunded_gross_cents"] == 0


def test_non_facilitator_jurisdiction_passes_the_tax_through(api, storefront_headers):
    """PRD 3.5: "When the jurisdiction is a marketplace facilitator, `tax_remitter` is
    `MARKETPLACE` and `developer_tax_remittance_cents` is 0 — the marketplace keeps the
    tax and pays it to the authority. When it is not, `tax_remitter` is `DEVELOPER` and
    `developer_tax_remittance_cents` equals `tax_cents`, an amount that will later be
    passed through to the developer so the developer can remit it."
    PRD 3.5: "An entry of `entry_type` `ACCRUAL` is created with `amount_cents` equal to
    `provisional_developer_net_cents`. When `tax_remitter` is `DEVELOPER`, a second entry
    of `entry_type` `TAX_PASSTHROUGH` is created with `amount_cents` equal to
    `developer_tax_remittance_cents`."

    Design: Corner/calculations/corner_non_facilitator_jurisdiction_pays_tax_through_to_developer
    """
    ctx = setup_marketplace_with_live_app(
        api,
        jurisdictions=[("US", 0, True), ("JP", 1000, False)],
        plan_overrides={"price_cents": 1100},
        app_overrides={"name": "Passthrough", "listed_countries": ["US", "JP"]},
        developer_overrides={"legal_name": "Passthrough KK", "email": "pt@x.test"},
    )
    payload = create_purchase_payload(
        ctx["app_id"], ctx["plan_id"], buyer_country_code="JP",
        external_order_ref="ORD-JP",
        line_items=single_line_purchase(1100),
    )
    purchase = validate_success(api.create_purchase(payload, storefront_headers), 201)
    assert purchase["tax_cents"] == 100
    assert purchase["tax_remitter"] == "DEVELOPER"
    assert purchase["developer_tax_remittance_cents"] == 100

    captured = capture_purchase(api, purchase["id"])
    assert captured["provisional_developer_net_cents"] == 700

    entries = ledger_entries(api, purchase_id=purchase["id"])
    by_type = {e["entry_type"]: e for e in entries}
    assert len(entries) == 2, f"expected an ACCRUAL and a TAX_PASSTHROUGH, got {entries}"
    assert by_type["ACCRUAL"]["amount_cents"] == 700
    assert by_type["TAX_PASSTHROUGH"]["amount_cents"] == 100
    assert read_developer(api, ctx["developer_id"])["unpaid_accrual_cents"] == 800


def test_tier_selection_falls_back_to_the_default_share(api):
    """PRD 3.1: "Tier selection is deterministic and is the same procedure everywhere it
    is used. Given a base amount, the candidate tiers are those whose
    `min_cumulative_base_cents` is less than or equal to that base amount. If no tier
    qualifies — including the case where no tiers have been registered at all — the
    developer's share is the marketplace default of 70 percent, that is, 7,000 basis
    points."
    PRD 3.5: "The chosen rate is stored as `provisional_share_bps`;
    `provisional_developer_net_cents` is `revenue_base_cents` multiplied by that rate and
    divided by ten thousand, rounded half-up to a whole cent; and `platform_fee_cents` is
    `revenue_base_cents` less `provisional_developer_net_cents`."

    Design: Corner/calculations/corner_tier_selection_falls_back_to_default_share_when_candidate_set_empty
    """
    ctx = setup_marketplace_with_live_app(
        api,
        tiers=[("SCALE", 1000000, 9000)],
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Fallback", "category": "GAMES"},
        developer_overrides={"legal_name": "Fallback Co", "email": "fb@x.test"},
    )
    captured = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"],
        external_order_ref="ORD-FB", line_items=single_line_purchase(10000),
    )
    assert captured["provisional_share_bps"] == 7000, (
        "the only tier starts at 1,000,000 cents, so the candidate set is empty"
    )
    assert captured["provisional_developer_net_cents"] == 7000
    assert captured["platform_fee_cents"] == 3000
    assert_purchase_split_identity(captured)
    assert read_developer(api, ctx["developer_id"])["lifetime_revenue_base_cents"] == 10000


def test_capturing_an_already_captured_purchase_is_rejected(api, storefront_headers):
    """PRD 3.5: "Capture is where the developer's money starts to exist. Moving
    `AUTHORIZED → CAPTURED` stamps `captured_at` with the current logical clock and runs
    the revenue share in its **provisional** variant"
    PRD 2.8: "State legality. The target resource is in a state from which the requested
    transition is declared — otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_capture_twice_second_call_rejected
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Twice", "category": "GAMES"},
        developer_overrides={"legal_name": "Twice Co", "email": "tw@x.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"],
        external_order_ref="ORD-TWICE", line_items=single_line_purchase(10000),
    )

    response = api.capture_purchase(purchase["id"], storefront_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    accruals = ledger_entries(api, purchase_id=purchase["id"], entry_type="ACCRUAL")
    assert len(accruals) == 1, "a rejected second capture must not write a second accrual"
    assert read_developer(api, ctx["developer_id"])["lifetime_revenue_base_cents"] == 10000


def test_purchase_from_an_unconfigured_country_is_refused(api, storefront_headers,
                                                          finance_headers):
    """PRD 3.5: "At creation the purchase copies `developer_id` from the listing's owner
    and resolves `tax_jurisdiction_id` from `buyer_country_code`; if no jurisdiction is
    registered for that country the purchase is refused with
    `ERR_JURISDICTION_NOT_CONFIGURED`."

    Design: Corner/validations/corner_purchase_with_unconfigured_buyer_country_returns_jurisdiction_not_configured
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 5000},
        app_overrides={"name": "Geo", "category": "GAMES", "listed_countries": ["US", "BR"]},
        developer_overrides={"legal_name": "Geo Co", "email": "geo@x.test"},
    )
    payload = create_purchase_payload(
        ctx["app_id"], ctx["plan_id"], buyer_country_code="BR",
        external_order_ref="ORD-BR", line_items=single_line_purchase(5000),
    )
    response = api.create_purchase(payload, storefront_headers)
    validate_error(response, ApiErrorId.ERR_JURISDICTION_NOT_CONFIGURED)
    assert response.status_code == 422

    _rows, meta = validate_paginated(
        api.list_purchases(finance_headers, {"app_id": ctx["app_id"]})
    )
    assert meta["total_count"] == 0


def test_purchase_against_a_suspended_listing_is_rejected(api, officer_headers,
                                                          storefront_headers,
                                                          finance_headers):
    """PRD 3.3: "Once live, a listing can be suspended by a `PolicyOfficer` with a
    `reason`, moving `LIVE → SUSPENDED`; a suspended listing rejects new purchases with
    `ERR_APP_NOT_PURCHASABLE`."
    PRD 3.5: "A purchase may only be recorded when the listing is `LIVE` and the
    referenced plan's status is `ACTIVE`; otherwise the storefront receives
    `ERR_APP_NOT_PURCHASABLE`."

    Design: Corner/validations/corner_purchase_against_suspended_app_returns_not_purchasable
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 5000},
        app_overrides={"name": "Suspendable", "category": "GAMES"},
        developer_overrides={"legal_name": "Suspend Co", "email": "sp@x.test"},
    )
    suspended = validate_success(
        api.suspend_app(ctx["app_id"], {"reason": "under investigation"}, officer_headers)
    )
    assert suspended["status"] == "SUSPENDED"

    payload = create_purchase_payload(
        ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-SUSP",
        line_items=single_line_purchase(5000),
    )
    response = api.create_purchase(payload, storefront_headers)
    validate_error(response, ApiErrorId.ERR_APP_NOT_PURCHASABLE)
    assert response.status_code == 409

    assert validate_success(
        api.get_pricing_plan(ctx["plan_id"], finance_headers)
    )["status"] == "ACTIVE"


def test_purchase_naming_a_plan_of_another_listing_is_rejected(api, storefront_headers,
                                                                finance_headers):
    """PRD 3.5: "The referenced plan must belong to the referenced listing, or the request
    is rejected with `ERR_PLAN_APP_MISMATCH`."

    Design: Corner/validations/corner_purchase_with_plan_belonging_to_another_app_returns_mismatch
    """
    ctx_a = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 1000},
        app_overrides={"name": "App A", "category": "GAMES"},
        developer_overrides={"legal_name": "Mismatch Co", "email": "mm@x.test"},
    )
    from test_helpers.fixtures import setup_live_app

    ctx_b = setup_live_app(
        api,
        developer_id=ctx_a["developer_id"],
        plan_overrides={"price_cents": 2000},
        app_overrides={"name": "App B", "category": "GAMES"},
    )

    payload = create_purchase_payload(
        ctx_a["app_id"], ctx_b["plan_id"], external_order_ref="ORD-MM",
        line_items=single_line_purchase(2000),
    )
    response = api.create_purchase(payload, storefront_headers)
    validate_error(response, ApiErrorId.ERR_PLAN_APP_MISMATCH)
    assert response.status_code == 422

    _rows, meta = validate_paginated(
        api.list_purchases(finance_headers, {"app_id": ctx_a["app_id"]})
    )
    assert meta["total_count"] == 0


def test_purchases_can_be_filtered_by_developer(api, finance_headers):
    """PRD 3.5: "Purchases may be listed with filters on `app_id`, `pricing_plan_id`,
    `developer_id`, `tax_jurisdiction_id`, `payment_status` and `settlement_status`"
    PRD 3.5: "At creation the purchase copies `developer_id` from the listing's owner and
    resolves `tax_jurisdiction_id` from `buyer_country_code`"

    Design: Corner/endpoints/corner_purchases_filtered_by_developer_id_reverse_reachability
    """
    from test_helpers.fixtures import setup_live_app

    ctx_a = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 1000},
        app_overrides={"name": "FA App", "category": "GAMES"},
        developer_overrides={"legal_name": "Filter A", "email": "fa@x.test"},
    )
    ctx_b = setup_live_app(
        api,
        plan_overrides={"price_cents": 1000},
        app_overrides={"name": "FB App", "category": "GAMES"},
        developer_overrides={"legal_name": "Filter B", "email": "fb2@x.test"},
    )

    record_purchase(api, ctx_a["app_id"], ctx_a["plan_id"],
                    external_order_ref="ORD-FA-1", line_items=single_line_purchase(1000))
    record_purchase(api, ctx_a["app_id"], ctx_a["plan_id"],
                    external_order_ref="ORD-FA-2", line_items=single_line_purchase(1000))
    record_purchase(api, ctx_b["app_id"], ctx_b["plan_id"],
                    external_order_ref="ORD-FB-1", line_items=single_line_purchase(1000))

    rows, meta = validate_paginated(
        api.list_purchases(finance_headers, {"developer_id": ctx_a["developer_id"]})
    )
    assert meta["total_count"] == 2
    for row in rows:
        assert row["developer_id"] == ctx_a["developer_id"]
        assert row["app_id"] == ctx_a["app_id"]

    _rows_b, meta_b = validate_paginated(
        api.list_purchases(finance_headers, {"developer_id": ctx_b["developer_id"]})
    )
    assert meta_b["total_count"] == 1


def test_lifetime_revenue_base_counts_only_captured_purchases(api, storefront_headers,
                                                               finance_headers):
    """PRD 2.9: "`lifetime_revenue_base_cents` is the running sum of `revenue_base_cents`
    over that developer's purchases whose `payment_status` is `CAPTURED`."
    PRD 3.5: "An authorised purchase may be voided by the storefront, moving
    `AUTHORIZED → VOIDED` on the payment dimension. `settlement_status` stays
    `UNSETTLED`, no ledger entry is created, and `VOIDED` is terminal for the payment
    dimension."

    Design: Corner/cross_cutting_complexity_layers/corner_developer_lifetime_base_counts_only_captured_purchases
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Derived", "category": "FINANCE"},
        developer_overrides={"legal_name": "Derived Co", "email": "dr@x.test"},
    )
    p1 = record_purchase(api, ctx["app_id"], ctx["plan_id"],
                         external_order_ref="ORD-D1", line_items=single_line_purchase(10000))
    p2 = record_purchase(api, ctx["app_id"], ctx["plan_id"],
                         external_order_ref="ORD-D2", line_items=single_line_purchase(10000))
    p3 = record_purchase(api, ctx["app_id"], ctx["plan_id"],
                         external_order_ref="ORD-D3", line_items=single_line_purchase(10000))
    validate_success(api.void_purchase(p3["id"], storefront_headers))

    capture_purchase(api, p1["id"])

    developer = read_developer(api, ctx["developer_id"])
    assert developer["lifetime_revenue_base_cents"] == 10000
    assert developer["unpaid_accrual_cents"] == 7000

    p2_after = validate_success(api.get_purchase(p2["id"], finance_headers))
    assert p2_after["payment_status"] == "AUTHORIZED"
    assert p2_after["settlement_status"] == "UNSETTLED"
    p3_after = validate_success(api.get_purchase(p3["id"], finance_headers))
    assert p3_after["payment_status"] == "VOIDED"

    assert len(ledger_entries(api, developer_id=ctx["developer_id"])) == 1
