"""Nomination windows, the symmetric ramp buffer, the hourly injection ceiling and the
cumulative curtailment counter that suspends an interconnection agreement."""
from test_helpers import (
    OPERATOR,
    SCHEDULER,
    confirm_nomination,
    create_nomination,
    curtail_nomination,
    set_clock,
    setup_interconnect_at_curtailment_charges,
    setup_pipeline_spec_day,
    validate_error,
    validate_paginated,
    validate_success,
)


def _spec_day():
    """A closed, pipeline-quality day carrying 120.280 MMBtu behind an ACTIVE interconnect."""
    return setup_pipeline_spec_day()


def _spec_day_with_confirmed_window():
    """The same day with 06:00-18:00 on 2026-08-04 already CONFIRMED at 120.280 MMBtu."""
    plant = _spec_day()
    nomination = create_nomination(
        plant["interconnect"]["id"],
        plant["ops_day"]["id"],
        window_start_utc="2026-08-04T06:00:00Z",
        window_end_utc="2026-08-04T18:00:00Z",
        nominated_mmbtu=120.280,
    )
    plant["nomination"] = confirm_nomination(nomination["id"])
    return plant


def test_01_a_rate_landing_exactly_on_the_injection_ceiling_is_nominated(api):
    """120.000 MMBtu across 600 minutes is exactly 12.000 and is accepted.

    PRD: "That rate must be less than or equal to `max_hourly_injection_mmbtu`, with exact equality accepted and anything strictly greater rejected with `ERR_HOURLY_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/bpc_hourly_injection_rate_exactly_at_interconnect_ceiling_is_accepted
    """
    plant = _spec_day()
    assert plant["ops_day"]["pipeline_gas_mmbtu"] == 120.280

    nomination = validate_success(
        api.create_nomination(
            {
                "interconnect_id": plant["interconnect"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "window_start_utc": "2026-08-04T06:00:00Z",
                "window_end_utc": "2026-08-04T16:00:00Z",
                "nominated_mmbtu": 120.000,
            },
            SCHEDULER,
        ),
        201,
    )
    assert nomination["window_minutes"] == 600
    assert nomination["hourly_rate_mmbtu"] == 12.000
    assert nomination["status"] == "NOMINATED"


def test_02_a_tenth_of_an_mmbtu_more_over_the_same_window_breaches_the_ceiling(api):
    """120.100 MMBtu across the same 600 minutes rounds to 12.010 and is refused.

    PRD: "Fourth, rate: `window_minutes` is the count of whole minutes from `window_start_utc` to `window_end_utc`, and `hourly_rate_mmbtu` is `nominated_mmbtu` divided by the window length expressed in hours, where that length in hours is `window_minutes` divided by 60, with the quotient rounded to 3 decimal places."

    Design: Difficulty/boundary_precision_check/bpc_hourly_injection_rate_exactly_at_interconnect_ceiling_is_accepted
    """
    plant = _spec_day()
    at_ceiling = create_nomination(
        plant["interconnect"]["id"],
        plant["ops_day"]["id"],
        window_start_utc="2026-08-04T06:00:00Z",
        window_end_utc="2026-08-04T16:00:00Z",
        nominated_mmbtu=120.000,
    )
    assert at_ceiling["hourly_rate_mmbtu"] == 12.000

    validate_error(
        api.create_nomination(
            {
                "interconnect_id": plant["interconnect"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "window_start_utc": "2026-08-04T17:00:00Z",
                "window_end_utc": "2026-08-05T03:00:00Z",
                "nominated_mmbtu": 120.100,
            },
            SCHEDULER,
        ),
        "ERR_HOURLY_CAPACITY_EXCEEDED",
        422,
    )

    day = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR), 200)
    assert day["pipeline_gas_mmbtu"] == 120.280


def test_03_a_window_reaching_into_the_ramp_buffer_collides(api):
    """A window opening at 18:00 sits inside the incumbent's buffered upper bound.

    PRD: "Second, collision: the requested window is expanded by `ramp_buffer_minutes` at each end — the buffered lower bound is `window_start_utc` moved earlier by that many minutes, the buffered upper bound is `window_end_utc` moved later by the same amount — and compared against every existing nomination on the same interconnection agreement whose status is `NOMINATED`, `CONFIRMED`, `CURTAILED` or `DELIVERED`, each of which is expanded the same way."

    Design: Difficulty/resource_temporal_overlap/rto_injection_windows_half_open_with_symmetric_ramp_buffer_touching_ends_allowed
    """
    plant = _spec_day_with_confirmed_window()
    assert plant["nomination"]["hourly_rate_mmbtu"] == 10.023
    assert plant["nomination"]["status"] == "CONFIRMED"

    validate_error(
        api.create_nomination(
            {
                "interconnect_id": plant["interconnect"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "window_start_utc": "2026-08-04T18:00:00Z",
                "window_end_utc": "2026-08-04T23:00:00Z",
                "nominated_mmbtu": 60.000,
            },
            SCHEDULER,
        ),
        "ERR_INJECTION_WINDOW_OVERLAP",
        409,
    )


def test_04_buffered_windows_that_merely_touch_are_both_scheduled(api):
    """A window opening at 19:00 buffers back to exactly the incumbent's buffered end.

    PRD: "Two buffered windows conflict when the new buffered lower bound is strictly earlier than the existing buffered upper bound **and** the existing buffered lower bound is strictly earlier than the new buffered upper bound; because both comparisons are strict, windows that merely touch at a buffered endpoint do not conflict."

    Design: Difficulty/resource_temporal_overlap/rto_injection_windows_half_open_with_symmetric_ramp_buffer_touching_ends_allowed
    """
    plant = _spec_day_with_confirmed_window()

    adjacent = validate_success(
        api.create_nomination(
            {
                "interconnect_id": plant["interconnect"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "window_start_utc": "2026-08-04T19:00:00Z",
                "window_end_utc": "2026-08-05T00:00:00Z",
                "nominated_mmbtu": 60.000,
            },
            SCHEDULER,
        ),
        201,
    )
    assert adjacent["window_minutes"] == 300
    assert adjacent["hourly_rate_mmbtu"] == 12.000
    assert adjacent["status"] == "NOMINATED"

    rows, meta = validate_paginated(
        api.list_nominations(
            SCHEDULER, {"interconnect_id": plant["interconnect"]["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_05_a_new_nomination_is_born_with_its_derived_window_fields(api):
    """Creation stamps the window length and the hourly rate and leaves the volumes open.

    PRD: "A created nomination has `confirmed_mmbtu` and `delivered_mmbtu` null."

    Design: Corner/state_machines/sm_nomination_is_born_nominated_with_derived_window_fields
    """
    plant = _spec_day()

    nomination = validate_success(
        api.create_nomination(
            {
                "interconnect_id": plant["interconnect"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "window_start_utc": "2026-08-04T06:00:00Z",
                "window_end_utc": "2026-08-04T18:00:00Z",
                "nominated_mmbtu": 120.280,
            },
            SCHEDULER,
        ),
        201,
    )
    assert nomination["status"] == "NOMINATED"
    assert nomination["nominated_mmbtu"] == 120.280
    assert nomination["window_minutes"] == 720
    assert nomination["hourly_rate_mmbtu"] == 10.023
    assert nomination["confirmed_mmbtu"] is None
    assert nomination["delivered_mmbtu"] is None
    assert nomination["version"] == 1


def test_06_the_nomination_screen_reports_notice_volume_and_rate_in_turn(api):
    """Three breaches of the same screen surface in the pinned ladder order.

    PRD: "First, notice: the logical clock must be at least `nomination_lead_hours` whole hours earlier than `window_start_utc`, or the request is rejected with `ERR_NOMINATION_LEAD_TIME`."

    Design: Corner/validations/validation_nomination_screen_rejects_lead_time_volume_and_rate_breaches
    """
    plant = _spec_day()

    set_clock("2026-08-04T00:00:00Z")
    validate_error(
        api.create_nomination(
            {
                "interconnect_id": plant["interconnect"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "window_start_utc": "2026-08-04T06:00:00Z",
                "window_end_utc": "2026-08-04T18:00:00Z",
                "nominated_mmbtu": 120.280,
            },
            SCHEDULER,
        ),
        "ERR_NOMINATION_LEAD_TIME",
        422,
    )

    set_clock("2026-08-01T00:00:00Z")
    validate_error(
        api.create_nomination(
            {
                "interconnect_id": plant["interconnect"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "window_start_utc": "2026-08-04T06:00:00Z",
                "window_end_utc": "2026-08-04T18:00:00Z",
                "nominated_mmbtu": 130.000,
            },
            SCHEDULER,
        ),
        "ERR_NOMINATION_EXCEEDS_PRODUCTION",
        422,
    )

    validate_error(
        api.create_nomination(
            {
                "interconnect_id": plant["interconnect"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "window_start_utc": "2026-08-04T06:00:00Z",
                "window_end_utc": "2026-08-04T10:00:00Z",
                "nominated_mmbtu": 120.280,
            },
            SCHEDULER,
        ),
        "ERR_HOURLY_CAPACITY_EXCEEDED",
        422,
    )

    interconnect = validate_success(
        api.get_interconnect(plant["interconnect"]["id"], SCHEDULER)
    )
    assert interconnect["curtailment_count"] == 0
    assert interconnect["status"] == "ACTIVE"


def test_07_injecting_more_than_the_confirmed_volume_is_refused(api):
    """The pipeline cannot be told it took more gas than it agreed to take.

    PRD: "The scheduler supplies `delivered_mmbtu`, which must be less than or equal to `confirmed_mmbtu` or the request is rejected with `ERR_DELIVERY_EXCEEDS_CONFIRMED`."

    Design: Corner/validations/validation_delivered_energy_above_the_confirmed_quantity_is_rejected
    """
    plant = _spec_day_with_confirmed_window()
    assert plant["nomination"]["confirmed_mmbtu"] == 120.280

    validate_error(
        api.deliver_nomination(
            plant["nomination"]["id"], {"delivered_mmbtu": 130.000}, SCHEDULER
        ),
        "ERR_DELIVERY_EXCEEDS_CONFIRMED",
        422,
    )

    unchanged = validate_success(
        api.get_nomination(plant["nomination"]["id"], SCHEDULER)
    )
    assert unchanged["status"] == "CONFIRMED"
    assert unchanged["delivered_mmbtu"] is None
    day = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert day["gas_state"] == "PIPELINE_SPEC"


def test_08_curtailing_confirms_only_the_reduced_volume(api):
    """A curtailment writes the smaller volume into the confirmed field and charges once.

    PRD: "`CURTAIL` moves the nomination `NOMINATED → CURTAILED` and requires a `curtailed_mmbtu` value that is strictly greater than zero and strictly less than `nominated_mmbtu`; `confirmed_mmbtu` is set to that curtailed volume."

    Design: Corner/endpoints/endpoint_curtail_decision_confirms_only_the_curtailed_volume
    """
    plant = _spec_day()
    nomination = create_nomination(
        plant["interconnect"]["id"],
        plant["ops_day"]["id"],
        window_start_utc="2026-08-04T06:00:00Z",
        window_end_utc="2026-08-04T18:00:00Z",
        nominated_mmbtu=120.280,
    )

    curtailed = validate_success(
        api.schedule_decision(
            nomination["id"],
            {
                "decision": "CURTAIL",
                "curtailed_mmbtu": 60.000,
                "reason": "Receipt-point pressure",
            },
            SCHEDULER,
        )
    )
    assert curtailed["status"] == "CURTAILED"
    assert curtailed["nominated_mmbtu"] == 120.280
    assert curtailed["confirmed_mmbtu"] == 60.000
    assert curtailed["version"] == 2

    interconnect = validate_success(
        api.get_interconnect(plant["interconnect"]["id"], SCHEDULER)
    )
    assert interconnect["curtailment_count"] == 1
    assert interconnect["status"] == "ACTIVE"
    day = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert day["gas_state"] == "PIPELINE_SPEC"


def test_09_reinstating_a_suspended_interconnect_clears_the_charge_counter(api):
    """Three charges suspend the agreement and reinstatement wipes the counter.

    PRD: "`REINSTATE` moves it `SUSPENDED → ACTIVE` and resets `curtailment_count` to 0, incrementing its `version` by one."

    Design: Corner/state_machines/sm_interconnect_reinstate_after_threshold_suspension_clears_curtailment_count
    """
    plant = setup_interconnect_at_curtailment_charges(3, curtailed_mmbtu=20.000)
    suspended = validate_success(
        api.get_interconnect(plant["interconnect"]["id"], SCHEDULER)
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["curtailment_count"] == 3

    reinstated = validate_success(
        api.change_interconnect_status(
            plant["interconnect"]["id"],
            {"action": "REINSTATE", "reason": "Compressor repaired"},
            SCHEDULER,
        )
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["curtailment_count"] == 0

    third = validate_success(
        api.get_nomination(plant["nominations"][2]["id"], SCHEDULER)
    )
    assert third["status"] == "CURTAILED"
    assert third["confirmed_mmbtu"] == 20.000


def test_10_the_curtailment_threshold_binds_only_on_the_third_charge(api):
    """Two charges leave the agreement open for business; the third closes it.

    PRD: "Curtailment also increments the interconnection agreement's `curtailment_count` by one, and when that counter reaches three the agreement moves `ACTIVE → SUSPENDED`."

    Design: Corner/cross_cutting_layers/ccl_curtailment_threshold_binds_only_on_the_third_charge
    """
    plant = _spec_day()
    windows = [
        ("2026-08-04T06:00:00Z", "2026-08-04T10:00:00Z"),
        ("2026-08-04T11:00:00Z", "2026-08-04T15:00:00Z"),
        ("2026-08-04T16:00:00Z", "2026-08-04T20:00:00Z"),
    ]
    nominations = [
        create_nomination(
            plant["interconnect"]["id"],
            plant["ops_day"]["id"],
            window_start_utc=start,
            window_end_utc=end,
            nominated_mmbtu=30.000,
        )
        for start, end in windows
    ]

    first = curtail_nomination(nominations[0]["id"], 10.000, "Receipt-point pressure")
    assert first["confirmed_mmbtu"] == 10.000
    curtail_nomination(nominations[1]["id"], 10.000, "Receipt-point pressure")
    still_open = validate_success(
        api.get_interconnect(plant["interconnect"]["id"], SCHEDULER)
    )
    assert still_open["status"] == "ACTIVE"
    assert still_open["curtailment_count"] == 2

    fourth = validate_success(
        api.create_nomination(
            {
                "interconnect_id": plant["interconnect"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "window_start_utc": "2026-08-04T21:00:00Z",
                "window_end_utc": "2026-08-05T01:00:00Z",
                "nominated_mmbtu": 30.000,
            },
            SCHEDULER,
        ),
        201,
    )
    assert fourth["status"] == "NOMINATED"

    third = curtail_nomination(nominations[2]["id"], 10.000, "Receipt-point pressure")
    assert third["status"] == "CURTAILED"
    suspended = validate_success(
        api.get_interconnect(plant["interconnect"]["id"], SCHEDULER)
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["curtailment_count"] == 3

    validate_error(
        api.create_nomination(
            {
                "interconnect_id": plant["interconnect"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "window_start_utc": "2026-08-05T06:00:00Z",
                "window_end_utc": "2026-08-05T10:00:00Z",
                "nominated_mmbtu": 30.000,
            },
            SCHEDULER,
        ),
        "ERR_NO_ACTIVE_INTERCONNECT",
        409,
    )
