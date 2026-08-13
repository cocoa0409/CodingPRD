"""Waste manifest lifecycle (net weight, frozen per-manifest fees, seal /
ship / deliver / confirm / reject / void), facility gates and suspension
cascade, and the project money calculations (estimated vs final disposal
cost, pinned rounding order, cost rollup)."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_manifest,
    assert_project_cost_rollup_consistent,
    create_confirmed_manifest,
    create_facility_entity,
    create_manifest_entity,
    create_manifest_payload,
    create_relocation_unit_payload,
    create_sealed_manifest,
    create_shipped_manifest,
    deliver_manifest,
    get_facility,
    get_project,
    list_project_manifests,
    make_facility_operator_headers,
    make_supervisor_headers,
    seal_manifest,
    setup_in_progress_project,
    setup_in_progress_with_facility,
    ship_manifest,
    validate_error,
    validate_success,
    void_manifest,
)


class TestManifestCreation:
    def test_nonpositive_net_weight_rejected(self):
        """PRD section 3.7: "At creation the server computes the net weight:
        `net_weight_lbs` is the gross weight minus a tare of 2 pounds per bag,
        at 2 decimal places, and if that net weight is not strictly positive
        the manifest is rejected with `ERR_MANIFEST_WEIGHT_INVALID` (422)."

        Design: Corner/validations/create_manifest_nonpositive_net_weight_rejected
        """
        ctx = setup_in_progress_with_facility(name="P-V6")
        # gross 4 lbs with 3 bags -> net 4 - 3*2 = -2 lbs.
        resp = api_client.create_manifest(
            create_manifest_payload(
                ctx["project"]["id"], ctx["facility"]["id"],
                bags_count=3, gross_weight_lbs=4),
            make_supervisor_headers(ctx["supervisor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MANIFEST_WEIGHT_INVALID)


class TestEstimatedVsFinalDisposalCost:
    def test_estimated_density_variant_vs_final_manifested_variant(self):
        """PRD section 3.7: "The **estimated** disposal cost, computed at
        survey finalization (§3.2), assumes a debris density of one and
        a half pounds per square foot: the estimated tonnage is
        `total_acm_sq_ft` multiplied by 1.5 and divided by 2,000, the same
        two-tier rate applies — 15,000 cents per ton at or below 10 tons,
        12,500 cents per ton above — and the product is rounded half up to
        whole cents to become `estimated_disposal_cost_cents`."
        PRD section 2.7: "A project similarly carries
        `estimated_disposal_cost_cents`, a survey-derived figure computed
        under a standard density assumption before any waste exists, alongside
        `final_disposal_cost_cents`, the sum of actual frozen manifest fees as
        disposal is confirmed."

        Design: Difficulty/dual_variant_calc/disposal_cost_estimated_survey_vs_final_manifested
        """
        ctx = setup_in_progress_with_facility(name="P-DV2")
        # 100 sqft -> 100 * 1.5 / 2000 = 0.075 t (tier 1) -> 1125 cents.
        project = get_project(ctx["project"]["id"])
        assert project["estimated_disposal_cost_cents"] == 1125, (
            f"survey-derived estimate: expected 1125, got "
            f"{project['estimated_disposal_cost_cents']}"
        )
        # net 2003 - 2 = 2001 lbs = 1.0005 t -> fee round_half_up(15007.5).
        manifest = create_confirmed_manifest(ctx, bags_count=1,
                                             gross_weight_lbs=2003)
        assert manifest["fee_cents"] == 15008
        project = get_project(ctx["project"]["id"])
        assert project["estimated_disposal_cost_cents"] == 1125, \
            "the estimated variant must remain visible after confirmation"
        assert project["final_disposal_cost_cents"] == 15008, (
            f"final variant sums frozen fees: expected 15008, got "
            f"{project['final_disposal_cost_cents']}"
        )
        assert project["estimated_disposal_cost_cents"] != \
            project["final_disposal_cost_cents"], \
            "the variants must diverge when reality departs from assumption"

    def test_rollup_computed_from_final_variant(self):
        """PRD section 3.7: "first the subtotal is `base_abatement_cost_cents`
        plus `final_disposal_cost_cents`; then `insurance_surcharge_cents` is
        8 percent of that pre-surcharge subtotal, rounded half up to whole
        cents — the surcharge never compounds on itself and there is no
        iteration; finally `total_project_cost_cents` is the subtotal plus the
        surcharge."

        Design: Difficulty/dual_variant_calc/disposal_cost_estimated_survey_vs_final_manifested
        """
        ctx = setup_in_progress_with_facility(name="P-DV2B")
        create_confirmed_manifest(ctx, bags_count=1, gross_weight_lbs=2003)
        project = get_project(ctx["project"]["id"])
        assert project["final_disposal_cost_cents"] == 15008
        # subtotal 5_015_008; surcharge round_half_up(401_200.64) = 401_201.
        assert project["insurance_surcharge_cents"] == 401_201
        assert project["total_project_cost_cents"] == 5_416_209
        assert_project_cost_rollup_consistent(project)


class TestManifestFeeRounding:
    def test_fee_rounded_per_manifest_at_seal(self):
        """PRD section 3.7: "The frozen `fee_cents` uses two-tier pricing:
        when the manifest's own `net_tons` is at most 10 tons the rate is
        15,000 cents per ton, and above 10 tons the rate is 12,500 cents per
        ton; the fee is the manifest's `net_tons` multiplied by its tier rate,
        rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/manifest_fee_per_manifest_rounding_then_sum
        """
        ctx = setup_in_progress_with_facility(name="P-CF2")
        m1 = create_sealed_manifest(ctx, bags_count=1, gross_weight_lbs=2003)
        m2 = create_sealed_manifest(ctx, bags_count=1, gross_weight_lbs=2003)
        assert_manifest(m1)
        assert_manifest(m2)
        assert m1["fee_cents"] == 15008, (
            f"1.0005 t x 15000 = 15007.5 -> round half up 15008, "
            f"got {m1['fee_cents']}"
        )
        assert m2["fee_cents"] == 15008, \
            "each manifest's fee is rounded individually at seal time"

    def test_project_total_sums_rounded_fees(self):
        """PRD section 3.7: "The rounding order is pinned: each manifest's fee
        is rounded individually at seal time, and the project's
        `final_disposal_cost_cents` is the sum of those already-rounded
        `fee_cents` over manifests in `CONFIRMED` status only — summing
        unrounded fees and rounding once at the project level is forbidden
        because it produces different cents."

        Design: Difficulty/combinatorial_formula/manifest_fee_per_manifest_rounding_then_sum
        """
        ctx = setup_in_progress_with_facility(name="P-CF2B")
        create_confirmed_manifest(ctx, bags_count=1, gross_weight_lbs=2003)
        create_confirmed_manifest(ctx, bags_count=1, gross_weight_lbs=2003)
        project = get_project(ctx["project"]["id"])
        assert project["final_disposal_cost_cents"] == 30016, (
            f"sum of already-rounded fees 15008 + 15008 = 30016 (NOT the "
            f"forbidden round-of-sum 30015), got "
            f"{project['final_disposal_cost_cents']}"
        )


class TestProjectCostRollup:
    def test_surcharge_is_eight_percent_of_pre_surcharge_subtotal(self):
        """PRD section 3.7: "The **project cost rollup** then runs in a pinned
        evaluation order whenever the base or disposal figures change: first
        the subtotal is `base_abatement_cost_cents` plus
        `final_disposal_cost_cents`; then `insurance_surcharge_cents` is 8
        percent of that pre-surcharge subtotal, rounded half up to whole cents
        — the surcharge never compounds on itself and there is no iteration;
        finally `total_project_cost_cents` is the subtotal plus the
        surcharge."

        Design: Difficulty/combinatorial_formula/project_cost_rollup_surcharge_on_pre_surcharge_subtotal
        """
        ctx = setup_in_progress_with_facility(name="P-CF3")
        create_confirmed_manifest(ctx, bags_count=1, gross_weight_lbs=2003)
        create_confirmed_manifest(ctx, bags_count=1, gross_weight_lbs=2003)
        project = get_project(ctx["project"]["id"])
        assert project["final_disposal_cost_cents"] == 30016
        # subtotal = 5_000_000 + 30_016 = 5_030_016;
        # surcharge = round_half_up(5_030_016 * 0.08) = round_half_up(402_401.28).
        assert project["insurance_surcharge_cents"] == 402_401, (
            f"8% of the pre-surcharge subtotal only: expected 402401, "
            f"got {project['insurance_surcharge_cents']}"
        )

    def test_total_is_subtotal_plus_surcharge(self):
        """PRD section 3.7: "finally `total_project_cost_cents` is the
        subtotal plus the surcharge."
        PRD section 3.7: "the surcharge never compounds on itself and there is
        no iteration"

        Design: Difficulty/combinatorial_formula/project_cost_rollup_surcharge_on_pre_surcharge_subtotal
        """
        ctx = setup_in_progress_with_facility(name="P-CF3B")
        create_confirmed_manifest(ctx, bags_count=1, gross_weight_lbs=2003)
        create_confirmed_manifest(ctx, bags_count=1, gross_weight_lbs=2003)
        project = get_project(ctx["project"]["id"])
        assert project["total_project_cost_cents"] == 5_432_417, (
            f"5_030_016 + 402_401 = 5_432_417, got "
            f"{project['total_project_cost_cents']}"
        )
        assert_project_cost_rollup_consistent(project)


class TestManifestedWeightInvariant:
    def test_seal_counts_and_draft_excluded(self):
        """PRD section 3.7: "Sealing also stamps `sealed_by_user_id` with the
        supervisor's `X-User-ID` and recomputes the project's
        `manifested_weight_lbs`, which is always the sum of `net_weight_lbs`
        over the project's manifests in `SEALED`, `IN_TRANSIT`, `DELIVERED`,
        or `CONFIRMED` status."

        Design: Difficulty/compensating_invariant/manifest_create_void_conserves_manifested_weight
        """
        ctx = setup_in_progress_with_facility(name="P-INV1")
        m1 = create_sealed_manifest(ctx, bags_count=2, gross_weight_lbs=100)
        assert m1["net_weight_lbs"] == 96, "100 - 2 bags x 2 lbs = 96"
        assert m1["fee_cents"] == 720, "0.048 t x 15000 = 720"
        project = get_project(ctx["project"]["id"])
        assert project["manifested_weight_lbs"] == 96
        # A DRAFT manifest (net 48 lbs) is outside the aggregation set.
        create_manifest_entity(ctx["project"]["id"], ctx["facility"]["id"],
                               ctx["supervisor"]["id"], bags_count=1,
                               gross_weight_lbs=50)
        project = get_project(ctx["project"]["id"])
        assert project["manifested_weight_lbs"] == 96, \
            "DRAFT manifests must not enter the manifested-weight aggregate"

    def test_void_restores_manifested_weight(self):
        """PRD section 3.7: "A manifest in `DRAFT` or `REJECTED` may also be
        **voided** by a `Supervisor` or `ContractorAdmin`, moving it to
        `VOIDED` and recomputing the project's `manifested_weight_lbs` with
        voided manifests excluded from the aggregation."

        Design: Difficulty/compensating_invariant/manifest_create_void_conserves_manifested_weight
        """
        ctx = setup_in_progress_with_facility(name="P-INV1B")
        create_sealed_manifest(ctx, bags_count=2, gross_weight_lbs=100)
        draft = create_manifest_entity(ctx["project"]["id"],
                                       ctx["facility"]["id"],
                                       ctx["supervisor"]["id"], bags_count=1,
                                       gross_weight_lbs=50)
        void_manifest(draft["id"])
        project = get_project(ctx["project"]["id"])
        assert project["manifested_weight_lbs"] == 96, (
            f"create+void must conserve manifested weight at 96, got "
            f"{project['manifested_weight_lbs']}"
        )


class TestFacilityGates:
    def test_deliver_to_suspended_facility_rejected(self):
        """PRD section 3.7: "Delivery is the facility's affair: a
        `FacilityOperator` records delivery, moving the manifest from
        `IN_TRANSIT` to `DELIVERED`, and the gate evaluates four conditions in
        order — the operator's `X-User-ID` must equal the manifest's
        `facility_id` (`ERR_FACILITY_MISMATCH`, 403); the facility must be
        `APPROVED` (`ERR_FACILITY_NOT_APPROVED`, 409)"

        Design: Corner/validations/deliver_to_suspended_facility_rejected
        """
        ctx = setup_in_progress_project(name="P-V7")
        facility = create_facility_entity(name="Fac S", epa_id="EPA-S")
        validate_success(api_client.suspend_facility(facility["id"], ADMIN))
        manifest = create_manifest_entity(
            ctx["project"]["id"], facility["id"], ctx["supervisor"]["id"],
            bags_count=2, gross_weight_lbs=100)
        seal_manifest(manifest["id"], ctx["supervisor"]["id"])
        ship_manifest(manifest["id"], ctx["supervisor"]["id"])
        resp = api_client.deliver_manifest(
            manifest["id"], make_facility_operator_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_APPROVED)

    def test_deliver_hazard_mismatch_rejected(self):
        """PRD section 3.7: "the facility's `accepted_hazards` must cover the
        project's `hazard_class`, where a `MIXED` project requires both
        `ASBESTOS` and `LEAD` to be present and any other class requires that
        class itself (`ERR_FACILITY_HAZARD_MISMATCH`, 422)"

        Design: Corner/validations/deliver_hazard_mismatch_rejected
        """
        ctx = setup_in_progress_with_facility(
            name="P-V8", hazard_class="LEAD", sample_qty=80, friable=False)
        manifest = create_shipped_manifest(ctx, bags_count=2,
                                           gross_weight_lbs=100)
        resp = api_client.deliver_manifest(
            manifest["id"],
            make_facility_operator_headers(ctx["facility"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FACILITY_HAZARD_MISMATCH)

    def test_deliver_manifest_wrong_facility_forbidden(self):
        """PRD section 2.1: "When `X-User-Role` is `FacilityOperator`,
        `X-User-ID` is the `id` of the acting `DisposalFacility`; delivery,
        confirmation, and rejection of a manifest require `X-User-ID` to equal
        the manifest's `facility_id`, failing with `ERR_FACILITY_MISMATCH`
        (HTTP 403) otherwise."

        Design: Corner/endpoints/deliver_manifest_wrong_facility_forbidden
        """
        ctx = setup_in_progress_with_facility(name="P-E3")
        other = create_facility_entity(name="Fac 2", epa_id="EPA-2")
        manifest = create_shipped_manifest(ctx, bags_count=2,
                                           gross_weight_lbs=100)
        resp = api_client.deliver_manifest(
            manifest["id"], make_facility_operator_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FACILITY_MISMATCH)
        listing = list_project_manifests(ctx["project"]["id"])
        mine = [m for m in listing if m["id"] == manifest["id"]]
        assert mine and mine[0]["status"] == "IN_TRANSIT", \
            "a rejected delivery must leave the manifest IN_TRANSIT"

    def test_monthly_capacity_exact_fit_then_overflow(self):
        """PRD section 3.7: "the facility's `delivered_tons_current_month`
        plus the manifest's `net_tons` must not exceed
        `monthly_capacity_tons`, with equality allowed
        (`ERR_FACILITY_CAPACITY_EXCEEDED`, 422)."
        PRD section 3.7: "That monthly figure is the sum of `net_tons` over
        the facility's manifests in `DELIVERED` or `CONFIRMED` status whose
        `delivered_at` falls within the current UTC calendar month — from the
        first instant of the month, inclusive, to the first instant of the
        next month, exclusive — carried at 4 decimal places, rounded half up."

        Design: Corner/calculations/facility_monthly_capacity_exact_fit_then_overflow
        """
        ctx = setup_in_progress_with_facility(name="P-C5", capacity_tons=2.0)
        # M1 net 2001 lbs = 1.0005 t; M2 net 1999 lbs = 0.9995 t; M3 net 2 lbs
        # = 0.001 t.
        m1 = create_shipped_manifest(ctx, bags_count=1, gross_weight_lbs=2003)
        m2 = create_shipped_manifest(ctx, bags_count=1, gross_weight_lbs=2001)
        m3 = create_shipped_manifest(ctx, bags_count=1, gross_weight_lbs=4)
        deliver_manifest(m1["id"], ctx["facility"]["id"])
        delivered = deliver_manifest(m2["id"], ctx["facility"]["id"])
        assert delivered["status"] == "DELIVERED", \
            "cumulative 2.0000 t equals capacity: equality is allowed"
        facility = get_facility(ctx["facility"]["id"])
        assert facility["delivered_tons_current_month"] == pytest.approx(2.0), (
            f"1.0005 + 0.9995 = 2.0000 t delivered, got "
            f"{facility['delivered_tons_current_month']}"
        )
        resp = api_client.deliver_manifest(
            m3["id"], make_facility_operator_headers(ctx["facility"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED)


class TestFacilitySuspendCascade:
    def test_suspend_rejects_in_transit_manifests(self):
        """PRD section 3.7: "A `ContractorAdmin` moves a facility from
        `APPROVED` to `SUSPENDED`, and the suspension cascades: every manifest
        addressed to that facility still `IN_TRANSIT` transitions to
        `REJECTED` with its `reject_reason` set to the literal
        `FACILITY_SUSPENDED`, and for each affected manifest the owning
        project's `manifested_weight_lbs` and the facility's
        `delivered_tons_current_month` are recomputed."

        Design: Corner/state_machines/facility_suspend_rejects_in_transit_manifests
        """
        ctx = setup_in_progress_with_facility(name="P-SM10")
        manifest = create_shipped_manifest(ctx, bags_count=2,
                                           gross_weight_lbs=100)
        project = get_project(ctx["project"]["id"])
        assert project["manifested_weight_lbs"] == 96
        facility = validate_success(
            api_client.suspend_facility(ctx["facility"]["id"], ADMIN))
        assert facility["status"] == "SUSPENDED"
        listing = list_project_manifests(ctx["project"]["id"])
        mine = [m for m in listing if m["id"] == manifest["id"]]
        assert mine and mine[0]["status"] == "REJECTED", \
            "the IN_TRANSIT manifest must be rejected by the cascade"
        assert mine[0]["reject_reason"] == "FACILITY_SUSPENDED"
        project = get_project(ctx["project"]["id"])
        assert project["manifested_weight_lbs"] == 0, \
            "REJECTED leaves the aggregation set: manifested weight drops to 0"


class TestCompleteWorkGate:
    def test_complete_work_with_draft_manifest_rejected(self):
        """PRD section 3.6: "a `Supervisor` completes the work phase, moving
        the project from `IN_PROGRESS` to `AWAITING_CLEARANCE`, only when no
        manifest of the project remains in `DRAFT` — unsealed manifests mean
        unaccounted waste and the transition fails with
        `ERR_MANIFESTS_OUTSTANDING`."

        Design: Corner/validations/complete_work_with_draft_manifest_rejected
        """
        ctx = setup_in_progress_with_facility(name="P-V11")
        create_manifest_entity(ctx["project"]["id"], ctx["facility"]["id"],
                               ctx["supervisor"]["id"], bags_count=2,
                               gross_weight_lbs=100)
        resp = api_client.complete_work(
            ctx["project"]["id"],
            make_supervisor_headers(ctx["supervisor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MANIFESTS_OUTSTANDING)
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "IN_PROGRESS", \
            "a rejected complete-work must leave the project IN_PROGRESS"


class TestRelocationUnitRbac:
    def test_facility_operator_cannot_create_relocation_unit(self):
        """PRD section 2.1: "`ContractorAdmin` — the abatement contractor's
        office administrator. Owns projects, worker registration and
        recertification, regulatory filings, facility registration and
        suspension, relocation units and records, project start and closeout,
        and the logical clock."
        PRD section 2.1: "Beyond authentication, each endpoint restricts which
        roles may call it; a call from a role outside the permitted set is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/facility_operator_cannot_create_relocation_unit
        """
        facility = create_facility_entity()
        resp = api_client.create_relocation_unit(
            create_relocation_unit_payload(unit_label="U-X",
                                           capacity_persons=2),
            make_facility_operator_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
