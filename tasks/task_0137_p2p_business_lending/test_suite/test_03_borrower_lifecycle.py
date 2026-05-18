"""Borrower lifecycle: create, snapshot attach, approve, suspend,
reinstate, ban.

PRD §3.2.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    approve_borrower,
    assert_borrower,
    attach_plaid_snapshot,
    ban_borrower,
    create_borrower,
    create_borrower_payload,
    create_compliance_officer,
    create_listing,
    get_borrower,
    get_investor,
    get_listing,
    get_loan,
    list_disclosures,
    make_compliance_officer_headers,
    reinstate_borrower,
    setup_approved_borrower,
    setup_funded_listing,
    setup_loan_charged_off,
    setup_open_listing,
    setup_platform_with_officer,
    suspend_borrower,
    validate_error,
    validate_success,
)


class TestBorrowerCreate:

    def test_create_borrower_initial_state(
        self, api, platform_operator_headers,
    ):
        """PRD §3.2: "On creation, the borrower's status is PENDING_KYC,
        the final_grade is UNGRADED, the plaid_snapshot_id is null, and
        the server immediately computes the borrower's provisional_grade
        from the self-reported fields alone."

        Claim: new borrower has status=PENDING_KYC, final_grade=
        UNGRADED, plaid_snapshot_id is null, provisional_grade is one
        of A..E.
        """
        platform, _ = setup_platform_with_officer()
        b = create_borrower(platform["id"])
        assert_borrower(b)
        assert b["status"] == "PENDING_KYC"
        assert b["final_grade"] == "UNGRADED"
        assert b["plaid_snapshot_id"] is None
        assert b["provisional_grade"] in {"A", "B", "C", "D", "E"}

    def test_duplicate_ein_rejected(
        self, api, platform_operator_headers,
    ):
        """PRD §3.2: "The ein must be unique among all borrowers on the
        same platform; a duplicate yields ERR_DUPLICATE_EIN."

        Claim: creating a second borrower with the same ein on the same
        platform -> ERR_DUPLICATE_EIN.
        """
        platform, _ = setup_platform_with_officer()
        b1 = create_borrower(platform["id"], ein="12-3456789")
        resp = api.create_borrower(
            platform["id"],
            create_borrower_payload(ein="12-3456789"),
            platform_operator_headers,
        )
        validate_error(resp, "ERR_DUPLICATE_EIN")


class TestPlaidSnapshotAttach:

    def test_attach_snapshot_updates_borrower_plaid_snapshot_id(
        self, api,
    ):
        """PRD §3.2: "sets the borrower's plaid_snapshot_id to the new
        snapshot's id so that the most recent snapshot is always the
        one used for grading."

        Claim: after attach, borrower.plaid_snapshot_id == snapshot.id.
        """
        platform, _ = setup_platform_with_officer()
        b = create_borrower(platform["id"])
        snap = attach_plaid_snapshot(platform["id"], b["id"])
        refreshed = get_borrower(platform["id"], b["id"])
        assert refreshed["plaid_snapshot_id"] == snap["id"]

    def test_attach_snapshot_recomputes_final_grade(self, api):
        """PRD §3.2: "Attaching a snapshot triggers a recomputation of
        final_grade."

        Claim: an UNGRADED borrower with no snapshot, after attach
        becomes non-UNGRADED.
        """
        platform, _ = setup_platform_with_officer()
        b = create_borrower(platform["id"])
        assert b["final_grade"] == "UNGRADED"
        attach_plaid_snapshot(
            platform["id"], b["id"],
            deposits_last_90d_cents=9_000_000,
            avg_daily_balance_cents=5_000_000,
            nsf_count_last_90d=0,
            existing_debt_service_cents=1_000_00,
        )
        refreshed = get_borrower(platform["id"], b["id"])
        assert refreshed["final_grade"] in {"A", "B", "C", "D", "E"}


class TestBorrowerApprove:

    def test_approve_without_snapshot_rejected(self, api):
        """PRD §3.2: "The transition is rejected unless at least one
        PlaidSnapshot has been attached (otherwise ERR_NO_PLAID_SNAPSHOT)
        and final_grade is not UNGRADED (otherwise
        ERR_BORROWER_UNGRADED)."

        Claim: approve on a borrower with NO snapshot ->
        ERR_NO_PLAID_SNAPSHOT.
        """
        platform, officer = setup_platform_with_officer()
        b = create_borrower(platform["id"])
        resp = api.approve_borrower(
            platform["id"], b["id"],
            make_compliance_officer_headers(officer["id"]),
        )
        validate_error(resp, "ERR_NO_PLAID_SNAPSHOT")

    def test_approve_transitions_borrower_to_approved(self, api):
        """PRD §3.2: "Approval transitions the borrower from
        PENDING_KYC to APPROVED and is reserved for a ComplianceOfficer."

        Claim: after approve, borrower.status == 'APPROVED'.
        """
        platform, officer, b = setup_approved_borrower()
        assert b["status"] == "APPROVED"


class TestBorrowerSuspendCascade:

    def test_suspend_borrower_status_changes(self, api):
        """PRD §3.2: "Suspending an APPROVED borrower drops them to
        SUSPENDED and cascades".

        Claim: suspend on APPROVED borrower -> status == SUSPENDED.
        """
        platform, officer, b = setup_approved_borrower()
        b2 = suspend_borrower(platform["id"], b["id"], officer["id"])
        assert b2["status"] == "SUSPENDED"

    def test_suspend_borrower_cascades_open_listings_to_withdrawn(
        self, api,
    ):
        """PRD §3.2: "every OPEN LoanListing of that borrower is moved
        to WITHDRAWN".

        Claim: after suspend, the borrower's previously OPEN listing
        has status == WITHDRAWN.
        """
        platform, officer, b, listing = setup_open_listing()
        assert listing["status"] == "OPEN"
        suspend_borrower(platform["id"], b["id"], officer["id"])
        refreshed = get_listing(platform["id"], listing["id"])
        assert refreshed["status"] == "WITHDRAWN"

    def test_suspend_refunds_committed_investments(self, api):
        """PRD §3.2: "Suspending an APPROVED borrower drops them to
        SUSPENDED and cascades: every OPEN LoanListing of that borrower
        is moved to WITHDRAWN, every COMMITTED Investment on those
        listings is moved to RELEASED, and each affected investor's
        cash_balance_cents is credited by the corresponding
        amount_cents as a refund."

        Claim: after suspend, the COMMITTED investment on the OPEN
        listing becomes RELEASED and the investor's cash balance is
        credited by the amount_cents of the released investment.

        Note: PRD §3.2's cascade names "every OPEN LoanListing", not
        FUNDED. A FUNDED listing's committed investments are NOT named
        by the cascade, so this test exercises the cascade on a
        partially pledged OPEN listing (still OPEN because the pledge
        is strictly less than principal_cents).
        """
        from test_helpers import (
            create_investment,
            get_listing,
            setup_funded_investor,
            setup_open_listing,
        )
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        investor = setup_funded_investor(platform["id"])
        # Partial pledge -> listing stays OPEN (40_000 < 100_000), the
        # investment is COMMITTED, and the borrower owns the OPEN
        # listing — so the suspend cascade should fire.
        create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=40_000,
        )
        refreshed_listing = get_listing(platform["id"], listing["id"])
        assert refreshed_listing["status"] == "OPEN"
        cash_before = get_investor(
            platform["id"], investor["id"],
        )["cash_balance_cents"]
        suspend_borrower(platform["id"], b["id"], officer["id"])
        inv_after = get_investor(platform["id"], investor["id"])
        assert inv_after["cash_balance_cents"] == cash_before + 40_000


class TestBorrowerReinstate:

    def test_reinstate_blocked_if_borrower_has_charged_off_loan(
        self, api,
    ):
        """PRD §3.2: "Reinstating a SUSPENDED borrower returns them to
        APPROVED; this is rejected with ERR_BORROWER_HAS_LOSSES if the
        borrower has any Loan currently in CHARGED_OFF status."

        Claim: a borrower with a CHARGED_OFF loan who is then suspended
        cannot be reinstated -> ERR_BORROWER_HAS_LOSSES.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_charged_off(principal_cents=100_000)
        assert loan["status"] == "CHARGED_OFF"
        # Suspend the borrower so reinstate is the relevant transition.
        suspend_borrower(platform["id"], b["id"], officer["id"])
        resp = api.reinstate_borrower(
            platform["id"], b["id"],
            make_compliance_officer_headers(officer["id"]),
        )
        validate_error(resp, "ERR_BORROWER_HAS_LOSSES")

    def test_reinstate_returns_borrower_to_approved(self, api):
        """PRD §3.2: "Reinstating a SUSPENDED borrower returns them to
        APPROVED".

        Claim: a clean suspended borrower (no losses) -> reinstate
        succeeds and status == APPROVED.
        """
        platform, officer, b = setup_approved_borrower()
        suspend_borrower(platform["id"], b["id"], officer["id"])
        b2 = reinstate_borrower(platform["id"], b["id"], officer["id"])
        assert b2["status"] == "APPROVED"


class TestBorrowerBan:

    def test_ban_transitions_borrower_to_banned(self, api):
        """PRD §3.2: "Banning is permanent: an APPROVED borrower
        transitions APPROVED -> BANNED with the same OPEN-listing-and-
        COMMITTED-investment cascade as suspend".

        Claim: ban on APPROVED -> status == BANNED.
        """
        platform, officer, b = setup_approved_borrower()
        b2 = ban_borrower(platform["id"], b["id"], officer["id"])
        assert b2["status"] == "BANNED"

    def test_ban_cascades_open_listing_to_withdrawn(self, api):
        """PRD §3.2: "the same OPEN-listing-and-COMMITTED-investment
        cascade as suspend".

        Claim: an OPEN listing on the borrower transitions to WITHDRAWN
        after ban.
        """
        platform, officer, b, listing = setup_open_listing()
        ban_borrower(platform["id"], b["id"], officer["id"])
        refreshed = get_listing(platform["id"], listing["id"])
        assert refreshed["status"] == "WITHDRAWN"
