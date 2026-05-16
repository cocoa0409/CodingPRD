"""Family invoicing.

Tests cover PRD §3.7 (family weekly invoice — sum of snapshotted
final_fee_cents over CONFIRMED enrollments aligned to the requested
ISO week).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    confirm_enrollment,
    create_enrollment,
    re_get_enrollment,
    setup_authorized_child,
    setup_family_with_n_authorized_children,
    setup_family_with_primary_guardian,
    setup_open_session,
    validate_success,
)


# ===========================================================================
# Family weekly invoice — sum of snapshots
# ===========================================================================
class TestFamilyInvoice:
    def test_invoice_sums_snapshotted_final_fee_cents(self, api):
        """PRD §3.7: "The invoice totals the per-row snapshotted
        final_fee_cents over those rows — the implementation must read
        the snapshots, not re-derive them from current sibling counts
        or award balances."

        Claim: with one CONFIRMED enrollment of final_fee_cents=10000,
        invoice_total_cents==10000.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session(base_weekly_fee_cents=10_000)
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
        )
        enrollment = create_enrollment(child=child, session=session)
        confirm_enrollment(enrollment=enrollment)
        res = api.get_family_invoice(
            family["id"], TEST_USERS["admin_headers"],
            params={"week_start": session["week_start"]},
        )
        invoice = validate_success(res, 200)
        assert invoice["invoice_total_cents"] == 10_000
        assert invoice["family_id"] == family["id"]
        assert invoice["week_start"] == session["week_start"]

    def test_invoice_excludes_pending_and_cancelled(self, api):
        """PRD §3.7: "the system iterates every CONFIRMED enrollment
        for any child in this family whose session-week aligns".

        Claim: a PENDING_AUTH (non-CONFIRMED) enrollment does NOT
        contribute to the invoice total.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session(base_weekly_fee_cents=10_000)
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
        )
        # Leave the enrollment in PENDING_AUTH (do not confirm).
        create_enrollment(child=child, session=session)
        res = api.get_family_invoice(
            family["id"], TEST_USERS["admin_headers"],
            params={"week_start": session["week_start"]},
        )
        invoice = validate_success(res, 200)
        assert invoice["invoice_total_cents"] == 0

    def test_invoice_three_siblings_per_line_rounding(self, api):
        """PRD §3.5: "The dollar discount for each affected
        enrollment is list_fee_cents multiplied by the per-row
        percentage, then rounded half-up to whole cents
        independently for each line item before the family-level
        summation."
        PRD §3.7: "The invoice totals the per-row snapshotted
        final_fee_cents over those rows".

        Claim: with base_weekly_fee_cents=10003 and three CONFIRMED
        siblings (N=3, 15%, per-line 1500), invoice_total_cents ==
        3 * (10003 - 1500) == 25509.
        """
        family, guardian, children = (
            setup_family_with_n_authorized_children(n=3)
        )
        session = setup_open_session(
            base_weekly_fee_cents=10_003, weekly_capacity=5,
        )
        for c in children:
            e = create_enrollment(child=c, session=session)
            confirm_enrollment(enrollment=e)
        res = api.get_family_invoice(
            family["id"], TEST_USERS["admin_headers"],
            params={"week_start": session["week_start"]},
        )
        invoice = validate_success(res, 200)
        # Per-line: 10003 - 1500 = 8503; total 3 * 8503 = 25509.
        assert invoice["invoice_total_cents"] == 25_509
