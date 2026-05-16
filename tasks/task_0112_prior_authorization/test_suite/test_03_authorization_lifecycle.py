"""AuthorizationRequest lifecycle: create (DRAFT), PATCH while DRAFT,
submit, withdraw.

PRD §3.2 (creation, draft editing, submission), §2.10 (version
pinning), §3.5 (withdraw cascades).
"""
from __future__ import annotations

from test_helpers import (
    assert_authorization_request,
    create_authorization_request,
    create_authorization_request_payload,
    create_provider,
    make_provider_headers,
    occ_payload,
    patch_authorization_request_payload,
    re_get_authorization,
    retire_service_catalog_item,
    setup_reference_data,
    setup_submitted_authorization,
    setup_under_review_authorization,
    validate_error,
    validate_success,
)


# ===========================================================================
# DRAFT creation
# ===========================================================================
class TestCreateDraft:
    """PRD §3.2: creation."""

    def test_create_starts_in_draft(self, api):
        """PRD §3.2: "On creation, the new authorization is in DRAFT
        status, its evidence_reuse_discount is initialized to 0.00, and
        no SLA timer has yet started."

        Claim: a newly created AuthorizationRequest has status=DRAFT
        and evidence_reuse_discount=0.00.
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        assert auth["status"] == "DRAFT"
        assert auth.get("evidence_reuse_discount") == 0.00
        assert_authorization_request(auth)

    def test_default_urgency_is_standard(self, api):
        """PRD §3.2: "an urgency that is one of STANDARD or EXPEDITED
        (defaults to STANDARD)".

        Claim: omitting urgency yields STANDARD.
        """
        patient, provider, catalog_item = setup_reference_data()
        payload = create_authorization_request_payload(
            patient_id=patient["id"], provider_id=provider["id"],
            service_catalog_item_id=catalog_item["id"],
        )
        payload.pop("urgency", None)
        res = api.create_authorization_request(
            payload, make_provider_headers(provider["id"]),
        )
        auth = validate_success(res, 201)
        assert auth["urgency"] == "STANDARD"

    def test_provider_id_must_match_x_user_id(self, api):
        """PRD §3.2: "the provider_id of the requesting practice (which
        must equal X-User-ID when the caller is a Provider)".

        Claim: a Provider whose X-User-ID does not equal the request's
        provider_id is rejected with ERR_FORBIDDEN.
        """
        patient, provider, catalog_item = setup_reference_data()
        other_provider = create_provider()
        payload = create_authorization_request_payload(
            patient_id=patient["id"],
            provider_id=provider["id"],
            service_catalog_item_id=catalog_item["id"],
        )
        res = api.create_authorization_request(
            payload, make_provider_headers(other_provider["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# DRAFT editing via PATCH
# ===========================================================================
class TestPatchWhileDraft:
    """PRD §3.2: editing in DRAFT."""

    def test_can_patch_clinical_justification_in_draft(self, api):
        """PRD §3.2: "While in DRAFT, the provider may freely revise
        clinical_justification, requested_units, or urgency".

        Claim: PATCH on a DRAFT request updates clinical_justification.
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        res = api.patch_authorization_request(
            auth["id"],
            patch_authorization_request_payload(
                clinical_justification="Revised justification text",
                version=auth["version"],
            ),
            make_provider_headers(provider["id"]),
        )
        updated = validate_success(res, 200)
        assert updated["clinical_justification"] == (
            "Revised justification text"
        )
        assert updated["version"] == auth["version"] + 1

    def test_patch_after_submit_rejected_invalid_state(self, api):
        """PRD §3.2: "Any attempt to revise a request once it has left
        DRAFT is rejected as ERR_INVALID_STATE."

        Claim: PATCH on a SUBMITTED request returns ERR_INVALID_STATE.
        """
        _, provider, _, auth, _ = setup_submitted_authorization()
        res = api.patch_authorization_request(
            auth["id"],
            patch_authorization_request_payload(
                clinical_justification="late change",
                version=auth["version"],
            ),
            make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Submission
# ===========================================================================
class TestSubmission:
    """PRD §3.2: submission preconditions and side effects."""

    def test_submit_transitions_draft_to_submitted(self, api):
        """PRD §3.2: "submitting the request advances
        AuthorizationRequest.status from DRAFT to SUBMITTED."

        Claim: submit a DRAFT with full evidence → status=SUBMITTED.
        """
        _, _, _, auth, _ = setup_submitted_authorization()
        assert auth["status"] == "SUBMITTED"
        assert auth.get("submitted_at") is not None

    def test_submit_pins_service_catalog_item_version(self, api):
        """PRD §3.2: "service_catalog_item_version is pinned to the
        catalog item's current version".
        PRD §2.10: "every AuthorizationRequest captures
        service_catalog_item_version at the moment it transitions from
        DRAFT to SUBMITTED".

        Claim: submitted authorization carries
        service_catalog_item_version equal to the catalog's version at
        submission.
        """
        _, _, catalog_item, auth, _ = setup_submitted_authorization()
        assert auth.get("service_catalog_item_version") == (
            catalog_item["version"]
        )

    def test_submit_denormalizes_service_code(self, api):
        """PRD §3.2: "service_code is denormalized to the catalog item's
        current code".

        Claim: service_code on the submitted authorization equals the
        catalog item's code.
        """
        _, _, catalog_item, auth, _ = setup_submitted_authorization()
        assert auth.get("service_code") == catalog_item["code"]

    def test_submit_retired_catalog_rejected(self, api):
        """PRD §3.2: "the catalog item must be ACTIVE (else
        ERR_CATALOG_RETIRED)".

        Claim: submit on a retired catalog returns ERR_CATALOG_RETIRED.

        difficulty: cross_entity_state_dependency/authorization_request_submit_depends_on_service_catalog_item_status
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        retire_service_catalog_item(catalog_item)
        res = api.submit_authorization_request(
            auth["id"], occ_payload(version=auth["version"]),
            make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_CATALOG_RETIRED")

    # NOTE: ERR_PATIENT_INACTIVE (PRD §3.2) and ERR_PROVIDER_SUSPENDED
    # (PRD §3.2) are state-checked at submission. PRD §3.1 names
    # INACTIVE/SUSPENDED as status values but does not name a public
    # operation that transitions Patient.ACTIVE → Patient.INACTIVE or
    # Provider.ACTIVE → Provider.SUSPENDED. Therefore the precondition
    # cannot be reached through PRD-named operations alone, and any
    # test that flips the status via an unspecified admin path would
    # rely on out-of-PRD behaviour. Silence-pattern: enum-write-pathway.

    def test_submit_expedited_without_enough_justification_rejected(
        self, api,
    ):
        """PRD §3.2: "if urgency is EXPEDITED — the clinical_
        justification must contain at least 50 non-whitespace characters
        (else ERR_EXPEDITED_JUSTIFICATION_REQUIRED). The same
        50-character requirement does not apply to STANDARD requests."

        Claim: an EXPEDITED authorization with a 10-char
        clinical_justification is rejected with
        ERR_EXPEDITED_JUSTIFICATION_REQUIRED.
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
            urgency="EXPEDITED",
            clinical_justification="too short",  # 9 chars, no whitespace
        )
        from test_helpers import attach_categories, TEST_DEFAULTS
        attach_categories(
            provider=provider, authorization=auth,
            categories=list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"]),
        )
        res = api.submit_authorization_request(
            auth["id"], occ_payload(version=auth["version"]),
            make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_EXPEDITED_JUSTIFICATION_REQUIRED")

    def test_submit_standard_skips_justification_length_rule(self, api):
        """PRD §3.2: "The same 50-character requirement does not apply
        to STANDARD requests."

        Claim: a STANDARD authorization with a 10-char justification
        submits successfully.
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
            urgency="STANDARD", clinical_justification="short okay",
        )
        from test_helpers import attach_categories, TEST_DEFAULTS
        from test_helpers import re_get_authorization
        attach_categories(
            provider=provider, authorization=auth,
            categories=list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"]),
        )
        # Re-fetch so OCC version reflects any parent recompute bumps.
        auth = re_get_authorization(auth["id"])
        res = api.submit_authorization_request(
            auth["id"], occ_payload(version=auth["version"]),
            make_provider_headers(provider["id"]),
        )
        submitted = validate_success(res, 200)
        assert submitted["status"] == "SUBMITTED"


# ===========================================================================
# Withdrawal
# ===========================================================================
class TestWithdraw:
    """PRD §3.2: withdrawal."""

    def test_withdraw_from_draft(self, api):
        """PRD §3.2: "The same provider may also withdraw the request
        entirely from DRAFT, in which case the authorization
        transitions directly to WITHDRAWN."

        Claim: withdraw from DRAFT → status=WITHDRAWN.
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        res = api.withdraw_authorization_request(
            auth["id"], occ_payload(version=auth["version"]),
            make_provider_headers(provider["id"]),
        )
        wd = validate_success(res, 200)
        assert wd["status"] == "WITHDRAWN"

    def test_withdraw_from_pending_info(self, api):
        """PRD §3.4: "While the authorization is in PENDING_INFO, the
        provider may also withdraw the request entirely; the
        authorization transitions directly to WITHDRAWN."

        Claim: withdraw from PENDING_INFO → status=WITHDRAWN.
        """
        from test_helpers import request_info
        _, provider, _, auth, _ = setup_under_review_authorization()
        request_info(authorization=auth)
        auth = re_get_authorization(auth["id"])
        res = api.withdraw_authorization_request(
            auth["id"], occ_payload(version=auth["version"]),
            make_provider_headers(provider["id"]),
        )
        wd = validate_success(res, 200)
        assert wd["status"] == "WITHDRAWN"
