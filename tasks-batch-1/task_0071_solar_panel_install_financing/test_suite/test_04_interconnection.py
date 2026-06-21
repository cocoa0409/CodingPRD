"""Interconnection review: feeder-headroom ledger, PTO cascade, precedence."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_homeowner_headers, make_utility_headers,
    register_homeowner, register_installer, register_utility,
    create_active_plan, drive_to_installed,
    setup_under_review_application, setup_installed_with_approved_app,
    setup_pto_pending_with_approved_app, setup_operational_project,
    create_interconnection_application_payload, make_installer_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# --- Difficulty: boundary_precision_check / feeder_headroom_exact_equality_approves ---

def test_feeder_headroom_exact_equality_approves(api):
    """PRD 3.7: "it is permitted only when the utility's feeder_headroom_kw is at
    least the application's requested_export_kw, failing which it is rejected with
    ERR_INSUFFICIENT_FEEDER_HEADROOM (HTTP 422)."

    Design: Difficulty/boundary_precision_check/feeder_headroom_exact_equality_approves
    """
    ctx = setup_under_review_application(feeder_headroom_kw=7.0, requested_export_kw=7.0)
    resp = api.approve_interconnection(ctx["app"]["id"], ctx["util_headers"])
    data = validate_success(resp, 200)
    assert data["status"] == "APPROVED"


def test_feeder_headroom_decrements_to_zero_at_boundary(api):
    """PRD 3.7: "On approval the utility's feeder_headroom_kw is decremented by the
    requested_export_kw, and both the utility's and the application's version
    increment."

    Design: Difficulty/boundary_precision_check/feeder_headroom_exact_equality_approves
    """
    ctx = setup_under_review_application(feeder_headroom_kw=7.0, requested_export_kw=7.0)
    get_success_data(api.approve_interconnection(ctx["app"]["id"], ctx["util_headers"]))
    util = get_success_data(api.get_utility(ctx["utility"]["id"], ctx["util_headers"]))
    assert util["feeder_headroom_kw"] == 0.0


def test_approve_below_headroom_rejected(api):
    """PRD 3.7: "it is permitted only when the utility's feeder_headroom_kw is at
    least the application's requested_export_kw, failing which it is rejected with
    ERR_INSUFFICIENT_FEEDER_HEADROOM (HTTP 422)."

    Design: Difficulty/boundary_precision_check/feeder_headroom_exact_equality_approves
    """
    ctx = setup_under_review_application(feeder_headroom_kw=6.0, requested_export_kw=7.0)
    resp = api.approve_interconnection(ctx["app"]["id"], ctx["util_headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FEEDER_HEADROOM, 422)


# --- Difficulty: compensating_invariant / feeder_headroom_conserved_on_withdraw ---

def test_withdraw_restores_feeder_headroom(api):
    """PRD 3.7: "Withdrawal is the compensating action for approval: it restores
    the utility's feeder_headroom_kw by exactly the requested_export_kw the
    approval decremented, conserving total feeder capacity, and increments both
    the utility's and the application's version."

    Design: Difficulty/compensating_invariant/feeder_headroom_conserved_on_withdraw
    """
    ctx = setup_under_review_application(feeder_headroom_kw=1000.0, requested_export_kw=7.0)
    get_success_data(api.approve_interconnection(ctx["app"]["id"], ctx["util_headers"]))
    get_success_data(api.withdraw_interconnection(ctx["app"]["id"], ctx["util_headers"]))
    util = get_success_data(api.get_utility(ctx["utility"]["id"], ctx["util_headers"]))
    assert util["feeder_headroom_kw"] == 1000.0


def test_withdraw_moves_application_to_rejected(api):
    """PRD 3.7: "An already-approved application may be withdrawn — moving APPROVED
    to REJECTED — but only while its project has not yet reached OPERATIONAL."

    Design: Difficulty/compensating_invariant/feeder_headroom_conserved_on_withdraw
    """
    ctx = setup_under_review_application(feeder_headroom_kw=1000.0, requested_export_kw=7.0)
    get_success_data(api.approve_interconnection(ctx["app"]["id"], ctx["util_headers"]))
    resp = api.withdraw_interconnection(ctx["app"]["id"], ctx["util_headers"])
    data = validate_success(resp, 200)
    assert data["status"] == "REJECTED"


# --- Difficulty: priority_pair_validation_conflict / state_vs_safety ---

def test_approve_filed_app_over_headroom_fails_state_first(api):
    """PRD 2.9: "then whether the target is in a state from which the requested
    transition is defined (ERR_INVALID_STATE). Only after these structural gates
    pass does the system evaluate domain-specific business rules"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_interconnection_approve
    """
    # App is FILED (never begin-review'd) AND requested 7.0 > headroom 2.0.
    homeowner, installer, project, plan = create_active_plan(model="LEASE")
    utility = register_utility(state_code="CA", feeder_headroom_kw=2.0)
    inst_headers = make_installer_headers(installer["id"])
    util_headers = make_utility_headers(utility["id"])
    drive_to_installed(homeowner, installer, project)
    app = get_success_data(api.create_interconnection_application(
        create_interconnection_application_payload(
            project_id=project["id"], utility_id=utility["id"], requested_export_kw=7.0,
        ),
        inst_headers,
    ))
    resp = api.approve_interconnection(app["id"], util_headers)
    # State check (priority 5) precedes business-safety (priority 13).
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_state_check_precedes_safety_returns_409_not_422(api):
    """PRD 2.9: "Within a single endpoint the structural order above always holds;
    the business checks specific to each endpoint are described alongside their
    workflows in Section 3."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_interconnection_approve
    """
    homeowner, installer, project, plan = create_active_plan(model="LEASE")
    utility = register_utility(state_code="CA", feeder_headroom_kw=2.0)
    inst_headers = make_installer_headers(installer["id"])
    util_headers = make_utility_headers(utility["id"])
    drive_to_installed(homeowner, installer, project)
    app = get_success_data(api.create_interconnection_application(
        create_interconnection_application_payload(
            project_id=project["id"], utility_id=utility["id"], requested_export_kw=7.0,
        ),
        inst_headers,
    ))
    resp = api.approve_interconnection(app["id"], util_headers)
    assert resp.status_code == 409, f"Expected 409 (state), got {resp.status_code}"


# --- Difficulty: priority_pair_validation_conflict / owner_vs_state ---

def test_non_owner_cancel_operational_fails_ownership_first(api):
    """PRD 2.9: "then resource ownership for entity-backed callers
    (ERR_NOT_RESOURCE_OWNER), then whether the target is in a state from which the
    requested transition is defined (ERR_INVALID_STATE)."

    Design: Difficulty/priority_pair_validation_conflict/owner_vs_state_on_project_cancel
    """
    ctx = setup_operational_project()
    other = register_homeowner(state_code="CA")
    other_headers = make_homeowner_headers(other["id"])
    # Operational (un-cancellable) project cancelled by a non-owner.
    resp = api.cancel_project(ctx["project"]["id"], other_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)


def test_non_owner_cancel_returns_403_not_409(api):
    """PRD 2.1: "When a role is permitted in general but the acting principal does
    not own the specific resource being acted upon, the request is rejected with
    ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/owner_vs_state_on_project_cancel
    """
    ctx = setup_operational_project()
    other = register_homeowner(state_code="CA")
    other_headers = make_homeowner_headers(other["id"])
    resp = api.cancel_project(ctx["project"]["id"], other_headers)
    assert resp.status_code == 403, f"Expected 403 (ownership), got {resp.status_code}"


# --- Difficulty: cross_entity_state_dependency / grant_pto_requires_project_pto_pending ---

def test_grant_pto_requires_project_pto_pending(api):
    """PRD 3.7: "Finally, granting PTO moves an APPROVED application to the
    terminal PTO_GRANTED state, but only when its project is in PTO_PENDING"

    Design: Difficulty/cross_entity_state_dependency/grant_pto_requires_project_pto_pending
    """
    # Project at INSTALLED (inspection not run) with app APPROVED.
    ctx = setup_installed_with_approved_app()
    resp = api.grant_pto(ctx["app"]["id"], ctx["util_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_grant_pto_blocked_app_stays_approved(api):
    """PRD 3.7: "Finally, granting PTO moves an APPROVED application to the
    terminal PTO_GRANTED state, but only when its project is in PTO_PENDING"

    Design: Difficulty/cross_entity_state_dependency/grant_pto_requires_project_pto_pending
    """
    ctx = setup_installed_with_approved_app()
    api.grant_pto(ctx["app"]["id"], ctx["util_headers"])
    app = get_success_data(api.get_interconnection_application(ctx["app"]["id"], ctx["util_headers"]))
    assert app["status"] == "APPROVED"


# --- Difficulty: transitive_cascade / grant_pto_depth3_app_project_warranty ---

def test_grant_pto_cascades_app_project_warranty(api):
    """PRD 3.6: "When a Utility grants PTO on an application (Section 3.8) whose
    project is in PTO_PENDING, the project transitions to OPERATIONAL — a terminal
    state — and a WarrantyPolicy is minted for it with coverage_start set to the
    grant time and coverage_years of 25."

    Design: Difficulty/transitive_cascade/grant_pto_depth3_app_project_warranty
    """
    ctx = setup_pto_pending_with_approved_app()
    resp = api.grant_pto(ctx["app"]["id"], ctx["util_headers"])
    data = validate_success(resp, 200)
    assert data["status"] == "PTO_GRANTED"
    proj = get_success_data(api.get_project(ctx["project"]["id"], ctx["ho_headers"]))
    assert proj["status"] == "OPERATIONAL"


def test_grant_pto_mints_warranty_policy_with_25_years(api):
    """PRD 3.6: "the project transitions to OPERATIONAL — a terminal state — and a
    WarrantyPolicy is minted for it with coverage_start set to the grant time and
    coverage_years of 25."

    Design: Difficulty/transitive_cascade/grant_pto_depth3_app_project_warranty
    """
    ctx = setup_pto_pending_with_approved_app()
    get_success_data(api.grant_pto(ctx["app"]["id"], ctx["util_headers"]))
    resp = api.list_warranty_policies(ctx["ho_headers"],
                                      params={"project_id": ctx["project"]["id"]})
    from test_helpers import validate_paginated
    data, meta = validate_paginated(resp)
    matching = [p for p in data if p["project_id"] == ctx["project"]["id"]]
    assert len(matching) == 1
    assert matching[0]["coverage_years"] == 25
