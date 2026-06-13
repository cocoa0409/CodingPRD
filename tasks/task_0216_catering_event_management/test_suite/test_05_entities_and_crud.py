"""Entity CRUD and field-contract tests: creation defaults, retrieval, listing, not-found,
required-field and enum validation, system-minted fields, append-only ledger shape, FK
existence, and the order window validation.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_client_headers,
    create_order_payload,
    create_add_on_payload,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


def test_create_client_returns_201_with_defaults(api):
    """PRD §3.2: "Registration also accepts two optional flags: `tax_exempt`, which defaults to
    false ... and `gratuity_policy`, one of `INCLUDED` or `OPTIONAL`, defaulting to `INCLUDED`".
    PRD §2.4: "The `version` is an integer that starts at 1".

    Design: Corner/entities/create_client_returns_201_with_all_fields
    """
    client = validate_success(
        api.create_client({"company_name": "Acme", "billing_email": "a@x.com"}, ADMIN),
        expected_status=201,
    )
    assert client["status"] == "ACTIVE"
    assert client["tax_exempt"] is False
    assert client["gratuity_policy"] == "INCLUDED"
    assert client["version"] == 1


def test_get_order_returns_stored_dimensions(api):
    """PRD §2.10: "An `Order` carries two independent state dimensions ... beginning at `DRAFT`
    ... beginning at `UNBILLED`".

    Design: Corner/entities/get_order_returns_stored_entity
    """
    ctx = fx.create_draft_order(booked_headcount=80)
    fetched = validate_success(api.get_order(ctx["order"]["id"], COORD))
    assert fetched["lifecycle_status"] == "DRAFT"
    assert fetched["settlement_status"] == "UNBILLED"


def test_list_packages_returns_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope."

    Design: Corner/entities/list_packages_returns_paginated_envelope
    """
    fx.create_package(name="Gala", per_head_cents=5000, min_headcount=1, lead_time_hours=24)
    fx.create_package(name="Brunch", per_head_cents=3000, min_headcount=1, lead_time_hours=12)
    data, meta = validate_paginated(api.list_packages(COORD))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_get_nonexistent_order_returns_not_found(api):
    """PRD §2.6: "a path or body foreign key that does not resolve yields `ERR_NOT_FOUND`".

    Design: Corner/entities/get_order_nonexistent_returns_not_found
    """
    validate_error(api.get_order(NON_EXISTENT_UUID, COORD), ApiErrorId.ERR_NOT_FOUND.value)


def test_create_order_missing_booked_headcount_rejected(api):
    """PRD §3.12: "request-body well-formedness — required fields present with correct types and
    valid enum membership (`ERR_INVALID_REQUEST`)".
    PRD §3.2: "the `booked_headcount` (the guest count at booking, which must be at least the
    package's `min_headcount`)".

    Design: Corner/entities/create_order_missing_required_field_returns_invalid_request
    """
    cat = fx.setup_catalog()
    headers = make_client_headers(cat["client"]["id"])
    payload = {
        "client_id": cat["client"]["id"], "package_id": cat["package"]["id"],
        "venue_id": cat["venue"]["id"],
        "event_start": "2026-09-01T17:00:00Z", "event_end": "2026-09-01T22:00:00Z",
    }
    validate_error(api.create_order(payload, headers), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_client_tax_exempt_defaults_false_when_omitted(api):
    """PRD §3.2: "`tax_exempt`, which defaults to false".

    Design: Corner/entities/client_tax_exempt_default_applied_when_omitted
    """
    client = validate_success(
        api.create_client({"company_name": "Beta", "billing_email": "b@x.com"}, ADMIN),
        expected_status=201,
    )
    assert client["tax_exempt"] is False


def test_order_id_and_version_system_generated(api):
    """PRD §2.4: "The `id` is a server-minted UUID with no type prefix; it is identity only and
    is never an input to a business decision ... The `version` is an integer that starts at 1".

    Design: Corner/entities/order_id_and_version_are_system_generated_input_ignored
    """
    from test_helpers import is_valid_uuid
    ctx = fx.create_draft_order(booked_headcount=80)
    order = ctx["order"]
    assert is_valid_uuid(order["id"])
    assert order["version"] == 1
    assert order["lifecycle_status"] == "DRAFT"


def test_add_on_invalid_kind_enum_rejected(api):
    """PRD §3.3: "Each line declares a `kind` — one of `DELIVERY`, `SETUP`, or `STAFFING`".
    PRD §3.12: "valid enum membership (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/add_on_invalid_kind_enum_returns_invalid_request
    """
    ctx = fx.create_draft_order(booked_headcount=80)
    validate_error(
        api.create_add_on(ctx["order"]["id"],
                          {"kind": "CATERING", "unit_cents": 5000, "quantity": 1},
                          ctx["client_headers"]),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


def test_ledger_entry_has_no_version_field(api):
    """PRD §2.4: "A `DepositLedgerEntry` has no `updated_at` and no `version`, because it is
    never modified after it is written."

    Design: Corner/entities/ledger_entry_immutable_no_version_field
    """
    ctx = fx.setup_confirmed_order(clock="2026-06-01T00:00:00Z", booked_headcount=80)
    entries, _ = validate_paginated(api.list_order_ledger(ctx["order"]["id"], COORD))
    holds = [e for e in entries if e["entry_type"] == "DEPOSIT_HOLD"]
    assert len(holds) == 1
    for entry in entries:
        assert "id" in entry and "created_at" in entry
        assert "version" not in entry, "append-only ledger entry must not carry version"


def test_create_order_with_nonexistent_package_returns_not_found(api):
    """PRD §2.6: "For any endpoint whose path carries a resource identifier, the system validates
    that identifier's existence before applying business rules; a path or body foreign key that
    does not resolve yields `ERR_NOT_FOUND`".

    Design: Corner/entities/create_order_with_nonexistent_package_returns_not_found
    """
    venue = fx.create_venue()
    client = fx.create_client()
    headers = make_client_headers(client["id"])
    validate_error(
        api.create_order(
            create_order_payload(client["id"], NON_EXISTENT_UUID, venue["id"], booked_headcount=80),
            headers,
        ),
        ApiErrorId.ERR_NOT_FOUND.value,
    )


def test_order_event_end_before_start_rejected(api):
    """PRD §3.2: "The `event_end` must fall strictly after `event_start`; an order whose
    `event_end` is at or before `event_start` is rejected with `ERR_VALIDATION_WINDOW`".

    Design: Corner/entities/order_event_end_before_start_returns_validation_window
    """
    cat = fx.setup_catalog()
    headers = make_client_headers(cat["client"]["id"])
    validate_error(
        api.create_order(
            create_order_payload(cat["client"]["id"], cat["package"]["id"], cat["venue"]["id"],
                                 booked_headcount=80,
                                 event_start="2026-09-01T22:00:00Z", event_end="2026-09-01T17:00:00Z"),
            headers,
        ),
        ApiErrorId.ERR_VALIDATION_WINDOW.value,
    )
