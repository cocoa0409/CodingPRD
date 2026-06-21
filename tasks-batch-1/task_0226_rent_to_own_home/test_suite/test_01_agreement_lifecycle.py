"""Agreement drafting, activation, and the Property occupancy / OCC contract.

Covers creation and retrieval of the central Agreement entity, the system-managed
defaults and copied fields, the DRAFT -> ACTIVE transition with its optimistic
concurrency gate on the Property version, and the single-occupancy rule that keeps
one Property under at most one active agreement.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    is_iso8601_timestamp,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    assert_agreement,
    assert_property,
    create_agreement_payload,
    create_property_payload,
    # fixtures
    create_landlord,
    create_tenant,
    create_property,
    create_parties_and_property,
    create_draft_agreement,
    create_active_agreement,
    activate_agreement,
    make_landlord_headers,
    make_tenant_headers,
    setup_two_drafts_on_one_property,
)


def test_create_agreement_returns_201_draft_with_copied_landlord(api):
    """PRD §3.2: "When an agreement is created it is born in `DRAFT`." and
    "instead `landlord_id` is copied from the chosen property's `landlord_id` at
    creation, and the issuing landlord must in fact own that property".

    Design: Corner/entities/entity_create_agreement_returns_201_with_fields
    """
    landlord, tenant, prop = create_parties_and_property()
    res = api.create_agreement(
        create_agreement_payload(prop["id"], tenant["id"]),
        make_landlord_headers(landlord["id"]),
    )
    data = validate_success(res, expected_status=201)
    assert_agreement(data)
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"
    assert data["landlord_id"] == landlord["id"], (
        f"landlord_id must be copied from the property: expected {landlord['id']}, "
        f"got {data['landlord_id']}"
    )


def test_get_agreement_returns_stored_resource(api):
    """PRD §2.9: "Child resources such as rent payments, maintenance tickets,
    option exercises, and mortgages are also individually fetchable and listable
    by their own identifiers".
    PRD §3.2: "A fetched agreement always reports its computed accrual fields
    freshly recomputed".

    Design: Corner/entities/entity_get_agreement_returns_stored
    """
    landlord, tenant, prop, agreement = create_draft_agreement()
    res = api.get_agreement(agreement["id"], make_tenant_headers(tenant["id"]))
    data = validate_success(res, expected_status=200)
    assert data["id"] == agreement["id"], (
        f"GET must return the stored agreement id {agreement['id']}, got {data['id']}"
    )


def test_list_properties_is_paginated(api):
    """PRD §2.3: "List responses carry the pagination bookkeeping in the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/entity_list_properties_paginated
    """
    landlord = create_landlord()
    create_property(landlord)
    res = api.list_properties(
        make_landlord_headers(landlord["id"]),
        params={"landlord_id": landlord["id"], "limit": 10, "offset": 0},
    )
    data, meta = validate_paginated(res)
    assert meta["total_count"] >= 1, f"expected total_count >= 1, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"


def test_get_agreement_unknown_id_not_found(api):
    """PRD §2.8: "every resource referenced by the path or body must exist; these
    are validated left-to-right, and the first missing one yields `ERR_NOT_FOUND`
    (404)."

    Design: Corner/entities/entity_get_agreement_not_found
    """
    landlord = create_landlord()
    res = api.get_agreement(NON_EXISTENT_UUID, make_landlord_headers(landlord["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_agreement_missing_credit_pct_rejected(api):
    """PRD §2.8: "on writes, required body fields must be present and well-typed,
    enum values must be in their allowed sets, and numeric ranges must hold ... a
    violation yields `ERR_INVALID_REQUEST` (422)."
    PRD §3.2: "`credit_pct`, the fraction of each monthly payment that accrues as
    purchase credit, which must be between 0 and 1 inclusive."

    Design: Corner/entities/entity_create_agreement_missing_required_field
    """
    landlord, tenant, prop = create_parties_and_property()
    payload = create_agreement_payload(prop["id"], tenant["id"])
    payload.pop("credit_pct")
    res = api.create_agreement(payload, make_landlord_headers(landlord["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_agreement_optional_fields_apply_named_defaults(api):
    """PRD §3.2: "`max_credit_pct` caps the total credit that can ever be applied
    ... and defaults to 0.20 when omitted. `grace_days` is the number of days after
    a payment's due date within which a payment still earns its credit; it must be
    at least zero and defaults to 5. `maintenance_threshold_cents` is the per-ticket
    cost split point ... and defaults to 50000 (five hundred dollars)."
    PRD §3.2: "`option_fee_creditable`, a boolean that decides whether that fee
    credits toward the purchase at exercise; when omitted it defaults to true."

    Design: Corner/entities/entity_agreement_defaults_applied
    """
    landlord, tenant, prop = create_parties_and_property()
    res = api.create_agreement(
        create_agreement_payload(prop["id"], tenant["id"]),
        make_landlord_headers(landlord["id"]),
    )
    data = validate_success(res, expected_status=201)
    assert data["max_credit_pct"] == pytest.approx(0.20), data["max_credit_pct"]
    assert data["grace_days"] == 5, data["grace_days"]
    assert data["maintenance_threshold_cents"] == 50000, data["maintenance_threshold_cents"]
    assert data["option_fee_creditable"] is True, data["option_fee_creditable"]


def test_property_created_available_with_system_fields(api):
    """PRD §3.1: "A new property is born in the `AVAILABLE` state".
    PRD §2.4: "`id` — a unique, server-minted identifier formatted as a UUID, with
    no type prefix." and "`created_at` — an ISO 8601 UTC timestamp".

    Design: Corner/entities/entity_system_fields_generated
    """
    landlord = create_landlord()
    res = api.create_property(
        create_property_payload(landlord["id"]),
        make_landlord_headers(landlord["id"]),
    )
    data = validate_success(res, expected_status=201)
    assert_property(data)
    assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert data["status"] == "AVAILABLE", f"new property must be AVAILABLE, got {data['status']}"


def test_create_tenant_credit_score_above_range_rejected(api):
    """PRD §3.1: "a `credit_score` — a FICO-style integer that must lie between 300
    and 850 inclusive".
    PRD §2.8: "numeric ranges must hold (for example ... `credit_score` between 300
    and 850 inclusive ...); a violation yields `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/entity_tenant_credit_score_out_of_range
    """
    res = api.create_tenant(
        {"legal_name": "Out Of Range", "email": "oor@example.com", "credit_score": 900},
        TEST_USERS["tenant_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_property_unknown_landlord_not_found(api):
    """PRD §2.8: "every resource referenced by the path or body must exist; these
    are validated left-to-right, and the first missing one yields `ERR_NOT_FOUND`
    (404)."
    PRD §3.1: "The creation payload names the `landlord_id` (which must identify the
    acting landlord)".

    Design: Corner/entities/entity_property_fk_landlord_not_found
    """
    bogus = "00000000-0000-4000-8000-0000000000aa"
    res = api.create_property(
        {"landlord_id": bogus, "address": "Ghost Way", "list_price_cents": 30000000},
        make_landlord_headers(bogus),
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_tenant_cannot_activate_agreement(api):
    """PRD §4: the routing table lists `POST /agreements/{id}/activate` as authorized
    for Landlord only.
    PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership check fails — the request is
    rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/rbac_tenant_cannot_activate_agreement
    """
    landlord, tenant, prop, agreement = create_draft_agreement()
    res = api.activate_agreement(
        agreement["id"],
        {"expected_property_version": prop["version"]},
        make_tenant_headers(tenant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_activation_with_stale_property_version_rejected(api):
    """PRD §2.7: "If another writer has advanced the property's version since the
    activating client last observed it ... the activation is rejected with
    `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a property
    it has not freshly observed."

    Design: Corner/cross_cutting_complexity_layers/ccl_occ_stale_property_version_on_activate
    """
    landlord, tenant, prop, a1, a2, ver_before = setup_two_drafts_on_one_property()
    # a2 activates with the stale pre-a1 version.
    res = api.activate_agreement(
        a2["id"],
        {"expected_property_version": ver_before},
        make_landlord_headers(landlord["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


def test_property_version_increments_on_activation_cascade(api):
    """PRD §2.4: "`version` — a system-managed integer that begins at its initial
    value and increments by one on every mutation of the resource."
    PRD §2.6: "the property moves from `AVAILABLE` to `UNDER_AGREEMENT`, which itself
    increments the property's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/ccl_version_increments_on_mutation
    """
    landlord, tenant, prop, agreement = create_draft_agreement()
    ver_before = get_success_data(
        api.get_property(prop["id"], make_landlord_headers(landlord["id"]))
    )["version"]
    activate_agreement(landlord, prop, agreement)
    after = get_success_data(
        api.get_property(prop["id"], make_landlord_headers(landlord["id"]))
    )
    assert after["version"] == ver_before + 1, (
        f"property version must increment by one on the activation cascade: "
        f"{ver_before} -> {after['version']}"
    )
    assert after["status"] == "UNDER_AGREEMENT", (
        f"activation must take the property UNDER_AGREEMENT, got {after['status']}"
    )


def test_activate_second_agreement_on_taken_property_rejected(api):
    """PRD §3.2: "Once the version matches, the property must be `AVAILABLE`; if it
    is not, activation is rejected with `ERR_PROPERTY_NOT_AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/cesd_activate_depends_on_property_available
    """
    landlord, tenant, prop, a1, a2, ver_before = setup_two_drafts_on_one_property()
    fresh = get_success_data(
        api.get_property(prop["id"], make_landlord_headers(landlord["id"]))
    )
    res = api.activate_agreement(
        a2["id"],
        {"expected_property_version": fresh["version"]},
        make_landlord_headers(landlord["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PROPERTY_NOT_AVAILABLE.value)
    a2_now = get_success_data(
        api.get_agreement(a2["id"], make_landlord_headers(landlord["id"]))
    )
    assert a2_now["status"] == "DRAFT", (
        f"rejected activation must leave the agreement DRAFT, got {a2_now['status']}"
    )


def test_property_hosts_single_active_agreement(api):
    """PRD §3.2: "Once the version matches, the property must be `AVAILABLE`; if it
    is not, activation is rejected with `ERR_PROPERTY_NOT_AVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/rto_property_single_active_agreement_occupancy
    """
    landlord, tenant, prop, a1, a2, ver_before = setup_two_drafts_on_one_property(
    )
    fresh = get_success_data(
        api.get_property(prop["id"], make_landlord_headers(landlord["id"]))
    )
    res = api.activate_agreement(
        a2["id"],
        {"expected_property_version": fresh["version"]},
        make_landlord_headers(landlord["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PROPERTY_NOT_AVAILABLE.value)


def test_duplicate_period_index_rejected(api):
    """PRD §3.3: "The pair of agreement and `period_index` must be unique among
    non-superseded payment rows; scheduling a second row for an already-billed
    period is rejected with `ERR_DUPLICATE_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/rto_rentpayment_period_index_collision
    """
    landlord, tenant, prop, agreement = create_active_agreement()
    first = api.create_rent_payment(
        agreement["id"], {"period_index": 1, "due_date": "2026-02-01T00:00:00Z"},
        make_landlord_headers(landlord["id"]),
    )
    validate_success(first, expected_status=201)
    dup = api.create_rent_payment(
        agreement["id"], {"period_index": 1, "due_date": "2026-02-01T00:00:00Z"},
        make_landlord_headers(landlord["id"]),
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_PERIOD.value)


def test_distinct_period_index_accepted(api):
    """PRD §3.3: "The pair of agreement and `period_index` must be unique among
    non-superseded payment rows; scheduling a second row for an already-billed
    period is rejected with `ERR_DUPLICATE_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/rto_rentpayment_period_index_collision
    """
    landlord, tenant, prop, agreement = create_active_agreement()
    first = api.create_rent_payment(
        agreement["id"], {"period_index": 1, "due_date": "2026-02-01T00:00:00Z"},
        make_landlord_headers(landlord["id"]),
    )
    validate_success(first, expected_status=201)
    second = api.create_rent_payment(
        agreement["id"], {"period_index": 2, "due_date": "2026-03-01T00:00:00Z"},
        make_landlord_headers(landlord["id"]),
    )
    data = validate_success(second, expected_status=201)
    assert data["period_index"] == 2, data["period_index"]


def test_first_agreement_occupies_property_before_second_rejected(api):
    """PRD §3.2: "When both gates pass, the agreement transitions `DRAFT → ACTIVE`,
    its `option_deadline` is settled, and the cascade takes the property
    `AVAILABLE → UNDER_AGREEMENT`".

    Design: Difficulty/cross_entity_state_dependency/cesd_activate_depends_on_property_available
    """
    landlord, tenant, prop, a1, a2, ver_before = setup_two_drafts_on_one_property()
    a1_now = get_success_data(
        api.get_agreement(a1["id"], make_landlord_headers(landlord["id"]))
    )
    assert a1_now["status"] == "ACTIVE", a1_now["status"]
    p = get_success_data(
        api.get_property(prop["id"], make_landlord_headers(landlord["id"]))
    )
    assert p["status"] == "UNDER_AGREEMENT", p["status"]


def test_active_agreement_takes_property_under_agreement(api):
    """PRD §3.2: "the cascade takes the property `AVAILABLE → UNDER_AGREEMENT` (which
    bumps the property's `version`)".

    Design: Difficulty/resource_temporal_overlap/rto_property_single_active_agreement_occupancy
    """
    landlord, tenant, prop, a1, a2, ver_before = setup_two_drafts_on_one_property()
    p = get_success_data(
        api.get_property(prop["id"], make_landlord_headers(landlord["id"]))
    )
    assert p["status"] == "UNDER_AGREEMENT", (
        f"the property hosting the active agreement must be UNDER_AGREEMENT, got {p['status']}"
    )
