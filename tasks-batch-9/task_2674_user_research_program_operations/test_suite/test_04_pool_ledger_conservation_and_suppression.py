"""Money conservation across withdrawals and settlement, and the three-hop
no-show cascade that suppresses a participant and restricts their pool.
"""

import pytest

from test_helpers import (
    RESEARCH_OPS_ADMIN_HEADERS,
    assert_ledger_partition,
    assert_pool_posture_matches_ledger,
    close_fielding,
    complete_session,
    enroll_participant,
    grant_consent,
    invite,
    read_participant,
    read_pool,
    read_recruitment,
    read_study,
    record_no_show,
    schedule,
    screen,
    screening_answers,
    settle,
    setup_fielding_study,
    setup_invited_recruitments,
    setup_two_fielding_studies_sharing_pool,
    validate_paginated,
    withdraw,
)

WITHDRAW_THIRD_REASON = "Participant asked to be removed before screening"
WITHDRAW_SECOND_REASON = "Duplicate outreach in the same week"


def _three_reservations_crossing_the_half_boundary(api):
    """Three named invitations on a 20000-cent budget: 5000, 5000 and then 5250,
    because the third one is priced at an exact 0.50 utilization."""
    return setup_invited_recruitments(
        api,
        invite_count=3,
        participant_count=3,
        incentive_amount_cents=5000,
        target_participant_count=3,
        pool_overrides={
            "incentive_budget_cents": 20000,
            "pool_type": "EXTERNAL_PANEL",
        },
    )


class TestWithdrawalConservesPoolCents:
    """A withdrawal is a transfer, so the four ledger fields stay a partition."""

    def test_withdrawal_returns_the_stored_reserved_cents_not_a_recomputed_amount(self, api):
        """The surcharged 5250 comes back in full, not the 5000 a fresh reservation would cost at the new utilization.

        PRD 2.10: "Withdrawing an invitation moves exactly the same number of cents —
        the recruitment's stored `reserved_cents`, not a recomputed amount — from reserved
        back to available."

        PRD 3.5: "A withdrawal is available from `INVITED`, from `SCREENED_IN` and from
        `SCHEDULED` — three separate transitions into the terminal `WITHDRAWN` state, all
        available to a `Researcher`, `ResearchLead` or `ResearchOpsAdmin`, and all behaving
        identically: the supplied `reason` is stored as `closure_reason`, and the
        recruitment's `incentive_state` moves `RESERVED → RELEASED` with `paid_cents` left
        at 0, returning exactly the recruitment's stored `reserved_cents` — never a
        recomputed figure — out of the pool's `incentive_reserved_cents` and therefore back
        into `incentive_available_cents`."

        Design: Difficulty/compensating_invariant/pool_cents_conserved_when_invitations_are_withdrawn
        """
        ctx = _three_reservations_crossing_the_half_boundary(api)
        third = ctx["recruitments"][2]
        assert third["reserved_cents"] == 5250, (
            f"Expected 5250, got {third['reserved_cents']} for a reservation taken at an "
            "exact 0.50 utilization"
        )

        before = read_pool(ctx["pool"]["id"], api)
        assert_ledger_partition(before)
        assert before["incentive_reserved_cents"] == 15250, (
            f"Expected 15250 reserved, got {before['incentive_reserved_cents']} after "
            "three invitations"
        )
        assert before["incentive_paid_cents"] == 0, (
            f"Expected 0 paid, got {before['incentive_paid_cents']} before any settlement"
        )
        assert before["incentive_available_cents"] == 4750, (
            f"Expected 4750 available, got {before['incentive_available_cents']} after "
            "three invitations"
        )

        withdrawn = withdraw(third["id"], api, reason=WITHDRAW_THIRD_REASON)
        assert withdrawn["status"] == "WITHDRAWN", (
            f"Expected WITHDRAWN, got {withdrawn['status']} after the withdrawal"
        )
        assert withdrawn["incentive_state"] == "RELEASED", (
            f"Expected RELEASED, got {withdrawn['incentive_state']} after the withdrawal"
        )
        assert withdrawn["paid_cents"] == 0, (
            f"Expected 0 paid, got {withdrawn['paid_cents']} on a withdrawn recruitment"
        )
        assert withdrawn["closure_reason"] == WITHDRAW_THIRD_REASON, (
            f"Expected the supplied reason, got {withdrawn['closure_reason']!r} as "
            "closure_reason"
        )

        after = read_pool(ctx["pool"]["id"], api)
        assert_ledger_partition(after)
        assert after["incentive_reserved_cents"] == 10000, (
            f"Expected 10000 reserved, got {after['incentive_reserved_cents']} — exactly "
            "5250 must have been released, not the 5000 a fresh reservation would cost"
        )
        assert after["incentive_available_cents"] == 10000, (
            f"Expected 10000 available, got {after['incentive_available_cents']} after "
            "5250 came back out of reserved"
        )
        assert after["incentive_paid_cents"] == 0, (
            f"Expected 0 paid, got {after['incentive_paid_cents']} — a withdrawal pays "
            "nothing"
        )

    def test_two_withdrawals_keep_the_ledger_a_partition_at_every_instant(self, api):
        """After releasing 5250 and then 5000 the pool is back to a single 5000-cent reservation with the sum intact.

        PRD 2.10: "A participant pool's money is a partition, not a set of independent
        counters. At every observable instant, and for every pool, the following must hold:
        `incentive_available_cents` plus `incentive_reserved_cents` plus
        `incentive_paid_cents` equals `incentive_budget_cents`."

        PRD 2.10: "Consequently every money-moving operation is a transfer. Inviting a
        participant moves cents from available into reserved. Withdrawing an invitation
        moves exactly the same number of cents — the recruitment's stored `reserved_cents`,
        not a recomputed amount — from reserved back to available."

        Design: Difficulty/compensating_invariant/pool_cents_conserved_when_invitations_are_withdrawn
        """
        ctx = _three_reservations_crossing_the_half_boundary(api)
        pool_id = ctx["pool"]["id"]
        assert_ledger_partition(read_pool(pool_id, api))

        withdraw(ctx["recruitments"][2]["id"], api, reason=WITHDRAW_THIRD_REASON)
        midway = read_pool(pool_id, api)
        assert_ledger_partition(midway)
        assert midway["incentive_reserved_cents"] == 10000, (
            f"Expected 10000 reserved, got {midway['incentive_reserved_cents']} after the "
            "first withdrawal"
        )

        withdraw(ctx["recruitments"][1]["id"], api, reason=WITHDRAW_SECOND_REASON)
        final = read_pool(pool_id, api)
        assert_ledger_partition(final)
        assert final["incentive_reserved_cents"] == 5000, (
            f"Expected 5000 reserved, got {final['incentive_reserved_cents']} after both "
            "withdrawals"
        )
        assert final["incentive_available_cents"] == 15000, (
            f"Expected 15000 available, got {final['incentive_available_cents']} after "
            "both withdrawals"
        )
        assert final["incentive_paid_cents"] == 0, (
            f"Expected 0 paid, got {final['incentive_paid_cents']} after two withdrawals"
        )

    def test_withdrawals_leave_the_untouched_invitation_and_the_pool_posture_alone(self, api):
        """The surviving invitation keeps its own 5000-cent reservation and the pool never leaves OPEN.

        PRD 3.2: "Money coming back — a withdrawal, a no-show or a settlement release —
        moves the pool the other way: `CLOSED → RESTRICTED` once utilization is back inside
        the 0.80-to-0.95 band, and `RESTRICTED → OPEN` once utilization is below 0.80 and
        the suppression ratio is at most 0.50."

        PRD 3.4: "A successful invitation writes a recruitment in `status` `INVITED` with
        `incentive_state` `RESERVED` and its `reserved_cents` stored, sets `screen_score`,
        `scheduled_start`, `scheduled_end`, `moderator_user_id`, `actual_duration_min` and
        `closure_reason` to null with `reschedule_count` at 0 and `paid_cents` at 0, and
        copies the study's `guide_version_pinned` onto the recruitment's own
        `guide_version_pinned` so the session is forever tied to the guide version that was
        in force."

        Design: Difficulty/compensating_invariant/pool_cents_conserved_when_invitations_are_withdrawn
        """
        ctx = _three_reservations_crossing_the_half_boundary(api)
        pool_id = ctx["pool"]["id"]

        opening = read_pool(pool_id, api)
        assert opening["status"] == "OPEN", (
            f"Expected OPEN, got {opening['status']} at a peak utilization of 15250/20000"
        )
        assert_pool_posture_matches_ledger(opening)

        withdraw(ctx["recruitments"][2]["id"], api, reason=WITHDRAW_THIRD_REASON)
        midway = read_pool(pool_id, api)
        assert midway["status"] == "OPEN", (
            f"Expected OPEN, got {midway['status']} at a utilization of 10000/20000"
        )
        assert_pool_posture_matches_ledger(midway)

        withdraw(ctx["recruitments"][1]["id"], api, reason=WITHDRAW_SECOND_REASON)
        final = read_pool(pool_id, api)
        assert final["status"] == "OPEN", (
            f"Expected OPEN, got {final['status']} at a utilization of 5000/20000"
        )
        assert_pool_posture_matches_ledger(final)

        survivor = read_recruitment(ctx["recruitments"][0]["id"], api)
        assert survivor["status"] == "INVITED", (
            f"Expected INVITED, got {survivor['status']} for the recruitment nobody "
            "withdrew"
        )
        assert survivor["incentive_state"] == "RESERVED", (
            f"Expected RESERVED, got {survivor['incentive_state']} for the recruitment "
            "nobody withdrew"
        )
        assert survivor["reserved_cents"] == 5000, (
            f"Expected 5000, got {survivor['reserved_cents']} for the first invitation of "
            "an unstressed pool"
        )
        assert survivor["paid_cents"] == 0, (
            f"Expected 0 paid, got {survivor['paid_cents']} before any settlement"
        )


def _three_reservations_with_a_screened_out_third(api):
    """Three invitations of one study: two POWER_USER candidates who will screen in,
    and a CASUAL_USER whose answer sheet scores 50.00 and screens out."""
    ctx = setup_fielding_study(
        api,
        participant_count=2,
        incentive_amount_cents=5000,
        target_participant_count=3,
        pool_overrides={
            "incentive_budget_cents": 20000,
            "pool_type": "EXTERNAL_PANEL",
        },
    )
    pool_id = ctx["pool"]["id"]
    study_id = ctx["study"]["id"]
    casual = enroll_participant(
        pool_id,
        api,
        external_ref=f"casual-{pool_id[:8]}",
        segment="CASUAL_USER",
        locale="en-US",
    )
    ctx["participants"].append(casual)
    for participant in ctx["participants"][:2]:
        grant_consent(
            participant["id"], study_id, api, scopes=["RECORDING"], retention_days=90
        )
    ctx["recruitments"] = [
        invite(study_id, ctx["participants"][0]["id"], api),
        invite(study_id, ctx["participants"][1]["id"], api),
        invite(
            study_id,
            casual["id"],
            api,
            screening_answers=screening_answers(segment="CASUAL_USER"),
        ),
    ]
    ctx["pool"] = read_pool(pool_id, api)
    ctx["study"] = read_study(study_id, api)
    return ctx


def _estimate_then_resolve_every_session(api):
    """Run the advisory estimate while every row is still `INVITED`, then let the
    study finish: one COMPLETED, one NO_SHOW, one SCREENED_OUT, fielding closed."""
    ctx = _three_reservations_with_a_screened_out_third(api)
    pool_id = ctx["pool"]["id"]
    study_id = ctx["study"]["id"]
    settle(pool_id, study_id, "FORWARD_ESTIMATE", api)
    ctx["estimate_pool"] = read_pool(pool_id, api)

    first, second, third = ctx["recruitments"]
    screen(first["id"], api)
    screen(second["id"], api)
    ctx["recruitments"][2] = screen(third["id"], api)
    schedule(first["id"], "2026-08-05T14:00:00Z", "2026-08-05T15:00:00Z", api)
    schedule(second["id"], "2026-08-06T14:00:00Z", "2026-08-06T15:00:00Z", api)
    ctx["recruitments"][0] = complete_session(first["id"], api)
    ctx["recruitments"][1] = record_no_show(
        second["id"], api, reason="Participant did not join the call"
    )
    ctx["study"] = close_fielding(study_id, api)
    return ctx


class TestForwardEstimateVersusChronologicalActual:
    """The advisory mode and the binding mode read the same rows and answer
    different numbers."""

    def test_forward_estimate_sums_open_reservations_and_mutates_no_recruitment(self, api):
        """Three open reservations of 5000, 5000 and 5250 project a 15250-cent estimate while every row stays RESERVED.

        PRD 3.9: "It includes every recruitment whose participant belongs to this pool,
        whose `study_id` equals the supplied one, whose `incentive_state` is `RESERVED`, and
        whose `status` is `INVITED`, `SCREENED_IN`, `SCHEDULED` or `COMPLETED`. The estimate
        is the plain sum of those rows' `reserved_cents` — the assumption being that every
        open recruitment completes at its full reserved amount."

        PRD 3.9: "The figure is written to the pool's `last_estimate_cents` and no
        recruitment row is mutated."

        Design: Difficulty/dual_variant_calc/incentive_forward_estimate_vs_chronological_actual
        """
        ctx = _three_reservations_with_a_screened_out_third(api)
        pool_id = ctx["pool"]["id"]
        reserved_amounts = [row["reserved_cents"] for row in ctx["recruitments"]]
        assert reserved_amounts == [5000, 5000, 5250], (
            f"Expected [5000, 5000, 5250], got {reserved_amounts} — the third invitation "
            "is priced at an exact 0.50 utilization"
        )

        settle(pool_id, ctx["study"]["id"], "FORWARD_ESTIMATE", api)

        pool = read_pool(pool_id, api)
        assert_ledger_partition(pool)
        assert pool["last_estimate_cents"] == 15250, (
            f"Expected a 15250-cent estimate, got {pool['last_estimate_cents']} for three "
            "open reservations of 5000, 5000 and 5250"
        )
        assert pool["incentive_reserved_cents"] == 15250, (
            f"Expected 15250 reserved, got {pool['incentive_reserved_cents']} — the "
            "advisory run moves no money"
        )
        assert pool["incentive_paid_cents"] == 0, (
            f"Expected 0 paid, got {pool['incentive_paid_cents']} — the advisory run moves "
            "no money"
        )
        assert pool["incentive_available_cents"] == 4750, (
            f"Expected 4750 available, got {pool['incentive_available_cents']} — the "
            "advisory run moves no money"
        )
        assert pool["settled_study_ids"] == [], (
            f"Expected no settled study, got {pool['settled_study_ids']} after an advisory "
            "run"
        )

        for index, row in enumerate(ctx["recruitments"]):
            after = read_recruitment(row["id"], api)
            assert after["incentive_state"] == "RESERVED", (
                f"Expected RESERVED, got {after['incentive_state']} on recruitment "
                f"{index + 1} after the advisory run"
            )
            assert after["paid_cents"] == 0, (
                f"Expected 0 paid, got {after['paid_cents']} on recruitment {index + 1} "
                "after the advisory run"
            )
            assert after["status"] == "INVITED", (
                f"Expected INVITED, got {after['status']} on recruitment {index + 1} after "
                "the advisory run"
            )

    def test_chronological_actual_pays_the_completed_row_and_the_screen_out_stipend(self, api):
        """The binding run pays 5000 for the completed session and 200 for the screened-out row, leaving nothing reserved.

        PRD 3.9: "A `COMPLETED` row is entitled to its full `reserved_cents`. A
        `SCREENED_OUT` row is entitled to the screen-out stipend of 200 cents — a token
        payment for the person's time, and the reason a screened-out row keeps its
        reservation all the way to settlement."

        PRD 3.9: "When the payment is greater than zero, the row's `paid_cents` is set to
        it, its `incentive_state` moves `RESERVED → PAID`, and the pool's
        `incentive_paid_cents` rises by the same amount."

        PRD 3.9: "When the walk is done, the settled `study_id` is appended to the pool's
        `settled_study_ids` and the pool's posture is re-derived from its new ledger."

        Design: Difficulty/dual_variant_calc/incentive_forward_estimate_vs_chronological_actual
        """
        ctx = _estimate_then_resolve_every_session(api)
        pool_id = ctx["pool"]["id"]
        study_id = ctx["study"]["id"]
        completed, no_show, screened_out = ctx["recruitments"]

        assert screened_out["status"] == "SCREENED_OUT", (
            f"Expected SCREENED_OUT, got {screened_out['status']} for an answer sheet "
            "naming the wrong segment"
        )
        assert float(screened_out["screen_score"]) == pytest.approx(50.00, abs=0.01), (
            f"Expected a 50.00 screen score, got {screened_out['screen_score']} for a "
            "wrong segment, right locale and two target hits"
        )

        settle(pool_id, study_id, "CHRONOLOGICAL_ACTUAL", api)

        paid_row = read_recruitment(completed["id"], api)
        assert paid_row["incentive_state"] == "PAID", (
            f"Expected PAID, got {paid_row['incentive_state']} for the completed session"
        )
        assert paid_row["paid_cents"] == 5000, (
            f"Expected 5000 paid, got {paid_row['paid_cents']} for a completed session "
            "entitled to its full reservation"
        )

        stipend_row = read_recruitment(screened_out["id"], api)
        assert stipend_row["incentive_state"] == "PAID", (
            f"Expected PAID, got {stipend_row['incentive_state']} for the screened-out row"
        )
        assert stipend_row["paid_cents"] == 200, (
            f"Expected the 200-cent stipend, got {stipend_row['paid_cents']} for the "
            "screened-out row"
        )

        pool = read_pool(pool_id, api)
        assert_ledger_partition(pool)
        assert pool["incentive_paid_cents"] == 5200, (
            f"Expected 5200 paid, got {pool['incentive_paid_cents']} for a 5000-cent "
            "payment plus a 200-cent stipend"
        )
        assert pool["incentive_reserved_cents"] == 0, (
            f"Expected 0 reserved, got {pool['incentive_reserved_cents']} once the walk "
            "released every candidate row"
        )
        assert pool["incentive_available_cents"] == 14800, (
            f"Expected 14800 available, got {pool['incentive_available_cents']} after "
            "paying 5200 out of a 20000-cent budget"
        )
        assert pool["settled_study_ids"] == [study_id], (
            f"Expected [{study_id}], got {pool['settled_study_ids']} after the binding run"
        )
        assert_pool_posture_matches_ledger(pool)

        forfeited = read_recruitment(no_show["id"], api)
        assert forfeited["incentive_state"] == "FORFEITED", (
            f"Expected FORFEITED, got {forfeited['incentive_state']} for the no-show, which "
            "the binding run must leave alone"
        )
        assert forfeited["paid_cents"] == 0, (
            f"Expected 0 paid, got {forfeited['paid_cents']} for a forfeited no-show"
        )

    def test_the_two_modes_disagree_on_the_same_recruitment_set(self, api):
        """The same three recruitments project 15250 cents and actually pay 5200, a divergence of 10050.

        PRD 3.9: "Its candidate set is wider than the estimate's: every recruitment whose
        participant belongs to this pool, whose `study_id` matches, and whose
        `incentive_state` is `RESERVED`, regardless of `status`. Screened-out rows therefore
        enter the binding run even though they never entered the estimate, which is exactly
        why the two modes disagree."

        PRD 3.9: "Rows whose `incentive_state` is already `FORFEITED` from a no-show, or
        already `RELEASED` from a withdrawal, are outside both modes' candidate sets — their
        money was accounted for when the session fell through."

        PRD 2.10: "`last_estimate_cents` is the one exception to the partition and is
        explicitly outside it: it is an advisory projection written by a non-binding
        settlement run and it never moves money."

        Design: Difficulty/dual_variant_calc/incentive_forward_estimate_vs_chronological_actual
        """
        ctx = _estimate_then_resolve_every_session(api)
        pool_id = ctx["pool"]["id"]
        estimate = ctx["estimate_pool"]["last_estimate_cents"]
        assert estimate == 15250, (
            f"Expected a 15250-cent forward estimate, got {estimate}"
        )
        assert_ledger_partition(ctx["estimate_pool"])

        settle(pool_id, ctx["study"]["id"], "CHRONOLOGICAL_ACTUAL", api)

        pool = read_pool(pool_id, api)
        assert_ledger_partition(pool)
        actual = pool["incentive_paid_cents"]
        assert actual == 5200, (
            f"Expected 5200 actually paid, got {actual} from the binding run"
        )
        assert estimate - actual == 10050, (
            f"Expected the two variants to diverge by 10050 cents, got "
            f"{estimate - actual} (estimate {estimate}, actual {actual})"
        )
        assert pool["last_estimate_cents"] == estimate, (
            f"Expected the advisory projection to survive the binding run at {estimate}, "
            f"got {pool['last_estimate_cents']}"
        )


def _one_participant_scheduled_in_a_second_study_after_one_strike(api):
    """A single-participant pool where the person already carries one no-show strike
    from study A and is booked into a session of study B."""
    ctx = setup_two_fielding_studies_sharing_pool(
        api,
        participant_count=1,
        pool_overrides={
            "incentive_budget_cents": 100000,
            "contact_cap_per_window": 2,
        },
    )
    pool_id = ctx["pool"]["id"]
    participant_id = ctx["participants"][0]["id"]
    study_a = ctx["studies"][0]["id"]
    study_b = ctx["studies"][1]["id"]

    grant_consent(participant_id, study_a, api, scopes=["RECORDING"], retention_days=60)
    first = invite(study_a, participant_id, api)
    screen(first["id"], api)
    schedule(first["id"], "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z", api)
    ctx["recruitment_a"] = record_no_show(first["id"], api, reason="First missed session")

    grant_consent(participant_id, study_b, api, scopes=["RECORDING"], retention_days=60)
    second = invite(study_b, participant_id, api)
    screen(second["id"], api)
    ctx["recruitment_b"] = schedule(
        second["id"], "2026-08-07T09:00:00Z", "2026-08-07T10:00:00Z", api
    )

    ctx["participant"] = read_participant(participant_id, api)
    ctx["pool"] = read_pool(pool_id, api)
    return ctx


class TestNoShowCascadeSuppressesAndRestricts:
    """A second no-show forfeits money, suppresses the person and restricts the pool."""

    def test_no_show_forfeits_the_reservation_and_hands_the_cents_back_to_available(self, api):
        """Hop one and hop two: the reservation is forfeited and exactly its cents leave the pool's reserved column.

        PRD 3.5: "Hop one: the recruitment's `incentive_state` moves
        `RESERVED → FORFEITED` with `paid_cents` left at 0, and the participant's
        `no_show_strikes` is incremented by 1."

        PRD 3.5: "Hop two: the forfeiture removes exactly `reserved_cents` from the pool's
        `incentive_reserved_cents`, which re-derives the pool's posture and may take it
        `CLOSED → RESTRICTED` or `RESTRICTED → OPEN`."

        Design: Difficulty/transitive_cascade/no_show_three_hop_suppression_and_pool_posture
        """
        ctx = _one_participant_scheduled_in_a_second_study_after_one_strike(api)
        pool_id = ctx["pool"]["id"]

        assert ctx["participant"]["no_show_strikes"] == 1, (
            f"Expected 1 strike, got {ctx['participant']['no_show_strikes']} before the "
            "second no-show"
        )
        assert ctx["participant"]["contacts_in_window"] == 2, (
            f"Expected 2 contacts in the window, got "
            f"{ctx['participant']['contacts_in_window']} after two invitations"
        )
        assert ctx["participant"]["status"] == "COOLDOWN", (
            f"Expected COOLDOWN, got {ctx['participant']['status']} at one strike and "
            "contacts equal to the cap of 2"
        )

        before = read_pool(pool_id, api)
        assert_ledger_partition(before)
        assert before["status"] == "OPEN", (
            f"Expected OPEN, got {before['status']} before anyone was suppressed"
        )
        assert before["suppressed_participant_count"] == 0, (
            f"Expected 0 suppressed, got {before['suppressed_participant_count']} before "
            "the second strike"
        )
        assert before["incentive_reserved_cents"] == 5000, (
            f"Expected 5000 reserved, got {before['incentive_reserved_cents']} for the one "
            "live invitation"
        )

        after_row = record_no_show(
            ctx["recruitment_b"]["id"], api, reason="Second missed session"
        )
        assert after_row["status"] == "NO_SHOW", (
            f"Expected NO_SHOW, got {after_row['status']} after the no-show"
        )
        assert after_row["incentive_state"] == "FORFEITED", (
            f"Expected FORFEITED, got {after_row['incentive_state']} after the no-show"
        )
        assert after_row["paid_cents"] == 0, (
            f"Expected 0 paid, got {after_row['paid_cents']} on a forfeited recruitment"
        )

        after = read_pool(pool_id, api)
        assert_ledger_partition(after)
        assert after["incentive_reserved_cents"] == 0, (
            f"Expected 0 reserved, got {after['incentive_reserved_cents']} once the "
            "forfeiture removed the 5000-cent reservation"
        )
        assert after["incentive_available_cents"] == 100000, (
            f"Expected the whole 100000-cent budget back as available, got "
            f"{after['incentive_available_cents']}"
        )
        assert after["incentive_paid_cents"] == 0, (
            f"Expected 0 paid, got {after['incentive_paid_cents']} — a no-show pays nothing"
        )

    def test_the_second_strike_suppresses_the_participant_and_restricts_the_pool(self, api):
        """Hops two and three: the strike increment suppresses the person, and that suppression alone restricts the pool.

        PRD 3.5: "Hop three: the incremented `no_show_strikes` re-derives the
        participant's contact posture, and at two strikes moves them into `SUPPRESSED`, which
        increments the pool's `suppressed_participant_count` and re-runs the pool's posture
        derivation a second time."

        PRD 3.2: "`SUPPRESSED` is absorbing: whether the participant was `ELIGIBLE` or in
        `COOLDOWN` when their second strike landed, the transition into `SUPPRESSED` is
        one-way, it increments the pool's `suppressed_participant_count` and then re-runs the
        pool's posture derivation, and every future invitation naming them is refused with
        `ERR_PARTICIPANT_SUPPRESSED`."

        PRD 3.2: "Note the asymmetry between the two thresholds — utilization is compared
        inclusively at its band edges, whereas the suppression ratio must strictly exceed one
        half, so a pool with exactly half its participants suppressed and low utilization
        stays `OPEN`."

        Design: Difficulty/transitive_cascade/no_show_three_hop_suppression_and_pool_posture
        """
        ctx = _one_participant_scheduled_in_a_second_study_after_one_strike(api)
        pool_id = ctx["pool"]["id"]
        participant_id = ctx["participants"][0]["id"]

        record_no_show(ctx["recruitment_b"]["id"], api, reason="Second missed session")

        participant = read_participant(participant_id, api)
        assert participant["no_show_strikes"] == 2, (
            f"Expected 2 strikes, got {participant['no_show_strikes']} after the second "
            "no-show"
        )
        assert participant["status"] == "SUPPRESSED", (
            f"Expected SUPPRESSED, got {participant['status']} at two strikes"
        )

        pool = read_pool(pool_id, api)
        assert_ledger_partition(pool)
        assert pool["suppressed_participant_count"] == 1, (
            f"Expected 1 suppressed participant, got "
            f"{pool['suppressed_participant_count']} after the suppression"
        )
        assert pool["participant_count"] == 1, (
            f"Expected 1 participant, got {pool['participant_count']} in this pool"
        )
        assert pool["status"] == "RESTRICTED", (
            f"Expected RESTRICTED, got {pool['status']} at a suppression ratio of 1.0 and "
            "a utilization of 0.00"
        )
        assert_pool_posture_matches_ledger(pool)

    def test_the_suppression_is_durable_in_the_pool_participant_listing(self, api):
        """The suppressed person is the only row a SUPPRESSED-filtered pool listing returns, and the earlier no-show is untouched.

        PRD 3.2: "A pool's participants can be listed with optional `status` and `segment`
        filters, ordered by `created_at` ascending."

        PRD 3.5: "Hop three: the incremented `no_show_strikes` re-derives the
        participant's contact posture, and at two strikes moves them into `SUPPRESSED`, which
        increments the pool's `suppressed_participant_count` and re-runs the pool's posture
        derivation a second time."

        Design: Difficulty/transitive_cascade/no_show_three_hop_suppression_and_pool_posture
        """
        ctx = _one_participant_scheduled_in_a_second_study_after_one_strike(api)
        pool_id = ctx["pool"]["id"]
        participant_id = ctx["participants"][0]["id"]

        record_no_show(ctx["recruitment_b"]["id"], api, reason="Second missed session")

        rows, _meta = validate_paginated(
            api.list_pool_participants(
                pool_id, RESEARCH_OPS_ADMIN_HEADERS, {"status": "SUPPRESSED"}
            )
        )
        assert len(rows) == 1, (
            f"Expected exactly one suppressed participant, got {len(rows)} rows"
        )
        assert rows[0]["id"] == participant_id, (
            f"Expected the suppressed row to be {participant_id}, got {rows[0]['id']}"
        )

        earlier = read_recruitment(ctx["recruitment_a"]["id"], api)
        assert earlier["status"] == "NO_SHOW", (
            f"Expected the first no-show to stay NO_SHOW, got {earlier['status']}"
        )
        assert earlier["incentive_state"] == "FORFEITED", (
            f"Expected the first no-show to stay FORFEITED, got "
            f"{earlier['incentive_state']}"
        )
        assert_ledger_partition(read_pool(pool_id, api))
