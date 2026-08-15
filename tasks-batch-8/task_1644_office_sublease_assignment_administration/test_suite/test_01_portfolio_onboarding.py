"""Portfolio onboarding: parties, buildings, leases (PRD §2.2–2.4, §3.1)."""
from test_helpers import (
    ApiErrorId,
    MGR,
    NON_EXISTENT_UUID,
    assert_lease,
    assert_party,
    create_building_payload,
    create_lease_payload,
    create_party_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_party_creation_and_retrieval_roundtrip(api):
    """PRD §3.1: "A party is registered with its `legal_name`, a `party_kind` of `LANDLORD`, `TENANT`, `SUBTENANT`, or `ASSIGNEE`, and a `credit_rating_bps` score between 0 and 10000 that the credit review later consults."
    PRD §2.4: "`id` (string): a server-minted UUID with no type prefix."

    Design: Corner/entities/party_creation_and_retrieval_roundtrip
    """
    resp = api.create_party(
        create_party_payload(legal_name="Landlord One LLC", party_kind="LANDLORD",
                             credit_rating_bps=9000),
        MGR,
    )
    created = validate_success(resp, 201)
    assert_party(created)
    assert is_valid_uuid(created["id"]), "server mints the id"
    assert isinstance(created["version"], int), "version is system-managed"
    assert is_iso8601_timestamp(created["created_at"])

    fetched = validate_success(api.get_party(created["id"], MGR), 200)
    assert_party(fetched)
    assert fetched["legal_name"] == "Landlord One LLC"
    assert fetched["party_kind"] == "LANDLORD"
    assert fetched["credit_rating_bps"] == 9000


def test_party_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "A request body with a required field missing, an unknown enum value, or a type mismatch is rejected outright with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/party_missing_required_field_returns_invalid_request
    """
    resp = api.create_party(
        {"legal_name": "No Kind Co", "credit_rating_bps": 5000}, MGR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    data, meta = validate_paginated(api.list_parties(MGR))
    assert data == [], "no party row is persisted after a rejected create"
    assert meta["total_count"] == 0


def test_party_invalid_enum_value_rejected(api):
    """PRD §2.8: "A request body with a required field missing, an unknown enum value, or a type mismatch is rejected outright with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "A party is registered with its `legal_name`, a `party_kind` of `LANDLORD`, `TENANT`, `SUBTENANT`, or `ASSIGNEE`, and a `credit_rating_bps` score between 0 and 10000 that the credit review later consults."

    Design: Corner/entities/party_invalid_enum_value_rejected
    """
    resp = api.create_party(
        create_party_payload(legal_name="Bad Enum Co", party_kind="BROKER",
                             credit_rating_bps=5000),
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_lease_system_fields_ignore_client_input(api):
    """PRD §3.1: "A new lease starts with `status` of `ACTIVE` — this administration surface manages transfers on active leases only, and lease expiry or termination is outside the transfer-consent domain — with `open_transfer_count` and `cumulative_profit_share_cents` both zero."

    Design: Corner/entities/lease_system_fields_ignore_client_input
    """
    pl = validate_success(api.create_party(
        create_party_payload(legal_name="Landlord One LLC", party_kind="LANDLORD",
                             credit_rating_bps=9000), MGR), 201)
    pt = validate_success(api.create_party(
        create_party_payload(legal_name="Tenant Alpha Inc", party_kind="TENANT",
                             credit_rating_bps=8000), MGR), 201)
    bld = validate_success(api.create_building(create_building_payload(), MGR), 201)

    lease = validate_success(api.create_lease(
        create_lease_payload(building_id=bld["id"], tenant_party_id=pt["id"],
                             landlord_party_id=pl["id"]),
        MGR,
    ), 201)
    assert_lease(lease)
    assert lease["status"] == "ACTIVE", "status is system-set, never client-supplied"
    assert lease["cumulative_profit_share_cents"] == 0
    assert lease["open_transfer_count"] == 0
    assert isinstance(lease["version"], int)


def test_lease_get_not_found_returns_404(api):
    """PRD §2.8: "then existence of path-referenced resources (`ERR_NOT_FOUND`)".
    PRD §2.8: "When a path contains more than one identifier — a lease before its transfer, a transfer before its review — the first identifier that does not resolve to an existing resource produces the `ERR_NOT_FOUND` (HTTP 404) rejection, before any later identifier is examined."

    Design: Corner/entities/lease_get_not_found_returns_404
    """
    resp = api.get_lease(NON_EXISTENT_UUID, MGR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_tier2_below_tier1_fiscal_incoherence_on_lease_create(api):
    """PRD §3.1: "Fiscal coherence forbids a tier-two percentage below the tier-one percentage; such a lease is rejected with `ERR_FISCAL_INCOHERENT` (HTTP 422)."

    Design: Corner/validations/tier2_below_tier1_fiscal_incoherence_on_lease_create
    """
    pl = validate_success(api.create_party(
        create_party_payload(legal_name="Landlord One LLC", party_kind="LANDLORD",
                             credit_rating_bps=9000), MGR), 201)
    pt = validate_success(api.create_party(
        create_party_payload(legal_name="Tenant Alpha Inc", party_kind="TENANT",
                             credit_rating_bps=8000), MGR), 201)
    bld = validate_success(api.create_building(create_building_payload(), MGR), 201)

    resp = api.create_lease(
        create_lease_payload(building_id=bld["id"], tenant_party_id=pt["id"],
                             landlord_party_id=pl["id"],
                             profit_share_tier1_pct_bps=5000,
                             profit_share_tier2_pct_bps=4000),
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_FISCAL_INCOHERENT, 422)

    # Equal tier percentages are not "below" — the >= boundary is accepted.
    ok = validate_success(api.create_lease(
        create_lease_payload(building_id=bld["id"], tenant_party_id=pt["id"],
                             landlord_party_id=pl["id"],
                             profit_share_tier1_pct_bps=5000,
                             profit_share_tier2_pct_bps=5000),
        MGR,
    ), 201)
    assert_lease(ok)


def test_lease_list_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults to 10, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter skips a number of items before returning the page and defaults to 0."
    PRD §2.3: "Every list response — paginated or not — carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/lease_list_pagination_defaults
    """
    pl = validate_success(api.create_party(
        create_party_payload(legal_name="Landlord One LLC", party_kind="LANDLORD",
                             credit_rating_bps=9000), MGR), 201)
    pt = validate_success(api.create_party(
        create_party_payload(legal_name="Tenant Alpha Inc", party_kind="TENANT",
                             credit_rating_bps=8000), MGR), 201)
    bld = validate_success(api.create_building(create_building_payload(), MGR), 201)
    lease1 = validate_success(api.create_lease(
        create_lease_payload(building_id=bld["id"], tenant_party_id=pt["id"],
                             landlord_party_id=pl["id"]), MGR), 201)
    lease2 = validate_success(api.create_lease(
        create_lease_payload(building_id=bld["id"], tenant_party_id=pt["id"],
                             landlord_party_id=pl["id"],
                             base_rent_per_rsf_annual_cents=6000, leased_rsf=5000,
                             consent_window_business_days=10,
                             deemed_approval_enabled=False,
                             profit_share_tier1_pct_bps=2500,
                             profit_share_tier1_threshold_annual_cents=5000000,
                             profit_share_tier2_pct_bps=5000), MGR), 201)

    data, meta = validate_paginated(
        api.list_leases(MGR, params={"limit": 1, "offset": 0})
    )
    assert len(data) == 1, "limit=1 returns exactly one row"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0

    data2, meta2 = validate_paginated(
        api.list_leases(MGR, params={"limit": 1, "offset": 1})
    )
    assert len(data2) == 1
    assert meta2["has_more"] is False
    assert meta2["offset"] == 1
    # Both pages together cover both leases exactly once (created_at ties make
    # no per-page ordering promise beyond the default ascending sort).
    assert {data[0]["id"], data2[0]["id"]} == {lease1["id"], lease2["id"]}
