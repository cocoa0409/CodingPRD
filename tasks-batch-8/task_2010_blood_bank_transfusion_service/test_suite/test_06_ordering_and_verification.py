"""Transfusion order lifecycle edges and the scarcity admission gates."""
from test_helpers import (
    ApiErrorId,
    cancel_order_payload,
    create_transfusion_order_payload,
    get_order,
    get_success_data,
    make_mtp,
    make_order,
    make_patient,
    make_policy,
    make_stock,
    make_typed_patient,
    make_verified_order,
    receive_unit_descriptor,
    reject_order_payload,
    set_clock,
    validate_error,
    validate_success,
    verify_order,
    DOC_1,
    DOC_2,
    TECH_A,
    api_client,
)


class TestOrderRejectAndCancel:
    def test_order_reject_lifecycle(self, api):
        """PRD §3.3: "A technologist who cannot verify the order instead rejects it
        from `PENDING_VERIFICATION` with a `rejection_reason`, settling it in
        terminal `REJECTED`; any other from-state draws `ERR_ORDER_NOT_REJECTABLE`."

        Design: Corner/state_machines/order_reject_lifecycle
        """
        patient = make_patient(mrn="M-2007", full_name="Kim Doe",
                               date_of_birth="1989-02-02")
        ord1 = make_order(patient["id"], product_type="FFP", units_requested=1,
                          urgency="ROUTINE", indication_code="COAG")
        ord2 = make_order(patient["id"], product_type="RBC", units_requested=1,
                          urgency="EMERGENCY", indication_code="TRAUMA")
        verify_order(ord2["id"])  # EMERGENCY may proceed untyped

        rejected = validate_success(api.reject_order(
            ord1["id"], reject_order_payload("duplicate order"), TECH_A))
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "duplicate order"

        resp = api.reject_order(ord2["id"], reject_order_payload("changed mind"),
                                TECH_A)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_REJECTABLE)

    def test_order_cancel_twice_rejected(self, api):
        """PRD §3.3: "the ordering physician may cancel the order — with an
        optional `cancel_reason` — from any of `PENDING_VERIFICATION`,
        `AWAITING_CROSSMATCH`, `READY`, `PARTIALLY_ISSUED`, or `ON_HOLD` (anything
        else: `ERR_ORDER_NOT_CANCELLABLE`)."

        Design: Corner/state_machines/order_cancel_twice_rejected
        """
        patient = make_patient(mrn="M-2002", full_name="Fran Doe",
                               date_of_birth="1979-09-09")
        order = make_order(patient["id"], product_type="FFP", units_requested=2,
                           urgency="ROUTINE", indication_code="COAGULOPATHY")
        cancelled = validate_success(api.cancel_order(
            order["id"], cancel_order_payload("order entry error"), DOC_1))
        assert cancelled["status"] == "CANCELLED"

        resp = api.cancel_order(order["id"], cancel_order_payload("again"), DOC_1)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)


class TestScarcityAdmissionGates:
    def test_shortage_gate_critical_blocks_elective_verify(self, api):
        """PRD §3.3: "First, if an `ACTIVE` par-level policy exists for that bucket
        and its current posture is `CRITICAL`, a `ROUTINE` order is rejected with
        `ERR_BUCKET_CRITICAL_ELECTIVE_BLOCKED` — elective draws on a critical
        bucket are refused outright."
        PRD §3.3: "`URGENT` and `EMERGENCY` orders pass both gates."

        Design: Corner/cross_cutting_layers/shortage_gate_critical_blocks_elective_verify
        """
        set_clock("2026-08-10T09:00:00Z")
        make_policy(product_type="RBC", abo_type="A", rh_type="POS",
                    watch_threshold=6, shortage_threshold=4, critical_threshold=2)
        patient, _ts = make_typed_patient(mrn="M-6004", full_name="Cole Doe",
                                          date_of_birth="1974-11-11", abo="A",
                                          rh="POS")
        routine = make_order(patient["id"], product_type="RBC", units_requested=1,
                             urgency="ROUTINE", indication_code="ANEMIA")
        urgent = make_order(patient["id"], product_type="RBC", units_requested=1,
                            urgency="URGENT", indication_code="ACTIVE_BLEED")

        resp = api.verify_order(routine["id"], TECH_A)
        validate_error(resp, ApiErrorId.ERR_BUCKET_CRITICAL_ELECTIVE_BLOCKED)

        verified = validate_success(api.verify_order(urgent["id"], TECH_A))
        assert verified["status"] == "AWAITING_CROSSMATCH", (
            "URGENT orders are exempt from the admission gates"
        )

    def test_mtp_triage_gate_blocks_elective_verify(self, api):
        """PRD §3.3: "Second, if any patient anywhere has an `ACTIVATED` massive
        transfusion protocol and the bucket's posture is `SHORTAGE` or `CRITICAL`,
        a `ROUTINE` order is rejected with `ERR_BUCKET_SHORTAGE_MTP_PRIORITY`,
        reserving strained stock for the protocol."
        PRD §3.6: "Standing down — a physician action requiring `ACTIVATED`
        (`ERR_MTP_NOT_ACTIVE`) — moves the record to `STANDING_DOWN`, stamps
        `stood_down_at`, and ends the patient's emergency-release privilege
        immediately."

        Design: Corner/cross_cutting_layers/mtp_triage_gate_blocks_elective_verify
        """
        set_clock("2026-08-10T09:00:00Z")
        make_policy(product_type="RBC", abo_type="A", rh_type="POS",
                    watch_threshold=6, shortage_threshold=4, critical_threshold=0)
        # One usable A POS unit -> posture SHORTAGE (1 <= 4, but 1 > 0).
        make_stock([receive_unit_descriptor("U-100", abo_type="A", rh_type="POS",
                                            donor_id="D-540", lot_number="LOT-5")])
        mtp_patient = make_patient(mrn="M-6005", full_name="Drew Doe",
                                   date_of_birth="1997-01-01")
        mtp = make_mtp(mtp_patient["id"], "massive bleed protocol")
        patient, _ts = make_typed_patient(mrn="M-6006", full_name="Elle Doe",
                                          date_of_birth="1980-05-05", abo="A",
                                          rh="POS")
        order = make_order(patient["id"], product_type="RBC", units_requested=1,
                           urgency="ROUTINE", indication_code="ANEMIA")

        resp = api.verify_order(order["id"], TECH_A)
        validate_error(resp, ApiErrorId.ERR_BUCKET_SHORTAGE_MTP_PRIORITY)

        get_success_data(api.stand_down_mtp(mtp["id"], DOC_1))
        verified = validate_success(api.verify_order(order["id"], TECH_A))
        assert verified["status"] == "AWAITING_CROSSMATCH", (
            "once no protocol is ACTIVATED the triage gate lifts"
        )
