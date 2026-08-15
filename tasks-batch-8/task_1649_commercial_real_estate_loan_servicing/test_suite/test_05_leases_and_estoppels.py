"""Lease drafting/submission/decision/revision lifecycle, suite-overlap
policing, and the estoppel certificate gate on major-lease approvals."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_borrower,
    create_lease,
    create_lease_payload,
    create_loan,
    create_property,
    decide_lease,
    execute_estoppel,
    get_success_data,
    make_borrower_headers,
    request_estoppel,
    revise_lease,
    set_clock,
    submit_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

MS = TEST_USERS["master_servicer_headers"]


def _lease_workspace(tax_id, loan_number):
    borrower = create_borrower(legal_name=f"{loan_number} Co", tax_id=tax_id,
                               contact_email=f"{tax_id.lower()}@x.com")
    loan = create_loan(borrower["id"], loan_number=loan_number,
                       original_principal_cents=100_000_000, note_rate=0.05)
    prop = create_property(loan["id"], address=f"1 {loan_number} St")
    return borrower, loan, prop


class TestLeaseSubmission:
    def test_lease_double_submit_rejected(self, api):
        """PRD §3.4: "Submitting a lease not in `DRAFT` earns `ERR_INVALID_STATE`,
        and submitting outside the borrower's own chain earns
        `ERR_OWNERSHIP_MISMATCH`."

        Design: Corner/state_machines/lease_double_submit_rejected
        """
        borrower, _loan, prop = _lease_workspace("TX-DBL", "LN-DBL")
        lease = create_lease(prop["id"], borrower["id"], suite_ref="STE-1")
        submit_lease(lease["id"], borrower["id"])
        resp = api.submit_lease(lease["id"], make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_lease_suite_overlap_rejected(self, api):
        """PRD §3.4: "Submission moves a `DRAFT` lease to `SUBMITTED`, and it is
        at submission — not drafting — that suite occupancy is policed: occupancy
        intervals are closed on both ends, so if the new lease's interval touches
        or overlaps the interval of any other lease with the same `suite_ref` on
        the same property standing in `SUBMITTED`, `APPROVED`, or
        `CONDITIONALLY_APPROVED`, the submission is rejected with
        `ERR_LEASE_SUITE_OVERLAP`."

        Design: Corner/validations/lease_suite_overlap_rejected
        """
        borrower, _loan, prop = _lease_workspace("TX-SUI", "LN-SUI")
        lease1 = create_lease(prop["id"], borrower["id"], suite_ref="STE-300",
                              tenant_name="T1",
                              commencement_date="2026-09-01T00:00:00Z",
                              expiry_date="2027-08-31T00:00:00Z")
        submit_lease(lease1["id"], borrower["id"])

        lease2 = create_lease(prop["id"], borrower["id"], suite_ref="STE-300",
                              tenant_name="T2", base_rent_cents_monthly=110_000,
                              commencement_date="2027-01-01T00:00:00Z",
                              expiry_date="2027-12-31T00:00:00Z")
        resp = api.submit_lease(lease2["id"], make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_LEASE_SUITE_OVERLAP)
        assert get_success_data(api.get_lease(lease2["id"], MS))["status"] == "DRAFT"

        # Same window on a different suite: the overlap scope is property + suite.
        lease3 = create_lease(prop["id"], borrower["id"], suite_ref="STE-301",
                              tenant_name="T3", base_rent_cents_monthly=110_000,
                              commencement_date="2027-01-01T00:00:00Z",
                              expiry_date="2027-12-31T00:00:00Z")
        submitted = submit_lease(lease3["id"], borrower["id"])
        assert submitted["status"] == "SUBMITTED"


class TestLeaseRevisionCycle:
    def _setup_rejected_lease(self):
        borrower, _loan, prop = _lease_workspace("TX-CYC", "LN-CYC")
        lease = create_lease(
            prop["id"], borrower["id"], suite_ref="STE-100", tenant_name="Tenant A",
            commencement_date="2026-09-01T00:00:00Z",
            expiry_date="2029-08-31T00:00:00Z",
            base_rent_cents_monthly=400_000, sqft=3_000, term_months=36)
        submit_lease(lease["id"], borrower["id"])
        decide_lease(lease["id"], "REJECT")
        return borrower, lease

    def test_rejected_lease_revise_returns_to_draft_with_edits(self, api):
        """PRD §3.4: "A borrower returns a `REJECTED` lease to `DRAFT` by revising
        it, optionally editing `base_rent_cents_monthly`, `sqft`, `term_months`,
        `commencement_date`, or `expiry_date`; revision clears any recorded
        `conditions` and recomputes both approval flags from the edited terms."

        Design: Difficulty/non_linear_state_machine/lease_reject_revise_resubmit_cycle
        """
        borrower, lease = self._setup_rejected_lease()
        revised = revise_lease(lease["id"], borrower["id"],
                               base_rent_cents_monthly=410_000)
        assert revised["status"] == "DRAFT", "revision returns REJECTED to DRAFT"
        assert revised["base_rent_cents_monthly"] == 410_000, (
            "the optional edit is applied")
        assert not revised.get("conditions"), "revision clears recorded conditions"

    def test_lease_cycle_completes_through_conditional_to_approved(self, api):
        """PRD §3.4: "An approval may land on a lease in `SUBMITTED` or
        `CONDITIONALLY_APPROVED`; a conditional approval — which requires the
        servicer's `conditions` text — only on a `SUBMITTED` one; and a rejection
        on either of those two states. Any other starting state fails with
        `ERR_INVALID_STATE`."
        PRD §3.4: "`lender_approval_required`, true whenever the monthly base rent
        exceeds 500,000 cents or the leased area exceeds 5,000 square feet or the
        term exceeds 60 months, and `estoppel_required`, which simply mirrors
        `lender_approval_required`."

        Design: Difficulty/non_linear_state_machine/lease_reject_revise_resubmit_cycle
        """
        borrower, lease = self._setup_rejected_lease()
        revise_lease(lease["id"], borrower["id"], base_rent_cents_monthly=410_000)
        resubmitted = submit_lease(lease["id"], borrower["id"])
        assert resubmitted["status"] == "SUBMITTED", "the cycle re-enters SUBMITTED"

        conditional = decide_lease(lease["id"], "CONDITIONAL",
                                   conditions="repaint suite before commencement")
        assert conditional["status"] == "CONDITIONALLY_APPROVED"
        assert conditional["conditions"] == "repaint suite before commencement"

        approved = decide_lease(lease["id"], "APPROVE")
        assert approved["status"] == "APPROVED", (
            "approval lands on a CONDITIONALLY_APPROVED lease")
        # 410,000 <= 500,000 cents; 3,000 <= 5,000 sqft; 36 <= 60 months.
        assert approved["lender_approval_required"] is False
        assert approved["estoppel_required"] is False


class TestEstoppelGate:
    def _setup_major_lease(self):
        borrower, loan, prop = _lease_workspace("TX-GT2", "LN-GT2")
        lease = create_lease(
            prop["id"], borrower["id"], suite_ref="STE-200",
            tenant_name="Major Tenant",
            commencement_date="2026-09-01T00:00:00Z",
            expiry_date="2030-08-31T00:00:00Z",
            base_rent_cents_monthly=600_000, sqft=4_000, term_months=48)
        submit_lease(lease["id"], borrower["id"])
        estoppel = request_estoppel(lease["id"], "2026-08-20T00:00:00Z")
        return borrower, lease, estoppel

    def test_major_lease_approve_blocked_by_pending_estoppel(self, api):
        """PRD §3.4: "Every approval of an estoppel-required lease passes through
        the estoppel gate: the lease must hold an `EXECUTED` certificate whose
        `expires_at` is still in the future relative to the clock, otherwise the
        decision is refused with `ERR_ESTOPPEL_REQUIRED`."
        PRD §3.4: "`lender_approval_required`, true whenever the monthly base rent
        exceeds 500,000 cents or the leased area exceeds 5,000 square feet or the
        term exceeds 60 months, and `estoppel_required`, which simply mirrors
        `lender_approval_required`."

        Design: Difficulty/cross_entity_state_dependency/major_lease_approval_gated_by_estoppel_execution
        """
        borrower, lease, estoppel = self._setup_major_lease()
        assert estoppel["status"] == "PENDING"
        current = get_success_data(api.get_lease(lease["id"], MS))
        assert current["lender_approval_required"] is True, (
            "rent 600,000 exceeds the 500,000-cent major-lease test")
        assert current["estoppel_required"] is True

        resp = api.decide_lease(lease["id"], {"decision": "APPROVE"}, MS)
        validate_error(resp, ApiErrorId.ERR_ESTOPPEL_REQUIRED)
        after = get_success_data(api.get_lease(lease["id"], MS))
        assert after["status"] == "SUBMITTED", "the blocked approval changes nothing"

    def test_executed_estoppel_unblocks_approval(self, api):
        """PRD §3.4: "The borrower executes a pending certificate on its own
        loan's lease, which stamps `executed_at` — null until that moment — with
        the clock time and sets `expires_at` exactly ninety days later."
        PRD §3.4: "Every approval of an estoppel-required lease passes through the
        estoppel gate: the lease must hold an `EXECUTED` certificate whose
        `expires_at` is still in the future relative to the clock, otherwise the
        decision is refused with `ERR_ESTOPPEL_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/major_lease_approval_gated_by_estoppel_execution
        """
        borrower, lease, estoppel = self._setup_major_lease()
        executed = execute_estoppel(estoppel["id"], borrower["id"])
        assert executed["status"] == "EXECUTED"
        assert executed["executed_at"] is not None
        # Executed at the 2026-08-01 clock; exactly ninety days later.
        assert executed["expires_at"].startswith("2026-10-30"), (
            f"expires_at is executed_at + 90 days, got {executed['expires_at']}")

        approved = decide_lease(lease["id"], "APPROVE")
        assert approved["status"] == "APPROVED"


class TestEstoppelLifecycle:
    def test_duplicate_active_estoppel_rejected(self, api):
        """PRD §3.4: "A lease may hold at most one live certificate — requesting
        another while an unexpired `PENDING` or `EXECUTED` certificate exists for
        the lease is refused with `ERR_DUPLICATE_ACTIVE_ESTOPPEL`."

        Design: Corner/validations/duplicate_active_estoppel_rejected
        """
        borrower, _loan, prop = _lease_workspace("TX-DPE", "LN-DPE")
        lease = create_lease(prop["id"], borrower["id"], suite_ref="STE-7")
        request_estoppel(lease["id"], "2026-08-20T00:00:00Z")
        resp = api.request_estoppel(lease["id"], "2026-08-25T00:00:00Z", MS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_ESTOPPEL)

    def test_estoppel_expiry_allows_fresh_request(self, api):
        """PRD §3.4: "The clock sweep then ages certificates out along two paths:
        a certificate still `PENDING` once the clock passes its `due_date` becomes
        `EXPIRED`, and an `EXECUTED` one becomes `EXPIRED` once the clock passes
        its `expires_at`."
        PRD §3.4: "`EXPIRED` is terminal — a fresh need for an estoppel is met by
        requesting a new record, and a lease's certificates list beneath it."

        Design: Corner/state_machines/estoppel_expiry_allows_fresh_request
        """
        borrower, _loan, prop = _lease_workspace("TX-EST", "LN-EST")
        lease = create_lease(prop["id"], borrower["id"], suite_ref="STE-5")
        first = request_estoppel(lease["id"], "2026-08-10T00:00:00Z")
        set_clock("2026-08-15T00:00:00Z")

        rows, meta = validate_paginated(api.list_estoppels(lease["id"], MS))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["status"] == "EXPIRED", (
            "a PENDING certificate past its due_date is swept to EXPIRED")

        second = validate_success(api.request_estoppel(
            lease["id"], "2026-09-01T00:00:00Z", MS), 201)
        assert second["status"] == "PENDING", (
            "an EXPIRED certificate does not block a fresh request")
