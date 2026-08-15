"""The ON_HOLD <-> reactivate loop driven by type-and-screen expiry."""
from test_helpers import (
    ApiErrorId,
    collect_ts,
    expire_patient_typing,
    get_order,
    get_patient,
    get_success_data,
    get_ts,
    get_unit,
    make_verified_order,
    result_ts,
    set_clock,
    setup_order_with_reserved_units,
    validate_error,
    validate_success,
    validate_ts,
    TECH_A,
    api_client,
)

TS1_EXPIRY = "2026-08-13T08:00:00Z"  # specimen 2026-08-10T08:00:00Z + 72h


def _fresh_specimen(patient_id, collected_at):
    set_clock(collected_at)  # collect at the current instant (never the future)
    patient = get_patient(patient_id)
    ts = collect_ts(patient, collected_at)
    result_ts(ts["id"], abo_result="A", rh_result="POS")
    return validate_ts(ts["id"])


class TestHoldReactivateLoop:
    def test_sweep_holds_order_and_reactivate_resumes(self, api):
        """PRD §3.1: "every transfusion order of the patient sitting in
        `AWAITING_CROSSMATCH`, `READY`, or `PARTIALLY_ISSUED` drops to `ON_HOLD`,
        with bucket postures recomputed throughout."
        PRD §3.3: "Reactivation's target state is derived from the live counters
        rather than chosen by the caller: fulfillment still short of
        `units_requested` lands in `AWAITING_CROSSMATCH`"

        Design: Difficulty/non_linear_state_machine/transfusion_order_hold_reactivate_loop
        """
        ctx = setup_order_with_reserved_units(mrn="M-9011", unit_numbers=["U-100"])
        expire_patient_typing(ctx, to_iso=TS1_EXPIRY)  # sweep at the exact expiry
        assert ctx["ts"]["status"] == "EXPIRED"
        assert ctx["crossmatches"]["U-100"]["status"] == "EXPIRED"
        assert ctx["units"]["U-100"]["status"] == "AVAILABLE"
        assert ctx["order"]["status"] == "ON_HOLD", "READY dropped to ON_HOLD"

        _fresh_specimen(ctx["patient"]["id"], "2026-08-13T09:00:00Z")
        reactivated = validate_success(
            api.reactivate_order(ctx["order"]["id"], TECH_A))
        assert reactivated["status"] == "AWAITING_CROSSMATCH", (
            "fulfillment 0 < 1 derives the AWAITING_CROSSMATCH target"
        )

    def test_verify_fork_sends_plasma_order_straight_to_ready(self, api):
        """PRD §3.3: "The order's stay in `VERIFIED` is transient — within the same
        call it auto-advances to `AWAITING_CROSSMATCH` when a crossmatch is
        required, or straight to `READY` when it is not."
        PRD §3.3: "`type_restriction`, set to `O_ONLY` for red-cell-class or
        `AB_ONLY` for plasma-class products when the order was verified without an
        `ACTIVE` type-and-screen and otherwise `NONE`"

        Design: Difficulty/non_linear_state_machine/transfusion_order_hold_reactivate_loop
        """
        ctx = setup_order_with_reserved_units(mrn="M-9011", unit_numbers=["U-100"])
        expire_patient_typing(ctx, to_iso=TS1_EXPIRY)
        ts2 = _fresh_specimen(ctx["patient"]["id"], "2026-08-13T09:00:00Z")
        patient = get_patient(ctx["patient"]["id"])
        assert patient["abo_confirmed"] is True, (
            "two distinct specimens with the same ABO result latch abo_confirmed"
        )
        assert ts2["status"] == "ACTIVE"

        ffp_order = make_verified_order(patient["id"], product_type="FFP",
                                        units_requested=1, urgency="ROUTINE",
                                        indication_code="COAGULOPATHY")
        assert ffp_order["status"] == "READY", (
            "requires_crossmatch is false for plasma products"
        )
        assert ffp_order["type_restriction"] == "NONE", (
            "the verify ran with an ACTIVE type-and-screen"
        )


class TestReactivateGate:
    def test_reactivate_without_active_ts_rejected(self, api):
        """PRD §3.3: "the order must be `ON_HOLD` (`ERR_ORDER_NOT_REACTIVATABLE`
        otherwise) and the patient's `has_active_type_and_screen` true
        (`ERR_TS_NOT_ACTIVE` otherwise)."

        Design: Difficulty/cross_entity_state_dependency/order_reactivate_requires_fresh_type_and_screen
        """
        ctx = setup_order_with_reserved_units(mrn="M-9034", unit_numbers=["U-902"])
        expire_patient_typing(ctx)  # sweep at 2026-08-14T09:00:00Z
        assert ctx["patient"]["has_active_type_and_screen"] is False
        resp = api.reactivate_order(ctx["order"]["id"], TECH_A)
        validate_error(resp, ApiErrorId.ERR_TS_NOT_ACTIVE)

    def test_reactivate_with_fresh_ts_reaches_derived_state(self, api):
        """PRD §3.3: "Reactivation's target state is derived from the live counters
        rather than chosen by the caller: fulfillment still short of
        `units_requested` lands in `AWAITING_CROSSMATCH`; fulfillment satisfied
        with nothing currently issued lands in `READY`; and at least one unit
        issued with `units_transfused` still below the request lands in
        `PARTIALLY_ISSUED`."
        PRD §3.1: "the maintenance sweep moves an `ACTIVE` specimen whose time has
        come to `EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/order_reactivate_requires_fresh_type_and_screen
        """
        ctx = setup_order_with_reserved_units(mrn="M-9034", unit_numbers=["U-902"])
        expire_patient_typing(ctx)
        ts1_id = ctx["ts"]["id"]

        ts2 = _fresh_specimen(ctx["patient"]["id"], "2026-08-14T10:00:00Z")
        reactivated = validate_success(
            api.reactivate_order(ctx["order"]["id"], TECH_A))
        assert reactivated["status"] == "AWAITING_CROSSMATCH"
        assert get_ts(ts1_id)["status"] == "EXPIRED"
        assert ts2["status"] == "ACTIVE"
