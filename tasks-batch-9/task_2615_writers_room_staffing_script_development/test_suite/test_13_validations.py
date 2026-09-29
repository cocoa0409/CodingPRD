"""Each guard walked to its own refusal, then repaired so the write lands.

One test per breadth instance of the corner design's `validations` section.
Adjacent codes are kept distinct — the guild floor from the level ceiling, the
malformed interval from the out-of-window one — and every refusal is followed
by an assertion that the target row and its counters did not move.
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

CONDITIONAL_NOTE = "Change the character's home state and re-submit for a read."

ZERO_LENGTH_WINDOW = {
    "start_date": "2026-10-01T00:00:00Z",
    "end_date": "2026-10-01T00:00:00Z",
    "commitment_type": "NON_EXCLUSIVE",
}
# A start date inside the season's staffing-window-through-photography span, so
# the only thing wrong with this room is that its end date precedes its start.
BACKWARDS_ROOM = {
    "name": "Backwards Room",
    "format": "REMOTE",
    "seat_capacity": 2,
    "start_date": "2026-10-01T00:00:00Z",
    "end_date": K.ROOM_START_DATE,
}
PAST_THE_WINDOW = "2026-10-01T00:00:00Z"
ON_THE_WINDOW_EDGE = "2026-09-30T00:00:00Z"

CLOCK_PAST_STAFFING = "2026-10-01T00:00:00Z"
RESCHEDULE_INTO_THE_WINDOW = "2026-09-15T00:00:00Z"
RESCHEDULE_TO_DECEMBER = "2026-12-01T00:00:00Z"
# The four leads (42, 28, 14, 3) subtracted from a 2026-12-01 photography start.
DUE_DATES_DEC_01 = {
    "OUTLINE": "2026-10-20T23:59:59.999Z",
    "FIRST_DRAFT": "2026-11-03T23:59:59.999Z",
    "SECOND_DRAFT": "2026-11-17T23:59:59.999Z",
    "POLISH": "2026-11-28T23:59:59.999Z",
}

W3_WINDOW_END = "2026-10-01T00:00:00Z"
TIGHT_BUDGET = {"staffing_budget_weekly_cents": 1250000}


def _seat_body(writer_id, room_version, **overrides):
    """A seat offer with every field named, so each refusal differs in one place."""
    return F.build_seat_offer(writer_id, room_version, **overrides)


def _room_rows(api, season_id):
    """Every room configured on one season."""
    rows, _ = validate_paginated(
        api.list_rooms(STUDIO_EXECUTIVE_HEADERS, {"season_id": season_id, "limit": 100})
    )
    return rows


def _seat_rows(api, room_id):
    """Every seat of one room."""
    rows, _ = validate_paginated(
        api.list_room_seats(
            STUDIO_EXECUTIVE_HEADERS, {"room_id": room_id, "limit": 100}
        )
    )
    return rows


def _coverage(api, season_id):
    """The season's three coverage figures, as a tuple."""
    season = X.read_season(api, season_id)
    return (
        season["ready_script_count"],
        season["coverage_gap"],
        season["coverage_posture"],
    )


def test_the_guild_floor_and_the_level_ceiling_refuse_underpaid_or_over_titled_seats(
    api,
):
    """Three adjacent 422s on one create, kept apart by one field each.

    PRD: "Then the money floor: the offered weekly compensation must be at least the agreement's minimum weekly cents for the seat's `level_at_hire`, otherwise `ERR_BELOW_GUILD_MINIMUM`."

    PRD: "Then the level requirement: reading the levels in the fixed order `STAFF_WRITER`, `STORY_EDITOR`, `EXEC_STORY_EDITOR`, `CO_PRODUCER`, `PRODUCER`, the seat's `level_at_hire` must be at or below the writer's `determined_level`, except that a diversity-program-funded seat may be written at exactly one position above the determined level — two positions above is never allowed."

    PRD: "Then funding eligibility: a seat may only be marked `diversity_program_funded` when the writer's `diversity_program_participant` flag is true, otherwise `ERR_DIVERSITY_FUNDING_INELIGIBLE`."

    PRD: "When the seat is `diversity_program_funded` and the writer is a `diversity_program_participant`, the seat's `diversity_subsidy_weekly_cents` is the lesser of two figures: the seat's weekly compensation multiplied by the agreement's `diversity_subsidy_pct` and rounded to whole cents, and the agreement's `diversity_subsidy_cap_weekly_cents`."

    PRD: "The seat's `studio_charge_weekly_cents` is its weekly compensation minus that subsidy, and it is the figure the studio actually bears — though note that the room's burn and the season's staffing commitment are built from full weekly compensation, not from the studio charge."

    Design: Corner/validations/the_guild_floor_and_the_level_ceiling_refuse_underpaid_or_over_titled_seats
    """
    world = X.build_staffing_room_world(api)
    stale_free_version = world["room_version"]
    A.assert_field_values(
        X.read_writer(api, world["w1_id"]),
        determined_level="STORY_EDITOR",
        diversity_program_participant=False,
    )
    A.assert_field_values(
        X.read_writer(api, world["w8_id"]),
        determined_level="STORY_EDITOR",
        diversity_program_participant=True,
    )

    validate_error(
        api.offer_seat(
            world["room_id"],
            _seat_body(
                world["w1_id"],
                stale_free_version,
                offered_weekly_compensation_cents=599999,
            ),
            world["sr_headers"],
        ),
        ApiErrorId.BELOW_GUILD_MINIMUM,
    )
    validate_error(
        api.offer_seat(
            world["room_id"],
            _seat_body(
                world["w1_id"],
                stale_free_version,
                level_at_hire="EXEC_STORY_EDITOR",
                offered_weekly_compensation_cents=700000,
            ),
            world["sr_headers"],
        ),
        ApiErrorId.LEVEL_ABOVE_DETERMINED,
    )
    validate_error(
        api.offer_seat(
            world["room_id"],
            _seat_body(
                world["w1_id"],
                stale_free_version,
                level_at_hire="EXEC_STORY_EDITOR",
                offered_weekly_compensation_cents=700000,
                diversity_program_funded=True,
            ),
            world["sr_headers"],
        ),
        ApiErrorId.DIVERSITY_FUNDING_INELIGIBLE,
    )
    validate_error(
        api.offer_seat(
            world["room_id"],
            _seat_body(
                world["w8_id"],
                stale_free_version,
                level_at_hire="CO_PRODUCER",
                offered_weekly_compensation_cents=850000,
                exclusivity="NON_EXCLUSIVE",
                diversity_program_funded=True,
            ),
            world["sr_headers"],
        ),
        ApiErrorId.LEVEL_ABOVE_DETERMINED,
    )

    subsidised = validate_success(
        api.offer_seat(
            world["room_id"],
            _seat_body(
                world["w8_id"],
                stale_free_version,
                level_at_hire="EXEC_STORY_EDITOR",
                offered_weekly_compensation_cents=700000,
                exclusivity="NON_EXCLUSIVE",
                diversity_program_funded=True,
            ),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_seat_pricing(subsidised, 700000, 700000, 250000, 450000)

    at_the_floor = validate_success(
        api.offer_seat(
            world["room_id"],
            _seat_body(
                world["w1_id"],
                X.current_room_version(api, world["room_id"]),
                offered_weekly_compensation_cents=600000,
            ),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_seat_pricing(at_the_floor, 600000, 600000, 0, 600000)

    room = X.read_room(api, world["room_id"])
    A.assert_field_values(room, filled_seat_count=2, open_seat_count=1, version=4)
    A.assert_seat_capacity_conserved(room)


def test_a_conditional_clearance_decision_without_a_note_is_refused(api):
    """The note is optional in the schema and mandatory only on one branch.

    PRD: "A `CONDITIONAL` decision must carry a non-empty `conditional_note`, otherwise `ERR_CONDITIONAL_NOTE_REQUIRED`; the note is stored on the item and remains null for the other two decisions."

    PRD: "The item must still be `SUBMITTED`, otherwise `ERR_ITEM_ALREADY_DECIDED` — decisions are one-way and are never revised."

    PRD: "A new item's `decision` is `SUBMITTED`, its `conditional_note` is null, and its `risk_weight` is 0 — an undecided item carries no risk weight even though its type already implies one."

    PRD: "The decision sets the item's `risk_weight` to the agreement's `clearance_item_weights` entry for the item's `item_type` multiplied by a decision multiplier of 0 for `CLEARED`, 1 for `CONDITIONAL` and 4 for `BLOCKED`."

    PRD: "`CONDITIONAL` when the `risk_score` is strictly greater than 0."

    Design: Corner/validations/a_conditional_clearance_decision_without_a_note_is_refused
    """
    world = X.build_clearance_world(api)
    depiction = X.seed_clearance_item(
        api, world["review_id"], "DEPICTION", "Real hospital shown mid-malpractice", "3B"
    )
    name = X.seed_clearance_item(
        api, world["review_id"], "NAME", "Character surname Kowalczyk", "1A"
    )

    validate_error(
        api.decide_clearance_item(
            depiction["id"], F.build_item_decision("CONDITIONAL"), LEGAL_COUNSEL_HEADERS
        ),
        ApiErrorId.CONDITIONAL_NOTE_REQUIRED,
    )
    A.assert_field_values(
        X.read_item(api, depiction["id"]),
        decision="SUBMITTED",
        risk_weight=0,
        conditional_note=None,
    )

    decided = validate_success(
        api.decide_clearance_item(
            depiction["id"],
            F.build_item_decision("CONDITIONAL", CONDITIONAL_NOTE),
            LEGAL_COUNSEL_HEADERS,
        )
    )
    A.assert_field_values(
        decided,
        decision="CONDITIONAL",
        risk_weight=25,
        conditional_note=CONDITIONAL_NOTE,
    )
    A.assert_field_values(
        X.read_review(api, world["review_id"]),
        risk_score=25,
        decided_item_count=1,
        posture="CONDITIONAL",
    )

    validate_error(
        api.decide_clearance_item(
            depiction["id"], F.build_item_decision("CLEARED"), LEGAL_COUNSEL_HEADERS
        ),
        ApiErrorId.ITEM_ALREADY_DECIDED,
    )
    A.assert_field_values(
        X.read_item(api, depiction["id"]),
        decision="CONDITIONAL",
        conditional_note=CONDITIONAL_NOTE,
    )

    cleared = X.decide_item(api, name["id"], "CLEARED")
    A.assert_field_values(cleared, risk_weight=0, conditional_note=None)
    A.assert_field_values(
        X.read_review(api, world["review_id"]),
        risk_score=25,
        decided_item_count=2,
        item_count=2,
        posture="CONDITIONAL",
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), clearance_posture="CONDITIONAL"
    )


def test_activation_is_gated_on_the_rooms_own_diversity_seat_requirement(api):
    """One confirmed seat is not enough when the room asked for a funded one.

    PRD: "The room's `confirmed_diversity_seat_count` must be at least its `diversity_seats_required`, otherwise `ERR_DIVERSITY_REQUIREMENT_UNMET`."

    PRD: "The room's `confirmed_seat_count` increases by one, and when the seat is `diversity_program_funded` its `confirmed_diversity_seat_count` also increases by one."

    PRD: "Optionally the room declares `diversity_seats_required`, a count from 0 through the room's capacity that defaults to 0 and sets how many confirmed diversity-funded seats the room must hold before it may be activated."

    PRD: "Activation recomputes the room's weekly burn and the season's staffing commitment and increments the room's `version`."

    Design: Corner/validations/activation_is_gated_on_the_rooms_own_diversity_seat_requirement
    """
    world = X.build_staffing_room_world(api, room_overrides={"diversity_seats_required": 1})
    plain = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
    )
    X.accept_seat(api, plain["id"], world["w1_id"])
    A.assert_field_values(
        X.read_room(api, world["room_id"]),
        confirmed_seat_count=1,
        confirmed_diversity_seat_count=0,
        diversity_seats_required=1,
    )

    validate_error(
        api.activate_room(world["room_id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.DIVERSITY_REQUIREMENT_UNMET,
    )
    A.assert_field_values(X.read_room(api, world["room_id"]), status="STAFFING")

    funded = X.seed_seat(
        api,
        world["room_id"],
        world["w8_id"],
        world["sr_headers"],
        exclusivity="NON_EXCLUSIVE",
        diversity_program_funded=True,
        episodic_guarantee_count=0,
    )
    A.assert_seat_pricing(funded, 600000, 600000, 250000, 350000)
    X.accept_seat(api, funded["id"], world["w8_id"])

    room = X.read_room(api, world["room_id"])
    A.assert_field_values(
        room, confirmed_seat_count=2, confirmed_diversity_seat_count=1
    )
    A.assert_room_burn(room, 1200000, K.FACILITY_TIER_1, 200000, 1400000)

    activated = X.activate_room(api, world["room_id"])
    A.assert_field_values(activated, status="ACTIVE")
    A.assert_cents(
        X.read_season(api, world["season_id"])["staffing_commitment_weekly_cents"],
        1400000,
        "staffing_commitment_weekly_cents",
    )


def test_interval_wellformedness_and_the_staffing_window_bracket_the_seat_start(api):
    """Malformed intervals and an out-of-window start carry two different codes.

    PRD: "Any supplied interval whose `end_date` is not strictly after its `start_date` is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 422); the same code covers a season whose `staffing_window_end` precedes its `staffing_window_start`, or whose `production_start_date` is not strictly after `staffing_window_end`."

    PRD: "Then staffing-season timing: the seat's `start_date` must fall within the season's staffing window, at or after `staffing_window_start` and at or before `staffing_window_end`, otherwise `ERR_OUTSIDE_STAFFING_WINDOW`."

    PRD: "and `production_start_date` is the instant principal photography begins, which must be strictly after the staffing window closes"

    Design: Corner/validations/interval_wellformedness_and_the_staffing_window_bracket_the_seat_start
    """
    world = X.build_staffing_room_world(api)

    validate_error(
        api.create_availability_window(
            world["w1_id"],
            F.build_availability_window(**ZERO_LENGTH_WINDOW),
            make_writer_headers(world["w1_id"]),
        ),
        ApiErrorId.INVALID_DATE_RANGE,
    )
    validate_error(
        api.create_room(
            world["season_id"], F.build_room(**BACKWARDS_ROOM), world["sr_headers"]
        ),
        ApiErrorId.INVALID_DATE_RANGE,
    )
    validate_error(
        api.create_season(
            F.build_season(
                world["agreement_id"],
                world["sr_id"],
                production_start_date=K.STAFFING_WINDOW_END,
            ),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        ApiErrorId.INVALID_DATE_RANGE,
    )

    validate_error(
        api.offer_seat(
            world["room_id"],
            _seat_body(
                world["w1_id"], world["room_version"], start_date=PAST_THE_WINDOW
            ),
            world["sr_headers"],
        ),
        ApiErrorId.OUTSIDE_STAFFING_WINDOW,
    )

    on_the_edge = validate_success(
        api.offer_seat(
            world["room_id"],
            _seat_body(
                world["w1_id"], world["room_version"], start_date=ON_THE_WINDOW_EDGE
            ),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_field_values(on_the_edge, status="OFFERED")
    A.assert_instant(on_the_edge["start_date"], ON_THE_WINDOW_EDGE, "start_date")

    rows, meta = validate_paginated(
        api.list_availability_windows(
            GUILD_ADMINISTRATOR_HEADERS, {"writer_id": world["w1_id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1, f"The zero-length window was never created: {rows}"
    assert len(_room_rows(api, world["season_id"])) == 1, (
        "The backwards room was never created"
    )


def test_staffing_window_closure_and_reschedule_dates_are_measured_against_the_clock(
    api,
):
    """The clock past the window shuts hiring and floors every new photography date.

    PRD: "It is refused with `ERR_ROOM_NOT_ACCEPTING_SEATS` unless the room is currently `OPEN`, and refused with `ERR_STAFFING_WINDOW_CLOSED` if the logical clock has already passed the season's `staffing_window_end` — hiring cannot begin after the hiring window has shut, though the clock standing exactly on the closing instant is still in time."

    PRD: "The proposed date must be strictly after the season's `staffing_window_end` and strictly after the logical clock — a production cannot be rescheduled into the past or back inside the hiring window — and a date failing either test is rejected with `ERR_RESCHEDULE_DATE_INVALID`."

    PRD: "When the date is accepted, the delta between the old and new season production start is computed once and applied uniformly: every episode of the season whose `script_readiness` is not `LOCKED` has its own `production_start_date` shifted by that same signed delta, so relative episode spacing and unit assignments survive the move untouched."

    PRD: "Every non-void script assignment on a shifted episode has all four of its due-date fields re-derived from the new episode date, and every milestone of those assignments has its `due_date` re-derived to match."

    PRD: "Moving the clock is not itself a domain event: it mutates no entity."

    Design: Corner/validations/staffing_window_closure_and_reschedule_dates_are_measured_against_the_clock
    """
    world = X.build_assignment_world(api)
    latecomer = X.seed_room(
        api,
        world["season_id"],
        world["sr_headers"],
        name="Latecomer Room",
        format="REMOTE",
        seat_capacity=2,
    )
    A.assert_field_values(latecomer, status="OPEN")

    X.set_clock(api, CLOCK_PAST_STAFFING)
    A.assert_field_values(X.read_room(api, latecomer["id"]), status="OPEN", version=1)

    validate_error(
        api.open_staffing(latecomer["id"], world["sr_headers"]),
        ApiErrorId.STAFFING_WINDOW_CLOSED,
    )
    A.assert_field_values(X.read_room(api, latecomer["id"]), status="OPEN", version=1)

    before = X.read_season(api, world["season_id"])
    validate_error(
        api.reschedule_season(
            world["season_id"],
            F.build_reschedule(before["version"], RESCHEDULE_INTO_THE_WINDOW),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        ApiErrorId.RESCHEDULE_DATE_INVALID,
    )
    unmoved = X.read_season(api, world["season_id"])
    A.assert_instant(
        unmoved["production_start_date"],
        K.SEASON_PRODUCTION_START,
        "production_start_date",
    )
    assert unmoved["version"] == before["version"], "A refused reschedule moved the season"

    moved = validate_success(
        api.reschedule_season(
            world["season_id"],
            F.build_reschedule(before["version"], RESCHEDULE_TO_DECEMBER),
            STUDIO_EXECUTIVE_HEADERS,
        )
    )
    A.assert_instant(
        moved["production_start_date"], RESCHEDULE_TO_DECEMBER, "production_start_date"
    )
    A.assert_instant(
        moved["staffing_window_end"], K.STAFFING_WINDOW_END, "staffing_window_end"
    )
    assert moved["version"] == before["version"] + 1, (
        f"Reschedule must move the season version once: {moved['version']}"
    )
    A.assert_instant(
        X.read_episode(api, world["ep1_id"])["production_start_date"],
        RESCHEDULE_TO_DECEMBER,
        "episode production_start_date",
    )

    assignment = X.read_assignment(api, world["a1_id"])
    assert assignment["outline_due_date"] == DUE_DATES_DEC_01["OUTLINE"], assignment
    assert assignment["first_draft_due_date"] == DUE_DATES_DEC_01["FIRST_DRAFT"], assignment
    assert assignment["second_draft_due_date"] == DUE_DATES_DEC_01["SECOND_DRAFT"], assignment
    assert assignment["polish_due_date"] == DUE_DATES_DEC_01["POLISH"], assignment
    assert assignment["late_milestone_count"] == 0, assignment

    for milestone in X.milestones_of(api, world["a1_id"]):
        assert milestone["due_date"] == DUE_DATES_DEC_01[milestone["milestone_type"]], (
            f"Milestone {milestone['milestone_type']} kept a stale deadline: {milestone}"
        )
        A.assert_field_values(milestone, status="PENDING", days_late=0)


def test_availability_containment_is_enforced_at_the_offer_and_again_at_acceptance(api):
    """A window that only partly covers the seat is not coverage, at either gate.

    PRD: "**Availability containment** then requires that the writer has at least one availability window in `OPEN` status whose interval fully contains the seat's: the window must start at or before the seat's start and end at or after the seat's end."

    PRD: "Partial coverage is not coverage, and the absence of any such window is rejected with `ERR_WRITER_UNAVAILABLE`."

    PRD: "An offer is a proposal, and the writer answers it. Accepting is available only to the writer who holds the seat: the seat must still be `OFFERED` (otherwise `ERR_SEAT_NOT_OFFERED`), the acting `X-User-ID` must equal the seat's writer (otherwise `ERR_NOT_RESOURCE_OWNER`), the room must still be `STAFFING` (otherwise `ERR_ROOM_NOT_ACCEPTING_SEATS`), and the writer must still have an `OPEN` availability window containing the seat's whole interval (otherwise `ERR_WRITER_UNAVAILABLE`)."

    PRD: "The winning window moves to `CONSUMED` and records the seat in its `consumed_by_seat_id`, while the seat records the window in its `consumed_window_id` — a two-way link that makes the later release reversible."

    PRD: "The pair collides only when at least one of the two seats is `EXCLUSIVE`; two `NON_EXCLUSIVE` seats may overlap freely."

    Design: Corner/validations/availability_containment_is_enforced_at_the_offer_and_again_at_acceptance
    """
    world = X.build_staffing_room_world(api)
    X.seed_window(
        api, world["w3_id"], "EXCLUSIVE", K.WINDOW_START_DATE, W3_WINDOW_END
    )

    validate_error(
        api.offer_seat(
            world["room_id"],
            _seat_body(
                world["w3_id"],
                world["room_version"],
                level_at_hire="STAFF_WRITER",
                offered_weekly_compensation_cents=450000,
            ),
            world["sr_headers"],
        ),
        ApiErrorId.WRITER_UNAVAILABLE,
    )

    contained = X.seed_seat(
        api,
        world["room_id"],
        world["w3_id"],
        world["sr_headers"],
        level_at_hire="STAFF_WRITER",
        offered_weekly_compensation_cents=450000,
        end_date=W3_WINDOW_END,
    )
    A.assert_field_values(contained, status="OFFERED", consumed_window_id=None)

    early = X.seed_seat(
        api,
        world["room_id"],
        world["w2_id"],
        world["sr_headers"],
        exclusivity="NON_EXCLUSIVE",
        start_date=K.ROOM_START_DATE,
        end_date="2026-11-01T00:00:00Z",
    )
    overlapping = X.seed_seat(
        api,
        world["room_id"],
        world["w2_id"],
        world["sr_headers"],
        exclusivity="NON_EXCLUSIVE",
        start_date="2026-09-15T00:00:00Z",
        end_date="2027-01-01T00:00:00Z",
    )

    confirmed = X.accept_seat(api, early["id"], world["w2_id"])
    A.assert_field_values(
        confirmed, status="CONFIRMED", consumed_window_id=world["aw2_id"]
    )
    A.assert_field_values(
        X.read_window(api, world["aw2_id"]),
        status="CONSUMED",
        consumed_by_seat_id=early["id"],
    )

    validate_error(
        api.accept_seat(overlapping["id"], make_writer_headers(world["w2_id"])),
        ApiErrorId.WRITER_UNAVAILABLE,
    )
    A.assert_field_values(
        X.read_seat(api, overlapping["id"]), status="OFFERED", consumed_window_id=None
    )

    room = X.read_room(api, world["room_id"])
    A.assert_field_values(
        room, filled_seat_count=3, confirmed_seat_count=1, open_seat_count=0
    )
    A.assert_seat_capacity_conserved(room)
    A.assert_field_values(X.read_writer(api, world["w2_id"]), active_seat_count=2)


def test_predecessor_linkage_is_required_for_rewrites_and_forbidden_for_originals(api):
    """One field, two opposite refusals, decided by the assignment type.

    PRD: "**Predecessor linkage**: a `REWRITE` or a `PRODUCTION_POLISH` must name a `predecessor_assignment_id` that belongs to the same episode and whose status is `APPROVED`, and an absent, foreign-episode or unapproved predecessor is rejected with `ERR_PREDECESSOR_NOT_APPROVED`; conversely a `STORY`, `TELEPLAY` or `STORY_AND_TELEPLAY` must omit the field entirely, and supplying it is rejected with `ERR_PREDECESSOR_NOT_ALLOWED`."

    PRD: "An episode already at `READY` that receives a `REWRITE` returns to `IN_PROGRESS`, because a rewrite reopens the script — and it retains its `approved_teleplay_assignment_id`, so the clearance mirror keeps pointing at the draft that was actually approved."

    PRD: "a `REWRITE` gets a single `FIRST_DRAFT`"

    PRD: "The `coverage_posture` is then `COVERED` when the gap is exactly 0, `AT_RISK` when the gap is 1 or 2, and `CRITICAL` for any gap above 2."

    Design: Corner/validations/predecessor_linkage_is_required_for_rewrites_and_forbidden_for_originals
    """
    world = X.build_approved_assignment_world(api)
    story = X.seed_assignment(
        api, world["ep1_id"], world["w2_id"], world["sr_headers"], assignment_type="STORY"
    )
    A.assert_field_values(story, status="DRAFTING")
    A.assert_field_values(X.read_episode(api, world["ep1_id"]), script_readiness="READY")
    episode_version = X.current_episode_version(api, world["ep1_id"])

    validate_error(
        api.create_script_assignment(
            world["ep1_id"],
            F.build_script_assignment(world["w1_id"], episode_version, "REWRITE"),
            world["sr_headers"],
        ),
        ApiErrorId.PREDECESSOR_NOT_APPROVED,
    )
    validate_error(
        api.create_script_assignment(
            world["ep1_id"],
            F.build_script_assignment(
                world["w1_id"],
                episode_version,
                "REWRITE",
                predecessor_assignment_id=story["id"],
            ),
            world["sr_headers"],
        ),
        ApiErrorId.PREDECESSOR_NOT_APPROVED,
    )
    validate_error(
        api.create_script_assignment(
            world["ep1_id"],
            F.build_script_assignment(
                world["w1_id"],
                episode_version,
                "STORY_AND_TELEPLAY",
                predecessor_assignment_id=world["a1_id"],
            ),
            world["sr_headers"],
        ),
        ApiErrorId.PREDECESSOR_NOT_ALLOWED,
    )

    rewrite = validate_success(
        api.create_script_assignment(
            world["ep1_id"],
            F.build_script_assignment(
                world["w1_id"],
                episode_version,
                "REWRITE",
                predecessor_assignment_id=world["a1_id"],
            ),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_field_values(
        rewrite, status="DRAFTING", predecessor_assignment_id=world["a1_id"]
    )
    A.assert_assignment_settlement(rewrite, 1750000, False, 0, 1750000)

    chain = X.milestones_of(api, rewrite["id"])
    assert len(chain) == 1, f"A rewrite carries one milestone, got {chain}"
    A.assert_field_values(
        chain[0], milestone_type="FIRST_DRAFT", sequence_index=1, status="PENDING"
    )
    assert chain[0]["due_date"] == K.DUE_DATES_NOV_02["FIRST_DRAFT"], chain[0]

    episode = X.read_episode(api, world["ep1_id"])
    A.assert_field_values(
        episode,
        script_readiness="IN_PROGRESS",
        approved_teleplay_assignment_id=world["a1_id"],
    )
    assert _coverage(api, world["season_id"]) == (0, 1, "AT_RISK"), X.read_season(
        api, world["season_id"]
    )


def test_a_clearance_review_must_name_a_delivered_milestone_of_its_own_assignment(api):
    """A missing id, a foreign milestone and an undelivered one, kept apart.

    PRD: "The `reviewed_draft_milestone_id` must belong to that same assignment and must have a status in `DELIVERED`, `NOTES_ISSUED` or `ACCEPTED`; a milestone of another assignment, or one still `PENDING` or `LATE`, is rejected with `ERR_MILESTONE_NOT_IN_ASSIGNMENT`."

    PRD: "Resources referenced from a request body rather than the path are checked with the same codes: `guild_agreement_id`, `agreement_id`, `showrunner_writer_id`, `writer_id`, every id in `arbiter_writer_ids`, `predecessor_assignment_id` and `reviewed_draft_milestone_id` must all resolve to existing rows."

    PRD: "A new review starts with `posture` at `PENDING`, `risk_score` 0, `item_count` 0, `decided_item_count` 0, `legal_waiver_granted` false and `waiver_memo` null, and it sets the episode's `clearance_posture` to `PENDING`, which is also where a fresh episode already sits."

    Design: Corner/validations/a_clearance_review_must_name_a_delivered_milestone_of_its_own_assignment
    """
    world = X.build_assignment_world(api)
    outline_id, first_draft_id = world["a1_milestone_ids"][0], world["a1_milestone_ids"][1]
    delivered = X.deliver_milestone(api, outline_id, world["w1_id"])
    A.assert_field_values(delivered, status="DELIVERED")

    story = X.seed_assignment(
        api, world["ep1_id"], world["w2_id"], world["sr_headers"], assignment_type="STORY"
    )
    foreign = X.milestones_of(api, story["id"])[0]

    validate_error(
        api.create_clearance_review(
            world["a1_id"],
            F.build_clearance_review(NON_EXISTENT_UUID),
            LEGAL_COUNSEL_HEADERS,
        ),
        ApiErrorId.MILESTONE_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.create_clearance_review(
            world["a1_id"],
            F.build_clearance_review(foreign["id"]),
            LEGAL_COUNSEL_HEADERS,
        ),
        ApiErrorId.MILESTONE_NOT_IN_ASSIGNMENT,
    )
    A.assert_field_values(X.read_milestone(api, first_draft_id), status="PENDING")
    validate_error(
        api.create_clearance_review(
            world["a1_id"],
            F.build_clearance_review(first_draft_id),
            LEGAL_COUNSEL_HEADERS,
        ),
        ApiErrorId.MILESTONE_NOT_IN_ASSIGNMENT,
    )

    review = validate_success(
        api.create_clearance_review(
            world["a1_id"],
            F.build_clearance_review(outline_id),
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
        reviewed_draft_milestone_id=outline_id,
    )

    rows, meta = validate_paginated(
        api.list_clearance_reviews(
            LEGAL_COUNSEL_HEADERS, {"assignment_id": world["a1_id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1, f"Only the accepted review exists: {rows}"
    A.assert_field_values(X.read_assignment(api, world["a1_id"]), status="DRAFTING")
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), clearance_posture="PENDING"
    )


def test_closing_credits_needs_at_least_one_eligible_submission(api):
    """A submission exists, yet none survives the filter, so nothing is persisted.

    PRD: "The episode's `credit_status` must be `SUBMISSIONS_OPEN`, otherwise `ERR_SUBMISSION_WINDOW_CLOSED`, and the episode must have at least one submission, otherwise `ERR_NO_ELIGIBLE_SUBMISSIONS`."

    PRD: "The close then applies the eligibility filter: a submission becomes `ELIGIBLE` when its writer holds at least one script assignment on that episode with status `APPROVED`, and `INELIGIBLE` otherwise."

    PRD: "If the filter leaves *no* eligible submission the whole call is rejected with `ERR_NO_ELIGIBLE_SUBMISSIONS` and nothing is persisted — no status is written and the episode stays in `SUBMISSIONS_OPEN`."

    PRD: "A new submission's `status` is `SUBMITTED`, its `provisional_share_pct` is 0, its `arbitrated_share_pct` is null and its `receives_credit` is false."

    PRD: "The close writes each eligible submission's `provisional_share_pct`, writes the whole writer-id-to-share map into the episode's `provisional_credit_shares`, sets `receives_credit` on each eligible submission according to whether its provisional share is at or above the agreement's `credit_share_threshold_pct` (default 33, an inclusive comparison — a share of exactly 33 earns credit), moves `credit_status` to `SUBMISSIONS_CLOSED` and increments the episode's `version`."

    Design: Corner/validations/closing_credits_needs_at_least_one_eligible_submission
    """
    world = X.build_approved_assignment_world(api)
    drafting = X.seed_assignment(
        api, world["ep1_id"], world["w2_id"], world["sr_headers"], assignment_type="STORY"
    )
    A.assert_field_values(drafting, status="DRAFTING")

    ineligible = X.seed_credit_submission(
        api, world["ep1_id"], world["w2_id"], "STORY_BY", 30
    )
    A.assert_field_values(
        ineligible,
        status="SUBMITTED",
        provisional_share_pct=0,
        arbitrated_share_pct=None,
        receives_credit=False,
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), credit_status="SUBMISSIONS_OPEN"
    )

    validate_error(
        api.close_credit_submissions(world["ep1_id"], GUILD_ADMINISTRATOR_HEADERS),
        ApiErrorId.NO_ELIGIBLE_SUBMISSIONS,
    )
    stalled = X.read_episode(api, world["ep1_id"])
    A.assert_field_values(
        stalled, credit_status="SUBMISSIONS_OPEN", provisional_credit_shares={}
    )
    A.assert_field_values(
        X.read_submission(api, ineligible["id"]), status="SUBMITTED", provisional_share_pct=0
    )

    eligible = X.seed_credit_submission(
        api, world["ep1_id"], world["w1_id"], "WRITTEN_BY", 60
    )
    closed = X.close_submissions(api, world["ep1_id"])
    A.assert_field_values(
        closed,
        credit_status="SUBMISSIONS_CLOSED",
        provisional_credit_shares={world["w1_id"]: 100},
    )
    A.assert_field_values(
        X.read_submission(api, eligible["id"]),
        status="ELIGIBLE",
        provisional_share_pct=100,
        receives_credit=True,
    )
    A.assert_field_values(
        X.read_submission(api, ineligible["id"]),
        status="INELIGIBLE",
        provisional_share_pct=0,
        receives_credit=False,
    )


def test_the_staffing_budget_admits_the_last_exact_cent_and_refuses_the_next_seat(api):
    """The ceiling is inclusive, so the seat that lands exactly on it is hired.

    PRD: "The **staffing budget** test on a seat offer adds the new seat's own weekly compensation to the season's current commitment and requires the result to be at or below `staffing_budget_weekly_cents`; exceeding it is rejected with `ERR_SEASON_STAFFING_BUDGET_EXCEEDED`."

    PRD: "**Season staffing commitment** is the sum of `weekly_burn_cents` over the season's rooms whose status is `STAFFING` or `ACTIVE`; rooms that are still `OPEN` and rooms that have `WRAPPED` retain their computed burn but are excluded from the sum."

    PRD: "The room's `filled_seat_count` increases by one and its `open_seat_count` is recomputed as capacity minus filled seats; the writer's `active_seat_count` increases by one; the room's weekly figures and the season's staffing commitment are recomputed; and the room's `version` increments."

    Design: Corner/validations/the_staffing_budget_admits_the_last_exact_cent_and_refuses_the_next_seat
    """
    world = X.build_staffing_room_world(api, season_overrides=TIGHT_BUDGET)
    X.seed_window(api, world["w3_id"])
    spare = X.seed_writer(
        api, world["agreement_id"], "Nia Fowler", "GM-9001", career_episodic_credits=0
    )
    X.seed_window(api, spare["id"])
    A.assert_cents(
        X.read_season(api, world["season_id"])["staffing_commitment_weekly_cents"],
        K.ROOM_BURN_EMPTY_IN_PERSON,
        "staffing_commitment_weekly_cents",
    )

    top_seat = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
    )
    A.assert_cents(
        X.read_season(api, world["season_id"])["staffing_commitment_weekly_cents"],
        K.ROOM_BURN_EMPTY_IN_PERSON,
        "an offered seat is not yet a commitment",
    )
    X.accept_seat(api, top_seat["id"], world["w1_id"])
    A.assert_cents(
        X.read_season(api, world["season_id"])["staffing_commitment_weekly_cents"],
        K.ROOM_BURN_ONE_SEAT_600000,
        "staffing_commitment_weekly_cents",
    )

    exact = X.seed_seat(
        api,
        world["room_id"],
        world["w3_id"],
        world["sr_headers"],
        level_at_hire="STAFF_WRITER",
        offered_weekly_compensation_cents=450000,
    )
    A.assert_seat_pricing(exact, 450000, 450000, 0, 450000)
    X.accept_seat(api, exact["id"], world["w3_id"])
    room = X.read_room(api, world["room_id"])
    A.assert_room_burn(room, 1050000, K.FACILITY_TIER_1, 200000, 1250000)
    A.assert_cents(
        X.read_season(api, world["season_id"])["staffing_commitment_weekly_cents"],
        1250000,
        "the commitment sits exactly on the budget",
    )
    A.assert_field_values(room, confirmed_seat_count=2, filled_seat_count=2)

    validate_error(
        api.offer_seat(
            world["room_id"],
            _seat_body(
                spare["id"],
                X.current_room_version(api, world["room_id"]),
                level_at_hire="STAFF_WRITER",
                offered_weekly_compensation_cents=450000,
            ),
            world["sr_headers"],
        ),
        ApiErrorId.SEASON_STAFFING_BUDGET_EXCEEDED,
    )
    A.assert_field_values(X.read_room(api, world["room_id"]), filled_seat_count=2)
    assert len(_seat_rows(api, world["room_id"])) == 2, "The refused offer created a seat"
    A.assert_field_values(X.read_writer(api, spare["id"]), active_seat_count=0)


def test_a_ballot_must_cover_exactly_the_participants_and_sum_to_one_hundred(api):
    """A short map, a missing participant and a stranger all fail one way.

    PRD: "The `vote_shares` payload must have keys that are exactly the `participant_writer_ids` — no missing participant, no stranger — with integer values summing to exactly 100, otherwise `ERR_VOTE_SHARES_INVALID`."

    PRD: "and an arbiter who has already appeared as a key of `vote_ledger` is refused with `ERR_BALLOT_ALREADY_CAST` — ballots are append-only and are never revised."

    Design: Corner/validations/a_ballot_must_cover_exactly_the_participants_and_sum_to_one_hundred
    """
    world = X.build_arbitration_world(api)
    w1, w2 = world["w1_id"], world["w2_id"]
    A.assert_field_values(
        X.read_arbitration(api, world["arbitration_id"]),
        status="STATEMENTS_OPEN",
        votes_cast_count=0,
        vote_ledger={},
    )

    for shares in ({w1: 60, w2: 30}, {w1: 100}, {w1: 50, w2: 30, world["ar2_id"]: 20}):
        validate_error(
            api.cast_arbitration_vote(
                world["arbitration_id"],
                F.build_ballot(shares),
                make_writer_headers(world["ar1_id"]),
            ),
            ApiErrorId.VOTE_SHARES_INVALID,
        )
    A.assert_field_values(
        X.read_arbitration(api, world["arbitration_id"]),
        status="STATEMENTS_OPEN",
        votes_cast_count=0,
        vote_ledger={},
    )

    voted = X.cast_ballot(api, world["arbitration_id"], world["ar1_id"], {w1: 50, w2: 50})
    A.assert_field_values(
        voted,
        status="PANEL_VOTING",
        votes_cast_count=1,
        vote_ledger={world["ar1_id"]: {w1: 50, w2: 50}},
    )

    validate_error(
        api.cast_arbitration_vote(
            world["arbitration_id"],
            F.build_ballot({w1: 10, w2: 90}),
            make_writer_headers(world["ar1_id"]),
        ),
        ApiErrorId.BALLOT_ALREADY_CAST,
    )
    A.assert_field_values(
        X.read_arbitration(api, world["arbitration_id"]),
        votes_cast_count=1,
        vote_ledger={world["ar1_id"]: {w1: 50, w2: 50}},
    )


def test_pagination_bounds_are_enforced_before_any_row_is_read(api, agreement):
    """Out-of-range paging is a 400 even when the filters would have matched.

    PRD: "`limit` controls page size: it defaults to 10, may not be smaller than 1, and may not be larger than 100."

    PRD: "`offset` controls the starting position: it defaults to 0 and may not be negative."

    PRD: "A `limit` outside the inclusive range 1 through 100, or a negative `offset`, or a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    PRD: "Both parameters are echoed back in the `meta` object of the response alongside `total_count` — the number of records matching the filters before pagination is applied — and `has_more`, which is true when records remain beyond the current page."

    Design: Corner/validations/pagination_bounds_are_enforced_before_any_row_is_read
    """
    agreement_id = agreement["id"]
    for index, name in enumerate(("Ada Pike", "Bo Marsh", "Cyd Vale"), start=1):
        X.seed_writer(api, agreement_id, name, f"GM-77{index:02d}")

    for params in (
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"limit": 0, "determined_level": "PRODUCER"},
    ):
        validate_error(
            api.list_writers(GUILD_ADMINISTRATOR_HEADERS, params),
            ApiErrorId.INVALID_PAGINATION,
            expected_status=400,
        )

    rows, meta = validate_paginated(
        api.list_writers(GUILD_ADMINISTRATOR_HEADERS, {"limit": 100, "offset": 0})
    )
    A.assert_pagination_meta(meta, 3, False, 100, 0)
    assert len(rows) == 3, f"Every registered writer belongs on one page: {rows}"

    tail, tail_meta = validate_paginated(
        api.list_writers(GUILD_ADMINISTRATOR_HEADERS, {"limit": 1, "offset": 2})
    )
    A.assert_pagination_meta(tail_meta, 3, False, 1, 2)
    assert len(tail) == 1, f"The last page holds exactly one writer: {tail}"
