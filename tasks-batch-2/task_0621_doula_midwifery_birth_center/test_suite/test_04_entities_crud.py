"""Entity creation, required fields, defaults, not-found, computed snapshots,
uniqueness, and immutability (queue B: Corner / entities).
"""
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    is_valid_uuid, ApiErrorId, fixtures, MISSING_UUID,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["center_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


# ---- create_client_returns_201_active ----
def test_create_client_returns_201_active(api):
    """PRD §3.1: "A newly registered client opens in ACTIVE status."
    PRD §2.4: "an id that is a server-minted UUID with no type prefix"

    Design: Corner/entities/create_client_returns_201_active
    """
    resp = api.create_client(f.create_client_payload(), INTAKE)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert is_valid_uuid(data["id"]), "id must be a prefix-free UUID"


# ---- create_client_missing_full_name_invalid_request ----
def test_create_client_missing_full_name_invalid_request(api):
    """PRD §2.6: "Request well-formedness is checked fourth — required fields present,
    enum values valid, and integer constraints satisfied ... with any violation producing
    ERR_INVALID_REQUEST (HTTP 422)."
    PRD §3.1: "A client's relationship with the center begins when an IntakeCoordinator
    registers them, supplying the full_name, the date_of_birth, and the parity"

    Design: Corner/entities/create_client_missing_full_name_invalid_request
    """
    resp = api.create_client({"date_of_birth": "1994-03-02", "parity": 0}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---- create_client_negative_parity_invalid_request ----
def test_create_client_negative_parity_invalid_request(api):
    """PRD §3.1: "the parity (the number of prior births, which must be at least 0)"
    PRD §2.6: "integer constraints satisfied (a parity of at least 0 ...) — with any
    violation producing ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_client_negative_parity_invalid_request
    """
    resp = api.create_client(
        f.create_client_payload(parity=-1), INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---- client_insurance_payer_defaults_empty_string ----
def test_client_insurance_payer_defaults_empty_string(api):
    """PRD §3.1: "Insurance details are optional at intake: insurance_payer and
    policy_number may be provided, and when they are omitted they default to the empty
    string, which the system reads as self-pay."

    Design: Corner/entities/client_insurance_payer_defaults_empty_string
    """
    data = validate_success(api.create_client(f.create_client_payload(), INTAKE), expected_status=201)
    assert data["insurance_payer"] == "", f"default empty string, got {data['insurance_payer']!r}"
    assert data["policy_number"] == "", f"default empty string, got {data['policy_number']!r}"


# ---- get_client_not_found ----
def test_get_client_not_found(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing resource
    produces ERR_NOT_FOUND (HTTP 404) before any later identifier or body field is
    examined."

    Design: Corner/entities/get_client_not_found
    """
    resp = api.get_client(MISSING_UUID, INTAKE)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---- episode_computed_global_fee_snapshot ----
def test_episode_global_fee_snapshot_at_create(api):
    """PRD §3.1: "It snapshots the chosen package's global_fee_cents into its own
    global_fee_cents field."
    PRD §3.1: "The episode starts with clinical_status of PLANNING, financial_status of
    UNBILLED, and risk_tier of LOW."

    Design: Corner/entities/episode_computed_global_fee_snapshot
    """
    kit, package = fixtures.create_catalog(global_fee_cents=800000)
    client = fixtures.create_client()
    episode = validate_success(api.create_episode(
        f.create_episode_payload(client["id"], package_code=package["code"], edd="2026-08-01"), INTAKE),
        expected_status=201)
    assert episode["global_fee_cents"] == 800000
    assert episode["clinical_status"] == "PLANNING"
    assert episode["financial_status"] == "UNBILLED"
    assert episode["risk_tier"] == "LOW"
    assert episode["kit_issued"] is True


# ---- duplicate_supply_kit_sku_conflict ----
def test_duplicate_supply_kit_sku_conflict(api):
    """PRD §3.1: "A supply kit is created with a unique sku (duplicates refused with
    ERR_DUPLICATE_RESOURCE)"

    Design: Corner/entities/duplicate_supply_kit_sku_conflict
    """
    kit = fixtures.create_kit(on_hand_count=5)
    resp = api.create_supply_kit(
        f.create_supply_kit_payload(sku=kit["sku"], name="Dup Kit", on_hand_count=9), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


# ---- care_package_immutable_no_version ----
def test_care_package_carries_no_version_field(api):
    """PRD §2.4: "A CarePackage carries only id and created_at; it has no updated_at and
    no version, because it is never modified after creation. Note that for the lookup
    endpoints the id of a CarePackage is its code"

    Design: Corner/entities/care_package_immutable_no_version
    """
    kit = fixtures.create_kit(on_hand_count=5)
    package = fixtures.create_package(kit["sku"], global_fee_cents=800000)
    fetched = validate_success(api.get_care_package(package["code"], ADMIN))
    assert fetched["code"] == package["code"]
    assert fetched["global_fee_cents"] == 800000
    assert "version" not in fetched, "CarePackage must not expose version"
    assert "updated_at" not in fetched, "CarePackage must not expose updated_at"
