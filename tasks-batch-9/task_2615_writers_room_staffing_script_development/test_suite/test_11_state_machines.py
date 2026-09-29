"""Every declared lifecycle: initial states, legal walks, refusals and cascades.

One test per breadth instance of the corner design's `state_machines` section.
The nine machines are exercised through the endpoints that own them, and each
refusal is checked to have left the target row exactly where it was.
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
from test_helpers.test_users import (
    LEGAL_COUNSEL_HEADERS,
    STUDIO_EXECUTIVE_HEADERS,
    make_writer_headers,
)

WITHDRAW_REASON = {"reason": "Offer withdrawn so the room can be activated."}
DECLINE_REASON = {"reason": "The writer took another room."}
RELEASE_REASON = {"reason": "Attempt to release a declined seat."}

SATELLITE_ROOM = {"name": "Satellite Room", "format": "REMOTE", "seat_capacity": 2}


def _commitment(api, season_id):
    """The season's live weekly staffing commitment."""
    return X.read_season(api, season_id)["staffing_commitment_weekly_cents"]


def _seat_statuses(api, room_id):
    """Every seat of one room, as an id-to-status map."""
    rows, _ = validate_paginated(
        api.list_room_seats(STUDIO_EXECUTIVE_HEADERS, {"room_id": room_id, "limit": 100})
    )
    return {row["id"]: row["status"] for row in rows}


def test_every_state_machine_starts_in_its_own_declared_initial_state(api):
    """Nine machines, nine initial states, none borrowing another's.

    PRD: "A new room is `OPEN` and empty."

    PRD: "Every window is created `OPEN` with no consuming seat, so its `consumed_by_seat_id` is null; it becomes `CONSUMED` only when a seat acceptance claims it, and returns to `OPEN` when that seat is released."

    PRD: "A surviving offer creates the seat in `OFFERED` status with all four compensation figures and the prorated commitment computed, `guarantee_slots_consumed` at 0 and `guarantee_slots_remaining` equal to the seat's `episodic_guarantee_count`, `confirmed_at` and `consumed_window_id` both null."

    PRD: "A new episode starts at the bottom of all three of its state dimensions: `script_readiness` is `NOT_STARTED`, `credit_status` is `PENDING`, and `clearance_posture` is `PENDING`."

    PRD: "The assignment is created in `DRAFTING`, its `revision_round` at 0, its `approved_at` and `approved_by_role` null, and its `late_milestone_count` at 0."

    PRD: "Each milestone is numbered by `sequence_index` starting at 1 in that chain order, copies the matching due-date field into its own `due_date`, and starts `PENDING` — or `LATE` immediately, if the logical clock has already passed that deadline at the moment the assignment is created."

    PRD: "A new review starts with `posture` at `PENDING`, `risk_score` 0, `item_count` 0, `decided_item_count` 0, `legal_waiver_granted` false and `waiver_memo` null, and it sets the episode's `clearance_posture` to `PENDING`, which is also where a fresh episode already sits."

    PRD: "A new item's `decision` is `SUBMITTED`, its `conditional_note` is null, and its `risk_weight` is 0 — an undecided item carries no risk weight even though its type already implies one."

    Design: Corner/state_machines/every_state_machine_starts_in_its_own_declared_initial_state
    """
    world = X.build_staffing_room_world(api)

    second_room = validate_success(
        api.create_room(
            world["season_id"], F.build_room(**SATELLITE_ROOM), world["sr_headers"]
        ),
        expected_status=201,
    )
    A.assert_field_values(
        second_room, status="OPEN", version=1, open_seat_count=2, filled_seat_count=0
    )

    A.assert_field_values(
        X.read_window(api, world["aw1_id"]), status="OPEN", consumed_by_seat_id=None
    )

    seat = validate_success(
        api.offer_seat(
            world["room_id"],
            F.build_seat_offer(world["w1_id"], world["room_version"]),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_field_values(
        seat,
        status="OFFERED",
        confirmed_at=None,
        consumed_window_id=None,
        guarantee_slots_consumed=0,
    )
    X.accept_seat(api, seat["id"], world["w1_id"])
    X.activate_room(api, world["room_id"])

    episode = validate_success(
        api.create_episode(
            world["season_id"], F.build_episode(1), STUDIO_EXECUTIVE_HEADERS
        ),
        expected_status=201,
    )
    A.assert_field_values(
        episode,
        script_readiness="NOT_STARTED",
        credit_status="PENDING",
        clearance_posture="PENDING",
        approved_teleplay_assignment_id=None,
        locked_at=None,
    )

    assignment = validate_success(
        api.create_script_assignment(
            episode["id"],
            F.build_script_assignment(world["w1_id"], episode["version"]),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_field_values(
        assignment,
        status="DRAFTING",
        revision_round=0,
        approved_at=None,
        approved_by_role=None,
        late_milestone_count=0,
    )

    milestones = X.milestones_of(api, assignment["id"])
    assert [m["status"] for m in milestones] == ["PENDING", "PENDING", "PENDING"], (
        f"Every synthesized milestone starts PENDING: {milestones}"
    )

    X.deliver_all(api, assignment["id"], world["w1_id"])
    X.approve_assignment(api, assignment["id"])

    review = validate_success(
        api.create_clearance_review(
            assignment["id"],
            F.build_clearance_review(milestones[-1]["id"]),
            LEGAL_COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    A.assert_field_values(
        review,
        posture="PENDING",
        risk_score=0,
        item_count=0,
        decided_item_count=0,
        legal_waiver_granted=False,
        waiver_memo=None,
    )

    item = validate_success(
        api.create_clearance_item(
            review["id"],
            F.build_clearance_item("NAME", "Character surname Kowalczyk", "1A"),
            LEGAL_COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    A.assert_field_values(
        item, decision="SUBMITTED", conditional_note=None, risk_weight=0
    )
    A.assert_field_values(
        X.read_episode(api, episode["id"]), clearance_posture="PENDING"
    )


def test_room_walks_open_to_staffing_to_active_to_wrapped_bumping_version(api):
    """Four states, six versions, and the commitment set is exactly STAFFING plus ACTIVE.

    PRD: "Opening the room for offers is the showrunner's move, and it takes the room from `OPEN` to `STAFFING`."

    PRD: "**Season staffing commitment** is the sum of `weekly_burn_cents` over the season's rooms whose status is `STAFFING` or `ACTIVE`; rooms that are still `OPEN` and rooms that have `WRAPPED` retain their computed burn but are excluded from the sum."

    PRD: "Activation closes staffing and opens creative work; only a studio executive may perform it, and it takes the room `STAFFING → ACTIVE`."

    PRD: "and because a `WRAPPED` room is excluded from the commitment sum, wrapping is what actually returns the season's weekly burn to the budget"

    PRD: "`version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row"

    Design: Corner/state_machines/room_walks_open_to_staffing_to_active_to_wrapped_bumping_version_each_step
    """
    world = X.build_season_world(api)
    room = X.seed_room(api, world["season_id"], world["sr_headers"])
    A.assert_field_values(room, status="OPEN", version=1)
    A.assert_room_burn(
        room, 0, K.FACILITY_TIER_1, K.ROOM_BURN_EMPTY_IN_PERSON, K.ROOM_BURN_EMPTY_IN_PERSON
    )
    assert _commitment(api, world["season_id"]) == 0, "An OPEN room is no commitment yet"

    staffing = X.open_room(api, room["id"], world["sr_headers"])
    A.assert_field_values(staffing, status="STAFFING", version=2)
    assert _commitment(api, world["season_id"]) == K.ROOM_BURN_EMPTY_IN_PERSON, (
        "A STAFFING room counts at its empty-room burn"
    )

    seat = X.seed_seat(
        api, room["id"], world["w1_id"], world["sr_headers"], expected_room_version=2
    )
    offered = X.read_room(api, room["id"])
    A.assert_field_values(
        offered, status="STAFFING", version=3, seat_subtotal_weekly_cents=0
    )
    assert _commitment(api, world["season_id"]) == K.ROOM_BURN_EMPTY_IN_PERSON, (
        "A merely OFFERED seat moves no money"
    )

    X.accept_seat(api, seat["id"], world["w1_id"])
    accepted = X.read_room(api, room["id"])
    A.assert_field_values(
        accepted, status="STAFFING", version=4, confirmed_seat_count=1
    )
    A.assert_room_burn(
        accepted,
        600000,
        K.FACILITY_TIER_1,
        K.ROOM_BURN_EMPTY_IN_PERSON,
        K.ROOM_BURN_ONE_SEAT_600000,
    )
    assert _commitment(api, world["season_id"]) == K.ROOM_BURN_ONE_SEAT_600000

    active = X.activate_room(api, room["id"])
    A.assert_field_values(active, status="ACTIVE", version=5)
    assert _commitment(api, world["season_id"]) == K.ROOM_BURN_ONE_SEAT_600000, (
        "ACTIVE is still inside the commitment set"
    )

    wrapped = validate_success(api.wrap_room(room["id"], STUDIO_EXECUTIVE_HEADERS))
    A.assert_field_values(
        wrapped, status="WRAPPED", version=6, confirmed_seat_count=0
    )
    A.assert_room_burn(
        wrapped, 0, K.FACILITY_TIER_1, K.ROOM_BURN_EMPTY_IN_PERSON, K.ROOM_BURN_EMPTY_IN_PERSON
    )
    A.assert_field_values(X.read_seat(api, seat["id"]), status="RELEASED")
    assert _commitment(api, world["season_id"]) == 0, (
        "A WRAPPED room retains its burn but leaves the sum"
    )


def test_activation_enforces_no_offered_seat_then_at_least_one_confirmed_seat(api):
    """Two activation preconditions, two distinct codes, one clearing withdrawal.

    PRD: "No seat of the room may still be `OFFERED` — every offer must be answered or withdrawn first, otherwise `ERR_SEATS_STILL_OFFERED`."

    PRD: "The room must hold at least one confirmed seat, otherwise `ERR_ROOM_HAS_NO_CONFIRMED_SEATS`."

    PRD: "Withdrawing is the mirror image from the studio side: the showrunner pulls an outstanding offer, optionally citing a `reason`, and the seat becomes `WITHDRAWN` with exactly the same counter arithmetic."

    PRD: "Step three multiplies the facility fee for the selected tier by the agreement's format surcharge fraction for the room's `format` and rounds the product to whole cents, giving `facility_surcharge_weekly_cents`."

    Design: Corner/state_machines/activation_enforces_no_offered_seat_then_at_least_one_confirmed_seat
    """
    world = X.build_staffing_room_world(api)
    s1 = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
    )
    X.accept_seat(api, s1["id"], world["w1_id"])
    s2 = X.seed_seat(
        api,
        world["room_id"],
        world["w2_id"],
        world["sr_headers"],
        exclusivity="NON_EXCLUSIVE",
        episodic_guarantee_count=0,
    )

    seatless = X.seed_room(
        api, world["season_id"], world["sr_headers"], **SATELLITE_ROOM
    )
    X.open_room(api, seatless["id"], world["sr_headers"])

    validate_error(
        api.activate_room(world["room_id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.SEATS_STILL_OFFERED,
    )
    A.assert_field_values(X.read_room(api, world["room_id"]), status="STAFFING")

    validate_error(
        api.activate_room(seatless["id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.ROOM_HAS_NO_CONFIRMED_SEATS,
    )
    A.assert_field_values(
        X.read_room(api, seatless["id"]), status="STAFFING", confirmed_seat_count=0
    )

    withdrawn = validate_success(
        api.withdraw_seat(s2["id"], world["sr_headers"], WITHDRAW_REASON)
    )
    A.assert_field_values(withdrawn, status="WITHDRAWN")

    activated = validate_success(
        api.activate_room(world["room_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    A.assert_field_values(
        activated,
        status="ACTIVE",
        confirmed_seat_count=1,
        filled_seat_count=1,
        open_seat_count=2,
    )
    A.assert_room_burn(
        activated,
        600000,
        K.FACILITY_TIER_1,
        K.ROOM_BURN_EMPTY_IN_PERSON,
        K.ROOM_BURN_ONE_SEAT_600000,
    )
    A.assert_seat_capacity_conserved(activated)
    assert _commitment(api, world["season_id"]) == (
        K.ROOM_BURN_ONE_SEAT_600000 + K.ROOM_BURN_EMPTY_REMOTE
    ), "The seatless STAFFING satellite still contributes its REMOTE surcharge"


def test_a_room_cannot_reopen_staffing_or_wrap_while_staffing_or_seat_when_active(api):
    """Absent triggers are refused with the code that names the state they want.

    PRD: "It is refused with `ERR_ROOM_NOT_ACCEPTING_SEATS` unless the room is currently `OPEN`"

    PRD: "The room must be `ACTIVE`, otherwise `ERR_ROOM_NOT_ACTIVE`."

    PRD: "First the room must be in `STAFFING`, otherwise `ERR_ROOM_NOT_ACCEPTING_SEATS`."

    PRD: "Ownership and season-showrunner checks therefore precede optimistic concurrency, and optimistic concurrency precedes every state and domain check — a caller holding a stale room version learns that before learning that the room is full."

    Design: Corner/state_machines/a_room_cannot_reopen_staffing_reconfigure_when_active_or_wrap_while_staffing
    """
    world = X.build_staffing_room_world(api)
    s1 = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
    )
    X.accept_seat(api, s1["id"], world["w1_id"])
    staffing_version = X.current_room_version(api, world["room_id"])

    validate_error(
        api.open_staffing(world["room_id"], world["sr_headers"]),
        ApiErrorId.ROOM_NOT_ACCEPTING_SEATS,
    )
    A.assert_field_values(
        X.read_room(api, world["room_id"]), status="STAFFING", version=staffing_version
    )

    validate_error(
        api.wrap_room(world["room_id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.ROOM_NOT_ACTIVE,
    )
    A.assert_field_values(X.read_room(api, world["room_id"]), status="STAFFING")

    A.assert_field_values(X.activate_room(api, world["room_id"]), status="ACTIVE")
    active_version = X.current_room_version(api, world["room_id"])

    validate_error(
        api.offer_seat(
            world["room_id"],
            F.build_seat_offer(
                world["w2_id"], active_version, exclusivity="NON_EXCLUSIVE"
            ),
            world["sr_headers"],
        ),
        ApiErrorId.ROOM_NOT_ACCEPTING_SEATS,
    )

    unchanged = X.read_room(api, world["room_id"])
    A.assert_field_values(
        unchanged,
        status="ACTIVE",
        format="IN_PERSON",
        filled_seat_count=1,
        confirmed_seat_count=1,
        version=active_version,
    )
    A.assert_seat_capacity_conserved(unchanged)


def test_wrapped_rooms_declined_seats_and_locked_episodes_admit_no_transition(api):
    """Three terminal states from three machines, each with its own refusal code.

    PRD: "The room must be `ACTIVE`, otherwise `ERR_ROOM_NOT_ACTIVE`."

    PRD: "`DECLINED` and `WITHDRAWN` are terminal; a writer cannot later accept a seat they declined, and the same `ERR_SEAT_NOT_OFFERED` guards both operations against a seat that has already moved on."

    PRD: "The seat must be `CONFIRMED`, otherwise `ERR_SEAT_NOT_CONFIRMED`."

    PRD: "`LOCKED` is terminal on the readiness dimension: no rewrite, no polish, no assignment, no delivery and no void may touch the episode afterwards, and every such attempt is rejected with `ERR_EPISODE_ALREADY_LOCKED`."

    PRD: "Locked episodes keep counting — locking never lowers coverage."

    PRD: "Seats already sitting in `DECLINED`, `WITHDRAWN` or `RELEASED` are left exactly as they are."

    Design: Corner/state_machines/wrapped_rooms_declined_seats_and_locked_episodes_admit_no_further_transition
    """
    world = X.build_staffing_room_world(api)
    s1 = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
    )
    X.accept_seat(api, s1["id"], world["w1_id"])
    s2 = X.seed_seat(
        api,
        world["room_id"],
        world["w2_id"],
        world["sr_headers"],
        exclusivity="NON_EXCLUSIVE",
        episodic_guarantee_count=0,
    )
    declined = validate_success(
        api.decline_seat(s2["id"], make_writer_headers(world["w2_id"]), DECLINE_REASON)
    )
    A.assert_field_values(declined, status="DECLINED")
    X.activate_room(api, world["room_id"])

    episode = X.seed_episode(api, world["season_id"], 1)
    a1 = X.seed_assignment(api, episode["id"], world["w1_id"], world["sr_headers"])
    X.deliver_all(api, a1["id"], world["w1_id"])
    X.approve_assignment(api, a1["id"])
    milestones = X.milestones_of(api, a1["id"])
    review = X.seed_clearance_review(api, a1["id"], milestones[-1]["id"])
    item = X.seed_clearance_item(api, review["id"], "NAME", "Harbor Mercy Hospital", "2C")
    X.decide_item(api, item["id"], "CLEARED")
    locked = X.lock_episode(api, episode["id"])
    A.assert_field_values(locked, script_readiness="LOCKED")
    locked_at = locked["locked_at"]
    validate_success(api.wrap_room(world["room_id"], STUDIO_EXECUTIVE_HEADERS))

    validate_error(
        api.wrap_room(world["room_id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.ROOM_NOT_ACTIVE,
    )

    wrapped_version = X.current_room_version(api, world["room_id"])
    validate_error(
        api.offer_seat(
            world["room_id"],
            F.build_seat_offer(
                world["w2_id"], wrapped_version, exclusivity="NON_EXCLUSIVE"
            ),
            world["sr_headers"],
        ),
        ApiErrorId.ROOM_NOT_ACCEPTING_SEATS,
    )

    validate_error(
        api.accept_seat(s2["id"], make_writer_headers(world["w2_id"])),
        ApiErrorId.SEAT_NOT_OFFERED,
    )
    validate_error(
        api.release_seat(s2["id"], STUDIO_EXECUTIVE_HEADERS, RELEASE_REASON),
        ApiErrorId.SEAT_NOT_CONFIRMED,
    )
    A.assert_field_values(X.read_seat(api, s2["id"]), status="DECLINED")

    validate_error(
        api.lock_episode_for_production(episode["id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.EPISODE_ALREADY_LOCKED,
    )
    A.assert_field_values(
        X.read_episode(api, episode["id"]),
        script_readiness="LOCKED",
        locked_at=locked_at,
    )
    A.assert_field_values(
        X.read_season(api, world["season_id"]),
        ready_script_count=1,
        coverage_gap=0,
        coverage_posture="COVERED",
    )


def test_accepting_or_approving_twice_is_refused_on_the_second_attempt(api):
    """No action endpoint is idempotent, and no replay re-applies a side effect.

    PRD: "the seat must still be `OFFERED` (otherwise `ERR_SEAT_NOT_OFFERED`)"

    PRD: "The milestone must be in a deliverable status — `PENDING`, `LATE` or `NOTES_ISSUED` — otherwise `ERR_MILESTONE_NOT_DELIVERABLE`."

    PRD: "the assignment must be in `DELIVERED` (otherwise `ERR_ASSIGNMENT_NOT_DELIVERED`)"

    PRD: "Every milestone of the assignment becomes `ACCEPTED`."

    PRD: "Under `FORWARD_COMMIT` no re-settlement occurs and no reallocation entry is written."

    Design: Corner/state_machines/accepting_or_approving_twice_is_refused_on_the_second_attempt
    """
    world = X.build_approved_assignment_world(api)
    approved = X.read_assignment(api, world["a1_id"])
    before_ledger = X.ledger_for_assignment(api, world["a1_id"])

    validate_error(
        api.accept_seat(world["s1_id"], make_writer_headers(world["w1_id"])),
        ApiErrorId.SEAT_NOT_OFFERED,
    )
    A.assert_field_values(X.read_writer(api, world["w1_id"]), active_seat_count=1)
    A.assert_field_values(
        X.read_room(api, world["room_id"]), confirmed_seat_count=2, filled_seat_count=2
    )
    A.assert_field_values(
        X.read_window(api, world["aw1_id"]),
        status="CONSUMED",
        consumed_by_seat_id=world["s1_id"],
    )

    first_milestone = world["a1_milestone_ids"][0]
    A.assert_field_values(X.read_milestone(api, first_milestone), status="ACCEPTED")
    validate_error(
        api.deliver_milestone(first_milestone, make_writer_headers(world["w1_id"])),
        ApiErrorId.MILESTONE_NOT_DELIVERABLE,
    )

    validate_error(
        api.approve_assignment(world["a1_id"], world["sr_headers"]),
        ApiErrorId.ASSIGNMENT_NOT_DELIVERED,
    )
    replayed = X.read_assignment(api, world["a1_id"])
    A.assert_field_values(
        replayed,
        status="APPROVED",
        approved_at=approved["approved_at"],
        version=approved["version"],
    )

    after_ledger = X.ledger_for_assignment(api, world["a1_id"])
    assert after_ledger == before_ledger, (
        f"No replay may append a ledger row: {A.entry_types(after_ledger)}"
    )
    assert len(after_ledger) == 2, (
        f"The assignment still owns exactly its two creation rows: {after_ledger}"
    )
    assert "GUARANTEE_REALLOCATION" not in A.entry_types(after_ledger), (
        "A FORWARD_COMMIT season never reallocates"
    )


def test_seat_acceptance_consumes_the_earliest_containing_window(api):
    """Two OPEN containing windows, and the earlier-starting one is the one consumed.

    PRD: "The candidate set is every availability window of the seat's writer whose status is `OPEN` and whose interval contains the seat's half-open interval; candidates are ranked by the window's `start_date` ascending, and ties are broken by the window's `created_at` ascending; the first candidate wins."

    PRD: "Acceptance moves the seat `OFFERED → CONFIRMED` and stamps `confirmed_at` from the logical clock."

    PRD: "The winning window moves to `CONSUMED` and records the seat in its `consumed_by_seat_id`, while the seat records the window in its `consumed_window_id` — a two-way link that makes the later release reversible."

    PRD: "The room's `confirmed_seat_count` increases by one, and when the seat is `diversity_program_funded` its `confirmed_diversity_seat_count` also increases by one."

    PRD: "Because a confirmed seat now contributes to the subtotal, the room's `seat_subtotal_weekly_cents`, `facility_tier`, `facility_surcharge_weekly_cents` and `weekly_burn_cents` are recomputed, and the season's `staffing_commitment_weekly_cents` follows."

    PRD: "Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to real time."

    Design: Corner/state_machines/seat_acceptance_consumes_the_earliest_containing_window_and_moves_four_counters
    """
    world = X.build_staffing_room_world(api)
    later_window = X.seed_window(
        api, world["w1_id"], "NON_EXCLUSIVE", "2026-08-20T00:00:00Z", K.WINDOW_END_DATE
    )

    seat = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
    )
    confirmed = X.accept_seat(api, seat["id"], world["w1_id"])
    A.assert_field_values(
        confirmed, status="CONFIRMED", consumed_window_id=world["aw1_id"]
    )
    A.assert_instant(confirmed["confirmed_at"], K.CLOCK_EPOCH, "confirmed_at")

    A.assert_field_values(
        X.read_window(api, world["aw1_id"]),
        status="CONSUMED",
        consumed_by_seat_id=seat["id"],
    )
    A.assert_field_values(
        X.read_window(api, later_window["id"]),
        status="OPEN",
        consumed_by_seat_id=None,
    )

    room = X.read_room(api, world["room_id"])
    A.assert_field_values(
        room, confirmed_seat_count=1, confirmed_diversity_seat_count=0
    )
    A.assert_room_burn(
        room,
        600000,
        K.FACILITY_TIER_1,
        K.ROOM_BURN_EMPTY_IN_PERSON,
        K.ROOM_BURN_ONE_SEAT_600000,
    )
    A.assert_field_values(X.read_writer(api, world["w1_id"]), active_seat_count=1)
    assert _commitment(api, world["season_id"]) == K.ROOM_BURN_ONE_SEAT_600000


def test_an_assignment_reaches_delivered_only_when_its_last_milestone_lands(api):
    """The parent flips inside the third delivery, not the first or the second.

    PRD: "Then `delivered_at` is stamped from the logical clock and the milestone becomes `DELIVERED`."

    PRD: "Then `days_late` is frozen at the number of whole days by which the UTC calendar date of `delivered_at` exceeds the UTC calendar date of `due_date`, floored at 0 — an on-time or early delivery is 0."

    PRD: "the same call then checks whether every milestone of the assignment now holds a status in `DELIVERED`, `NOTES_ISSUED` or `ACCEPTED`, and if so moves the assignment `DRAFTING → DELIVERED`."

    PRD: "the assignment must be in `DELIVERED` (otherwise `ERR_ASSIGNMENT_NOT_DELIVERED`)"

    PRD: "An episode at `NOT_STARTED` advances to `IN_PROGRESS` on its first non-void assignment."

    Design: Corner/state_machines/an_assignment_reaches_delivered_only_when_its_last_milestone_lands
    """
    world = X.build_assignment_world(api)
    m1, m2, m3 = world["a1_milestone_ids"]

    first = X.deliver_milestone(api, m1, world["w1_id"])
    A.assert_field_values(first, status="DELIVERED", days_late=0)
    A.assert_instant(first["delivered_at"], K.CLOCK_EPOCH, "delivered_at")
    A.assert_field_values(X.read_assignment(api, world["a1_id"]), status="DRAFTING")

    validate_error(
        api.approve_assignment(world["a1_id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.ASSIGNMENT_NOT_DELIVERED,
    )

    X.deliver_milestone(api, m2, world["w1_id"])
    A.assert_field_values(X.read_assignment(api, world["a1_id"]), status="DRAFTING")
    A.assert_field_values(X.read_milestone(api, m3), status="PENDING")

    X.deliver_milestone(api, m3, world["w1_id"])
    delivered = X.read_assignment(api, world["a1_id"])
    A.assert_field_values(delivered, status="DELIVERED", late_milestone_count=0)
    assert [m["status"] for m in X.milestones_of(api, world["a1_id"])] == [
        "DELIVERED",
        "DELIVERED",
        "DELIVERED",
    ], "Every milestone landed before the parent moved"
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), script_readiness="IN_PROGRESS"
    )


def test_wrapping_a_room_releases_every_confirmed_seat_and_pends_their_assignments(api):
    """The fan-out moves the live assignment and leaves the approved one alone.

    PRD: "The room becomes `WRAPPED`, which is terminal, and every seat of the room still in `CONFIRMED` status is released as part of the same call — each such seat runs the full release chain described above, including the return of its consumed availability window, the counter arithmetic, the move of its live assignments to `REASSIGNMENT_PENDING`, and the episode-readiness and season-coverage recomputation that follows."

    PRD: "the window it consumed returns to `OPEN` with its `consumed_by_seat_id` cleared and the seat's `consumed_window_id` cleared, freeing that stretch of the writer's calendar for another room"

    PRD: "every script assignment held through that seat whose status is `DRAFTING`, `DELIVERED` or `IN_NOTES` moves to `REASSIGNMENT_PENDING`; the assignment keeps the seat reference it was created with, so the seat's guarantee counters are unaffected by the release, and the assignment's milestones keep their current statuses and due dates untouched."

    PRD: "an episode sitting at `READY` returns to `IN_PROGRESS` when it has no `approved_teleplay_assignment_id` and at least one non-void assignment survives, and an episode at `IN_PROGRESS` falls back to `NOT_STARTED` when every one of its assignments is void."

    PRD: "the writer's `active_seat_count` drops by one"

    Design: Corner/state_machines/wrapping_a_room_releases_every_confirmed_seat_and_pends_their_assignments
    """
    world = X.build_approved_assignment_world(api)
    story = X.seed_assignment(
        api, world["ep1_id"], world["w2_id"], world["sr_headers"], "STORY"
    )
    A.assert_field_values(story, status="DRAFTING", room_seat_id=world["s2_id"])
    milestones_before = X.milestones_of(api, story["id"])

    wrapped = validate_success(
        api.wrap_room(world["room_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    A.assert_field_values(wrapped, status="WRAPPED", confirmed_seat_count=0)
    A.assert_room_burn(
        wrapped, 0, K.FACILITY_TIER_1, K.ROOM_BURN_EMPTY_IN_PERSON, K.ROOM_BURN_EMPTY_IN_PERSON
    )

    statuses = _seat_statuses(api, world["room_id"])
    assert statuses == {world["s1_id"]: "RELEASED", world["s2_id"]: "RELEASED"}, (
        f"Both confirmed seats were released by the wrap: {statuses}"
    )
    for window_key in ("aw1_id", "aw2_id"):
        A.assert_field_values(
            X.read_window(api, world[window_key]),
            status="OPEN",
            consumed_by_seat_id=None,
        )

    A.assert_field_values(
        X.read_assignment(api, story["id"]),
        status="REASSIGNMENT_PENDING",
        room_seat_id=world["s2_id"],
    )
    assert X.milestones_of(api, story["id"]) == milestones_before, (
        "The cascade leaves the pended assignment's milestones untouched"
    )
    A.assert_field_values(
        X.read_assignment(api, world["a1_id"]),
        status="APPROVED",
        room_seat_id=world["s1_id"],
    )

    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]),
        script_readiness="READY",
        approved_teleplay_assignment_id=world["a1_id"],
    )
    A.assert_field_values(X.read_writer(api, world["w1_id"]), active_seat_count=0)
    A.assert_field_values(X.read_writer(api, world["w2_id"]), active_seat_count=0)
    assert _commitment(api, world["season_id"]) == 0, (
        "The wrap returns the season's weekly burn to the budget"
    )


def test_a_milestone_flips_to_late_inside_the_delivery_call_and_stamps_days_late(api):
    """The clock alone changes nothing; the flip happens inside the delivery.

    PRD: "Moving the clock is not itself a domain event: it mutates no entity."

    PRD: "A milestone that has slipped past its deadline does not flip to `LATE` at the moment the clock passes the deadline — it flips on the next write that touches the milestone's assignment or the milestone's season, which is where the re-evaluation is performed."

    PRD: "If the milestone is still `PENDING` and the logical clock already stands past its `due_date`, it flips to `LATE` first, so lateness is recorded even when the writer never saw a warning."

    PRD: "Then `days_late` is frozen at the number of whole days by which the UTC calendar date of `delivered_at` exceeds the UTC calendar date of `due_date`, floored at 0 — an on-time or early delivery is 0."

    PRD: "The owning assignment's `late_milestone_count` is then recomputed as the number of its milestones that are either sitting in `LATE`, or sitting in `DELIVERED`, `NOTES_ISSUED` or `ACCEPTED` with a `days_late` above 0; lateness once incurred is not erased by a subsequent on-time redelivery of the same milestone."

    Design: Corner/state_machines/a_milestone_flips_to_late_inside_the_delivery_call_and_stamps_days_late
    """
    world = X.build_assignment_world(api)
    m1, m2, m3 = world["a1_milestone_ids"]
    A.assert_field_values(
        X.read_milestone(api, m1), status="PENDING", due_date=K.DUE_DATES_NOV_02["OUTLINE"]
    )

    X.set_clock(api, K.CLOCK_LATE_OUTLINE)
    A.assert_field_values(X.read_milestone(api, m1), status="PENDING", days_late=0)
    A.assert_field_values(
        X.read_assignment(api, world["a1_id"]), late_milestone_count=0, status="DRAFTING"
    )

    delivered = X.deliver_milestone(api, m1, world["w1_id"])
    A.assert_field_values(delivered, status="DELIVERED", days_late=4)
    A.assert_instant(delivered["delivered_at"], K.CLOCK_LATE_OUTLINE, "delivered_at")
    A.assert_field_values(
        X.read_assignment(api, world["a1_id"]), late_milestone_count=1, status="DRAFTING"
    )

    for still_pending in (m2, m3):
        A.assert_field_values(
            X.read_milestone(api, still_pending), status="PENDING", days_late=0
        )

    rows, meta = validate_paginated(
        api.list_milestones(
            STUDIO_EXECUTIVE_HEADERS,
            {"assignment_id": world["a1_id"], "status": "PENDING", "limit": 100},
        )
    )
    assert meta["total_count"] == 2, f"Exactly two milestones are still pending: {rows}"


def test_a_review_reaches_cleared_only_when_every_item_is_decided(api):
    """CLEARED needs the conjunction; one cleared item out of two is still PENDING.

    PRD: "The decision sets the item's `risk_weight` to the agreement's `clearance_item_weights` entry for the item's `item_type` multiplied by a decision multiplier of 0 for `CLEARED`, 1 for `CONDITIONAL` and 4 for `BLOCKED`."

    PRD: "`CLEARED` when `item_count` is at least 1 and `decided_item_count` equals `item_count` — every raised item decided, and every one of them cleared."

    PRD: "`PENDING` otherwise, which covers both the review with no items at all and the review whose items are all still undecided."

    PRD: "An episode counts toward `ready_script_count` only when *both* dimensions permit: its `script_readiness` is `READY` or `LOCKED`, **and** its `clearance_posture` is `CLEARED` or `CONDITIONAL_WAIVED`."

    Design: Corner/state_machines/a_review_reaches_cleared_only_when_every_item_is_decided_and_scores_zero
    """
    world = X.build_clearance_world(api)
    it1 = X.seed_clearance_item(
        api, world["review_id"], "DEPICTION", "Real hospital shown mid-malpractice", "3B"
    )
    it2 = X.seed_clearance_item(
        api, world["review_id"], "NAME", "Character surname Kowalczyk", "1A"
    )
    A.assert_field_values(
        X.read_review(api, world["review_id"]),
        item_count=2,
        decided_item_count=0,
        risk_score=0,
        posture="PENDING",
    )

    decided = X.decide_item(api, it1["id"], "CLEARED")
    A.assert_field_values(decided, decision="CLEARED", risk_weight=0)
    A.assert_field_values(
        X.read_review(api, world["review_id"]),
        item_count=2,
        decided_item_count=1,
        risk_score=0,
        posture="PENDING",
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), clearance_posture="PENDING"
    )

    X.decide_item(api, it2["id"], "CLEARED")
    A.assert_field_values(
        X.read_review(api, world["review_id"]),
        item_count=2,
        decided_item_count=2,
        risk_score=0,
        posture="CLEARED",
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]),
        clearance_posture="CLEARED",
        script_readiness="READY",
    )
    A.assert_field_values(
        X.read_season(api, world["season_id"]),
        ready_script_count=1,
        coverage_gap=0,
        coverage_posture="COVERED",
    )


def test_the_arbitration_panel_stays_in_panel_voting_across_all_three_ballots(api):
    """Only the first ballot is a transition; the running figures still move each time.

    PRD: "The arbitration is created in `INITIATED` and auto-advanced to `STATEMENTS_OPEN` inside the same call, so a caller never observes `INITIATED`."

    PRD: "`votes_cast_count` starts at 0, `vote_ledger` at an empty map, `leading_writer_id` and `determined_credit_string` at null, `concurrence_pct` at 0 and `outcome` at `NONE`."

    PRD: "The first ballot moves the arbitration `STATEMENTS_OPEN → PANEL_VOTING`; the second and third are self-loops that leave it in `PANEL_VOTING`."

    PRD: "The `leading_writer_id` is the participant with the highest panel mean, with ties broken by submission `created_at` ascending."

    PRD: "The `concurrence_pct` is the count of recorded ballots whose share *for the leading writer* lies within `arbitration_concurrence_band_pct` percentage points (default 10, an inclusive absolute comparison) of the leading writer's panel mean, divided by `votes_cast_count`, rounded half up to three decimals."

    PRD: "Nothing else moves — the arbitration stays in `PANEL_VOTING` however many ballots arrive, and the shares are not written to any submission."

    Design: Corner/state_machines/the_arbitration_panel_stays_in_panel_voting_across_all_three_ballots
    """
    world = X.build_arbitration_world(api)
    arbitration = world["arbitration"]
    A.assert_field_values(
        arbitration,
        status="STATEMENTS_OPEN",
        votes_cast_count=0,
        vote_ledger={},
        leading_writer_id=None,
        determined_credit_string=None,
        concurrence_pct=0,
        outcome="NONE",
        participant_writer_ids=[world["w1_id"], world["w2_id"]],
    )
    ballots = X.concurring_ballots(world)

    first = X.cast_ballot(api, world["arbitration_id"], world["ar1_id"], ballots[0])
    A.assert_field_values(
        first,
        status="PANEL_VOTING",
        votes_cast_count=1,
        leading_writer_id=world["w1_id"],
        concurrence_pct=1.0,
    )
    assert list(first["vote_ledger"]) == [world["ar1_id"]], (
        f"The ledger holds exactly the first arbiter: {first['vote_ledger']}"
    )

    second = X.cast_ballot(api, world["arbitration_id"], world["ar2_id"], ballots[1])
    A.assert_field_values(
        second,
        status="PANEL_VOTING",
        votes_cast_count=2,
        leading_writer_id=world["w2_id"],
        concurrence_pct=1.0,
    )

    third = X.cast_ballot(api, world["arbitration_id"], world["ar3_id"], ballots[2])
    A.assert_field_values(
        third,
        status="PANEL_VOTING",
        votes_cast_count=3,
        leading_writer_id=world["w2_id"],
        concurrence_pct=1.0,
        outcome="NONE",
        determined_credit_string=None,
    )

    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]),
        credit_status="IN_ARBITRATION",
        final_credit_shares={},
    )
    A.assert_field_values(
        X.read_submission(api, world["sb1_id"]), arbitrated_share_pct=None
    )
    A.assert_field_values(
        X.read_submission(api, world["sb2_id"]), arbitrated_share_pct=None
    )
