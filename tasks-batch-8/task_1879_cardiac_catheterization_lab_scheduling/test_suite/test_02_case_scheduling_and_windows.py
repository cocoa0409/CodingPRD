"""Case scheduling: AUC gate, equipment match, room/staff window rules, beds."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_staff,
    assert_cath_case,
    assert_instant_equals,
    create_cardiologist,
    create_recovery_bed,
    create_room,
    create_scrub_technologist,
    get_bed,
    post_case,
    schedule_case,
    schedule_case_payload,
    setup_case_workspace,
    validate_error,
    validate_paginated,
    validate_success,
)

SCHEDULER = TEST_USERS["scheduler_headers"]
NURSE_MANAGER = TEST_USERS["nurse_manager_headers"]

START = "2026-08-10T09:00:00Z"


class TestInitialStates:
    def test_case_created_initial_state_posted(self, api):
        """PRD §3.2: "`ELECTIVE` and `URGENT` cases are created in `POSTED` status
        and wait for explicit scheduling (§3.3)."
        PRD §3.2: "A new case begins with `cumulative_contrast_ml` and
        `cumulative_radiation_mgy` at zero, `radiation_alert` false, and
        `bump_count` at zero."
        PRD §3.2: "Each victim moves `SCHEDULED` → `BUMPED`, its `bump_count` rises
        by one, and its `lab_id`, `scheduled_start`, and `scheduled_end` are
        cleared to null — indeed, those three fields remain null on any case
        sitting in `POSTED`, `BUMPED`, or `CANCELLED`."

        Design: Corner/state_machines/case_created_initial_state_posted
        """
        physician = create_cardiologist()
        case = post_case(physician["id"], patient_mrn="MRN-1",
                         procedure_type="EP_STUDY", priority="ELECTIVE")
        assert_cath_case(case)
        assert case["status"] == "POSTED"
        assert case["lab_id"] is None
        assert case["scheduled_start"] is None
        assert case["scheduled_end"] is None
        assert case["bump_count"] == 0

    def test_stemi_case_created_directly_scheduled(self, api):
        """PRD §3.2: "A `STEMI` case is an activation: it bypasses the queue and is
        created directly in `SCHEDULED`."
        PRD §3.2: "a base duration by procedure type — forty-five minutes for
        `DIAGNOSTIC_CATHETERIZATION`, ninety for `PCI`, seventy-five for
        `STEMI_PCI`, sixty for `DEVICE_IMPLANT`, and one hundred twenty for
        `EP_STUDY` — plus a setup allowance. The setup allowance is zero for a
        STEMI activation, the expedited branch; otherwise it is zero when the case
        lists no equipment, fifteen minutes when it lists one or two equipment
        codes, and thirty minutes when it lists three or more."
        PRD §3.2: "The activation also reserves a recovery bed through the bed
        selector (§3.3), moving the chosen bed `AVAILABLE` → `RESERVED` with a
        recovery window beginning at the STEMI case's `scheduled_end`."

        Design: Corner/state_machines/stemi_case_created_directly_scheduled
        """
        physician = create_cardiologist()
        room = create_room(room_name="Lab 1")
        bed = create_recovery_bed("Bed 1")
        case = post_case(physician["id"], patient_mrn="MRN-S",
                         procedure_type="STEMI_PCI", priority="STEMI",
                         weight_kg=80, serum_creatinine=1.1,
                         scheduled_start=START)
        assert case["status"] == "SCHEDULED"
        assert case["lab_id"] == room["id"]
        assert_instant_equals(case["scheduled_end"], "2026-08-10T10:15:00Z")
        # 75-minute STEMI_PCI base, setup forced to zero by the expedited branch.
        reserved = get_bed(bed["id"])
        assert reserved["status"] == "RESERVED"
        assert reserved["held_case_id"] == case["id"]


class TestAucGate:
    def test_urgent_case_schedules_without_auc_satisfaction_pass(self, api):
        """PRD §3.3: "`URGENT` and `STEMI` cases carry no such gate."
        PRD §3.2: "The setup allowance is zero for a STEMI activation, the
        expedited branch; otherwise it is zero when the case lists no equipment,
        fifteen minutes when it lists one or two equipment codes, and thirty
        minutes when it lists three or more."

        Design: Corner/validations/urgent_case_schedules_without_auc_satisfaction_pass
        """
        workspace = setup_case_workspace(priority="URGENT")
        case = workspace["case"]
        assert case["status"] == "SCHEDULED"
        assert case["auc_status"] == "NOT_DOCUMENTED"
        assert_instant_equals(case["scheduled_end"], "2026-08-10T10:30:00Z")
        # PCI base 90 + 0 setup (no equipment listed).

    def test_schedule_elective_without_auc_returns_auc_required(self, api):
        """PRD §3.3: "For an `ELECTIVE` case, scheduling is gated on
        appropriate-use documentation: the case's `auc_status` must be `DOCUMENTED`,
        or the request is refused with `ERR_AUC_REQUIRED`."

        Design: Corner/validations/schedule_elective_without_auc_returns_auc_required
        """
        physician = create_cardiologist()
        room = create_room(room_name="Lab 1")
        bed = create_recovery_bed("Bed 1")
        case = post_case(physician["id"], priority="ELECTIVE")
        resp = api.schedule_case(
            case["id"], schedule_case_payload(room["id"], START, bed_id=bed["id"]),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_AUC_REQUIRED, expected_status=422)
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["status"] == "POSTED"
        assert get_bed(bed["id"])["status"] == "AVAILABLE", \
            "a refused schedule secures no bed"


class TestRoomQualification:
    def test_equipment_mismatch_returns_error(self, api):
        """PRD §3.3: "And the case's `equipment_needs` must be a subset of the
        room's `equipment_profile`, failing which the request is refused with
        `ERR_EQUIPMENT_MISMATCH`."
        PRD §3.2: "The setup allowance is zero for a STEMI activation, the
        expedited branch; otherwise it is zero when the case lists no equipment,
        fifteen minutes when it lists one or two equipment codes, and thirty
        minutes when it lists three or more."

        Design: Corner/validations/equipment_mismatch_returns_error
        """
        physician = create_cardiologist()
        room_without = create_room(room_name="Lab 1")           # no IVUS
        room_with = create_room(room_name="Lab 2", equipment_profile=["IVUS"])
        bed1 = create_recovery_bed("Bed 1")
        bed2 = create_recovery_bed("Bed 2")
        case = post_case(physician["id"], equipment_needs=["IVUS"])

        resp = api.schedule_case(
            case["id"],
            schedule_case_payload(room_without["id"], START, bed_id=bed1["id"]),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_MISMATCH, expected_status=422)
        assert api.get_case(case["id"], SCHEDULER).json()["data"]["status"] == "POSTED"

        scheduled = schedule_case(case["id"], room_with["id"], START,
                                  bed_id=bed2["id"])
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["lab_id"] == room_with["id"]
        assert_instant_equals(scheduled["scheduled_end"], "2026-08-10T10:45:00Z")
        # PCI base 90 + 15 (one equipment code).


class TestBedSecuring:
    def test_explicit_reserved_bed_returns_bed_invalid_state(self, api):
        """PRD §3.3: "When the payload names a `bed_id`, that bed must currently be
        `AVAILABLE`; otherwise the schedule fails with `ERR_BED_INVALID_STATE`."

        Design: Corner/validations/explicit_reserved_bed_returns_bed_invalid_state
        """
        workspace = setup_case_workspace(priority="URGENT", patient_mrn="MRN-A")
        bed = workspace["bed"]  # RESERVED by case A
        physician = workspace["physician"]
        case_b = post_case(physician["id"], patient_mrn="MRN-B", weight_kg=75,
                           serum_creatinine=1.2)
        resp = api.schedule_case(
            case_b["id"],
            schedule_case_payload(workspace["room"]["id"], "2026-08-10T13:00:00Z",
                                  bed_id=bed["id"]),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_BED_INVALID_STATE, expected_status=409)
        current = validate_success(api.get_case(case_b["id"], SCHEDULER))
        assert current["status"] == "POSTED"

    def test_no_available_bed_returns_no_recovery_bed(self, api):
        """PRD §3.3: "When no `bed_id` is given, the bed selector runs: only
        `AVAILABLE` beds are eligible — a bed holds at most one case at a time, so
        `RESERVED`, `OCCUPIED`, and `OUT_OF_SERVICE` beds are out — the
        earliest-created eligible bed wins, ties break by `bed_label` ascending,
        and an empty eligible set fails the whole scheduling request with
        `ERR_NO_RECOVERY_BED`."

        Design: Corner/validations/no_available_bed_returns_no_recovery_bed
        """
        workspace = setup_case_workspace(priority="URGENT", patient_mrn="MRN-A")
        # The single bed is RESERVED by case A.
        room2 = create_room(room_name="Lab 2")
        case_b = post_case(workspace["physician"]["id"], patient_mrn="MRN-B",
                           weight_kg=75, serum_creatinine=1.2)
        resp = api.schedule_case(
            case_b["id"],
            schedule_case_payload(room2["id"], "2026-08-10T13:00:00Z"),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_NO_RECOVERY_BED, expected_status=409)
        current = validate_success(api.get_case(case_b["id"], SCHEDULER))
        assert current["status"] == "POSTED"

    def test_bed_selector_picks_earliest_created_available_bed(self, api):
        """PRD §3.3: "When no `bed_id` is given, the bed selector runs: only
        `AVAILABLE` beds are eligible — a bed holds at most one case at a time, so
        `RESERVED`, `OCCUPIED`, and `OUT_OF_SERVICE` beds are out — the
        earliest-created eligible bed wins, ties break by `bed_label` ascending,
        and an empty eligible set fails the whole scheduling request with
        `ERR_NO_RECOVERY_BED`."

        Design: Corner/cross_cutting_complexity_layers/bed_selector_picks_earliest_created_available_bed
        """
        physician = create_cardiologist()
        room = create_room(room_name="Lab 1")
        bed1 = create_recovery_bed("Bed 1")   # earliest created
        bed2 = create_recovery_bed("Bed 2")
        case = post_case(physician["id"])
        scheduled = schedule_case(case["id"], room["id"], START)  # no bed_id
        assert scheduled["status"] == "SCHEDULED"
        assert get_bed(bed1["id"])["status"] == "RESERVED"
        assert get_bed(bed1["id"])["held_case_id"] == case["id"]
        assert get_bed(bed2["id"])["status"] == "AVAILABLE", \
            "the selector's loser stays AVAILABLE"


class TestScheduleFromState:
    def test_conditional_action_schedule_only_from_posted_or_bumped(self, api):
        """PRD §3.3: "A `CathLabScheduler` schedules a `POSTED` case — or
        reschedules a `BUMPED` one, and the two transitions share their rulebook
        entirely — by supplying the target `lab_id` and `scheduled_start`, with an
        optional `bed_id` pinning a specific recovery bed. Scheduling from any
        other case status is rejected with `ERR_CASE_INVALID_STATE`."

        Design: Corner/endpoints/conditional_action_schedule_only_from_posted_or_bumped
        """
        workspace = setup_case_workspace(priority="URGENT")
        case = workspace["case"]  # already SCHEDULED
        room2 = create_room(room_name="Lab 2")
        bed2 = create_recovery_bed("Bed 2")
        resp = api.schedule_case(
            case["id"],
            schedule_case_payload(room2["id"], "2026-08-11T09:00:00Z",
                                  bed_id=bed2["id"]),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE, expected_status=409)
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["status"] == "SCHEDULED"
        assert current["lab_id"] == workspace["room"]["id"]
        assert_instant_equals(current["scheduled_start"], START)


class TestRoomWindowConflict:
    """Room windows are buffer-extended half-open: [start, end + 20)."""

    def _setup_room_with_committed_case(self, api):
        physician = create_cardiologist()
        room = create_room(room_name="Lab 1")
        bed1 = create_recovery_bed("Bed 1")
        create_recovery_bed("Bed 2")
        case_a = post_case(physician["id"], patient_mrn="MRN-A")
        schedule_case(case_a["id"], room["id"], START, bed_id=bed1["id"])
        # Case A: PCI 09:00-10:30; buffered occupancy until 10:50.
        return physician, room, case_a

    def test_room_conflict_within_turnover_buffer(self, api):
        """PRD §3.3: "Each committed case occupies a half-open interval from its
        `scheduled_start` through its `scheduled_end` plus a twenty-minute turnover
        buffer, and the incoming case occupies the same shape of interval, from its
        own start through its own end plus twenty minutes. A conflict exists when
        the incoming start is earlier than a committed case's buffered end and that
        committed case's start is earlier than the incoming case's buffered end;
        the rejection is `ERR_ROOM_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/room_overlap_turnover_buffer_blocks_but_exact_adjacency_allowed
        """
        physician, room, _ = self._setup_room_with_committed_case(api)
        beds = api.list_recovery_beds(NURSE_MANAGER).json()["data"]
        bed2 = [b for b in beds if b["bed_label"] == "Bed 2"][0]
        case_b = post_case(physician["id"], patient_mrn="MRN-B",
                           procedure_type="DIAGNOSTIC_CATHETERIZATION")
        resp = api.schedule_case(
            case_b["id"],
            schedule_case_payload(room["id"], "2026-08-10T10:40:00Z",
                                  bed_id=bed2["id"]),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_ROOM_WINDOW_CONFLICT,
                       expected_status=409)
        # 10:40 < 10:50 (committed case's buffered end): inside the buffer.
        current = validate_success(api.get_case(case_b["id"], SCHEDULER))
        assert current["status"] == "POSTED"

    def test_room_exact_adjacency_after_buffer_allowed(self, api):
        """PRD §3.3: "Exact adjacency after the buffer is allowed — an incoming
        case starting precisely twenty minutes after a committed case's
        `scheduled_end` is not a conflict."

        Design: Difficulty/resource_temporal_overlap/room_overlap_turnover_buffer_blocks_but_exact_adjacency_allowed
        """
        physician, room, _ = self._setup_room_with_committed_case(api)
        beds = api.list_recovery_beds(NURSE_MANAGER).json()["data"]
        bed2 = [b for b in beds if b["bed_label"] == "Bed 2"][0]
        case_c = post_case(physician["id"], patient_mrn="MRN-C",
                           procedure_type="DIAGNOSTIC_CATHETERIZATION",
                           weight_kg=65, serum_creatinine=1.1)
        scheduled = schedule_case(case_c["id"], room["id"], "2026-08-10T10:50:00Z",
                                  bed_id=bed2["id"])
        # 10:50 == 10:30 + 20 minutes: exactly adjacent after the buffer.
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["lab_id"] == room["id"]
        assert_instant_equals(scheduled["scheduled_end"], "2026-08-10T11:35:00Z")
        # DIAGNOSTIC_CATHETERIZATION base 45 + 0 setup.


class TestStaffWindowConflict:
    """Staff windows are strict half-open [window_start, window_end), no buffer."""

    def _setup_staff_scenario(self, api):
        physician = create_cardiologist()
        tech = create_scrub_technologist()
        rooms = [create_room(room_name=f"Lab {i}") for i in (1, 2, 3)]
        beds = [create_recovery_bed(f"Bed {i}") for i in (1, 2, 3)]
        case_a = post_case(physician["id"], patient_mrn="MRN-A")  # PCI 09:00-10:30
        schedule_case(case_a["id"], rooms[0]["id"], START, bed_id=beds[0]["id"])
        assign_staff(case_a["id"], tech["id"], "SCRUB")
        case_d = post_case(physician["id"], patient_mrn="MRN-D",
                           procedure_type="DIAGNOSTIC_CATHETERIZATION")
        schedule_case(case_d["id"], rooms[1]["id"], "2026-08-10T10:30:00Z",
                      bed_id=beds[1]["id"])  # 10:30-11:15
        case_e = post_case(physician["id"], patient_mrn="MRN-E",
                           procedure_type="DIAGNOSTIC_CATHETERIZATION")
        schedule_case(case_e["id"], rooms[2]["id"], "2026-08-10T10:29:00Z",
                      bed_id=beds[2]["id"])  # 10:29-11:14
        return tech, case_d, case_e

    def test_staff_exact_adjacency_allowed(self, api):
        """PRD §3.4: "A new assignment conflicts when its start is earlier than a
        committed assignment's end and that committed assignment's start is earlier
        than the new one's end, and it is rejected with
        `ERR_STAFF_WINDOW_CONFLICT`. Exact adjacency — the new window starting
        precisely when a committed window ends — is allowed."

        Design: Difficulty/resource_temporal_overlap/staff_overlap_strict_adjacency_allowed_but_true_overlap_blocked
        """
        tech, case_d, _ = self._setup_staff_scenario(api)
        # Case D starts at 10:30, exactly when the tech's window on case A ends.
        asg = assign_staff(case_d["id"], tech["id"], "SCRUB")
        assert asg["status"] == "ASSIGNED"
        assert_instant_equals(asg["window_start"], "2026-08-10T10:30:00Z")
        assert_instant_equals(asg["window_end"], "2026-08-10T11:15:00Z")

    def test_staff_one_minute_overlap_blocked(self, api):
        """PRD §3.4: "The member's committed set is every `ASSIGNED` assignment of
        theirs whose case is `SCHEDULED` or `IN_PROGRESS`, each occupying the
        strict half-open interval from its `window_start` to its `window_end` with
        no turnover buffer at all. A new assignment conflicts when its start is
        earlier than a committed assignment's end and that committed assignment's
        start is earlier than the new one's end, and it is rejected with
        `ERR_STAFF_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/staff_overlap_strict_adjacency_allowed_but_true_overlap_blocked
        """
        tech, case_d, case_e = self._setup_staff_scenario(api)
        assign_staff(case_d["id"], tech["id"], "SCRUB")  # adjacency: fine
        # Case E starts 10:29, one minute before the committed 10:30 end.
        resp = api.create_staff_assignment(
            case_e["id"], {"staff_id": tech["id"], "role_in_case": "SCRUB"},
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_STAFF_WINDOW_CONFLICT,
                       expected_status=409)
        data, meta = validate_paginated(
            api.list_staff_assignments(tech["id"], SCHEDULER))
        assert meta["total_count"] == 2
        assert all(a["status"] == "ASSIGNED" for a in data)
