"""Rejection precedence, uniqueness scopes, interval guards and conditional inputs."""

import pytest

from test_helpers import (
    MISSING_UUID,
    MISSING_UUID_ALT,
    TEST_USERS,
    ApiErrorId,
    assign_turnover_payload,
    build_user_headers,
    create_booking_payload,
    create_cleaner_payload,
    create_property_payload,
    create_quality_audit_payload,
    create_turnover_payload,
    fixtures as fx,
    make_quality_auditor_headers,
    restock_entry,
    review_task_payload,
    same_instant,
    schedule_change_payload,
    submit_task_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["coordinator_reviewer_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]
AUDITOR_TWO = TEST_USERS["quality_auditor_second_headers"]

# A request that carries neither X-User-Role nor X-User-ID, and one whose role
# token is not among the five declared roles.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
BOGUS_ROLE_HEADERS = build_user_headers("u-1", "SuperUser")


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def registered_unit(api):
    """P1 'AUS-101' alone, so a missing-id read has a live sibling to contrast."""
    fx.reset_clock(api)
    p1 = validate_success(api.create_property(create_property_payload(), ADMIN), 201)
    return p1


@pytest.fixture
def departing_stay(api):
    """P1 plus OUT-1 (16:00Z departure) and no turnover, isolating the stay guards."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    b1 = fx.seed_booking(api, p1["id"])
    return {"p1": p1, "b1": b1}


@pytest.fixture
def two_units_one_sku_one_ref(api):
    """P1 carrying LIN-SHEET-Q and OUT-1, plus an empty second unit P2."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    p2 = validate_success(api.create_property(create_property_payload(
        code="AUS-102", name="Second Unit", zone_code="ZONE_B",
        size_tier="STUDIO", owner_contact_email="owner2@example.com"), ADMIN), 201)
    sl1 = fx.seed_supply_line(
        api, p1["id"], sku="LIN-SHEET-Q", name="Queen Sheet Set",
        category="LINEN", unit_cost_cents=260, par_qty=6, unit="SET",
        initial_on_hand_qty=6)
    b1 = fx.seed_booking(api, p1["id"])
    return {"p1": p1, "p2": p2, "sl1": sl1, "b1": b1}


@pytest.fixture
def buffer_tight_pairs(api):
    """Two units whose arriving stays sit 30 and 31 minutes after the departure."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    p2 = validate_success(api.create_property(create_property_payload(
        code="AUS-102", name="Rainey Studio", zone_code="ZONE_A",
        size_tier="STUDIO", owner_contact_email="owner2@example.com",
        bedroom_count=1, bathroom_count=1, bed_count=1), ADMIN), 201)
    b1_out = fx.seed_booking(api, p1["id"])
    b1_in = fx.seed_booking(
        api, p1["id"], external_ref="IN-1", guest_name="Guest In 1",
        checkin_at="2026-08-08T16:30:00Z", checkout_at="2026-08-11T16:00:00Z")
    b2_out = fx.seed_booking(
        api, p2["id"], external_ref="OUT-2", guest_name="Guest Out 2",
        checkin_at="2026-08-05T21:00:00Z", checkout_at="2026-08-08T16:00:00Z")
    b2_in = fx.seed_booking(
        api, p2["id"], external_ref="IN-2", guest_name="Guest In 2",
        checkin_at="2026-08-08T16:31:00Z", checkout_at="2026-08-11T16:00:00Z")
    return {"p1": p1, "p2": p2, "b1_out": b1_out, "b1_in": b1_in,
            "b2_out": b2_out, "b2_in": b2_in}


@pytest.fixture
def early_departure_world(api):
    """T1 accepted, then the guest recorded out at 14:00Z, two hours early."""
    world = fx.world_scheduled(api, supply=None)
    fx.reset_clock(api, "2026-08-08T14:00:00Z")
    world["b_out"] = validate_success(api.checkout_booking(
        world["b_out"]["id"], {"actual_checkout_at": "2026-08-08T14:00:00Z"},
        COORDINATOR))
    return world


@pytest.fixture
def arriving_stay_underway(api):
    """IN-1 on P1 with the clock pushed past its check-in, so a review is legal."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    b_in = fx.seed_booking(
        api, p1["id"], external_ref="IN-1", guest_name="Guest In",
        checkin_at="2026-08-08T21:00:00Z", checkout_at="2026-08-11T16:00:00Z")
    fx.reset_clock(api, "2026-08-11T16:00:00Z")
    return {"p1": p1, "b_in": b_in}


@pytest.fixture
def verified_turn_at_finish(api):
    """Every row VERIFIED by coord-2 on a turn offered by coord-1, clock 20:00Z."""
    world = fx.world_all_verified(api, supply="pair")
    fx.reset_clock(api, "2026-08-08T20:00:00Z")
    return world


@pytest.fixture
def single_line_in_progress(api):
    """One LINEN line on P1 and a running clean with its four PENDING rows."""
    world = fx.build_world(api, supply=None)
    world["supply_lines"].append(fx.seed_supply_line(
        api, world["p1"]["id"], sku="LIN-SHEET-Q", name="Queen Sheet Set",
        category="LINEN", unit_cost_cents=260, par_qty=6, unit="SET",
        initial_on_hand_qty=6))
    fx.offer_turnover(api, world)
    fx.accept_offer(api, world)
    fx.start_clean(api, world)
    return world


@pytest.fixture
def single_line_all_submitted(api, single_line_in_progress):
    """The same clean with all four rows SUBMITTED and none reviewed, clock 19:00Z."""
    world = single_line_in_progress
    fx.submit_all_tasks(
        api, world,
        restock_entries=[restock_entry(world["supply_lines"][0]["id"], 1)])
    fx.reset_clock(api, "2026-08-08T19:00:00Z")
    return world


@pytest.fixture
def ineligible_candidates(api):
    """P1 needing skill 2, one under-skilled local cleaner and one far-zone one."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    c_low = validate_success(api.create_cleaner(create_cleaner_payload(
        name="Cleaner LOW", home_zone_code="ZONE_A", skill_level=1), ADMIN), 201)
    c_far = validate_success(api.create_cleaner(create_cleaner_payload(
        name="Cleaner FAR", home_zone_code="ZONE_D", skill_level=5), ADMIN), 201)
    b_out, b_in = fx.seed_stay_pair(api, p1["id"])
    t1 = fx.seed_turnover(api, b_out["id"], b_in["id"])
    return {"p1": p1, "c_low": c_low, "c_far": c_far, "t1": t1}


# ─── validations ──────────────────────────────────────────────────────────

def test_01_authentication_outranks_role_which_outranks_shape_and_existence(
        api, registered_unit):
    """The same unknown id answers 401, then 403, then 400, then only 404.

    PRD §2.5: "1. **Header authentication.** `X-User-Role` and `X-User-ID` must
    both be present and `X-User-Role` must be one of the five declared roles, on
    every endpoint. Failure yields `ERR_UNAUTHENTICATED` (401)." PRD §2.5: "2.
    **Role authorization.** The acting role must appear in the addressed
    endpoint's authorized-role list, on every endpoint. Failure yields
    `ERR_UNAUTHORIZED` (403)." PRD §2.5: "3. **Request shape.** On every
    endpoint: every required input field must be present, every enum-typed value
    must be one of the declared members, every integer must sit inside its
    declared bounds, every datetime must parse as ISO 8601 UTC, quantities and
    scores must sit inside their declared ranges, and `restock_entries` must be
    well formed. Failure yields `ERR_INVALID_REQUEST` (400)."

    Design: Corner/validations/corner_val_priority_1_to_5_ladder_auth_outranks_role_shape_and_existence
    """
    validate_error(api.get_property(MISSING_UUID, NO_AUTH_HEADERS),
                   ApiErrorId.ERR_UNAUTHENTICATED, 401)
    validate_error(api.get_property(MISSING_UUID, BOGUS_ROLE_HEADERS),
                   ApiErrorId.ERR_UNAUTHENTICATED, 401)

    nameless = {"home_zone_code": "ZONE_A", "skill_level": 3}
    validate_error(api.create_cleaner(nameless, COORDINATOR),
                   ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api.create_cleaner(nameless, ADMIN),
                   ApiErrorId.ERR_INVALID_REQUEST, 400)
    validate_error(api.create_cleaner(create_cleaner_payload(
        name="Cleaner E", home_zone_code="ZONE_A", skill_level=9), ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST, 400)

    validate_error(api.get_property(MISSING_UUID, ADMIN),
                   ApiErrorId.ERR_PROPERTY_NOT_FOUND, 404)

    live = validate_success(api.get_property(registered_unit["id"], ADMIN))
    assert live["code"] == "AUS-101", (
        f"the same endpoint must answer for a real id, so none of the refusals "
        f"above is an endpoint defect, got code {live['code']}")


def test_02_body_carried_ids_resolve_only_after_the_shape_is_accepted(api):
    """A missing body field is 400 while an unresolvable one is an entity 404.

    PRD §2.5: "6. **Body reference existence.** Every identifier referenced in a
    request body must resolve: `property_id`, `outgoing_booking_id`,
    `incoming_booking_id`, `cleaner_id`, each member of `exclude_cleaner_ids`,
    `turnover_id`, and the `supply_line_id` of each entry inside
    `restock_entries`." PRD §2.5: "3. **Request shape.** On every endpoint: every
    required input field must be present, every enum-typed value must be one of
    the declared members, every integer must sit inside its declared bounds,
    every datetime must parse as ISO 8601 UTC, quantities and scores must sit
    inside their declared ranges, and `restock_entries` must be well formed.
    Failure yields `ERR_INVALID_REQUEST` (400)."

    Design: Corner/validations/corner_val_body_referenced_ids_are_resolved_after_shape_validation
    """
    world = fx.build_world(api, supply=None)

    validate_error(
        api.create_turnover({"incoming_booking_id": world["b_in"]["id"]},
                            COORDINATOR),
        ApiErrorId.ERR_INVALID_REQUEST, 400)
    validate_error(
        api.create_booking(create_booking_payload(
            MISSING_UUID_ALT, external_ref="OUT-X", guest_name="Ghost",
            checkin_at="2026-08-20T21:00:00Z",
            checkout_at="2026-08-22T16:00:00Z"), COORDINATOR),
        ApiErrorId.ERR_PROPERTY_NOT_FOUND, 404)
    validate_error(
        api.create_turnover(create_turnover_payload(MISSING_UUID_ALT), COORDINATOR),
        ApiErrorId.ERR_BOOKING_NOT_FOUND, 404)
    validate_error(
        api.assign_turnover(world["t1"]["id"], assign_turnover_payload(
            world["t1"]["version"], MISSING_UUID_ALT), COORDINATOR),
        ApiErrorId.ERR_CLEANER_NOT_FOUND, 404)
    validate_error(
        api.create_quality_audit(
            create_quality_audit_payload(MISSING_UUID_ALT, 88), AUDITOR),
        ApiErrorId.ERR_TURNOVER_NOT_FOUND, 404)

    after = fx.read_turnover(api, world)
    assert after["status"] == "PENDING_ASSIGNMENT", (
        f"no refused call may move the turnover, got {after['status']}")
    assert after["version"] == 1, (
        f"no refused call may bump the turnover version, got {after['version']}")


def test_03_a_code_is_globally_unique_while_a_sku_and_a_ref_are_per_unit(
        api, two_units_one_sku_one_ref):
    """AUS-101 cannot repeat anywhere, yet LIN-SHEET-Q and OUT-1 can on P2.

    PRD §2.5: "28. **Uniqueness.** A property's `code` must be unique across all
    properties; a supply line's `sku` must be unique within its property; a
    booking's `external_ref` must be unique within its property." PRD §3.1:
    "Creating a line requires the `sku`, which must be unique within the
    property, a human-readable `name`, a `category` of `LINEN`, `CONSUMABLE` or
    `WELCOME`, the `unit_cost_cents` replacement cost per unit (never negative),
    and the `par_qty` target stock level per turn (never negative)."

    Design: Corner/validations/corner_val_duplicate_keys_rejected_globally_and_per_property
    """
    world = two_units_one_sku_one_ref

    validate_error(api.create_property(create_property_payload(
        code="AUS-101", name="Clone Of Barton", zone_code="ZONE_C",
        size_tier="ONE_BR", owner_contact_email="owner9@example.com"), ADMIN),
        ApiErrorId.ERR_DUPLICATE_RESOURCE_KEY, 409)
    validate_error(api.create_supply_line(world["p1"]["id"], {
        "sku": "LIN-SHEET-Q", "name": "Queen Sheet Set Duplicate",
        "category": "LINEN", "unit_cost_cents": 300, "par_qty": 4}, COORDINATOR),
        ApiErrorId.ERR_DUPLICATE_RESOURCE_KEY, 409)

    twin_line = validate_success(api.create_supply_line(world["p2"]["id"], {
        "sku": "LIN-SHEET-Q", "name": "Queen Sheet Set On P2",
        "category": "LINEN", "unit_cost_cents": 300, "par_qty": 4,
        "initial_on_hand_qty": 4}, COORDINATOR), 201)
    assert twin_line["sku"] == "LIN-SHEET-Q", (
        f"the sku scope is per property, got {twin_line['sku']}")
    assert twin_line["property_id"] == world["p2"]["id"], (
        f"the accepted twin must belong to P2, got {twin_line['property_id']}")

    validate_error(api.create_booking(create_booking_payload(
        world["p1"]["id"], external_ref="OUT-1", guest_name="Guest Clash",
        checkin_at="2026-09-05T21:00:00Z",
        checkout_at="2026-09-08T16:00:00Z"), COORDINATOR),
        ApiErrorId.ERR_DUPLICATE_RESOURCE_KEY, 409)

    twin_stay = validate_success(api.create_booking(create_booking_payload(
        world["p2"]["id"], external_ref="OUT-1", guest_name="Guest On P2",
        checkin_at="2026-08-05T21:00:00Z",
        checkout_at="2026-08-08T16:00:00Z"), COORDINATOR), 201)
    assert twin_stay["external_ref"] == "OUT-1", (
        f"the external_ref scope is per property, got {twin_stay['external_ref']}")

    _, meta = validate_paginated(
        api.list_property_supply_lines(world["p1"]["id"], COORDINATOR))
    assert meta["total_count"] == 1, (
        f"the refused duplicate must not have written a partial line, "
        f"got {meta['total_count']}")


def test_04_a_degenerate_interval_is_refused_at_each_of_its_four_boundaries(
        api, departing_stay):
    """Equal, reversed, non-extending and pre-arrival instants all draw one code.

    PRD §2.5: "19. **Interval ordering.** Across `POST /bookings`, `POST
    /bookings/{id}/schedule-change`, `POST /bookings/{id}/guest-review` and `POST
    /turnovers`: a booking's `checkout_at` must be strictly later than its
    `checkin_at`; a `LATE_CHECKOUT` request's `new_time_at` must be strictly
    later than the contracted `checkout_at`; an `EARLY_CHECKIN` request's
    `new_time_at` must be strictly earlier than the contracted `checkin_at` and
    at or after the affected turnover's `window_start_at`; the incoming booking's
    `checkin_at` must be at or after the outgoing booking's `checkout_at`; and a
    guest review requires the logical clock to be at or after that booking's
    `checkin_at`. Failure yields `ERR_INVALID_TIME_INTERVAL` (422)." PRD §3.2: "A
    cleanliness review carries a single `cleanliness_rating` from 1 to 5 and is
    accepted once the logical clock has reached the booking's `checkin_at`,
    whether or not the stay has ended; an earlier attempt is refused with
    `ERR_INVALID_TIME_INTERVAL`."

    Design: Corner/validations/corner_val_interval_ordering_rejects_reversed_equal_and_backdated_times
    """
    world = departing_stay

    validate_error(api.create_booking(create_booking_payload(
        world["p1"]["id"], external_ref="ZERO-1", guest_name="Zero Night",
        checkin_at="2026-09-01T16:00:00Z",
        checkout_at="2026-09-01T16:00:00Z"), COORDINATOR),
        ApiErrorId.ERR_INVALID_TIME_INTERVAL, 422)
    validate_error(api.create_booking(create_booking_payload(
        world["p1"]["id"], external_ref="REV-1", guest_name="Reversed",
        checkin_at="2026-09-05T16:00:00Z",
        checkout_at="2026-09-04T16:00:00Z"), COORDINATOR),
        ApiErrorId.ERR_INVALID_TIME_INTERVAL, 422)
    validate_error(api.schedule_change_booking(
        world["b1"]["id"],
        schedule_change_payload("LATE_CHECKOUT", "2026-08-08T16:00:00Z"),
        COORDINATOR), ApiErrorId.ERR_INVALID_TIME_INTERVAL, 422)
    validate_error(api.schedule_change_booking(
        world["b1"]["id"],
        schedule_change_payload("EARLY_CHECKIN", "2026-08-05T21:00:00Z"),
        COORDINATOR), ApiErrorId.ERR_INVALID_TIME_INTERVAL, 422)
    validate_error(api.submit_guest_review(
        world["b1"]["id"], {"cleanliness_rating": 5}, COORDINATOR),
        ApiErrorId.ERR_INVALID_TIME_INTERVAL, 422)

    granted = validate_success(api.schedule_change_booking(
        world["b1"]["id"],
        schedule_change_payload("LATE_CHECKOUT", "2026-08-08T16:01:00Z"),
        COORDINATOR))
    assert same_instant(granted["late_checkout_until_at"], "2026-08-08T16:01:00Z"), (
        f"one minute past the contracted departure is a legal extension, "
        f"got {granted['late_checkout_until_at']}")
    assert granted["status"] == "SCHEDULED", (
        f"a courtesy never moves the occupancy dimension, got {granted['status']}")
    assert granted["guest_notice_code"] == "LATE_CHECKOUT_GRANTED", (
        f"the notice code must record the courtesy, "
        f"got {granted['guest_notice_code']}")

    _, meta = validate_paginated(
        api.list_bookings(COORDINATOR, {"property_id": world["p1"]["id"]}))
    assert meta["total_count"] == 1, (
        f"neither refused reservation may be persisted, got {meta['total_count']}")


def test_05_a_late_checkout_of_exactly_four_hours_is_inside_the_ceiling(
        api, departing_stay):
    """240 minutes past the departure is granted and 241 is refused outright.

    PRD §2.5: "20. **Late-checkout ceiling.** On `POST
    /bookings/{id}/schedule-change`, a granted late checkout may not fall later
    than four hours — 240 minutes — after the contracted `checkout_at`. Failure
    yields `ERR_SCHEDULE_CHANGE_LIMIT_EXCEEDED` (422)." PRD §3.2: "A
    `LATE_CHECKOUT` request writes `late_checkout_until_at` and sets
    `guest_notice_code` to `LATE_CHECKOUT_GRANTED`; its `new_time_at` must be
    strictly later than the contracted `checkout_at` (else
    `ERR_INVALID_TIME_INTERVAL`) and may not fall more than 240 minutes past it
    (else `ERR_SCHEDULE_CHANGE_LIMIT_EXCEEDED`)." PRD §3.2: "A fresh reservation
    lands with `status` `SCHEDULED`, `checkin_gate` `OPEN` and
    `guest_notice_code` `NONE`, and is refused with `ERR_BOOKING_OVERLAP` if its
    half-open occupancy interval collides with another `SCHEDULED` or
    `CHECKED_OUT` stay on the same unit under the zero-buffer rule of §2.6."

    Design: Corner/validations/corner_val_late_checkout_ceiling_accepts_240_and_rejects_241
    """
    world = departing_stay
    assert world["b1"]["guest_notice_code"] == "NONE", (
        f"a fresh reservation carries no notice, "
        f"got {world['b1']['guest_notice_code']}")
    assert world["b1"]["late_checkout_until_at"] is None, (
        f"no courtesy has been granted yet, "
        f"got {world['b1']['late_checkout_until_at']}")

    validate_error(api.schedule_change_booking(
        world["b1"]["id"],
        schedule_change_payload("LATE_CHECKOUT", "2026-08-08T20:01:00Z"),
        COORDINATOR), ApiErrorId.ERR_SCHEDULE_CHANGE_LIMIT_EXCEEDED, 422)

    untouched = validate_success(api.get_booking(world["b1"]["id"], COORDINATOR))
    assert untouched["late_checkout_until_at"] is None, (
        f"the refused change must write nothing, "
        f"got {untouched['late_checkout_until_at']}")
    assert untouched["guest_notice_code"] == "NONE", (
        f"a refused courtesy must not notify the guest, "
        f"got {untouched['guest_notice_code']}")

    granted = validate_success(api.schedule_change_booking(
        world["b1"]["id"],
        schedule_change_payload("LATE_CHECKOUT", "2026-08-08T20:00:00Z"),
        COORDINATOR))
    assert same_instant(granted["late_checkout_until_at"], "2026-08-08T20:00:00Z"), (
        f"exactly 240 minutes past 16:00Z is inside the ceiling, "
        f"got {granted['late_checkout_until_at']}")
    assert granted["guest_notice_code"] == "LATE_CHECKOUT_GRANTED", (
        f"the granted courtesy must set the notice, "
        f"got {granted['guest_notice_code']}")
    assert granted["status"] == "SCHEDULED", (
        f"the occupancy dimension stays put, got {granted['status']}")


def test_06_a_zero_length_window_is_refused_and_no_override_rescues_it(
        api, buffer_tight_pairs):
    """The 30-minute arrival collapses the window, while 31 minutes survives.

    PRD §2.5: "22. **Positive window.** On `POST /turnovers` and `POST
    /bookings/{id}/schedule-change`, the derived cleaning window must be strictly
    positive. Failure yields `ERR_CLEANING_WINDOW_NON_POSITIVE` (422)." PRD
    §2.5: "23. **Window sufficiency at creation.** On `POST /turnovers`,
    `window_minutes` must be greater than or equal to `required_minutes` unless
    an `override_reason` is supplied. Failure yields
    `ERR_WINDOW_OVERRIDE_REQUIRED` (422)." PRD §3.3: "With an arriving stay, the
    effective arrival instant is the *earliest* of the two candidate arrival
    instants that are not null — the contracted `checkin_at` and the granted
    `early_checkin_at` — and `window_end_at` is that effective arrival instant
    pulled back by a 30-minute inspection buffer, so that a supervisor always has
    half an hour between the cleaner finishing and the guest arriving."

    Design: Corner/validations/corner_val_zero_length_window_is_refused_while_one_minute_survives_with_override
    """
    world = buffer_tight_pairs

    validate_error(api.create_turnover(create_turnover_payload(
        world["b1_out"]["id"], world["b1_in"]["id"]), COORDINATOR),
        ApiErrorId.ERR_CLEANING_WINDOW_NON_POSITIVE, 422)
    validate_error(api.create_turnover(create_turnover_payload(
        world["b1_out"]["id"], world["b1_in"]["id"],
        override_reason="owner insists on a same-slot turn"), COORDINATOR),
        ApiErrorId.ERR_CLEANING_WINDOW_NON_POSITIVE, 422)

    validate_error(api.create_turnover(create_turnover_payload(
        world["b2_out"]["id"], world["b2_in"]["id"]), COORDINATOR),
        ApiErrorId.ERR_WINDOW_OVERRIDE_REQUIRED, 422)

    t2 = validate_success(api.create_turnover(create_turnover_payload(
        world["b2_out"]["id"], world["b2_in"]["id"],
        override_reason="impossible turn accepted by ops with a double crew"),
        COORDINATOR), 201)
    assert same_instant(t2["window_start_at"], "2026-08-08T16:00:00Z"), (
        f"the window opens at the contracted departure, "
        f"got {t2['window_start_at']}")
    assert same_instant(t2["window_end_at"], "2026-08-08T16:01:00Z"), (
        f"16:31Z pulled back 30 minutes is 16:01Z, got {t2['window_end_at']}")
    assert t2["window_minutes"] == 1, (
        f"the surviving window is one minute, got {t2['window_minutes']}")
    assert t2["required_minutes"] == 110, (
        f"a STUDIO with 1 bathroom and 1 bed requires 90 + 12 + 8 minutes, "
        f"got {t2['required_minutes']}")
    assert t2["slack_minutes"] == -109, (
        f"slack must be 1 - 110, got {t2['slack_minutes']}")
    assert t2["is_tight"] is True, (
        f"negative slack is far below 45 minutes, got {t2['is_tight']}")
    assert t2["escalation_required"] is True, (
        f"negative slack raises escalation at creation, "
        f"got {t2['escalation_required']}")
    assert t2["status"] == "PENDING_ASSIGNMENT", (
        f"an overridden turnover is still a normal one, got {t2['status']}")

    _, meta = validate_paginated(
        api.list_turnovers(COORDINATOR, {"property_id": world["p1"]["id"]}))
    assert meta["total_count"] == 0, (
        f"the collapsed pair must have produced no row, got {meta['total_count']}")


def test_07_a_courtesy_that_compresses_a_live_turn_needs_a_written_reason(
        api):
    """210 minutes is granted freely, 180 only with a reason, and never voided.

    PRD §2.5: "24. **Window sufficiency at schedule change.** On `POST
    /bookings/{id}/schedule-change`, a change that would compress an existing
    turnover's window below `required_minutes` is refused unless an
    `override_reason` is supplied. Failure yields
    `ERR_SCHEDULE_CHANGE_BLOCKS_TURN` (409)." PRD §3.2: "Either variant then
    re-derives the affected non-terminal turnover's window and increments that
    turnover's `version` by 1." PRD §3.2: "Unlike a recorded departure, a
    schedule change is held to the strict standard: a derived window that is not
    strictly positive draws `ERR_CLEANING_WINDOW_NON_POSITIVE`, and a window
    compressed below `required_minutes` without an `override_reason` draws
    `ERR_SCHEDULE_CHANGE_BLOCKS_TURN`."

    Design: Corner/validations/corner_val_schedule_change_that_compresses_a_live_turn_needs_an_override
    """
    world = fx.build_world(api, supply=None)
    assert world["t1"]["window_minutes"] == 270, (
        f"the opening window runs 16:00Z to 20:30Z, "
        f"got {world['t1']['window_minutes']}")
    assert world["t1"]["required_minutes"] == 198, (
        f"the TWO_BR requirement is 150 + 24 + 24, "
        f"got {world['t1']['required_minutes']}")
    assert world["t1"]["version"] == 1, (
        f"a fresh turnover is at version 1, got {world['t1']['version']}")

    first = validate_success(api.schedule_change_booking(
        world["b_out"]["id"],
        schedule_change_payload("LATE_CHECKOUT", "2026-08-08T17:00:00Z"),
        COORDINATOR))
    assert same_instant(first["late_checkout_until_at"], "2026-08-08T17:00:00Z")
    assert first["guest_notice_code"] == "LATE_CHECKOUT_GRANTED", (
        f"the courtesy is granted with no reason needed, "
        f"got {first['guest_notice_code']}")

    after_first = fx.read_turnover(api, world)
    assert same_instant(after_first["window_start_at"], "2026-08-08T17:00:00Z"), (
        f"the granted extension becomes the latest opening candidate, "
        f"got {after_first['window_start_at']}")
    assert after_first["window_minutes"] == 210, (
        f"17:00Z to 20:30Z is 210 minutes, still at least 198, "
        f"got {after_first['window_minutes']}")
    assert after_first["slack_minutes"] == 12, (
        f"slack must be 210 - 198, got {after_first['slack_minutes']}")
    assert after_first["version"] == 2, (
        f"the propagated re-derivation bumps the turnover once, "
        f"got {after_first['version']}")

    validate_error(api.schedule_change_booking(
        world["b_out"]["id"],
        schedule_change_payload("LATE_CHECKOUT", "2026-08-08T17:30:00Z"),
        COORDINATOR), ApiErrorId.ERR_SCHEDULE_CHANGE_BLOCKS_TURN, 409)

    after_refusal = fx.read_turnover(api, world)
    assert after_refusal["window_minutes"] == 210, (
        f"the refused change must not touch the window, "
        f"got {after_refusal['window_minutes']}")
    assert after_refusal["version"] == 2, (
        f"the refused change must not bump the version, "
        f"got {after_refusal['version']}")

    forced = validate_success(api.schedule_change_booking(
        world["b_out"]["id"],
        schedule_change_payload("LATE_CHECKOUT", "2026-08-08T17:30:00Z",
                                override_reason="VIP guest, crew doubled"),
        COORDINATOR))
    assert same_instant(forced["late_checkout_until_at"], "2026-08-08T17:30:00Z")

    after_override = fx.read_turnover(api, world)
    assert same_instant(after_override["window_start_at"], "2026-08-08T17:30:00Z")
    assert after_override["window_minutes"] == 180, (
        f"17:30Z to 20:30Z is 180 minutes, got {after_override['window_minutes']}")
    assert after_override["slack_minutes"] == -18, (
        f"slack must be 180 - 198, got {after_override['slack_minutes']}")
    assert after_override["is_tight"] is True
    assert after_override["escalation_required"] is True, (
        f"a compressed window raises escalation, "
        f"got {after_override['escalation_required']}")
    assert after_override["version"] == 3, (
        f"the second accepted change bumps the turnover again, "
        f"got {after_override['version']}")
    assert after_override["status"] == "PENDING_ASSIGNMENT", (
        f"the turnover is compressed rather than voided, "
        f"got {after_override['status']}")


def test_08_an_early_departure_never_pulls_the_start_gate_forward(
        api, early_departure_world):
    """Starting is refused at 14:00Z and 15:59Z and accepted at exactly 16:00Z.

    PRD §2.5: "26. **Start not before the window opens.** On `POST
    /turnovers/{id}/start`, the logical clock must be at or after the turnover's
    `window_start_at`. Failure yields `ERR_TOO_EARLY_TO_START` (409)." PRD §3.3:
    "Its opening instant, `window_start_at`, is the latest of three candidate
    instants on the departing stay, considering only those that are not null: the
    contracted `checkout_at`, the granted `late_checkout_until_at`, and the
    recorded `actual_checkout_at`." PRD §3.2: "This is the one boundary movement
    that **never refuses**: every non-terminal turnover whose departing stay is
    this booking re-derives `window_start_at`, `window_end_at`,
    `window_minutes`, `slack_minutes`, `turn_type` and `is_tight`, and has its
    `version` incremented by 1, but a window that would come out non-positive is
    clamped to 0 rather than rejected."

    Design: Corner/validations/corner_val_start_is_refused_before_the_window_opens_and_allowed_exactly_on_it
    """
    world = early_departure_world
    assert world["b_out"]["status"] == "CHECKED_OUT", (
        f"the departure must be recorded, got {world['b_out']['status']}")
    assert same_instant(world["b_out"]["actual_checkout_at"], "2026-08-08T14:00:00Z"), (
        f"the early departure instant must be stored, "
        f"got {world['b_out']['actual_checkout_at']}")

    before = fx.read_turnover(api, world)
    assert same_instant(before["window_start_at"], "2026-08-08T16:00:00Z"), (
        f"14:00Z is earlier than the contracted 16:00Z, so the latest candidate "
        f"still wins, got {before['window_start_at']}")
    assert before["window_minutes"] == 270, (
        f"an early departure never widens the window, "
        f"got {before['window_minutes']}")
    assert before["status"] == "SCHEDULED", (
        f"acceptance moved the turnover out of PENDING_ASSIGNMENT, "
        f"got {before['status']}")
    assert before["version"] == 4, (
        f"creation, offer, acceptance and the recorded departure each bump once, "
        f"got {before['version']}")

    validate_error(api.start_turnover(before["id"], {}, world["cleaner_headers"]),
                   ApiErrorId.ERR_TOO_EARLY_TO_START, 409)

    fx.reset_clock(api, "2026-08-08T15:59:00Z")
    validate_error(api.start_turnover(before["id"], {}, world["cleaner_headers"]),
                   ApiErrorId.ERR_TOO_EARLY_TO_START, 409)

    fx.reset_clock(api, "2026-08-08T16:00:00Z")
    started = validate_success(
        api.start_turnover(before["id"], {}, world["cleaner_headers"]))
    assert started["status"] == "IN_PROGRESS", (
        f"the clock standing exactly on window_start_at is enough, "
        f"got {started['status']}")
    assert same_instant(started["started_at"], "2026-08-08T16:00:00Z"), (
        f"started_at is the logical clock reading, got {started['started_at']}")
    assert started["checklist_task_count"] == 4, (
        f"a TWO_BR unit materialises four rows, "
        f"got {started['checklist_task_count']}")


def test_09_a_stay_accepts_exactly_one_cleanliness_review_ever(
        api, arriving_stay_underway):
    """A 6 is a shape failure, the first 4 lands, and every later rating is 409.

    PRD §2.5: "31. **One guest review per stay.** On `POST
    /bookings/{id}/guest-review`, a booking accepts exactly one cleanliness
    review. Failure yields `ERR_GUEST_REVIEW_ALREADY_SUBMITTED` (409)." PRD
    §3.2: "The rating and its `cleanliness_rated_at` logical-clock reading are
    recorded, and a booking accepts exactly one such review — a second attempt
    is refused with `ERR_GUEST_REVIEW_ALREADY_SUBMITTED`." PRD §2.5: "3.
    **Request shape.** On every endpoint: every required input field must be
    present, every enum-typed value must be one of the declared members, every
    integer must sit inside its declared bounds, every datetime must parse as ISO
    8601 UTC, quantities and scores must sit inside their declared ranges, and
    `restock_entries` must be well formed. Failure yields `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/validations/corner_val_booking_accepts_exactly_one_guest_cleanliness_review
    """
    world = arriving_stay_underway
    assert world["b_in"]["cleanliness_rating"] is None, (
        f"a fresh reservation carries no rating, "
        f"got {world['b_in']['cleanliness_rating']}")
    assert world["b_in"]["cleanliness_rated_at"] is None, (
        f"a fresh reservation carries no rating instant, "
        f"got {world['b_in']['cleanliness_rated_at']}")

    validate_error(api.submit_guest_review(
        world["b_in"]["id"], {"cleanliness_rating": 6}, COORDINATOR),
        ApiErrorId.ERR_INVALID_REQUEST, 400)

    rated = validate_success(api.submit_guest_review(
        world["b_in"]["id"], {"cleanliness_rating": 4}, COORDINATOR))
    assert rated["cleanliness_rating"] == 4, (
        f"the first review must be recorded, got {rated['cleanliness_rating']}")
    assert same_instant(rated["cleanliness_rated_at"], "2026-08-11T16:00:00Z"), (
        f"cleanliness_rated_at is the logical clock reading, "
        f"got {rated['cleanliness_rated_at']}")

    validate_error(api.submit_guest_review(
        world["b_in"]["id"], {"cleanliness_rating": 4}, COORDINATOR),
        ApiErrorId.ERR_GUEST_REVIEW_ALREADY_SUBMITTED, 409)
    validate_error(api.submit_guest_review(
        world["b_in"]["id"], {"cleanliness_rating": 1}, COORDINATOR),
        ApiErrorId.ERR_GUEST_REVIEW_ALREADY_SUBMITTED, 409)

    final = validate_success(api.get_booking(world["b_in"]["id"], COORDINATOR))
    assert final["cleanliness_rating"] == 4, (
        f"no later attempt may overwrite the first review, "
        f"got {final['cleanliness_rating']}")
    assert same_instant(final["cleanliness_rated_at"], "2026-08-11T16:00:00Z"), (
        f"the recorded instant must survive the refusals, "
        f"got {final['cleanliness_rated_at']}")


def test_10_sampling_clears_completion_independence_window_then_uniqueness(
        api, verified_turn_at_finish):
    """Each refusal proves the previous gate had already been satisfied.

    PRD §3.9: "The turnover must have reached `COMPLETED`, otherwise
    `ERR_TURNOVER_NOT_COMPLETED`; sampling is permitted only within 72 hours —
    three days — of the turnover's `finished_at`, after which the answer is
    `ERR_AUDIT_WINDOW_CLOSED`; and a turnover may carry at most one audit that is
    not `VOIDED`, a second attempt drawing `ERR_AUDIT_ALREADY_EXISTS`." PRD
    §3.9: "The independence rule is the sharpest of the four: the acting
    auditor's `X-User-ID` must differ both from the `assigned_by_user_id`
    recorded on the turnover's assignment and from every `reviewed_by_user_id`
    recorded on that turnover's checklist rows, failing which the request is
    refused with `ERR_SEGREGATION_OF_DUTIES`." PRD §3.9: "Finalization moves the
    audit `SAMPLED → FINALIZED` and may be performed only by the auditor who
    sampled it: a mismatch between `auditor_user_id` and the acting `X-User-ID`
    draws `ERR_NOT_AUDIT_OWNER`, and an audit already `FINALIZED` or `VOIDED`
    draws `ERR_INVALID_AUDIT_STATE`."

    Design: Corner/validations/corner_val_audit_sampling_gauntlet_completion_duties_window_then_uniqueness
    """
    world = verified_turn_at_finish
    payload = create_quality_audit_payload(world["t1"]["id"], 88)

    validate_error(api.create_quality_audit(payload, AUDITOR),
                   ApiErrorId.ERR_TURNOVER_NOT_COMPLETED, 409)

    finished = validate_success(api.complete_turnover(
        world["t1"]["id"], {}, world["cleaner_headers"]))
    assert finished["status"] == "COMPLETED", (
        f"the turn must close before it can be sampled, got {finished['status']}")
    assert same_instant(finished["finished_at"], "2026-08-08T20:00:00Z"), (
        f"finished_at anchors the 72-hour window, got {finished['finished_at']}")

    validate_error(
        api.create_quality_audit(payload, make_quality_auditor_headers("coord-1")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    validate_error(
        api.create_quality_audit(payload, make_quality_auditor_headers("coord-2")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    fx.reset_clock(api, "2026-08-11T20:01:00Z")
    validate_error(api.create_quality_audit(payload, AUDITOR),
                   ApiErrorId.ERR_AUDIT_WINDOW_CLOSED, 422)

    fx.reset_clock(api, "2026-08-11T20:00:00Z")
    audit = validate_success(api.create_quality_audit(
        create_quality_audit_payload(world["t1"]["id"], 88,
                                     findings="spot check clean"), AUDITOR), 201)
    assert audit["status"] == "SAMPLED", (
        f"exactly 72 hours after finishing is still inside the window, "
        f"got {audit['status']}")
    assert audit["cleaner_id"] == world["cc"]["id"], (
        f"the audit copies the cleaner from the COMPLETED assignment, "
        f"got {audit['cleaner_id']}")
    assert audit["auditor_user_id"] == "auditor-1", (
        f"auditor_user_id is the acting X-User-ID, got {audit['auditor_user_id']}")

    validate_error(api.create_quality_audit(
        create_quality_audit_payload(world["t1"]["id"], 60), AUDITOR_TWO),
        ApiErrorId.ERR_AUDIT_ALREADY_EXISTS, 409)
    validate_error(api.finalize_quality_audit(audit["id"], {}, AUDITOR_TWO),
                   ApiErrorId.ERR_NOT_AUDIT_OWNER, 403)

    final = validate_success(api.finalize_quality_audit(audit["id"], {}, AUDITOR))
    assert final["status"] == "FINALIZED", (
        f"the sampling auditor may finalize, got {final['status']}")
    assert final["variant_applied"] == "AUDIT_ONLY", (
        f"the arriving stay never filed a rating, "
        f"got {final['variant_applied']}")
    assert float(final["observed_score"]) == pytest.approx(88.00, abs=0.005), (
        f"audit-only observed is the raw score, got {final['observed_score']}")
    assert float(final["resulting_quality_score"]) == pytest.approx(
        90.80, abs=0.005), (
        f"carryover must be 0.7 * 92.00 + 0.3 * 88.00, "
        f"got {final['resulting_quality_score']}")
    assert final["pay_adjustment_cents"] == 0, (
        f"88 sits inside the neutral band, got {final['pay_adjustment_cents']}")

    validate_error(api.finalize_quality_audit(audit["id"], {}, AUDITOR),
                   ApiErrorId.ERR_INVALID_AUDIT_STATE, 409)

    pay = validate_success(
        api.list_pay_lines(COORDINATOR, {"turnover_id": world["t1"]["id"]}))[0]
    assert pay["net_cents"] == 11114, (
        f"a neutral audit leaves the settled net alone, got {pay['net_cents']}")
    assert pay["audit_adjustment_cents"] == 0, (
        f"no adjustment may be folded in, got {pay['audit_adjustment_cents']}")


def test_11_restock_entries_are_mandatory_on_one_row_and_banned_on_another(
        api, single_line_in_progress):
    """The computed category decides, and an empty array still counts as none.

    PRD §3.6: "Restock entries must be present exactly when the row's `category`
    is `RESTOCK`: a restock row with none draws `ERR_RESTOCK_ENTRIES_REQUIRED`,
    and a `CLEANING` or `STAGING` row carrying any draws
    `ERR_RESTOCK_ENTRIES_NOT_ALLOWED`." PRD §2.5: "16. **Restock entries
    required.** On `POST /checklist-tasks/{id}/submit`, a task whose `category`
    is `RESTOCK` must carry at least one restock entry. Failure yields
    `ERR_RESTOCK_ENTRIES_REQUIRED` (422)." PRD §3.6: "**No stock moves at
    submission time**: consumption is booked only when a reviewer approves, which
    is precisely what prevents a rejected-then-resubmitted row from
    double-counting stock."

    Design: Corner/validations/corner_val_restock_entry_presence_is_conditional_on_the_task_category
    """
    world = single_line_in_progress
    sl1 = world["supply_lines"][0]
    strip = world["tasks"][0]
    restock = world["tasks"][3]
    assert strip["category"] == "CLEANING", (
        f"the first row's category is computed by the template, "
        f"got {strip['category']}")
    assert restock["category"] == "RESTOCK", (
        f"the fourth row's category is computed by the template, "
        f"got {restock['category']}")

    photo = "https://cdn.example.com/supply_restock.jpg"
    validate_error(api.submit_checklist_task(
        restock["id"], submit_task_payload(photo_uri=photo),
        world["cleaner_headers"]),
        ApiErrorId.ERR_RESTOCK_ENTRIES_REQUIRED, 422)
    validate_error(api.submit_checklist_task(
        restock["id"], submit_task_payload(photo_uri=photo, restock_entries=[]),
        world["cleaner_headers"]),
        ApiErrorId.ERR_RESTOCK_ENTRIES_REQUIRED, 422)
    validate_error(api.submit_checklist_task(
        strip["id"], submit_task_payload(
            note="linens stripped",
            restock_entries=[restock_entry(sl1["id"], 1)]),
        world["cleaner_headers"]),
        ApiErrorId.ERR_RESTOCK_ENTRIES_NOT_ALLOWED, 422)

    cleaning = validate_success(api.submit_checklist_task(
        strip["id"], submit_task_payload(note="linens stripped"),
        world["cleaner_headers"]))
    assert cleaning["status"] == "SUBMITTED", (
        f"the same row is accepted once it carries no stock intent, "
        f"got {cleaning['status']}")
    assert cleaning["restock_line_count"] == 0, (
        f"a CLEANING row books no lines, got {cleaning['restock_line_count']}")
    assert cleaning["restock_charge_cents"] == 0, (
        f"a CLEANING row books no chargeback, "
        f"got {cleaning['restock_charge_cents']}")

    stocked = validate_success(api.submit_checklist_task(
        restock["id"], submit_task_payload(
            photo_uri=photo, restock_entries=[restock_entry(sl1["id"], 2)]),
        world["cleaner_headers"]))
    assert stocked["status"] == "SUBMITTED", (
        f"one entry is enough for the RESTOCK row, got {stocked['status']}")
    assert stocked["restock_line_count"] == 1, (
        f"restock_line_count counts this submission's entries, "
        f"got {stocked['restock_line_count']}")
    assert stocked["restock_charge_cents"] == 0, (
        f"the chargeback is computed at approval, not at submission, "
        f"got {stocked['restock_charge_cents']}")

    line = fx.read_supply_line(api, sl1["id"])
    assert line["on_hand_qty"] == 6, (
        f"submission alone moves no stock, got {line['on_hand_qty']}")


def test_12_completion_waits_for_the_last_row_not_merely_for_the_parent_state(
        api, single_line_all_submitted):
    """A legal AWAITING_VERIFICATION parent still fails the aggregate child check.

    PRD §2.5: "18. **Verification completeness.** On `POST
    /turnovers/{id}/complete`, every checklist task of the turnover must be
    `VERIFIED` or `WAIVED`. Failure yields `ERR_UNVERIFIED_TASKS_REMAIN` (409)."
    PRD §3.6: "if any child sits in `REJECTED` the turnover is
    `REWORK_REQUIRED`; otherwise if any child sits in `PENDING` the turnover is
    `IN_PROGRESS`; otherwise — every child being `VERIFIED` or `WAIVED` — the
    turnover is `AWAITING_VERIFICATION`." PRD §3.8: "The turnover's
    `restock_chargeback_cents` is set to the sum of `restock_charge_cents` across
    its `VERIFIED` restock rows — rows still `SUBMITTED`, or sitting in
    `REJECTED` or `WAIVED`, contribute nothing — and the property's
    `last_turnover_completed_at` is stamped from the logical clock."

    Design: Corner/validations/corner_val_completion_requires_every_checklist_row_verified_or_waived
    """
    world = single_line_all_submitted
    before = fx.read_turnover(api, world)
    assert before["status"] == "AWAITING_VERIFICATION", (
        f"four SUBMITTED rows leave nothing PENDING, got {before['status']}")

    validate_error(
        api.complete_turnover(world["t1"]["id"], {}, world["cleaner_headers"]),
        ApiErrorId.ERR_UNVERIFIED_TASKS_REMAIN, 409)

    for task in world["tasks"][:3]:
        validate_success(api.review_checklist_task(
            task["id"], review_task_payload("APPROVE"), REVIEWER))

    validate_error(
        api.complete_turnover(world["t1"]["id"], {}, world["cleaner_headers"]),
        ApiErrorId.ERR_UNVERIFIED_TASKS_REMAIN, 409)

    rows = validate_success(
        api.list_turnover_checklist_tasks(world["t1"]["id"], COORDINATOR))
    outstanding = [row for row in rows if row["status"] == "SUBMITTED"]
    assert len(outstanding) == 1, (
        f"exactly one row is still unreviewed, got {len(outstanding)}")

    validate_success(api.review_checklist_task(
        world["tasks"][3]["id"], review_task_payload("APPROVE"), REVIEWER))

    closed = validate_success(
        api.complete_turnover(world["t1"]["id"], {}, world["cleaner_headers"]))
    assert closed["status"] == "COMPLETED", (
        f"the fourth approval unblocks completion, got {closed['status']}")
    assert same_instant(closed["finished_at"], "2026-08-08T19:00:00Z"), (
        f"finished_at is the logical clock reading, got {closed['finished_at']}")
    assert closed["late_minutes"] == 0, (
        f"19:00Z precedes the 20:30Z close, got {closed['late_minutes']}")
    assert closed["restock_chargeback_cents"] == 280, (
        f"the chargeback must be round_half_up(260 * 1 * 1.075), "
        f"got {closed['restock_chargeback_cents']}")


def test_13_a_named_ineligible_cleaner_and_an_empty_pool_answer_differently(
        api, ineligible_candidates):
    """The same predicate yields NOT_ELIGIBLE explicitly and NO_ELIGIBLE by selector.

    PRD §2.5: "32. **Explicit-cleaner eligibility.** On `POST
    /turnovers/{id}/assign` with a named cleaner, that cleaner must serve the
    property's zone — by home zone, by secondary zone, or by accepting
    cross-zone work — and must have a `skill_level` greater than or equal to the
    property's `min_skill_level`. Failure yields `ERR_CLEANER_NOT_ELIGIBLE`
    (422)." PRD §2.5: "34. **Non-empty candidate pool.** On `POST
    /turnovers/{id}/assign` without a named cleaner, the filtered candidate pool
    must contain at least one cleaner. Failure yields `ERR_NO_ELIGIBLE_CLEANER`
    (422)." PRD §3.4: "A cleaner failing any of those conditions is simply
    filtered out; if the filtering empties the pool, the request is refused with
    `ERR_NO_ELIGIBLE_CLEANER`." PRD §3.4: "The score is then the sum of three
    weighted terms: normalised quality weighted at 0.50, the zone factor weighted
    at 0.30, and skill headroom weighted at 0.20."

    Design: Corner/validations/corner_val_explicit_cleaner_eligibility_versus_empty_selector_pool
    """
    world = ineligible_candidates
    assert world["c_low"]["skill_level"] == 1
    assert float(world["c_low"]["quality_score"]) == pytest.approx(
        80.00, abs=0.005), (
        f"an unseeded cleaner starts at 80.00, "
        f"got {world['c_low']['quality_score']}")
    assert world["c_far"]["secondary_zone_codes"] == [], (
        f"secondary reach defaults to empty, "
        f"got {world['c_far']['secondary_zone_codes']}")
    assert world["c_far"]["accepts_cross_zone"] is False, (
        f"cross-zone willingness defaults to false, "
        f"got {world['c_far']['accepts_cross_zone']}")

    version = world["t1"]["version"]
    validate_error(api.assign_turnover(
        world["t1"]["id"],
        assign_turnover_payload(version, world["c_low"]["id"]), COORDINATOR),
        ApiErrorId.ERR_CLEANER_NOT_ELIGIBLE, 422)
    validate_error(api.assign_turnover(
        world["t1"]["id"],
        assign_turnover_payload(version, world["c_far"]["id"]), COORDINATOR),
        ApiErrorId.ERR_CLEANER_NOT_ELIGIBLE, 422)
    validate_error(api.assign_turnover(
        world["t1"]["id"], assign_turnover_payload(version), COORDINATOR),
        ApiErrorId.ERR_NO_ELIGIBLE_CLEANER, 422)

    c_ok = validate_success(api.create_cleaner(create_cleaner_payload(
        name="Cleaner OK", home_zone_code="ZONE_A", skill_level=2), ADMIN), 201)

    validate_error(api.assign_turnover(
        world["t1"]["id"], assign_turnover_payload(
            version, exclude_cleaner_ids=[c_ok["id"]]), COORDINATOR),
        ApiErrorId.ERR_NO_ELIGIBLE_CLEANER, 422)

    offer = validate_success(api.assign_turnover(
        world["t1"]["id"], assign_turnover_payload(version), COORDINATOR), 201)
    assert offer["selection_mode"] == "SELECTOR", (
        f"omitting cleaner_id runs the selector, got {offer['selection_mode']}")
    assert offer["cleaner_id"] == c_ok["id"], (
        f"the one surviving candidate must win, got {offer['cleaner_id']}")
    assert float(offer["zone_match_factor"]) == pytest.approx(1.0, abs=0.00005)
    assert float(offer["match_score"]) == pytest.approx(0.7500, abs=0.00005), (
        f"match_score must be 0.50 * 0.80 + 0.30 * 1.0 + 0.20 * 0.25, "
        f"got {offer['match_score']}")

    after = validate_success(api.get_turnover(world["t1"]["id"], COORDINATOR))
    assert after["version"] == 2, (
        f"only the accepted offer bumped the version; five refusals bumped "
        f"nothing, got {after['version']}")
    assert after["status"] == "PENDING_ASSIGNMENT", (
        f"an offer alone does not schedule the turn, got {after['status']}")
