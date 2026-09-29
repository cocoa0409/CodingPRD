"""Transitions whose consequences land in a different entity altogether.

Confirming a prohibited-claim incident revokes a training record.  Moving the
clock retires a contract and the country it held.  Voiding one ledger row
rewrites two derived balances and closes the row for good.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_accrual_entry,
    assert_cents,
    assert_score_2dp,
    assert_sweep_counts,
    one_entry,
)
from test_helpers.test_users import COMPLIANCE, FINANCE_PAYER


class TestConfirmedProhibitedClaimReachesTraining:
    def test_confirming_the_claim_revokes_only_the_claims_module(self, client):
        """One adjudication touches the incident, a certification and the scores.

        "Confirmation of a `PROHIBITED_CLAIM` carries an additional consequence:
        every certification of that agency whose `module_code` is
        `PROHIBITED_CLAIMS` and whose `status` is `VALID` is driven to `REVOKED`
        with `revoked_reason` recorded as `CONFIRMED_PROHIBITED_CLAIM`."

        "Both outcomes stamp `resolved_by_user_id` from the acting `X-User-ID` and
        increment the incident's `version`."

        "Severity carries a weight: `LOW` weighs 5, `MEDIUM` weighs 15, `HIGH`
        weighs 30, and `CRITICAL` weighs 50."

        Design: Corner/state_machines/confirmed_prohibited_claim_revokes_certification
        """
        agency = fx.register_agency(
            client, legal_name="Prohibited Claim Agency", complete_diligence=False
        )
        accuracy = fx.record_certification(
            client, agency["id"], C.MODULE_PROGRAM_ACCURACY, 92, C.DEFAULT_CLOCK_DATE
        )
        claims = fx.record_certification(
            client, agency["id"], C.MODULE_PROHIBITED_CLAIMS, 88, C.DEFAULT_CLOCK_DATE
        )
        incident = fx.file_incident(
            client,
            agency["id"],
            category=C.INCIDENT_PROHIBITED_CLAIM,
            severity=C.SEVERITY_MEDIUM,
            occurred_on=C.DEFAULT_CLOCK_DATE,
            source=C.SOURCE_STUDENT_COMPLAINT,
        )

        resolved = fx.resolve_incident(
            client,
            incident["id"],
            C.RESOLUTION_CONFIRM,
            note="Recording of the seminar confirms a guaranteed-visa claim",
        )
        assert resolved["status"] == C.INCIDENT_CONFIRMED
        assert resolved["resolved_by_user_id"] == "compliance-1"

        by_id = {
            record["id"]: record
            for record in fx.read_certifications(client, agency["id"])
        }
        assert by_id[claims["id"]]["status"] == C.CERT_REVOKED
        assert (
            by_id[claims["id"]]["revoked_reason"]
            == C.REVOKED_REASON_CONFIRMED_PROHIBITED_CLAIM
        )
        assert by_id[accuracy["id"]]["status"] == C.CERT_VALID, (
            "only the prohibited-claims module is pulled"
        )

    def test_the_same_request_lifts_both_risk_figures_without_moving_the_posture(
        self, client
    ):
        """A medium-severity confirmation scores 15.00, which is below the band.

        "`posture_band`, the band the rolling figure currently falls in:
        `GOOD_STANDING` below 40.00, `WATCH` from 40.00, `PROBATION` from 65.00,
        and `SUSPENDED` from 85.00."

        "the fraud rate is zero when the agency's `reviewed_document_count` is
        zero"

        Design: Corner/state_machines/confirmed_prohibited_claim_revokes_certification
        """
        agency = fx.register_agency(
            client, legal_name="Prohibited Claim Agency", complete_diligence=False
        )
        fx.record_certification(
            client, agency["id"], C.MODULE_PROHIBITED_CLAIMS, 88, C.DEFAULT_CLOCK_DATE
        )
        incident = fx.file_incident(
            client,
            agency["id"],
            category=C.INCIDENT_PROHIBITED_CLAIM,
            severity=C.SEVERITY_MEDIUM,
            occurred_on=C.DEFAULT_CLOCK_DATE,
            source=C.SOURCE_STUDENT_COMPLAINT,
        )
        fx.resolve_incident(client, incident["id"], C.RESOLUTION_CONFIRM)

        scored = fx.read_agency(client, agency["id"])
        assert scored["confirmed_incident_count"] == 1
        assert_score_2dp(scored["rolling_risk_score"], 15.00, "rolling_risk_score")
        assert_score_2dp(scored["lifetime_risk_score"], 15.00, "lifetime_risk_score")
        assert scored["compliance_posture"] == C.POSTURE_GOOD_STANDING


class TestClockSweepRetiresContractAndTerritory:
    def test_one_day_past_the_term_expires_the_paper_and_the_country_together(
        self, client
    ):
        """The sweep reports both retirements and leaves the training alone.

        "Every `AgentContract` in `ACTIVE` or `SUSPENDED` whose `term_end_date` is
        now strictly earlier than the current logical-clock date moves to
        `EXPIRED`. When such a contract was `ACTIVE`, each of its territory
        assignments still in `ACTIVE` also moves to `EXPIRED` with `released_on`
        set to the current logical-clock date."

        "The response reports the new clock instant as `current_utc` together with
        four counters describing what the sweep touched: `expired_contract_count`,
        `expired_assignment_count`, `expired_certification_count` and
        `risk_recomputed_agency_count`."

        Design: Corner/state_machines/clock_sweep_expires_contract_and_its_territory
        """
        partner = fx.build_active_partner(
            client,
            legal_name="Expiry Sweep Agency",
            contract_ref="CTR-001",
            term_end_date="2026-08-31",
        )

        sweep = fx.set_clock(client, "2026-09-01T00:00:00Z", COMPLIANCE)
        assert_sweep_counts(
            sweep,
            current_utc="2026-09-01T00:00:00Z",
            expired_contract_count=1,
            expired_assignment_count=1,
            expired_certification_count=0,
            risk_recomputed_agency_count=0,
        )

        assert (
            fx.read_contract(client, partner["contract_id"])["status"]
            == C.CONTRACT_EXPIRED
        )

        assignments = fx.read_assignments(client, partner["contract_id"])
        assert len(assignments) == 1
        assert assignments[0]["status"] == C.ASSIGNMENT_EXPIRED
        assert assignments[0]["released_on"] == "2026-09-01"

        claims = fx.read_certifications(
            client, partner["agency_id"], module_code=C.MODULE_PROHIBITED_CLAIMS
        )
        assert len(claims) == 1
        assert claims[0]["status"] == C.CERT_VALID, (
            "an expiry date of 2027-01-28 is still in the future"
        )

    def test_the_retired_country_is_free_again_on_the_swept_date(self, client):
        """An expired row contributes neither occupancy nor shadow.

        "Occupancy is computed only from assignments still in `ACTIVE`; rows in
        `RELEASED` or `EXPIRED` contribute neither occupancy nor any lingering
        shadow."

        Design: Corner/state_machines/clock_sweep_expires_contract_and_its_territory
        """
        fx.build_active_partner(
            client,
            legal_name="Expiry Sweep Agency",
            contract_ref="CTR-001",
            term_end_date="2026-08-31",
        )

        fx.set_clock(client, "2026-09-01T00:00:00Z", COMPLIANCE)

        occupancy = fx.read_occupancy(client, "IN", "2026-09-01")
        assert occupancy["exclusive_active_count"] == 0
        assert occupancy["exclusive_slot_available"] is True


class TestVoidRewritesTheLedgerBalances:
    @pytest.fixture()
    def single_deposit_accrual(self, client):
        """One ACCRUED deposit row of 80000 cents on an untiered agency."""
        partner = fx.build_active_partner(
            client,
            legal_name="Ledger Sync Agency",
            contract_ref="CTR-001",
            program_overrides={"annual_tuition_cents": 2000000},
        )
        admitted = fx.build_admitted_application(
            client, partner, student_ref="STU-001"
        )

        fx.set_clock(client, "2026-08-02T00:00:00Z")
        fx.register_milestone(
            client,
            admitted["application_id"],
            C.MILESTONE_DEPOSIT_PAID,
            "2026-08-02",
            admitted["version"],
        )

        entries = fx.read_entries(client, application_id=admitted["application_id"])
        entry = one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID)
        return {
            "agency_id": partner["agency_id"],
            "schedule_id": partner["schedule_id"],
            "application_id": admitted["application_id"],
            "entry_id": entry["id"],
            "entry": entry,
        }

    def test_voiding_the_only_accrual_drops_both_derived_balances_to_zero(
        self, client, single_deposit_accrual
    ):
        """The row leaves both sums, so the application and the agency read zero.

        "An `action` of `VOID` is available from either `ACCRUED` or `APPROVED`,
        moves the entry to `VOID`, records a `void_reason`, and recomputes both the
        application's `net_commission_cents` and the agency's
        `net_earned_commission_cents`."

        "Entries in `FORFEITED` or `VOID` contribute to neither sum."

        Design: Corner/state_machines/entry_void_recomputes_ledger_then_approve_rejected
        """
        env = single_deposit_accrual

        assert_accrual_entry(
            env["entry"],
            milestone=C.MILESTONE_DEPOSIT_PAID,
            tier_snapshot=C.TIER_UNRATED,
            effective_bps=400,
            amount_cents=80000,
        )
        assert env["entry"]["schedule_id"] == env["schedule_id"]
        assert_cents(
            fx.read_application(client, env["application_id"])["net_commission_cents"],
            80000,
            "net_commission_cents before the void",
        )
        assert_cents(
            fx.read_agency(client, env["agency_id"])["net_earned_commission_cents"],
            80000,
            "net_earned_commission_cents before the void",
        )

        voided = fx.void_entry(
            client, env["entry_id"], note="Duplicate registrar feed"
        )
        assert voided["state"] == C.ENTRY_VOID
        assert voided["void_reason"] is not None

        assert_cents(
            fx.read_application(client, env["application_id"])["net_commission_cents"],
            0,
            "net_commission_cents after the void",
        )
        agency = fx.read_agency(client, env["agency_id"])
        assert_cents(
            agency["net_earned_commission_cents"],
            0,
            "net_earned_commission_cents after the void",
        )
        assert_cents(
            agency["clawback_liability_cents"], 0, "a void is not a clawback"
        )

    def test_a_voided_row_cannot_be_approved_back_into_the_ledger(
        self, client, single_deposit_accrual
    ):
        """The terminal state is enforced instead of silently re-entered.

        "`ACCRUED` is the initial state; `PAID`, `CLAWED_BACK`, `FORFEITED` and
        `VOID` are all terminal. A disposition that is not defined from the entry's
        current `state` is `ERR_INVALID_ENTRY_STATE`."

        Design: Corner/state_machines/entry_void_recomputes_ledger_then_approve_rejected
        """
        env = single_deposit_accrual
        fx.void_entry(client, env["entry_id"], note="Duplicate registrar feed")

        refused = client.entry_disposition(
            env["entry_id"], F.disposition_payload(C.DISPOSITION_APPROVE), FINANCE_PAYER
        )
        validate_error(refused, E.ERR_INVALID_ENTRY_STATE)

        still_void = validate_success(
            client.get_commission_entry(env["entry_id"], FINANCE_PAYER)
        )
        assert still_void["state"] == C.ENTRY_VOID
