"""LoadInSlot reservations: half-open interval overlap semantics on (bay, kind)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_load_in_slot,
    reserve_slot, setup_approved_ctx,
)


def _ctx_with_slot(api):
    """SCHEDULING ctx with one NORTH/LOAD_IN slot [09:00, 11:00) reserved."""
    ctx = setup_approved_ctx()
    res = reserve_slot(
        ctx["event"]["id"], ctx["assignment"]["id"], ctx["vendor"]["id"],
        kind="LOAD_IN", starts_at="2026-06-01T09:00:00Z",
        ends_at="2026-06-01T11:00:00Z", bay="NORTH",
    )
    slot = validate_success(res, 201)
    assert_load_in_slot(slot)
    return ctx


def test_adjacent_slot_accepted_and_one_minute_overlap_rejected(api):
    """PRD §3.5: "Equivalently, there is no conflict when the new slot ends at or
    before the existing slot's start, or starts at or after the existing slot's
    end — back-to-back reservations on the same bay are explicitly permitted."
    PRD §3.5: "A conflicting reservation is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/boundary_precision_check/load_in_slot_adjacency_half_open
    """
    ctx = _ctx_with_slot(api)
    event_id = ctx["event"]["id"]

    # Boundary: starts exactly when the existing slot ends (11:00 == 11:00).
    adjacent = reserve_slot(
        event_id, ctx["assignment"]["id"], ctx["vendor"]["id"],
        kind="LOAD_IN", starts_at="2026-06-01T11:00:00Z",
        ends_at="2026-06-01T13:00:00Z", bay="NORTH",
    )
    slot = validate_success(adjacent, 201)
    assert_load_in_slot(slot)

    # One minute inside the existing slot's span must reject.
    overlapping = reserve_slot(
        event_id, ctx["assignment"]["id"], ctx["vendor"]["id"],
        kind="LOAD_IN", starts_at="2026-06-01T10:59:00Z",
        ends_at="2026-06-01T12:00:00Z", bay="NORTH",
    )
    validate_error(overlapping, ApiErrorId.ERR_SLOT_OVERLAP, expected_status=409)


def test_no_conflict_across_bay_or_kind(api):
    """PRD §3.5: "Slots are half-open intervals — a slot occupies the span from
    `starts_at` inclusive to `ends_at` exclusive — and two slots conflict only when
    they share both bay and kind and their spans genuinely intersect: a new slot
    conflicts with an existing one when it starts before the existing slot ends and
    the existing slot starts before the new one ends."

    Design: Difficulty/boundary_precision_check/load_in_slot_adjacency_half_open
    """
    ctx = _ctx_with_slot(api)
    event_id = ctx["event"]["id"]

    # Identical span on the other bay: bay differs, so no conflict.
    other_bay = reserve_slot(
        event_id, ctx["assignment"]["id"], ctx["vendor"]["id"],
        kind="LOAD_IN", starts_at="2026-06-01T09:00:00Z",
        ends_at="2026-06-01T11:00:00Z", bay="SOUTH",
    )
    validate_success(other_bay, 201)

    # Identical span, same bay, different kind: kind differs, so no conflict.
    other_kind = reserve_slot(
        event_id, ctx["assignment"]["id"], ctx["vendor"]["id"],
        kind="LOAD_OUT", starts_at="2026-06-01T09:00:00Z",
        ends_at="2026-06-01T11:00:00Z", bay="NORTH",
    )
    validate_success(other_kind, 201)


def test_partial_overlap_rejected(api):
    """PRD §3.5: "Slots are half-open intervals — a slot occupies the span from
    `starts_at` inclusive to `ends_at` exclusive — and two slots conflict only when
    they share both bay and kind and their spans genuinely intersect: a new slot
    conflicts with an existing one when it starts before the existing slot ends and
    the existing slot starts before the new one ends."
    PRD §3.5: "A conflicting reservation is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/load_in_slot_half_open_semantics
    """
    ctx = _ctx_with_slot(api)
    res = reserve_slot(
        ctx["event"]["id"], ctx["assignment"]["id"], ctx["vendor"]["id"],
        kind="LOAD_IN", starts_at="2026-06-01T10:30:00Z",
        ends_at="2026-06-01T12:00:00Z", bay="NORTH",
    )
    validate_error(res, ApiErrorId.ERR_SLOT_OVERLAP, expected_status=409)


def test_contained_overlap_rejected(api):
    """PRD §3.5: "Slots are half-open intervals — a slot occupies the span from
    `starts_at` inclusive to `ends_at` exclusive — and two slots conflict only when
    they share both bay and kind and their spans genuinely intersect: a new slot
    conflicts with an existing one when it starts before the existing slot ends and
    the existing slot starts before the new one ends."
    PRD §3.5: "A conflicting reservation is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/load_in_slot_half_open_semantics
    """
    ctx = _ctx_with_slot(api)
    # Fully contained inside the existing [09:00, 11:00) span: genuinely intersects.
    res = reserve_slot(
        ctx["event"]["id"], ctx["assignment"]["id"], ctx["vendor"]["id"],
        kind="LOAD_IN", starts_at="2026-06-01T09:30:00Z",
        ends_at="2026-06-01T10:30:00Z", bay="NORTH",
    )
    validate_error(res, ApiErrorId.ERR_SLOT_OVERLAP, expected_status=409)
