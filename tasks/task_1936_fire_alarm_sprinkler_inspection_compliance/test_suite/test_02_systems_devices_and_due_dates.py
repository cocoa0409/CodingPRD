"""Device frequency/due-date computation, uniqueness, replacement, and the
decommission cascade."""
from test_helpers import (
    DEVICE_REPLACEMENT_IDS,
    DUPLICATE_DEVICE_SERIAL_IDS,
    assert_device,
    assert_system,
    create_device,
    create_property,
    create_system,
    get_success_data,
    replace_device_payload,
    schedule_event,
    setup_completed_event,
    setup_inspection_site,
    setup_published_plan,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import TEST_USERS, create_contractor, admin_headers

MARSHAL = TEST_USERS["fire_marshal_headers"]


class TestDeviceFrequencyAndDueDate:
    def test_gauge_valve_gets_quarterly_and_clamped_due_date(self, api):
        """PRD §3.2: "The device's `frequency_code` is derived from a fixed code
        table at creation: `FIRE_PUMP_CONTROLLER` devices are `MONTHLY`;
        `GAUGE_VALVE` and `SUPERVISORY_SWITCH` devices are `QUARTERLY`;
        `SMOKE_DETECTOR`, `PULL_STATION`, `NOTIFICATION_APPLIANCE`,
        `SPRINKLER_HEAD`, and `BACKFLOW_ASSEMBLY` devices are `ANNUAL`."
        PRD §3.2: "The corresponding inspection intervals are one calendar month
        for `MONTHLY`, three calendar months for `QUARTERLY`, and twelve calendar
        months for `ANNUAL`."
        PRD §2.10: "Date arithmetic on inspection due dates uses calendar months
        with month-end clamping: adding one calendar month to January 31 yields
        February 28 (or 29 in a leap year)."

        Design: Corner/entities/device_frequency_code_computed_from_type
        """
        ctx = setup_inspection_site(system_category="SPRINKLER",
                                    install_date="2026-01-31",
                                    device_count=0)
        dev = create_device(ctx["con"], ctx["sys"], device_type="GAUGE_VALVE",
                            serial_no="GV-9")
        assert_device(dev)
        assert dev["frequency_code"] == "QUARTERLY"
        assert str(dev["next_due_date"])[:10] == "2026-04-30", (
            "install 2026-01-31 + 3 calendar months clamps to the April month end")

    def test_next_due_rolls_to_completion_date_plus_interval(self, api):
        """PRD §3.2: "The base for the computation is the completion date of the
        latest completed inspection event covering the device; if no such event
        exists, the base is the parent system's `install_date`. The next due date
        is the base plus the device's interval in calendar months, with month-end
        clamping."
        PRD §3.4: "The server stamps `completed_at` with the current clock and
        sets `report_due_date` to the completion date plus seven calendar days."

        Design: Corner/entities/device_next_due_rolls_on_event_completion
        """
        ctx = setup_completed_event(
            install_date="2026-01-15",
            scheduled_start="2026-08-03T09:00:00Z",
            scheduled_end="2026-08-03T10:00:00Z",
            complete_clock="2026-08-03T09:30:00Z",
        )
        dev = validate_success(api.get_device(ctx["dev"]["id"], ctx["admin"]))
        assert str(dev["next_due_date"])[:10] == "2027-08-03", (
            "ANNUAL device recomputes to completion date 2026-08-03 + 12 months")
        ev = validate_success(api.get_event(ctx["ev"]["id"], ctx["admin"]))
        assert str(ev["report_due_date"])[:10] == "2026-08-10", (
            "report_due_date is the completion date plus seven calendar days")


class TestDeviceUniquenessAndReplacement:
    def test_duplicate_serial_rejected_within_same_system_only(self, api):
        """PRD §3.2: "Registering a device takes a `device_type` ... and a
        `serial_no` unique within the parent system (conflicts surface as
        `ERR_DUPLICATE_CONSTRAINT` with alias `ERR_DUPLICATE_DEVICE_SERIAL`)."

        Design: Corner/entities/device_duplicate_serial_within_system_rejected
        """
        con = create_contractor(legal_name="Dup Co", state_license_no="C-9300")
        prop = create_property(con, address_line="2 Dup Ln")
        sys_a = create_system(con, prop, system_category="FIRE_ALARM")
        sys_b = create_system(con, prop, system_category="FIRE_ALARM")
        create_device(con, sys_a, device_type="SMOKE_DETECTOR", serial_no="SD-DUP")

        conflict = api.create_device(
            sys_a["id"], {"device_type": "SMOKE_DETECTOR", "serial_no": "SD-DUP"},
            admin_headers(con))
        validate_error_is_one_of(conflict, DUPLICATE_DEVICE_SERIAL_IDS)
        assert conflict.status_code == 409

        other = api.create_device(
            sys_b["id"], {"device_type": "SMOKE_DETECTOR", "serial_no": "SD-DUP"},
            admin_headers(con))
        ok_dev = validate_success(other, 201)
        assert_device(ok_dev)
        assert ok_dev["system_id"] == sys_b["id"], (
            "the same serial is accepted in a different system")

    def test_replace_rejects_cross_system_and_self_references(self, api):
        """PRD §3.2: "Marking a device replaced requires the device to be
        `IN_SERVICE`, the `replaced_by_device_id` pointer to reference a different
        `IN_SERVICE` device in the same system (violations raise
        `ERR_DEVICE_REPLACEMENT_MISMATCH`)"
        PRD §2.7: "the more specific aliases `ERR_SYSTEM_CATEGORY_MISMATCH` ...
        and `ERR_DEVICE_REPLACEMENT_MISMATCH` (a replacement pointer that leaves
        the system, targets a non-in-service device, or self-references) belong
        to this same error class."

        Design: Corner/entities/device_replace_self_reference_rejected
        """
        con = create_contractor(legal_name="Repl Co", state_license_no="C-9400")
        prop = create_property(con, address_line="3 Repl Rd")
        sys1 = create_system(con, prop, system_category="FIRE_ALARM")
        sys2 = create_system(con, prop, system_category="SPRINKLER")
        d1 = create_device(con, sys1, device_type="SMOKE_DETECTOR", serial_no="SD-R1")
        d2 = create_device(con, sys2, device_type="SPRINKLER_HEAD", serial_no="SH-R2")

        cross = api.replace_device(d1["id"], replace_device_payload(d2["id"]),
                                   admin_headers(con))
        validate_error_is_one_of(cross, DEVICE_REPLACEMENT_IDS)
        assert cross.status_code == 422

        self_ref = api.replace_device(d1["id"], replace_device_payload(d1["id"]),
                                      admin_headers(con))
        validate_error_is_one_of(self_ref, DEVICE_REPLACEMENT_IDS)
        assert self_ref.status_code == 422

        after = validate_success(api.get_device(d1["id"], admin_headers(con)))
        assert after["status"] == "IN_SERVICE", (
            "both rejected replacements leave the device IN_SERVICE")


class TestDecommissionCascade:
    def _setup_two_event_site(self, api):
        ctx = setup_inspection_site(system_category="SPRINKLER",
                                    device_type="GAUGE_VALVE",
                                    occupancy_class="STORAGE",
                                    legal_name="Cascade Co")
        setup_published_plan(ctx)
        ctx["ev1"] = schedule_event(ctx["con"], ctx["plan"], ctx["sys"],
                                    ctx["tech"],
                                    scheduled_start="2026-09-01T09:00:00Z",
                                    scheduled_end="2026-09-01T10:00:00Z")
        ctx["ev2"] = schedule_event(ctx["con"], ctx["plan"], ctx["sys"],
                                    ctx["tech"],
                                    scheduled_start="2026-10-01T09:00:00Z",
                                    scheduled_end="2026-10-01T10:00:00Z")
        return ctx

    def test_decommission_cascades_to_system_and_devices(self, api):
        """PRD §3.2: "The cascade removes every `IN_SERVICE` device (each becomes
        `REMOVED`), cancels every `SCHEDULED` inspection event referencing the
        system — each cancellation re-evaluating its parent plan's posture —
        forces the system's `impairment_status` to `OUT_OF_SERVICE`, and advances
        the system's `version`."

        Design: Difficulty/transitive_cascade/system_decommission_three_hop_cascade
        """
        ctx = self._setup_two_event_site(api)
        resp = api.decommission_system(ctx["sys"]["id"], ctx["admin"])
        sys_after = validate_success(resp, 200)
        assert_system(sys_after)
        assert sys_after["status"] == "DECOMMISSIONED"
        assert sys_after["impairment_status"] == "OUT_OF_SERVICE"

        devices = get_success_data(api.list_devices(ctx["sys"]["id"], ctx["admin"]))
        assert len(devices) >= 1, "the device's rows remain queryable"
        for d in devices:
            assert d["status"] == "REMOVED", (
                "every IN_SERVICE device becomes REMOVED in the cascade")

    def test_decommission_cancels_events_and_plan_not_fulfilled(self, api):
        """PRD §3.2: "The cascade removes every `IN_SERVICE` device (each becomes
        `REMOVED`), cancels every `SCHEDULED` inspection event referencing the
        system — each cancellation re-evaluating its parent plan's posture —
        forces the system's `impairment_status` to `OUT_OF_SERVICE`, and advances
        the system's `version`."
        PRD §3.3: "When `events_completed` reaches `total_events_required` and
        every child event is terminal with none in `NO_ACCESS`, the plan becomes
        `FULFILLED`"

        Design: Difficulty/transitive_cascade/system_decommission_three_hop_cascade
        """
        ctx = self._setup_two_event_site(api)
        validate_success(api.decommission_system(ctx["sys"]["id"], ctx["admin"]))

        for key in ("ev1", "ev2"):
            ev = validate_success(api.get_event(ctx[key]["id"], ctx["admin"]))
            assert ev["status"] == "CANCELLED", (
                f"{key} must be CANCELLED by the decommission cascade")
        plan = validate_success(api.get_plan(ctx["plan"]["id"], ctx["admin"]))
        assert plan["plan_posture"] != "FULFILLED", (
            "with zero events completed against a nonzero requirement, "
            "the plan can never be FULFILLED")

    def test_decommission_effects_visible_immediately(self, api):
        """PRD §3.2: "The cascade removes every `IN_SERVICE` device (each becomes
        `REMOVED`), cancels every `SCHEDULED` inspection event referencing the
        system — each cancellation re-evaluating its parent plan's posture —
        forces the system's `impairment_status` to `OUT_OF_SERVICE`, and advances
        the system's `version`."

        Design: Corner/consistency_model/immediate_visibility_of_cascade_in_same_read
        """
        ctx = setup_inspection_site(system_category="SPRINKLER",
                                    device_type="SPRINKLER_HEAD",
                                    device_count=2, legal_name="Immed Co")
        resp = api.decommission_system(ctx["sys"]["id"], ctx["admin"])
        sys_after = validate_success(resp, 200)
        assert sys_after["status"] == "DECOMMISSIONED"
        assert sys_after["impairment_status"] == "OUT_OF_SERVICE"

        devices = get_success_data(api.list_devices(ctx["sys"]["id"], ctx["admin"]))
        assert len(devices) == 2
        assert all(d["status"] == "REMOVED" for d in devices), (
            "the immediately-following device list already reflects the cascade")
