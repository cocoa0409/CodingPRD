"""Onboarding, resource defaults, access control, pagination, and listing."""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_facility_payload, create_buyer_payload,
    assert_buyer, assert_lien_notice, assert_unit,
    make_platform_admin_headers, make_buyer_headers, make_tenant_headers,
    make_facility_operator_headers,
    setup_matured_unit, create_facility, create_tenant, create_unit,
    CANONICAL,
)

ADMIN = make_platform_admin_headers()


def test_create_facility_missing_name_returns_validation(api):
    """PRD §2.10: "then, on every create-or-action request that carries a body,
    presence of required fields, valid enum values, and non-negative integers
    (else `ERR_VALIDATION`); then the general state check that the target resource
    is in a state permitting the requested transition (else `ERR_INVALID_STATE`)."
    PRD §3.1: "A facility is created with a display `name`, a `state_code` (the US
    state code, retained only for auditing since the tax rate is pinned per
    facility), a `sales_tax_rate_bps` giving the sales-tax rate in basis points
    applied to a buyer's taxable amount, and a `facility_fee_bps` giving the
    facility's auction commission in basis points."

    Design: Corner/entities/create_facility_missing_name_returns_422
    """
    payload = create_facility_payload()
    del payload["name"]
    resp = api.create_facility(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_get_unit_unknown_id_returns_not_found(api):
    """PRD §2.8: "When a path contains identifiers, the system validates their
    existence from left to right and rejects the request with `ERR_NOT_FOUND` at
    the first identifier that does not resolve to an existing resource."

    Design: Corner/entities/get_unit_not_found_returns_404
    """
    resp = api.get_unit(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_new_buyer_deposit_fields_default_zero(api):
    """PRD §3.1: "A buyer's `status` begins at `REGISTERED` and may later become
    `SUSPENDED`; its three deposit fields — `deposit_available_cents` (un-held
    funds), `deposit_held_cents` (funds held against an open winning sale), and
    `deposit_forfeited_cents` (funds cumulatively lost to forfeiture) — all begin
    at zero."

    Design: Corner/entities/buyer_deposit_fields_default_zero
    """
    resp = api.create_buyer(create_buyer_payload(), ADMIN)
    buyer = validate_success(resp, expected_status=201)
    assert_buyer(buyer)
    assert buyer["status"] == "REGISTERED"
    assert buyer["deposit_available_cents"] == 0
    assert buyer["deposit_held_cents"] == 0
    assert buyer["deposit_forfeited_cents"] == 0


def test_lien_notice_creation_stamps_sent_at_and_cure_deadline(api):
    """PRD §2.5: "On server startup the clock reads exactly `2026-03-01T00:00:00Z`,
    and before any call is made the clock holds precisely this default and never
    falls back to wall-clock time."
    PRD §3.2: "The declaration creates a `LienNotice` in `SENT` status, stamps its
    `notice_sent_at` from the logical clock, records the supplied arrears as the
    unit's `past_due_balance_cents`, and sets the notice's `cure_deadline` to
    fourteen days after `notice_sent_at` — the tenant may cure at or before that
    instant."

    Design: Corner/entities/notice_creation_sets_sent_at_and_cure_deadline
    """
    facility = create_facility(api)
    tenant = create_tenant(api, facility["id"])
    unit = create_unit(api, facility["id"], tenant["id"])
    fac_hdr = make_facility_operator_headers(facility["id"])
    resp = api.create_lien_notice(unit["id"], {"past_due_balance_cents": 60000}, fac_hdr)
    notice = validate_success(resp, expected_status=201)
    assert_lien_notice(notice)
    assert notice["status"] == "SENT"
    assert notice["notice_sent_at"].startswith("2026-03-01T00:00:00")
    assert notice["cure_deadline"].startswith("2026-03-15T00:00:00")
    unit_after = validate_success(api.get_unit(unit["id"], ADMIN))
    assert unit_after["status"] == "LIEN_NOTICED"
    assert unit_after["lien_amount_provisional_cents"] == CANONICAL["provisional_lien_cents"]


def test_request_without_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or is not one of the recognised role
    names, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_role_header_returns_401
    """
    headers_without_role = {"X-User-ID": "someone"}
    resp = api.create_facility(create_facility_payload(), headers_without_role)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_tenant_scheduling_auction_is_forbidden(api):
    """PRD §2.1: "If the role is recognised but is not permitted to perform the
    requested operation — or if an ownership-scoped role acts on a resource it does
    not own — the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/validations/tenant_schedule_auction_forbidden
    """
    ctx = setup_matured_unit(api)
    resp = api.create_auction(
        {"unit_id": ctx["unit_id"], "mode": "ONLINE",
         "start_at": "2026-03-21T00:00:00Z", "end_at": "2026-03-22T00:00:00Z",
         "reserve_cents": 50000, "min_increment_cents": 5000},
        make_tenant_headers(ctx["ten"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_buyer_funding_another_buyers_deposit_is_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the
    acting `Buyer`; ownership checks on any resource that references a `Buyer`
    compare the resource's buyer foreign key to `X-User-ID`. A buyer may fund its
    own deposit, bid, retract its own bids, pay, and clean out only its own
    resources."

    Design: Corner/validations/buyer_fund_other_buyer_deposit_forbidden
    """
    buyer1 = validate_success(api.create_buyer(create_buyer_payload(email="b1@x.com"), ADMIN), 201)
    buyer2 = validate_success(api.create_buyer(create_buyer_payload(email="b2@x.com"), ADMIN), 201)
    resp = api.fund_deposit(buyer2["id"], {"amount_cents": 50000}, make_buyer_headers(buyer1["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_list_units_limit_zero_returns_pagination_invalid(api):
    """PRD §2.3: "A `limit` outside the range of 1 through 100 inclusive, or a
    negative `offset`, is rejected with `ERR_PAGINATION_INVALID`."

    Design: Corner/validations/list_units_pagination_limit_zero_returns_422
    """
    resp = api.list_units(ADMIN, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)


def test_list_units_by_facility_returns_paginated_array(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope, where `total_count`
    reflects the full matching set before pagination and `has_more` indicates
    whether items remain beyond the current page."

    Design: Corner/endpoints/list_units_by_facility_paginated_envelope
    """
    facility = create_facility(api)
    tenant = create_tenant(api, facility["id"])
    create_unit(api, facility["id"], tenant["id"], unit_number="U1")
    create_unit(api, facility["id"], tenant["id"], unit_number="U2")
    resp = api.list_units(ADMIN, params={"facility_id": facility["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2
