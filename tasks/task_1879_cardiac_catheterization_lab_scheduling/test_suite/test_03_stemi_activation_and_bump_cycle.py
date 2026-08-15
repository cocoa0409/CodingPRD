"""STEMI activation: window arithmetic, room selector, and the bump cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_staff,
    assert_device_lot_invariants,
    assert_instant_equals,
    create_cardiologist,
    create_case_payload,
    create_device_lot,
    create_recovery_bed,
    create_room,
    create_scrub_technologist,
    document_auc,
    get_bed,
    get_lot,
    post_case,
    reserve_device_usage,
    schedule_case,
    setup_case_workspace,
    setup_in_progress_workspace,
    validate_error,
    validate_paginated,
    validate_success,
)

SCHEDULER = TEST_USERS["scheduler_headers"]
NURSE_MANAGER = TEST_USERS["nurse_manager_headers"]

ELECTIVE_NEEDS = ["IVUS", "OCT", "FFR"]


class TestEstimatedCaseWindow:
    def test_elective_pci_three_equipment_tier_thirty_minutes(self, api):
        """PRD §3.2: "a base duration by procedure type — forty-five minutes for
        `DIAGNOSTIC_CATHETERIZATION`, ninety for `PCI`, seventy-five for
        `STEMI_PCI`, sixty for `DEVICE_IMPLANT`, and one hundred twenty for
        `EP_STUDY` — plus a setup allowance. The setup allowance is zero for a
        STEMI activation, the expedited branch; otherwise it is zero when the case
        lists no equipment, fifteen minutes when it lists one or two equipment
        codes, and thirty minutes when it lists three or more."

        Design: Difficulty/combinatorial_formula/estimated_case_window_tiered_setup_and_stemi_branch
        """
        workspace = setup_case_workspace(
            priority="ELECTIVE", procedure_type="PCI",
            equipment_needs=ELECTIVE_NEEDS, room_equipment=ELECTIVE_NEEDS)
        case = workspace["case"]
        assert case["status"] == "SCHEDULED"
        # PCI base 90 + 30 setup tier (three equipment codes) = 120 minutes.
        assert_instant_equals(case["scheduled_end"], "2026-08-10T11:00:00Z")

    def test_stemi_branch_zeroes_setup_and_selector_picks_zero_victim_room(self, api):
        """PRD §3.2: "The setup allowance is zero for a STEMI activation, the
        expedited branch; otherwise it is zero when the case lists no equipment,
        fifteen minutes when it lists one or two equipment codes, and thirty
        minutes when it lists three or more."
        PRD §3.2: "Among the eligible rooms the selector prefers the one where the
        fewest `SCHEDULED` `ELECTIVE` cases overlap the STEMI window — fewest
        victims first — and breaks ties by the room's `created_at` ascending, never
        by identifier."

        Design: Difficulty/combinatorial_formula/estimated_case_window_tiered_setup_and_stemi_branch
        """
        physician = create_cardiologist()
        ordering = create_cardiologist(full_name="Dr Order")
        room1 = create_room(room_name="Lab 1", equipment_profile=ELECTIVE_NEEDS)
        room2 = create_room(room_name="Lab 2", equipment_profile=ELECTIVE_NEEDS)
        bed1 = create_recovery_bed("Bed 1")
        create_recovery_bed("Bed 2")
        case_a = post_case(physician["id"], patient_mrn="MRN-A", priority="ELECTIVE",
                           equipment_needs=ELECTIVE_NEEDS)
        case_a = document_auc(case_a, ordering)
        case_a = schedule_case(case_a["id"], room1["id"], "2026-08-10T09:00:00Z",
                               bed_id=bed1["id"])

        stemi = post_case(physician["id"], patient_mrn="MRN-B",
                          procedure_type="STEMI_PCI", priority="STEMI",
                          weight_kg=80, serum_creatinine=1.2,
                          equipment_needs=ELECTIVE_NEEDS,
                          scheduled_start="2026-08-10T09:00:00Z")
        # STEMI_PCI base 75 + setup forced to 0 despite three equipment codes.
        assert_instant_equals(stemi["scheduled_end"], "2026-08-10T10:15:00Z")
        # Room 2 has zero overlapping elective victims; room 1 has one.
        assert stemi["lab_id"] == room2["id"]
        after_a = validate_success(api.get_case(case_a["id"], SCHEDULER))
        assert after_a["status"] == "SCHEDULED", \
            "the STEMI window on room 2 never touches room 1's case"


class TestBumpRescheduleCycle:
    def _setup_bump_scenario(self, api):
        physician = create_cardiologist()
        ordering = create_cardiologist(full_name="Dr Order")
        room = create_room(room_name="Lab 1")
        bed1 = create_recovery_bed("Bed 1")
        create_recovery_bed("Bed 2")
        case_e = post_case(physician["id"], patient_mrn="MRN-E",
                           procedure_type="DIAGNOSTIC_CATHETERIZATION",
                           priority="ELECTIVE")
        case_e = document_auc(case_e, ordering)
        case_e = schedule_case(case_e["id"], room["id"], "2026-08-10T09:00:00Z",
                               bed_id=bed1["id"])  # 09:00-09:45
        stemi = post_case(physician["id"], patient_mrn="MRN-S",
                          procedure_type="STEMI_PCI", priority="STEMI",
                          weight_kg=80, serum_creatinine=1.1,
                          scheduled_start="2026-08-10T09:15:00Z")
        return physician, room, case_e, stemi

    def test_stemi_bump_moves_elective_case_to_bumped_and_counts(self, api):
        """PRD §3.2: "Each victim moves `SCHEDULED` → `BUMPED`, its `bump_count`
        rises by one, and its `lab_id`, `scheduled_start`, and `scheduled_end` are
        cleared to null — indeed, those three fields remain null on any case
        sitting in `POSTED`, `BUMPED`, or `CANCELLED`."

        Design: Difficulty/non_linear_state_machine/case_bump_reschedule_cycle
        """
        _, room, case_e, stemi = self._setup_bump_scenario(api)
        assert stemi["status"] == "SCHEDULED"
        assert stemi["lab_id"] == room["id"]

        victim = validate_success(api.get_case(case_e["id"], SCHEDULER))
        assert victim["status"] == "BUMPED"
        assert victim["bump_count"] == 1
        assert victim["lab_id"] is None
        assert victim["scheduled_start"] is None
        assert victim["scheduled_end"] is None

        # The activation secures exactly one recovery bed for the STEMI case,
        # projected from the STEMI scheduled_end 10:30 (+ 90 minutes).
        beds, _ = validate_paginated(api.list_recovery_beds(NURSE_MANAGER))
        held = [b for b in beds if b["held_case_id"] == stemi["id"]]
        assert len(held) == 1
        assert held[0]["status"] == "RESERVED"
        assert_instant_equals(held[0]["window_start"], "2026-08-10T10:30:00Z")
        assert_instant_equals(held[0]["window_end"], "2026-08-10T12:00:00Z")

    def test_bumped_case_reschedule_closes_cycle(self, api):
        """PRD §3.3: "A `CathLabScheduler` schedules a `POSTED` case — or
        reschedules a `BUMPED` one, and the two transitions share their rulebook
        entirely"
        PRD §3.3: "and the cycle `SCHEDULED` → `BUMPED` → `SCHEDULED` is the normal
        recovery path after a STEMI activation."
        PRD §3.3: "An attestation recorded before a bump survives it, so a
        rescheduled elective case does not need to be re-documented."

        Design: Difficulty/non_linear_state_machine/case_bump_reschedule_cycle
        """
        _, room, case_e, _ = self._setup_bump_scenario(api)
        # After the bump, exactly one bed is still free; pin it explicitly.
        beds, _ = validate_paginated(api.list_recovery_beds(
            NURSE_MANAGER, params={"status": "AVAILABLE"}))
        assert len(beds) == 1
        rescheduled = schedule_case(case_e["id"], room["id"],
                                    "2026-08-10T13:00:00Z",
                                    bed_id=beds[0]["id"])
        assert rescheduled["status"] == "SCHEDULED", "cycle closed"
        assert rescheduled["bump_count"] == 1, "bump_count accumulates, not resets"
        assert rescheduled["lab_id"] == room["id"]
        assert_instant_equals(rescheduled["scheduled_end"], "2026-08-10T13:45:00Z")
        # DIAGNOSTIC_CATHETERIZATION base 45 + 0 setup (no equipment listed).
        assert get_bed(beds[0]["id"])["held_case_id"] == case_e["id"]


class TestStemiBumpCascade:
    def _setup_cascade_scenario(self, api):
        physician = create_cardiologist()
        ordering = create_cardiologist(full_name="Dr Order")
        tech = create_scrub_technologist()
        room = create_room(room_name="Lab 1")
        bed1 = create_recovery_bed("Bed 1")
        create_recovery_bed("Bed 2")
        lot = create_device_lot(quantity_on_hand=2, reorder_threshold=1)
        case_e = post_case(physician["id"], patient_mrn="MRN-E", priority="ELECTIVE")
        case_e = document_auc(case_e, ordering, auc_score="MAY_BE_APPROPRIATE",
                              criterion_code="AUC-45.2")
        case_e = schedule_case(case_e["id"], room["id"], "2026-08-10T09:00:00Z",
                               bed_id=bed1["id"])  # PCI 09:00-10:30
        assignment = assign_staff(case_e["id"], tech["id"], "SCRUB")
        usage = reserve_device_usage(case_e["id"], lot["id"], 2)
        return physician, tech, room, lot, case_e, assignment, usage

    def test_stemi_bump_releases_staff_and_device_reservations(self, api):
        """PRD §3.2: "the victim's reserved recovery bed returns to `AVAILABLE`
        with `held_case_id` and both window fields cleared, every `ASSIGNED` staff
        assignment on the victim is `RELEASED`, and every `RESERVED` device usage
        is `RELEASED`, which in turn recomputes each affected lot's
        `allocated_units` and derived `status`."
        PRD §3.5: "`DEPLETED` when nothing is available"

        Design: Difficulty/transitive_cascade/stemi_bump_cascade_releases_bed_staff_devices
        """
        physician, tech, room, lot, case_e, assignment, usage = \
            self._setup_cascade_scenario(api)
        pre = get_lot(lot["id"])
        assert pre["status"] == "DEPLETED", "available 2 - 2 == 0 before the bump"

        stemi = post_case(physician["id"], patient_mrn="MRN-S",
                          procedure_type="STEMI_PCI", priority="STEMI",
                          weight_kg=80, serum_creatinine=1.1,
                          scheduled_start="2026-08-10T09:30:00Z")
        assert stemi["status"] == "SCHEDULED"

        victim = validate_success(api.get_case(case_e["id"], SCHEDULER))
        assert victim["status"] == "BUMPED"
        assert victim["bump_count"] == 1

        asg_list, meta = validate_paginated(
            api.list_staff_assignments(tech["id"], SCHEDULER))
        assert meta["total_count"] == 1
        assert asg_list[0]["id"] == assignment["id"]
        assert asg_list[0]["status"] == "RELEASED", "link 2a: staff released"

        usages, meta = validate_paginated(
            api.list_lot_usages(lot["id"], TEST_USERS["technologist_headers"]))
        assert meta["total_count"] == 1
        assert usages[0]["id"] == usage["id"]
        assert usages[0]["status"] == "RELEASED", "link 2c: usage released"

    def test_stemi_bump_lot_recompute_and_bed_recommitment(self, api):
        """PRD §3.2: "every `RESERVED` device usage is `RELEASED`, which in turn
        recomputes each affected lot's `allocated_units` and derived `status`."
        PRD §3.5: "The lot's `status` is fully derived from those figures after
        every mutation that touches either counter — creation, reservation,
        release, implantation, restock: `DEPLETED` when nothing is available;
        otherwise `LOW_STOCK` when the available figure is below the
        `reorder_threshold`; otherwise `ACTIVE`."
        PRD §3.2: "The activation also reserves a recovery bed through the bed
        selector (§3.3), moving the chosen bed `AVAILABLE` → `RESERVED` with a
        recovery window beginning at the STEMI case's `scheduled_end`."

        Design: Difficulty/transitive_cascade/stemi_bump_cascade_releases_bed_staff_devices
        """
        physician, _, room, lot, _, _, _ = self._setup_cascade_scenario(api)
        stemi = post_case(physician["id"], patient_mrn="MRN-S",
                          procedure_type="STEMI_PCI", priority="STEMI",
                          weight_kg=80, serum_creatinine=1.1,
                          scheduled_start="2026-08-10T09:30:00Z")
        assert stemi["lab_id"] == room["id"]

        after = get_lot(lot["id"])
        assert after["allocated_units"] == 0, "link 3: recompute after release"
        assert after["quantity_on_hand"] == 2, "release does not consume stock"
        assert after["available_units"] == 2
        assert after["status"] == "ACTIVE", "DEPLETED flips back to ACTIVE"
        assert_device_lot_invariants(after)

        # Exactly one bed ends up committed to the STEMI case; its recovery
        # window is the scheduled variant anchored at scheduled_end 10:45.
        beds, _ = validate_paginated(api.list_recovery_beds(NURSE_MANAGER))
        held = [b for b in beds if b["held_case_id"] == stemi["id"]]
        assert len(held) == 1
        assert held[0]["status"] == "RESERVED"
        assert_instant_equals(held[0]["window_start"], "2026-08-10T10:45:00Z")
        assert_instant_equals(held[0]["window_end"], "2026-08-10T12:15:00Z")
        remaining = [b for b in beds if b["held_case_id"] != stemi["id"]]
        assert all(b["status"] == "AVAILABLE" for b in remaining)


class TestStemiSelectorFallback:
    def test_stemi_activation_with_no_eligible_room_returns_no_stemi_room(self, api):
        """PRD §3.2: "A room is eligible only when it is `ACTIVE`, when every code
        in the case's `equipment_needs` appears in the room's `equipment_profile`,
        when no case on the room is `IN_PROGRESS`, and when no `SCHEDULED` case of
        `STEMI` or `URGENT` priority on the room has a buffered window that
        overlaps the STEMI window"
        PRD §3.2: "If no room qualifies, the activation fails outright with
        `ERR_NO_STEMI_ROOM` and no case is persisted."

        Design: Corner/validations/stemi_activation_with_no_eligible_room_returns_no_stemi_room
        """
        workspace = setup_in_progress_workspace()  # the only room is busy
        case = workspace["case"]
        assert case["status"] == "IN_PROGRESS"
        resp = api.create_case(
            create_case_payload(
                patient_mrn="MRN-S", procedure_type="STEMI_PCI", priority="STEMI",
                performing_physician_id=workspace["physician"]["id"],
                weight_kg=80, serum_creatinine=1.1,
                scheduled_start="2026-08-10T09:30:00Z"),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_NO_STEMI_ROOM, expected_status=409)
        _, meta = validate_paginated(api.list_cases(SCHEDULER))
        assert meta["total_count"] == 1, "the failed activation persists nothing"
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["status"] == "IN_PROGRESS", \
            "an IN_PROGRESS case is never bumped"

    def test_stemi_selector_tiebreak_earliest_created_room(self, api):
        """PRD §3.2: "Among the eligible rooms the selector prefers the one where
        the fewest `SCHEDULED` `ELECTIVE` cases overlap the STEMI window — fewest
        victims first — and breaks ties by the room's `created_at` ascending,
        never by identifier."

        Design: Corner/cross_cutting_complexity_layers/stemi_selector_tiebreak_earliest_created_room
        """
        physician = create_cardiologist()
        room1 = create_room(room_name="Lab 1")  # earliest created
        create_room(room_name="Lab 2")
        create_recovery_bed("Bed 1")
        stemi = post_case(physician["id"], patient_mrn="MRN-S",
                          procedure_type="STEMI_PCI", priority="STEMI",
                          weight_kg=80, serum_creatinine=1.1,
                          scheduled_start="2026-08-10T09:00:00Z")
        assert stemi["status"] == "SCHEDULED"
        assert stemi["lab_id"] == room1["id"], \
            "equal eligibility: the earliest-created room wins the tie"
