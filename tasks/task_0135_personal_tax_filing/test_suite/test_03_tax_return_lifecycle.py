"""TaxReturn create / patch / state transitions.

Coverage targets (PRD §3.1, §2.7, §3.5):
- Return born in DRAFT.
- One non-DRAFT return per (taxpayer, tax_year) -> ERR_DUPLICATE_RETURN.
- qualifying_children_under_17 must not exceed dependents_count.
- Out-of-range tax_year rejected ERR_INVALID_INPUT.
- PATCH on READY_TO_FILE reverts to DRAFT and invalidates computed
  fields (PRD §2.7).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_tax_return,
    create_tax_return,
    create_tax_return_payload,
    create_taxpayer,
    make_taxpayer_headers,
    patch_tax_return,
    re_get_tax_return,
    setup_active_taxpayer_with_draft_return,
    setup_ready_to_file_return,
    setup_simple_w2_return,
    validate_error,
    validate_success,
)


# ===========================================================================
# Creation — PRD §3.1
# ===========================================================================
class TestCreateTaxReturn:

    def test_create_return_starts_in_draft(self, api):
        """PRD §3.1: "A return is born in the DRAFT state."

        Claim: POST /tax-returns returns status == DRAFT.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        assert tax_return["status"] == "DRAFT"
        assert_tax_return(tax_return)

    def test_default_deduction_method_is_standard(self, api):
        """PRD §3.1: "The optional deduction_method election is captured
        at open time, defaulting to STANDARD and otherwise set to
        ITEMIZED."

        Claim: omitting deduction_method on POST /tax-returns -> the
        response shows deduction_method == STANDARD.
        """
        taxpayer = create_taxpayer()
        headers = make_taxpayer_headers(taxpayer["id"])
        payload = create_tax_return_payload(taxpayer_id=taxpayer["id"])
        payload.pop("deduction_method", None)
        resp = api.create_tax_return(payload, headers)
        data = validate_success(resp, expected_status=201)
        assert data["deduction_method"] == "STANDARD"

    def test_default_dependents_and_qc_are_zero(self, api):
        """PRD §3.1: "Optionally they may declare a dependents_count
        and the subset that are qualifying_children_under_17; both
        default to zero".

        Claim: omitting both fields -> response has them as 0.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        assert tax_return["dependents_count"] == 0
        assert tax_return["qualifying_children_under_17"] == 0


# ===========================================================================
# Duplicate detection — PRD §3.1 / §2.10 priority 19
# ===========================================================================
class TestDuplicateReturn:

    def test_second_non_draft_return_same_year_rejected(self, api):
        """PRD §3.1: "A second attempt to open a return for a year that
        already has a READY_TO_FILE, FILED, ACCEPTED, AMENDED, or
        SUPERSEDED return for the same taxpayer is rejected with
        ERR_DUPLICATE_RETURN."

        Claim: POST /tax-returns after the prior return reached
        READY_TO_FILE -> ERR_DUPLICATE_RETURN.
        """
        taxpayer, ready_return, _ = setup_ready_to_file_return()
        # Try to open another return for the same year.
        headers = make_taxpayer_headers(taxpayer["id"])
        resp = api.create_tax_return(
            create_tax_return_payload(
                taxpayer_id=taxpayer["id"],
                tax_year=ready_return["tax_year"],
                filing_status="SINGLE",
            ),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RETURN.value)

    def test_second_draft_return_same_year_allowed(self, api):
        """PRD §3.1: "While the original is still DRAFT, however, the
        system tolerates an additional DRAFT for the same year so
        taxpayers can scratch and start over."

        Claim: a second POST /tax-returns succeeds while only DRAFTs
        exist for that (taxpayer, year).
        """
        taxpayer, first_return = setup_active_taxpayer_with_draft_return()
        # Open another return same year, still DRAFT-only — should pass.
        second = create_tax_return(
            taxpayer, tax_year=first_return["tax_year"],
            filing_status="SINGLE",
        )
        assert second["id"] != first_return["id"]


# ===========================================================================
# Invalid inputs — PRD §2.10 priority 13 / 21
# ===========================================================================
class TestInvalidInputs:

    def test_qualifying_children_exceed_dependents(self, api):
        """PRD §3.1: "the qualifying-children count may not exceed the
        dependents count (rejection with
        ERR_QUALIFYING_CHILDREN_EXCEED_DEPENDENTS when violated)".

        Claim: dependents_count=1 with qualifying_children_under_17=2
        -> ERR_QUALIFYING_CHILDREN_EXCEED_DEPENDENTS.
        """
        taxpayer = create_taxpayer()
        headers = make_taxpayer_headers(taxpayer["id"])
        resp = api.create_tax_return(
            create_tax_return_payload(
                taxpayer_id=taxpayer["id"],
                tax_year=2025,
                filing_status="SINGLE",
                dependents_count=1,
                qualifying_children_under_17=2,
            ),
            headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_QUALIFYING_CHILDREN_EXCEED_DEPENDENTS.value,
        )

    @pytest.mark.parametrize("bad_year", [2019, 2026, 1999, 3000])
    def test_tax_year_out_of_range(self, api, bad_year):
        """PRD §2.10 priority 21: "tax_year falls in the inclusive
        interval from 2020 through 2025 ... ERR_INVALID_INPUT".

        Claim: tax_year outside [2020, 2025] -> ERR_INVALID_INPUT.
        """
        taxpayer = create_taxpayer()
        headers = make_taxpayer_headers(taxpayer["id"])
        resp = api.create_tax_return(
            create_tax_return_payload(
                taxpayer_id=taxpayer["id"],
                tax_year=bad_year,
                filing_status="SINGLE",
            ),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_invalid_filing_status(self, api):
        """PRD §2.10 priority 21: "filing_status is one of the five
        valid enum values ... ERR_INVALID_INPUT".

        Claim: invalid filing_status -> ERR_INVALID_INPUT.
        """
        taxpayer = create_taxpayer()
        headers = make_taxpayer_headers(taxpayer["id"])
        resp = api.create_tax_return(
            create_tax_return_payload(
                taxpayer_id=taxpayer["id"],
                tax_year=2025,
                filing_status="MARRIED",  # invalid
            ),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)


# ===========================================================================
# PATCH re-opens READY_TO_FILE — PRD §2.7
# ===========================================================================
class TestPatchReopens:

    def test_patch_on_ready_reverts_to_draft(self, api):
        """PRD §2.7: "Any creation, update, or deletion of an
        IncomeDocument, Schedule, or TaxCredit belonging to a TaxReturn
        currently in READY_TO_FILE reverts the parent return to DRAFT
        and invalidates the computed numbers ... The same applies when
        the return itself is patched while in READY_TO_FILE."

        Claim: PATCH /tax-returns/{id} on a READY_TO_FILE return
        reverts the return to DRAFT and zeroes the computed fields.
        """
        taxpayer, ready_return, _ = setup_ready_to_file_return()
        assert ready_return["status"] == "READY_TO_FILE"
        # Capture pre-patch computed values.
        assert ready_return["agi_cents"] > 0

        patched = patch_tax_return(
            taxpayer, ready_return["id"], dependents_count=1,
            version=ready_return["version"],
        )
        assert patched["status"] == "DRAFT"
        # PRD §2.7 explicitly lists these fields as reset to 0.
        for f in (
            "agi_cents",
            "taxable_income_cents",
            "regular_tax_cents",
            "amt_cents",
            "total_credits_cents",
            "balance_due_or_refund_cents",
        ):
            assert patched[f] == 0, (
                f"PRD §2.7: {f} must be reset to 0; got {patched[f]}"
            )

    def test_patch_preserves_deduction_method(self, api):
        """PRD §2.7: "The deduction_method election remains as the
        taxpayer last set it."

        Claim: PATCH that reverts READY_TO_FILE -> DRAFT does NOT
        clear the previously-elected deduction_method.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            deduction_method="ITEMIZED",
            wages_cents=0, federal_withholding_cents=0,
        )
        from test_helpers import add_schedule_a, compute_tax_return
        add_schedule_a(
            taxpayer, tax_return["id"], itemized_salt_cents=100_000,
        )
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["status"] == "READY_TO_FILE"
        # PATCH the dependents count — this should revert to DRAFT but
        # preserve deduction_method == ITEMIZED.
        patched = patch_tax_return(
            taxpayer, tax_return["id"], dependents_count=1,
            version=computed["version"],
        )
        assert patched["status"] == "DRAFT"
        assert patched["deduction_method"] == "ITEMIZED"


# ===========================================================================
# Listing — PRD §4 GET /tax-returns
# ===========================================================================
class TestListReturns:

    def test_list_by_taxpayer_id(self, api):
        """PRD §4: GET /tax-returns supports filter by taxpayer_id.

        Claim: filtering by taxpayer_id returns only that taxpayer's
        returns.
        """
        taxpayer_a, return_a = setup_active_taxpayer_with_draft_return()
        taxpayer_b, return_b = setup_active_taxpayer_with_draft_return()
        # IRSAdjudicator can see any; filter by taxpayer_id.
        from test_helpers import TEST_USERS, validate_paginated
        resp = api.list_tax_returns(
            TEST_USERS["irs_adjudicator_headers"],
            params={"taxpayer_id": taxpayer_a["id"]},
        )
        data, _ = validate_paginated(resp)
        ids = {row["id"] for row in data}
        assert return_a["id"] in ids
        assert return_b["id"] not in ids
