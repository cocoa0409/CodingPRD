"""Depth-3 transitive cascades: permanent transition activation and the
assessment cap-shrink cascade."""
from test_helpers import (
    validate_success, get_success_data,
    create_active_home_patient, create_machine, set_clock, get_patient,
    create_draft_order, create_chair, create_slot, request_transition,
    approve_transition, activate_transition, create_accepted_assessment,
    assign_machine, api_client, make_admin_headers, make_nurse_headers,
    make_biomed_headers,
    create_maintenance_event_payload, create_home_assessment_payload,
    submit_order,
)


class TestPermanentTransitionMachineMaintenanceCascade:
    """Depth-3 chain: transition activate -> Patient TRANSITIONED_OUT ->
    machine ASSIGNED -> IN_STOCK -> its SCHEDULED MaintenanceEvent CANCELLED,
    with sibling cascades (plan CLOSED, order CANCELLED, slot CANCELLED)."""

    def test_permanent_transition_fires_full_cascade(self, api):
        """PRD §3.9: "In both cases the assigned machine returns from
        `ASSIGNED` to `IN_STOCK` with `assigned_patient_id` cleared (when the
        machine is already `IN_STOCK` this first link is inert and only the
        remaining cascades fire), that machine's `SCHEDULED` maintenance events
        are cancelled, every open order in `DRAFT`, `SUBMITTED`,
        `CHANGES_REQUESTED`, or `APPROVED` is cancelled together with its
        `SCHEDULED` delivery appointments, and the patient's future `RESERVED`
        slot reservations are cancelled. A permanent transition additionally
        closes the emergency plan — `ACTIVE` or `EXPIRED` becomes `CLOSED` —
        while a temporary one retains the plan and lets the drill clock keep
        running."

        Design: Difficulty/transitive_cascade/permanent_transition_machine_maintenance_cascade
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        plan = ctx["plan"]["id"]
        prog = ctx["program"]["id"]
        # SCHEDULED maintenance event on the assigned machine.
        evt = validate_success(api.create_maintenance_event(
            create_maintenance_event_payload(mach),
            make_biomed_headers("biomed-1")), 201)
        order = create_draft_order(pat, "2026-05",
                                   [{"sku": "DIALYSATE_2L", "quantity": 10}])
        chair = create_chair(prog, chair_code="CH-1")
        slot = create_slot(pat, chair["id"], "2026-05-12T10:00:00Z",
                           "2026-05-12T12:00:00Z")
        trans = request_transition(pat, "HOME_TO_CENTER", "PATIENT_CHOICE",
                                   "2026-05-02")
        approve_transition(trans["id"])
        set_clock("2026-05-02T00:00:00Z")
        activate_transition(trans["id"])
        patient = get_patient(pat)
        assert patient["program_status"] == "TRANSITIONED_OUT"
        assert patient["posture"] == "BLOCKED", (
            "rung 2 of the posture ladder: TRANSITIONED_OUT is BLOCKED")
        machine = get_success_data(api.get_machine(mach,
                                                   make_admin_headers("admin-1")))
        assert machine["status"] == "IN_STOCK"
        assert machine["assigned_patient_id"] is None
        events = get_success_data(api.list_machine_events(
            mach, make_admin_headers("admin-1")))
        assert events[0]["status"] == "CANCELLED", (
            "link 2: the unassigned machine's SCHEDULED events cancel")
        plans = get_success_data(api.list_patient_backup_plans(
            pat, make_admin_headers("admin-1")))
        assert plans[0]["status"] == "CLOSED"
        order_after = get_success_data(api.get_supply_order(
            order["id"], make_admin_headers("admin-1")))
        assert order_after["order_status"] == "CANCELLED"
        slots = get_success_data(api.list_patient_slot_reservations(
            pat, make_admin_headers("admin-1")))
        assert slots[0]["status"] == "CANCELLED"

    def test_temporary_transition_retains_plan_but_unassigns_machine(self, api):
        """PRD §3.9: "Activating a `HOME_TO_CENTER` fires the full cascade. A
        temporary transition (one with an `effective_to`) drops the patient to
        `SUSPENDED`; a permanent one moves the patient to the terminal
        `TRANSITIONED_OUT` — including directly from `SUSPENDED` when the
        patient was already suspended."
        PRD §3.4: "When a patient reaches `TRANSITIONED_OUT`, the plan —
        `ACTIVE` or `EXPIRED` — moves to the terminal `CLOSED` state; during a
        merely temporary center stay the plan is retained and its drill clock
        keeps running (§3.9)."

        Design: Difficulty/transitive_cascade/permanent_transition_machine_maintenance_cascade
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        trans = request_transition(pat, "HOME_TO_CENTER", "PATIENT_CHOICE",
                                   "2026-05-10", effective_to="2026-05-20")
        approve_transition(trans["id"])
        set_clock("2026-05-10T00:00:00Z")
        activate_transition(trans["id"])
        patient = get_patient(pat)
        assert patient["program_status"] == "SUSPENDED"
        machine = get_success_data(api.get_machine(mach,
                                                   make_admin_headers("admin-1")))
        assert machine["status"] == "IN_STOCK"
        assert machine["assigned_patient_id"] is None
        plans = get_success_data(api.list_patient_backup_plans(
            pat, make_admin_headers("admin-1")))
        assert plans[0]["status"] == "ACTIVE", (
            "temporary transition retains the plan")


class TestAssessmentAcceptCapShrinkCancelsOpenOrders:
    """Depth-3 chain from a different trigger: accept -> prior ACCEPTED
    SUPERSEDED -> patient cap recomputed 400 -> 100 -> over-cap open
    SUBMITTED order cascade-CANCELLED."""

    def test_cap_shrink_cancels_over_cap_open_order(self, api):
        """PRD §3.3: "Acceptance stamps `accepted_at` with the logical clock
        and fires a three-link cascade: any previously `ACCEPTED` assessment
        for the same patient becomes `SUPERSEDED` (its terminal state); the
        patient's `storage_cap_units` is recomputed from the newly accepted
        assessment; and a cap-shrink cascade sweeps the patient's open orders —
        every SupplyOrder in `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED` whose
        `on_hand_units` plus `provisional_total_units` now exceeds the shrunken
        cap is `CANCELLED`, together with any `SCHEDULED` delivery appointments
        on those orders."

        Design: Difficulty/transitive_cascade/assessment_accept_cap_shrink_cancels_open_orders
        """
        catalog = [{"sku": "CONCENTRATE_5L", "name": "Concentrate 5L",
                    "unit_price_cents": 4000, "handling_rate_cents": 20,
                    "unit_credit_cents": 1000}]
        ctx = create_active_home_patient(tpw=7, upt=12, storage_area_sqft=100,
                                         catalog=catalog)
        pat = ctx["patient"]["id"]
        asmt1 = ctx["assessment"]["id"]
        # 300 units fits cap 400 and allowance 336.
        order = create_draft_order(pat, "2026-05",
                                   [{"sku": "CONCENTRATE_5L", "quantity": 300}])
        submit_order(order["id"], pat)
        # New assessment shrinks the cap to 100.
        asmt2 = validate_success(api.create_home_assessment(
            create_home_assessment_payload(pat, assessment_kind="REASSESSMENT",
                                           storage_area_sqft=25),
            make_nurse_headers("nurse-1")), 201)
        accepted = validate_success(api.accept_assessment(
            asmt2["id"], make_nurse_headers("nurse-2")))
        assert accepted["status"] == "ACCEPTED"
        first = get_success_data(api.get_home_assessment(
            asmt1, make_admin_headers("admin-1")))
        assert first["status"] == "SUPERSEDED", "link 1: prior ACCEPTED flips"
        assert get_patient(pat)["storage_cap_units"] == 100, (
            "link 2: min(400, floor(25 * 4)) = 100")
        order_after = get_success_data(api.get_supply_order(
            order["id"], make_admin_headers("admin-1")))
        assert order_after["order_status"] == "CANCELLED", (
            "link 3: 0 on-hand + 300 units > 100 cap triggers cap-shrink")

    def test_accept_supersedes_without_shrink_keeps_orders(self, api):
        """PRD §3.3: "Acceptance stamps `accepted_at` with the logical clock
        and fires a three-link cascade: any previously `ACCEPTED` assessment
        for the same patient becomes `SUPERSEDED` (its terminal state); the
        patient's `storage_cap_units` is recomputed from the newly accepted
        assessment; and a cap-shrink cascade sweeps the patient's open orders —
        every SupplyOrder in `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED` whose
        `on_hand_units` plus `provisional_total_units` now exceeds the shrunken
        cap is `CANCELLED`, together with any `SCHEDULED` delivery appointments
        on those orders."

        Design: Difficulty/transitive_cascade/assessment_accept_cap_shrink_cancels_open_orders
        """
        ctx = create_active_home_patient(storage_area_sqft=100)
        pat = ctx["patient"]["id"]
        asmt1 = ctx["assessment"]["id"]
        order = create_draft_order(pat, "2026-05",
                                   [{"sku": "DIALYSATE_2L", "quantity": 10}])
        submit_order(order["id"], pat)
        # Reassessment with the same 100 sqft: cap unchanged (400), no shrink.
        asmt2 = validate_success(api.create_home_assessment(
            create_home_assessment_payload(pat, assessment_kind="REASSESSMENT",
                                           storage_area_sqft=100),
            make_nurse_headers("nurse-1")), 201)
        validate_success(api.accept_assessment(asmt2["id"],
                                               make_nurse_headers("nurse-2")))
        first = get_success_data(api.get_home_assessment(
            asmt1, make_admin_headers("admin-1")))
        assert first["status"] == "SUPERSEDED"
        assert get_patient(pat)["storage_cap_units"] == 400
        order_after = get_success_data(api.get_supply_order(
            order["id"], make_admin_headers("admin-1")))
        assert order_after["order_status"] == "SUBMITTED", (
            "order fits the recomputed cap, so the cascade does not cancel it")
