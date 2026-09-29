"""Opening an engagement, owner project requirements and the commissioning plan."""

from test_helpers import (
    ApiErrorId,
    assert_cx_project,
    assert_cx_plan,
    assert_owner_requirement,
    create_approved_requirement,
    create_approved_plan,
    create_cx_plan_payload,
    create_cx_project_payload,
    create_issue,
    create_project,
    get_project,
    is_valid_uuid,
    project_version,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ADMIN, CONTRACTOR, CXA, OWNER


class TestEngagementCreation:
    def test_new_engagement_applies_declared_defaults(self, api):
        """PRD §3.1: "Two optional inputs shape later behaviour: `certification_target`
        declares the green-certification package the owner is pursuing and is one of
        `NONE`, `STANDARD` or `ENHANCED`, defaulting to `NONE`; and `witness_capacity`
        declares how many functional performance tests the CxA firm can witness on this
        engagement at one instant, defaulting to 1 and never below 1."
        PRD §3.1: "A freshly opened engagement sits in `delivery_phase` `PLANNING` with
        `readiness_posture` `OPEN`, and every derived roll-up starts at its zero value —
        `issue_severity_index`, `retainage_withheld_cents`, `verified_prefunctional_units`,
        `open_blocking_issue_count`, `acceptance_completion_score`, `withdrawn_credit_count`
        and `total_awarded_points` all read 0, while `final_acceptance_score` and
        `acceptance_kind` are null."
        PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every
        mutation of the row."

        Design: Corner/entities/create_cx_project_applies_declared_defaults
        """
        payload = create_cx_project_payload(
            name="Default Cx",
            building_name="Default Block",
            contract_value_cents=50_000_000,
        )
        response = api.create_cx_project(payload, ADMIN)
        project = validate_success(response, 201)

        assert_cx_project(project)
        assert project["certification_target"] == "NONE"
        assert project["witness_capacity"] == 1
        assert project["delivery_phase"] == "PLANNING"
        assert project["readiness_posture"] == "OPEN"
        assert project["issue_severity_index"] == 0
        assert project["retainage_withheld_cents"] == 0
        assert project["verified_prefunctional_units"] == 0
        assert project["open_blocking_issue_count"] == 0
        assert project["acceptance_completion_score"] == 0
        assert project["withdrawn_credit_count"] == 0
        assert project["total_awarded_points"] == 0
        assert project["final_acceptance_score"] is None
        assert project["acceptance_kind"] is None
        assert project["version"] == 1
        assert is_valid_uuid(project["id"]), "id must be a bare UUID with no type prefix"
        assert not project["id"].startswith("cx_"), "id carries no type prefix"

    def test_reading_an_engagement_echoes_every_stored_field(self, api):
        """PRD §3.1: "The payload carries a `name` for the engagement, a `building_name`
        for the facility it covers, a `project_type` of either `NEW_CONSTRUCTION` or
        `RETRO_COMMISSIONING`, and a `contract_value_cents` giving the total construction
        contract value in cents, which must be at least 1."
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array"
        for a list of resources."

        Design: Corner/entities/get_cx_project_returns_the_stored_row
        """
        created = create_project(
            name="Echo Cx",
            building_name="Echo Hall",
            project_type="RETRO_COMMISSIONING",
            contract_value_cents=50_000_000,
            certification_target="ENHANCED",
            witness_capacity=3,
        )

        response = api.get_cx_project(created["id"], OWNER)
        project = validate_success(response, 200)

        assert response.json()["response_type"] == "object"
        assert project["building_name"] == "Echo Hall"
        assert project["project_type"] == "RETRO_COMMISSIONING"
        assert project["certification_target"] == "ENHANCED"
        assert project["witness_capacity"] == 3
        assert project["contract_value_cents"] == 50_000_000


class TestOwnerRequirements:
    def test_owner_requirement_without_metric_key_is_rejected(self, api):
        """PRD §3.1: "Each line names its engagement through a `project_id`, carries a
        `metric_key` identifying what is being measured (for example `SUPPLY_AIRFLOW_CFM`),
        a `target_value` the owner expects which may not be negative, a `tolerance_pct`
        giving the acceptable deviation band in percent which must be at least 0 and at
        most 100, and a `criticality` of `LIFE_SAFETY`, `CRITICAL` or `STANDARD`."
        PRD §2.5: "The request body carries every required field with a well-formed type,
        every enumerated value is a declared member of its enumeration, every numeric field
        satisfies its declared range constraint, every datetime parses as ISO 8601 UTC, and
        `limit` and `offset` are inside the pagination bounds — otherwise `ERR_VALIDATION`
        (400)."

        Design: Corner/entities/create_owner_requirement_without_metric_key_returns_validation
        """
        project = create_project(name="Missing Field Cx", building_name="MF Block")

        payload = {
            "project_id": project["id"],
            "target_value": 100,
            "tolerance_pct": 5,
            "criticality": "STANDARD",
        }
        response = api.create_owner_requirement(payload, OWNER)
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

        rows, meta = validate_paginated(
            api.list_owner_requirements(CXA, params={"project_id": project["id"]})
        )
        assert meta["total_count"] == 0, "the rejected request wrote no requirement row"

    def test_revision_chain_is_reachable_through_the_supersedes_filter(self, api):
        """PRD §3.1: "Revising an `APPROVED` line moves that line `APPROVED` → `SUPERSEDED`
        and mints a **new** requirement row in `DRAFT` whose `revision` is one greater than
        its predecessor's, whose `supersedes_requirement_id` points at the predecessor, and
        whose `target_value`, `tolerance_pct` and `criticality` come from the revise payload
        while its `project_id` and `metric_key` are inherited."
        PRD §3.1: "The revision chain is walkable by filtering the requirement list on
        `supersedes_requirement_id`, and the list also narrows by `project_id` and by
        `status`."

        Design: Corner/entities/owner_requirement_revision_chain_discoverable_by_supersedes_filter
        """
        project = create_project(name="Revision Cx", building_name="Revision Block")
        original = create_approved_requirement(project["id"])

        revision = validate_success(
            api.revise_owner_requirement(
                original["id"],
                {"target_value": 12_000, "tolerance_pct": 6, "criticality": "STANDARD"},
                OWNER,
            ),
            201,
        )
        assert_owner_requirement(revision)

        rows, meta = validate_paginated(
            api.list_owner_requirements(
                CXA, params={"supersedes_requirement_id": original["id"]}
            )
        )
        assert len(rows) == 1, f"expected exactly the one revision row, got {rows}"
        assert rows[0]["id"] == revision["id"]
        assert revision["revision"] == 2
        assert revision["status"] == "DRAFT"
        assert revision["target_value"] == 12_000
        assert revision["tolerance_pct"] == 6

        predecessor = validate_success(
            api.get_owner_requirement(original["id"], CXA), 200
        )
        assert predecessor["status"] == "SUPERSEDED"


class TestDeliveryPhases:
    def test_phase_advance_accepts_only_the_immediate_next_phase(self, api):
        """PRD §3.1: "Any `target_phase` that skips a phase, repeats the current one, or
        moves backwards is refused with `ERR_PHASE_NOT_ALLOWED`, and `CLOSED` is terminal."
        PRD §3.1: "`PLANNING` → `DESIGN` requires at least one owner requirement of this
        engagement to be `APPROVED`."

        Design: Corner/endpoints/advance_phase_only_accepts_the_immediate_next_phase
        """
        project = create_project(
            name="Phase Cx", building_name="Phase Block", contract_value_cents=50_000_000
        )
        create_approved_requirement(project["id"])

        skipped = api.advance_phase(project["id"], {"target_phase": "CONSTRUCTION"}, CXA)
        validate_error(skipped, ApiErrorId.ERR_PHASE_NOT_ALLOWED.value, 409)

        advanced = validate_success(
            api.advance_phase(project["id"], {"target_phase": "DESIGN"}, CXA), 200
        )
        assert advanced["delivery_phase"] == "DESIGN"
        assert get_project(project["id"])["delivery_phase"] == "DESIGN"


class TestCommissioningPlan:
    def test_new_plan_supersedes_every_prior_plan_of_the_engagement(self, api):
        """PRD §3.1: "On creation, every prior plan of that engagement moves to
        `SUPERSEDED`, whether it was sitting in `DRAFT` or in `APPROVED`; the new plan is
        born `DRAFT` with an empty `pinned_requirement_ids`, a `pinned_requirement_count`
        of 0, `pin_stale` false and `approved_at` null; and the engagement's `version`
        increments by one."

        Design: Corner/cross_cutting_complexity_layers/new_plan_supersedes_the_prior_plan_for_the_same_project
        """
        project = create_project(name="Supersede Cx", building_name="Supersede Block")
        create_approved_requirement(project["id"])
        first = create_approved_plan(project["id"], title="Plan revision 0")
        assert first["status"] == "APPROVED"
        assert first["pinned_requirement_count"] == 1

        second = validate_success(
            api.create_cx_plan(
                create_cx_plan_payload(
                    project["id"], project_version(project["id"]), title="Plan revision 1"
                ),
                CXA,
            ),
            201,
        )
        assert_cx_plan(second)
        assert second["status"] == "DRAFT"
        assert second["pinned_requirement_count"] == 0

        superseded = validate_success(api.get_cx_plan(first["id"], CXA), 200)
        assert superseded["status"] == "SUPERSEDED"

        _, all_meta = validate_paginated(
            api.list_cx_plans(CXA, params={"project_id": project["id"]})
        )
        assert all_meta["total_count"] == 2
        _, approved_meta = validate_paginated(
            api.list_cx_plans(
                CXA, params={"project_id": project["id"], "status": "APPROVED"}
            )
        )
        assert approved_meta["total_count"] == 0

    def test_plan_creation_rejects_a_stale_engagement_version(self, api):
        """PRD §2.9: "If `expected_project_version` does not equal the engagement's current
        `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` and HTTP 412,
        and no plan is created."
        PRD §2.8: "The engagement's `version` deserves particular care because optimistic
        concurrency reads it. It is incremented by one on each of the following: advancing
        the delivery phase; issuing an acceptance certificate; running the seasonal sweep;
        creating a commissioning plan; verifying a pre-functional checklist; rejecting a
        pre-functional checklist; recording a functional test result; logging an issue;
        verifying an issue closure; re-opening an issue; deferring an issue; voiding an
        issue; executing a deferred test; accepting a closeout deliverable; returning a
        closeout deliverable; submitting a certification credit; and adjudicating a
        certification credit."

        Design: Corner/cross_cutting_complexity_layers/stale_project_version_blocks_plan_creation
        """
        project = create_project(name="OCC Plan Cx", building_name="OCC Block")
        stale_version = project["version"]
        create_approved_requirement(project["id"])
        create_issue(
            project["id"], "S4", description="Drawing index missing a sheet"
        )

        stale = api.create_cx_plan(
            create_cx_plan_payload(project["id"], stale_version, title="Stale attempt"),
            CXA,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, 412)

        current_version = project_version(project["id"])
        assert current_version > stale_version

        plan = validate_success(
            api.create_cx_plan(
                create_cx_plan_payload(
                    project["id"], current_version, title="Current attempt"
                ),
                CXA,
            ),
            201,
        )
        assert plan["status"] == "DRAFT"

        _, meta = validate_paginated(
            api.list_cx_plans(CXA, params={"project_id": project["id"]})
        )
        assert meta["total_count"] == 1, "the stale attempt created nothing"
        assert get_project(project["id"])["version"] == current_version + 1

    def test_contractor_may_not_draft_a_commissioning_plan(self, api):
        """PRD §2.1: "A request whose role is recognised but is not listed for the endpoint
        in the Section 4 table is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD §3.1: "**The commissioning plan** is authored by a `CxAuthority` and carries a
        `project_id` and a `title`."

        Design: Corner/rbac/contractor_cannot_create_a_cx_plan
        """
        project = create_project(
            name="RoleDeny Cx",
            building_name="RoleDeny Block",
            contract_value_cents=50_000_000,
        )
        create_approved_requirement(project["id"])
        version_before = project_version(project["id"])

        response = api.create_cx_plan(
            create_cx_plan_payload(
                project["id"], version_before, title="Contractor drafted plan"
            ),
            CONTRACTOR,
        )
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        _, meta = validate_paginated(
            api.list_cx_plans(CXA, params={"project_id": project["id"]})
        )
        assert meta["total_count"] == 0
        assert get_project(project["id"])["version"] == version_before, (
            "a refused request bumps nothing"
        )
