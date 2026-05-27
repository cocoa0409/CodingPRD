"""Supplementary second-pass tests for difficulty-index instances that
need their ≥2 coverage filled out. Each test asserts a different facet
of the same PRD claim as its sibling in tests 01–06."""
from test_helpers import (
    ApiErrorId,
    bootstrap_acc_request_on_suspended_property,
    bootstrap_assessment_overdue_by_clock,
    create_community,
    create_reserve_component,
    create_reserve_study,
    get_assessment,
    validate_error,
)
from test_helpers.test_users import make_acc_member_headers


# ─────────────────────────────────────────────────────────────────────────────
# Rule 2 instance 1 — second test
# ─────────────────────────────────────────────────────────────────────────────

def test_reserve_obligation_component_zero_remaining_life_uses_factor_one(api):
    """PRD §3.8: "For each component, it computes the inflation factor as
    one plus `reserve_inflation_bps` divided by 10000, then raised to the
    power of the component's `remaining_life_years`."

    Boundary facet of the three-input non-linear formula: a single
    component with remaining_life_years=0 yields inflation factor =
    1.03^0 = 1.0, so the per-component inflated cost equals replacement
    cost exactly. This isolates the exponent-zero edge of the non-linear
    interaction — a different facet from the three-component sum test.

    Setup: one component cost=800000 remaining=0 useful=20.
    floor(800000 * 1.03^0) = 800000.

    Design: Difficulty/combinatorial_formula/reserve_obligation_three_input_non_linear_component_method
    """
    community = create_community(name="ZeroRemaining")
    create_reserve_component(
        community["id"], label="C0", useful_life_years=20,
        remaining_life_years=0, replacement_cost_cents=800000,
    )
    study = create_reserve_study(
        community["id"], fiscal_year=2026, method="COMPONENT",
        accumulated_funds_cents=400_000,
    )
    assert study["projected_obligation_cents"] == 800000, (
        f"factor 1.03^0=1 means obligation==replacement_cost; expected 800000, "
        f"got {study['projected_obligation_cents']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Rule 2 instance 2 — second test
# ─────────────────────────────────────────────────────────────────────────────

def test_late_fee_per_cycle_floor_then_sum_with_three_cycles(api):
    """PRD §3.3: "For each cycle, the system adds the flat per-cycle charge
    `late_fee_flat_cents` and adds the percentage component computed as
    `principal_cents` multiplied by `late_fee_pct_bps`, divided by 10000,
    rounded down to whole cents per cycle before summing."

    Three-cycle facet of the per-cycle nested-rounding rule (the sibling
    test covers two cycles). principal=33333, grace=15. Advance clock to
    2026-02-16 → elapsed_days = 46, cycles = 1 + floor((46-15)/15)
    = 1 + 2 = 3. Per cycle: 2500 + floor(33333*1000/10000) = 5833.
    Total: 3 * 5833 = 17499.

    Design: Difficulty/combinatorial_formula/late_fee_nested_rounding_per_cycle_floor_then_sum
    """
    _community, _owner, _prop, assessment = bootstrap_assessment_overdue_by_clock(
        community_name="RoundTown3",
        owner_email="rt3@x.com",
        owner_name="RT3",
        unit_label="RT3-1",
        principal_cents=33333,
        due_date="2026-01-01T00:00:00Z",
        advance_to="2026-02-16T00:00:00Z",
        regular_assessment_cents=33333,
    )
    a = get_assessment(assessment["id"])
    assert a["late_fee_cents"] == 17499, (
        f"3 cycles × (2500 + floor(33333*1000/10000)) = 3*5833 = 17499, "
        f"got {a['late_fee_cents']}"
    )
    assert a["status"] == "OVERDUE"


# ─────────────────────────────────────────────────────────────────────────────
# Rule 5 instance 2 — second test (companion facet)
# ─────────────────────────────────────────────────────────────────────────────

def test_acc_reject_on_suspended_property_is_unaffected_by_property_suspended_rule(api):
    """PRD §3.6: "They may approve, but only when the underlying property's
    `compliance_posture` is not `SUSPENDED` — a suspended property's ACC
    approval is refused with `ERR_PROPERTY_SUSPENDED`. A successful approval
    moves the status from `SUBMITTED` to `APPROVED` (terminal) and stamps
    `decided_at` with `current_utc`. They may reject outright, moving the
    status to `REJECTED` (terminal) and stamping `decided_at` with
    `current_utc`."

    Companion facet of the safety-vs-temporal priority test: PRD prose
    scopes the SUSPENDED guard to the APPROVE action only — the REJECT
    action carries no such guard. On a SUSPENDED property, REJECT must
    succeed and move the request to REJECTED — proving the priority-6
    business_safety check is specifically attached to APPROVE, not a
    blanket gate on every ACC transition.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_acc_approve_on_suspended_property_in_window_returns_property_suspended
    """
    _community, _owner, _prop, acc, _lien = (
        bootstrap_acc_request_on_suspended_property(
            community_name="SuspReject", scope="LANDSCAPING",
            description="Plant olive tree",
        )
    )
    # First confirm APPROVE is gated (positive sibling test does this too;
    # we re-anchor here so the docstring-traceability is unambiguous).
    approve_resp = api.approve_acc_request(acc["id"], make_acc_member_headers())
    validate_error(approve_resp, ApiErrorId.ERR_PROPERTY_SUSPENDED)
    # Then verify REJECT is NOT gated by the same SUSPENDED rule.
    reject_resp = api.reject_acc_request(acc["id"], make_acc_member_headers())
    body = reject_resp.json()
    assert reject_resp.status_code == 200, (
        f"REJECT on SUSPENDED property must succeed (PRD §3.6 scopes the "
        f"SUSPENDED guard to APPROVE only), got {reject_resp.status_code} "
        f"with body {body}"
    )
    assert body["data"]["status"] == "REJECTED", (
        f"expected status REJECTED, got {body['data']['status']}"
    )
