"""Program creation defaults, claim creation defaults, and claim-list envelope."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_settlement_program, assert_claim,
    create_program_payload, create_claimant_payload, create_claim_payload,
    create_program, create_claimant, create_submitted_claim,
    DEFAULT_CLOCK_UTC,
    NON_EXISTENT_UUID,
)


class TestProgramCreation:
    def test_create_program_returns_201_with_version_one(self, api, program_admin_headers):
        """PRD §2.4: "`version`, an integer that starts at 1 and increments by exactly 1 on every mutation of that resource."

        Design: Corner/entities/create_program_returns_201_with_common_fields
        """
        payload = create_program_payload(program_code="MT-CRE", tort_name="Test", qsf_principal_cents=5_000_000)
        resp = api.create_program(payload, program_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_settlement_program(data)
        assert data["version"] == 1, f"New program version must be 1, got {data['version']}"

    def test_create_program_initializes_clock_and_matrix_flag(self, api, program_admin_headers):
        """PRD §3.1: "The new program's logical clock reads exactly `2026-08-01T00:00:00Z`, its `matrix_published` flag is `false`, and its spendable remainder equals its principal."

        Design: Corner/entities/create_program_returns_201_with_common_fields
        """
        payload = create_program_payload(program_code="MT-CRE2", tort_name="Test", qsf_principal_cents=5_000_000)
        resp = api.create_program(payload, program_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["current_utc"] == DEFAULT_CLOCK_UTC, (
            f"Program clock must initialize to {DEFAULT_CLOCK_UTC}, got {data['current_utc']}"
        )
        assert data["matrix_published"] is False
        assert data["qsf_remaining_cents"] == 5_000_000


class TestClaimCreation:
    def test_create_claim_missing_claimant_id_returns_invalid_request(self, api, program_admin_headers, intake_specialist_headers):
        """PRD §3.2: "Denial at intake moves the claim from `SUBMITTED` to the terminal `DENIED` status, sets `eligibility_status` to `FAILED`, and requires a non-empty `denied_reason` — an empty reason is rejected as `ERR_INVALID_REQUEST` (HTTP 400), and denying a claim that is not `SUBMITTED` is again `ERR_CLAIM_INVALID_STATE`." (The PRD routes every required-field / malformed-input rejection through `ERR_INVALID_REQUEST`; §5 maps it to HTTP 400.)

        Design: Corner/entities/create_claim_missing_claimant_id_returns_invalid_request
        """
        program = create_program(program_code="MT-REQ")
        resp = api.create_claim(program["id"], {}, intake_specialist_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_new_claim_has_default_parallel_posture_dimensions(self, api, intake_specialist_headers):
        """PRD §3.2: "All three parallel posture dimensions start at their defaults: `eligibility_status` is `PENDING`, `injury_verification_status` is `PENDING`, and `lien_posture` — which takes one of `NOT_STARTED`, `IDENTIFYING`, `NEGOTIATING`, or `ALL_RESOLVED` over the claim's life — starts at `NOT_STARTED`."

        Design: Corner/entities/claim_default_enums_applied
        """
        program = create_program(program_code="MT-DEF")
        claimant = create_claimant(program["id"], full_name="Sam", ssn_last4="1010")
        resp = api.create_claim(program["id"], create_claim_payload(claimant["id"]), intake_specialist_headers)
        data = validate_success(resp, expected_status=201)
        assert_claim(data)
        assert data["eligibility_status"] == "PENDING"
        assert data["injury_verification_status"] == "PENDING"
        assert data["lien_posture"] == "NOT_STARTED"

    def test_new_claim_monetary_fields_start_at_zero(self, api, intake_specialist_headers):
        """PRD §3.2: "The monetary fields `gross_award_cents`, `total_lien_cents`, `attorney_fee_cents`, `net_award_cents`, and `qsf_reservation_cents` all start at 0, and `active_appeal_id` is null."

        Design: Corner/entities/claim_default_enums_applied
        """
        program = create_program(program_code="MT-DEF2")
        claimant = create_claimant(program["id"], full_name="Sam Two", ssn_last4="1011")
        resp = api.create_claim(program["id"], create_claim_payload(claimant["id"]), intake_specialist_headers)
        data = validate_success(resp, expected_status=201)
        for field in ("gross_award_cents", "total_lien_cents", "attorney_fee_cents", "net_award_cents", "qsf_reservation_cents"):
            assert data[field] == 0, f"{field} must start at 0, got {data[field]}"
        assert data["active_appeal_id"] is None

    def test_claimant_injury_category_enum_out_of_range(self, api, intake_specialist_headers):
        """PRD §3.2: "An `IntakeSpecialist` registers a claimant with `full_name`, `date_of_birth`, `ssn_last4` (exactly four numeric characters), the exposure window `date_of_exposure_start` through `date_of_exposure_end`, the `date_of_diagnosis`, an `injury_category` of `QUALIFYING_CAT_A`, `QUALIFYING_CAT_B`, or `NON_QUALIFYING`, and the `represented_by_counsel` flag that later governs attorney fees."

        Design: Corner/entities/claimant_invalid_injury_category_enum_returns_invalid_request
        """
        program = create_program(program_code="MT-EN")
        payload = create_claimant_payload(full_name="Tina", ssn_last4="1111", injury_category="BOGUS")
        resp = api.create_claimant(program["id"], payload, intake_specialist_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_claim_returns_not_found(self, api, program_admin_headers):
        """PRD §2.7: "Any failure of existence or nesting is rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_claim_returns_not_found
        """
        program = create_program(program_code="MT-NF")
        resp = api.get_claim(program["id"], NON_EXISTENT_UUID, program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestClaimListing:
    def test_list_claims_pagination_envelope(self, api, program_admin_headers):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `total_count` reports the total number of matching resources and `has_more` indicates whether additional pages exist beyond the current window."

        Design: Corner/entities/list_claims_pagination_envelope
        """
        program = create_program(program_code="MT-PG")
        claimant = create_claimant(program["id"], full_name="Vic", ssn_last4="1313")
        create_submitted_claim(program["id"], claimant["id"])
        resp = api.list_claims(program["id"], program_admin_headers, params={"limit": 10, "offset": 0})
        data, meta = validate_paginated(resp)
        assert isinstance(data, list) and len(data) == 1, f"Expected exactly 1 claim, got {len(data)}"
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0

    def test_list_claims_response_type_is_array(self, api, program_admin_headers):
        """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

        Design: Corner/entities/list_claims_pagination_envelope
        """
        program = create_program(program_code="MT-PG2")
        claimant = create_claimant(program["id"], full_name="Vic Two", ssn_last4="1314")
        create_submitted_claim(program["id"], claimant["id"])
        resp = api.list_claims(program["id"], program_admin_headers, params={"limit": 10, "offset": 0})
        body = resp.json()
        assert body.get("response_type") == "array", f"List endpoints must use response_type 'array', got {body.get('response_type')}"
        assert "api_request_id" in body.get("meta", {}), "meta.api_request_id must be present"
