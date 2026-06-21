"""CRUD basics, defaults, type constraints, append-only immutability, and
list/computed-read endpoints."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_license, assert_lab_result,
    create_cultivation_license, create_testing_license,
    create_cured_harvest, create_package, record_lab_result,
    create_active_package,
    cult_h, qa_h, cm_h, reg_h,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# License creation / defaults / constraints
# ---------------------------------------------------------------------------
def test_create_license_returns_201_active_version_1(api):
    """PRD §3.1: "A newly registered license is born in `ACTIVE` status with
    `version` 1."
    PRD §2.4: "Every top-level resource carries a server-minted `id` formatted
    as a UUID with no type prefix"

    Design: Corner/entities/create_license_returns_201_active_version_1
    """
    resp = api.create_license({
        "license_number": "LIC-CR1", "license_type": "RETAIL", "state_code": "CA",
        "expires_on": "2027-01-01T00:00:00Z", "daily_purchase_limit_grams": 28.5,
    }, reg_h())
    data = validate_success(resp, 201)
    assert_license(data)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_create_license_missing_type_rejected(api):
    """PRD §3.1: "Registering a license requires a `license_number` (the
    state-issued number, which must be unique across all licenses and
    non-empty), a `license_type`, a two-uppercase-letter `state_code`, and an
    `expires_on` expiry date."

    Design: Corner/entities/create_license_missing_license_type_returns_invalid_request
    """
    resp = api.create_license({
        "license_number": "LIC-CR2", "state_code": "CA",
        "expires_on": "2027-01-01T00:00:00Z",
    }, reg_h())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_license_not_found(api):
    """PRD §2.8: "A reference to a resource that does not exist is rejected with
    `ERR_NOT_FOUND`."

    Design: Corner/entities/get_license_nonexistent_returns_not_found
    """
    resp = api.get_license(NON_EXISTENT_UUID, reg_h())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_license_daily_limit_defaults_to_285(api):
    """PRD §3.1: "A retail license may also be registered with a
    `daily_purchase_limit_grams` value, the per-customer daily flower-equivalent
    cap in grams; if omitted it defaults to 28.5 grams, and it must be at least
    0."

    Design: Corner/entities/license_daily_limit_default_applied_when_omitted
    """
    resp = api.create_license({
        "license_number": "LIC-CR3", "license_type": "RETAIL", "state_code": "CA",
        "expires_on": "2027-01-01T00:00:00Z",
    }, reg_h())
    data = validate_success(resp, 201)
    assert data["daily_purchase_limit_grams"] == 28.5


def test_license_invalid_enum_type_rejected(api):
    """PRD §3.1: "The `license_type` is one of `CULTIVATION`, `MANUFACTURING`,
    `RETAIL`, `TESTING`, or `DISTRIBUTION`."

    Design: Corner/entities/license_invalid_enum_license_type_rejected
    """
    resp = api.create_license({
        "license_number": "LIC-CR6", "license_type": "WHOLESALE", "state_code": "CA",
        "expires_on": "2027-01-01T00:00:00Z",
    }, reg_h())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Append-only immutability
# ---------------------------------------------------------------------------
def test_lab_result_has_no_version_field(api):
    """PRD §2.4: "By contrast, the append-only and child records — LabResult,
    ManifestLine, SaleLine, ReconciliationCount, and WasteEvent — carry only
    `id` and `created_at`. These records have neither an `updated_at` field nor
    a `version` field, because they are written once and never modified."

    Design: Corner/entities/lab_result_immutable_no_version_field
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    harvest = create_cured_harvest(cul["id"], dry_weight_grams=500)
    pkg = create_package(harvest["id"], quantity_grams=50)
    lr = record_lab_result(pkg["id"], lab["id"], pesticide_pass=True)
    data = validate_success(api.get_lab_result(lr["id"], qa_h("qa-1")))
    assert_lab_result(data)
    assert "version" not in data
    assert "updated_at" not in data


# ---------------------------------------------------------------------------
# Listing / pagination / computed reads
# ---------------------------------------------------------------------------
def test_list_licenses_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`."

    Design: Corner/endpoints/list_licenses_paginated_envelope
    """
    api.create_license({
        "license_number": "LIC-E1A", "license_type": "RETAIL", "state_code": "CA",
        "expires_on": "2027-01-01T00:00:00Z", "daily_purchase_limit_grams": 28.5,
    }, reg_h())
    api.create_license({
        "license_number": "LIC-E1B", "license_type": "CULTIVATION", "state_code": "CA",
        "expires_on": "2027-01-01T00:00:00Z",
    }, reg_h())
    data, meta = validate_paginated(api.list_licenses(reg_h()))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_package_remaining_grams_reflects_waste(api):
    """PRD §2.5: "Each of these secondary mutations is real and observable; none
    is optional."
    PRD §3.8: "For a package source, the event decrements the package's
    `remaining_grams`"

    Design: Corner/endpoints/package_computed_remaining_read_after_waste
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(cul["id"], lab["id"], quantity_grams=100)
    api.create_waste_event({
        "source_type": "PACKAGE", "package_id": pkg["id"], "reason": "MOLD",
        "destroyed_grams": 10, "destroyed_at": "2026-06-18T00:00:00Z",
    }, cm_h("cm-1"))
    data = validate_success(api.get_package(pkg["id"], cm_h("cm-1")))
    assert data["remaining_grams"] == 90.0


def test_list_packages_filtered_by_harvest(api):
    """PRD §3.4: "Product leaves the harvest bin as **Packages**. A package is
    pulled from a harvest by a `Cultivator` or `ComplianceManager`, supplying
    the source `harvest_id`"

    Design: Corner/endpoints/list_packages_by_harvest_filter
    """
    cul = create_cultivation_license()
    harvest = create_cured_harvest(cul["id"], wet_weight_grams=1000, dry_weight_grams=800)
    create_package(harvest["id"], quantity_grams=100, package_tag="PKG-E3A")
    create_package(harvest["id"], quantity_grams=100, package_tag="PKG-E3B")
    data, meta = validate_paginated(
        api.list_packages(cult_h(), params={"harvest_id": harvest["id"]}))
    assert len(data) == 2
    assert all(p["harvest_id"] == harvest["id"] for p in data)
