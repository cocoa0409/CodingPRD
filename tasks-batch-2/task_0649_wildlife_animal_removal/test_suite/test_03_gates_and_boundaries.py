"""Safety/capacity/temporal gates on trap placement and monitoring visits, validation
priority conflicts, and boundary-precision checks (relocation band edges, empty-set guard).

Covers difficulty queue A rules priority_pair_validation_conflict, boundary_precision_check,
resource_temporal_overlap, plus corner-queue validation instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    create_capture_payload,
    create_trap_placement_payload,
    create_monitoring_visit_payload,
    create_permit_approve_payload,
    make_field_technician_headers,
    setup_open_work_order,
    setup_draft_quote,
    set_trap,
    start_repair,
    get_first_permit,
    deny_first_permit,
    fetch_trap_placement,
)
import test_helpers as th

api = th.api_client
_DISPATCHER = th.TEST_USERS["dispatcher_headers"]
_COMPLIANCE = th.TEST_USERS["compliance_officer_headers"]


# ─── priority_pair_validation_conflict / state_beats_business_safety ─────────

def test_trap_set_on_cancelled_work_order_returns_invalid_state_not_permit_required():
    """PRD §2.12: "Then the target resource's state is checked against the requested
    transition, yielding `ERR_INVALID_STATE` if the transition is not defined from the current
    state."
    PRD §3.8: "First, the permit gate: if the trap's species `is_regulated`, a permit for that
    species on this work order must be `APPROVED`; otherwise the set is rejected with
    `ERR_PERMIT_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_trap_set
    """
    # Regulated species, permit REQUESTED then DENIED -> work order CANCELLED, no approved permit.
    sp_reg = th.create_species(is_regulated=True, risk_weight=2.0,
                               relocation_min_miles=5, relocation_max_miles=25,
                               common_name="Beaver")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=5),
        entry_points=[{"species": sp_reg, "severity": "MAJOR", "estimated_individuals": 2}],
        line_items=[{"species": sp_reg, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    deny_first_permit(wo["id"])  # cancels the work order

    res = api.create_trap_placement(
        wo["id"],
        create_trap_placement_payload(sp_reg["id"], tech["id"]),
        make_field_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_state_check_precedes_business_gates_in_priority_order():
    """PRD §2.12: "Then the target resource's state is checked against the requested
    transition, yielding `ERR_INVALID_STATE` if the transition is not defined from the current
    state. Then, on work-order cancellation only, the optimistic-concurrency check compares
    `expected_work_order_version` and yields `ERR_STALE_VERSION` on mismatch. Domain-specific
    business gates follow in this relative order: the permit-required gate
    (`ERR_PERMIT_REQUIRED`)"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_trap_set
    """
    # Same conflict, asserting the cancelled lifecycle wins over the missing permit gate.
    sp_reg = th.create_species(is_regulated=True, risk_weight=2.0,
                               relocation_min_miles=5, relocation_max_miles=25,
                               common_name="Beaver2")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=5),
        entry_points=[{"species": sp_reg, "severity": "MAJOR", "estimated_individuals": 2}],
        line_items=[{"species": sp_reg, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    deny_first_permit(wo["id"])

    res = api.create_trap_placement(
        wo["id"],
        create_trap_placement_payload(sp_reg["id"], tech["id"]),
        make_field_technician_headers(tech["id"]),
    )
    body = res.json()
    assert body["data"]["error_id"] == "ERR_INVALID_STATE", (
        f"State check must win over the permit gate; got {body['data']['error_id']}"
    )


# ─── priority_pair_validation_conflict / business_temporal_beats_fiscal ──────

def test_window_conflict_beats_kit_exhausted_when_both_violated():
    """PRD §3.8: "Third, the technician-window-conflict gate: the trap's visit window, taken as
    the closed interval from `window_start` to `window_end` and inflated by a buffer on each
    side, must not overlap the buffered window of any other `SET` trap on the same technician"
    PRD §3.8: "Fourth, the kit-capacity gate: a set that would drive the assigned technician's
    `traps_available` below 0 is rejected with `ERR_KIT_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_beats_business_fiscal_on_trap_set
    """
    sp = th.create_species(common_name="Vole")
    tech = th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=1)
    base = setup_open_work_order(
        technician=tech,
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 2, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    # First trap occupies 09:00-10:00, exhausting the kit-of-1.
    set_trap(wo["id"], sp["id"], tech["id"],
             window_start="2026-04-03T09:00:00Z", window_end="2026-04-03T10:00:00Z")
    # Second trap overlaps that window AND kit is exhausted; the window gate must win.
    res = api.create_trap_placement(
        wo["id"],
        create_trap_placement_payload(sp["id"], tech["id"],
                                      window_start="2026-04-03T09:30:00Z",
                                      window_end="2026-04-03T10:30:00Z"),
        make_field_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_TECH_WINDOW_CONFLICT", expected_status=409)


def test_window_conflict_gate_precedes_kit_capacity_gate():
    """PRD §3.8: "Third, the technician-window-conflict gate: the trap's visit window, taken as
    the closed interval from `window_start` to `window_end` and inflated by a buffer on each
    side, must not overlap the buffered window of any other `SET` trap on the same technician;
    an overlap is rejected with `ERR_TECH_WINDOW_CONFLICT`."
    PRD §3.8: "Fourth, the kit-capacity gate: a set that would drive the assigned technician's
    `traps_available` below 0 is rejected with `ERR_KIT_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_beats_business_fiscal_on_trap_set
    """
    sp = th.create_species(common_name="Vole2")
    tech = th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=1)
    base = setup_open_work_order(
        technician=tech,
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 2, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    set_trap(wo["id"], sp["id"], tech["id"],
             window_start="2026-04-03T09:00:00Z", window_end="2026-04-03T10:00:00Z")
    res = api.create_trap_placement(
        wo["id"],
        create_trap_placement_payload(sp["id"], tech["id"],
                                      window_start="2026-04-03T09:30:00Z",
                                      window_end="2026-04-03T10:30:00Z"),
        make_field_technician_headers(tech["id"]),
    )
    body = res.json()
    assert body["data"]["error_id"] == "ERR_TECH_WINDOW_CONFLICT", (
        f"Window-conflict gate must win over kit-capacity gate; got {body['data']['error_id']}"
    )


# ─── boundary_precision_check / relocation_distance_inclusive band edge ──────

def test_relocation_above_max_band_edge_rejected():
    """PRD §3.6: "The release is lawful only when this rounded distance is at least the
    species' `relocation_min_miles` and at most its `relocation_max_miles` — both band edges
    inclusive; a distance outside the band is rejected with `ERR_RELOCATION_DISTANCE` and no
    capture persists."

    Design: Difficulty/boundary_precision_check/relocation_distance_inclusive_lower_band_edge
    """
    sp = th.create_species(relocation_min_miles=5, relocation_max_miles=25, common_name="Chipmunk")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    trap = set_trap(wo["id"], sp["id"], tech["id"])
    # Release at 40.37 -> 25.56 mi (> max 25) -> reject, trap stays SET.
    res = api.create_capture(
        trap["id"],
        create_capture_payload(release_latitude=40.37, release_longitude=-75.0),
        make_field_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_RELOCATION_DISTANCE", expected_status=422)
    trap_after = fetch_trap_placement(trap["id"])
    assert trap_after["status"] == "SET", f"Expected SET (no capture persisted), got {trap_after['status']}"


def test_relocation_within_band_compliant_release_persists():
    """PRD §3.6: "On a compliant release a capture event is created with `disposition` of
    `RELOCATED` (the only disposition that ever persists), and the trap moves from `SET` to
    `SPENT`."

    Design: Difficulty/boundary_precision_check/relocation_distance_inclusive_lower_band_edge
    """
    sp = th.create_species(relocation_min_miles=5, relocation_max_miles=25, common_name="Chipmunk2")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    trap = set_trap(wo["id"], sp["id"], tech["id"])
    # Release at 40.145 -> 10.02 mi (within [5,25]) -> compliant.
    res = api.create_capture(
        trap["id"],
        create_capture_payload(release_latitude=40.145, release_longitude=-75.0),
        make_field_technician_headers(tech["id"]),
    )
    capture = validate_success(res, 201)
    assert capture["release_distance_miles"] == 10.02
    trap_after = fetch_trap_placement(trap["id"])
    assert trap_after["status"] == "SPENT", f"Expected SPENT, got {trap_after['status']}"


# ─── boundary_precision_check / send_quote_empty_line_item_set_rejected ──────

def test_send_quote_with_zero_line_items_rejected():
    """PRD §3.3: "A quote may be sent only while in `DRAFT` and only if it carries at least one
    line item; sending an empty quote is rejected with `ERR_EMPTY_SET`."

    Design: Difficulty/boundary_precision_check/send_quote_empty_line_item_set_rejected
    """
    base = setup_draft_quote(line_items=[])  # zero line items
    res = api.send_quote(base["quote"]["id"], _DISPATCHER)
    validate_error(res, "ERR_EMPTY_SET", expected_status=409)
    quote_after = th.fetch_quote(base["quote"]["id"])
    assert quote_after["status"] == "DRAFT", f"Expected DRAFT, got {quote_after['status']}"


def test_empty_quote_remains_draft_after_rejected_send():
    """PRD §3.3: "A quote may be sent only while in `DRAFT` and only if it carries at least one
    line item; sending an empty quote is rejected with `ERR_EMPTY_SET`."

    Design: Difficulty/boundary_precision_check/send_quote_empty_line_item_set_rejected
    """
    base = setup_draft_quote(line_items=[])
    api.send_quote(base["quote"]["id"], _DISPATCHER)
    quote_after = th.fetch_quote(base["quote"]["id"])
    assert quote_after["status"] == "DRAFT"
    assert quote_after["provisional_total_cents"] == 0, (
        "Empty rejected quote must not have computed a provisional total"
    )


# ─── resource_temporal_overlap / technician_trap_window_closed_plus_buffer ───

def test_trap_window_buffer_blocks_near_adjacent_window():
    """PRD §3.8: "Third, the technician-window-conflict gate: the trap's visit window, taken as
    the closed interval from `window_start` to `window_end` and inflated by a buffer on each
    side, must not overlap the buffered window of any other `SET` trap on the same technician;
    an overlap is rejected with `ERR_TECH_WINDOW_CONFLICT`."
    PRD §3.8: "The buffer applied on each side is fifteen minutes."

    Design: Difficulty/resource_temporal_overlap/technician_trap_window_closed_interval_plus_buffer
    """
    sp = th.create_species(common_name="Marten")
    tech = th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=5)
    base = setup_open_work_order(
        technician=tech,
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 2, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    set_trap(wo["id"], sp["id"], tech["id"],
             window_start="2026-04-03T09:00:00Z", window_end="2026-04-03T10:00:00Z")
    # Second window 10:15-11:00 is 15 min after the first end; buffered windows overlap.
    res = api.create_trap_placement(
        wo["id"],
        create_trap_placement_payload(sp["id"], tech["id"],
                                      window_start="2026-04-03T10:15:00Z",
                                      window_end="2026-04-03T11:00:00Z"),
        make_field_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_TECH_WINDOW_CONFLICT", expected_status=409)


def test_trap_window_far_apart_succeeds():
    """PRD §3.8: "Third, the technician-window-conflict gate: the trap's visit window, taken as
    the closed interval from `window_start` to `window_end` and inflated by a buffer on each
    side, must not overlap the buffered window of any other `SET` trap on the same technician;
    an overlap is rejected with `ERR_TECH_WINDOW_CONFLICT`."
    PRD §3.8: "The buffer applied on each side is fifteen minutes."

    Design: Difficulty/resource_temporal_overlap/technician_trap_window_closed_interval_plus_buffer
    """
    sp = th.create_species(common_name="Marten2")
    tech = th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=5)
    base = setup_open_work_order(
        technician=tech,
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 2, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    set_trap(wo["id"], sp["id"], tech["id"],
             window_start="2026-04-03T09:00:00Z", window_end="2026-04-03T10:00:00Z")
    # A window on the next day cannot overlap even with a 15-minute buffer each side.
    res = api.create_trap_placement(
        wo["id"],
        create_trap_placement_payload(sp["id"], tech["id"],
                                      window_start="2026-04-04T09:00:00Z",
                                      window_end="2026-04-04T10:00:00Z"),
        make_field_technician_headers(tech["id"]),
    )
    trap = validate_success(res, 201)
    assert trap["status"] == "SET"


# ─── resource_temporal_overlap / monitoring_visit_half_open_no_buffer ────────

def test_monitoring_visit_overlap_rejected_half_open():
    """PRD §3.9: "A monitoring visit's window is treated as the half-open interval from
    `visit_start` up to but not including `visit_end`, with no buffer; it must not overlap any
    other monitoring visit on the same property, and an overlap is rejected with
    `ERR_VISIT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/monitoring_visit_half_open_interval_no_buffer_adjacency_ok
    """
    base = th.setup_closed_work_order_via_pull_and_seal(account_name="P8b")
    wo = base["work_order"]
    tech = base["technician"]
    fth = make_field_technician_headers(tech["id"])

    validate_success(api.create_monitoring_visit(
        wo["id"], create_monitoring_visit_payload(visit_start="2026-05-01T09:00:00Z",
                                                   visit_end="2026-05-01T10:00:00Z",
                                                   traps_reset=1), fth), 201)
    # Overlapping [09:30,10:30) on same property -> reject.
    res = api.create_monitoring_visit(
        wo["id"], create_monitoring_visit_payload(visit_start="2026-05-01T09:30:00Z",
                                                  visit_end="2026-05-01T10:30:00Z",
                                                  traps_reset=0), fth)
    validate_error(res, "ERR_VISIT_OVERLAP", expected_status=409)


def test_monitoring_visit_touching_boundary_allowed():
    """PRD §3.9: "A monitoring visit's window is treated as the half-open interval from
    `visit_start` up to but not including `visit_end`, with no buffer; it must not overlap any
    other monitoring visit on the same property, and an overlap is rejected with
    `ERR_VISIT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/monitoring_visit_half_open_interval_no_buffer_adjacency_ok
    """
    base = th.setup_closed_work_order_via_pull_and_seal(account_name="P8b2")
    wo = base["work_order"]
    tech = base["technician"]
    fth = make_field_technician_headers(tech["id"])

    validate_success(api.create_monitoring_visit(
        wo["id"], create_monitoring_visit_payload(visit_start="2026-05-01T09:00:00Z",
                                                   visit_end="2026-05-01T10:00:00Z",
                                                   traps_reset=1), fth), 201)
    # A visit starting exactly at the prior visit's end (10:00) touches but does not overlap.
    res = api.create_monitoring_visit(
        wo["id"], create_monitoring_visit_payload(visit_start="2026-05-01T10:00:00Z",
                                                  visit_end="2026-05-01T11:00:00Z",
                                                  traps_reset=0), fth)
    visit = validate_success(res, 201)
    assert visit["visit_start"].startswith("2026-05-01T10:00")


# ─── Corner: validations.invalid_window_end_not_after_start_rejected ─────────

def test_trap_window_end_equal_to_start_rejected():
    """PRD §3.8: "Independently, the visit window itself must be well formed: `window_end` must
    be strictly after `window_start`, or the request is rejected with `ERR_INVALID_WINDOW`."

    Design: Corner/validations/invalid_window_end_not_after_start_rejected
    """
    sp = th.create_species(common_name="Rabbit")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    res = api.create_trap_placement(
        wo["id"],
        create_trap_placement_payload(sp["id"], tech["id"],
                                      window_start="2026-04-03T09:00:00Z",
                                      window_end="2026-04-03T09:00:00Z"),
        make_field_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_INVALID_WINDOW", expected_status=422)


# ─── Corner: validations.kit_exhausted_when_no_traps_available ───────────────

def test_kit_exhausted_second_set_rejected_non_overlapping_window():
    """PRD §3.8: "Fourth, the kit-capacity gate: a set that would drive the assigned
    technician's `traps_available` below 0 is rejected with `ERR_KIT_EXHAUSTED`."

    Design: Corner/validations/kit_exhausted_when_no_traps_available
    """
    sp = th.create_species(common_name="Weasel")
    tech = th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=1)
    base = setup_open_work_order(
        technician=tech,
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 2, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    # First trap exhausts the kit-of-1.
    set_trap(wo["id"], sp["id"], tech["id"],
             window_start="2026-04-03T09:00:00Z", window_end="2026-04-03T10:00:00Z")
    # Second trap, NON-overlapping window (next day) -> isolates the kit/fiscal check.
    res = api.create_trap_placement(
        wo["id"],
        create_trap_placement_payload(sp["id"], tech["id"],
                                      window_start="2026-04-04T09:00:00Z",
                                      window_end="2026-04-04T10:00:00Z"),
        make_field_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_KIT_EXHAUSTED", expected_status=409)


# ─── Corner: validations.tech_not_certified_for_regulated_species_rejected ───

def test_basic_tech_setting_regulated_trap_rejected():
    """PRD §3.8: "Second, the certification gate: a `BASIC`-tier technician may not set a trap
    for a regulated species — that requires a `CERTIFIED` technician — and an attempt is
    rejected with `ERR_TECH_NOT_CERTIFIED`."

    Design: Corner/validations/tech_not_certified_for_regulated_species_rejected
    """
    sp_reg = th.create_species(is_regulated=True, risk_weight=2.0,
                               relocation_min_miles=5, relocation_max_miles=25,
                               common_name="Eagle")
    tech = th.create_technician(license_tier="BASIC", kit_trap_capacity=5)
    base = setup_open_work_order(
        technician=tech,
        entry_points=[{"species": sp_reg, "severity": "MAJOR", "estimated_individuals": 1}],
        line_items=[{"species": sp_reg, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    # Approve the permit so the permit gate passes and the certification gate is reached.
    permit = get_first_permit(wo["id"])
    validate_success(api.approve_permit(
        permit["id"], create_permit_approve_payload(permit_number="REG-2026-V3"), _COMPLIANCE), 200)

    res = api.create_trap_placement(
        wo["id"],
        create_trap_placement_payload(sp_reg["id"], tech["id"]),
        make_field_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_TECH_NOT_CERTIFIED", expected_status=409)


# ─── Corner: validations.exclusion_repair_entry_point_mismatch_rejected ──────

def test_exclusion_repair_entry_point_from_other_inspection_rejected():
    """PRD §3.6: "A repair may only target an entry point that belongs to the inspection
    underlying this work order's quote and whose `seal_status` is still `OPEN`; targeting an
    entry point from a different inspection, or one already `SEALED`, is rejected with
    `ERR_ENTRY_POINT_MISMATCH`."

    Design: Corner/validations/exclusion_repair_entry_point_mismatch_rejected
    """
    sp = th.create_species(common_name="Robin")
    # Separate inspection B (different property, same account) with its own entry point.
    acct = th.create_account(account_name="V4")
    prop_b = th.create_property(acct["id"], latitude=41.0, longitude=-76.0)
    insp_b = th.create_draft_inspection(prop_b["id"])
    ep_b = th.add_entry_point(insp_b["id"], sp["id"], severity="MINOR", estimated_individuals=1,
                              location_label="other gap")
    th.complete_inspection(prop_b["id"], insp_b["id"])

    # Work order on inspection A (its own property), EXCLUSION line only.
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1,
                       "location_label": "A gap"}],
        line_items=[{"species": sp, "line_type": "EXCLUSION", "quantity": 1, "unit_price_cents": 9000}],
        account_name="V4main",
    )
    wo = base["work_order"]
    tech = base["technician"]
    res = api.create_exclusion_repair(
        wo["id"],
        th.create_exclusion_repair_payload(ep_b["id"]),
        make_field_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_ENTRY_POINT_MISMATCH", expected_status=409)
