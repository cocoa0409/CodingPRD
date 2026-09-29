"""Certification credit documentation: evidence freshness, the four-step score, submission."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_certification_credit,
    assert_credit_evidence,
    attach_evidence,
    create_credit,
    create_project,
    execute_checklist,
    get_credit,
    get_equipment,
    get_project,
    get_test,
    list_issues,
    project_version,
    record_item,
    record_test_result,
    setup_credit_with_stale_plan_pin,
    setup_frozen_project_with_incomplete_credit,
    setup_gold_credit_on_verified_equipment,
    setup_prefunctional_verified_equipment,
    setup_ready_equipment_on_pinned_plan,
    setup_submitted_gold_credit_with_test_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
    verify_checklist,
)
from test_helpers import CXA, OWNER
from test_helpers import create_issue


class TestCreditLifecycleEntry:
    def test_a_new_credit_starts_not_started_and_the_first_evidence_prepares_it(self, api):
        """PRD §3.8: "A new package sits in `NOT_STARTED` with `evidence_count`,
        `fresh_evidence_count`, `stale_evidence_count`, `completeness_ratio`,
        `documentation_score` and `awarded_points` all 0, `provisional_tier` and
        `final_tier` both `NONE`, and `submitted_at` null."
        PRD §3.8: "Attaching the first evidence row to a package moves it `NOT_STARTED` →
        `IN_PREPARATION`; attaching one to a package that had been withdrawn moves it
        `WITHDRAWN` → `IN_PREPARATION`."
        PRD §3.8: "`documentation_score` starts from 100.0 multiplied by
        `completeness_ratio` multiplied by the quality weight of the **provisional** tier
        just computed — 1.00 for `GOLD`, 0.85 for `SILVER`, 0.60 for `BRONZE` and 0.40 for
        `NONE`."

        Design: Corner/state_machines/new_certification_credit_starts_in_not_started
        """
        project = create_project(name="Initial Cx", building_name="Initial Block")
        unit = setup_prefunctional_verified_equipment(
            project["id"], started_up=False, tag="AHU-IN"
        )
        credit = create_credit(project["id"], 2, 4.0)

        assert_certification_credit(credit)
        assert credit["status"] == "NOT_STARTED"
        assert credit["final_tier"] == "NONE"
        assert credit["documentation_score"] == 0

        attach_evidence(credit["id"], "CHECKLIST", unit["checklist"]["id"])

        after = get_credit(credit["id"])
        assert after["status"] == "IN_PREPARATION"
        assert after["evidence_count"] == 1
        assert after["fresh_evidence_count"] == 1
        assert after["completeness_ratio"] == 0.5
        assert after["provisional_tier"] == "BRONZE"
        assert after["documentation_score"] == 30.00
        assert after["final_tier"] == "NONE"

    def test_evidence_under_an_unknown_credit_is_a_not_found(self, api):
        """PRD §2.5: "Every identifier embedded in the request path resolves to a stored
        row, checked from left to right, answering with the not-found code of the first
        identifier that fails: `ERR_PROJECT_NOT_FOUND`, `ERR_REQUIREMENT_NOT_FOUND`,
        `ERR_PLAN_NOT_FOUND`, `ERR_SUBMITTAL_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_CHECKLIST_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND`,
        `ERR_DEFERRED_TEST_NOT_FOUND`, `ERR_DELIVERABLE_NOT_FOUND`, `ERR_CREDIT_NOT_FOUND`
        or `ERR_BASELINE_NOT_FOUND` (all 404)."

        Design: Corner/entities/credit_evidence_requires_an_existing_parent_credit
        """
        response = api.attach_credit_evidence(
            NON_EXISTENT_UUID,
            {"evidence_type": "CHECKLIST", "evidence_ref_id": NON_EXISTENT_UUID},
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_CREDIT_NOT_FOUND.value, 404)

    def test_evidence_type_and_target_family_must_agree(self, api):
        """PRD §3.8: "The `evidence_type` fixes what the reference means and what "still
        valid" means for it: `EQUIPMENT_VERIFICATION` names an equipment unit,
        `FUNCTIONAL_TEST` names a functional test, `CHECKLIST` names a pre-functional
        checklist, `TRAINING` and `MANUAL_SECTION` both name a closeout deliverable, and
        `ENERGY_BASELINE` names a retro-commissioning measure."
        PRD §3.8: "A reference that does not resolve to a row of the declared family, or
        that resolves to a row belonging to another engagement, is refused with
        `ERR_EVIDENCE_REF_INVALID`."

        Design: Corner/errors/evidence_ref_invalid_when_type_and_target_disagree
        """
        project = create_project(name="RefType Cx", building_name="RefType Block")
        unit = setup_prefunctional_verified_equipment(
            project["id"], started_up=False, tag="AHU-RT"
        )
        credit = create_credit(project["id"], 1, 2.0)

        response = api.attach_credit_evidence(
            credit["id"],
            {
                "evidence_type": "FUNCTIONAL_TEST",
                "evidence_ref_id": unit["checklist"]["id"],
            },
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_EVIDENCE_REF_INVALID.value, 422)

        after = get_credit(credit["id"])
        assert after["status"] == "NOT_STARTED"
        assert after["evidence_count"] == 0

        _, meta = validate_paginated(api.list_credit_evidence(credit["id"], CXA))
        assert meta["total_count"] == 0

    def test_the_evidence_sub_resource_returns_only_its_own_credits_rows(self, api):
        """PRD §3.8: "Evidence is attached one row at a time by a `CxAuthority`, naming an
        `evidence_type` and an `evidence_ref_id`; the stored row records the package it
        documents through its own `credit_id`."
        PRD §3.8: "The credit's `evidence_count` is the number of its evidence rows,
        `fresh_evidence_count` counts those whose `is_stale` is false, and
        `stale_evidence_count` counts those whose `is_stale` is true."

        Design: Corner/endpoints/credit_evidence_subresource_returns_only_that_credits_rows
        """
        project = create_project(name="Evidence Cx", building_name="Evidence Block")
        unit = setup_prefunctional_verified_equipment(
            project["id"], started_up=False, tag="AHU-EV"
        )
        first = create_credit(project["id"], 1, 2.0, credit_code="EA-CX-FUNDAMENTAL")
        second = create_credit(project["id"], 1, 6.0, credit_code="EA-CX-ENHANCED")
        row_one = attach_evidence(first["id"], "CHECKLIST", unit["checklist"]["id"])
        row_two = attach_evidence(second["id"], "CHECKLIST", unit["checklist"]["id"])

        rows, meta = validate_paginated(api.list_credit_evidence(first["id"], OWNER))
        assert len(rows) == 1
        assert rows[0]["id"] == row_one["id"]
        assert rows[0]["credit_id"] == first["id"]
        assert rows[0]["is_stale"] is False
        assert row_two["id"] not in [row["id"] for row in rows]
        assert_credit_evidence(rows[0])

        assert get_credit(first["id"])["evidence_count"] == 1
        assert get_credit(second["id"])["evidence_count"] == 1


class TestFourStepDocumentationScore:
    def test_returning_a_training_deliverable_stales_only_its_own_evidence_row(self, api):
        """PRD §3.7: "It also reaches across into certification documentation: every credit
        evidence row whose `evidence_type` is `TRAINING` or `MANUAL_SECTION` and whose
        `evidence_ref_id` names this deliverable flips `is_stale` to true."
        PRD §3.8: "A row's `is_stale` is true precisely when the referenced artifact is no
        longer in its evidentiary state: an `EQUIPMENT_VERIFICATION` row is stale unless the
        unit's `verification_status` is one of `PREFUNCTIONAL_VERIFIED`,
        `FUNCTIONAL_ACCEPTED` or `CONDITIONALLY_ACCEPTED`; a `FUNCTIONAL_TEST` row is stale
        unless the test's `status` is `PASSED` or `PASSED_WITH_EXCEPTIONS`; a `CHECKLIST`
        row is stale unless the checklist's `status` is `VERIFIED`; a `TRAINING` row and a
        `MANUAL_SECTION` row are each stale unless the deliverable's `status` is `ACCEPTED`;
        and an `ENERGY_BASELINE` row is stale unless the measure's `status` is `CERTIFIED`."
        PRD §3.7: "It moves the row `DELIVERED` -> `RETURNED` and clears
        `delivered_by_user_id` so that the next delivery is judged on its own actor."
        PRD §3.7: "`ACCEPTED` is terminal." — so the returned deliverable is the one still
        sitting in `DELIVERED`; the accepted manual section beside it keeps its row fresh.

        Design: Difficulty/combinatorial_formula/credit_documentation_score_single_pass_tier_evaluation_order
        """
        setup = setup_gold_credit_on_verified_equipment(
            project_overrides={
                "name": "Riverside Cx",
                "building_name": "Riverside Labs",
                "certification_target": "STANDARD",
            },
            equipment_overrides={"tag": "AHU-2"},
            required_evidence_count=4,
            max_points=6.0,
            credit_code="EA-CX-FUNDAMENTAL",
            started_up=False,
            accept_training=False,
        )
        assert setup["training_deliverable"]["status"] == "DELIVERED"

        validate_success(
            api.return_closeout_deliverable(
                setup["training_deliverable"]["id"],
                {"reason": "Attendance roster unsigned"},
                CXA,
            ),
            200,
        )

        rows, _ = validate_paginated(
            api.list_credit_evidence(setup["credit"]["id"], CXA)
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id[setup["evidence_training"]["id"]]["is_stale"] is True
        assert by_id[setup["evidence_equipment"]["id"]]["is_stale"] is False
        assert by_id[setup["evidence_checklist"]["id"]]["is_stale"] is False
        assert by_id[setup["evidence_manual"]["id"]]["is_stale"] is False

        credit = get_credit(setup["credit"]["id"])
        assert credit["fresh_evidence_count"] == 3
        assert credit["stale_evidence_count"] == 1

    def test_the_score_uses_the_provisional_tier_weight_in_a_single_pass(self, api):
        """PRD §3.8: "The evaluation order is pinned to exactly four steps, executed once,
        top to bottom, with no iteration and no search for a fixed point. `final_tier` is
        derived from `documentation_score` and is **never** fed back into it."
        PRD §3.8: "`provisional_tier` is `GOLD` when `completeness_ratio` is at least 1.00,
        `SILVER` when it is at least 0.75, `BRONZE` when it is at least 0.50, and `NONE`
        otherwise."
        PRD §3.8: "From that product a flat penalty of 15.00 points is subtracted for
        **each** stale evidence row the credit holds."
        PRD §3.8: "`final_tier` is `GOLD` when `documentation_score` is at least 90.00,
        `SILVER` when it is at least 70.00, `BRONZE` when it is at least 50.00, and `NONE`
        otherwise."
        PRD §3.5: "a blocking issue demotes its equipment and stales that equipment's
        verification evidence"
        PRD §3.4: "When a blocking issue attaches to a unit that is sitting in
        `PREFUNCTIONAL_VERIFIED`, `FUNCTIONAL_ACCEPTED` or `CONDITIONALLY_ACCEPTED`, that
        unit is demoted to `UNVERIFIED` and every `EQUIPMENT_VERIFICATION` evidence row
        whose `evidence_ref_id` names it flips `is_stale` to true and stamps `staled_at`."

        Design: Difficulty/combinatorial_formula/credit_documentation_score_single_pass_tier_evaluation_order
        """
        setup = setup_gold_credit_on_verified_equipment(
            project_overrides={
                "name": "Riverside Cx",
                "building_name": "Riverside Labs",
                "certification_target": "STANDARD",
            },
            equipment_overrides={"tag": "AHU-2"},
            required_evidence_count=4,
            max_points=6.0,
            credit_code="EA-CX-FUNDAMENTAL",
            started_up=False,
        )
        assert setup["credit"]["documentation_score"] == 100.00
        assert setup["credit"]["final_tier"] == "GOLD"

        # One blocking (S2) deficiency on the unit stales exactly one of the four rows:
        # the EQUIPMENT_VERIFICATION row.  The checklist stays VERIFIED and both
        # deliverables stay ACCEPTED, so their rows stay fresh.
        create_issue(
            setup["project"]["id"],
            "S2",
            origin="DESIGN_REVIEW",
            description="Isolation damper linkage disconnected",
            equipment_id=setup["equipment"]["id"],
        )

        rows, _ = validate_paginated(
            api.list_credit_evidence(setup["credit"]["id"], CXA)
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id[setup["evidence_equipment"]["id"]]["is_stale"] is True
        assert by_id[setup["evidence_checklist"]["id"]]["is_stale"] is False
        assert by_id[setup["evidence_manual"]["id"]]["is_stale"] is False
        assert by_id[setup["evidence_training"]["id"]]["is_stale"] is False

        credit = get_credit(setup["credit"]["id"])
        assert credit["completeness_ratio"] == 0.75
        assert credit["provisional_tier"] == "SILVER"
        assert credit["documentation_score"] == 48.75, (
            "100.0 * 0.75 * 0.85 minus one 15.00 stale penalty"
        )
        assert credit["final_tier"] == "NONE"
        assert credit["status"] == "IN_PREPARATION"

    def test_evidence_freshness_moves_back_when_the_artifact_is_restored(self, api):
        """PRD §3.8: "The whole four-step pass reruns whenever an evidence row is added to
        the credit and whenever any of its evidence rows flips `is_stale` in either
        direction."
        PRD §3.8: "When `required_evidence_count` is 0, `completeness_ratio` is 0.0 — a
        credit demanding no evidence scores nothing rather than everything. Otherwise
        `completeness_ratio` is the fresh evidence count divided by the required evidence
        count, capped at 1.0, rounded half up to four decimal places. Stale rows never count
        toward completeness."

        Design: Corner/cross_cutting_complexity_layers/evidence_freshness_reconciles_when_the_artifact_is_restored
        """
        project = create_project(name="Reconcile Cx", building_name="Reconcile Block")
        unit = setup_prefunctional_verified_equipment(
            project["id"], started_up=False, tag="AHU-RC"
        )
        credit = create_credit(project["id"], 1, 2.0)
        evidence = attach_evidence(credit["id"], "CHECKLIST", unit["checklist"]["id"])
        assert evidence["is_stale"] is False

        validate_success(
            api.reject_checklist(
                unit["checklist"]["id"], {"reason": "Filter media wrong grade"}, CXA
            ),
            200,
        )
        stale_credit = get_credit(credit["id"])
        assert stale_credit["fresh_evidence_count"] == 0
        assert stale_credit["documentation_score"] == 0.00
        assert stale_credit["final_tier"] == "NONE"

        record_item(unit["checklist"]["id"], item_code="PFC-01", result="PASS")
        execute_checklist(unit["checklist"]["id"])
        verify_checklist(unit["checklist"]["id"])

        rows, _ = validate_paginated(api.list_credit_evidence(credit["id"], CXA))
        assert rows[0]["id"] == evidence["id"]
        assert rows[0]["is_stale"] is False

        restored = get_credit(credit["id"])
        assert restored["fresh_evidence_count"] == 1
        assert restored["stale_evidence_count"] == 0
        assert restored["documentation_score"] == 100.00
        assert restored["final_tier"] == "GOLD"
        assert get_project(project["id"])["verified_prefunctional_units"] == 10


class TestSubmissionGates:
    def test_insufficient_fresh_evidence_blocks_submission(self, api):
        """PRD §3.8: "Submission is the `CxAuthority`'s, and it is the most heavily gated
        write in the system. The package must be `IN_PREPARATION`; the engagement's posture
        must not be `FROZEN`; the engagement's newest commissioning plan must be `APPROVED`
        with `pin_stale` false, failing with `ERR_PLAN_NOT_APPROVED` and
        `ERR_PLAN_PIN_STALE` respectively; `fresh_evidence_count` must be at least
        `required_evidence_count`, failing with `ERR_EVIDENCE_INSUFFICIENT`; and the caller
        must present `expected_project_version` matching the engagement's current `version`
        as described in Section 2.9."

        Design: Corner/errors/insufficient_fresh_evidence_blocks_credit_submission
        """
        setup = setup_ready_equipment_on_pinned_plan(
            project_overrides={
                "name": "Insufficient Cx",
                "building_name": "Insufficient Block",
                "certification_target": "STANDARD",
            },
            equipment_overrides={"tag": "AHU-IS"},
            started_up=False,
        )
        credit = create_credit(
            setup["project"]["id"], 3, 6.0, credit_code="EA-CX-ENHANCED"
        )
        attach_evidence(credit["id"], "CHECKLIST", setup["checklist"]["id"])

        response = api.submit_certification_credit(
            credit["id"],
            {"expected_project_version": project_version(setup["project"]["id"])},
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_EVIDENCE_INSUFFICIENT.value, 422)

        after = get_credit(credit["id"])
        assert after["status"] == "IN_PREPARATION"
        assert after["submitted_at"] is None
        assert after["fresh_evidence_count"] == 1
        assert after["completeness_ratio"] == 0.3333
        assert after["provisional_tier"] == "NONE"
        assert after["documentation_score"] == 13.33

    def test_submission_rejects_a_stale_engagement_version(self, api):
        """PRD §2.9: "Submission snapshots the evidence posture of the whole engagement;
        when the engagement's `version` has advanced since the client read it, because a
        cascade staled evidence, a deficiency was logged or the posture moved, the
        submission is built on a view that no longer holds and is rejected with
        `ERR_STALE_PROJECT_VERSION` and HTTP 412."
        PRD §3.8: "A successful submission moves the package `IN_PREPARATION` →
        `SUBMITTED`, stamps `submitted_at` from the logical clock and increments the
        engagement's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/stale_project_version_blocks_credit_submission
        """
        setup = setup_ready_equipment_on_pinned_plan(
            project_overrides={
                "name": "OCC Credit Cx",
                "building_name": "OCC Credit Block",
                "certification_target": "STANDARD",
            },
            equipment_overrides={"tag": "AHU-OC"},
            started_up=False,
        )
        credit = create_credit(
            setup["project"]["id"], 1, 2.0, credit_code="EA-CX-FUNDAMENTAL"
        )
        attach_evidence(credit["id"], "CHECKLIST", setup["checklist"]["id"])

        stale_version = project_version(setup["project"]["id"])
        create_issue(setup["project"]["id"], "S4", description="Punchlist note")

        stale = api.submit_certification_credit(
            credit["id"], {"expected_project_version": stale_version}, CXA
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, 412)

        current_version = project_version(setup["project"]["id"])
        assert current_version > stale_version

        submitted = validate_success(
            api.submit_certification_credit(
                credit["id"], {"expected_project_version": current_version}, CXA
            ),
            200,
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] is not None

        after = get_credit(credit["id"])
        assert after["completeness_ratio"] == 1.0
        assert after["final_tier"] == "GOLD"

    def test_frozen_posture_is_reported_ahead_of_insufficient_evidence(self, api):
        """PRD §2.5: "The engagement's `readiness_posture` is not `FROZEN` — otherwise
        `ERR_PROJECT_FROZEN` (409). This guards phase advance, acceptance issuance, deferred
        test scheduling, closeout deliverable acceptance and certification credit submission
        — five operations."
        PRD §2.5: "`fresh_evidence_count` is greater than or equal to
        `required_evidence_count` — otherwise `ERR_EVIDENCE_INSUFFICIENT` (422). Only
        certification credit submission is guarded."

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_outranks_insufficient_evidence_on_credit_submit
        """
        setup = setup_frozen_project_with_incomplete_credit()
        assert setup["frozen_project"]["readiness_posture"] == "FROZEN"
        assert setup["frozen_project"]["issue_severity_index"] == 50.00
        assert setup["credit"]["fresh_evidence_count"] == 1
        assert setup["credit"]["required_evidence_count"] == 4

        response = api.submit_certification_credit(
            setup["credit"]["id"],
            {"expected_project_version": project_version(setup["project"]["id"])},
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_PROJECT_FROZEN.value, 409)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_EVIDENCE_INSUFFICIENT.value
        )

    def test_the_refused_submission_leaves_the_package_untouched(self, api):
        """PRD §2.5: "When a request violates more than one rule, exactly one error is
        returned and no side effect of any kind is written."
        PRD §2.7: "The **base** is the equipment unit's `contract_value_cents` when the
        issue names an `equipment_id`, and the engagement's own `contract_value_cents` when
        it does not."

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_outranks_insufficient_evidence_on_credit_submit
        """
        setup = setup_frozen_project_with_incomplete_credit()

        api.submit_certification_credit(
            setup["credit"]["id"],
            {"expected_project_version": project_version(setup["project"]["id"])},
            CXA,
        )

        credit = get_credit(setup["credit"]["id"])
        assert credit["status"] == "IN_PREPARATION"
        assert credit["submitted_at"] is None

        assert setup["issue"]["retainage_hold_cents"] == 5_000_000, (
            "a project-wide S1 uses the engagement contract value and the STANDARD factor"
        )
        assert get_project(setup["project"]["id"])["retainage_withheld_cents"] == 5_000_000

    def test_revising_a_pinned_requirement_flips_the_plan_pin_stale(self, api):
        """PRD §3.1: "Crucially, the revision reaches sideways: every commissioning plan of
        the engagement whose `pinned_requirement_ids` array contains the superseded
        predecessor has its `pin_stale` flag set to true."
        PRD §3.1: "That flag is the tripwire that later stops a certification package from
        being submitted against a requirement set the owner has already moved on from."

        Design: Difficulty/cross_entity_state_dependency/credit_submit_blocked_when_plan_pin_goes_stale
        """
        setup = setup_credit_with_stale_plan_pin()

        assert setup["plan"]["pin_stale"] is False
        assert setup["plan"]["pinned_requirement_count"] == 1
        assert setup["revision"]["revision"] == 2
        assert setup["revision"]["supersedes_requirement_id"] == setup["requirement"]["id"]

        predecessor = validate_success(
            api.get_owner_requirement(setup["requirement"]["id"], CXA), 200
        )
        assert predecessor["status"] == "SUPERSEDED"

        plan = validate_success(api.get_cx_plan(setup["plan"]["id"], CXA), 200)
        assert plan["pin_stale"] is True
        assert plan["status"] == "APPROVED"

    def test_a_stale_plan_pin_blocks_the_credit_submission(self, api):
        """PRD §2.5: "The engagement's newest commissioning plan has `pin_stale` false —
        otherwise `ERR_PLAN_PIN_STALE` (409). Only certification credit submission is
        guarded."
        PRD §3.8: "Submission is the `CxAuthority`'s, and it is the most heavily gated write
        in the system. The package must be `IN_PREPARATION`; the engagement's posture must
        not be `FROZEN`; the engagement's newest commissioning plan must be `APPROVED` with
        `pin_stale` false, failing with `ERR_PLAN_NOT_APPROVED` and `ERR_PLAN_PIN_STALE`
        respectively; `fresh_evidence_count` must be at least `required_evidence_count`,
        failing with `ERR_EVIDENCE_INSUFFICIENT`; and the caller must present
        `expected_project_version` matching the engagement's current `version` as described
        in Section 2.9."

        Design: Difficulty/cross_entity_state_dependency/credit_submit_blocked_when_plan_pin_goes_stale
        """
        setup = setup_credit_with_stale_plan_pin()
        assert setup["credit"]["fresh_evidence_count"] == 1
        assert get_project(setup["project"]["id"])["readiness_posture"] == "OPEN"

        response = api.submit_certification_credit(
            setup["credit"]["id"],
            {"expected_project_version": project_version(setup["project"]["id"])},
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_PLAN_PIN_STALE.value, 409)

        credit = get_credit(setup["credit"]["id"])
        assert credit["status"] == "IN_PREPARATION"
        assert credit["fresh_evidence_count"] == 1


class TestFailedTestCascadeIntoCredits:
    def test_the_failure_opens_a_blocking_deficiency_and_demotes_the_unit(self, api):
        """PRD §3.4: "**First**, the test is written to `FAILED` and an issue is opened with
        `origin` `FUNCTIONAL`, the test's equipment as `equipment_id`, `source_ref_id`
        pointing at the test, `opened_by_user_id` of `SYSTEM`, and a `severity` taken from
        the equipment's own `criticality`: `LIFE_SAFETY` equipment yields `S1`, `CRITICAL`
        equipment yields `S2` and `STANDARD` equipment yields `S3`."
        PRD §3.4: "**Second**, when that issue's severity makes `blocks_acceptance` true —
        that is, when it came out `S1` or `S2` — the unit's `blocking_issue_count` increments
        and its verification dimension is demoted to `UNVERIFIED`."

        Design: Difficulty/transitive_cascade/failed_functional_test_cascades_to_certification_credit_withdrawal
        """
        setup = setup_submitted_gold_credit_with_test_in_progress()
        assert setup["submitted_credit"]["status"] == "SUBMITTED"
        assert setup["submitted_credit"]["final_tier"] == "GOLD"
        assert setup["submitted_credit"]["documentation_score"] == 100.00

        completed = record_test_result(setup["test"]["id"], 8_000)
        assert completed["status"] == "FAILED"
        assert completed["outcome_deviation_pct"] == 20.00

        rows, meta = list_issues(
            equipment_id=setup["equipment"]["id"], origin="FUNCTIONAL"
        )
        assert meta["total_count"] == 1
        assert rows[0]["severity"] == "S1"
        assert rows[0]["status"] == "OPEN"
        assert rows[0]["retainage_hold_cents"] == 75_000

        equipment = get_equipment(setup["equipment"]["id"])
        assert equipment["verification_status"] == "UNVERIFIED"
        assert equipment["blocking_issue_count"] == 1

        project = get_project(setup["project"]["id"])
        assert project["retainage_withheld_cents"] == 75_000
        assert project["issue_severity_index"] == 50.00
        assert project["readiness_posture"] == "FROZEN"

    def test_the_demotion_stales_the_evidence_and_withdraws_the_submitted_credit(self, api):
        """PRD §3.4: "**Third**, because the unit has left its verified states, every
        `EQUIPMENT_VERIFICATION` evidence row whose `evidence_ref_id` names that unit flips
        `is_stale` to true and stamps `staled_at`, and every certification credit holding
        such a row recomputes its `completeness_ratio`, `provisional_tier`,
        `documentation_score` and `final_tier`."
        PRD §3.4: "**Fourth**, any credit whose recomputed `final_tier` has fallen to `NONE`
        while its `status` was `SUBMITTED` is moved `SUBMITTED` → `WITHDRAWN` and the
        engagement's `withdrawn_credit_count` increments by one."

        Design: Difficulty/transitive_cascade/failed_functional_test_cascades_to_certification_credit_withdrawal
        """
        setup = setup_submitted_gold_credit_with_test_in_progress()
        record_test_result(setup["test"]["id"], 8_000)

        rows, _ = validate_paginated(
            api.list_credit_evidence(setup["credit"]["id"], CXA)
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id[setup["evidence_equipment"]["id"]]["is_stale"] is True
        assert by_id[setup["evidence_checklist"]["id"]]["is_stale"] is False
        assert by_id[setup["evidence_manual"]["id"]]["is_stale"] is False
        assert by_id[setup["evidence_training"]["id"]]["is_stale"] is False

        credit = get_credit(setup["credit"]["id"])
        assert credit["completeness_ratio"] == 0.75
        assert credit["provisional_tier"] == "SILVER"
        assert credit["documentation_score"] == 48.75
        assert credit["final_tier"] == "NONE"
        assert credit["status"] == "WITHDRAWN"

        assert get_project(setup["project"]["id"])["withdrawn_credit_count"] == 1
        assert get_test(setup["test"]["id"])["status"] == "FAILED"
