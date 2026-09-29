"""The outer rungs of the ladder: identity, ownership, path resolution and the amendment budget."""

from test_helpers import (
    NOT_FOUND_BY_ENTITY,
    UNDECLARED_ROLE_NAME,
    UNDECLARED_ROLE_USER_ID,
    UNKNOWN_UUID_ALT,
    ApiErrorId,
    api_client,
    build_user_headers,
    make_parent_guardian_headers,
    make_platform_admin_headers,
    open_consent_amendment,
    read_enrollment,
    register_enrollment,
    set_clock,
    sign_consent,
    validate_error,
    validate_paginated,
    validate_success,
)


def _every_by_id_read():
    """One reader per entity, each addressed with the same fabricated identifier."""
    admin = make_platform_admin_headers()
    return {
        "enrollment": api_client.get_enrollment(UNKNOWN_UUID_ALT, admin),
        "storage_account": api_client.get_storage_account(UNKNOWN_UUID_ALT, admin),
        "collection_kit": api_client.get_collection_kit(UNKNOWN_UUID_ALT, admin),
        "collection": api_client.get_collection(UNKNOWN_UUID_ALT, admin),
        "unit": api_client.get_unit(UNKNOWN_UUID_ALT, admin),
        "processing_run": api_client.get_processing_run(UNKNOWN_UUID_ALT, admin),
        "quality_test": api_client.get_quality_test(UNKNOWN_UUID_ALT, admin),
        "maternal_screening": api_client.get_maternal_screening(UNKNOWN_UUID_ALT, admin),
        "storage_tank": api_client.get_storage_tank(UNKNOWN_UUID_ALT, admin),
        "temperature_excursion": api_client.get_excursion(UNKNOWN_UUID_ALT, admin),
        "registry_listing": api_client.get_registry_listing(UNKNOWN_UUID_ALT, admin),
        "storage_invoice": api_client.get_storage_invoice(UNKNOWN_UUID_ALT, admin),
        "reservation": api_client.get_reservation(UNKNOWN_UUID_ALT, admin),
    }


class TestTheThirteenNotFoundCodes:
    def test_each_by_id_read_answers_with_its_own_entity_code(self):
        """A shared generic 404 would satisfy none of the thirteen expectations.

        "When a path carries an identifier, the identifier is resolved before any body field is
        examined."

        Design: Corner/errors/corner_every_entity_read_with_an_unknown_id_returns_its_own_not_found_code
        """
        set_clock("2026-08-01T00:00:00Z")

        responses = _every_by_id_read()

        assert len(responses) == 13
        for entity, response in responses.items():
            validate_error(response, NOT_FOUND_BY_ENTITY[entity], 404)

    def test_the_thirteen_codes_are_distinct_and_none_of_them_is_a_role_refusal(self):
        """The platform operator is authorized everywhere, so nothing may answer 403.

        "Where a path carries more than one identifier, resolution proceeds strictly left to right
        and the first unresolvable segment determines the error."

        Design: Corner/errors/corner_every_entity_read_with_an_unknown_id_returns_its_own_not_found_code
        """
        set_clock("2026-08-01T00:00:00Z")

        responses = _every_by_id_read()

        codes = []
        for response in responses.values():
            assert response.status_code == 404, response.text
            codes.append(response.json()["data"]["error_id"])

        assert len(set(codes)) == 13
        assert sorted(codes) == sorted(NOT_FOUND_BY_ENTITY.values())


class TestTheAuthenticationRung:
    def test_an_absent_user_id_and_an_undeclared_role_both_answer_the_same_way(self):
        """Neither call can be distinguished from the other by its error identifier.

        "If either header is absent, or if `X-User-Role` is not one of the ten role names declared
        below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/corner_missing_x_user_header_returns_unauthenticated
        """
        set_clock("2026-08-01T00:00:00Z")

        headerless = api_client.list_storage_tanks({"X-User-Role": "PlatformAdmin"})
        validate_error(headerless, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        undeclared = api_client.list_storage_tanks(
            build_user_headers(UNDECLARED_ROLE_USER_ID, UNDECLARED_ROLE_NAME)
        )
        validate_error(undeclared, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    def test_the_first_rung_pre_empts_both_the_role_check_and_the_body_check(self):
        """A write whose role is undeclared and whose body is unusable still answers 401.

        "Role membership is checked before any body parsing, any path lookup and any business
        rule."

        Design: Corner/errors/corner_missing_x_user_header_returns_unauthenticated
        """
        set_clock("2026-08-01T00:00:00Z")

        response = api_client.create_storage_tank(
            {"tank_code": "TANK-Z", "tank_class": "GOLD", "capacity_slots": -4},
            build_user_headers(UNDECLARED_ROLE_USER_ID, UNDECLARED_ROLE_NAME),
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        rows, meta = validate_paginated(api_client.list_storage_tanks(make_platform_admin_headers()))
        assert meta["total_count"] == 0
        assert rows == []


def _two_unrelated_enrollments():
    """Two enrollments, each its own ParentGuardian principal, neither consented."""
    set_clock("2026-08-01T00:00:00Z")
    first = register_enrollment(
        primary_parent_name="Avery Lin",
        expected_delivery_date="2026-08-10",
        collection_site_code="SITE-01",
    )
    second = register_enrollment(
        primary_parent_name="Blair Nakamura",
        expected_delivery_date="2026-08-20",
        collection_site_code="SITE-02",
    )
    return first, second


class TestParentGuardianOwnership:
    def test_a_guardian_may_read_its_own_enrollment_but_not_its_neighbours(self):
        """The role is authorized on the endpoint, so only the identity check can refuse.

        "Concretely, a `ParentGuardian` may address only its own enrollment and the rows reachable
        from it — its `StorageAccount`, its `CollectionKit` rows, its `MaternalScreening` rows, its
        `CordBloodUnit` rows and its `StorageInvoice` rows — and any attempt to address another
        enrollment's data is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/errors/corner_parent_guardian_cannot_read_another_enrollment
        """
        first, second = _two_unrelated_enrollments()
        guardian = make_parent_guardian_headers(first["id"])

        foreign = api_client.get_enrollment(second["id"], guardian)
        validate_error(foreign, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

        own = validate_success(api_client.get_enrollment(first["id"], guardian))
        assert own["id"] == first["id"]
        assert own["primary_parent_name"] == "Avery Lin"

    def test_the_rule_reaches_the_child_listings_of_a_foreign_enrollment(self):
        """An empty list would be a leak of the neighbour's existence, so 403 comes first.

        "This ownership check applies to fetching an enrollment, listing an enrollment's storage
        accounts, listing an enrollment's collection kits, listing an enrollment's maternal
        screenings, signing consent, opening a consent amendment, withdrawing the enrollment,
        fetching a storage account, listing a storage account's invoices, and posting a payment
        against an invoice."

        Design: Corner/errors/corner_parent_guardian_cannot_read_another_enrollment
        """
        first, second = _two_unrelated_enrollments()
        guardian = make_parent_guardian_headers(first["id"])

        kits = api_client.list_enrollment_collection_kits(second["id"], guardian)
        validate_error(kits, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

        accounts = api_client.list_enrollment_storage_accounts(second["id"], guardian)
        validate_error(accounts, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

        screenings = api_client.list_enrollment_maternal_screenings(second["id"], guardian)
        validate_error(screenings, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)


def _enrollment_that_has_spent_its_amendment_budget():
    """One enrollment consented once, then amended and re-signed three times over."""
    set_clock("2026-08-01T00:00:00Z")
    enrollment = register_enrollment(
        primary_parent_name="Avery Lin",
        expected_delivery_date="2026-08-10",
        collection_site_code="SITE-01",
    )
    sign_consent(enrollment["id"], consent_document_hash="hash-amd-v1")
    for cycle in (1, 2, 3):
        amended = open_consent_amendment(enrollment["id"])
        assert amended["consent_status"] == "AMENDMENT_PENDING"
        assert amended["consent_amendment_count"] == cycle
        sign_consent(enrollment["id"], consent_document_hash=f"hash-amd-v{cycle + 1}")
    return read_enrollment(enrollment["id"])


class TestTheAmendmentBudget:
    def test_three_amendment_cycles_are_accepted_and_leave_the_consent_current(self):
        """The budget is spent exactly, not overspent and not left short.

        "Opening one carries an `amendment_reason_code` and drives the consent axis `CONSENTED →
        AMENDMENT_PENDING`, incrementing `consent_amendment_count` by 1."

        Design: Corner/errors/corner_fourth_consent_amendment_hits_the_declared_limit
        """
        enrollment = _enrollment_that_has_spent_its_amendment_budget()

        assert enrollment["consent_amendment_count"] == 3
        assert enrollment["consent_status"] == "CONSENTED"
        assert enrollment["consent_version"] == 4
        assert enrollment["lifecycle_status"] == "ACTIVE"

    def test_the_fourth_amendment_is_refused_and_writes_nothing(self):
        """A counter already at three cannot be pushed to four by a refused request.

        "A family may traverse this loop at most three times: when `consent_amendment_count` has
        already reached 3, a further amendment is refused with `ERR_CONSENT_AMENDMENT_LIMIT`."

        Design: Corner/errors/corner_fourth_consent_amendment_hits_the_declared_limit
        """
        enrollment = _enrollment_that_has_spent_its_amendment_budget()
        version_before = enrollment["consent_version"]

        response = api_client.open_consent_amendment(
            enrollment["id"],
            {"amendment_reason_code": "RESEARCH_USE_CHANGE"},
            make_platform_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_CONSENT_AMENDMENT_LIMIT.value, 409)

        after = read_enrollment(enrollment["id"])
        assert after["consent_status"] == "CONSENTED"
        assert after["consent_amendment_count"] == 3
        assert after["consent_version"] == version_before
