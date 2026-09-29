"""Multi-step money formulas whose step order is the whole behaviour.

The revenue split reads its fee tier off the pre-fee amount and hands the whole
truncation remainder to one party; the rebate invoice rounds every line before
it adds them up. Both answers change if a step is reordered.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    RebateModel,
    assertions,
    factories as f,
    fixtures as fx,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS


def _partially_collected_env(api) -> fx.Env:
    """An invoice of 54,000 cents with 50,001 cents collected against it.

    The collected figure sits just above the middle admin-fee tier's lower edge
    while the post-fee amount falls back below it, so the two readings of the
    tier table disagree.
    """
    env = fx.executed_contract_env(
        api,
        contract_overrides={"rebate_flat_cents_per_room_night": 1500},
    )
    fx.add_team(env)
    fx.add_registration(env)
    booking_one = fx.add_booking(env, rooms_requested=6)

    team_two = fx.create_team(
        api, name="Bravo SC 14U", org_contact_email="bravo14@example.com"
    )
    registration_two = fx.add_registration(env, team=team_two)
    booking_two = fx.add_booking(env, registration=registration_two, rooms_requested=6)

    for booking in (booking_one, booking_two):
        fx.submit_rooming_list(
            env,
            booking=booking,
            entries=[f.rooming_list_entry(index + 1, occupant_count=2) for index in range(6)],
        )
        fx.confirm_booking(env, booking=booking)

    fx.close_booking_window(env)
    fx.actualize(env, 18, booking=booking_one)
    fx.actualize(env, 18, booking=booking_two)

    fx.create_invoice(env)
    fx.issue_invoice(env)
    fx.remit(env, 50001)
    return env


def _two_percent_lines_env(api) -> fx.Env:
    """Two percent-of-revenue rebate lines that each need rounding.

    Four room nights and six room nights at 14,999 cents and 0.0825 produce
    4,949.67 and 7,424.505 cents, so the per-line and the whole-total rounding
    orders differ by a cent.
    """
    env = fx.executed_contract_env(
        api,
        contract_overrides={
            "negotiated_nightly_rate_cents": 14999,
            "rebate_model": RebateModel.PERCENT_OF_ROOM_REVENUE.value,
            "rebate_percent": 0.0825,
            "rebate_flat_cents_per_room_night": None,
            "attrition_threshold_pct": 0.05,
        },
    )
    fx.add_team(env, name="Riverside FC 14U", org_contact_email="riverside14@example.com")
    fx.add_registration(env, roster_player_count=5, roster_staff_count=1)
    booking_x = fx.add_booking(
        env, rooms_requested=2, check_in_date="2026-09-10", check_out_date="2026-09-12"
    )

    team_y = fx.create_team(
        api, name="Lakeside SC 14U", org_contact_email="lakeside14@example.com"
    )
    registration_y = fx.add_registration(
        env, team=team_y, roster_player_count=5, roster_staff_count=1
    )
    booking_y = fx.add_booking(
        env,
        registration=registration_y,
        rooms_requested=2,
        check_in_date="2026-09-10",
        check_out_date="2026-09-13",
    )

    entries = [f.rooming_list_entry(index + 1, occupant_count=3) for index in range(2)]
    for booking in (booking_x, booking_y):
        fx.submit_rooming_list(env, booking=booking, entries=entries)
        fx.confirm_booking(env, booking=booking)

    fx.close_booking_window(env)
    fx.actualize(env, 4, booking=booking_x)
    fx.actualize(env, 6, booking=booking_y)
    env.bookings = [
        env.refresh_booking(booking_x),
        env.refresh_booking(booking_y),
    ]
    return env


class TestRevenueSplitWaterfall:
    """The six-step split, read in the order the PRD fixes."""

    def test_the_admin_fee_tier_reads_the_collected_amount_not_the_post_fee_amount(
        self, api
    ):
        """50,001 cents collected selects the 0.06 tier even though the
        distributable 47,001 cents would have selected 0.08.

        PRD §3.9: "Step one snapshots `gross_collected_cents` as the source
        invoice's `collected_cents` at that instant."

        PRD §3.9: "Step two selects `admin_fee_pct` from a three-tier table
        **keyed on `gross_collected_cents`**, never on the post-fee amount:
        below 50,000 cents the fee is 0.08; from 50,000 cents up to but not
        including 200,000 cents it is 0.06; at 200,000 cents or above it is
        0.045."

        PRD §3.9: "Step three computes `admin_fee_cents` as
        `gross_collected_cents` multiplied by `admin_fee_pct`, rounded half up
        to a whole cent."

        PRD §3.9: "Step four computes `distributable_cents` as
        `gross_collected_cents` less `admin_fee_cents`."

        Design: Difficulty/combinatorial_formula/revenue_share_split_admin_tier_keyed_on_gross_not_distributable
        """
        env = _partially_collected_env(api)
        assert env.invoice["total_due_cents"] == 54000
        assert env.invoice["status"] == "PARTIALLY_PAID"
        invoice = env.refresh_invoice()

        distribution = validate_success(
            api.create_revenue_distribution(
                f.revenue_distribution_payload(
                    env.tournament_id, invoice["id"], invoice["version"]
                ),
                HM,
            ),
            expected_status=201,
        )

        assert distribution["gross_collected_cents"] == 50001
        assert distribution["admin_fee_pct"] == 0.06
        assert distribution["admin_fee_cents"] == 3000
        assert distribution["distributable_cents"] == 47001

    def test_the_whole_truncation_remainder_is_added_to_the_organizer_bucket(self, api):
        """Truncating 47,001 cents by 0.5, 0.3 and 0.2 loses one cent, and that
        cent goes entirely to the organizer rather than being shared out.

        PRD §3.9: "Step five allocates the three party buckets from
        `distributable_cents` in the fixed order organizer, then rights holder,
        then destination, each by multiplying `distributable_cents` by that
        party's share fraction on the tournament — `share_pct_organizer`,
        `share_pct_rights_holder` and `share_pct_destination` respectively — and
        truncating the product down to a whole cent; the rights-holder and
        destination results are stored directly as `rights_holder_cents` and
        `destination_cents`."

        PRD §3.9: "Step six computes `rounding_remainder_cents` as
        `distributable_cents` less the three truncated allocations, and stores
        `organizer_cents` as the organizer's truncated allocation **plus that
        entire remainder**."

        PRD §3.9: "The remainder is never split between parties, never assigned
        by bucket size, and never assigned by any other rule."

        Design: Difficulty/combinatorial_formula/revenue_share_split_admin_tier_keyed_on_gross_not_distributable
        """
        env = _partially_collected_env(api)
        invoice = env.refresh_invoice()

        distribution = validate_success(
            api.create_revenue_distribution(
                f.revenue_distribution_payload(
                    env.tournament_id, invoice["id"], invoice["version"]
                ),
                HM,
            ),
            expected_status=201,
        )

        assert distribution["rounding_remainder_cents"] == 1
        assert distribution["organizer_cents"] == 23501
        assert distribution["rights_holder_cents"] == 14100
        assert distribution["destination_cents"] == 9400
        assert (
            distribution["organizer_cents"]
            + distribution["rights_holder_cents"]
            + distribution["destination_cents"]
            == distribution["distributable_cents"]
        )
        assert distribution["status"] == "CALCULATED"
        assertions.assert_versioned_record(distribution, expected_version=1)


class TestInvoiceLineRoundingOrder:
    """Every rebate line is rounded before the invoice adds them together."""

    def test_each_rebate_line_is_rounded_to_whole_cents_on_its_own(self, api):
        """4,949.67 becomes 4,950 and 7,424.505 becomes 7,425, one booking at a
        time, before either figure reaches the invoice.

        PRD §3.7: "Under `PERCENT_OF_ROOM_REVENUE`, the line is
        `actualized_room_nights` multiplied by the contract's
        `negotiated_nightly_rate_cents` multiplied by its `rebate_percent`, with
        the product rounded half up to a whole cent."

        PRD §2.7: "Wherever a monetary amount is derived from a multiplication
        involving a fraction, the result is rounded **half up** to a whole cent
        — that is, a computed value whose fractional part is exactly one half
        rounds away from zero to the next whole cent."

        Design: Difficulty/combinatorial_formula/rebate_invoice_round_per_line_then_sum_not_sum_then_round
        """
        env = _two_percent_lines_env(api)
        booking_x, booking_y = env.bookings

        assert booking_x["actualized_room_nights"] == 4
        assert booking_x["rebate_accrued_cents"] == 4950
        assert booking_y["actualized_room_nights"] == 6
        assert booking_y["rebate_accrued_cents"] == 7425

    def test_the_invoice_sums_the_rounded_lines_and_not_the_raw_products(self, api):
        """The invoice reads 12,375 cents; summing the unrounded products first
        would have produced 12,374.

        PRD §3.8: "`invoiced_rebate_cents` is the sum of each scoped booking's
        rebate line, computed exactly as in §3.7 and — this ordering is fixed —
        **rounded to whole cents per line before the lines are summed**."

        PRD §3.8: "Summing unrounded products and rounding the single total at
        the end is not equivalent and can differ by one or more cents from the
        correct answer."

        PRD §3.8: "`invoiced_room_nights` is the sum of `actualized_room_nights`
        across the scope."

        Design: Difficulty/combinatorial_formula/rebate_invoice_round_per_line_then_sum_not_sum_then_round
        """
        env = _two_percent_lines_env(api)

        invoice = validate_success(
            api.create_rebate_invoice(f.rebate_invoice_payload(env.contract_id), HM),
            expected_status=201,
        )

        assert invoice["invoiced_room_nights"] == 10
        assert invoice["invoiced_rebate_cents"] == 12375
        assert invoice["attrition_shortfall_room_nights_per_block"] == 0
        assert invoice["attrition_penalty_cents"] == 0
        assert invoice["total_due_cents"] == 12375
        assertions.assert_rebate_ledger_conserved(invoice)
