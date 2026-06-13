"""Creation defaults, field validation, referential and account-state guards,
filtered listing, and RBAC.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_field_technician_headers,
    setup_account_with_rate_card,
    create_account,
    create_location,
    create_container,
)
from test_helpers import factories as f

CO = TEST_USERS["compliance_officer_headers"]
AM = TEST_USERS["account_manager_headers"]


# ===========================================================================
# Corner: entities / create_account_returns_201_with_defaults
# ===========================================================================
def test_create_account_defaults(api):
    """PRD §3.1: "A new account begins ACTIVE, with its deterministic billing
    clock current_period_index set to 0 and its prepaid storage_credit_cents
    balance set to 0."

    PRD §2.4: "The version field is an integer that begins at creation and
    increments by one on every mutation."

    Design: Corner/entities/create_account_returns_201_with_defaults
    """
    data = validate_success(api.create_account(
        f.create_account_payload(business_name="Acme", compliance_regime="FACTA"), CO), 201)
    assert data["status"] == "ACTIVE", f"got {data['status']}"
    assert data["current_period_index"] == 0, f"got {data['current_period_index']}"
    assert data["storage_credit_cents"] == 0, f"got {data['storage_credit_cents']}"
    assert data["version"] == 1, f"got {data['version']}"


# ===========================================================================
# Corner: entities / get_account_not_found
# ===========================================================================
def test_get_account_not_found(api):
    """PRD §2.6: "the server validates referenced identifiers left to right and
    rejects on the first one that does not resolve, returning the not-found error
    specific to that resource: ERR_ACCOUNT_NOT_FOUND ... for accounts."

    Design: Corner/entities/get_account_not_found
    """
    validate_error(api.get_account(NON_EXISTENT_UUID, CO),
                   ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)


# ===========================================================================
# Corner: entities / create_order_missing_required_field
# ===========================================================================
def test_create_order_missing_service_mode(api):
    """PRD §3.3: "choosing a service_mode of ON_SITE, OFF_SITE_PICKUP, or
    DROP_OFF, and a cadence of SCHEDULED or ONE_TIME."

    PRD §3.3: "Field sanity (a slot end after its start, valid enum members, and
    so on) is enforced with ERR_INVALID_FIELD_VALUE."

    Omitting the required service_mode is rejected with ERR_INVALID_FIELD_VALUE.

    Design: Corner/entities/create_order_missing_required_field
    """
    account, location, rate_card = setup_account_with_rate_card()
    payload = {
        "account_id": account["id"],
        "location_id": location["id"],
        "cadence": "SCHEDULED",
        "scheduled_slot_start": "2026-07-01T09:00:00Z",
        "scheduled_slot_end": "2026-07-01T10:00:00Z",
    }
    validate_error(api.create_order(payload, AM), ApiErrorId.ERR_INVALID_FIELD_VALUE.value)


# ===========================================================================
# Corner: entities / invalid_enum_compliance_regime
# ===========================================================================
def test_invalid_compliance_regime_enum(api):
    """PRD §3.1: "a compliance_regime - one of STANDARD, FACTA, or HIPAA."

    A compliance_regime outside the enum is rejected with ERR_INVALID_FIELD_VALUE.

    Design: Corner/entities/invalid_enum_compliance_regime
    """
    validate_error(api.create_account(
        f.create_account_payload(business_name="Bad", compliance_regime="GDPR"), CO),
        ApiErrorId.ERR_INVALID_FIELD_VALUE.value)


# ===========================================================================
# Corner: validations / container_location_mismatch_on_order_create
# ===========================================================================
def test_container_location_mismatch_on_order_create(api):
    """PRD §3.3: "If any named container does not belong to the same account and
    location as the order, the request is rejected with
    ERR_CONTAINER_LOCATION_MISMATCH."

    Creating an order at L1 listing a container placed at L2 is rejected.

    Design: Corner/validations/container_location_mismatch_on_order_create
    """
    account = create_account()
    loc1 = create_location(account["id"], label="L1", address="1 Main")
    loc2 = create_location(account["id"], label="L2", address="2 Main")
    get_success_data(api.create_rate_card(f.create_rate_card_payload(account["id"]), CO))
    cards, _ = validate_paginated(api.list_rate_cards(CO, params={"account_id": account["id"]}))
    api.activate_rate_card(cards[0]["id"], CO)
    container = create_container(account["id"], loc2["id"], "CONSOLE", 50, 8.0)
    validate_error(api.create_order(f.create_order_payload(
        account["id"], loc1["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[container["id"]]), AM),
        ApiErrorId.ERR_CONTAINER_LOCATION_MISMATCH.value)


# ===========================================================================
# Corner: validations / duplicate_barcode_among_non_destroyed
# ===========================================================================
def test_duplicate_barcode_rejected(api):
    """PRD §3.8: "The barcode must be unique among the account's boxes whose
    status is not DESTROYED; a collision is rejected with ERR_DUPLICATE_BARCODE."

    Ingesting a second box with a barcode already held by a non-DESTROYED box is
    rejected.

    Design: Corner/validations/duplicate_barcode_among_non_destroyed
    """
    account = create_account()
    location = create_location(account["id"], label="Vault", address="2 Ave")
    get_success_data(api.create_retention_box(
        f.create_retention_box_payload(account["id"], location["id"], "BX-1"), AM))
    validate_error(api.create_retention_box(
        f.create_retention_box_payload(account["id"], location["id"], "BX-1"), AM),
        ApiErrorId.ERR_DUPLICATE_BARCODE.value)


# ===========================================================================
# Corner: validations / create_order_on_suspended_account
# ===========================================================================
def test_create_order_on_suspended_account(api):
    """PRD §3.3: "Creating an order requires that the account be ACTIVE -
    otherwise ERR_ACCOUNT_NOT_ACTIVE."

    A SUSPENDED account rejects order creation.

    Design: Corner/validations/create_order_on_suspended_account
    """
    account, location, rate_card = setup_account_with_rate_card()
    get_success_data(api.suspend_account(account["id"], CO))
    validate_error(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[]), AM),
        ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)


# ===========================================================================
# Corner: validations / no_active_rate_card_on_order_create
# ===========================================================================
def test_no_active_rate_card_on_order_create(api):
    """PRD §3.3: "and that the account have an ACTIVE rate card to price the work
    - otherwise ERR_NO_ACTIVE_RATE_CARD."

    An account whose only rate card is DRAFT (never activated) rejects order
    creation.

    Design: Corner/validations/no_active_rate_card_on_order_create
    """
    account = create_account()
    location = create_location(account["id"])
    get_success_data(api.create_rate_card(f.create_rate_card_payload(account["id"]), CO))
    validate_error(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[]), AM),
        ApiErrorId.ERR_NO_ACTIVE_RATE_CARD.value)


# ===========================================================================
# Corner: validations / slot_end_before_start_invalid
# ===========================================================================
def test_slot_end_before_start_invalid(api):
    """PRD §3.3: "a scheduled_slot_start and a scheduled_slot_end as ISO 8601 UTC
    instants where the end must be strictly after the start."

    A slot whose end precedes its start is rejected with ERR_INVALID_FIELD_VALUE.

    Design: Corner/validations/slot_end_before_start_invalid
    """
    account, location, rate_card = setup_account_with_rate_card()
    validate_error(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[],
        scheduled_slot_start="2026-07-01T10:00:00Z",
        scheduled_slot_end="2026-07-01T09:00:00Z"), AM),
        ApiErrorId.ERR_INVALID_FIELD_VALUE.value)


# ===========================================================================
# Corner: endpoints / list_containers_filtered_by_location
# ===========================================================================
def test_list_containers_filtered_by_location(api):
    """PRD §2.6: "a parent is reached by filtering a list endpoint on the relevant
    foreign-key field (for instance, listing containers by account_id and
    location_id), never by a nested URL."

    GET /containers?location_id=L1 returns only the container placed at L1.

    Design: Corner/endpoints/list_containers_filtered_by_location
    """
    account = create_account()
    loc1 = create_location(account["id"], label="L1", address="1 Main")
    loc2 = create_location(account["id"], label="L2", address="2 Main")
    c1 = create_container(account["id"], loc1["id"], "BIN", 40, 4.0)
    c2 = create_container(account["id"], loc2["id"], "BIN", 40, 4.0)
    data, meta = validate_paginated(api.list_containers(AM, params={"location_id": loc1["id"]}))
    ids = {c["id"] for c in data}
    assert c1["id"] in ids, "c1 at L1 present"
    assert c2["id"] not in ids, "c2 at L2 absent"
    assert "total_count" in meta
    assert "has_more" in meta


# ===========================================================================
# Corner: rbac / field_technician_cannot_create_account
# ===========================================================================
def test_field_technician_cannot_create_account(api):
    """PRD §2.1: "If the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."

    POST /accounts is a ComplianceOfficer-exclusive op; a FieldTechnician is
    denied.

    Design: Corner/rbac/field_technician_cannot_create_account
    """
    tech_headers = make_field_technician_headers("tech-1")
    validate_error(api.create_account(f.create_account_payload(business_name="X"), tech_headers),
                   ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Corner: rbac / missing_auth_header_rejected
# ===========================================================================
def test_missing_auth_header_rejected(api):
    """PRD §2.1: "If either header is absent or malformed, the request is rejected
    with ERR_MISSING_AUTH_CONTEXT (HTTP 401)."

    A request with no auth headers is rejected before any business logic.

    Design: Corner/rbac/missing_auth_header_rejected
    """
    validate_error(api.list_accounts({}), ApiErrorId.ERR_MISSING_AUTH_CONTEXT.value)
