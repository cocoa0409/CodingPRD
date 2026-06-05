"""PDGM payment calculations — provisional vs final settlement, mileage tiers,
companion offset (PRD §3.3, §3.6, §3.8). Queue A difficulty instances plus their
≥2-test depth coverage.
"""
import pytest

from test_helpers import api_client, validate_success
from test_helpers.fixtures import (
    BILLING,
    INTAKE,
    SCHEDULER,
    book_companion_shift,
    deliver_companion_shift,
    file_mileage_claim,
    schedule_confirm_complete,
    setup_active_episode,
    set_clock,
)
from test_helpers.test_users import make_clinician_headers

WOUND_RATE = {
    "clinical_group": "WOUND", "base_30day_rate": 2000.00,
    "functional_weight_low": 0.95, "functional_weight_medium": 1.00,
    "functional_weight_high": 1.05, "lupa_threshold": 5,
}
WOUND_OASIS = {"clinical_group": "WOUND", "functional_level": "HIGH", "comorbidity_count": 2}

MMTA_RATE = {
    "clinical_group": "MMTA_OTHER", "base_30day_rate": 1500.00,
    "functional_weight_low": 1.00, "functional_weight_medium": 1.00,
    "functional_weight_high": 1.00, "lupa_threshold": 1,
}
MMTA_OASIS = {"clinical_group": "MMTA_OTHER", "functional_level": "LOW", "comorbidity_count": 0}


def _confirm(visit_id, rn_id):
    return validate_success(api_client.confirm_visit(visit_id, make_clinician_headers(rn_id)))


def _complete(visit_id, rn_id):
    return validate_success(api_client.complete_visit(visit_id, make_clinician_headers(rn_id)))


# ===========================================================================
# Difficulty: provisional_vs_final_pdgm_diverge_on_episode (≥2 tests)
# ===========================================================================
def test_provisional_full_pdgm_vs_final_lupa_diverge(api):
    """PRD §3.8: "if the completed-visit count is strictly less than the
    episode's lupa_threshold, the payment basis is LUPA_PER_VISIT and the gross
    PDGM amount is $165.00 per completed visit, rounded half-up to two decimal
    places; otherwise the payment basis is FULL_PDGM and the gross PDGM amount is
    the case-mix amount multiplied by 2, rounded half-up to two decimal places."
    PRD §3.3: "if the planned total is greater than or equal to the episode's
    lupa_threshold, the provisional payment is the case-mix amount multiplied by
    2 (the episode spans two 30-day periods), rounded half-up to two decimal
    places".

    Design: Difficulty/dual_variant_calc/provisional_vs_final_pdgm_diverge_on_episode
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    assert base["episode"]["provisional_payment"] == 4452.00

    # schedule 3 visits, confirm, complete; advance clock past windows
    v_ids = []
    for d in ("03", "04", "05"):
        v = validate_success(api.create_visit(ep_id, {
            "clinician_id": rn_id, "discipline": "RN",
            "scheduled_start": f"2026-02-{d}T09:00:00Z",
            "scheduled_end": f"2026-02-{d}T10:00:00Z",
        }, SCHEDULER), 201)
        v_ids.append(v["id"])
    for vid in v_ids:
        _confirm(vid, rn_id)
    set_clock("2026-02-06T08:00:00Z", api)
    for vid in v_ids:
        _complete(vid, rn_id)

    fin = validate_success(api.finalize_episode(ep_id, BILLING))
    assert fin["provisional_payment"] == 4452.00
    assert fin["final_payment"] == 495.00  # 3 < 5 -> LUPA 165*3
    assert fin["status"] == "DISCHARGED"


def test_final_full_pdgm_when_completed_meets_threshold(api):
    """PRD §3.8: "otherwise the payment basis is FULL_PDGM and the gross PDGM
    amount is the case-mix amount multiplied by 2, rounded half-up to two decimal
    places." (5 completed >= threshold 5 -> FULL PDGM, matching the provisional.)

    Design: Difficulty/dual_variant_calc/provisional_vs_final_pdgm_diverge_on_episode
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 5},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    v_ids = []
    for d in ("03", "04", "05", "06", "07"):
        v = validate_success(api.create_visit(ep_id, {
            "clinician_id": rn_id, "discipline": "RN",
            "scheduled_start": f"2026-02-{d}T09:00:00Z",
            "scheduled_end": f"2026-02-{d}T10:00:00Z",
        }, SCHEDULER), 201)
        v_ids.append(v["id"])
    for vid in v_ids:
        _confirm(vid, rn_id)
    set_clock("2026-02-08T08:00:00Z", api)
    for vid in v_ids:
        _complete(vid, rn_id)
    fin = validate_success(api.finalize_episode(ep_id, BILLING))
    assert fin["final_payment"] == 4452.00


# ===========================================================================
# Difficulty: mileage_reimbursement_vs_companion_offset_distinct_domains (≥2)
# ===========================================================================
def test_mileage_reimbursement_and_companion_hours_distinct(api):
    """PRD §3.6: "The reimbursement is the first-tier miles times $0.67 plus the
    second-tier miles times $0.50, rounded half-up to two decimal places. The
    approved reimbursement is then added to the episode's running
    total_mileage_reimbursed".
    PRD §3.5: "On success the shift's hours are added to the episode's running
    companion_hours_used".

    Design: Difficulty/dual_variant_calc/mileage_reimbursement_vs_companion_offset_distinct_domains
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 1, "companion_hours_authorized": 2},
        with_hha=True,
    )
    ep_id, rn_id, hha_id = base["episode"]["id"], base["rn"]["id"], base["hha"]["id"]

    visit = schedule_confirm_complete(ep_id, rn_id, "2026-02-03T11:00:00Z", api)
    claim = file_mileage_claim(visit["id"], rn_id, api, claimed_miles=20.0)
    cs1 = book_companion_shift(ep_id, hha_id, api,
                              shift_start="2026-02-03T13:00:00Z", shift_end="2026-02-03T13:30:00Z")
    cs2 = book_companion_shift(ep_id, hha_id, api,
                              shift_start="2026-02-03T14:00:00Z", shift_end="2026-02-03T14:30:00Z")
    set_clock("2026-02-03T15:00:00Z", api)
    deliver_companion_shift(cs1["id"], api)
    deliver_companion_shift(cs2["id"], api)

    approved = validate_success(api.approve_mileage_claim(claim["id"], BILLING))
    assert approved["reimbursement"] == 10.05
    assert approved["status"] == "APPROVED"
    ep = validate_success(api.get_episode(ep_id, INTAKE))
    assert ep["total_mileage_reimbursed"] == 10.05
    assert ep["companion_hours_used"] == 1.0


def test_companion_hours_accrue_independently_of_mileage(api):
    """PRD §3.5: "On success the shift's hours are added to the episode's running
    companion_hours_used, and the shift version is bumped." (Two 0.5h shifts
    accrue 1.0 hour regardless of any mileage activity.)

    Design: Difficulty/dual_variant_calc/mileage_reimbursement_vs_companion_offset_distinct_domains
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 1, "companion_hours_authorized": 2},
        with_hha=True,
    )
    ep_id, hha_id = base["episode"]["id"], base["hha"]["id"]
    cs1 = book_companion_shift(ep_id, hha_id, api,
                              shift_start="2026-02-03T13:00:00Z", shift_end="2026-02-03T13:30:00Z")
    set_clock("2026-02-03T15:00:00Z", api)
    deliver_companion_shift(cs1["id"], api)
    ep = validate_success(api.get_episode(ep_id, INTAKE))
    assert ep["companion_hours_used"] == 0.5
    assert ep["total_mileage_reimbursed"] == 0


# ===========================================================================
# Difficulty: mileage_tiered_min_cap_free_tier_mode_a (≥2)
# ===========================================================================
def test_mileage_tiered_free_tier_and_tier1(api):
    """PRD §3.6: "From the capped figure, the first 5.0 miles are a free tier
    that earns nothing, so the billable distance is the capped figure minus 5.0,
    floored at zero; this billable distance is recorded as reimbursable_miles.
    The billable distance is then priced on two marginal tiers: the first 20.0
    billable miles earn $0.67 per mile, and any billable miles beyond 20.0 earn
    $0.50 per mile."

    Design: Difficulty/combinatorial_formula/mileage_tiered_min_cap_free_tier_mode_a
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 1},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    visit = schedule_confirm_complete(ep_id, rn_id, "2026-02-03T11:00:00Z", api)
    claim = file_mileage_claim(visit["id"], rn_id, api, claimed_miles=20.0)
    approved = validate_success(api.approve_mileage_claim(claim["id"], BILLING))
    assert approved["reimbursable_miles"] == 15.0  # 20 - 5 free tier
    assert approved["reimbursement"] == 10.05  # 15 * 0.67


def test_mileage_cap_uses_min_of_claimed_and_computed(api):
    """PRD §3.6: "The capped figure is the smaller of claimed_miles and
    computed_miles multiplied by 1.10 (the latter product rounded half-up to two
    decimal places)." (A 27-mile claim against a ~21.16 computed trip is capped
    out by the overclaim ceiling and rejected; see overclaim test — here we assert
    the in-bounds claim is priced from the claimed figure when below the cap.)

    Design: Difficulty/combinatorial_formula/mileage_tiered_min_cap_free_tier_mode_a
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 1},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    visit = schedule_confirm_complete(ep_id, rn_id, "2026-02-03T11:00:00Z", api)
    # claimed 10 < computed*1.10 -> capped figure is 10, billable = 10-5 = 5
    claim = file_mileage_claim(visit["id"], rn_id, api, claimed_miles=10.0)
    approved = validate_success(api.approve_mileage_claim(claim["id"], BILLING))
    assert approved["reimbursable_miles"] == 5.0
    assert approved["reimbursement"] == 3.35  # 5 * 0.67


# ===========================================================================
# Difficulty: companion_offset_round_per_shift_then_sum_mode_b (≥2)
# ===========================================================================
def test_companion_offset_rounds_per_shift_then_sums(api):
    """PRD §3.8: "For each DELIVERED companion shift on the episode, that shift's
    cost is its hours multiplied by the companion hourly rate of $24.05, rounded
    half-up to two decimal places per shift; the companion_offset is the sum of
    those per-shift rounded costs".

    Design: Difficulty/combinatorial_formula/companion_offset_round_per_shift_then_sum_mode_b
    """
    base = setup_active_episode(
        api, rate_overrides=MMTA_RATE, oasis_overrides=MMTA_OASIS,
        plan_overrides={"planned_rn_visits": 1, "companion_hours_authorized": 2},
        with_hha=True,
    )
    ep_id, rn_id, hha_id = base["episode"]["id"], base["rn"]["id"], base["hha"]["id"]
    schedule_confirm_complete(ep_id, rn_id, "2026-02-03T11:00:00Z", api)
    cs1 = book_companion_shift(ep_id, hha_id, api,
                              shift_start="2026-02-03T13:00:00Z", shift_end="2026-02-03T13:30:00Z")
    cs2 = book_companion_shift(ep_id, hha_id, api,
                              shift_start="2026-02-03T14:00:00Z", shift_end="2026-02-03T14:30:00Z")
    set_clock("2026-02-03T15:00:00Z", api)
    deliver_companion_shift(cs1["id"], api)
    deliver_companion_shift(cs2["id"], api)
    fin = validate_success(api.finalize_episode(ep_id, BILLING))
    # per-shift: round(0.5*24.05,2)=12.03 each -> 24.06; gross FULL PDGM 3000.00
    assert fin["final_payment"] == 3024.06
    rows, _ = _ledger(api, ep_id)
    assert rows[0]["companion_offset"] == 24.06


def test_single_companion_shift_offset(api):
    """PRD §3.8: "that shift's cost is its hours multiplied by the companion
    hourly rate of $24.05, rounded half-up to two decimal places per shift".
    (One 0.5h shift -> 12.03 offset.)

    Design: Difficulty/combinatorial_formula/companion_offset_round_per_shift_then_sum_mode_b
    """
    base = setup_active_episode(
        api, rate_overrides=MMTA_RATE, oasis_overrides=MMTA_OASIS,
        plan_overrides={"planned_rn_visits": 1, "companion_hours_authorized": 2},
        with_hha=True,
    )
    ep_id, rn_id, hha_id = base["episode"]["id"], base["rn"]["id"], base["hha"]["id"]
    schedule_confirm_complete(ep_id, rn_id, "2026-02-03T11:00:00Z", api)
    cs1 = book_companion_shift(ep_id, hha_id, api,
                              shift_start="2026-02-03T13:00:00Z", shift_end="2026-02-03T13:30:00Z")
    set_clock("2026-02-03T15:00:00Z", api)
    deliver_companion_shift(cs1["id"], api)
    fin = validate_success(api.finalize_episode(ep_id, BILLING))
    rows, _ = _ledger(api, ep_id)
    assert rows[0]["companion_offset"] == 12.03
    assert fin["final_payment"] == 3012.03


# ===========================================================================
# Difficulty: lupa_threshold_exact_boundary_full_pdgm (≥2)
# ===========================================================================
def test_lupa_boundary_exact_threshold_pays_full(api):
    """PRD §3.8: "if the completed-visit count is strictly less than the
    episode's lupa_threshold, the payment basis is LUPA_PER_VISIT ... otherwise
    the payment basis is FULL_PDGM and the gross PDGM amount is the case-mix
    amount multiplied by 2". (n == threshold == 5 is NOT strictly less, so FULL.)

    Design: Difficulty/boundary_precision_check/lupa_threshold_exact_boundary_full_pdgm
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 5},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    v_ids = []
    for d in ("03", "04", "05", "06", "07"):
        v = validate_success(api.create_visit(ep_id, {
            "clinician_id": rn_id, "discipline": "RN",
            "scheduled_start": f"2026-02-{d}T09:00:00Z",
            "scheduled_end": f"2026-02-{d}T10:00:00Z",
        }, SCHEDULER), 201)
        v_ids.append(v["id"])
    for vid in v_ids:
        _confirm(vid, rn_id)
    set_clock("2026-02-08T08:00:00Z", api)
    for vid in v_ids:
        _complete(vid, rn_id)
    fin = validate_success(api.finalize_episode(ep_id, BILLING))
    rows, _ = _ledger(api, ep_id)
    assert rows[0]["payment_basis"] == "FULL_PDGM"
    assert fin["final_payment"] == 4452.00


def test_lupa_boundary_below_threshold_pays_per_visit(api):
    """PRD §3.8: "if the completed-visit count is strictly less than the
    episode's lupa_threshold, the payment basis is LUPA_PER_VISIT and the gross
    PDGM amount is $165.00 per completed visit". (4 completed < 5 -> LUPA.)

    Design: Difficulty/boundary_precision_check/lupa_threshold_exact_boundary_full_pdgm
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 5},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    v_ids = []
    for d in ("03", "04", "05", "06"):
        v = validate_success(api.create_visit(ep_id, {
            "clinician_id": rn_id, "discipline": "RN",
            "scheduled_start": f"2026-02-{d}T09:00:00Z",
            "scheduled_end": f"2026-02-{d}T10:00:00Z",
        }, SCHEDULER), 201)
        v_ids.append(v["id"])
    for vid in v_ids:
        _confirm(vid, rn_id)
    set_clock("2026-02-08T08:00:00Z", api)
    for vid in v_ids:
        _complete(vid, rn_id)
    fin = validate_success(api.finalize_episode(ep_id, BILLING))
    rows, _ = _ledger(api, ep_id)
    assert rows[0]["payment_basis"] == "LUPA_PER_VISIT"
    assert fin["final_payment"] == 660.00  # 165 * 4


def _ledger(api, ep_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_payment_ledger(ep_id, BILLING))
