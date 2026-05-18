"""Application CRUD and claim-shape enforcement.

Covers PRD §3.2 (drafting and updates) and the claim-shape rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_application,
    create_applicant,
    create_application_payload,
    create_draft_application,
    make_applicant_headers,
    patch_application_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Draft creation (PRD §3.2)
# ===========================================================================
class TestDraftCreate:

    def test_create_utility_draft_succeeds(self, api):
        """PRD §3.2: "A new draft's status defaults to DRAFT".
        """
        a = create_applicant(entity_size="SMALL")
        payload = create_application_payload(
            applicant_id=a["id"], application_type="UTILITY",
            claim_count=1, independent_claim_count=1,
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        data = validate_success(res, 201)
        assert_application(data)
        assert data["status"] == "DRAFT"
        assert data["application_type"] == "UTILITY"
        assert data["total_fees_paid_cents"] == 0
        assert data["filed_at"] is None or "filed_at" not in data \
            or data.get("filed_at") is None

    def test_create_provisional_with_zero_claims_succeeds(self, api):
        """PRD §3.2: "for a PROVISIONAL filing, both claim_count and
        independent_claim_count must be exactly 0."
        """
        a = create_applicant(entity_size="SMALL")
        payload = create_application_payload(
            applicant_id=a["id"], application_type="PROVISIONAL",
            claim_count=0, independent_claim_count=0,
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        data = validate_success(res, 201)
        assert data["application_type"] == "PROVISIONAL"
        assert data["claim_count"] == 0
        assert data["independent_claim_count"] == 0


# ===========================================================================
# Claim-shape validation (PRD §3.2)
# ===========================================================================
class TestClaimShape:

    @pytest.mark.parametrize("app_type", ["UTILITY", "DESIGN"])
    def test_zero_claims_on_utility_or_design_rejected(self, api, app_type):
        """PRD §3.2: "For a UTILITY or DESIGN filing, claim_count must
        be at least 1 and independent_claim_count must be at least 1
        and no greater than claim_count ... Any violation of these
        constraints is reported as ERR_CLAIM_SHAPE_INVALID."
        """
        a = create_applicant(entity_size="SMALL")
        payload = create_application_payload(
            applicant_id=a["id"], application_type=app_type,
            claim_count=0, independent_claim_count=0,
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_CLAIM_SHAPE_INVALID.value)

    def test_independent_exceeding_total_rejected(self, api):
        """PRD §3.2: "independent_claim_count must be at least 1 and no
        greater than claim_count ... Any violation of these constraints
        is reported as ERR_CLAIM_SHAPE_INVALID."

        Claim: independent_claim_count > claim_count fails.
        """
        a = create_applicant(entity_size="SMALL")
        payload = create_application_payload(
            applicant_id=a["id"], application_type="UTILITY",
            claim_count=2, independent_claim_count=3,
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_CLAIM_SHAPE_INVALID.value)

    def test_provisional_with_nonzero_claim_count_rejected(self, api):
        """PRD §3.2: "for a PROVISIONAL filing, both claim_count and
        independent_claim_count must be exactly 0."
        """
        a = create_applicant(entity_size="SMALL")
        payload = create_application_payload(
            applicant_id=a["id"], application_type="PROVISIONAL",
            claim_count=1, independent_claim_count=0,
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_CLAIM_SHAPE_INVALID.value)

    def test_provisional_with_nonzero_independent_count_rejected(self, api):
        """PRD §3.2: "for a PROVISIONAL filing, both claim_count and
        independent_claim_count must be exactly 0."
        """
        a = create_applicant(entity_size="SMALL")
        payload = create_application_payload(
            applicant_id=a["id"], application_type="PROVISIONAL",
            claim_count=0, independent_claim_count=1,
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_CLAIM_SHAPE_INVALID.value)


# ===========================================================================
# Draft PATCH (PRD §3.2)
# ===========================================================================
class TestDraftPatch:

    def test_patch_draft_title_succeeds(self, api):
        """PRD §3.2: "A draft's mutable fields — title, claim_count,
        and independent_claim_count — can be edited while the
        application remains in DRAFT".
        """
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(a)
        res = api.patch_application(
            app["id"], patch_application_payload(title="Better title"),
            make_applicant_headers(a["id"]),
        )
        data = validate_success(res, 200)
        assert data["title"] == "Better title"
        assert data["version"] > app["version"]

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.5: stale version in body yields ERR_VERSION_CONFLICT."""
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(a)
        v0 = app["version"]
        first = api.patch_application(
            app["id"], patch_application_payload(title="t1", version=v0),
            make_applicant_headers(a["id"]),
        )
        validate_success(first, 200)
        res = api.patch_application(
            app["id"], patch_application_payload(title="t2", version=v0),
            make_applicant_headers(a["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_after_file_rejected_as_invalid_state(self, api):
        """PRD §3.2: "any update attempt after the application has left
        DRAFT is rejected as an invalid state."

        Claim: after FILED, PATCH /applications/{id} returns
        ERR_INVALID_STATE.
        """
        from test_helpers import setup_filed_application
        a, app = setup_filed_application()
        res = api.patch_application(
            app["id"], patch_application_payload(title="too late"),
            make_applicant_headers(a["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
