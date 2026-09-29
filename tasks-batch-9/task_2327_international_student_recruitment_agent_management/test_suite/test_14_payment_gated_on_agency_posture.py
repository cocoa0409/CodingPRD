"""Payment reads the agency's standing, not the contract's status.

A suspended agency blocks the money leaving the institution.  Reinstatement to
the intermediate standing releases the payment even though the contract that
produced the entry is still suspended.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, one_entry


@pytest.fixture()
def approved_entry_under_suspension(client):
    """An approved accrual whose agency was suspended by hand afterwards."""
    partner = fx.build_active_partner(client)
    admitted = fx.build_admitted_application(
        client,
        partner,
        student_ref="STU-7001",
        passport_hash="hash-passport-7001",
        applicant_user_id="applicant-7001",
    )

    fx.set_clock(client, "2026-09-05T00:00:00Z")
    fx.register_milestone(
        client,
        admitted["application_id"],
        C.MILESTONE_DEPOSIT_PAID,
        "2026-09-05",
        admitted["version"],
    )

    entries = fx.read_entries(client, application_id=admitted["application_id"])
    entry = one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID)
    fx.approve_entry(client, entry["id"])

    fx.posture_action(
        client,
        partner["agency_id"],
        C.POSTURE_SUSPEND,
        "Regulator inquiry into visa integrity",
    )

    return {
        "partner": partner,
        "agency_id": partner["agency_id"],
        "contract_id": partner["contract_id"],
        "application_id": admitted["application_id"],
        "entry_id": entry["id"],
    }


class TestPaymentGatedOnAgencyPosture:
    def test_payment_is_refused_while_the_agency_is_suspended(
        self, client, approved_entry_under_suspension
    ):
        """The approved entry does not move and stamps nobody.

        "It requires an acting `X-User-ID` different from the entry's
        `approved_by_user_id` per §2.10, an agency integrity standing that is not
        `SUSPENDED` and not `DEBARRED`, and an agency `clawback_liability_cents`
        of exactly zero"

        "Business-safety gates, in this internal order: vetting cleared
        (`ERR_AGENCY_NOT_CLEARED`); compliance posture
        (`ERR_AGENCY_POSTURE_BLOCKED`)"

        Design: Difficulty/cross_entity_state_dependency/entry_pay_blocked_while_agency_suspended
        """
        env = approved_entry_under_suspension

        response = client.entry_disposition(
            env["entry_id"],
            F.disposition_payload(C.DISPOSITION_PAY),
            fx.FINANCE_PAYER,
        )
        validate_error(response, E.ERR_AGENCY_POSTURE_BLOCKED)

        entries = fx.read_entries(client, application_id=env["application_id"])
        entry = one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID)
        assert entry["state"] == C.ENTRY_APPROVED
        assert entry["paid_by_user_id"] is None

    def test_reinstatement_releases_the_payment_while_the_contract_stays_suspended(
        self, client, approved_entry_under_suspension
    ):
        """Two different finance identities, and no contract dependency at all.

        "`REINSTATE` is the de-escalation and it lands on `WATCH`, never on
        `GOOD_STANDING`: from `PROBATION` or from `SUSPENDED` the agency returns
        to `WATCH`, and only when `rolling_risk_score` is strictly below 65.00."

        "An `action` of `PAY` moves `APPROVED → PAID` and stamps
        `paid_by_user_id`."

        Design: Difficulty/cross_entity_state_dependency/entry_pay_blocked_while_agency_suspended
        """
        env = approved_entry_under_suspension

        fx.posture_action(
            client, env["agency_id"], C.POSTURE_REINSTATE, "Inquiry closed"
        )
        agency = fx.read_agency(client, env["agency_id"])
        assert agency["compliance_posture"] == C.POSTURE_WATCH

        fx.pay_entry(client, env["entry_id"])

        entries = fx.read_entries(client, application_id=env["application_id"])
        entry = one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID)
        assert entry["state"] == C.ENTRY_PAID
        assert entry["approved_by_user_id"] == "finance-1"
        assert entry["paid_by_user_id"] == "finance-2"

        contract = fx.read_contract(client, env["contract_id"])
        assert contract["status"] == C.CONTRACT_SUSPENDED, (
            "payment must not depend on the contract's own status"
        )

    def test_the_balances_are_unchanged_by_moving_money_within_the_ledger(
        self, client, approved_entry_under_suspension
    ):
        """PAID counts towards the net exactly as ACCRUED and APPROVED do.

        "`net_earned_commission_cents` is the sum of `amount_cents` over every
        `ACCRUAL` entry reachable from the agency through its contracts whose
        `state` is `ACCRUED`, `APPROVED` or `PAID`"

        "`clawback_liability_cents` is the sum of `amount_cents` over the
        agency's `CLAWBACK` entries in `CLAWED_BACK` whose parent accrual was in
        `PAID` at the time the clawback was written."

        Design: Difficulty/cross_entity_state_dependency/entry_pay_blocked_while_agency_suspended
        """
        env = approved_entry_under_suspension

        fx.posture_action(
            client, env["agency_id"], C.POSTURE_REINSTATE, "Inquiry closed"
        )
        fx.pay_entry(client, env["entry_id"])

        agency = fx.read_agency(client, env["agency_id"])
        assert_cents(
            agency["net_earned_commission_cents"],
            113828,
            "net_earned_commission_cents",
        )
        assert_cents(agency["clawback_liability_cents"], 0, "clawback_liability_cents")
