"""Dual-variant financial calculations — depth tests.

Owner statements diverge between CASH and ACCRUAL basis on identical underlying
data; deposit settlement runs interest accrual then the deduction waterfall.
"""
import pytest
from test_helpers import get_success_data
from test_helpers.fixtures import (
    PM, create_owner, create_property, create_unit, create_approved_applicant,
    create_draft_lease, collect_deposit, post_rent_charge, post_payment,
    assess_late_fees, create_draft_statement, fund_trust,
)
from test_helpers.api_client import api_client


def _build_collected_world():
    """CA property, mgmt fee 0.08, ACTIVE lease, one 200000 RENT charge for
    2026-06; a 12500 late fee assessed (2026-06-09 sweep would create it but the
    statement instance assesses at 2026-06-09 then pays 150000): 12500 -> late
    fee, 137500 -> rent. Returns (property, lease)."""
    owner = create_owner(management_fee_pct=0.08)
    prop = create_property(owner_id=owner["id"], state_code="CA", reserve_floor_cents=0)
    unit = create_unit(property_id=prop["id"], market_rent_cents=200000)
    app = create_approved_applicant(unit["id"], annual_income_cents=12000000,
                                    credit_score=700, requested_rent_cents=200000,
                                    monthly_debt_cents=50000)
    lease = create_draft_lease(unit["id"], app["id"], start_date="2026-06-01",
                               end_date="2027-06-01", monthly_rent_cents=200000,
                               late_fee_flat_cents=2500, late_fee_pct=0.05,
                               grace_period_days=5)
    collect_deposit(lease["id"], collected_cents=300000, collected_date="2026-06-01")
    signed = get_success_data(api_client.sign_lease(lease["id"], PM))
    post_rent_charge(signed["id"], amount_cents=200000, period_label="2026-06",
                     due_date="2026-06-01")
    assess_late_fees(signed["id"], "2026-06-09")
    post_payment(signed["id"], 150000, received_date="2026-06-10")
    return prop, signed


class TestOwnerStatementBasis:
    def test_cash_basis_nets_collected_rent(self, api):
        """PRD §3.10: "On a cash basis the gross is the sum of the rent actually
        collected in the period — that is, the applied_to_rent_cents of every
        payment on those leases whose received_date falls within the month named
        by the period." PRD §3.10: "The management fee is the gross multiplied by
        the owner's management_fee_pct, rounded half-up to whole cents once on the
        gross total." PRD §3.10: "The net to owner is the gross minus the
        management fee minus the maintenance, floored at zero".

        Of a 150000 payment, 12500 covered the late fee and 137500 was applied to
        rent, so CASH gross 137500, fee round(137500*0.08)=11000, net 126500.

        Design: Difficulty/dual_variant_calc/owner_statement_cash_vs_accrual_diverge
        """
        prop, lease = _build_collected_world()
        stmt = create_draft_statement(prop["id"], period_label="2026-06", basis="CASH")
        finalized = get_success_data(api.finalize_owner_statement(stmt["id"], PM))
        assert finalized["gross_cents"] == 137500
        assert finalized["management_fee_cents"] == 11000
        assert finalized["net_to_owner_cents"] == 126500

    def test_accrual_basis_nets_billed_rent_and_diverges(self, api):
        """PRD §3.10: "On an accrual basis the gross is instead the sum of
        amount_cents over the RENT charges on those leases whose period_label
        equals the statement's period, counting rent that was billed regardless of
        whether it was paid — generally a different figure from the cash gross for
        the same property and period."

        ACCRUAL gross is the billed 200000, fee round(200000*0.08)=16000, net
        184000 — distinct from the 126500 CASH net on identical data.

        Design: Difficulty/dual_variant_calc/owner_statement_cash_vs_accrual_diverge
        """
        prop, lease = _build_collected_world()
        cash = create_draft_statement(prop["id"], period_label="2026-06", basis="CASH")
        cash_final = get_success_data(api.finalize_owner_statement(cash["id"], PM))
        accrual = create_draft_statement(prop["id"], period_label="2026-06",
                                         basis="ACCRUAL")
        accrual_final = get_success_data(api.finalize_owner_statement(accrual["id"], PM))
        assert accrual_final["gross_cents"] == 200000
        assert accrual_final["management_fee_cents"] == 16000
        assert accrual_final["net_to_owner_cents"] == 184000
        assert cash_final["net_to_owner_cents"] != accrual_final["net_to_owner_cents"]


class TestDepositSettlement:
    def _build_ny_expired_lease_with_arrears(self):
        """NY lease, deposit 300000 collected 2024-06-01; one 112500 RENT charge
        outstanding; lease expired 2025-06-01."""
        owner = create_owner(management_fee_pct=0.08)
        prop = create_property(owner_id=owner["id"], state_code="NY",
                               reserve_floor_cents=0)
        unit = create_unit(property_id=prop["id"], market_rent_cents=250000)
        # The deposit refund (146500) is debited from the property trust at
        # settlement (PRD §3.6), and the trust is credited only by collected rent
        # or manual operator fundings (PRD §2.8). No rent is collected in this
        # world, so fund the trust so it can cover the refund debit.
        fund_trust(prop["id"], 200000)
        app = create_approved_applicant(unit["id"], annual_income_cents=18000000,
                                        credit_score=720, requested_rent_cents=250000,
                                        monthly_debt_cents=0)
        lease = create_draft_lease(unit["id"], app["id"], start_date="2024-06-01",
                                   end_date="2025-06-01", monthly_rent_cents=250000,
                                   grace_period_days=5)
        dep = collect_deposit(lease["id"], collected_cents=300000,
                              collected_date="2024-06-01")
        signed = get_success_data(api_client.sign_lease(lease["id"], PM))
        post_rent_charge(signed["id"], amount_cents=112500, period_label="2025-05",
                         due_date="2025-05-01")
        get_success_data(api_client.expire_lease(signed["id"],
                                                 {"as_of_date": "2025-06-01"}, PM))
        return prop, dep

    def test_settle_accrues_ny_interest_then_refunds_remainder(self, api):
        """PRD §3.6: "New York accrues at 0.0150 ... Only fully completed 365-day
        years accrue: the number of accruing years is the count of whole days
        between the collection date and the settlement date, divided by 365 and
        taken as the floor ... The accrued interest is the collected principal
        multiplied by the state rate multiplied by that whole-year count, rounded
        half-up to whole cents". PRD §3.6: "Deductions are taken in a fixed order:
        first, outstanding lease arrears ... then from what remains, requested
        damages ... and whatever remains after both is the refund_cents."

        744 days -> 2 full years -> interest round(300000*0.015*2)=9000; available
        309000; arrears 112500 + damage 50000 = deductions 162500; refund 146500.

        Design: Difficulty/dual_variant_calc/deposit_settlement_refund_vs_forfeit_diverge
        """
        prop, dep = self._build_ny_expired_lease_with_arrears()
        settled = get_success_data(api.settle_security_deposit(
            dep["id"], {"settlement_date": "2026-06-15",
                        "damage_deductions_cents": 50000}, PM))
        assert settled["interest_accrued_cents"] == 9000
        assert settled["deductions_cents"] == 162500
        assert settled["refund_cents"] == 146500
        assert settled["status"] == "SETTLED"

    def test_settle_status_is_settled_when_refund_positive(self, api):
        """PRD §3.6: "If the refund is positive the deposit settles: its status
        becomes SETTLED, and the refund is debited from the property's
        trust_balance_cents".

        Second test of the deposit-settlement instance: with refund 146500 > 0 the
        deposit ends SETTLED (not FORFEITED).

        Design: Difficulty/dual_variant_calc/deposit_settlement_refund_vs_forfeit_diverge
        """
        prop, dep = self._build_ny_expired_lease_with_arrears()
        settled = get_success_data(api.settle_security_deposit(
            dep["id"], {"settlement_date": "2026-06-15",
                        "damage_deductions_cents": 50000}, PM))
        assert settled["status"] == "SETTLED"
        assert settled["refund_cents"] == 146500
