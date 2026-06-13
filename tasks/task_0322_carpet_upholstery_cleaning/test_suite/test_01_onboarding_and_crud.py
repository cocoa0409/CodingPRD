"""Onboarding and CRUD tests: customer/catalog/job creation defaults, uniqueness
constraints, request well-formedness, not-found existence, and role-based access
control.

Covers corner section `entities`, the room-validation corner instances, and the
`rbac` corner instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    assert_customer,
    assert_cleaning_job,
    assert_wallet_ledger_entry,
    create_customer,
    create_catalog,
    create_job,
    setup_customer_with_wallet_credit,
    make_customer_headers,
    TEST_USERS,
    NON_EXISTENT_UUID,
)

CUSTOMER = TEST_USERS["customer_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
SERVICE_MANAGER = TEST_USERS["service_manager_headers"]


# ─── entities: creation defaults ──────────────────────────────

def test_create_customer_defaults_active_zero_wallet(api):
    """PRD §3.1: "A freshly created customer begins life with status of ACTIVE and
    an account credit of zero cents."
    PRD §2.4: "The version starts at 1 when the resource is created and increments
    by one on every mutation of that resource."

    Design: Corner/entities/create_customer_returns_201_with_defaults
    """
    res = api.create_customer({"full_name": "New Cust", "email": "newcust-defaults@x.com"}, CUSTOMER)
    customer = validate_success(res, 201)
    assert_customer(customer)
    assert customer["status"] == "ACTIVE"
    assert customer["wallet_credit_cents"] == 0
    assert customer["version"] == 1


def test_create_job_defaults_draft_unbilled(api):
    """PRD §3.2: "A new job begins in DRAFT lifecycle status, UNBILLED billing
    status, and with total_sqft of 0."
    PRD §3.2: "it may also optionally set move_furniture, which defaults to false."
    PRD §3.2: "The creation request may optionally name a recurring_plan_id, which
    is left null for a one-off job."

    Design: Corner/entities/create_cleaning_job_defaults_draft_unbilled
    """
    customer = create_customer()
    catalog = create_catalog()
    res = api.create_cleaning_job(
        {"customer_id": customer["id"], "service_catalog_id": catalog["id"]},
        make_customer_headers(customer["id"]))
    job = validate_success(res, 201)
    assert_cleaning_job(job)
    assert job["lifecycle_status"] == "DRAFT"
    assert job["billing_status"] == "UNBILLED"
    assert job["move_furniture"] is False
    assert job["total_sqft"] == 0
    assert job["recurring_plan_id"] is None


def test_get_nonexistent_job_returns_not_found(api):
    """PRD §2.5: "a non-existent job surfaces ERR_JOB_NOT_FOUND."

    Design: Corner/entities/get_cleaning_job_not_found
    """
    res = api.get_cleaning_job(NON_EXISTENT_UUID, SERVICE_MANAGER)
    validate_error(res, "ERR_JOB_NOT_FOUND", expected_status=404)


# ─── entities: request validation ─────────────────────────────

def test_create_room_missing_area_sqft_rejected(api):
    """PRD §2.6: "the request body itself is checked for well-formedness — required
    fields present, enumerated fields within their allowed sets, and integers
    within their stated bounds — with any failure rejected as ERR_INVALID_REQUEST
    (HTTP 422)."

    Design: Corner/entities/create_room_missing_required_field
    """
    customer = create_customer()
    catalog = create_catalog()
    job = create_job(customer, catalog["id"])
    res = api.add_room(job["id"], {"area_label": "NoSqft", "soiling_level": "LIGHT"},
                       make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_room_invalid_soiling_enum_rejected(api):
    """PRD §2.6: "the request body itself is checked for well-formedness — required
    fields present, enumerated fields within their allowed sets, and integers
    within their stated bounds — with any failure rejected as ERR_INVALID_REQUEST
    (HTTP 422)."

    Design: Corner/entities/create_room_invalid_soiling_enum
    """
    customer = create_customer()
    catalog = create_catalog()
    job = create_job(customer, catalog["id"])
    res = api.add_room(job["id"], {"area_label": "Bad", "area_sqft": 100, "soiling_level": "FILTHY"},
                       make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_room_zero_sqft_rejected(api):
    """PRD §2.6: "a room's area_sqft must be at least 1, a payment's amount_cents
    must be at least 1, a slot's end_minute must be strictly greater than its
    start_minute, and catalog rates may not be negative. Any violation is an
    ERR_INVALID_REQUEST."

    Design: Corner/entities/create_room_zero_sqft_rejected
    """
    customer = create_customer()
    catalog = create_catalog()
    job = create_job(customer, catalog["id"])
    res = api.add_room(job["id"], {"area_label": "Zero", "area_sqft": 0, "soiling_level": "LIGHT"},
                       make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ─── entities: uniqueness ─────────────────────────────────────

def test_duplicate_customer_email_rejected(api):
    """PRD §3.1: "The email must be unique across all customers — a second customer
    attempting to register an address already on file is rejected with
    ERR_EMAIL_TAKEN."

    Design: Corner/entities/duplicate_customer_email_rejected
    """
    validate_success(api.create_customer({"full_name": "First", "email": "dupe-email@x.com"}, CUSTOMER), 201)
    res = api.create_customer({"full_name": "Second", "email": "dupe-email@x.com"}, CUSTOMER)
    validate_error(res, "ERR_EMAIL_TAKEN", expected_status=409)


def test_duplicate_service_type_catalog_rejected(api):
    """PRD §3.1: "Only one catalog may exist per service type; an attempt to create
    a second STEAM or a second DRY catalog is rejected with ERR_SERVICE_TYPE_TAKEN."

    Design: Corner/entities/duplicate_service_type_catalog_rejected
    """
    create_catalog(service_type="STEAM")
    res = api.create_service_catalog(
        {"service_type": "STEAM", "base_rate_cents_per_sqft": 60, "stain_addon_cents": 2500,
         "pet_addon_cents": 1800, "protectant_cents_per_sqft": 12,
         "move_furniture_flat_cents": 3000, "dry_time_minutes": 240},
        SERVICE_MANAGER)
    validate_error(res, "ERR_SERVICE_TYPE_TAKEN", expected_status=409)


# ─── entities: append-only ledger ─────────────────────────────

def test_wallet_ledger_entry_is_lean_append_only(api):
    """PRD §2.4: "A WalletLedgerEntry is an append-only ledger record: it carries
    only id and created_at. It has no updated_at and no version, because once
    written it is never modified."
    PRD §3.5: "it grants a flat goodwill account credit of 2000 cents by writing a
    WalletLedgerEntry with that positive delta_cents and a reason of
    GUARANTEE_CREDIT."

    Design: Corner/entities/wallet_ledger_immutable_entity_no_version
    """
    base = setup_customer_with_wallet_credit()
    customer = base["customer"]
    data, meta = _list(api.list_customer_wallet_ledger(customer["id"], SERVICE_MANAGER))
    assert meta["total_count"] == 1, f"one ledger entry expected, got {meta['total_count']}"
    entry = data[0]
    assert_wallet_ledger_entry(entry)
    assert entry["reason"] == "GUARANTEE_CREDIT"
    assert entry["delta_cents"] == 2000


# ─── rbac ─────────────────────────────────────────────────────

def test_customer_cannot_create_crew(api):
    """PRD §3.1: "A Dispatcher creates a crew."
    PRD §2.1: "When the headers are valid but the named role is not permitted to
    perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/customer_cannot_create_crew
    """
    customer = create_customer()
    res = api.create_crew(
        {"crew_name": "Sneaky", "supported_service_type": "STEAM", "turnaround_buffer_minutes": 30},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_missing_auth_role_rejected(api):
    """PRD §2.1: "If either header is absent, or X-User-Role does not name a role
    the system recognizes, the request is rejected with ERR_MISSING_AUTH (HTTP 401)."

    Design: Corner/rbac/missing_auth_header_rejected
    """
    customer = create_customer()
    catalog = create_catalog()
    ghost_headers = {"X-User-ID": "ghost-1", "X-User-Role": "Ghost", "Content-Type": "application/json"}
    res = api.create_cleaning_job(
        {"customer_id": customer["id"], "service_catalog_id": catalog["id"]}, ghost_headers)
    validate_error(res, "ERR_MISSING_AUTH", expected_status=401)


def test_customer_cannot_mutate_other_customers_job(api):
    """PRD §2.1: "When a Customer attempts to mutate a job, room, add-on, or plan
    that they do not own, the request is rejected with ERR_NOT_RESOURCE_OWNER
    (HTTP 403)."

    Design: Corner/rbac/customer_cannot_mutate_other_customers_job
    """
    owner = create_customer(full_name="OwnerA")
    intruder = create_customer(full_name="OwnerB")
    catalog = create_catalog()
    job = create_job(owner, catalog["id"])
    res = api.add_room(job["id"], {"area_label": "Intruder", "area_sqft": 50, "soiling_level": "LIGHT"},
                       make_customer_headers(intruder["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def _list(response):
    body = response.json()
    return body["data"], body["meta"]
