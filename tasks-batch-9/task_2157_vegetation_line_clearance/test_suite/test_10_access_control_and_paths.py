"""Authentication, endpoint authorization and per-entity path resolution."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, create_prescription_payload, validate_error,
    validate_paginated, validate_success,
)

FORESTER = TEST_USERS["forester_headers"]
PLANNER = TEST_USERS["planner_headers"]

UNKNOWN_IDS = {
    "work-orders": ("00000000-0000-4000-8000-000000000001",
                    ApiErrorId.ERR_WORK_ORDER_NOT_FOUND.value),
    "billing-lines": ("00000000-0000-4000-8000-000000000002",
                      ApiErrorId.ERR_BILLING_LINE_NOT_FOUND.value),
    "crews": ("00000000-0000-4000-8000-000000000003",
              ApiErrorId.ERR_CREW_NOT_FOUND.value),
    "storm-events": ("00000000-0000-4000-8000-000000000004",
                     ApiErrorId.ERR_STORM_EVENT_NOT_FOUND.value),
    "herbicide-permits": ("00000000-0000-4000-8000-000000000005",
                          ApiErrorId.ERR_PERMIT_NOT_FOUND.value),
    "hazard-trees": ("00000000-0000-4000-8000-000000000006",
                     ApiErrorId.ERR_HAZARD_TREE_NOT_FOUND.value),
    "customer-notifications": ("00000000-0000-4000-8000-000000000007",
                               ApiErrorId.ERR_NOTIFICATION_NOT_FOUND.value),
    "crew-assignments": ("00000000-0000-4000-8000-000000000008",
                         ApiErrorId.ERR_CREW_ASSIGNMENT_NOT_FOUND.value),
    "production-entries": ("00000000-0000-4000-8000-000000000009",
                           ApiErrorId.ERR_PRODUCTION_ENTRY_NOT_FOUND.value),
    "outage-records": ("00000000-0000-4000-8000-00000000000a",
                       ApiErrorId.ERR_OUTAGE_RECORD_NOT_FOUND.value),
    "prescriptions": ("00000000-0000-4000-8000-00000000000b",
                      ApiErrorId.ERR_PRESCRIPTION_NOT_FOUND.value),
    "work-plans": ("00000000-0000-4000-8000-00000000000c",
                   ApiErrorId.ERR_WORK_PLAN_NOT_FOUND.value),
}


@pytest.mark.parametrize("collection", sorted(UNKNOWN_IDS))
def test_each_entity_type_reports_its_own_not_found_code(api, collection):
    """PRD §2.5: "Each entity type has its own not-found code:
    `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_WORK_PLAN_NOT_FOUND`,
    `ERR_WORK_ORDER_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_PRODUCTION_ENTRY_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`,
    `ERR_HAZARD_TREE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND`,
    `ERR_BILLING_LINE_NOT_FOUND` and `ERR_OUTAGE_RECORD_NOT_FOUND`, each returned with
    HTTP 404."
    PRD §2.5: "Path identifiers are resolved strictly left to right. Where a path names more
    than one resource, the leftmost is looked up first, and the first identifier that does not
    resolve determines the response — a request naming a nonexistent span and a nonexistent
    billing line fails on the span."

    Design: Corner/entities/corner_path_ids_validated_left_to_right_return_resource_not_found
    """
    unknown_id, expected_error = UNKNOWN_IDS[collection]

    resp = api.raw_get(f"/vm/{collection}/{unknown_id}", headers=FORESTER)

    validate_error(resp, expected_error)
    assert resp.status_code == 404
    assert resp.json()["response_type"] == "error"


def test_a_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint — reads included — must present two headers:
    `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either
    header is absent, or if `X-User-Role` holds a string that is not one of the seven roles
    below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/corner_missing_auth_header_returns_unauthenticated
    """
    resp = api.raw_get("/vm/circuits/00000000-0000-4000-8000-000000000000",
                       headers={"Content-Type": "application/json"})

    error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert resp.status_code == 401
    assert error["error_id"] != ApiErrorId.ERR_CIRCUIT_NOT_FOUND.value


def test_only_the_forester_may_author_a_prescription(api):
    """PRD §2.1: "The `UtilityForester` is the utility-side program owner. It alone authors and
    activates prescriptions, registers circuits and re-resolves their prescriptions, creates
    and cancels work plans, records outages, finalizes customer refusals, decides hazard trees,
    decides and revokes herbicide permits, declares/activates/demobilizes/closes storm events,
    and reviews and pays billing lines."
    PRD §2.1: "If both headers are well formed but the named role is not among the roles
    authorized for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/corner_contractor_planner_cannot_create_prescription
    """
    payload = create_prescription_payload(
        voltage_class="DISTRIBUTION_12KV", growth_zone="RAPID", base_cycle_years=4,
        clearance_radius_ft=10, effective_from="2026-01-01")

    denied = api.create_prescription(payload, PLANNER)

    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert denied.status_code == 403
    _, meta = validate_paginated(api.list_prescriptions(FORESTER))
    assert meta["total_count"] == 0

    allowed = api.create_prescription(payload, FORESTER)
    validate_success(allowed, 201)
