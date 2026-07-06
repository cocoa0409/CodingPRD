"""Subscription creation, pricing calculation, defaults, and required-input validation.

Covers difficulty rule `combinatorial_formula.renewal_price_floor_and_cap_nonlinear`
and multiple corner entities/calculations/consistency instances.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    TEST_USERS,
    make_customer_headers,
    create_plan,
    create_customer,
    create_subscription_for,
    setup_plan_customer_subscription,
    get_subscription_shipments,
    ApiErrorId,
)
from test_helpers.factories import (
    create_customer_payload,
    create_plan_payload,
    create_subscription_payload,
)


# =====================================================================
# Difficulty §1.8: combinatorial_formula.renewal_price_floor_and_cap_nonlinear
# =====================================================================


def test_renewal_price_floors_up_to_min_price_cents():
    """PRD §3.2: "the net price is the larger of (gross minus applied discount) and a floor of 2000 cents. That net value is `renewal_price_cents`."

    Gross = base 1500 + PETITE upcharge 0 + no vase 0 = 1500. Discount 0 -> applied 0.
    Net = max(1500, 2000) = 2000. Floor dominates.

    Design: Difficulty/combinatorial_formula/renewal_price_floor_and_cap_nonlinear
    """
    plan = create_plan(cadence="MONTHLY", base_fee_cents=1500, name="Mini Monthly")
    customer = create_customer()
    payload = create_subscription_payload(
        customer_id=customer["id"],
        plan_id=plan["id"],
        size="PETITE",
        start_date="2026-03-01T00:00:00Z",
    )
    res = api_client.create_subscription(payload, TEST_USERS["platform_admin_headers"])
    data = validate_success(res, expected_status=201)
    assert data["renewal_price_cents"] == 2000, (
        f"Expected floor-dominated 2000; got {data['renewal_price_cents']}"
    )


def test_renewal_price_standard_composition_no_bounds():
    """PRD §3.2: "The gross price is the plan's `base_fee_cents` plus a size upcharge plus a vase upcharge. The size upcharge is 0 cents for `PETITE`, 0 cents for `ORIGINAL`, 1500 cents for `DELUXE`, and 3000 cents for `GRAND`."

    Base 6000 + DELUXE 1500 + no vase 0 = 7500. Discount 0, cap/floor inactive.

    Design: Corner/calculations/corner_renewal_price_standard_no_floor
    """
    plan = create_plan(cadence="WEEKLY", base_fee_cents=6000)
    customer = create_customer()
    payload = create_subscription_payload(
        customer_id=customer["id"],
        plan_id=plan["id"],
        size="DELUXE",
        start_date="2026-03-01T00:00:00Z",
    )
    res = api_client.create_subscription(payload, TEST_USERS["platform_admin_headers"])
    data = validate_success(res, expected_status=201)
    assert data["renewal_price_cents"] == 7500, (
        f"Expected 6000+1500=7500; got {data['renewal_price_cents']}"
    )


def test_renewal_price_with_vase_and_grand():
    """PRD §3.2: "The vase upcharge is 1200 cents when `vase_addon` is true and 0 cents otherwise."

    Base 6000 + GRAND 3000 + vase 1200 = 10200. Discount 0, unbounded.

    Design: Difficulty/combinatorial_formula/renewal_price_floor_and_cap_nonlinear
    """
    plan = create_plan(cadence="WEEKLY", base_fee_cents=6000)
    customer = create_customer()
    payload = create_subscription_payload(
        customer_id=customer["id"],
        plan_id=plan["id"],
        size="GRAND",
        vase_addon=True,
        start_date="2026-03-01T00:00:00Z",
    )
    res = api_client.create_subscription(payload, TEST_USERS["platform_admin_headers"])
    data = validate_success(res, expected_status=201)
    assert data["renewal_price_cents"] == 10200


# =====================================================================
# Corner: entities — creation, defaults, validation, not-found
# =====================================================================


def test_customer_creation_returns_201_active_default():
    """PRD §3.1: "A new customer's account `status` begins as `ACTIVE` and may otherwise be `CLOSED`."

    Design: Corner/entities/corner_customer_creation_returns_201
    """
    payload = create_customer_payload(email="new@x.com", full_name="New Person")
    res = api_client.create_customer(payload, TEST_USERS["platform_admin_headers"])
    data = validate_success(res, expected_status=201)
    assert data["status"] == "ACTIVE"
    # id must be a server-minted UUID (§2.4)
    assert len(data["id"]) > 0


def test_subscription_default_style_round_when_omitted():
    """PRD §3.2: "The request may also set `style` (defaulting to `ROUND`), `vase_addon` (defaulting to false), `is_gift` (defaulting to false)".

    Design: Corner/entities/corner_subscription_default_style_applied
    """
    plan = create_plan()
    customer = create_customer()
    payload = {
        "customer_id": customer["id"],
        "plan_id": plan["id"],
        "size": "ORIGINAL",
        "start_date": "2026-03-01T00:00:00Z",
    }
    res = api_client.create_subscription(payload, TEST_USERS["platform_admin_headers"])
    data = validate_success(res, expected_status=201)
    assert data["style"] == "ROUND"


def test_subscription_missing_size_returns_invalid_request():
    """PRD §2.9: "The body must be well-formed — required fields present, enum values valid, numbers within range, and pagination parameters within their bounds — else `ERR_INVALID_REQUEST` (400)."
    PRD §3.2: "the bouquet `size` — one of `PETITE`, `ORIGINAL`, `DELUXE`, or `GRAND`."

    Size is a required input on subscription create; omission yields ERR_INVALID_REQUEST.

    Design: Corner/entities/corner_subscription_missing_size_returns_invalid_request
    """
    plan = create_plan()
    customer = create_customer()
    payload = {"customer_id": customer["id"], "plan_id": plan["id"]}
    res = api_client.create_subscription(payload, TEST_USERS["platform_admin_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_subscription_invalid_size_enum_rejected():
    """PRD §2.9: "The body must be well-formed — required fields present, enum values valid, numbers within range, and pagination parameters within their bounds — else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/corner_subscription_invalid_size_enum
    """
    plan = create_plan()
    customer = create_customer()
    payload = {
        "customer_id": customer["id"],
        "plan_id": plan["id"],
        "size": "HUGE",
    }
    res = api_client.create_subscription(payload, TEST_USERS["platform_admin_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_subscription_create_plan_not_found():
    """PRD §2.10 (existence check applies to path IDs); PRD does not commit whether a body FK
    resolves to a not-found error or a well-formedness error, so accept either.

    Design: Corner/entities/corner_subscription_create_plan_not_found
    """
    customer = create_customer()
    payload = {
        "customer_id": customer["id"],
        "plan_id": NON_EXISTENT_UUID,
        "size": "ORIGINAL",
    }
    res = api_client.create_subscription(payload, TEST_USERS["platform_admin_headers"])
    validate_error_is_one_of(
        res,
        [
            ApiErrorId.ERR_PLAN_NOT_FOUND.value,
            ApiErrorId.ERR_INVALID_REQUEST.value,
        ],
    )


def test_get_unknown_customer_returns_not_found():
    """PRD §2.10: "The first identifier in the path that does not resolve to an existing resource determines the not-found error returned"; "Each entity has its own not-found error: `ERR_CUSTOMER_NOT_FOUND`".

    Design: Corner/entities/corner_customer_not_found
    """
    res = api_client.get_customer(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
    validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


# =====================================================================
# Corner: cross_cutting — scheduled deliveries + immediate visibility
# =====================================================================


def test_weekly_subscription_seeds_four_scheduled_shipments_at_expected_dates():
    """PRD §3.2: "The k-th shipment (counting from zero) has its `scheduled_delivery_date` set to the start instant plus a 2-day first-delivery lead plus a per-cadence spacing multiplied by k, where the spacing is 7 days for `WEEKLY`, 14 days for `BIWEEKLY`, and 30 days for `MONTHLY`."

    WEEKLY with start 2026-03-01: shipments at k=0..3 -> 2026-03-03, -10, -17, -24.

    Design: Corner/cross_cutting/corner_scheduled_deliveries_created_on_subscribe
    """
    _plan, _customer, subscription = setup_plan_customer_subscription(cadence="WEEKLY")
    shipments = get_subscription_shipments(subscription["id"])
    assert len(shipments) == 4, f"Expected 4 SCHEDULED cycle-1 shipments; got {len(shipments)}"
    for sh in shipments:
        assert sh["status"] == "SCHEDULED"
        assert sh["cycle_index"] == 1
    # start (2026-03-01) + FIRST_LEAD_DAYS(2) + WEEKLY(7)*k
    assert shipments[0]["scheduled_delivery_date"].startswith("2026-03-03")
    assert shipments[1]["scheduled_delivery_date"].startswith("2026-03-10")


def test_renewal_price_immediately_readable_via_get():
    """PRD §3.2: "Creating a subscription immediately computes its `renewal_price_cents`, the per-cycle price."
    PRD §3.2: "A subscription's `lifecycle_status`, `billing_status`, `discount_pct`, and `renewal_price_cents` are all readable, along with the current `version`, when the subscription is fetched."

    Create returns the price and a follow-up GET returns the same value.

    Design: Corner/consistency_model/corner_immediate_renewal_price_visible
    """
    plan = create_plan(cadence="WEEKLY", base_fee_cents=6000)
    customer = create_customer()
    payload = create_subscription_payload(
        customer_id=customer["id"],
        plan_id=plan["id"],
        size="GRAND",
        vase_addon=True,
        start_date="2026-03-01T00:00:00Z",
    )
    create_res = api_client.create_subscription(payload, TEST_USERS["platform_admin_headers"])
    created = validate_success(create_res, expected_status=201)
    # 6000 + GRAND 3000 + vase 1200 = 10200
    assert created["renewal_price_cents"] == 10200
    # Follow-up GET returns the same price.
    get_res = api_client.get_subscription(created["id"], TEST_USERS["platform_admin_headers"])
    fetched = validate_success(get_res)
    assert fetched["renewal_price_cents"] == 10200
