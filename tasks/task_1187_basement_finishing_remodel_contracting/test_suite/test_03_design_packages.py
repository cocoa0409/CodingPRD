"""Moisture remediation loop and design-package revision cycle tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_design_package_payload,
    create_moisture_assessment_payload,
    get_success_data,
    make_contractor_headers,
    make_homeowner_headers,
    reopen_moisture_assessment_payload,
    setup_design_project,
    setup_intake_project,
    validate_error,
    validate_success,
)


def _setup_rejected_assessment(api):
    """INTAKE project whose first SCREENING assessment scores HIGH -> REJECTED."""
    ctx = setup_intake_project(address="6 F St", basement_sqft=850,
                               base_contract_cents=4000000)
    ctr_h = make_contractor_headers(ctx["contractor"]["id"])
    ma = get_success_data(
        api.create_moisture_assessment(
            ctx["project"]["id"],
            create_moisture_assessment_payload(
                slab_moisture_lbs=6.0, interior_rh_pct=72,
                efflorescence_observed=True, grading_deficit=True,
                egress_windows_existing=0,
            ),
            ctr_h,
        )
    )
    ma = validate_success(api.submit_moisture_assessment(ma["id"], ctr_h), 200)
    ctx["assessment"] = ma
    return ctx


class TestMoistureRemediationCycle:
    def test_rejected_assessment_reopen_forces_verification(self, api):
        """PRD §3.2: "Reopening forces the `assessment_kind` to `VERIFICATION`,
        because a reopened assessment exists to verify remediation, and clears the
        computed score and band until the next submit"
        PRD §3.2: "the contractor reopens a `REJECTED` assessment — the only state
        from which reopening is allowed, with any other state rejected as
        `ERR_INVALID_STATE` — supplying `remediation_notes` and the four
        post-remediation readings, which overwrite the prior readings in place."

        Design: Difficulty/non_linear_state_machine/moisture_assessment_remediation_cycle
        """
        ctx = _setup_rejected_assessment(api)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ma = ctx["assessment"]
        # SCREENING: slab 6.0 -> 50, RH 72 -> 30, efflorescence 20, grading 15 = 115.
        assert ma["status"] == "REJECTED"
        assert ma["risk_band"] == "HIGH"
        assert ma["moisture_risk_score"] == 115

        reopened = validate_success(
            api.reopen_moisture_assessment(
                ma["id"],
                reopen_moisture_assessment_payload(
                    remediation_notes="interior drain tile + dehumidifier",
                ),
                ctr_h,
            ),
            200,
        )
        assert reopened["status"] == "DRAFT"
        assert reopened["assessment_kind"] == "VERIFICATION"
        assert reopened["remediation_notes"] == "interior drain tile + dehumidifier"

    def test_remediated_resubmit_accepted_advances_project_to_design(self, api):
        """PRD §3.2: "An acceptable band resolves the assessment to `ACCEPTED`, and if
        the project is still in `INTAKE` or `ASSESSMENT` it advances to `DESIGN`"
        PRD §3.2: "a `VERIFICATION` assessment is accepted only in the `LOW` band."

        Design: Difficulty/non_linear_state_machine/moisture_assessment_remediation_cycle
        """
        ctx = _setup_rejected_assessment(api)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ma = ctx["assessment"]
        validate_success(
            api.reopen_moisture_assessment(
                ma["id"],
                reopen_moisture_assessment_payload(
                    slab_moisture_lbs=2.0, interior_rh_pct=50,
                ),
                ctr_h,
            ),
            200,
        )
        resolved = validate_success(
            api.submit_moisture_assessment(ma["id"], ctr_h), 200
        )
        # VERIFICATION: slab 2.0 -> 0, RH 50 -> 0, no flags -> score 0 / LOW.
        assert resolved["status"] == "ACCEPTED"
        assert resolved["moisture_risk_score"] == 0
        assert resolved["risk_band"] == "LOW"
        proj = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert proj["status"] == "DESIGN"


def _setup_revision_loop(api):
    """Project in DESIGN; package P1 submitted, revision-requested. Returns ctx."""
    ctx = setup_design_project(address="7 G St", basement_sqft=1000,
                               base_contract_cents=6000000)
    ctr_h = make_contractor_headers(ctx["contractor"]["id"])
    ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
    dp1 = get_success_data(
        api.create_design_package(
            ctx["project"]["id"],
            create_design_package_payload(layout_notes="v1 layout"),
            ctr_h,
        )
    )
    validate_success(api.submit_design_package(dp1["id"], ctr_h), 200)
    validate_success(
        api.request_design_revision(
            dp1["id"], {"revision_notes": "move wet bar to east wall"}, ho_h
        ),
        200,
    )
    ctx.update({"dp1": dp1, "ctr_h": ctr_h, "ho_h": ho_h})
    return ctx


class TestDesignPackageRevisionLoop:
    def test_resubmit_from_revision_requested_increments_revision_number(self, api):
        """PRD §3.3: "A resubmission from `REVISION_REQUESTED` increments the
        package's `revision_number` by one, so the revision number always counts how
        many times the package has traveled around the negotiation loop."

        Design: Difficulty/non_linear_state_machine/design_package_revision_loop_with_supersede
        """
        ctx = _setup_revision_loop(api)
        resubmitted = validate_success(
            api.submit_design_package(ctx["dp1"]["id"], ctx["ctr_h"]), 200
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_number"] == 2

    def test_second_approval_supersedes_first_and_repoints_project(self, api):
        """PRD §3.3: "Approval moves the package from `SUBMITTED` to `APPROVED`,
        supersedes any previously `APPROVED` package of the same project (which moves
        to `SUPERSEDED`), and sets the project's `approved_design_id` to the newly
        approved package; when the project is in `DESIGN` it then advances to
        `PERMITTING`."

        Design: Difficulty/non_linear_state_machine/design_package_revision_loop_with_supersede
        """
        ctx = _setup_revision_loop(api)
        ctr_h, ho_h = ctx["ctr_h"], ctx["ho_h"]
        dp1 = ctx["dp1"]
        validate_success(api.submit_design_package(dp1["id"], ctr_h), 200)
        approved1 = validate_success(api.approve_design_package(dp1["id"], ho_h), 200)
        assert approved1["status"] == "APPROVED"
        proj = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert proj["status"] == "PERMITTING"
        assert proj["approved_design_id"] == dp1["id"]

        dp2 = get_success_data(
            api.create_design_package(
                ctx["project"]["id"],
                create_design_package_payload(
                    layout_notes="v2 layout",
                    mechanical_relocations=[{
                        "system": "PLUMBING",
                        "description": "relocate rough-in",
                        "estimated_cents": 180000,
                    }],
                ),
                ctr_h,
            )
        )
        validate_success(api.submit_design_package(dp2["id"], ctr_h), 200)
        approved2 = validate_success(api.approve_design_package(dp2["id"], ho_h), 200)
        assert approved2["status"] == "APPROVED"

        dp1_after = get_success_data(api.get_design_package(dp1["id"], ctr_h))
        assert dp1_after["status"] == "SUPERSEDED"
        proj_after = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert proj_after["approved_design_id"] == dp2["id"]


def _setup_rejected_then_no_accepted(api):
    """ASSESSMENT project whose only assessment was REJECTED; a DRAFT package."""
    ctx = setup_intake_project(address="15 O St", basement_sqft=900,
                               base_contract_cents=4500000)
    ctr_h = make_contractor_headers(ctx["contractor"]["id"])
    ma = get_success_data(
        api.create_moisture_assessment(
            ctx["project"]["id"],
            create_moisture_assessment_payload(
                slab_moisture_lbs=6.5, interior_rh_pct=75,
                efflorescence_observed=True, egress_windows_existing=0,
            ),
            ctr_h,
        )
    )
    validate_success(api.submit_moisture_assessment(ma["id"], ctr_h), 200)
    dp = get_success_data(
        api.create_design_package(
            ctx["project"]["id"],
            create_design_package_payload(layout_notes="suite"),
            ctr_h,
        )
    )
    ctx.update({"assessment": ma, "package": dp})
    return ctx


class TestDesignSubmitMoistureGate:
    def test_design_submit_blocked_without_accepted_assessment(self, api):
        """PRD §3.3: "In both cases the project must hold an `ACCEPTED` moisture
        assessment — without one, submission is rejected with
        `ERR_MOISTURE_NOT_CLEARED`."

        Design: Difficulty/cross_entity_state_dependency/design_submit_blocked_until_moisture_accepted
        """
        ctx = _setup_rejected_then_no_accepted(api)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        res = api.submit_design_package(ctx["package"]["id"], ctr_h)
        validate_error(res, ApiErrorId.ERR_MOISTURE_NOT_CLEARED)
        dp = get_success_data(api.get_design_package(ctx["package"]["id"], ctr_h))
        assert dp["status"] == "DRAFT"
        assert dp["revision_number"] == 1, "failed submit must not consume a revision"

    def test_design_submit_succeeds_after_remediation_acceptance(self, api):
        """PRD §3.3: "In both cases the project must hold an `ACCEPTED` moisture
        assessment — without one, submission is rejected with
        `ERR_MOISTURE_NOT_CLEARED`."
        PRD §3.3: "Every new package starts in `DRAFT` with `revision_number` 1."

        Design: Difficulty/cross_entity_state_dependency/design_submit_blocked_until_moisture_accepted
        """
        ctx = _setup_rejected_then_no_accepted(api)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ma = ctx["assessment"]
        validate_success(
            api.reopen_moisture_assessment(
                ma["id"],
                reopen_moisture_assessment_payload(
                    remediation_notes="fixed grading",
                    slab_moisture_lbs=1.8, interior_rh_pct=50,
                ),
                ctr_h,
            ),
            200,
        )
        validate_success(api.submit_moisture_assessment(ma["id"], ctr_h), 200)
        submitted = validate_success(
            api.submit_design_package(ctx["package"]["id"], ctr_h), 200
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["revision_number"] == 1


class TestDesignInvalidTransitions:
    def test_design_approve_from_draft_rejected(self, api):
        """PRD §3.3: "Both actions require the acting homeowner to own the project
        (`ERR_NOT_RESOURCE_OWNER`) and require the package to be `SUBMITTED`
        (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/design_approve_from_draft_rejected
        """
        ctx = setup_design_project(address="11 Corner Way")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
        dp = get_success_data(
            api.create_design_package(
                ctx["project"]["id"],
                create_design_package_payload(layout_notes="x"),
                ctr_h,
            )
        )
        res = api.approve_design_package(dp["id"], ho_h)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        dp_after = get_success_data(api.get_design_package(dp["id"], ctr_h))
        assert dp_after["status"] == "DRAFT"
        assert dp_after["revision_number"] == 1
