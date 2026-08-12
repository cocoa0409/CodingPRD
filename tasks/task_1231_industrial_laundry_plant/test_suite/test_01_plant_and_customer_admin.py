"""Plant/customer administration: creation, required fields, not-found,
system-managed fields, and uniqueness of immutable/unique-keyed resources."""
from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    is_valid_uuid, is_iso8601_timestamp,
    ApiErrorId, TEST_USERS,
    assert_plant, assert_customer, assert_utility_reading,
    create_plant_payload, create_customer_payload, create_linen_category_payload,
    create_utility_reading_payload, register_garment_payload,
    create_plant, create_linen_category, create_customer, post_utility_reading,
)

ADMIN = TEST_USERS["plant_admin_headers"]


class TestPlantCreation:
    def test_plant_create_returns_201_with_common_fields(self, api):
        """PRD §4: "Creating a new resource returns HTTP 201; operations that modify an existing resource, and all reads, return HTTP 200."
        PRD §2.4: "Every persisted resource carries an `id` field: a server-minted UUID with no type prefix. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, set at creation."
        PRD §2.4: "All resources except `UtilityReading` additionally carry `updated_at` — an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation — and `version`, an integer that starts at its initial value on creation and increments by one on every mutation of that resource."

        Design: Corner/entities/plant_create_returns_201_with_defaults
        """
        resp = api.create_plant(create_plant_payload(name="P"), ADMIN)
        data = validate_success(resp, 201)
        assert_plant(data)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])

    def test_plant_create_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.1: "Creating a plant requires a `name` and four policy numbers that govern alerting and surcharges for everything that follows: `reject_rate_alert_pct`, the reject-rate percentage at or above which a sort batch raises an alert; `par_shortage_alert_pieces`, the number of pieces of par shortfall at or above which a delivery raises a shortage alert; and the utility baselines `utility_baseline_kwh_per_lb` and `utility_baseline_gal_per_lb`"
        PRD §2.9: "Request-body schema validation: required fields present, types correct, quantities non-negative, piece counts at least 1, `reject_reason` present if and only if `disposition` is `REJECTED` (present on an `ACCEPTED` row or absent on a `REJECTED` row is a schema violation), `billing_period_end` strictly after `billing_period_start`, and enum members drawn from their declared value sets. Failures surface as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/plant_create_missing_required_field_returns_invalid_request
        """
        payload = create_plant_payload()
        del payload["reject_rate_alert_pct"]
        resp = api.create_plant(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCustomerAdmin:
    def test_customer_get_nonexistent_returns_not_found(self, api):
        """PRD §2.9: "Existence of path resources, validated left to right along the URL hierarchy (plant first, then each nested resource in turn) — `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/customer_get_nonexistent_returns_not_found
        """
        create_plant()
        resp = api.get_customer(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_customer_create_starts_active_with_zero_balance(self, api):
        """PRD §3.1: "A newly created customer starts in `ACTIVE` status with an `account_balance_cents` of zero; the balance is a computed figure, the sum of unpaid invoice totals minus credits, where a positive value means the customer owes the plant."

        Design: Corner/entities/system_fields_ignore_client_input
        """
        plant = create_plant()
        resp = api.create_customer(
            plant["id"], create_customer_payload(credit_limit_cents=1000), ADMIN
        )
        data = validate_success(resp, 201)
        assert_customer(data)
        assert data["status"] == "ACTIVE", "new customer must start ACTIVE"
        assert data["account_balance_cents"] == 0, "new customer balance must be 0"


class TestUniquenessAndImmutability:
    def test_utility_reading_duplicate_period_month_rejected(self, api):
        """PRD §3.8: "Posting the month's reading later — an immutable `UtilityReading` naming its `period_month` in YYYY-MM form (unique per plant, collisions rejected as `ERR_DUPLICATE`)"
        PRD §2.4: "`UtilityReading` is an immutable monthly posting and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it."

        Design: Corner/entities/utility_reading_duplicate_period_month_rejected
        """
        plant = create_plant()
        first = api.create_utility_reading(
            plant["id"], create_utility_reading_payload(period_month="2026-05"), TEST_USERS["billing_clerk_headers"]
        )
        reading = validate_success(first, 201)
        assert_utility_reading(reading)

        dup = api.create_utility_reading(
            plant["id"],
            create_utility_reading_payload(
                period_month="2026-05", kwh_used=9999, gallons_used=9999
            ),
            TEST_USERS["billing_clerk_headers"],
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE)

    def test_garment_duplicate_chip_code_rejected(self, api):
        """PRD §3.6: "A `PlantAdmin` registers a garment by naming its `customer_id`, `category_id`, and `chip_code`; the chip code is globally unique across the system, and a colliding registration is rejected with `ERR_DUPLICATE`."

        Design: Corner/entities/garment_duplicate_chip_code_rejected
        """
        plant = create_plant()
        category = create_linen_category(plant["id"])
        customer = create_customer(
            plant["id"], billing_mode="RENTAL", chip_tracking_enabled=True
        )
        payload = register_garment_payload(customer["id"], category["id"], "CHIP-X")
        get_success_data(api.register_garment(payload, ADMIN))
        dup = api.register_garment(payload, ADMIN)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE)
