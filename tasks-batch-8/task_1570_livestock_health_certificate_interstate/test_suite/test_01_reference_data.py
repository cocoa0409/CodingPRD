"""Reference data: premises, veterinarians, entry-requirement matrix defaults,
schema validation, and FK existence enforcement (PRD §2.5, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    assert_entry_requirement,
    assert_premises,
    assert_test_record,
    assert_veterinarian,
    create_entry_requirement_payload,
    create_premises,
    create_premises_payload,
    create_quarantine_order_payload,
    create_test_record_payload,
    create_veterinarian,
    make_officer_headers,
    make_vet_headers,
    validate_error,
    validate_success,
)


class TestPremisesDefaults:
    def test_premises_creation_defaults_applied(self, api, admin_headers, auditor_headers):
        """PRD §3.1: "The premises begins life with `disease_status` `MONITORED`
        unless the administrator supplies a different standing at registration,
        and its `current_head_count` is initialized to `initial_head_count`."

        Design: Corner/entities/premises_creation_defaults_applied
        """
        resp = api.create_premises(
            {
                "name": "Ranch D1",
                "county": "Yolo",
                "state_code": "CA",
                "species_code": "CATTLE",
                "initial_head_count": 20,
            },
            admin_headers,
        )
        created = validate_success(resp, 201)
        assert_premises(created)

        data = validate_success(api.get_premises(created["id"], auditor_headers))
        assert data["disease_status"] == "MONITORED", (
            f"default disease_status must be MONITORED, got {data['disease_status']}"
        )
        assert data["current_head_count"] == 20, (
            f"current_head_count must initialize to initial_head_count 20, "
            f"got {data['current_head_count']}"
        )


class TestEntryRequirementDefaults:
    def test_entry_requirement_defaults_applied(self, api, admin_headers, auditor_headers):
        """PRD §3.1: "`vaccination_min_days_before_inspection` (defaulting to 0,
        never negative) sets the minimum whole-day lead time, inclusive."
        PRD §3.1: "a null `effective_until` means the row is open-ended".
        PRD §3.1: "Rows begin `ACTIVE`, and may later be `RETIRED`."

        Design: Corner/entities/entry_requirement_defaults_applied
        """
        resp = api.create_entry_requirement(
            {
                "destination_state_code": "KS",
                "species_code": "CATTLE",
                "test_type": "BRUCELLOSIS",
                "test_validity_days": 30,
                "vaccination_required": False,
                "permit_required": True,
                "effective_from": "2026-06-01T00:00:00Z",
            },
            admin_headers,
        )
        data = validate_success(resp, 201)
        assert_entry_requirement(data)
        assert data["vaccination_min_days_before_inspection"] == 0, (
            f"default vaccination_min_days_before_inspection must be 0, "
            f"got {data['vaccination_min_days_before_inspection']}"
        )
        assert data["status"] == "ACTIVE", (
            f"a new matrix row must begin ACTIVE, got {data['status']}"
        )
        assert data["effective_until"] is None, (
            f"omitted effective_until must read null (open-ended), got {data['effective_until']!r}"
        )


class TestTestRecordDefaults:
    def test_test_record_default_result_pending(self, api, admin_headers, lab_headers):
        """PRD §3.2: "The record is born with `result` `RESULT_PENDING`, and
        the test-records listing under a premises supports the usual `limit`
        and `offset` pagination."

        Design: Corner/entities/test_record_default_result_pending
        """
        premises = create_premises(name="Ranch D3", initial_head_count=20)
        resp = api.create_test_record(
            create_test_record_payload(premises_id=premises["id"], lab_reference="LAB-D3"),
            lab_headers,
        )
        data = validate_success(resp, 201)
        assert_test_record(data)
        assert data["result"] == "RESULT_PENDING", (
            f"a new test record must be born RESULT_PENDING, got {data['result']}"
        )


class TestVeterinarianCredentialComputed:
    def test_veterinarian_is_credential_current_computed(self, api, admin_headers):
        """PRD §3.1: "The derived flag `is_credential_current` recomputes on
        every read: it is true exactly when `status` is `ACTIVE` and
        `accreditation_expires_at` is at or after the logical clock."
        PRD §2.4: "At startup, before any administrative action, the logical
        clock reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/veterinarian_is_credential_current_computed
        """
        resp_ok = api.create_veterinarian(
            {
                "full_name": "Dr. Current",
                "accreditation_number": "ACCRED-C",
                "accreditation_expires_at": "2027-01-01T00:00:00Z",
            },
            admin_headers,
        )
        vet_ok = validate_success(resp_ok, 201)
        assert_veterinarian(vet_ok)
        assert vet_ok["status"] == "ACTIVE"
        assert vet_ok["is_credential_current"] is True, (
            "expiry 2027-01-01 >= startup clock 2026-08-01 must read current"
        )

        resp_bad = api.create_veterinarian(
            {
                "full_name": "Dr. Expired",
                "accreditation_number": "ACCRED-X",
                "accreditation_expires_at": "2026-07-01T00:00:00Z",
            },
            admin_headers,
        )
        vet_bad = validate_success(resp_bad, 201)
        assert vet_bad["status"] == "ACTIVE", (
            "a new veterinarian starts ACTIVE regardless of the expiry instant"
        )
        assert vet_bad["is_credential_current"] is False, (
            "expiry 2026-07-01 < startup clock 2026-08-01 must read not-current "
            "even though status is ACTIVE"
        )


class TestSchemaValidation:
    def test_premises_invalid_species_enum_rejected(self, api, admin_headers):
        """PRD §2.5: "Required fields must be present, types must be valid,
        enum values must be in range, `head_count` values must be greater than
        zero, `end_at` must be later than `start_at`, `effective_until` must be
        later than `effective_from`, `valid_until` must not be earlier than
        `valid_from`, a test's `test_date` must not be after the certificate's
        `inspection_date`, and `inspection_date` must not be after the logical
        clock."
        PRD §2.5: "Violations yield `ERR_VALIDATION` (HTTP 400) on any endpoint
        that takes a request body."

        Design: Corner/entities/premises_invalid_species_enum_rejected
        """
        resp = api.create_premises(
            create_premises_payload(name="Ranch Bad", species_code="LLAMA", initial_head_count=5),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_premises_missing_required_county_rejected(self, api, admin_headers):
        """PRD §2.5: "Required fields must be present, types must be valid,
        enum values must be in range, `head_count` values must be greater than
        zero, `end_at` must be later than `start_at`, `effective_until` must be
        later than `effective_from`, `valid_until` must not be earlier than
        `valid_from`, a test's `test_date` must not be after the certificate's
        `inspection_date`, and `inspection_date` must not be after the logical
        clock."
        PRD §2.5: "Violations yield `ERR_VALIDATION` (HTTP 400) on any endpoint
        that takes a request body."

        Design: Corner/entities/premises_missing_required_county_rejected
        """
        resp = api.create_premises(
            {
                "name": "Ranch NoCounty",
                "state_code": "CA",
                "species_code": "CATTLE",
                "initial_head_count": 5,
            },
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_certificate_head_count_zero_rejected(self, api, admin_headers, auditor_headers):
        """PRD §3.3: "the `head_count` covered (greater than zero, and editable
        only while the certificate is `DRAFT`)".
        PRD §2.5: "Required fields must be present, types must be valid, enum
        values must be in range, `head_count` values must be greater than zero,
        `end_at` must be later than `start_at`, `effective_until` must be later
        than `effective_from`, `valid_until` must not be earlier than
        `valid_from`, a test's `test_date` must not be after the certificate's
        `inspection_date`, and `inspection_date` must not be after the logical
        clock."

        Design: Corner/entities/certificate_head_count_zero_rejected
        """
        premises = create_premises(name="Ranch D9", initial_head_count=20)
        vet = create_veterinarian()
        resp = api.create_certificate(
            {
                "origin_premises_id": premises["id"],
                "destination_state_code": "KS",
                "species_code": "CATTLE",
                "head_count": 0,
                "inspection_date": "2026-08-01T00:00:00Z",
            },
            make_vet_headers(vet["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_certificate_future_inspection_date_rejected(self, api, admin_headers):
        """PRD §3.3: "the `inspection_date` of the veterinary inspection (which
        may not be later than the logical clock)".
        PRD §2.5: "`inspection_date` must not be after the logical clock.
        Violations yield `ERR_VALIDATION` (HTTP 400)".
        PRD §2.4: "At startup, before any administrative action, the logical
        clock reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/certificate_future_inspection_date_rejected
        """
        premises = create_premises(name="Ranch D10", initial_head_count=20)
        vet = create_veterinarian()
        # Clock left at the startup default 2026-08-01; inspection 2026-08-10 is future.
        resp = api.create_certificate(
            {
                "origin_premises_id": premises["id"],
                "destination_state_code": "KS",
                "species_code": "CATTLE",
                "head_count": 5,
                "inspection_date": "2026-08-10T00:00:00Z",
            },
            make_vet_headers(vet["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_inverted_window_fields_rejected(self, api, admin_headers):
        """PRD §2.5: "Required fields must be present, types must be valid,
        enum values must be in range, `head_count` values must be greater than
        zero, `end_at` must be later than `start_at`, `effective_until` must be
        later than `effective_from`, `valid_until` must not be earlier than
        `valid_from`, a test's `test_date` must not be after the certificate's
        `inspection_date`, and `inspection_date` must not be after the logical
        clock."
        PRD §2.5: "Violations yield `ERR_VALIDATION` (HTTP 400) on any endpoint
        that takes a request body."

        Design: Corner/entities/inverted_window_fields_rejected
        """
        vet = create_veterinarian()

        # Quarantine order with end_at == start_at (must be strictly later).
        resp_q = api.create_quarantine_order(
            create_quarantine_order_payload(
                premises_id="00000000-0000-0000-0000-0000000000aa",
                start_at="2026-08-10T00:00:00Z",
                end_at="2026-08-10T00:00:00Z",
                reason="EQUAL_END",
            ),
            make_officer_headers("officer-a"),
        )
        validate_error(resp_q, ApiErrorId.ERR_VALIDATION)

        # Entry requirement with effective_until == effective_from.
        resp_r = api.create_entry_requirement(
            create_entry_requirement_payload(
                test_type="NONE",
                vaccination_required=False,
                permit_required=False,
                effective_from="2026-08-01T00:00:00Z",
                effective_until="2026-08-01T00:00:00Z",
            ),
            admin_headers,
        )
        validate_error(resp_r, ApiErrorId.ERR_VALIDATION)

        # Permit with valid_until < valid_from (schema beats the dangling FK).
        resp_p = api.create_movement_permit(
            {
                "certificate_id": "00000000-0000-0000-0000-0000000000bb",
                "allocated_head_count": 5,
                "valid_from": "2026-08-11T00:00:00Z",
                "valid_until": "2026-08-10T00:00:00Z",
            },
            make_vet_headers(vet["id"]),
        )
        validate_error(resp_p, ApiErrorId.ERR_VALIDATION)


class TestForeignKeyExistence:
    def test_body_fk_existence_enforced(self, api, admin_headers, lab_headers):
        """PRD §2.5: "Path identifiers must exist and are validated
        strictly left-to-right along the URL hierarchy; body-supplied foreign
        keys — `origin_premises_id`, `test_record_id`, `premises_id`,
        `certificate_id`, `permit_id` — must also resolve to existing rows."
        PRD §2.5: "A missing resource yields its specific not-found error (for
        example `ERR_PREMISES_NOT_FOUND` or `ERR_PERMIT_NOT_FOUND`, HTTP 404;
        the full catalogue appears in §5)."
        PRD §3.5: "The request names the `permit_id` (an unknown one yields
        `ERR_PERMIT_NOT_FOUND`, HTTP 404)".

        Design: Corner/entities/body_fk_existence_enforced
        """
        vet = create_veterinarian()
        bogus_premises = "00000000-0000-0000-0000-0000000000aa"
        bogus_cert = "00000000-0000-0000-0000-0000000000bb"
        bogus_permit = "00000000-0000-0000-0000-0000000000cc"

        resp_t = api.create_test_record(
            create_test_record_payload(premises_id=bogus_premises, lab_reference="LAB-X"),
            lab_headers,
        )
        validate_error(resp_t, ApiErrorId.ERR_PREMISES_NOT_FOUND)

        resp_c = api.create_certificate(
            {
                "origin_premises_id": bogus_premises,
                "destination_state_code": "KS",
                "species_code": "CATTLE",
                "head_count": 5,
                "inspection_date": "2026-08-01T00:00:00Z",
            },
            make_vet_headers(vet["id"]),
        )
        validate_error(resp_c, ApiErrorId.ERR_PREMISES_NOT_FOUND)

        resp_p = api.create_movement_permit(
            {
                "certificate_id": bogus_cert,
                "allocated_head_count": 5,
                "valid_from": "2026-08-11T00:00:00Z",
                "valid_until": "2026-09-08T00:00:00Z",
            },
            make_vet_headers(vet["id"]),
        )
        validate_error(resp_p, ApiErrorId.ERR_CERTIFICATE_NOT_FOUND)

        resp_m = api.create_movement_record(
            {
                "permit_id": bogus_permit,
                "head_count": 2,
                "destination_name": "Nowhere",
                "planned_ship_date": "2026-08-21T00:00:00Z",
            },
            make_vet_headers(vet["id"]),
        )
        validate_error(resp_m, ApiErrorId.ERR_PERMIT_NOT_FOUND)

        resp_q = api.create_quarantine_order(
            create_quarantine_order_payload(
                premises_id=bogus_premises,
                start_at="2026-08-01T00:00:00Z",
                end_at="2026-08-15T00:00:00Z",
                reason="DANGLING",
            ),
            make_officer_headers("officer-a"),
        )
        validate_error(resp_q, ApiErrorId.ERR_PREMISES_NOT_FOUND)

    def test_certificate_create_unknown_vet_identity_404(self, api, admin_headers):
        """PRD §2.1: "When `X-User-Role` is `AccreditedVet`, `X-User-ID` is the
        `id` of the acting `Veterinarian`; a request under this role whose
        `X-User-ID` matches no registered `Veterinarian` row is rejected with
        `ERR_VETERINARIAN_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/certificate_create_unknown_vet_identity_404
        """
        premises = create_premises(name="Ranch D13", initial_head_count=20)
        resp = api.create_certificate(
            {
                "origin_premises_id": premises["id"],
                "destination_state_code": "KS",
                "species_code": "CATTLE",
                "head_count": 5,
                "inspection_date": "2026-08-01T00:00:00Z",
            },
            make_vet_headers("00000000-0000-0000-0000-0000000000dd"),
        )
        validate_error(resp, ApiErrorId.ERR_VETERINARIAN_NOT_FOUND)


class TestNotFound:
    def test_not_found_direct_get_endpoints(self, api, auditor_headers):
        """PRD §2.5: "Path identifiers must exist and are validated
        strictly left-to-right along the URL hierarchy; body-supplied foreign
        keys — `origin_premises_id`, `test_record_id`, `premises_id`,
        `certificate_id`, `permit_id` — must also resolve to existing rows."
        PRD §2.5: "A missing resource yields its specific not-found error (for
        example `ERR_PREMISES_NOT_FOUND` or `ERR_PERMIT_NOT_FOUND`, HTTP 404;
        the full catalogue appears in §5)."
        PRD §3.4: "A certificate id that does not exist yields
        `ERR_CERTIFICATE_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/not_found_direct_get_endpoints
        """
        resp_p = api.get_premises("00000000-0000-0000-0000-000000000001", auditor_headers)
        validate_error(resp_p, ApiErrorId.ERR_PREMISES_NOT_FOUND)

        resp_c = api.get_certificate("00000000-0000-0000-0000-000000000002", auditor_headers)
        validate_error(resp_c, ApiErrorId.ERR_CERTIFICATE_NOT_FOUND)

        resp_m = api.get_movement_permit("00000000-0000-0000-0000-000000000003", auditor_headers)
        validate_error(resp_m, ApiErrorId.ERR_PERMIT_NOT_FOUND)

    def test_not_found_action_endpoints(self, api, admin_headers, lab_headers, officer_headers):
        """PRD §2.5: "Path identifiers must exist and are validated
        strictly left-to-right along the URL hierarchy; body-supplied foreign
        keys — `origin_premises_id`, `test_record_id`, `premises_id`,
        `certificate_id`, `permit_id` — must also resolve to existing rows."
        PRD §2.5: "A missing resource yields its specific not-found error (for
        example `ERR_PREMISES_NOT_FOUND` or `ERR_PERMIT_NOT_FOUND`, HTTP 404;
        the full catalogue appears in §5)."
        PRD §3.6: "a zone id that does not exist yields
        `ERR_OUTBREAK_ZONE_NOT_FOUND` (HTTP 404)."
        PRD §3.7: "an unknown order id yields `ERR_QUARANTINE_ORDER_NOT_FOUND`."
        PRD §3.8: "an unknown audit id yields `ERR_TRANSMISSION_AUDIT_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/not_found_action_endpoints
        """
        vet = create_veterinarian()
        req = validate_success(
            api.create_entry_requirement(
                create_entry_requirement_payload(
                    test_type="NONE", vaccination_required=False, permit_required=False
                ),
                admin_headers,
            ),
            201,
        )

        resp_v = api.suspend_veterinarian(
            "00000000-0000-0000-0000-000000000004", officer_headers
        )
        validate_error(resp_v, ApiErrorId.ERR_VETERINARIAN_NOT_FOUND)

        resp_t = api.report_test_result(
            "00000000-0000-0000-0000-000000000005", {"result": "NEGATIVE"}, lab_headers
        )
        validate_error(resp_t, ApiErrorId.ERR_TEST_RECORD_NOT_FOUND)

        resp_m = api.depart_movement_record(
            "00000000-0000-0000-0000-000000000006", make_vet_headers(vet["id"])
        )
        validate_error(resp_m, ApiErrorId.ERR_MOVEMENT_RECORD_NOT_FOUND)

        resp_z = api.escalate_outbreak_zone(
            "00000000-0000-0000-0000-000000000007", officer_headers
        )
        validate_error(resp_z, ApiErrorId.ERR_OUTBREAK_ZONE_NOT_FOUND)

        resp_q = api.lift_quarantine_order(
            "00000000-0000-0000-0000-000000000008", make_officer_headers("officer-b")
        )
        validate_error(resp_q, ApiErrorId.ERR_QUARANTINE_ORDER_NOT_FOUND)

        resp_a = api.acknowledge_transmission(
            "00000000-0000-0000-0000-000000000009", officer_headers
        )
        validate_error(resp_a, ApiErrorId.ERR_TRANSMISSION_AUDIT_NOT_FOUND)

        resp_r = api.amend_entry_requirement(
            "00000000-0000-0000-0000-00000000000a",
            {
                "expected_requirement_version": req["version"],
                "test_validity_days": 45,
            },
            admin_headers,
        )
        validate_error(resp_r, ApiErrorId.ERR_ENTRY_REQUIREMENT_NOT_FOUND)
