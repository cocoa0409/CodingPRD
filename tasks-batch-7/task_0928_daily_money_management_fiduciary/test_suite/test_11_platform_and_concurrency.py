"""Platform-level behaviour: enum membership, listing pagination,
authentication, optimistic concurrency, and the logical clock's default."""

from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    account_version,
    add_payee,
    api_client,
    assert_instant_rendering,
    assert_same_instant,
    create_active_client,
    create_client,
    create_payee_payload,
    payment_request,
    read_account,
    read_budget_category,
    register_bond,
    schedule_payment,
    set_clock,
    setup_billpay_world,
    list_payments,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["fiduciary_manager_headers"]
SPECIALIST = TEST_USERS["bill_pay_specialist_headers"]


def test_an_unknown_payee_type_is_refused_at_the_enum_membership_rung():
    """PRD §2.9 rung 5: "**Enum membership.** Every enum-typed input field
    holds a declared member of its enumeration; otherwise `ERR_INVALID_ENUM`
    (422). This rung is a **closed, exhaustive list** — exactly the following
    fields route here and **no other field routes to `ERR_INVALID_ENUM`**: an
    authorization's `scope_tier`; an account's `account_type`; a payee's
    `payee_type`; a payment's `channel`;"
    PRD §3.2: "A `BillPaySpecialist` or `FiduciaryManager` registers one by
    naming the `client_id` it serves, the `payee_name`, a `payee_type` of
    `RECURRING_BILLER`, `ESSENTIAL` or `DISCRETIONARY`, and the
    `remittance_reference` — the account or invoice number the practice quotes
    when remitting."

    Design: Corner/entities/corner_payee_type_invalid_enum_rejected
    """
    set_clock("2026-06-01T09:00:00Z")
    client = create_client(intake_reference="INT-C004")

    response = api_client.create_payee(
        create_payee_payload(client["id"], payee_type="UTILITY_VENDOR"), SPECIALIST
    )

    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value, 422)


def test_the_payments_listing_reports_total_count_and_has_more():
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
    and `has_more` inside the `meta` object; `total_count` counts the rows that
    survived filtering before pagination was applied, and `has_more` is true
    exactly when the sum of `offset` and the number of returned rows is less
    than `total_count`."
    PRD §2.3: "The `offset` parameter says how many rows to skip and defaults
    to 0, with a minimum of 0."

    Design: Corner/entities/corner_payments_list_pagination_reports_total_count_and_has_more
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    second_payee = add_payee(world)
    schedule_payment(world, amount_cents=50000, channel="ACH")
    schedule_payment(world, amount_cents=60000, channel="ACH", payee=second_payee)

    first_page, first_meta = validate_paginated(
        api_client.list_payments(
            MANAGER, {"account_id": world["account"]["id"], "limit": 1, "offset": 0}
        )
    )
    assert len(first_page) == 1
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api_client.list_payments(
            MANAGER, {"account_id": world["account"]["id"], "limit": 1, "offset": 1}
        )
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False
    assert second_page[0]["id"] != first_page[0]["id"]


def test_a_request_carrying_no_auth_headers_is_refused_before_existence():
    """PRD §2.1: "Every request to the API must carry two headers:
    `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's
    role. If either header is absent, or if `X-User-Role` holds a string that
    is not one of the seven role names below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401). This check runs before anything else, on
    every endpoint including the reads and the operational endpoints."

    Design: Corner/rbac/corner_missing_auth_headers_returns_unauthenticated
    """
    set_clock("2026-06-01T09:00:00Z")

    response = api_client.get_client(NON_EXISTENT_UUID, NO_AUTH_HEADERS)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_a_stale_account_version_refuses_the_second_payment():
    """PRD §2.10: "Scheduling a payment requires `expected_account_version`,
    carrying the client's last observed `version` of the `ClientAccount` named
    by `account_id`. Two payments against the same account are both legitimate;
    what makes the second unsafe is that the preparer committed funds against a
    balance picture that a deposit, a hold, a settlement, a cancellation or an
    earlier payment has already moved. If the account's `version` has advanced
    since the preparer read it, the schedule is refused with
    `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_account_version_rejected_on_payment_create
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    observed = account_version(world["account"]["id"])

    first = payment_request(
        world, amount_cents=80000, channel="ACH", expected_account_version=observed
    )
    validate_success(first, 201)

    second = payment_request(
        world, amount_cents=30000, channel="ACH", expected_account_version=observed
    )

    validate_error(second, ApiErrorId.ERR_STALE_VERSION.value, 412)
    assert len(list_payments(account_id=world["account"]["id"])) == 1
    assert read_account(world["account"]["id"])["committed_disbursements_cents"] == 80500
    assert read_budget_category(world["budget_category"]["id"])["committed_cents"] == 80000


def test_the_logical_clock_starts_at_the_fixed_startup_instant():
    """PRD §2.4: "Before any caller has moved it, the logical clock reads
    exactly `2026-05-01T00:00:00Z`, and it never falls back to real time."
    PRD §2.4: "**Server-written instants** are rendered in ISO 8601 UTC with
    exactly three fractional-second digits and a trailing `Z` — the shape
    `YYYY-MM-DDTHH:MM:SS.mmmZ`, for example `2026-05-01T00:00:00.000Z`. The
    three fractional digits are always present, including when they are all
    zero."

    Design: Corner/endpoints/corner_logical_clock_defaults_to_the_fixed_startup_instant
    """
    # Deliberately no call to the clock endpoint: the server must still be
    # holding its startup instant.
    bond = register_bond(bond_number="SB-DEFAULT")
    client = create_client(intake_reference="INT-C070")

    assert_same_instant(bond["created_at"], "2026-05-01T00:00:00Z", "SuretyBond.created_at")
    assert_instant_rendering(bond["created_at"], "SuretyBond.created_at")
    assert_same_instant(client["created_at"], "2026-05-01T00:00:00Z", "Client.created_at")
    assert_instant_rendering(client["created_at"], "Client.created_at")
