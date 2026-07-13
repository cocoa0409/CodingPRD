"""Entity creation, defaults, computed fields, not-found, and FK-filtered listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_incident_payload, create_task_payload, create_member_payload,
    create_resource_payload, create_callout_payload,
    assert_incident, assert_member, assert_resource,
    create_active_incident, create_team, create_member, create_team_and_member,
    create_task, create_callout,
)

COORD = TEST_USERS["coordinator_headers"]
IC = TEST_USERS["incident_commander_headers"]


def test_create_incident_starts_planning_with_zero_ledger(api):
    """PRD §3.1: "A new incident starts in `PLANNING` status, and its ledger and
    rollup fields (`total_approved_reimbursement_cents`, `total_logged_hours`,
    `total_mileage_miles`, `active_task_count`) all begin at zero."
    PRD §2.4: "an integer `version` that starts at 1 and increments by one on each mutation."

    Design: Corner/entities/create_incident_returns_201_with_system_fields
    """
    resp = api.create_incident(
        create_incident_payload(name="New Inc", incident_type="DISASTER",
                                ics_incident_number="OR-2026-1000"),
        COORD,
    )
    data = validate_success(resp, expected_status=201)
    assert_incident(data)
    assert data["status"] == "PLANNING"
    assert data["version"] == 1
    assert data["total_approved_reimbursement_cents"] == 0


def test_get_incident_unknown_id_returns_not_found(api):
    """PRD §2.7: "The first identifier in the path that does not correspond to an
    existing resource causes immediate rejection with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_incident_nonexistent_returns_not_found
    """
    resp = api.get_incident("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", COORD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_task_missing_segment_area_returns_validation(api):
    """PRD §2.5: "The request body must be well-formed: required fields present,
    enum values legal, numeric ranges honored (for example `segment_area_sqkm`
    strictly greater than 0, `planned_end` strictly after `planned_start`,
    `window_end` strictly after `window_start`, and non-negative amounts), and any
    foreign key named in the body must reference an existing record. Otherwise
    `ERR_VALIDATION` (422)."

    Design: Corner/entities/create_task_missing_required_field_returns_validation
    """
    inc = api.create_incident(
        create_incident_payload(name="Val Inc", incident_type="URBAN",
                                ics_incident_number="OR-2026-1001"), COORD)
    inc_id = validate_success(inc, expected_status=201)["id"]

    payload = create_task_payload(inc_id)
    del payload["segment_area_sqkm"]
    resp = api.create_task(payload, COORD)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_create_member_defaults_to_active(api):
    """PRD §3.2: "A member opens in `ACTIVE` status; over an operation their
    `status` moves to `STANDBY` and `DEPLOYED` as their callouts advance, and back
    to `ACTIVE` when they demobilize."

    Design: Corner/entities/create_member_default_status_active
    """
    team = create_team(api)
    resp = api.create_member(create_member_payload(team["id"], full_name="Pat Vol",
                                                    email="pat@x.org"), COORD)
    data = validate_success(resp, expected_status=201)
    assert_member(data)
    assert data["status"] == "ACTIVE"


def test_create_resource_computed_available_zero_count(api):
    """PRD §3.5: "A resource opens with `active_assignment_count` at zero and,
    being idle and in service, an effective `status` of `AVAILABLE`."

    Design: Corner/entities/create_resource_computed_status_and_count
    """
    # A K9 requires a handler per §3.5; supply a real one so the create is valid
    # and the claim under test (computed AVAILABLE + zero count) is what we exercise.
    team, member = create_team_and_member(api, member_overrides={"member_role": "K9_HANDLER"})
    resp = api.create_resource(
        create_resource_payload(name="K9 Ranger", resource_type="K9",
                                handler_member_id=member["id"]), COORD)
    data = validate_success(resp, expected_status=201)
    assert_resource(data)
    assert data["status"] == "AVAILABLE"
    assert data["active_assignment_count"] == 0


def test_filtered_callout_list_by_task_returns_task_children(api):
    """PRD §1: "every foreign-key relationship is navigable through filtered list
    endpoints so that the full operational graph is reconstructable at any time."

    Design: Corner/cross_cutting/fk_filtered_list_callouts_by_task_returns_children
    """
    inc = create_active_incident(api, name="Fk Inc", ics_incident_number="OR-2026-1020")
    team, member = create_team_and_member(api)
    task = create_task(api, inc["id"])
    co = create_callout(api, task["id"], member["id"])

    resp = api.list_callouts(COORD, params={"task_id": task["id"]})
    data, meta = validate_paginated(resp)
    ids = [row["id"] for row in data]
    assert co["id"] in ids, f"Expected callout {co['id']} in task-filtered list, got {ids}"
    assert all(row["task_id"] == task["id"] for row in data)
