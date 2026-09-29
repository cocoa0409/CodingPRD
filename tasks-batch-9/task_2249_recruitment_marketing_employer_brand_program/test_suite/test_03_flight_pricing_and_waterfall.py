"""Media-flight pricing in its pinned order, and the ledger that funds it."""
from test_helpers import assertions as a
from test_helpers import fixtures as fx


def _social_program(api):
    """A program funded only through its social pool, with a draft posting to point at."""
    program = fx.create_program(api, pool_social_cents=1000000, flex_reserve_cents=0)
    family = fx.create_job_family(api, program["id"], dedicated_budget_cents=0)
    channel = fx.create_channel(
        api, program["id"], name="Social B", channel_type="SOCIAL"
    )
    posting = fx.create_posting(api, family["id"])
    return program, family, channel, posting


def _three_bucket_program(api):
    """Funding split so that one flight must draw dedicated, then pool, then flex."""
    program = fx.create_program(
        api, pool_job_board_cents=200000, flex_reserve_cents=100000
    )
    family = fx.create_job_family(api, program["id"], dedicated_budget_cents=100000)
    channel = fx.create_channel(api, program["id"])
    posting = fx.create_posting(api, family["id"])
    return program, family, channel, posting


def _reserve_seven_day_flight(api, program, family, channel, posting, **overrides):
    return fx.reserve_flight(
        api,
        channel["id"],
        family["id"],
        posting["id"],
        fx.program_version(api, program["id"]),
        start_date="2026-08-01",
        end_date="2026-08-08",
        daily_cap_cents=50000,
        **overrides,
    )


def test_flight_price_tiers_on_base_gross_and_charges_the_fee_on_the_net(api):
    """PRD §3.4: "Step two fixes `cost_tier` from `base_gross_cents` alone: the tier is
    `TIER_1` when `base_gross_cents` is below 500,000 cents (five thousand dollars), `TIER_2`
    when it is at least 500,000 cents but below 2,000,000 cents (twenty thousand dollars), and
    `TIER_3` when it is at least 2,000,000 cents."
    PRD §3.4: "Step five computes `platform_fee_cents` as that net media amount multiplied by
    the fee rate for the channel's type at the flight's tier, **rounded half up** to a whole
    cent."
    PRD §3.4: "On a `SOCIAL` channel it is 6 percent at `TIER_1`, 5 percent at `TIER_2` and 4
    percent at `TIER_3`."

    Design: Difficulty/combinatorial_formula/flight_pricing_pins_tier_from_base_gross_and_fee_on_net_mode_c
    """
    program, family, channel, posting = _social_program(api)

    flight = fx.reserve_flight(
        api,
        channel["id"],
        family["id"],
        posting["id"],
        fx.program_version(api, program["id"]),
        start_date="2026-08-01",
        end_date="2026-08-09",
        daily_cap_cents=65000,
    )

    a.assert_flight_pricing(
        flight,
        flight_days=8,
        base_gross_cents=520000,
        cost_tier="TIER_2",
        volume_discount_cents=26000,
        platform_fee_cents=24700,
        total_cost_cents=518700,
    )
    assert flight["state"] == "RESERVED", flight
    a.assert_cents(flight["reserved_cents"], 518700, "reserved_cents")
    entries = fx.ledger_entries_for_source(api, flight["id"])
    assert len(entries) == 1, entries
    a.assert_ledger_entry(
        entries[0],
        bucket="POOL_SOCIAL",
        entry_type="RESERVE",
        delta_cents=518700,
        reason="FLIGHT_RESERVATION",
        source_type="MEDIA_FLIGHT",
        source_id=flight["id"],
    )
    a.assert_program_budget(
        fx.read_program(api, program["id"]),
        committed_budget_cents=518700,
        available_budget_cents=481300,
    )


def test_flight_price_never_retiers_on_the_discounted_amount_nor_taxes_the_gross(api):
    """PRD §3.4: "The tier is never re-derived from the post-discount amount: a discount can
    push a `TIER_2` flight's net below 500,000 cents, and an implementation that re-tiered at
    that point would apply a `TIER_1` fee rate."
    PRD §3.4: "And the platform fee is never charged on `base_gross_cents`; its base is always
    the post-discount net media amount."
    PRD §3.4: "Step three computes `volume_discount_cents` as `base_gross_cents` multiplied by
    the tier's discount rate and **rounded down** to a whole cent, where the discount rate is 0
    percent at `TIER_1`, 5 percent at `TIER_2` and 8 percent at `TIER_3`."

    Design: Difficulty/combinatorial_formula/flight_pricing_pins_tier_from_base_gross_and_fee_on_net_mode_c
    """
    program, family, channel, posting = _social_program(api)

    flight = fx.reserve_flight(
        api,
        channel["id"],
        family["id"],
        posting["id"],
        fx.program_version(api, program["id"]),
        start_date="2026-08-01",
        end_date="2026-08-09",
        daily_cap_cents=65000,
    )

    a.assert_cents(flight["total_cost_cents"], 518700, "total_cost_cents")
    assert flight["total_cost_cents"] != 523640, (
        "the platform fee was charged on base gross rather than on the net media amount"
    )
    assert flight["total_cost_cents"] != 520000, (
        "the discount and the fee cancelled out, so one of the two steps was skipped"
    )
    assert flight["cost_tier"] == "TIER_2", (
        "the tier must come from base gross, not from the post-discount net"
    )
    a.assert_cents(
        flight["base_gross_cents"] - flight["volume_discount_cents"], 494000, "net media"
    )
    a.assert_family_reservation(
        fx.read_job_family(api, family["id"]),
        reserved_cents=0,
        dedicated_available_cents=0,
    )


def test_reservation_draws_dedicated_then_pool_then_flex_in_bucket_order(api):
    """PRD §2.6: "For a media flight the bucket order is: the family-dedicated bucket first,
    then exactly one channel-type pool chosen by the channel's `channel_type` (the job-board
    pool when the type is `JOB_BOARD`, the social pool when it is `SOCIAL`, the programmatic
    pool when it is `PROGRAMMATIC`), then the flex reserve."
    PRD §2.6: "When the walk succeeds, one `BudgetLedgerEntry` is written per contributing
    bucket, in bucket order, with ascending `sequence_no`."

    Design: Difficulty/compensating_invariant/budget_cents_are_conserved_across_a_three_bucket_reservation_and_its_cancellation
    """
    program, family, channel, posting = _three_bucket_program(api)

    flight = _reserve_seven_day_flight(api, program, family, channel, posting)

    a.assert_cents(flight["total_cost_cents"], 360500, "total_cost_cents")
    entries = fx.ledger_entries_for_source(api, flight["id"])
    a.assert_ledger_buckets(
        entries,
        [
            ("FAMILY_DEDICATED", "RESERVE", 100000),
            ("POOL_JOB_BOARD", "RESERVE", 200000),
            ("FLEX_RESERVE", "RESERVE", 60500),
        ],
    )
    a.assert_sequence_numbers_ascend(entries)
    assert sum(entry["delta_cents"] for entry in entries) == 360500, entries
    a.assert_program_budget(
        fx.read_program(api, program["id"]),
        committed_budget_cents=360500,
        available_budget_cents=39500,
    )
    a.assert_family_reservation(
        fx.read_job_family(api, family["id"]),
        reserved_cents=100000,
        dedicated_available_cents=0,
    )


def test_cancelling_a_three_bucket_reservation_mirrors_every_release(api):
    """PRD §2.6: "When a reservation unwinds, the service walks that source's outstanding
    `RESERVE` entries in ascending `sequence_no` order and writes one `RELEASE` entry per
    original, reproducing the original `bucket` and negating the original `delta_cents`."
    PRD §3.5: "Cancellation sets `release_reason` to `CANCELLED` and `reserved_cents` to 0, and
    writes one mirroring `RELEASE` ledger entry per outstanding `RESERVE` entry of the flight —
    same `bucket`, negated `delta_cents`, ascending `sequence_no` of the originals, `reason`
    `FLIGHT_CANCELLED` — so that the program's `committed_budget_cents` and the family's
    `reserved_cents` return to exactly their pre-reservation values while
    `available_budget_cents` and `dedicated_available_cents` rise by exactly the released
    amounts."

    Design: Difficulty/compensating_invariant/budget_cents_are_conserved_across_a_three_bucket_reservation_and_its_cancellation
    """
    program, family, channel, posting = _three_bucket_program(api)
    flight = _reserve_seven_day_flight(api, program, family, channel, posting)

    cancelled = fx.cancel_flight(api, flight["id"], reason="client pulled the brief")

    assert cancelled["state"] == "CANCELLED", cancelled
    assert cancelled["release_reason"] == "CANCELLED", cancelled
    a.assert_cents(cancelled["reserved_cents"], 0, "reserved_cents")
    entries = fx.ledger_entries_for_source(api, flight["id"])
    a.assert_ledger_buckets(
        entries,
        [
            ("FAMILY_DEDICATED", "RESERVE", 100000),
            ("POOL_JOB_BOARD", "RESERVE", 200000),
            ("FLEX_RESERVE", "RESERVE", 60500),
            ("FAMILY_DEDICATED", "RELEASE", -100000),
            ("POOL_JOB_BOARD", "RELEASE", -200000),
            ("FLEX_RESERVE", "RELEASE", -60500),
        ],
    )
    a.assert_releases_mirror_reserves(entries[:3], entries[3:])
    assert sum(entry["delta_cents"] for entry in entries) == 0, entries
    a.assert_program_budget(
        fx.read_program(api, program["id"]),
        committed_budget_cents=0,
        available_budget_cents=400000,
    )
    a.assert_family_reservation(
        fx.read_job_family(api, family["id"]),
        reserved_cents=0,
        dedicated_available_cents=100000,
    )


def test_reserving_again_after_a_cancellation_reproduces_the_identical_bucket_draw(api):
    """PRD §2.6: "Because release entries carry negative deltas, availability restores itself
    automatically as reservations unwind."
    PRD §2.6: "Availability in a channel-type pool is the corresponding program pool amount
    less the sum of `delta_cents` across every ledger entry of that program whose `bucket` is
    that pool, and availability in the flex reserve is computed the same way against
    `flex_reserve_cents`."

    Design: Difficulty/compensating_invariant/budget_cents_are_conserved_across_a_three_bucket_reservation_and_its_cancellation
    """
    program, family, channel, posting = _three_bucket_program(api)
    first = _reserve_seven_day_flight(api, program, family, channel, posting)
    fx.cancel_flight(api, first["id"])

    second = _reserve_seven_day_flight(api, program, family, channel, posting)

    a.assert_cents(second["total_cost_cents"], 360500, "total_cost_cents")
    a.assert_ledger_buckets(
        fx.ledger_entries_for_source(api, second["id"]),
        [
            ("FAMILY_DEDICATED", "RESERVE", 100000),
            ("POOL_JOB_BOARD", "RESERVE", 200000),
            ("FLEX_RESERVE", "RESERVE", 60500),
        ],
    )
    whole_ledger = fx.list_ledger_entries(api, program_id=program["id"])
    assert len(whole_ledger) == 9, whole_ledger
    assert sum(entry["delta_cents"] for entry in whole_ledger) == 360500, whole_ledger
    a.assert_sequence_numbers_ascend(whole_ledger)
    a.assert_program_budget(
        fx.read_program(api, program["id"]),
        committed_budget_cents=360500,
        available_budget_cents=39500,
    )
