"""Entity creation, defaults, system fields, immutability, listing, and computed
reads — corner-design instances for the entities and endpoints sections.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_member_headers,
    assert_invoice_immutable_shape,
    fixtures as fx,
)


# =========================================================================== #
# Corner: entities                                                            #
# =========================================================================== #
def test_create_subscription_plan_returns_201_with_fields(api):
    """PRD §3.1: "A plan's `status` is system-managed, defaults to `ACTIVE`, and may
    also read `RETIRED`."

    Design: Corner/entities/create_subscription_plan_returns_201_with_all_fields
    """
    fx.set_clock()
    data = validate_success(api.create_plan(
        {"tier": "ESSENTIAL", "monthly_fee_cents": 60000, "included_miles_per_cycle": 800,
         "free_buffer_miles": 50, "overage_tier1_rate_cents": 20, "overage_tier2_rate_cents": 30,
         "included_swaps_per_term": 0, "min_term_months": 3, "deposit_base_cents": 50000},
        TEST_USERS["platform_admin_headers"]), expected_status=201)
    assert data["tier"] == "ESSENTIAL"
    assert data["monthly_fee_cents"] == 60000
    assert data["status"] == "ACTIVE"


def test_free_buffer_miles_and_swaps_default_when_omitted(api):
    """PRD §3.1: "an optional `free_buffer_miles` grace amount beyond the included
    allowance that defaults to 0 when omitted and must be zero or more."
    PRD §3.1: "The plan also sets `included_swaps_per_term`, the number of free swaps
    granted before a swap fee applies, which defaults to 0 and must be zero or more".

    Design: Corner/entities/free_buffer_miles_default_applied_when_omitted
    """
    fx.set_clock()
    data = validate_success(api.create_plan(
        {"tier": "ESSENTIAL", "monthly_fee_cents": 60000, "included_miles_per_cycle": 800,
         "overage_tier1_rate_cents": 20, "overage_tier2_rate_cents": 30,
         "min_term_months": 3, "deposit_base_cents": 50000},
        TEST_USERS["platform_admin_headers"]), expected_status=201)
    assert data["free_buffer_miles"] == 0, f"expected default 0, got {data['free_buffer_miles']}"
    assert data["included_swaps_per_term"] == 0, f"expected default 0, got {data['included_swaps_per_term']}"


def test_get_vehicle_nonexistent_returns_not_found(api):
    """PRD §2.9: "the system validates each identifier left to right and rejects the
    first one that does not resolve to an existing resource with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_vehicle_nonexistent_returns_not_found
    """
    fx.set_clock()
    resp = api.get_vehicle(NON_EXISTENT_UUID, TEST_USERS["fleet_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_vehicle_missing_vin_returns_invalid_request(api):
    """PRD §2.10: "structural validity of the request body — required fields present,
    correctly typed, and enum values within their declared sets (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_vehicle_missing_required_vin_returns_invalid_request
    """
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    resp = api.create_vehicle(
        {"fleet_id": fleet["id"], "plan_id": plan["id"], "model_label": "XC40", "odometer_miles": 0},
        TEST_USERS["fleet_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_applicant_invalid_history_flag_rejected(api):
    """PRD §3.3: "and a `history_flag` of `CLEAN`, `MINOR`, or `SEVERE`."

    Design: Corner/entities/applicant_invalid_history_flag_enum_rejected
    """
    fx.set_clock()
    resp = api.create_applicant(
        {"full_name": "Bad", "email": "bad@example.com", "credit_score": 700,
         "monthly_income_cents": 300000, "history_flag": "UNKNOWN"},
        TEST_USERS["member_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_new_vehicle_system_fields_defaulted(api):
    """PRD §3.2: "A new vehicle's allocation `status` defaults to `AVAILABLE`, and its
    `active_subscription_id` defaults to null."

    Design: Corner/entities/vehicle_system_fields_status_active_subscription_generated
    """
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    data = validate_success(api.create_vehicle(
        {"fleet_id": fleet["id"], "plan_id": plan["id"], "vin": "SF-1",
         "model_label": "XC40", "odometer_miles": 12},
        TEST_USERS["fleet_operator_headers"]), expected_status=201)
    assert data["status"] == "AVAILABLE"
    assert data["active_subscription_id"] is None
    assert data["version"] == 1, f"new vehicle version must be 1, got {data['version']}"


def test_list_plans_returns_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_plans_paginated_envelope
    """
    fx.set_clock()
    fx.create_plan(tier="PLUS")
    fx.create_plan(tier="ESSENTIAL", monthly_fee_cents=60000, included_miles_per_cycle=800,
                   overage_tier1_rate_cents=20, overage_tier2_rate_cents=30,
                   min_term_months=3, deposit_base_cents=50000)
    resp = api.list_plans(TEST_USERS["platform_admin_headers"], params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"


def test_invoice_is_immutable_no_version_field(api):
    """PRD §2.4: "The `Invoice` resource is immutable once posted: it carries only an
    `id` and a `created_at`, and has neither an `updated_at` nor a `version` field."

    Design: Corner/entities/invoice_immutable_no_version_field
    """
    ctx = fx.setup_active_subscription(vehicle_overrides={"odometer_miles": 1000})
    sub_id = ctx["subscription"]["id"]
    cycle_id = fx.open_billing_cycle_id(sub_id)
    # delta 500 < included+buffer 1050 -> no overage -> amount 80000
    get_success_data(api.close_billing_cycle(
        cycle_id, {"odometer_end_miles": 1500}, TEST_USERS["billing_admin_headers"]))
    invs, _ = fx._list(api.list_subscription_invoices(
        sub_id, TEST_USERS["billing_admin_headers"], params={"source_kind": "CYCLE"}))
    inv_id = invs[0]["id"]
    data = validate_success(api.get_invoice(inv_id, TEST_USERS["billing_admin_headers"]))
    assert data["source_kind"] == "CYCLE"
    assert data["amount_cents"] == 80000, f"expected 80000 (no overage), got {data['amount_cents']}"
    assert_invoice_immutable_shape(data)


# =========================================================================== #
# Corner: endpoints                                                           #
# =========================================================================== #
def test_get_subscription_reflects_lifetime_billed_accumulator(api):
    """PRD §3.14: "The subscription's derived `lifetime_billed_cents` is the running sum
    of the `amount_cents` of every invoice posted for that subscription."

    Design: Corner/endpoints/get_subscription_returns_stored_data
    """
    ctx = fx.setup_active_subscription(vehicle_overrides={"odometer_miles": 5000})
    sub_id = ctx["subscription"]["id"]
    appl_id = ctx["applicant"]["id"]
    cycle_id = fx.open_billing_cycle_id(sub_id)
    # delta 1500 -> overage 14500; CYCLE invoice 94500
    get_success_data(api.close_billing_cycle(
        cycle_id, {"odometer_end_miles": 6500}, TEST_USERS["billing_admin_headers"]))
    data = validate_success(api.get_subscription(sub_id, make_member_headers(appl_id)))
    assert data["lifetime_billed_cents"] == 94500, (
        f"expected lifetime_billed 94500, got {data['lifetime_billed_cents']}"
    )
