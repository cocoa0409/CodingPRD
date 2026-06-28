"""RBAC enforcement, optimistic concurrency, compensating invariants, derived
fields, and entity CRUD / system-field contracts.

Covers difficulty queue A (compensating_invariant) and corner queue B (rbac,
cross_cutting_complexity_layers/OCC + derived + feature-flag, entities section).
"""
import datetime

import pytest

from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    validate_paginated,
    is_iso8601_timestamp,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
    factories as f,
    make_customer_headers,
    make_technician_headers,
)

SM = TEST_USERS["service_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: compensating_invariant / tech_load_count_conserved_assign_then_cancel
# ─────────────────────────────────────────────────────────────────────────────
def test_tech_load_count_conserved_assign_then_cancel(api):
    """PRD §3.8: "On assignment the `assigned_tech_id` is recorded, the technician's
    `open_dispatch_count` increments by one"
    PRD §3.8: "if it was `DISPATCHED`, cancelling decrements the assigned technician's
    `open_dispatch_count` by one."

    Design: Difficulty/compensating_invariant/tech_load_count_conserved_assign_then_cancel
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    tech_id = setup["technician"]["id"]
    disp = fx.create_paid_dispatch(setup["unit"]["id"], labor_cents=5000)
    fx.assign_dispatch(disp["id"], tech_id)
    assigned_tech = get_success_data(api.get_technician(tech_id, SM))
    assert assigned_tech["open_dispatch_count"] == 1
    res = api.cancel_dispatch(disp["id"], SM)
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    after_tech = get_success_data(api.get_technician(tech_id, SM))
    assert after_tech["open_dispatch_count"] == 0


def test_tech_load_count_global_invariant_after_assign_cancel(api):
    """PRD §3.8: "On assignment the `assigned_tech_id` is recorded, the technician's
    `open_dispatch_count` increments by one, and the dispatch's `version` increments."
    PRD §3.8: "A dispatch in `REQUESTED` or `DISPATCHED` may be cancelled by a
    `ServiceManager` — but it cannot be cancelled once `IN_PROGRESS`; if it was
    `DISPATCHED`, cancelling decrements the assigned technician's `open_dispatch_count`
    by one."

    A second technician with no dispatches must keep open_dispatch_count 0 throughout,
    so the global sum of open_dispatch_count returns to 0 after the assign/cancel
    round-trip — the counter is globally conserved, not merely reset on one tech.

    Design: Difficulty/compensating_invariant/tech_load_count_conserved_assign_then_cancel
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    tech_a_id = setup["technician"]["id"]
    tech_b = fx.create_technician(gas_certified=True)
    disp = fx.create_paid_dispatch(setup["unit"]["id"], labor_cents=5000)
    fx.assign_dispatch(disp["id"], tech_a_id)
    get_success_data(api.cancel_dispatch(disp["id"], SM))
    tech_a = get_success_data(api.get_technician(tech_a_id, SM))
    tech_b_after = get_success_data(api.get_technician(tech_b["id"], SM))
    assert tech_a["open_dispatch_count"] == 0
    assert tech_b_after["open_dispatch_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: compensating_invariant / plan_price_conserved_suspend_then_resume
# ─────────────────────────────────────────────────────────────────────────────
def test_plan_price_conserved_suspend_then_resume(api):
    """PRD §3.6: "A customer (or `ServiceManager`) suspends an `ACTIVE` plan, freezing
    `next_due_at` so visits are no longer auto-required and incrementing the plan's
    `version`. Resuming a `SUSPENDED` plan requires the owning unit not to be
    `DECOMMISSIONED`; it recomputes `next_due_at`, recomputes the unit's posture, and
    increments the plan's `version`."

    A suspend/resume cycle does not re-price the plan, so annual_price_cents is
    conserved across the round trip.

    Design: Difficulty/compensating_invariant/plan_price_conserved_suspend_then_resume
    """
    setup = fx.setup_activated_unit(rated_kw=26)
    plan = fx.create_active_plan(setup["unit"]["id"], frequency="SEMI_ANNUAL", monitoring_bundled=True)
    assert plan["annual_price_cents"] == 66600
    get_success_data(api.suspend_plan(plan["id"], SM))
    res = api.resume_plan(plan["id"], SM)
    resumed = validate_success(res, 200)
    assert resumed["status"] == "ACTIVE"
    assert resumed["annual_price_cents"] == 66600


def test_plan_price_unchanged_while_version_advances_on_suspend_resume(api):
    """PRD §3.6: "A customer (or `ServiceManager`) suspends an `ACTIVE` plan, freezing
    `next_due_at` so visits are no longer auto-required and incrementing the plan's
    `version`. Resuming a `SUSPENDED` plan requires the owning unit not to be
    `DECOMMISSIONED`; it recomputes `next_due_at`, recomputes the unit's posture, and
    increments the plan's `version`."

    The price is conserved as a money quantity even though both suspend and resume are
    real mutations that advance the plan's version — the conserved value survives two
    version bumps.

    Design: Difficulty/compensating_invariant/plan_price_conserved_suspend_then_resume
    """
    setup = fx.setup_activated_unit(rated_kw=26)
    plan = fx.create_active_plan(setup["unit"]["id"], frequency="SEMI_ANNUAL", monitoring_bundled=True)
    original_price = plan["annual_price_cents"]
    original_version = plan["version"]
    suspended = get_success_data(api.suspend_plan(plan["id"], SM))
    resumed = get_success_data(api.resume_plan(plan["id"], SM))
    assert suspended["version"] > original_version
    assert resumed["version"] > suspended["version"]
    assert resumed["annual_price_cents"] == original_price


# ─────────────────────────────────────────────────────────────────────────────
# Corner: cross_cutting_complexity_layers / occ_dispatch_assign_stale_version_conflict
# ─────────────────────────────────────────────────────────────────────────────
def test_dispatch_assign_with_stale_version_rejected(api):
    """PRD §2.7: "Assigning a technician to a repair dispatch requires the request to
    carry `expected_dispatch_version` matching that `RepairDispatch`'s current
    `version`. If another writer has already assigned or cancelled the dispatch,
    advancing its `version` since the client last read it, the assignment is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_dispatch_assign_stale_version_conflict
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    tech_id = setup["technician"]["id"]
    disp = fx.create_paid_dispatch(setup["unit"]["id"], labor_cents=5000)
    stale_version = disp["version"]
    # First assign (with the fresh version) succeeds and bumps the dispatch version.
    fx.assign_dispatch(disp["id"], tech_id, expected_version=stale_version)
    # Cancel returns the dispatch to a state where re-assign is structurally possible,
    # but the version has advanced past `stale_version`.
    get_success_data(api.cancel_dispatch(disp["id"], SM))
    res = api.assign_dispatch(disp["id"], f.assign_payload(tech_id, stale_version), SM)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: cross_cutting_complexity_layers / derived_runtime_hours_accumulates_on_resolve
# ─────────────────────────────────────────────────────────────────────────────
def test_runtime_hours_accumulates_on_dispatch_resolve(api):
    """PRD §3.8: "Resolving advances `IN_PROGRESS` to `RESOLVED`, optionally adding
    `runtime_added_hours` (defaulting to 0, at least zero) to the unit's
    `runtime_hours`."

    Design: Corner/cross_cutting_complexity_layers/derived_runtime_hours_accumulates_on_resolve
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    unit_id = setup["unit"]["id"]
    tech_id = setup["technician"]["id"]
    assert setup["unit"]["runtime_hours"] == 0
    disp = fx.dispatch_in_progress(unit_id, tech_id, labor_cents=5000)
    get_success_data(
        api.resolve_dispatch(disp["id"], {"runtime_added_hours": 120}, make_technician_headers(tech_id))
    )
    unit = get_success_data(api.get_unit(unit_id, SM))
    assert unit["runtime_hours"] == 120


# ─────────────────────────────────────────────────────────────────────────────
# Corner: cross_cutting_complexity_layers / register_extends_warranty_total_months
# ─────────────────────────────────────────────────────────────────────────────
def test_register_unit_extends_warranty_total_months(api):
    """PRD §3.4: "Setting `register` true moves `registration_status` to `REGISTERED`
    and extends coverage by adding a 12-month registration bonus to
    `warranty_total_months`."

    Design: Corner/cross_cutting_complexity_layers/register_extends_warranty_total_months
    """
    setup = fx.setup_activated_unit(rated_kw=20, warranty_months=60)
    unit_id = setup["unit"]["id"]
    assert setup["unit"]["warranty_total_months"] == 60
    res = api.update_unit(unit_id, {"register": True}, SM)
    registered = validate_success(res, 200)
    assert registered["registration_status"] == "REGISTERED"
    assert registered["warranty_total_months"] == 72


# ─────────────────────────────────────────────────────────────────────────────
# Corner: rbac / customer_cannot_adjudicate_warranty_claim
# ─────────────────────────────────────────────────────────────────────────────
def test_customer_cannot_adjudicate_warranty_claim(api):
    """PRD §2.1: "When a principal presents valid headers but the role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."

    Adjudication is ComplianceOfficer-exclusive; a Customer is rejected with
    ERR_FORBIDDEN.

    Design: Corner/rbac/customer_cannot_adjudicate_warranty_claim
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    customer_id = setup["customer"]["id"]
    unit_id = setup["unit"]["id"]
    claim = fx.file_claim_under_review(unit_id, description="x")
    res = api.adjudicate_claim(
        claim["id"], f.adjudicate_payload("DENY"), make_customer_headers(customer_id)
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: rbac / missing_headers_returns_unauthenticated
# ─────────────────────────────────────────────────────────────────────────────
def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits either header is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    customer = fx.create_customer()
    res = api.get_customer(customer["id"], headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: rbac / complete_visit_by_non_assigned_tech_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_complete_visit_by_non_assigned_tech_rejected(api):
    """PRD §2.1: "a technician who is not the assigned or install technician for the
    targeted resource is rejected with `ERR_NOT_ASSIGNED_TECH`."
    PRD §3.6: "Completion is gated: the acting technician must be the visit's
    `assigned_tech_id`"

    Design: Corner/rbac/complete_visit_by_non_assigned_tech_rejected
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    tech_a_id = setup["technician"]["id"]  # install tech, will be the assigned tech
    tech_b = fx.create_technician(gas_certified=True)
    plan = fx.create_active_plan(setup["unit"]["id"], frequency="ANNUAL")
    visit = fx.schedule_visit(plan["id"], "2026-06-01T09:00:00Z", assigned_tech_id=tech_a_id)
    # Tech B (not the assigned tech) attempts to complete.
    res = api.complete_visit(visit["id"], {}, make_technician_headers(tech_b["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_ASSIGNED_TECH.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: entities / create_customer_returns_201_with_fields
# ─────────────────────────────────────────────────────────────────────────────
def test_create_customer_returns_201_with_defaults(api):
    """PRD §3.1: "A customer record is created by submitting an `email`, a `full_name`,
    and a `service_address`, with an optional `elevation_ft` (the site elevation above
    sea level in feet, defaulting to 0 and never negative)"
    PRD §2.4: "The `version` field is an integer that starts at its initial value and
    increments by one on every mutation of the resource"

    Design: Corner/entities/create_customer_returns_201_with_fields
    """
    res = api.create_customer(
        {"email": f.unique_email(), "full_name": "Cee", "service_address": "1 St"}, SM
    )
    customer = validate_success(res, 201)
    assert customer["elevation_ft"] == 0
    assert customer["version"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Corner: entities / get_customer_not_found_returns_404
# ─────────────────────────────────────────────────────────────────────────────
def test_get_customer_not_found_returns_404(api):
    """PRD §2.5: "the first identifier in the path that does not correspond to an
    existing resource produces `ERR_NOT_FOUND` before any deeper lookup is attempted."

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    res = api.get_customer("00000000-0000-4000-8000-000000000000", SM)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: entities / create_project_missing_required_field_returns_400
# ─────────────────────────────────────────────────────────────────────────────
def test_create_project_missing_fuel_type_returns_400(api):
    """PRD §2.8: "the request body is checked for well-formedness — required fields
    present, enum values valid, numeric ranges respected, and the appliances array
    non-empty — yielding `ERR_INVALID_REQUEST`"
    PRD §3.2: "Creation captures the owning `customer_id`, the declared `fuel_type`
    (either `NG` for natural gas or `PROPANE`, the fuel that will be hooked up)"

    fuel_type is a required input with no default; omitting it is malformed.

    Design: Corner/entities/create_project_missing_required_field_returns_400
    """
    customer = fx.create_customer()
    res = api.create_project({"customer_id": customer["id"]}, SM)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: entities / load_assessment_starting_below_running_returns_422
# ─────────────────────────────────────────────────────────────────────────────
def test_load_assessment_starting_below_running_returns_422(api):
    """PRD §3.2: "A starting-watts figure below the running-watts figure is a semantic
    field violation rejected with `ERR_VALIDATION`."
    PRD §2.8: "a value that parses but violates a field-level semantic rule (such as a
    starting-watts figure below its running-watts figure) yields `ERR_VALIDATION`."

    Design: Corner/entities/load_assessment_starting_below_running_returns_422
    """
    customer, project = fx.create_draft_project(fuel_type="NG")
    res = api.create_load_assessment(
        project["id"],
        {"appliances": [{"name": "bad", "running_watts": 5000, "starting_watts": 1000}]},
        SM,
    )
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: entities / empty_appliances_array_returns_400
# ─────────────────────────────────────────────────────────────────────────────
def test_empty_appliances_array_returns_400(api):
    """PRD §2.8: "the request body is checked for well-formedness — required fields
    present, enum values valid, numeric ranges respected, and the appliances array
    non-empty — yielding `ERR_INVALID_REQUEST`"
    PRD §3.2: "The appliances array must be non-empty"

    Design: Corner/entities/empty_appliances_array_returns_400
    """
    customer, project = fx.create_draft_project(fuel_type="NG")
    res = api.create_load_assessment(project["id"], {"appliances": []}, SM)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: entities / unit_system_fields_generated_input_ignored
# ─────────────────────────────────────────────────────────────────────────────
def test_unit_warranty_start_is_logical_clock_and_total_months_snapshot(api):
    """PRD §3.4: "the unit's `warranty_start` is set to the current clock as the
    warranty-clock origin"
    PRD §3.4: "the model's warranty length into `warranty_total_months`"
    PRD §2.4: "On startup the clock reads exactly `2026-01-01T00:00:00Z`"

    Activation runs at the default clock (never advanced), so warranty_start is the
    2026-01-01 instant rather than any client-supplied value.

    Design: Corner/entities/unit_system_fields_generated_input_ignored
    """
    setup = fx.setup_activated_unit(rated_kw=20, warranty_months=60)
    unit = setup["unit"]
    assert is_iso8601_timestamp(unit["warranty_start"]), "warranty_start must be an ISO 8601 instant"
    parsed = datetime.datetime.fromisoformat(unit["warranty_start"].replace("Z", "+00:00"))
    expected = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    assert parsed == expected, "warranty_start is the default-clock instant 2026-01-01T00:00:00Z"
    assert unit["warranty_total_months"] == 60


# ─────────────────────────────────────────────────────────────────────────────
# Corner: entities / list_customer_projects_paginated_envelope
# ─────────────────────────────────────────────────────────────────────────────
def test_list_customer_projects_paginated_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/list_customer_projects_paginated_envelope
    """
    customer = fx.create_customer()
    get_success_data(api.create_project(f.create_project_payload(customer["id"], fuel_type="PROPANE"), SM))
    data, meta = validate_paginated(api.list_customer_projects(customer["id"], SM, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Corner: entities / model_immutable_no_version_field
# ─────────────────────────────────────────────────────────────────────────────
def test_model_is_lean_no_version_field(api):
    """PRD §2.4: "A `GeneratorModel` carries only `id` and `created_at` — it has no
    `updated_at` and no `version`."

    Design: Corner/entities/model_immutable_no_version_field
    """
    model = fx.create_model(rated_kw=18, fuel_types=["NG", "PROPANE"], warranty_months=48)
    res = api.get_model(model["id"], SM)
    fetched = validate_success(res, 200)
    assert is_iso8601_timestamp(fetched["created_at"])
    assert "version" not in fetched, "GeneratorModel must not carry a version field"
    assert "updated_at" not in fetched, "GeneratorModel must not carry an updated_at field"
