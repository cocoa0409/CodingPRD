"""Second assertions for each difficulty (queue A) instance.

Each test here covers a distinct, separately-PRD-derivable observable facet of
the same difficulty rule already exercised in test_01..test_04, satisfying the
queue-A requirement of >= 2 tests per difficulty instance. Every docstring
carries the same Design tag as its companion test.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    assert_dose_waste_invariants,
    factories as f,
    fixtures as fx,
    make_nurse_headers,
)
from test_helpers.test_users import TEST_USERS

PHARM = TEST_USERS["pharmacist_headers"]

FLAT_CHEMO = dict(drug_name="DrugC", role="CHEMO", dosing_method="FLAT",
                  flat_dose_mg=600, vial_size_mg=150, day_offset=1, sequence_index=1)
BSA_ITEM = dict(drug_name="DrugB", role="CHEMO", dosing_method="BSA",
                dose_per_m2=175, vial_size_mg=50, flat_dose_mg=None,
                day_offset=1, sequence_index=1)
AUC_ITEM = dict(drug_name="DrugA", role="CHEMO", dosing_method="AUC",
                target_auc=5, vial_size_mg=150, flat_dose_mg=None,
                day_offset=1, sequence_index=2)


class TestDualVariantSecond:
    def test_bsa_order_derives_full_vial_waste_chain(self):
        """PRD §3.7: "with a dose per square meter of 175, a frozen body-surface
        snapshot of 1.82, no reduction, and a 50 mg vial, the base is 175 times
        1.82 equals 318.5; with no reduction the reduced figure is 318.5; rounding
        318.5 half-up gives an ordered dose of 319 mg; dividing 319 by 50 and
        rounding up gives 7 vials; supplied is 350 mg; waste is 31 mg; and the JW
        flag is true."

        Design: Difficulty/dual_variant_calc/dual_variant_bsa_vs_auc_ordered_dose
        """
        env = fx.setup_active_cycle(
            patient_overrides=dict(height_cm=170, weight_kg=70, gfr_ml_min=80),
            item_overrides=dict(BSA_ITEM))
        order = validate_success(api_client.create_drug_order(
            f.create_drug_order_payload(env["cycle"]["id"], env["item"]["id"]), PHARM), 201)
        assert order["ordered_dose_mg"] == 319
        assert order["vials_drawn"] == 7, f"expected 7 vials, got {order['vials_drawn']}"
        assert order["supplied_mg"] == 350
        assert order["waste_mg"] == 31
        assert order["jw_modifier"] is True
        assert_dose_waste_invariants(order)

    def test_repeated_post_patch_order_still_uses_frozen_snapshot(self):
        """PRD §2.7: "every dose computed for that cycle reads those snapshots, so
        that later edits to the patient's height, weight, or renal function never
        retroactively change an active cycle's doses."

        Even a second order created after the patient's live BSA rose to 2.0 still
        doses off the frozen 1.82 -> 319 mg.

        Design: Difficulty/dual_variant_calc/dual_variant_frozen_snapshot_vs_live_patient_bsa
        """
        env = fx.setup_active_cycle(
            patient_overrides=dict(height_cm=170, weight_kg=70, gfr_ml_min=80),
            item_overrides=dict(BSA_ITEM))
        validate_success(api_client.update_patient(
            env["patient"]["id"], {"height_cm": 180, "weight_kg": 80}, PHARM), 200)
        first = validate_success(api_client.create_drug_order(
            f.create_drug_order_payload(env["cycle"]["id"], env["item"]["id"]), PHARM), 201)
        second = validate_success(api_client.create_drug_order(
            f.create_drug_order_payload(env["cycle"]["id"], env["item"]["id"]), PHARM), 201)
        assert first["ordered_dose_mg"] == 319
        assert second["ordered_dose_mg"] == 319, (
            f"second post-PATCH order must still use frozen snapshot, got {second['ordered_dose_mg']}")


class TestCombinatorialSecond:
    def test_zero_reduction_baseline_distinguishes_reduce_before_round(self):
        """PRD §3.7: "The reduction is then applied to this unrounded base: the
        reduced dose is the base multiplied by the quantity one minus
        `dose_reduction_pct` divided by 100. The `ordered_dose_mg` is that reduced
        figure rounded half-up to a whole number of milligrams."

        With dose_reduction_pct=0 the AUC base 5*(80+25)=525 yields 525, the
        un-reduced anchor against which the 20%->420 reduction is contrasted.

        Design: Difficulty/combinatorial_formula/combinatorial_dose_reduction_then_round_order_fixed
        """
        env = fx.setup_active_cycle(patient_overrides=dict(gfr_ml_min=80),
                                    item_overrides=dict(AUC_ITEM))
        order = validate_success(api_client.create_drug_order(
            f.create_drug_order_payload(env["cycle"]["id"], env["item"]["id"],
                                        dose_reduction_pct=0), PHARM), 201)
        assert order["ordered_dose_mg"] == 525, f"expected 525, got {order['ordered_dose_mg']}"

    def test_calvert_cap_at_exactly_125_gfr(self):
        """PRD §3.7: "the item's `target_auc` multiplied by the quantity formed by
        taking the smaller of the cycle's frozen `gfr_snapshot_ml_min` and 125,
        then adding 25 — the glomerular filtration rate is capped at 125 before
        the addition"

        At gfr exactly 125 the min() is 125 -> 5*(125+25)=750, the boundary value
        the cap clamps everything at or above 125 onto.

        Design: Difficulty/combinatorial_formula/combinatorial_auc_calvert_min_cap_nonlinear
        """
        env = fx.setup_active_cycle(patient_overrides=dict(gfr_ml_min=125),
                                    item_overrides=dict(AUC_ITEM))
        order = validate_success(api_client.create_drug_order(
            f.create_drug_order_payload(env["cycle"]["id"], env["item"]["id"]), PHARM), 201)
        assert order["ordered_dose_mg"] == 750, f"expected 750 at gfr 125, got {order['ordered_dose_mg']}"


class TestNonlinearStateMachineSecond:
    def test_reprepared_order_can_be_verified_by_independent_nurse(self):
        """PRD §3.8: "When all four hold, the acting nurse's identity is recorded
        in `verified_by_nurse_id` and the order becomes `VERIFIED`."

        After the reject-revert loop returns the order to ORDERED and a new nurse
        re-prepares it, a third independent certified nurse completes the forward
        edge ORDERED->PREPARED->VERIFIED.

        Design: Difficulty/non_linear_state_machine/nonlinear_drug_order_prepare_reject_revert_loop
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        n1 = fx.create_nurse(full_name="N1", is_chemo_certified=True)
        n2 = fx.create_nurse(full_name="N2", is_chemo_certified=True)
        n3 = fx.create_nurse(full_name="N3", is_chemo_certified=True)
        order = fx.create_drug_order(env["cycle"]["id"], env["item"]["id"])
        fx.prepare_order(order["id"], n1["id"])
        validate_success(api_client.reject_drug_order(order["id"], make_nurse_headers(n2["id"])), 200)
        fx.prepare_order(order["id"], n2["id"])  # re-prepared by n2
        verified = validate_success(api_client.verify_drug_order(
            order["id"], f.verify_drug_order_payload(order["ordered_dose_mg"]),
            make_nurse_headers(n3["id"])), 200)
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_nurse_id"] == n3["id"]

    def test_hold_and_resume_each_increment_cycle_version(self):
        """PRD §3.9: "The hold then moves the cycle `status` to `ON_HOLD` and
        increments the cycle's `version` by 1."
        PRD §3.9: "Resume moves `status` to `ACTIVE` and increments `version` by
        1."

        Each leg of the ACTIVE<->ON_HOLD loop bumps version monotonically.

        Design: Difficulty/non_linear_state_machine/nonlinear_treatment_cycle_active_onhold_cycle
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO),
                                    protocol_overrides=dict(total_cycles=2))
        cyc = env["cycle"]["id"]
        v0 = env["cycle"]["version"]
        held = validate_success(api_client.hold_treatment_cycle(cyc, PHARM), 200)
        assert held["version"] == v0 + 1, f"hold should bump version to {v0+1}, got {held['version']}"
        resumed = validate_success(api_client.resume_treatment_cycle(cyc, PHARM), 200)
        assert resumed["version"] == v0 + 2, f"resume should bump to {v0+2}, got {resumed['version']}"


class TestTransitiveCascadeSecond:
    def test_grade3_boundary_toxicity_triggers_hold(self):
        """PRD §3.11: "When the recorded `ctcae_grade` is 3 or higher and the cycle
        is currently `ACTIVE`, recording the event automatically places the cycle
        `ON_HOLD` ... for that event `triggered_hold` is true."

        At the exact threshold grade 3 the auto-hold fires (triggered_hold true,
        cycle ON_HOLD).

        Design: Difficulty/transitive_cascade/cascade_toxicity_grade3_holds_cycle_cancels_children
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        tox = validate_success(api_client.create_toxicity_event(
            f.create_toxicity_event_payload(env["cycle"]["id"], 3, "grade 3 reaction"),
            make_nurse_headers(fx.create_nurse(full_name="Ntri")["id"])), 201)
        assert tox["triggered_hold"] is True
        cycle_now = validate_success(api_client.get_treatment_cycle(env["cycle"]["id"], PHARM), 200)
        assert cycle_now["status"] == "ON_HOLD"

    def test_administered_order_records_dose_when_pa_exhausts(self):
        """PRD §3.8: "On success the order's `administered_dose_mg` is set to
        `ordered_dose_mg` and `status` becomes `ADMINISTERED`."

        The administer that drives the PA to EXHAUSTED also sets the order's
        administered_dose_mg to its ordered 525.

        Design: Difficulty/transitive_cascade/cascade_administer_consumes_pa_then_exhausts
        """
        env = fx.setup_verified_order_with_pa(authorized_units_mg=525)
        administered = validate_success(api_client.administer_drug_order(
            env["order"]["id"], make_nurse_headers(env["nb"]["id"])), 200)
        assert administered["administered_dose_mg"] == 525
        pa = validate_success(api_client.get_prior_authorization(env["pa"]["id"], PHARM), 200)
        assert pa["status"] == "EXHAUSTED"


class TestPriorityPairSecond:
    def test_certified_same_nurse_verify_returns_same_nurse_error(self):
        """PRD §3.8: "Third, the acting nurse must differ from the recorded
        `prepared_by_nurse_id`, enforcing segregation of duties; a
        self-verification is rejected with `ERR_SAME_NURSE_VERIFICATION` (409)."

        With the certification gate satisfied (the preparer IS certified), the
        same-nurse self-verify now surfaces ERR_SAME_NURSE_VERIFICATION, isolating
        the lower-priority rule.

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_certified_vs_same_nurse
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        n1 = fx.create_nurse(full_name="N1cert", is_chemo_certified=True)
        order = fx.create_drug_order(env["cycle"]["id"], env["item"]["id"])
        fx.prepare_order(order["id"], n1["id"])
        resp = api_client.verify_drug_order(
            order["id"], f.verify_drug_order_payload(600), make_nurse_headers(n1["id"]))
        validate_error(resp, ApiErrorId.ERR_SAME_NURSE_VERIFICATION.value)


class TestBoundaryPrecisionSecond:
    def test_single_appointment_acuity_equal_to_max_allowed(self):
        """PRD §3.10: "The rejection fires only when the load is strictly greater
        than `max_acuity_load` — a load exactly equal to the ceiling is
        permitted"

        A lone acuity-5 booking on a max_acuity_load=5 nurse has concurrent load
        exactly 5 (==max) and is permitted. (acuity stays within the PRD-declared
        1..5 range per §3.10 so the load check — not body validation — governs.)

        Design: Difficulty/boundary_precision_check/boundary_nurse_acuity_at_max_allowed
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        chair = fx.create_chair(label="C-max5")
        nurse = fx.create_nurse(full_name="Nmax5", is_chemo_certified=True, max_acuity_load=5)
        cyc = env["cycle"]
        appt = validate_success(api_client.create_infusion_appointment(
            f.create_infusion_appointment_payload(
                cyc["id"], chair["id"], nurse["id"],
                "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 5, cyc["version"]),
            PHARM), 201)
        assert appt["status"] == "SCHEDULED"
        assert appt["acuity"] == 5

    def test_one_milligram_over_vial_boundary_sets_jw(self):
        """PRD §3.7: "The `jw_modifier` flag is true exactly when `waste_mg` is
        greater than zero, marking the discarded single-use-vial drug as
        JW-billable."

        A FLAT 601 mg order on 150 mg vials needs 5 vials (supplied 750), leaving
        waste 149>0 -> jw_modifier true, the strictly-positive companion to the
        zero-waste case.

        Design: Difficulty/boundary_precision_check/boundary_jw_waste_zero_no_modifier
        """
        env = fx.setup_active_cycle(
            item_overrides=dict(drug_name="DrugC", role="CHEMO", dosing_method="FLAT",
                                flat_dose_mg=601, vial_size_mg=150, day_offset=1, sequence_index=1))
        order = validate_success(api_client.create_drug_order(
            f.create_drug_order_payload(env["cycle"]["id"], env["item"]["id"]), PHARM), 201)
        assert order["ordered_dose_mg"] == 601
        assert order["vials_drawn"] == 5, f"expected 5 vials, got {order['vials_drawn']}"
        assert order["waste_mg"] == 149
        assert order["jw_modifier"] is True
        assert_dose_waste_invariants(order)


class TestCrossEntityStateSecond:
    def test_create_order_on_planned_cycle_rejected(self):
        """PRD §3.7: "Creating an order requires the parent cycle to be `ACTIVE`;
        attempting it against any other cycle state is rejected with
        `ERR_CYCLE_NOT_ACTIVE`."

        Against a PLANNED (never-activated) cycle the create is also rejected with
        ERR_CYCLE_NOT_ACTIVE — a different non-ACTIVE parent state than ON_HOLD.

        Design: Difficulty/cross_entity_state_dependency/cross_entity_order_create_requires_cycle_active
        """
        patient = fx.create_patient()
        protocol, item = fx.setup_published_protocol_with_item(item_overrides=dict(FLAT_CHEMO))
        cycle = fx.create_cycle(patient["id"], protocol["id"])  # PLANNED
        resp = api_client.create_drug_order(
            f.create_drug_order_payload(cycle["id"], item["id"]), PHARM)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_ACTIVE.value)

    def test_completed_after_checkin_on_active_cycle(self):
        """PRD §3.10: "A nurse then completes a checked-in appointment, advancing
        it from `CHECKED_IN` to `COMPLETED`; completion requires the appointment
        to be `CHECKED_IN` (otherwise `ERR_APPOINTMENT_NOT_CHECKED_IN`)."

        On an ACTIVE cycle, check-in then complete advances the appointment all
        the way to COMPLETED, confirming the cross-entity ACTIVE precondition lets
        the forward path proceed.

        Design: Difficulty/cross_entity_state_dependency/cross_entity_appointment_checkin_requires_cycle_active
        """
        env = fx.setup_active_cycle_with_chair_and_nurse(item_overrides=dict(FLAT_CHEMO))
        cyc = env["cycle"]
        nurse_h = make_nurse_headers(env["nurse"]["id"])
        appt = fx.book_appointment(cyc["id"], env["chair"]["id"], env["nurse"]["id"],
                                   "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, cyc["version"])
        validate_success(api_client.check_in_infusion_appointment(appt["id"], nurse_h), 200)
        completed = validate_success(api_client.complete_infusion_appointment(appt["id"], nurse_h), 200)
        assert completed["status"] == "COMPLETED"


class TestResourceTemporalOverlapSecond:
    def test_chair_adjacency_back_to_back_allowed(self):
        """PRD §2.8: "Two intervals overlap only when each starts strictly before
        the other ends; intervals that merely touch — one ending exactly when the
        next begins — do not overlap and may share a chair or nurse back-to-back."

        A 10:30-11:30 booking on the same chair as a 09:00-10:30 appointment is
        adjacency (end==start), not overlap, so it succeeds.

        Design: Difficulty/resource_temporal_overlap/overlap_chair_double_book_rejected
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        chair = fx.create_chair(label="C-adj")
        n1 = fx.create_nurse(full_name="Nadj1", is_chemo_certified=True, max_acuity_load=6)
        n2 = fx.create_nurse(full_name="Nadj2", is_chemo_certified=True, max_acuity_load=6)
        cyc = env["cycle"]
        fx.book_appointment(cyc["id"], chair["id"], n1["id"],
                            "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, cyc["version"])
        appt2 = validate_success(api_client.create_infusion_appointment(
            f.create_infusion_appointment_payload(
                cyc["id"], chair["id"], n2["id"],
                "2026-07-01T10:30:00Z", "2026-07-01T11:30:00Z", 2, cyc["version"]),
            PHARM), 201)
        assert appt2["status"] == "SCHEDULED", f"adjacency should be allowed, got {appt2['status']}"

    def test_nonoverlapping_nurse_intervals_do_not_aggregate(self):
        """PRD §3.10: "take every `SCHEDULED` or `CHECKED_IN` appointment already
        on that same nurse whose half-open interval overlaps the requested
        interval, sum their `acuity` values"

        Two non-overlapping (back-to-back) acuity-4 appointments on a
        max_acuity_load=6 nurse do not aggregate (only overlapping ones sum), so
        the second succeeds despite 4+4>6.

        Design: Difficulty/resource_temporal_overlap/overlap_nurse_acuity_aggregate_capacity_rejected
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        chair_p = fx.create_chair(label="C-P-noagg")
        chair_q = fx.create_chair(label="C-Q-noagg")
        nurse = fx.create_nurse(full_name="Nnoagg", is_chemo_certified=True, max_acuity_load=6)
        cyc = env["cycle"]
        fx.book_appointment(cyc["id"], chair_p["id"], nurse["id"],
                            "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z", 4, cyc["version"])
        appt2 = validate_success(api_client.create_infusion_appointment(
            f.create_infusion_appointment_payload(
                cyc["id"], chair_q["id"], nurse["id"],
                "2026-07-01T10:00:00Z", "2026-07-01T11:00:00Z", 4, cyc["version"]),
            PHARM), 201)
        assert appt2["status"] == "SCHEDULED", (
            f"non-overlapping intervals must not aggregate, got {appt2['status']}")


class TestCompensatingInvariantSecond:
    def test_remaining_headroom_after_partial_administer_is_reusable(self):
        """PRD §3.8: "the linked authorization must be `APPROVED` and its remaining
        headroom — `authorized_units_mg` minus `consumed_units_mg` — must be at
        least the order's `ordered_dose_mg`"

        After administering 525 against an authorized-600 PA, the remaining 75 is
        reflected as consumed 525 with the PA still APPROVED (headroom unspent
        beyond the order dose).

        Design: Difficulty/compensating_invariant/invariant_pa_units_conserved_on_administer
        """
        env = fx.setup_verified_order_with_pa(authorized_units_mg=600)
        validate_success(api_client.administer_drug_order(
            env["order"]["id"], make_nurse_headers(env["nb"]["id"])), 200)
        pa = validate_success(api_client.get_prior_authorization(env["pa"]["id"], PHARM), 200)
        assert pa["consumed_units_mg"] == 525
        assert pa["status"] == "APPROVED"
        assert pa["authorized_units_mg"] - pa["consumed_units_mg"] == 75

    def test_rebooked_appointment_after_release_is_usable(self):
        """PRD §3.10: "Once booked, a `Nurse` checks the patient in, advancing the
        appointment from `SCHEDULED` to `CHECKED_IN`; check-in requires the
        appointment to be `SCHEDULED` ... and the parent cycle to be `ACTIVE`"

        The appointment re-booked on the released 09:00-10:30 interval is a fully
        live SCHEDULED appointment — it can be checked in, proving the interval
        was genuinely freed and reusable.

        Design: Difficulty/compensating_invariant/invariant_chair_minutes_released_on_hold_cancel
        """
        env = fx.setup_active_cycle_with_chair_and_nurse(item_overrides=dict(FLAT_CHEMO))
        cyc = env["cycle"]
        nurse_h = make_nurse_headers(env["nurse"]["id"])
        fx.book_appointment(cyc["id"], env["chair"]["id"], env["nurse"]["id"],
                            "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, cyc["version"])
        validate_success(api_client.hold_treatment_cycle(cyc["id"], PHARM), 200)
        resumed = validate_success(api_client.resume_treatment_cycle(cyc["id"], PHARM), 200)
        appt2 = validate_success(api_client.create_infusion_appointment(
            f.create_infusion_appointment_payload(
                cyc["id"], env["chair"]["id"], env["nurse"]["id"],
                "2026-07-01T09:00:00Z", "2026-07-01T10:30:00Z", 2, resumed["version"]),
            PHARM), 201)
        checked = validate_success(api_client.check_in_infusion_appointment(appt2["id"], nurse_h), 200)
        assert checked["status"] == "CHECKED_IN"
