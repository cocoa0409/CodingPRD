"""Corner coverage: backup slot validation battery and the
terminal/no-show battery."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, get_success_data,
    create_active_home_patient, create_chair, create_slot, set_clock,
    get_patient, api_client,
    make_admin_headers, make_nurse_headers, make_patient_headers,
)


class TestSlotValidationBattery:
    """Four distinct reservation rejections on one setup."""

    def _setup(self, api):
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        chair = create_chair(ctx["program"]["id"], chair_code="CH-1")
        return ctx, pat, chair

    def test_past_and_short_slots_rejected(self, api):
        """PRD §3.7: "`slot_start` must not lie before the current clock
        (`ERR_SLOT_IN_PAST`); the slot must run at least 60 and at most 480
        minutes (`ERR_SLOT_DURATION_INVALID`);"

        Design: Corner/state_machines/slot_validation_battery
        """
        ctx, pat, chair = self._setup(api)
        # Clock is the startup default 2026-05-01; April is in the past.
        resp = api.create_slot_reservation(
            {"patient_id": pat, "chair_id": chair["id"],
             "slot_start": "2026-04-01T10:00:00Z",
             "slot_end": "2026-04-01T12:00:00Z"},
            make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_SLOT_IN_PAST)
        # 30-minute slot violates the 60-minute minimum.
        resp = api.create_slot_reservation(
            {"patient_id": pat, "chair_id": chair["id"],
             "slot_start": "2026-05-10T10:00:00Z",
             "slot_end": "2026-05-10T10:30:00Z"},
            make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_SLOT_DURATION_INVALID)

    def test_daily_cap_and_out_of_service_chair(self, api):
        """PRD §3.7: "Finally, a patient may hold at most two `RESERVED`
        reservations on the same calendar service day
        (`ERR_SLOT_DAILY_CAP_EXCEEDED`)."
        PRD §3.7: "The guards, in their pipeline stages: an `ACTIVE`
        EmergencyBackupPlan must exist for the patient (`ERR_PLAN_NOT_ACTIVE`);
        the chair must be in service (`ERR_CHAIR_OUT_OF_SERVICE`);"

        Design: Corner/state_machines/slot_validation_battery
        """
        ctx, pat, chair = self._setup(api)
        s1 = create_slot(pat, chair["id"], "2026-05-10T10:00:00Z",
                         "2026-05-10T12:00:00Z")
        assert s1["status"] == "RESERVED"
        create_slot(pat, chair["id"], "2026-05-10T13:00:00Z",
                    "2026-05-10T15:00:00Z")
        # Third same-day reservation exceeds the aggregate cap of 2.
        resp = api.create_slot_reservation(
            {"patient_id": pat, "chair_id": chair["id"],
             "slot_start": "2026-05-10T16:00:00Z",
             "slot_end": "2026-05-10T18:00:00Z"},
            make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_SLOT_DAILY_CAP_EXCEEDED)
        # Out-of-service chair rejects new reservations.
        validate_success(api.patch_chair(chair["id"], {"in_service": False},
                                         make_admin_headers("admin-1")))
        resp = api.create_slot_reservation(
            {"patient_id": pat, "chair_id": chair["id"],
             "slot_start": "2026-05-11T10:00:00Z",
             "slot_end": "2026-05-11T12:00:00Z"},
            make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_CHAIR_OUT_OF_SERVICE)


class TestSlotTerminalAndNoShowBattery:
    """Cancel after completion, cancel after slot_start, and the lazy NO_SHOW
    flip with no_show_count increment."""

    def _setup(self, api):
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        chair = create_chair(ctx["program"]["id"], chair_code="CH-1")
        return ctx, pat, chair

    def test_complete_then_cancel_invalid_and_too_late_cancel(self, api):
        """PRD §3.7: "The patient cancels a reservation only while the clock
        is still before `slot_start` (`ERR_SLOT_TOO_LATE_TO_CANCEL`), and only
        from `RESERVED` (`ERR_SLOT_INVALID_STATE`); a `HomeNurse` marks
        attendance by moving `RESERVED` to `COMPLETED`."

        Design: Corner/state_machines/slot_terminal_and_noshow_battery
        """
        ctx, pat, chair = self._setup(api)
        s1 = create_slot(pat, chair["id"], "2026-05-10T10:00:00Z",
                         "2026-05-10T12:00:00Z")
        completed = validate_success(api.complete_slot_reservation(
            s1["id"], make_nurse_headers("nurse-1")))
        assert completed["status"] == "COMPLETED"
        # Cancel after completion: invalid transition.
        resp = api.cancel_slot_reservation(s1["id"], make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_SLOT_INVALID_STATE)
        # Cancel at/after slot_start.
        s2 = create_slot(pat, chair["id"], "2026-05-11T10:00:00Z",
                         "2026-05-11T12:00:00Z")
        set_clock("2026-05-11T11:00:00Z")
        resp = api.cancel_slot_reservation(s2["id"], make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_SLOT_TOO_LATE_TO_CANCEL)

    def test_lazy_no_show_increments_count(self, api):
        """PRD §2.5: "A BackupSlotReservation still `RESERVED` once the clock
        has passed its `slot_end` reads as `NO_SHOW` and increments the
        patient's `no_show_count`."

        Design: Corner/state_machines/slot_terminal_and_noshow_battery
        """
        ctx, pat, chair = self._setup(api)
        s2 = create_slot(pat, chair["id"], "2026-05-11T10:00:00Z",
                         "2026-05-11T12:00:00Z")
        set_clock("2026-05-12T00:00:00Z")
        rows = get_success_data(api.list_patient_slot_reservations(
            pat, make_admin_headers("admin-1"), params={"status": "NO_SHOW"}))
        assert len(rows) == 1
        assert rows[0]["status"] == "NO_SHOW"
        assert rows[0]["id"] == s2["id"]
        assert get_patient(pat)["no_show_count"] == 1
