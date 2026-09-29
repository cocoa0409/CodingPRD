"""Boundary precision: the minimum-payout threshold and the empty pool eligible set.

Both groups sit one unit either side of a named edge. The statement group puts a
net payable exactly on the 2500-cent minimum and then one cent below it; the pool
group accepts a usage report whose only cue sheet has never been registered, so
the eligible set is empty, and then the same report once that sheet is filed.
"""

import pytest

from test_helpers import (
    ACCOUNTANT_ONE,
    ACCOUNTANT_TWO,
    accept_usage_report,
    assert_allocation,
    assert_cents_equal,
    assert_composer_money,
    assert_created,
    assert_credits_equal,
    assert_declared_error,
    assert_ok,
    assert_pool_conserves_cents,
    assert_same_instant,
    assert_single_ledger_entry,
    assert_statement_figures,
    assert_status,
    finalize_statement,
    ledger_entries,
    new_active_blanket,
    new_cataloged_work,
    new_composer,
    new_cue_sheet,
    new_draft_statement,
    new_licensee,
    open_usage_report,
    read_blanket_agreement,
    read_composer,
    read_cue_sheet,
    read_statement,
    register_cue_sheet,
    select_ledger_entries,
    submit_usage_report,
)
from test_helpers import factories as build
from test_helpers.test_users import ACCOUNTANT_ONE_USER_ID, ACCOUNTANT_TWO_USER_ID


# ---------------------------------------------------------------------------
# The minimum-payout boundary
# ---------------------------------------------------------------------------


def _composer_holding_one_adjustment(api, amount_cents, display_name):
    """A composer with no agreement — so no advance to recoup — whose ledger holds
    exactly one manual adjustment stamped at the clock inside the August window."""
    composer = new_composer(
        api,
        display_name=display_name,
        pro_affiliation="ASCAP",
        payee_country="US",
        tax_withholding_pct=0.30,
    )
    assert_created(
        api.create_royalty_ledger_entry(
            build.ledger_entry_payload(composer["id"], amount_cents), ACCOUNTANT_ONE
        )
    )
    return composer


class TestStatementMinimumPayoutBoundary:
    @pytest.mark.parametrize(
        "gross_cents, net_payable_cents, payout_status",
        [
            (3571, 2500, "PAYABLE"),
            (3570, 2499, "HELD_BELOW_MINIMUM"),
        ],
    )
    def test_payout_status_turns_only_strictly_below_the_minimum(
        self, api, gross_cents, net_payable_cents, payout_status
    ):
        """PRD §3.9: "`payout_status` is `NO_ACTIVITY` when `gross_cents` is 0,
        `HELD_BELOW_MINIMUM` when `net_payable_cents` is below the minimum payout of
        2500 cents, and `PAYABLE` otherwise."

        Design: Difficulty/boundary_precision_check/statement_min_payout_boundary_2500_vs_2499
        """
        composer = _composer_holding_one_adjustment(api, gross_cents, "Boundary Composer")

        statement = new_draft_statement(api, composer["id"])

        assert_statement_figures(
            statement,
            gross_cents=gross_cents,
            recouped_cents=0,
            withholding_cents=1071,
            net_payable_cents=net_payable_cents,
            payout_status=payout_status,
            line_count=1,
        )

    def test_withholding_rounds_half_up_once_on_both_sides_of_the_minimum(self, api):
        """PRD §3.9: "`withholding_cents` is the post-recoupment base — `gross_cents`
        less `recouped_cents` — multiplied by the composer's `tax_withholding_pct` and
        rounded half up exactly once."

        Design: Difficulty/boundary_precision_check/statement_min_payout_boundary_2500_vs_2499
        """
        at_minimum = _composer_holding_one_adjustment(api, 3571, "Boundary Composer One")
        below_minimum = _composer_holding_one_adjustment(api, 3570, "Boundary Composer Two")

        statement_at = new_draft_statement(api, at_minimum["id"])
        statement_below = new_draft_statement(api, below_minimum["id"])

        # 3571 * 0.30 is 1071.3 and 3570 * 0.30 is exactly 1071, so a single
        # half-up rounding gives both statements the same withholding and leaves
        # the one-cent difference in gross to land wholly in net payable.
        assert_cents_equal(statement_at["withholding_cents"], 1071, "withholding at the minimum")
        assert_cents_equal(
            statement_below["withholding_cents"], 1071, "withholding below the minimum"
        )
        assert_cents_equal(
            statement_at["net_payable_cents"] - statement_below["net_payable_cents"],
            1,
            "net payable difference",
        )

    def test_statement_held_one_cent_below_the_minimum_cannot_be_paid(self, api):
        """PRD §3.9: "Two guards apply, in this order: `payout_status` must read
        `PAYABLE`, so a statement that is `HELD_BELOW_MINIMUM` or has no activity is
        refused with `ERR_STATEMENT_NOT_PAYABLE`; and the acting `X-User-ID` must differ
        from `finalized_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/boundary_precision_check/statement_min_payout_boundary_2500_vs_2499
        """
        composer = _composer_holding_one_adjustment(api, 3570, "Boundary Composer Two")
        statement = new_draft_statement(api, composer["id"])
        finalized = finalize_statement(api, statement["id"])
        assert_status(finalized, "FINALIZED")

        assert_declared_error(
            api.pay_royalty_statement(
                statement["id"], {"payment_reference": "WIRE-0002"}, ACCOUNTANT_TWO
            ),
            "ERR_STATEMENT_NOT_PAYABLE",
        )

        assert_status(read_statement(api, statement["id"]), "FINALIZED")
        assert_composer_money(read_composer(api, composer["id"]), lifetime_paid_cents=0)

    def test_statement_exactly_at_the_minimum_is_paid_by_a_second_accountant(self, api):
        """PRD §3.9: "Payment then moves `FINALIZED → PAID`, taking a
        `payment_reference` recorded on the statement alongside `paid_by_user_id` and
        `paid_at`, and raising the composer's `lifetime_paid_cents` by
        `net_payable_cents`."

        Design: Difficulty/boundary_precision_check/statement_min_payout_boundary_2500_vs_2499
        """
        composer = _composer_holding_one_adjustment(api, 3571, "Boundary Composer One")
        statement = new_draft_statement(api, composer["id"])
        finalize_statement(api, statement["id"])

        paid = assert_ok(
            api.pay_royalty_statement(
                statement["id"], {"payment_reference": "WIRE-0001"}, ACCOUNTANT_TWO
            )
        )

        assert_status(paid, "PAID")
        assert paid["finalized_by_user_id"] == ACCOUNTANT_ONE_USER_ID
        assert paid["paid_by_user_id"] == ACCOUNTANT_TWO_USER_ID
        assert_cents_equal(paid["net_payable_cents"], 2500, "net_payable_cents")
        assert_composer_money(
            read_composer(api, composer["id"]),
            accrued_unpaid_cents=0,
            lifetime_paid_cents=2500,
        )

        entries = ledger_entries(api, composer["id"], source_type="ADJUSTMENT")
        assert len(entries) == 1
        assert entries[0]["statement_id"] == statement["id"]


# ---------------------------------------------------------------------------
# The empty eligible set of the pool distribution
# ---------------------------------------------------------------------------


def _submitted_report_with_one_sheet(api, register_sheet):
    """A monthly blanket agreement whose August report carries exactly one cue sheet.

    The sheet cites a single 90-second BACKGROUND cue on a CABLE transmission and is
    registered with a society only when `register_sheet` is true, which is the one
    thing that decides whether the pool has an eligible work.
    """
    work = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Selma Ruiz", "pro_affiliation": "ASCAP"},
        agreement_overrides={
            "writer_share_pct": 50.00,
            "publisher_share_pct": 50.00,
            "sync_fee_share_pct": 40.00,
            "blanket_opt_in": True,
        },
        title="Dry Season",
        duration_sec=160,
        tempo_bpm=98,
        genre="FOLK",
        mood_tags=["CALM"],
        instrumentation=["GUITAR"],
    )
    licensee = new_licensee(
        api,
        legal_name="Plateau Networks",
        licensee_type="BROADCASTER",
        credit_limit_cents=10000000,
    )
    blanket = new_active_blanket(
        api,
        licensee,
        coverage_start="2026-08-01T00:00:00Z",
        coverage_end="2027-08-01T00:00:00Z",
        annual_fee_cents=4800000,
        reporting_cadence="MONTHLY",
        usage_cap_minutes=3,
        pool_share_pct=25.00,
    )
    open_usage_report(api, blanket)
    sheet = new_cue_sheet(
        api,
        [build.cue(work.composition_id, "BACKGROUND", 90)],
        usage_report_id=blanket.usage_report_id,
        production_title="Dry Season Segment",
        broadcast_date="2026-08-09T00:00:00Z",
        market_tier="CABLE",
    )
    if register_sheet:
        sheet = register_cue_sheet(api, sheet["id"], "ASCAP-2026-0001")
    submit_usage_report(api, blanket)
    return blanket, work, sheet


class TestPoolEmptyEligibleSet:
    def test_pool_is_still_funded_when_no_sheet_has_reached_the_society(
        self, api, clock_origin
    ):
        """PRD §3.6: "When the eligible set is empty, `pool_allocations` is an empty
        array, `pool_cents` and `pool_admin_fee_cents` are still computed, and
        `pool_distributable_cents` is simply retained by the library with no ledger entry
        appended."

        Design: Difficulty/boundary_precision_check/pool_empty_eligible_set_retains_distributable_with_no_ledger
        """
        blanket, _work, _sheet = _submitted_report_with_one_sheet(api, register_sheet=False)

        accept_usage_report(api, blanket)
        report = blanket.usage_report

        assert_status(report, "ACCEPTED")
        assert_same_instant(report["accepted_at"], clock_origin)
        # 4800000 * 25.00 / 100 * 1/12 rounds to 100000, of which 15.00 percent
        # is retained as the administration fee.
        assert_cents_equal(report["pool_cents"], 100000, "pool_cents")
        assert_cents_equal(report["pool_admin_fee_cents"], 15000, "pool_admin_fee_cents")
        assert_cents_equal(
            report["pool_distributable_cents"], 85000, "pool_distributable_cents"
        )
        assert report["pool_allocations"] == []
        assert_pool_conserves_cents(report)

    def test_collected_sheet_is_outside_the_frozen_usage_and_the_eligible_set(self, api):
        """PRD §3.6: "The eligible works are the distinct compositions cited by the cues
        of this report's attached cue sheets whose `status` is `REGISTERED` or
        `ACCEPTED_BY_SOCIETY` and whose governing agreement has `blanket_opt_in` true."

        Design: Difficulty/boundary_precision_check/pool_empty_eligible_set_retains_distributable_with_no_ledger
        """
        blanket, work, sheet = _submitted_report_with_one_sheet(api, register_sheet=False)

        accept_usage_report(api, blanket)
        report = blanket.usage_report

        assert report["reported_minutes_total"] == 0
        assert_credits_equal(report["reported_credits_total"], 0.00, "reported_credits_total")
        assert report["pool_allocations"] == []

        agreement = read_blanket_agreement(api, blanket.agreement_id)
        assert agreement["reported_minutes_ytd"] == 0
        assert agreement["overage_minutes"] == 0
        assert_cents_equal(agreement["overage_cents"], 0, "overage_cents")
        assert_cents_equal(
            agreement["pool_distributed_cents"], 85000, "pool_distributed_cents"
        )
        assert_cents_equal(
            agreement["pool_admin_fee_cents"], 15000, "cumulative pool_admin_fee_cents"
        )

        # The sheet itself was still costed at creation even though it never
        # reached the society: 90 / 30 * 0.35 * 0.65 is 0.6825, rounded to 0.68.
        stored_sheet = read_cue_sheet(api, sheet["id"])
        assert_status(stored_sheet, "COLLECTED")
        assert_credits_equal(stored_sheet["total_credits"], 0.68, "total_credits")
        assert stored_sheet["total_seconds"] == 90
        assert_credits_equal(
            stored_sheet["credits_by_composition"][work.composition_id],
            0.68,
            "credits_by_composition",
        )

    def test_no_blanket_pool_entry_is_appended_for_an_empty_allocation_array(self, api):
        """PRD §3.6: "**Step five**: because allocations exist, one ledger entry with the
        blanket-pool origin is appended per allocation, for the composer of that
        allocation's work, whose amount is the allocation multiplied by the governing
        agreement's `writer_share_pct` divided by 100 and rounded half up, pointing at
        this report, with both its accrual and cash instants set to the clock; each
        append raises that composer's `accrued_unpaid_cents`, and the entries are
        appended in `pool_allocations` order."

        Design: Difficulty/boundary_precision_check/pool_empty_eligible_set_retains_distributable_with_no_ledger
        """
        blanket, work, _sheet = _submitted_report_with_one_sheet(api, register_sheet=False)

        accept_usage_report(api, blanket)

        entries = ledger_entries(api, work.composer_id)
        assert select_ledger_entries(entries, source_type="BLANKET_POOL") == []
        assert_composer_money(read_composer(api, work.composer_id), accrued_unpaid_cents=0)

    def test_one_registered_sheet_takes_the_whole_distributable_pool(self, api):
        """PRD §3.6: "Each work's floor share is the largest whole number not exceeding
        `pool_distributable_cents` multiplied by that work's credits divided by the total
        credits."

        Design: Difficulty/boundary_precision_check/pool_empty_eligible_set_retains_distributable_with_no_ledger
        """
        blanket, work, _sheet = _submitted_report_with_one_sheet(api, register_sheet=True)

        accept_usage_report(api, blanket)
        report = blanket.usage_report

        # 90 seconds is 1.5 minutes and the ceiling is applied once per report.
        assert report["reported_minutes_total"] == 2
        assert_credits_equal(report["reported_credits_total"], 0.68, "reported_credits_total")
        assert_cents_equal(report["pool_cents"], 100000, "pool_cents")
        assert_cents_equal(
            report["pool_distributable_cents"], 85000, "pool_distributable_cents"
        )
        assert len(report["pool_allocations"]) == 1
        assert_allocation(report, work.composition_id, 0.68, 85000)
        assert_pool_conserves_cents(report)

        entry = assert_single_ledger_entry(
            ledger_entries(api, work.composer_id),
            "BLANKET_POOL",
            42500,
            source_ref_id=blanket.usage_report_id,
        )
        assert entry["cash_recognized_at"] is not None
