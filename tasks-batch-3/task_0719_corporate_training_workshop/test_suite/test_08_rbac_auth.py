"""Authentication, role authorization, and reverse-reachability listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_open_cohort, register_learner,
    make_learner_headers, NO_AUTH_HEADERS, TEST_USERS,
)

COORD = TEST_USERS["scheduling_coordinator_headers"]


def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "Every request to the API must be authenticated by two mandatory HTTP headers.
    `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational
    capacity under which the request is made. If either header is absent, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_missing_headers_returns_401
    """
    resp = api.create_program(
        {"title": "NoAuth", "category": "TECHNICAL", "delivery_mode": "VIRTUAL"},
        NO_AUTH_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_learner_cannot_create_program(api):
    """PRD §2.1: "When a request is authenticated but the acting role is not permitted to perform
    the requested operation, the system responds with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §2.1:
    "A `ProgramDesigner` owns catalog and custom program design".

    Design: Corner/rbac/learner_cannot_create_program
    """
    resp = api.create_program(
        {"title": "Hack", "category": "TECHNICAL", "delivery_mode": "VIRTUAL"},
        make_learner_headers("learner-x"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_scheduling_coordinator_cannot_create_contract(api):
    """PRD §2.1: "When a request is authenticated but the acting role is not permitted to perform
    the requested operation, the system responds with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §2.1:
    "A `FinanceManager` owns enterprise contracts and has visibility into invoices."

    Design: Corner/rbac/scheduling_coordinator_cannot_create_contract
    """
    resp = api.create_contract({"client_name": "X", "budget_cents": 1000}, COORD)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_list_cohort_registrations_reverse_reachability(api):
    """PRD §2.5: "Each `Cohort` maintains three derived seat counters that the system keeps
    consistent with the registrations beneath it." PRD §2.3: "Every list response includes the
    pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of
    the envelope." The cohort's registration list therefore returns the registrations beneath that
    cohort; a cohort with exactly two registrations and no others lists exactly those two.

    Design: Corner/endpoints/list_cohort_registrations_reverse_reachability
    """
    ctx = setup_open_cohort(version_overrides={"per_seat_cents": 10000, "min_seats": 1})
    coh_id = ctx["cohort"]["id"]
    register_learner(coh_id, "lr1@example.com")
    register_learner(coh_id, "lr2@example.com")
    rows, meta = validate_paginated(api.list_cohort_registrations(coh_id, COORD))
    assert len(rows) == 2, f"expected 2 registrations, got {len(rows)}"
