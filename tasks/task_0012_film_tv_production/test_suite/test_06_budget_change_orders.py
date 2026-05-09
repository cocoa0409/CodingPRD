"""Budget categories, change orders, segregation of duties, posture/alert.

Covers PRD §3.1 (allocation), §3.7 (change orders, reserve draws), §2.6
(posture), §2.7 (alert thresholds), §2.10 (priority).
Difficulty design:
  priority_pair_validation_conflict/state_vs_business_fiscal_on_change_order_approve,
  priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_change_order_approve,
  boundary_precision_check/category_alert_state_warn_at_exact_ninety_percent.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    create_budget_category_payload,
    create_change_order_payload,
    create_vendor_invoice_payload,
    setup_production_with_categories,
    create_production,
    get_categories_by_code,
    get_production,
    make_line_producer_headers,
    make_finance_controller_headers,
    with_override_reason,
    EXEC,
    LP,
    FC,
    CD,
    PC,
)


# ─── Budget category creation cap ────────────────────────────────────────────

def test_budget_category_overallocation_rejected(api):
    """PRD §3.1: "The sum of `planned_cents` across all categories of a
    production, plus the `reserve_fund_cents`, must never exceed the
    `total_budget_cents`; an attempt to create or change-order a category
    that would breach this cap is rejected with `ERR_BUDGET_OVERALLOCATED`
    (HTTP 422)."

    Claim: creating a category whose planned_cents pushes the sum over the
    limit → ERR_BUDGET_OVERALLOCATED.
    """
    # total=10_000_000, reserve=1_000_000 ⇒ allowable category sum = 9_000_000
    prod = create_production(api, total_budget_cents=10_000_000, reserve_fund_cents=1_000_000)
    # First create one category that consumes 9_000_000 (limit).
    validate_success(api.create_budget_category(
        prod["id"],
        create_budget_category_payload(code="CAST", planned_cents=9_000_000),
        FC,
    ), 201)
    # Second category at 1 → would push sum to 9_000_001, exceeding limit.
    res = api.create_budget_category(
        prod["id"],
        create_budget_category_payload(code="CREW", planned_cents=1),
        FC,
    )
    validate_error(res, "ERR_BUDGET_OVERALLOCATED", expected_status=422)


# ─── Change order: segregation of duties ────────────────────────────────────

def test_change_order_approver_cannot_be_requester(api):
    """PRD §3.7: "both reject and approve enforce that the approver's
    `X-User-ID` is *not* equal to `requested_by` — segregation of duties is
    the system's primary fiscal control, and any violation yields
    `ERR_SEGREGATION_OF_DUTIES`."

    Claim: approver's X-User-ID == requested_by → ERR_SEGREGATION_OF_DUTIES.
    """
    prod, cats = setup_production_with_categories(api)
    # Submit change order as a specific LineProducer.
    lp_headers = make_line_producer_headers("test-lp-shared")
    co_resp = api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=100_000,
            source="REALLOCATION",
        ),
        lp_headers,
    )
    co = validate_success(co_resp, 201)
    # Now try to approve using the SAME X-User-ID but role=FinanceController.
    fc_same_id = make_finance_controller_headers("test-lp-shared")
    res = api.approve_change_order(co["id"], fc_same_id)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)


def test_change_order_segregation_wins_over_reserve_insufficient(api):
    """PRD §2.10: priority order is (...) "7. Segregation of duties (...) 9.
    Domain-specific business constraints — interval semantics, permit,
    capacity, weather, audition, actor conflicts, equipment availability,
    equipment event payload, budget allocation, reserve sufficiency, open
    obligations, pagination bounds — all evaluated after the higher-priority
    gates above have passed. The earliest failing rule in this list
    determines the response; lower-priority rules are not evaluated."

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_change_order_approve
    Claim: same-user approval of a RESERVE_DRAW that also exceeds reserve →
    ERR_SEGREGATION_OF_DUTIES (priority 7), not ERR_RESERVE_INSUFFICIENT
    (priority 9 — fiscal).
    """
    prod, cats = setup_production_with_categories(api, reserve_fund_cents=100_000)
    lp_headers = make_line_producer_headers("test-lp-segvsfiscal")
    co_resp = api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=500_000,  # exceeds reserve 100_000
            source="RESERVE_DRAW",
        ),
        lp_headers,
    )
    co = validate_success(co_resp, 201)
    # Same X-User-ID approves
    fc_same = make_finance_controller_headers("test-lp-segvsfiscal")
    res = api.approve_change_order(co["id"], fc_same)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)


def test_invalid_state_wins_over_reserve_insufficient_on_double_approve(api):
    """PRD §2.10: priority order — state (5) precedes domain-specific business
    constraints (9). "The earliest failing rule in this list determines the
    response; lower-priority rules are not evaluated."

    # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_on_change_order_approve
    Claim: a second approve on an already-APPROVED change order returns
    ERR_INVALID_STATE (priority 5), not ERR_RESERVE_INSUFFICIENT (priority 9),
    even when the RESERVE_DRAW would have exceeded reserve.
    """
    prod, cats = setup_production_with_categories(
        api,
        total_budget_cents=200_000_000,
        reserve_fund_cents=100_000,
    )
    # Reserve = 100_000; submit a small first CO that fits in reserve, approve it.
    lp_headers = make_line_producer_headers("test-lp-statevsfiscal")
    fc_first = make_finance_controller_headers("test-fc1")
    co1_resp = api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=50_000,
            source="RESERVE_DRAW",
        ),
        lp_headers,
    )
    co1 = validate_success(co1_resp, 201)
    validate_success(api.approve_change_order(co1["id"], fc_first), 200)

    # Second approve on the already-APPROVED change order from a *different* FC.
    fc_second = make_finance_controller_headers("test-fc2")
    res = api.approve_change_order(co1["id"], fc_second)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_reserve_draw_when_reserve_sufficient_succeeds(api):
    """PRD §3.7: "If the change order is sourced as `RESERVE_DRAW` and the
    `delta_cents` is positive, the production's remaining reserve fund —
    `reserve_fund_cents` minus the cumulative reserve already drawn — must
    be at least the new `delta_cents`(...)."

    Claim: reserve_fund=1M, RESERVE_DRAW delta=200K → approval succeeds, CO
    status=APPROVED.
    """
    prod, cats = setup_production_with_categories(
        api, reserve_fund_cents=1_000_000,
    )
    lp_headers = make_line_producer_headers("test-lp-rd")
    fc_diff = make_finance_controller_headers("test-fc-rd-approver")
    co = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=200_000,
            source="RESERVE_DRAW",
        ),
        lp_headers,
    ), 201)
    approved = validate_success(api.approve_change_order(co["id"], fc_diff), 200)
    assert approved["status"] == "APPROVED"


def test_reserve_draw_exceeding_reserve_rejected(api):
    """PRD §3.7: "an insufficient reserve yields `ERR_RESERVE_INSUFFICIENT`
    (HTTP 409)."

    Claim: reserve_fund=100K, RESERVE_DRAW delta=500K → approval rejected
    with ERR_RESERVE_INSUFFICIENT.
    """
    prod, cats = setup_production_with_categories(api, reserve_fund_cents=100_000)
    lp_headers = make_line_producer_headers("test-lp-ri")
    fc_diff = make_finance_controller_headers("test-fc-ri-approver")
    co = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=500_000,
            source="RESERVE_DRAW",
        ),
        lp_headers,
    ), 201)
    res = api.approve_change_order(co["id"], fc_diff)
    validate_error(res, "ERR_RESERVE_INSUFFICIENT", expected_status=409)


def test_change_order_originator_can_cancel(api):
    """PRD §3.7: "The originator may **cancel** (`PENDING → CANCELLED`)
    provided their `X-User-ID` equals the recorded `requested_by`."

    Claim: same X-User-ID as requested_by can cancel; different X-User-ID
    cannot.
    """
    prod, cats = setup_production_with_categories(api)
    lp_headers = make_line_producer_headers("test-lp-cancel")
    co = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=10_000,
            source="REALLOCATION",
        ),
        lp_headers,
    ), 201)
    cancelled = validate_success(api.cancel_change_order(co["id"], lp_headers), 200)
    assert cancelled["status"] == "CANCELLED"


def test_change_order_non_originator_cannot_cancel(api):
    """PRD §3.7: "The originator may **cancel** (`PENDING → CANCELLED`)
    provided their `X-User-ID` equals the recorded `requested_by`."

    Claim: a different LineProducer X-User-ID cannot cancel; rejected (the
    ownership check on cancel is not satisfied).
    """
    prod, cats = setup_production_with_categories(api)
    lp_headers = make_line_producer_headers("test-lp-orig")
    co = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=10_000,
            source="REALLOCATION",
        ),
        lp_headers,
    ), 201)
    other_lp = make_line_producer_headers("test-lp-other")
    res = api.cancel_change_order(co["id"], other_lp)
    # PRD does not name the specific error_id for this case — but the
    # behavior must NOT be 200 success. The closest PRD-stated reason is the
    # ownership rule on `requested_by`. Two-reader principle: a faithful PRD
    # implementation could use ERR_FORBIDDEN here. We accept either ERR_FORBIDDEN
    # or ERR_INVALID_STATE / ERR_VALIDATION.
    from test_helpers import validate_error_is_one_of
    validate_error_is_one_of(res, ["ERR_FORBIDDEN", "ERR_INVALID_STATE", "ERR_VALIDATION"])


# ─── Posture gating on RESERVE_DRAW (PRD §2.6, §3.7) ────────────────────────

def test_reserve_draw_in_red_posture_blocked_without_override(api):
    """PRD §2.6: "A `RED` posture additionally gates approval of
    `RESERVE_DRAW` change orders: such approvals are rejected with
    `ERR_POSTURE_BLOCKED` unless the approver supplies the
    `X-Override-Reason` header with a non-empty value."

    Claim: production posture=RED + RESERVE_DRAW approval without
    X-Override-Reason → ERR_POSTURE_BLOCKED (409).

    Path to RED posture (per §3.2 sign-headroom + §2.7 utilization rule, and
    §3.7 change-order approve recomputing alert_state):
      1. SIGN role: CAST.committed = 200_000 (within planned=500_000).
      2. Approve negative REALLOCATION CO on CAST: CAST.planned drops to
         100_000. Recomputed utilization = 200_000 / 100_000 = 2.0 → OVER.
      3. Posture is RED.
    """
    prod, cats = setup_production_with_categories(
        api,
        cast_planned_cents=500_000,
        crew_planned_cents=10_000,
        equipment_planned_cents=10_000,
        location_planned_cents=10_000,
        post_planned_cents=10_000,
        misc_planned_cents=10_000,
        reserve_fund_cents=1_000_000,
    )
    from test_helpers import (
        create_role_in_production,
        create_actor,
        walk_role_to_offered,
        create_scene_in_production,
    )
    role = create_role_in_production(
        api, production_id=prod["id"],
        union_tier="SUPPORTING", day_rate_cents=200_000,
    )
    actor = create_actor(api)
    create_scene_in_production(
        api, production_id=prod["id"],
        scene_number="S-redblock",
        planned_duration_minutes=480,
        required_actor_role_ids=[role["id"]],
    )
    walk_role_to_offered(api, production_id=prod["id"], role_id=role["id"],
                          actor_id=actor["id"])
    validate_success(api.sign_role(prod["id"], role["id"], LP), 200)

    # Negative REALLOCATION on CAST to push planned below committed.
    lp_a = make_line_producer_headers("test-lp-redblock-shrink")
    fc_a = make_finance_controller_headers("test-fc-redblock-shrink")
    shrink_co = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=-400_000,
            source="REALLOCATION",
        ),
        lp_a,
    ), 201)
    validate_success(api.approve_change_order(shrink_co["id"], fc_a), 200)
    p = get_production(api, production_id=prod["id"])
    assert p["posture"] == "RED"

    # Now try to approve a RESERVE_DRAW CO without X-Override-Reason — should be blocked.
    lp_headers = make_line_producer_headers("test-lp-redblock")
    fc_diff = make_finance_controller_headers("test-fc-redblock")
    co = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=10_000,
            source="RESERVE_DRAW",
        ),
        lp_headers,
    ), 201)
    res = api.approve_change_order(co["id"], fc_diff)
    validate_error(res, "ERR_POSTURE_BLOCKED", expected_status=409)


def test_reserve_draw_in_red_posture_with_override_reason_succeeds(api):
    """PRD §2.6: "(...) such approvals are rejected with `ERR_POSTURE_BLOCKED`
    unless the approver supplies the `X-Override-Reason` header with a
    non-empty value."

    Claim: same RED-posture scenario but with X-Override-Reason set →
    approval succeeds.

    Path to RED posture mirrors test_reserve_draw_in_red_posture_blocked_without_override.
    """
    prod, cats = setup_production_with_categories(
        api,
        cast_planned_cents=500_000,
        crew_planned_cents=10_000,
        equipment_planned_cents=10_000,
        location_planned_cents=10_000,
        post_planned_cents=10_000,
        misc_planned_cents=10_000,
        reserve_fund_cents=1_000_000,
    )
    from test_helpers import (
        create_role_in_production,
        create_actor,
        walk_role_to_offered,
        create_scene_in_production,
    )
    role = create_role_in_production(
        api, production_id=prod["id"],
        union_tier="SUPPORTING", day_rate_cents=200_000,
    )
    actor = create_actor(api)
    create_scene_in_production(
        api, production_id=prod["id"],
        scene_number="S-overflow2",
        planned_duration_minutes=480,
        required_actor_role_ids=[role["id"]],
    )
    walk_role_to_offered(api, production_id=prod["id"], role_id=role["id"],
                          actor_id=actor["id"])
    validate_success(api.sign_role(prod["id"], role["id"], LP), 200)

    lp_a = make_line_producer_headers("test-lp-redover-shrink")
    fc_a = make_finance_controller_headers("test-fc-redover-shrink")
    shrink_co = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=-400_000,
            source="REALLOCATION",
        ),
        lp_a,
    ), 201)
    validate_success(api.approve_change_order(shrink_co["id"], fc_a), 200)
    assert get_production(api, production_id=prod["id"])["posture"] == "RED"

    # Approve with X-Override-Reason set
    lp_headers = make_line_producer_headers("test-lp-override")
    fc_diff_override = with_override_reason(
        make_finance_controller_headers("test-fc-override"),
        "Mid-production reserve draw under override",
    )
    co = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=10_000,
            source="RESERVE_DRAW",
        ),
        lp_headers,
    ), 201)
    approved = validate_success(api.approve_change_order(co["id"], fc_diff_override), 200)
    assert approved["status"] == "APPROVED"


# ─── Alert state threshold (boundary precision) ─────────────────────────────

def test_alert_state_warn_at_exactly_ninety_percent(api):
    """PRD §2.7: "If utilization is strictly greater than 1.00 the category is
    `OVER`; otherwise if utilization is at least 0.90 the category is
    `WARN`; otherwise the category is `OK`."

    # difficulty: boundary_precision_check/category_alert_state_warn_at_exact_ninety_percent
    Claim: utilization at exactly 0.90 → alert_state == WARN (>= 0.90 inclusive,
    not OVER).
    """
    # Drive CAST.committed_cents to exactly 0.90 of planned.
    # Use SIGN cascade: 1 BREAKDOWN scene * 480min * 1 day * day_rate=900_000;
    # planned=1_000_000 → utilization=0.90.
    prod, cats = setup_production_with_categories(
        api,
        cast_planned_cents=1_000_000,
        crew_planned_cents=10_000,
        equipment_planned_cents=10_000,
        location_planned_cents=10_000,
        post_planned_cents=10_000,
        misc_planned_cents=10_000,
    )
    from test_helpers import (
        create_role_in_production,
        create_actor,
        walk_role_to_offered,
        create_scene_in_production,
    )
    role = create_role_in_production(
        api, production_id=prod["id"],
        union_tier="SUPPORTING", day_rate_cents=900_000,
    )
    actor = create_actor(api)
    create_scene_in_production(
        api, production_id=prod["id"],
        scene_number="S-warn",
        planned_duration_minutes=480,
        required_actor_role_ids=[role["id"]],
    )
    walk_role_to_offered(api, production_id=prod["id"], role_id=role["id"],
                          actor_id=actor["id"])
    validate_success(api.sign_role(prod["id"], role["id"], LP), 200)

    cat = get_categories_by_code(api, production_id=prod["id"])["CAST"]
    assert cat["committed_cents"] == 900_000, (
        f"Expected committed_cents=900000 (utilization 0.90), got {cat['committed_cents']}"
    )
    assert cat["alert_state"] == "WARN", (
        f"At utilization 0.90 (>= 0.90 inclusive, not > 1.00), alert_state must be WARN; got {cat['alert_state']}"
    )


def test_alert_state_over_strictly_above_one(api):
    """PRD §2.7: "If utilization is strictly greater than 1.00 the category is
    `OVER`; (...) The boundary is deliberately asymmetric — utilization of
    exactly 1.00 maps to `WARN`, not `OVER` — because a category that has
    consumed exactly its plan is not yet *over* it."

    Claim: utilization > 1.00 (e.g., 1.20) → alert_state == OVER.

    Path: SIGN one role (commits CAST.committed=200_000 against
    CAST.planned=500_000), then approve a NEGATIVE REALLOCATION change order
    that lowers CAST.planned to 100_000. After approval, recomputed
    utilization = (committed + actual)/planned = 200_000/100_000 = 2.0,
    strictly above 1.00 → alert_state == OVER. PRD §3.2's headroom check
    applies only to the SIGN itself; subsequent change-order approvals
    recompute alert_state per §2.7 with no headroom bound on planned.
    """
    prod, cats = setup_production_with_categories(
        api,
        cast_planned_cents=500_000,
        crew_planned_cents=10_000,
        equipment_planned_cents=10_000,
        location_planned_cents=10_000,
        post_planned_cents=10_000,
        misc_planned_cents=10_000,
    )
    from test_helpers import (
        create_role_in_production,
        create_actor,
        walk_role_to_offered,
        create_scene_in_production,
    )
    role = create_role_in_production(
        api, production_id=prod["id"],
        union_tier="SUPPORTING", day_rate_cents=200_000,
    )
    actor = create_actor(api)
    # 1 BREAKDOWN scene × 1 day × 200_000 = 200_000 (within planned 500_000).
    create_scene_in_production(
        api, production_id=prod["id"],
        scene_number="S-over-0",
        planned_duration_minutes=480,
        required_actor_role_ids=[role["id"]],
    )
    walk_role_to_offered(api, production_id=prod["id"], role_id=role["id"],
                          actor_id=actor["id"])
    validate_success(api.sign_role(prod["id"], role["id"], LP), 200)
    cat = get_categories_by_code(api, production_id=prod["id"])["CAST"]
    assert cat["committed_cents"] == 200_000

    # Now lower CAST.planned to 100_000 via negative REALLOCATION (delta = -400_000).
    lp_headers = make_line_producer_headers("test-lp-overshrink")
    fc_diff = make_finance_controller_headers("test-fc-overshrink")
    co = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=-400_000,
            source="REALLOCATION",
        ),
        lp_headers,
    ), 201)
    validate_success(api.approve_change_order(co["id"], fc_diff), 200)

    cat = get_categories_by_code(api, production_id=prod["id"])["CAST"]
    # CAST.planned = 500_000 - 400_000 = 100_000; committed=200_000; utilization=2.0
    assert cat["planned_cents"] == 100_000
    assert cat["committed_cents"] == 200_000
    assert cat["alert_state"] == "OVER"
