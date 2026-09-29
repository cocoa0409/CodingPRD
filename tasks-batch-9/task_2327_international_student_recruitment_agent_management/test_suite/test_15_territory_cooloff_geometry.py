"""An exclusive territory casts a trailing shadow past its own end.

The incumbent occupies IN over a half-open interval ending 2026-12-01.  A rival
request starting exactly on that end date shares no instant with the incumbent
and is still refused; the same request starting thirty days later is accepted.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_occupancy


@pytest.fixture()
def incumbent_and_challenger(client):
    """One active exclusive assignment and a rival contract wanting the same country."""
    incumbent = fx.register_agency(client)
    incumbent_contract = fx.draft_contract(client, incumbent["id"])
    assignment = fx.assign_territory(
        client,
        incumbent_contract["id"],
        country_code="IN",
        exclusivity=C.TERRITORY_EXCLUSIVE,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )

    challenger = fx.register_agency(
        client,
        legal_name="Global Pathways Partners",
        home_country_code="IN",
        beneficial_owner_count=1,
        reference_check_count=2,
    )
    challenger_contract = fx.draft_contract(
        client,
        challenger["id"],
        contract_ref="CTR-2026-002",
        annual_commission_cap_cents=4000000,
    )

    return {
        "incumbent_contract_id": incumbent_contract["id"],
        "assignment_id": assignment["id"],
        "challenger_contract_id": challenger_contract["id"],
    }


class TestTerritoryCooloffGeometry:
    def test_an_interval_starting_on_the_incumbents_end_date_is_still_refused(
        self, client, incumbent_and_challenger
    ):
        """The buffer, not a shared instant, is what produces the conflict.

        "An `EXCLUSIVE` assignment additionally casts a **cool-off shadow**: its
        shadow ends 30 days after its `end_date`, whereas a `NON_EXCLUSIVE`
        assignment's shadow ends exactly at its `end_date`."

        "The exclusivity gate says that an `EXCLUSIVE` request requires zero
        `ACTIVE` assignments of either kind overlapping its interval and no
        `EXCLUSIVE` cool-off shadow reaching into that interval"

        Design: Difficulty/resource_temporal_overlap/exclusive_territory_cooloff_shadow_blocks_adjacent_interval
        """
        env = incumbent_and_challenger

        response = client.assign_territory(
            env["challenger_contract_id"],
            F.territory_payload(
                country_code="IN",
                exclusivity=C.TERRITORY_EXCLUSIVE,
                start_date="2026-12-01",
                end_date="2027-03-01",
            ),
            fx.OFFICER,
        )
        validate_error(response, E.ERR_TERRITORY_EXCLUSIVITY_CONFLICT)

        assert fx.read_assignments(client, env["challenger_contract_id"]) == []

    def test_the_occupancy_view_reports_the_shadow_with_no_live_occupant(
        self, client, incumbent_and_challenger
    ):
        """Mid-shadow, the counts are zero but the slot is not available.

        "`exclusive_cooloff_until` — the latest cool-off end among the country's
        `ACTIVE` `EXCLUSIVE` assignments, or null when there are none — and
        `exclusive_slot_available`, which is true exactly when
        `exclusive_active_count` is zero, `non_exclusive_active_count` is zero,
        and either `exclusive_cooloff_until` is null or the requested instant
        falls at or after it."

        "The response echoes the `country_code` and `at_date` it was asked
        about."

        Design: Difficulty/resource_temporal_overlap/exclusive_territory_cooloff_shadow_blocks_adjacent_interval
        """
        occupancy = fx.read_occupancy(client, "IN", "2026-12-15")
        assert_occupancy(
            occupancy,
            country_code="IN",
            at_date="2026-12-15",
            exclusive_active_count=0,
            non_exclusive_active_count=0,
            exclusive_cooloff_until="2026-12-31",
            exclusive_slot_available=False,
        )

    def test_an_interval_starting_on_the_cooloff_end_is_accepted(
        self, client, incumbent_and_challenger
    ):
        """Thirty days after the end date the country is free again.

        "The shadow of an assignment covers instants from `start_date` up to but
        not including that shadow end."

        Design: Difficulty/resource_temporal_overlap/exclusive_territory_cooloff_shadow_blocks_adjacent_interval
        """
        env = incumbent_and_challenger

        granted = fx.assign_territory(
            client,
            env["challenger_contract_id"],
            country_code="IN",
            exclusivity=C.TERRITORY_EXCLUSIVE,
            start_date="2026-12-31",
            end_date="2027-03-01",
        )
        assert granted["start_date"] == "2026-12-31"
        assert granted["status"] == C.ASSIGNMENT_ACTIVE
        assert granted["contract_id"] == env["challenger_contract_id"]

        challenger_rows = fx.read_assignments(client, env["challenger_contract_id"])
        assert len(challenger_rows) == 1, (
            f"only the accepted request may persist, got {challenger_rows!r}"
        )

        incumbent_rows = fx.read_assignments(client, env["incumbent_contract_id"])
        assert len(incumbent_rows) == 1
        assert incumbent_rows[0]["status"] == C.ASSIGNMENT_ACTIVE
        assert incumbent_rows[0]["end_date"] == "2026-12-01"
