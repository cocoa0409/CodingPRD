"""Business-constraint and validation-priority enforcement: cross-entity gates,
priority-pair conflicts, temporal-overlap collisions, and single-rule violations.

Covers difficulty queue A (priority_pair_validation_conflict,
cross_entity_state_dependency, resource_temporal_overlap) and corner queue B
(validations section).
"""
import pytest

from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
    factories as f,
    make_technician_headers,
)

SM = TEST_USERS["service_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: priority_pair_validation_conflict / warranty_lapsed_beats_invalid_state
# ─────────────────────────────────────────────────────────────────────────────
def test_review_withdrawn_void_warranty_claim_returns_invalid_state(api):
    """PRD §2.8: "Then state-transition legality is checked, yielding
    `ERR_INVALID_STATE` when the target is not in a state from which the requested
    transition is allowed. Business-safety and business-constraint checks run last"

    The claim is WITHDRAWN (a state violation for review) AND on a VOID-warranty unit
    (a business-safety violation). State legality is checked before the business-safety
    warranty gate, so ERR_INVALID_STATE wins.

    Design: Difficulty/priority_pair_validation_conflict/warranty_lapsed_beats_invalid_state_on_review
    """
    setup = fx.setup_activated_unit(rated_kw=22)
    unit_id = setup["unit"]["id"]
    claim = fx.file_warranty_claim(unit_id, description="early claim")
    get_success_data(api.withdraw_claim(claim["id"], SM))
    # Drive warranty VOID via an overdue MANDATORY recall.
    fx.create_open_campaign(setup["model"]["id"], severity="MANDATORY", remediation_window_days=10)
    fx.set_clock("2026-02-01T00:00:00Z")
    void_unit = get_success_data(api.get_unit(unit_id, SM))
    assert void_unit["warranty_status"] == "VOID"
    res = api.review_claim(claim["id"], CO)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: priority_pair_validation_conflict / non_compliant_beats_segregation
# ─────────────────────────────────────────────────────────────────────────────
def test_resolve_non_recall_dispatch_on_non_compliant_unit_rejected(api):
    """PRD §3.8: "A unit that is `NON_COMPLIANT` blocks resolution of a non-recall
    dispatch with `ERR_UNIT_NON_COMPLIANT`; recall-origin resolution is exempt
    because it is the very work that clears the non-compliance."

    Design: Difficulty/priority_pair_validation_conflict/non_compliant_beats_segregation_on_resolve_then_close
    """
    setup = fx.setup_activated_unit(rated_kw=22)
    unit_id = setup["unit"]["id"]
    tech_id = setup["technician"]["id"]
    disp = fx.dispatch_in_progress(unit_id, tech_id, labor_cents=5000)
    # Drive the unit NON_COMPLIANT via overdue MANDATORY recall.
    fx.create_open_campaign(setup["model"]["id"], severity="MANDATORY", remediation_window_days=10)
    fx.set_clock("2026-02-01T00:00:00Z")
    nc_unit = get_success_data(api.get_unit(unit_id, SM))
    assert nc_unit["operating_status"] == "NON_COMPLIANT"
    res = api.resolve_dispatch(disp["id"], {}, make_technician_headers(tech_id))
    validate_error(res, ApiErrorId.ERR_UNIT_NON_COMPLIANT.value)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: cross_entity_state_dependency / warranty_review_requires_unit_warranty_active
# ─────────────────────────────────────────────────────────────────────────────
def test_review_blocked_when_parent_unit_warranty_void(api):
    """PRD §3.7: "A `ComplianceOfficer` moves a claim from `OPEN` to `UNDER_REVIEW`,
    but only while the unit's `warranty_status` is `ACTIVE` at the time of review — a
    unit whose warranty is `LAPSED` or `VOID` blocks review with `ERR_WARRANTY_LAPSED`."

    Design: Difficulty/cross_entity_state_dependency/warranty_review_requires_unit_warranty_active
    """
    setup = fx.setup_activated_unit(rated_kw=22)
    unit_id = setup["unit"]["id"]
    # File an OPEN claim while warranty is still ACTIVE.
    claim = fx.file_warranty_claim(unit_id, description="fault before recall")
    # Now void the warranty via an overdue MANDATORY recall.
    fx.create_open_campaign(setup["model"]["id"], severity="MANDATORY", remediation_window_days=10)
    fx.set_clock("2026-02-01T00:00:00Z")
    void_unit = get_success_data(api.get_unit(unit_id, SM))
    assert void_unit["warranty_status"] == "VOID"
    res = api.review_claim(claim["id"], CO)
    validate_error(res, ApiErrorId.ERR_WARRANTY_LAPSED.value)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: cross_entity_state_dependency / remediation_schedule_requires_unit_not_decommissioned
# ─────────────────────────────────────────────────────────────────────────────
def test_schedule_remediation_on_decommissioned_unit_rejected(api):
    """PRD §3.9: "Scheduling requires the remediation to be `PENDING` and not already
    `OVERDUE` ... and the owning unit must not be `DECOMMISSIONED`."
    PRD §2.8: "Then state-transition legality is checked, yielding `ERR_INVALID_STATE`
    when the target is not in a state from which the requested transition is allowed."

    Design: Difficulty/cross_entity_state_dependency/remediation_schedule_requires_unit_not_decommissioned
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    unit_id = setup["unit"]["id"]
    fx.create_open_campaign(setup["model"]["id"], severity="ADVISORY", remediation_window_days=90)
    remediation = fx.get_unit_remediation(unit_id)
    get_success_data(api.decommission_unit(unit_id, SM))
    decommissioned = get_success_data(api.get_unit(unit_id, SM))
    assert decommissioned["operating_status"] == "DECOMMISSIONED"
    res = api.schedule_remediation(remediation["id"], SM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: resource_temporal_overlap / technician_buffer_overlap_half_open_4h
# ─────────────────────────────────────────────────────────────────────────────
def test_tech_double_booked_within_4h_buffer_on_different_units(api):
    """PRD §3.6: "when an `assigned_tech_id` is provided, that technician must not
    already have a `SCHEDULED` visit whose `scheduled_for` falls within a four-hour
    buffer of the new one — specifically, the new visit is rejected with
    `ERR_TECH_DOUBLE_BOOKED` if it lies in the half-open window from four hours before
    the other visit up to (but not including) four hours after it."

    Design: Difficulty/resource_temporal_overlap/technician_buffer_overlap_half_open_4h
    """
    # Two different units sharing one technician; tech assigned to a 09:00 visit on unit A.
    first = fx.setup_activated_unit(rated_kw=20)
    tech_id = first["technician"]["id"]
    plan_a = fx.create_active_plan(first["unit"]["id"], frequency="ANNUAL")
    fx.schedule_visit(plan_a["id"], "2026-04-10T09:00:00Z", assigned_tech_id=tech_id)

    second = fx.setup_activated_unit(rated_kw=20)
    plan_b = fx.create_active_plan(second["unit"]["id"], frequency="ANNUAL")
    # 11:00 is 2h after the 09:00 visit -> inside the half-open buffer.
    res = api.schedule_visit(
        plan_b["id"], f.visit_payload("2026-04-10T11:00:00Z", assigned_tech_id=tech_id), SM
    )
    validate_error(res, ApiErrorId.ERR_TECH_DOUBLE_BOOKED.value)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: resource_temporal_overlap / unit_same_day_collision_closed_daybucket
# ─────────────────────────────────────────────────────────────────────────────
def test_unit_same_day_visit_collision_closed_daybucket(api):
    """PRD §3.6: "the unit cannot already have a `SCHEDULED` visit on the same UTC
    calendar day: the day is treated as a closed bucket spanning the whole calendar
    date, so any two visit timestamps sharing the same UTC date collide regardless of
    the hour, and the second is rejected with `ERR_UNIT_VISIT_COLLISION`."

    Design: Difficulty/resource_temporal_overlap/unit_same_day_collision_closed_daybucket
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    plan = fx.create_active_plan(setup["unit"]["id"], frequency="SEMI_ANNUAL")
    # First visit, no tech assigned (so the tech-buffer rule cannot fire).
    fx.schedule_visit(plan["id"], "2026-04-12T09:00:00Z")
    # Second visit on the same UTC day, 11h later, still no tech.
    res = api.schedule_visit(plan["id"], f.visit_payload("2026-04-12T20:00:00Z"), SM)
    validate_error(res, ApiErrorId.ERR_UNIT_VISIT_COLLISION.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: validations / size_with_undersized_model_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_size_with_undersized_model_rejected(api):
    """PRD §3.2: "The model must be adequate: its `rated_kw` must be at least the
    selected assessment's required kilowatts ... a model whose rating is below the
    requirement or whose fuel list excludes the project fuel is rejected with
    `ERR_MODEL_UNDERSIZED`."

    Design: Corner/validations/size_with_undersized_model_rejected
    """
    customer, project = fx.create_draft_project(fuel_type="NG")
    model = fx.create_model(rated_kw=14, fuel_types=["NG"])  # below the 15.0 kW requirement
    assessment = fx.add_load_assessment(
        project["id"], appliances=[{"name": "ac", "running_watts": 4000, "starting_watts": 12000}]
    )
    res = api.size_project(project["id"], f.size_payload(assessment["id"], model["id"]), SM)
    validate_error(res, ApiErrorId.ERR_MODEL_UNDERSIZED.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: validations / size_with_fuel_incompatible_model_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_size_with_fuel_incompatible_model_rejected(api):
    """PRD §3.2: "its `fuel_types` must include the project's declared `fuel_type`; a
    model whose rating is below the requirement or whose fuel list excludes the
    project fuel is rejected with `ERR_MODEL_UNDERSIZED`."

    Design: Corner/validations/size_with_fuel_incompatible_model_rejected
    """
    customer, project = fx.create_draft_project(fuel_type="PROPANE")
    model = fx.create_model(rated_kw=30, fuel_types=["NG"])  # adequate kW but NG-only
    assessment = fx.add_load_assessment(project["id"])
    res = api.size_project(project["id"], f.size_payload(assessment["id"], model["id"]), SM)
    validate_error(res, ApiErrorId.ERR_MODEL_UNDERSIZED.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: validations / install_with_non_gas_certified_tech_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_install_with_non_gas_certified_tech_rejected(api):
    """PRD §3.3: "The named install technician must be `ACTIVE` and must hold
    `gas_certified` true — required to sign off the propane or natural-gas fuel
    hookup; a suspended or non-gas-certified technician is rejected with
    `ERR_TECH_NOT_QUALIFIED`."

    Design: Corner/validations/install_with_non_gas_certified_tech_rejected
    """
    permitted = fx.setup_permitted_project(rated_kw=20, fuel_type="NG", gas_certified=False)
    res = api.install_project(
        permitted["project"]["id"], f.install_payload(permitted["technician"]["id"]), SM
    )
    validate_error(res, ApiErrorId.ERR_TECH_NOT_QUALIFIED.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: validations / duplicate_serial_on_activate_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_duplicate_serial_on_activate_rejected(api):
    """PRD §3.4: "the supplied `serial_no` must be unique and non-empty across all
    units, with a collision rejected as `ERR_DUPLICATE_SERIAL`."

    Design: Corner/validations/duplicate_serial_on_activate_rejected
    """
    first = fx.setup_activated_unit(rated_kw=20)
    used_serial = first["unit"]["serial_no"]
    # Second project installed and ready to activate with the same serial.
    second = fx.setup_installed_project(rated_kw=20, fuel_type="NG")
    res = api.activate_project(second["project"]["id"], f.activate_payload(serial_no=used_serial), SM)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_SERIAL.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: validations / reference_not_found_unknown_customer_on_project_create
# ─────────────────────────────────────────────────────────────────────────────
def test_project_create_with_unknown_customer_returns_reference_not_found(api):
    """PRD §2.8: "Then foreign-key body references (such as `customer_id`, `model_id`,
    `assigned_tech_id`, and `install_tech_id`) are resolved, yielding
    `ERR_REFERENCE_NOT_FOUND` when a referenced row does not exist."

    Design: Corner/validations/reference_not_found_unknown_customer_on_project_create
    """
    res = api.create_project(
        f.create_project_payload("00000000-0000-4000-8000-0000000000aa", fuel_type="NG"), SM
    )
    validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: boundary_precision_check / tech_load_cap_5_boundary_on_assign
# ─────────────────────────────────────────────────────────────────────────────
def test_assign_at_count_5_rejected_tech_overloaded(api):
    """PRD §3.8: "The named technician must be `ACTIVE`, and the technician's
    `open_dispatch_count` must be below 5 — a technician already at five open
    dispatches is rejected with `ERR_TECH_OVERLOADED`."

    Design: Difficulty/boundary_precision_check/tech_load_cap_5_boundary_on_assign
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    unit_id = setup["unit"]["id"]
    tech_id = setup["technician"]["id"]
    fx.saturate_tech_dispatches(unit_id, tech_id, count=5)
    at_cap = get_success_data(api.get_technician(tech_id, SM))
    assert at_cap["open_dispatch_count"] == 5
    sixth = fx.create_paid_dispatch(unit_id, labor_cents=100)
    res = api.assign_dispatch(sixth["id"], f.assign_payload(tech_id, sixth["version"]), SM)
    validate_error(res, ApiErrorId.ERR_TECH_OVERLOADED.value)


def test_assign_at_count_4_succeeds_below_cap(api):
    """PRD §3.8: "the technician's `open_dispatch_count` must be below 5 — a
    technician already at five open dispatches is rejected with `ERR_TECH_OVERLOADED`."

    At count 4 (still below the cap) the 5th assignment succeeds and lifts the count
    to exactly 5 — the boundary value at which the next assign would be rejected.

    Design: Difficulty/boundary_precision_check/tech_load_cap_5_boundary_on_assign
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    unit_id = setup["unit"]["id"]
    tech_id = setup["technician"]["id"]
    fx.saturate_tech_dispatches(unit_id, tech_id, count=4)
    below_cap = get_success_data(api.get_technician(tech_id, SM))
    assert below_cap["open_dispatch_count"] == 4
    fifth = fx.create_paid_dispatch(unit_id, labor_cents=100)
    res = api.assign_dispatch(fifth["id"], f.assign_payload(tech_id, fifth["version"]), SM)
    assigned = validate_success(res, 200)
    assert assigned["status"] == "DISPATCHED"
    at_cap = get_success_data(api.get_technician(tech_id, SM))
    assert at_cap["open_dispatch_count"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: resource_temporal_overlap / technician_buffer_overlap_half_open_4h
#   second test — the open right boundary at exactly +4h is allowed
# ─────────────────────────────────────────────────────────────────────────────
def test_tech_visit_exactly_4h_after_is_allowed_right_open_boundary(api):
    """PRD §3.6: "A new visit exactly four hours after an existing one is allowed
    because the right boundary is open."

    Design: Difficulty/resource_temporal_overlap/technician_buffer_overlap_half_open_4h
    """
    first = fx.setup_activated_unit(rated_kw=20)
    tech_id = first["technician"]["id"]
    plan_a = fx.create_active_plan(first["unit"]["id"], frequency="ANNUAL")
    fx.schedule_visit(plan_a["id"], "2026-04-10T09:00:00Z", assigned_tech_id=tech_id)

    second = fx.setup_activated_unit(rated_kw=20)
    plan_b = fx.create_active_plan(second["unit"]["id"], frequency="ANNUAL")
    # 13:00 is exactly +4h after the 09:00 visit -> outside the half-open window.
    res = api.schedule_visit(
        plan_b["id"], f.visit_payload("2026-04-10T13:00:00Z", assigned_tech_id=tech_id), SM
    )
    visit = validate_success(res, 201)
    assert visit["status"] == "SCHEDULED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: resource_temporal_overlap / unit_same_day_collision_closed_daybucket
#   second test — a visit on a DIFFERENT UTC day on the same unit is allowed
# ─────────────────────────────────────────────────────────────────────────────
def test_unit_visit_on_different_day_is_allowed(api):
    """PRD §3.6: "the unit cannot already have a `SCHEDULED` visit on the same UTC
    calendar day: the day is treated as a closed bucket spanning the whole calendar
    date, so any two visit timestamps sharing the same UTC date collide regardless of
    the hour"

    A second visit on a different calendar date does not share the day bucket, so it
    is accepted.

    Design: Difficulty/resource_temporal_overlap/unit_same_day_collision_closed_daybucket
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    plan = fx.create_active_plan(setup["unit"]["id"], frequency="SEMI_ANNUAL")
    fx.schedule_visit(plan["id"], "2026-04-12T09:00:00Z")
    # Next calendar day -> different day bucket, no collision.
    res = api.schedule_visit(plan["id"], f.visit_payload("2026-04-13T09:00:00Z"), SM)
    visit = validate_success(res, 201)
    assert visit["status"] == "SCHEDULED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: priority_pair_validation_conflict / warranty_lapsed_beats_invalid_state
#   second test — the state check fires for a WITHDRAWN claim even with ACTIVE warranty
# ─────────────────────────────────────────────────────────────────────────────
def test_review_withdrawn_claim_with_active_warranty_still_invalid_state(api):
    """PRD §2.8: "Then state-transition legality is checked, yielding
    `ERR_INVALID_STATE` when the target is not in a state from which the requested
    transition is allowed. Business-safety and business-constraint checks run last"

    The state check fires on a WITHDRAWN claim regardless of warranty: even when the
    warranty is still ACTIVE (so the §10 warranty gate could not fire), review of a
    terminal WITHDRAWN claim returns ERR_INVALID_STATE — confirming the state path is
    reached before the lower-precedence business-safety path.

    Design: Difficulty/priority_pair_validation_conflict/warranty_lapsed_beats_invalid_state_on_review
    """
    setup = fx.setup_activated_unit(rated_kw=22)
    claim = fx.file_warranty_claim(setup["unit"]["id"], description="early claim")
    get_success_data(api.withdraw_claim(claim["id"], SM))
    active_unit = get_success_data(api.get_unit(setup["unit"]["id"], SM))
    assert active_unit["warranty_status"] == "ACTIVE"
    res = api.review_claim(claim["id"], CO)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: priority_pair_validation_conflict / non_compliant_beats_segregation
#   second test — recall-origin resolution on the same NON_COMPLIANT unit is exempt
# ─────────────────────────────────────────────────────────────────────────────
def test_recall_origin_resolve_on_non_compliant_unit_is_exempt(api):
    """PRD §3.8: "A unit that is `NON_COMPLIANT` blocks resolution of a non-recall
    dispatch with `ERR_UNIT_NON_COMPLIANT`; recall-origin resolution is exempt because
    it is the very work that clears the non-compliance."

    Where a non-recall resolve is blocked, the RECALL-origin resolve on the same
    NON_COMPLIANT unit is exempt and succeeds — the same guard with the opposite
    (exempt) branch.

    Design: Difficulty/priority_pair_validation_conflict/non_compliant_beats_segregation_on_resolve_then_close
    """
    setup = fx.setup_recall_dispatch_started(rated_kw=22)
    unit_id = setup["unit"]["id"]
    tech_id = setup["technician"]["id"]
    pre = get_success_data(api.get_unit(unit_id, SM))
    assert pre["operating_status"] == "NON_COMPLIANT"
    res = api.resolve_dispatch(setup["recall_dispatch_id"], {}, make_technician_headers(tech_id))
    resolved = validate_success(res, 200)
    assert resolved["status"] == "RESOLVED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: cross_entity_state_dependency / warranty_review_requires_unit_warranty_active
#   second test — with the parent unit's warranty ACTIVE, review succeeds
# ─────────────────────────────────────────────────────────────────────────────
def test_review_succeeds_when_parent_unit_warranty_active(api):
    """PRD §3.7: "A `ComplianceOfficer` moves a claim from `OPEN` to `UNDER_REVIEW`,
    but only while the unit's `warranty_status` is `ACTIVE` at the time of review"

    The same cross-entity gate, taken on its passing branch: while the parent unit's
    warranty is ACTIVE, the OPEN -> UNDER_REVIEW transition is allowed.

    Design: Difficulty/cross_entity_state_dependency/warranty_review_requires_unit_warranty_active
    """
    setup = fx.setup_activated_unit(rated_kw=22)
    unit = get_success_data(api.get_unit(setup["unit"]["id"], SM))
    assert unit["warranty_status"] == "ACTIVE"
    claim = fx.file_warranty_claim(setup["unit"]["id"], description="fault")
    res = api.review_claim(claim["id"], CO)
    reviewed = validate_success(res, 200)
    assert reviewed["status"] == "UNDER_REVIEW"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: cross_entity_state_dependency / remediation_schedule_requires_unit_not_decommissioned
#   second test — on a non-decommissioned unit the same schedule transition succeeds
# ─────────────────────────────────────────────────────────────────────────────
def test_schedule_remediation_on_operational_unit_succeeds(api):
    """PRD §3.9: "A `ServiceManager` schedules a `PENDING` remediation, spawning a
    `RECALL`-origin repair dispatch in `REQUESTED`, recording its id on the
    remediation's `dispatch_id`, and moving the remediation to `SCHEDULED`."

    The same gate, taken on its passing branch: while the owning unit is OPERATIONAL
    (not DECOMMISSIONED), the PENDING -> SCHEDULED transition is allowed.

    Design: Difficulty/cross_entity_state_dependency/remediation_schedule_requires_unit_not_decommissioned
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    unit_id = setup["unit"]["id"]
    fx.create_open_campaign(setup["model"]["id"], severity="ADVISORY", remediation_window_days=90)
    remediation = fx.get_unit_remediation(unit_id)
    res = api.schedule_remediation(remediation["id"], SM)
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["dispatch_id"] is not None
