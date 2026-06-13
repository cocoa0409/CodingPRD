"""Catalog CRUD, defaults, listing, pagination, and role-based access control.

Traces queue-B corner instances in the `entities`, `endpoints`, and `rbac`
sections, plus the RBAC negative for the clock/operator surface.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    api_client,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_passenger_headers,
    assert_operator,
    assert_settlement_note,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


# ─── entities ─────────────────────────────────────────
def test_create_operator_applies_policy_defaults(api):
    """PRD §3.1: "Each operator also configures two policy values used much later
    in the lifecycle: `default_connection_buffer_min`, the minimum number of minutes
    that must elapse between an inbound leg's arrival and the next leg's departure
    on a multi-leg booking (at least 0, defaulting to 30), and `exchange_fee_cents`,
    the flat fee charged when a passenger exchanges a leg (at least 0, defaulting to
    1000). An operator begins at `version` 1."

    Design: Corner/entities/create_operator_returns_201_with_defaults
    """
    resp = api.create_operator(
        f.create_operator_payload(name="Coastliner", mode="RAIL"),
        TEST_USERS["schedule_manager_headers"],
    )
    data = validate_success(resp, 201)
    assert_operator(data)
    assert data["default_connection_buffer_min"] == 30
    assert data["exchange_fee_cents"] == 1000
    assert data["version"] == 1


def test_create_operator_missing_mode_rejected(api):
    """PRD §3.1: "creating an **Operator** — a carrier identified by its `name` and
    its transport `mode`, which is either `RAIL` or `BUS`".
    PRD §2.11: "the request body is well-formed — field types and enums are valid,
    required fields are present ... — else `ERR_INVALID_REQUEST`".

    Design: Corner/entities/create_operator_missing_mode_returns_invalid_request
    """
    resp = api.create_operator({"name": "NoMode"}, TEST_USERS["schedule_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_get_operator_not_found(api):
    """PRD §2.5: "The system validates every referenced resource left-to-right ...
    and rejects the request with `ERR_NOT_FOUND` at the first identifier that does
    not resolve to an existing resource."

    Design: Corner/entities/get_operator_not_found_returns_404
    """
    resp = api.get_operator(NON_EXISTENT_UUID, TEST_USERS["schedule_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_passenger_duplicate_email_rejected(api):
    """PRD §3.12: "A **Passenger** registers with a `full_name`, an `email` that must
    be unique among passengers (a repeat raises `ERR_DUPLICATE_EMAIL`)".

    Design: Corner/entities/passenger_duplicate_email_rejected
    """
    fx.create_passenger(full_name="First", email="dup@x.com")
    resp = api.create_passenger(
        f.create_passenger_payload(full_name="Second", email="dup@x.com"),
        TEST_USERS["passenger_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value, 409)


def test_service_date_system_fields_server_set(api):
    """PRD §3.2: "On creation its seat counters are initialized, its `lifecycle` is
    `SCHEDULED`, its `sales` gate is `OPEN`, and its `version` is 1."
    PRD §2.6: "The available count, `seats_available`, is the physical capacity
    `seats_total` minus `seats_held` minus `seats_sold`".

    Design: Corner/entities/service_date_system_fields_generated_input_ignored
    """
    cat = fx.setup_catalog(set_clock_first=False)
    resp = api.create_service_date(
        f.create_service_date_payload(cat["route"]["id"], seats_total=40, base_fare_cents=4000),
        TEST_USERS["schedule_manager_headers"],
    )
    data = validate_success(resp, 201)
    assert data["seats_held"] == 0
    assert data["seats_sold"] == 0
    assert data["seats_available"] == 40
    assert data["lifecycle"] == "SCHEDULED"
    assert data["sales"] == "OPEN"
    assert data["version"] == 1


def test_settlement_note_is_immutable_with_no_version_field(api):
    """PRD §2.4: "A settlement note (the refund/credit document described in §3) is
    append-only and immutable once written: it carries `id` and `created_at` but
    has neither `updated_at` nor `version`."

    Design: Corner/entities/refund_credit_note_is_immutable_no_version_field
    """
    cat = fx.setup_paid_booking(refundable=True)
    passenger = cat["passenger"]
    booking = cat["booking"]
    get_success_data(
        api.cancel_booking(booking["id"], f.cancel_payload("CASH"), make_passenger_headers(passenger["id"]))
    )
    resp = api.list_settlement_notes(
        make_passenger_headers(passenger["id"]), params={"booking_id": booking["id"]}
    )
    notes, _ = validate_paginated(resp)
    assert len(notes) == 1, f"expected exactly one settlement note, got {len(notes)}"
    note = notes[0]
    assert_settlement_note(note)
    assert "version" not in note, "settlement note must NOT carry a version field"
    assert "updated_at" not in note, "settlement note must NOT carry an updated_at field"


# ─── endpoints (listing + pagination) ─────────────────
def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100 ... A `limit` or `offset` outside
    its allowed bounds is rejected with `ERR_VALIDATION_PAGINATION`."

    Design: Corner/endpoints/pagination_out_of_bounds_rejected
    """
    fx.set_clock()
    fx.create_operator()
    resp = api.list_routes(TEST_USERS["schedule_manager_headers"], params={"limit": 101})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION.value, 422)


def test_list_routes_filtered_by_operator(api):
    """PRD §2.5: "List endpoints support reverse-reachability filtering so that
    children can be located from a parent ... routes by `operator_id`".
    PRD §2.3: "The `meta` object of every list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/list_routes_filtered_by_operator
    """
    operator = fx.create_operator()
    get_success_data(
        api.create_route(f.create_route_payload(operator["id"]), TEST_USERS["schedule_manager_headers"])
    )
    get_success_data(
        api.create_route(
            f.create_route_payload(operator["id"], origin_code="BOS", destination_code="NYP",
                                   depart_minute_of_day=600, arrive_minute_of_day=840),
            TEST_USERS["schedule_manager_headers"],
        )
    )
    resp = api.list_routes(TEST_USERS["schedule_manager_headers"], params={"operator_id": operator["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 routes for the operator, got {len(data)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ─── rbac ─────────────────────────────────────────────
def test_passenger_cannot_create_operator(api):
    """PRD §2.1: "When both headers are present but the declared role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §4: the create-operator endpoint authorizes only `ScheduleManager`.

    Design: Corner/rbac/passenger_cannot_create_operator
    """
    passenger = fx.create_passenger()
    resp = api.create_operator(
        f.create_operator_payload(name="Sneaky", mode="BUS"),
        make_passenger_headers(passenger["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_gate_agent_cannot_grant_accessibility(api):
    """PRD §2.1: "When both headers are present but the declared role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §4: the grant-accessibility endpoint authorizes only `SupportAgent`.

    Design: Corner/rbac/gate_agent_cannot_grant_accessibility
    """
    cat = fx.setup_catalog()
    passenger = fx.create_passenger()
    booking = fx.hold_booking(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    leg = fx.legs_for_booking(booking["id"], passenger["id"])[0]
    ar = get_success_data(
        api.create_accessibility_request(
            leg["id"], f.accessibility_payload("SERVICE_ANIMAL"), make_passenger_headers(passenger["id"])
        )
    )
    resp = api.grant_accessibility_request(ar["id"], TEST_USERS["gate_agent_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    after = get_success_data(api.get_accessibility_request(ar["id"], TEST_USERS["support_agent_headers"]))
    assert after["status"] == "REQUESTED"


def test_passenger_cannot_confirm_other_passengers_booking(api):
    """PRD §2.1: "A passenger-scoped mutation on a booking, pass, or baggage item that
    the acting passenger does not own is rejected with `ERR_NOT_OWNER`."

    Design: Corner/rbac/passenger_cannot_confirm_other_passengers_booking
    """
    cat = fx.setup_catalog()
    passenger_a = fx.create_passenger(full_name="A", email="a@x.com")
    passenger_b = fx.create_passenger(full_name="B", email="b@x.com")
    booking = fx.hold_booking(passenger_a["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    sd_v = fx.current_sd_version(cat["service_date"]["id"])
    resp = api.confirm_booking(booking["id"], f.confirm_payload(sd_v), make_passenger_headers(passenger_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value, 403)
    after = get_success_data(api.get_booking(booking["id"], make_passenger_headers(passenger_a["id"])))
    assert after["booking_status"] == "HELD"


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, declaring the operational capacity under which
    the request is made. A request missing either header is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api._request("GET", f"/v1/operators/{NON_EXISTENT_UUID}", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
