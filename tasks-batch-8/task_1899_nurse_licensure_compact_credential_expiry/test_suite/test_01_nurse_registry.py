"""Nurse registry: creation defaults, input validation, listings, envelopes,
uniqueness, and license retrieval (PRD §2.1-§2.4, §3.1, §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_nurse,
    assert_state_license,
    create_license_draft,
    create_nurse,
    create_nurse_payload,
    create_state_license_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client, TEST_USERS

SPEC1 = TEST_USERS["specialist_1"]
CO1 = TEST_USERS["compliance_1"]


class TestNurseCreation:
    def test_nurse_creation_defaults_and_system_fields(self):
        """PRD §3.1: "A new nurse stands `ONBOARDING`, with `credential_posture`
        `SCHEDULING_SUSPENDED` and `multistate_privilege_status` `NONE`."
        PRD §2.4: "Every persisted resource carries four common properties: `id`,
        a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC
        timestamp with three fractional digits; `updated_at`, refreshed on every
        mutation; and `version`, an integer that increments on every mutation of
        the row."

        Design: Corner/entities/nurse_creation_defaults_and_system_fields
        """
        set_clock()
        resp = api_client.create_nurse(
            create_nurse_payload(full_name="Rita New", email="rita.new@x.com"), SPEC1
        )
        data = validate_success(resp, 201)
        assert_nurse(data)
        assert data["status"] == "ONBOARDING", f"status {data['status']} != ONBOARDING"
        assert data["credential_posture"] == "SCHEDULING_SUSPENDED"
        assert data["multistate_privilege_status"] == "NONE"
        assert data["practice_scope"] == [], "practice_scope must start empty"
        assert data["open_encumbrance_count"] == 0
        assert data["updated_at"] == data["created_at"], (
            "updated_at is refreshed on every mutation; at creation both timestamps coincide"
        )

    def test_nurse_missing_required_field_returns_400(self):
        """PRD §2.9: "malformed requests — a missing required field, a type mismatch,
        an unknown field, an invalid enum value, or a missing conditional field such
        as `discrepancy_note`, `rejection_reason`, `resolution_note`, or the
        `license_id` of a `LICENSE`-scope action — are `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/nurse_missing_required_field_returns_400
        """
        set_clock()
        payload = {
            "full_name": "No State",
            "email": "no.state@x.com",
            "employment_type": "STAFF",
            "hire_date": "2026-07-01",
        }
        resp = api_client.create_nurse(payload, SPEC1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _data, meta = validate_paginated(api_client.list_nurses(SPEC1))
        assert meta["total_count"] == 0, "the rejected create must not persist a nurse"


class TestNurseRetrieval:
    def test_nurse_get_not_found_returns_404(self):
        """PRD §2.9: "4. **Path existence** — path resource ids must exist, validated
        left to right, else `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/nurse_get_not_found_returns_404
        """
        set_clock()
        resp = api_client.get_nurse(NON_EXISTENT_UUID, SPEC1)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_nurse_create_with_computed_field_rejected(self):
        """PRD §2.8: "Four nurse fields are computed, never written directly:
        `credential_posture`, the gating axis of `CLEAR`, `SCHEDULING_SUSPENDED`, or
        `PRACTICE_RESTRICTED`; ..."
        PRD §2.9: "malformed requests — a missing required field, a type mismatch, an
        unknown field, an invalid enum value, ... — are `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/nurse_create_with_computed_field_rejected
        """
        set_clock()
        payload = create_nurse_payload(
            full_name="Cheat Clear", email="cheat.clear@x.com"
        )
        payload["credential_posture"] = "CLEAR"
        resp = api_client.create_nurse(payload, SPEC1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _data, meta = validate_paginated(api_client.list_nurses(SPEC1))
        assert meta["total_count"] == 0, "the rejected create must not persist a nurse"


class TestNurseListing:
    def test_nurse_list_pagination_defaults(self):
        """PRD §2.3: "All list endpoints accept the `limit` and `offset` query
        parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100;
        `offset` defaults to 0. List responses carry the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` inside `meta`."

        Design: Corner/entities/nurse_list_pagination_defaults
        """
        set_clock()
        for i in range(1, 13):
            create_nurse(full_name=f"Page N{i:02d}", email=f"page{i:02d}@x.com")

        data, meta = validate_paginated(api_client.list_nurses(SPEC1))
        assert len(data) == 10, f"default page must hold 10 rows, got {len(data)}"
        assert meta["limit"] == 10 and meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True

        data2, meta2 = validate_paginated(api_client.list_nurses(SPEC1, params={"offset": 10}))
        assert len(data2) == 2, f"offset=10 page must hold 2 rows, got {len(data2)}"
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False

    def test_state_license_filtered_list_by_nurse_fk(self):
        """PRD §4: "GET /credentialing/state-licenses | List licenses, reverse-lookup
        by nurse".
        PRD §3.2: "A license is born `DRAFT`, and its creator is recorded in
        `created_by_user_id` for later segregation checks."

        Design: Corner/entities/state_license_filtered_list_by_nurse_fk
        """
        set_clock()
        nurse_a = create_nurse(full_name="Ann Two", email="ann.two@x.com")
        lic_a1 = create_license_draft(nurse_a["id"], state_code="AZ",
                                      license_number="RN-AZ-AT1")
        lic_a2 = create_license_draft(nurse_a["id"], state_code="TX",
                                      license_number="RN-TX-AT2", multistate_flag=False)
        nurse_b = create_nurse(full_name="Ben One", email="ben.one@x.com")
        lic_b1 = create_license_draft(nurse_b["id"], state_code="AZ",
                                      license_number="RN-AZ-BO1")

        data, meta = validate_paginated(
            api_client.list_state_licenses(SPEC1, params={"nurse_id": nurse_a["id"]})
        )
        ids = {row["id"] for row in data}
        assert meta["total_count"] == 2 and len(data) == 2
        assert ids == {lic_a1["id"], lic_a2["id"]}, f"expected nurse A's licenses, got {ids}"
        assert lic_b1["id"] not in ids, "nurse B's license leaked into nurse A's filter"
        for row in data:
            assert row["status"] == "DRAFT"
            assert row["nurse_id"] == nurse_a["id"]


class TestEnvelopeAndUniqueness:
    def test_error_envelope_shape_on_404(self):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard
        envelope format" with `meta` holding `api_request_id` and
        `api_request_timestamp`, `response_type` of \"error\", and `data` carrying
        `error_id` and `message`.
        PRD §2.9: "4. **Path existence** — path resource ids must exist, validated
        left to right, else `ERR_NOT_FOUND` (404)."

        Design: Corner/errors/error_envelope_shape_on_404
        """
        resp = api_client.get_unit(NON_EXISTENT_UUID, SPEC1)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"], "meta.api_request_id must be present"
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["data"]["message"].strip(), "data.message must be non-empty"

    def test_duplicate_email_rejected(self):
        """PRD §3.1: "A `CredentialingSpecialist` opens a nurse record with
        `full_name`, a work `email` (unique across nurses — a duplicate is
        `ERR_DUPLICATE_RESOURCE`), ..."

        Design: Corner/errors/duplicate_email_rejected
        """
        set_clock()
        create_nurse(full_name="Dup One", email="dup@x.com")
        resp = api_client.create_nurse(
            create_nurse_payload(
                full_name="Dup Two",
                email="dup@x.com",
                primary_state_of_residence="TX",
                employment_type="TRAVEL",
                hire_date="2026-07-02",
            ),
            SPEC1,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)
        _data, meta = validate_paginated(api_client.list_nurses(SPEC1))
        assert meta["total_count"] == 1, "the duplicate create must not persist"

    def test_duplicate_license_number_rejected(self):
        """PRD §3.2: "Licenses are registered by a `CredentialingSpecialist` with the
        owning `nurse_id`, the issuing `state_code`, a `license_number` (the
        state-code-plus-license-number pair must be unique, else
        `ERR_DUPLICATE_RESOURCE`), ..."

        Design: Corner/errors/duplicate_license_number_rejected
        """
        set_clock()
        nurse_a = create_nurse(full_name="Lic A", email="lic.a@x.com",
                               primary_state_of_residence="AZ")
        nurse_b = create_nurse(full_name="Lic B", email="lic.b@x.com",
                               primary_state_of_residence="TX")
        create_license_draft(nurse_a["id"], state_code="AZ", license_number="RN-777")

        resp_dup = api_client.create_state_license(
            create_state_license_payload(nurse_b["id"], state_code="AZ",
                                         license_number="RN-777"),
            SPEC1,
        )
        validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE_RESOURCE)

        resp_ok = api_client.create_state_license(
            create_state_license_payload(nurse_b["id"], state_code="TX",
                                         license_number="RN-777", multistate_flag=False),
            SPEC1,
        )
        lic_b = validate_success(resp_ok, 201)
        assert_state_license(lic_b)
        assert lic_b["state_code"] == "TX", (
            "the same license number in a different state is a distinct pair"
        )


class TestBodyForeignKeys:
    def test_body_fk_nurse_not_found_returns_404(self):
        """PRD §2.9: "5. **Body referential integrity** — foreign keys in the payload
        must resolve: `nurse_id` (`ERR_NURSE_NOT_FOUND`), `license_id`
        (`ERR_LICENSE_NOT_FOUND`), `unit_id` or `target_unit_id`
        (`ERR_UNIT_NOT_FOUND`), and `requirement_id` (`ERR_REQUIREMENT_NOT_FOUND`),
        all 404."

        Design: Corner/validations/body_fk_nurse_not_found_returns_404
        """
        resp = api_client.create_state_license(
            create_state_license_payload(NON_EXISTENT_UUID, license_number="RN-AZ-XX1"),
            SPEC1,
        )
        validate_error(resp, ApiErrorId.ERR_NURSE_NOT_FOUND)
        _data, meta = validate_paginated(api_client.list_state_licenses(SPEC1))
        assert meta["total_count"] == 0, "the rejected create must not persist a license"


class TestLicenseRetrieval:
    def test_license_get_returns_persisted_fields(self):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."
        PRD §3.2: "A license is born `DRAFT`, and its creator is recorded in
        `created_by_user_id` for later segregation checks."
        PRD §3.2: "The attester is stamped into `verified_by_user_id`, which stays
        null until attestation."

        Design: Corner/endpoints/license_get_returns_persisted_fields
        """
        set_clock()
        nurse = create_nurse(full_name="Get Fields", email="get.fields@x.com")
        lic = create_license_draft(
            nurse["id"],
            state_code="FL",
            license_number="RN-FL-GF1",
            license_class="APRN",
            multistate_flag=True,
            issued_on="2026-06-15",
            expires_on="2027-06-30",
        )
        resp = api_client.get_state_license(lic["id"], CO1)
        data = validate_success(resp, 200)
        assert_state_license(data)
        assert data["state_code"] == "FL"
        assert data["license_number"] == "RN-FL-GF1"
        assert data["license_class"] == "APRN"
        assert data["multistate_flag"] is True
        assert data["issued_on"] == "2026-06-15"
        assert data["expires_on"] == "2027-06-30"
        assert data["status"] == "DRAFT"
        assert data["created_by_user_id"] == "spec-1"
        assert data["verified_by_user_id"] is None
