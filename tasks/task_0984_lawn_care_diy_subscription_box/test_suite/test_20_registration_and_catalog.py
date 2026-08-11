"""Registration, referral entry point, catalog uniqueness, weather upsert,
and read-after-write visibility (PRD 2.2, 2.4, 3.1, 3.2, 3.7)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_customer_register_defaults_and_system_fields(api):
    """PRD 3.2: "The server mints a unique `referral_code` for the new account (shaped like `REF-XXXXXX`), initializes `credit_balance_cents` to 0, and sets the customer `status` to `ACTIVE`."
    PRD 2.4: "Every persisted resource carries a server-minted `id` in UUID format with no type prefix."

    Design: Corner/entities/customer_register_defaults_and_system_fields
    """
    resp = api.register_customer(
        th.customer_payload(email="c1@x.com", full_name="C One", climate_zone="COOL")
    )
    assert resp.status_code == 201
    body = resp.json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["response_type"] == "object"
    customer = body["data"]
    th.assert_customer(customer)
    assert customer["status"] == "ACTIVE"
    assert customer["credit_balance_cents"] == 0
    assert isinstance(customer["version"], int)
    assert th.is_valid_uuid(customer["id"]), "id is a bare UUID with no type prefix"


def test_customer_register_duplicate_email_rejected(api):
    """PRD 3.2: "Email uniqueness is enforced case-insensitively: registering an address that differs from an existing one only by letter case is rejected with `ERR_EMAIL_TAKEN` (HTTP 409)."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/entities/customer_register_duplicate_email_rejected
    """
    th.register_customer(email="c1@x.com", full_name="C One")
    resp = api.register_customer(
        th.customer_payload(email="c1@x.com", full_name="C Uno", climate_zone="WARM")
    )
    error = th.validate_error(resp, th.ApiErrorId.ERR_EMAIL_TAKEN)
    assert error["message"].strip(), "error envelope carries a non-empty message"


def test_invalid_referral_code_rejected(api):
    """PRD 3.2: "A code that resolves to no customer is rejected with `ERR_REFERRAL_CODE_INVALID` (HTTP 422)."

    Design: Corner/validations/invalid_referral_code_rejected
    """
    th.validate_error(
        api.register_customer(
            th.customer_payload(email="v4@x.com", referred_by_code="REF-NOPE")
        ),
        th.ApiErrorId.ERR_REFERRAL_CODE_INVALID,
    )


def test_duplicate_sku_rejected(api):
    """PRD 3.1: "A PlatformAdmin seeds the platform by creating catalog products, each identified by a unique `sku` — reusing an existing sku is rejected with `ERR_SKU_TAKEN` (HTTP 409)."

    Design: Corner/validations/duplicate_sku_rejected
    """
    th.seed_catalog_products("FERT-01")
    th.validate_error(
        api.create_catalog_product(
            th.catalog_product_payload(
                sku="FERT-01", name="Copycat", category="SEED",
                list_price_cents=100, tier_t1_cents=100, tier_t2_cents=100,
                tier_t3_cents=100, conflicting_categories=[],
            ),
            ADMIN,
        ),
        th.ApiErrorId.ERR_SKU_TAKEN,
    )


def test_weather_advisory_upsert_replaces(api):
    """PRD 3.7: "Weather advisories enter the system through a PlatformAdmin upsert keyed on `region` and `date`, carrying `rain_probability`, `wind_kph`, and `temp_high_c`; the pair of region and date is unique, and posting an advisory for an existing pair replaces the previous one."

    Design: Corner/entities/weather_advisory_upsert_replaces
    """
    th.get_success_data(
        api.create_weather_advisory(
            th.weather_advisory_payload(region="NE-OH", date="2026-06-10",
                                        rain_probability=0.10, wind_kph=5,
                                        temp_high_c=22),
            ADMIN,
        )
    )
    th.get_success_data(
        api.create_weather_advisory(
            th.weather_advisory_payload(region="NE-OH", date="2026-06-10",
                                        rain_probability=0.90, wind_kph=30,
                                        temp_high_c=22),
            ADMIN,
        )
    )
    data, meta = th.validate_paginated(
        api.list_weather_advisories(ADMIN, params={"region": "NE-OH",
                                                   "date": "2026-06-10"})
    )
    assert len(data) == 1, "the second write replaces the first, no second row"
    assert data[0]["rain_probability"] == 0.90
    assert data[0]["wind_kph"] == 30


def test_immediate_read_after_write_visibility(api):
    """PRD 2.4: "Every persisted resource carries a server-minted `id` in UUID format with no type prefix. Every resource records `created_at` as an ISO 8601 UTC timestamp with three fractional digits, and — with one exception — also carries `updated_at` in the same format and an integer `version` that starts at its initial value on creation and increments by exactly 1 on every mutation of that resource, whether the mutation comes from a direct client write or from a system cascade."
    PRD 3.2: "The server mints a unique `referral_code` for the new account (shaped like `REF-XXXXXX`), initializes `credit_balance_cents` to 0, and sets the customer `status` to `ACTIVE`."

    Design: Corner/consistency_model/immediate_read_after_write_visibility
    """
    created = th.register_customer(email="m1@x.com", full_name="M One",
                                   climate_zone="WARM")
    fetched = th.validate_success(api.get_customer(created["id"], ADMIN))
    assert fetched["id"] == created["id"]
    assert fetched["climate_zone"] == "WARM" == created["climate_zone"]
    assert fetched["credit_balance_cents"] == 0 == created["credit_balance_cents"]
    assert fetched["status"] == "ACTIVE"
