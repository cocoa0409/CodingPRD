"""Season-policy variants: the two guarantee settlement modes and the two credit splits.

Each test drives one declared variant of a calculation whose inputs are held
identical, so the divergence is attributable to the policy alone.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import GUILD_ADMINISTRATOR_HEADERS, STUDIO_EXECUTIVE_HEADERS

HALF_HOUR_EPISODE = {
    "length_format": "HALF_HOUR",
    "production_unit": "UNIT_B",
    "production_start_date": "2026-11-16T00:00:00Z",
}


def _two_episode_world(api, mode):
    """An ACTIVE room, a ONE_HOUR episode and a HALF_HOUR episode on the other unit."""
    world = X.build_active_room_world(
        api, season_overrides={"guarantee_application_mode": mode}
    )
    world["ep1"] = X.seed_episode(api, world["season_id"], 1)
    world["ep1_id"] = world["ep1"]["id"]
    world["ep2"] = X.seed_episode(api, world["season_id"], 2, **HALF_HOUR_EPISODE)
    world["ep2_id"] = world["ep2"]["id"]
    world["a1"] = X.seed_assignment(
        api, world["ep1_id"], world["w1_id"], world["sr_headers"], "TELEPLAY"
    )
    world["a1_id"] = world["a1"]["id"]
    return world


def test_forward_commit_awards_the_slot_to_the_earliest_created_assignment(api):
    """The earliest-created assignment keeps the seat's only guarantee slot.

    PRD: "Under `FORWARD_COMMIT`, the candidates are the seat's assignments whose status is not `VOID`, ordered by `created_at` ascending; a slot is therefore committed at creation time, the earliest-created assignment wins the guarantee even if a later-created assignment is approved first, and approval performs no re-settlement at all."

    Design: Difficulty/dual_variant_calc/guarantee_forward_commit_awards_slot_to_earliest_created_assignment
    """
    world = _two_episode_world(api, "FORWARD_COMMIT")

    a2 = validate_success(
        api.create_script_assignment(
            world["ep2_id"],
            F.build_script_assignment(
                world["w1_id"], world["ep2"]["version"], "TELEPLAY"
            ),
            world["sr_headers"],
        ),
        201,
    )

    a1 = X.read_assignment(api, world["a1_id"])
    A.assert_assignment_settlement(a1, 3500000, True, 1750000, 1750000)
    A.assert_assignment_settlement(a2, 1750000, False, 0, 1750000)

    seat = X.read_seat(api, world["s1_id"])
    A.assert_field_values(seat, guarantee_slots_consumed=1, guarantee_slots_remaining=0)
    A.assert_guarantee_slots_conserved(seat)

    season = X.read_season(api, world["season_id"])
    A.assert_cents(
        season["script_fee_committed_cents"], 3500000, "script_fee_committed_cents"
    )


def test_forward_commit_writes_the_offset_ledger_row_at_creation_time(api):
    """The slot that applied at creation shows up as a negative ledger row.

    PRD: "Creating an assignment therefore appends a `SCRIPT_FEE_ACCRUAL` entry for the full gross and, when a slot applied at creation, a `GUARANTEE_OFFSET` entry for the negative offset."

    Design: Difficulty/dual_variant_calc/guarantee_forward_commit_awards_slot_to_earliest_created_assignment
    """
    world = _two_episode_world(api, "FORWARD_COMMIT")
    a2 = validate_success(
        api.create_script_assignment(
            world["ep2_id"],
            F.build_script_assignment(
                world["w1_id"], world["ep2"]["version"], "TELEPLAY"
            ),
            world["sr_headers"],
        ),
        201,
    )

    first_rows = X.ledger_for_assignment(api, world["a1_id"])
    assert len(first_rows) == 2, f"Expected 2 ledger rows for the first assignment: {first_rows}"
    assert A.entry_types(first_rows) == ["SCRIPT_FEE_ACCRUAL", "GUARANTEE_OFFSET"]
    A.assert_ledger_sum(first_rows, 1750000)

    second_rows = X.ledger_for_assignment(api, a2["id"])
    assert len(second_rows) == 1, f"Expected 1 ledger row for the second assignment: {second_rows}"
    assert A.entry_types(second_rows) == ["SCRIPT_FEE_ACCRUAL"]
    A.assert_ledger_sum(second_rows, 1750000)

    for row in first_rows + second_rows:
        A.assert_ledger_common_fields(row)

    A.assert_ledger_sum(X.ledger_for_season(api, world["season_id"]), 3500000)


def test_chronological_settlement_moves_the_slot_to_the_first_approved_assignment(api):
    """Approval order, not creation order, decides the slot under the other mode.

    PRD: "Under `CHRONOLOGICAL_ON_ACCEPTANCE`, the candidates are only those assignments whose status is `APPROVED`, ordered by `approved_at` ascending with `created_at` breaking ties; a brand-new assignment therefore carries no slot at creation and its `payable_fee_cents` equals its `gross_fee_cents` in full, and the slot is granted later, at approval time, in approval order."

    Design: Difficulty/dual_variant_calc/guarantee_chronological_on_acceptance_awards_slot_to_first_approved_assignment
    """
    world = _two_episode_world(api, "CHRONOLOGICAL_ON_ACCEPTANCE")
    a2 = X.seed_assignment(
        api,
        world["ep2_id"],
        world["w1_id"],
        world["sr_headers"],
        "TELEPLAY",
        expected_episode_version=world["ep2"]["version"],
    )
    A.assert_assignment_settlement(a2, 1750000, False, 0, 1750000)
    X.deliver_all(api, a2["id"], world["w1_id"])

    approved = validate_success(api.approve_assignment(a2["id"], STUDIO_EXECUTIVE_HEADERS))
    A.assert_field_values(approved, status="APPROVED", approved_by_role="STUDIO_EXECUTIVE")
    A.assert_assignment_settlement(approved, 1750000, True, 875000, 875000)

    a1 = X.read_assignment(api, world["a1_id"])
    A.assert_field_values(a1, status="DRAFTING")
    A.assert_assignment_settlement(a1, 3500000, False, 0, 3500000)

    seat = X.read_seat(api, world["s1_id"])
    A.assert_field_values(seat, guarantee_slots_consumed=1, guarantee_slots_remaining=0)

    season = X.read_season(api, world["season_id"])
    A.assert_cents(
        season["script_fee_committed_cents"], 4375000, "script_fee_committed_cents"
    )


def test_chronological_settlement_records_the_slot_move_as_a_reallocation_row(api):
    """A slot granted at approval time is booked as a signed reallocation delta.

    PRD: "and `GUARANTEE_REALLOCATION` is written when a chronological settlement moves a slot between assignments, carrying the signed delta."

    Design: Difficulty/dual_variant_calc/guarantee_chronological_on_acceptance_awards_slot_to_first_approved_assignment
    """
    world = _two_episode_world(api, "CHRONOLOGICAL_ON_ACCEPTANCE")
    a2 = X.seed_assignment(
        api,
        world["ep2_id"],
        world["w1_id"],
        world["sr_headers"],
        "TELEPLAY",
        expected_episode_version=world["ep2"]["version"],
    )
    X.deliver_all(api, a2["id"], world["w1_id"])
    X.approve_assignment(api, a2["id"])

    second_rows = X.ledger_for_assignment(api, a2["id"])
    assert A.entry_types(second_rows) == [
        "SCRIPT_FEE_ACCRUAL",
        "GUARANTEE_REALLOCATION",
    ], f"Unexpected ledger shape for the approved assignment: {second_rows}"
    A.assert_ledger_sum(second_rows, 875000)
    assert second_rows[1]["amount_cents"] == -875000

    first_rows = X.ledger_for_assignment(api, world["a1_id"])
    assert len(first_rows) == 1, f"The unapproved assignment keeps one row: {first_rows}"
    A.assert_ledger_sum(first_rows, 3500000)

    A.assert_ledger_sum(X.ledger_for_season(api, world["season_id"]), 4375000)


def _three_claim_world(api):
    """Two credit-eligible writers claiming 60 and 30, plus an ineligible claim of 25."""
    world = X.build_approved_assignment_world(api)
    X.seed_second_assignment(api, world)
    world["sb1"] = X.seed_credit_submission(
        api, world["ep1_id"], world["w1_id"], "TELEPLAY_BY", 60
    )
    world["sb1_id"] = world["sb1"]["id"]
    world["sb2"] = X.seed_credit_submission(
        api, world["ep1_id"], world["w2_id"], "STORY_BY", 30
    )
    world["sb2_id"] = world["sb2"]["id"]
    world["sb3"] = X.seed_credit_submission(
        api, world["ep1_id"], world["w3_id"], "WRITTEN_BY", 25
    )
    world["sb3_id"] = world["sb3"]["id"]
    return world


def test_provisional_shares_normalise_the_two_eligible_claims_at_close(api):
    """Claims of 60 and 30 normalise to 67 and 33 and the outsider gets nothing.

    PRD: "The close writes each eligible submission's `provisional_share_pct`, writes the whole writer-id-to-share map into the episode's `provisional_credit_shares`, sets `receives_credit` on each eligible submission according to whether its provisional share is at or above the agreement's `credit_share_threshold_pct` (default 33, an inclusive comparison — a share of exactly 33 earns credit), moves `credit_status` to `SUBMISSIONS_CLOSED` and increments the episode's `version`."

    Design: Difficulty/dual_variant_calc/credit_shares_diverge_between_provisional_claim_split_and_arbitrated_panel_mean
    """
    world = _three_claim_world(api)

    episode = validate_success(
        api.close_credit_submissions(world["ep1_id"], GUILD_ADMINISTRATOR_HEADERS)
    )
    assert episode["provisional_credit_shares"] == {
        world["w1_id"]: 67,
        world["w2_id"]: 33,
    }, f"Unexpected provisional split: {episode['provisional_credit_shares']}"
    A.assert_field_values(episode, credit_status="SUBMISSIONS_CLOSED")

    sb1 = X.read_submission(api, world["sb1_id"])
    A.assert_field_values(
        sb1, status="ELIGIBLE", provisional_share_pct=67, receives_credit=True
    )
    sb2 = X.read_submission(api, world["sb2_id"])
    A.assert_field_values(
        sb2, status="ELIGIBLE", provisional_share_pct=33, receives_credit=True
    )
    sb3 = X.read_submission(api, world["sb3_id"])
    A.assert_field_values(
        sb3,
        status="INELIGIBLE",
        provisional_share_pct=0,
        arbitrated_share_pct=None,
        receives_credit=False,
    )


def test_arbitrated_shares_reweight_the_same_claims_by_panel_mean(api):
    """The identical submissions split 45/55 once the panel's mean supplies the weights.

    PRD: "When `concurrence_pct` is at or above the agreement's `arbitration_concurrence_pct` (default 0.667, inclusive), the panel governs: the arbitration moves to `DETERMINED` and shares are recomputed by the same six-step normalisation as at close, but with each participant's weight taken from their *panel mean* rather than their own claim."

    Design: Difficulty/dual_variant_calc/credit_shares_diverge_between_provisional_claim_split_and_arbitrated_panel_mean
    """
    world = _three_claim_world(api)
    X.close_submissions(api, world["ep1_id"])
    X.convene_panel(api, world)
    X.cast_full_panel(api, world, X.concurring_ballots(world))

    arbitration = validate_success(
        api.determine_arbitration(
            world["arbitration_id"],
            GUILD_ADMINISTRATOR_HEADERS,
            {"policy_override": False},
        )
    )
    A.assert_field_values(
        arbitration,
        status="DETERMINED",
        outcome="REVISED",
        leading_writer_id=world["w2_id"],
        concurrence_pct=1.0,
        participant_writer_ids=[world["w1_id"], world["w2_id"]],
        determined_credit_string="Bram Ochoa & Wanda Cole",
    )

    episode = X.read_episode(api, world["ep1_id"])
    assert episode["final_credit_shares"] == {
        world["w1_id"]: 45,
        world["w2_id"]: 55,
    }, f"Unexpected arbitrated split: {episode['final_credit_shares']}"
    A.assert_field_values(episode, credit_status="DETERMINED")
    assert episode["provisional_credit_shares"] == {
        world["w1_id"]: 67,
        world["w2_id"]: 33,
    }, "The provisional map must survive the determination unchanged"

    A.assert_field_values(
        X.read_submission(api, world["sb1_id"]),
        provisional_share_pct=67,
        arbitrated_share_pct=45,
        receives_credit=True,
    )
    A.assert_field_values(
        X.read_submission(api, world["sb2_id"]),
        provisional_share_pct=33,
        arbitrated_share_pct=55,
        receives_credit=True,
    )
    A.assert_field_values(
        X.read_submission(api, world["sb3_id"]),
        status="INELIGIBLE",
        arbitrated_share_pct=None,
        receives_credit=False,
    )
