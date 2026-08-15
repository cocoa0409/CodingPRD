"""Material transfer through the airlock: dwell boundary, wipe-down gate,
transfer state machine, and validation ordering."""
from test_helpers import (
    MAT_HANDLER,
    QA,
    ApiErrorId,
    add_sampling_point,
    assert_material_transfer,
    create_room,
    get_success_data,
    record_excursion_sample,
    set_clock,
    setup_certified_room,
    stage_transfer,
    validate_error,
    validate_success,
)


def _certified_room(room_code):
    return setup_certified_room(
        room_code=room_code, iso_class="ISO_8",
        particle_alert_limit=3500000, particle_action_limit=3520000,
        viable_alert_limit=100, viable_action_limit=200)


class TestDwellBoundary:
    def test_introduce_one_second_before_dwell_met_rejected(self, api):
        """PRD §3.5: "the logical clock must have reached or passed `staged_at`
        plus `dwell_minutes` — the boundary is inclusive, so introduction is
        allowed at the exact instant the dwell completes, and earlier attempts
        fail with `ERR_DWELL_TIME_NOT_MET`".

        Design: Difficulty/boundary_precision_check/dwell_exactly_met_allows_introduction
        """
        room = _certified_room("CR-L")
        set_clock("2026-08-01T10:00:00Z")
        transfer = stage_transfer(room["id"], material_lot="LOT-L",
                                  item_description="Fasteners", dwell_minutes=30,
                                  wiped_down=True)

        set_clock("2026-08-01T10:29:59Z")
        resp = api.introduce_material_transfer(transfer["id"], MAT_HANDLER)
        validate_error(resp, ApiErrorId.ERR_DWELL_TIME_NOT_MET)
        staged = get_success_data(api.get_material_transfer(transfer["id"], MAT_HANDLER))
        assert staged["status"] == "STAGED"

    def test_introduce_at_exact_dwell_completion_succeeds(self, api):
        """PRD §3.5: "the logical clock must have reached or passed `staged_at`
        plus `dwell_minutes` — the boundary is inclusive, so introduction is
        allowed at the exact instant the dwell completes, and earlier attempts
        fail with `ERR_DWELL_TIME_NOT_MET`".
        PRD §3.5: "A successful introduction moves the transfer from `STAGED`
        to terminal `INTRODUCED`."

        Design: Difficulty/boundary_precision_check/dwell_exactly_met_allows_introduction
        """
        room = _certified_room("CR-L")
        set_clock("2026-08-01T10:00:00Z")
        transfer = stage_transfer(room["id"], material_lot="LOT-L",
                                  item_description="Fasteners", dwell_minutes=30,
                                  wiped_down=True)

        set_clock("2026-08-01T10:30:00Z")
        introduced = validate_success(
            api.introduce_material_transfer(transfer["id"], MAT_HANDLER), 200)
        assert_material_transfer(introduced)
        assert introduced["status"] == "INTRODUCED", (
            "10:30:00 is exactly staged_at + 30 minutes: the boundary is inclusive")


class TestIntroductionGates:
    def test_introduce_without_wipe_down_rejected(self, api):
        """PRD §3.5: "Introduction from the airlock into the room is gated five
        ways: the transfer must still stand `STAGED` (`ERR_TRANSFER_NOT_STAGED`);
        `wiped_down` must be true (`ERR_WIPE_DOWN_MISSING`); the logical clock
        must have reached or passed `staged_at` plus `dwell_minutes` — the
        boundary is inclusive, so introduction is allowed at the exact instant
        the dwell completes, and earlier attempts fail with
        `ERR_DWELL_TIME_NOT_MET`; the room's posture must be `IN_CONTROL`
        (`ERR_ROOM_NOT_IN_CONTROL`); and the room's certification must stand
        `CERTIFIED` (`ERR_ROOM_NOT_CERTIFIED`)."

        Design: Corner/state_machines/transfer_introduce_requires_wipe_down
        """
        room = _certified_room("CR-S6")
        transfer = stage_transfer(room["id"], material_lot="LOT-S6",
                                  item_description="Unwiped part", dwell_minutes=0,
                                  wiped_down=False)
        resp = api.introduce_material_transfer(transfer["id"], MAT_HANDLER)
        validate_error(resp, ApiErrorId.ERR_WIPE_DOWN_MISSING)
        staged = get_success_data(api.get_material_transfer(transfer["id"], MAT_HANDLER))
        assert staged["status"] == "STAGED"

    def test_double_introduce_rejected(self, api):
        """PRD §3.5: "the transfer must still stand `STAGED`
        (`ERR_TRANSFER_NOT_STAGED`)".
        PRD §3.5: "A successful introduction moves the transfer from `STAGED`
        to terminal `INTRODUCED`."

        Design: Corner/errors/error_transfer_not_staged_on_double_introduce
        """
        room = _certified_room("CR-ER6")
        transfer = stage_transfer(room["id"], material_lot="LOT-ER6",
                                  item_description="Part ER6", dwell_minutes=0,
                                  wiped_down=True)
        introduced = validate_success(
            api.introduce_material_transfer(transfer["id"], MAT_HANDLER), 200)
        assert introduced["status"] == "INTRODUCED"

        resp = api.introduce_material_transfer(transfer["id"], MAT_HANDLER)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_NOT_STAGED)


class TestPostureVersusDwellOrdering:
    def _room_with_raised_posture_and_staged_transfer(self, api):
        """Room whose posture is raised by an open ALERT excursion; a wiped
        transfer staged at 10:00 with a 60-minute dwell."""
        room = create_room(room_code="CR-J")
        point = add_sampling_point(room["id"], point_code="SP-J", metric="VIABLE")
        set_clock("2026-08-01T10:00:00Z")
        transfer = stage_transfer(room["id"], material_lot="LOT-J",
                                  item_description="Seal kit", dwell_minutes=60,
                                  wiped_down=True)
        record_excursion_sample(point["id"], 75, sampled_at="2026-08-01T10:05:00Z")
        room_now = get_success_data(api.get_room(room["id"], QA))
        assert room_now["environment_posture"] == "ALERT"
        return room, transfer

    def test_posture_error_beats_dwell_error_when_both_violated(self, api):
        """PRD §2.10: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order so that the surfaced
        error is deterministic".
        PRD §2.10: "6. The room-posture gate, applied to personnel entry,
        material introduction, traveler start, and batch release
        (`ERR_ROOM_NOT_IN_CONTROL`)."
        PRD §2.10: "11. Temporal gates — the gowning qualification not expired,
        the transfer's dwell elapsed, the audit window started
        (`ERR_GOWNING_NOT_QUALIFIED`, `ERR_DWELL_TIME_NOT_MET`,
        `ERR_AUDIT_WINDOW_NOT_STARTED`)."

        Design: Difficulty/priority_pair_validation_conflict/posture_gate_beats_dwell_temporal_check
        """
        _room, transfer = self._room_with_raised_posture_and_staged_transfer(api)
        set_clock("2026-08-01T10:30:00Z")
        # 30 of 60 dwell minutes elapsed: the temporal gate is also violated,
        # but the posture gate (priority 6) precedes it (priority 11).
        resp = api.introduce_material_transfer(transfer["id"], MAT_HANDLER)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_IN_CONTROL)
        staged = get_success_data(api.get_material_transfer(transfer["id"], MAT_HANDLER))
        assert staged["status"] == "STAGED"

    def test_posture_error_when_dwell_met(self, api):
        """PRD §2.7: "Personnel entry, material introduction, traveler step
        start, and batch release each require the room to be `IN_CONTROL`;
        against a room in any raised posture those operations are rejected with
        `ERR_ROOM_NOT_IN_CONTROL`."

        Design: Difficulty/priority_pair_validation_conflict/posture_gate_beats_dwell_temporal_check
        """
        _room, transfer = self._room_with_raised_posture_and_staged_transfer(api)
        set_clock("2026-08-01T11:00:00Z")
        # Dwell exactly met (60 minutes), but the posture gate still blocks.
        resp = api.introduce_material_transfer(transfer["id"], MAT_HANDLER)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_IN_CONTROL)
