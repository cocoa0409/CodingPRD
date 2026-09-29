"""Depth tests for the three combinatorial formulas.

The ``combinatorial_formula`` rule has three instances: the sequential
integrity ladder of PRD §3.8, the bucketed entry-fee waterfall of PRD §3.6,
and the circularly dependent scholarship projection of PRD §3.9.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    INTEGRITY_OFFICER_ID,
    league_admin_headers,
)


# ==========================================================================
# Instance: integrity_score_repeat_multiplier_ladder_lands_exactly_on_the_
#           suspension_floor
# ==========================================================================
def _build_three_case_ladder(api):
    """A DRAFT team with a single PROSPECTIVE STARTER slot, carrying three
    MINOR cases opened in the order CHEAT_DETECTION, ACCOUNT_SHARING,
    ACCOUNT_SHARING.  The first two are already sustained; the third only
    reaches ``INVESTIGATING`` so the caller can drive the final decision."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    student = fx.make_student(api, school["id"])
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    slot = fx.add_slot(api, team["id"], student["id"], coach["id"], slot_role="STARTER")

    case_1 = fx.open_student_case(
        api, team["id"], student["id"], case_type="CHEAT_DETECTION"
    )
    fx.investigate_case(api, case_1["id"], officer_id=INTEGRITY_OFFICER_ID)
    fx.decide_case(
        api,
        case_1["id"],
        decision="SUSTAIN",
        severity="MINOR",
        officer_id=INTEGRITY_OFFICER_ID,
    )
    case_2 = fx.open_student_case(
        api, team["id"], student["id"], case_type="ACCOUNT_SHARING"
    )
    fx.investigate_case(api, case_2["id"], officer_id=INTEGRITY_OFFICER_ID)
    fx.decide_case(
        api,
        case_2["id"],
        decision="SUSTAIN",
        severity="MINOR",
        officer_id=INTEGRITY_OFFICER_ID,
    )
    case_3 = fx.open_student_case(
        api, team["id"], student["id"], case_type="ACCOUNT_SHARING"
    )
    fx.investigate_case(api, case_3["id"], officer_id=INTEGRITY_OFFICER_ID)
    return {
        "district": district,
        "school": school,
        "coach": coach,
        "team": team,
        "student": student,
        "slot": slot,
        "case_1": case_1,
        "case_2": case_2,
        "case_3": case_3,
    }


def _sustain_third(api, world):
    return fx.decide_case(
        api,
        world["case_3"]["id"],
        decision="SUSTAIN",
        severity="MINOR",
        officer_id=INTEGRITY_OFFICER_ID,
    )


def test_repeat_multiplier_ladder_rounds_each_case_before_summing(api):
    """Each case's penalty is rounded on its own, never on the total.

    PRD §3.8: "Each case's `severity_weight` is the sum of two constants: a
    severity component worth 5 for `MINOR`, 15 for `MAJOR` and 40 for
    `SEVERE`; and a case-type surcharge worth 5 for `ACCOUNT_SHARING`, 10 for
    `SMURFING`, 20 for `CHEAT_DETECTION` and 0 for `SPECTATOR_CONDUCT`. The
    repeat multiplier is 1.0 for the first case in the set, 1.5 for the
    second, and 2.0 for the third and every case after it. Each case's
    `applied_penalty` is its `severity_weight` multiplied by its own
    multiplier, rounded half up to two decimals — the rounding happens per
    case, never once on the total."  And: "The team's `integrity_score` is
    100.00 minus the total penalty plus that credit".

    Design: Difficulty/combinatorial_formula/integrity_score_repeat_multiplier_ladder_lands_exactly_on_the_suspension_floor
    """
    world = _build_three_case_ladder(api)
    _sustain_third(api, world)

    case_1 = fx.get_case(api, world["case_1"]["id"])
    assert case_1["repeat_index"] == 1
    assert case_1["severity_weight"] == 25
    A.assert_integrity_score(case_1["applied_penalty"], 25.00)

    case_2 = fx.get_case(api, world["case_2"]["id"])
    assert case_2["repeat_index"] == 2
    assert case_2["severity_weight"] == 10
    A.assert_integrity_score(case_2["applied_penalty"], 15.00)

    case_3 = fx.get_case(api, world["case_3"]["id"])
    assert case_3["repeat_index"] == 3
    assert case_3["severity_weight"] == 10
    A.assert_integrity_score(case_3["applied_penalty"], 20.00)

    team = fx.get_team(api, world["team"]["id"])
    A.assert_integrity_score(team["integrity_score"], 40.00)


def test_score_landing_exactly_on_forty_does_not_escalate_to_team_suspension(api):
    """The integrity-floor override is a strict ``below 40`` comparison.

    PRD §3.8: "A `SEVERE` severity selects `TEAM_SUSPENSION`. Otherwise a
    `MATCH_BROADCAST` subject selects `WARNING`. Otherwise the selection is
    `STUDENT_SUSPENSION`. Two overrides then apply in order: if the
    recomputed `integrity_score` is below 40 the sanction becomes
    `TEAM_SUSPENSION` regardless of what was selected".  The third link only
    demotes slots whose "`participation_status` is `ACTIVE`", and the fourth
    link is a "`COMPETING → SUSPENDED`" move.

    Design: Difficulty/combinatorial_formula/integrity_score_repeat_multiplier_ladder_lands_exactly_on_the_suspension_floor
    """
    world = _build_three_case_ladder(api)
    case_3 = _sustain_third(api, world)

    assert case_3["status"] == "SUSTAINED"
    assert case_3["sanction_type"] == "STUDENT_SUSPENSION"

    team = fx.get_team(api, world["team"]["id"])
    A.assert_integrity_score(team["integrity_score"], 40.00)
    assert team["status"] == "DRAFT"
    assert team["suspension_reason"] is None

    student = fx.get_student(api, world["student"]["id"])
    assert student["fair_play_status"] == "SANCTIONED"

    slot = fx.get_slot(api, world["slot"]["id"])
    A.assert_slot_axes(slot, participation_status="PROSPECTIVE")
    assert slot["ineligibility_reason"] is None


# ==========================================================================
# Instance: entry_fee_waterfall_per_line_subsidy_rounding_with_two_starters
# ==========================================================================
def _build_two_starter_draft_team(api):
    """A DRAFT team holding two ACTIVE STARTER slots inside the default
    registration window, on a district-approved title."""
    world = fx.build_draft_team(api, term_gpa=3.100, term_credits=6.0)
    student_b = fx.make_student_with_term(
        api, world["school"]["id"], term_gpa=3.100, term_credits=6.0
    )
    world["slot_a"] = fx.make_active_starter(
        api, world["team"]["id"], world["coach"]["id"], world["student"], "STARTER"
    )
    world["slot_b"] = fx.make_active_starter(
        api, world["team"]["id"], world["coach"]["id"], student_b, "STARTER"
    )
    world["student_b"] = student_b
    return world


def test_two_starter_entry_fee_subsidises_each_line_item_separately(api):
    """The per-line subsidy sums to 4796, not the 4795 of sum-then-round.

    PRD §3.6: "The district's subsidy is then computed **per line item**:
    each line item is multiplied by the district's `subsidy_pct` and that
    product is rounded half up to a whole number of cents, and only then are
    the per-line results added together to give `subsidy_granted_cents`.
    Rounding the sum instead of the parts is wrong and can differ by one cent
    for every line item."  And: "`net_fee_due_cents` is `entry_fee_cents`
    less `subsidy_granted_cents`."

    Design: Difficulty/combinatorial_formula/entry_fee_waterfall_per_line_subsidy_rounding_with_two_starters
    """
    world = _build_two_starter_draft_team(api)

    response = api.register_team(world["team"]["id"], {}, fx.make_coach_headers(world["coach"]["id"]))
    validate_success(response)
    team = A.data_of(response)

    assert team["status"] == "REGISTERED"
    A.assert_cents(team["entry_fee_cents"], 19180)
    A.assert_cents(team["subsidy_granted_cents"], 4796)
    A.assert_cents(team["net_fee_due_cents"], 14384)


def test_two_starter_registration_debits_the_district_pool_by_the_line_sum(api):
    """The one-cent difference is observable on the district's ledger.

    PRD §3.6: "the district's `subsidy_pool_cents` is reduced by exactly the
    `subsidy_granted_cents` just awarded, keeping the subsidy conservation
    invariant in balance against the district's `subsidy_pool_initial_cents`"
    and "the season's `registered_team_count` is recomputed".

    Design: Difficulty/combinatorial_formula/entry_fee_waterfall_per_line_subsidy_rounding_with_two_starters
    """
    world = _build_two_starter_draft_team(api)
    team = fx.register_team(api, world["team"])

    district = fx.get_district(api, world["district"]["id"])
    A.assert_cents(district["subsidy_pool_initial_cents"], 5000000)
    A.assert_cents(district["subsidy_pool_cents"], 4995204)
    A.assert_subsidy_conserved(district, team["subsidy_granted_cents"])

    assert team["starter_slots_used"] == 2
    assert team["starter_slots_available"] == 1
    assert team["active_starter_count"] == 2

    season = fx.get_season(api, world["season"]["id"])
    assert season["registered_team_count"] == 1


# ==========================================================================
# Instance: scholarship_award_tier_pinned_to_provisional_total_not_final_total
# ==========================================================================
def _build_seeded_two_team_season(api):
    """Alpha and Bravo both score 0.0000 seed points, so the created_at ASC
    final tie-break puts Alpha on seed 1 and Bravo on seed 2."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    title = fx.make_title(api, server_pool_capacity=2)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    season = fx.open_registration(api, season["id"])

    built = {}
    for label in ("Alpha", "Bravo"):
        coach = fx.make_certified_coach(api, school["id"])
        student = fx.make_student_with_term(
            api, school["id"], term_gpa=3.100, term_credits=6.0
        )
        team = fx.make_team(
            api, season["id"], school["id"], title["id"], coach["id"], name=label
        )
        fx.make_active_starter(api, team["id"], coach["id"], student, "STARTER")
        team = fx.register_team(api, team)
        team = fx.lock_roster(api, team)
        built[label] = {"team": team, "student": student, "coach": coach}

    fx.advance_season(api, season["id"], "ROSTER_LOCKED")
    fx.advance_season(api, season["id"], "REGULAR_SEASON")
    season = fx.run_seeding(api, season["id"])

    return {
        "district": district,
        "school": school,
        "season": season,
        "alpha": built["Alpha"],
        "bravo": built["Bravo"],
    }


def test_award_tier_stays_silver_although_the_final_total_lies_in_the_gold_band(api):
    """The tier is pinned to the provisional total and never re-derived.

    PRD §3.9: "Step two chooses `award_tier` from that provisional total
    alone: at or above 350,000 cents it is `GOLD`, otherwise at or above
    200,000 cents it is `SILVER`".  And: "A student in `GOOD` standing on the
    top-seeded team reaches a provisional total of 330,000 cents, which lands
    in the silver band, earning a 39,600-cent bonus and a final
    `scholarship_award_cents` of 369,600. The stored `award_tier` remains
    `SILVER` even though the final figure sits inside the gold band, and the
    bonus is never recomputed at the gold rate."

    Design: Difficulty/combinatorial_formula/scholarship_award_tier_pinned_to_provisional_total_not_final_total
    """
    world = _build_seeded_two_team_season(api)
    alpha_team = fx.get_team(api, world["alpha"]["team"]["id"])
    assert alpha_team["seed_position"] == 1

    student_id = world["alpha"]["student"]["id"]
    response = api.nominate_showcase(
        student_id,
        {"nominating_team_id": alpha_team["id"]},
        league_admin_headers(),
    )
    validate_success(response)
    student = A.data_of(response)

    assert student["academic_standing"] == "GOOD"
    A.assert_gpa(student["effective_gpa"], 3.100)
    A.assert_cents(student["provisional_award_cents"], 330000)
    assert student["award_tier"] == "SILVER"
    A.assert_cents(student["scholarship_award_cents"], 369600)


def test_showcase_nomination_pins_the_seed_and_leaves_the_sibling_untouched(api):
    """Only the nominated student's projection is written.

    PRD §3.9: "On acceptance `showcase_status` becomes `NOMINATED` and
    `nominating_team_id` is stored on the student."  And: "Step four sets
    `scholarship_award_cents` to the provisional total plus that bonus, and
    sets `scholarship_award_state` to `CURRENT`."  `scholarship_award_state`
    "takes `NONE` before any nomination".

    Design: Difficulty/combinatorial_formula/scholarship_award_tier_pinned_to_provisional_total_not_final_total
    """
    world = _build_seeded_two_team_season(api)
    alpha_team = fx.get_team(api, world["alpha"]["team"]["id"])
    bravo_team = fx.get_team(api, world["bravo"]["team"]["id"])
    A.assert_seed_points(alpha_team["seed_points"], 0.0000)
    A.assert_seed_points(bravo_team["seed_points"], 0.0000)
    assert alpha_team["seed_position"] == 1
    assert bravo_team["seed_position"] == 2

    fx.data_of(
        api.nominate_showcase(
            world["alpha"]["student"]["id"],
            {"nominating_team_id": alpha_team["id"]},
            league_admin_headers(),
        )
    )

    nominated = fx.get_student(api, world["alpha"]["student"]["id"])
    assert nominated["showcase_status"] == "NOMINATED"
    assert nominated["nominating_team_id"] == alpha_team["id"]
    assert nominated["scholarship_award_state"] == "CURRENT"

    sibling = fx.get_student(api, world["bravo"]["student"]["id"])
    assert sibling["showcase_status"] == "NONE"
    A.assert_cents(sibling["scholarship_award_cents"], 0)
    assert sibling["nominating_team_id"] is None
    assert sibling["award_tier"] == "NONE"
    assert sibling["scholarship_award_state"] == "NONE"
