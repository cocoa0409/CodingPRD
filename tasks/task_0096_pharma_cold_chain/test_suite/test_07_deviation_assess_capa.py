"""Deviation QA assessment and CAPA opening — PRD §3.3.

Tests assess transitions CLOSED_PENDING_QA → CLOSED_ASSESSED, CAPA
opening on MAJOR/CRITICAL classifications, deviation state-precondition
guard, and sweep behaviour for OVERDUE CAPAs.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock,
    assert_capa,
    assess_deviation,
    get_capa,
    get_deviation,
    get_lot,
    list_capas,
    list_deviations,
    record_temperature_event,
    run_sweep,
    setup_accepted_lot,
    setup_basic_topology,
    setup_deviation_at_duration_boundary,
    trigger_alarm_high_and_recover,
    validate_error,
)


# ===========================================================================
# Assess state precondition — PRD §3.3
# ===========================================================================
class TestAssessStatePrecondition:

    def test_assess_on_open_deviation_returns_err_deviation_state_invalid(
        self, api,
    ):
        """PRD §3.3: "Assessment is rejected with
        `ERR_DEVIATION_STATE_INVALID` (HTTP 409) unless the deviation
        is currently in `CLOSED_PENDING_QA`."

        Claim: a Deviation row still in OPEN cannot be assessed.
        """
        topology = setup_basic_topology()
        # Open a deviation (alarm event) but do NOT recover; deviation
        # is OPEN.
        record_temperature_event(
            topology["zone"]["id"], at_minutes=0, temp_c=12.0,
        )
        deviations = list_deviations(topology["warehouse"]["id"])
        assert len(deviations) == 1
        dev = deviations[0]
        assert dev["status"] == "OPEN"
        res = api.assess_deviation(
            dev["id"],
            {"qa_decision": "QUARANTINE"},
            TEST_USERS["qa_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_DEVIATION_STATE_INVALID.value)

    def test_assess_after_closed_assessed_rejected(self, api):
        """PRD §2.11: "a duplicate assess against an already-progressed
        deviation is rejected with `ERR_DEVIATION_STATE_INVALID`
        (HTTP 409)."

        Claim: an already-assessed deviation cannot be assessed a
        second time.
        """
        topology = setup_basic_topology()
        dev = trigger_alarm_high_and_recover(
            topology["zone"]["id"], topology["warehouse"]["id"],
            alarm_temp_c=12.0, in_range_temp_c=5.0, start_minutes=1,
        )
        assess_deviation(
            dev["id"], qa_decision="QUARANTINE",
            headers=TEST_USERS["qa_officer_headers"],
        )
        # Try again.
        res = api.assess_deviation(
            dev["id"],
            {"qa_decision": "RELEASE"},
            TEST_USERS["qa_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_DEVIATION_STATE_INVALID.value)


# ===========================================================================
# QA decision → lot quality_status
# ===========================================================================
class TestAssessLotCascade:

    def test_assess_release_returns_lots_to_released(self, api):
        """PRD §3.3: "On a valid assess, each affected lot's
        `quality_status` is set according to the decision (`RELEASE`
        becomes `RELEASED`, `QUARANTINE` becomes `QUARANTINED`,
        `REJECT` becomes `REJECTED`)".

        Claim: after assess(RELEASE), affected lots in
        QUARANTINED state revert to RELEASED.

        Note: PRD §3.3 says MAJOR/CRITICAL+RELEASE require an OPEN
        capa_id. We engineer a MINOR deviation (duration < 60 and
        magnitude < 2.0) so RELEASE does not need a CAPA.
        """
        ctx = setup_accepted_lot(quantity_units=3)
        # MINOR deviation: WARNING_HIGH at 9.5 (magnitude=1.5), duration=1.
        record_temperature_event(
            ctx["zone"]["id"], at_minutes=0, temp_c=9.5,
        )
        advance_clock(ctx["warehouse"]["id"], 1)
        record_temperature_event(
            ctx["zone"]["id"], at_minutes=1, temp_c=5.0,
        )
        deviations = list_deviations(ctx["warehouse"]["id"])
        dev = deviations[-1]
        assert dev["status"] == "CLOSED_PENDING_QA"
        assert dev["classification"] == "MINOR"
        # Lot is currently QUARANTINED (cascade from deviation close).
        lot_quarantined = get_lot(ctx["lot"]["id"])
        assert lot_quarantined["quality_status"] == "QUARANTINED"
        # Assess RELEASE.
        assess_deviation(
            dev["id"], qa_decision="RELEASE",
            headers=TEST_USERS["qa_officer_headers"],
        )
        lot_after = get_lot(ctx["lot"]["id"])
        assert lot_after["quality_status"] == "RELEASED"

    def test_assess_reject_sets_lots_to_rejected(self, api):
        ctx = setup_accepted_lot(quantity_units=3)
        # Trigger a MAJOR/CRITICAL deviation so REJECT pathway is
        # exercised (CAPA-required check is for RELEASE, not REJECT).
        dev = trigger_alarm_high_and_recover(
            ctx["zone"]["id"], ctx["warehouse"]["id"],
            alarm_temp_c=12.0, in_range_temp_c=5.0, start_minutes=1,
        )
        assess_deviation(
            dev["id"], qa_decision="REJECT",
            headers=TEST_USERS["qa_officer_headers"],
        )
        lot_after = get_lot(ctx["lot"]["id"])
        assert lot_after["quality_status"] == "REJECTED"


# ===========================================================================
# CAPA opening on MAJOR / CRITICAL
# ===========================================================================
class TestCapaOpening:

    def test_major_assess_release_opens_capa_with_4320_min_due(self, api):
        """PRD §3.3: "if the classification is `MAJOR` or `CRITICAL`,
        the system opens a new `CAPA` row whose `due_minutes` is the
        deviation's closure `clock_minutes` plus 720 minutes (12 hours)
        when the classification is `CRITICAL`, or that closure plus
        4320 minutes (72 hours) when the classification is `MAJOR`."

        Claim: MAJOR deviation, RELEASE with capa_id requirement → a
        new CAPA exists with due_minutes ≈ clock_minutes_at_close +
        4320. We assert due_minutes >= closure_clock + 4320 (since
        clock may have advanced during teardown of trigger helper).

        Two-reader: PRD says "the deviation's closure `clock_minutes`
        plus 720/4320 minutes". The closure occurs inside the
        IN_RANGE event handler, so closure_clock == clock at that
        moment. We replicate that by tracking clock before and after.

        We exercise the QUARANTINE pathway (which does not need an
        existing capa_id) but still triggers CAPA opening because the
        rule is "if classification ∈ {MAJOR, CRITICAL}" — not
        contingent on RELEASE specifically.
        """
        topology = setup_basic_topology()
        # Build a MAJOR deviation: magnitude 4 C (12-8), short duration
        # 1 min → MAJOR (magnitude>=2.0).
        record_temperature_event(
            topology["zone"]["id"], at_minutes=0, temp_c=12.0,
        )
        advance_clock(topology["warehouse"]["id"], 1)
        record_temperature_event(
            topology["zone"]["id"], at_minutes=1, temp_c=5.0,
        )
        deviations = list_deviations(topology["warehouse"]["id"])
        dev = deviations[-1]
        assert dev["classification"] == "MAJOR"
        # Clock at this point — use get_warehouse to read it.
        from test_helpers import get_warehouse
        wh_before_assess = get_warehouse(topology["warehouse"]["id"])
        # Use QUARANTINE assess to skip the RELEASE+capa_id requirement.
        assess_deviation(
            dev["id"], qa_decision="QUARANTINE",
            headers=TEST_USERS["qa_officer_headers"],
        )
        capas = list_capas(topology["warehouse"]["id"])
        # PRD §3.3 ties CAPA to the originating deviation_id.
        matching = [c for c in capas if c.get("deviation_id") == dev["id"]]
        assert len(matching) == 1, (
            f"Expected exactly one CAPA originating from deviation "
            f"{dev['id']}, got {len(matching)}"
        )
        capa = matching[0]
        # PRD: due_minutes = closure_clock + 4320 (MAJOR). closure_clock
        # is when the deviation was set to CLOSED_PENDING_QA — i.e.
        # when the IN_RANGE event arrived. We advanced the clock to 1
        # before posting the IN_RANGE event, so closure_clock should
        # be 1. We assert due_minutes is exactly 1 + 4320 = 4321.
        # However the PRD prose says "clock_minutes" at closure. We
        # take a generous interpretation tolerating the clock at
        # closure being either 1 (immediately after advance_clock)
        # or 1 (after IN_RANGE event processed).
        # We assert exactly 4321 to enforce PRD precision.
        assert capa["due_minutes"] == 1 + 4320, (
            f"MAJOR CAPA due_minutes must be closure_clock + 4320; got "
            f"{capa['due_minutes']}, expected 4321"
        )
        assert capa["status"] == "OPEN"
        assert_capa(capa)


    def test_critical_assess_opens_capa_with_720_min_due(self, api):
        """PRD §3.3: "...plus 720 minutes (12 hours) when the
        classification is `CRITICAL`".

        Claim: a CRITICAL deviation produces a CAPA whose due_minutes
        is closure_clock + 720.
        """
        topology = setup_basic_topology()
        # Build a CRITICAL deviation: magnitude >= 5.0 (target_high=8,
        # reading=13.5 → magnitude 5.5).
        record_temperature_event(
            topology["zone"]["id"], at_minutes=0, temp_c=13.5,
        )
        advance_clock(topology["warehouse"]["id"], 1)
        record_temperature_event(
            topology["zone"]["id"], at_minutes=1, temp_c=5.0,
        )
        deviations = list_deviations(topology["warehouse"]["id"])
        dev = deviations[-1]
        assert dev["classification"] == "CRITICAL"
        assess_deviation(
            dev["id"], qa_decision="QUARANTINE",
            headers=TEST_USERS["qa_officer_headers"],
        )
        capas = list_capas(topology["warehouse"]["id"])
        matching = [c for c in capas if c.get("deviation_id") == dev["id"]]
        assert len(matching) == 1
        capa = matching[0]
        assert capa["due_minutes"] == 1 + 720

    def test_minor_assess_does_not_open_capa(self, api):
        """PRD §3.3: CAPA is opened only "if the classification is
        `MAJOR` or `CRITICAL`". A MINOR deviation must NOT open a
        CAPA.

        Claim: assessing a MINOR deviation does not produce any new
        CAPA row.
        """
        topology = setup_basic_topology()
        record_temperature_event(
            topology["zone"]["id"], at_minutes=0, temp_c=9.5,  # WARNING_HIGH
        )
        advance_clock(topology["warehouse"]["id"], 1)
        record_temperature_event(
            topology["zone"]["id"], at_minutes=1, temp_c=5.0,
        )
        deviations = list_deviations(topology["warehouse"]["id"])
        dev = deviations[-1]
        assert dev["classification"] == "MINOR"
        capas_before = list_capas(topology["warehouse"]["id"])
        assess_deviation(
            dev["id"], qa_decision="RELEASE",
            headers=TEST_USERS["qa_officer_headers"],
        )
        capas_after = list_capas(topology["warehouse"]["id"])
        new_capas = [
            c for c in capas_after
            if c.get("deviation_id") == dev["id"]
        ]
        assert len(new_capas) == 0


# ===========================================================================
# Helper import
# ===========================================================================
from test_helpers import list_capas  # noqa: E402


# ===========================================================================
# Sweep — OVERDUE transition
# ===========================================================================
class TestSweepOverdueCapa:

    def test_sweep_flips_capa_to_overdue_when_due_minutes_past(self, api):
        """PRD §2.7: "the sweep walks every CAPA in the warehouse and
        flips any whose `due_minutes` is strictly less than
        `clock_minutes` into `OVERDUE`".

        Claim: a CAPA with due_minutes < clock_minutes is set to
        OVERDUE by /_sweep/run.
        """
        topology = setup_basic_topology()
        # Open a MAJOR deviation/CAPA early on the clock.
        record_temperature_event(
            topology["zone"]["id"], at_minutes=0, temp_c=12.0,
        )
        advance_clock(topology["warehouse"]["id"], 1)
        record_temperature_event(
            topology["zone"]["id"], at_minutes=1, temp_c=5.0,
        )
        deviations = list_deviations(topology["warehouse"]["id"])
        dev = deviations[-1]
        assess_deviation(
            dev["id"], qa_decision="QUARANTINE",
            headers=TEST_USERS["qa_officer_headers"],
        )
        capas = list_capas(topology["warehouse"]["id"])
        capa = [c for c in capas if c.get("deviation_id") == dev["id"]][0]
        # due_minutes is closure_clock + 4320 = 1 + 4320 = 4321.
        # Advance clock past it.
        advance_clock(topology["warehouse"]["id"], 4500)
        run_sweep(topology["warehouse"]["id"])
        capa_after = get_capa(capa["id"])
        assert capa_after["status"] == "OVERDUE"
