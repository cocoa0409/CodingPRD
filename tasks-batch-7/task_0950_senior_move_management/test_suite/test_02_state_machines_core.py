"""Cycles, cascades, terminal lockdowns and precondition enforcement across the
engagement, placement, hold, sort-plan, crew, vendor, timeline and unpack machines."""

from test_helpers import (
    ApiErrorId,
    BILLING_ADMIN,
    MAX_HOLD_ESCALATIONS,
    MOVE_MANAGER,
    MOVE_START,
    PLATFORM_ADMIN,
    api_client,
    accept_vendor_assignment,
    assert_money,
    assert_same_instant,
    assert_two_dp,
    assert_vendor_payout_conservation,
    assign_crew,
    complete_milestone,
    complete_unpack_session,
    confirm_assignment,
    designate,
    drive_sort_plan_to_approved,
    get_success_data,
    make_family_member_headers,
    make_vendor_headers,
    milestone_by_key,
    new_active_authority,
    new_authority_record,
    new_crew_member,
    new_family_hold,
    new_item,
    new_move_day_plan,
    new_portal_party,
    new_punch_item,
    new_room,
    new_sort_plan,
    new_unpack_session,
    new_vendor,
    new_vendor_assignment,
    no_show,
    read_authority,
    read_crew_assignment,
    read_crew_member,
    read_engagement,
    read_hold,
    read_item,
    read_milestone,
    read_move_day_plan,
    read_party,
    read_punch_item,
    read_residence,
    read_room,
    read_sort_plan,
    read_unpack_session,
    read_vendor_assignment,
    resolve_punch_item,
    room_effective_capacity,
    schedule_vendor_assignment,
    set_clock,
    setup_engagement,
    setup_settle_in,
    start_unpack_session,
    submit_sort_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_hold_and_resume_cycle_restores_active_and_counts_every_pause():
    """PRD §3.1: "Placing it `ON_HOLD` requires a `reason`, which is stored as
    `hold_reason`; `hold_count` rises by one and never falls, recording how often the
    engagement has been paused, and `version` rises by one. Resuming clears
    `hold_reason` back to null and raises `version` by one. The cycle between
    `ACTIVE` and `ON_HOLD` is unbounded."

    Design: Corner/state_machines/engagement_hold_resume_cycle_restores_active_and_counts_holds
    """
    world = setup_engagement(with_client_party=False)
    eng_id = world["engagement_id"]

    held = validate_success(
        api_client.hold_engagement(eng_id, {"reason": "Family conference pending"}, MOVE_MANAGER)
    )
    assert held["status"] == "ON_HOLD"
    assert held["hold_reason"] == "Family conference pending"

    resumed = validate_success(api_client.resume_engagement(eng_id, MOVE_MANAGER))
    assert resumed["status"] == "ACTIVE"
    assert resumed["hold_reason"] is None

    validate_success(
        api_client.hold_engagement(eng_id, {"reason": "Closing date slipped"}, MOVE_MANAGER)
    )
    validate_success(api_client.resume_engagement(eng_id, MOVE_MANAGER))
    final = read_engagement(eng_id)
    assert final["status"] == "ACTIVE"
    assert final["hold_count"] == 2


def test_resuming_an_active_engagement_is_an_invalid_transition():
    """PRD §2.7: "The subject entity's current state is in the triggered
    transition's declared originating set. Otherwise `ERR_INVALID_STATE`, HTTP 409.
    Applies to every action endpoint that drives a state machine."
    PRD §3.1: "The engagement's `status` is its lifecycle axis and starts at `ACTIVE`."

    Design: Corner/state_machines/engagement_resume_from_active_is_rejected_invalid_state
    """
    world = setup_engagement(with_client_party=False)
    validate_error(
        api_client.resume_engagement(world["engagement_id"], MOVE_MANAGER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    engagement = read_engagement(world["engagement_id"])
    assert engagement["status"] == "ACTIVE"
    assert engagement["hold_count"] == 0


def test_a_cancelled_engagement_locks_every_child_write():
    """PRD §2.7: "The owning engagement's `status` is not `CANCELLED`. Otherwise
    `ERR_ENGAGEMENT_CANCELLED`, HTTP 409. Applies to every mutating endpoint under
    an engagement."
    PRD §3.1: "`CLOSED` and `CANCELLED` are both terminal."

    Design: Corner/state_machines/cancelled_engagement_blocks_every_child_mutation
    """
    world = setup_engagement(with_client_party=False)
    eng_id = world["engagement_id"]
    validate_success(
        api_client.cancel_engagement(eng_id, {"reason": "Client entered hospital"}, MOVE_MANAGER)
    )

    validate_error(
        api_client.create_inventory_item(
            {
                "engagement_id": eng_id,
                "label": "Walnut sideboard",
                "category": "FURNITURE",
                "footprint_linear_inches": 96,
                "volume_cft": 40,
            },
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_ENGAGEMENT_CANCELLED.value,
    )
    # PRD §2.7 rung 23 sits in gate 3 and fires ahead of the gate-10 state rungs, and
    # rung 24 exempts cancel only from the ON_HOLD rung, never from the CANCELLED one,
    # so a second cancel reports ERR_ENGAGEMENT_CANCELLED.
    validate_error(
        api_client.cancel_engagement(eng_id, {"reason": "duplicate"}, MOVE_MANAGER),
        ApiErrorId.ERR_ENGAGEMENT_CANCELLED.value,
    )
    engagement = read_engagement(eng_id)
    assert engagement["status"] == "CANCELLED"
    assert engagement["cancel_reason"] == "Client entered hospital"
    assert engagement["inventory_item_count"] == 0


def test_cancelling_the_engagement_cancels_its_open_vendor_orders():
    """PRD §3.1: "It records `cancel_reason` and runs the same cascade in both
    cases: every vendor assignment of the engagement in status `REQUESTED`,
    `ACCEPTED`, `SCHEDULED` or `COI_BLOCKED` moves to `CANCELLED`, and every unpack
    session still `SCHEDULED` moves to `COMPLETED` with its `items_unpacked_count`
    unchanged."

    Design: Corner/state_machines/engagement_cancel_cascades_open_vendor_assignments_to_cancelled
    """
    world = setup_engagement(with_client_party=False)
    eng_id = world["engagement_id"]
    vendor = new_vendor(
        "Bright Path Cleaning", "CLEANING", "2027-01-31", daily_capacity=2, holdback_pct=0.1
    )
    scheduled = new_vendor_assignment(eng_id, vendor["id"], "CLEANING", "2026-06-16", 85000)
    requested = new_vendor_assignment(eng_id, vendor["id"], "CLEANING", "2026-06-16", 60000)
    accept_vendor_assignment(scheduled["id"], vendor["id"])
    schedule_vendor_assignment(scheduled["id"])

    validate_success(
        api_client.cancel_engagement(eng_id, {"reason": "Client entered hospital"}, MOVE_MANAGER)
    )
    assert read_vendor_assignment(scheduled["id"])["status"] == "CANCELLED"
    assert read_vendor_assignment(requested["id"])["status"] == "CANCELLED"
    assert read_engagement(eng_id)["status"] == "CANCELLED"


def test_revising_an_approved_placement_bumps_the_revision_and_leaves_headroom_negative():
    """PRD §3.3: "From `APPROVED` it returns the plan to `DRAFT` only when no item
    assigned to a room of this residence has reached `DELIVERED` or `UNPACKED`; it
    raises `placement_revision` by one, clears both `approved_by_party_id` and
    `approved_at_utc` to null, and drops every child room's
    `effective_capacity_linear_inches` back to the provisional variant, which
    excludes the addendum."
    PRD §3.3: "Headroom is explicitly permitted to persist negative."

    Design: Corner/state_machines/placement_revise_from_approved_increments_revision_and_shrinks_capacity
    """
    world = setup_engagement(
        with_residence=True, room_kwargs={"approved_addendum_linear_inches": 36}
    )
    eng_id, room_id = world["engagement_id"], world["room"]["id"]
    first = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40)
    second = new_item(eng_id, label="Reading chair", footprint_linear_inches=90, volume_cft=35)
    third = new_item(eng_id, label="China cabinet", footprint_linear_inches=84, volume_cft=30)
    designate(first["id"], "KEEP", room_id)
    designate(second["id"], "KEEP", room_id)
    get_success_data(api_client.propose_placement(world["residence"]["id"], MOVE_MANAGER))
    get_success_data(
        api_client.approve_placement(
            world["residence"]["id"],
            {"approved_by_party_id": world["client_party"]["id"]},
            MOVE_MANAGER,
        )
    )
    designate(third["id"], "KEEP", room_id)

    before = read_room(room_id)
    assert_two_dp(before["keep_load_linear_inches"], 270.00, "keep_load before revision")
    assert_two_dp(before["headroom_linear_inches"], 6.00, "headroom before revision")

    validate_success(
        api_client.revise_placement(
            world["residence"]["id"],
            {"reason": "Building changed the unit allocation"},
            MOVE_MANAGER,
        )
    )
    residence = read_residence(world["residence"]["id"])
    assert residence["placement_status"] == "DRAFT"
    assert residence["placement_revision"] == 2
    assert residence["approved_by_party_id"] is None
    assert residence["approved_at_utc"] is None

    room = read_room(room_id)
    assert_two_dp(
        room["effective_capacity_linear_inches"],
        room_effective_capacity(240, 36, approved=False),
        "effective_capacity_linear_inches",
    )
    assert_two_dp(room["headroom_linear_inches"], -78.00, "headroom_linear_inches")
    assert read_item(third["id"])["disposition"] == "KEEP"


def test_moving_a_keep_item_between_rooms_rebalances_both_loads():
    """PRD §3.4: "Moving an item from one room to another while it stays `KEEP` is a
    real transition, not a no-op: it recomputes both the vacated and the target
    room's load and headroom and raises `redesignation_count` by one."
    PRD §3.3: "Items assigned to the room whose disposition is anything other than
    `KEEP` — `DONATE`, `SELL`, `HAUL_AWAY` or `UNDECIDED` — contribute nothing to
    either load, but they still count in `assigned_item_count`, which tallies every
    item pointing at the room whatever its disposition."

    Design: Corner/state_machines/keep_to_keep_room_move_is_a_self_loop_that_rebalances_both_rooms
    """
    world = setup_engagement(with_client_party=False, with_residence=True)
    room_a = world["room"]["id"]
    room_b = new_room(
        world["residence"]["id"], room_type="BEDROOM", nominal_linear_inches=200, nominal_volume_cft=300
    )["id"]
    item = new_item(
        world["engagement_id"], label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40
    )
    designate(item["id"], "KEEP", room_a)

    validate_success(
        api_client.designate_item(
            item["id"], {"disposition": "KEEP", "assigned_room_id": room_b}, MOVE_MANAGER
        )
    )
    moved = read_item(item["id"])
    assert moved["assigned_room_id"] == room_b
    assert moved["redesignation_count"] == 1

    vacated, target = read_room(room_a), read_room(room_b)
    assert_two_dp(vacated["keep_load_linear_inches"], 0.00, "vacated keep_load")
    assert_two_dp(vacated["headroom_linear_inches"], 192.00, "vacated headroom")
    assert_two_dp(target["keep_load_linear_inches"], 96.00, "target keep_load")
    assert_two_dp(target["headroom_linear_inches"], 64.00, "target headroom")
    assert vacated["assigned_item_count"] == 0
    assert target["assigned_item_count"] == 1


def test_escalate_and_remand_alternate_until_the_escalation_cap_bites():
    """PRD §3.5: "Escalation moves an `OPEN` hold to `ESCALATED`, takes a `note`,
    raises `escalation_count` by one, and leaves the item `HELD`; the move manager
    and a family member may escalate. Remand sends an `ESCALATED` hold back to
    `OPEN`, takes a `note`, raises `remand_count` by one, and is reserved to the move
    manager. The two counters are capped independently at two apiece, so the
    escalate-and-remand cycle can run at most twice in each direction before
    `ERR_HOLD_ESCALATION_LIMIT` shuts it down."

    Design: Corner/state_machines/family_hold_escalate_remand_cycle_respects_its_cap
    """
    world = setup_engagement(with_client_party=False, with_family_party=True)
    item = new_item(
        world["engagement_id"], label="China cabinet", footprint_linear_inches=84, volume_cft=30
    )
    hold = new_family_hold(item["id"], world["family_party"]["id"], reason="Promised to me")

    validate_success(api_client.escalate_family_hold(hold["id"], {"note": "First escalation"}, MOVE_MANAGER))
    validate_success(api_client.remand_family_hold(hold["id"], {"note": "Back to the family"}, MOVE_MANAGER))
    mid = read_hold(hold["id"])
    assert mid["status"] == "OPEN"
    assert mid["escalation_count"] == 1
    assert mid["remand_count"] == 1

    validate_success(api_client.escalate_family_hold(hold["id"], {"note": "Second escalation"}, MOVE_MANAGER))
    validate_success(api_client.remand_family_hold(hold["id"], {"note": "Back again"}, MOVE_MANAGER))
    validate_error(
        api_client.escalate_family_hold(hold["id"], {"note": "Third escalation"}, MOVE_MANAGER),
        ApiErrorId.ERR_HOLD_ESCALATION_LIMIT.value,
    )
    final = read_hold(hold["id"])
    assert final["status"] == "OPEN"
    assert final["escalation_count"] == MAX_HOLD_ESCALATIONS
    assert final["remand_count"] == 2
    assert read_item(item["id"])["hold_state"] == "HELD"


def test_resolving_a_hold_in_favour_of_the_family_forces_the_item_to_keep():
    """PRD §3.5: "Resolving in favour of the family — the `KEEP` resolution — is
    reachable from either `OPEN` or `ESCALATED`; it stamps `resolved_by_party_id` and
    `resolution_note`, forces the item's disposition to `KEEP` while leaving its
    `assigned_room_id` exactly as it was, and recomputes the item's `hold_state` to
    `NONE` when no other hold on that item remains `OPEN` or `ESCALATED`."

    Design: Corner/state_machines/family_hold_resolve_keep_forces_disposition_and_clears_hold_state
    """
    world = setup_engagement(with_family_party=True)
    item = new_item(
        world["engagement_id"],
        label="China cabinet",
        footprint_linear_inches=84,
        volume_cft=30,
        appraised_value_cents=40000,
        appraisal_source="APPRAISED",
    )
    hold = new_family_hold(item["id"], world["family_party"]["id"], reason="Promised to me")

    validate_success(
        api_client.resolve_family_hold(
            hold["id"],
            {"resolution": "KEEP", "resolved_by_party_id": world["client_party"]["id"]},
            MOVE_MANAGER,
        )
    )
    resolved = read_hold(hold["id"])
    assert resolved["status"] == "RESOLVED_KEEP"
    assert resolved["resolved_by_party_id"] == world["client_party"]["id"]

    subject = read_item(item["id"])
    assert subject["disposition"] == "KEEP"
    assert subject["hold_state"] == "NONE"


def test_only_the_raising_family_member_may_withdraw_its_own_hold():
    """PRD §3.5: "Withdrawal is the raiser's own exit, available only from `OPEN`,
    open to the move manager and to a family member, and when the actor is a family
    member the `X-User-ID` must equal the hold's `raised_by_party_id`; it recomputes
    `hold_state` to `NONE` when no other hold on the item remains `OPEN` or `ESCALATED`."
    PRD §2.1: "An entity-backed actor whose `X-User-ID` does not match the resource
    it claims to own is rejected with `ERR_ACTOR_NOT_OWNER` (HTTP 403)."

    Design: Corner/state_machines/family_hold_withdraw_by_non_raiser_family_member_is_rejected
    """
    world = setup_engagement(with_client_party=False, with_family_party=True)
    other = new_portal_party(
        world["engagement_id"], "FAMILY_MEMBER", display_name="Lena Whitfield", email="lena@example.com"
    )
    item = new_item(
        world["engagement_id"], label="China cabinet", footprint_linear_inches=84, volume_cft=30
    )
    raiser = world["family_party"]["id"]
    hold = new_family_hold(
        item["id"], raiser, headers=make_family_member_headers(raiser), reason="Promised to me"
    )

    validate_error(
        api_client.withdraw_family_hold(hold["id"], make_family_member_headers(other["id"])),
        ApiErrorId.ERR_ACTOR_NOT_OWNER.value,
    )
    assert read_hold(hold["id"])["status"] == "OPEN"
    assert read_item(item["id"])["hold_state"] == "HELD"


def test_the_reject_and_reopen_cycle_shares_the_single_reopen_budget():
    """PRD §3.6: "Rejection is the other outlet from `SUBMITTED`. It takes a
    non-empty `reason`, which is stored as `rejected_reason`, and is open to the same
    three roles as approval. From `REJECTED` the move manager may reopen the plan
    back to `DRAFT`: this raises `reopen_count` by one and clears `rejected_reason`
    to null, closing the first cycle."
    PRD §3.6: "Both reopen legs take a `reason` and both are capped at two reopens;
    the third attempt is refused with `ERR_SORT_PLAN_REOPEN_LIMIT`."

    Design: Corner/state_machines/sort_plan_reject_then_reopen_cycle_and_its_cap
    """
    world = setup_engagement()
    eng_id = world["engagement_id"]
    item = new_item(eng_id, label="Old linens", category="LINENS", footprint_linear_inches=10, volume_cft=5)
    designate(item["id"], "DONATE")
    plan = new_sort_plan(eng_id)

    for reason in ("Donate list is wrong", "Still wrong"):
        submit_sort_plan(plan["id"])
        get_success_data(api_client.reject_sort_plan(plan["id"], {"reason": reason}, MOVE_MANAGER))
        get_success_data(api_client.reopen_sort_plan(plan["id"], {"reason": "Rework"}, MOVE_MANAGER))
    submit_sort_plan(plan["id"])
    get_success_data(api_client.reject_sort_plan(plan["id"], {"reason": "Third time"}, MOVE_MANAGER))

    validate_error(
        api_client.reopen_sort_plan(plan["id"], {"reason": "Rework a third time"}, MOVE_MANAGER),
        ApiErrorId.ERR_SORT_PLAN_REOPEN_LIMIT.value,
    )
    final = read_sort_plan(plan["id"])
    assert final["status"] == "REJECTED"
    assert final["reopen_count"] == 2
    assert final["rejected_reason"] == "Third time"


def test_a_no_show_slot_is_superseded_by_the_replacement_assignment():
    """PRD §3.7: "Staffing the plan creates a crew assignment naming the
    `move_day_plan_id`, the `crew_member_id` and `expected_move_day_plan_version`,
    and optionally a `replaces_assignment_id` pointing at the `NO_SHOW` slot it
    fills. Creating one raises the plan's `version` by one, transitions the replaced
    assignment from `NO_SHOW` to `REPLACED`, and raises the crew member's
    `assignment_count`."
    PRD §3.7: "A member who never turns up is marked with a `note` stored as
    `no_show_note`; that is reachable from `ASSIGNED` and from `CONFIRMED`, and from
    `CONFIRMED` it recomputes `crew_confirmed_count` downward, which may drop the
    plan below its crew minimum."

    Design: Corner/state_machines/crew_no_show_then_replacement_joins_the_fork
    """
    world = setup_engagement()
    eng_id = world["engagement_id"]
    item = new_item(eng_id, label="Old linens", category="LINENS", footprint_linear_inches=10, volume_cft=5)
    designate(item["id"], "DONATE")
    drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])

    plan = new_move_day_plan(eng_id)
    lead = new_crew_member("Tom Reyes", "LEAD", 9500)
    packer = new_crew_member("Nina Ortiz", "PACKER", 6800)
    spare = new_crew_member("Jo Alvarez", "PACKER", 6800)
    lead_assignment = assign_crew(plan["id"], lead["id"])
    packer_assignment = assign_crew(plan["id"], packer["id"])
    confirm_assignment(lead_assignment["id"])
    confirm_assignment(packer_assignment["id"])

    no_show(packer_assignment["id"], "Called in sick")
    assert read_crew_assignment(packer_assignment["id"])["status"] == "NO_SHOW"
    assert read_move_day_plan(plan["id"])["crew_confirmed_count"] == 1

    replacement = assign_crew(plan["id"], spare["id"], replaces_assignment_id=packer_assignment["id"])
    replaced = read_crew_assignment(packer_assignment["id"])
    assert replaced["status"] == "REPLACED"
    assert replaced["no_show_note"] == "Called in sick"
    assert replacement["status"] == "ASSIGNED"
    assert replacement["replaces_assignment_id"] == packer_assignment["id"]
    assert read_crew_member(spare["id"])["assignment_count"] == 1


def test_the_vendor_payout_moves_from_interim_to_final_and_paid_is_terminal():
    """PRD §3.8: "Sign-off follows: the move manager, the client or a power of
    attorney supplies a `signed_off_by_party_id` that must resolve to a seat on the
    same engagement, `holdback_released` becomes true and `paid_cents` becomes the
    final payout, the full `quoted_cents`."
    PRD §2.7: "The subject entity is not already in one of its machine's terminal
    states. Otherwise `ERR_ALREADY_TERMINAL`, HTTP 409. Applies to every action
    endpoint that drives a state machine."

    Design: Corner/state_machines/vendor_lifecycle_perform_signoff_pay_and_terminal_lockdown
    """
    world = setup_engagement()
    vendor = new_vendor(
        "Bright Path Cleaning", "CLEANING", "2027-01-31", daily_capacity=3, holdback_pct=0.1
    )
    assignment = new_vendor_assignment(
        world["engagement_id"], vendor["id"], "CLEANING", "2026-06-16", 85000
    )
    accept_vendor_assignment(assignment["id"], vendor["id"])
    schedule_vendor_assignment(assignment["id"])
    set_clock("2026-06-16T10:00:00.000Z")

    performed = validate_success(
        api_client.perform_vendor_assignment(
            assignment["id"],
            {"performed_at_utc": "2026-06-16T10:00:00.000Z"},
            make_vendor_headers(vendor["id"]),
        )
    )
    assert performed["status"] == "PERFORMED"
    assert_money(performed["holdback_cents"], 8500, "holdback_cents")
    assert_money(performed["paid_cents"], 76500, "interim paid_cents")
    assert performed["holdback_released"] is False
    assert_vendor_payout_conservation(performed)

    signed = validate_success(
        api_client.sign_off_vendor_assignment(
            assignment["id"], {"signed_off_by_party_id": world["client_party"]["id"]}, MOVE_MANAGER
        )
    )
    assert_money(signed["paid_cents"], 85000, "final paid_cents")
    assert signed["holdback_released"] is True

    validate_success(api_client.pay_vendor_assignment(assignment["id"], BILLING_ADMIN))
    assert read_vendor_assignment(assignment["id"])["status"] == "PAID"
    # PRD §2.7 walks rung 48 (originating set, ERR_INVALID_STATE) before rung 49, and
    # "returns the error of the first rung it fails"; PAID is not in the pay
    # transition's originating set, so rung 48 is the first failure.
    validate_error(
        api_client.pay_vendor_assignment(assignment["id"], BILLING_ADMIN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert_vendor_payout_conservation(read_vendor_assignment(assignment["id"]))


def test_the_lateness_axis_latches_and_never_returns_to_on_time():
    """PRD §3.10: "The ops-run checkpoint moves it to `OVERDUE` when the milestone's
    status is `PENDING`, `IN_PROGRESS` or `REOPENED` and the logical clock's date is
    **strictly after** `due_on` — a clock date exactly equal to `due_on` is not
    overdue — and it walks the engagement's milestones in `sequence_index` ascending
    order, skipping `COMPLETE` ones."
    PRD §3.10: "Completing a milestone that is `OVERDUE` moves it to `RECOVERED`;
    reopening one that is `RECOVERED` moves it back to `OVERDUE`. `OVERDUE` and
    `RECOVERED` therefore alternate with completion and reopening, and `ON_TIME` is
    unreachable once left."

    Design: Corner/state_machines/milestone_overdue_latch_never_returns_to_on_time
    """
    world = setup_engagement()
    eng_id = world["engagement_id"]
    assessment_id = milestone_by_key(eng_id, "ASSESSMENT")["id"]

    set_clock("2026-05-11T23:00:00.000Z")
    get_success_data(api_client.ops_run(eng_id, MOVE_MANAGER))
    assert read_milestone(assessment_id)["overdue_status"] == "ON_TIME"

    set_clock("2026-05-12T09:00:00.000Z")
    validate_success(api_client.ops_run(eng_id, MOVE_MANAGER))
    assert read_milestone(assessment_id)["overdue_status"] == "OVERDUE"

    complete_milestone(assessment_id, world["client_party"]["id"])
    completed = read_milestone(assessment_id)
    assert completed["overdue_status"] == "RECOVERED"
    assert completed["status"] == "COMPLETE"

    validate_success(
        api_client.reopen_milestone(
            assessment_id, {"reason": "Assessment walkthrough was incomplete"}, MOVE_MANAGER
        )
    )
    reopened = read_milestone(assessment_id)
    assert reopened["overdue_status"] == "OVERDUE"
    assert reopened["status"] == "IN_PROGRESS"
    assert reopened["reopen_count"] == 1
    assert reopened["completed_at_utc"] is None
    assert read_engagement(eng_id)["phase"] == "ASSESSMENT"


def _settle_in_with_a_resolved_punch_and_a_closed_timeline():
    world = setup_settle_in(settle_in_clock="2026-06-20T09:00:00.000Z")
    eng_id = world["engagement_id"]
    session = new_unpack_session(eng_id, "2026-06-20T10:00:00.000Z", "ESSENTIALS")
    start_unpack_session(session["id"])
    complete_unpack_session(session["id"])
    punch = new_punch_item(
        eng_id, "Scratched dresser top", "MAJOR", unpack_session_id=session["id"]
    )
    resolve_punch_item(punch["id"], "Touched up by the crew")
    for key in ("SETTLE_IN", "CLOSE_OUT"):
        complete_milestone(
            milestone_by_key(eng_id, key)["id"], world["client_party"]["id"]
        )
    world["session"] = session
    world["punch"] = punch
    return world


def test_reopening_a_punch_item_reopens_its_session_and_the_close_out_milestone():
    """PRD §3.9: "The reopen raises `reopen_count` by one and cascades twice: where
    the item names an `unpack_session_id` and that session is `COMPLETED`, the
    session moves to `REOPENED`; and where the engagement's `CLOSE_OUT` milestone is
    `COMPLETE`, it moves to `REOPENED` too, pulling the engagement's `phase` back to
    `CLOSE_OUT`."

    Design: Corner/state_machines/punch_reopen_cascades_into_unpack_session_and_close_out_milestone
    """
    world = _settle_in_with_a_resolved_punch_and_a_closed_timeline()
    eng_id = world["engagement_id"]
    close_out_id = milestone_by_key(eng_id, "CLOSE_OUT")["id"]

    validate_success(
        api_client.reopen_punch_list_item(
            world["punch"]["id"], {"reason": "Scratch is still visible in daylight"}, MOVE_MANAGER
        )
    )
    punch = read_punch_item(world["punch"]["id"])
    assert punch["status"] == "REOPENED"
    assert punch["reopen_count"] == 1

    session = read_unpack_session(world["session"]["id"])
    assert session["status"] == "REOPENED"
    assert session["reopen_count"] == 1

    close_out = read_milestone(close_out_id)
    assert close_out["status"] == "IN_PROGRESS"
    assert close_out["reopen_count"] == 1
    assert read_engagement(eng_id)["phase"] == "CLOSE_OUT"


def test_suspend_and_reinstate_toggle_the_seat_while_revocation_is_terminal():
    """PRD §3.2: "Suspension moves `ACTIVE` to `SUSPENDED`, records the supplied
    reason in `revoked_reason`, raises `suspend_count` by one, and recomputes the
    holder's `can_approve_dispositions` to false when no other record of that seat
    remains `ACTIVE`. Reinstatement moves `SUSPENDED` back to `ACTIVE`, requires the
    clock to be strictly before `effective_to_utc`, and recomputes the holder's
    derived approval fields; the suspend-and-reinstate cycle is capped at two
    suspensions, and a third attempt is refused with `ERR_HOLD_ESCALATION_LIMIT`."

    Design: Corner/state_machines/authority_suspend_reinstate_cycle_and_revoke_is_terminal
    """
    world = setup_engagement(with_client_party=False, with_poa_party=True)
    party_id = world["poa_party"]["id"]
    record = new_active_authority(
        world["engagement_id"], party_id, authority_scope="FULL", approval_ceiling_cents=400000
    )
    before = read_party(party_id)
    assert before["can_approve_dispositions"] is True
    assert_money(before["active_authority_ceiling_cents"], 400000, "active ceiling")

    validate_success(
        api_client.suspend_authority_record(
            record["id"], {"reason": "Family dispute over the POA"}, MOVE_MANAGER
        )
    )
    assert read_authority(record["id"])["status"] == "SUSPENDED"
    assert read_party(party_id)["can_approve_dispositions"] is False

    validate_success(api_client.reinstate_authority_record(record["id"], MOVE_MANAGER))
    reinstated = read_authority(record["id"])
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspend_count"] == 1
    assert read_party(party_id)["can_approve_dispositions"] is True

    validate_success(
        api_client.revoke_authority_record(
            record["id"], {"reason": "Client revoked the POA"}, MOVE_MANAGER
        )
    )
    assert read_authority(record["id"])["status"] == "REVOKED"
    # PRD §2.7 rung 48 (originating set) precedes rung 49; reinstatement originates
    # only from SUSPENDED, so a REVOKED record fails rung 48 first.
    validate_error(
        api_client.reinstate_authority_record(record["id"], MOVE_MANAGER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    after = read_party(party_id)
    assert after["can_approve_dispositions"] is False
    assert_money(after["active_authority_ceiling_cents"], 0, "active ceiling after revocation")


def test_the_ops_run_checkpoint_expires_an_authority_whose_window_has_closed():
    """PRD §3.2: "Expiry is not a user action at all: the ops-run checkpoint moves
    any record in `PENDING`, `ACTIVE` or `SUSPENDED` to `EXPIRED` once the logical
    clock has reached `effective_to_utc`, and recomputes the holder's
    `can_approve_dispositions` to false when no other record of that seat remains
    `ACTIVE`."
    PRD §3.10: "It answers with the `engagement_id`, a `milestones_flagged_overdue`
    count, an `authorities_expired` count, a `vendor_assignments_blocked` count and
    the new `ops_run_seq`."

    Design: Corner/state_machines/authority_expires_at_ops_run_when_window_closes
    """
    world = setup_engagement(with_client_party=False, with_poa_party=True)
    record = new_active_authority(
        world["engagement_id"],
        world["poa_party"]["id"],
        authority_scope="FULL",
        effective_to_utc="2026-05-20T00:00:00.000Z",
        approval_ceiling_cents=400000,
    )
    set_clock("2026-05-20T00:00:00.000Z")
    report = validate_success(api_client.ops_run(world["engagement_id"], MOVE_MANAGER))

    assert report["authorities_expired"] == 1
    assert report["ops_run_seq"] == 1
    assert read_authority(record["id"])["status"] == "EXPIRED"
    assert read_party(world["poa_party"]["id"])["can_approve_dispositions"] is False
    assert read_engagement(world["engagement_id"])["ops_run_seq"] == 1


def test_a_standard_session_may_not_start_while_an_earlier_essentials_one_is_pending():
    """PRD §3.9: "Where the session's `priority` is `STANDARD`, every `ESSENTIALS`
    session of the same engagement created earlier must already be `COMPLETED`;
    otherwise the start is refused with `ERR_ESSENTIALS_SESSION_PENDING`."

    Design: Corner/state_machines/unpack_essentials_before_standard_ordering_enforced
    """
    world = setup_settle_in(settle_in_clock="2026-06-20T09:00:00.000Z")
    eng_id = world["engagement_id"]
    essentials = new_unpack_session(eng_id, "2026-06-20T10:00:00.000Z", "ESSENTIALS")
    standard = new_unpack_session(eng_id, "2026-06-21T10:00:00.000Z", "STANDARD")

    validate_error(
        api_client.start_unpack_session(standard["id"], MOVE_MANAGER),
        ApiErrorId.ERR_ESSENTIALS_SESSION_PENDING.value,
    )
    start_unpack_session(essentials["id"])
    complete_unpack_session(essentials["id"])
    validate_success(api_client.start_unpack_session(standard["id"], MOVE_MANAGER))

    assert read_unpack_session(essentials["id"])["status"] == "COMPLETED"
    assert read_unpack_session(standard["id"])["status"] == "IN_PROGRESS"
    assert read_unpack_session(essentials["id"])["items_unpacked_count"] == 0
