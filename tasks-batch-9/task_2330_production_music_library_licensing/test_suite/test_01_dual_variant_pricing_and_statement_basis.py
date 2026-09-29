"""The two variant pairs: quote versus issuance pricing, accrual versus cash sweeps.

Both pairs run the same formula twice over identical stored inputs and differ
only in the snapshot each variant reads — the licensee's committed spend in the
pricing pair, the recognition timestamp column in the statement pair.
"""

from test_helpers import (
    ACCOUNTANT_ONE,
    CATALOG_ADMIN,
    LICENSING_AGENT,
    RIGHTS_MANAGER,
    assert_cents_equal,
    assert_composer_money,
    assert_created,
    assert_credit_exposure,
    assert_final_figures,
    assert_ok,
    assert_quote_figures,
    assert_statement_figures,
    composer_version,
    composition_version,
    ledger_entries,
    make_licensee_headers,
    new_active_agreement,
    new_composer,
    new_licensee,
    new_tier,
    read_composer,
    read_licensee,
    select_ledger_entries,
)
from test_helpers import factories as build


def _two_film_deals(api):
    """One agreement, two catalogued works, two identical FILM sync requests.

    Request B is carried all the way to an issued licence; request A is left
    ACCEPTED so that its quote was produced before B's fee entered committed
    spend.
    """
    composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
    agreement = new_active_agreement(api, composer["id"], sync_fee_share_pct=40.00)
    tier = new_tier(
        api,
        media_type="FILM",
        base_rate_cents=600000,
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        min_term_months=1,
        max_term_months=120,
    )
    licensee = new_licensee(api, legal_name="Northline Pictures", credit_limit_cents=10000000)

    works = []
    for title, tempo in (("Harbour Lights", 130), ("Slate Horizon", 118)):
        composition = assert_created(
            api.create_composition(
                build.composition_payload(
                    composer["id"], agreement["id"], title=title, tempo_bpm=tempo
                ),
                CATALOG_ADMIN,
            )
        )
        works.append(assert_ok(api.catalog_composition(composition["id"], None, CATALOG_ADMIN)))

    requests = []
    for composition in works:
        request = assert_created(
            api.create_sync_request(
                build.sync_request_payload(
                    composition["id"],
                    licensee["id"],
                    tier["id"],
                    media_type="FILM",
                    distribution_scale="NATIONAL",
                    requested_term_start="2026-09-01T00:00:00Z",
                    requested_term_months=24,
                ),
                LICENSING_AGENT,
            )
        )
        assert_ok(api.review_sync_request(request["id"], None, LICENSING_AGENT))
        request = assert_ok(
            api.quote_sync_request(request["id"], build.quote_payload(14), LICENSING_AGENT)
        )
        assert_ok(
            api.accept_sync_request(
                request["id"], None, make_licensee_headers(licensee["id"])
            )
        )
        requests.append(request)

    request_a, request_b = requests
    license_b = assert_created(
        api.create_license(
            build.per_use_license_payload(
                request_b["id"], composition_version(api, works[1]["id"])
            ),
            LICENSING_AGENT,
        )
    )
    return {
        "composer": composer,
        "agreement": agreement,
        "tier": tier,
        "licensee": licensee,
        "composition_a": works[0],
        "composition_b": works[1],
        "request_a": request_a,
        "request_b": request_b,
        "license_b": license_b,
    }


class TestProvisionalVersusFinalLicenseFee:
    def test_final_fee_reprices_at_a_deeper_discount_than_the_standing_quote(self, api):
        """PRD §3.5: "That final variant differs from the provisional one in exactly
        one respect: the spend basis adds the `committed_spend_cents` observed at the
        issuance instant, which includes every licence issued to this licensee after
        the quote was produced."

        Design: Difficulty/dual_variant_calc/license_fee_provisional_vs_final_diverges_on_intervening_issuance
        """
        ground = _two_film_deals(api)

        assert_quote_figures(ground["request_a"], 1914000, 10.00, 1722600)
        assert_final_figures(ground["license_b"], 1914000, 10.00, 1722600)

        license_a = assert_created(
            api.create_license(
                build.per_use_license_payload(
                    ground["request_a"]["id"],
                    composition_version(api, ground["composition_a"]["id"]),
                ),
                LICENSING_AGENT,
            )
        )
        assert_final_figures(license_a, 3636600, 15.00, 1626900)
        assert_cents_equal(
            ground["request_a"]["quoted_fee_cents"] - license_a["final_fee_cents"],
            95700,
            "quote less final fee",
        )

    def test_quoted_figures_are_never_back_patched_by_the_issuance_reprice(self, api):
        """PRD §3.5: "The recomputed discount tier can therefore differ from
        `quoted_discount_pct`, and `final_fee_cents` can differ from
        `quoted_fee_cents`; the quote is never back-patched to match."

        Design: Difficulty/dual_variant_calc/license_fee_provisional_vs_final_diverges_on_intervening_issuance
        """
        ground = _two_film_deals(api)
        assert_created(
            api.create_license(
                build.per_use_license_payload(
                    ground["request_a"]["id"],
                    composition_version(api, ground["composition_a"]["id"]),
                ),
                LICENSING_AGENT,
            )
        )

        reread = assert_ok(api.get_sync_request(ground["request_a"]["id"], LICENSING_AGENT))
        assert_quote_figures(reread, 1914000, 10.00, 1722600)

    def test_only_the_final_fee_reaches_committed_spend_and_the_composer_ledger(self, api):
        """PRD §3.5: "It is `final_fee_cents`, never `quoted_fee_cents`, that enters
        `committed_spend_cents` and that the composer's ledger entry is derived from."

        Design: Difficulty/dual_variant_calc/license_fee_provisional_vs_final_diverges_on_intervening_issuance
        """
        ground = _two_film_deals(api)
        license_a = assert_created(
            api.create_license(
                build.per_use_license_payload(
                    ground["request_a"]["id"],
                    composition_version(api, ground["composition_a"]["id"]),
                ),
                LICENSING_AGENT,
            )
        )

        assert_cents_equal(license_a["composer_sync_share_cents"], 650760, "share on A")
        assert_cents_equal(
            ground["license_b"]["composer_sync_share_cents"], 689040, "share on B"
        )
        assert_credit_exposure(read_licensee(api, ground["licensee"]["id"]), 3349500, 0, 6650500)
        assert_composer_money(
            read_composer(api, ground["composer"]["id"]), accrued_unpaid_cents=1339800
        )
        assert license_a["term_start"].startswith("2026-09-01")
        assert license_a["term_end"].startswith("2028-08-31")


def _ledger_of_three_recognitions(api):
    """One composer whose ledger holds a collected fee, an uncollected performance
    amount and a collected settlement, plus a 150000 advance to recoup."""
    composer = new_composer(
        api, display_name="Ivo Brandt", pro_affiliation="BMI", tax_withholding_pct=0.30
    )
    agreement = new_active_agreement(
        api, composer["id"], sync_fee_share_pct=40.00, advance_cents=150000
    )
    composition = assert_created(
        api.create_composition(
            build.composition_payload(
                composer["id"],
                agreement["id"],
                title="Night Freight",
                duration_sec=150,
                tempo_bpm=96,
                genre="ELECTRONIC",
                mood_tags=["TENSE", "DARK"],
                instrumentation=["SYNTH", "PERCUSSION"],
            ),
            CATALOG_ADMIN,
        )
    )
    composition = assert_ok(api.catalog_composition(composition["id"], None, CATALOG_ADMIN))
    tier = new_tier(api, media_type="BROADCAST_TV", base_rate_cents=300000)
    licensee = new_licensee(
        api, legal_name="Meridian Broadcast", licensee_type="BROADCASTER", credit_limit_cents=5000000
    )

    request = assert_created(
        api.create_sync_request(
            build.sync_request_payload(
                composition["id"],
                licensee["id"],
                tier["id"],
                media_type="BROADCAST_TV",
                distribution_scale="NATIONAL",
                requested_term_start="2026-09-01T00:00:00Z",
                requested_term_months=12,
            ),
            LICENSING_AGENT,
        )
    )
    assert_ok(api.review_sync_request(request["id"], None, LICENSING_AGENT))
    assert_ok(api.quote_sync_request(request["id"], build.quote_payload(14), LICENSING_AGENT))
    assert_ok(
        api.accept_sync_request(request["id"], None, make_licensee_headers(licensee["id"]))
    )
    license_row = assert_created(
        api.create_license(
            build.per_use_license_payload(
                request["id"], composition_version(api, composition["id"])
            ),
            LICENSING_AGENT,
        )
    )
    assert_ok(
        api.record_license_payment(
            license_row["id"], {"amount_cents": 390000}, ACCOUNTANT_ONE
        )
    )

    sheet = assert_created(
        api.create_cue_sheet(
            build.three_cue_network_sheet(
                composition["id"],
                license_id=license_row["id"],
                production_title="Night Freight Promo",
            ),
            LICENSING_AGENT,
        )
    )
    assert_ok(
        api.register_cue_sheet(
            sheet["id"], {"society_reference": "BMI-2026-0001"}, RIGHTS_MANAGER
        )
    )

    match = assert_created(
        api.create_fingerprint_match(
            build.fingerprint_match_payload(composition["id"]), CATALOG_ADMIN
        )
    )
    claim = assert_created(
        api.create_infringement_claim({"fingerprint_match_id": match["id"]}, RIGHTS_MANAGER)
    )
    assert_ok(api.notice_claim(claim["id"], {"notice_channel": "DMCA_EMAIL"}, RIGHTS_MANAGER))
    assert_ok(api.settle_claim(claim["id"], build.settle_claim_payload(), RIGHTS_MANAGER))

    return {
        "composer": composer,
        "agreement": agreement,
        "composition": composition,
        "license": license_row,
        "cue_sheet": sheet,
        "claim": claim,
    }


class TestAccrualVersusCashStatementBasis:
    def test_preview_reports_both_bases_over_the_same_ledger(self, api):
        """PRD §3.9: "It returns `basis`, `accrual_gross_cents` and `cash_gross_cents`
        — always both, so the two bases can be compared on identical data — plus
        `gross_cents`, `included_entry_count`, `outstanding_advance_cents`,
        `projected_recoup_cents`, `projected_withholding_cents`, `projected_net_cents`
        and `projected_payout_status`, all of which follow the selected basis."

        Design: Difficulty/dual_variant_calc/statement_accrual_vs_cash_basis_diverges_on_uncollected_performance
        """
        ground = _ledger_of_three_recognitions(api)
        composer_id = ground["composer"]["id"]

        accrual = assert_ok(
            api.get_royalty_preview(
                composer_id, build.preview_params(basis="ACCRUAL"), ACCOUNTANT_ONE
            )
        )
        cash = assert_ok(
            api.get_royalty_preview(
                composer_id, build.preview_params(basis="CASH"), ACCOUNTANT_ONE
            )
        )

        for preview in (accrual, cash):
            assert_cents_equal(preview["accrual_gross_cents"], 247882, "accrual_gross_cents")
            assert_cents_equal(preview["cash_gross_cents"], 246000, "cash_gross_cents")

        assert accrual["basis"] == "ACCRUAL"
        assert_cents_equal(accrual["gross_cents"], 247882, "accrual gross_cents")
        assert accrual["included_entry_count"] == 3
        assert_cents_equal(accrual["projected_recoup_cents"], 150000, "projected_recoup_cents")
        assert_cents_equal(
            accrual["projected_withholding_cents"], 29365, "projected_withholding_cents"
        )
        assert_cents_equal(accrual["projected_net_cents"], 68517, "projected_net_cents")
        assert accrual["projected_payout_status"] == "PAYABLE"

    def test_cash_basis_drops_the_entry_whose_money_is_still_outstanding(self, api):
        """PRD §3.9: "Under `CASH`, the window is tested against `cash_recognized_at`
        and any entry whose `cash_recognized_at` is null is excluded entirely,
        deferring uncollected obligations to a later period."

        Design: Difficulty/dual_variant_calc/statement_accrual_vs_cash_basis_diverges_on_uncollected_performance
        """
        ground = _ledger_of_three_recognitions(api)
        composer_id = ground["composer"]["id"]

        accrual = assert_ok(
            api.get_royalty_preview(
                composer_id, build.preview_params(basis="ACCRUAL"), ACCOUNTANT_ONE
            )
        )
        cash = assert_ok(
            api.get_royalty_preview(
                composer_id, build.preview_params(basis="CASH"), ACCOUNTANT_ONE
            )
        )

        assert cash["basis"] == "CASH"
        assert_cents_equal(cash["gross_cents"], 246000, "cash gross_cents")
        assert cash["included_entry_count"] == 2
        assert_cents_equal(cash["projected_recoup_cents"], 150000, "projected_recoup_cents")
        assert_cents_equal(
            cash["projected_withholding_cents"], 28800, "projected_withholding_cents"
        )
        assert_cents_equal(cash["projected_net_cents"], 67200, "projected_net_cents")
        assert cash["projected_payout_status"] == "PAYABLE"
        assert_cents_equal(
            accrual["projected_net_cents"] - cash["projected_net_cents"], 1317, "net divergence"
        )

    def test_accrual_statement_sweeps_the_uncollected_performance_entry(self, api):
        """PRD §3.9: "Under `ACCRUAL`, the window is tested against
        `accrual_recognized_at`, so an obligation recognized in the period is included
        even when no money has been collected — a performance entry from a cue sheet
        registered but not yet accepted by the society is swept on this basis."

        Design: Difficulty/dual_variant_calc/statement_accrual_vs_cash_basis_diverges_on_uncollected_performance
        """
        ground = _ledger_of_three_recognitions(api)
        composer_id = ground["composer"]["id"]

        statement = assert_created(
            api.create_royalty_statement(
                build.statement_payload(composer_id, composer_version(api, composer_id)),
                ACCOUNTANT_ONE,
            )
        )
        assert_statement_figures(
            statement,
            gross_cents=247882,
            recouped_cents=150000,
            withholding_cents=29365,
            net_payable_cents=68517,
            payout_status="PAYABLE",
            line_count=3,
        )
        assert_composer_money(
            read_composer(api, composer_id), outstanding_advance_cents=0
        )

        performance = select_ledger_entries(
            ledger_entries(api, composer_id), source_type="PERFORMANCE"
        )
        assert len(performance) == 1
        assert_cents_equal(performance[0]["amount_cents"], 1882, "performance amount_cents")
        assert performance[0]["cash_recognized_at"] is None
        assert performance[0]["statement_id"] == statement["id"]
