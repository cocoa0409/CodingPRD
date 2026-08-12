"""Moisture assessment scoring: dual variants, boundaries, creation guards."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_moisture_assessment,
    create_homeowner_payload,
    create_moisture_assessment_payload,
    create_project_payload,
    get_success_data,
    make_contractor_headers,
    register_contractor,
    setup_intake_project,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_divergence_projects(api):
    """Project A: SCREENING slab 3.0 / RH 60 submitted.
    Project B: SCREENING slab 6.0 rejected, then VERIFICATION slab 3.0 / RH 60
    submitted. Returns both resolved assessments plus both projects."""
    ctr = register_contractor(name="GC One", license_no="LIC-1")
    ctr_h = make_contractor_headers(ctr["id"])
    ho_a = get_success_data(
        api.create_homeowner(
            create_homeowner_payload(name="H A", email="ha@x.com", phone="1"), ctr_h
        )
    )
    ho_b = get_success_data(
        api.create_homeowner(
            create_homeowner_payload(name="H B", email="hb@x.com", phone="2"), ctr_h
        )
    )
    proj_a = get_success_data(
        api.create_project(
            create_project_payload(
                ho_a["id"], address="1 A St", basement_sqft=900,
                base_contract_cents=5000000,
            ),
            ctr_h,
        )
    )
    ma_a = get_success_data(
        api.create_moisture_assessment(
            proj_a["id"],
            create_moisture_assessment_payload(
                slab_moisture_lbs=3.0, interior_rh_pct=60,
            ),
            ctr_h,
        )
    )
    ma_a = validate_success(api.submit_moisture_assessment(ma_a["id"], ctr_h), 200)

    proj_b = get_success_data(
        api.create_project(
            create_project_payload(
                ho_b["id"], address="2 B St", basement_sqft=900,
                base_contract_cents=5000000,
            ),
            ctr_h,
        )
    )
    ma_b1 = get_success_data(
        api.create_moisture_assessment(
            proj_b["id"],
            create_moisture_assessment_payload(slab_moisture_lbs=6.0),
            ctr_h,
        )
    )
    validate_success(api.submit_moisture_assessment(ma_b1["id"], ctr_h), 200)
    ma_b2 = get_success_data(
        api.create_moisture_assessment(
            proj_b["id"],
            create_moisture_assessment_payload(
                assessment_kind="VERIFICATION",
                slab_moisture_lbs=3.0, interior_rh_pct=60,
            ),
            ctr_h,
        )
    )
    ma_b2 = validate_success(api.submit_moisture_assessment(ma_b2["id"], ctr_h), 200)
    proj_b_after = get_success_data(api.get_project(proj_b["id"], ctr_h))
    return {"ma_a": ma_a, "ma_b2": ma_b2, "proj_a": proj_a, "proj_b": proj_b_after}


class TestScreeningVsVerificationDivergence:
    def test_identical_readings_score_zero_low_accepted_under_screening(self, api):
        """PRD §3.2: "Identical readings therefore score lower under screening than
        under verification: a slab emission of 3.0 with humidity of 60 contributes no
        points under `SCREENING` but 40 points under `VERIFICATION`."
        PRD §3.2: "a `SCREENING` assessment is accepted in either the `LOW` or
        `MODERATE` band, while a `VERIFICATION` assessment is accepted only in the
        `LOW` band."

        Design: Difficulty/dual_variant_calc/moisture_screening_vs_verification_divergence
        """
        ctx = _setup_divergence_projects(api)
        ma_a = ctx["ma_a"]
        assert_moisture_assessment(ma_a)
        assert ma_a["assessment_kind"] == "SCREENING"
        assert ma_a["moisture_risk_score"] == 0
        assert ma_a["risk_band"] == "LOW"
        assert ma_a["status"] == "ACCEPTED"

    def test_identical_readings_score_40_high_rejected_under_verification(self, api):
        """PRD §3.2: "Identical readings therefore score lower under screening than
        under verification: a slab emission of 3.0 with humidity of 60 contributes no
        points under `SCREENING` but 40 points under `VERIFICATION`."
        PRD §3.2: "an unacceptable band — `HIGH` for screening, or `MODERATE` or
        `HIGH` for verification — resolves the assessment to `REJECTED` with the
        project status unchanged."

        Design: Difficulty/dual_variant_calc/moisture_screening_vs_verification_divergence
        """
        ctx = _setup_divergence_projects(api)
        ma_b2 = ctx["ma_b2"]
        assert_moisture_assessment(ma_b2)
        assert ma_b2["assessment_kind"] == "VERIFICATION"
        assert ma_b2["moisture_risk_score"] == 40
        assert ma_b2["risk_band"] == "HIGH"
        assert ma_b2["status"] == "REJECTED"
        assert ctx["proj_b"]["status"] == "ASSESSMENT", (
            "a VERIFICATION rejection must not advance the project"
        )
        assert ctx["ma_a"]["moisture_risk_score"] == 0
        assert ma_b2["moisture_risk_score"] == 40


def _setup_slab_boundary_projects(api, slab_a, slab_b):
    """Two INTAKE projects, each with one SCREENING assessment at the given slab
    emission (all other readings benign), both submitted."""
    ctr = register_contractor(name="GC Eleven", license_no="LIC-11")
    ctr_h = make_contractor_headers(ctr["id"])
    out = {}
    for key, slab, addr, name, email, phone in (
        ("a", slab_a, "12 L St", "H L", "hl@x.com", "12"),
        ("b", slab_b, "13 M St", "H M", "hm@x.com", "13"),
    ):
        ho = get_success_data(
            api.create_homeowner(
                create_homeowner_payload(name=name, email=email, phone=phone), ctr_h
            )
        )
        proj = get_success_data(
            api.create_project(
                create_project_payload(
                    ho["id"], address=addr, basement_sqft=800,
                    base_contract_cents=4000000,
                ),
                ctr_h,
            )
        )
        ma = get_success_data(
            api.create_moisture_assessment(
                proj["id"],
                create_moisture_assessment_payload(slab_moisture_lbs=slab),
                ctr_h,
            )
        )
        ma = validate_success(api.submit_moisture_assessment(ma["id"], ctr_h), 200)
        proj_after = get_success_data(api.get_project(proj["id"], ctr_h))
        out[key] = {"assessment": ma, "project": proj_after}
    return out


class TestSlabEmissionBoundary:
    def test_slab_5_0_scores_25_moderate_accepted(self, api):
        """PRD §3.2: "Under `SCREENING`: the slab component is 0 points when
        `slab_moisture_lbs` is at most 3.0, 25 points when it is greater than 3.0 and
        at most 5.0, and 50 points when it exceeds 5.0"
        PRD §3.2: "An acceptable band resolves the assessment to `ACCEPTED`, and if
        the project is still in `INTAKE` or `ASSESSMENT` it advances to `DESIGN`"

        Design: Difficulty/boundary_precision_check/slab_emission_threshold_5_0_boundary
        """
        ctx = _setup_slab_boundary_projects(api, 5.0, 5.01)
        ma_a = ctx["a"]["assessment"]
        assert ma_a["moisture_risk_score"] == 25
        assert ma_a["risk_band"] == "MODERATE"
        assert ma_a["status"] == "ACCEPTED"
        assert ctx["a"]["project"]["status"] == "DESIGN"

    def test_slab_5_01_scores_50_high_rejected(self, api):
        """PRD §3.2: "Under `SCREENING`: the slab component is 0 points when
        `slab_moisture_lbs` is at most 3.0, 25 points when it is greater than 3.0 and
        at most 5.0, and 50 points when it exceeds 5.0"
        PRD §3.2: "an unacceptable band — `HIGH` for screening, or `MODERATE` or
        `HIGH` for verification — resolves the assessment to `REJECTED` with the
        project status unchanged."

        Design: Difficulty/boundary_precision_check/slab_emission_threshold_5_0_boundary
        """
        ctx = _setup_slab_boundary_projects(api, 5.0, 5.01)
        ma_b = ctx["b"]["assessment"]
        assert ma_b["moisture_risk_score"] == 50
        assert ma_b["risk_band"] == "HIGH"
        assert ma_b["status"] == "REJECTED"
        assert ctx["b"]["project"]["status"] == "ASSESSMENT"


class TestAssessmentCreationGuards:
    def test_assessment_kind_defaults_to_screening(self, api):
        """PRD §3.2: "The optional `assessment_kind` defaults to `SCREENING`."
        PRD §3.2: "The first assessment created on an `INTAKE` project advances the
        project to `ASSESSMENT`."

        Design: Corner/entities/assessment_kind_defaults_to_screening
        """
        ctx = setup_intake_project()
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        res = api.create_moisture_assessment(
            ctx["project"]["id"], create_moisture_assessment_payload(), ctr_h
        )
        ma = validate_success(res, 201)
        assert ma["assessment_kind"] == "SCREENING"
        assert ma["status"] == "DRAFT"
        proj = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert proj["status"] == "ASSESSMENT"

    def test_duplicate_draft_assessment_rejected(self, api):
        """PRD §3.2: "a project may hold at most one `DRAFT` assessment at a time
        (`ERR_ASSESSMENT_IN_PROGRESS`)"

        Design: Corner/validations/duplicate_draft_assessment_rejected
        """
        ctx = setup_intake_project()
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ma = get_success_data(
            api.create_moisture_assessment(
                ctx["project"]["id"], create_moisture_assessment_payload(), ctr_h
            )
        )
        res = api.create_moisture_assessment(
            ctx["project"]["id"],
            create_moisture_assessment_payload(slab_moisture_lbs=2.1),
            ctr_h,
        )
        validate_error(res, ApiErrorId.ERR_ASSESSMENT_IN_PROGRESS)

        validate_success(api.submit_moisture_assessment(ma["id"], ctr_h), 200)
        res2 = api.create_moisture_assessment(
            ctx["project"]["id"],
            create_moisture_assessment_payload(slab_moisture_lbs=2.1),
            ctr_h,
        )
        validate_success(res2, 201)

    def test_verification_without_prior_rejection_rejected(self, api):
        """PRD §3.2: "a `VERIFICATION` assessment may be created only when a
        `REJECTED` assessment already exists on the project
        (`ERR_REASSESSMENT_NOT_ALLOWED`)"

        Design: Corner/validations/verification_without_prior_rejection_rejected
        """
        ctx = setup_intake_project()
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        res = api.create_moisture_assessment(
            ctx["project"]["id"],
            create_moisture_assessment_payload(
                assessment_kind="VERIFICATION",
                slab_moisture_lbs=1.5, interior_rh_pct=45,
            ),
            ctr_h,
        )
        validate_error(res, ApiErrorId.ERR_REASSESSMENT_NOT_ALLOWED)
