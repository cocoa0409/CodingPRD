"""Embargo determination, candidate ordering and the posture ladder.

Determination picks at most one governing rule from an ordered candidate set, and
posture derivation is a first-match-wins ladder in which the embargo branch sits
above both the closed-by-operation branch and the load branch.
"""

from test_helpers import (
    ApiErrorId,
    assert_animal_state,
    assert_flight_leg_state,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_superseded_embargo_rule_is_excluded_from_the_candidate_set(
    api, workbench, catalog, primary_leg
):
    """A superseded rule that would otherwise trip is never a candidate, and
    reactivating it brings it straight back into determination.

    PRD §3.3: "Rules whose `status` is `SUPERSEDED` are never candidates. If no rule
    is a candidate, `governing_embargo_rule_id` is set to null."

    Design: Corner/calculations/superseded_embargo_rule_is_excluded_from_the_candidate_set
    """
    superseded = workbench.create_embargo_rule(
        catalog["hkg_id"], forecast_high_limit_c=29.5, forecast_low_limit_c=-5.0
    )
    workbench.set_embargo_rule_status(superseded["id"], "SUPERSEDED")
    workbench.create_embargo_rule(
        catalog["hkg_id"], forecast_high_limit_c=35.0, forecast_low_limit_c=-20.0
    )

    leg = primary_leg(forecast_high_c=30.0, forecast_low_c=20.0)
    assert_flight_leg_state(
        leg, status="SCHEDULED", posture="OPEN", governing_embargo_rule_id=None
    )

    workbench.set_embargo_rule_status(superseded["id"], "ACTIVE")
    reactivated = workbench.update_forecast(leg["id"], 30.0, 20.0)
    assert_flight_leg_state(
        reactivated,
        posture="EMBARGOED",
        governing_embargo_rule_id=superseded["id"],
    )


def test_governing_embargo_rule_tie_breaks_on_created_at_not_id(
    api, workbench, catalog, primary_leg
):
    """Two rules share a high limit and both trip, so the earlier-created rule
    governs regardless of which identifier sorts first.

    PRD §3.3: "Otherwise the candidates are ordered by `forecast_high_limit_c`
    ascending and, among rules sharing the same high limit, by `created_at`
    ascending — never by `id` — and the first rule in that order becomes the leg's
    `governing_embargo_rule_id`."

    Design: Corner/calculations/governing_embargo_rule_tie_breaks_on_created_at_not_id
    """
    earlier = workbench.create_embargo_rule(
        catalog["hkg_id"],
        season_start_month_day="06-01",
        season_end_month_day="09-30",
        forecast_high_limit_c=29.5,
        forecast_low_limit_c=-5.0,
    )
    later = workbench.create_embargo_rule(
        catalog["hkg_id"],
        season_start_month_day="07-01",
        season_end_month_day="10-31",
        forecast_high_limit_c=29.5,
        forecast_low_limit_c=-8.0,
    )
    assert earlier["id"] != later["id"]

    leg = primary_leg(forecast_high_c=31.0, forecast_low_c=22.0)
    assert_flight_leg_state(
        leg, posture="EMBARGOED", governing_embargo_rule_id=earlier["id"]
    )


def test_leg_posture_becomes_restricted_when_booked_load_reaches_ninety_percent(
    api, workbench, catalog, primary_leg
):
    """One of two checked positions leaves the leg open; the second reaches nine
    tenths of the ceiling under the integer cross-multiplication.

    PRD §3.3: "Otherwise, if for any one of the three routings the leg's limit for
    that routing is greater than 0 and the booked count for that routing, multiplied
    by ten, is greater than or equal to that limit multiplied by nine, the posture is
    `RESTRICTED`."

    Design: Corner/calculations/leg_posture_becomes_restricted_when_booked_load_reaches_ninety_percent
    """
    leg = primary_leg(checked_animal_limit=2)
    reservation = workbench.create_reservation()
    first_animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    second_animal = workbench.create_animal(
        reservation["id"],
        catalog["species_id"],
        catalog["container_id"],
        animal_name="Taro",
        breed_name="Beagle",
        declared_weight_kg=12,
        height_at_shoulder_cm=30,
        length_nose_to_tail_cm=45,
        age_weeks=40,
    )

    workbench.create_segment(first_animal["id"], leg["id"])
    assert_flight_leg_state(
        workbench.read_leg(leg["id"]),
        posture="OPEN",
        booked_checked_count=1,
        governing_embargo_rule_id=None,
    )

    workbench.create_segment(second_animal["id"], leg["id"])
    assert_flight_leg_state(
        workbench.read_leg(leg["id"]),
        posture="RESTRICTED",
        booked_checked_count=2,
        governing_embargo_rule_id=None,
    )


def test_embargo_fires_at_forecast_exactly_equal_to_high_limit(
    api, workbench, catalog, primary_leg
):
    """One tenth of a degree below the high limit leaves the leg open; exactly at the
    limit the rule trips and governs.

    PRD §3.3: "and whose temperature test trips: the leg's `forecast_high_c` is
    greater than or equal to the rule's `forecast_high_limit_c`, or the leg's
    `forecast_low_c` is less than or equal to the rule's `forecast_low_limit_c`. A
    forecast exactly equal to either limit trips the rule."

    Design: Difficulty/boundary_precision_check/embargo_fires_at_forecast_exactly_equal_to_high_limit
    """
    rule = workbench.create_embargo_rule(
        catalog["hkg_id"], forecast_high_limit_c=29.5, forecast_low_limit_c=-5.0
    )

    leg = primary_leg(forecast_high_c=29.4, forecast_low_c=20.0)
    assert_flight_leg_state(
        leg, posture="OPEN", governing_embargo_rule_id=None
    )
    assert leg["version"] == 1

    at_limit = workbench.update_forecast(leg["id"], 29.5, 20.0)
    assert_flight_leg_state(
        at_limit,
        status="SCHEDULED",
        posture="EMBARGOED",
        governing_embargo_rule_id=rule["id"],
    )
    assert at_limit["version"] == 2
    assert at_limit["forecast_high_c"] == 29.5


def test_embargo_fires_at_forecast_exactly_equal_to_low_limit(
    api, workbench, catalog, primary_leg
):
    """The same equality holds at the other end of the temperature test: a tenth of a
    degree above the low limit is safe, the limit itself is not.

    PRD §3.3: "A forecast exactly equal to either limit trips the rule."

    Design: Difficulty/boundary_precision_check/embargo_fires_at_forecast_exactly_equal_to_high_limit
    """
    rule = workbench.create_embargo_rule(
        catalog["hkg_id"], forecast_high_limit_c=29.5, forecast_low_limit_c=-5.0
    )

    leg = primary_leg(forecast_high_c=25.0, forecast_low_c=-4.9)
    assert_flight_leg_state(leg, posture="OPEN", governing_embargo_rule_id=None)

    at_limit = workbench.update_forecast(leg["id"], 25.0, -5.0)
    assert_flight_leg_state(
        at_limit, posture="EMBARGOED", governing_embargo_rule_id=rule["id"]
    )
    assert at_limit["forecast_low_c"] == -5.0


def test_segment_create_blocked_by_embargoed_parent_leg_rejected(
    api, workbench, catalog, primary_leg, program_admin_headers
):
    """A slot cannot be opened on a leg the temperature embargo suppresses, and the
    refusal leaves the animal's own state untouched.

    PRD §3.5: "The leg must not be embargoed for this routing: when the leg's
    `posture` is `EMBARGOED` and the governing rule's `applies_to_routings` contains
    the requested `routing_type`, the create is refused with `ERR_LEG_EMBARGOED`".

    Design: Difficulty/cross_entity_state_dependency/segment_create_blocked_by_embargoed_parent_leg_rejected
    """
    rule = workbench.create_embargo_rule(
        catalog["hkg_id"],
        forecast_high_limit_c=29.5,
        forecast_low_limit_c=-5.0,
        applies_to_routings=["CHECKED", "CARGO"],
    )
    leg = primary_leg(forecast_high_c=30.0, forecast_low_c=20.0)
    assert_flight_leg_state(
        leg, posture="EMBARGOED", governing_embargo_rule_id=rule["id"]
    )

    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    workbench.screen_animal(animal["id"])

    refused = api.create_segment_assignment(
        {
            "animal_record_id": animal["id"],
            "flight_leg_id": leg["id"],
            "routing_type": "CHECKED",
            "sequence_index": 1,
            "expected_flight_leg_version": leg["version"],
        },
        workbench.agent(),
    )
    validate_error(refused, ApiErrorId.LEG_EMBARGOED, 422)

    assert_animal_state(
        workbench.read_animal(animal["id"]),
        status="SCREENED",
        container_compliance_state="COMPLIANT",
    )
    assert_flight_leg_state(
        workbench.read_leg(leg["id"]), posture="EMBARGOED", booked_checked_count=0
    )
    _, meta = validate_paginated(
        api.list_segment_assignments(program_admin_headers, {"flight_leg_id": leg["id"]})
    )
    assert meta["total_count"] == 0


def test_embargoed_leg_still_accepts_a_routing_the_rule_does_not_suppress(
    api, workbench, catalog, primary_leg, program_admin_headers
):
    """The embargo is read through the governing rule's routing list, so the same
    embargoed leg refuses the suppressed routing and accepts the other one.

    PRD §3.5: "an embargoed leg whose governing rule suppresses only cargo still
    accepts a cabin slot."

    Design: Difficulty/cross_entity_state_dependency/segment_create_blocked_by_embargoed_parent_leg_rejected
    """
    workbench.create_embargo_rule(
        catalog["hkg_id"],
        forecast_high_limit_c=29.5,
        forecast_low_limit_c=-5.0,
        applies_to_routings=["CARGO"],
    )
    leg = primary_leg(forecast_high_c=30.0, forecast_low_c=20.0)
    assert_flight_leg_state(leg, posture="EMBARGOED")

    cargo_reservation = workbench.create_reservation(routing_type="CARGO")
    cargo_animal = workbench.create_animal(
        cargo_reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    refused = api.create_segment_assignment(
        {
            "animal_record_id": cargo_animal["id"],
            "flight_leg_id": leg["id"],
            "routing_type": "CARGO",
            "sequence_index": 1,
            "expected_flight_leg_version": leg["version"],
        },
        workbench.agent(),
    )
    validate_error(refused, ApiErrorId.LEG_EMBARGOED, 422)

    cabin_reservation = workbench.create_reservation(
        passenger_name="Ng", contact_email="ng@example.com", routing_type="CABIN"
    )
    cabin_animal = workbench.create_animal(
        cabin_reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    accepted = validate_success(
        api.create_segment_assignment(
            {
                "animal_record_id": cabin_animal["id"],
                "flight_leg_id": leg["id"],
                "routing_type": "CABIN",
                "sequence_index": 1,
                "expected_flight_leg_version": workbench.leg_version(leg["id"]),
            },
            workbench.agent(),
        ),
        201,
    )
    assert accepted["status"] == "RESERVED"

    after = workbench.read_leg(leg["id"])
    assert_flight_leg_state(
        after, posture="EMBARGOED", booked_cabin_count=1, booked_cargo_count=0
    )
    rows, meta = validate_paginated(
        api.list_segment_assignments(program_admin_headers, {"flight_leg_id": leg["id"]})
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [accepted["id"]]
