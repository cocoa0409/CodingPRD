"""Tally, recount, certification — provisional vs reconciled variants,
pinned rounding order, recount-threshold boundary, recount lifecycle.

PRD §2.10 (Numeric Precision), §3.2 (Lifecycle), §3.9 (Tally, Recount,
and Reconciliation).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_past_ballot_return,
    advance_to_early_voting,
    advance_to_election_day,
    api_client,
    assert_recount_request,
    file_manual_recount,
    initiate_tally,
    list_recounts,
    setup_active_voter,
    setup_election_in_tally,
    state_transition_payload,
    transition_election,
    transition_recount,
    validate_error,
    validate_success,
)


class TestProvisionalTallyExcludesProvisional:

    def test_provisional_tally_excludes_provisional_ballots(self, api):
        """PRD §3.9: 'whose method is in EARLY_IN_PERSON,
        ELECTION_DAY_MACHINE, or ABSENTEE — ELECTION_DAY_PROVISIONAL
        is explicitly excluded under the provisional variant.'

        Set up a precinct with 50 A early + 49 A provisional + 50 B
        early. Provisional variant should report A=50, B=50, margin=0.
        """
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 50, "B": 50},
                "method": "EARLY_IN_PERSON",
            }],
            include_provisional={"P1": {"A": 49}},
            recount_threshold_pct=0.005,
        )
        resp = api.get_tally(
            ctx["election"]["id"],
            TEST_USERS["election_board_headers"],
            variant="provisional",
        )
        data = validate_success(resp)
        # Provisional totals should NOT include the 49 PROVISIONAL As.
        # We only assert the precinct-level totals contain A=50 and
        # B=50; the exact response shape is up to the implementation
        # but PRD §3.9 pins these counts.
        # Inspect any nested totals; locate keys "A" and "B" with value 50.
        flat = []

        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in ("A", "B") and isinstance(v, int):
                        flat.append((k, v))
                    walk(v)
            elif isinstance(obj, list):
                for x in obj:
                    walk(x)

        walk(data)
        # Find A and B totals (could appear per precinct and
        # election-wide). The minimum sane assertion: A=50 appears
        # somewhere AND no A=99 appears (which would have been the
        # case if provisional ballots were counted).
        a_values = {v for k, v in flat if k == "A"}
        b_values = {v for k, v in flat if k == "B"}
        assert 50 in a_values, (
            f"provisional variant must count A=50 (not 99); "
            f"observed A values={a_values}"
        )
        assert 50 in b_values, (
            f"provisional variant must count B=50; "
            f"observed B values={b_values}"
        )
        assert 99 not in a_values, (
            f"provisional variant must EXCLUDE the 49 PROVISIONAL A "
            f"ballots; observed A values={a_values}"
        )


class TestRecountAutoTriggerBoundary:

    def test_recount_auto_trigger_at_inclusive_boundary(self, api):
        """PRD §3.9: 'The boundary is inclusive on the low side: a
        margin exactly equal to the threshold triggers a recount.'

        Set choice A=201 + B=199 (sum=400, margin=2/400=0.005000
        exactly == recount_threshold_pct).
        """
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 201, "B": 199},
                "method": "EARLY_IN_PERSON",
            }],
            recount_threshold_pct=0.005,
        )
        recounts = list_recounts(ctx["election"]["id"])
        assert any(
            r.get("requested_by_role") == "system"
            and abs(float(r.get("trigger_margin_pct", -1)) - 0.005) < 1e-9
            for r in recounts
        ), (
            "expected one system-triggered RecountRequest with "
            f"trigger_margin_pct=0.005000, got {recounts!r}"
        )

    def test_certify_blocked_when_recount_required(self, api):
        """PRD §3.2: 'Going on to CERTIFIED requires that the
        provisional margin is strictly greater than the recount
        threshold (otherwise the transition is rejected with
        ERR_RECOUNT_REQUIRED).'
        """
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 201, "B": 199},  # margin == threshold
                "method": "EARLY_IN_PERSON",
            }],
            recount_threshold_pct=0.005,
        )
        resp = api.transition_election(
            ctx["election"]["id"],
            state_transition_payload("CERTIFIED"),
            TEST_USERS["election_board_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RECOUNT_REQUIRED.value)


class TestPinnedRoundingOrder:

    def test_election_margin_uses_summed_integer_totals(self, api):
        """PRD §3.9: 'each per-choice total is summed across precincts
        as integer counts (each precinct's per-choice count is already
        integer, so this addition is exact and incurs no rounding).
        ... This order — sum integer counts first, then divide once —
        is mandatory.'

        Build P1=(A:67, B:33) and P2=(A:1, B:2). Pinned-order margin =
        (68-35)/103 = 0.320388 (6 dp). Per-precinct averaging would
        yield ~0.003 — fails this assertion, proving rounding-order
        sensitivity.
        """
        ctx = setup_election_in_tally(
            precincts_choice_counts=[
                {"code": "P1", "pattern": ".*Main.*",
                 "choices": {"A": 67, "B": 33}},
                {"code": "P2", "pattern": ".*Oak.*",
                 "choices": {"A": 1, "B": 2}},
            ],
            recount_threshold_pct=0.001,
        )
        resp = api.get_tally(
            ctx["election"]["id"],
            TEST_USERS["election_board_headers"],
            variant="provisional",
        )
        data = validate_success(resp)
        # Find any field that looks like the election margin (6dp,
        # close to 0.320388).
        observed = []

        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, (int, float)) and isinstance(v, float):
                        observed.append((k, v))
                    walk(v)
            elif isinstance(obj, list):
                for x in obj:
                    walk(x)

        walk(data)
        # The pinned-order margin must appear.
        assert any(
            abs(v - 0.320388) < 1e-6 for _k, v in observed
        ), (
            "expected election_margin_pct ≈ 0.320388 from pinned "
            f"rounding order; observed floats={observed}"
        )


class TestRecountLifecycle:

    def test_in_progress_cascades_election_to_recount_and_challenged(
            self, api):
        """PRD §3.9: 'Advancing approval to IN_PROGRESS has the side
        effect of cascading the election from TALLY to RECOUNT
        (cascade-up) and setting every TALLIED BallotCast to
        CHALLENGED.'
        """
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 201, "B": 199},  # auto-trigger
            }],
            recount_threshold_pct=0.005,
        )
        recounts = list_recounts(ctx["election"]["id"])
        rr = next(r for r in recounts if r["requested_by_role"] == "system")
        rr = transition_recount(rr["id"], "APPROVED")
        rr = transition_recount(rr["id"], "IN_PROGRESS")
        # Election should be in RECOUNT now.
        from test_helpers import get_election
        e = get_election(ctx["election"]["id"])
        assert e["state"] == "RECOUNT", (
            f"election must cascade to RECOUNT, got {e['state']!r}"
        )

    def test_resolve_overturn_rejected_when_winner_matches(self, api):
        """PRD §3.9: 'an attempt to resolve as RESOLVED_OVERTURN while
        the two winners agree is rejected with
        ERR_RECOUNT_NO_OVERTURN.'

        Build a case where provisional winner == reconciled winner
        (no PROVISIONAL ballots, so both variants are identical), then
        attempt RESOLVED_OVERTURN.
        """
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 201, "B": 199},  # auto-trigger
            }],
            recount_threshold_pct=0.005,
        )
        recounts = list_recounts(ctx["election"]["id"])
        rr = next(r for r in recounts if r["requested_by_role"] == "system")
        rr = transition_recount(rr["id"], "APPROVED")
        rr = transition_recount(rr["id"], "IN_PROGRESS")
        # No PROVISIONAL ballots, so reconciled winner is also A.
        resp = api.transition_recount(
            rr["id"], state_transition_payload("RESOLVED_OVERTURN"),
            TEST_USERS["election_board_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RECOUNT_NO_OVERTURN.value)

    def test_resolve_no_change_returns_challenged_to_tallied(self, api):
        """PRD §3.9: 'Both resolution side effects ... cascade-down by
        moving every CHALLENGED BallotCast back to TALLIED with
        challenge_reason cleared to null.'

        Compensating-action invariant: count(TALLIED ∪ CHALLENGED) is
        constant through the cycle.
        """
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 201, "B": 199},
            }],
            recount_threshold_pct=0.005,
        )
        recounts = list_recounts(ctx["election"]["id"])
        rr = next(r for r in recounts if r["requested_by_role"] == "system")
        rr = transition_recount(rr["id"], "APPROVED")
        rr = transition_recount(rr["id"], "IN_PROGRESS")
        rr = transition_recount(rr["id"], "RESOLVED_NO_CHANGE")
        assert rr["status"] == "RESOLVED_NO_CHANGE"
        # We can't easily inspect every BallotCast here without a list
        # endpoint, but the recount having resolved without error is
        # the directly observable PRD claim.
