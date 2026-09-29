"""Role authority and the three segregation-of-duties bars.

Authorisation sits above every business rule in the precedence ladder, so each
case here also proves that the refusal is an authorisation refusal and not the
state or shape error that would otherwise apply.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER_ID,
    SECOND_COMPLIANCE_OFFICER_ID,
    animal_incident_payload,
    assert_animal_state,
    assert_flight_leg_state,
    assert_incident_state,
    assert_initial_version,
    assert_segment_state,
    validate_error,
    validate_success,
)


def test_program_admin_cannot_screen_animal_forbidden(api, workbench, catalog):
    """Screening belongs to the acceptance counter; the programme administrator is
    refused and the animal is left untouched.

    PRD §2.6: "The acting role appears in the called endpoint's authorised role
    list — otherwise `ERR_UNAUTHORIZED` (403). Every endpoint."

    Design: Corner/rbac/program_admin_cannot_screen_animal_forbidden
    """
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )

    refused = api.screen_animal_record(animal["id"], workbench.admin())
    validate_error(refused, ApiErrorId.UNAUTHORIZED, 403)
    assert_animal_state(
        workbench.read_animal(animal["id"]),
        status="DRAFT",
        container_compliance_state="UNEVALUATED",
    )

    allowed = api.screen_animal_record(
        animal["id"], workbench.acceptance("accept-01")
    )
    screened = validate_success(allowed)
    assert_animal_state(screened, status="SCREENED")


def test_reservations_agent_cannot_verify_health_document_forbidden(
    api, workbench, catalog
):
    """Verification is the reviewer's act. The booking agent's attempt fails on
    authority, above the document-state rung that would also have refused it.

    PRD §2.1: "**`VeterinaryReviewer`** — takes health documents under review and
    verifies or rejects them, and runs the per-reservation destination compliance
    sweep."

    Design: Corner/rbac/reservations_agent_cannot_verify_health_document_forbidden
    """
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    document = workbench.submit_document(
        animal["id"],
        document_type="HEALTH_CERTIFICATE",
        issuing_country_code="HK",
        issued_at="2026-08-20T00:00:00Z",
        expires_at="2026-11-20T00:00:00Z",
    )
    assert document["status"] == "SUBMITTED"

    refused = api.verify_health_document(document["id"], workbench.agent())
    validate_error(refused, ApiErrorId.UNAUTHORIZED, 403)

    stored = workbench.read_document(document["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["reviewed_by_user_id"] is None


def test_booking_agent_cannot_accept_its_own_reservation_forbidden(
    api, workbench, confirmed_booking
):
    """The operator who sold the booking may not accept it at the counter, even
    when every other acceptance precondition is satisfied.

    PRD §2.11: "Accepting a segment at the counter requires that the acting
    `X-User-ID` differ from the `booked_by_agent_id` recorded on the owning
    reservation."

    Design: Corner/rbac/booking_agent_cannot_accept_its_own_reservation_forbidden
    """
    state = confirmed_booking(booked_by="dual-01")
    workbench.amend_animal(
        state["animal_id"], as_user_id="dual-01", measured_weight_kg=27
    )

    refused = api.accept_segment_assignment(
        state["segment_id"], workbench.acceptance("dual-01")
    )
    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

    assert_segment_state(
        workbench.read_segment(state["segment_id"]),
        status="RESERVED",
        fee_variant="PROVISIONAL_AT_RESERVATION",
    )
    assert (
        workbench.read_reservation(state["reservation_id"])["booked_by_agent_id"]
        == "dual-01"
    )


def test_incident_reporter_cannot_investigate_own_report_forbidden(
    api, workbench, screened_booking
):
    """An officer may open an incident, but not investigate the one it opened.

    PRD §2.11: "Opening an incident investigation requires that the acting
    `X-User-ID` differ from the incident's `reported_by_user_id`."

    Design: Corner/rbac/incident_reporter_cannot_investigate_own_report_forbidden
    """
    state = screened_booking()
    reported = validate_success(
        api.create_animal_incident(
            animal_incident_payload(
                state["animal_id"],
                incident_type="INJURY",
                discovered_at_utc="2026-08-01T00:00:00Z",
            ),
            workbench.officer("comp-01"),
        ),
        201,
    )
    assert reported["reported_by_user_id"] == "comp-01"

    refused = api.investigate_animal_incident(
        reported["id"], workbench.officer("comp-01")
    )
    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

    unchanged = workbench.read_incident(reported["id"])
    assert_incident_state(unchanged, status="REPORTED")
    assert unchanged["investigated_by_user_id"] is None

    opened = validate_success(
        api.investigate_animal_incident(reported["id"], workbench.officer("comp-02"))
    )
    assert_incident_state(opened, status="INVESTIGATING")
    assert opened["investigated_by_user_id"] == "comp-02"


def test_investigator_cannot_close_the_incident_it_investigated_forbidden(
    api, workbench, investigated_incident
):
    """The investigating officer is barred from the close-out, and a second officer
    closing with an indeterminate finding scales the raw score by nine tenths.

    PRD §3.9: "That variant takes the same raw score as before, multiplies it by
    the attribution factor for the supplied `veterinary_finding` — one for
    `CARRIER_ATTRIBUTABLE`, nine tenths for `INDETERMINATE`, eight tenths for
    `PRE_EXISTING_CONDITION` — and rounds that product half up to a whole integer."

    Design: Corner/rbac/investigator_cannot_close_the_incident_it_investigated_forbidden
    """
    state = investigated_incident(
        reported_by="accept-01", investigated_by=COMPLIANCE_OFFICER_ID
    )

    refused = api.close_animal_incident(
        state["incident_id"],
        {"veterinary_finding": "INDETERMINATE"},
        workbench.officer(COMPLIANCE_OFFICER_ID),
    )
    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

    unchanged = workbench.read_incident(state["incident_id"])
    assert_incident_state(
        unchanged, status="INVESTIGATING", adjudicated_severity_score=None
    )
    assert unchanged["closed_by_user_id"] is None

    closed = validate_success(
        api.close_animal_incident(
            state["incident_id"],
            {"veterinary_finding": "INDETERMINATE"},
            workbench.officer(SECOND_COMPLIANCE_OFFICER_ID),
        )
    )
    assert_incident_state(
        closed,
        status="CLOSED",
        preliminary_severity_score=40,
        adjudicated_severity_score=36,
    )
    assert closed["closed_by_user_id"] == SECOND_COMPLIANCE_OFFICER_ID


def test_animal_update_is_shared_between_reservations_and_acceptance_agents(
    api, workbench, catalog
):
    """Amending an animal record is one of the two deliberately shared writes, so
    both agent roles succeed on it and the reviewer does not.

    PRD §2.1: "Write authority is otherwise disjoint, with two deliberate
    exceptions: amending an animal record is shared between `ReservationsAgent` and
    `AcceptanceAgent`, and reporting an animal incident is shared between
    `AcceptanceAgent` and `ComplianceOfficer`."

    Design: Corner/rbac/animal_update_is_shared_between_reservations_and_acceptance_agents
    """
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )

    by_agent = validate_success(
        api.update_animal_record(
            animal["id"], {"behavior_attestation_on_file": True}, workbench.agent()
        )
    )
    assert by_agent["behavior_attestation_on_file"] is True

    by_acceptance = validate_success(
        api.update_animal_record(
            animal["id"], {"measured_weight_kg": 21.4}, workbench.acceptance()
        )
    )
    assert by_acceptance["behavior_attestation_on_file"] is True
    assert by_acceptance["measured_weight_kg"] == 21.4
    assert by_acceptance["version"] == 3
    assert_animal_state(by_acceptance, status="DRAFT")

    refused = api.update_animal_record(
        animal["id"], {"measured_weight_kg": 22}, workbench.reviewer()
    )
    validate_error(refused, ApiErrorId.UNAUTHORIZED, 403)


def test_every_role_can_read_a_flight_leg(
    api,
    workbench,
    primary_leg,
    program_admin_headers,
    reservations_agent_headers,
    acceptance_agent_headers,
    veterinary_reviewer_headers,
    compliance_officer_headers,
):
    """Reads are open to the whole operator population, and every role sees the
    same derived view of the leg.

    PRD §2.1: "Every `GET` endpoint in the service is readable by all five roles."

    Design: Corner/rbac/every_role_can_read_a_flight_leg
    """
    leg = primary_leg()

    for headers in (
        program_admin_headers,
        reservations_agent_headers,
        acceptance_agent_headers,
        veterinary_reviewer_headers,
        compliance_officer_headers,
    ):
        seen = validate_success(api.get_flight_leg(leg["id"], headers))
        assert_flight_leg_state(
            seen, status="SCHEDULED", posture="OPEN", block_minutes=780
        )
        assert_initial_version(seen)
