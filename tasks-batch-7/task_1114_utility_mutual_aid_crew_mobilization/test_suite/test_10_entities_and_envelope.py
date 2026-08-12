"""Corner tests for entity creation defaults, required fields, uniqueness,
not-found behavior, computed fields, and list pagination envelope
(PRD §2.2, §2.3, §2.5, §3.1, §3.3)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, NON_EXISTENT_UUID,
    make_program_admin_headers, make_responding_coordinator_headers,
    create_company, create_event, setup_event_with_accepted_request,
    commit_crew, create_utility_company_payload, create_event_payload,
    create_crew_payload,
)


def test_event_created_with_system_defaults():
    """PRD §3.1: "A new event opens in `OPEN` status with an `ACCEPTING` intake
    posture" PRD §2.8: "otherwise it is `ACCEPTING`" and the open-request
    population starts empty. PRD §2.5: "`version` (integer): a system-managed
    integer that increments by one on every mutation of the resource"

    Design: Corner/entities/entity_event_defaults_applied
    """
    host = create_company()
    resp = api_client.create_event(create_event_payload(host_utility_id=host["id"]),
                                   make_program_admin_headers())
    event = validate_success(resp, expected_status=201)
    assert event["status"] == "OPEN"
    assert event["intake_posture"] == "ACCEPTING"
    assert event["open_request_count"] == 0
    assert event["version"] == 1


def test_company_create_missing_company_code_rejected():
    """PRD §3.1: "a `ProgramAdmin` enrolls each participating company by
    providing its legal `name`, a program-wide `company_code` such as `HELCO`,
    its `role_capability` — one of `HOST`, `RESPONDING`, or `BOTH`, declaring
    which side(s) of mutual aid the company may act on — and a free-form
    `home_region`." — omitting the required `company_code` is a malformed
    body, rejected per §5 with `ERR_INVALID_REQUEST`.

    Design: Corner/entities/entity_company_create_missing_required_field_rejected
    """
    resp = api_client.create_utility_company(
        {"name": "No Code Co", "role_capability": "BOTH", "home_region": "Coastal"},
        make_program_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_company_duplicate_code_rejected():
    """PRD §3.1: "Company codes are unique across all registered companies; a
    duplicate `company_code` is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/entity_company_duplicate_code_rejected
    """
    create_company()
    resp = api_client.create_utility_company(
        create_utility_company_payload(name="Copycat", company_code="HST",
                                       role_capability="RESPONDING", home_region="Inland"),
        make_program_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_nonexistent_crew_returns_not_found():
    """PRD §2.9: "4. **Existence** — every referenced identifier exists,
    validated left-to-right with path parameters first and body-referenced
    identifiers after, else `ERR_NOT_FOUND` (HTTP 404)"

    Design: Corner/entities/entity_get_nonexistent_returns_not_found
    """
    resp = api_client.get_crew(NON_EXISTENT_UUID, make_program_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_crew_computed_fields_derived_server_side():
    """PRD §3.3: "The server derives `roster_size` from the roster's length and
    `equipment_daily_total_cents` as the sum of the equipment daily rates" and
    "A crew is born with `mobility_status` `COMMITTED` and `readiness_status`
    `AWAITING_BRIEFING`"

    Design: Corner/entities/entity_crew_computed_fields_input_ignored
    """
    ctx = setup_event_with_accepted_request()
    payload = create_crew_payload(
        request_id=ctx["request"]["id"],
        roster=[{"member_ref": "M1", "member_role": "foreman"},
                {"member_ref": "M2", "member_role": "lineman"}],
        equipment_units=[
            {"unit_type": "bucket_truck", "unit_ref": "BT-1", "daily_rate_cents": 20000},
            {"unit_type": "digger", "unit_ref": "DG-2", "daily_rate_cents": 25000},
        ])
    payload["roster_size"] = 99  # client-supplied value must be ignored
    resp = api_client.create_crew(payload, make_responding_coordinator_headers(ctx["rsp"]["id"]))
    crew = validate_success(resp, expected_status=201)
    assert crew["roster_size"] == 2
    assert crew["equipment_daily_total_cents"] == 45000
    assert crew["mobility_status"] == "COMMITTED"
    assert crew["readiness_status"] == "AWAITING_BRIEFING"


def test_timesheet_invalid_day_classification_rejected():
    """PRD §3.6: "The `CrewSupervisor` drafts a timesheet with the `crew_id`,
    the `work_date`, a `day_classification` of `TRAVEL`, `WORK`, `STANDBY`, or
    `REST`" — any other value is a malformed body, rejected with
    `ERR_INVALID_REQUEST` (HTTP 400) per §5.

    Design: Corner/entities/entity_timesheet_invalid_enum_rejected
    """
    ctx = setup_event_with_accepted_request()
    crew = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
    from test_helpers import make_crew_supervisor_headers, create_timesheet_payload
    resp = api_client.create_timesheet(
        create_timesheet_payload(crew_id=crew["id"], day_classification="HOLIDAY"),
        make_crew_supervisor_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_crew_list_response_carries_pagination_fields():
    """PRD §2.3: "the `meta` object of a list response carries `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/entity_list_envelope_pagination_fields
    """
    ctx = setup_event_with_accepted_request()
    commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
    commit_crew(ctx["request"]["id"], ctx["rsp"]["id"], crew_type="TREE",
                home_base="Depot 9", roster=[{"member_ref": "M2", "member_role": "foreman"}])
    resp = api_client.list_crews(make_program_admin_headers(),
                                 params={"request_id": ctx["request"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert "limit" in meta and "offset" in meta
    assert len(data) == 2
