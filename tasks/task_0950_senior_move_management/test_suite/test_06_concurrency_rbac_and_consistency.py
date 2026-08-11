"""Optimistic concurrency on the three parent versions, the ops-run checkpoint,
eager derived-field reconciliation, the unpack selector, role denials and the
immediate visibility of every cascade."""

from test_helpers import (
    ApiErrorId,
    BILLING_ADMIN,
    FREEZE_INSTANT,
    MOVE_MANAGER,
    MOVE_START,
    PLATFORM_ADMIN,
    api_client,
    accept_vendor_assignment,
    assert_money,
    assert_two_dp,
    assert_hours,
    complete_unpack_session,
    coordination_fee_cents,
    create_crew_assignment_payload,
    create_invoice_line_payload,
    create_sort_plan_payload,
    designate,
    drive_sort_plan_to_approved,
    get_success_data,
    invoice_of,
    labor_cents,
    long_carry_surcharge_cents,
    make_family_member_headers,
    make_vendor_headers,
    milestone_by_key,
    new_crew_member,
    new_item,
    new_move_day_plan,
    new_portal_party,
    new_room,
    new_sort_plan,
    new_unpack_session,
    new_vendor,
    new_vendor_assignment,
    read_crew_assignment,
    read_engagement,
    read_invoice,
    read_move_day_plan,
    read_residence,
    read_room,
    read_sort_plan,
    read_summary,
    read_unpack_session,
    read_vendor,
    read_vendor_assignment,
    room_effective_capacity,
    schedule_vendor_assignment,
    set_clock,
    setup_completed_move_day,
    setup_engagement,
    setup_issued_invoice,
    setup_move_day_plan_confirmed,
    setup_settle_in,
    stairs_surcharge_cents,
    start_unpack_session,
    submit_sort_plan,
    travel_surcharge_cents,
    trip_count,
    validate_error,
    validate_paginated,
    validate_success,
)

CHECK_OUT_2330 = "2026-06-15T23:30:00.000Z"
EXPECTED_LABOUR = labor_cents(9.50, 9500) + labor_cents(6.00, 6800)
EXPECTED_SUBTOTAL = (
    EXPECTED_LABOUR
    + travel_surcharge_cents(22)
    + stairs_surcharge_cents(2, 2)
    + long_carry_surcharge_cents(100)
)
EXPECTED_FEE = coordination_fee_cents(EXPECTED_SUBTOTAL)


def test_a_sort_plan_create_carrying_a_pre_catalogue_engagement_version_is_stale():
    """PRD §2.10: "`POST /sort-plans` therefore requires
    `expected_engagement_version` carrying the client's last observed `version` of
    the target `Engagement`. If it does not equal the engagement's current `version`
    at the moment the create is processed, the request is rejected with
    `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_engagement_version_on_sort_plan_create
    """
    world = setup_engagement()
    eng_id = world["engagement_id"]
    observed = read_engagement(eng_id)["version"]
    new_item(eng_id, label="Old linens", category="LINENS", footprint_linear_inches=10, volume_cft=5)

    validate_error(
        api_client.create_sort_plan(create_sort_plan_payload(eng_id, observed), MOVE_MANAGER),
        ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value,
    )
    refreshed = read_engagement(eng_id)["version"]
    plan = validate_success(
        api_client.create_sort_plan(create_sort_plan_payload(eng_id, refreshed), MOVE_MANAGER),
        expected_status=201,
    )
    assert plan["status"] == "DRAFT"
    _, meta = validate_paginated(
        api_client.list_sort_plans(MOVE_MANAGER, params={"engagement_id": eng_id})
    )
    assert meta["total_count"] == 1


def test_the_plan_version_goes_stale_as_soon_as_the_first_assignment_is_created():
    """PRD §2.10: "Creating a crew assignment can supersede a `NO_SHOW` slot and
    therefore changes the plan's `crew_confirmed_count` and possibly its status."
    PRD §3.7: "Creating one raises the plan's `version` by one, transitions the
    replaced assignment from `NO_SHOW` to `REPLACED`, and raises the crew member's
    `assignment_count`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_move_day_plan_version_on_crew_assignment_create
    """
    world = setup_engagement()
    eng_id = world["engagement_id"]
    item = new_item(eng_id, label="Old linens", category="LINENS", footprint_linear_inches=10, volume_cft=5)
    designate(item["id"], "DONATE")
    drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])

    plan = new_move_day_plan(eng_id)
    observed = plan["version"]
    lead = new_crew_member("Tom Reyes", "LEAD", 9500)
    packer = new_crew_member("Nina Ortiz", "PACKER", 6800)
    get_success_data(
        api_client.create_crew_assignment(
            create_crew_assignment_payload(plan["id"], lead["id"], observed), MOVE_MANAGER
        )
    )
    validate_error(
        api_client.create_crew_assignment(
            create_crew_assignment_payload(plan["id"], packer["id"], observed), MOVE_MANAGER
        ),
        ApiErrorId.ERR_STALE_MOVE_DAY_PLAN_VERSION.value,
    )
    refreshed = read_move_day_plan(plan["id"])["version"]
    second = validate_success(
        api_client.create_crew_assignment(
            create_crew_assignment_payload(plan["id"], packer["id"], refreshed), MOVE_MANAGER
        ),
        expected_status=201,
    )
    assert second["status"] == "ASSIGNED"
    _, meta = validate_paginated(
        api_client.list_crew_assignments(MOVE_MANAGER, params={"move_day_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 2


def test_a_manual_line_one_version_behind_is_rejected_and_the_fresh_one_lands():
    """PRD §2.10: "A manual adjustment line is written against a specific observed
    ledger state, and settlement, reversal, vendor pass-through and labour cascades
    all append lines and advance `Invoice.version`."
    PRD §3.11: "Billing may append a manual adjustment directly, supplying
    `expected_invoice_version` under the optimistic-concurrency rule of §2.10; that
    append raises the invoice's `version` by one and recomputes `subtotal_cents`,
    `credits_cents`, `total_cents` and `balance_due_cents`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_invoice_version_on_manual_adjustment_line
    """
    world = setup_issued_invoice(
        keep_items=[],
        other_items=[{"label": "Old linens", "category": "LINENS", "footprint_linear_inches": 10, "volume_cft": 5}],
        lead_in=MOVE_START,
        packer_in="2026-06-15T17:30:00.000Z",
        lead_out=CHECK_OUT_2330,
        packer_out=None,
        complete_at=CHECK_OUT_2330,
        actual_loaded_volume_cft=2200,
    )
    invoice_id = world["invoice"]["id"]
    current = read_invoice(invoice_id)["version"]

    validate_error(
        api_client.create_invoice_line(
            create_invoice_line_payload(
                invoice_id, "MANUAL_ADJUSTMENT", 5000, "Packing material top-up", current - 1
            ),
            BILLING_ADMIN,
        ),
        ApiErrorId.ERR_STALE_INVOICE_VERSION.value,
    )
    line = validate_success(
        api_client.create_invoice_line(
            create_invoice_line_payload(
                invoice_id, "MANUAL_ADJUSTMENT", 5000, "Packing material top-up", current
            ),
            BILLING_ADMIN,
        ),
        expected_status=201,
    )
    assert_money(line["amount_cents"], 5000, "manual line amount_cents")
    invoice = read_invoice(invoice_id)
    assert_money(invoice["subtotal_cents"], EXPECTED_SUBTOTAL + 5000, "subtotal_cents")
    assert_money(invoice["coordination_fee_cents"], EXPECTED_FEE, "coordination_fee_cents")
    assert_money(invoice["total_cents"], EXPECTED_SUBTOTAL + 5000 + EXPECTED_FEE, "total_cents")


def test_the_ops_run_checkpoint_blocks_a_vendor_left_behind_by_a_reschedule():
    """PRD §3.8: "The ops-run checkpoint sweeps that up: a `SCHEDULED` assignment
    whose vendor's `coi_expires_on` is now earlier than its `service_date` moves to
    `COI_BLOCKED` and raises the vendor's `blocked_assignment_count`."
    PRD §3.10: "The ops-run checkpoint is the system's periodic sweep, available to
    the move manager and the platform administrator, and it does exactly three things
    in one request: it latches milestone lateness as described above, it expires
    authority records whose `effective_to_utc` the clock has reached, and it moves
    `SCHEDULED` vendor assignments whose certificate now expires before their service
    date into `COI_BLOCKED`."

    Design: Corner/cross_cutting_complexity_layers/ops_run_checkpoint_blocks_a_vendor_whose_coi_lapsed_behind_a_reschedule
    """
    world = setup_move_day_plan_confirmed(
        keep_items=[], other_items=[{"label": "Old linens", "category": "LINENS", "footprint_linear_inches": 10, "volume_cft": 5}]
    )
    eng_id = world["engagement_id"]
    vendor = new_vendor(
        "Bright Path Cleaning", "CLEANING", "2026-06-20", daily_capacity=3, holdback_pct=0.1
    )
    assignment = new_vendor_assignment(eng_id, vendor["id"], "CLEANING", "2026-06-15", 85000)
    accept_vendor_assignment(assignment["id"], vendor["id"])
    schedule_vendor_assignment(assignment["id"])

    validate_success(
        api_client.reschedule_move_day_plan(
            world["plan"]["id"],
            {"new_start_utc": "2026-06-29T14:00:00.000Z", "reason": "Elevator reservation moved"},
            MOVE_MANAGER,
        )
    )
    assert read_vendor_assignment(assignment["id"])["service_date"] == "2026-06-29"

    report = validate_success(api_client.ops_run(eng_id, MOVE_MANAGER))
    assert read_vendor_assignment(assignment["id"])["status"] == "COI_BLOCKED"
    assert report["vendor_assignments_blocked"] == 1

    validate_success(
        api_client.renew_vendor_coi(vendor["id"], {"coi_expires_on": "2026-08-31"}, PLATFORM_ADMIN)
    )
    assert read_vendor(vendor["id"])["coi_renewal_count"] == 1
    assert read_vendor_assignment(assignment["id"])["status"] == "SCHEDULED"
    assert read_vendor(vendor["id"])["blocked_assignment_count"] == 0


def test_denormalised_room_and_inventory_rollups_are_refreshed_on_write():
    """PRD §2.12: "Derived fields are reconciled eagerly. When an item's disposition
    changes, the affected rooms' loads and headroom, and the engagement's keep and
    haul volumes, are recomputed inside the same request."
    PRD §3.3: "Capacity is recomputed when a room is created, on every placement
    transition, and on every designation that touches the room."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_of_phase_and_rollups_after_item_delete_free_changes
    """
    world = setup_engagement(with_client_party=False, with_residence=True)
    eng_id = world["engagement_id"]
    first = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40)
    designate(first["id"], "KEEP", world["room"]["id"])

    room_b = new_room(
        world["residence"]["id"], room_type="BEDROOM", nominal_linear_inches=200, nominal_volume_cft=300
    )
    new_item(eng_id, label="Old linens", category="LINENS", footprint_linear_inches=10, volume_cft=5)

    residence = read_residence(world["residence"]["id"])
    assert residence["room_count"] == 2
    assert_two_dp(
        residence["total_effective_capacity_linear_inches"],
        room_effective_capacity(240, 0, approved=False) + room_effective_capacity(200, 0, approved=False),
        "total_effective_capacity_linear_inches",
    )
    assert_two_dp(
        read_room(room_b["id"])["effective_capacity_linear_inches"],
        room_effective_capacity(200, 0, approved=False),
        "second room capacity",
    )

    engagement = read_engagement(eng_id)
    assert engagement["inventory_item_count"] == 2
    assert_two_dp(engagement["total_inventory_volume_cft"], 45.00, "total_inventory_volume_cft")
    assert_two_dp(engagement["keep_volume_cft"], 40.00, "keep_volume_cft")
    assert engagement["phase"] == "ASSESSMENT"


def test_the_unpack_selector_prefers_essentials_and_falls_back_to_null():
    """PRD §3.9: "Candidates are ranked with essentials before standard, and within a
    priority by `scheduled_start_utc` ascending; ties are broken by `created_at`
    ascending, never by `id`. The first candidate under that ordering wins, and when
    the pool is empty the summary reports `next_unpack_session_id` as null."
    PRD §3.9: "The candidate pool is the engagement's sessions in status `SCHEDULED`
    or `REOPENED`; sessions that are `IN_PROGRESS` or `COMPLETED` are excluded."

    Design: Corner/cross_cutting_complexity_layers/unpack_selector_ranking_tie_break_and_empty_pool_fallback
    """
    world = setup_settle_in(settle_in_clock="2026-06-20T09:00:00.000Z")
    eng_id = world["engagement_id"]
    standard = new_unpack_session(eng_id, "2026-06-20T10:00:00.000Z", "STANDARD")
    essentials = new_unpack_session(eng_id, "2026-06-21T10:00:00.000Z", "ESSENTIALS")

    assert read_summary(eng_id)["next_unpack_session_id"] == essentials["id"], (
        "essentials outrank standard even when scheduled a day later"
    )

    start_unpack_session(essentials["id"])
    complete_unpack_session(essentials["id"])
    start_unpack_session(standard["id"])
    complete_unpack_session(standard["id"])

    assert read_summary(eng_id)["next_unpack_session_id"] is None
    assert read_unpack_session(essentials["id"])["status"] == "COMPLETED"
    assert read_unpack_session(standard["id"])["status"] == "COMPLETED"


def test_a_family_member_is_refused_by_the_role_list_before_any_authority_rung():
    """PRD §2.1: "A `FAMILY_MEMBER` may raise, escalate and withdraw disputes and may
    dispute an invoice, but may never approve a disposition."
    PRD §2.7: "The acting role appears in the endpoint's declared role list.
    Otherwise `ERR_ROLE_NOT_PERMITTED`, HTTP 403. Applies to every endpoint."

    Design: Corner/rbac/family_member_cannot_approve_a_sort_plan
    """
    world = setup_engagement()
    eng_id, party_id = world["engagement_id"], world["client_party"]["id"]
    item = new_item(eng_id, label="Old linens", category="LINENS", footprint_linear_inches=10, volume_cft=5)
    designate(item["id"], "DONATE")
    assessment = milestone_by_key(eng_id, "ASSESSMENT")
    get_success_data(
        api_client.complete_milestone(
            assessment["id"], {"completed_by_party_id": party_id}, MOVE_MANAGER
        )
    )
    plan = new_sort_plan(eng_id)
    submit_sort_plan(plan["id"])
    family = new_portal_party(
        eng_id, "FAMILY_MEMBER", display_name="Marcus Whitfield", email="marcus@example.com"
    )

    validate_error(
        api_client.approve_sort_plan(
            plan["id"],
            {"approved_by_party_id": family["id"]},
            make_family_member_headers(family["id"]),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )
    stored = read_sort_plan(plan["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["approved_by_party_id"] is None


def test_the_invoice_lifecycle_is_reserved_to_billing():
    """PRD §2.1: "When `X-User-Role` is `BILLING_ADMIN`, `X-User-ID` is again an
    opaque back-office operator identifier not tied to any persisted entity;
    `BILLING_ADMIN` is the only role that can move an invoice through its lifecycle."
    PRD §3.11: "Issuing the invoice is billing's act, is reachable from `DRAFT`, and
    requires the engagement's `MOVE_DAY` milestone to be `COMPLETE`."

    Design: Corner/rbac/move_manager_cannot_issue_or_finalize_an_invoice
    """
    world = setup_completed_move_day(
        keep_items=[],
        other_items=[{"label": "Old linens", "category": "LINENS", "footprint_linear_inches": 10, "volume_cft": 5}],
        lead_in=MOVE_START,
        packer_in="2026-06-15T17:30:00.000Z",
        lead_out=CHECK_OUT_2330,
        packer_out=None,
        complete_at=CHECK_OUT_2330,
        actual_loaded_volume_cft=2200,
    )
    invoice_id = world["invoice"]["id"]
    validate_error(
        api_client.issue_invoice(invoice_id, MOVE_MANAGER), ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
    )
    invoice = read_invoice(invoice_id)
    assert invoice["status"] == "DRAFT"
    assert invoice["issued_at_utc"] is None


def test_a_vendor_may_not_accept_an_order_addressed_to_another_vendor():
    """PRD §2.1: "When `X-User-Role` is `VENDOR`, `X-User-ID` is the `id` of the
    acting `Vendor`; ownership checks on any resource that references a vendor
    compare that resource's vendor foreign key to `X-User-ID`."
    PRD §2.7: "Entity-backed ownership holds: a `CLIENT` actor's `X-User-ID` equals
    the engagement's client id, a `FAMILY_MEMBER` or `POWER_OF_ATTORNEY` actor's
    `X-User-ID` equals the id of a portal party on the engagement, a `VENDOR` actor's
    `X-User-ID` equals the vendor id on the vendor assignment or on the consignment
    lot, and a `CREW_LEAD` actor's `X-User-ID` equals the id of a crew member holding
    a non-terminal crew assignment on the engagement's move-day plan. Otherwise
    `ERR_ACTOR_NOT_OWNER`, HTTP 403."

    Design: Corner/rbac/vendor_cannot_accept_another_vendors_assignment
    """
    world = setup_engagement(with_client_party=False)
    first = new_vendor("Bright Path Cleaning", "CLEANING", "2027-01-31", daily_capacity=3, holdback_pct=0.1)
    second = new_vendor("Sunrise Cleaning", "CLEANING", "2027-01-31", daily_capacity=3, holdback_pct=0.1)
    assignment = new_vendor_assignment(
        world["engagement_id"], first["id"], "CLEANING", "2026-06-16", 85000
    )

    validate_error(
        api_client.accept_vendor_assignment(assignment["id"], make_vendor_headers(second["id"])),
        ApiErrorId.ERR_ACTOR_NOT_OWNER.value,
    )
    stored = read_vendor_assignment(assignment["id"])
    assert stored["status"] == "REQUESTED"
    assert_money(stored["holdback_cents"], 0, "holdback_cents")


def test_every_hop_of_the_completion_cascade_is_visible_in_the_same_response():
    """PRD §2.12: "Derived fields are reconciled eagerly. When a crew assignment's
    hours change, the assignment's money and the engagement's labour rollups are
    recomputed inside the same request."
    PRD §2.4: "Where a mutation response returns a resource, the returned
    representation reflects the state after every side effect and every version
    increment that the request caused."

    Design: Corner/consistency_model/immediate_consistency_every_cascade_is_visible_in_the_same_response
    """
    world = setup_move_day_plan_confirmed(
        keep_items=[], other_items=[{"label": "Old linens", "category": "LINENS", "footprint_linear_inches": 10, "volume_cft": 5}]
    )
    from test_helpers import check_in, check_out, freeze_and_start

    freeze_and_start(world)
    check_in(world["lead_assignment"]["id"], MOVE_START)
    check_in(world["packer_assignment"]["id"], "2026-06-15T17:30:00.000Z")
    set_clock(CHECK_OUT_2330)
    check_out(world["lead_assignment"]["id"], CHECK_OUT_2330)

    body = validate_success(
        api_client.complete_move_day_plan(
            world["plan"]["id"], {"actual_loaded_volume_cft": 2200}, MOVE_MANAGER
        )
    )
    assert body["status"] == "COMPLETED"
    assert body["actual_trip_count"] == trip_count(2200, 1000, 1)

    engagement = read_engagement(world["engagement_id"])
    assert_money(engagement["accrued_labor_cents"], EXPECTED_LABOUR, "accrued_labor_cents")
    assert_hours(engagement["billing_hours_total"], 15.50, "billing_hours_total")
    assert engagement["phase"] == "SETTLE_IN"
