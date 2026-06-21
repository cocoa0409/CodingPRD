"""Conserved-quantity (compensating-invariant) depth tests.

Property trust cents: rent in, distribution out. Lease balance cents: late fee
on, waiver off.
"""
import pytest
from test_helpers import get_success_data
from test_helpers.fixtures import (
    PM, create_owner, create_property, create_unit, create_approved_applicant,
    create_draft_lease, collect_deposit, post_rent_charge, post_payment,
    assess_late_fees, list_late_fee_charges, create_finalized_statement,
    property_version, setup_active_lease,
)
from test_helpers.api_client import api_client


def _collected_world():
    """CA property reserve_floor 0; ACTIVE lease; 200000 RENT for 2026-06; late
    fee 12500 assessed; payment 150000 -> 12500 late fee, 137500 rent (trust
    137500)."""
    owner = create_owner(management_fee_pct=0.08)
    prop = create_property(owner_id=owner["id"], state_code="CA", reserve_floor_cents=0)
    unit = create_unit(property_id=prop["id"], market_rent_cents=200000)
    app = create_approved_applicant(unit["id"], annual_income_cents=12000000,
                                    credit_score=700, requested_rent_cents=200000)
    lease = create_draft_lease(unit["id"], app["id"], start_date="2026-06-01",
                               end_date="2027-06-01", monthly_rent_cents=200000,
                               late_fee_pct=0.05, late_fee_flat_cents=2500,
                               grace_period_days=5)
    collect_deposit(lease["id"], collected_cents=200000)
    signed = get_success_data(api_client.sign_lease(lease["id"], PM))
    post_rent_charge(signed["id"], amount_cents=200000, period_label="2026-06",
                     due_date="2026-06-01")
    assess_late_fees(signed["id"], "2026-06-09")
    post_payment(signed["id"], 150000, received_date="2026-06-10")
    return prop, signed


class TestTrustConservation:
    def test_trust_holds_collected_rent_before_distribution(self, api):
        """PRD §3.5: "that rent portion is credited to the owning property's
        trust_balance_cents and the property's distributable amount is recomputed."

        After 137500 is applied to rent the property trust holds exactly 137500.

        Design: Difficulty/compensating_invariant/trust_conservation_rent_in_distribution_out
        """
        prop, lease = _collected_world()
        refreshed = get_success_data(api.get_property(prop["id"], PM))
        assert refreshed["trust_balance_cents"] == 137500

    def test_distribution_leaves_trust_with_zero_drift(self, api):
        """PRD §3.10: "The amount actually paid, recorded as distribution_cents, is
        the smaller of the statement's net_to_owner_cents and the property's
        current distributable_cents ... That amount is debited from the property's
        trust_balance_cents".

        137500 collected; CASH net 126500 distributed -> trust 11000 left, zero
        drift.

        Design: Difficulty/compensating_invariant/trust_conservation_rent_in_distribution_out
        """
        prop, lease = _collected_world()
        stmt = create_finalized_statement(prop["id"], period_label="2026-06",
                                          basis="CASH")
        assert stmt["net_to_owner_cents"] == 126500
        v = property_version(prop["id"])
        distributed = get_success_data(api.distribute_owner_statement(
            stmt["id"], {"expected_property_version": v}, PM))
        assert distributed["distribution_cents"] == 126500
        refreshed = get_success_data(api.get_property(prop["id"], PM))
        assert refreshed["trust_balance_cents"] == 11000


class TestLeaseBalanceConservation:
    def test_waive_returns_balance_to_pre_fee_value(self, api):
        """PRD §3.5: "A successful waiver drives the charge to the terminal WAIVED
        state, zeroes its outstanding amount, and recomputes the lease's balance
        due."

        balance 200000 -> 212500 after a 12500 late fee -> 200000 after waiving it,
        zero drift.

        Design: Difficulty/compensating_invariant/lease_balance_conservation_charge_then_waive
        """
        world = setup_active_lease(
            state_code="TX", market_rent_cents=200000, deposit_cents=200000,
            lease_overrides={"monthly_rent_cents": 200000, "late_fee_pct": 0.05,
                             "late_fee_flat_cents": 2500, "grace_period_days": 5})
        lease_id = world["lease"]["id"]
        post_rent_charge(lease_id, amount_cents=200000, due_date="2026-06-01")
        swept = assess_late_fees(lease_id, "2026-06-09")
        assert swept["balance_due_cents"] == 212500
        fee = list_late_fee_charges(lease_id)[0]
        get_success_data(api.waive_rent_charge(fee["id"], PM))
        lease = get_success_data(api.get_lease(lease_id, PM))
        assert lease["balance_due_cents"] == 200000

    def test_waived_charge_outstanding_zeroed(self, api):
        """PRD §3.5: "A successful waiver drives the charge to the terminal WAIVED
        state, zeroes its outstanding amount".

        Second test of the lease-balance conservation instance: the waived LATE_FEE
        charge itself is WAIVED with amount_outstanding_cents 0.

        Design: Difficulty/compensating_invariant/lease_balance_conservation_charge_then_waive
        """
        world = setup_active_lease(
            state_code="TX", market_rent_cents=200000, deposit_cents=200000,
            lease_overrides={"monthly_rent_cents": 200000, "late_fee_pct": 0.05,
                             "late_fee_flat_cents": 2500, "grace_period_days": 5})
        lease_id = world["lease"]["id"]
        post_rent_charge(lease_id, amount_cents=200000, due_date="2026-06-01")
        assess_late_fees(lease_id, "2026-06-09")
        fee = list_late_fee_charges(lease_id)[0]
        waived = get_success_data(api.waive_rent_charge(fee["id"], PM))
        assert waived["status"] == "WAIVED"
        assert waived["amount_outstanding_cents"] == 0
