"""ExemptionDesignation lifecycle: eligibility, sweep, review cycle, SoD."""
from test_helpers import (
    ApiErrorId,
    alert_in_status,
    approve_exemption,
    create_active_phase_i_exemption,
    get_single_ctr_for_customer,
    get_success_data,
    list_ctrs_for_customer,
    make_officer_headers,
    post_cash_txn,
    request_exemption,
    set_clock,
    setup_branch_and_customer,
    api_client,
    validate_error,
)


class TestPhaseIiEligibilityVariants:
    def test_phase_ii_initial_designation_passes_at_five_days(self, api):
        """PRD §3.6: "The initial-designation variant passes exactly when
        `qualifying_day_count` is at least 5 and `account_age_days` is at least
        60; it does not consult referred alerts."

        Design: Difficulty/dual_variant_calc/phase_ii_eligibility_initial_vs_review_variant
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c1 = create_customer(
            legal_name="Delta Nonlisted Inc", tin="33-3333333",
            customer_type="BUSINESS_NONLISTED", account_opened_date="2025-06-01T00:00:00Z",
        )
        for d in ("2026-07-06", "2026-07-08", "2026-07-10", "2026-07-13", "2026-07-15"):
            post_cash_txn(c1["id"], br1["id"], amount_cents=1_100_000,
                          occurred_at=f"{d}T10:00:00Z")
        ex = request_exemption(c1["id"], phase="PHASE_II", requester_id="officer-a")
        approved = approve_exemption(ex["id"], approver_id="officer-b")
        assert approved["status"] == "ACTIVE"
        assert approved["eligibility_snapshot"]["qualifying_day_count"] == 5

    def test_phase_ii_annual_review_window_ages_out_old_days(self, api):
        """PRD §3.6: "The annual-review variant passes exactly when
        `qualifying_day_count` is at least 5 and `referred_alert_in_window` is
        false—the account-age conjunct drops away, and the referred-alert
        conjunct appears in its place; because the window anchors at the review
        date, the same transaction history can pass at designation and fail at
        review, or vice versa."
        PRD §3.6: "When `outcome` is `FAIL`, the designation moves `REVIEW_DUE →
        REVOKED` with `revocation_reason` set to `REVIEW_FAILED`".

        Design: Difficulty/dual_variant_calc/phase_ii_eligibility_initial_vs_review_variant
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c1 = create_customer(
            legal_name="Delta Nonlisted Inc", tin="33-3333333",
            customer_type="BUSINESS_NONLISTED", account_opened_date="2025-06-01T00:00:00Z",
        )
        for d in ("2026-07-06", "2026-07-08", "2026-07-10", "2026-07-13", "2026-07-15"):
            post_cash_txn(c1["id"], br1["id"], amount_cents=1_100_000,
                          occurred_at=f"{d}T10:00:00Z")
        ex = request_exemption(c1["id"], phase="PHASE_II", requester_id="officer-a")
        approve_exemption(ex["id"], approver_id="officer-b")
        # Sweep flips to REVIEW_DUE
        set_clock("2027-08-02T00:00:00Z")
        ex_now = get_success_data(api_client.get_exemption_designation(ex["id"], headers=make_officer_headers()))
        assert ex_now["status"] == "REVIEW_DUE"
        # Annual-review PASS attempt fails: the July 2026 days aged out of the
        # trailing-365-day window anchored at 2027-08-02.
        resp = api_client.complete_review_exemption(
            ex["id"],
            {"outcome": "PASS", "expected_exemption_version": ex_now["version"]},
            headers=make_officer_headers("officer-c"),
        )
        validate_error(resp, ApiErrorId.ERR_PHASE_II_INELIGIBLE)
        # FAIL outcome succeeds and revokes
        revoked = get_success_data(api_client.complete_review_exemption(
            ex["id"],
            {"outcome": "FAIL", "expected_exemption_version": ex_now["version"]},
            headers=make_officer_headers("officer-c"),
        ))
        assert revoked["status"] == "REVOKED"
        assert revoked["revocation_reason"] == "REVIEW_FAILED"


class TestPhaseIiQualifyingDayCountBoundary:
    def test_five_qualifying_days_passes(self, api):
        """PRD §3.6: "The initial-designation variant passes exactly when
        `qualifying_day_count` is at least 5 and `account_age_days` is at least
        60".

        Design: Difficulty/boundary_precision_check/phase_ii_qualifying_day_count_5_vs_4
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c5 = create_customer(
            legal_name="Five Days Inc", tin="56-5656565",
            customer_type="BUSINESS_NONLISTED", account_opened_date="2026-05-01T00:00:00Z",
        )
        for d in ("2026-07-06", "2026-07-08", "2026-07-10", "2026-07-13", "2026-07-15"):
            post_cash_txn(c5["id"], br1["id"], amount_cents=1_100_000,
                          occurred_at=f"{d}T10:00:00Z")
        ex5 = request_exemption(c5["id"], phase="PHASE_II", requester_id="officer-a")
        approved = approve_exemption(ex5["id"], approver_id="officer-b")
        assert approved["status"] == "ACTIVE"
        assert approved["eligibility_snapshot"]["qualifying_day_count"] == 5
        assert approved["eligibility_snapshot"]["account_age_days"] == 92

    def test_four_qualifying_days_fails(self, api):
        """PRD §3.6: "The initial-designation variant passes exactly when
        `qualifying_day_count` is at least 5 and `account_age_days` is at least
        60".
        PRD §3.6: "For `PHASE_II`, the initial-designation eligibility evaluation
        must pass, surfacing `ERR_PHASE_II_INELIGIBLE` when it does not."

        Design: Difficulty/boundary_precision_check/phase_ii_qualifying_day_count_5_vs_4
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c4 = create_customer(
            legal_name="Four Days Inc", tin="67-6767676",
            customer_type="BUSINESS_NONLISTED", account_opened_date="2026-05-01T00:00:00Z",
        )
        for d in ("2026-07-06", "2026-07-08", "2026-07-10", "2026-07-13"):
            post_cash_txn(c4["id"], br1["id"], amount_cents=1_100_000,
                          occurred_at=f"{d}T10:00:00Z")
        ex4 = request_exemption(c4["id"], phase="PHASE_II", requester_id="officer-a")
        resp = api_client.approve_exemption(ex4["id"], headers=make_officer_headers("officer-b"))
        validate_error(resp, ApiErrorId.ERR_PHASE_II_INELIGIBLE)
        after = get_success_data(api_client.get_exemption_designation(ex4["id"], headers=make_officer_headers()))
        assert after["status"] == "PENDING_REVIEW"


class TestExemptionReviewCycle:
    def test_exemption_review_cycle_active_review_due_active(self, api):
        """PRD §3.6: "When a `SystemAdmin` advances the clock, the sweep
        synchronously transitions every `ACTIVE` designation whose
        `review_due_date` is earlier than the new current date from `ACTIVE` to
        `REVIEW_DUE`."
        PRD §3.6: "A passing review moves the designation `REVIEW_DUE → ACTIVE`:
        `last_reviewed_at` is stamped, `review_due_date` advances 365 days from
        the current date".

        Design: Difficulty/non_linear_state_machine/exemption_review_cycle_active_review_due_active
        """
        set_clock("2026-01-02T09:00:00Z")
        from test_helpers import create_customer
        c1 = create_customer(
            legal_name="City Transit Authority", tin="66-6666666",
            customer_type="GOVERNMENT_AGENCY", account_opened_date="2020-01-01T00:00:00Z",
        )
        ex = create_active_phase_i_exemption(c1["id"])
        # Boundary: clock on the review_due_date itself does NOT flip
        set_clock("2027-01-02T23:00:00Z")
        boundary = get_success_data(api_client.get_exemption_designation(ex["id"], headers=make_officer_headers()))
        assert boundary["status"] == "ACTIVE"
        # Strictly past -> flips
        set_clock("2027-01-03T00:00:00Z")
        due = get_success_data(api_client.get_exemption_designation(ex["id"], headers=make_officer_headers()))
        assert due["status"] == "REVIEW_DUE"
        # Complete the cycle: PASS by a third officer restores ACTIVE
        final = get_success_data(api_client.complete_review_exemption(
            ex["id"],
            {"outcome": "PASS", "expected_exemption_version": due["version"]},
            headers=make_officer_headers("officer-c"),
        ))
        assert final["status"] == "ACTIVE"
        assert final["review_due_date"] == "2028-01-03"

    def test_exemption_sweep_strictly_greater_semantics(self, api):
        """PRD §3.6: "the sweep synchronously transitions every `ACTIVE`
        designation whose `review_due_date` is earlier than the new current date
        from `ACTIVE` to `REVIEW_DUE`."

        Independent confirmation that the comparison is strictly-less-than on
        review_due_date (i.e. equality does not flip).

        Design: Difficulty/non_linear_state_machine/exemption_review_cycle_active_review_due_active
        """
        set_clock("2026-06-15T09:00:00Z")
        from test_helpers import create_customer
        c1 = create_customer(
            legal_name="City Library", customer_type="GOVERNMENT_AGENCY",
            account_opened_date="2020-01-01T00:00:00Z",
        )
        ex = create_active_phase_i_exemption(c1["id"])
        # review_due_date == 2027-06-15
        assert ex["review_due_date"] == "2027-06-15"
        # Advance to exactly the due date — no flip
        set_clock("2027-06-15T12:00:00Z")
        on_due = get_success_data(api_client.get_exemption_designation(ex["id"], headers=make_officer_headers()))
        assert on_due["status"] == "ACTIVE"
        # Advance one day past — flip
        set_clock("2027-06-16T00:00:00Z")
        past_due = get_success_data(api_client.get_exemption_designation(ex["id"], headers=make_officer_headers()))
        assert past_due["status"] == "REVIEW_DUE"


class TestCoverageEvaluationOrder:
    def test_coverage_evaluation_order_circular_pin(self, api):
        """PRD §3.6: "Within that window the evaluation counts
        `qualifying_day_count`, the number of business dates whose aggregation
        row is raw-reportable in the covered direction ignoring any exemption
        coverage—`raw_reportable_in` for a `BUSINESS_NONLISTED` customer,
        `raw_reportable_out` for a `PAYROLL_CUSTOMER`. Because raw reportability
        ignores coverage, this counting never depends on the designation being
        evaluated."

        Design: Difficulty/combinatorial_formula/coverage_evaluation_order_circular_pin
        """
        set_clock("2026-01-02T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c1 = create_customer(
            legal_name="Circular Corp", tin="66-7777777",
            customer_type="BUSINESS_NONLISTED", account_opened_date="2025-06-01T00:00:00Z",
        )
        # Five pre-exemption qualifying days
        for d in ("2025-12-08", "2025-12-10", "2025-12-12", "2025-12-15", "2025-12-17"):
            post_cash_txn(c1["id"], br1["id"], amount_cents=1_100_000,
                          occurred_at=f"{d}T10:00:00Z")
        ex = request_exemption(c1["id"], phase="PHASE_II", requester_id="officer-a")
        approve_exemption(ex["id"], approver_id="officer-b")
        # While exempt: five more qualifying days -> no CTRs (covered)
        set_clock("2026-12-20T09:00:00Z")
        for d in ("2026-12-07", "2026-12-09", "2026-12-11", "2026-12-14", "2026-12-16"):
            post_cash_txn(c1["id"], br1["id"], amount_cents=1_100_000,
                          occurred_at=f"{d}T10:00:00Z")
        _, live_meta = list_ctrs_for_customer(c1["id"], status="DRAFT")
        assert live_meta["total_count"] == 0
        # Sweep flips to REVIEW_DUE; coverage lapses; trailing-45 recompute
        # auto-creates DRAFT CTRs for the December 2026 days.
        set_clock("2027-01-03T00:00:00Z")
        ex_now = get_success_data(api_client.get_exemption_designation(ex["id"], headers=make_officer_headers()))
        assert ex_now["status"] == "REVIEW_DUE"
        # Annual review PASS: the 5 covered December days still count as qualifying
        passed = get_success_data(api_client.complete_review_exemption(
            ex["id"],
            {"outcome": "PASS", "expected_exemption_version": ex_now["version"]},
            headers=make_officer_headers("officer-c"),
        ))
        assert passed["status"] == "ACTIVE"
        assert passed["eligibility_snapshot"]["qualifying_day_count"] == 5
        assert passed["review_due_date"] == "2028-01-03"
        # Coverage restored: the auto-created DRAFT CTRs are voided by the cascade
        _, after_meta = list_ctrs_for_customer(c1["id"], status="DRAFT")
        assert after_meta["total_count"] == 0

    def test_covered_days_do_not_create_ctrs_during_exemption(self, api):
        """PRD §3.4: "Under an active Phase I designation both directions are
        covered, so `ctr_required` is false regardless of the totals."

        Independent confirmation on Phase I (different coverage variant than the
        Phase II instance above).

        Design: Difficulty/combinatorial_formula/coverage_evaluation_order_circular_pin
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c1 = create_customer(
            legal_name="City Hospital", customer_type="GOVERNMENT_AGENCY",
            account_opened_date="2020-01-01T00:00:00Z",
        )
        create_active_phase_i_exemption(c1["id"])
        post_cash_txn(c1["id"], br1["id"], amount_cents=2_000_000,
                      occurred_at="2026-08-01T08:00:00Z")
        _, meta = list_ctrs_for_customer(c1["id"])
        assert meta["total_count"] == 0
        agg = get_single_ctr_for_customer  # silence linters; not used
        from test_helpers import get_aggregation_for
        row = get_aggregation_for(c1["id"], "2026-08-01")
        assert row["raw_reportable_in"] is True
        assert row["covered_in"] is True
        assert row["ctr_required"] is False


class TestExemptionPhaseAndBasis:
    def test_exemption_phase_mismatch_by_customer_type(self, api):
        """PRD §3.6: "The phase must be compatible with the customer's
        `customer_type`: `PHASE_I` is available to `BANK`, `GOVERNMENT_AGENCY`,
        and `BUSINESS_LISTED` customers; `PHASE_II` is available to
        `BUSINESS_NONLISTED` and `PAYROLL_CUSTOMER` customers. An incompatible
        pairing is rejected with `ERR_EXEMPTION_PHASE_MISMATCH`."

        Design: Corner/validations/exemption_phase_mismatch_by_customer_type
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_customer
        ci = create_customer(legal_name="Ind Ivy", customer_type="INDIVIDUAL",
                             account_opened_date="2020-01-01T00:00:00Z")
        cb = create_customer(legal_name="Bank Bros", customer_type="BANK",
                             account_opened_date="2020-01-01T00:00:00Z")
        r1 = api_client.create_exemption_designation(
            ci["id"], {"phase": "PHASE_I"}, headers=make_officer_headers("officer-a"),
        )
        validate_error(r1, ApiErrorId.ERR_EXEMPTION_PHASE_MISMATCH)
        r2 = api_client.create_exemption_designation(
            cb["id"], {"phase": "PHASE_II"}, headers=make_officer_headers("officer-a"),
        )
        validate_error(r2, ApiErrorId.ERR_EXEMPTION_PHASE_MISMATCH)

    def test_phase_i_listed_business_requires_stock_exchange(self, api):
        """PRD §3.6: "For `PHASE_I`, the customer's type must be one of `BANK`,
        `GOVERNMENT_AGENCY`, or `BUSINESS_LISTED`, and a `BUSINESS_LISTED`
        customer must have a non-null `stock_exchange`; failure surfaces
        `ERR_PHASE_I_BASIS_INVALID`."

        Design: Corner/validations/phase_i_listed_business_requires_stock_exchange
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_customer
        c1 = create_customer(
            legal_name="ListCo", tin="31-3131313",
            customer_type="BUSINESS_LISTED", account_opened_date="2020-01-01T00:00:00Z",
        )
        ex1 = request_exemption(c1["id"], phase="PHASE_I", requester_id="officer-a")
        resp = api_client.approve_exemption(ex1["id"], headers=make_officer_headers("officer-b"))
        validate_error(resp, ApiErrorId.ERR_PHASE_I_BASIS_INVALID)
        # Clean up via deny so a corrected request can be submitted
        get_success_data(api_client.deny_exemption(
            ex1["id"], {"reason": "missing exchange"}, headers=make_officer_headers("officer-b"),
        ))
        ex2 = request_exemption(
            c1["id"], phase="PHASE_I", stock_exchange="NYSE", requester_id="officer-a",
        )
        approved = approve_exemption(ex2["id"], approver_id="officer-b")
        assert approved["status"] == "ACTIVE"

    def test_duplicate_active_exemption_rejected(self, api):
        """PRD §3.6: "A customer may hold at most one designation in any of
        `PENDING_REVIEW`, `ACTIVE`, or `REVIEW_DUE`; a request while one exists
        is rejected with `ERR_DUPLICATE_ACTIVE_EXEMPTION`."

        Design: Corner/validations/duplicate_active_exemption_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_customer
        c1 = create_customer(legal_name="Dup City", customer_type="GOVERNMENT_AGENCY",
                             account_opened_date="2020-01-01T00:00:00Z")
        ex1 = request_exemption(c1["id"], phase="PHASE_I", requester_id="officer-a")
        # Second concurrent request rejected
        resp = api_client.create_exemption_designation(
            c1["id"], {"phase": "PHASE_I"}, headers=make_officer_headers("officer-a"),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_EXEMPTION)
        # After denial (terminal), a new request succeeds
        get_success_data(api_client.deny_exemption(
            ex1["id"], {"reason": "duplicate cleanup"}, headers=make_officer_headers("officer-b"),
        ))
        ex2 = get_success_data(api_client.create_exemption_designation(
            c1["id"], {"phase": "PHASE_I"}, headers=make_officer_headers("officer-a"),
        ))
        assert ex2["id"]

    def test_exemption_covers_flags_computed_from_type(self, api):
        """PRD §3.6: "the coverage flags are derived from the phase and customer
        type: `covers_cash_in` is true for `PHASE_I` always and for `PHASE_II`
        only when the customer is `BUSINESS_NONLISTED`; `covers_cash_out` is
        true for `PHASE_I` always and for `PHASE_II` only when the customer is
        `PAYROLL_CUSTOMER`."

        Design: Corner/entities/exemption_covers_flags_computed_from_type
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_customer
        cn = create_customer(legal_name="Nonlisted Ned", customer_type="BUSINESS_NONLISTED",
                             account_opened_date="2025-01-15T00:00:00Z")
        cp = create_customer(legal_name="Payroll Pam", customer_type="PAYROLL_CUSTOMER",
                             account_opened_date="2025-01-15T00:00:00Z")
        cb = create_customer(legal_name="Sister Bank", customer_type="BANK",
                             account_opened_date="2020-01-15T00:00:00Z")
        n = request_exemption(cn["id"], phase="PHASE_II", requester_id="officer-a")
        p = request_exemption(cp["id"], phase="PHASE_II", requester_id="officer-a")
        b = request_exemption(cb["id"], phase="PHASE_I", requester_id="officer-a")
        assert n["covers_cash_in"] is True and n["covers_cash_out"] is False
        assert p["covers_cash_in"] is False and p["covers_cash_out"] is True
        assert b["covers_cash_in"] is True and b["covers_cash_out"] is True
        assert n["status"] == "PENDING_REVIEW"


class TestExemptionApproveGating:
    def test_exemption_approve_gated_by_structuring_alert_state(self, api):
        """PRD §3.6: "Approval is refused while the customer has any structuring
        alert in `OPEN` or `UNDER_REVIEW`, surfacing
        `ERR_OPEN_ALERT_BLOCKS_EXEMPTION`."

        Design: Difficulty/cross_entity_state_dependency/exemption_approve_gated_by_structuring_alert_state
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_customer
        c1 = create_customer(
            legal_name="Port Authority", tin="90-9090909",
            customer_type="GOVERNMENT_AGENCY", account_opened_date="2020-01-01T00:00:00Z",
        )
        alert_in_status(c1["id"], "OPEN", creator_id="officer-z",
                        window_start_date="2026-07-27", window_end_date="2026-07-31",
                        note="teller tip: repeated 9k deposits")
        ex = request_exemption(c1["id"], phase="PHASE_I", requester_id="officer-a")
        resp = api_client.approve_exemption(ex["id"], headers=make_officer_headers("officer-b"))
        validate_error(resp, ApiErrorId.ERR_OPEN_ALERT_BLOCKS_EXEMPTION)
        # Dismiss the alert; the same approve call now succeeds
        # Walk alert: OPEN -> UNDER_REVIEW -> DISMISSED
        alerts_resp = api_client.list_structuring_alerts(
            headers=make_officer_headers(), params={"customer_id": c1["id"]},
        )
        alert_id = alerts_resp.json()["data"][0]["id"]
        from test_helpers import make_analyst_headers
        get_success_data(api_client.begin_review_alert(alert_id, headers=make_analyst_headers("analyst-x")))
        get_success_data(api_client.dismiss_alert(
            alert_id, {"disposition_note": "legitimate payroll pattern"},
            headers=make_officer_headers("officer-z"),
        ))
        approved = approve_exemption(ex["id"], approver_id="officer-b")
        assert approved["status"] == "ACTIVE"

    def test_exemption_approve_unblocked_after_alert_referral(self, api):
        """PRD §3.6: "Approval is refused while the customer has any structuring
        alert in `OPEN` or `UNDER_REVIEW`, surfacing
        `ERR_OPEN_ALERT_BLOCKS_EXEMPTION`."
        PRD §3.7: "referral moves `UNDER_REVIEW → REFERRED` (the terminal state)".

        Independent confirmation: once the alert is terminally REFERRED (no
        longer OPEN/UNDER_REVIEW), the same approve call succeeds.

        Design: Difficulty/cross_entity_state_dependency/exemption_approve_gated_by_structuring_alert_state
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_customer, make_analyst_headers
        c1 = create_customer(
            legal_name="Harbor District", tin="90-9090910",
            customer_type="GOVERNMENT_AGENCY", account_opened_date="2020-01-01T00:00:00Z",
        )
        alert_in_status(c1["id"], "OPEN", creator_id="officer-z",
                        window_start_date="2026-07-27", window_end_date="2026-07-31",
                        note="teller tip")
        ex = request_exemption(c1["id"], phase="PHASE_I", requester_id="officer-a")
        resp = api_client.approve_exemption(ex["id"], headers=make_officer_headers("officer-b"))
        validate_error(resp, ApiErrorId.ERR_OPEN_ALERT_BLOCKS_EXEMPTION)
        # Refer the alert: OPEN -> UNDER_REVIEW -> REFERRED (terminal)
        alerts_resp = api_client.list_structuring_alerts(
            headers=make_officer_headers(), params={"customer_id": c1["id"]},
        )
        alert_id = alerts_resp.json()["data"][0]["id"]
        get_success_data(api_client.begin_review_alert(alert_id, headers=make_analyst_headers("analyst-x")))
        get_success_data(api_client.refer_alert(
            alert_id, {"referral_note": "confirmed pattern"},
            headers=make_officer_headers("officer-z"),
        ))
        # Gate lifted: approve succeeds
        approved = approve_exemption(ex["id"], approver_id="officer-b")
        assert approved["status"] == "ACTIVE"

    def test_open_alert_safety_beats_ineligibility_constraint(self, api):
        """PRD §2.10 step 7: "Business safety: exemption approval is refused while
        the customer has an alert in `OPEN` or `UNDER_REVIEW` (else
        `ERR_OPEN_ALERT_BLOCKS_EXEMPTION`)".
        PRD §2.10 step 8: "Business constraints: phase-to-customer-type
        compatibility (else `ERR_EXEMPTION_PHASE_MISMATCH`), no second live
        designation for the customer (else `ERR_DUPLICATE_ACTIVE_EXEMPTION`),
        Phase I basis (else `ERR_PHASE_I_BASIS_INVALID`), Phase II eligibility
        (else `ERR_PHASE_II_INELIGIBLE`)".
        The two steps are ordered: safety (step 7) fires before constraints (step 8).

        Design: Difficulty/priority_pair_validation_conflict/open_alert_safety_beats_ineligibility_constraint
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        br2 = create_branch(name="West", branch_code="BR2")
        c1 = create_customer(
            legal_name="Risky Business LLC", tin="23-2323232",
            customer_type="BUSINESS_NONLISTED", account_opened_date="2026-06-15T00:00:00Z",
        )
        # structuring pattern -> AUTO alert OPEN
        post_cash_txn(c1["id"], br1["id"], amount_cents=950_000, occurred_at="2026-07-28T10:00:00Z")
        post_cash_txn(c1["id"], br1["id"], amount_cents=100_000, occurred_at="2026-07-29T10:00:00Z")
        post_cash_txn(c1["id"], br2["id"], amount_cents=100_000, occurred_at="2026-07-30T10:00:00Z")
        ex = request_exemption(c1["id"], phase="PHASE_II", requester_id="officer-a")
        # Both safety (open alert) and constraint (0 qualifying days, 47-day age)
        # fail; safety wins by priority.
        resp = api_client.approve_exemption(ex["id"], headers=make_officer_headers("officer-b"))
        validate_error(resp, ApiErrorId.ERR_OPEN_ALERT_BLOCKS_EXEMPTION)
        after = get_success_data(api_client.get_exemption_designation(ex["id"], headers=make_officer_headers()))
        assert after["status"] == "PENDING_REVIEW"

    def test_open_alert_safety_beats_ineligibility_constraint_under_review(self, api):
        """PRD §2.10 step 7: "Business safety: exemption approval is refused while
        the customer has an alert in `OPEN` or `UNDER_REVIEW` (else
        `ERR_OPEN_ALERT_BLOCKS_EXEMPTION`)".
        PRD §2.10 step 8: "Business constraints: phase-to-customer-type
        compatibility (else `ERR_EXEMPTION_PHASE_MISMATCH`), no second live
        designation for the customer (else `ERR_DUPLICATE_ACTIVE_EXEMPTION`),
        Phase I basis (else `ERR_PHASE_I_BASIS_INVALID`), Phase II eligibility
        (else `ERR_PHASE_II_INELIGIBLE`)".
        The two steps are ordered: safety (step 7) fires before constraints (step 8).

        Independent confirmation: an alert in UNDER_REVIEW (the other blocking
        state) also surfaces ERR_OPEN_ALERT_BLOCKS_EXEMPTION before the
        eligibility failure is reported.

        Design: Difficulty/priority_pair_validation_conflict/open_alert_safety_beats_ineligibility_constraint
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c1 = create_customer(
            legal_name="Risky Under Review LLC", tin="23-2323233",
            customer_type="BUSINESS_NONLISTED", account_opened_date="2026-06-15T00:00:00Z",
        )
        # Post small cash activity so an AUTO alert exists; then begin-review it
        post_cash_txn(c1["id"], br1["id"], amount_cents=950_000, occurred_at="2026-07-28T10:00:00Z")
        post_cash_txn(c1["id"], br1["id"], amount_cents=100_000, occurred_at="2026-07-29T10:00:00Z")
        from test_helpers import create_branch
        br2 = create_branch(name="West", branch_code="BR2")
        post_cash_txn(c1["id"], br2["id"], amount_cents=100_000, occurred_at="2026-07-30T10:00:00Z")
        # Move the auto alert OPEN -> UNDER_REVIEW
        alerts = api_client.list_structuring_alerts(
            headers=make_officer_headers(), params={"customer_id": c1["id"]},
        ).json()["data"]
        alert_id = alerts[0]["id"]
        from test_helpers import make_analyst_headers
        get_success_data(api_client.begin_review_alert(alert_id, headers=make_analyst_headers("analyst-x")))
        ex = request_exemption(c1["id"], phase="PHASE_II", requester_id="officer-a")
        # UNDER_REVIEW alert + ineligibility both fail; safety (priority 7) wins
        resp = api_client.approve_exemption(ex["id"], headers=make_officer_headers("officer-b"))
        validate_error(resp, ApiErrorId.ERR_OPEN_ALERT_BLOCKS_EXEMPTION)
        after = get_success_data(api_client.get_exemption_designation(ex["id"], headers=make_officer_headers()))
        assert after["status"] == "PENDING_REVIEW"


class TestExemptionDenyAndTerminalLockdown:
    def test_exemption_deny_and_denied_terminal_lockdown(self, api):
        """PRD §3.6: "Denial is the other exit from review: a `BSAOfficer` other
        than the requester (again enforced via `ERR_SEGREGATION_OF_DUTIES`) may
        deny a `PENDING_REVIEW` designation with a recorded `reason`, moving it
        to the terminal `DENIED` state."
        PRD §2.10 step 6: "the requested action is a valid transition from the
        record's current status (else `ERR_INVALID_STATE_TRANSITION`)".

        Design: Corner/state_machines/exemption_deny_and_denied_terminal_lockdown
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_customer
        c1 = create_customer(legal_name="Denied City", customer_type="GOVERNMENT_AGENCY",
                             account_opened_date="2020-01-01T00:00:00Z")
        ex = request_exemption(c1["id"], phase="PHASE_I", requester_id="officer-a")
        get_success_data(api_client.deny_exemption(
            ex["id"], {"reason": "insufficient documentation"},
            headers=make_officer_headers("officer-b"),
        ))
        resp = api_client.approve_exemption(ex["id"], headers=make_officer_headers("officer-b"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api_client.get_exemption_designation(ex["id"], headers=make_officer_headers()))
        assert after["status"] == "DENIED"
