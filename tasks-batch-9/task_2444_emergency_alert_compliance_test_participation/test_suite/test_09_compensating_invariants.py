"""Compensating invariants: undoing a write must restore the exact prior figure.

Three round trips are exercised: reversing a filing and returning the station's
penalty ledger to its pre-filing value, decommissioning and reinstating a
monitoring assignment, and superseding an assignment so that coverage is swapped
rather than added to. Each round trip is paired with the guard that fires when
the same undo or redo is attempted a second time.
"""

import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    OFFICER,
    SOURCE_CALL_SIGNS,
    ApiErrorId,
    add_ready_device,
    api_client,
    assert_score_and_posture,
    assert_summary_inputs,
    assign_source,
    filing_record_payload,
    get_success_data,
    reversal_payload,
    set_clock,
    setup_logged_test_event,
    setup_station,
    station_summary,
    test_event_version as current_event_version,
    validate_error,
    validate_paginated,
    validate_success,
)

# One day past the canonical filing_deadline_at 2026-08-17T01:00:00Z, and well
# inside the ten-day grace period.
LATE_FILING_AT = "2026-08-17T02:00:00Z"


# ---------------------------------------------------------------------------
# Local setup built out of the shared primitives
# ---------------------------------------------------------------------------
def _logged_event_ready_for_a_late_filing():
    """Station scoring 100.00 with a LOGGED event carrying one TRANSMISSION and one
    RECEIPT line, clock parked one day past the filing deadline."""
    ctx = setup_logged_test_event(required_source_types=("PEP",))
    set_clock(LATE_FILING_AT)
    ctx["summary_before"] = station_summary(ctx["station_id"])
    return ctx


def _file_late(ctx):
    version = current_event_version(ctx["test_event_id"])
    filing = validate_success(
        api_client.create_filing_record(
            filing_record_payload(ctx["test_event_id"], version), OFFICER
        ),
        201,
    )
    ctx["filing"] = filing
    ctx["filing_id"] = filing["id"]
    ctx["event_version_before_filing"] = version
    return filing


class TestFilingReversalCompensation:
    def test_accepted_late_filing_charges_its_penalty_under_the_certified_variant(self):
        """PRD §3.7: "For each log line — taking every line whose `test_event_id` matches, in `created_at` ascending order, with no status filter whatsoever since log lines have no status — multiply `late_days` by a per-entry late rate of 0.065 points and by that line's kind weight, and **round that per-line product half-up to two decimal places immediately**."
        PRD §3.7: "`penalty_points` is then the smaller of a per-filing cap of 25.00 points and the sum of `entry_subtotal_points`, `lateness_points` and `unconfirmed_relay_points`, rounded half-up to two decimal places."
        PRD §3.7: "Acceptance fires a station recompute event, and its consequence is significant: an accepted filing is what makes the station eligible for the certified scoring variant of §3.8, so a station scoring a perfect 100.00 provisionally can drop two posture bands the moment its first filing is accepted."

        Design: Difficulty/compensating_invariant/filing_reversal_returns_penalty_total_to_its_exact_pre_filing_value
        """
        ctx = _logged_event_ready_for_a_late_filing()
        assert ctx["summary_before"]["penalty_points_total"] == pytest.approx(0.00, abs=0.01)
        assert ctx["summary_before"]["compliance_variant_applied"] == "PROVISIONAL"
        assert_score_and_posture(ctx["summary_before"], 100.00, "COMPLIANT")

        filing = _file_late(ctx)
        assert filing["status"] == "SUBMITTED"
        assert filing["reversal_reason"] is None
        assert filing["superseded_filing_id"] is None
        assert filing["late_days"] == 1
        assert filing["entry_subtotal_points"] == pytest.approx(0.19, abs=0.01)
        assert filing["lateness_points"] == pytest.approx(0.75, abs=0.01)
        assert filing["unconfirmed_relay_points"] == pytest.approx(0.00, abs=0.01)
        assert filing["penalty_points"] == pytest.approx(0.94, abs=0.01)

        event = get_success_data(api_client.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["status"] == "FILED"
        assert event["version"] == ctx["event_version_before_filing"] + 1

        submitted_summary = station_summary(ctx["station_id"])
        assert submitted_summary["penalty_points_total"] == pytest.approx(0.94, abs=0.01)
        assert submitted_summary["compliance_variant_applied"] == "PROVISIONAL"
        assert_score_and_posture(submitted_summary, 100.00, "COMPLIANT")

        accepted = validate_success(
            api_client.accept_filing(ctx["filing_id"], ADMIN), 200
        )
        assert accepted["status"] == "ACCEPTED"

        certified_summary = station_summary(ctx["station_id"])
        assert certified_summary["compliance_variant_applied"] == "CERTIFIED"
        assert certified_summary["penalty_points_total"] == pytest.approx(0.94, abs=0.01)
        assert_score_and_posture(certified_summary, 99.06, "COMPLIANT")

    def test_reversal_returns_the_penalty_total_to_its_exact_pre_filing_value(self):
        """PRD §3.7: "Reversal writes the supplied `reversal_reason`, removes the row from the `penalty_points_total` input set so that the station's total returns to its exact pre-filing value, and fires a station recompute event."
        PRD §3.7: "Filings whose `status` is `REVERSED` contribute nothing to that sum, which is the mechanism that makes reversal an exact compensation rather than an approximate one."
        PRD §3.8: "the station's `penalty_points_total` verbatim, point for point — **certified variant only**."

        Design: Difficulty/compensating_invariant/filing_reversal_returns_penalty_total_to_its_exact_pre_filing_value
        """
        ctx = _logged_event_ready_for_a_late_filing()
        pts_before = ctx["summary_before"]["penalty_points_total"]
        score_before = ctx["summary_before"]["compliance_score"]

        _file_late(ctx)
        get_success_data(api_client.accept_filing(ctx["filing_id"], ADMIN))

        reversed_filing = validate_success(
            api_client.reverse_filing(
                ctx["filing_id"],
                reversal_payload(reversal_reason="ATTESTATION_WITHDRAWN"),
                ADMIN,
            ),
            200,
        )
        assert reversed_filing["status"] == "REVERSED"
        assert reversed_filing["reversal_reason"] == "ATTESTATION_WITHDRAWN"
        assert reversed_filing["penalty_points"] == pytest.approx(0.94, abs=0.01), (
            "the reversed row keeps its own computed penalty"
        )
        assert reversed_filing["late_days"] == 1
        assert reversed_filing["superseded_filing_id"] is None

        summary = station_summary(ctx["station_id"])
        assert summary["penalty_points_total"] == pytest.approx(pts_before, abs=0.01)
        assert summary["penalty_points_total"] == pytest.approx(0.00, abs=0.01)
        assert summary["compliance_variant_applied"] == "PROVISIONAL"
        assert summary["compliance_score"] == pytest.approx(score_before, abs=0.01)
        assert_score_and_posture(summary, 100.00, "COMPLIANT")
        assert_summary_inputs(summary, unfiled_test_count=0)

        event = get_success_data(api_client.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["status"] == "FILED", "reversal withdraws the ledger entry, not the filing"

    def test_second_reversal_is_rejected_and_the_ledger_does_not_drift(self):
        """PRD §3.7: "Reversal by a `ComplianceAdmin` carries an explicit `reversal_reason` in the payload and is permitted from two starting statuses with identical effect — `SUBMITTED` → `REVERSED` and `ACCEPTED` → `REVERSED`; a filing already in `REVERSED` is rejected with `ERR_FILING_NOT_REVERSIBLE`, and `REVERSED` is terminal."

        Design: Difficulty/compensating_invariant/filing_reversal_returns_penalty_total_to_its_exact_pre_filing_value
        """
        ctx = _logged_event_ready_for_a_late_filing()
        _file_late(ctx)
        get_success_data(api_client.accept_filing(ctx["filing_id"], ADMIN))
        get_success_data(
            api_client.reverse_filing(ctx["filing_id"], reversal_payload(), ADMIN)
        )

        validate_error(
            api_client.reverse_filing(ctx["filing_id"], reversal_payload(), ADMIN),
            ApiErrorId.ERR_FILING_NOT_REVERSIBLE,
            409,
        )

        summary = station_summary(ctx["station_id"])
        assert summary["penalty_points_total"] == pytest.approx(0.00, abs=0.01)
        assert_score_and_posture(summary, 100.00, "COMPLIANT")


class TestAssignmentReinstatementCompensation:
    def test_decommission_then_reinstate_restores_coverage_and_score_exactly(self):
        """PRD §3.3: "Deliberate retirement of an assignment by a `StationEngineer` is permitted from three starting statuses with identical effect — `ACTIVE` → `DECOMMISSIONED`, `SILENT` → `DECOMMISSIONED` and `SUSPENDED` → `DECOMMISSIONED` — each recomputing the station's `accessible_source_count` and firing a station recompute event; attempting it on a row already in `DECOMMISSIONED` is rejected with `ERR_ASSIGNMENT_NOT_ACTIVE`."
        PRD §3.3: "A successful reinstatement likewise recomputes `accessible_source_count` and fires a station recompute event."
        PRD §3.8: "25.00 points for every required source type the station is missing, where the missing count is the plan's `required_source_count` less the station's `accessible_source_count`, floored at zero so that over-coverage never earns a credit;"

        Design: Difficulty/compensating_invariant/assignment_decommission_then_reinstate_restores_coverage_without_drift
        """
        ctx = setup_station(required_source_types=("PEP", "SATELLITE"))
        assignment_id = ctx["assignments"]["PEP"]["id"]

        baseline = station_summary(ctx["station_id"])
        assert_summary_inputs(
            baseline,
            required_source_count=2,
            accessible_source_count=2,
            missing_source_count=0,
            silent_assignment_count=0,
        )
        assert_score_and_posture(baseline, 100.00, "COMPLIANT")

        retired = get_success_data(
            api_client.decommission_assignment(assignment_id, ENGINEER)
        )
        assert retired["status"] == "DECOMMISSIONED"
        assert retired["counts_toward_required_sources"] is False

        lapsed = station_summary(ctx["station_id"])
        assert_summary_inputs(
            lapsed, accessible_source_count=1, missing_source_count=1
        )
        assert_score_and_posture(lapsed, 75.00, "WATCH")

        reinstated = validate_success(
            api_client.reinstate_assignment(assignment_id, ENGINEER), 200
        )
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["counts_toward_required_sources"] is True
        assert reinstated["silence_flagged_at"] is None

        restored = station_summary(ctx["station_id"])
        assert restored["accessible_source_count"] == baseline["accessible_source_count"]
        assert restored["compliance_score"] == pytest.approx(
            baseline["compliance_score"], abs=0.01
        )
        assert_summary_inputs(
            restored,
            accessible_source_count=2,
            missing_source_count=0,
            silent_assignment_count=0,
        )
        assert_score_and_posture(restored, 100.00, "COMPLIANT")

    def test_second_reinstate_is_rejected_and_coverage_is_not_double_counted(self):
        """PRD §3.3: "Reinstatement runs the other way, `DECOMMISSIONED` → `ACTIVE`, and carries three preconditions: the row must currently be `DECOMMISSIONED`, otherwise `ERR_ASSIGNMENT_NOT_DECOMMISSIONED`; no other assignment of the same station may be in `ACTIVE` with the same `source_type`, otherwise `ERR_SOURCE_TYPE_ALREADY_COVERED`; and the referenced unit must currently be in `READY`, otherwise `ERR_DEVICE_NOT_READY`."

        Design: Difficulty/compensating_invariant/assignment_decommission_then_reinstate_restores_coverage_without_drift
        """
        ctx = setup_station(required_source_types=("PEP", "SATELLITE"))
        assignment_id = ctx["assignments"]["PEP"]["id"]
        get_success_data(api_client.decommission_assignment(assignment_id, ENGINEER))
        get_success_data(api_client.reinstate_assignment(assignment_id, ENGINEER))

        validate_error(
            api_client.reinstate_assignment(assignment_id, ENGINEER),
            ApiErrorId.ERR_ASSIGNMENT_NOT_DECOMMISSIONED,
            409,
        )

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(
            summary, accessible_source_count=2, missing_source_count=0
        )
        assert_score_and_posture(summary, 100.00, "COMPLIANT")


class TestSupersedeConservesOneActiveRowPerSourceType:
    def test_replacement_assignment_swaps_coverage_without_a_dip(self):
        """PRD §3.3: "If the station already had an `ACTIVE` assignment for the same `source_type`, that older row is pushed `ACTIVE` → `DECOMMISSIONED` and the new row's `superseded_assignment_id` is set to the older row's `id`; when no such row existed, `superseded_assignment_id` stays null."
        PRD §3.3: "The station's `accessible_source_count` is recomputed exactly once, *after* the supersede has landed, and then the create fires a station recompute event."
        PRD §3.3: "Assignments can be listed filtered by `station_id`, `device_id`, `source_type`, `status` and `superseded_assignment_id`."

        Design: Difficulty/compensating_invariant/supersede_conserves_exactly_one_active_row_per_source_type
        """
        ctx = setup_station(required_source_types=("PEP",))
        first_id = ctx["assignments"]["PEP"]["id"]
        baseline = station_summary(ctx["station_id"])
        assert_summary_inputs(baseline, accessible_source_count=1)
        assert_score_and_posture(baseline, 100.00, "COMPLIANT")

        second_device = add_ready_device(ctx, device_role="MONITOR")
        replacement = assign_source(
            ctx["station_id"],
            second_device["id"],
            source_type="PEP",
            source_call_sign="WXPEP2",
        )
        assert replacement["status"] == "ACTIVE"
        assert replacement["counts_toward_required_sources"] is True
        assert replacement["superseded_assignment_id"] == first_id

        superseded = get_success_data(
            api_client.get_monitoring_assignment(first_id, ADMIN)
        )
        assert superseded["status"] == "DECOMMISSIONED"
        assert superseded["counts_toward_required_sources"] is False
        assert superseded["superseded_assignment_id"] is None, (
            "the pointer lives on the new row"
        )

        summary = station_summary(ctx["station_id"])
        assert summary["accessible_source_count"] == baseline["accessible_source_count"]
        assert_summary_inputs(summary, accessible_source_count=1, missing_source_count=0)
        assert_score_and_posture(summary, 100.00, "COMPLIANT")

        referring, referring_meta = validate_paginated(
            api_client.list_monitoring_assignments(
                ADMIN,
                params={
                    "station_id": ctx["station_id"],
                    "superseded_assignment_id": first_id,
                },
            )
        )
        assert referring_meta["total_count"] == 1, f"expected one successor, got {referring}"
        assert referring[0]["id"] == replacement["id"]

        live, live_meta = validate_paginated(
            api_client.list_monitoring_assignments(
                ADMIN,
                params={
                    "station_id": ctx["station_id"],
                    "source_type": "PEP",
                    "status": "ACTIVE",
                },
            )
        )
        assert live_meta["total_count"] == 1, f"expected one ACTIVE PEP row, got {live}"
        assert live[0]["id"] == replacement["id"]
        assert live[0]["source_call_sign"] != SOURCE_CALL_SIGNS["PEP"], (
            "the surviving row is the replacement, not the superseded original"
        )

    def test_superseded_assignment_cannot_be_reinstated_while_its_successor_is_active(self):
        """PRD §3.3: "Reinstatement runs the other way, `DECOMMISSIONED` → `ACTIVE`, and carries three preconditions: the row must currently be `DECOMMISSIONED`, otherwise `ERR_ASSIGNMENT_NOT_DECOMMISSIONED`; no other assignment of the same station may be in `ACTIVE` with the same `source_type`, otherwise `ERR_SOURCE_TYPE_ALREADY_COVERED`; and the referenced unit must currently be in `READY`, otherwise `ERR_DEVICE_NOT_READY`."

        Design: Difficulty/compensating_invariant/supersede_conserves_exactly_one_active_row_per_source_type
        """
        ctx = setup_station(required_source_types=("PEP",))
        first_id = ctx["assignments"]["PEP"]["id"]
        second_device = add_ready_device(ctx, device_role="MONITOR")
        assign_source(
            ctx["station_id"],
            second_device["id"],
            source_type="PEP",
            source_call_sign="WXPEP2",
        )

        validate_error(
            api_client.reinstate_assignment(first_id, ENGINEER),
            ApiErrorId.ERR_SOURCE_TYPE_ALREADY_COVERED,
            409,
        )

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(
            summary, accessible_source_count=1, silent_assignment_count=0
        )
        assert_score_and_posture(summary, 100.00, "COMPLIANT")
