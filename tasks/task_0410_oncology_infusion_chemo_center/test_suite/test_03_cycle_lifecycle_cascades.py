"""Treatment-cycle lifecycle, cascades, and toxicity holds (PRD §3.2, §3.5, §3.9, §3.11).

Queue A: non_linear_state_machine (active<->on_hold loop), transitive_cascade
(grade3 toxicity hold cancels children), cross_entity_state_dependency
(order-create / check-in require ACTIVE cycle), compensating_invariant (chair
released on hold cancel).
Queue B: publish preconditions, activate preconditions, resume-not-on-hold,
advance unresolved/completed, grade2 no-hold, abandon cascade.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    factories as f,
    fixtures as fx,
    make_nurse_headers,
)
from test_helpers.test_users import TEST_USERS

PHARM = TEST_USERS["pharmacist_headers"]

FLAT_CHEMO = dict(drug_name="DrugC", role="CHEMO", dosing_method="FLAT",
                  flat_dose_mg=600, vial_size_mg=150, day_offset=1, sequence_index=1)


class TestActiveOnHoldLoop:
    def test_hold_resume_hold_cycles_status(self):
        """PRD §3.9: "Placing an `ACTIVE` cycle `ON_HOLD` may be done explicitly by
        a `Nurse` or `Pharmacist`"
        PRD §3.9: "Resuming returns an `ON_HOLD` cycle to `ACTIVE`."

        hold -> ON_HOLD, resume -> ACTIVE, hold again -> ON_HOLD: a back-and-forth
        loop on the same cycle.

        Design: Difficulty/non_linear_state_machine/nonlinear_treatment_cycle_active_onhold_cycle
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO),
                                    protocol_overrides=dict(total_cycles=2))
        cyc = env["cycle"]["id"]
        held1 = validate_success(api_client.hold_treatment_cycle(cyc, PHARM), 200)
        assert held1["status"] == "ON_HOLD"
        resumed = validate_success(api_client.resume_treatment_cycle(cyc, PHARM), 200)
        assert resumed["status"] == "ACTIVE", f"after resume expected ACTIVE, got {resumed['status']}"
        held2 = validate_success(api_client.hold_treatment_cycle(cyc, PHARM), 200)
        assert held2["status"] == "ON_HOLD", f"after second hold expected ON_HOLD, got {held2['status']}"


class TestToxicityCascade:
    def test_grade3_toxicity_holds_cycle_and_cancels_children(self):
        """PRD §3.11: "When the recorded `ctcae_grade` is 3 or higher and the cycle
        is currently `ACTIVE`, recording the event automatically places the cycle
        `ON_HOLD` with the same two-step child cascade described in Section 3.9 —
        open drug orders cancelled, then open appointments cancelled — and
        increments the cycle's `version`; for that event `triggered_hold` is true."

        A grade-4 event holds the cycle, cancelling the open ORDERED order and the
        SCHEDULED appointment.

        Design: Difficulty/transitive_cascade/cascade_toxicity_grade3_holds_cycle_cancels_children
        """
        env = fx.setup_active_cycle_with_chair_and_nurse(item_overrides=dict(FLAT_CHEMO))
        cyc = env["cycle"]
        order = fx.create_drug_order(cyc["id"], env["item"]["id"])
        appt = fx.book_appointment(
            cyc["id"], env["chair"]["id"], env["nurse"]["id"],
            "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, cyc["version"])

        tox = validate_success(api_client.create_toxicity_event(
            f.create_toxicity_event_payload(cyc["id"], 4, "anaphylaxis",
                                            drug_order_id=order["id"]),
            make_nurse_headers(env["nurse"]["id"])), 201)
        assert tox["triggered_hold"] is True

        cycle_now = validate_success(api_client.get_treatment_cycle(cyc["id"], PHARM), 200)
        assert cycle_now["status"] == "ON_HOLD"
        order_now = validate_success(api_client.get_drug_order(order["id"], PHARM), 200)
        assert order_now["status"] == "CANCELLED", f"order should be cancelled, got {order_now['status']}"
        appt_now = validate_success(api_client.get_infusion_appointment(appt["id"], PHARM), 200)
        assert appt_now["status"] == "CANCELLED", f"appt should be cancelled, got {appt_now['status']}"

    def test_grade2_toxicity_does_not_hold_cycle(self):
        """PRD §3.11: "An event of grade 1 or 2, or any event recorded against a
        cycle that is not `ACTIVE`, does not move the cycle and leaves
        `triggered_hold` false."

        A grade-2 event leaves triggered_hold false and the cycle ACTIVE.

        Design: Corner/state_machines/error_toxicity_grade2_no_hold
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        tox = validate_success(api_client.create_toxicity_event(
            f.create_toxicity_event_payload(env["cycle"]["id"], 2, "mild nausea"),
            make_nurse_headers(fx.create_nurse(full_name="Tri")["id"])), 201)
        assert tox["triggered_hold"] is False
        cycle_now = validate_success(api_client.get_treatment_cycle(env["cycle"]["id"], PHARM), 200)
        assert cycle_now["status"] == "ACTIVE"


class TestCrossEntityCycleState:
    def test_create_drug_order_requires_active_cycle(self):
        """PRD §3.7: "Creating an order requires the parent cycle to be `ACTIVE`;
        attempting it against any other cycle state is rejected with
        `ERR_CYCLE_NOT_ACTIVE`."

        Against an ON_HOLD cycle the create is rejected with ERR_CYCLE_NOT_ACTIVE.

        Design: Difficulty/cross_entity_state_dependency/cross_entity_order_create_requires_cycle_active
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        validate_success(api_client.hold_treatment_cycle(env["cycle"]["id"], PHARM), 200)
        resp = api_client.create_drug_order(
            f.create_drug_order_payload(env["cycle"]["id"], env["item"]["id"]), PHARM)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_ACTIVE.value)

    def test_check_in_succeeds_on_active_cycle(self):
        """PRD §3.10: "a `Nurse` checks the patient in, advancing the appointment
        from `SCHEDULED` to `CHECKED_IN`; check-in requires the appointment to be
        `SCHEDULED` (otherwise `ERR_APPOINTMENT_NOT_SCHEDULED`) and the parent
        cycle to be `ACTIVE` (otherwise `ERR_CYCLE_NOT_ACTIVE`)."

        On an ACTIVE cycle the SCHEDULED->CHECKED_IN check-in succeeds.

        Design: Difficulty/cross_entity_state_dependency/cross_entity_appointment_checkin_requires_cycle_active
        """
        env = fx.setup_active_cycle_with_chair_and_nurse(item_overrides=dict(FLAT_CHEMO))
        cyc = env["cycle"]
        appt = fx.book_appointment(
            cyc["id"], env["chair"]["id"], env["nurse"]["id"],
            "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, cyc["version"])
        checked = validate_success(api_client.check_in_infusion_appointment(
            appt["id"], make_nurse_headers(env["nurse"]["id"])), 200)
        assert checked["status"] == "CHECKED_IN"


class TestChairReleasedOnHold:
    def test_hold_cancel_releases_chair_interval_for_rebooking(self):
        """PRD §3.9: "Second, every infusion appointment of the cycle in
        `SCHEDULED` or `CHECKED_IN` is moved to `CANCELLED`, releasing the chair
        and nurse intervals they held."
        PRD §3.10: "A non-terminal appointment — `SCHEDULED` or `CHECKED_IN` — may
        be cancelled by a `Nurse` or `Pharmacist`, moving it to `CANCELLED` and
        releasing its chair and nurse interval"

        The 09:00-10:30 interval cancelled by the hold is fully released, so the
        identical interval re-books successfully after resume.

        Design: Difficulty/compensating_invariant/invariant_chair_minutes_released_on_hold_cancel
        """
        env = fx.setup_active_cycle_with_chair_and_nurse(item_overrides=dict(FLAT_CHEMO))
        cyc = env["cycle"]
        appt1 = fx.book_appointment(
            cyc["id"], env["chair"]["id"], env["nurse"]["id"],
            "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, cyc["version"])
        held = validate_success(api_client.hold_treatment_cycle(cyc["id"], PHARM), 200)
        resumed = validate_success(api_client.resume_treatment_cycle(cyc["id"], PHARM), 200)

        appt1_now = validate_success(api_client.get_infusion_appointment(appt1["id"], PHARM), 200)
        assert appt1_now["status"] == "CANCELLED"

        appt2 = validate_success(api_client.create_infusion_appointment(
            f.create_infusion_appointment_payload(
                cyc["id"], env["chair"]["id"], env["nurse"]["id"],
                "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, resumed["version"]),
            PHARM), 201)
        assert appt2["status"] == "SCHEDULED", f"re-book should succeed, got {appt2['status']}"
        assert appt2["start_at"] == "2026-07-01T09:00:00Z"


class TestAbandonCascade:
    def test_abandon_cancels_children(self):
        """PRD §3.9: "Abandonment moves `status` to `ABANDONED`, then cascades
        exactly as a hold does over its children: every non-terminal drug order of
        the cycle is moved to `CANCELLED` and every non-terminal infusion
        appointment of the cycle is moved to `CANCELLED`, and the cycle's
        `version` increments by 1."

        Design: Corner/cross_cutting_complexity_layers/abandon_cycle_cascade_cancels_children
        """
        env = fx.setup_active_cycle_with_chair_and_nurse(item_overrides=dict(FLAT_CHEMO))
        cyc = env["cycle"]
        order = fx.create_drug_order(cyc["id"], env["item"]["id"])
        appt = fx.book_appointment(
            cyc["id"], env["chair"]["id"], env["nurse"]["id"],
            "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, cyc["version"])
        abandoned = validate_success(api_client.abandon_treatment_cycle(cyc["id"], PHARM), 200)
        assert abandoned["status"] == "ABANDONED"
        order_now = validate_success(api_client.get_drug_order(order["id"], PHARM), 200)
        assert order_now["status"] == "CANCELLED"
        appt_now = validate_success(api_client.get_infusion_appointment(appt["id"], PHARM), 200)
        assert appt_now["status"] == "CANCELLED"


class TestProtocolPublishPreconditions:
    def test_publish_without_items_rejected(self):
        """PRD §3.2: "the protocol must have at least one order set item, or the
        publish is rejected with `ERR_NO_ORDER_SET_ITEMS`"

        Design: Corner/state_machines/publish_protocol_without_items_rejected
        """
        protocol = fx.create_protocol()
        resp = api_client.publish_regimen_protocol(protocol["id"], PHARM)
        validate_error(resp, ApiErrorId.ERR_NO_ORDER_SET_ITEMS.value)
        proto_now = validate_success(api_client.get_regimen_protocol(protocol["id"], PHARM), 200)
        assert proto_now["status"] == "DRAFT"

    def test_publish_premed_only_rejected(self):
        """PRD §3.2: "it must have at least one order set item whose `role` is
        `CHEMO`, or the publish is rejected with `ERR_NO_CHEMO_ITEM`"

        Design: Corner/state_machines/publish_protocol_premed_only_rejected
        """
        protocol = fx.create_protocol()
        fx.add_order_set_item(protocol["id"], drug_name="Ondansetron", role="PREMED",
                              dosing_method="FLAT", flat_dose_mg=8, vial_size_mg=8,
                              day_offset=1, sequence_index=1)
        resp = api_client.publish_regimen_protocol(protocol["id"], PHARM)
        validate_error(resp, ApiErrorId.ERR_NO_CHEMO_ITEM.value)


class TestCycleActivationPreconditions:
    def test_activate_unpublished_protocol_rejected(self):
        """PRD §3.5: "the protocol's `status` must be `PUBLISHED`, or it is
        rejected with `ERR_PROTOCOL_NOT_PUBLISHED`"

        Design: Corner/state_machines/activate_cycle_unpublished_protocol_rejected
        """
        patient = fx.create_patient()
        protocol = fx.create_protocol()
        fx.add_order_set_item(protocol["id"], **FLAT_CHEMO)  # CHEMO item but never published
        cycle = fx.create_cycle(patient["id"], protocol["id"])
        resp = api_client.activate_treatment_cycle(cycle["id"], PHARM)
        validate_error(resp, ApiErrorId.ERR_PROTOCOL_NOT_PUBLISHED.value)

    def test_activate_deceased_patient_rejected(self):
        """PRD §3.5: "the patient's `status` must be `ACTIVE`, or the activation is
        rejected with `ERR_PATIENT_NOT_ACTIVE`"

        Design: Corner/state_machines/activate_cycle_deceased_patient_rejected
        """
        patient = fx.create_patient()
        protocol, _ = fx.setup_published_protocol_with_item(item_overrides=dict(FLAT_CHEMO))
        cycle = fx.create_cycle(patient["id"], protocol["id"])
        validate_success(api_client.mark_patient_deceased(patient["id"], PHARM), 200)
        resp = api_client.activate_treatment_cycle(cycle["id"], PHARM)
        validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_ACTIVE.value)


class TestCycleAdvanceResume:
    def test_resume_active_cycle_rejected(self):
        """PRD §3.9: "A `Pharmacist` resumes only when the cycle is `ON_HOLD`
        (otherwise `ERR_CYCLE_NOT_ON_HOLD`)"

        Resuming an ACTIVE (never-held) cycle returns ERR_CYCLE_NOT_ON_HOLD.

        Design: Corner/state_machines/resume_cycle_not_on_hold_rejected
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        resp = api_client.resume_treatment_cycle(env["cycle"]["id"], PHARM)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_ON_HOLD.value)

    def test_advance_with_unresolved_order_rejected(self):
        """PRD §3.9: "A `Pharmacist` advances a cycle that is `ACTIVE` (otherwise
        `ERR_CYCLE_NOT_ACTIVE`) and only when every drug order of the current
        cycle is in `ADMINISTERED` or `CANCELLED` (otherwise
        `ERR_UNRESOLVED_ORDERS`)."

        With one still-ORDERED order, advance-cycle returns ERR_UNRESOLVED_ORDERS.

        Design: Corner/state_machines/advance_cycle_with_unresolved_order_rejected
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO),
                                    protocol_overrides=dict(total_cycles=2))
        fx.create_drug_order(env["cycle"]["id"], env["item"]["id"])
        resp = api_client.advance_treatment_cycle(env["cycle"]["id"], PHARM)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_ORDERS.value)

    def test_advance_completes_on_final_cycle(self):
        """PRD §3.9: "when `current_cycle_number` already equals `total_cycles`,
        the advance instead moves `status` to `COMPLETED`."

        On a single-cycle protocol with no outstanding orders, advance completes
        the cycle.

        Design: Corner/state_machines/advance_cycle_to_completed_on_final_cycle
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO),
                                    protocol_overrides=dict(total_cycles=1))
        advanced = validate_success(api_client.advance_treatment_cycle(env["cycle"]["id"], PHARM), 200)
        assert advanced["status"] == "COMPLETED", f"expected COMPLETED, got {advanced['status']}"
