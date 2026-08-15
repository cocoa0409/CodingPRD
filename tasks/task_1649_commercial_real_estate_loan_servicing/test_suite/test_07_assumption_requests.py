"""Assumption request lifecycle: OCC-guarded creation, approval gates, fee
variants, approval expiry, and execution."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_inspection,
    create_assumption,
    create_assumption_payload,
    create_borrower,
    create_inspector,
    create_loan,
    create_property,
    decide_assumption,
    get_loan,
    get_success_data,
    make_borrower_headers,
    schedule_inspection,
    set_clock,
    set_payment_status,
    start_assumption_review,
    validate_error,
    validate_paginated,
    validate_success,
)

MS = TEST_USERS["master_servicer_headers"]


def _assumption_workspace(tax_id, loan_number, with_inspection=False,
                          origination="2026-08-01T00:00:00Z",
                          principal=500_000_000, note_rate=0.05,
                          fee_basis="OUTSTANDING", current_balance=None):
    borrower = create_borrower(legal_name=f"{loan_number} Co", tax_id=tax_id,
                               contact_email=f"{tax_id.lower()}@x.com")
    overrides = dict(original_principal_cents=principal, note_rate=note_rate,
                     origination_date=origination,
                     assumption_fee_basis=fee_basis)
    if current_balance is not None:
        overrides["current_balance_cents"] = current_balance
    loan = create_loan(borrower["id"], loan_number=loan_number, **overrides)
    prop = create_property(loan["id"], address=f"1 {loan_number} St")
    inspector = None
    if with_inspection:
        inspector = create_inspector(full_name="Assumption Spect",
                                     license_no=f"LIC-{tax_id}")
        insp = schedule_inspection(prop["id"], inspector["id"],
                                   scheduled_start="2026-08-01T09:00:00Z",
                                   scheduled_end="2026-08-01T10:00:00Z")
        complete_inspection(insp["id"], inspector["id"], "GOOD")
    return borrower, loan, prop, inspector


def _request_status(api, loan_id, request_id):
    rows, _meta = validate_paginated(api.list_assumption_requests(loan_id, MS))
    for row in rows:
        if row["id"] == request_id:
            return row["status"]
    raise AssertionError(f"assumption request {request_id} not found")


class TestAssumptionFeeVariants:
    def _board_fee_pair(self):
        """Two loans, identical principal/balance, differing only in fee basis;
        each with a property and a fresh COMPLETED GOOD inspection."""
        borrower = create_borrower(legal_name="Fee Divergence LP",
                                   tax_id="TX-FEE-1", contact_email="fee@x.com")
        inspector = create_inspector(full_name="Ingrid Specter",
                                     license_no="LIC-001")
        loans = {}
        for tag, basis, start, end in (
                ("OUT", "OUTSTANDING", "2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z"),
                ("ORG", "ORIGINAL", "2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z")):
            loan = create_loan(
                borrower["id"], loan_number=f"LN-{tag}",
                original_principal_cents=1_000_000_000,
                current_balance_cents=800_000_000, note_rate=0.06,
                origination_date="2025-01-01T00:00:00Z",
                maturity_date="2028-01-31T00:00:00Z",
                assumption_fee_basis=basis)
            prop = create_property(loan["id"], address=f"Fee St {tag}",
                                   appraised_value_cents=2_000_000_000)
            insp = schedule_inspection(prop["id"], inspector["id"],
                                       scheduled_start=start, scheduled_end=end)
            complete_inspection(insp["id"], inspector["id"], "GOOD")
            loans[tag] = loan
        return borrower, loans

    def test_assumption_fee_outstanding_basis(self, api):
        """PRD §3.7: "On the `OUTSTANDING` basis the fee is one percent of the
        loan's `current_balance_cents`, rounded half-up to whole cents, then
        clamped to never less than 1,000,000 cents and never more than
        25,000,000 cents."
        PRD §2.8: "`POST /loans/{loan_id}/assumption-requests` requires the
        non-optional field `expected_loan_version`, carrying the target loan's
        `version` as the client last observed it."

        Design: Difficulty/dual_variant_calc/assumption_fee_outstanding_vs_original_divergence
        """
        borrower, loans = self._board_fee_pair()
        loan_c = loans["OUT"]
        # The OCC token captured at boarding still matches: neither attaching a
        # property nor the inspections mutate the loan's version.
        request = create_assumption(loan_c["id"], borrower["id"],
                                    expected_version=loan_c["version"],
                                    proposed_assumptor_name="Acquirer One",
                                    proposed_assumptor_tax_id="TX-AQ-1")
        start_assumption_review(request["id"])
        decided = decide_assumption(request["id"], "APPROVE")
        assert decided["status"] == "APPROVED"
        # 1% of the 800,000,000 current UPB, inside the clamp band.
        assert decided["fee_cents"] == 8_000_000

    def test_assumption_fee_original_basis(self, api):
        """PRD §3.7: "On the `ORIGINAL` basis the fee is one-half of one percent
        of the `original_principal_cents`, rounded half-up to whole cents, plus a
        flat 25,000 cents, and this variant is never clamped."
        PRD §3.7: "The computed `fee_cents` — null until this point — the
        `decided_at` clock time, and an `approval_expires_at` exactly sixty days
        after the decision are all stamped at approval."

        Design: Difficulty/dual_variant_calc/assumption_fee_outstanding_vs_original_divergence
        """
        borrower, loans = self._board_fee_pair()
        loan_d = loans["ORG"]
        request = create_assumption(loan_d["id"], borrower["id"],
                                    expected_version=loan_d["version"],
                                    proposed_assumptor_name="Acquirer Two",
                                    proposed_assumptor_tax_id="TX-AQ-2")
        assert request["fee_cents"] is None, "fee_cents stays null until approval"
        start_assumption_review(request["id"])
        decided = decide_assumption(request["id"], "APPROVE")
        assert decided["status"] == "APPROVED"
        # 0.5% of the 1,000,000,000 original principal + 25,000 flat, unclamped.
        assert decided["fee_cents"] == 5_025_000
        assert decided["decided_at"].startswith("2026-08-01")
        assert decided["approval_expires_at"].startswith("2026-09-30"), (
            "approval_expires_at is exactly sixty days after the decision")


class TestAssumptionOptimisticConcurrency:
    def test_stale_version_checked_before_uniqueness(self, api):
        """PRD §2.10: "Every request is validated against a fixed pipeline, and
        when several checks would fail at once, the error returned is the one
        belonging to the earliest failing check" — step 6 is "Optimistic
        concurrency: on the two guarded creates of §2.8, the expected parent
        version must equal the parent's current `version` — else
        `ERR_STALE_VERSION`" and step 25 is "Assumption already in progress —
        `ERR_ASSUMPTION_IN_PROGRESS`."
        PRD §3.7: "creating the request itself advances the loan's `version`."

        Design: Corner/validations/stale_version_checked_before_uniqueness
        """
        borrower, loan, _prop, _i = _assumption_workspace(
            "TX-OCC", "LN-OCC", with_inspection=False)
        first = create_assumption(loan["id"], borrower["id"],
                                  expected_version=loan["version"],
                                  proposed_assumptor_name="First",
                                  proposed_assumptor_tax_id="TX-F1",
                                  proposed_net_worth_cents=100_000_000)
        assert first["status"] == "SUBMITTED"
        # The second create carries the same stale token while a non-terminal
        # request exists: OCC (step 6) precedes uniqueness (step 25).
        resp = api.create_assumption_request(
            loan["id"],
            create_assumption_payload(loan["version"],
                                      proposed_assumptor_name="Second",
                                      proposed_assumptor_tax_id="TX-F2",
                                      proposed_net_worth_cents=200_000_000),
            make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

    def test_occ_assumption_create_stale_loan_version_returns_412(self, api):
        """PRD §2.8: "`POST /loans/{loan_id}/assumption-requests` requires the
        non-optional field `expected_loan_version`, carrying the target loan's
        `version` as the client last observed it. If the loan's current `version`
        no longer matches — because the loan has been mutated since that read —
        the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the
        client from booking an assumption priced on a stale snapshot of the loan."
        PRD §3.6: "Every payment-dimension change advances the loan's `version`"

        Design: Corner/cross_cutting_complexity_layers/occ_assumption_create_stale_loan_version_returns_412
        """
        borrower, loan, _prop, _i = _assumption_workspace("TX-OCL", "LN-OCL")
        set_payment_status(loan["id"], "DELINQUENT")
        set_payment_status(loan["id"], "CURRENT")
        # The loan's version moved twice since the client's read.
        resp = api.create_assumption_request(
            loan["id"],
            create_assumption_payload(loan["version"],
                                      proposed_assumptor_name="Stale Buyer",
                                      proposed_assumptor_tax_id="TX-STB",
                                      proposed_net_worth_cents=900_000_000),
            make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        _rows, meta = validate_paginated(
            api.list_assumption_requests(loan["id"], MS))
        assert meta["total_count"] == 0, "no request is persisted on a stale create"


class TestAssumptionGates:
    def test_assumption_approve_without_inspection_rejected(self, api):
        """PRD §3.7: "every property of the loan must have a `COMPLETED`
        inspection whose `completed_at` lies within twelve months of the clock
        with a rating other than `CRITICAL` (else `ERR_INSPECTION_STALE`)."

        Design: Corner/validations/assumption_approve_without_inspection_rejected
        """
        borrower, loan, _prop, _i = _assumption_workspace(
            "TX-NIN", "LN-NIN", with_inspection=False)
        request = create_assumption(loan["id"], borrower["id"],
                                    proposed_assumptor_name="NoInsp Buyer",
                                    proposed_assumptor_tax_id="TX-NIB",
                                    proposed_net_worth_cents=900_000_000)
        start_assumption_review(request["id"])
        resp = api.decide_assumption(request["id"], {"decision": "APPROVE"}, MS)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_STALE)
        assert _request_status(api, loan["id"], request["id"]) == "UNDER_REVIEW"

    def test_assumption_execute_after_approval_expiry_rejected(self, api):
        """PRD §3.7: "Execution is guarded afresh: the request must stand
        `APPROVED` (else `ERR_INVALID_STATE`); the clock must not have passed
        `approval_expires_at` (else `ERR_ASSUMPTION_APPROVAL_EXPIRED`)"
        PRD §3.7: "an `approval_expires_at` exactly sixty days after the decision"

        Design: Corner/validations/assumption_execute_after_approval_expiry_rejected
        """
        borrower, loan, _prop, _i = _assumption_workspace(
            "TX-LPA", "LN-LPA", with_inspection=True)
        request = create_assumption(loan["id"], borrower["id"],
                                    proposed_assumptor_name="Lpa Buyer",
                                    proposed_assumptor_tax_id="TX-LPB",
                                    proposed_net_worth_cents=900_000_000)
        start_assumption_review(request["id"])
        decided = decide_assumption(request["id"], "APPROVE")
        assert decided["status"] == "APPROVED"
        # Approved at the 2026-08-01 clock, expiring 2026-09-30; 2026-10-01 lapses it.
        set_clock("2026-10-01T00:00:00Z")
        resp = api.execute_assumption(request["id"], MS)
        validate_error(resp, ApiErrorId.ERR_ASSUMPTION_APPROVAL_EXPIRED)
        assert _request_status(api, loan["id"], request["id"]) == "APPROVED"
        assert get_loan(loan["id"])["borrower_id"] == borrower["id"], (
            "an expired execution never reassigns the borrower")
