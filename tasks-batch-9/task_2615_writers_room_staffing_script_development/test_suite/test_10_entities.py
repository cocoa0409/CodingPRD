"""Entity surface: creation defaults, derived-on-create fields, reads and lists.

One test per breadth instance of the corner design's `entities` section. Each
test drives only PRD endpoints and asserts only what the PRD's own sentences
pin down for a freshly created row.
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
    make_showrunner_headers,
    make_writer_headers,
)


def _rows(response):
    """The data array of a paginated response."""
    rows, _ = validate_paginated(response)
    return rows


def _page(api, lister, **params):
    """A single page of a list endpoint read as the guild administrator."""
    return validate_paginated(lister(GUILD_ADMINISTRATOR_HEADERS, params))


def test_registering_the_rate_card_echoes_every_declared_field(api):
    """The whole rate card comes back verbatim, with the common quartet minted.

    PRD: "It is identified by its `mba_year`, an integer between 2020 and 2035 inclusive that is unique across all guild agreements."

    PRD: "Six of its fields are keyed objects whose key sets are fixed and must be supplied exactly"

    PRD: "Every persisted resource carries an `id`, which is a server-minted UUID with no type prefix; clients never supply ids for the resources they create."

    PRD: "Registering a Minimum Basic Agreement creates a configuration row and nothing else: no season, room or writer is touched by it, and the row is never mutated afterwards"

    Design: Corner/entities/guild_agreement_creation_echoes_the_whole_rate_card_in_the_success_envelope
    """
    payload = F.build_guild_agreement()
    created = validate_success(
        api.create_guild_agreement(payload, GUILD_ADMINISTRATOR_HEADERS),
        expected_status=201,
    )

    A.assert_common_fields(created)
    A.assert_field_values(created, version=1, **payload)
    assert created["created_at"] == created["updated_at"], (
        "An unmutated row's updated_at equals its created_at: "
        f"{created['created_at']} vs {created['updated_at']}"
    )

    fetched = validate_success(
        api.get_guild_agreement(created["id"], STUDIO_EXECUTIVE_HEADERS)
    )
    assert fetched == created, "The read must return the stored row unchanged"

    assert _rows(api.list_seasons(STUDIO_EXECUTIVE_HEADERS, {"limit": 100})) == [], (
        "Registering a rate card creates no season"
    )
    assert _rows(api.list_writers(GUILD_ADMINISTRATOR_HEADERS, {"limit": 100})) == [], (
        "Registering a rate card creates no writer"
    )


def test_registering_writers_derives_each_level_and_zeroes_the_counters(api):
    """Twenty credits, three credits and none walk the thresholds to three levels.

    PRD: "If the writer's career episodic credits are at least the `PRODUCER` threshold, `determined_level` becomes `PRODUCER`; otherwise, if they are at least the `CO_PRODUCER` threshold, the level is `CO_PRODUCER`; otherwise, if they are at least the `EXEC_STORY_EDITOR` threshold, the level is `EXEC_STORY_EDITOR`; otherwise, if they are at least the `STORY_EDITOR` threshold, the level is `STORY_EDITOR`; and if none of those hold, the level is `STAFF_WRITER`."

    PRD: "Whichever agreement produced the answer is recorded in `level_determination_agreement_id`, which is null only for a writer who has never been determined."

    PRD: "A newly registered writer starts with no live seats and no on-screen credits, so `active_seat_count` and `on_screen_credit_count` both begin at 0."

    Design: Corner/entities/writer_creation_runs_level_determination_and_zeroes_the_derived_counters
    """
    agreement = X.seed_agreement(api)

    producer = validate_success(
        api.create_writer(
            F.build_writer(
                agreement["id"],
                "Sloane Reyes",
                "GM-SHOW",
                career_episodic_credits=20,
                is_showrunner_eligible=True,
            ),
            GUILD_ADMINISTRATOR_HEADERS,
        ),
        expected_status=201,
    )
    editor = validate_success(
        api.create_writer(
            F.build_writer(
                agreement["id"], "Wanda Cole", "GM-1001", career_episodic_credits=3
            ),
            GUILD_ADMINISTRATOR_HEADERS,
        ),
        expected_status=201,
    )
    staff = validate_success(
        api.create_writer(
            F.build_minimal_writer(agreement["id"], "Ivy Nakamura", "GM-1003"),
            GUILD_ADMINISTRATOR_HEADERS,
        ),
        expected_status=201,
    )

    for writer, level, credits in (
        (producer, "PRODUCER", 20),
        (editor, "STORY_EDITOR", 3),
        (staff, "STAFF_WRITER", 0),
    ):
        A.assert_common_fields(writer)
        A.assert_field_values(
            writer,
            determined_level=level,
            career_episodic_credits=credits,
            level_determination_agreement_id=agreement["id"],
            active_seat_count=0,
            on_screen_credit_count=0,
            version=1,
        )

    A.assert_field_values(
        producer, legal_name="Sloane Reyes", is_showrunner_eligible=True
    )
    A.assert_field_values(
        staff, diversity_program_participant=False, is_showrunner_eligible=False
    )


def test_declaring_availability_starts_the_window_open_and_unconsumed(api):
    """Both commitment types are stored, and neither window backs a seat yet.

    PRD: "A window names the writer it belongs to through the path, and carries a `start_date` and an `end_date` — the interval is half-open, so it covers the start instant but not the end instant — plus a `commitment_type` of either `EXCLUSIVE`, meaning the window may back at most one occupying seat interval at a time, or `NON_EXCLUSIVE`, meaning overlapping seats may draw on it."

    PRD: "Every window is created `OPEN` with no consuming seat, so its `consumed_by_seat_id` is null; it becomes `CONSUMED` only when a seat acceptance claims it, and returns to `OPEN` when that seat is released."

    Design: Corner/entities/availability_window_creation_starts_open_with_no_consuming_seat
    """
    agreement = X.seed_agreement(api)
    w1 = X.seed_writer(api, agreement["id"], "Wanda Cole", "GM-1001")
    w2 = X.seed_writer(api, agreement["id"], "Bram Ochoa", "GM-1002")

    exclusive = validate_success(
        api.create_availability_window(
            w1["id"], F.build_availability_window(), make_writer_headers(w1["id"])
        ),
        expected_status=201,
    )
    shared = validate_success(
        api.create_availability_window(
            w2["id"],
            F.build_availability_window(commitment_type="NON_EXCLUSIVE"),
            GUILD_ADMINISTRATOR_HEADERS,
        ),
        expected_status=201,
    )

    A.assert_common_fields(exclusive)
    A.assert_field_values(
        exclusive,
        writer_id=w1["id"],
        commitment_type="EXCLUSIVE",
        status="OPEN",
        consumed_by_seat_id=None,
        version=1,
    )
    A.assert_instant(exclusive["start_date"], K.WINDOW_START_DATE, "start_date")
    A.assert_instant(exclusive["end_date"], K.WINDOW_END_DATE, "end_date")
    A.assert_field_values(
        shared,
        writer_id=w2["id"],
        commitment_type="NON_EXCLUSIVE",
        status="OPEN",
        consumed_by_seat_id=None,
    )

    rows, meta = _page(api, api.list_availability_windows, status="OPEN", limit=100)
    assert sorted(r["id"] for r in rows) == sorted([exclusive["id"], shared["id"]]), (
        f"Both windows are OPEN and neither is consumed: {rows}"
    )
    assert meta["total_count"] == 2, f"Expected two open windows: {meta}"


def test_creating_a_season_zeroes_the_money_and_derives_coverage_at_once(api):
    """Nothing is committed, nothing is ready, and the posture is already computed.

    PRD: "A freshly created season has committed nothing and finished nothing, so `staffing_commitment_weekly_cents`, `script_fee_committed_cents` and `ready_script_count` all start at 0, and the coverage figures are computed immediately from that empty state."

    PRD: "The `coverage_posture` is then `COVERED` when the gap is exactly 0, `AT_RISK` when the gap is 1 or 2, and `CRITICAL` for any gap above 2."

    PRD: "`guarantee_application_mode` is either `FORWARD_COMMIT` or `CHRONOLOGICAL_ON_ACCEPTANCE`, and it defaults to `CHRONOLOGICAL_ON_ACCEPTANCE`."

    Design: Corner/entities/season_creation_initialises_the_fiscal_counters_and_derives_coverage_at_once
    """
    world = X.build_registry(api)

    at_risk = validate_success(
        api.create_season(
            F.build_season(world["agreement_id"], world["sr_id"], ready_script_target=1),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        expected_status=201,
    )
    critical = validate_success(
        api.create_season(
            F.build_minimal_season(
                world["agreement_id"], world["sr_id"], ready_script_target=5
            ),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        expected_status=201,
    )

    A.assert_common_fields(at_risk)
    A.assert_cents(
        at_risk["staffing_commitment_weekly_cents"],
        0,
        "staffing_commitment_weekly_cents",
    )
    A.assert_cents(
        at_risk["script_fee_committed_cents"], 0, "script_fee_committed_cents"
    )
    A.assert_field_values(
        at_risk,
        guild_agreement_id=world["agreement_id"],
        showrunner_writer_id=world["sr_id"],
        ready_script_count=0,
        ready_script_target=1,
        coverage_gap=1,
        coverage_posture="AT_RISK",
        guarantee_application_mode="FORWARD_COMMIT",
        version=1,
    )

    A.assert_field_values(
        critical,
        ready_script_count=0,
        coverage_gap=5,
        coverage_posture="CRITICAL",
        guarantee_application_mode="CHRONOLOGICAL_ON_ACCEPTANCE",
        version=1,
    )
    A.assert_cents(
        critical["script_fee_committed_cents"], 0, "script_fee_committed_cents"
    )


def test_creating_a_room_starts_open_with_every_seat_free_and_tier_one(api):
    """An empty room is priced immediately: subtotal 0, TIER_1, surcharge only.

    PRD: "A new room is `OPEN` and empty. Its `open_seat_count` equals its `seat_capacity`, its `filled_seat_count`, `confirmed_seat_count` and `confirmed_diversity_seat_count` are all 0, and the room's weekly-cost figures are computed immediately over that empty seat set, which lands `facility_tier` at `TIER_1`."

    PRD: "Step three multiplies the facility fee for the selected tier by the agreement's format surcharge fraction for the room's `format` and rounds the product to whole cents, giving `facility_surcharge_weekly_cents`."

    PRD: "**Season staffing commitment** is the sum of `weekly_burn_cents` over the season's rooms whose status is `STAFFING` or `ACTIVE`; rooms that are still `OPEN` and rooms that have `WRAPPED` retain their computed burn but are excluded from the sum."

    Design: Corner/entities/room_creation_starts_open_with_every_seat_free_and_tier_one_facility_fee
    """
    world = X.build_season_world(api)
    payload = F.build_room()

    room = validate_success(
        api.create_room(world["season_id"], payload, world["sr_headers"]),
        expected_status=201,
    )

    A.assert_common_fields(room)
    A.assert_field_values(
        room,
        season_id=world["season_id"],
        name=payload["name"],
        format="IN_PERSON",
        seat_capacity=3,
        duration_weeks_committed=26,
        diversity_seats_required=0,
        status="OPEN",
        open_seat_count=3,
        filled_seat_count=0,
        confirmed_seat_count=0,
        confirmed_diversity_seat_count=0,
        version=1,
    )
    A.assert_instant(room["start_date"], K.ROOM_START_DATE, "start_date")
    A.assert_instant(room["end_date"], K.ROOM_END_DATE, "end_date")
    A.assert_seat_capacity_conserved(room)
    A.assert_room_burn(
        room,
        0,
        K.FACILITY_TIER_1,
        K.ROOM_BURN_EMPTY_IN_PERSON,
        K.ROOM_BURN_EMPTY_IN_PERSON,
    )

    A.assert_cents(
        X.read_season(api, world["season_id"])["staffing_commitment_weekly_cents"],
        0,
        "staffing_commitment_weekly_cents",
    )


def test_offering_a_seat_computes_the_floor_the_proration_and_the_slots(api):
    """The offer is priced and dated on creation while contributing nothing to the burn.

    PRD: "A surviving offer creates the seat in `OFFERED` status with all four compensation figures and the prorated commitment computed, `guarantee_slots_consumed` at 0 and `guarantee_slots_remaining` equal to the seat's `episodic_guarantee_count`, `confirmed_at` and `consumed_window_id` both null."

    PRD: "The seat's `weekly_compensation_cents` is then the greater of the studio's `offered_weekly_compensation_cents` and that floor, so a generous offer stands and a thin one is lifted to the floor."

    PRD: "Round the weekly compensation divided by 7 to whole cents **first** to obtain a daily rate, then multiply that rounded daily rate by the residual days, and add the product of the full weeks and the full weekly compensation."

    PRD: "Step one sums `weekly_compensation_cents` across only those seats of the room whose status is `CONFIRMED`, producing `seat_subtotal_weekly_cents`; seats merely `OFFERED` contribute nothing."

    Design: Corner/entities/seat_offer_creation_computes_floor_weekly_prorated_and_guarantee_slots
    """
    world = X.build_staffing_room_world(api)

    seat = validate_success(
        api.offer_seat(
            world["room_id"],
            F.build_seat_offer(world["w1_id"], world["room_version"]),
            world["sr_headers"],
        ),
        expected_status=201,
    )

    A.assert_common_fields(seat)
    A.assert_field_values(
        seat,
        room_id=world["room_id"],
        writer_id=world["w1_id"],
        level_at_hire="STORY_EDITOR",
        exclusivity="EXCLUSIVE",
        status="OFFERED",
        episodic_guarantee_count=1,
        guarantee_slots_consumed=0,
        guarantee_slots_remaining=1,
        diversity_program_funded=False,
        confirmed_at=None,
        consumed_window_id=None,
        version=1,
    )
    A.assert_guarantee_slots_conserved(seat)
    A.assert_seat_pricing(
        seat, 600000, 600000, 0, 600000, K.SEAT_PRORATED_181_DAYS_AT_600000
    )

    room = X.read_room(api, world["room_id"])
    A.assert_field_values(
        room, filled_seat_count=1, open_seat_count=2, confirmed_seat_count=0
    )
    A.assert_room_burn(
        room,
        0,
        K.FACILITY_TIER_1,
        K.ROOM_BURN_EMPTY_IN_PERSON,
        K.ROOM_BURN_EMPTY_IN_PERSON,
    )
    A.assert_cents(
        X.read_season(api, world["season_id"])["staffing_commitment_weekly_cents"],
        K.ROOM_BURN_EMPTY_IN_PERSON,
        "staffing_commitment_weekly_cents",
    )
    A.assert_field_values(X.read_window(api, world["aw1_id"]), status="OPEN")


def test_ordering_an_episode_starts_all_three_posture_dimensions_at_the_bottom(api):
    """Readiness, credit and clearance all start at their initial values.

    PRD: "A new episode starts at the bottom of all three of its state dimensions: `script_readiness` is `NOT_STARTED`, `credit_status` is `PENDING`, and `clearance_posture` is `PENDING`."

    PRD: "It has no approved teleplay, so `approved_teleplay_assignment_id` is null; it has no credit maps, so `provisional_credit_shares` and `final_credit_shares` are empty objects and `determined_credit_string` is null; and it is not locked, so `locked_at` is null."

    PRD: "Adding the episode also re-runs the season's coverage computation, because the season now has one more episode that might or might not be ready."

    Design: Corner/entities/episode_creation_starts_all_three_posture_dimensions_at_their_initial_values
    """
    world = X.build_active_room_world(api)

    episode = validate_success(
        api.create_episode(
            world["season_id"], F.build_episode(1), STUDIO_EXECUTIVE_HEADERS
        ),
        expected_status=201,
    )

    A.assert_common_fields(episode)
    A.assert_field_values(
        episode,
        season_id=world["season_id"],
        episode_number=1,
        length_format="ONE_HOUR",
        production_unit="UNIT_A",
        shoot_days=8,
        script_readiness="NOT_STARTED",
        credit_status="PENDING",
        clearance_posture="PENDING",
        approved_teleplay_assignment_id=None,
        determined_credit_string=None,
        provisional_credit_shares={},
        final_credit_shares={},
        locked_at=None,
        version=1,
    )
    A.assert_instant(
        episode["production_start_date"], K.SEASON_PRODUCTION_START, "production_start_date"
    )

    A.assert_field_values(
        X.read_season(api, world["season_id"]),
        ready_script_count=0,
        coverage_gap=1,
        coverage_posture="AT_RISK",
    )


def test_creating_an_assignment_synthesizes_only_its_own_milestone_chain(api):
    """A teleplay gets three milestones and a story exactly one, both fully dated.

    PRD: "The milestone rows themselves, by contrast, are synthesized to match the type, each carrying its kind in `milestone_type`: a `STORY` assignment gets a single `OUTLINE` milestone; a `TELEPLAY` and a `STORY_AND_TELEPLAY` each get `OUTLINE`, `FIRST_DRAFT` and `SECOND_DRAFT`; a `REWRITE` gets a single `FIRST_DRAFT`; and a `PRODUCTION_POLISH` gets a single `PRODUCTION_POLISH`."

    PRD: "All four due-date fields — `outline_due_date`, `first_draft_due_date`, `second_draft_due_date` and `polish_due_date` — are always populated on the assignment itself regardless of its type, each computed by taking the UTC calendar date of the episode's `production_start_date`, subtracting the agreement's lead days for that milestone kind, and stamping the resulting date at `23:59:59.999Z`."

    PRD: "Each milestone is numbered by `sequence_index` starting at 1 in that chain order, copies the matching due-date field into its own `due_date`, and starts `PENDING` — or `LATE` immediately, if the logical clock has already passed that deadline at the moment the assignment is created."

    PRD: "The assignment is created in `DRAFTING`, its `revision_round` at 0, its `approved_at` and `approved_by_role` null, and its `late_milestone_count` at 0."

    Design: Corner/entities/assignment_creation_synthesizes_only_the_teleplay_milestone_chain
    """
    world = X.build_episode_world(api)

    teleplay = validate_success(
        api.create_script_assignment(
            world["ep1_id"],
            F.build_script_assignment(
                world["w1_id"], world["ep1_version"], assignment_type="TELEPLAY"
            ),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_common_fields(teleplay)
    A.assert_field_values(
        teleplay,
        episode_id=world["ep1_id"],
        writer_id=world["w1_id"],
        assignment_type="TELEPLAY",
        room_seat_id=world["s1_id"],
        status="DRAFTING",
        revision_round=0,
        approved_at=None,
        approved_by_role=None,
        late_milestone_count=0,
        outline_due_date=K.DUE_DATES_NOV_02["OUTLINE"],
        first_draft_due_date=K.DUE_DATES_NOV_02["FIRST_DRAFT"],
        second_draft_due_date=K.DUE_DATES_NOV_02["SECOND_DRAFT"],
        polish_due_date=K.DUE_DATES_NOV_02["POLISH"],
        version=1,
    )
    A.assert_assignment_settlement(teleplay, 3500000, True, 1750000, 1750000)

    chain = X.milestones_of(api, teleplay["id"])
    assert [m["milestone_type"] for m in chain] == [
        "OUTLINE",
        "FIRST_DRAFT",
        "SECOND_DRAFT",
    ], f"A teleplay chain is exactly three milestones: {chain}"
    assert [m["sequence_index"] for m in chain] == [1, 2, 3], (
        f"The chain is numbered from 1: {chain}"
    )
    for milestone, due in zip(
        chain,
        (
            K.DUE_DATES_NOV_02["OUTLINE"],
            K.DUE_DATES_NOV_02["FIRST_DRAFT"],
            K.DUE_DATES_NOV_02["SECOND_DRAFT"],
        ),
    ):
        A.assert_field_values(
            milestone,
            assignment_id=teleplay["id"],
            status="PENDING",
            days_late=0,
            delivered_at=None,
            due_date=due,
        )

    story = validate_success(
        api.create_script_assignment(
            world["ep1_id"],
            F.build_script_assignment(
                world["w2_id"],
                X.current_episode_version(api, world["ep1_id"]),
                assignment_type="STORY",
            ),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_assignment_settlement(story, 1500000, False, 0, 1500000)
    story_chain = X.milestones_of(api, story["id"])
    assert [m["milestone_type"] for m in story_chain] == ["OUTLINE"], (
        f"A story chain is exactly one milestone: {story_chain}"
    )
    A.assert_field_values(
        story_chain[0], sequence_index=1, due_date=K.DUE_DATES_NOV_02["OUTLINE"]
    )
    A.assert_field_values(
        story,
        outline_due_date=K.DUE_DATES_NOV_02["OUTLINE"],
        polish_due_date=K.DUE_DATES_NOV_02["POLISH"],
    )

    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), script_readiness="IN_PROGRESS"
    )
    A.assert_cents(
        X.read_season(api, world["season_id"])["script_fee_committed_cents"],
        3250000,
        "script_fee_committed_cents",
    )


def test_opening_a_clearance_review_starts_pending_and_scores_nothing(api):
    """The review exists, cites its draft, and carries no exposure yet.

    PRD: "A new review starts with `posture` at `PENDING`, `risk_score` 0, `item_count` 0, `decided_item_count` 0, `legal_waiver_granted` false and `waiver_memo` null, and it sets the episode's `clearance_posture` to `PENDING`, which is also where a fresh episode already sits."

    PRD: "The `reviewed_draft_milestone_id` must belong to that same assignment and must have a status in `DELIVERED`, `NOTES_ISSUED` or `ACCEPTED`; a milestone of another assignment, or one still `PENDING` or `LATE`, is rejected with `ERR_MILESTONE_NOT_IN_ASSIGNMENT`."

    Design: Corner/entities/clearance_review_creation_starts_pending_and_resets_the_episode_posture
    """
    world = X.build_delivered_assignment_world(api)
    draft_id = world["a1_milestone_ids"][-1]

    review = validate_success(
        api.create_clearance_review(
            world["a1_id"], F.build_clearance_review(draft_id), LEGAL_COUNSEL_HEADERS
        ),
        expected_status=201,
    )

    A.assert_common_fields(review)
    A.assert_field_values(
        review,
        assignment_id=world["a1_id"],
        reviewed_draft_milestone_id=draft_id,
        posture="PENDING",
        risk_score=0,
        item_count=0,
        decided_item_count=0,
        legal_waiver_granted=False,
        waiver_memo=None,
        version=1,
    )

    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), clearance_posture="PENDING"
    )
    A.assert_field_values(X.read_assignment(api, world["a1_id"]), status="DELIVERED")

    rows, meta = validate_paginated(
        api.list_clearance_items(
            LEGAL_COUNSEL_HEADERS, {"review_id": review["id"], "limit": 100}
        )
    )
    assert rows == [] and meta["total_count"] == 0, (
        f"A new review carries no items: {rows}"
    )


def test_raising_an_item_records_the_exposure_but_scores_nothing_yet(api):
    """Both items are stored undecided, so the review's figures stay at zero.

    PRD: "An item records one exposure: an `item_type` of `NAME`, `TRADEMARK` or `DEPICTION`, a `descriptor` of 1 to 200 characters naming the thing being cleared, and a `scene_reference` of 1 to 80 characters locating it in the script."

    PRD: "A new item's `decision` is `SUBMITTED`, its `conditional_note` is null, and its `risk_weight` is 0 — an undecided item carries no risk weight even though its type already implies one."

    PRD: "Raising the item increments the review's `item_count`, re-derives the review's `risk_score`, `decided_item_count` and `posture`, mirrors the posture where applicable and increments the review's `version`."

    PRD: "Items still `SUBMITTED` contribute nothing to either figure."

    Design: Corner/entities/clearance_item_creation_records_the_catalogue_weight_but_scores_nothing_yet
    """
    world = X.build_clearance_world(api)

    depiction = validate_success(
        api.create_clearance_item(
            world["review_id"],
            F.build_clearance_item(
                "DEPICTION", "Fictional senator resembling a sitting official", "2 / 4"
            ),
            LEGAL_COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    name = validate_success(
        api.create_clearance_item(
            world["review_id"],
            F.build_clearance_item("NAME", "Character surname Kowalczyk", "1 / 1"),
            LEGAL_COUNSEL_HEADERS,
        ),
        expected_status=201,
    )

    A.assert_common_fields(depiction)
    A.assert_field_values(
        depiction,
        review_id=world["review_id"],
        item_type="DEPICTION",
        descriptor="Fictional senator resembling a sitting official",
        scene_reference="2 / 4",
        decision="SUBMITTED",
        conditional_note=None,
        risk_weight=0,
        version=1,
    )
    A.assert_field_values(
        name,
        review_id=world["review_id"],
        item_type="NAME",
        decision="SUBMITTED",
        conditional_note=None,
        risk_weight=0,
        version=1,
    )

    review = X.read_review(api, world["review_id"])
    A.assert_field_values(
        review,
        item_count=2,
        decided_item_count=0,
        risk_score=0,
        posture="PENDING",
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), clearance_posture="PENDING"
    )


def test_filing_a_credit_claim_starts_submitted_with_no_share(api):
    """Two claims are recorded as claims: no share, no credit, no arbitrated figure.

    PRD: "A new submission's `status` is `SUBMITTED`, its `provisional_share_pct` is 0, its `arbitrated_share_pct` is null and its `receives_credit` is false."

    PRD: "The `claim_basis` is one of `WRITTEN_BY`, `STORY_BY` or `TELEPLAY_BY`, and `claimed_contribution_pct` is an integer from 1 to 100 — it is a claim, not a share, so the claims of the several writers on one episode need not sum to anything in particular."

    PRD: "Independently of readiness, the episode's `credit_status` moves `PENDING → SUBMISSIONS_OPEN` on the episode's *first* approved assignment of any type — a story approval is enough to open the credit window."

    Design: Corner/entities/credit_submission_creation_starts_submitted_with_no_share_and_no_credit
    """
    world = X.build_approved_assignment_world(api)
    X.seed_second_assignment(api, world)
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), credit_status="SUBMISSIONS_OPEN"
    )

    first = validate_success(
        api.create_credit_submission(
            world["ep1_id"],
            F.build_credit_submission(world["w1_id"], "WRITTEN_BY", 60),
            make_writer_headers(world["w1_id"]),
        ),
        expected_status=201,
    )
    second = validate_success(
        api.create_credit_submission(
            world["ep1_id"],
            F.build_credit_submission(world["w2_id"], "STORY_BY", 30),
            make_writer_headers(world["w2_id"]),
        ),
        expected_status=201,
    )

    for submission, writer_id, basis, claim in (
        (first, world["w1_id"], "WRITTEN_BY", 60),
        (second, world["w2_id"], "STORY_BY", 30),
    ):
        A.assert_common_fields(submission)
        A.assert_field_values(
            submission,
            episode_id=world["ep1_id"],
            writer_id=writer_id,
            claim_basis=basis,
            claimed_contribution_pct=claim,
            status="SUBMITTED",
            provisional_share_pct=0,
            arbitrated_share_pct=None,
            receives_credit=False,
            version=1,
        )

    episode = X.read_episode(api, world["ep1_id"])
    A.assert_field_values(
        episode, credit_status="SUBMISSIONS_OPEN", provisional_credit_shares={}
    )
    A.assert_field_values(X.read_writer(api, world["w1_id"]), on_screen_credit_count=0)

    rows, meta = _page(
        api, api.list_credit_submissions, episode_id=world["ep1_id"], limit=100
    )
    assert len(rows) == 2 and meta["total_count"] == 2, (
        f"Both claims are recorded against the episode: {rows}"
    )


def test_convening_the_panel_copies_the_participants_and_auto_advances(api):
    """The caller never sees INITIATED, and the participant order is the claim order.

    PRD: "The arbitration is created in `INITIATED` and auto-advanced to `STATEMENTS_OPEN` inside the same call, so a caller never observes `INITIATED`."

    PRD: "Its `participant_writer_ids` are the writer ids of the episode's `ELIGIBLE` submissions ordered by submission `created_at` ascending — that ordering is load-bearing, because it fixes the key set every ballot must match."

    PRD: "`votes_cast_count` starts at 0, `vote_ledger` at an empty map, `leading_writer_id` and `determined_credit_string` at null, `concurrence_pct` at 0 and `outcome` at `NONE`."

    PRD: "The episode moves to `IN_ARBITRATION` and its `version` increments."

    PRD: "an episode may have at most one arbitration ever — a second is rejected with `ERR_ARBITRATION_ALREADY_EXISTS`"

    Design: Corner/entities/arbitration_creation_copies_eligible_participants_and_auto_advances_once
    """
    world = X.build_closed_credit_world(api)
    before_version = X.read_episode(api, world["ep1_id"])["version"]
    arbiters = [world["ar1_id"], world["ar2_id"], world["ar3_id"]]

    arbitration = validate_success(
        api.convene_credit_arbitration(
            world["ep1_id"], F.build_arbitration(*arbiters), GUILD_ADMINISTRATOR_HEADERS
        ),
        expected_status=201,
    )

    A.assert_common_fields(arbitration)
    A.assert_field_values(
        arbitration,
        episode_id=world["ep1_id"],
        status="STATEMENTS_OPEN",
        arbiter_writer_ids=arbiters,
        participant_writer_ids=[world["w1_id"], world["w2_id"]],
        votes_cast_count=0,
        vote_ledger={},
        leading_writer_id=None,
        determined_credit_string=None,
        concurrence_pct=0,
        outcome="NONE",
        version=1,
    )

    episode = X.read_episode(api, world["ep1_id"])
    A.assert_field_values(
        episode, credit_status="IN_ARBITRATION", version=before_version + 1
    )
    # The episode now sits at IN_ARBITRATION, and the credit-status gate is a
    # step-14 state check while the at-most-one rule is step-18 uniqueness, so
    # the state check reports first.
    validate_error(
        api.convene_credit_arbitration(
            world["ep1_id"], F.build_arbitration(*arbiters), GUILD_ADMINISTRATOR_HEADERS
        ),
        ApiErrorId.ARBITRATION_NOT_AVAILABLE,
    )


def test_reading_back_the_seat_and_room_shows_every_derived_counter(api):
    """Acceptance is visible on both sides of the junction and in the season's money.

    PRD: "Acceptance moves the seat `OFFERED → CONFIRMED` and stamps `confirmed_at` from the logical clock."

    PRD: "The winning window moves to `CONSUMED` and records the seat in its `consumed_by_seat_id`, while the seat records the window in its `consumed_window_id` — a two-way link that makes the later release reversible."

    PRD: "Because a confirmed seat now contributes to the subtotal, the room's `seat_subtotal_weekly_cents`, `facility_tier`, `facility_surcharge_weekly_cents` and `weekly_burn_cents` are recomputed, and the season's `staffing_commitment_weekly_cents` follows."

    PRD: "Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to real time."

    Design: Corner/entities/retrieval_returns_the_stored_seat_and_room_with_every_derived_counter
    """
    world = X.build_staffing_room_world(api)
    offered = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
    )
    X.accept_seat(api, offered["id"], world["w1_id"])

    seat = validate_success(
        api.get_room_seat(offered["id"], GUILD_ADMINISTRATOR_HEADERS)
    )
    A.assert_common_fields(seat)
    A.assert_field_values(
        seat,
        status="CONFIRMED",
        room_id=world["room_id"],
        writer_id=world["w1_id"],
        consumed_window_id=world["aw1_id"],
        guarantee_slots_consumed=0,
        guarantee_slots_remaining=1,
    )
    A.assert_instant(seat["confirmed_at"], K.CLOCK_EPOCH, "confirmed_at")
    A.assert_seat_pricing(
        seat, 600000, 600000, 0, 600000, K.SEAT_PRORATED_181_DAYS_AT_600000
    )

    room = validate_success(api.get_room(world["room_id"], GUILD_ADMINISTRATOR_HEADERS))
    A.assert_field_values(
        room,
        status="STAFFING",
        confirmed_seat_count=1,
        filled_seat_count=1,
        open_seat_count=2,
        confirmed_diversity_seat_count=0,
    )
    A.assert_seat_capacity_conserved(room)
    A.assert_room_burn(
        room,
        600000,
        K.FACILITY_TIER_1,
        K.ROOM_BURN_EMPTY_IN_PERSON,
        K.ROOM_BURN_ONE_SEAT_600000,
    )

    A.assert_field_values(
        X.read_window(api, world["aw1_id"]),
        status="CONSUMED",
        consumed_by_seat_id=seat["id"],
    )
    A.assert_field_values(X.read_writer(api, world["w1_id"]), active_seat_count=1)
    A.assert_cents(
        X.read_season(api, world["season_id"])["staffing_commitment_weekly_cents"],
        K.ROOM_BURN_ONE_SEAT_600000,
        "staffing_commitment_weekly_cents",
    )


def test_listing_writers_paginates_and_filters_on_the_derived_level(api):
    """The page echoes its own window, and the level filter narrows the count.

    PRD: "`limit` controls page size: it defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` controls the starting position: it defaults to 0 and may not be negative."

    PRD: "Both parameters are echoed back in the `meta` object of the response alongside `total_count` — the number of records matching the filters before pagination is applied — and `has_more`, which is true when records remain beyond the current page."

    PRD: "The default ordering for list endpoints is `created_at` ascending, so the oldest record appears first."

    PRD: "All filter parameters on a list endpoint combine conjunctively: a record must match every supplied filter to appear."

    Design: Corner/entities/listing_writers_paginates_with_total_count_has_more_and_a_filter
    """
    X.build_registry(api)

    first_page, meta = _page(api, api.list_writers, limit=2, offset=0)
    assert len(first_page) == 2, f"A limit of 2 returns two rows: {first_page}"
    A.assert_pagination_meta(meta, total_count=8, has_more=True, limit=2, offset=0)
    A.assert_ordered_by(first_page, "created_at")

    last_page, last_meta = _page(api, api.list_writers, limit=2, offset=7)
    assert len(last_page) == 1, f"The tail page holds the single last row: {last_page}"
    A.assert_pagination_meta(last_meta, total_count=8, has_more=False, limit=2, offset=7)

    default_page, default_meta = _page(api, api.list_writers)
    assert len(default_page) == 8, f"Eight writers fit the default page: {default_meta}"
    A.assert_pagination_meta(
        default_meta, total_count=8, has_more=False, limit=10, offset=0
    )
    A.assert_ordered_by(default_page, "created_at")

    editors, editor_meta = _page(
        api, api.list_writers, determined_level="STORY_EDITOR", limit=100
    )
    assert len(editors) == 3 and editor_meta["total_count"] == 3, (
        f"Exactly the three-credit writers are STORY_EDITOR: {editors}"
    )
    assert {w["determined_level"] for w in editors} == {"STORY_EDITOR"}, (
        f"The filter admits no other level: {editors}"
    )

    narrowed, narrowed_meta = _page(
        api,
        api.list_writers,
        determined_level="STORY_EDITOR",
        diversity_program_participant=True,
        limit=100,
    )
    assert narrowed_meta["total_count"] == 1, (
        f"Two filters combine conjunctively: {narrowed}"
    )
    A.assert_field_values(
        narrowed[0], determined_level="STORY_EDITOR", diversity_program_participant=True
    )


def test_unknown_ids_return_the_resource_specific_not_found_code(api):
    """Each resource type answers with its own 404, in the path and in the body alike.

    PRD: "A path variable that names no existing row yields HTTP 404 with the code for that resource type"

    PRD: "Nested paths are resolved strictly left to right, and the first segment that does not resolve determines the error."

    PRD: "Resources referenced from a request body rather than the path are checked with the same codes"

    PRD: "6. Every body-referenced resource exists — otherwise the matching not-found code."

    PRD: "13. The optimistic-concurrency version field matches the parent row's current `version` — otherwise the matching stale-version code."

    Design: Corner/entities/unknown_ids_return_the_resource_specific_not_found_code
    """
    world = X.build_staffing_room_world(api)
    X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
    )

    for reader, error_id in (
        (api.get_guild_agreement, ApiErrorId.AGREEMENT_NOT_FOUND),
        (api.get_season, ApiErrorId.SEASON_NOT_FOUND),
        (api.get_writer, ApiErrorId.WRITER_NOT_FOUND),
        (api.get_availability_window, ApiErrorId.WINDOW_NOT_FOUND),
        (api.get_room, ApiErrorId.ROOM_NOT_FOUND),
        (api.get_room_seat, ApiErrorId.SEAT_NOT_FOUND),
        (api.get_episode, ApiErrorId.EPISODE_NOT_FOUND),
        (api.get_script_assignment, ApiErrorId.ASSIGNMENT_NOT_FOUND),
        (api.get_milestone, ApiErrorId.MILESTONE_NOT_FOUND),
    ):
        validate_error(
            reader(NON_EXISTENT_UUID, GUILD_ADMINISTRATOR_HEADERS), error_id
        )

    validate_error(
        api.get_clearance_review(NON_EXISTENT_UUID, LEGAL_COUNSEL_HEADERS),
        ApiErrorId.REVIEW_NOT_FOUND,
    )
    validate_error(
        api.get_clearance_item(NON_EXISTENT_UUID, LEGAL_COUNSEL_HEADERS),
        ApiErrorId.ITEM_NOT_FOUND,
    )
    validate_error(
        api.get_fee_ledger_entry(NON_EXISTENT_UUID, STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.LEDGER_ENTRY_NOT_FOUND,
    )
    validate_error(
        api.get_credit_submission(NON_EXISTENT_UUID, GUILD_ADMINISTRATOR_HEADERS),
        ApiErrorId.SUBMISSION_NOT_FOUND,
    )
    validate_error(
        api.get_credit_arbitration(NON_EXISTENT_UUID, GUILD_ADMINISTRATOR_HEADERS),
        ApiErrorId.ARBITRATION_NOT_FOUND,
    )

    validate_error(
        api.create_room(
            NON_EXISTENT_UUID, F.build_room(name="Ghost Room"), world["sr_headers"]
        ),
        ApiErrorId.SEASON_NOT_FOUND,
    )
    validate_error(
        api.offer_seat(
            world["room_id"],
            F.build_seat_offer(NON_EXISTENT_UUID, world["room_version"]),
            world["sr_headers"],
        ),
        ApiErrorId.WRITER_NOT_FOUND,
    )

    rooms, _ = _page(api, api.list_rooms, season_id=world["season_id"], limit=100)
    assert len(rooms) == 1, f"No refused call created a room: {rooms}"
    seats, _ = _page(api, api.list_room_seats, room_id=world["room_id"], limit=100)
    assert len(seats) == 1, f"No refused call created a seat: {seats}"


def test_missing_required_fields_are_rejected_before_anything_is_created(api):
    """Four bodies each drop one required field and each is refused at the gate.

    PRD: "7. The request body satisfies its declared schema: required fields present, types correct, enum members recognised, integers inside their declared ranges, and rate-card objects carrying exactly the declared keys — otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

    PRD: "The guild administrator supplies the writer's `legal_name` as it appears on guild paperwork (1 to 200 characters), their `guild_member_id` (1 to 40 characters), and the `agreement_id` of the rate card whose credit thresholds should be applied to them."

    PRD: "In every case the version field is a **required, non-optional** input, and a value that does not equal the parent row's current `version` at the moment of the write is rejected before any side effect is applied."

    PRD: "The offer must additionally carry `expected_room_version` as described in §2.9."

    Design: Corner/entities/missing_required_fields_are_rejected_before_anything_is_created
    """
    world = X.build_staffing_room_world(api)

    validate_error(
        api.create_writer(
            {"legal_name": "No Guild Id", "agreement_id": world["agreement_id"]},
            GUILD_ADMINISTRATOR_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
    )

    season_payload = F.build_season(world["agreement_id"], world["sr_id"])
    season_payload.pop("staffing_window_start")
    season_payload.pop("staffing_window_end")
    validate_error(
        api.create_season(season_payload, STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.INVALID_REQUEST,
    )

    seat_payload = F.build_seat_offer(world["w1_id"], world["room_version"])
    seat_payload.pop("expected_room_version")
    validate_error(
        api.offer_seat(world["room_id"], seat_payload, world["sr_headers"]),
        ApiErrorId.INVALID_REQUEST,
    )

    window_payload = F.build_availability_window()
    window_payload.pop("commitment_type")
    validate_error(
        api.create_availability_window(
            world["w1_id"], window_payload, make_writer_headers(world["w1_id"])
        ),
        ApiErrorId.INVALID_REQUEST,
    )

    writers, writer_meta = _page(api, api.list_writers, limit=100)
    assert writer_meta["total_count"] == 8, (
        f"No refused writer body was persisted: {len(writers)}"
    )
    seasons, season_meta = _page(api, api.list_seasons, limit=100)
    assert season_meta["total_count"] == 1, (
        f"No refused season body was persisted: {seasons}"
    )
    seats, seat_meta = _page(api, api.list_room_seats, room_id=world["room_id"], limit=100)
    assert seat_meta["total_count"] == 0, f"No refused seat body was persisted: {seats}"
    windows, window_meta = _page(
        api, api.list_availability_windows, writer_id=world["w1_id"], limit=100
    )
    assert window_meta["total_count"] == 1, (
        f"No refused window body was persisted: {windows}"
    )
    A.assert_field_values(
        X.read_room(api, world["room_id"]),
        open_seat_count=3,
        version=world["room_version"],
    )


def test_omitting_every_optional_agreement_field_applies_the_declared_defaults(api):
    """A rate card holding only its required fields comes back fully populated.

    PRD: "The remaining fields are scalars, several with defaults that apply when the client omits them. `diversity_subsidy_pct` is greater than 0 and at most 1 and defaults to 0.5; `diversity_subsidy_cap_weekly_cents` is a required integer of at least 1; `mini_room_floor_multiplier` is at least 1 and defaults to 1.2; `short_commitment_weeks_threshold` is an integer of at least 1 and defaults to 20; `short_commitment_uplift_pct` runs from 0 through 1 inclusive and defaults to 0.1; `max_free_revision_rounds` is an integer of at least 0 and defaults to 2; `credit_share_threshold_pct` is an integer from 1 through 100 and defaults to 33; `arbitration_concurrence_pct` is greater than 0 and at most 1 and defaults to 0.667; `arbitration_concurrence_band_pct` is an integer from 1 through 100 and defaults to 10; `turnaround_buffer_days` is an integer of at least 0 and defaults to 2; `clearance_escalation_score` is an integer of at least 0 and defaults to 30"

    PRD: "the guild agreement list returns rate cards newest-created first"

    Design: Corner/entities/omitting_every_optional_agreement_field_applies_the_declared_defaults
    """
    first = X.seed_agreement(api)
    payload = F.build_minimal_guild_agreement(mba_year=2027)

    minimal = validate_success(
        api.create_guild_agreement(payload, GUILD_ADMINISTRATOR_HEADERS),
        expected_status=201,
    )

    A.assert_common_fields(minimal)
    A.assert_field_values(
        minimal,
        mba_year=2027,
        diversity_subsidy_pct=K.DIVERSITY_SUBSIDY_PCT,
        mini_room_floor_multiplier=K.MINI_ROOM_FLOOR_MULTIPLIER,
        short_commitment_weeks_threshold=K.SHORT_COMMITMENT_WEEKS_THRESHOLD,
        short_commitment_uplift_pct=K.SHORT_COMMITMENT_UPLIFT_PCT,
        max_free_revision_rounds=K.MAX_FREE_REVISION_ROUNDS,
        credit_share_threshold_pct=K.CREDIT_SHARE_THRESHOLD_PCT,
        arbitration_concurrence_pct=K.ARBITRATION_CONCURRENCE_PCT,
        arbitration_concurrence_band_pct=K.ARBITRATION_CONCURRENCE_BAND_PCT,
        turnaround_buffer_days=K.TURNAROUND_BUFFER_DAYS,
        clearance_escalation_score=K.CLEARANCE_ESCALATION_SCORE,
        version=1,
    )
    A.assert_field_values(minimal, **payload)

    rows, meta = _page(api, api.list_guild_agreements, limit=100)
    assert [row["id"] for row in rows] == [minimal["id"], first["id"]], (
        f"Rate cards are listed newest-created first: {[r['mba_year'] for r in rows]}"
    )
    assert meta["total_count"] == 2, f"Both rate cards are on file: {meta}"


def test_omitting_the_optional_writer_room_seat_and_episode_fields(api):
    """Four resources are created at their minimum, and each default is the declared one.

    PRD: "`career_episodic_credits`, the count of produced episodic credits the writer brings with them, which must not be negative and defaults to 0; `diversity_program_participant`, which defaults to false and is the prerequisite for ever holding a diversity-program-funded seat; and `is_showrunner_eligible`, which also defaults to false"

    PRD: "Optionally the room declares `diversity_seats_required`, a count from 0 through the room's capacity that defaults to 0 and sets how many confirmed diversity-funded seats the room must hold before it may be activated."

    PRD: "Two optional inputs shape the money: `episodic_guarantee_count`, a count from 0 to 30 that defaults to 0 and says how many episode scripts are guaranteed to the writer under this seat, and `diversity_program_funded`, which defaults to false."

    PRD: "and `shoot_days`, an integer from 1 to 30 that defaults to 8."

    Design: Corner/entities/omitting_optional_writer_room_seat_and_episode_fields_applies_their_defaults
    """
    agreement = X.seed_agreement(api)
    showrunner = X.seed_writer(
        api,
        agreement["id"],
        "Sloane Reyes",
        "GM-SHOW",
        career_episodic_credits=20,
        is_showrunner_eligible=True,
    )
    sr_headers = make_showrunner_headers(showrunner["id"])

    writer = validate_success(
        api.create_writer(
            F.build_minimal_writer(agreement["id"], "Ivy Nakamura", "GM-1003"),
            GUILD_ADMINISTRATOR_HEADERS,
        ),
        expected_status=201,
    )
    A.assert_field_values(
        writer,
        career_episodic_credits=0,
        diversity_program_participant=False,
        is_showrunner_eligible=False,
        determined_level="STAFF_WRITER",
    )
    X.seed_window(api, writer["id"])

    season = validate_success(
        api.create_season(
            F.build_minimal_season(agreement["id"], showrunner["id"]),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        expected_status=201,
    )
    A.assert_field_values(
        season, guarantee_application_mode="CHRONOLOGICAL_ON_ACCEPTANCE"
    )

    room = validate_success(
        api.create_room(season["id"], F.build_minimal_room(), sr_headers),
        expected_status=201,
    )
    A.assert_field_values(room, diversity_seats_required=0, seat_capacity=3)
    staffing = X.open_room(api, room["id"], sr_headers)

    seat = validate_success(
        api.offer_seat(
            room["id"],
            F.build_minimal_seat_offer(
                writer["id"],
                staffing["version"],
                level_at_hire="STAFF_WRITER",
                offered_weekly_compensation_cents=450000,
            ),
            sr_headers,
        ),
        expected_status=201,
    )
    A.assert_field_values(
        seat,
        episodic_guarantee_count=0,
        diversity_program_funded=False,
        guarantee_slots_consumed=0,
        guarantee_slots_remaining=0,
    )
    A.assert_guarantee_slots_conserved(seat)
    A.assert_cents(
        seat["diversity_subsidy_weekly_cents"], 0, "diversity_subsidy_weekly_cents"
    )
    A.assert_cents(seat["studio_charge_weekly_cents"], 450000, "studio_charge_weekly_cents")

    episode = validate_success(
        api.create_episode(
            season["id"], F.build_minimal_episode(1), STUDIO_EXECUTIVE_HEADERS
        ),
        expected_status=201,
    )
    A.assert_field_values(episode, shoot_days=8, episode_number=1)


def test_computed_and_system_fields_supplied_by_the_client_are_ignored(api):
    """Injected money and injected statuses are overwritten by the derivations.

    PRD: "**Seat weekly compensation** is derived, not accepted as given."

    PRD: "A surviving offer creates the seat in `OFFERED` status with all four compensation figures and the prorated commitment computed, `guarantee_slots_consumed` at 0 and `guarantee_slots_remaining` equal to the seat's `episodic_guarantee_count`, `confirmed_at` and `consumed_window_id` both null."

    PRD: "A freshly created season has committed nothing and finished nothing, so `staffing_commitment_weekly_cents`, `script_fee_committed_cents` and `ready_script_count` all start at 0, and the coverage figures are computed immediately from that empty state."

    PRD: "7. The request body satisfies its declared schema: required fields present, types correct, enum members recognised, integers inside their declared ranges, and rate-card objects carrying exactly the declared keys — otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/computed_and_system_fields_supplied_by_the_client_are_ignored_input
    """
    world = X.build_staffing_room_world(api)

    seat = validate_success(
        api.offer_seat(
            world["room_id"],
            F.build_seat_offer(
                world["w1_id"],
                world["room_version"],
                weekly_compensation_cents=1,
                prorated_commitment_cents=0,
                status="CONFIRMED",
                guarantee_slots_consumed=5,
            ),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_field_values(
        seat,
        status="OFFERED",
        guarantee_slots_consumed=0,
        guarantee_slots_remaining=1,
        confirmed_at=None,
        consumed_window_id=None,
    )
    A.assert_seat_pricing(
        seat, 600000, 600000, 0, 600000, K.SEAT_PRORATED_181_DAYS_AT_600000
    )

    season = validate_success(
        api.create_season(
            F.build_season(
                world["agreement_id"],
                world["sr_id"],
                title="Injected Season",
                ready_script_target=1,
                script_fee_committed_cents=999,
                ready_script_count=7,
                coverage_posture="COVERED",
            ),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        expected_status=201,
    )
    A.assert_cents(
        season["script_fee_committed_cents"], 0, "script_fee_committed_cents"
    )
    A.assert_field_values(
        season, ready_script_count=0, coverage_gap=1, coverage_posture="AT_RISK"
    )


def test_milestone_and_ledger_rows_carry_only_server_minted_system_fields(api):
    """Neither row type is ever created by a client, and the ledger keeps no version.

    PRD: "Each milestone is numbered by `sequence_index` starting at 1 in that chain order, copies the matching due-date field into its own `due_date`, and starts `PENDING` — or `LATE` immediately, if the logical clock has already passed that deadline at the moment the assignment is created."

    PRD: "Each entry records the `season_id` whose committed total it moves, the `assignment_id` that produced it, the `writer_id` the money is owed to or reversed from, an `entry_type`, a signed `amount_cents`, and a human-readable `memo` such as "void reversal of TELEPLAY fee"."

    PRD: "Creating an assignment therefore appends a `SCRIPT_FEE_ACCRUAL` entry for the full gross and, when a slot applied at creation, a `GUARANTEE_OFFSET` entry for the negative offset."

    PRD: "Fee ledger entries are append-only accounting records: once written they are never mutated and never deleted, so they carry only `id` and `created_at`."

    Design: Corner/entities/milestone_and_ledger_rows_carry_only_server_minted_system_fields
    """
    world = X.build_assignment_world(api)

    chain = X.milestones_of(api, world["a1_id"])
    assert [m["milestone_type"] for m in chain] == [
        "OUTLINE",
        "FIRST_DRAFT",
        "SECOND_DRAFT",
    ], f"The chain is minted by the server: {chain}"
    assert [m["sequence_index"] for m in chain] == [1, 2, 3], (
        f"Sequence indices are minted by the server: {chain}"
    )
    for milestone in chain:
        A.assert_common_fields(milestone)
        A.assert_field_values(milestone, assignment_id=world["a1_id"], version=1)

    entries = X.ledger_for_season(api, world["season_id"])
    assert A.entry_types(entries) == ["SCRIPT_FEE_ACCRUAL", "GUARANTEE_OFFSET"], (
        f"The create writes exactly these two rows: {A.entry_types(entries)}"
    )
    A.assert_cents(entries[0]["amount_cents"], 3500000, "amount_cents")
    A.assert_cents(entries[1]["amount_cents"], -1750000, "amount_cents")
    for entry in entries:
        A.assert_ledger_common_fields(entry)
        A.assert_fields_absent(entry, "updated_at", "version")
        A.assert_field_values(
            entry,
            season_id=world["season_id"],
            assignment_id=world["a1_id"],
            writer_id=world["w1_id"],
        )
        assert isinstance(entry["memo"], str) and entry["memo"], (
            f"Every ledger row carries a human-readable memo: {entry}"
        )


def test_out_of_range_values_and_unknown_enum_members_are_rejected(api):
    """One code covers every declared range and every declared enum domain.

    PRD: "7. The request body satisfies its declared schema: required fields present, types correct, enum members recognised, integers inside their declared ranges, and rate-card objects carrying exactly the declared keys — otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

    PRD: "a `seat_capacity` from 1 to 12"

    PRD: "The season declares how much television it intends to make through `episode_order`, an integer from 1 to 30"

    PRD: "Both ceilings are non-negative integers."

    PRD: "A `limit` outside the inclusive range 1 through 100, or a negative `offset`, or a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/entities/out_of_range_values_and_unknown_enum_members_are_rejected
    """
    world = X.build_season_world(api)

    validate_error(
        api.create_room(
            world["season_id"],
            F.build_room(name="Too Big", seat_capacity=13),
            world["sr_headers"],
        ),
        ApiErrorId.INVALID_REQUEST,
    )
    validate_error(
        api.create_room(
            world["season_id"],
            F.build_room(name="Bad Format", format="HYBRID"),
            world["sr_headers"],
        ),
        ApiErrorId.INVALID_REQUEST,
    )
    validate_error(
        api.create_season(
            F.build_season(
                world["agreement_id"], world["sr_id"], title="Over Order", episode_order=31
            ),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
    )
    validate_error(
        api.create_season(
            F.build_season(
                world["agreement_id"],
                world["sr_id"],
                title="Negative Budget",
                staffing_budget_weekly_cents=-1,
            ),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
    )

    validate_error(
        api.list_writers(GUILD_ADMINISTRATOR_HEADERS, {"limit": 101}),
        ApiErrorId.INVALID_PAGINATION,
    )
    validate_error(
        api.list_writers(GUILD_ADMINISTRATOR_HEADERS, {"offset": -1}),
        ApiErrorId.INVALID_PAGINATION,
    )

    rooms, _ = _page(api, api.list_rooms, season_id=world["season_id"], limit=100)
    assert rooms == [], f"Neither refused room body was persisted: {rooms}"
    _, season_meta = _page(api, api.list_seasons, limit=100)
    assert season_meta["total_count"] == 1, (
        f"Neither refused season body was persisted: {season_meta}"
    )


def test_fee_ledger_entries_are_append_only_with_no_update_path(api):
    """The approve leaves the two existing rows byte-identical and adds nothing.

    PRD: "Every movement of script money is recorded in an **append-only fee ledger**, whose entries are never mutated or deleted."

    PRD: "A fee ledger entry has no `updated_at` and no `version` field at all, and no endpoint exists to change one."

    PRD: "Under `FORWARD_COMMIT` no re-settlement occurs and no reallocation entry is written."

    Design: Corner/entities/fee_ledger_entries_are_append_only_with_no_update_path
    """
    world = X.build_delivered_assignment_world(api)
    before = X.ledger_for_assignment(api, world["a1_id"])
    assert A.entry_types(before) == ["SCRIPT_FEE_ACCRUAL", "GUARANTEE_OFFSET"], (
        f"The create wrote both rows: {A.entry_types(before)}"
    )
    accrual = before[0]

    X.approve_assignment(api, world["a1_id"])

    fetched = validate_success(
        api.get_fee_ledger_entry(accrual["id"], STUDIO_EXECUTIVE_HEADERS)
    )
    assert fetched == accrual, (
        f"The approve must not touch a written row: {accrual} became {fetched}"
    )
    A.assert_field_values(fetched, entry_type="SCRIPT_FEE_ACCRUAL")
    A.assert_cents(fetched["amount_cents"], 3500000, "amount_cents")
    A.assert_ledger_common_fields(fetched)
    A.assert_fields_absent(fetched, "updated_at", "version")

    after = X.ledger_for_assignment(api, world["a1_id"])
    assert after == before, (
        f"A FORWARD_COMMIT approve appends no reallocation row: {A.entry_types(after)}"
    )
    A.assert_assignment_settlement(
        X.read_assignment(api, world["a1_id"]), 3500000, True, 1750000, 1750000
    )


def test_nested_creates_are_scoped_to_their_parent_and_reject_a_foreign_one(api):
    """A review under one assignment may not cite another assignment's milestone.

    PRD: "The `reviewed_draft_milestone_id` must belong to that same assignment and must have a status in `DELIVERED`, `NOTES_ISSUED` or `ACCEPTED`; a milestone of another assignment, or one still `PENDING` or `LATE`, is rejected with `ERR_MILESTONE_NOT_IN_ASSIGNMENT`."

    PRD: "5. Every path-segment resource exists, left to right — otherwise the matching not-found code."

    PRD: "Nested paths are resolved strictly left to right, and the first segment that does not resolve determines the error."

    Design: Corner/entities/nested_creates_are_scoped_to_their_parent_and_reject_a_foreign_one
    """
    world = X.build_delivered_assignment_world(api)
    own_draft_id = world["a1_milestone_ids"][-1]

    story = X.seed_assignment(
        api, world["ep1_id"], world["w2_id"], world["sr_headers"], "STORY"
    )
    X.deliver_all(api, story["id"], world["w2_id"])
    foreign_draft_id = X.milestones_of(api, story["id"])[0]["id"]

    validate_error(
        api.create_clearance_review(
            world["a1_id"],
            F.build_clearance_review(foreign_draft_id),
            LEGAL_COUNSEL_HEADERS,
        ),
        ApiErrorId.MILESTONE_NOT_IN_ASSIGNMENT,
    )
    validate_error(
        api.create_clearance_review(
            NON_EXISTENT_UUID,
            F.build_clearance_review(own_draft_id),
            LEGAL_COUNSEL_HEADERS,
        ),
        ApiErrorId.ASSIGNMENT_NOT_FOUND,
    )

    review = validate_success(
        api.create_clearance_review(
            world["a1_id"],
            F.build_clearance_review(own_draft_id),
            LEGAL_COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    A.assert_field_values(
        review,
        assignment_id=world["a1_id"],
        reviewed_draft_milestone_id=own_draft_id,
        posture="PENDING",
    )

    mine, mine_meta = validate_paginated(
        api.list_clearance_reviews(
            LEGAL_COUNSEL_HEADERS, {"assignment_id": world["a1_id"], "limit": 100}
        )
    )
    assert [row["id"] for row in mine] == [review["id"]], (
        f"Exactly the one accepted review hangs off a1: {mine_meta}"
    )
    foreign, foreign_meta = validate_paginated(
        api.list_clearance_reviews(
            LEGAL_COUNSEL_HEADERS, {"assignment_id": story["id"], "limit": 100}
        )
    )
    assert foreign == [] and foreign_meta["total_count"] == 0, (
        f"The refused review did not land on the story assignment: {foreign}"
    )


def test_the_seat_junction_and_the_predecessor_edge_both_hold(api):
    """One room holds two writers, and a rewrite points back at the approved teleplay.

    PRD: "**Predecessor linkage**: a `REWRITE` or a `PRODUCTION_POLISH` must name a `predecessor_assignment_id` that belongs to the same episode and whose status is `APPROVED`"

    PRD: "a `REWRITE` gets a single `FIRST_DRAFT`"

    PRD: "An episode already at `READY` that receives a `REWRITE` returns to `IN_PROGRESS`, because a rewrite reopens the script — and it retains its `approved_teleplay_assignment_id`, so the clearance mirror keeps pointing at the draft that was actually approved."

    PRD: "The winning window moves to `CONSUMED` and records the seat in its `consumed_by_seat_id`, while the seat records the window in its `consumed_window_id` — a two-way link that makes the later release reversible."

    Design: Corner/entities/the_seat_junction_and_the_self_referential_predecessor_edge_both_hold
    """
    world = X.build_approved_assignment_world(api)

    seats, seat_meta = _page(api, api.list_room_seats, room_id=world["room_id"], limit=100)
    assert seat_meta["total_count"] == 2, f"The room holds two seats: {seats}"
    assert {s["status"] for s in seats} == {"CONFIRMED"}, (
        f"Both seats are confirmed: {seats}"
    )
    assert len({s["writer_id"] for s in seats}) == 2, (
        f"The junction holds two different writers: {seats}"
    )
    A.assert_field_values(
        X.read_window(api, world["aw1_id"]), consumed_by_seat_id=world["s1_id"]
    )
    A.assert_field_values(
        X.read_window(api, world["aw2_id"]), consumed_by_seat_id=world["s2_id"]
    )

    rewrite = validate_success(
        api.create_script_assignment(
            world["ep1_id"],
            F.build_script_assignment(
                world["w2_id"],
                world["ep1_version"],
                assignment_type="REWRITE",
                predecessor_assignment_id=world["a1_id"],
            ),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_field_values(
        rewrite,
        predecessor_assignment_id=world["a1_id"],
        room_seat_id=world["s2_id"],
        status="DRAFTING",
    )
    A.assert_assignment_settlement(rewrite, 1750000, False, 0, 1750000)

    chain = X.milestones_of(api, rewrite["id"])
    assert [m["milestone_type"] for m in chain] == ["FIRST_DRAFT"], (
        f"A rewrite chain is exactly one first draft: {chain}"
    )
    A.assert_field_values(
        chain[0], sequence_index=1, due_date=K.DUE_DATES_NOV_02["FIRST_DRAFT"]
    )

    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]),
        script_readiness="IN_PROGRESS",
        approved_teleplay_assignment_id=world["a1_id"],
    )

    descendants, _ = _page(
        api,
        api.list_script_assignments,
        predecessor_assignment_id=world["a1_id"],
        limit=100,
    )
    assert [row["id"] for row in descendants] == [rewrite["id"]], (
        f"The lineage filter finds exactly the rewrite: {descendants}"
    )
