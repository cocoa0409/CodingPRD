"""Compensating reversals: money and credits are undone by opposite entries.

Two events undo something already recognized — revoking a licence and a society
rejecting a registered cue sheet. Neither rewrites history: each appends a new,
oppositely-signed ledger entry, leaves the original entry standing, and returns
the derived rollups (the composer's accrual, the licensee's credit exposure, the
work's lifetime performance credits) to the values they held before the forward
action.
"""

from test_helpers import (
    RIGHTS_MANAGER,
    assert_cash_unrecognized,
    assert_cents_equal,
    assert_composer_money,
    assert_credit_exposure,
    assert_credits_equal,
    assert_ledger_sum,
    assert_ok,
    assert_same_instant,
    assert_single_ledger_entry,
    assert_status,
    ledger_entries,
    new_issued_deal,
    new_registered_cue_sheet,
    pay_license_in_full,
    read_composer,
    read_composition,
    read_cue_sheet,
    read_license,
    read_licensee,
    select_ledger_entries,
)
from test_helpers import factories as build
from test_helpers.constants import CLOCK_ORIGIN

# A BROADCAST_TV tier at 300000 cents, NATIONAL, 12 months, no exclusivity and
# no rush: 300000 x 1.30 x 1.00 x 1.00 with no add-on and a spend basis of
# 390000, which is below the first discount band.
FINAL_FEE_CENTS = 390000
# 390000 x 40.00 / 100, the composer's share of the licence fee.
SYNC_SHARE_CENTS = 156000
CREDIT_LIMIT_CENTS = 5000000

# Three 45-second cues on a NETWORK sheet: 1.5 x 1.00, 1.5 x 0.65 and
# 1.5 x 0.35, each rounded to 2 decimals, then summed.
THEME_CREDITS = 1.50
FEATURE_CREDITS = 0.98
BACKGROUND_CREDITS = 0.53
SHEET_CREDITS = 3.01
SHEET_SECONDS = 135
# 3.01 x 1250 rounded half up is 3763; 3763 x 50.00 / 100 rounded half up.
PERFORMANCE_CENTS = 1882


def _paid_broadcast_licence(api):
    """A per-use BROADCAST_TV licence in ISSUED, paid in full.

    Issuance recognized the composer's 156000-cent share of the 390000-cent fee
    and moved the fee into the licensee's committed spend; the payment stamped
    the cash instant on that sync-fee entry.
    """
    deal = new_issued_deal(
        api,
        work_overrides={
            "composer_overrides": {
                "display_name": "Ravi Chandran",
                "pro_affiliation": "ASCAP",
                "payee_country": "US",
                "tax_withholding_pct": 0.30,
            },
            "agreement_overrides": {
                "writer_share_pct": 50.00,
                "publisher_share_pct": 50.00,
                "sync_fee_share_pct": 40.00,
                "advance_cents": 0,
            },
            "title": "Monsoon Wire",
            "duration_sec": 185,
            "tempo_bpm": 122,
            "genre": "ELECTRONIC",
            "mood_tags": ["TENSE"],
            "instrumentation": ["SYNTH", "PERCUSSION"],
        },
        tier_overrides={
            "media_type": "BROADCAST_TV",
            "base_rate_cents": 300000,
            "allowed_scales": ["LOCAL", "NATIONAL", "WORLDWIDE"],
        },
        licensee_overrides={
            "legal_name": "Monsoon Media",
            "licensee_type": "PRODUCTION_COMPANY",
            "credit_limit_cents": CREDIT_LIMIT_CENTS,
        },
    )
    pay_license_in_full(api, deal)

    assert_cents_equal(deal.license["final_fee_cents"], FINAL_FEE_CENTS, "final_fee_cents")
    original = assert_single_ledger_entry(
        ledger_entries(api, deal.work.composer_id),
        "SYNC_FEE",
        SYNC_SHARE_CENTS,
        source_ref_id=deal.license_id,
    )
    assert_same_instant(original["cash_recognized_at"], CLOCK_ORIGIN)
    return deal


def _registered_sheet_on_a_licence(api):
    """A REGISTERED cue sheet whose registration recognized 1882 cents.

    The composer is affiliated with BMI and takes a 50.00 writer share, so the
    sheet's 3.01 credits become 3763 cents gross and 1882 cents to the writer.
    """
    deal = new_issued_deal(
        api,
        work_overrides={
            "composer_overrides": {
                "display_name": "Noor Haddad",
                "pro_affiliation": "BMI",
                "payee_country": "US",
                "tax_withholding_pct": 0.30,
            },
            "agreement_overrides": {
                "writer_share_pct": 50.00,
                "publisher_share_pct": 50.00,
                "sync_fee_share_pct": 40.00,
                "advance_cents": 0,
            },
            "title": "Cedar Line",
            "duration_sec": 170,
            "tempo_bpm": 108,
            "genre": "CINEMATIC",
            "mood_tags": ["HOPEFUL"],
            "instrumentation": ["STRINGS", "PIANO"],
        },
        tier_overrides={
            "media_type": "BROADCAST_TV",
            "base_rate_cents": 300000,
            "allowed_scales": ["LOCAL", "NATIONAL", "WORLDWIDE"],
        },
        licensee_overrides={
            "legal_name": "Cedar Line Films",
            "licensee_type": "PRODUCTION_COMPANY",
            "credit_limit_cents": CREDIT_LIMIT_CENTS,
        },
    )
    composition_id = deal.composition_id
    sheet = new_registered_cue_sheet(
        api,
        [
            build.cue(composition_id, "THEME", 45),
            build.cue(composition_id, "FEATURE", 45),
            build.cue(composition_id, "BACKGROUND", 45),
        ],
        license_id=deal.license_id,
        society_reference="BMI-2026-0042",
        production_title="Cedar Line Feature",
        market_tier="NETWORK",
        broadcast_date="2026-08-01T00:00:00Z",
    )

    assert_credits_equal(sheet["total_credits"], SHEET_CREDITS, "total_credits")
    assert_single_ledger_entry(
        ledger_entries(api, deal.work.composer_id),
        "PERFORMANCE",
        PERFORMANCE_CENTS,
        source_ref_id=sheet["id"],
    )
    return deal, sheet


class TestLicenseRevocationCompensatesTheSyncFee:
    def test_revocation_appends_an_oppositely_signed_sync_fee_reversal(self, api):
        """PRD §3.5: "One compensating ledger entry with the sync-fee-reversal origin is appended for the composer, pointing at this licence, with an amount equal to the negation of `composer_sync_share_cents`, its accrual instant set to the clock, and its cash instant set to the clock when the original sync-fee entry had a cash instant and left null when it did not — the effect being that the composer's `accrued_unpaid_cents` returns to its pre-issuance value."

        Design: Difficulty/compensating_invariant/license_revocation_restores_composer_accrual_and_licensee_credit
        """
        deal = _paid_broadcast_licence(api)

        revoked = assert_ok(
            api.revoke_license(deal.license_id, {"reason": "LICENSEE_BREACH"}, RIGHTS_MANAGER)
        )
        assert_status(revoked, "REVOKED")
        assert revoked["revoke_reason"] == "LICENSEE_BREACH"

        reversal = assert_single_ledger_entry(
            ledger_entries(api, deal.work.composer_id),
            "SYNC_FEE_REVERSAL",
            -SYNC_SHARE_CENTS,
            source_ref_id=deal.license_id,
        )
        assert reversal["composer_id"] == deal.work.composer_id
        assert_same_instant(reversal["accrual_recognized_at"], CLOCK_ORIGIN)
        assert_same_instant(reversal["cash_recognized_at"], CLOCK_ORIGIN)
        assert reversal["statement_id"] is None

    def test_the_original_sync_fee_entry_survives_and_the_accrual_returns_to_zero(self, api):
        """PRD §2.11: "Money that must be undone is undone by appending a new, oppositely-signed ledger entry; an entry that has already been swept into a finalized or paid statement is never mutated or deleted."

        Design: Difficulty/compensating_invariant/license_revocation_restores_composer_accrual_and_licensee_credit
        """
        deal = _paid_broadcast_licence(api)
        composer_id = deal.work.composer_id

        assert_composer_money(
            read_composer(api, composer_id), accrued_unpaid_cents=SYNC_SHARE_CENTS
        )
        assert_ok(api.revoke_license(deal.license_id, {"reason": "LICENSEE_BREACH"}, RIGHTS_MANAGER))

        entries = ledger_entries(api, composer_id)
        original = assert_single_ledger_entry(
            entries, "SYNC_FEE", SYNC_SHARE_CENTS, source_ref_id=deal.license_id
        )
        assert_same_instant(original["accrual_recognized_at"], CLOCK_ORIGIN)
        assert_same_instant(original["cash_recognized_at"], CLOCK_ORIGIN)
        assert len(entries) == 2, f"expected two ledger entries, found {len(entries)}"
        assert_ledger_sum(entries, 0)
        assert_composer_money(
            read_composer(api, composer_id),
            accrued_unpaid_cents=0,
            outstanding_advance_cents=0,
        )

    def test_committed_spend_and_available_credit_return_to_their_pre_issuance_values(self, api):
        """PRD §3.5: "The licensee's `committed_spend_cents` falls by `final_fee_cents`."

        Design: Difficulty/compensating_invariant/license_revocation_restores_composer_accrual_and_licensee_credit
        """
        deal = _paid_broadcast_licence(api)

        assert_credit_exposure(
            read_licensee(api, deal.licensee_id),
            committed_spend_cents=FINAL_FEE_CENTS,
            reserved_spend_cents=0,
            credit_available_cents=CREDIT_LIMIT_CENTS - FINAL_FEE_CENTS,
        )

        assert_ok(api.revoke_license(deal.license_id, {"reason": "LICENSEE_BREACH"}, RIGHTS_MANAGER))

        assert_credit_exposure(
            read_licensee(api, deal.licensee_id),
            committed_spend_cents=0,
            reserved_spend_cents=0,
            credit_available_cents=CREDIT_LIMIT_CENTS,
        )

    def test_the_revoked_licence_keeps_its_fee_and_collected_cash_while_the_work_clears(self, api):
        """PRD §2.11: "Reversal is always compensating, never destructive."

        Design: Difficulty/compensating_invariant/license_revocation_restores_composer_accrual_and_licensee_credit
        """
        deal = _paid_broadcast_licence(api)

        assert_ok(api.revoke_license(deal.license_id, {"reason": "LICENSEE_BREACH"}, RIGHTS_MANAGER))

        license_row = read_license(api, deal.license_id)
        assert_status(license_row, "REVOKED")
        assert_cents_equal(license_row["final_fee_cents"], FINAL_FEE_CENTS, "final_fee_cents")
        assert_cents_equal(
            license_row["collected_amount_cents"], FINAL_FEE_CENTS, "collected_amount_cents"
        )
        assert_cents_equal(
            license_row["composer_sync_share_cents"],
            SYNC_SHARE_CENTS,
            "composer_sync_share_cents",
        )
        assert_same_instant(license_row["collected_at"], CLOCK_ORIGIN)

        composition = read_composition(api, deal.composition_id)
        assert composition["active_license_count"] == 0
        assert composition["exclusive_block_until"] is None


class TestSocietyRejectionCompensatesThePerformanceRoyalty:
    def test_rejection_appends_an_oppositely_signed_performance_reversal(self, api):
        """PRD §3.7: "On `REJECT` a `rejection_reason` must be supplied, absent which the request is refused with `ERR_VALIDATION`; the sheet moves `REGISTERED → REJECTED_BY_SOCIETY`, and one compensating entry with the performance-reversal origin is appended per previously credited composer, each for the negation of the performance amount it compensates."

        Design: Difficulty/compensating_invariant/society_rejection_restores_composition_performance_credits
        """
        deal, sheet = _registered_sheet_on_a_licence(api)

        rejected = assert_ok(
            api.record_society_decision(
                sheet["id"],
                {"decision": "REJECT", "rejection_reason": "CUE_TIMING_MISMATCH"},
                RIGHTS_MANAGER,
            )
        )
        assert_status(rejected, "REJECTED_BY_SOCIETY")
        assert rejected["rejection_reason"] == "CUE_TIMING_MISMATCH"

        reversal = assert_single_ledger_entry(
            ledger_entries(api, deal.work.composer_id),
            "PERFORMANCE_REVERSAL",
            -PERFORMANCE_CENTS,
            source_ref_id=sheet["id"],
        )
        assert reversal["composer_id"] == deal.work.composer_id
        assert_same_instant(reversal["accrual_recognized_at"], CLOCK_ORIGIN)
        assert reversal["statement_id"] is None

    def test_lifetime_performance_credits_return_to_their_pre_registration_value(self, api):
        """PRD §3.7: "Because the sheet has now left both `REGISTERED` and `ACCEPTED_BY_SOCIETY`, `lifetime_performance_credits` on every cited work returns to its pre-registration value."

        Design: Difficulty/compensating_invariant/society_rejection_restores_composition_performance_credits
        """
        deal, sheet = _registered_sheet_on_a_licence(api)

        assert_credits_equal(
            read_composition(api, deal.composition_id)["lifetime_performance_credits"],
            SHEET_CREDITS,
            "lifetime_performance_credits while registered",
        )

        assert_ok(
            api.record_society_decision(
                sheet["id"],
                {"decision": "REJECT", "rejection_reason": "CUE_TIMING_MISMATCH"},
                RIGHTS_MANAGER,
            )
        )

        assert_credits_equal(
            read_composition(api, deal.composition_id)["lifetime_performance_credits"],
            0.00,
            "lifetime_performance_credits after rejection",
        )

    def test_the_original_performance_entry_survives_and_only_the_sync_fee_stays_accrued(
        self, api
    ):
        """PRD §2.11: "Money that must be undone is undone by appending a new, oppositely-signed ledger entry; an entry that has already been swept into a finalized or paid statement is never mutated or deleted."

        Design: Difficulty/compensating_invariant/society_rejection_restores_composition_performance_credits
        """
        deal, sheet = _registered_sheet_on_a_licence(api)
        composer_id = deal.work.composer_id

        assert_ok(
            api.record_society_decision(
                sheet["id"],
                {"decision": "REJECT", "rejection_reason": "CUE_TIMING_MISMATCH"},
                RIGHTS_MANAGER,
            )
        )

        entries = ledger_entries(api, composer_id)
        original = assert_single_ledger_entry(
            entries, "PERFORMANCE", PERFORMANCE_CENTS, source_ref_id=sheet["id"]
        )
        assert_same_instant(original["accrual_recognized_at"], CLOCK_ORIGIN)
        assert_cash_unrecognized(original)

        assert_single_ledger_entry(
            entries, "SYNC_FEE", SYNC_SHARE_CENTS, source_ref_id=deal.license_id
        )
        assert len(entries) == 3, f"expected three ledger entries, found {len(entries)}"
        assert_ledger_sum(select_ledger_entries(entries, source_ref_id=sheet["id"]), 0)
        assert_ledger_sum(entries, SYNC_SHARE_CENTS)
        assert_composer_money(
            read_composer(api, composer_id), accrued_unpaid_cents=SYNC_SHARE_CENTS
        )

    def test_the_sheet_keeps_the_credit_figures_it_computed_at_creation(self, api):
        """PRD §3.7: "Credits are computed at creation and never again."

        Design: Difficulty/compensating_invariant/society_rejection_restores_composition_performance_credits
        """
        deal, sheet = _registered_sheet_on_a_licence(api)

        assert_ok(
            api.record_society_decision(
                sheet["id"],
                {"decision": "REJECT", "rejection_reason": "CUE_TIMING_MISMATCH"},
                RIGHTS_MANAGER,
            )
        )

        reread = read_cue_sheet(api, sheet["id"])
        assert_credits_equal(reread["total_credits"], SHEET_CREDITS, "total_credits")
        assert reread["total_seconds"] == SHEET_SECONDS
        assert_credits_equal(
            reread["credits_by_composition"][deal.composition_id],
            SHEET_CREDITS,
            "credits_by_composition",
        )
        breakdown = reread["cue_credit_breakdown"]
        assert [item["usage_type"] for item in breakdown] == ["THEME", "FEATURE", "BACKGROUND"]
        for item, expected in zip(
            breakdown, [THEME_CREDITS, FEATURE_CREDITS, BACKGROUND_CREDITS]
        ):
            assert_credits_equal(item["credits"], expected, f"{item['usage_type']} credits")
        assert reread["registration_round"] == 1
        assert reread["society_reference"] == "BMI-2026-0042"
