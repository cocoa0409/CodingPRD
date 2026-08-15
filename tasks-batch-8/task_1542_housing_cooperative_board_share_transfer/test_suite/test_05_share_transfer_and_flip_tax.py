"""Recording the share transfer: flip-tax variants and rounding, share
conservation through the ledger rewrite, and OCC on the recording write."""
from test_helpers import (
    OFFICER,
    ApiErrorId,
    advance_clock,
    assert_purchase_application,
    assert_share_ledger_entry,
    assert_shares_conserved,
    find_shareholder_by_email,
    fresh_coop_version,
    open_resolution,
    pass_resolution,
    record_transfer,
    setup_application_approved,
    validate_error,
    validate_paginated,
    validate_success,
)


def _get_app(api, coop_id, app_id):
    return validate_success(api.get_purchase_application(coop_id, app_id, OFFICER))


class TestFlipTaxVariants:
    def test_flip_tax_gross_percent_scales_with_price(self, api):
        """PRD §3.6: "Under `GROSS_PERCENT`, the tax is the
        `gross_sale_price_cents` multiplied by the cooperative's
        `flip_tax_percent_bps` and divided by ten thousand, rounded half-up to
        whole cents."

        Design: Difficulty/dual_variant_calc/flip_tax_gross_percent_vs_per_share_divergence
        """
        env = setup_application_approved(
            coop_overrides={"flip_tax_policy": "GROSS_PERCENT",
                            "flip_tax_percent_bps": 200,
                            "flip_tax_per_share_cents": 50000},
            shares_allocated=200,
            app_overrides={"gross_sale_price_cents": 50000000,
                           "financing_percent_bps": 7000,
                           "debt_to_income_bps": 2000,
                           "post_closing_liquidity_cents": 100000000})
        transferred = record_transfer(env["coop"]["id"], env["app"]["id"])
        assert transferred["application_status"] == "TRANSFERRED"
        # 50000000 * 200 / 10000 = 1000000
        assert transferred["flip_tax_cents"] == 1000000

    def test_flip_tax_per_share_is_price_independent(self, api):
        """PRD §3.6: "Under `PER_SHARE`, the tax is the unit's
        `shares_allocated` multiplied by the cooperative's
        `flip_tax_per_share_cents` — it depends only on the unit's allocation,
        never on the price or the buyer's financing."

        Design: Difficulty/dual_variant_calc/flip_tax_gross_percent_vs_per_share_divergence
        """
        env = setup_application_approved(
            coop_overrides={"flip_tax_policy": "PER_SHARE",
                            "flip_tax_percent_bps": 200,
                            "flip_tax_per_share_cents": 50000},
            shares_allocated=200,
            app_overrides={"gross_sale_price_cents": 50000000,
                           "financing_percent_bps": 7000,
                           "debt_to_income_bps": 2000,
                           "post_closing_liquidity_cents": 100000000})
        transferred = record_transfer(env["coop"]["id"], env["app"]["id"])
        # 200 shares * 50000 cents = 10000000, independent of the sale price —
        # ten times the GROSS_PERCENT result for identical inputs.
        assert transferred["flip_tax_cents"] == 10000000


class TestFlipTaxRoundingAndPersistence:
    def test_flip_tax_rounds_half_up_at_fractional_cent(self, api):
        """PRD §3.6: "Under `GROSS_PERCENT`, the tax is the
        `gross_sale_price_cents` multiplied by the cooperative's
        `flip_tax_percent_bps` and divided by ten thousand, rounded half-up to
        whole cents."
        PRD §2.6: "all computed money amounts are rounded half-up to
        whole cents (zero decimal places)".

        Design: Difficulty/combinatorial_formula/flip_tax_per_share_rounding_then_multiply
        """
        env = setup_application_approved(
            coop_overrides={"flip_tax_policy": "GROSS_PERCENT",
                            "flip_tax_percent_bps": 150},
            app_overrides={"gross_sale_price_cents": 33333333})
        transferred = record_transfer(env["coop"]["id"], env["app"]["id"])
        # 33333333 * 150 / 10000 = 499999.995 -> 500000 (round half-up; a floor
        # implementation would record 499999 — the rounding mode is load-bearing).
        assert transferred["flip_tax_cents"] == 500000

    def test_recorded_flip_tax_not_reopened_by_later_policy_change(self, api):
        """PRD §3.6: "The flip tax is computed exactly once, at the
        instant of recording, against the policy then in force — later policy
        changes never reopen recorded transfers."
        PRD §3.2: "`SET_POLICY` writes the cooperative's policy fields —
        the `flip_tax_`, `sublet_policy_`, and `arrears_` families — from
        `payload_json`".

        Design: Difficulty/combinatorial_formula/flip_tax_per_share_rounding_then_multiply
        """
        env = setup_application_approved(
            coop_overrides={"flip_tax_policy": "GROSS_PERCENT",
                            "flip_tax_percent_bps": 150},
            app_overrides={"gross_sale_price_cents": 33333333})
        transferred = record_transfer(env["coop"]["id"], env["app"]["id"])
        assert transferred["flip_tax_cents"] == 500000

        resolution = open_resolution(env["coop"]["id"], "SET_POLICY", "Cooperative",
                                     env["coop"]["id"],
                                     payload_json={"flip_tax_percent_bps": 300})
        resolution = pass_resolution(env["coop"]["id"], resolution["id"])
        assert resolution["resolution_status"] == "PASSED"
        coop = validate_success(api.get_cooperative(env["coop"]["id"], OFFICER))
        assert coop["flip_tax_percent_bps"] == 300, "SET_POLICY writes policy fields"

        reread = _get_app(api, env["coop"]["id"], env["app"]["id"])
        assert reread["flip_tax_cents"] == 500000, \
            "recorded transfer is never reopened by later policy"
        assert reread["application_status"] == "TRANSFERRED"


class TestShareConservationThroughTransfer:
    def test_transfer_preserves_total_shares_and_rewrites_ledger(self, api):
        """PRD §2.7: "the cooperative's `total_shares` must always equal
        the sum of `shares_allocated` over all of its units, and the shares
        assigned to a unit through the share ledger must in turn reconcile
        exactly with that unit's allocation."
        PRD §3.6: "The recording also rewrites the share ledger: every
        `ACTIVE` ledger entry for the unit becomes `SUPERSEDED`, and a fresh
        `ACTIVE` entry is created assigning the buyer the unit's full
        `shares_allocated`."

        Design: Difficulty/compensating_invariant/share_conservation_through_transfer
        """
        env = setup_application_approved(
            coop_overrides={"flip_tax_policy": "GROSS_PERCENT",
                            "flip_tax_percent_bps": 200})
        coop_id = env["coop"]["id"]
        before = validate_success(api.get_cooperative(coop_id, OFFICER))
        assert before["total_shares"] == 100

        transferred = record_transfer(coop_id, env["app"]["id"])
        assert transferred["application_status"] == "TRANSFERRED"
        assert transferred["transferred_at"], "transferred_at is stamped"

        after = validate_success(api.get_cooperative(coop_id, OFFICER))
        assert after["total_shares"] == 100, "total_shares invariant preserved"

        data, _meta = validate_paginated(api.list_share_ledger_entries(
            coop_id, OFFICER, params={"unit_id": env["unit"]["id"]}))
        old_entries = [e for e in data if e["shareholder_id"] == env["owner"]["id"]]
        new_entries = [e for e in data if e["entry_status"] == "ACTIVE"]
        assert all(e["entry_status"] == "SUPERSEDED" for e in old_entries), \
            "seller's entries become SUPERSEDED"
        assert len(new_entries) == 1
        assert new_entries[0]["shares_held"] == 100
        assert new_entries[0]["shareholder_id"] != env["owner"]["id"]
        for entry in data:
            assert_share_ledger_entry(entry)
        assert_shares_conserved(after, data)

    def test_transfer_creates_buyer_shareholder_and_active_entry(self, api):
        """PRD §3.6: "If no shareholder record exists with the
        application's `buyer_email`, one is created for the buyer; the seller's
        `standing` is then recomputed and ordinarily stands unchanged."
        PRD §3.6: "a fresh `ACTIVE` entry is created assigning the buyer
        the unit's full `shares_allocated`."

        Design: Difficulty/compensating_invariant/share_conservation_through_transfer
        """
        env = setup_application_approved(
            app_overrides={"buyer_email": "newbuyer@example.com"})
        coop_id = env["coop"]["id"]
        assert find_shareholder_by_email(coop_id, "newbuyer@example.com") is None

        record_transfer(coop_id, env["app"]["id"])

        buyer = find_shareholder_by_email(coop_id, "newbuyer@example.com")
        assert buyer is not None, "a shareholder record is created for the buyer"
        assert buyer["standing"] == "GOOD_STANDING"

        data, _meta = validate_paginated(api.list_share_ledger_entries(
            coop_id, OFFICER, params={"shareholder_id": buyer["id"]}))
        assert len(data) == 1
        assert data[0]["entry_status"] == "ACTIVE"
        assert data[0]["unit_id"] == env["unit"]["id"]
        assert data[0]["shares_held"] == env["unit"]["shares_allocated"]

        seller = validate_success(
            api.get_shareholder(coop_id, env["owner"]["id"], OFFICER))
        assert seller["standing"] == "GOOD_STANDING", "seller standing unchanged"


class TestRecordTransferOCC:
    def test_record_transfer_with_stale_version_rejected(self, api):
        """PRD §3.6: "the request must carry
        `expected_cooperative_version` equal to the cooperative's current
        `version`, or the recording is rejected with `ERR_STALE_COOP_VERSION`
        (HTTP 412) and nothing changes — the guard exists because the flip-tax
        policy or share totals the client priced against may have been rewritten
        by a policy resolution since approval."

        Design: Corner/endpoints/record_transfer_occ_stale_version_rejected
        """
        env = setup_application_approved()
        coop_id, app_id = env["coop"]["id"], env["app"]["id"]
        stale_version = fresh_coop_version(coop_id)
        # Any clock advancement increments the cooperative's version (PRD 2.5).
        advance_clock(coop_id, "2026-08-16T00:00:00Z")
        resp = api.record_transfer(coop_id, app_id,
                                   {"expected_cooperative_version": stale_version},
                                   OFFICER)
        validate_error(resp, ApiErrorId.ERR_STALE_COOP_VERSION, expected_status=412)
        app = _get_app(api, coop_id, app_id)
        assert app["application_status"] == "APPROVED", "nothing changes on 412"
        assert_purchase_application(app)
