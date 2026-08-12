"""Customer onboarding, schema validation, and the payment wallet (PRD §3.1, §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_payment,
    get_success_data,
    make_customer,
    make_depot,
    make_payment,
    order_payload,
    order_line,
    set_logical_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK_1 = TEST_USERS["billing_clerk_1_headers"]


def test_customer_creation_missing_required_field(api):
    """PRD §2.6: "required fields are present, types match, enum values are
    valid, unknown fields are rejected, the `lines` array is non-empty,
    `window_start` falls before `window_end`, and `period_start` falls before
    `period_end`, else `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/customer_creation_missing_required_field
    """
    resp = api.create_customer(
        {
            "kind": "BAR_RESTAURANT",
            "tier": "STANDARD",
            "credit_terms": "NET_30",
            "credit_limit_cents": 1000,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_customer_defaults_applied(api):
    """PRD §3.1: "New accounts start with `credit_balance_cents` and
    `outstanding_exposure_cents` at zero and a `standing` of `GOOD`."

    Design: Corner/entities/customer_defaults_applied
    """
    data = validate_success(
        api.create_customer(
            {
                "account_name": "New Bar",
                "kind": "BAR_RESTAURANT",
                "tier": "STANDARD",
                "credit_terms": "NET_30",
                "credit_limit_cents": 1000,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert data["credit_balance_cents"] == 0
    assert data["outstanding_exposure_cents"] == 0
    assert data["standing"] == "GOOD"
    assert isinstance(data["version"], int), "version is a system-managed integer"


def test_order_create_invalid_enum_rejected(api):
    """PRD §2.6: "required fields are present, types match, enum values are
    valid, unknown fields are rejected, the `lines` array is non-empty,
    `window_start` falls before `window_end`, and `period_start` falls before
    `period_end`, else `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.4: "a `channel` of `DELIVERY` or `WILL_CALL`".

    Design: Corner/entities/order_create_invalid_enum_rejected
    """
    from test_helpers import make_customer_agent_headers

    depot = make_depot(10, "Depot E4")
    cust = make_customer(
        account_name="E4", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=100000,
    )
    payload = order_payload(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="DRONE", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    resp = api.create_order(payload, make_customer_agent_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_payment_immutable_ledger_row(api):
    """PRD §2.5: "A `Payment` is an immutable ledger entry, and a
    `WaitlistEntry` is a transient queue record: both carry only `id` and
    `created_at`, and both `updated_at` and `version` are absent from them."
    PRD §3.8: "Whatever remains unallocated is the payment's
    `overpayment_cents`, credited to the customer's `credit_balance_cents`".

    Design: Corner/entities/payment_immutable_ledger_row
    """
    cust = make_customer(
        account_name="E5", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=100000,
    )
    resp = api.create_payment(
        {"customer_id": cust["id"], "amount_cents": 5000, "method": "CASH"},
        CLERK_1,
    )
    data = validate_success(resp, expected_status=201)
    assert_payment(data)
    assert data["applied_cents"] == 0, "no open invoices: nothing to allocate"
    assert data["overpayment_cents"] == 5000
    customer = get_success_data(api.get_customer(cust["id"], CLERK_1))
    assert customer["credit_balance_cents"] == 5000


def test_payment_amount_zero_rejected(api):
    """PRD §3.8: "an `amount_cents` of at least one
    (`ERR_PAYMENT_AMOUNT_INVALID`)".

    Design: Corner/validations/payment_amount_zero_rejected
    """
    cust = make_customer(
        account_name="V37", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=100000,
    )
    resp = api.create_payment(
        {"customer_id": cust["id"], "amount_cents": 0, "method": "ACH"},
        CLERK_1,
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID)


def test_read_after_write_immediate(api):
    """PRD §3.8: "Whatever remains unallocated is the payment's
    `overpayment_cents`, credited to the customer's `credit_balance_cents`".
    PRD §1: "every mutation recomputes them immediately, in the same request."

    Design: Corner/consistency_model/read_after_write_immediate
    """
    cust = make_customer(
        account_name="M55", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=100000,
    )
    payment = make_payment(cust["id"], 7000, method="CARD")
    assert payment["overpayment_cents"] == 7000
    customer = get_success_data(api.get_customer(cust["id"], CLERK_1))
    assert customer["credit_balance_cents"] == 7000, (
        "wallet credit must be visible on the very next read"
    )
