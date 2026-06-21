"""Registration, exchange creation, relinquished/trust setup, RBAC, listing.

Translates corner-design instances from sections: entities, endpoints, rbac,
state_machines (initial state), and the auth validation.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_exchanger_payload, create_exchange_payload,
    create_relinquished_property_payload,
    make_qi_coordinator_headers, make_settlement_officer_headers,
    assert_exchanger, assert_exchange,
    create_exchanger, create_exchange,
)


COORD = make_qi_coordinator_headers("coord-1")
OFFICER = make_settlement_officer_headers("officer-1")


def test_register_exchanger_returns_201_with_system_fields(api):
    """PRD §3.1: "A `QICoordinator` registers an **exchanger** by supplying a
    `legal_name`, a `taxpayer_id`, and an `email`."
    PRD §2.4: "`version` (integer): a counter starting at 1 that increments by one
    on every modification of the resource."

    Design: Corner/entities/create_exchanger_returns_201_with_system_fields
    """
    resp = api.create_exchanger(
        create_exchanger_payload(legal_name="Alice Doe", taxpayer_id="TP-C-100"), COORD
    )
    data = validate_success(resp, expected_status=201)
    assert_exchanger(data)
    assert data["legal_name"] == "Alice Doe", "legal_name must echo input"
    assert data["version"] == 1, f"new exchanger version must be 1, got {data['version']}"


def test_get_exchange_not_found_returns_404(api):
    """PRD §2.5: "the server validates them strictly left to right and rejects the
    request with `ERR_NOT_FOUND` at the *first* identifier that does not resolve to a
    stored entity."

    Design: Corner/entities/get_exchange_not_found_returns_404
    """
    resp = api.get_exchange(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_exchange_missing_exchange_type_rejected(api):
    """PRD §2.10: "then request-body well-formedness — required fields present and
    correctly typed, enums within their declared sets, and numeric bounds satisfied
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_exchange_missing_exchange_type_returns_invalid_request
    """
    exr = create_exchanger("coord-req")
    resp = api.create_exchange({"exchanger_id": exr["id"]}, make_qi_coordinator_headers("coord-req"))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_exchange_bad_exchange_type_enum_rejected(api):
    """PRD §3.1: "the coordinator opens an **exchange** by naming the taxpayer through
    `exchanger_id` and choosing an `exchange_type` of `FORWARD`, `REVERSE`, or
    `IMPROVEMENT`."
    PRD §2.10: "then request-body well-formedness — required fields present and
    correctly typed, enums within their declared sets, and numeric bounds satisfied
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_exchange_bad_exchange_type_enum_returns_invalid_request
    """
    exr = create_exchanger("coord-enm")
    resp = api.create_exchange(
        create_exchange_payload(exr["id"], "SIDEWAYS"), make_qi_coordinator_headers("coord-enm")
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_relinquished_property_nonpositive_fmv_rejected(api):
    """PRD §3.2: "The sale price `fair_market_value` must be strictly greater than
    zero; `selling_expenses`, `mortgage_payoff`, and `adjusted_basis` must each be
    zero or greater."

    Design: Corner/entities/relinquished_property_negative_fmv_returns_invalid_request
    """
    exr = create_exchanger("coord-neg")
    ex = create_exchange(exr["id"], "FORWARD", "coord-neg")
    resp = api.create_relinquished_property(
        ex["id"],
        {"address": "Z St", "fair_market_value": 0, "selling_expenses": 0,
         "mortgage_payoff": 0, "adjusted_basis": 0},
        make_qi_coordinator_headers("coord-neg"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_duplicate_taxpayer_id_rejected(api):
    """PRD §3.1: "an attempt to register a second exchanger with a `taxpayer_id`
    already in use is rejected with `ERR_DUPLICATE_TAXPAYER_ID`."

    Design: Corner/entities/duplicate_taxpayer_id_returns_conflict
    """
    api.create_exchanger(create_exchanger_payload(legal_name="Dup A", taxpayer_id="TP-DUP-1"), COORD)
    resp = api.create_exchanger(
        create_exchanger_payload(legal_name="Dup B", taxpayer_id="TP-DUP-1"), COORD
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAXPAYER_ID.value)


def test_second_trust_open_rejected(api):
    """PRD §3.2: "an attempt to open a second trust on an exchange that already has
    one is rejected with `ERR_TRUST_ALREADY_EXISTS`."

    Design: Corner/endpoints/second_trust_open_returns_already_exists
    """
    exr = create_exchanger("coord-t2")
    ex = create_exchange(exr["id"], "FORWARD", "coord-t2")
    headers = make_qi_coordinator_headers("coord-t2")
    validate_success(api.create_trust(ex["id"], headers), expected_status=201)
    resp = api.create_trust(ex["id"], headers)
    validate_error(resp, ApiErrorId.ERR_TRUST_ALREADY_EXISTS.value)


def test_new_exchange_starts_in_draft(api):
    """PRD §3.1: "The new exchange begins life in `DRAFT` status, and the opaque
    `X-User-ID` of the creating coordinator is captured as `coordinator_user_id` — the
    anchor for the later four-eyes control."

    Design: Corner/state_machines/new_exchange_starts_in_draft_posture_open_after_close
    """
    exr = create_exchanger("coord-ini")
    resp = api.create_exchange(
        create_exchange_payload(exr["id"], "FORWARD"), make_qi_coordinator_headers("coord-ini")
    )
    data = validate_success(resp, expected_status=201)
    assert_exchange(data)
    assert data["status"] == "DRAFT", f"new exchange status must be DRAFT, got {data['status']}"


def test_list_exchanges_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses surface four fields inside the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_exchanges_pagination_envelope
    """
    exr = create_exchanger("coord-lst")
    create_exchange(exr["id"], "FORWARD", "coord-lst")
    resp = api.list_exchanges(make_qi_coordinator_headers("coord-lst"), params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert "total_count" in meta, "meta must carry total_count"
    assert "has_more" in meta, "meta must carry has_more"


# ── RBAC ─────────────────────────────────────────────────────────────

def test_settlement_officer_cannot_create_exchange(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/settlement_officer_cannot_create_exchange
    """
    exr = create_exchanger("coord-rb")
    resp = api.create_exchange(create_exchange_payload(exr["id"], "FORWARD"), OFFICER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.create_exchange(
        {"exchanger_id": NON_EXISTENT_UUID, "exchange_type": "FORWARD"}, {}
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
