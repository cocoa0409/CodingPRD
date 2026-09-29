"""Incident severity variants, the disclosure clock and the investigation join.

The severity score has a preliminary and an adjudicated variant over the same raw
score, and the disclosure obligation decides which of the two close-out branches an
incident may take.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER_ID,
    SECOND_COMPLIANCE_OFFICER_ID,
    assert_incident_state,
    assert_segment_state,
    validate_error,
    validate_success,
)


def _cargo_itinerary_with_long_connection(workbench, catalog, primary_leg):
    """A CARGO booking whose two legs leave a twelve-hour connection, so the second
    slot demands four welfare checks and the itinerary is international."""
    first_leg = primary_leg()
    second_leg = workbench.create_leg(
        catalog["lax_id"],
        catalog["jfk_id"],
        flight_number="AN205",
        scheduled_departure_utc="2026-09-11T03:00:00Z",
        scheduled_arrival_utc="2026-09-11T08:00:00Z",
    )
    reservation = workbench.create_reservation(
        passenger_name="Chan", contact_email="chan@example.com", routing_type="CARGO"
    )
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    first_slot = workbench.create_segment(
        animal["id"], first_leg["id"], routing_type="CARGO", sequence_index=1
    )
    second_slot = workbench.create_segment(
        animal["id"], second_leg["id"], routing_type="CARGO", sequence_index=2
    )
    return {
        "reservation_id": reservation["id"],
        "animal_id": animal["id"],
        "first_slot_id": first_slot["id"],
        "second_slot_id": second_slot["id"],
    }


def test_loss_incident_without_segment_zeroes_transit_and_welfare_components(
    api, workbench, catalog
):
    """With no slot cited neither the in-transit adder nor the welfare gap applies, so
    the preliminary score is the bare base weight for a loss.

    PRD §3.9: "An in-transit adder of 10 applies when a `segment_assignment_id` was
    supplied, and is zero otherwise. A welfare-gap term also applies only when a
    `segment_assignment_id` was supplied".

    Design: Corner/calculations/loss_incident_without_segment_zeroes_transit_and_welfare_components
    """
    workbench.set_clock("2026-08-02T00:00:00Z")
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    workbench.screen_animal(animal["id"])

    incident = workbench.report_incident(
        animal["id"],
        incident_type="LOSS",
        discovered_at_utc="2026-08-02T00:00:00Z",
    )
    assert incident["segment_assignment_id"] is None
    assert_incident_state(
        incident,
        status="REPORTED",
        preliminary_severity_score=70,
        adjudicated_severity_score=None,
        disclosure_required=True,
        disclosure_deadline_utc="2026-08-04T00:00:00Z",
        disclosure_on_time=None,
    )

    assert workbench.read_animal(animal["id"])["status"] == "DENIED"
    assert workbench.read_reservation(reservation["id"])["booking_status"] == "PENDING"


def test_incident_citing_another_animals_segment_rejected(
    api, workbench, booking_with_reserved_segment
):
    """The cited slot has to belong to the cited animal, so a sibling animal's slot is
    refused outright.

    PRD §3.9: "When a `segment_assignment_id` is supplied it must belong to the supplied
    `animal_record_id`, and a mismatch is refused with `ERR_SEGMENT_ANIMAL_MISMATCH`."

    Design: Corner/validations/incident_citing_another_animals_segment_rejected
    """
    state = booking_with_reserved_segment()
    other_animal = workbench.create_animal(
        state["reservation_id"],
        state["catalog"]["species_id"],
        state["catalog"]["container_id"],
        animal_name="Taro",
        breed_name="Beagle",
        declared_weight_kg=12,
        height_at_shoulder_cm=30,
        length_nose_to_tail_cm=45,
        age_weeks=40,
    )

    refused = api.create_animal_incident(
        {
            "animal_record_id": other_animal["id"],
            "segment_assignment_id": state["segment_id"],
            "incident_type": "INJURY",
            "discovered_at_utc": "2026-08-01T12:00:00Z",
        },
        workbench.acceptance(),
    )
    validate_error(refused, ApiErrorId.SEGMENT_ANIMAL_MISMATCH, 422)

    assert workbench.read_animal(other_animal["id"])["status"] == "DRAFT"
    assert_segment_state(workbench.read_segment(state["segment_id"]), status="RESERVED")


def test_disclose_on_incident_not_requiring_disclosure_rejected(
    api, workbench, investigated_incident
):
    """An injury scoring below sixty carries no disclosure obligation, so filing a
    disclosure for it is refused and the incident closes directly instead.

    PRD §3.9: "Filing a disclosure for an incident whose `disclosure_required` is false
    is refused with `ERR_DISCLOSURE_NOT_REQUIRED`."

    Design: Corner/endpoints/disclose_on_incident_not_requiring_disclosure_rejected
    """
    state = investigated_incident(
        incident_overrides={"discovered_at_utc": "2026-08-01T06:00:00Z"}
    )
    assert_incident_state(
        state["incident"],
        status="INVESTIGATING",
        preliminary_severity_score=40,
        disclosure_required=False,
        disclosure_deadline_utc=None,
    )

    refused = api.disclose_animal_incident(
        state["incident_id"],
        workbench.officer(COMPLIANCE_OFFICER_ID),
        {"regulator_reference": "CAD-2026-0001"},
    )
    validate_error(refused, ApiErrorId.DISCLOSURE_NOT_REQUIRED, 422)

    unchanged = workbench.read_incident(state["incident_id"])
    assert_incident_state(
        unchanged,
        status="INVESTIGATING",
        disclosure_required=False,
        disclosure_deadline_utc=None,
        disclosure_on_time=None,
    )
    assert unchanged["disclosed_at_utc"] is None

    closed = validate_success(
        api.close_animal_incident(
            state["incident_id"],
            {"veterinary_finding": "CARRIER_ATTRIBUTABLE"},
            workbench.officer(SECOND_COMPLIANCE_OFFICER_ID),
        )
    )
    assert_incident_state(closed, status="CLOSED", adjudicated_severity_score=40)


def test_international_itinerary_halves_the_disclosure_deadline_hours(
    api, workbench, catalog, primary_leg
):
    """A cross-border itinerary halves the injury window, and the welfare gap on the
    cited slot lifts the preliminary score over the mandatory-disclosure threshold.

    PRD §3.9: "That window is **halved** when the animal's itinerary is international,
    meaning at least one of its slots whose `status` is not `RELEASED` sits on a leg
    whose origin station's `country_code` differs from its destination station's
    `country_code`."

    Design: Corner/cross_cutting_complexity_layers/international_itinerary_halves_the_disclosure_deadline_hours
    """
    workbench.set_clock("2026-08-02T00:00:00Z")
    itinerary = _cargo_itinerary_with_long_connection(workbench, catalog, primary_leg)
    assert_segment_state(
        workbench.read_segment(itinerary["second_slot_id"]),
        connection_minutes=720,
        required_welfare_check_count=4,
        completed_welfare_check_count=0,
    )

    incident = workbench.report_incident(
        itinerary["animal_id"],
        incident_type="INJURY",
        segment_assignment_id=itinerary["second_slot_id"],
        discovered_at_utc="2026-08-02T00:00:00Z",
    )
    assert_incident_state(
        incident,
        status="REPORTED",
        preliminary_severity_score=62,
        disclosure_required=True,
        disclosure_deadline_utc="2026-08-05T12:00:00Z",
        disclosure_on_time=None,
    )


def test_incident_severity_preliminary_vs_adjudicated_diverges(
    api, workbench, catalog, primary_leg
):
    """The two variants read the same raw score: the preliminary one caps it as is, the
    adjudicated one scales it by the attribution factor and rounds half up.

    PRD §3.9: "That variant takes the same raw score as before, multiplies it by the
    attribution factor for the supplied `veterinary_finding` — one for
    `CARRIER_ATTRIBUTABLE`, nine tenths for `INDETERMINATE`, eight tenths for
    `PRE_EXISTING_CONDITION` — and rounds that product half up to a whole integer."

    Design: Difficulty/dual_variant_calc/incident_severity_preliminary_vs_adjudicated_diverges
    """
    workbench.set_clock("2026-08-02T00:00:00Z")
    itinerary = _cargo_itinerary_with_long_connection(workbench, catalog, primary_leg)

    incident = workbench.report_incident(
        itinerary["animal_id"],
        incident_type="INJURY",
        segment_assignment_id=itinerary["second_slot_id"],
        discovered_at_utc="2026-08-02T00:00:00Z",
    )
    assert_incident_state(
        incident, preliminary_severity_score=62, adjudicated_severity_score=None
    )

    workbench.investigate_incident(incident["id"], as_user_id=COMPLIANCE_OFFICER_ID)
    disclosed = workbench.disclose_incident(
        incident["id"],
        as_user_id=COMPLIANCE_OFFICER_ID,
        regulator_reference="CAD-2026-0001",
    )
    assert_incident_state(
        disclosed,
        status="REGULATOR_DISCLOSED",
        disclosure_required=True,
        disclosure_on_time=True,
    )
    assert disclosed["disclosed_at_utc"] == "2026-08-02T00:00:00Z"

    closed = workbench.close_incident(
        incident["id"], "INDETERMINATE", as_user_id=SECOND_COMPLIANCE_OFFICER_ID
    )
    assert_incident_state(
        closed,
        status="CLOSED",
        preliminary_severity_score=62,
        adjudicated_severity_score=56,
        disclosure_on_time=True,
    )
    assert closed["closed_by_user_id"] == SECOND_COMPLIANCE_OFFICER_ID


def test_adjudicated_severity_scales_by_the_pre_existing_condition_factor(
    api, workbench, catalog, primary_leg
):
    """A pre-existing condition scales the same raw score by four fifths, and the
    product rounds half up before any cap is applied.

    PRD §3.9: "It then adds a late-disclosure penalty of 20 when `disclosure_required`
    is true and `disclosure_on_time` is false, and finally caps the result at 100. The
    rounding happens before the penalty is added and before the cap is applied."

    Design: Difficulty/dual_variant_calc/incident_severity_preliminary_vs_adjudicated_diverges
    """
    workbench.set_clock("2026-08-02T00:00:00Z")
    itinerary = _cargo_itinerary_with_long_connection(workbench, catalog, primary_leg)

    incident = workbench.report_incident(
        itinerary["animal_id"],
        incident_type="INJURY",
        segment_assignment_id=itinerary["second_slot_id"],
        discovered_at_utc="2026-08-02T00:00:00Z",
    )
    workbench.investigate_incident(incident["id"], as_user_id=COMPLIANCE_OFFICER_ID)
    workbench.disclose_incident(incident["id"], as_user_id=COMPLIANCE_OFFICER_ID)

    closed = workbench.close_incident(
        incident["id"], "PRE_EXISTING_CONDITION", as_user_id=SECOND_COMPLIANCE_OFFICER_ID
    )
    assert_incident_state(
        closed,
        status="CLOSED",
        preliminary_severity_score=62,
        adjudicated_severity_score=50,
        disclosure_required=True,
        disclosure_on_time=True,
    )


def test_disclosable_incident_cannot_close_before_disclosure(
    api, workbench, catalog, primary_leg
):
    """Branch A must be walked before the join: closing a disclosable incident straight
    out of the investigation is refused and adjudicates nothing.

    PRD §3.9: "Attempting to close an incident straight out of `INVESTIGATING` while its
    `disclosure_required` is true and no disclosure has been filed is refused with
    `ERR_DISCLOSURE_PENDING`."

    Design: Difficulty/non_linear_state_machine/disclosable_incident_cannot_close_before_disclosure_while_minor_incident_closes_directly
    """
    workbench.set_clock("2026-08-02T00:00:00Z")
    itinerary = _cargo_itinerary_with_long_connection(workbench, catalog, primary_leg)
    incident = workbench.report_incident(
        itinerary["animal_id"],
        incident_type="INJURY",
        segment_assignment_id=itinerary["second_slot_id"],
        discovered_at_utc="2026-08-02T00:00:00Z",
    )
    workbench.investigate_incident(incident["id"], as_user_id=COMPLIANCE_OFFICER_ID)

    refused = api.close_animal_incident(
        incident["id"],
        {"veterinary_finding": "CARRIER_ATTRIBUTABLE"},
        workbench.officer(SECOND_COMPLIANCE_OFFICER_ID),
    )
    validate_error(refused, ApiErrorId.DISCLOSURE_PENDING, 422)

    unchanged = workbench.read_incident(incident["id"])
    assert_incident_state(
        unchanged,
        status="INVESTIGATING",
        preliminary_severity_score=62,
        adjudicated_severity_score=None,
        disclosure_required=True,
        disclosure_on_time=None,
    )
    assert unchanged["closed_by_user_id"] is None
    assert unchanged["veterinary_finding"] is None


def test_minor_incident_closes_directly_out_of_investigating(
    api, workbench, investigated_incident
):
    """Branch B is the other half of the same fork: an incident with no disclosure
    obligation closes directly and writes no disclosure fields at all.

    PRD §3.9: "**Branch B** applies to incidents whose `disclosure_required` is false:
    those close directly out of `INVESTIGATING`, writing no disclosure fields at all."

    Design: Difficulty/non_linear_state_machine/disclosable_incident_cannot_close_before_disclosure_while_minor_incident_closes_directly
    """
    state = investigated_incident()
    assert_incident_state(
        state["incident"],
        status="INVESTIGATING",
        preliminary_severity_score=40,
        disclosure_required=False,
    )

    closed = workbench.close_incident(
        state["incident_id"],
        "CARRIER_ATTRIBUTABLE",
        as_user_id=SECOND_COMPLIANCE_OFFICER_ID,
    )
    assert_incident_state(
        closed,
        status="CLOSED",
        preliminary_severity_score=40,
        adjudicated_severity_score=40,
        disclosure_required=False,
        disclosure_deadline_utc=None,
        disclosure_on_time=None,
    )
    assert closed["disclosed_at_utc"] is None
    assert closed["veterinary_finding"] == "CARRIER_ATTRIBUTABLE"
    assert closed["closed_by_user_id"] == SECOND_COMPLIANCE_OFFICER_ID
