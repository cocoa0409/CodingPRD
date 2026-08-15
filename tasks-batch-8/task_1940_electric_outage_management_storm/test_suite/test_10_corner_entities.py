"""Corner tests — entities section.

Covers creation, defaults, required fields, type constraints, immutability,
not-found, and pagination envelope shape.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_outage,
    assert_trouble_signal,
    create_and_activate_event,
    create_feeder_record,
    create_outage_payload,
    create_priority_customer_payload,
    create_trouble_signal_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    set_clock,
    setup_event_with_feeder,
    validate_error,
    validate_paginated,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]
TG = TEST_USERS["telemetry_gateway_headers"]


def test_outage_create_success_initial_state_and_system_fields(api):
    """PRD §3.3: "a `Dispatcher` may file one manually with a payload
    containing the `storm_event_id` and `feeder_id`. Manual creation requires
    the event to be `ACTIVE` (`ERR_EVENT_NOT_ACTIVE`), and the new record
    starts in `SUSPECTED`."

    Design: Corner/entities/outage_create_success_initial_state_and_system_fields
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    assert_outage(ot)
    assert ot["outage_status"] == "SUSPECTED"
    assert ot["version"] == 1
    assert ot["current_etr"] is None
    assert ot["customers_affected"] is None
    assert ot["etr_missed"] is False
    assert ot["created_at"] == "2026-08-10T00:00:00.000Z"


def test_outage_create_missing_required_returns_invalid_request(api):
    """PRD §2.7: "any request whose body is malformed — a missing required
    field, an invalid enum value, or a violated numeric constraint — is
    rejected with `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/outage_create_missing_required_returns_invalid_request
    """
    ev, _fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    resp = api.create_outage({"storm_event_id": ev["id"]}, DISP)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert err["error_id"] == "ERR_INVALID_REQUEST"
    outages, meta = validate_paginated(
        api.list_outages(DISP, params={"storm_event_id": ev["id"]})
    )
    assert meta["total_count"] == 0


def test_feeder_threshold_defaults_applied(api):
    """PRD §3.1: "`cluster_signal_threshold`, the meter last-gasp count at or
    above which a cluster becomes an outage, defaults to 3, and
    `cluster_call_threshold`, the customer-call count with the same effect,
    defaults to 5".

    Design: Corner/entities/feeder_threshold_defaults_applied
    """
    set_clock("2026-08-10T00:00:00Z")
    fd = create_feeder_record(county_code="C9", customer_count=500)
    assert fd["cluster_signal_threshold"] == 3
    assert fd["cluster_call_threshold"] == 5


def test_priority_customer_invalid_enum_returns_invalid_request(api):
    """PRD §2.7: "any request whose body is malformed — a missing required
    field, an invalid enum value, or a violated numeric constraint — is
    rejected with `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/priority_customer_invalid_enum_returns_invalid_request
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    resp = api.create_priority_customer(
        create_priority_customer_payload(fd["id"], priority_class="VIP"), DISP
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert err["error_id"] == "ERR_INVALID_REQUEST"


def test_trouble_signal_immutable_event_entity_shape(api):
    """PRD §2.5: "Three record types are append-style and carry only `id` and
    `created_at` — both `updated_at` and `version` are absent from them:
    trouble signals, ETR revisions, and cost ledger entries."

    Design: Corner/entities/trouble_signal_immutable_event_entity_shape
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    sig = get_success_data(
        api.create_trouble_signal(
            create_trouble_signal_payload(
                fd["id"],
                signal_type="CUSTOMER_CALL",
                occurred_at="2026-08-10T00:00:00Z",
            ),
            TG,
        )
    )
    assert_trouble_signal(sig)
    assert sig["disposition"] == "UNCLUSTERED"


def test_outage_get_not_found_returns_404(api):
    """PRD §2.7: "Resource identifiers in the path are validated left to
    right ... and the request is rejected with `ERR_NOT_FOUND` (404) at the
    first identifier that does not correspond to an existing resource."

    Design: Corner/entities/outage_get_not_found_returns_404
    """
    set_clock("2026-08-10T00:00:00Z")
    resp = api.get_outage(NON_EXISTENT_UUID, DISP)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert err["error_id"] == "ERR_NOT_FOUND"


def test_storm_events_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; it defaults to 10 when omitted, with a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies how many items to skip
    and defaults to 0. ... Paginated list responses include `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    response envelope."

    Design: Corner/entities/storm_events_list_pagination_envelope
    """
    set_clock("2026-08-10T00:00:00Z")
    get_success_data(
        api.create_storm_event(
            {"event_name": "Storm C3", "event_type": "HURRICANE"}, ED
        )
    )
    data, meta = validate_paginated(api.list_storm_events(DISP))
    assert len(data) == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_nested_outage_under_terminal_parent_rejected(api):
    """PRD §3.3: "The parent must belong to the same storm event
    (`ERR_CROSS_EVENT_LINK`) and must not already be in `VERIFIED` or
    `CANCELLED` (`ERR_PARENT_OUTAGE_TERMINAL`); root outages leave
    `parent_outage_id` null."

    Design: Corner/entities/nested_outage_under_terminal_parent_rejected
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    parent = get_success_data(
        api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
    )
    get_success_data(api.cancel_outage(parent["id"], DISP))
    resp = api.create_outage(
        create_outage_payload(ev["id"], fd["id"], parent_outage_id=parent["id"]),
        DISP,
    )
    err = validate_error(resp, ApiErrorId.ERR_PARENT_OUTAGE_TERMINAL)
    assert err["error_id"] == "ERR_PARENT_OUTAGE_TERMINAL"
