"""Delay events and standby billing: per-event rounding, grace, cause filter."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    register_carrier,
    register_escort,
    set_clock,
    get_job,
    setup_booked_job,
    setup_en_route_one_position_job,
    advance_to_cleared,
    advance_to_scheduled,
    advance_to_en_route,
    offer_and_accept,
    open_delay,
    close_delay,
    api_client,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _setup_two_position_en_route():
    """EN_ROUTE TX job at width 185 / height 150: FRONT + REAR (2 positions)."""
    carrier = register_carrier(10_000_000, "Dusty Roads Inc")
    esc_f = register_escort(("TX",), "Front Rider")
    esc_r = register_escort(("TX",), "Rear Rider")
    bundle = setup_booked_job(carrier, load_description="Wide tank", width_inches=185)
    bundle["escort"] = esc_f
    advance_to_cleared(bundle)
    offer_and_accept(bundle, esc_f, "FRONT")
    offer_and_accept(bundle, esc_r, "REAR")
    advance_to_scheduled(bundle)
    advance_to_en_route(bundle, "2026-08-10T09:00:00Z")
    return bundle


def test_standby_per_event_rounding_first_event(api):
    """PRD §3.7: "the first 30 minutes are free: the chargeable time is
    `raw_minutes` minus 30, never less than zero — a 30-minute delay is exactly
    free — and that chargeable remainder is rounded up to the next whole
    15-minute increment to produce `billable_minutes`."
    PRD §3.7: "The event's `standby_amount_cents` is the billable minutes
    divided by 60, multiplied by the standby rate of 7,500 cents per hour,
    multiplied by the job's `total_escort_positions` at close time"

    Design: Difficulty/combinatorial_formula/standby_per_event_rounding_order
    """
    bundle = _setup_two_position_en_route()
    job_id = bundle["job"]["id"]
    set_clock("2026-08-10T10:00:00Z")
    d1 = open_delay(job_id, "CARRIER_DELAY", "2026-08-10T10:00:00Z")
    set_clock("2026-08-10T10:31:00Z")
    d1 = close_delay(d1["id"])

    assert d1["raw_minutes"] == 31
    assert d1["billable_minutes"] == 15, "31 - 30 grace = 1 chargeable -> ceil(1/15)*15"
    # 0.25h x 7500 x 2 positions
    assert d1["standby_amount_cents"] == 3750


def test_standby_per_event_rounding_then_sum(api):
    """PRD §3.7: "Rounding is pinned per event: each closed event rounds its
    own minutes, and invoice composition later sums the per-event amounts,
    never the raw minutes."

    Design: Difficulty/combinatorial_formula/standby_per_event_rounding_order
    """
    bundle = _setup_two_position_en_route()
    job_id = bundle["job"]["id"]
    set_clock("2026-08-10T10:00:00Z")
    d1 = open_delay(job_id, "CARRIER_DELAY", "2026-08-10T10:00:00Z")
    set_clock("2026-08-10T10:31:00Z")
    close_delay(d1["id"])

    set_clock("2026-08-10T11:00:00Z")
    d2 = open_delay(job_id, "MECHANICAL_BREAKDOWN", "2026-08-10T11:00:00Z")
    set_clock("2026-08-10T11:46:00Z")
    d2 = close_delay(d2["id"])

    assert d2["raw_minutes"] == 46
    assert d2["billable_minutes"] == 30, "46 - 30 = 16 -> ceil(16/15)*15 = 30"
    # 0.5h x 7500 x 2 positions
    assert d2["standby_amount_cents"] == 7500

    rows, _ = validate_paginated(api.list_job_delay_events(job_id, DISPATCHER))
    total = sum(r["standby_amount_cents"] for r in rows)
    assert total == 11250, "3750 + 7500; rounding the summed minutes once would be wrong"


def test_standby_grace_exactly_30_minutes_free(api):
    """PRD §3.7: "the first 30 minutes are free: the chargeable time is
    `raw_minutes` minus 30, never less than zero — a 30-minute delay is exactly
    free"

    Design: Difficulty/boundary_precision_check/standby_grace_boundary_30_vs_31
    """
    bundle = setup_en_route_one_position_job(escort_name="Steady Rider")
    job_id = bundle["job"]["id"]
    set_clock("2026-08-10T10:00:00Z")
    d30 = open_delay(job_id, "CARRIER_DELAY", "2026-08-10T10:00:00Z")
    set_clock("2026-08-10T10:30:00Z")
    d30 = close_delay(d30["id"])

    assert d30["raw_minutes"] == 30
    assert d30["billable_minutes"] == 0, "exactly 30 is fully inside the grace"
    assert d30["standby_amount_cents"] == 0


def test_standby_grace_31_minutes_bills_one_increment(api):
    """PRD §3.7: "that chargeable remainder is rounded up to the next whole
    15-minute increment to produce `billable_minutes`."

    Design: Difficulty/boundary_precision_check/standby_grace_boundary_30_vs_31
    """
    bundle = setup_en_route_one_position_job(escort_name="Steady Rider")
    job_id = bundle["job"]["id"]
    set_clock("2026-08-10T11:00:00Z")
    d31 = open_delay(job_id, "CARRIER_DELAY", "2026-08-10T11:00:00Z")
    set_clock("2026-08-10T11:31:00Z")
    d31 = close_delay(d31["id"])

    assert d31["raw_minutes"] == 31
    assert d31["billable_minutes"] == 15, "31 - 30 = 1 chargeable -> ceil(1/15)*15"
    # 0.25h x 7500 x 1 position
    assert d31["standby_amount_cents"] == 1875


def test_non_billable_and_billable_delay_causes(api):
    """PRD §3.7: "Seven causes are recognized, split into two families: the
    billable causes `CARRIER_DELAY`, `MECHANICAL_BREAKDOWN`, and
    `DOCUMENTATION_ISSUE`, and the non-billable causes `WEATHER`,
    `CURFEW_HOLD`, `POLICE_DIRECTED`, and `ROAD_CLOSURE`."
    PRD §3.7: "For a non-billable cause, `billable_minutes` is 0."

    Design: Corner/calculations/non_billable_and_billable_delay_causes
    """
    bundle = setup_en_route_one_position_job(escort_name="Rider CF")
    job_id = bundle["job"]["id"]
    esc_id = bundle["escort"]["id"]

    set_clock("2026-08-10T10:00:00Z")
    d_weather = open_delay(job_id, "WEATHER", "2026-08-10T10:00:00Z", escort_id=esc_id)
    set_clock("2026-08-10T11:00:00Z")
    d_weather = close_delay(d_weather["id"], escort_id=esc_id)
    assert d_weather["raw_minutes"] == 60
    assert d_weather["billable_minutes"] == 0, "WEATHER is non-billable regardless of length"
    assert d_weather["standby_amount_cents"] == 0

    d_doc = open_delay(job_id, "DOCUMENTATION_ISSUE", "2026-08-10T11:00:00Z")
    set_clock("2026-08-10T12:00:00Z")
    d_doc = close_delay(d_doc["id"])
    assert d_doc["raw_minutes"] == 60
    assert d_doc["billable_minutes"] == 30, "60 - 30 grace -> ceil(30/15)*15"
    # 0.5h x 7500 x 1 position
    assert d_doc["standby_amount_cents"] == 3750


def test_delay_close_twice_rejected(api):
    """PRD §3.7: "Either role closes an `OPEN` event — a closed one rejects
    further closure with `ERR_DELAY_EVENT_INVALID_STATE`."

    Design: Corner/state_machines/delay_close_twice_rejected
    """
    bundle = setup_en_route_one_position_job(escort_name="Rider DD")
    job_id = bundle["job"]["id"]
    set_clock("2026-08-10T10:00:00Z")
    d1 = open_delay(job_id, "CARRIER_DELAY", "2026-08-10T10:00:00Z")
    set_clock("2026-08-10T10:45:00Z")
    d1 = close_delay(d1["id"])
    assert d1["raw_minutes"] == 45 and d1["billable_minutes"] == 15
    assert d1["standby_amount_cents"] == 1875

    resp = api.close_delay_event(d1["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_DELAY_EVENT_INVALID_STATE)

    rows, _ = validate_paginated(api.list_job_delay_events(job_id, DISPATCHER))
    assert rows[0]["raw_minutes"] == 45, "a rejected close must not recompute amounts"
    assert rows[0]["billable_minutes"] == 15
    assert rows[0]["standby_amount_cents"] == 1875


def test_incident_and_delay_require_active_job(api):
    """PRD §3.7: "A `Dispatcher` or an `EscortOperator` opens a delay event on
    a job in `EN_ROUTE` or `ON_HOLD` — any other job status is rejected with
    `ERR_JOB_INVALID_STATE`"
    PRD §3.7: "A `CarrierRep`, a `Dispatcher`, or an `EscortOperator` reports
    an incident on a job in `EN_ROUTE`, `ON_HOLD`, or `DELIVERED` — any other
    status is rejected with `ERR_JOB_INVALID_STATE`"

    Design: Corner/state_machines/incident_and_delay_require_active_job
    """
    carrier = register_carrier(10_000_000, "Active Gate Co")
    bundle = setup_booked_job(carrier, load_description="AG")
    job_id = bundle["job"]["id"]

    resp = api.create_incident(
        job_id,
        {
            "incident_type": "EQUIPMENT_DAMAGE",
            "description": "too early",
            "claimed_amount_cents": 1000,
        },
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_JOB_INVALID_STATE)

    # started_at is kept <= the logical clock so only the job-state rule fails.
    resp2 = api.create_delay_event(
        job_id, {"cause": "WEATHER", "started_at": "2026-08-04T23:00:00Z"}, DISPATCHER
    )
    validate_error(resp2, ApiErrorId.ERR_JOB_INVALID_STATE)
