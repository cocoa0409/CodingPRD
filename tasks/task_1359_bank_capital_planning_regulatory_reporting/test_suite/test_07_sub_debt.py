"""Subordinated debt issuances and capital instruments: T2 headroom
arithmetic, the settle cascade, the conserved-headroom invariant, amortization
haircut boundaries, and callability rules."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    add_exposure,
    add_instrument,
    advance_clock_past,
    approve_sub_debt,
    create_bank,
    create_period,
    create_prepared_call_report,
    create_proposed_sub_debt,
    make_capital_analyst_headers,
    set_clock,
    setup_accepted_report,
    setup_priced_sub_debt,
    SUBMITTER_USER_ID,
)


class TestSubDebtGates(object):
    def test_error_maturity_too_short(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.7: "The term must be at least five years for the debt to be
        Tier 2-eligible at issuance — a shorter maturity_years is rejected
        with ERR_MATURITY_TOO_SHORT (HTTP 409)."

        Design: Corner/errors/error_maturity_too_short
        """
        bank, period, report = setup_accepted_report(
            "CH-MAT-001", cet1_cents=10_000_000_000, rwa_cents=100_000_000_000
        )
        issuance = create_proposed_sub_debt(
            bank["id"], proposed_amount_cents=500_000_000, proposed_rate_bps=500,
            maturity_years=3, target_settlement_date="2026-09-01",
        )
        bank_now = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        res = api.approve_sub_debt(
            bank["id"], issuance["id"], {"expected_bank_version": bank_now["version"]},
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_MATURITY_TOO_SHORT)


class TestSubDebtSettleCascade(object):
    def test_settle_creates_instrument_and_refreshes_headroom(self, api, system_operator_headers,
                                                              capital_analyst_headers):
        """PRD §3.7: "A clean settlement moves the issuance to SETTLED,
        creates the corresponding capital instrument with instrument_class T2
        and instrument_subtype SUBORDINATED_DEBT" and "Headroom is recomputed
        at proposal, at approval, on every RWA recomputation, and whenever a
        Tier 2 instrument is called, redeemed, or matures."

        Design: Difficulty/transitive_cascade/sub_debt_settle_cascade_depth_2
        """
        bank, period, report, sd1 = setup_priced_sub_debt(
            "CH-SDB-001", proposed_amount_cents=1_000_000_000, settlement_date="2026-08-15",
            maturity_years=10,
        )
        # RWA 100e9 -> T2 cap 2e9; nothing settled yet -> observer headroom 2e9.
        sd2 = create_proposed_sub_debt(
            bank["id"], proposed_amount_cents=500_000_000, proposed_rate_bps=550,
            maturity_years=7, target_settlement_date="2026-09-01",
        )
        assert sd2["t2_capacity_headroom_cents"] == 2_000_000_000
        set_clock("2026-08-15T12:00:00Z")
        settled = validate_success(api.settle_sub_debt(bank["id"], sd1["id"], capital_analyst_headers))
        assert settled["status"] == "SETTLED"
        assert settled["capital_instrument_id"] is not None
        sd2_now = validate_success(
            api.get_sub_debt_issuance(bank["id"], sd2["id"], capital_analyst_headers)
        )
        # 2e9 cap - 1e9 newly settled T2 = 1e9 headroom on the open proposal.
        assert sd2_now["t2_capacity_headroom_cents"] == 1_000_000_000

    def test_settle_cascade_instrument_matches_proposal_terms(self, api, system_operator_headers,
                                                              capital_analyst_headers):
        """PRD §3.7: "creates the corresponding capital instrument with
        instrument_class T2 and instrument_subtype SUBORDINATED_DEBT,
        outstanding_amount_cents equal to the proposed amount,
        contractual_rate_bps equal to the proposed coupon"

        Design: Difficulty/transitive_cascade/sub_debt_settle_cascade_depth_2
        """
        bank, period, report, sd1 = setup_priced_sub_debt(
            "CH-SDB-002", proposed_amount_cents=1_000_000_000, settlement_date="2026-08-15",
            maturity_years=10,
        )
        set_clock("2026-08-15T12:00:00Z")
        settled = validate_success(api.settle_sub_debt(bank["id"], sd1["id"], capital_analyst_headers))
        instrument = validate_success(
            api.get_capital_instrument(bank["id"], settled["capital_instrument_id"], capital_analyst_headers)
        )
        assert instrument["instrument_class"] == "T2"
        assert instrument["instrument_subtype"] == "SUBORDINATED_DEBT"
        assert instrument["outstanding_amount_cents"] == 1_000_000_000
        assert instrument["contractual_rate_bps"] == 500


class TestHeadroomConservation(object):
    def test_settle_then_call_conserves_t2_headroom(self, api, system_operator_headers,
                                                    capital_analyst_headers):
        """PRD §3.7: "headroom is the greater of zero and the cap minus the
        sum of regulatory_capital_cents over the bank's OUTSTANDING T2
        instruments" and "Headroom is recomputed at proposal, at approval, on
        every RWA recomputation, and whenever a Tier 2 instrument is called,
        redeemed, or matures."

        Design: Difficulty/compensating_invariant/sub_debt_settle_then_call_conserves_t2_headroom
        """
        bank, period, report, sd1 = setup_priced_sub_debt(
            "CH-CP2-001", proposed_amount_cents=800_000_000, settlement_date="2026-08-15",
            maturity_years=10,
        )
        observer = create_proposed_sub_debt(
            bank["id"], proposed_amount_cents=100_000_000, proposed_rate_bps=600,
            maturity_years=5, target_settlement_date="2026-09-01",
        )
        assert observer["t2_capacity_headroom_cents"] == 2_000_000_000
        set_clock("2026-08-15T12:00:00Z")
        settled = validate_success(api.settle_sub_debt(bank["id"], sd1["id"], capital_analyst_headers))
        after_settle = validate_success(
            api.get_sub_debt_issuance(bank["id"], observer["id"], capital_analyst_headers)
        )
        assert after_settle["t2_capacity_headroom_cents"] == 1_200_000_000
        # Calling the settled instrument removes it from OUTSTANDING -> headroom restored.
        validate_success(
            api.call_capital_instrument(bank["id"], settled["capital_instrument_id"], capital_analyst_headers)
        )
        after_call = validate_success(
            api.get_sub_debt_issuance(bank["id"], observer["id"], capital_analyst_headers)
        )
        assert after_call["t2_capacity_headroom_cents"] == 2_000_000_000

    def test_settle_consumes_headroom_visible_on_observer(self, api, system_operator_headers,
                                                          capital_analyst_headers):
        """PRD §3.7: "the cap is 2 percent of the bank's most recently
        accepted RWA — the rwa_cents of its latest ACCEPTED call report ...
        computed as that RWA times 200 over 10000 and floored, and headroom is
        the greater of zero and the cap minus the sum of
        regulatory_capital_cents over the bank's OUTSTANDING T2 instruments."

        Design: Difficulty/compensating_invariant/sub_debt_settle_then_call_conserves_t2_headroom
        """
        # Second observation of the same conserved quantity with a different
        # bank: settle 800e6 against a 2e9 cap -> observer headroom 1.2e9.
        bank, period, report, sd1 = setup_priced_sub_debt(
            "CH-CP2-002", proposed_amount_cents=800_000_000, settlement_date="2026-08-15",
            maturity_years=10,
        )
        observer = create_proposed_sub_debt(
            bank["id"], proposed_amount_cents=100_000_000, proposed_rate_bps=600,
            maturity_years=5, target_settlement_date="2026-09-01",
        )
        set_clock("2026-08-15T12:00:00Z")
        validate_success(api.settle_sub_debt(bank["id"], sd1["id"], capital_analyst_headers))
        after_settle = validate_success(
            api.get_sub_debt_issuance(bank["id"], observer["id"], capital_analyst_headers)
        )
        # T2 cap = 2% of 100e9 = 2e9; 800e6 now OUTSTANDING -> 1_200_000_000.
        assert after_settle["t2_capacity_headroom_cents"] == 1_200_000_000


class TestDerivedFieldReconciliation(object):
    def test_derived_field_reconciliation_on_instrument_call(self, api, system_operator_headers,
                                                             capital_analyst_headers,
                                                             regulator_reviewer_headers):
        """PRD §3.1: "the two actions share their eligibility rules and their
        aftermath: mdba_cents is recomputed, the Tier 2 headroom on every open
        sub-debt proposal is recomputed, and the bank's version increments."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_on_instrument_call
        """
        bank = create_bank("CH-RCN-001", legal_name="ReconBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(bank["id"], period["id"], exposure_at_default_cents=100_000_000_000)
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000_000)
        t2 = add_instrument(
            bank["id"], instrument_class="T2", instrument_subtype="SUBORDINATED_DEBT",
            outstanding_amount_cents=1_000_000_000, issuance_date="2022-01-15",
            maturity_date="2032-12-31", contractual_rate_bps=500,
        )
        report = create_prepared_call_report(bank["id"], period["id"])
        # Move the period unambiguously to FILING_DUE before submitting.
        advance_clock_past("2026-06-30")
        validate_success(
            api.submit_call_report(
                bank["id"], period["id"], report["id"],
                make_capital_analyst_headers(SUBMITTER_USER_ID),
            )
        )
        validate_success(api.accept_call_report(bank["id"], period["id"], report["id"], regulator_reviewer_headers))
        # T2 cap = 2% of 100e9 = 2e9; 1e9 outstanding -> headroom 1e9.
        sd = create_proposed_sub_debt(
            bank["id"], proposed_amount_cents=500_000_000, proposed_rate_bps=500,
            maturity_years=10, target_settlement_date="2026-09-01",
        )
        assert sd["t2_capacity_headroom_cents"] == 1_000_000_000
        validate_success(api.call_capital_instrument(bank["id"], t2["id"], capital_analyst_headers))
        sd_now = validate_success(
            api.get_sub_debt_issuance(bank["id"], sd["id"], capital_analyst_headers)
        )
        assert sd_now["t2_capacity_headroom_cents"] == 2_000_000_000


class TestInstrumentCallability(object):
    def test_instrument_common_stock_cannot_be_called(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.1: "a COMMON_STOCK instrument can never be called or
        redeemed, and such an attempt is rejected with
        ERR_INSTRUMENT_NOT_CALLABLE (HTTP 409)."

        Design: Corner/state_machines/instrument_common_stock_cannot_be_called
        """
        bank = create_bank("CH-CAL-001", legal_name="CallBank")
        instrument = add_instrument(
            bank["id"], instrument_class="CET1", instrument_subtype="COMMON_STOCK",
            outstanding_amount_cents=1_000_000_000, issuance_date="2020-01-15",
            contractual_rate_bps=0,
        )
        res = api.call_capital_instrument(bank["id"], instrument["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_INSTRUMENT_NOT_CALLABLE)


class TestAmortizationHaircut(object):
    def test_t2_amortization_haircut_at_year_boundary(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.1: "with five or more years remaining the instrument counts
        in full (t2_haircut_pct of 0); at four years the haircut is 20
        percent; at three years, 40; at two, 60; at one, 80; and inside the
        final year the instrument counts for nothing, a 100 percent haircut."

        Design: Corner/calculations/t2_amortization_haircut_at_year_boundary
        """
        bank = create_bank("CH-HRC-001", legal_name="HaircutBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(bank["id"], period["id"], exposure_at_default_cents=100_000_000_000)
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000_000)
        # Period end 2026-06-30; 2030-06-30 is exactly 1461 days = 4 years
        # (365.25-day bucketing) -> 20% haircut.
        i4 = add_instrument(
            bank["id"], instrument_class="T2", instrument_subtype="SUBORDINATED_DEBT",
            outstanding_amount_cents=1_000_000_000, issuance_date="2020-07-01",
            maturity_date="2030-06-30", contractual_rate_bps=500,
        )
        # 2031-07-01 is 1827 days = 5 years -> no haircut.
        i5 = add_instrument(
            bank["id"], instrument_class="T2", instrument_subtype="SUBORDINATED_DEBT",
            outstanding_amount_cents=1_000_000_000, issuance_date="2020-07-01",
            maturity_date="2031-07-01", contractual_rate_bps=500,
        )
        report = create_prepared_call_report(bank["id"], period["id"])
        i4_now = validate_success(
            api.get_capital_instrument(bank["id"], i4["id"], capital_analyst_headers)
        )
        i5_now = validate_success(
            api.get_capital_instrument(bank["id"], i5["id"], capital_analyst_headers)
        )
        assert i4_now["t2_haircut_pct"] == 20
        assert i5_now["t2_haircut_pct"] == 0
        assert i4_now["regulatory_capital_cents"] == 800_000_000
        assert i5_now["regulatory_capital_cents"] == 1_000_000_000
