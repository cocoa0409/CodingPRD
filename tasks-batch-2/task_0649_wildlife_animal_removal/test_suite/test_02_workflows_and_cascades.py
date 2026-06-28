"""Lifecycle workflows: quote revision loop, parallel work-order dimensions, the
accept->work-order->permit->posture cascade, capture->removal cascade, permit
adjudication side effects, and cross-entity transition dependencies.

Covers difficulty queue A rules non_linear_state_machine, transitive_cascade,
cross_entity_state_dependency, plus corner-queue state_machine instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_permit_approve_payload,
    make_property_owner_headers,
    make_field_technician_headers,
    setup_open_work_order,
    setup_sent_quote,
    set_trap,
    relocate_capture,
    pull_trap,
    start_repair,
    fetch_work_order,
    fetch_property,
    get_first_permit,
)
import test_helpers as th

api = th.api_client
_DISPATCHER = th.TEST_USERS["dispatcher_headers"]
_COMPLIANCE = th.TEST_USERS["compliance_officer_headers"]


# ─── non_linear_state_machine / quote_revision_cycle_sent_back_to_draft ──────

def test_quote_revision_loop_reopen_then_resendable():
    """PRD §3.3: "A `Dispatcher` may then reopen a `REVISION_REQUESTED` quote back to `DRAFT`,
    where its line items may be edited again, closing the `DRAFT → SENT → REVISION_REQUESTED →
    DRAFT` cycle."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_sent_back_to_draft
    """
    base = setup_sent_quote(
        line_items=[{"line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    quote_id = base["quote"]["id"]
    owner = make_property_owner_headers(base["account"]["id"])

    validate_success(api.request_revision_quote(quote_id, owner), 200)
    reopened = validate_success(api.reopen_quote(quote_id, _DISPATCHER), 200)
    assert reopened["status"] == "DRAFT", f"Expected DRAFT after reopen, got {reopened['status']}"

    resent = validate_success(api.send_quote(quote_id, _DISPATCHER), 200)
    assert resent["status"] == "SENT", f"Expected SENT after re-send, got {resent['status']}"


def test_quote_request_revision_from_sent_moves_to_revision_requested():
    """PRD §3.3: "The `PropertyOwner` may request revisions on a `SENT` quote, moving it to
    `REVISION_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_sent_back_to_draft
    """
    base = setup_sent_quote(
        line_items=[{"line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    owner = make_property_owner_headers(base["account"]["id"])
    revised = validate_success(api.request_revision_quote(base["quote"]["id"], owner), 200)
    assert revised["status"] == "REVISION_REQUESTED", (
        f"Expected REVISION_REQUESTED, got {revised['status']}"
    )


# ─── non_linear_state_machine / work_order_parallel_removal_and_exclusion ────

def test_parallel_dimensions_removal_cleared_while_exclusion_pending():
    """PRD §3.6: "The removal dimension (`removal_status`) runs `PENDING → TRAPPING → CLEARED`;
    the exclusion dimension (`exclusion_status`) runs `PENDING → SEALING → SEALED`."
    PRD §3.6: "If no trap placement on the work order remains `SET` and at least one trap was
    ever set, `removal_status` advances to `CLEARED` and the matching `TRAP` line item's
    `performed` flag is set true."

    Design: Difficulty/non_linear_state_machine/work_order_parallel_removal_and_exclusion_dimensions
    """
    sp = th.create_species(common_name="Squirrel")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    trap = set_trap(wo["id"], sp["id"], tech["id"])
    pull_trap(trap["id"], tech["id"])

    wo_after = fetch_work_order(wo["id"])
    assert wo_after["removal_status"] == "CLEARED", f"Expected CLEARED, got {wo_after['removal_status']}"
    assert wo_after["exclusion_status"] == "PENDING", (
        f"Expected exclusion PENDING, got {wo_after['exclusion_status']}"
    )
    assert wo_after["lifecycle"] == "OPEN", f"Expected OPEN, got {wo_after['lifecycle']}"


def test_first_trap_set_advances_removal_to_trapping():
    """PRD §3.6: "Setting the first trap advances `removal_status` from `PENDING` to
    `TRAPPING`, decrements the technician's `traps_deployed` (raising it by one) and decreases
    `traps_available` (lowering it by one) to draw the trap from the conserved kit."

    Design: Difficulty/non_linear_state_machine/work_order_parallel_removal_and_exclusion_dimensions
    """
    sp = th.create_species(common_name="Squirrel")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    set_trap(wo["id"], sp["id"], tech["id"])

    wo_after = fetch_work_order(wo["id"])
    assert wo_after["removal_status"] == "TRAPPING", (
        f"Expected TRAPPING, got {wo_after['removal_status']}"
    )


# ─── transitive_cascade / quote_accept_cascade_to_workorder_permit_posture ───

def test_accept_cascade_workorder_risk_permit_posture_depth4():
    """PRD §3.4: "Then a **work order** is created from the quote, recording the `quote_id`, a
    denormalized `property_id` for convenient filtering, and the `assigned_technician_id`"
    PRD §3.4: "Separately, for each distinct regulated species appearing among the inspection's
    entry points, a **permit** is created on the work order in `REQUESTED` status, recording
    the `work_order_id` and that `species_id` (its `permit_number` is initially absent)."
    PRD §3.4: "Finally the property's posture is reconciled: if any permit was created, the
    parent property's `posture` becomes `REGULATORY_HOLD`"

    Design: Difficulty/transitive_cascade/quote_accept_cascade_to_workorder_permit_posture_depth4
    """
    # One regulated EP individuals 2 MAJOR weight 2.0 => initial 2*2.0*3.5*1.5 = 21.0
    sp_reg = th.create_species(is_regulated=True, risk_weight=2.0,
                               relocation_min_miles=5, relocation_max_miles=25,
                               common_name="Coyote")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=5),
        entry_points=[{"species": sp_reg, "severity": "MAJOR", "estimated_individuals": 2}],
        line_items=[{"species": sp_reg, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    assert wo["lifecycle"] == "OPEN", f"Expected OPEN, got {wo['lifecycle']}"
    assert wo["initial_risk_score"] == 21.0, f"Expected 21.0, got {wo['initial_risk_score']}"

    prop = fetch_property(base["property"]["id"])
    assert prop["posture"] == "REGULATORY_HOLD", (
        f"Expected REGULATORY_HOLD, got {prop['posture']}"
    )

    permits, meta = validate_paginated(api.list_work_order_permits(wo["id"], _COMPLIANCE))
    assert len(permits) == 1, f"Expected exactly 1 permit, got {len(permits)}"
    assert permits[0]["status"] == "REQUESTED"
    assert permits[0]["species_id"] == sp_reg["id"]


def test_accept_with_no_regulated_species_sets_active_remediation_posture():
    """PRD §3.4: "if no permit was created, the property's `posture` becomes
    `ACTIVE_REMEDIATION`."

    Design: Difficulty/transitive_cascade/quote_accept_cascade_to_workorder_permit_posture_depth4
    """
    sp = th.create_species(is_regulated=False, common_name="Raccoon")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    prop = fetch_property(base["property"]["id"])
    assert prop["posture"] == "ACTIVE_REMEDIATION", (
        f"Expected ACTIVE_REMEDIATION, got {prop['posture']}"
    )


# ─── transitive_cascade / capture_cascade_trap_spent_to_removal_cleared ──────

def test_capture_cascades_trap_spent_removal_cleared_line_performed():
    """PRD §3.6: "On a compliant release a capture event is created with `disposition` of
    `RELOCATED` (the only disposition that ever persists), and the trap moves from `SET` to
    `SPENT`."
    PRD §3.6: "If no trap placement on the work order remains `SET` after this, the
    `removal_status` advances from `TRAPPING` to `CLEARED`, and the matching `TRAP` line item's
    `performed` flag is set true."

    Design: Difficulty/transitive_cascade/capture_cascade_trap_spent_to_removal_cleared_depth2
    """
    sp = th.create_species(relocation_min_miles=5, relocation_max_miles=25, common_name="Groundhog")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    line_item = base["line_items"][0]
    trap = set_trap(wo["id"], sp["id"], tech["id"])
    relocate_capture(trap["id"], tech["id"], release_latitude=40.145)

    trap_after = th.fetch_trap_placement(trap["id"])
    assert trap_after["status"] == "SPENT", f"Expected SPENT, got {trap_after['status']}"

    wo_after = fetch_work_order(wo["id"])
    assert wo_after["removal_status"] == "CLEARED", (
        f"Expected CLEARED, got {wo_after['removal_status']}"
    )

    li_after = validate_success(api.get_line_item(line_item["id"], _DISPATCHER), 200)
    assert li_after["performed"] is True, "Expected matching TRAP line performed == true"


def test_capture_returns_trap_to_kit():
    """PRD §3.6: "As a secondary effect, the trap's exit from `SET` returns it to the kit: the
    technician's `traps_deployed` drops by one and `traps_available` rises by one."

    Design: Difficulty/transitive_cascade/capture_cascade_trap_spent_to_removal_cleared_depth2
    """
    sp = th.create_species(relocation_min_miles=5, relocation_max_miles=25, common_name="Groundhog")
    tech = th.create_technician(license_tier="BASIC", kit_trap_capacity=5)
    base = setup_open_work_order(
        technician=tech,
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    trap = set_trap(wo["id"], sp["id"], tech["id"])
    relocate_capture(trap["id"], tech["id"], release_latitude=40.145)

    tech_after = th.fetch_technician(tech["id"])
    assert tech_after["traps_deployed"] == 0, f"Expected deployed 0, got {tech_after['traps_deployed']}"
    assert tech_after["traps_available"] == 5, (
        f"Expected available 5, got {tech_after['traps_available']}"
    )


# ─── cross_entity_state_dependency / trap_set_requires_permit_approved ───────

def test_regulated_trap_set_blocked_until_permit_approved():
    """PRD §3.8: "First, the permit gate: if the trap's species `is_regulated`, a permit for
    that species on this work order must be `APPROVED`; otherwise the set is rejected with
    `ERR_PERMIT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/trap_set_requires_permit_approved_trap_to_permit
    """
    sp_reg = th.create_species(is_regulated=True, risk_weight=2.0,
                               relocation_min_miles=5, relocation_max_miles=25,
                               common_name="Deer")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=5),
        entry_points=[{"species": sp_reg, "severity": "MAJOR", "estimated_individuals": 2}],
        line_items=[{"species": sp_reg, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    # Permit still REQUESTED (not approved).
    res = api.create_trap_placement(
        wo["id"],
        th.create_trap_placement_payload(sp_reg["id"], tech["id"]),
        make_field_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_PERMIT_REQUIRED", expected_status=409)


def test_regulated_trap_set_succeeds_after_permit_approved():
    """PRD §3.5: "Approval requires the permit to be in `REQUESTED` status and a
    `permit_number` to be supplied in the request body; on success the permit moves to
    `APPROVED` and the regulator-issued `permit_number` is stored."
    PRD §3.8: "First, the permit gate: if the trap's species `is_regulated`, a permit for that
    species on this work order must be `APPROVED`; otherwise the set is rejected with
    `ERR_PERMIT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/trap_set_requires_permit_approved_trap_to_permit
    """
    sp_reg = th.create_species(is_regulated=True, risk_weight=2.0,
                               relocation_min_miles=5, relocation_max_miles=25,
                               common_name="Deer")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=5),
        entry_points=[{"species": sp_reg, "severity": "MAJOR", "estimated_individuals": 2}],
        line_items=[{"species": sp_reg, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    permit = get_first_permit(wo["id"])
    validate_success(api.approve_permit(
        permit["id"], create_permit_approve_payload(permit_number="REG-2026-OK"), _COMPLIANCE), 200)

    res = api.create_trap_placement(
        wo["id"],
        th.create_trap_placement_payload(sp_reg["id"], tech["id"]),
        make_field_technician_headers(tech["id"]),
    )
    trap = validate_success(res, 201)
    assert trap["status"] == "SET", f"Expected SET, got {trap['status']}"


# ─── cross_entity_state_dependency / exclusion_complete_requires_removal_cleared ─

def test_exclusion_complete_blocked_while_removal_not_cleared():
    """PRD §3.6: "Completing a repair (the repair is named by its own `repair_id` in the path)
    requires the work order to be `OPEN`, the repair's `status` to be `STARTED`, and —
    crucially — the removal dimension to have reached `CLEARED` first, because sealing the
    building before the animals are cleared would trap them inside; completing while
    `removal_status` is not `CLEARED` is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/exclusion_complete_requires_removal_cleared_repair_to_workorder
    """
    sp = th.create_species(common_name="Possum")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MODERATE", "estimated_individuals": 2}],
        line_items=[
            {"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000},
            {"species": sp, "line_type": "EXCLUSION", "quantity": 1, "unit_price_cents": 9000},
        ],
    )
    wo = base["work_order"]
    tech = base["technician"]
    ep = base["entry_points"][0]
    # Set a trap (removal still TRAPPING, not CLEARED), then start + try-complete a repair.
    set_trap(wo["id"], sp["id"], tech["id"])
    repair = start_repair(wo["id"], ep["id"], tech["id"])

    res = api.complete_exclusion_repair(wo["id"], repair["id"], make_field_technician_headers(tech["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    rep_after = th.fetch_exclusion_repair(repair["id"])
    assert rep_after["status"] == "STARTED", f"Expected STARTED, got {rep_after['status']}"


def test_exclusion_complete_succeeds_after_removal_cleared():
    """PRD §3.6: "On completion the repair's `status` moves to `COMPLETED`, the targeted entry
    point's `seal_status` becomes `SEALED`, and the matching `EXCLUSION` line item's
    `performed` flag is set true."

    Design: Difficulty/cross_entity_state_dependency/exclusion_complete_requires_removal_cleared_repair_to_workorder
    """
    sp = th.create_species(common_name="Possum")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MODERATE", "estimated_individuals": 2}],
        line_items=[
            {"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000},
            {"species": sp, "line_type": "EXCLUSION", "quantity": 1, "unit_price_cents": 9000},
        ],
    )
    wo = base["work_order"]
    tech = base["technician"]
    ep = base["entry_points"][0]
    trap = set_trap(wo["id"], sp["id"], tech["id"])
    pull_trap(trap["id"], tech["id"])  # removal -> CLEARED
    repair = start_repair(wo["id"], ep["id"], tech["id"])

    res = api.complete_exclusion_repair(wo["id"], repair["id"], make_field_technician_headers(tech["id"]))
    completed = validate_success(res, 200)
    assert completed["status"] == "COMPLETED", f"Expected COMPLETED, got {completed['status']}"


# ─── Corner: state_machines.permit_approve_lifts_regulatory_hold_bubble ──────

def test_permit_approve_bubbles_posture_to_active_remediation():
    """PRD §3.5: "After an approval, if every permit on the work order is now `APPROVED`, the
    parent property's `posture` bubbles up to `ACTIVE_REMEDIATION`, lifting the regulatory
    hold."

    Design: Corner/state_machines/permit_approve_lifts_regulatory_hold_bubble
    """
    sp_reg = th.create_species(is_regulated=True, risk_weight=2.0,
                               relocation_min_miles=5, relocation_max_miles=25,
                               common_name="Fox")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=5),
        entry_points=[{"species": sp_reg, "severity": "MAJOR", "estimated_individuals": 2}],
        line_items=[{"species": sp_reg, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    prop_before = fetch_property(base["property"]["id"])
    assert prop_before["posture"] == "REGULATORY_HOLD"

    permit = get_first_permit(wo["id"])
    approved = validate_success(api.approve_permit(
        permit["id"], create_permit_approve_payload(permit_number="REG-2026-001"), _COMPLIANCE), 200)
    assert approved["status"] == "APPROVED"

    prop_after = fetch_property(base["property"]["id"])
    assert prop_after["posture"] == "ACTIVE_REMEDIATION", (
        f"Expected ACTIVE_REMEDIATION, got {prop_after['posture']}"
    )


# ─── Corner: state_machines.permit_deny_cascade_cancels_work_order ───────────

def test_permit_deny_cascade_cancels_work_order_and_resets_posture():
    """PRD §3.5: "Denying a `REQUESTED` permit moves it to `DENIED` and cascades hard: the work
    order's `lifecycle` is driven to `CANCELLED`, the property's `posture` is reset to `OPEN`,
    and every trap placement on that work order still in the `SET` state is moved to
    `CANCELLED` with its trap returned to the owning technician's kit (each such cancellation
    decrements that technician's `traps_deployed` by one and increments `traps_available` by
    one)."

    Design: Corner/state_machines/permit_deny_cascade_cancels_work_order
    """
    sp_reg = th.create_species(is_regulated=True, risk_weight=2.0,
                               relocation_min_miles=5, relocation_max_miles=25,
                               common_name="Owl")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="CERTIFIED", kit_trap_capacity=5),
        entry_points=[{"species": sp_reg, "severity": "MAJOR", "estimated_individuals": 2}],
        line_items=[{"species": sp_reg, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    permit = get_first_permit(wo["id"])
    denied = validate_success(api.deny_permit(permit["id"], _COMPLIANCE), 200)
    assert denied["status"] == "DENIED"

    wo_after = fetch_work_order(wo["id"])
    assert wo_after["lifecycle"] == "CANCELLED", f"Expected CANCELLED, got {wo_after['lifecycle']}"

    prop_after = fetch_property(base["property"]["id"])
    assert prop_after["posture"] == "OPEN", f"Expected OPEN, got {prop_after['posture']}"
