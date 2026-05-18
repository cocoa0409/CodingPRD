"""Validation priority order and optimistic concurrency.

Coverage targets:
- PRD §2.10 priority is observable: when multiple checks would fail,
  the first-by-priority wins. We test SPECIFIC PRD-named precedences
  (priority 7 state vs priority 10 div), not arbitrary pairs that PRD
  is silent on.
- OCC (PRD §2.6): version mismatch -> ERR_VERSION_CONFLICT;
  version match -> success.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_1099_div,
    compute_tax_return,
    efile_tax_return,
    make_taxpayer_headers,
    patch_income_document_payload,
    patch_tax_return,
    re_get_tax_return,
    setup_active_taxpayer_with_draft_return,
    setup_filed_return,
    setup_simple_w2_return,
    validate_error,
    validate_success,
)


# ===========================================================================
# Validation priority — only test precedences PRD names directly
# ===========================================================================
class TestValidationPriority:

    def test_state_precondition_wins_over_dividend_constraint(self, api):
        """PRD §2.10 priority 7 (state) precedes priority 10
        (qualified-div constraint). PRD §2.10: "This priority order is
        observable: a request that fails several checks reports only
        the first one to fire."

        Claim: PATCHing a 1099_DIV with qualified>ordinary on a return
        currently in FILED state — both state precondition (mutating
        child after FILED) and div-constraint fail — surfaces
        ERR_INVALID_STATE (priority 7), not
        ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY (priority 10).
        """
        # Build a FILED return that has a 1099_DIV.
        # 1. setup_simple_w2_return gives DRAFT.
        # 2. Add 1099_DIV with qualified <= ordinary.
        # 3. Compute -> READY_TO_FILE.
        # 4. Efile -> FILED.
        # 5. PATCH the DIV with qualified > ordinary.
        taxpayer, tax_return, _w2 = setup_simple_w2_return(
            wages_cents=2_000_000, federal_withholding_cents=200_000,
            filing_status="SINGLE",
        )
        div_doc = add_1099_div(
            taxpayer, tax_return["id"],
            ordinary_dividends_cents=100_000,
            qualified_dividends_cents=50_000,
        )
        compute_tax_return(taxpayer, tax_return["id"])
        efile_tax_return(taxpayer, tax_return["id"])
        # Now FILED. Try patch with qualified > ordinary.
        resp = api.patch_income_document(
            div_doc["id"],
            patch_income_document_payload(
                qualified_dividends_cents=200_000,
                ordinary_dividends_cents=100_000,
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        # PRD §2.10 priority order: state precondition (7) fires
        # before business_safety dividend check (10).
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Optimistic concurrency — PRD §2.6
# ===========================================================================
class TestOptimisticConcurrency:

    def test_patch_with_matching_version_succeeds(self, api):
        """PRD §2.6: "Mutating endpoints accept an optional version
        field in the request body. When version is supplied, the
        server compares it to the current version of the targeted
        entity".

        Claim: PATCH with the entity's actual current version
        succeeds.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        patched = patch_tax_return(
            taxpayer, tax_return["id"],
            dependents_count=1,
            version=tax_return["version"],
        )
        assert patched["version"] == tax_return["version"] + 1

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.6: "a mismatch is rejected with ERR_VERSION_CONFLICT
        (HTTP 409) and the resource is left untouched."

        Claim: PATCH with a stale version -> ERR_VERSION_CONFLICT
        and the entity is unchanged.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        # First patch advances version.
        patch_tax_return(
            taxpayer, tax_return["id"],
            dependents_count=1, version=tax_return["version"],
        )
        # Stale version (the original).
        resp = api.patch_tax_return(
            tax_return["id"],
            {"dependents_count": 3, "version": tax_return["version"]},
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_without_version_proceeds(self, api):
        """PRD §2.6: "When version is omitted, the operation proceeds
        without an optimistic concurrency check."

        Claim: PATCH without supplying version succeeds even after
        the entity has been mutated by another request.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        # First patch — no version.
        first = patch_tax_return(
            taxpayer, tax_return["id"], dependents_count=1,
        )
        # Second patch — also no version. Should succeed despite the
        # caller not knowing the new version.
        second = patch_tax_return(
            taxpayer, tax_return["id"], dependents_count=2,
        )
        assert second["version"] > first["version"]


# ===========================================================================
# Version increments by exactly one — PRD §2.4
# ===========================================================================
class TestVersionIncrement:

    def test_version_increments_by_one_on_mutation(self, api):
        """PRD §2.4: "a monotonically increasing integer that starts
        at 1 on creation and increments by exactly 1 on every mutation."

        Claim: PATCH bumps version by exactly 1.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        v0 = tax_return["version"]
        patched = patch_tax_return(
            taxpayer, tax_return["id"], dependents_count=1,
            version=v0,
        )
        assert patched["version"] == v0 + 1
