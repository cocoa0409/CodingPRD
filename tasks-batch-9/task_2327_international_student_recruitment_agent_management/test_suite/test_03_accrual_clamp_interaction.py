"""Three clamps interact inside one accrual formula.

The top tier adds 150 basis points to every milestone rate.  For the deposit
milestone the bonus survives the rate ceiling and the cent ceiling then bites;
for the enrollment milestone the bonus is clipped by the rate ceiling first and
the cent ceiling bites afterwards; for the census milestone neither ceiling
applies and only the half-up rounding of a half-cent shows.
"""

import pytest

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_accrual_entry, assert_cents, one_entry


@pytest.fixture()
def platinum_full_chain(client):
    """A top-tier agency whose second student file runs the whole chain."""
    partner = fx.build_platinum_history(client)

    fx.set_clock(client, "2026-08-12T00:00:00Z")
    ready = fx.build_submission_ready_application(
        client,
        partner,
        student_ref="STU-1001",
        passport_hash="hash-passport-1001",
        applicant_user_id="applicant-1001",
        program_id=partner["masters_program_id"],
    )
    fx.submit_application(client, partner["agency_id"], ready["application_id"])
    admitted = fx.admit_application(client, ready["application_id"])
    version = admitted["version"]

    for milestone, event_date in (
        (C.MILESTONE_DEPOSIT_PAID, "2026-08-20"),
        (C.MILESTONE_ENROLLED, "2026-08-25"),
        (C.MILESTONE_CENSUS_CONFIRMED, "2026-09-30"),
        (C.MILESTONE_PERSISTED, "2027-02-15"),
    ):
        fx.set_clock(client, f"{event_date}T00:00:00Z")
        updated = fx.register_milestone(
            client, ready["application_id"], milestone, event_date, version
        )
        version = updated["version"]

    return {
        "partner": partner,
        "application_id": ready["application_id"],
        "foundation_application_id": partner["first_application_id"],
    }


class TestAccrualClampInteraction:
    def test_rate_ceiling_and_cent_ceiling_bite_in_the_documented_order(
        self, client, platinum_full_chain
    ):
        """Bonus, then rate ceilings, then rounding, then the cent ceiling.

        "`effective_bps` is then the greater of zero and the smallest of three
        quantities: the base plus bonus, the pinned card's `rate_cap_bps`, and
        the program's `max_commission_bps`"

        "The raw amount is the program's `annual_tuition_cents` multiplied by
        `effective_bps` and divided by 10,000; `amount_cents` is that raw amount
        rounded half up to whole cents and then, and only then, capped at the
        pinned card's `per_milestone_cap_cents`."

        Design: Difficulty/combinatorial_formula/platinum_accrual_rate_cap_and_cent_cap_interaction
        """
        env = platinum_full_chain
        entries = fx.read_entries(client, application_id=env["application_id"])

        expected = {
            C.MILESTONE_DEPOSIT_PAID: (550, 150000),
            C.MILESTONE_ENROLLED: (600, 150000),
            C.MILESTONE_CENSUS_CONFIRMED: (350, 99600),
            C.MILESTONE_PERSISTED: (300, 85371),
        }
        for milestone, (effective_bps, amount_cents) in expected.items():
            entry = one_entry(entries, C.ENTRY_KIND_ACCRUAL, milestone)
            assert_accrual_entry(
                entry,
                milestone=milestone,
                tier_snapshot=C.TIER_PLATINUM,
                effective_bps=effective_bps,
                amount_cents=amount_cents,
            )
            assert entry["schedule_id"] == env["partner"]["schedule_id"], (
                f"{milestone} must price from the pinned rate card"
            )

    def test_balances_sum_the_four_accruals_and_the_ineligible_program_accrues_nothing(
        self, client, platinum_full_chain
    ):
        """A commission-ineligible programme creates no ledger rows at all.

        "if the program's `commission_eligible` is false, no entry is created at
        all"

        "`net_commission_cents` is the *final chronological* figure, recomputed
        after every accrual, clawback, forfeiture and void"

        Design: Difficulty/combinatorial_formula/platinum_accrual_rate_cap_and_cent_cap_interaction
        """
        env = platinum_full_chain

        application = fx.read_application(client, env["application_id"])
        assert application["status"] == C.APPLICATION_PERSISTED
        assert_cents(
            application["net_commission_cents"], 484971, "net_commission_cents"
        )

        agency = fx.read_agency(client, env["partner"]["agency_id"])
        assert_cents(
            agency["net_earned_commission_cents"],
            484971,
            "net_earned_commission_cents",
        )

        foundation_entries = fx.read_entries(
            client, application_id=env["foundation_application_id"]
        )
        assert foundation_entries == [], (
            "the foundation programme is commission-ineligible, so its four "
            f"milestones must produce no ledger rows, found {foundation_entries!r}"
        )
