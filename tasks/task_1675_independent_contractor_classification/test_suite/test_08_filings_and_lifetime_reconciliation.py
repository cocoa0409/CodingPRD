"""1099 filings: reporting math, penalty tiers, lifecycle cycles, lifetime totals."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_filing,
    create_filing,
    create_jurisdiction,
    create_contractor,
    get_contractor,
    get_filing,
    setup_contractor_with_filing,
    submit_filing,
    validate_error,
    validate_success,
    verify_contractor,
)

_TAX = TEST_USERS["tax_reporting_specialist_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]
_OFFICER = TEST_USERS["compliance_officer_headers"]


class TestReportableAmountBoundary:
    def test_reportable_amount_at_federal_boundary(self, api, tax_reporting_specialist_headers):
        """PRD §3.8: "`reportable_amount_cents` sums the `amount_cents` of every line
        item whose `kind` is `SERVICE_FEE` and whose `payment_date` falls within the
        calendar window from January 1 through December 31 of the `tax_year`, both
        endpoints inclusive; `EXPENSE_REIMBURSEMENT` items and service fees paid
        outside the window are excluded."
        PRD §3.8: "`federal_filing_required` is true when the reportable amount is at
        least 60000 cents — the boundary is inclusive. `state_filing_required` is true
        when the reportable amount is at least the referenced jurisdiction's
        `state_filing_threshold_cents`, again inclusive."

        Design: Difficulty/boundary_precision_check/bpc_reportable_threshold_exact_60000
        """
        # Build the contractor directly: setup_contractor_with_filing pre-creates a
        # DRAFT ORIGINAL filing for tax_year 2026, and PRD §3.8's per-recipient/year
        # uniqueness would then correctly reject this test's own filing creation.
        jurisdiction = create_jurisdiction(
            code="US-CA", test_type="ABC_TEST", state_filing_threshold_cents=0,
        )
        contractor = create_contractor()
        res = api.create_filing(
            {
                "contractor_id": contractor["id"],
                "state_jurisdiction_id": jurisdiction["id"],
                "tax_year": 2026,
                "payment_line_items": [
                    {"amount_cents": 40000, "payment_date": "2026-03-10", "kind": "SERVICE_FEE"},
                    {"amount_cents": 20000, "payment_date": "2026-11-01", "kind": "SERVICE_FEE"},
                    {"amount_cents": 50000, "payment_date": "2026-04-01", "kind": "EXPENSE_REIMBURSEMENT"},
                    {"amount_cents": 9999, "payment_date": "2027-01-05", "kind": "SERVICE_FEE"},
                ],
            },
            tax_reporting_specialist_headers,
        )
        filing = validate_success(res, 201)
        assert_filing(filing)
        assert filing["reportable_amount_cents"] == 60000
        assert filing["federal_filing_required"] is True
        # Jurisdiction state threshold is 0: 60000 >= 0.
        assert filing["state_filing_required"] is True

    def test_reportable_amount_one_cent_below_boundary(self, api, tax_reporting_specialist_headers):
        """PRD §3.8: "`federal_filing_required` is true when the reportable amount is
        at least 60000 cents — the boundary is inclusive."

        Design: Difficulty/boundary_precision_check/bpc_reportable_threshold_exact_60000
        """
        # See test_reportable_amount_at_federal_boundary: the fixture's pre-created
        # DRAFT ORIGINAL filing would collide under PRD §3.8 uniqueness.
        jurisdiction = create_jurisdiction(
            code="US-CA", test_type="ABC_TEST", state_filing_threshold_cents=0,
        )
        contractor = create_contractor()
        res = api.create_filing(
            {
                "contractor_id": contractor["id"],
                "state_jurisdiction_id": jurisdiction["id"],
                "tax_year": 2026,
                "payment_line_items": [
                    {"amount_cents": 40000, "payment_date": "2026-03-10", "kind": "SERVICE_FEE"},
                    {"amount_cents": 19999, "payment_date": "2026-11-01", "kind": "SERVICE_FEE"},
                ],
            },
            tax_reporting_specialist_headers,
        )
        filing = validate_success(res, 201)
        assert filing["reportable_amount_cents"] == 59999
        assert filing["federal_filing_required"] is False


class TestLateFilingPenalty:
    def test_late_penalty_tier_boundary_30_vs_31_days(self, api, tax_reporting_specialist_headers,
                                                      platform_admin_headers):
        """PRD §3.8: "the filing deadline is January 31 of the year following the
        `tax_year`, `days_late` is the number of calendar days from that deadline to
        the filing date, floored at zero, and the penalty is 0 cents when the filing is
        on time, 6000 cents when between 1 and 30 days late inclusive, 13000 cents when
        between 31 and 121 days late inclusive, and 33000 cents when 122 or more days
        late."

        Design: Corner/calculations/calc_late_filing_penalty_tier_boundary
        """
        setup_a = setup_contractor_with_filing(
            line_items=[{"amount_cents": 100000, "payment_date": "2026-05-20", "kind": "SERVICE_FEE"}],
            jurisdiction_overrides={
                "code": "US-CA", "test_type": "ABC_TEST", "state_filing_threshold_cents": 0,
            },
        )
        setup_b = setup_contractor_with_filing(
            line_items=[{"amount_cents": 100000, "payment_date": "2026-05-20", "kind": "SERVICE_FEE"}],
            jurisdiction_overrides={
                "code": "US-NV", "test_type": "ABC_TEST", "state_filing_threshold_cents": 0,
            },
        )

        # Deadline for tax_year 2026 is 2027-01-31; 2027-03-02 is 30 days late.
        api.set_clock("2027-03-02T12:00:00Z", platform_admin_headers)
        filed_a = validate_success(
            api.submit_filing(setup_a["filing"]["id"], tax_reporting_specialist_headers), 200
        )
        assert filed_a["days_late"] == 30
        assert filed_a["penalty_cents"] == 6000

        # 2027-03-03 is 31 days late: tier 2 lower edge.
        api.set_clock("2027-03-03T12:00:00Z", platform_admin_headers)
        filed_b = validate_success(
            api.submit_filing(setup_b["filing"]["id"], tax_reporting_specialist_headers), 200
        )
        assert filed_b["days_late"] == 31
        assert filed_b["penalty_cents"] == 13000


class TestDefaultClock:
    def test_default_clock_stamps_filed_at(self, api, tax_reporting_specialist_headers):
        """PRD §2.5: "At server startup, before any explicit set, the clock reads
        exactly 2026-08-01T00:00:00Z, and it must not fall back to wall-clock time
        under any circumstance."
        PRD §3.8: "On the first successful submission the filing's `filed_at` is
        stamped with the logical clock, and `days_late` and `penalty_cents` are
        computed" — with the default clock a 2026 filing is on time (0 and 0).

        Design: Corner/endpoints/ep_clock_default_is_2026_08_01
        """
        setup = setup_contractor_with_filing(
            line_items=[{"amount_cents": 80000, "payment_date": "2026-05-01", "kind": "SERVICE_FEE"}]
        )
        filed = validate_success(
            api.submit_filing(setup["filing"]["id"], tax_reporting_specialist_headers), 200
        )
        assert str(filed["filed_at"]).startswith("2026-08-01T00:00:00")
        assert filed["days_late"] == 0
        assert filed["penalty_cents"] == 0


class TestFilingGates:
    def test_filing_submit_blocked_until_contractor_verified(self, api, tax_reporting_specialist_headers):
        """PRD §3.2: "Executing a contract and submitting a 1099 filing each require
        `verification_status` of `VERIFIED`; otherwise the operation is rejected with
        `ERR_CONTRACTOR_NOT_VERIFIED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/cesd_filing_submit_requires_verified_contractor
        """
        setup = setup_contractor_with_filing(
            verify=False,
            line_items=[{"amount_cents": 100000, "payment_date": "2026-05-20", "kind": "SERVICE_FEE"}],
        )
        assert setup["contractor"]["verification_status"] == "UNVERIFIED"
        res = api.submit_filing(setup["filing"]["id"], tax_reporting_specialist_headers)
        validate_error(res, ApiErrorId.ERR_CONTRACTOR_NOT_VERIFIED.value)

    def test_filing_submit_succeeds_after_verification(self, api, tax_reporting_specialist_headers):
        """PRD §3.2: "Executing a contract and submitting a 1099 filing each require
        `verification_status` of `VERIFIED`; otherwise the operation is rejected with
        `ERR_CONTRACTOR_NOT_VERIFIED` (HTTP 422)."
        PRD §3.8: "Submission moves a filing from `DRAFT` — or from `REJECTED_AGENCY`,
        the resubmission cycle — to `SUBMITTED`".

        Design: Difficulty/cross_entity_state_dependency/cesd_filing_submit_requires_verified_contractor
        """
        setup = setup_contractor_with_filing(
            verify=False,
            line_items=[{"amount_cents": 100000, "payment_date": "2026-05-20", "kind": "SERVICE_FEE"}],
        )
        verify_contractor(setup["contractor"]["id"])
        submitted = validate_success(
            api.submit_filing(setup["filing"]["id"], tax_reporting_specialist_headers), 200
        )
        assert submitted["status"] == "SUBMITTED"

    def test_duplicate_original_filing_same_year_rejected(self, api, tax_reporting_specialist_headers):
        """PRD §3.8: "Uniqueness is enforced per recipient and year: at most one
        `ORIGINAL` filing that is neither `VOID` nor `SUPERSEDED` may exist for a given
        `contractor_id` and `tax_year`, and a conflicting creation is rejected with
        `ERR_DUPLICATE_FILING` (HTTP 409)."

        Design: Corner/validations/val_duplicate_filing_same_year_rejected
        """
        setup = setup_contractor_with_filing(verify=False)
        res = api.create_filing(
            {
                "contractor_id": setup["contractor"]["id"],
                "state_jurisdiction_id": setup["jurisdiction"]["id"],
                "tax_year": 2026,
                "payment_line_items": [
                    {"amount_cents": 5000, "payment_date": "2026-06-01", "kind": "SERVICE_FEE"}
                ],
            },
            tax_reporting_specialist_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_FILING.value)

    def test_correction_submit_requires_accepted_target(self, api, tax_reporting_specialist_headers):
        """PRD §3.8: "a `CORRECTION` filing additionally requires its
        `corrects_filing_id` target to be in `ACCEPTED` status, otherwise
        `ERR_CORRECTION_REQUIRES_ACCEPTED` (HTTP 409)."

        Design: Corner/validations/val_correction_submit_requires_accepted_target
        """
        setup = setup_contractor_with_filing()
        original = submit_filing(setup["filing"]["id"])
        assert original["status"] == "SUBMITTED"

        correction = create_filing(
            setup["contractor"]["id"], setup["jurisdiction"]["id"], tax_year=2026,
            line_items=[{"amount_cents": 85000, "payment_date": "2026-05-01", "kind": "SERVICE_FEE"}],
            kind="CORRECTION", corrects_filing_id=original["id"],
        )
        res = api.submit_filing(correction["id"], tax_reporting_specialist_headers)
        validate_error(res, ApiErrorId.ERR_CORRECTION_REQUIRES_ACCEPTED.value)
        assert get_filing(original["id"])["status"] == "SUBMITTED"

    def test_submit_from_accepted_not_submittable(self, api, tax_reporting_specialist_headers):
        """PRD §3.8: "Submission moves a filing from `DRAFT` — or from
        `REJECTED_AGENCY`, the resubmission cycle — to `SUBMITTED`; submitting from any
        other status is rejected with `ERR_FILING_NOT_SUBMITTABLE` (HTTP 409)."

        Design: Corner/errors/err_filing_submit_from_accepted_not_submittable
        """
        setup = setup_contractor_with_filing()
        submit_filing(setup["filing"]["id"])
        accepted = validate_success(
            api.agency_response(setup["filing"]["id"], {"outcome": "ACCEPTED"},
                                tax_reporting_specialist_headers),
            200,
        )
        assert accepted["status"] == "ACCEPTED"

        res = api.submit_filing(setup["filing"]["id"], tax_reporting_specialist_headers)
        validate_error(res, ApiErrorId.ERR_FILING_NOT_SUBMITTABLE.value)
        assert get_filing(setup["filing"]["id"])["status"] == "ACCEPTED"
        assert get_contractor(setup["contractor"]["id"])["lifetime_reported_cents"] == 80000


class TestFilingCycles:
    def test_filing_rejection_and_resubmission_cycle(self, api, tax_reporting_specialist_headers):
        """PRD §3.8: "The agency's acknowledgement arrives through the
        `TaxReportingSpecialist` recording an `outcome`: `ACCEPTED` moves the filing
        `SUBMITTED → ACCEPTED`, while `REJECTED` moves it `SUBMITTED → REJECTED_AGENCY`,
        from which the resubmission cycle above can begin again."

        Design: Difficulty/non_linear_state_machine/nsm_filing_rejection_and_correction_cycles
        """
        setup = setup_contractor_with_filing(
            line_items=[
                {"amount_cents": 60000, "payment_date": "2026-03-10", "kind": "SERVICE_FEE"},
                {"amount_cents": 40000, "payment_date": "2026-06-15", "kind": "SERVICE_FEE"},
            ]
        )
        filing_id = setup["filing"]["id"]
        submit_filing(filing_id)
        rejected = validate_success(
            api.agency_response(filing_id, {"outcome": "REJECTED"}, tax_reporting_specialist_headers),
            200,
        )
        assert rejected["status"] == "REJECTED_AGENCY"

        resubmitted = validate_success(
            api.submit_filing(filing_id, tax_reporting_specialist_headers), 200
        )
        assert resubmitted["status"] == "SUBMITTED"

        accepted = validate_success(
            api.agency_response(filing_id, {"outcome": "ACCEPTED"}, tax_reporting_specialist_headers),
            200,
        )
        assert accepted["status"] == "ACCEPTED"

    def test_correction_submit_supersedes_accepted_target(self, api, tax_reporting_specialist_headers):
        """PRD §3.8: "When a `CORRECTION` filing is submitted, its accepted target
        transitions `ACCEPTED → SUPERSEDED` — the target's signed amount leaves the
        contractor's lifetime total and the correction's enters".

        Design: Difficulty/non_linear_state_machine/nsm_filing_rejection_and_correction_cycles
        """
        setup = setup_contractor_with_filing(
            line_items=[
                {"amount_cents": 60000, "payment_date": "2026-03-10", "kind": "SERVICE_FEE"},
                {"amount_cents": 40000, "payment_date": "2026-06-15", "kind": "SERVICE_FEE"},
            ]
        )
        contractor_id = setup["contractor"]["id"]
        original = submit_filing(setup["filing"]["id"])
        validate_success(
            api.agency_response(original["id"], {"outcome": "ACCEPTED"}, tax_reporting_specialist_headers),
            200,
        )

        correction = create_filing(
            contractor_id, setup["jurisdiction"]["id"], tax_year=2026,
            line_items=[
                {"amount_cents": 60000, "payment_date": "2026-03-10", "kind": "SERVICE_FEE"},
                {"amount_cents": 45000, "payment_date": "2026-06-15", "kind": "SERVICE_FEE"},
            ],
            kind="CORRECTION", corrects_filing_id=original["id"],
        )
        submitted = validate_success(
            api.submit_filing(correction["id"], tax_reporting_specialist_headers), 200
        )
        assert submitted["status"] == "SUBMITTED"
        assert get_filing(original["id"])["status"] == "SUPERSEDED"
        # Correction 60000 + 45000 = 105000 counted; the superseded original is out.
        assert get_contractor(contractor_id)["lifetime_reported_cents"] == 105000


class TestLifetimeReconciliation:
    def test_submit_raises_lifetime_reported(self, api, tax_reporting_specialist_headers):
        """PRD §3.8: "A contractor's `lifetime_reported_cents` is the sum of
        `signed_amount_cents` over exactly those of the contractor's filings in
        `SUBMITTED` or `ACCEPTED` status; filings in `DRAFT`, `REJECTED_AGENCY`,
        `SUPERSEDED`, or `VOID` contribute nothing."

        Design: Difficulty/compensating_invariant/ci_lifetime_reported_submit_void_pair
        """
        setup = setup_contractor_with_filing(
            line_items=[{"amount_cents": 60000, "payment_date": "2026-04-15", "kind": "SERVICE_FEE"}]
        )
        contractor_id = setup["contractor"]["id"]
        assert get_contractor(contractor_id)["lifetime_reported_cents"] == 0
        submit_filing(setup["filing"]["id"])
        assert get_contractor(contractor_id)["lifetime_reported_cents"] == 60000

    def test_void_correction_restores_lifetime_exactly(self, api, tax_reporting_specialist_headers):
        """PRD §3.8: "The total is recomputed on every transition into or out of the
        counted set — submission, resubmission, agency response, void correction, and
        correction supersession — so the reconciliation invariant holds: a submission
        followed by a `VOID` correction of the same filing returns
        `lifetime_reported_cents` to its pre-submission value exactly."

        Design: Difficulty/compensating_invariant/ci_lifetime_reported_submit_void_pair
        """
        setup = setup_contractor_with_filing(
            line_items=[{"amount_cents": 60000, "payment_date": "2026-04-15", "kind": "SERVICE_FEE"}]
        )
        contractor_id = setup["contractor"]["id"]
        filing_id = setup["filing"]["id"]
        before = get_contractor(contractor_id)["lifetime_reported_cents"]
        submit_filing(filing_id)
        voided = validate_success(
            api.correct_filing(filing_id, {"mode": "VOID", "reason": "Filed in error — wrong contractor"},
                               tax_reporting_specialist_headers),
            200,
        )
        assert voided["status"] == "VOID"
        assert get_contractor(contractor_id)["lifetime_reported_cents"] == before

    def test_lifetime_reconciles_on_agency_rejection(self, api, tax_reporting_specialist_headers):
        """PRD §3.8: "A contractor's `lifetime_reported_cents` is the sum of
        `signed_amount_cents` over exactly those of the contractor's filings in
        `SUBMITTED` or `ACCEPTED` status; filings in `DRAFT`, `REJECTED_AGENCY`,
        `SUPERSEDED`, or `VOID` contribute nothing. The total is recomputed on every
        transition into or out of the counted set".

        Design: Corner/cross_cutting_layers/layer_derived_field_reconciliation_on_agency_rejection
        """
        setup = setup_contractor_with_filing()
        contractor_id = setup["contractor"]["id"]
        filing_id = setup["filing"]["id"]

        submit_filing(filing_id)
        assert get_contractor(contractor_id)["lifetime_reported_cents"] == 80000

        validate_success(
            api.agency_response(filing_id, {"outcome": "REJECTED"}, tax_reporting_specialist_headers),
            200,
        )
        assert get_contractor(contractor_id)["lifetime_reported_cents"] == 0

        submit_filing(filing_id)
        assert get_contractor(contractor_id)["lifetime_reported_cents"] == 80000
