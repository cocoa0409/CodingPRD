"""Fee assessment on submission: the donor surcharge's pinned rounding order and the
expedite tier that is keyed on the subtotal rather than on the running total.

Both quantities are one arithmetic decision away from a plausible wrong answer — a
single cent in the donor surcharge, and three hundred cents in the expedite tier — so
each is exercised against the figure the pinned order produces.
"""

import pytest

from test_helpers import (
    BASE_APPLICATION_FEE_CENTS,
    EXPEDITE_TIER_1_CEILING,
    add_photo_set,
    assert_application,
    assert_fee_ledger_closes,
    file_parts_document,
    issue_title,
    read_application,
    read_fee_quote,
    read_rebuilder,
    register_vehicle,
    setup_draft_application,
    submit_application,
    verify_parts_document,
)


def _donor_source() -> dict:
    """A donor vehicle holding an unbranded active title, usable as a traceable source."""
    donor_vehicle = register_vehicle(
        body_class="TRAILER", make="Wells", model="Cargo", model_year=2015
    )
    donor_title = issue_title(donor_vehicle["id"], owner_name="Pine Salvage Yard")
    return {"vin": donor_vehicle["vin"], "title_id": donor_title["id"]}


def _trailer_application_with_donor_lines(amounts, expedite_requested=False) -> dict:
    """A trailer application carrying one verified used-donor powertrain line per amount.

    A trailer requires no part class at all, so the documentation gate is satisfied from
    the moment the application exists and the only surcharge in play is the donor one.
    """
    donor = _donor_source()
    env = setup_draft_application(
        body_class="TRAILER", expedite_requested=expedite_requested
    )
    env["donor_documents"] = []
    for index, amount_cents in enumerate(amounts, start=1):
        document = file_parts_document(
            env["application_id"],
            env["rebuilder_id"],
            doc_type="PARTS_INVOICE",
            part_class="POWERTRAIN",
            source_type="USED_DONOR",
            amount_cents=amount_cents,
            vendor_name="Pine Salvage Yard",
            part_serial_number=f"PT-{index}",
            donor_vin=donor["vin"],
            donor_title_id=donor["title_id"],
        )
        env["donor_documents"].append(
            verify_parts_document(document["id"], env["inspector_id"])
        )
    add_photo_set(env)
    return env


class TestDonorSurchargeRoundingOrder:
    """Each donor line is rounded before the lines are summed."""

    def test_three_donor_lines_are_rounded_individually_before_summation(self):
        """Three 12,499-cent donor lines assess 8,061 cents, one cent below the summed order.

        PRD: "The rounding order here is pinned and is not interchangeable: rounding each line first and then summing is the specified behaviour, and summing the raw amounts and rounding the product once would produce a different figure — three lines of 12,499 cents each round to 187 cents apiece for a donor surcharge of 561 cents, whereas rounding a single summed product would give 562."

        Design: Difficulty/combinatorial_formula/donor_surcharge_rounds_each_line_before_summation
        """
        env = _trailer_application_with_donor_lines([12_499, 12_499, 12_499])

        application = submit_application(env["application_id"], env["rebuilder_id"])

        assert_application(application)
        assert application["documented_parts_cost_cents"] == 37_497, (
            "the three verified lines must sum to 37497, got "
            f"{application['documented_parts_cost_cents']}"
        )
        assert application["assessed_fee_cents"] == 8_061, (
            "7500 base plus a per-line-rounded donor surcharge of 561 must assess 8061, got "
            f"{application['assessed_fee_cents']}"
        )
        assert application["assessed_fee_cents"] != 8_062, (
            "summing the raw amounts and rounding once is the wrong order and would assess 8062"
        )
        assert application["documentation_completeness_pct"] == pytest.approx(
            100.00, abs=0.01
        ), (
            "a trailer requires no part class, so completeness is 100.00, got "
            f"{application['documentation_completeness_pct']}"
        )
        assert application["status"] == "SUBMITTED", (
            f"a successful submission lands in SUBMITTED, got {application['status']}"
        )
        assert application["fee_escrowed_cents"] == 8_061, (
            "with no expedite and no re-inspection the escrow equals the assessment, got "
            f"{application['fee_escrowed_cents']}"
        )

    def test_a_single_donor_line_of_the_summed_amount_assesses_one_cent_more(self):
        """One 37,497-cent line rounds once and assesses 8,062 cents.

        PRD: "For each such document the program multiplies that document's `amount_cents` by the donor-part surcharge rate of one and a half percent and rounds the product half up to a whole number of cents; only after every line has been rounded individually are the rounded line values added together."

        Design: Difficulty/combinatorial_formula/donor_surcharge_rounds_each_line_before_summation
        """
        env = _trailer_application_with_donor_lines([37_497])

        application = submit_application(env["application_id"], env["rebuilder_id"])

        assert application["documented_parts_cost_cents"] == 37_497, (
            "the single verified line must be documented at 37497, got "
            f"{application['documented_parts_cost_cents']}"
        )
        assert application["assessed_fee_cents"] == 8_062, (
            "one line of 37497 rounds to a 562-cent surcharge, so the assessment is 8062, got "
            f"{application['assessed_fee_cents']}"
        )
        assert application["assessed_fee_cents"] - BASE_APPLICATION_FEE_CENTS == 562, (
            "the surcharge above the base fee must be 562, got "
            f"{application['assessed_fee_cents'] - BASE_APPLICATION_FEE_CENTS}"
        )
        assert len(env["donor_documents"]) == 1, "the contrast case files exactly one line"
        assert env["donor_documents"][0]["traceable"] is True, (
            "a used-donor line naming a donor title is traceable"
        )


class TestExpediteTierKeyedOnSubtotal:
    """The expedite rate is chosen by the subtotal, never by the charge it produces."""

    def test_subtotal_below_the_first_ceiling_draws_the_ten_percent_rate(self):
        """A 9,800-cent subtotal charges 10,780, not the 10,486 a running-total tier would give.

        PRD: "Keying either tier on the running total rather than on the subtotal is the circular reading and produces the wrong answer; the inputs are the application's own `assessed_fee_cents` and `attempts_completed` — counting only attempts that reached `COMPLETED_PASS` or `COMPLETED_FAIL`, never `CANCELLED` ones — together with the rebuilder's `applications_titled_count` as it stands at the instant of the call."

        Design: Difficulty/combinatorial_formula/expedite_tier_keyed_on_subtotal_not_on_running_total
        """
        env = _trailer_application_with_donor_lines([153_333], expedite_requested=True)

        application = submit_application(env["application_id"], env["rebuilder_id"])

        assert application["expedite_requested"] is True, (
            "the application was opened with the expedite requested"
        )
        assert application["attempts_completed"] == 0, (
            f"no attempt has been completed yet, got {application['attempts_completed']}"
        )
        assert application["assessed_fee_cents"] == 9_800, (
            "7500 base plus a 2300 donor surcharge must assess 9800, got "
            f"{application['assessed_fee_cents']}"
        )
        assert application["total_program_charge_cents"] == 10_780, (
            "a 9800 subtotal draws ten percent, so the charge is 10780, got "
            f"{application['total_program_charge_cents']}"
        )
        assert application["total_program_charge_cents"] != 10_486, (
            "keying the tier on the running total of 10780 is the circular reading and would "
            "charge 10486"
        )
        assert application["fee_escrowed_cents"] == 10_780, (
            "the escrow equals the freshly computed charge, got "
            f"{application['fee_escrowed_cents']}"
        )
        assert application["status"] == "SUBMITTED", (
            f"a successful submission lands in SUBMITTED, got {application['status']}"
        )

        rebuilder = read_rebuilder(env["rebuilder_id"])
        assert rebuilder["escrowed_fee_total_cents"] == 10_780, (
            "the rebuilder's escrow total rises by the charge, got "
            f"{rebuilder['escrowed_fee_total_cents']}"
        )
        assert rebuilder["fee_balance_cents"] == 489_220, (
            "the 500000 deposit less the 10780 charge leaves 489220, got "
            f"{rebuilder['fee_balance_cents']}"
        )
        assert_fee_ledger_closes(rebuilder)

    def test_subtotal_of_exactly_the_first_ceiling_draws_the_seven_percent_rate(self):
        """A subtotal of exactly 10,000 cents is not below the ceiling and charges 10,700.

        PRD: "The expedite tier is then selected *by the subtotal*, never by any running total: a subtotal below 10,000 cents draws a ten percent expedite rate, a subtotal below 25,000 cents draws seven percent, and a subtotal of 25,000 cents or more draws five percent."

        Design: Difficulty/combinatorial_formula/expedite_tier_keyed_on_subtotal_not_on_running_total
        """
        env = _trailer_application_with_donor_lines([166_666], expedite_requested=True)

        application = submit_application(env["application_id"], env["rebuilder_id"])

        assert application["assessed_fee_cents"] == 10_000, (
            "7500 base plus a 2500 donor surcharge must assess 10000, got "
            f"{application['assessed_fee_cents']}"
        )
        assert application["assessed_fee_cents"] == EXPEDITE_TIER_1_CEILING, (
            "the subtotal must land exactly on the first expedite ceiling, got "
            f"{application['assessed_fee_cents']}"
        )
        assert application["total_program_charge_cents"] == 10_700, (
            "a subtotal of exactly 10000 is not below the ceiling, so seven percent applies and "
            f"the charge is 10700, got {application['total_program_charge_cents']}"
        )
        assert application["total_program_charge_cents"] != 11_000, (
            "ten percent belongs to subtotals strictly below 10000"
        )
        assert application["fee_escrowed_cents"] == 10_700, (
            f"the escrow equals the charge, got {application['fee_escrowed_cents']}"
        )

    def test_the_fee_quote_publishes_the_subtotal_the_tier_was_keyed_on(self):
        """The non-mutating quotation exposes a 9,800 subtotal beside a 980 expedite fee.

        PRD: "It exposes every intermediate of the charge computation side by side — `assessed_fee_cents`, `subtotal_cents`, `expedite_fee_cents`, `discount_cents` and `total_program_charge_cents` — and it never changes the application."

        Design: Difficulty/combinatorial_formula/expedite_tier_keyed_on_subtotal_not_on_running_total
        """
        env = _trailer_application_with_donor_lines([153_333], expedite_requested=True)
        submitted = submit_application(env["application_id"], env["rebuilder_id"])

        quote = read_fee_quote(env["application_id"])

        assert quote["assessed_fee_cents"] == 9_800, (
            f"the quotation must restate the 9800 assessment, got {quote['assessed_fee_cents']}"
        )
        assert quote["subtotal_cents"] == 9_800, (
            "with no completed attempt the subtotal equals the assessment, got "
            f"{quote['subtotal_cents']}"
        )
        assert quote["expedite_fee_cents"] == 980, (
            "ten percent of the 9800 subtotal is 980, got "
            f"{quote['expedite_fee_cents']}"
        )
        assert quote["discount_cents"] == 0, (
            "a rebuilder with no titled application earns no volume discount, got "
            f"{quote['discount_cents']}"
        )
        assert quote["total_program_charge_cents"] == 10_780, (
            f"the quoted charge must be 10780, got {quote['total_program_charge_cents']}"
        )

        after = read_application(env["application_id"])
        assert after["version"] == submitted["version"], (
            "reading the quotation must not mutate the application: version moved from "
            f"{submitted['version']} to {after['version']}"
        )
        assert after["total_program_charge_cents"] == 10_780, (
            "the stored charge must be unchanged by the quotation, got "
            f"{after['total_program_charge_cents']}"
        )
