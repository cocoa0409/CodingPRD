"""Multi-factor formulas whose result turns on a branch or on the rounding order.

The colour composite branches on the station's physical character; the wrap-time
allocation is rounding-order sensitive; the booking charge pins the day-rate cap
to the very last step.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import PRODUCER
from test_helpers.test_users import make_photographer_headers


def _two_stations_one_style_both_shooting(api):
    """A MODEL bay and a STILL_LIFE bench, each shooting one item of the same style."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(api, required_angles=["FRONT", "FLAT"])
    model_bay = fx.create_station(api, station_code="MODEL-1", station_type="MODEL")
    bench = fx.create_station(api, station_code="STILL-1", station_type="STILL_LIFE")
    provider = fx.create_provider(api)
    ph1 = fx.create_photographer(api)
    ph2 = fx.create_photographer(api, full_name="Cal Ndiaye")
    style = fx.create_style(api, vendor["id"], profile["id"], style_number="TOP1001")
    sample = fx.create_sample(api, vendor["id"], declared_style_number="TOP1001")
    fx.receive_sample(api, sample["id"])
    fx.match_sample(api, sample["id"], style["id"])
    fx.custody_move(api, sample["id"], "IN_STUDIO")

    item_model = fx.create_shot_item(
        api, style["id"], asset_kind="ON_MODEL", angle_code="FRONT"
    )
    item_flat = fx.create_shot_item(
        api,
        style["id"],
        asset_kind="STILL_ANGLE",
        angle_code="FLAT",
        estimated_minutes=45,
    )
    session_model = fx.create_session(
        api,
        model_bay["id"],
        provider["id"],
        session_label="on-model",
        scheduled_start="2026-08-03T09:00:00Z",
        scheduled_end="2026-08-03T11:00:00Z",
    )
    session_flat = fx.create_session(
        api,
        bench["id"],
        provider["id"],
        session_label="tabletop",
        scheduled_start="2026-08-03T09:00:00Z",
        scheduled_end="2026-08-03T11:00:00Z",
    )
    fx.assign_item(api, item_model["id"], session_model["id"])
    fx.assign_item(api, item_flat["id"], session_flat["id"])
    for session, talent in ((session_model, ph1), (session_flat, ph2)):
        booking = fx.create_booking(
            api,
            session["id"],
            talent["id"],
            call_time="2026-08-03T09:00:00Z",
            wrap_time="2026-08-03T11:00:00Z",
        )
        fx.confirm_booking(api, booking["id"])
        fx.lock_session(api, session["id"])
    fx.set_clock(api, "2026-08-03T09:00:00Z")
    fx.start_session(api, session_model["id"], ph1["id"])
    fx.start_session(api, session_flat["id"], ph2["id"])
    return {
        "session_model": session_model,
        "session_flat": session_flat,
        "ph1": ph1,
        "ph2": ph2,
    }


def test_model_station_weights_the_worst_patch_at_seven_tenths_and_fails(api):
    """On a model bay the same readings compose to 2.20 and miss the 2.00 tolerance.

    PRD: "On a station whose `station_type` is `MODEL`, the composite is three tenths of the mean plus seven tenths of the largest, rounded half up to two decimals — skin-tone accuracy is punished far more by one badly-off patch than by a mildly-off average."

    Design: Difficulty/combinatorial_formula/color_composite_weighting_branches_on_station_type
    """
    world = _two_stations_one_style_both_shooting(api)

    session = validate_success(
        api.submit_color_measurement(
            world["session_model"]["id"],
            f.color_measurement_payload([2.5, 1.0, 1.0]),
            make_photographer_headers(world["ph1"]["id"]),
        )
    )

    assert float(session["color_composite_delta_e"]) == 2.20
    assert session["color_check_state"] == "FAIL"


def test_still_life_station_weights_mean_and_worst_equally_and_passes(api):
    """On a tabletop bench the identical readings compose to 2.00 and pass inclusively.

    PRD: "On a `MANNEQUIN` or `STILL_LIFE` station the two contributions are weighted equally, one half each, likewise rounded half up to two decimals."

    Design: Difficulty/combinatorial_formula/color_composite_weighting_branches_on_station_type
    """
    world = _two_stations_one_style_both_shooting(api)

    session = validate_success(
        api.submit_color_measurement(
            world["session_flat"]["id"],
            f.color_measurement_payload([2.5, 1.0, 1.0]),
            make_photographer_headers(world["ph2"]["id"]),
        )
    )

    assert float(session["color_composite_delta_e"]) == 2.00
    assert session["color_check_state"] == "PASS"


def test_each_reading_records_its_own_acting_photographer(api):
    """Two readings on two stations pin two different measuring photographers.

    PRD: "When the reading is accepted, `color_patch_deltas` records the submitted array verbatim, `color_composite_delta_e` records the composite, `color_check_state` records the verdict, `color_measured_at` is stamped from the logical clock, and `color_measured_by_talent_id` records the acting photographer."

    Design: Difficulty/combinatorial_formula/color_composite_weighting_branches_on_station_type
    """
    world = _two_stations_one_style_both_shooting(api)

    measured_model = validate_success(
        api.submit_color_measurement(
            world["session_model"]["id"],
            f.color_measurement_payload([2.5, 1.0, 1.0]),
            make_photographer_headers(world["ph1"]["id"]),
        )
    )
    measured_flat = validate_success(
        api.submit_color_measurement(
            world["session_flat"]["id"],
            f.color_measurement_payload([2.5, 1.0, 1.0]),
            make_photographer_headers(world["ph2"]["id"]),
        )
    )

    assert measured_model["color_measured_by_talent_id"] == world["ph1"]["id"]
    assert measured_flat["color_measured_by_talent_id"] == world["ph2"]["id"]


def _three_captured_items_across_two_styles(api):
    """One 173-minute session carrying two items of TOP1001 and one of TOP2002."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(api, required_angles=["FRONT", "BACK"])
    station = fx.create_station(api)
    provider = fx.create_provider(api)
    photographer = fx.create_photographer(api)
    style_one = fx.create_style(
        api, vendor["id"], profile["id"], style_number="TOP1001", priority_tier="B"
    )
    style_two = fx.create_style(
        api, vendor["id"], profile["id"], style_number="TOP2002", priority_tier="B"
    )
    for barcode, number, style in (
        ("SMP-1001", "TOP1001", style_one),
        ("SMP-2002", "TOP2002", style_two),
    ):
        sample = fx.create_sample(
            api, vendor["id"], barcode=barcode, declared_style_number=number
        )
        fx.receive_sample(api, sample["id"])
        fx.match_sample(api, sample["id"], style["id"])
        fx.custody_move(api, sample["id"], "IN_STUDIO")

    item_one = fx.create_shot_item(
        api, style_one["id"], asset_kind="ON_MODEL", angle_code="FRONT"
    )
    item_two = fx.create_shot_item(
        api, style_one["id"], asset_kind="ON_MODEL", angle_code="BACK"
    )
    item_three = fx.create_shot_item(
        api, style_two["id"], asset_kind="ON_MODEL", angle_code="FRONT"
    )
    session = fx.create_session(api, station["id"], provider["id"])
    for item in (item_one, item_two, item_three):
        fx.assign_item(api, item["id"], session["id"])
    booking = fx.create_booking(api, session["id"], photographer["id"])
    fx.confirm_booking(api, booking["id"])
    fx.lock_session(api, session["id"])
    fx.set_clock(api, "2026-08-03T09:00:00Z")
    fx.start_session(api, session["id"], photographer["id"])
    fx.ingest_asset(api, item_one["id"], photographer["id"], "TOP1001_FRONT_001")
    fx.ingest_asset(api, item_two["id"], photographer["id"], "TOP1001_BACK_001")
    fx.ingest_asset(api, item_three["id"], photographer["id"], "TOP2002_FRONT_001")
    fx.set_clock(api, "2026-08-03T11:53:00Z")
    return {
        "session": session,
        "photographer": photographer,
        "items": [item_one, item_two, item_three],
        "styles": [style_one, style_two],
    }


def test_leftover_cents_are_handed_to_the_earliest_created_items(api):
    """A 101342-cent total over three captured items pays 33781, 33781 and 33780.

    PRD: "The station leg is the producing provider's `station_hour_rate_cents` multiplied by the session's `actual_minutes` divided by 60, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/session_cost_allocation_rounds_per_item_before_folding_into_styles
    """
    world = _three_captured_items_across_two_styles(api)

    fx.wrap_session(api, world["session"]["id"], world["photographer"]["id"])

    shares = [
        validate_success(api.get_shot_list_item(item["id"], PRODUCER))[
            "allocated_cost_cents"
        ]
        for item in world["items"]
    ]
    assert shares == [33781, 33781, 33780]


def test_style_banks_the_sum_of_its_item_shares_not_a_rounded_proportion(api):
    """The two-item style banks 67562, one cent more than a proportional split gives.

    PRD: "Deriving a style's share by rounding a session-wide proportion instead is not permitted, because it yields a different number of cents."

    Design: Difficulty/combinatorial_formula/session_cost_allocation_rounds_per_item_before_folding_into_styles
    """
    world = _three_captured_items_across_two_styles(api)

    fx.wrap_session(api, world["session"]["id"], world["photographer"]["id"])

    style_one = validate_success(
        api.get_style(world["styles"][0]["id"], PRODUCER)
    )
    style_two = validate_success(
        api.get_style(world["styles"][1]["id"], PRODUCER)
    )
    assert style_one["allocated_cost_cents"] == 67562
    assert style_two["allocated_cost_cents"] == 33780


def test_wrap_fixes_actual_minutes_and_releases_the_confirmed_crew(api):
    """Wrapping at 11:53 records 173 actual minutes and releases the booking.

    PRD: "Every booking on the session still in `CONFIRMED` moves to `RELEASED`."

    Design: Difficulty/combinatorial_formula/session_cost_allocation_rounds_per_item_before_folding_into_styles
    """
    world = _three_captured_items_across_two_styles(api)

    wrapped = fx.wrap_session(
        api, world["session"]["id"], world["photographer"]["id"]
    )

    assert wrapped["actual_minutes"] == 173
    bookings, _ = fx.get_bookings_of_session(api, world["session"]["id"])
    assert [b["booking_state"] for b in bookings] == ["RELEASED"]


def _model_holding_the_whole_regular_allowance(api):
    """A model already held 09:00-13:00 on a session that runs until 21:00."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    station = fx.create_station(api)
    provider = fx.create_provider(api)
    model = fx.create_talent(
        api,
        full_name="Ada Wu",
        talent_type="MODEL",
        hourly_rate_cents=25000,
        day_rate_cents=150000,
        minimum_call_hours=3,
        max_daily_minutes=480,
    )
    session = fx.create_session(
        api,
        station["id"],
        provider["id"],
        session_label="long day",
        scheduled_start="2026-08-03T09:00:00Z",
        scheduled_end="2026-08-03T21:00:00Z",
        budget_cap_cents=1000000,
    )
    first = fx.create_booking(
        api,
        session["id"],
        model["id"],
        role_on_set="MODEL",
        call_time="2026-08-03T09:00:00Z",
        wrap_time="2026-08-03T13:00:00Z",
    )
    return {"session": session, "model": model, "first": first}


def test_day_rate_cap_bites_only_on_a_booking_with_no_overtime(api):
    """The first hold is priced at 100000 and stays under the 150000 standard day.

    PRD: "when `overtime_minutes` is zero, `charge_cents` is the smaller of the uncapped figure and the person's `day_rate_cents`; the moment even one overtime minute exists the cap is void and the uncapped figure stands in full."

    Design: Difficulty/combinatorial_formula/day_rate_cap_applies_last_and_is_void_once_overtime_exists
    """
    world = _model_holding_the_whole_regular_allowance(api)

    first = world["first"]
    assert first["regular_minutes"] == 240
    assert first["overtime_minutes"] == 0
    assert first["charge_cents"] == 100000


def test_overtime_voids_the_cap_and_the_uncapped_figure_stands(api):
    """The second hold splits 240 regular against 240 overtime and charges 250000.

    PRD: "The cap never feeds back into the regular/overtime split."

    Design: Difficulty/combinatorial_formula/day_rate_cap_applies_last_and_is_void_once_overtime_exists
    """
    world = _model_holding_the_whole_regular_allowance(api)

    second = validate_success(
        api.create_talent_booking(
            f.booking_payload(
                world["session"]["id"],
                world["model"]["id"],
                fx.session_version(api, world["session"]["id"]),
                role_on_set="MODEL",
                call_time="2026-08-03T13:00:00Z",
                wrap_time="2026-08-03T21:00:00Z",
            ),
            PRODUCER,
        ),
        expected_status=201,
    )

    assert second["booked_minutes"] == 480
    assert second["regular_minutes"] == 240
    assert second["overtime_minutes"] == 240
    assert second["charge_cents"] == 250000


def test_two_holds_move_the_minute_ledger_but_not_the_money_ledger(api):
    """720 booked minutes stand against a session that has committed nothing.

    PRD: "Note that a held booking contributes nothing to `committed_talent_cost_cents` — money is only committed at confirmation."

    Design: Difficulty/combinatorial_formula/day_rate_cap_applies_last_and_is_void_once_overtime_exists
    """
    world = _model_holding_the_whole_regular_allowance(api)

    validate_success(
        api.create_talent_booking(
            f.booking_payload(
                world["session"]["id"],
                world["model"]["id"],
                fx.session_version(api, world["session"]["id"]),
                role_on_set="MODEL",
                call_time="2026-08-03T13:00:00Z",
                wrap_time="2026-08-03T21:00:00Z",
            ),
            PRODUCER,
        ),
        expected_status=201,
    )

    talent = validate_success(
        api.get_talent_profile(world["model"]["id"], PRODUCER)
    )
    session = validate_success(
        api.get_shoot_session(world["session"]["id"], PRODUCER)
    )
    assert talent["booked_minutes_today"] == 720
    assert session["committed_talent_cost_cents"] == 0
