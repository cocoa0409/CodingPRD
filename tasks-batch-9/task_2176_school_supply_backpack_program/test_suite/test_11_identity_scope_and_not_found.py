"""Operator identity, role scoping, and the per-entity not-found codes."""

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    create_active_school,
    create_active_site,
    create_collecting_cycle,
    create_pencil,
    create_site,
    make_school_liaison_headers,
    make_site_coordinator_headers,
    school_payload,
    validate_error,
    validate_paginated,
)
from test_helpers import TEST_USERS

PD = TEST_USERS["program_director_headers"]
WL = TEST_USERS["warehouse_lead_headers"]
DR = TEST_USERS["donor_relations_headers"]
SL = TEST_USERS["school_liaison_headers"]
SC = TEST_USERS["site_coordinator_headers"]


def test_request_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint — reads included — must carry two
    headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming
    the role that operator is acting in. If either header is absent, or if
    `X-User-Role` is not exactly one of the five declared role names, the request is
    rejected with `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/rbac/request_without_identity_headers_is_unauthenticated
    """
    response = api.create_school(school_payload(), {"Content-Type": "application/json"})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_site_coordinator_may_not_register_a_school(api):
    """PRD §2.1: "Once the caller is authenticated, the role is checked against the list
    of roles authorised for the requested endpoint in §4. A role that is not on that
    list is rejected with `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/site_coordinator_cannot_register_a_school
    """
    cycle = create_collecting_cycle()
    site = create_active_site(cycle["id"])

    response = api.create_school(school_payload(), make_site_coordinator_headers(site["id"]))
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_school_liaison_may_not_open_a_needs_list_for_another_school(api):
    """PRD §2.1: "When `X-User-Role` is `SchoolLiaison`, `X-User-ID` is the `id` of the
    acting `School`; ownership checks on any resource that references a `School`
    compare the resource's governing school reference to `X-User-ID`."
    PRD §2.1: "A liaison acting outside its own school is rejected with
    `ERR_SCHOOL_SCOPE_VIOLATION` (HTTP 403); a coordinator acting outside its own site
    is rejected with `ERR_SITE_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/school_liaison_cannot_open_a_needs_list_for_another_school
    """
    own = create_active_school(name="Lincoln Elementary")
    other = create_active_school(name="Garfield Middle", title_i_pct=0.60, enrollment_count=500)

    response = api.create_grade_kit_spec(
        {"school_id": other["id"], "grade_band": "K_2", "student_target_count": 80},
        make_school_liaison_headers(own["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SCHOOL_SCOPE_VIOLATION.value, expected_status=403)

    rows, _ = validate_paginated(api.list_school_grade_kit_specs(other["id"], PD))
    assert rows == [], "no needs list may be opened outside the liaison's own school"


def test_site_coordinator_may_not_book_donations_at_another_site(api):
    """PRD §2.1: "When `X-User-Role` is `SiteCoordinator`, `X-User-ID` is the `id` of the
    acting `CollectionSite`; ownership checks on any resource that references a
    `CollectionSite` compare the resource's governing site reference to `X-User-ID`."
    PRD §2.7: "7. Site scope: a `SiteCoordinator`'s `X-User-ID` equals the governing
    collection site of the resource. This guards five operations — moving the pledge
    dimension, creating a donation batch, transitioning a donation batch, creating a
    volunteer session, and transitioning a volunteer session. Otherwise
    `ERR_SITE_SCOPE_VIOLATION`, 403."

    Design: Corner/rbac/site_coordinator_cannot_book_donations_at_another_site
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    own = create_active_site(cycle["id"], name="Northside Depot")
    other = create_active_site(
        cycle["id"], name="Civic Center", site_type="LIBRARY", bin_capacity=8
    )

    response = api.create_donation_batch(
        {
            "collection_site_id": other["id"],
            "supply_item_id": pencil["id"],
            "qty_declared": 10,
            "condition": "NEW",
            "sealed": True,
        },
        make_site_coordinator_headers(own["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SITE_SCOPE_VIOLATION.value, expected_status=403)

    rows, _ = validate_paginated(
        api.list_donation_batches(WL, params={"collection_site_id": other["id"]})
    )
    assert rows == []


def _assert_not_found(response, error_id):
    error = validate_error(response, error_id, expected_status=404)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip()


def test_unknown_school_id_returns_school_not_found(api):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first
    identifier that fails to resolve decides the response with HTTP 404. Each entity has
    its own not-found code: `ERR_SCHOOL_NOT_FOUND`, `ERR_SUPPLY_ITEM_NOT_FOUND`,
    `ERR_KIT_SPEC_NOT_FOUND` (used for both a needs list and one of its lines),
    `ERR_DRIVE_CYCLE_NOT_FOUND`, `ERR_COLLECTION_SITE_NOT_FOUND`,
    `ERR_DONATION_BATCH_NOT_FOUND`, `ERR_INVENTORY_POSITION_NOT_FOUND`,
    `ERR_CASH_DONATION_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_VOLUNTEER_EVENT_NOT_FOUND`, `ERR_DISTRIBUTION_EVENT_NOT_FOUND`,
    `ERR_REGISTRATION_NOT_FOUND` and `ERR_TEACHER_REQUEST_NOT_FOUND`."

    Design: Corner/errors/school_get_with_unknown_id_returns_not_found
    """
    _assert_not_found(api.get_school(MISSING_UUID, PD), ApiErrorId.ERR_SCHOOL_NOT_FOUND.value)


def test_unknown_needs_list_id_returns_kit_spec_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_SCHOOL_NOT_FOUND`,
    `ERR_SUPPLY_ITEM_NOT_FOUND`, `ERR_KIT_SPEC_NOT_FOUND` (used for both a needs list
    and one of its lines), `ERR_DRIVE_CYCLE_NOT_FOUND`, `ERR_COLLECTION_SITE_NOT_FOUND`,
    `ERR_DONATION_BATCH_NOT_FOUND`, `ERR_INVENTORY_POSITION_NOT_FOUND`,
    `ERR_CASH_DONATION_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_VOLUNTEER_EVENT_NOT_FOUND`, `ERR_DISTRIBUTION_EVENT_NOT_FOUND`,
    `ERR_REGISTRATION_NOT_FOUND` and `ERR_TEACHER_REQUEST_NOT_FOUND`."

    Design: Corner/errors/grade_kit_spec_get_with_unknown_id_returns_not_found
    """
    _assert_not_found(
        api.get_grade_kit_spec(MISSING_UUID, SL), ApiErrorId.ERR_KIT_SPEC_NOT_FOUND.value
    )


def test_unknown_drive_cycle_id_returns_drive_cycle_not_found(api):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first
    identifier that fails to resolve decides the response with HTTP 404."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/errors/drive_cycle_get_with_unknown_id_returns_not_found
    """
    _assert_not_found(
        api.get_drive_cycle(MISSING_UUID, PD), ApiErrorId.ERR_DRIVE_CYCLE_NOT_FOUND.value
    )


def test_unknown_collection_site_id_returns_collection_site_not_found(api):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first
    identifier that fails to resolve decides the response with HTTP 404."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/collection_site_get_with_unknown_id_returns_not_found
    """
    _assert_not_found(
        api.get_collection_site(MISSING_UUID, PD),
        ApiErrorId.ERR_COLLECTION_SITE_NOT_FOUND.value,
    )


def test_unknown_donation_batch_id_returns_donation_batch_not_found(api):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first
    identifier that fails to resolve decides the response with HTTP 404."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/errors/donation_batch_get_with_unknown_id_returns_not_found
    """
    _assert_not_found(
        api.get_donation_batch(MISSING_UUID, WL),
        ApiErrorId.ERR_DONATION_BATCH_NOT_FOUND.value,
    )


def test_unknown_inventory_position_id_returns_inventory_position_not_found(api):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first
    identifier that fails to resolve decides the response with HTTP 404."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/inventory_position_get_with_unknown_id_returns_not_found
    """
    _assert_not_found(
        api.get_inventory_position(MISSING_UUID, WL),
        ApiErrorId.ERR_INVENTORY_POSITION_NOT_FOUND.value,
    )


def test_unknown_cash_donation_id_returns_cash_donation_not_found(api):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first
    identifier that fails to resolve decides the response with HTTP 404."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/errors/cash_donation_get_with_unknown_id_returns_not_found
    """
    _assert_not_found(
        api.get_cash_donation(MISSING_UUID, DR),
        ApiErrorId.ERR_CASH_DONATION_NOT_FOUND.value,
    )


def test_unknown_purchase_order_id_returns_purchase_order_not_found(api):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first
    identifier that fails to resolve decides the response with HTTP 404."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/purchase_order_get_with_unknown_id_returns_not_found
    """
    _assert_not_found(
        api.get_purchase_order(MISSING_UUID, WL),
        ApiErrorId.ERR_PURCHASE_ORDER_NOT_FOUND.value,
    )


def test_unknown_distribution_event_id_returns_distribution_event_not_found(api):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first
    identifier that fails to resolve decides the response with HTTP 404."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/errors/distribution_event_get_with_unknown_id_returns_not_found
    """
    _assert_not_found(
        api.get_distribution_event(MISSING_UUID, PD),
        ApiErrorId.ERR_DISTRIBUTION_EVENT_NOT_FOUND.value,
    )


def test_unknown_registration_id_returns_registration_not_found(api):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first
    identifier that fails to resolve decides the response with HTTP 404."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/student_registration_get_with_unknown_id_returns_not_found
    """
    _assert_not_found(
        api.get_student_registration(MISSING_UUID, SL),
        ApiErrorId.ERR_REGISTRATION_NOT_FOUND.value,
    )


def test_unknown_teacher_request_id_returns_teacher_request_not_found(api):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first
    identifier that fails to resolve decides the response with HTTP 404."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/errors/teacher_request_get_with_unknown_id_returns_not_found
    """
    _assert_not_found(
        api.get_teacher_request(MISSING_UUID, PD),
        ApiErrorId.ERR_TEACHER_REQUEST_NOT_FOUND.value,
    )


def test_transitioning_an_unknown_volunteer_session_is_not_found(api):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first
    identifier that fails to resolve decides the response with HTTP 404."
    PRD §2.7: "4. Path existence: every identifier in the path resolves, left to right
    — otherwise the matching not-found code, 404."

    Design: Corner/errors/volunteer_event_transition_with_unknown_id_returns_not_found
    """
    cycle = create_collecting_cycle()
    site = create_site(cycle["id"])

    response = api.transition_volunteer_event(
        MISSING_UUID, {"target_status": "IN_PROGRESS"}, make_site_coordinator_headers(site["id"])
    )
    validate_error(
        response, ApiErrorId.ERR_VOLUNTEER_EVENT_NOT_FOUND.value, expected_status=404
    )
