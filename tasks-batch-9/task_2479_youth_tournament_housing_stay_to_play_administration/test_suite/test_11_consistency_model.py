"""Nothing about housing settles later.

A confirmation's own response body already carries the committed booking, and
reads taken straight afterwards already show the block, the team, the contract
and the event at their final values.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    assertions,
    fixtures as fx,
    validate_paginated,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS


def _booking_awaiting_confirmation_env(api) -> fx.Env:
    """A four-room booking with a full rooming list on the event's only
    twenty-room block, one confirmation away from committing its rooms."""
    return fx.rooming_list_env(api)


class TestConfirmIsImmediatelyConsistent:
    """The confirmation and everything it derives land in the same request."""

    def test_the_confirm_response_itself_carries_the_committed_booking(self, api):
        """The call that commits the rooms answers with the booking already at
        confirmed, its twelve projected room nights intact and its version moved
        on by one.

        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        PRD §3.4: "It moves a booking `ROOMING_LIST_SUBMITTED → CONFIRMED`, and
        it requires the governing tournament to be `OPEN`, the owning contract to
        be `EXECUTED`, and the block's `status` to still be `OPEN` or
        `RESTRICTED`."

        PRD §3.4: "Every resource whose values actually changed along that chain
        has its `updated_at` refreshed and its `version` incremented by 1."

        PRD §4: "Status codes follow one uniform rule: an endpoint that creates a
        new resource responds with `201 Created` and returns the created resource
        in `data`, while an endpoint that reads a resource, lists resources, or
        modifies or transitions an existing resource responds with `200 OK` and
        returns the read or updated resource in `data`."

        Design: Corner/consistency_model/confirm_response_already_shows_every_derived_change
        """
        env = _booking_awaiting_confirmation_env(api)
        before = env.booking

        booking = validate_success(api.confirm_booking(env.booking_id, HM))

        assert booking["id"] == env.booking_id
        assert booking["booking_status"] == "CONFIRMED"
        assert booking["rooms_requested"] == 4
        assert booking["nights"] == 3
        assert booking["projected_room_nights"] == 12
        assert booking["version"] == before["version"] + 1
        assertions.assert_versioned_record(booking)

    def test_the_very_next_reads_already_show_every_derived_field_settled(self, api):
        """With no clock advance and no second write, the block already reports
        four of twenty rooms committed at a utilization of 0.2, the team already
        reads housing-compliant against its floor of four, and the contract and
        the event already report an available, unpressured position.

        PRD §2.9: "Consistency is therefore maintained not by a hierarchy but by
        **derivation chains**: a small number of persisted aggregate fields are
        recomputed, in a fixed order, every time a fact underneath them changes."

        PRD §2.9: "Every resource whose fields a chain actually changes has its
        `updated_at` refreshed and its `version` incremented by 1, including
        resources several links away from the one the request named."

        PRD §3.4: "`rooms_available` is then `block_size_rooms` less
        `rooms_committed` while the block is `OPEN` or `RESTRICTED`, and exactly 0
        once it is `RELEASED` or `SETTLED`."

        PRD §3.4: "`utilization_pct` is `rooms_committed` divided by
        `block_size_rooms`, rounded half up to four decimal places."

        PRD §3.4: "While a block's `status` is `OPEN` or `RESTRICTED`, it reads
        `RESTRICTED` whenever `utilization_pct` is at or above 0.90 — ninety
        percent of the held rooms committed — and `OPEN` otherwise."

        PRD §3.3: "Otherwise, if `committed_rooms` is greater than or equal to
        `effective_required_rooms`, the registration is `HOUSING_COMPLIANT`; the
        comparison is inclusive, so a team that has committed exactly its
        effective requirement is compliant."

        PRD §3.2: "Otherwise it is `AVAILABLE`."

        PRD §3.2: "`housing_pressure` reads `CONSTRAINED` when
        `executed_contract_count` is at least 1 and `sold_out_contract_count`
        equals `executed_contract_count`; in every other case, including the case
        of no executed contracts at all, it reads `NORMAL`."

        Design: Corner/consistency_model/confirm_response_already_shows_every_derived_change
        """
        env = _booking_awaiting_confirmation_env(api)

        validate_success(api.confirm_booking(env.booking_id, HM))

        blocks, meta = validate_paginated(
            api.list_contract_room_blocks(env.contract_id, HM, params={"status": "OPEN"})
        )
        assert meta["total_count"] == 1
        block = blocks[0]
        assert block["block_size_rooms"] == 20
        assert block["rooms_committed"] == 4
        assert block["rooms_available"] == 16
        assert block["utilization_pct"] == 0.2
        assert block["status"] == "OPEN"
        assertions.assert_block_inventory_conserved(block)

        registration = env.refresh_registration()
        assert registration["committed_rooms"] == 4
        assert registration["effective_required_rooms"] == 4
        assert registration["status"] == "HOUSING_COMPLIANT"

        assert env.refresh_contract()["block_posture"] == "AVAILABLE"
        tournament = env.refresh_tournament()
        assert tournament["executed_contract_count"] == 1
        assert tournament["sold_out_contract_count"] == 0
        assert tournament["housing_pressure"] == "NORMAL"
        assert tournament["posture"] == "OPEN"
