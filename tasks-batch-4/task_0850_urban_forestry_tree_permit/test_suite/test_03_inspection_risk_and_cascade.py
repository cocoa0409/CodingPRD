"""Condition inspection, risk-rating variants, dispute cycle, and zone risk cascade."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_inspection_payload,
    setup_tree, setup_finalized_inspection_tree,
    new_inspection, finalize, dispute,
    TEST_USERS,
)

INSPECTOR = TEST_USERS["inspector_headers"]
ADMIN = TEST_USERS["forestry_admin_headers"]


# ── Corner: invalid transition & OCC ─────────────────────────────────────
def test_finalize_already_finalized_inspection_rejected(api):
    """PRD §3.3: "When the `Inspector` **finalizes** an inspection — a transition
    permitted only from `DRAFT` or from `DISPUTED` status, and rejected with
    `ERR_INVALID_STATE` otherwise — the server computes the **final** variant."

    Design: Corner/state_machines/finalize_already_finalized_inspection_returns_invalid_state
    """
    zone, species, tree, insp = setup_finalized_inspection_tree(likelihood=2, consequence=2, target=2)
    res = api.finalize_inspection(insp["id"], INSPECTOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_inspection_create_with_stale_tree_version_rejected(api):
    """PRD §2.7: "the server bumps the tree's `version` each time an inspection is created
    and records the new inspection as the tree's current one".
    PRD §2.7: "When `expected_tree_version` does not equal the tree's current `version`,
    the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from
    superseding an inspection it never saw."

    Design: Corner/cross_cutting_complexity_layers/inspection_create_stale_tree_version_returns_412
    """
    zone, species, tree = setup_tree(dbh=20.0)
    v1 = tree["version"]
    # First create observes v1 and bumps the tree's version.
    new_inspection(tree["id"], v1, inspection_type="RISK",
                   likelihood_score=2, consequence_score=2, target_rating=2)
    # Second create carrying the now-stale v1 must be rejected.
    res = api.create_inspection(
        tree["id"],
        create_inspection_payload(v1, inspection_type="ROUTINE",
                                  likelihood_score=1, consequence_score=1, target_rating=1),
        INSPECTOR)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# ── dual_variant_calc: provisional vs final band ─────────────────────────
def test_provisional_variant_scores_nine_high_at_create(api):
    """PRD §3.3: "At create time the server computes the **provisional** variant and
    stores it on the inspection: `provisional_risk_score` is the `likelihood_score`
    multiplied by the `consequence_score`, with no target bonus and no cap, and
    `provisional_risk_rating` is that score's band."
    PRD §3.3: "a score from 8 through 11 is `HIGH`".

    Design: Difficulty/dual_variant_calc/risk_provisional_vs_final_diverge
    """
    zone, species, tree = setup_tree(dbh=20.0)
    res = api.create_inspection(
        tree["id"],
        create_inspection_payload(tree["version"], inspection_type="RISK",
                                  likelihood_score=3, consequence_score=3, target_rating=4),
        INSPECTOR)
    insp = validate_success(res, 201)
    assert insp["provisional_risk_score"] == 9
    assert insp["provisional_risk_rating"] == "HIGH"


def test_final_variant_scores_twelve_severe_diverging_from_provisional(api):
    """PRD §3.3: "The `final_risk_score` is the `likelihood_score` multiplied by the
    `consequence_score`, plus a target bonus of 3 when the `target_rating` is 3 or greater
    (and no bonus when it is below 3), with the resulting sum then capped at a maximum of
    16".
    PRD §3.3: "a score of 12 or more is `SEVERE`".

    Design: Difficulty/dual_variant_calc/risk_provisional_vs_final_diverge
    """
    zone, species, tree = setup_tree(dbh=20.0)
    insp = new_inspection(tree["id"], tree["version"], inspection_type="RISK",
                          likelihood_score=3, consequence_score=3, target_rating=4)
    final = finalize(insp["id"])
    assert final["final_risk_score"] == 12
    assert final["final_risk_rating"] == "SEVERE"
    assert final["final_risk_rating"] != final["provisional_risk_rating"]


# ── combinatorial_formula: three-input nonlinear final with cap ──────────
def test_final_score_clamps_to_cap_sixteen(api):
    """PRD §3.3: "with the resulting sum then capped at a maximum of 16; that is, the final
    score is the smaller of the bonus-adjusted product and 16."

    Design: Difficulty/combinatorial_formula/risk_final_nonlinear_three_inputs
    """
    zone, species, tree = setup_tree(dbh=20.0)
    insp = new_inspection(tree["id"], tree["version"], inspection_type="RISK",
                          likelihood_score=4, consequence_score=4, target_rating=4)
    final = finalize(insp["id"])
    # 4*4=16, +3 target bonus = 19, clamped to 16.
    assert final["final_risk_score"] == 16
    assert final["final_risk_rating"] == "SEVERE"


def test_provisional_uncapped_product_also_sixteen(api):
    """PRD §3.3: "`provisional_risk_score` is the `likelihood_score` multiplied by the
    `consequence_score`, with no target bonus and no cap".
    PRD §3.3: "the final score is the smaller of the bonus-adjusted product and 16."

    Design: Difficulty/combinatorial_formula/risk_final_nonlinear_three_inputs
    """
    zone, species, tree = setup_tree(dbh=20.0)
    res = api.create_inspection(
        tree["id"],
        create_inspection_payload(tree["version"], inspection_type="RISK",
                                  likelihood_score=4, consequence_score=4, target_rating=4),
        INSPECTOR)
    insp = validate_success(res, 201)
    assert insp["provisional_risk_score"] == 16
    final = finalize(insp["id"])
    assert final["final_risk_score"] == 16


# ── non_linear_state_machine: dispute <-> finalize cycle ─────────────────
def test_dispute_moves_finalized_inspection_to_disputed(api):
    """PRD §3.3: "A `ForestryAdmin` may **dispute** a finalized inspection, transitioning
    it `FINALIZED → DISPUTED`."

    Design: Difficulty/non_linear_state_machine/inspection_dispute_finalize_cycle
    """
    zone, species, tree, insp = setup_finalized_inspection_tree(likelihood=2, consequence=2, target=2)
    res = api.dispute_inspection(insp["id"], ADMIN)
    disputed = validate_success(res, 200)
    assert disputed["status"] == "DISPUTED"


def test_refinalize_disputed_inspection_returns_finalized(api):
    """PRD §3.3: "Because finalize and dispute form a loop, a single inspection may cycle
    between `FINALIZED` and `DISPUTED` any number of times, each finalize re-snapshotting
    and each dispute restoring."

    Design: Difficulty/non_linear_state_machine/inspection_dispute_finalize_cycle
    """
    zone, species, tree, insp = setup_finalized_inspection_tree(likelihood=2, consequence=2, target=2)
    dispute(insp["id"])
    res = api.finalize_inspection(insp["id"], INSPECTOR)
    refinalized = validate_success(res, 200)
    assert refinalized["status"] == "FINALIZED"


# ── transitive_cascade: finalize SEVERE -> tree HAZARD -> zone count ─────
def test_finalize_severe_sets_tree_hazard_and_severe_risk(api):
    """PRD §3.3: "It then sets the tree's `risk_rating` to the `final_risk_rating`. It sets
    the tree's `health_status` to `HAZARD` when the final rating is `SEVERE`, to
    `DECLINING` when the final rating is `HIGH`, and to `HEALTHY` otherwise".

    Design: Difficulty/transitive_cascade/inspection_finalize_hazard_bumps_zone_high_risk
    """
    zone, species, tree = setup_tree(dbh=20.0)
    insp = new_inspection(tree["id"], tree["version"], inspection_type="RISK",
                          likelihood_score=3, consequence_score=3, target_rating=4)
    finalize(insp["id"])
    fetched = validate_success(api.get_tree(tree["id"], ADMIN), 200)
    assert fetched["risk_rating"] == "SEVERE"
    assert fetched["health_status"] == "HAZARD"


def test_finalize_severe_bumps_zone_high_risk_count(api):
    """PRD §3.3: "Finally it recomputes the owning zone's `high_risk_tree_count`, since a
    rating of `HIGH` or `SEVERE` places the tree in the high-risk set."

    Design: Difficulty/transitive_cascade/inspection_finalize_hazard_bumps_zone_high_risk
    """
    zone, species, tree = setup_tree(dbh=20.0)
    insp = new_inspection(tree["id"], tree["version"], inspection_type="RISK",
                          likelihood_score=3, consequence_score=3, target_rating=4)
    finalize(insp["id"])
    fetched = validate_success(api.get_zone(zone["id"], ADMIN), 200)
    assert fetched["high_risk_tree_count"] == 1


# ── compensating_invariant: dispute restores count and tree state ────────
def test_dispute_restores_zone_high_risk_count(api):
    """PRD §3.3: "Disputing compensates the finalize exactly: it restores the tree's
    `risk_rating` from `prior_risk_rating` and its `health_status` from
    `prior_health_status`, then recomputes the zone's `high_risk_tree_count` so the count
    returns to its pre-finalize value."

    Design: Difficulty/compensating_invariant/finalize_then_dispute_conserves_zone_high_risk_count
    """
    zone, species, tree = setup_tree(dbh=20.0)
    insp = new_inspection(tree["id"], tree["version"], inspection_type="RISK",
                          likelihood_score=3, consequence_score=3, target_rating=4)
    finalize(insp["id"])
    dispute(insp["id"])
    fetched = validate_success(api.get_zone(zone["id"], ADMIN), 200)
    assert fetched["high_risk_tree_count"] == 0


def test_dispute_restores_tree_prior_risk_and_health(api):
    """PRD §3.3: "Disputing compensates the finalize exactly: it restores the tree's
    `risk_rating` from `prior_risk_rating` and its `health_status` from
    `prior_health_status`".

    Design: Difficulty/compensating_invariant/finalize_then_dispute_conserves_zone_high_risk_count
    """
    zone, species, tree = setup_tree(dbh=20.0)
    insp = new_inspection(tree["id"], tree["version"], inspection_type="RISK",
                          likelihood_score=3, consequence_score=3, target_rating=4)
    finalize(insp["id"])
    dispute(insp["id"])
    fetched = validate_success(api.get_tree(tree["id"], ADMIN), 200)
    assert fetched["risk_rating"] == "NONE"
    assert fetched["health_status"] == "HEALTHY"
