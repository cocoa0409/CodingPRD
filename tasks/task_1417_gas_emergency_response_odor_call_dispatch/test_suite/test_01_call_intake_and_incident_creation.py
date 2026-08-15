"""Call intake, incident creation, and request-shape rules (PRD §2.5, §2.6, §3.2)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    is_valid_uuid, ApiErrorId, NON_EXISTENT_UUID,
    setup_territory, intake_call, get_incident,
    create_emergency_call_payload, create_technician_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def test_primary_call_spawns_new_incident_with_implied_priority(api):
    """PRD §3.2: "PRIMARY — no live match and no recurrence match. A new gas
    incident is created in lifecycle status `NEW`, its `priority` initialized
    to the call's `implied_priority`" and "a call with no odor and no symptoms
    implies `P4`." A new incident starts with "linked_call_count 1" and
    "severity_score 0".

    Design: Corner/entities/emergency_call_intake_creates_incident_with_implied_priority
    """
    terr = setup_territory()
    call = intake_call(terr["id"], address_line="1 New St", caller_name="Zoe",
                       caller_phone="555-0200", location_context="PUBLIC_SPACE",
                       odor_reported=False, symptoms_reported=False,
                       hissing_reported=False)
    assert call["classification"] == "PRIMARY"
    assert call["implied_priority"] == "P4"
    assert call["is_duplicate"] is False

    incident = get_incident(call["incident_id"])
    assert incident["lifecycle_status"] == "NEW"
    assert incident["priority"] == "P4"
    assert incident["linked_call_count"] == 1
    # PRD §3.2: a new incident starts with severity_score 0.
    assert incident["severity_score"] == 0


def test_primary_call_implied_priority_rule_p1_via_symptoms(api):
    """PRD §3.2: "Any call with `symptoms_reported` true implies `P1`."
    The spawned incident's priority is initialized to the call's
    implied_priority (same PRIMARY rule).

    Design: Corner/entities/emergency_call_intake_creates_incident_with_implied_priority
    """
    terr = setup_territory()
    call = intake_call(terr["id"], address_line="2 New St", caller_name="Zoe",
                       caller_phone="555-0201", location_context="PUBLIC_SPACE",
                       odor_reported=False, symptoms_reported=True,
                       hissing_reported=False)
    assert call["classification"] == "PRIMARY"
    assert call["implied_priority"] == "P1"

    incident = get_incident(call["incident_id"])
    assert incident["lifecycle_status"] == "NEW"
    assert incident["priority"] == "P1"


def test_emergency_call_missing_required_field_returns_invalid_request(api):
    """PRD §2.6 step 5: "Required fields present, enum values within their
    declared domains ... (`ERR_INVALID_REQUEST`, `ERR_INVALID_TIME_RANGE`)."
    §3.2 lists `odor_reported` among the recorded intake fields.

    Design: Corner/entities/emergency_call_missing_required_field_returns_invalid_request
    """
    terr = setup_territory()
    payload = create_emergency_call_payload(
        caller_name="Amy", caller_phone="555-0201", address_line="2 New St",
        territory_id=terr["id"], location_context="INSIDE_STRUCTURE",
        symptoms_reported=False, hissing_reported=False)
    del payload["odor_reported"]
    resp = api_client.create_emergency_call(payload, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    data, meta = validate_paginated(api_client.list_incidents(
        SUPERVISOR, params={"territory_id": terr["id"]}))
    assert meta["total_count"] == 0, "rejected intake must leave no incident"


def test_emergency_call_occupancy_default_applied(api):
    """PRD §3.2: "The `occupancy_type` is optional and defaults to
    `SINGLE_FAMILY`" and a PRIMARY incident has "its `territory_id` and
    `occupancy_type` copied from the call".

    Design: Corner/entities/emergency_call_occupancy_default_applied
    """
    terr = setup_territory()
    payload = create_emergency_call_payload(
        caller_name="Ben", caller_phone="555-0202", address_line="3 New St",
        territory_id=terr["id"], location_context="OUTSIDE_STRUCTURE",
        odor_reported=True, symptoms_reported=False, hissing_reported=False)
    assert "occupancy_type" not in payload
    resp = api_client.create_emergency_call(payload, DISPATCHER)
    call = validate_success(resp, expected_status=201)
    assert call["occupancy_type"] == "SINGLE_FAMILY"

    incident = get_incident(call["incident_id"])
    assert incident["occupancy_type"] == "SINGLE_FAMILY"


def test_system_minted_fields_client_input_ignored(api):
    """PRD §2.5: "The `id` is a server-minted UUID with no type prefix. The
    `version` is a system-managed integer that increments with every
    mutation." §3.1: "`active_assignment_count` tallies their assignments
    currently in `EN_ROUTE` or `ON_SCENE`" and on_shift "is true exactly when
    the current logical time falls inside at least one of the technician's
    declared shift windows."

    Design: Corner/entities/system_minted_fields_client_input_ignored
    """
    terr = setup_territory()
    payload = create_technician_payload(
        full_name="Cy", badge_number="B100", home_territory_id=terr["id"],
        hourly_rate_cents=5500)
    payload["id"] = "00000000-0000-0000-0000-000000000000"
    payload["version"] = 99
    resp = api_client.create_technician(payload, ADMIN)
    tech = validate_success(resp, expected_status=201)

    assert tech["id"] != "00000000-0000-0000-0000-000000000000"
    assert is_valid_uuid(tech["id"])
    assert tech["version"] == 1
    assert tech["active_assignment_count"] == 0
    assert tech["on_shift"] is False


def test_invalid_enum_value_on_triage_returns_invalid_request(api):
    """PRD §2.6 step 5: "Required fields present, enum values within their
    declared domains ... (`ERR_INVALID_REQUEST`, `ERR_INVALID_TIME_RANGE`)."
    §3.3: "Triage is the first human judgment on an incident. A `Dispatcher`
    or `Supervisor` confirms or sets the priority by submitting a `priority`
    value" — the priority domain is P1..P4.

    Design: Corner/entities/invalid_enum_value_returns_invalid_request
    """
    terr = setup_territory()
    call = intake_call(terr["id"], address_line="4 New St", caller_name="Dee",
                       caller_phone="555-0203")
    resp = api_client.triage_incident(call["incident_id"], {"priority": "P9"},
                                      DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    incident = get_incident(call["incident_id"])
    assert incident["lifecycle_status"] == "NEW", "rejected triage must not mutate"


def test_invalid_time_range_on_shift_returns_400(api):
    """PRD §3.1: "An end that is not strictly after its start is rejected with
    `ERR_INVALID_TIME_RANGE` (HTTP 400)."

    Design: Corner/entities/invalid_time_range_on_shift_returns_400
    """
    terr = setup_territory()
    resp = api_client.create_technician(
        create_technician_payload(full_name="Ed", badge_number="B101",
                                  home_territory_id=terr["id"]), ADMIN)
    tech = validate_success(resp, expected_status=201)

    resp = api_client.create_shift(
        tech["id"],
        {"shift_start": "2026-08-01T08:00:00Z",
         "shift_end": "2026-08-01T08:00:00Z"},
        SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)


def test_immutable_emergency_call_has_no_version_field(api):
    """PRD §2.5: "Five entity kinds are deliberately lighter: a technician
    shift, an emergency call, an atmospheric reading, a make-safe action, and
    a premise entry authorization each carry `id` and `created_at` only — both
    `updated_at` and `version` are absent from them, because they are
    immutable records once created."

    Design: Corner/entities/immutable_emergency_call_has_no_version_field
    """
    terr = setup_territory()
    call = intake_call(terr["id"], address_line="6 New St", caller_name="Fi",
                       caller_phone="555-0204", location_context="OUTSIDE_STRUCTURE")

    resp = api_client.get_emergency_call(call["id"], DISPATCHER)
    data = validate_success(resp)
    assert "id" in data and "created_at" in data
    assert "received_at" in data and "classification" in data
    assert "version" not in data, "emergency call carries no version"
    assert "updated_at" not in data, "emergency call carries no updated_at"


def test_get_incident_not_found_returns_404(api):
    """PRD §2.6 step 3: "Every resource identifier in the URL path must exist,
    validated left to right (`ERR_TERRITORY_NOT_FOUND`, ...,
    `ERR_INCIDENT_NOT_FOUND`, ...)."

    Design: Corner/entities/get_incident_not_found_returns_404
    """
    setup_territory()
    resp = api_client.get_incident(NON_EXISTENT_UUID, SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_FOUND)


def test_list_incidents_pagination_envelope(api):
    """PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`." §2.2: the
    envelope carries meta.api_request_id / api_request_timestamp and
    response_type "array" for a list of resources.

    Design: Corner/entities/list_incidents_pagination_envelope
    """
    terr = setup_territory()
    for i in (1, 2, 3):
        intake_call(terr["id"], address_line=f"{i} Page St",
                    caller_name=f"G{i}", caller_phone=f"555-020{4 + i}",
                    location_context="OUTSIDE_STRUCTURE")

    resp = api_client.list_incidents(
        SUPERVISOR, params={"territory_id": terr["id"], "limit": 2, "offset": 0})
    body = resp.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in body["meta"]
    assert body["response_type"] == "array"
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    resp2 = api_client.list_incidents(
        SUPERVISOR, params={"territory_id": terr["id"], "limit": 2, "offset": 2})
    data2, meta2 = validate_paginated(resp2)
    assert len(data2) == 1
    assert meta2["has_more"] is False
