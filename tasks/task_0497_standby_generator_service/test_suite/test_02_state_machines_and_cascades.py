"""State-machine cycles, transitive cascades, terminal lockdown, and invalid
transitions.

Covers difficulty queue A (non_linear_state_machine, transitive_cascade) and
corner queue B (state_machines section, plus the consistency_model fan-out).
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
# Difficulty: non_linear_state_machine / warranty_claim_review_loop_cycle
# ─────────────────────────────────────────────────────────────────────────────
def test_warranty_claim_review_loop_returns_to_open_then_review(api):
    """PRD §3.7: "From `UNDER_REVIEW` the officer may return the claim for more
    information, bouncing it back to `OPEN`; the claim can oscillate between `OPEN`
    and `UNDER_REVIEW` any number of times before a terminal decision."

    Design: Difficulty/non_linear_state_machine/warranty_claim_review_loop_cycle
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    claim = fx.file_warranty_claim(setup["unit"]["id"], description="intermittent fault")
    get_success_data(api.review_claim(claim["id"], CO))
    get_success_data(api.return_claim_for_info(claim["id"], CO))
    res = api.review_claim(claim["id"], CO)
    after = validate_success(res, 200)
    assert after["status"] == "UNDER_REVIEW"


def test_warranty_claim_version_increments_each_review_transition(api):
    """PRD §2.4: "The `version` field is an integer that starts at its initial value
    and increments by one on every mutation of the resource"
    PRD §3.7: "the claim can oscillate between `OPEN` and `UNDER_REVIEW` any number
    of times before a terminal decision."

    Design: Difficulty/non_linear_state_machine/warranty_claim_review_loop_cycle
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    claim = fx.file_warranty_claim(setup["unit"]["id"], description="intermittent fault")
    assert claim["version"] == 1
    get_success_data(api.review_claim(claim["id"], CO))
    get_success_data(api.return_claim_for_info(claim["id"], CO))
    res = api.review_claim(claim["id"], CO)
    after = validate_success(res, 200)
    # create=1, then +3 transition mutations.
    assert after["version"] == 4


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: non_linear_state_machine / repair_dispatch_progress_pause_cycle
# ─────────────────────────────────────────────────────────────────────────────
def test_repair_dispatch_start_pause_start_cycle(api):
    """PRD §3.8: "starting work advances `DISPATCHED` to `IN_PROGRESS`; pausing
    advances `IN_PROGRESS` back to `DISPATCHED`, and a dispatch may oscillate between
    `DISPATCHED` and `IN_PROGRESS` across multiple field visits."

    Design: Difficulty/non_linear_state_machine/repair_dispatch_progress_pause_cycle
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    tech_id = setup["technician"]["id"]
    tech_h = make_technician_headers(tech_id)
    disp = fx.create_paid_dispatch(setup["unit"]["id"], labor_cents=5000)
    fx.assign_dispatch(disp["id"], tech_id)
    get_success_data(api.start_dispatch(disp["id"], tech_h))
    get_success_data(api.pause_dispatch(disp["id"], tech_h))
    res = api.start_dispatch(disp["id"], tech_h)
    after = validate_success(res, 200)
    assert after["status"] == "IN_PROGRESS"


def test_dispatch_open_count_unchanged_across_pause_cycle(api):
    """PRD §3.8: "On assignment the `assigned_tech_id` is recorded, the technician's
    `open_dispatch_count` increments by one"
    PRD §3.8: "a dispatch may oscillate between `DISPATCHED` and `IN_PROGRESS` across
    multiple field visits."

    The open_dispatch_count counts DISPATCHED or IN_PROGRESS dispatches, so the
    start/pause cycle (which keeps the dispatch in that set) leaves the count at 1.

    Design: Difficulty/non_linear_state_machine/repair_dispatch_progress_pause_cycle
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    tech_id = setup["technician"]["id"]
    tech_h = make_technician_headers(tech_id)
    disp = fx.create_paid_dispatch(setup["unit"]["id"], labor_cents=5000)
    fx.assign_dispatch(disp["id"], tech_id)
    get_success_data(api.start_dispatch(disp["id"], tech_h))
    get_success_data(api.pause_dispatch(disp["id"], tech_h))
    get_success_data(api.start_dispatch(disp["id"], tech_h))
    tech = get_success_data(api.get_technician(tech_id, SM))
    assert tech["open_dispatch_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: transitive_cascade / recall_resolve_cascade_depth4_restores_warranty
# ─────────────────────────────────────────────────────────────────────────────
def test_recall_resolve_completes_remediation(api):
    """PRD §3.9: "When the linked `RECALL` dispatch reaches `RESOLVED`, the
    remediation cascades to `COMPLETED` (reachable whether it was `SCHEDULED` or had
    already gone `OVERDUE`)"

    Design: Difficulty/transitive_cascade/recall_resolve_cascade_depth4_restores_warranty
    """
    setup = fx.setup_recall_dispatch_started(rated_kw=22)
    tech_id = setup["technician"]["id"]
    get_success_data(
        api.resolve_dispatch(setup["recall_dispatch_id"], {}, make_technician_headers(tech_id))
    )
    remediation = get_success_data(api.get_recall_remediation(setup["remediation"]["id"], SM))
    assert remediation["status"] == "COMPLETED"


def test_recall_resolve_restores_unit_posture_and_warranty(api):
    """PRD §3.9: "if this cleared the last overdue mandatory remediation, the unit
    returns from `NON_COMPLIANT` to `OPERATIONAL` and its `warranty_status` is
    restored."

    Design: Difficulty/transitive_cascade/recall_resolve_cascade_depth4_restores_warranty
    """
    setup = fx.setup_recall_dispatch_started(rated_kw=22)
    unit_id = setup["unit"]["id"]
    tech_id = setup["technician"]["id"]
    # Precondition: the overdue MANDATORY remediation drove the unit NON_COMPLIANT / VOID.
    pre = get_success_data(api.get_unit(unit_id, SM))
    assert pre["operating_status"] == "NON_COMPLIANT"
    assert pre["warranty_status"] == "VOID"
    get_success_data(
        api.resolve_dispatch(setup["recall_dispatch_id"], {}, make_technician_headers(tech_id))
    )
    unit = get_success_data(api.get_unit(unit_id, SM))
    assert unit["operating_status"] == "OPERATIONAL"
    assert unit["warranty_status"] == "ACTIVE"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: transitive_cascade / decommission_cascade_depth2_cancels_plan_and_visits
# ─────────────────────────────────────────────────────────────────────────────
def test_decommission_cancels_owning_plan(api):
    """PRD §3.9: "Decommissioning moves `operating_status` to its terminal
    `DECOMMISSIONED` state, cancels the unit's `ACTIVE` and `SUSPENDED` maintenance
    plans, cancels its `SCHEDULED` maintenance visits"

    Design: Difficulty/transitive_cascade/decommission_cascade_depth2_cancels_plan_and_visits
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    unit_id = setup["unit"]["id"]
    plan = fx.create_active_plan(unit_id, frequency="ANNUAL")
    visit = fx.schedule_visit(plan["id"], "2026-05-01T09:00:00Z")
    res = api.decommission_unit(unit_id, SM)
    decommissioned = validate_success(res, 200)
    assert decommissioned["operating_status"] == "DECOMMISSIONED"
    after_plan = get_success_data(api.get_maintenance_plan(plan["id"], SM))
    assert after_plan["status"] == "CANCELLED"


def test_decommission_cascades_to_scheduled_visit(api):
    """PRD §3.9: "Decommissioning moves `operating_status` to its terminal
    `DECOMMISSIONED` state, cancels the unit's `ACTIVE` and `SUSPENDED` maintenance
    plans, cancels its `SCHEDULED` maintenance visits"

    Design: Difficulty/transitive_cascade/decommission_cascade_depth2_cancels_plan_and_visits
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    unit_id = setup["unit"]["id"]
    plan = fx.create_active_plan(unit_id, frequency="ANNUAL")
    visit = fx.schedule_visit(plan["id"], "2026-05-01T09:00:00Z")
    get_success_data(api.decommission_unit(unit_id, SM))
    after_visit = get_success_data(api.get_maintenance_visit(visit["id"], SM))
    assert after_visit["status"] == "CANCELLED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner: state_machines / cancel_activated_project_returns_invalid_state
# ─────────────────────────────────────────────────────────────────────────────
def test_cancel_activated_project_rejected(api):
    """PRD §3.4: "A project that is already `ACTIVATED` or `CANCELLED` cannot be
    cancelled — once a unit exists, the decommission path on the unit is used
    instead."

    Design: Corner/state_machines/cancel_activated_project_returns_invalid_state
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    res = api.cancel_project(setup["project"]["id"], {"cancellation_reason": "changed mind"}, SM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: state_machines / size_without_assessment_returns_no_assessment
# ─────────────────────────────────────────────────────────────────────────────
def test_size_with_unknown_assessment_returns_no_assessment(api):
    """PRD §3.2: "sizing with no assessment, or naming an assessment that is not on
    the project, is rejected with `ERR_NO_ASSESSMENT`."

    Design: Corner/state_machines/size_without_assessment_returns_no_assessment
    """
    customer, project = fx.create_draft_project(fuel_type="NG")
    model = fx.create_model(rated_kw=30, fuel_types=["NG"])
    res = api.size_project(
        project["id"],
        f.size_payload("00000000-0000-4000-8000-000000000001", model["id"]),
        SM,
    )
    validate_error(res, ApiErrorId.ERR_NO_ASSESSMENT.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: state_machines / activate_before_permit_approved_returns_permit_not_approved
# ─────────────────────────────────────────────────────────────────────────────
def test_activate_from_sized_state_rejected_invalid_state(api):
    """PRD §2.8: "Then state-transition legality is checked, yielding
    `ERR_INVALID_STATE` when the target is not in a state from which the requested
    transition is allowed."
    PRD §3.4: "A `ServiceManager` activates an installed project, advancing it from
    `INSTALLED` to its terminal `ACTIVATED` state"

    Activation is reachable only from INSTALLED; a SIZED project is not in that
    from-state, so activate returns ERR_INVALID_STATE.

    Design: Corner/state_machines/activate_before_permit_approved_returns_permit_not_approved
    """
    sized = fx.setup_sized_project(rated_kw=30, fuel_type="NG")
    res = api.activate_project(sized["project"]["id"], f.activate_payload(), SM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: state_machines / campaign_close_with_open_remediation_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_close_campaign_with_pending_remediation_rejected(api):
    """PRD §3.9: "A campaign may later be closed by a `ComplianceOfficer`, but only
    when no remediation under it is still `PENDING` or `SCHEDULED`; closing with open
    remediations is rejected with `ERR_CAMPAIGN_HAS_OPEN_REMEDIATIONS`."

    Design: Corner/state_machines/campaign_close_with_open_remediation_rejected
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    campaign = fx.create_open_campaign(
        setup["model"]["id"], severity="ADVISORY", remediation_window_days=90
    )
    res = api.close_campaign(campaign["id"], CO)
    validate_error(res, ApiErrorId.ERR_CAMPAIGN_HAS_OPEN_REMEDIATIONS.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: state_machines / withdrawn_claim_terminal_lockdown
# ─────────────────────────────────────────────────────────────────────────────
def test_withdraw_already_withdrawn_claim_rejected(api):
    """PRD §3.7: "A customer who owns the claimed unit may withdraw a claim from
    either `OPEN` or `UNDER_REVIEW`, moving it to `WITHDRAWN` and incrementing its
    `version`."
    PRD §2.8: "Then state-transition legality is checked, yielding `ERR_INVALID_STATE`
    when the target is not in a state from which the requested transition is allowed."

    Design: Corner/state_machines/withdrawn_claim_terminal_lockdown
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    claim = fx.file_warranty_claim(setup["unit"]["id"], description="x")
    get_success_data(api.withdraw_claim(claim["id"], SM))
    res = api.withdraw_claim(claim["id"], SM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: state_machines / dispatch_cancel_in_progress_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_cancel_in_progress_dispatch_rejected(api):
    """PRD §3.8: "A dispatch in `REQUESTED` or `DISPATCHED` may be cancelled by a
    `ServiceManager` — but it cannot be cancelled once `IN_PROGRESS`"

    Design: Corner/state_machines/dispatch_cancel_in_progress_rejected
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    tech_id = setup["technician"]["id"]
    disp = fx.dispatch_in_progress(setup["unit"]["id"], tech_id, labor_cents=5000)
    assert disp["status"] == "IN_PROGRESS"
    res = api.cancel_dispatch(disp["id"], SM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: state_machines / bubble_up_warranty_repair_dispatch_spawned
# ─────────────────────────────────────────────────────────────────────────────
def test_adjudicate_repair_covered_spawns_warranty_dispatch(api):
    """PRD §3.7: "When the resolution is `REPAIR_COVERED`, the system spawns a
    `RepairDispatch` with origin `WARRANTY` in `REQUESTED` status and records its id
    as the claim's `dispatch_id`."
    PRD §3.8: "A dispatch is `billable` only when its origin is `PAID` — `WARRANTY`
    and `RECALL` dispatches are no-charge and carry an `invoice_total_cents` of 0."

    Design: Corner/state_machines/bubble_up_warranty_repair_dispatch_spawned
    """
    setup = fx.setup_activated_unit(rated_kw=20)
    claim = fx.file_claim_under_review(setup["unit"]["id"], description="covered defect")
    res = api.adjudicate_claim(claim["id"], f.adjudicate_payload("APPROVE", resolution="REPAIR_COVERED"), CO)
    adjudicated = validate_success(res, 200)
    assert adjudicated["status"] == "APPROVED"
    assert adjudicated["dispatch_id"] is not None
    dispatch = get_success_data(api.get_repair_dispatch(adjudicated["dispatch_id"], SM))
    assert dispatch["origin"] == "WARRANTY"
    assert dispatch["billable"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Corner: consistency_model / recall_open_fanout_visible_immediately
# ─────────────────────────────────────────────────────────────────────────────
def test_recall_open_fanout_affected_unit_count_immediate(api):
    """PRD §3.9: "Opening a campaign sets `opened_at` to the current clock and fans
    out: for every `ACTIVATED` unit whose `model_id` matches the campaign's model and
    whose `operating_status` is not `DECOMMISSIONED`, the system creates a
    `RecallRemediation` in `PENDING` status"
    PRD §3.9: "The campaign's `affected_unit_count` is set to the number of
    remediations created"

    Design: Corner/consistency_model/recall_open_fanout_visible_immediately
    """
    # Two ACTIVATED units of the SAME model.
    first = fx.setup_activated_unit(rated_kw=20)
    model_id = first["model"]["id"]
    customer2, project2 = fx.create_draft_project(fuel_type="NG")
    tech2 = fx.create_technician(gas_certified=True)
    assessment2 = fx.add_load_assessment(project2["id"])
    get_success_data(api.size_project(project2["id"], f.size_payload(assessment2["id"], model_id), SM))
    get_success_data(api.permit_project(project2["id"], f.permit_payload(), SM))
    get_success_data(api.install_project(project2["id"], f.install_payload(tech2["id"]), SM))
    get_success_data(api.activate_project(project2["id"], f.activate_payload(), SM))

    campaign = get_success_data(
        api.create_recall_campaign(
            f.recall_campaign_payload(model_id, severity="MANDATORY", remediation_window_days=60), CO
        )
    )
    res = api.open_campaign(campaign["id"], CO)
    opened = validate_success(res, 200)
    assert opened["affected_unit_count"] == 2
