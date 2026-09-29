"""
Who may act, and in which capacity: the endpoint role matrix, the one
entity-backed identity among the seven roles, the two ownership comparisons
that guard a pick session, and the three segregation-of-duties splits that are
enforced on the acting operator identifier rather than on the role.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers import test_users as u


def _cleared_block(api, name: str):
    """A block with one passing sample, so its posture is CLEARED."""
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
    return block


def _window_over_the_third(api, block_id: str, crew_id: str):
    """A window on 2026-08-03 at 45 cents a clamshell and one pound a clamshell."""
    return x.opened_window(
        api,
        block_id,
        crew_id,
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )


def test_no_role_may_borrow_another_roles_exclusive_write(api):
    """
    Block registration belongs to the harvest manager and tunnel registration to
    the packhouse; a caller in the wrong capacity is refused on the role matrix
    before any body field is looked at, and neither collection gains a row.

    PRD 2.7 rule 3: "(3) The acting role appears on the target endpoint's authorized list, otherwise `ERR_FORBIDDEN_ROLE`, on every endpoint."

    PRD 2.1: "The seven roles are `HarvestManager`, `FoodSafetyOfficer`, `CrewSupervisor`, `PayrollClerk`, `PackhouseOperator`, `SalesManager` and `Picker`."

    Design: Corner/rbac/cross_role_writes_cannot_borrow_another_roles_exclusive_operations
    """
    validate_error(
        api.create_block(
            f.block_payload(
                name="BLK-V25",
                variety="STRAWBERRY",
                acres=8.00,
                planting_year=2021,
                irrigation_source_code="WELL-V25",
            ),
            u.CREW_SUPERVISOR,
        ),
        e.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.create_cooling_tunnel(
            f.cooling_tunnel_payload(
                name="TUN-V25", slot_capacity=2, target_pulp_temp_f=34.0
            ),
            u.SALES_MANAGER,
        ),
        e.ERR_FORBIDDEN_ROLE,
        403,
    )

    _, block_meta = validate_paginated(api.list_blocks(u.HARVEST_MANAGER))
    a.assert_page_meta(block_meta, expected_total=0)
    _, tunnel_meta = validate_paginated(
        api.list_cooling_tunnels(u.PACKHOUSE_OPERATOR)
    )
    a.assert_page_meta(tunnel_meta, expected_total=0)


def test_the_picker_role_needs_an_identity_that_resolves_to_a_picker_row(api):
    """
    Six roles carry an opaque identifier, but the seventh is resolved against
    the table: an operator string that is not a `Picker` id cannot list sessions
    at all, while the registered picker's own id reads an empty list.

    PRD 2.1: "A caller who presents the `Picker` role with an `X-User-ID` that does not resolve to an existing `Picker` row is rejected with `ERR_FORBIDDEN_ROLE`; this identity resolution is enforced on the three endpoints a `Picker` may reach — disputing a session, reading one session, and listing sessions."

    PRD 2.7 rule 4: "(4) When the acting role is `Picker`, `X-User-ID` resolves to an existing `Picker` row, otherwise `ERR_FORBIDDEN_ROLE`; this applies to disputing a pick session, reading one pick session, and listing pick sessions."

    Design: Corner/rbac/picker_role_without_an_entity_backed_picker_identity_is_forbidden
    """
    crew = x.recruit_crew(api, name="CREW-V26")
    picker = x.register_picker(api, crew["id"], full_name="Vera Twenty Six")

    validate_error(
        api.list_pick_sessions(u.make_picker_headers(u.HM_1)),
        e.ERR_FORBIDDEN_ROLE,
        403,
    )

    response = api.list_pick_sessions(u.make_picker_headers(picker["id"]))
    rows, meta = validate_paginated(response)
    a.assert_array_response(response)
    a.assert_page_meta(meta, expected_total=0)
    assert rows == []

    assert x.read_picker(api, picker["id"])["crew_id"] == crew["id"]
    assert x.read_crew(api, crew["id"])["picker_count"] == 1


def test_a_supervisor_of_another_crew_cannot_tally_this_crews_session(api):
    """
    The tally is guarded by an equality between the acting operator and the
    `supervisor_user_id` stored when the crew was recruited, so a supervisor of
    equal standing but of another crew moves nothing at all.

    PRD 2.7 rule 20: "(20) On a tally, `X-User-ID` equals the `supervisor_user_id` of the crew that owns the session's window, otherwise `ERR_NOT_SESSION_SUPERVISOR`."

    PRD 2.1: "It also compares a `CrewSupervisor` caller's `X-User-ID` against the `supervisor_user_id` value that was supplied when the crew was recruited; that field holds an opaque operator identifier, not the `id` of any row."

    Design: Corner/rbac/tally_by_a_supervisor_of_another_crew_returns_not_session_supervisor
    """
    block = _cleared_block(api, "BLK-V27")
    crew, pickers = x.certified_crew(
        api, picker_count=1, name="CREW-V27", supervisor_user_id=u.SUP_1
    )
    window = _window_over_the_third(api, block["id"], crew["id"])
    session = x.open_session(
        api, window["id"], pickers[0]["id"], supervisor_user_id=u.SUP_1,
        work_date="2026-08-03",
    )

    validate_error(
        api.tally_pick_session(
            session["id"],
            f.tally_payload(hours_worked=3.00, clamshells_filled=20, culled_clamshells=0),
            u.CREW_SUPERVISOR_2,
        ),
        e.ERR_NOT_SESSION_SUPERVISOR,
        403,
    )

    stored = x.read_session(api, session["id"])
    a.assert_status(stored, "status", "OPEN")
    a.assert_status(stored, "quality_flag", "PENDING")
    a.assert_unset(stored, "tallied_by_user_id", "session")

    a.assert_cents(
        x.read_crew(api, crew["id"])["accrued_wage_cents"], 0, "crew.accrued_wage_cents"
    )
    assert x.read_picker(api, pickers[0]["id"])["total_clamshells_lifetime"] == 0


def test_a_picker_may_dispute_only_the_session_that_carries_their_own_id(api):
    """
    Disputing is shared with the supervisor, but a `Picker` caller is confined to
    their own row: the crew-mate's refusal is an ownership failure rather than a
    role failure, and the owner's dispute preserves the money it reverses.

    PRD 2.7 rule 21: "(21) On a dispute raised with the `Picker` role, `X-User-ID` equals the session's `picker_id`, otherwise `ERR_NOT_SESSION_OWNER`."

    PRD 2.1: "When a `Picker` acts on a session whose `picker_id` is not their own identifier, the rejection is `ERR_NOT_SESSION_OWNER` (HTTP 403)."

    PRD 2.9: "When an approved session is pulled back out of the paid set, the crew's `accrued_wage_cents` is decremented by the *same stored* `net_cents` figure that was added when it was approved, so the ledger cannot drift by a rounding step."

    Design: Corner/rbac/picker_disputing_another_pickers_session_returns_not_session_owner
    """
    block = _cleared_block(api, "BLK-V28")
    crew, pickers = x.certified_crew(
        api, picker_count=2, name="CREW-V28", supervisor_user_id=u.SUP_1
    )
    owner, crew_mate = pickers[0], pickers[1]
    window = _window_over_the_third(api, block["id"], crew["id"])
    session = x.approved_session(
        api,
        window["id"],
        owner["id"],
        supervisor_user_id=u.SUP_1,
        approver_headers=u.PAYROLL_CLERK,
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
        culled_clamshells=0,
    )
    a.assert_cents(session["net_cents"], 4950, "session.net_cents")

    validate_error(
        api.dispute_pick_session(
            session["id"],
            f.dispute_payload(dispute_reason_code="PICKER_CONTESTS_COUNT"),
            u.make_picker_headers(crew_mate["id"]),
        ),
        e.ERR_NOT_SESSION_OWNER,
        403,
    )

    disputed = validate_success(
        api.dispute_pick_session(
            session["id"],
            f.dispute_payload(dispute_reason_code="PICKER_CONTESTS_COUNT"),
            u.make_picker_headers(owner["id"]),
        ),
        200,
    )
    a.assert_status(disputed, "status", "DISPUTED")
    assert disputed["dispute_reason_code"] == "PICKER_CONTESTS_COUNT"
    a.assert_cents(disputed["net_cents"], 4950, "session.net_cents")

    a.assert_cents(
        x.read_crew(api, crew["id"])["accrued_wage_cents"], 0, "crew.accrued_wage_cents"
    )
    assert x.read_picker(api, crew_mate["id"])["total_clamshells_lifetime"] == 0


def test_the_operator_who_tallied_a_session_may_not_approve_it(api):
    """
    The duty split compares operator identifiers, not roles: one person holding
    both the supervisor and the clerk capacity is still one person, and only a
    second clerk can move the money onto the crew ledger.

    PRD 2.10: "Three points in the season are governed by a duty split, and all three are enforced by comparing the acting `X-User-ID` against an operator identifier the system stored earlier. All three report `ERR_SEGREGATION_OF_DUTIES` with HTTP 409."

    PRD 3.4: "The approving `X-User-ID` must differ from `tallied_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. Approval stores `approved_by_user_id`, adds the session's `net_cents` to the crew's `accrued_wage_cents`, recomputes the picker's lifetime productivity, recomputes the window's `harvested_clamshells`, and increments the `version` of the session, the crew, the picker and the window each by 1."

    Design: Corner/rbac/same_user_cannot_tally_and_approve_the_same_session
    """
    block = _cleared_block(api, "BLK-V29")
    crew, pickers = x.certified_crew(
        api, picker_count=1, name="CREW-V29", supervisor_user_id=u.CLERK_1
    )
    window = _window_over_the_third(api, block["id"], crew["id"])
    session = x.tallied_session(
        api,
        window["id"],
        pickers[0]["id"],
        supervisor_user_id=u.CLERK_1,
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
        culled_clamshells=0,
    )
    assert session["tallied_by_user_id"] == u.CLERK_1

    validate_error(
        api.approve_pick_session(session["id"], u.PAYROLL_CLERK),
        e.ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    a.assert_status(x.read_session(api, session["id"]), "status", "TALLIED")
    a.assert_cents(
        x.read_crew(api, crew["id"])["accrued_wage_cents"], 0, "crew.accrued_wage_cents"
    )

    approved = validate_success(
        api.approve_pick_session(session["id"], u.PAYROLL_CLERK_2), 200
    )
    a.assert_status(approved, "status", "APPROVED")
    assert approved["approved_by_user_id"] == u.CLERK_2
    assert approved["tallied_by_user_id"] == u.CLERK_1
    a.assert_cents(approved["net_cents"], 4950, "session.net_cents")
    a.assert_cents(
        x.read_crew(api, crew["id"])["accrued_wage_cents"],
        4950,
        "crew.accrued_wage_cents",
    )


def test_the_clerk_who_locked_a_period_may_not_settle_it(api):
    """
    The same split guards the pay period: the locking clerk's settlement is
    refused with the run still `LOCKED` and no settled figure determined, while
    the second clerk's settlement pays the period average and reconciles the
    crew in one call.

    PRD 2.10: "The clerk who locks a pay period may not settle it: the settling `X-User-ID` must differ from the run's `locked_by_user_id`."

    PRD 3.5: "Settling moves a run `LOCKED → SETTLED` and must be performed by a different clerk: the settling `X-User-ID` must differ from `locked_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

    PRD 3.5: "Settling then moves every bound session `APPROVED → SETTLED`, incrementing each session's `version` by 1, and reconciles the crew: `accrued_wage_cents` is decremented by the sum of the bound sessions' `net_cents`, `settled_wage_cents` is incremented by the run's `settled_net_cents`, and `reconciliation_delta_cents` is incremented by the same signed delta the run recorded."

    Design: Corner/rbac/same_clerk_cannot_lock_and_settle_the_same_payroll_run
    """
    block = _cleared_block(api, "BLK-V30")
    crew, pickers = x.certified_crew(
        api, picker_count=1, name="CREW-V30", supervisor_user_id=u.SUP_1
    )
    window = _window_over_the_third(api, block["id"], crew["id"])
    session = x.approved_session(
        api,
        window["id"],
        pickers[0]["id"],
        supervisor_user_id=u.SUP_1,
        approver_headers=u.PAYROLL_CLERK_2,
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
        culled_clamshells=0,
    )
    run = x.locked_payroll_run(
        api,
        crew["id"],
        locker_headers=u.PAYROLL_CLERK,
        period_start_date="2026-08-03",
        period_end_date="2026-08-03",
    )
    assert run["locked_by_user_id"] == u.CLERK_1

    validate_error(
        api.settle_payroll_run(run["id"], u.PAYROLL_CLERK),
        e.ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    refused = x.read_payroll_run(api, run["id"])
    a.assert_status(refused, "status", "LOCKED")
    a.assert_unset(refused, "settled_net_cents", "run")
    a.assert_cents(
        x.read_crew(api, crew["id"])["settled_wage_cents"], 0, "crew.settled_wage_cents"
    )

    settled = validate_success(
        api.settle_payroll_run(run["id"], u.PAYROLL_CLERK_2), 200
    )
    a.assert_status(settled, "status", "SETTLED")
    assert settled["locked_by_user_id"] == u.CLERK_1
    assert settled["settled_by_user_id"] == u.CLERK_2
    assert settled["bound_session_count"] == 1
    a.assert_hours(settled["period_hours"], 3.00, "run.period_hours")
    a.assert_cents(settled["period_piece_cents"], 900, "run.period_piece_cents")
    a.assert_cents(settled["settled_gross_cents"], 4950, "run.settled_gross_cents")
    a.assert_cents(settled["settled_net_cents"], 4950, "run.settled_net_cents")
    a.assert_cents(
        settled["reconciliation_delta_cents"], 0, "run.reconciliation_delta_cents"
    )

    reconciled = x.read_crew(api, crew["id"])
    a.assert_cents(reconciled["accrued_wage_cents"], 0, "crew.accrued_wage_cents")
    a.assert_cents(reconciled["settled_wage_cents"], 4950, "crew.settled_wage_cents")
    a.assert_cents(
        reconciled["reconciliation_delta_cents"], 0, "crew.reconciliation_delta_cents"
    )

    stored_session = x.read_session(api, session["id"])
    a.assert_status(stored_session, "status", "SETTLED")
    assert stored_session["payroll_run_id"] == run["id"]


def test_the_officer_who_quarantined_a_block_may_not_clear_it(api):
    """
    The third split is why `quarantined_by_user_id` survives the clearance: the
    imposing officer's own attempt is refused with the hold still on the lot, and
    the second officer's clearance lifts it while the evidence of who imposed it
    remains on the block.

    PRD 2.10: "And the officer who quarantines a block may not be the one who lifts the hold: the clearing `X-User-ID` must differ from the block's `quarantined_by_user_id`. That last comparison is why `quarantined_by_user_id` is retained on the block after the hold is cleared rather than being emptied — it is the evidence the next quarantine-and-clear cycle is checked against."

    PRD 3.1: "Clearing sets `manual_quarantine_active` back to false, recomputes the posture to `CLEARED`, and sets `food_safety_hold` back to false on every lot of the block whose `disposition_status` is `UNCOMMITTED` or `RESERVED`."

    Design: Corner/rbac/quarantining_officer_cannot_clear_the_same_block
    """
    block = _cleared_block(api, "BLK-V31")
    crew = x.recruit_crew(api, name="CREW-V31")
    window = x.plan_window(
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
    lot = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=50,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T12:00:00Z",
        field_pulp_temp_f=62.0,
    )
    x.quarantine_block(
        api, block["id"], reason_code="ADJACENT_LIVESTOCK", headers=u.FOOD_SAFETY_OFFICER
    )
    assert x.read_lot(api, lot["id"])["food_safety_hold"] is True

    validate_error(
        api.clear_block(block["id"], u.FOOD_SAFETY_OFFICER),
        e.ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    still_held = x.read_block(api, block["id"])
    a.assert_status(still_held, "food_safety_posture", "QUARANTINED")
    assert still_held["manual_quarantine_active"] is True
    assert x.read_lot(api, lot["id"])["food_safety_hold"] is True

    cleared = validate_success(
        api.clear_block(block["id"], u.FOOD_SAFETY_OFFICER_2), 200
    )
    a.assert_status(cleared, "food_safety_posture", "CLEARED")
    assert cleared["manual_quarantine_active"] is False
    assert cleared["quarantined_by_user_id"] == u.FSO_1
    a.assert_status(cleared, "water_status", "PROVISIONAL")

    released_lot = x.read_lot(api, lot["id"])
    assert released_lot["food_safety_hold"] is False
    a.assert_status(released_lot, "disposition_status", "UNCOMMITTED")
