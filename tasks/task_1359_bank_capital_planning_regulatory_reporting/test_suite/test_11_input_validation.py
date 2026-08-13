"""Input validation: enum sets, risk-parameter bands, cross-bank reference
integrity, and the prepare-without-exposures gate."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    add_exposure,
    add_instrument,
    create_bank,
    create_period,
    create_risk_exposure_payload,
    create_stress_scenario_payload,
    create_capital_plan_payload,
)


class TestEnumValidation(object):
    def test_risk_exposure_invalid_enum_rejected(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §2.9: "an enum field carrying a value outside its declared set
        — an unknown exposure_class, period_quarter, or instrument_class, for
        instance — is rejected with ERR_INVALID_ENUM_VALUE (HTTP 422)."

        Design: Corner/entities/risk_exposure_invalid_enum_rejected
        """
        bank = create_bank("CH-ENM-001", legal_name="EnumBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        res = api.create_risk_exposure(
            bank["id"], period["id"],
            create_risk_exposure_payload(
                period["id"], exposure_class="BOGUS",
                exposure_at_default_cents=1_000_000, risk_weight_bps=10000,
                obligor_grade="INVESTMENT_GRADE",
            ),
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_ENUM_VALUE)

    def test_reporting_period_invalid_quarter_enum_rejected(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.2: "the period_quarter — one of Q1, Q2, Q3, or Q4" and
        PRD §2.9: "an enum field carrying a value outside its declared set —
        an unknown exposure_class, period_quarter, or instrument_class, for
        instance — is rejected with ERR_INVALID_ENUM_VALUE (HTTP 422)."

        Design: Corner/entities/risk_exposure_invalid_enum_rejected
        """
        bank = create_bank("CH-ENM-002", legal_name="EnumBank2")
        res = api.create_reporting_period(
            bank["id"],
            {"period_end_date": "2026-06-30", "period_year": 2026, "period_quarter": "Q5"},
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_ENUM_VALUE)


class TestRiskParameterBands(object):
    def test_risk_exposure_invalid_risk_weight_band(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.2: "A collateral_haircut_bps may be supplied, defaulting to
        0, and must lie between 0 and 10000 inclusive. A non-positive exposure
        amount, an out-of-band risk weight, or an out-of-range haircut is
        rejected with ERR_INVALID_RISK_PARAMETER (HTTP 422)."

        Design: Corner/entities/risk_exposure_invalid_risk_weight_band
        """
        bank = create_bank("CH-RBD-001", legal_name="RiskBandBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        res = api.create_risk_exposure(
            bank["id"], period["id"],
            create_risk_exposure_payload(
                period["id"], exposure_class="CORPORATE",
                exposure_at_default_cents=1_000_000, risk_weight_bps=10000,
                obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=15000,
            ),
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_RISK_PARAMETER)

    def test_risk_exposure_non_positive_ead_rejected(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.2: "A non-positive exposure amount, an out-of-band risk
        weight, or an out-of-range haircut is rejected with
        ERR_INVALID_RISK_PARAMETER (HTTP 422)."

        Design: Corner/entities/risk_exposure_invalid_risk_weight_band
        """
        bank = create_bank("CH-RBD-002", legal_name="RiskBandBank2")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        res = api.create_risk_exposure(
            bank["id"], period["id"],
            create_risk_exposure_payload(
                period["id"], exposure_class="CORPORATE",
                exposure_at_default_cents=0, risk_weight_bps=10000,
                obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=0,
            ),
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_RISK_PARAMETER)


class TestCrossBankReferences(object):
    def test_cross_bank_fk_reference_rejected(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.5: "A capital plan binds a plan_year, a baseline_period_id,
        and a stress_scenario_id — both references must resolve to entities
        owned by the same bank or creation fails with
        ERR_CROSS_BANK_REFERENCE."

        Design: Corner/entities/cross_bank_fk_reference_rejected
        """
        bank_a = create_bank("CH-XREF-A", legal_name="XRefA")
        bank_b = create_bank("CH-XREF-B", legal_name="XRefB")
        period_a = create_period(bank_a["id"], "2026-06-30", 2026, "Q2")
        scenario_b = validate_success(
            api.create_stress_scenario(
                bank_b["id"], create_stress_scenario_payload(scenario_code="X-B"),
                capital_analyst_headers,
            ),
            201,  # PRD §4: creation operations return 201 Created
        )
        # baseline_period_id belongs to Bank A; the plan is created under Bank B.
        res = api.create_capital_plan(
            bank_b["id"],
            create_capital_plan_payload(
                baseline_period_id=period_a["id"], stress_scenario_id=scenario_b["id"]
            ),
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_CROSS_BANK_REFERENCE)

    def test_cross_bank_scenario_reference_rejected(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §2.9: "Fourth, cross-bank referential integrity of
        body-supplied references — a stress_scenario_id, capital_plan_id,
        baseline_period_id, reporting_period_id, or governing_capital_plan_id
        that points at an entity owned by a different bank is rejected with
        ERR_CROSS_BANK_REFERENCE (HTTP 422)."

        Design: Corner/entities/cross_bank_fk_reference_rejected
        """
        bank_a = create_bank("CH-XREF-C", legal_name="XRefC")
        bank_b = create_bank("CH-XREF-D", legal_name="XRefD")
        period_b = create_period(bank_b["id"], "2026-06-30", 2026, "Q2")
        scenario_a = validate_success(
            api.create_stress_scenario(
                bank_a["id"], create_stress_scenario_payload(scenario_code="X-A"),
                capital_analyst_headers,
            ),
            201,  # PRD §4: creation operations return 201 Created
        )
        # stress_scenario_id belongs to Bank A; the plan is created under Bank B.
        res = api.create_capital_plan(
            bank_b["id"],
            create_capital_plan_payload(
                baseline_period_id=period_b["id"], stress_scenario_id=scenario_a["id"]
            ),
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_CROSS_BANK_REFERENCE)


class TestPrepareGates(object):
    def test_error_no_exposures_on_prepare(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.3: "When the analyst prepares a report, the server first
        requires that at least one risk exposure exists for the period —
        preparing an exposure-less report is rejected with ERR_NO_EXPOSURES
        (HTTP 409)"

        Design: Corner/errors/error_no_exposures_on_prepare
        """
        bank = create_bank("CH-NEX-001", legal_name="NoExpBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000)
        report = validate_success(
            api.create_call_report(bank["id"], period["id"], {}, capital_analyst_headers),
            201,  # PRD §4: creation operations return 201 Created
        )
        res = api.prepare_call_report(bank["id"], period["id"], report["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_NO_EXPOSURES)
