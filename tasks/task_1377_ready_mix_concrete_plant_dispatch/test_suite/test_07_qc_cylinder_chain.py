"""QC cylinder chain: casting gates, break timing and segregation of duties,
certification gating on the load, and the acceptance-basis liability split."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_cylinder_set,
    get_load,
    record_seven_day_break,
    record_twenty_eight_day_break,
    set_clock,
    setup_batched_load,
    setup_cylinder_set_on_pouring_load,
    setup_final_recorded_cylinder_set,
    validate_error,
    validate_success,
)

DISP = TEST_USERS["dispatcher_headers"]
DRV1 = TEST_USERS["driver_headers"]
QC_A = TEST_USERS["qc_a_headers"]
QC_B = TEST_USERS["qc_b_headers"]
QC_C = TEST_USERS["qc_c_headers"]


class TestCastingGate:
    def test_cast_rejected_before_on_site_and_accepted_while_pouring(self, api):
        """PRD §3.8: "A `QCTech` casts a cylinder set from a load while the
        load is `ON_SITE`, `POURING`, or `COMPLETED` — casting against any
        other load state is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cylinder_cast_requires_on_site_or_later_load
        """
        ctx, load = setup_batched_load()
        res = api.create_cylinder_set(load["id"], {"num_cylinders": 3}, QC_A)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

        # Drive to POURING and cast again.
        validate_success(api.depart_load(load["id"], DRV1), 200)
        set_clock("2026-08-15T10:30:00Z")
        validate_success(api.arrive_load(load["id"], DRV1), 200)
        validate_success(api.start_pour_load(load["id"], DRV1), 200)
        cset = validate_success(
            api.create_cylinder_set(load["id"], {"num_cylinders": 3}, QC_A), 201
        )
        assert cset["status"] == "CURING"
        assert cset["acceptance_basis"] == "DESIGN_BASIS"
        assert cset["required_strength_psi"] == 4000
        assert cset["cast_by_user_id"] == "qc-a"


class TestBreakTimingAndSoD:
    def test_seven_day_break_too_early_rejected_then_accepted_at_boundary(self, api):
        """PRD §3.8: "Recording a seven-day break (break type `SEVEN_DAY`)
        requires the current logical time to be at least 7 days after
        `cast_at`, and the recorder must not be the set's `cast_by_user_id`; a
        too-early break is rejected with `ERR_BREAK_TOO_EARLY` (HTTP 422) and
        a same-person break with `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/validations/break_too_early_rejected
        """
        ctx, load, cset = setup_cylinder_set_on_pouring_load(
            cast_clock="2026-08-15T10:35:00Z"
        )
        # cast_at + 6 days: too early.
        set_clock("2026-08-21T10:35:00Z")
        res = api.record_break(
            cset["id"], {"break_type": "SEVEN_DAY", "strength_psi": 3100}, QC_B
        )
        validate_error(res, ApiErrorId.ERR_BREAK_TOO_EARLY.value)
        assert get_cylinder_set(cset["id"])["status"] == "CURING"

        # Exactly cast_at + 7 days: accepted.
        cset_after = record_seven_day_break(
            cset["id"], 3100, "2026-08-22T10:35:00Z"
        )
        assert cset_after["status"] == "SEVEN_DAY_RECORDED"
        assert cset_after["seven_day_strength_psi"] == 3100

    def test_break_recorded_by_caster_rejected(self, api):
        """PRD §3.8: "Recording a seven-day break (break type `SEVEN_DAY`)
        requires the current logical time to be at least 7 days after
        `cast_at`, and the recorder must not be the set's `cast_by_user_id`; a
        too-early break is rejected with `ERR_BREAK_TOO_EARLY` (HTTP 422) and
        a same-person break with `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/validations/sod_break_by_caster_rejected
        """
        ctx, load, cset = setup_cylinder_set_on_pouring_load(
            cast_clock="2026-08-15T10:35:00Z"
        )
        set_clock("2026-08-22T11:00:00Z")
        res = api.record_break(
            cset["id"], {"break_type": "SEVEN_DAY", "strength_psi": 3100}, QC_A
        )
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION.value)

        ok = validate_success(
            api.record_break(
                cset["id"], {"break_type": "SEVEN_DAY", "strength_psi": 3100}, QC_B
            ),
            200,
        )
        assert ok["seven_day_recorded_by"] == "qc-b"

    def test_certify_by_break_recorder_rejected(self, api):
        """PRD §3.8: "A `QCTech` — who must be neither the caster nor the
        twenty-eight-day recorder, otherwise `ERR_SOD_VIOLATION` — certifies a
        `FINAL_RECORDED` set."

        Design: Corner/validations/sod_certify_by_break_recorder_rejected
        """
        ctx, load, cset = setup_final_recorded_cylinder_set(
            seven_day_psi=3300, final_psi=4200, complete_before_breaks=True
        )
        res = api.certify_cylinder_set(cset["id"], QC_B)
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION.value)

        certified = validate_success(api.certify_cylinder_set(cset["id"], QC_C), 200)
        assert certified["status"] == "CERTIFIED"
        assert certified["acceptance_passed"] is True
        assert certified["certified_by_user_id"] == "qc-c"


class TestCertifyLoadGate:
    def test_certify_blocked_until_load_completed(self, api):
        """PRD §3.8: "The load the set was cast from must be `COMPLETED`;
        certifying against a load in any other state is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/certify_blocked_until_load_completed
        """
        ctx, load, cset = setup_final_recorded_cylinder_set(
            seven_day_psi=3300, final_psi=4200, complete_before_breaks=False
        )
        assert get_load(load["id"])["status"] == "POURING"
        res = api.certify_cylinder_set(cset["id"], QC_C)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

        set_clock("2026-09-12T12:30:00Z")
        validate_success(
            api.complete_load(load["id"], {"discharged_qty_yd3": 8.0}, DRV1), 200
        )
        certified = validate_success(api.certify_cylinder_set(cset["id"], QC_C), 200)
        assert certified["status"] == "CERTIFIED"
        assert certified["acceptance_passed"] is True
        assert certified["certified_by_user_id"] == "qc-c"

    def test_certify_passes_when_final_meets_required_strength(self, api):
        """PRD §3.8: "The acceptance test itself is the same under both bases:
        `acceptance_passed` is true if and only if `final_strength_psi` is
        greater than or equal to `required_strength_psi`. On a pass the set
        moves to `CERTIFIED`."

        Design: Difficulty/cross_entity_state_dependency/certify_blocked_until_load_completed
        """
        ctx, load, cset = setup_final_recorded_cylinder_set(
            seven_day_psi=3300, final_psi=4200, complete_before_breaks=True
        )
        certified = validate_success(api.certify_cylinder_set(cset["id"], QC_C), 200)
        assert certified["status"] == "CERTIFIED"
        assert certified["acceptance_passed"] is True
        assert certified["required_strength_psi"] == 4000
        assert certified["final_strength_psi"] == 4200


class TestAcceptanceBasisLiability:
    def test_identical_failure_yields_plant_under_design_basis(self, api):
        """PRD §3.8: "On a failure the set moves to `FLAGGED`, and liability
        is assigned per the acceptance basis: under `DESIGN_BASIS` the load's
        `strength_liability` becomes `PLANT`; under `AS_PLACED` it becomes
        `CUSTOMER` if any water addition on the load was customer-authorized,
        and `PLANT` otherwise."

        Design: Difficulty/dual_variant_calc/design_basis_vs_as_placed_strength_liability
        """
        # Leg 1: no site water -> DESIGN_BASIS failure -> PLANT.
        ctx, load, cset = setup_final_recorded_cylinder_set(
            seven_day_psi=3100, final_psi=3800, complete_before_breaks=True
        )
        flagged = validate_success(api.certify_cylinder_set(cset["id"], QC_C), 200)
        assert flagged["status"] == "FLAGGED"
        assert flagged["acceptance_basis"] == "DESIGN_BASIS"
        assert flagged["acceptance_passed"] is False
        load_after = get_load(load["id"])
        assert load_after["over_watered"] is False
        assert load_after["strength_liability"] == "PLANT"

    def test_identical_failure_yields_customer_under_as_placed(self, api):
        """PRD §3.8: "under `AS_PLACED` it becomes `CUSTOMER` if any water
        addition on the load was customer-authorized, and `PLANT` otherwise."
        PRD §3.8: "The acceptance test itself is the same under both bases:
        `acceptance_passed` is true if and only if `final_strength_psi` is
        greater than or equal to `required_strength_psi`."

        Design: Difficulty/dual_variant_calc/design_basis_vs_as_placed_strength_liability
        """
        # Leg 2: 60 customer-authorized gallons while POURING (w/c 0.561 >
        # 0.50) flips the basis; the same 3800-psi break then fails AS_PLACED.
        ctx, load, cset = setup_cylinder_set_on_pouring_load()
        validate_success(
            api.add_water(
                load["id"], {"gallons": 60, "customer_authorized": True}, DRV1
            ),
            201,
        )
        flipped = get_cylinder_set(cset["id"])
        assert flipped["acceptance_basis"] == "AS_PLACED"
        assert get_load(load["id"])["over_watered"] is True

        set_clock("2026-08-15T12:30:00Z")
        validate_success(
            api.complete_load(load["id"], {"discharged_qty_yd3": 8.0}, DRV1), 200
        )
        record_seven_day_break(cset["id"], 3100, "2026-08-22T12:00:00Z")
        record_twenty_eight_day_break(cset["id"], 3800, "2026-09-12T12:00:00Z")
        flagged = validate_success(api.certify_cylinder_set(cset["id"], QC_C), 200)
        assert flagged["status"] == "FLAGGED"
        assert flagged["acceptance_basis"] == "AS_PLACED"
        assert flagged["acceptance_passed"] is False
        load_after = get_load(load["id"])
        assert load_after["actual_wc_ratio"] == pytest.approx(0.561, abs=1e-9)
        assert load_after["strength_liability"] == "CUSTOMER"
