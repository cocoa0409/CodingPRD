"""Optimistic concurrency control and validation priority ordering
(PRD §2.9, §2.10).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_days_iso,
    advance_clock_to,
    create_assessment,
    create_owner,
    create_property,
    file_appeal_payload,
    get_assessment,
    issue_assessment,
    make_owner_headers,
    setup_issued_assessment,
    setup_owner_and_property,
    validate_error,
    validate_success,
    version_body,
)


# ===========================================================================
# OCC version mismatch — PRD §2.10
# ===========================================================================
class TestOptimisticConcurrency:

    def test_stale_version_on_issue_rejected(self, api):
        """PRD §2.10: 'When version is supplied, the server compares
        it against the target resource's current version; a mismatch
        fails the request with ERR_VERSION_MISMATCH.'

        Claim: passing a stale version on /assessments/{id}/issue is
        rejected with ERR_VERSION_MISMATCH.
        """
        owner, prop = setup_owner_and_property()
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        # Use a deliberately wrong version (current is 1; pass 99).
        from test_helpers import api_client, TEST_USERS
        resp = api_client.issue_assessment(
            prop["id"], draft["id"], TEST_USERS["assessor_headers"],
            version_body(99),
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_MISMATCH.value)

    def test_omitted_version_skips_occ_check(self, api):
        """PRD §2.10: 'When version is omitted from the request body,
        the OCC check is skipped and the request proceeds against
        whatever version is current.'

        Claim: omitting the version body field on a mutation succeeds
        regardless of the current version.
        """
        owner, prop = setup_owner_and_property()
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        from test_helpers import api_client, TEST_USERS
        # Pass no version → OCC skipped.
        resp = api_client.issue_assessment(
            prop["id"], draft["id"], TEST_USERS["assessor_headers"],
            {},
        )
        data = validate_success(resp)
        assert data["status"] == "ISSUED"

    def test_mutation_increments_version_by_exactly_one(self, api):
        """PRD §2.10: 'Successful mutations always increment version
        by exactly 1 and refresh updated_at, regardless of whether
        the client supplied a version.'

        Claim: after a successful issue, version is exactly prev+1.
        """
        owner, prop = setup_owner_and_property()
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        prev_v = draft["version"]
        issued = issue_assessment(
            property_id=prop["id"], assessment_id=draft["id"],
        )
        assert issued["version"] == prev_v + 1, (
            f"version must increment by exactly 1; prev={prev_v}, "
            f"after issue={issued['version']}"
        )


# ===========================================================================
# Validation priority — PRD §2.9
# ===========================================================================
class TestValidationPriority:

    def test_state_check_fires_before_window_temporal_check(self, api):
        """PRD §2.9: 'the target resource's state-machine eligibility
        (ERR_INVALID_STATE), then cross-entity preconditions ... then
        temporal gates such as the appeal window or hearing-interval
        validity'.

        Claim: when an Assessment is already FINALIZED AND the
        appeal window is closed, filing an Appeal surfaces
        ERR_INVALID_STATE (state check, priority 5) before the
        temporal check (priority 7 ERR_APPEAL_WINDOW_CLOSED).

        # difficulty: priority_pair_validation_conflict/state_vs_business_temporal_pair
        """
        owner, prop, asmt = setup_issued_assessment()
        # Advance clock well past appeal_window_closes_at; no Appeal
        # filed → Assessment auto-FINALIZEs.
        advance_clock_to(add_days_iso(asmt["appeal_window_closes_at"], 15))
        # Confirm Assessment is FINALIZED.
        re_asmt = get_assessment(prop["id"], asmt["id"])
        assert re_asmt["status"] == "FINALIZED"
        # Try to file Appeal — both state (FINALIZED, priority 5) and
        # temporal (window closed, priority 7) would reject. Priority
        # 5 wins per PRD §2.9.
        from test_helpers import api_client
        resp = api_client.file_appeal(
            prop["id"],
            file_appeal_payload(
                assessment_id=asmt["id"], claimed_value=100_000.00,
            ),
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_ownership_check_fires_before_state_check(self, api):
        """PRD §2.9: 'then ownership of the target property for
        owner-scoped writes (ERR_OWNERSHIP_MISMATCH), then the target
        resource's state-machine eligibility (ERR_INVALID_STATE)'.

        Claim: a DIFFERENT owner attempting to file an Appeal on a
        DRAFT Assessment is rejected with ERR_OWNERSHIP_MISMATCH
        (priority 4) before ERR_INVALID_STATE (priority 5).
        """
        owner, prop = setup_owner_and_property()
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        # DRAFT Assessment → ERR_INVALID_STATE would fire if owner
        # matched. Use a different owner → ownership check fires
        # first.
        other_owner = create_owner()
        from test_helpers import api_client
        resp = api_client.file_appeal(
            prop["id"],
            file_appeal_payload(
                assessment_id=draft["id"], claimed_value=100_000.00,
            ),
            make_owner_headers(other_owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH.value)
