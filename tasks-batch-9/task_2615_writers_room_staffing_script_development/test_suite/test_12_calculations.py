"""Every derived figure the PRD names, probed where its inputs are chosen.

One test per breadth instance of the corner design's `calculations` section.
The emphasis is on which inputs a formula reads: the episode's length rather
than the season's, the named agreement rather than the newest one on file, and
the two-dimension conjunction behind the season's ready-script count.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import fixtures as X
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    GUILD_ADMINISTRATOR_HEADERS,
    STUDIO_EXECUTIVE_HEADERS,
)

REMOTE_ANNEX = {"name": "Remote Annex", "format": "REMOTE", "seat_capacity": 2}
UNOPENED_ROOM = {"name": "Unopened Room", "format": "IN_PERSON", "seat_capacity": 2}

HALF_HOUR_EPISODE = {
    "length_format": "HALF_HOUR",
    "production_unit": "UNIT_B",
    "production_start_date": "2026-11-16T00:00:00Z",
}

BAND_WRITERS = [
    ("Band One Low", "GM-3001", 1, "STAFF_WRITER"),
    ("Band Two Edge", "GM-3002", 2, "STORY_EDITOR"),
    ("Band Two High", "GM-3003", 3, "STORY_EDITOR"),
    ("Band Three Edge", "GM-3004", 4, "EXEC_STORY_EDITOR"),
    ("Band Three High", "GM-3005", 6, "EXEC_STORY_EDITOR"),
    ("Band Four Edge", "GM-3006", 7, "CO_PRODUCER"),
    ("Band Four High", "GM-3007", 11, "CO_PRODUCER"),
]


def _commitment(api, season_id):
    """The season's live weekly staffing commitment."""
    return X.read_season(api, season_id)["staffing_commitment_weekly_cents"]


def _committed_script_money(api, season_id):
    """The season's live committed script money."""
    return X.read_season(api, season_id)["script_fee_committed_cents"]


def _coverage(api, season_id):
    """The season's three coverage figures, as a tuple."""
    season = X.read_season(api, season_id)
    return (
        season["ready_script_count"],
        season["coverage_gap"],
        season["coverage_posture"],
    )


def test_writer_level_determination_is_inclusive_at_every_threshold_boundary(
    api, agreement
):
    """Seven writers probe each of the four thresholds one credit either side.

    PRD: "The rule is a descending threshold walk against the supplied agreement's `level_credit_thresholds`, and every comparison is inclusive — credits exactly equal to a threshold do reach that level."

    PRD: "Whichever agreement produced the answer is recorded in `level_determination_agreement_id`, which is null only for a writer who has never been determined."

    PRD: "A newly registered writer starts with no live seats and no on-screen credits, so `active_seat_count` and `on_screen_credit_count` both begin at 0."

    PRD: "the awarded count is added to the writer's `career_episodic_credits`, the threshold walk above is then re-run against the *post-award* total, and `determined_level` may consequently rise."

    Design: Corner/calculations/writer_level_determination_is_inclusive_at_every_threshold_boundary
    """
    assert K.LEVEL_CREDIT_THRESHOLDS == {
        "STORY_EDITOR": 2,
        "EXEC_STORY_EDITOR": 4,
        "CO_PRODUCER": 7,
        "PRODUCER": 12,
    }, "The rate card under test carries the thresholds these boundaries probe"

    seeded = {}
    for legal_name, member_id, credits, expected_level in BAND_WRITERS:
        writer = X.seed_writer(
            api,
            agreement["id"],
            legal_name,
            member_id,
            career_episodic_credits=credits,
        )
        seeded[credits] = writer
        A.assert_field_values(
            writer,
            career_episodic_credits=credits,
            determined_level=expected_level,
            level_determination_agreement_id=agreement["id"],
            active_seat_count=0,
            on_screen_credit_count=0,
            version=1,
        )

    promoted = validate_success(
        api.add_credit_history(
            seeded[11]["id"],
            {"episodic_credits_awarded": 1, "agreement_id": agreement["id"]},
            GUILD_ADMINISTRATOR_HEADERS,
        )
    )
    A.assert_field_values(
        promoted,
        career_episodic_credits=12,
        determined_level="PRODUCER",
        level_determination_agreement_id=agreement["id"],
        version=2,
    )

    rows, meta = validate_paginated(
        api.list_writers(
            GUILD_ADMINISTRATOR_HEADERS,
            {"determined_level": "EXEC_STORY_EDITOR", "limit": 100},
        )
    )
    assert meta["total_count"] == 2, (
        f"Only the writers at 4 and 6 credits sit in that band: {rows}"
    )
    assert sorted(row["id"] for row in rows) == sorted(
        [seeded[4]["id"], seeded[6]["id"]]
    ), f"The band holds exactly the two boundary writers: {rows}"


def test_script_fee_derivation_spans_both_lengths_and_three_type_shares(api):
    """Base times share, with the base read off the episode and not the season.

    PRD: "The base is the agreement's script fee in cents for the *episode's* `length_format`, not the season's; the share is the agreement's type share for the assignment's `assignment_type`."

    PRD: "The base multiplied by that share, rounded half up to whole cents, is the assignment's `gross_fee_cents`."

    PRD: "its own `length_format`, which selects the base script fee for its scripts and need not match the season default"

    PRD: "Under `FORWARD_COMMIT`, the candidates are the seat's assignments whose status is not `VOID`, ordered by `created_at` ascending; a slot is therefore committed at creation time, the earliest-created assignment wins the guarantee even if a later-created assignment is approved first, and approval performs no re-settlement at all."

    PRD: "The season's `script_fee_committed_cents` is then recomputed as the signed sum of every ledger entry of that season — it is never incremented in place."

    Design: Corner/calculations/script_fee_derivation_spans_both_lengths_and_three_type_shares
    """
    world = X.build_assignment_world(api)
    A.assert_field_values(
        X.read_season(api, world["season_id"]),
        length_format="ONE_HOUR",
        guarantee_application_mode="FORWARD_COMMIT",
    )
    A.assert_assignment_settlement(
        world["a1"], K.SCRIPT_FEE_ONE_HOUR["TELEPLAY"], True, 1750000, 1750000
    )

    story = X.seed_assignment(
        api, world["ep1_id"], world["w2_id"], world["sr_headers"], "STORY"
    )
    A.assert_assignment_settlement(
        story,
        K.SCRIPT_FEE_ONE_HOUR["STORY"],
        False,
        0,
        K.SCRIPT_FEE_ONE_HOUR["STORY"],
    )

    ep2 = X.seed_episode(api, world["season_id"], 2, **HALF_HOUR_EPISODE)
    A.assert_field_values(ep2, length_format="HALF_HOUR", script_readiness="NOT_STARTED")

    half_hour_teleplay = X.seed_assignment(
        api, ep2["id"], world["w1_id"], world["sr_headers"], "TELEPLAY"
    )
    A.assert_assignment_settlement(
        half_hour_teleplay,
        K.SCRIPT_FEE_HALF_HOUR["TELEPLAY"],
        False,
        0,
        K.SCRIPT_FEE_HALF_HOUR["TELEPLAY"],
    )
    assert (
        half_hour_teleplay["payable_fee_cents"] == world["a1"]["payable_fee_cents"]
    ), "Identical payables from different grosses: 1750000 either way"

    combined = X.seed_assignment(
        api, ep2["id"], world["w2_id"], world["sr_headers"], "STORY_AND_TELEPLAY"
    )
    A.assert_assignment_settlement(
        combined,
        K.SCRIPT_FEE_HALF_HOUR["STORY_AND_TELEPLAY"],
        False,
        0,
        K.SCRIPT_FEE_HALF_HOUR["STORY_AND_TELEPLAY"],
    )

    A.assert_cents(
        _committed_script_money(api, world["season_id"]),
        1750000 + 1500000 + 1750000 + 2500000,
        "script_fee_committed_cents",
    )
    A.assert_field_values(
        X.read_episode(api, ep2["id"]), script_readiness="IN_PROGRESS"
    )
    rows, meta = validate_paginated(
        api.list_script_assignments(
            STUDIO_EXECUTIVE_HEADERS, {"episode_id": ep2["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2, f"The half-hour episode holds two scripts: {rows}"


def test_fees_and_thresholds_come_from_the_named_agreement_not_the_newest_card(api):
    """Two rate cards coexist and each formula follows its own pointer.

    PRD: "A studio executive opens a season by naming its governing rate card through `guild_agreement_id`, its creative lead through `showrunner_writer_id`, and its `title` (1 to 200 characters)."

    PRD: "the `agreement_id` of the rate card whose credit thresholds should be applied to them"

    PRD: "The base is the agreement's script fee in cents for the *episode's* `length_format`, not the season's; the share is the agreement's type share for the assignment's `assignment_type`."

    PRD: "Nothing else participates in this computation — no seat, no room and no season is read, and a seat's `level_at_hire` is emphatically not an input to it."

    Design: Corner/calculations/fees_and_thresholds_come_from_the_named_agreement_not_the_newest_card
    """
    world = X.build_assignment_world(api)
    later_card = X.build_second_agreement(api)

    X.seed_window(api, world["w3_id"])
    other_season = X.seed_season(api, later_card["id"], world["sr_id"])
    room = X.seed_room(api, other_season["id"], world["sr_headers"])
    X.open_room(api, room["id"], world["sr_headers"])
    seat = X.seed_seat(
        api,
        room["id"],
        world["w3_id"],
        world["sr_headers"],
        level_at_hire="STAFF_WRITER",
        offered_weekly_compensation_cents=K.MIN_WEEKLY_CENTS_BY_LEVEL["STAFF_WRITER"],
    )
    X.accept_seat(api, seat["id"], world["w3_id"])
    X.activate_room(api, room["id"])
    ep3 = X.seed_episode(api, other_season["id"], 1)
    ep4 = X.seed_episode(
        api, other_season["id"], 2, length_format="HALF_HOUR", production_unit="UNIT_B"
    )

    teleplay = X.seed_assignment(
        api, ep3["id"], world["w3_id"], world["sr_headers"], "TELEPLAY"
    )
    A.assert_cents(teleplay["gross_fee_cents"], 5600000, "gross_fee_cents")
    story = X.seed_assignment(
        api, ep4["id"], world["w3_id"], world["sr_headers"], "STORY"
    )
    A.assert_cents(story["gross_fee_cents"], 900000, "gross_fee_cents")

    A.assert_cents(
        _committed_script_money(api, other_season["id"]),
        6500000,
        "script_fee_committed_cents",
    )
    A.assert_cents(
        _committed_script_money(api, world["season_id"]),
        1750000,
        "script_fee_committed_cents",
    )

    on_later_card = X.seed_writer(
        api, later_card["id"], "Card Three Writer", "GM-3101", career_episodic_credits=6
    )
    A.assert_field_values(
        on_later_card,
        determined_level="STORY_EDITOR",
        level_determination_agreement_id=later_card["id"],
    )
    on_first_card = X.seed_writer(
        api,
        world["agreement_id"],
        "Card One Writer",
        "GM-3102",
        career_episodic_credits=6,
    )
    A.assert_field_values(
        on_first_card,
        determined_level="EXEC_STORY_EDITOR",
        level_determination_agreement_id=world["agreement_id"],
    )

    A.assert_field_values(
        X.read_writer(api, world["w3_id"]),
        determined_level="STAFF_WRITER",
        level_determination_agreement_id=world["agreement_id"],
    )


def test_the_season_commitment_sums_only_staffing_and_active_rooms(api):
    """Three rooms in three states; the OPEN one and the WRAPPED one sit outside.

    PRD: "**Season staffing commitment** is the sum of `weekly_burn_cents` over the season's rooms whose status is `STAFFING` or `ACTIVE`; rooms that are still `OPEN` and rooms that have `WRAPPED` retain their computed burn but are excluded from the sum."

    PRD: "An `OPEN` room, however, is not yet a staffing commitment against the season's budget — see the room-posture rules in §3.4."

    PRD: "The room's weekly figures are recomputed and the season's staffing commitment is recomputed, and because a `WRAPPED` room is excluded from the commitment sum, wrapping is what actually returns the season's weekly burn to the budget."

    PRD: "Its `open_seat_count` equals its `seat_capacity`, its `filled_seat_count`, `confirmed_seat_count` and `confirmed_diversity_seat_count` are all 0, and the room's weekly-cost figures are computed immediately over that empty seat set, which lands `facility_tier` at `TIER_1`."

    Design: Corner/calculations/the_season_commitment_sums_only_staffing_and_active_rooms
    """
    world = X.build_staffing_room_world(api)
    seat = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
    )
    X.accept_seat(api, seat["id"], world["w1_id"])
    main_room = X.activate_room(api, world["room_id"])
    A.assert_room_burn(
        main_room,
        600000,
        K.FACILITY_TIER_1,
        K.ROOM_BURN_EMPTY_IN_PERSON,
        K.ROOM_BURN_ONE_SEAT_600000,
    )
    A.assert_cents(
        _commitment(api, world["season_id"]),
        K.ROOM_BURN_ONE_SEAT_600000,
        "staffing_commitment_weekly_cents",
    )

    annex = X.seed_room(api, world["season_id"], world["sr_headers"], **REMOTE_ANNEX)
    annex = X.open_room(api, annex["id"], world["sr_headers"])
    A.assert_field_values(annex, status="STAFFING")
    A.assert_room_burn(
        annex,
        0,
        K.FACILITY_TIER_1,
        K.ROOM_BURN_EMPTY_REMOTE,
        K.ROOM_BURN_EMPTY_REMOTE,
    )
    A.assert_cents(
        _commitment(api, world["season_id"]),
        K.ROOM_BURN_ONE_SEAT_600000 + K.ROOM_BURN_EMPTY_REMOTE,
        "staffing_commitment_weekly_cents",
    )

    unopened = X.seed_room(api, world["season_id"], world["sr_headers"], **UNOPENED_ROOM)
    A.assert_field_values(unopened, status="OPEN")
    A.assert_room_burn(
        unopened,
        0,
        K.FACILITY_TIER_1,
        K.ROOM_BURN_EMPTY_IN_PERSON,
        K.ROOM_BURN_EMPTY_IN_PERSON,
    )
    A.assert_cents(
        _commitment(api, world["season_id"]),
        K.ROOM_BURN_ONE_SEAT_600000 + K.ROOM_BURN_EMPTY_REMOTE,
        "staffing_commitment_weekly_cents",
    )

    wrapped = validate_success(
        api.wrap_room(world["room_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    A.assert_field_values(wrapped, status="WRAPPED")
    A.assert_cents(
        _commitment(api, world["season_id"]),
        K.ROOM_BURN_EMPTY_REMOTE,
        "staffing_commitment_weekly_cents",
    )
    A.assert_room_burn(
        X.read_room(api, world["room_id"]),
        0,
        K.FACILITY_TIER_1,
        K.ROOM_BURN_EMPTY_IN_PERSON,
        K.ROOM_BURN_EMPTY_IN_PERSON,
    )


def test_coverage_counts_an_episode_only_when_readiness_and_clearance_both_qualify(api):
    """One episode observed at five points; only the last two count toward coverage.

    PRD: "An episode counts toward `ready_script_count` only when *both* dimensions permit: its `script_readiness` is `READY` or `LOCKED`, **and** its `clearance_posture` is `CLEARED` or `CONDITIONAL_WAIVED`."

    PRD: "An episode with an approved teleplay but a `PENDING`, `CONDITIONAL`, `ESCALATED` or `BLOCKED` clearance posture does not count, and neither does a fully cleared episode whose script is only `NOT_STARTED` or `IN_PROGRESS`."

    PRD: "Locked episodes keep counting — locking never lowers coverage."

    PRD: "The `coverage_posture` is then `COVERED` when the gap is exactly 0, `AT_RISK` when the gap is 1 or 2, and `CRITICAL` for any gap above 2."

    PRD: "A successful lock sets `script_readiness` to `LOCKED`, stamps `locked_at` from the logical clock, recomputes the season's coverage figures and increments the episode's `version`."

    Design: Corner/calculations/coverage_counts_an_episode_only_when_readiness_and_clearance_both_qualify
    """
    world = X.build_episode_world(api)
    A.assert_field_values(
        X.read_season(api, world["season_id"]), ready_script_target=1
    )
    assert _coverage(api, world["season_id"]) == (0, 1, "AT_RISK"), (
        "A season with one NOT_STARTED episode is one ready script short"
    )

    assignment = X.seed_assignment(
        api,
        world["ep1_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_episode_version=world["ep1_version"],
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), script_readiness="IN_PROGRESS"
    )
    assert _coverage(api, world["season_id"]) == (0, 1, "AT_RISK"), (
        "Work in progress is not a ready script"
    )

    milestones = X.deliver_all(api, assignment["id"], world["w1_id"])
    X.approve_assignment(api, assignment["id"])
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]),
        script_readiness="READY",
        clearance_posture="PENDING",
    )
    assert _coverage(api, world["season_id"]) == (0, 1, "AT_RISK"), (
        "Readiness alone never counts while clearance is still PENDING"
    )

    review = X.seed_clearance_review(api, assignment["id"], milestones[-1]["id"])
    item = X.seed_clearance_item(api, review["id"], "NAME")
    X.decide_item(api, item["id"], "CLEARED")
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), clearance_posture="CLEARED"
    )
    assert _coverage(api, world["season_id"]) == (1, 0, "COVERED"), (
        "Both dimensions now permit, so the episode counts"
    )

    locked = validate_success(
        api.lock_episode_for_production(world["ep1_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    A.assert_field_values(locked, script_readiness="LOCKED")
    A.assert_instant(locked["locked_at"], K.CLOCK_EPOCH, "locked_at")
    assert _coverage(api, world["season_id"]) == (1, 0, "COVERED"), (
        "LOCKED is inside the readiness input set, so the count does not fall back"
    )


def test_milestone_due_dates_are_lead_day_offsets_stamped_at_end_of_day(api):
    """Four leads subtracted across a month and a year boundary, at end of day.

    PRD: "A due date is computed by taking the UTC calendar date of the owning episode's `production_start_date`, subtracting the whole number of lead days for that milestone type, and stamping the resulting UTC date at `23:59:59.999Z`."

    PRD: "All four due-date fields — `outline_due_date`, `first_draft_due_date`, `second_draft_due_date` and `polish_due_date` — are always populated on the assignment itself regardless of its type, each computed by taking the UTC calendar date of the episode's `production_start_date`, subtracting the agreement's lead days for that milestone kind, and stamping the resulting date at `23:59:59.999Z`."

    PRD: "Each milestone is numbered by `sequence_index` starting at 1 in that chain order, copies the matching due-date field into its own `due_date`, and starts `PENDING` — or `LATE` immediately, if the logical clock has already passed that deadline at the moment the assignment is created."

    Design: Corner/calculations/milestone_due_dates_are_lead_day_offsets_stamped_at_end_of_day
    """
    world = X.build_assignment_world(api)
    late_episode = X.seed_episode(
        api,
        world["season_id"],
        3,
        production_start_date=K.RESCHEDULED_PRODUCTION_START,
    )
    A.assert_instant(
        late_episode["production_start_date"],
        K.RESCHEDULED_PRODUCTION_START,
        "production_start_date",
    )

    assignment = X.seed_assignment(
        api, late_episode["id"], world["w2_id"], world["sr_headers"], "TELEPLAY"
    )
    A.assert_field_values(
        assignment,
        outline_due_date=K.DUE_DATES_JAN_04["OUTLINE"],
        first_draft_due_date=K.DUE_DATES_JAN_04["FIRST_DRAFT"],
        second_draft_due_date=K.DUE_DATES_JAN_04["SECOND_DRAFT"],
        polish_due_date=K.DUE_DATES_JAN_04["POLISH"],
    )

    milestones = X.milestones_of(api, assignment["id"])
    assert [m["milestone_type"] for m in milestones] == [
        "OUTLINE",
        "FIRST_DRAFT",
        "SECOND_DRAFT",
    ], f"A teleplay chain in due-date order: {milestones}"
    for index, milestone in enumerate(milestones, start=1):
        A.assert_field_values(
            milestone,
            sequence_index=index,
            status="PENDING",
            days_late=0,
            due_date=K.DUE_DATES_JAN_04[milestone["milestone_type"]],
        )

    A.assert_field_values(
        X.read_assignment(api, world["a1_id"]),
        outline_due_date=K.DUE_DATES_NOV_02["OUTLINE"],
        first_draft_due_date=K.DUE_DATES_NOV_02["FIRST_DRAFT"],
        second_draft_due_date=K.DUE_DATES_NOV_02["SECOND_DRAFT"],
        polish_due_date=K.DUE_DATES_NOV_02["POLISH"],
    )
    A.assert_instant(
        X.read_episode(api, late_episode["id"])["production_start_date"],
        K.RESCHEDULED_PRODUCTION_START,
        "production_start_date",
    )


def test_a_blocked_clearance_item_overrides_the_score_ladder(api):
    """Twenty points of BLOCKED outrank a score ladder the sum never reaches.

    PRD: "The decision sets the item's `risk_weight` to the agreement's `clearance_item_weights` entry for the item's `item_type` multiplied by a decision multiplier of 0 for `CLEARED`, 1 for `CONDITIONAL` and 4 for `BLOCKED`."

    PRD: "A new item's `decision` is `SUBMITTED`, its `conditional_note` is null, and its `risk_weight` is 0 — an undecided item carries no risk weight even though its type already implies one."

    PRD: "The review's `risk_score` is then the sum of `risk_weight` over its items whose `decision` is `CLEARED`, `CONDITIONAL` or `BLOCKED`, capped at 100 — the cap applies to the sum, not to any individual weight — and `decided_item_count` is the count of those same items."

    PRD: "`BLOCKED` when any item's `decision` is `BLOCKED`, whatever the score."

    PRD: "Second the clearance gate: the episode's `clearance_posture` must be `CLEARED` or `CONDITIONAL_WAIVED`, and a failure is reported as `ERR_CLEARANCE_BLOCKED` when the posture is `BLOCKED` and as `ERR_CLEARANCE_NOT_CLEARED` for `PENDING`, `CONDITIONAL` or `ESCALATED` — two distinct codes for one gate, so the caller can tell a fatal exposure from an unfinished one."

    Design: Corner/calculations/a_blocked_clearance_item_overrides_the_score_ladder_and_undecided_items_score_zero
    """
    world = X.build_clearance_world(api)
    depiction = X.seed_clearance_item(
        api, world["review_id"], "DEPICTION", "Real hospital shown mid-malpractice", "3B"
    )
    name = X.seed_clearance_item(
        api, world["review_id"], "NAME", "Character surname Kowalczyk", "1A"
    )
    A.assert_field_values(depiction, decision="SUBMITTED", risk_weight=0)
    A.assert_field_values(name, decision="SUBMITTED", risk_weight=0)

    blocked = X.decide_item(api, name["id"], "BLOCKED")
    A.assert_field_values(blocked, decision="BLOCKED", risk_weight=20)
    A.assert_field_values(
        X.read_item(api, depiction["id"]), decision="SUBMITTED", risk_weight=0
    )

    A.assert_field_values(
        X.read_review(api, world["review_id"]),
        risk_score=20,
        decided_item_count=1,
        item_count=2,
        posture="BLOCKED",
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]),
        clearance_posture="BLOCKED",
        script_readiness="READY",
    )

    validate_error(
        api.lock_episode_for_production(world["ep1_id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.CLEARANCE_BLOCKED,
    )
    A.assert_field_values(X.read_episode(api, world["ep1_id"]), locked_at=None)
    assert _coverage(api, world["season_id"]) == (0, 1, "AT_RISK"), (
        "A blocked episode contributes nothing to coverage"
    )
