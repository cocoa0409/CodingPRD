"""Entity creation defaults, common-field shape, required-field enforcement,
not-found behavior, listing pagination, and HOA/scope/ownership validations.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    ApiErrorId,
    api_client,
    TEST_USERS,
    make_customer_headers,
    create_customer_payload,
    create_yard_payload,
    create_subscription_plan_payload,
    create_subscription_payload,
    create_customer,
    create_yard,
    create_access_profile,
    create_verified_access_profile,
    create_subscription_plan,
    assert_customer,
    NON_EXISTENT_UUID,
)

OPS = TEST_USERS["ops_headers"]
BILLING = TEST_USERS["billing_headers"]


# =========================================================================
# Corner / entities / customer_creation_required_fields
# Corner / entities / customer_missing_required_field_returns_invalid_request
# Corner / entities / customer_get_by_id_not_found
# Corner / entities / customer_list_pagination_envelope
# =========================================================================

class TestCustomerCreation:
    def test_customer_created_with_defaults(self, api):
        """PRD §3.1: "The resulting `Customer` record starts with
        `account_status` set to `ACTIVE`, a `credit_balance_cents` of 0,
        `lifetime_visits_completed` at 0, and `satisfaction_rolling_avg` set
        to null (no reports yet exist)."

        Design: Corner/entities/customer_creation_required_fields
        """
        resp = api_client.create_customer(
            create_customer_payload(full_name="Z", email="z@x.com"), OPS
        )
        data = validate_success(resp, expected_status=201)
        assert_customer(data)
        assert data["account_status"] == "ACTIVE"
        assert data["credit_balance_cents"] == 0
        assert data["lifetime_visits_completed"] == 0
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])

    def test_missing_email_returns_invalid_request(self, api):
        """PRD §2.9 trailing paragraph: "Malformed bodies, missing required
        fields, and wrong-typed fields are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/customer_missing_required_field_returns_invalid_request
        """
        resp = api_client.create_customer({"full_name": "Z"}, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_customer_by_id_not_found(self, api):
        """PRD §2.9 item 3: "Every path-parameter id resolves to an existing
        entity, evaluated left-to-right along the URL — otherwise
        `ERR_NOT_FOUND`."

        Design: Corner/entities/customer_get_by_id_not_found
        """
        resp = api_client.get_customer(NON_EXISTENT_UUID, OPS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_customers_list_pagination_envelope(self, api):
        """PRD §2.3: "The `meta` envelope for list responses includes the
        four pagination fields `limit`, `offset`, `total_count`, and
        `has_more`, where `total_count` reflects the full filtered set size
        (not the size of the returned page) and `has_more` indicates whether
        further pages exist beyond the current `offset` plus returned
        `limit`."

        Design: Corner/entities/customer_list_pagination_envelope
        """
        for i in range(3):
            create_customer(full_name=f"P{i+1}", email=f"p{i+1}@x.com")
        resp = api_client.list_customers(OPS, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert len(data) == 2


# =========================================================================
# Corner / entities / yard_multifamily_hoa_code_required
# Corner / entities / subscription_plan_enum_visit_frequency
# Corner / entities / yard_parent_relationship_wrong_customer
# Corner / entities / yard_computed_subscription_fee_recomputed_on_update
# =========================================================================

class TestYardAndPlanValidation:
    def test_multifamily_yard_without_hoa_code_rejected(self, api):
        """PRD §3.1: "Whenever `is_multifamily_common_area` is true, an
        `hoa_account_code` referencing the managing HOA billing account is
        required — its absence triggers `ERR_HOA_CODE_REQUIRED`."

        Design: Corner/entities/yard_multifamily_hoa_code_required
        """
        customer = create_customer()
        resp = api_client.create_yard(
            {
                "customer_id": customer["id"],
                "address_line1": "5 Park",
                "city": "SF",
                "state_code": "CA",
                "postal_code": "94110",
                "yard_size_sqft": 5000,
                "pet_count": 0,
                "is_multifamily_common_area": True,
                # hoa_account_code omitted
                "service_region_code": "R1",
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_HOA_CODE_REQUIRED)

    def test_subscription_plan_invalid_visit_frequency(self, api):
        """PRD §3.2: "a `visit_frequency` drawn from exactly `WEEKLY`,
        `BIWEEKLY`, `TWICE_WEEKLY`, or `DAILY`." Combined with PRD §2.9
        trailing paragraph: "Malformed bodies, missing required fields, and
        wrong-typed fields are rejected with `ERR_INVALID_REQUEST` (HTTP
        400)."

        Design: Corner/entities/subscription_plan_enum_visit_frequency
        """
        resp = api_client.create_subscription_plan(
            {
                "plan_code": "X",
                "display_name": "X",
                "visit_frequency": "MONTHLY",  # not in the enum
                "applies_to_multifamily": False,
                "base_monthly_fee_cents": 1000,
                "yard_tier_thresholds": [],
                "yard_tier_surcharges_cents": [0],
                "pet_tier_thresholds": [],
                "pet_tier_surcharges_cents": [0],
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_subscription_rejected_when_yard_belongs_to_other_customer(self, api):
        """PRD §3.3: "the referenced yard must belong to the referenced
        customer (otherwise `ERR_YARD_OWNERSHIP_MISMATCH`)"

        Design: Corner/entities/yard_parent_relationship_wrong_customer
        """
        cu_a1 = create_customer(full_name="A1", email="a1@x.com")
        cu_a2 = create_customer(full_name="A2", email="a2@x.com")
        yard_a2 = create_yard(cu_a2["id"])
        plan = create_subscription_plan()
        resp = api_client.create_subscription(
            {
                "customer_id": cu_a1["id"],
                "yard_id": yard_a2["id"],
                "plan_id": plan["id"],
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_YARD_OWNERSHIP_MISMATCH)

    def test_yard_update_recomputes_active_subscription_fee(self, api):
        """PRD §3.1: "Each such change cascades: any subscription on the yard
        that is currently `ACTIVE` has its `monthly_fee_cents_snapshot`
        recomputed using the forward-looking variant of the monthly-fee
        calculation described later, so that billing always reflects the
        yard's current physical reality."

        Design: Corner/entities/yard_computed_subscription_fee_recomputed_on_update
        """
        api_client.set_current_utc("2026-05-01T00:00:00Z", OPS)
        customer = create_customer()
        yard = create_yard(customer["id"], yard_size_sqft=1500, pet_count=2)
        create_verified_access_profile(yard["id"])
        plan = create_subscription_plan(
            plan_code="CF",
            visit_frequency="WEEKLY",
            base_monthly_fee_cents=10000,
            yard_tier_thresholds=[],
            yard_tier_surcharges_cents=[0],
            pet_tier_thresholds=[1, 3],
            pet_tier_surcharges_cents=[0, 2000, 5000],
        )
        sub_resp = api_client.create_subscription(
            create_subscription_payload(customer["id"], yard["id"], plan["id"]),
            make_customer_headers(customer["id"]),
        )
        subscription = get_success_data(sub_resp)
        act_resp = api_client.activate_subscription(
            subscription["id"], make_customer_headers(customer["id"])
        )
        activated = validate_success(act_resp)
        # pet_count=2 -> pet_tier_idx=1 -> surcharge 2000. fee = 10000+0+2000 = 12000
        assert activated["monthly_fee_cents_snapshot"] == 12000
        # Mutate pet_count to 5 -> pet_tier_idx=2 -> surcharge 5000. fee=15000.
        api_client.update_yard(yard["id"], {"pet_count": 5}, OPS)
        get_resp = api_client.get_subscription(subscription["id"], OPS)
        data = validate_success(get_resp)
        assert data["monthly_fee_cents_snapshot"] == 15000
