"""Temporal-overlap rules: half-open statute windows (adjacency allowed) versus
closed parcel service windows (adjacency rejected)."""
from test_helpers import (
    ApiErrorId,
    create_jurisdiction,
    create_search_order,
    create_search_order_payload,
    create_statute,
    make_provider_admin_headers,
    make_title_agent_headers,
    set_clock,
    setup_config_a,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_provider_admin_headers()
AGENT = make_title_agent_headers("agent_1")
AGENT2 = make_title_agent_headers("agent_2")


def test_overlapping_statute_window_rejected(api):
    """PRD 2.9: "Each window carries an inclusive `effective_from` and an
    exclusive `effective_to`, so coverage is half-open: a window covers a date
    when the date is on or after `effective_from` and strictly before
    `effective_to`, and a null `effective_to` makes the window open-ended.
    Windows of one jurisdiction must never overlap; a new window whose
    `effective_from` equals an existing window's `effective_to` is adjacent,
    not overlapping, and is allowed, while any true overlap is rejected with
    `ERR_STATUTE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/statute_window_overlap_half_open_adjacency
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    create_statute(
        jurisdiction["id"], effective_from="2026-01-01", effective_to="2026-07-01"
    )
    # [2026-06-01, 2026-09-01) truly overlaps [2026-01-01, 2026-07-01).
    response = api.create_statute(
        {
            "jurisdiction_id": jurisdiction["id"],
            "effective_from": "2026-06-01",
            "effective_to": "2026-09-01",
            "estoppel_response_days": 12,
            "estoppel_fee_cap_cents": 15000,
            "estoppel_validity_days": 45,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_STATUTE_WINDOW_OVERLAP.value)
    assert response.status_code == 422


def test_adjacent_statute_window_accepted(api):
    """PRD 2.9: "Windows of one jurisdiction must never overlap; a new window
    whose `effective_from` equals an existing window's `effective_to` is
    adjacent, not overlapping, and is allowed, while any true overlap is
    rejected with `ERR_STATUTE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/statute_window_overlap_half_open_adjacency
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    create_statute(
        jurisdiction["id"], effective_from="2026-01-01", effective_to="2026-07-01"
    )
    # new.effective_from == old.effective_to: adjacency, not overlap.
    adjacent = create_statute(
        jurisdiction["id"],
        effective_from="2026-07-01",
        effective_to=None,
        estoppel_response_days=12,
        estoppel_fee_cap_cents=15000,
        estoppel_validity_days=45,
    )
    assert adjacent["effective_from"] == "2026-07-01"

    statutes, meta = validate_paginated(
        api.list_jurisdiction_statutes(jurisdiction["id"], ADMIN)
    )
    assert len(statutes) == 2
    assert meta["total_count"] == 2


def test_parcel_reorder_on_closing_day_conflicts(api):
    """PRD 3.2: "A new order conflicts — and is rejected with
    `ERR_DUPLICATE_ACTIVE_SEARCH` — when the existing order's creation date
    falls on or before the requested `closing_date` and the current clock date
    falls on or before the existing order's `closing_date`. Because the
    interval is closed at both ends, a new order created exactly on the existing
    order's closing date still conflicts; adjacency is not an escape."

    Design: Difficulty/resource_temporal_overlap/parcel_service_window_closed_interval_adjacency_rejected
    """
    set_clock()
    first = create_search_order("P-900", property_address="9 Z St",
                                closing_date="2026-08-20")
    assert first["status"] == "INTAKE"

    # Created exactly on the first order's closing date: still conflicts.
    set_clock("2026-08-20T09:00:00Z")
    response = api.create_search_order(
        create_search_order_payload(
            "P-900", property_address="9 Z St", closing_date="2026-09-15"
        ),
        AGENT2,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ACTIVE_SEARCH.value)
    assert response.status_code == 409


def test_parcel_reorder_after_window_passes_accepted(api):
    """PRD 3.2: "A new order conflicts — and is rejected with
    `ERR_DUPLICATE_ACTIVE_SEARCH` — when the existing order's creation date
    falls on or before the requested `closing_date` and the current clock date
    falls on or before the existing order's `closing_date`. Because the
    interval is closed at both ends, a new order created exactly on the existing
    order's closing date still conflicts; adjacency is not an escape.
    Cancelling the existing order frees the parcel immediately."

    Design: Difficulty/resource_temporal_overlap/parcel_service_window_closed_interval_adjacency_rejected
    """
    set_clock()
    create_search_order("P-900", property_address="9 Z St",
                        closing_date="2026-08-20")

    # One day past the existing order's closing date the window has fully
    # passed, so the parcel is free again.
    set_clock("2026-08-21T09:00:00Z")
    response = api.create_search_order(
        create_search_order_payload(
            "P-900", property_address="9 Z St", closing_date="2026-09-15"
        ),
        AGENT2,
    )
    order = validate_success(response, 201)
    assert order["parcel_number"] == "P-900"
    assert order["status"] == "INTAKE"
