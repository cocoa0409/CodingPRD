"""Requirement determination thresholds, provisional quoting, and quote gates."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    register_carrier,
    set_clock,
    create_tx_job,
    list_job_legs,
    quote_job,
    parse_ts,
    api_client,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_superload_tx_two_front_rear_pole_police_survey(api):
    """PRD §3.3: "For a leg traversing Texas (`TX`): one rear escort is required
    when the load width is at least 168 inches; front coverage is two front
    escorts when the width is at least 192 inches, otherwise one front escort
    when it is at least 180 inches, otherwise none. A height pole is required
    when the load height is at least 174 inches. A police escort is required
    when the width is at least 192 inches or the gross weight is at least
    200,000 pounds."
    PRD §3.3: "The equipment estimate adds 15,000 cents for a leg that requires
    a height pole, 40,000 cents for a leg that requires a police escort, and
    25,000 cents for a leg that requires a route survey."

    Design: Difficulty/combinatorial_formula/per_state_requirement_branching
    """
    carrier = register_carrier(10_000_000, "Cimarron Carriers")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(
        carrier,
        load_description="Superload A",
        width_inches=195,
        height_inches=180,
        gross_weight_lbs=250000,
        map_min_clearance_inches=200,
    )
    leg = list_job_legs(job["id"])[0]
    quoted = quote_job(job["id"])

    leg = api.get_leg(leg["id"], DISPATCHER).json()["data"]
    assert leg["required_rear_escorts"] == 1, "195 >= 168 rear threshold"
    assert leg["required_front_escorts"] == 2, "195 >= 192 two-front threshold"
    assert leg["requires_height_pole"] is True, "180 >= 174 pole threshold"
    assert leg["requires_police_escort"] is True, "195 >= 192 width branch"
    assert leg["requires_route_survey"] is True
    assert quoted["total_escort_positions"] == 3
    # 2.5h x 3 positions x 9000 = 67500 base + 15000 pole + 40000 police + 25000 survey
    assert quoted["quoted_cents"] == 147500


def test_police_requirement_from_weight_alone_with_zero_positions(api):
    """PRD §3.3: "A police escort is required when the width is at least 192
    inches or the gross weight is at least 200,000 pounds."
    PRD §3.3: "The job's `quoted_cents` is the sum of the base and equipment
    estimates across all legs, an integer number of cents with no further
    rounding."

    Design: Difficulty/combinatorial_formula/per_state_requirement_branching
    """
    carrier = register_carrier(10_000_000, "Heavy Haul Branch")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(
        carrier,
        load_description="Heavy B",
        width_inches=150,
        height_inches=150,
        gross_weight_lbs=250000,
        map_min_clearance_inches=200,
    )
    leg = list_job_legs(job["id"])[0]
    quoted = quote_job(job["id"])

    leg = api.get_leg(leg["id"], DISPATCHER).json()["data"]
    assert leg["required_rear_escorts"] == 0, "150 < 168 rear threshold"
    assert leg["required_front_escorts"] == 0
    assert leg["requires_height_pole"] is False
    assert leg["requires_police_escort"] is True, "weight branch alone: 250000 >= 200000"
    assert leg["requires_route_survey"] is False, "150 < 174 and 150 < 168"
    assert quoted["total_escort_positions"] == 0
    # 0 base + 40000 police coordination fee survives zero escort positions.
    assert quoted["quoted_cents"] == 40000


def test_width_168_triggers_rear_escort_inclusive(api):
    """PRD §3.3: "Every threshold below is in whole inches or whole pounds and
    every boundary is inclusive: a width exactly at a threshold always triggers
    the requirement."

    Design: Difficulty/boundary_precision_check/width_threshold_inclusive_168
    """
    carrier = register_carrier(10_000_000, "Precision Carriers")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(
        carrier,
        load_description="Exactly 168",
        width_inches=168,
        distance_miles=100,
        window_start_at="2026-08-10T09:00:00Z",
        window_end_at="2026-08-10T11:00:00Z",
    )
    leg = list_job_legs(job["id"])[0]
    quoted = quote_job(job["id"])

    leg = api.get_leg(leg["id"], DISPATCHER).json()["data"]
    assert leg["required_rear_escorts"] == 1, "168 >= 168: the boundary is inclusive"
    assert leg["required_front_escorts"] == 0
    # ceil(100/50*2)/2 = 2.0h x 1 position x 9000
    assert quoted["quoted_cents"] == 18000
    assert quoted["total_escort_positions"] == 1


def test_width_167_stays_below_rear_threshold(api):
    """PRD §3.3: "one rear escort is required when the load width is at least
    168 inches"

    Design: Difficulty/boundary_precision_check/width_threshold_inclusive_168
    """
    carrier = register_carrier(10_000_000, "Precision Carriers")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(
        carrier,
        load_description="Just 167",
        width_inches=167,
        distance_miles=100,
        window_start_at="2026-08-11T09:00:00Z",
        window_end_at="2026-08-11T11:00:00Z",
    )
    leg = list_job_legs(job["id"])[0]
    quoted = quote_job(job["id"])

    leg = api.get_leg(leg["id"], DISPATCHER).json()["data"]
    assert leg["required_rear_escorts"] == 0, "167 < 168: below the threshold"
    assert leg["required_front_escorts"] == 0
    assert quoted["quoted_cents"] == 0
    assert quoted["total_escort_positions"] == 0


def test_quote_estimated_hours_round_up_to_half_hour(api):
    """PRD §3.3: "For each leg, the estimated escort hours are the leg's
    `distance_miles` divided by an assumed average speed of 50 miles per hour,
    with the quotient rounded up to a multiple of half an hour — a value already
    on a half-hour boundary is unchanged."
    PRD §3.3: "Quoting also stamps `quoted_at` with the current time, sets
    `quote_expires_at` exactly 72 hours later, records the job's
    `total_escort_positions` as the sum of front and rear requirements across
    all legs, and moves the job from `DRAFT` to `QUOTED`."

    Design: Corner/calculations/quote_estimated_hours_ceil_to_half_hour
    """
    carrier = register_carrier(10_000_000, "Short Haul Co")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(
        carrier,
        load_description="Short",
        distance_miles=30,
        window_start_at="2026-08-10T09:00:00Z",
        window_end_at="2026-08-10T11:00:00Z",
    )
    quoted = quote_job(job["id"])

    # ceil(30/50*2)/2 = 1.0h x 1 position x 9000 (170 >= 168 rear threshold)
    assert quoted["quoted_cents"] == 9000
    assert quoted["total_escort_positions"] == 1
    delta = parse_ts(quoted["quote_expires_at"]) - parse_ts(quoted["quoted_at"])
    assert delta.total_seconds() == 72 * 3600, "quote_expires_at must be exactly quoted_at + 72h"


def test_quote_when_already_quoted_rejected(api):
    """PRD §3.3: "A `Dispatcher` requests a quote for a job in `DRAFT`; a job in
    any other status is rejected with `ERR_JOB_INVALID_STATE`."

    Design: Corner/state_machines/quote_when_quoted_rejected
    """
    carrier = register_carrier(10_000_000, "Repeat Quote Co")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="Q")
    quoted = quote_job(job["id"])
    assert quoted["job_status"] == "QUOTED"

    resp = api.quote_job(job["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_JOB_INVALID_STATE)

    after = api.get_job(job["id"], DISPATCHER).json()["data"]
    assert after["job_status"] == "QUOTED"
    assert after["version"] == quoted["version"], "a rejected quote must not mutate the job"


def test_confirm_police_when_not_required_rejected(api):
    """PRD §3.4: "Confirming police on a leg whose `requires_police_escort` is
    false is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/confirm_police_not_required_rejected
    """
    carrier = register_carrier(10_000_000, "Police Co")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="No police")
    leg = list_job_legs(job["id"])[0]
    quote_job(job["id"])

    leg = api.get_leg(leg["id"], DISPATCHER).json()["data"]
    assert leg["requires_police_escort"] is False

    resp = api.confirm_police(leg["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    leg = api.get_leg(leg["id"], DISPATCHER).json()["data"]
    assert leg["police_confirmed"] is False
