"""Cycles, self-loops, parallel axes and re-entry on the non-linear machines."""

from test_helpers import (
    ApiErrorId,
    MOVE_MANAGER,
    MOVE_START,
    api_client,
    advance_handling,
    assert_money,
    assert_same_instant,
    designate,
    drive_sort_plan_to_approved,
    freeze_and_start,
    get_success_data,
    markdown_price_cents,
    milestone_by_key,
    new_family_hold,
    new_item,
    new_portal_party,
    read_engagement,
    read_hold,
    read_item,
    read_lot,
    read_move_day_plan,
    read_sort_plan,
    set_clock,
    setup_consignment_lot,
    setup_engagement,
    setup_move_day_plan_confirmed,
    validate_error,
    validate_success,
    confirm_assignment,
    read_crew_assignment,
)

ADDENDUM_ROOM = {"approved_addendum_linear_inches": 36}
TWO_KEEP_ITEMS = [
    {"label": "Walnut sideboard", "footprint_linear_inches": 96, "volume_cft": 40},
    {"label": "Reading chair", "footprint_linear_inches": 90, "volume_cft": 35},
]


def _engagement_with_approved_sort_plan_and_two_keep_items():
    world = setup_engagement(with_residence=True, room_kwargs=ADDENDUM_ROOM)
    world["items"] = []
    for spec in TWO_KEEP_ITEMS:
        item = new_item(world["engagement_id"], **spec)
        designate(item["id"], "KEEP", world["room"]["id"])
        world["items"].append(item)
    world["sort_plan"] = drive_sort_plan_to_approved(
        world["engagement_id"], world["client_party"]["id"]
    )
    return world


def test_sort_plan_reopen_returns_to_draft_and_unlocks_every_disposition():
    """PRD §3.6: "That reopen raises `reopen_count` by one, sets
    `disposition_locked` back to false on every item of the engagement — restoring
    the reversible mesh in full — and moves the `SORT_PLAN` milestone from
    `COMPLETE` back to `REOPENED`, which pulls the engagement's `phase` back to
    `SORT_PLAN`."

    Design: Difficulty/non_linear_state_machine/sort_plan_reopen_cycle_unlocks_dispositions
    """
    world = _engagement_with_approved_sort_plan_and_two_keep_items()
    first, second = world["items"]

    assert read_item(first["id"])["disposition_locked"] is True
    assert read_engagement(world["engagement_id"])["phase"] == "PACK"

    validate_success(
        api_client.reopen_sort_plan(
            world["sort_plan"]["id"],
            {"reason": "Daughter wants the sideboard reconsidered"},
            MOVE_MANAGER,
        )
    )
    plan = read_sort_plan(world["sort_plan"]["id"])
    assert plan["status"] == "DRAFT"
    assert plan["reopen_count"] == 1
    assert read_item(first["id"])["disposition_locked"] is False
    assert read_item(second["id"])["disposition_locked"] is False


def test_sort_plan_reopen_drags_the_timeline_back_to_the_sort_plan_phase():
    """PRD §3.10: "`REOPENED` never rests: in the same request the milestone returns
    to `IN_PROGRESS`, recomputing `phase` again."
    PRD §3.10: "It raises `reopen_count` by one, clears `completed_at_utc` back to
    null, moves the lateness axis from `RECOVERED` back to `OVERDUE` (never to
    `ON_TIME`), and recomputes `phase` back to this milestone's key."

    Design: Difficulty/non_linear_state_machine/sort_plan_reopen_cycle_unlocks_dispositions
    """
    world = _engagement_with_approved_sort_plan_and_two_keep_items()

    validate_success(
        api_client.reopen_sort_plan(
            world["sort_plan"]["id"],
            {"reason": "Daughter wants the sideboard reconsidered"},
            MOVE_MANAGER,
        )
    )
    assert read_engagement(world["engagement_id"])["phase"] == "SORT_PLAN"
    milestone = milestone_by_key(world["engagement_id"], "SORT_PLAN")
    assert milestone["status"] == "IN_PROGRESS"
    assert milestone["reopen_count"] == 1
    assert milestone["completed_at_utc"] is None


def _lot_marked_down_once():
    world = setup_consignment_lot()
    get_success_data(api_client.mark_down_lot(world["lot"]["id"], MOVE_MANAGER))
    return world


def test_second_markdown_is_a_self_loop_taken_off_the_original_list_price():
    """PRD §3.8: "Markdowns run twice at most and are always taken off the
    **original** list price rather than compounded off the previous price. The first
    markdown moves `LISTED` to `MARKED_DOWN` and raises `markdown_round` to 1,
    setting `current_price_cents` to the `list_price_cents` less twenty percent,
    rounded half-up to whole cents. The second is a self-loop on `MARKED_DOWN` that
    raises `markdown_round` to 2 and sets `current_price_cents` to the
    `list_price_cents` less thirty-five percent, rounded the same way."

    Design: Difficulty/non_linear_state_machine/consignment_lot_markdown_self_loop_then_unsold
    """
    world = _lot_marked_down_once()
    assert_money(
        read_lot(world["lot"]["id"])["current_price_cents"],
        markdown_price_cents(240000, 1),
        "current_price_cents after one markdown",
    )

    validate_success(api_client.mark_down_lot(world["lot"]["id"], MOVE_MANAGER))
    lot = read_lot(world["lot"]["id"])
    assert lot["status"] == "MARKED_DOWN"
    assert lot["markdown_round"] == 2
    assert_money(
        lot["current_price_cents"],
        markdown_price_cents(240000, 2),
        "current_price_cents after two markdowns",
    )


def test_marked_down_lot_can_still_be_declared_unsold_keeping_its_markdown_state():
    """PRD §3.8: "Declaring a lot unsold is reachable from `LISTED` and from
    `MARKED_DOWN` and requires the logical clock's date to be at least thirty days
    after `listed_on`; an earlier attempt is refused with
    `ERR_UNSOLD_WINDOW_NOT_ELAPSED`. The move manager and the vendor may both declare."

    Design: Difficulty/non_linear_state_machine/consignment_lot_markdown_self_loop_then_unsold
    """
    world = _lot_marked_down_once()
    validate_success(api_client.mark_down_lot(world["lot"]["id"], MOVE_MANAGER))

    set_clock("2026-06-05T00:00:00.000Z")
    validate_success(api_client.declare_lot_unsold(world["lot"]["id"], MOVE_MANAGER))

    lot = read_lot(world["lot"]["id"])
    assert lot["status"] == "UNSOLD"
    assert lot["markdown_round"] == 2
    assert_money(
        lot["current_price_cents"],
        markdown_price_cents(240000, 2),
        "current_price_cents is untouched by the unsold declaration",
    )


def _packed_item_on_an_in_progress_plan():
    world = setup_move_day_plan_confirmed()
    world["family_party"] = new_portal_party(
        world["engagement_id"],
        "FAMILY_MEMBER",
        display_name="Marcus Whitfield",
        email="marcus@example.com",
    )
    item_id = world["items"][0]["id"]
    advance_handling(item_id, "PACKED")
    freeze_and_start(world)
    world["item_id"] = item_id
    return world


def test_handling_axis_advances_while_the_hold_and_disposition_axes_stay_pinned():
    """PRD §3.4: "Two independent state axes live on the same item, and this is
    deliberate. The **disposition** axis records what the family decided; the
    **handling** axis records where the object physically is."
    PRD §3.4: "`PACKED` to `LOADED` requires the move-day plan to be `IN_PROGRESS`.
    `LOADED` to `DELIVERED` requires the move-day plan to be `IN_PROGRESS` or
    `COMPLETED` and the item's `assigned_room_id` to be non-null."

    Design: Difficulty/non_linear_state_machine/item_handling_axis_advances_while_disposition_and_hold_axes_are_pinned
    """
    world = _packed_item_on_an_in_progress_plan()
    item_id = world["item_id"]

    before = read_item(item_id)
    assert before["handling_state"] == "PACKED"
    assert before["disposition_locked"] is True
    assert before["hold_state"] == "NONE"

    hold = new_family_hold(item_id, world["family_party"]["id"])
    assert read_hold(hold["id"])["status"] == "OPEN"
    assert read_item(item_id)["hold_state"] == "HELD"

    advance_handling(item_id, "LOADED")
    assert read_item(item_id)["handling_state"] == "LOADED"
    advance_handling(item_id, "DELIVERED")

    after = read_item(item_id)
    assert after["handling_state"] == "DELIVERED"
    assert after["disposition"] == "KEEP"
    assert after["disposition_locked"] is True
    assert after["hold_state"] == "HELD"
    assert after["redesignation_count"] == 0


def test_a_re_designation_on_a_move_day_engagement_is_refused_by_the_phase_gate():
    """PRD §2.7: "The engagement's `phase` permits the operation: cataloguing an item
    and designating one require phase `ASSESSMENT` or `SORT_PLAN`; move-day plan
    creation requires phase `PACK` or `MOVE_DAY`; unpack-session and punch-list
    creation require phase `SETTLE_IN` or `CLOSE_OUT`. Otherwise
    `ERR_PHASE_NOT_PERMITTED`, HTTP 409."
    PRD §2.6: "Every mutating endpoint — that is, every non-GET endpoint except
    `POST /_clock/set_current_utc`, `POST /clients`, `POST /crew-members` and
    `POST /vendors`, which have no engagement context — passes through twelve gates
    in this exact order, and the first gate that fails determines the returned
    `error_id`."

    Design: Difficulty/non_linear_state_machine/item_handling_axis_advances_while_disposition_and_hold_axes_are_pinned
    """
    world = _packed_item_on_an_in_progress_plan()
    item_id = world["item_id"]
    new_family_hold(item_id, world["family_party"]["id"])
    advance_handling(item_id, "LOADED")
    advance_handling(item_id, "DELIVERED")

    assert read_engagement(world["engagement_id"])["phase"] == "MOVE_DAY"
    response = api_client.designate_item(item_id, {"disposition": "DONATE"}, MOVE_MANAGER)
    validate_error(response, ApiErrorId.ERR_PHASE_NOT_PERMITTED.value)

    assert read_item(item_id)["disposition"] == "KEEP"
    assert read_sort_plan(world["sort_plan"]["id"])["status"] == "FROZEN"


def test_reschedule_sends_a_confirmed_plan_back_to_draft_with_a_new_freeze_boundary():
    """PRD §3.7: "It takes a `new_start_utc`, which must be strictly after the
    current logical clock, and a `reason`. It raises `reschedule_count` by one, sets
    `scheduled_start_utc` to the new instant and recomputes `freeze_at_utc` from it,
    and shifts every vendor assignment of the engagement in status `ACCEPTED`,
    `SCHEDULED` or `COI_BLOCKED` whose `service_date` equalled the pre-reschedule
    start date onto the new start date — which is precisely how a vendor's
    certificate of insurance can end up expiring before its own service date."
    PRD §3.7: "`RESCHEDULED` is never observable as a resting state; in the same
    request the plan returns to `DRAFT`, reverting every `CONFIRMED` assignment on
    it to `ASSIGNED`."

    Design: Difficulty/non_linear_state_machine/move_day_plan_re_enters_confirmed_with_a_recomputed_freeze_boundary
    """
    world = setup_move_day_plan_confirmed()
    plan_id = world["plan"]["id"]

    validate_success(
        api_client.reschedule_move_day_plan(
            plan_id,
            {
                "new_start_utc": "2026-06-22T14:00:00.000Z",
                "reason": "Destination handover slipped by a week",
            },
            MOVE_MANAGER,
        )
    )
    plan = read_move_day_plan(plan_id)
    assert plan["status"] == "DRAFT"
    assert plan["reschedule_count"] == 1
    assert plan["crew_confirmed_count"] == 0
    assert_same_instant(
        plan["scheduled_start_utc"], "2026-06-22T14:00:00.000Z", "scheduled_start_utc"
    )
    assert_same_instant(plan["freeze_at_utc"], "2026-06-19T14:00:00.000Z", "freeze_at_utc")

    confirm_assignment(world["lead_assignment"]["id"])
    assert read_move_day_plan(plan_id)["status"] == "DRAFT"
    confirm_assignment(world["packer_assignment"]["id"])
    plan = read_move_day_plan(plan_id)
    assert plan["status"] == "CREWED"
    assert plan["crew_confirmed_count"] == 2
    validate_success(api_client.confirm_move_day_plan(plan_id, MOVE_MANAGER))
    assert read_move_day_plan(plan_id)["status"] == "CONFIRMED"


def test_the_original_freeze_instant_no_longer_freezes_the_re_entered_plan():
    """PRD §2.7: "Freezing the move-day plan requires the logical clock to be at or
    after `freeze_at_utc`; the boundary instant itself is inside the window.
    Otherwise `ERR_FREEZE_WINDOW_NOT_ENTERED`, HTTP 409."
    PRD §3.7: "Freezing is the move manager's declaration that the plan is final. It
    is permitted from `CONFIRMED` only once the clock is at or after `freeze_at_utc`
    — attempting it earlier is refused with `ERR_FREEZE_WINDOW_NOT_ENTERED` — and it
    cascades twice: the engagement's sort plan moves from `APPROVED` to `FROZEN`,
    and the `PACK` milestone moves from `IN_PROGRESS` to `COMPLETE`, starting the
    `MOVE_DAY` milestone."

    Design: Difficulty/non_linear_state_machine/move_day_plan_re_enters_confirmed_with_a_recomputed_freeze_boundary
    """
    world = setup_move_day_plan_confirmed()
    plan_id = world["plan"]["id"]
    validate_success(
        api_client.reschedule_move_day_plan(
            plan_id,
            {
                "new_start_utc": "2026-06-22T14:00:00.000Z",
                "reason": "Destination handover slipped by a week",
            },
            MOVE_MANAGER,
        )
    )
    confirm_assignment(world["lead_assignment"]["id"])
    confirm_assignment(world["packer_assignment"]["id"])
    validate_success(api_client.confirm_move_day_plan(plan_id, MOVE_MANAGER))

    set_clock("2026-06-12T14:00:00.000Z")
    validate_error(
        api_client.freeze_move_day_plan(plan_id, MOVE_MANAGER),
        ApiErrorId.ERR_FREEZE_WINDOW_NOT_ENTERED.value,
    )

    set_clock("2026-06-19T14:00:00.000Z")
    validate_success(api_client.freeze_move_day_plan(plan_id, MOVE_MANAGER))

    plan = read_move_day_plan(plan_id)
    assert plan["status"] == "FROZEN"
    assert plan["reschedule_count"] == 1
    assert read_sort_plan(world["sort_plan"]["id"])["status"] == "FROZEN"
    assert read_crew_assignment(world["lead_assignment"]["id"])["status"] == "CONFIRMED"
    assert read_crew_assignment(world["packer_assignment"]["id"])["status"] == "CONFIRMED"
