"""Appeals, the 14-day window, posture transitions, and the auto-FINAL
path (PRD §3.8, §2.8, §2.13)."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    add_seconds,
    advance_clock,
    decide_appeal,
    file_appeal,
    file_appeal_payload,
    find_payment_for_participant,
    find_sync_events,
    get_event,
    get_sanction,
    latest_sanction_for_sample,
    list_audit_logs,
    list_participants,
    list_prize_payments,
    list_sync_events,
    make_participant_headers,
    parse_iso,
    positive_doping_for,
    setup_single_elim_8_with_complete,
    validate_error,
    validate_success,
)


# ===========================================================================
# 3.8 — Appeal filing transitions sanction to APPEALED, posture to FROZEN
# ===========================================================================
class TestAppealFiling:
    def test_appeal_transitions_sanction_to_appealed(self, api):
        """PRD §3.8: 'Filing an appeal moves the sanction from ISSUED to
        APPEALED.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        appeal = file_appeal(sanction["id"], target["id"])
        # Re-fetch sanction.
        s_after = get_sanction(sanction["id"])
        assert s_after["status"] == "APPEALED"

    def test_appeal_freezes_event_posture(self, api):
        """PRD §3.8: 'The cascade flips the event's posture to FROZEN
        (because per §2.8 any APPEALED sanction freezes the event).'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        file_appeal(sanction["id"], target["id"])
        ev = get_event(completed["id"])
        assert ev["posture"] == "FROZEN"

    def test_appeal_filed_by_non_sanctioned_participant_rejected(self, api):
        """PRD §3.8: 'the filed_by_user_id must equal
        SanctionRecord.participant_id.' A participant other than the
        sanctioned athlete cannot file the appeal."""
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]
        intruder = parts[2]
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        # Use the WRONG participant identity. PRD §2.1 ownership comparison
        # makes X-User-ID equal to body's filed_by_user_id only when they
        # match Participant.id; using a different participant must reject.
        res = api.file_appeal(
            file_appeal_payload(sanction_id=sanction["id"]),
            make_participant_headers(intruder["id"]),
        )
        # The body's filed_by_user_id will equal the X-User-ID (intruder),
        # which differs from sanction.participant_id (target). PRD §3.8
        # says the appeal cannot be filed by a different participant; the
        # most faithful surface signal is ERR_FORBIDDEN (the role is
        # entity-backed and ownership fails). Since PRD does not pin a
        # single error_id for this off-actor case, accept either FORBIDDEN
        # or VALIDATION-class rejections.
        assert res.status_code >= 400


# ===========================================================================
# 3.8 — Appeal window
# ===========================================================================
class TestAppealWindow:
    def test_late_appeal_rejected_with_window_closed(self, api):
        """PRD §3.8: 'A late appeal, where now() is strictly later than
        created_at + 14 days, is rejected with ERR_APPEAL_WINDOW_CLOSED.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        # Advance clock 14 days + 1 second past the sanction's created_at.
        future = add_seconds(add_days(sanction["created_at"], 14), 1)
        advance_clock(future)
        res = api.file_appeal(
            file_appeal_payload(sanction_id=sanction["id"]),
            make_participant_headers(target["id"]),
        )
        validate_error(res, "ERR_APPEAL_WINDOW_CLOSED")

    def test_appeal_at_exact_14_day_boundary_succeeds(self, api):
        """PRD §3.8: 'The window is inclusive on the closing edge: an
        appeal filed at the instant now() equals created_at + 14 days is
        still accepted.' (Also PRD §2.13.)"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        boundary = add_days(sanction["created_at"], 14)
        advance_clock(boundary)
        res = api.file_appeal(
            file_appeal_payload(sanction_id=sanction["id"]),
            make_participant_headers(target["id"]),
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# 3.8 — Appeal decisions
# ===========================================================================
class TestAppealDecide:
    def test_uphold_revokes_sanction_and_unfreezes_payment(self, api):
        """PRD §3.8: 'On uphold true (the appeal is granted) the appeal
        flips to UPHELD and the sanction transitions from APPEALED to
        REVOKED. The cascade on a revoke is the reverse of the issuance
        cascade ... any PrizePayment in FORFEITED returns to SCHEDULED
        with forfeit_amount_cents set to 0.'"""
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_000, tax_withholding_pct=0.0
        )
        # Pick the rank-2 participant (has a SCHEDULED PrizePayment).
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
        payments = list_prize_payments(completed["id"])
        pay = find_payment_for_participant(payments, target["id"])
        assert pay is not None
        assert pay["status"] == "SCHEDULED"
        assert pay["forfeit_amount_cents"] == 0

    def test_dismiss_finalizes_sanction(self, api):
        """PRD §3.8: 'On uphold false (the appeal is dismissed) the appeal
        flips to DISMISSED, the sanction transitions from APPEALED to
        FINAL.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        appeal = file_appeal(sanction["id"], target["id"])
        decide_appeal(appeal["id"], uphold=False)
        s_after = get_sanction(sanction["id"])
        assert s_after["status"] == "FINAL"


# ===========================================================================
# 3.8 — Auto-FINAL after 14-day window without an appeal
# ===========================================================================
class TestAutoFinal:
    def test_no_appeal_after_14_days_advances_to_final(self, api):
        """PRD §3.8: 'If no appeal is filed, the system advances the
        sanction from ISSUED to FINAL automatically when the clock
        crosses created_at + 14 days and no Appeal exists.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        future = add_seconds(add_days(sanction["created_at"], 14), 1)
        advance_clock(future)
        # The clock advance itself triggers the system FINAL transition,
        # but we run /_sweep/run for idempotency / explicit recompute.
        from test_helpers import run_sweep
        run_sweep()
        s_after = get_sanction(sanction["id"])
        assert s_after["status"] == "FINAL"

    def test_auto_final_emits_sanction_archived_sync_event(self, api):
        """PRD §3.8: 'The cascade recomputes the event's posture and emits
        a SyncEvent of kind SANCTION_ARCHIVED to GOVERNING_BODY.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]
        sample = positive_doping_for(completed["id"], target["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        future = add_seconds(add_days(sanction["created_at"], 14), 1)
        advance_clock(future)
        from test_helpers import run_sweep
        run_sweep()
        sync = list_sync_events(target_system="GOVERNING_BODY",
                                kind="SANCTION_ARCHIVED")
        assert len(sync) >= 1, (
            "PRD §3.8: a SANCTION_ARCHIVED sync-event row to "
            "GOVERNING_BODY must be emitted on auto-FINAL."
        )


# ===========================================================================
# 2.8 — Posture gating
# ===========================================================================
class TestPostureGating:
    def test_complete_blocked_when_event_frozen(self, api, organizer_headers):
        """PRD §2.8: 'A FROZEN posture gates a fixed set of operations:
        result submission for any match, the system-driven prize-payout
        transition that pays a PrizePayment, and event completion. In all
        three, the rejection code is ERR_EVENT_FROZEN.'

        Build a non-completed event scenario where posture is FROZEN.
        Easiest: complete event, freeze via positive+appeal, then attempt
        a fresh /complete on a different event after manually freezing —
        but PRD only freezes via posture which gates COMPLETED transition
        from IN_PROGRESS. We exercise the result-submission gate instead,
        which yields the same ERR_EVENT_FROZEN under the same posture
        rule.
        """
        # We rely on the result-submission FROZEN gate, which is one of
        # the three operations explicitly named in §2.8.
        from test_helpers import event_in_progress, list_matches, advance_clock
        from test_helpers import add_seconds
        # Build event in IN_PROGRESS with one round-1 match. Mark posture
        # FROZEN by issuing a sanction whose appeal is pending.
        # However: positive doping requires the participant to be ACTIVE
        # in an event whose lifecycle reached at least IN_PROGRESS. The
        # SanctionRecord cascade itself flips posture to UNDER_REVIEW; an
        # APPEAL is required for FROZEN.
        event, parts, matches = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=4,
            countries=["FR", "IT", "PT", "NL"],
            teams=["TFR", "TIT", "TPT", "TNL"],
        )
        # Open positive sample on parts[2] (loser of an unlocked round-1
        # match) — this triggers the cascade with the participant still
        # ACTIVE.
        sample = positive_doping_for(event["id"], parts[2]["id"])
        sanction = latest_sanction_for_sample(sample["id"])
        # File appeal -> posture FROZEN.
        file_appeal(sanction["id"], parts[2]["id"])
        ev = get_event(event["id"])
        assert ev["posture"] == "FROZEN"
        # Now attempt /complete on the IN_PROGRESS event. Even if
        # preconditions on locked matches do not all hold, the FROZEN
        # gate (priority 6 per §2.12) is evaluated AFTER state validity
        # (priority 5). Skip if state-check would fire first.
        # Instead, exercise result submission as the FROZEN-gated op.
        from test_helpers import (
            create_referee, assign_head_referee, assign_assistant_referee,
            make_referee_headers, submit_result_payload,
        )
        # Find a still-live round-1 match.
        live = [m for m in list_matches(event["id"])
                if m["round_index"] == 1 and m["status"] == "SCHEDULED"
                and m.get("home_participant_id") and m.get("away_participant_id")]
        if not live:
            pytest.skip("No live SCHEDULED round-1 match remained.")
        match = live[0]
        head = create_referee(country_code="GR", team_affiliation=None,
                                qualifications=[event["event_type"]])
        head_asg = assign_head_referee(match["id"], head["id"])
        advance_clock(add_seconds(match["scheduled_end_at"], 1))
        res = api.submit_result(
            match["id"],
            submit_result_payload(
                submitted_by_assignment_id=head_asg["id"],
                home_score=2, away_score=1,
            ),
            make_referee_headers(head["id"]),
        )
        validate_error(res, "ERR_EVENT_FROZEN")
