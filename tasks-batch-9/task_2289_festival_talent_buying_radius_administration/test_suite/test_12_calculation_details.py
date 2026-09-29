"""Arithmetic detail of the festival talent-buying API.

Every test below builds its own preconditions from an empty database, because
the server is restarted before each test, and sets the logical clock explicitly
whenever a temporal rule is in play. Expected figures are cross-checked against
the pure re-implementations in test_helpers.assertions.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    BUSINESS_AFFAIRS,
    FINANCE_CONTROLLER,
    PRODUCTION_MANAGER,
    TALENT_BUYER,
    expected_distance_miles,
    expected_draw_penalty,
    expected_line_cost_cents,
    expected_settlement_total_cents,
    make_artist_rep_headers,
    round_half_up,
)
from test_helpers import fixtures as fx
from test_helpers.constants import (
    ALLOCATABLE_BUDGET_CENTS,
    DEFAULT_CLOCK_UTC,
    GENRE_FACTOR_SOFT,
    HOSPITALITY_LINE_CAP_CENTS,
    PORTLAND_DISTANCE_MILES,
    TALENT_BUDGET_CENTS,
)
from test_helpers.factories import competing_performance_payload, offer_payload

CANONICAL_TIER_SPECS = (
    ("HEADLINER", 1, 0.50),
    ("MID_CARD", 2, 0.30),
    ("EMERGING", 3, 0.20),
)


# --------------------------------------------------------------- local builders
def _edition(
    api,
    clock=DEFAULT_CLOCK_UTC,
    talent_budget_cents=TALENT_BUDGET_CENTS,
    contingency_reserve_pct=0.05,
    tier_specs=CANONICAL_TIER_SPECS,
    max_slots=5,
):
    """Allocated Harbor Lights edition with one flagship stage.

    Returns {"festival": row, "tiers": {tier_code: row}, "stage": row}; the
    festival row is the post-allocation read so its counters are current.
    """
    fx.set_clock(api, clock)
    festival = fx.create_festival(
        api,
        talent_budget_cents=talent_budget_cents,
        contingency_reserve_pct=contingency_reserve_pct,
    )
    tiers = {}
    for code, rank, pct in tier_specs:
        tiers[code] = fx.create_tier(
            api,
            festival["id"],
            tier_code=code,
            tier_rank=rank,
            allocation_pct=pct,
            max_slots=max_slots,
            genre_focus="MIXED",
        )
    fx.allocate(api, validate_success(api.get_festival(festival["id"], TALENT_BUYER)))
    stage = fx.create_stage(api, festival["id"])
    festival = validate_success(api.get_festival(festival["id"], TALENT_BUYER))
    for code, tier in list(tiers.items()):
        tiers[code] = validate_success(api.get_budget_tier(tier["id"], TALENT_BUYER))
    return {"festival": festival, "tiers": tiers, "stage": stage}


def _draft(api, ctx, artist_id, tier_code, **overrides):
    payload = offer_payload(
        ctx["festival"]["id"],
        artist_id,
        ctx["tiers"][tier_code]["id"],
        ctx["stage"]["id"],
        **overrides,
    )
    return validate_success(api.create_offer(payload, TALENT_BUYER), 201)


def _issue(api, offer_id):
    return validate_success(api.issue_offer(offer_id, TALENT_BUYER))


def _accept(api, offer_id, artist_id):
    return validate_success(
        api.accept_offer(offer_id, make_artist_rep_headers(artist_id)), 201
    )


def _report(api, artist_id, **overrides):
    return validate_success(
        api.create_competing_performance(
            competing_performance_payload(artist_id, **overrides), BUSINESS_AFFAIRS
        ),
        201,
    )


# ------------------------------------------------------------ budget waterfall
def test_waterfall_remainder_lands_whole_on_the_lowest_ranked_tier(api):
    """A fractional split floors per tier and hands the whole remainder to rank 1.

    "Then each tier's `allocation_cents` is set to the edition's `allocatable_budget_cents` multiplied by that tier's `allocation_pct` and **floored** to whole cents — floored per tier, never rounded half up."
    "Flooring leaves a remainder: the difference between `allocatable_budget_cents` and the sum of the floored per-tier figures is added, whole and un-floored, to the single tier with the lowest `tier_rank`."
    Design: Corner/calculations/tier_waterfall_remainder_assigned_to_lowest_rank
    """
    fx.set_clock(api, DEFAULT_CLOCK_UTC)
    festival = fx.create_festival(
        api, talent_budget_cents=999999, contingency_reserve_pct=0.0
    )
    assert festival["allocatable_budget_cents"] == 999999
    for code, rank, pct in CANONICAL_TIER_SPECS:
        fx.create_tier(
            api,
            festival["id"],
            tier_code=code,
            tier_rank=rank,
            allocation_pct=pct,
            max_slots=5,
            genre_focus="MIXED",
        )

    before = validate_success(api.get_festival(festival["id"], TALENT_BUYER))
    response = api.allocate_tiers(
        festival["id"], {"expected_festival_version": before["version"]}, TALENT_BUYER
    )
    tiers = validate_success(response)
    assert response.json()["response_type"] == "array"
    assert len(tiers) == 3

    assert tiers[0]["tier_rank"] == 1
    assert tiers[0]["allocation_cents"] == 500001
    assert tiers[1]["allocation_cents"] == 299999
    assert tiers[2]["allocation_cents"] == 199999
    assert sum(tier["allocation_cents"] for tier in tiers) == 999999

    after = validate_success(api.get_festival(festival["id"], TALENT_BUYER))
    assert after["tiers_allocated"] is True
    assert after["version"] == before["version"] + 1


def test_contingency_reserve_rounds_half_up_at_the_exact_half_cent(api):
    """A reserve of exactly 5000.5 cents rounds away from zero to 5001.

    "At registration the edition's `allocatable_budget_cents` is set to `talent_budget_cents` less the reserve, where the reserve is the `talent_budget_cents` multiplied by `contingency_reserve_pct` and rounded half up to whole cents, taken off the top exactly once."
    Design: Corner/calculations/contingency_reserve_uses_round_half_up_at_the_exact_half_cent
    """
    assert round_half_up(5000.5) == 5001, "half a cent rounds away from zero"

    fx.set_clock(api, DEFAULT_CLOCK_UTC)
    festival = fx.create_festival(
        api, talent_budget_cents=100010, contingency_reserve_pct=0.05
    )
    read = validate_success(api.get_festival(festival["id"], FINANCE_CONTROLLER))
    assert read["talent_budget_cents"] == 100010
    assert read["contingency_reserve_pct"] == pytest.approx(0.05)
    assert read["allocatable_budget_cents"] == 95009

    fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=1.00,
        max_slots=3,
        genre_focus="MIXED",
    )
    tiers = fx.allocate(
        api, validate_success(api.get_festival(festival["id"], TALENT_BUYER))
    )
    assert len(tiers) == 1
    assert tiers[0]["allocation_cents"] == 95009


# ------------------------------------------------------------------ rider cost
def test_travel_rider_lines_are_escalated_per_line_and_hospitality_is_capped_in_contracted_scope(
    api,
):
    """Twelve percent lands inside the travel line; the cap only bites in contracted scope.

    "Travel lines carry a twelve percent escalation to cover fare drift; lines in the other two categories carry none."
    "`line_cost_cents` is then the `quantity` multiplied by the effective unit price multiplied by one plus the escalation, rounded half up to whole cents."
    "`rider_estimate_cents` is the **contracted scope**: it sums only lines whose `approval_status` is `APPROVED` or `SUBSTITUTED` — dropping both undecided and rejected lines — contributes 0 for any line whose `is_promoter_provided` is true, contributes the lesser of the line's `line_cost_cents` and 150000 cents (fifteen hundred dollars) for any `HOSPITALITY` line, and contributes the full `line_cost_cents` otherwise."
    Design: Corner/calculations/rider_travel_escalation_and_hospitality_cap_are_line_scoped
    """
    ctx = _edition(api)
    artist = fx.create_artist(api, default_radius_miles=100)
    offer = _draft(
        api,
        ctx,
        artist["id"],
        "HEADLINER",
        guarantee_cents=1800000,
        slot_start_utc="2026-12-04T21:00:00Z",
    )
    _issue(api, offer["id"])
    booking = _accept(api, offer["id"], artist["id"])

    technical = fx.add_rider_line(
        api,
        booking["id"],
        artist["id"],
        category="TECHNICAL",
        description="Line-array PA package",
        quantity=1,
        unit_cost_cents=250000,
    )
    travel = fx.add_rider_line(
        api,
        booking["id"],
        artist["id"],
        category="TRAVEL",
        description="Long-haul airfare",
        quantity=3,
        unit_cost_cents=118750,
    )
    hospitality = fx.add_rider_line(
        api,
        booking["id"],
        artist["id"],
        category="HOSPITALITY",
        description="Dressing-room catering",
        quantity=4,
        unit_cost_cents=50000,
    )
    for line in (technical, travel, hospitality):
        fx.decide_rider_line(api, line["id"], "APPROVED")

    assert expected_line_cost_cents(3, 118750, "TRAVEL") == 399000
    assert expected_line_cost_cents(4, 50000, "HOSPITALITY") == 200000

    estimate = validate_success(
        api.get_rider_estimate(booking["id"], PRODUCTION_MANAGER, {"variant": "BOTH"})
    )
    assert estimate["proposed_scope_cents"] == 849000
    assert estimate["contracted_scope_cents"] == 799000
    assert estimate["variant_delta_cents"] == 50000
    assert estimate["priced_line_count"] == 3
    assert estimate["capped_line_count"] == 1
    assert estimate["zeroed_line_count"] == 0

    travel_row = validate_success(api.get_rider_item(travel["id"], PRODUCTION_MANAGER))
    assert travel_row["line_cost_cents"] == 399000
    hospitality_row = validate_success(
        api.get_rider_item(hospitality["id"], PRODUCTION_MANAGER)
    )
    assert hospitality_row["line_cost_cents"] == 200000
    assert hospitality_row["line_cost_cents"] > HOSPITALITY_LINE_CAP_CENTS

    final = validate_success(api.get_booking(booking["id"], FINANCE_CONTROLLER))
    assert final["rider_proposed_cents"] == 849000
    assert final["rider_estimate_cents"] == 799000
    assert final["contract_status"] == "RIDER_SETTLED"
    assert final["settlement_total_cents"] == 2399250
    assert final["settlement_total_cents"] == expected_settlement_total_cents(
        1800000, 799000, 0, 0
    )


# --------------------------------------------------------------------- risk
def test_draw_penalty_rounds_half_up_and_both_variants_agree_without_reports(api):
    """With an empty history each risk variant collapses onto the rounded draw penalty.

    "The draw penalty is 0.20 multiplied by the difference between 100 and the act's `draw_score`, rounded half up to a whole number of points — so a low-draw act carries a structural penalty of up to twenty points on its own."
    "It returns the requested `variant`, the act's `reported_conflict_count` and `radius_breach_count`, the `draw_penalty` in points, the resulting `risk_score`, and a `blocked` flag reflecting whether that variant's score has reached the blocking threshold of 60."
    Design: Corner/calculations/draw_penalty_rounds_half_up_and_both_variants_agree_without_reports
    """
    fx.set_clock(api, DEFAULT_CLOCK_UTC)
    high_draw = fx.create_artist(
        api,
        legal_name="Cassia Vale Touring Inc",
        performing_name="Cassia Vale",
        primary_genre="POP",
        draw_score=87,
        default_radius_miles=100,
    )
    low_draw = fx.create_artist(
        api,
        legal_name="Bramble Line LLC",
        performing_name="Bramble Line",
        primary_genre="COUNTRY",
        draw_score=40,
        default_radius_miles=100,
    )
    assert expected_draw_penalty(87) == 3, "0.20 * 13 = 2.6 rounds half up to 3"
    assert expected_draw_penalty(40) == 12

    strict = validate_success(
        api.get_radius_risk(high_draw["id"], BUSINESS_AFFAIRS, {"variant": "STRICT"})
    )
    assert strict["variant"] == "STRICT"
    assert strict["draw_penalty"] == 3
    assert strict["risk_score"] == 3
    assert strict["blocked"] is False

    adjudicated = validate_success(
        api.get_radius_risk(
            high_draw["id"], BUSINESS_AFFAIRS, {"variant": "ADJUDICATED"}
        )
    )
    assert adjudicated["variant"] == "ADJUDICATED"
    assert adjudicated["draw_penalty"] == 3
    assert adjudicated["risk_score"] == 3

    defaulted = validate_success(api.get_radius_risk(low_draw["id"], BUSINESS_AFFAIRS))
    assert defaulted["variant"] == "STRICT"
    assert defaulted["draw_penalty"] == 12
    assert defaulted["risk_score"] == 12
    assert defaulted["blocked"] is False
    assert defaulted["reported_conflict_count"] == 0
    assert defaulted["radius_breach_count"] == 0

    stored = validate_success(api.get_artist(low_draw["id"], TALENT_BUYER))
    assert stored["strict_risk_score"] == 0
    assert stored["adjudicated_risk_score"] == 0


# ----------------------------------------------------------- radius detection
def test_conflict_detection_ignores_a_provisional_clause(api):
    """The same Portland show is clear against a drafted clause and a conflict once issued.

    "At creation the system selects, from all clauses, the candidate set: clauses belonging to the same act, whose `enforcement_status` is `ACTIVE` — `PROVISIONAL`, `BREACHED`, `WAIVED` and `RELEASED` clauses never enter the candidate set at all — whose closed window contains the `performance_date` inclusive of both endpoints, whose scope reaches this performance, and whose mileage covers the venue."
    "If the candidate set is empty, the report's `conflict_assessment` is `NO_CONFLICT`, its `conflicting_radius_clause_id` is null and its `distance_to_market_miles` is null."
    Design: Corner/calculations/conflict_detection_ignores_provisional_clauses
    """
    ctx = _edition(api)
    artist = fx.create_artist(api, default_radius_miles=100)
    assert artist["strict_risk_score"] == 0, "a new act opens with a zero score"

    offer = _draft(
        api,
        ctx,
        artist["id"],
        "HEADLINER",
        guarantee_cents=1800000,
        slot_start_utc="2026-12-04T21:00:00Z",
        radius_miles=150,
        window_start_date="2026-10-05",
        window_end_date="2027-01-04",
    )
    clause = fx.clause_of_offer(api, offer["id"])
    assert clause["enforcement_status"] == "PROVISIONAL"

    before = _report(api, artist["id"], performance_date="2026-11-15")
    assert before["conflict_assessment"] == "NO_CONFLICT"
    assert before["conflicting_radius_clause_id"] is None
    assert before["distance_to_market_miles"] is None

    unmoved = validate_success(api.get_artist(artist["id"], BUSINESS_AFFAIRS))
    assert unmoved["reported_conflict_count"] == 0

    _issue(api, offer["id"])
    assert (
        validate_success(api.get_radius_clause(clause["id"], BUSINESS_AFFAIRS))[
            "enforcement_status"
        ]
        == "ACTIVE"
    )

    after = _report(api, artist["id"], performance_date="2026-11-16")
    assert after["conflict_assessment"] == "CONFLICT"
    assert after["distance_to_market_miles"] == PORTLAND_DISTANCE_MILES
    assert after["distance_to_market_miles"] == 145.41
    assert after["conflicting_radius_clause_id"] == clause["id"]

    replayed = validate_success(
        api.get_competing_performance(before["id"], BUSINESS_AFFAIRS)
    )
    assert replayed["conflict_assessment"] == "NO_CONFLICT"

    scored = validate_success(api.get_artist(artist["id"], BUSINESS_AFFAIRS))
    assert scored["reported_conflict_count"] == 1
    assert scored["strict_risk_score"] == 18


def test_exclusivity_scope_filters_the_candidate_set_by_show_shape(api):
    """A ticketed-only clause ignores a free show and a festival-only clause ignores a club date.

    "Scope reaches the performance when `exclusivity_scope` is `FULL`, or when it is `TICKETED_ONLY` and the report's `is_ticketed` is true, or when it is `FESTIVAL_ONLY` and the report's `is_festival` is true."
    Design: Corner/calculations/exclusivity_scope_filters_the_candidate_set_per_show_shape
    """
    ctx = _edition(api)
    nova = fx.create_artist(api, default_radius_miles=100)
    vela = fx.create_artist(
        api,
        legal_name="Vela Roan Touring Ltd",
        performing_name="Vela Roan",
        primary_genre="ROCK",
        draw_score=72,
        default_radius_miles=100,
    )

    ticketed_only = _draft(
        api,
        ctx,
        nova["id"],
        "HEADLINER",
        guarantee_cents=1800000,
        slot_start_utc="2026-12-04T21:00:00Z",
        radius_miles=150,
        exclusivity_scope="TICKETED_ONLY",
    )
    _issue(api, ticketed_only["id"])
    festival_only = _draft(
        api,
        ctx,
        vela["id"],
        "HEADLINER",
        guarantee_cents=1800000,
        slot_start_utc="2026-12-05T21:00:00Z",
        radius_miles=150,
        exclusivity_scope="FESTIVAL_ONLY",
    )
    _issue(api, festival_only["id"])
    vela_clause = fx.clause_of_offer(api, festival_only["id"])

    free_show = _report(
        api,
        nova["id"],
        performance_date="2026-11-10",
        is_ticketed=False,
        is_festival=False,
    )
    assert free_show["conflict_assessment"] == "NO_CONFLICT"

    ticketed_show = _report(
        api,
        nova["id"],
        performance_date="2026-11-11",
        is_ticketed=True,
        is_festival=False,
    )
    assert ticketed_show["conflict_assessment"] == "CONFLICT"
    assert ticketed_show["distance_to_market_miles"] == 145.41

    club_date = _report(
        api,
        vela["id"],
        performance_date="2026-11-12",
        is_ticketed=True,
        is_festival=False,
    )
    assert club_date["conflict_assessment"] == "NO_CONFLICT"

    festival_date = _report(
        api,
        vela["id"],
        performance_date="2026-11-13",
        is_ticketed=True,
        is_festival=True,
    )
    assert festival_date["conflict_assessment"] == "CONFLICT"
    assert festival_date["conflicting_radius_clause_id"] == vela_clause["id"]

    assert (
        validate_success(api.get_artist(nova["id"], BUSINESS_AFFAIRS))[
            "reported_conflict_count"
        ]
        == 1
    )
    assert (
        validate_success(api.get_artist(vela["id"], BUSINESS_AFFAIRS))[
            "reported_conflict_count"
        ]
        == 1
    )


def test_distance_is_rounded_to_two_decimals_before_the_inclusive_radius_compare(api):
    """145.004002 miles rounds inside a 145-mile clause while 145.007001 stays clear.

    "Mileage covers the venue when the great-circle distance from the clause's festival market to the venue, rounded half up to two decimal places, is at or below the clause's `radius_miles` — the comparison is inclusive, so a venue at exactly the clause mileage is inside."
    Design: Corner/calculations/distance_is_rounded_to_two_decimals_before_the_inclusive_compare
    """
    ctx = _edition(api)
    artist = fx.create_artist(api, default_radius_miles=100)
    offer = _draft(
        api,
        ctx,
        artist["id"],
        "HEADLINER",
        guarantee_cents=1800000,
        slot_start_utc="2026-12-04T21:00:00Z",
        radius_miles=145,
        window_start_date="2026-10-05",
        window_end_date="2027-01-04",
    )
    _issue(api, offer["id"])
    clause = fx.clause_of_offer(api, offer["id"])
    assert clause["radius_miles"] == 145
    assert clause["enforcement_status"] == "ACTIVE"

    market = (ctx["festival"]["market_latitude"], ctx["festival"]["market_longitude"])
    assert expected_distance_miles(market[0], market[1], 45.5075341, -122.3321) == 145.0
    assert (
        expected_distance_miles(market[0], market[1], 45.5074907, -122.3321) == 145.01
    )

    inside = _report(
        api,
        artist["id"],
        venue_city="Ridgefield",
        venue_latitude=45.5075341,
        venue_longitude=-122.3321,
        performance_date="2026-11-18",
    )
    assert inside["conflict_assessment"] == "CONFLICT"
    assert inside["distance_to_market_miles"] == 145.0
    assert inside["conflicting_radius_clause_id"] == clause["id"]

    outside = _report(
        api,
        artist["id"],
        venue_city="Ridgefield",
        venue_latitude=45.5074907,
        venue_longitude=-122.3321,
        performance_date="2026-11-19",
    )
    assert outside["conflict_assessment"] == "NO_CONFLICT"
    assert outside["distance_to_market_miles"] is None

    scored = validate_success(api.get_artist(artist["id"], BUSINESS_AFFAIRS))
    assert scored["reported_conflict_count"] == 1


# ---------------------------------------------------------- payment schedule
def test_deposit_band_and_due_date_clamp_follow_the_logical_clock(api):
    """Two identical guarantees accepted at two clock positions build two different schedules.

    "The deposit percentage is 0.50 when there are at least 120 days to go — exactly 120 days still earns 0.50 — 0.40 when there are at least 60 but fewer than 120, and 0.25 when there are fewer than 60."
    "The deposit's `amount_cents` is the booking's `guarantee_cents` multiplied by that percentage and rounded half up once; the balance's `amount_cents` is the guarantee less the deposit, taken as an exact integer complement and never independently rounded, so the pair always sums back to the guarantee."
    "The deposit's `due_date` is the later of today's date and the earlier of two candidates: today plus 30 days, and the edition's `event_start_date` less 14 days."
    "The balance's `due_date` is the calendar date of the booking's `slot_start_utc`."
    Design: Corner/calculations/deposit_band_and_due_date_clamp_selected_from_the_logical_clock
    """
    ctx = _edition(api)
    nova = fx.create_artist(api, default_radius_miles=100)
    vela = fx.create_artist(
        api,
        legal_name="Vela Roan Touring Ltd",
        performing_name="Vela Roan",
        primary_genre="ROCK",
        draw_score=72,
        default_radius_miles=100,
    )

    fx.set_clock(api, "2026-09-15T00:00:00Z")
    vela_offer = _draft(
        api,
        ctx,
        vela["id"],
        "HEADLINER",
        guarantee_cents=1800000,
        slot_start_utc="2026-12-05T21:00:00Z",
        offer_expires_utc="2026-10-01T00:00:00Z",
    )
    _issue(api, vela_offer["id"])
    vela_booking = _accept(api, vela_offer["id"], vela["id"])

    fx.set_clock(api, "2026-11-01T00:00:00Z")
    nova_offer = _draft(
        api,
        ctx,
        nova["id"],
        "HEADLINER",
        guarantee_cents=1800000,
        slot_start_utc="2026-12-04T21:00:00Z",
        offer_expires_utc="2026-12-01T00:00:00Z",
    )
    _issue(api, nova_offer["id"])
    nova_booking = _accept(api, nova_offer["id"], nova["id"])

    far_rows, far_meta = validate_paginated(
        api.list_payment_installments(vela_booking["id"], FINANCE_CONTROLLER)
    )
    assert far_meta["total_count"] == 2
    assert [row["due_date"] for row in far_rows] == sorted(
        row["due_date"] for row in far_rows
    )
    assert far_rows[0]["installment_type"] == "DEPOSIT"
    assert far_rows[0]["sequence_index"] == 1
    assert far_rows[0]["status"] == "SCHEDULED"
    assert far_rows[0]["amount_cents"] == 720000
    assert far_rows[0]["due_date"] == "2026-10-15"
    assert far_rows[1]["installment_type"] == "BALANCE"
    assert far_rows[1]["amount_cents"] == 1080000
    assert far_rows[1]["due_date"] == "2026-12-05"
    assert far_rows[0]["amount_cents"] + far_rows[1]["amount_cents"] == 1800000

    near_rows, near_meta = validate_paginated(
        api.list_payment_installments(nova_booking["id"], FINANCE_CONTROLLER)
    )
    assert near_meta["total_count"] == 2
    assert near_rows[0]["installment_type"] == "DEPOSIT"
    assert near_rows[0]["amount_cents"] == 450000
    assert near_rows[0]["due_date"] == "2026-11-20"
    assert near_rows[1]["installment_type"] == "BALANCE"
    assert near_rows[1]["amount_cents"] == 1350000
    assert near_rows[1]["due_date"] == "2026-12-04"
    assert near_rows[0]["amount_cents"] + near_rows[1]["amount_cents"] == 1800000


# -------------------------------------------------------- posture and ceiling
def test_lineup_posture_is_restricted_at_exactly_the_eighty_five_percent_ratio(api):
    """A committed ratio of exactly 0.85 reads RESTRICTED and still admits an issuance.

    "It reads `RESTRICTED` when the committed ratio has reached 0.85 but is still below 1.00 — so a ratio of exactly 0.85 is `RESTRICTED` and a ratio of exactly 1.00 is `FROZEN`."
    "`RESTRICTED` permits all three: it is an advisory posture whose only real effect is to narrow the guarantee ceiling through the shrinking festival headroom."
    Design: Corner/calculations/lineup_posture_is_restricted_at_exactly_the_085_ratio
    """
    ctx = _edition(
        api,
        talent_budget_cents=4000000,
        contingency_reserve_pct=0.0,
        tier_specs=(("HEADLINER", 1, 0.50), ("MID_CARD", 2, 0.50)),
    )
    assert ctx["festival"]["allocatable_budget_cents"] == 4000000
    assert ctx["tiers"]["HEADLINER"]["allocation_cents"] == 2000000

    electronic = fx.create_artist(api, draw_score=64, default_radius_miles=100)
    rock = fx.create_artist(
        api,
        legal_name="Vela Roan Touring Ltd",
        performing_name="Vela Roan",
        primary_genre="ROCK",
        draw_score=64,
        default_radius_miles=100,
    )
    pop = fx.create_artist(
        api,
        legal_name="Cassia Vale Touring Inc",
        performing_name="Cassia Vale",
        primary_genre="POP",
        draw_score=20,
        default_radius_miles=100,
    )
    jazz = fx.create_artist(
        api,
        legal_name="Quill Hart Music Ltd",
        performing_name="Quill Hart",
        primary_genre="JAZZ_SOUL",
        draw_score=100,
        default_radius_miles=100,
    )

    plan = (
        (electronic, "HEADLINER", 1600000, 1, 90, "2026-12-04T21:00:00Z"),
        (rock, "MID_CARD", 1600000, 2, 90, "2026-12-04T18:00:00Z"),
        (pop, "MID_CARD", 200000, 3, 60, "2026-12-04T15:00:00Z"),
    )
    for artist, tier_code, guarantee, position, minutes, slot in plan:
        offer = _draft(
            api,
            ctx,
            artist["id"],
            tier_code,
            guarantee_cents=guarantee,
            billing_position=position,
            set_length_minutes=minutes,
            slot_start_utc=slot,
        )
        _issue(api, offer["id"])
        _accept(api, offer["id"], artist["id"])

    summary = validate_success(
        api.get_budget_summary(ctx["festival"]["id"], FINANCE_CONTROLLER)
    )
    assert summary["allocatable_budget_cents"] == 4000000
    assert summary["committed_budget_cents"] == 3400000
    assert summary["tier_committed_sum_cents"] == 3400000
    assert summary["booking_committed_sum_cents"] == 3400000
    assert summary["committed_ratio"] == pytest.approx(0.85)
    assert summary["lineup_posture"] == "RESTRICTED"
    assert summary["open_tier_count"] == 2
    assert summary["closed_tier_count"] == 0
    assert summary["headliner_anchor_count"] == 1

    festival = validate_success(api.get_festival(ctx["festival"]["id"], TALENT_BUYER))
    assert festival["lineup_posture"] == "RESTRICTED"
    assert festival["announcement_phase"] == "PRESALE"

    fourth = _draft(
        api,
        ctx,
        jazz["id"],
        "MID_CARD",
        guarantee_cents=200000,
        billing_position=4,
        set_length_minutes=60,
        slot_start_utc="2026-12-04T12:00:00Z",
    )
    issued = _issue(api, fourth["id"])
    assert issued["status"] == "ISSUED"
    assert issued["guarantee_ceiling_cents"] == 200000
    assert issued["genre_balance_factor"] == pytest.approx(1.0)


def test_genre_balance_factor_steps_to_085_between_the_soft_and_hard_caps(api):
    """A committed share of 0.3158 stamps a 0.85 factor and floors the scaled draw once.

    "Computed **excluding** the offer under evaluation, the share picks the factor: `genre_balance_factor` is stamped at 1.00 when the share is at most 0.30, at 0.85 when the share is above 0.30 but at most 0.40, and at 0.60 when the share is above 0.40."
    "Step five scales that draw component by the genre balance factor and **floors** the product to whole cents; this is the only rounding step in the whole computation, applied once at the end rather than per input."
    "An offer whose `guarantee_cents` plus `production_fee_cents` exceeds that ceiling is refused with `ERR_GUARANTEE_CEILING_EXCEEDED`; equality with the ceiling passes."
    Design: Corner/calculations/genre_balance_factor_steps_to_085_between_the_soft_and_hard_caps
    """
    ctx = _edition(api)
    assert ctx["festival"]["allocatable_budget_cents"] == ALLOCATABLE_BUDGET_CENTS

    halcyon = fx.create_artist(
        api,
        legal_name="Halcyon Drift LLC",
        performing_name="Halcyon Drift",
        primary_genre="ELECTRONIC",
        draw_score=100,
        default_radius_miles=100,
    )
    static = fx.create_artist(
        api,
        legal_name="Static Bloom LLC",
        performing_name="Static Bloom",
        primary_genre="ELECTRONIC",
        draw_score=20,
        default_radius_miles=100,
    )
    ember = fx.create_artist(
        api,
        legal_name="Ember Kade LLC",
        performing_name="Ember Kade",
        primary_genre="ELECTRONIC",
        draw_score=37,
        default_radius_miles=100,
    )
    vela = fx.create_artist(
        api,
        legal_name="Vela Roan Touring Ltd",
        performing_name="Vela Roan",
        primary_genre="ROCK",
        draw_score=37,
        default_radius_miles=100,
    )

    first = _draft(
        api,
        ctx,
        halcyon["id"],
        "HEADLINER",
        guarantee_cents=2500000,
        billing_position=1,
        set_length_minutes=90,
        slot_start_utc="2026-12-04T21:00:00Z",
    )
    _issue(api, first["id"])
    second = _draft(
        api,
        ctx,
        static["id"],
        "MID_CARD",
        guarantee_cents=500000,
        billing_position=2,
        set_length_minutes=60,
        slot_start_utc="2026-12-04T18:00:00Z",
    )
    _issue(api, second["id"])

    # Two live ELECTRONIC offers put the excluding share at 3000000 / 9500000.
    overshoot = _draft(
        api,
        ctx,
        ember["id"],
        "EMERGING",
        guarantee_cents=786251,
        billing_position=6,
        set_length_minutes=60,
        slot_start_utc="2026-12-06T12:00:00Z",
    )
    validate_error(
        api.issue_offer(overshoot["id"], TALENT_BUYER),
        "ERR_GUARANTEE_CEILING_EXCEEDED",
        422,
    )

    scaled = _draft(
        api,
        ctx,
        ember["id"],
        "MID_CARD",
        guarantee_cents=786250,
        billing_position=3,
        set_length_minutes=60,
        slot_start_utc="2026-12-05T21:00:00Z",
    )
    scaled = _issue(api, scaled["id"])
    assert scaled["status"] == "ISSUED"
    assert scaled["genre_balance_factor"] == pytest.approx(GENRE_FACTOR_SOFT)
    assert scaled["guarantee_ceiling_cents"] == 786250
    assert scaled["guarantee_cents"] == 786250

    unscaled = _draft(
        api,
        ctx,
        vela["id"],
        "EMERGING",
        guarantee_cents=925000,
        billing_position=4,
        set_length_minutes=60,
        slot_start_utc="2026-12-06T21:00:00Z",
    )
    unscaled = _issue(api, unscaled["id"])
    assert unscaled["genre_balance_factor"] == pytest.approx(1.0)
    assert unscaled["guarantee_ceiling_cents"] == 925000
