"""Waste manifests: profile gates, capacity ledger, variance branch,
reconciliation, and facility reservation invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_facility_and_approved_profile,
    create_issued_manifest,
    create_job_in_progress,
    create_manifest,
    create_waste_profile_payload,
    get_success_data,
    validate_error,
)

PM = TEST_USERS["project_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
EA = TEST_USERS["environmental_approver_headers"]


def _ctx_with_profile(api, profile_overrides=None, facility_overrides=None,
                      job_overrides=None):
    ctx = create_job_in_progress(job_overrides=job_overrides)
    facility, profile = create_facility_and_approved_profile(
        ctx["site"]["id"], profile_overrides, facility_overrides
    )
    ctx.update({"facility": facility, "profile": profile})
    return ctx


class TestEstimatedTonsPrecision:
    def test_estimated_tons_rounds_half_up_at_two_dp(self, api):
        """PRD §3.6: "computes `estimated_tons` as the shipped gallons multiplied
        by the profile's `density_lbs_per_gal` and divided by 2000, rounded half
        up to two decimal places."

        Design: Corner/calculations/estimated_tons_rounds_half_up_at_two_dp
        """
        ctx = _ctx_with_profile(
            api,
            profile_overrides={"density_lbs_per_gal": 8.345, "variance_basis": "WEIGHT"},
        )
        manifest = create_manifest(ctx["job"]["id"], ctx["profile"]["id"], gallons=2000)
        issued = get_success_data(api.issue_manifest(manifest["id"], PM))
        assert issued["estimated_tons"] == pytest.approx(8.35)


class TestManifestProfileGate:
    def test_issue_with_submitted_profile_rejected(self, api):
        """PRD §3.6: "Issuing (`DRAFT` → `ISSUED`) requires the profile to be
        `APPROVED` (`ERR_WASTE_PROFILE_NOT_APPROVED` otherwise)".

        Design: Difficulty/cross_entity_state_dependency/manifest_issue_requires_approved_profile
        """
        ctx = create_job_in_progress()
        from test_helpers import create_disposal_facility_payload
        facility = get_success_data(
            api.create_disposal_facility(
                create_disposal_facility_payload(), TEST_USERS["platform_admin_headers"]
            )
        )
        profile = get_success_data(
            api.create_waste_profile(
                create_waste_profile_payload(ctx["site"]["id"], facility["id"]), CO
            )
        )
        get_success_data(api.submit_waste_profile(profile["id"], CO))
        manifest = create_manifest(ctx["job"]["id"], profile["id"])
        resp = api.issue_manifest(manifest["id"], PM)
        validate_error(resp, ApiErrorId.ERR_WASTE_PROFILE_NOT_APPROVED.value)
        assert resp.status_code == 422

    def test_issue_with_approved_profile_reserves_capacity(self, api):
        """PRD §3.6: "Issuing (`DRAFT` → `ISSUED`) requires the profile to be
        `APPROVED` (`ERR_WASTE_PROFILE_NOT_APPROVED` otherwise) ... On success
        the reservation is added and the facility's `posture` recomputed."
        PRD §2.9: "Issuing a manifest adds its estimated tonnage".

        Design: Difficulty/cross_entity_state_dependency/manifest_issue_requires_approved_profile
        """
        ctx = _ctx_with_profile(api)
        manifest = create_manifest(ctx["job"]["id"], ctx["profile"]["id"], gallons=2500)
        issued = get_success_data(api.issue_manifest(manifest["id"], PM))
        assert issued["status"] == "ISSUED"
        assert issued["estimated_tons"] == pytest.approx(10.0)
        facility = get_success_data(api.get_disposal_facility(ctx["facility"]["id"], PM))
        assert facility["reserved_tons"] == pytest.approx(10.0)
        manifest_after = get_success_data(api.get_manifest(manifest["id"], PM))
        assert manifest_after["status"] == "ISSUED"
        assert facility["reserved_tons"] == pytest.approx(10.0)


class TestVarianceBoundary:
    def _setup_two_in_transit(self, api):
        ctx = _ctx_with_profile(
            api,
            profile_overrides={"density_lbs_per_gal": 8.0, "variance_basis": "WEIGHT"},
        )
        man_a = create_issued_manifest(ctx["job"]["id"], ctx["profile"]["id"], 2500)
        get_success_data(api.depart_manifest(man_a["id"], PM))
        man_b = create_issued_manifest(ctx["job"]["id"], ctx["profile"]["id"], 2500)
        get_success_data(api.depart_manifest(man_b["id"], PM))
        return ctx, man_a, man_b

    def test_variance_exactly_ten_pct_stays_received(self, api):
        """PRD §3.6: "An absolute `variance_pct` greater than 10.00 percent — in
        either direction — routes the manifest to `EXCEPTION`; a variance at or
        below 10.00 percent, equality included, routes it to `RECEIVED`."

        Design: Difficulty/boundary_precision_check/manifest_variance_exactly_ten_pct_stays_received
        """
        _, man_a, _ = self._setup_two_in_transit(api)
        received = get_success_data(
            api.receive_manifest(man_a["id"], {"received_tons": 11.0}, PM)
        )
        assert received["variance_pct"] == pytest.approx(10.0)
        assert received["status"] == "RECEIVED"

    def test_variance_just_over_ten_pct_lands_exception(self, api):
        """PRD §3.6: "An absolute `variance_pct` greater than 10.00 percent — in
        either direction — routes the manifest to `EXCEPTION`".

        Design: Difficulty/boundary_precision_check/manifest_variance_exactly_ten_pct_stays_received
        """
        _, _, man_b = self._setup_two_in_transit(api)
        received = get_success_data(
            api.receive_manifest(man_b["id"], {"received_tons": 11.01}, PM)
        )
        assert received["variance_pct"] == pytest.approx(10.1)
        assert received["status"] == "EXCEPTION"


class TestVarianceBasisVariants:
    def _setup_pair(self, api):
        from test_helpers import create_disposal_facility_payload
        ctx = create_job_in_progress()
        facility = get_success_data(
            api.create_disposal_facility(
                create_disposal_facility_payload(),
                TEST_USERS["platform_admin_headers"],
            )
        )
        prof_w = get_success_data(
            api.create_waste_profile(
                create_waste_profile_payload(
                    ctx["site"]["id"], facility["id"], density_lbs_per_gal=8.345,
                    variance_basis="WEIGHT",
                ),
                CO,
            )
        )
        get_success_data(api.submit_waste_profile(prof_w["id"], CO))
        get_success_data(api.approve_waste_profile(prof_w["id"], EA))
        prof_v = get_success_data(
            api.create_waste_profile(
                create_waste_profile_payload(
                    ctx["site"]["id"], facility["id"], density_lbs_per_gal=8.345,
                    variance_basis="VOLUME",
                ),
                CO,
            )
        )
        get_success_data(api.submit_waste_profile(prof_v["id"], CO))
        get_success_data(api.approve_waste_profile(prof_v["id"], EA))
        man_w = create_issued_manifest(ctx["job"]["id"], prof_w["id"], 2750)
        get_success_data(api.depart_manifest(man_w["id"], PM))
        man_v = create_issued_manifest(ctx["job"]["id"], prof_v["id"], 2750)
        get_success_data(api.depart_manifest(man_v["id"], PM))
        return man_w, man_v

    def test_weight_basis_variance_value(self, api):
        """PRD §3.6: "Under `WEIGHT`, the shipped estimate is converted to tons
        the same way as at issue — gallons times density divided by 2000,
        rounded half up to two decimal places — and the variance is the
        difference between `received_tons` and that shipped estimate, divided by
        the shipped estimate, expressed as a percentage rounded half up to two
        decimal places."

        Design: Difficulty/dual_variant_calc/manifest_variance_weight_vs_volume_basis
        """
        man_w, _ = self._setup_pair(api)
        received = get_success_data(
            api.receive_manifest(man_w["id"], {"received_tons": 11.6}, PM)
        )
        assert received["variance_pct"] == pytest.approx(1.13)
        assert received["status"] == "RECEIVED"

    def test_volume_basis_variance_value_diverges(self, api):
        """PRD §3.6: "Under `VOLUME`, the received weight is converted to
        gallons instead — `received_tons` times 2000 divided by the density,
        rounded half up to one decimal place — and the variance is the
        difference between that received-gallons figure and `estimated_gallons`,
        divided by `estimated_gallons`, again expressed as a percentage rounded
        half up to two decimal places. The two bases round in a different order
        and can produce different percentages for identical weights and
        measures."

        Design: Difficulty/dual_variant_calc/manifest_variance_weight_vs_volume_basis
        """
        man_w, man_v = self._setup_pair(api)
        rec_w = get_success_data(
            api.receive_manifest(man_w["id"], {"received_tons": 11.6}, PM)
        )
        rec_v = get_success_data(
            api.receive_manifest(man_v["id"], {"received_tons": 11.6}, PM)
        )
        assert rec_v["variance_pct"] == pytest.approx(1.09)
        assert rec_v["status"] == "RECEIVED"
        assert rec_w["variance_pct"] != rec_v["variance_pct"]


class TestReconciliation:
    def test_reconcile_locks_billed_tons_and_charge(self, api):
        """PRD §3.6: "From `RECEIVED`, reconciling sets `billed_tons` to
        `received_tons`. ... Both paths then compute `disposal_charge_cents` as
        `billed_tons` multiplied by the profile's `disposal_rate_per_ton_cents`,
        rounded half up to whole cents."

        Design: Corner/calculations/reconcile_locks_billed_tons_and_disposal_charge
        """
        ctx = _ctx_with_profile(api)
        manifest = create_issued_manifest(ctx["job"]["id"], ctx["profile"]["id"], 2500)
        get_success_data(api.depart_manifest(manifest["id"], PM))
        get_success_data(api.receive_manifest(manifest["id"], {"received_tons": 11.0}, PM))
        reconciled = get_success_data(api.reconcile_manifest(manifest["id"], PM))
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["billed_tons"] == pytest.approx(11.0)
        assert reconciled["disposal_charge_cents"] == 385000

    def test_resolve_exception_with_adjusted_tons_repriced(self, api):
        """PRD §3.6: "From `EXCEPTION`, resolving requires a `resolution_note` —
        a missing note is rejected with `ERR_INVALID_REQUEST` — and sets
        `billed_tons` to `adjusted_tons` when the caller provides one, otherwise
        to `received_tons`."

        Design: Corner/calculations/resolve_exception_with_adjusted_tons_repriced
        """
        ctx = _ctx_with_profile(api)
        manifest = create_issued_manifest(ctx["job"]["id"], ctx["profile"]["id"], 2500)
        get_success_data(api.depart_manifest(manifest["id"], PM))
        received = get_success_data(
            api.receive_manifest(manifest["id"], {"received_tons": 11.5}, PM)
        )
        assert received["status"] == "EXCEPTION"
        resolved = get_success_data(
            api.resolve_manifest_exception(
                manifest["id"],
                {"resolution_note": "Scale ticket re-issued by facility; water content adjusted",
                 "adjusted_tons": 10.8},
                PM,
            )
        )
        assert resolved["status"] == "RECONCILED"
        assert resolved["billed_tons"] == pytest.approx(10.8)
        assert resolved["disposal_charge_cents"] == 378000


class TestFacilityCapacity:
    def test_manifest_over_capacity_rejected(self, api):
        """PRD §3.6: "the manifest's `estimated_tons` added to the facility's
        `reserved_tons` may not exceed `total_capacity_tons` — exactly reaching
        capacity is allowed — else the issue is rejected with
        `ERR_FACILITY_CAPACITY_EXCEEDED`."

        Design: Corner/validations/facility_capacity_rejects_manifest_over_capacity
        """
        ctx = _ctx_with_profile(
            api, facility_overrides={"total_capacity_tons": 50.0}
        )
        man_a = create_manifest(ctx["job"]["id"], ctx["profile"]["id"], 12000)
        get_success_data(api.issue_manifest(man_a["id"], PM))
        man_b = create_manifest(ctx["job"]["id"], ctx["profile"]["id"], 250)
        get_success_data(api.issue_manifest(man_b["id"], PM))
        man_c = create_manifest(ctx["job"]["id"], ctx["profile"]["id"], 500)
        resp = api.issue_manifest(man_c["id"], PM)
        validate_error(resp, ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED.value)
        assert resp.status_code == 422
        man_c_after = get_success_data(api.get_manifest(man_c["id"], PM))
        assert man_c_after["status"] == "DRAFT"
        facility = get_success_data(api.get_disposal_facility(ctx["facility"]["id"], PM))
        assert facility["reserved_tons"] == pytest.approx(49.0)


class TestFacilityReservationInvariant:
    def _setup(self, api):
        return _ctx_with_profile(
            api, facility_overrides={"total_capacity_tons": 10.0}
        )

    def test_issue_then_void_restores_reserved_tons(self, api):
        """PRD §2.9: "Issuing a manifest adds its estimated tonnage; receiving
        it, voiding it while `ISSUED`, or suspending its waste profile ... each
        release the reservation; and every release recomputes the facility's
        `posture` immediately — a `FULL` facility returns to `AVAILABLE` the
        moment `reserved_tons` drops below `total_capacity_tons`."

        Design: Difficulty/compensating_invariant/facility_reserved_tons_invariant_under_issue_then_void
        """
        ctx = self._setup(api)
        facility_id = ctx["facility"]["id"]
        initial = get_success_data(api.get_disposal_facility(facility_id, PM))
        assert initial["reserved_tons"] == pytest.approx(0.0)
        assert initial["posture"] == "AVAILABLE"

        manifest = create_manifest(ctx["job"]["id"], ctx["profile"]["id"], 2500)
        get_success_data(api.issue_manifest(manifest["id"], PM))
        mid = get_success_data(api.get_disposal_facility(facility_id, PM))
        assert mid["reserved_tons"] == pytest.approx(10.0)
        assert mid["posture"] == "FULL"

        get_success_data(api.void_manifest(manifest["id"], CO))
        post = get_success_data(api.get_disposal_facility(facility_id, PM))
        assert post["reserved_tons"] == pytest.approx(0.0)
        assert post["posture"] == "AVAILABLE"

    def test_issued_void_releases_reservation_immediately(self, api):
        """PRD §3.6: "voiding an `ISSUED` manifest releases its reservation and
        recomputes the facility's `posture`."
        PRD §2.4: "Consistency is immediate rather than eventual".

        Design: Difficulty/compensating_invariant/facility_reserved_tons_invariant_under_issue_then_void
        """
        ctx = self._setup(api)
        manifest = create_issued_manifest(ctx["job"]["id"], ctx["profile"]["id"], 2500)
        voided = get_success_data(api.void_manifest(manifest["id"], CO))
        assert voided["status"] == "VOIDED"
        facility = get_success_data(api.get_disposal_facility(ctx["facility"]["id"], PM))
        assert facility["reserved_tons"] == pytest.approx(0.0)
        assert facility["posture"] == "AVAILABLE"


class TestManifestInvalidTransitions:
    def test_depart_from_draft_rejected(self, api):
        """PRD §3.6: "Departure moves `ISSUED` → `IN_TRANSIT`."
        PRD §2.8: "State legality — the target entity is in a from-state that
        permits the requested transition ... else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/manifest_depart_from_draft_rejected
        """
        ctx = _ctx_with_profile(api)
        manifest = create_manifest(ctx["job"]["id"], ctx["profile"]["id"])
        resp = api.depart_manifest(manifest["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = get_success_data(api.get_manifest(manifest["id"], PM))
        assert after["status"] == "DRAFT"


class TestManifestCreateGate:
    def test_manifest_create_requires_job_in_progress(self, api):
        """PRD §3.6: "A `ProjectManager` creates one against a `job_id` — the
        job must be `IN_PROGRESS` or `FIELD_COMPLETE`, and any other execution
        state is rejected with `ERR_INVALID_STATE`".

        Design: Corner/validations/manifest_create_requires_job_in_progress
        """
        from test_helpers import create_site_with_active_schedule, create_job
        site, _ = create_site_with_active_schedule()
        facility, profile = create_facility_and_approved_profile(site["id"])
        job = create_job(site["id"], description="too early")
        resp = api.create_manifest(
            {"job_id": job["id"], "waste_profile_id": profile["id"],
             "estimated_gallons": 1000},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestJobCancelBlockedByCommittedWaste:
    def test_cancel_blocked_while_manifest_in_transit(self, api):
        """PRD §3.7: "Cancelling is available from `QUOTED`, `SCHEDULED`,
        `MOBILIZED`, `IN_PROGRESS` and `FIELD_COMPLETE` ... and is blocked while
        any manifest of the job is `IN_TRANSIT`, `RECEIVED` or `RECONCILED`,
        rejected with `ERR_JOB_HAS_COMMITTED_WASTE`."

        Design: Corner/validations/job_cancel_blocked_by_committed_waste
        """
        ctx = _ctx_with_profile(api)
        manifest = create_issued_manifest(ctx["job"]["id"], ctx["profile"]["id"], 1000)
        get_success_data(api.depart_manifest(manifest["id"], PM))
        resp = api.cancel_job(ctx["job"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_JOB_HAS_COMMITTED_WASTE.value)
        assert resp.status_code == 409
        job_after = get_success_data(api.get_job(ctx["job"]["id"], PM))
        assert job_after["execution_status"] == "IN_PROGRESS"
