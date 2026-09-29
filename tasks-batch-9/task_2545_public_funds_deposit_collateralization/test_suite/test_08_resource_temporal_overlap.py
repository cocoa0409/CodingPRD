"""Two contended resources with opposite interval semantics: half-open pledge occupation of an
asset's par, and the closed mark-to-market timeline of a depository."""

from test_helpers import assertions, fixtures, get_success_data, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import DEFAULT_CLOCK_UTC, OPEN_ENDED_SENTINEL, clock_stamp
from test_helpers.factories import create_mtm_run_payload, create_pledge_allocation_payload
from test_helpers.fixtures import OFFICER, REGULATOR

EARLY_TO = "2026-08-10T00:00:00Z"
OVERLAP_FROM = "2026-08-09T00:00:00Z"
OVERLAP_TO = "2026-08-20T00:00:00Z"


def _agreement_with_one_million_par_of_treasury(client):
    """A fully documented dedicated arrangement whose only asset carries exactly 1,000,000
    cents of par at par price, so a single pledge exhausts its capacity."""
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="US_TREASURY",
        par_value_cents=1_000_000,
        market_price_bps=10000,
    )
    perimeter["asset_id"] = asset["id"]
    return perimeter


def _attempt_allocation(client, agreement_id, asset_id, par_cents, effective_from, effective_to):
    payload = create_pledge_allocation_payload(
        agreement_id,
        asset_id,
        par_cents,
        fixtures.agreement_version(client, agreement_id),
        effective_from=effective_from,
        effective_to=effective_to,
    )
    return client.create_pledge_allocation(payload, OFFICER)


def _two_back_to_back_full_par_pledges(client):
    """The full par pledged twice over intervals that merely touch at 2026-08-10."""
    perimeter = _agreement_with_one_million_par_of_treasury(client)
    early = fixtures.create_allocation(
        client,
        perimeter["agreement_id"],
        perimeter["asset_id"],
        1_000_000,
        effective_from=DEFAULT_CLOCK_UTC,
        effective_to=EARLY_TO,
    )
    late = fixtures.create_allocation(
        client,
        perimeter["agreement_id"],
        perimeter["asset_id"],
        1_000_000,
        effective_from=EARLY_TO,
        effective_to=OPEN_ENDED_SENTINEL,
    )
    perimeter["early"] = early
    perimeter["late"] = late
    return perimeter


def test_touching_pledge_intervals_are_legal_but_a_one_day_overlap_is_not(client):
    """Two pledges of the entire par succeed while their half-open intervals only touch at
    2026-08-10, and a third that starts one day earlier is refused as oversubscribed — the
    agreement keeps only the two accepted pledges.

    PRD: "Considering every instant inside the requested half-open interval, the sum of
    `allocated_par_cents` of the asset's `ACTIVE` allocations that overlap that instant, plus the
    newly requested `allocated_par_cents`, must not exceed the asset's `par_value_cents`."
    PRD: "Two intervals that merely touch — where an existing allocation's `effective_to` equals
    the new allocation's `effective_from` — do **not** overlap, so back-to-back pledges of the
    full par are legitimate."
    PRD: "The interval is half-open: it includes `effective_from` and excludes `effective_to`."

    Design: Difficulty/resource_temporal_overlap/allocation_half_open_adjacency_versus_overlap_on_asset_par
    """
    perimeter = _two_back_to_back_full_par_pledges(client)

    assert perimeter["early"]["status"] == "ACTIVE"
    assert perimeter["early"]["allocated_collateral_value_cents"] == 980_000
    assert perimeter["early"]["effective_to"] == EARLY_TO
    assert perimeter["late"]["status"] == "ACTIVE"
    assert perimeter["late"]["effective_from"] == EARLY_TO
    assert perimeter["late"]["effective_to"] == OPEN_ENDED_SENTINEL

    overlapping = _attempt_allocation(
        client,
        perimeter["agreement_id"],
        perimeter["asset_id"],
        1_000_000,
        OVERLAP_FROM,
        OVERLAP_TO,
    )
    validate_error(overlapping, ApiErrorId.ERR_ALLOCATION_OVERSUBSCRIBED.value, 409)

    allocations, meta = validate_paginated(
        client.list_pledge_allocations(
            OFFICER, {"pledge_agreement_id": perimeter["agreement_id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 2
    assert len(allocations) == 2


def test_the_interval_filter_reaches_the_mirrors_and_the_run_but_not_the_agreement(client):
    """At a clock of 2026-08-01 only the earlier pledge is in force, so the asset reads fully
    pledged on 1,000,000 cents of par and the bank mirrors 1,000,000 — yet the agreement sums
    both pledges unfiltered to 2,000,000 par and 1,960,000 of value, and the run counts only the
    980,000 that covers its as_of instant.

    PRD: "An asset's `pledged_par_cents` is the sum of `allocated_par_cents` over its `ACTIVE`
    allocations whose effective interval covers the current logical clock, meaning the
    allocation's `effective_from` is at or before the clock and its `effective_to` is strictly
    after it."
    PRD: "A depository's `total_pledged_par_cents` is likewise the sum of `allocated_par_cents`
    over the `ACTIVE` allocations of its `EXECUTED` agreements whose intervals cover the current
    clock."
    PRD: "its `total_pledged_par_cents` is the sum of `allocated_par_cents` over all of its
    `ACTIVE` allocations, whether or not the underlying asset is still eligible; and its
    `active_allocation_count` is the number of its allocations in `ACTIVE` status."
    PRD: "The run's `total_collateral_value_cents` is the sum of
    `allocated_collateral_value_cents` over the allocations that are `ACTIVE`, belong to the
    depository's agreements in `EXECUTED` status, rest on assets whose `eligibility_status` is
    `ELIGIBLE`, and whose half-open effective interval covers the run's `as_of` — that is, whose
    `effective_from` is at or before `as_of` and whose `effective_to` is strictly after it."
    PRD: "Its `cure_deadline_at` is the run's `as_of` advanced by a number of hours that depends
    on how badly the bank is short: 24 hours when `deficiency_ratio_bps` is at least 2000,
    otherwise 48 hours when it is at least 500, and otherwise 120 hours, which is five full days
    for a trivial shortfall."

    Design: Difficulty/resource_temporal_overlap/allocation_half_open_adjacency_versus_overlap_on_asset_par
    """
    perimeter = _two_back_to_back_full_par_pledges(client)

    asset = get_success_data(client.get_collateral_asset(perimeter["asset_id"], OFFICER), 200)
    assert asset["pledged_par_cents"] == 1_000_000
    assert asset["available_par_cents"] == 0
    assert asset["pledge_status"] == "FULLY_PLEDGED"
    assertions.assert_asset_par_conservation(asset)

    agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert agreement["total_pledged_par_cents"] == 2_000_000
    assert agreement["total_collateral_value_cents"] == 1_960_000
    assert agreement["active_allocation_count"] == 2

    before_run = get_success_data(
        client.get_depository(perimeter["depository_id"], REGULATOR), 200
    )
    assert before_run["total_pledged_par_cents"] == 1_000_000
    assert before_run["total_pledged_collateral_value_cents"] == 1_960_000

    run = fixtures.create_mtm_run(
        client, perimeter["depository_id"], "2026-07-31T20:00:00Z", DEFAULT_CLOCK_UTC
    )
    assert run["as_of"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert run["total_collateral_value_cents"] == 980_000
    assert run["total_required_collateral_cents"] == 78_750_000
    assert run["deficiency_cents"] == 77_770_000
    assert run["deficiency_ratio_bps"] == 9875
    assert run["outcome"] == "DEFICIENT"
    assert run["deficiency_surcharge_bps_applied"] == 0

    call = fixtures.latest_margin_call(client, perimeter["depository_id"])
    assert call["required_cure_cents"] == 77_770_000
    assert call["cure_deadline_at"] == clock_stamp("2026-08-02T00:00:00Z")
    assert call["breach_deadline_at"] == clock_stamp("2026-08-03T00:00:00Z")

    depository = get_success_data(
        client.get_depository(perimeter["depository_id"], REGULATOR), 200
    )
    assert depository["consecutive_deficiency_runs"] == 1
    assert depository["mtm_run_index"] == 1
    assert depository["collateral_posture"] == "MARGIN_DEFICIENT"


FIRST_WINDOW = ("2026-07-30T00:00:00Z", "2026-07-31T00:00:00Z")
TOUCHING_START = "2026-07-31T00:00:00Z"
CROWDED_START = "2026-07-31T03:59:00Z"
BUFFERED_START = "2026-07-31T04:00:00Z"


def _bank_with_one_completed_run(client):
    """A well-capitalized bank holding a single funded 100,000,000-cent account, no collateral,
    and one closed valuation window already on the books."""
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client)
    depository = fixtures.create_approved_depository(client, capital_ratio_bps=1200)
    account = fixtures.create_funded_account(
        client, depository["id"], public_unit["id"], 100_000_000
    )
    first = fixtures.create_mtm_run(
        client, depository["id"], FIRST_WINDOW[0], FIRST_WINDOW[1]
    )
    version_after_first = fixtures.depository_version(client, depository["id"])
    return {
        "depository_id": depository["id"],
        "account_id": account["id"],
        "first": first,
        "version_after_first": version_after_first,
    }


def _attempt_run(client, depository_id, window_start, window_end, expected_version):
    return client.create_mtm_run(
        depository_id,
        create_mtm_run_payload(window_start, window_end, expected_version),
        OFFICER,
    )


def test_a_window_that_touches_or_crowds_the_previous_one_is_refused(client):
    """A window starting exactly where the previous one ended intersects it and is refused, a
    window starting 3 hours 59 minutes later clears the intersection but not the buffer and is
    refused too, and a window starting exactly 4 hours later is accepted as the second run.

    PRD: "the closed window from `window_start` to `window_end` inclusive must not intersect the
    closed window of any prior run of the same depository; and `window_start` must fall at least
    4 hours after the previous run's `window_end`, giving a mandatory buffer between consecutive
    windows."
    PRD: "**Mark-to-market window sanity** — `ERR_MTM_WINDOW_OVERLAP` (HTTP 409) on a run whose
    window collides with, or crowds, a prior run of the same depository."
    PRD: "The run's `as_of` is stamped from the logical clock, and its `run_index` is the
    depository's `mtm_run_index` plus 1."

    Design: Difficulty/resource_temporal_overlap/mtm_window_closed_interval_gap_buffer_on_depository
    """
    world = _bank_with_one_completed_run(client)
    assert world["first"]["run_index"] == 1
    assert world["first"]["as_of"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert world["first"]["total_required_collateral_cents"] == 78_750_000
    assert world["first"]["total_collateral_value_cents"] == 0
    assert world["first"]["deficiency_cents"] == 78_750_000
    assert world["first"]["deficiency_ratio_bps"] == 10000
    assert world["first"]["outcome"] == "DEFICIENT"

    touching = _attempt_run(
        client,
        world["depository_id"],
        TOUCHING_START,
        DEFAULT_CLOCK_UTC,
        world["version_after_first"],
    )
    validate_error(touching, ApiErrorId.ERR_MTM_WINDOW_OVERLAP.value, 409)

    crowded = _attempt_run(
        client,
        world["depository_id"],
        CROWDED_START,
        DEFAULT_CLOCK_UTC,
        world["version_after_first"],
    )
    validate_error(crowded, ApiErrorId.ERR_MTM_WINDOW_OVERLAP.value, 409)

    buffered = get_success_data(
        _attempt_run(
            client,
            world["depository_id"],
            BUFFERED_START,
            DEFAULT_CLOCK_UTC,
            world["version_after_first"],
        ),
        201,
    )
    assert buffered["run_index"] == 2
    assert buffered["window_start"] == BUFFERED_START
    assert buffered["deficiency_surcharge_bps_applied"] == 0
    assert buffered["total_required_collateral_cents"] == 78_750_000


def test_the_refused_windows_leave_no_trace_on_the_timeline(client):
    """Only the two accepted windows exist afterwards: the depository shows exactly two runs and
    two open margin calls, its version moved by exactly one for the accepted run, and the streak
    of two deficient runs is still short of the freeze threshold.

    PRD: "On a `DEFICIENT` outcome the depository's `consecutive_deficiency_runs` becomes the
    snapshot plus 1, and a margin call is issued against the depository referencing this run as
    its `mtm_run_id`, with `required_cure_cents` frozen at the run's `deficiency_cents`,
    `cured_cents` at zero and `status` `ISSUED`."
    PRD: "Either way the depository's `mtm_run_index` is set to the run's `run_index`, its
    `last_mtm_window_end` is set to the run's `window_end`, and its `collateral_posture` is
    re-derived: `FROZEN` when `consecutive_deficiency_runs` has reached 3 or more, otherwise
    `MARGIN_DEFICIENT` when `open_margin_call_count` is 1 or more, otherwise `COMPLIANT`."
    PRD: "The depository's `version` is incremented by 1, which is why a client running two
    consecutive runs must re-read the depository between them."

    Design: Difficulty/resource_temporal_overlap/mtm_window_closed_interval_gap_buffer_on_depository
    """
    world = _bank_with_one_completed_run(client)

    validate_error(
        _attempt_run(
            client,
            world["depository_id"],
            TOUCHING_START,
            DEFAULT_CLOCK_UTC,
            world["version_after_first"],
        ),
        ApiErrorId.ERR_MTM_WINDOW_OVERLAP.value,
        409,
    )
    validate_error(
        _attempt_run(
            client,
            world["depository_id"],
            CROWDED_START,
            DEFAULT_CLOCK_UTC,
            world["version_after_first"],
        ),
        ApiErrorId.ERR_MTM_WINDOW_OVERLAP.value,
        409,
    )
    get_success_data(
        _attempt_run(
            client,
            world["depository_id"],
            BUFFERED_START,
            DEFAULT_CLOCK_UTC,
            world["version_after_first"],
        ),
        201,
    )

    runs, runs_meta = validate_paginated(
        client.list_depository_mtm_runs(world["depository_id"], OFFICER)
    )
    assert runs_meta["total_count"] == 2
    assert [run["run_index"] for run in runs] == [1, 2]

    depository = get_success_data(
        client.get_depository(world["depository_id"], REGULATOR), 200
    )
    assert depository["version"] == world["version_after_first"] + 1
    assert depository["consecutive_deficiency_runs"] == 2
    assert depository["mtm_run_index"] == 2
    assert depository["last_mtm_window_end"] == DEFAULT_CLOCK_UTC
    assert depository["collateral_posture"] == "MARGIN_DEFICIENT"
    assert depository["open_margin_call_count"] == 2

    calls, calls_meta = validate_paginated(
        client.list_margin_calls(OFFICER, {"depository_id": world["depository_id"]})
    )
    assert calls_meta["total_count"] == 2
    assert [call["status"] for call in calls] == ["ISSUED", "ISSUED"]
    assert [call["required_cure_cents"] for call in calls] == [78_750_000, 78_750_000]
