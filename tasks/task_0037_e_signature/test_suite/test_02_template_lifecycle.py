"""Template authorship and TemplateVersion lifecycle.

Covers PRD §3.1 (template creation, version upload, publish, deprecate)
and the OCC checks tied to those mutations.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_template,
    assert_template_version,
    create_published_template,
    create_template,
    create_template_payload,
    create_template_version,
    create_template_version_payload,
    is_lower_hex_64,
    make_template_admin_headers,
    patch_template_version_payload,
    publish_template_version,
    signature_position,
    stable_user_id,
    unique_blob_sha256,
    unique_template_name,
    validate_error,
    validate_success,
    variable_field,
)


class TestTemplateCreate:

    def test_template_minted_with_initial_state(self, api):
        """PRD §3.1: 'The newly minted Template starts with status =
        ACTIVE (the alternative is ARCHIVED), a latest_version_number of 0,
        and a null published_version_number.'

        Claim: a freshly created Template has status=ACTIVE,
        latest_version_number=0, published_version_number=null.
        """
        admin_id = stable_user_id("admin")
        res = api.create_template(
            create_template_payload(category="HR"),
            make_template_admin_headers(admin_id),
        )
        data = validate_success(res, expected_status=201)
        assert_template(data)
        assert data["status"] == "ACTIVE"
        assert data["latest_version_number"] == 0
        assert data["published_version_number"] is None

    def test_default_permission_scope_is_org_only(self, api):
        """PRD §3.1: 'an optional permission_scope defaulting to ORG_ONLY'.

        Claim: a Template created without permission_scope has
        permission_scope == 'ORG_ONLY'.
        """
        admin_id = stable_user_id("admin")
        res = api.create_template(
            create_template_payload(),  # no permission_scope
            make_template_admin_headers(admin_id),
        )
        data = validate_success(res, expected_status=201)
        assert data["permission_scope"] == "ORG_ONLY"


class TestTemplateVersionCreate:

    def test_first_version_starts_at_one_in_draft(self, api):
        """PRD §3.1: 'Each new version receives a version_number that
        monotonically increases per Template starting at 1, and the parent
        Template's latest_version_number is updated to match. The new
        version starts as DRAFT.'

        Claim: first TemplateVersion has version_number=1, status=DRAFT,
        and the parent's latest_version_number becomes 1.
        """
        template, admin_id, _ = create_template()
        res = api.create_template_version(
            template["id"],
            create_template_version_payload(),
            make_template_admin_headers(admin_id),
        )
        data = validate_success(res, expected_status=201)
        assert_template_version(data)
        assert data["version_number"] == 1
        assert data["status"] == "DRAFT"

        # Read the parent and check latest_version_number was updated.
        get_res = api.get_template(
            template["id"], make_template_admin_headers(admin_id)
        )
        parent = validate_success(get_res)
        assert parent["latest_version_number"] == 1

    def test_second_version_increments_to_two(self, api):
        """PRD §3.1: 'monotonically increases per Template starting at 1'.

        Claim: appending a second version on the same template yields
        version_number=2.
        """
        template, admin_id, _ = create_template()
        v1 = create_template_version(
            template_id=template["id"], admin_id=admin_id,
        )
        res = api.create_template_version(
            template["id"],
            create_template_version_payload(),
            make_template_admin_headers(admin_id),
        )
        v2 = validate_success(res, expected_status=201)
        assert v2["version_number"] == 2

    def test_invalid_blob_hash_rejected(self, api):
        """PRD §3.1: 'document_blob_sha256 (exactly 64 lowercase hex
        characters)'.

        Claim: a non-hex / wrong-length document_blob_sha256 is rejected
        with ERR_VALIDATION_FAILED.
        """
        template, admin_id, _ = create_template()
        res = api.create_template_version(
            template["id"],
            create_template_version_payload(
                document_blob_sha256="not-a-valid-hash",
            ),
            make_template_admin_headers(admin_id),
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION_FAILED.value)

    def test_page_count_below_one_rejected(self, api):
        """PRD §3.1: 'the page_count (which must be at least 1)'.

        Claim: page_count=0 is rejected with ERR_VALIDATION_FAILED.
        """
        template, admin_id, _ = create_template()
        res = api.create_template_version(
            template["id"],
            create_template_version_payload(page_count=0),
            make_template_admin_headers(admin_id),
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION_FAILED.value)


class TestTemplateVersionPatchAndOcc:

    def test_patch_draft_with_correct_version_succeeds(self, api):
        """PRD §3.1: 'While in DRAFT it can be edited freely (under OCC)
        to revise document_blob_sha256, page_count, variable_fields, or
        signature_positions -- the version field guards these PATCH calls
        and a stale version is rejected with ERR_VERSION_CONFLICT.'

        Claim: PATCH with the current version_field succeeds and bumps
        the resource's version.
        """
        template, admin_id, _ = create_template()
        version = create_template_version(
            template_id=template["id"], admin_id=admin_id,
        )
        res = api.patch_template_version(
            template["id"], version["id"],
            patch_template_version_payload(
                version=version["version"], page_count=2,
            ),
            make_template_admin_headers(admin_id),
        )
        data = validate_success(res)
        assert data["page_count"] == 2
        assert data["version"] == version["version"] + 1

    def test_patch_with_stale_version_returns_conflict(self, api):
        """PRD §2.4: 'If the supplied version does not match the stored
        value, the server rejects the call with ERR_VERSION_CONFLICT and
        HTTP 409.'

        Claim: PATCH with a stale version yields ERR_VERSION_CONFLICT.
        """
        template, admin_id, _ = create_template()
        version = create_template_version(
            template_id=template["id"], admin_id=admin_id,
        )
        # First PATCH bumps the version.
        api.patch_template_version(
            template["id"], version["id"],
            patch_template_version_payload(
                version=version["version"], page_count=2,
            ),
            make_template_admin_headers(admin_id),
        )
        # Re-PATCH with the OLD version -> conflict.
        res = api.patch_template_version(
            template["id"], version["id"],
            patch_template_version_payload(
                version=version["version"], page_count=3,
            ),
            make_template_admin_headers(admin_id),
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)


class TestPublishAndDeprecate:

    def test_publish_draft_advances_to_published(self, api):
        """PRD §3.1: 'Publishing a TemplateVersion advances it from DRAFT
        to PUBLISHED... On success, the parent Template's
        published_version_number is set to the version's version_number'.

        Claim: publish a DRAFT version -> status PUBLISHED, parent's
        published_version_number == this version_number.
        """
        template, admin_id, _ = create_template()
        version = create_template_version(
            template_id=template["id"], admin_id=admin_id,
        )
        published = publish_template_version(
            template_id=template["id"], version_id=version["id"],
            admin_id=admin_id,
        )
        assert published["status"] == "PUBLISHED"

        get_res = api.get_template(
            template["id"], make_template_admin_headers(admin_id),
        )
        parent = validate_success(get_res)
        assert parent["published_version_number"] == published[
            "version_number"
        ]

    def test_publish_requires_at_least_one_signature_position(self, api):
        """PRD §3.1: 'requires that the version currently be DRAFT and that
        at least one signature position have been pinned.'

        Claim: publish without signature_positions -> ERR_INVALID_STATE.
        """
        template, admin_id, _ = create_template()
        # Create a version with an empty signature_positions list.
        v = create_template_version(
            template_id=template["id"], admin_id=admin_id,
            signature_positions=[],
        )
        res = api.publish_template_version(
            template["id"], v["id"],
            make_template_admin_headers(admin_id),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_publish_non_draft_version_rejected(self, api):
        """PRD §3.1: 'requires that the version currently be DRAFT'.

        Claim: publish on an already-PUBLISHED version -> ERR_INVALID_STATE.
        """
        bundle = create_published_template()
        res = api.publish_template_version(
            bundle["template"]["id"], bundle["version"]["id"],
            make_template_admin_headers(bundle["admin_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_deprecate_with_active_contract_rejected(self, api):
        """PRD §3.1: 'A PUBLISHED version may later be advanced to
        DEPRECATED, but only if no Contract that references it is currently
        in DRAFT, PENDING_SIGN, or PARTIALLY_SIGNED.'

        Claim: with a DRAFT contract referencing the version, deprecate
        is rejected with ERR_INVALID_STATE.
        """
        from test_helpers import setup_single_party_contract
        ctx = setup_single_party_contract()  # contract is in DRAFT
        res = api.deprecate_template_version(
            ctx["template"]["id"], ctx["version"]["id"],
            make_template_admin_headers(ctx["admin_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_deprecate_clears_published_version_number_when_match(self, api):
        """PRD §3.1: 'if the Template's published_version_number equalled
        the deprecated version's version_number, the parent's
        published_version_number is cleared back to null.'

        Claim: with no referencing contracts, deprecate the
        currently-published version -> parent's published_version_number
        becomes null.
        """
        bundle = create_published_template()
        res = api.deprecate_template_version(
            bundle["template"]["id"], bundle["version"]["id"],
            make_template_admin_headers(bundle["admin_id"]),
        )
        deprecated = validate_success(res)
        assert deprecated["status"] == "DEPRECATED"
        get_res = api.get_template(
            bundle["template"]["id"],
            make_template_admin_headers(bundle["admin_id"]),
        )
        parent = validate_success(get_res)
        assert parent["published_version_number"] is None
