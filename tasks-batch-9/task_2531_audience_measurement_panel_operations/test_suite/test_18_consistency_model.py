"""The immediate consistency model (PRD 2.9).

There is no recompute, refresh or reconcile endpoint anywhere in the contract, so
every derived field has to be correct in the body of the write that caused it and
in the very next read. These tests walk one chain across three entities without a
single settling call in between.
"""

from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, validate_success

from test_helpers.assertions import (
    expected_boost_reservation,
    expected_fill_rate,
)
from test_helpers.constants import BOOSTED_MULTIPLIER
from test_helpers.fixtures import CLOCK_T0, PanelHarness

MARKET_CODE = "DMA-701"
DMA_RANK = 201
BUDGET_CENTS = 500000
TARGET_HOUSEHOLDS = 2
BASE_INCENTIVE_CENTS = 2000
SERIAL_NO = "MT-002103"


def _instant_seconds(value: str) -> int:
    """Whole seconds since the epoch for an ISO 8601 UTC instant."""
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC instant: {value!r}"
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _assert_instant(got: str, want: str, label: str = "timestamp") -> None:
    """Assert two ISO 8601 UTC instants name the same moment, to the second."""
    assert _instant_seconds(got) == _instant_seconds(want), (
        f"{label}: expected {want!r}, got {got!r}"
    )


class TestDerivedRollupsAreCurrentImmediately:
    """One market, one cell, one household, walked write by write (PRD 2.9)."""

    @staticmethod
    def _create_market(panel: PanelHarness):
        """POST /markets, returning the creation response body itself."""
        return validate_success(
            panel.client.create_market(
                panel.ops,
                name="Fairview DMA",
                market_code=MARKET_CODE,
                dma_rank=DMA_RANK,
                incentive_budget_cents=BUDGET_CENTS,
            ),
            201,
        )

    @staticmethod
    def _create_cell(panel: PanelHarness, market_id: str):
        """POST /markets/{id}/quota-cells, returning the creation response body."""
        return validate_success(
            panel.client.create_quota_cell(
                panel.ops,
                market_id,
                age_band="P18_34",
                income_band="MID",
                geo_zone="URBAN",
                target_households=TARGET_HOUSEHOLDS,
                base_incentive_cents=BASE_INCENTIVE_CENTS,
            ),
            201,
        )

    def test_creation_responses_already_carry_their_derived_fields(
        self, panel: PanelHarness
    ):
        """The posture and the fill grade are computed inside the create, not on read.

        PRD 2.9: "The platform treats those secondary movements as part of the
        operation, not as eventual consequences: they are applied immediately, in
        the order the workflow states, within the same request."

        Design: Corner/consistency_model/every_derived_rollup_is_current_in_the_response_that_caused_it
        """
        market = self._create_market(panel)
        # PRD 3.1: "the initial posture is `RESTRICTED` rather than `OPEN`" and
        # "`posture_changed_at` is stamped from the logical clock at registration".
        assert market["recruitment_posture"] == "RESTRICTED"
        _assert_instant(market["posture_changed_at"], CLOCK_T0, "posture_changed_at")

        cell = self._create_cell(panel, market["id"])
        # PRD 3.1: "A newly created cell is empty, and the fill calculation
        # therefore lands it in its most aggressive recruitment stance:
        # `intab_count` 0, `fill_rate` 0.0000, `quota_status` `UNDER_TARGET`,
        # `incentive_boost_active` true and `effective_incentive_multiplier` 1.25."
        assert cell["intab_count"] == 0
        assert cell["fill_rate"] == expected_fill_rate(0, TARGET_HOUSEHOLDS)
        assert cell["fill_rate"] == 0.0
        assert cell["quota_status"] == "UNDER_TARGET"
        assert cell["incentive_boost_active"] is True
        assert cell["effective_incentive_multiplier"] == BOOSTED_MULTIPLIER

    def test_the_parents_rollups_moved_on_the_childs_write(self, panel: PanelHarness):
        """The first read after the cell write already shows the reserve and the flip.

        PRD 3.1: "That armed boost immediately reserves budget on the parent
        market, the market's `quota_cell_count` and `under_target_cell_count`
        each rise by one, the posture is re-evaluated - which moves a market
        holding its first cell from `RESTRICTED` to `OPEN`, because clause 3 no
        longer matches".

        Design: Corner/consistency_model/every_derived_rollup_is_current_in_the_response_that_caused_it
        """
        market = self._create_market(panel)
        self._create_cell(panel, market["id"])

        after = validate_success(panel.client.get_market(panel.ops, market["id"]), 200)

        assert after["incentive_budget_reserved_cents"] == expected_boost_reservation(
            BASE_INCENTIVE_CENTS, TARGET_HOUSEHOLDS
        )
        assert after["incentive_budget_reserved_cents"] == 1000
        assert after["quota_cell_count"] == 1
        assert after["under_target_cell_count"] == 1
        assert after["recruitment_posture"] == "OPEN"

    def test_immediacy_is_not_eagerness_for_a_recruited_household(
        self, panel: PanelHarness
    ):
        """A RECRUITED home is outside the fill calculation's inputs, so nothing moved.

        PRD 3.2: "A recruited household begins at `status` `RECRUITED` ...
        Recruitment alone does not put a household in tab: the cell's
        `intab_count` does not move."

        Design: Corner/consistency_model/every_derived_rollup_is_current_in_the_response_that_caused_it
        """
        market = self._create_market(panel)
        cell = self._create_cell(panel, market["id"])

        household = validate_success(
            panel.client.create_household(
                panel.ops,
                market_id=market["id"],
                quota_cell_id=cell["id"],
                recruitment_source="ADDRESS_SAMPLE",
                persons_count=2,
            ),
            201,
        )
        assert household["status"] == "RECRUITED"

        unchanged = validate_success(
            panel.client.get_quota_cell(panel.ops, cell["id"]), 200
        )
        assert unchanged["intab_count"] == 0
        assert unchanged["fill_rate"] == 0.0

    def test_the_enumeration_response_carries_the_two_level_rollup(
        self, panel: PanelHarness
    ):
        """Household, cell and market are all settled by the time the write returns.

        PRD 3.2: "`ENUM_PENDING` with a `COMPLIANT` verdict moves the household to
        `ACTIVE`. ... Its cell's `intab_count` rises by one, the fill calculation
        re-grades the cell, and the market's posture is recomputed."

        Design: Corner/consistency_model/every_derived_rollup_is_current_in_the_response_that_caused_it
        """
        market = self._create_market(panel)
        cell = self._create_cell(panel, market["id"])
        household = panel.recruit_household(
            market["id"],
            cell["id"],
            recruitment_source="ADDRESS_SAMPLE",
            persons_count=2,
        )
        meter = panel.ship_meter(
            household["id"], meter_type="TV_TUNER", serial_no=SERIAL_NO
        )
        panel.install_meter(meter["id"])

        enumerated = validate_success(
            panel.client.create_enumeration(
                panel.tech, household["id"], roster_persons_count=2, tv_sets_count=1
            ),
            200,
        )
        assert enumerated["status"] == "ACTIVE"
        assert enumerated["enumeration_verdict"] == "COMPLIANT"
        assert enumerated["enumeration_count"] == 1

        regraded = validate_success(
            panel.client.get_quota_cell(panel.ops, cell["id"]), 200
        )
        assert regraded["intab_count"] == 1
        assert regraded["fill_rate"] == expected_fill_rate(1, TARGET_HOUSEHOLDS)
        assert regraded["fill_rate"] == 0.5
        assert regraded["quota_status"] == "UNDER_TARGET"

        recomputed = validate_success(
            panel.client.get_market(panel.ops, market["id"]), 200
        )
        assert recomputed["under_target_cell_count"] == 1
        assert recomputed["recruitment_posture"] == "OPEN"
