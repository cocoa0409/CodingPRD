"""Creation, retrieval, listing and field-authority surfaces of the bank's rows."""

import pytest

from test_helpers import (
    UNKNOWN_UUID,
    UNKNOWN_UUID_ALT,
    UNKNOWN_UUID_THIRD,
    ApiErrorId,
    api_client,
    assert_quality_test,
    build_bank_scenario,
    dispatch_kit,
    is_valid_uuid,
    make_billing_admin_headers,
    make_collection_site_headers,
    make_facilities_engineer_headers,
    make_intake_coordinator_headers,
    make_medical_director_headers,
    make_platform_admin_headers,
    make_technologist_headers,
    register_enrollment,
    set_clock,
    sign_consent,
    validate_error,
    validate_paginated,
    validate_success,
)

INTAKE = make_intake_coordinator_headers("ic-001")


def _enrollment_payload(**overrides):
    payload = {
        "program_type": "PRIVATE_FAMILY",
        "primary_parent_name": "Avery Lin",
        "expected_delivery_date": "2026-08-10",
        "collection_site_code": "SITE-01",
    }
    payload.update(overrides)
    return payload


class TestEnrollmentCreationSurface:
    def test_the_declared_inputs_come_back_exactly_as_supplied(self):
        """Both optional consent flags are honoured when they are supplied.

        "Registration supplies the custody model in `program_type` (either `PRIVATE_FAMILY` or
        `PUBLIC_DONATION`, immutable once written), the consenting parent's
        `primary_parent_name` of between 1 and 120 characters, the `expected_delivery_date` that
        will later anchor the maternal-screening window, and the `collection_site_code` of
        between 1 and 20 characters identifying the hospital that will perform the collection."

        Design: Corner/entities/corner_enrollment_create_returns_declared_fields_and_system_defaults
        """
        set_clock("2026-08-01T00:00:00Z")

        created = validate_success(
            api_client.create_enrollment(
                _enrollment_payload(research_use_authorized=True, hla_typing_consent=True), INTAKE
            ),
            201,
        )

        assert created["program_type"] == "PRIVATE_FAMILY"
        assert created["primary_parent_name"] == "Avery Lin"
        assert created["collection_site_code"] == "SITE-01"
        assert created["research_use_authorized"] is True
        assert created["hla_typing_consent"] is True

    def test_the_system_owned_fields_start_at_their_declared_values(self):
        """A freshly registered enrollment sits at the head of both axes.

        "A freshly registered enrollment has `lifecycle_status` of `CONSENT_PENDING`,
        `consent_status` of `PENDING`, a `consent_version` of 0 and a `consent_amendment_count`
        of 0."

        Design: Corner/entities/corner_enrollment_create_returns_declared_fields_and_system_defaults
        """
        set_clock("2026-08-01T00:00:00Z")

        created = validate_success(
            api_client.create_enrollment(_enrollment_payload(), INTAKE), 201
        )

        assert created["lifecycle_status"] == "CONSENT_PENDING"
        assert created["consent_status"] == "PENDING"
        assert created["consent_version"] == 0
        assert created["consent_amendment_count"] == 0
        assert created["consent_signed_at"] is None
        assert created["withdrawal_reason_code"] is None
        assert is_valid_uuid(created["id"])
        assert created["created_at"].startswith("2026-08-01T00:00:00")
        assert created["version"] == 1


class TestEnrollmentRetrievalSurface:
    def test_reading_a_row_back_returns_it_unchanged(self):
        """A nested or direct read creates nothing and mutates nothing.

        "Nested `GET` paths exist for exactly one purpose: to make every foreign key
        reverse-reachable, so that a client holding a parent can discover its children. They
        create nothing and mutate nothing."

        Design: Corner/entities/corner_enrollment_get_by_id_returns_the_stored_row
        """
        set_clock("2026-08-01T00:00:00Z")
        created = validate_success(
            api_client.create_enrollment(
                _enrollment_payload(
                    program_type="PUBLIC_DONATION",
                    primary_parent_name="Dana Ruiz",
                    collection_site_code="SITE-02",
                ),
                INTAKE,
            ),
            201,
        )

        fetched = validate_success(api_client.get_enrollment(created["id"], INTAKE))

        assert fetched["id"] == created["id"]
        assert fetched["program_type"] == "PUBLIC_DONATION"
        assert fetched["primary_parent_name"] == "Dana Ruiz"
        assert fetched["collection_site_code"] == "SITE-02"
        assert fetched["version"] == 1
        assert fetched["updated_at"] == fetched["created_at"]


class TestEnrollmentListingSurface:
    def test_the_window_walks_the_rows_in_creation_order(self):
        """`limit` and `offset` cut a window out of the created_at ascending order.

        "`limit` caps the number of elements returned; it defaults to 10, may not be below 1 and
        may not exceed 100. `offset` is the number of elements to skip and defaults to 0."

        Design: Corner/entities/corner_enrollment_list_paginates_with_total_count_and_has_more
        """
        set_clock("2026-08-01T00:00:00Z")
        first = register_enrollment(primary_parent_name="Parent A")
        set_clock("2026-08-01T00:01:00Z")
        second = register_enrollment(primary_parent_name="Parent B")
        set_clock("2026-08-01T00:02:00Z")
        third = register_enrollment(
            primary_parent_name="Parent C", program_type="PUBLIC_DONATION"
        )

        admin = make_platform_admin_headers()
        page_one, meta_one = validate_paginated(
            api_client.list_enrollments(admin, {"limit": 2, "offset": 0})
        )
        page_two, meta_two = validate_paginated(
            api_client.list_enrollments(admin, {"limit": 2, "offset": 2})
        )

        assert [row["id"] for row in page_one] == [first["id"], second["id"]]
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True

        assert [row["id"] for row in page_two] == [third["id"]]
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False

    def test_an_unparameterised_call_uses_the_default_limit(self):
        """`total_count` counts the whole filtered set, not the returned window.

        "`total_count` counts every element that satisfies the request's filters before the
        pagination window is applied, and `has_more` is true exactly when elements remain beyond
        the current window."

        Design: Corner/entities/corner_enrollment_list_paginates_with_total_count_and_has_more
        """
        set_clock("2026-08-01T00:00:00Z")
        register_enrollment(primary_parent_name="Parent A")
        set_clock("2026-08-01T00:01:00Z")
        register_enrollment(primary_parent_name="Parent B")
        set_clock("2026-08-01T00:02:00Z")
        register_enrollment(primary_parent_name="Parent C", program_type="PUBLIC_DONATION")

        rows, meta = validate_paginated(api_client.list_enrollments(make_platform_admin_headers()))

        assert len(rows) == 3
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0


class TestNotFoundSurface:
    def test_a_well_formed_but_absent_unit_id_answers_with_the_units_own_code(self):
        """Each entity owns its own 404 identifier.

        "Each entity has its own 404 code — `ERR_ENROLLMENT_NOT_FOUND`,
        `ERR_STORAGE_ACCOUNT_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, `ERR_COLLECTION_NOT_FOUND`,
        `ERR_UNIT_NOT_FOUND`, `ERR_PROCESSING_RUN_NOT_FOUND`, `ERR_QUALITY_TEST_NOT_FOUND`,
        `ERR_SCREENING_NOT_FOUND`, `ERR_TANK_NOT_FOUND`, `ERR_EXCURSION_NOT_FOUND`,
        `ERR_LISTING_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` and `ERR_RESERVATION_NOT_FOUND`"

        Design: Corner/entities/corner_unit_get_with_unknown_uuid_returns_unit_not_found
        """
        set_clock("2026-08-01T00:00:00Z")

        response = api_client.get_unit(UNKNOWN_UUID, make_medical_director_headers("md-001"))

        body = validate_error(response, ApiErrorId.ERR_UNIT_NOT_FOUND.value, 404)
        assert response.json()["response_type"] == "error"
        assert body["error_id"] == "ERR_UNIT_NOT_FOUND"


class TestRequestShapeSurface:
    def test_an_enrollment_without_a_delivery_date_never_reaches_a_business_rule(self):
        """A missing required field is answered by the request-shape rung.

        "on every write endpoint: the body parses, every required field is present, every enum
        value is a declared member, every numeric field lies inside its declared range and every
        timestamp is RFC 3339 UTC. Otherwise `ERR_VALIDATION_FAILED` (422)."

        Design: Corner/entities/corner_enrollment_create_without_expected_delivery_date_is_rejected
        """
        set_clock("2026-08-01T00:00:00Z")

        payload = _enrollment_payload()
        payload.pop("expected_delivery_date")
        response = api_client.create_enrollment(payload, INTAKE)

        validate_error(response, ApiErrorId.ERR_VALIDATION_FAILED.value, 422)
        _, meta = validate_paginated(api_client.list_enrollments(make_platform_admin_headers()))
        assert meta["total_count"] == 0

    @pytest.mark.parametrize(
        "payload_builder, endpoint",
        [
            (lambda: _enrollment_payload(program_type="RESEARCH_ONLY"), "enrollment"),
            (
                lambda: {"tank_code": "TANK-B", "tank_class": "CRYO_DELUXE", "capacity_slots": 4},
                "tank",
            ),
            (
                lambda: {"tank_code": "TANK-C", "tank_class": "STANDARD", "capacity_slots": 0},
                "tank",
            ),
        ],
    )
    def test_values_outside_their_declared_domain_are_refused(self, payload_builder, endpoint):
        """An enum member outside its domain and a count below its floor both fail the same rung.

        "A `FacilitiesEngineer` commissions a **StorageTank** with a globally unique `tank_code`
        of between 1 and 20 characters, a `tank_class` of either `STANDARD` or `PREMIUM`, a
        `capacity_slots` count of at least 1"

        Design: Corner/entities/corner_enrollment_create_with_undeclared_program_type_is_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        payload = payload_builder()

        if endpoint == "enrollment":
            response = api_client.create_enrollment(payload, INTAKE)
            survivors = api_client.list_enrollments(make_platform_admin_headers())
        else:
            response = api_client.create_storage_tank(
                payload, make_facilities_engineer_headers("fe-001")
            )
            survivors = api_client.list_storage_tanks(make_facilities_engineer_headers())

        validate_error(response, ApiErrorId.ERR_VALIDATION_FAILED.value, 422)
        _, meta = validate_paginated(survivors)
        assert meta["total_count"] == 0


class TestFieldAuthoritySurface:
    def test_omitted_consent_flags_come_back_as_false(self):
        """The two flags default to false, not to null and not to absent.

        "Two consent flags may be supplied at registration and both default to false when
        omitted: `research_use_authorized` and `hla_typing_consent`."

        Design: Corner/entities/corner_enrollment_create_omitting_consent_flags_applies_false_defaults
        """
        set_clock("2026-08-01T00:00:00Z")

        created = validate_success(
            api_client.create_enrollment(
                _enrollment_payload(
                    program_type="PUBLIC_DONATION",
                    primary_parent_name="Dana Ruiz",
                    collection_site_code="SITE-02",
                ),
                INTAKE,
            ),
            201,
        )

        assert created["research_use_authorized"] is False
        assert created["hla_typing_consent"] is False

        fetched = validate_success(api_client.get_enrollment(created["id"], INTAKE))
        assert fetched["research_use_authorized"] is False
        assert fetched["hla_typing_consent"] is False

    def test_a_client_supplied_net_volume_is_discarded_for_the_derived_one(self):
        """The net figure is the server's arithmetic, never the client's claim.

        "The system immediately derives `net_volume_ml` as the gross collection volume minus the
        anticoagulant volume, rounded half up to 1 decimal place"

        Design: Corner/entities/corner_collection_net_volume_computed_and_client_input_ignored
        """
        scenario = build_bank_scenario(stage="kit", tank_code=None)
        set_clock("2026-08-10T06:00:00Z")

        created = validate_success(
            api_client.create_collection(
                {
                    "kit_id": scenario["kit"]["id"],
                    "collected_at": "2026-08-10T05:00:00Z",
                    "collection_volume_ml": 130.0,
                    "anticoagulant_volume_ml": 25.0,
                    "delivery_mode": "VAGINAL",
                    "net_volume_ml": 999.9,
                },
                make_collection_site_headers("cs-001"),
            ),
            201,
        )

        assert created["net_volume_ml"] == pytest.approx(105.0, abs=0.01)
        assert created["hours_to_receipt"] is None
        assert created["received_at"] is None
        assert created["status"] == "COLLECTED"

    def test_a_client_cannot_seed_a_tanks_server_owned_fields(self):
        """Identity, audit triple, status and occupancy are all server-owned.

        "A new tank begins in `status` of `ONLINE`, with `occupied_slots` at 0 and
        `cumulative_excursion_minutes_30d` at 0; `last_temperature_c` and `last_reading_at` are
        null until the first reading arrives."

        Design: Corner/entities/corner_storage_tank_create_system_fields_input_ignored
        """
        set_clock("2026-08-01T00:00:00Z")

        created = validate_success(
            api_client.create_storage_tank(
                {
                    "tank_code": "TANK-A",
                    "tank_class": "STANDARD",
                    "capacity_slots": 4,
                    "id": "11111111-1111-4111-8111-111111111111",
                    "created_at": "2000-01-01T00:00:00Z",
                    "version": 77,
                    "status": "OFFLINE",
                    "occupied_slots": 3,
                },
                make_facilities_engineer_headers("fe-001"),
            ),
            201,
        )

        assert created["id"] != "11111111-1111-4111-8111-111111111111"
        assert created["created_at"].startswith("2026-08-01T00:00:00")
        assert created["version"] == 1
        assert created["status"] == "ONLINE"
        assert created["occupied_slots"] == 0
        assert created["last_temperature_c"] is None
        assert created["last_reading_at"] is None


class TestQualityTestImmutability:
    def test_the_test_record_carries_no_version_and_no_updated_at(self):
        """The one entity in the bank that has no audit triple.

        "The `QualityTest` resource is the single exception: a test record is immutable once
        written, so it carries only `id` and `created_at`. It has no `updated_at` field and no
        `version` field, and neither field appears in its representation."

        Design: Corner/entities/corner_quality_test_row_is_immutable_and_version_free
        """
        scenario = build_bank_scenario(stage="reduced", tank_code=None)

        created = validate_success(
            api_client.create_quality_test(
                {
                    "unit_id": scenario["unit"]["id"],
                    "test_kind": "POST_PROCESSING",
                    "tnc_millions": 1000,
                    "cd34_thousands": 2400,
                    "viability_pct": 88.0,
                    "volume_ml": 25.0,
                    "sterility_result": "NEGATIVE",
                },
                make_technologist_headers("tech-001"),
            ),
            201,
        )

        assert_quality_test(created)
        assert created["performed_at"].startswith("2026-08-11T00:00:00")
        assert created["performed_by_user_id"] == "tech-001"
        assert created["outcome"] == "PASS"
        assert created["failure_reason_codes"] == []

        fetched = validate_success(
            api_client.get_quality_test(created["id"], make_medical_director_headers())
        )
        assert fetched == created


class TestForeignKeyResolution:
    def test_an_unresolvable_body_reference_answers_with_that_entitys_not_found(self):
        """A bogus foreign key is caught before any state or consent rule runs.

        "A body reference to a non-existent enrollment is `ERR_ENROLLMENT_NOT_FOUND`, a body
        reference to a non-existent unit is `ERR_UNIT_NOT_FOUND`, and so on for every reference
        the system accepts"

        Design: Corner/entities/corner_collection_against_unknown_kit_returns_kit_not_found
        """
        set_clock("2026-08-10T06:00:00Z")

        collection_response = api_client.create_collection(
            {
                "kit_id": UNKNOWN_UUID_ALT,
                "collected_at": "2026-08-10T05:00:00Z",
                "collection_volume_ml": 130.0,
                "anticoagulant_volume_ml": 25.0,
                "delivery_mode": "VAGINAL",
            },
            make_collection_site_headers("cs-001"),
        )
        account_response = api_client.create_storage_account(
            {
                "enrollment_id": UNKNOWN_UUID_THIRD,
                "billing_contact_email": "a@example.com",
                "plan_term_years": 5,
                "prepaid_through_date": "2031-08-01",
            },
            make_billing_admin_headers("ba-001"),
        )

        validate_error(collection_response, ApiErrorId.ERR_KIT_NOT_FOUND.value, 404)
        validate_error(account_response, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND.value, 404)

    def test_each_enrollment_sees_only_its_own_kit(self):
        """Reverse navigation is scoped to the parent that owns the foreign key.

        "Dispatch stamps `dispatched_at` from the logical clock and computes `expires_at` as
        `dispatched_at` plus a shelf life of 120 days; the kit begins in `DISPATCHED`, and the
        enrollment advances `ACTIVE → KIT_DISPATCHED`."

        Design: Corner/entities/corner_kit_fk_is_reverse_reachable_and_scoped_per_enrollment
        """
        set_clock("2026-08-01T00:00:00Z")
        first = register_enrollment(primary_parent_name="Parent One")
        sign_consent(first["id"], consent_document_hash="hash-1")
        second = register_enrollment(
            primary_parent_name="Parent Two", expected_delivery_date="2026-08-12"
        )
        sign_consent(second["id"], consent_document_hash="hash-2")
        kit_one = dispatch_kit(first["id"], kit_lot_code="LOT-1", courier_tracking_code="TRK-1")
        kit_two = dispatch_kit(second["id"], kit_lot_code="LOT-2", courier_tracking_code="TRK-2")

        rows_one, meta_one = validate_paginated(
            api_client.list_enrollment_collection_kits(first["id"], INTAKE)
        )
        rows_two, meta_two = validate_paginated(
            api_client.list_enrollment_collection_kits(second["id"], INTAKE)
        )

        assert meta_one["total_count"] == 1
        assert rows_one[0]["id"] == kit_one["id"]
        assert rows_one[0]["enrollment_id"] == first["id"]
        assert rows_one[0]["expires_at"].startswith("2026-11-29T00:00:00")

        assert meta_two["total_count"] == 1
        assert rows_two[0]["id"] == kit_two["id"]
        assert rows_two[0]["enrollment_id"] == second["id"]

    def test_an_empty_child_set_is_a_successful_empty_list(self):
        """No account yet is not a missing resource.

        "An empty result set is a successful 200 response with an empty `data` array and a
        `total_count` of 0 — never an error."

        Design: Corner/entities/corner_kit_fk_is_reverse_reachable_and_scoped_per_enrollment
        """
        set_clock("2026-08-01T00:00:00Z")
        enrollment = register_enrollment(primary_parent_name="Parent One")
        sign_consent(enrollment["id"], consent_document_hash="hash-1")

        rows, meta = validate_paginated(
            api_client.list_enrollment_storage_accounts(
                enrollment["id"], make_billing_admin_headers("ba-001")
            )
        )

        assert rows == []
        assert meta["total_count"] == 0
