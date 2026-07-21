"""Watch parallel state dimensions plus catalog/inventory CRUD, provenance,
pagination, input validation, and RBAC on watch operations."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    is_valid_uuid, set_clock, new_customer, new_model, new_watch, new_watchmaker,
    authenticate, NON_EXISTENT_UUID, make_client_headers, TEST_USERS,
)
from test_helpers.factories import (
    create_customer_payload, create_watch_payload, create_service_ticket_payload,
)
from test_helpers.assertions import assert_provenance_event

ASSOC = TEST_USERS["associate_headers"]


def test_authenticate_leaves_inventory_status_unchanged(api):
    """PRD §3.1: "Authentication moves the watch's authentication_status from
    UNVERIFIED to AUTHENTICATED; it is permitted only when the watch is currently
    UNVERIFIED, otherwise ERR_INVALID_STATE."
    PRD §2.8: "A Watch has an inventory status and, evolving separately, an
    authentication_status."

    Design: Difficulty/non_linear_state_machine/watch_parallel_status_authentication
    """
    model = new_model()
    watch = new_watch(model["id"])
    assert watch["status"] == "IN_STOCK" and watch["authentication_status"] == "UNVERIFIED"
    authed = validate_success(api.authenticate_watch(watch["id"], ASSOC))
    assert authed["authentication_status"] == "AUTHENTICATED"
    assert authed["status"] == "IN_STOCK"  # inventory dimension untouched


def test_service_open_leaves_authentication_unchanged(api):
    """PRD §3.6: "Opening a ticket requires the serviced watch to be AUTHENTICATED
    (else ERR_WATCH_NOT_AUTHENTICATED, 409); on success the watch moves IN_STOCK →
    IN_SERVICE".
    PRD §2.8: "A Watch has an inventory status and, evolving separately, an
    authentication_status."

    Design: Difficulty/non_linear_state_machine/watch_parallel_status_authentication
    """
    set_clock("2026-07-02T00:00:00Z")
    customer = new_customer()
    model = new_model()
    watch = authenticate(new_watch(model["id"])["id"])
    wm = new_watchmaker()
    validate_success(
        api.create_service_ticket(
            create_service_ticket_payload(
                watch["id"], customer["id"], wm["id"], service_type="BATTERY",
                appt_start="2026-07-03T09:00:00Z", appt_end="2026-07-03T09:30:00Z"),
            ASSOC),
        expected_status=201,
    )
    fresh = validate_success(api.get_watch(watch["id"], ASSOC))
    assert fresh["status"] == "IN_SERVICE"
    assert fresh["authentication_status"] == "AUTHENTICATED"  # auth dimension untouched


def test_customer_create_initializes_store_credit_and_version(api):
    """PRD §3.1: "the balance store_credit_cents is initialized to 0 and is never
    client-supplied."
    PRD §2.4: "an integer version that begins at 1 and increases by one on each
    mutation."

    Design: Corner/entities/customer_create_success_system_fields
    """
    data = validate_success(api.create_customer(create_customer_payload(), ASSOC),
                            expected_status=201)
    assert data["store_credit_cents"] == 0
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])


def test_watch_create_with_unknown_model_not_found(api):
    """PRD §2.10: "then existence of every path-referenced and foreign-key-referenced
    resource, resolved left to right along the URL and then across referenced ids
    (ERR_NOT_FOUND, 404)".

    Design: Corner/entities/watch_create_bad_model_returns_not_found
    """
    validate_error(
        api.create_watch(create_watch_payload(NON_EXISTENT_UUID), ASSOC),
        ApiErrorId.ERR_NOT_FOUND,
    )


def test_duplicate_serial_number_rejected(api):
    """PRD §3.1: "The serial_number must be unique across all watches; a collision
    is rejected with ERR_SERIAL_DUPLICATE (HTTP 409), and this same uniqueness rule
    guards the serial minted when a trade-in or consignment settles."

    Design: Corner/entities/watch_serial_duplicate_rejected
    """
    model = new_model()
    validate_success(
        api.create_watch(create_watch_payload(model["id"], serial_number="DUP-X"), ASSOC),
        expected_status=201,
    )
    validate_error(
        api.create_watch(create_watch_payload(model["id"], serial_number="DUP-X",
                                              condition_grade="MINT"), ASSOC),
        ApiErrorId.ERR_SERIAL_DUPLICATE,
    )


def test_watch_intake_defaults(api):
    """PRD §3.1: "On intake the watch is born with inventory status of IN_STOCK,
    authentication_status of UNVERIFIED, a source of PURCHASE, a null
    current_appraisal_id, and an INTAKE provenance event is appended."

    Design: Corner/entities/watch_computed_status_and_auth_defaults
    """
    model = new_model()
    data = validate_success(api.create_watch(create_watch_payload(model["id"]), ASSOC),
                            expected_status=201)
    assert data["status"] == "IN_STOCK"
    assert data["authentication_status"] == "UNVERIFIED"
    assert data["source"] == "PURCHASE"


def test_list_watches_pagination_envelope(api):
    """PRD §2.3: "For every list response, the meta object carries limit, offset,
    total_count (the total number of records matching the query before pagination),
    and has_more (true when records beyond the current page remain)."

    Design: Corner/endpoints/list_watches_pagination_envelope
    """
    model = new_model()
    new_watch(model["id"])
    new_watch(model["id"])
    data, meta = validate_paginated(
        api.list_watches(ASSOC, params={"model_id": model["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_provenance_history_records_intake_and_authenticated(api):
    """PRD §3.7: "These events are written as the byproducts described throughout
    Section 3 — intake at inventory creation, authentication and flagging on the
    authentication actions, appraisal on valuation, allocation on offer, layaway
    reservation on plan creation, servicing on finish, and trade-in intake on
    settlement — and are never modified once written."

    Design: Corner/endpoints/provenance_history_after_authenticate
    """
    model = new_model()
    watch = authenticate(new_watch(model["id"])["id"])
    data, _meta = validate_paginated(api.get_provenance(watch["id"], ASSOC))
    for event in data:
        assert_provenance_event(event)
    event_types = {e["event_type"] for e in data}
    assert "INTAKE" in event_types
    assert "AUTHENTICATED" in event_types


def test_create_customer_missing_email_rejected(api):
    """PRD §2.10: "then request-body well-formedness — required fields present, enum
    values recognized, integer fields non-negative (ERR_VALIDATION, 400)."

    Design: Corner/validations/create_customer_missing_email_validation
    """
    validate_error(api.create_customer({"full_name": "No Email"}, ASSOC),
                   ApiErrorId.ERR_VALIDATION)


def test_authenticate_by_client_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)."
    PRD §2.1: "Associates are the boutique's staff and drive inventory,
    authentication, allocation, appraisal, trade-in and consignment administration,
    layaway administration, and the logical clock."

    Design: Corner/rbac/authenticate_by_client_unauthorized
    """
    customer = new_customer()
    model = new_model()
    watch = new_watch(model["id"])
    validate_error(
        api.authenticate_watch(watch["id"], make_client_headers(customer["id"])),
        ApiErrorId.ERR_UNAUTHORIZED,
    )


def test_create_watch_without_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or X-User-Role is not one of the
    three recognized roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP
    401)."

    Design: Corner/rbac/create_watch_missing_headers_unauthenticated
    """
    model = new_model()
    validate_error(
        api.create_watch(create_watch_payload(model["id"]), {}),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )
