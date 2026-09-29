"""Compensating operations checked against the quantity they are meant to conserve.

A void must return the season's committed money to the byte-identical figure it
held before the create while adding rather than deleting ledger rows; a
withdrawal must return the room's seat capacity while leaving the row behind.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import STUDIO_EXECUTIVE_HEADERS, make_writer_headers

VOID_REASON = "Episode restructured; the teleplay is being reassigned."
WITHDRAW_REASON = "Offer superseded by a competing bid."


def _committed_assignment(api):
    """One teleplay has committed 1,750,000 of script money against the season."""
    world = X.build_assignment_world(api)
    world["season_before"] = X.read_season(api, world["season_id"])
    world["rows_before"] = X.ledger_for_assignment(api, world["a1_id"])
    return world


def _seats_of(api, **params):
    """Every seat row matching the supplied filter."""
    rows, _ = validate_paginated(
        api.list_room_seats(STUDIO_EXECUTIVE_HEADERS, dict(params, limit=100))
    )
    return rows


def _observe_room(api, world):
    """The room and season figures that the capacity invariant is read from."""
    room = X.read_room(api, world["room_id"])
    A.assert_seat_capacity_conserved(room)
    season = X.read_season(api, world["season_id"])
    return room, season


def _withdrawn_offer_world(api):
    """The single outstanding offer has been pulled back by the showrunner."""
    world = X.build_offered_seat_world(api)
    validate_success(
        api.withdraw_seat(
            world["s1_id"], world["sr_headers"], {"reason": WITHDRAW_REASON}
        )
    )
    world["room_version"] = X.current_room_version(api, world["room_id"])
    return world


def test_the_void_appends_a_reversal_that_drives_the_ledger_sum_to_zero(api):
    """Three surviving rows sum to nothing, and the season's committed figure is back to 0.

    PRD: "The assignment becomes `VOID` and its money is unwound exactly: a single `FEE_REVERSAL` entry is appended whose `amount_cents` is the negation of the sum of every prior ledger entry of that assignment, which drives the assignment's own ledger contribution to exactly 0, and the assignment's `guarantee_slot_applied` is cleared to false with `guarantee_offset_cents` and `payable_fee_cents` both set to 0."

    PRD: "Every movement of script money is recorded in an **append-only fee ledger**, whose entries are never mutated or deleted."

    PRD: "The season's `script_fee_committed_cents` is recomputed from the ledger — so a create followed by its void returns the season's committed figure to the value it held before the create — and the seat's guarantee counters are recounted, returning the freed slot to `guarantee_slots_remaining`."

    Design: Difficulty/compensating_invariant/void_restores_season_committed_fee_and_drives_the_assignment_ledger_sum_to_zero
    """
    world = _committed_assignment(api)
    A.assert_cents(
        world["season_before"]["script_fee_committed_cents"],
        1750000,
        "script_fee_committed_cents",
    )
    assert len(world["rows_before"]) == 2, (
        f"Creation writes two rows: {A.entry_types(world['rows_before'])}"
    )
    A.assert_ledger_sum(world["rows_before"], 1750000)

    voided = validate_success(
        api.void_assignment(
            world["a1_id"], F.build_void(VOID_REASON), world["sr_headers"]
        )
    )
    A.assert_field_values(voided, status="VOID", guarantee_slot_applied=False)
    A.assert_cents(voided["guarantee_offset_cents"], 0, "guarantee_offset_cents")
    A.assert_cents(voided["payable_fee_cents"], 0, "payable_fee_cents")

    rows = X.ledger_for_assignment(api, world["a1_id"])
    assert A.entry_types(rows) == [
        "SCRIPT_FEE_ACCRUAL",
        "GUARANTEE_OFFSET",
        "FEE_REVERSAL",
    ], f"The reversal is appended, never substituted: {A.entry_types(rows)}"
    A.assert_ledger_sum(rows, 0)
    assert rows[:2] == world["rows_before"], (
        "The two pre-existing rows must be byte-identical after the void"
    )
    A.assert_cents(rows[2]["amount_cents"], -1750000, "amount_cents")
    A.assert_ledger_common_fields(rows[2])

    A.assert_cents(
        X.read_season(api, world["season_id"])["script_fee_committed_cents"],
        0,
        "script_fee_committed_cents",
    )


def test_the_void_returns_the_guarantee_slot_and_freezes_the_milestones(api):
    """The freed slot goes back to the seat and the frozen chain admits no delivery.

    PRD: "The assignment's milestones are frozen at whatever status they held — the milestone lifecycle has no cancelled member — and no further delivery can be made against them, because delivery requires the owning assignment to be in `DRAFTING` or `IN_NOTES`."

    PRD: "The episode's `script_readiness` falls `IN_PROGRESS → NOT_STARTED` only when every assignment of that episode is void after this one is applied; otherwise readiness is unchanged."

    PRD: "an attempt against an assignment already `APPROVED` or `VOID` is rejected with `ERR_ASSIGNMENT_ALREADY_TERMINAL`"

    Design: Difficulty/compensating_invariant/void_restores_season_committed_fee_and_drives_the_assignment_ledger_sum_to_zero
    """
    world = _committed_assignment(api)
    outline_id = world["a1_milestone_ids"][0]

    validate_success(
        api.void_assignment(
            world["a1_id"], F.build_void(VOID_REASON), world["sr_headers"]
        )
    )

    A.assert_field_values(
        X.read_seat(api, world["s1_id"]),
        guarantee_slots_consumed=0,
        guarantee_slots_remaining=1,
    )
    A.assert_guarantee_slots_conserved(X.read_seat(api, world["s1_id"]))
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), script_readiness="NOT_STARTED"
    )
    A.assert_field_values(
        X.read_milestone(api, outline_id),
        status="PENDING",
        due_date=K.DUE_DATES_NOV_02["OUTLINE"],
    )

    # The frozen milestone is still PENDING, so it passes the deliverable-status
    # gate; PRD: "no further delivery can be made against them, because delivery
    # requires the owning assignment to be in `DRAFTING` or `IN_NOTES`".
    validate_error(
        api.deliver_milestone(outline_id, make_writer_headers(world["w1_id"])),
        ApiErrorId.ASSIGNMENT_NOT_DRAFTING,
    )
    validate_error(
        api.void_assignment(
            world["a1_id"], F.build_void(VOID_REASON), world["sr_headers"]
        ),
        ApiErrorId.ASSIGNMENT_ALREADY_TERMINAL,
    )

    assert len(X.ledger_for_assignment(api, world["a1_id"])) == 3, (
        "A refused void appends nothing"
    )
    A.assert_field_values(
        X.read_season(api, world["season_id"]), ready_script_count=0, coverage_gap=1
    )


def test_withdrawing_the_offer_restores_the_room_counters_exactly(api):
    """The room returns to the figures it held before the offer was ever made.

    PRD: "Withdrawing is the mirror image from the studio side: the showrunner pulls an outstanding offer, optionally citing a `reason`, and the seat becomes `WITHDRAWN` with exactly the same counter arithmetic."

    PRD: "The seat becomes `DECLINED`, the room's `filled_seat_count` drops by one and `open_seat_count` is recomputed as capacity minus filled seats — which restores the room's seat-conservation identity exactly — the writer's `active_seat_count` drops by one, and the room's weekly figures and the season's staffing commitment are recomputed even though a merely offered seat never contributed to the subtotal."

    Design: Difficulty/compensating_invariant/withdrawing_a_seat_offer_restores_room_capacity_and_season_burn_exactly
    """
    world = X.build_offered_seat_world(api)
    offered_room, offered_season = _observe_room(api, world)
    A.assert_field_values(
        offered_room, filled_seat_count=1, open_seat_count=2, confirmed_seat_count=0
    )
    A.assert_room_burn(
        offered_room, 0, K.FACILITY_TIER_1, K.ROOM_BURN_EMPTY_IN_PERSON, K.ROOM_BURN_EMPTY_IN_PERSON
    )

    withdrawn = validate_success(
        api.withdraw_seat(
            world["s1_id"], world["sr_headers"], {"reason": WITHDRAW_REASON}
        )
    )
    A.assert_field_values(withdrawn, status="WITHDRAWN")

    room, season = _observe_room(api, world)
    A.assert_field_values(
        room, filled_seat_count=0, open_seat_count=3, confirmed_seat_count=0
    )
    A.assert_room_burn(
        room, 0, K.FACILITY_TIER_1, K.ROOM_BURN_EMPTY_IN_PERSON, K.ROOM_BURN_EMPTY_IN_PERSON
    )
    A.assert_cents(
        season["staffing_commitment_weekly_cents"],
        offered_season["staffing_commitment_weekly_cents"],
        "staffing_commitment_weekly_cents",
    )
    A.assert_field_values(X.read_writer(api, world["w1_id"]), active_seat_count=0)
    A.assert_field_values(X.read_window(api, world["aw1_id"]), status="OPEN")


def test_the_withdrawn_row_survives_and_the_freed_capacity_is_reusable(api):
    """History is kept, the seat is terminal, and the identical offer succeeds again.

    PRD: "`DECLINED` and `WITHDRAWN` are terminal; a writer cannot later accept a seat they declined, and the same `ERR_SEAT_NOT_OFFERED` guards both operations against a seat that has already moved on."

    PRD: "Finally the room must have room — `open_seat_count` must be at least 1, otherwise `ERR_SEAT_CAPACITY_EXCEEDED`"

    Design: Difficulty/compensating_invariant/withdrawing_a_seat_offer_restores_room_capacity_and_season_burn_exactly
    """
    world = _withdrawn_offer_world(api)

    kept = _seats_of(api, room_id=world["room_id"], status="WITHDRAWN")
    assert len(kept) == 1 and kept[0]["id"] == world["s1_id"], (
        f"The withdrawn seat is history, not a deletion: {kept}"
    )
    A.assert_field_values(X.read_seat(api, world["s1_id"]), status="WITHDRAWN")

    replayed = validate_success(
        api.offer_seat(
            world["room_id"],
            F.build_seat_offer(world["w1_id"], world["room_version"]),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_field_values(replayed, status="OFFERED")

    room, _ = _observe_room(api, world)
    A.assert_field_values(room, filled_seat_count=1, open_seat_count=2)

    validate_error(
        api.withdraw_seat(
            world["s1_id"], world["sr_headers"], {"reason": WITHDRAW_REASON}
        ),
        ApiErrorId.SEAT_NOT_OFFERED,
    )
