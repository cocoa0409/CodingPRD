"""Conserved-money and conserved-kit invariants on work-order cancellation, OCC stale-version
guard, plus entity CRUD/defaults/type constraints, invalid-state transitions, auth/RBAC, and
derived-field reconciliation.

Covers difficulty queue A rule compensating_invariant, plus corner-queue entities, state_machines,
errors, rbac, and cross_cutting_complexity_layers instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_accept_payload,
    create_species_profile_payload,
    create_technician_payload,
    create_property_payload,
    create_entry_point_payload,
    create_inspection_payload,
    make_property_owner_headers,
    make_field_technician_headers,
    setup_open_work_order,
    setup_draft_quote,
    set_trap,
    pull_trap,
    fetch_work_order,
    fetch_technician,
)
import test_helpers as th

api = th.api_client
_DISPATCHER = th.TEST_USERS["dispatcher_headers"]
_COMPLIANCE = th.TEST_USERS["compliance_officer_headers"]
NON_EXISTENT_UUID = th.NON_EXISTENT_UUID


# ─── compensating_invariant / workorder_cancel_conserves_money ──────────────

def test_cancel_settles_net_charged_to_performed_subtotal():
    """PRD §3.7: "The refund is the work order's current `net_charged_cents` minus this
    performed subtotal, and `net_charged_cents` settles down to the performed subtotal."
    PRD §3.7: "for each line item whose `performed` flag is true, the raw amount (`quantity`
    times `unit_price_cents` times the surcharge factor) is rounded to the nearest whole cent
    using round-half-up, and these rounded amounts are summed"

    Design: Difficulty/compensating_invariant/workorder_cancel_conserves_money_net_plus_refund
    """
    sp = th.create_species(common_name="Hare")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[
            {"species": sp, "line_type": "TRAP", "quantity": 2, "unit_price_cents": 6000},
            {"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 5000},
            {"species": sp, "line_type": "EXCLUSION", "quantity": 1, "unit_price_cents": 9000},
        ],
    )
    wo = base["work_order"]
    tech = base["technician"]
    # Set one trap then pull it: removal advances to CLEARED, flipping the first
    # not-yet-performed TRAP line (qty2@6000) to performed; nothing else performed.
    trap = set_trap(wo["id"], sp["id"], tech["id"])
    pull_trap(trap["id"], tech["id"])
    wo_current = fetch_work_order(wo["id"])

    res = api.cancel_work_order(
        wo["id"], {"expected_work_order_version": wo_current["version"]}, _DISPATCHER)
    cancelled = validate_success(res, 200)
    # provisional 26000; performed subtotal = qty2@6000 = 12000.
    assert cancelled["net_charged_cents"] == 12000, (
        f"Expected net 12000, got {cancelled['net_charged_cents']}"
    )
    assert cancelled["lifecycle"] == "CANCELLED", f"Expected CANCELLED, got {cancelled['lifecycle']}"


def test_cancel_conserves_money_net_plus_refund_equals_provisional():
    """PRD §2.9: "At acceptance the work order's `net_charged_cents` is initialized to the
    quote's `provisional_total_cents`."
    PRD §3.7: "Because the work order's `net_charged_cents` plus the refund equals the
    originally committed provisional total, no money is created or destroyed."

    Design: Difficulty/compensating_invariant/workorder_cancel_conserves_money_net_plus_refund
    """
    sp = th.create_species(common_name="Hare2")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[
            {"species": sp, "line_type": "TRAP", "quantity": 2, "unit_price_cents": 6000},
            {"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 5000},
            {"species": sp, "line_type": "EXCLUSION", "quantity": 1, "unit_price_cents": 9000},
        ],
    )
    wo = base["work_order"]
    tech = base["technician"]
    provisional = base["quote"]["provisional_total_cents"]
    assert provisional == 26000
    # net at accept == provisional.
    assert wo["net_charged_cents"] == 26000, f"Expected net 26000 at accept, got {wo['net_charged_cents']}"

    # Set then pull a trap: removal -> CLEARED flips the first TRAP line (qty2@6000)
    # to performed, so the performed subtotal is 12000 and the refund is 14000.
    trap = set_trap(wo["id"], sp["id"], tech["id"])
    pull_trap(trap["id"], tech["id"])
    wo_current = fetch_work_order(wo["id"])
    cancelled = validate_success(api.cancel_work_order(
        wo["id"], {"expected_work_order_version": wo_current["version"]}, _DISPATCHER), 200)
    refund = provisional - cancelled["net_charged_cents"]
    assert cancelled["net_charged_cents"] + refund == provisional, (
        "net_charged_cents + refund must equal the committed provisional total"
    )
    assert refund == 14000, f"Expected refund 14000, got {refund}"


# ─── compensating_invariant / workorder_cancel_conserves_kit_pool ───────────

def test_cancel_restores_technician_kit_pool():
    """PRD §3.7: "moves every `SET` trap placement on the work order to `CANCELLED`, restoring
    each to its technician's kit (each decrements `traps_deployed` by one and increments
    `traps_available` by one)"

    Design: Difficulty/compensating_invariant/workorder_cancel_conserves_technician_trap_kit_pool
    """
    sp = th.create_species(common_name="Stoat")
    tech = th.create_technician(license_tier="BASIC", kit_trap_capacity=5)
    base = setup_open_work_order(
        technician=tech,
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    trap = set_trap(wo["id"], sp["id"], tech["id"])
    tech_mid = fetch_technician(tech["id"])
    assert tech_mid["traps_deployed"] == 1 and tech_mid["traps_available"] == 4

    wo_current = fetch_work_order(wo["id"])
    validate_success(api.cancel_work_order(
        wo["id"], {"expected_work_order_version": wo_current["version"]}, _DISPATCHER), 200)

    tech_after = fetch_technician(tech["id"])
    assert tech_after["traps_deployed"] == 0, f"Expected deployed 0, got {tech_after['traps_deployed']}"
    assert tech_after["traps_available"] == 5, f"Expected available 5, got {tech_after['traps_available']}"
    trap_after = th.fetch_trap_placement(trap["id"])
    assert trap_after["status"] == "CANCELLED", f"Expected CANCELLED, got {trap_after['status']}"


def test_kit_invariant_holds_across_set_and_cancel():
    """PRD §2.8: "The invariant `traps_deployed` plus `traps_available` equals
    `kit_trap_capacity` holds at all times, and `traps_available` is never negative."

    Design: Difficulty/compensating_invariant/workorder_cancel_conserves_technician_trap_kit_pool
    """
    sp = th.create_species(common_name="Stoat2")
    tech = th.create_technician(license_tier="BASIC", kit_trap_capacity=5)
    base = setup_open_work_order(
        technician=tech,
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    set_trap(wo["id"], sp["id"], tech["id"])
    tech_mid = fetch_technician(tech["id"])
    th.assert_technician_kit_invariant(tech_mid)

    wo_current = fetch_work_order(wo["id"])
    validate_success(api.cancel_work_order(
        wo["id"], {"expected_work_order_version": wo_current["version"]}, _DISPATCHER), 200)
    tech_after = fetch_technician(tech["id"])
    th.assert_technician_kit_invariant(tech_after)


# ─── Corner: cross_cutting.occ_stale_work_order_cancel_rejected ──────────────

def test_stale_work_order_version_cancel_rejected():
    """PRD §2.6: "If `expected_work_order_version` does not equal the work order's current
    `version` — that is, if any trap set, capture, pull, or repair completion advanced the work
    order since the client read it — the cancellation is rejected with `ERR_STALE_VERSION`
    (HTTP 412), and no refund or kit restoration is performed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_work_order_cancel_rejected
    """
    sp = th.create_species(common_name="Lynx")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    stale_version = wo["version"]  # version observed at accept
    set_trap(wo["id"], sp["id"], tech["id"])  # bumps WorkOrder.version

    res = api.cancel_work_order(
        wo["id"], {"expected_work_order_version": stale_version}, _DISPATCHER)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    wo_after = fetch_work_order(wo["id"])
    assert wo_after["lifecycle"] == "OPEN", f"Expected OPEN (still), got {wo_after['lifecycle']}"


# ─── Corner: cross_cutting.derived_detected_individual_count_reconciles ──────

def test_detected_individual_count_reconciles_on_entry_point_add():
    """PRD §3.2: "Whenever an entry point is added, the parent inspection's
    `detected_individual_count` is refreshed to the sum of `estimated_individuals` across all
    of that inspection's entry points."

    Design: Corner/cross_cutting_complexity_layers/derived_detected_individual_count_reconciles_on_entry_point_add
    """
    sp = th.create_species(common_name="Newt")
    acct = th.create_account(account_name="CC2")
    prop = th.create_property(acct["id"])
    insp = th.create_draft_inspection(prop["id"])
    th.add_entry_point(insp["id"], sp["id"], severity="MINOR", estimated_individuals=4,
                       location_label="g1")
    ep2 = validate_success(api.create_entry_point(
        insp["id"], create_entry_point_payload(sp["id"], severity="MINOR",
                                                estimated_individuals=3, location_label="g2"),
        _DISPATCHER), 201)
    assert ep2["estimated_individuals"] == 3

    insp_after = th.fetch_inspection(insp["id"])
    assert insp_after["detected_individual_count"] == 7, (
        f"Expected 7, got {insp_after['detected_individual_count']}"
    )


# ─── Corner: entities.create_species_profile_returns_201_all_fields ──────────

def test_create_species_profile_201_with_defaults():
    """PRD §3.1: "The profile declares whether the species `is_regulated` (defaulting to not
    regulated), the lawful relocation band as a `relocation_min_miles` and
    `relocation_max_miles` pair (defaulting to a minimum of 0 and a maximum of 25 miles)"
    PRD §2.4: "an integer `version` that begins at its initial value on creation and increments
    by one on every mutation."

    Design: Corner/entities/create_species_profile_returns_201_all_fields
    """
    res = api.create_species_profile(
        create_species_profile_payload(common_name="Eastern Gray Squirrel", code="EGS_C",
                                       base_trap_fee_cents=4000),
        _COMPLIANCE)
    sp = validate_success(res, 201)
    th.assert_species_profile(sp)
    assert sp["is_regulated"] is False
    assert sp["relocation_max_miles"] == 25
    assert sp["version"] == 1


# ─── Corner: entities.get_property_not_found_returns_404 ─────────────────────

def test_get_property_not_found():
    """PRD §2.5: "the server validates the path identifiers left to right and rejects the
    request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing
    resource, before any body-level foreign keys are checked."

    Design: Corner/entities/get_property_not_found_returns_404
    """
    res = api.get_property("00000000-0000-4000-8000-000000000000", _DISPATCHER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── Corner: entities.create_entry_point_missing_required_estimated_individuals ─

def test_entry_point_missing_estimated_individuals_rejected():
    """PRD §2.12: "Last of all, generic body-shape validation — missing required fields, bad
    enum values, out-of-range numbers, or non-positive quantities — yields
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_entry_point_missing_required_estimated_individuals
    """
    sp = th.create_species(common_name="Bat")
    acct = th.create_account(account_name="E1")
    prop = th.create_property(acct["id"])
    insp = th.create_draft_inspection(prop["id"])
    payload = {"species_id": sp["id"], "location_label": "gap"}  # no estimated_individuals
    res = api.create_entry_point(insp["id"], payload, _DISPATCHER)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ─── Corner: entities.create_inspection_default_is_emergency_false ───────────

def test_create_inspection_default_is_emergency_false():
    """PRD §3.2: "A `Dispatcher` schedules an **inspection** on a property, supplying the
    `scheduled_for` visit time and an optional `is_emergency` flag (defaulting to false)."
    PRD §3.2: "The inspection is created with its `status` field at `DRAFT` and a
    `detected_individual_count` of 0; the property is recorded via `property_id`."

    Design: Corner/entities/create_inspection_default_is_emergency_false
    """
    acct = th.create_account(account_name="E2")
    prop = th.create_property(acct["id"])
    res = api.create_inspection(prop["id"],
                                create_inspection_payload(scheduled_for="2026-04-02T09:00:00Z"),
                                _DISPATCHER)
    insp = validate_success(res, 201)
    assert insp["is_emergency"] is False
    assert insp["status"] == "DRAFT"


# ─── Corner: entities.technician_computed_kit_counts_on_create ───────────────

def test_technician_kit_counts_computed_on_create():
    """PRD §3.1: "On registration the technician's `traps_deployed` starts at 0 and
    `traps_available` starts equal to `kit_trap_capacity`."

    Design: Corner/entities/technician_computed_kit_counts_on_create
    """
    res = api.create_technician(
        create_technician_payload(full_name="Ty", license_tier="CERTIFIED", kit_trap_capacity=5),
        _DISPATCHER)
    tech = validate_success(res, 201)
    assert tech["traps_deployed"] == 0
    assert tech["traps_available"] == 5


# ─── Corner: entities.entry_point_invalid_severity_enum_rejected ─────────────

def test_entry_point_invalid_severity_enum_rejected():
    """PRD §2.12: "Last of all, generic body-shape validation — missing required fields, bad
    enum values, out-of-range numbers, or non-positive quantities — yields
    `ERR_INVALID_REQUEST`."
    PRD §3.2: "an access `severity` of `MINOR`, `MODERATE`, or `MAJOR` (defaulting to
    `MODERATE`)"

    Design: Corner/entities/entry_point_invalid_severity_enum_rejected
    """
    sp = th.create_species(common_name="Mouse")
    acct = th.create_account(account_name="E3")
    prop = th.create_property(acct["id"])
    insp = th.create_draft_inspection(prop["id"])
    payload = create_entry_point_payload(sp["id"], severity="EXTREME", estimated_individuals=2)
    res = api.create_entry_point(insp["id"], payload, _DISPATCHER)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ─── Corner: entities.property_wrong_parent_account_not_found ────────────────

def test_create_property_with_nonexistent_account_not_found():
    """PRD §2.5: "Body-referenced foreign keys are validated only after the path resolves, and
    a missing body reference likewise yields `ERR_NOT_FOUND`."

    Design: Corner/entities/property_wrong_parent_account_not_found
    """
    res = api.create_property(
        create_property_payload("00000000-0000-4000-8000-000000000000",
                                latitude=40.0, longitude=-75.0),
        _DISPATCHER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── Corner: entities.species_profile_min_exceeds_max_rejected ───────────────

def test_species_profile_min_exceeds_max_rejected():
    """PRD §3.1: "The relocation minimum must be at least 0 and no greater than the maximum,
    and the maximum must be at least the minimum."

    Design: Corner/entities/species_profile_min_exceeds_max_rejected
    """
    res = api.create_species_profile(
        create_species_profile_payload(common_name="Bad", code="BAD_E4",
                                       base_trap_fee_cents=4000,
                                       relocation_min_miles=30, relocation_max_miles=10),
        _COMPLIANCE)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ─── Corner: state_machines invalid/terminal transitions ─────────────────────

def test_complete_already_completed_inspection_invalid_state():
    """PRD §3.2: "Attempting either transition from any other state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/inspection_complete_from_completed_returns_invalid_state
    """
    sp = th.create_species(common_name="Rat")
    acct = th.create_account(account_name="S1")
    prop = th.create_property(acct["id"])
    insp = th.create_draft_inspection(prop["id"])
    th.add_entry_point(insp["id"], sp["id"], severity="MINOR", estimated_individuals=1)
    th.complete_inspection(prop["id"], insp["id"])
    res = api.complete_inspection(prop["id"], insp["id"], _DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_accept_draft_quote_invalid_state():
    """PRD §3.3: "From `SENT`, the owner may also decline the quote (moving it to the terminal
    `DECLINED` state) or accept it. Each transition is legal only from its named source state;
    any other source yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/quote_accept_from_draft_returns_invalid_state
    """
    base = setup_draft_quote(
        line_items=[{"line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    tech = th.create_technician(license_tier="BASIC", kit_trap_capacity=5)
    owner = make_property_owner_headers(base["account"]["id"])
    res = api.accept_quote(base["quote"]["id"], create_accept_payload(tech["id"]), owner)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_capture_on_spent_trap_invalid_state():
    """PRD §3.6: "When an animal is found, a `FieldTechnician` records a **capture event**
    against a `SET` trap on an `OPEN` work order"

    Design: Corner/state_machines/trap_capture_from_spent_trap_returns_invalid_state
    """
    sp = th.create_species(relocation_min_miles=5, relocation_max_miles=25, common_name="Hog")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = base["work_order"]
    tech = base["technician"]
    trap = set_trap(wo["id"], sp["id"], tech["id"])
    th.relocate_capture(trap["id"], tech["id"], release_latitude=40.145)  # -> SPENT
    # Second capture on the already-SPENT trap.
    res = api.create_capture(
        trap["id"],
        th.create_capture_payload(captured_at="2026-04-03T13:00:00Z",
                                  release_latitude=40.145, release_longitude=-75.0),
        make_field_technician_headers(tech["id"]),
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    trap_after = th.fetch_trap_placement(trap["id"])
    assert trap_after["status"] == "SPENT"


def test_complete_cancelled_inspection_terminal_lockdown():
    """PRD §3.2: "A `Dispatcher` may instead cancel a `DRAFT` inspection, moving it to the
    terminal `CANCELLED` status; cancellation is permitted only from `DRAFT`."
    PRD §3.2: "Attempting either transition from any other state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancelled_inspection_terminal_lockdown_cannot_complete
    """
    acct = th.create_account(account_name="S7")
    prop = th.create_property(acct["id"])
    insp = th.create_draft_inspection(prop["id"])
    validate_success(api.cancel_inspection(prop["id"], insp["id"], _DISPATCHER), 200)
    res = api.complete_inspection(prop["id"], insp["id"], _DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner: errors auth ─────────────────────────────────────────────────────

def test_unauthenticated_unknown_role_header():
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the recognized
    roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/unauthenticated_missing_role_header
    """
    bad_headers = th.build_user_headers("someone", "Nobody")
    res = api.list_species_profiles(bad_headers)
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_forbidden_field_tech_cannot_create_species():
    """PRD §2.1: "When the headers are well formed but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/errors/forbidden_role_field_tech_cannot_create_species
    """
    fth = make_field_technician_headers("00000000-0000-4000-8000-000000000001")
    res = api.create_species_profile(
        create_species_profile_payload(common_name="X", code="X_ERR", base_trap_fee_cents=4000),
        fth)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


# ─── Corner: rbac peer-role exclusivity ──────────────────────────────────────

def test_property_owner_cannot_cancel_work_order():
    """PRD §2.1: "`Dispatcher` — schedules inspections, records entry-point findings, builds
    and sends quotes, reopens quotes for revision, registers service accounts, properties, and
    technicians, and cancels work orders."
    PRD §2.1: "When the headers are well formed but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/property_owner_cannot_cancel_work_order
    """
    sp = th.create_species(common_name="Jay")
    base = setup_open_work_order(
        technician=th.create_technician(license_tier="BASIC", kit_trap_capacity=5),
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[{"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    wo = fetch_work_order(base["work_order"]["id"])
    owner = make_property_owner_headers(base["account"]["id"])
    res = api.cancel_work_order(wo["id"], {"expected_work_order_version": wo["version"]}, owner)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_compliance_officer_cannot_send_quote():
    """PRD §2.1: "`Dispatcher` — schedules inspections, records entry-point findings, builds
    and sends quotes, reopens quotes for revision, registers service accounts, properties, and
    technicians, and cancels work orders."
    PRD §2.1: "When the headers are well formed but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/compliance_officer_cannot_send_quote
    """
    base = setup_draft_quote(
        line_items=[{"line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}],
    )
    res = api.send_quote(base["quote"]["id"], _COMPLIANCE)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


# ─── Corner: endpoints listing / pagination ──────────────────────────────────

def test_list_properties_filtered_by_account_id():
    """PRD §3.10: "Properties may be listed and narrowed by an `account_id` filter"
    PRD §2.3: "The response envelope's `meta` object for a list carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reflects the full
    matching set before the limit/offset window is applied and `has_more` indicates whether
    additional items remain beyond the returned window."

    Design: Corner/endpoints/list_properties_filtered_by_account_id_pagination
    """
    acct = th.create_account(account_name="EP1")
    th.create_property(acct["id"], latitude=40.0, longitude=-75.0)
    th.create_property(acct["id"], latitude=41.0, longitude=-76.0)
    res = api.list_properties(_DISPATCHER, params={"account_id": acct["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, f"Expected total_count 2, got {meta['total_count']}"
    assert len(data) == 2, f"Expected 2 properties, got {len(data)}"


def test_list_property_inspections_returns_array():
    """PRD §3.10: "Beyond the workflows above, the system exposes read access across the
    hierarchy so operators can navigate it."
    PRD §2.3: "Unless an endpoint explicitly states otherwise, every list is returned sorted by
    the resource's `created_at` timestamp in ascending order."

    Design: Corner/endpoints/list_inspections_subresource_returns_array
    """
    acct = th.create_account(account_name="EP2")
    prop = th.create_property(acct["id"])
    th.create_draft_inspection(prop["id"])
    res = api.list_property_inspections(prop["id"], _DISPATCHER)
    data, meta = validate_paginated(res)
    assert len(data) == 1, f"Expected 1 inspection, got {len(data)}"
