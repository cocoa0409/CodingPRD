"""Derived figures: the accrual input set, the pump's block arithmetic, the
settlement tier ladder, the rollover cap and the read-only forecast."""
import pytest

from test_helpers import (
    ADMIN,
    MONTH_WINDOWS,
    api_client,
    assert_gallons_equal,
    assert_instant_equals,
    assert_points_summary,
    factories,
    fixtures,
    validate_paginated,
)

AUGUST_START, AUGUST_END = MONTH_WINDOWS["2026-08"]


def test_the_cap_limits_the_cents_and_the_surplus_points_stay_spendable():
    """The debit is back-derived from the capped cents, so the points the ceiling
    made unusable are never consumed.

    PRD: "That uncapped figure is then capped: at a `PARTNER_STATION` the ceiling
    is the site's own `per_gallon_cap_cents`, and at an `OWNED_FUEL_CENTER` it is
    the banner's `max_cents_off_per_gallon`."

    PRD: "The debit is then **back-derived from the capped cents**, which is the
    whole point of the design: `blocks_effective` is `cents_off_per_gallon` divided
    by `cents_off_per_block`, and `points_debited_at_auth` is `blocks_effective`
    multiplied by `points_per_discount_block`."

    PRD: "Every point the cap made unusable stays in the member's balance rather
    than being consumed and wasted, and so does the sub-block remainder that the
    rounding-down discarded."

    Design: Corner/calculations/redemption_authorization_caps_cents_off_and_refunds_the_uncapped_points
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=2000, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]

    redemption = fixtures.authorize_redemption(
        member_id, program["fuel"]["id"], "6660000001", 1500
    )

    assert redemption["cents_off_per_gallon"] == 100
    assert redemption["points_debited_at_auth"] == 1000
    assert redemption["blocks_effective"] == 10
    assert_gallons_equal(redemption["gallons_authorized"], "35.000")
    assert fixtures.get_member(member_id)["available_points"] == 1000

    rows, meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member_id, "entry_type": "REDEMPTION"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["points_delta"] == -1000


def test_a_partial_block_is_floored_and_its_remainder_is_left_behind():
    """One hundred and forty-nine points buys exactly one block; the forty-nine
    left over are not rounded up into a second.

    PRD: "The offer is first converted to whole discount blocks: the number of
    blocks requested is `points_committed` divided by the banner's
    `points_per_discount_block`, **rounded down** to a whole number."

    PRD: "Those blocks buy an uncapped per-gallon discount equal to the block count
    multiplied by the banner's `cents_off_per_block`."

    Design: Corner/calculations/redemption_authorization_floors_partial_blocks_and_leaves_the_remainder
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]

    redemption = fixtures.authorize_redemption(
        member_id, program["fuel"]["id"], "6660000001", 149
    )

    assert redemption["cents_off_per_gallon"] == 10
    assert redemption["points_debited_at_auth"] == 100
    assert redemption["blocks_effective"] == 1
    assert redemption["points_committed"] == 149
    assert fixtures.get_member(member_id)["available_points"] == 200


def test_a_pharmacy_line_pays_per_script_whatever_the_prescription_cost():
    """Three cheap scripts out-earn one expensive one, because the dollar amount
    plays no part in a pharmacy base.

    PRD: "A `PHARMACY` line ignores `amount_cents` entirely and takes its base as
    the line's `quantity` (the number of scripts) multiplied by the banner's
    `pharmacy_points_per_script`."

    PRD: "A `GIFT_CARD` line takes the banner's `gift_card_multiplier`; a
    `PHARMACY` line takes the banner's `pharmacy_multiplier`; a `GROCERY` line
    takes 1; and a `FUEL`, `TOBACCO` or `ALCOHOL` line takes 0."

    Design: Corner/calculations/pharmacy_accrual_pays_per_script_and_ignores_the_dollar_amount
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_member(
        alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    grocery_id = program["grocery"]["id"]
    basket = fixtures.record_basket(
        program["member"]["id"],
        grocery_id,
        [
            factories.purchase_line("PHARMACY", 12, 3),
            factories.purchase_line("PHARMACY", 90000, 1),
        ],
        "2026-08-01T00:00:00Z",
    )

    posted = fixtures.post_basket(basket["id"], grocery_id)

    assert posted["gross_points_awarded"] == 400
    breakdown = posted["line_points_breakdown"]
    assert [line["line_points"] for line in breakdown] == [300, 100]
    assert [line["category_base_points"] for line in breakdown] == [150, 50]
    assert posted["subtotal_cents"] == 90012
    assert fixtures.get_member(program["member"]["id"])["available_points"] == 400


def test_tobacco_alcohol_and_fuel_lines_count_in_the_subtotal_but_earn_nothing():
    """Three excluded categories keep their money in `subtotal_cents` while
    contributing a zero line award each.

    PRD: "A `FUEL`, `TOBACCO` or `ALCOHOL` line has a base of zero."

    PRD: "Recording immediately computes `subtotal_cents` as the sum of
    `amount_cents` across **every** submitted line, including lines in categories
    that will earn nothing."

    Design: Corner/calculations/tobacco_and_alcohol_lines_are_excluded_from_the_accrual_input_set
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_member(
        alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    grocery_id = program["grocery"]["id"]
    basket = fixtures.record_basket(
        program["member"]["id"],
        grocery_id,
        [
            factories.purchase_line("GROCERY", 10000, 1),
            factories.purchase_line("TOBACCO", 5000, 2),
            factories.purchase_line("ALCOHOL", 3000, 1),
            factories.purchase_line("FUEL", 4000, 10),
        ],
        "2026-08-01T00:00:00Z",
    )
    assert basket["subtotal_cents"] == 22000

    posted = fixtures.post_basket(basket["id"], grocery_id)

    assert posted["gross_points_awarded"] == 100
    assert [line["line_points"] for line in posted["line_points_breakdown"]] == [
        100,
        0,
        0,
        0,
    ]
    assert posted["subtotal_cents"] == 22000
    assert fixtures.get_member(program["member"]["id"])["available_points"] == 100


def _two_thousand_gallon_month(banner_code: str, alt_id: str, extra_thousandth: bool):
    """One partner station whose August pool holds two fills totalling either
    exactly 2000.000 gallons or one thousandth more.

    `max_gallons_per_redemption` is at most a thousand gallons and an
    over-dispense is a hard rejection, so no single authorization can cover
    1000.001 gallons: the volume that straddles the tier edge is assembled from
    two full fills plus, in the high case, one extra thousandth of a gallon.
    That extra thousandth adds nothing to `gross_discount_cents` — 0.001 gallons
    at 10 cents off is 0.01 cents, which rounds half up to zero — so the two
    banners carry an identical gross and differ only in `gallons_total`.
    """
    program = fixtures.partner_fuel_program(
        points=700,
        alt_id=alt_id,
        per_gallon_cap_cents=30,
        max_gallons_per_redemption=1000,
        banner_code=banner_code,
        name=f"{banner_code} Banner",
    )
    fixtures.add_dispensed_fill(program, 300, 1000.0)
    fixtures.add_dispensed_fill(program, 300, 1000.0)
    if extra_thousandth:
        fixtures.add_dispensed_fill(program, 100, 0.001)
    program["batch"] = fixtures.open_batch(
        program["partner"]["id"], AUGUST_START, AUGUST_END
    )
    return program


def test_exactly_two_thousand_gallons_settles_a_band_below_the_next_thousandth():
    """Identical gross discounts price differently because the ladder reads
    gallons: 2000.000 stays mid while 2000.001 is high.

    PRD: "`tier_rate_pct` is selected from the **whole** `gallons_total` as a flat
    rate on the entire volume, never marginally band by band."

    PRD: "The band edges are inclusive upper bounds of the lower band, so a total
    of exactly 500.000 gallons is still the low tier and the mid tier begins at
    500.001, while exactly 2,000.000 gallons is still the mid tier and the high
    tier begins at 2,000.001."

    Design: Corner/calculations/settlement_tier_boundary_splits_two_thousand_gallons_from_the_next_thousandth
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    mid_program = _two_thousand_gallon_month(
        "MID", "6660000001", extra_thousandth=False
    )
    high_program = _two_thousand_gallon_month(
        "HIGH", "6660000002", extra_thousandth=True
    )

    mid = fixtures.submit_batch(
        mid_program["batch"]["id"], mid_program["partner"]["id"]
    )
    high = fixtures.submit_batch(
        high_program["batch"]["id"], high_program["partner"]["id"]
    )

    assert mid["gross_discount_cents"] == 60000
    assert high["gross_discount_cents"] == 60000
    assert_gallons_equal(mid["gallons_total"], "2000.000")
    assert_gallons_equal(high["gallons_total"], "2000.001")

    assert mid["tier_rate_pct"] == pytest.approx(0.90, abs=0.0001)
    assert mid["pre_fee_reimbursement_cents"] == 54000
    assert mid["admin_fee_cents"] == 810
    assert mid["reimbursement_cents"] == 53190

    assert high["tier_rate_pct"] == pytest.approx(0.95, abs=0.0001)
    assert high["pre_fee_reimbursement_cents"] == 57000
    assert high["admin_fee_cents"] == 855
    assert high["reimbursement_cents"] == 56145


def test_the_sweep_rescues_only_up_to_the_banner_rollover_cap():
    """Seven hundred expiring points produce a full debit and a capped credit
    rather than one netted row.

    PRD: "An eligible member rolls over the lesser of their expiring remainder and
    the banner's `rollover_cap_points`; an ineligible member rolls over nothing."

    PRD: "When the expired amount is greater than zero, one `EXPIRY` row is
    appended whose `points_delta` is the negation of the **full** expiring
    remainder — not of the expired portion — with `point_cycle_id` set to the
    closing cycle and `lot_expires_at` null."

    PRD: "When the rolled-over amount is greater than zero, one `ROLLOVER` row is
    appended whose `points_delta` is the positive rolled-over amount, with
    `point_cycle_id` set to the closing cycle and `lot_expires_at` set to the
    **next** cycle's `closes_at`."

    Design: Corner/calculations/expiry_sweep_rolls_over_only_up_to_the_banner_cap_for_an_eligible_member
    """
    fixtures.set_clock("2026-07-15T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    cycles = fixtures.create_month_cycles(
        banner["id"], ("2026-07", "2026-08", "2026-09")
    )
    grocery = fixtures.create_grocery_site(banner["id"], "G-100")
    member = fixtures.create_member(banner["id"], alt_id="6660000001")
    household = fixtures.create_household(banner["id"], "HH-CORE-1")
    fixtures.create_link(household["id"], member["id"], "PRIMARY", activate=True)
    fixtures.accrue_points(member["id"], grocery["id"], 700, "2026-07-15T00:00:00Z")
    july = fixtures.run_close(cycles["2026-07"]["id"], "2026-08-01T00:00:00Z")
    assert july["expired_points_total"] == 0

    august = fixtures.run_close(cycles["2026-08"]["id"], "2026-09-01T00:00:00Z")

    assert august["expired_points_total"] == 200
    assert august["rolled_over_points_total"] == 500
    assert august["swept_member_count"] == 1

    expiries, expiry_meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member["id"], "entry_type": "EXPIRY"}
        )
    )
    assert expiry_meta["total_count"] == 1
    assert expiries[0]["points_delta"] == -700
    assert expiries[0]["lot_expires_at"] is None

    rollovers, rollover_meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member["id"], "entry_type": "ROLLOVER"}
        )
    )
    assert rollover_meta["total_count"] == 1
    assert rollovers[0]["points_delta"] == 500
    assert_instant_equals(rollovers[0]["lot_expires_at"], "2026-09-30T23:59:59.999Z")

    assert fixtures.get_member(member["id"])["available_points"] == 500


def test_the_forecast_separates_spendable_points_from_committed_ones():
    """The read reports the standing authorization as pending rather than
    spendable, and it writes nothing at all.

    PRD: "It reports the member's `member_id`, their current `available_points`,
    the `open_cycle_id` of the banner's open cycle containing the logical clock,
    their `pending_authorized_points` (the sum of `points_debited_at_auth` over
    that member's redemptions still in `AUTHORIZED` status), their
    `projected_expiring_points` and `projected_rollover_points` (the expiring
    remainder and the rescued amount the sweep **would** produce for this member
    against the open cycle, computed with the banner's `expiry_basis` honoured
    exactly as above), and their `projected_available_after_close` (their
    `available_points` minus `projected_expiring_points`)."

    PRD: "This forecast must never append a ledger row and never advance any
    `version`."

    Design: Corner/calculations/points_summary_projection_reports_pending_authorizations_without_writing
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=500, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    fixtures.authorize_redemption(member_id, program["fuel"]["id"], "6660000001", 300)
    version_before = fixtures.member_version(member_id)

    summary = fixtures.points_summary(member_id)

    assert summary["member_id"] == member_id
    assert summary["open_cycle_id"] == program["cycles"]["2026-08"]["id"]
    assert_points_summary(
        summary,
        available_points=200,
        pending_authorized_points=300,
        projected_expiring_points=0,
        projected_rollover_points=0,
        projected_available_after_close=200,
    )

    assert fixtures.member_version(member_id) == version_before
    _rows, meta = validate_paginated(
        api_client.list_point_ledger_entries(ADMIN, {"member_id": member_id})
    )
    assert meta["total_count"] == 2
