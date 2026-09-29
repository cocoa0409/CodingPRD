"""Unwinds that give back exactly what they took, and nothing else.

A distribution reversal is checked against the money identity: the gross pool is
conserved across the unwind and every member balance returns to zero because the
debit is read off the stored share rather than re-derived.  A file reversal is
checked against the year-to-date ledgers: two files reversed in the opposite
order to their loads walk back through the exact intermediate state and then to a
true zero, taking the leakage flag and the watchlist with them.
"""

import pytest

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import TIER_0
from test_helpers.fixtures import (
    build_priced_setup,
    create_distribution,
    distribute_distribution,
    lines_of_file,
    read_commitment,
    read_distribution,
    read_distributor_file,
    read_member,
    reverse_distributor_file,
    submit_distributor_file,
)
from test_helpers.test_users import (
    compliance_analyst_headers,
    finance_administrator_headers,
)


@pytest.fixture
def ledger_reversal_setup(api):
    """Two statements loaded in order, leaving the member flagged and watchlisted.

    D-A is fully accepted — 5000 on-contract units at 9500 plus 500 unmatched
    units at 6000 — and D-B lands `PARTIALLY_LOADED` with 1500 leakage units at
    10500 next to one rejected zero-quantity line.
    """
    setup = build_priced_setup(
        api,
        member_overrides={
            "item_master": [
                f.item_master_row("MI-1"),
                f.item_master_row("MI-9", "Unlisted suture kit"),
            ]
        },
    )
    file_a = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [
            f.purchase_line_row("MI-1", 5000, 9500, "2026-08-05"),
            f.purchase_line_row("MI-9", 500, 6000, "2026-08-10"),
        ],
        distributor_code="D-A",
    )
    file_b = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [
            f.purchase_line_row("MI-1", 1500, 10500, "2026-08-12"),
            f.purchase_line_row("MI-1", 0, 9500, "2026-08-20"),
        ],
        distributor_code="D-B",
    )
    setup.update({"file_a": file_a, "file_b": file_b})
    return setup


def _reverse_distribution(api, distribution_id, reason):
    return validate_success(
        api.reverse_distribution(
            distribution_id,
            f.reason_payload(reason),
            headers=finance_administrator_headers(),
        ),
        200,
    )


def _distributions_of(api, contract_id):
    data, _meta = validate_paginated(
        api.list_distributions(
            {"contract_id": contract_id, "limit": 100},
            headers=compliance_analyst_headers(),
        )
    )
    return data


class TestDistributionReversalConservesTheGrossPool:
    """58617 + 0 + 41583 becomes 0 + 100200 + 0, and the gross never moves."""

    def test_the_collected_pool_splits_by_weight_and_balances_to_the_gross(
        self, api, holdback_two_member_setup
    ):
        """PRD §3.9: "With a holdback ladder of one entry at a 0 minimum and 0 basis
        points and a second at a 100,000-cent minimum and 250 basis points, and a
        `member_share_bps` of 6000, a gross pool of 100,200 cents selects the
        250-basis-point rung, giving a `holdback_cents` of 2505, a `net_pool_cents` of
        97,695 and a `member_pool_cents` of 58,617."
        PRD §3.9: "Worked through: a `member_pool_cents` of 58,617 split between weights
        of 4,750,000 and 1,900,000, a total weight of 6,650,000, gives exact shares of
        41,869.28… and 16,747.71…; the floors are 41,869 and 16,747, summing to 58,616,
        one cent short; the larger fractional part is the second member's .71 against the
        first member's .28, so the remainder cent goes there and the final shares are
        41,869 and 16,748, summing to exactly 58,617."
        PRD §3.9: "`gpo_retained_cents` is `gross_pool_cents` minus
        `member_share_total_cents` minus `undistributed_cents`, which is exactly the
        holdback plus the non-member slice of the net pool."

        Design: Difficulty/compensating_invariant/distribution_reverse_conserves_gross_fee_cents
        """
        setup = holdback_two_member_setup

        settled = distribute_distribution(api, setup["distribution"]["id"])

        assert settled["basis"] == "COLLECTED"
        assert settled["gross_pool_cents"] == 100200
        assert settled["holdback_bps_applied"] == 250
        assert settled["holdback_cents"] == 2505
        assert settled["net_pool_cents"] == 97695
        assert settled["member_pool_cents"] == 58617
        assert settled["member_share_total_cents"] == 58617
        assert settled["undistributed_cents"] == 0
        assert settled["gpo_retained_cents"] == 41583
        a.assert_member_share(settled, setup["member_a"]["id"], 4750000, 41869)
        a.assert_member_share(settled, setup["member_b"]["id"], 1900000, 16748)
        a.assert_waterfall_conserved(settled)

    def test_the_reversal_zeroes_every_pool_and_parks_the_whole_gross_undistributed(
        self, api, holdback_two_member_setup
    ):
        """PRD §3.9: "Then `holdback_bps_applied`, `holdback_cents`, `net_pool_cents`,
        `member_pool_cents`, `member_share_total_cents` and `gpo_retained_cents` are all
        set to 0, `member_shares` is emptied, and `undistributed_cents` is set to
        `gross_pool_cents` — which keeps the conservation identity true on the reversed
        row, with the whole gross pool now sitting undistributed."
        PRD §3.9: "`accrued_fee_cents`, `collected_fee_cents`, `gross_pool_cents` and
        `basis` are left untouched as the record of what was settled."
        PRD §3.9: "`status` becomes `REVERSED` and the `version` increments by one."
        PRD §3.9: "A distribution in `DISTRIBUTED` status can be reversed, optionally
        carrying a `reason` that is stored as `reverse_note` and is null when omitted."

        Design: Difficulty/compensating_invariant/distribution_reverse_conserves_gross_fee_cents
        """
        setup = holdback_two_member_setup
        distributed = distribute_distribution(api, setup["distribution"]["id"])
        assert distributed["status"] == "DISTRIBUTED"

        _reverse_distribution(
            api,
            setup["distribution"]["id"],
            "Supplier clawed back the August remittance.",
        )

        reversed_row = read_distribution(api, setup["distribution"]["id"])
        assert reversed_row["status"] == "REVERSED"
        assert reversed_row["reverse_note"] == "Supplier clawed back the August remittance."
        assert reversed_row["accrued_fee_cents"] == 199500
        assert reversed_row["collected_fee_cents"] == 100200
        assert reversed_row["gross_pool_cents"] == 100200
        assert reversed_row["basis"] == "COLLECTED"
        assert reversed_row["member_shares"] == []
        assert reversed_row["member_share_total_cents"] == 0
        assert reversed_row["holdback_cents"] == 0
        assert reversed_row["net_pool_cents"] == 0
        assert reversed_row["member_pool_cents"] == 0
        assert reversed_row["gpo_retained_cents"] == 0
        assert reversed_row["undistributed_cents"] == 100200
        a.assert_waterfall_conserved(reversed_row)

    def test_each_member_is_debited_by_exactly_the_share_it_was_credited(
        self, api, holdback_two_member_setup
    ):
        """PRD §3.9: "Reversal debits each member listed in `member_shares` by exactly the
        `share_cents` recorded for that member, incrementing each member's `version` by
        one; the credits are read back off the stored array rather than re-derived, so a
        reversal returns precisely what was paid even if the underlying spend has since
        moved."
        PRD §3.9: "Every eligible member's `fee_credit_balance_cents` is then credited by
        that member's `share_cents`, incrementing each member's `version` by one, the
        distribution's `status` becomes `DISTRIBUTED`, and its `version` increments by
        one."

        Design: Difficulty/compensating_invariant/distribution_reverse_conserves_gross_fee_cents
        """
        setup = holdback_two_member_setup
        distribute_distribution(api, setup["distribution"]["id"])
        assert read_member(api, setup["member_a"]["id"])["fee_credit_balance_cents"] == 41869
        assert read_member(api, setup["member_b"]["id"])["fee_credit_balance_cents"] == 16748

        _reverse_distribution(
            api,
            setup["distribution"]["id"],
            "Supplier clawed back the August remittance.",
        )

        assert read_member(api, setup["member_a"]["id"])["fee_credit_balance_cents"] == 0
        assert read_member(api, setup["member_b"]["id"])["fee_credit_balance_cents"] == 0

    def test_the_released_period_re_accrues_the_identical_fee(
        self, api, holdback_two_member_setup
    ):
        """PRD §3.9: "No distribution for the same contract in any status other than
        `REVERSED` may already cover the identical `period_start` and `period_end` pair,
        else `ERR_DUPLICATE_DISTRIBUTION_PERIOD` — a reversed settlement releases its
        period so it can be settled again."
        PRD §3.9: "`accrued_fee_cents` is computed at the moment of creation and is never
        recomputed by any later transition."

        Design: Difficulty/compensating_invariant/distribution_reverse_conserves_gross_fee_cents
        """
        setup = holdback_two_member_setup
        assert setup["distribution"]["accrued_fee_cents"] == 199500
        distribute_distribution(api, setup["distribution"]["id"])
        _reverse_distribution(
            api,
            setup["distribution"]["id"],
            "Supplier clawed back the August remittance.",
        )

        restated = create_distribution(api, setup["contract"]["id"])

        assert restated["status"] == "ACCRUED"
        assert restated["accrued_fee_cents"] == 199500
        assert restated["collected_fee_cents"] == 0
        assert restated["gross_pool_cents"] == 0
        assert len(_distributions_of(api, setup["contract"]["id"])) == 2

    def test_unwinding_the_money_never_touches_the_spend_ledgers(
        self, api, holdback_two_member_setup
    ):
        """PRD §3.7: "**Hop 2 — the year-to-date ledgers**, caused by hop 1's
        classification writes."
        PRD §3.9: "The member pool is split among the contract's *eligible* commitments:
        those whose `election_status` is `ACTIVE`, whose `lop_status` is `COUNTERSIGNED`,
        whose `leakage_flag` is false, and whose `ytd_on_contract_spend_cents` is strictly
        greater than 0."

        Design: Difficulty/compensating_invariant/distribution_reverse_conserves_gross_fee_cents
        """
        setup = holdback_two_member_setup
        distribute_distribution(api, setup["distribution"]["id"])

        _reverse_distribution(
            api,
            setup["distribution"]["id"],
            "Supplier clawed back the August remittance.",
        )

        commitment_a = read_commitment(api, setup["commitment_a"]["id"])
        commitment_b = read_commitment(api, setup["commitment_b"]["id"])
        assert commitment_a["ytd_on_contract_spend_cents"] == 4750000
        assert commitment_a["ytd_measured_volume_units"] == 500
        assert commitment_b["ytd_on_contract_spend_cents"] == 1900000
        assert commitment_b["ytd_measured_volume_units"] == 200


class TestFileReversalConservesTheYearToDateLedgers:
    """47500000 / 66250000 / 5000 back to 47500000 / 50500000 / 5000, then to zero."""

    def test_both_loads_leave_the_member_flagged_and_watchlisted(
        self, api, ledger_reversal_setup
    ):
        """PRD §3.7: "**`VALIDATING → PARTIALLY_LOADED`** when `rejected_line_count` is
        greater than 0 and `accepted_line_count` is also greater than 0."
        PRD §3.7: "The server finds the commitment for this file's member-and-contract pair
        whose `election_status` is `ELECTED`, `ACTIVE` or `REQUAL_REVIEW`, and posts three
        running sums onto it: `ytd_on_contract_spend_cents` grows by the total
        `extended_cost_cents` of the file's `ON_CONTRACT` lines;
        `ytd_total_category_spend_cents` grows by the total `extended_cost_cents` of the
        file's `ON_CONTRACT`, `OFF_CONTRACT_LEAKAGE` and `UNMATCHED` lines together; and
        `ytd_measured_volume_units` grows by the total `contract_units` of the file's
        `ON_CONTRACT` lines."
        PRD §3.7: "If the recomputed `ytd_leakage_pct` is **strictly greater than** the
        contract's `leakage_alert_threshold_pct`, `leakage_flag` is set to true; a rate
        landing exactly on the threshold does not raise the flag."
        PRD §3.7: "The member's `watchlist_status` becomes `WATCHLIST` and that member's
        `version` increments by one."

        Design: Difficulty/compensating_invariant/file_reverse_conserves_ytd_spend_and_volume_ledgers
        """
        setup = ledger_reversal_setup
        assert setup["file_a"]["status"] == "LOADED"
        assert setup["file_b"]["status"] == "PARTIALLY_LOADED"

        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["ytd_on_contract_spend_cents"] == 47500000
        assert commitment["ytd_total_category_spend_cents"] == 66250000
        assert commitment["ytd_measured_volume_units"] == 5000
        a.assert_pct(commitment["ytd_leakage_pct"], 28.30)
        assert commitment["leakage_flag"] is True
        assert read_member(api, setup["member"]["id"])["watchlist_status"] == "WATCHLIST"

    def test_reversing_the_leakage_statement_walks_the_ledgers_back_one_load(
        self, api, ledger_reversal_setup
    ):
        """PRD §3.7: "Reversal unwinds a load completely."
        PRD §3.7: "First, the same commitment's `ytd_on_contract_spend_cents`,
        `ytd_total_category_spend_cents` and `ytd_measured_volume_units` are each
        decremented by **exactly the amounts this file added at load time** — not by a
        re-derivation from current data — and the commitment's `version` increments by
        one."

        Design: Difficulty/compensating_invariant/file_reverse_conserves_ytd_spend_and_volume_ledgers
        """
        setup = ledger_reversal_setup

        reverse_distributor_file(
            api, setup["file_b"]["id"], "Distributor withdrew the leakage statement."
        )

        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["ytd_on_contract_spend_cents"] == 47500000
        assert commitment["ytd_total_category_spend_cents"] == 50500000
        assert commitment["ytd_measured_volume_units"] == 5000

    def test_the_recomputed_rate_lowers_the_flag_and_un_watchlists_the_member(
        self, api, ledger_reversal_setup
    ):
        """PRD §3.7: "Second, caused by that decrement, `ytd_leakage_pct` is recomputed by
        the same formula as hop 3, and if the recomputed rate is less than or equal to the
        contract's `leakage_alert_threshold_pct` — including the case where the denominator
        has fallen back to 0 and the rate is therefore 0.00 — then `leakage_flag` is set to
        false."
        PRD §3.7: "Third, caused by that flag falling, the member's `watchlist_status`
        returns to `NONE` if and only if no commitment of that member still carries
        `leakage_flag` true, with a `version` increment on the member."

        Design: Difficulty/compensating_invariant/file_reverse_conserves_ytd_spend_and_volume_ledgers
        """
        setup = ledger_reversal_setup

        reverse_distributor_file(
            api, setup["file_b"]["id"], "Distributor withdrew the leakage statement."
        )

        commitment = read_commitment(api, setup["commitment"]["id"])
        a.assert_pct(commitment["ytd_leakage_pct"], 5.94)
        assert commitment["leakage_flag"] is False
        assert read_member(api, setup["member"]["id"])["watchlist_status"] == "NONE"

    def test_the_reversed_lines_are_unclassified_but_keep_their_reject_reason(
        self, api, ledger_reversal_setup
    ):
        """PRD §3.7: "Finally every purchase line of the reversed file has its
        `classification` reset to `UNCLASSIFIED`, its `contract_units` reset to 0 and its
        `matched_vendor_item_number` reset to null; `reject_reason` is left exactly as
        validation stamped it."
        PRD §3.7: "`status` becomes `REVERSED`, which is terminal, and the file's `version`
        increments by one."

        Design: Difficulty/compensating_invariant/file_reverse_conserves_ytd_spend_and_volume_ledgers
        """
        setup = ledger_reversal_setup

        reversed_file = reverse_distributor_file(
            api, setup["file_b"]["id"], "Distributor withdrew the leakage statement."
        )

        assert reversed_file["status"] == "REVERSED"
        lines = lines_of_file(api, setup["file_b"]["id"])
        assert len(lines) == 2
        for line in lines:
            assert line["classification"] == "UNCLASSIFIED"
            assert line["contract_units"] == 0
            assert line["matched_vendor_item_number"] is None
        rejected = a.line_by_item_and_quantity(lines, "MI-1", 0)
        assert rejected["reject_reason"] == "ZERO_QUANTITY"
        accepted = a.line_by_item_and_quantity(lines, "MI-1", 1500)
        assert accepted["reject_reason"] == "NONE"

    def test_reversing_both_statements_returns_the_ledgers_to_a_true_zero(
        self, api, ledger_reversal_setup
    ):
        """PRD §3.7: "First, the same commitment's `ytd_on_contract_spend_cents`,
        `ytd_total_category_spend_cents` and `ytd_measured_volume_units` are each
        decremented by **exactly the amounts this file added at load time** — not by a
        re-derivation from current data — and the commitment's `version` increments by
        one."
        PRD §3.7: "When `ytd_total_category_spend_cents` is 0 the recomputed value is 0.00
        rather than an error."

        Design: Difficulty/compensating_invariant/file_reverse_conserves_ytd_spend_and_volume_ledgers
        """
        setup = ledger_reversal_setup

        reverse_distributor_file(
            api, setup["file_b"]["id"], "Distributor withdrew the leakage statement."
        )
        reverse_distributor_file(
            api, setup["file_a"]["id"], "August statement restated in full."
        )

        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["ytd_on_contract_spend_cents"] == 0
        assert commitment["ytd_total_category_spend_cents"] == 0
        assert commitment["ytd_measured_volume_units"] == 0
        a.assert_pct(commitment["ytd_leakage_pct"], 0.00)
        assert commitment["leakage_flag"] is False
        assert read_member(api, setup["member"]["id"])["watchlist_status"] == "NONE"
        assert read_distributor_file(api, setup["file_a"]["id"])["status"] == "REVERSED"

    def test_the_fully_unwound_statement_leaves_two_unclassified_lines(
        self, api, ledger_reversal_setup
    ):
        """PRD §3.7: "Finally every purchase line of the reversed file has its
        `classification` reset to `UNCLASSIFIED`, its `contract_units` reset to 0 and its
        `matched_vendor_item_number` reset to null; `reject_reason` is left exactly as
        validation stamped it."
        PRD §3.7: "Purchase lines are immutable append-only records: no request ever
        creates, updates or deletes one directly, and they are discovered only through the
        purchase-line list — filterable by `distributor_file_id`, `classification` and
        `reject_reason` — or through a single-line read."

        Design: Difficulty/compensating_invariant/file_reverse_conserves_ytd_spend_and_volume_ledgers
        """
        setup = ledger_reversal_setup

        reverse_distributor_file(
            api, setup["file_a"]["id"], "August statement restated in full."
        )

        unclassified = lines_of_file(
            api, setup["file_a"]["id"], classification="UNCLASSIFIED"
        )
        assert len(unclassified) == 2
        for line in unclassified:
            assert line["contract_units"] == 0
            assert line["matched_vendor_item_number"] is None
            assert line["reject_reason"] == "NONE"

    def test_reversing_files_never_retiers_the_commitment(
        self, api, ledger_reversal_setup
    ):
        """PRD §3.8: "**Hop 2**, caused by hop 1. The commitment's
        `last_final_compliance_pct` is set to the final `compliance_pct`, its
        `current_tier_code` is overwritten with the measurement's `qualified_tier_code`,
        its `requalification_round` increments by one, and its `election_status` returns
        from `REQUAL_REVIEW` to `ACTIVE`, closing the requalification cycle."
        PRD §3.7: "Reversal unwinds a load completely."

        Design: Difficulty/compensating_invariant/file_reverse_conserves_ytd_spend_and_volume_ledgers
        """
        setup = ledger_reversal_setup

        reverse_distributor_file(
            api, setup["file_b"]["id"], "Distributor withdrew the leakage statement."
        )
        reverse_distributor_file(
            api, setup["file_a"]["id"], "August statement restated in full."
        )

        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["election_status"] == "ACTIVE"
        assert commitment["current_tier_code"] == TIER_0
        assert commitment["requalification_round"] == 0
