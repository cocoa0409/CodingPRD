"""The arithmetic, and — more often the point — which rows the arithmetic reads.

A half-cent that must round away from even, a floor that outranks the discount
it was applied to, three classifications produced by one load, a closed pricing
window whose endpoints are inside it, two compliance bases that admit different
file statuses, a two-axis tier ladder that falls back rather than interpolates,
three evidence weights applied to unrounded products, a fee accrued per line,
and a member pool that skips the members who bought badly or not at all.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import (
    FLAT_TIER_LADDER,
    FULL_TIER_LADDER,
    HOLDBACK_FLAT,
    TIER_0,
    TIER_1,
    TIER_2,
)
from test_helpers.fixtures import (
    build_priced_setup,
    build_second_member,
    create_contract,
    create_distribution,
    create_evidence_review,
    create_item,
    create_tier_activation,
    distribute_distribution,
    lines_of_file,
    load_distributor_file,
    measure,
    open_measurement,
    read_commitment,
    read_contract,
    read_evidence_review,
    read_member,
    set_clock,
    submit_distributor_file,
)
from test_helpers.test_users import (
    CLINICAL_REVIEWER_1,
    clinical_reviewer_headers,
)


@pytest.fixture
def two_items_at_the_rounding_boundary(api):
    """One base price of 10010 on the 1500-bps rung, over a low floor and a high one."""
    setup = build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-PRC",
            "tiers": [dict(row) for row in FULL_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
        item_overrides={
            "vendor_item_number": "V-1",
            "base_price_cents": 10010,
            "floor_price_cents": 8000,
        },
        member_overrides={"member_code": "M-PRC"},
        elected_tier_code=TIER_2,
        committed_volume_units=5000,
        with_xref=False,
        with_activation=False,
    )
    setup["item_high_floor"] = create_item(
        api,
        setup["contract"]["id"],
        vendor_item_number="V-2",
        item_description="Mesh graft",
        base_price_cents=10010,
        floor_price_cents=8600,
    )
    return setup


class TestTheHalfCentAndTheFloorOnTwoSiblingItems:
    """Identical arithmetic, two items: one rounds up, the other is clamped."""

    def test_the_activation_pins_the_tier_the_member_actually_holds(
        self, api, two_items_at_the_rounding_boundary
    ):
        """PRD §3.4: "It sets `current_tier_code` to the commitment's `elected_tier_code`,
        which is the first moment the member has a tier actually in force rather than merely
        elected."
        PRD §3.6: "The server then pins `tier_code_at_activation`: the commitment's
        `current_tier_code` if it has one, or the contract's `default_tier_code` when
        `current_tier_code` is still null — which is the case for any commitment whose letter
        has not yet been countersigned."

        Design: Corner/calculations/tier_price_half_up_rounding_and_floor_clamp_on_two_items
        """
        setup = two_items_at_the_rounding_boundary
        assert setup["commitment"]["current_tier_code"] == TIER_2

        activation = create_tier_activation(
            api, setup["commitment"]["id"], setup["item"]["id"]
        )

        assert activation["tier_code_at_activation"] == TIER_2

    def test_eight_thousand_five_hundred_and_eight_point_five_rounds_up(
        self, api, two_items_at_the_rounding_boundary
    ):
        """PRD §3.6: "Take 10000 basis points, subtract the tier's `discount_bps`, multiply the
        base price by that difference, divide by 10000, and round the result half up to a whole
        number of cents."
        PRD §3.6: "Worked over a `base_price_cents` of 10000 against a ladder whose rungs carry
        0, 800 and 1500 basis points of discount, the tier prices are 10000, 9200 and 8500
        cents respectively; over a `base_price_cents` of 10010 at 1500 basis points the exact
        result is 8508.5 cents, which rounds half up to 8509."
        PRD §3.6: "The rounding boundary is fixed and singular: the only rounding in this
        derivation happens at step 2."

        Design: Corner/calculations/tier_price_half_up_rounding_and_floor_clamp_on_two_items
        """
        setup = two_items_at_the_rounding_boundary

        activation = create_tier_activation(
            api, setup["commitment"]["id"], setup["item"]["id"]
        )

        assert activation["computed_price_cents"] == 8509
        assert activation["computed_price_cents"] != 8508
        assert activation["price_clamped"] is False

    def test_the_high_floor_overrides_the_same_discounted_candidate(
        self, api, two_items_at_the_rounding_boundary
    ):
        """PRD §3.6: "If the candidate price from step 3 is strictly below the item's
        `floor_price_cents`, then `computed_price_cents` becomes the floor price and
        `price_clamped` is set to true."
        PRD §3.6: "Otherwise `computed_price_cents` is the candidate price and `price_clamped`
        is false."
        PRD §3.6: "The floor outranks both the tier discount and the local exception."

        Design: Corner/calculations/tier_price_half_up_rounding_and_floor_clamp_on_two_items
        """
        setup = two_items_at_the_rounding_boundary

        activation = create_tier_activation(
            api, setup["commitment"]["id"], setup["item_high_floor"]["id"]
        )

        assert activation["tier_code_at_activation"] == TIER_2
        assert activation["computed_price_cents"] == 8600
        assert activation["price_clamped"] is True


@pytest.fixture
def three_way_classification_load(api):
    """One load over a 10000-cent governing price: at it, above it, and unmapped."""
    setup = build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-CLS",
            "tiers": [dict(row) for row in FLAT_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
        item_overrides={"base_price_cents": 10000, "floor_price_cents": 8000},
        member_overrides={
            "member_code": "M-CLS",
            "item_master": [
                f.item_master_row("MI-1"),
                f.item_master_row("MI-2", description="Mesh graft"),
            ],
        },
        match_type="MANUAL",
        conversion_factor=1.5,
    )
    validated = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [
            f.purchase_line_row("MI-1", 3, 10000, "2026-08-05"),
            f.purchase_line_row("MI-1", 1, 10001, "2026-08-06"),
            f.purchase_line_row("MI-2", 4, 500, "2026-08-07"),
        ],
        stage="VALIDATED",
    )
    setup["validated"] = validated
    setup["statement"] = load_distributor_file(api, validated["id"])
    return setup


@pytest.fixture
def eleven_day_pricing_window_load(api):
    """A price live only over [2026-08-10, 2026-08-20], and four purchases around it."""
    setup = build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-WIN",
            "tiers": [dict(row) for row in FLAT_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
        item_overrides={"base_price_cents": 10000, "floor_price_cents": 8000},
        member_overrides={"member_code": "M-WIN"},
        activation_from="2026-08-10",
        activation_to="2026-08-20",
    )
    setup["statement"] = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [
            f.purchase_line_row("MI-1", 1, 9000, "2026-08-05"),
            f.purchase_line_row("MI-1", 1, 9000, "2026-08-10"),
            f.purchase_line_row("MI-1", 1, 9000, "2026-08-20"),
            f.purchase_line_row("MI-1", 1, 9000, "2026-08-21"),
        ],
        stage="LOADED",
    )
    return setup


def _dates_of(lines):
    return sorted(line["purchase_date"] for line in lines)


class TestOneLoadProducesAllThreeClassifications:
    """At the price, one cent over it, and never mapped to the catalog at all."""

    def test_the_statement_validated_clean_and_loaded_in_full(
        self, api, three_way_classification_load
    ):
        """PRD §3.7: "**`VALIDATING → LOADED`** when `rejected_line_count` is 0 and
        `accepted_line_count` is greater than 0."
        PRD §3.7: "Every accepted line is classified, the ledger cascade runs in full, `status`
        becomes `LOADED`, and `loaded_at` is stamped from the logical clock."

        Design: Corner/calculations/classification_three_way_split_and_conversion_factor_rounding
        """
        setup = three_way_classification_load

        assert setup["activation"]["computed_price_cents"] == 10000
        assert setup["validated"]["rejected_line_count"] == 0
        assert setup["validated"]["accepted_line_count"] == 3
        assert setup["statement"]["status"] == "LOADED"

    def test_the_comparison_is_inclusive_at_the_governing_price(
        self, api, three_way_classification_load
    ):
        """PRD §3.7: "Against the governing row's `computed_price_cents`, the line classifies as
        `ON_CONTRACT` when its `unit_price_paid_cents` is less than or equal to that price, and
        as `OFF_CONTRACT_LEAKAGE` when it is greater."
        PRD §3.7: "The comparison is an integer cent comparison and it is **inclusive at
        equality**: paying exactly the computed price is on contract, paying less than it is
        still on contract because the member merely beat the ceiling, and paying one cent more
        is leakage."

        Design: Corner/calculations/classification_three_way_split_and_conversion_factor_rounding
        """
        setup = three_way_classification_load
        lines = lines_of_file(api, setup["statement"]["id"])
        assert len(lines) == 3

        at_the_price = a.line_by_item_and_quantity(lines, "MI-1", 3)
        one_cent_over = a.line_by_item_and_quantity(lines, "MI-1", 1)

        a.assert_line_classification(
            at_the_price, "ON_CONTRACT", matched_vendor_item_number="V-1", contract_units=5
        )
        a.assert_line_classification(
            one_cent_over,
            "OFF_CONTRACT_LEAKAGE",
            matched_vendor_item_number="V-1",
            contract_units=2,
        )

    def test_the_conversion_factor_rounds_half_up_and_the_unmapped_line_stays_empty(
        self, api, three_way_classification_load
    ):
        """PRD §3.7: "Otherwise the server takes the catalog item the cross-reference points at,
        copies that item's `vendor_item_number` into the line's `matched_vendor_item_number` —
        deliberately a value copy rather than a foreign key, because distributor data is keyed
        by item numbers rather than by identifiers — and computes `contract_units` as the
        line's `quantity_units` multiplied by the cross-reference's `conversion_factor`,
        rounded half up to a whole number of units."
        PRD §3.7: "If no such cross-reference exists, the line's `classification` becomes
        `UNMATCHED`, `matched_vendor_item_number` stays null, `contract_units` stays 0, and the
        line is finished."

        Design: Corner/calculations/classification_three_way_split_and_conversion_factor_rounding
        """
        setup = three_way_classification_load
        lines = lines_of_file(api, setup["statement"]["id"])

        unmapped = a.line_by_item_and_quantity(lines, "MI-2", 4)

        a.assert_line_classification(
            unmapped, "UNMATCHED", matched_vendor_item_number=None, contract_units=0
        )
        assert unmapped["extended_cost_cents"] == 2000
        assert a.line_by_item_and_quantity(lines, "MI-1", 3)["contract_units"] == 5
        assert a.line_by_item_and_quantity(lines, "MI-1", 1)["contract_units"] == 2

    def test_unmatched_spend_enters_the_denominator_but_not_the_volume(
        self, api, three_way_classification_load
    ):
        """PRD §3.7: "The server finds the commitment for this file's member-and-contract pair
        whose `election_status` is `ELECTED`, `ACTIVE` or `REQUAL_REVIEW`, and posts three
        running sums onto it: `ytd_on_contract_spend_cents` grows by the total
        `extended_cost_cents` of the file's `ON_CONTRACT` lines; `ytd_total_category_spend_cents`
        grows by the total `extended_cost_cents` of the file's `ON_CONTRACT`,
        `OFF_CONTRACT_LEAKAGE` and `UNMATCHED` lines together; and `ytd_measured_volume_units`
        grows by the total `contract_units` of the file's `ON_CONTRACT` lines."
        PRD §3.7: "`ytd_leakage_pct` is recomputed as follows: subtract
        `ytd_on_contract_spend_cents` from `ytd_total_category_spend_cents`, multiply the
        difference by 100, divide by `ytd_total_category_spend_cents`, and round half up to two
        decimal places."
        PRD §3.7: "If the recomputed `ytd_leakage_pct` is **strictly greater than** the
        contract's `leakage_alert_threshold_pct`, `leakage_flag` is set to true; a rate landing
        exactly on the threshold does not raise the flag."

        Design: Corner/calculations/classification_three_way_split_and_conversion_factor_rounding
        """
        setup = three_way_classification_load

        commitment = read_commitment(api, setup["commitment"]["id"])

        assert commitment["ytd_on_contract_spend_cents"] == 30000
        assert commitment["ytd_total_category_spend_cents"] == 42001
        assert commitment["ytd_measured_volume_units"] == 5
        a.assert_pct(commitment["ytd_leakage_pct"], 28.57)
        assert commitment["leakage_flag"] is True


class TestBothEndsOfThePricingWindowAreInside:
    """The window is closed, so 08-10 and 08-20 price; 08-05 and 08-21 find nothing."""

    def test_the_two_endpoints_are_on_contract(self, api, eleven_day_pricing_window_load):
        """PRD §3.7: "The server then asks which activation governs the line."
        PRD §3.7: "Only activations in `ACTIVE` status count, and only those belonging to the
        commitment for this member-and-contract pair, naming this catalog item, and whose
        closed window contains the line's `purchase_date` — that is, `effective_from` on or
        before the purchase date and `effective_to` on or after it."

        Design: Corner/calculations/classification_outside_every_active_window_is_leakage
        """
        setup = eleven_day_pricing_window_load
        assert setup["statement"]["status"] == "LOADED"

        on_contract = lines_of_file(api, setup["statement"]["id"], classification="ON_CONTRACT")

        assert _dates_of(on_contract) == ["2026-08-10", "2026-08-20"]
        for line in on_contract:
            a.assert_line_classification(
                line, "ON_CONTRACT", matched_vendor_item_number="V-1", contract_units=1
            )

    def test_a_purchase_outside_every_window_is_leakage_though_it_matched(
        self, api, eleven_day_pricing_window_load
    ):
        """PRD §3.7: "If no eligible activation exists, the line's `classification` becomes
        `OFF_CONTRACT_LEAKAGE`, even though `contract_units` and `matched_vendor_item_number`
        have already been written."
        PRD §3.7: "Purchase lines are immutable append-only records: no request ever creates,
        updates or deletes one directly, and they are discovered only through the purchase-line
        list — filterable by `distributor_file_id`, `classification` and `reject_reason` — or
        through a single-line read."

        Design: Corner/calculations/classification_outside_every_active_window_is_leakage
        """
        setup = eleven_day_pricing_window_load

        leaked = lines_of_file(
            api, setup["statement"]["id"], classification="OFF_CONTRACT_LEAKAGE"
        )
        unmatched = lines_of_file(api, setup["statement"]["id"], classification="UNMATCHED")

        assert _dates_of(leaked) == ["2026-08-05", "2026-08-21"]
        for line in leaked:
            a.assert_line_classification(
                line,
                "OFF_CONTRACT_LEAKAGE",
                matched_vendor_item_number="V-1",
                contract_units=1,
            )
        assert unmatched == []

    def test_the_ledgers_count_only_the_two_priced_purchases(
        self, api, eleven_day_pricing_window_load
    ):
        """PRD §3.7: "**Hop 2 — the year-to-date ledgers**, caused by hop 1's classification
        writes."
        PRD §3.7: "The commitment's `version` increments by one when it is posted to."

        Design: Corner/calculations/classification_outside_every_active_window_is_leakage
        """
        setup = eleven_day_pricing_window_load

        commitment = read_commitment(api, setup["commitment"]["id"])

        assert commitment["ytd_on_contract_spend_cents"] == 18000
        assert commitment["ytd_total_category_spend_cents"] == 36000
        assert commitment["ytd_measured_volume_units"] == 2
        assert commitment["version"] > setup["commitment"]["version"]


@pytest.fixture
def a_reversed_file_and_an_unvalidated_one(api):
    """Thirty thousand cents of spend, all of it in files no compliance variant admits."""
    setup = build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-FLT",
            "tiers": [dict(row) for row in FLAT_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
        item_overrides={"base_price_cents": 10000, "floor_price_cents": 8000},
        member_overrides={"member_code": "M-FLT"},
    )
    setup["reversed_file"] = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [f.purchase_line_row("MI-1", 3, 10000, "2026-08-05")],
        stage="REVERSED",
    )
    setup["received_file"] = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [f.purchase_line_row("MI-1", 7, 10000, "2026-08-09")],
        distributor_code="D-B",
        stage="RECEIVED",
    )
    setup["commitment_before"] = read_commitment(api, setup["commitment"]["id"])
    setup["measurement"] = open_measurement(api, setup["commitment"]["id"])
    return setup


@pytest.fixture
def ninety_five_percent_on_three_thousand_units(api):
    """Compliance five points clear of the top rung, on three fifths of its volume floor."""
    setup = build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-RQF",
            "tiers": [dict(row) for row in FULL_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
        item_overrides={"base_price_cents": 10000, "floor_price_cents": 8000},
        member_overrides={"member_code": "M-RQF"},
    )
    setup["statement"] = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [
            f.purchase_line_row("MI-1", 3000, 9500, "2026-08-05"),
            f.purchase_line_row("MI-1", 100, 15000, "2026-08-06"),
        ],
        stage="LOADED",
    )
    setup["commitment_before"] = read_commitment(api, setup["commitment"]["id"])
    setup["measurement"] = open_measurement(api, setup["commitment"]["id"])
    return setup


class TestTheComplianceBasisAdmitsNeitherFile:
    """Reversed spend does not resurface, and an unvalidated statement never counted.
    """

    def test_the_reverse_already_unwound_what_the_load_posted(
        self, api, a_reversed_file_and_an_unvalidated_one
    ):
        """PRD §3.7: "First, the same commitment's `ytd_on_contract_spend_cents`,
        `ytd_total_category_spend_cents` and `ytd_measured_volume_units` are each decremented by
        **exactly the amounts this file added at load time** — not by a re-derivation from
        current data — and the commitment's `version` increments by one."
        PRD §3.7: "An accepted submission creates the file in `RECEIVED` status and turns each
        entry of `lines` into exactly one **purchase line**, each carrying the file's identifier
        as `distributor_file_id`, the submitted `member_item_number`, `quantity_units`,
        `unit_price_paid_cents` and `purchase_date`, an `extended_cost_cents` computed
        immediately as `quantity_units` multiplied by `unit_price_paid_cents`, a `classification`
        of `UNCLASSIFIED`, a `reject_reason` of `NONE`, `contract_units` of 0, and
        `matched_vendor_item_number` null."

        Design: Corner/calculations/compliance_measure_excludes_reversed_and_unvalidated_files
        """
        setup = a_reversed_file_and_an_unvalidated_one

        assert setup["reversed_file"]["status"] == "REVERSED"
        assert setup["received_file"]["status"] == "RECEIVED"
        assert setup["commitment_before"]["ytd_on_contract_spend_cents"] == 0
        assert setup["commitment_before"]["ytd_total_category_spend_cents"] == 0
        assert setup["commitment_before"]["ytd_measured_volume_units"] == 0

    def test_the_measure_lands_on_the_empty_basis_branch(
        self, api, a_reversed_file_and_an_unvalidated_one
    ):
        """PRD §3.8: "The server assembles the eligible distributor files: files belonging to the
        member-and-contract pair of the measurement's commitment, whose own half-open period
        lies wholly inside the measurement's half-open period, and whose `status` is in the
        variant's admitted set."
        PRD §3.8: "Files still in `RECEIVED` or `VALIDATING`, and files in `REVERSED`, are
        excluded by both variants."
        PRD §3.8: "When `total_category_spend_cents` comes out at 0, `compliance_pct` is 0.00
        and `basis_empty` is set to true; otherwise `compliance_pct` is
        `on_contract_spend_cents` multiplied by 100, divided by `total_category_spend_cents`,
        rounded half up to two decimal places, and `basis_empty` is false."
        PRD §3.8: "If no entry is eligible, `qualified_tier_code` falls back to the contract's
        `default_tier_code`."

        Design: Corner/calculations/compliance_measure_excludes_reversed_and_unvalidated_files
        """
        setup = a_reversed_file_and_an_unvalidated_one

        measured = measure(api, setup["measurement"]["id"])

        assert measured["on_contract_spend_cents"] == 0
        assert measured["leakage_spend_cents"] == 0
        assert measured["unmatched_spend_cents"] == 0
        assert measured["total_category_spend_cents"] == 0
        assert measured["measured_volume_units"] == 0
        a.assert_pct(measured["compliance_pct"], 0.00)
        assert measured["basis_empty"] is True
        assert measured["qualified_tier_code"] == TIER_0
        assert measured["computed_variant"] == "PRELIMINARY"

    def test_the_commitment_row_is_untouched_apart_from_the_open(
        self, api, a_reversed_file_and_an_unvalidated_one
    ):
        """PRD §3.8: "Crucially, **no commitment field moves**: a preliminary measurement never
        retiers anybody."
        PRD §3.8: "The new row is created in `DRAFT` with every money and volume field at 0,
        `compliance_pct` at 0.00, `preliminary_compliance_pct` null, `qualified_tier_code` null,
        `basis_empty` false, and `computed_variant` null; the parent commitment's `version`
        increments by one."

        Design: Corner/calculations/compliance_measure_excludes_reversed_and_unvalidated_files
        """
        setup = a_reversed_file_and_an_unvalidated_one
        before = read_commitment(api, setup["commitment"]["id"])

        measure(api, setup["measurement"]["id"])

        after = read_commitment(api, setup["commitment"]["id"])
        a.assert_version_unchanged(after, before["version"])
        a.assert_fields_unchanged(
            before,
            after,
            "election_status",
            "current_tier_code",
            "requalification_round",
            "last_final_compliance_pct",
            "ytd_on_contract_spend_cents",
            "ytd_total_category_spend_cents",
            "ytd_measured_volume_units",
            "ytd_leakage_pct",
            "leakage_flag",
        )
        assert before["version"] == setup["commitment_before"]["version"] + 1


class TestTheTierLadderFallsBackRatherThanInterpolates:
    """Compliance clears the top rung; volume does not, and no tier is invented between.
    """

    def test_the_load_left_the_member_five_percent_leaked_and_unflagged(
        self, api, ninety_five_percent_on_three_thousand_units
    ):
        """PRD §3.7: "When `ytd_total_category_spend_cents` is 0 the recomputed value is 0.00
        rather than an error."
        PRD §3.7: "With the default threshold of 15.00, a member whose leakage stands at exactly
        15.00 percent is not flagged and one at 15.01 percent is."

        Design: Corner/calculations/requalification_falls_back_when_only_the_volume_axis_misses
        """
        setup = ninety_five_percent_on_three_thousand_units

        assert setup["statement"]["status"] == "LOADED"
        a.assert_pct(setup["commitment_before"]["ytd_leakage_pct"], 5.00)
        assert setup["commitment_before"]["leakage_flag"] is False
        assert setup["commitment_before"]["ytd_on_contract_spend_cents"] == 28500000
        assert setup["commitment_before"]["ytd_measured_volume_units"] == 3000

    def test_the_percentage_is_computed_once_from_the_integer_sums(
        self, api, ninety_five_percent_on_three_thousand_units
    ):
        """PRD §3.8: "From those files it takes every purchase line whose `reject_reason` is
        `NONE` and computes four sums: `on_contract_spend_cents` is the total
        `extended_cost_cents` of lines classified `ON_CONTRACT`; `leakage_spend_cents` is the
        total `extended_cost_cents` of lines classified `OFF_CONTRACT_LEAKAGE`;
        `unmatched_spend_cents` is the total `extended_cost_cents` of lines classified
        `UNMATCHED`; and `measured_volume_units` is the total `contract_units` of lines
        classified `ON_CONTRACT`."
        PRD §3.8: "All the sums are exact integer cents and the percentage is computed **once**
        from the unrounded integer sums — never by averaging per-file percentages."
        PRD §3.8: "It **excludes** `unmatched_spend_cents` from the denominator, on the reasoning
        that an unmatched line has not yet been proven to belong to the contract's category and
        charging it against the member early would understate compliance."

        Design: Corner/calculations/requalification_falls_back_when_only_the_volume_axis_misses
        """
        setup = ninety_five_percent_on_three_thousand_units

        measured = measure(api, setup["measurement"]["id"])

        assert measured["on_contract_spend_cents"] == 28500000
        assert measured["leakage_spend_cents"] == 1500000
        assert measured["unmatched_spend_cents"] == 0
        assert measured["total_category_spend_cents"] == 30000000
        assert measured["measured_volume_units"] == 3000
        a.assert_pct(measured["compliance_pct"], 95.00)
        assert measured["basis_empty"] is False

    def test_the_volume_axis_alone_costs_the_member_the_top_rung(
        self, api, ninety_five_percent_on_three_thousand_units
    ):
        """PRD §3.8: "A ladder entry is *eligible* when the measured compliance percentage is at
        least that entry's `min_compliance_pct` **and** the measured volume is at least that
        entry's `min_committed_volume_units`."
        PRD §3.8: "Both comparisons are inclusive, so landing exactly on a threshold qualifies;
        compliance is compared at two decimal places against a two-decimal minimum, and volume
        is an integer comparison."
        PRD §3.8: "Otherwise the eligible entries are ordered by `discount_bps` descending, then
        by `min_committed_volume_units` descending, then by `tier_code` ascending, and the first
        entry's `tier_code` is the answer."

        Design: Corner/calculations/requalification_falls_back_when_only_the_volume_axis_misses
        """
        setup = ninety_five_percent_on_three_thousand_units

        measured = measure(api, setup["measurement"]["id"])

        assert measured["qualified_tier_code"] == TIER_1
        assert measured["qualified_tier_code"] != TIER_2
        assert measured["qualified_tier_code"] != TIER_0

    def test_the_preliminary_reading_retiers_nobody(
        self, api, ninety_five_percent_on_three_thousand_units
    ):
        """PRD §3.8: "The measure action drives `DRAFT → PRELIMINARY` — any other starting status
        returns `ERR_INVALID_MEASUREMENT_STATE` — writes the result to both `compliance_pct` and
        `preliminary_compliance_pct`, sets `computed_variant` to `PRELIMINARY`, computes
        `qualified_tier_code` from the preliminary figures, and increments the measurement's
        `version` by one."

        Design: Corner/calculations/requalification_falls_back_when_only_the_volume_axis_misses
        """
        setup = ninety_five_percent_on_three_thousand_units

        measured = measure(api, setup["measurement"]["id"])

        a.assert_pct(measured["preliminary_compliance_pct"], 95.00)
        commitment = read_commitment(api, setup["commitment"]["id"])
        assert commitment["current_tier_code"] == TIER_0
        assert commitment["last_final_compliance_pct"] is None
        assert setup["commitment_before"]["last_final_compliance_pct"] is None


@pytest.fixture
def dossier_at_six_point_five_five(api):
    """A DRAFT contract's first dossier, scored 6.50 / 7.00 / 6.00 by CR-1."""
    set_clock(api)
    contract = create_contract(
        api,
        contract_code="C-WGT",
        requires_clinical_review=True,
        tiers=[dict(row) for row in FLAT_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    review = create_evidence_review(api, contract["id"], 6.50, 7.00, 6.00, summary="initial dossier")
    return {"contract": contract, "review": review}


def _rescore(api, review_id, efficacy, safety, resilience):
    return validate_success(
        api.patch_review_scores(
            review_id,
            f.scores_payload(efficacy, safety, resilience),
            headers=clinical_reviewer_headers(),
        ),
        200,
    )


class TestTheThreeWeightsAreAppliedOnceAndReappliedEveryTime:
    """0.40, 0.35, 0.25 against unrounded products — and a 7.0050 that must become 7.01."""

    def test_the_first_scoring_lands_below_the_inclusive_threshold(
        self, api, dossier_at_six_point_five_five
    ):
        """PRD §3.2: "Worked through: scores of 8.00, 7.00 and 6.00 give 3.20 plus 2.45 plus
        1.50, a weighted score of 7.15; scores of 6.50, 7.00 and 6.00 give 2.60 plus 2.45 plus
        1.50, a weighted score of 6.55; and scores of 7.00, 7.00 and 7.02 give an unrounded
        7.0050 that rounds half up to 7.01."
        PRD §3.2: "From the weighted score the server derives `conversion_recommendation`: it is
        `CONVERT` when the weighted score is at least 7.00 — the threshold is **inclusive**, so a
        weighted score of exactly 7.00 recommends conversion — and `DO_NOT_CONVERT` otherwise."
        PRD §3.2: "The dossier is created in `UNDER_REVIEW` status with `revision_round` at
        zero, and its `submitted_by_user_id` is set to the submitting reviewer's `X-User-ID`."

        Design: Corner/calculations/evidence_weights_applied_once_and_rescored_on_every_patch
        """
        review = dossier_at_six_point_five_five["review"]

        a.assert_score(review["weighted_score"], 6.55)
        assert review["conversion_recommendation"] == "DO_NOT_CONVERT"
        assert review["status"] == "UNDER_REVIEW"
        assert review["revision_round"] == 0
        assert review["submitted_by_user_id"] == CLINICAL_REVIEWER_1

    def test_the_recommendation_is_rederived_rather_than_sticky(
        self, api, dossier_at_six_point_five_five
    ):
        """PRD §3.2: "The recommendation is recomputed every time the scores change."
        PRD §3.2: "Scores can be revised in place while the dossier is `UNDER_REVIEW` or
        `REVISION_REQUESTED`: the revising reviewer submits all three of
        `clinical_efficacy_score`, `safety_score` and `supply_resilience_score`, which replace
        the stored values, and `weighted_score` and `conversion_recommendation` are recomputed
        under the same weighting."

        Design: Corner/calculations/evidence_weights_applied_once_and_rescored_on_every_patch
        """
        review = dossier_at_six_point_five_five["review"]

        rescored = _rescore(api, review["id"], 8.00, 7.00, 6.00)

        a.assert_score(rescored["weighted_score"], 7.15)
        assert rescored["conversion_recommendation"] == "CONVERT"

    def test_the_products_are_summed_unrounded_and_rounded_exactly_once(
        self, api, dossier_at_six_point_five_five
    ):
        """PRD §3.2: "In arithmetic terms, the efficacy score is multiplied by 0.40, the safety
        score by 0.35, and the supply-resilience score by 0.25; those three products are added
        together **unrounded**, and the single resulting sum is then rounded half up to exactly
        two decimal places, once."
        PRD §3.2: "The dossier's `weighted_score` is derived from the three scores by a fixed
        weighting: the efficacy score counts for forty percent of the total, the safety score
        for thirty-five percent, and the supply-resilience score for the remaining twenty-five
        percent."

        Design: Corner/calculations/evidence_weights_applied_once_and_rescored_on_every_patch
        """
        review = dossier_at_six_point_five_five["review"]
        _rescore(api, review["id"], 8.00, 7.00, 6.00)

        rescored = _rescore(api, review["id"], 7.00, 7.00, 7.02)

        a.assert_score(rescored["weighted_score"], 7.01)
        assert float(rescored["weighted_score"]) != 7.00
        assert rescored["conversion_recommendation"] == "CONVERT"

    def test_rescoring_moves_no_status_and_opens_no_gate(
        self, api, dossier_at_six_point_five_five
    ):
        """PRD §3.2: "A score revision increments the dossier's `version` by one and does not
        change its `status`."
        PRD §3.2: "No other review and no field of the contract participates in this
        computation."

        Design: Corner/calculations/evidence_weights_applied_once_and_rescored_on_every_patch
        """
        setup = dossier_at_six_point_five_five
        review = setup["review"]

        _rescore(api, review["id"], 8.00, 7.00, 6.00)
        _rescore(api, review["id"], 7.00, 7.00, 7.02)

        after = read_evidence_review(api, review["id"])
        assert after["status"] == "UNDER_REVIEW"
        assert after["revision_round"] == 0
        assert after["version"] == review["version"] + 2
        assert read_contract(api, setup["contract"]["id"])["evidence_endorsed"] is False


@pytest.fixture
def one_full_load_and_one_partial(api):
    """Four lines fully loaded and two lines partially loaded, against a 1200-cent price."""
    setup = build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-FEE",
            "tiers": [dict(row) for row in FLAT_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
        item_overrides={"base_price_cents": 1200, "floor_price_cents": 1000},
        member_overrides={
            "member_code": "M-FEE",
            "item_master": [
                f.item_master_row("MI-1"),
                f.item_master_row("MI-2", description="Mesh graft"),
            ],
        },
    )
    setup["loaded"] = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [
            f.purchase_line_row("MI-1", 1, 1150, "2026-08-05"),
            f.purchase_line_row("MI-1", 1, 1150, "2026-08-06"),
            f.purchase_line_row("MI-1", 1, 1500, "2026-08-07"),
            f.purchase_line_row("MI-2", 1, 1000, "2026-08-08"),
        ],
        stage="LOADED",
    )
    setup["partial"] = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [
            f.purchase_line_row("MI-1", 1, 1150, "2026-08-09"),
            f.purchase_line_row("MI-1", 0, 1150, "2026-08-10"),
        ],
        distributor_code="D-B",
        stage="LOADED",
    )
    return setup


class TestTheAccrualBasisIsNarrowerThanTheComplianceBasis:
    """One eligible line shape, one rounding rule, and four wrong answers ruled out."""

    def test_the_two_statements_land_in_different_load_states(
        self, api, one_full_load_and_one_partial
    ):
        """PRD §3.7: "**`VALIDATING → PARTIALLY_LOADED`** when `rejected_line_count` is greater
        than 0 and `accepted_line_count` is also greater than 0."
        PRD §3.7: "A partially loaded file is a real load: its accepted lines are real purchases
        and they move the member's ledgers."

        Design: Corner/calculations/admin_fee_accrual_counts_only_on_contract_lines_of_loaded_files
        """
        setup = one_full_load_and_one_partial

        assert setup["loaded"]["status"] == "LOADED"
        assert setup["partial"]["status"] == "PARTIALLY_LOADED"
        assert setup["partial"]["accepted_line_count"] == 1
        assert setup["partial"]["rejected_line_count"] == 1

    def test_the_fee_is_rounded_per_line_over_loaded_on_contract_lines_only(
        self, api, one_full_load_and_one_partial
    ):
        """PRD §3.9: "The eligible lines are purchase lines whose `reject_reason` is `NONE` and
        whose `classification` is `ON_CONTRACT`, belonging to distributor files of this contract
        — across every member, since the fee is the contract's, not a member's — whose own
        half-open period lies wholly inside the distribution's half-open period, and whose
        `status` is `LOADED`."
        PRD §3.9: "Files in `PARTIALLY_LOADED` status earn nothing, and neither do files that
        have been reversed; leakage lines and unmatched lines earn nothing, because a fee is owed
        only where the contract was actually used."
        PRD §3.9: "The rounding happens per line and only per line — never on the summed spend —
        and the difference is real: two lines of 1150 cents at 300 basis points each yield 34.5
        cents, rounded half up to 35, for a total of 70 cents, whereas rounding the aggregate
        would give 2300 times 300 divided by 10000, or 69 cents."

        Design: Corner/calculations/admin_fee_accrual_counts_only_on_contract_lines_of_loaded_files
        """
        setup = one_full_load_and_one_partial

        distribution = create_distribution(api, setup["contract"]["id"])

        assert distribution["accrued_fee_cents"] == 70
        assert distribution["accrued_fee_cents"] != 105
        assert distribution["accrued_fee_cents"] != 115
        assert distribution["accrued_fee_cents"] != 100
        assert distribution["accrued_fee_cents"] != 69

    def test_nothing_is_pooled_at_the_moment_of_accrual(
        self, api, one_full_load_and_one_partial
    ):
        """PRD §3.9: "The new row is created in `ACCRUED` status with `collected_fee_cents` at 0,
        `basis` null, `holdback_bps_applied`, `holdback_cents`, `gross_pool_cents`,
        `net_pool_cents`, `member_pool_cents`, `member_share_total_cents`, `undistributed_cents`
        and `gpo_retained_cents` all at 0, `member_shares` an empty array, and `reverse_note`
        null."
        PRD §3.9: "`accrued_fee_cents` is computed at the moment of creation and is never
        recomputed by any later transition."

        Design: Corner/calculations/admin_fee_accrual_counts_only_on_contract_lines_of_loaded_files
        """
        setup = one_full_load_and_one_partial

        distribution = create_distribution(api, setup["contract"]["id"])

        assert distribution["status"] == "ACCRUED"
        assert distribution["collected_fee_cents"] == 0
        assert distribution["basis"] is None
        assert distribution["gross_pool_cents"] == 0
        assert distribution["member_shares"] == []


@pytest.fixture
def three_members_and_one_accrual(api):
    """Three countersigned members contribute to a 100-cent accrual; one is eligible."""
    setup = build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-WFL",
            "share_basis": "ACCRUAL",
            "tiers": [dict(row) for row in FLAT_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
        item_overrides={"base_price_cents": 1200, "floor_price_cents": 1000},
        member_overrides={"member_code": "M-A"},
    )
    contract_id = setup["contract"]["id"]
    item_id = setup["item"]["id"]
    setup["leaking"] = build_second_member(
        api, contract_id, item_id, member_code="M-B", name="Lakeside Surgical Center"
    )
    setup["idle"] = build_second_member(
        api,
        contract_id,
        item_id,
        member_code="M-C",
        name="Northgate Childrens",
        with_xref=False,
        with_activation=False,
    )
    submit_distributor_file(
        api,
        setup["member"]["id"],
        contract_id,
        [
            f.purchase_line_row("MI-1", 1, 1150, "2026-08-05"),
            f.purchase_line_row("MI-1", 1, 1150, "2026-08-06"),
        ],
        stage="LOADED",
    )
    submit_distributor_file(
        api,
        setup["leaking"]["member"]["id"],
        contract_id,
        [
            f.purchase_line_row("MI-1", 1, 1000, "2026-08-05"),
            f.purchase_line_row("MI-1", 1, 5000, "2026-08-06"),
        ],
        stage="LOADED",
    )
    setup["distribution"] = create_distribution(api, contract_id)
    return setup


class TestTheMemberPoolSkipsTheFlaggedAndTheIdle:
    """M-B earned thirty of the hundred cents and is paid none of the sixty."""

    def test_the_accrual_pools_every_members_on_contract_lines(
        self, api, three_members_and_one_accrual
    ):
        """PRD §3.9: "The lines are visited in order of `purchase_date` ascending and then
        `created_at` ascending, and each one's fee is `extended_cost_cents` multiplied by the
        contract's `admin_fee_bps`, divided by 10000, rounded half up to a whole cent."
        PRD §3.9: "`accrued_fee_cents` is then the exact integer sum of those already-rounded
        per-line fees."

        Design: Corner/calculations/waterfall_eligibility_drops_leakage_flagged_and_zero_spend_members
        """
        setup = three_members_and_one_accrual

        assert setup["distribution"]["accrued_fee_cents"] == 100

    def test_the_leaking_member_is_flagged_and_on_the_watchlist(
        self, api, three_members_and_one_accrual
    ):
        """PRD §3.7: "**Hop 4 — the watchlist**, caused by hop 3 raising the flag from false to
        true."
        PRD §3.7: "The member's `watchlist_status` becomes `WATCHLIST` and that member's
        `version` increments by one."

        Design: Corner/calculations/waterfall_eligibility_drops_leakage_flagged_and_zero_spend_members
        """
        setup = three_members_and_one_accrual

        commitment = read_commitment(api, setup["leaking"]["commitment"]["id"])

        a.assert_pct(commitment["ytd_leakage_pct"], 83.33)
        assert commitment["leakage_flag"] is True
        assert commitment["ytd_on_contract_spend_cents"] == 1000
        member = read_member(api, setup["leaking"]["member"]["id"])
        assert member["watchlist_status"] == "WATCHLIST"

    def test_the_whole_member_pool_goes_to_the_one_eligible_commitment(
        self, api, three_members_and_one_accrual
    ):
        """PRD §3.9: "The member pool is split among the contract's *eligible* commitments: those
        whose `election_status` is `ACTIVE`, whose `lop_status` is `COUNTERSIGNED`, whose
        `leakage_flag` is false, and whose `ytd_on_contract_spend_cents` is strictly greater than
        0."
        PRD §3.9: "A flagged member is excluded from the rebate entirely for that period — that
        is the commercial teeth behind the leakage threshold."
        PRD §3.9: "Each `member_shares` entry records `member_id`, `commitment_id`,
        `weight_cents` — that commitment's `ytd_on_contract_spend_cents`, the weight actually
        used — and `share_cents`, the final allocated amount including any remainder cent."

        Design: Corner/calculations/waterfall_eligibility_drops_leakage_flagged_and_zero_spend_members
        """
        setup = three_members_and_one_accrual

        distributed = distribute_distribution(api, setup["distribution"]["id"])

        assert distributed["status"] == "DISTRIBUTED"
        assert len(distributed["member_shares"]) == 1
        a.assert_member_share(
            distributed, setup["member"]["id"], weight_cents=2300, share_cents=60
        )
        assert distributed["member_shares"][0]["commitment_id"] == setup["commitment"]["id"]

    def test_the_waterfall_pins_its_basis_and_conserves_the_gross_pool(
        self, api, three_members_and_one_accrual
    ):
        """PRD §3.9: "Distributing pins `basis` to the contract's `share_basis` so the settlement
        records the rule it was computed under."
        PRD §3.9: "`gross_pool_cents` is `accrued_fee_cents` when `basis` is `ACCRUAL` and
        `collected_fee_cents` when `basis` is `COLLECTED`."
        PRD §3.9: "Then `holdback_cents` is `gross_pool_cents` multiplied by
        `holdback_bps_applied`, divided by 10000, rounded half up; `net_pool_cents` is
        `gross_pool_cents` minus `holdback_cents`; and `member_pool_cents` is `net_pool_cents`
        multiplied by the contract's `member_share_bps`, divided by 10000, rounded half up."
        PRD §3.9: "The identity `member_share_total_cents` plus `undistributed_cents` plus
        `gpo_retained_cents` equals `gross_pool_cents` holds on every distributed row."

        Design: Corner/calculations/waterfall_eligibility_drops_leakage_flagged_and_zero_spend_members
        """
        setup = three_members_and_one_accrual

        distributed = distribute_distribution(api, setup["distribution"]["id"])

        assert distributed["basis"] == "ACCRUAL"
        assert distributed["gross_pool_cents"] == 100
        assert distributed["holdback_bps_applied"] == 0
        assert distributed["holdback_cents"] == 0
        assert distributed["net_pool_cents"] == 100
        assert distributed["member_pool_cents"] == 60
        assert distributed["member_share_total_cents"] == 60
        assert distributed["undistributed_cents"] == 0
        assert distributed["gpo_retained_cents"] == 40
        a.assert_waterfall_conserved(distributed)

    def test_only_the_eligible_members_credit_balance_moves(
        self, api, three_members_and_one_accrual
    ):
        """PRD §3.9: "Every eligible member's `fee_credit_balance_cents` is then credited by that
        member's `share_cents`, incrementing each member's `version` by one, the distribution's
        `status` becomes `DISTRIBUTED`, and its `version` increments by one."
        PRD §3.3: "`fee_credit_balance_cents` is the cumulative administrative-fee share credited
        to the member by the distribution waterfall of §3.9; it never goes below zero, and it is
        debited by an exact recorded amount when a distribution is reversed."

        Design: Corner/calculations/waterfall_eligibility_drops_leakage_flagged_and_zero_spend_members
        """
        setup = three_members_and_one_accrual

        distribute_distribution(api, setup["distribution"]["id"])

        assert read_member(api, setup["member"]["id"])["fee_credit_balance_cents"] == 60
        assert (
            read_member(api, setup["leaking"]["member"]["id"])["fee_credit_balance_cents"] == 0
        )
        assert read_member(api, setup["idle"]["member"]["id"])["fee_credit_balance_cents"] == 0
