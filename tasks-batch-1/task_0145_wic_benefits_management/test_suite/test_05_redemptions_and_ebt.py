"""Redemptions and the EBT ledger: the four redemption gates, the conserved-value
invariant across void, and the empty-balance boundary (PRD §3.8, §3.6).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    assert_ebt_conservation,
    setup_certified_with_prescription,
    setup_certified_with_prescription_and_redemption,
    make_participant_headers,
    make_cpa_headers,
    CLERK,
    CPA,
)

CPA1 = make_cpa_headers("cpa-1")

PREG_LINE_ITEMS = [
    {"food_category": "MILK", "requested_units": 6},
    {"food_category": "EGGS", "requested_units": 2},
    {"food_category": "JUICE", "requested_units": 3},
]


class TestRedemptionGates:
    def test_redeem_while_certification_suspended_rejected(self, api):
        """PRD §3.8: "The certification owning the prescription being drawn against
        must be in ACTIVE status, otherwise the redemption is rejected with
        ERR_CERT_NOT_ACTIVE. The EBT account must be in OPEN status, otherwise
        ERR_EBT_FROZEN."
        PRD §3.6: "Suspension transitions the participant from ACTIVE to SUSPENDED
        and increments the participant's version by one, and it freezes the EBT
        account from OPEN to FROZEN."

        Suspension makes the certification non-ACTIVE AND freezes the EBT in one
        cascade, so both gates fail simultaneously; the PRD lists them adjacently
        without pinning which pre-empts, so either rejection is contract-faithful.

        Design: Difficulty/cross_entity_state_dependency/redemption_requires_certification_active
        """
        ctx = setup_certified_with_prescription(
            line_items=[{"food_category": "MILK", "requested_units": 4}],
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], with_vendor=True,
            clock_iso="2026-03-02T00:00:00.000Z", ssn_last4="2008",
        )
        # Suspend the certification: makes cert non-ACTIVE and freezes the EBT.
        validate_success(api.suspend_certification(ctx["certification"]["id"], CPA))
        p_id = ctx["participant"]["id"]
        resp = api.create_redemption(
            {
                "ebt_account_id": ctx["ebt_account"]["id"],
                "vendor_id": ctx["vendor"]["id"],
                "food_category": "MILK",
                "units": 1,
            },
            make_participant_headers(p_id),
        )
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_CERT_NOT_ACTIVE.value, ApiErrorId.ERR_EBT_FROZEN.value],
        )

    def test_redeem_while_certification_terminated_rejected(self, api):
        """PRD §3.8: "The certification owning the prescription being drawn against
        must be in ACTIVE status, otherwise the redemption is rejected with
        ERR_CERT_NOT_ACTIVE. The EBT account must be in OPEN status, otherwise
        ERR_EBT_FROZEN."
        PRD §3.6: "each voided prescription moves its remaining unredeemed value
        into the EBT account's voided_value_cents, zeroes the corresponding
        balance_units, and the EBT account recomputes its remaining_value_cents;
        the EBT account is then frozen to FROZEN."

        Termination, like suspension, drives the cert non-ACTIVE and freezes the
        EBT together, so either coupled error is contract-faithful.

        Design: Difficulty/cross_entity_state_dependency/redemption_requires_certification_active
        """
        ctx = setup_certified_with_prescription(
            line_items=[{"food_category": "MILK", "requested_units": 4}],
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], with_vendor=True,
            clock_iso="2026-03-02T00:00:00.000Z", ssn_last4="2018",
        )
        validate_success(api.terminate_certification(ctx["certification"]["id"], CPA))
        p_id = ctx["participant"]["id"]
        resp = api.create_redemption(
            {
                "ebt_account_id": ctx["ebt_account"]["id"],
                "vendor_id": ctx["vendor"]["id"],
                "food_category": "MILK",
                "units": 1,
            },
            make_participant_headers(p_id),
        )
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_CERT_NOT_ACTIVE.value, ApiErrorId.ERR_EBT_FROZEN.value],
        )

    def test_redeem_against_pending_vendor_rejected(self, api):
        """PRD §3.8: "The referenced vendor must exist and be in AUTHORIZED status,
        otherwise ERR_VENDOR_NOT_AUTHORIZED."

        Design: Corner/errors/vendor_not_authorized_redemption
        """
        ctx = setup_certified_with_prescription(
            line_items=[{"food_category": "MILK", "requested_units": 4}],
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], with_vendor=False,
            clock_iso="2026-03-02T00:00:00.000Z", ssn_last4="3333",
        )
        # A PENDING (never authorized) vendor.
        pending_vendor = validate_success(api.create_vendor(
            {"agency_id": ctx["agency_id"], "legal_name": "Pending Vendor",
             "peer_group": "SMALL"},
            CLERK,
        ), 201)
        p_id = ctx["participant"]["id"]
        resp = api.create_redemption(
            {
                "ebt_account_id": ctx["ebt_account"]["id"],
                "vendor_id": pending_vendor["id"],
                "food_category": "MILK",
                "units": 1,
            },
            make_participant_headers(p_id),
        )
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_AUTHORIZED.value)

    def test_redeem_beyond_drained_balance_rejected(self, api):
        """PRD §3.8: "the redeemed units must not exceed the remaining balance_units
        for that food_category, otherwise ERR_INSUFFICIENT_BALANCE."

        Design: Difficulty/boundary_precision_check/empty_balance_zero_unit_redemption_rejected
        """
        # EGGS cap for PREGNANT is 2; issue 2, redeem 2 to drain to 0, then redeem 1.
        ctx = setup_certified_with_prescription_and_redemption(
            line_items=[{"food_category": "EGGS", "requested_units": 2}],
            redeem_category="EGGS", redeem_units=2,
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], ssn_last4="2007",
            clock_iso="2026-03-02T00:00:00.000Z",
        )
        assert ctx["ebt_account"]["balance_units"].get("EGGS", 0) == 0
        p_id = ctx["participant"]["id"]
        resp = api.create_redemption(
            {
                "ebt_account_id": ctx["ebt_account"]["id"],
                "vendor_id": ctx["vendor"]["id"],
                "food_category": "EGGS",
                "units": 1,
            },
            make_participant_headers(p_id),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)

    def test_redeem_exactly_remaining_balance_succeeds_and_completes(self, api):
        """PRD §3.8: "the redeemed units must not exceed the remaining balance_units
        for that food_category".
        PRD §3.8: "the redemption that drains the last remaining unit moves it to
        REDEEMED_FULL."

        Boundary at exactly the remaining balance: a redemption equal to (not above)
        the balance is permitted and drains the prescription to REDEEMED_FULL.

        Design: Difficulty/boundary_precision_check/empty_balance_zero_unit_redemption_rejected
        """
        # EGGS cap for PREGNANT is 2; issue 2, redeem exactly 2 (the boundary).
        ctx = setup_certified_with_prescription(
            line_items=[{"food_category": "EGGS", "requested_units": 2}],
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], with_vendor=True,
            clock_iso="2026-03-02T00:00:00.000Z", ssn_last4="2017",
        )
        p_id = ctx["participant"]["id"]
        rx_id = ctx["prescription"]["id"]
        resp = api.create_redemption(
            {
                "ebt_account_id": ctx["ebt_account"]["id"],
                "vendor_id": ctx["vendor"]["id"],
                "food_category": "EGGS",
                "units": 2,
            },
            make_participant_headers(p_id),
        )
        validate_success(resp, 201)
        rx = validate_success(api.get_food_prescription(rx_id, CPA))
        assert rx["status"] == "REDEEMED_FULL"


class TestEbtConservation:
    def test_value_conserved_across_redeem_and_void(self, api):
        """PRD §3.8: "remaining_value_cents equals issued_value_cents minus
        redeemed_value_cents minus voided_value_cents."
        PRD §3.6: "each voided prescription moves its remaining unredeemed value
        into the EBT account's voided_value_cents, zeroes the corresponding
        balance_units, and the EBT account recomputes its remaining_value_cents".

        Design: Difficulty/compensating_invariant/ebt_value_units_conserved_on_void
        """
        ctx = setup_certified_with_prescription_and_redemption(
            line_items=PREG_LINE_ITEMS, redeem_category="MILK", redeem_units=4,
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], ssn_last4="2010",
            clock_iso="2026-03-02T00:00:00.000Z",
        )
        # terminate voids the remaining unredeemed value
        validate_success(api.terminate_certification(ctx["certification"]["id"], CPA))
        ebt = validate_success(api.get_ebt_account(ctx["ebt_account"]["id"], CPA))
        assert ebt["issued_value_cents"] == 2500
        assert ebt["redeemed_value_cents"] == 1400
        assert ebt["voided_value_cents"] == 1100
        assert ebt["remaining_value_cents"] == 0
        assert_ebt_conservation(ebt)

    def test_redeemed_value_drawdown_and_remaining(self, api):
        """PRD §3.8: "redeemed_value_cents is the cumulative value of redeemed
        units drawn down in chronological order".
        PRD §3.8: "adds the redemption value to the account's redeemed_value_cents,
        and recomputes remaining_value_cents."

        Design: Difficulty/compensating_invariant/ebt_value_units_conserved_on_void
        """
        ctx = setup_certified_with_prescription_and_redemption(
            line_items=PREG_LINE_ITEMS, redeem_category="MILK", redeem_units=4,
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], ssn_last4="2210",
            clock_iso="2026-03-02T00:00:00.000Z",
        )
        ebt = ctx["ebt_account"]
        assert ebt["issued_value_cents"] == 2500
        assert ebt["redeemed_value_cents"] == 1400
        assert ebt["voided_value_cents"] == 0
        assert ebt["remaining_value_cents"] == 1100
        assert_ebt_conservation(ebt)
