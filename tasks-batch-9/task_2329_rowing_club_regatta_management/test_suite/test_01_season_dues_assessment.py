"""Season dues: the provisional seasonal assessment and the usage true-up.

The same member data is billed two different ways depending on the invoice's
`variant_basis`, and the provisional figure is only reproducible when the three
prorated components are rounded one at a time.
"""

import pytest

from test_helpers import assert_dues_invoice, assert_member
from test_helpers.fixtures import (
    add_single,
    enrol_athlete,
    hourly_windows,
    issue_invoice,
    log_returned_sessions,
    pay_invoice,
    read_member,
    true_up_invoice,
)


@pytest.fixture
def four_month_locker_invoice():
    """A RECREATIONAL member billed for four months of the season with a locker."""
    member = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)
    invoice = issue_invoice(member["id"], billable_months=4, locker_requested=True)
    return {"member": member, "invoice": invoice}


@pytest.fixture
def seven_session_true_up(cast, four_month_locker_invoice):
    """The same invoice after seven completed outings and a part payment.

    A true-up is only accepted against a `PARTIALLY_PAID` invoice, so a token
    payment of 1000 cents is applied before the rebill.
    """
    member = four_month_locker_invoice["member"]
    invoice = four_month_locker_invoice["invoice"]
    shell = add_single(hull_name="Kingfisher")
    log_returned_sessions(
        shell["id"],
        [member["id"]],
        cast["coach_headers"],
        cast["officer_headers"],
        7,
        windows=hourly_windows(7),
    )
    pay_invoice(invoice["id"], 1000)
    trued_up = true_up_invoice(invoice["id"])
    return {
        "member": read_member(member["id"]),
        "provisional": invoice,
        "invoice": trued_up,
    }


class TestProvisionalSeasonalAssessment:
    def test_four_month_locker_invoice_is_assessed_twenty_seven_thousand_five_hundred_eighty_four(
        self, four_month_locker_invoice
    ):
        """Each prorated component is rounded on its own before they are added.

        PRD: "`assessed_cents` is the sum of those three already-rounded
        components; the per-component rounding order is pinned as described in
        §2.6."

        Design: Difficulty/combinatorial_formula/dues_per_component_rounding_order_pinned_mode_b
        """
        invoice = assert_dues_invoice(four_month_locker_invoice["invoice"])
        assert invoice["assessed_cents"] == 27584, (
            "a RECREATIONAL member billed four of twelve months with a locker is "
            "assessed 20500 + 4167 + 2917 = 27584 cents, got "
            f"{invoice['assessed_cents']}"
        )
        assert invoice["assessed_cents"] != 27583, (
            "27583 is the sum-then-round figure; the components must be rounded "
            "individually before they are added"
        )
        assert invoice["variant_basis"] == "PROVISIONAL", (
            "a fresh invoice carries variant_basis PROVISIONAL, got "
            f"{invoice['variant_basis']}"
        )

    def test_fresh_invoice_opens_unpaid_with_no_true_up_delta(self, four_month_locker_invoice):
        """A newly issued invoice has taken no money and recorded no rebill.

        PRD: "A fresh invoice is `ISSUED`, with `variant_basis` `PROVISIONAL`,
        `paid_cents` 0 and `trueup_cents` null."

        Design: Difficulty/combinatorial_formula/dues_per_component_rounding_order_pinned_mode_b
        """
        invoice = four_month_locker_invoice["invoice"]
        assert invoice["status"] == "ISSUED", (
            f"a fresh invoice is ISSUED, got {invoice['status']}"
        )
        assert invoice["paid_cents"] == 0, (
            f"a fresh invoice has paid_cents 0, got {invoice['paid_cents']}"
        )
        assert invoice["trueup_cents"] is None, (
            f"a fresh invoice has trueup_cents null, got {invoice['trueup_cents']}"
        )

    def test_assessment_lands_on_the_member_balance_and_supervises_access(
        self, four_month_locker_invoice
    ):
        """The outstanding assessment is the member's balance and downgrades access.

        PRD: "`SUPERVISED` when `membership_status` is `ACTIVE` and
        `dues_balance_cents` is greater than 0"

        Design: Difficulty/combinatorial_formula/dues_per_component_rounding_order_pinned_mode_b
        """
        member = assert_member(read_member(four_month_locker_invoice["member"]["id"]))
        assert member["dues_balance_cents"] == 27584, (
            "the member's balance is the assessed figure less nothing paid, "
            f"expected 27584, got {member['dues_balance_cents']}"
        )
        assert member["boathouse_access_level"] == "SUPERVISED", (
            "an ACTIVE member carrying a positive balance is SUPERVISED, got "
            f"{member['boathouse_access_level']}"
        )


class TestUsageTrueUp:
    def test_true_up_rebills_seven_outings_at_thirty_six_thousand_five_hundred(
        self, seven_session_true_up
    ):
        """Actual usage beats the tier floor, so the rebill is usage plus admin fee.

        PRD: "the usage basis is whichever of those two is larger; and the new
        assessment is the usage basis plus a flat administration fee of 5000
        cents."

        Design: Difficulty/dual_variant_calc/dues_provisional_seasonal_vs_trueup_actual_divergence
        """
        invoice = assert_dues_invoice(seven_session_true_up["invoice"])
        assert invoice["assessed_cents"] == 36500, (
            "seven outings bill 31500 cents, which beats the 24600-cent "
            "RECREATIONAL floor, plus a 5000-cent administration fee = 36500, "
            f"got {invoice['assessed_cents']}"
        )
        assert invoice["variant_basis"] == "TRUEUP", (
            f"a rebilled invoice carries variant_basis TRUEUP, got {invoice['variant_basis']}"
        )

    def test_true_up_records_the_signed_delta_against_the_provisional_figure(
        self, seven_session_true_up
    ):
        """The two variants read the same member differently.

        PRD: "a `RECREATIONAL` member with four billable months, a locker and
        seven returned sessions is assessed 27584 cents provisionally and 36500
        cents on true-up, giving `trueup_cents` of 8916."

        Design: Difficulty/dual_variant_calc/dues_provisional_seasonal_vs_trueup_actual_divergence
        """
        invoice = seven_session_true_up["invoice"]
        assert invoice["trueup_cents"] == 8916, (
            "trueup_cents is 36500 less the 27584 that stood before the rebill, "
            f"expected 8916, got {invoice['trueup_cents']}"
        )
        assert invoice["assessed_cents"] != seven_session_true_up["provisional"]["assessed_cents"], (
            "the usage rebill must diverge from the prorated assessment for "
            "identical member data"
        )

    def test_true_up_counts_only_returned_outings_and_recomputes_the_balance(
        self, seven_session_true_up
    ):
        """Seven completed outings are what the rebill is keyed on.

        PRD: "`logged_session_count` is the number of water sessions in status
        `RETURNED` whose `athlete_member_ids` array contains this member's `id`."

        Design: Difficulty/dual_variant_calc/dues_provisional_seasonal_vs_trueup_actual_divergence
        """
        member = assert_member(seven_session_true_up["member"])
        invoice = seven_session_true_up["invoice"]
        assert member["logged_session_count"] == 7, (
            "seven outings were logged back in, got "
            f"{member['logged_session_count']}"
        )
        assert invoice["status"] == "PARTIALLY_PAID", (
            "a rebill above paid_cents leaves the invoice PARTIALLY_PAID, got "
            f"{invoice['status']}"
        )
        assert member["dues_balance_cents"] == 35500, (
            "the balance is the rebilled 36500 less the 1000 already paid, "
            f"expected 35500, got {member['dues_balance_cents']}"
        )
        assert member["boathouse_access_level"] == "SUPERVISED", (
            "an ACTIVE member still carrying arrears is SUPERVISED, got "
            f"{member['boathouse_access_level']}"
        )
