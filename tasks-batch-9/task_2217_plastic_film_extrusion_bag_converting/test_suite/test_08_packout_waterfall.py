"""Packout: the case waterfall, the partial-case threshold and the pallet ceiling."""
import pytest

from test_helpers import (
    CONVERTER,
    get_success_data,
    read_bag_lot_version,
    setup_bag_lot_qualified,
    validate_success,
)


def _packout(api, lot_id, requested_bags):
    version = read_bag_lot_version(api, lot_id)
    return validate_success(
        api.packout_bag_lot(lot_id, requested_bags, version, CONVERTER), 200)


class TestPalletCountIsCeilingOverCumulativeCases:
    """Two identical packouts of 45 cases each give three pallets, not four."""

    def test_first_packout_books_forty_five_whole_cases(self, api):
        """22500 bags at 500 per case leaves no remainder at all.

        PRD: "the number of full cases is `requested_bags` divided by the
        product's `bags_per_case`, rounded down; the remainder is
        `requested_bags` minus that full-case count multiplied by `bags_per_case`."

        Design: Difficulty/combinatorial_formula/pallet_count_is_ceiling_over_cumulative_case_count
        """
        world = setup_bag_lot_qualified(api)
        first = _packout(api, world["bag_lot"]["id"], 22500)

        assert first["packed_case_count"] == 45
        assert first["partial_case_bag_count"] == 0
        assert first["pallet_count"] == 2
        assert first["packed_bag_count"] == 22500
        assert first["bag_count_unpacked"] == 23500

    def test_first_packout_moves_the_lot_into_packed(self, api):
        """The lot leaves QUALIFIED on the first accepted allocation.

        PRD: "The first accepted packout moves the lot `QUALIFIED → PACKED` or
        `CONDITIONAL → PACKED`, applying identical allocation and counter updates
        on both branches".

        Design: Difficulty/combinatorial_formula/pallet_count_is_ceiling_over_cumulative_case_count
        """
        world = setup_bag_lot_qualified(api)
        assert world["bag_lot"]["status"] == "QUALIFIED"

        first = _packout(api, world["bag_lot"]["id"], 22500)
        assert first["status"] == "PACKED"

    def test_second_packout_takes_the_ceiling_over_the_cumulative_count(self, api):
        """Ninety cumulative cases over forty per pallet gives three pallets.

        PRD: the pallet count is
        "a ceiling taken over the cumulative case count, never the sum of per-packout ceilings."

        Design: Difficulty/combinatorial_formula/pallet_count_is_ceiling_over_cumulative_case_count
        """
        world = setup_bag_lot_qualified(api)
        _packout(api, world["bag_lot"]["id"], 22500)
        second = _packout(api, world["bag_lot"]["id"], 22500)

        assert second["packed_case_count"] == 90
        assert second["pallet_count"] == 3
        assert second["pallet_count"] != 4
        assert second["packed_bag_count"] == 45000
        assert second["bag_count_unpacked"] == 1000

    def test_conservation_holds_after_both_allocations(self, api):
        """Every produced bag is accounted for in exactly one bucket.

        PRD: "A conservation invariant holds after every packout and every
        unwind: `bag_count_produced` always equals `bag_count_unpacked` plus
        `packed_bag_count` plus `bag_count_scrapped`."

        Design: Difficulty/combinatorial_formula/pallet_count_is_ceiling_over_cumulative_case_count
        """
        world = setup_bag_lot_qualified(api)
        _packout(api, world["bag_lot"]["id"], 22500)
        _packout(api, world["bag_lot"]["id"], 22500)

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["bag_count_produced"] == 46000
        assert (lot["bag_count_unpacked"] + lot["packed_bag_count"]
                + lot["bag_count_scrapped"]) == lot["bag_count_produced"]


class TestPartialCaseThreshold:
    """A remainder of 200 is billable; a remainder of 199 is not packed at all."""

    def test_remainder_exactly_at_the_threshold_opens_a_partial_case(self, api):
        """10200 bags leave 200 over, which equals min_partial_case_bags.

        PRD: "A short case counts as one billable case only when the remainder is
        greater than zero **and** at least the product's `min_partial_case_bags`;
        in that case the remainder's bags are packed into it".

        Design: Difficulty/boundary_precision_check/packout_remainder_exactly_at_partial_case_threshold_versus_one_below
        """
        world = setup_bag_lot_qualified(api)
        first = _packout(api, world["bag_lot"]["id"], 10200)

        assert first["packed_case_count"] == 21
        assert first["partial_case_bag_count"] == 200
        assert first["packed_bag_count"] == 10200
        assert first["bag_count_unpacked"] == 35800
        assert first["pallet_count"] == 1

    def test_remainder_one_below_the_threshold_leaves_its_bags_unpacked(self, api):
        """10199 bags book twenty full cases and strand 199 bags.

        PRD: "otherwise the short case is not created and its bags are **not**
        packed — they remain in `bag_count_unpacked` awaiting a later call."

        Design: Difficulty/boundary_precision_check/packout_remainder_exactly_at_partial_case_threshold_versus_one_below
        """
        world = setup_bag_lot_qualified(api)
        _packout(api, world["bag_lot"]["id"], 10200)
        second = _packout(api, world["bag_lot"]["id"], 10199)

        assert second["packed_case_count"] == 41
        assert second["packed_bag_count"] == 20200
        assert second["bag_count_unpacked"] == 25800

    def test_pallet_count_follows_the_forty_one_cumulative_cases(self, api):
        """Forty-one cases over forty per pallet rounds up to two pallets.

        PRD: "`pallet_count` is then recomputed as the **cumulative**
        `packed_case_count` divided by the product's `cases_per_pallet`,
        rounded up — a ceiling taken over the cumulative case count, never the
        sum of per-packout ceilings."

        Design: Difficulty/boundary_precision_check/packout_remainder_exactly_at_partial_case_threshold_versus_one_below
        """
        world = setup_bag_lot_qualified(api)
        _packout(api, world["bag_lot"]["id"], 10200)
        second = _packout(api, world["bag_lot"]["id"], 10199)

        assert second["pallet_count"] == 2
        assert second["status"] == "PACKED"

    @pytest.mark.parametrize("requested_bags,expected_cases,expected_packed", [
        (10200, 21, 10200),
        (10199, 20, 10000),
    ])
    def test_one_bag_apart_the_allocations_diverge(self, api, requested_bags,
                                                   expected_cases, expected_packed):
        """The threshold decides both the case count and the packed bag count.

        PRD: "The bags packed by this call are the full-case count multiplied by
        `bags_per_case`, plus the partial-case bags if any."

        Design: Difficulty/boundary_precision_check/packout_remainder_exactly_at_partial_case_threshold_versus_one_below
        """
        world = setup_bag_lot_qualified(api)
        result = _packout(api, world["bag_lot"]["id"], requested_bags)

        assert result["packed_case_count"] == expected_cases
        assert result["packed_bag_count"] == expected_packed
        assert result["bag_count_unpacked"] == 46000 - expected_packed
