"""Gates that read a sibling entity: the departing guest, the cleaner, the unit."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    cleaner_status_payload,
    create_turnover_payload,
    fixtures as fx,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def scheduled_guest_still_in_world(api):
    """T1 SCHEDULED at the exact window opening with the guest still in the unit."""
    world = fx.world_scheduled(api, supply=None)
    fx.reset_clock(api, fx.CHECKOUT_INSTANT)
    return world


@pytest.fixture
def suspended_cleaner_world(api):
    """T1 at version 1 and the only capable cleaner SUSPENDED."""
    world = fx.build_world(api, supply=None)
    suspended = validate_success(api.set_cleaner_status(
        world["cc"]["id"],
        cleaner_status_payload("SUSPEND", reason="documents expired"), ADMIN))
    world["cc"] = suspended
    return world


@pytest.fixture
def paused_and_active_units(api):
    """One PAUSED unit and one ACTIVE twin, each with the same booking geometry."""
    fx.reset_clock(api)
    paused = fx.seed_property(
        api, code="AUS-104", name="Paused Loft",
        owner_contact_email="owner4@example.com", status="PAUSED")
    active = fx.seed_property(api)
    p_out = fx.seed_booking(
        api, paused["id"], external_ref="OUT-4", guest_name="Guest Out 4",
        checkin_at="2026-08-05T21:00:00Z", checkout_at="2026-08-08T16:00:00Z")
    p_in = fx.seed_booking(
        api, paused["id"], external_ref="IN-4", guest_name="Guest In 4",
        checkin_at="2026-08-08T21:00:00Z", checkout_at="2026-08-11T16:00:00Z")
    a_out, a_in = fx.seed_stay_pair(api, active["id"])
    return {"paused": paused, "active": active, "p_out": p_out, "p_in": p_in,
            "a_out": a_out, "a_in": a_in}


# ─── start_requires_outgoing_booking_checked_out ─────────────────────────

def test_01_the_clean_cannot_start_while_the_departing_guest_is_still_in(
        api, scheduled_guest_still_in_world):
    """Even at the window opening the start is refused until the guest leaves.

    PRD §2.5: "**Gating sibling state.** A *different* entity than the one
    addressed must also be in the required state: the property must be `ACTIVE`
    for a new turnover, the cleaner must be `ACTIVE` to be offered work or to
    accept it, the outgoing booking must be `CHECKED_OUT` before the clean
    starts, and the turnover must be `COMPLETED` before an audit may be
    sampled." PRD §3.5: "Four preconditions guard it: the turnover must be in
    `SCHEDULED`, the acting cleaner must own the turnover's `ACCEPTED` offer,
    the departing stay must already be `CHECKED_OUT` — a cross-entity gate
    answering `ERR_GUEST_NOT_CHECKED_OUT` when the guest has not left — and the
    logical clock must be at or after `window_start_at`, answering
    `ERR_TOO_EARLY_TO_START` when the cleaner arrives ahead of the window."

    Design: Difficulty/cross_entity_state_dependency/start_requires_outgoing_booking_checked_out
    """
    world = scheduled_guest_still_in_world
    response = api.start_turnover(world["t1"]["id"], {}, world["cleaner_headers"])
    validate_error(response, ApiErrorId.ERR_GUEST_NOT_CHECKED_OUT.value, 409)

    after = fx.read_turnover(api, world)
    assert after["status"] == "SCHEDULED", (
        f"the refused start must leave the turn SCHEDULED, got {after['status']}")
    assert after["version"] == 3, (
        f"no side effect fired so the version stays 3, got {after['version']}")
    assert after["checklist_task_count"] == 0, (
        f"the checklist is only generated on a successful start, "
        f"got {after['checklist_task_count']}")


def test_02_recording_the_departure_unblocks_the_identical_start_request(
        api, scheduled_guest_still_in_world):
    """The same call succeeds once the sibling booking reaches CHECKED_OUT.

    PRD §3.5: "Beginning the clean advances the turnover `SCHEDULED →
    IN_PROGRESS` and simultaneously moves the accepted offer `ACCEPTED →
    ACTIVE`." PRD §3.5: "On success `started_at` is stamped from the logical
    clock and the turnover's `version` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/start_requires_outgoing_booking_checked_out
    """
    world = scheduled_guest_still_in_world
    api.start_turnover(world["t1"]["id"], {}, world["cleaner_headers"])

    departed = validate_success(
        api.checkout_booking(world["b_out"]["id"], {}, COORDINATOR))
    assert departed["status"] == "CHECKED_OUT", (
        f"the departure must be recorded first, got {departed['status']}")

    started = validate_success(
        api.start_turnover(world["t1"]["id"], {}, world["cleaner_headers"]))
    assert started["status"] == "IN_PROGRESS", (
        f"the identical request must now succeed, got {started['status']}")
    assert started["checklist_task_count"] == 4, (
        f"a TWO_BR generates four rows, got {started['checklist_task_count']}")
    assert same_instant(started["started_at"], "2026-08-08T16:00:00Z"), (
        f"started_at reads the logical clock, got {started['started_at']}")

    assignment = validate_success(
        api.get_assignment(world["a1"]["id"], COORDINATOR))
    assert assignment["status"] == "ACTIVE", (
        f"the accepted offer must become ACTIVE, got {assignment['status']}")


# ─── assign_requires_named_cleaner_active ────────────────────────────────

def test_03_a_suspended_cleaner_cannot_be_named_on_an_offer(
        api, suspended_cleaner_world):
    """Naming a suspended cleaner is refused rather than silently filtered.

    PRD §3.1: "A cleaner's employment `status` may be `ACTIVE`, `SUSPENDED` or
    `OFFBOARDED` and defaults to `ACTIVE`; only an `ACTIVE` cleaner may be
    offered work or accept it." PRD §2.5: "The gate guards `POST /turnovers`,
    `POST /turnovers/{id}/assign`, `POST /assignments/{id}/accept`,
    `POST /turnovers/{id}/start` and `POST /quality-audits`, and yields
    `ERR_PROPERTY_NOT_ACTIVE`, `ERR_CLEANER_NOT_ACTIVE`,
    `ERR_GUEST_NOT_CHECKED_OUT` or `ERR_TURNOVER_NOT_COMPLETED` (409)."

    Design: Difficulty/cross_entity_state_dependency/assign_requires_named_cleaner_active
    """
    world = suspended_cleaner_world
    assert world["cc"]["status"] == "SUSPENDED", (
        f"the cleaner must be suspended for this gate, "
        f"got {world['cc']['status']}")

    response = api.assign_turnover(
        world["t1"]["id"],
        {"expected_turnover_version": 1, "cleaner_id": world["cc"]["id"]},
        COORDINATOR)
    validate_error(response, ApiErrorId.ERR_CLEANER_NOT_ACTIVE.value, 409)

    assert fx.read_turnover(api, world)["version"] == 1, (
        "the refused offer must leave the turnover at version 1")
    _, meta = validate_paginated(api.list_assignments(
        COORDINATOR, {"turnover_id": world["t1"]["id"]}))
    assert meta["total_count"] == 0, (
        f"no assignment row may be created, got {meta['total_count']}")


def test_04_reactivating_the_cleaner_makes_the_same_offer_land_at_0_9100(
        api, suspended_cleaner_world):
    """The stale version reading is still good because the refusal changed nothing.

    PRD §3.10: "Reactivation restores nothing: the cleaner becomes eligible for
    new work again, but revoked assignments are never resurrected." PRD §3.4:
    "In explicit mode the coordinator names a `cleaner_id` and the system
    verifies eligibility rather than choosing".

    Design: Difficulty/cross_entity_state_dependency/assign_requires_named_cleaner_active
    """
    world = suspended_cleaner_world
    api.assign_turnover(
        world["t1"]["id"],
        {"expected_turnover_version": 1, "cleaner_id": world["cc"]["id"]},
        COORDINATOR)

    reactivated = validate_success(api.set_cleaner_status(
        world["cc"]["id"], cleaner_status_payload("REACTIVATE"), ADMIN))
    assert reactivated["status"] == "ACTIVE", (
        f"the cleaner must be eligible again, got {reactivated['status']}")

    offer = validate_success(api.assign_turnover(
        world["t1"]["id"],
        {"expected_turnover_version": 1, "cleaner_id": world["cc"]["id"]},
        COORDINATOR), 201)
    assert offer["selection_mode"] == "EXPLICIT", (
        f"the coordinator named the cleaner, got {offer['selection_mode']}")
    assert float(offer["match_score"]) == pytest.approx(0.9100, abs=0.00005), (
        f"0.50*0.92 + 0.30*1.0 + 0.20*0.75 is 0.9100, "
        f"got {offer['match_score']}")
    assert offer["status"] == "OFFERED"
    assert fx.read_turnover(api, world)["version"] == 2, (
        "the accepted offer bumps the turnover to version 2")


# ─── turnover_creation_requires_property_active ──────────────────────────

def test_05_no_turnover_may_be_opened_on_a_paused_unit(
        api, paused_and_active_units):
    """A generous window does not save a turn on a PAUSED unit.

    PRD §3.1: "What the dimension *does* is gate new work — a unit that is
    `PAUSED` or `OFFBOARDED` refuses to open a new turnover and answers
    `ERR_PROPERTY_NOT_ACTIVE`, while an `ACTIVE` unit accepts one." PRD §3.3:
    "The turnover copies its `property_id` from the departing stay, lands with
    `status` `PENDING_ASSIGNMENT` and `version` 1, and refuses to be created at
    all if the property is not `ACTIVE` (`ERR_PROPERTY_NOT_ACTIVE`), if the
    departing stay already carries a turnover that is not `VOID`
    (`ERR_TURNOVER_ALREADY_EXISTS`), if the two nominated stays belong to
    different units (`ERR_PROPERTY_MISMATCH`), or if the arriving stay's
    `checkin_at` precedes the departing stay's `checkout_at`
    (`ERR_INVALID_TIME_INTERVAL`)."

    Design: Difficulty/cross_entity_state_dependency/turnover_creation_requires_property_active
    """
    world = paused_and_active_units
    assert world["paused"]["status"] == "PAUSED", (
        f"the unit must be registered directly in PAUSED, "
        f"got {world['paused']['status']}")
    assert world["active"]["status"] == "ACTIVE", (
        f"the twin unit must default to ACTIVE, got {world['active']['status']}")

    response = api.create_turnover(
        create_turnover_payload(world["p_out"]["id"], world["p_in"]["id"]),
        COORDINATOR)
    validate_error(response, ApiErrorId.ERR_PROPERTY_NOT_ACTIVE.value, 409)

    _, meta = validate_paginated(api.list_turnovers(
        COORDINATOR, {"property_id": world["paused"]["id"]}))
    assert meta["total_count"] == 0, (
        f"the paused unit must carry no turnover, got {meta['total_count']}")
    still_scheduled = validate_success(
        api.get_booking(world["p_out"]["id"], COORDINATOR))
    assert still_scheduled["status"] == "SCHEDULED", (
        f"the refused creation left the stays alone, "
        f"got {still_scheduled['status']}")


def test_06_the_same_geometry_opens_normally_on_the_active_twin(
        api, paused_and_active_units):
    """The ACTIVE unit yields a 270-minute window with 72 minutes of slack.

    PRD §3.3: "Once past the guards, `window_minutes` is the raw length with a
    floor of 0 applied, `slack_minutes` is `window_minutes` less
    `required_minutes` and may legitimately be negative, and `is_tight` is true
    whenever `slack_minutes` is strictly below 45 minutes — note that a
    comfortable window is not merely one that fits, but one that fits with
    three quarters of an hour to spare." PRD §3.3: "An optional
    `override_reason` may be supplied as justification for a window too short
    for the work."

    Design: Difficulty/cross_entity_state_dependency/turnover_creation_requires_property_active
    """
    world = paused_and_active_units
    turnover = validate_success(api.create_turnover(
        create_turnover_payload(world["a_out"]["id"], world["a_in"]["id"]),
        COORDINATOR), 201)

    assert turnover["status"] == "PENDING_ASSIGNMENT", (
        f"a fresh turn opens in PENDING_ASSIGNMENT, got {turnover['status']}")
    assert turnover["window_minutes"] == 270, (
        f"16:00Z to 20:30Z is 270 minutes, got {turnover['window_minutes']}")
    assert turnover["required_minutes"] == 198, (
        f"the TWO_BR requirement is 198, got {turnover['required_minutes']}")
    assert turnover["slack_minutes"] == 72, (
        f"270 less 198 is 72, got {turnover['slack_minutes']}")
    assert turnover["is_tight"] is False, (
        f"72 minutes of slack is not tight, got {turnover['is_tight']}")
