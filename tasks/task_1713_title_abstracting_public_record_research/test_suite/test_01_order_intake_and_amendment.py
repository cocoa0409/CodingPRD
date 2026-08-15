"""Order intake, quoting, and scope amendment (PRD §2.5, §2.7, §2.8, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    assert_abstract_order,
    create_order,
    create_order_payload,
    drive_order_to_search_complete,
    get_order,
    make_client_headers,
    make_ops_headers,
    validate_error,
    validate_success,
)


class TestOrderCreation:
    def test_order_creation_applies_defaults_and_computed_fields(self, api):
        """PRD §3.1: "Two engagement tiers may optionally be supplied: `sla_tier`
        (`STANDARD` or `RUSH`, defaulting to `STANDARD`) and `liability_tier`
        (`STANDARD` or `EXTENDED`, defaulting to `STANDARD`)."
        PRD §3.1: "Creation stamps `received_at` from the logical clock and leaves
        the order in `RECEIVED` status."
        PRD §2.5: "At server startup, before any administrative adjustment, the
        logical clock reads exactly `2026-08-01T00:00:00Z`."
        PRD §2.5: "The due instant `due_at` is derived at creation as `received_at`
        plus seventy-two hours for a `STANDARD` order, or plus twenty-four hours
        for a `RUSH` order."
        PRD §3.1: "for a `STANDARD` order the premium is zero and the quote is
        exactly 60000 cents."
        PRD §3.1: "The order's `final_fee_cents`, `delivered_at`, and
        `billed_fee_cents` are all null until delivery, `late_credit_cents` starts
        at 0, `open_curative_count` starts at 0, and the `legal_hold` flag starts
        false."

        Design: Corner/entities/order_creation_applies_defaults_and_computed_fields
        """
        resp = api.create_abstract_order(
            create_order_payload("client_801", property_address="10 Cedar St"),
            make_client_headers("client_801"),
        )
        order = validate_success(resp, 201)
        assert_abstract_order(order)

        assert order["sla_tier"] == "STANDARD", "sla_tier default must be STANDARD"
        assert order["liability_tier"] == "STANDARD", "liability_tier default must be STANDARD"
        assert order["status"] == "RECEIVED"
        assert order["received_at"] == "2026-08-01T00:00:00Z", (
            f"received_at must be the logical clock startup default, got {order['received_at']}"
        )
        assert order["due_at"] == "2026-08-04T00:00:00Z", (
            f"STANDARD due_at = received_at + 72h, got {order['due_at']}"
        )
        assert order["scope_start_date"] == "1996-01-15", (
            f"30-year scope from 2026-01-15 opens 1996-01-15, got {order['scope_start_date']}"
        )
        assert order["provisional_fee_cents"] == 60000, (
            f"STANDARD provisional = 40000 + 8*2500, got {order['provisional_fee_cents']}"
        )
        assert order["accrued_fees_cents"] == 40000, (
            f"running fee initializes to the base fee only, got {order['accrued_fees_cents']}"
        )
        assert order["liability_cap_cents"] == 120000, (
            f"cap = min(3*40000, 200000), got {order['liability_cap_cents']}"
        )
        assert order["open_curative_count"] == 0
        assert order["legal_hold"] is False
        assert order["is_overdue"] is False
        assert order["final_fee_cents"] is None
        assert order["delivered_at"] is None
        assert order["billed_fee_cents"] is None
        assert order["late_credit_cents"] == 0

    def test_order_create_missing_required_field_rejected(self, api):
        """PRD §3.1: "A request missing a required field, presenting an enum
        outside its declared values, or violating a range — a `search_period_years`
        of 0 or 61, a `state_code` in lowercase — is rejected with `ERR_VALIDATION`
        (HTTP 400)."

        Design: Corner/entities/order_create_missing_required_field_rejected
        """
        payload = create_order_payload("client_803", property_address="12 Cedar St")
        del payload["county"]
        resp = api.create_abstract_order(payload, make_client_headers("client_803"))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_provisional_fee_constants_applied_for_standard_order(self, api):
        """PRD §3.1: "The provisional fee `provisional_fee_cents` is the sum of a
        40000-cent base fee and an estimated retrieval allowance — eight projected
        county documents at 2500 cents each, i.e. 20000 cents — plus, when the tier
        is `RUSH`, a premium of twenty-five percent of that subtotal rounded half
        up; for a `STANDARD` order the premium is zero and the quote is exactly
        60000 cents."
        PRD §3.1: "The running ledger `accrued_fees_cents` initializes differently:
        it contains the base fee plus, for `RUSH` only, twenty-five percent of the
        base fee alone rounded half up — the estimated allowance is a projection
        for quoting, not yet a charge, and it is discarded entirely at
        finalization, which uses only actually posted, non-reversed retrieval fees."

        Design: Corner/calculations/provisional_fee_constants_applied_for_standard_order
        """
        resp = api.create_abstract_order(
            create_order_payload(
                "client_821", property_address="30 Fir St", sla_tier="STANDARD"
            ),
            make_client_headers("client_821"),
        )
        order = validate_success(resp, 201)
        assert order["provisional_fee_cents"] == 60000, (
            f"provisional = 40000 + 8*2500 = 60000, got {order['provisional_fee_cents']}"
        )
        assert order["accrued_fees_cents"] == 40000, (
            f"actuals variant carries no retrieval allowance, got {order['accrued_fees_cents']}"
        )


class TestLiabilityCapTierBranch:
    def test_standard_tier_cap_selects_multiplier_branch(self, api):
        """PRD §2.7: "The cap `liability_cap_cents` is the lesser of two quantities:
        the tier multiplier applied to the fee basis — three times the basis for
        the `STANDARD` liability tier, five times for `EXTENDED` — or an absolute
        ceiling of 200000 cents."
        PRD §3.1: "The running ledger `accrued_fees_cents` initializes differently:
        it contains the base fee plus, for `RUSH` only, twenty-five percent of the
        base fee alone rounded half up — the estimated allowance is a projection
        for quoting, not yet a charge, and it is discarded entirely at
        finalization, which uses only actually posted, non-reversed retrieval fees."

        Design: Difficulty/combinatorial_formula/liability_cap_nested_min_max_tier_branch
        """
        order = create_order(
            "client_711",
            property_address="1 Capitol Way",
            search_period_years=20,
            sla_tier="RUSH",
            liability_tier="STANDARD",
        )
        assert order["accrued_fees_cents"] == 50000, (
            f"RUSH running fee = 40000 + 25%*40000 = 50000, got {order['accrued_fees_cents']}"
        )
        fetched = get_order(order["id"])
        assert fetched["liability_cap_cents"] == 150000, (
            f"min(3*50000, 200000) selects the multiplier branch, got {fetched['liability_cap_cents']}"
        )

    def test_extended_tier_cap_selects_absolute_ceiling_branch(self, api):
        """PRD §2.7: "The cap `liability_cap_cents` is the lesser of two quantities:
        the tier multiplier applied to the fee basis — three times the basis for
        the `STANDARD` liability tier, five times for `EXTENDED` — or an absolute
        ceiling of 200000 cents."

        Design: Difficulty/combinatorial_formula/liability_cap_nested_min_max_tier_branch
        """
        order_std = create_order(
            "client_711",
            property_address="1 Capitol Way",
            search_period_years=20,
            sla_tier="RUSH",
            liability_tier="STANDARD",
        )
        order_ext = create_order(
            "client_711",
            property_address="2 Congress Ave",
            search_period_years=20,
            sla_tier="RUSH",
            liability_tier="EXTENDED",
        )
        assert order_std["accrued_fees_cents"] == 50000
        assert order_ext["accrued_fees_cents"] == 50000, "identical fee basis across tiers"
        cap_std = get_order(order_std["id"])["liability_cap_cents"]
        cap_ext = get_order(order_ext["id"])["liability_cap_cents"]
        assert cap_ext == 200000, (
            f"5*50000 = 250000 exceeds the ceiling, got {cap_ext}"
        )
        assert cap_std != cap_ext, "tier branch must be load-bearing on identical basis"


class TestScopeAmendment:
    def test_occ_stale_patch_rejected(self, api):
        """PRD §2.8: "Amending an order's engagement scope requires the request to
        carry `expected_abstract_order_version`, a non-optional field holding the
        order `version` the client last observed."
        PRD §2.8: "if the order's current `version` on the server has advanced past
        the supplied value — because another writer patched the scope, a cascade
        bumped the version, or any other mutation intervened — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412); the client must re-read the
        order and retry against the version it actually observes."
        PRD §3.2: "a change to `sla_tier` recomputes `due_at` and the premium
        portion of both the provisional quote and the running fee"

        Design: Corner/cross_cutting_layers/occ_stale_patch_rejected
        """
        order = create_order("client_871", property_address="90 Cedar Park")
        v1 = order["version"]

        patch1 = api.patch_abstract_order(
            order["id"],
            {"expected_abstract_order_version": v1, "sla_tier": "RUSH"},
            make_ops_headers(),
        )
        patched = validate_success(patch1, 200)
        assert patched["version"] == v1 + 1, (
            f"accepted amendment increments the order version, got {patched['version']}"
        )
        assert patched["provisional_fee_cents"] == 75000, (
            f"RUSH quote recomputed: 60000 + 25%*60000, got {patched['provisional_fee_cents']}"
        )
        assert patched["accrued_fees_cents"] == 50000, (
            f"RUSH running fee recomputed: 40000 + 25%*40000, got {patched['accrued_fees_cents']}"
        )

        patch2 = api.patch_abstract_order(
            order["id"],
            {"expected_abstract_order_version": v1, "liability_tier": "EXTENDED"},
            make_ops_headers(),
        )
        validate_error(patch2, ApiErrorId.ERR_STALE_VERSION)

    def test_scope_patch_locked_after_search_complete(self, api):
        """PRD §3.2: "Once the order has advanced beyond `SEARCH_IN_PROGRESS` the
        scope is locked, and any such amendment is rejected with `ERR_SCOPE_LOCKED`
        (HTTP 409)."

        Design: Corner/validations/scope_patch_locked_after_search_complete
        """
        ctx = drive_order_to_search_complete("client_827", "abs_827", "ex_827")
        order = ctx["order"]
        assert order["status"] == "SEARCH_COMPLETE", "scenario precondition"

        resp = api.patch_abstract_order(
            order["id"],
            {"expected_abstract_order_version": order["version"], "search_period_years": 40},
            make_ops_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_SCOPE_LOCKED)
