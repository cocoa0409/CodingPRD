"""Commercial gates: authorize preconditions, credit limit, suspension (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_customer_payload,
    create_order_payload,
    get_success_data,
    setup_authorized_order,
    setup_catalog,
    setup_customer,
    setup_order,
    create_approved_study,
    create_submitted_study,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_engineer_headers"]


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_authorize
# ---------------------------------------------------------------------------

def test_authorize_referential_gate_precedes_credit_gate(api):
    """PRD §3.1: "Three gates are checked, in the priority order of §2.8: at
    least one sizing study for the order must already be `APPROVED` or the
    request fails with `ERR_SIZING_NOT_APPROVED`; the customer's `status` must
    be `ACTIVE` or it fails with `ERR_CUSTOMER_SUSPENDED`; and the customer's
    `credit_utilized_cents` plus the new `amount_cents` must not exceed
    `credit_limit_cents`, or the request fails with
    `ERR_CREDIT_LIMIT_EXCEEDED`."
    PRD §2.8: "...cross-entity referential requirements, and finally fiscal
    gates such as the credit check."

    An order with no APPROVED study AND an amount over the credit limit fails
    with ERR_SIZING_NOT_APPROVED — referential before fiscal.

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_authorize
    """
    customer = setup_customer(credit_limit_cents=50000000, primary_locale="DE")
    _, engine, alternator = setup_catalog()
    order = setup_order(customer["id"], site_locale="DE")
    # Study exists but is only SUBMITTED, never approved.
    create_submitted_study(order, engine["id"], alternator["id"])
    resp = api_client.authorize_order(
        order["id"], {"amount_cents": 60000000, "freight_charge_cents": 1250000}, SALES
    )
    validate_error(resp, ApiErrorId.ERR_SIZING_NOT_APPROVED)
    order_now = get_success_data(api_client.get_order(order["id"], SALES))
    assert order_now["commercial_status"] == "QUOTE"
    customer_now = get_success_data(api_client.get_customer(customer["id"], SALES))
    assert customer_now["credit_utilized_cents"] == 0


def test_authorize_no_study_at_all_rejected(api):
    """PRD §3.1: "...at least one sizing study for the order must already be
    `APPROVED` or the request fails with `ERR_SIZING_NOT_APPROVED`..."

    An order with no study at all fails the same referential gate; the fiscal
    over-limit condition (60000000 > 50000000) is not the reported error.

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_authorize
    """
    customer = setup_customer(credit_limit_cents=50000000)
    order = setup_order(customer["id"])
    resp = api_client.authorize_order(
        order["id"], {"amount_cents": 60000000, "freight_charge_cents": 0}, SALES
    )
    validate_error(resp, ApiErrorId.ERR_SIZING_NOT_APPROVED)


# ---------------------------------------------------------------------------
# Corner/validations/customer_suspended_authorize_rejected
# ---------------------------------------------------------------------------

def test_customer_suspended_authorize_rejected(api):
    """PRD §3.1: "...the customer's `status` must be `ACTIVE` or it fails with
    `ERR_CUSTOMER_SUSPENDED`..."

    Design: Corner/validations/customer_suspended_authorize_rejected
    """
    customer, engine, alternator = setup_catalog(
        customer_overrides={"status": "SUSPENDED"}
    )
    order = setup_order(customer["id"])
    create_approved_study(order, engine["id"], alternator["id"])
    resp = api_client.authorize_order(
        order["id"], {"amount_cents": 1000, "freight_charge_cents": 0}, SALES
    )
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED)
    order_now = get_success_data(api_client.get_order(order["id"], SALES))
    assert order_now["commercial_status"] == "QUOTE"


# ---------------------------------------------------------------------------
# Corner/validations/credit_limit_exact_boundary
# ---------------------------------------------------------------------------

def test_credit_limit_exact_boundary(api):
    """PRD §3.1: "...the customer's `credit_utilized_cents` plus the new
    `amount_cents` must not exceed `credit_limit_cents`, or the request fails
    with `ERR_CREDIT_LIMIT_EXCEEDED`."

    utilized + amount == limit passes ("must not exceed"); one cent over fails.

    Design: Corner/validations/credit_limit_exact_boundary
    """
    customer, engine, alternator = setup_catalog(
        customer_overrides={"credit_limit_cents": 60000000}
    )
    order_a = setup_order(customer["id"])
    create_approved_study(order_a, engine["id"], alternator["id"])
    order_b = setup_order(customer["id"])
    create_approved_study(order_b, engine["id"], alternator["id"])

    authorized = validate_success(api_client.authorize_order(
        order_a["id"], {"amount_cents": 60000000, "freight_charge_cents": 0}, SALES
    ))
    assert authorized["commercial_status"] == "AUTHORIZED"

    resp = api_client.authorize_order(
        order_b["id"], {"amount_cents": 1, "freight_charge_cents": 0}, SALES
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


# ---------------------------------------------------------------------------
# Corner/entities/customer_creation_defaults_and_retrieval
# ---------------------------------------------------------------------------

def test_customer_creation_defaults_and_retrieval(api):
    """PRD §3.1: "An account's `status` starts `ACTIVE` and may be set
    `SUSPENDED`; its `credit_utilized_cents` starts at 0 and thereafter
    tracks... the sum of `committed_amount_cents` across that customer's orders
    whose `commercial_status` is either `AUTHORIZED` or `INVOICED`."
    PRD §2.5: "`version` (integer): starts at the value assigned at creation and
    increments by exactly 1 on every mutation of the resource..."

    Design: Corner/entities/customer_creation_defaults_and_retrieval
    """
    created = validate_success(api_client.create_customer(
        create_customer_payload(
            name="Sierra Health", credit_limit_cents=75000000, primary_locale="US_CA"
        ),
        ADMIN,
    ), expected_status=201)
    assert created["status"] == "ACTIVE"
    assert created["credit_utilized_cents"] == 0
    assert created["version"] == 1

    fetched = validate_success(api_client.get_customer(created["id"], SALES))
    assert fetched["id"] == created["id"]
    assert fetched["status"] == "ACTIVE"
    assert fetched["credit_utilized_cents"] == 0
    assert fetched["version"] == 1


# ---------------------------------------------------------------------------
# Corner/entities/order_creation_missing_required_field_returns_invalid_request
# ---------------------------------------------------------------------------

def test_order_creation_missing_required_field(api):
    """PRD §2.8: "A payload that is malformed in its own right — a missing
    required field, an unknown enum member, an empty `readings` array,
    non-positive quantities, or a `start_hour` not strictly before `end_hour` —
    is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "a `SalesEngineer` opens a `PackageOrder` by naming the
    `customer_id` of the ordering account and three classifiers that drive
    nearly every downstream rule: the `site_locale`... the `occupancy_type`...
    and the duty `application`..."

    Omitting occupancy_type is a missing-required-field rejection.

    Design: Corner/entities/order_creation_missing_required_field_returns_invalid_request
    """
    customer = setup_customer()
    payload = {
        "customer_id": customer["id"],
        "site_locale": "US_TX",
        "application": "STANDBY",
    }
    resp = api_client.create_order(payload, SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Corner/entities/order_creation_invalid_enum_member_rejected
# ---------------------------------------------------------------------------

def test_order_creation_invalid_enum_member_rejected(api):
    """PRD §2.8: "A payload that is malformed in its own right — a missing
    required field, an unknown enum member, an empty `readings` array,
    non-positive quantities, or a `start_hour` not strictly before `end_hour` —
    is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "the `site_locale` of the installation jurisdiction (`US_CA`,
    `US_TX`, or `DE`)..."

    site_locale 'US_NV' is not a declared enum member.

    Design: Corner/entities/order_creation_invalid_enum_member_rejected
    """
    customer = setup_customer()
    payload = create_order_payload(customer_id=customer["id"], site_locale="US_NV")
    resp = api_client.create_order(payload, SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Corner/entities/get_nonexistent_order_returns_not_found
# ---------------------------------------------------------------------------

def test_get_nonexistent_order_returns_not_found(api):
    """PRD §4: "Each binds the `id` of the named resource; an id that does not
    resolve is rejected per §2.8 with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_nonexistent_order_returns_not_found
    """
    resp = api_client.get_order(NON_EXISTENT_UUID, SALES)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner/entities/orders_list_pagination_envelope
# ---------------------------------------------------------------------------

def test_orders_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps how many items a page returns: it
    defaults to 10, must be at least 1, and may not exceed 100. The `offset`
    parameter says how many items to skip before the page begins and defaults
    to 0... The `meta` object of every paginated response carries `limit`,
    `offset`, `total_count`, and `has_more`."

    Three orders on one customer, page of limit 2: 2 rows, total_count 3,
    has_more true.

    Design: Corner/entities/orders_list_pagination_envelope
    """
    customer = setup_customer(credit_limit_cents=300000000)
    setup_order(customer["id"])
    setup_order(customer["id"], site_locale="US_CA", occupancy_type="HOSPITAL", application="PRIME")
    setup_order(customer["id"], site_locale="DE")

    data, meta = validate_paginated(api_client.list_orders(
        SALES, params={"customer_id": customer["id"], "limit": 2, "offset": 0}
    ))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


# ---------------------------------------------------------------------------
# Corner/entities/foreign_key_integrity_unknown_engine_rejected
# ---------------------------------------------------------------------------

def test_sizing_create_unknown_engine_rejected(api):
    """PRD §2.8: "...then existence (every referenced id is looked up;
    path-template identifiers are validated left-to-right so the leftmost
    missing id determines the `ERR_NOT_FOUND` (HTTP 404))..."
    PRD §4: "Each binds the `id` of the named resource; an id that does not
    resolve is rejected per §2.8 with `ERR_NOT_FOUND`."

    A sizing study naming a non-existent engine_model_id fails existence
    validation before any business rule runs.

    Design: Corner/entities/foreign_key_integrity_unknown_engine_rejected
    """
    customer, _, alternator = setup_catalog()
    order = setup_order(customer["id"])
    payload = {
        "order_id": order["id"],
        "engine_model_id": NON_EXISTENT_UUID,
        "alternator_model_id": alternator["id"],
        "load_steps": [{"description": "A", "kva": 100, "duty": "CONTINUOUS"}],
        "largest_motor_kva": 100,
        "starting_method": "DOL",
        "altitude_m": 500,
        "ambient_c": 40,
        "method": "NAMEPLATE_SUM",
        "expected_order_version": order["version"],
    }
    resp = api_client.create_sizing_study(payload, TEST_USERS["application_engineer_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner/entities/fk_reverse_reachability_sizing_studies_by_order
# ---------------------------------------------------------------------------

def test_sizing_studies_filtered_by_order(api):
    """PRD §3.2: "Studies may be browsed filtered by `order_id`,
    `engine_model_id`, `alternator_model_id`, or `superseded_by_id`."

    Two studies on order A and none on order B: the filtered lists return
    exactly those rows.

    Design: Corner/entities/fk_reverse_reachability_sizing_studies_by_order
    """
    customer, engine, alternator = setup_catalog()
    order_a = setup_order(customer["id"])
    order_b = setup_order(customer["id"])

    from test_helpers import create_study
    create_study(order_a, engine["id"], alternator["id"])
    create_study(order_a, engine["id"], alternator["id"],
                 load_steps=[{"description": "B", "kva": 50, "duty": "CONTINUOUS"}],
                 largest_motor_kva=50)

    data_a, meta_a = validate_paginated(api_client.list_sizing_studies(
        SALES, params={"order_id": order_a["id"]}
    ))
    assert meta_a["total_count"] == 2
    assert all(row["order_id"] == order_a["id"] for row in data_a)

    _, meta_b = validate_paginated(api_client.list_sizing_studies(
        SALES, params={"order_id": order_b["id"]}
    ))
    assert meta_b["total_count"] == 0
