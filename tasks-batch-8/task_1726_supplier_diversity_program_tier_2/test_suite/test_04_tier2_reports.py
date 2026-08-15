"""Tier-2 reports: per-line rounding, return/correction cycle, eligibility at
approval, edit lockdown, and the exactly-one-approved invariant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_tier2_report,
    create_approved_tier2_report,
    create_business_unit,
    create_supplier,
    create_supplier_with_verified_cert,
    create_tier2_report,
    generate_scorecard,
    get_success_data,
    make_prime_contact_headers,
    replace_lines_payload,
    submit_tier2_report,
    tier2_line,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN1 = TEST_USERS["admin_1_headers"]
ANALYST1 = TEST_USERS["analyst_1_headers"]


class TestPerLineRounding:
    def _create_three_line_report(self, api):
        """Prime + three diverse suppliers; one DRAFT report whose lines are
        chosen so per-line rounding order decides the cent total."""
        bu = create_business_unit()
        prime = create_supplier(legal_name="Prime Build Inc", tax_id="T-P1",
                                kind="PRIME", contact_email="p@x.com")
        s1 = create_supplier(legal_name="D1", tax_id="T-D1",
                             contact_email="d1@x.com")
        s2 = create_supplier(legal_name="D2", tax_id="T-D2",
                             contact_email="d2@x.com")
        s3 = create_supplier(legal_name="D3", tax_id="T-D3",
                             contact_email="d3@x.com")
        lines = [
            tier2_line(s1["id"], 100001, 33.33),
            tier2_line(s2["id"], 100001, 33.33),
            tier2_line(s3["id"], 100001, 33.34),
        ]
        report = create_tier2_report(prime["id"], bu["id"],
                                     reporting_period="2026-Q1", lines=lines)
        return prime, report

    def test_tier2_per_line_rounding_totals(self, api):
        """PRD §3.4: "`total_subcontracted_cents` is the sum of
        `gross_subcontract_cents` across the lines. `total_diverse_tier2_cents`
        is the sum of a per-line allocation: for each line, the allocated cents
        are the gross subcontract cents multiplied by the diverse share
        percentage divided by 100, rounded half-up to whole cents — and that
        rounding is applied per line first, before any aggregation, and only
        then are the per-line amounts summed."

        Design: Difficulty/combinatorial_formula/tier2_per_line_rounding_then_sum
        """
        _prime, report = self._create_three_line_report(api)
        assert report["total_subcontracted_cents"] == 300003
        # Per-line round_half_up: 33330.3333 -> 33330, 33330.3333 -> 33330,
        # 33340.3334 -> 33340; the diverse total is 33330 + 33330 + 33340.
        assert report["total_diverse_tier2_cents"] == 100000

    def test_tier2_per_line_round_first_not_sum_first(self, api):
        """PRD §3.4: "Summing first and rounding once at the end yields a
        different cent total and is not the contract."

        Design: Difficulty/combinatorial_formula/tier2_per_line_rounding_then_sum
        """
        prime, report = self._create_three_line_report(api)
        stored = validate_success(
            api.get_tier2_report(report["id"],
                                 make_prime_contact_headers(prime["id"])))
        assert stored["total_diverse_tier2_cents"] == 100000, (
            "Pinned order is per-line round first, then sum"
        )
        assert stored["total_diverse_tier2_cents"] != 100001, (
            "The sum-then-round order would give 100001 and is not the "
            "contract"
        )
        assert stored["total_subcontracted_cents"] == 300003


class TestReturnCorrectionCycle:
    def _setup_returned_report(self, api):
        """BU + prime + diverse supplier (VERIFIED cert covering the Q2 period
        end) + one report returned for correction."""
        bu = create_business_unit()
        prime = create_supplier(legal_name="Prime Build Inc", tax_id="T-P9",
                                kind="PRIME", contact_email="p@x.com")
        diverse, _cert = create_supplier_with_verified_cert(
            legal_name="Diverse Parts Co", tax_id="T-DP", cert_type="WBE",
            certificate_number="W-9")
        report = create_tier2_report(
            prime["id"], bu["id"], reporting_period="2026-Q2",
            lines=[tier2_line(diverse["id"], 50000, 80.00)])
        return bu, prime, diverse, report

    def test_tier2_return_correction_cycle_states(self, api):
        """PRD §3.4: "A `DiversityAdmin` or `DiversityAnalyst` may return a
        `SUBMITTED` report to the prime with a `note`, moving it to `RETURNED`
        for correction."
        PRD §3.4: "Submitting — available from either `DRAFT` or `RETURNED` —
        requires that the caller own the report and that `lines` be non-empty
        (an empty submission is `ERR_INVALID_REQUEST`); it moves the report to
        `SUBMITTED` and stamps `submitted_by_user_id`."

        Design: Difficulty/non_linear_state_machine/tier2_report_return_correction_cycle
        """
        _bu, prime, _diverse, report = self._setup_returned_report(api)
        assert report["status"] == "DRAFT"
        assert report["total_diverse_tier2_cents"] == 40000, (
            "80.00% of 50000 allocated per line at creation"
        )
        submitted = submit_tier2_report(report["id"], prime["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == prime["id"]
        returned = validate_success(
            api.return_tier2_report(report["id"], "missing PO detail",
                                    ANALYST1))
        assert returned["status"] == "RETURNED", (
            "The cycle branch DRAFT -> SUBMITTED -> RETURNED is defined"
        )

    def test_tier2_corrected_totals_replace_not_accumulate(self, api):
        """PRD §3.4: "While a report is `DRAFT` or `RETURNED`, the owning
        prime may replace its `lines` wholesale via the report-replacement
        capability; attempting that replacement on a report in any other state
        is rejected with `ERR_REPORT_NOT_EDITABLE`."
        PRD §3.4: "On approval the report moves from `SUBMITTED` to `APPROVED`
        and `reviewed_by_user_id` is stamped."

        Design: Difficulty/non_linear_state_machine/tier2_report_return_correction_cycle
        """
        _bu, prime, diverse, report = self._setup_returned_report(api)
        submit_tier2_report(report["id"], prime["id"])
        get_success_data(
            api.return_tier2_report(report["id"], "missing PO detail",
                                    ANALYST1))
        replaced = validate_success(api.replace_tier2_lines(
            report["id"],
            replace_lines_payload([tier2_line(diverse["id"], 50000, 100.00)]),
            make_prime_contact_headers(prime["id"])))
        assert replaced["total_diverse_tier2_cents"] == 50000, (
            "PUT replaced the line wholesale: 100.00% of 50000"
        )
        submit_tier2_report(report["id"], prime["id"])
        approved = validate_success(
            api.approve_tier2_report(report["id"], ADMIN1))
        assert approved["status"] == "APPROVED"
        assert approved["total_diverse_tier2_cents"] == 50000
        assert approved["total_subcontracted_cents"] == 50000, (
            "Approved totals reflect only the corrected submission, not the "
            "returned 40000"
        )
        assert approved["reviewed_by_user_id"] == "admin-1"


class TestApprovalEligibility:
    def test_tier2_report_for_non_prime_returns_prime_only(self, api):
        """PRD §3.4: "The `prime_supplier_id` must equal the caller's
        `X-User-ID` — a `PrimeContact` filing for any other prime receives
        `ERR_FORBIDDEN_FOR_ROLE` — and the referenced supplier's `kind` must
        be `PRIME` or `BOTH`, otherwise `ERR_PRIME_ONLY`."

        Design: Corner/validations/tier2_report_for_non_prime_returns_prime_only
        """
        bu = create_business_unit()
        supplier = create_supplier(legal_name="Diverse Only Co", tax_id="T-DO",
                                   kind="DIVERSE")
        payload = {
            "prime_supplier_id": supplier["id"],
            "business_unit_id": bu["id"],
            "reporting_period": "2026-Q1",
            "lines": [tier2_line(supplier["id"], 10000, 100.00)],
        }
        # Ownership passes (caller IS that supplier); the kind check fires.
        resp = api.create_tier2_report(
            payload, make_prime_contact_headers(supplier["id"]))
        validate_error(resp, ApiErrorId.ERR_PRIME_ONLY)

    def test_tier2_approve_requires_cert_covering_period_end(self, api):
        """PRD §3.4: "each `diverse_supplier_id` must reference a supplier
        whose `kind` is `DIVERSE` or `BOTH`, and that supplier must hold a
        certification in `VERIFIED` or `EXPIRED` status whose closed validity
        window covers the reporting period's end date — a `REVOKED`
        certification never qualifies, even if its window would have covered
        the period. A failure on either check is `ERR_SUPPLIER_NOT_ELIGIBLE`."

        Design: Corner/calculations/tier2_approve_requires_cert_covering_period_end
        """
        bu = create_business_unit()
        # The window [2026-01-01, 2026-11-15] verifies at the startup clock
        # date but does not cover the 2026-Q4 period end (2026-12-31).
        diverse, _cert = create_supplier_with_verified_cert(
            legal_name="Short Cert Co", tax_id="T-SHT",
            certificate_number="M-SHT", valid_from="2026-01-01",
            valid_to="2026-11-15")
        prime = create_supplier(legal_name="Prime Build Inc", tax_id="T-PB",
                                kind="PRIME", contact_email="p@x.com")
        report = create_tier2_report(
            prime["id"], bu["id"], reporting_period="2026-Q4",
            lines=[tier2_line(diverse["id"], 100000, 100.00)])
        submit_tier2_report(report["id"], prime["id"])
        resp = api.approve_tier2_report(report["id"], ADMIN1)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_ELIGIBLE)
        stored = validate_success(api.get_tier2_report(report["id"], ADMIN1))
        assert stored["status"] == "SUBMITTED", (
            "The rejected approval leaves the report SUBMITTED"
        )


class TestSupersessionInvariant:
    def _setup_two_reports_same_key(self, api):
        """BU + prime + certified diverse supplier; RA (100000 diverse cents)
        APPROVED, then RB (80000 diverse cents) created and submitted for the
        same (prime, period)."""
        bu = create_business_unit()
        prime = create_supplier(legal_name="Prime Build Inc", tax_id="T-PB",
                                kind="PRIME", contact_email="p@x.com")
        diverse, _cert = create_supplier_with_verified_cert(
            legal_name="Diverse Parts Co", tax_id="T-DP",
            certificate_number="M-DP")
        report_a = create_approved_tier2_report(
            prime["id"], bu["id"], reporting_period="2026-Q1",
            lines=[tier2_line(diverse["id"], 100000, 100.00)])
        report_b = create_tier2_report(
            prime["id"], bu["id"], reporting_period="2026-Q1",
            lines=[tier2_line(diverse["id"], 80000, 100.00)])
        submit_tier2_report(report_b["id"], prime["id"])
        return bu, prime, diverse, report_a, report_b

    def test_tier2_approval_supersedes_prior_approved(self, api):
        """PRD §3.4: "Approval also enforces the exactly-one-approved
        invariant: any other report in `APPROVED` for the same
        `(prime_supplier_id, reporting_period)` pair automatically transitions
        to `SUPERSEDED`."

        Design: Difficulty/compensating_invariant/tier2_approval_supersession_conserves_single_approved
        """
        _bu, prime, _diverse, report_a, report_b = (
            self._setup_two_reports_same_key(api))
        approved_b = validate_success(
            api.approve_tier2_report(report_b["id"], ADMIN1))
        assert approved_b["status"] == "APPROVED"
        stored_a = validate_success(
            api.get_tier2_report(report_a["id"], ADMIN1))
        assert stored_a["status"] == "SUPERSEDED"
        reports, _meta = validate_paginated(api.list_tier2_reports(ADMIN1))
        approved = [r for r in reports
                    if r["prime_supplier_id"] == prime["id"]
                    and r["reporting_period"] == "2026-Q1"
                    and r["status"] == "APPROVED"]
        assert len(approved) == 1, (
            "Exactly one APPROVED report exists per (prime, period) at all "
            "times"
        )
        assert approved[0]["id"] == report_b["id"]

    def test_tier2_supersession_rollup_reflects_sole_approved(self, api):
        """PRD §3.6: "The tier-2 roll-up then sets
        `tier2_diverse_spend_cents` to the sum of `total_diverse_tier2_cents`
        over reports for this business unit and reporting period that are
        currently `APPROVED`."
        PRD §3.4: "Supersession does not mutate any already-generated
        scorecard; the change becomes visible when a scorecard is
        recomputed."

        Design: Difficulty/compensating_invariant/tier2_approval_supersession_conserves_single_approved
        """
        bu, _prime, _diverse, report_a, report_b = (
            self._setup_two_reports_same_key(api))
        scorecard = generate_scorecard(bu["id"], reporting_period="2026-Q1",
                                       attribution_basis="ACCRUAL")
        assert scorecard["tier2_diverse_spend_cents"] == 100000
        get_success_data(api.approve_tier2_report(report_b["id"], ADMIN1))
        snapshot = validate_success(api.get_scorecard(scorecard["id"], ADMIN1))
        assert snapshot["tier2_diverse_spend_cents"] == 100000, (
            "The generated snapshot is not mutated by supersession"
        )
        recomputed = validate_success(
            api.recompute_scorecard(scorecard["id"], ANALYST1))
        assert recomputed["tier2_diverse_spend_cents"] == 80000, (
            "After recompute the roll-up reflects the sole APPROVED report, "
            "never the 180000 sum of both"
        )

    def test_tier2_superseded_report_not_editable(self, api):
        """PRD §3.4: "While a report is `DRAFT` or `RETURNED`, the owning
        prime may replace its `lines` wholesale via the report-replacement
        capability; attempting that replacement on a report in any other state
        is rejected with `ERR_REPORT_NOT_EDITABLE`."

        Design: Corner/state_machines/tier2_superseded_report_not_editable
        """
        _bu, prime, diverse, report_a, report_b = (
            self._setup_two_reports_same_key(api))
        get_success_data(api.approve_tier2_report(report_b["id"], ADMIN1))
        resp = api.replace_tier2_lines(
            report_a["id"],
            replace_lines_payload([tier2_line(diverse["id"], 1, 100.00)]),
            make_prime_contact_headers(prime["id"]))
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_EDITABLE)
