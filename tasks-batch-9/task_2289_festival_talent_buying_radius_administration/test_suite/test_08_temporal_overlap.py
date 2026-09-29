"""Overlap over time: buffered stage intervals, closed clause windows, day loads.

Every test below builds its own preconditions from an empty database, because
the server is restarted before each test.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    PRODUCTION_MANAGER,
    TALENT_BUYER,
    expected_adjudicated_risk_score,
    expected_distance_miles,
    expected_strict_risk_score,
)
from test_helpers import fixtures as fx
from test_helpers.constants import (
    MARKET_LATITUDE,
    MARKET_LONGITUDE,
    PORTLAND_LATITUDE,
    PORTLAND_LONGITUDE,
)

CLOCK_AT_PLANNING = "2026-08-01T00:00:00Z"
BOISE_LATITUDE = 43.6150
BOISE_LONGITUDE = -116.2023


# --------------------------------------------------------------------------
# One flagship stage carrying an accepted 19:00-20:30 set plus four probes.
# --------------------------------------------------------------------------
def _aurora_line_with_anchor_and_probes(api):
    fx.set_clock(api, CLOCK_AT_PLANNING)
    festival = fx.create_festival(api)
    tier = fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=1.00,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.allocate(api, festival)
    stage = fx.create_stage(api, festival["id"], daily_program_minutes_cap=900)
    anchor = fx.create_artist(api)
    ctx = {"festival": festival, "tier": tier, "stage": stage, "artist": anchor}

    booking = fx.accepted_booking(
        api, ctx, anchor, billing_position=1, slot_start_utc="2026-12-05T19:00:00Z"
    )

    def probe(performing_name, legal_name, genre, agency, billing_position, slot_start_utc):
        artist = fx.create_artist(
            api,
            legal_name=legal_name,
            performing_name=performing_name,
            primary_genre=genre,
            agency=agency,
            draw_score=20,
            default_radius_miles=75,
        )
        return fx.draft_offer(
            api,
            ctx,
            artist,
            guarantee_cents=500000,
            production_fee_cents=0,
            billing_position=billing_position,
            set_length_minutes=90,
            slot_start_utc=slot_start_utc,
            radius_miles=75,
            window_start_date="2026-11-04",
            window_end_date="2026-12-14",
        )

    gap_equals_buffer = probe(
        "Vela Trio", "Vela Trio LLC", "JAZZ_SOUL", "Foghorn Agency", 2, "2026-12-05T21:00:00Z"
    )
    exact_abutment = probe(
        "Hollow Pines", "Hollow Pines LLC", "COUNTRY", "Foghorn Agency", 3,
        "2026-12-05T17:30:00Z",
    )
    far_gap = probe(
        "Pale Signal", "Pale Signal LLC", "POP", "Foghorn Agency", 4, "2026-12-05T14:00:00Z"
    )
    draft_only_collision = probe(
        "Sol Ateneo", "Sol Ateneo LLC", "LATIN", "Meridian Talent", 5, "2026-12-05T16:30:00Z"
    )

    return {
        "stage": stage,
        "booking": booking,
        "gap_equals_buffer": gap_equals_buffer,
        "exact_abutment": exact_abutment,
        "far_gap": far_gap,
        "draft_only_collision": draft_only_collision,
    }


def test_a_gap_of_exactly_the_changeover_buffer_clears_the_booking(api):
    """The 21:00 set starts exactly one buffer after the booking's 20:30 end.

    "A collision exists when, for some occupant, the evaluated set's start is strictly earlier than that occupant's end advanced by the buffer *and* that occupant's start is strictly earlier than the evaluated set's end advanced by the buffer."
    "Both comparisons are strict."

    Design: Difficulty/resource_temporal_overlap/stage_buffered_abutment_conflict
    """
    line = _aurora_line_with_anchor_and_probes(api)

    issued = validate_success(
        api.issue_offer(line["gap_equals_buffer"]["id"], TALENT_BUYER)
    )
    assert issued["status"] == "ISSUED"


def test_exact_abutment_collides_when_the_stage_carries_a_buffer(api):
    """The probe ends at 19:00, the very instant the booked set begins.

    "The practical consequence is worth stating: two sets that abut exactly, where one ends at the very instant the other begins, collide when the stage carries any changeover buffer at all and do not collide when the buffer is 0."
    "A collision is `ERR_STAGE_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/stage_buffered_abutment_conflict
    """
    line = _aurora_line_with_anchor_and_probes(api)
    validate_success(api.issue_offer(line["gap_equals_buffer"]["id"], TALENT_BUYER))

    validate_error(
        api.issue_offer(line["exact_abutment"]["id"], TALENT_BUYER),
        "ERR_STAGE_SLOT_CONFLICT",
        409,
    )

    refused = validate_success(api.get_offer(line["exact_abutment"]["id"], TALENT_BUYER))
    assert refused["status"] == "DRAFT"


def test_a_probe_clear_of_every_occupant_by_more_than_the_buffer_is_issued(api):
    """The 14:00-15:30 set clears the refused draft at 17:30 and the booking at 19:00.

    "The occupants of a stage are every other offer on that stage whose `status` is `DRAFT`, `ISSUED` or `COUNTERED` — the offer under evaluation is excluded from its own occupant set — plus every booking on that stage whose `contract_status` is not `CANCELLED`."

    Design: Difficulty/resource_temporal_overlap/stage_buffered_abutment_conflict
    """
    line = _aurora_line_with_anchor_and_probes(api)
    validate_success(api.issue_offer(line["gap_equals_buffer"]["id"], TALENT_BUYER))
    validate_error(
        api.issue_offer(line["exact_abutment"]["id"], TALENT_BUYER),
        "ERR_STAGE_SLOT_CONFLICT",
        409,
    )

    issued = validate_success(api.issue_offer(line["far_gap"]["id"], TALENT_BUYER))
    assert issued["status"] == "ISSUED"


def test_a_probe_whose_only_overlap_is_a_draft_offer_is_refused(api):
    """The 16:30-18:00 set clears the booking but not the still-DRAFT 17:30 probe.

    "The occupants of a stage are every other offer on that stage whose `status` is `DRAFT`, `ISSUED` or `COUNTERED` — the offer under evaluation is excluded from its own occupant set — plus every booking on that stage whose `contract_status` is not `CANCELLED`."
    "A draft commits no budget and reserves no stage time."

    Design: Difficulty/resource_temporal_overlap/stage_buffered_abutment_conflict
    """
    line = _aurora_line_with_anchor_and_probes(api)
    validate_success(api.issue_offer(line["gap_equals_buffer"]["id"], TALENT_BUYER))
    validate_error(
        api.issue_offer(line["exact_abutment"]["id"], TALENT_BUYER),
        "ERR_STAGE_SLOT_CONFLICT",
        409,
    )
    validate_success(api.issue_offer(line["far_gap"]["id"], TALENT_BUYER))

    validate_error(
        api.issue_offer(line["draft_only_collision"]["id"], TALENT_BUYER),
        "ERR_STAGE_SLOT_CONFLICT",
        409,
    )

    stage = validate_success(api.get_stage(line["stage"]["id"], PRODUCTION_MANAGER))
    assert stage["booked_minutes"] == 90


# --------------------------------------------------------------------------
# One ACTIVE clause whose closed window runs 2026-10-05 to 2027-01-04.
# --------------------------------------------------------------------------
def _edition_with_one_active_clause(api):
    fx.set_clock(api, CLOCK_AT_PLANNING)
    festival = fx.create_festival(api)
    tier = fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=1.00,
        max_slots=1,
        genre_focus="ELECTRONIC",
    )
    fx.allocate(api, festival)
    stage = fx.create_stage(api, festival["id"])
    artist = fx.create_artist(api)
    ctx = {"festival": festival, "tier": tier, "stage": stage, "artist": artist}

    booking = fx.accepted_booking(api, ctx, artist)
    clause = fx.clause_of_booking(api, booking["id"])
    assert clause["enforcement_status"] == "ACTIVE"
    return {"artist": artist, "booking": booking, "clause": clause}


def _report_portland(api, artist_id, performance_date):
    return fx.report_performance(
        api,
        artist_id,
        venue_city="Portland",
        venue_latitude=PORTLAND_LATITUDE,
        venue_longitude=PORTLAND_LONGITUDE,
        performance_date=performance_date,
    )


def _report_boise(api, artist_id, performance_date):
    return fx.report_performance(
        api,
        artist_id,
        venue_city="Boise",
        venue_latitude=BOISE_LATITUDE,
        venue_longitude=BOISE_LONGITUDE,
        performance_date=performance_date,
    )


def test_a_show_on_the_window_end_date_itself_is_a_conflict(api):
    """The last day of the exclusivity window is inside it.

    "At creation the system selects, from all clauses, the candidate set: clauses belonging to the same act, whose `enforcement_status` is `ACTIVE` — `PROVISIONAL`, `BREACHED`, `WAIVED` and `RELEASED` clauses never enter the candidate set at all — whose closed window contains the `performance_date` inclusive of both endpoints, whose scope reaches this performance, and whose mileage covers the venue."
    "Otherwise the candidates are ranked by `radius_miles` descending, then `window_start_date` ascending, then `created_at` ascending, and the first is the winner: `conflict_assessment` becomes `CONFLICT`, `conflicting_radius_clause_id` names the winning clause, and `distance_to_market_miles` records the distance to that winner's market, rounded half up to two decimals."

    Design: Difficulty/resource_temporal_overlap/radius_window_closed_interval_boundary_conflict
    """
    state = _edition_with_one_active_clause(api)

    report = _report_portland(api, state["artist"]["id"], "2027-01-04")
    assert report["conflict_assessment"] == "CONFLICT"
    assert report["conflicting_radius_clause_id"] == state["clause"]["id"]
    assert report["distance_to_market_miles"] == 145.41
    assert report["distance_to_market_miles"] == expected_distance_miles(
        MARKET_LATITUDE, MARKET_LONGITUDE, PORTLAND_LATITUDE, PORTLAND_LONGITUDE
    )


def test_a_show_the_day_after_the_window_ends_is_outside_it(api):
    """One day past the closing endpoint leaves the candidate set empty.

    "If the candidate set is empty, the report's `conflict_assessment` is `NO_CONFLICT`, its `conflicting_radius_clause_id` is null and its `distance_to_market_miles` is null."

    Design: Difficulty/resource_temporal_overlap/radius_window_closed_interval_boundary_conflict
    """
    state = _edition_with_one_active_clause(api)

    report = _report_portland(api, state["artist"]["id"], "2027-01-05")
    assert report["conflict_assessment"] == "NO_CONFLICT"
    assert report["conflicting_radius_clause_id"] is None
    assert report["distance_to_market_miles"] is None


def test_a_show_on_the_window_start_date_itself_is_a_conflict(api):
    """The window is closed at its opening endpoint too, not half-open.

    "At creation the system selects, from all clauses, the candidate set: clauses belonging to the same act, whose `enforcement_status` is `ACTIVE` — `PROVISIONAL`, `BREACHED`, `WAIVED` and `RELEASED` clauses never enter the candidate set at all — whose closed window contains the `performance_date` inclusive of both endpoints, whose scope reaches this performance, and whose mileage covers the venue."

    Design: Difficulty/resource_temporal_overlap/radius_window_closed_interval_boundary_conflict
    """
    state = _edition_with_one_active_clause(api)

    report = _report_portland(api, state["artist"]["id"], "2026-10-05")
    assert report["conflict_assessment"] == "CONFLICT"
    assert report["conflicting_radius_clause_id"] == state["clause"]["id"]
    assert report["distance_to_market_miles"] == 145.41


def test_a_show_the_day_before_the_window_opens_is_outside_it(api):
    """The window is exactly the inclusive span between its two stored dates.

    "If the candidate set is empty, the report's `conflict_assessment` is `NO_CONFLICT`, its `conflicting_radius_clause_id` is null and its `distance_to_market_miles` is null."

    Design: Difficulty/resource_temporal_overlap/radius_window_closed_interval_boundary_conflict
    """
    state = _edition_with_one_active_clause(api)

    report = _report_portland(api, state["artist"]["id"], "2026-10-04")
    assert report["conflict_assessment"] == "NO_CONFLICT"
    assert report["conflicting_radius_clause_id"] is None
    assert report["distance_to_market_miles"] is None


def test_a_show_inside_the_window_but_beyond_the_mileage_is_no_conflict(api):
    """Boise sits mid-window at 404.52 miles, well past the clause's 150.

    "Mileage covers the venue when the great-circle distance from the clause's festival market to the venue, rounded half up to two decimal places, is at or below the clause's `radius_miles` — the comparison is inclusive, so a venue at exactly the clause mileage is inside."
    "If the candidate set is empty, the report's `conflict_assessment` is `NO_CONFLICT`, its `conflicting_radius_clause_id` is null and its `distance_to_market_miles` is null."

    Design: Difficulty/resource_temporal_overlap/radius_window_closed_interval_boundary_conflict
    """
    state = _edition_with_one_active_clause(api)
    assert (
        expected_distance_miles(
            MARKET_LATITUDE, MARKET_LONGITUDE, BOISE_LATITUDE, BOISE_LONGITUDE
        )
        == 404.52
    )

    report = _report_boise(api, state["artist"]["id"], "2026-11-20")
    assert report["conflict_assessment"] == "NO_CONFLICT"
    assert report["conflicting_radius_clause_id"] is None
    assert report["distance_to_market_miles"] is None


def test_only_the_detected_conflicts_move_the_acts_risk_scores(api):
    """Five reports, two of them inside both predicates, none adjudicated.

    "A report that lands as a `CONFLICT` raises the act's `reported_conflict_count` and re-derives its `strict_risk_score`; the act's `adjudicated_risk_score` is deliberately untouched, so a fresh report alone can never block issuance."
    "`strict_risk_score` is the smaller of 100 and the sum of twelve points per unadjudicated conflict, twenty-five points per adjudicated breach, and the draw penalty."

    Design: Difficulty/resource_temporal_overlap/radius_window_closed_interval_boundary_conflict
    """
    state = _edition_with_one_active_clause(api)
    artist_id = state["artist"]["id"]

    _report_portland(api, artist_id, "2027-01-04")
    _report_portland(api, artist_id, "2027-01-05")
    _report_portland(api, artist_id, "2026-10-05")
    _report_portland(api, artist_id, "2026-10-04")
    _report_boise(api, artist_id, "2026-11-20")

    artist = validate_success(api.get_artist(artist_id, TALENT_BUYER))
    assert artist["reported_conflict_count"] == 2
    assert artist["radius_breach_count"] == 0
    assert artist["strict_risk_score"] == 30
    assert artist["strict_risk_score"] == expected_strict_risk_score(2, 0, 72)
    assert artist["adjudicated_risk_score"] == 6
    assert artist["adjudicated_risk_score"] == expected_adjudicated_risk_score(0, 72)


# --------------------------------------------------------------------------
# A side stage whose day cap admits exactly three buffered 90-minute sets.
# --------------------------------------------------------------------------
GROVE_ACTS = [
    ("Vela Trio", "Vela Trio LLC", "JAZZ_SOUL", "Foghorn Agency"),
    ("Hollow Pines", "Hollow Pines LLC", "COUNTRY", "Foghorn Agency"),
    ("Pale Signal", "Pale Signal LLC", "POP", "Foghorn Agency"),
    ("Sol Ateneo", "Sol Ateneo LLC", "LATIN", "Meridian Talent"),
]


def _grove_edition(api):
    fx.set_clock(api, CLOCK_AT_PLANNING)
    festival = fx.create_festival(api)
    tier = fx.create_tier(
        api,
        festival["id"],
        tier_code="MID_CARD",
        tier_rank=1,
        allocation_pct=1.00,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.allocate(api, festival)
    stage = fx.create_stage(
        api,
        festival["id"],
        name="Grove",
        capacity=6000,
        daily_curfew_minute=1200,
        daily_program_minutes_cap=360,
        changeover_buffer_minutes=30,
        is_flagship=False,
    )
    artists = [
        fx.create_artist(
            api,
            legal_name=legal_name,
            performing_name=performing_name,
            primary_genre=genre,
            agency=agency,
            draw_score=20,
            default_radius_miles=75,
        )
        for performing_name, legal_name, genre, agency in GROVE_ACTS
    ]
    return {"festival": festival, "tier": tier, "stage": stage, "artists": artists}


def _grove_slot(api, grove, index, billing_position, slot_start_utc):
    """Draft one 90-minute Grove set; a DRAFT already counts toward the day load."""
    return fx.draft_offer(
        api,
        grove,
        grove["artists"][index],
        guarantee_cents=500000,
        production_fee_cents=0,
        billing_position=billing_position,
        set_length_minutes=90,
        slot_start_utc=slot_start_utc,
        radius_miles=75,
        window_start_date="2026-11-04",
        window_end_date="2026-12-14",
    )


def test_a_day_load_exactly_equal_to_the_cap_is_allowed(api):
    """Three buffered 90-minute sets make 360 minutes, the cap to the minute.

    "Sum, over every other offer on that stage in `DRAFT`, `ISSUED` or `COUNTERED` whose set starts on that date, the offer's `set_length_minutes` plus the stage's `changeover_buffer_minutes`; add the same quantity for every booking on that stage that is not `CANCELLED` and starts on that date; then add the evaluated offer's own `set_length_minutes` plus one changeover buffer, counted exactly once."
    "If that total exceeds `daily_program_minutes_cap` the request is refused with `ERR_STAGE_DAY_CAP_EXCEEDED`; a total exactly equal to the cap is allowed."

    Design: Difficulty/resource_temporal_overlap/stage_day_aggregate_minutes_cap
    """
    grove = _grove_edition(api)
    first = _grove_slot(api, grove, 0, 2, "2026-12-05T12:00:00Z")
    validate_success(api.issue_offer(first["id"], TALENT_BUYER))
    second = _grove_slot(api, grove, 1, 3, "2026-12-05T14:00:00Z")
    validate_success(api.issue_offer(second["id"], TALENT_BUYER))

    third = _grove_slot(api, grove, 2, 4, "2026-12-05T16:00:00Z")
    issued = validate_success(api.issue_offer(third["id"], TALENT_BUYER))
    assert issued["status"] == "ISSUED"


def test_the_fourth_buffered_set_overflows_the_day_although_no_pair_overlaps(api):
    """Every gap is exactly the buffer, yet the summed day load reaches 480.

    "The **day load** rule is evaluated on issuance and on revision, and it is an aggregate rather than a pairwise test — every individual set can fit and no pair can overlap while the day as a whole still overflows."
    "If that total exceeds `daily_program_minutes_cap` the request is refused with `ERR_STAGE_DAY_CAP_EXCEEDED`; a total exactly equal to the cap is allowed."

    Design: Difficulty/resource_temporal_overlap/stage_day_aggregate_minutes_cap
    """
    grove = _grove_edition(api)
    for index, (billing_position, slot) in enumerate(
        [(2, "2026-12-05T12:00:00Z"), (3, "2026-12-05T14:00:00Z"), (4, "2026-12-05T16:00:00Z")]
    ):
        offer = _grove_slot(api, grove, index, billing_position, slot)
        validate_success(api.issue_offer(offer["id"], TALENT_BUYER))

    fourth = _grove_slot(api, grove, 3, 5, "2026-12-05T18:00:00Z")
    validate_error(
        api.issue_offer(fourth["id"], TALENT_BUYER), "ERR_STAGE_DAY_CAP_EXCEEDED", 409
    )

    refused = validate_success(api.get_offer(fourth["id"], TALENT_BUYER))
    assert refused["status"] == "DRAFT"


def test_the_same_four_sets_spread_across_the_event_dates_all_pass(api):
    """The load is summed per UTC calendar date, not per edition.

    "Take the UTC calendar date on which the evaluated set starts."
    "If that total exceeds `daily_program_minutes_cap` the request is refused with `ERR_STAGE_DAY_CAP_EXCEEDED`; a total exactly equal to the cap is allowed."

    Design: Difficulty/resource_temporal_overlap/stage_day_aggregate_minutes_cap
    """
    grove = _grove_edition(api)
    spread = [
        (2, "2026-12-04T12:00:00Z"),
        (3, "2026-12-05T12:00:00Z"),
        (4, "2026-12-06T12:00:00Z"),
        (5, "2026-12-04T14:00:00Z"),
    ]
    for index, (billing_position, slot) in enumerate(spread):
        offer = _grove_slot(api, grove, index, billing_position, slot)
        issued = validate_success(api.issue_offer(offer["id"], TALENT_BUYER))
        assert issued["status"] == "ISSUED"
