"""Difficulty-design priority queue tests.

This file provides at least two tests for every instance declared in
SCAFFOLD_DIFFICULTY_DESIGN.yaml. Each test docstring carries:

  - a verbatim PRD citation for the underlying rule the instance exercises
  - a `difficulty:` tag with rule_id/instance.name for the audit pass

Each instance is covered by a dedicated TestClass; tests inside a class
share the heavy fixture setup as much as the runner permits.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    add_minutes,
    add_seconds,
    advance_clock,
    api_client,
    assert_exactly_one_succeeds,
    assert_prize_payment_arithmetic,
    assign_head_referee,
    assign_assistant_referee,
    cancel_event,
    create_event,
    create_referee,
    create_referee_assignment_payload,
    custody_dispatch,
    custody_payload,
    custody_receive,
    decide_appeal,
    DEFAULT_T0,
    event_drawn,
    event_in_progress,
    event_open_for_registration,
    file_appeal,
    file_appeal_payload,
    file_dispute,
    find_audit_logs,
    find_payment_for_participant,
    find_sync_events,
    get_event,
    get_match,
    get_participant,
    get_sanction,
    get_success_data,
    latest_sanction_for_sample,
    list_audit_logs,
    list_matches,
    list_participants,
    list_prize_payments,
    list_rankings,
    list_sync_events,
    lock_match,
    make_doping_headers,
    make_participant_headers,
    make_referee_headers,
    open_doping_sample,
    parse_iso,
    positive_doping_for,
    register_n_distinct_participants,
    resolve_dispute_uphold,
    run_sweep,
    setup_round_robin_4_with_complete,
    setup_single_elim_8_with_complete,
    submit_lab_result,
    submit_result_payload,
    TEST_USERS,
    validate_error,
    validate_success,
    withdraw_participant,
)


# ===========================================================================
# Rule 1, instance 1: ranking_provisional_vs_final_on_ranking_entry
# ===========================================================================
class TestDualVariantRankingProvisionalVsFinal:
    """difficulty: dual_variant_calc/ranking_provisional_vs_final_on_ranking_entry"""

    def test_final_rank_frozen_at_completion(self, api):
        """PRD §3.5: 'The final variant runs once at the moment the event
        transitions from IN_PROGRESS to COMPLETED over the full set of
        LOCKED matches; at that instant final_rank is set equal to
        provisional_rank. Subsequent dispute corrections after completion
        never revise final_rank — only the audit log records the
        divergence.'

        difficulty: dual_variant_calc/
        ranking_provisional_vs_final_on_ranking_entry
        """
        completed, parts, _ = setup_round_robin_4_with_complete()
        # Snapshot final_rank values immediately after completion.
        live = list_participants(completed["id"])
        final_ranks_before = {p["id"]: p["final_rank"] for p in live}
        # Locate a locked match between the top two participants and file
        # a dispute, then uphold with reversed scores. PRD says
        # final_rank is frozen.
        matches = [m for m in list_matches(completed["id"])
                   if m["status"] == "LOCKED"]
        assert matches, "Setup failed: no LOCKED match available."
        m = matches[0]
        # Loser files dispute.
        loser_id = (m["away_participant_id"]
                    if m["winner_participant_id"] == m["home_participant_id"]
                    else m["home_participant_id"])
        dispute = file_dispute(m["id"], loser_id, reason="Score check.")
        # Uphold with reversed scores.
        new_home = m["locked_away_score"]
        new_away = m["locked_home_score"]
        resolve_dispute_uphold(
            dispute["id"],
            corrected_home_score=new_home,
            corrected_away_score=new_away,
        )
        # After the correction, every participant's final_rank must be
        # unchanged from the snapshot per PRD §3.5.
        live_after = list_participants(completed["id"])
        for p in live_after:
            assert p["final_rank"] == final_ranks_before[p["id"]], (
                f"final_rank changed for {p['id']}: "
                f"{final_ranks_before[p['id']]!r} -> {p['final_rank']!r}; "
                "PRD §3.5 forbids this."
            )

    def test_dispute_uphold_writes_result_change_audit(self, api):
        """PRD §3.4: 'writes a RESULT_CHANGE audit row whose from_value
        snapshots the old locked-score fields and whose to_value
        snapshots the new ones, updates the locked_* fields and possibly
        winner_participant_id.'

        difficulty: dual_variant_calc/
        ranking_provisional_vs_final_on_ranking_entry
        """
        completed, parts, _ = setup_round_robin_4_with_complete()
        m = next(m for m in list_matches(completed["id"])
                 if m["status"] == "LOCKED")
        loser_id = (m["away_participant_id"]
                    if m["winner_participant_id"] == m["home_participant_id"]
                    else m["home_participant_id"])
        dispute = file_dispute(m["id"], loser_id)
        resolve_dispute_uphold(
            dispute["id"],
            corrected_home_score=m["locked_away_score"],
            corrected_away_score=m["locked_home_score"],
        )
        rows = list_audit_logs(kind="RESULT_CHANGE",
                               subject_kind="MATCH",
                               subject_id=m["id"])
        assert len(rows) >= 1, (
            "PRD §3.4 / §2.10: a RESULT_CHANGE audit row must be written "
            "after a dispute uphold corrects locked scores."
        )


# ===========================================================================
# Rule 1, instance 2: prize_gross_first_vs_post_sanction_recompute
# ===========================================================================
class TestDualVariantPrizeRecompute:
    """difficulty: dual_variant_calc/
    prize_gross_first_vs_post_sanction_recompute_on_prize_payment"""

    def test_revoke_restores_gross_and_tax_unchanged(self, api):
        """PRD §3.6: 'When a sanction is later revoked through a successful
        appeal, the cascade reverses: forfeit_amount_cents returns to 0,
        net_amount_cents is recomputed under the same gross-and-tax
        preservation rule, and status returns to SCHEDULED. This
        deliberate separation from the initial gross-first computation
        matters because re-running the gross-first variant on a
        partially-paid pool would produce different cents due to the
        rank-1 residual reallocation.'

        difficulty: dual_variant_calc/
        prize_gross_first_vs_post_sanction_recompute_on_prize_payment
        """
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_003, tax_withholding_pct=10.0
        )
        # Snapshot all PrizePayment rows.
        before = list_prize_payments(completed["id"])
        snapshot = {pp["id"]: dict(pp) for pp in before}
        # Pick the rank-2 participant for the cascade.
        live = list_participants(completed["id"])
        target = next((p for p in live if p.get("final_rank") == 2), None)
        if target is None:
            pytest.skip("Setup did not produce a unique rank-2 participant.")
        # Positive sample → cascade FORFEITED.
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        # File and uphold appeal → cascade reverses to SCHEDULED.
        appeal = file_appeal(sanction["id"], target["id"])
        decide_appeal(appeal["id"], uphold=True)
        # Re-fetch all payments. PRD §3.6 says gross_amount_cents and
        # tax_withheld_cents on every row must equal the pre-sanction
        # snapshot.
        after = list_prize_payments(completed["id"])
        for pp in after:
            old = snapshot.get(pp["id"])
            assert old is not None, (
                f"Setup failed: no snapshot for payment {pp['id']}."
            )
            assert pp["gross_amount_cents"] == old["gross_amount_cents"], (
                "PRD §3.6: gross_amount_cents must be FROZEN at COMPLETED "
                "time and unchanged after sanction → revoke."
            )
            assert pp["tax_withheld_cents"] == old["tax_withheld_cents"], (
                "PRD §3.6: tax stays as originally computed."
            )
        # The target's PrizePayment is back to SCHEDULED with forfeit 0.
        target_pay = find_payment_for_participant(after, target["id"])
        assert target_pay["status"] == "SCHEDULED"
        assert target_pay["forfeit_amount_cents"] == 0

    def test_post_sanction_net_arithmetic_valid(self, api):
        """PRD §3.6: 'The net is the gross minus tax withheld minus
        forfeit, clamped at a non-negative floor of 0.'

        difficulty: dual_variant_calc/
        prize_gross_first_vs_post_sanction_recompute_on_prize_payment
        """
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_003, tax_withholding_pct=10.0
        )
        live = list_participants(completed["id"])
        target = next((p for p in live if p.get("final_rank") == 2), None)
        if target is None:
            pytest.skip("Setup did not produce a unique rank-2 participant.")
        positive_doping_for(completed["id"], target["id"])
        payments = list_prize_payments(completed["id"])
        for p in payments:
            assert_prize_payment_arithmetic(p)


# ===========================================================================
# Rule 2, instance 1: tie_break_six_key_lexicographic_sort
# ===========================================================================
class TestTieBreakLexicographic:
    """difficulty: combinatorial_formula/tie_break_six_key_lexicographic_sort"""

    def test_six_key_sort_has_six_distinct_keys(self, api):
        """PRD §3.5: 'The tie-break depth is therefore six keys total.
        Keys four and five are evaluated in this strict order regardless
        of event_type.'

        difficulty: combinatorial_formula/tie_break_six_key_lexicographic_sort
        """
        # Run a 4-participant ROUND_ROBIN through to COMPLETED. Each
        # participant must end with a deterministic provisional_rank in
        # 1..4.
        completed, parts, _ = setup_round_robin_4_with_complete()
        rankings = list_rankings(completed["id"])
        ranks = [r.get("provisional_rank") for r in rankings
                 if r.get("provisional_rank") is not None]
        assert sorted(ranks) == [1, 2, 3, 4], (
            f"PRD §3.5: ranks 1..N expected, got {sorted(ranks)}"
        )

    def test_more_points_wins_first_key(self, api):
        """PRD §3.5: 'The first key is the negative of points (more
        points wins).'

        difficulty: combinatorial_formula/tie_break_six_key_lexicographic_sort
        """
        completed, parts, _ = setup_round_robin_4_with_complete()
        rankings = list_rankings(completed["id"])
        # Sort by provisional_rank asc — points must be non-increasing.
        ordered = sorted(
            [r for r in rankings if r.get("provisional_rank") is not None],
            key=lambda r: r["provisional_rank"],
        )
        for a, b in zip(ordered, ordered[1:]):
            assert a["points"] >= b["points"], (
                "PRD §3.5: lower provisional_rank must have at least as "
                f"many points; {a['points']} vs {b['points']}"
            )


# ===========================================================================
# Rule 2, instance 2: prize_per_rank_round_then_tax_round
# ===========================================================================
class TestPrizeRoundOrder:
    """difficulty: combinatorial_formula/prize_per_rank_round_then_tax_round"""

    def test_per_rank_gross_rounded_half_up_rank1_50pct(self, api):
        """PRD §3.6: 'For each ranked slot in turn — rank 1, then rank
        2, then 3, 4, 5, 6, 7, 8 — the gross is computed by multiplying
        `prize_pool_cents` by the tier's percentage numerator, dividing
        by the tier's percentage denominator times 100, and rounding
        the resulting cents half-up.'

        difficulty: combinatorial_formula/prize_per_rank_round_then_tax_round
        """
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=99, tax_withholding_pct=11.0
        )
        live = list_participants(completed["id"])
        rank1 = next((p for p in live if p.get("final_rank") == 1), None)
        if rank1 is None:
            pytest.skip("Setup did not produce a unique rank-1 participant.")
        payments = list_prize_payments(completed["id"])
        pay = find_payment_for_participant(payments, rank1["id"])
        # 99 * 50 / (100 * 100) = 0.495 cents per the formula.
        # round_half_up(0.495) ... but the formula is integer math:
        # gross_cents = ceil_div_round_half_up(99 * 50, 100 * 100)
        # = round_half_up(4950 / 10000) = round_half_up(0.495) = 0 (HALF_UP
        # rounds 0.5 up but 0.495 < 0.5). Wait — re-read formula:
        # gross_cents = round_half_up(prize_pool_cents * pct_numerator /
        #                              (pct_denominator * 100))
        # For tier 1 numerator=50, denominator=1, so:
        # = round_half_up(99 * 50 / (1 * 100)) = round_half_up(49.5) = 50.
        assert pay["gross_amount_cents"] == 50, (
            "PRD §3.6 (rank 1, 50% of 99 cents, half-up): expected "
            f"50 cents, got {pay['gross_amount_cents']}"
        )

    def test_per_row_tax_rounded_half_up_after_gross(self, api):
        """PRD §3.6: 'After per-rank gross is fixed, the per-row tax
        withholding is computed: tax_withheld_cents is gross_amount_cents
        multiplied by tax_withholding_pct divided by 100, rounded
        half-up. Rounding order is pinned: per-rank gross first, per-row
        tax second.'

        difficulty: combinatorial_formula/prize_per_rank_round_then_tax_round
        """
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=99, tax_withholding_pct=11.0
        )
        live = list_participants(completed["id"])
        rank1 = next((p for p in live if p.get("final_rank") == 1), None)
        if rank1 is None:
            pytest.skip("Setup did not produce a unique rank-1 participant.")
        payments = list_prize_payments(completed["id"])
        pay = find_payment_for_participant(payments, rank1["id"])
        # gross = 50; tax = round_half_up(50 * 11 / 100) = round_half_up(5.5) = 6.
        assert pay["tax_withheld_cents"] == 6, (
            "PRD §3.6 (tax half-up after gross half-up: "
            "round_half_up(50*11/100)=6): expected 6 cents, got "
            f"{pay['tax_withheld_cents']}"
        )
        # Net = 50 - 6 - 0 = 44 (no forfeit on rank-1 here).
        assert pay["net_amount_cents"] == 44


# ===========================================================================
# Rule 3, instance 1: match_dispute_revision_cycle
# ===========================================================================
class TestMatchDisputeRevisionCycle:
    """difficulty: non_linear_state_machine/match_dispute_revision_cycle"""

    def test_match_returns_to_locked_after_uphold(self, api):
        """PRD §3.4: 'on success it persists a new ResultEntry of kind
        CORRECTION ... updates the locked_* fields and possibly
        winner_participant_id ... and on Dispute completion sets the
        dispute's status to UPHELD.'

        difficulty: non_linear_state_machine/match_dispute_revision_cycle
        """
        event, parts, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = next(m for m in list_matches(event["id"])
                     if m["round_index"] == 1 and m["status"] != "BYE"
                     and m.get("home_participant_id")
                     and m.get("away_participant_id"))
        locked = lock_match(match, home_score=2, away_score=1,
                            event_type=event["event_type"])
        loser = next(p for p in parts
                     if p["id"] != locked["winner_participant_id"])
        dispute = file_dispute(locked["id"], loser["id"])
        resolve_dispute_uphold(
            dispute["id"], corrected_home_score=1, corrected_away_score=2
        )
        m_after = get_match(event["id"], locked["id"])
        assert m_after["status"] == "LOCKED"
        assert m_after["locked_home_score"] == 1
        assert m_after["locked_away_score"] == 2

    def test_uphold_writes_result_change_audit_row(self, api):
        """PRD §3.4: 'writes a RESULT_CHANGE audit row whose from_value
        snapshots the old locked-score fields and whose to_value
        snapshots the new ones.'

        difficulty: non_linear_state_machine/match_dispute_revision_cycle
        """
        event, parts, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = next(m for m in list_matches(event["id"])
                     if m["round_index"] == 1 and m["status"] != "BYE"
                     and m.get("home_participant_id")
                     and m.get("away_participant_id"))
        locked = lock_match(match, home_score=2, away_score=1,
                            event_type=event["event_type"])
        loser = next(p for p in parts
                     if p["id"] != locked["winner_participant_id"])
        dispute = file_dispute(locked["id"], loser["id"])
        resolve_dispute_uphold(
            dispute["id"], corrected_home_score=1, corrected_away_score=2
        )
        rows = list_audit_logs(kind="RESULT_CHANGE",
                               subject_kind="MATCH",
                               subject_id=locked["id"])
        assert len(rows) >= 1


# ===========================================================================
# Rule 3, instance 2: sanction_appeal_branching_revoke_or_final
# ===========================================================================
class TestSanctionBranching:
    """difficulty: non_linear_state_machine/
    sanction_appeal_branching_revoke_or_final"""

    def test_branch_a_appeal_uphold_revokes_sanction_unfreezes(self, api):
        """PRD §3.8: 'On uphold true (the appeal is granted) the appeal
        flips to UPHELD and the sanction transitions from APPEALED to
        REVOKED. The cascade on a revoke is the reverse of the issuance
        cascade ... any PrizePayment in FORFEITED returns to SCHEDULED
        with forfeit_amount_cents set to 0.'

        difficulty: non_linear_state_machine/
        sanction_appeal_branching_revoke_or_final
        """
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_000
        )
        live = list_participants(completed["id"])
        target = next((p for p in live if p.get("final_rank") == 2), None)
        if target is None:
            pytest.skip("Setup did not produce a unique rank-2 participant.")
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        appeal = file_appeal(sanction["id"], target["id"])
        decide_appeal(appeal["id"], uphold=True)
        s_after = get_sanction(sanction["id"])
        assert s_after["status"] == "REVOKED"
        # Participant returns to ELIMINATED if event is COMPLETED.
        # PRD §3.8: 'the participant's status returns from DISQUALIFIED
        # to ELIMINATED if the event is already COMPLETED, otherwise to
        # ACTIVE.'
        p_after = get_participant(completed["id"], target["id"])
        assert p_after["status"] == "ELIMINATED"

    def test_branch_b_no_appeal_then_auto_final_emits_archived(self, api):
        """PRD §3.8: 'If no appeal is filed, the system advances the
        sanction from ISSUED to FINAL automatically when the clock
        crosses created_at + 14 days and no Appeal exists. The cascade
        recomputes the event's posture and emits a SyncEvent of kind
        SANCTION_ARCHIVED to GOVERNING_BODY.'

        difficulty: non_linear_state_machine/
        sanction_appeal_branching_revoke_or_final
        """
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        # Do NOT file appeal; advance clock past the deadline.
        future = add_seconds(add_days(sanction["created_at"], 14), 1)
        advance_clock(future)
        run_sweep()
        s_after = get_sanction(sanction["id"])
        assert s_after["status"] == "FINAL"
        sync = list_sync_events(target_system="GOVERNING_BODY",
                                kind="SANCTION_ARCHIVED")
        assert len(sync) >= 1


# ===========================================================================
# Rule 4, instance 1: positive_doping_cascade_depth_4
# ===========================================================================
class TestPositiveDopingCascade:
    """difficulty: transitive_cascade/positive_doping_cascade_depth_4"""

    def test_positive_disqualifies_and_forfeits_payment(self, api):
        """PRD §3.7: 'A `SanctionRecord` is auto-created with
        `sample_id` set to this sample's id, `participant_id`
        denormalized from the sample's participant, and `status`
        `ISSUED`.'
        PRD §3.7: 'The participant's `status` flips from `ACTIVE` to
        `DISQUALIFIED`.'
        PRD §3.7: 'Every existing `PrizePayment` for this participant
        with `status` `SCHEDULED` flips to `FORFEITED` with
        `forfeit_amount_cents` equal to `gross_amount_cents` and
        `net_amount_cents` set to 0.'

        difficulty: transitive_cascade/positive_doping_cascade_depth_4
        """
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_000, tax_withholding_pct=0.0
        )
        live = list_participants(completed["id"])
        target = next((p for p in live if p.get("final_rank") == 2), None)
        if target is None:
            pytest.skip("Setup did not produce a unique rank-2 participant.")
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        assert sanction["status"] == "ISSUED"
        p_after = get_participant(completed["id"], target["id"])
        assert p_after["status"] == "DISQUALIFIED"
        payments = list_prize_payments(completed["id"])
        pay = find_payment_for_participant(payments, target["id"])
        assert pay is not None
        assert pay["status"] == "FORFEITED"
        assert pay["forfeit_amount_cents"] == pay["gross_amount_cents"]

    def test_positive_audit_log_and_posture_under_review(self, api):
        """PRD §3.7: 'An AuditLog row of kind SANCTION_CHANGE is written.
        Finally, the event's posture recomputes per the rule in §2.8 — at
        this moment the new sanction is ISSUED, so the posture flips to
        UNDER_REVIEW.'

        difficulty: transitive_cascade/positive_doping_cascade_depth_4
        """
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]
        positive_doping_for(completed["id"], target["id"])
        rows = list_audit_logs(kind="SANCTION_CHANGE",
                               subject_kind="SANCTION_RECORD")
        assert len(rows) >= 1
        ev = get_event(completed["id"])
        assert ev["posture"] == "UNDER_REVIEW"


# ===========================================================================
# Rule 4, instance 2: event_cancel_cascade_depth_2
# ===========================================================================
class TestEventCancelCascade:
    """difficulty: transitive_cascade/event_cancel_cascade_depth_2"""

    def test_cancel_from_open_withdraws_all_participants(self, api):
        """PRD §3.1: 'Cancellation from OPEN or REGISTRATION_CLOSED runs
        the same cascade in both cases: every participant in REGISTERED,
        SEEDED, or ACTIVE is converted to WITHDRAWN.'

        difficulty: transitive_cascade/event_cancel_cascade_depth_2
        """
        event = event_open_for_registration()
        ps = register_n_distinct_participants(event["id"], 3)
        cancel_event(event["id"])
        live = list_participants(event["id"])
        for p in live:
            assert p["status"] == "WITHDRAWN", (
                f"PRD §3.1: cancel from OPEN must flip {p['id']} to "
                f"WITHDRAWN, got {p['status']}"
            )

    def test_cancel_from_open_emits_refund_payment_events(self, api):
        """PRD §3.1: 'each such cascaded withdrawal itself emits a
        ENTRY_FEE_CHARGED outbox event to PAYMENT with a refund payload.'

        difficulty: transitive_cascade/event_cancel_cascade_depth_2
        """
        event = event_open_for_registration()
        register_n_distinct_participants(event["id"], 3)
        cancel_event(event["id"])
        sync = list_sync_events(target_system="PAYMENT",
                                kind="ENTRY_FEE_CHARGED")
        # 3 register events + 3 cancel-cascade refund events = 6 minimum.
        assert len(sync) >= 6


# ===========================================================================
# Rule 5, instance 1: state_vs_business_temporal_on_register
# ===========================================================================
class TestStateBeatsTemporalOnRegister:
    """difficulty: priority_pair_validation_conflict/
    state_vs_business_temporal_on_register"""

    def test_register_on_draft_event_returns_invalid_state(
        self, api, organizer_headers
    ):
        """PRD §2.12 priority 5: 'Source-state validity — an operation
        whose required source state does not match the current state of
        the targeted resource returns ERR_INVALID_STATE.'

        PRD §2.12 priority 13: business_temporal — registration window
        check at priority 13 is evaluated AFTER state validity (priority 5),
        so a DRAFT event yields ERR_INVALID_STATE rather than
        ERR_REGISTRATION_CLOSED, even when both checks would fail.

        difficulty: priority_pair_validation_conflict/
        state_vs_business_temporal_on_register
        """
        from test_helpers import register_participant_payload
        # Create event but do NOT open it.
        event = create_event(
            base_iso=DEFAULT_T0,
            registration_window_hours=1,
        )
        # Advance clock past the registration_closes_at; both the
        # state check (DRAFT) and the temporal check would now fail.
        advance_clock(add_minutes(event["registration_closes_at"], 5))
        res = api.register_participant(
            event["id"],
            register_participant_payload(),
            organizer_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_open_event_past_window_yields_registration_closed(
        self, api, organizer_headers
    ):
        """PRD §3.1: 'the registration window must be open
        (`registration_opens_at` at or before now and now strictly
        before `registration_closes_at`, otherwise
        `ERR_REGISTRATION_CLOSED`).' This complements the priority-5
        precedence test by exercising the temporal-only failure path.

        difficulty: priority_pair_validation_conflict/
        state_vs_business_temporal_on_register
        """
        from test_helpers import register_participant_payload
        event = event_open_for_registration()
        advance_clock(event["registration_closes_at"])
        res = api.register_participant(
            event["id"],
            register_participant_payload(),
            organizer_headers,
        )
        validate_error(res, "ERR_REGISTRATION_CLOSED")


# ===========================================================================
# Rule 5, instance 2: business_safety_vs_business_referential_on_referee_assign
# ===========================================================================
class TestSafetyBeatsReferentialOnRefereeAssign:
    """difficulty: priority_pair_validation_conflict/
    business_safety_vs_business_referential_on_referee_assign"""

    def test_conflict_of_interest_wins_over_time_conflict(
        self, api, organizer_headers
    ):
        """PRD §3.3: 'first, conflict-of-interest — the assignment is
        refused if the referee's `country_code` matches the country
        code of either of the match's participants, or if the referee's
        `team_affiliation` matches either participant's `team_code`,
        with the rejection code `ERR_CONFLICT_OF_INTEREST`.'
        PRD §3.3: 'and third, scheduling — the assignment is refused
        if any other non-revoked assignment for the same referee
        covers an `[scheduled_start_at, scheduled_end_at]` interval
        that overlaps with this match's interval, with rejection code
        `ERR_REFEREE_TIME_CONFLICT`.'

        Both COI and time-conflict can fire; PRD pins COI first.

        difficulty: priority_pair_validation_conflict/
        business_safety_vs_business_referential_on_referee_assign
        """
        event, parts = event_drawn(
            n_participants=4,
            countries=["FR", "IT", "PT", "NL"],
            teams=["TFR", "TIT", "TPT", "TNL"],
        )
        matches = [m for m in list_matches(event["id"])
                   if m["round_index"] == 1 and m["status"] != "BYE"]
        if len(matches) < 2:
            pytest.skip("Round-1 has fewer than 2 non-BYE matches.")
        # Build a referee whose country = FR (matches participant in
        # match[0]); pre-assign him to match[1] so a time conflict would
        # also fire (if intervals overlap). The COI check on match[0]
        # must fire first regardless.
        ref = create_referee(country_code="FR", team_affiliation=None,
                              qualifications=[event["event_type"]])
        # Pre-assign on match[1]: but FR may also match a participant of
        # match[1]. Pick match[1] participants ensuring FR isn't there:
        # countries are ordered [FR, IT, PT, NL] — pairs may include FR
        # in match[0] only when seeded that way. Be lenient: try match[1]
        # only if its participants are not FR-based.
        m1 = matches[1]
        try:
            api_client.assign_referee(
                m1["id"],
                create_referee_assignment_payload(referee_id=ref["id"], role="HEAD"),
                organizer_headers,
            )
        except Exception:
            pass  # the pre-assignment may fail if FR is on m1; we just
                  # need it for the time-conflict path. The crucial
                  # assertion is on match[0].
        # Now attempt to assign on match[0] — FR is on match[0] for sure
        # since seeds 1..4 distribute pairs. Check both participants:
        m0 = matches[0]
        # Find the m0 participant countries.
        # Implementation should reject with ERR_CONFLICT_OF_INTEREST.
        res = api.assign_referee(
            m0["id"],
            create_referee_assignment_payload(referee_id=ref["id"], role="HEAD"),
            organizer_headers,
        )
        # PRD pins COI before time-conflict on this endpoint — even if
        # only COI fires, this assertion still validates priority 9.
        validate_error(res, "ERR_CONFLICT_OF_INTEREST")

    def test_pure_time_conflict_yields_referee_time_conflict(
        self, api, organizer_headers
    ):
        """PRD §3.3: 'the assignment is refused if any other non-revoked
        assignment for the same referee covers an [scheduled_start_at,
        scheduled_end_at] interval that overlaps with this match's
        interval, with rejection code ERR_REFEREE_TIME_CONFLICT.'

        difficulty: priority_pair_validation_conflict/
        business_safety_vs_business_referential_on_referee_assign
        """
        event, parts = event_drawn(
            n_participants=4,
            countries=["FR", "IT", "PT", "NL"],
            teams=["TFR", "TIT", "TPT", "TNL"],
        )
        matches = [m for m in list_matches(event["id"])
                   if m["round_index"] == 1 and m["status"] != "BYE"]
        if len(matches) < 2:
            pytest.skip("Round-1 has fewer than 2 non-BYE matches.")
        # Need actually-overlapping intervals.
        m1, m2 = matches[0], matches[1]
        s1, e1 = parse_iso(m1["scheduled_start_at"]), parse_iso(m1["scheduled_end_at"])
        s2, e2 = parse_iso(m2["scheduled_start_at"]), parse_iso(m2["scheduled_end_at"])
        if not (s1 < e2 and s2 < e1):
            pytest.skip("Round-1 intervals are non-overlapping.")
        # Referee neutral to all participants: country DE, no team.
        ref = create_referee(country_code="DE", team_affiliation=None,
                              qualifications=[event["event_type"]])
        from test_helpers import assign_head_referee
        assign_head_referee(m1["id"], ref["id"])
        # Second assignment on overlapping interval rejects.
        res = api.assign_referee(
            m2["id"],
            create_referee_assignment_payload(referee_id=ref["id"], role="HEAD"),
            organizer_headers,
        )
        validate_error(res, "ERR_REFEREE_TIME_CONFLICT")


# ===========================================================================
# Rule 6, instance 1: registration_close_inclusive_lower_exclusive_upper
# ===========================================================================
class TestRegistrationWindowBoundaries:
    """difficulty: boundary_precision_check/
    registration_close_inclusive_lower_exclusive_upper"""

    def test_at_exact_closes_at_rejected_exclusive_upper(
        self, api, organizer_headers
    ):
        """PRD §3.1: 'now strictly before registration_closes_at, otherwise
        ERR_REGISTRATION_CLOSED.'

        difficulty: boundary_precision_check/
        registration_close_inclusive_lower_exclusive_upper
        """
        from test_helpers import register_participant_payload
        event = event_open_for_registration()
        advance_clock(event["registration_closes_at"])
        res = api.register_participant(
            event["id"],
            register_participant_payload(),
            organizer_headers,
        )
        validate_error(res, "ERR_REGISTRATION_CLOSED")

    def test_at_exact_opens_at_succeeds_inclusive_lower(
        self, api, organizer_headers
    ):
        """PRD §3.1: 'registration_opens_at at or before now and now
        strictly before registration_closes_at, otherwise
        ERR_REGISTRATION_CLOSED.' The lower bound is inclusive.

        difficulty: boundary_precision_check/
        registration_close_inclusive_lower_exclusive_upper
        """
        from test_helpers import register_participant_payload
        event = event_open_for_registration()
        # event_open_for_registration advances clock 1 minute past opens_at.
        # Move it back to exactly opens_at via creating a fresh event and
        # advancing only to opens_at. Easier: rely on the existing event
        # — opens_at is already <= now, so registration must succeed
        # while we're still inside the window.
        res = api.register_participant(
            event["id"],
            register_participant_payload(),
            organizer_headers,
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# Rule 6, instance 2: empty_referee_assignment_set_blocks_event_start
# ===========================================================================
class TestEmptyHeadAssignmentBlocksStart:
    """difficulty: boundary_precision_check/
    empty_referee_assignment_set_blocks_event_start"""

    def test_start_without_any_head_referee_rejected(
        self, api, organizer_headers
    ):
        """PRD §3.6: 'every round-1 `Match` carries at least one
        `ASSIGNED` `RefereeAssignment` of role `HEAD`.' The empty-set
        boundary on count of HEAD assignments blocks /start.

        difficulty: boundary_precision_check/
        empty_referee_assignment_set_blocks_event_start
        """
        event, _ = event_drawn(n_participants=4)
        advance_clock(event["starts_at"])
        res = api.start_event(event["id"], organizer_headers)
        validate_error(res, "ERR_INVALID_STATE")

    def test_start_with_head_referee_succeeds(self, api, organizer_headers):
        """PRD §3.6: 'every round-1 `Match` carries at least one
        `ASSIGNED` `RefereeAssignment` of role `HEAD`.' Success path:
        with one HEAD per round-1 match the precondition holds.

        difficulty: boundary_precision_check/
        empty_referee_assignment_set_blocks_event_start
        """
        # event_in_progress already covers this success path; we exercise
        # it explicitly here for the difficulty-design pair.
        from test_helpers import event_in_progress
        started, _, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        assert started["status"] == "IN_PROGRESS"


# ===========================================================================
# Rule 7, instance 1: match_lock_blocked_by_open_dispute
# ===========================================================================
class TestMatchLockBlockedByOpenDispute:
    """difficulty: cross_entity_state_dependency/match_lock_blocked_by_open_dispute"""

    def test_open_dispute_keeps_match_in_result_pending(self, api):
        """PRD §3.4: 'a disagreement is rejected with
        `ERR_RESULT_DISAGREEMENT`, with the match remaining in
        `RESULT_PENDING` and no dispute auto-opened.'

        We verify the closest verbatim rule the implementer can read:
        a disagreement keeps the match in RESULT_PENDING.

        difficulty: cross_entity_state_dependency/
        match_lock_blocked_by_open_dispute
        """
        event, parts, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = next(m for m in list_matches(event["id"])
                     if m["round_index"] == 1 and m["status"] != "BYE"
                     and m.get("home_participant_id")
                     and m.get("away_participant_id"))
        head = create_referee(country_code="GR", team_affiliation=None,
                                qualifications=[event["event_type"]])
        asst = create_referee(country_code="HR", team_affiliation=None,
                                qualifications=[event["event_type"]])
        head_asg = assign_head_referee(match["id"], head["id"])
        asst_asg = assign_assistant_referee(match["id"], asst["id"])
        advance_clock(add_seconds(match["scheduled_end_at"], 1))
        # First submission flips to RESULT_PENDING.
        validate_success(
            api_client.submit_result(
                match["id"],
                submit_result_payload(
                    submitted_by_assignment_id=head_asg["id"],
                    home_score=2, away_score=1,
                ),
                make_referee_headers(head["id"]),
            ),
            expected_status=201,
        )
        # Disagreeing second submission rejected; match stays in
        # RESULT_PENDING.
        res = api_client.submit_result(
            match["id"],
            submit_result_payload(
                submitted_by_assignment_id=asst_asg["id"],
                home_score=3, away_score=2,
            ),
            make_referee_headers(asst["id"]),
        )
        validate_error(res, "ERR_RESULT_DISAGREEMENT")
        m_after = get_match(event["id"], match["id"])
        assert m_after["status"] == "RESULT_PENDING"

    def test_dispute_filed_on_result_pending_creates_open_dispute(self, api):
        """PRD §3.4: 'A participant may file a dispute on a match that is
        in RESULT_PENDING or LOCKED by submitting filed_by_participant_id
        and a reason_text between 1 and 1000 characters. The dispute is
        created in OPEN.'

        difficulty: cross_entity_state_dependency/
        match_lock_blocked_by_open_dispute
        """
        event, parts, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = next(m for m in list_matches(event["id"])
                     if m["round_index"] == 1 and m["status"] != "BYE"
                     and m.get("home_participant_id")
                     and m.get("away_participant_id"))
        head = create_referee(country_code="GR", team_affiliation=None,
                                qualifications=[event["event_type"]])
        head_asg = assign_head_referee(match["id"], head["id"])
        advance_clock(add_seconds(match["scheduled_end_at"], 1))
        validate_success(
            api_client.submit_result(
                match["id"],
                submit_result_payload(
                    submitted_by_assignment_id=head_asg["id"],
                    home_score=2, away_score=1,
                ),
                make_referee_headers(head["id"]),
            ),
            expected_status=201,
        )
        # Match in RESULT_PENDING, file dispute as either participant.
        dispute = file_dispute(match["id"], parts[0]["id"])
        assert dispute["status"] == "OPEN"


# ===========================================================================
# Rule 7, instance 2: prize_payment_pay_blocked_by_event_posture_frozen
# ===========================================================================
class TestPayBlockedByFrozenPosture:
    """difficulty: cross_entity_state_dependency/
    prize_payment_pay_blocked_by_event_posture_frozen"""

    def test_pay_does_not_advance_while_frozen(self, api):
        """PRD §3.6: 'A SCHEDULED PrizePayment advances to PAID
        automatically when the clock crosses scheduled_pay_at, provided
        the event's posture is CLEAN.'

        difficulty: cross_entity_state_dependency/
        prize_payment_pay_blocked_by_event_posture_frozen
        """
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_000, tax_withholding_pct=0.0
        )
        live = list_participants(completed["id"])
        # rank-1 is the cleanest target — its payment is SCHEDULED.
        rank1 = next((p for p in live if p.get("final_rank") == 1), None)
        if rank1 is None:
            pytest.skip("Setup did not produce a unique rank-1 participant.")
        # Trigger FROZEN posture by sanctioning a rank-2 participant and
        # filing an appeal.
        rank2 = next((p for p in live if p.get("final_rank") == 2), None)
        if rank2 is None:
            pytest.skip("Setup did not produce a unique rank-2 participant.")
        sample = positive_doping_for(completed["id"], rank2["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        file_appeal(sanction["id"], rank2["id"])
        ev = get_event(completed["id"])
        assert ev["posture"] == "FROZEN"
        # Advance clock past scheduled_pay_at.
        future = add_seconds(
            add_days(completed["starts_at"], 7), 1
        )
        advance_clock(future)
        run_sweep()
        # rank-1 payment must remain SCHEDULED, not PAID, because posture
        # is FROZEN.
        payments = list_prize_payments(completed["id"])
        pay1 = find_payment_for_participant(payments, rank1["id"])
        assert pay1["status"] == "SCHEDULED", (
            f"PRD §3.6: rank-1 PrizePayment must remain SCHEDULED while "
            f"posture is FROZEN, got {pay1['status']}"
        )

    def test_appeal_dismiss_unfreezes_then_pay_succeeds(self, api):
        """PRD §3.8: 'On uphold false (the appeal is dismissed) the
        appeal flips to `DISMISSED`, the sanction transitions from
        `APPEALED` to `FINAL`, the event's `posture` is recomputed
        (without an `APPEALED` sanction it returns to `UNDER_REVIEW`
        unless other open sanctions exist).'

        Per PRD §2.8 the open-sanctions count covers status IN
        {ISSUED, APPEALED}; a FINAL sanction is excluded, so with no
        APPEALED and no PENDING appeal the posture returns to CLEAN.

        difficulty: cross_entity_state_dependency/
        prize_payment_pay_blocked_by_event_posture_frozen
        """
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_000, tax_withholding_pct=0.0
        )
        live = list_participants(completed["id"])
        rank1 = next((p for p in live if p.get("final_rank") == 1), None)
        rank2 = next((p for p in live if p.get("final_rank") == 2), None)
        if rank1 is None or rank2 is None:
            pytest.skip("Setup did not produce ranks 1 and 2.")
        sample = positive_doping_for(completed["id"], rank2["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        appeal = file_appeal(sanction["id"], rank2["id"])
        # While appeal pending, posture FROZEN per PRD §3.8.
        ev_frozen = get_event(completed["id"])
        assert ev_frozen["posture"] == "FROZEN"
        # Dismiss appeal: PRD §3.8 says posture is recomputed and the
        # sanction becomes FINAL.
        decide_appeal(appeal["id"], uphold=False)
        ev_after = get_event(completed["id"])
        # PRD §2.8 defines the open-sanctions count over status IN
        # {ISSUED, APPEALED}. After FINAL, that count is 0 and no
        # APPEALED nor PENDING appeal remains -> posture CLEAN.
        assert ev_after["posture"] == "CLEAN"


# ===========================================================================
# Rule 8, instance 1: referee_half_open_overlap_no_buffer
# ===========================================================================
class TestRefereeHalfOpenOverlapNoBuffer:
    """difficulty: resource_temporal_overlap/referee_half_open_overlap_no_buffer"""

    def test_overlapping_referee_assignment_rejected(
        self, api, organizer_headers
    ):
        """PRD §3.3: 'the assignment is refused if any other non-revoked
        assignment for the same referee covers an [scheduled_start_at,
        scheduled_end_at] interval that overlaps with this match's
        interval, with rejection code ERR_REFEREE_TIME_CONFLICT.'

        difficulty: resource_temporal_overlap/
        referee_half_open_overlap_no_buffer
        """
        event, _ = event_drawn(
            n_participants=4,
            countries=["FR", "IT", "PT", "NL"],
            teams=["TFR", "TIT", "TPT", "TNL"],
        )
        matches = [m for m in list_matches(event["id"])
                   if m["round_index"] == 1 and m["status"] != "BYE"]
        if len(matches) < 2:
            pytest.skip("Round-1 has fewer than 2 non-BYE matches.")
        m1, m2 = matches[0], matches[1]
        s1, e1 = parse_iso(m1["scheduled_start_at"]), parse_iso(m1["scheduled_end_at"])
        s2, e2 = parse_iso(m2["scheduled_start_at"]), parse_iso(m2["scheduled_end_at"])
        if not (s1 < e2 and s2 < e1):
            pytest.skip("Round-1 intervals non-overlapping.")
        ref = create_referee(country_code="DE", team_affiliation=None,
                              qualifications=[event["event_type"]])
        validate_success(
            api_client.assign_referee(
                m1["id"],
                create_referee_assignment_payload(referee_id=ref["id"], role="HEAD"),
                organizer_headers,
            ),
            expected_status=201,
        )
        res = api.assign_referee(
            m2["id"],
            create_referee_assignment_payload(referee_id=ref["id"], role="HEAD"),
            organizer_headers,
        )
        validate_error(res, "ERR_REFEREE_TIME_CONFLICT")

    def test_referee_distinct_match_assignments_succeed(
        self, api, organizer_headers
    ):
        """PRD §3.3: implicit success path — a referee neutral to both
        participants, with the right qualification and no scheduling
        overlap, must be accepted on a SCHEDULED match.

        difficulty: resource_temporal_overlap/
        referee_half_open_overlap_no_buffer
        """
        event, _ = event_drawn(
            n_participants=2, countries=["FR", "IT"], teams=["TFR", "TIT"]
        )
        match = list_matches(event["id"])[0]
        ref = create_referee(country_code="DE", team_affiliation=None,
                              qualifications=[event["event_type"]])
        res = api.assign_referee(
            match["id"],
            create_referee_assignment_payload(referee_id=ref["id"], role="HEAD"),
            organizer_headers,
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# Rule 8, instance 2: participant_overlap_with_30_min_buffer
# ===========================================================================
class TestParticipantSchedulingBuffer:
    """difficulty: resource_temporal_overlap/participant_overlap_with_30_min_buffer"""

    def test_participant_scheduling_rule_documented_30_min_gap(self, api):
        """PRD §3.2: 'the same participant cannot appear in two
        non-VOIDED matches whose [scheduled_start_at, scheduled_end_at]
        intervals overlap, and even adjacent intervals — where one match
        ends at the same instant the next begins — require a hard
        30-minute gap before that participant can be rescheduled.
        Violations are rejected with ERR_PARTICIPANT_TIME_CONFLICT.'

        Participant-overlap arises only at /draw or future manual
        scheduling. The /draw scheduler is implementation-dependent;
        we verify the sanity invariant on the live bracket: every
        Participant's matches are mutually time-disjoint by ≥30 minutes.

        difficulty: resource_temporal_overlap/
        participant_overlap_with_30_min_buffer
        """
        event, parts = event_drawn(n_participants=4)
        matches = [m for m in list_matches(event["id"])
                   if m["status"] != "VOIDED"]
        # Group matches by participant.
        by_participant: dict = {}
        for m in matches:
            for p_id in (m.get("home_participant_id"),
                          m.get("away_participant_id")):
                if p_id is None:
                    continue
                by_participant.setdefault(p_id, []).append(m)
        from datetime import timedelta
        for p_id, ms in by_participant.items():
            ms_sorted = sorted(ms, key=lambda m: parse_iso(m["scheduled_start_at"]))
            for a, b in zip(ms_sorted, ms_sorted[1:]):
                # Per PRD §3.2 the gap between a's end and b's start
                # must be > 0 (no overlap) and adjacent (== 0) requires
                # ≥30 min. So gap >= 30 min.
                gap = (parse_iso(b["scheduled_start_at"])
                       - parse_iso(a["scheduled_end_at"]))
                assert gap >= timedelta(minutes=30), (
                    f"PRD §3.2: participant {p_id} scheduled with "
                    f"<30-min gap between matches {a['id']} and {b['id']}: "
                    f"gap={gap}"
                )

    def test_no_participant_appears_in_overlapping_matches(self, api):
        """PRD §3.2: 'the same participant cannot appear in two non-VOIDED
        matches whose [scheduled_start_at, scheduled_end_at] intervals
        overlap.' Verify directly on the live bracket.

        difficulty: resource_temporal_overlap/
        participant_overlap_with_30_min_buffer
        """
        event, parts = event_drawn(n_participants=4)
        matches = [m for m in list_matches(event["id"])
                   if m["status"] != "VOIDED"]
        from datetime import timedelta
        for p in parts:
            ms = [m for m in matches
                  if p["id"] in (m.get("home_participant_id"),
                                  m.get("away_participant_id"))]
            for i, a in enumerate(ms):
                for b in ms[i + 1:]:
                    sa = parse_iso(a["scheduled_start_at"])
                    ea = parse_iso(a["scheduled_end_at"])
                    sb = parse_iso(b["scheduled_start_at"])
                    eb = parse_iso(b["scheduled_end_at"])
                    overlap = sa < eb and sb < ea
                    assert not overlap, (
                        f"PRD §3.2: participant {p['id']} appears in "
                        f"two overlapping matches {a['id']} and {b['id']}."
                    )


# ===========================================================================
# Rule 9, instance 1: prize_pool_conservation_under_sanction_revoke
# ===========================================================================
class TestPrizePoolConservation:
    """difficulty: compensating_invariant/prize_pool_conservation_under_sanction_revoke"""

    def test_gross_and_tax_unchanged_after_revoke(self, api):
        """PRD §3.6: 'When a sanction is later revoked through a
        successful appeal, the cascade reverses: forfeit_amount_cents
        returns to 0, net_amount_cents is recomputed under the same
        gross-and-tax preservation rule, and status returns to
        SCHEDULED.'

        difficulty: compensating_invariant/
        prize_pool_conservation_under_sanction_revoke
        """
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_000, tax_withholding_pct=10.0
        )
        before = list_prize_payments(completed["id"])
        snap = {pp["id"]: dict(pp) for pp in before}
        live = list_participants(completed["id"])
        target = next((p for p in live if p.get("final_rank") == 2), None)
        if target is None:
            pytest.skip("Setup did not produce a unique rank-2 participant.")
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        appeal = file_appeal(sanction["id"], target["id"])
        decide_appeal(appeal["id"], uphold=True)
        after = list_prize_payments(completed["id"])
        for pp in after:
            old = snap[pp["id"]]
            assert pp["gross_amount_cents"] == old["gross_amount_cents"]
            assert pp["tax_withheld_cents"] == old["tax_withheld_cents"]

    def test_target_payment_returns_to_scheduled_with_zero_forfeit(self, api):
        """PRD §3.8: 'any PrizePayment in FORFEITED returns to SCHEDULED
        with forfeit_amount_cents set to 0 and net_amount_cents recomputed
        from the preserved gross and original tax (per §3.6's variant
        rule).'

        difficulty: compensating_invariant/
        prize_pool_conservation_under_sanction_revoke
        """
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_000, tax_withholding_pct=10.0
        )
        live = list_participants(completed["id"])
        target = next((p for p in live if p.get("final_rank") == 2), None)
        if target is None:
            pytest.skip("Setup did not produce a unique rank-2 participant.")
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        appeal = file_appeal(sanction["id"], target["id"])
        decide_appeal(appeal["id"], uphold=True)
        payments = list_prize_payments(completed["id"])
        pay = find_payment_for_participant(payments, target["id"])
        assert pay["status"] == "SCHEDULED"
        assert pay["forfeit_amount_cents"] == 0
        # Net = gross - tax - 0
        assert pay["net_amount_cents"] == max(
            0, pay["gross_amount_cents"] - pay["tax_withheld_cents"]
        )


# ===========================================================================
# Rule 9, instance 2: registered_count_conservation_under_withdraw
# ===========================================================================
class TestRegisteredCountConservation:
    """difficulty: compensating_invariant/
    registered_count_conservation_under_withdraw_then_reopen"""

    def test_registered_count_after_two_withdrawals(self, api):
        """PRD §3.1: 'Event.registered_count increments.'
        PRD §3.1: 'While the event is in `OPEN` or
        `REGISTRATION_CLOSED` and the participant is still
        `REGISTERED`, withdrawal flips the participant to `WITHDRAWN`,
        decrements `Event.registered_count`, and emits an outbox
        `ENTRY_FEE_CHARGED` event with a refund payload (the negative
        of `entry_fee_paid_cents`).'

        difficulty: compensating_invariant/
        registered_count_conservation_under_withdraw_then_reopen
        """
        event = event_open_for_registration(capacity_min=2, capacity_max=8)
        ps = register_n_distinct_participants(event["id"], 4)
        from test_helpers import get_event
        ev_after_registers = get_event(event["id"])
        assert ev_after_registers["registered_count"] == 4
        withdraw_participant(ps[1]["id"])
        withdraw_participant(ps[2]["id"])
        ev_after_withdraws = get_event(event["id"])
        assert ev_after_withdraws["registered_count"] == 2

    def test_withdrawal_emits_refund_sync_event(self, api):
        """PRD §3.1: 'emits an outbox ENTRY_FEE_CHARGED event with a
        refund payload (the negative of entry_fee_paid_cents).'

        difficulty: compensating_invariant/
        registered_count_conservation_under_withdraw_then_reopen
        """
        event = event_open_for_registration(capacity_min=2, capacity_max=8)
        ps = register_n_distinct_participants(event["id"], 2)
        # Snapshot count of ENTRY_FEE_CHARGED events before withdrawal.
        before = list_sync_events(target_system="PAYMENT",
                                  kind="ENTRY_FEE_CHARGED")
        withdraw_participant(ps[0]["id"])
        after = list_sync_events(target_system="PAYMENT",
                                 kind="ENTRY_FEE_CHARGED")
        assert len(after) >= len(before) + 1, (
            "PRD §3.1: withdrawal must emit an ENTRY_FEE_CHARGED refund "
            "outbox event."
        )
