"""Deep cascades read back immediately, and a settlement that agrees with itself.

Two chains run end to end in this file and both are inspected the instant they
finish: the file load, which walks line classification into the commitment's
year-to-date ledgers, into the leakage rate, into the member's watchlist; and
the distribution, which walks a per-line accrual into a holdback, a net pool, a
member pool, a per-member share and finally a credit on the member row. Every
figure is checked twice — once in the response of the request that wrote it and
once in the next request's plain read — because a settlement whose numbers are
recomputed on read, or posted by a later pass, is a different settlement.
"""

from typing import Any, Dict

import pytest

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import DEFAULT_CLOCK_INSTANT, FLAT_TIER_LADDER
from test_helpers.fixtures import (
    countersign_commitment,
    create_active_contract,
    create_active_tier_activation,
    create_approved_cross_reference,
    create_commitment,
    create_distribution,
    create_item,
    create_member,
    distribute_distribution,
    load_distributor_file,
    read_commitment,
    read_distribution,
    read_member,
    submit_distributor_file,
)

Json = Dict[str, Any]

ACCRUAL_HOLDBACK_LADDER = [f.holdback_row(0, 0), f.holdback_row(50000, 100)]
AUGUST_PURCHASE = [f.purchase_line_row("MI-1", 300, 10000, "2026-08-10")]


@pytest.fixture
def settlement_setup(api) -> Json:
    """An ACCRUAL contract, one countersigned member, and a validated August file.

    The logical clock is deliberately never set here, so the ``loaded_at`` stamp
    the load writes can only have come from the declared default instant.
    """
    contract = create_active_contract(
        api,
        contract_code="C-CS",
        requires_clinical_review=False,
        share_basis="ACCRUAL",
        admin_fee_bps=300,
        member_share_bps=6000,
        tiers=FLAT_TIER_LADDER,
        holdback_tiers=ACCRUAL_HOLDBACK_LADDER,
    )
    item = create_item(api, contract["id"])
    member = create_member(api)
    commitment = create_commitment(api, member["id"], contract["id"])
    countersign_commitment(api, commitment["id"], member["id"], signer_name="Dana Whitfield")
    create_approved_cross_reference(api, member["id"], item["id"])
    activation = create_active_tier_activation(
        api,
        commitment["id"],
        item["id"],
        effective_from="2026-08-01",
        effective_to="2026-08-31",
    )
    statement = submit_distributor_file(
        api,
        member["id"],
        contract["id"],
        AUGUST_PURCHASE,
        distributor_code="DIST-MW",
        period_start="2026-08-01",
        period_end="2026-09-01",
        stage="VALIDATED",
    )
    return {
        "contract": contract,
        "item": item,
        "member": member,
        "commitment": commitment,
        "activation": activation,
        "statement": statement,
    }


def _settle(api, setup: Json) -> Json:
    """Load the statement, open the settlement, and distribute it."""
    load_distributor_file(api, setup["statement"]["id"])
    opened = create_distribution(api, setup["contract"]["id"])
    return distribute_distribution(api, opened["id"])


class TestTheLoadCascadeIsCompleteOnTheVeryNextRead:
    """Four hops written by one request, and nothing left for a later pass."""

    def test_the_load_stamps_the_default_clock_instant(self, api, settlement_setup):
        """The activation is in force and the landing carries the untouched clock.

        PRD §2.4: "Before that capability is called for the first time, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time."
        PRD §2.4: "Every date-window comparison the server performs, the `loaded_at` stamp written when a distributor file is loaded, and the `effective_from` of any replacement price activation minted by a cascade all read this clock and nothing else."
        PRD §3.6: "Activation sets `status` to `ACTIVE`, increments the activation's own `version` by one, and recomputes the catalog item's `active_activation_count`, incrementing that item's `version` by one."
        PRD §3.7: "**`VALIDATING → LOADED`** when `rejected_line_count` is 0 and `accepted_line_count` is greater than 0. Every accepted line is classified, the ledger cascade runs in full, `status` becomes `LOADED`, and `loaded_at` is stamped from the logical clock."

        Design: Corner/consistency_model/distribute_response_and_member_read_agree_in_the_same_request
        """
        assert settlement_setup["activation"]["status"] == "ACTIVE"

        landed = load_distributor_file(api, settlement_setup["statement"]["id"])
        assert landed["status"] == "LOADED"
        assert landed["accepted_line_count"] == 1
        assert landed["rejected_line_count"] == 0
        a.assert_instant_equals(landed["loaded_at"], DEFAULT_CLOCK_INSTANT)

    def test_every_ledger_hop_is_readable_immediately(self, api, settlement_setup):
        """One load, and the ledgers, the rate and the watchlist are already settled.

        PRD §3.7: "Otherwise the server takes the catalog item the cross-reference points at, copies that item's `vendor_item_number` into the line's `matched_vendor_item_number` — deliberately a value copy rather than a foreign key, because distributor data is keyed by item numbers rather than by identifiers — and computes `contract_units` as the line's `quantity_units` multiplied by the cross-reference's `conversion_factor`, rounded half up to a whole number of units."
        PRD §3.7: "Against the governing row's `computed_price_cents`, the line classifies as `ON_CONTRACT` when its `unit_price_paid_cents` is less than or equal to that price, and as `OFF_CONTRACT_LEAKAGE` when it is greater."
        PRD §3.7: "The server finds the commitment for this file's member-and-contract pair whose `election_status` is `ELECTED`, `ACTIVE` or `REQUAL_REVIEW`, and posts three running sums onto it: `ytd_on_contract_spend_cents` grows by the total `extended_cost_cents` of the file's `ON_CONTRACT` lines; `ytd_total_category_spend_cents` grows by the total `extended_cost_cents` of the file's `ON_CONTRACT`, `OFF_CONTRACT_LEAKAGE` and `UNMATCHED` lines together; and `ytd_measured_volume_units` grows by the total `contract_units` of the file's `ON_CONTRACT` lines."
        PRD §3.7: "If the recomputed `ytd_leakage_pct` is **strictly greater than** the contract's `leakage_alert_threshold_pct`, `leakage_flag` is set to true; a rate landing exactly on the threshold does not raise the flag."
        PRD §3.7: "**Hop 4 — the watchlist**, caused by hop 3 raising the flag from false to true."
        PRD §3.3: "`watchlist_status` takes the value `WATCHLIST` when the leakage cascade of §3.7 raises the leakage flag on any of that member's commitments, and returns to `NONE` only when no commitment of that member carries a raised flag."

        Design: Corner/consistency_model/distribute_response_and_member_read_agree_in_the_same_request
        """
        load_distributor_file(api, settlement_setup["statement"]["id"])

        commitment = read_commitment(api, settlement_setup["commitment"]["id"])
        assert commitment["ytd_on_contract_spend_cents"] == 3000000
        assert commitment["ytd_total_category_spend_cents"] == 3000000
        assert commitment["ytd_measured_volume_units"] == 300
        a.assert_pct(commitment["ytd_leakage_pct"], 0.00)
        assert commitment["leakage_flag"] is False

        member = read_member(api, settlement_setup["member"]["id"])
        assert member["watchlist_status"] == "NONE"


class TestTheSettlementComputesItselfInsideItsOwnResponses:
    """Accrual at creation, the pool waterfall at distribution, nothing deferred."""

    def test_the_accrual_is_final_in_the_create_response(self, api, settlement_setup):
        """One on-contract line at 300 basis points, summed per line and frozen.

        PRD §3.9: "The new row is created in `ACCRUED` status with `collected_fee_cents` at 0, `basis` null, `holdback_bps_applied`, `holdback_cents`, `gross_pool_cents`, `net_pool_cents`, `member_pool_cents`, `member_share_total_cents`, `undistributed_cents` and `gpo_retained_cents` all at 0, `member_shares` an empty array, and `reverse_note` null."
        PRD §3.9: "`accrued_fee_cents` is computed at the moment of creation and is never recomputed by any later transition."
        PRD §3.9: "The eligible lines are purchase lines whose `reject_reason` is `NONE` and whose `classification` is `ON_CONTRACT`, belonging to distributor files of this contract — across every member, since the fee is the contract's, not a member's — whose own half-open period lies wholly inside the distribution's half-open period, and whose `status` is `LOADED`."
        PRD §3.9: "The lines are visited in order of `purchase_date` ascending and then `created_at` ascending, and each one's fee is `extended_cost_cents` multiplied by the contract's `admin_fee_bps`, divided by 10000, rounded half up to a whole cent."
        PRD §3.9: "`accrued_fee_cents` is then the exact integer sum of those already-rounded per-line fees."

        Design: Corner/consistency_model/distribute_response_and_member_read_agree_in_the_same_request
        """
        load_distributor_file(api, settlement_setup["statement"]["id"])
        opened = create_distribution(api, settlement_setup["contract"]["id"])

        assert opened["status"] == "ACCRUED"
        assert opened["accrued_fee_cents"] == 90000
        assert opened["collected_fee_cents"] == 0
        assert opened["basis"] is None
        assert opened["member_shares"] == []
        assert opened["reverse_note"] is None
        for zeroed in (
            "holdback_bps_applied",
            "holdback_cents",
            "gross_pool_cents",
            "net_pool_cents",
            "member_pool_cents",
            "member_share_total_cents",
            "undistributed_cents",
            "gpo_retained_cents",
        ):
            assert opened[zeroed] == 0, zeroed

        again = read_distribution(api, opened["id"])
        assert again["accrued_fee_cents"] == 90000
        assert again["status"] == "ACCRUED"

    def test_the_pool_waterfall_is_complete_in_the_distribute_response(
        self, api, settlement_setup
    ):
        """Holdback off the gross, member pool off the net, both already returned.

        PRD §3.9: "The `ACCRUED → DISTRIBUTED` route is legal only when `share_basis` is `ACCRUAL`, meaning the GPO shares what it billed and carries the collection risk itself; if `share_basis` is `COLLECTED`, distributing straight from `ACCRUED` returns `ERR_DISTRIBUTION_BASIS_NOT_COLLECTABLE`, since the cash has not been recorded yet."
        PRD §3.9: "Distributing pins `basis` to the contract's `share_basis` so the settlement records the rule it was computed under."
        PRD §3.9: "`gross_pool_cents` is `accrued_fee_cents` when `basis` is `ACCRUAL` and `collected_fee_cents` when `basis` is `COLLECTED`."
        PRD §3.9: "The server takes the ladder entry with the greatest `min_gross_pool_cents` that is less than or equal to `gross_pool_cents` and writes its `holdback_bps` into `holdback_bps_applied`; if no entry qualifies, `holdback_bps_applied` is 0."
        PRD §3.9: "Then `holdback_cents` is `gross_pool_cents` multiplied by `holdback_bps_applied`, divided by 10000, rounded half up; `net_pool_cents` is `gross_pool_cents` minus `holdback_cents`; and `member_pool_cents` is `net_pool_cents` multiplied by the contract's `member_share_bps`, divided by 10000, rounded half up."

        Design: Corner/consistency_model/distribute_response_and_member_read_agree_in_the_same_request
        """
        distributed = _settle(api, settlement_setup)

        assert distributed["status"] == "DISTRIBUTED"
        assert distributed["basis"] == "ACCRUAL"
        assert distributed["gross_pool_cents"] == 90000
        assert distributed["holdback_bps_applied"] == 100
        assert distributed["holdback_cents"] == 900
        assert distributed["net_pool_cents"] == 89100
        assert distributed["member_pool_cents"] == 53460

    def test_the_single_share_row_travels_with_the_conservation_identity(
        self, api, settlement_setup
    ):
        """The only eligible commitment takes the whole member pool, weight and all.

        PRD §3.9: "The member pool is split among the contract's *eligible* commitments: those whose `election_status` is `ACTIVE`, whose `lop_status` is `COUNTERSIGNED`, whose `leakage_flag` is false, and whose `ytd_on_contract_spend_cents` is strictly greater than 0."
        PRD §3.9: "The total weight is the sum of those commitments' `ytd_on_contract_spend_cents`."
        PRD §3.9: "Otherwise each eligible member's exact share is `member_pool_cents` multiplied by that commitment's `ytd_on_contract_spend_cents`, divided by the total weight."
        PRD §3.9: "Each `member_shares` entry records `member_id`, `commitment_id`, `weight_cents` — that commitment's `ytd_on_contract_spend_cents`, the weight actually used — and `share_cents`, the final allocated amount including any remainder cent."
        PRD §3.9: "`member_share_total_cents` is the sum of the `share_cents` values and, in this branch, equals `member_pool_cents` exactly, so `undistributed_cents` is 0."
        PRD §3.9: "`gpo_retained_cents` is `gross_pool_cents` minus `member_share_total_cents` minus `undistributed_cents`, which is exactly the holdback plus the non-member slice of the net pool."
        PRD §3.9: "The identity `member_share_total_cents` plus `undistributed_cents` plus `gpo_retained_cents` equals `gross_pool_cents` holds on every distributed row."

        Design: Corner/consistency_model/distribute_response_and_member_read_agree_in_the_same_request
        """
        distributed = _settle(api, settlement_setup)

        assert len(distributed["member_shares"]) == 1
        a.assert_member_share(
            distributed, settlement_setup["member"]["id"], 3000000, 53460
        )
        row = a.share_for_member(distributed, settlement_setup["member"]["id"])
        assert row["commitment_id"] == settlement_setup["commitment"]["id"]

        assert distributed["member_share_total_cents"] == 53460
        assert distributed["undistributed_cents"] == 0
        assert distributed["gpo_retained_cents"] == 36540
        a.assert_waterfall_conserved(distributed)


class TestTheWrittenNumbersAreTheStoredNumbers:
    """The credit posted on the member row, and the row re-read afterwards."""

    def test_the_member_credit_is_posted_for_the_next_request(self, api, settlement_setup):
        """A ledger that starts at zero and is already at the share when next read.

        PRD §3.3: "A new member is `ACTIVE`, with `watchlist_status` `NONE` and `fee_credit_balance_cents` zero."
        PRD §3.3: "`fee_credit_balance_cents` is the cumulative administrative-fee share credited to the member by the distribution waterfall of §3.9; it never goes below zero, and it is debited by an exact recorded amount when a distribution is reversed."
        PRD §3.9: "Every eligible member's `fee_credit_balance_cents` is then credited by that member's `share_cents`, incrementing each member's `version` by one, the distribution's `status` becomes `DISTRIBUTED`, and its `version` increments by one."

        Design: Corner/consistency_model/distribute_response_and_member_read_agree_in_the_same_request
        """
        assert settlement_setup["member"]["fee_credit_balance_cents"] == 0

        load_distributor_file(api, settlement_setup["statement"]["id"])
        before = read_member(api, settlement_setup["member"]["id"])
        assert before["fee_credit_balance_cents"] == 0

        opened = create_distribution(api, settlement_setup["contract"]["id"])
        distributed = distribute_distribution(api, opened["id"])

        after = read_member(api, settlement_setup["member"]["id"])
        assert after["fee_credit_balance_cents"] == 53460
        assert after["fee_credit_balance_cents"] == distributed["member_shares"][0]["share_cents"]
        a.assert_version_bump(after, before["version"])

    def test_the_re_read_reports_exactly_what_the_write_returned(self, api, settlement_setup):
        """Storage, not a recompute on read: every settled figure comes back identical.

        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.9: "`accrued_fee_cents` is computed at the moment of creation and is never recomputed by any later transition."
        PRD §3.9: "Once set, it is the single figure every later step and the conservation identity refer to; nothing downstream re-derives it from the accrual or the collection."
        PRD §3.9: "The identity `member_share_total_cents` plus `undistributed_cents` plus `gpo_retained_cents` equals `gross_pool_cents` holds on every distributed row."

        Design: Corner/consistency_model/distribute_response_and_member_read_agree_in_the_same_request
        """
        distributed = _settle(api, settlement_setup)
        again = read_distribution(api, distributed["id"])

        assert again["status"] == "DISTRIBUTED"
        assert again["basis"] == distributed["basis"]
        assert again["version"] == distributed["version"]
        for field in (
            "accrued_fee_cents",
            "collected_fee_cents",
            "gross_pool_cents",
            "holdback_bps_applied",
            "holdback_cents",
            "net_pool_cents",
            "member_pool_cents",
            "member_share_total_cents",
            "undistributed_cents",
            "gpo_retained_cents",
        ):
            assert again[field] == distributed[field], field
        assert again["member_shares"] == distributed["member_shares"]
        a.assert_waterfall_conserved(again)
        assert again["member_pool_cents"] == 53460
        assert again["gpo_retained_cents"] == 36540
