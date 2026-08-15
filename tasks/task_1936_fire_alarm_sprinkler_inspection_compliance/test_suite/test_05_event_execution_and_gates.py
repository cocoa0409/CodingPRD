"""Field-execution gates on inspection events: license validity, system
impairment gating, validation priority, terminal lockdown, no-access timing."""
from test_helpers import (
    ApiErrorId,
    create_impairment_payload,
    get_success_data,
    set_clock,
    setup_completed_event,
    setup_scheduled_event,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MARSHAL = TEST_USERS["fire_marshal_headers"]


class TestLicenseValidityGate:
    def test_license_expiring_on_event_date_rejected(self, api):
        """PRD §3.4: "the lead to hold an `ACTIVE` license whose class matches
        the system's category mapping — `ALARM` for `FIRE_ALARM`, `SPRINKLER` for
        `SPRINKLER`, `BACKFLOW` for `BACKFLOW`, `PUMP` for `FIRE_PUMP` — with
        `expires_on` strictly after the event's scheduled date (else
        `ERR_LICENSE_NOT_VALID`)"

        Design: Corner/validations/license_expiring_on_event_date_rejected
        """
        ctx = setup_scheduled_event(
            license_expires_on="2026-08-05",
            scheduled_start="2026-08-05T09:00:00Z",
            scheduled_end="2026-08-05T10:00:00Z",
            legal_name="Exp Day Co")
        set_clock("2026-08-05T08:00:00Z")
        resp = api.start_event(ctx["ev"]["id"], ctx["tech_headers"])
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_VALID)

    def test_wrong_license_class_rejected(self, api):
        """PRD §3.4: "the lead to hold an `ACTIVE` license whose class matches
        the system's category mapping — `ALARM` for `FIRE_ALARM`, `SPRINKLER` for
        `SPRINKLER`, `BACKFLOW` for `BACKFLOW`, `PUMP` for `FIRE_PUMP` — with
        `expires_on` strictly after the event's scheduled date (else
        `ERR_LICENSE_NOT_VALID`)"

        Design: Corner/validations/wrong_license_class_rejected
        """
        ctx = setup_scheduled_event(
            system_category="FIRE_ALARM", device_type="SMOKE_DETECTOR",
            license_class="SPRINKLER",
            scheduled_start="2026-08-05T09:00:00Z",
            scheduled_end="2026-08-05T10:00:00Z",
            legal_name="WrongClass Co")
        set_clock("2026-08-05T08:00:00Z")
        resp = api.start_event(ctx["ev"]["id"], ctx["tech_headers"])
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_VALID)


class TestTerminalStateLockdown:
    def test_completed_event_rejects_start(self, api):
        """PRD §2.6: "5. **Transition legality** — the target resource must be in
        a state from which the requested transition exists; failure yields
        `ERR_INVALID_STATE`. Terminal-state lockdown and repeated actions also
        fail here."

        Design: Corner/state_machines/terminal_state_lockdown_event_completed_rejects_start
        """
        ctx = setup_completed_event(legal_name="Lockdown Co")
        resp = api.start_event(ctx["ev"]["id"], ctx["tech_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_event(ctx["ev"]["id"], ctx["admin"]))
        assert after["status"] == "COMPLETED", "COMPLETED is terminal"


class TestSystemImpairmentGate:
    def _impaired_site(self, api):
        """Event scheduled 2026-08-05 09:00; an UNPLANNED impairment open since
        2026-08-01 has exceeded ten hours by 2026-08-05T09:00."""
        ctx = setup_scheduled_event(
            scheduled_start="2026-08-05T09:00:00Z",
            scheduled_end="2026-08-05T10:00:00Z",
            legal_name="Gate Co")
        api.create_impairment(
            ctx["sys"]["id"],
            create_impairment_payload(impairment_kind="UNPLANNED",
                                      planned_start="2026-08-04T20:00:00Z",
                                      planned_end="2026-08-06T08:00:00Z"),
            ctx["admin"])
        set_clock("2026-08-05T09:00:00Z")
        ctx["ev"] = get_success_data(api.get_event(ctx["ev"]["id"], ctx["admin"]))
        return ctx

    def test_start_rejected_when_system_out_of_service(self, api):
        """PRD §3.4: "the contractor not to be `SUSPENDED`, and the system's
        `impairment_status` not to be `OUT_OF_SERVICE` (else
        `ERR_SYSTEM_OUT_OF_SERVICE`)"
        PRD §3.6: "while any impairment has remained in `OPEN` or `NOTIFIED` for
        strictly longer than ten hours, the system reads `OUT_OF_SERVICE`"

        Design: Difficulty/cross_entity_state_dependency/event_start_gated_by_system_impairment_state
        """
        ctx = self._impaired_site(api)
        sys_now = validate_success(api.get_system(ctx["sys"]["id"], ctx["admin"]))
        assert sys_now["impairment_status"] == "OUT_OF_SERVICE", (
            "an impairment open far longer than ten hours escalates the system")
        resp = api.start_event(ctx["ev"]["id"], ctx["tech_headers"])
        validate_error(resp, ApiErrorId.ERR_SYSTEM_OUT_OF_SERVICE)
        after = validate_success(api.get_event(ctx["ev"]["id"], ctx["admin"]))
        assert after["status"] == "SCHEDULED", "the rejected start changes nothing"

    def test_start_allowed_after_impairment_restored(self, api):
        """PRD §3.6: "Restoration — permitted from either `OPEN` or `NOTIFIED` —
        stamps `restored_at`, moves the impairment to `RESTORED`, and re-derives
        the system's impairment status, returning it toward `NORMAL` when no
        other open impairments remain."
        PRD §3.4: "the system's `impairment_status` not to be `OUT_OF_SERVICE`
        (else `ERR_SYSTEM_OUT_OF_SERVICE`)"

        Design: Difficulty/cross_entity_state_dependency/event_start_gated_by_system_impairment_state
        """
        ctx = self._impaired_site(api)
        impairments = get_success_data(
            api.list_impairments(ctx["sys"]["id"], ctx["admin"]))
        imp = impairments[0]
        validate_success(api.restore_impairment(imp["id"], ctx["admin"]))
        sys_now = validate_success(api.get_system(ctx["sys"]["id"], ctx["admin"]))
        assert sys_now["impairment_status"] == "NORMAL", (
            "with no open impairments remaining the system returns to NORMAL")
        started = validate_success(api.start_event(ctx["ev"]["id"], ctx["tech_headers"]))
        assert started["status"] == "IN_PROGRESS"


class TestValidationPriority:
    def _expired_license_site(self, api):
        """Technician's ALARM license (issued 2024-01-01) expired 2025-01-01;
        event 2026-08-05. The issue/expiry pair is a valid strictly-ordered
        range — the license is lapsed relative to the logical clock."""
        ctx = setup_scheduled_event(
            license_issued_on="2024-01-01",
            license_expires_on="2025-01-01",
            scheduled_start="2026-08-05T09:00:00Z",
            scheduled_end="2026-08-05T10:00:00Z",
            legal_name="Priority One")
        set_clock("2026-08-05T08:00:00Z")
        return ctx

    def test_cancelled_event_with_invalid_license_yields_invalid_state(self, api):
        """PRD §2.6: "Every request is validated in a fixed priority order, and
        the first failing rule determines the error returned."
        PRD §2.6: "5. **Transition legality** — the target resource must be in a
        state from which the requested transition exists; failure yields
        `ERR_INVALID_STATE`."
        PRD §2.6: "7. **License validity** — on inspection-event start and on
        backflow and fire-pump test creation, the acting or named technician must
        hold an `ACTIVE` license of the required class whose expiry is strictly
        after the relevant date; failure yields `ERR_LICENSE_NOT_VALID`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_event_start
        """
        ctx = self._expired_license_site(api)
        validate_success(api.cancel_event(ctx["ev"]["id"], ctx["admin"]))
        resp = api.start_event(ctx["ev"]["id"], ctx["tech_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409, (
            "transition legality (rule 5) is evaluated before license validity "
            "(rule 7), so the cancelled event yields ERR_INVALID_STATE")

    def test_scheduled_event_with_invalid_license_yields_license_error(self, api):
        """PRD §2.6: "7. **License validity** — on inspection-event start and on
        backflow and fire-pump test creation, the acting or named technician must
        hold an `ACTIVE` license of the required class whose expiry is strictly
        after the relevant date; failure yields `ERR_LICENSE_NOT_VALID`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_event_start
        """
        ctx = self._expired_license_site(api)
        resp = api.start_event(ctx["ev"]["id"], ctx["tech_headers"])
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_VALID)
        assert resp.status_code == 422, (
            "with the state gate satisfied, the license gate fires on its own")


class TestNoAccessTiming:
    def test_mark_no_access_before_scheduled_start_rejected(self, api):
        """PRD §3.4: "The assigned technician may instead mark no-access, but
        only once the current clock has reached `scheduled_start` (attempting
        earlier yields `ERR_EVENT_NOT_YET_DUE`)"

        Design: Corner/errors/mark_no_access_before_scheduled_start_rejected
        """
        ctx = setup_scheduled_event(
            scheduled_start="2026-08-10T09:00:00Z",
            scheduled_end="2026-08-10T10:00:00Z",
            legal_name="Early Co")
        set_clock("2026-08-05T00:00:00Z")
        resp = api.mark_no_access(ctx["ev"]["id"], ctx["tech_headers"])
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_YET_DUE)
        after = validate_success(api.get_event(ctx["ev"]["id"], ctx["admin"]))
        assert after["status"] == "SCHEDULED", "the rejected mark changes nothing"
