"""Reversals must put the conserved quantity back exactly, with no drift."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_values


def _booked_outing_holding_two_seats(api):
    """A TRANSPORT_BOOKED outing holding two forward seats: one rider plus one escort."""
    resident, _ = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "Lucien Marchetti", "room_number": "150A",
                         "admission_date": "2026-03-09"},
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-20",
    )
    program = fx.create_program(
        api, name="Lakeside Picnic", domain="SOCIAL", max_group_size=12
    )
    vehicle = fx.create_vehicle(
        api, label="Van 3", ambulatory_seats=8, wheelchair_stations=2,
        turnaround_minutes=30,
    )
    outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Lakeside Park",
        departure_at="2026-08-16T09:00:00Z",
        return_at="2026-08-16T13:00:00Z",
        escort_count=1,
    )
    consent = fx.add_rider(
        api,
        outing["id"],
        resident["id"],
        responsible_party_name="Gia Marchetti",
        responsible_party_relation="ADULT_CHILD",
    )
    fx.book_transport(api, outing["id"], vehicle_id=vehicle["id"])
    return resident, program, vehicle, outing, consent


def test_outing_cancel_restores_vehicle_seat_conservation(api, director):
    """Cancelling from TRANSPORT_BOOKED hands both reserved seats back to the fleet and
    stores the reason, leaving the counters exactly where booking found them.

    PRD: "`CANCEL` is admitted from `PLANNING`, `TRANSPORT_BOOKED`, or `READY`, requires a
    `cancel_reason` which it stores, and from the latter two states also releases the
    reservation counters and advances the vehicle's `version` by 1."

    Design: Difficulty/compensating_invariant/outing_cancel_restores_vehicle_seat_conservation
    """
    _, _, vehicle, outing, _ = _booked_outing_holding_two_seats(api)

    assert_values(fx.read_outing(api, outing["id"]), logistics_status="TRANSPORT_BOOKED",
                  ambulatory_seats_required=2, wheelchair_seats_required=0)
    assert_values(fx.read_vehicle(api, vehicle["id"]), reserved_ambulatory_seats=2,
                  reserved_wheelchair_stations=0)

    cancelled = validate_success(
        api.outing_logistics(
            outing["id"], {"action": "CANCEL", "cancel_reason": "Storm warning"}, director
        ),
        200,
    )
    assert_values(cancelled, logistics_status="CANCELLED", cancel_reason="Storm warning")

    assert_values(fx.read_vehicle(api, vehicle["id"]), reserved_ambulatory_seats=0,
                  reserved_wheelchair_stations=0)


def test_outing_cancel_restores_vehicle_seat_conservation_seats_rebookable(api, director):
    """With the reserving set empty again a second trip books the very same two seats and
    the counter reads 2, not 4, so nothing was left stranded; the cancelled trip's consent
    row is untouched by the logistics dimension.

    PRD: "each holds the sum of `ambulatory_seats_required` and
    `wheelchair_seats_required` respectively over the outings on that vehicle whose
    `logistics_status` is `TRANSPORT_BOOKED`, `READY`, or `DEPARTED`."

    Design: Difficulty/compensating_invariant/outing_cancel_restores_vehicle_seat_conservation
    """
    resident, program, vehicle, outing, consent = _booked_outing_holding_two_seats(api)

    fx.logistics(api, outing["id"], "CANCEL", cancel_reason="Storm warning")

    replacement = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Lakeside Park Again",
        departure_at="2026-08-16T09:00:00Z",
        return_at="2026-08-16T13:00:00Z",
        escort_count=1,
    )
    fx.add_rider(
        api,
        replacement["id"],
        resident["id"],
        responsible_party_name="Gia Marchetti",
        responsible_party_relation="ADULT_CHILD",
    )
    fx.book_transport(api, replacement["id"], vehicle_id=vehicle["id"])

    assert_values(fx.read_vehicle(api, vehicle["id"]), reserved_ambulatory_seats=2,
                  reserved_wheelchair_stations=0)
    assert_values(fx.read_consent(api, consent["id"]), status="REQUESTED")


def _replacement_plan_ready_to_activate(api):
    """A resident gated by a plan in revision, plus a DRAFT replacement on a newer
    assessment that is ready to go live."""
    resident, first_assessment = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "Verna Duplessis", "room_number": "160A",
                         "admission_date": "2026-01-20"},
        cognitive_level="MILD_IMPAIRMENT",
        functional_mobility="ASSIST_1",
        interest_domains=["SOCIAL", "SPIRITUAL"],
        effective_date="2026-07-20",
    )
    first_plan = fx.active_plan(
        api,
        resident["id"],
        first_assessment["id"],
        targets=f.domain_targets(social=2, spiritual=1),
    )
    fx.get_success_data(
        api.transition_activity_plan(
            first_plan["id"],
            {"action": "REVISE", "review_reason": "THERAPIST_REQUEST"},
            fx.THERAPIST_HEADERS,
        )
    )
    second_assessment = fx.file_assessment(
        api,
        resident["id"],
        cognitive_level="MODERATE_IMPAIRMENT",
        functional_mobility="ASSIST_2",
        interest_domains=["SPIRITUAL"],
        preferred_group_size="SOLO",
        effective_date="2026-08-02",
    )
    second_plan = fx.draft_plan(
        api,
        resident["id"],
        second_assessment["id"],
        targets=f.domain_targets(spiritual=3),
    )
    return resident, first_assessment, first_plan, second_assessment, second_plan


def test_plan_supersede_restores_resident_gate_conservation(api, therapist):
    """Activating the replacement supersedes the predecessor that was under revision, and
    the superseded plan never counts a revision because it was never reactivated.

    PRD: "Activation is also the moment of supersession: **every other** plan for the same
    resident whose `status` is `ACTIVE` or `UNDER_REVISION` transitions to `SUPERSEDED`"

    Design: Difficulty/compensating_invariant/plan_supersede_restores_resident_gate_conservation
    """
    _, _, first_plan, _, second_plan = _replacement_plan_ready_to_activate(api)
    assert_values(fx.read_plan(api, first_plan["id"]), status="UNDER_REVISION")

    activated = validate_success(
        api.transition_activity_plan(second_plan["id"], {"action": "ACTIVATE"}, therapist),
        200,
    )
    assert_values(activated, status="ACTIVE")

    assert_values(fx.read_plan(api, first_plan["id"]), status="SUPERSEDED",
                  revision_count=0)


def test_plan_supersede_restores_resident_gate_conservation_gate_released(api, therapist):
    """The supersession compensates the gate the revision raised, so the resident is left
    ungated with exactly one live plan, and the older assessment carries the superseded
    label while the newer one does not.

    PRD: "each plan that is displaced clears the resident's gate fields, setting
    `care_plan_review_due` to false and `enrollment_gate` to `NONE`."

    Design: Difficulty/compensating_invariant/plan_supersede_restores_resident_gate_conservation
    """
    resident, first_assessment, _, second_assessment, second_plan = (
        _replacement_plan_ready_to_activate(api)
    )

    before = fx.read_resident(api, resident["id"])
    assert_values(before, care_plan_review_due=True, enrollment_gate="THERAPIST_REVIEW")

    validate_success(
        api.transition_activity_plan(second_plan["id"], {"action": "ACTIVATE"}, therapist),
        200,
    )

    after = fx.read_resident(api, resident["id"])
    assert_values(after, care_plan_review_due=False, enrollment_gate="NONE")

    assert_values(
        validate_success(api.get_assessment(first_assessment["id"], therapist), 200),
        superseded=True,
    )
    assert_values(
        validate_success(api.get_assessment(second_assessment["id"], therapist), 200),
        superseded=False,
    )
