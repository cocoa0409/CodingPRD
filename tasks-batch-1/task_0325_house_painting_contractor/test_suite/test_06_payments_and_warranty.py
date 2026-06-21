"""Payments, dual-variant totals/warranty payouts, walkthrough->completion
cascade, warranty window boundary, and a payment validation-priority pair.

Covers the frozen-estimate vs EXECUTED-only final total divergence, the provisional
vs final warranty payout divergence, the walkthrough-pass completion cascade and
warranty-expiry stamping, the inclusive warranty-window boundary, final-payment
state precedence over amount mismatch, deposit amount equality, the COMPLETED
precondition for warranty filing, and product/surface-kind compatibility.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_product, create_project, add_surface,
    setup_estimated_project, setup_completed_project, setup_walkthrough_pending_project,
    propose_and_approve_color, create_crew, schedule_crew, pay_deposit, pay_final,
    create_submitted_change_order, pin_clock,
    TEST_DEFAULTS, TEST_USERS,
)

EST = TEST_USERS["estimator_headers"]
PM = TEST_USERS["project_manager_headers"]
CUST = TEST_USERS["customer_headers"]
CREW = TEST_USERS["crew_member_headers"]

S1_DEPOSIT = TEST_DEFAULTS["S1_DEPOSIT_30PCT_CENTS"]          # 2674
S1_BALANCE_AFTER_DEPOSIT = TEST_DEFAULTS["S1_BALANCE_AFTER_DEPOSIT_CENTS"]  # 6239
S1_S2_DEPOSIT = TEST_DEFAULTS["S1_S2_DEPOSIT_30PCT_CENTS"]    # 6330


def _two_surface_overrides():
    return [
        {"label": "Bedroom", "area_sqft": 120, "coats": 1, "prep_level": "LIGHT"},
        {"label": "Hall", "area_sqft": 100, "coats": 2, "prep_level": "LIGHT"},
    ]


# ─── dual_variant_calc: project estimate vs final diverge (removed surface)

def test_final_total_diverges_from_frozen_estimate_after_removal(api):
    """PRD §3.7: "It computes `final_total_cents` as the sum, over the line items whose
    surface is `EXECUTED`, of each such line item's material plus labor cost (summing the
    per-line-item whole-cent figures). This final total diverges from the frozen
    `estimate_total_cents` whenever an approved change order added, removed, or revised
    scope after finalization."

    Design: Difficulty/dual_variant_calc/project_estimate_vs_final_total_diverge_on_removed_surface
    """
    product, project, surfaces = setup_estimated_project(
        project_overrides={"deposit_pct": 30, "warranty_months": 12},
        surfaces=_two_surface_overrides(),
    )
    s2 = surfaces[1]
    # Approved REMOVE_SURFACE drops S2 after finalize (frozen estimate stays 21101).
    co = create_submitted_change_order(
        project["id"], project["version"], "REMOVE_SURFACE",
        reason="drop hall", target_surface_id=s2["id"])
    validate_success(api.approve_change_order(co["id"], CUST), 200)

    propose_and_approve_color(surfaces[0]["id"])
    crew = create_crew()
    asg = schedule_crew(project["id"], crew["id"], "2026-03-02", "2026-03-03")
    pay_deposit(project["id"], S1_S2_DEPOSIT)  # deposit based on FROZEN 21101 -> 6330
    validate_success(api.schedule_project(project["id"], PM), 200)
    validate_success(api.start_work(project["id"], PM), 200)
    validate_success(api.begin_crew_assignment(asg["id"], CREW), 200)
    validate_success(api.complete_crew_assignment(asg["id"], CREW), 200)
    validate_success(api.request_walkthrough(project["id"], PM), 200)
    wts, _ = _list(api.list_walkthroughs(PM, params={"project_id": project["id"]}))
    # revised_total after removing S2 = 8913; balance = 8913 - 6330 = 2583.
    pay_final(project["id"], 2583)
    pin_clock("2026-04-01T09:00:00Z")
    validate_success(api.pass_walkthrough(wts[0]["id"], CUST), 200)

    completed = validate_success(api.get_project(project["id"], PM), 200)
    assert completed["workflow_status"] == "COMPLETED"
    assert completed["estimate_total_cents"] == 21101  # frozen
    assert completed["final_total_cents"] == 8913       # EXECUTED only
    assert completed["final_total_cents"] != completed["estimate_total_cents"]


def test_frozen_estimate_unchanged_through_completion(api):
    """PRD §3.3: "These three figures form the contractual estimate and are **never
    recomputed afterward** — later change orders do not move them."

    Design: Difficulty/dual_variant_calc/project_estimate_vs_final_total_diverge_on_removed_surface
    """
    product, project, surfaces = setup_estimated_project(
        project_overrides={"deposit_pct": 30, "warranty_months": 12},
        surfaces=_two_surface_overrides(),
    )
    assert project["estimate_total_cents"] == 21101
    co = create_submitted_change_order(
        project["id"], project["version"], "REMOVE_SURFACE",
        reason="drop hall", target_surface_id=surfaces[1]["id"])
    validate_success(api.approve_change_order(co["id"], CUST), 200)
    after = validate_success(api.get_project(project["id"], PM), 200)
    assert after["estimate_total_cents"] == 21101    # frozen
    assert after["revised_total_cents"] == 8913       # live, dropped S2


# ─── dual_variant_calc: warranty provisional vs final payout ──────────────

def test_warranty_provisional_payout_at_filing(api):
    """PRD §3.11: "The `provisional_payout_cents` is the target surface's line-item labor
    cost multiplied by a touch-up labor fraction of 0.20 (twenty percent), rounded half-up
    to whole cents."

    Design: Difficulty/dual_variant_calc/warranty_provisional_vs_final_payout_diverge
    """
    bundle = setup_completed_project(
        S1_DEPOSIT, S1_BALANCE_AFTER_DEPOSIT,
        project_overrides={"deposit_pct": 30, "warranty_months": 12})
    project = bundle["project"]
    surface = bundle["surfaces"][0]
    res = api.create_warranty_claim(
        {
            "project_id": project["id"],
            "surface_id": surface["id"],
            "description": "peeling near trim",
            "filed_at": "2026-05-01T00:00:00.000Z",
        },
        CUST,
    )
    claim = validate_success(res, 201)
    # 0.20 * 4913 = 982.6 -> round_half_up -> 983.
    assert claim["provisional_payout_cents"] == 983


def test_warranty_final_payout_diverges_from_provisional(api):
    """PRD §3.11: "`final_payout_cents` is the logged touch-up hours multiplied by the
    labor rate of 6550 cents per hour, rounded half-up to whole cents, and the claim moves
    to `RESOLVED`. The final payout is derived from the actual logged hours and therefore
    diverges from the provisional twenty-percent estimate whenever real rework differs from
    the estimate."

    Design: Difficulty/dual_variant_calc/warranty_provisional_vs_final_payout_diverge
    """
    bundle = setup_completed_project(
        S1_DEPOSIT, S1_BALANCE_AFTER_DEPOSIT,
        project_overrides={"deposit_pct": 30, "warranty_months": 12})
    project = bundle["project"]
    surface = bundle["surfaces"][0]
    claim = validate_success(api.create_warranty_claim(
        {
            "project_id": project["id"],
            "surface_id": surface["id"],
            "description": "peeling near trim",
            "filed_at": "2026-05-01T00:00:00.000Z",
        }, CUST), 201)
    validate_success(api.approve_warranty_claim(claim["id"], PM), 200)
    resolved = validate_success(
        api.resolve_warranty_claim(claim["id"], {"logged_touchup_hours": 3.0}, PM), 200)
    # 3.0 * 6550 = 19650.
    assert resolved["final_payout_cents"] == 19650
    assert resolved["provisional_payout_cents"] == 983
    assert resolved["final_payout_cents"] != resolved["provisional_payout_cents"]


# ─── transitive_cascade: walkthrough pass -> COMPLETED -> warranty_expires ─

def test_walkthrough_pass_cascades_to_completed(api):
    """PRD §3.7: "if the project's `payment_status` is already `PAID_IN_FULL`, passing
    cascades the project to `COMPLETED`..."

    Design: Difficulty/transitive_cascade/walkthrough_pass_cascade_depth2_to_completed_warranty
    """
    bundle = setup_walkthrough_pending_project(
        S1_DEPOSIT, project_overrides={"deposit_pct": 30, "warranty_months": 12})
    project = bundle["project"]
    pay_final(project["id"], S1_BALANCE_AFTER_DEPOSIT)
    pin_clock("2026-04-01T09:00:00Z")
    validate_success(api.pass_walkthrough(bundle["walkthrough"]["id"], CUST), 200)
    completed = validate_success(api.get_project(project["id"], PM), 200)
    assert completed["workflow_status"] == "COMPLETED"


def test_completion_sets_warranty_expiry(api):
    """PRD §3.7: "The transition also sets `warranty_expires_at` to the completion
    timestamp plus the project's `warranty_months` months, and advances `workflow_status`
    to `COMPLETED`."

    Design: Difficulty/transitive_cascade/walkthrough_pass_cascade_depth2_to_completed_warranty
    """
    bundle = setup_walkthrough_pending_project(
        S1_DEPOSIT, project_overrides={"deposit_pct": 30, "warranty_months": 12})
    project = bundle["project"]
    pay_final(project["id"], S1_BALANCE_AFTER_DEPOSIT)
    pin_clock("2026-04-01T09:00:00Z")
    passed = validate_success(api.pass_walkthrough(bundle["walkthrough"]["id"], CUST), 200)
    assert passed["status"] == "PASSED"
    completed = validate_success(api.get_project(project["id"], PM), 200)
    # completion 2026-04-01T09:00:00Z + 12 months -> 2027-04-01T09:00:00.000Z.
    assert completed["warranty_expires_at"] == "2027-04-01T09:00:00.000Z"


# ─── boundary_precision_check: warranty window inclusive at exact expiry ──

def test_warranty_claim_at_exact_expiry_accepted(api):
    """PRD §3.11: "The expiry is inclusive — a claim filed at the exact expiry instant is
    accepted, while one filed even a millisecond later is rejected."

    Design: Difficulty/boundary_precision_check/warranty_window_inclusive_at_exact_expiry
    """
    bundle = setup_completed_project(
        S1_DEPOSIT, S1_BALANCE_AFTER_DEPOSIT,
        project_overrides={"deposit_pct": 30, "warranty_months": 12})
    project = bundle["project"]
    surface = bundle["surfaces"][0]
    # warranty_expires_at == 2027-04-01T09:00:00.000Z (completion + 12 months).
    res = api.create_warranty_claim(
        {
            "project_id": project["id"],
            "surface_id": surface["id"],
            "description": "edge case at exact expiry",
            "filed_at": "2027-04-01T09:00:00.000Z",
        },
        CUST,
    )
    claim = validate_success(res, 201)
    assert claim["status"] == "FILED"


def test_warranty_claim_one_ms_past_expiry_rejected(api):
    """PRD §3.11: "then `filed_at` must be no later than the project's
    `warranty_expires_at` (otherwise `ERR_WARRANTY_EXPIRED`, HTTP 409). The expiry is
    inclusive — a claim filed at the exact expiry instant is accepted, while one filed even
    a millisecond later is rejected."

    Design: Difficulty/boundary_precision_check/warranty_window_inclusive_at_exact_expiry
    """
    bundle = setup_completed_project(
        S1_DEPOSIT, S1_BALANCE_AFTER_DEPOSIT,
        project_overrides={"deposit_pct": 30, "warranty_months": 12})
    project = bundle["project"]
    surface = bundle["surfaces"][0]
    res = api.create_warranty_claim(
        {
            "project_id": project["id"],
            "surface_id": surface["id"],
            "description": "one ms past expiry",
            "filed_at": "2027-04-01T09:00:00.001Z",
        },
        CUST,
    )
    validate_error(res, "ERR_WARRANTY_EXPIRED", expected_status=409)


# ─── priority pair: final-payment state (prio5) beats fiscal (prio12) ─────

def test_final_payment_state_error_beats_amount_mismatch(api):
    """PRD §3.8: "A **final** payment carries `kind` `FINAL` and drives the axis from
    `DEPOSIT_PAID` to `PAID_IN_FULL`. It is allowed only when `payment_status` is
    `DEPOSIT_PAID` (otherwise `ERR_FINAL_BEFORE_DEPOSIT`) and the project's
    `workflow_status` is `WALKTHROUGH_PENDING` (otherwise `ERR_PROJECT_NOT_IN_WALKTHROUGH`),
    and the amount tendered must equal the current `balance_due_cents` exactly (otherwise
    `ERR_FINAL_AMOUNT_MISMATCH`, HTTP 402)."
    PRD §3.12: "(5) state correctness for the requested transition (the relevant state
    code, 409); ... The domain checks that follow — ... payment-amount equality, ... — run
    after these foundational gates..."

    Design: Difficulty/priority_pair_validation_conflict/final_payment_state_beats_fiscal_mismatch
    """
    product, project, surfaces = setup_estimated_project(
        project_overrides={"deposit_pct": 30}, surfaces=_two_surface_overrides())
    pay_deposit(project["id"], S1_S2_DEPOSIT)  # now DEPOSIT_PAID, still ESTIMATED workflow
    # FINAL while workflow is ESTIMATED (not WALKTHROUGH_PENDING) AND wrong amount.
    res = api.create_payment(
        {"project_id": project["id"], "kind": "FINAL", "amount_cents": 99999}, CUST)
    validate_error(res, "ERR_PROJECT_NOT_IN_WALKTHROUGH", expected_status=409)


def test_final_payment_wrong_state_reports_state_even_with_correct_amount(api):
    """PRD §3.8: "It is allowed only when `payment_status` is `DEPOSIT_PAID` (otherwise
    `ERR_FINAL_BEFORE_DEPOSIT`) and the project's `workflow_status` is `WALKTHROUGH_PENDING`
    (otherwise `ERR_PROJECT_NOT_IN_WALKTHROUGH`), and the amount tendered must equal the
    current `balance_due_cents` exactly (otherwise `ERR_FINAL_AMOUNT_MISMATCH`, HTTP 402)."
    PRD §3.12: "(5) state correctness for the requested transition (the relevant state
    code, 409); ... The domain checks that follow — ... payment-amount equality, ... — run
    after these foundational gates..."

    Design: Difficulty/priority_pair_validation_conflict/final_payment_state_beats_fiscal_mismatch
    """
    product, project, surfaces = setup_estimated_project(
        project_overrides={"deposit_pct": 30}, surfaces=_two_surface_overrides())
    pay_deposit(project["id"], S1_S2_DEPOSIT)  # DEPOSIT_PAID, still ESTIMATED workflow
    fresh = validate_success(api.get_project(project["id"], PM), 200)
    correct_balance = fresh["balance_due_cents"]
    # FINAL with the exactly-correct balance amount, but the workflow is still ESTIMATED.
    # The state gate (prio 5) fires before the fiscal amount check (prio 12), so even a
    # perfectly correct amount surfaces ERR_PROJECT_NOT_IN_WALKTHROUGH, never a 402.
    res = api.create_payment(
        {"project_id": project["id"], "kind": "FINAL", "amount_cents": correct_balance}, CUST)
    validate_error(res, "ERR_PROJECT_NOT_IN_WALKTHROUGH", expected_status=409)


# ─── corner: deposit amount mismatch ──────────────────────────────────────

def test_deposit_amount_mismatch_rejected(api):
    """PRD §3.8: "the amount tendered must equal `deposit_due_cents` exactly (otherwise
    `ERR_DEPOSIT_AMOUNT_MISMATCH`, HTTP 402)."

    Design: Corner/validations/deposit_amount_mismatch_rejected
    """
    _, project, _ = setup_estimated_project(project_overrides={"deposit_pct": 30})
    assert project["deposit_due_cents"] == S1_DEPOSIT  # 2674
    res = api.create_payment(
        {"project_id": project["id"], "kind": "DEPOSIT", "amount_cents": 2000}, CUST)
    validate_error(res, "ERR_DEPOSIT_AMOUNT_MISMATCH", expected_status=402)


# ─── corner: warranty claim before COMPLETED ──────────────────────────────

def test_warranty_claim_before_completed_rejected(api):
    """PRD §3.11: "first, the parent project must be `COMPLETED` (otherwise
    `ERR_PROJECT_NOT_COMPLETED`, HTTP 409, checked before the window check)..."

    Design: Corner/errors/warranty_claim_before_completed_rejected
    """
    _, project, surfaces = setup_estimated_project()
    res = api.create_warranty_claim(
        {
            "project_id": project["id"],
            "surface_id": surfaces[0]["id"],
            "description": "too early",
            "filed_at": "2026-05-01T00:00:00.000Z",
        },
        CUST,
    )
    validate_error(res, "ERR_PROJECT_NOT_COMPLETED", expected_status=409)


# ─── corner: surface product/surface-kind mismatch ────────────────────────

def test_surface_product_kind_mismatch_rejected(api):
    """PRD §3.2: "an `INTERIOR` product may be used only on an `INTERIOR` surface, and an
    `EXTERIOR` product only on an `EXTERIOR` surface ... both reported with
    `ERR_PRODUCT_SURFACE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/surface_product_surface_kind_mismatch_rejected
    """
    product = create_product(name="Interior Only", surface_kind="INTERIOR", finish_type="EGGSHELL")
    project = create_project(scope="BOTH")
    res = api.create_surface(
        {
            "project_id": project["id"],
            "label": "North Wall",
            "surface_kind": "EXTERIOR",
            "area_sqft": 400,
            "coats": 2,
            "prep_level": "STANDARD",
            "paint_product_id": product["id"],
        },
        EST,
    )
    validate_error(res, "ERR_PRODUCT_SURFACE_MISMATCH", expected_status=422)


# ─── helper ───────────────────────────────────────────────────────────────

def _list(response):
    body = response.json()
    return body.get("data", []), body
