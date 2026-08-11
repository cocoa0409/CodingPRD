"""Covenant calendar: ratio basis divergence, delinquency sweep ladder,
certificate-accept cure cascade, consent-driven waiver cascade
(PRD §3.3, §3.6)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    CLOCK_START, set_clock,
    create_active_indenture_with_tranche, setup_indenture_with_positions,
    create_obligation, submit_certificate, review_certificate,
    declare_default, confirm_default,
    create_solicitation, open_solicitation, create_open_solicitation,
    cast_ballot, close_solicitation,
    get_obligation, get_indenture, get_default_case,
    get_success_data, make_trust_officer_headers,
)

OFFICER = make_trust_officer_headers("officer-1")


class TestMeasurementBasisDivergence:
    def _setup_dual_basis_obligations(self, api):
        """Two DEBT_SERVICE_COVERAGE obligations (MIN 2.0) differing only in
        measurement_basis; each with a certificate carrying metric_value 1.5
        and ttm_metric_value 2.5."""
        set_clock(CLOCK_START)
        indenture, tranche = create_active_indenture_with_tranche(reset_clock=False)
        ob_ttm = create_obligation(
            indenture["id"], covenant_type="DEBT_SERVICE_COVERAGE",
            frequency="QUARTERLY", period_anchor_date="2026-06-30",
            threshold_value=2.0, threshold_direction="MIN",
            measurement_basis="TTM", grace_period_days=10)
        ob_qa = create_obligation(
            indenture["id"], covenant_type="DEBT_SERVICE_COVERAGE",
            frequency="QUARTERLY", period_anchor_date="2026-06-30",
            threshold_value=2.0, threshold_direction="MIN",
            measurement_basis="QUARTERLY_ANNUALIZED", grace_period_days=10)
        cert_ttm = submit_certificate(
            ob_ttm["id"], issuer_ref="issuer-1", document_ref="doc-1",
            metric_value=1.5, ttm_metric_value=2.5)
        cert_qa = submit_certificate(
            ob_qa["id"], issuer_ref="issuer-1", document_ref="doc-2",
            metric_value=1.5, ttm_metric_value=2.5)
        return {"indenture": indenture, "ob_ttm": ob_ttm, "ob_qa": ob_qa,
                "cert_ttm": cert_ttm, "cert_qa": cert_qa}

    def test_ttm_basis_accepts_certificate(self, api):
        """PRD §3.3: "the metric compared is `ttm_metric_value` when the
        obligation's `measurement_basis` is `TTM` and `metric_value` when it
        is `QUARTERLY_ANNUALIZED`; under direction `MIN` the metric must be at
        least `threshold_value`, under `MAX` it must be at most
        `threshold_value`, and equality passes in both directions."
        PRD §3.3: "On acceptance the certificate becomes `ACCEPTED`,
        `reviewed_by_user_id` records the reviewing officer, and the
        obligation rolls forward: it remains (or returns to) `OPEN` and its
        `next_due_date` advances by one `frequency` interval — the period
        outcome is observable on the certificate and on the advanced due
        date, because the obligation machine is cyclic."

        Design: Difficulty/dual_variant_calc/covenant_ttm_vs_quarterly_annualized_basis
        """
        ctx = self._setup_dual_basis_obligations(api)
        accepted = review_certificate(ctx["cert_ttm"]["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED", "2.5 >= 2.0 on the TTM basis"

        obligation = get_obligation(ctx["ob_ttm"]["id"])
        assert obligation["status"] == "OPEN"
        assert obligation["next_due_date"] == "2026-09-30", (
            "advanced by one QUARTERLY interval from 2026-06-30")

    def test_quarterly_annualized_basis_rejects_same_financials(self, api):
        """PRD §3.3: "A failing metric rejects the acceptance with
        `ERR_COVENANT_RATIO_FAILED` (HTTP 422), and the same submitted
        financials can legitimately pass on one basis and fail on the other."

        Design: Difficulty/dual_variant_calc/covenant_ttm_vs_quarterly_annualized_basis
        """
        ctx = self._setup_dual_basis_obligations(api)
        review_certificate(ctx["cert_ttm"]["id"], "ACCEPT")

        resp = api.review_covenant_certificate(
            ctx["cert_qa"]["id"], {"decision": "ACCEPT"}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_COVENANT_RATIO_FAILED)

        cert_after = get_success_data(
            api.get_covenant_certificate(ctx["cert_qa"]["id"], OFFICER))
        assert cert_after["status"] == "SUBMITTED", (
            "the acceptance is rejected; the certificate is not")


class TestCertificateCureCascade:
    def _setup_breached_obligation(self, api):
        """QUARTERLY FINANCIAL_REPORT obligation anchored 2026-06-30 with
        10-day grace; clock advanced to 2026-07-11 so the sweep breaches it
        and auto-creates an ALLEGED DefaultCase; a late certificate
        submitted."""
        set_clock(CLOCK_START)
        indenture, tranche = create_active_indenture_with_tranche(reset_clock=False)
        obligation = create_obligation(
            indenture["id"], covenant_type="FINANCIAL_REPORT",
            frequency="QUARTERLY", period_anchor_date="2026-06-30",
            grace_period_days=10)
        set_clock("2026-07-11T00:00:00Z")
        cases = get_success_data(api.list_default_cases(
            OFFICER, params={"indenture_id": indenture["id"]}))
        assert len(cases) == 1, "sweep auto-created exactly one default case"
        certificate = submit_certificate(
            obligation["id"], issuer_ref="issuer-1", document_ref="doc-late")
        return {"indenture": indenture, "obligation": obligation,
                "auto_case": cases[0], "certificate": certificate}

    def test_accept_late_certificate_rolls_forward(self, api):
        """PRD §3.3: "Accepting a late certificate returns a `LATE`
        obligation to `OPEN` with the standard roll-forward; accepting a
        certificate while `BREACHED` rolls forward identically"
        PRD §3.3: "computes `is_late`, which is true exactly when the
        submission date falls after the obligation's `next_due_date` as of
        that moment."

        Design: Difficulty/transitive_cascade/covenant_cure_certificate_cascade
        """
        ctx = self._setup_breached_obligation(api)
        assert ctx["certificate"]["is_late"] is True, (
            "submitted 2026-07-11 after next_due_date 2026-06-30")

        reviewed = review_certificate(ctx["certificate"]["id"], "ACCEPT")
        assert reviewed["status"] == "ACCEPTED"

        obligation = get_obligation(ctx["obligation"]["id"])
        assert obligation["status"] == "OPEN", "link 1: roll-forward"
        assert obligation["next_due_date"] == "2026-09-30"

    def test_accept_breached_certificate_cures_default_case(self, api):
        """PRD §3.3: "accepting a certificate while `BREACHED` rolls forward
        identically and additionally cures the linked `ALLEGED` default case
        (the one whose `source_ref` is this obligation), which becomes
        `CURED`"
        PRD §3.3: "The posture itself is derived: `BREACH` when any
        obligation of the indenture is `BREACHED`, else `GRACE` when any is
        `LATE`, else `CURRENT`."

        Design: Difficulty/transitive_cascade/covenant_cure_certificate_cascade
        """
        ctx = self._setup_breached_obligation(api)
        auto_case = ctx["auto_case"]
        assert auto_case["status"] == "ALLEGED"
        assert auto_case["default_type"] == "COVENANT_BREACH"
        assert auto_case["source_ref"] == ctx["obligation"]["id"]

        review_certificate(ctx["certificate"]["id"], "ACCEPT")

        case_after = get_default_case(auto_case["id"])
        assert case_after["status"] == "CURED", "link 2: source_ref match cured"
        indenture = get_indenture(ctx["indenture"]["id"])
        assert indenture["covenant_posture"] == "CURRENT", "link 3: posture recomputed"
        assert indenture["active_default_count"] == 0


class TestConsentWaiverCascade:
    def _setup_waiver_scenario(self, api):
        """OPEN obligation with a manually declared ALLEGED COVENANT_BREACH
        case (source_ref = obligation), and an OPEN WAIVE_COVENANT
        solicitation with A and B consenting."""
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000, 350000000),
            holder_prefixes=("H-A", "H-B"),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 1000000000},
            reset_clock=False)
        obligation = create_obligation(
            ctx["indenture"]["id"], covenant_type="INSURANCE_CERT",
            frequency="ANNUAL", period_anchor_date="2026-12-31",
            grace_period_days=10)
        case = declare_default(ctx["indenture"]["id"],
                               default_type="COVENANT_BREACH",
                               source_ref=obligation["id"])
        solicitation = create_open_solicitation(
            ctx["indenture"]["id"], issuer_ref="issuer-1",
            subject_type="WAIVE_COVENANT", target_obligation_id=obligation["id"],
            consent_threshold_bps=5000, tabulation_basis="CURRENT_OUTSTANDING",
            record_date="2026-06-01", expiry_date="2026-07-01",
            amendment_payload=None)
        cast_ballot(solicitation["id"], ctx["accounts"][0]["id"], "CONSENT")
        cast_ballot(solicitation["id"], ctx["accounts"][1]["id"], "CONSENT")
        ctx.update({"obligation": obligation, "case": case,
                    "solicitation": solicitation})
        return ctx

    def test_waive_covenant_consent_passes_threshold(self, api):
        """PRD §3.6: "The solicitation becomes `PASSED` when the consenting
        weight multiplied by ten thousand is at least `consent_threshold_bps`
        multiplied by the eligible principal — integer cross-multiplication
        with no floating-point division"

        Consenting 750000000 of eligible 750000000 against a 5000 bps
        threshold: 750000000*10000 >= 5000*750000000.

        Design: Difficulty/transitive_cascade/consent_passed_covenant_waiver_cascade
        """
        ctx = self._setup_waiver_scenario(api)
        closed = close_solicitation(ctx["solicitation"]["id"])
        assert closed["status"] == "PASSED"
        assert closed["consenting_principal_cents"] == 750000000

    def test_waive_covenant_consent_waives_obligation_and_case(self, api):
        """PRD §3.6: "`WAIVE_COVENANT` moves the target obligation to
        `WAIVED`, flips any linked `ALLEGED` default case to `WAIVED`, and
        recomputes the indenture's `covenant_posture`"

        Design: Difficulty/transitive_cascade/consent_passed_covenant_waiver_cascade
        """
        ctx = self._setup_waiver_scenario(api)
        close_solicitation(ctx["solicitation"]["id"])

        obligation = get_obligation(ctx["obligation"]["id"])
        assert obligation["status"] == "WAIVED", "link 1: target obligation waived"
        case = get_default_case(ctx["case"]["id"])
        assert case["status"] == "WAIVED", "link 2: linked ALLEGED case waived"
        indenture = get_indenture(ctx["indenture"]["id"])
        assert indenture["covenant_posture"] == "CURRENT", "link 3: posture recomputed"


class TestDelinquencySweepLadder:
    def test_obligation_sweep_late_then_breached(self, api):
        """PRD §3.3: "When the logical clock's date passes an `OPEN`
        obligation's `next_due_date` with no `ACCEPTED` certificate for the
        current period, the obligation becomes `LATE` and the indenture's
        `covenant_posture` is recomputed. When the clock's date passes
        `next_due_date` by more than `grace_period_days`, the obligation
        becomes `BREACHED`, the posture is recomputed again, and a
        `DefaultCase` is auto-created with `default_type` `COVENANT_BREACH`,
        `source_ref` pointing at the obligation, status `ALLEGED`, and a
        `cure_deadline` thirty days out from the sweep."

        Design: Corner/validations/obligation_late_then_breached_sweep_states
        """
        set_clock(CLOCK_START)
        indenture, tranche = create_active_indenture_with_tranche(reset_clock=False)
        obligation = create_obligation(
            indenture["id"], covenant_type="FINANCIAL_REPORT",
            frequency="QUARTERLY", period_anchor_date="2026-06-30",
            grace_period_days=10)

        # Due date + 1 day: LATE, posture GRACE, no default case yet.
        set_clock("2026-07-01T00:00:00Z")
        obligation = get_obligation(obligation["id"])
        assert obligation["status"] == "LATE"
        indenture_now = get_indenture(indenture["id"])
        assert indenture_now["covenant_posture"] == "GRACE"
        cases = get_success_data(api.list_default_cases(
            OFFICER, params={"indenture_id": indenture["id"]}))
        assert len(cases) == 0, "grace period: no default case exists"

        # Due date + 11 days (beyond the 10-day grace): BREACHED + auto case.
        set_clock("2026-07-11T00:00:00Z")
        obligation = get_obligation(obligation["id"])
        assert obligation["status"] == "BREACHED"
        indenture_now = get_indenture(indenture["id"])
        assert indenture_now["covenant_posture"] == "BREACH"
        cases = get_success_data(api.list_default_cases(
            OFFICER, params={"indenture_id": indenture["id"]}))
        assert len(cases) == 1, "exactly one auto-created default case"
        auto_case = cases[0]
        assert auto_case["status"] == "ALLEGED"
        assert auto_case["default_type"] == "COVENANT_BREACH"
        assert auto_case["source_ref"] == obligation["id"]
