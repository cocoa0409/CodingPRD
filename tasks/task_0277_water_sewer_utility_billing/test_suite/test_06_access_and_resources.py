"""Resource creation/validation, access control, listing, and immediate
consistency.

Translates Corner queue: entities, rbac, endpoints, consistency_model sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    fixtures, factories, TEST_USERS, make_customer_headers,
    NON_EXISTENT_UUID, ApiErrorId, assert_account,
)

CLERK = TEST_USERS["billing_clerk_headers"]
FIELDOPS = TEST_USERS["field_ops_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


# ===========================================================================
# Account creation defaults & not-found / required-field / enum validation
# ===========================================================================
def test_create_account_returns_201_with_defaults(api):
    """PRD §3.2: "A freshly created account starts life with `balance_due_cents` at
    zero, `billing_status` of `CURRENT`, and `service_status` of `ACTIVE`."
    PRD §2.4: "a `version` integer that begins at 1 and increments by one on every
    mutation."

    Design: Corner/entities/create_account_returns_201_with_defaults
    """
    rs = fixtures.create_rate_schedule()
    acct = validate_success(
        api.create_account(factories.account_payload(rs["id"], holder_name="Jane"), CLERK), 201)
    assert acct["billing_status"] == "CURRENT"
    assert acct["service_status"] == "ACTIVE"
    assert acct["balance_due_cents"] == 0
    assert acct["version"] == 1
    assert_account(acct)


def test_get_account_not_found_returns_404(api):
    """PRD §2.8: "the server validates the path identifiers left to right and rejects
    the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to
    an existing resource, before considering the body."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    resp = api.get_account(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_account_missing_required_field_returns_422(api):
    """PRD §2.8: "Only after existence is confirmed does the server validate the
    body's required fields and enum domains; a missing or ill-typed field, or an enum
    value outside its declared set, is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_account_missing_required_field_returns_422
    """
    rs = fixtures.create_rate_schedule()
    payload = {"rate_schedule_id": rs["id"], "service_address": "1 Main"}  # holder_name omitted
    resp = api.create_account(payload, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_meter_invalid_enum_type_returns_422(api):
    """PRD §3.2: "The `meter_type` is either `POTABLE` — an indoor meter whose
    consumption is both water-billable and sewer-billable — or `IRRIGATION` — a
    second, outdoor meter whose consumption is water-billable but never contributes
    to the sewer charge."
    PRD §2.8: "a missing or ill-typed field, or an enum value outside its declared
    set, is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/meter_invalid_enum_type_returns_422
    """
    rs = fixtures.create_rate_schedule()
    account = fixtures.create_account(rs["id"])
    resp = api.create_meter(account["id"], {"meter_type": "GAS", "serial": "G1"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Listing & pagination envelope
# ===========================================================================
def test_list_accounts_paginated_envelope(api):
    """PRD §2.3: "Every list response includes the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` inside the response envelope's `meta`
    object."

    Design: Corner/entities/list_accounts_paginated_envelope
    """
    rs = fixtures.create_rate_schedule()
    fixtures.create_account(rs["id"], holder_name="A", service_address="1 Main")
    fixtures.create_account(rs["id"], holder_name="B", service_address="2 Main")
    data, meta = validate_paginated(api.list_accounts(CLERK, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_list_bills_filtered_by_account_id(api):
    """PRD §3.4: "bills can be listed with optional filters on `account_id`,
    `billing_cycle_id`, `rate_schedule_id`, and `status`."

    Design: Corner/endpoints/list_bills_filtered_by_account_id
    """
    account, bill, rs, cycle, _, _ = fixtures.setup_canonical_draft_bill(potable=6000, irrigation=None)
    data, meta = validate_paginated(api.list_bills(CLERK, params={"account_id": account["id"]}))
    assert meta["total_count"] == 1
    assert all(b["account_id"] == account["id"] for b in data)


def test_list_meters_for_account_reverse_reachability(api):
    """PRD §3.2: "Meters for an account can be listed by reaching through the
    account, and an individual meter can be fetched directly."

    Design: Corner/endpoints/list_meters_for_account_reverse_reachability
    """
    rs = fixtures.create_rate_schedule()
    account = fixtures.create_account(rs["id"])
    fixtures.create_meter(account["id"], "POTABLE", "P1")
    fixtures.create_meter(account["id"], "IRRIGATION", "I1")
    data, meta = validate_paginated(api.list_meters(account["id"], CLERK))
    assert meta["total_count"] == 2


def test_pagination_limit_out_of_bounds_returns_422(api):
    """PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is rejected
    with `ERR_VALIDATION_LIMIT`."

    Design: Corner/validations/pagination_limit_out_of_bounds_returns_422
    """
    resp = api.list_accounts(CLERK, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_LIMIT.value)


# ===========================================================================
# RBAC
# ===========================================================================
def test_fieldops_cannot_create_account(api):
    """PRD §2.1: "If the header names a valid role but that role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/fieldops_cannot_create_account
    """
    rs = fixtures.create_rate_schedule()
    resp = api.create_account(factories.account_payload(rs["id"]), FIELDOPS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_customer_cannot_approve_leak_adjustment(api):
    """PRD §2.1: "If the header names a valid role but that role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §3.8: "Adjudication is the caseworker's job."

    Design: Corner/rbac/customer_cannot_approve_leak_adjustment
    """
    account, bill, leak = fixtures.setup_pending_leak_on_posted(
        baseline_gallons=4000, potable=12000, irrigation=None)
    cust = make_customer_headers(account["id"])
    resp = api.approve_leak_adjustment(leak["id"], cust)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_role_header_returns_401(api):
    """PRD §2.1: "If `X-User-Role` is missing or does not name one of the recognized
    roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_401
    """
    no_role_headers = {"X-User-ID": "someone", "Content-Type": "application/json"}
    resp = api.list_accounts(no_role_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Immediate consistency
# ===========================================================================
def test_bill_post_balance_visible_same_request(api):
    """PRD §3.5: "the system finalizes all computed charge fields, confirms the
    pinned `rate_schedule_id`, and increases the account's `balance_due_cents` by the
    bill's `total_cents` through reconciliation."

    Design: Corner/consistency_model/bill_post_balance_visible_same_request
    """
    # Flat 500/kgal, fixed 2000, sewer_ratio 0 -> water_vol(6000)=3000, amount=5000
    rs = fixtures.create_rate_schedule(
        name="Flat",
        water_tiers=[{"up_to_gallons": None, "rate_cents_per_kgal": 500}],
        sewer_rate_cents_per_kgal=0,
        sewer_ratio_pct=0,
    )
    account = fixtures.create_account(rs["id"])
    meter = fixtures.create_meter(account["id"], "POTABLE", "P1")
    cycle = fixtures.create_cycle()
    fixtures.add_read(meter["id"], 0, "2026-01-01T00:00:00Z")
    fixtures.add_read(meter["id"], 6000, "2026-01-20T00:00:00Z")
    bill = fixtures.generate_bill(account["id"], cycle["id"])
    bill = validate_success(api.get_bill(bill["id"], CLERK))
    assert bill["water_volumetric_cents"] == 3000
    assert bill["fixed_charge_cents"] == 2000
    assert bill["amount_billed_cents"] == 5000
    fixtures.post_bill(bill["id"])
    acct = validate_success(api.get_account(account["id"], CLERK))
    assert acct["balance_due_cents"] == 5000
