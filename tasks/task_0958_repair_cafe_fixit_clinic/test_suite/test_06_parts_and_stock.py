"""Parts stock conservation, stock OCC, reservation expiry/availability and
safety holds (PRD §2.8, §2.10, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, TEST_USERS, ApiErrorId,
    make_fixer_headers, assert_part_stock_conservation,
    set_logical_clock, setup_intake_open_event,
    progress_item_to_assigned, progress_item_to_in_repair,
    make_part_stock, reserve_part, commit_reservation, release_reservation,
    report_incident,
)

COORD = TEST_USERS["coordinator_headers"]


# ─── reserve/release/commit conservation ────────────────────────────────────

def test_parts_reserve_release_conserves_on_hand(api):
    """PRD §2.10: "For each `PartStock` row, the physical `quantity_on_hand`
    always equals the initial on-hand quantity, plus the sum of all
    administrative adjustment deltas applied to it, minus the sum of `quantity`
    over its reservations in `COMMITTED` status; and `quantity_reserved` always
    equals the sum of `quantity` over its reservations in `RESERVED` status.
    The derived `quantity_available` is `quantity_on_hand` minus
    `quantity_reserved`. A reserve followed by its own release must leave both
    `quantity_on_hand` and `quantity_reserved` unchanged."
    PRD §3.4: "A commit decrements the stock's `quantity_on_hand` by the
    reserved `quantity`, bumps the stock row's `version` by 1, and recomputes
    `quantity_reserved`, `quantity_available`, and the event's
    `parts_committed_cents` (the sum of `cost_cents` over `COMMITTED`
    reservations of the event's items)."

    Design: Difficulty/compensating_invariant/parts_reserve_release_conserves_on_hand
    """
    ctx = setup_intake_open_event(event_name="Cafe Rho")
    item = progress_item_to_in_repair(ctx, description="Amp",
                                      weight_kg_estimated=4.0)
    stock = make_part_stock(sku="CAP-470U", name="470uF cap",
                            unit_cost_cents=120, quantity_on_hand=10)
    fid = ctx["fixer"]["id"]

    # Reserve 3 then release: both pools return to their pre-reservation state.
    r1 = reserve_part(stock["id"], item["id"], 3, fid)
    release_reservation(r1["id"], fid)
    after_release = validate_success(api.get_part_stock(stock["id"], COORD), 200)
    assert after_release["quantity_on_hand"] == 10
    assert after_release["quantity_reserved"] == 0
    assert_part_stock_conservation(after_release)
    r1_after = validate_success(api.get_part_reservation(r1["id"], COORD), 200)
    assert r1_after["status"] == "RELEASED"

    # Only a commit may move quantity_on_hand.
    r2 = reserve_part(stock["id"], item["id"], 3, fid)
    version_before_commit = validate_success(
        api.get_part_stock(stock["id"], COORD), 200)["version"]
    commit_reservation(r2["id"], fid)
    final = validate_success(api.get_part_stock(stock["id"], COORD), 200)
    assert final["quantity_on_hand"] == 7, "only the commit moved on_hand"
    assert final["quantity_reserved"] == 0
    assert final["quantity_available"] == 7
    assert final["version"] == version_before_commit + 1, (
        "a commit bumps the stock row's version by 1")
    r2_after = validate_success(api.get_part_reservation(r2["id"], COORD), 200)
    assert r2_after["status"] == "COMMITTED"


def test_parts_reserve_updates_reserved_and_available(api):
    """PRD §2.10: "For each `PartStock` row, the physical `quantity_on_hand`
    always equals the initial on-hand quantity, plus the sum of all
    administrative adjustment deltas applied to it, minus the sum of `quantity`
    over its reservations in `COMMITTED` status; and `quantity_reserved` always
    equals the sum of `quantity` over its reservations in `RESERVED` status.
    The derived `quantity_available` is `quantity_on_hand` minus
    `quantity_reserved`. A reserve followed by its own release must leave both
    `quantity_on_hand` and `quantity_reserved` unchanged."

    Design: Difficulty/compensating_invariant/parts_reserve_release_conserves_on_hand
    """
    ctx = setup_intake_open_event(event_name="Cafe Rho-2")
    item = progress_item_to_in_repair(ctx, description="Amp",
                                      weight_kg_estimated=4.0)
    stock = make_part_stock(name="470uF cap", unit_cost_cents=120,
                            quantity_on_hand=10)
    reserve_part(stock["id"], item["id"], 3, ctx["fixer"]["id"])
    stock_after = validate_success(api.get_part_stock(stock["id"], COORD), 200)
    assert stock_after["quantity_reserved"] == 3, (
        "reserved pool sums reservations in RESERVED status")
    assert stock_after["quantity_on_hand"] == 10, (
        "a reservation alone must not touch physical on-hand")
    assert stock_after["quantity_available"] == 7, (
        "quantity_available is quantity_on_hand minus quantity_reserved")
    assert_part_stock_conservation(stock_after)


# ─── OCC on stock adjustment ────────────────────────────────────────────────

def test_occ_patch_stock_stale_version(api):
    """PRD §2.8: "Second, adjusting a part stock row requires
    `expected_part_stock_version` carrying the stock row's last-observed
    `version`; reservation commits decrement on-hand quantity and bump the
    version, so a stale adjustment would overwrite stock it never accounted
    for, and is likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_patch_stock_stale_version
    """
    set_logical_clock()
    stock = make_part_stock(sku="FUSE-10A", name="10A fuse",
                            unit_cost_cents=400, quantity_on_hand=5)
    observed_version = stock["version"]

    # First adjustment with the last-observed version succeeds.
    patched = validate_success(api.adjust_part_stock(
        stock["id"], {"unit_cost_cents": 450,
                      "expected_part_stock_version": observed_version},
        COORD), 200)
    assert patched["unit_cost_cents"] == 450
    assert patched["version"] == observed_version + 1

    # Replaying the same (now stale) version is rejected with ERR_STALE_VERSION.
    res = api.adjust_part_stock(
        stock["id"], {"unit_cost_cents": 475,
                      "expected_part_stock_version": observed_version},
        COORD)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    after = validate_success(api.get_part_stock(stock["id"], COORD), 200)
    assert after["unit_cost_cents"] == 450
    assert after["version"] == observed_version + 1


# ─── reservation expiry / availability / stock floor / safety hold ──────────

def test_reservation_commit_after_expiry_rejected(api):
    """PRD §3.4: "Committing a reservation (`RESERVED → COMMITTED`) requires
    the logical clock to be at or before `expires_at` — a commit attempted past
    expiry is rejected with `ERR_RESERVATION_EXPIRED` without flipping the
    reservation's status — and requires that no `SafetyIncident` of severity
    `HIGH` or `CRITICAL` in status `REPORTED` exists for the item
    (`ERR_SAFETY_HOLD`)."

    Design: Corner/validations/reservation_commit_after_expiry_rejected
    """
    ctx = setup_intake_open_event(event_name="Cafe Lamed")
    item = progress_item_to_in_repair(ctx, description="Amp",
                                      weight_kg_estimated=4.0)
    stock = make_part_stock(sku="CAP-470U", name="470uF cap",
                            unit_cost_cents=120, quantity_on_hand=5)
    reservation = reserve_part(stock["id"], item["id"], 1, ctx["fixer"]["id"])

    # expires_at is the event's ends_at (16:00); 16:00:01 is past it.
    set_logical_clock("2026-06-01T16:00:01Z")
    res = api.commit_reservation(reservation["id"],
                                 make_fixer_headers(ctx["fixer"]["id"]))
    validate_error(res, ApiErrorId.ERR_RESERVATION_EXPIRED)

    reservation_after = validate_success(
        api.get_part_reservation(reservation["id"], COORD), 200)
    assert reservation_after["status"] == "RESERVED", (
        "a rejected commit does not flip the reservation's status")
    stock_after = validate_success(api.get_part_stock(stock["id"], COORD), 200)
    assert stock_after["quantity_on_hand"] == 5


def test_reserve_more_than_available_rejected(api):
    """PRD §3.4: "The stock's `quantity_available` must cover the request, else
    `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/validations/reserve_more_than_available_rejected
    """
    ctx = setup_intake_open_event(event_name="Cafe Mem")
    item = progress_item_to_assigned(ctx, description="Speaker",
                                     weight_kg_estimated=1.9)
    stock = make_part_stock(sku="COIL-8R", name="voice coil",
                            unit_cost_cents=700, quantity_on_hand=2)
    # quantity_available 2 < requested 3.
    res = api.create_part_reservation(
        {"part_stock_id": stock["id"], "repair_item_id": item["id"],
         "quantity": 3},
        make_fixer_headers(ctx["fixer"]["id"]))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STOCK)
    stock_after = validate_success(api.get_part_stock(stock["id"], COORD), 200)
    assert stock_after["quantity_reserved"] == 0
    assert stock_after["quantity_on_hand"] == 2


def test_patch_stock_below_reserved_rejected(api):
    """PRD §3.4: "A `Coordinator` adjusts a stock row's `quantity_on_hand` or
    `unit_cost_cents` through the stock-adjustment write, which is the second
    OCC-protected operation: it requires `expected_part_stock_version` matching
    the row's current `version`, rejected with `ERR_STALE_VERSION` on mismatch,
    and it may never push `quantity_on_hand` below the live
    `quantity_reserved` (`ERR_STOCK_BELOW_RESERVED`)."

    Design: Corner/validations/patch_stock_below_reserved_rejected
    """
    ctx = setup_intake_open_event(event_name="Cafe Nun")
    item = progress_item_to_assigned(ctx, description="Drill",
                                     weight_kg_estimated=1.6)
    stock = make_part_stock(sku="BRUSH-6", name="carbon brush",
                            unit_cost_cents=250, quantity_on_hand=5)
    reserve_part(stock["id"], item["id"], 4, ctx["fixer"]["id"])
    current = validate_success(api.get_part_stock(stock["id"], COORD), 200)

    # 4 units are RESERVED; pushing on_hand to 3 would go below reserved.
    res = api.adjust_part_stock(
        stock["id"], {"quantity_on_hand": 3,
                      "expected_part_stock_version": current["version"]},
        COORD)
    validate_error(res, ApiErrorId.ERR_STOCK_BELOW_RESERVED)
    after = validate_success(api.get_part_stock(stock["id"], COORD), 200)
    assert after["quantity_on_hand"] == 5
    assert after["version"] == current["version"], (
        "a rejected adjustment must not bump the version")


def test_safety_hold_blocks_part_commit(api):
    """PRD §3.4: "Committing a reservation (`RESERVED → COMMITTED`) requires
    the logical clock to be at or before `expires_at` — a commit attempted past
    expiry is rejected with `ERR_RESERVATION_EXPIRED` without flipping the
    reservation's status — and requires that no `SafetyIncident` of severity
    `HIGH` or `CRITICAL` in status `REPORTED` exists for the item
    (`ERR_SAFETY_HOLD`)."

    Design: Corner/validations/safety_hold_blocks_part_commit
    """
    ctx = setup_intake_open_event(event_name="Cafe Pe")
    item = progress_item_to_in_repair(ctx, description="Heater",
                                      weight_kg_estimated=5.0, severity=5,
                                      estimated_difficulty=3,
                                      diagnosis="element")
    stock = make_part_stock(sku="ELT-2KW", name="2kW element",
                            unit_cost_cents=900, quantity_on_hand=5)
    reservation = reserve_part(stock["id"], item["id"], 1, ctx["fixer"]["id"])
    # An open HIGH incident on the item blocks the commit.
    report_incident(ctx["event"]["id"], severity="HIGH",
                    description="scorch smell", item_id=item["id"])

    res = api.commit_reservation(reservation["id"],
                                 make_fixer_headers(ctx["fixer"]["id"]))
    validate_error(res, ApiErrorId.ERR_SAFETY_HOLD)

    reservation_after = validate_success(
        api.get_part_reservation(reservation["id"], COORD), 200)
    assert reservation_after["status"] == "RESERVED"
    stock_after = validate_success(api.get_part_stock(stock["id"], COORD), 200)
    assert stock_after["quantity_on_hand"] == 5
