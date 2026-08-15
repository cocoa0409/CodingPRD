"""Envelope shape, common resource properties, and basic creation/readback rules."""
import pytest

from test_helpers import (
    MECH,
    NON_EXISTENT_UUID,
    SCHED,
    TEST_DEFAULTS,
    assert_agreement,
    assert_excursion,
    create_active_agreement,
    create_agreement_payload,
    create_draft_excursion,
    create_open_slot,
    create_slot_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_rolling_stock_payload


def test_excursion_created_with_defaults_and_computed_service_date(api, scheduler_headers):
    """PRD §3.3: "The excursion copies its `service_date` from the slot, starts life
    in `DRAFT`, and is born with a companion: exactly one provisioning manifest per
    excursion, auto-created in `DRAFT` with zeroed counts, addressed through the excursion."
    PRD §3.6: "An excursion's `cancel_reason` stays null for its whole life until the
    moment it is cancelled".
    PRD §3.4: "Each is the sum of `effective_capacity` over the consist's assignments
    of that class minus the party sizes of that class's bookings in `CONFIRMED` or
    `CHECKED_IN` status." (empty consist -> 0)

    Design: Corner/entities/excursion_created_with_defaults_and_computed_service_date
    """
    agreement = create_active_agreement()
    slot = create_open_slot(agreement["id"])

    res = api.create_excursion(
        {"title": "Fall Colors", "slot_id": slot["id"], "event_type": "REGULAR",
         "surge_multiplier_bp": 10000},
        scheduler_headers)
    excursion = validate_success(res, 201)
    assert_excursion(excursion)
    assert excursion["status"] == "DRAFT", "excursion starts life in DRAFT"
    assert excursion["version"] == 1, "version starts at 1"
    assert excursion["service_date"] == TEST_DEFAULTS["SERVICE_DATE"], (
        "service_date copied from the slot")
    assert excursion["cancel_reason"] is None, "cancel_reason null until cancelled"
    assert excursion["coach_seats_available"] == 0, "no cars assigned yet -> 0 seats"
    assert excursion["first_class_seats_available"] == 0
    assert excursion["dining_seats_available"] == 0


def test_create_slot_missing_required_field_returns_invalid_request(api, scheduler_headers):
    """PRD §3.1: "A `Scheduler` carves out a slot by supplying the `agreement_id`, a
    `service_date`, and the half-open window from `start_minute` to `end_minute`."
    PRD §3.5: "getting that conditional wrong is `ERR_VALIDATION`, as is any malformed
    body, missing required field, invalid enum value, or unknown `event_type`."
    PRD §5: `ERR_VALIDATION` -> 400 Bad Request.

    Design: Corner/entities/create_slot_missing_required_field_returns_invalid_request
    """
    agreement = create_active_agreement()
    payload = create_slot_payload(agreement["id"])
    del payload["end_minute"]

    res = api.create_slot(payload, scheduler_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_create_agreement_system_fields_input_ignored(api, scheduler_headers):
    """PRD §2.4: "`id` is a server-minted UUID with no type prefix; it serves identity
    only and is never an input to any business decision."
    PRD §3.1: "A new agreement is born in `DRAFT` with `version` 1."

    Design: Corner/entities/create_agreement_system_fields_input_ignored
    """
    res = api.create_agreement(create_agreement_payload(), scheduler_headers)
    agreement = validate_success(res, 201)
    assert_agreement(agreement)
    assert is_valid_uuid(agreement["id"]), "server mints its own UUID id"
    assert agreement["version"] == 1, "version starts at 1 at creation"
    assert agreement["status"] == "DRAFT"


def test_create_stock_invalid_enum_value_rejected(api, mechanic_headers):
    """PRD §3.2: "Rostering a unit takes a `unit_code` that must be unique across all
    rolling stock (roster codes look like LOC-301 or CAR-DINING-2), a `stock_type` of
    `LOCOMOTIVE`, `COACH_CAR`, `FIRST_CLASS_CAR`, or `DINING_CAR`, a `seat_capacity`,
    and a `table_count`."
    PRD §3.5: "getting that conditional wrong is `ERR_VALIDATION`, as is any malformed
    body, missing required field, invalid enum value, or unknown `event_type`."

    Design: Corner/entities/create_stock_invalid_enum_value_rejected
    """
    payload = create_rolling_stock_payload(unit_code="TENDER-1", stock_type="TENDER",
                                           seat_capacity=0, table_count=0)
    res = api.create_rolling_stock(payload, mechanic_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_get_nonexistent_excursion_returns_not_found(api, scheduler_headers):
    """PRD §2.9: "resource identifiers in the URL are validated left to right; the
    first identifier that does not resolve to an existing resource yields
    `ERR_NOT_FOUND` (HTTP 404) before anything deeper is examined."

    Design: Corner/entities/get_nonexistent_excursion_returns_not_found
    """
    res = api.get_excursion(NON_EXISTENT_UUID, scheduler_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_bookings_list_pagination_envelope_defaults(api, station_agent_headers):
    """PRD §2.3: "`limit` caps the number of returned items: it defaults to 10, with a
    minimum of 1 and a maximum of 100. `offset` skips that many items from the front of
    the result set and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either \"object\" for a single resource or
    \"array\" for a list of resources."

    Design: Corner/entities/bookings_list_pagination_envelope_defaults
    """
    res = api.list_bookings(station_agent_headers)
    data, meta = validate_paginated(res)
    body = res.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert data == [], "empty database -> empty list"
    assert meta["limit"] == 10, "limit defaults to 10"
    assert meta["offset"] == 0, "offset defaults to 0"
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
