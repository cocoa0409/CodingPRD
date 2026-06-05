"""Registration, field validation, defaults, computed reads, listing, and the clock.

Breadth coverage for the entities corner section: physician/patient creation and
duplicate handling, request-body validation (required/enum/numeric), the platform_fee
default, the derived active_license_count, not-found reads, pagination envelope, and
clock set/read.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    make_physician_headers,
    make_patient_headers,
    board_headers,
    anonymous_headers,
    set_clock,
    create_physician,
    issue_license,
    create_patient,
    setup_cleared_visit,
)


class TestPhysicianRegistration:

    def test_create_physician_returns_201_with_system_fields(self, api):
        """PRD §3.1: "A newly registered physician's `status` is `ACTIVE`, and their
        `active_license_count` begins at 0."
        PRD §2.4: "`id` — a unique, server-minted identifier formatted as a UUID, with no
        type prefix."

        Design: Corner/entities/create_physician_returns_201_with_system_fields
        """
        res = api.create_physician(
            {"full_name": "Dr Vega", "npi": "1234567890", "home_state_code": "CA"}, anonymous_headers(),
        )
        phys = validate_success(res, 201)
        assert is_valid_uuid(phys["id"]), "id must be a server-minted UUID"
        assert phys["status"] == "ACTIVE", f"expected status ACTIVE, got {phys['status']}"
        assert phys["active_license_count"] == 0, (
            f"active_license_count must begin at 0, got {phys['active_license_count']}"
        )

    def test_create_physician_missing_npi_returns_invalid_request(self, api):
        """PRD §3.1: "The `npi` is the ten-digit National Provider Identifier and must
        consist of exactly ten numeric digits; it must also be unique across all
        physicians."

        Design: Corner/entities/create_physician_missing_npi_returns_invalid_request
        """
        res = api.create_physician({"full_name": "Dr Vega", "home_state_code": "CA"}, anonymous_headers())
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_create_physician_bad_npi_length_returns_invalid_request(self, api):
        """PRD §3.1: "The `npi` is the ten-digit National Provider Identifier and must
        consist of exactly ten numeric digits; it must also be unique across all
        physicians."

        Design: Corner/entities/create_physician_bad_npi_length_returns_invalid_request
        """
        res = api.create_physician(
            {"full_name": "Dr Vega", "npi": "123456789", "home_state_code": "CA"}, anonymous_headers(),
        )
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_duplicate_npi_returns_duplicate_resource(self, api):
        """PRD §3.1: "Should a physician's `npi` duplicate an existing one, registration
        is rejected with `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/entities/duplicate_npi_returns_duplicate_resource
        """
        api.create_physician({"full_name": "Dr One", "npi": "1234567890", "home_state_code": "CA"}, anonymous_headers())
        res = api.create_physician({"full_name": "Dr Two", "npi": "1234567890", "home_state_code": "TX"}, anonymous_headers())
        validate_error(res, "ERR_DUPLICATE_RESOURCE")

    def test_get_physician_nonexistent_returns_not_found(self, api):
        """PRD §2.5: "the platform validates the identifiers in the path from left to
        right, and rejects the request with `ERR_NOT_FOUND` at the *first* identifier in
        the path that does not resolve to an existing resource."

        Design: Corner/entities/get_physician_nonexistent_returns_not_found
        """
        res = api.get_physician("00000000-0000-4000-8000-000000000000", board_headers())
        validate_error(res, "ERR_NOT_FOUND")

    def test_physician_computed_active_license_count_ignores_input(self, api):
        """PRD §3.1: "The physician's `active_license_count` is a derived figure: it is the
        number of that physician's `StateLicense` rows whose `status` is `ACTIVE`, and it
        is recomputed every time any of that physician's licenses changes status."

        Design: Corner/entities/physician_computed_active_license_count_ignores_input
        """
        physician = create_physician(imlc_eligible=True, home_state_code="CA")
        issue_license(physician["id"], state_code="CA", issuance_type="FULL")
        issue_license(physician["id"], state_code="NV", issuance_type="COMPACT_EXPEDITED")
        phys = validate_success(api.get_physician(physician["id"], board_headers()), 200)
        assert phys["active_license_count"] == 2, (
            f"derived count must be 2 after two ACTIVE licenses, got {phys['active_license_count']}"
        )

    def test_list_physicians_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_physicians_pagination_envelope
        """
        api.create_physician({"full_name": "Dr One", "npi": "1111111111", "home_state_code": "CA"}, anonymous_headers())
        api.create_physician({"full_name": "Dr Two", "npi": "2222222222", "home_state_code": "TX"}, anonymous_headers())
        data, meta = validate_paginated(api.list_physicians(board_headers(), params={"limit": 1, "offset": 0}))
        assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
        assert meta["has_more"] is True, "expected has_more True with limit 1 of 2"
        assert len(data) == 1, f"expected one item with limit 1, got {len(data)}"


class TestPatientRegistration:

    def test_duplicate_patient_email_returns_duplicate_resource(self, api):
        """PRD §3.2: "The `email` doubles as the login identity and must be unique across
        patients; a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/entities/duplicate_patient_email_returns_duplicate_resource
        """
        api.create_patient({"full_name": "Pat A", "email": "a@x.com", "residence_state_code": "CA"}, anonymous_headers())
        res = api.create_patient({"full_name": "Pat A2", "email": "a@x.com", "residence_state_code": "TX"}, anonymous_headers())
        validate_error(res, "ERR_DUPLICATE_RESOURCE")


class TestVisitRequestValidation:

    def test_create_visit_bad_modality_enum_returns_invalid_request(self, api):
        """PRD §3.2: "the `modality` (`VIDEO` or `AUDIO_ONLY`)".

        Design: Corner/entities/create_visit_bad_modality_enum_returns_invalid_request
        """
        physician = create_physician(home_state_code="CA")
        patient = create_patient(residence_state_code="CA")
        res = api.create_visit({
            "physician_id": physician["id"], "patient_id": patient["id"], "modality": "PHONE",
            "scheduled_at": "2026-04-02T10:00:00.000Z", "determined_state_code": "CA", "list_fee_cents": 10000,
        }, make_patient_headers(patient["id"]))
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_create_visit_zero_list_fee_returns_invalid_request(self, api):
        """PRD §3.2: "The `list_fee_cents` is the platform's list (rack) clinical fee and
        must be strictly greater than zero".

        Design: Corner/entities/create_visit_negative_list_fee_returns_invalid_request
        """
        physician = create_physician(home_state_code="CA")
        patient = create_patient(residence_state_code="CA")
        res = api.create_visit({
            "physician_id": physician["id"], "patient_id": patient["id"], "modality": "VIDEO",
            "scheduled_at": "2026-04-02T10:00:00.000Z", "determined_state_code": "CA", "list_fee_cents": 0,
        }, make_patient_headers(patient["id"]))
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_visit_default_platform_fee_zero_when_omitted(self, api):
        """PRD §3.2: "the `platform_fee_cents` is an additional technology/service fee that
        defaults to 0 when omitted, must be zero or greater, and is consulted only by the
        self-pay cost path."
        PRD §3.5: "the patient's cost is the sum of those two already-rounded shares."

        Design: Corner/entities/visit_default_platform_fee_zero_when_omitted
        """
        # platform_fee omitted -> 0; self-pay cost = round(10000*0.8) + round(0*0.8) = 8000 + 0.
        _, _, _, cleared = setup_cleared_visit(visit_overrides={"list_fee_cents": 10000})
        phys_headers = make_physician_headers(cleared["physician_id"])
        approved = validate_success(api.approve_visit(cleared["id"], phys_headers), 200)
        assert approved["platform_fee_cents"] == 0, (
            f"omitted platform_fee should default to 0, got {approved['platform_fee_cents']}"
        )
        assert approved["patient_cost_cents"] == 8000, (
            f"self-pay cost with 0 platform fee expected 8000, got {approved['patient_cost_cents']}"
        )


class TestClock:

    def test_clock_state_set_and_read(self, api):
        """PRD §2.4: "The clock begins at `1970-01-01T00:00:00.000Z` and is advanced only
        through the test-driving clock-set capability, which writes a supplied
        `current_utc` instant."

        Design: Corner/entities/clock_state_set_and_read
        """
        validate_success(api.set_clock({"current_utc": "2026-05-15T08:30:00.000Z"}, anonymous_headers()), 200)
        clock = validate_success(api.get_clock(anonymous_headers()), 200)
        assert clock["current_utc"] == "2026-05-15T08:30:00.000Z", (
            f"clock should read back the set instant, got {clock['current_utc']}"
        )
