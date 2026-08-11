"""One entity's next state decided by another's, and the interval semantics of
the vendor day and the move-day freeze window."""

from test_helpers import (
    ApiErrorId,
    BILLING_ADMIN,
    FREEZE_INSTANT,
    MOVE_MANAGER,
    api_client,
    assert_exactly_one_line,
    assert_money,
    assert_same_instant,
    assert_vendor_payout_conservation,
    accept_vendor_assignment,
    confirm_assignment,
    create_invoice_line_payload,
    designate,
    drive_sort_plan_to_approved,
    get_success_data,
    invoice_lines,
    invoice_of,
    make_vendor_headers,
    milestone_by_key,
    new_engagement,
    new_item,
    new_move_day_plan,
    new_vendor,
    new_vendor_assignment,
    read_invoice,
    read_item,
    read_move_day_plan,
    read_sort_plan,
    read_vendor,
    read_vendor_assignment,
    reopen_milestone,
    schedule_vendor_assignment,
    set_clock,
    setup_engagement,
    setup_move_day_plan_confirmed,
    staff_lead_and_packer,
    validate_error,
    validate_success,
)


def _crewed_plan_whose_sort_plan_was_reopened():
    world = setup_engagement(with_residence=True)
    eng_id = world["engagement_id"]
    item = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40)
    designate(item["id"], "KEEP", world["room"]["id"])
    world["sort_plan"] = drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])
    plan = new_move_day_plan(eng_id)
    roster = staff_lead_and_packer(plan["id"])
    confirm_assignment(roster["lead_assignment"]["id"])
    confirm_assignment(roster["packer_assignment"]["id"])
    get_success_data(
        api_client.reopen_sort_plan(
            world["sort_plan"]["id"],
            {"reason": "Client changed her mind about the sideboard"},
            MOVE_MANAGER,
        )
    )
    world["plan"] = plan
    world.update(roster)
    return world


def test_plan_confirm_is_refused_while_the_sibling_sort_plan_sits_in_draft():
    """PRD §3.7: "The move manager confirms the plan from `CREWED` to `CONFIRMED`,
    which requires the engagement's sort plan to be `APPROVED` and recomputes
    `planned_trip_count` again."
    PRD §2.7: "The subject entity's current state is in the triggered transition's
    declared originating set. Otherwise `ERR_INVALID_STATE`, HTTP 409. Applies to
    every action endpoint that drives a state machine."

    Design: Difficulty/cross_entity_state_dependency/move_day_confirm_blocked_by_reopened_sort_plan
    """
    world = _crewed_plan_whose_sort_plan_was_reopened()
    assert read_move_day_plan(world["plan"]["id"])["status"] == "CREWED"

    validate_error(
        api_client.confirm_move_day_plan(world["plan"]["id"], MOVE_MANAGER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert read_move_day_plan(world["plan"]["id"])["status"] == "CREWED"


def test_the_refused_confirm_leaves_both_entities_where_they_were():
    """PRD §3.6: "From `APPROVED` the move manager may also reopen back to `DRAFT`,
    but only when the engagement's move-day plan, if one exists, is not `FROZEN`,
    `IN_PROGRESS` or `COMPLETED`."
    PRD §3.7: "It recomputes the plan's `crew_confirmed_count` — the number of the
    plan's assignments in status `CONFIRMED`, `CHECKED_IN` or `COMPLETED` — and then
    bubbles upward: when that count has reached `crew_min_required` and at least one
    of the confirmed assignments belongs to a crew member whose `crew_role` is
    `LEAD`, the plan itself transitions from `DRAFT` to `CREWED`, which recomputes
    `planned_trip_count` from the engagement's `keep_volume_cft`."

    Design: Difficulty/cross_entity_state_dependency/move_day_confirm_blocked_by_reopened_sort_plan
    """
    world = _crewed_plan_whose_sort_plan_was_reopened()
    api_client.confirm_move_day_plan(world["plan"]["id"], MOVE_MANAGER)

    assert read_sort_plan(world["sort_plan"]["id"])["status"] == "DRAFT"
    plan = read_move_day_plan(world["plan"]["id"])
    assert plan["status"] == "CREWED"
    assert plan["crew_confirmed_count"] == 2


def _accepted_cleaning_order_against_a_lapsed_certificate():
    world = setup_engagement(with_client_party=False)
    vendor = new_vendor(
        "Bright Path Cleaning", "CLEANING", "2026-06-10", daily_capacity=3, holdback_pct=0.1
    )
    assignment = new_vendor_assignment(
        world["engagement_id"], vendor["id"], "CLEANING", "2026-06-15", 85000
    )
    accept_vendor_assignment(assignment["id"], vendor["id"])
    return vendor, assignment


def test_scheduling_is_refused_while_the_certificate_expires_before_the_service_date():
    """PRD §3.8: "The certificate check compares two calendar dates, not instants:
    the vendor's `coi_expires_on` must not be earlier than the assignment's
    `service_date`, so a certificate expiring exactly *on* the service date is still
    valid, and a failure reports `ERR_VENDOR_COI_EXPIRED`."
    PRD §3.8: "The vendor accepts its own order — the acting `X-User-ID` must equal
    the assignment's `vendor_id` — moving it from `REQUESTED` to `ACCEPTED` and
    computing `holdback_cents` as the `quoted_cents` multiplied by the vendor's
    `holdback_pct` at accept time, rounded half-up to whole cents."

    Design: Difficulty/cross_entity_state_dependency/vendor_schedule_blocked_by_expired_coi_then_unblocked_by_renewal
    """
    vendor, assignment = _accepted_cleaning_order_against_a_lapsed_certificate()
    validate_error(
        api_client.schedule_vendor_assignment(assignment["id"], MOVE_MANAGER),
        ApiErrorId.ERR_VENDOR_COI_EXPIRED.value,
    )
    current = read_vendor_assignment(assignment["id"])
    assert current["status"] == "ACCEPTED"
    assert_money(current["holdback_cents"], 8500, "holdback_cents")


def test_renewing_the_certificate_lets_the_identical_schedule_succeed():
    """PRD §3.8: "Renewing the certificate takes a new `coi_expires_on`, raises
    `coi_renewal_count`, and cascades in the other direction: every `COI_BLOCKED`
    assignment whose `service_date` the renewed date now covers returns to
    `SCHEDULED`, lowering `blocked_assignment_count`. The platform administrator and
    the vendor itself may renew."

    Design: Difficulty/cross_entity_state_dependency/vendor_schedule_blocked_by_expired_coi_then_unblocked_by_renewal
    """
    vendor, assignment = _accepted_cleaning_order_against_a_lapsed_certificate()
    api_client.schedule_vendor_assignment(assignment["id"], MOVE_MANAGER)

    validate_success(
        api_client.renew_vendor_coi(
            vendor["id"], {"coi_expires_on": "2026-07-31"}, make_vendor_headers(vendor["id"])
        )
    )
    refreshed = read_vendor(vendor["id"])
    assert refreshed["coi_renewal_count"] == 1
    assert refreshed["coi_expires_on"] == "2026-07-31"

    validate_success(api_client.schedule_vendor_assignment(assignment["id"], MOVE_MANAGER))
    assert read_vendor_assignment(assignment["id"])["status"] == "SCHEDULED"


def _scheduled_cleaning_order_and_an_observed_invoice_version():
    world = setup_engagement(with_client_party=False)
    vendor = new_vendor(
        "Bright Path Cleaning", "CLEANING", "2027-01-31", daily_capacity=3, holdback_pct=0.1
    )
    assignment = new_vendor_assignment(
        world["engagement_id"], vendor["id"], "CLEANING", "2026-06-16", 85000
    )
    accept_vendor_assignment(assignment["id"], vendor["id"])
    schedule_vendor_assignment(assignment["id"])
    invoice = invoice_of(world["engagement_id"])
    set_clock("2026-06-16T09:00:00.000Z")
    return {
        "vendor": vendor,
        "assignment": assignment,
        "invoice": invoice,
        "observed_version": invoice["version"],
    }


def test_a_vendor_perform_bumps_the_invoice_version_and_defeats_the_manual_line():
    """PRD §3.8: "It stamps `performed_at_utc`, sets `paid_cents` to the interim
    payout — the `quoted_cents` less the `holdback_cents` — and appends a
    `VENDOR_PASSTHROUGH` ledger line for the full `quoted_cents` to the engagement's
    invoice, recomputing the invoice totals."
    PRD §2.10: "`POST /invoice-lines` requires `expected_invoice_version` carrying
    the client's last observed `version` of the target `Invoice`; a value that does
    not equal the invoice's current `version` is rejected with
    `ERR_STALE_INVOICE_VERSION` (HTTP 412)."

    Design: Difficulty/cross_entity_state_dependency/invoice_version_bumped_by_a_vendor_cascade_defeats_the_manual_adjustment
    """
    scenario = _scheduled_cleaning_order_and_an_observed_invoice_version()
    validate_success(
        api_client.perform_vendor_assignment(
            scenario["assignment"]["id"],
            {"performed_at_utc": "2026-06-16T09:00:00.000Z"},
            make_vendor_headers(scenario["vendor"]["id"]),
        )
    )
    performed = read_vendor_assignment(scenario["assignment"]["id"])
    assert performed["status"] == "PERFORMED"
    assert_money(performed["holdback_cents"], 8500, "holdback_cents")
    assert_money(performed["paid_cents"], 76500, "paid_cents")
    assert_vendor_payout_conservation(performed)

    invoice_id = scenario["invoice"]["id"]
    assert_exactly_one_line(invoice_lines(invoice_id), "VENDOR_PASSTHROUGH", 85000)
    invoice = read_invoice(invoice_id)
    assert invoice["version"] == scenario["observed_version"] + 1
    assert_money(invoice["subtotal_cents"], 85000, "subtotal_cents")

    validate_error(
        api_client.create_invoice_line(
            create_invoice_line_payload(
                invoice_id,
                "MANUAL_ADJUSTMENT",
                5000,
                "Packing material top-up",
                scenario["observed_version"],
            ),
            BILLING_ADMIN,
        ),
        ApiErrorId.ERR_STALE_INVOICE_VERSION.value,
    )
    assert_money(read_invoice(invoice_id)["subtotal_cents"], 85000, "subtotal after the loss")


def test_re_reading_the_invoice_lets_the_identical_manual_line_land():
    """PRD §2.4: "Where a mutation response returns a resource, the returned
    representation reflects the state after every side effect and every version
    increment that the request caused. A client that reads an entity and immediately
    uses the `version` it just observed in an optimistic-concurrency field must
    therefore succeed."
    PRD §3.11: "Billing may append a manual adjustment directly, supplying
    `expected_invoice_version` under the optimistic-concurrency rule of §2.10; that
    append raises the invoice's `version` by one and recomputes `subtotal_cents`,
    `credits_cents`, `total_cents` and `balance_due_cents`."

    Design: Difficulty/cross_entity_state_dependency/invoice_version_bumped_by_a_vendor_cascade_defeats_the_manual_adjustment
    """
    scenario = _scheduled_cleaning_order_and_an_observed_invoice_version()
    invoice_id = scenario["invoice"]["id"]
    get_success_data(
        api_client.perform_vendor_assignment(
            scenario["assignment"]["id"],
            {"performed_at_utc": "2026-06-16T09:00:00.000Z"},
            make_vendor_headers(scenario["vendor"]["id"]),
        )
    )
    fresh_version = read_invoice(invoice_id)["version"]
    assert fresh_version == scenario["observed_version"] + 1

    line = validate_success(
        api_client.create_invoice_line(
            create_invoice_line_payload(
                invoice_id,
                "MANUAL_ADJUSTMENT",
                5000,
                "Packing material top-up",
                fresh_version,
            ),
            BILLING_ADMIN,
        ),
        expected_status=201,
    )
    assert_money(line["amount_cents"], 5000, "manual line amount_cents")

    invoice = read_invoice(invoice_id)
    assert_money(invoice["subtotal_cents"], 90000, "subtotal_cents")
    assert_money(invoice["total_cents"], 90000, "total_cents")
    assert_money(
        invoice["coordination_fee_cents"], 0, "coordination_fee_cents before issue"
    )
    body = api_client.list_invoice_lines(BILLING_ADMIN, params={"invoice_id": invoice_id}).json()
    assert body["meta"]["total_count"] == 2


def _one_slot_vendor_with_three_accepted_orders():
    world = setup_engagement(with_client_party=False)
    eng_id = world["engagement_id"]
    vendor = new_vendor(
        "Bright Path Cleaning", "CLEANING", "2027-01-31", daily_capacity=1, holdback_pct=0.1
    )
    first = new_vendor_assignment(eng_id, vendor["id"], "CLEANING", "2026-06-16", 85000)
    second = new_vendor_assignment(eng_id, vendor["id"], "CLEANING", "2026-06-16", 60000)
    third = new_vendor_assignment(eng_id, vendor["id"], "CLEANING", "2026-06-17", 60000)
    for assignment in (first, second, third):
        accept_vendor_assignment(assignment["id"], vendor["id"])
    schedule_vendor_assignment(first["id"])
    return vendor, first, second, third


def test_the_vendor_day_is_a_closed_whole_day_count():
    """PRD §3.8: "The capacity check counts the vendor's assignments on that same
    calendar date whose status is `SCHEDULED`, `COI_BLOCKED`, `PERFORMED`,
    `SIGNED_OFF` or `PAID` and requires that count to be strictly below
    `daily_capacity`; orders still `REQUESTED` or `ACCEPTED`, and cancelled ones,
    consume no capacity. Capacity is whole-day granular, so two assignments on the
    same date collide once the ceiling is reached regardless of the hour, and the
    failure reports `ERR_VENDOR_DAILY_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/vendor_daily_capacity_whole_day_closed_count
    """
    vendor, first, second, third = _one_slot_vendor_with_three_accepted_orders()
    validate_error(
        api_client.schedule_vendor_assignment(second["id"], MOVE_MANAGER),
        ApiErrorId.ERR_VENDOR_DAILY_CAPACITY_EXCEEDED.value,
    )
    assert read_vendor_assignment(second["id"])["status"] == "ACCEPTED"
    assert read_vendor_assignment(first["id"])["status"] == "SCHEDULED"


def test_the_adjacent_calendar_date_does_not_collide_at_all():
    """PRD §2.7: "The vendor's count of assignments on that same `service_date`
    whose status is `SCHEDULED`, `COI_BLOCKED`, `PERFORMED`, `SIGNED_OFF` or `PAID`
    is strictly less than its `daily_capacity`. Otherwise
    `ERR_VENDOR_DAILY_CAPACITY_EXCEEDED`, HTTP 409."

    Design: Difficulty/resource_temporal_overlap/vendor_daily_capacity_whole_day_closed_count
    """
    vendor, first, second, third = _one_slot_vendor_with_three_accepted_orders()
    api_client.schedule_vendor_assignment(second["id"], MOVE_MANAGER)

    validate_success(api_client.schedule_vendor_assignment(third["id"], MOVE_MANAGER))
    assert read_vendor_assignment(third["id"])["status"] == "SCHEDULED"
    assert read_vendor_assignment(second["id"])["status"] == "ACCEPTED"


def test_the_freeze_window_excludes_the_instant_one_millisecond_early():
    """PRD §3.7: "`freeze_at_utc` is the scheduled start less seventy-two hours; the
    freeze window is entered when the clock is **at or after** that instant, so the
    boundary instant itself is already inside the window."
    PRD §2.7: "Freezing the move-day plan requires the logical clock to be at or
    after `freeze_at_utc`; the boundary instant itself is inside the window.
    Otherwise `ERR_FREEZE_WINDOW_NOT_ENTERED`, HTTP 409."

    Design: Difficulty/resource_temporal_overlap/move_day_freeze_window_half_open_instant_boundary
    """
    world = setup_move_day_plan_confirmed()
    set_clock("2026-06-12T13:59:59.999Z")
    validate_error(
        api_client.freeze_move_day_plan(world["plan"]["id"], MOVE_MANAGER),
        ApiErrorId.ERR_FREEZE_WINDOW_NOT_ENTERED.value,
    )
    assert_same_instant(
        read_move_day_plan(world["plan"]["id"])["freeze_at_utc"],
        FREEZE_INSTANT,
        "freeze_at_utc",
    )


def test_the_boundary_instant_freezes_the_plan_and_locks_designation():
    """PRD §2.7: "Once the logical clock is at or after that same instant, no
    inventory item may be designated or appraised. Otherwise
    `ERR_FREEZE_WINDOW_ENTERED`, HTTP 409. Applies to
    `POST /inventory-items/{id}/designate` and `POST /inventory-items/{id}/appraise`."
    PRD §3.6: "It is cascaded in when the move-day plan is frozen, it stamps
    `frozen_at_utc` from the logical clock, and from there no reopen is possible
    regardless of how much `reopen_count` budget remains; the attempt is refused
    with `ERR_SORT_PLAN_FROZEN`."

    Design: Difficulty/resource_temporal_overlap/move_day_freeze_window_half_open_instant_boundary
    """
    world = setup_move_day_plan_confirmed()
    set_clock(FREEZE_INSTANT)
    validate_success(api_client.freeze_move_day_plan(world["plan"]["id"], MOVE_MANAGER))

    assert read_move_day_plan(world["plan"]["id"])["status"] == "FROZEN"
    assert read_sort_plan(world["sort_plan"]["id"])["status"] == "FROZEN"

    # The freeze completes the PACK milestone (PRD §3.6), which would put the phase at
    # MOVE_DAY and make gate 5 (rung 31) the first failing rung on a designation. Gate
    # 6 is what this test is about, so the phase is walked back to SORT_PLAN through
    # two milestone reopens - each permitted by PRD §3.10 because no higher-sequence
    # milestone is COMPLETE - which leaves the frozen sort plan and the frozen
    # move-day plan exactly as they are.
    eng_id = world["engagement_id"]
    reopen_milestone(milestone_by_key(eng_id, "PACK")["id"], "Packing list reworked")
    reopen_milestone(milestone_by_key(eng_id, "SORT_PLAN")["id"], "Family asked to revisit")

    item_id = world["items"][0]["id"]
    error = validate_error(
        api_client.designate_item(item_id, {"disposition": "DONATE"}, MOVE_MANAGER),
        ApiErrorId.ERR_FREEZE_WINDOW_ENTERED.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_DISPOSITION_LOCKED.value
    assert read_item(item_id)["disposition"] == "KEEP"


def _one_slot_vendor_shared_by_two_engagements():
    world_a = setup_engagement(with_client_party=False)
    engagement_b = new_engagement(
        world_a["client"]["id"],
        home_tier="ONE_BED",
        scheduled_move_start_utc="2026-06-18T14:00:00.000Z",
    )
    vendor = new_vendor(
        "Bright Path Cleaning", "CLEANING", "2027-01-31", daily_capacity=1, holdback_pct=0.1
    )
    order_a = new_vendor_assignment(
        world_a["engagement_id"], vendor["id"], "CLEANING", "2026-06-16", 85000
    )
    order_b = new_vendor_assignment(
        engagement_b["id"], vendor["id"], "CLEANING", "2026-06-16", 60000
    )
    accept_vendor_assignment(order_a["id"], vendor["id"])
    accept_vendor_assignment(order_b["id"], vendor["id"])
    schedule_vendor_assignment(order_a["id"])
    return {
        "engagement_a": world_a["engagement_id"],
        "engagement_b": engagement_b["id"],
        "vendor": vendor,
        "order_a": order_a,
        "order_b": order_b,
    }


def test_the_occupied_resource_is_the_vendor_day_not_the_engagement():
    """PRD §2.7: "The vendor's count of assignments on that same `service_date`
    whose status is `SCHEDULED`, `COI_BLOCKED`, `PERFORMED`, `SIGNED_OFF` or `PAID`
    is strictly less than its `daily_capacity`. Otherwise
    `ERR_VENDOR_DAILY_CAPACITY_EXCEEDED`, HTTP 409."
    PRD §3.8: "Capacity is whole-day granular, so two assignments on the same date
    collide once the ceiling is reached regardless of the hour, and the failure
    reports `ERR_VENDOR_DAILY_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/vendor_daily_capacity_is_scoped_to_the_vendor_not_the_engagement
    """
    scenario = _one_slot_vendor_shared_by_two_engagements()
    assert scenario["order_a"]["engagement_id"] == scenario["engagement_a"]
    assert scenario["order_b"]["engagement_id"] == scenario["engagement_b"]

    validate_error(
        api_client.schedule_vendor_assignment(scenario["order_b"]["id"], MOVE_MANAGER),
        ApiErrorId.ERR_VENDOR_DAILY_CAPACITY_EXCEEDED.value,
    )
    assert read_vendor_assignment(scenario["order_b"]["id"])["status"] == "ACCEPTED"


def test_cancelling_the_first_engagements_order_frees_the_slot_for_the_second():
    """PRD §3.8: "Cancellation is reachable from `REQUESTED`, `ACCEPTED`,
    `SCHEDULED` and `COI_BLOCKED`, takes a `reason` stored as `cancel_reason`, and
    is open to the move manager and the vendor; cancelling from `SCHEDULED`
    additionally frees the slot it held on the vendor's day."

    Design: Difficulty/resource_temporal_overlap/vendor_daily_capacity_is_scoped_to_the_vendor_not_the_engagement
    """
    scenario = _one_slot_vendor_shared_by_two_engagements()
    api_client.schedule_vendor_assignment(scenario["order_b"]["id"], MOVE_MANAGER)

    validate_success(
        api_client.cancel_vendor_assignment(
            scenario["order_a"]["id"], {"reason": "Client A cancelled the deep clean"}, MOVE_MANAGER
        )
    )
    assert read_vendor_assignment(scenario["order_a"]["id"])["status"] == "CANCELLED"

    validate_success(api_client.schedule_vendor_assignment(scenario["order_b"]["id"], MOVE_MANAGER))
    assert read_vendor_assignment(scenario["order_b"]["id"])["status"] == "SCHEDULED"
    assert_money(
        read_vendor_assignment(scenario["order_a"]["id"])["holdback_cents"], 8500, "holdback A"
    )
    assert_money(
        read_vendor_assignment(scenario["order_b"]["id"])["holdback_cents"], 6000, "holdback B"
    )
