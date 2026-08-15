"""Customer onboarding, boat registration, and account-read fundamentals."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_boat,
    assert_customer,
    create_customer,
    make_customer_headers,
    validate_error,
    validate_success,
    TEST_USERS,
)

MGR = TEST_USERS["loft_manager_headers"]


def test_customer_created_with_defaults(api):
    """PRD §3.1: "The new Customer record starts with `outstanding_balance_cents`
    at zero and `status` set to `ACTIVE`."

    Design: Corner/entities/customer_created_with_defaults
    """
    resp = api.create_customer(
        {"full_name": "New Cust", "email": "n@x.com", "credit_limit_cents": 100000}, MGR
    )
    customer = validate_success(resp, expected_status=201)
    assert_customer(customer)
    assert customer["outstanding_balance_cents"] == 0, (
        f"new customer balance must be 0, got {customer['outstanding_balance_cents']}"
    )
    assert customer["status"] == "ACTIVE", (
        f"new customer status must be ACTIVE, got {customer['status']}"
    )


def test_get_customer_not_found_returns_404(api):
    """PRD §2.5: "Path identifiers are validated strictly left-to-right: a request
    addressed to a nested resource (for example, a measurement sheet under a boat
    under a customer) is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the
    first identifier in the path that does not correspond to an existing resource,
    and no later identifier or business rule is consulted until every earlier one
    resolves."

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    resp = api.get_customer(NON_EXISTENT_UUID, MGR)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


def test_create_customer_missing_credit_limit_returns_400(api):
    """PRD §2.6: "Requests with a missing required field, a type mismatch, or an
    enum value outside its declared set are rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.1: "A `LoftManager` onboards a new customer with their `full_name`,
    `email`, and `credit_limit_cents`."

    Design: Corner/entities/create_customer_missing_required_field_returns_400
    """
    resp = api.create_customer({"full_name": "No Limit", "email": "nolimit@x.com"}, MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_boat_created_with_mast_status_stepped(api):
    """PRD §3.1: "A new boat's `mast_status` is initialized to `STEPPED` and its
    `status` to `ACTIVE`; the full `status` enumeration also includes
    `OUT_OF_SERVICE` and `RETIRED`."
    PRD §3.1: "optionally the `running_rigging_hours_accumulated` on the current
    running rigging, which defaults to 0."

    Design: Corner/entities/boat_created_with_mast_status_default_stepped
    """
    customer = create_customer(full_name="C19")
    resp = api.create_boat(
        customer["id"],
        {
            "boat_name": "B19",
            "hull_length_m": 9.5,
            "racing_class": "PHRF",
            "standing_rigging_install_date": "2024-06-01T00:00:00Z",
        },
        MGR,
    )
    boat = validate_success(resp, expected_status=201)
    assert_boat(boat)
    assert boat["mast_status"] == "STEPPED", f"mast_status default must be STEPPED, got {boat['mast_status']}"
    assert boat["status"] == "ACTIVE", f"boat status default must be ACTIVE, got {boat['status']}"
    assert boat["running_rigging_hours_accumulated"] == 0, (
        f"running hours default must be 0, got {boat['running_rigging_hours_accumulated']}"
    )


def test_boat_invalid_racing_class_rejected(api):
    """PRD §2.6: "Requests with a missing required field, a type mismatch, or an
    enum value outside its declared set are rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.1: "a `racing_class` of `NONE`, `J70`, `J105`, `TP52`, `ORC`, or `PHRF`"

    Design: Corner/entities/boat_invalid_racing_class_enum_rejected
    """
    customer = create_customer(full_name="C20")
    resp = api.create_boat(
        customer["id"],
        {
            "boat_name": "B20",
            "hull_length_m": 9.5,
            "racing_class": "AMERICA_CUP",
            "standing_rigging_install_date": "2024-06-01T00:00:00Z",
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_customer_role_cannot_register_boat(api):
    """PRD §2.1: "A request whose role is well-formed but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "POST | `/lofts/customers/{customerId}/boats` | Register a boat for a
    customer | LoftManager" — the endpoint is LoftManager-only.

    Design: Corner/errors/err_forbidden_role_when_customer_creates_boat
    """
    customer = create_customer(full_name="C38")
    resp = api.create_boat(
        customer["id"],
        {
            "boat_name": "B38",
            "hull_length_m": 9.0,
            "racing_class": "NONE",
            "standing_rigging_install_date": "2024-01-01T00:00:00Z",
        },
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
