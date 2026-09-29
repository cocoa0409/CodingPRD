"""Clawback totals are sums of per-entry rounded reversals.

Three accruals of 113828, 142285 and 56914 cents are reversed at prorations of
0.6417, 0.6667 and 0.8833.  Rounding each product to whole cents and then adding
gives 218176; adding the raw products and rounding once gives 218177, so the
total alone decides whether the evaluation order was followed.
"""

import pytest

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, one_entry


@pytest.fixture()
def withdrawn_three_accrual_file(client):
    """A file that reached the census milestone and is then withdrawn.

    No scorecard is ever run, so every accrual prices at the unrated tier and the
    three amounts are exactly the card's base rates applied to the tuition.
    """
    partner = fx.build_active_partner(client)
    ready = fx.build_submission_ready_application(
        client,
        partner,
        student_ref="STU-1001",
        passport_hash="hash-passport-1001",
        applicant_user_id="applicant-1001",
    )
    fx.submit_application(client, partner["agency_id"], ready["application_id"])
    admitted = fx.admit_application(client, ready["application_id"])
    version = admitted["version"]

    for milestone, event_date in (
        (C.MILESTONE_DEPOSIT_PAID, "2026-09-05"),
        (C.MILESTONE_ENROLLED, "2026-09-08"),
        (C.MILESTONE_CENSUS_CONFIRMED, "2026-10-04"),
    ):
        fx.set_clock(client, f"{event_date}T00:00:00Z")
        updated = fx.register_milestone(
            client, ready["application_id"], milestone, event_date, version
        )
        version = updated["version"]

    fx.set_clock(client, "2026-10-18T00:00:00Z")
    withdrawal = fx.withdraw_application(
        client,
        ready["application_id"],
        "2026-10-18",
        "Student deferred to next intake",
    )

    return {
        "partner": partner,
        "application_id": ready["application_id"],
        "withdrawal": withdrawal,
    }


class TestClawbackRoundingOrder:
    def test_reversals_are_rounded_per_entry_and_the_total_is_their_sum(
        self, client, withdrawn_three_accrual_file
    ):
        """218176, never the 218177 a single final rounding would produce.

        "the percentage is the window length minus the age, divided by the
        window length, rounded half up to four decimal places"

        "The entry's reversal is then its `amount_cents` multiplied by that
        percentage, rounded half up to whole cents — rounded *per entry*, never
        once at the end."

        "Any total clawback figure is the sum of these already-rounded per-entry
        values; summing the raw products and rounding once is explicitly not the
        rule and produces a different total."

        "it is the sum of `amount_cents` over that application's `ACCRUAL` entries
        whose `state` is `ACCRUED`, `APPROVED` or `PAID`, minus the sum of
        `amount_cents` over its `CLAWBACK` entries whose `state` is `CLAWED_BACK`"

        Design: Difficulty/combinatorial_formula/clawback_per_entry_rounding_order_pinned
        """
        env = withdrawn_three_accrual_file
        entries = fx.read_entries(client, application_id=env["application_id"])

        expected_reversals = {
            C.MILESTONE_DEPOSIT_PAID: 73043,
            C.MILESTONE_ENROLLED: 94861,
            C.MILESTONE_CENSUS_CONFIRMED: 50272,
        }
        for milestone, amount in expected_reversals.items():
            reversal = one_entry(entries, C.ENTRY_KIND_CLAWBACK, milestone)
            assert_cents(reversal["amount_cents"], amount, f"reversal for {milestone}")
            assert reversal["state"] == C.ENTRY_CLAWED_BACK

        total = sum(
            e["amount_cents"] for e in entries if e["kind"] == C.ENTRY_KIND_CLAWBACK
        )
        assert total == 218176, (
            f"clawback total must be 218176, not 218177; got {total}"
        )

        # Every reversed parent has moved to CLAWED_BACK, so no accrual is left in
        # ACCRUED, APPROVED or PAID and the accrual side of both figures is zero;
        # what remains is the negated clawback total.
        application = fx.read_application(client, env["application_id"])
        assert_cents(
            application["net_commission_cents"], -218176, "net_commission_cents"
        )

        agency = fx.read_agency(client, env["partner"]["agency_id"])
        assert_cents(
            agency["net_earned_commission_cents"], -218176, "net_earned_commission_cents"
        )

    def test_each_reversal_names_its_parent_and_an_unpaid_reversal_creates_no_liability(
        self, client, withdrawn_three_accrual_file
    ):
        """Parents move to the reversed state; liability tracks paid money only.

        "a reversal row is appended with `kind` `CLAWBACK` and `state`
        `CLAWED_BACK`, its `parent_entry_id` pointing at the accrual it reverses"

        "If the parent accrual's `state` was `PAID` — meaning the money had
        already left the institution — the reversal amount is added to the
        agency's `clawback_liability_cents`."

        "if the agency's total clawback amount divided by its total lifetime
        accrual amount reaches 0.25 — a quarter of everything ever accrued having
        been reversed — and its integrity standing is `GOOD_STANDING`, that
        standing escalates to `WATCH`"

        Design: Difficulty/combinatorial_formula/clawback_per_entry_rounding_order_pinned
        """
        env = withdrawn_three_accrual_file
        entries = fx.read_entries(client, application_id=env["application_id"])

        for milestone in (
            C.MILESTONE_DEPOSIT_PAID,
            C.MILESTONE_ENROLLED,
            C.MILESTONE_CENSUS_CONFIRMED,
        ):
            accrual = one_entry(entries, C.ENTRY_KIND_ACCRUAL, milestone)
            reversal = one_entry(entries, C.ENTRY_KIND_CLAWBACK, milestone)
            assert accrual["state"] == C.ENTRY_CLAWED_BACK
            assert reversal["parent_entry_id"] == accrual["id"], (
                f"the {milestone} reversal must name the {milestone} accrual"
            )
            assert reversal["tier_snapshot"] == accrual["tier_snapshot"]
            assert reversal["effective_bps"] == accrual["effective_bps"]
            assert reversal["milestone_event_date"] == accrual["milestone_event_date"]

        agency = fx.read_agency(client, env["partner"]["agency_id"])
        assert_cents(
            agency["clawback_liability_cents"], 0, "clawback_liability_cents"
        )
        assert agency["compliance_posture"] == C.POSTURE_WATCH

        application = fx.read_application(client, env["application_id"])
        assert application["status"] == C.APPLICATION_WITHDRAWN
        assert application["withdrawn_on"] == "2026-10-18"
