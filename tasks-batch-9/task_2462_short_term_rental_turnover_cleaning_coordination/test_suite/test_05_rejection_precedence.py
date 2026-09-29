"""Gate ordering: the first failing gate answers, never a later one."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_property_payload,
    create_turnover_payload,
    fixtures as fx,
    restock_entry,
    submit_task_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def rewound_running_world(api):
    """A clean already IN_PROGRESS with the clock rewound before its window."""
    world = fx.world_in_progress(api, supply=None)
    world["t1"] = fx.read_turnover(api, world)
    fx.reset_clock(api)
    return world


@pytest.fixture
def scarce_stock_world(api):
    """A running clean whose WELCOME line holds a single bottle."""
    world = fx.build_world(api, supply=None)
    world["supply_lines"] = [
        fx.seed_supply_line(
            api, world["p1"]["id"], sku="LIN-SHEET-Q", name="Queen Sheet Set",
            category="LINEN", unit_cost_cents=260, par_qty=6, unit="SET",
            initial_on_hand_qty=6),
        fx.seed_supply_line(
            api, world["p1"]["id"], sku="WEL-WINE", name="Welcome Wine",
            category="WELCOME", unit_cost_cents=900, par_qty=1, unit="BOTTLE",
            initial_on_hand_qty=1),
    ]
    fx.offer_turnover(api, world)
    fx.accept_offer(api, world)
    fx.start_clean(api, world)
    return world


@pytest.fixture
def studio_with_live_turnover(api):
    """A STUDIO carrying a live VACANT_GAP turn and a tight arriving stay."""
    fx.reset_clock(api)
    p1b = validate_success(api.create_property(create_property_payload(
        code="AUS-102", name="Zilker Studio", zone_code="ZONE_A",
        size_tier="STUDIO", owner_contact_email="owner2@example.com",
        bedroom_count=1, bathroom_count=1, bed_count=1,
        local_utc_offset_minutes=-300, min_clean_minutes=60,
        min_skill_level=1), ADMIN), 201)
    b_out = fx.seed_booking(
        api, p1b["id"], external_ref="OUT-2", guest_name="Guest Out 2",
        checkin_at="2026-08-06T21:00:00Z", checkout_at="2026-08-08T16:00:00Z")
    b_in = fx.seed_booking(
        api, p1b["id"], external_ref="IN-2", guest_name="Guest In 2",
        checkin_at="2026-08-08T17:47:00Z", checkout_at="2026-08-10T16:00:00Z")
    t_a = fx.seed_turnover(api, b_out["id"])
    return {"p1b": p1b, "b_out": b_out, "b_in": b_in, "t_a": t_a}


# ─── invalid_turnover_state_outranks_too_early_to_start ──────────────────

def test_01_target_state_answers_before_the_window_timing_gate(
        api, rewound_running_world):
    """Re-starting a running clean before its window answers on state, not time.

    PRD §2.5: "A request is evaluated through the following gates, and the
    **first** gate that fails determines the response; no later gate may mask an
    earlier one." PRD §2.5: "**Target state.** On every action endpoint, the
    addressed resource must itself be in a state that permits the operation,
    yielding one of `ERR_INVALID_TURNOVER_STATE`, `ERR_INVALID_ASSIGNMENT_STATE`,
    `ERR_INVALID_TASK_STATE`, `ERR_INVALID_ISSUE_STATE`,
    `ERR_INVALID_REPAIR_STATE`, `ERR_INVALID_AUDIT_STATE`,
    `ERR_BOOKING_NOT_SCHEDULED` or `ERR_INVALID_CLEANER_STATE`, each at HTTP
    409."

    Design: Difficulty/priority_pair_validation_conflict/invalid_turnover_state_outranks_too_early_to_start
    """
    world = rewound_running_world
    assert world["t1"]["status"] == "IN_PROGRESS" and world["t1"]["version"] == 5, (
        f"the clean must already be running at version 5, got "
        f"{world['t1']['status']} / {world['t1']['version']}")

    response = api.start_turnover(world["t1"]["id"], {}, world["cleaner_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_TURNOVER_STATE.value, 409)
    assert response.json()["data"]["error_id"] != "ERR_TOO_EARLY_TO_START", (
        "the later timing gate must not mask the earlier target-state gate")


def test_02_the_rejected_restart_leaves_no_trace_on_the_turnover(
        api, rewound_running_world):
    """A refused request fires no side effect at all.

    PRD §2.5: "**Start not before the window opens.** On
    `POST /turnovers/{id}/start`, the logical clock must be at or after the
    turnover's `window_start_at`. Failure yields `ERR_TOO_EARLY_TO_START`
    (409)." PRD §3.5: "Beginning the clean advances the turnover `SCHEDULED →
    IN_PROGRESS` and simultaneously moves the accepted offer `ACCEPTED →
    ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_turnover_state_outranks_too_early_to_start
    """
    world = rewound_running_world
    api.start_turnover(world["t1"]["id"], {}, world["cleaner_headers"])

    after = fx.read_turnover(api, world)
    assert after["status"] == "IN_PROGRESS", (
        f"the status must be unchanged, got {after['status']}")
    assert after["version"] == 5, (
        f"a refused request must not bump the version, got {after['version']}")
    assert after["checklist_task_count"] == 4, (
        f"the checklist must not be generated a second time, "
        f"got {after['checklist_task_count']}")


# ─── photo_required_outranks_insufficient_on_hand ────────────────────────

def test_03_missing_photo_answers_before_the_stock_sufficiency_gate(
        api, scarce_stock_world):
    """A photoless restock over-drawing stock answers ERR_PHOTO_REQUIRED.

    PRD §2.5: "**Photo evidence.** On `POST /checklist-tasks/{id}/submit`,
    `photo_uri` must be present when the task's `requires_photo` is true.
    Failure yields `ERR_PHOTO_REQUIRED` (422)." PRD §2.5: "**Stock
    sufficiency.** On `POST /checklist-tasks/{id}/submit`, every restock entry's
    `qty_used` must be less than or equal to its supply line's `on_hand_qty`,
    and a replenishment quantity must be at least 1. Failure yields
    `ERR_INSUFFICIENT_ON_HAND` (409)."

    Design: Difficulty/priority_pair_validation_conflict/photo_required_outranks_insufficient_on_hand
    """
    world = scarce_stock_world
    restock = next(t for t in world["tasks"] if t["category"] == "RESTOCK")
    assert restock["requires_photo"] is True, (
        "the restock row demands photographic evidence")

    wine = world["supply_lines"][1]
    response = api.submit_checklist_task(
        restock["id"],
        submit_task_payload(note="restocked",
                            restock_entries=[restock_entry(wine["id"], 5)]),
        world["cleaner_headers"])
    validate_error(response, ApiErrorId.ERR_PHOTO_REQUIRED.value, 422)
    assert response.json()["data"]["error_id"] != "ERR_INSUFFICIENT_ON_HAND", (
        "the fiscal gate sits later in the ladder and must not answer first")


def test_04_the_refused_submission_moves_neither_the_row_nor_the_closet(
        api, scarce_stock_world):
    """No stock movement is appended and the row stays PENDING.

    PRD §2.9: "A supply line's `on_hand_qty` is a pure projection: it equals the
    sum of `delta_qty` across every `StockMovement` bearing that line's
    `supply_line_id`, regardless of the movement's `reason`." PRD §3.5: "A
    successful submission
    records `photo_uri`, `note`, a `submitted_at` reading of the logical clock,
    and `restock_line_count` — the number of restock entries carried on this
    most recent submission — and re-derives the parent."

    Design: Difficulty/priority_pair_validation_conflict/photo_required_outranks_insufficient_on_hand
    """
    world = scarce_stock_world
    restock = next(t for t in world["tasks"] if t["category"] == "RESTOCK")
    wine = world["supply_lines"][1]
    api.submit_checklist_task(
        restock["id"],
        submit_task_payload(note="restocked",
                            restock_entries=[restock_entry(wine["id"], 5)]),
        world["cleaner_headers"])

    rows = validate_success(api.list_turnover_checklist_tasks(
        world["t1"]["id"], COORDINATOR))
    row = {r["id"]: r for r in rows}[restock["id"]]
    assert row["status"] == "PENDING", (
        f"the refused row must stay PENDING, got {row['status']}")
    assert row["restock_line_count"] == 0, (
        f"nothing was recorded on the row, got {row['restock_line_count']}")

    line = fx.read_supply_line(api, wine["id"])
    assert line["on_hand_qty"] == 1, (
        f"the single bottle must still be on hand, got {line['on_hand_qty']}")
    movements = fx.read_movements(api, {"supply_line_id": wine["id"]})
    assert len(movements) == 1 and movements[0]["reason"] == "SEED", (
        f"only the seeding movement may exist, got {len(movements)} rows")
    assert fx.read_turnover(api, world)["status"] == "IN_PROGRESS"


# ─── window_override_required_outranks_turnover_already_exists ───────────

def test_05_window_sufficiency_answers_before_the_duplicate_turn_gate(
        api, studio_with_live_turnover):
    """A short window on an already-turned departure answers on the window.

    PRD §2.5: "**Window sufficiency at creation.** On `POST /turnovers`,
    `window_minutes` must be greater than or equal to `required_minutes` unless
    an `override_reason` is supplied. Failure yields
    `ERR_WINDOW_OVERRIDE_REQUIRED` (422)." PRD §2.5: "**One live turnover per
    departure.** On `POST /turnovers`, an outgoing booking may carry at most one
    turnover that is not `VOID`. Failure yields `ERR_TURNOVER_ALREADY_EXISTS`
    (409)."

    Design: Difficulty/priority_pair_validation_conflict/window_override_required_outranks_turnover_already_exists
    """
    world = studio_with_live_turnover
    assert world["t_a"]["turn_type"] == "VACANT_GAP", (
        f"the first turn was opened without an arriving stay, "
        f"got {world['t_a']['turn_type']}")
    assert world["t_a"]["required_minutes"] == 110, (
        f"a STUDIO with 1 bath and 1 bed requires 90 + 12 + 8 minutes, "
        f"got {world['t_a']['required_minutes']}")

    response = api.create_turnover(
        create_turnover_payload(world["b_out"]["id"], world["b_in"]["id"]),
        COORDINATOR)
    validate_error(response, ApiErrorId.ERR_WINDOW_OVERRIDE_REQUIRED.value, 422)
    assert response.json()["data"]["error_id"] != "ERR_TURNOVER_ALREADY_EXISTS", (
        "the duplicate-turn gate sits later and must not answer first")


def test_06_the_refused_creation_leaves_the_first_turnover_alone(
        api, studio_with_live_turnover):
    """Exactly one turnover survives on the departure and it is unmodified.

    PRD §3.3: "A `Coordinator` opens a turnover by nominating the departing stay
    through `outgoing_booking_id` and, when an arriving stay is already known,
    the `incoming_booking_id`; omitting the latter declares a vacant gap." PRD
    §3.3: "A raw window length strictly less than `required_minutes` is refused
    with `ERR_WINDOW_OVERRIDE_REQUIRED` unless an `override_reason` was
    supplied".

    Design: Difficulty/priority_pair_validation_conflict/window_override_required_outranks_turnover_already_exists
    """
    world = studio_with_live_turnover
    api.create_turnover(
        create_turnover_payload(world["b_out"]["id"], world["b_in"]["id"]),
        COORDINATOR)

    rows, meta = validate_paginated(api.list_turnovers(
        COORDINATOR, {"outgoing_booking_id": world["b_out"]["id"]}))
    assert meta["total_count"] == 1, (
        f"the departure must still carry exactly one turnover, "
        f"got {meta['total_count']}")
    assert rows[0]["id"] == world["t_a"]["id"]

    survivor = validate_success(api.get_turnover(world["t_a"]["id"], COORDINATOR))
    assert survivor["status"] == "PENDING_ASSIGNMENT", (
        f"the surviving turn is untouched, got {survivor['status']}")
    assert survivor["incoming_booking_id"] is None, (
        f"the refused request must not attach the arriving stay, "
        f"got {survivor['incoming_booking_id']}")
