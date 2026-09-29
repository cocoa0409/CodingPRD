"""Two window regimes with deliberately different endpoint semantics: pricing
exception windows are half-open, so back-to-back weeks are legal, while suspension
windows are closed and additionally carry a cooling-off buffer behind them.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import ApiErrorId, BCM_HEADERS, api_client
from test_helpers.assertions import assert_same_instant, violation_points
from test_helpers.factories import exception_payload, notice_payload
from test_helpers.fixtures import (
    approve_exception,
    bootstrap_authorized_channel,
    create_detected_violation,
    issue_notice,
    pin_clock,
    read_compliance_summary,
    read_effective_floor,
    read_notice,
    read_product,
    read_reseller,
    read_violation,
    request_exception,
    run_sweep,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_10 = "2026-08-10T00:00:00Z"
OBSERVED_AUG_05 = "2026-08-05T00:00:00Z"

E1_STARTS = "2026-09-01T00:00:00Z"
E1_ENDS = "2026-09-10T00:00:00Z"


# --------------------------------------------------------------------------- #
# Instance 1 — half-open exception windows: adjacency legal, one second is not
# --------------------------------------------------------------------------- #
def _setup_first_promotional_window():
    """One approved marketplace promotion running the first nine days of September."""
    pin_clock(CLOCK_AUG_01)
    world = bootstrap_authorized_channel(
        product_overrides={"msrp_cents": 15000, "standard_map_floor_cents": 10000},
    )
    pin_clock(CLOCK_AUG_10)
    requested = request_exception(
        world["product"]["id"],
        exception_type="PROMOTIONAL_EVENT",
        channel_scope="MARKETPLACE",
        starts_at=E1_STARTS,
        ends_at=E1_ENDS,
        requested_override_floor_cents=8000,
    )
    assert requested["retroactive"] is False
    world["first_exception"] = approve_exception(requested["id"])
    return world


def test_a_window_starting_exactly_where_another_ends_is_adjacent_not_overlapping():
    """Back-to-back promotional weeks on the same channel are legal.

    PRD: "Half-open means a window whose `starts_at` falls exactly on another's
    `ends_at` is adjacent, not overlapping — back-to-back promotional weeks are legal."

    Design: Difficulty/resource_temporal_overlap/exception_windows_half_open_adjacency_allowed_one_second_overlap_rejected
    """
    world = _setup_first_promotional_window()
    assert world["first_exception"]["status"] == "APPROVED"
    assert world["first_exception"]["override_floor_cents"] == 8000

    adjacent = request_exception(
        world["product"]["id"],
        exception_type="PROMOTIONAL_EVENT",
        channel_scope="MARKETPLACE",
        starts_at=E1_ENDS,
        ends_at="2026-09-20T00:00:00Z",
        requested_override_floor_cents=8000,
    )
    assert adjacent["status"] == "REQUESTED"
    assert_same_instant(adjacent["starts_at"], E1_ENDS, "starts_at")


def test_a_single_second_of_genuine_overlap_on_the_same_scope_is_refused():
    """One second inside the incumbent window is an intersection.

    PRD: "A request is rejected with `ERR_EXCEPTION_WINDOW_OVERLAP` when another
    exception on the same product, in status `REQUESTED` or `APPROVED`, has a window
    that intersects the requested one under half-open interval semantics and has a
    channel scope that intersects the requested scope."

    Design: Difficulty/resource_temporal_overlap/exception_windows_half_open_adjacency_allowed_one_second_overlap_rejected
    """
    world = _setup_first_promotional_window()
    validate_error(
        api_client.create_exception(
            exception_payload(
                world["product"]["id"],
                exception_type="PROMOTIONAL_EVENT",
                channel_scope="MARKETPLACE",
                starts_at="2026-09-09T23:59:59Z",
                ends_at="2026-09-20T00:00:00Z",
                requested_override_floor_cents=8000,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_EXCEPTION_WINDOW_OVERLAP.value,
    )


def test_scopes_that_do_not_intersect_may_share_a_window_but_all_scope_may_not():
    """A different channel coexists inside the same days; ALL collides with everything.

    PRD: "Channel scopes intersect when they are equal or when either is `ALL`."

    Design: Difficulty/resource_temporal_overlap/exception_windows_half_open_adjacency_allowed_one_second_overlap_rejected
    """
    world = _setup_first_promotional_window()
    request_exception(
        world["product"]["id"],
        exception_type="PROMOTIONAL_EVENT",
        channel_scope="MARKETPLACE",
        starts_at=E1_ENDS,
        ends_at="2026-09-20T00:00:00Z",
        requested_override_floor_cents=8000,
    )
    own_website = request_exception(
        world["product"]["id"],
        exception_type="PROMOTIONAL_EVENT",
        channel_scope="OWN_WEBSITE",
        starts_at="2026-09-05T00:00:00Z",
        ends_at="2026-09-06T00:00:00Z",
        requested_override_floor_cents=9000,
    )
    assert own_website["status"] == "REQUESTED"

    validate_error(
        api_client.create_exception(
            exception_payload(
                world["product"]["id"],
                exception_type="PROMOTIONAL_EVENT",
                channel_scope="ALL",
                starts_at="2026-09-05T00:00:00Z",
                ends_at="2026-09-06T00:00:00Z",
                requested_override_floor_cents=9000,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_EXCEPTION_WINDOW_OVERLAP.value,
    )

    rows, meta = validate_paginated(
        api_client.list_exceptions(BCM_HEADERS, params={"product_id": world["product"]["id"]})
    )
    assert meta["total_count"] == 3
    assert sorted(row["status"] for row in rows) == ["APPROVED", "REQUESTED", "REQUESTED"]

    # Only the approved one is counted as open on the product.
    product = read_product(world["product"]["id"])
    assert product["open_exception_count"] == 1


def test_the_resolved_floor_ends_the_instant_the_window_does():
    """The window contains its start and excludes its end on the read path too.

    PRD: "Consider every exception on that product whose status is `APPROVED`, whose
    window contains the instant under half-open semantics — `starts_at` at or before the
    instant and the instant strictly before `ends_at` — whose `channel_scope` is either
    `ALL` or exactly the channel in question, and which is either not a `BUNDLE`
    exception or else is being applied to a listing where `is_bundle` is true, since
    bundle exceptions only cover bundle listings."

    Design: Difficulty/resource_temporal_overlap/exception_windows_half_open_adjacency_allowed_one_second_overlap_rejected
    """
    world = _setup_first_promotional_window()

    inside = read_effective_floor(
        world["product"]["id"], channel="MARKETPLACE", as_of="2026-09-05T00:00:00Z"
    )
    assert inside["effective_map_floor_cents"] == 8000
    assert inside["floor_source"] == "EXCEPTION"
    assert inside["applied_exception_id"] == world["first_exception"]["id"]

    at_the_end = read_effective_floor(
        world["product"]["id"], channel="MARKETPLACE", as_of=E1_ENDS
    )
    assert at_the_end["effective_map_floor_cents"] == 10000
    assert at_the_end["floor_source"] == "STANDARD"
    assert at_the_end["applied_exception_id"] is None
    assert at_the_end["standard_map_floor_cents"] == 10000


# --------------------------------------------------------------------------- #
# Instance 2 — closed suspension windows plus a cooling-off buffer behind them
# --------------------------------------------------------------------------- #
FIRST_SUSPENSION_STARTS = "2026-08-15T00:00:00Z"
FIRST_SUSPENSION_ENDS = "2026-08-25T00:00:00Z"


def _setup_served_suspension():
    """Take a retailer-site reseller through a suspension and let the sweep serve it."""
    pin_clock(CLOCK_AUG_01)
    world = bootstrap_authorized_channel(
        policy_overrides={
            "cure_window_days": 10,
            "suspension_points_threshold": 6,
            "termination_points_threshold": 12,
            "suspension_cooling_off_days": 14,
        },
        product_overrides={"msrp_cents": 15000, "standard_map_floor_cents": 10000},
        reseller_overrides={"primary_channel": "RETAILER_SITE"},
        agreement_overrides={"permitted_channels": ["RETAILER_SITE"]},
    )
    pin_clock(CLOCK_AUG_10)
    violations = []
    for index, price in enumerate((9900, 8000, 9000)):
        violation, _obs, _eval = create_detected_violation(
            world["product"]["id"],
            world["reseller"]["id"],
            listed_price_cents=price,
            channel="RETAILER_SITE",
            observed_at=OBSERVED_AUG_05,
            listing_url=f"https://retailer.example/overlap-{index}",
        )
        violations.append(violation)
    first_notice = issue_notice(world["reseller"]["id"], violations[0]["id"])
    second_notice = issue_notice(
        world["reseller"]["id"],
        violations[1]["id"],
        suspension_starts_at=FIRST_SUSPENSION_STARTS,
        suspension_ends_at=FIRST_SUSPENSION_ENDS,
    )
    world.update(
        {"violations": violations, "first_notice": first_notice, "second_notice": second_notice}
    )
    return world


def _serve_the_suspension(world):
    """Advance the clock past the window and let the sweep reinstate the reseller."""
    pin_clock(FIRST_SUSPENSION_ENDS)
    return run_sweep()


def test_serving_a_suspension_stamps_the_elapsed_end_and_reinstates_the_reseller():
    """The sweep records the window's own end, not the instant it happened to run.

    PRD: "When the sweep observes a reseller whose `authorization_status` is
    `SUSPENDED`, whose `hold_reason` is `SUSPENSION` and whose `suspension_ends_at` is at
    or before the clock, the reseller returns to `AUTHORIZED` with `supply_status` `OPEN`
    and `hold_reason` `NONE`; `last_suspension_ended_at` is set to the
    `suspension_ends_at` that just elapsed (not to the sweep instant),
    `suspension_ends_at` is cleared to null, and the reseller's `version` is advanced."

    Design: Difficulty/resource_temporal_overlap/suspension_windows_closed_interval_plus_cooling_off_buffer
    """
    world = _setup_served_suspension()
    assert world["second_notice"]["rung"] == "SUSPENSION"

    sweep = _serve_the_suspension(world)
    assert sweep["escalated_violations"] == 2
    assert sweep["reinstated_resellers"] == 1

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "AUTHORIZED"
    assert reseller["supply_status"] == "OPEN"
    assert reseller["hold_reason"] == "NONE"
    assert reseller["suspension_ends_at"] is None
    assert_same_instant(
        reseller["last_suspension_ended_at"], FIRST_SUSPENSION_ENDS, "last_suspension_ended_at"
    )

    served = read_notice(world["second_notice"]["id"])
    assert served["status"] == "SATISFIED"
    assert served["closed_reason"] == "SUSPENSION_SERVED"


def test_a_window_touching_the_served_one_is_refused_as_a_closed_interval():
    """Suspension windows intersect on touching endpoints, unlike exception windows.

    PRD: "The window must not intersect any existing non-rescinded suspension window for
    the same reseller, treated as a closed interval so that touching endpoints do count
    as an intersection."

    Design: Difficulty/resource_temporal_overlap/suspension_windows_closed_interval_plus_cooling_off_buffer
    """
    world = _setup_served_suspension()
    _serve_the_suspension(world)

    validate_error(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                world["violations"][2]["id"],
                read_reseller(world["reseller"]["id"])["version"],
                suspension_starts_at=FIRST_SUSPENSION_ENDS,
                suspension_ends_at="2026-09-05T00:00:00Z",
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_SUSPENSION_COOLING_OFF.value,
    )


def test_the_cooling_off_buffer_pushes_the_next_legal_start_two_weeks_out():
    """A start inside the buffer is refused and the first start beyond it is accepted.

    PRD: "And `suspension_starts_at` must be at or after the reseller's
    `last_suspension_ended_at` advanced by the cited policy's
    `suspension_cooling_off_days` — with the default fourteen-day setting, a reseller
    whose previous suspension ended on the first of a month cannot be suspended again
    before the fifteenth."

    Design: Difficulty/resource_temporal_overlap/suspension_windows_closed_interval_plus_cooling_off_buffer
    """
    world = _setup_served_suspension()
    _serve_the_suspension(world)

    # 2026-09-01 still sits inside the fourteen days that follow 2026-08-25.
    validate_error(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                world["violations"][2]["id"],
                read_reseller(world["reseller"]["id"])["version"],
                suspension_starts_at="2026-09-01T00:00:00Z",
                suspension_ends_at="2026-09-11T00:00:00Z",
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_SUSPENSION_COOLING_OFF.value,
    )

    third = issue_notice(
        world["reseller"]["id"],
        world["violations"][2]["id"],
        suspension_starts_at="2026-09-08T00:00:00Z",
        suspension_ends_at="2026-09-18T00:00:00Z",
    )
    assert third["rung"] == "SUSPENSION"
    assert third["assessed_points"] == violation_points(10000, 9000, "RETAILER_SITE", 2) == 3

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "SUSPENDED"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "SUSPENSION"
    assert_same_instant(
        reseller["suspension_ends_at"], "2026-09-18T00:00:00Z", "suspension_ends_at"
    )
    assert reseller["violation_points_total"] == 9


def test_the_escalated_violations_keep_their_points_in_the_reconciled_ledger():
    """Escalation on a missed cure deadline changes status but not the arithmetic.

    PRD: "Third, violations in `NOTICED` whose `cure_deadline_at` is at or before the
    clock become `ESCALATED`."

    Design: Difficulty/resource_temporal_overlap/suspension_windows_closed_interval_plus_cooling_off_buffer
    """
    world = _setup_served_suspension()
    _serve_the_suspension(world)

    for violation_id in (world["violations"][0]["id"], world["violations"][1]["id"]):
        violation = read_violation(violation_id)
        assert violation["status"] == "ESCALATED"

    summary = read_compliance_summary(world["reseller"]["id"])
    assert summary["violation_points_total"] == 6
    assert summary["summed_assessed_points"] == 6
    assert summary["contributing_violation_count"] == 2
    assert summary["highest_issued_rung"] == "SUSPENSION"
