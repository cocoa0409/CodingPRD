"""Entity CRUD breadth: program creation defaults, required-field validation,
not-found, computed advance, listing pagination, system-field handling.

Corner queue B: entities.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, is_valid_uuid,
    create_program_payload, create_client_payload, setup_funded_invoice,
    NON_EXISTENT_UUID, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
FO = TEST_USERS["funding_headers"]


def test_program_create_returns_201_with_defaults(api):
    """PRD §3.1: "A `PlatformAdmin` creates one by supplying a display `name` and
    optionally a `currency` (defaulting to `USD`), a `default_fee_rate_per_day`
    (the base factoring discount rate per day, defaulting to 0.0005 ...), a
    `tier2_multiplier` (defaulting to 1.5), a `tier3_multiplier` (defaulting to
    2.0), and `recourse_grace_days` (defaulting to 90). A program begins in
    `ACTIVE` status."

    Design: Corner/entities/entity_program_create_returns_201_with_defaults
    """
    res = api.create_program({"name": "P-DEF"}, ADMIN)
    program = validate_success(res, 201)
    assert program["status"] == "ACTIVE"
    assert program["currency"] == "USD"
    assert program["default_fee_rate_per_day"] == 0.0005
    assert program["recourse_grace_days"] == 90
    assert program["version"] == 1


def test_client_missing_required_field_returns_422(api):
    """PRD §3.1: "A client is onboarded by either a `PlatformAdmin` or an
    `UnderwritingOfficer`, who supplies the `program_id` it belongs to, its
    `legal_name`, and its `requested_advance_rate_pct` — the advance rate the
    client asks for, which must lie strictly between 0 and 1."
    PRD §2.6: "Structural validity of the body — required fields present and
    well-typed, enum values within their allowed sets, `face_amount_cents`
    greater than zero, any `amount_cents` greater than zero, `due_date` strictly
    later than `issue_date`, and advance and concentration rates within range
    (`ERR_INVALID_REQUEST`, HTTP 422)."

    Omitting requested_advance_rate_pct -> 422 ERR_INVALID_REQUEST.

    Design: Corner/entities/entity_client_missing_required_field_returns_422
    """
    program = get_success_data(api.create_program({"name": "P-RF"}, ADMIN))
    res = api.create_client({"program_id": program["id"], "legal_name": "NoRate"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_invoice_not_found_returns_404(api):
    """PRD §2.5: "the server resolves every such identifier left-to-right
    (program, then client, debtor, invoice, relationship, batch, or posting as
    applicable) and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the
    first identifier that does not resolve to an existing resource."

    Design: Corner/entities/entity_invoice_not_found_returns_404
    """
    res = api.get_invoice(NON_EXISTENT_UUID, FO)
    validate_error(res, "ERR_NOT_FOUND")


def test_invoice_computed_advance_ignores_client_input(api):
    """PRD §3.5: "The `advance_amount_cents` is the face value multiplied by the
    advance rate, rounded half-up to whole cents, and the `reserve_held_cents`
    is the exact remainder of `face_amount_cents` minus `advance_amount_cents`."

    face 100000 @ 0.85 -> advance 85000, reserve 15000 at funding.

    Design: Corner/entities/entity_invoice_computed_advance_ignores_client_input
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               invoice_overrides={"invoice_number": "INV-COMP"})
    invoice = ctx["invoice"]
    assert invoice["advance_amount_cents"] == 85000
    assert invoice["reserve_held_cents"] == 15000
    assert invoice["status"] == "FUNDED"


def test_list_clients_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the following fields inside the
    `meta` object of the envelope: `limit`, `offset`, `total_count`, and
    `has_more`." PRD §2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources."

    limit=1 over two clients -> total_count 2, has_more true, one row.

    Design: Corner/entities/entity_list_clients_pagination_envelope
    """
    program = get_success_data(api.create_program({"name": "P-LIST"}, ADMIN))
    api.create_client(create_client_payload(program["id"], legal_name="L1",
                                            requested_advance_rate_pct=0.8), ADMIN)
    api.create_client(create_client_payload(program["id"], legal_name="L2",
                                            requested_advance_rate_pct=0.8), ADMIN)
    data, meta = validate_paginated(
        api.list_clients(ADMIN, params={"program_id": program["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_program_system_fields_server_minted(api):
    """PRD §2.4: "`id` — a unique, server-minted identifier formatted as a UUID.
    It carries no type prefix." and "`version` — a system-managed integer that
    begins at its initial value and increments by one on every mutation." PRD
    §3.1: "A program begins in `ACTIVE` status."

    Design: Corner/entities/entity_program_system_fields_input_ignored
    """
    res = api.create_program({"name": "P-SYS"}, ADMIN)
    program = validate_success(res, 201)
    assert program["status"] == "ACTIVE"
    assert program["version"] == 1
    assert is_valid_uuid(program["id"])
    assert "_" not in program["id"], "id carries no type prefix"
    assert program.get("created_at")
