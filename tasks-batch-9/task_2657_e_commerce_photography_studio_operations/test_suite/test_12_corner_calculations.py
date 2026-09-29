"""Calculation corners: the charge ladder, lateness ceiling, queue order, counters.

Literal results, the input sets a figure is and is not allowed to draw on, the
constants applied to one leg only, and counters checked against a full recount.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN,
    COORDINATOR,
    PRODUCER,
    make_retoucher_headers,
)


def test_a_four_hour_photographer_call_bills_every_minute_at_regular_time(api):
    """Four booked hours sit inside the 480-minute day, so nothing spills to overtime.

    PRD: "First, `booked_minutes` is the whole number of minutes between `call_time` and `wrap_time`, and the billable quantity is the larger of that figure and the person's `minimum_call_hours` converted to minutes — a four-hour minimum call means a 90-minute booking is billed as 240 minutes."

    Design: Corner/calculations/booking_charge_of_a_four_hour_photographer_call_is_forty_eight_thousand_cents
    """
    world = fx.build_reference_data(api)
    session = fx.create_session(api, world.station_id, world.provider_id)

    booking = validate_success(
        api.create_talent_booking(
            f.booking_payload(
                session["id"],
                world.photographer_id,
                session["version"],
            ),
            PRODUCER,
        ),
        201,
    )

    assert booking["booked_minutes"] == 240
    assert booking["regular_minutes"] == 240
    assert booking["overtime_minutes"] == 0


def test_a_four_hour_photographer_call_costs_forty_eight_thousand_cents(api):
    """The uncapped figure is below the day rate, so the cap does not bind.

    PRD: "Fourth and last, the standard-day cap is applied, and it applies **only** to a booking that produced no overtime at all: when `overtime_minutes` is zero, `charge_cents` is the smaller of the uncapped figure and the person's `day_rate_cents`; the moment even one overtime minute exists the cap is void and the uncapped figure stands in full."

    Design: Corner/calculations/booking_charge_of_a_four_hour_photographer_call_is_forty_eight_thousand_cents
    """
    world = fx.build_reference_data(api)
    session = fx.create_session(api, world.station_id, world.provider_id)

    booking = validate_success(
        api.create_talent_booking(
            f.booking_payload(session["id"], world.photographer_id, session["version"]),
            PRODUCER,
        ),
        201,
    )

    assert booking["charge_cents"] == 48000
    photographer = validate_success(
        api.get_talent_profile(world.photographer_id, ADMIN)
    )
    assert photographer["day_rate_cents"] == 80000
    assert photographer["booked_minutes_today"] == 240


def test_prior_minutes_ignores_cancelled_holds_and_other_calendar_dates(api):
    """A cancelled same-day hold and a live next-day hold both stay out of the sum.

    PRD: "Second, the regular-time headroom is established: the system sums `booked_minutes` across the **other** bookings of the same person whose `booking_state` is `HELD` or `CONFIRMED` and whose `call_time` falls on the same UTC calendar date as this booking's `call_time`, excluding this booking itself and excluding every booking that is `CANCELLED` or `RELEASED` and every booking on another date; the headroom is the person's `max_daily_minutes` less that prior total, floored at zero."

    Design: Corner/calculations/prior_minutes_ignores_cancelled_bookings_and_other_calendar_dates
    """
    world = fx.build_reference_data(api)
    model = fx.create_model(api, minimum_call_hours=0, max_daily_minutes=240)
    session_a = fx.create_session(
        api,
        world.station_id,
        world.provider_id,
        scheduled_start="2026-08-03T09:00:00Z",
        scheduled_end="2026-08-03T18:00:00Z",
        budget_cap_cents=900000,
    )
    session_b = fx.create_session(
        api,
        world.station_id,
        world.provider_id,
        scheduled_start="2026-08-04T09:00:00Z",
        scheduled_end="2026-08-04T13:00:00Z",
        budget_cap_cents=900000,
    )
    cancelled = fx.create_booking(
        api,
        session_a["id"],
        model["id"],
        role_on_set="MODEL",
        call_time="2026-08-03T09:00:00Z",
        wrap_time="2026-08-03T13:00:00Z",
    )
    validate_success(
        api.cancel_booking(cancelled["id"], PRODUCER, {"reason": "casting changed"})
    )
    fx.create_booking(
        api,
        session_b["id"],
        model["id"],
        role_on_set="MODEL",
        call_time="2026-08-04T09:00:00Z",
        wrap_time="2026-08-04T13:00:00Z",
    )

    booking = validate_success(
        api.create_talent_booking(
            f.booking_payload(
                session_a["id"],
                model["id"],
                fx.session_version(api, session_a["id"]),
                role_on_set="MODEL",
                call_time="2026-08-03T14:00:00Z",
                wrap_time="2026-08-03T18:00:00Z",
            ),
            PRODUCER,
        ),
        201,
    )

    assert booking["booked_minutes"] == 240
    assert booking["regular_minutes"] == 240
    assert booking["overtime_minutes"] == 0
    assert booking["charge_cents"] == 100000
    assert validate_success(api.get_talent_booking(cancelled["id"], PRODUCER))[
        "booking_state"
    ] == "CANCELLED"


def test_the_overtime_leg_carries_the_one_and_a_half_premium(api):
    """A half-day model on a four-hour call splits the charge across both legs.

    PRD: "Third, the two legs are priced separately and each is rounded to a whole cent before they are added: the regular leg is the person's `hourly_rate_cents` multiplied by `regular_minutes` divided by 60, rounded half up; the overtime leg is `hourly_rate_cents` multiplied by one and a half — the studio's overtime premium — then multiplied by `overtime_minutes` divided by 60, and rounded half up."

    Design: Corner/calculations/overtime_multiplier_constant_prices_the_second_leg_at_one_and_a_half
    """
    world = fx.build_reference_data(api)
    model = fx.create_model(api, minimum_call_hours=0, max_daily_minutes=120)
    session = fx.create_session(api, world.station_id, world.provider_id)

    booking = validate_success(
        api.create_talent_booking(
            f.booking_payload(
                session["id"],
                model["id"],
                session["version"],
                role_on_set="MODEL",
            ),
            PRODUCER,
        ),
        201,
    )

    assert booking["regular_minutes"] == 120
    assert booking["overtime_minutes"] == 120
    assert booking["charge_cents"] == 125000


def _a_box_returned_a_day_and_a_half_late(api):
    """A 2-day service level received 01 Aug 08:00, brought back 04 Aug 20:00."""
    fx.set_clock(api, "2026-08-01T08:00:00Z")
    vendor = fx.create_vendor(api, sample_sla_days=2)
    sample = fx.create_sample(api, vendor["id"])
    fx.receive_sample(api, sample["id"])
    fx.custody_move(api, sample["id"], "RETURN_PENDING")
    fx.set_clock(api, "2026-08-04T20:00:00Z")
    return vendor, sample


def test_a_partial_day_of_overrun_is_ceilinged_to_a_whole_day(api):
    """One and a half days late is reported as two whole days, never as one.

    PRD: "Custody moves `RETURN_PENDING → RETURNED`, `returned_at` is stamped from the logical clock, and lateness is computed: the overrun is the whole number of seconds from `due_return_at` to `returned_at`, and `return_days_late` is 0 whenever that overrun is zero or negative, and otherwise the overrun divided by the 86,400 seconds in a day and rounded **up** to the next whole day."

    Design: Corner/calculations/sample_lateness_ceilings_a_partial_day_up_to_a_whole_day
    """
    _, sample = _a_box_returned_a_day_and_a_half_late(api)

    returned = validate_success(
        api.return_sample(
            sample["id"], COORDINATOR, {"condition_note": "creased but usable"}
        )
    )

    assert returned["custody_state"] == "RETURNED"
    assert returned["due_return_at"] == "2026-08-03T08:00:00.000Z"
    assert returned["return_days_late"] == 2


def test_a_late_return_costs_the_vendor_one_strike_short_of_a_hold(api):
    """The strike lands but a single strike is not yet a coordination hold.

    PRD: "The vendor's `outstanding_sample_count` then falls by one; if `return_days_late` is greater than 0 the vendor also takes a strike, raising `late_return_count` by one; and once `late_return_count` reaches 3 strikes the vendor's `coordination_hold` flips to true, which is what stops any further receipts from that vendor."

    Design: Corner/calculations/sample_lateness_ceilings_a_partial_day_up_to_a_whole_day
    """
    vendor, sample = _a_box_returned_a_day_and_a_half_late(api)

    validate_success(
        api.return_sample(
            sample["id"], COORDINATOR, {"condition_note": "creased but usable"}
        )
    )

    after = validate_success(api.get_vendor(vendor["id"], ADMIN))
    assert after["late_return_count"] == 1
    assert after["coordination_hold"] is False
    assert after["outstanding_sample_count"] == 0


def test_the_outstanding_counter_matches_a_recount_of_the_boxes_still_held(api):
    """Of three boxes only the received one is outstanding once the third comes back.

    PRD: "The vendor's `outstanding_sample_count` then falls by one; if `return_days_late` is greater than 0 the vendor also takes a strike, raising `late_return_count` by one; and once `late_return_count` reaches 3 strikes the vendor's `coordination_hold` flips to true, which is what stops any further receipts from that vendor."

    Design: Corner/calculations/vendor_outstanding_counter_agrees_with_a_full_recount_of_its_samples
    """
    fx.set_clock(api, "2026-08-01T08:00:00Z")
    vendor = fx.create_vendor(api)
    never_received = fx.create_sample(
        api, vendor["id"], barcode="SMP-A", declared_style_number="TOP1001"
    )
    on_the_rack = fx.create_sample(
        api, vendor["id"], barcode="SMP-B", declared_style_number="TOP1002"
    )
    going_back = fx.create_sample(
        api, vendor["id"], barcode="SMP-C", declared_style_number="TOP1003"
    )
    fx.receive_sample(api, on_the_rack["id"])
    fx.receive_sample(api, going_back["id"])
    fx.custody_move(api, going_back["id"], "RETURN_PENDING")

    returned = validate_success(api.return_sample(going_back["id"], COORDINATOR))

    assert validate_success(api.get_vendor(vendor["id"], ADMIN))[
        "outstanding_sample_count"
    ] == 1
    assert validate_success(api.get_vendor(vendor["id"], ADMIN))[
        "late_return_count"
    ] == 0
    assert returned["custody_state"] == "RETURNED"
    assert returned["return_days_late"] == 0
    assert validate_success(api.get_sample(never_received["id"], COORDINATOR))[
        "custody_state"
    ] == "EXPECTED"
    assert validate_success(api.get_sample(on_the_rack["id"], COORDINATOR))[
        "custody_state"
    ] == "RECEIVED"


def _two_queued_tasks_that_score_the_same(api):
    """FRONT ingested at 10:00 and BACK at 10:30; both queued at 11:00 on tier C."""
    world = fx.build_reference_data(api)
    fx.build_style_on_the_rack(api, world)
    fx.build_planned_session(
        api,
        world,
        item_specs=[
            {"asset_kind": "ON_MODEL", "angle_code": "FRONT"},
            {"asset_kind": "ON_MODEL", "angle_code": "BACK"},
        ],
    )
    fx.build_shooting_session(api, world)
    fx.set_clock(api, "2026-08-03T10:00:00Z")
    fx.build_ingested_asset(api, world, item_index=0)
    fx.set_clock(api, "2026-08-03T10:30:00Z")
    fx.build_ingested_asset(api, world, item_index=1)
    fx.set_clock(api, "2026-08-03T11:00:00Z")
    fx.build_queued_task(api, world, asset_index=1)
    fx.build_queued_task(api, world, asset_index=0)
    return world


def test_claim_next_hands_over_the_task_whose_due_date_falls_first(api):
    """With the scores tied, the earlier due date wins and the other stays queued.

    PRD: "Candidates are ranked by `priority_score` from highest to lowest; ties are broken by the earlier `due_at` first, and any remaining tie by the earlier `created_at` first."

    Design: Corner/calculations/claim_next_breaks_a_score_tie_on_the_earlier_due_date
    """
    world = _two_queued_tasks_that_score_the_same(api)
    task_on_the_back = world.tasks[0]
    task_on_the_front = world.tasks[1]

    claimed = validate_success(
        api.claim_next_retouch_task(make_retoucher_headers(world.retoucher_id))
    )

    assert claimed["id"] == task_on_the_front["id"]
    assert claimed["task_state"] == "IN_PROGRESS"
    assert claimed["assigned_retoucher_id"] == world.retoucher_id
    assert validate_success(
        api.get_retouch_task(task_on_the_back["id"], ADMIN)
    )["task_state"] == "QUEUED"


def test_the_two_queued_tasks_score_identically(api):
    """Tier C plus the on-model bonus and no waiting at all gives both 50.00 points.

    PRD: "The four terms are combined — weight plus urgency, less the rework penalty, plus the scope bonus — and the result is rounded half up to two decimals."

    Design: Corner/calculations/claim_next_breaks_a_score_tie_on_the_earlier_due_date
    """
    world = _two_queued_tasks_that_score_the_same(api)

    fx.claim_next(api, world.retoucher_id)

    assert float(world.read_task(0)["priority_score"]) == 50.00
    assert float(world.read_task(1)["priority_score"]) == 50.00


def test_each_task_pins_its_due_date_from_its_own_assets_creation(api):
    """Twelve provider hours are added to the instant each file was ingested.

    PRD: "That figure is written to the task's own `sla_hours`, and `due_at` becomes the asset's `created_at` plus that many hours."

    Design: Corner/calculations/claim_next_breaks_a_score_tie_on_the_earlier_due_date
    """
    world = _two_queued_tasks_that_score_the_same(api)

    task_on_the_back = world.read_task(0)
    task_on_the_front = world.read_task(1)

    assert task_on_the_front["sla_hours"] == 12
    assert task_on_the_front["due_at"] == "2026-08-03T22:00:00.000Z"
    assert task_on_the_back["due_at"] == "2026-08-03T22:30:00.000Z"
