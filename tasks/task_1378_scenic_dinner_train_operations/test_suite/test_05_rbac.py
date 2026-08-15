"""Role-based access control: per-endpoint and per-event_type role splits (PRD §2.1, §4)."""
import pytest

from test_helpers import (
    ANONYMOUS_HEADERS,
    MECH,
    NON_EXISTENT_UUID,
    create_active_agreement,
    create_slot_payload,
    setup_draft_excursion,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


def test_mechanic_cannot_create_slot(api, mechanic_headers):
    """PRD §2.1: "Authorization is purely role-based: each write operation is restricted
    to the roles listed for it in §4 (with some event endpoints split further by
    `event_type`), and an authenticated operator attempting an operation outside their
    role is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST `/railroad/slots` — "Create an operating slot (OPEN) under an ACTIVE
    agreement" — authorized role: Scheduler.

    Design: Corner/rbac/mechanic_cannot_create_slot
    """
    agreement = create_active_agreement()
    res = api.create_slot(create_slot_payload(agreement["id"]), mechanic_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_station_agent_cannot_publish_excursion(api, station_agent_headers):
    """PRD §2.1: "Authorization is purely role-based: each write operation is restricted
    to the roles listed for it in §4 (with some event endpoints split further by
    `event_type`), and an authenticated operator attempting an operation outside their
    role is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST `/railroad/excursions/{id}/events` — "PUBLISH (Scheduler, OCC),
    BEGIN_BOARDING (Scheduler, service-date gated), MARK_OPERATED (Scheduler), CANCEL
    (OperationsManager, with cancel_reason)".

    Design: Corner/rbac/station_agent_cannot_publish_excursion
    """
    scenario = setup_draft_excursion()
    excursion = scenario["excursion"]
    current = validate_success(api.get_excursion(excursion["id"], station_agent_headers), 200)

    res = api.excursion_event(excursion["id"],
                              {"event_type": "PUBLISH",
                               "expected_excursion_version": current["version"]},
                              station_agent_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
    after = validate_success(api.get_excursion(excursion["id"], station_agent_headers), 200)
    assert after["status"] == "DRAFT", "a forbidden publish changes nothing"


def test_scheduler_cannot_cancel_excursion(api, scheduler_headers):
    """PRD §2.1: "Authorization is purely role-based: each write operation is restricted
    to the roles listed for it in §4 (with some event endpoints split further by
    `event_type`), and an authenticated operator attempting an operation outside their
    role is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST `/railroad/excursions/{id}/events` — "PUBLISH (Scheduler, OCC),
    BEGIN_BOARDING (Scheduler, service-date gated), MARK_OPERATED (Scheduler), CANCEL
    (OperationsManager, with cancel_reason)".

    Design: Corner/rbac/scheduler_cannot_cancel_excursion
    """
    scenario = setup_draft_excursion()
    res = api.excursion_event(scenario["excursion"]["id"],
                              {"event_type": "CANCEL", "cancel_reason": "WEATHER"},
                              scheduler_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting operator, and `X-User-Role`, naming their operational capacity. A request
    missing either header, or carrying a role outside the declared set, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: "Requests are validated against a fixed priority pipeline, and when several
    checks could fail, the earliest tier's error is the one returned." (Authentication is
    tier 1, path existence is tier 3.)

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    # Even for a non-existent path id, the missing auth headers win (401 beats 404).
    res = api.get_excursion(NON_EXISTENT_UUID, headers=ANONYMOUS_HEADERS)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_any_role_can_read_shared_get(api, mechanic_headers, scheduler_headers):
    """PRD §2.1: "All read and list endpoints are shared by all six roles."

    Design: Corner/rbac/any_role_can_read_shared_get
    """
    scenario = setup_draft_excursion(car_specs=[], with_crew=False)
    res = api.get_excursion(scenario["excursion"]["id"], mechanic_headers)
    excursion = validate_success(res, 200)
    assert excursion["status"] == "DRAFT", "Mechanic (a non-scheduling role) reads fine"
