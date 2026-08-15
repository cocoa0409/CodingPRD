"""Insurance compliance evaluation, certificate expiry against the logical
clock, the bonding decision, and the issue/execute gates."""
import pytest

from test_helpers import (
    BL,
    OM,
    ADMIN,
    ApiErrorId,
    api_client,
    award_sub,
    create_draft_subcontract,
    create_open_project,
    create_package,
    execute_sub,
    get_success_data,
    issue_sub,
    place_bid,
    publish_package,
    recommend,
    register_compliant_cert,
    setup_awarded_subcontract,
    setup_executed_subcontract,
    setup_issued_subcontract,
    setup_leveling_package,
    validate_error,
    validate_paginated,
    validate_success,
)


def _awarded(name, number, trade_code, **kwargs):
    proj, proj_v = create_open_project(name, number)
    ctx = setup_awarded_subcontract(
        proj["id"], proj_v, name=name, trade_code=trade_code, **kwargs)
    return proj, ctx


class TestInsuranceGatesAtIssue:

    def test_issue_without_any_certificate_rejected(self):
        """PRD section 3.6: "The insurance gate: the subcontract's
        `insurance_status` must be `COMPLIANT`, and each non-compliant
        posture maps to its own error — `MISSING` yields
        `ERR_INSURANCE_MISSING`".

        Design: Corner/validations/issue_without_any_certificate_rejected
        """
        _proj, ctx = _awarded("P-V16", "V16", "V16-26")
        resp = api_client.issue_subcontract(ctx["subcontract"]["id"], BL)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_MISSING)

    def test_issue_with_only_noncompliant_cert_rejected(self):
        """PRD section 3.6: "`NON_COMPLIANT` yields
        `ERR_INSURANCE_NON_COMPLIANT`".

        Design: Corner/validations/issue_with_only_noncompliant_cert_rejected
        """
        _proj, ctx = _awarded("P-V17", "V17", "V17-26")
        sub_id = ctx["subcontract"]["id"]
        validate_success(api_client.create_insurance_certificate(
            sub_id,
            {"certificate_number": "CERT-V17",
             "gl_occurrence_cents": 500_000,
             "gl_aggregate_cents": 2_000_000,
             "auto_cents": 1_000_000,
             "umbrella_cents": 5_000_000,
             "workers_comp": "STATUTORY",
             "ai_endorsed": True, "wos_endorsed": True, "ptd_endorsed": True,
             "pollution_cents": 0, "expires_on": "2027-06-01"},
            BL,
        ), expected_status=201)
        resp = api_client.issue_subcontract(sub_id, BL)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_NON_COMPLIANT)

    def test_insurance_numeric_shortfall_non_compliant(self):
        """PRD section 3.7: "A numeric failure is any of the four liability
        limits on the certificate falling below the corresponding required
        limit".
        PRD section 3.7: "otherwise `NON_COMPLIANT` if any certificate
        evaluated `NON_COMPLIANT`".

        Design: Corner/calculations/insurance_numeric_shortfall_non_compliant
        """
        _proj, ctx = _awarded("P-C5", "C5", "C5-26")
        sub_id = ctx["subcontract"]["id"]
        resp = api_client.create_insurance_certificate(
            sub_id,
            {"certificate_number": "CERT-C5",
             "gl_occurrence_cents": 500_000,
             "gl_aggregate_cents": 2_000_000,
             "auto_cents": 1_000_000,
             "umbrella_cents": 5_000_000,
             "workers_comp": "STATUTORY",
             "ai_endorsed": True, "wos_endorsed": True, "ptd_endorsed": True,
             "pollution_cents": 0, "expires_on": "2027-06-01"},
            BL,
        )
        data = validate_success(resp, expected_status=201)
        assert data["compliance_verdict"] == "NON_COMPLIANT", (
            f"500000 < 1000000 numeric shortfall; endorsements cannot "
            f"compensate, got {data['compliance_verdict']}"
        )
        sub = get_success_data(api_client.get_subcontract(sub_id, BL))
        assert sub["insurance_status"] == "NON_COMPLIANT"


class TestCertificateExpiryVsLogicalClock:

    def _awarded_at_september_clock(self):
        """Project clock advanced to 2026-09-01; package bid window stays
        ahead of the moved clock; subcontract AWARDED at 9000000."""
        proj = get_success_data(api_client.create_project(
            {"name": "P-TO2", "project_number": "TO2",
             "estimated_budget_cents": 50_000_000,
             "buyout_target_savings_pct": 0.05},
            ADMIN,
        ), )
        api_client.open_project(proj["id"], ADMIN)
        resp = api_client.advance_clock(
            proj["id"], {"to_iso8601": "2026-09-01T00:00:00Z"}, ADMIN)
        moved = get_success_data(resp)
        ctx = setup_leveling_package(
            proj["id"], moved["version"], name="TO2", trade_code="TO2-09",
            bid_due_at="2026-10-20T16:00:00Z",
            bids=((9_000_000, "2026-09-15T12:00:00Z"),
                  (9_100_000, "2026-09-15T13:00:00Z")),
            withdraw_last=True,
        )
        sub = create_draft_subcontract(
            ctx["package"]["id"], ctx["bids"][0]["id"], "Upsilon Elec")
        recommend(sub["id"], 9_000_000)
        award_sub(sub["id"])
        return proj, sub

    def test_certificate_expiring_on_clock_date_is_expired(self):
        """PRD section 3.7: "An expiry failure occurs when the certificate's
        `expires_on` date is not strictly after the project logical clock's
        current date: coverage must outlive "today" on the project clock, and
        a certificate expiring exactly on the clock's date is already
        expired."
        PRD section 3.7: "if the expiry check failed the certificate's own
        status moves `ISSUED → EXPIRED`".

        Design: Difficulty/resource_temporal_overlap/insurance_certificate_expired_at_logical_clock_overlap
        """
        _proj, sub = self._awarded_at_september_clock()
        resp = api_client.create_insurance_certificate(
            sub["id"],
            {"certificate_number": "CERT-EXP",
             "gl_occurrence_cents": 1_000_000,
             "gl_aggregate_cents": 2_000_000,
             "auto_cents": 1_000_000,
             "umbrella_cents": 5_000_000,
             "workers_comp": "STATUTORY",
             "ai_endorsed": True, "wos_endorsed": True, "ptd_endorsed": True,
             "pollution_cents": 0, "expires_on": "2026-09-01"},
            BL,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "EXPIRED"
        assert data["compliance_verdict"] == "NON_COMPLIANT", \
            "expires_on equal to the clock date fails the strict rule"

    def test_issue_blocked_then_satisfied_one_day_later(self):
        """PRD section 3.6: "`EXPIRED_CERT_ONLY` yields
        `ERR_INSURANCE_CERT_EXPIRED`".
        PRD section 3.7: "An expiry failure occurs when the certificate's
        `expires_on` date is not strictly after the project logical clock's
        current date".

        Design: Difficulty/resource_temporal_overlap/insurance_certificate_expired_at_logical_clock_overlap
        """
        _proj, sub = self._awarded_at_september_clock()
        validate_success(api_client.create_insurance_certificate(
            sub["id"],
            {"certificate_number": "CERT-EXP",
             "gl_occurrence_cents": 1_000_000,
             "gl_aggregate_cents": 2_000_000,
             "auto_cents": 1_000_000,
             "umbrella_cents": 5_000_000,
             "workers_comp": "STATUTORY",
             "ai_endorsed": True, "wos_endorsed": True, "ptd_endorsed": True,
             "pollution_cents": 0, "expires_on": "2026-09-01"},
            BL,
        ), expected_status=201)
        resp = api_client.issue_subcontract(sub["id"], BL)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_CERT_EXPIRED)

        ok = validate_success(api_client.create_insurance_certificate(
            sub["id"],
            {"certificate_number": "CERT-OK",
             "gl_occurrence_cents": 1_000_000,
             "gl_aggregate_cents": 2_000_000,
             "auto_cents": 1_000_000,
             "umbrella_cents": 5_000_000,
             "workers_comp": "STATUTORY",
             "ai_endorsed": True, "wos_endorsed": True, "ptd_endorsed": True,
             "pollution_cents": 0, "expires_on": "2026-09-02"},
            BL,
        ), expected_status=201)
        assert ok["compliance_verdict"] == "COMPLIANT", \
            "one day of forward coverage satisfies the whole-window rule"
        issued = validate_success(api_client.issue_subcontract(sub["id"], BL))
        assert issued["status"] == "ISSUED"

    def test_cert_expiry_reevaluated_at_execute_after_clock_advance(self):
        """PRD section 2.4: "Advancing the clock re-evaluates certificate
        expiry across the project, so a single clock step can flip
        certificates from `ISSUED` to `EXPIRED` and change subcontract
        `insurance_status` values without any certificate ever being
        re-submitted."
        PRD section 3.6: "Execution — recording the signed subcontract,
        `ISSUED → EXECUTED`, again by a `BuyoutLead` — repeats the insurance
        gate with the same error mapping, because time may have advanced
        between issuance and signature."

        Design: Corner/calculations/cert_expiry_reevaluated_at_execute_after_clock_advance
        """
        proj, proj_v = create_open_project("P-C9", "C9")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="C9", trade_code="C9-26")
        sub = create_draft_subcontract(
            ctx["package"]["id"], ctx["bids"][0]["id"], "X1")
        recommend(sub["id"], 9_000_000)
        award_sub(sub["id"])
        cert = register_compliant_cert(
            sub["id"], certificate_number="CERT-C9", expires_on="2026-06-01")
        assert cert["compliance_verdict"] == "COMPLIANT"
        issue_sub(sub["id"])

        validate_success(api_client.advance_clock(
            proj["id"], {"to_iso8601": "2026-06-15T00:00:00Z"}, ADMIN))

        resp = api_client.execute_subcontract(sub["id"], BL)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_CERT_EXPIRED)
        certs, _meta = validate_paginated(
            api_client.list_insurance_certificates(sub["id"], BL))
        by_id = {c["id"]: c["status"] for c in certs}
        assert by_id[cert["id"]] == "EXPIRED", (
            "after clock advance past expires_on, the certificate flips to "
            "EXPIRED and execute re-evaluates and blocks"
        )


class TestBondingDecision:

    def test_bond_decision_before_award_rejected(self):
        """PRD section 3.7: "The bonding decision is the
        `OperationsManager`'s call, recorded once per subcontract — a second
        active `BondDecision` on the same subcontract is rejected with
        `ERR_BOND_DECISION_LOCKED` — and only while the subcontract is
        `AWARDED` (else `ERR_INVALID_STATE_TRANSITION`)."

        Design: Corner/state_machines/bond_decision_before_award_rejected
        """
        proj, proj_v = create_open_project("P-S9", "S9")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="S9", trade_code="S9-26",
            bonding_policy="PER_TRADE_RISK",
            bids=((1_000_000, "2026-05-15T12:00:00Z"),
                  (1_100_000, "2026-05-15T13:00:00Z")),
        )
        sub = create_draft_subcontract(
            ctx["package"]["id"], ctx["bids"][0]["id"], "H1")
        recommend(sub["id"], 1_000_000)
        resp = api_client.create_bond_decision(
            sub["id"], {"trade_history": "CLEAN"}, OM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_second_bond_decision_rejected(self):
        """PRD section 3.7: "recorded once per subcontract — a second active
        `BondDecision` on the same subcontract is rejected with
        `ERR_BOND_DECISION_LOCKED`".

        Design: Corner/state_machines/second_bond_decision_rejected
        """
        _proj, ctx = _awarded(
            "P-S10", "S10", "S10-26", bonding_policy="PER_TRADE_RISK",
            bid_amount=1_000_000, contract_value_cents=1_000_000)
        sub_id = ctx["subcontract"]["id"]
        first = validate_success(api_client.create_bond_decision(
            sub_id, {"trade_history": "CLEAN"}, OM), expected_status=201)
        # value 1_000_000 < 5_000_000 -> 10; ratio 0.10 <= 0.25 -> 0;
        # CLEAN -> 10; score 20 <= 40 -> NOT_REQUIRED; premium 0
        assert first["trade_risk_score"] == 20
        assert first["decision"] == "NOT_REQUIRED"
        assert first["premium_cents"] == 0
        resp = api_client.create_bond_decision(
            sub_id, {"trade_history": "CLAIMS"}, OM)
        validate_error(resp, ApiErrorId.ERR_BOND_DECISION_LOCKED)

    def test_trade_risk_score_three_factor_threshold(self):
        """PRD section 3.7: "The value component looks at the subcontract's
        `contract_value_cents`: below 5,000,000 cents it contributes 10
        points; at or above 5,000,000 and at or below 10,000,000 cents it
        contributes 20; above 10,000,000 cents it contributes 35. The size
        component divides the subcontract's `contract_value_cents` by the
        package's `estimated_budget_cents`: a ratio at or below 0.25
        contributes 0 points, and anything above contributes 25. The history
        component adds 10 points for a `CLEAN` record and 25 for `CLAIMS`."
        PRD section 3.7: "61 through 85 means `SUBGUARD`."

        Design: Difficulty/combinatorial_formula/trade_risk_score_three_factor_state_dependent_threshold
        """
        _proj, ctx = _awarded(
            "P-CF2", "CF2", "CF2-03", bonding_policy="PER_TRADE_RISK",
            budget=12_000_000, bid_amount=12_000_000,
            contract_value_cents=12_000_000)
        sub_id = ctx["subcontract"]["id"]
        resp = api_client.create_bond_decision(
            sub_id,
            {"trade_history": "CLAIMS",
             "decision_rationale": "large single-trade share with prior claims"},
            OM,
        )
        data = validate_success(resp, expected_status=201)
        # 12_000_000 > 10_000_000 -> 35; ratio 1.0 > 0.25 -> 25;
        # CLAIMS -> 25; total 85
        assert data["trade_risk_score"] == 85
        assert data["decision"] == "SUBGUARD", \
            "score 85 falls in tier 61..85 under PER_TRADE_RISK"

    def test_bond_decision_cascades_premium_and_requirement(self):
        """PRD section 3.7: "The premium quote follows the decision:
        `NOT_REQUIRED` quotes 0 cents; `SURETY_BOND` quotes the
        `contract_value_cents` multiplied by 0.015; `SUBGUARD` quotes it
        multiplied by 0.010 — both rounded half-up to integer cents.
        Recording the decision sets the subcontract's `bonding_requirement`
        to the computed `decision`".

        Design: Difficulty/combinatorial_formula/trade_risk_score_three_factor_state_dependent_threshold
        """
        _proj, ctx = _awarded(
            "P-CF2B", "CF2B", "CF2B-03", bonding_policy="PER_TRADE_RISK",
            budget=12_000_000, bid_amount=12_000_000,
            contract_value_cents=12_000_000)
        sub_id = ctx["subcontract"]["id"]
        data = validate_success(api_client.create_bond_decision(
            sub_id, {"trade_history": "CLAIMS"}, OM), expected_status=201)
        # round_half_up(12_000_000 * 0.010) == 120_000
        assert data["premium_cents"] == 120_000
        sub = get_success_data(api_client.get_subcontract(sub_id, BL))
        assert sub["bonding_requirement"] == "SUBGUARD", \
            "decision cascades onto the subcontract"

    def test_bond_premium_surety_rounding_half_up(self):
        """PRD section 3.7: "`SURETY_BOND` quotes the `contract_value_cents`
        multiplied by 0.015; `SUBGUARD` quotes it multiplied by 0.010 — both
        rounded half-up to integer cents."
        PRD section 3.7: "41 through 60 means `SURETY_BOND`".

        Design: Corner/calculations/bond_premium_surety_rounding_half_up
        """
        _proj, ctx = _awarded(
            "P-C7", "C7", "C7-26", bonding_policy="PER_TRADE_RISK",
            budget=9_000_100, bid_amount=9_000_100,
            contract_value_cents=9_000_100)
        resp = api_client.create_bond_decision(
            ctx["subcontract"]["id"], {"trade_history": "CLEAN"}, OM)
        data = validate_success(resp, expected_status=201)
        # value band 5_000_000..10_000_000 -> 20; ratio 1.0 > 0.25 -> 25;
        # CLEAN -> 10; total 55 in 41..60 -> SURETY_BOND
        assert data["trade_risk_score"] == 55
        assert data["decision"] == "SURETY_BOND"
        # round_half_up(9_000_100 * 0.015) = round_half_up(135_001.50)
        assert data["premium_cents"] == 135_002

    def test_issue_without_bond_decision_rejected(self):
        """PRD section 3.6: "unless the package policy is `WAIVED`, the
        `bonding_requirement` must have been resolved to one of
        `NOT_REQUIRED`, `SURETY_BOND`, or `SUBGUARD` with a recorded
        `BondDecision`; otherwise issuance fails with
        `ERR_BONDING_NOT_SATISFIED`."

        Design: Corner/validations/issue_without_bond_decision_rejected
        """
        _proj, ctx = _awarded(
            "P-V18", "V18", "V18-26", bonding_policy="PER_TRADE_RISK")
        sub_id = ctx["subcontract"]["id"]
        register_compliant_cert(sub_id, certificate_number="CERT-V18")
        resp = api_client.issue_subcontract(sub_id, BL)
        validate_error(resp, ApiErrorId.ERR_BONDING_NOT_SATISFIED)
