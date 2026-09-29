"""Which rate card prices a milestone, and which accruals survive a termination.

A student file carries the rate card that was effective when it was submitted, so
a later card never reprices it.  A voluntary termination walks the ledger in
vesting order and keeps everything an enrolled student earned.
"""

import pytest
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_accrual_entry, assert_cents, one_entry
from test_helpers.test_users import OFFICER


class TestPinnedCardOutlivesTheEffectiveCard:
    @pytest.fixture()
    def two_card_contract(self, client):
        """A contract with a 400 bps card, then a 900 bps card from September."""
        partner = fx.build_active_partner(
            client,
            legal_name="Pinned Card Agency",
            contract_ref="CTR-001",
            program_overrides={"annual_tuition_cents": 2000000},
            schedule_overrides={"effective_to": "2026-09-01"},
            activate=False,
        )
        richer_card = fx.append_schedule(
            client,
            partner["contract_id"],
            fx.contract_version(client, partner["contract_id"]),
            effective_from="2026-09-01",
            effective_to="2027-07-31",
            deposit_rate_bps=900,
            enrollment_rate_bps=900,
            census_rate_bps=900,
            persistence_rate_bps=900,
            rate_cap_bps=1000,
            per_milestone_cap_cents=500000,
        )
        fx.activate_contract(client, partner["agency_id"], partner["contract_id"])

        admitted = fx.build_admitted_application(
            client, partner, student_ref="STU-001"
        )
        fx.set_clock(client, "2026-09-05T00:00:00Z")

        return {
            "partner": partner,
            "first_card_id": partner["schedule_id"],
            "second_card_id": richer_card["id"],
            "application_id": admitted["application_id"],
            "version": admitted["version"],
        }

    def test_submission_pins_the_card_that_was_effective_that_day(
        self, client, two_card_contract
    ):
        """Only the first card covers 2026-08-01, so only it can be pinned.

        "It pins `pinned_contract_id` to the sole contract in `ACTIVE` and
        `pinned_schedule_id` to the rate card effective on that date — and those two
        pins, not the currently effective records, are what every later milestone
        accrual reads."

        "It stamps `submitted_on` with the current logical-clock date."

        Design: Corner/calculations/accrual_prices_from_pinned_schedule_not_current_card
        """
        env = two_card_contract

        application = fx.read_application(client, env["application_id"])
        assert application["pinned_schedule_id"] == env["first_card_id"]
        assert application["pinned_contract_id"] == env["partner"]["contract_id"]
        assert application["submitted_on"] == C.DEFAULT_CLOCK_DATE

    def test_a_september_milestone_is_still_priced_from_the_august_card(
        self, client, two_card_contract
    ):
        """Four hundred basis points, not nine hundred, on a September event.

        "Rates come exclusively from the pinned rate card, never from whichever card
        happens to be effective on the event date."

        "The raw amount is the program's `annual_tuition_cents` multiplied by
        `effective_bps` and divided by 10,000; `amount_cents` is that raw amount
        rounded half up to whole cents and then, and only then, capped at the pinned
        card's `per_milestone_cap_cents`."

        Design: Corner/calculations/accrual_prices_from_pinned_schedule_not_current_card
        """
        env = two_card_contract

        moved = fx.register_milestone(
            client,
            env["application_id"],
            C.MILESTONE_DEPOSIT_PAID,
            "2026-09-05",
            env["version"],
        )
        assert moved["status"] == C.APPLICATION_DEPOSIT_PAID

        entries = fx.read_entries(client, application_id=env["application_id"])
        assert len(entries) == 1
        entry = one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID)
        assert_accrual_entry(
            entry,
            milestone=C.MILESTONE_DEPOSIT_PAID,
            tier_snapshot=C.TIER_UNRATED,
            effective_bps=400,
            amount_cents=80000,
        )
        assert entry["schedule_id"] == env["first_card_id"]
        assert entry["schedule_id"] != env["second_card_id"], (
            "the card effective on the milestone date must not be consulted"
        )

        assert_cents(
            fx.read_application(client, env["application_id"])["net_commission_cents"],
            80000,
            "net_commission_cents",
        )


class TestConvenienceTerminationKeepsVestedAccruals:
    @pytest.fixture()
    def enrolled_student_ledger(self, client):
        """An active partner whose only student file reached ENROLLED."""
        partner = fx.build_active_partner(
            client,
            legal_name="Vested Accrual Agency",
            contract_ref="CTR-001",
            program_overrides={"annual_tuition_cents": 2000000},
        )
        admitted = fx.build_admitted_application(
            client, partner, student_ref="STU-001"
        )

        fx.set_clock(client, "2026-08-03T00:00:00Z")
        deposited = fx.register_milestone(
            client,
            admitted["application_id"],
            C.MILESTONE_DEPOSIT_PAID,
            "2026-08-02",
            admitted["version"],
        )
        fx.register_milestone(
            client,
            admitted["application_id"],
            C.MILESTONE_ENROLLED,
            "2026-08-03",
            deposited["version"],
        )

        return {
            "partner": partner,
            "application_id": admitted["application_id"],
        }

    def test_the_voluntary_exit_closes_the_paper_and_frees_the_country(
        self, client, enrolled_student_ledger
    ):
        """Termination stamps the reason and the date, and releases the territory.

        "Only a `ComplianceOfficer` terminates, and termination is permitted from
        `ACTIVE` and from `SUSPENDED`; from any other status it is
        `ERR_INVALID_CONTRACT_STATE`."

        "The `effective_date` is stamped into `terminated_on` and the reason into
        `termination_reason_code`."

        "Every territory assignment on the contract still in `ACTIVE` is `RELEASED`."

        Design: Corner/calculations/convenience_termination_preserves_vested_enrolled_accrual
        """
        env = enrolled_student_ledger
        partner = env["partner"]

        terminated = fx.terminate_contract(
            client,
            partner["contract_id"],
            C.TERMINATION_CONVENIENCE,
            "2026-08-03",
            "Agency exits the market voluntarily",
        )
        assert terminated["status"] == C.CONTRACT_TERMINATED
        assert terminated["termination_reason_code"] == C.TERMINATION_CONVENIENCE
        assert terminated["terminated_on"] == "2026-08-03"

        assignments = fx.read_assignments(client, partner["contract_id"])
        assert len(assignments) == 1
        assert assignments[0]["status"] == C.ASSIGNMENT_RELEASED

    def test_enrolment_vests_both_accruals_and_no_student_file_is_transitioned(
        self, client, enrolled_student_ledger
    ):
        """Nothing is forfeited and nothing is handed to a successor.

        "Otherwise a candidate is kept exactly when its producing application's
        `status` is `ENROLLED`, `CENSUS_CONFIRMED` or `PERSISTED`, because enrollment
        is what vests a commission, and every other candidate is forfeited."

        "Applications already at `ENROLLED` or beyond, and those in a terminal status,
        are not transitioned."

        "The agency's `net_earned_commission_cents` is recomputed in full from the
        surviving rows."

        Design: Corner/calculations/convenience_termination_preserves_vested_enrolled_accrual
        """
        env = enrolled_student_ledger
        partner = env["partner"]

        fx.terminate_contract(
            client,
            partner["contract_id"],
            C.TERMINATION_CONVENIENCE,
            "2026-08-03",
            "Agency exits the market voluntarily",
        )

        entries = fx.read_entries(client, application_id=env["application_id"])
        assert len(entries) == 2
        assert_accrual_entry(
            one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID),
            milestone=C.MILESTONE_DEPOSIT_PAID,
            tier_snapshot=C.TIER_UNRATED,
            effective_bps=400,
            amount_cents=80000,
        )
        assert_accrual_entry(
            one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_ENROLLED),
            milestone=C.MILESTONE_ENROLLED,
            tier_snapshot=C.TIER_UNRATED,
            effective_bps=500,
            amount_cents=100000,
        )

        assert_cents(
            fx.read_agency(client, partner["agency_id"])[
                "net_earned_commission_cents"
            ],
            180000,
            "net_earned_commission_cents",
        )
        application = fx.read_application(client, env["application_id"])
        assert_cents(
            application["net_commission_cents"], 180000, "net_commission_cents"
        )
        assert application["custody_agency_id"] == partner["agency_id"]

        _, meta = validate_paginated(client.list_file_transitions(OFFICER))
        assert meta["total_count"] == 0
