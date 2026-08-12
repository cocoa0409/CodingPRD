"""Customer account surface, the append-only ledger, and customer OCC."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    is_valid_uuid, is_iso8601_timestamp,
    assert_customer, assert_ledger_entry,
    create_customer, create_part, create_unit,
    credit_adjustment_payload, TEST_USERS,
)

FINANCE = TEST_USERS["finance_controller_headers"]
AGENT = TEST_USERS["aog_desk_agent_headers"]
WAREHOUSE = TEST_USERS["warehouse_operator_headers"]


def test_customer_create_defaults_and_system_fields(api):
    """PRD §3.1: "The new account starts `ACTIVE` with `priority_tier`
    `STANDARD`, a zeroed `outstanding_balance_cents`, zeroed trailing-window
    counters (`core_returns_settled_180d`, `core_returns_on_time_180d`), zero
    `warranty_fraud_flags`, and `version` 1."
    PRD §2.4: "`id` (string): a server-minted UUID with no type prefix" and
    "`created_at` (string): an ISO 8601 UTC timestamp with three fractional
    digits recording when the resource was created."

    Design: Corner/entities/customer_create_defaults_and_system_fields
    """
    created = validate_success(
        api.create_customer(
            {"name": "DefaultAir", "country_code": "DE",
             "credit_limit_cents": 5_000_000},
            FINANCE,
        ),
        201,
    )
    assert created["status"] == "ACTIVE"
    assert created["priority_tier"] == "STANDARD"
    assert created["outstanding_balance_cents"] == 0
    assert created["core_returns_settled_180d"] == 0
    assert created["core_returns_on_time_180d"] == 0
    assert created["warranty_fraud_flags"] == 0
    assert created["version"] == 1
    assert is_valid_uuid(created["id"]) and "_" not in created["id"], (
        "id must be a bare UUID with no type prefix"
    )
    assert is_iso8601_timestamp(created["created_at"])

    fetched = validate_success(api.get_customer(created["id"], FINANCE))
    assert_customer(fetched)
    assert fetched["status"] == "ACTIVE"
    assert fetched["priority_tier"] == "STANDARD"


def test_customer_get_not_found(api):
    """PRD §2.11: "Path identifiers are validated left to right, then body
    foreign-key references; each missing resource surfaces its own not-found
    code:" — for a customer id that is `ERR_CUSTOMER_NOT_FOUND` (404).

    Design: Corner/entities/customer_get_not_found
    """
    res = api.get_customer(NON_EXISTENT_UUID, FINANCE)
    validate_error(res, "ERR_CUSTOMER_NOT_FOUND", expected_status=404)


def test_order_get_not_found(api):
    """PRD §2.11: "Path identifiers are validated left to right, then body
    foreign-key references; each missing resource surfaces its own not-found
    code:" — for an order id that is `ERR_ORDER_NOT_FOUND` (404).

    Design: Corner/consistency_model/order_get_not_found
    """
    res = api.get_order(NON_EXISTENT_UUID, AGENT)
    validate_error(res, "ERR_ORDER_NOT_FOUND", expected_status=404)


def test_core_return_not_found(api):
    """PRD §2.11: "Path identifiers are validated left to right, then body
    foreign-key references; each missing resource surfaces its own not-found
    code:" — for a core-return id that is `ERR_CORE_RETURN_NOT_FOUND` (404).

    Design: Corner/errors/core_return_not_found
    """
    res = api.receive_core_return(
        NON_EXISTENT_UUID, {"core_serial_number": "SN-X"}, WAREHOUSE
    )
    validate_error(res, "ERR_CORE_RETURN_NOT_FOUND", expected_status=404)


def test_ledger_entry_immutability(api):
    """PRD §2.4: "The AccountLedgerEntry is the single exception: it is
    append-only and immutable, so it carries only `id` and `created_at`. Both
    `updated_at` and `version` are absent from ledger entries."
    PRD §3.1: "without it, the entry references the customer itself."

    Design: Corner/entities/ledger_entry_immutability
    """
    customer = create_customer(name="LedgerAir", credit_limit_cents=9_000_000)
    entry = validate_success(
        api.post_credit_adjustment(
            customer["id"],
            credit_adjustment_payload(
                "MANUAL_DEBIT", 12_345, customer["version"], memo="audit fee"
            ),
            FINANCE,
        ),
        201,
    )
    assert_ledger_entry(entry)

    data, meta = validate_paginated(
        api.list_ledger_entries(customer["id"], FINANCE)
    )
    assert len(data) == 1
    row = data[0]
    assert_ledger_entry(row)
    assert row["entry_type"] == "MANUAL_DEBIT"
    assert row["amount_cents"] == 12_345
    assert row["reference_type"] == "CUSTOMER"
    assert row["reference_id"] == customer["id"]


def test_occ_customer_adjust_stale_version(api):
    """PRD §2.9: "Posting a manual or payment adjustment against a customer
    account requires `expected_customer_version`. Ledger cascades (invoices,
    deposit debits, waivers) advance the customer's `version`, so an adjustment
    carrying a stale expectation would apply to a balance the controller never
    observed; it is rejected with `ERR_STALE_CUSTOMER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_customer_adjust_stale_version
    """
    customer = create_customer(name="OccCust")
    assert customer["version"] == 1

    first = api.post_credit_adjustment(
        customer["id"],
        credit_adjustment_payload("MANUAL_DEBIT", 1_000, 1, memo="first"),
        FINANCE,
    )
    validate_success(first, 201)

    stale = api.post_credit_adjustment(
        customer["id"],
        credit_adjustment_payload("MANUAL_DEBIT", 1_000, 1, memo="second (stale)"),
        FINANCE,
    )
    validate_error(stale, "ERR_STALE_CUSTOMER_VERSION", expected_status=412)

    after = validate_success(api.get_customer(customer["id"], FINANCE))
    assert after["outstanding_balance_cents"] == 1_000, (
        "exactly one posting must have landed"
    )
    assert after["version"] == 2


def test_immediate_visibility_after_mutation(api):
    """PRD §3.2: "New units are born `AVAILABLE`, and registration raises the
    part's `available_count` by one."
    PRD §2.5: "The balance is recomputed synchronously within the same request
    that posts any entry — the posting and the recomputation are atomic."

    Design: Corner/consistency_model/immediate_visibility_after_mutation
    """
    part = create_part()
    assert part["available_count"] == 0
    create_unit(part["id"])
    part_after = validate_success(api.get_part(part["id"], WAREHOUSE))
    assert part_after["available_count"] == 1

    customer = create_customer(name="ImmAir")
    validate_success(
        api.post_credit_adjustment(
            customer["id"],
            credit_adjustment_payload("MANUAL_DEBIT", 777, customer["version"],
                                      memo="now"),
            FINANCE,
        ),
        201,
    )
    cust_after = validate_success(api.get_customer(customer["id"], FINANCE))
    assert cust_after["outstanding_balance_cents"] == 777
