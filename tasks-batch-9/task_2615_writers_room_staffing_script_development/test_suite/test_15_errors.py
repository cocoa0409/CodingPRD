"""Error-catalogue coverage: not-found reads, uniqueness and capacity ceilings,
out-of-sequence credit calls, undeliverable scripts and the script-fee budget.

Every test in this module translates exactly one instance of
SCAFFOLD_CORNER_DESIGN.yaml section `errors`.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    GUILD_ADMINISTRATOR_HEADERS,
    LEGAL_COUNSEL_HEADERS,
    STUDIO_EXECUTIVE_HEADERS,
    make_writer_headers,
)

# --- Module landmarks --------------------------------------------------------

# build_registry seeds exactly these eight writers: sr, w1, w2, w3, w8, ar1..ar3.
REGISTRY_SIZE = 8

# A one-seat room per side of the capacity story: the ACTIVE room that carries
# the assignment, and the STAFFING room whose last seat is already taken.
SOLO_ROOM = {"name": "Solo Room", "seat_capacity": 1}
SATELLITE_ROOM = {"name": "Satellite Room", "format": "REMOTE", "seat_capacity": 1}
OVERSIZED_MINI_ROOM = {
    "name": "Oversized Mini Room",
    "format": "MINI_ROOM",
    "seat_capacity": 6,
}

FULL_CLAIM_PCT = 100
LATE_CLAIM_PCT = 20

RELEASE_REASON = {"reason": "Writer left for a rival room."}
VOID_REASON = "Writer left the production."

# A season that can afford one one-hour teleplay's payable fee and no second script.
TIGHT_SCRIPT_FEE_BUDGET = 3000000
TELEPLAY_OFFSET_ONE_HOUR = 1750000
TELEPLAY_PAYABLE_ONE_HOUR = 1750000
STORY_OFFSET_ONE_HOUR = 750000
STORY_PAYABLE_ONE_HOUR = 750000


# --- Local helpers -----------------------------------------------------------

def _assert_error_envelope(response, expected_error_id, expected_status):
    """Validate one error response and the envelope shape §2.2 prescribes."""
    error = validate_error(response, expected_error_id, expected_status)
    body = response.json()
    assert set(body["data"]) == {"error_id", "message"}, (
        f"An error payload carries only error_id and message: {sorted(body['data'])}"
    )
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
        f"An error meta carries only the two request fields: {sorted(body['meta'])}"
    )
    return error


def _total(response):
    """The pre-pagination row count of one list response."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def _milestone_rows(api, params):
    """Milestone rows plus meta for one filter set."""
    return validate_paginated(api.list_milestones(STUDIO_EXECUTIVE_HEADERS, params))


def test_every_downstream_not_found_code_is_reachable_by_a_single_read(api):
    """Reads of the eight downstream resources answer their own 404 code, in the
    envelope shape §2.2 fixes, while a filtered list of unknown ids is an empty
    page rather than an error.

    PRD: "5. Every path-segment resource exists, left to right — otherwise the matching not-found code."

    PRD: "The following table lists every error identifier the API may return, with its HTTP status code."

    PRD: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    PRD: "Both parameters are echoed back in the `meta` object of the response alongside `total_count` — the number of records matching the filters before pagination is applied — and `has_more`, which is true when records remain beyond the current page."

    Design: Corner/errors/the_second_half_of_the_not_found_catalogue_is_triggerable_by_read
    """
    world = X.build_arbitration_world(api)
    review = X.seed_clearance_review(
        api, world["a1_id"], X.last_draft_milestone(world)["id"]
    )
    item = X.seed_clearance_item(api, review["id"])
    ledger = X.ledger_for_season(api, world["season_id"])
    assert ledger, "the canonical world must have written fee ledger entries"

    # The database is populated: every one of the eight resources reads back.
    validate_success(api.get_episode(world["ep1_id"], STUDIO_EXECUTIVE_HEADERS))
    validate_success(
        api.get_script_assignment(world["a1_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    validate_success(
        api.get_milestone(world["a1_milestone_ids"][0], STUDIO_EXECUTIVE_HEADERS)
    )
    validate_success(api.get_clearance_review(review["id"], LEGAL_COUNSEL_HEADERS))
    validate_success(api.get_clearance_item(item["id"], LEGAL_COUNSEL_HEADERS))
    validate_success(
        api.get_credit_submission(world["sb1_id"], GUILD_ADMINISTRATOR_HEADERS)
    )
    validate_success(
        api.get_credit_arbitration(
            world["arbitration_id"], GUILD_ADMINISTRATOR_HEADERS
        )
    )
    validate_success(
        api.get_fee_ledger_entry(ledger[0]["id"], STUDIO_EXECUTIVE_HEADERS)
    )

    # So a 404 on the same path is about the id, not about an empty service.
    probes = [
        (
            "episodes",
            api.get_episode(NON_EXISTENT_UUID, STUDIO_EXECUTIVE_HEADERS),
            ApiErrorId.EPISODE_NOT_FOUND,
        ),
        (
            "script-assignments",
            api.get_script_assignment(NON_EXISTENT_UUID, STUDIO_EXECUTIVE_HEADERS),
            ApiErrorId.ASSIGNMENT_NOT_FOUND,
        ),
        (
            "milestones",
            api.get_milestone(NON_EXISTENT_UUID, STUDIO_EXECUTIVE_HEADERS),
            ApiErrorId.MILESTONE_NOT_FOUND,
        ),
        (
            "clearance-reviews",
            api.get_clearance_review(NON_EXISTENT_UUID, LEGAL_COUNSEL_HEADERS),
            ApiErrorId.REVIEW_NOT_FOUND,
        ),
        (
            "clearance-items",
            api.get_clearance_item(NON_EXISTENT_UUID, LEGAL_COUNSEL_HEADERS),
            ApiErrorId.ITEM_NOT_FOUND,
        ),
        (
            "credit-submissions",
            api.get_credit_submission(NON_EXISTENT_UUID, GUILD_ADMINISTRATOR_HEADERS),
            ApiErrorId.SUBMISSION_NOT_FOUND,
        ),
        (
            "credit-arbitrations",
            api.get_credit_arbitration(NON_EXISTENT_UUID, GUILD_ADMINISTRATOR_HEADERS),
            ApiErrorId.ARBITRATION_NOT_FOUND,
        ),
        (
            "fee-ledger-entries",
            api.get_fee_ledger_entry(NON_EXISTENT_UUID, STUDIO_EXECUTIVE_HEADERS),
            ApiErrorId.LEDGER_ENTRY_NOT_FOUND,
        ),
    ]
    for resource, response, expected in probes:
        error = _assert_error_envelope(response, expected, 404)
        assert error["error_id"] == expected.value, (
            f"/{resource}/<unknown> must answer {expected.value}"
        )

    # A filter that matches nothing is not a not-found: it is an empty page.
    rows, meta = _milestone_rows(api, {"assignment_id": NON_EXISTENT_UUID})
    assert rows == [], f"An unmatched filter returns no rows: {rows}"
    A.assert_pagination_meta(meta, total_count=0, has_more=False, limit=10, offset=0)

    rows, meta = _milestone_rows(api, {"assignment_id": world["a1_id"]})
    assert meta["total_count"] == len(world["a1_milestone_ids"]), (
        "the same list filtered by a real assignment returns that chain: "
        f"{meta['total_count']} rows"
    )
    assert [row["id"] for row in rows] == world["a1_milestone_ids"], (
        "the milestone list walks the chain in sequence order"
    )


def test_every_uniqueness_and_capacity_ceiling_refuses_the_second_write(api):
    """The guild number, the episode number, the credit claim, the live
    assignment type, the last open seat and the mini-room capacity each refuse
    the second write, and none of the six refusals moves a counter.

    PRD: "Membership numbers are unique across the whole registry, and a second registration under a number already on file is rejected with `ERR_DUPLICATE_GUILD_MEMBER_ID`."

    PRD: "a 1-based integer that may not exceed the season's `episode_order` and is unique within the season, a second use being rejected with `ERR_DUPLICATE_EPISODE_NUMBER`"

    PRD: "one writer may file only one claim per episode: a second claim on the same episode is rejected with `ERR_DUPLICATE_SUBMISSION`."

    PRD: "an episode may hold at most one live assignment of any given type, so a create is rejected with `ERR_ASSIGNMENT_TYPE_CONFLICT` when another assignment of the same `assignment_type` on the same episode is in `DRAFTING`, `DELIVERED`, `IN_NOTES` or `APPROVED`."

    PRD: "Finally the room must have room — `open_seat_count` must be at least 1, otherwise `ERR_SEAT_CAPACITY_EXCEEDED`"

    PRD: "A mini room is a small room by definition: configuring or reconfiguring a `MINI_ROOM` with a capacity above 4 is rejected with `ERR_MINI_ROOM_SEAT_LIMIT`."

    PRD: "When a request violates more than one rule, the single error returned is the one with the lowest priority number in the precedence list of §2.11, and no partial state is ever persisted alongside an error."

    Design: Corner/errors/every_uniqueness_and_capacity_ceiling_rejects_the_second_write
    """
    # An ACTIVE one-seat room carrying an approved teleplay and one credit claim.
    world = X.build_staffing_room_world(api, room_overrides=dict(SOLO_ROOM))
    solo_seat = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
        episodic_guarantee_count=1,
    )
    X.accept_seat(api, solo_seat["id"], world["w1_id"])
    solo_room = X.activate_room(api, world["room_id"])
    A.assert_field_values(solo_room, status="ACTIVE", filled_seat_count=1, open_seat_count=0)

    episode = X.seed_episode(api, world["season_id"], 1)
    assignment = X.seed_assignment(
        api, episode["id"], world["w1_id"], world["sr_headers"], "TELEPLAY"
    )
    X.deliver_all(api, assignment["id"], world["w1_id"])
    assignment = X.approve_assignment(api, assignment["id"])
    A.assert_field_values(assignment, status="APPROVED", assignment_type="TELEPLAY")
    claim = X.seed_credit_submission(
        api, episode["id"], world["w1_id"], "WRITTEN_BY", FULL_CLAIM_PCT
    )

    # A second STAFFING room whose single seat is already taken by w2.
    satellite = X.seed_room(
        api, world["season_id"], world["sr_headers"], **dict(SATELLITE_ROOM)
    )
    satellite = X.open_room(api, satellite["id"], world["sr_headers"])
    satellite_seat = X.seed_seat(
        api,
        satellite["id"],
        world["w2_id"],
        world["sr_headers"],
        expected_room_version=satellite["version"],
        exclusivity="NON_EXCLUSIVE",
        episodic_guarantee_count=0,
    )
    X.accept_seat(api, satellite_seat["id"], world["w2_id"])
    satellite = X.read_room(api, satellite["id"])
    A.assert_field_values(
        satellite, status="STAFFING", seat_capacity=1, filled_seat_count=1, open_seat_count=0
    )
    satellite_version = satellite["version"]
    X.seed_window(api, world["w3_id"])

    episode_version_before = X.current_episode_version(api, episode["id"])
    committed_before = X.read_season(api, world["season_id"])["script_fee_committed_cents"]

    # 1. The guild membership number is unique across the whole registry.
    _assert_error_envelope(
        api.create_writer(
            F.build_writer(world["agreement_id"], "Wanda Cole Again", "GM-1001"),
            GUILD_ADMINISTRATOR_HEADERS,
        ),
        ApiErrorId.DUPLICATE_GUILD_MEMBER_ID,
        409,
    )
    assert _total(api.list_writers(GUILD_ADMINISTRATOR_HEADERS)) == REGISTRY_SIZE, (
        "the refused registration adds no writer"
    )

    # 2. The episode number is unique within the season. The reuse goes on UNIT_B
    #    so that production-unit turnaround — listed ahead of uniqueness inside
    #    precedence step 18 — has nothing to say about it.
    _assert_error_envelope(
        api.create_episode(
            world["season_id"],
            F.build_episode(1, production_unit="UNIT_B"),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        ApiErrorId.DUPLICATE_EPISODE_NUMBER,
        409,
    )
    assert _total(
        api.list_episodes(STUDIO_EXECUTIVE_HEADERS, {"season_id": world["season_id"]})
    ) == 1, "the refused episode is not ordered onto the season"

    # 3. One writer files one claim per episode.
    _assert_error_envelope(
        api.create_credit_submission(
            episode["id"],
            F.build_credit_submission(world["w1_id"], "TELEPLAY_BY", LATE_CLAIM_PCT),
            make_writer_headers(world["w1_id"]),
        ),
        ApiErrorId.DUPLICATE_SUBMISSION,
        409,
    )
    A.assert_field_values(
        X.read_submission(api, claim["id"]),
        claim_basis="WRITTEN_BY",
        claimed_contribution_pct=FULL_CLAIM_PCT,
    )

    # 4. An approved teleplay still blocks a second teleplay on that episode.
    _assert_error_envelope(
        api.create_script_assignment(
            episode["id"],
            F.build_script_assignment(
                world["w1_id"], episode_version_before, assignment_type="TELEPLAY"
            ),
            world["sr_headers"],
        ),
        ApiErrorId.ASSIGNMENT_TYPE_CONFLICT,
        409,
    )
    assert _total(
        api.list_script_assignments(
            STUDIO_EXECUTIVE_HEADERS, {"episode_id": episode["id"]}
        )
    ) == 1, "the refused assignment is not persisted"

    # 5. A full room has no seat left to offer.
    _assert_error_envelope(
        api.offer_seat(
            satellite["id"],
            F.build_seat_offer(
                world["w3_id"],
                satellite_version,
                level_at_hire="STAFF_WRITER",
                exclusivity="NON_EXCLUSIVE",
            ),
            world["sr_headers"],
        ),
        ApiErrorId.SEAT_CAPACITY_EXCEEDED,
        409,
    )
    A.assert_field_values(
        X.read_room(api, satellite["id"]),
        seat_capacity=1,
        filled_seat_count=1,
        open_seat_count=0,
        version=satellite_version,
    )
    assert _total(
        api.list_room_seats(STUDIO_EXECUTIVE_HEADERS, {"room_id": satellite["id"]})
    ) == 1, "the refused offer writes no seat row"

    # 6. A mini room may not be configured above four seats.
    _assert_error_envelope(
        api.create_room(
            world["season_id"],
            F.build_room(**dict(OVERSIZED_MINI_ROOM)),
            world["sr_headers"],
        ),
        ApiErrorId.MINI_ROOM_SEAT_LIMIT,
        422,
    )
    assert _total(
        api.list_rooms(STUDIO_EXECUTIVE_HEADERS, {"season_id": world["season_id"]})
    ) == 2, "the refused mini room is not configured"

    # Six refusals, and the episode and the season's money are untouched.
    A.assert_field_values(
        X.read_episode(api, episode["id"]),
        version=episode_version_before,
        credit_status="SUBMISSIONS_OPEN",
    )
    A.assert_cents(
        X.read_season(api, world["season_id"])["script_fee_committed_cents"],
        committed_before,
        "script_fee_committed_cents after six refusals",
    )


def test_the_credit_workflow_refuses_every_out_of_sequence_call(api):
    """Convening early, claiming late, seating an interested arbiter, convening
    twice and determining on two ballots are each refused, and the arbitration
    stays exactly where the third ballot left it.

    PRD: "The episode's `credit_status` must be `SUBMISSIONS_CLOSED`, otherwise `ERR_ARBITRATION_NOT_AVAILABLE`, and an episode may have at most one arbitration ever — a second is rejected with `ERR_ARBITRATION_ALREADY_EXISTS`."

    PRD: "The episode's `credit_status` must be `SUBMISSIONS_OPEN`, otherwise `ERR_SUBMISSION_WINDOW_CLOSED`, and one writer may file only one claim per episode"

    PRD: "an arbiter who holds a non-void script assignment on the episode, or who has filed any credit submission on it at all — eligible or not — disqualifies the panel with `ERR_ARBITER_IS_PARTICIPANT`, as do three ids that are not distinct."

    PRD: "`votes_cast_count` starts at 0, `vote_ledger` at an empty map, `leading_writer_id` and `determined_credit_string` at null, `concurrence_pct` at 0 and `outcome` at `NONE`."

    PRD: "The episode moves to `IN_ARBITRATION` and its `version` increments."

    PRD: "Called without `policy_override`, or with it false, all three ballots must be in: `votes_cast_count` below 3 is refused with `ERR_PANEL_INCOMPLETE`."

    Design: Corner/errors/the_credit_workflow_refuses_every_out_of_sequence_call
    """
    world = X.build_submissions_world(api)
    panel = F.build_arbitration(world["ar1_id"], world["ar2_id"], world["ar3_id"])

    # 1. Arbitration is unavailable while the submission window is still open.
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), credit_status="SUBMISSIONS_OPEN"
    )
    _assert_error_envelope(
        api.convene_credit_arbitration(
            world["ep1_id"], panel, GUILD_ADMINISTRATOR_HEADERS
        ),
        ApiErrorId.ARBITRATION_NOT_AVAILABLE,
        409,
    )

    closed = X.close_submissions(api, world["ep1_id"])
    A.assert_field_values(closed, credit_status="SUBMISSIONS_CLOSED")

    # 2. And a claim filed after the close is refused.
    _assert_error_envelope(
        api.create_credit_submission(
            world["ep1_id"],
            F.build_credit_submission(world["sr_id"], "STORY_BY", LATE_CLAIM_PCT),
            make_writer_headers(world["sr_id"]),
        ),
        ApiErrorId.SUBMISSION_WINDOW_CLOSED,
        409,
    )
    assert _total(api.list_credit_submissions(GUILD_ADMINISTRATOR_HEADERS)) == 2, (
        "the late claim is not persisted"
    )

    # 3. A claimant may not sit on the panel that judges their own claim.
    _assert_error_envelope(
        api.convene_credit_arbitration(
            world["ep1_id"],
            F.build_arbitration(world["ar1_id"], world["w1_id"], world["ar3_id"]),
            GUILD_ADMINISTRATOR_HEADERS,
        ),
        ApiErrorId.ARBITER_IS_PARTICIPANT,
        422,
    )
    assert _total(api.list_credit_arbitrations(GUILD_ADMINISTRATOR_HEADERS)) == 0, (
        "the disqualified panel writes no arbitration row"
    )

    # 4. The clean panel convenes exactly once.
    world = X.convene_panel(api, world)
    A.assert_field_values(
        world["arbitration"],
        status="STATEMENTS_OPEN",
        votes_cast_count=0,
        outcome="NONE",
        determined_credit_string=None,
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), credit_status="IN_ARBITRATION"
    )
    # The episode has left SUBMISSIONS_CLOSED for IN_ARBITRATION, and the
    # credit-status gate is a step-14 state check while the at-most-one rule is
    # step-18 uniqueness, so the state check reports first.
    _assert_error_envelope(
        api.convene_credit_arbitration(
            world["ep1_id"], panel, GUILD_ADMINISTRATOR_HEADERS
        ),
        ApiErrorId.ARBITRATION_NOT_AVAILABLE,
        409,
    )
    assert _total(api.list_credit_arbitrations(GUILD_ADMINISTRATOR_HEADERS)) == 1, (
        "an episode may have at most one arbitration ever"
    )

    # 5. Two ballots are not a panel: the determination is refused.
    X.cast_ballot(
        api,
        world["arbitration_id"],
        world["ar1_id"],
        {world["w1_id"]: 50, world["w2_id"]: 50},
    )
    X.cast_ballot(
        api,
        world["arbitration_id"],
        world["ar2_id"],
        {world["w1_id"]: 40, world["w2_id"]: 60},
    )
    _assert_error_envelope(
        api.determine_arbitration(world["arbitration_id"], GUILD_ADMINISTRATOR_HEADERS),
        ApiErrorId.PANEL_INCOMPLETE,
        409,
    )

    arbitration = X.read_arbitration(api, world["arbitration_id"])
    A.assert_field_values(
        arbitration,
        status="PANEL_VOTING",
        votes_cast_count=2,
        outcome="NONE",
        determined_credit_string=None,
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), credit_status="IN_ARBITRATION"
    )


def test_a_reassigned_script_refuses_delivery_and_an_unready_episode_refuses_the_lock(api):
    """Releasing the seat parks the script at REASSIGNMENT_PENDING, where the
    milestone gate is read before the assignment gate, the episode is too unready
    to lock, and only the void gets through.

    PRD: "Because the seat is no longer `CONFIRMED`, every script assignment held through that seat whose status is `DRAFTING`, `DELIVERED` or `IN_NOTES` moves to `REASSIGNMENT_PENDING`; the assignment keeps the seat reference it was created with, so the seat's guarantee counters are unaffected by the release, and the assignment's milestones keep their current statuses and due dates untouched."

    PRD: "The milestone must be in a deliverable status — `PENDING`, `LATE` or `NOTES_ISSUED` — otherwise `ERR_MILESTONE_NOT_DELIVERABLE`."

    PRD: "The owning assignment must be in `DRAFTING` or `IN_NOTES`, otherwise `ERR_ASSIGNMENT_NOT_DRAFTING`, which is what makes an approved or voided assignment permanently undeliverable."

    PRD: "First the episode's `script_readiness` must be `READY`, otherwise `ERR_EPISODE_NOT_READY`."

    PRD: "the assignment's `guarantee_slot_applied` is cleared to false with `guarantee_offset_cents` and `payable_fee_cents` both set to 0"

    PRD: "an episode at `IN_PROGRESS` falls back to `NOT_STARTED` when every one of its assignments is void"

    Design: Corner/errors/a_reassigned_script_refuses_delivery_and_an_unready_episode_refuses_the_lock
    """
    world = X.build_assignment_world(api)
    outline_id, first_draft_id = world["a1_milestone_ids"][0], world["a1_milestone_ids"][1]
    A.assert_field_values(X.read_assignment(api, world["a1_id"]), status="DRAFTING")

    delivered_outline = X.deliver_milestone(api, outline_id, world["w1_id"])
    A.assert_field_values(delivered_outline, status="DELIVERED", sequence_index=1)

    released = validate_success(
        api.release_seat(world["s1_id"], STUDIO_EXECUTIVE_HEADERS, dict(RELEASE_REASON))
    )
    A.assert_field_values(released, status="RELEASED")

    # The script is parked, and its chain is exactly where the release found it.
    parked = X.read_assignment(api, world["a1_id"])
    A.assert_field_values(
        parked, status="REASSIGNMENT_PENDING", room_seat_id=world["s1_id"]
    )
    first_draft = X.read_milestone(api, first_draft_id)
    A.assert_field_values(first_draft, status="PENDING", sequence_index=2)
    A.assert_instant(
        first_draft["due_date"],
        K.DUE_DATES_NOV_02["FIRST_DRAFT"],
        "first draft due date after the release",
    )
    A.assert_field_values(
        X.read_seat(api, world["s1_id"]),
        guarantee_slots_consumed=1,
        guarantee_slots_remaining=0,
    )

    # A deliverable milestone on a parked assignment fails on the assignment gate.
    _assert_error_envelope(
        api.deliver_milestone(first_draft_id, make_writer_headers(world["w1_id"])),
        ApiErrorId.ASSIGNMENT_NOT_DRAFTING,
        409,
    )
    # An already-delivered milestone fails on the milestone gate, read first.
    _assert_error_envelope(
        api.deliver_milestone(outline_id, make_writer_headers(world["w1_id"])),
        ApiErrorId.MILESTONE_NOT_DELIVERABLE,
        409,
    )

    # The episode never reached READY, so the lock is refused on the first gate.
    episode = X.read_episode(api, world["ep1_id"])
    A.assert_field_values(episode, script_readiness="IN_PROGRESS")
    _assert_error_envelope(
        api.lock_episode_for_production(world["ep1_id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.EPISODE_NOT_READY,
        409,
    )

    # The void is the one call that is available, and it unwinds the money.
    voided = validate_success(
        api.void_assignment(
            world["a1_id"], F.build_void(VOID_REASON), STUDIO_EXECUTIVE_HEADERS
        )
    )
    A.assert_field_values(voided, status="VOID", guarantee_slot_applied=False)
    A.assert_cents(voided["guarantee_offset_cents"], 0, "voided guarantee offset")
    A.assert_cents(voided["payable_fee_cents"], 0, "voided payable fee")
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), script_readiness="NOT_STARTED"
    )
    A.assert_field_values(
        X.read_seat(api, world["s1_id"]),
        guarantee_slots_consumed=0,
        guarantee_slots_remaining=1,
    )

    # And the pending milestone is now permanently undeliverable.
    _assert_error_envelope(
        api.deliver_milestone(first_draft_id, make_writer_headers(world["w1_id"])),
        ApiErrorId.ASSIGNMENT_NOT_DRAFTING,
        409,
    )
    A.assert_field_values(X.read_milestone(api, first_draft_id), status="PENDING")


def test_the_script_fee_budget_stops_the_assignment_that_would_cross_it(api):
    """A season with room for exactly one teleplay's payable fee refuses the next
    script, and the same script is admitted once the void has returned both the
    committed money and the guarantee slot.

    PRD: "The base multiplied by that share, rounded half up to whole cents, is the assignment's `gross_fee_cents`."

    PRD: "its `guarantee_offset_cents` becomes its gross fee multiplied by the agreement's guarantee offset fraction for the level recorded on the seat's `level_at_hire`, rounded half up to whole cents"

    PRD: "Under `FORWARD_COMMIT`, the candidates are the seat's assignments whose status is not `VOID`, ordered by `created_at` ascending; a slot is therefore committed at creation time, the earliest-created assignment wins the guarantee even if a later-created assignment is approved first, and approval performs no re-settlement at all."

    PRD: "Creating an assignment therefore appends a `SCRIPT_FEE_ACCRUAL` entry for the full gross and, when a slot applied at creation, a `GUARANTEE_OFFSET` entry for the negative offset."

    PRD: "The season's `script_fee_committed_cents` is then recomputed as the signed sum of every ledger entry of that season — it is never incremented in place."

    PRD: "The **script fee budget** is checked before any of this is persisted: the season's current `script_fee_committed_cents` plus the new assignment's `payable_fee_cents` must be at or below `script_fee_budget_cents`, and exceeding the ceiling is rejected with `ERR_SCRIPT_FEE_BUDGET_EXCEEDED`."

    PRD: "a single `FEE_REVERSAL` entry is appended whose `amount_cents` is the negation of the sum of every prior ledger entry of that assignment, which drives the assignment's own ledger contribution to exactly 0"

    PRD: "The season's `script_fee_committed_cents` is recomputed from the ledger — so a create followed by its void returns the season's committed figure to the value it held before the create — and the seat's guarantee counters are recounted, returning the freed slot to `guarantee_slots_remaining`."

    Design: Corner/errors/the_script_fee_budget_stops_the_assignment_that_would_cross_it
    """
    world = X.build_episode_world(
        api, season_overrides={"script_fee_budget_cents": TIGHT_SCRIPT_FEE_BUDGET}
    )
    season = X.read_season(api, world["season_id"])
    A.assert_field_values(season, guarantee_application_mode="FORWARD_COMMIT")
    A.assert_cents(
        season["script_fee_budget_cents"], TIGHT_SCRIPT_FEE_BUDGET, "script fee budget"
    )
    A.assert_cents(season["script_fee_committed_cents"], 0, "committed before any script")

    # The teleplay fits: 1,750,000 payable against a 3,000,000 ceiling.
    teleplay = X.seed_assignment(
        api, world["ep1_id"], world["w1_id"], world["sr_headers"], "TELEPLAY"
    )
    A.assert_assignment_settlement(
        teleplay,
        K.SCRIPT_FEE_ONE_HOUR["TELEPLAY"],
        True,
        TELEPLAY_OFFSET_ONE_HOUR,
        TELEPLAY_PAYABLE_ONE_HOUR,
    )
    entries = X.ledger_for_season(api, world["season_id"])
    assert A.entry_types(entries) == ["SCRIPT_FEE_ACCRUAL", "GUARANTEE_OFFSET"], (
        f"the create appends the accrual and its offset: {A.entry_types(entries)}"
    )
    A.assert_ledger_sum(entries, TELEPLAY_PAYABLE_ONE_HOUR)
    A.assert_cents(
        X.read_season(api, world["season_id"])["script_fee_committed_cents"],
        TELEPLAY_PAYABLE_ONE_HOUR,
        "committed after the teleplay",
    )

    # The story does not: w1's only slot is spent, so its full gross would cross.
    episode_version = X.current_episode_version(api, world["ep1_id"])
    _assert_error_envelope(
        api.create_script_assignment(
            world["ep1_id"],
            F.build_script_assignment(
                world["w1_id"], episode_version, assignment_type="STORY"
            ),
            world["sr_headers"],
        ),
        ApiErrorId.SCRIPT_FEE_BUDGET_EXCEEDED,
        409,
    )
    assert len(X.ledger_for_season(api, world["season_id"])) == 2, (
        "the refused assignment writes no ledger entry"
    )
    A.assert_cents(
        X.read_season(api, world["season_id"])["script_fee_committed_cents"],
        TELEPLAY_PAYABLE_ONE_HOUR,
        "committed after the refusal",
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), version=episode_version
    )

    # Voiding the teleplay returns the money and the slot.
    voided = validate_success(
        api.void_assignment(
            teleplay["id"], F.build_void(VOID_REASON), STUDIO_EXECUTIVE_HEADERS
        )
    )
    A.assert_field_values(voided, status="VOID", guarantee_slot_applied=False)
    A.assert_cents(voided["payable_fee_cents"], 0, "voided payable fee")
    entries = X.ledger_for_season(api, world["season_id"])
    assert len(entries) == 3, f"the void appends a single reversal: {A.entry_types(entries)}"
    reversal = A.find_by(entries, entry_type="FEE_REVERSAL")
    A.assert_cents(
        reversal["amount_cents"], -TELEPLAY_PAYABLE_ONE_HOUR, "fee reversal amount"
    )
    A.assert_ledger_sum(X.ledger_for_assignment(api, teleplay["id"]), 0)
    A.assert_cents(
        X.read_season(api, world["season_id"])["script_fee_committed_cents"],
        0,
        "committed after the void",
    )

    # And the same story is now admitted, carrying the freed slot.
    story = X.seed_assignment(
        api, world["ep1_id"], world["w1_id"], world["sr_headers"], "STORY"
    )
    A.assert_assignment_settlement(
        story,
        K.SCRIPT_FEE_ONE_HOUR["STORY"],
        True,
        STORY_OFFSET_ONE_HOUR,
        STORY_PAYABLE_ONE_HOUR,
    )
    A.assert_cents(
        X.read_season(api, world["season_id"])["script_fee_committed_cents"],
        STORY_PAYABLE_ONE_HOUR,
        "committed after the story",
    )
    A.assert_field_values(
        X.read_seat(api, world["s1_id"]),
        guarantee_slots_consumed=1,
        guarantee_slots_remaining=0,
    )
