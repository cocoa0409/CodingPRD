"""The deep termination/expiry cascade: terminate -> prescription VOIDED ->
EBT voided/remaining recompute, and the clock-driven expiry sweep (PRD §3.6).
"""
from test_helpers import (
    validate_success,
    setup_certified_participant,
    setup_certified_with_prescription_and_redemption,
    CLERK,
    CPA,
)

PREG_LINE_ITEMS = [
    {"food_category": "MILK", "requested_units": 6},
    {"food_category": "EGGS", "requested_units": 2},
    {"food_category": "JUICE", "requested_units": 3},
]


class TestTerminateCascadeDepth3:
    def test_terminate_voids_prescription_and_moves_value(self, api):
        """PRD §3.6: "At the second level, every food prescription on this
        certification whose status is ISSUED or REDEEMED_PARTIAL is moved to
        VOIDED. At the third level, each voided prescription moves its remaining
        unredeemed value into the EBT account's voided_value_cents, zeroes the
        corresponding balance_units, and the EBT account recomputes its
        remaining_value_cents".

        Design: Difficulty/transitive_cascade/terminate_to_prescription_to_ebt_depth3
        """
        ctx = setup_certified_with_prescription_and_redemption(
            line_items=PREG_LINE_ITEMS, redeem_category="MILK", redeem_units=4,
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], ssn_last4="2005",
            clock_iso="2026-03-02T00:00:00.000Z",
        )
        rx_id = ctx["prescription"]["id"]
        ebt_id = ctx["ebt_account"]["id"]
        validate_success(api.terminate_certification(ctx["certification"]["id"], CPA))

        rx = validate_success(api.get_food_prescription(rx_id, CPA))
        assert rx["status"] == "VOIDED"
        ebt = validate_success(api.get_ebt_account(ebt_id, CPA))
        # 4 MILK redeemed (1400) leaves 1100 unredeemed -> all moved to voided
        assert ebt["voided_value_cents"] == 1100
        assert ebt["remaining_value_cents"] == 0

    def test_terminate_freezes_ebt_and_terminates_participant(self, api):
        """PRD §3.6: "the certification moves to TERMINATED, the participant moves
        to TERMINATED, the participant's version increments by one".
        PRD §3.6: "the EBT account is then frozen to FROZEN."

        Design: Difficulty/transitive_cascade/terminate_to_prescription_to_ebt_depth3
        """
        ctx = setup_certified_with_prescription_and_redemption(
            line_items=PREG_LINE_ITEMS, redeem_category="MILK", redeem_units=4,
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], ssn_last4="2015",
            clock_iso="2026-03-02T00:00:00.000Z",
        )
        cert = validate_success(api.terminate_certification(ctx["certification"]["id"], CPA))
        assert cert["status"] == "TERMINATED"
        participant = validate_success(api.get_participant(ctx["participant"]["id"], CPA))
        assert participant["status"] == "TERMINATED"
        ebt = validate_success(api.get_ebt_account(ctx["ebt_account"]["id"], CPA))
        assert ebt["status"] == "FROZEN"


def test_certification_expiry_on_clock_advance(api):
    """PRD §3.6: "for each ACTIVE certification whose agency current_utc has
    reached or passed its period_end_utc, the certification moves to EXPIRED.
    Expiry transitions the participant from ACTIVE to TERMINATED and increments
    the participant's version by one, decrements the agency's active_caseload_count
    by one, and freezes the EBT account to FROZEN."

    Design: Corner/state_machines/certification_expiry_on_clock_advance
    """
    # POSTPARTUM cert (180 days) from 2026-01-01; advance clock to 2027-01-01.
    ctx = setup_certified_participant(
        category="POSTPARTUM", adjunctive_program="MEDICAID",
        household_size=2, pregnancy_count=0, risk_factor_codes=["ANEMIA"],
        income_records=[(100000, "MONTHLY")],
        clock_iso="2026-01-01T00:00:00.000Z", ssn_last4="5555",
    )
    agency_id = ctx["agency_id"]
    cert_id = ctx["certification"]["id"]
    p_id = ctx["participant"]["id"]
    validate_success(api.set_current_utc(agency_id, "2027-01-01T00:00:00.000Z", CLERK))
    validate_success(api.advance_expirations(agency_id, CLERK))

    cert = validate_success(api.get_certification(cert_id, CLERK))
    assert cert["status"] == "EXPIRED"
    participant = validate_success(api.get_participant(p_id, CLERK))
    assert participant["status"] == "TERMINATED"
    agency = validate_success(api.get_agency(agency_id, CLERK))
    assert agency["active_caseload_count"] == 0
