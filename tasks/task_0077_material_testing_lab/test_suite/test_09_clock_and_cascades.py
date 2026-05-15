"""Clock-advance sweeps and their cascading state changes (PRD §2.5, §2.10,
§3.4, §3.5)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    anchor_plus,
    api_client,
    assert_test_task,
    create_tester,
    iso,
    parse_iso,
    qualification,
    setup_assigned_task_with_short_calibration,
    TEST_USERS,
    update_tester_payload,
    validate_error,
    validate_success,
)


class TestInstrumentCalibrationLapseCascade:
    """Difficulty-design instance: instrument_calibration_lapse_cascade
    (transitive cascade, depth >= 3)."""

    def test_calibration_lapse_flips_instrument_status(
        self, api, lab_manager_headers, lab_clerk_headers,
    ):
        """PRD §3.4 / state machine: 'Clock-advance sweep at
        calibration_valid_to + 1ms; auto' moves the instrument from
        AVAILABLE to CALIBRATION_DUE.

        Difficulty-design: instrument_calibration_lapse_cascade
        (primary-effect-only branch).

        The PRD pins the cascade rule as "every future-dated RESERVED
        booking whose slot_start lies after the lapsed boundary is
        cancelled" — but PRD §3.4 also forbids creating a booking whose
        slot_start lies after calibration_valid_to (priority-13
        ERR_BOOKING_OUTSIDE_CALIBRATION). The PRD-only reader cannot
        reach a state where such a booking exists without out-of-band
        manipulation, so we limit this test to the directly-derivable
        primary effect: Instrument.status flips to CALIBRATION_DUE.

        Claim: after /_clock/advance crosses calibration_valid_to,
        Instrument.status == CALIBRATION_DUE.
        """
        # difficulty: transitive_cascade/instrument_calibration_lapse_cascade
        from test_helpers import create_instrument
        calibration_end = anchor_plus(days=10)
        instrument = create_instrument(
            capabilities=["COMPRESSION_STRENGTH"],
            calibration_valid_from=anchor_plus(days=-30),
            calibration_valid_to=calibration_end,
        )
        assert instrument["status"] == "AVAILABLE"
        # Advance clock past calibration_valid_to.
        advance_to = iso(parse_iso(calibration_end) +
                         _timedelta(seconds=1))
        advance_clock_to(to=advance_to)
        instr = validate_success(
            api.get_instrument(instrument["id"], lab_manager_headers),
        )
        assert instr["status"] == "CALIBRATION_DUE"


def _timedelta(*, seconds: int = 0, days: int = 0):
    from datetime import timedelta as _td
    return _td(seconds=seconds, days=days)


class TestQualificationPostureAtClockAdvance:
    def test_clock_advance_lapses_qualification_and_cascades(
        self, api, lab_manager_headers,
    ):
        """PRD §3.5: 'When a tester flips to LAPSED — every ASSIGNED
        TestTask belonging to that tester is auto-reverted to
        PENDING_ASSIGNMENT, with the tester's active_task_count
        decremented and assigned_tester_id cleared on each reverted
        task.'

        Difficulty-design:
        tester_qualification_posture_at_mutation_vs_at_clock_advance
        (Branch B — at_clock_advance variant).

        Claim: after /_clock/advance crosses the qualification's
        valid_to, the tester's posture is LAPSED, every ASSIGNED task
        is reverted to PENDING_ASSIGNMENT, and active_task_count drops
        to 0.
        """
        # difficulty: dual_variant_calc/tester_qualification_posture_at_mutation_vs_at_clock_advance
        from test_helpers import (
            create_client, create_sample, create_task,
        )
        # The qualification's valid_to is at CLOCK_ANCHOR + 30 days (a
        # date strictly after both the server's wall-clock start AND
        # any previously-advanced clock value). We then advance past it.
        from datetime import timedelta
        from test_helpers import CLOCK_ANCHOR
        valid_to_dt = CLOCK_ANCHOR + timedelta(days=30)
        valid_to_str = valid_to_dt.strftime("%Y-%m-%d")
        client = create_client()
        tester = create_tester(
            qualifications=[
                qualification(
                    "CONCRETE", "2024-01-01", valid_to_str,
                ),
            ],
            max_concurrent_tasks=5,
        )
        sample = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        task = create_task(
            sample_id=sample["id"], test_method="COMPRESSION_STRENGTH",
        )
        assert task["status"] == "ASSIGNED"
        assert task["assigned_tester_id"] == tester["id"]
        # Advance past valid_to.
        advance_to = iso(valid_to_dt + timedelta(days=1))
        advance_clock_to(to=advance_to)
        # Tester posture should be LAPSED.
        refreshed_tester = validate_success(
            api.get_tester(tester["id"], lab_manager_headers),
        )
        assert refreshed_tester["qualification_posture"] == "LAPSED"
        # Task reverted.
        refreshed_task = validate_success(
            api.get_task(task["id"], lab_manager_headers),
        )
        assert refreshed_task["status"] == "PENDING_ASSIGNMENT"
        assert refreshed_task["assigned_tester_id"] is None
        assert refreshed_tester["active_task_count"] == 0


class TestQualificationPostureAtMutation:
    def test_mutation_to_empty_qualifications_does_not_cascade(
        self, api, lab_manager_headers,
    ):
        """PRD §3.5: 'The mutation-triggered reconciliation only updates
        the tester's own row; the clock-advance reconciliation
        additionally cascades when a tester flips to LAPSED.'

        Difficulty-design:
        tester_qualification_posture_at_mutation_vs_at_clock_advance
        (Branch A — at_mutation variant).

        Claim: PATCH /testers/{id} setting qualifications=[] sets
        posture=LAPSED but the previously-ASSIGNED task remains
        ASSIGNED (no cascade under the at_mutation variant).
        """
        # difficulty: dual_variant_calc/tester_qualification_posture_at_mutation_vs_at_clock_advance
        from test_helpers import (
            create_client, create_sample, create_task,
        )
        client = create_client()
        tester = create_tester(
            qualifications=[
                qualification("CONCRETE", "2024-01-01", "2200-12-31"),
            ],
            max_concurrent_tasks=5,
        )
        sample = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        task = create_task(
            sample_id=sample["id"], test_method="COMPRESSION_STRENGTH",
        )
        assert task["status"] == "ASSIGNED"
        # PATCH to empty qualifications array. The tester row was version-
        # bumped by the auto-assignment (active_task_count incremented), so
        # refresh before issuing the PATCH to avoid an ERR_VERSION_CONFLICT
        # under the PRD §2.4 OCC contract.
        tester = validate_success(
            api.get_tester(tester["id"], lab_manager_headers),
        )
        patch_resp = api.update_tester(
            tester["id"],
            update_tester_payload(
                version=tester["version"], qualifications=[],
            ),
            lab_manager_headers,
        )
        patched = validate_success(patch_resp)
        assert patched["qualification_posture"] == "LAPSED"
        # Task is still ASSIGNED (no cascade under at_mutation).
        refreshed_task = validate_success(
            api.get_task(task["id"], lab_manager_headers),
        )
        assert refreshed_task["status"] == "ASSIGNED"
        assert refreshed_task["assigned_tester_id"] == tester["id"]


class TestReportArchiveSweep:
    def test_issued_report_auto_archives_after_30_days(
        self, api, lab_manager_headers,
    ):
        """PRD §3.9: 'If no recall happens within 30 days of issued_at,
        the clock-advance sweep auto-transitions the report to
        ARCHIVED (terminal). The boundary is inclusive on the archive
        side: when the logical clock is at or beyond issued_at plus 30
        days, the sweep moves the report to ARCHIVED.'

        Claim: an ISSUED report whose issued_at is 30+ days in the past
        of the new clock instant transitions to ARCHIVED on the sweep.
        """
        from test_helpers import setup_issued_report
        env = setup_issued_report()
        issued_at = env["report"]["issued_at"]
        from datetime import timedelta
        target = iso(parse_iso(issued_at) + timedelta(days=31))
        advance_clock_to(to=target)
        refreshed = validate_success(
            api.get_report(env["report"]["id"], lab_manager_headers),
        )
        assert refreshed["status"] == "ARCHIVED"
