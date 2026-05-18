"""TaxYear amendment cycle and K-1 supersession — PRD §3.5, §3.7."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    amend_tax_year,
    assert_k1,
    assert_tax_year,
    begin_close_tax_year,
    finalize_tax_year,
    iso_instant_utc,
    list_k1s_for_year,
    setup_closed_tax_year,
    setup_tax_year_in_amend_state,
    validate_error,
    validate_success,
)


# ===========================================================================
# CLOSED -> AMENDED -> CLOSED cycle — PRD §3.5
# ===========================================================================
class TestAmendCycle:

    def test_amend_transitions_closed_to_amended(self, api):
        """PRD §3.5: "On success the TaxYear transitions CLOSED →
        AMENDED; every K-1 in ISSUED status for this tax_year_id
        transitions to SUPERSEDED; and a fresh set of DRAFT K-1
        records is created, one per ACTIVE-at-year-end Beneficiary."

        Claim: amend on a CLOSED TaxYear moves status to AMENDED.
        """
        scenario = setup_closed_tax_year(income_amount=5_000.00)
        assert scenario.tax_year["status"] == "CLOSED"
        scenario.tax_year = amend_tax_year(
            scenario.trust, scenario.tax_year,
        )
        assert scenario.tax_year["status"] == "AMENDED"

    def test_refinalize_after_amend_returns_to_closed(self, api):
        """PRD §3.5: "A subsequent finalize transitions the TaxYear
        back AMENDED → CLOSED and re-issues the K-1s".

        Claim: finalize on AMENDED returns the year to CLOSED.
        """
        scenario = setup_tax_year_in_amend_state(income_amount=5_000.00)
        scenario.tax_year = finalize_tax_year(
            scenario.trust, scenario.tax_year,
        )
        assert scenario.tax_year["status"] == "CLOSED"

    def test_amend_blocked_when_newer_year_closed(self, api):
        """PRD §3.5: "Amendment is forbidden when a later TaxYear for
        the same trust has already reached CLOSED status — the rule
        is 'amend in chronological order' and the rejection code is
        ERR_NEWER_YEAR_CLOSED."

        Claim: amend on year 2025 when year 2026 is CLOSED ->
        ERR_NEWER_YEAR_CLOSED.

        Construction: open and close 2025 then 2026 in sequence on
        the same trust, then try to amend 2025.
        """
        # Use far-future years so clock advances persist cleanly and
        # don't interfere with earlier tests' fixtures.
        from test_helpers import (
            TEST_USERS, add_tax_year, book_transaction,
            create_trust, setup_activatable_trust,
        )
        # Open the trust with inception_date in 2025 and a 2025
        # TaxYear so activation works.
        scenario = setup_activatable_trust(
            inception_date="2025-01-01", calendar_year=2025,
        )
        # Activate.
        from test_helpers import activate_trust
        scenario.trust = activate_trust(
            scenario.trust, scenario.grantor_headers,
        )
        # Book some 2025 income and close 2025.
        book_transaction(
            scenario.trust, scenario.primary_trustee_headers,
            txn_type="INCOME_ORDINARY", amount=1_000.00,
            principal_or_income="INCOME",
            transaction_date=iso_instant_utc(2025, 6, 1),
        )
        advance_clock_to(iso_instant_utc(2026, 1, 2))
        ty_2025 = begin_close_tax_year(
            scenario.trust, scenario.tax_year,
        )
        ty_2025 = finalize_tax_year(scenario.trust, ty_2025)
        # Open 2026 TaxYear, add income, close it.
        ty_2026 = add_tax_year(scenario.trust, calendar_year=2026)
        book_transaction(
            scenario.trust, scenario.primary_trustee_headers,
            txn_type="INCOME_ORDINARY", amount=500.00,
            principal_or_income="INCOME",
            transaction_date=iso_instant_utc(2026, 6, 1),
        )
        advance_clock_to(iso_instant_utc(2027, 1, 2))
        ty_2026 = begin_close_tax_year(scenario.trust, ty_2026)
        ty_2026 = finalize_tax_year(scenario.trust, ty_2026)
        assert ty_2026["status"] == "CLOSED"
        # Now try to amend 2025.
        resp = api.amend_tax_year(
            scenario.trust["id"], ty_2025["id"],
            TEST_USERS["tax_preparer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NEWER_YEAR_CLOSED.value)


# ===========================================================================
# K-1 supersession — PRD §3.5, §3.7
# ===========================================================================
class TestK1Supersession:

    def test_amend_supersedes_issued_k1s_and_drafts_new(self, api):
        """PRD §3.5: "every K-1 in ISSUED status for this tax_year_id
        transitions to SUPERSEDED; and a fresh set of DRAFT K-1
        records is created, one per ACTIVE-at-year-end Beneficiary."
        PRD §3.7: "Exactly one K-1 in ISSUED status exists per
        pairing of tax_year_id and beneficiary_id; previously-issued
        copies for the same pair are moved to SUPERSEDED when a new
        amendment is issued."

        Claim: after amend, the prior ISSUED K-1 for the beneficiary
        is now SUPERSEDED, and there is a fresh DRAFT K-1 in its
        place.
        """
        scenario = setup_closed_tax_year(income_amount=5_000.00)
        # K-1 should exist as ISSUED for the beneficiary.
        issued_k1s = list_k1s_for_year(
            scenario.trust, scenario.tax_year,
        )
        # Filter to this beneficiary.
        own = [
            k for k in issued_k1s
            if k["beneficiary_id"] == scenario.beneficiary["id"]
        ]
        assert any(k["status"] == "ISSUED" for k in own), (
            f"Expected an ISSUED K-1 for the beneficiary after "
            f"first close; got {own}"
        )
        # Amend.
        scenario.tax_year = amend_tax_year(
            scenario.trust, scenario.tax_year,
        )
        k1s_after = list_k1s_for_year(
            scenario.trust, scenario.tax_year,
        )
        own_after = [
            k for k in k1s_after
            if k["beneficiary_id"] == scenario.beneficiary["id"]
        ]
        # Previously-issued K-1 must now be SUPERSEDED.
        assert any(k["status"] == "SUPERSEDED" for k in own_after), (
            f"After amend, previously-issued K-1 must become "
            f"SUPERSEDED; got {own_after}"
        )
        # A fresh DRAFT K-1 must exist.
        assert any(k["status"] == "DRAFT" for k in own_after), (
            f"After amend, a fresh DRAFT K-1 must exist; got "
            f"{own_after}"
        )

    def test_k1_status_in_enum(self, api):
        """PRD §3.7: "a status of DRAFT, ISSUED, or SUPERSEDED".

        Claim: every K-1 returned by a list call has status in the
        documented enum.
        """
        scenario = setup_closed_tax_year(income_amount=5_000.00)
        k1s = list_k1s_for_year(scenario.trust, scenario.tax_year)
        assert k1s, "expected at least one K-1 after close"
        for k in k1s:
            assert_k1(k)
            assert k["status"] in {"DRAFT", "ISSUED", "SUPERSEDED"}
