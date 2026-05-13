"""Dispute workflow: open → investigate → mediate (with cyclic
back-edge) → arbitrate → resolve / withdraw, plus posture cascade and
exposure score (PRD §3.11, §2.7, §2.10 priority 27)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    DOFF,
    NON_EXISTENT_UUID,
    advance_to_arbitration,
    advance_to_mediation,
    assert_dispute,
    create_dispute_payload,
    create_rights_holder,
    find_distributions_for_work,
    list_pool_distributions,
    make_rights_holder_headers,
    open_dispute,
    reopen_investigation,
    resolve_dispute,
    resolve_dispute_payload,
    setup_approved_recording_work,
    setup_closed_pool_for_works,
    setup_dispute_cyclic_through_resolved,
    setup_dispute_through_arbitration,
    start_investigation,
    submit_evidence,
    submit_evidence_payload,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_dispute,
)


class TestOpenDispute:

    def test_open_dispute_freezes_work_posture(self, api):
        """PRD §2.7: 'Posture is FROZEN if and only if there exists at
        least one Dispute on this work whose status is one of OPEN,
        UNDER_INVESTIGATION, MEDIATION, or ARBITRATION.' PRD §3.11:
        'because at least one open dispute now exists, [the work's
        dispute_posture] flips from CLEAR to FROZEN.'

        Claim: opening a dispute on an APPROVED work sets the work's
        dispute_posture to FROZEN.
        """
        h, work, _share = setup_approved_recording_work()
        open_dispute(work["id"], h["id"], dispute_kind="OWNERSHIP")
        # Reload work.
        resp = api.get_work(work["id"], make_rights_holder_headers(h["id"]))
        data = validate_success(resp, 200)
        assert data["dispute_posture"] == "FROZEN"

    def test_open_dispute_freezes_pending_distribution(self, api):
        """PRD §2.7: 'When posture flips from CLEAR to FROZEN, every
        PENDING Distribution on that work flips to FROZEN.'

        Claim: open dispute after a pool close caused PENDING
        distributions → all matching distributions become FROZEN.
        """
        h, work, _share = setup_approved_recording_work()
        closed, _rule, dists_before = setup_closed_pool_for_works(
            [work], gross_revenue_cents=10_000_000,
        )
        for d in dists_before:
            assert d["status"] == "PENDING"
        open_dispute(work["id"], h["id"], dispute_kind="OWNERSHIP")
        dists_after = list_pool_distributions(closed["id"])
        for d in find_distributions_for_work(dists_after, work["id"]):
            assert d["status"] == "FROZEN", \
                f"Expected FROZEN after open-dispute; got {d['status']}"


class TestEvidenceAndAdvance:

    def test_advance_to_mediation_requires_two_evidence_items(self, api):
        """PRD §3.11: 'From UNDER_INVESTIGATION, the officer may advance
        to MEDIATION once evidence_items contains at least two entries
        — the platform requires at least two parties to have submitted
        evidence before mediation.'

        Claim: advance-to-mediation with only one evidence item →
        ERR_INVALID_STATE (409).
        """
        h, work, _share = setup_approved_recording_work()
        disp = open_dispute(work["id"], h["id"], dispute_kind="OWNERSHIP")
        start_investigation(disp["id"])
        submit_evidence(disp["id"], h["id"], url="https://example.com/e1.pdf")
        # Only one evidence item — must be blocked.
        resp = api.advance_to_mediation(disp["id"], DOFF)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    def test_advance_chain_succeeds_with_two_evidence_items(self, api):
        """PRD §3.11: 'From OPEN, the officer starts the investigation,
        flipping status to UNDER_INVESTIGATION. From UNDER_INVESTIGATION,
        the officer may advance to MEDIATION once evidence_items
        contains at least two entries...'

        Claim: open → start-investigation → 2 evidence → mediation →
        arbitration each returns 200 with the next status set.
        """
        disp_summary = setup_dispute_through_arbitration(
            *_make_holder_and_work(api),
        )
        assert disp_summary["status"] == "ARBITRATION"


def _make_holder_and_work(api):
    h, work, _share = setup_approved_recording_work()
    return work["id"], h["id"]


class TestResolveAndCascade:

    def test_resolve_requires_outcome_and_decision(self, api):
        """PRD §3.11 / §2.10 priority 27: 'a malformed body lacking
        either of these is rejected with ERR_RESOLUTION_INVALID.'

        Claim: resolve without outcome → ERR_RESOLUTION_INVALID (422).
        """
        h, work, _share = setup_approved_recording_work()
        # Get the dispute to arbitration.
        ctx = setup_dispute_cyclic_through_resolved(holder=h, work=work)
        # That flow already RESOLVED. Build a NEW one for the malformed test.
        h2, work2, _ = setup_approved_recording_work(
            holder_legal_name="Resolve Negative Holder",
        )
        disp = open_dispute(work2["id"], h2["id"], dispute_kind="OWNERSHIP")
        start_investigation(disp["id"])
        submit_evidence(disp["id"], h2["id"], url="https://example.com/x.pdf")
        submit_evidence(disp["id"], as_officer=True,
                        url="https://example.com/y.pdf")
        advance_to_mediation(disp["id"])
        advance_to_arbitration(disp["id"])
        # Resolve with empty body — should fail.
        resp = api.resolve_dispute(disp["id"], {}, DOFF)
        validate_error(resp, ApiErrorId.ERR_RESOLUTION_INVALID.value, 422)

    def test_resolve_dismissed_releases_frozen_distributions(self, api):
        """PRD §3.11: 'On a successful resolution, the dispute's status
        becomes either RESOLVED_UPHELD or RESOLVED_DISMISSED according
        to the supplied outcome, arbitrator_id is stamped with the
        officer's X-User-ID, and the work's dispute_posture is
        recomputed (cascade depth 1) — if no other open dispute
        remains on this work, posture flips to CLEAR (cascade depth 2)
        and every FROZEN distribution on this work flips to RELEASED
        (cascade depth 3).'

        Claim: resolve DISMISSED → arbitrator_id stamped; work posture
        flips CLEAR; previously-FROZEN distributions → RELEASED.
        """
        h, work, _share = setup_approved_recording_work()
        closed, _rule, dists_before = setup_closed_pool_for_works(
            [work], gross_revenue_cents=10_000_000,
        )
        # Open and walk through arbitration.
        disp = open_dispute(work["id"], h["id"], dispute_kind="OWNERSHIP")
        # After dispute opens, dists should be FROZEN.
        start_investigation(disp["id"])
        submit_evidence(disp["id"], h["id"], url="https://example.com/x.pdf")
        submit_evidence(disp["id"], as_officer=True,
                        url="https://example.com/y.pdf")
        advance_to_mediation(disp["id"])
        advance_to_arbitration(disp["id"])
        resolved = resolve_dispute(disp["id"], outcome="DISMISSED",
                                   arbitration_decision="No merit.")
        assert resolved["status"] == "RESOLVED_DISMISSED"
        assert resolved.get("arbitrator_id") == DOFF["X-User-ID"]
        # Check the work posture is CLEAR.
        w_resp = api.get_work(work["id"],
                              make_rights_holder_headers(h["id"]))
        w_data = validate_success(w_resp, 200)
        assert w_data["dispute_posture"] == "CLEAR"
        # And the FROZEN distributions should be RELEASED.
        dists_after = list_pool_distributions(closed["id"])
        for d in find_distributions_for_work(dists_after, work["id"]):
            assert d["status"] == "RELEASED", \
                f"Expected RELEASED after resolve; got {d['status']}"

    def test_withdraw_only_by_claimant(self, api):
        """PRD §3.11: 'Withdrawal is gated on the caller's X-User-ID
        matching the dispute's claimant_rights_holder_id.'

        Claim: a different holder cannot withdraw someone else's OPEN
        dispute → ERR_FORBIDDEN (403).
        """
        h, work, _share = setup_approved_recording_work()
        other = create_rights_holder(legal_name="Different Holder")
        disp = open_dispute(work["id"], h["id"], dispute_kind="OWNERSHIP")
        resp = api.withdraw_dispute(disp["id"],
                                    make_rights_holder_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


class TestCyclicMediation:

    def test_mediation_can_reopen_investigation(self, api):
        """PRD §3.11: 'Within mediation, the officer may either advance
        forward to ARBITRATION, or reopen the investigation by flipping
        the status back to UNDER_INVESTIGATION (the cyclic loop allows
        further evidence collection).'

        Claim: MEDIATION → UNDER_INVESTIGATION via reopen-investigation
        returns 200 with status=UNDER_INVESTIGATION; advance-to-
        mediation succeeds again afterwards.
        """
        h, work, _share = setup_approved_recording_work()
        disp = open_dispute(work["id"], h["id"], dispute_kind="OWNERSHIP")
        start_investigation(disp["id"])
        submit_evidence(disp["id"], h["id"], url="https://example.com/a.pdf")
        submit_evidence(disp["id"], as_officer=True,
                        url="https://example.com/b.pdf")
        med1 = advance_to_mediation(disp["id"])
        assert med1["status"] == "MEDIATION"
        reopened = reopen_investigation(disp["id"])
        assert reopened["status"] == "UNDER_INVESTIGATION"
        med2 = advance_to_mediation(disp["id"])
        assert med2["status"] == "MEDIATION"
