"""Tax-form recapture computation — PRD §3.8.

Coverage targets:
- Default basis is chronological.
- Chronological replay: deductible clamped event-by-event.
- forward_looking: deductible = min(YTD, cap+catch_up).
- Two variants differ when non-qualified claims happen between
  contributions.
- Penalty calc round_half_up via 2000 bps.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_tax_form,
    setup_hsa_non_qualified_for_chronological_tax_form,
    validate_success,
)


# ===========================================================================
# Chronological vs forward_looking — PRD §3.8
# ===========================================================================
class TestTaxFormVariants:

    def test_default_basis_is_chronological(self, api, auditor_headers):
        """PRD §3.8: "The response is an object containing
        deductible_cents, recapture_cents, tax_basis_cents, and basis.
        The computation has two variants, selected by the query
        parameter basis, which defaults to chronological."

        Claim: omitting basis returns basis == "chronological".
        """
        holder, acct, py = setup_hsa_non_qualified_for_chronological_tax_form(
            calendar_year=2025,
            contribution_one_cents=200_000,
            non_qual_claim_cents=200_000,
            contribution_two_cents=200_000,
        )
        resp = api.get_tax_form(acct["id"], py["id"], auditor_headers)
        data = validate_success(resp, expected_status=200)
        assert_tax_form(data)
        assert data["basis"] == "chronological"

    def test_chronological_replay_clamps_event_by_event(
        self, api, auditor_headers,
    ):
        """PRD §3.8: "The chronological variant replays the audit
        events for the plan year in (occurred_at, id) order,
        maintaining a running deductible accumulator. On each
        CONTRIBUTION_POSTED event the deductible accumulator is
        increased by the lesser of the event's cents_delta (the
        contribution amount) and the remaining room under
        contribution_cap_cents + catch_up_cap_cents (the cap room not
        yet used by earlier contributions). On each CLAIM_PAID event
        whose linked QualifiedExpense.category is NON_QUALIFIED, a
        penalty cents value is computed as the absolute value of the
        event's cents_delta multiplied by the HSA penalty rate of
        2,000 basis points (i.e., 20.00%) divided by 10,000, rounded
        half-up to a whole cent; the gross recapture for the event is
        the absolute value of cents_delta plus the penalty cents;
        the amount applied is the lesser of the gross and the
        current deductible accumulator; that applied amount is added
        to a running recapture_cents and subtracted from the
        deductible accumulator. After all events are replayed,
        deductible_cents is the final deductible accumulator value,
        recapture_cents is the running recapture total, and
        tax_basis_cents is deductible_cents minus recapture_cents."

        Claim (anchored to difficulty-design instance
        tax_basis_chronological_vs_forward_looking_hsa, grounded in
        PRD §3.8 verbatim): for the chronological replay over the
        sequence (contribute $2,000, pay non-qualified $2,000,
        contribute $2,000) under HSA SELF_ONLY cap $4,125 the
        per-step computation yields:
          - after first contribution: deductible 200_000
          - non-qualified claim: gross = 200_000 + round_half_up
            (200_000 * 2000 / 10000) = 200_000 + 40_000 = 240_000.
            applied = min(240_000, 200_000) = 200_000. recapture =
            200_000, deductible = 0.
          - second contribution: deductible += min(200_000,
            412_500 - 200_000) = min(200_000, 212_500) = 200_000.
        Final: deductible_cents == 200_000, recapture_cents ==
        200_000, tax_basis_cents == 0.
        """
        holder, acct, py = setup_hsa_non_qualified_for_chronological_tax_form(
            calendar_year=2025,
            contribution_one_cents=200_000,
            non_qual_claim_cents=200_000,
            contribution_two_cents=200_000,
        )
        resp = api.get_tax_form(
            acct["id"], py["id"], auditor_headers,
            params={"basis": "chronological"},
        )
        data = validate_success(resp, expected_status=200)
        assert data["deductible_cents"] == 200_000, (
            f"chronological deductible_cents expected 200_000, "
            f"got {data['deductible_cents']}"
        )
        assert data["recapture_cents"] == 200_000, (
            f"chronological recapture_cents expected 200_000, "
            f"got {data['recapture_cents']}"
        )
        assert data["tax_basis_cents"] == 0, (
            f"chronological tax_basis_cents expected 0, "
            f"got {data['tax_basis_cents']}"
        )

    def test_forward_looking_uses_final_cap(self, api, auditor_headers):
        """PRD §3.8: "The forward_looking variant ignores event
        ordering. deductible_cents is the minimum of
        contributions_ytd_cents and contribution_cap_cents +
        catch_up_cap_cents. recapture_cents is the sum, over every
        PAID claim whose linked QualifiedExpense.category is
        NON_QUALIFIED, of the claim's paid_amount_cents multiplied by
        1 plus the HSA penalty rate (i.e., paid_amount_cents * 1.20,
        rounded half-up to a whole cent). tax_basis_cents is
        deductible_cents minus recapture_cents."

        Claim: contributions_ytd_cents is cumulative POSTED
        contributions = 400_000; claims_paid_ytd does NOT subtract
        from contributions_ytd_cents (PRD §3.3). The HSA cap is
        412_500.
          deductible = min(400_000, 412_500) = 400_000.
          recapture = 200_000 * 1.20 = 240_000 (round_half_up).
          tax_basis = 400_000 - 240_000 = 160_000.
        """
        holder, acct, py = setup_hsa_non_qualified_for_chronological_tax_form(
            calendar_year=2025,
            contribution_one_cents=200_000,
            non_qual_claim_cents=200_000,
            contribution_two_cents=200_000,
        )
        resp = api.get_tax_form(
            acct["id"], py["id"], auditor_headers,
            params={"basis": "forward_looking"},
        )
        data = validate_success(resp, expected_status=200)
        assert data["basis"] == "forward_looking"
        assert data["deductible_cents"] == 400_000, (
            f"forward_looking deductible_cents expected 400_000, "
            f"got {data['deductible_cents']}"
        )
        assert data["recapture_cents"] == 240_000, (
            f"forward_looking recapture_cents expected 240_000, "
            f"got {data['recapture_cents']}"
        )
        assert data["tax_basis_cents"] == 160_000, (
            f"forward_looking tax_basis_cents expected 160_000, "
            f"got {data['tax_basis_cents']}"
        )

    def test_two_variants_disagree(self, api, auditor_headers):
        """PRD §3.8: "The two variants can disagree. When contributions
        arrive after non-qualified claims have already been paid, the
        chronological variant clamps each contribution's deductibility
        event-by-event, so later contributions that would have crossed
        the cap mid-year are dropped from the deductible; the
        forward-looking variant simply caps the final year-to-date
        total. Same dollars in, different deductible out — and tests
        must exercise both branches."

        Claim: chronological tax_basis_cents != forward_looking
        tax_basis_cents for the scenario above.
        """
        holder, acct, py = setup_hsa_non_qualified_for_chronological_tax_form(
            calendar_year=2025,
            contribution_one_cents=200_000,
            non_qual_claim_cents=200_000,
            contribution_two_cents=200_000,
        )
        resp_chrono = api.get_tax_form(
            acct["id"], py["id"], auditor_headers,
            params={"basis": "chronological"},
        )
        resp_fl = api.get_tax_form(
            acct["id"], py["id"], auditor_headers,
            params={"basis": "forward_looking"},
        )
        chrono = validate_success(resp_chrono, expected_status=200)
        fl = validate_success(resp_fl, expected_status=200)
        assert chrono["tax_basis_cents"] != fl["tax_basis_cents"], (
            f"chronological and forward_looking must disagree; "
            f"chrono={chrono['tax_basis_cents']}, fl={fl['tax_basis_cents']}"
        )
