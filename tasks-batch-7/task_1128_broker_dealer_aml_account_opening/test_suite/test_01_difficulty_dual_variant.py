"""Difficulty queue: dual-variant calculations (risk score, SAR deadlines)."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    approve_account,
    begin_investigation,
    create_account,
    create_customer,
    create_rep,
    create_rule,
    create_sar_filing,
    escalate_alert,
    file_sar,
    get_account_version,
    get_sar_filing,
    list_alerts_for_account,
    post_structuring_buys,
    post_wire,
    recommend_sar,
    run_scan,
    set_clock,
    submit_and_verify_document,
    validate_success,
)


class TestAccountRiskScoreInitialVsOngoingVariant:
    def test_initial_variant_stamped_at_creation_and_approval(self, api):
        """PRD §3.3: "These static components are the whole story at creation: the
        `INITIAL` variant of the score adds no activity component at all, and approval
        re-stamps this same `INITIAL` computation, recording `risk_variant_used` as
        `INITIAL`."
        PRD §3.3: "Country contributes 0 points for `LOW`, 10 for `MEDIUM`, or 25 for
        `HIGH`" and "Products add 15 points when `LOW_PRICED_SECURITIES` is present in
        `product_set`" — 25 + 15 = 40, tier MEDIUM (at least 40, below 70).

        Design: Difficulty/dual_variant_calc/account_risk_score_initial_vs_ongoing_variant
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep A", crd_number="CRD-DV1")
        customer = create_customer(
            rep,
            customer_type="INDIVIDUAL",
            full_name="Alice High",
            tax_id="TIN-DV1",
            country_risk_tier="HIGH",
            is_pep=False,
            date_of_birth="1980-01-01",
        )
        submit_and_verify_document(customer["id"], rep, document_number="P-DV1")
        account = create_account(customer["id"], rep, product_set=["LOW_PRICED_SECURITIES"])
        assert account["risk_score"] == 40, (
            f"INITIAL score must be 40 (25 country + 15 product), got {account['risk_score']}"
        )
        assert account["risk_tier"] == "MEDIUM"
        assert account["risk_variant_used"] == "INITIAL"

        approved = approve_account(account["id"])
        assert approved["risk_score"] == 40, "approval re-stamps the INITIAL computation"
        assert approved["risk_tier"] == "MEDIUM"
        assert approved["risk_variant_used"] == "INITIAL"
        assert approved["lifecycle_status"] == "OPEN"

    def test_ongoing_variant_adds_activity_points_on_explicit_recalc(self, api):
        """PRD §3.3: "The **ONGOING** variant, used by explicit recalculation, alert
        escalation, case opening, and 314(a) confirmation, adds an activity component
        on top of the identical static profile — so the same profile scores higher once
        activity exists."
        PRD §3.3: "Activity contributes 5 points per monitoring alert of the account
        currently in `UNDER_REVIEW` or `ESCALATED_TO_CASE` ... plus a velocity-band
        component" and "a ratio of at least four fifths contributes 10 points" —
        40 static + 5 alert + 10 band (85000/100000 = 0.85) = 55, still MEDIUM.
        PRD §3.3: "An explicit recalculation by an `AMLAnalyst` or `ComplianceOfficer`
        runs the `ONGOING` variant, stamps `risk_variant_used` as `ONGOING`".

        Design: Difficulty/dual_variant_calc/account_risk_score_initial_vs_ongoing_variant
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep A", crd_number="CRD-DV1")
        customer = create_customer(
            rep,
            customer_type="INDIVIDUAL",
            full_name="Alice High",
            tax_id="TIN-DV1",
            country_risk_tier="HIGH",
            is_pep=False,
            date_of_birth="1980-01-01",
        )
        submit_and_verify_document(customer["id"], rep, document_number="P-DV1")
        account = create_account(customer["id"], rep, product_set=["LOW_PRICED_SECURITIES"])
        approve_account(account["id"])
        post_wire(account["id"], rep, 60000.00)
        post_wire(account["id"], rep, 25000.00)
        create_rule(rule_code="WIRE_VELOCITY", threshold_amount=80000.00, window_days=30,
                    min_transaction_count=1)
        scan = run_scan()
        assert scan["alerts_created"] == 1, f"Setup failed: scan created {scan['alerts_created']} alerts"
        alert = list_alerts_for_account(account["id"])[0]
        resp = api_client.begin_alert_review(alert["id"], TEST_USERS["analyst_headers"])
        validate_success(resp)

        version = get_account_version(account["id"])
        resp = api_client.recalculate_risk(
            account["id"],
            {"expected_account_version": version},
            TEST_USERS["analyst_headers"],
        )
        recalculated = validate_success(resp)
        assert recalculated["risk_score"] == 55, (
            f"ONGOING score must be 55 (40 static + 5 alert + 10 velocity band), "
            f"got {recalculated['risk_score']}"
        )
        assert recalculated["risk_tier"] == "MEDIUM"
        assert recalculated["risk_variant_used"] == "ONGOING"
        assert recalculated["wire_velocity_30d_amount"] == pytest.approx(85000.00, abs=0.01)


class TestSarDeadlineInitialVsContinuingVariants:
    def _setup_case_sar_recommended(self):
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep B", crd_number="CRD-DV2")
        customer = create_customer(
            rep,
            customer_type="INDIVIDUAL",
            full_name="Bob Low",
            tax_id="TIN-DV2",
            country_risk_tier="LOW",
            is_pep=False,
            date_of_birth="1975-06-15",
        )
        submit_and_verify_document(customer["id"], rep, document_number="P-DV2")
        account = create_account(customer["id"], rep, product_set=["CASH"])
        approve_account(account["id"])
        create_rule(rule_code="STRUCTURING", threshold_amount=10000.00, window_days=2,
                    min_transaction_count=3)
        post_structuring_buys(account["id"], rep)
        run_scan()
        alert = list_alerts_for_account(account["id"])[0]
        resp = api_client.begin_alert_review(alert["id"], TEST_USERS["analyst_headers"])
        validate_success(resp)
        escalation = escalate_alert(alert["id"])
        case_id = escalation["case_id"]
        begin_investigation(case_id)
        recommend_sar(
            case_id,
            analyst_id="analyst-dv2",
            initial_detection_date="2026-05-10",
            recommendation_note="structured buys",
        )
        return {"rep": rep, "account": account, "case_id": case_id}

    def test_initial_filing_deadline_detection_plus_30d(self, api):
        """PRD §3.6: "An *initial* filing — one with no `prior_filing_id` — requires
        its case to be in `SAR_RECOMMENDED`, else `ERR_CASE_NOT_SAR_RECOMMENDED`, and
        its `filing_deadline` is the case's `initial_detection_date` plus thirty
        calendar days."
        PRD §3.6: "Filing stamps `filed_at`, computes `filed_late` (true exactly when
        the filed date is later than the `filing_deadline`), and sets
        `continuing_review_due_date` to the filed date plus ninety calendar days."
        Detection 2026-05-10 -> deadline 2026-06-09; filed 2026-06-01 -> not late;
        review due 2026-08-30.

        Design: Difficulty/dual_variant_calc/sar_deadline_initial_vs_continuing_variants
        """
        ctx = self._setup_case_sar_recommended()
        sar = create_sar_filing(
            ctx["case_id"],
            sar_officer_id="saroff-dv2",
            narrative="Initial SAR",
            activity_start="2026-05-01",
            activity_end="2026-05-01",
        )
        assert sar["status"] == "DRAFT"
        assert sar["filing_deadline"] == "2026-06-09", (
            f"initial deadline must be detection 2026-05-10 + 30d = 2026-06-09, "
            f"got {sar['filing_deadline']}"
        )

        set_clock("2026-06-01T00:00:00Z")
        filed = file_sar(sar["id"], sar_officer_id="saroff-dv2")
        assert filed["status"] == "FILED"
        assert filed["filed_late"] is False, "filed 2026-06-01 is before deadline 2026-06-09"
        assert filed["continuing_review_due_date"] == "2026-08-30", (
            f"filed 2026-06-01 + 90d = 2026-08-30, got {filed['continuing_review_due_date']}"
        )

    def test_continuing_filing_deadline_prior_filed_plus_120d(self, api):
        """PRD §3.6: "The continuing variant's `filing_deadline` is the prior filing's
        `filed_at` date plus one hundred twenty calendar days — a different, later
        anchor than an initial filing for the same detection date."
        PRD §3.6: "When the outcome is `CONTINUING_ACTIVITY`, a new `DRAFT` filing is
        created in the same action with its `prior_filing_id` set to the reviewed filing
        and a deadline one hundred twenty days after that filing's filed date."
        Prior filed 2026-06-01 -> continuing deadline 2026-09-29.

        Design: Difficulty/dual_variant_calc/sar_deadline_initial_vs_continuing_variants
        """
        ctx = self._setup_case_sar_recommended()
        sar1 = create_sar_filing(
            ctx["case_id"],
            sar_officer_id="saroff-dv2",
            narrative="Initial SAR",
            activity_start="2026-05-01",
            activity_end="2026-05-01",
        )
        set_clock("2026-06-01T00:00:00Z")
        file_sar(sar1["id"], sar_officer_id="saroff-dv2")

        resp = api_client.record_continuing_review(
            sar1["id"],
            {
                "outcome": "CONTINUING_ACTIVITY",
                "note": "activity persists",
                "narrative": "Continuing SAR",
                "activity_start": "2026-06-01",
                "activity_end": "2026-08-01",
            },
            TEST_USERS["sar_officer_headers"],
        )
        review_out = validate_success(resp)
        sar2_id = review_out["new_draft_filing_id"]
        assert sar2_id, "CONTINUING_ACTIVITY must create a linked draft filing"

        sar2 = get_sar_filing(sar2_id)
        assert sar2["status"] == "DRAFT"
        assert sar2["prior_filing_id"] == sar1["id"]
        assert sar2["filing_deadline"] == "2026-09-29", (
            f"continuing deadline must be prior filed 2026-06-01 + 120d = 2026-09-29, "
            f"got {sar2['filing_deadline']}"
        )
