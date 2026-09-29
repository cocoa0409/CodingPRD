"""Stale-version guards, the version trace across aggregates and immediate settlement."""

from datetime import datetime

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_turnover_payload,
    fixtures as fx,
    replenish_payload,
    restock_entry,
    review_task_payload,
    same_instant,
    schedule_change_payload,
    submit_task_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["coordinator_reviewer_headers"]


def _utc(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of its fractional-digit width."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def turnover_at_version_one(api):
    """P1, Cleaner C, OUT-1/IN-1 and T1 freshly opened at version 1."""
    return fx.build_world(api, supply=None)


@pytest.fixture
def seeded_sheet_line(api):
    """One LINEN line seeded at 6 SET, reorder_point 0, sitting at version 1."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    sl1 = fx.seed_supply_line(
        api, p1["id"], sku="LIN-SHEET-Q", name="Queen Sheet Set",
        category="LINEN", unit_cost_cents=260, par_qty=6, unit="SET",
        initial_on_hand_qty=6)
    return {"p1": p1, "sl1": sl1}


@pytest.fixture
def offered_pair_world(api):
    """The canonical two-linen-line world with T1 offered to Cleaner C."""
    world = fx.build_world(api, supply="pair")
    fx.offer_turnover(api, world)
    return world


# ─── cross_cutting_layers ─────────────────────────────────────────────────

def test_01_a_window_recomputation_makes_the_coordinators_offer_stale(
        api, turnover_at_version_one):
    """The refused offer creates nothing and the identical body lands on a re-read.

    PRD §2.7: "Creating a cleaner offer on a turnover requires
    `expected_turnover_version` in the request body, carrying the client's last
    observed `version` of that `Turnover`." PRD §2.7: "If it does not equal the
    turnover's current `version`, the request is rejected with
    `ERR_STALE_TURNOVER_VERSION` at HTTP 412." PRD §3.2: "Either variant then
    re-derives the affected non-terminal turnover's window and increments that
    turnover's `version` by 1." PRD §3.4: "Offering also increments the turnover's
    `version` by 1, and requires the turnover to be in `PENDING_ASSIGNMENT`; any
    other status draws `ERR_INVALID_TURNOVER_STATE`."

    Design: Corner/cross_cutting_layers/corner_cc_occ_stale_turnover_version_refused_then_fresh_version_accepted
    """
    world = turnover_at_version_one
    stale_version = world["t1"]["version"]
    assert stale_version == 1, (
        f"the coordinator's reading is taken at creation, got {stale_version}")

    granted = validate_success(api.schedule_change_booking(
        world["b_out"]["id"],
        schedule_change_payload("LATE_CHECKOUT", "2026-08-08T17:00:00Z"),
        COORDINATOR))
    assert same_instant(granted["late_checkout_until_at"], "2026-08-08T17:00:00Z"), (
        f"the courtesy is recorded on the departing stay, "
        f"got {granted['late_checkout_until_at']}")

    validate_error(api.assign_turnover(
        world["t1"]["id"],
        assign_turnover_payload(stale_version, world["cc"]["id"]), COORDINATOR),
        ApiErrorId.ERR_STALE_TURNOVER_VERSION, 412)

    _, offers_meta = validate_paginated(
        api.list_assignments(COORDINATOR, {"turnover_id": world["t1"]["id"]}))
    assert offers_meta["total_count"] == 0, (
        f"a 412 must not have minted an offer, got {offers_meta['total_count']}")

    fresh = fx.read_turnover(api, world)
    assert fresh["version"] == 2, (
        f"the schedule change had already bumped the turnover, "
        f"got {fresh['version']}")
    assert fresh["window_minutes"] == 210, (
        f"the window now runs 17:00Z to 20:30Z, got {fresh['window_minutes']}")

    offer = validate_success(api.assign_turnover(
        world["t1"]["id"],
        assign_turnover_payload(fresh["version"], world["cc"]["id"]),
        COORDINATOR), 201)
    assert offer["status"] == "OFFERED", (
        f"the identical body carrying the fresh token is accepted, "
        f"got {offer['status']}")

    after = fx.read_turnover(api, world)
    assert after["version"] == 3, (
        f"the accepted write bumped the turnover again, got {after['version']}")


def test_02_a_retried_delivery_on_a_stale_token_cannot_double_the_stock(
        api, seeded_sheet_line):
    """The refused retry appends no ledger row, and a fresh token adds the next four.

    PRD §2.7: "Recording received stock on a supply line requires
    `expected_supply_line_version` in the request body, carrying the client's last
    observed `version` of that `SupplyLine`." PRD §2.7: "If it does not equal the
    line's current `version`, the request is rejected with
    `ERR_STALE_SUPPLY_LINE_VERSION` at HTTP 412." PRD §3.1: "The append carries
    `reason` `REPLENISH` and a `delta_qty` equal to the supplied `qty`, refreshes
    `on_hand_qty` and `below_par`, and increments the line's `version` by 1." PRD
    §2.9: "A supply line's `on_hand_qty` is a pure projection: it equals the sum of
    `delta_qty` across every `StockMovement` bearing that line's `supply_line_id`,
    regardless of the movement's `reason`."

    Design: Corner/cross_cutting_layers/corner_cc_occ_stale_supply_line_version_prevents_double_counting_a_delivery
    """
    line = seeded_sheet_line["sl1"]
    stale_version = line["version"]
    assert line["on_hand_qty"] == 6, (
        f"the SEED movement carried the whole opening stock, "
        f"got {line['on_hand_qty']}")
    assert stale_version == 1, (
        f"a freshly created line sits at version 1, got {stale_version}")

    first = validate_success(api.replenish_supply_line(
        line["id"], replenish_payload(4, stale_version, note="delivery 8891"),
        COORDINATOR))
    assert first["on_hand_qty"] == 10, (
        f"the delivery is purely additive, got {first['on_hand_qty']}")
    assert first["version"] == 2, (
        f"the append bumped the line, got {first['version']}")

    validate_error(api.replenish_supply_line(
        line["id"],
        replenish_payload(4, stale_version, note="delivery 8891 retried"),
        COORDINATOR), ApiErrorId.ERR_STALE_SUPPLY_LINE_VERSION, 412)

    unchanged = fx.read_supply_line(api, line["id"])
    assert unchanged["on_hand_qty"] == 10, (
        f"the retry must have added nothing, got {unchanged['on_hand_qty']}")
    assert unchanged["version"] == 2, (
        f"a refused write leaves the token where it was, "
        f"got {unchanged['version']}")

    rows, meta = validate_paginated(
        api.list_stock_movements(COORDINATOR, {"supply_line_id": line["id"]}))
    assert meta["total_count"] == 2, (
        f"only SEED and one REPLENISH may exist, got {meta['total_count']}")
    assert [row["reason"] for row in rows] == ["SEED", "REPLENISH"], (
        f"no phantom third row was appended, "
        f"got {[row['reason'] for row in rows]}")
    assert rows[1]["delta_qty"] == 4, (
        f"the surviving delivery moved four units, got {rows[1]['delta_qty']}")
    assert rows[1]["note"] == "delivery 8891", (
        f"the note of the accepted call is the one carried, "
        f"got {rows[1]['note']}")

    second = validate_success(api.replenish_supply_line(
        line["id"],
        replenish_payload(4, unchanged["version"], note="delivery 8892"),
        COORDINATOR))
    assert second["on_hand_qty"] == 14, (
        f"a genuinely new delivery on a fresh token lands, "
        f"got {second['on_hand_qty']}")
    assert second["version"] == 3, (
        f"and bumps the token once more, got {second['version']}")


def test_03_the_version_advances_on_every_write_including_a_neighbours(
        api, turnover_at_version_one):
    """Two reads leave the token alone while four writes walk it from 1 to 5.

    PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
    timestamp refreshed on every mutation, and `version`, an integer that begins at
    1 when the resource is created and increases by exactly 1 on each mutation that
    the specification declares to be a version-bumping change." PRD §3.4:
    "Offering also increments the turnover's `version` by 1, and requires the
    turnover to be in `PENDING_ASSIGNMENT`; any other status draws
    `ERR_INVALID_TURNOVER_STATE`." PRD §3.2: "This is the one boundary movement
    that **never refuses**: every non-terminal turnover whose departing stay is
    this booking re-derives `window_start_at`, `window_end_at`, `window_minutes`,
    `slack_minutes`, `turn_type` and `is_tight`, and has its `version` incremented
    by 1, but a window that would come out non-positive is clamped to 0 rather than
    rejected." PRD §3.5: "On success `started_at` is stamped from the logical clock
    and the turnover's `version` increments by 1."

    Design: Corner/cross_cutting_layers/corner_cc_version_increments_on_every_write_and_never_on_a_read
    """
    world = turnover_at_version_one
    created = world["t1"]
    assert created["version"] == 1, (
        f"creation mints the token at 1, got {created['version']}")
    assert _utc(created["updated_at"]) == _utc("2026-08-01T00:00:00Z"), (
        f"updated_at is a reading of the logical clock, "
        f"got {created['updated_at']}")

    read_once = fx.read_turnover(api, world)
    assert read_once["version"] == 1, (
        f"a single read is not a mutation, got {read_once['version']}")

    listed, _ = validate_paginated(
        api.list_turnovers(COORDINATOR, {"property_id": world["p1"]["id"]}))
    assert listed[0]["version"] == 1, (
        f"the list projection reports the same token, got {listed[0]['version']}")

    offer = validate_success(api.assign_turnover(
        world["t1"]["id"],
        assign_turnover_payload(read_once["version"], world["cc"]["id"]),
        COORDINATOR), 201)
    assert fx.read_turnover(api, world)["version"] == 2, (
        f"the coordinator's offer is the first bump, "
        f"got {fx.read_turnover(api, world)['version']}")

    validate_success(
        api.accept_assignment(offer["id"], {}, world["cleaner_headers"]))
    assert fx.read_turnover(api, world)["version"] == 3, (
        f"a cleaner's write on a sibling aggregate bumps it too, "
        f"got {fx.read_turnover(api, world)['version']}")

    fx.reset_clock(api, "2026-08-08T16:00:00Z")
    validate_success(api.checkout_booking(world["b_out"]["id"], {}, COORDINATOR))
    after_checkout = fx.read_turnover(api, world)
    assert after_checkout["version"] == 4, (
        f"a write to the booking bumped the turnover that re-derived its window, "
        f"got {after_checkout['version']}")
    assert _utc(after_checkout["updated_at"]) == _utc("2026-08-08T16:00:00Z"), (
        f"updated_at tracks the same logical clock, "
        f"got {after_checkout['updated_at']}")

    started = validate_success(
        api.start_turnover(world["t1"]["id"], {}, world["cleaner_headers"]))
    assert started["version"] == 5, (
        f"the transition response itself carries the fifth token, "
        f"got {started['version']}")


# ─── consistency_model ────────────────────────────────────────────────────

def test_04_every_cascade_effect_is_readable_on_the_very_next_request(
        api, offered_pair_world):
    """Acceptance money and approval stock are both settled before their responses land.

    PRD §2.10: "Where this document says that an operation revokes offers, voids
    pay lines, reverts a parent status, blocks a guest's arrival, or debits the
    payout ledger, every one of those secondary effects is part of the same request
    and must be applied before the response is emitted. The consistency model is
    immediate: there is no deferred or eventual settlement anywhere in this API."
    PRD §3.5: "On success the offer moves `OFFERED → ACCEPTED` with `accepted_at`
    stamped from the logical clock, the turnover moves `PENDING_ASSIGNMENT →
    SCHEDULED` and its `version` increments by 1, a pay line is created in `status`
    `PROVISIONAL` under the `PROVISIONAL` variant, and the cleaner's
    `pending_payout_cents` increases by that pay line's `net_cents`." PRD §3.6:
    "**Approval** moves the row `SUBMITTED → VERIFIED` and requires the row to have
    been `SUBMITTED` and the turnover to be in one of `IN_PROGRESS`,
    `AWAITING_VERIFICATION` or `REWORK_REQUIRED`. For a `RESTOCK` row, approval is
    the moment stock actually leaves the closet: one stock movement is appended per
    submitted restock entry, in the exact order the entries were supplied, each
    with `reason` `RESTOCK_USE` and a `delta_qty` equal to the negative of that
    entry's `qty_used`; each affected supply line then re-projects `on_hand_qty`,
    recomputes `below_par`, and has its `version` incremented by 1." PRD §3.6:
    "That chargeback is computed **per line and then summed**, and the order is
    normative: for each restock entry in the order supplied, multiply the supply
    line's `unit_cost_cents` by the entry's `qty_used` and then by a waste factor of
    1.075 — a seven-and-a-half percent allowance for spoilage and partial packs —
    and round that product half up to whole cents; the row's `restock_charge_cents`
    is the sum of those already-rounded per-line charges." PRD §3.6: "While the
    clean is underway, and **only** while the turnover's current status is one of
    `IN_PROGRESS`, `AWAITING_VERIFICATION` or `REWORK_REQUIRED`, the turnover's
    status is re-derived after every single child change by this ordered rule, first
    match winning: if any child sits in `REJECTED` the turnover is
    `REWORK_REQUIRED`; otherwise if any child sits in `PENDING` the turnover is
    `IN_PROGRESS`; otherwise — every child being `VERIFIED` or `WAIVED` — the
    turnover is `AWAITING_VERIFICATION`."

    Design: Corner/consistency_model/corner_consistency_every_cascade_effect_is_readable_in_the_same_response
    """
    world = offered_pair_world
    sl1, sl2 = world["supply_lines"]
    assert fx.read_cleaner(api, world)["pending_payout_cents"] == 0, (
        f"a mere offer moves no money, "
        f"got {fx.read_cleaner(api, world)['pending_payout_cents']}")

    accepted = validate_success(
        api.accept_assignment(world["a1"]["id"], {}, world["cleaner_headers"]))
    assert accepted["status"] == "ACCEPTED", (
        f"the offer is accepted, got {accepted['status']}")
    assert same_instant(accepted["accepted_at"], "2026-08-01T00:00:00Z"), (
        f"accepted_at reads the logical clock, got {accepted['accepted_at']}")

    lines, lines_meta = validate_paginated(
        api.list_pay_lines(COORDINATOR, {"turnover_id": world["t1"]["id"]}))
    assert lines_meta["total_count"] == 1, (
        f"the pay line exists on the very next read, "
        f"got {lines_meta['total_count']}")
    assert lines[0]["variant"] == "PROVISIONAL", (
        f"it was minted under the provisional variant, got {lines[0]['variant']}")
    assert lines[0]["net_cents"] == 12554, (
        f"11254 gross plus 1300 of bonuses, got {lines[0]['net_cents']}")
    assert fx.read_cleaner(api, world)["pending_payout_cents"] == 12554, (
        f"the payout counter moved inside the accept transaction, "
        f"got {fx.read_cleaner(api, world)['pending_payout_cents']}")
    assert fx.read_turnover(api, world)["status"] == "SCHEDULED", (
        f"the parent transition is visible immediately, "
        f"got {fx.read_turnover(api, world)['status']}")

    tasks = fx.start_clean(api, world)
    restock_row = tasks[3]
    assert restock_row["category"] == "RESTOCK", (
        f"the fourth generated row books supply consumption, "
        f"got {restock_row['category']}")

    validate_success(api.submit_checklist_task(
        restock_row["id"],
        submit_task_payload(
            photo_uri="https://cdn.example.com/supply_restock.jpg",
            restock_entries=[restock_entry(sl1["id"], 1),
                             restock_entry(sl2["id"], 1)]),
        world["cleaner_headers"]))

    reviewed = validate_success(api.review_checklist_task(
        restock_row["id"], review_task_payload("APPROVE"), REVIEWER))
    assert reviewed["status"] == "VERIFIED", (
        f"approval clears the row, got {reviewed['status']}")
    assert reviewed["restock_charge_cents"] == 474, (
        f"280 plus 194 is returned by the review call itself, "
        f"got {reviewed['restock_charge_cents']}")

    after_sl1 = fx.read_supply_line(api, sl1["id"])
    after_sl2 = fx.read_supply_line(api, sl2["id"])
    assert after_sl1["on_hand_qty"] == 5, (
        f"one sheet set left the closet in that same request, "
        f"got {after_sl1['on_hand_qty']}")
    assert after_sl1["below_par"] is False, (
        f"five still exceeds the reorder point of zero, "
        f"got {after_sl1['below_par']}")
    assert after_sl2["on_hand_qty"] == 7, (
        f"one towel left too, got {after_sl2['on_hand_qty']}")

    movements, movements_meta = validate_paginated(api.list_stock_movements(
        COORDINATOR, {"checklist_task_id": restock_row["id"]}))
    assert movements_meta["total_count"] == 2, (
        f"one ledger row per entry is already there, "
        f"got {movements_meta['total_count']}")
    by_line = {row["supply_line_id"]: row for row in movements}
    assert by_line[sl1["id"]]["reason"] == "RESTOCK_USE", (
        f"consumption is booked at approval, "
        f"got {by_line[sl1['id']]['reason']}")
    assert by_line[sl1["id"]]["delta_qty"] == -1, (
        f"the delta negates the quantity used, "
        f"got {by_line[sl1['id']]['delta_qty']}")
    assert by_line[sl1["id"]]["charge_cents"] == 280, (
        f"260 times 1.075 rounds half up to 280, "
        f"got {by_line[sl1['id']]['charge_cents']}")
    assert by_line[sl2["id"]]["charge_cents"] == 194, (
        f"180 times 1.075 rounds half up to 194, "
        f"got {by_line[sl2['id']]['charge_cents']}")

    assert fx.read_turnover(api, world)["status"] == "IN_PROGRESS", (
        f"three rows are still PENDING, so the re-derivation held, "
        f"got {fx.read_turnover(api, world)['status']}")
