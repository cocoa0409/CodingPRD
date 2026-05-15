"""Tariff, VAT, consumption-tax, broker-fee calculation tests and the
advance/reimbursement settlement workflow (PRD §3.8, §3.9, §3.10)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    action_with_version_payload,
    advance_clock_to,
    advance_settlement_payload,
    api_client,
    assert_money_2dp,
    assert_settlement,
    emit_bank_debit,
    emit_bank_debit_payload,
    locate_settlement_for_declaration,
    make_filing_officer_headers,
    make_settlement_officer_headers,
    reset_clock_to_epoch,
    setup_declaration_released_via_emit,
    setup_settlement_in_advanced,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import TEST_EPOCH


# ===========================================================================
# §3.8 — Tariff under MFN (general) rate
# ===========================================================================
class TestTariffCalculation:

    def test_general_tariff_cn_default_rate_low_tier(self, api):
        """PRD §3.8: "for jurisdiction CN the rate is 0.10 for general
        goods ... a base value at most 10000 carries a tier factor of
        1.00 ... The final tariff is the base value multiplied by the
        duty rate multiplied by the tier factor, rounded half-up once
        at the very end to two decimal places."

        Claim: declared=1000 USD, fx=7.20 (USD→CNY), HS=1000xxxx (not
        8517 override), trade=NONE, CN jurisdiction → base=7200,
        rate=0.10, tier=1.00 → tariff = round(7200*0.10*1.00, 2) = 720.00.
        """
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="CNY",
            agreement_currency="USD",
            jurisdiction_code="CN",
            hs_code="10000000",
            country_of_origin="JP",
            trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
        )
        s = ctx["settlement"]
        assert s["tariff_amount"] == pytest.approx(720.00, abs=0.01), (
            f"Expected tariff_amount=720.00; got {s.get('tariff_amount')}"
        )
        assert_money_2dp(s["tariff_amount"], "tariff_amount")

    def test_general_tariff_cn_8517_override_rate(self, api):
        """PRD §3.8: "for jurisdiction CN the rate is 0.10 for general
        goods and 0.05 for HS prefix 8517".

        Claim: HS prefix 8517 in CN under NONE → rate=0.05.
        declared=1000 USD, fx=7.20 → base=7200, tariff = 7200*0.05*1.00 = 360.00.
        """
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="CNY",
            agreement_currency="USD",
            jurisdiction_code="CN",
            hs_code="85171200",
            country_of_origin="JP",
            trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
        )
        s = ctx["settlement"]
        assert s["tariff_amount"] == pytest.approx(360.00, abs=0.01)


# ===========================================================================
# §3.8 — VAT computed off rounded tariff
# ===========================================================================
class TestVATCalculation:

    def test_vat_cn_rate_applied_to_base_plus_tariff(self, api):
        """PRD §3.8: "The VAT is computed off the already-rounded tariff.
        The VAT base is the sum of the base value and the tariff amount,
        and the VAT amount is that base multiplied by the jurisdiction's
        VAT rate — 0.13 for CN".

        Claim: base=7200, tariff=720 (from CN/HS-1000/NONE/1000 USD case),
        vat = round((7200+720) * 0.13, 2) = round(1029.60, 2) = 1029.60.
        """
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="CNY",
            agreement_currency="USD",
            jurisdiction_code="CN",
            hs_code="10000000",
            country_of_origin="JP",
            trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
        )
        s = ctx["settlement"]
        assert s["vat_amount"] == pytest.approx(1029.60, abs=0.01)

    def test_vat_us_zero(self, api):
        """PRD §3.8: "0.00 for US".

        Claim: US jurisdiction → vat_amount = 0.00.
        """
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="USD",
            agreement_currency="USD",
            jurisdiction_code="US",
            hs_code="10000000",
            country_of_origin="JP",
            trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
        )
        s = ctx["settlement"]
        assert s["vat_amount"] == pytest.approx(0.00, abs=0.01)


# ===========================================================================
# §3.8 — Consumption tax — only for specific (jurisdiction, HS) pairs
# ===========================================================================
class TestConsumptionTax:

    def test_consumption_tax_zero_outside_table(self, api):
        """PRD §3.8: "pairs outside this set produce a consumption tax of zero."

        Claim: CN + HS 8517 (not in CT table) → ct=0.00.
        """
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="85171200",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
        )
        s = ctx["settlement"]
        assert s["consumption_tax_amount"] == pytest.approx(0.00, abs=0.01)

    def test_consumption_tax_cn_spirits(self, api):
        """PRD §3.8: "(CN, 2208) at 0.20 ... When a pair is in the table,
        the consumption-tax base is the sum of the base value and the
        tariff amount (the VAT is excluded), and the tax is the base
        multiplied by the consumption-tax rate, rounded half-up to two
        decimals."

        Claim: HS 2208 in CN, declared=50 USD (within 25% of ref=50
        CNY-units so declared-value review = ACCEPTED), fx=7.20 →
        base=360, tariff=round(360*0.10*1.00,2)=36.00, ct_base=396,
        ct=round(396*0.20,2)=79.20.
        """
        # Note: HS 2208 in CN is also dangerous-goods (PRD §3.5). The
        # difficulty index instance maps this exact scenario through
        # setup_declaration_released_via_emit + DG decl attached
        # implicitly. Add DANGEROUS_GOODS_DECL as extra doc.
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="22080000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=50.00, declared_currency="USD",
            extra_docs=[{"doc_type": "DANGEROUS_GOODS_DECL"}],
        )
        s = ctx["settlement"]
        assert s["consumption_tax_amount"] == pytest.approx(79.20, abs=0.01)


# ===========================================================================
# §3.10 — Advance funding preconditions
# ===========================================================================
class TestSettlementAdvance:

    def test_advance_succeeds_sums_amounts_and_sets_due_at(self, api):
        """PRD §3.10: "On success, the settlement transitions from FINAL
        to ADVANCED, advance_paid_amount is set to the sum tariff + VAT
        + consumption tax + penalty, advance_paid_at is set to the
        current instant, and reimbursement_due_at is set to the current
        instant plus seven days."

        Claim: after /advance, status=ADVANCED, advance_paid_amount =
        tariff + vat + ct + penalty, reimbursement_due_at populated.
        """
        ctx = setup_settlement_in_advanced(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
        )
        s = ctx["settlement"]
        assert s["status"] == "ADVANCED"
        expected_advance = (
            s["tariff_amount"] + s["vat_amount"] +
            s["consumption_tax_amount"] + s["penalty_amount"]
        )
        assert s["advance_paid_amount"] == pytest.approx(expected_advance, abs=0.01)
        assert s.get("advance_paid_at") is not None
        assert s.get("reimbursement_due_at") is not None

    def test_advance_blocked_when_zero_amount(self, api):
        """PRD §3.10: "the sum of tariff_amount, vat_amount,
        consumption_tax_amount, and penalty_amount must be strictly
        positive (a settlement whose entire bill is zero cannot be
        advanced and is rejected with ERR_SETTLEMENT_ZERO_AMOUNT)".

        Claim: US jurisdiction (vat=0) + HS not in CT + tariff > 0 yields
        non-zero advance, so this test instead targets a configuration
        where total bill = 0. US has vat=0; with declared_value=0 and
        HS not in CT table, tariff = round(0 * 0.08 * 1.00, 2) = 0.
        But the system does not permit declared_value=0 in PRD prose
        sufficiently to act here. Test by attempting to advance a
        zero-tariff settlement constructed deliberately:
        US jurisdiction, declared_value_amount=0.00 USD (declared >= 0
        per PRD §3.3) → base=0, tariff=0, vat=0, ct=0, penalty=0 → all zero.
        """
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="USD", agreement_currency="USD",
            jurisdiction_code="US",
            hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=0.00, declared_currency="USD",
        )
        s = ctx["settlement"]
        # Confirm zero-bill precondition.
        if (s["tariff_amount"] + s["vat_amount"]
                + s["consumption_tax_amount"] + s.get("penalty_amount", 0)) != 0:
            pytest.skip("Could not construct a zero-bill settlement via API")
        resp = api.advance_settlement(
            s["id"], advance_settlement_payload(version=s["version"]),
            TEST_USERS["settlement_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_ZERO_AMOUNT.value)

    def test_advance_segregation_of_duties(self, api):
        """PRD §3.10: "the acting X-User-ID must differ from the X-User-ID
        of the FilingOfficer who filed the declaration, otherwise the
        transition is rejected with ERR_SEGREGATION_OF_DUTIES."

        Claim: SettlementOfficer with the same X-User-ID as the
        FilingOfficer → ERR_SEGREGATION_OF_DUTIES.
        """
        shared_id = "shared-officer-sod"
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
            reviewer_id="reviewer-sod",
            filer_id=shared_id,
        )
        s = ctx["settlement"]
        resp = api.advance_settlement(
            s["id"], advance_settlement_payload(version=s["version"]),
            make_settlement_officer_headers(shared_id),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ===========================================================================
# §3.10 — Late interest boundary + reimbursement flow
# ===========================================================================
class TestLateInterestAndReimbursement:

    def test_no_late_interest_before_due(self, api, broker_ops_headers):
        """PRD §3.10: "While the current instant is at or before
        reimbursement_due_at, late_interest_amount is zero."

        Claim: a settlement just-advanced (now <= due_at) reports
        late_interest_amount = 0.
        """
        reset_clock_to_epoch()
        ctx = setup_settlement_in_advanced(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
        )
        s = ctx["settlement"]
        # Re-read live.
        live = validate_success(api.get_settlement(s["id"], broker_ops_headers))
        assert live["late_interest_amount"] == pytest.approx(0.00, abs=0.01)

    def test_late_interest_one_microsecond_past_due_is_one_day(self, api,
                                                                broker_ops_headers):
        """PRD §3.10: "the number of days late is the ceiling of the
        elapsed seconds divided by 86400 — a partial day still counts
        as a full day, so the moment the instant exceeds the deadline
        by even one microsecond, one full day of interest is owed."

        Claim: advance clock past due_at by the smallest representable
        instant (PRD §2.4 timestamps carry three fractional digits → 1ms
        precision over the wire) → days_late=1 → interest
        = round(advance_paid_amount * rate_per_day * 1, 2).
        """
        reset_clock_to_epoch()
        ctx = setup_settlement_in_advanced(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
        )
        s = ctx["settlement"]
        # advance_paid_amount and rate.
        principal = s["advance_paid_amount"]
        # rate_per_day = 100 / 10000 = 0.01 (PRD: 1% per day).
        rate = 0.01
        due_at_str = s["reimbursement_due_at"]
        from datetime import datetime as _dt
        due_dt = _dt.fromisoformat(due_at_str.replace("Z", "+00:00"))
        # Use 1ms — PRD §2.4 caps timestamp precision at 3 fractional
        # digits, so any sub-millisecond offset is lost on the wire and
        # cannot drive the partial-day-counts-as-one-day rule.
        advance_clock_to(due_dt + timedelta(milliseconds=1))
        live = validate_success(api.get_settlement(s["id"], broker_ops_headers))
        expected = round(principal * rate * 1, 2)
        assert live["late_interest_amount"] == pytest.approx(expected, abs=0.01), (
            f"Expected {expected}, got {live['late_interest_amount']}"
        )

    def test_bank_debit_amount_mismatch(self, api, system_admin_headers):
        """PRD §3.10: "A mismatch — payload amount differing from the
        expected sum — is rejected with ERR_BANK_AMOUNT_MISMATCH and
        HTTP 422."

        Claim: BANK_DEBIT_CONFIRMED with wrong amount → ERR_BANK_AMOUNT_MISMATCH.
        """
        reset_clock_to_epoch()
        ctx = setup_settlement_in_advanced(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
        )
        s = ctx["settlement"]
        resp = api.emit_event(
            emit_bank_debit_payload(
                settlement_id=s["id"],
                amount=s["advance_paid_amount"] + 1.00,
            ),
            system_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BANK_AMOUNT_MISMATCH.value)

    def test_bank_debit_exact_amount_reimburses(self, api, broker_ops_headers,
                                                 system_admin_headers):
        """PRD §3.10: "An exact match advances the settlement from
        ADVANCED to REIMBURSED, sets reimbursed_at to the current
        instant, computes late_interest_amount one final time at the
        reimbursement moment and freezes the value, generates voucher_uri
        by concatenating the literal string 'voucher://' with the
        settlement's id".

        Claim: emit BANK_DEBIT_CONFIRMED with exact amount → status=REIMBURSED,
        voucher_uri starts with 'voucher://'.
        """
        reset_clock_to_epoch()
        ctx = setup_settlement_in_advanced(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
        )
        s = ctx["settlement"]
        emit_bank_debit(s["id"], amount=s["advance_paid_amount"])
        live = validate_success(api.get_settlement(s["id"], broker_ops_headers))
        assert live["status"] == "REIMBURSED"
        voucher = live.get("voucher_uri") or ""
        assert voucher.startswith("voucher://"), (
            f"voucher_uri must start with 'voucher://'; got {voucher!r}"
        )
        assert voucher.endswith(s["id"]), (
            "voucher_uri must end with the settlement id (PRD §3.10)"
        )


# ===========================================================================
# §2.9 — SoD between file and advance
# ===========================================================================
# (Covered in TestSettlementAdvance.test_advance_segregation_of_duties.)


# ===========================================================================
# §3.8 — Currency conversion at pre-validate
# ===========================================================================
class TestFxRateSnapshot:

    def test_fx_rate_one_when_currencies_match(self, api):
        """PRD §2.7: "when the declared and settlement currencies coincide,
        that rate is 1.0."

        Claim: declared=USD, settlement=USD → fx_rate_to_settlement=1.0
        after pre-validate.
        """
        from test_helpers import setup_declaration_in_pre_validated
        ctx = setup_declaration_in_pre_validated(
            default_settlement_currency="USD",
            declared_currency="USD",
        )
        assert ctx["declaration"]["fx_rate_to_settlement"] == 1.0
