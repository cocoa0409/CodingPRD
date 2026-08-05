"""District creation, certification gating, and access control."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    create_district_payload, create_taxing_body_payload,
    assert_district, setup_certified_district, create_draft_district,
)

ADMIN = TEST_USERS["municipal_admin_headers"]
CLERK = TEST_USERS["county_clerk_headers"]


# ─── Corner: entities ──────────────────────────────────────────────────────

def test_create_district_returns_201_draft_with_default_surplus_policy():
    """PRD 3.1: "A freshly created district begins in `DRAFT` status, and only a
    `MunicipalAdmin` may create one."
    PRD 3.1: "The authority may also choose the district's `surplus_policy`, one of
    `GROSS` or `NET`; when the field is omitted it defaults to `GROSS`."
    PRD 2.4: "`version` — an integer that starts at 1 on creation and increments by
    one on every mutation."

    Design: Corner/entities/district_create_returns_201_with_defaults
    """
    resp = api_client.create_district(
        create_district_payload(name="New TIF", municipality_name="Town",
                                base_tax_year=2025, base_eav_cents=1_000_000_000,
                                term_years=23),
        ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_district(data)
    assert data["status"] == "DRAFT"
    assert data["surplus_policy"] == "GROSS"
    assert data["version"] == 1


def test_get_district_unknown_id_returns_not_found():
    """PRD 2.7: "a missing district yields `ERR_DISTRICT_NOT_FOUND`."

    Design: Corner/entities/district_get_not_found_returns_404
    """
    resp = api_client.get_district(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DISTRICT_NOT_FOUND, expected_status=404)


def test_create_district_missing_base_eav_returns_validation():
    """PRD 2.7: "the body is present with all required fields, valid enum values, and
    satisfied numeric constraints such as strictly-positive amounts and bounded
    ranges, else `ERR_VALIDATION` (422)."

    Design: Corner/entities/district_create_missing_required_returns_validation
    """
    payload = {"name": "No Base", "municipality_name": "Town",
               "base_tax_year": 2025, "term_years": 23}
    resp = api_client.create_district(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=422)


def test_taxing_body_invalid_body_type_returns_validation():
    """PRD 3.1: "a `body_type` — one of `SCHOOL`, `COUNTY`, `MUNICIPAL`, `PARK`,
    `LIBRARY`, or `OTHER`".
    PRD 2.7: "the body is present with all required fields, valid enum values, and
    satisfied numeric constraints such as strictly-positive amounts and bounded
    ranges, else `ERR_VALIDATION` (422)."

    Design: Corner/entities/taxing_body_invalid_enum_body_type_returns_validation
    """
    district = validate_success(
        api_client.create_district(
            create_district_payload(name="Enum TIF", base_eav_cents=100_000_000), ADMIN),
        expected_status=201)
    resp = api_client.create_taxing_body(
        district["id"],
        create_taxing_body_payload(name="Bad", body_type="FIRE_DEPT", tax_rate=0.03),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=422)


def test_list_districts_pagination_envelope():
    """PRD 2.3: "The response envelope's `meta` object for any list carries `limit`,
    `offset`, `total_count`, and `has_more`, where `total_count` is the size of the
    full unpaginated result and `has_more` is true when rows remain beyond the
    returned window."
    PRD 2.3: "The `limit` parameter caps the number of items returned".

    Design: Corner/entities/districts_list_pagination_envelope
    """
    api_client.create_district(create_district_payload(name="L1", base_eav_cents=100_000_000), ADMIN)
    api_client.create_district(create_district_payload(name="L2", base_eav_cents=100_000_000), ADMIN)
    data, meta = validate_paginated(api_client.list_districts(ADMIN, params={"limit": 1, "offset": 0}))
    assert len(data) == 1, f"limit=1 should cap page to 1 row, got {len(data)}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True


# ─── Corner: state_machines (certification gating) ─────────────────────────

def test_certify_already_certified_returns_not_draft():
    """PRD 3.1: "Certification is permitted only when the district is in `DRAFT`;
    otherwise it is rejected with `ERR_DISTRICT_NOT_DRAFT`."

    Design: Corner/state_machines/certify_non_draft_returns_not_draft
    """
    ctx = setup_certified_district(bodies=[("School", "SCHOOL", 0.05)],
                                   base_eav_cents=100_000_000)
    resp = api_client.certify_district(ctx["district"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_DISTRICT_NOT_DRAFT, expected_status=409)


def test_add_taxing_body_after_certify_rejected():
    """PRD 3.1: "A taxing body may only be added while its district is still `DRAFT`;
    an attempt once the district has moved on is rejected with `ERR_DISTRICT_NOT_DRAFT`."

    Design: Corner/state_machines/add_taxing_body_after_certify_rejected
    """
    ctx = setup_certified_district(bodies=[("School", "SCHOOL", 0.05)],
                                   base_eav_cents=100_000_000)
    resp = api_client.create_taxing_body(
        ctx["district"]["id"],
        create_taxing_body_payload(name="Late County", body_type="COUNTY", tax_rate=0.02),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_DISTRICT_NOT_DRAFT, expected_status=409)


# ─── Corner: validations (certify requires a taxing body) ──────────────────

def test_certify_with_no_taxing_bodies_returns_error():
    """PRD 3.1: "It further requires that at least one taxing body exists for the
    district — a certification attempt against a district with no bodies is rejected
    with `ERR_NO_TAXING_BODIES`".

    Design: Corner/validations/certify_no_taxing_bodies_returns_error
    """
    district = validate_success(
        api_client.create_district(
            create_district_payload(name="Empty TIF", base_eav_cents=100_000_000), ADMIN),
        expected_status=201)
    resp = api_client.certify_district(district["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_NO_TAXING_BODIES, expected_status=409)


# ─── Corner: rbac ──────────────────────────────────────────────────────────

def test_countyclerk_cannot_certify_unauthorized():
    """PRD 3.1: "Certification is the irreversible act that freezes the baseline and
    brings the district to life, and it is reserved to a `MunicipalAdmin`."
    PRD 2.1: "A recognized user who attempts an operation their role is not permitted
    to perform is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/countyclerk_cannot_certify_unauthorized
    """
    district, _ = create_draft_district(bodies=[("School", "SCHOOL", 0.05)],
                                        base_eav_cents=100_000_000)
    resp = api_client.certify_district(district["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_create_district_without_auth_headers_returns_unauthenticated():
    """PRD 2.1: "A request missing either header, or presenting a role the system
    does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/district_create_unauthenticated_returns_401
    """
    resp = api_client.create_district(
        create_district_payload(name="NoAuth", base_eav_cents=100_000_000), {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
