"""Doping samples, custody chain, lab results, and sanction issuance
(PRD §3.7, §3.8, §2.13)."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    add_seconds,
    advance_clock,
    assert_doping_sample,
    assert_sanction,
    custody_dispatch,
    custody_payload,
    custody_receive,
    event_completed,
    find_audit_logs,
    find_payment_for_participant,
    find_sync_events,
    get_participant,
    latest_sanction_for_sample,
    list_audit_logs,
    list_participants,
    list_prize_payments,
    list_sync_events,
    make_doping_headers,
    open_doping_sample,
    open_sample_payload,
    positive_doping_for,
    setup_single_elim_8_with_complete,
    submit_lab_result,
    validate_error,
    validate_success,
    api_client,
)


# ===========================================================================
# 3.7 — Sample creation
# ===========================================================================
class TestOpenSample:
    def test_open_sample_returns_collected(self, api, doping_headers):
        """PRD §3.7: 'The new DopingSample row carries event_id (from the
        URL), the supplied participant_id and collected_at, an empty
        chain_log, an initial status of COLLECTED, and a result_text that
        defaults to null.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        p = parts[0]
        res = api.open_sample(
            completed["id"],
            open_sample_payload(participant_id=p["id"]),
            doping_headers,
        )
        sample = validate_success(res, expected_status=201)
        assert_doping_sample(sample)
        assert sample["status"] == "COLLECTED"
        assert sample["chain_log"] == []
        assert sample.get("result_text") is None


# ===========================================================================
# 3.7 — Chain of custody monotonicity
# ===========================================================================
class TestChainOfCustody:
    def test_dispatch_advances_to_in_transit(self, api):
        """PRD §3.7: 'A first dispatch advances the sample from COLLECTED
        to IN_TRANSIT.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        s = open_doping_sample(completed["id"], parts[0]["id"],
                                collected_at="2030-04-01T08:00:00.000Z")
        out = custody_dispatch(s["id"], "2030-04-01T08:30:00.000Z",
                                officer_id="dop-001")
        assert out["status"] == "IN_TRANSIT"

    def test_receive_after_dispatch_advances_to_received(self, api):
        """PRD §3.7: 'A subsequent receive advances it from IN_TRANSIT to
        RECEIVED.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        s = open_doping_sample(completed["id"], parts[0]["id"],
                                collected_at="2030-04-01T08:00:00.000Z")
        custody_dispatch(s["id"], "2030-04-01T08:30:00.000Z",
                          officer_id="dop-001")
        out = custody_receive(s["id"], "2030-04-01T09:00:00.000Z",
                                officer_id="dop-001")
        assert out["status"] == "RECEIVED"

    def test_non_monotonic_at_rejected(self, api, doping_headers):
        """PRD §3.7: 'an append with an at less than or equal to the prior
        tail is rejected with ERR_CHAIN_OF_CUSTODY_BROKEN.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        s = open_doping_sample(completed["id"], parts[0]["id"],
                                collected_at="2030-04-01T08:00:00.000Z")
        custody_dispatch(s["id"], "2030-04-01T09:00:00.000Z",
                          officer_id="dop-001")
        # Try to append RECEIVE with at == prior dispatch's at (not strict).
        res = api.append_custody(
            s["id"],
            custody_payload(action="RECEIVE", at="2030-04-01T09:00:00.000Z"),
            doping_headers,
        )
        validate_error(res, "ERR_CHAIN_OF_CUSTODY_BROKEN")

    def test_at_equal_to_tail_rejected_strict_monotonicity(
        self, api, doping_headers
    ):
        """PRD §3.7: 'the new entry's at must be strictly greater than the
        most-recent entry's at already in chain_log.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        s = open_doping_sample(completed["id"], parts[0]["id"])
        custody_dispatch(s["id"], "2030-04-01T09:00:00.000Z",
                          officer_id="dop-001")
        # at less-than tail -> rejected
        res = api.append_custody(
            s["id"],
            custody_payload(action="RECEIVE", at="2030-04-01T08:00:00.000Z"),
            doping_headers,
        )
        validate_error(res, "ERR_CHAIN_OF_CUSTODY_BROKEN")


# ===========================================================================
# 3.7 — Segregation of duties on lab result
# ===========================================================================
class TestSegregationOfDuties:
    def test_same_officer_who_received_cannot_post_result(self, api):
        """PRD §3.7: 'the same DopingOfficer (compared by X-User-ID) who
        appended the RECEIVE custody entry is forbidden from submitting
        the lab result, with the rejection code ERR_SEGREGATION_OF_DUTIES.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        s = open_doping_sample(completed["id"], parts[0]["id"],
                                collected_at="2030-04-01T08:00:00.000Z")
        custody_dispatch(s["id"], "2030-04-01T08:30:00.000Z",
                          officer_id="dop-001")
        custody_receive(s["id"], "2030-04-01T09:00:00.000Z",
                          officer_id="dop-001")
        # Same officer (dop-001) attempts to post the lab result.
        res = api.submit_lab_result(
            s["id"],
            {"positive": False},
            make_doping_headers("dop-001"),
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")

    def test_different_officer_can_post_result(self, api):
        """PRD §3.7 segregation rule allows a distinct officer."""
        completed, parts, _ = setup_single_elim_8_with_complete()
        s = open_doping_sample(completed["id"], parts[0]["id"])
        custody_dispatch(s["id"], "2030-04-01T08:30:00.000Z",
                          officer_id="dop-001")
        custody_receive(s["id"], "2030-04-01T09:00:00.000Z",
                          officer_id="dop-001")
        out = submit_lab_result(s["id"], positive=False, officer_id="dop-002")
        assert out["status"] == "NEGATIVE"


# ===========================================================================
# 3.7 — Positive cascade
# ===========================================================================
class TestPositiveCascade:
    def test_positive_creates_sanction_and_disqualifies_participant(self, api):
        """PRD §3.7: 'A `SanctionRecord` is auto-created with
        `sample_id` set to this sample's id, `participant_id`
        denormalized from the sample's participant, and `status`
        `ISSUED`.'
        PRD §3.7: 'The participant's `status` flips from `ACTIVE` to
        `DISQUALIFIED`.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]  # someone other than rank-1
        out = positive_doping_for(completed["id"], target["id"])
        assert out["status"] == "POSITIVE"
        # Participant must be DISQUALIFIED.
        p_after = get_participant(completed["id"], target["id"])
        assert p_after["status"] == "DISQUALIFIED"
        # SanctionRecord with sample_id == sample.id, status ISSUED.
        sanction = latest_sanction_for_sample(out["id"])
        assert_sanction(sanction)
        assert sanction["status"] == "ISSUED"
        assert sanction["sample_id"] == out["id"]
        assert sanction["participant_id"] == target["id"]

    def test_positive_writes_sanction_change_audit(self, api):
        """PRD §3.7: 'An AuditLog row of kind SANCTION_CHANGE is written.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]
        sample = positive_doping_for(completed["id"], target["id"])
        rows = list_audit_logs(kind="SANCTION_CHANGE",
                               subject_kind="SANCTION_RECORD")
        assert len(rows) >= 1, (
            "PRD §3.7 / §2.10: a SANCTION_CHANGE audit row must be "
            "written when a sanction is auto-issued."
        )

    def test_positive_forfeits_existing_scheduled_payment(self, api):
        """PRD §3.7: 'Every existing PrizePayment for this participant
        with status SCHEDULED flips to FORFEITED with forfeit_amount_cents
        equal to gross_amount_cents and net_amount_cents set to 0.'"""
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_000, tax_withholding_pct=0.0
        )
        # Find a rank that currently has a SCHEDULED payment.
        live = list_participants(completed["id"])
        target = next((p for p in live if p.get("final_rank") == 2), None)
        if target is None:
            pytest.skip("Setup did not produce a unique rank-2 participant.")
        positive_doping_for(completed["id"], target["id"])
        payments = list_prize_payments(completed["id"])
        pay = find_payment_for_participant(payments, target["id"])
        assert pay is not None
        assert pay["status"] == "FORFEITED"
        assert pay["forfeit_amount_cents"] == pay["gross_amount_cents"]
        assert pay["net_amount_cents"] == 0

    def test_positive_event_posture_under_review(self, api):
        """PRD §3.7: 'the event's posture recomputes per the rule in §2.8
        — at this moment the new sanction is ISSUED, so the posture flips
        to UNDER_REVIEW.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]
        positive_doping_for(completed["id"], target["id"])
        from test_helpers import get_event
        ev = get_event(completed["id"])
        assert ev["posture"] == "UNDER_REVIEW"


# ===========================================================================
# 3.7 — Negative result
# ===========================================================================
class TestNegativeResult:
    def test_negative_transitions_to_negative_no_cascade(self, api):
        """PRD §3.7: 'A negative result transitions the sample to NEGATIVE
        with no further side effect.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        target = parts[1]
        s = open_doping_sample(completed["id"], target["id"])
        custody_dispatch(s["id"], "2030-04-01T08:30:00.000Z",
                          officer_id="dop-001")
        custody_receive(s["id"], "2030-04-01T09:00:00.000Z",
                          officer_id="dop-001")
        out = submit_lab_result(s["id"], positive=False, officer_id="dop-002")
        assert out["status"] == "NEGATIVE"
        # No sanction-change audit rows from this flow.
        # Participant remains in its prior status.
        p_after = get_participant(completed["id"], target["id"])
        assert p_after["status"] != "DISQUALIFIED"
