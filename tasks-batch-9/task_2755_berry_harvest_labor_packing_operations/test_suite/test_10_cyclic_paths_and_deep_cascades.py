"""
Paths that loop and requests that reach a long way down: the bounded
dispute-and-retally cycle, a lot whose two state dimensions move on their own
schedules, and the two cascades that rewrite rows the caller never named.

Each test walks one whole path and then reads back every row the path was
supposed to touch — and every row it was supposed to leave alone.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers import test_users as u


def _session_on_a_full_day(api, name):
    """
    A tallied session of four hours for 100 clamshells with 2 culled, on a
    domestic crew paying 45 cents a clamshell.

    The saleable count is 98, so the piece earnings of 4410 cents fall short of
    the 6600-cent floor for four hours.
    """
    setup = x.harvest_ready(
        api,
        block_name=name,
        variety="STRAWBERRY",
        picker_count=1,
        labor_program="DOMESTIC",
        supervisor_user_id=u.SUP_1,
        crew_overrides={"name": "CREW-" + name},
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    session = x.tallied_session(
        api,
        setup["window"]["id"],
        setup["picker"]["id"],
        u.SUP_1,
        work_date="2026-08-03",
        hours_worked=4.00,
        clamshells_filled=100,
        culled_clamshells=2,
    )
    return setup, session


def test_a_disputed_tally_may_be_corrected_and_reprices_from_scratch(api):
    """
    Each correction out of `DISPUTED` clears the reason code, consumes one of
    the three permitted revisions and reprices the row from the new counts —
    the first tally out of `OPEN` consuming none of them.

    PRD 3.4: "The saleable clamshells are `clamshells_filled` less `culled_clamshells`. `piece_cents` is that saleable count multiplied by `effective_piece_rate_cents`. Culled clamshells are never paid for."

    PRD 3.4: "A dispute out of `TALLIED` simply stores the reason code and increments the session's `version` by 1."

    PRD 3.4: "A `DISPUTED` session can be re-tallied, moving `DISPUTED → TALLIED`. Each such repeat increments `tally_revision_count` by 1, clears the `dispute_reason_code`, and recomputes every pay figure from the new tally inputs."

    PRD 3.4: "The first tally out of `OPEN` does not consume a revision — the counter records only the corrections applied after the original."

    Design: Difficulty/non_linear_state_machine/pick_session_dispute_retally_cycle_bounded_at_three_revisions
    """
    _, session = _session_on_a_full_day(api, "BLK-NL1")

    a.assert_status(session, "status", "TALLIED")
    assert session["tally_revision_count"] == 0
    a.assert_ratio(session["cull_rate"], 0.0200, "session.cull_rate")
    a.assert_status(session, "quality_flag", "MEETS_STANDARD")
    a.assert_cents(session["piece_cents"], 4410, "first tally.piece_cents")
    a.assert_cents(session["guarantee_floor_cents"], 6600, "first tally.guarantee_floor_cents")
    a.assert_cents(session["makeup_cents"], 2190, "first tally.makeup_cents")
    a.assert_cents(session["gross_cents"], 6600, "first tally.gross_cents")
    a.assert_cents(session["net_cents"], 6600, "first tally.net_cents")

    disputed = x.dispute_session(api, session["id"], "COUNT_DISAGREEMENT")
    a.assert_status(disputed, "status", "DISPUTED")
    assert disputed["dispute_reason_code"] == "COUNT_DISAGREEMENT"
    assert disputed["tally_revision_count"] == 0
    a.assert_cents(disputed["piece_cents"], 4410, "disputed.piece_cents")

    first_fix = x.tally_session(
        api,
        session["id"],
        u.SUP_1,
        hours_worked=4.00,
        clamshells_filled=104,
        culled_clamshells=2,
    )
    a.assert_status(first_fix, "status", "TALLIED")
    assert first_fix["tally_revision_count"] == 1
    a.assert_unset(first_fix, "dispute_reason_code", "corrected session")
    assert first_fix["clamshells_filled"] == 104
    a.assert_ratio(first_fix["cull_rate"], 0.0192, "session.cull_rate")
    a.assert_cents(first_fix["piece_cents"], 4590, "first fix.piece_cents")
    a.assert_cents(first_fix["makeup_cents"], 2010, "first fix.makeup_cents")
    a.assert_cents(first_fix["gross_cents"], 6600, "first fix.gross_cents")

    x.dispute_session(api, session["id"], "COUNT_DISAGREEMENT")
    second_fix = x.tally_session(
        api,
        session["id"],
        u.SUP_1,
        hours_worked=4.00,
        clamshells_filled=106,
        culled_clamshells=2,
    )
    a.assert_status(second_fix, "status", "TALLIED")
    assert second_fix["tally_revision_count"] == 2
    a.assert_ratio(second_fix["cull_rate"], 0.0189, "session.cull_rate")
    a.assert_cents(second_fix["piece_cents"], 4680, "second fix.piece_cents")
    a.assert_cents(second_fix["makeup_cents"], 1920, "second fix.makeup_cents")
    a.assert_cents(second_fix["net_cents"], 6600, "second fix.net_cents")


def test_the_fourth_correction_is_refused_and_the_row_keeps_the_third(api):
    """
    Three corrections exhaust the cap, so the fourth tally is refused and the
    session stays `DISPUTED` carrying the figures the third correction wrote.

    PRD 3.4: "Tallying is admitted from `OPEN` and from `DISPUTED` and from nowhere else, always on an `OPEN` window, and always by the operator named as the crew's `supervisor_user_id`."

    PRD 3.4: "The count is capped: a session that has already used its three permitted revisions is refused with `ERR_TALLY_REVISION_LIMIT`."

    PRD 3.4: "The session lifecycle is cyclic by design: `TALLIED → DISPUTED → TALLIED` and `APPROVED → DISPUTED → TALLIED` are both legitimate paths, bounded only by the three-revision cap."

    Design: Difficulty/non_linear_state_machine/pick_session_dispute_retally_cycle_bounded_at_three_revisions
    """
    _, session = _session_on_a_full_day(api, "BLK-NL2")

    for revision, filled in enumerate((104, 106, 108), start=1):
        x.dispute_session(api, session["id"], "COUNT_DISAGREEMENT")
        corrected = x.tally_session(
            api,
            session["id"],
            u.SUP_1,
            hours_worked=4.00,
            clamshells_filled=filled,
            culled_clamshells=2,
        )
        assert corrected["tally_revision_count"] == revision

    a.assert_cents(corrected["piece_cents"], 4770, "third fix.piece_cents")
    a.assert_cents(corrected["makeup_cents"], 1830, "third fix.makeup_cents")
    a.assert_cents(corrected["net_cents"], 6600, "third fix.net_cents")

    x.dispute_session(api, session["id"], "COUNT_DISAGREEMENT")
    refused = api.tally_pick_session(
        session["id"],
        f.tally_payload(hours_worked=4.00, clamshells_filled=110, culled_clamshells=2),
        x.supervisor_headers(u.SUP_1),
    )
    validate_error(refused, e.ERR_TALLY_REVISION_LIMIT, 409)

    stored = x.read_session(api, session["id"])
    a.assert_status(stored, "status", "DISPUTED")
    assert stored["tally_revision_count"] == 3
    assert stored["clamshells_filled"] == 108
    assert stored["dispute_reason_code"] == "COUNT_DISAGREEMENT"
    a.assert_ratio(stored["cull_rate"], 0.0185, "session.cull_rate")
    a.assert_cents(stored["piece_cents"], 4770, "session.piece_cents")
    a.assert_cents(stored["guarantee_floor_cents"], 6600, "session.guarantee_floor_cents")
    a.assert_cents(stored["makeup_cents"], 1830, "session.makeup_cents")
    a.assert_cents(stored["gross_cents"], 6600, "session.gross_cents")
    a.assert_cents(stored["net_cents"], 6600, "session.net_cents")


def _lot_cooling_with_a_buyer_waiting(api, name):
    """
    A 100-pound grade-A lot part way through a cooling run, and an `OPEN`
    100-pound buyer program that accepts its variety.

    The block carries three passing samples so that the line can later ship.
    """
    block = x.block_with_compliant_water(
        api,
        name=name,
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2022,
        irrigation_source_code="WELL-" + name,
    )
    crew = x.recruit_crew(api, name="CREW-" + name)
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T05:00:00Z",
        end_at="2026-08-03T17:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=200.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    tunnel = x.register_tunnel(
        api, name="TUN-" + name, slot_capacity=4, target_pulp_temp_f=34.0
    )
    lot = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=100,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T07:00:00Z",
        field_pulp_temp_f=64.0,
    )
    x.start_cooling(
        api,
        lot["id"],
        tunnel["id"],
        cool_start_at="2026-08-03T08:00:00Z",
        planned_cool_end_at="2026-08-03T12:00:00Z",
        entry_pulp_temp_f=58.0,
        pallet_slots=1,
    )
    commitment = x.open_commitment(
        api,
        buyer_name="Inland Grocers " + name,
        buyer_user_id="buyer-" + name.lower(),
        variety="STRAWBERRY",
        volume_commitment_lbs=100.00,
        price_cents_per_lb=400,
        shelf_life_guarantee_days=3,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )
    return block, window, tunnel, lot, commitment


def test_a_lot_can_be_pledged_while_it_is_still_inside_the_tunnel(api):
    """
    Pledging looks only at the disposition dimension, so a `COOLING` lot becomes
    `RESERVED` without leaving the tunnel, and completing the run afterwards
    advances the cold chain while leaving the pledge exactly where it was.

    PRD 3.7: "The commitment must still be `OPEN`, and the lot's `disposition_status` must be `UNCOMMITTED` or already `RESERVED`."

    PRD 3.7: "An accepted allocation is created in status `RESERVED`, moves the lot's `disposition_status` to `RESERVED` if it was `UNCOMMITTED`, recomputes the lot's `allocated_lbs` and `available_lbs`, recomputes the commitment's `committed_lbs`, `open_lbs`, `fill_pct`, coverage and `risk_flag`, and increments the `version` of the lot and the commitment by 1."

    PRD 3.6: "It computes `cool_hours` as the elapsed hours from `cool_start_at` to `cool_complete_at` rounded half up to two decimals, stamps `verified_shelf_life_days` and `shelf_life_expires_on` from the verified variant, releases the slots by decrementing the tunnel's `committed_slots` by the lot's `pallet_slots` and incrementing the tunnel's `version` by 1, moves the lot `COOLING → COOLED`, and increments the lot's `version` by 1."

    PRD 2.11: "Fruit lots may be filtered by `harvest_window_id`, by `block_id`, by `source_lot_id` (which is how repack lineage is walked), by `cooling_tunnel_id`, by `cold_chain_status` or by `disposition_status`."

    Design: Difficulty/non_linear_state_machine/fruit_lot_cold_chain_and_disposition_dimensions_advance_independently
    """
    _, _, tunnel, lot, commitment = _lot_cooling_with_a_buyer_waiting(api, "BLK-NL3")

    response = api.create_lot_allocation(
        f.lot_allocation_payload(
            lot["id"], commitment["id"], 100.00, x.commitment_version(api, commitment["id"])
        ),
        u.SALES_MANAGER,
    )
    line = validate_success(response, 201)
    a.assert_status(line, "status", "RESERVED")
    a.assert_pounds(line["allocated_lbs"], 100.00, "line.allocated_lbs")

    pledged = x.read_lot(api, lot["id"])
    a.assert_status(pledged, "cold_chain_status", "COOLING")
    a.assert_status(pledged, "disposition_status", "RESERVED")
    a.assert_pounds(pledged["allocated_lbs"], 100.00, "lot.allocated_lbs")
    a.assert_pounds(pledged["available_lbs"], 0.00, "lot.available_lbs")
    a.assert_pounds(pledged["net_packed_lbs"], 100.00, "lot.net_packed_lbs")
    a.assert_lot_mass_balance(pledged)
    a.assert_unset(pledged, "verified_shelf_life_days", "cooling lot")

    cooling_rows, cooling_meta = x.list_lots(api, cold_chain_status="COOLING")
    a.assert_page_meta(cooling_meta, expected_total=1)
    assert a.ids_of(cooling_rows) == [lot["id"]]
    reserved_rows, reserved_meta = x.list_lots(api, disposition_status="RESERVED")
    a.assert_page_meta(reserved_meta, expected_total=1)
    assert a.ids_of(reserved_rows) == [lot["id"]]

    cooled = x.complete_cooling(
        api,
        lot["id"],
        cool_complete_at="2026-08-03T12:00:00Z",
        exit_pulp_temp_f=34.0,
    )
    a.assert_status(cooled, "cold_chain_status", "COOLED")
    a.assert_status(cooled, "disposition_status", "RESERVED")
    a.assert_hours(cooled["cool_hours"], 4.00, "lot.cool_hours")
    assert cooled["verified_shelf_life_days"] == 7
    assert cooled["shelf_life_expires_on"] == "2026-08-10"
    a.assert_pounds(cooled["allocated_lbs"], 100.00, "lot.allocated_lbs")
    a.assert_pounds(cooled["available_lbs"], 0.00, "lot.available_lbs")

    assert x.read_tunnel(api, tunnel["id"])["committed_slots"] == 0
    assert x.read_allocation(api, line["id"])["status"] == "RESERVED"


def test_the_two_dimensions_only_move_together_when_the_line_ships(api):
    """
    Shipping is the one event that advances both dimensions at once, carrying the
    lot `COOLED → SHIPPED` and `RESERVED → DELIVERED` and pushing the pounds onto
    the buyer's shipped total.

    PRD 3.7: "The lot's `cold_chain_status` must be exactly `COOLED` — fruit that is still `PACKED` or `COOLING` has no verified shelf life to sell against, and the rejection is `ERR_INVALID_COLD_CHAIN_STATE`."

    PRD 3.7: "Shipping stores `shipped_at`, moves the lot's `cold_chain_status` `COOLED → SHIPPED` and its `disposition_status` `RESERVED → DELIVERED`, increases the commitment's `shipped_lbs` by the line's `allocated_lbs` and recomputes `fill_pct`, and increments the `version` of the allocation, the lot and the commitment each by 1."

    PRD 3.7: "`committed_lbs` is the sum of `allocated_lbs` over the commitment's `RESERVED` and `SHIPPED` lines, `shipped_lbs` the sum over the `SHIPPED` lines alone, and `open_lbs` is `volume_commitment_lbs` less `committed_lbs`, floored at 0.00 and carried to two decimals."

    Design: Difficulty/non_linear_state_machine/fruit_lot_cold_chain_and_disposition_dimensions_advance_independently
    """
    _, _, _, lot, commitment = _lot_cooling_with_a_buyer_waiting(api, "BLK-NL4")

    line = x.allocate(api, lot["id"], commitment["id"], 100.00)
    x.complete_cooling(
        api,
        lot["id"],
        cool_complete_at="2026-08-03T12:00:00Z",
        exit_pulp_temp_f=34.0,
    )

    shipped_line = x.ship_allocation(api, line["id"], "2026-08-04T09:00:00Z")
    a.assert_status(shipped_line, "status", "SHIPPED")
    a.assert_instant(
        shipped_line["shipped_at"], "2026-08-04T09:00:00Z", "line.shipped_at"
    )

    delivered = x.read_lot(api, lot["id"])
    a.assert_status(delivered, "cold_chain_status", "SHIPPED")
    a.assert_status(delivered, "disposition_status", "DELIVERED")
    a.assert_pounds(delivered["allocated_lbs"], 100.00, "lot.allocated_lbs")
    a.assert_pounds(delivered["available_lbs"], 0.00, "lot.available_lbs")
    assert delivered["verified_shelf_life_days"] == 7

    filled = x.read_commitment(api, commitment["id"])
    a.assert_status(filled, "status", "OPEN")
    a.assert_commitment_exposure(filled, 100.00, 100.00)
    a.assert_ratio(filled["fill_pct"], 1.0000, "commitment.fill_pct")


def _live_block_with_paid_and_unpriced_work(api, name):
    """
    An `OPEN` window on a `CLEARED` block carrying one `APPROVED` session worth
    4950 cents, one still-`OPEN` session, and one packed lot.

    Returns the setup dict plus the paid session, the unpriced session and the
    lot.
    """
    setup = x.harvest_ready(
        api,
        block_name=name,
        variety="STRAWBERRY",
        picker_count=2,
        planned_head_count=2,
        labor_program="DOMESTIC",
        supervisor_user_id=u.SUP_1,
        crew_overrides={"name": "CREW-" + name},
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    paid = x.approved_session(
        api,
        setup["window"]["id"],
        setup["pickers"][0]["id"],
        u.SUP_1,
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
        culled_clamshells=0,
    )
    unpriced = x.open_session(
        api,
        setup["window"]["id"],
        setup["pickers"][1]["id"],
        u.SUP_1,
        work_date="2026-08-03",
    )
    lot = x.pack_lot(
        api,
        setup["window"]["id"],
        setup["block"]["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=50,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T12:00:00Z",
        field_pulp_temp_f=70.0,
    )
    return setup, paid, unpriced, lot


def test_a_quarantine_suspends_the_running_window_and_holds_its_fruit(api):
    """
    One hold on the block stops the shift and freezes the fruit: the `OPEN`
    window is suspended with the cascade's own reason code and the uncommitted
    lot goes on food-safety hold, all without the caller naming either.

    PRD 3.1: "`manual_quarantine_active` becomes true, `quarantined_by_user_id` records the acting operator, `quarantine_reason_code` is stored, and the posture becomes `QUARANTINED`."

    PRD 3.1: "**Level 1:** every harvest window on this block whose status is `CONFIRMED` or `OPEN`, processed in ascending `start_at` and then ascending `created_at` order, moves to `SUSPENDED` with `suspended_reason_code` set to `BLOCK_QUARANTINE`."

    PRD 3.1: "Independently of the window chain, every fruit lot whose traceability block is this block and whose `disposition_status` is `UNCOMMITTED` or `RESERVED` has `food_safety_hold` set to true."

    PRD 3.1: "The block's `version` is incremented by 1, as is the `version` of every window, session, crew, picker and lot the cascade touched."

    Design: Difficulty/transitive_cascade/block_quarantine_cascades_four_levels_to_crew_wage_ledger
    """
    setup, _, _, lot = _live_block_with_paid_and_unpriced_work(api, "BLK-TC1")

    held = x.quarantine_block(
        api, setup["block"]["id"], reason_code="ADJACENT_LIVESTOCK_INTRUSION"
    )
    a.assert_status(held, "food_safety_posture", "QUARANTINED")
    assert held["manual_quarantine_active"] is True
    assert held["quarantined_by_user_id"] == u.FSO_1
    assert held["quarantine_reason_code"] == "ADJACENT_LIVESTOCK_INTRUSION"
    a.assert_status(held, "water_status", "PROVISIONAL")
    assert held["version"] == 3

    suspended = x.read_window(api, setup["window"]["id"])
    a.assert_status(suspended, "status", "SUSPENDED")
    assert suspended["suspended_reason_code"] == "BLOCK_QUARANTINE"
    a.assert_unset(suspended, "cancel_reason_code", "suspended window")

    frozen = x.read_lot(api, lot["id"])
    assert frozen["food_safety_hold"] is True
    a.assert_status(frozen, "disposition_status", "UNCOMMITTED")
    a.assert_status(frozen, "cold_chain_status", "PACKED")
    a.assert_pounds(frozen["available_lbs"], 50.00, "lot.available_lbs")
    assert frozen["version"] == 2

    crew = x.read_crew(api, setup["crew"]["id"])
    a.assert_status(crew, "status", "ACTIVE")


def test_the_quarantine_reverses_the_paid_day_and_voids_the_unpriced_one(api):
    """
    Four levels down, the approved day is pulled back to `DISPUTED` and its exact
    net is subtracted from the crew ledger, while the day that had never been
    priced is voided and moves no money at all.

    PRD 3.1: "**Level 2**, caused by level 1: for each window that just entered `SUSPENDED`, its pick sessions are processed in ascending `created_at` order. Those whose status is `OPEN` or `TALLIED` move to `VOIDED` with `void_reason_code` set to `WINDOW_SUSPENDED` — a `TALLIED` session keeps its computed pay figures for audit even though it will never be paid. Those whose status is `APPROVED` move to `DISPUTED` with `dispute_reason_code` set to `WINDOW_SUSPENDED`."

    PRD 3.1: "**Level 3**, caused by level 2: for each session that just left `APPROVED`, the crew's `accrued_wage_cents` is reduced by that session's stored `net_cents`, and the picker's `total_clamshells_lifetime`, `total_hours_lifetime` and `avg_lbs_per_hour`, together with the window's `harvested_clamshells`, are recomputed over the sessions that remain `APPROVED` or `SETTLED`. Sessions that went to `VOIDED` from `OPEN` or `TALLIED` produce no ledger movement at all, because they had never accrued."

    PRD 3.8: "An `OPEN` or `TALLIED` session is voided, and because it had never accrued, **no** ledger decrement is performed — subtracting for a voided session would corrupt the ledger downward."

    Design: Difficulty/transitive_cascade/block_quarantine_cascades_four_levels_to_crew_wage_ledger
    """
    setup, paid, unpriced, _ = _live_block_with_paid_and_unpriced_work(api, "BLK-TC2")

    a.assert_cents(paid["net_cents"], 4950, "approved session.net_cents")
    before = x.read_crew(api, setup["crew"]["id"])
    a.assert_cents(before["accrued_wage_cents"], 4950, "crew.accrued_wage_cents")
    earner_before = x.read_picker(api, setup["pickers"][0]["id"])
    assert earner_before["total_clamshells_lifetime"] == 20
    a.assert_hours(earner_before["total_hours_lifetime"], 3.00, "picker.total_hours_lifetime")
    a.assert_rate(earner_before["avg_lbs_per_hour"], 6.67, "picker.avg_lbs_per_hour")

    x.quarantine_block(
        api, setup["block"]["id"], reason_code="ADJACENT_LIVESTOCK_INTRUSION"
    )

    pulled_back = x.read_session(api, paid["id"])
    a.assert_status(pulled_back, "status", "DISPUTED")
    assert pulled_back["dispute_reason_code"] == "WINDOW_SUSPENDED"
    a.assert_unset(pulled_back, "approved_by_user_id", "disputed session")
    a.assert_unset(pulled_back, "void_reason_code", "disputed session")
    a.assert_cents(pulled_back["net_cents"], 4950, "disputed session.net_cents")
    a.assert_cents(pulled_back["gross_cents"], 4950, "disputed session.gross_cents")

    voided = x.read_session(api, unpriced["id"])
    a.assert_status(voided, "status", "VOIDED")
    assert voided["void_reason_code"] == "WINDOW_SUSPENDED"
    a.assert_status(voided, "quality_flag", "PENDING")
    a.assert_cents(voided["net_cents"], 0, "voided session.net_cents")

    after = x.read_crew(api, setup["crew"]["id"])
    a.assert_cents(after["accrued_wage_cents"], 0, "crew.accrued_wage_cents")
    a.assert_cents(after["settled_wage_cents"], 0, "crew.settled_wage_cents")
    a.assert_cents(
        after["reconciliation_delta_cents"], 0, "crew.reconciliation_delta_cents"
    )

    earner_after = x.read_picker(api, setup["pickers"][0]["id"])
    assert earner_after["total_clamshells_lifetime"] == 0
    a.assert_hours(earner_after["total_hours_lifetime"], 0.00, "picker.total_hours_lifetime")
    a.assert_rate(earner_after["avg_lbs_per_hour"], 0.00, "picker.avg_lbs_per_hour")

    stalled = x.read_window(api, setup["window"]["id"])
    assert stalled["harvested_clamshells"] == 0


def _pledged_cooled_lot(api, name):
    """
    A `COOLED` 100-clamshell lot with 60.00 lbs pledged to an `OPEN` program.

    Returns the lot, the commitment and the reserved allocation line.
    """
    block = x.block_with_compliant_water(api, name=name)
    crew = x.recruit_crew(api, name="CREW-" + name)
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T05:00:00Z",
        end_at="2026-08-03T17:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=200.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    tunnel = x.register_tunnel(api, name="TUN-" + name, slot_capacity=4, target_pulp_temp_f=34.0)
    lot = x.cooled_lot(
        api,
        window["id"],
        block["id"],
        tunnel["id"],
        cool_start_at="2026-08-03T08:00:00Z",
        planned_cool_end_at="2026-08-03T12:00:00Z",
        cool_complete_at="2026-08-03T12:00:00Z",
        entry_pulp_temp_f=58.0,
        exit_pulp_temp_f=34.0,
        pallet_slots=1,
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=100,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T07:00:00Z",
        field_pulp_temp_f=64.0,
    )
    assert lot["verified_shelf_life_days"] == 7
    commitment = x.open_commitment(
        api,
        variety="STRAWBERRY",
        volume_commitment_lbs=100.00,
        price_cents_per_lb=400,
        shelf_life_guarantee_days=3,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )
    line = x.allocate(api, lot["id"], commitment["id"], 60.00)
    return lot, commitment, line


def test_rejecting_a_pledged_lot_releases_its_line_with_the_cascade_code(api):
    """
    One rejection on the packing line reaches the sales ledger: the lot is held
    and emptied, and the buyer's reserved line is let go under the cascade's own
    reason code, which no caller supplied.

    PRD 3.6: "Rejection sets `food_safety_hold` true, drives `available_lbs` to 0.00, moves the lot to `REJECTED`, recomputes the parent window's `packed_lbs`, and increments the lot's and the window's `version` by 1."

    PRD 3.6: "From `RESERVED` it cascades two levels: every lot allocation of that lot in status `RESERVED` moves to `RELEASED` with `release_reason_code` set to `LOT_REJECTED`, and each affected buyer commitment has its `committed_lbs_exposure` reduced by exactly that line's `allocated_lbs`, with the `version` of every touched allocation and commitment incremented by 1."

    PRD 3.6: "`REJECTED` is terminal on the disposition dimension."

    Design: Difficulty/transitive_cascade/lot_rejection_cascades_three_levels_to_buyer_commitment_exposure
    """
    lot, _, line = _pledged_cooled_lot(api, "BLK-TC3")
    a.assert_status(line, "status", "RESERVED")

    rejected = x.reject_lot(api, lot["id"], reason_code="SOFT_FRUIT_BREAKDOWN")
    a.assert_status(rejected, "disposition_status", "REJECTED")
    assert rejected["food_safety_hold"] is True
    a.assert_pounds(rejected["available_lbs"], 0.00, "lot.available_lbs")
    assert rejected["reject_reason_code"] == "SOFT_FRUIT_BREAKDOWN"
    a.assert_status(rejected, "cold_chain_status", "COOLED")
    a.assert_pounds(rejected["net_packed_lbs"], 100.00, "lot.net_packed_lbs")
    assert rejected["version"] == 5

    let_go = x.read_allocation(api, line["id"])
    a.assert_status(let_go, "status", "RELEASED")
    assert let_go["release_reason_code"] == "LOT_REJECTED"
    a.assert_pounds(let_go["allocated_lbs"], 60.00, "allocation.allocated_lbs")
    a.assert_unset(let_go, "shipped_at", "released line")
    assert let_go["version"] == 2


def test_the_released_line_leaves_the_program_exposure_exactly_as_it_was(api):
    """
    Three levels down, the buyer program is back to nothing committed: the
    exposure is compensated by precisely the pledged pounds, and the released
    line counts towards no figure at all.

    PRD 3.7: "Release requires the commitment to be `OPEN` and is an **exact compensation**, not a recomputation from scratch of anything the line did not touch: the commitment's `committed_lbs` is decremented by precisely that line's `allocated_lbs`, its `open_lbs` and `risk_flag` are recomputed, and its `version` is incremented by 1; the lot's `allocated_lbs` and `available_lbs` are restored to their pre-allocation values and its `version` is incremented by 1; and the lot's `disposition_status` returns from `RESERVED` to `UNCOMMITTED` only when no `RESERVED` or `SHIPPED` line of that lot remains — a lot pledged to two buyers stays `RESERVED` when one of them lets go."

    PRD 3.7: "`RELEASED` lines are excluded from every subsequent figure — exposure, revenue and fill alike — so a released line leaves no trace."

    PRD 3.7: "The exposure figures are always recomputed from the surviving allocation rows rather than nudged: `committed_lbs` is the sum of `allocated_lbs` over the commitment's `RESERVED` and `SHIPPED` lines, `shipped_lbs` the sum over the `SHIPPED` lines alone, and `open_lbs` is `volume_commitment_lbs` less `committed_lbs`, floored at 0.00 and carried to two decimals."

    Design: Difficulty/transitive_cascade/lot_rejection_cascades_three_levels_to_buyer_commitment_exposure
    """
    lot, commitment, line = _pledged_cooled_lot(api, "BLK-TC4")
    pledged = x.read_commitment(api, commitment["id"])
    a.assert_commitment_exposure(pledged, 60.00, 0.00)
    a.assert_pounds(pledged["open_lbs"], 40.00, "commitment.open_lbs")

    x.reject_lot(api, lot["id"], reason_code="SOFT_FRUIT_BREAKDOWN")

    unwound = x.read_commitment(api, commitment["id"])
    a.assert_commitment_exposure(unwound, 0.00, 0.00)
    a.assert_pounds(unwound["open_lbs"], 100.00, "commitment.open_lbs")
    a.assert_ratio(unwound["fill_pct"], 0.0000, "commitment.fill_pct")
    a.assert_status(unwound, "fill_status", "PENDING")
    a.assert_status(unwound, "status", "OPEN")
    a.assert_status(unwound, "risk_flag", "ON_TRACK")
    a.assert_unset(unwound, "settled_revenue_cents", "open commitment")
    assert unwound["version"] == 3

    rows, meta = x.list_allocations(api, buyer_commitment_id=commitment["id"])
    a.assert_page_meta(meta, expected_total=1)
    assert a.ids_of(rows) == [line["id"]]
    a.assert_status(rows[0], "status", "RELEASED")
