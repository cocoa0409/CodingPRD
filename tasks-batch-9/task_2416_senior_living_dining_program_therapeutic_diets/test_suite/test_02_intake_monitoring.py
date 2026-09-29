"""Intake observations: the two weight variants, the risk score and the four-hop cascade."""
import pytest

from test_helpers import (
    CLINICAL_STAFF,
    DIETITIAN,
    api_client,
    approve_diet_order,
    create_community,
    create_diet_order,
    create_resident,
    create_substitution_rule,
    list_rules,
    read_community,
    read_diet_order,
    read_resident,
    record_observation,
    reviews_for,
    set_clock,
    validate_paginated,
    validate_success,
)


def _elmhurst_two_weights():
    """Baseline 78.0 kg, then 80.0 kg and 76.0 kg eighteen days apart."""
    set_clock("2026-08-02T08:00:00Z")
    community = create_community(
        "Brookdale Elmhurst", ["ASSISTED_LIVING", "MEMORY_CARE"]
    )
    resident = create_resident(
        community["id"], full_name="Bea Ortiz", baseline_weight_kg=78.0
    )
    record_observation(resident["id"], "2026-08-02", "LUNCH", 80, weight_kg=80.0)
    set_clock("2026-08-20T08:00:00Z")
    return {"community": community, "resident": resident}


def test_rolling_window_and_baseline_anchored_trends_diverge(api):
    """The same two weights read -5.00 against the oldest weight still inside the rolling
    window and -2.56 against the admission baseline, and the reported-only variant also
    publishes `current_weight_kg`.

    PRD: "Take all of the resident's weight-carrying observations regardless of date, sorted by
    descending `observation_date` and then descending `created_at`; the first row's `weight_kg`
    is the resident's `current_weight_kg`, and when the resident has no weight-carrying
    observation at all `current_weight_kg` falls back to `baseline_weight_kg`."

    Design: Difficulty/dual_variant_calc/weight_trend_rolling_vs_baseline_clinical
    """
    program = _elmhurst_two_weights()

    response = api.create_intake_observation(
        program["resident"]["id"],
        {
            "observation_date": "2026-08-20",
            "meal_period": "LUNCH",
            "intake_pct": 60,
            "weight_kg": 76.0,
        },
        CLINICAL_STAFF,
    )
    validate_success(response, 201)

    resident = read_resident(program["resident"]["id"])
    assert resident["rolling_30d_weight_change_pct"] == pytest.approx(-5.00, abs=0.01)
    assert resident["baseline_weight_change_pct"] == pytest.approx(-2.56, abs=0.01)
    assert resident["current_weight_kg"] == pytest.approx(76.0, abs=0.01)
    assert resident["avg_intake_pct_7d"] == pytest.approx(60.00, abs=0.01)
    assert resident["intake_risk_score"] == pytest.approx(45.00, abs=0.01)


def test_only_the_rolling_variant_gates_the_plan_of_care_review(api):
    """The review that opens cites `WEIGHT_LOSS_30D` and snapshots the hop-one score, which the
    -2.56 baseline figure could never have produced.

    PRD: "Only the rolling thirty-day variant is consulted here; the baseline-anchored figure
    never gates."

    Design: Difficulty/dual_variant_calc/weight_trend_rolling_vs_baseline_clinical
    """
    program = _elmhurst_two_weights()
    observation = record_observation(
        program["resident"]["id"], "2026-08-20", "LUNCH", 60, weight_kg=76.0
    )

    reviews = reviews_for(program["resident"]["id"], status="OPEN")
    assert len(reviews) == 1
    assert reviews[0]["trigger_reason"] == "WEIGHT_LOSS_30D"
    assert reviews[0]["risk_score_at_open"] == pytest.approx(45.00, abs=0.01)
    assert reviews[0]["trigger_observation_id"] == observation["id"]


def _wexford_two_residents():
    """Two residents at baseline 78.0 kg, each with one 80.0 kg observation on 2026-08-02."""
    set_clock("2026-08-02T08:00:00Z")
    community = create_community("Brookdale Wexford", ["ASSISTED_LIVING"])
    resident_a = create_resident(
        community["id"], full_name="Lena Ashford", baseline_weight_kg=78.0
    )
    resident_b = create_resident(
        community["id"], full_name="Miles Trent", baseline_weight_kg=78.0
    )
    record_observation(resident_a["id"], "2026-08-02", "LUNCH", 80, weight_kg=80.0)
    record_observation(resident_b["id"], "2026-08-02", "LUNCH", 80, weight_kg=80.0)
    set_clock("2026-08-20T08:00:00Z")
    return {"community": community, "a": resident_a, "b": resident_b}


def test_rolling_loss_of_exactly_five_percent_breaches_while_four_seventy_five_does_not(api):
    """76.0 kg against 80.0 kg lands exactly on -5.00 and opens a review; 76.2 kg lands on
    -4.75 and opens nothing, leaving that resident's tray card clear.

    PRD: "The weight breach holds when `rolling_30d_weight_change_pct` is at most negative 5.00
    — exactly negative 5.00 does breach, negative 4.99 does not."

    Design: Difficulty/boundary_precision_check/rolling_weight_loss_inclusive_minus_five_boundary
    """
    program = _wexford_two_residents()

    record_observation(program["a"]["id"], "2026-08-20", "LUNCH", 80, weight_kg=76.0)
    record_observation(program["b"]["id"], "2026-08-20", "LUNCH", 80, weight_kg=76.2)

    reviews_a = api_client.list_plan_of_care_reviews(
        DIETITIAN, params={"resident_id": program["a"]["id"]}
    )
    rows_a, meta_a = validate_paginated(reviews_a)
    assert meta_a["total_count"] == 1
    assert rows_a[0]["trigger_reason"] == "WEIGHT_LOSS_30D"

    reviews_b = api_client.list_plan_of_care_reviews(
        DIETITIAN, params={"resident_id": program["b"]["id"]}
    )
    rows_b, meta_b = validate_paginated(reviews_b)
    assert meta_b["total_count"] == 0
    assert rows_b == []
    assert read_resident(program["b"]["id"])["tray_card_state"] == "CLEAR"


def test_both_weight_variants_are_published_on_each_side_of_the_boundary(api):
    """The two residents differ by 0.2 kg, and both variants move with it: -5.00 / -2.56 for
    one and -4.75 / -2.31 for the other.

    PRD: "Otherwise take the earliest weight and the latest weight in that ordering, subtract
    the earliest from the latest, divide by the earliest, multiply by 100, and round half up to
    2 decimal places."

    Design: Difficulty/boundary_precision_check/rolling_weight_loss_inclusive_minus_five_boundary
    """
    program = _wexford_two_residents()

    record_observation(program["a"]["id"], "2026-08-20", "LUNCH", 80, weight_kg=76.0)
    record_observation(program["b"]["id"], "2026-08-20", "LUNCH", 80, weight_kg=76.2)

    resident_a = read_resident(program["a"]["id"])
    resident_b = read_resident(program["b"]["id"])

    assert resident_a["rolling_30d_weight_change_pct"] == pytest.approx(-5.00, abs=0.01)
    assert resident_a["baseline_weight_change_pct"] == pytest.approx(-2.56, abs=0.01)
    assert resident_b["rolling_30d_weight_change_pct"] == pytest.approx(-4.75, abs=0.01)
    assert resident_b["baseline_weight_change_pct"] == pytest.approx(-2.31, abs=0.01)


def _windemere_monitored_resident():
    """A MEMORY_CARE resident with a restrictive order and two substitution rules."""
    set_clock("2026-08-02T08:00:00Z")
    community = create_community(
        "Brookdale Windemere", ["ASSISTED_LIVING", "MEMORY_CARE"]
    )
    resident = create_resident(
        community["id"],
        full_name="Fay Okonkwo",
        care_level="MEMORY_CARE",
        baseline_weight_kg=78.0,
        allergens=["PEANUT"],
    )
    order = create_diet_order(
        resident["id"],
        texture_level="MINCED_MOIST",
        liquid_consistency="MILDLY_THICK",
        therapeutic_codes=["LOW_SODIUM", "RENAL"],
    )
    approve_diet_order(order["id"])
    texture_rule = create_substitution_rule(
        resident["id"], "TEXTURE", "ANY", "PUREED-ALT", priority_rank=1
    )
    allergen_rule = create_substitution_rule(
        resident["id"], "ALLERGEN", "PEANUT", "NUT-FREE-ALT", priority_rank=1
    )
    record_observation(resident["id"], "2026-08-02", "LUNCH", 80, weight_kg=80.0)
    set_clock("2026-08-20T08:00:00Z")
    return {
        "community": community,
        "resident": resident,
        "order": order,
        "texture_rule": texture_rule,
        "allergen_rule": allergen_rule,
    }


def test_observation_opens_a_review_and_pushes_the_active_order_to_rereview(api):
    """Hops one to three: the metrics are recomputed, the breach opens a review snapshotting a
    score of 75.00, and the `ACTIVE` order's review axis moves without its clinical axis.

    PRD: "**Hop 3** fires when hop 2 actually opened a review: the resident's diet order whose
    `clinical_status` is `ACTIVE` moves its `review_status` from `APPROVED` to
    `REREVIEW_REQUIRED`, while `clinical_status` stays `ACTIVE`."

    Design: Difficulty/transitive_cascade/intake_observation_four_hop_monitoring_chain
    """
    program = _windemere_monitored_resident()

    response = api.create_intake_observation(
        program["resident"]["id"],
        {
            "observation_date": "2026-08-20",
            "meal_period": "LUNCH",
            "intake_pct": 60,
            "weight_kg": 76.0,
        },
        CLINICAL_STAFF,
    )
    observation = validate_success(response, 201)

    resident = read_resident(program["resident"]["id"])
    assert resident["rolling_30d_weight_change_pct"] == pytest.approx(-5.00, abs=0.01)
    assert resident["intake_risk_score"] == pytest.approx(75.00, abs=0.01)

    reviews = reviews_for(program["resident"]["id"], status="OPEN")
    assert len(reviews) == 1
    assert reviews[0]["trigger_observation_id"] == observation["id"]
    assert reviews[0]["risk_score_at_open"] == pytest.approx(75.00, abs=0.01)
    assert reviews[0]["trigger_reason"] == "WEIGHT_LOSS_30D"

    order = read_diet_order(program["order"]["id"])
    assert order["review_status"] == "REREVIEW_REQUIRED"
    assert order["clinical_status"] == "ACTIVE"


def test_only_texture_rules_are_superseded_and_the_tray_card_goes_on_hold(api):
    """Hop four supersedes the `TEXTURE` rule, leaves the `ALLERGEN` rule active, holds the
    tray card and lands the order in the community's pending review count.

    PRD: "**Hop 4** follows from that transition: every substitution rule of the resident whose
    `trigger_type` is `TEXTURE` and whose `status` is `ACTIVE` flips to `SUPERSEDED`, and the
    resident's `tray_card_state` moves from `CLEAR` to `HOLD_PENDING_REVIEW`."

    Design: Difficulty/transitive_cascade/intake_observation_four_hop_monitoring_chain
    """
    program = _windemere_monitored_resident()

    record_observation(
        program["resident"]["id"], "2026-08-20", "LUNCH", 60, weight_kg=76.0
    )

    texture_rules = list_rules(program["resident"]["id"], trigger_type="TEXTURE")
    assert len(texture_rules) == 1
    assert texture_rules[0]["status"] == "SUPERSEDED"

    allergen_rules = list_rules(program["resident"]["id"], trigger_type="ALLERGEN")
    assert len(allergen_rules) == 1
    assert allergen_rules[0]["status"] == "ACTIVE"

    assert (
        read_resident(program["resident"]["id"])["tray_card_state"]
        == "HOLD_PENDING_REVIEW"
    )
    assert read_community(program["community"]["id"])["pending_dietitian_review_count"] == 1


def _larkspur_reviewed_order():
    """A restrictive order approved before a rolling-window weight breach."""
    set_clock("2026-08-02T08:00:00Z")
    community = create_community(
        "Brookdale Larkspur", ["ASSISTED_LIVING", "MEMORY_CARE"]
    )
    resident = create_resident(
        community["id"], full_name="Eli Nakamura", baseline_weight_kg=78.0
    )
    order = create_diet_order(
        resident["id"],
        texture_level="MINCED_MOIST",
        liquid_consistency="MILDLY_THICK",
        therapeutic_codes=["LOW_SODIUM", "RENAL"],
    )
    approved = approve_diet_order(order["id"])
    record_observation(resident["id"], "2026-08-02", "LUNCH", 80, weight_kg=80.0)
    set_clock("2026-08-20T08:00:00Z")
    return {"community": community, "resident": resident, "order": approved}


def test_review_axis_returns_to_approved_without_the_clinical_axis_moving(api):
    """The cascade pushes the order to `REREVIEW_REQUIRED` at `review_round` 0 and a fresh
    approval returns it to `APPROVED`, with `clinical_status` `ACTIVE` and `activated_at`
    unchanged throughout.

    PRD: "It moves `review_status` from `REREVIEW_REQUIRED` to `APPROVED` while
    `clinical_status` remains `ACTIVE` throughout — proof that the two axes are genuinely
    independent."

    Design: Difficulty/non_linear_state_machine/diet_order_parallel_axes_rereview_while_active
    """
    program = _larkspur_reviewed_order()
    activated_at_first = program["order"]["activated_at"]

    record_observation(
        program["resident"]["id"], "2026-08-20", "LUNCH", 60, weight_kg=76.0
    )

    after_observation = read_diet_order(program["order"]["id"])
    assert after_observation["review_status"] == "REREVIEW_REQUIRED"
    assert after_observation["clinical_status"] == "ACTIVE"
    assert after_observation["review_round"] == 0

    response = api.dietitian_review_diet_order(
        program["order"]["id"], {"decision": "APPROVE"}, DIETITIAN
    )
    final = validate_success(response)
    assert final["review_status"] == "APPROVED"
    assert final["clinical_status"] == "ACTIVE"
    assert final["activated_at"] == activated_at_first


def test_reapproval_lifts_the_hold_while_the_risk_score_keeps_the_order_contributions(api):
    """Re-approving out of `REREVIEW_REQUIRED` returns `tray_card_state` to `CLEAR`, and the
    score still reads the active order's texture, therapeutic and liquid contributions at 75.00.

    PRD: "It sets `reviewed_by_user_id` to the acting `X-User-ID`, cascades the resident's
    `tray_card_state` from `HOLD_PENDING_REVIEW` back to `CLEAR`, and recomputes the community's
    `pending_dietitian_review_count`."

    Design: Difficulty/non_linear_state_machine/diet_order_parallel_axes_rereview_while_active
    """
    program = _larkspur_reviewed_order()

    record_observation(
        program["resident"]["id"], "2026-08-20", "LUNCH", 60, weight_kg=76.0
    )
    approve_diet_order(program["order"]["id"])

    resident = read_resident(program["resident"]["id"])
    assert resident["tray_card_state"] == "CLEAR"
    assert resident["intake_risk_score"] == pytest.approx(75.00, abs=0.01)
