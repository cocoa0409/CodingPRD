"""Chip fleet and race-day check-in: uniqueness, assignment gates, the two
deassign dispositions, and fleet conservation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_race,
    create_chip_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLERK = TEST_USERS["registration_clerk_headers"]

LOCKED_POINTS = [
    {"key": "start", "point_index": 1, "kind": "START", "distance_km": 0.0},
    {"key": "finish", "point_index": 2, "kind": "FINISH", "distance_km": 5.0},
]
LOCKED_WAVE = {"key": "w1", "wave_index": 1,
               "scheduled_start_time": "2026-08-01T07:00:00Z", "max_capacity": 10}


def _locked_race(api, name, chips, registrations):
    return build_race(
        name=name, distance_km=5.0, course_type="UNCERTIFIED_COURSE",
        cutoff_minutes=90, points=LOCKED_POINTS, waves=[LOCKED_WAVE],
        chips=chips, registrations=registrations, lock=True)


class TestChipUniqueness:
    def test_chip_code_uniqueness_returns_409(self, api):
        """PRD §3.3: "A `RegistrationClerk` registers each **Chip** with a
        fleet-wide unique `chip_code` — a duplicate code is refused with
        `ERR_CHIP_CODE_TAKEN` — and the chip begins `AVAILABLE` with no holder,
        its `current_registration_id` null."

        Design: Corner/entities/chip_code_uniqueness_returns_409
        """
        validate_success(api.create_chip(create_chip_payload("CHIP-DUP"), CLERK), 201)
        resp = api.create_chip(create_chip_payload("CHIP-DUP"), CLERK)
        validate_error(resp, ApiErrorId.ERR_CHIP_CODE_TAKEN, expected_status=409)


class TestAssignChipGates:
    def _gate_scenario(self, api):
        return _locked_race(
            api, "Gate 5K",
            chips=[{"key": "cx", "chip_code": "CHIP-X"},
                   {"key": "cy", "chip_code": "CHIP-Y"}],
            registrations=[
                {"key": "g1", "wave": "w1", "bib_number": "411",
                 "participant_name": "G One", "birth_date": "1990-01-01",
                 "gender": "M", "chip": "cx"},
                {"key": "g2", "wave": "w1", "bib_number": "412",
                 "participant_name": "G Two", "birth_date": "1990-01-01",
                 "gender": "M"},
                {"key": "g3", "wave": "w1", "bib_number": "413",
                 "participant_name": "G Three", "birth_date": "1990-01-01",
                 "gender": "M", "pay": False, "confirm": False},
            ])

    def test_assign_rejected_by_chip_state_and_registration_state(self, api):
        """PRD §3.3: "Three conditions guard the binding, evaluated state-first.
        The registration must be `CONFIRMED` and its race must be in
        `TIMING_LOCKED` or `IN_PROGRESS` — a registration in any other lifecycle
        state, or a race outside that window, fails the state check with
        `ERR_INVALID_STATE`. The chip must be `AVAILABLE`, otherwise
        `ERR_CHIP_NOT_AVAILABLE`. And the registration must not already hold a
        chip, otherwise `ERR_CHIP_ALREADY_ASSIGNED`."

        Design: Difficulty/cross_entity_state_dependency/assign_chip_gated_by_chip_status
        """
        ctx = self._gate_scenario(api)
        # CONFIRMED registration + ASSIGNED chip: the chip's state blocks.
        resp1 = api.assign_chip(ctx["regs"]["g2"]["id"], ctx["chips"]["cx"]["id"], CLERK)
        validate_error(resp1, ApiErrorId.ERR_CHIP_NOT_AVAILABLE, expected_status=409)
        # REGISTERED (unpaid) registration + AVAILABLE chip: state-first gate.
        resp2 = api.assign_chip(ctx["regs"]["g3"]["id"], ctx["chips"]["cy"]["id"], CLERK)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_assign_success_links_registration_and_chip(self, api):
        """PRD §3.3: "A successful assignment moves the registration `CONFIRMED
        → CHECKED_IN`, moves the chip `AVAILABLE → ASSIGNED`, and links the two
        in both directions: the registration's `chip_id` is set, and the chip's
        `current_registration_id` points back."

        Design: Difficulty/cross_entity_state_dependency/assign_chip_gated_by_chip_status
        """
        ctx = self._gate_scenario(api)
        reg = validate_success(api.assign_chip(
            ctx["regs"]["g2"]["id"], ctx["chips"]["cy"]["id"], CLERK), 200)
        assert reg["lifecycle_status"] == "CHECKED_IN"
        assert reg["chip_id"] == ctx["chips"]["cy"]["id"]
        chip = validate_success(api.get_chip(ctx["chips"]["cy"]["id"], CLERK), 200)
        assert chip["status"] == "ASSIGNED"
        assert chip["current_registration_id"] == ctx["regs"]["g2"]["id"]


class TestChipRelease:
    def test_deassign_available_chip_returns_409(self, api):
        """PRD §3.3: "Releasing a chip takes a `disposition` of either `RETURNED`
        or `LOST`, and requires the chip to be `ASSIGNED` — releasing anything
        else fails with `ERR_CHIP_NOT_ASSIGNED`."

        Design: Corner/validations/deassign_available_chip_returns_409
        """
        chip = validate_success(
            api.create_chip(create_chip_payload("CHIP-AV"), CLERK), 201)
        resp = api.deassign_chip(chip["id"], "RETURNED", CLERK)
        validate_error(resp, ApiErrorId.ERR_CHIP_NOT_ASSIGNED, expected_status=409)

    def test_chip_lost_reverts_checkin(self, api):
        """PRD §3.3: "A `LOST` chip leaves the fleet permanently — `LOST` is
        terminal — and the athlete is bumped back from `CHECKED_IN` to
        `CONFIRMED`, requiring a fresh check-in with a new chip; both links are
        cleared here as well."
        PRD §3.3: "The chip must be `AVAILABLE`, otherwise
        `ERR_CHIP_NOT_AVAILABLE`."

        Design: Corner/state_machines/chip_lost_reverts_checkin
        """
        ctx = _locked_race(
            api, "Lost 5K",
            chips=[{"key": "lx", "chip_code": "CHIP-LX"}],
            registrations=[{"key": "r1", "wave": "w1", "bib_number": "730",
                            "participant_name": "L One", "birth_date": "1990-01-01",
                            "gender": "M", "chip": "lx"}])
        chip = validate_success(
            api.deassign_chip(ctx["chips"]["lx"]["id"], "LOST", CLERK), 200)
        assert chip["status"] == "LOST"
        assert chip["current_registration_id"] is None

        reg = validate_success(
            api.get_registration(ctx["regs"]["r1"]["id"], CLERK), 200)
        assert reg["lifecycle_status"] == "CONFIRMED", "LOST reverts the check-in"
        assert reg["chip_id"] is None

        resp = api.assign_chip(reg["id"], ctx["chips"]["lx"]["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_CHIP_NOT_AVAILABLE, expected_status=409)


class TestChipFleetConservation:
    def _conservation_scenario(self, api):
        return _locked_race(
            api, "Conserve 5K",
            chips=[{"key": "cx", "chip_code": "CHIP-CX"},
                   {"key": "cy", "chip_code": "CHIP-CY"}],
            registrations=[{"key": "r1", "wave": "w1", "bib_number": "511",
                            "participant_name": "Conserve One",
                            "birth_date": "1990-01-01", "gender": "M"}])

    def _available_count(self, api):
        _data, meta = validate_paginated(
            api.list_chips(CLERK, params={"status": "AVAILABLE"}))
        return meta["total_count"]

    def test_assign_consumes_one_available_chip(self, api):
        """PRD §3.3: "A successful assignment moves the registration `CONFIRMED
        → CHECKED_IN`, moves the chip `AVAILABLE → ASSIGNED`, and links the two
        in both directions: the registration's `chip_id` is set, and the chip's
        `current_registration_id` points back."

        Design: Difficulty/compensating_invariant/chip_fleet_conservation
        """
        ctx = self._conservation_scenario(api)
        assert self._available_count(api) == 2
        validate_success(api.assign_chip(
            ctx["regs"]["r1"]["id"], ctx["chips"]["cx"]["id"], CLERK), 200)
        assert self._available_count(api) == 1, "assignment consumes one fleet chip"

    def test_deassign_returned_restores_fleet_and_keeps_checkin(self, api):
        """PRD §3.3: "A `RETURNED` chip goes back to `AVAILABLE`, the athlete
        stays `CHECKED_IN` and may check in again with a different chip, and
        both links are cleared."

        Design: Difficulty/compensating_invariant/chip_fleet_conservation
        """
        ctx = self._conservation_scenario(api)
        validate_success(api.assign_chip(
            ctx["regs"]["r1"]["id"], ctx["chips"]["cx"]["id"], CLERK), 200)
        chip = validate_success(
            api.deassign_chip(ctx["chips"]["cx"]["id"], "RETURNED", CLERK), 200)
        assert self._available_count(api) == 2, "assign + RETURNED conserves the fleet"
        assert chip["status"] == "AVAILABLE"
        assert chip["current_registration_id"] is None

        reg = validate_success(
            api.get_registration(ctx["regs"]["r1"]["id"], CLERK), 200)
        assert reg["chip_id"] is None
        assert reg["lifecycle_status"] == "CHECKED_IN", (
            "RETURNED does not revert the athlete's check-in"
        )
