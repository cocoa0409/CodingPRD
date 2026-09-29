"""Computed readings: tray-card ranking, seat roll-ups, refresh index, postures and scores."""
import pytest

from test_helpers import (
    add_verified_resident,
    approve_diet_order,
    cast_ballot,
    create_community,
    create_diet_order,
    create_reservation,
    create_resident,
    create_substitution_rule,
    create_venue,
    list_observations,
    list_rules,
    log_temperature,
    read_menu_cycle,
    read_resident,
    read_seat_availability,
    read_tray_card,
    read_venue,
    record_observation,
    release_reservation,
    reviews_for,
    set_clock,
    set_dining_status,
    setup_dining_program,
    setup_published_menu_cycle,
)


def test_the_allergen_rule_wins_the_line_despite_its_worse_priority_rank(api):
    """Trigger priority is the first ordering key, so the `ALLERGEN` rule ranked 5 and created last
    still beats the `TEXTURE` rule ranked 1; the losing rule stays `ACTIVE`.

    PRD: "The winning rule among the candidates is chosen by three ordered keys: trigger priority
    first, where `ALLERGEN` ranks 0, `TEXTURE` ranks 1 and `DISLIKE` ranks 2 and the lowest rank
    wins; then ascending `priority_rank`; then ascending `created_at`."

    Design: Corner/calculations/tray_card_allergen_rule_outranks_texture_rule_by_trigger_priority
    """
    set_clock("2026-08-05T08:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"],
        full_name="Karla Vinterberg",
        baseline_weight_kg=64.0,
        allergens=["PEANUT"],
    )
    order = create_diet_order(
        resident["id"], texture_level="MINCED_MOIST", liquid_consistency="THIN"
    )
    approve_diet_order(order["id"])
    texture_rule = create_substitution_rule(
        resident["id"], "TEXTURE", "MINCED_MOIST", "PUREED-ENTREE", priority_rank=1
    )
    allergen_rule = create_substitution_rule(
        resident["id"], "ALLERGEN", "PEANUT", "NUT-FREE-PUREE", priority_rank=5
    )
    setup_published_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
        items=[
            {
                "item_code": "PB-NOODLE",
                "name": "Peanut Noodle Bowl",
                "day_index": 3,
                "meal_period": "LUNCH",
                "base_texture": "REGULAR",
                "allergen_tags": ["PEANUT"],
            }
        ],
    )

    card = read_tray_card(resident["id"], "2026-08-12", "LUNCH")

    assert card["day_index"] == 3
    assert len(card["lines"]) == 1
    assert card["lines"][0]["served_item_code"] == "NUT-FREE-PUREE"
    assert card["lines"][0]["reason"] == "ALLERGEN_SUBSTITUTION"
    assert card["lines"][0]["substitution_rule_id"] == allergen_rule["id"]
    assert card["lines"][0]["substitution_rule_id"] != texture_rule["id"]
    assert card["blocked_item_codes"] == []
    assert card["tray_status"] == "CLEAR"

    texture_rows = list_rules(resident["id"], trigger_type="TEXTURE")
    assert texture_rows[0]["status"] == "ACTIVE"


def test_committed_seats_count_only_the_reserved_and_seated_rows(api):
    """A released row and a waitlisted row sit on the same venue, date and meal period yet
    contribute no seats and no entries to `blocking_reservation_ids`.

    PRD: "For one venue, one `service_date` and one `meal_period` it rolls up the sum of
    `party_size` over every reservation of that venue, date and meal period whose `status` is
    `RESERVED` or `SEATED`, and reports `venue_id`, `service_date`, `meal_period`, `seat_capacity`,
    `committed_seats`, `open_seats` — the venue's `seat_capacity` minus committed seats, floored at
    0 — and `blocking_reservation_ids`, the ids of the rows that were summed, in ascending
    `created_at` order."

    Design: Corner/calculations/venue_committed_seats_ignores_waitlisted_and_released_rows
    """
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Aldergate",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Aldergate Main Dining",
        seat_capacity=6,
        resident_name="Resident A",
        baseline_weight_kg=70.0,
    )
    venue_id = program["venue"]["id"]
    resident_b = add_verified_resident(
        program["community"], "Resident B", baseline_weight_kg=71.0
    )
    resident_c = add_verified_resident(
        program["community"], "Resident C", baseline_weight_kg=72.0
    )

    reserved = create_reservation(
        program["resident"]["id"],
        venue_id,
        "2026-08-11",
        "LUNCH",
        "2026-08-11T12:00:00Z",
        party_size=2,
    )
    released_row = create_reservation(
        resident_b["id"],
        venue_id,
        "2026-08-11",
        "LUNCH",
        "2026-08-11T12:00:00Z",
        party_size=1,
    )
    released = release_reservation(released_row["id"], reason="family took the resident out")
    waitlisted = create_reservation(
        resident_c["id"],
        venue_id,
        "2026-08-11",
        "LUNCH",
        "2026-08-11T12:00:00Z",
        party_size=5,
        allow_waitlist=True,
    )

    assert released["status"] == "RELEASED"
    assert waitlisted["status"] == "WAITLISTED"

    availability = read_seat_availability(venue_id, "2026-08-11", "LUNCH")

    assert availability["seat_capacity"] == 6
    assert availability["committed_seats"] == 2
    assert availability["open_seats"] == 4
    assert availability["blocking_reservation_ids"] == [reserved["id"]]


def test_the_second_ballot_reaches_exactly_forty_percent_and_flips_the_cycle(api):
    """One ballot of five residents is 20.00 percent participation — `ADVISORY`, index 12.00, below
    the 40.00 advisory threshold — and the second lands on exactly 40.00, which reaches quorum and
    lifts the index to 40.00, clearing the quorum threshold of 25.00.

    PRD: "The `refresh_tier` is `QUORUM` when participation is at least 40.00 percent — exactly
    40.00 does reach quorum — and `ADVISORY` otherwise."

    Design: Corner/calculations/menu_refresh_quorum_participation_exactly_forty_triggers_refresh_pending
    """
    community = create_community("Brookdale Elmsford", ["ASSISTED_LIVING"])
    voters = [
        create_resident(community["id"], full_name=name, baseline_weight_kg=weight)
        for name, weight in (
            ("Voter One", 70.0),
            ("Voter Two", 71.0),
            ("Silent Three", 72.0),
            ("Silent Four", 73.0),
            ("Silent Five", 74.0),
        )
    ]
    program = setup_published_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
        items=[
            {
                "item_code": "REG-COD",
                "name": "Baked Cod",
                "day_index": 1,
                "meal_period": "LUNCH",
                "base_texture": "REGULAR",
            }
        ],
    )
    cycle_id = program["cycle"]["id"]

    first = cast_ballot(cycle_id, voters[0]["id"], "REG-COD", "NEGATIVE")
    after_first = read_menu_cycle(cycle_id)

    assert first["vote_weight"] == 1
    assert first["status"] == "SUBMITTED"
    assert after_first["refresh_tier"] == "ADVISORY"
    assert float(after_first["refresh_index"]) == 12.00
    assert after_first["status"] == "PUBLISHED"

    second = cast_ballot(cycle_id, voters[1]["id"], "REG-COD", "NEGATIVE")
    after_second = read_menu_cycle(cycle_id)

    assert second["vote_weight"] == 1
    assert after_second["refresh_tier"] == "QUORUM"
    assert float(after_second["refresh_index"]) == 40.00
    assert after_second["status"] == "REFRESH_PENDING"


def test_the_boundary_reading_is_in_range_and_only_a_corrective_action_resets(api):
    """134.9 is still a violation, exactly 135.0 is in range but leaves the sticky counter at 2, and
    only the in-range reading carrying a corrective action drops it back to 0 and to `COMPLIANT`.

    PRD: "An in-range log **without** a corrective action code leaves the counter exactly where it
    was — it neither resets nor increments."

    Design: Corner/calculations/temperature_exactly_135_in_range_with_corrective_action_resets_counter
    """
    set_clock("2026-08-10T09:00:00Z")
    community = create_community("Brookdale Aldergate", ["MEMORY_CARE"])
    venue = create_venue(
        community["id"],
        name="Aldergate Satellite",
        venue_kind="SATELLITE",
        seat_capacity=4,
        care_levels_served=["MEMORY_CARE"],
    )

    first = log_temperature(venue["id"], "HOT_HOLDING", 120.0)
    second = log_temperature(venue["id"], "HOT_HOLDING", 134.9)
    assert first["in_range"] is False
    assert first["violation_sequence_index"] == 1
    assert second["in_range"] is False
    assert second["violation_sequence_index"] == 2

    on_watch = read_venue(venue["id"])
    assert on_watch["temp_compliance_posture"] == "WATCH"
    assert on_watch["consecutive_temp_violation_count"] == 2

    boundary = log_temperature(venue["id"], "HOT_HOLDING", 135.0)
    assert boundary["in_range"] is True
    assert boundary["violation_sequence_index"] == 2

    still_on_watch = read_venue(venue["id"])
    assert still_on_watch["temp_compliance_posture"] == "WATCH"
    assert still_on_watch["consecutive_temp_violation_count"] == 2

    corrective = log_temperature(
        venue["id"],
        "HOT_HOLDING",
        135.0,
        corrective_action_code="HOLDING_UNIT_RECALIBRATED",
    )
    assert corrective["in_range"] is True
    assert corrective["violation_sequence_index"] == 0

    recovered = read_venue(venue["id"])
    assert recovered["temp_compliance_posture"] == "COMPLIANT"
    assert recovered["consecutive_temp_violation_count"] == 0
    assert recovered["status"] == "OPEN"


def test_the_rolling_window_sorts_by_observation_date_not_by_insertion_order(api):
    """The older weight is written second, and the trend still anchors on it: one in-window weight
    reads 0.00, and adding the earlier 80.0 kg row makes the change -5.00 rather than 0.00.

    PRD: "Take the resident's observations that carry a weight and whose `observation_date` falls
    inside the closed window from 30 days before the clock date through the clock date, sorted by
    ascending `observation_date` and then ascending `created_at`; ids are never an ordering input."

    Design: Corner/calculations/weight_trend_out_of_order_observation_dates_still_chronological
    """
    set_clock("2026-08-20T08:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Lena Marchetti", baseline_weight_kg=78.0
    )

    record_observation(resident["id"], "2026-08-20", "LUNCH", 80, weight_kg=76.0)
    after_one = read_resident(resident["id"])
    assert after_one["rolling_30d_weight_change_pct"] == pytest.approx(0.00, abs=0.01)

    older = record_observation(resident["id"], "2026-08-05", "LUNCH", 90, weight_kg=80.0)

    final = read_resident(resident["id"])
    assert final["rolling_30d_weight_change_pct"] == pytest.approx(-5.00, abs=0.01)
    assert final["baseline_weight_change_pct"] == pytest.approx(-2.56, abs=0.01)
    assert final["avg_intake_pct_7d"] == pytest.approx(80.00, abs=0.01)
    assert final["intake_risk_score"] == pytest.approx(30.00, abs=0.01)

    reviews = reviews_for(resident["id"], status="OPEN")
    assert len(reviews) == 1
    assert reviews[0]["trigger_reason"] == "WEIGHT_LOSS_30D"
    assert reviews[0]["trigger_observation_id"] == older["id"]
    assert reviews[0]["risk_score_at_open"] == pytest.approx(30.00, abs=0.01)


def test_the_intake_mean_covers_seven_days_and_excludes_the_eighth(api):
    """With the clock on 2026-08-20 the 2026-08-13 observation sits one day outside the window: the
    mean is null while it is the only row, then 70.00 rather than the 60.00 all three would give.

    PRD: "The seven-day intake average, `avg_intake_pct_7d`, is the mean of `intake_pct` over the
    resident's observations whose `observation_date` falls inside the closed window from 6 days
    before the clock date through the clock date — a seven-day window counting today — rounded half
    up to 2 decimal places, and null when that window holds no observation at all."

    Design: Corner/calculations/avg_intake_7d_window_excludes_observations_older_than_six_days
    """
    set_clock("2026-08-20T08:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Mira Halvorsen", baseline_weight_kg=70.0
    )

    record_observation(resident["id"], "2026-08-13", "LUNCH", 40)
    assert read_resident(resident["id"])["avg_intake_pct_7d"] is None

    record_observation(resident["id"], "2026-08-14", "LUNCH", 60)
    record_observation(resident["id"], "2026-08-20", "LUNCH", 80)

    final = read_resident(resident["id"])
    assert final["avg_intake_pct_7d"] == pytest.approx(70.00, abs=0.01)
    assert final["rolling_30d_weight_change_pct"] == pytest.approx(0.00, abs=0.01)
    assert final["baseline_weight_change_pct"] == pytest.approx(0.00, abs=0.01)
    assert final["tray_card_state"] == "CLEAR"

    assert len(list_observations(resident["id"])) == 3
    assert reviews_for(resident["id"]) == []


def test_the_on_leave_multiplier_halves_the_summed_score_once(api):
    """The five components sum to 75.00 while the resident is `ACTIVE`; `ON_LEAVE` halves that sum
    to 37.50 without changing any component input, and returning to `ACTIVE` restores 75.00.

    PRD: "Sum the five contributions, then multiply by a severity multiplier of 0.50 when the
    resident's `dining_status` is `ON_LEAVE` and 1.00 otherwise, then clamp the product to be no less
    than 0.00 and no more than 100.00, and round half up to 2 decimal places."

    Design: Corner/calculations/intake_risk_score_on_leave_multiplier_halves_score
    """
    program = setup_dining_program(
        clock="2026-08-02T08:00:00Z",
        community_name="Brookdale Aldergate",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Aldergate Main Dining",
        seat_capacity=6,
        resident_name="Nadia Broussard",
        baseline_weight_kg=80.0,
        texture_level="MINCED_MOIST",
        liquid_consistency="SLIGHTLY_THICK",
        therapeutic_codes=["LOW_SODIUM"],
    )
    resident_id = program["resident"]["id"]
    record_observation(resident_id, "2026-08-02", "LUNCH", 40, weight_kg=80.0)
    set_clock("2026-08-20T08:00:00Z")
    record_observation(resident_id, "2026-08-20", "LUNCH", 40, weight_kg=76.0)

    active = read_resident(resident_id)
    assert active["dining_status"] == "ACTIVE"
    assert active["rolling_30d_weight_change_pct"] == pytest.approx(-5.00, abs=0.01)
    assert active["avg_intake_pct_7d"] == pytest.approx(40.00, abs=0.01)
    assert active["intake_risk_score"] == pytest.approx(75.00, abs=0.01)

    on_leave = set_dining_status(resident_id, "ON_LEAVE")

    assert on_leave["dining_status"] == "ON_LEAVE"
    assert on_leave["intake_risk_score"] == pytest.approx(37.50, abs=0.01)
    assert on_leave["rolling_30d_weight_change_pct"] == pytest.approx(-5.00, abs=0.01)
    assert on_leave["avg_intake_pct_7d"] == pytest.approx(40.00, abs=0.01)

    back = set_dining_status(resident_id, "ACTIVE")
    assert back["dining_status"] == "ACTIVE"
    assert back["intake_risk_score"] == pytest.approx(75.00, abs=0.01)
