"""Endpoint surfaces walked end to end: the round trip, the self-loop, the link.

One test per breadth instance of the corner design's `endpoints` section. Each
test drives a real endpoint group rather than a single call — a create/read/list
triple that must agree on derived data, a self-loop that rewrites its children,
an association whose three ends fail with three different codes, a read that has
to reconcile against the lists behind it, and an action gated on a computed
posture.
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
)

CO_PRODUCER_CREDITS = 8

# A 26-week MINI_ROOM: the 1.2 floor multiplier applies, the 20-week uplift does not.
MINI_ROOM_FLOOR_AT_600000 = 720000
MINI_ROOM_PRORATED_181_DAYS = 18617142
MINI_ROOM_SURCHARGE = 120000
MINI_ROOM_BURN = 840000

# A 12-week IN_PERSON room: no format multiplier, but the short-commitment uplift.
SHORT_IN_PERSON_FLOOR_AT_600000 = 660000
SHORT_IN_PERSON_PRORATED_181_DAYS = 17065716
SHORT_IN_PERSON_BURN = 860000

# Both confirmed seats of the canonical active room, plus the tier-1 facility fee.
ACTIVE_ROOM_SUBTOTAL = 1200000
ACTIVE_ROOM_BURN = 1400000

TELEPLAY_GROSS_ONE_HOUR = 3500000
TELEPLAY_OFFSET_ONE_HOUR = 1750000
STORY_GROSS_ONE_HOUR = 1500000
COMMITTED_SCRIPT_MONEY = 3250000

WAIVER_MEMO = "Depiction risk accepted; E&O carrier notified 2026-08-01."
CONDITIONAL_NOTE = "Change the senator's home state and surname."


def _writer_ids(api, params):
    """The ids a filtered writer listing returns, with its meta."""
    rows, meta = validate_paginated(api.list_writers(GUILD_ADMINISTRATOR_HEADERS, params))
    return [row["id"] for row in rows], meta


def _episode_rows(api, params):
    """One filtered episode listing."""
    rows, _ = validate_paginated(api.list_episodes(STUDIO_EXECUTIVE_HEADERS, params))
    return rows


def _room_burn_sum(api, season_id, status):
    """The weekly burn the season's rooms of one status actually carry."""
    rows, _ = validate_paginated(
        api.list_rooms(
            STUDIO_EXECUTIVE_HEADERS,
            {"season_id": season_id, "status": status, "limit": 100},
        )
    )
    return sum(row["weekly_burn_cents"] for row in rows), rows


def test_writer_create_read_and_list_round_trip_with_filters_and_pagination(
    api, agreement
):
    """The level POST computed is the level GET returns and the filter selects on.

    PRD: "**Level determination** runs at registration and again on every later credit award."

    PRD: "otherwise, if they are at least the `CO_PRODUCER` threshold, the level is `CO_PRODUCER`"

    PRD: "Whichever agreement produced the answer is recorded in `level_determination_agreement_id`, which is null only for a writer who has never been determined."

    PRD: "A newly registered writer starts with no live seats and no on-screen credits, so `active_seat_count` and `on_screen_credit_count` both begin at 0."

    PRD: "All filter parameters on a list endpoint combine conjunctively: a record must match every supplied filter to appear."

    PRD: "Both parameters are echoed back in the `meta` object of the response alongside `total_count` — the number of records matching the filters before pagination is applied — and `has_more`, which is true when records remain beyond the current page."

    PRD: "A path variable that names no existing row yields HTTP 404 with the code for that resource type: `agreement_id` yields `ERR_AGREEMENT_NOT_FOUND`, `season_id` yields `ERR_SEASON_NOT_FOUND`, `writer_id` yields `ERR_WRITER_NOT_FOUND`"

    Design: Corner/endpoints/writer_create_read_and_list_round_trip_with_filters_and_pagination
    """
    agreement_id = agreement["id"]
    diverse = validate_success(
        api.create_writer(
            F.build_writer(
                agreement_id,
                "Ines Roche",
                "GM-5001",
                career_episodic_credits=CO_PRODUCER_CREDITS,
                diversity_program_participant=True,
            ),
            GUILD_ADMINISTRATOR_HEADERS,
        ),
        expected_status=201,
    )
    A.assert_common_fields(diverse)
    A.assert_field_values(
        diverse,
        version=1,
        determined_level="CO_PRODUCER",
        level_determination_agreement_id=agreement_id,
        career_episodic_credits=CO_PRODUCER_CREDITS,
        diversity_program_participant=True,
        is_showrunner_eligible=False,
        active_seat_count=0,
        on_screen_credit_count=0,
    )
    plain = validate_success(
        api.create_writer(
            F.build_writer(
                agreement_id,
                "Tomas Berg",
                "GM-5002",
                career_episodic_credits=CO_PRODUCER_CREDITS,
            ),
            GUILD_ADMINISTRATOR_HEADERS,
        ),
        expected_status=201,
    )
    A.assert_field_values(
        plain, determined_level="CO_PRODUCER", diversity_program_participant=False
    )

    read_back = X.read_writer(api, diverse["id"])
    assert read_back == diverse, (
        f"The read must return the created row untouched:\n{read_back}\n{diverse}"
    )

    by_level, meta = _writer_ids(api, {"determined_level": "CO_PRODUCER", "limit": 100})
    A.assert_pagination_meta(meta, 2, False, 100, 0)
    assert set(by_level) == {diverse["id"], plain["id"]}, by_level

    composed, composed_meta = _writer_ids(
        api,
        {
            "determined_level": "CO_PRODUCER",
            "diversity_program_participant": True,
            "limit": 100,
        },
    )
    assert composed_meta["total_count"] == 1, composed_meta
    assert composed == [diverse["id"]], composed

    first_page, first_meta = _writer_ids(
        api, {"determined_level": "CO_PRODUCER", "limit": 1, "offset": 0}
    )
    A.assert_pagination_meta(first_meta, 2, True, 1, 0)
    assert len(first_page) == 1, first_page
    second_page, second_meta = _writer_ids(
        api, {"determined_level": "CO_PRODUCER", "limit": 1, "offset": 1}
    )
    A.assert_pagination_meta(second_meta, 2, False, 1, 1)
    assert set(first_page + second_page) == {diverse["id"], plain["id"]}, (
        f"The two pages must partition the filtered set: {first_page} {second_page}"
    )

    validate_error(
        api.get_writer(NON_EXISTENT_UUID, GUILD_ADMINISTRATOR_HEADERS),
        ApiErrorId.WRITER_NOT_FOUND,
        expected_status=404,
    )


def test_reconfigure_rewrites_every_confirmed_seat_and_is_refused_once_the_room_is_active(
    api,
):
    """Two payload fields rewrite the seat, the room and the season in one call.

    PRD: "Reconfiguring a room is the studio executive's lever over format and duration mid-staffing, and it is a self-loop: the room is in `STAFFING` before the call and in `STAFFING` after it."

    PRD: "The reconfiguration chain then runs in order: every seat of the room whose status is `CONFIRMED` has `guild_floor_weekly_cents`, `weekly_compensation_cents`, `diversity_subsidy_weekly_cents` and `studio_charge_weekly_cents` re-derived under the new format and duration, and its `prorated_commitment_cents` re-derived from the new weekly figure; the room's `seat_subtotal_weekly_cents`, `facility_tier`, `facility_surcharge_weekly_cents` and `weekly_burn_cents` are then recomputed from those new seat figures; and the season's `staffing_commitment_weekly_cents` is recomputed from the new room burn."

    PRD: "The room's `version` increments, and so does the `version` of every seat that was re-derived."

    PRD: "That level minimum is multiplied by a format multiplier, which is the agreement's `mini_room_floor_multiplier` when the room's format is `MINI_ROOM` and exactly 1 for both `IN_PERSON` and `REMOTE` — a mini room pays a premium because it asks fewer writers to carry a whole season."

    PRD: "It is then multiplied by one plus a short-commitment uplift, where the uplift is the agreement's `short_commitment_uplift_pct` when the room's `duration_weeks_committed` is strictly below the agreement's `short_commitment_weeks_threshold`, and zero when the commitment is at or above that threshold; with the default threshold of 20 weeks, a room committed for exactly 20 weeks attracts no uplift while a 19-week room does."

    PRD: "Round the weekly compensation divided by 7 to whole cents **first** to obtain a daily rate, then multiply that rounded daily rate by the residual days, and add the product of the full weeks and the full weekly compensation."

    Design: Corner/endpoints/reconfigure_rewrites_every_confirmed_seat_and_is_refused_once_the_room_is_active
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
    A.assert_seat_pricing(
        X.read_seat(api, seat["id"]),
        600000,
        600000,
        0,
        600000,
        prorated_commitment_cents=K.SEAT_PRORATED_181_DAYS_AT_600000,
    )
    before = X.read_room(api, world["room_id"])
    A.assert_room_burn(
        before,
        600000,
        K.FACILITY_TIER_1,
        K.FACILITY_FEE_TIERS["TIER_1"],
        K.ROOM_BURN_ONE_SEAT_600000,
    )

    mini = validate_success(
        api.reconfigure_room(
            world["room_id"],
            F.build_reconfigure(before["version"], "MINI_ROOM", 26),
            STUDIO_EXECUTIVE_HEADERS,
        )
    )
    A.assert_field_values(mini, status="STAFFING", format="MINI_ROOM")
    assert mini["version"] == before["version"] + 1, mini
    A.assert_seat_pricing(
        X.read_seat(api, seat["id"]),
        MINI_ROOM_FLOOR_AT_600000,
        MINI_ROOM_FLOOR_AT_600000,
        0,
        MINI_ROOM_FLOOR_AT_600000,
        prorated_commitment_cents=MINI_ROOM_PRORATED_181_DAYS,
    )
    A.assert_room_burn(
        mini,
        MINI_ROOM_FLOOR_AT_600000,
        K.FACILITY_TIER_1,
        MINI_ROOM_SURCHARGE,
        MINI_ROOM_BURN,
    )
    A.assert_cents(
        X.read_season(api, world["season_id"])["staffing_commitment_weekly_cents"],
        MINI_ROOM_BURN,
        "staffing_commitment_weekly_cents",
    )

    short = validate_success(
        api.reconfigure_room(
            world["room_id"],
            F.build_reconfigure(mini["version"], "IN_PERSON", 12),
            STUDIO_EXECUTIVE_HEADERS,
        )
    )
    A.assert_field_values(
        short, status="STAFFING", format="IN_PERSON", duration_weeks_committed=12
    )
    reworked = X.read_seat(api, seat["id"])
    A.assert_seat_pricing(
        reworked,
        SHORT_IN_PERSON_FLOOR_AT_600000,
        SHORT_IN_PERSON_FLOOR_AT_600000,
        0,
        SHORT_IN_PERSON_FLOOR_AT_600000,
        prorated_commitment_cents=SHORT_IN_PERSON_PRORATED_181_DAYS,
    )
    assert reworked["version"] == 4, (
        f"create, accept and two reconfigures make four seat versions: {reworked}"
    )
    A.assert_room_burn(
        short,
        SHORT_IN_PERSON_FLOOR_AT_600000,
        K.FACILITY_TIER_1,
        K.FACILITY_FEE_TIERS["TIER_1"],
        SHORT_IN_PERSON_BURN,
    )
    A.assert_cents(
        X.read_season(api, world["season_id"])["staffing_commitment_weekly_cents"],
        SHORT_IN_PERSON_BURN,
        "staffing_commitment_weekly_cents",
    )

    activated = X.activate_room(api, world["room_id"])
    A.assert_field_values(activated, status="ACTIVE")

    # The PRD makes reconfiguration a STAFFING self-loop but never names the code
    # for an ACTIVE room, so only the refusal and the untouched room are asserted.
    refused = api.reconfigure_room(
        world["room_id"],
        F.build_reconfigure(activated["version"], "REMOTE", 26),
        STUDIO_EXECUTIVE_HEADERS,
    )
    assert refused.status_code >= 400, (
        f"An ACTIVE room may not be reconfigured: {refused.status_code} {refused.text}"
    )
    frozen = X.read_room(api, world["room_id"])
    A.assert_field_values(
        frozen,
        status="ACTIVE",
        format="IN_PERSON",
        duration_weeks_committed=12,
        version=activated["version"],
    )
    A.assert_cents(frozen["weekly_burn_cents"], SHORT_IN_PERSON_BURN, "weekly_burn_cents")


def test_offering_a_seat_links_a_writer_a_room_and_the_window_that_covers_it(api):
    """Three resolvable ends, three different refusals, one navigable link.

    PRD: "Nested paths are resolved strictly left to right, and the first segment that does not resolve determines the error."

    PRD: "`room_id` yields `ERR_ROOM_NOT_FOUND`"

    PRD: "Resources referenced from a request body rather than the path are checked with the same codes: `guild_agreement_id`, `agreement_id`, `showrunner_writer_id`, `writer_id`, every id in `arbiter_writer_ids`, `predecessor_assignment_id` and `reviewed_draft_milestone_id` must all resolve to existing rows."

    PRD: "Partial coverage is not coverage, and the absence of any such window is rejected with `ERR_WRITER_UNAVAILABLE`."

    PRD: "A surviving offer creates the seat in `OFFERED` status with all four compensation figures and the prorated commitment computed, `guarantee_slots_consumed` at 0 and `guarantee_slots_remaining` equal to the seat's `episodic_guarantee_count`, `confirmed_at` and `consumed_window_id` both null."

    PRD: "The winning window moves to `CONSUMED` and records the seat in its `consumed_by_seat_id`, while the seat records the window in its `consumed_window_id` — a two-way link that makes the later release reversible."

    Design: Corner/endpoints/offering_a_seat_links_a_writer_a_room_and_the_window_that_covers_it
    """
    world = X.build_staffing_room_world(api)
    room_version = world["room_version"]

    validate_error(
        api.offer_seat(
            NON_EXISTENT_UUID,
            F.build_seat_offer(world["w1_id"], room_version),
            world["sr_headers"],
        ),
        ApiErrorId.ROOM_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.offer_seat(
            world["room_id"],
            F.build_seat_offer(NON_EXISTENT_UUID, room_version),
            world["sr_headers"],
        ),
        ApiErrorId.WRITER_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.offer_seat(
            world["room_id"],
            F.build_seat_offer(
                world["w3_id"],
                room_version,
                level_at_hire="STAFF_WRITER",
                offered_weekly_compensation_cents=450000,
                exclusivity="NON_EXCLUSIVE",
            ),
            world["sr_headers"],
        ),
        ApiErrorId.WRITER_UNAVAILABLE,
        expected_status=409,
    )

    seat = validate_success(
        api.offer_seat(
            world["room_id"],
            F.build_seat_offer(world["w1_id"], room_version),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_field_values(
        seat,
        room_id=world["room_id"],
        writer_id=world["w1_id"],
        status="OFFERED",
        consumed_window_id=None,
        confirmed_at=None,
        guarantee_slots_consumed=0,
        guarantee_slots_remaining=1,
    )

    confirmed = X.accept_seat(api, seat["id"], world["w1_id"])
    A.assert_field_values(confirmed, consumed_window_id=world["aw1_id"])
    A.assert_field_values(
        X.read_window(api, world["aw1_id"]),
        status="CONSUMED",
        consumed_by_seat_id=seat["id"],
    )

    windows, window_meta = validate_paginated(
        api.list_availability_windows(
            GUILD_ADMINISTRATOR_HEADERS,
            {"consumed_by_seat_id": seat["id"], "limit": 100},
        )
    )
    assert window_meta["total_count"] == 1 and windows[0]["id"] == world["aw1_id"], windows
    seats_by_window, seat_meta = validate_paginated(
        api.list_room_seats(
            STUDIO_EXECUTIVE_HEADERS,
            {"consumed_window_id": world["aw1_id"], "limit": 100},
        )
    )
    assert seat_meta["total_count"] == 1 and seats_by_window[0]["id"] == seat["id"], (
        seats_by_window
    )

    of_room, _ = validate_paginated(
        api.list_room_seats(
            STUDIO_EXECUTIVE_HEADERS, {"room_id": world["room_id"], "limit": 100}
        )
    )
    assert len(of_room) == 1, f"Only the surviving offer created a seat: {of_room}"
    of_w3, w3_meta = validate_paginated(
        api.list_room_seats(
            STUDIO_EXECUTIVE_HEADERS, {"writer_id": world["w3_id"], "limit": 100}
        )
    )
    assert w3_meta["total_count"] == 0 and of_w3 == [], of_w3


def test_season_and_ledger_reads_return_the_calculated_figures_not_stored_copies(api):
    """Every derived number on the season read reconciles against its own lists.

    PRD: "**Season staffing commitment** is the sum of `weekly_burn_cents` over the season's rooms whose status is `STAFFING` or `ACTIVE`; rooms that are still `OPEN` and rooms that have `WRAPPED` retain their computed burn but are excluded from the sum."

    PRD: "The season's `script_fee_committed_cents` is then recomputed as the signed sum of every ledger entry of that season — it is never incremented in place."

    PRD: "Creating an assignment therefore appends a `SCRIPT_FEE_ACCRUAL` entry for the full gross and, when a slot applied at creation, a `GUARANTEE_OFFSET` entry for the negative offset."

    PRD: "A fee ledger entry has no `updated_at` and no `version` field at all, and no endpoint exists to change one."

    PRD: "An episode counts toward `ready_script_count` only when *both* dimensions permit: its `script_readiness` is `READY` or `LOCKED`, **and** its `clearance_posture` is `CLEARED` or `CONDITIONAL_WAIVED`."

    PRD: "The `coverage_posture` is then `COVERED` when the gap is exactly 0, `AT_RISK` when the gap is 1 or 2, and `CRITICAL` for any gap above 2."

    Design: Corner/endpoints/season_and_ledger_reads_return_the_calculated_figures_not_stored_copies
    """
    world = X.build_approved_assignment_world(api)
    story = X.seed_assignment(
        api, world["ep1_id"], world["w2_id"], world["sr_headers"], assignment_type="STORY"
    )
    A.assert_assignment_settlement(story, STORY_GROSS_ONE_HOUR, False, 0, STORY_GROSS_ONE_HOUR)

    season = X.read_season(api, world["season_id"])
    burn_sum, active_rooms = _room_burn_sum(api, world["season_id"], "ACTIVE")
    assert len(active_rooms) == 1, active_rooms
    A.assert_cents(
        season["staffing_commitment_weekly_cents"],
        ACTIVE_ROOM_BURN,
        "staffing_commitment_weekly_cents",
    )
    A.assert_cents(burn_sum, ACTIVE_ROOM_BURN, "the room list's own burn total")
    A.assert_room_burn(
        active_rooms[0],
        ACTIVE_ROOM_SUBTOTAL,
        K.FACILITY_TIER_1,
        K.FACILITY_FEE_TIERS["TIER_1"],
        ACTIVE_ROOM_BURN,
    )

    entries = X.ledger_for_season(api, world["season_id"])
    assert len(entries) == 3, f"Two creations and one offset make three rows: {entries}"
    for entry in entries:
        A.assert_ledger_common_fields(entry)
        assert entry["season_id"] == world["season_id"], entry
    A.assert_ledger_sum(entries, COMMITTED_SCRIPT_MONEY)
    A.assert_cents(
        season["script_fee_committed_cents"],
        COMMITTED_SCRIPT_MONEY,
        "script_fee_committed_cents",
    )
    teleplay_entries = X.ledger_for_assignment(api, world["a1_id"])
    assert len(teleplay_entries) == 2, teleplay_entries
    # PRD: "Creating an assignment therefore appends a `SCRIPT_FEE_ACCRUAL` entry
    # for the full gross and, when a slot applied at creation, a
    # `GUARANTEE_OFFSET` entry for the negative offset."
    assert A.entry_types(teleplay_entries) == [
        "SCRIPT_FEE_ACCRUAL",
        "GUARANTEE_OFFSET",
    ], teleplay_entries
    A.assert_ledger_sum(
        teleplay_entries, TELEPLAY_GROSS_ONE_HOUR - TELEPLAY_OFFSET_ONE_HOUR
    )

    A.assert_field_values(
        season, ready_script_count=0, coverage_gap=1, coverage_posture="AT_RISK"
    )
    ready = _episode_rows(
        api, {"season_id": world["season_id"], "script_readiness": "READY", "limit": 100}
    )
    assert len(ready) == 1 and ready[0]["clearance_posture"] == "PENDING", ready
    cleared = _episode_rows(
        api,
        {"season_id": world["season_id"], "clearance_posture": "CLEARED", "limit": 100},
    )
    assert cleared == [], f"No episode is cleared yet, so none is countable: {cleared}"
    A.assert_cents(
        season["staffing_budget_weekly_cents"], 5000000, "staffing_budget_weekly_cents"
    )


def test_a_legal_waiver_is_available_only_while_the_review_sits_at_conditional(api):
    """The release valve opens on a computed posture and shuts once it is used.

    PRD: "The waiver is legal counsel's release valve on a merely conditional review. It requires a `waiver_memo`, and the review's `posture` must be exactly `CONDITIONAL`; a waiver on a `PENDING`, `CLEARED`, `ESCALATED` or `BLOCKED` review — or on one already waived — is rejected with `ERR_WAIVER_NOT_APPLICABLE`."

    PRD: "The waiver moves `posture` to `CONDITIONAL_WAIVED`, sets `legal_waiver_granted` true, stores the `waiver_memo`, mirrors `CONDITIONAL_WAIVED` onto the episode's `clearance_posture`, recomputes the season's coverage figures — the episode now counts as a ready script — and increments the review's `version`."

    PRD: "`PENDING` otherwise, which covers both the review with no items at all and the review whose items are all still undecided."

    PRD: "The decision sets the item's `risk_weight` to the agreement's `clearance_item_weights` entry for the item's `item_type` multiplied by a decision multiplier of 0 for `CLEARED`, 1 for `CONDITIONAL` and 4 for `BLOCKED`."

    PRD: "An episode counts toward `ready_script_count` only when *both* dimensions permit: its `script_readiness` is `READY` or `LOCKED`, **and** its `clearance_posture` is `CLEARED` or `CONDITIONAL_WAIVED`."

    Design: Corner/endpoints/a_legal_waiver_is_available_only_while_the_review_sits_at_conditional
    """
    world = X.build_clearance_world(api)
    depiction = X.seed_clearance_item(
        api, world["review_id"], "DEPICTION", "Senator drawn from a sitting official", "2C"
    )
    name = X.seed_clearance_item(api, world["review_id"], "NAME")

    validate_error(
        api.grant_clearance_waiver(
            world["review_id"], F.build_waiver("Premature."), LEGAL_COUNSEL_HEADERS
        ),
        ApiErrorId.WAIVER_NOT_APPLICABLE,
    )
    A.assert_field_values(
        X.read_review(api, world["review_id"]),
        posture="PENDING",
        legal_waiver_granted=False,
        waiver_memo=None,
    )

    X.decide_item(api, name["id"], "CLEARED")
    A.assert_field_values(
        X.read_review(api, world["review_id"]),
        posture="PENDING",
        risk_score=0,
        item_count=2,
        decided_item_count=1,
    )
    validate_error(
        api.grant_clearance_waiver(
            world["review_id"], F.build_waiver("Still premature."), LEGAL_COUNSEL_HEADERS
        ),
        ApiErrorId.WAIVER_NOT_APPLICABLE,
    )

    X.decide_item(api, depiction["id"], "CONDITIONAL", CONDITIONAL_NOTE)
    A.assert_field_values(
        X.read_review(api, world["review_id"]),
        risk_score=K.CLEARANCE_ITEM_WEIGHTS["DEPICTION"],
        posture="CONDITIONAL",
    )
    episode = X.read_episode(api, world["ep1_id"])
    A.assert_field_values(
        episode, clearance_posture="CONDITIONAL", script_readiness="READY"
    )
    A.assert_field_values(
        X.read_season(api, world["season_id"]),
        ready_script_count=0,
        coverage_gap=1,
        coverage_posture="AT_RISK",
    )

    waived = X.grant_waiver(api, world["review_id"], WAIVER_MEMO)
    A.assert_field_values(
        waived,
        posture="CONDITIONAL_WAIVED",
        legal_waiver_granted=True,
        waiver_memo=WAIVER_MEMO,
        risk_score=K.CLEARANCE_ITEM_WEIGHTS["DEPICTION"],
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), clearance_posture="CONDITIONAL_WAIVED"
    )
    A.assert_field_values(
        X.read_season(api, world["season_id"]),
        ready_script_count=1,
        coverage_gap=0,
        coverage_posture="COVERED",
    )

    validate_error(
        api.grant_clearance_waiver(
            world["review_id"], F.build_waiver("Second bite."), LEGAL_COUNSEL_HEADERS
        ),
        ApiErrorId.WAIVER_NOT_APPLICABLE,
    )
    A.assert_field_values(
        X.read_review(api, world["review_id"]), waiver_memo=WAIVER_MEMO
    )
