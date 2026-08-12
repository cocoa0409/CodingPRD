"""Packaging, shelf-life expiry, FEFO allocation, shipping."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_commitment_with_line,
    get_success_data,
    pack_flush_lot,
    record_flush_on_cycle,
    report_and_confirm_contamination,
    setup_fruiting_cycle,
    setup_fruiting_cycle_with_graded_flush,
    validate_error,
    validate_paginated,
    validate_success,
)

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_manager_headers"]
ANY = TEST_USERS["any_headers"]


def _iso_instant(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp to an aware datetime so assertions
    compare the instant, not the wire string (PRD §2.4 pins the
    3-fractional-digit format only for created_at/updated_at)."""
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_pack_quarantine_beats_grade_kg_shortfall(api):
    """PRD §2.8: "State preconditions come next (priority 7), then safety
    gating such as quarantine blocks (priority 8), then temporal rules such
    as window overlap and clock checks (priority 9), then business
    constraints such as capacity, sufficiency, and segregation-of-duties
    checks (priority 10)."
    PRD §3.5: "The room of the flush's cycle must not be `QUARANTINED`,
    otherwise `ERR_ROOM_QUARANTINED`."

    When the flush is GRADED (state passes) but its room is QUARANTINED and
    the requested pack exceeds remaining grade-A kg, the safety error wins
    over the business-constraint error.

    Design: Difficulty/priority_pair_validation_conflict/pack_quarantine_beats_grade_kg_shortfall
    """
    _variety, _batch, room, rc, flush = setup_fruiting_cycle_with_graded_flush()
    # Quarantine the room: severity >= 4 aborts the cycle but the flush stays GRADED.
    report_and_confirm_contamination(room, rc, severity=4)

    resp = api.pack_flush(
        flush["id"],
        {"grade": "A", "units": 100, "kg_per_unit": 1.0},
        FARM,
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_QUARANTINED)


def test_pack_quarantine_persists_no_lot(api):
    """PRD §3.5: "The room of the flush's cycle must not be `QUARANTINED`,
    otherwise `ERR_ROOM_QUARANTINED`." A rejected pack creates no lot.

    Design: Difficulty/priority_pair_validation_conflict/pack_quarantine_beats_grade_kg_shortfall
    """
    _variety, _batch, room, rc, flush = setup_fruiting_cycle_with_graded_flush()
    report_and_confirm_contamination(room, rc, severity=4)

    resp = api.pack_flush(
        flush["id"],
        {"grade": "A", "units": 100, "kg_per_unit": 1.0},
        FARM,
    )
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_ROOM_QUARANTINED"
    assert body["data"]["error_id"] != "ERR_INSUFFICIENT_GRADE_KG"

    lots, _meta = validate_paginated(api.list_packaged_lots(ANY, params={"flush_id": flush["id"]}))
    assert lots == [], "rejected pack must persist no PackagedLot"


def test_fefo_allocation_prefers_earliest_expiry(api):
    """PRD §3.5: "Candidates are ranked by `expires_at` ascending with ties
    broken by `created_at` ascending, never by id. The sweep then walks the
    ranked list taking whole lots while the running total plus the
    candidate's `lot_kg` stays within `target_kg`, and it stops at the first
    lot that would overshoot — no skipping ahead to a smaller lot. ... Each
    taken lot moves `IN_STOCK → ALLOCATED`, records the line in its
    `allocated_line_id`, and adds its `lot_kg` to the line's `allocated_kg`;
    the response reports the `allocated_lot_ids` and the total
    `allocated_kg`."

    Design: Corner/calculations/fefo_allocation_prefers_earliest_expiry
    """
    variety, _batch, _room, rc, flush = setup_fruiting_cycle_with_graded_flush()

    # lot1: packed at the current clock (2026-05-08), expires 2026-05-13.
    lot1 = pack_flush_lot(flush, grade="A", units=20, kg_per_unit=1.0)
    # lot2: packed a day later, expires 2026-05-14.
    get_success_data(api.set_clock({"to_iso8601": "2026-05-09T00:00:00Z"}, FARM))
    lot2 = pack_flush_lot(flush, grade="A", units=20, kg_per_unit=1.0)

    _buyer, _commitment, line = create_active_commitment_with_line(variety, committed_kg=500.0)

    alloc = api.allocate_commitment_line(line["id"], {"target_kg": 20.0}, SALES)
    data = validate_success(alloc, expected_status=200)
    assert data["allocated_kg"] == 20.0

    lot1_after = get_success_data(api.get_packaged_lot(lot1["id"], ANY))
    lot2_after = get_success_data(api.get_packaged_lot(lot2["id"], ANY))
    assert lot1_after["status"] == "ALLOCATED"
    assert lot1_after["allocated_line_id"] == line["id"]
    assert lot2_after["status"] == "IN_STOCK", (
        "earliest-expiry-first: the 2026-05-13 lot is taken before the 2026-05-14 lot"
    )
    line_after = get_success_data(api.get_commitment_line(line["id"], ANY))
    assert line_after["allocated_kg"] == 20.0


def test_sweep_expires_lot_at_exact_expiry(api):
    """PRD §3.5: "During the daily sweep, any lot in `IN_STOCK` or
    `ALLOCATED` whose `expires_at` is less than or equal to the current clock
    time moves to `EXPIRED` — the boundary is inclusive, so a lot expiring
    exactly at the sweep instant expires."
    PRD §3.5: "its `expires_at` is `packed_at` plus the variety's
    `shelf_life_days` whole days — the exact instant that many days later."

    Design: Difficulty/boundary_precision_check/sweep_expires_lot_at_exact_expiry
    """
    _variety, _batch, _room, rc, flush = setup_fruiting_cycle_with_graded_flush()
    # packed at the canonical 2026-05-08 clock; shelf_life_days 5 -> expires 2026-05-13T00:00:00Z.
    lot = pack_flush_lot(flush, grade="A", units=10, kg_per_unit=1.0)
    # PRD §3.5 pins the instant ("packed_at plus shelf_life_days whole days —
    # the exact instant that many days later"); compare instants, not strings.
    assert _iso_instant(lot["expires_at"]) == _iso_instant("2026-05-13T00:00:00Z")

    # One second before expiry: sweep expires nothing.
    get_success_data(api.set_clock({"to_iso8601": "2026-05-12T23:59:59Z"}, FARM))
    sweep1 = validate_success(api.run_daily_sweep(FARM), expected_status=200)
    assert sweep1["expired_lot_count"] == 0
    assert get_success_data(api.get_packaged_lot(lot["id"], ANY))["status"] == "IN_STOCK"

    # At exactly expires_at: sweep expires the lot (inclusive boundary).
    get_success_data(api.set_clock({"to_iso8601": "2026-05-13T00:00:00Z"}, FARM))
    sweep2 = validate_success(api.run_daily_sweep(FARM), expected_status=200)
    assert sweep2["expired_lot_count"] == 1
    assert get_success_data(api.get_packaged_lot(lot["id"], ANY))["status"] == "EXPIRED"


def test_sweep_inclusive_boundary_expires_lot(api):
    """PRD §3.5: "the boundary is inclusive, so a lot expiring exactly at the
    sweep instant expires."

    Design: Difficulty/boundary_precision_check/sweep_expires_lot_at_exact_expiry
    """
    _variety, _batch, _room, rc, flush = setup_fruiting_cycle_with_graded_flush()
    lot = pack_flush_lot(flush, grade="A", units=10, kg_per_unit=1.0)

    get_success_data(api.set_clock({"to_iso8601": "2026-05-13T00:00:00Z"}, FARM))
    sweep = validate_success(api.run_daily_sweep(FARM), expected_status=200)
    assert sweep["expired_lot_count"] == 1
    after = get_success_data(api.get_packaged_lot(lot["id"], ANY))
    assert after["status"] == "EXPIRED"


def test_lot_ship_after_expiry_rejected(api):
    """PRD §3.5: "Shipping, by contrast, uses a strict guard: a lot may ship
    only while `expires_at` is strictly greater than the current clock time,
    and equality is rejected with `ERR_LOT_EXPIRED`."

    With the clock past expiry (and no sweep run), the ALLOCATED lot still
    ships-fails; expiry is materialized only by the sweep.

    Design: Corner/validations/lot_ship_after_expiry_rejected
    """
    variety, _batch, _room, rc, flush = setup_fruiting_cycle_with_graded_flush()
    lot = pack_flush_lot(flush, grade="A", units=20, kg_per_unit=1.0)
    _buyer, _commitment, line = create_active_commitment_with_line(variety, committed_kg=500.0)
    get_success_data(api.allocate_commitment_line(line["id"], {"target_kg": 20.0}, SALES))

    # Move the clock past expiry (2026-05-13) without running a sweep.
    get_success_data(api.set_clock({"to_iso8601": "2026-05-14T00:00:00Z"}, FARM))

    resp = api.ship_packaged_lot(lot["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED)
    lot_after = get_success_data(api.get_packaged_lot(lot["id"], ANY))
    assert lot_after["status"] == "ALLOCATED", (
        "no sweep ran, so the lot has not transitioned to EXPIRED"
    )
    line_after = get_success_data(api.get_commitment_line(line["id"], ANY))
    assert line_after["delivered_kg"] == 0.0


def test_lot_ship_from_in_stock_rejected(api):
    """PRD §3.5: "Shipping an `ALLOCATED` lot — again `ERR_LOT_NOT_ALLOCATED`
    otherwise."

    Design: Corner/errors/lot_ship_from_in_stock_rejected
    """
    _variety, _batch, _room, rc, flush = setup_fruiting_cycle_with_graded_flush()
    lot = pack_flush_lot(flush, grade="A", units=20, kg_per_unit=1.0)
    resp = api.ship_packaged_lot(lot["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_ALLOCATED)
    after = get_success_data(api.get_packaged_lot(lot["id"], ANY))
    assert after["status"] == "IN_STOCK"


def test_deallocate_reconciles_line_allocated_kg(api):
    """PRD §3.5: "Deallocating returns an `ALLOCATED` lot to `IN_STOCK`,
    subtracting its `lot_kg` from the line's `allocated_kg` and clearing
    `allocated_line_id`."

    Design: Corner/calculations/deallocate_reconciles_line_allocated_kg
    """
    variety, _batch, _room, rc, flush = setup_fruiting_cycle_with_graded_flush()
    lot = pack_flush_lot(flush, grade="A", units=20, kg_per_unit=1.0)
    _buyer, _commitment, line = create_active_commitment_with_line(variety, committed_kg=500.0)
    get_success_data(api.allocate_commitment_line(line["id"], {"target_kg": 20.0}, SALES))

    line_mid = get_success_data(api.get_commitment_line(line["id"], ANY))
    assert line_mid["allocated_kg"] == 20.0

    get_success_data(api.deallocate_packaged_lot(lot["id"], SALES))

    lot_after = get_success_data(api.get_packaged_lot(lot["id"], ANY))
    assert lot_after["status"] == "IN_STOCK"
    assert lot_after["allocated_line_id"] is None

    line_after = get_success_data(api.get_commitment_line(line["id"], ANY))
    assert line_after["allocated_kg"] == 0.0
    assert line_after["delivered_kg"] == 0.0, "deallocate never touches delivered_kg"
