"""Releasing an exclusive territory hands the slot straight back.

The incumbent holds IN exclusively for a full year.  An early release frees the
country the same day with no residual buffer, a rival immediately takes the slot,
and the count never reaches two.
"""

import pytest

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_occupancy


@pytest.fixture()
def occupied_country(client):
    """One active exclusive year-long grant on IN, plus an idle rival contract."""
    incumbent = fx.register_agency(client)
    incumbent_contract = fx.draft_contract(client, incumbent["id"])
    assignment = fx.assign_territory(
        client,
        incumbent_contract["id"],
        country_code="IN",
        exclusivity=C.TERRITORY_EXCLUSIVE,
        start_date="2026-08-01",
        end_date="2027-07-31",
    )

    rival = fx.register_agency(
        client,
        legal_name="Global Pathways Partners",
        home_country_code="IN",
        beneficial_owner_count=1,
        reference_check_count=2,
    )
    rival_contract = fx.draft_contract(
        client,
        rival["id"],
        contract_ref="CTR-2026-002",
        annual_commission_cap_cents=4000000,
    )

    return {
        "incumbent_contract_id": incumbent_contract["id"],
        "assignment_id": assignment["id"],
        "rival_contract_id": rival_contract["id"],
    }


class TestReleaseRestoresExclusiveSlot:
    def test_the_country_is_taken_and_shadowed_before_the_release(
        self, client, occupied_country
    ):
        """A live exclusive grant occupies the instant and closes the slot.

        "An assignment occupies a given instant when its status is `ACTIVE` and
        the instant falls at or after `start_date` and strictly before
        `end_date`."

        "`exclusive_slot_available`, which is true exactly when
        `exclusive_active_count` is zero, `non_exclusive_active_count` is zero,
        and either `exclusive_cooloff_until` is null or the requested instant
        falls at or after it."

        Design: Difficulty/compensating_invariant/territory_release_restores_free_exclusive_slot
        """
        occupancy = fx.read_occupancy(client, "IN", "2026-08-15")
        assert_occupancy(
            occupancy,
            country_code="IN",
            at_date="2026-08-15",
            exclusive_active_count=1,
            non_exclusive_active_count=0,
            exclusive_cooloff_until="2027-08-30",
            exclusive_slot_available=False,
        )

    def test_an_early_release_frees_the_slot_the_same_day_with_no_residual_buffer(
        self, client, occupied_country
    ):
        """The shadow of a released row disappears along with its occupancy.

        "A `RecruitmentOfficer` or `ComplianceOfficer` may release an assignment
        early, moving `ACTIVE → RELEASED` with `released_on` set to the current
        logical-clock date."

        "Release is immediate and total: the country's exclusive-slot occupancy
        drops at once and no cool-off buffer survives a release, so the freed slot
        is available the same day."

        Design: Difficulty/compensating_invariant/territory_release_restores_free_exclusive_slot
        """
        env = occupied_country

        released = fx.release_territory(
            client, env["incumbent_contract_id"], env["assignment_id"]
        )
        assert released["status"] == C.ASSIGNMENT_RELEASED
        assert released["released_on"] == C.DEFAULT_CLOCK_DATE

        occupancy = fx.read_occupancy(client, "IN", "2026-08-15")
        assert_occupancy(
            occupancy,
            country_code="IN",
            at_date="2026-08-15",
            exclusive_active_count=0,
            non_exclusive_active_count=0,
            exclusive_cooloff_until=None,
            exclusive_slot_available=True,
        )

    def test_the_freed_slot_is_grantable_and_the_exclusive_count_never_reaches_two(
        self, client, occupied_country
    ):
        """The rival takes the country over an interval the incumbent had held.

        "The exclusivity gate says that an `EXCLUSIVE` request requires zero
        `ACTIVE` assignments of either kind overlapping its interval and no
        `EXCLUSIVE` cool-off shadow reaching into that interval"

        "Occupancy is computed only from assignments still in `ACTIVE`; rows in
        `RELEASED` or `EXPIRED` contribute neither occupancy nor any lingering
        shadow."

        Design: Difficulty/compensating_invariant/territory_release_restores_free_exclusive_slot
        """
        env = occupied_country

        fx.release_territory(
            client, env["incumbent_contract_id"], env["assignment_id"]
        )
        granted = fx.assign_territory(
            client,
            env["rival_contract_id"],
            country_code="IN",
            exclusivity=C.TERRITORY_EXCLUSIVE,
            start_date="2026-08-15",
            end_date="2027-01-01",
        )
        assert granted["status"] == C.ASSIGNMENT_ACTIVE
        assert granted["contract_id"] == env["rival_contract_id"]
        assert granted["released_on"] is None

        occupancy = fx.read_occupancy(client, "IN", "2026-08-15")
        assert occupancy["exclusive_active_count"] == 1, (
            "the released row must not be counted alongside the new grant"
        )
        assert occupancy["exclusive_slot_available"] is False

        incumbent_rows = fx.read_assignments(client, env["incumbent_contract_id"])
        assert len(incumbent_rows) == 1
        assert incumbent_rows[0]["status"] == C.ASSIGNMENT_RELEASED
