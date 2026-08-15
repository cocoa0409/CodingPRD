"""Catalog management: boat model seeding, defaults, field-domain validation,
and option-package self-referential incompatibility (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_boat_model,
    assert_option_package,
    create_boat_model_payload,
    create_option_package_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
ANY = TEST_USERS["any_headers"]


class TestBoatModelSeeding:
    def test_model_creation_defaults_to_orderable(self, api):
        """PRD §3.1: "The model's `status` is set at creation and is immutable
        thereafter: it defaults to `ORDERABLE` when omitted, or may be seeded
        directly as `DISCONTINUED` for catalog cleanup."

        Design: Corner/entities/boat_model_creation_defaults_to_orderable
        """
        payload = create_boat_model_payload(model_code="SP190")
        data = validate_success(api.create_boat_model(payload, ADMIN), 201)
        assert_boat_model(data)
        assert data["status"] == "ORDERABLE", (
            f"status must default to ORDERABLE when omitted, got {data['status']}"
        )

    def test_model_creation_explicit_discontinued(self, api):
        """PRD §3.1: "The model's `status` is set at creation and is immutable
        thereafter: it defaults to `ORDERABLE` when omitted, or may be seeded
        directly as `DISCONTINUED` for catalog cleanup."

        Design: Corner/entities/boat_model_creation_explicit_discontinued
        """
        payload = create_boat_model_payload(
            model_code="OLD10",
            model_name="Legacy 10",
            model_year=2020,
            base_price_cents=1000000,
            production_hours=30,
            status="DISCONTINUED",
        )
        data = validate_success(api.create_boat_model(payload, ADMIN), 201)
        assert_boat_model(data)
        assert data["status"] == "DISCONTINUED", (
            f"explicit DISCONTINUED seeding must be honored, got {data['status']}"
        )


class TestBoatModelFieldDomain:
    def test_model_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.9: "Body schema and field domains: required fields present;
        enum values valid; dates well-formed with start not after end; a
        production run's `build_week_end` exactly seven days after its
        `build_week_start`; amounts non-negative; `hin_serial_start` not greater
        than `hin_serial_end`; a `BOAT_SHOW`-sourced order carries a
        `show_event_id` while other sources must not; `option_package_ids`, when
        provided on an amendment, is non-empty; and no duplicate option
        identifiers appear within one order — any violation is
        `ERR_INVALID_REQUEST`."
        PRD §3.1: "Registering a boat model takes a `model_code` (unique across
        all models, e.g. SP190), a `model_name`, a `model_year`, a
        `base_price_cents` strictly greater than zero"

        Design: Corner/entities/boat_model_missing_required_field_returns_invalid_request
        """
        payload = create_boat_model_payload(model_code="SP190")
        del payload["base_price_cents"]
        resp = api.create_boat_model(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_model_invalid_enum_status_returns_invalid_request(self, api):
        """PRD §2.9: "Body schema and field domains: required fields present;
        enum values valid; dates well-formed with start not after end; a
        production run's `build_week_end` exactly seven days after its
        `build_week_start`; amounts non-negative; `hin_serial_start` not greater
        than `hin_serial_end`; a `BOAT_SHOW`-sourced order carries a
        `show_event_id` while other sources must not; `option_package_ids`, when
        provided on an amendment, is non-empty; and no duplicate option
        identifiers appear within one order — any violation is
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/boat_model_invalid_enum_status_returns_invalid_request
        """
        payload = create_boat_model_payload(model_code="SP190", status="BROKEN")
        resp = api.create_boat_model(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestOptionPackages:
    def test_option_self_referential_incompatibility_stored(self, api):
        """PRD §3.1: "An option may declare a self-referential
        `incompatible_with_option_id`; incompatibility is symmetric, so if
        option A declares B, then B is treated as incompatible with A even
        though B's own row says nothing."

        Design: Corner/entities/option_package_self_referential_incompatibility_stored
        """
        model = validate_success(
            api.create_boat_model(create_boat_model_payload(model_code="SP190"), ADMIN),
            201,
        )
        opt_a = validate_success(
            api.create_option_package(
                create_option_package_payload(
                    model["id"], option_code="TOWER", price_cents=350000,
                    production_hours=6,
                ),
                ADMIN,
            ),
            201,
        )
        opt_b = validate_success(
            api.create_option_package(
                create_option_package_payload(
                    model["id"], option_code="BIMINI", name="Bimini Top",
                    price_cents=80000, production_hours=2,
                    incompatible_with_option_id=opt_a["id"],
                ),
                ADMIN,
            ),
            201,
        )
        assert_option_package(opt_b)
        assert opt_b["incompatible_with_option_id"] == opt_a["id"], (
            "declared incompatibility reference must round-trip on creation"
        )

    def test_option_list_filtered_by_model_id(self, api):
        """PRD §3.1: "The options collection supports reverse lookups by
        `model_id` or by `incompatible_with_option_id`."

        Design: Corner/entities/option_package_list_filtered_by_model_id
        """
        m1 = validate_success(
            api.create_boat_model(create_boat_model_payload(model_code="SP190"), ADMIN),
            201,
        )
        m2 = validate_success(
            api.create_boat_model(
                create_boat_model_payload(
                    model_code="SP210", model_name="Sport 210",
                    base_price_cents=3000000, length_feet=21.0, production_hours=50,
                ),
                ADMIN,
            ),
            201,
        )
        validate_success(
            api.create_option_package(
                create_option_package_payload(m1["id"], option_code="TOWER"), ADMIN
            ),
            201,
        )
        validate_success(
            api.create_option_package(
                create_option_package_payload(
                    m2["id"], option_code="TOWER-XL", price_cents=450000,
                    production_hours=8,
                ),
                ADMIN,
            ),
            201,
        )
        data, meta = validate_paginated(
            api.list_option_packages(ANY, params={"model_id": m1["id"]})
        )
        assert len(data) == 1, f"expected exactly one SP190 option, got {len(data)}"
        assert data[0]["option_code"] == "TOWER"
        assert data[0]["model_id"] == m1["id"]
