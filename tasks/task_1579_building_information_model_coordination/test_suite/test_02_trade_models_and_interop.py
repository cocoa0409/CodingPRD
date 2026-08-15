"""Trade model creation rules, interop matrix, LOD gates, review cycle,
and the submission-vs-audit dual score variants."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_model,
    create_and_accept_model,
    create_lod_requirement,
    create_model,
    create_partner,
    create_project,
    create_trade_model_payload,
    get_model,
    make_trade_model_author_headers,
    reject_model,
    setup_frozen_assembly,
    submit_model,
    validate_error,
    validate_paginated,
    validate_success,
)

VDC = TEST_USERS["vdc_manager_headers"]
COORD = TEST_USERS["bim_coordinator_headers"]


class TestModelCreationRules:
    def test_trade_model_invalid_file_format_rejected(self, api):
        """PRD §3.2: "plus a `file_format` of `RVT`, `IFC`, `NWC`, or `DWG`"
        PRD §2.8: "Fifth, request shape: required fields present, types
        correct, enum values within range, array constraints satisfied — a
        fabrication scope of one to three unique disciplines, a non-empty
        elements array whose each `gross_qty` is at least its `deduction_qty`
        with neither negative, element counters non-negative with at least one
        element across the three criticality classes — and `ends_at` strictly
        after `starts_at`; shape failures are `ERR_INVALID_REQUEST`, except
        malformed time ranges, which are `ERR_INVALID_TIME_RANGE`."

        Design: Corner/entities/trade_model_invalid_file_format_rejected
        """
        project = create_project("E3")
        partner = create_partner(project["id"])
        payload = create_trade_model_payload(
            partner["id"], file_format="PDF", declared_lod=300,
            life_safety_elements=1, life_safety_compliant=1,
            envelope_elements=0, envelope_compliant=0,
            finish_elements=0, finish_compliant=0)
        resp = api.create_trade_model(
            project["id"], payload, make_trade_model_author_headers(partner["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_trade_model_zero_total_elements_rejected(self, api):
        """PRD §3.2: "Each class count must be non-negative, each compliant
        count must lie between zero and its class count, and the three classes
        must total at least one element; violations are rejected with
        `ERR_INVALID_REQUEST` at creation."

        Design: Corner/entities/trade_model_zero_total_elements_rejected
        """
        project = create_project("E4")
        partner = create_partner(project["id"])
        payload = create_trade_model_payload(
            partner["id"], file_format="RVT", declared_lod=300,
            life_safety_elements=0, life_safety_compliant=0,
            envelope_elements=0, envelope_compliant=0,
            finish_elements=0, finish_compliant=0)
        resp = api.create_trade_model(
            project["id"], payload, make_trade_model_author_headers(partner["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_trade_model_revision_numbers_are_per_discipline(self, api):
        """PRD §3.2: "The revision's `discipline` is copied from its authoring
        partner, and it receives a `revision_number` that increases
        monotonically per project and discipline, starting at 1."

        Design: Corner/entities/trade_model_revision_numbers_are_per_discipline
        """
        project = create_project("E5")
        p1 = create_partner(project["id"], company_name="StructCo",
                            discipline="STRUCTURAL")
        p2 = create_partner(project["id"], company_name="MechCo",
                            discipline="MECHANICAL", hourly_rate_cents=10000,
                            coordination_budget_hours=50.0,
                            software_platform="TEKLA")
        minimal = dict(life_safety_elements=1, life_safety_compliant=1,
                       envelope_elements=0, envelope_compliant=0,
                       finish_elements=0, finish_compliant=0)
        s1 = create_model(project["id"], p1["id"], declared_lod=300, **minimal)
        s2 = create_model(project["id"], p1["id"], declared_lod=350, **minimal)
        m1 = create_model(project["id"], p2["id"], file_format="IFC",
                          declared_lod=300, **minimal)
        assert s1["revision_number"] == 1
        assert s2["revision_number"] == 2, "second STRUCTURAL revision is 2"
        assert m1["revision_number"] == 1, "counter is per (project, discipline)"
        assert m1["discipline"] == "MECHANICAL", "discipline copied from partner"
        assert s1["discipline"] == "STRUCTURAL"

    def test_interop_status_computed_from_platform_format_matrix(self, api):
        """PRD §3.2: "A model authored in `REVIT` is `NATIVE` as `RVT`,
        `CONVERTIBLE` as `IFC` or `NWC`, and `INCOMPATIBLE` as `DWG`."
        PRD §3.2: "An `IFC_ONLY` partner produces `NATIVE` output only as
        `IFC`; every other format is `INCOMPATIBLE`."

        Design: Corner/entities/interop_status_computed_from_platform_format_matrix
        """
        project = create_project("E6")
        p1 = create_partner(project["id"], company_name="StructCo",
                            software_platform="REVIT")
        p3 = create_partner(project["id"], company_name="IfcCo",
                            discipline="ELECTRICAL", hourly_rate_cents=9000,
                            coordination_budget_hours=40.0,
                            software_platform="IFC_ONLY")
        minimal = dict(life_safety_elements=1, life_safety_compliant=1,
                       envelope_elements=0, envelope_compliant=0,
                       finish_elements=0, finish_compliant=0)
        m_native = create_model(project["id"], p1["id"], file_format="RVT",
                                **minimal)
        m_conv = create_model(project["id"], p1["id"], file_format="IFC",
                              **minimal)
        m_incompat = create_model(project["id"], p3["id"], file_format="RVT",
                                  **minimal)
        assert m_native["interop_status"] == "NATIVE"
        assert m_conv["interop_status"] == "CONVERTIBLE"
        assert m_incompat["interop_status"] == "INCOMPATIBLE"


class TestLodGate:
    def test_lod_requirement_exact_boundary_and_phase_keying(self, api):
        """PRD §3.2: "when a LOD requirement exists for the revision's
        discipline and the project's phase at submit time, `declared_lod` must
        be at least the required `min_lod` — equality passes — and a shortfall
        is rejected with `ERR_LOD_BELOW_PHASE_REQUIREMENT`; when no such
        requirement row exists, no LOD gate applies and submission proceeds."

        Design: Corner/calculations/lod_requirement_exact_boundary_and_phase_keying
        """
        project = create_project("CAL1")
        create_lod_requirement(project["id"], discipline="STRUCTURAL",
                               phase="SCHEMATIC_DESIGN", min_lod=300)
        p1 = create_partner(project["id"], company_name="StructCo",
                            discipline="STRUCTURAL")
        p4 = create_partner(project["id"], company_name="PlumbCo",
                            discipline="PLUMBING", hourly_rate_cents=9500,
                            coordination_budget_hours=40.0,
                            software_platform="ARCHICAD")
        minimal = dict(life_safety_elements=1, life_safety_compliant=1,
                       envelope_elements=0, envelope_compliant=0,
                       finish_elements=0, finish_compliant=0)
        m299 = create_model(project["id"], p1["id"], declared_lod=299, **minimal)
        m300 = create_model(project["id"], p1["id"], declared_lod=300, **minimal)
        mp = create_model(project["id"], p4["id"], file_format="IFC",
                          declared_lod=100, **minimal)

        resp = api.submit_trade_model(
            m299["id"], make_trade_model_author_headers(p1["id"]))
        validate_error(resp, ApiErrorId.ERR_LOD_BELOW_PHASE_REQUIREMENT)
        assert get_model(m299["id"])["status"] == "DRAFT"

        ok = validate_success(api.submit_trade_model(
            m300["id"], make_trade_model_author_headers(p1["id"])))
        assert ok["status"] == "SUBMITTED", "declared 300 == required 300 passes"

        ungated = validate_success(api.submit_trade_model(
            mp["id"], make_trade_model_author_headers(p4["id"])))
        assert ungated["status"] == "SUBMITTED", \
            "no requirement row for (PLUMBING, SCHEMATIC_DESIGN): no LOD gate"


class TestReviewCycle:
    def test_model_accept_from_draft_rejected(self, api):
        """PRD §3.2: "Review belongs to the `BIMCoordinator`, and only a
        `SUBMITTED` revision can be accepted or rejected — any other state
        draws `ERR_MODEL_NOT_SUBMITTED`."

        Design: Corner/state_machines/model_accept_from_draft_rejected
        """
        project = create_project("SM3")
        partner = create_partner(project["id"])
        model = create_model(project["id"], partner["id"],
                             life_safety_elements=1, life_safety_compliant=1,
                             envelope_elements=0, envelope_compliant=0,
                             finish_elements=0, finish_compliant=0)
        resp = api.accept_trade_model(model["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_MODEL_NOT_SUBMITTED)
        assert get_model(model["id"])["status"] == "DRAFT"

    def test_model_resubmit_after_reject_cycle(self, api):
        """PRD §3.2: "Submitting a revision moves it from `DRAFT` to
        `SUBMITTED` — or, in the rework loop, from `REJECTED` back to
        `SUBMITTED`" and "A successful submit records the caller in
        `submitted_by_user_id` and computes `submission_score`"
        PRD §3.2: "Rejection moves the revision to `REJECTED`, from which the
        author may resubmit after rework."

        Design: Corner/state_machines/model_resubmit_after_reject_cycle
        """
        project = create_project("SM4")
        partner = create_partner(project["id"])
        model = create_model(project["id"], partner["id"],
                             life_safety_elements=1, life_safety_compliant=1,
                             envelope_elements=0, envelope_compliant=0,
                             finish_elements=0, finish_compliant=0)
        submit_model(model["id"], partner["id"])
        rejected = reject_model(model["id"])
        assert rejected["status"] == "REJECTED"

        resubmitted = submit_model(model["id"], partner["id"])
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["submission_score"] == pytest.approx(100.0, abs=1e-6)
        assert resubmitted["submitted_by_user_id"] == partner["id"]

    def test_model_terminal_superseded_lockdown(self, api):
        """PRD §3.2: "Submitting a revision moves it from `DRAFT` to
        `SUBMITTED` — or, in the rework loop, from `REJECTED` back to
        `SUBMITTED` — and any other from-state is rejected with
        `ERR_MODEL_NOT_SUBMITTABLE`."

        Design: Corner/state_machines/model_terminal_superseded_lockdown
        """
        project = create_project("SM5")
        partner = create_partner(project["id"])
        minimal = dict(life_safety_elements=1, life_safety_compliant=1,
                       envelope_elements=0, envelope_compliant=0,
                       finish_elements=0, finish_compliant=0)
        m1 = create_and_accept_model(project["id"], partner["id"],
                                     declared_lod=300, **minimal)
        m2 = create_and_accept_model(project["id"], partner["id"],
                                     declared_lod=350, **minimal)
        # M2's acceptance superseded M1 (same discipline).
        assert get_model(m1["id"])["status"] == "SUPERSEDED"

        headers = make_trade_model_author_headers(partner["id"])
        resp1 = api.submit_trade_model(m1["id"], headers)
        validate_error(resp1, ApiErrorId.ERR_MODEL_NOT_SUBMITTABLE)
        resp2 = api.submit_trade_model(m2["id"], headers)
        validate_error(resp2, ApiErrorId.ERR_MODEL_NOT_SUBMITTABLE)


class TestDualScoreVariants:
    def test_model_scores_diverge_on_identical_counters(self, api):
        """PRD §3.2: "A successful submit records the caller in
        `submitted_by_user_id` and computes `submission_score`: one hundred
        times the total compliant elements divided by the total elements
        across all three classes, every element weighted equally, rounded
        half-up to one decimal place."
        PRD §3.2: "Acceptance computes `audit_score`, the criticality-weighted
        counterpart of the submission score: life-safety elements carry weight
        0.5, weather-envelope elements 0.3, and finish elements 0.2, so life
        safety counts two and a half times finish."

        Design: Difficulty/dual_variant_calc/model_score_submission_vs_audit_diverge
        """
        project = create_project("DV2")
        partner = create_partner(project["id"])
        model = create_model(project["id"], partner["id"],
                             life_safety_elements=10, life_safety_compliant=10,
                             envelope_elements=10, envelope_compliant=6,
                             finish_elements=10, finish_compliant=10)

        submitted = submit_model(model["id"], partner["id"])
        assert submitted["submission_score"] == pytest.approx(86.7, abs=1e-6), \
            "element-count-weighted: 100 x 26/30 rounded half-up to 1 dp"

        accepted = accept_model(model["id"])
        assert accepted["status"] == "ACCEPTED"
        assert accepted["audit_score"] == pytest.approx(88.0, abs=1e-6), \
            "criticality-weighted: 100 x (0.5x1.0 + 0.3x0.6 + 0.2x1.0) / 1.0"
        assert accepted["submission_score"] == pytest.approx(86.7, abs=1e-6)
        assert abs(accepted["audit_score"]
                   - accepted["submission_score"]) > 1e-6, \
            "the two variants of the same model data disagree"

    def test_model_scores_null_until_their_lifecycle_moments(self, api):
        """PRD §3.2: "Until its first submit, a revision's `submission_score`
        is null." and "until acceptance the `audit_score` is null."

        Design: Difficulty/dual_variant_calc/model_score_submission_vs_audit_diverge
        """
        project = create_project("DV2B")
        partner = create_partner(project["id"])
        model = create_model(project["id"], partner["id"],
                             life_safety_elements=10, life_safety_compliant=10,
                             envelope_elements=10, envelope_compliant=6,
                             finish_elements=10, finish_compliant=10)
        assert model["submission_score"] is None
        assert model["audit_score"] is None

        submitted = submit_model(model["id"], partner["id"])
        assert submitted["submission_score"] == pytest.approx(86.7, abs=1e-6)
        assert submitted["audit_score"] is None, \
            "audit_score stays null until acceptance"

        accepted = accept_model(model["id"])
        assert accepted["audit_score"] == pytest.approx(88.0, abs=1e-6)


class TestScoreRenormalization:
    def test_audit_score_zero_class_weight_renormalization(self, api):
        """PRD §3.2: "For each class holding at least one element, the class's
        compliant ratio is multiplied by its weight; the weighted ratios are
        summed, divided by the sum of the included weights, multiplied by one
        hundred, and rounded half-up to one decimal place. Classes with zero
        elements are excluded and the remaining weights renormalize"

        Design: Corner/calculations/audit_score_zero_class_weight_renormalization
        """
        project = create_project("CAL2")
        partner = create_partner(project["id"])
        model = create_model(project["id"], partner["id"],
                             life_safety_elements=0, life_safety_compliant=0,
                             envelope_elements=10, envelope_compliant=8,
                             finish_elements=10, finish_compliant=10)
        submitted = submit_model(model["id"], partner["id"])
        assert submitted["submission_score"] == pytest.approx(90.0, abs=1e-6), \
            "element-count-weighted: 100 x 18/20"

        accepted = accept_model(model["id"])
        assert accepted["audit_score"] == pytest.approx(88.0, abs=1e-6), \
            "life-safety excluded: 100 x (0.3x0.8 + 0.2x1.0) / (0.3 + 0.2)"


class TestListingAndConsistency:
    def test_fk_reverse_reachability_lists(self, api):
        """PRD §3.3: "An assembly's memberships, an assembly's freeze windows,
        and the federation memberships of any trade model are all listable"
        PRD §3.2: "Revisions are listable with `project_id`,
        `trade_partner_id`, `supersedes_model_id`, `status`, and `discipline`
        filters"

        Design: Corner/entities/fk_reverse_reachability_lists
        """
        ws = setup_frozen_assembly("E10")
        members, members_meta = validate_paginated(
            api.list_federated_model_members(ws["fed"]["id"], VDC))
        assert len(members) == 1
        assert members[0]["trade_model_id"] == ws["model"]["id"]

        data, meta = validate_paginated(api.list_trade_models(
            VDC, params={"project_id": ws["project"]["id"], "status": "ACCEPTED"}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == ws["model"]["id"]

    def test_immediate_consistency_in_mutation_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §2.4: "The `version` is an integer that starts at 1 and increments
        by one on every mutation of that resource."

        Design: Corner/consistency_model/immediate_consistency_in_mutation_response
        """
        project = create_project("CM1")
        partner = create_partner(project["id"])
        model = create_model(project["id"], partner["id"])
        submit_model(model["id"], partner["id"])

        # The accept response itself carries the post-mutation state —
        # no re-read required. Model version: 1 (create) +1 (submit) +1
        # (accept) == 3.
        accepted = validate_success(api.accept_trade_model(model["id"], COORD))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["audit_score"] == pytest.approx(100.0, abs=1e-6)
        assert accepted["version"] == 3
