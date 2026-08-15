"""License renewal/reinstatement/surrender, the logical clock, and CE audit
totals with their determinations."""
from test_helpers import (
    EVALUATOR,
    ApiErrorId,
    add_verified_ce_credit,
    api_client,
    assert_same_instant,
    make_applicant_headers,
    num,
    open_ce_audit,
    post_determination,
    set_clock,
    setup_licensed_applicant,
    transition_audit,
    validate_error,
    validate_success,
)


def _license_with_verified_credits(credits, **applicant_overrides):
    """Licensed applicant plus VERIFIED CE credits.
    credits: list of (category, hours, earned_on)."""
    ctx = setup_licensed_applicant(**applicant_overrides)
    applicant_id = ctx["applicant"]["id"]
    license_id = ctx["license"]["id"]
    credit_ids = [
        add_verified_ce_credit(license_id, applicant_id, category, hours,
                               earned_on)["id"]
        for category, hours, earned_on in credits
    ]
    return ctx, credit_ids


class TestClockDefault:

    def test_license_timestamps_use_default_logical_clock(self):
        """PRD section 2.8: "At server startup the clock reads exactly
        2026-08-01T00:00:00Z, and before any administrative set call the clock
        continues to read that default regardless of real elapsed time."
        PRD section 3.7: "Approval creates the license: `status` `ACTIVE`, a
        server-minted sequential `license_number` used for identity only,
        `issued_on` set to the current clock time, `expires_on` set exactly
        60 months after issuance"

        Design: Corner/cross_cutting_layers/clock_default_is_2026_08_01
        """
        ctx = setup_licensed_applicant(full_name="Kat Ka", email="kat@x.com")
        license_ = ctx["license"]
        assert license_["status"] == "ACTIVE"
        assert_same_instant(license_["issued_on"], "2026-08-01T00:00:00Z",
                            "issued_on")
        assert_same_instant(license_["expires_on"], "2031-08-01T00:00:00Z",
                            "expires_on")


class TestRenewalWindow:

    def test_renewal_before_window_opens_rejected(self):
        """PRD section 3.8: "the current clock time must fall within the
        renewal window that opens 180 days before `expires_on` and closes when
        `expires_on` arrives, inclusive of the opening instant and exclusive
        of expiry (outside the window the request is rejected with
        `ERR_RENEWAL_WINDOW_CLOSED`)"

        Design: Corner/validations/renewal_window_not_open_yet_rejected
        """
        ctx = setup_licensed_applicant(full_name="Jed Je", email="jed@x.com")
        license_ = ctx["license"]
        set_clock("2031-01-01T00:00:00Z")
        resp = api_client.renew_license(
            license_["id"], {"payment_token": "tok_2"},
            make_applicant_headers(ctx["applicant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)
        fetched = validate_success(api_client.get_license(license_["id"], EVALUATOR))
        assert fetched["status"] == "ACTIVE"

    def test_surrendered_license_rejects_renewal(self):
        """PRD section 3.8: "surrender by the owning `Applicant` moves an
        `ACTIVE` license to `SURRENDERED`"
        PRD section 2.5: "The target entity must be in a state from which the
        requested transition exists, and terminal states reject every
        transition, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/surrendered_license_rejects_renewal
        """
        ctx = setup_licensed_applicant(full_name="Xan Xa", email="xan@x.com")
        license_ = ctx["license"]
        surrendered = validate_success(api_client.surrender_license(
            license_["id"], make_applicant_headers(ctx["applicant"]["id"])))
        assert surrendered["status"] == "SURRENDERED"
        resp = api_client.renew_license(
            license_["id"], {"payment_token": "tok_2"},
            make_applicant_headers(ctx["applicant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = validate_success(api_client.get_license(license_["id"], EVALUATOR))
        assert fetched["status"] == "SURRENDERED"


class TestReinstatement:

    def test_reinstate_after_grace_expired_rejected(self):
        """PRD section 3.8: "Within a grace period ending 730 days after
        `expires_on` — a request after that instant is rejected with
        `ERR_REINSTATE_GRACE_EXPIRED`"

        Design: Corner/validations/reinstate_grace_expired_rejected
        """
        ctx = setup_licensed_applicant(full_name="Vic Vi", email="vic@x.com")
        license_ = ctx["license"]
        set_clock("2034-01-01T00:00:00Z")
        resp = api_client.reinstate_license(
            license_["id"], {"pays_amount_cents": 100},
            make_applicant_headers(ctx["applicant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_REINSTATE_GRACE_EXPIRED)
        fetched = validate_success(api_client.get_license(license_["id"], EVALUATOR))
        assert fetched["status"] == "EXPIRED"

    def test_reinstate_fee_mismatch_rejected(self):
        """PRD section 3.8: "the owner may reinstate by paying the computed
        reinstatement fee in `pays_amount_cents`; any amount other than the
        computed figure is rejected with `ERR_FEE_AMOUNT_MISMATCH`"
        PRD section 3.8: "at most 365 days overdue costs 5,000 cents, and from
        366 up to 730 days overdue costs 15,000 cents. The subtotal is 15,000
        cents of base renewal plus the late fee. The surcharge rate is
        selected by that subtotal: a subtotal below 25,000 cents pays no
        surcharge, a subtotal from 25,000 through 39,999 cents pays 10
        percent, and a subtotal of 40,000 cents or more pays 20 percent."

        Design: Corner/validations/reinstate_fee_mismatch_rejected
        """
        ctx = setup_licensed_applicant(full_name="Cid Cy", email="cidc@x.com")
        applicant_id = ctx["applicant"]["id"]
        license_ = ctx["license"]
        # Satisfy the RESTORATION-audit gate first so the amount check is the
        # only violated precondition (PRD section 2.5 places "reinstatement
        # amount equality" among the fiscal rules but never places the
        # audit-existence gate in the pipeline, so a setup violating both
        # would not have a uniquely derivable error).
        for category, hours, earned_on in (
                ("CONTENT", 60, "2029-01-10T00:00:00Z"),
                ("PEDAGOGY", 30, "2029-06-01T00:00:00Z"),
                ("ETHICS", 5, "2030-01-05T00:00:00Z")):
            add_verified_ce_credit(license_["id"], applicant_id, category,
                                   hours, earned_on)
        audit = open_ce_audit(license_["id"], audit_variant="RESTORATION")
        post_determination(audit["id"], audit["version"])
        transition_audit(audit["id"], "UNDER_REVIEW")
        transition_audit(audit["id"], "PASSED")
        set_clock("2032-08-20T00:00:00Z")
        # 385 days overdue: 15000 + 15000 = 30000 subtotal, 10% surcharge ->
        # 33000 due; 32999 must be rejected.
        resp = api_client.reinstate_license(
            license_["id"], {"pays_amount_cents": 32_999},
            make_applicant_headers(applicant_id))
        validate_error(resp, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH)
        fetched = validate_success(api_client.get_license(license_["id"], EVALUATOR))
        assert fetched["status"] == "EXPIRED"

    def test_reinstate_requires_passed_restoration_audit(self):
        """PRD section 3.8: "a `PASSED` audit of `audit_variant` `RESTORATION`
        must exist (else `ERR_AUDIT_NOT_PASSED`)"
        PRD section 3.8: "Successful reinstatement returns the license to
        `ACTIVE`, resets `expires_on` to the current clock time plus 60
        months, and increments `version`."

        Design: Difficulty/cross_entity_state_dependency/reinstate_requires_restoration_audit_passed
        """
        ctx = setup_licensed_applicant(full_name="Ora Or", email="ora@x.com")
        applicant_id = ctx["applicant"]["id"]
        license_id = ctx["license"]["id"]
        set_clock("2032-08-20T00:00:00Z")
        resp = api_client.reinstate_license(
            license_id, {"pays_amount_cents": 33_000},
            make_applicant_headers(applicant_id))
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_PASSED)
        for category, hours, earned_on in (
                ("CONTENT", 60, "2029-01-10T00:00:00Z"),
                ("PEDAGOGY", 30, "2029-06-01T00:00:00Z"),
                ("ETHICS", 5, "2030-01-05T00:00:00Z")):
            add_verified_ce_credit(license_id, applicant_id, category, hours,
                                   earned_on)
        audit = open_ce_audit(license_id, audit_variant="RESTORATION")
        audit = post_determination(audit["id"], audit["version"])
        # RESTORATION caps 90/45/8/15 admit everything: 60 + 30 + 5 = 95.
        assert num(audit["verified_hours"]) == 95
        assert audit["required_hours"] == 90
        transition_audit(audit["id"], "UNDER_REVIEW")
        transition_audit(audit["id"], "PASSED")
        reinstated = validate_success(api_client.reinstate_license(
            license_id, {"pays_amount_cents": 33_000},
            make_applicant_headers(applicant_id)))
        assert reinstated["status"] == "ACTIVE"
        assert_same_instant(reinstated["expires_on"], "2037-08-20T00:00:00Z",
                            "expires_on after reinstatement")

    def test_reinstate_at_exact_grace_boundary_succeeds(self):
        """PRD section 3.8: "Within a grace period ending 730 days after
        `expires_on` — a request after that instant is rejected with
        `ERR_REINSTATE_GRACE_EXPIRED`"
        PRD section 3.8: "The late fee tiers on those days: at most 365 days
        overdue costs 5,000 cents, and from 366 up to 730 days overdue costs
        15,000 cents."

        Design: Difficulty/cross_entity_state_dependency/reinstate_requires_restoration_audit_passed
        """
        ctx = setup_licensed_applicant(full_name="Ora Os", email="oras@x.com")
        applicant_id = ctx["applicant"]["id"]
        license_id = ctx["license"]["id"]
        for category, hours, earned_on in (
                ("CONTENT", 60, "2029-01-10T00:00:00Z"),
                ("PEDAGOGY", 30, "2029-06-01T00:00:00Z"),
                ("ETHICS", 5, "2030-01-05T00:00:00Z")):
            add_verified_ce_credit(license_id, applicant_id, category, hours,
                                   earned_on)
        audit = open_ce_audit(license_id, audit_variant="RESTORATION")
        post_determination(audit["id"], audit["version"])
        transition_audit(audit["id"], "UNDER_REVIEW")
        transition_audit(audit["id"], "PASSED")
        # expires_on 2031-08-01 + 730 days = 2033-07-31 exactly: still within
        # grace ("a request after that instant is rejected").
        set_clock("2033-07-31T00:00:00Z")
        reinstated = validate_success(api_client.reinstate_license(
            license_id, {"pays_amount_cents": 33_000},
            make_applicant_headers(applicant_id)))
        assert reinstated["status"] == "ACTIVE"
        assert_same_instant(reinstated["expires_on"], "2038-07-31T00:00:00Z",
                            "expires_on after boundary reinstatement")


class TestAuditVariantTotals:

    def _ctx_with_ethics_and_content(self, full_name, email):
        return _license_with_verified_credits(
            [("ETHICS", 6, "2026-02-01T00:00:00Z"),
             ("CONTENT", 10, "2027-01-15T00:00:00Z")],
            full_name=full_name, email=email)

    def test_standard_audit_excludes_pre_cycle_credit(self):
        """PRD section 3.8: "Candidate credits are the license's `VERIFIED`
        credits whose `earned_on` falls at or after `cycle_start` and strictly
        before `cycle_end`"
        PRD section 3.8: "The audit's `required_hours` are 60 for a
        `STANDARD` audit and 90 for a `RESTORATION` audit."

        Design: Difficulty/dual_variant_calc/ce_audit_standard_vs_restoration_totals
        """
        ctx, _ = self._ctx_with_ethics_and_content("Ann Able", "ann@x.com")
        audit = open_ce_audit(ctx["license"]["id"], audit_variant="STANDARD")
        audit = post_determination(audit["id"], audit["version"])
        # The ETHICS credit earned 2026-02-01 precedes cycle_start
        # 2026-08-01 and is excluded; only CONTENT 10 counts.
        assert num(audit["verified_hours"]) == 10
        assert audit["required_hours"] == 60

    def test_restoration_audit_lookback_and_raised_caps(self):
        """PRD section 3.8: "a `RESTORATION` audit additionally admits credits
        earned in the 12 months before `cycle_start`."
        PRD section 3.8: "The category caps for a `STANDARD` audit are 30
        hours of `PEDAGOGY`, 60 of `CONTENT`, 5 of `ETHICS`, and 10 of
        `TECHNOLOGY`; a `RESTORATION` audit raises them to 45, 90, 8, and 15
        respectively."

        Design: Difficulty/dual_variant_calc/ce_audit_standard_vs_restoration_totals
        """
        ctx, _ = self._ctx_with_ethics_and_content("Ann Abe", "ann2@x.com")
        license_id = ctx["license"]["id"]
        standard = open_ce_audit(license_id, audit_variant="STANDARD")
        post_determination(standard["id"], standard["version"])
        transition_audit(standard["id"], "UNDER_REVIEW")
        transition_audit(standard["id"], "FAILED")
        restoration = open_ce_audit(license_id, audit_variant="RESTORATION")
        restoration = post_determination(restoration["id"],
                                         restoration["version"])
        # Lookback to 2025-08-01 admits the ETHICS 6h credit; 6 + 10 = 16.
        assert num(restoration["verified_hours"]) == 16
        assert restoration["required_hours"] == 90


class TestAuditTotalsOrdering:

    def test_chronological_fit_or_skip(self):
        """PRD section 3.8: "Candidates are processed in `earned_on` ascending
        order, ties broken by `created_at` ascending, and each credit counts
        only if it fits entirely within the remaining cap of its category —
        otherwise it counts zero rather than partially."

        Design: Corner/calculations/ce_audit_chronological_fit_or_skip_order
        """
        ctx, _ = _license_with_verified_credits(
            [("PEDAGOGY", 20, "2027-01-01T00:00:00Z"),
             ("CONTENT", 40, "2027-03-01T00:00:00Z"),
             ("PEDAGOGY", 15, "2027-06-01T00:00:00Z")],
            full_name="Ivy Iv", email="ivy@x.com")
        audit = open_ce_audit(ctx["license"]["id"], audit_variant="STANDARD")
        audit = post_determination(audit["id"], audit["version"])
        # PEDAGOGY cap 30: the 20h credit fits, the later 15h credit does not
        # (10 remaining) and counts zero; total 40 + 20 = 60.
        assert num(audit["verified_hours"]) == 60

    def test_audit_total_stale_until_next_determination(self):
        """PRD section 3.8: "the `VERIFIED` → `VOIDED` → `VERIFIED` cycle
        preserves pair-invariant audited totals, because open audits are never
        recomputed mid-flight when a credit changes; they wait for the next
        determination."
        PRD section 3.8: "Each determination recomputes `verified_hours` and
        `required_hours` under the rules above and increments the audit's
        `version`, so the latest determination supersedes all earlier totals."

        Design: Corner/cross_cutting_layers/audit_total_stale_until_determination
        """
        ctx, _ = _license_with_verified_credits(
            [("CONTENT", 30, "2027-01-10T00:00:00Z"),
             ("PEDAGOGY", 20, "2027-02-01T00:00:00Z")],
            full_name="Nan Na", email="nan@x.com")
        applicant_id = ctx["applicant"]["id"]
        license_id = ctx["license"]["id"]
        audit = open_ce_audit(license_id, audit_variant="STANDARD")
        audit = post_determination(audit["id"], audit["version"])
        assert num(audit["verified_hours"]) == 50
        add_verified_ce_credit(license_id, applicant_id, "TECHNOLOGY", 10,
                               "2027-04-01T00:00:00Z")
        fetched = validate_success(api_client.get_ce_audit(audit["id"], EVALUATOR))
        assert num(fetched["verified_hours"]) == 50, (
            "stored totals must not move until the next determination")
        refreshed = post_determination(audit["id"], fetched["version"])
        assert num(refreshed["verified_hours"]) == 60

    def test_stale_audit_version_rejected_on_determination(self):
        """PRD section 2.7: "Posting a determination against a CE audit
        requires `expected_ce_audit_version`, carrying the audit's last
        observed `version`; because a newer determination legitimately
        supersedes earlier totals, a stale write is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_audit_version_rejected
        """
        ctx = setup_licensed_applicant(full_name="Mel Me", email="mel@x.com")
        audit = open_ce_audit(ctx["license"]["id"], audit_variant="STANDARD")
        post_determination(audit["id"], audit["version"])
        resp = api_client.post_audit_determination(
            audit["id"], {"expected_ce_audit_version": audit["version"]},
            EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412


class TestAuditReviewLoop:

    _CREDITS_55 = [("CONTENT", 30, "2027-01-10T00:00:00Z"),
                   ("PEDAGOGY", 20, "2027-02-01T00:00:00Z"),
                   ("ETHICS", 5, "2027-03-01T00:00:00Z")]

    def test_audit_pass_with_insufficient_hours_rejected(self):
        """PRD section 3.8: "passing requires `verified_hours` of at least
        `required_hours` per the latest determination (else
        `ERR_AUDIT_HOURS_INSUFFICIENT`) and lands the audit in `PASSED`, its
        terminal state; failing moves it to `FAILED`."

        Design: Corner/validations/audit_pass_with_insufficient_hours_rejected
        """
        ctx, _ = _license_with_verified_credits(
            self._CREDITS_55, full_name="Abe Ab", email="abe@x.com")
        audit = open_ce_audit(ctx["license"]["id"], audit_variant="STANDARD")
        audit = post_determination(audit["id"], audit["version"])
        assert num(audit["verified_hours"]) == 55
        transition_audit(audit["id"], "UNDER_REVIEW")
        resp = api_client.transition_ce_audit(
            audit["id"], {"to_status": "PASSED"}, EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_AUDIT_HOURS_INSUFFICIENT)
        fetched = validate_success(api_client.get_ce_audit(audit["id"], EVALUATOR))
        assert fetched["status"] == "UNDER_REVIEW"

    def test_failed_remediation_loop_reaches_passed(self):
        """PRD section 3.8: "A failed audit enters `REMEDIATION`, and after
        makeup credits the evaluator returns it to `UNDER_REVIEW` — the
        `FAILED` → `REMEDIATION` → `UNDER_REVIEW` loop may repeat until the
        audit passes."

        Design: Difficulty/non_linear_state_machine/ce_audit_failed_remediation_loop
        """
        ctx, _ = _license_with_verified_credits(
            self._CREDITS_55, full_name="Gil Gi", email="gil@x.com")
        applicant_id = ctx["applicant"]["id"]
        license_id = ctx["license"]["id"]
        audit = open_ce_audit(license_id, audit_variant="STANDARD")
        audit = post_determination(audit["id"], audit["version"])
        assert num(audit["verified_hours"]) == 55
        transition_audit(audit["id"], "UNDER_REVIEW")
        transition_audit(audit["id"], "FAILED")
        transition_audit(audit["id"], "REMEDIATION")
        add_verified_ce_credit(license_id, applicant_id, "TECHNOLOGY", 5,
                               "2027-04-01T00:00:00Z")
        audit = transition_audit(audit["id"], "UNDER_REVIEW")
        audit = post_determination(audit["id"], audit["version"])
        assert num(audit["verified_hours"]) == 60
        passed = transition_audit(audit["id"], "PASSED")
        assert passed["status"] == "PASSED"
        assert passed["required_hours"] == 60

    def test_failed_remediation_loop_may_repeat(self):
        """PRD section 3.8: "A failed audit enters `REMEDIATION`, and after
        makeup credits the evaluator returns it to `UNDER_REVIEW` — the
        `FAILED` → `REMEDIATION` → `UNDER_REVIEW` loop may repeat until the
        audit passes."

        Design: Difficulty/non_linear_state_machine/ce_audit_failed_remediation_loop
        """
        ctx, _ = _license_with_verified_credits(
            self._CREDITS_55, full_name="Gil Gj", email="gilj@x.com")
        applicant_id = ctx["applicant"]["id"]
        license_id = ctx["license"]["id"]
        audit = open_ce_audit(license_id, audit_variant="STANDARD")
        post_determination(audit["id"], audit["version"])
        # First loop: fail and re-enter review with no new credits.
        transition_audit(audit["id"], "UNDER_REVIEW")
        transition_audit(audit["id"], "FAILED")
        transition_audit(audit["id"], "REMEDIATION")
        audit = transition_audit(audit["id"], "UNDER_REVIEW")
        assert audit["status"] == "UNDER_REVIEW"
        # Second loop: fail again, then remediate with a makeup credit.
        transition_audit(audit["id"], "FAILED")
        transition_audit(audit["id"], "REMEDIATION")
        add_verified_ce_credit(license_id, applicant_id, "TECHNOLOGY", 5,
                               "2027-04-01T00:00:00Z")
        audit = transition_audit(audit["id"], "UNDER_REVIEW")
        audit = post_determination(audit["id"], audit["version"])
        assert num(audit["verified_hours"]) == 60
        passed = transition_audit(audit["id"], "PASSED")
        assert passed["status"] == "PASSED"


class TestCeCreditVoidReinstateInvariant:

    def test_void_then_reinstate_conserves_audit_total(self):
        """PRD section 3.8: "A `CredentialEvaluator` verifies credits to
        `VERIFIED`, voids them to `VOIDED`, and reinstates a voided credit
        back to `VERIFIED` after appeal — the `VERIFIED` → `VOIDED` →
        `VERIFIED` cycle preserves pair-invariant audited totals, because open
        audits are never recomputed mid-flight when a credit changes; they
        wait for the next determination."

        Design: Difficulty/compensating_invariant/ce_credit_void_reinstate_conserves_audit_total
        """
        ctx, credit_ids = _license_with_verified_credits(
            [("CONTENT", 30, "2027-01-10T00:00:00Z"),
             ("PEDAGOGY", 20, "2027-02-01T00:00:00Z")],
            full_name="Rae Ra", email="rae@x.com")
        audit = open_ce_audit(ctx["license"]["id"], audit_variant="STANDARD")
        audit = post_determination(audit["id"], audit["version"])
        totals = [num(audit["verified_hours"])]
        resp = api_client.transition_ce_credit(
            credit_ids[1], {"to_status": "VOIDED"}, EVALUATOR)
        validate_success(resp)
        audit = post_determination(audit["id"], audit["version"])
        totals.append(num(audit["verified_hours"]))
        resp = api_client.transition_ce_credit(
            credit_ids[1], {"to_status": "VERIFIED"}, EVALUATOR)
        reinstated = validate_success(resp)
        audit = post_determination(audit["id"], audit["version"])
        totals.append(num(audit["verified_hours"]))
        assert totals == [50, 30, 50], (
            f"void + reinstate must conserve the audited total, got {totals}")
        assert reinstated["status"] == "VERIFIED"

    def test_void_all_then_reinstate_all_conserves_audit_total(self):
        """PRD section 3.8: "the `VERIFIED` → `VOIDED` → `VERIFIED` cycle
        preserves pair-invariant audited totals, because open audits are never
        recomputed mid-flight when a credit changes; they wait for the next
        determination."
        PRD section 3.8: "Candidate credits are the license's `VERIFIED`
        credits whose `earned_on` falls at or after `cycle_start` and strictly
        before `cycle_end`"

        Design: Difficulty/compensating_invariant/ce_credit_void_reinstate_conserves_audit_total
        """
        ctx, credit_ids = _license_with_verified_credits(
            [("CONTENT", 30, "2027-01-10T00:00:00Z"),
             ("PEDAGOGY", 20, "2027-02-01T00:00:00Z")],
            full_name="Rae Rb", email="raeb@x.com")
        audit = open_ce_audit(ctx["license"]["id"], audit_variant="STANDARD")
        audit = post_determination(audit["id"], audit["version"])
        totals = [num(audit["verified_hours"])]
        for credit_id in credit_ids:
            resp = api_client.transition_ce_credit(
                credit_id, {"to_status": "VOIDED"}, EVALUATOR)
            validate_success(resp)
        audit = post_determination(audit["id"], audit["version"])
        totals.append(num(audit["verified_hours"]))
        for credit_id in credit_ids:
            resp = api_client.transition_ce_credit(
                credit_id, {"to_status": "VERIFIED"}, EVALUATOR)
            validate_success(resp)
        audit = post_determination(audit["id"], audit["version"])
        totals.append(num(audit["verified_hours"]))
        assert totals == [50, 0, 50], (
            f"voiding both credits then reinstating both must conserve the "
            f"total, got {totals}")


class TestAuditUniqueness:

    def test_second_open_audit_rejected(self):
        """PRD section 3.8: "only one audit may be open at a time per license,
        where open means `INITIATED`, `UNDER_REVIEW`, or `REMEDIATION` — a
        second open audit is rejected with `ERR_AUDIT_ALREADY_OPEN`."

        Design: Corner/validations/second_open_audit_rejected
        """
        ctx = setup_licensed_applicant(full_name="Quin Q", email="quin@x.com")
        open_ce_audit(ctx["license"]["id"], audit_variant="STANDARD")
        resp = api_client.create_ce_audit(
            ctx["license"]["id"], {"audit_variant": "RESTORATION"}, EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_AUDIT_ALREADY_OPEN)
