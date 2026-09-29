"""Rate cards tile the contract term with zero tolerance either way.

The first card covers 2026-08-01 to 2026-11-01.  A second card starting before
that frontier is an overlap, one starting after it is a gap, and only the exact
seam is accepted.  Nothing but the accepted append touches the parent version.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as fx

SECOND_CARD_RATES = {
    "deposit_rate_bps": 420,
    "enrollment_rate_bps": 520,
    "census_rate_bps": 210,
    "persistence_rate_bps": 160,
}


@pytest.fixture()
def half_tiled_contract(client):
    """A contract whose first rate card stops three months into its term."""
    agency = fx.register_agency(client)
    contract = fx.draft_contract(client, agency["id"])
    first_card = fx.append_schedule(
        client,
        contract["id"],
        contract["version"],
        effective_from="2026-08-01",
        effective_to="2026-11-01",
    )
    frontier_version = fx.contract_version(client, contract["id"])

    return {
        "contract_id": contract["id"],
        "first_card_id": first_card["id"],
        "frontier_version": frontier_version,
    }


class TestScheduleTilingSeam:
    @pytest.mark.parametrize(
        "effective_from,expected_error",
        [
            ("2026-10-15", E.ERR_SCHEDULE_INTERVAL_CONFLICT),
            ("2026-11-15", E.ERR_SCHEDULE_GAP),
        ],
    )
    def test_a_card_off_the_seam_is_refused_on_the_side_it_misses(
        self, client, half_tiled_contract, effective_from, expected_error
    ):
        """Early is an overlap; late is a gap.

        "A card whose `effective_from` is earlier than the greatest existing
        `effective_to` on the contract — or a first card that does not start on
        `term_start_date` — is rejected with `ERR_SCHEDULE_INTERVAL_CONFLICT`."

        "A card whose `effective_from` is later than that greatest existing
        `effective_to`, leaving an uncovered stretch, is rejected with
        `ERR_SCHEDULE_GAP`."

        Design: Difficulty/resource_temporal_overlap/commission_schedule_contiguous_tiling_rejects_overlap_and_gap
        """
        env = half_tiled_contract

        response = client.append_commission_schedule(
            env["contract_id"],
            F.schedule_payload(
                env["frontier_version"],
                effective_from=effective_from,
                effective_to="2027-02-01",
                **SECOND_CARD_RATES,
            ),
            fx.OFFICER,
        )
        validate_error(response, expected_error)

        assert len(fx.read_schedules(client, env["contract_id"])) == 1, (
            "a rejected append must persist no row"
        )
        assert fx.contract_version(client, env["contract_id"]) == (
            env["frontier_version"]
        ), "a rejected append must not bump the parent version"

    def test_the_exact_seam_is_accepted_and_numbered_in_creation_order(
        self, client, half_tiled_contract
    ):
        """The two cards abut with no gap and no overlap.

        "every later card must begin precisely where the latest existing card
        ended"

        "The server assigns `version_no` itself as the 1-based sequence number of
        the card in creation order within the contract, so the first card on a
        contract is 1 and each subsequent card is one higher."

        "the successful append increments the contract's `version` by one"

        Design: Difficulty/resource_temporal_overlap/commission_schedule_contiguous_tiling_rejects_overlap_and_gap
        """
        env = half_tiled_contract

        second_card = fx.append_schedule(
            client,
            env["contract_id"],
            env["frontier_version"],
            effective_from="2026-11-01",
            effective_to="2027-02-01",
            **SECOND_CARD_RATES,
        )
        assert second_card["version_no"] == 2
        assert second_card["effective_from"] == "2026-11-01"

        cards = fx.read_schedules(client, env["contract_id"])
        assert len(cards) == 2
        by_id = {c["id"]: c for c in cards}
        assert by_id[env["first_card_id"]]["effective_to"] == "2026-11-01"
        assert by_id[second_card["id"]]["effective_from"] == "2026-11-01"

        assert fx.contract_version(client, env["contract_id"]) == (
            env["frontier_version"] + 1
        )
