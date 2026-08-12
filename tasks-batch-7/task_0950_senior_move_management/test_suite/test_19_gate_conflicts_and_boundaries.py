"""Requests that violate two rungs at once, and the exact edges of three thresholds."""

from test_helpers import (
    ApiErrorId,
    CONSIGN_MIN_VALUE_CENTS,
    FREEZE_INSTANT,
    MOVE_MANAGER,
    MOVE_START,
    PACKAGE_BASE_CENTS,
    api_client,
    assert_exactly_one_line,
    assert_hours,
    assert_money,
    assert_no_line_of_type,
    assert_two_dp,
    check_in,
    create_crew_assignment_payload,
    designate,
    drive_sort_plan_to_approved,
    get_success_data,
    invoice_lines,
    labor_cents,
    make_power_of_attorney_headers,
    new_active_authority,
    new_crew_member,
    new_family_hold,
    new_item,
    new_move_day_plan,
    package_overage_cents,
    read_crew_assignment,
    read_crew_member,
    read_engagement,
    read_invoice,
    read_item,
    read_move_day_plan,
    read_party,
    read_room,
    set_clock,
    setup_completed_move_day,
    setup_engagement,
    trip_count,
    validate_error,
    validate_success,
)

ADDENDUM_ROOM = {"approved_addendum_linear_inches": 36}


def _held_item_that_would_also_overflow_the_room():
    world = setup_engagement(
        with_client_party=False, with_family_party=True, with_residence=True, room_kwargs=ADDENDUM_ROOM
    )
    eng_id = world["engagement_id"]
    first = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40)
    second = new_item(eng_id, label="Reading chair", footprint_linear_inches=90, volume_cft=35)
    third = new_item(
        eng_id, label="Mother's china cabinet", footprint_linear_inches=84, volume_cft=30
    )
    designate(first["id"], "KEEP", world["room"]["id"])
    designate(second["id"], "KEEP", world["room"]["id"])
    new_family_hold(third["id"], world["family_party"]["id"], reason="My mother promised this cabinet to me")
    world["third"] = third
    return world


def test_family_hold_gate_answers_before_the_room_capacity_gate():
    """PRD §2.7: "The item's `hold_state` is `NONE`, that is no dispute on the item
    is `OPEN` or `ESCALATED`. Otherwise `ERR_ITEM_UNDER_FAMILY_HOLD`, HTTP 409.
    Applies to `POST /inventory-items/{id}/designate`."
    PRD §2.6: "Every mutating endpoint — that is, every non-GET endpoint except
    `POST /_clock/set_current_utc`, `POST /clients`, `POST /crew-members` and
    `POST /vendors`, which have no engagement context — passes through twelve gates
    in this exact order, and the first gate that fails determines the returned
    `error_id`."

    Design: Difficulty/priority_pair_validation_conflict/family_hold_outranks_room_capacity_on_designate
    """
    world = _held_item_that_would_also_overflow_the_room()
    response = api_client.designate_item(
        world["third"]["id"],
        {"disposition": "KEEP", "assigned_room_id": world["room"]["id"]},
        MOVE_MANAGER,
    )
    error = validate_error(response, ApiErrorId.ERR_ITEM_UNDER_FAMILY_HOLD.value)
    assert error["error_id"] != ApiErrorId.ERR_ROOM_CAPACITY_EXCEEDED.value


def test_the_refused_designation_leaves_the_item_and_the_room_untouched():
    """PRD §2.7: "The target room's prospective `KEEP` linear load, including the
    item being designated, is less than or equal to its
    `effective_capacity_linear_inches`. The boundary is inclusive. Otherwise
    `ERR_ROOM_CAPACITY_EXCEEDED`, HTTP 422."
    PRD §3.5: "It is born `OPEN`, and creating it immediately sets the subject
    item's `hold_state` to `HELD`, which blocks re-designation, appraisal, staging
    and consignment membership for as long as the dispute is live."

    Design: Difficulty/priority_pair_validation_conflict/family_hold_outranks_room_capacity_on_designate
    """
    world = _held_item_that_would_also_overflow_the_room()
    api_client.designate_item(
        world["third"]["id"],
        {"disposition": "KEEP", "assigned_room_id": world["room"]["id"]},
        MOVE_MANAGER,
    )
    item = read_item(world["third"]["id"])
    assert item["disposition"] == "UNDECIDED"
    assert item["hold_state"] == "HELD"
    assert_two_dp(
        read_room(world["room"]["id"])["keep_load_linear_inches"],
        186.00,
        "keep_load_linear_inches",
    )


def _on_hold_engagement_with_an_under_ceilinged_poa():
    world = setup_engagement(
        with_client_party=False, with_poa_party=True, with_residence=True
    )
    eng_id = world["engagement_id"]
    new_active_authority(
        eng_id,
        world["poa_party"]["id"],
        authority_scope="DISPOSITION_ONLY",
        approval_ceiling_cents=100000,
    )
    world["item"] = new_item(
        eng_id,
        label="Walnut sideboard",
        footprint_linear_inches=96,
        volume_cft=40,
        appraised_value_cents=200000,
        appraisal_source="APPRAISED",
    )
    get_success_data(
        api_client.hold_engagement(eng_id, {"reason": "Family conference pending"}, MOVE_MANAGER)
    )
    return world


def test_engagement_hold_answers_before_the_authority_ceiling_check():
    """PRD §2.7: "The owning engagement's `status` is not `ON_HOLD`, except for
    `POST /engagements/{id}/resume` and `POST /engagements/{id}/cancel`. Otherwise
    `ERR_ENGAGEMENT_ON_HOLD`, HTTP 409."
    PRD §2.6: "3. **Engagement lifecycle.** The owning engagement's `status` must
    not be `CLOSED` or `CANCELLED`; `ON_HOLD` blocks every mutation except resuming
    and cancelling the engagement. Ladder rungs 22 through 24."

    Design: Difficulty/priority_pair_validation_conflict/engagement_hold_outranks_authority_ceiling_on_designate
    """
    world = _on_hold_engagement_with_an_under_ceilinged_poa()
    response = api_client.designate_item(
        world["item"]["id"],
        {
            "disposition": "KEEP",
            "assigned_room_id": world["room"]["id"],
            "acting_party_id": world["poa_party"]["id"],
        },
        make_power_of_attorney_headers(world["poa_party"]["id"]),
    )
    error = validate_error(response, ApiErrorId.ERR_ENGAGEMENT_ON_HOLD.value)
    assert error["error_id"] != ApiErrorId.ERR_AUTHORITY_CEILING_EXCEEDED.value


def test_the_held_engagement_records_its_hold_and_writes_no_disposition():
    """PRD §3.1: "Placing it `ON_HOLD` requires a `reason`, which is stored as
    `hold_reason`; `hold_count` rises by one and never falls, recording how often
    the engagement has been paused, and `version` rises by one."
    PRD §2.9: "Where several active records exist, the highest
    `approval_ceiling_cents` among them is the one used; `active_authority_ceiling_cents`
    on the portal seat is exactly that maximum, and reads 0 when no record of that
    seat is `ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/engagement_hold_outranks_authority_ceiling_on_designate
    """
    world = _on_hold_engagement_with_an_under_ceilinged_poa()
    api_client.designate_item(
        world["item"]["id"],
        {
            "disposition": "KEEP",
            "assigned_room_id": world["room"]["id"],
            "acting_party_id": world["poa_party"]["id"],
        },
        make_power_of_attorney_headers(world["poa_party"]["id"]),
    )
    engagement = read_engagement(world["engagement_id"])
    assert engagement["status"] == "ON_HOLD"
    assert engagement["hold_count"] == 1
    assert read_item(world["item"]["id"])["disposition"] == "UNDECIDED"
    assert read_party(world["poa_party"]["id"])["active_authority_ceiling_cents"] == 100000


def _draft_plan_inside_the_freeze_window_with_a_stale_version():
    world = setup_engagement(with_residence=True)
    eng_id = world["engagement_id"]
    item = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40)
    designate(item["id"], "KEEP", world["room"]["id"])
    drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])

    plan = new_move_day_plan(eng_id)
    stale_version = plan["version"]
    lead = new_crew_member("Tom Reyes", "LEAD", 9500)
    packer = new_crew_member("Nina Ortiz", "PACKER", 6800)
    first = get_success_data(
        api_client.create_crew_assignment(
            create_crew_assignment_payload(plan["id"], lead["id"], stale_version),
            MOVE_MANAGER,
        )
    )
    current_version = read_move_day_plan(plan["id"])["version"]
    set_clock(FREEZE_INSTANT)
    return {
        "plan": plan,
        "stale_version": stale_version,
        "current_version": current_version,
        "lead_assignment": first,
        "packer": packer,
    }


def test_freeze_window_answers_before_the_stale_plan_version_check():
    """PRD §2.7: "Once the logical clock is at or after the move-day plan's
    `freeze_at_utc`, the crew roster is locked: no crew assignment may be created,
    confirmed or re-crewed. Otherwise `ERR_FREEZE_WINDOW_ENTERED`, HTTP 409."
    PRD §2.10: "`POST /crew-assignments` requires `expected_move_day_plan_version`
    carrying the client's last observed `version` of the target `MoveDayPlan`; a
    value that does not equal the plan's current `version` is rejected with
    `ERR_STALE_MOVE_DAY_PLAN_VERSION` (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/freeze_window_outranks_the_stale_plan_version_on_crew_assignment_create
    """
    scenario = _draft_plan_inside_the_freeze_window_with_a_stale_version()
    assert scenario["current_version"] != scenario["stale_version"], (
        "the captured plan version must genuinely be stale"
    )

    response = api_client.create_crew_assignment(
        create_crew_assignment_payload(
            scenario["plan"]["id"], scenario["packer"]["id"], scenario["stale_version"]
        ),
        MOVE_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_FREEZE_WINDOW_ENTERED.value)
    assert response.status_code != 412


def test_the_refused_crew_create_writes_no_assignment_row():
    """PRD §3.7: "Staffing the plan creates a crew assignment naming the
    `move_day_plan_id`, the `crew_member_id` and `expected_move_day_plan_version`,
    and optionally a `replaces_assignment_id` pointing at the `NO_SHOW` slot it
    fills. Creating one raises the plan's `version` by one, transitions the replaced
    assignment from `NO_SHOW` to `REPLACED`, and raises the crew member's
    `assignment_count`."
    PRD §3.7: "`freeze_at_utc` is the scheduled start less seventy-two hours; the
    freeze window is entered when the clock is **at or after** that instant, so the
    boundary instant itself is already inside the window."

    Design: Difficulty/priority_pair_validation_conflict/freeze_window_outranks_the_stale_plan_version_on_crew_assignment_create
    """
    scenario = _draft_plan_inside_the_freeze_window_with_a_stale_version()
    api_client.create_crew_assignment(
        create_crew_assignment_payload(
            scenario["plan"]["id"], scenario["packer"]["id"], scenario["stale_version"]
        ),
        MOVE_MANAGER,
    )
    body = api_client.list_crew_assignments(
        MOVE_MANAGER, params={"move_day_plan_id": scenario["plan"]["id"]}
    ).json()
    assert body["meta"]["total_count"] == 1
    assert body["data"][0]["id"] == scenario["lead_assignment"]["id"]
    assert read_crew_member(scenario["packer"]["id"])["assignment_count"] == 0

    plan = read_move_day_plan(scenario["plan"]["id"])
    assert plan["version"] == scenario["current_version"]
    assert plan["status"] == "DRAFT"


def _two_items_on_either_side_of_the_consign_minimum():
    world = setup_engagement(with_client_party=False)
    eng_id = world["engagement_id"]
    world["on_edge"] = new_item(
        eng_id,
        label="Cut glass decanter",
        category="MISC",
        footprint_linear_inches=8,
        volume_cft=2,
        appraised_value_cents=CONSIGN_MIN_VALUE_CENTS,
        appraisal_source="APPRAISED",
    )
    world["under_edge"] = new_item(
        eng_id,
        label="Brass candlesticks",
        category="MISC",
        footprint_linear_inches=6,
        volume_cft=1,
        appraised_value_cents=CONSIGN_MIN_VALUE_CENTS - 1,
        appraisal_source="APPRAISED",
    )
    return world


def test_exactly_the_consign_minimum_is_consignable():
    """PRD §3.4: "Moving to `SELL` additionally requires `appraised_value_cents` of
    at least 15000 cents — exactly 15000 is consignable, one cent less is not, and
    the request is then refused with `ERR_ITEM_BELOW_CONSIGN_MINIMUM` — and it
    clears `assigned_room_id` to null."

    Design: Difficulty/boundary_precision_check/consign_minimum_inclusive_boundary_on_designate
    """
    world = _two_items_on_either_side_of_the_consign_minimum()
    validate_success(
        api_client.designate_item(world["on_edge"]["id"], {"disposition": "SELL"}, MOVE_MANAGER)
    )
    item = read_item(world["on_edge"]["id"])
    assert item["disposition"] == "SELL"
    assert item["assigned_room_id"] is None


def test_one_cent_below_the_consign_minimum_is_refused():
    """PRD §2.7: "An item designated `SELL` has `appraised_value_cents` greater than
    or equal to 15000 cents. The boundary is inclusive. Otherwise
    `ERR_ITEM_BELOW_CONSIGN_MINIMUM`, HTTP 422."
    PRD §3.4: "Cataloguing an item raises the engagement's `inventory_item_count`
    and `total_inventory_volume_cft` and raises the engagement's `version` by one."

    Design: Difficulty/boundary_precision_check/consign_minimum_inclusive_boundary_on_designate
    """
    world = _two_items_on_either_side_of_the_consign_minimum()
    validate_error(
        api_client.designate_item(world["under_edge"]["id"], {"disposition": "SELL"}, MOVE_MANAGER),
        ApiErrorId.ERR_ITEM_BELOW_CONSIGN_MINIMUM.value,
    )
    assert read_item(world["under_edge"]["id"])["disposition"] == "UNDECIDED"
    assert read_engagement(world["engagement_id"])["inventory_item_count"] == 2


def test_a_remainder_of_exactly_fifteen_percent_adds_no_extra_trip():
    """PRD §3.7: "The remainder is the volume less the full trips multiplied by the
    combined capacity, and one extra trip is added only when that remainder is
    **strictly greater** than fifteen percent of the combined capacity — a remainder
    of exactly fifteen percent is absorbed into the last trip and adds nothing."

    Design: Difficulty/boundary_precision_check/truck_partial_trip_threshold_strict_boundary
    """
    world = setup_completed_move_day(
        lead_in=MOVE_START,
        packer_in="2026-06-15T17:30:00.000Z",
        lead_out=None,
        packer_out=None,
        complete_at="2026-06-15T23:30:00.000Z",
        actual_loaded_volume_cft=2150,
    )
    plan = read_move_day_plan(world["plan"]["id"])
    assert plan["actual_trip_count"] == trip_count(2150, 1000, 1) == 2


def test_the_planned_variant_is_unchanged_by_the_actual_load():
    """PRD §3.7: "The planned variant, stored in `planned_trip_count`, is computed
    when the plan reaches `CREWED` and again at `CONFIRMED`, and uses the
    engagement's `keep_volume_cft`, that is only the items designated `KEEP`."
    PRD §3.7: "Alongside the cascade the supplied `actual_loaded_volume_cft` is
    stored and `actual_trip_count` is computed under the actual variant."

    Design: Difficulty/boundary_precision_check/truck_partial_trip_threshold_strict_boundary
    """
    world = setup_completed_move_day(
        lead_in=MOVE_START,
        packer_in="2026-06-15T17:30:00.000Z",
        lead_out=None,
        packer_out=None,
        complete_at="2026-06-15T23:30:00.000Z",
        actual_loaded_volume_cft=2150,
    )
    plan = read_move_day_plan(world["plan"]["id"])
    assert plan["planned_trip_count"] == trip_count(40, 1000, 1) == 1
    assert_two_dp(plan["actual_loaded_volume_cft"], 2150.00, "actual_loaded_volume_cft")
    assert plan["status"] == "COMPLETED"


def _package_studio_one_quarter_hour_over_the_allowance():
    return setup_completed_move_day(
        billing_mode="PACKAGE",
        package_tier="STUDIO",
        lead_in=MOVE_START,
        packer_in=MOVE_START,
        packer_out="2026-06-15T23:00:00.000Z",
        lead_out="2026-06-15T23:15:00.000Z",
        complete_at="2026-06-15T23:15:00.000Z",
        actual_loaded_volume_cft=900,
    )


def test_crew_overtime_accrues_even_though_the_package_ledger_never_sees_it():
    """PRD §3.7: "From `billing_hours` the money follows in three fixed steps.
    `applied_hours` applies the minimum call-out floor, and this is the first place
    the two pipelines part company: under `HOURLY` it is the greater of
    `billing_hours` and three hours, while under `PACKAGE` there is no floor at all
    and `applied_hours` simply equals `billing_hours`."

    Design: Difficulty/boundary_precision_check/package_overage_one_quarter_hour_above_the_studio_allowance
    """
    world = _package_studio_one_quarter_hour_over_the_allowance()
    lead = read_crew_assignment(world["lead_assignment"]["id"])
    packer = read_crew_assignment(world["packer_assignment"]["id"])

    assert_hours(lead["billing_hours"], 9.25, "lead billing_hours")
    assert_hours(lead["applied_hours"], 9.25, "lead applied_hours")
    assert_hours(lead["overtime_hours"], 1.25, "lead overtime_hours")
    assert_money(lead["labor_cents"], labor_cents(9.25, 9500), "lead labor_cents")
    assert_hours(packer["applied_hours"], 9.00, "packer applied_hours")
    assert_money(packer["labor_cents"], labor_cents(9.00, 6800), "packer labor_cents")

    engagement = read_engagement(world["engagement_id"])
    assert_hours(engagement["billing_hours_total"], 18.25, "billing_hours_total")
    assert_money(
        engagement["accrued_labor_cents"],
        labor_cents(9.25, 9500) + labor_cents(9.00, 6800),
        "accrued_labor_cents",
    )


def test_one_quarter_hour_above_the_studio_allowance_writes_a_tiny_overage_line():
    """PRD §3.11: "The boundary is strict in an unusual way: a `billing_hours_total`
    exactly equal to the allowance produces **no** `OVERAGE_LABOR` line at all, not
    a line of amount zero, and an `OVERAGE_LABOR` line is appended only when the
    computed overage charge is greater than zero."

    Design: Difficulty/boundary_precision_check/package_overage_one_quarter_hour_above_the_studio_allowance
    """
    world = _package_studio_one_quarter_hour_over_the_allowance()
    lines = invoice_lines(world["invoice"]["id"])

    assert_exactly_one_line(lines, "OVERAGE_LABOR", package_overage_cents(18.25, "STUDIO"))
    assert_exactly_one_line(lines, "PACKAGE_BASE", PACKAGE_BASE_CENTS["STUDIO"])
    assert_no_line_of_type(lines, "HOURLY_LABOR")
    assert len(lines) == 2, f"expected exactly two ledger lines, found {len(lines)}"

    assert_money(
        read_invoice(world["invoice"]["id"])["subtotal_cents"],
        PACKAGE_BASE_CENTS["STUDIO"] + package_overage_cents(18.25, "STUDIO"),
        "subtotal_cents",
    )
