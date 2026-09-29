"""Breadth tests for the ``consistency_model`` design section.

Both instances are ``immediate``-claim probes: one POST, then the first read of
every entity the write touched, plus one repeated read to show nothing settles
between calls.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    INTEGRITY_OFFICER_ID,
    INTEGRITY_OFFICER_ID_2,
    integrity_officer_headers,
    league_admin_headers,
    make_athletic_director_headers,
    make_coach_headers,
)


# ==========================================================================
# Instance: a_sustain_decision_exposes_every_cascade_effect_to_the_very_next_read
# ==========================================================================
def _build_investigated_cheat_case(api):
    """One DRAFT team with a single ACTIVE starter and one CHEAT_DETECTION case
    already taken up by integrity officer A (PRD §3.8 INVESTIGATING)."""
    world = fx.build_draft_team(api)
    world["slot"] = fx.make_active_starter(
        api,
        world["team"]["id"],
        world["coach"]["id"],
        world["student"],
        slot_role="STARTER",
    )
    case = fx.open_student_case(
        api,
        world["team"]["id"],
        world["student"]["id"],
        case_type="CHEAT_DETECTION",
    )
    world["case"] = fx.investigate_case(
        api, case["id"], officer_id=INTEGRITY_OFFICER_ID
    )
    return world


def test_one_sustain_post_is_already_visible_to_every_following_read(api):
    """The decision response carries the whole computed cascade, and the first
    read of the student, the slot and the team is already correct.

    PRD §3.8: "A `SUSTAIN` ... sets the case's `status` to `SUSTAINED`, stamps
    `decider_user_id` and `decided_at`, records the `severity`, computes
    `severity_weight` as the severity base — `MINOR` 5, `MAJOR` 15, `SEVERE` 40 —
    plus the case-type surcharge ... `CHEAT_DETECTION` 20 ... sets the student's
    `fair_play_status` to `SANCTIONED`, moves every roster slot of that student
    whose `participation_status` is `PROSPECTIVE` or `ACTIVE` to `INELIGIBLE`
    with `ineligibility_reason` `FAIR_PLAY`, and recomputes the charged team's
    `integrity_score`."  PRD §3.8 on the score: "`integrity_score` is `100.00`
    minus the total penalty plus the clean-conduct credit, clamped to the range
    `0.00` to `100.00`", with the repeat multiplier "`1.0` for `repeat_index` 1".
    PRD §2.5: "Every read of an entity reflects every write that has already
    returned."

    Design: Corner/consistency_model/a_sustain_decision_exposes_every_cascade_effect_to_the_very_next_read
    """
    world = _build_investigated_cheat_case(api)
    officer_b = integrity_officer_headers(INTEGRITY_OFFICER_ID_2)
    coach_headers = make_coach_headers(world["coach"]["id"])

    decision_response = api.decide_case(
        world["case"]["id"],
        {
            "decision": "SUSTAIN",
            "severity": "MAJOR",
            "decision_note": "third-party client confirmed",
        },
        officer_b,
    )
    validate_success(decision_response)
    decided = A.data_of(decision_response)
    assert decided["status"] == "SUSTAINED"
    assert decided["severity"] == "MAJOR"
    assert decided["severity_weight"] == 35, "MAJOR 15 plus CHEAT_DETECTION 20"
    assert decided["repeat_index"] == 1
    A.assert_integrity_score(decided["applied_penalty"], 35.00)
    assert decided["sanction_type"] == "STUDENT_SUSPENSION"
    assert decided["decider_user_id"] == INTEGRITY_OFFICER_ID_2
    assert decided["decided_at"] == "2026-08-01T00:00:00.000Z"

    student = A.data_of(api.get_student(world["student"]["id"], officer_b))
    assert student["fair_play_status"] == "SANCTIONED", (
        "the first read after the write must already show the sanction"
    )

    slot = A.data_of(api.get_roster_slot(world["slot"]["id"], officer_b))
    assert slot["participation_status"] == "INELIGIBLE"
    assert slot["ineligibility_reason"] == "FAIR_PLAY"

    team = A.data_of(api.get_team(world["team"]["id"], officer_b))
    A.assert_integrity_score(team["integrity_score"], 65.00)
    assert team["active_starter_count"] == 0
    assert team["status"] == "DRAFT", (
        "a DRAFT team has no COMPETING state to fall from"
    )

    team_as_coach = A.data_of(api.get_team(world["team"]["id"], coach_headers))
    assert team_as_coach == team, "visibility is not per-caller"

    case_read = A.data_of(api.get_fair_play_case(world["case"]["id"], officer_b))
    assert case_read == decided, (
        "the response body and the persisted row never diverged"
    )

    assert A.data_of(api.get_student(world["student"]["id"], officer_b)) == student
    assert A.data_of(api.get_roster_slot(world["slot"]["id"], officer_b)) == slot
    assert A.data_of(api.get_team(world["team"]["id"], officer_b)) == team


# ==========================================================================
# Instance: registration_publishes_the_fee_the_subsidy_and_both_ledgers_in_the_
#           same_response
# ==========================================================================
def _build_registrable_team_with_one_starter(api):
    """A DRAFT team on a REGISTRATION_OPEN season carrying exactly one ACTIVE
    starter — the single line item PRD §3.6 charges beyond the base fee."""
    world = fx.build_draft_team(api)
    world["slot"] = fx.make_active_starter(
        api,
        world["team"]["id"],
        world["coach"]["id"],
        world["student"],
        slot_role="STARTER",
    )
    return world


def test_registration_publishes_the_fee_and_both_ledgers_in_one_response(api):
    """The register response already carries the pinned fee triple, and the
    district pool and the season counter are reconciled by the first read after.

    PRD §3.6: "The entry fee is the season's `entry_fee_base_cents` plus
    `per_starter_fee_cents` for each of the team's active starters ... The
    subsidy is `subsidy_pct` of each fee line item, rounded half up to the cent
    line by line and then summed ... `subsidy_granted_cents` is deducted from the
    district's `subsidy_pool_cents`, `net_fee_due_cents` is the entry fee minus
    the subsidy, and all three figures are pinned on the team."  PRD §2.4:
    "Percentages apply to each line item and each product is rounded half up to
    the cent before the line items are summed; summing first and rounding once is
    a different and incorrect answer."  PRD §2.9: "A district's
    `subsidy_pool_cents` plus the `subsidy_granted_cents` of every one of its
    non-`WITHDRAWN` teams always equals `subsidy_pool_initial_cents`."

    Design: Corner/consistency_model/registration_publishes_the_fee_the_subsidy_and_both_ledgers_in_the_same_response
    """
    world = _build_registrable_team_with_one_starter(api)
    admin = league_admin_headers()
    coach_headers = make_coach_headers(world["coach"]["id"])
    director = make_athletic_director_headers(world["school"]["id"])

    before = A.data_of(api.get_district(world["district"]["id"], admin))
    A.assert_cents(before["subsidy_pool_cents"], 5_000_000)
    A.assert_cents(before["subsidy_pool_initial_cents"], 5_000_000)
    A.assert_subsidy_conserved(before, 0)

    register_response = api.register_team(world["team"]["id"], {}, coach_headers)
    validate_success(register_response)
    registered = A.data_of(register_response)
    assert registered["status"] == "REGISTERED"
    assert registered["registered_at"] == "2026-08-01T00:00:00.000Z"
    A.assert_cents(registered["entry_fee_cents"], 15_845)
    A.assert_cents(registered["subsidy_granted_cents"], 3_962)
    A.assert_cents(registered["net_fee_due_cents"], 11_883)
    assert registered["subsidy_granted_cents"] != 3_961, (
        "3961 is the sum-then-round answer; §2.4 rounds 12510*0.25 -> 3128 and "
        "3335*0.25 -> 834 line by line"
    )
    assert (
        registered["entry_fee_cents"] - registered["subsidy_granted_cents"]
        == registered["net_fee_due_cents"]
    )

    after = A.data_of(api.get_district(world["district"]["id"], admin))
    A.assert_cents(after["subsidy_pool_cents"], 4_996_038)
    A.assert_cents(after["subsidy_pool_initial_cents"], 5_000_000)
    A.assert_subsidy_conserved(after, registered["subsidy_granted_cents"])

    season = A.data_of(api.get_season(world["season"]["id"], admin))
    assert season["registered_team_count"] == 1

    as_director = A.data_of(api.get_district(world["district"]["id"], director))
    A.assert_cents(as_director["subsidy_pool_cents"], 4_996_038)
    assert as_director == after, "the balance is stored, not converging"

    team_read = A.data_of(api.get_team(world["team"]["id"], coach_headers))
    A.assert_cents(team_read["entry_fee_cents"], 15_845)
    A.assert_cents(team_read["subsidy_granted_cents"], 3_962)
    A.assert_cents(team_read["net_fee_due_cents"], 11_883)
    assert team_read == registered, (
        "the pinned values are persisted, not recomputed per read"
    )
