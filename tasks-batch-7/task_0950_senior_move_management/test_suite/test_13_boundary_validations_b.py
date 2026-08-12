"""The unsold window, the authority window, the two retry caps and the hold /
freeze gates on re-designation."""

from test_helpers import (
    ApiErrorId,
    FREEZE_INSTANT,
    MAX_AUTHORITY_SUSPENSIONS,
    MAX_MILESTONE_REOPENS,
    MOVE_MANAGER,
    MOVE_START,
    api_client,
    accept_vendor_assignment,
    assert_two_dp,
    complete_milestone,
    designate,
    drive_sort_plan_to_approved,
    get_success_data,
    make_client_headers,
    make_family_member_headers,
    make_vendor_headers,
    milestone_by_key,
    new_active_authority,
    new_authority_record,
    new_consignment_lot,
    new_family_hold,
    new_item,
    new_move_day_plan,
    new_vendor,
    new_vendor_assignment,
    read_authority,
    read_engagement,
    read_hold,
    read_item,
    read_lot,
    read_milestone,
    read_move_day_plan,
    read_party,
    read_room,
    read_vendor_assignment,
    schedule_vendor_assignment,
    set_clock,
    setup_engagement,
    validate_error,
    validate_success,
    assert_same_instant,
)

DONATE_SPEC = {
    "label": "Old linens",
    "category": "LINENS",
    "footprint_linear_inches": 10,
    "volume_cft": 5,
}


def _listed_lot(listed_on="2026-05-02"):
    world = setup_engagement(
        with_client_party=False, scheduled_move_start_utc="2026-08-15T14:00:00.000Z"
    )
    eng_id = world["engagement_id"]
    item = new_item(
        eng_id,
        label="Porcelain vase",
        category="ARTWORK",
        footprint_linear_inches=30,
        volume_cft=10,
        appraised_value_cents=40000,
        appraisal_source="APPRAISED",
    )
    designate(item["id"], "SELL")
    vendor = new_vendor("Harbour Consignment", "CONSIGNMENT", "2026-12-31")
    world["item"] = item
    world["lot"] = new_consignment_lot(eng_id, vendor["id"], 40000, listed_on, [item["id"]])
    return world


def test_the_unsold_window_elapses_exactly_on_day_thirty():
    """PRD §2.7: "A lot may be declared unsold only once the logical clock date is at
    least thirty days after `listed_on`. Otherwise `ERR_UNSOLD_WINDOW_NOT_ELAPSED`,
    HTTP 409. Applies to `POST /consignment-lots/{id}/declare-unsold`."

    Design: Corner/validations/unsold_window_elapses_exactly_on_day_thirty
    """
    world = _listed_lot()
    set_clock("2026-06-01T00:00:00.000Z")
    validate_success(api_client.declare_lot_unsold(world["lot"]["id"], MOVE_MANAGER))

    lot = read_lot(world["lot"]["id"])
    assert lot["status"] == "UNSOLD"
    assert lot["current_price_cents"] == 40000
    assert lot["markdown_round"] == 0
    assert read_item(world["item"]["id"])["consignment_lot_id"] == world["lot"]["id"]


def test_one_day_short_of_the_unsold_window_is_refused():
    """PRD §3.8: "Declaring a lot unsold is reachable from `LISTED` and from
    `MARKED_DOWN` and requires the logical clock's date to be at least thirty days
    after `listed_on`; an earlier attempt is refused with
    `ERR_UNSOLD_WINDOW_NOT_ELAPSED`. The move manager and the vendor may both declare."

    Design: Corner/validations/unsold_window_one_day_short_is_refused
    """
    world = _listed_lot()
    set_clock("2026-05-31T23:59:59.999Z")
    validate_error(
        api_client.declare_lot_unsold(world["lot"]["id"], MOVE_MANAGER),
        ApiErrorId.ERR_UNSOLD_WINDOW_NOT_ELAPSED.value,
    )
    assert read_lot(world["lot"]["id"])["status"] == "LISTED"


def _pending_authority(effective_from="2026-05-02T09:00:00.000Z", effective_to="2026-06-01T00:00:00.000Z"):
    world = setup_engagement(with_client_party=False, with_poa_party=True)
    world["authority"] = new_authority_record(
        world["engagement_id"],
        world["poa_party"]["id"],
        authority_scope="DISPOSITION_ONLY",
        effective_from_utc=effective_from,
        effective_to_utc=effective_to,
        approval_ceiling_cents=200000,
    )
    return world


def test_activation_at_exactly_effective_from_is_permitted():
    """PRD §3.2: "Activation moves `PENDING` to `ACTIVE` and is permitted only when
    the logical clock is at or after `effective_from_utc` and strictly before
    `effective_to_utc`; a clock outside that window yields
    `ERR_AUTHORITY_WINDOW_INVALID`. Activation recomputes the holder seat's
    `can_approve_dispositions` and `active_authority_ceiling_cents`."

    Design: Corner/validations/authority_activation_at_exactly_effective_from_is_permitted
    """
    world = _pending_authority()
    activated = validate_success(
        api_client.activate_authority_record(world["authority"]["id"], MOVE_MANAGER)
    )
    assert activated["status"] == "ACTIVE"
    party = read_party(world["poa_party"]["id"])
    assert party["can_approve_dispositions"] is True
    assert party["active_authority_ceiling_cents"] == 200000


def test_activation_at_exactly_effective_to_is_refused():
    """PRD §2.7: "An authority record's `effective_to_utc` is strictly after its
    `effective_from_utc` at creation; activation requires the clock to be at or after
    `effective_from_utc` and strictly before `effective_to_utc`; reinstatement
    requires the clock to be strictly before `effective_to_utc`. Otherwise
    `ERR_AUTHORITY_WINDOW_INVALID`, HTTP 409."

    Design: Corner/validations/authority_activation_at_exactly_effective_to_is_refused
    """
    world = _pending_authority()
    set_clock("2026-06-01T00:00:00.000Z")
    validate_error(
        api_client.activate_authority_record(world["authority"]["id"], MOVE_MANAGER),
        ApiErrorId.ERR_AUTHORITY_WINDOW_INVALID.value,
    )
    assert read_authority(world["authority"]["id"])["status"] == "PENDING"
    assert read_party(world["poa_party"]["id"])["can_approve_dispositions"] is False


def _authority_suspended_and_reinstated(times):
    world = setup_engagement(with_client_party=False, with_poa_party=True)
    record = new_active_authority(
        world["engagement_id"], world["poa_party"]["id"], authority_scope="FULL"
    )
    for index in range(times):
        get_success_data(
            api_client.suspend_authority_record(
                record["id"], {"reason": f"Review {index + 1} opened"}, MOVE_MANAGER
            )
        )
        get_success_data(api_client.reinstate_authority_record(record["id"], MOVE_MANAGER))
    world["authority"] = record
    return world


def test_the_second_suspension_is_still_inside_the_cap():
    """PRD §2.7: "A family hold's `escalation_count` and `remand_count` are each
    strictly below 2, and an authority record's `suspend_count` is strictly below 2.
    Otherwise `ERR_HOLD_ESCALATION_LIMIT`, HTTP 409."

    Design: Corner/validations/authority_suspend_cap_admits_the_second_suspension
    """
    world = _authority_suspended_and_reinstated(1)
    suspended = validate_success(
        api_client.suspend_authority_record(
            world["authority"]["id"], {"reason": "Second review opened"}, MOVE_MANAGER
        )
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspend_count"] == MAX_AUTHORITY_SUSPENSIONS
    assert read_party(world["poa_party"]["id"])["can_approve_dispositions"] is False


def test_the_third_suspension_is_refused_and_leaves_the_record_active():
    """PRD §3.2: "Reinstatement moves `SUSPENDED` back to `ACTIVE`, requires the
    clock to be strictly before `effective_to_utc`, and recomputes the holder's
    derived approval fields; the suspend-and-reinstate cycle is capped at two
    suspensions, and a third attempt is refused with `ERR_HOLD_ESCALATION_LIMIT`."

    Design: Corner/validations/authority_suspend_cap_refuses_the_third_suspension
    """
    world = _authority_suspended_and_reinstated(2)
    validate_error(
        api_client.suspend_authority_record(
            world["authority"]["id"], {"reason": "Third review opened"}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_HOLD_ESCALATION_LIMIT.value,
    )
    record = read_authority(world["authority"]["id"])
    assert record["status"] == "ACTIVE"
    assert record["suspend_count"] == MAX_AUTHORITY_SUSPENSIONS
    assert read_party(world["poa_party"]["id"])["can_approve_dispositions"] is True


def _assessment_reopened(times):
    world = setup_engagement()
    eng_id, party_id = world["engagement_id"], world["client_party"]["id"]
    assessment_id = milestone_by_key(eng_id, "ASSESSMENT")["id"]
    complete_milestone(assessment_id, party_id)
    for index in range(times):
        get_success_data(
            api_client.reopen_milestone(
                assessment_id, {"reason": f"Walkthrough {index + 1} incomplete"}, MOVE_MANAGER
            )
        )
        complete_milestone(assessment_id, party_id)
    world["assessment_id"] = assessment_id
    return world


def test_the_second_milestone_reopen_is_still_inside_the_cap():
    """PRD §2.7: "The milestone's `reopen_count` is below 2, the unpack session's
    `reopen_count` is below 2, and the punch-list item's `reopen_count` is below 3.
    Otherwise `ERR_REOPEN_LIMIT`, HTTP 409."
    PRD §3.10: "Reopening a completed milestone takes a `reason`, is reachable only
    from `COMPLETE`, is capped at two reopens, and additionally requires that no
    milestone of the same engagement with a higher `sequence_index` is `COMPLETE` —
    otherwise `ERR_SUCCESSOR_MILESTONE_COMPLETE`."

    Design: Corner/validations/milestone_reopen_cap_admits_the_second_reopen
    """
    world = _assessment_reopened(1)
    validate_success(
        api_client.reopen_milestone(
            world["assessment_id"], {"reason": "A second walkthrough is needed"}, MOVE_MANAGER
        )
    )
    milestone = read_milestone(world["assessment_id"])
    assert milestone["reopen_count"] == MAX_MILESTONE_REOPENS
    assert milestone["status"] == "IN_PROGRESS"
    assert milestone["completed_at_utc"] is None
    assert read_engagement(world["engagement_id"])["phase"] == "ASSESSMENT"


def test_the_third_milestone_reopen_is_refused_by_the_cap():
    """PRD §2.7: "The milestone's `reopen_count` is below 2, the unpack session's
    `reopen_count` is below 2, and the punch-list item's `reopen_count` is below 3.
    Otherwise `ERR_REOPEN_LIMIT`, HTTP 409. Applies to
    `POST /milestones/{id}/reopen` and `POST /punch-list-items/{id}/reopen`."

    Design: Corner/validations/milestone_reopen_cap_refuses_the_third_reopen
    """
    world = _assessment_reopened(2)
    validate_error(
        api_client.reopen_milestone(
            world["assessment_id"], {"reason": "A third walkthrough is needed"}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_REOPEN_LIMIT.value,
    )
    milestone = read_milestone(world["assessment_id"])
    assert milestone["status"] == "COMPLETE"
    assert milestone["reopen_count"] == MAX_MILESTONE_REOPENS
    assert read_engagement(world["engagement_id"])["phase"] == "SORT_PLAN"


def test_the_on_hold_block_exempts_exactly_resume_and_cancel():
    """PRD §2.7: "The owning engagement's `status` is not `ON_HOLD`, except for
    `POST /engagements/{id}/resume` and `POST /engagements/{id}/cancel`. Otherwise
    `ERR_ENGAGEMENT_ON_HOLD`, HTTP 409. Applies to every mutating endpoint under an
    engagement other than those two."

    Design: Corner/validations/on_hold_engagement_blocks_child_writes_but_exempts_resume_and_cancel
    """
    world = setup_engagement(with_client_party=False)
    eng_id = world["engagement_id"]
    get_success_data(
        api_client.hold_engagement(eng_id, {"reason": "Awaiting the family conference"}, MOVE_MANAGER)
    )
    validate_error(
        api_client.create_inventory_item(
            {
                "engagement_id": eng_id,
                "label": "Old linens",
                "category": "LINENS",
                "footprint_linear_inches": 10,
                "volume_cft": 5,
            },
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_ENGAGEMENT_ON_HOLD.value,
    )
    resumed = validate_success(api_client.resume_engagement(eng_id, MOVE_MANAGER))
    assert resumed["status"] == "ACTIVE"

    get_success_data(
        api_client.hold_engagement(eng_id, {"reason": "Conference postponed again"}, MOVE_MANAGER)
    )
    cancelled = validate_success(
        api_client.cancel_engagement(
            eng_id, {"reason": "Client moved in with family instead"}, MOVE_MANAGER
        )
    )
    assert cancelled["status"] == "CANCELLED"
    engagement = read_engagement(eng_id)
    assert engagement["hold_count"] == 2
    assert engagement["inventory_item_count"] == 0


def test_a_live_hold_blocks_re_designation_until_the_dispute_is_released():
    """PRD §3.5: "It is born `OPEN`, and creating it immediately sets the subject
    item's `hold_state` to `HELD`, which blocks re-designation, appraisal, staging and
    consignment membership for as long as the dispute is live."
    PRD §3.4: "A third, derived axis — `hold_state` — records whether a family member
    has frozen the object mid-argument, and reads `HELD` when at least one hold on the
    item is `OPEN` or `ESCALATED` and `NONE` otherwise."

    Design: Corner/validations/hold_state_rung_blocks_re_designation_until_the_hold_is_resolved
    """
    world = setup_engagement(
        with_family_party=True,
        with_residence=True,
        room_kwargs={"nominal_linear_inches": 240, "nominal_volume_cft": 200},
    )
    eng_id, room_id = world["engagement_id"], world["room"]["id"]
    item = new_item(eng_id, label="Wing chair", footprint_linear_inches=30, volume_cft=20)
    designate(item["id"], "DONATE")
    hold = new_family_hold(
        item["id"],
        world["family_party"]["id"],
        headers=make_family_member_headers(world["family_party"]["id"]),
        reason="Grandchild may want the chair",
    )

    validate_error(
        api_client.designate_item(
            item["id"], {"disposition": "KEEP", "assigned_room_id": room_id}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_ITEM_UNDER_FAMILY_HOLD.value,
    )
    validate_success(
        api_client.resolve_family_hold(
            hold["id"],
            {"resolution": "RELEASE", "resolved_by_party_id": world["client_party"]["id"]},
            MOVE_MANAGER,
        )
    )
    assert read_hold(hold["id"])["status"] == "RESOLVED_RELEASE"
    assert read_item(item["id"])["hold_state"] == "NONE"

    validate_success(
        api_client.designate_item(
            item["id"], {"disposition": "KEEP", "assigned_room_id": room_id}, MOVE_MANAGER
        )
    )
    moved = read_item(item["id"])
    assert moved["disposition"] == "KEEP"
    assert moved["redesignation_count"] == 1
    assert_two_dp(read_room(room_id)["keep_load_linear_inches"], 30.00, "keep_load_linear_inches")


def test_a_reopened_sort_plan_milestone_still_meets_the_freeze_window():
    """PRD §2.7: "Once the logical clock is at or after that same instant, no
    inventory item may be designated or appraised. Otherwise
    `ERR_FREEZE_WINDOW_ENTERED`, HTTP 409."
    PRD §3.10: "The engagement's `phase` is derived, never assigned. It is the
    `milestone_key` of the open milestone with the lowest `sequence_index`, where
    "open" means status `PENDING`, `IN_PROGRESS` or `REOPENED`; when no milestone is
    open at all, the phase reads `DONE`."

    Design: Corner/validations/designate_after_a_milestone_reopen_still_hits_the_freeze_window_rung
    """
    world = setup_engagement()
    eng_id = world["engagement_id"]
    item = new_item(eng_id, **DONATE_SPEC)
    designate(item["id"], "DONATE")
    drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])
    plan = new_move_day_plan(eng_id)
    get_success_data(
        api_client.reopen_milestone(
            milestone_by_key(eng_id, "SORT_PLAN")["id"],
            {"reason": "One disposition still under discussion"},
            MOVE_MANAGER,
        )
    )
    set_clock(FREEZE_INSTANT)

    assert read_engagement(eng_id)["phase"] == "SORT_PLAN"
    assert_same_instant(read_move_day_plan(plan["id"])["freeze_at_utc"], FREEZE_INSTANT, "freeze_at_utc")
    error = validate_error(
        api_client.designate_item(item["id"], {"disposition": "HAUL_AWAY"}, MOVE_MANAGER),
        ApiErrorId.ERR_FREEZE_WINDOW_ENTERED.value,
    )
    assert error["error_id"] not in (
        ApiErrorId.ERR_PHASE_NOT_PERMITTED.value,
        ApiErrorId.ERR_DISPOSITION_LOCKED.value,
    )
    assert read_item(item["id"])["disposition"] == "DONATE"
