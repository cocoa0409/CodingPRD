"""Two interval resources with deliberately opposite semantics.

The reporting calendar is half-open with capacity one, so any intersection is
refused and adjacency is free. A plant's forward delivery capacity is closed on
both ends with aggregate capacity, so touching days do collide but overlap is
legal right up to the cap.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.api_errors import ApiErrorId
from test_helpers.types import ReportClass, ReportingWindowStatus, WindowFrequency

INCUMBENT = dict(
    period_start="2026-08-03T00:00:00Z",
    period_end="2026-08-10T00:00:00Z",
    submission_deadline_utc="2026-08-11T15:00:00Z",
    correction_deadline_utc="2026-08-18T15:00:00Z",
    publication_release_utc="2026-08-19T12:00:00Z",
)
PARTIAL_OVERLAP = dict(
    period_start="2026-08-09T00:00:00Z",
    period_end="2026-08-16T00:00:00Z",
    submission_deadline_utc="2026-08-17T15:00:00Z",
    correction_deadline_utc="2026-08-24T15:00:00Z",
    publication_release_utc="2026-08-25T12:00:00Z",
)
CONTAINED = dict(
    period_start="2026-08-05T00:00:00Z",
    period_end="2026-08-06T00:00:00Z",
    submission_deadline_utc="2026-08-07T15:00:00Z",
    correction_deadline_utc="2026-08-14T15:00:00Z",
    publication_release_utc="2026-08-15T12:00:00Z",
)
ADJACENT = dict(
    period_start="2026-08-10T00:00:00Z",
    period_end="2026-08-17T00:00:00Z",
    submission_deadline_utc="2026-08-18T15:00:00Z",
    correction_deadline_utc="2026-08-25T15:00:00Z",
    publication_release_utc="2026-08-26T12:00:00Z",
)

ZERO_HEAD_HISTORY = {"2021": 0, "2022": 0, "2023": 0, "2024": 0, "2025": 0}


def test_01_an_intersecting_calendar_proposal_is_refused_however_it_intersects(api):
    """Partial overlap and total containment are both intersections.

    A window running from inside the incumbent's span to beyond it is refused,
    and so is one lying wholly inside it -- and neither refusal edits the
    incumbent's own calendar.

    PRD §3.3: "Two windows sharing the same `species`, `report_class` and
    `frequency` may not have intersecting half-open intervals; an overlapping
    proposal is rejected with `ERR_WINDOW_PERIOD_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/window_calendar_half_open_adjacency
    """
    incumbent = fx.create_window(api, **INCUMBENT)

    for proposal in (PARTIAL_OVERLAP, CONTAINED):
        refused = api.create_reporting_window(
            f.reporting_window_payload(**proposal), u.PROGRAM_ADMIN
        )
        validate_error(refused, ApiErrorId.ERR_WINDOW_PERIOD_OVERLAP.value, 409)

    unmoved = fx.read_window(api, incumbent["id"])
    assert unmoved["period_end"] == "2026-08-10T00:00:00Z", unmoved


def test_02_a_window_starting_exactly_at_the_incumbents_end_is_accepted(api):
    """The upper bound is exclusive, so the shared instant belongs to nobody twice.

    A window whose start is the incumbent's end covers disjoint trade and is
    created in the open state, one day earlier than the refused proposal.

    PRD §3.3: "while exact adjacency, where the new window's `period_start` equals
    an existing window's `period_end`, is explicitly allowed."

    Design: Difficulty/resource_temporal_overlap/window_calendar_half_open_adjacency
    """
    fx.create_window(api, **INCUMBENT)

    created = get_success_data(
        api.create_reporting_window(
            f.reporting_window_payload(**ADJACENT), u.PROGRAM_ADMIN
        ),
        expected_status=201,
    )

    assert created["period_start"] == "2026-08-10T00:00:00Z", created
    assert created["status"] == ReportingWindowStatus.OPEN.value, created


def test_03_the_calendar_slot_is_keyed_by_species_class_and_frequency(api):
    """The very span that was refused is free again under another key.

    The contained span is accepted once its frequency differs, and the
    incumbent's own span is accepted again under a different report class, so
    four windows stand where two proposals were refused.

    PRD §3.3: "Collection happens inside reporting windows, each opened by a
    `ProgramAdmin` for one `species`, one `report_class` and one `frequency`."

    Design: Difficulty/resource_temporal_overlap/window_calendar_half_open_adjacency
    """
    fx.create_window(api, **INCUMBENT)
    fx.create_window(api, **ADJACENT)

    daily = get_success_data(
        api.create_reporting_window(
            f.reporting_window_payload(
                frequency=WindowFrequency.DAILY.value,
                min_reported_head=200,
                **CONTAINED,
            ),
            u.PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert daily["frequency"] == WindowFrequency.DAILY.value, daily

    boxed = get_success_data(
        api.create_reporting_window(
            f.reporting_window_payload(
                report_class=ReportClass.BOXED_BEEF.value,
                min_reported_head=100000,
                **INCUMBENT,
            ),
            u.PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert boxed["report_class"] == ReportClass.BOXED_BEEF.value, boxed

    windows, meta = validate_paginated(api.list_reporting_windows(u.PROGRAM_ADMIN))
    assert meta["total_count"] == 4, meta
    assert len(windows) == 4, windows


def _plant_holding_an_eighteen_hundred_head_commitment(api):
    """Two plants with different caps, and one forward commitment already booked."""
    firm = fx.firm_with_plants(
        api,
        [
            {"plant_code": "EST-101"},
            {
                "plant_code": "EST-101B",
                "annual_head_history": dict(ZERO_HEAD_HISTORY),
                "boxed_beef_volume_lbs_prior_year": 0,
                "forward_commitment_cap_head": 500,
            },
        ],
        legal_name="Alpha Packing",
    )
    entity_id = firm["entity"]["id"]
    window = fx.create_standard_window(api)

    first = fx.draft_filing(api, entity_id, firm["plants"][0]["id"], window["id"])
    second = fx.draft_filing(api, entity_id, firm["plants"][1]["id"], window["id"])
    fx.add_transaction(
        api,
        entity_id,
        first["id"],
        f.forward_transaction_payload(
            head_count=1800,
            avg_net_price_per_cwt=281.00,
            avg_carcass_weight_cwt=8.50,
        ),
    )

    return {"entity_id": entity_id, "first": first, "second": second}


def test_04_a_commitment_starting_on_the_incumbents_last_delivery_day_collides(api):
    """Closed intervals share their endpoint day, so the head sums on it.

    A 1,500-head commitment starting on the day the booked 1,800-head commitment
    ends probes that shared day at 3,300 head and breaks the 3,000-head cap,
    while the same commitment shifted one day later is accepted.

    PRD §3.4: "A forward-contract delivery span is a **closed** interval on both
    ends, so `forward_delivery_start` must be no later than `forward_delivery_end`".

    Design: Difficulty/resource_temporal_overlap/forward_commitment_closed_interval_aggregate_cap
    """
    scene = _plant_holding_an_eighteen_hundred_head_commitment(api)
    line = dict(
        head_count=1500, avg_net_price_per_cwt=282.00, avg_carcass_weight_cwt=8.60
    )

    refused = api.add_transaction(
        scene["first"]["id"],
        f.forward_transaction_payload(
            forward_delivery_start="2026-09-10T00:00:00Z",
            forward_delivery_end="2026-09-20T00:00:00Z",
            **line,
        ),
        u.reporter_agent(scene["entity_id"]),
    )
    validate_error(
        refused, ApiErrorId.ERR_FORWARD_COMMITMENT_CAP_EXCEEDED.value, 409
    )

    accepted = get_success_data(
        api.add_transaction(
            scene["first"]["id"],
            f.forward_transaction_payload(
                forward_delivery_start="2026-09-11T00:00:00Z",
                forward_delivery_end="2026-09-20T00:00:00Z",
                **line,
            ),
            u.reporter_agent(scene["entity_id"]),
        ),
        expected_status=201,
    )
    assert accepted["head_count"] == 1500, accepted


def test_05_overlap_is_legal_up_to_the_cap_and_refused_one_head_beyond_it(api):
    """Capacity is aggregate: a peak exactly at the cap passes, 3,001 does not.

    A 1,200-head commitment overlapping the booked one lifts the shared day to
    exactly the 3,000-head cap and is accepted, and a single further head on that
    same day is refused.

    PRD §3.4: "two forward contracts may share delivery days freely as long as
    their combined head on every shared day stays within the cap, and a peak
    exactly equal to the cap is permitted."

    Design: Difficulty/resource_temporal_overlap/forward_commitment_closed_interval_aggregate_cap
    """
    scene = _plant_holding_an_eighteen_hundred_head_commitment(api)
    headers = u.reporter_agent(scene["entity_id"])

    at_the_cap = get_success_data(
        api.add_transaction(
            scene["first"]["id"],
            f.forward_transaction_payload(
                forward_delivery_start="2026-09-05T00:00:00Z",
                forward_delivery_end="2026-09-15T00:00:00Z",
                head_count=1200,
                avg_net_price_per_cwt=283.00,
                avg_carcass_weight_cwt=8.70,
            ),
            headers,
        ),
        expected_status=201,
    )
    assert at_the_cap["head_count"] == 1200, at_the_cap

    one_over = api.add_transaction(
        scene["first"]["id"],
        f.forward_transaction_payload(
            forward_delivery_start="2026-09-05T00:00:00Z",
            forward_delivery_end="2026-09-05T00:00:00Z",
            head_count=1,
            avg_net_price_per_cwt=284.00,
            avg_carcass_weight_cwt=8.80,
        ),
        headers,
    )
    validate_error(
        one_over, ApiErrorId.ERR_FORWARD_COMMITMENT_CAP_EXCEEDED.value, 409
    )


def test_06_the_cap_is_measured_per_plant_and_only_accepted_lines_persist(api):
    """The sister plant's own cap is untouched by the first plant's peak.

    A 500-head single-day commitment fills the second plant's own 500-head cap on
    the very day the first plant is saturated, and the refused appends leave no
    trace: three lines and 4,500 head on one filing, one line on the other.

    PRD §3.4: "The candidate set is every `FORWARD_CONTRACT` transaction line of
    the **same plant** — across all of that plant's filings, not just this one".

    Design: Difficulty/resource_temporal_overlap/forward_commitment_closed_interval_aggregate_cap
    """
    scene = _plant_holding_an_eighteen_hundred_head_commitment(api)
    headers = u.reporter_agent(scene["entity_id"])

    api.add_transaction(
        scene["first"]["id"],
        f.forward_transaction_payload(
            forward_delivery_start="2026-09-10T00:00:00Z",
            forward_delivery_end="2026-09-20T00:00:00Z",
            head_count=1500,
            avg_net_price_per_cwt=282.00,
            avg_carcass_weight_cwt=8.60,
        ),
        headers,
    )
    fx.add_transaction(
        api,
        scene["entity_id"],
        scene["first"]["id"],
        f.forward_transaction_payload(
            forward_delivery_start="2026-09-11T00:00:00Z",
            forward_delivery_end="2026-09-20T00:00:00Z",
            head_count=1500,
            avg_net_price_per_cwt=282.00,
            avg_carcass_weight_cwt=8.60,
        ),
    )
    fx.add_transaction(
        api,
        scene["entity_id"],
        scene["first"]["id"],
        f.forward_transaction_payload(
            forward_delivery_start="2026-09-05T00:00:00Z",
            forward_delivery_end="2026-09-15T00:00:00Z",
            head_count=1200,
            avg_net_price_per_cwt=283.00,
            avg_carcass_weight_cwt=8.70,
        ),
    )
    api.add_transaction(
        scene["first"]["id"],
        f.forward_transaction_payload(
            forward_delivery_start="2026-09-05T00:00:00Z",
            forward_delivery_end="2026-09-05T00:00:00Z",
            head_count=1,
            avg_net_price_per_cwt=284.00,
            avg_carcass_weight_cwt=8.80,
        ),
        headers,
    )

    sister = fx.add_transaction(
        api,
        scene["entity_id"],
        scene["second"]["id"],
        f.forward_transaction_payload(
            forward_delivery_start="2026-09-05T00:00:00Z",
            forward_delivery_end="2026-09-05T00:00:00Z",
            head_count=500,
            avg_net_price_per_cwt=285.00,
            avg_carcass_weight_cwt=8.90,
        ),
    )
    assert sister["head_count"] == 500, sister

    first_lines, first_meta = validate_paginated(
        api.list_transactions(scene["first"]["id"], u.PROGRAM_ADMIN)
    )
    assert first_meta["total_count"] == 3, first_meta
    assert len(first_lines) == 3, first_lines
    assert fx.read_submission(api, scene["first"]["id"])["reported_head"] == 4500

    _second_lines, second_meta = validate_paginated(
        api.list_transactions(scene["second"]["id"], u.PROGRAM_ADMIN)
    )
    assert second_meta["total_count"] == 1, second_meta
