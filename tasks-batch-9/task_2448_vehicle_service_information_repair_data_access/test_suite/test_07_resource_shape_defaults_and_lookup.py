"""Resource shape on creation, defaulted and computed fields, typed lookups.

Covers what a create call stamps for itself, which fields a client may not
supply, how immutable catalogue rows differ from versioned ones, and which typed
identifier answers a lookup that names a row that does not exist.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    CONTENT_PUBLISHER_1_USER_ID,
    EntitlementStatus,
    IdentityStatus,
    ParityStatus,
    PublicationType,
    Region,
    SeatStatus,
    ShopTier,
    assert_immutable_common_fields,
    assert_manufacturer,
    assert_publication,
    assert_seat_counts,
    assert_shop,
    assert_system_area,
    assert_technician,
    assert_vehicle_model,
    factories,
    fixtures,
    make_compliance_officer_headers,
    make_content_publisher_headers,
    make_platform_admin_headers,
    make_shop_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCreationStampsDerivedState:
    """A create call is never a bare insert; the platform stamps its own fields."""

    def test_manufacturer_registration_stamps_the_parity_verdict(self, api):
        """The response echoes the seven inputs and adds the two parity fields.

        PRD 3.1: "Registration immediately stamps the row's `parity_index` and
        `parity_status`, and `parity_status` reads `COMPLIANT` or
        `NON_COMPLIANT` — nothing else." PRD 2.4 opens the revision counter at 1,
        since `version` "begins at 1 when the row is created".

        Design: Corner/entities/manufacturer_creation_returns_201_with_stamped_parity
        """
        created = validate_success(
            api.create_manufacturer(
                factories.manufacturer_payload(), make_platform_admin_headers()
            ),
            201,
        )

        assert_manufacturer(created)
        assert created["name"] == "Acme Motors"
        assert created["oem_code"] == "ACME"
        assert created["region"] == Region.NA
        assert created["independent_list_monthly_cents"] == 115000
        assert created["independent_covered_system_count"] == 3
        assert created["oem_dealer_monthly_cents"] == 100000
        assert created["oem_dealer_covered_system_count"] == 4
        assert created["parity_index"] == pytest.approx(1.1500, abs=5e-5)
        assert created["parity_status"] == ParityStatus.COMPLIANT
        assert created["version"] == 1

    def test_shop_read_returns_the_ledger_exactly_as_funding_left_it(self, api):
        """The read reports stored ledger figures and recomputes nothing.

        PRD 3.3: "A newly registered shop starts with `funded_credit_total_cents`
        at 0, `data_credit_balance_cents` at 0, `gateway_fee_accrued_cents` at 0
        and `coverage_completeness_pct` at `0.00`", and a funding call raises both
        credit figures by the funded amount. PRD 2.4 advances `version` by exactly
        1 on that mutation.

        Design: Corner/entities/shop_retrieval_returns_stored_ledger_fields
        """
        admin = make_platform_admin_headers()
        shop = validate_success(
            api.create_shop(factories.shop_payload(), admin), 201
        )
        validate_success(
            api.fund_shop_credit(
                shop["id"], factories.credit_funding_payload(200000), admin
            )
        )

        read = validate_success(
            api.get_shop(shop["id"], make_shop_manager_headers(shop["id"]))
        )

        assert_shop(read)
        assert read["id"] == shop["id"]
        assert read["name"] == "Bay Auto"
        assert read["tier"] == ShopTier.PRO
        assert read["funded_credit_total_cents"] == 200000
        assert read["data_credit_balance_cents"] == 200000
        assert read["gateway_fee_accrued_cents"] == 0
        assert read["coverage_completeness_pct"] == pytest.approx(0.00, abs=0.005)
        assert read["version"] == 2

    def test_system_area_flags_default_to_false_and_an_explicit_true_survives(
        self, api
    ):
        """Omitting both booleans yields false; supplying true keeps true.

        PRD 3.1: "Two boolean flags on the row drive obligations elsewhere and
        both default to false when omitted."

        Design: Corner/entities/system_area_defaults_calibration_and_credential_flags_to_false
        """
        admin = make_platform_admin_headers()

        defaulted = validate_success(
            api.create_system_area(
                {"code": "BODY_ELECTRICAL", "name": "Body Electrical"}, admin
            ),
            201,
        )
        assert_system_area(defaulted)
        assert defaulted["code"] == "BODY_ELECTRICAL"
        assert defaulted["name"] == "Body Electrical"
        assert defaulted["requires_calibration_doc"] is False
        assert defaulted["requires_security_credential"] is False

        explicit = validate_success(
            api.create_system_area(
                {
                    "code": "ADAS",
                    "name": "Advanced Driver Assistance",
                    "requires_calibration_doc": True,
                    "requires_security_credential": True,
                },
                admin,
            ),
            201,
        )
        assert explicit["requires_calibration_doc"] is True
        assert explicit["requires_security_credential"] is True

    def test_system_area_carries_no_version_and_no_updated_at(self, api):
        """The immutable catalogue row has only its own fields plus identity.

        PRD 2.4: "A vehicle model, a system area, and an audit event each carry
        only `id` and `created_at`; they have no `updated_at` and no `version`
        field at all." PRD 3.1 adds that "System areas are immutable catalogue
        rows once written."

        Design: Corner/entities/system_area_is_immutable_and_carries_no_version_field
        """
        created = validate_success(
            api.create_system_area(
                factories.system_area_payload("ADAS"), make_platform_admin_headers()
            ),
            201,
        )

        assert_immutable_common_fields(created, "SystemArea")
        assert set(created.keys()) == {
            "id",
            "created_at",
            "code",
            "name",
            "requires_calibration_doc",
            "requires_security_credential",
        }


class TestClientSuppliedFieldsAreRefused:
    """Rung six rejects a body that names anything outside the input list."""

    def test_computed_entitlement_fields_may_not_be_supplied(self, api):
        """A payload naming seats_available or charged_cents fails shape validation.

        PRD 2.7: "Request-shape validation at rung 6 covers, in one pass: that
        the body parses as JSON, that it contains no unknown fields", so a
        purchase naming the platform's own computed figures is refused with
        `ERR_INVALID_REQUEST`. PRD 3.3 then stamps those figures itself, opening
        the row with "`seats_assigned` of 0 and `seats_available` equal to
        `seats_total`".

        Design: Corner/entities/entitlement_seats_available_computed_field_input_ignored
        """
        ctx = fixtures.build_funded_shop(api, covered_area_codes=("POWERTRAIN",))
        payload = factories.entitlement_payload(
            ctx["shop"]["id"], ctx["license"]["id"], seats_total=3
        )

        validate_error(
            api.create_entitlement(
                dict(payload, seats_available=99, charged_cents=1),
                ctx["manager_headers"],
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        clean = validate_success(
            api.create_entitlement(payload, ctx["manager_headers"]), 201
        )
        assert clean["seats_total"] == 3
        assert_seat_counts(clean, 0, 3)
        assert clean["charged_cents"] == 85000

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["data_credit_balance_cents"] == 115000

    def test_technician_identity_status_may_not_be_supplied(self, api):
        """Identity is server-owned, so a create naming it is refused.

        PRD 2.7 checks "that it contains no unknown fields", so naming a
        server-owned field returns `ERR_INVALID_REQUEST`. PRD 3.5: "Enrolment does
        not confer access: a new technician opens in `identity_status` of
        `UNVERIFIED`, with `identity_document_ref` and `verified_by_user_id` both
        null."

        Design: Corner/entities/technician_system_field_identity_status_input_ignored
        """
        admin = make_platform_admin_headers()
        shop = validate_success(api.create_shop(factories.shop_payload(), admin), 201)
        manager = make_shop_manager_headers(shop["id"])
        payload = factories.technician_payload(shop["id"])

        validate_error(
            api.create_technician(
                dict(payload, identity_status=IdentityStatus.VERIFIED), manager
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        created = validate_success(api.create_technician(payload, manager), 201)
        assert_technician(created)
        assert created["identity_status"] == IdentityStatus.UNVERIFIED
        assert created["verified_by_user_id"] is None
        assert created["identity_document_ref"] is None
        assert created["version"] == 1
        assert created["shop_id"] == shop["id"]

    def test_a_missing_required_name_persists_no_partial_technician(self, api):
        """Omitting full_name is a shape failure, and no row is written.

        PRD 2.7: rung 6 checks "that every required field is present", and PRD 3.5
        makes `full_name` part of the enrolment payload, so the create is refused
        with `ERR_INVALID_REQUEST` before any row exists.

        Design: Corner/entities/create_technician_missing_full_name_returns_4XX_invalid_request
        """
        admin = make_platform_admin_headers()
        shop = validate_success(api.create_shop(factories.shop_payload(), admin), 201)
        manager = make_shop_manager_headers(shop["id"])

        validate_error(
            api.create_technician(
                {
                    "shop_id": shop["id"],
                    "credential_expires_at": "2026-12-31T00:00:00Z",
                },
                manager,
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        _rows, meta = validate_paginated(
            api.list_shop_technicians(shop["id"], manager)
        )
        assert meta["total_count"] == 0

    def test_an_off_enum_tier_and_an_inverted_license_window_are_both_refused(
        self, api
    ):
        """Enum membership and interval ordering are both pre-persistence checks.

        PRD 3.3 fixes the tier vocabulary as "`BASIC`, `PRO` or `ENTERPRISE`", and
        PRD 3.2 requires "the ISO 8601 UTC instants `effective_start` and
        `effective_end`, where the end must be strictly after the start"; PRD 2.7
        checks "that every enum-typed value is one of that field's declared
        members" at rung 6, so both bodies return `ERR_INVALID_REQUEST`.

        Design: Corner/entities/create_shop_unknown_tier_and_license_inverted_window_rejected
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        admin = make_platform_admin_headers()

        validate_error(
            api.create_shop({"name": "Gold Garage", "tier": "GOLD"}, admin),
            ApiErrorId.INVALID_REQUEST,
            400,
        )
        validate_error(
            api.create_license(
                factories.license_payload(
                    ctx["manufacturer"]["id"],
                    fixtures.area_ids(ctx, ("POWERTRAIN",)),
                    effective_start="2027-08-01T00:00:00Z",
                    effective_end="2026-08-01T00:00:00Z",
                ),
                admin,
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        _rows, meta = validate_paginated(
            api.list_manufacturer_licenses(ctx["manufacturer"]["id"], admin)
        )
        assert meta["total_count"] == 0


class TestTypedLookupsAndNavigation:
    """Each entity answers a lookup miss with its own identifier."""

    def test_an_unknown_entitlement_id_returns_the_typed_not_found(self, api):
        """A well-formed but unknown id is an entitlement-specific 404.

        PRD 2.6: "Each entity type has its own not-found error, and the same error
        is used whether the missing identifier arrived in the path or in the
        request body", the list including `ERR_ENTITLEMENT_NOT_FOUND`, "all HTTP
        404".

        Design: Corner/entities/get_entitlement_unknown_id_returns_entitlement_not_found
        """
        response = api.get_entitlement(
            NON_EXISTENT_UUID, make_compliance_officer_headers()
        )

        validate_error(response, ApiErrorId.ENTITLEMENT_NOT_FOUND, 404)
        assert response.json()["response_type"] == "error"

    def test_a_vehicle_model_under_an_unknown_manufacturer_is_a_secondary_404(self, api):
        """The manufacturer axis of a vehicle model is a secondary reference.

        PRD 2.6: "A distinct error covers **secondary** references — identifiers
        that point at supporting catalogue rows rather than at the request's
        subject." The enumeration that follows names "the `manufacturer_id` axis
        check when a vehicle model is registered", and "all of these resolve to
        `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404) when they fail."

        Design: Corner/entities/create_vehicle_model_unknown_manufacturer_not_found
        """
        admin = make_platform_admin_headers()
        manufacturer = validate_success(
            api.create_manufacturer(factories.manufacturer_payload(), admin), 201
        )

        validate_error(
            api.create_vehicle_model(
                factories.vehicle_model_payload(NON_EXISTENT_UUID), admin
            ),
            ApiErrorId.REFERENCED_RESOURCE_NOT_FOUND,
            404,
        )

        created = validate_success(
            api.create_vehicle_model(
                factories.vehicle_model_payload(manufacturer["id"]), admin
            ),
            201,
        )
        assert_vehicle_model(created)
        assert created["manufacturer_id"] == manufacturer["id"]
        assert created["model_code"] == "AX7"
        assert created["model_year"] == 2025

        _rows, meta = validate_paginated(
            api.list_manufacturer_vehicle_models(manufacturer["id"], admin)
        )
        assert meta["total_count"] == 1

    def test_publication_listing_counts_the_filtered_set_not_the_page(self, api):
        """total_count spans the whole filtered set across both pages.

        PRD 2.3: "List responses report `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object, where `total_count` is the number of
        rows matching the request's filters before pagination is applied and
        `has_more` indicates whether any matching row remains beyond the returned
        page." PRD 3.6
        adds that "A newly opened publication has `current_version_no` of 0 and
        `published_version_id` of null".

        Design: Corner/entities/publication_listing_paginates_with_total_count_and_has_more
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        author = make_content_publisher_headers(CONTENT_PUBLISHER_1_USER_ID)
        model_id = ctx["vehicle_model"]["id"]
        area_id = ctx["areas"]["POWERTRAIN"]["id"]
        created_ids = set()
        for publication_type in (
            PublicationType.REPAIR_PROCEDURE,
            PublicationType.TSB,
            PublicationType.CALIBRATION_DOC,
        ):
            publication = validate_success(
                api.create_publication(
                    factories.publication_payload(
                        model_id, area_id, publication_type=publication_type
                    ),
                    author,
                ),
                201,
            )
            assert_publication(publication)
            assert publication["current_version_no"] == 0
            assert publication["published_version_id"] is None
            created_ids.add(publication["id"])

        officer = make_compliance_officer_headers()
        first_rows, first_meta = validate_paginated(
            api.list_publications(
                officer, {"vehicle_model_id": model_id, "limit": 2, "offset": 0}
            )
        )
        second_rows, second_meta = validate_paginated(
            api.list_publications(
                officer, {"vehicle_model_id": model_id, "limit": 2, "offset": 2}
            )
        )

        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert len(first_rows) == 2
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert len(second_rows) == 1
        assert {row["id"] for row in first_rows + second_rows} == created_ids

    def test_seat_assignments_are_navigable_from_both_sides_of_the_junction(self, api):
        """One entitlement lists two seats; one technician lists its own.

        PRD 3.5: "Seat lists narrow by `entitlement_id`, by `technician_id` and by
        `status`", and "`seats_assigned` is the count of seat rows on that
        entitlement whose status is `ACTIVE`" with `seats_available` the
        remainder.

        Design: Corner/entities/seat_assignment_junction_navigable_from_both_technician_and_entitlement
        """
        ctx = fixtures.build_entitled_shop(
            api, covered_area_codes=("POWERTRAIN",), seats_total=3
        )
        fixtures.add_technician(api, ctx, key="main", full_name="Tina Tech")
        fixtures.add_technician(
            api,
            ctx,
            key="second",
            full_name="Raj Wrench",
            identity_document_ref="DL-77124",
        )
        fixtures.add_seat(api, ctx, key="main")
        fixtures.add_seat(api, ctx, key="second")
        manager = ctx["manager_headers"]

        by_entitlement, entitlement_meta = validate_paginated(
            api.list_seat_assignments(
                manager,
                {
                    "entitlement_id": ctx["entitlement"]["id"],
                    "status": SeatStatus.ACTIVE,
                },
            )
        )
        by_technician, technician_meta = validate_paginated(
            api.list_seat_assignments(
                manager, {"technician_id": ctx["technicians"]["second"]["id"]}
            )
        )

        assert entitlement_meta["total_count"] == 2
        assert {row["id"] for row in by_entitlement} == {
            ctx["seats"]["main"]["id"],
            ctx["seats"]["second"]["id"],
        }
        assert technician_meta["total_count"] == 1
        assert by_technician[0]["id"] == ctx["seats"]["second"]["id"]
        assert by_technician[0]["entitlement_id"] == ctx["entitlement"]["id"]
        assert (
            by_technician[0]["technician_id"] == ctx["technicians"]["second"]["id"]
        )

        entitlement = fixtures.refresh_entitlement(api, ctx)
        assert entitlement["status"] == EntitlementStatus.ACTIVE
        assert_seat_counts(entitlement, 2, 1)

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["data_credit_balance_cents"] == 115000
