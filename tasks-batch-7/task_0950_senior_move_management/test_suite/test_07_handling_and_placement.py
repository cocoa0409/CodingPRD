"""The two handling branches, the placement propose/revise leg, the full
disposition mesh and the release resolution."""

from test_helpers import (
    ApiErrorId,
    MOVE_MANAGER,
    MOVE_START,
    api_client,
    accept_vendor_assignment,
    advance_handling,
    assert_two_dp,
    check_in,
    complete_unpack_session,
    designate,
    freeze_and_start,
    get_success_data,
    make_client_headers,
    make_crew_lead_headers,
    make_family_member_headers,
    make_vendor_headers,
    new_family_hold,
    new_item,
    new_unpack_session,
    new_vendor,
    new_vendor_assignment,
    read_engagement,
    read_hold,
    read_item,
    read_residence,
    read_room,
    read_unpack_session,
    read_vendor_assignment,
    room_effective_capacity,
    schedule_vendor_assignment,
    set_clock,
    setup_engagement,
    setup_move_day_plan_confirmed,
    start_unpack_session,
    validate_error,
    validate_success,
    assert_money,
    drive_sort_plan_to_approved,
)

DONATE_SPEC = {
    "label": "Old linens",
    "category": "LINENS",
    "footprint_linear_inches": 10,
    "volume_cft": 5,
}


def test_the_keep_branch_walks_packed_loaded_delivered_and_unpacked():
    """PRD §3.4: "Branch A carries the keepers: `PACKED`, then `LOADED`, then
    `DELIVERED`, then `UNPACKED`."
    PRD §3.4: "`DELIVERED` to `UNPACKED` requires the supplied unpack session to
    belong to the same engagement and to be `IN_PROGRESS`; it sets the item's
    `unpack_session_id` and raises that session's `items_unpacked_count`."

    Design: Corner/state_machines/handling_branch_a_walks_packed_loaded_delivered_unpacked
    """
    world = setup_move_day_plan_confirmed(other_items=[dict(DONATE_SPEC)])
    freeze_and_start(world)
    keeper = world["items"][0]["id"]
    crew_headers = make_crew_lead_headers(world["lead_member"]["id"])

    for target in ("PACKED", "LOADED", "DELIVERED"):
        validate_success(
            api_client.advance_handling(keeper, {"target_handling_state": target}, crew_headers)
        )

    # PRD §3.7: completing move day "requires the plan to be `IN_PROGRESS` and every
    # assignment on it to be `COMPLETED`, `NO_SHOW`, `REPLACED` or `CHECKED_IN` - no
    # assignment may still be `ASSIGNED` or `CONFIRMED`", so the roster is clocked in
    # before the cascade is driven.
    check_in(world["lead_assignment"]["id"], MOVE_START)
    check_in(world["packer_assignment"]["id"], MOVE_START)
    set_clock("2026-06-15T23:30:00.000Z")
    get_success_data(
        api_client.complete_move_day_plan(
            world["plan"]["id"], {"actual_loaded_volume_cft": 2200}, MOVE_MANAGER
        )
    )
    set_clock("2026-06-20T09:00:00.000Z")
    session = new_unpack_session(
        world["engagement_id"], "2026-06-20T10:00:00.000Z", "ESSENTIALS"
    )
    start_unpack_session(session["id"])
    advance_handling(keeper, "UNPACKED", unpack_session_id=session["id"])
    complete_unpack_session(session["id"])

    item = read_item(keeper)
    assert item["handling_state"] == "UNPACKED"
    assert item["disposition"] == "KEEP"
    assert item["unpack_session_id"] == session["id"]
    stored = read_unpack_session(session["id"])
    assert stored["items_unpacked_count"] == 1
    assert stored["status"] == "COMPLETED"
    assert read_engagement(world["engagement_id"])["phase"] == "SETTLE_IN"


def test_the_disposal_branch_stages_only_once_the_hold_is_lifted_then_removes():
    """PRD §2.7: "The item's `hold_state` is `NONE` for appraisal, for staging and
    for consignment membership. Otherwise `ERR_ITEM_UNDER_FAMILY_HOLD`, HTTP 409."
    PRD §3.4: "`STAGED_FOR_PICKUP` to `REMOVED` requires at least one vendor
    assignment on the engagement whose `service_kind` matches the item's disposition
    family to be `PERFORMED`, `SIGNED_OFF` or `PAID`, and it recomputes the
    engagement's `haul_volume_cft` when the disposition is `HAUL_AWAY`."

    Design: Corner/state_machines/handling_branch_b_stages_then_removes_after_vendor_performance
    """
    world = setup_engagement(with_family_party=True, with_residence=True)
    eng_id = world["engagement_id"]
    keeper = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40)
    junk = new_item(eng_id, label="Garage shelving", category="MISC", footprint_linear_inches=50, volume_cft=25)
    designate(keeper["id"], "KEEP", world["room"]["id"])
    designate(junk["id"], "HAUL_AWAY")
    drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])

    hold = new_family_hold(junk["id"], world["family_party"]["id"], reason="Wait, I want the shelving")
    vendor = new_vendor("Northside Junk Haul", "JUNK_HAUL", "2027-01-31", daily_capacity=3, holdback_pct=0.1)
    order = new_vendor_assignment(eng_id, vendor["id"], "HAUL_AWAY", "2026-06-15", 85000)
    accept_vendor_assignment(order["id"], vendor["id"])
    schedule_vendor_assignment(order["id"])

    validate_error(
        api_client.advance_handling(
            junk["id"], {"target_handling_state": "STAGED_FOR_PICKUP"}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_ITEM_UNDER_FAMILY_HOLD.value,
    )
    validate_success(
        api_client.withdraw_family_hold(
            hold["id"], make_family_member_headers(world["family_party"]["id"])
        )
    )
    assert read_hold(hold["id"])["status"] == "WITHDRAWN"
    assert read_item(junk["id"])["hold_state"] == "NONE"

    advance_handling(junk["id"], "STAGED_FOR_PICKUP")
    set_clock("2026-06-15T12:00:00.000Z")
    performed = validate_success(
        api_client.perform_vendor_assignment(
            order["id"],
            {"performed_at_utc": "2026-06-15T12:00:00.000Z"},
            make_vendor_headers(vendor["id"]),
        )
    )
    assert performed["status"] == "PERFORMED"
    assert_money(performed["paid_cents"], 76500, "interim paid_cents")

    advance_handling(junk["id"], "REMOVED")
    removed = read_item(junk["id"])
    assert removed["handling_state"] == "REMOVED"
    assert removed["disposition"] == "HAUL_AWAY"


def test_proposing_then_revising_a_placement_leaves_the_revision_counter_alone():
    """PRD §3.3: "From `PROPOSED` it returns the plan to `DRAFT` and recomputes child
    room capacities under the provisional variant; nothing else changes."
    PRD §3.3: "`placement_revision` starts at 1 and counts only revisions out of
    `APPROVED`; the residence also carries `room_count` and
    `total_effective_capacity_linear_inches`, the latter summing
    `effective_capacity_linear_inches` across its rooms."

    Design: Corner/state_machines/placement_propose_then_revise_returns_to_draft
    """
    world = setup_engagement(with_residence=True)
    eng_id, room_id = world["engagement_id"], world["room"]["id"]
    keeper = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40)
    donor = new_item(eng_id, **DONATE_SPEC)
    designate(keeper["id"], "KEEP", room_id)
    designate(donor["id"], "DONATE")

    validate_success(api_client.propose_placement(world["residence"]["id"], MOVE_MANAGER))
    assert read_residence(world["residence"]["id"])["placement_status"] == "PROPOSED"

    validate_success(
        api_client.revise_placement(
            world["residence"]["id"], {"reason": "Wrong wall measurements"}, MOVE_MANAGER
        )
    )
    residence = read_residence(world["residence"]["id"])
    assert residence["placement_status"] == "DRAFT"
    assert residence["placement_revision"] == 1
    assert residence["approved_by_party_id"] is None

    room = read_room(room_id)
    assert_two_dp(
        room["effective_capacity_linear_inches"],
        room_effective_capacity(240, 0, approved=False),
        "effective_capacity_linear_inches",
    )
    assert_two_dp(room["headroom_linear_inches"], 96.00, "headroom_linear_inches")


def test_every_initial_designation_succeeds_and_an_unconsigned_sell_may_still_be_hauled():
    """PRD §3.4: "The disposition axis starts at `UNDECIDED` and admits `KEEP`,
    `DONATE`, `SELL` and `HAUL_AWAY`. Before the sort plan is approved it is a fully
    reversible mesh: any of the five values may move to any other, provided
    `disposition_locked` is false and `hold_state` is `NONE`."
    PRD §3.4: "Going from `SELL` to `HAUL_AWAY` is reserved to the move manager and
    additionally requires the item's `consignment_lot_id` to be null; it recomputes
    `haul_volume_cft` and raises `redesignation_count` by one."

    Design: Corner/state_machines/disposition_mesh_covers_every_initial_designation_and_sell_to_haul
    """
    world = setup_engagement(with_client_party=False, with_residence=True)
    eng_id, room_id = world["engagement_id"], world["room"]["id"]
    keeper = new_item(eng_id, label="Keeper", footprint_linear_inches=96, volume_cft=40)
    donor = new_item(eng_id, label="Donor", category="LINENS", footprint_linear_inches=10, volume_cft=5)
    seller = new_item(
        eng_id,
        label="Seller",
        category="ARTWORK",
        footprint_linear_inches=20,
        volume_cft=8,
        appraised_value_cents=45000,
        appraisal_source="APPRAISED",
    )
    junk = new_item(eng_id, label="Junk", category="MISC", footprint_linear_inches=30, volume_cft=60)

    validate_success(
        api_client.designate_item(
            keeper["id"], {"disposition": "KEEP", "assigned_room_id": room_id}, MOVE_MANAGER
        )
    )
    validate_success(api_client.designate_item(donor["id"], {"disposition": "DONATE"}, MOVE_MANAGER))
    validate_success(api_client.designate_item(seller["id"], {"disposition": "SELL"}, MOVE_MANAGER))
    validate_success(api_client.designate_item(junk["id"], {"disposition": "HAUL_AWAY"}, MOVE_MANAGER))
    validate_success(
        api_client.designate_item(seller["id"], {"disposition": "HAUL_AWAY"}, MOVE_MANAGER)
    )

    assert read_item(keeper["id"])["assigned_room_id"] == room_id
    assert read_item(donor["id"])["disposition"] == "DONATE"
    assert read_item(junk["id"])["disposition"] == "HAUL_AWAY"
    converted = read_item(seller["id"])
    assert converted["disposition"] == "HAUL_AWAY"
    assert converted["redesignation_count"] == 1

    engagement = read_engagement(eng_id)
    assert_two_dp(engagement["keep_volume_cft"], 40.00, "keep_volume_cft")
    assert_two_dp(engagement["haul_volume_cft"], 68.00, "haul_volume_cft")
    assert_two_dp(engagement["total_inventory_volume_cft"], 113.00, "total_inventory_volume_cft")


def test_releasing_an_escalated_hold_clears_the_hold_but_not_the_disposition():
    """PRD §3.5: "Resolving the other way — the `RELEASE` resolution — is likewise
    reachable from `OPEN` or `ESCALATED`; it stamps `resolved_by_party_id` and
    `resolution_note` and recomputes `hold_state` to `NONE` under the same condition,
    but leaves the disposition untouched, so the table goes to the consignment house
    after all."

    Design: Corner/state_machines/escalated_hold_resolved_release_leaves_disposition_untouched
    """
    world = setup_engagement(with_family_party=True, with_residence=True)
    eng_id = world["engagement_id"]
    keeper = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40)
    donor = new_item(eng_id, **DONATE_SPEC)
    designate(keeper["id"], "KEEP", world["room"]["id"])
    designate(donor["id"], "DONATE")

    family_headers = make_family_member_headers(world["family_party"]["id"])
    hold = new_family_hold(
        donor["id"], world["family_party"]["id"], headers=family_headers, reason="Those were grandmother's"
    )
    validate_success(
        api_client.escalate_family_hold(hold["id"], {"note": "Family cannot agree"}, family_headers)
    )

    validate_success(
        api_client.resolve_family_hold(
            hold["id"],
            {"resolution": "RELEASE", "resolved_by_party_id": world["client_party"]["id"]},
            make_client_headers(world["client"]["id"]),
        )
    )
    resolved = read_hold(hold["id"])
    assert resolved["status"] == "RESOLVED_RELEASE"
    assert resolved["escalation_count"] == 1
    assert resolved["resolved_by_party_id"] == world["client_party"]["id"]

    item = read_item(donor["id"])
    assert item["hold_state"] == "NONE"
    assert item["disposition"] == "DONATE"
