"""Permit compliance evaluation, pinned-revision freshness, and expiry tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_permit,
    create_design_package_payload,
    create_permit_payload,
    create_started_phase,
    get_success_data,
    make_contractor_headers,
    make_homeowner_headers,
    make_subcontractor_headers,
    register_subcontractor,
    set_logical_clock,
    setup_permitting_project,
    validate_error,
    validate_success,
)

INSPECTOR = TEST_USERS["inspector_headers"]


def _setup_boundary_permit(api):
    """PERMITTING project; permit sitting exactly on the R1/R2 compliance edges."""
    ctx = setup_permitting_project(address="4 D St", basement_sqft=1200,
                                   base_contract_cents=8000000)
    ctr_h = make_contractor_headers(ctx["contractor"]["id"])
    pm = get_success_data(
        api.create_permit(
            ctx["project"]["id"],
            create_permit_payload(
                bedroom_count=2,
                windows=[
                    {"net_clear_sqft": 6.0, "sill_height_in": 40},
                    {"net_clear_sqft": 5.7, "sill_height_in": 44},
                ],
                ceiling_height_in=84,
                finished_area_sqft=1200,
                low_area_sqft=600,
                prohibited_area_sqft=0,
            ),
            ctr_h,
        )
    )
    ctx["permit"] = pm
    return ctx


class TestEgressCeilingBoundary:
    def test_boundary_window_and_half_area_both_compliant(self, api):
        """PRD §3.4: "Next, egress rule R1: the count of proposed windows with
        `net_clear_sqft` of at least 5.7 square feet and `sill_height_in` of at most
        44 inches must be at least the `bedroom_count`"
        PRD §3.4: "R2 requires at least half of the finished area to be full-height,
        evaluated exactly as `finished_area_sqft` minus `low_area_sqft` minus
        `prohibited_area_sqft`, doubled, being at least `finished_area_sqft`"

        Design: Difficulty/combinatorial_formula/egress_ceiling_multi_input_boundary
        """
        ctx = _setup_boundary_permit(api)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        submitted = validate_success(api.submit_permit(ctx["permit"]["id"], ctr_h), 200)
        assert_permit(submitted)
        assert submitted["egress_compliant"] is True, (
            "window {5.7 sqft, 44 in sill} sits exactly on the compliant edge"
        )
        assert submitted["ceiling_compliant"] is True, (
            "full-height area 600 of 1200 is exactly half; zero prohibited"
        )

    def test_boundary_submit_reaches_under_review_with_revision_pin(self, api):
        """PRD §3.4: "At creation the permit pins the design it is based on:
        `pinned_design_id` and `pinned_design_revision` capture the identity and
        `revision_number` of the project's currently `APPROVED` package"
        PRD §3.4: "On every submission the `egress_compliant` flag (R1 alone) and the
        `ceiling_compliant` flag (R2 and R3 together) are computed and persisted"

        Design: Difficulty/combinatorial_formula/egress_ceiling_multi_input_boundary
        """
        ctx = _setup_boundary_permit(api)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        pm = ctx["permit"]
        assert pm["pinned_design_id"] == ctx["design"]["id"]
        assert pm["pinned_design_revision"] == 1
        submitted = validate_success(api.submit_permit(pm["id"], ctr_h), 200)
        assert submitted["status"] == "UNDER_REVIEW"
        assert submitted["pinned_design_revision"] == 1


class TestComplianceFailures:
    def test_egress_failure_reported_before_ceiling(self, api):
        """PRD §3.4: "failure is rejected with `ERR_EGRESS_NONCOMPLIANT` — reported
        even when the ceiling rules would also fail, because R1 is always evaluated
        and reported before R2 and R3."

        Design: Corner/validations/egress_priority_over_ceiling
        """
        ctx = setup_permitting_project(address="V2 St")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        pm = get_success_data(
            api.create_permit(
                ctx["project"]["id"],
                create_permit_payload(
                    bedroom_count=1,
                    windows=[{"net_clear_sqft": 4.0, "sill_height_in": 50}],
                    ceiling_height_in=80,
                    finished_area_sqft=800,
                    low_area_sqft=100,
                    prohibited_area_sqft=10,
                ),
                ctr_h,
            )
        )
        res = api.submit_permit(pm["id"], ctr_h)
        validate_error(res, ApiErrorId.ERR_EGRESS_NONCOMPLIANT)
        # Re-read via list to confirm the permit never left DRAFT.
        permits = api.list_permits(ctx["project"]["id"], ctr_h).json()["data"]
        assert permits[0]["status"] == "DRAFT"

    def test_ceiling_full_height_below_half_rejected(self, api):
        """PRD §3.4: "R2 requires at least half of the finished area to be
        full-height, evaluated exactly as `finished_area_sqft` minus `low_area_sqft`
        minus `prohibited_area_sqft`, doubled, being at least `finished_area_sqft` —
        the doubling keeps the comparison in whole square feet — and R3 requires
        `prohibited_area_sqft` to be exactly zero; failure of either is rejected with
        `ERR_CEILING_NONCOMPLIANT`."

        Design: Corner/validations/ceiling_noncompliant_returns_error
        """
        ctx = setup_permitting_project(address="V3 St", basement_sqft=1000)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        pm = get_success_data(
            api.create_permit(
                ctx["project"]["id"],
                create_permit_payload(
                    bedroom_count=0, windows=[], ceiling_height_in=80,
                    finished_area_sqft=1000, low_area_sqft=601,
                    prohibited_area_sqft=0,
                ),
                ctr_h,
            )
        )
        # (1000 - 601 - 0) * 2 = 798 < 1000: R2 fails; R1 vacuously satisfied.
        res = api.submit_permit(pm["id"], ctr_h)
        validate_error(res, ApiErrorId.ERR_CEILING_NONCOMPLIANT)


class TestPinnedRevisionFreshness:
    def test_resubmit_after_new_design_approval_is_stale(self, api):
        """PRD §3.4: "Freshness comes first: the pinned pair must still equal the
        identity and revision number of the project's currently `APPROVED` package,
        so if the homeowner has since approved a different package or a newer
        revision of it, submission is rejected with `ERR_DESIGN_REVISION_STALE`."
        PRD §3.4: "a resubmission from `CORRECTIONS_REQUIRED` additionally increments
        `amendment_count` — which starts at zero at permit creation — by one and
        recomputes both flags."

        Design: Corner/validations/design_revision_stale_blocks_permit_resubmit
        """
        ctx = setup_permitting_project(address="V9 St")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
        dp1 = ctx["design"]
        pm = get_success_data(
            api.create_permit(ctx["project"]["id"], create_permit_payload(), ctr_h)
        )
        assert pm["pinned_design_id"] == dp1["id"]
        assert pm["pinned_design_revision"] == 1
        validate_success(api.submit_permit(pm["id"], ctr_h), 200)
        validate_success(
            api.record_permit_decision(
                pm["id"],
                {"outcome": "CORRECTIONS_REQUIRED",
                 "notes": "structural detail missing"},
                INSPECTOR,
            ),
            200,
        )
        # Homeowner approves a different package in between.
        dp2 = get_success_data(
            api.create_design_package(
                ctx["project"]["id"],
                create_design_package_payload(layout_notes="v2"),
                ctr_h,
            )
        )
        validate_success(api.submit_design_package(dp2["id"], ctr_h), 200)
        validate_success(api.approve_design_package(dp2["id"], ho_h), 200)

        res = api.submit_permit(pm["id"], ctr_h)
        validate_error(res, ApiErrorId.ERR_DESIGN_REVISION_STALE)
        permits = api.list_permits(ctx["project"]["id"], ctr_h).json()["data"]
        assert permits[0]["amendment_count"] == 0, (
            "a rejected resubmit must not consume an amendment"
        )
        assert permits[0]["status"] == "CORRECTIONS_REQUIRED"


class TestPermitExpiry:
    def test_expired_permit_blocks_final_inspection(self, api):
        """PRD §2.5: "A permit still in `ISSUED` whose `issued_at` date is more than
        180 days behind the new current date moves to `EXPIRED`, unless its project
        has already reached `COMPLETED`."
        PRD §3.8: "A `FINAL` request is refused with `ERR_PERMIT_EXPIRED` while any
        permit of the project is `EXPIRED`."

        Design: Corner/validations/permit_expiry_blocks_final
        """
        ctx = setup_permitting_project(address="V8 St")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        pm = get_success_data(
            api.create_permit(ctx["project"]["id"], create_permit_payload(), ctr_h)
        )
        validate_success(api.submit_permit(pm["id"], ctr_h), 200)
        set_logical_clock("2026-06-01T00:00:00Z")
        validate_success(
            api.record_permit_decision(pm["id"], {"outcome": "ISSUED"}, INSPECTOR), 200
        )
        sub = register_subcontractor(trade="GENERAL", name="Gen V8")
        phase = create_started_phase(
            ctx["project"]["id"], ctr_h, sub,
            trade="GENERAL", zone="REC",
            start_date="2026-06-01", end_date="2026-06-08",
        )
        get_success_data(
            api.complete_work_phase(
                phase["id"], make_subcontractor_headers(sub["id"])
            )
        )
        # 2026-06-01 + 180 days = 2026-11-28; the new clock date is past it.
        set_logical_clock("2026-12-01T00:00:00Z")
        permits = api.list_permits(ctx["project"]["id"], ctr_h).json()["data"]
        assert permits[0]["status"] == "EXPIRED"

        res = api.create_inspection(ctx["project"]["id"], {"type": "FINAL"}, ctr_h)
        validate_error(res, ApiErrorId.ERR_PERMIT_EXPIRED)
