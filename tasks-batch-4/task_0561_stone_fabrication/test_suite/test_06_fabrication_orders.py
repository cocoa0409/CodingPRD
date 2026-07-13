"""Fabrication-order transitions, the create-guard priority chain, resource temporal overlap
on the bay, and the complete-consume-remnant cascade."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_fabrication_order_payload,
    setup_scheduled_fab, setup_complete_fab, setup_measured_template_project,
    setup_priced_project, new_slab, new_bay, new_fab_order,
)


# --------------------------------------------------------------------------
# Corner/state_machines — invalid & terminal transitions, recut loop
# --------------------------------------------------------------------------
def test_qc_from_scheduled_returns_invalid_transition(api, fabricator_headers):
    """PRD §3.5: "A quality check carries a `result` of `PASS`, moving `CUTTING` to
    `QC_PASSED`, or `FAIL`, moving `CUTTING` to `RECUTTING`."
    PRD §2.9: "the server checks that any requested state transition is legal from the target's
    current state (`ERR_INVALID_TRANSITION`, 409)."

    QC requires CUTTING; calling it on a SCHEDULED order is rejected and leaves the state.

    Design: Corner/state_machines/qc_from_scheduled_returns_invalid_transition
    """
    ctx = setup_scheduled_fab()
    resp = api.qc_fabrication_order(ctx["f_id"], {"result": "PASS"}, fabricator_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
    fab = validate_success(api.get_fabrication_order(ctx["f_id"], fabricator_headers))
    assert fab["status"] == "SCHEDULED"


def test_cancel_completed_fab_returns_invalid_transition(api, fabricator_headers):
    """PRD §3.5: "`COMPLETE` and `CANCELLED` are terminal, and any transition attempted from a
    state that does not permit it is rejected as `ERR_INVALID_TRANSITION`."

    Cancelling a COMPLETE order is rejected; the consumed slab is unaffected.

    Design: Corner/state_machines/cancel_completed_fab_returns_invalid_transition_terminal
    """
    ctx = setup_complete_fab()
    resp = api.cancel_fabrication_order(ctx["f_id"], fabricator_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
    slab = validate_success(api.get_slab(ctx["sl_id"], fabricator_headers))
    assert slab["status"] == "CONSUMED"


def test_recut_loop_qc_fail_then_restart_cut(api, fabricator_headers):
    """PRD §3.5: "A quality check carries a `result` of `PASS`, moving `CUTTING` to
    `QC_PASSED`, or `FAIL`, moving `CUTTING` to `RECUTTING`; from `RECUTTING`, beginning the cut
    again returns the order to `CUTTING`, forming the recut loop."

    Design: Corner/state_machines/recut_loop_qc_fail_then_restart_cut
    """
    ctx = setup_scheduled_fab()
    validate_success(api.start_cut(ctx["f_id"], fabricator_headers))
    validate_success(api.qc_fabrication_order(ctx["f_id"], {"result": "FAIL"}, fabricator_headers))
    restarted = validate_success(api.start_cut(ctx["f_id"], fabricator_headers))
    assert restarted["status"] == "CUTTING"


# --------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency — fab create blocked by unapproved template
# --------------------------------------------------------------------------
def test_fab_create_blocked_by_measured_template(api, fabricator_headers):
    """PRD §3.5: "The referenced template must be `APPROVED`, or the create is rejected with
    `ERR_TEMPLATE_NOT_APPROVED` (409)."

    Design: Difficulty/cross_entity_state_dependency/fab_create_blocked_by_unapproved_template
    """
    ctx = setup_measured_template_project(with_deposit=True)
    sl = new_slab()
    b = new_bay()
    payload = create_fabrication_order_payload(
        project_id=ctx["p_id"], template_id=ctx["t_id"], slab_id=sl["id"], bay_id=b["id"],
        pieces=[{"label": "A", "sqft": 25}])
    resp = api.create_fabrication_order(payload, fabricator_headers)
    validate_error(resp, ApiErrorId.ERR_TEMPLATE_NOT_APPROVED)


def test_fab_create_blocked_leaves_slab_in_stock(api, fabricator_headers):
    """PRD §3.5: "On successful creation the order's `actual_consumed_sqft` is computed, the
    referenced slab moves from `IN_STOCK` to `RESERVED` with its `reserved_sqft` set to that
    consumption and `remaining_sqft` recomputed."

    A rejected create (template only MEASURED) reserves nothing; the slab stays IN_STOCK.

    Design: Difficulty/cross_entity_state_dependency/fab_create_blocked_by_unapproved_template
    """
    ctx = setup_measured_template_project(with_deposit=True)
    sl = new_slab()
    b = new_bay()
    payload = create_fabrication_order_payload(
        project_id=ctx["p_id"], template_id=ctx["t_id"], slab_id=sl["id"], bay_id=b["id"],
        pieces=[{"label": "A", "sqft": 25}])
    api.create_fabrication_order(payload, fabricator_headers)
    slab = validate_success(api.get_slab(sl["id"], fabricator_headers))
    assert slab["status"] == "IN_STOCK"


# --------------------------------------------------------------------------
# Corner/validations — deposit-not-paid, invalid interval
# --------------------------------------------------------------------------
def test_fab_before_deposit_returns_deposit_not_paid(api, fabricator_headers):
    """PRD §3.5: "The project's `payment_status` must be `DEPOSIT_PAID` or `PAID_IN_FULL`, or it
    is rejected with `ERR_DEPOSIT_NOT_PAID` (409)."

    Design: Corner/validations/fab_before_deposit_returns_deposit_not_paid
    """
    ctx = setup_priced_project(with_deposit=False, sink_cutouts=0)
    sl = new_slab()
    b = new_bay()
    payload = create_fabrication_order_payload(
        project_id=ctx["p_id"], template_id=ctx["t_id"], slab_id=sl["id"], bay_id=b["id"],
        pieces=[{"label": "A", "sqft": 25}])
    resp = api.create_fabrication_order(payload, fabricator_headers)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_PAID)


def test_fab_invalid_interval_returns_invalid_interval(api, fabricator_headers):
    """PRD §3.5: "The `scheduled_end` must be strictly after the `scheduled_start`, or it is
    rejected with `ERR_INVALID_INTERVAL` (422)."

    Design: Corner/validations/fab_invalid_interval_returns_invalid_interval
    """
    ctx = setup_priced_project(with_deposit=True, sink_cutouts=0)
    sl = new_slab()
    b = new_bay()
    payload = create_fabrication_order_payload(
        project_id=ctx["p_id"], template_id=ctx["t_id"], slab_id=sl["id"], bay_id=b["id"],
        scheduled_start="2026-06-10T08:00:00Z", scheduled_end="2026-06-10T08:00:00Z",
        pieces=[{"label": "A", "sqft": 25}])
    resp = api.create_fabrication_order(payload, fabricator_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL)


# --------------------------------------------------------------------------
# Difficulty/boundary_precision_check — empty pieces boundary
# --------------------------------------------------------------------------
def test_empty_pieces_rejected_on_fab_create(api, fabricator_headers):
    """PRD §3.5: "The `pieces` array must contain at least one piece, or it is rejected with
    `ERR_NO_PIECES` (422)."

    Design: Difficulty/boundary_precision_check/empty_pieces_rejected_on_fab_create_boundary
    """
    ctx = setup_priced_project(with_deposit=True, sink_cutouts=0)
    sl = new_slab()
    b = new_bay()
    payload = create_fabrication_order_payload(
        project_id=ctx["p_id"], template_id=ctx["t_id"], slab_id=sl["id"], bay_id=b["id"], pieces=[])
    resp = api.create_fabrication_order(payload, fabricator_headers)
    validate_error(resp, ApiErrorId.ERR_NO_PIECES)


def test_empty_pieces_rejection_leaves_slab_in_stock(api, fabricator_headers):
    """PRD §3.5: "The `pieces` array must contain at least one piece, or it is rejected with
    `ERR_NO_PIECES` (422)."
    PRD §3.5: "On successful creation ... the referenced slab moves from `IN_STOCK` to
    `RESERVED`." — a rejected create reserves nothing.

    Design: Difficulty/boundary_precision_check/empty_pieces_rejected_on_fab_create_boundary
    """
    ctx = setup_priced_project(with_deposit=True, sink_cutouts=0)
    sl = new_slab()
    b = new_bay()
    payload = create_fabrication_order_payload(
        project_id=ctx["p_id"], template_id=ctx["t_id"], slab_id=sl["id"], bay_id=b["id"], pieces=[])
    api.create_fabrication_order(payload, fabricator_headers)
    slab = validate_success(api.get_slab(sl["id"], fabricator_headers))
    assert slab["status"] == "IN_STOCK"


# --------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict — slab-constraint beats bay-temporal
# --------------------------------------------------------------------------
def test_slab_not_available_beats_bay_unavailable(api, fabricator_headers):
    """PRD §3.5: "The referenced slab must be `IN_STOCK`, or it is rejected with
    `ERR_SLAB_NOT_AVAILABLE` (409). The `scheduled_end` must be strictly after the
    `scheduled_start`, or it is rejected with `ERR_INVALID_INTERVAL` (422). Finally, the bay
    must be free for the requested window: the interval is treated as half-open, so the create
    is rejected with `ERR_BAY_UNAVAILABLE` (409)."

    The slab guard runs before the bay guard, so a create that both reuses a RESERVED slab and
    overlaps the bay returns ERR_SLAB_NOT_AVAILABLE.

    Design: Difficulty/priority_pair_validation_conflict/constraint_slab_beats_temporal_bay_on_fab_create
    """
    ctx = setup_scheduled_fab()  # SL1 RESERVED, BAY1 booked [08:00, 12:00)
    payload = create_fabrication_order_payload(
        project_id=ctx["p_id"], template_id=ctx["t_id"], slab_id=ctx["sl_id"], bay_id=ctx["b_id"],
        scheduled_start="2026-06-10T11:00:00Z", scheduled_end="2026-06-10T13:00:00Z",
        pieces=[{"label": "C", "sqft": 20}])
    resp = api.create_fabrication_order(payload, fabricator_headers)
    validate_error(resp, ApiErrorId.ERR_SLAB_NOT_AVAILABLE)


def test_reserved_slab_alone_returns_slab_not_available(api, fabricator_headers):
    """PRD §3.5: "The referenced slab must be `IN_STOCK`, or it is rejected with
    `ERR_SLAB_NOT_AVAILABLE` (409)."

    Reusing a RESERVED slab with a bay window that abuts (does not overlap) the first booking
    still fails purely on the slab guard.

    Design: Difficulty/priority_pair_validation_conflict/constraint_slab_beats_temporal_bay_on_fab_create
    """
    ctx = setup_scheduled_fab()  # SL1 RESERVED, BAY1 booked [08:00, 12:00)
    payload = create_fabrication_order_payload(
        project_id=ctx["p_id"], template_id=ctx["t_id"], slab_id=ctx["sl_id"], bay_id=ctx["b_id"],
        scheduled_start="2026-06-10T12:00:00Z", scheduled_end="2026-06-10T14:00:00Z",
        pieces=[{"label": "C", "sqft": 20}])
    resp = api.create_fabrication_order(payload, fabricator_headers)
    validate_error(resp, ApiErrorId.ERR_SLAB_NOT_AVAILABLE)


# --------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap — bay half-open interval semantics
# --------------------------------------------------------------------------
def test_bay_half_open_overlap_rejected(api, fabricator_headers):
    """PRD §3.5: "the create is rejected with `ERR_BAY_UNAVAILABLE` (409) if any non-cancelled
    fabrication order on the same bay overlaps such that this order's start is before that
    order's end and that order's start is before this order's end — abutting intervals where
    one ends exactly when the other starts are allowed."

    [11:00, 13:00) overlaps the existing [08:00, 12:00) booking on the same bay.

    Design: Difficulty/resource_temporal_overlap/bay_half_open_overlap_rejected
    """
    ctx = setup_priced_project(with_deposit=True, sink_cutouts=0)
    sl1 = new_slab(slab_label="SL1")
    sl2 = new_slab(slab_label="SL2")
    b = new_bay()
    new_fab_order(ctx["p_id"], ctx["t_id"], sl1["id"], b["id"],
                  start="2026-06-10T08:00:00Z", end="2026-06-10T12:00:00Z")
    payload = create_fabrication_order_payload(
        project_id=ctx["p_id"], template_id=ctx["t_id"], slab_id=sl2["id"], bay_id=b["id"],
        scheduled_start="2026-06-10T11:00:00Z", scheduled_end="2026-06-10T13:00:00Z",
        pieces=[{"label": "C", "sqft": 20}])
    resp = api.create_fabrication_order(payload, fabricator_headers)
    validate_error(resp, ApiErrorId.ERR_BAY_UNAVAILABLE)


def test_bay_abutting_interval_allowed(api, fabricator_headers):
    """PRD §3.5: "abutting intervals where one ends exactly when the other starts are allowed."

    [12:00, 14:00) abuts the existing [08:00, 12:00) booking end-to-start, so the create is
    accepted.

    Design: Difficulty/resource_temporal_overlap/bay_half_open_overlap_rejected
    """
    ctx = setup_priced_project(with_deposit=True, sink_cutouts=0)
    sl1 = new_slab(slab_label="SL1")
    sl2 = new_slab(slab_label="SL2")
    b = new_bay()
    new_fab_order(ctx["p_id"], ctx["t_id"], sl1["id"], b["id"],
                  start="2026-06-10T08:00:00Z", end="2026-06-10T12:00:00Z")
    payload = create_fabrication_order_payload(
        project_id=ctx["p_id"], template_id=ctx["t_id"], slab_id=sl2["id"], bay_id=b["id"],
        scheduled_start="2026-06-10T12:00:00Z", scheduled_end="2026-06-10T14:00:00Z",
        pieces=[{"label": "C", "sqft": 20}])
    data = validate_success(api.create_fabrication_order(payload, fabricator_headers), expected_status=201)
    assert data["status"] == "SCHEDULED"


# --------------------------------------------------------------------------
# Difficulty/transitive_cascade — complete -> consume -> remnant (depth 3)
# --------------------------------------------------------------------------
def test_fab_complete_consumes_slab(api, fabricator_headers):
    """PRD §3.5: "Completing the order advances `QC_PASSED` to `COMPLETE`, at which point the
    reserved slab is consumed (moving it to `CONSUMED`) and a remnant is created from the
    leftover area, as in §2.6 and §3.4."

    Design: Difficulty/transitive_cascade/fab_complete_consume_cascade_depth3
    """
    ctx = setup_scheduled_fab(nominal_sqft=50)
    api.start_cut(ctx["f_id"], fabricator_headers)
    api.qc_fabrication_order(ctx["f_id"], {"result": "PASS"}, fabricator_headers)
    completed = validate_success(api.complete_fabrication_order(ctx["f_id"], fabricator_headers))
    assert completed["status"] == "COMPLETE"
    slab = validate_success(api.get_slab(ctx["sl_id"], fabricator_headers))
    assert slab["status"] == "CONSUMED"


def test_fab_complete_creates_remnant_from_leftover(api, fabricator_headers):
    """PRD §3.4: "When a slab is finally consumed, the leftover becomes a **Remnant** child of
    the slab, recording its `slab_id` and an `area_sqft` equal to the slab's `nominal_sqft`
    minus the consuming order's `actual_consumed_sqft`."

    50 - 40.20 = 9.80.

    Design: Difficulty/transitive_cascade/fab_complete_consume_cascade_depth3
    """
    ctx = setup_scheduled_fab(nominal_sqft=50)
    api.start_cut(ctx["f_id"], fabricator_headers)
    api.qc_fabrication_order(ctx["f_id"], {"result": "PASS"}, fabricator_headers)
    api.complete_fabrication_order(ctx["f_id"], fabricator_headers)
    remnants, _meta = validate_paginated(api.list_slab_remnants(ctx["sl_id"], fabricator_headers))
    assert len(remnants) == 1
    assert remnants[0]["area_sqft"] == pytest.approx(9.80, abs=0.005)
