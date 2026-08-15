"""Placement gating on barn state and the wash/downtime/service cycle."""
from test_helpers import (
    ApiErrorId,
    assert_barn,
    assert_barn_wash,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    FIELDTECH,
    create_barn,
    create_scheduled_group,
    create_ticket,
    get_barn,
    get_settlement_for_group,
    record_barn_wash,
    set_clock,
    setup_placed_group,
    wash_barn_to_downtime,
)


class TestConfirmRequiresBarnAvailable:
    def test_confirm_blocked_until_barn_cycles_back_to_available(self, api):
        """PRD §3.2: "Confirmation requires the barn to be `AVAILABLE`
        (`ERR_BARN_NOT_PLACEABLE` otherwise), the clock date to have reached
        the `placement_date` (confirming early fails with
        `ERR_CONFIRM_TOO_EARLY`), and the governing contract to be `ACTIVE`
        (`ERR_CONTRACT_NOT_ACTIVE`)."
        PRD §3.6: "The close flips the barn `OCCUPIED` → `WASH_REQUIRED`,
        clears `current_group_id` back to null, sets the barn's `wash_required`
        flag, and advances the barn's `version`."

        Confirm fails while the barn is OCCUPIED, again while WASH_REQUIRED,
        again while DOWNTIME, and succeeds only after release.

        Design: Difficulty/cross_entity_state_dependency/placement_confirm_requires_barn_available
        """
        ctx = setup_placed_group(head_placed=500)
        barn_id = ctx["barn"]["id"]
        contract_id = ctx["contract"]["id"]
        group_a = ctx["group"]

        # Adjacent group: [2026-07-13, 2026-08-24) touches A's stay legally.
        group_b = create_scheduled_group(
            barn_id, contract_id,
            placement_date="2026-07-13", target_market_date="2026-08-24",
            head_placed=500,
        )

        # 1) Barn OCCUPIED (group A on the ground) — confirm refused.
        set_clock("2026-07-13T00:00:00Z")
        res = api.confirm_placement(group_b["id"], {}, FIELDTECH)
        validate_error(res, ApiErrorId.ERR_BARN_NOT_PLACEABLE, expected_status=409)

        # 2) Barn WASH_REQUIRED after A's force close-out — still refused.
        get_success_data(api.close_out_pig_group(group_a["id"], FIELDTECH))
        res = api.confirm_placement(group_b["id"], {}, FIELDTECH)
        validate_error(res, ApiErrorId.ERR_BARN_NOT_PLACEABLE, expected_status=409)

        # 3) Barn DOWNTIME (wash verified, 72h not yet elapsed) — refused.
        wash_barn_to_downtime(
            barn_id, ctx["grower"]["id"], "2026-07-13T10:00:00Z",
            clock="2026-07-13T12:00:00Z",
        )
        assert get_barn(barn_id)["barn_status"] == "DOWNTIME"
        res = api.confirm_placement(group_b["id"], {}, FIELDTECH)
        validate_error(res, ApiErrorId.ERR_BARN_NOT_PLACEABLE, expected_status=409)

        # Release once the downtime has elapsed; the confirm then succeeds.
        set_clock("2026-07-17T00:00:00Z")
        released = validate_success(api.release_barn(barn_id, ADMIN), 200)
        assert released["barn_status"] == "AVAILABLE"
        placed = validate_success(api.confirm_placement(group_b["id"], {}, FIELDTECH), 200)
        assert placed["group_status"] == "PLACED"
        barn = get_barn(barn_id)
        assert barn["barn_status"] == "OCCUPIED"
        assert barn["current_group_id"] == group_b["id"]

    def test_force_closeout_marks_unaccounted_and_zeroes_bonus(self, api):
        """PRD §3.8: "The force path is a deliberate close-out by a `FieldTech`
        while the group is `PLACED` or `MARKETING`, used when remaining pigs
        cannot be marketed; force closing copies the remaining `head_current`
        into `head_unaccounted` and zeroes `head_current`, whereas a natural
        close leaves `head_unaccounted` at its default of zero."
        PRD §3.8: "If `head_unaccounted` is greater than zero — a force
        close-out left pigs unaccounted — the `bonus_cents` is zero."
        PRD §3.6: "The close flips the barn `OCCUPIED` → `WASH_REQUIRED`,
        clears `current_group_id` back to null, sets the barn's `wash_required`
        flag, and advances the barn's `version`."

        Design: Difficulty/cross_entity_state_dependency/placement_confirm_requires_barn_available
        """
        ctx = setup_placed_group(head_placed=500)
        group_id = ctx["group"]["id"]

        closed = validate_success(api.close_out_pig_group(group_id, FIELDTECH), 200)
        assert closed["group_status"] == "CLOSED"
        assert closed["head_unaccounted"] == 500
        assert closed["head_current"] == 0
        assert closed["closed_at"] is not None

        barn = get_barn(ctx["barn"]["id"])
        assert barn["barn_status"] == "WASH_REQUIRED"
        assert barn["wash_required"] is True
        assert barn["current_group_id"] is None

        settlement = get_settlement_for_group(group_id)
        assert settlement["settlement_status"] == "FINALIZED"
        assert settlement["head_marketed"] == 0
        assert settlement["base_pay_cents"] == 500 * 4000
        assert settlement["bonus_cents"] == 0
        assert settlement["total_pay_cents"] == 2000000


class TestBarnWashLoop:
    def test_barn_wash_reject_reverts_to_wash_required(self, api):
        """PRD §3.6: "Rejection instead moves the wash `RECORDED` → `REJECTED`
        and sends the barn `WASHING` → `WASH_REQUIRED`, again incrementing its
        `version`, so the barn simply awaits a proper wash."
        PRD §3.6: "Recording is accepted only while the barn is in
        `WASH_REQUIRED`; the attempt against a barn in any other status fails
        with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/barn_wash_reject_reverts_to_wash_required
        """
        ctx = setup_placed_group(head_placed=100)
        barn_id = ctx["barn"]["id"]
        grower_id = ctx["grower"]["id"]
        get_success_data(api.close_out_pig_group(ctx["group"]["id"], FIELDTECH))
        assert get_barn(barn_id)["barn_status"] == "WASH_REQUIRED"

        wash1 = record_barn_wash(
            barn_id, grower_id, "2026-03-02T12:00:00Z",
            clock="2026-03-02T12:00:00Z",
        )
        assert_barn_wash(wash1)
        assert wash1["wash_status"] == "RECORDED"
        assert get_barn(barn_id)["barn_status"] == "WASHING"

        rejected = validate_success(api.reject_barn_wash(wash1["id"], ADMIN), 200)
        assert rejected["wash_status"] == "REJECTED"
        assert get_barn(barn_id)["barn_status"] == "WASH_REQUIRED"

        # The re-wash loop works: a fresh wash is accepted again.
        wash2 = record_barn_wash(
            barn_id, grower_id, "2026-03-03T09:00:00Z",
            clock="2026-03-03T09:00:00Z",
        )
        assert wash2["wash_status"] == "RECORDED"
        assert get_barn(barn_id)["barn_status"] == "WASHING"

    def test_barn_release_during_downtime_rejected(self, api):
        """PRD §3.6: "A barn in `DOWNTIME` rests until its downtime elapses: an
        `IntegratorAdmin` releases it, moving `DOWNTIME` → `AVAILABLE`, only
        once the clock has reached `downtime_until` — releasing early fails
        with `ERR_BARN_DOWNTIME_ACTIVE`."
        PRD §3.6: "moves the barn `WASHING` → `DOWNTIME`, setting
        `downtime_until` to the wash's `completed_at` plus seventy-two hours".
        PRD §2.4: "Where a rule says "on or after" or "at most", the boundary
        is inclusive".

        Design: Corner/errors/barn_release_during_downtime_rejected
        """
        ctx = setup_placed_group(head_placed=100)
        barn_id = ctx["barn"]["id"]
        grower_id = ctx["grower"]["id"]
        set_clock("2026-07-13T10:00:00Z")
        get_success_data(api.close_out_pig_group(ctx["group"]["id"], FIELDTECH))
        wash_barn_to_downtime(barn_id, grower_id, "2026-07-13T10:00:00Z")

        barn = get_barn(barn_id)
        assert barn["barn_status"] == "DOWNTIME"
        # completed 2026-07-13T10:00 + 72h -> downtime_until 2026-07-16T10:00.
        assert barn["downtime_until"].startswith("2026-07-16T10:00")

        set_clock("2026-07-15T00:00:00Z")
        res = api.release_barn(barn_id, ADMIN)
        validate_error(res, ApiErrorId.ERR_BARN_DOWNTIME_ACTIVE, expected_status=409)
        assert get_barn(barn_id)["barn_status"] == "DOWNTIME"

        set_clock("2026-07-16T10:00:00Z")
        released = validate_success(api.release_barn(barn_id, ADMIN), 200)
        assert released["barn_status"] == "AVAILABLE"
        assert released["wash_required"] is False
        assert released["downtime_until"] is None


class TestServiceStatusGuards:
    def test_return_to_service_blocked_and_mark_oos_occupied_rejected(self, api):
        """PRD §3.6: "Returning a barn to service is permitted only while no
        maintenance ticket for that barn remains `OPEN`, `QUOTED`, `APPROVED`,
        or `IN_PROGRESS` (`ERR_TICKETS_OPEN`)".
        PRD §3.6: "An `IntegratorAdmin` may mark a barn out of service from
        `AVAILABLE`, `WASH_REQUIRED`, `WASHING`, or `DOWNTIME`, moving it to
        `OUT_OF_SERVICE`; a barn that is `OCCUPIED` cannot be taken out of
        service (`ERR_BARN_OCCUPIED`)."

        Design: Corner/errors/return_to_service_blocked_and_mark_oos_occupied_rejected
        """
        ctx = setup_placed_group(head_placed=500, barn_code="B2")
        barn_occupied = ctx["barn"]  # OCCUPIED via the placed group
        barn3 = create_barn(
            ctx["site"]["id"], barn_code="B3",
            capacity_head=800, floor_space_sqft=6400,
        )
        get_success_data(api.mark_barn_out_of_service(barn3["id"], ADMIN))
        ticket = create_ticket(barn3["id"], ctx["grower"]["id"],
                               category="STRUCTURAL", description="slat crack")
        assert ticket["ticket_status"] == "OPEN"

        res = api.return_barn_to_service(barn3["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_TICKETS_OPEN, expected_status=409)
        assert get_barn(barn3["id"])["barn_status"] == "OUT_OF_SERVICE"

        res = api.mark_barn_out_of_service(barn_occupied["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_BARN_OCCUPIED, expected_status=409)
        barn = get_barn(barn_occupied["id"])
        assert_barn(barn)
        assert barn["barn_status"] == "OCCUPIED"
