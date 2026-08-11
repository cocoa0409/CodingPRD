"""Storage loss events: TABLE_RATE vs RESURVEY deterioration variants, inclusive
survey blackout windows, measured-weight validation, the zero-remaining
allocation guard, and shipped-weight attestation at reclaim."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_loss_event,
    create_loss_event_payload,
    create_pile,
    create_station,
    get_success_data,
    seal_pile,
    set_logical_clock,
    setup_accepted_world,
    validate_error,
    validate_success,
)

def _sealed_empty_pile(api, station_operator_headers):
    """Station + pile sealed at the startup-default clock (empty pile)."""
    station = create_station()
    pile = create_pile(station["id"], capacity_tons=200)
    seal_pile(pile["id"])  # sealed at the logical clock's startup default
    return station, pile


def test_table_rate_loss_projects_from_sealed_mass(api, station_operator_headers,
                                                   pool_accountant_headers):
    """PRD §3.8: "Under `TABLE_RATE`, the loss is the pile's `sealed_stored_lbs`
    multiplied by a daily deterioration rate of 0.0008 and by the day count,
    rounded half-up to 2 decimal places — a projection independent of any
    measurement." and "The day count is the whole number of days between sealing
    and survey: the difference between `survey_at` and the pile's `sealed_at`,
    divided by 86400 seconds and rounded down."

    Design: Difficulty/dual_variant_calc/pile_loss_table_rate_vs_resurvey
    """
    world = setup_accepted_world(gross_weight_lbs=72000, tare_weight_lbs=32000,
                                 sugar_pct=17.00, trash_pct=2.00,
                                 estimated_tons=25, pile_capacity_tons=500)
    # accepted 40000 lbs (trash 2.00 <= 3.00: no deduction)
    seal_pile(world["pile"]["id"], clock="2026-10-05T09:00:00Z")
    event = create_loss_event(world["pile"]["id"], "TABLE_RATE",
                              survey_at="2026-10-15T09:00:00Z",
                              window_start="2026-10-15T08:00:00Z",
                              window_end="2026-10-15T10:00:00Z")
    confirmed = validate_success(
        api.confirm_loss_event(event["id"], station_operator_headers), 200)
    assert confirmed["loss_lbs"] == pytest.approx(320.00, abs=1e-9)  # 40000 x 0.0008 x 10
    pile = validate_success(api.get_pile(world["pile"]["id"], pool_accountant_headers), 200)
    # 320.00 / 40000 = 0.80% <= 5.00% -> DETERIORATING
    assert pile["condition_status"] == "DETERIORATING"


def test_resurvey_loss_derives_from_measurement(api, station_operator_headers,
                                                pool_accountant_headers):
    """PRD §3.8: "Under `RESURVEY`, the loss is the pile's `sealed_stored_lbs`,
    minus the sum of `loss_lbs` over the pile's prior `CONFIRMED` or `ALLOCATED`
    events, minus the supplied `measured_remaining_lbs`; the result must be at
    least 0, and a missing measurement or a negative result is rejected with
    `ERR_MEASURED_WEIGHT_INVALID`. For the same pile state the two variants
    generally produce different `loss_lbs`."

    Design: Difficulty/dual_variant_calc/pile_loss_table_rate_vs_resurvey
    """
    world = setup_accepted_world(gross_weight_lbs=72000, tare_weight_lbs=32000,
                                 sugar_pct=17.00, trash_pct=2.00,
                                 estimated_tons=25, pile_capacity_tons=500)
    seal_pile(world["pile"]["id"], clock="2026-10-05T09:00:00Z")
    event = create_loss_event(world["pile"]["id"], "RESURVEY",
                              survey_at="2026-10-15T09:00:00Z",
                              window_start="2026-10-15T08:00:00Z",
                              window_end="2026-10-15T10:00:00Z",
                              measured_remaining_lbs=39600)
    confirmed = validate_success(
        api.confirm_loss_event(event["id"], station_operator_headers), 200)
    assert confirmed["loss_lbs"] == pytest.approx(400.00, abs=1e-9)  # 40000 - 0 - 39600
    pile = validate_success(api.get_pile(world["pile"]["id"], pool_accountant_headers), 200)
    # 400.00 / 40000 = 1.00% <= 5.00% -> DETERIORATING
    assert pile["condition_status"] == "DETERIORATING"


def test_begin_reclaim_blocked_at_inclusive_window_end(api, station_operator_headers):
    """PRD §3.8: "Blackout containment is inclusive at both ends: the clock is
    blocked whenever it is at or after the event's `window_start` and at or
    before its `window_end`; a clock equal to `window_end` is still blocked. A
    blocked attempt is rejected with `ERR_SURVEY_BLACKOUT`."

    Design: Difficulty/resource_temporal_overlap/pile_survey_blackout_inclusive_bounds
    """
    _station, pile = _sealed_empty_pile(api, station_operator_headers)
    create_loss_event(pile["id"], "TABLE_RATE",
                      survey_at="2026-10-10T11:00:00Z",
                      window_start="2026-10-10T10:00:00Z",
                      window_end="2026-10-10T12:00:00Z")
    set_logical_clock("2026-10-10T12:00:00Z")  # exactly window_end
    res = api.begin_reclaim_pile(pile["id"], station_operator_headers)
    validate_error(res, ApiErrorId.ERR_SURVEY_BLACKOUT.value)


def test_begin_reclaim_released_one_second_past_window_end(api, station_operator_headers):
    """PRD §3.8: "Blackout containment is inclusive at both ends: the clock is
    blocked whenever it is at or after the event's `window_start` and at or
    before its `window_end`; a clock equal to `window_end` is still blocked."

    Design: Difficulty/resource_temporal_overlap/pile_survey_blackout_inclusive_bounds
    """
    _station, pile = _sealed_empty_pile(api, station_operator_headers)
    create_loss_event(pile["id"], "TABLE_RATE",
                      survey_at="2026-10-10T11:00:00Z",
                      window_start="2026-10-10T10:00:00Z",
                      window_end="2026-10-10T12:00:00Z")
    set_logical_clock("2026-10-10T12:00:01Z")  # one second past window_end
    pile_after = validate_success(
        api.begin_reclaim_pile(pile["id"], station_operator_headers), 200)
    assert pile_after["fill_status"] == "RECLAIMING"


def test_resurvey_impossible_measured_returns_error(api, station_operator_headers):
    """PRD §3.8: "the result must be at least 0, and a missing measurement or a
    negative result is rejected with `ERR_MEASURED_WEIGHT_INVALID`."

    Only the negative-result branch is asserted here. The missing-measurement
    branch is not uniquely derivable: PRD §3.8 also states
    "`measured_remaining_lbs` ... must be supplied at creation", which a
    faithful implementer may enforce at creation time (request-shape error),
    making the confirm-time missing-measurement path unreachable.

    Design: Corner/validations/resurvey_missing_or_impossible_measured_returns_error
    """
    _station, pile = _sealed_empty_pile(api, station_operator_headers)
    # sealed_stored_lbs == 0 for this empty pile
    le2 = get_success_data(api.create_loss_event(
        create_loss_event_payload(pile["id"], "RESURVEY",
                                  "2026-10-07T09:00:00Z",
                                  "2026-10-07T08:00:00Z", "2026-10-07T10:00:00Z",
                                  measured_remaining_lbs=100),
        station_operator_headers))
    res2 = api.confirm_loss_event(le2["id"], station_operator_headers)
    validate_error(res2, ApiErrorId.ERR_MEASURED_WEIGHT_INVALID.value)  # 0 - 100 < 0


def test_loss_allocate_zero_remaining_guard_and_loss_declared(api, station_operator_headers,
                                                              pool_accountant_headers):
    """PRD §3.8: "The candidates are the pile's allocations in `ACTIVE` status;
    if their `remaining_lbs` sums to zero, nothing is distributed, the event's
    `unallocated_lbs` is set to the full `loss_lbs` (a zero-quantity guard that
    avoids any division), and the event moves to `ALLOCATED`."
    PRD §3.8: "a confirmation that pushes cumulative confirmed loss over 5.00
    percent moves the pile — whether `SOUND` or already `DETERIORATING` — to the
    terminal `LOSS_DECLARED`."

    Design: Corner/calculations/loss_allocate_zero_remaining_guard_and_loss_declared
    """
    world = setup_accepted_world(gross_weight_lbs=72000, tare_weight_lbs=32000,
                                 sugar_pct=16.00, trash_pct=2.00,
                                 estimated_tons=25, pile_capacity_tons=500)
    seal_pile(world["pile"]["id"], clock="2026-10-05T09:00:00Z")
    # First event: RESURVEY measuring 0 lbs remaining -> loss is the full 40000.
    le1 = create_loss_event(world["pile"]["id"], "RESURVEY",
                            survey_at="2026-10-06T09:00:00Z",
                            window_start="2026-10-06T08:00:00Z",
                            window_end="2026-10-06T10:00:00Z",
                            measured_remaining_lbs=0)
    confirmed1 = validate_success(
        api.confirm_loss_event(le1["id"], station_operator_headers), 200)
    assert confirmed1["loss_lbs"] == pytest.approx(40000.00, abs=1e-9)
    validate_success(api.allocate_loss_event(le1["id"], pool_accountant_headers), 200)
    pile = validate_success(api.get_pile(world["pile"]["id"], pool_accountant_headers), 200)
    assert pile["condition_status"] == "LOSS_DECLARED"  # 100% > 5.00%
    assert pile["stored_lbs"] == pytest.approx(0.0, abs=1e-9)

    # Second event: TABLE_RATE over 10 days -> 320.00 lbs computed, but no
    # remaining mass exists to absorb it.
    le2 = create_loss_event(world["pile"]["id"], "TABLE_RATE",
                            survey_at="2026-10-15T09:00:00Z",
                            window_start="2026-10-15T08:00:00Z",
                            window_end="2026-10-15T10:00:00Z")
    confirmed2 = validate_success(
        api.confirm_loss_event(le2["id"], station_operator_headers), 200)
    assert confirmed2["loss_lbs"] == pytest.approx(320.00, abs=1e-9)
    allocated2 = validate_success(
        api.allocate_loss_event(le2["id"], pool_accountant_headers), 200)
    assert allocated2["status"] == "ALLOCATED"
    assert allocated2["unallocated_lbs"] == pytest.approx(320.00, abs=1e-9)
    pile = validate_success(api.get_pile(world["pile"]["id"], pool_accountant_headers), 200)
    assert pile["stored_lbs"] == pytest.approx(0.0, abs=1e-9)


def test_complete_reclaim_shipped_mismatch_then_exact(api, station_operator_headers):
    """PRD §3.8: "Completing the reclaim moves `RECLAIMING` to the terminal
    `EMPTY` state, but the operator must attest the shipped mass: the supplied
    `shipped_lbs` must equal the sum of `remaining_lbs` over the pile's `ACTIVE`
    allocations exactly, otherwise `ERR_SHIPPED_WEIGHT_MISMATCH`."

    Design: Corner/validations/complete_reclaim_shipped_mismatch_then_exact
    """
    world = setup_accepted_world(gross_weight_lbs=72000, tare_weight_lbs=32000,
                                 sugar_pct=16.00, trash_pct=2.00,
                                 estimated_tons=25, pile_capacity_tons=200)
    seal_pile(world["pile"]["id"])
    get_success_data(api.begin_reclaim_pile(world["pile"]["id"], station_operator_headers))
    res = api.complete_reclaim_pile(world["pile"]["id"], {"shipped_lbs": 39999},
                                    station_operator_headers)
    validate_error(res, ApiErrorId.ERR_SHIPPED_WEIGHT_MISMATCH.value)
    pile = validate_success(api.complete_reclaim_pile(
        world["pile"]["id"], {"shipped_lbs": 40000}, station_operator_headers), 200)
    assert pile["fill_status"] == "EMPTY"
    assert pile["stored_lbs"] == pytest.approx(0.0, abs=1e-9)
