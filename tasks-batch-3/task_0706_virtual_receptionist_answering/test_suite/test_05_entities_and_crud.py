"""Entity creation, immutability, computed-on-create fields, defaults, FK
integrity, required-field/enum validation, and the listing envelope."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    assert_service_plan,
    fixtures as fx, factories as f,
    make_platform_admin_headers, make_account_owner_headers,
)

ADMIN = make_platform_admin_headers()


# =============================================================================
# Corner / entities / service_plan_create_returns_201_and_fields
# =============================================================================
def test_service_plan_create_returns_201_with_echoed_fields(api):
    """PRD §4: "Operations that create a new, stand-alone resource return 201
    Created."
    PRD §3.1: "A plan is created with a name and a billing_model, which is either
    PER_MINUTE or PER_CALL."

    Creating a service plan returns 201 and echoes name, billing_model, and
    base_fee_cents.

    Design: Corner/entities/service_plan_create_returns_201_and_fields
    """
    plan = validate_success(api.create_service_plan(
        f.create_per_minute_plan_payload(
            name="Basic", base_fee_cents=1000, included_minutes=60), ADMIN),
        expected_status=201)
    assert plan["billing_model"] == "PER_MINUTE"
    assert plan["base_fee_cents"] == 1000
    assert_service_plan(plan)


# =============================================================================
# Corner / entities / service_plan_immutable_no_version_field
# =============================================================================
def test_service_plan_carries_no_version_field(api):
    """PRD §2.4: "A ServicePlan is an immutable price card: once created it is never
    modified, so it carries only id and created_at. A ServicePlan has no updated_at
    field and no version field."

    A fetched service plan contains id and created_at but no version field.

    Design: Corner/entities/service_plan_immutable_no_version_field
    """
    created = get_success_data(api.create_service_plan(
        f.create_per_call_plan_payload(name="Basic", base_fee_cents=1000), ADMIN))
    fetched = validate_success(api.get_service_plan(created["id"], ADMIN))
    assert "id" in fetched and "created_at" in fetched
    assert "version" not in fetched, "ServicePlan must NOT carry a version field"
    assert "updated_at" not in fetched, "ServicePlan must NOT carry an updated_at field"


# =============================================================================
# Corner / entities / plan_misconfigured_per_minute_with_included_calls
# =============================================================================
def test_per_minute_plan_with_included_calls_misconfigured(api):
    """PRD §3.1: "A plan that mixes the two — a PER_MINUTE plan declaring a positive
    included_calls, or a PER_CALL plan declaring a positive included_minutes — is
    misconfigured and rejected with ERR_PLAN_MISCONFIGURED."

    A PER_MINUTE plan that declares a positive included_calls is rejected with
    ERR_PLAN_MISCONFIGURED.

    Design: Corner/entities/plan_misconfigured_per_minute_with_included_calls
    """
    resp = api.create_service_plan(
        f.create_per_minute_plan_payload(
            name="Bad", base_fee_cents=1000, included_minutes=60, included_calls=5), ADMIN)
    validate_error(resp, ApiErrorId.ERR_PLAN_MISCONFIGURED.value)


# =============================================================================
# Corner / entities / account_create_opens_first_billing_period
# =============================================================================
def test_account_create_opens_first_billing_period(api):
    """PRD §3.1: "A newly created account starts with status of ACTIVE. Creating an
    account also opens the account's first BillingPeriod: a period whose
    period_index is 0, whose plan_id snapshots the account's plan, and whose
    included_units is pinned from that plan — included_minutes for a PER_MINUTE
    plan, included_calls for a PER_CALL plan. The new period's status is OPEN, and
    the account's current_period_id is set to point at it."

    Creating an account on a PER_MINUTE plan (included_minutes=60) yields an ACTIVE
    account whose current_period_id points to an OPEN period_index-0 period with
    included_units 60.

    Design: Corner/entities/account_create_opens_first_billing_period
    """
    plan = get_success_data(api.create_service_plan(
        f.create_per_minute_plan_payload(name="P60", base_fee_cents=0, included_minutes=60),
        ADMIN))
    account = validate_success(api.create_account(
        f.create_account_payload(plan["id"], business_name="Acme"), ADMIN),
        expected_status=201)
    assert account["status"] == "ACTIVE"
    assert account["current_period_id"]

    period = validate_success(api.get_billing_period(account["current_period_id"], ADMIN))
    assert period["period_index"] == 0
    assert period["included_units"] == 60, (
        f"included_units {period['included_units']} != 60 (pinned from plan)")
    assert period["status"] == "OPEN"


# =============================================================================
# Corner / entities / account_default_language_defaults_to_en
# =============================================================================
def test_account_default_language_defaults_to_en(api):
    """PRD §3.1: "an optional default_language that is either EN or ES and defaults
    to EN."

    Omitting default_language on account create applies EN.

    Design: Corner/entities/account_default_language_defaults_to_en
    """
    plan = get_success_data(api.create_service_plan(
        f.create_per_call_plan_payload(name="Pd", base_fee_cents=0), ADMIN))
    account = validate_success(api.create_account(
        f.create_account_payload(plan["id"], business_name="Defaulty"), ADMIN),
        expected_status=201)
    assert account["default_language"] == "EN", (
        f"default_language {account['default_language']} != EN")


# =============================================================================
# Corner / entities / account_get_not_found
# =============================================================================
def test_get_account_not_found(api):
    """PRD §2.8: "Every identifier a request references — whether it appears in the
    URL path or as a foreign-key field in the body — must resolve to an existing
    resource ... the first identifier that does not resolve produces ERR_NOT_FOUND
    immediately".

    GETting a non-existent account id returns ERR_NOT_FOUND.

    Design: Corner/entities/account_get_not_found
    """
    resp = api.get_account("00000000-0000-0000-0000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# =============================================================================
# Corner / entities / call_script_missing_required_field
# =============================================================================
def test_call_script_missing_greeting_en_rejected(api):
    """PRD §3.2: "A script supplies an English greeting in greeting_en".
    PRD §2.7: "Required-field presence and enum/range validity (ERR_INVALID_REQUEST)
    is the lowest-priority check, applied last."

    Creating a call script without the required greeting_en is rejected with
    ERR_INVALID_REQUEST.

    Design: Corner/entities/call_script_missing_required_field
    """
    plan = get_success_data(api.create_service_plan(
        f.create_per_call_plan_payload(name="Ps", base_fee_cents=0), ADMIN))
    account = get_success_data(api.create_account(
        f.create_account_payload(plan["id"], business_name="Sigma"), ADMIN))
    owner = make_account_owner_headers(account["id"])
    resp = api.create_call_script(
        {"account_id": account["id"], "business_open_minute": 540, "business_close_minute": 1020},
        owner)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# =============================================================================
# Corner / entities / receptionist_languages_enum_constraint
# =============================================================================
def test_receptionist_invalid_language_rejected(api):
    """PRD §3.3: "a non-empty languages array whose values are drawn from EN and
    ES".
    PRD §2.7: "Required-field presence and enum/range validity (ERR_INVALID_REQUEST)
    is the lowest-priority check".

    Creating a receptionist with a language outside {EN, ES} is rejected with
    ERR_INVALID_REQUEST.

    Design: Corner/entities/receptionist_languages_enum_constraint
    """
    resp = api.create_receptionist(
        {"display_name": "Bad", "languages": ["FR"], "max_concurrent_calls": 1}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# =============================================================================
# Corner / entities / call_script_unknown_account_fk_not_found
# =============================================================================
def test_call_script_unknown_account_fk_rejected(api):
    """PRD §2.8: "Every identifier a request references — whether it appears in the
    URL path or as a foreign-key field in the body — must resolve to an existing
    resource. These are validated left-to-right in the order they appear, and the
    first identifier that does not resolve produces ERR_NOT_FOUND immediately".

    Creating a call script whose account_id FK does not exist is rejected with
    ERR_NOT_FOUND.

    Design: Corner/entities/call_script_unknown_account_fk_not_found
    """
    missing = "00000000-0000-0000-0000-000000000000"
    owner = make_account_owner_headers(missing)
    resp = api.create_call_script(
        {"account_id": missing, "greeting_en": "hi",
         "business_open_minute": 540, "business_close_minute": 1020}, owner)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# =============================================================================
# Corner / entities / list_service_plans_pagination_envelope
# =============================================================================
def test_list_service_plans_pagination_envelope(api):
    """PRD §2.3: "List endpoints are paginated through two query parameters. The
    limit parameter caps the number of items returned ... Every list response
    includes limit, offset, total_count, and has_more in the meta object of the
    envelope."

    With two plans created and limit=1, the list returns one item, total_count 2,
    and has_more true.

    Design: Corner/entities/list_service_plans_pagination_envelope
    """
    get_success_data(api.create_service_plan(
        f.create_per_call_plan_payload(name="L1", base_fee_cents=0), ADMIN))
    get_success_data(api.create_service_plan(
        f.create_per_minute_plan_payload(name="L2", base_fee_cents=0, included_minutes=60),
        ADMIN))

    data, meta = validate_paginated(api.list_service_plans(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"total_count {meta['total_count']} != 2"
    assert meta["has_more"] is True, "has_more must be true (limit 1 < total 2)"
    assert len(data) == 1, f"page length {len(data)} != 1 (limit 1)"
