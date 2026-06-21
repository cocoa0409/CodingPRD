"""Corner (breadth) tests for entity creation, validation, and listing.

Queue (B) corner-design instances from the `entities` section (PRD §2.2, §2.3,
§2.10, §3.1, §3.2).
"""
from test_helpers import (
    create_community,
    setup_community_and_plan,
    AD,
    FO,
    NON_EXISTENT_UUID,
)
from test_helpers.api_client import api_client
from test_helpers import (
    assert_community,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_community_payload,
    create_contract_plan_payload,
    create_residency_payload,
    create_resident_payload,
    create_unit_payload,
)


def _AD():
    from test_helpers import make_admissions_director_headers
    return make_admissions_director_headers()


# ─────────────────────────────────────────────────────────────────────────────
# entities / create_community_returns_201_with_system_fields
# ─────────────────────────────────────────────────────────────────────────────

def test_create_community_returns_201_with_system_fields(api):
    """PRD §3.1: "On creation the community's `current_period_index` is 0 and
    `is_admissions_frozen` is false."
    PRD §2.4: "The `version` is an integer that begins at 1 (or the implementation's
    initial value) and increments by exactly one on every mutation of the resource."

    Design: Corner/entities/create_community_returns_201_with_system_fields
    """
    resp = api_client.create_community(
        create_community_payload(name="Lakeside", actuarial_discount_rate_bps=600), FO,
    )
    data = validate_success(resp, expected_status=201)
    assert_community(data)
    assert data["current_period_index"] == 0
    assert data["is_admissions_frozen"] is False
    assert data["version"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# entities / create_community_missing_required_field_returns_invalid_request
# ─────────────────────────────────────────────────────────────────────────────

def test_create_community_missing_discount_rate_rejected(api):
    """PRD §3.1: "A `FinanceOfficer` establishes a community by supplying its legal
    `name` and its `actuarial_discount_rate_bps`".
    PRD §2.10: "Request-body well-formedness is fifth — required fields present and
    correctly typed ... yielding `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_community_missing_required_field_returns_invalid_request
    """
    resp = api_client.create_community({"name": "NoRate"}, FO)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─────────────────────────────────────────────────────────────────────────────
# entities / create_plan_nonpositive_entrance_fee_returns_invalid_request
# ─────────────────────────────────────────────────────────────────────────────

def test_create_plan_zero_entrance_fee_rejected(api):
    """PRD §3.1: "The `entrance_fee_cents` and `monthly_service_fee_cents` must each
    be strictly greater than zero ... a violation of any of these ... is rejected
    with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_plan_nonpositive_entrance_fee_returns_invalid_request
    """
    community = create_community(name="FeeTown")
    resp = api_client.create_contract_plan(
        create_contract_plan_payload(
            community["id"], name="Bad", contract_type="TYPE_C",
            entrance_fee_cents=0, refund_plan="DECLINING",
            monthly_service_fee_cents=300_000, second_person_fee_cents=0,
        ), FO,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─────────────────────────────────────────────────────────────────────────────
# entities / create_plan_invalid_enum_contract_type_returns_invalid_request
# ─────────────────────────────────────────────────────────────────────────────

def test_create_plan_invalid_contract_type_enum_rejected(api):
    """PRD §3.1: "a missing required field, a bad enum, or a malformed body — is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_plan_invalid_enum_contract_type_returns_invalid_request
    """
    community = create_community(name="EnumTown")
    resp = api_client.create_contract_plan(
        create_contract_plan_payload(
            community["id"], name="BadEnum", contract_type="TYPE_D",
            entrance_fee_cents=5_000_000, refund_plan="DECLINING",
            monthly_service_fee_cents=300_000, second_person_fee_cents=0,
        ), FO,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─────────────────────────────────────────────────────────────────────────────
# entities / get_unit_nonexistent_returns_not_found
# ─────────────────────────────────────────────────────────────────────────────

def test_get_unit_nonexistent_returns_not_found(api):
    """PRD §2.10: "the first identifier in the path that does not correspond to an
    existing resource causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/get_unit_nonexistent_returns_not_found
    """
    resp = api_client.get_unit(NON_EXISTENT_UUID, _AD())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ─────────────────────────────────────────────────────────────────────────────
# entities / create_residency_unknown_plan_returns_referenced_entity_not_found
# ─────────────────────────────────────────────────────────────────────────────

def test_create_residency_unknown_plan_rejected(api):
    """PRD §2.10: "Existence of foreign-key references in the request body is fourth:
    a body field that names a non-existent community, residency, resident, plan,
    unit, or council is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 422)."

    Design: Corner/entities/create_residency_unknown_plan_returns_referenced_entity_not_found
    """
    community = create_community(name="RefTown")
    resident = validate_success(api_client.create_resident(
        create_resident_payload(community["id"], full_name="Ron R"), _AD(),
    ), expected_status=201)
    resp = api_client.create_residency(
        create_residency_payload(
            community["id"], resident["id"], NON_EXISTENT_UUID,
        ), _AD(),
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND.value)


# ─────────────────────────────────────────────────────────────────────────────
# entities / unit_default_bed_capacity_applied_when_omitted
# ─────────────────────────────────────────────────────────────────────────────

def test_unit_default_bed_capacity_and_available_status(api):
    """PRD §3.1: "a `care_level`, and an optional `bed_capacity` (default 1,
    meaningful only for skilled health-center units). A unit's `status` is
    system-managed: it is `AVAILABLE` on creation".

    Design: Corner/entities/unit_default_bed_capacity_applied_when_omitted
    """
    community = create_community(name="DefTown")
    data = validate_success(api_client.create_unit(
        create_unit_payload(community["id"], unit_number="D1", care_level="SKILLED"),
        _AD(),
    ), expected_status=201)
    assert data["bed_capacity"] == 1, f"default bed_capacity must be 1, got {data['bed_capacity']}"
    assert data["status"] == "AVAILABLE", f"new unit must be AVAILABLE, got {data['status']}"


# ─────────────────────────────────────────────────────────────────────────────
# entities / list_communities_paginated_envelope
# ─────────────────────────────────────────────────────────────────────────────

def test_list_communities_paginated_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_communities_paginated_envelope
    """
    create_community(name="P1")
    create_community(name="P2")
    data, meta = validate_paginated(api_client.list_communities(FO))
    assert meta["total_count"] >= 2, f"total_count must be >= 2, got {meta['total_count']}"
    assert "has_more" in meta, "meta must carry has_more"
