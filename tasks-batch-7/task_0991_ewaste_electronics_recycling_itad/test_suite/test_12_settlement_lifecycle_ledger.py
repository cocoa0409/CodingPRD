"""Settlement lifecycle and ledger posting: finalize/pay/void, the void
compensating invariant, supersede chains, quote OCC, and the fiscal guards
(PRD §2.8, §3.3, §3.8)."""
from test_helpers import (
    ApiErrorId,
    am_headers,
    create_quote_settlement,
    list_item,
    reconcile_manifest,
    scan_and_triage,
    sell_listing,
    set_clock,
    setup_finalized_settlement,
    setup_quote_for_sale,
    setup_received_manifest,
    setup_triaged_item,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVoidCompensatingInvariant:
    def test_finalize_then_void_restores_balance(self, api, platform_admin_headers):
        """PRD §3.8: "Voiding moves it to `VOIDED` and posts one `REVERSAL` entry per entry that finalization posted, each with the negated amount of its original, so the account's balance returns exactly to its pre-finalization value — the compensating invariant."
        PRD §3.8: "The account's `credit_balance_cents` grows by exactly `net_amount_cents`."

        Design: Difficulty/compensating_invariant/settlement_finalize_then_void_restores_balance
        """
        ctx = setup_finalized_settlement(sale_price_cents=60000)
        account = validate_success(api.get_account(ctx["account"]["id"],
                                                   platform_admin_headers))
        # BUYBACK_CREDIT +51000 (fees and rebate are zero, so their entries
        # are skipped); the balance moved by exactly the net.
        assert account["credit_balance_cents"] == 51000

        settlement = validate_success(api.void_settlement(ctx["settlement"]["id"],
                                                          platform_admin_headers))
        assert settlement["status"] == "VOIDED"
        account = validate_success(api.get_account(ctx["account"]["id"],
                                                   platform_admin_headers))
        assert account["credit_balance_cents"] == 0

    def test_void_posts_negating_reversal_entries(self, api, platform_admin_headers):
        """PRD §3.8: "Voiding moves it to `VOIDED` and posts one `REVERSAL` entry per entry that finalization posted, each with the negated amount of its original, so the account's balance returns exactly to its pre-finalization value — the compensating invariant."
        PRD §3.8: "The ledger then posts in a fixed sequence: a `BUYBACK_CREDIT` entry of the positive gross when gross is non-zero, then a `FEE_DEBIT` of the negated fees when fees are non-zero, then a `BONUS_CREDIT` of the rebate when the rebate is non-zero; every posted `LedgerEntry` records its `account_id`, its `settlement_id`, its `entry_type` (one of the five types above, or `REVERSAL` on a void), its signed `amount_cents` (credits positive, debits negative), and the running `balance_after_cents` immediately after posting."

        Design: Difficulty/compensating_invariant/settlement_finalize_then_void_restores_balance
        """
        ctx = setup_finalized_settlement(sale_price_cents=60000)
        # Distinct created_at between finalize and void fixes chronological order.
        set_clock("2026-05-01T01:00:00Z")
        validate_success(api.void_settlement(ctx["settlement"]["id"], platform_admin_headers))

        entries, _meta = validate_paginated(
            api.list_settlement_ledger_entries(ctx["settlement"]["id"], platform_admin_headers)
        )
        assert [(e["entry_type"], e["amount_cents"]) for e in entries] == [
            ("BUYBACK_CREDIT", 51000),
            ("REVERSAL", -51000),
        ]
        assert entries[0]["balance_after_cents"] == 51000
        assert entries[1]["balance_after_cents"] == 0
        assert all(e["account_id"] == ctx["account"]["id"] for e in entries)
        assert all(e["settlement_id"] == ctx["settlement"]["id"] for e in entries)


class TestImmediateConsistency:
    def test_finalize_immediately_visible_on_account_and_ledger(self, api,
                                                                platform_admin_headers):
        """PRD §3.8: "The ledger then posts in a fixed sequence: a `BUYBACK_CREDIT` entry of the positive gross when gross is non-zero, then a `FEE_DEBIT` of the negated fees when fees are non-zero, then a `BONUS_CREDIT` of the rebate when the rebate is non-zero; every posted `LedgerEntry` records its `account_id`, its `settlement_id`, its `entry_type` (one of the five types above, or `REVERSAL` on a void), its signed `amount_cents` (credits positive, debits negative), and the running `balance_after_cents` immediately after posting. The account's `credit_balance_cents` grows by exactly `net_amount_cents`."
        PRD §3.1: "The credit balance is never written directly: it is the running sum of every ledger `amount_cents` posted to the account, and a positive balance means the platform owes the customer money. Reading an account returns both computed figures."

        Design: Corner/consistency_model/finalize_immediately_visible
        """
        ctx = setup_quote_for_sale(sale_price_cents=60000)
        settlement = validate_success(api.finalize_settlement(ctx["settlement"]["id"],
                                                              platform_admin_headers))
        assert settlement["net_amount_cents"] == 51000

        # The very next reads already reflect the posting: no lag.
        account = validate_success(api.get_account(ctx["account"]["id"],
                                                   platform_admin_headers))
        assert account["credit_balance_cents"] == 51000

        entries, _meta = validate_paginated(
            api.list_settlement_ledger_entries(settlement["id"], platform_admin_headers)
        )
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "BUYBACK_CREDIT"
        assert entries[0]["amount_cents"] == 51000
        assert entries[0]["balance_after_cents"] == 51000


class TestSettlementStateGuards:
    def test_pay_open_quote_rejected(self, api, platform_admin_headers):
        """PRD §3.8: "Two exits exist from `FINALIZED`, both restricted to `PlatformAdmin` and both guarded by `ERR_SETTLEMENT_NOT_FINALIZED` when attempted from any other state."

        Design: Corner/errors/pay_open_quote_rejected
        """
        ctx = setup_quote_for_sale(sale_price_cents=60000)
        resp = api.pay_settlement(ctx["settlement"]["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FINALIZED)
        assert resp.status_code == 409

    def test_finalize_with_pending_items_rejected(self, api, platform_admin_headers):
        """PRD §3.8: "Only a settlement whose `kind` is `QUOTE` may be finalized — a `FINAL` record is never re-finalized — the owning manifest must be `RECONCILED` (`ERR_INVALID_STATE`), and every item of the manifest must stand in `SOLD` or `COMPLETE` (`ERR_FINALIZE_ITEMS_PENDING`); the state checks run before the item-pending check."

        Design: Corner/validations/finalize_with_pending_items_rejected
        """
        _account, manifest = setup_received_manifest(declared_item_count=2)
        item_one = scan_and_triage(manifest["id"], "RESALE", serial_number="SN-PE1",
                                   category="LAPTOP", declared_grade="A")
        item_two = scan_and_triage(manifest["id"], "RESALE", serial_number="SN-PE2",
                                   category="LAPTOP", declared_grade="A")
        listing_one = list_item(item_one["id"], asking_price_cents=60000,
                                floor_price_cents=50000)
        # Item two stays LISTED but unsold.
        list_item(item_two["id"], asking_price_cents=60000, floor_price_cents=50000)
        sell_listing(listing_one["id"], 60000)
        reconcile_manifest(manifest["id"])
        quote = create_quote_settlement(manifest["id"])

        resp = api.finalize_settlement(quote["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_FINALIZE_ITEMS_PENDING)
        assert resp.status_code == 422

    def test_close_with_unpaid_settlement_rejected(self, api):
        """PRD §3.3: "Closure by an `AccountManager` is available from `RECONCILED`, and only after the money has settled: at least one settlement must exist for the manifest, and every settlement that has not been superseded must be `PAID` or `VOIDED`, otherwise the close is rejected with `ERR_CLOSE_SETTLEMENT_UNPAID`."

        Design: Corner/validations/close_with_unpaid_settlement_rejected
        """
        ctx = setup_finalized_settlement(sale_price_cents=60000)
        resp = api.close_manifest(ctx["manifest"]["id"], am_headers(ctx["account"]))
        validate_error(resp, ApiErrorId.ERR_CLOSE_SETTLEMENT_UNPAID)
        assert resp.status_code == 422


class TestSupersedeChain:
    def test_requote_supersedes_prior_quote_and_is_queryable(self, api, platform_admin_headers):
        """PRD §3.8: "The created settlement records its owning manifest as `manifest_id`, has `kind` `QUOTE` and `status` `QUOTE_OPEN`, and it supersedes its predecessor: if a previous `QUOTE_OPEN` settlement existed for the manifest, that record moves to `SUPERSEDED` and the new settlement's `supersedes_settlement_id` points at it, forming a chain that can be walked through the settlement list's `supersedes_settlement_id` filter. Creating the quote also increments the manifest's `version`, which is exactly what the OCC guard on the next re-quote protects against."

        Design: Corner/endpoints/settlement_supersede_chain_queryable
        """
        ctx = setup_triaged_item(disposition="RESALE", declared_grade="A")
        first = create_quote_settlement(ctx["manifest"]["id"])
        # create_quote_settlement re-reads the manifest version, which the
        # first quote bumped, so the second quote passes the OCC guard.
        second = create_quote_settlement(ctx["manifest"]["id"])

        first_after = validate_success(api.get_settlement(first["id"],
                                                          platform_admin_headers))
        assert first_after["status"] == "SUPERSEDED"
        assert second["supersedes_settlement_id"] == first["id"]

        replacements, _meta = validate_paginated(api.list_settlements(
            platform_admin_headers, params={"supersedes_settlement_id": first["id"]},
        ))
        assert [s["id"] for s in replacements] == [second["id"]]

    def test_requote_with_stale_version_rejected(self, api, intake_operator_headers):
        """PRD §2.8: "The same rule guards quote creation: creating a QUOTE settlement against a manifest requires `expected_manifest_version` matching the manifest's current `version`, and a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), so the figures in the new quote are always computed against a manifest the client has actually observed."
        PRD §3.8: "Creating the quote also increments the manifest's `version`, which is exactly what the OCC guard on the next re-quote protects against."

        Design: Corner/cross_cutting_complexity_layers/occ_requote_stale_returns_412
        """
        ctx = setup_triaged_item(disposition="RESALE", declared_grade="A")
        manifest = validate_success(api.get_manifest(ctx["manifest"]["id"],
                                                     intake_operator_headers))
        observed_version = manifest["version"]
        validate_success(api.create_settlement(
            ctx["manifest"]["id"], {"expected_manifest_version": observed_version},
            intake_operator_headers,
        ), 201)

        # The first quote bumped the manifest version, so the replay is stale.
        resp = api.create_settlement(
            ctx["manifest"]["id"], {"expected_manifest_version": observed_version},
            intake_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
