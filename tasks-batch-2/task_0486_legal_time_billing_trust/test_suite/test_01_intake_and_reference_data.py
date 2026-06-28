"""Client / timekeeper / billing-code intake, reference data, RBAC, and auth.

Each test translates exactly one corner-design instance (queue B).
"""
import pytest
from test_helpers import (
    api_client,
    TEST_USERS,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_client_payload, create_timekeeper_payload, create_billing_code_payload,
    create_matter_payload,
    assert_client, assert_timekeeper,
    create_timekeeper, create_client, ensure_billing_codes, create_flagged_matter,
    setup_draft_invoice,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]
ATT = TEST_USERS["attorney_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# Section 1 — Entities
# ---------------------------------------------------------------------------
def test_create_client_returns_201_with_defaults(api):
    """PRD §3.1: "A newly created client starts life in `status` `PROSPECT`
    with an `ar_balance_cents` of 0."

    Design: Corner/entities/create_client_returns_201_with_defaults
    """
    data = validate_success(
        api.create_client(create_client_payload(), CLERK), expected_status=201)
    assert_client(data)
    assert data["status"] == "PROSPECT"
    assert data["ar_balance_cents"] == 0
    assert data["version"] == 1


def test_get_client_returns_stored_entity(api):
    """PRD §3.1: "A firm begins by registering a `Client`, supplying a
    `display_name` (the client's legal name, one to two hundred characters) and a
    `client_type` of either `INDIVIDUAL` or `ORGANIZATION`."

    Design: Corner/entities/get_client_returns_stored_entity
    """
    created = validate_success(
        api.create_client(create_client_payload(display_name="Acme Corp",
                                                client_type="ORGANIZATION"), CLERK),
        expected_status=201)
    data = validate_success(api.get_client(created["id"], ATT))
    assert data["display_name"] == "Acme Corp"
    assert data["client_type"] == "ORGANIZATION"


def test_list_clients_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_clients_paginated_envelope
    """
    validate_success(api.create_client(create_client_payload(display_name="Acme Corp"), CLERK),
                     expected_status=201)
    validate_success(api.create_client(create_client_payload(display_name="Beta LLC"), CLERK),
                     expected_status=201)
    data, meta = validate_paginated(api.list_clients(CLERK, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_get_client_not_found(api):
    """PRD §2.6: "The first identifier that does not resolve to an existing
    resource causes the request to be rejected immediately with `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_client_not_found
    """
    validate_error(api.get_client(NON_EXISTENT, CLERK), ApiErrorId.ERR_NOT_FOUND)


def test_create_client_missing_required_field(api):
    """PRD §2.10: "Last of all comes generic body validation
    (`ERR_INVALID_REQUEST`) for missing or malformed fields, bad enums, and
    non-positive numeric inputs".

    Design: Corner/entities/create_client_missing_required_field
    """
    validate_error(
        api.create_client({"display_name": "Acme Corp"}, CLERK),
        ApiErrorId.ERR_INVALID_REQUEST)


def test_create_client_invalid_enum_rejected(api):
    """PRD §2.10: "Last of all comes generic body validation
    (`ERR_INVALID_REQUEST`) for missing or malformed fields, bad enums, and
    non-positive numeric inputs".

    Design: Corner/entities/create_client_invalid_enum_rejected
    """
    validate_error(
        api.create_client(create_client_payload(client_type="COMPANY"), CLERK),
        ApiErrorId.ERR_INVALID_REQUEST)


def test_timekeeper_is_active_default_true(api):
    """PRD §3.10: "a non-negative `standard_rate_cents`, and an optional
    `is_active` flag defaulting to true".

    Design: Corner/entities/timekeeper_is_active_default_true
    """
    data = validate_success(
        api.create_timekeeper(create_timekeeper_payload(), ADMIN), expected_status=201)
    assert data["is_active"] is True


def test_time_entry_resolved_rate_is_computed_not_input(api):
    """PRD §3.3: "The highest-precedence tier is the matter's own negotiated
    rate: if the matter's `matter_rate_cents` is present (non-null), the resolved
    rate is exactly that value."
    PRD §3.4: "The number of billable tenths of an hour is the worked `minutes`
    divided by 6, rounded up to the next whole tenth".

    Design: Corner/entities/time_entry_resolved_rate_is_computed_not_input
    """
    from test_helpers import create_open_matter, capture_time_entry
    ensure_billing_codes()
    matter, client_id, tk_id = create_open_matter(matter_rate_cents=30000)
    te = capture_time_entry(matter["id"], tk_id, minutes=60)
    assert te["resolved_rate_cents"] == 30000
    # 30000 * ceil(60/6)/10 = 30000 * 10 / 10 = 30000
    assert te["billable_amount_cents"] == 30000


def test_billing_code_immutable_no_version_field(api):
    """PRD §2.4: "A `BillingCode` and a `TrustTransaction` each carry only an `id`
    and a `created_at`; neither has an `updated_at` and neither has a `version`."

    Design: Corner/entities/billing_code_immutable_no_version_field
    """
    validate_success(
        api.create_billing_code(create_billing_code_payload("L110", "TASK", "Fact Investigation"),
                                ADMIN), expected_status=201)
    data, _ = validate_paginated(api.list_billing_codes(CLERK, params={"kind": "TASK"}))
    assert len(data) >= 1
    code = data[0]
    assert "id" in code and "created_at" in code
    assert "version" not in code, "BillingCode must not expose version"
    assert "updated_at" not in code, "BillingCode must not expose updated_at"


def test_matter_requires_existing_client_parent(api):
    """PRD §2.6: "The first identifier that does not resolve to an existing
    resource causes the request to be rejected immediately with `ERR_NOT_FOUND`
    (HTTP 404), before any later identifier is examined and before any state or
    business check is attempted."

    Design: Corner/entities/matter_requires_existing_client_parent
    """
    tk_id = create_timekeeper()["id"]
    validate_error(
        api.create_matter(create_matter_payload(NON_EXISTENT, tk_id, title="Ghost"), CLERK),
        ApiErrorId.ERR_NOT_FOUND)


def test_code_kind_mismatch_on_time_entry(api):
    """PRD §2.7: "A time entry's `utbms_task_code` must reference a `BillingCode`
    whose `kind` is `TASK`". PRD §2.7: "Any of these kind violations is rejected
    with `ERR_CODE_KIND_MISMATCH` (HTTP 422)."

    Design: Corner/entities/code_kind_mismatch_on_time_entry
    """
    from test_helpers import create_open_matter, create_time_entry_payload
    # Only A101 (ACTIVITY) exists; using it as the task code is a kind mismatch.
    validate_success(
        api.create_billing_code(create_billing_code_payload("A101", "ACTIVITY", "Plan and prepare"),
                                ADMIN), expected_status=201)
    matter, client_id, tk_id = create_open_matter(matter_rate_cents=50000)
    payload = create_time_entry_payload(matter["id"], tk_id, minutes=60,
                                        utbms_task_code="A101", utbms_activity_code="A101")
    validate_error(api.create_time_entry(payload, ATT), ApiErrorId.ERR_CODE_KIND_MISMATCH)


def test_duplicate_billing_code_rejected(api):
    """PRD §3.10: "Attempting to create a code whose `code` already exists is
    rejected with `ERR_DUPLICATE_CODE` (HTTP 409)."

    Design: Corner/entities/duplicate_billing_code_rejected
    """
    validate_success(
        api.create_billing_code(create_billing_code_payload("L110", "TASK", "Fact Investigation"),
                                ADMIN), expected_status=201)
    validate_error(
        api.create_billing_code(create_billing_code_payload("L110", "TASK", "Duplicate"), ADMIN),
        ApiErrorId.ERR_DUPLICATE_CODE)


# ---------------------------------------------------------------------------
# Section 6 — Errors (auth)
# ---------------------------------------------------------------------------
def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "A request missing either header is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_missing_headers
    """
    validate_error(
        api.create_client(create_client_payload(), headers={}),
        ApiErrorId.ERR_UNAUTHENTICATED)


# ---------------------------------------------------------------------------
# Section 7 — RBAC
# ---------------------------------------------------------------------------
def test_billingclerk_cannot_waive_conflict(api):
    """PRD §4 endpoint table: "POST `/firm/conflict-checks/{id}/waive` | Partner
    waiver of a FLAGGED conflict | Attorney". PRD §2.1: "When a present,
    authenticated role is not permitted to perform the requested operation, the
    request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/billingclerk_cannot_waive_conflict
    """
    matter, cc, _, _, _ = create_flagged_matter()
    validate_error(api.waive_conflict_check(cc["id"], CLERK), ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_billingclerk_cannot_create_timekeeper(api):
    """PRD §2.1: "in addition to its exclusive configuration powers (creating
    timekeepers, creating billing codes, creating trust accounts, and advancing
    the logical clock)." PRD §2.1: "the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/billingclerk_cannot_create_timekeeper
    """
    validate_error(
        api.create_timekeeper(create_timekeeper_payload(), CLERK),
        ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_attorney_cannot_finalize_invoice(api):
    """PRD §4 endpoint table: "POST `/firm/invoices/{id}/finalize` | Finalize a
    DRAFT invoice and issue it | BillingClerk, PlatformAdmin". PRD §2.1: "the
    request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/attorney_cannot_finalize_invoice
    """
    base = setup_draft_invoice()
    validate_error(api.finalize_invoice(base["invoice"]["id"], {}, ATT),
                   ApiErrorId.ERR_FORBIDDEN_ROLE)
