"""Roles, ownership, the logical clock, pagination bounds and row versioning."""

from test_helpers import *  # noqa: F401,F403


def test_pagination_limit_above_the_maximum_is_rejected(api, admin):
    """PRD §2.3: "`limit` defaults to 10 (`DEFAULT_PAGE_LIMIT`), may not be smaller
    than 1 (`MIN_PAGE_LIMIT`) and may not be larger than 100 (`MAX_PAGE_LIMIT`); a
    value outside that closed range is refused with `ERR_VALUE_OUT_OF_RANGE` (HTTP
    422)."

    Design: Corner/validations/corner_pagination_limit_above_the_maximum_is_rejected
    """
    response = api.list_barns(admin, params={"limit": MAX_PAGE_LIMIT + 1})

    validate_error(response, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value)
    assert response.status_code == 422

    accepted, meta = validate_paginated(
        api.list_barns(admin, params={"limit": MAX_PAGE_LIMIT})
    )
    assert meta["limit"] == 100, "the closed range admits its upper bound"


def test_clock_reads_the_declared_default_before_any_set_call(api, admin, dispatcher):
    """PRD §2.4: "Time in this system is a **logical clock**, never the host's wall
    clock. Before any operator sets it, the clock reads exactly
    `2026-05-01T00:00:00Z` (`DEFAULT_CLOCK_UTC`), and it never falls back to real
    time."
    PRD §2.6: "The `Farrier` that owns the `Route` in scope must have `status`
    `ACTIVE`, and that farrier's `cert_expires_on` must be on or after the logical
    clock date."
    PRD §2.4: "A `PlatformAdmin` moves it with a test-driving capability that takes
    a single field, `to_iso8601`, and returns an object rather than an entity:
    `current_utc` (the new clock value as an ISO 8601 string),
    `expired_prescription_ids` (the ids of prescriptions this move pushed into
    `EXPIRED`, ordered by their `created_at` ascending) and `restanding_client_ids`
    (the ids of clients whose `billing_standing` this move changed, ordered by their
    `created_at` ascending)."

    Design: Corner/endpoints/corner_clock_reads_the_declared_default_before_any_set_call
    """
    lapsed = create_farrier(display_name="Lapsed", cert_expires_on="2026-04-30")
    current = create_farrier(display_name="Current", cert_expires_on="2026-05-01")

    refused = api.create_route(
        {"farrier_id": lapsed["id"], "route_date": "2026-05-06"}, dispatcher
    )
    validate_error(refused, ApiErrorId.ERR_FARRIER_CERT_EXPIRED.value)

    admitted = validate_success(
        api.create_route(
            {"farrier_id": current["id"], "route_date": "2026-05-06"}, dispatcher
        ),
        201,
    )
    assert_route(admitted)

    data = validate_success(
        api.set_clock({"to_iso8601": DEFAULT_CLOCK_UTC}, admin)
    )
    assert_same_instant(data["current_utc"], DEFAULT_CLOCK_UTC)
    assert data["expired_prescription_ids"] == []
    assert data["restanding_client_ids"] == []


NOT_FOUND_READS = [
    ("get_client", ApiErrorId.ERR_CLIENT_NOT_FOUND.value),
    ("get_farrier", ApiErrorId.ERR_FARRIER_NOT_FOUND.value),
    ("get_shoe_sku", ApiErrorId.ERR_SKU_NOT_FOUND.value),
    ("get_inventory_bucket", ApiErrorId.ERR_BUCKET_NOT_FOUND.value),
    ("get_stock_transfer", ApiErrorId.ERR_TRANSFER_NOT_FOUND.value),
    ("get_shoe_reservation", ApiErrorId.ERR_RESERVATION_NOT_FOUND.value),
    ("get_rate_card", ApiErrorId.ERR_RATE_CARD_NOT_FOUND.value),
    ("get_route", ApiErrorId.ERR_ROUTE_NOT_FOUND.value),
    ("get_route_stop", ApiErrorId.ERR_ROUTE_STOP_NOT_FOUND.value),
    ("get_appointment", ApiErrorId.ERR_APPOINTMENT_NOT_FOUND.value),
    ("get_service_line", ApiErrorId.ERR_SERVICE_LINE_NOT_FOUND.value),
    ("get_lameness_case", ApiErrorId.ERR_LAMENESS_CASE_NOT_FOUND.value),
    ("get_prescription", ApiErrorId.ERR_PRESCRIPTION_NOT_FOUND.value),
    ("get_invoice", ApiErrorId.ERR_INVOICE_NOT_FOUND.value),
    ("get_reminder", ApiErrorId.ERR_REMINDER_NOT_FOUND.value),
]


def test_unknown_ids_return_the_entity_specific_not_found_code(api, admin):
    """PRD §2.7: "In order: (4) `Barn` — `ERR_BARN_NOT_FOUND`, on barn read, client
    creation, horse creation and stop insertion. (5) `Client` —
    `ERR_CLIENT_NOT_FOUND`, on client read, deposit posting, payment application and
    horse creation. (6) `Horse` — `ERR_HORSE_NOT_FOUND`, on horse read, horse patch,
    retire, reinstate, limb-state listing, appointment creation and lameness-case
    creation."
    PRD §2.7: "(19) `Invoice` — `ERR_INVOICE_NOT_FOUND`, on invoice read,
    invoice-line listing, issue and void. (20) `Reminder` —
    `ERR_REMINDER_NOT_FOUND`, on reminder read, send and acknowledge."

    Design: Corner/errors/corner_unknown_ids_return_the_entity_specific_not_found_code
    """
    for method_name, expected_error in NOT_FOUND_READS:
        response = getattr(api, method_name)(NON_EXISTENT_UUID, admin)
        assert response.status_code == 404, (
            f"{method_name} must answer an unknown id with 404, "
            f"got {response.status_code}"
        )
        validate_error(response, expected_error)


def test_missing_auth_headers_returns_unauthenticated(api, no_auth):
    """PRD §2.1: "Every request to this API — without exception, including read-only
    requests — must carry two headers: `X-User-ID` and `X-User-Role`. If either
    header is absent, or if `X-User-Role` carries a string that is not one of the
    six roles named below, the request is refused with `ERR_UNAUTHENTICATED` (HTTP
    401)."
    PRD §2.1: "These two checks sit at the very top of the rejection ladder and run
    before anything else, including before the server looks up any resource id."

    Design: Corner/rbac/corner_missing_auth_headers_returns_unauthenticated
    """
    response = api.get_barn(NON_EXISTENT_UUID, no_auth)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401


def test_veterinarian_cannot_open_a_route(api, vet):
    """PRD §2.1: "If both headers are well formed but the named role does not appear
    in the authorized-role set of the endpoint being called, the request is refused
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.4: "A `Dispatcher` opens a route for one farrier on one date, supplying
    `farrier_id` and `route_date`."

    Design: Corner/rbac/corner_veterinarian_cannot_open_a_route
    """
    farrier = create_farrier()

    response = api.create_route(
        {"farrier_id": farrier["id"], "route_date": "2026-05-06"}, vet
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert response.status_code == 403
    rows, _meta = validate_paginated(
        api.list_routes(dispatcher_headers(), params={"farrier_id": farrier["id"]})
    )
    assert rows == [], "no route row was created"


def test_dispatcher_cannot_complete_an_appointment(api, dispatcher):
    """PRD §2.1: "If both headers are well formed but the named role does not appear
    in the authorized-role set of the endpoint being called, the request is refused
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.7: "Completing the visit is the largest single operation in this
    specification. It carries `performed_service_line_ids`, the ids of the lines
    actually carried out; every id must belong to this appointment and be `PLANNED`,
    else `ERR_SERVICE_LINE_NOT_FOUND`."

    Design: Corner/rbac/corner_dispatcher_cannot_complete_an_appointment
    """
    world = setup_reference(with_sku=False)
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    appointment, lines = setup_in_progress_visit(
        world, limbs=("LF",), service_type="TRIM", scheduled_date="2026-05-06"
    )
    assert appointment["status"] == "IN_PROGRESS"

    response = api.complete_appointment(
        appointment["id"],
        {"performed_service_line_ids": [lines[0]["id"]]},
        dispatcher,
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert response.status_code == 403
    assert read_appointment(appointment["id"])["status"] == "IN_PROGRESS"


def test_client_user_cannot_cancel_another_clients_appointment(api):
    """PRD §2.1: "When `X-User-Role` is `ClientUser`, `X-User-ID` is the `id` of the
    acting `Client` row; ownership checks compare the resource's owning client —
    directly for a `Client`, through `client_id` for a `Horse`, through the horse
    for an `Appointment`, and through `client_id` for an `Invoice` — to
    `X-User-ID`."
    PRD §2.1: "A mismatch is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403), and
    this ownership rung sits immediately below the role check and above every
    existence check."

    Design: Corner/rbac/corner_client_user_cannot_cancel_another_clients_appointment
    """
    barn = create_barn()
    owner = create_client(barn["id"], display_name="Aoi Tanaka")
    stranger = create_client(barn["id"], display_name="Ben Ito")
    horse = create_horse(owner["id"], barn["id"])
    appointment = create_appointment(horse["id"], "2026-05-13")

    response = api.cancel_appointment(
        appointment["id"], make_client_headers(stranger["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert response.status_code == 403
    assert read_appointment(appointment["id"])["status"] == "UNROUTED"


def test_version_increments_by_one_on_every_mutation(api, admin):
    """PRD §2.4: "All but one entity additionally carry `updated_at` (same format as
    `created_at`, refreshed on every mutation of that row) and `version`, an integer
    that starts at 1 when the row is minted and increases by exactly 1 on every
    mutation of that row."
    PRD §3.1: "An owner or administrator may amend a horse in flight, supplying any
    of `routine_cycle_weeks`, `requires_sedation` and `shoe_size_code`; each
    supplied field replaces the stored one, omitted fields are left alone, and the
    horse's `version` increments by 1."

    Design: Corner/cross_cutting_layers/corner_version_increments_by_one_on_every_mutation
    """
    barn = create_barn()
    client = create_client(barn["id"])
    horse = create_horse(client["id"], barn["id"])
    assert horse["version"] == 1

    first = validate_success(
        api.patch_horse(horse["id"], {"routine_cycle_weeks": 7}, admin)
    )
    second = validate_success(
        api.patch_horse(horse["id"], {"requires_sedation": True}, admin)
    )

    assert first["version"] == 2
    assert second["version"] == 3
    assert second["routine_cycle_weeks"] == 7, "the earlier amendment is left alone"
    assert second["requires_sedation"] is True
    assert_same_instant(
        second["created_at"], horse["created_at"], "created_at must not move"
    )
