"""Firm element plan workflow: publish/close guards, attestation gating,
plan-year uniqueness, OCC on plan creation, publish side effects."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT,
    create_needs_analysis_payload,
    create_plan,
    create_plan_with_needs_analysis,
    create_published_plan,
    create_rep,
    get_pending_attestation,
    get_success_data,
    make_rep_headers,
    set_clock,
    setup_rep_with_published_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPublishGuards:
    def test_publish_without_needs_analysis_rejected(self, api, admin_headers):
        """PRD §3.6: "Publishing moves the plan from `NEEDS_ANALYSIS` to
        `PLAN_PUBLISHED`. It requires the needs analysis to have been completed
        — publishing without it is rejected with `ERR_NEEDS_ANALYSIS_MISSING`."

        Design: Corner/errors/c_publish_without_needs_analysis_returns_409
        """
        rep = create_rep(crd_number="CRD-NAM")
        plan = create_plan(rep["id"], rep["version"], plan_year=2026)
        resp = api.publish_plan(plan["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_NEEDS_ANALYSIS_MISSING)

    def test_publish_without_needs_analysis_leaves_plan_in_draft(
            self, api, admin_headers):
        """PRD §3.6: "It requires the needs analysis to have been completed —
        publishing without it is rejected with `ERR_NEEDS_ANALYSIS_MISSING` —
        and it is the moment the year's requirement is fixed."

        Design: Corner/errors/c_publish_without_needs_analysis_returns_409
        """
        rep = create_rep(crd_number="CRD-NAM2")
        plan = create_plan(rep["id"], rep["version"], plan_year=2026)
        validate_error(
            api.publish_plan(plan["id"], admin_headers),
            ApiErrorId.ERR_NEEDS_ANALYSIS_MISSING)
        data = validate_success(api.get_firm_element_plan(plan["id"], admin_headers))
        assert data["plan_status"] == "NEEDS_ANALYSIS"

    def test_needs_analysis_after_publish_rejected(self, api, admin_headers):
        """PRD §3.6: "While the plan is in `NEEDS_ANALYSIS` — otherwise the
        request is rejected with `ERR_PLAN_NOT_NEEDS_ANALYSIS` — a
        `TrainingAdmin` records the analysis by supplying an
        `analysis_document_ref` and free-text `analysis_notes`."

        Design: Corner/errors/c_needs_analysis_on_published_plan_returns_409
        """
        rep = create_rep(crd_number="CRD-NAP")
        plan = create_published_plan(rep["id"], rep["version"], plan_year=2026)
        resp = api.record_needs_analysis(
            plan["id"],
            create_needs_analysis_payload(
                analysis_document_ref="doc-nap-late", analysis_notes="late edit"),
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_NEEDS_ANALYSIS)


class TestCloseGuards:
    def test_close_with_hours_unmet_rejected(self, api, admin_headers):
        """PRD §3.6: "a `TrainingAdmin` may close a plan that is
        `PLAN_PUBLISHED` — otherwise `ERR_PLAN_NOT_PUBLISHED` — only once its
        `certified_hours` are at least its `required_hours`; closing short of
        the requirement is rejected with `ERR_PLAN_HOURS_UNMET`."

        Design: Corner/state_machines/c_close_plan_hours_unmet_returns_409
        """
        rep, plan = setup_rep_with_published_plan(
            plan_year=2026, rep_overrides={"crd_number": "CRD-C11"})
        # RR rep, excess 0, no products -> required_hours 12; certified 0.
        resp = api.close_plan(plan["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_PLAN_HOURS_UNMET)

        data = validate_success(api.get_firm_element_plan(plan["id"], admin_headers))
        assert data["plan_status"] == "PLAN_PUBLISHED", (
            f"rejected close must leave the plan PLAN_PUBLISHED, "
            f"got {data['plan_status']}")

    def test_close_unpublished_plan_rejected(self, api, admin_headers):
        """PRD §3.6: "a `TrainingAdmin` may close a plan that is
        `PLAN_PUBLISHED` — otherwise `ERR_PLAN_NOT_PUBLISHED`."

        Design: Corner/errors/c_close_unpublished_plan_returns_409
        """
        rep = create_rep(crd_number="CRD-PNP")
        plan = create_plan(rep["id"], rep["version"], plan_year=2026)
        resp = api.close_plan(plan["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_PUBLISHED)


class TestPublishSideEffects:
    def test_publish_creates_single_pending_attestation(self, api, admin_headers):
        """PRD §3.6: "Publishing also stamps `published_at`, recomputes the
        plan's progress hours once, creates the plan's annual attestation in
        `PENDING` with its `rep_id` copied from the plan, and writes a
        `PLAN_PUBLISHED` event."

        Design: Corner/state_machines/c_publish_creates_pending_attestation
        """
        rep = create_rep(crd_number="CRD-C12")
        plan = create_plan_with_needs_analysis(
            rep["id"], rep["version"], plan_year=2026)
        get_success_data(api.publish_plan(plan["id"], admin_headers))

        data, meta = validate_paginated(
            api.list_attestations(admin_headers, params={"plan_id": plan["id"]}))
        assert len(data) == 1, (
            f"publish must create exactly one attestation, got {len(data)}")
        assert data[0]["attestation_status"] == "PENDING"
        assert data[0]["rep_id"] == rep["id"], (
            f"attestation rep_id must be copied from the plan, "
            f"got {data[0]['rep_id']}")


class TestAttestationGating:
    def test_attest_requires_plan_closed(self, api, admin_headers):
        """PRD §3.6: "the `RegisteredRep` whose identity matches the plan's
        `rep_id` (otherwise `ERR_OWNERSHIP_REQUIRED`) attests while the
        attestation is `PENDING` (otherwise `ERR_ATTESTATION_NOT_PENDING`) and
        the plan is `CLOSED` (otherwise `ERR_PLAN_NOT_CLOSED`), supplying the
        `attestation_statement`."

        Design: Difficulty/cross_entity_state_dependency/attest_requires_plan_closed
        """
        rep, plan = setup_rep_with_published_plan(
            plan_year=2026, rep_overrides={"crd_number": "CRD-CE2"})
        attestation = get_pending_attestation(plan["id"])
        resp = api.attest(
            attestation["id"],
            {"attestation_statement": "I attest completion of my plan."},
            make_rep_headers(rep["id"]))
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_CLOSED)

    def test_attest_rejected_leaves_attestation_pending(self, api, admin_headers):
        """PRD §3.6: "attests while the attestation is `PENDING` (otherwise
        `ERR_ATTESTATION_NOT_PENDING`) and the plan is `CLOSED` (otherwise
        `ERR_PLAN_NOT_CLOSED`)."

        Design: Difficulty/cross_entity_state_dependency/attest_requires_plan_closed
        """
        rep, plan = setup_rep_with_published_plan(
            plan_year=2026, rep_overrides={"crd_number": "CRD-CE2b"})
        attestation = get_pending_attestation(plan["id"])
        validate_error(
            api.attest(
                attestation["id"],
                {"attestation_statement": "I attest completion of my plan."},
                make_rep_headers(rep["id"])),
            ApiErrorId.ERR_PLAN_NOT_CLOSED)
        data = validate_success(api.get_attestation(attestation["id"], admin_headers))
        assert data["attestation_status"] == "PENDING"


class TestAttestTwice:
    def test_second_attest_rejected(self, api, admin_headers):
        """PRD §3.6: "attests while the attestation is `PENDING` (otherwise
        `ERR_ATTESTATION_NOT_PENDING`)."

        Design: Corner/errors/c_attest_twice_returns_409
        """
        from test_helpers import setup_closed_plan_with_attestation
        rep, plan, attestation, _enr, _content = (
            setup_closed_plan_with_attestation(content_hours=13.0))
        # First attestation is already ATTESTED by the fixture.
        resp = api.attest(
            attestation["id"],
            {"attestation_statement": "I attest again."},
            make_rep_headers(rep["id"]))
        validate_error(resp, ApiErrorId.ERR_ATTESTATION_NOT_PENDING)


class TestPlanYearUniqueness:
    def test_duplicate_plan_year_rejected(self, api, admin_headers):
        """PRD §3.6: "Two plans for the same rep and year cannot both be live:
        if a plan in `NEEDS_ANALYSIS` already exists for the same rep and
        `plan_year`, the new plan supersedes it, moving the old draft to
        `SUPERSEDED`; if instead a `PLAN_PUBLISHED` or `CLOSED` plan already
        exists for that rep and year, the create is rejected with
        `ERR_DUPLICATE_PLAN_YEAR`."

        Design: Corner/validations/c_duplicate_plan_year_returns_409
        """
        rep = create_rep(crd_number="CRD-C22")
        plan = create_published_plan(rep["id"], rep["version"], plan_year=2026)
        rep_now = validate_success(api.get_representative(rep["id"], admin_headers))
        resp = api.create_firm_element_plan(
            {"rep_id": rep["id"], "plan_year": 2026,
             "expected_representative_version": rep_now["version"]},
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PLAN_YEAR)


class TestPlanCreateOcc:
    def test_stale_representative_version_rejected(self, api, admin_headers):
        """PRD §2.7: "A `POST /firm-element-plans` request must carry
        `expected_representative_version` holding the `version` of the target
        representative as the client last observed it. Creating a plan
        supersedes any existing draft for the same rep and year and bumps the
        representative's `version`, so a client holding a stale view must
        re-read before writing: if `expected_representative_version` does not
        match the representative's current `version`, the create is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/c_occ_plan_create_rejects_stale_version
        """
        rep = create_rep(crd_number="CRD-C36")
        stale_version = rep["version"]
        # First plan create succeeds and bumps the rep version.
        create_plan(rep["id"], stale_version, plan_year=2026)
        # Second create with the pre-first-create version must be rejected,
        # even though the payload (a new plan_year) is otherwise legitimate.
        resp = api.create_firm_element_plan(
            {"rep_id": rep["id"], "plan_year": 2027,
             "expected_representative_version": stale_version},
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_fresh_representative_version_accepted(self, api, admin_headers):
        """PRD §2.7: "A `POST /firm-element-plans` request must carry
        `expected_representative_version` holding the `version` of the target
        representative as the client last observed it."

        Design: Corner/cross_cutting_layers/c_occ_plan_create_rejects_stale_version
        """
        rep = create_rep(crd_number="CRD-C36b")
        create_plan(rep["id"], rep["version"], plan_year=2026)
        rep_now = validate_success(api.get_representative(rep["id"], admin_headers))
        plan = create_plan(rep["id"], rep_now["version"], plan_year=2027)
        assert plan["plan_status"] == "NEEDS_ANALYSIS"
