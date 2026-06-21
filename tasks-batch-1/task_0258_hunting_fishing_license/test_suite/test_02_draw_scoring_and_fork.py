"""The lottery draw: priority scoring variants, the AWARDED/UNSUCCESSFUL fork, the
award cascade, tag conservation, and optimistic-concurrency on execution.

PRD §3.6 (entry/snapshots), §3.8 (execution, scoring, cascade), §2.7 (OCC).
"""
from test_helpers import (
    validate_success,
    create_applicant, create_season, create_tag_product_for_season,
    create_pool, enter_draw, close_pool, execute_pool_draw,
    setup_closed_pool_ready_to_draw, set_clock, TEST_USERS,
)

OFFICER = TEST_USERS["draw_officer_headers"]


def _drive_to_two_preference_points(season_id, product_id):
    """Create applicant X and lose two single-quota draws so X reaches preference_points 2.
    Returns X's applicant id. Mirrors the divergence-instance accrual recipe."""
    x = create_applicant(full_name="X", declared_state_code="MT")
    # Losing draw L1: winner W1 (bonus 1) beats X (pp0,b0); X pp 0->1.
    w1 = create_applicant(full_name="W1", bonus_points=1)
    pl1 = create_pool(season_id, product_id, quota=1,
                      entry_deadline="2026-03-10T00:00:00Z", scoring_model="SQUARED")
    enter_draw(pl1["id"], w1["id"])
    enter_draw(pl1["id"], x["id"])
    closed1 = close_pool(pl1["id"], "2026-03-11T00:00:00Z")
    execute_pool_draw(pl1["id"], closed1["version"])
    # Losing draw L2: winner W2 (bonus 2, score 2) beats X (pp1, score 1); X pp 1->2.
    w2 = create_applicant(full_name="W2", bonus_points=2)
    pl2 = create_pool(season_id, product_id, quota=1,
                      entry_deadline="2026-03-20T00:00:00Z", scoring_model="SQUARED")
    enter_draw(pl2["id"], w2["id"])
    enter_draw(pl2["id"], x["id"])
    closed2 = close_pool(pl2["id"], "2026-03-21T00:00:00Z")
    execute_pool_draw(pl2["id"], closed2["version"])
    return x["id"]


def test_priority_score_squared_model(api):
    """PRD §3.8: "Under the `SQUARED` model the score is the preference points multiplied by
    themselves, plus the bonus points."

    Design: Difficulty/dual_variant_calc/draw_priority_score_squared_vs_linear_diverge
    """
    set_clock("2026-03-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    x_id = _drive_to_two_preference_points(season["id"], product["id"])

    p_sq = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-03-30T00:00:00Z", scoring_model="SQUARED")
    da_sq = enter_draw(p_sq["id"], x_id)
    closed = close_pool(p_sq["id"], "2026-03-31T00:00:00Z")
    execute_pool_draw(p_sq["id"], closed["version"])

    drawn_app = validate_success(api.get_draw_application(da_sq["id"], OFFICER), 200)
    # points_at_entry 2, bonus_at_entry 0 -> SQUARED = 2*2 + 0 = 4.
    assert drawn_app["priority_score"] == 4, (
        f"SQUARED score for pp=2,b=0 should be 4, got {drawn_app['priority_score']}")


def test_priority_score_linear_model_diverges(api):
    """PRD §3.8: "Under the `LINEAR` model the score is the preference points plus the bonus
    points. (Concretely, three preference points and two bonus points yield eleven under
    `SQUARED` but five under `LINEAR`.)"

    Design: Difficulty/dual_variant_calc/draw_priority_score_squared_vs_linear_diverge
    """
    set_clock("2026-03-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    x_id = _drive_to_two_preference_points(season["id"], product["id"])

    p_ln = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-03-30T00:00:00Z", scoring_model="LINEAR")
    da_ln = enter_draw(p_ln["id"], x_id)
    closed = close_pool(p_ln["id"], "2026-03-31T00:00:00Z")
    execute_pool_draw(p_ln["id"], closed["version"])

    drawn_app = validate_success(api.get_draw_application(da_ln["id"], OFFICER), 200)
    # points_at_entry 2, bonus_at_entry 0 -> LINEAR = 2 + 0 = 2.
    assert drawn_app["priority_score"] == 2, (
        f"LINEAR score for pp=2,b=0 should be 2, got {drawn_app['priority_score']}")


def test_draw_fork_awarded_branch_side_effects(api):
    """PRD §3.8: "For each awarded application the system mints a `License` with `issued_via`
    of `DRAW_AWARD` (priced per §3.5 using the applicant's residency at award time, with no
    agent surcharge), populates the application's `issued_license_id` with that license, resets
    the applicant's `preference_points` to 0, and increments the applicant's `version`."

    Design: Difficulty/non_linear_state_machine/draw_application_fork_awarded_vs_unsuccessful_divergent_side_effects
    """
    set_clock("2026-03-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    pool = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-03-10T00:00:00Z", scoring_model="SQUARED")
    a1 = create_applicant(full_name="A1")
    a2 = create_applicant(full_name="A2")
    da1 = enter_draw(pool["id"], a1["id"])
    enter_draw(pool["id"], a2["id"])
    closed = close_pool(pool["id"], "2026-03-11T00:00:00Z")
    execute_pool_draw(pool["id"], closed["version"])

    # A1 created first -> wins tie-break (both pp0/b0, tie broken by created_at ASC).
    awarded = validate_success(api.get_draw_application(da1["id"], OFFICER), 200)
    assert awarded["status"] == "AWARDED"
    assert awarded["issued_license_id"] is not None
    applicant_a1 = validate_success(api.get_applicant(a1["id"], OFFICER), 200)
    assert applicant_a1["preference_points"] == 0, (
        "awarded applicant's preference_points must reset to 0")


def test_draw_fork_unsuccessful_branch_side_effects(api):
    """PRD §3.8: "Every remaining `SUBMITTED` application that did not place within quota moves `SUBMITTED → UNSUCCESSFUL`; for each, the applicant's `preference_points` is increased by one — but clamped so it never exceeds the preference-point cap of twelve — and the applicant's `version` is incremented."

    Design: Difficulty/non_linear_state_machine/draw_application_fork_awarded_vs_unsuccessful_divergent_side_effects
    """
    set_clock("2026-03-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    pool = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-03-10T00:00:00Z", scoring_model="SQUARED")
    a1 = create_applicant(full_name="A1")
    a2 = create_applicant(full_name="A2")
    enter_draw(pool["id"], a1["id"])
    da2 = enter_draw(pool["id"], a2["id"])
    closed = close_pool(pool["id"], "2026-03-11T00:00:00Z")
    execute_pool_draw(pool["id"], closed["version"])

    # A2 created second -> loses the tie, goes UNSUCCESSFUL.
    unsuccessful = validate_success(api.get_draw_application(da2["id"], OFFICER), 200)
    assert unsuccessful["status"] == "UNSUCCESSFUL"
    assert unsuccessful["issued_license_id"] is None, (
        "unsuccessful application must not be linked to any minted license")
    applicant_a2 = validate_success(api.get_applicant(a2["id"], OFFICER), 200)
    assert applicant_a2["preference_points"] == 1, (
        "unsuccessful applicant gains exactly one preference point")


def test_draw_award_depth3_cascade(api):
    """PRD §3.8: "For each awarded application the system mints a `License` with `issued_via` of
    `DRAW_AWARD` (priced per §3.5 using the applicant's residency at award time, with no agent
    surcharge), populates the application's `issued_license_id` with that license, resets the
    applicant's `preference_points` to 0, and increments the applicant's `version`."

    Design: Difficulty/transitive_cascade/draw_award_depth3_cascade_application_license_points
    """
    set_clock("2026-04-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    w = create_applicant(full_name="W")
    # Prior losing draw lifts W to preference_points=1.
    w0 = create_applicant(full_name="Winner0", bonus_points=5)
    pl0 = create_pool(season["id"], product["id"], quota=1,
                      entry_deadline="2026-04-10T00:00:00Z", scoring_model="SQUARED")
    enter_draw(pl0["id"], w0["id"])
    enter_draw(pl0["id"], w["id"])
    closed0 = close_pool(pl0["id"], "2026-04-11T00:00:00Z")
    execute_pool_draw(pl0["id"], closed0["version"])
    assert validate_success(api.get_applicant(w["id"], OFFICER), 200)["preference_points"] == 1

    # Winning pool with W alone.
    pool = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-04-20T00:00:00Z", scoring_model="SQUARED")
    da = enter_draw(pool["id"], w["id"])
    closed = close_pool(pool["id"], "2026-04-21T00:00:00Z")
    execute_pool_draw(pool["id"], closed["version"])

    # Link 1: application AWARDED.
    awarded = validate_success(api.get_draw_application(da["id"], OFFICER), 200)
    assert awarded["status"] == "AWARDED"
    # Link 2: minted DRAW_AWARD license is ISSUED.
    minted = validate_success(api.get_license(awarded["issued_license_id"], OFFICER), 200)
    assert minted["status"] == "ISSUED"
    assert minted["issued_via"] == "DRAW_AWARD"
    # Link 3: winner's preference_points reset to 0.
    applicant_w = validate_success(api.get_applicant(w["id"], OFFICER), 200)
    assert applicant_w["preference_points"] == 0


def test_draw_award_mints_draw_award_license_for_winner(api):
    """PRD §3.8: "For each awarded application the system mints a `License` with `issued_via` of
    `DRAW_AWARD` (priced per §3.5 using the applicant's residency at award time, with no agent
    surcharge), populates the application's `issued_license_id` with that license".

    Design: Difficulty/transitive_cascade/draw_award_depth3_cascade_application_license_points
    """
    set_clock("2026-03-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    pool = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-03-10T00:00:00Z", scoring_model="SQUARED")
    winner = create_applicant(full_name="W")
    da = enter_draw(pool["id"], winner["id"])
    closed = close_pool(pool["id"], "2026-03-11T00:00:00Z")
    execute_pool_draw(pool["id"], closed["version"])

    awarded = validate_success(api.get_draw_application(da["id"], OFFICER), 200)
    assert awarded["status"] == "AWARDED"
    minted = validate_success(api.get_license(awarded["issued_license_id"], OFFICER), 200)
    assert minted["issued_via"] == "DRAW_AWARD"
    assert minted["status"] == "ISSUED"
    assert minted["applicant_id"] == winner["id"], (
        "the draw-minted license must belong to the awarded applicant")


def test_draw_conserves_tag_pool(api):
    """PRD §3.8: "The top applications up to the pool's `quota` are awarded: each moves `SUBMITTED → AWARDED`, and this fork drives a deeper cascade."
    PRD §3.8: "Every remaining `SUBMITTED` application that did not place within quota moves `SUBMITTED → UNSUCCESSFUL".
    PRD §3.8: "Finally the pool's `awarded_count` is set to the number of awarded applications, the pool moves `CLOSED → DRAWN".

    Design: Difficulty/compensating_invariant/draw_conserves_tag_pool_awarded_plus_unawarded_equals_entrants_capped_by_quota
    """
    set_clock("2026-03-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    pool = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-03-10T00:00:00Z", scoring_model="SQUARED")
    app_ids = [enter_draw(pool["id"], create_applicant(full_name=name)["id"])["id"]
               for name in ("A1", "A2", "A3")]
    closed = close_pool(pool["id"], "2026-03-11T00:00:00Z")
    drawn = execute_pool_draw(pool["id"], closed["version"])

    assert drawn["awarded_count"] == 1, (
        f"with quota 1 and 3 entrants, awarded_count must be 1, got {drawn['awarded_count']}")
    statuses = [validate_success(api.get_draw_application(aid, OFFICER), 200)["status"]
                for aid in app_ids]
    assert statuses.count("AWARDED") == 1
    assert statuses.count("UNSUCCESSFUL") == 2
    assert len(statuses) == 3


def test_draw_awarded_count_recomputed(api):
    """PRD §3.8: "Finally the pool's `awarded_count` is set to the number of awarded applications, the pool moves `CLOSED → DRAWN".

    Design: Difficulty/compensating_invariant/draw_conserves_tag_pool_awarded_plus_unawarded_equals_entrants_capped_by_quota
    """
    season, product, pool, applicants, closed = setup_closed_pool_ready_to_draw(
        quota=1, num_entrants=3)
    drawn = execute_pool_draw(pool["id"], closed["version"])
    assert drawn["status"] == "DRAWN"
    assert drawn["awarded_count"] == 1


def test_execute_draw_correct_version_succeeds_and_increments(api):
    """PRD §2.7: "The server compares it to the pool's current `version`."
    PRD §3.8: "the pool moves `CLOSED → DRAWN`, and the pool's `version` is incremented by one as the concurrency advance."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_pool_version_succeeds_and_increments
    """
    season, product, pool, applicants, closed = setup_closed_pool_ready_to_draw(
        quota=1, num_entrants=1)
    drawn = execute_pool_draw(pool["id"], closed["version"])
    assert drawn["status"] == "DRAWN"
    assert drawn["version"] == closed["version"] + 1, (
        f"DrawPool.version must increment by exactly 1 on execute-draw; "
        f"was {closed['version']}, now {drawn['version']}")
