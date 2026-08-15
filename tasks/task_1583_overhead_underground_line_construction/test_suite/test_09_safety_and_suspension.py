"""Safety events and stop-work authority: the suspension cascade, the resume
gate, and the suspension-era write block."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_safety_event,
    create_assignment_payload,
    create_crew_payload,
    create_equipment_payload,
    get_success_data,
    setup_approved_outage,
    setup_field_scenario,
    setup_mobilized_scenario,
    suspend_contract_via_incident,
    validate_error,
    validate_success,
)

PM = TEST_USERS["contractor_pm_headers"]
FOREMAN = TEST_USERS["foreman_headers"]
DISPATCHER = TEST_USERS["utility_dispatcher_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


def _cascade_scenario(api):
    """IN_PROGRESS outage-dependent package with an ACTIVE assignment (clock
    2026-08-03 inside its window) and an APPROVED outage on CKT-9 for
    2026-08-10 (outside the clock, so it is not yet in effect)."""
    scenario = setup_field_scenario(
        requires_outage=True,
        contract_overrides={"contract_number": "C-501"},
        bid_item_overrides={"item_code": "UG-CABLE-500",
                            "description": "500MCM UG cable", "unit": "LF",
                            "unit_price": 30.00, "estimated_quantity": 200},
        wp_overrides={"name": "UG feeder U-8", "location": "Airport Rd"},
        crew_overrides={"crew_code": "CR-X", "crew_type": "UNDERGROUND",
                        "base_rate_per_hour": 58.00},
        equipment_overrides={"equipment_code": "EQ-X", "kind": "REEL_TRAILER",
                             "daily_rate": 90.00})
    outage = setup_approved_outage(scenario["work_package"]["id"], "CKT-9",
                                   "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z")
    return scenario, outage


class TestSuspensionCascade:
    def test_fatal_incident_suspends_contract(self, api):
        """PRD §2.10: "Suspension itself is never requested directly. It is the
        system's response to a serious field incident: when a safety event of
        kind `INCIDENT` with severity `OSHA_RECORDABLE` or `FATAL` is created,
        the contract moves from `ACTIVE` to `SUSPENDED` automatically, and the
        stop-work cascade resolves everything in flight — every assignment of
        every work package of the contract standing in `PLANNED` or `ACTIVE` is
        moved to `CANCELLED`, and every outage request of every work package
        standing in `REQUESTED`, `APPROVED`, or `CHANGE_REQUESTED` is moved to
        `CANCELLED`."
        PRD §3.8: "A new event stands `OPEN`."

        Design: Difficulty/transitive_cascade/fatal_incident_cascade_suspends_contract
        """
        scenario, outage = _cascade_scenario(api)
        event = suspend_contract_via_incident(
            scenario, severity="FATAL", crew_id=scenario["crew"]["id"])
        assert_safety_event(event)
        assert event["status"] == "OPEN", "A new event stands OPEN"
        assert event["kind"] == "INCIDENT"
        assert event["severity"] == "FATAL"

        contract_after = validate_success(
            api.get_contract(scenario["contract"]["id"], PM))
        assert contract_after["status"] == "SUSPENDED", (
            "The FATAL incident moves the contract from ACTIVE to SUSPENDED "
            "automatically")

    def test_fatal_incident_cancels_assignments_and_outages(self, api):
        """PRD §2.10: "Suspension itself is never requested directly. It is the
        system's response to a serious field incident: when a safety event of
        kind `INCIDENT` with severity `OSHA_RECORDABLE` or `FATAL` is created,
        the contract moves from `ACTIVE` to `SUSPENDED` automatically, and the
        stop-work cascade resolves everything in flight — every assignment of
        every work package of the contract standing in `PLANNED` or `ACTIVE` is
        moved to `CANCELLED`, and every outage request of every work package
        standing in `REQUESTED`, `APPROVED`, or `CHANGE_REQUESTED` is moved to
        `CANCELLED`."

        Design: Difficulty/transitive_cascade/fatal_incident_cascade_suspends_contract
        """
        scenario, outage = _cascade_scenario(api)
        assert scenario["assignment"]["status"] == "ACTIVE"
        assert outage["status"] == "APPROVED"

        suspend_contract_via_incident(scenario, severity="FATAL",
                                      crew_id=scenario["crew"]["id"])

        assignment_after = validate_success(
            api.get_assignment(scenario["assignment"]["id"], PM))
        assert assignment_after["status"] == "CANCELLED", (
            "The suspension cascade cancels the in-flight ACTIVE assignment")
        outage_after = validate_success(api.get_outage_request(outage["id"], PM))
        assert outage_after["status"] == "CANCELLED", (
            "The suspension cascade cancels the APPROVED outage request")


class TestResumption:
    def test_resume_blocked_until_incidents_closed(self, api):
        """PRD §3.8: "Resumption is the dispatcher's deliberate act: a contract
        transition with `to` set to `ACTIVE` moves a `SUSPENDED` contract back
        to `ACTIVE`, but only when no safety event of kind `INCIDENT` stands in
        `OPEN` or `UNDER_REVIEW` on any work package of the contract — while one
        remains, the resume is rejected with `ERR_SAFETY_EVENT_OPEN`."
        PRD §2.10: "Safety-event review transitions — moving an event to
        `UNDER_REVIEW` or `CLOSED` — remain available while the contract is
        suspended, so incidents logged before the suspension can be reviewed and
        closed; without this exemption, resumption would be unreachable."

        Design: Corner/validations/contract_resume_blocked_until_incidents_closed
        """
        scenario = setup_mobilized_scenario(
            contract_overrides={"contract_number": "CV-11"},
            wp_overrides={"name": "WP safe", "location": "L17"})
        event = suspend_contract_via_incident(
            scenario, severity="OSHA_RECORDABLE")

        resume = api.transition_contract(scenario["contract"]["id"],
                                         {"to": "ACTIVE"}, DISPATCHER)
        validate_error(resume, ApiErrorId.ERR_SAFETY_EVENT_OPEN)

        # The review track stays available while the contract is SUSPENDED.
        under_review = validate_success(api.transition_safety_event(
            event["id"], {"to": "UNDER_REVIEW"}, SAFETY))
        assert under_review["status"] == "UNDER_REVIEW"
        closed = validate_success(api.transition_safety_event(
            event["id"], {"to": "CLOSED"}, SAFETY))
        assert closed["status"] == "CLOSED"

        resumed = validate_success(api.transition_contract(
            scenario["contract"]["id"], {"to": "ACTIVE"}, DISPATCHER))
        assert resumed["status"] == "ACTIVE", (
            "With the incident CLOSED the dispatcher's resume succeeds")


class TestSuspendedWriteBlock:
    def test_writes_blocked_while_contract_suspended(self, api):
        """PRD §2.10: "Operational writes are only accepted while the owning
        contract is `ACTIVE`. When the contract is `SUSPENDED`, such writes are
        rejected with `ERR_CONTRACT_SUSPENDED` (HTTP 409); when it is `DRAFT` or
        `CLOSED`, they are rejected with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409).
        The gate covers work package transitions, assignment creation and
        transitions, production reporting, material issuance, returns and
        reconciliation, inspection scheduling and submission, outage requests
        and their downstream operations, storm activations, safety-event
        creation, and invoice creation and transitions."

        Design: Corner/validations/writes_blocked_while_contract_suspended
        """
        scenario = setup_mobilized_scenario(
            contract_overrides={"contract_number": "CV-16"},
            wp_overrides={"name": "WP sus", "location": "L22"})
        suspend_contract_via_incident(scenario, severity="FATAL")
        contract_after = validate_success(
            api.get_contract(scenario["contract"]["id"], PM))
        assert contract_after["status"] == "SUSPENDED"

        # Crews and equipment are registered once and reused across contracts;
        # their registration is not a contract-scoped operational write.
        crew = get_success_data(api.create_crew(
            create_crew_payload(crew_code="CR-AF"), PM))
        equipment = get_success_data(api.create_equipment(
            create_equipment_payload(equipment_code="EQ-AF"), PM))

        resp = api.create_assignment(
            scenario["work_package"]["id"],
            create_assignment_payload(crew["id"], equipment["id"]),
            FOREMAN)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_SUSPENDED)
