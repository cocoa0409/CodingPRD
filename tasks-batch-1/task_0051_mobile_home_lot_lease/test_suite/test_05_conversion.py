"""Park-to-resident conversion votes: tally pass cascade, tally fail keeping park
ownership, duplicate-ballot rejection, ballot reverse-reachability listing, and
the frozen-lot activation block.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
)

MGR = TEST_USERS["manager_headers"]


class TestTally:
    def test_tally_pass_flips_ownership_and_unfreezes(self, api):
        """PRD §3.8: "On a passing tally the vote moves `OPEN → PASSED`, the
        community's `ownership_model` flips `PARK_OWNED → RESIDENT_OWNED`, and
        every frozen community lot transitions `FROZEN → OCCUPIED` with its
        `version` incremented."

        Design: Difficulty/transitive_cascade/conversion_tally_pass_depth2_cascade
        """
        community, lot, resident, lease, vote = fx.setup_open_vote_one_lot(
            quorum=1.0, state_code="CA", api=api
        )
        get_success_data(api.cast_ballot(vote["id"], fx.f.create_ballot_payload(lot["id"], "YES"), MGR))
        tallied = get_success_data(api.tally_conversion_vote(vote["id"], MGR))
        assert tallied["status"] == "PASSED"
        community_after = get_success_data(api.get_community(community["id"], MGR))
        assert community_after["ownership_model"] == "RESIDENT_OWNED"
        lot_after = get_success_data(api.get_lot(lot["id"], MGR))
        assert lot_after["status"] == "OCCUPIED"

    def test_tally_pass_lot_returns_to_occupied(self, api):
        """PRD §3.8: "every frozen community lot transitions `FROZEN → OCCUPIED`
        with its `version` incremented."

        Design: Difficulty/transitive_cascade/conversion_tally_pass_depth2_cascade
        """
        community, lot, resident, lease, vote = fx.setup_open_vote_one_lot(
            quorum=1.0, state_code="CA", api=api
        )
        # Confirm the lot was frozen by opening.
        lot_frozen = get_success_data(api.get_lot(lot["id"], MGR))
        assert lot_frozen["status"] == "FROZEN"
        get_success_data(api.cast_ballot(vote["id"], fx.f.create_ballot_payload(lot["id"], "YES"), MGR))
        get_success_data(api.tally_conversion_vote(vote["id"], MGR))
        lot_after = get_success_data(api.get_lot(lot["id"], MGR))
        assert lot_after["status"] == "OCCUPIED"

    def test_tally_fail_keeps_park_owned(self, api):
        """PRD §3.8: "On a failing tally the vote moves `OPEN → FAILED`, the
        community's `ownership_model` is left unchanged, and the same unfreeze
        cascade returns every frozen lot `FROZEN → OCCUPIED` with its `version`
        incremented."

        Design: Corner/endpoints/conversion_tally_fail_keeps_park_owned
        """
        community, lot, resident, lease, vote = fx.setup_open_vote_one_lot(
            quorum=0.5, state_code="CA", api=api
        )
        # No YES ballots -> 0/1 < 0.5 -> FAILED.
        tallied = get_success_data(api.tally_conversion_vote(vote["id"], MGR))
        assert tallied["status"] == "FAILED"
        community_after = get_success_data(api.get_community(community["id"], MGR))
        assert community_after["ownership_model"] == "PARK_OWNED"
        lot_after = get_success_data(api.get_lot(lot["id"], MGR))
        assert lot_after["status"] == "OCCUPIED"


class TestBallots:
    def test_duplicate_ballot_for_lot_rejected(self, api):
        """PRD §3.8: "There may be only one ballot per lot per vote, and the lot
        must be occupied and therefore eligible; a second ballot for the same lot,
        or a ballot for an ineligible lot, is rejected with `ERR_DUPLICATE_BALLOT`
        (HTTP 409)."

        Design: Corner/validations/duplicate_ballot_for_lot_rejected
        """
        community, lot, resident, lease, vote = fx.setup_open_vote_one_lot(
            quorum=0.5, state_code="CA", api=api
        )
        get_success_data(api.cast_ballot(vote["id"], fx.f.create_ballot_payload(lot["id"], "YES"), MGR))
        resp = api.cast_ballot(vote["id"], fx.f.create_ballot_payload(lot["id"], "NO"), MGR)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BALLOT.value)

    def test_list_ballots_for_vote_returns_cast_ballot(self, api):
        """PRD §3.8: "A ballot records its `conversion_vote_id`, `lot_id`, and
        `choice`, and casting one recomputes the vote's `yes_count`."

        Design: Corner/endpoints/list_ballots_reverse_reachability
        """
        community, lot, resident, lease, vote = fx.setup_open_vote_one_lot(
            quorum=0.5, state_code="CA", api=api
        )
        get_success_data(api.cast_ballot(vote["id"], fx.f.create_ballot_payload(lot["id"], "YES"), MGR))
        resp = api.list_vote_ballots(vote["id"], MGR)
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert data[0]["choice"] == "YES"
        assert data[0]["lot_id"] == lot["id"]


class TestFrozenLotActivation:
    def test_activate_lease_on_non_vacant_lot_after_freeze_cycle_rejected(self, api):
        """PRD §3.2: "The lot must not be `FROZEN` by an open conversion vote; a
        frozen lot is rejected with `ERR_LOT_FROZEN` (HTTP 409)."
        PRD §3.2: "The target lot must be `VACANT`; a non-vacant lot is rejected
        with `ERR_LOT_NOT_VACANT` (HTTP 409)."

        Design: Corner/validations/activate_into_frozen_lot_rejected
        """
        community = fx.create_community(api, state_code="CA")
        lot1 = fx.create_lot(community["id"], api, lot_number="F1", base_rent_cents=60000)
        lot2 = fx.create_lot(community["id"], api, lot_number="F2", base_rent_cents=60000)
        res1 = fx.create_resident(community["id"], api, full_name="RF1")
        res2 = fx.create_resident(community["id"], api, full_name="RF2")
        lease1 = fx.create_lease(lot1["id"], res1["id"], api)
        fx.activate_lease(lease1["id"], api)
        lease2 = fx.create_lease(lot2["id"], res2["id"], api)
        fx.activate_lease(lease2["id"], api)
        vote = get_success_data(
            api.create_conversion_vote(
                fx.f.create_conversion_vote_payload(community["id"], quorum_threshold_pct=0.5), MGR
            )
        )
        get_success_data(api.open_conversion_vote(vote["id"], MGR))
        # Opening the vote froze every occupied lot (OCCUPIED -> FROZEN). A lease
        # activation against lot2 — now FROZEN and non-vacant — must be rejected.
        lease3 = fx.create_lease(lot2["id"], res1["id"], api, start_date="2026-03-01")
        resp = api.activate_lease(lease3["id"], MGR)
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_LOT_FROZEN.value, ApiErrorId.ERR_LOT_NOT_VACANT.value],
        )
