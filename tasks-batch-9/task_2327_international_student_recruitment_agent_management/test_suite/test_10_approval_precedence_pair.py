"""Two approval conditions fail on the same ledger entry.

The producing file is domestically recruited, so incentive compensation is
prohibited outright, and the accrued amount also blows straight through a
deliberately tiny annual ceiling.  The business-safety gate is checked first.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, one_entry


@pytest.fixture()
def domestic_entry_over_the_cap(client):
    """A domestic-origin accrual on a contract whose annual ceiling is 50000."""
    partner = fx.build_active_partner(
        client,
        legal_name="Liberty Student Placement",
        home_country_code="US",
        contract_ref="CTR-2026-009",
        annual_commission_cap_cents=50000,
        territory_country="US",
    )
    admitted = fx.build_admitted_application(
        client,
        partner,
        student_ref="STU-3001",
        student_residence_country="US",
        student_us_person=True,
        passport_hash="hash-passport-3001",
        passport_issuer="US Department of State",
        applicant_user_id="applicant-3001",
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

    return {
        "partner": partner,
        "agency_id": partner["agency_id"],
        "contract_id": partner["contract_id"],
        "application_id": admitted["application_id"],
        "entry_id": entry["id"],
        "entry": entry,
    }


class TestApprovalPrecedencePair:
    def test_the_incentive_prohibition_is_reported_and_the_fiscal_ceiling_is_not(
        self, client, domestic_entry_over_the_cap
    ):
        """Business-safety is group ten; fiscal ceilings are group fourteen.

        "The entry's `incentive_comp_prohibited` must be false: no per-enrollment
        incentive compensation may ever be approved for an application whose
        `recruitment_origin` is `DOMESTIC`, and the attempt is refused with
        `ERR_INCENTIVE_COMPENSATION_PROHIBITED`"

        "Business-safety gates, in this internal order"

        "incentive-compensation prohibition (`ERR_INCENTIVE_COMPENSATION_PROHIBITED`);
        due-diligence checklist completeness (`ERR_DUE_DILIGENCE_INCOMPLETE`)"

        "Fiscal ceilings, in this internal order: annual commission cap
        (`ERR_COMMISSION_CAP_EXCEEDED`)"

        Design: Difficulty/priority_pair_validation_conflict/approve_incentive_prohibition_outranks_commission_cap
        """
        env = domestic_entry_over_the_cap

        response = client.entry_disposition(
            env["entry_id"],
            F.disposition_payload(C.DISPOSITION_APPROVE),
            fx.FINANCE_APPROVER,
        )
        body = validate_error(response, E.ERR_INCENTIVE_COMPENSATION_PROHIBITED)
        assert body["error_id"] != E.ERR_COMMISSION_CAP_EXCEEDED

    def test_the_origin_classification_is_what_sets_the_entry_flag(
        self, client, domestic_entry_over_the_cap
    ):
        """A US residence country alone would have been enough.

        "When `student_residence_country` is `US`, or `student_us_person` is true,
        `recruitment_origin` is `DOMESTIC`; in every other case it is
        `INTERNATIONAL`."

        Design: Difficulty/priority_pair_validation_conflict/approve_incentive_prohibition_outranks_commission_cap
        """
        env = domestic_entry_over_the_cap

        application = fx.read_application(client, env["application_id"])
        assert application["recruitment_origin"] == C.ORIGIN_DOMESTIC

        assert env["entry"]["incentive_comp_prohibited"] is True
        assert_cents(env["entry"]["amount_cents"], 113828, "amount_cents")

    def test_the_fiscal_rule_was_genuinely_violated_and_the_refusal_changed_nothing(
        self, client, domestic_entry_over_the_cap
    ):
        """The accrual itself stands; only its approval is refused.

        "the sum of `amount_cents` over that contract's `ACCRUAL` entries already
        in `APPROVED` or `PAID`, plus this entry's own `amount_cents`, must not
        exceed the contract's `annual_commission_cap_cents`, and a breach is
        `ERR_COMMISSION_CAP_EXCEEDED`"

        "`net_earned_commission_cents` is the sum of `amount_cents` over every
        `ACCRUAL` entry reachable from the agency through its contracts whose
        `state` is `ACCRUED`, `APPROVED` or `PAID`"

        Design: Difficulty/priority_pair_validation_conflict/approve_incentive_prohibition_outranks_commission_cap
        """
        env = domestic_entry_over_the_cap

        client.entry_disposition(
            env["entry_id"],
            F.disposition_payload(C.DISPOSITION_APPROVE),
            fx.FINANCE_APPROVER,
        )

        contract = fx.read_contract(client, env["contract_id"])
        assert contract["annual_commission_cap_cents"] == 50000
        assert env["entry"]["amount_cents"] > contract["annual_commission_cap_cents"]

        entries = fx.read_entries(client, application_id=env["application_id"])
        entry = one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID)
        assert entry["state"] == C.ENTRY_ACCRUED
        assert entry["approved_by_user_id"] is None

        agency = fx.read_agency(client, env["agency_id"])
        assert_cents(
            agency["net_earned_commission_cents"],
            113828,
            "net_earned_commission_cents",
        )
