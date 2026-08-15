"""Pack-back scheduling: the four CONFIRM gates, half-open crew windows, and
the reschedule cycle (PRD §3.5).
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_cleaned_item, setup_item_in_storage,
    drive_structure_complete, create_schedule, get_schedule, transition_schedule,
    file_claim, get_item,
)

PM = TEST_USERS["project_manager_headers"]
PM1 = TEST_USERS["pm1_headers"]


def _confirm(api, schedule_id):
    return api.transition_pack_back_schedule(schedule_id, {"action": "CONFIRM"}, PM)


class TestConfirmGates:
    def _setup_structure_pending(self):
        """Item fully processed to IN_STORAGE, but structure never signed off."""
        ctx = setup_item_in_storage(
            job_overrides={"claim_number": "CLM-CE1", "property_address": "24 Sycamore St"},
            room_overrides={"name": "Lounge"},
            item_overrides={"barcode": "BC-CE1", "description": "Recliner",
                            "item_category": "FURNITURE", "declared_value_cents": 6000,
                            "volume_cu_ft": 15},
            vault_overrides={"code": "V-CE1", "climate_class": "STANDARD",
                             "capacity_cu_ft": 1000, "monthly_rate_cents_per_cu_ft": 100})
        schedule = create_schedule(
            ctx["job"]["id"], crew_id="crew-1", service_date="2026-09-12",
            window_start_hour=9, window_end_hour=13)
        ctx["schedule"] = schedule
        return ctx

    def test_schedule_confirm_gated_on_job_structure(self, api):
        """PRD §3.5: "Confirming a schedule runs a four-gate check sequence.
        First, the job's `structure_status` must be `COMPLETE`, else
        `ERR_JOB_NOT_READY_FOR_PACKBACK`."

        Design: Difficulty/cross_entity_state_dependency/schedule_confirm_gated_on_job_structure
        """
        ctx = self._setup_structure_pending()
        assert get_item(ctx["item"]["id"])["processing_status"] == "IN_STORAGE", (
            "precondition: eligible in-storage inventory exists")

        res = _confirm(api, ctx["schedule"]["id"])
        validate_error(res, ApiErrorId.ERR_JOB_NOT_READY_FOR_PACKBACK, expected_status=409)

    def test_structure_gate_leaves_schedule_requested(self, api):
        """PRD §3.5: "Confirming a schedule runs a four-gate check sequence.
        First, the job's `structure_status` must be `COMPLETE`, else
        `ERR_JOB_NOT_READY_FOR_PACKBACK`."
        PRD §3.5: "A new schedule starts `REQUESTED` with `eligible_item_count`
        null and `reschedule_count` zero."

        Design: Difficulty/cross_entity_state_dependency/schedule_confirm_gated_on_job_structure
        """
        ctx = self._setup_structure_pending()
        res = _confirm(api, ctx["schedule"]["id"])
        validate_error(res, ApiErrorId.ERR_JOB_NOT_READY_FOR_PACKBACK, expected_status=409)

        schedule = get_schedule(ctx["job"]["id"], ctx["schedule"]["id"])
        assert schedule["status"] == "REQUESTED", (
            f"the rejected CONFIRM must leave the schedule REQUESTED, got {schedule['status']}")

    def _setup_empty_eligible_set(self):
        """Structure COMPLETE; one item CLEANED but never placed (no IN_STORAGE)."""
        job, room, item, _task = setup_cleaned_item(
            job_overrides={"claim_number": "CLM-BP3", "property_address": "22 Alder Way"},
            room_overrides={"name": "Bath", "room_type": "BATH"},
            item_overrides={"barcode": "BC-BP3", "description": "Vanity",
                            "item_category": "FURNITURE", "declared_value_cents": 5000,
                            "volume_cu_ft": 10})
        drive_structure_complete(job["id"])
        schedule = create_schedule(job["id"], crew_id="crew-9",
                                   service_date="2026-09-10",
                                   window_start_hour=8, window_end_hour=12)
        return job, schedule

    def test_packback_confirm_empty_eligible_set_rejected(self, api):
        """PRD §3.5: "Third, the eligibility count must be at least one: the
        eligible set is exactly those items of the job whose `processing_status` is
        `IN_STORAGE` and whose every specialty referral has reached `QA_ACCEPTED` —
        no fuzzy "ready" notion, the enum set is the filter — and an empty set
        yields `ERR_NO_ELIGIBLE_ITEMS_FOR_PACKBACK`."

        Design: Difficulty/boundary_precision_check/packback_confirm_empty_eligible_set_rejected
        """
        _job, schedule = self._setup_empty_eligible_set()
        res = _confirm(api, schedule["id"])
        validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_ITEMS_FOR_PACKBACK, expected_status=422)

    def test_empty_eligible_set_leaves_schedule_requested(self, api):
        """PRD §3.5: "an empty set yields `ERR_NO_ELIGIBLE_ITEMS_FOR_PACKBACK`."
        PRD §3.5: "On success the schedule moves to `CONFIRMED` and the
        `eligible_item_count` snapshot is stored."

        Design: Difficulty/boundary_precision_check/packback_confirm_empty_eligible_set_rejected
        """
        job, schedule = self._setup_empty_eligible_set()
        res = _confirm(api, schedule["id"])
        validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_ITEMS_FOR_PACKBACK, expected_status=422)

        schedule_after = get_schedule(job["id"], schedule["id"])
        assert schedule_after["status"] == "REQUESTED", (
            f"a failed CONFIRM is no transition, got {schedule_after['status']}")

    def _setup_open_claim(self):
        """Structure COMPLETE; one item IN_STORAGE (eligible); a FILED claim on it."""
        ctx = setup_item_in_storage(
            job_overrides={"claim_number": "CLM-CE3", "property_address": "28 Dogwood Ln"},
            room_overrides={"name": "Kitchen", "room_type": "KITCHEN"},
            item_overrides={"barcode": "BC-CE3", "description": "Mixer",
                            "item_category": "APPLIANCE", "declared_value_cents": 12000,
                            "volume_cu_ft": 2},
            vault_overrides={"code": "V-CE3", "climate_class": "STANDARD",
                             "capacity_cu_ft": 1000, "monthly_rate_cents_per_cu_ft": 100})
        file_claim(ctx["item"]["id"], filer_headers=PM1,
                   claim_type="DAMAGE", description="Scratched in vault",
                   replacement_cost_cents=12000, item_age_years=1)
        drive_structure_complete(ctx["job"]["id"])
        ctx["schedule"] = create_schedule(
            ctx["job"]["id"], crew_id="crew-2", service_date="2026-09-15",
            window_start_hour=8, window_end_hour=10)
        return ctx

    def test_packback_confirm_blocked_by_open_claim(self, api):
        """PRD §3.5: "Fourth, no eligible item may carry an open handling claim —
        one in `FILED`, `UNDER_REVIEW`, or `APPROVED` status — else
        `ERR_OPEN_CLAIM_BLOCKS_PACKBACK`."

        Design: Difficulty/cross_entity_state_dependency/packback_confirm_blocked_by_open_claim
        """
        ctx = self._setup_open_claim()
        res = _confirm(api, ctx["schedule"]["id"])
        validate_error(res, ApiErrorId.ERR_OPEN_CLAIM_BLOCKS_PACKBACK, expected_status=409)

    def test_open_claim_gate_leaves_schedule_requested(self, api):
        """PRD §3.5: "Fourth, no eligible item may carry an open handling claim —
        one in `FILED`, `UNDER_REVIEW`, or `APPROVED` status — else
        `ERR_OPEN_CLAIM_BLOCKS_PACKBACK`."

        Design: Difficulty/cross_entity_state_dependency/packback_confirm_blocked_by_open_claim
        """
        ctx = self._setup_open_claim()
        res = _confirm(api, ctx["schedule"]["id"])
        validate_error(res, ApiErrorId.ERR_OPEN_CLAIM_BLOCKS_PACKBACK, expected_status=409)

        schedule_after = get_schedule(ctx["job"]["id"], ctx["schedule"]["id"])
        assert schedule_after["status"] == "REQUESTED", (
            f"the vetoed CONFIRM must leave the schedule REQUESTED, got {schedule_after['status']}")


class TestCrewWindowOverlap:
    def _setup_confirmed_a(self):
        """Structure COMPLETE + one IN_STORAGE item + schedule A (crew-7,
        2026-09-10 08-12) CONFIRMED."""
        ctx = setup_item_in_storage(
            job_overrides={"claim_number": "CLM-RO1", "property_address": "30 Redwood Rd"},
            room_overrides={"name": "Den"},
            item_overrides={"barcode": "BC-RO1", "description": "Ottoman",
                            "item_category": "FURNITURE", "declared_value_cents": 3000,
                            "volume_cu_ft": 8},
            vault_overrides={"code": "V-RO1", "climate_class": "STANDARD",
                             "capacity_cu_ft": 1000, "monthly_rate_cents_per_cu_ft": 100})
        drive_structure_complete(ctx["job"]["id"])
        sch_a = create_schedule(ctx["job"]["id"], crew_id="crew-7",
                                service_date="2026-09-10",
                                window_start_hour=8, window_end_hour=12)
        confirmed = get_success_data(transition_schedule(sch_a["id"], "CONFIRM"))
        assert confirmed["status"] == "CONFIRMED", "precondition: A confirmed"
        ctx["sch_a"] = confirmed
        return ctx

    def test_crew_window_adjacency_is_allowed(self, api):
        """PRD §3.5: "occupation is half-open: a crew occupies from the start hour
        up to but not including the end hour."
        PRD §3.5: "pure adjacency — one window's end equal to the other's start —
        is allowed, and a genuine collision yields `ERR_CREW_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/crew_window_half_open_adjacency
        """
        ctx = self._setup_confirmed_a()
        sch_b = create_schedule(ctx["job"]["id"], crew_id="crew-7",
                                service_date="2026-09-10",
                                window_start_hour=12, window_end_hour=16)
        confirmed_b = get_success_data(transition_schedule(sch_b["id"], "CONFIRM"))
        assert confirmed_b["status"] == "CONFIRMED", (
            "[8,12) and [12,16) touch but do not overlap under half-open semantics")

    def test_crew_window_overlap_rejected(self, api):
        """PRD §3.5: "Second, no other schedule with the same `crew_id` and
        `service_date` in `CONFIRMED` or `IN_TRANSIT` status may have a half-open
        window overlapping this one; pure adjacency — one window's end equal to the
        other's start — is allowed, and a genuine collision yields
        `ERR_CREW_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/crew_window_half_open_adjacency
        """
        ctx = self._setup_confirmed_a()
        sch_c = create_schedule(ctx["job"]["id"], crew_id="crew-7",
                                service_date="2026-09-10",
                                window_start_hour=11, window_end_hour=13)
        res = transition_schedule(sch_c["id"], "CONFIRM")
        validate_error(res, ApiErrorId.ERR_CREW_WINDOW_OVERLAP, expected_status=422)

        schedule_after = get_schedule(ctx["job"]["id"], sch_c["id"])
        assert schedule_after["status"] == "REQUESTED"


class TestRescheduleAndWindowValidation:
    def test_schedule_reschedule_frees_crew_window(self, api):
        """PRD §3.5: "A confirmed schedule can instead be rescheduled: supplying a
        new `service_date`, `window_start_hour`, and `window_end_hour` — all three
        present and valid, with the end strictly after the start else
        `ERR_WINDOW_INVALID` — returns the schedule to `REQUESTED`, increments
        `reschedule_count` by one, and frees the crew window, since a `REQUESTED`
        schedule occupies no window."

        Design: Corner/state_machines/schedule_reschedule_frees_crew_window
        """
        ctx = setup_item_in_storage(
            job_overrides={"claim_number": "CLM-SM5", "property_address": "54 Alder St"},
            room_overrides={"name": "Lounge"},
            item_overrides={"barcode": "BC-SM5", "description": "Loveseat",
                            "item_category": "FURNITURE", "declared_value_cents": 15000,
                            "volume_cu_ft": 14},
            vault_overrides={"code": "V-SM5", "climate_class": "STANDARD",
                             "capacity_cu_ft": 1000, "monthly_rate_cents_per_cu_ft": 100})
        drive_structure_complete(ctx["job"]["id"])
        sch_a = create_schedule(ctx["job"]["id"], crew_id="crew-3",
                                service_date="2026-09-10",
                                window_start_hour=8, window_end_hour=12)
        get_success_data(transition_schedule(sch_a["id"], "CONFIRM"))

        rescheduled = get_success_data(transition_schedule(
            sch_a["id"], "RESCHEDULE", service_date="2026-09-11",
            window_start_hour=14, window_end_hour=16))
        assert rescheduled["status"] == "REQUESTED", (
            f"RESCHEDULE returns the schedule to REQUESTED, got {rescheduled['status']}")
        assert rescheduled["reschedule_count"] == 1, (
            f"reschedule_count increments by one, got {rescheduled['reschedule_count']}")
        assert rescheduled["service_date"] == "2026-09-11"
        assert rescheduled["window_start_hour"] == 14
        assert rescheduled["window_end_hour"] == 16

        sch_b = create_schedule(ctx["job"]["id"], crew_id="crew-3",
                                service_date="2026-09-10",
                                window_start_hour=8, window_end_hour=12)
        confirmed_b = get_success_data(transition_schedule(sch_b["id"], "CONFIRM"))
        assert confirmed_b["status"] == "CONFIRMED", (
            "the freed 2026-09-10 08-12 window must accept a new CONFIRM")

    def test_schedule_window_invalid_on_create(self, api):
        """PRD §3.5: "Window hours are integers: start runs 0 through 23, end runs
        1 through 24, the end must be strictly greater than the start — otherwise
        `ERR_WINDOW_INVALID` — and occupation is half-open: a crew occupies from
        the start hour up to but not including the end hour."

        Design: Corner/validations/schedule_window_invalid_on_create
        """
        job = get_success_data(api.create_pack_out_job(
            {"claim_number": "CLM-V4", "property_address": "72 Elm St",
             "carrier_name": "Acme Mutual", "policy_coverage_type": "ACV"}, PM))

        res = api.create_pack_back_schedule(job["id"], {
            "crew_id": "crew-4", "service_date": "2026-09-20",
            "window_start_hour": 12, "window_end_hour": 8}, PM)
        validate_error(res, ApiErrorId.ERR_WINDOW_INVALID, expected_status=422)

        schedules = get_success_data(api.list_pack_back_schedules(job["id"], PM))
        assert schedules == [], f"the invalid schedule must not persist, got {schedules}"
