"""Onboarding defaults, response envelope, pagination, and 404 reference resolution."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_client_account,
    create_client,
    create_client_account_payload,
    create_filing_request_payload,
    is_valid_uuid,
    register_debtor,
    register_secured_party,
    seed_jurisdiction_profile,
    setup_client_world,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_create_client_account_returns_defaults(api):
    """PRD §3.1: "A new account's `status` starts at `ACTIVE` and its fee ledger at zero."
    PRD §2.7: "Each client account carries a two-column fee ledger that starts at zero
    when the account is created."
    PRD §4: "Operations that create a new resource — a client account, a jurisdiction
    profile, a debtor, a secured party, a filing request, a filing attempt, a lien
    search, or a perfection report — return `201 Created`."

    Design: Corner/entities/create_client_returns_defaults
    """
    resp = api.create_client_account(create_client_account_payload(name="Acme Lending"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_client_account(data)
    assert data["status"] == "ACTIVE", f"new account must start ACTIVE, got {data['status']}"
    assert data["fees_charged_total_cents"] == 0, "fee ledger must start at zero"
    assert data["fees_refunded_total_cents"] == 0, "fee ledger must start at zero"
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"


def test_create_client_ignores_client_supplied_system_fields(api):
    """PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."
    PRD §2.4: "At startup the clock reads exactly `2026-08-01T00:00:00Z`; until an
    administrator moves it, that default is what every system-assigned timestamp uses,
    and the clock never falls back to wall-clock time."

    Design: Corner/entities/create_client_system_input_ignored
    """
    spoofed_id = "11111111-1111-1111-1111-111111111111"
    payload = create_client_account_payload(name="Spoof Inc")
    payload["id"] = spoofed_id
    payload["created_at"] = "2020-01-01T00:00:00Z"
    resp = api.create_client_account(payload, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["id"] != spoofed_id, "server must mint its own UUID, not honor client input"
    created = _parse_iso(data["created_at"])
    assert created == datetime(2026, 8, 1, tzinfo=timezone.utc), (
        f"created_at must come from the logical clock default, got {data['created_at']}"
    )


def test_client_list_pagination_limit_offset(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies
    how many items to skip and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the four pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/pagination_limit_offset_total_count
    """
    for name in ("Alpha", "Beta", "Gamma"):
        create_client(name)
    data1, meta1 = validate_paginated(
        api.list_client_accounts(ADMIN, params={"limit": 2, "offset": 0}))
    assert len(data1) == 2, f"page 1 must hold 2 rows, got {len(data1)}"
    assert meta1["total_count"] == 3 and meta1["has_more"] is True
    data2, meta2 = validate_paginated(
        api.list_client_accounts(ADMIN, params={"limit": 2, "offset": 2}))
    assert len(data2) == 1, f"page 2 must hold the remaining row, got {len(data2)}"
    assert meta2["total_count"] == 3 and meta2["has_more"] is False


def test_duplicate_state_code_rejected(api, admin_headers):
    """PRD §3.1: "`state_code` (a two-letter code, unique across profiles — a duplicate
    is rejected with `ERR_DUPLICATE_STATE_CODE`)".

    Design: Corner/errors/duplicate_state_code_rejected
    """
    seed_jurisdiction_profile()
    resp = api.create_jurisdiction_profile(
        {
            "state_code": "CA",
            "base_fee_cents": 5000,
            "per_additional_debtor_fee_cents": 500,
            "county_surcharge_cents": 0,
            "county_filing_collateral_classes": [],
            "county_names": [],
            "individual_name_rule": "DL_SAFE_HARBOR",
            "expedited_daily_capacity": 1,
        },
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATE_CODE)


def test_filing_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "the server validates existence strictly left to right and returns the
    404 error corresponding to the first identifier that does not resolve:
    `ERR_CLIENT_NOT_FOUND` for a missing client, then — as applicable deeper in the
    path — `ERR_REQUEST_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_SEARCH_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_DEBTOR_NOT_FOUND`, `ERR_SECURED_PARTY_NOT_FOUND`, or
    `ERR_JURISDICTION_NOT_FOUND`."

    Design: Corner/entities/filing_not_found_returns_404
    """
    resp = api.get_filing(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_FILING_NOT_FOUND)


def test_client_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "the server validates existence strictly left to right and returns the
    404 error corresponding to the first identifier that does not resolve:
    `ERR_CLIENT_NOT_FOUND` for a missing client".

    Design: Corner/errors/client_not_found_returns_404
    """
    resp = api.get_client_account(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND)


def test_request_search_report_not_found(api, admin_headers):
    """PRD §2.6: "then — as applicable deeper in the path — `ERR_REQUEST_NOT_FOUND`,
    `ERR_FILING_NOT_FOUND`, `ERR_SEARCH_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
    `ERR_DEBTOR_NOT_FOUND`, `ERR_SECURED_PARTY_NOT_FOUND`, or
    `ERR_JURISDICTION_NOT_FOUND`."

    Design: Corner/errors/request_search_report_not_found
    """
    resp = api.get_filing_request(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_FOUND)
    resp = api.get_lien_search(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_SEARCH_NOT_FOUND)
    resp = api.get_perfection_report(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FOUND)


def test_unknown_jurisdiction_code_rejected(api):
    """PRD §2.6: "A `jurisdiction_code` must resolve to a registered jurisdiction
    profile (otherwise `ERR_JURISDICTION_NOT_FOUND`)."

    Design: Corner/errors/unknown_jurisdiction_code_rejected
    """
    world = setup_client_world()
    payload = create_filing_request_payload(
        client_id=world["client"]["id"],
        debtor_id=world["debtor"]["id"],
        secured_party_id=world["secured_party"]["id"],
        jurisdiction_code="ZZ",
    )
    resp = api.create_filing_request(payload, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_JURISDICTION_NOT_FOUND)


def test_body_debtor_not_found(api):
    """PRD §2.6: "A `debtor_id` or `secured_party_id` must exist under the declared
    client (otherwise `ERR_DEBTOR_NOT_FOUND` or `ERR_SECURED_PARTY_NOT_FOUND`
    respectively)."

    Design: Corner/errors/body_debtor_not_found
    """
    seed_jurisdiction_profile()
    client = create_client()
    secured_party = register_secured_party(client["id"])
    payload = create_filing_request_payload(
        client_id=client["id"],
        debtor_id=NON_EXISTENT_UUID,
        secured_party_id=secured_party["id"],
    )
    resp = api.create_filing_request(payload, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_DEBTOR_NOT_FOUND)


def test_secured_party_cross_client_not_found(api):
    """PRD §2.6: "A `debtor_id` or `secured_party_id` must exist under the declared
    client (otherwise `ERR_DEBTOR_NOT_FOUND` or `ERR_SECURED_PARTY_NOT_FOUND`
    respectively)."

    Design: Corner/errors/secured_party_cross_client_not_found
    """
    seed_jurisdiction_profile()
    client_a = create_client("Client A")
    client_b = create_client("Client B")
    debtor = register_debtor(client_a["id"])
    foreign_party = register_secured_party(client_b["id"], name="B's Bank")
    payload = create_filing_request_payload(
        client_id=client_a["id"],
        debtor_id=debtor["id"],
        secured_party_id=foreign_party["id"],
    )
    resp = api.create_filing_request(payload, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_SECURED_PARTY_NOT_FOUND)
