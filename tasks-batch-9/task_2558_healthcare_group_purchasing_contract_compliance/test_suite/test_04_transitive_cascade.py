"""Transitive cascades: each hop is caused by the writes of the hop before it.

Two chains are exercised here.  Finalizing a compliance measurement retiers a
commitment, and only a retier that actually moved the tier drags the live tier
price, which in turn drags the local exception for the same catalog item, which
in turn forces exactly one counter recompute on that item.  Loading a
distributor file classifies lines, which moves the year-to-date ledgers, which
recomputes the leakage rate, which — only when the rate crosses the contract's
threshold — raises the flag that watchlists the member.
"""

import pytest

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import TIER_0, TIER_2
from test_helpers.fixtures import (
    build_priced_setup,
    create_local_exception,
    finalize_measurement,
    lines_of_file,
    load_distributor_file,
    measure,
    open_measurement,
    open_requalification,
    read_activation,
    read_commitment,
    read_distributor_file,
    read_item,
    read_measurement,
    read_member,
    set_clock,
    submit_distributor_file,
)
from test_helpers.test_users import compliance_analyst_headers


@pytest.fixture
def retier_cascade_setup(api):
    """A PRELIMINARY measurement whose final figures will move the tier from TIER_0.

    Two live activations sit on the one (commitment, item) pair — a TIER_PRICE
    row and a LOCAL_EXCEPTION requesting 9600 — both windowed
    [2026-08-01, 2026-12-31], and the logical clock has been advanced to
    2026-09-02 so a replacement window can still open inside them.
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
    commitment_id = setup["commitment"]["id"]
    exception = create_local_exception(
        api, commitment_id, setup["member"]["id"], setup["item"]["id"], 9600
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
    open_requalification(api, commitment_id)
    measurement = open_measurement(api, commitment_id)
    preliminary = measure(api, measurement["id"])
    set_clock(api, "2026-09-02T00:00:00Z")
    setup.update(
        {
            "exception": exception,
            "file_a": file_a,
            "file_b": file_b,
            "measurement": measurement,
            "preliminary": preliminary,
        }
    )
    return setup


def _activations(api, **filters):
    params = dict(filters)
    params.setdefault("limit", 100)
    data, _meta = validate_paginated(
        api.list_price_activations(params, headers=compliance_analyst_headers())
    )
    return data


class TestRetierCascade:
    """finalize → retier → tier price → local exception → item counter."""

    def test_finalizing_recomputes_the_measurement_and_retiers_the_commitment(
        self, api, retier_cascade_setup
    ):
        """PRD §3.8: "**Hop 1.** Every money and volume field is recomputed under the
        final variant, `preliminary_compliance_pct` is preserved, `computed_variant`
        becomes `FINAL`, `qualified_tier_code` is derived from the final figures,
        `status` becomes `FINAL`, and the measurement's `version` increments by one."
        PRD §3.8: "**Hop 2**, caused by hop 1. The commitment's
        `last_final_compliance_pct` is set to the final `compliance_pct`, its
        `current_tier_code` is overwritten with the measurement's
        `qualified_tier_code`, its `requalification_round` increments by one, and its
        `election_status` returns from `REQUAL_REVIEW` to `ACTIVE`, closing the
        requalification cycle."

        Design: Difficulty/transitive_cascade/finalize_retier_supersedes_tier_row_then_local_exception_then_item_counter
        """
        setup = retier_cascade_setup
        assert setup["preliminary"]["qualified_tier_code"] == TIER_0
        assert read_commitment(api, setup["commitment"]["id"])["current_tier_code"] == TIER_0

        finalize_measurement(api, setup["measurement"]["id"])

        final = read_measurement(api, setup["measurement"]["id"])
        assert final["status"] == "FINAL"
        assert final["computed_variant"] == "FINAL"
        a.assert_pct(final["compliance_pct"], 94.06)
        assert final["measured_volume_units"] == 5000
        assert final["qualified_tier_code"] == TIER_2

        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["current_tier_code"] == TIER_2
        a.assert_pct(commitment["last_final_compliance_pct"], 94.06)
        assert commitment["requalification_round"] == 1
        assert commitment["election_status"] == "ACTIVE"

    def test_the_retier_supersedes_the_live_tier_price_and_mints_its_replacement(
        self, api, retier_cascade_setup
    ):
        """PRD §3.8: "**Hop 3**, caused by hop 2, and **only when
        `current_tier_code` actually changed**. Every price activation of this
        commitment whose `status` is `ACTIVE` and whose `activation_type` is
        `TIER_PRICE` moves to `SUPERSEDED`."
        PRD §3.8: "For each such row, if its `effective_to` is on or after the logical
        clock's current date, a replacement activation is minted: `origin`
        `REQUALIFICATION_CASCADE`, `activation_type` `TIER_PRICE`, `status` `ACTIVE`
        immediately, `effective_from` set to the logical clock's current date,
        `effective_to` copied from the superseded row, `tier_code_at_activation` set
        to the commitment's **new** `current_tier_code`, and `computed_price_cents` and
        `price_clamped` re-derived by the four-step derivation of §3.6 under that new
        tier."
        PRD §3.8: "The replacement's `replaces_activation_id` points at the superseded
        row and the superseded row's `superseded_by_activation_id` points at the
        replacement."

        Design: Difficulty/transitive_cascade/finalize_retier_supersedes_tier_row_then_local_exception_then_item_counter
        """
        setup = retier_cascade_setup
        tier_row_id = setup["activation"]["id"]

        finalize_measurement(api, setup["measurement"]["id"])

        superseded = read_activation(api, tier_row_id)
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_activation_id"] is not None

        replacements = _activations(api, replaces_activation_id=tier_row_id)
        assert len(replacements) == 1
        replacement = replacements[0]
        assert replacement["id"] == superseded["superseded_by_activation_id"]
        assert replacement["status"] == "ACTIVE"
        assert replacement["activation_type"] == "TIER_PRICE"
        assert replacement["origin"] == "REQUALIFICATION_CASCADE"
        assert replacement["tier_code_at_activation"] == TIER_2
        assert replacement["computed_price_cents"] == 8500
        assert replacement["price_clamped"] is False
        assert replacement["effective_from"] == "2026-09-02"
        assert replacement["effective_to"] == "2026-12-31"

    def test_the_superseded_tier_price_drags_the_local_exception_for_the_same_item(
        self, api, retier_cascade_setup
    ):
        """PRD §3.8: "**Hop 4**, caused by hop 3's supersede writes. For each
        commitment-and-catalog-item pair whose tier price was superseded in hop 3, an
        activation for that same pair whose `status` is `ACTIVE` and whose
        `activation_type` is `LOCAL_EXCEPTION` — if one exists — is also moved to
        `SUPERSEDED`."
        PRD §3.8: "If its `effective_to` is on or after the logical clock's current
        date, it too gets a replacement: `origin` `REQUALIFICATION_CASCADE`,
        `activation_type` `LOCAL_EXCEPTION`, `status` `ACTIVE`,
        `requested_price_cents` copied verbatim from the superseded row,
        `effective_from` set to the logical clock's current date, `effective_to`
        copied from the superseded row, `tier_code_at_activation` set to the
        commitment's new `current_tier_code`, and `computed_price_cents` and
        `price_clamped` re-derived under that new tier — which means the lesser-of
        ceiling in step 3 of the derivation moves, so a request that used to sit below
        the old tier price may now be ceilinged by the new one, or a request that used
        to be ceilinged may now stand."
        PRD §3.8: "A local exception is **never** re-derived on its own: it moves only
        because the tier price for the same catalog item moved first, which is what
        makes this cascade transitive rather than a fan-out."

        Design: Difficulty/transitive_cascade/finalize_retier_supersedes_tier_row_then_local_exception_then_item_counter
        """
        setup = retier_cascade_setup
        exception_id = setup["exception"]["id"]
        assert setup["exception"]["computed_price_cents"] == 9600

        finalize_measurement(api, setup["measurement"]["id"])

        superseded = read_activation(api, exception_id)
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_activation_id"] is not None

        replacements = _activations(api, replaces_activation_id=exception_id)
        assert len(replacements) == 1
        replacement = replacements[0]
        assert replacement["id"] == superseded["superseded_by_activation_id"]
        assert replacement["status"] == "ACTIVE"
        assert replacement["activation_type"] == "LOCAL_EXCEPTION"
        assert replacement["origin"] == "REQUALIFICATION_CASCADE"
        assert replacement["tier_code_at_activation"] == TIER_2
        assert replacement["requested_price_cents"] == 9600
        assert replacement["computed_price_cents"] == 8500
        assert replacement["effective_from"] == "2026-09-02"
        assert replacement["effective_to"] == "2026-12-31"

    def test_both_supersedes_produce_exactly_one_counter_recompute_on_the_item(
        self, api, retier_cascade_setup
    ):
        """PRD §3.8: "**Hop 5**, caused by the status writes of hops 3 and 4. For each
        catalog item touched anywhere in hops 3 and 4, `active_activation_count` is
        recomputed exactly once — once per item, not once per activation —
        incrementing that item's `version` by one."
        PRD §2.7: "When a single request supersedes four price activations belonging
        to two catalog items, each of those two items has `active_activation_count`
        recomputed exactly once and its `version` incremented by exactly one — not
        once per superseded activation."
        PRD §2.4: "`version`, an integer that starts at 1 on creation and increments
        by one on every accepted mutation of that row, including mutations the server
        performs on its own initiative as part of a cascade."

        Design: Difficulty/transitive_cascade/finalize_retier_supersedes_tier_row_then_local_exception_then_item_counter
        """
        setup = retier_cascade_setup
        item_id = setup["item"]["id"]
        before = read_item(api, item_id)
        assert before["active_activation_count"] == 2
        assert before["version"] == 3

        finalize_measurement(api, setup["measurement"]["id"])

        after = read_item(api, item_id)
        assert after["active_activation_count"] == 2
        assert after["version"] == 4

        rows = _activations(api, commitment_id=setup["commitment"]["id"])
        assert len(rows) == 4
        superseded = [row for row in rows if row["status"] == "SUPERSEDED"]
        cascaded = [row for row in rows if row["status"] == "ACTIVE"]
        assert len(superseded) == 2
        assert len(cascaded) == 2
        assert {row["origin"] for row in superseded} == {"REQUEST"}
        assert {row["origin"] for row in cascaded} == {"REQUALIFICATION_CASCADE"}


class TestLeakageWatchlistChain:
    """classification → ledgers → leakage rate → flag → watchlist."""

    def test_the_first_load_stops_at_the_ledger_hop_under_the_threshold(
        self, api, watchlist_chain_setup
    ):
        """PRD §3.7: "**Hop 2 — the year-to-date ledgers**, caused by hop 1's
        classification writes."
        PRD §3.7: "`ytd_on_contract_spend_cents` grows by the total
        `extended_cost_cents` of the file's `ON_CONTRACT` lines;
        `ytd_total_category_spend_cents` grows by the total `extended_cost_cents` of
        the file's `ON_CONTRACT`, `OFF_CONTRACT_LEAKAGE` and `UNMATCHED` lines
        together; and `ytd_measured_volume_units` grows by the total `contract_units`
        of the file's `ON_CONTRACT` lines."
        PRD §3.7: "If the recomputed `ytd_leakage_pct` is **strictly greater than** the
        contract's `leakage_alert_threshold_pct`, `leakage_flag` is set to true; a rate
        landing exactly on the threshold does not raise the flag."

        Design: Difficulty/transitive_cascade/file_load_classification_to_member_watchlist_chain
        """
        setup = watchlist_chain_setup
        assert setup["file_a"]["status"] == "LOADED"

        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["ytd_on_contract_spend_cents"] == 47500000
        assert commitment["ytd_total_category_spend_cents"] == 50500000
        assert commitment["ytd_measured_volume_units"] == 5000
        a.assert_pct(commitment["ytd_leakage_pct"], 5.94)
        assert commitment["leakage_flag"] is False
        assert read_member(api, setup["member"]["id"])["watchlist_status"] == "NONE"

    def test_only_the_accepted_line_of_a_partially_loaded_file_is_classified(
        self, api, watchlist_chain_setup
    ):
        """PRD §3.7: "**`VALIDATING → PARTIALLY_LOADED`** when `rejected_line_count`
        is greater than 0 and `accepted_line_count` is also greater than 0."
        PRD §3.7: "**Hop 1 — classification.** Each purchase line whose
        `reject_reason` is `NONE` is classified; rejected lines are skipped entirely
        and keep `classification` `UNCLASSIFIED`, `contract_units` 0 and
        `matched_vendor_item_number` null, and they never enter any sum anywhere in
        this system."
        PRD §3.7: "If several are eligible, they are ranked to pick one governing row:
        a `LOCAL_EXCEPTION` always outranks a `TIER_PRICE` for the same pair; among
        rows of the same `activation_type` the later `effective_from` wins; and a tie
        on `effective_from` is broken by the earlier `created_at`."
        PRD §3.7: "Against the governing row's `computed_price_cents`, the line
        classifies as `ON_CONTRACT` when its `unit_price_paid_cents` is less than or
        equal to that price, and as `OFF_CONTRACT_LEAKAGE` when it is greater."

        Design: Difficulty/transitive_cascade/file_load_classification_to_member_watchlist_chain
        """
        setup = watchlist_chain_setup
        assert setup["exception"]["computed_price_cents"] == 9600
        assert setup["file_b"]["accepted_line_count"] == 1
        assert setup["file_b"]["rejected_line_count"] == 1

        loaded = load_distributor_file(api, setup["file_b"]["id"])
        assert loaded["status"] == "PARTIALLY_LOADED"
        assert read_distributor_file(api, setup["file_b"]["id"])["status"] == "PARTIALLY_LOADED"

        lines = lines_of_file(api, setup["file_b"]["id"])
        assert len(lines) == 2
        a.assert_line_classification(
            a.line_by_item_and_quantity(lines, "MI-1", 1500),
            "OFF_CONTRACT_LEAKAGE",
            matched_vendor_item_number="V-1",
            contract_units=1500,
            reject_reason="NONE",
        )
        a.assert_line_classification(
            a.line_by_item_and_quantity(lines, "MI-1", 0),
            "UNCLASSIFIED",
            matched_vendor_item_number=None,
            contract_units=0,
            reject_reason="ZERO_QUANTITY",
        )

    def test_the_ledger_write_crosses_the_threshold_and_watchlists_the_member(
        self, api, watchlist_chain_setup
    ):
        """PRD §3.7: "**Hop 3 — the leakage rate**, caused by hop 2's ledger write.
        `ytd_leakage_pct` is recomputed as follows: subtract
        `ytd_on_contract_spend_cents` from `ytd_total_category_spend_cents`, multiply
        the difference by 100, divide by `ytd_total_category_spend_cents`, and round
        half up to two decimal places."
        PRD §3.7: "**Hop 4 — the watchlist**, caused by hop 3 raising the flag from
        false to true. The member's `watchlist_status` becomes `WATCHLIST` and that
        member's `version` increments by one."
        PRD §3.3: "`watchlist_status` takes the value `WATCHLIST` when the leakage
        cascade of §3.7 raises the leakage flag on any of that member's commitments,
        and returns to `NONE` only when no commitment of that member carries a raised
        flag."

        Design: Difficulty/transitive_cascade/file_load_classification_to_member_watchlist_chain
        """
        setup = watchlist_chain_setup

        load_distributor_file(api, setup["file_b"]["id"])

        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["ytd_on_contract_spend_cents"] == 47500000
        assert commitment["ytd_total_category_spend_cents"] == 66250000
        assert commitment["ytd_measured_volume_units"] == 5000
        a.assert_pct(commitment["ytd_leakage_pct"], 28.30)
        assert commitment["leakage_flag"] is True
        assert read_member(api, setup["member"]["id"])["watchlist_status"] == "WATCHLIST"
