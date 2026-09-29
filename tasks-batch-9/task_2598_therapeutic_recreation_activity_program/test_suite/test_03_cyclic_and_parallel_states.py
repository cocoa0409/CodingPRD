"""Non-linear lifecycles: the plan revision round trip and the outing's two dimensions."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_values


def _plan_under_revision(api, therapist):
    """A plan taken DRAFT to ACTIVE to UNDER_REVISION, with the resident gated."""
    resident, assessment = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "Iris Nakamura", "room_number": "112A",
                         "admission_date": "2026-04-11"},
        cognitive_level="MILD_IMPAIRMENT",
        functional_mobility="ASSIST_1",
        interest_domains=["SOCIAL", "CREATIVE"],
        effective_date="2026-07-20",
    )
    plan = fx.active_plan(
        api,
        resident["id"],
        assessment["id"],
        targets=f.domain_targets(social=2, creative=1),
    )
    validate_success(
        api.transition_activity_plan(
            plan["id"], {"action": "REVISE", "review_reason": "THERAPIST_REQUEST"}, therapist
        ),
        200,
    )
    return resident, plan


def test_activity_plan_revision_cycle_round_trip(api, therapist):
    """Reactivation returns the plan to a state it has already occupied, and the round
    trip leaves the revision counter permanently incremented with the reason cleared.

    PRD: "the plan's `status` returns to `ACTIVE`, `revision_count` increments by one,
    `review_reason` resets to `NONE`".

    Design: Difficulty/non_linear_state_machine/activity_plan_revision_cycle_round_trip
    """
    resident, plan = _plan_under_revision(api, therapist)

    reactivated = validate_success(
        api.transition_activity_plan(plan["id"], {"action": "REACTIVATE"}, therapist), 200
    )
    assert_values(reactivated, status="ACTIVE", revision_count=1, review_reason="NONE")

    stored = fx.read_plan(api, plan["id"])
    assert_values(stored, status="ACTIVE", revision_count=1, review_reason="NONE")
    assert stored["activated_at"] is not None, "Reactivation re-stamps activated_at"


def test_activity_plan_revision_cycle_round_trip_gate_released(api, therapist):
    """Every gate field the outbound leg raised on the resident is lowered again by the
    return leg, so the front line may book the resident once more.

    PRD: "The resident's gate is released — `care_plan_review_due` back to false and
    `enrollment_gate` back to `NONE`".

    Design: Difficulty/non_linear_state_machine/activity_plan_revision_cycle_round_trip
    """
    resident, plan = _plan_under_revision(api, therapist)

    gated = fx.read_resident(api, resident["id"])
    assert_values(gated, enrollment_gate="THERAPIST_REVIEW", care_plan_review_due=True)

    validate_success(
        api.transition_activity_plan(plan["id"], {"action": "REACTIVATE"}, therapist), 200
    )

    released = fx.read_resident(api, resident["id"])
    assert_values(released, enrollment_gate="NONE", care_plan_review_due=False)


def _booked_outing_with_outstanding_consent(api):
    """Transport booked while the single rider's consent is still merely requested."""
    resident, _ = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "Owen Petrov", "room_number": "104A",
                         "admission_date": "2026-05-19"},
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-20",
    )
    program = fx.create_program(
        api, name="Garden Center Trip", domain="SOCIAL", max_group_size=12
    )
    vehicle = fx.create_vehicle(
        api, label="Bus 1", ambulatory_seats=8, wheelchair_stations=2
    )
    outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Riverside Garden Center",
        departure_at="2026-08-12T09:00:00Z",
        return_at="2026-08-12T15:00:00Z",
        escort_count=1,
    )
    consent = fx.add_rider(
        api,
        outing["id"],
        resident["id"],
        responsible_party_name="Marta Petrov",
        responsible_party_relation="ADULT_CHILD",
    )
    fx.book_transport(api, outing["id"], vehicle_id=vehicle["id"])
    return outing, consent, vehicle


def test_outing_parallel_dimensions_evolve_independently(api, director):
    """Granting the outstanding consent advances only the consent dimension; the
    logistics dimension stays parked where the booking left it.

    PRD: "After every decision, and after every newly added `REQUESTED` row, the outing's
    `consent_status` is re-derived from the roster alone; no logistics action ever moves
    it."

    Design: Difficulty/non_linear_state_machine/outing_parallel_dimensions_evolve_independently
    """
    outing, consent, vehicle = _booked_outing_with_outstanding_consent(api)

    decided = validate_success(
        api.decide_outing_consent(
            outing["id"], consent["id"], {"decision": "GRANTED"}, director
        ),
        200,
    )
    assert_values(decided, status="GRANTED", effective=True)

    stored = fx.read_outing(api, outing["id"])
    assert_values(
        stored, consent_status="CONSENT_COMPLETE", logistics_status="TRANSPORT_BOOKED"
    )


def test_outing_parallel_dimensions_evolve_independently_seats_untouched(api, director):
    """The consent decision leaves the booked seat requirement and the vehicle's
    reservation exactly as the booking computed them: one rider plus one escort.

    PRD: "`ambulatory_seats_required` is the count of manifest riders whose
    `functional_mobility` is anything else, plus `escort_count`."

    Design: Difficulty/non_linear_state_machine/outing_parallel_dimensions_evolve_independently
    """
    outing, consent, vehicle = _booked_outing_with_outstanding_consent(api)

    validate_success(
        api.decide_outing_consent(
            outing["id"], consent["id"], {"decision": "GRANTED"}, director
        ),
        200,
    )

    stored = fx.read_outing(api, outing["id"])
    assert_values(stored, ambulatory_seats_required=2, wheelchair_seats_required=0)

    fleet = fx.read_vehicle(api, vehicle["id"])
    assert_values(fleet, reserved_ambulatory_seats=2, reserved_wheelchair_stations=0)
