"""Corner coverage: pole initial-state gating and the audit
dispute/resubmit cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_program,
    create_crew,
    create_district,
    create_pole,
    create_route,
    get_pole,
    make_field_supervisor_headers,
    setup_cleared_pole,
    setup_program_district_crew,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


def test_pole_initial_state_gates_stop_add(api):
    """PRD section 3.3: "The pole must live in the route's own district
    (ERR_CROSS_DISTRICT_STOP), must be AUDIT_CLEARED — an EXEMPT pole draws
    ERR_POLE_EXEMPT, a pole in any other state ERR_POLE_NOT_AUDIT_CLEARED";
    PRD section 3.1: "A pole is born SURVEYED".

    Design: Corner/state_machines/sm_pole_initial_state_gates_stop_add
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = create_pole(district["id"], pole_number="G-1", ownership_type="MUNICIPAL",
                       fixture_class="COBRA_HEAD", nameplate_wattage=250)
    assert pole["status"] == "SURVEYED"
    route = create_route(district["id"], crew["id"], start="2026-08-03", end="2026-08-03")

    resp = api.add_stop(
        route["id"],
        {"pole_id": pole["id"], "sequence_number": 1, "difficulty_class": "STANDARD"},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_POLE_NOT_AUDIT_CLEARED, expected_status=409)
    assert get_pole(pole["id"])["status"] == "SURVEYED"
    resp = api.list_stops(PM, params={"route_id": route["id"]})
    assert resp.json()["meta"]["total_count"] == 0


def test_audit_dispute_resubmit_cycle(api):
    """PRD section 3.2: "Dispute moves `SUBMITTED` → `DISPUTED` and records the
    decider in `decided_by_user_id`. A disputed audit is not dead: the
    `FieldSupervisor` may resubmit it with a corrected `audited_wattage` (and
    fresh `auditor_notes`), which returns it `DISPUTED` → `SUBMITTED`,
    increments `revision_count`, and clears `decided_by_user_id` back to null."
    PRD section 3.2: "On acceptance the pole's `effective_wattage` becomes the
    `audited_wattage`" and "a pole still `SURVEYED` advances to
    `AUDIT_CLEARED`".

    Design: Corner/state_machines/sm_audit_dispute_resubmit_cycle
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = create_pole(district["id"], pole_number="A-1", ownership_type="MUNICIPAL",
                       fixture_class="COBRA_HEAD", nameplate_wattage=250)

    resp = api.submit_audit(
        pole["id"],
        {"audited_wattage": 260, "expected_pole_version": pole["version"]},
        make_field_supervisor_headers(crew["id"]),
    )
    audit = validate_success(resp, expected_status=201)
    assert audit["status"] == "SUBMITTED"
    assert audit["revision_count"] == 0

    resp = api.dispute_audit(audit["id"], PM)
    disputed = validate_success(resp)
    assert disputed["status"] == "DISPUTED"

    resp = api.resubmit_audit(
        audit["id"],
        {"audited_wattage": 240, "auditor_notes": "re-read meter"},
        make_field_supervisor_headers(crew["id"]),
    )
    resubmitted = validate_success(resp)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1
    assert resubmitted["audited_wattage"] == 240
    assert resubmitted["decided_by_user_id"] is None

    resp = api.accept_audit(audit["id"], PM)
    accepted = validate_success(resp)
    assert accepted["status"] == "ACCEPTED"
    pole_after = get_pole(pole["id"])
    assert pole_after["effective_wattage"] == 240
    assert pole_after["status"] == "AUDIT_CLEARED"
    assert pole_after["wattage_tier"] == "T3"
