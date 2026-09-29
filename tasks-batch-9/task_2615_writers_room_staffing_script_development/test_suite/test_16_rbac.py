"""Role and identity coverage: header failures, cross-role refusals, the two
entity-backed roles, segregation of duties, panel membership and the operations
the contract genuinely shares.

Every test in this module translates exactly one instance of
SCAFFOLD_CORNER_DESIGN.yaml section `rbac`.
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
    NO_HEADERS,
    STUDIO_EXECUTIVE_HEADERS,
    headers_empty_role,
    headers_missing_role,
    make_headers,
    make_showrunner_headers,
    make_writer_headers,
)

# --- Module landmarks --------------------------------------------------------

# A real television job title that is not one of the five declared roles.
PRODUCER_ROLE = "Producer"

# build_registry seeds exactly these eight writers: sr, w1, w2, w3, w8, ar1..ar3.
REGISTRY_SIZE = 8

PIRATE_SEASON = {
    "title": "Pirate Season",
    "episode_order": 6,
    "production_start_date": "2027-11-02T00:00:00Z",
    "staffing_window_start": "2027-08-01T00:00:00Z",
    "staffing_window_end": "2027-09-30T00:00:00Z",
}
SECOND_ROOM = {"name": "Second Room", "format": "REMOTE", "seat_capacity": 2}

SHOWRUNNER_SEAT = {
    "level_at_hire": "PRODUCER",
    "offered_weekly_compensation_cents": 1000000,
    "exclusivity": "NON_EXCLUSIVE",
    "episodic_guarantee_count": 1,
}

NOTES = "Tighten the cold open."
CLOCK_AUGUST_02 = "2026-08-02T00:00:00Z"
CLOCK_AUGUST_03 = "2026-08-03T00:00:00Z"

# The canonical 60 / 30 claims normalise to this provisional split at close.
PROVISIONAL_SPLIT = {"w1": 67, "w2": 33}
# a1 writes an accrual and its guarantee offset; a2's seat has no slot, so a2
# writes only its accrual.
CANONICAL_LEDGER_ROWS = 3


# --- Local helpers -----------------------------------------------------------

def _assert_error_envelope(response, expected_error_id, expected_status):
    """Validate one error response and the envelope shape §2.2 prescribes."""
    error = validate_error(response, expected_error_id, expected_status)
    body = response.json()
    assert set(body["data"]) == {"error_id", "message"}, (
        f"An error payload carries only error_id and message: {sorted(body['data'])}"
    )
    return error


def _total(response):
    """The pre-pagination row count of one list response."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def test_missing_and_unknown_role_headers_are_read_before_any_state_check(api):
    """An absent header, an empty header and an unrecognised role are all 401s
    taken before the endpoint's own state gate, and none of them touches the room
    the same call would legitimately move.

    PRD: "Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the caller acts."

    PRD: "If either header is absent or empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

    PRD: "If `X-User-Role` is present but is not one of the five roles the system recognises — `StudioExecutive`, `Showrunner`, `Writer`, `GuildAdministrator`, `LegalCounsel` — the request is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401)."

    PRD: "1. Both authentication headers present and non-empty — otherwise `ERR_MISSING_AUTH_HEADERS`."

    PRD: "2. `X-User-Role` is one of the five recognised roles — otherwise `ERR_UNKNOWN_ROLE`."

    Design: Corner/rbac/every_write_rejects_missing_auth_headers_and_unknown_roles_before_any_state_check
    """
    world = X.build_season_world(api)
    room = X.seed_room(api, world["season_id"], world["sr_headers"])
    A.assert_field_values(room, status="OPEN", version=1)

    # An omitted role header and an empty one are both absent, not unknown.
    _assert_error_envelope(
        api.open_staffing(room["id"], headers_missing_role(world["sr_id"])),
        ApiErrorId.MISSING_AUTH_HEADERS,
        401,
    )
    _assert_error_envelope(
        api.open_staffing(room["id"], headers_empty_role(world["sr_id"])),
        ApiErrorId.MISSING_AUTH_HEADERS,
        401,
    )

    # A real job title outside the five-role vocabulary is unknown, not absent.
    _assert_error_envelope(
        api.open_staffing(room["id"], make_headers(PRODUCER_ROLE, world["sr_id"])),
        ApiErrorId.UNKNOWN_ROLE,
        401,
    )

    # Activation would be the room's own state failure once authenticated; the
    # header check is taken first, so the answer is still 401.
    _assert_error_envelope(
        api.activate_room(room["id"], NO_HEADERS),
        ApiErrorId.MISSING_AUTH_HEADERS,
        401,
    )
    # Reads are authenticated too.
    _assert_error_envelope(
        api.get_room(room["id"], NO_HEADERS), ApiErrorId.MISSING_AUTH_HEADERS, 401
    )

    A.assert_field_values(X.read_room(api, room["id"]), status="OPEN", version=1)

    # The endpoint was reachable all along.
    opened = validate_success(api.open_staffing(room["id"], world["sr_headers"]))
    A.assert_field_values(opened, status="STAFFING", version=2)


def test_cross_role_calls_are_forbidden_on_every_exclusive_operation(api):
    """Each exclusive operation refuses every other role symmetrically — the
    studio cannot open staffing, the showrunner cannot reconfigure, the guild
    cannot create a season, and the fee ledger is not even readable by the
    showrunner — and none of the eight refusals writes anything.

    PRD: "A recognised role that is not listed for the endpoint being called is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403); §4 is the authoritative table of which roles may call what."

    PRD: "3. The acting role is permitted on the endpoint — otherwise `ERR_ROLE_NOT_PERMITTED`."

    PRD: "they alone create seasons, reschedule a season's production start, order episodes, reconfigure a room's format and duration commitment, and activate a room"

    PRD: "they alone open a room for staffing, offer seats, withdraw a seat offer, create script assignments and issue notes on a delivered script"

    PRD: "they alone accept or decline a seat offer, deliver a milestone, submit a credit claim, and cast an arbitration ballot when serving on a panel"

    PRD: "they alone register a guild agreement, register a writer, award episodic credits, convene a credit arbitration panel and apply an arbitration determination or policy override"

    PRD: "opening a clearance review, adding clearance items, deciding items and granting waivers are theirs exclusively"

    PRD: "| GET | `/fee-ledger-entries` | List fee ledger entries, filterable by season, assignment, writer and entry type; the conservation invariant is audited against this list. | `StudioExecutive`, `GuildAdministrator` |"

    Design: Corner/rbac/cross_role_calls_are_forbidden_on_every_exclusive_operation
    """
    world = X.build_delivered_assignment_world(api)
    room_version = X.current_room_version(api, world["room_id"])
    episode_version = X.current_episode_version(api, world["ep1_id"])
    last_milestone_id = world["a1_milestone_ids"][-1]

    # 1. Opening a room for staffing is the showrunner's alone.
    _assert_error_envelope(
        api.open_staffing(world["room_id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    # 2. Reconfiguring it is the studio's alone.
    _assert_error_envelope(
        api.reconfigure_room(
            world["room_id"], F.build_reconfigure(room_version), world["sr_headers"]
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    # 3. Seasons are created by the studio, not by the guild that owns the card.
    _assert_error_envelope(
        api.create_season(
            F.build_season(world["agreement_id"], world["sr_id"], **PIRATE_SEASON),
            GUILD_ADMINISTRATOR_HEADERS,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    # 4. Writers are registered by the guild, not by the showrunner who hires them.
    _assert_error_envelope(
        api.create_writer(
            F.build_writer(world["agreement_id"], "Unauthorised Hire", "GM-9001"),
            world["sr_headers"],
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    # 5. Clearance is legal counsel's end to end.
    _assert_error_envelope(
        api.create_clearance_review(
            world["a1_id"],
            F.build_clearance_review(last_milestone_id),
            world["sr_headers"],
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    # 6. Delivery belongs to the writer, even against their own showrunner.
    _assert_error_envelope(
        api.deliver_milestone(last_milestone_id, world["sr_headers"]),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    # 7. Assignments are created by the showrunner, not by the studio.
    _assert_error_envelope(
        api.create_script_assignment(
            world["ep1_id"],
            F.build_script_assignment(
                world["w2_id"], episode_version, assignment_type="STORY"
            ),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    # 8. And the fee ledger is a read the showrunner does not have at all.
    _assert_error_envelope(
        api.list_fee_ledger_entries(
            world["sr_headers"], {"season_id": world["season_id"]}
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    assert _total(
        api.list_fee_ledger_entries(
            GUILD_ADMINISTRATOR_HEADERS, {"season_id": world["season_id"]}
        )
    ) > 0, "the same list is readable by the guild administrator"

    # Eight refusals and nothing moved.
    A.assert_field_values(
        X.read_room(api, world["room_id"]), status="ACTIVE", version=room_version
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), version=episode_version
    )
    assert _total(api.list_seasons(STUDIO_EXECUTIVE_HEADERS)) == 1, (
        "the refused season is not created"
    )
    assert _total(api.list_writers(GUILD_ADMINISTRATOR_HEADERS)) == REGISTRY_SIZE, (
        "the refused writer is not registered"
    )
    assert _total(
        api.list_clearance_reviews(LEGAL_COUNSEL_HEADERS, {"assignment_id": world["a1_id"]})
    ) == 0, "the refused clearance review is not opened"
    assert _total(
        api.list_script_assignments(
            STUDIO_EXECUTIVE_HEADERS, {"episode_id": world["ep1_id"]}
        )
    ) == 1, "the refused assignment is not created"
    A.assert_field_values(X.read_milestone(api, last_milestone_id), status="DELIVERED")


def test_an_entity_backed_role_must_resolve_to_a_writer_and_cannot_act_for_another(api):
    """Three different 403 codes on the same status: an acting id that is no
    writer at all, a real writer reaching for someone else's seat or milestone,
    and a showrunner-eligible writer who does not run this season.

    PRD: "For both of these roles, an `X-User-ID` that is not the id of an existing `Writer` is rejected with `ERR_ACTING_WRITER_NOT_FOUND` (HTTP 403)."

    PRD: "4. For endpoints open to the entity-backed roles `Writer` and `Showrunner`, `X-User-ID` is an existing writer's id — otherwise `ERR_ACTING_WRITER_NOT_FOUND`."

    PRD: "A `Writer` acting on a seat must be the seat's writer, a `Writer` delivering a milestone must be the writer of the milestone's assignment, and a `Writer` submitting a credit claim must supply their own id as the claim's writer; any of these mismatches is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    PRD: "A `Showrunner` acting on an episode of a season must be that season's `showrunner_writer_id`, otherwise the request is rejected with `ERR_NOT_SEASON_SHOWRUNNER` (HTTP 403)."

    PRD: "The winning window moves to `CONSUMED` and records the seat in its `consumed_by_seat_id`, while the seat records the window in its `consumed_window_id` — a two-way link that makes the later release reversible."

    PRD: "The system resolves the assignment's `room_seat_id` by filtering to seats of the named writer whose status is `CONFIRMED` in a writers room belonging to this episode's season whose own status is `ACTIVE`"

    PRD: "Then `days_late` is frozen at the number of whole days by which the UTC calendar date of `delivered_at` exceeds the UTC calendar date of `due_date`, floored at 0 — an on-time or early delivery is 0."

    Design: Corner/rbac/an_entity_backed_role_must_resolve_to_a_writer_and_cannot_act_for_another
    """
    # One ACTIVE room holding w2's confirmed seat, and a sibling STAFFING room
    # holding an offer w1 has not answered yet.
    world = X.build_staffing_room_world(api)
    confirmed_seat = X.seed_seat(
        api,
        world["room_id"],
        world["w2_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
        exclusivity="NON_EXCLUSIVE",
        episodic_guarantee_count=1,
    )
    X.accept_seat(api, confirmed_seat["id"], world["w2_id"])
    X.activate_room(api, world["room_id"])

    sibling = X.seed_room(api, world["season_id"], world["sr_headers"], **SECOND_ROOM)
    sibling = X.open_room(api, sibling["id"], world["sr_headers"])
    offered_seat = X.seed_seat(
        api,
        sibling["id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=sibling["version"],
    )
    A.assert_field_values(
        offered_seat, status="OFFERED", writer_id=world["w1_id"], consumed_window_id=None
    )

    episode = X.seed_episode(api, world["season_id"], 1)
    stranger_showrunner = X.seed_writer(
        api,
        world["agreement_id"],
        "Tova Bright",
        "GM-SHOW2",
        career_episodic_credits=20,
        is_showrunner_eligible=True,
    )

    # 1. An acting id that resolves to no writer never reaches ownership.
    _assert_error_envelope(
        api.accept_seat(offered_seat["id"], make_writer_headers(NON_EXISTENT_UUID)),
        ApiErrorId.ACTING_WRITER_NOT_FOUND,
        403,
    )
    # 2. A real writer, seated elsewhere, is still not this seat's owner.
    _assert_error_envelope(
        api.accept_seat(offered_seat["id"], make_writer_headers(world["w2_id"])),
        ApiErrorId.NOT_RESOURCE_OWNER,
        403,
    )
    A.assert_field_values(
        X.read_seat(api, offered_seat["id"]), status="OFFERED", consumed_window_id=None
    )
    A.assert_field_values(
        X.read_window(api, world["aw1_id"]), status="OPEN", consumed_by_seat_id=None
    )

    # 3. A showrunner-eligible writer who runs no season may not staff this one.
    episode_version = episode["version"]
    _assert_error_envelope(
        api.create_script_assignment(
            episode["id"],
            F.build_script_assignment(
                world["w2_id"], episode_version, assignment_type="STORY"
            ),
            make_showrunner_headers(stranger_showrunner["id"]),
        ),
        ApiErrorId.NOT_SEASON_SHOWRUNNER,
        403,
    )

    # 4. The same call from this season's showrunner lands on w2's confirmed seat.
    assignment = X.seed_assignment(
        api,
        episode["id"],
        world["w2_id"],
        world["sr_headers"],
        "STORY",
        expected_episode_version=episode_version,
    )
    A.assert_field_values(
        assignment, writer_id=world["w2_id"], room_seat_id=confirmed_seat["id"]
    )

    # 5. Delivery is the assignment writer's alone, and lands on time.
    milestones = X.milestones_of(api, assignment["id"])
    outline_id = milestones[0]["id"]
    _assert_error_envelope(
        api.deliver_milestone(outline_id, make_writer_headers(world["w1_id"])),
        ApiErrorId.NOT_RESOURCE_OWNER,
        403,
    )
    A.assert_field_values(X.read_milestone(api, outline_id), status="PENDING")

    delivered = X.deliver_milestone(api, outline_id, world["w2_id"])
    A.assert_field_values(delivered, status="DELIVERED", days_late=0)
    A.assert_instant(
        delivered["due_date"], K.DUE_DATES_NOV_02["OUTLINE"], "outline due date"
    )
    A.assert_instant(delivered["delivered_at"], K.CLOCK_EPOCH, "delivered_at")


def test_a_showrunner_may_not_approve_their_own_script_but_the_studio_may(api):
    """Self-approval is refused by acting identity rather than by role: the
    showrunner keeps every other authority over their own script, and the studio
    executive signs it off, with `approved_by_role` recording which path ran.

    PRD: "A `Showrunner` may not approve a script assignment they authored — that approval must come from a `StudioExecutive` — and the attempt is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403)."

    PRD: "and the actor must not be the assignment's own writer, otherwise `ERR_SELF_APPROVAL_FORBIDDEN` — a showrunner who has written the script must hand the approval to a studio executive, who is under no such restriction."

    PRD: "Notes move the assignment `DELIVERED → IN_NOTES` and increment `revision_round` by one, and every milestone of the assignment currently in `DELIVERED` becomes `NOTES_ISSUED`."

    PRD: "the assignment must be in `DELIVERED` (otherwise `ERR_ASSIGNMENT_NOT_DELIVERED`) with every one of its milestones in `DELIVERED` or `NOTES_ISSUED`"

    PRD: "Approval sets the assignment to `APPROVED`, stamps `approved_at` from the logical clock, and records `approved_by_role` as `SHOWRUNNER` or `STUDIO_EXECUTIVE` so the audit trail shows which side of the duty split signed off."

    PRD: "Every milestone of the assignment becomes `ACCEPTED`."

    PRD: "When the approved `assignment_type` is `TELEPLAY` or `STORY_AND_TELEPLAY`, the episode's `approved_teleplay_assignment_id` is set to this assignment and its `script_readiness` moves `IN_PROGRESS → READY`; approving a `STORY`, `REWRITE` or `PRODUCTION_POLISH` does neither."

    PRD: "Independently of readiness, the episode's `credit_status` moves `PENDING → SUBMISSIONS_OPEN` on the episode's *first* approved assignment of any type — a story approval is enough to open the credit window."

    Design: Corner/rbac/a_showrunner_may_not_approve_their_own_script_but_the_studio_may
    """
    # The showrunner takes a seat in their own room and writes the teleplay.
    world = X.build_staffing_room_world(api)
    X.seed_window(api, world["sr_id"], "NON_EXCLUSIVE")
    showrunner_seat = X.seed_seat(
        api,
        world["room_id"],
        world["sr_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
        **SHOWRUNNER_SEAT,
    )
    X.accept_seat(api, showrunner_seat["id"], world["sr_id"])
    X.activate_room(api, world["room_id"])
    episode = X.seed_episode(api, world["season_id"], 1)
    assignment = X.seed_assignment(
        api, episode["id"], world["sr_id"], world["sr_headers"], "TELEPLAY"
    )
    milestone_ids = [m["id"] for m in X.milestones_of(api, assignment["id"])]
    X.deliver_all(api, assignment["id"], world["sr_id"])

    before = X.read_assignment(api, assignment["id"])
    A.assert_field_values(before, status="DELIVERED", writer_id=world["sr_id"])
    A.assert_field_values(
        X.read_episode(api, episode["id"]),
        script_readiness="IN_PROGRESS",
        credit_status="PENDING",
    )

    # 1. The author cannot sign off their own script.
    _assert_error_envelope(
        api.approve_assignment(assignment["id"], world["sr_headers"]),
        ApiErrorId.SELF_APPROVAL_FORBIDDEN,
        403,
    )
    refused = X.read_assignment(api, assignment["id"])
    A.assert_field_values(
        refused, status="DELIVERED", approved_by_role=None, version=before["version"]
    )
    for milestone_id in milestone_ids:
        A.assert_field_values(X.read_milestone(api, milestone_id), status="DELIVERED")
    A.assert_field_values(
        X.read_episode(api, episode["id"]),
        script_readiness="IN_PROGRESS",
        credit_status="PENDING",
    )

    # 2. Every other authority over that script is untouched.
    in_notes = validate_success(
        api.issue_notes(assignment["id"], F.build_notes(NOTES), world["sr_headers"])
    )
    A.assert_field_values(in_notes, status="IN_NOTES", revision_round=1)
    for milestone_id in milestone_ids:
        A.assert_field_values(
            X.read_milestone(api, milestone_id), status="NOTES_ISSUED"
        )

    # 3. The two gates are independent: the studio must now wait for redelivery.
    _assert_error_envelope(
        api.approve_assignment(assignment["id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.ASSIGNMENT_NOT_DELIVERED,
        409,
    )

    # 4. One redelivery is enough, and then the studio may sign off.
    redelivered = X.deliver_milestone(api, milestone_ids[0], world["sr_id"])
    A.assert_field_values(redelivered, status="DELIVERED")
    A.assert_field_values(X.read_assignment(api, assignment["id"]), status="DELIVERED")

    approved = validate_success(
        api.approve_assignment(assignment["id"], STUDIO_EXECUTIVE_HEADERS)
    )
    A.assert_field_values(
        approved, status="APPROVED", approved_by_role="STUDIO_EXECUTIVE"
    )
    A.assert_instant(approved["approved_at"], K.CLOCK_EPOCH, "approved_at")
    for milestone_id in milestone_ids:
        A.assert_field_values(X.read_milestone(api, milestone_id), status="ACCEPTED")
    A.assert_field_values(
        X.read_episode(api, episode["id"]),
        script_readiness="READY",
        credit_status="SUBMISSIONS_OPEN",
        approved_teleplay_assignment_id=assignment["id"],
    )


def test_only_a_seated_arbiter_may_cast_a_ballot(api):
    """The ballot endpoint is open to the Writer role, so membership of the panel
    is decided per arbitration: a participant, an unrelated writer and the season
    showrunner are all refused, and only a seated arbiter moves the arbitration.

    PRD: "A writer casting an arbitration ballot who is not named on that arbitration's panel is rejected with `ERR_ARBITER_NOT_ON_PANEL` (HTTP 403)."

    PRD: "Ballots are cast by the arbiters themselves, acting as writers. The acting id must appear in `arbiter_writer_ids`, otherwise `ERR_ARBITER_NOT_ON_PANEL`"

    PRD: "`votes_cast_count` starts at 0, `vote_ledger` at an empty map, `leading_writer_id` and `determined_credit_string` at null, `concurrence_pct` at 0 and `outcome` at `NONE`."

    PRD: "The first ballot moves the arbitration `STATEMENTS_OPEN → PANEL_VOTING`; the second and third are self-loops that leave it in `PANEL_VOTING`."

    PRD: "Each ballot is recorded in `vote_ledger` under the arbiter's id, `votes_cast_count` increments, and two figures are recomputed over the ballots cast so far."

    Design: Corner/rbac/only_a_seated_arbiter_may_cast_a_ballot
    """
    world = X.build_arbitration_world(api)
    A.assert_field_values(
        X.read_arbitration(api, world["arbitration_id"]),
        status="STATEMENTS_OPEN",
        votes_cast_count=0,
        vote_ledger={},
    )
    even_split = {world["w1_id"]: 50, world["w2_id"]: 50}

    # A participant is exactly who may not judge the claim.
    _assert_error_envelope(
        api.cast_arbitration_vote(
            world["arbitration_id"],
            F.build_ballot({world["w1_id"]: 80, world["w2_id"]: 20}),
            make_writer_headers(world["w1_id"]),
        ),
        ApiErrorId.ARBITER_NOT_ON_PANEL,
        403,
    )
    # An unrelated staffed writer is not on the panel either.
    _assert_error_envelope(
        api.cast_arbitration_vote(
            world["arbitration_id"],
            F.build_ballot(dict(even_split)),
            make_writer_headers(world["w3_id"]),
        ),
        ApiErrorId.ARBITER_NOT_ON_PANEL,
        403,
    )
    # And no seniority bypasses the panel list.
    _assert_error_envelope(
        api.cast_arbitration_vote(
            world["arbitration_id"],
            F.build_ballot(dict(even_split)),
            make_writer_headers(world["sr_id"]),
        ),
        ApiErrorId.ARBITER_NOT_ON_PANEL,
        403,
    )
    A.assert_field_values(
        X.read_arbitration(api, world["arbitration_id"]),
        status="STATEMENTS_OPEN",
        votes_cast_count=0,
        vote_ledger={},
        outcome="NONE",
    )

    # The seated arbiter's ballot is the one that lands.
    voted = X.cast_ballot(
        api, world["arbitration_id"], world["ar1_id"], dict(even_split)
    )
    A.assert_field_values(voted, status="PANEL_VOTING", votes_cast_count=1)
    assert list(voted["vote_ledger"]) == [world["ar1_id"]], (
        f"the ledger is keyed by the arbiter who voted: {voted['vote_ledger']}"
    )
    assert voted["vote_ledger"][world["ar1_id"]] == even_split, (
        f"the ballot is recorded as cast: {voted['vote_ledger']}"
    )


def test_shared_operations_are_open_to_every_role_that_declares_them(api):
    """The clock answers all five roles, the guild may declare a window for a
    writer and close the credit window without being the showrunner, and the
    showrunner wraps a room exactly as the studio would — while the fee ledger
    stays closed to the showrunner.

    PRD: "All five roles may set the logical clock."

    PRD: "| POST | `/_clock/set_current_utc` | Set the server's logical UTC clock, which every deadline, window and lateness rule reads. Before any call to this endpoint the logical clock reads exactly 2026-08-01T00:00:00Z; it never falls back to real wall-clock time. | `StudioExecutive`, `Showrunner`, `Writer`, `GuildAdministrator`, `LegalCounsel` |"

    PRD: "| POST | `/writers/{writer_id}/availability-windows` | Declare a window in which the writer is available for a room commitment. | `Writer`, `GuildAdministrator` |"

    PRD: "they may also declare an availability window on a writer's behalf, close a credit submission window, and read agreements, writers, seasons, rooms, seats, episodes, assignments, milestones, credit records and the fee ledger."

    PRD: "Closing the window belongs to the season's showrunner or to a guild administrator."

    PRD: "With at least one eligible submission, provisional shares are computed by the normalisation procedure below with each writer's weight taken from their own `claimed_contribution_pct`."

    PRD: "Wrapping ends the room's life and is available to a showrunner or a studio executive."

    PRD: "The room becomes `WRAPPED`, which is terminal, and every seat of the room still in `CONFIRMED` status is released as part of the same call"

    PRD: "| GET | `/fee-ledger-entries` | List fee ledger entries, filterable by season, assignment, writer and entry type; the conservation invariant is audited against this list. | `StudioExecutive`, `GuildAdministrator` |"

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    world = X.build_submissions_world(api)

    # 1. The clock is shared by all five roles: an opaque one and a writer here.
    validate_success(api.set_clock(CLOCK_AUGUST_02, LEGAL_COUNSEL_HEADERS))
    validate_success(
        api.set_clock(CLOCK_AUGUST_03, make_writer_headers(world["w1_id"]))
    )

    # 2. The guild may declare a window on a writer's own behalf.
    window = validate_success(
        api.create_availability_window(
            world["w3_id"],
            F.build_availability_window(commitment_type="NON_EXCLUSIVE"),
            GUILD_ADMINISTRATOR_HEADERS,
        ),
        expected_status=201,
    )
    A.assert_field_values(
        window, writer_id=world["w3_id"], status="OPEN", commitment_type="NON_EXCLUSIVE"
    )
    A.assert_instant(window["start_date"], K.WINDOW_START_DATE, "declared window start")
    A.assert_instant(window["end_date"], K.WINDOW_END_DATE, "declared window end")

    # 3. The guild closes the credit window although it is not the showrunner.
    closed = validate_success(
        api.close_credit_submissions(world["ep1_id"], GUILD_ADMINISTRATOR_HEADERS)
    )
    A.assert_field_values(closed, credit_status="SUBMISSIONS_CLOSED")
    assert closed["provisional_credit_shares"] == {
        world["w1_id"]: PROVISIONAL_SPLIT["w1"],
        world["w2_id"]: PROVISIONAL_SPLIT["w2"],
    }, f"claims of 60 and 30 normalise to 67 / 33: {closed['provisional_credit_shares']}"

    # 4. The fee ledger remains a two-role read.
    assert _total(
        api.list_fee_ledger_entries(
            GUILD_ADMINISTRATOR_HEADERS, {"season_id": world["season_id"]}
        )
    ) == CANONICAL_LEDGER_ROWS, "the guild administrator reads the whole ledger"
    assert _total(
        api.list_fee_ledger_entries(
            STUDIO_EXECUTIVE_HEADERS, {"season_id": world["season_id"]}
        )
    ) == CANONICAL_LEDGER_ROWS, "so does the studio executive"
    _assert_error_envelope(
        api.list_fee_ledger_entries(
            world["sr_headers"], {"season_id": world["season_id"]}
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )

    # 5. And the showrunner wraps the room the studio could have wrapped.
    wrapped = validate_success(api.wrap_room(world["room_id"], world["sr_headers"]))
    A.assert_field_values(wrapped, status="WRAPPED")
    A.assert_field_values(X.read_seat(api, world["s1_id"]), status="RELEASED")
    A.assert_field_values(X.read_seat(api, world["s2_id"]), status="RELEASED")
