"""Change orders: cyclic revise loop, depth-3 approval cascade, reject invariant,
cross-entity changeable guard, and optimistic concurrency on create.

Covers the reject->revise->draft->submit loop, the approve-time re-pricing cascade
into the live revised total and balance, the frozen estimate/deposit invariants on
approve and reject, the project-changeable submit guard, the OCC stale/fresh
project-version paths, and balance reconciliation after a change order.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_product, create_project, add_surface,
    setup_estimated_project,
    create_change_order, create_submitted_change_order,
    add_surface_co_overrides, pay_deposit,
    TEST_DEFAULTS, TEST_USERS,
)

EST = TEST_USERS["estimator_headers"]
CUST = TEST_USERS["customer_headers"]
PM = TEST_USERS["project_manager_headers"]

S1_DEPOSIT = TEST_DEFAULTS["S1_DEPOSIT_30PCT_CENTS"]  # 2674
S1_TOTAL = TEST_DEFAULTS["S1_TOTAL_CENTS"]            # 8913
S3_DELTA = TEST_DEFAULTS["S3_ADD_DELTA_CENTS"]        # 47300


# ─── non_linear_state_machine: cyclic reject -> revise -> draft -> submit ─

def test_change_order_revise_returns_to_draft_with_zero_delta(api):
    """PRD §3.9: "From `REJECTED`, the estimator may revise the order back to `DRAFT`,
    which requires `REJECTED` status (otherwise `ERR_CHANGE_ORDER_NOT_REJECTED`); revision
    overwrites the order's editable fields ... resets `delta_total_cents` to 0 (it is
    recomputed on the next submit), and returns the order to `DRAFT`."

    Design: Difficulty/non_linear_state_machine/change_order_cyclic_reject_revise_to_draft
    """
    product, project, _ = setup_estimated_project()
    co = create_submitted_change_order(
        project["id"], project["version"], "ADD_SURFACE",
        reason="add study", **add_surface_co_overrides(product["id"]))
    validate_success(api.reject_change_order(co["id"], CUST), 200)
    revised = validate_success(
        api.revise_change_order(co["id"], {"new_area_sqft": 200}, EST), 200)
    assert revised["status"] == "DRAFT"
    assert revised["delta_total_cents"] == 0


def test_change_order_resubmit_after_revise(api):
    """PRD §3.9: "Submitting a draft change order computes its prospective price delta and
    moves it to `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/change_order_cyclic_reject_revise_to_draft
    """
    product, project, _ = setup_estimated_project()
    co = create_submitted_change_order(
        project["id"], project["version"], "ADD_SURFACE",
        reason="add study", **add_surface_co_overrides(product["id"]))
    validate_success(api.reject_change_order(co["id"], CUST), 200)
    validate_success(api.revise_change_order(co["id"], {"new_area_sqft": 200}, EST), 200)
    resubmitted = validate_success(api.submit_change_order(co["id"], EST), 200)
    assert resubmitted["status"] == "SUBMITTED"


# ─── transitive_cascade: approve -> surface -> line item -> revised total ─

def test_approve_add_surface_cascades_to_revised_total(api):
    """PRD §3.9: "an `ADD_SURFACE` creates a new `PLANNED` surface from the new-scope
    fields together with its line item ... The surface and line-item mutation then
    re-derives the live `revised_total_cents` as the sum over all non-`REMOVED` line items
    of each line item's material plus labor cost, and `balance_due_cents` is recomputed
    from the new revised total."

    Design: Difficulty/transitive_cascade/change_order_approve_cascade_depth3_to_project_totals
    """
    product, project, _ = setup_estimated_project(project_overrides={"deposit_pct": 30})
    co = create_submitted_change_order(
        project["id"], project["version"], "ADD_SURFACE",
        reason="add study", **add_surface_co_overrides(product["id"]))
    assert co["delta_total_cents"] == S3_DELTA
    validate_success(api.approve_change_order(co["id"], CUST), 200)
    after = validate_success(api.get_project(project["id"], PM), 200)
    # 8913 + 47300 = 56213
    assert after["revised_total_cents"] == S1_TOTAL + S3_DELTA
    assert after["revised_total_cents"] == 56213


def test_approve_change_order_leaves_frozen_estimate_and_deposit(api):
    """PRD §3.9: "The frozen `estimate_total_cents` and the pinned `deposit_due_cents` are
    deliberately **not** touched."

    Design: Difficulty/transitive_cascade/change_order_approve_cascade_depth3_to_project_totals
    """
    product, project, _ = setup_estimated_project(project_overrides={"deposit_pct": 30})
    co = create_submitted_change_order(
        project["id"], project["version"], "ADD_SURFACE",
        reason="add study", **add_surface_co_overrides(product["id"]))
    validate_success(api.approve_change_order(co["id"], CUST), 200)
    after = validate_success(api.get_project(project["id"], PM), 200)
    assert after["estimate_total_cents"] == S1_TOTAL    # frozen 8913
    assert after["deposit_due_cents"] == S1_DEPOSIT     # frozen 2674


# ─── cross_entity_state_dependency: submit requires project changeable ────

def test_submit_change_order_requires_project_changeable(api):
    """PRD §3.9: "Submission requires the order to be in `DRAFT` (otherwise
    `ERR_CHANGE_ORDER_NOT_DRAFT`) and the parent project's `workflow_status` to be one of
    `ESTIMATED`, `SCHEDULED`, or `IN_PROGRESS` (otherwise `ERR_PROJECT_NOT_CHANGEABLE`)."

    Design: Difficulty/cross_entity_state_dependency/change_order_submit_requires_project_changeable
    """
    product = create_product()
    project = create_project()  # stays DRAFT (never finalized)
    surface = add_surface(project["id"], product["id"])
    fresh = validate_success(api.get_project(project["id"], EST), 200)
    co = create_change_order(
        project["id"], fresh["version"], "REVISE_SURFACE",
        reason="revise area", target_surface_id=surface["id"],
        new_area_sqft=200, new_coats=1, new_prep_level="LIGHT",
        new_paint_product_id=product["id"])
    res = api.submit_change_order(co["id"], EST)
    validate_error(res, "ERR_PROJECT_NOT_CHANGEABLE", expected_status=409)


def test_submit_change_order_on_draft_project_blocked(api):
    """PRD §3.9: "the parent project's `workflow_status` to be one of `ESTIMATED`,
    `SCHEDULED`, or `IN_PROGRESS` (otherwise `ERR_PROJECT_NOT_CHANGEABLE`)."

    Design: Difficulty/cross_entity_state_dependency/change_order_submit_requires_project_changeable
    """
    product = create_product()
    project = create_project()  # DRAFT
    surface = add_surface(project["id"], product["id"])
    fresh = validate_success(api.get_project(project["id"], EST), 200)
    co = create_change_order(
        project["id"], fresh["version"], "REMOVE_SURFACE",
        reason="drop it", target_surface_id=surface["id"])
    res = api.submit_change_order(co["id"], EST)
    validate_error(res, "ERR_PROJECT_NOT_CHANGEABLE", expected_status=409)


# ─── compensating_invariant: reject leaves revised total unchanged ────────

def test_reject_change_order_conserves_revised_total(api):
    """PRD §3.9: "a rejection performs no surface or total mutation, so
    `revised_total_cents` and `estimate_total_cents` are left exactly as they were."

    Design: Difficulty/compensating_invariant/change_order_reject_leaves_estimate_total_unchanged
    """
    product, project, _ = setup_estimated_project()
    before = validate_success(api.get_project(project["id"], PM), 200)
    assert before["revised_total_cents"] == S1_TOTAL
    co = create_submitted_change_order(
        project["id"], project["version"], "ADD_SURFACE",
        reason="add study", **add_surface_co_overrides(product["id"]))
    rejected = validate_success(api.reject_change_order(co["id"], CUST), 200)
    assert rejected["status"] == "REJECTED"
    after = validate_success(api.get_project(project["id"], PM), 200)
    assert after["revised_total_cents"] == S1_TOTAL  # zero drift


def test_reject_change_order_status_and_no_drift(api):
    """PRD §3.9: "A homeowner may reject a submitted order, which requires `SUBMITTED`
    status (otherwise `ERR_CHANGE_ORDER_NOT_SUBMITTED`) and moves it to `REJECTED`;
    crucially, a rejection performs no surface or total mutation..."

    Design: Difficulty/compensating_invariant/change_order_reject_leaves_estimate_total_unchanged
    """
    product, project, _ = setup_estimated_project()
    co = create_submitted_change_order(
        project["id"], project["version"], "ADD_SURFACE",
        reason="add study", **add_surface_co_overrides(product["id"]))
    validate_success(api.reject_change_order(co["id"], CUST), 200)
    after = validate_success(api.get_project(project["id"], PM), 200)
    assert after["estimate_total_cents"] == S1_TOTAL


# ─── corner: OCC stale project version on create ──────────────────────────

def test_occ_stale_project_version_rejected(api):
    """PRD §2.7: "If another change order has since been approved — legitimately
    superseding the prior surface set and advancing the project's `version` — the author's
    view is stale and the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_change_order_create
    """
    product, project, _ = setup_estimated_project(project_overrides={"deposit_pct": 30})
    stale_version = project["version"]
    co1 = create_submitted_change_order(
        project["id"], stale_version, "ADD_SURFACE",
        reason="first", **add_surface_co_overrides(product["id"]))
    validate_success(api.approve_change_order(co1["id"], CUST), 200)
    # Second create still carrying the pre-approval (stale) version.
    res = api.create_change_order(
        {
            "project_id": project["id"],
            "expected_project_version": stale_version,
            "reason": "second on stale view",
            "action": "ADD_SURFACE",
            "new_label": "Den", "new_surface_kind": "INTERIOR",
            "new_area_sqft": 200, "new_coats": 1, "new_prep_level": "LIGHT",
            "new_paint_product_id": product["id"],
        },
        EST,
    )
    validate_error(res, "ERR_STALE_PROJECT_VERSION", expected_status=412)


def test_occ_fresh_project_version_accepted(api):
    """PRD §2.7: "The create-change-order request carries `expected_project_version`, which
    is a non-optional input field, and the server compares it to the target project's
    current `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_change_order_create_succeeds
    """
    product, project, _ = setup_estimated_project(project_overrides={"deposit_pct": 30})
    co1 = create_submitted_change_order(
        project["id"], project["version"], "ADD_SURFACE",
        reason="first", **add_surface_co_overrides(product["id"]))
    validate_success(api.approve_change_order(co1["id"], CUST), 200)
    fresh = validate_success(api.get_project(project["id"], EST), 200)
    res = api.create_change_order(
        {
            "project_id": project["id"],
            "expected_project_version": fresh["version"],
            "reason": "second on fresh view",
            "action": "ADD_SURFACE",
            "new_label": "Den", "new_surface_kind": "INTERIOR",
            "new_area_sqft": 200, "new_coats": 1, "new_prep_level": "LIGHT",
            "new_paint_product_id": product["id"],
        },
        EST,
    )
    co2 = validate_success(res, 201)
    assert co2["status"] == "DRAFT"


# ─── corner: derived balance reconciles after change order ────────────────

def test_balance_due_reconciles_after_approved_change_order(api):
    """PRD §3.8: "Throughout, `deposit_due_cents` is pinned to the frozen estimate while
    `balance_due_cents` tracks the live revised total, so a change order shifts the final
    payment without ever re-opening the deposit."
    PRD §3.3: "The balance, `balance_due_cents`, is set to the live `revised_total_cents`
    minus `amount_paid_cents`..."

    Design: Corner/cross_cutting_complexity_layers/derived_balance_due_reconciles_after_change_order
    """
    product, project, _ = setup_estimated_project(project_overrides={"deposit_pct": 30})
    pay_deposit(project["id"], S1_DEPOSIT)
    # Paying the deposit mutates the project (amount_paid_cents, balance_due_cents,
    # payment_status), so per PRD §2.5 the project's version increments. Re-read the
    # current version before authoring the change order to satisfy the OCC check (§2.7).
    fresh = validate_success(api.get_project(project["id"], EST), 200)
    co = create_submitted_change_order(
        project["id"], fresh["version"], "ADD_SURFACE",
        reason="add study", **add_surface_co_overrides(product["id"]))
    validate_success(api.approve_change_order(co["id"], CUST), 200)
    after = validate_success(api.get_project(project["id"], EST), 200)
    assert after["revised_total_cents"] == 56213
    # balance = revised_total 56213 - amount_paid 2674 = 53539
    assert after["balance_due_cents"] == 53539
    assert after["deposit_due_cents"] == S1_DEPOSIT  # frozen
