"""The recrew cycle, the crew no-show fork, vendor cancellation, the ON_HOLD
cancel exemption and the reschedule out of FROZEN."""

from test_helpers import (
    ApiErrorId,
    CREW_MIN_REQUIRED,
    FREEZE_INSTANT,
    MOVE_MANAGER,
    MOVE_START,
    api_client,
    accept_vendor_assignment,
    assert_money,
    assert_same_instant,
    assign_crew,
    confirm_assignment,
    designate,
    drive_sort_plan_to_approved,
    get_success_data,
    make_crew_lead_headers,
    make_vendor_headers,
    new_active_authority,
    new_crew_member,
    new_item,
    new_move_day_plan,
    new_vendor,
    new_vendor_assignment,
    no_show,
    read_authority,
    read_crew_assignment,
    read_engagement,
    read_item,
    read_move_day_plan,
    read_party,
    read_sort_plan,
    read_vendor_assignment,
    schedule_vendor_assignment,
    set_clock,
    setup_engagement,
    setup_move_day_plan_confirmed,
    trip_count,
    validate_error,
    validate_success,
)

DONATE_SPEC = {
    "label": "Old linens",
    "category": "LINENS",
    "footprint_linear_inches": 10,
    "volume_cft": 5,
}


def _draft_plan_with_two_assigned_crew():
    world = setup_engagement(with_residence=True)
    eng_id = world["engagement_id"]
    keeper = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40)
    donor = new_item(eng_id, **DONATE_SPEC)
    designate(keeper["id"], "KEEP", world["room"]["id"])
    designate(donor["id"], "DONATE")
    world["sort_plan"] = drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])

    plan = new_move_day_plan(eng_id)
    lead = new_crew_member("Tom Reyes", "LEAD", 9500)
    packer = new_crew_member("Nina Ortiz", "PACKER", 6800)
    world["plan"] = plan
    world["lead_member"] = lead
    world["lead_assignment"] = assign_crew(plan["id"], lead["id"])
    world["packer_assignment"] = assign_crew(plan["id"], packer["id"])
    world["keeper"] = keeper
    return world


def test_the_plan_bubbles_to_crewed_only_on_the_confirm_that_meets_the_minimum():
    """PRD §3.7: "Confirming an assignment moves it from `ASSIGNED` to `CONFIRMED`
    and is permitted only while the parent plan is `DRAFT` or `CREWED`."
    PRD §3.7: "Re-crewing takes a `reason`, requires the logical clock to be strictly
    before `freeze_at_utc`, returns the plan to `DRAFT` and reverts every `CONFIRMED`
    assignment on it to `ASSIGNED`, recomputing `crew_confirmed_count` to zero."

    Design: Corner/state_machines/move_day_recrew_cycle_and_crewed_bubble_up
    """
    world = _draft_plan_with_two_assigned_crew()
    plan_id = world["plan"]["id"]

    confirm_assignment(world["lead_assignment"]["id"])
    first = read_move_day_plan(plan_id)
    assert first["status"] == "DRAFT"
    assert first["crew_confirmed_count"] == 1

    confirm_assignment(world["packer_assignment"]["id"])
    crewed = read_move_day_plan(plan_id)
    assert crewed["status"] == "CREWED"
    assert crewed["crew_min_required"] == CREW_MIN_REQUIRED["STUDIO"]
    assert crewed["planned_trip_count"] == trip_count(40, 1000, 1)

    get_success_data(api_client.confirm_move_day_plan(plan_id, MOVE_MANAGER))
    validate_success(
        api_client.recrew_move_day_plan(plan_id, {"reason": "Swapping the packer"}, MOVE_MANAGER)
    )
    recrewed = read_move_day_plan(plan_id)
    assert recrewed["status"] == "DRAFT"
    assert recrewed["crew_confirmed_count"] == 0
    assert read_crew_assignment(world["lead_assignment"]["id"])["status"] == "ASSIGNED"
    assert read_crew_assignment(world["packer_assignment"]["id"])["status"] == "ASSIGNED"

    confirm_assignment(world["lead_assignment"]["id"])
    confirm_assignment(world["packer_assignment"]["id"])
    get_success_data(api_client.confirm_move_day_plan(plan_id, MOVE_MANAGER))
    set_clock(FREEZE_INSTANT)
    get_success_data(api_client.freeze_move_day_plan(plan_id, MOVE_MANAGER))
    set_clock(MOVE_START)
    get_success_data(api_client.start_move_day_plan(plan_id, MOVE_MANAGER))

    started = read_move_day_plan(plan_id)
    assert started["status"] == "IN_PROGRESS"
    assert_same_instant(started["started_at_utc"], MOVE_START, "started_at_utc")

    validate_success(
        api_client.check_in_crew_assignment(
            world["lead_assignment"]["id"],
            {"at_utc": MOVE_START},
            make_crew_lead_headers(world["lead_member"]["id"]),
        )
    )
    assert read_crew_assignment(world["lead_assignment"]["id"])["status"] == "CHECKED_IN"


def test_an_assigned_crew_member_may_no_show_before_ever_confirming():
    """PRD §3.7: "A member who never turns up is marked with a `note` stored as
    `no_show_note`; that is reachable from `ASSIGNED` and from `CONFIRMED`, and from
    `CONFIRMED` it recomputes `crew_confirmed_count` downward, which may drop the
    plan below its crew minimum."
    PRD §2.7: "The subject entity's current state is in the triggered transition's
    declared originating set. Otherwise `ERR_INVALID_STATE`, HTTP 409."

    Design: Corner/state_machines/assigned_crew_no_show_before_confirmation
    """
    world = _draft_plan_with_two_assigned_crew()
    packer = world["packer_assignment"]["id"]

    validate_success(
        api_client.no_show_crew_assignment(
            packer, {"note": "Never showed for the pre-brief"}, MOVE_MANAGER
        )
    )
    marked = read_crew_assignment(packer)
    assert marked["status"] == "NO_SHOW"
    assert marked["no_show_note"] == "Never showed for the pre-brief"
    plan = read_move_day_plan(world["plan"]["id"])
    assert plan["crew_confirmed_count"] == 0
    assert plan["status"] == "DRAFT"

    validate_error(
        api_client.no_show_crew_assignment(packer, {"note": "Duplicate"}, MOVE_MANAGER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_cancelling_a_scheduled_order_hands_its_day_slot_to_the_next_order():
    """PRD §3.8: "Cancellation is reachable from `REQUESTED`, `ACCEPTED`,
    `SCHEDULED` and `COI_BLOCKED`, takes a `reason` stored as `cancel_reason`, and is
    open to the move manager and the vendor; cancelling from `SCHEDULED` additionally
    frees the slot it held on the vendor's day."

    Design: Corner/state_machines/scheduled_vendor_cancel_frees_the_daily_capacity_slot
    """
    world = setup_engagement(with_client_party=False)
    eng_id = world["engagement_id"]
    vendor = new_vendor(
        "Bright Path Cleaning", "CLEANING", "2027-01-31", daily_capacity=1, holdback_pct=0.1
    )
    first = new_vendor_assignment(eng_id, vendor["id"], "CLEANING", "2026-06-16", 85000)
    second = new_vendor_assignment(eng_id, vendor["id"], "CLEANING", "2026-06-16", 60000)
    accept_vendor_assignment(first["id"], vendor["id"])
    accept_vendor_assignment(second["id"], vendor["id"])
    schedule_vendor_assignment(first["id"])

    validate_success(
        api_client.cancel_vendor_assignment(
            first["id"],
            {"reason": "Client cancelled the deep clean"},
            make_vendor_headers(vendor["id"]),
        )
    )
    cancelled = read_vendor_assignment(first["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "Client cancelled the deep clean"

    validate_success(api_client.schedule_vendor_assignment(second["id"], MOVE_MANAGER))
    scheduled = read_vendor_assignment(second["id"])
    assert scheduled["status"] == "SCHEDULED"
    assert_money(scheduled["holdback_cents"], 6000, "holdback_cents")


def test_cancel_is_exempt_from_the_on_hold_block_after_a_suspended_authority_is_revoked():
    """PRD §3.2: "Revocation is irreversible and is reachable from `PENDING`,
    `ACTIVE` and `SUSPENDED`; it records `revoked_reason`, and from `ACTIVE` it also
    recomputes the holder's `can_approve_dispositions` to false when no other record
    of that seat remains `ACTIVE`."
    PRD §3.1: "While the engagement is `ON_HOLD`, every mutating endpoint in its
    subtree is refused with `ERR_ENGAGEMENT_ON_HOLD` except resuming and cancelling."

    Design: Corner/state_machines/on_hold_engagement_can_still_be_cancelled_and_revokes_its_authorities
    """
    world = setup_engagement(with_client_party=False, with_poa_party=True)
    eng_id, party_id = world["engagement_id"], world["poa_party"]["id"]
    record = new_active_authority(
        eng_id, party_id, authority_scope="FULL", approval_ceiling_cents=400000
    )
    get_success_data(
        api_client.suspend_authority_record(record["id"], {"reason": "Under review"}, MOVE_MANAGER)
    )
    validate_success(
        api_client.revoke_authority_record(
            record["id"], {"reason": "Client revoked while suspended"}, MOVE_MANAGER
        )
    )
    revoked = read_authority(record["id"])
    assert revoked["status"] == "REVOKED"
    assert revoked["suspend_count"] == 1
    assert read_party(party_id)["can_approve_dispositions"] is False

    get_success_data(
        api_client.hold_engagement(eng_id, {"reason": "Client hospitalised"}, MOVE_MANAGER)
    )
    validate_success(
        api_client.cancel_engagement(eng_id, {"reason": "Move called off"}, MOVE_MANAGER)
    )
    engagement = read_engagement(eng_id)
    assert engagement["status"] == "CANCELLED"
    assert engagement["hold_count"] == 1
    assert engagement["cancel_reason"] == "Move called off"


def test_rescheduling_out_of_frozen_leaves_the_sort_plan_terminal():
    """PRD §3.7: "From the frozen leg there is one further pinned outcome: a sort
    plan already `FROZEN` does **not** return to `APPROVED`, because `FROZEN` is
    terminal."
    PRD §3.7: "Rescheduling is the escape hatch and is reachable from `CONFIRMED` and
    from `FROZEN`."

    Design: Corner/state_machines/reschedule_from_frozen_leaves_the_sort_plan_frozen
    """
    world = setup_move_day_plan_confirmed(other_items=[dict(DONATE_SPEC)])
    plan_id = world["plan"]["id"]
    set_clock(FREEZE_INSTANT)
    get_success_data(api_client.freeze_move_day_plan(plan_id, MOVE_MANAGER))

    validate_success(
        api_client.reschedule_move_day_plan(
            plan_id,
            {"new_start_utc": "2026-06-29T14:00:00.000Z", "reason": "Building elevator out of service"},
            MOVE_MANAGER,
        )
    )
    plan = read_move_day_plan(plan_id)
    assert plan["status"] == "DRAFT"
    assert plan["reschedule_count"] == 1
    assert_same_instant(plan["scheduled_start_utc"], "2026-06-29T14:00:00.000Z", "scheduled_start_utc")
    assert_same_instant(plan["freeze_at_utc"], "2026-06-26T14:00:00.000Z", "freeze_at_utc")
    assert plan["crew_confirmed_count"] == 0
    assert read_crew_assignment(world["lead_assignment"]["id"])["status"] == "ASSIGNED"

    assert read_sort_plan(world["sort_plan"]["id"])["status"] == "FROZEN"
    assert read_item(world["items"][0]["id"])["disposition_locked"] is True
