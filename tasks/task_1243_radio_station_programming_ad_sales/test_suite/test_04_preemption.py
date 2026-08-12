"""Preemption waterfall: tier permission, victim selection, minimum prefix,
and the four-factor rate stack at full utilization (PRD §3.2, §3.6)."""
from test_helpers import (
    TD,
    ApiErrorId,
    api_client,
    book_spot,
    book_spot_ok,
    create_active_order,
    create_locked_log,
    get_success_data,
    setup_bookable_scenario,
    setup_bookable_station,
    validate_error,
)

SAT_LOG_DATE = "2026-05-02"  # a Saturday


def _setup_full_sat_hour():
    """SAT clock hour 15 (4 units / 480s); AFTERNOON_DRIVE card 8000/3000 for
    SAT; PUBLISHED book share 5.5 (x1.25); PREEMPTIBLE order P with 4 spots
    filling hour 15; FIXED order F with 1 unit."""
    env = setup_bookable_station(
        weekday="SAT", daypart="AFTERNOON_DRIVE", hour=15,
        capacity_units=4, capacity_seconds=480,
        base_rate_cents=8000, min_rate_cents=3000,
        share_value=5.5, book_period=("2026-04-01", "2026-06-30"),
    )
    preemptible = create_active_order(
        env["station"]["id"], rate_tier="PREEMPTIBLE",
        daypart_targets=[{"daypart": "AFTERNOON_DRIVE", "units": 4}],
    )
    fixed = create_active_order(
        env["station"]["id"], rate_tier="FIXED",
        daypart_targets=[{"daypart": "AFTERNOON_DRIVE", "units": 1}],
    )
    log = create_locked_log(env["station"]["id"], log_date=SAT_LOG_DATE)
    victims = [
        book_spot_ok(preemptible["id"], log["id"], daypart="AFTERNOON_DRIVE", hour=15)
        for _ in range(4)
    ]
    env.update({"preemptible": preemptible, "fixed": fixed, "log": log, "victims": victims})
    return env


def test_preemption_four_factor_tier_stack_rate(api):
    """PRD §3.2: "at least 4.0 but below 6.0 yields 1.25", "The **day-of-week
    factor** is 0.85 when the air date's weekday is `SAT` or `SUN`", "at least
    0.85 yields 1.30", and "the final `unit_rate_cents` is the greater of
    `min_rate_cents` and the raw product rounded half-up to integer cents."
    Demand is evaluated before this booking: "The **demand multiplier**
    measures the target hour's utilization before this booking".

    Design: Difficulty/combinatorial_formula/spot_rate_four_factor_tier_stack_with_preemption
    """
    env = _setup_full_sat_hour()
    victims = env["victims"]
    # Rates landed during setup: u = 0, 0.25, 0.5 -> x1.00; u = 0.75 -> x1.15.
    assert [v["unit_rate_cents"] for v in victims] == [8500, 8500, 8500, 9775]

    fixed_spot = book_spot_ok(
        env["fixed"]["id"], env["log"]["id"],
        daypart="AFTERNOON_DRIVE", hour=15, allow_preemption=True,
    )
    assert fixed_spot["unit_rate_cents"] == 11050, (
        "round_half_up(8000 x 1.25 x 0.85 x 1.30); demand evaluated pre-booking "
        "at u = 4/4 = 1.0 >= 0.85"
    )


def test_preemption_minimum_prefix_victim_selection(api):
    """PRD §3.6: "The preemption selector builds the victim pool from spots at
    the same (log, hour) in `SCHEDULED` status whose order's `rate_tier` is
    `PREEMPTIBLE`, ranks them by `unit_rate_cents` ascending with ties broken
    by `created_at` ascending (the `id` is never used as a tiebreak), and
    preempts the minimum prefix of victims needed for the new unit to fit both
    units and seconds." and "Each victim transitions to `MAKE_GOOD_PENDING`
    with `make_good_reason` `PREEMPTED`".

    Design: Difficulty/combinatorial_formula/spot_rate_four_factor_tier_stack_with_preemption
    """
    env = _setup_full_sat_hour()
    p1, p2, p3, p4 = env["victims"]

    fixed_spot = book_spot_ok(
        env["fixed"]["id"], env["log"]["id"],
        daypart="AFTERNOON_DRIVE", hour=15, allow_preemption=True,
    )
    assert fixed_spot["status"] == "SCHEDULED"

    victim1 = get_success_data(api_client.get_spot(p1["id"], TD))
    assert victim1["status"] == "MAKE_GOOD_PENDING"
    assert victim1["make_good_reason"] == "PREEMPTED", (
        "lowest rate 8500, earliest created_at wins the tie among the first three"
    )
    for other in (p2, p3, p4):
        after = get_success_data(api_client.get_spot(other["id"], TD))
        assert after["status"] == "SCHEDULED", "minimum-prefix waterfall preempts exactly one"


def test_preemption_requires_fixed_tier(api):
    """PRD §3.6: "When the target hour is full, a `FIXED`-tier order may request
    `allow_preemption`. Requesting preemption on a `PREEMPTIBLE` order is
    rejected with `ERR_PREEMPTION_NOT_ALLOWED`."

    Design: Corner/validations/preemption_requires_fixed_tier
    """
    env = setup_bookable_scenario(
        capacity_units=1, capacity_seconds=120, units=2, rate_tier="PREEMPTIBLE"
    )
    book_spot_ok(env["order"]["id"], env["log"]["id"])

    resp = book_spot(env["order"]["id"], env["log"]["id"], allow_preemption=True)
    validate_error(resp, ApiErrorId.ERR_PREEMPTION_NOT_ALLOWED)
