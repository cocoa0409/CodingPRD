"""Access control, optimistic concurrency and the immediate-consistency contract."""

import pytest

from test_helpers import (
    CREDIT_MANAGER,
    FABRICATED_ID,
    PLATFORM_ADMIN,
    PRO_DESK_ASSOCIATE,
    SKU_SHINGLE_BUNDLE,
    STORE_OPERATIONS,
    TAX_COMPLIANCE_OFFICER,
    ApiErrorId,
    create_credit_line,
    create_draft_order,
    create_pro_account,
    create_store,
    create_store_payload,
    create_store_stock,
    counter_offer_line_price,
    get_success_data,
    make_contractor_admin_headers,
    make_credit_manager_headers,
    make_pro_desk_associate_headers,
    read_pro_account,
    setup_fulfilled_will_call_order,
    validate_error,
    validate_paginated,
    validate_success,
)

PLATFORM_ADMIN_HEADERS_WITHOUT_ROLE = {
    "X-User-ID": "admin-1",
    "Content-Type": "application/json",
}
PLATFORM_ADMIN_HEADERS_WITHOUT_ID = {
    "X-User-Role": "PlatformAdmin",
    "Content-Type": "application/json",
}
UNDECLARED_ROLE_HEADERS = {
    "X-User-ID": "rvp-1",
    "X-User-Role": "RegionalVicePresident",
    "Content-Type": "application/json",
}


# =========================================================================== #
# Authentication and role authorization                                       #
# =========================================================================== #


@pytest.mark.parametrize(
    "headers",
    [
        PLATFORM_ADMIN_HEADERS_WITHOUT_ROLE,
        PLATFORM_ADMIN_HEADERS_WITHOUT_ID,
        UNDECLARED_ROLE_HEADERS,
    ],
    ids=["no_role_header", "no_user_id_header", "role_outside_the_declared_six"],
)
def test_missing_or_undeclared_headers_are_rejected(api, headers):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which it is acting. If either header is absent, or if `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."
    PRD §2.11: "**Authentication** — the headers are present and `X-User-Role` names a declared role, otherwise `ERR_UNAUTHENTICATED`. Applies everywhere."

    Design: Corner/rbac/missing_or_undeclared_headers_are_rejected_before_any_lookup
    """
    store = create_store(store_code="HD-101")

    validate_error(
        api.get_store(store["id"], headers),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        expected_status=401,
    )


def test_authentication_is_checked_before_the_path_id_is_resolved(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."
    PRD §2.11: "**Path resolution** — every identifier in the path resolves, left to right, otherwise that resource type's not-found error. Applies to every endpoint with a path parameter."
    PRD §4: "A request with a missing or unrecognized identity header is rejected with `401 Unauthorized` and a request whose role is not listed for the endpoint with `403 Forbidden`, both before any other check; the status code attached to every other failure is given in §5."

    Design: Corner/rbac/missing_or_undeclared_headers_are_rejected_before_any_lookup
    """
    store = create_store(store_code="HD-101")

    # An id that resolves to nothing would be a 404 for an authenticated caller.
    validate_error(
        api.get_store(FABRICATED_ID, UNDECLARED_ROLE_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        expected_status=401,
    )

    readable = validate_success(
        api.get_store(store["id"], PLATFORM_ADMIN), expected_status=200
    )
    assert readable["store_code"] == "HD-101"


def test_exclusive_operations_reject_every_other_declared_role(api):
    """PRD §2.1: "Each endpoint publishes the roles permitted to invoke it (see §4); a well-formed request from a role that is not on that list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.11: "**Role authorization** — the acting role appears in the target endpoint's role list, otherwise `ERR_FORBIDDEN_ROLE`. Applies everywhere."

    Design: Corner/rbac/exclusive_operations_reject_every_other_declared_role
    """
    store = create_store(store_code="HD-101")
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    account = create_pro_account(store["id"], business_name="Role Test Remodeling")
    admin_headers = make_contractor_admin_headers(account["id"])

    order, _ = create_draft_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )

    # Registering a store belongs to the platform, not to a contractor.
    validate_error(
        api.create_store(
            create_store_payload(
                store_code="HD-999",
                distance_rank=9,
                will_call_bay_slots=1,
                lift_gate_available=False,
                tax_rate_pct=0.0500,
                max_stage_hours=12,
            ),
            admin_headers,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        expected_status=403,
    )
    # Opening a credit line belongs to credit, not to the platform.
    validate_error(
        api.create_credit_line(
            {
                "pro_account_id": account["id"],
                "limit_cents": 500000,
                "terms_days": 30,
            },
            PLATFORM_ADMIN,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        expected_status=403,
    )
    # Submitting an order belongs to the contractor, not to the yard.
    validate_error(
        api.submit_pro_order(order["id"], STORE_OPERATIONS),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        expected_status=403,
    )
    # Reading an order is closed to the tax role entirely.
    validate_error(
        api.get_pro_order(order["id"], TAX_COMPLIANCE_OFFICER),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        expected_status=403,
    )

    # None of the refusals wrote anything on the way out.
    stores, stores_meta = validate_paginated(api.list_stores(PLATFORM_ADMIN))
    assert stores_meta["total_count"] == 1
    assert [row["store_code"] for row in stores] == ["HD-101"]

    lines_of_credit, credit_meta = validate_paginated(
        api.list_credit_lines(CREDIT_MANAGER, params={"pro_account_id": account["id"]})
    )
    assert credit_meta["total_count"] == 0
    assert lines_of_credit == []

    submitted = validate_success(
        api.submit_pro_order(order["id"], admin_headers), expected_status=200
    )
    assert submitted["fulfillment_status"] == "SUBMITTED"


def test_contractor_admin_identity_is_scoped_to_its_own_pro_account(api):
    """PRD §2.1: "When `X-User-Role` is `ContractorAdmin`, `X-User-ID` is the `id` of the acting `ProAccount`; ownership checks on any resource that references a `ProAccount` compare the resource's foreign-key field to `X-User-ID`."
    PRD §2.1: "A `ContractorAdmin` acting on a resource that resolves to a different account is rejected with `ERR_ACCOUNT_SCOPE_VIOLATION` (HTTP 403)."
    PRD §2.11: "**Account scope** — a `ContractorAdmin`'s `X-User-ID` equals the `pro_account_id` owning the target resource, otherwise `ERR_ACCOUNT_SCOPE_VIOLATION`. Applies to every `ContractorAdmin` operation."

    Design: Corner/rbac/contractor_admin_identity_is_scoped_to_its_own_pro_account
    """
    store = create_store(store_code="HD-101")
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    account_a = create_pro_account(store["id"], business_name="Account A Builders")
    account_b = create_pro_account(store["id"], business_name="Account B Builders")
    a_headers = make_contractor_admin_headers(account_a["id"])
    b_headers = make_contractor_admin_headers(account_b["id"])

    order_a, order_a_lines = create_draft_order(
        account_a["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )

    validate_error(
        api.get_pro_order(order_a["id"], b_headers),
        ApiErrorId.ERR_ACCOUNT_SCOPE_VIOLATION.value,
        expected_status=403,
    )
    validate_error(
        api.create_order_line(
            order_a["id"], {"sku": SKU_SHINGLE_BUNDLE, "qty_units": 3}, b_headers
        ),
        ApiErrorId.ERR_ACCOUNT_SCOPE_VIOLATION.value,
        expected_status=403,
    )
    validate_error(
        api.submit_pro_order(order_a["id"], b_headers),
        ApiErrorId.ERR_ACCOUNT_SCOPE_VIOLATION.value,
        expected_status=403,
    )

    kept, kept_meta = validate_paginated(
        api.list_order_lines_of_order(order_a["id"], a_headers)
    )
    assert kept_meta["total_count"] == 1
    assert [row["id"] for row in kept] == [order_a_lines[0]["id"]]

    submitted = validate_success(
        api.submit_pro_order(order_a["id"], a_headers), expected_status=200
    )
    assert submitted["fulfillment_status"] == "SUBMITTED"
    assert submitted["total_cents"] == 21639


def test_the_associate_who_wrote_the_round_may_not_approve_it(api):
    """PRD §2.1: "Those recorded identifiers exist to support one rule in particular: the associate who authored a negotiated round can never be the manager who approves it, and an approval attempt where the acting `CreditManager`'s `X-User-ID` equals the quote's `authored_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §2.11: "**Segregation of duties** — the approving `CreditManager`'s `X-User-ID` differs from the quote's `authored_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. Applies to approving a job quote."
    PRD §3.5: "The quote also records the round's proposed `term_days` as the candidate term, stamps `authored_by_user_id` with the acting associate's `X-User-ID`, increases `round_count` by one, and increments its `version`."
    PRD §3.5: "A `CreditManager` moves the quote from `COUNTERED` to `APPROVED`, which stamps `approved_by_user_id` and increments the quote's `version`."

    Design: Corner/rbac/the_associate_who_wrote_the_round_may_not_approve_it
    """
    store = create_store(store_code="HD-101")
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    account = create_pro_account(store["id"], business_name="Four Eyes Fencing")
    admin_headers = make_contractor_admin_headers(account["id"])

    quote = get_success_data(
        api.create_job_quote(
            {
                "pro_account_id": account["id"],
                "originating_store_id": store["id"],
                "job_name": "SOD-A",
                "requested_term_days": 15,
            },
            admin_headers,
        )
    )
    quote_line = get_success_data(
        api.create_quote_line(
            quote["id"], {"sku": SKU_SHINGLE_BUNDLE, "qty_units": 8}, admin_headers
        )
    )
    submitted = validate_success(
        api.submit_job_quote(quote["id"], admin_headers), expected_status=200
    )

    countered = validate_success(
        api.counter_offer_job_quote(
            quote["id"],
            [counter_offer_line_price(quote_line["id"], 1500)],
            15,
            submitted["version"],
            make_pro_desk_associate_headers("u-7"),
        ),
        expected_status=200,
    )
    assert countered["authored_by_user_id"] == "u-7"

    # The author cannot wear the approver's hat, whatever role header it sends.
    validate_error(
        api.approve_job_quote(quote["id"], make_credit_manager_headers("u-7")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        expected_status=403,
    )
    unchanged = validate_success(api.get_job_quote(quote["id"], CREDIT_MANAGER))
    assert unchanged["status"] == "COUNTERED"
    assert unchanged["approved_by_user_id"] is None

    approved = validate_success(
        api.approve_job_quote(quote["id"], make_credit_manager_headers("u-8")),
        expected_status=200,
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "u-8"
    assert approved["discount_depth_pct"] == 0.2496


# =========================================================================== #
# Optimistic concurrency and threshold exactness                              #
# =========================================================================== #


def test_both_occ_rules_reject_writes_made_against_a_stale_parent_version(api):
    """PRD §2.7: "A counter-offer written on a job quote must carry `expected_job_quote_version`. The field is not optional: the request body must contain the client's last observed `version` of the target `JobQuote`. If that value does not equal the quote's current `version`, the counter-offer is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "A resale certificate filing must carry `expected_pro_account_version`, likewise non-optional, holding the client's last observed `version` of the target `ProAccount`. If it does not equal the account's current `version`, the filing is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "Both rejections carry the same identifier, `ERR_STALE_VERSION`, and the same HTTP 412 status."
    PRD §3.4: "A filing lands in `status` `PENDING` and, as a mutation of the account's exemption picture, increments the owning account's `version` by one."
    PRD §3.5: "A successful round **supersedes** the previous one wholesale. Each named line's `negotiated_unit_price_cents` is overwritten and its `line_negotiated_subtotal_cents` is set to that price multiplied by the line's `qty_units`."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_writes_made_against_a_stale_parent_version
    """
    store = create_store(store_code="HD-101")
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    account = create_pro_account(store["id"], business_name="Stale Read Structures")
    admin_headers = make_contractor_admin_headers(account["id"])
    account_version_at_open = account["version"]

    quote = get_success_data(
        api.create_job_quote(
            {
                "pro_account_id": account["id"],
                "originating_store_id": store["id"],
                "job_name": "OCC-A",
                "requested_term_days": 15,
            },
            admin_headers,
        )
    )
    quote_line = get_success_data(
        api.create_quote_line(
            quote["id"], {"sku": SKU_SHINGLE_BUNDLE, "qty_units": 8}, admin_headers
        )
    )
    submitted = validate_success(
        api.submit_job_quote(quote["id"], admin_headers), expected_status=200
    )
    version_at_submit = submitted["version"]

    first_round = validate_success(
        api.counter_offer_job_quote(
            quote["id"],
            [counter_offer_line_price(quote_line["id"], 1500)],
            15,
            version_at_submit,
            PRO_DESK_ASSOCIATE,
        ),
        expected_status=200,
    )

    # A second round written against the pre-round version is stale.
    validate_error(
        api.counter_offer_job_quote(
            quote["id"],
            [counter_offer_line_price(quote_line["id"], 1400)],
            15,
            version_at_submit,
            PRO_DESK_ASSOCIATE,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
        expected_status=412,
    )
    quote_after = validate_success(api.get_job_quote(quote["id"], PRO_DESK_ASSOCIATE))
    assert quote_after["version"] == first_round["version"]
    assert quote_after["round_count"] == 1
    line_after = validate_success(
        api.get_quote_line(quote_line["id"], PRO_DESK_ASSOCIATE)
    )
    assert line_after["negotiated_unit_price_cents"] == 1500

    first_certificate = validate_success(
        api.create_tax_exempt_certificate(
            {
                "pro_account_id": account["id"],
                "state_code": "IL",
                "certificate_number": "IL-OCC-1",
                "expires_on": "2027-12-31",
                "expected_pro_account_version": account_version_at_open,
            },
            admin_headers,
        ),
        expected_status=201,
    )

    # The filing moved the account's version, so the same figure is now stale.
    superseding_payload = {
        "pro_account_id": account["id"],
        "state_code": "IL",
        "certificate_number": "IL-OCC-2",
        "expires_on": "2028-12-31",
        "expected_pro_account_version": account_version_at_open,
    }
    validate_error(
        api.create_tax_exempt_certificate(superseding_payload, admin_headers),
        ApiErrorId.ERR_STALE_VERSION.value,
        expected_status=412,
    )

    fresh_account = read_pro_account(account["id"])
    assert fresh_account["version"] != account_version_at_open

    superseding_payload["expected_pro_account_version"] = fresh_account["version"]
    second_certificate = validate_success(
        api.create_tax_exempt_certificate(superseding_payload, admin_headers),
        expected_status=201,
    )
    assert second_certificate["status"] == "PENDING"

    certificates, certificates_meta = validate_paginated(
        api.list_tax_exempt_certificates(
            admin_headers, params={"pro_account_id": account["id"]}
        )
    )
    assert certificates_meta["total_count"] == 2
    assert len(certificates) == 2
    assert (
        validate_success(
            api.get_tax_exempt_certificate(
                first_certificate["id"], TAX_COMPLIANCE_OFFICER
            )
        )["certificate_number"]
        == "IL-OCC-1"
    )


@pytest.mark.parametrize(
    "limit_cents,expected_line_status,expected_frozen_reason,expected_available_cents,expected_account_status",
    [
        (91365, "FROZEN", "UTILIZATION_REVIEW", None, "HOLD"),
        (91367, "ACTIVE", None, 9138, "ACTIVE"),
    ],
    ids=["exposure_exactly_at_the_threshold", "one_cent_above_the_exposure"],
)
def test_freeze_threshold_is_exact_at_the_rounded_ninety_percent_mark(
    api,
    limit_cents,
    expected_line_status,
    expected_frozen_reason,
    expected_available_cents,
    expected_account_status,
):
    """PRD §3.3: "Its threshold is 90 percent of the limit: the freeze threshold in cents is `limit_cents` multiplied by nine tenths, rounded half up to a whole cent. When exposure reaches or exceeds that threshold the line freezes."
    PRD §3.9: "Hop two puts that freshly recomputed exposure through the **credit-utilization review**: when `exposure_cents` reaches or exceeds the limit multiplied by 90 percent — rounded half up to a whole cent — the credit line takes its own `ACTIVE` to `FROZEN` transition with `frozen_reason_code` set to `UTILIZATION_REVIEW`."
    PRD §3.9: "Hop three follows from that freeze: the owning account's `status` moves from `ACTIVE` to `HOLD`."
    PRD §3.3: "`available_cents` is `limit_cents` less `exposure_cents`."
    PRD §3.3: "A new line opens with `exposure_cents` at 0, `available_cents` equal to `limit_cents`, `status` `ACTIVE` and `frozen_reason_code` null."

    Design: Corner/cross_cutting_complexity_layers/freeze_threshold_is_exact_at_the_rounded_ninety_percent_mark
    """
    store = create_store(store_code="HD-101", tax_rate_pct=0.0825)
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    account = create_pro_account(store["id"], business_name="Freeze Threshold Framing")
    credit_line = create_credit_line(
        account["id"], limit_cents=limit_cents, terms_days=30
    )
    assert credit_line["status"] == "ACTIVE"
    assert credit_line["frozen_reason_code"] is None

    fulfilled = setup_fulfilled_will_call_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 38)],
        stage_start="2026-08-01T00:00:00Z",
        stage_hours=24,
        payment_method="CREDIT_LINE",
    )
    assert fulfilled["order"]["total_cents"] == 82229

    invoiced = validate_success(
        api.invoice_pro_order(fulfilled["order"]["id"], CREDIT_MANAGER),
        expected_status=200,
    )
    assert invoiced["credit_status"] == "INVOICED"

    line_after = validate_success(api.get_credit_line(credit_line["id"], CREDIT_MANAGER))
    assert line_after["exposure_cents"] == 82229
    assert line_after["status"] == expected_line_status
    assert line_after["frozen_reason_code"] == expected_frozen_reason
    if expected_available_cents is not None:
        assert line_after["available_cents"] == expected_available_cents

    assert read_pro_account(account["id"])["status"] == expected_account_status


# =========================================================================== #
# Consistency model                                                           #
# =========================================================================== #


def test_every_write_is_visible_in_the_same_response_and_the_next_read(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.6: "On success the server writes `tier_code_applied`, every order-line price field and every order money field, stamps `priced_at` with the current clock instant, recomputes the credit line's `exposure_cents` and `available_cents`, and increments the order's `version`."
    PRD §3.3: "Exposure is a recomputed aggregate, never an incrementally adjusted balance."
    PRD §3.1: "`reserved_units` is always the sum of `qty_units` across the reservations at that store for that SKU whose status is `HELD` or `ALLOCATED`, and `available_units` is `on_hand_units` less `reserved_units`; both are recomputed whenever a reservation is created, released or consumed, and reads of a position always show live figures."
    PRD §3.7: "Its `status` starts at `HELD` and its `released_reason_code` is null."

    Design: Corner/consistency_model/every_write_is_visible_in_the_same_response_and_the_next_read
    """
    store = create_store(store_code="HD-101", tax_rate_pct=0.0825)
    stock = create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    account = create_pro_account(store["id"], business_name="Read Your Writes Roofing")
    credit_line = create_credit_line(account["id"], limit_cents=100000, terms_days=30)
    admin_headers = make_contractor_admin_headers(account["id"])

    order, order_lines = create_draft_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CREDIT_LINE",
        delivery_mode="WILL_CALL",
    )

    # The mutation's own response already carries the priced figures.
    submitted = validate_success(
        api.submit_pro_order(order["id"], admin_headers), expected_status=200
    )
    assert submitted["total_cents"] == 21639
    assert submitted["tax_cents"] == 1649
    assert submitted["tier_code_applied"] == "MEMBER"

    # First read after the write, with no retry and no polling in between.
    line_after_submit = validate_success(
        api.get_credit_line(credit_line["id"], CREDIT_MANAGER)
    )
    assert line_after_submit["exposure_cents"] == 21639
    assert line_after_submit["available_cents"] == 78361

    priced_line = validate_success(
        api.get_order_line(order_lines[0]["id"], admin_headers)
    )
    assert priced_line["effective_unit_price_cents"] == 1999
    assert priced_line["price_source"] == "TIER_DISCOUNTED"

    reservations = get_success_data(
        api.reserve_pro_order(order["id"], PRO_DESK_ASSOCIATE)
    )
    position = validate_success(api.get_store_stock(stock["id"], PRO_DESK_ASSOCIATE))
    assert position["reserved_units"] == 10
    assert position["available_units"] == 590

    held = validate_success(
        api.get_reservation(reservations[0]["id"], PRO_DESK_ASSOCIATE)
    )
    assert held["status"] == "HELD"
    assert held["qty_units"] == 10
