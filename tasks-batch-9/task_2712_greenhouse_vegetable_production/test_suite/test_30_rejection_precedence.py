"""Rejection precedence when one request breaks several rules at once.

The greenhouse contract fixes exactly which rejection a caller sees, because
growers use the returned error to decide what to fix first. These tests build
requests that genuinely violate two rules of different categories and pin the
reported error to the lower-numbered rule.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    cold_chain_event,
    create_harvest_lot_payload,
    create_harvest_worker,
    create_posture_override,
    create_scout_worker,
    file_observation,
    grade_harvest_lot_payload,
    make_harvest_supervisor_headers,
    read_crop_cycle,
    read_lot,
    read_zone,
    setup_cold_held_lot,
    setup_production_cycle,
    validate_error,
    validate_paginated,
)

GM = TEST_USERS["grower_manager_headers"]

PRODUCTION_CLOCK = "2026-08-24T06:00:00Z"
FIRST_HARVEST_ALLOWED_DATE = "2026-08-24"
EARLY_HARVEST_DATE = "2026-08-20"


def _pest_locked_production_zone():
    """A PRODUCTION cycle whose compartment carries two open pest alerts."""
    state = setup_production_cycle(production_clock=PRODUCTION_CLOCK)
    scout = create_scout_worker()
    harvester = create_harvest_worker()
    file_observation(
        state["zone"]["id"],
        state["cycle"]["id"],
        scout["id"],
        observed_at="2026-08-24T05:00:00Z",
        pest_code="WHITEFLY",
        pest_count_per_plant=0.800,
    )
    file_observation(
        state["zone"]["id"],
        state["cycle"]["id"],
        scout["id"],
        observed_at="2026-08-24T05:30:00Z",
        pest_code="THRIPS",
        pest_count_per_plant=1.100,
    )
    state["scout"] = scout
    state["harvester"] = harvester
    return state


def _released_lot():
    """A 2000 lb lot graded 1200 / 700 / 100 and driven to the terminal RELEASED."""
    state = setup_cold_held_lot(production_clock=PRODUCTION_CLOCK)
    state["lot"] = cold_chain_event(state["lot"]["id"], "RELEASED", 5.5)
    return state


class TestPestLockOutranksEarlyHarvest:
    """A picked lot registered too early into a pest-locked compartment."""

    def test_pest_lock_is_reported_ahead_of_the_early_harvest_date(self, api):
        """PRD §2.10: "Validation rules are evaluated in a strict ascending priority order, and **the first violated rule determines the response**."

        Design: Difficulty/priority_pair_validation_conflict/ipm_lock_outranks_harvest_too_early_on_lot_registration
        """
        state = _pest_locked_production_zone()
        cycle = read_crop_cycle(state["cycle"]["id"])
        assert cycle["first_harvest_allowed_date"] == FIRST_HARVEST_ALLOWED_DATE, (
            "a 13-week cultivar first harvesting in week 4 off a 2026-08-03 transplant "
            f"allows picking from {FIRST_HARVEST_ALLOWED_DATE}, got "
            f"{cycle['first_harvest_allowed_date']}"
        )
        zone = read_zone(state["zone"]["id"])
        assert zone["open_pest_alert_count"] == 2, (
            f"two at-or-above observations open two alerts, got "
            f"{zone['open_pest_alert_count']}"
        )
        assert zone["ipm_posture"] == "LOCKED", (
            f"two open alerts lock the pest gate, got {zone['ipm_posture']}"
        )
        assert zone["reentry_clear_at"] is None, (
            "no release has run, so the re-entry clock is still null, got "
            f"{zone['reentry_clear_at']}"
        )

        response = api.create_harvest_lot(
            create_harvest_lot_payload(
                state["cycle"]["id"], harvest_date=EARLY_HARVEST_DATE
            ),
            make_harvest_supervisor_headers(state["harvester"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ZONE_IPM_LOCKED.value)

    def test_clearing_the_pest_lock_exposes_the_early_harvest_rejection(self, api):
        """PRD §3.9: "The lot's `harvest_date` must not fall before the cycle's `first_harvest_allowed_date` from §3.2, and an early pick is rejected with `ERR_HARVEST_TOO_EARLY`."

        Design: Difficulty/priority_pair_validation_conflict/ipm_lock_outranks_harvest_too_early_on_lot_registration
        """
        state = _pest_locked_production_zone()
        payload = create_harvest_lot_payload(
            state["cycle"]["id"], harvest_date=EARLY_HARVEST_DATE
        )
        supervisor = make_harvest_supervisor_headers(state["harvester"]["id"])

        validate_error(
            api.create_harvest_lot(payload, supervisor),
            ApiErrorId.ERR_ZONE_IPM_LOCKED.value,
        )

        locked_zone = read_zone(state["zone"]["id"])
        cleared = create_posture_override(
            locked_zone["id"], locked_zone["version"], target_field="ipm_posture"
        )
        assert cleared["ipm_posture"] == "NORMAL", (
            f"the override forces the pest gate to NORMAL, got {cleared['ipm_posture']}"
        )

        validate_error(
            api.create_harvest_lot(payload, supervisor),
            ApiErrorId.ERR_HARVEST_TOO_EARLY.value,
        )

        lots, meta = validate_paginated(
            api.list_harvest_lots(GM, params={"crop_cycle_id": state["cycle"]["id"]})
        )
        assert lots == [], f"neither refused registration may write a lot, got {lots}"
        assert meta["total_count"] == 0, (
            f"no lot row may exist for the cycle, got total_count {meta['total_count']}"
        )
        cycle = read_crop_cycle(state["cycle"]["id"])
        assert cycle["cumulative_harvested_lbs"] == pytest.approx(0.00, abs=0.01), (
            "a refused registration adds no pounds to the cycle ledger, got "
            f"{cycle['cumulative_harvested_lbs']}"
        )


class TestTerminalColdChainOutranksMassBalance:
    """A regrade that both misses gross weight and targets a released lot."""

    def test_terminal_cold_chain_is_reported_ahead_of_the_unbalanced_split(self, api):
        """PRD §2.10: "No later rule is evaluated once one has fired, so a request that breaks several rules at once always returns the error belonging to the lowest-numbered rule it broke."

        Design: Difficulty/priority_pair_validation_conflict/terminal_cold_chain_outranks_mass_balance_on_regrade
        """
        state = _released_lot()
        lot = read_lot(state["lot"]["id"])
        assert lot["cold_chain_status"] == "RELEASED", (
            f"the lot must sit in the terminal RELEASED, got {lot['cold_chain_status']}"
        )
        assert lot["grading_status"] == "GRADED", (
            f"the grading dimension is still GRADED, got {lot['grading_status']}"
        )
        assert lot["pack_out_pct"] == pytest.approx(95.00, abs=0.01), (
            f"1200 A plus 700 B of a 2000 lb lot packs out at 95.00, got "
            f"{lot['pack_out_pct']}"
        )

        payload = grade_harvest_lot_payload(grade_a_lbs=1150.00)
        payload["expected_lot_version"] = lot["version"]
        response = api.regrade_harvest_lot(
            lot["id"],
            payload,
            make_harvest_supervisor_headers(state["harvest_worker"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_TERMINAL_STATE.value)

    def test_the_refused_regrade_leaves_the_released_split_untouched(self, api):
        """PRD §3.9: "The lot's `cold_chain_status` must not be `RELEASED`, since a shipped lot's grade is settled history, and an attempt is rejected with `ERR_TERMINAL_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/terminal_cold_chain_outranks_mass_balance_on_regrade
        """
        state = _released_lot()
        before = read_lot(state["lot"]["id"])

        payload = grade_harvest_lot_payload(grade_a_lbs=1150.00)
        payload["expected_lot_version"] = before["version"]
        validate_error(
            api.regrade_harvest_lot(
                before["id"],
                payload,
                make_harvest_supervisor_headers(state["harvest_worker"]["id"]),
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
        )

        after = read_lot(before["id"])
        assert after["grading_status"] == "GRADED", (
            f"a refused regrade may not advance the grading dimension, got "
            f"{after['grading_status']}"
        )
        assert after["regrade_count"] == 0, (
            f"a refused regrade may not count as a pass, got {after['regrade_count']}"
        )
        assert after["grade_a_lbs"] == pytest.approx(1200.00, abs=0.01), (
            f"the original grade A split must stand, got {after['grade_a_lbs']}"
        )
        assert after["version"] == before["version"], (
            f"a refused regrade is not a mutation, expected version "
            f"{before['version']}, got {after['version']}"
        )

    def test_a_mass_balanced_regrade_of_a_released_lot_is_still_terminal(self, api):
        """PRD §3.9: "The lot's `cold_chain_status` must not be `RELEASED`, since a shipped lot's grade is settled history, and an attempt is rejected with `ERR_TERMINAL_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/terminal_cold_chain_outranks_mass_balance_on_regrade
        """
        state = _released_lot()
        lot = read_lot(state["lot"]["id"])

        payload = grade_harvest_lot_payload(
            grade_a_lbs=1100.00, grade_b_lbs=800.00, cull_lbs=100.00
        )
        payload["expected_lot_version"] = lot["version"]
        response = api.regrade_harvest_lot(
            lot["id"],
            payload,
            make_harvest_supervisor_headers(state["harvest_worker"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_TERMINAL_STATE.value)

        after = read_lot(lot["id"])
        assert after["grade_a_lbs"] == pytest.approx(1200.00, abs=0.01), (
            "a balanced split is refused just as firmly on a released lot, got "
            f"grade_a_lbs {after['grade_a_lbs']}"
        )
