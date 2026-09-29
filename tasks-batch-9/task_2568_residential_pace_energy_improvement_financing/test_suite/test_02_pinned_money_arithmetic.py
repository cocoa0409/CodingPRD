"""Money compositions whose intermediate rounding order the PRD pins step by step.

These tests reproduce the schedule, the payoff waterfall and the penalty accrual
from their declared constants and assert the exact cent figures, so that any
alternative but plausible ordering of the same arithmetic is rejected.
"""

from decimal import Decimal

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.test_users import COUNTY_OFFICER


def test_amortization_quantizes_interest_first_and_absorbs_drift_in_the_last_year(client):
    """Every schedule row rounds interest first, then derives principal by subtraction.

    For each year from 1 through `term_years`, in ascending order: compute
    `interest_cents` as the running balance multiplied by the rate, rounded half up
    to whole cents — the interest is quantized **first**; then derive `principal_cents`
    by subtracting that already-rounded interest from `annual_installment_cents`,
    except in the final year, where `principal_cents` is set to the entire remaining
    balance so the last line absorbs every accumulated rounding drift.

    Design: Difficulty/combinatorial_formula/amortization_interest_first_rounding_order_pinned
    """
    world = fixtures.funded_project(client)
    agreement = fixtures.read_agreement(client, world)
    A.assert_fields(
        agreement,
        principal_cents=4200000,
        admin_fee_cents=105000,
        county_recording_fee_cents=9500,
        financed_amount_cents=4314500,
        contractor_payable_cents=4200000,
        term_years=20,
        apr_bps=800,
        annual_installment_cents=439441,
    )

    fixtures.assessed_project(client, world, first_tax_year=2027)
    A.assert_fields(
        fixtures.read_assessment(client, world),
        original_principal_cents=4314500,
        principal_balance_cents=4314500,
        first_tax_year=2027,
        final_tax_year=2046,
        term_years=20,
        annual_installment_cents=439441,
    )

    rows = fixtures.schedule_of(client, world)
    assert len(rows) == 20
    assert [row["sequence"] for row in rows] == list(range(1, 21))
    assert [row["tax_year"] for row in rows] == list(range(2027, 2047))
    for row in rows:
        assert row["due_on"] == "{0}-12-10".format(row["tax_year"])
        assert row["servicing_fee_cents"] == 4000
        assert row["status"] == "SCHEDULED"

    A.assert_installment_row(rows[0], 1, 2027, 94281, 345160)
    A.assert_installment_row(rows[1], 2, 2028, 101823, 337618)
    # The final year is 22 cents above the level payment; it absorbs the drift.
    A.assert_installment_row(rows[19], 20, 2046, 406910, 32553)
    assert rows[19]["total_due_cents"] == 443463
    assert rows[0]["total_due_cents"] == 443441
    assert rows[1]["total_due_cents"] == 443441

    assert sum(row["principal_cents"] for row in rows) == 4314500
    assert sum(row["interest_cents"] for row in rows) == 4474342
    assert sum(row["total_due_cents"] for row in rows) == 8868842


def test_only_the_final_schedule_row_departs_from_the_level_payment(client):
    """The three self-check guarantees of the generated schedule all hold at once.

    Three guarantees follow and can be used as a self-check: the principal components
    sum to exactly `original_principal_cents`, the running balance ends at exactly 0,
    and only the final `total_due_cents` may differ from the others.

    Design: Difficulty/combinatorial_formula/amortization_interest_first_rounding_order_pinned
    """
    world = fixtures.assessed_project(client, first_tax_year=2027)
    rows = fixtures.schedule_of(client, world)

    A.assert_schedule_conserves_principal(rows, 4314500)

    level = rows[0]["total_due_cents"]
    for row in rows[:-1]:
        assert row["total_due_cents"] == level
    assert rows[-1]["total_due_cents"] != level

    # Replaying the interest-first recurrence must land on the stored figures.
    balance = 4314500
    for row in rows:
        interest = A.round_half_up(Decimal(balance) * Decimal(800) / Decimal(10000))
        assert row["interest_cents"] == interest
        balance -= row["principal_cents"]
    assert balance == 0

    for row in rows:
        assert row["billed_on"] is None
        assert row["paid_on"] is None
        assert row["paid_amount_cents"] == 0
        assert row["penalty_cents"] == 0
        assert row["months_past_due"] == 0


def _large_assessed_project(client, first_tax_year=2027):
    """A 4800000-cent principal, chosen so the payoff base lands near a tier ceiling."""
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    fixtures.open_draft_application(client, world, 20)
    solar = A.expect_created(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                world["solar_product_id"],
                fixtures.current_version(client, world),
                3600000,
                280000,
            ),
            world["owner_headers"],
        )
    )
    world["solar_measure_id"] = solar["id"]
    hvac = A.expect_created(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                world["hvac_product_id"],
                fixtures.current_version(client, world),
                1200000,
                100000,
            ),
            world["owner_headers"],
        )
    )
    world["hvac_measure_id"] = hvac["id"]
    fixtures.submitted_application(client, world)
    fixtures.funded_project(client, world, principal_cents=4800000)
    fixtures.assessed_project(client, world, first_tax_year=first_tax_year)
    # A payoff quote requires billing_status ON_ROLL, and "on its first billing an
    # assessment advances billing_status from PENDING_ROLL to ON_ROLL".  The first
    # year is billed well ahead of its December due date, so nothing sweeps.
    fixtures.move_clock(client, "2026-09-01T00:00:00Z")
    A.expect_ok(
        client.run_county_roll(
            "06073",
            factories.roll_run_payload(first_tax_year, "2026-09-01"),
            COUNTY_OFFICER,
        )
    )
    return world


def test_payoff_premium_tier_is_selected_from_the_base_not_from_the_total(client):
    """A base just under 5000000 takes the 200 bps tier though the total exceeds it.

    **Step five** selects the prepayment premium tier *from that base*:
    `prepayment_premium_bps` is 0 when `base_payoff_cents` is below 1000000 cents, 200
    when it is below 5000000 cents, and 350 otherwise.

    Design: Difficulty/combinatorial_formula/payoff_premium_tier_keyed_on_base_not_total
    """
    world = _large_assessed_project(client)
    assert fixtures.read_assessment(client, world)["interest_accrual_from"] == "2026-08-20"

    fixtures.move_clock(client, "2026-10-01T00:00:00Z")
    fixtures.payoff_quote(client, world, "2026-10-01", mode="PAYOFF_AT_CLOSING")
    transfer = fixtures.read_transfer(client, world)

    # 42 days actual/365 on a 4929500 balance at 800 bps.
    A.assert_payoff_composition(transfer, 4929500, 45378, 200)
    A.assert_fields(
        transfer,
        base_payoff_cents=4982378,
        prepayment_premium_cents=99648,
        payoff_total_cents=5082026,
        status="QUOTED",
        quoted_at="2026-10-01T00:00:00Z",
        good_through_date="2026-10-31",
        mode="PAYOFF_AT_CLOSING",
    )
    # The circular reading, which would key the tier on the total, is excluded.
    assert transfer["prepayment_premium_bps"] != 350
    assert transfer["prepayment_premium_cents"] != 174383
    assert transfer["payoff_total_cents"] != 5156761

    A.assert_fields(
        fixtures.read_assessment(client, world),
        transfer_status="QUOTED",
        principal_balance_cents=4929500,
    )


def test_a_total_above_the_tier_ceiling_does_not_promote_the_premium_tier(client):
    """The base stays 335 cents below the ceiling while the total clears it by 99658.

    Keying the tier on the base rather than on the total is deliberate and pinned —
    using the total would be circular, since the total depends on the premium the tier
    selects.

    Design: Difficulty/combinatorial_formula/payoff_premium_tier_keyed_on_base_not_total
    """
    world = _large_assessed_project(client)
    fixtures.move_clock(client, "2026-10-01T00:00:00Z")
    # 58 days of accrual: base 4999665, only 335 cents short of the 350 bps tier.
    fixtures.payoff_quote(client, world, "2026-10-17", mode="PAYOFF_AT_CLOSING")
    transfer = fixtures.read_transfer(client, world)

    A.assert_payoff_composition(transfer, 4929500, 62665, 200)
    A.assert_fields(
        transfer,
        base_payoff_cents=4999665,
        prepayment_premium_cents=99993,
        payoff_total_cents=5099658,
    )
    assert transfer["base_payoff_cents"] < 5000000
    assert transfer["payoff_total_cents"] > 5000000
    assert transfer["prepayment_premium_bps"] == 200


def _two_years_past_due(client):
    """The 2027 installment is a year late and the 2028 one is five days late."""
    world = fixtures.assessed_project(client, first_tax_year=2027)
    fixtures.move_clock(client, "2027-10-01T00:00:00Z")
    A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2027, "2027-10-01"), COUNTY_OFFICER
        )
    )
    fixtures.move_clock(client, "2028-12-15T00:00:00Z")
    world["roll_run"] = A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2028, "2028-12-15"), COUNTY_OFFICER
        )
    )
    return world


def test_penalty_floor_and_cap_bound_the_two_swept_installments(client):
    """One row is clipped by the 2400 bps cap while the other sits on the 1000 bps floor.

    The raw rate is 1000 basis points plus 150 basis points per whole month past due.
    The cap is 3000 basis points when the assessment's `lien_status` is already
    `LIEN_SALE_REFERRED` and 2400 otherwise, and the applied rate is the lesser of the
    raw rate and that cap.

    Design: Difficulty/combinatorial_formula/delinquency_penalty_floor_cap_and_referral_composition
    """
    world = _two_years_past_due(client)
    A.assert_fields(
        world["roll_run"],
        billed_installment_count=1,
        delinquent_installment_count=2,
        total_penalty_cents=150770,
    )

    rows = fixtures.schedule_of(client, world)
    late = A.find_installment(rows, 2027)
    fresh = A.find_installment(rows, 2028)
    # 371 days -> 12 whole months -> raw 2800 bps, clipped to 2400.
    A.assert_fields(late, status="DELINQUENT", months_past_due=12, penalty_cents=106426)
    assert A.round_half_up(Decimal(443441) * Decimal(2800) / Decimal(10000)) == 124163
    # 5 days -> 0 whole months -> the bare 1000 bps floor.
    A.assert_fields(fresh, status="DELINQUENT", months_past_due=0, penalty_cents=44344)

    # Referral happens in step three, after both rows were priced in step two.
    A.assert_fields(
        fixtures.read_assessment(client, world),
        lien_status="LIEN_SALE_REFERRED",
        billing_status="ON_ROLL",
        delinquent_installment_count=2,
        accrued_penalty_cents=150770,
    )
    assert late["penalty_cents"] + fresh["penalty_cents"] == 150770


def test_referral_fee_is_added_after_the_cap_and_never_re_prices_older_rows(client):
    """A later run adds the flat 15000 on the referred branch and leaves stamped rows alone.

    Finally, where the assessment's `lien_status` is `LIEN_SALE_REFERRED`, a flat 15000
    cents is added *after* the cap has been applied, so the referral fee is never itself
    capped.

    Design: Difficulty/combinatorial_formula/delinquency_penalty_floor_cap_and_referral_composition
    """
    world = _two_years_past_due(client)
    fixtures.move_clock(client, "2029-12-15T00:00:00Z")
    third_run = A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2029, "2029-12-15"), COUNTY_OFFICER
        )
    )
    A.assert_fields(
        third_run,
        billed_installment_count=1,
        delinquent_installment_count=1,
        total_penalty_cents=59344,
    )

    rows = fixtures.schedule_of(client, world)
    referred_row = A.find_installment(rows, 2029)
    A.assert_fields(
        referred_row, status="DELINQUENT", months_past_due=0, penalty_cents=59344
    )
    assert referred_row["penalty_cents"] == 44344 + 15000

    # Penalties stamped by the previous run keep their original figures.
    A.assert_fields(A.find_installment(rows, 2027), penalty_cents=106426, months_past_due=12)
    A.assert_fields(A.find_installment(rows, 2028), penalty_cents=44344, months_past_due=0)

    A.assert_fields(
        fixtures.read_assessment(client, world),
        lien_status="LIEN_SALE_REFERRED",
        delinquent_installment_count=3,
        accrued_penalty_cents=210114,
    )
