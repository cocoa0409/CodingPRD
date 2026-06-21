"""Entity CRUD corners: creation envelope, not-found, required-field and enum
validation, defaults, uniqueness, listing pagination.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_cap_table,
    create_cap_table,
    create_shareholder,
    api_client,
)
from test_helpers import ApiErrorId

ADMIN = TEST_USERS["administrator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ============================================================================
# Corner/entities/create_cap_table_returns_201_with_open_status
# ============================================================================

def test_create_cap_table_returns_201_open_zeroed(api):
    """PRD §3.1: "A freshly created table opens in `OPEN` status with
    `issued_shares` and `fully_diluted_shares` both at zero and `locked_at` null."

    PRD §2.4: `version` "starts at 1 on creation".

    Design: Corner/entities/create_cap_table_returns_201_with_open_status
    """
    data = validate_success(api.create_cap_table(
        {"company_name": "Fresh Co", "authorized_shares": 5_000_000}, ADMIN), 201)
    assert_cap_table(data)
    assert data["status"] == "OPEN", f"expected OPEN, got {data['status']}"
    assert data["issued_shares"] == 0
    assert data["fully_diluted_shares"] == 0
    assert data["version"] == 1, f"expected version 1, got {data['version']}"


# ============================================================================
# Corner/entities/get_cap_table_not_found_returns_404
# ============================================================================

def test_get_cap_table_not_found(api):
    """PRD §2.7: "the server resolves those ids left-to-right and rejects the
    first one that does not resolve to an existing entity with `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_cap_table_not_found_returns_404
    """
    resp = api.get_cap_table(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ============================================================================
# Corner/entities/create_security_class_missing_required_field_returns_400
# ============================================================================

def test_create_security_class_missing_class_type(api):
    """PRD §2.4: "A request whose body is malformed, omits a required field, or
    supplies a value of the wrong type or an enum value outside the declared set
    is rejected with `ERR_VALIDATION` (HTTP 400)."

    Omitting the required `class_type` → ERR_VALIDATION.

    Design: Corner/entities/create_security_class_missing_required_field_returns_400
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    resp = api.create_security_class({
        "cap_table_id": ct["id"], "name": "Common", "original_issue_price_cents": 0,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ============================================================================
# Corner/entities/create_security_class_invalid_enum_returns_400
# ============================================================================

def test_create_security_class_invalid_enum(api):
    """PRD §2.4: "A request whose body is malformed, omits a required field, or
    supplies a value of the wrong type or an enum value outside the declared set
    is rejected with `ERR_VALIDATION` (HTTP 400)."

    class_type='JUNIOR' is outside {COMMON, PREFERRED} → ERR_VALIDATION.

    Design: Corner/entities/create_security_class_invalid_enum_returns_400
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    resp = api.create_security_class({
        "cap_table_id": ct["id"], "name": "Weird", "class_type": "JUNIOR",
        "original_issue_price_cents": 0,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ============================================================================
# Corner/entities/shareholder_default_is_us_taxpayer_true
# ============================================================================

def test_shareholder_default_is_us_taxpayer_true(api):
    """PRD §3.3: "The `is_us_taxpayer` boolean (default true) records whether the
    holder is subject to IRS reporting and therefore eligible for a Form 3921 on
    exercise."

    Omitting is_us_taxpayer → default true applied.

    Design: Corner/entities/shareholder_default_is_us_taxpayer_true
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    data = validate_success(api.create_shareholder({
        "cap_table_id": ct["id"], "legal_name": "Pat", "holder_type": "FOUNDER",
        "email": "p@def.com",
    }, ADMIN), 201)
    assert data["is_us_taxpayer"] is True, (
        f"expected default is_us_taxpayer true, got {data['is_us_taxpayer']}"
    )


# ============================================================================
# Corner/entities/shareholder_email_unique_within_cap_table
# ============================================================================

def test_shareholder_duplicate_email_rejected(api):
    """PRD §3.3: "A `Shareholder` is registered by an `Administrator` against a
    `cap_table_id` with a `legal_name` (non-empty), a `holder_type` of `FOUNDER`,
    `EMPLOYEE`, `INVESTOR`, or `ENTITY`, and an `email` that must be non-empty and
    unique within the cap table."

    Second shareholder with a duplicate email → ERR_VALIDATION.

    Design: Corner/entities/shareholder_email_unique_within_cap_table
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    create_shareholder(ct["id"], legal_name="First", holder_type="FOUNDER", email="dup@x.com")
    resp = api.create_shareholder({
        "cap_table_id": ct["id"], "legal_name": "Second", "holder_type": "EMPLOYEE",
        "email": "dup@x.com",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ============================================================================
# Corner/entities/cap_table_list_pagination_envelope
# ============================================================================

def test_cap_table_list_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope, where `total_count`
    reflects the full size of the filtered collection and `has_more` indicates
    whether further pages remain."

    Two cap tables, limit=1 → data length 1, total_count 2, has_more true.

    Design: Corner/entities/cap_table_list_pagination_envelope
    """
    create_cap_table(company_name="A", authorized_shares=100)
    create_cap_table(company_name="B", authorized_shares=100)
    resp = api.list_cap_tables(AUDITOR, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more true, got {meta['has_more']}"
    assert len(data) == 1, f"expected 1 row, got {len(data)}"
