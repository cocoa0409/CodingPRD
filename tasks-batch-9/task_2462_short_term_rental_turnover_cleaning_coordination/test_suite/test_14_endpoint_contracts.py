"""Computed reads, conditional actions, the logical clock and the 404 code family."""

from datetime import datetime

import pytest

from test_helpers import (
    MISSING_UUID,
    TEST_USERS,
    ApiErrorId,
    create_booking_payload,
    create_issue_report_payload,
    create_property_payload,
    create_supply_line_payload,
    create_turnover_payload,
    dispatch_payload,
    fixtures as fx,
    make_cleaner_headers,
    make_property_owner_headers,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]


def _utc(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of its fractional-digit width."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def accepted_turn_with_four_lines(api):
    """T1 accepted by Cleaner C with two LINEN lines (par 6 + par 8) and two others."""
    return fx.world_scheduled(api, supply="four")


@pytest.fixture
def reported_finding(api):
    """A running clean carrying a MEDIUM 4,000-cent finding that stays in REPORTED."""
    world = fx.world_in_progress(api, supply=None)
    world["issue"] = validate_success(api.create_issue_report(
        create_issue_report_payload(
            world["t1"]["id"], issue_type="MAINTENANCE", severity="MEDIUM",
            description="shower valve drips continuously",
            estimated_cost_cents=4000),
        world["cleaner_headers"]), 201)
    return world


@pytest.fixture
def two_stays_on_one_unit(api):
    """P1 with OUT-1 departing 16:00Z and IN-1 arriving 21:00Z, and no turnover."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    b_out, b_in = fx.seed_stay_pair(api, p1["id"])
    return {"p1": p1, "b_out": b_out, "b_in": b_in}


@pytest.fixture
def empty_system(api):
    """Nothing but a pinned clock, so every id resolves to nothing at all."""
    fx.reset_clock(api)


@pytest.fixture
def bare_unit(api):
    """P1 registered with every optional field left at its declared default."""
    fx.reset_clock(api)
    return validate_success(
        api.create_property(create_property_payload(), ADMIN), 201)


# ─── endpoints ────────────────────────────────────────────────────────────

def test_01_the_pay_preview_mirrors_the_stored_line_without_persisting_anything(
        api, accepted_turn_with_four_lines):
    """Two previews return identical unpersisted breakdowns and move no ledger.

    PRD §3.8: "It returns the pay breakdown the turnover would settle at right
    now, shaped exactly like a pay line but unpersisted: its `id` and its
    `status` are both null." PRD §3.8: "While the turnover has not reached
    `COMPLETED` the preview uses the `PROVISIONAL` variant; once the turnover is
    `COMPLETED` it uses the `FINAL` variant." PRD §3.8: "Under the `PROVISIONAL`
    variant, `linen_units` is the estimate obtained by summing `par_qty` across
    the property's supply lines whose `category` is `LINEN` and whose `status` is
    `ACTIVE`; a `DISCONTINUED` linen line contributes nothing." PRD §3.8:
    "`net_cents` is `gross_cents` plus `bonus_cents`, less `penalty_cents`, plus
    `audit_adjustment_cents` — the last term being 0 until a quality audit folds
    one in."

    Design: Corner/endpoints/corner_ep_pay_preview_is_a_pure_computed_read_with_no_side_effects
    """
    world = accepted_turn_with_four_lines
    assert world["t1"]["turn_type"] == "SAME_DAY", (
        f"the rush premium depends on the turn type, "
        f"got {world['t1']['turn_type']}")

    stored = validate_success(
        api.list_pay_lines(COORDINATOR, {"turnover_id": world["t1"]["id"]}))[0]
    assert stored["status"] == "PROVISIONAL", (
        f"acceptance mints the line in PROVISIONAL, got {stored['status']}")
    assert stored["variant"] == "PROVISIONAL", (
        f"the stored variant must match its status, got {stored['variant']}")
    assert stored["assignment_id"] == world["a1"]["id"], (
        f"the line records the offer it was minted from, "
        f"got {stored['assignment_id']}")
    assert stored["net_cents"] == 12554, (
        f"the provisional net must be 11254 + 1300, got {stored['net_cents']}")

    preview = validate_success(
        api.get_pay_preview(world["t1"]["id"], world["cleaner_headers"]))
    assert preview["id"] is None, (
        f"a preview is unpersisted so it has no id, got {preview['id']}")
    assert preview["status"] is None, (
        f"a preview is unpersisted so it has no status, got {preview['status']}")
    assert preview["variant"] == "PROVISIONAL", (
        f"the turn has not reached COMPLETED, got {preview['variant']}")
    assert preview["size_base_cents"] == 8325, (
        f"the TWO_BR base is 8325, got {preview['size_base_cents']}")
    assert preview["rush_premium_cents"] == 1249, (
        f"the rush premium must be round_half_up(8325 * 0.15), "
        f"got {preview['rush_premium_cents']}")
    assert preview["tight_window_premium_cents"] == 0, (
        f"72 minutes of slack is not tight, "
        f"got {preview['tight_window_premium_cents']}")
    assert preview["cross_zone_premium_cents"] == 0, (
        f"the cleaner's home zone matches the unit's, "
        f"got {preview['cross_zone_premium_cents']}")
    assert preview["linen_units"] == 14, (
        f"the estimate sums par 6 and par 8 and excludes the CONSUMABLE and "
        f"WELCOME lines, got {preview['linen_units']}")
    assert preview["linen_adder_cents"] == 1680, (
        f"the adder must be 120 * 14, got {preview['linen_adder_cents']}")
    assert preview["gross_cents"] == 11254, (
        f"the gross must be 8325 + 1249 + 1680, got {preview['gross_cents']}")
    assert preview["on_time_bonus_cents"] == 800, (
        f"provisional lateness is forced to 0, "
        f"got {preview['on_time_bonus_cents']}")
    assert preview["photo_pass_bonus_cents"] == 500, (
        f"no rejection has been booked, "
        f"got {preview['photo_pass_bonus_cents']}")
    assert preview["bonus_cents"] == 1300, (
        f"the bonuses must sum to 800 + 500, got {preview['bonus_cents']}")
    assert preview["late_penalty_cents"] == 0
    assert preview["photo_penalty_cents"] == 0
    assert preview["penalty_cents"] == 0, (
        f"nothing is penalised yet, got {preview['penalty_cents']}")
    assert preview["audit_adjustment_cents"] == 0, (
        f"no audit has folded anything in, "
        f"got {preview['audit_adjustment_cents']}")
    assert preview["net_cents"] == stored["net_cents"] == 12554, (
        f"the preview must agree with the stored line, "
        f"got {preview['net_cents']} against {stored['net_cents']}")

    again = validate_success(api.get_pay_preview(world["t1"]["id"], COORDINATOR))
    assert again["net_cents"] == 12554, (
        f"a second read must be identical, got {again['net_cents']}")
    assert again["gross_cents"] == 11254, (
        f"a second read must be identical, got {again['gross_cents']}")
    assert again["linen_units"] == 14, (
        f"a second read must be identical, got {again['linen_units']}")

    after = fx.read_turnover(api, world)
    assert after["version"] == 3, (
        f"creation, offer and acceptance bump three times and two previews bump "
        f"nothing, got {after['version']}")
    assert after["status"] == "SCHEDULED", (
        f"a computed read moves no state, got {after['status']}")

    _, meta = validate_paginated(api.list_pay_lines(
        world["cleaner_headers"], {"cleaner_id": world["cc"]["id"]}))
    assert meta["total_count"] == 1, (
        f"the previews must not have persisted a second line, "
        f"got {meta['total_count']}")
    assert fx.read_cleaner(api, world)["pending_payout_cents"] == 12554, (
        f"the payout ledger must hold 12554, not 25108, got "
        f"{fx.read_cleaner(api, world)['pending_payout_cents']}")


def test_02_a_blocking_dispatch_fires_once_and_the_second_attempt_mints_nothing(
        api, reported_finding):
    """One dispatch crosses three aggregates, and repeating it is a state refusal.

    PRD §3.7: "Failing both conditions it is created in `REPORTED` with
    `owner_notified_at` left null." PRD §3.7: "Dispatching a vendor is available
    to a `Coordinator` and also to the `PropertyOwner` of the affected unit, and
    it advances the report from `REPORTED → DISPATCHED` or from `OWNER_NOTIFIED →
    DISPATCHED`; a report already `DISPATCHED` or `RESOLVED` draws
    `ERR_INVALID_ISSUE_STATE`." PRD §3.7: "A repair order is created in
    `DISPATCHED`, copying `issue_report_id` from the report it was raised against
    and `property_id` from that report." PRD §3.7: "When `blocks_checkin` is true
    and the associated turnover is non-terminal — that is, in any of
    `PENDING_ASSIGNMENT`, `SCHEDULED`, `IN_PROGRESS`, `AWAITING_VERIFICATION` or
    `REWORK_REQUIRED` — the turnover captures the status it is leaving into
    `pre_hold_status`, moves to `ON_HOLD`, records the new order in
    `blocking_repair_order_id`, and increments its `version` by 1; in a second hop
    the arriving stay's `checkin_gate` moves `OPEN → BLOCKED` with
    `guest_notice_code` `CHECKIN_DELAYED` and that booking's own `version`
    incremented by 1."

    Design: Corner/endpoints/corner_ep_issue_dispatch_is_a_conditional_action_that_is_not_repeatable
    """
    world = reported_finding
    assert world["p1"]["open_issue_count"] == 0, (
        f"a fresh unit carries no open findings, "
        f"got {world['p1']['open_issue_count']}")
    assert world["b_in"]["checkin_gate"] == "OPEN", (
        f"the arriving stay's gate starts OPEN, "
        f"got {world['b_in']['checkin_gate']}")
    assert world["b_in"]["guest_notice_code"] == "NONE", (
        f"no notice has been raised, "
        f"got {world['b_in']['guest_notice_code']}")
    assert world["t1"]["blocking_repair_order_id"] is None, (
        f"nothing is blocking the turn yet, "
        f"got {world['t1']['blocking_repair_order_id']}")

    issue = world["issue"]
    assert issue["status"] == "REPORTED", (
        f"4000 cents is below the 5000 floor and MEDIUM is below HIGH, "
        f"got {issue['status']}")
    assert issue["owner_notified_at"] is None, (
        f"the owner-notification cascade must not have fired, "
        f"got {issue['owner_notified_at']}")
    assert issue["property_id"] == world["p1"]["id"], (
        f"property_id is copied from the turnover, got {issue['property_id']}")
    assert issue["reported_by_cleaner_id"] == world["cc"]["id"], (
        f"the filer is read from X-User-ID, "
        f"got {issue['reported_by_cleaner_id']}")
    assert issue["guest_chargeable"] is False, (
        f"the chargeable flag defaults to false, got {issue['guest_chargeable']}")

    prop = validate_success(api.get_property(world["p1"]["id"], ADMIN))
    assert prop["open_issue_count"] == 1, (
        f"filing moved the derived counter, got {prop['open_issue_count']}")

    order = validate_success(api.dispatch_issue_report(
        issue["id"], dispatch_payload(
            vendor_name="Hill Country Plumbing",
            scheduled_at="2026-08-08T18:00:00Z", blocks_checkin=True),
        COORDINATOR), 201)
    assert order["status"] == "DISPATCHED", (
        f"a fresh order opens in DISPATCHED, got {order['status']}")
    assert order["blocks_checkin"] is True, (
        f"the supplied flag must be stored, got {order['blocks_checkin']}")
    assert order["issue_report_id"] == issue["id"], (
        f"the order copies the report it was raised against, "
        f"got {order['issue_report_id']}")
    assert order["property_id"] == world["p1"]["id"], (
        f"the order copies property_id from that report, "
        f"got {order['property_id']}")
    assert order["actual_cost_cents"] is None, (
        f"nothing has been invoiced yet, got {order['actual_cost_cents']}")
    assert order["completed_at"] is None, (
        f"the order is not closed yet, got {order['completed_at']}")

    dispatched = validate_success(api.get_issue_report(issue["id"], COORDINATOR))
    assert dispatched["status"] == "DISPATCHED", (
        f"the parent report must advance, got {dispatched['status']}")

    held = fx.read_turnover(api, world)
    assert held["status"] == "ON_HOLD", (
        f"a blocking order holds the non-terminal turnover, got {held['status']}")
    assert held["pre_hold_status"] == "IN_PROGRESS", (
        f"the status being left must be captured, "
        f"got {held['pre_hold_status']}")
    assert held["blocking_repair_order_id"] == order["id"], (
        f"the cross-aggregate stamp must name the order, "
        f"got {held['blocking_repair_order_id']}")

    arriving = validate_success(api.get_booking(world["b_in"]["id"], COORDINATOR))
    assert arriving["checkin_gate"] == "BLOCKED", (
        f"the second hop moves the gate, got {arriving['checkin_gate']}")
    assert arriving["guest_notice_code"] == "CHECKIN_DELAYED", (
        f"the guest is told the arrival is delayed, "
        f"got {arriving['guest_notice_code']}")
    assert arriving["status"] == "SCHEDULED", (
        f"the occupancy dimension is untouched, got {arriving['status']}")

    validate_error(api.dispatch_issue_report(
        issue["id"], dispatch_payload(
            vendor_name="Second Vendor", scheduled_at="2026-08-08T19:00:00Z"),
        COORDINATOR), ApiErrorId.ERR_INVALID_ISSUE_STATE, 409)

    _, meta = validate_paginated(api.list_repair_orders(
        COORDINATOR, {"issue_report_id": issue["id"]}))
    assert meta["total_count"] == 1, (
        f"the refused second dispatch must mint no order, "
        f"got {meta['total_count']}")

    owner = make_property_owner_headers(world["p1"]["id"])
    by_owner = validate_success(api.get_repair_order(order["id"], owner))
    assert by_owner["vendor_name"] == "Hill Country Plumbing", (
        f"the owner reads the vendor of record, got {by_owner['vendor_name']}")
    assert same_instant(by_owner["scheduled_at"], "2026-08-08T18:00:00Z"), (
        f"the owner reads the scheduled visit, got {by_owner['scheduled_at']}")


def test_03_every_server_minted_timestamp_reads_the_logical_clock(api):
    """A row minted before a jump keeps its instant while the next row reads the new one.

    PRD §2.4: "All temporal reasoning in this system — window boundaries, overlap
    buffers, lateness, audit eligibility, and every `..._at` timestamp the server
    writes itself — reads a single server-side logical UTC clock rather than the
    host's wall clock." PRD §2.4: "Before any client sets that clock it reads
    exactly `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock
    time." PRD §2.4: "Every resource also carries `created_at`, an ISO 8601 UTC
    timestamp with three fractional digits recording when the row was minted."
    PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
    timestamp refreshed on every mutation, and `version`, an integer that begins
    at 1 when the resource is created and increases by exactly 1 on each mutation
    that the specification declares to be a version-bumping change."

    Design: Corner/endpoints/corner_ep_clock_endpoint_returns_no_entity_and_drives_every_system_timestamp
    """
    fx.reset_clock(api, "2026-08-01T00:00:00Z")
    p1 = validate_success(api.create_property(create_property_payload(), ADMIN), 201)
    assert _utc(p1["created_at"]) == _utc("2026-08-01T00:00:00Z"), (
        f"created_at must be the logical clock reading, got {p1['created_at']}")
    assert _utc(p1["updated_at"]) == _utc("2026-08-01T00:00:00Z"), (
        f"a never-mutated row's updated_at matches its minting instant, "
        f"got {p1['updated_at']}")
    assert p1["version"] == 1, (
        f"a created row begins at version 1, got {p1['version']}")

    fx.reset_clock(api, "2026-08-05T09:30:00Z")
    p2 = validate_success(api.create_property(create_property_payload(
        code="AUS-102", name="Rainey Studio", zone_code="ZONE_A",
        size_tier="STUDIO", owner_contact_email="owner2@example.com"),
        ADMIN), 201)
    assert _utc(p2["created_at"]) == _utc("2026-08-05T09:30:00Z"), (
        f"the second row reads the moved clock rather than wall-clock time, "
        f"got {p2['created_at']}")

    reread = validate_success(api.get_property(p1["id"], ADMIN))
    assert _utc(reread["created_at"]) == _utc("2026-08-01T00:00:00Z"), (
        f"moving the clock is not a write to an existing row, "
        f"got {reread['created_at']}")
    assert _utc(reread["updated_at"]) == _utc("2026-08-01T00:00:00Z"), (
        f"moving the clock refreshes no updated_at, got {reread['updated_at']}")
    assert reread["version"] == 1, (
        f"moving the clock bumps no version, got {reread['version']}")


def test_04_both_booking_arms_of_a_turnover_are_resolved_independently(
        api, two_stays_on_one_unit):
    """Each arm answers the same 404, one booking in both slots is an interval fault.

    PRD §2.5: "6. **Body reference existence.** Every identifier referenced in a
    request body must resolve: `property_id`, `outgoing_booking_id`,
    `incoming_booking_id`, `cleaner_id`, each member of `exclude_cleaner_ids`,
    `turnover_id`, and the `supply_line_id` of each entry inside
    `restock_entries`." PRD §2.5: "19. **Interval ordering.** Across `POST
    /bookings`, `POST /bookings/{id}/schedule-change`, `POST
    /bookings/{id}/guest-review` and `POST /turnovers`: a booking's `checkout_at`
    must be strictly later than its `checkin_at`; a `LATE_CHECKOUT` request's
    `new_time_at` must be strictly later than the contracted `checkout_at`; an
    `EARLY_CHECKIN` request's `new_time_at` must be strictly earlier than the
    contracted `checkin_at` and at or after the affected turnover's
    `window_start_at`; the incoming booking's `checkin_at` must be at or after the
    outgoing booking's `checkout_at`; and a guest review requires the logical
    clock to be at or after that booking's `checkin_at`. Failure yields
    `ERR_INVALID_TIME_INTERVAL` (422)." PRD §2.4: "Most resources additionally
    carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and
    `version`, an integer that begins at 1 when the resource is created and
    increases by exactly 1 on each mutation that the specification declares to be
    a version-bumping change."

    Design: Corner/endpoints/corner_ep_turnover_creation_links_two_bookings_that_must_both_exist
    """
    world = two_stays_on_one_unit
    b_out, b_in = world["b_out"], world["b_in"]

    validate_error(api.create_turnover(
        create_turnover_payload(MISSING_UUID, b_in["id"]), COORDINATOR),
        ApiErrorId.ERR_BOOKING_NOT_FOUND, 404)
    validate_error(api.create_turnover(
        create_turnover_payload(b_out["id"], MISSING_UUID), COORDINATOR),
        ApiErrorId.ERR_BOOKING_NOT_FOUND, 404)
    validate_error(api.create_turnover(
        create_turnover_payload(b_out["id"], b_out["id"]), COORDINATOR),
        ApiErrorId.ERR_INVALID_TIME_INTERVAL, 422)

    t1 = validate_success(api.create_turnover(
        create_turnover_payload(b_out["id"], b_in["id"]), COORDINATOR), 201)
    assert t1["outgoing_booking_id"] == b_out["id"], (
        f"the departing arm must be stored, got {t1['outgoing_booking_id']}")
    assert t1["incoming_booking_id"] == b_in["id"], (
        f"the arriving arm must be stored, got {t1['incoming_booking_id']}")
    assert t1["turn_type"] == "SAME_DAY", (
        f"both stays sit on the same local date, got {t1['turn_type']}")

    by_out, out_meta = validate_paginated(
        api.list_turnovers(COORDINATOR, {"outgoing_booking_id": b_out["id"]}))
    assert out_meta["total_count"] == 1 and by_out[0]["id"] == t1["id"], (
        f"the link must be readable from the departing side, "
        f"got {out_meta['total_count']} rows")
    by_in, in_meta = validate_paginated(
        api.list_turnovers(COORDINATOR, {"incoming_booking_id": b_in["id"]}))
    assert in_meta["total_count"] == 1 and by_in[0]["id"] == t1["id"], (
        f"the same row must be readable from the arriving side, "
        f"got {in_meta['total_count']} rows")

    out_after = validate_success(api.get_booking(b_out["id"], COORDINATOR))
    assert out_after["status"] == "SCHEDULED", (
        f"linking is not a write to the departing stay, "
        f"got {out_after['status']}")
    assert out_after["version"] == b_out["version"] == 1, (
        f"the departing stay must stay at version 1, got {out_after['version']}")
    in_after = validate_success(api.get_booking(b_in["id"], COORDINATOR))
    assert in_after["checkin_gate"] == "OPEN", (
        f"linking is not a write to the arriving stay, "
        f"got {in_after['checkin_gate']}")
    assert in_after["version"] == b_in["version"] == 1, (
        f"the arriving stay must stay at version 1, got {in_after['version']}")


# ─── errors ───────────────────────────────────────────────────────────────

def test_05_all_twelve_not_found_codes_are_entity_specific(api, empty_system):
    """One unknown uuid drives twelve distinct 404 codes, never a generic one.

    PRD §2.5: "5. **Path existence, left to right.** On every endpoint carrying
    path parameters, each templated resource must exist, and the segments are
    resolved strictly left to right so that the outermost missing resource is the
    one reported. The applicable code is `ERR_PROPERTY_NOT_FOUND`,
    `ERR_CLEANER_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_TURNOVER_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_CHECKLIST_TASK_NOT_FOUND`,
    `ERR_SUPPLY_LINE_NOT_FOUND`, `ERR_ISSUE_REPORT_NOT_FOUND`,
    `ERR_REPAIR_ORDER_NOT_FOUND`, `ERR_QUALITY_AUDIT_NOT_FOUND`,
    `ERR_STOCK_MOVEMENT_NOT_FOUND` or `ERR_PAY_LINE_NOT_FOUND`, each at HTTP
    404." PRD §2.5: "A request is evaluated through the following gates, and the
    **first** gate that fails determines the response; no later gate may mask an
    earlier one." PRD §2.5: "15. **Photo evidence.** On `POST
    /checklist-tasks/{id}/submit`, `photo_uri` must be present when the task's
    `requires_photo` is true. Failure yields `ERR_PHOTO_REQUIRED` (422)."

    Design: Corner/errors/corner_err_each_of_the_ten_not_found_codes_is_triggerable_and_entity_specific
    """
    validate_error(api.get_property(MISSING_UUID, ADMIN),
                   ApiErrorId.ERR_PROPERTY_NOT_FOUND, 404)
    validate_error(api.get_cleaner(MISSING_UUID, ADMIN),
                   ApiErrorId.ERR_CLEANER_NOT_FOUND, 404)
    validate_error(api.get_booking(MISSING_UUID, COORDINATOR),
                   ApiErrorId.ERR_BOOKING_NOT_FOUND, 404)
    validate_error(api.get_turnover(MISSING_UUID, COORDINATOR),
                   ApiErrorId.ERR_TURNOVER_NOT_FOUND, 404)
    validate_error(api.get_assignment(MISSING_UUID, COORDINATOR),
                   ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND, 404)
    validate_error(api.get_supply_line(MISSING_UUID, COORDINATOR),
                   ApiErrorId.ERR_SUPPLY_LINE_NOT_FOUND, 404)
    validate_error(api.get_issue_report(MISSING_UUID, COORDINATOR),
                   ApiErrorId.ERR_ISSUE_REPORT_NOT_FOUND, 404)
    validate_error(api.get_repair_order(MISSING_UUID, COORDINATOR),
                   ApiErrorId.ERR_REPAIR_ORDER_NOT_FOUND, 404)
    validate_error(api.get_quality_audit(MISSING_UUID, AUDITOR),
                   ApiErrorId.ERR_QUALITY_AUDIT_NOT_FOUND, 404)
    validate_error(api.get_stock_movement(MISSING_UUID, COORDINATOR),
                   ApiErrorId.ERR_STOCK_MOVEMENT_NOT_FOUND, 404)
    validate_error(api.get_pay_line(MISSING_UUID, COORDINATOR),
                   ApiErrorId.ERR_PAY_LINE_NOT_FOUND, 404)

    # The checklist row has no single-resource read, so its code is driven
    # through the submit action — where existence still outranks the evidence
    # and state checks that sit at gates 12 and 15.
    validate_error(api.submit_checklist_task(
        MISSING_UUID, {"note": "nothing here"},
        make_cleaner_headers("cleaner-x")),
        ApiErrorId.ERR_CHECKLIST_TASK_NOT_FOUND, 404)


def test_06_one_bad_request_code_covers_six_structurally_different_faults(
        api, bare_unit):
    """A missing field, two enum faults, two range faults and a bad instant all read 400.

    PRD §2.5: "3. **Request shape.** On every endpoint: every required input
    field must be present, every enum-typed value must be one of the declared
    members, every integer must sit inside its declared bounds, every datetime
    must parse as ISO 8601 UTC, quantities and scores must sit inside their
    declared ranges, and `restock_entries` must be well formed. Failure yields
    `ERR_INVALID_REQUEST` (400)." PRD §3.2: "Reservations arrive from channel
    calendars and are imported by a `Coordinator`, who supplies the `property_id`
    of the unit, the channel's `external_ref` reservation reference (unique within
    that unit), the `guest_name` of record, and the contracted `checkin_at` and
    `checkout_at` instants, where the departure must be strictly later than the
    arrival." PRD §3.2: "Two optional inputs shape the work the stay will
    generate: `party_size`, the number of guests, defaulting to 1 within a range
    of 1 to 24; and `pet_stay`, a boolean defaulting to false that flags a pet in
    residence and, as §3.3 explains, inflates the cleaning requirement of the
    turnover that follows the stay." PRD §3.1: "Registering a rental unit
    requires an operator-facing `code` that must be unique across every property
    in the system, a display `name` for the unit, the `zone_code` naming the
    cleaning zone it sits in (an uppercase token between 1 and 16 characters, such
    as `ZONE_A`), the `size_tier` classifying the unit as `STUDIO`, `ONE_BR`,
    `TWO_BR` or `THREE_BR_PLUS`, and an `owner_contact_email` that becomes the
    notification target for damage findings."

    Design: Corner/errors/corner_err_invalid_request_covers_missing_enum_range_and_datetime_variants
    """
    p1 = bare_unit

    nameless = create_booking_payload(
        p1["id"], external_ref="NO-GUEST",
        checkin_at="2026-09-01T21:00:00Z", checkout_at="2026-09-03T16:00:00Z")
    nameless.pop("guest_name")
    validate_error(api.create_booking(nameless, COORDINATOR),
                   ApiErrorId.ERR_INVALID_REQUEST, 400)

    validate_error(api.create_property(create_property_payload(
        code="AUS-199", name="Bad Tier", zone_code="ZONE_A",
        size_tier="FOUR_BR", owner_contact_email="owner99@example.com"), ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST, 400)

    validate_error(api.create_booking(create_booking_payload(
        p1["id"], external_ref="PARTY-0", guest_name="Nobody",
        checkin_at="2026-09-05T21:00:00Z", checkout_at="2026-09-07T16:00:00Z",
        party_size=0), COORDINATOR), ApiErrorId.ERR_INVALID_REQUEST, 400)
    validate_error(api.create_booking(create_booking_payload(
        p1["id"], external_ref="PARTY-25", guest_name="Crowd",
        checkin_at="2026-09-09T21:00:00Z", checkout_at="2026-09-11T16:00:00Z",
        party_size=25), COORDINATOR), ApiErrorId.ERR_INVALID_REQUEST, 400)

    validate_error(api.create_booking(create_booking_payload(
        p1["id"], external_ref="BAD-DATE", guest_name="Timeless",
        checkin_at="next Tuesday", checkout_at="2026-09-15T16:00:00Z"),
        COORDINATOR), ApiErrorId.ERR_INVALID_REQUEST, 400)

    validate_error(api.create_supply_line(p1["id"], create_supply_line_payload(
        sku="BAD-CAT", name="Mystery Item", category="HARDWARE",
        unit_cost_cents=100, par_qty=2), COORDINATOR),
        ApiErrorId.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(
        api.list_bookings(COORDINATOR, {"property_id": p1["id"]}))
    assert meta["total_count"] == 0, (
        f"six rejected requests must have written nothing, "
        f"got {meta['total_count']}")
    _, line_meta = validate_paginated(
        api.list_property_supply_lines(p1["id"], COORDINATOR))
    assert line_meta["total_count"] == 0, (
        f"the rejected stock line must not exist, "
        f"got {line_meta['total_count']}")
