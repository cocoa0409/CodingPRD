"""Assay verdicts at the boundary, the re-treat/scrap/reject branches,
optimistic concurrency on order-retreat, and warranty voiding cascades
(PRD §2.7, §2.10, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_version_incremented,
    assay_threshold_bounds,
    book_treatment_slot,
    create_assay_payload,
    create_cycle_payload,
    create_warranty_payload,
    drive_inspection_to_findings,
    force_charge_state,
    get_charge,
    get_cylinder,
    get_plant,
    list_pieces,
    record_assay_for_outcome,
    setup_assayed_charge,
    setup_cycle_complete_charge,
    setup_inspection,
    setup_released_charge,
    setup_shop,
    validate_error,
    validate_paginated,
    validate_success,
)

OP = TEST_USERS["plant_operator_headers"]
LAB = TEST_USERS["lab_technician_headers"]
QM = TEST_USERS["quality_manager_headers"]


class TestAssayBoundary:
    def test_retention_assay_exact_target_passes_boundary(self, api):
        """PRD §3.7: "The assay's `pass_threshold_pcf` is ninety percent of
        the charge's `target_retention_pcf`."
        PRD §3.7: "The boundaries are inclusive at both ends — a mean exactly
        equal to the target is a `PASS`, provided the minimum sample also
        meets the threshold."

        Design: Difficulty/boundary_precision_check/retention_assay_exact_target_passes_boundary
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        charge, cycle = setup_cycle_complete_charge(shop, use_category="UC3B")

        target = charge["target_retention_pcf"]
        _lo, hi = assay_threshold_bounds(target)
        # mean exactly at target, min sample exactly at the pass threshold.
        resp = api.record_assay(
            plant_id, charge["id"],
            create_assay_payload(cycle["id"], target, hi), LAB)
        assay = validate_success(resp, 201)
        assert assay["outcome"] == "PASS"
        assert get_charge(plant_id, charge["id"])["status"] == "ASSAYED_PASS"

    def test_retention_assay_just_below_target_is_fail_marginal(self, api):
        """PRD §3.7: "it is `FAIL_MARGINAL` when `mean_retention_pcf` is at
        least `pass_threshold_pcf` yet still below `target_retention_pcf`
        while `min_sample_retention_pcf` falls below `pass_threshold_pcf`".
        PRD §3.7: "Recording the assay moves the charge: `CYCLE_COMPLETE` to
        `ASSAYED_PASS` on a `PASS`, or to `ASSAYED_FAIL` on either failing
        verdict".

        Design: Difficulty/boundary_precision_check/retention_assay_exact_target_passes_boundary
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        charge, cycle = setup_cycle_complete_charge(shop, use_category="UC3B")

        target = float(charge["target_retention_pcf"])
        lo, _hi = assay_threshold_bounds(target)
        mean = float(f"{target - 0.001:.3f}")          # >= threshold, < target
        min_sample = float(f"{lo - 0.001:.3f}")        # below threshold
        resp = api.record_assay(
            plant_id, charge["id"],
            create_assay_payload(cycle["id"], mean, min_sample), LAB)
        assay = validate_success(resp, 201)
        assert assay["outcome"] == "FAIL_MARGINAL"
        assert get_charge(plant_id, charge["id"])["status"] == "ASSAYED_FAIL"


class TestChargeFailBranches:
    def test_retreat_branch_returns_charge_to_cylinder_with_next_cycle_number(self, api):
        """PRD §3.7: "Ordering the re-treat moves the charge to
        `RE_TREAT_PENDING`, voids every `ACTIVE` WarrantyRegistration on the
        charge — each moves to `VOIDED_BY_RETREAT` — and increments the
        charge's `version` by 1."
        PRD §3.7: "To run the re-treat, a `TREATMENT` slot for it must exist,
        and scheduling the new cycle returns the charge from
        `RE_TREAT_PENDING` to `IN_CYLINDER` with a `cycle_number` one greater
        than the cycle before."

        Design: Difficulty/non_linear_state_machine/charge_branching_assayed_fail_to_retreat_or_scrap_or_reject
        """
        shop = setup_shop()
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]
        charge, cycle, assay = setup_assayed_charge(shop, outcome="FAIL_MARGINAL")
        assert charge["status"] == "ASSAYED_FAIL"

        ordered = validate_success(
            api.order_retreat(plant_id, charge["id"],
                              {"expected_charge_version": charge["version"]}, QM))
        assert ordered["status"] == "RE_TREAT_PENDING"
        assert_version_incremented(ordered["version"], charge["version"])

        # PRD §3.7: "To run the re-treat, a `TREATMENT` slot for it must
        # exist". Book a slot whose charge_id references the now
        # RE_TREAT_PENDING charge (a booking shape PRD §3.2 explicitly
        # permits). The original load slot still occupies the cylinder
        # through 2026-08-12 plus its buffer, so the re-treat slot is booked
        # past that slot's effective end to stay clear of the overlap rule.
        book_treatment_slot(
            plant_id, cyl_id,
            charge_id=charge["id"],
            slot_start="2026-08-13T06:00:00Z",
            slot_end="2026-08-14T06:00:00Z",
        )

        # The cylinder must be cleaned before the re-treat cycle runs.
        validate_success(api.mark_cleaned(plant_id, cyl_id, OP))
        cycle2 = validate_success(
            api.create_cycle(plant_id, cyl_id,
                             create_cycle_payload(shop["preservative"]["id"]), OP), 201)
        assert cycle2["cycle_number"] == 2
        assert get_charge(plant_id, charge["id"])["status"] == "IN_CYLINDER"

    def test_scrap_branch_posts_liability_and_scraps_pieces(self, api):
        """PRD §3.7: "When a charge's last assay was `FAIL_GROSS`, or the
        re-treat allowance is exhausted because `cycle_number` has reached 3,
        a `QualityManager` scraps the charge: it moves to `SCRAPPED`, its
        `ASSAYED_FAIL` pieces move to `SCRAPPED` with it, its `volume_mbf`
        times seventy-five thousand cents per mbf (a $750-per-mbf disposal
        cost) is added to the plant's `hazardous_waste_liability_cents`, and
        the plant's `compliance_score` drops by 100, clamped at zero."

        Design: Difficulty/non_linear_state_machine/charge_branching_assayed_fail_to_retreat_or_scrap_or_reject
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        charge, cycle, assay = setup_assayed_charge(shop, outcome="FAIL_GROSS", volume_mbf=5.0)
        assert assay["outcome"] == "FAIL_GROSS"

        force_charge_state(charge["id"], "RE_TREAT_PENDING")
        scrapped = validate_success(api.scrap_charge(plant_id, charge["id"], QM))
        assert scrapped["status"] == "SCRAPPED"

        plant = get_plant(plant_id)
        assert plant["hazardous_waste_liability_cents"] == 5.0 * 75000
        assert plant["compliance_score"] == 1000 - 100
        for piece in list_pieces(plant_id, charge["id"]):
            assert piece["status"] == "SCRAPPED"

    def test_reject_branch_on_critical_finding(self, api):
        """PRD §3.7: "Separately, from `CYCLE_COMPLETE`, a `QualityManager`
        may reject a charge outright when a `CRITICAL` finding from an agency
        inspection cites it; rejection moves the charge to `REJECTED`, and
        the cylinder still holding it moves to `NEEDS_CLEANING`."

        Design: Difficulty/non_linear_state_machine/charge_branching_assayed_fail_to_retreat_or_scrap_or_reject
        """
        shop = setup_shop()
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]
        charge, _cycle = setup_cycle_complete_charge(shop)

        inspection = setup_inspection(plant_id, charges_in_scope=[charge["id"]],
                                      severity="CRITICAL")
        drive_inspection_to_findings(plant_id, inspection["id"], severity="CRITICAL")

        rejected = validate_success(api.reject_charge(plant_id, charge["id"], QM))
        assert rejected["status"] == "REJECTED"
        assert get_cylinder(plant_id, cyl_id)["status"] == "NEEDS_CLEANING"


class TestRetreatEligibility:
    def test_retreat_not_permitted_on_fail_gross(self, api):
        """PRD §3.7: "only when the last assay's `outcome` was `FAIL_MARGINAL`
        — a `FAIL_GROSS` charge may not be re-treated and must be scrapped —
        and only while the charge's `cycle_number` is still below 3; violating
        the eligibility rule is rejected with `ERR_RETREAT_NOT_PERMITTED`
        (422)."

        Design: Corner/validations/retreat_not_permitted_on_fail_gross
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        charge, _cycle, assay = setup_assayed_charge(shop, outcome="FAIL_GROSS")
        assert assay["outcome"] == "FAIL_GROSS"

        resp = api.order_retreat(
            plant_id, charge["id"],
            {"expected_charge_version": charge["version"]}, QM)
        validate_error(resp, ApiErrorId.ERR_RETREAT_NOT_PERMITTED.value)

    def test_stale_version_occ_conflict(self, api):
        """PRD §2.7: "A request to
        `POST /treatment-plants/{plantId}/charges/{chargeId}/order-retreat`
        must include `expected_charge_version`, a non-optional field carrying
        the `version` of the charge as the `QualityManager` last observed it;
        if the charge's current `version` has advanced beyond that value, the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)".
        PRD §2.10: "the caller supplies `target_status`, the charge's `status`
        is set to that value, and the charge's `version` increments by 1."

        Design: Corner/validations/stale_version_occ_conflict
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        charge, _cycle, assay = setup_assayed_charge(shop, outcome="FAIL_MARGINAL")
        assert assay["outcome"] == "FAIL_MARGINAL"

        stale_version = charge["version"]
        # Another write (force-state to the same state) advances the version.
        bumped = force_charge_state(charge["id"], "ASSAYED_FAIL")
        assert_version_incremented(bumped["version"], stale_version)

        resp = api.order_retreat(
            plant_id, charge["id"], {"expected_charge_version": stale_version}, QM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


class TestRetreatVoidsWarranties:
    def test_retreat_order_voids_active_warranty(self, api):
        """PRD §3.7: "Ordering the re-treat moves the charge to
        `RE_TREAT_PENDING`, voids every `ACTIVE` WarrantyRegistration on the
        charge — each moves to `VOIDED_BY_RETREAT` — and increments the
        charge's `version` by 1."
        PRD §2.10: "the caller supplies `target_status`, the charge's `status`
        is set to that value, and the charge's `version` increments by 1."

        Design: Difficulty/transitive_cascade/retreat_order_cascades_voids_warranties_then_bubbles_version
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        warranty, released = setup_released_charge(shop, warranty_term_years=25)
        assert warranty["status"] == "ACTIVE"
        assert released["status"] == "RELEASED"

        # Force the charge back through CYCLE_COMPLETE and record a
        # FAIL_MARGINAL assay so a re-treat is eligible.
        force_charge_state(released["id"], "CYCLE_COMPLETE")
        # The original cycle belongs to this charge and is a valid assay ref.
        cycles, _meta = validate_paginated(
            api_client.list_cycles(plant_id, released["cylinder_id"], OP))
        cycle_id = cycles[0]["id"]
        assay = record_assay_for_outcome(plant_id, released["id"], cycle_id, "FAIL_MARGINAL")
        assert assay["outcome"] == "FAIL_MARGINAL"

        current = get_charge(plant_id, released["id"])
        ordered = validate_success(
            api.order_retreat(plant_id, released["id"],
                              {"expected_charge_version": current["version"]}, QM))
        assert ordered["status"] == "RE_TREAT_PENDING"
        assert_version_incremented(ordered["version"], current["version"])

        fetched = validate_success(
            api.get_warranty(plant_id, released["id"], warranty["id"], QM))
        assert fetched["status"] == "VOIDED_BY_RETREAT"

    def test_retreat_order_voids_every_active_warranty(self, api):
        """PRD §3.7: "Ordering the re-treat ... voids every `ACTIVE`
        WarrantyRegistration on the charge — each moves to
        `VOIDED_BY_RETREAT`".

        Design: Difficulty/transitive_cascade/retreat_order_cascades_voids_warranties_then_bubbles_version
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        warranty1, released = setup_released_charge(shop, warranty_term_years=25)

        # Force back to TAGGED and register a second ACTIVE warranty.
        forced = force_charge_state(released["id"], "TAGGED")
        warranty2 = validate_success(
            api.register_warranty(plant_id, released["id"],
                                  create_warranty_payload(forced["version"],
                                                          warranty_term_years=5), OP), 201)
        assert warranty2["status"] == "ACTIVE"

        # Drive to an eligible re-treat state.
        force_charge_state(released["id"], "CYCLE_COMPLETE")
        cycles, _meta = validate_paginated(
            api_client.list_cycles(plant_id, released["cylinder_id"], OP))
        assay = record_assay_for_outcome(plant_id, released["id"], cycles[0]["id"],
                                         "FAIL_MARGINAL")
        assert assay["outcome"] == "FAIL_MARGINAL"

        current = get_charge(plant_id, released["id"])
        ordered = validate_success(
            api.order_retreat(plant_id, released["id"],
                              {"expected_charge_version": current["version"]}, QM))
        assert ordered["status"] == "RE_TREAT_PENDING"

        for wid in (warranty1["id"], warranty2["id"]):
            fetched = validate_success(api.get_warranty(plant_id, released["id"], wid, QM))
            assert fetched["status"] == "VOIDED_BY_RETREAT"


class TestSegregationOfDuties:
    def test_segregation_of_duties_assay_vs_quality_decision(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403)."
        PRD §4: "Record a retention assay on a charge" is authorized for
        LabTechnician only, and "Order a re-treat for an ASSAYED_FAIL charge"
        is authorized for QualityManager only.

        Design: Corner/rbac/segregation_of_duties_assay_vs_quality_decision
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        charge, cycle, assay = setup_assayed_charge(shop, outcome="FAIL_MARGINAL")

        # LabTechnician may record assays but may not order a re-treat.
        resp = api.order_retreat(
            plant_id, charge["id"],
            {"expected_charge_version": charge["version"]}, LAB)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

        # QualityManager may order re-treats but may not record assays.
        resp = api.record_assay(
            plant_id, charge["id"],
            create_assay_payload(cycle["id"], 0.5, 0.45,
                                 recorded_at="2026-08-10T19:00:00Z"), QM)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
