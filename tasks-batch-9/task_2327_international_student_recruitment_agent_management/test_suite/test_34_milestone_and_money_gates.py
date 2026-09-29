"""Guards on the registrar's feed and on the money that follows it.

Four temporal guards separate on the milestone endpoint; the annual ceiling reads
a running total rather than the single entry; a payment waits for recovered money;
and a nominated successor is judged against a different agency's own standing.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, one_entry
from test_helpers.test_users import COMPLIANCE, FINANCE_APPROVER, FINANCE_PAYER, REGISTRAR


class TestFourTemporalGuardsOnOneEndpoint:
    @pytest.fixture()
    def admitted_file(self, client):
        """A file admitted on 2026-08-01 against the autumn program."""
        partner = fx.build_active_partner(
            client, legal_name="Milestone Guard Agency", contract_ref="CTR-001"
        )
        admitted = fx.build_admitted_application(
            client, partner, student_ref="STU-001", passport_hash="hash-m-001"
        )
        return {
            "partner": partner,
            "application_id": admitted["application_id"],
            "version": admitted["version"],
        }

    def test_ordering_and_predecessor_dates_are_two_separate_refusals(
        self, client, admitted_file
    ):
        """A skipped step is a conflict; a backdated step is unprocessable.

        "The milestone chain is strictly ordered — `ADMITTED → DEPOSIT_PAID → ENROLLED →
        CENSUS_CONFIRMED → PERSISTED` — and only the immediate successor of the
        application's current `status` may be registered."

        "`DEPOSIT_PAID` requires an `event_date` at or after `submitted_on` and at or
        before the current logical-clock date, and stamps `deposit_paid_on`."

        "A date before its predecessor's date, or later than the current logical-clock
        date, is `ERR_MILESTONE_DATE_INVALID`."

        Design: Corner/validations/milestone_order_and_date_guards_rejected
        """
        env = admitted_file
        version = env["version"]

        skipped = client.register_milestone(
            env["application_id"],
            F.milestone_payload(C.MILESTONE_ENROLLED, "2026-08-01", version),
            REGISTRAR,
        )
        validate_error(skipped, E.ERR_MILESTONE_OUT_OF_ORDER, 409)

        backdated = client.register_milestone(
            env["application_id"],
            F.milestone_payload(C.MILESTONE_DEPOSIT_PAID, "2026-07-31", version),
            REGISTRAR,
        )
        validate_error(backdated, E.ERR_MILESTONE_DATE_INVALID, 422)

        assert fx.application_version(client, env["application_id"]) == version, (
            "neither refusal wrote anything"
        )

        deposited = fx.register_milestone(
            client,
            env["application_id"],
            C.MILESTONE_DEPOSIT_PAID,
            "2026-08-01",
            version,
        )
        enrolled = fx.register_milestone(
            client,
            env["application_id"],
            C.MILESTONE_ENROLLED,
            "2026-08-01",
            deposited["version"],
        )
        assert enrolled["status"] == C.APPLICATION_ENROLLED
        assert enrolled["deposit_paid_on"] == "2026-08-01"
        assert enrolled["enrolled_on"] == "2026-08-01"

    def test_the_program_calendar_adds_two_more_gates_of_its_own(
        self, client, admitted_file
    ):
        """The census and persistence checkpoints refuse dates the chain allows.

        "Two further program-driven gates apply on top: a `CENSUS_CONFIRMED`
        `event_date` earlier than the program's `census_date` is refused with
        `ERR_CENSUS_DATE_NOT_REACHED`, and a `PERSISTED` `event_date` earlier than the
        program's `persistence_check_date` is refused with
        `ERR_PERSISTENCE_DATE_NOT_REACHED`."

        "`CENSUS_CONFIRMED` requires an `event_date` at or after `enrolled_on` and at or
        before the current logical-clock date, and stamps `census_confirmed_on`."

        Design: Corner/validations/milestone_order_and_date_guards_rejected
        """
        env = admitted_file

        deposited = fx.register_milestone(
            client,
            env["application_id"],
            C.MILESTONE_DEPOSIT_PAID,
            "2026-08-01",
            env["version"],
        )
        enrolled = fx.register_milestone(
            client,
            env["application_id"],
            C.MILESTONE_ENROLLED,
            "2026-08-01",
            deposited["version"],
        )

        too_early = client.register_milestone(
            env["application_id"],
            F.milestone_payload(
                C.MILESTONE_CENSUS_CONFIRMED, "2026-08-01", enrolled["version"]
            ),
            REGISTRAR,
        )
        validate_error(too_early, E.ERR_CENSUS_DATE_NOT_REACHED, 422)

        fx.set_clock(client, "2026-09-30T00:00:00Z")
        confirmed = fx.register_milestone(
            client,
            env["application_id"],
            C.MILESTONE_CENSUS_CONFIRMED,
            "2026-09-30",
            enrolled["version"],
        )
        assert confirmed["status"] == C.APPLICATION_CENSUS_CONFIRMED
        assert confirmed["census_confirmed_on"] == "2026-09-30"

        premature_persistence = client.register_milestone(
            env["application_id"],
            F.milestone_payload(
                C.MILESTONE_PERSISTED, "2026-09-30", confirmed["version"]
            ),
            REGISTRAR,
        )
        validate_error(premature_persistence, E.ERR_PERSISTENCE_DATE_NOT_REACHED, 422)

        assert (
            fx.application_version(client, env["application_id"])
            == confirmed["version"]
        ), "four writes happened and no refusal added a fifth"


class TestTheAnnualCeilingReadsARunningTotal:
    def test_the_second_approval_breaches_a_cap_the_first_one_fitted_inside(
        self, client
    ):
        """Each amount is under the cap; their sum is not.

        "Finally the annual ceiling applies: the sum of `amount_cents` over that
        contract's `ACCRUAL` entries already in `APPROVED` or `PAID`, plus this entry's
        own `amount_cents`, must not exceed the contract's
        `annual_commission_cap_cents`, and a breach is `ERR_COMMISSION_CAP_EXCEEDED`."

        "An `action` of `APPROVE` moves `ACCRUED → APPROVED` and stamps
        `approved_by_user_id`."

        Design: Corner/validations/entry_approve_over_annual_cap_rejected
        """
        partner = fx.build_active_partner(
            client,
            legal_name="Capped Agency",
            contract_ref="CTR-CAP",
            annual_commission_cap_cents=100000,
            program_overrides={"annual_tuition_cents": 2000000},
        )
        admitted = fx.build_admitted_application(
            client, partner, student_ref="STU-001", passport_hash="hash-c-001"
        )
        deposited = fx.register_milestone(
            client,
            admitted["application_id"],
            C.MILESTONE_DEPOSIT_PAID,
            "2026-08-01",
            admitted["version"],
        )
        fx.register_milestone(
            client,
            admitted["application_id"],
            C.MILESTONE_ENROLLED,
            "2026-08-01",
            deposited["version"],
        )

        entries = fx.read_entries(client, application_id=admitted["application_id"])
        deposit_entry = one_entry(
            entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID
        )
        enrolled_entry = one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_ENROLLED)

        approved = fx.approve_entry(client, deposit_entry["id"])
        assert approved["state"] == C.ENTRY_APPROVED
        assert_cents(approved["amount_cents"], 80000, "amount_cents")

        over_cap = client.entry_disposition(
            enrolled_entry["id"],
            F.disposition_payload(C.DISPOSITION_APPROVE),
            FINANCE_APPROVER,
        )
        validate_error(over_cap, E.ERR_COMMISSION_CAP_EXCEEDED, 422)

        still_accrued = one_entry(
            fx.read_entries(client, application_id=admitted["application_id"]),
            C.ENTRY_KIND_ACCRUAL,
            C.MILESTONE_ENROLLED,
        )
        assert still_accrued["state"] == C.ENTRY_ACCRUED
        assert still_accrued["approved_by_user_id"] is None
        assert_cents(still_accrued["amount_cents"], 100000, "amount_cents")


class TestUnrecoveredMoneyFreezesEveryPayment:
    @pytest.fixture()
    def withdrawn_file_with_a_paid_reversal(self, client):
        """A withdrawal that reverses a PAID accrual and parks the liability."""
        partner = fx.build_active_partner(
            client,
            legal_name="Liability Agency",
            contract_ref="CTR-001",
            program_overrides={"annual_tuition_cents": 2000000},
            schedule_overrides={"clawback_window_days": 10},
        )
        admitted = fx.build_admitted_application(
            client, partner, student_ref="STU-001", passport_hash="hash-w-001"
        )

        fx.set_clock(client, "2026-10-01T00:00:00Z")
        deposited = fx.register_milestone(
            client,
            admitted["application_id"],
            C.MILESTONE_DEPOSIT_PAID,
            "2026-10-01",
            admitted["version"],
        )
        fx.set_clock(client, "2026-10-20T00:00:00Z")
        fx.register_milestone(
            client,
            admitted["application_id"],
            C.MILESTONE_ENROLLED,
            "2026-10-20",
            deposited["version"],
        )

        entries = fx.read_entries(client, application_id=admitted["application_id"])
        deposit_entry = one_entry(
            entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID
        )
        enrolled_entry = one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_ENROLLED)

        fx.approve_entry(client, deposit_entry["id"])
        fx.approve_entry(client, enrolled_entry["id"])
        fx.pay_entry(client, enrolled_entry["id"])

        fx.set_clock(client, "2026-10-25T00:00:00Z")
        fx.withdraw_application(
            client, admitted["application_id"], "2026-10-25", "Visa refused"
        )

        return {
            "partner": partner,
            "application_id": admitted["application_id"],
            "deposit_entry_id": deposit_entry["id"],
            "enrolled_entry_id": enrolled_entry["id"],
        }

    def test_only_the_accrual_inside_the_window_is_reversed(
        self, client, withdrawn_file_with_a_paid_reversal
    ):
        """Five days into a ten-day window recovers half; twenty-four recovers none.

        "If that age is at most the pinned rate card's `clawback_window_days`, the
        percentage is the window length minus the age, divided by the window length,
        rounded half up to four decimal places"

        "If the age exceeds the window, the percentage is 0.0000 and nothing is
        recovered."

        "When the resulting figure is greater than zero, a reversal row is appended with
        `kind` `CLAWBACK` and `state` `CLAWED_BACK`, its `parent_entry_id` pointing at
        the accrual it reverses, and its `milestone`, `milestone_event_date`,
        `tier_snapshot` and `effective_bps` copied verbatim from that parent."

        Design: Corner/validations/entry_pay_with_unsettled_clawback_liability_rejected
        """
        env = withdrawn_file_with_a_paid_reversal

        withdrawn = fx.read_application(client, env["application_id"])
        assert withdrawn["status"] == C.APPLICATION_WITHDRAWN
        assert withdrawn["withdrawn_on"] == "2026-10-25"

        reversals = fx.read_entries(
            client,
            application_id=env["application_id"],
            kind=C.ENTRY_KIND_CLAWBACK,
        )
        assert len(reversals) == 1
        assert reversals[0]["parent_entry_id"] == env["enrolled_entry_id"]
        assert reversals[0]["state"] == C.ENTRY_CLAWED_BACK
        assert_cents(reversals[0]["amount_cents"], 50000, "reversal amount_cents")
        assert reversals[0]["milestone"] == C.MILESTONE_ENROLLED
        assert reversals[0]["milestone_event_date"] == "2026-10-20"
        assert reversals[0]["effective_bps"] == 500

        by_id = {
            entry["id"]: entry
            for entry in fx.read_entries(
                client, application_id=env["application_id"]
            )
        }
        assert by_id[env["enrolled_entry_id"]]["state"] == C.ENTRY_CLAWED_BACK
        assert by_id[env["deposit_entry_id"]]["state"] == C.ENTRY_APPROVED

    def test_the_untouched_entry_cannot_be_paid_while_the_liability_stands(
        self, client, withdrawn_file_with_a_paid_reversal
    ):
        """The deposit entry was never reversed, yet its payment is frozen too.

        "If the parent accrual's `state` was `PAID` — meaning the money had already left
        the institution — the reversal amount is added to the agency's
        `clawback_liability_cents`."

        "It requires an acting `X-User-ID` different from the entry's
        `approved_by_user_id` per §2.10, an agency integrity standing that is not
        `SUSPENDED` and not `DEBARRED`, and an agency `clawback_liability_cents` of
        exactly zero — no further money leaves the institution while unrecovered money
        is outstanding, and an attempt against a non-zero liability is
        `ERR_CLAWBACK_LIABILITY_UNSETTLED`."

        Design: Corner/validations/entry_pay_with_unsettled_clawback_liability_rejected
        """
        env = withdrawn_file_with_a_paid_reversal

        assert_cents(
            fx.read_agency(client, env["partner"]["agency_id"])[
                "clawback_liability_cents"
            ],
            50000,
            "clawback_liability_cents",
        )

        frozen = client.entry_disposition(
            env["deposit_entry_id"],
            F.disposition_payload(C.DISPOSITION_PAY),
            FINANCE_PAYER,
        )
        validate_error(frozen, E.ERR_CLAWBACK_LIABILITY_UNSETTLED, 422)

        unchanged = one_entry(
            fx.read_entries(client, application_id=env["application_id"]),
            C.ENTRY_KIND_ACCRUAL,
            C.MILESTONE_DEPOSIT_PAID,
        )
        assert unchanged["state"] == C.ENTRY_APPROVED
        assert unchanged["paid_by_user_id"] is None


class TestASuccessorIsJudgedOnItsOwnStanding:
    def test_naming_an_unvetted_agency_blocks_a_termination_that_omitting_it_allows(
        self, client
    ):
        """The nominee is a different agency, so its own record is what counts.

        "`successor_agency_id`, when provided, must name a *different* agency, whose
        `vetting_state` is `CLEARED`, whose `compliance_posture` is `GOOD_STANDING` or
        `WATCH`, and which holds at least one contract in `ACTIVE`. Naming the
        terminated agency itself, an uncleared agency, a blocked one, or one with no
        active contract is refused with `ERR_SUCCESSOR_NOT_ELIGIBLE`. Omitting the field
        is always allowed and means in-house custody."

        Design: Corner/validations/terminate_with_ineligible_successor_rejected
        """
        agency = fx.register_agency(client, legal_name="Outgoing Agency")
        fx.clear_agency(client, agency["id"])
        nominee = fx.register_agency(
            client,
            legal_name="Unvetted Successor Agency",
            complete_diligence=False,
        )
        assert nominee["vetting_state"] == C.VETTING_DRAFT

        contract = fx.draft_contract(client, agency["id"], contract_ref="CTR-001")
        fx.append_schedule(client, contract["id"], contract["version"])
        fx.activate_contract(client, agency["id"], contract["id"])

        refused = client.terminate_contract(
            contract["id"],
            F.termination_payload(
                C.TERMINATION_CONVENIENCE,
                "2026-08-01",
                "Transfer the book to the new partner",
                nominee["id"],
            ),
            COMPLIANCE,
        )
        validate_error(refused, E.ERR_SUCCESSOR_NOT_ELIGIBLE, 422)
        assert fx.read_contract(client, contract["id"])["status"] == C.CONTRACT_ACTIVE

        wound_down = validate_success(
            client.terminate_contract(
                contract["id"],
                F.termination_payload(
                    C.TERMINATION_CONVENIENCE,
                    "2026-08-01",
                    "Wind down without a successor",
                ),
                COMPLIANCE,
            )
        )
        assert wound_down["status"] == C.CONTRACT_TERMINATED
        assert wound_down["termination_reason_code"] == C.TERMINATION_CONVENIENCE
        assert wound_down["terminated_on"] == "2026-08-01"
        assert fx.read_transitions(client) == []
