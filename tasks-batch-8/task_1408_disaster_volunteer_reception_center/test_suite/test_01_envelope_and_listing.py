"""Response envelope, pagination, and logical-clock stamping."""
import json
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_volunteer_payload, create_incident, create_active_incident,
    register_volunteer, set_clock, TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
INTAKE = TEST_USERS["intake_headers"]


def test_single_read_uses_object_envelope(api):
    """PRD section 2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources."

    Design: Corner/endpoints/response_envelope_object_and_array_shapes
    """
    incident = create_active_incident(name="Flood F3")
    volunteer = register_volunteer(incident["id"], full_name="Yara Yip")
    res = api.get_volunteer(volunteer["id"], MGR)
    body = res.json()
    assert res.status_code == 200
    assert body["response_type"] == "object"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["data"], dict) and body["data"]["id"] == volunteer["id"]


def test_list_read_uses_array_envelope_with_pagination_meta(api):
    """PRD section 2.3: "The `meta` object of a list response carries the
    pagination fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/response_envelope_object_and_array_shapes
    """
    incident = create_active_incident(name="Flood F3")
    register_volunteer(incident["id"], full_name="Yara Yip")
    res = api.list_incident_volunteers(incident["id"], MGR)
    body = res.json()
    assert res.status_code == 200
    assert body["response_type"] == "array"
    assert isinstance(body["data"], list) and len(body["data"]) == 1
    meta = body["meta"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_volunteer_list_default_page_holds_ten_of_twelve(api):
    """PRD section 2.3: "The `limit` parameter caps the number of items
    returned: it defaults to 10, with a minimum of 1 and a maximum of 100."

    Design: Corner/entities/volunteer_list_paginates_with_default_limit_and_offset
    """
    incident = create_active_incident(name="Flood Psi",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    for i in range(12):
        register_volunteer(incident["id"], full_name=f"V{i + 1:02d} A",
                           phone=f"555-{i + 1:02d}", email=f"v{i + 1:02d}@x.com")
    data, meta = validate_paginated(api.list_incident_volunteers(incident["id"], MGR))
    assert len(data) == 10, f"default page must hold 10 items, got {len(data)}"
    assert meta["total_count"] == 12
    assert meta["has_more"] is True


def test_volunteer_list_second_page_returns_remainder(api):
    """PRD section 2.3: "The `offset` parameter sets the number of items
    skipped and defaults to 0."

    Design: Corner/entities/volunteer_list_paginates_with_default_limit_and_offset
    """
    incident = create_active_incident(name="Flood Psi",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    for i in range(12):
        register_volunteer(incident["id"], full_name=f"V{i + 1:02d} A",
                           phone=f"555-{i + 1:02d}", email=f"v{i + 1:02d}@x.com")
    data, meta = validate_paginated(
        api.list_incident_volunteers(incident["id"], MGR, params={"limit": 10, "offset": 10}))
    assert len(data) == 2, f"second page must hold the remaining 2, got {len(data)}"
    assert meta["has_more"] is False
    assert meta["offset"] == 10


def test_created_at_defaults_to_startup_clock(api):
    """PRD section 2.4: "Before any operator intervention, the logical clock
    reads exactly 2026-08-01T00:00:00Z."

    Design: Corner/entities/created_at_stamps_use_logical_clock_not_wall_clock
    """
    # Deliberately no set_clock call: the server must be at its startup default.
    incident = validate_success(api.create_incident(
        {"name": "Quake Omega",
         "ppe_stock": {"GLOVES": 1, "MASK": 1, "HARD_HAT": 1, "VEST": 1, "GOGGLES": 1}},
        MGR), 201)
    api.activate_incident(incident["id"], MGR)
    volunteer = register_volunteer(incident["id"], full_name="Early Ed")
    assert volunteer["created_at"].startswith("2026-08-01T00:00:00"), (
        f"created_at must be the startup instant, got {volunteer['created_at']!r}")
    assert volunteer["created_at"].endswith("Z")


def test_created_at_follows_the_logical_clock_after_set(api):
    """PRD section 2.4: "All time in the system comes from a single logical
    clock; the server never falls back to wall-clock time."

    Design: Corner/entities/created_at_stamps_use_logical_clock_not_wall_clock
    """
    incident = create_active_incident(name="Quake Omega",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    set_clock("2026-08-05T10:30:00Z")
    volunteer = register_volunteer(incident["id"], full_name="Late Liz")
    assert volunteer["created_at"].startswith("2026-08-05T10:30:00"), (
        f"created_at must equal the logical clock, got {volunteer['created_at']!r}")
    assert volunteer["created_at"].endswith("Z")
