"""Access grants, secure-bank read gating, and item variants."""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_access_grant_payload, create_variant_payload
from test_helpers.fixtures import (
    OFFICER,
    TRANSLATOR_H,
    create_draft_item,
    create_grant_strict,
    create_program,
    create_standard,
    drive_item_to_field_test_eligible,
    make_operational_items,
)
from test_helpers.test_users import (
    make_content_reviewer_headers,
    make_item_writer_headers,
    make_program_director_headers,
    make_security_officer_headers,
)


class TestAccessGrantOverlap:
    def test_full_overlap_rejected(self, api):
        """PRD: "A new grant whose validity interval would fully overlap an
        existing active grant for the same grantee and scope is rejected with
        `ERR_GRANT_OVERLAP` (HTTP 409)."
        (The second interval is fully contained in the first grant's closed
        validity interval.)

        Design: Difficulty/resource_temporal_overlap/access_grant_full_overlap_rejection_closed_interval
        """
        program = create_program()
        create_grant_strict(program["id"], "user-u", "ITEM_READ",
                            valid_from="2026-01-01T00:00:00Z",
                            valid_until="2026-12-31T23:59:59Z")
        resp = api.create_access_grant(
            create_access_grant_payload(
                program["id"], "user-u", "ITEM_READ",
                valid_from="2026-06-01T00:00:00Z",
                valid_until="2026-08-31T23:59:59Z"),
            make_security_officer_headers(OFFICER),
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_OVERLAP)

    def test_adjacent_grant_is_not_overlap(self, api):
        """PRD: "A new grant whose validity interval would fully overlap an
        existing active grant for the same grantee and scope is rejected with
        `ERR_GRANT_OVERLAP` (HTTP 409)."
        (A grant starting after the existing grant's valid_until does not
        overlap it and is accepted.)

        Design: Difficulty/resource_temporal_overlap/access_grant_full_overlap_rejection_closed_interval
        """
        program = create_program()
        create_grant_strict(program["id"], "user-u", "ITEM_READ",
                            valid_from="2026-01-01T00:00:00Z",
                            valid_until="2026-12-31T23:59:59Z")
        grant = validate_success(api.create_access_grant(
            create_access_grant_payload(
                program["id"], "user-u", "ITEM_READ",
                valid_from="2027-01-01T00:00:00Z",
                valid_until="2027-12-31T23:59:59Z"),
            make_security_officer_headers(OFFICER),
        ), 201)
        assert grant["grant_scope"] == "ITEM_READ"
        assert grant.get("revoked_at") is None


class TestSecuredItemReadGate:
    def _secured_item(self, api):
        """Drive an item to FIELD_TEST_ELIGIBLE, where it is SECURED."""
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-SEC")
        item = drive_item_to_field_test_eligible(program["id"], item)
        assert item["security_posture"] == "SECURED"
        return program, item

    def test_error_no_active_grant_on_secured_item_read(self, api):
        """PRD: "Reading an individual item whose `security_posture` is
        `SECURED` requires an active `ITEM_READ` grant"
        PRD: "An operation that requires a scope the caller does not actively
        hold is rejected with `ERR_NO_ACTIVE_GRANT` (HTTP 403)."

        Design: Corner/errors/error_no_active_grant_on_secured_item_read
        """
        program, item = self._secured_item(api)
        # This caller holds no grant for the program.
        outsider = make_program_director_headers("director-no-grant")
        resp = api.get_item(item["id"], outsider)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_GRANT)

    def test_secured_item_excluded_from_listing_without_grant(self, api):
        """PRD: "item list responses silently exclude `SECURED` items from
        callers who lack `ITEM_READ`."

        Design: Corner/errors/error_no_active_grant_on_secured_item_read
        """
        program, item = self._secured_item(api)
        outsider = make_program_director_headers("director-no-grant")
        data, meta = validate_paginated(
            api.list_items(outsider, params={"program_id": program["id"]}))
        assert all(row["id"] != item["id"] for row in data), (
            "SECURED item hidden from a caller lacking ITEM_READ"
        )


class TestVariants:
    def test_validation_variant_kind_mismatch_returns_422(self, api):
        """PRD: "Supplying the wrong field for the kind — or both fields at
        once — is rejected with `ERR_VARIANT_KIND_MISMATCH` (HTTP 422)."
        (A TRANSLATION variant without its language_code.)

        Design: Corner/validations/validation_variant_kind_mismatch_returns_422
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-V")
        payload = create_variant_payload(item["id"], "TRANSLATION")
        del payload["language_code"]
        resp = api.create_item_variant(payload, TRANSLATOR_H)
        validate_error(resp, ApiErrorId.ERR_VARIANT_KIND_MISMATCH)

    def test_variant_approval_gated_by_item_state(self, api):
        """PRD: "Approval requires the variant to be in `DRAFT`
        (`ERR_VARIANT_NOT_DRAFT` otherwise) and requires its source item to be
        in `OPERATIONAL`, `FIELD_TESTING`, or `STATS_REVIEW`
        (`ERR_VARIANT_SOURCE_NOT_READY`, HTTP 409), moving the variant to
        `APPROVED`."
        (The source item here is still DRAFT.)

        Design: Difficulty/cross_entity_state_dependency/variant_approval_gated_by_item_state
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-VG")
        variant = validate_success(api.create_item_variant(
            create_variant_payload(item["id"], "TRANSLATION", language_code="es"),
            TRANSLATOR_H,
        ), 201)
        resp = api.approve_item_variant(
            variant["id"], make_content_reviewer_headers("cr-v"))
        validate_error(resp, ApiErrorId.ERR_VARIANT_SOURCE_NOT_READY)
        after = validate_success(api.get_item_variant(variant["id"], TRANSLATOR_H))
        assert after["status"] == "DRAFT", "the rejected approval changes nothing"

    def test_variant_approval_succeeds_for_operational_source(self, api):
        """PRD: "Approval requires the variant to be in `DRAFT`
        (`ERR_VARIANT_NOT_DRAFT` otherwise) and requires its source item to be
        in `OPERATIONAL`, `FIELD_TESTING`, or `STATS_REVIEW`
        (`ERR_VARIANT_SOURCE_NOT_READY`, HTTP 409), moving the variant to
        `APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/variant_approval_gated_by_item_state
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = make_operational_items(program["id"], standard["id"], [30])[0]
        assert item["status"] == "OPERATIONAL"
        variant = validate_success(api.create_item_variant(
            create_variant_payload(item["id"], "ACCOMMODATION",
                                   accommodation_code="LARGE_PRINT"),
            make_item_writer_headers("writer-1"),
        ), 201)
        approved = validate_success(api.approve_item_variant(
            variant["id"], make_content_reviewer_headers("cr-v2")))
        assert approved["status"] == "APPROVED"
