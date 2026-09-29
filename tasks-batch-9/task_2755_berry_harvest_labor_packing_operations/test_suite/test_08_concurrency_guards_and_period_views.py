"""
Layers that only appear when several mechanisms are stacked in one sequence: the
two mandatory expected-version guards refusing a stale view and then admitting
the re-read one, the period-averaged settlement diverging from the summed
per-session accrual, and the commitment risk flag pivoting on the logical clock.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers import test_users as u


def _sampled_block_with_window(api, name: str, **window_overrides):
    """A CLEARED block, a crew and a PLANNED window over 2026-08-03."""
    block = x.register_block(
        api,
        name=name,
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-" + name,
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew = x.recruit_crew(api, name="CREW-" + name)
    settings = dict(
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    settings.update(window_overrides)
    window = x.plan_window(api, block["id"], crew["id"], **settings)
    return block, crew, window


def _packed_lot(api, window_id, block_id, clamshells, pack_at="2026-08-03T12:00:00Z"):
    """One PACKED grade-A lot of one-pound clamshells."""
    return x.pack_lot(
        api,
        window_id,
        block_id,
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=clamshells,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at=pack_at,
        field_pulp_temp_f=62.0,
    )


def test_a_stale_tunnel_version_is_refused_and_the_reread_version_admitted(api):
    """
    The first lot into the tunnel advances the version the second lot is still
    holding, so the second admission is refused on the guard alone — no slot is
    taken and no tunnel identifier is stamped — and the same request carrying the
    re-read version then succeeds because room genuinely remains.

    PRD 2.8: "Pushing a lot into a forced-air tunnel requires `expected_cooling_tunnel_version`, carrying the client's last observed `version` of the target `CoolingTunnel`. If that value does not match the tunnel's current `version`, the request is rejected with `ERR_STALE_TUNNEL_VERSION` and HTTP 412."

    PRD 2.8: "A caller that re-reads the tunnel and resubmits with the current `version` succeeds whenever room genuinely remains."

    Design: Corner/cross_cutting_complexity_layers/stale_tunnel_version_conflicts_then_succeeds_after_a_reread
    """
    block, _, window = _sampled_block_with_window(api, "BLK-V32")
    tunnel = x.register_tunnel(api, name="TUN-V32", slot_capacity=4)
    observed_version = tunnel["version"]

    first = _packed_lot(api, window["id"], block["id"], 50)
    second = _packed_lot(
        api, window["id"], block["id"], 50, pack_at="2026-08-03T12:30:00Z"
    )

    x.start_cooling(
        api,
        first["id"],
        tunnel["id"],
        expected_version=observed_version,
        cool_start_at="2026-08-03T13:00:00Z",
        planned_cool_end_at="2026-08-03T17:00:00Z",
        entry_pulp_temp_f=62.0,
        pallet_slots=1,
    )
    after_first = x.read_tunnel(api, tunnel["id"])
    assert after_first["committed_slots"] == 1
    assert after_first["version"] == observed_version + 1

    validate_error(
        api.start_cooling(
            second["id"],
            f.start_cooling_payload(
                tunnel["id"],
                observed_version,
                cool_start_at="2026-08-03T13:30:00Z",
                planned_cool_end_at="2026-08-03T17:30:00Z",
                entry_pulp_temp_f=61.0,
                pallet_slots=1,
            ),
            u.PACKHOUSE_OPERATOR,
        ),
        e.ERR_STALE_TUNNEL_VERSION,
        412,
    )
    refused_tunnel = x.read_tunnel(api, tunnel["id"])
    assert refused_tunnel["committed_slots"] == 1
    refused_lot = x.read_lot(api, second["id"])
    a.assert_status(refused_lot, "cold_chain_status", "PACKED")
    a.assert_unset(refused_lot, "cooling_tunnel_id", "lot")

    current_version = x.tunnel_version(api, tunnel["id"])
    assert current_version == 2

    admitted = validate_success(
        api.start_cooling(
            second["id"],
            f.start_cooling_payload(
                tunnel["id"],
                current_version,
                cool_start_at="2026-08-03T13:30:00Z",
                planned_cool_end_at="2026-08-03T17:30:00Z",
                entry_pulp_temp_f=61.0,
                pallet_slots=1,
            ),
            u.PACKHOUSE_OPERATOR,
        ),
        200,
    )
    a.assert_status(admitted, "cold_chain_status", "COOLING")
    assert admitted["cooling_tunnel_id"] == tunnel["id"]

    final_tunnel = x.read_tunnel(api, tunnel["id"])
    assert final_tunnel["committed_slots"] == 2
    assert final_tunnel["slot_capacity"] == 4
    assert final_tunnel["version"] == 3


def test_a_stale_commitment_version_is_refused_and_the_reread_version_admitted(api):
    """
    Pledging pounds is guarded the same way and for the same reason: the first
    pledge advanced the exposure the second was sized against, so the stale
    second pledge moves nothing, and the re-read guard admits it once the caller
    is reasoning about the pounds the server actually holds.

    PRD 2.8: "Pledging pounds against a buyer program requires `expected_buyer_commitment_version`, carrying the client's last observed `version` of the target `BuyerCommitment`. A mismatch with the commitment's current `version` is rejected with `ERR_STALE_COMMITMENT_VERSION` and HTTP 412."

    PRD 2.8: "Re-reading the commitment and resubmitting succeeds while `open_lbs` still covers the request."

    Design: Corner/cross_cutting_complexity_layers/stale_commitment_version_conflicts_then_succeeds_after_a_reread
    """
    block, _, window = _sampled_block_with_window(api, "BLK-V33")
    first = _packed_lot(api, window["id"], block["id"], 50)
    second = _packed_lot(
        api, window["id"], block["id"], 50, pack_at="2026-08-03T12:30:00Z"
    )
    commitment = x.open_commitment(
        api,
        buyer_name="PROGRAM-V33",
        variety="STRAWBERRY",
        volume_commitment_lbs=200.00,
        price_cents_per_lb=400,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )
    observed_version = commitment["version"]

    x.allocate(
        api, first["id"], commitment["id"], 40.00, expected_version=observed_version
    )

    validate_error(
        api.create_lot_allocation(
            f.lot_allocation_payload(
                second["id"], commitment["id"], 30.00, observed_version
            ),
            u.SALES_MANAGER,
        ),
        e.ERR_STALE_COMMITMENT_VERSION,
        412,
    )
    refused = x.read_commitment(api, commitment["id"])
    a.assert_pounds(refused["committed_lbs"], 40.00, "commitment.committed_lbs")
    a.assert_status(x.read_lot(api, second["id"]), "disposition_status", "UNCOMMITTED")
    _, refused_meta = x.list_allocations(api, buyer_commitment_id=commitment["id"])
    a.assert_page_meta(refused_meta, expected_total=1)

    current_version = x.commitment_version(api, commitment["id"])
    assert current_version == 2

    admitted = validate_success(
        api.create_lot_allocation(
            f.lot_allocation_payload(
                second["id"], commitment["id"], 30.00, current_version
            ),
            u.SALES_MANAGER,
        ),
        201,
    )
    a.assert_status(admitted, "status", "RESERVED")
    a.assert_pounds(admitted["allocated_lbs"], 30.00, "allocation.allocated_lbs")

    final = x.read_commitment(api, commitment["id"])
    a.assert_pounds(final["committed_lbs"], 70.00, "commitment.committed_lbs")
    a.assert_pounds(final["open_lbs"], 130.00, "commitment.open_lbs")
    assert final["version"] == 3

    a.assert_pounds(
        x.read_lot(api, first["id"])["available_lbs"], 10.00, "lot1.available_lbs"
    )
    a.assert_pounds(
        x.read_lot(api, second["id"])["available_lbs"], 20.00, "lot2.available_lbs"
    )
    _, final_meta = x.list_allocations(api, buyer_commitment_id=commitment["id"])
    a.assert_page_meta(final_meta, expected_total=2)


def test_the_settled_period_average_diverges_from_the_summed_session_accrual(api):
    """
    Two sessions of the same period, one short of the hourly floor and one well
    past it, accrue 13950 cents session by session but settle at 9900 on the
    period, because the floor is applied once to the summed hours; the run records
    both figures and the signed difference between them.

    PRD 3.5: "`period_hours` is **summed first and multiplied once**: `period_floor_cents` is `period_hours` multiplied by the same minimum of 1650 cents per hour, rounded half up to a whole cent. It is emphatically *not* the sum of the individual sessions' `guarantee_floor_cents`."

    PRD 3.5: "On the period the figures are `period_hours` 6.00, `period_piece_cents` 9900, `period_floor_cents` 9900, `period_makeup_cents` 0, `settled_gross_cents` 9900, `period_deduction_cents` 0 and `settled_net_cents` 9900 — session B's surplus absorbs session A's shortfall entirely — so `reconciliation_delta_cents` is 9900 less 13950, that is −4050."

    PRD 3.5: "From the stamped set the run records `bound_session_count`, `period_hours` as the sum of `hours_worked` to two decimals, `period_piece_cents` as the sum of `piece_cents`, and `accrued_gross_cents` as the sum of `gross_cents` — the per-session figure, captured for comparison."

    Design: Corner/cross_cutting_complexity_layers/period_averaged_settlement_diverges_from_the_summed_session_view
    """
    block = x.register_block(
        api,
        name="BLK-V34",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V34",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, pickers = x.certified_crew(
        api,
        picker_count=2,
        name="CREW-V34",
        labor_program="DOMESTIC",
        supervisor_user_id=u.SUP_1,
    )
    window = x.opened_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )

    short_session = x.approved_session(
        api,
        window["id"],
        pickers[0]["id"],
        supervisor_user_id=u.SUP_1,
        approver_headers=u.PAYROLL_CLERK,
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
        culled_clamshells=0,
    )
    fast_session = x.approved_session(
        api,
        window["id"],
        pickers[1]["id"],
        supervisor_user_id=u.SUP_1,
        approver_headers=u.PAYROLL_CLERK,
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=200,
        culled_clamshells=0,
    )
    a.assert_cents(short_session["piece_cents"], 900, "sessionA.piece_cents")
    a.assert_cents(short_session["gross_cents"], 4950, "sessionA.gross_cents")
    a.assert_cents(short_session["net_cents"], 4950, "sessionA.net_cents")
    a.assert_cents(fast_session["piece_cents"], 9000, "sessionB.piece_cents")
    a.assert_cents(fast_session["gross_cents"], 9000, "sessionB.gross_cents")
    a.assert_cents(fast_session["net_cents"], 9000, "sessionB.net_cents")

    run = x.locked_payroll_run(
        api,
        crew["id"],
        locker_headers=u.PAYROLL_CLERK,
        period_start_date="2026-08-03",
        period_end_date="2026-08-03",
    )
    assert run["bound_session_count"] == 2
    a.assert_cents(run["accrued_gross_cents"], 13950, "run.accrued_gross_cents")

    settled = validate_success(
        api.settle_payroll_run(run["id"], u.PAYROLL_CLERK_2), 200
    )
    a.assert_status(settled, "status", "SETTLED")
    assert settled["bound_session_count"] == 2
    a.assert_hours(settled["period_hours"], 6.00, "run.period_hours")
    a.assert_cents(settled["period_piece_cents"], 9900, "run.period_piece_cents")
    a.assert_cents(settled["period_floor_cents"], 9900, "run.period_floor_cents")
    a.assert_cents(settled["period_makeup_cents"], 0, "run.period_makeup_cents")
    a.assert_cents(settled["period_deduction_cents"], 0, "run.period_deduction_cents")
    a.assert_cents(settled["settled_gross_cents"], 9900, "run.settled_gross_cents")
    a.assert_cents(settled["settled_net_cents"], 9900, "run.settled_net_cents")
    a.assert_cents(settled["accrued_gross_cents"], 13950, "run.accrued_gross_cents")
    a.assert_cents(
        settled["reconciliation_delta_cents"], -4050, "run.reconciliation_delta_cents"
    )

    reconciled = x.read_crew(api, crew["id"])
    a.assert_cents(reconciled["accrued_wage_cents"], 0, "crew.accrued_wage_cents")
    a.assert_cents(reconciled["settled_wage_cents"], 9900, "crew.settled_wage_cents")
    a.assert_cents(
        reconciled["reconciliation_delta_cents"],
        -4050,
        "crew.reconciliation_delta_cents",
    )

    for session in (short_session, fast_session):
        a.assert_status(x.read_session(api, session["id"]), "status", "SETTLED")


def test_the_risk_flag_waits_for_the_clock_to_pass_the_three_day_lead(api):
    """
    Coverage of half the contracted pounds is not enough on its own: on the lead
    date itself the program is still `ON_TRACK`, and only once the logical clock
    moves past `window_end_date` less three days does the very next allocation
    event flip the same under-covered program to `AT_RISK`.

    PRD 3.7: "`risk_flag` becomes `AT_RISK` when the logical clock date is past `window_end_date` less the three-day risk lead **and** coverage is still below the ninety-five percent fill target, and `ON_TRACK` in every other case; it is re-evaluated on every allocation event, never only at settlement."

    PRD 2.5: "Nothing in this system reads the host machine's wall clock. The service maintains a single logical UTC instant, and every date-sensitive rule consults it: whether a picker's hygiene training is still valid, whether a harvest window may still be opened or resumed, whether a buyer program's delivery window has closed and the program may therefore be settled, whether a lot is still inside its shelf life on the day it ships, and whether a commitment should be flagged as at risk of shortfall."

    Design: Corner/cross_cutting_complexity_layers/commitment_risk_flag_flips_only_past_the_three_day_lead_threshold
    """
    block, _, window = _sampled_block_with_window(api, "BLK-V35")
    first = _packed_lot(api, window["id"], block["id"], 100)
    second = _packed_lot(
        api, window["id"], block["id"], 100, pack_at="2026-08-03T12:30:00Z"
    )
    commitment = x.open_commitment(
        api,
        buyer_name="PROGRAM-V35",
        variety="STRAWBERRY",
        volume_commitment_lbs=200.00,
        price_cents_per_lb=400,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )
    observed_version = commitment["version"]

    x.set_clock(api, "2026-08-07T00:00:00Z")
    x.allocate(
        api, first["id"], commitment["id"], 50.00, expected_version=observed_version
    )
    on_the_lead_date = x.read_commitment(api, commitment["id"])
    a.assert_status(on_the_lead_date, "risk_flag", "ON_TRACK")
    a.assert_pounds(
        on_the_lead_date["committed_lbs"], 50.00, "commitment.committed_lbs"
    )
    a.assert_pounds(on_the_lead_date["open_lbs"], 150.00, "commitment.open_lbs")

    x.set_clock(api, "2026-08-08T00:00:00Z")
    current_version = x.commitment_version(api, commitment["id"])
    assert current_version == 2

    line = validate_success(
        api.create_lot_allocation(
            f.lot_allocation_payload(
                second["id"], commitment["id"], 50.00, current_version
            ),
            u.SALES_MANAGER,
        ),
        201,
    )
    a.assert_status(line, "status", "RESERVED")

    past_the_lead_date = x.read_commitment(api, commitment["id"])
    a.assert_status(past_the_lead_date, "risk_flag", "AT_RISK")
    a.assert_pounds(
        past_the_lead_date["committed_lbs"], 100.00, "commitment.committed_lbs"
    )
    a.assert_pounds(past_the_lead_date["open_lbs"], 100.00, "commitment.open_lbs")
    a.assert_pounds(past_the_lead_date["shipped_lbs"], 0.00, "commitment.shipped_lbs")
    a.assert_ratio(past_the_lead_date["fill_pct"], 0.0000, "commitment.fill_pct")
    a.assert_status(past_the_lead_date, "status", "OPEN")
    assert past_the_lead_date["version"] == 3

    lines, meta = x.list_allocations(api, buyer_commitment_id=commitment["id"])
    a.assert_page_meta(meta, expected_total=2)
    for row in lines:
        a.assert_status(row, "status", "RESERVED")
