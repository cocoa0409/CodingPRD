"""Reads, partial writes and action routes: what each endpoint touches and what it leaves alone."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    UNKNOWN_ID,
    ApiErrorId,
    assert_bay_ledger,
    assert_money,
    assert_project_state,
    assert_skid_state,
    factories,
    fixtures,
    make_application_engineer_headers,
    make_commissioning_engineer_headers,
    make_contracts_administrator_headers,
    make_fabrication_manager_headers,
    make_owner_representative_headers,
    make_quality_engineer_headers,
)

DEMO_WINDOW_START = "2026-08-20T00:00:00.000Z"
DEMO_WINDOW_END = "2026-08-27T00:00:00.000Z"


class TestPartialPackageWrite:
    """A PATCH overwrites what it names, keeps what it omits, and reprices."""

    def test_patching_the_pressure_and_tag_reprices_and_preserves_the_rest(self, api):
        """Raising the pressure to 300 psig lands on 272,064,000 cents and keeps the material.

        The PRD says "a `DRAFT` package may be revised by the same role, supplying any
        subset of `material_spec_id`, `tag_number`, `design_pressure_psig` and
        `design_temp_c`; whichever fields are omitted keep their stored values, the
        supplied ones overwrite, `budgetary_cost_cents` is re-derived, and the package's
        `version` advances by 1." The re-derivation "multiplies the base by a nominal
        material factor of exactly 1.0 — the material is not yet committed, so the
        selected material's `cost_index` is deliberately ignored — then by the pressure
        uplift, then by the code-stamp surcharge, and rounds the product half up to whole
        cents exactly once, at the end."

        Design: Corner/endpoints/patch_reprices_the_package_and_leaves_omitted_fields_alone
        """
        state = fixtures.scoped_single_stage_project(api)
        package = fixtures.add_draft_package(
            api,
            state["filtration_stage"]["id"],
            state["material_spec"]["id"],
            tag_number="F-100",
            design_pressure_psig=150,
            design_temp_c=30.0,
        )
        assert_money(
            package["budgetary_cost_cents"], 260832000, "budgetary_cost_cents"
        )

        revised = validate_success(
            api.update_equipment_package(
                package["id"],
                {"tag_number": "F-101", "design_pressure_psig": 300},
                make_application_engineer_headers(),
            )
        )

        assert revised["tag_number"] == "F-101"
        assert revised["design_pressure_psig"] == 300
        assert revised["design_temp_c"] == 30.0
        assert revised["material_spec_id"] == state["material_spec"]["id"]
        assert_money(
            revised["budgetary_cost_cents"], 272064000, "budgetary_cost_cents"
        )
        assert_money(revised["firm_cost_cents"], 0, "firm_cost_cents")
        assert revised["cost_variance_pct"] == 0
        assert revised["variance_flag"] is False
        assert revised["status"] == "DRAFT"
        assert revised["revision_round"] == 0
        assert revised["version"] == 2


class TestQaRejectionBranch:
    """The rejecting branch of the QA route writes the audit trail but no design basis."""

    def test_a_rejected_sample_never_becomes_the_governing_profile(self, api):
        """The profile records its rejection while the project keeps a null governing sample.

        A rejection is one of the two branches: "either `ACCEPT`, which moves the profile
        `SUBMITTED → ACCEPTED`, or `REJECT`, which moves it `SUBMITTED → REJECTED` —
        together with an optional `qa_note`. Both outcomes store the acting operator's
        identifier as `qa_decided_by_user_id`, store the note, and advance the profile's
        `version` by 1." Re-derivation is asymmetric: "on a rejection, the re-derivation
        matters only when the rejected sample was the governing one".

        Design: Corner/endpoints/profile_rejection_leaves_the_project_without_a_governing_profile
        """
        project = fixtures.create_draft_project(api)
        profile = fixtures.add_influent_profile(api, project["id"])

        decided = validate_success(
            api.decide_influent_profile_qa(
                profile["id"],
                {"decision": "REJECT", "qa_note": "Chloride spike unrepresentative"},
                make_quality_engineer_headers(),
            )
        )

        assert decided["qa_status"] == "REJECTED"
        assert decided["qa_decided_by_user_id"] == "qa-1"
        assert decided["qa_note"] == "Chloride spike unrepresentative"
        assert decided["version"] == 2

        stored = validate_success(
            api.get_project(project["id"], make_contracts_administrator_headers())
        )
        assert stored["governing_influent_profile_id"] is None
        assert_project_state(stored, status="DRAFT")


class TestBodyReferenceResolution:
    """A route that links two rows resolves both before it evaluates anything."""

    def test_booking_against_an_unknown_bay_never_reaches_the_occupancy_ladder(
        self, api
    ):
        """The unresolvable bay identifier is a catalog reference failure, not a bay conflict.

        Section 2.9 says the catalog reads "report an unresolvable identifier as
        `ERR_CATALOG_REF_NOT_FOUND` (HTTP 404), and so does any foreign key supplied in a
        *request body* — `material_spec_id`, `skid_id`, `test_bay_id` or `project_id` —
        that does not resolve to a live row." Only a resolved booking reaches occupancy,
        which "is then evaluated over a **buffered half-open interval**".

        Design: Corner/endpoints/fat_run_against_an_unknown_test_bay_is_not_found
        """
        state = fixtures.fat_ready_single_stage_project(api)
        skid = fixtures.current_skid(api, state["skid"]["id"])

        response = api.create_fat_run(
            factories.fat_run_payload(skid["id"], UNKNOWN_ID, skid["version"]),
            make_fabrication_manager_headers(),
        )

        validate_error(response, ApiErrorId.CATALOG_REF_NOT_FOUND.value, 404)

        bay = validate_success(
            api.get_test_bay(
                state["test_bay"]["id"], make_fabrication_manager_headers()
            )
        )
        assert_bay_ledger(bay, 0)
        assert skid["fat_readiness"] == "READY"

        _, meta = validate_paginated(
            api.list_fat_runs(
                make_fabrication_manager_headers(), {"skid_id": skid["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestComputedReads:
    """A read returns the derived state the writes already stored."""

    def test_the_submittal_read_exposes_the_score_maintained_as_deviations_were_filed(
        self, api
    ):
        """One MAJOR and one MINOR objection leave a stored score of 83.00 on a DRAFT submittal.

        Severity weights are pinned as "2 points for `MINOR`, 6 for `MODERATE`, 15 for
        `MAJOR` and 30 for `FUNDAMENTAL`", and "a `PENDING` deviation counts at full
        weight". The submittal's "`compliance_score` is 100 minus that total, rounded half
        up to two decimal places, and floored at 0 so it never goes negative", while
        "`open_fundamental_count` is the number of child deviations whose `severity` is
        `FUNDAMENTAL` and whose `disposition` is either `PENDING` or `REJECTED`".

        Design: Corner/endpoints/submittal_read_exposes_the_weighted_score_and_the_fundamental_counter
        """
        state = fixtures.scoped_single_stage_project(api)
        submittal = fixtures.add_submittal(api, state["project"]["id"])
        major = fixtures.add_deviation(
            api, submittal["id"], "MAJOR", spec_paragraph="2.03.B"
        )
        minor = fixtures.add_deviation(
            api, submittal["id"], "MINOR", spec_paragraph="2.05.C"
        )

        stored = validate_success(
            api.get_or_equal_submittal(
                submittal["id"], make_application_engineer_headers()
            )
        )

        assert stored["compliance_score"] == 83.00
        assert stored["open_fundamental_count"] == 0
        assert stored["status"] == "DRAFT"
        assert stored["submitted_at"] is None
        assert stored["revision_round"] == 0

        assert major["weighted_penalty_points"] == 15.00
        assert minor["weighted_penalty_points"] == 2.00

    def test_the_package_list_filters_on_status_across_the_whole_train(self, api):
        """Of two packages on two stages only the DRAFT disinfection row comes back.

        Section 2.3 says collections "accept optional filter parameters, all of which
        narrow the result set by exact match and combine conjunctively when more than one
        is supplied", and that "equipment packages filter on `treatment_stage_id`,
        `material_spec_id` and `status`." The returned row prices itself with the surcharge
        table: "the **code-stamp surcharge** is one plus the stamp's premium: nothing for
        `NONE`, four percent for `AWWA`, six percent for `NSF61`, and eleven and a half
        percent for `ASME_U`."

        Design: Corner/endpoints/package_list_filters_on_status_across_both_stages
        """
        state = fixtures.scoped_two_stage_project(api)
        filtration = fixtures.add_draft_package(
            api,
            state["filtration_stage"]["id"],
            state["material_spec"]["id"],
            tag_number="F-100",
            design_pressure_psig=150,
        )
        approved = fixtures.approve_package(api, filtration["id"])
        disinfection = fixtures.add_draft_package(
            api,
            state["disinfection_stage"]["id"],
            state["material_spec"]["id"],
            tag_number="D-200",
            design_pressure_psig=100,
        )

        rows, meta = validate_paginated(
            api.list_equipment_packages(
                make_application_engineer_headers(), {"status": "DRAFT"}
            )
        )

        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == disinfection["id"]
        assert rows[0]["code_stamp_required"] == "NONE"
        assert_money(rows[0]["budgetary_cost_cents"], 74160000, "budgetary_cost_cents")
        assert approved["status"] == "APPROVED"


class TestConditionalActionRoutes:
    """An action route that refuses because the row has already moved on."""

    def test_cancelling_a_passed_run_is_refused_and_the_ledger_is_not_double_released(
        self, api
    ):
        """A run that has already been witnessed cannot be cancelled a second time.

        The PRD says a `FabricationManager` "cancels a `SCHEDULED` run with an optional
        `cancel_reason`, moving it `SCHEDULED → CANCELLED` and subtracting exactly the
        footprint-minutes the booking added ... `PASSED`, `FAILED`, `CONDITIONAL`,
        `CANCELLED` and `SUPERSEDED` are all terminal for a run, and a run in any of them
        can be neither witnessed nor cancelled."

        Design: Corner/endpoints/cancel_on_an_already_witnessed_fat_run_is_rejected
        """
        state = fixtures.scheduled_fat_run_project(api)
        fixtures.witness_run(api, state["fat_run"]["id"], "PASS", 0)

        response = api.cancel_fat_run(
            state["fat_run"]["id"],
            make_fabrication_manager_headers(),
            {"cancel_reason": "Bay reassigned"},
        )

        validate_error(response, ApiErrorId.FAT_RUN_NOT_SCHEDULED.value, 409)

        run = validate_success(
            api.get_fat_run(
                state["fat_run"]["id"], make_fabrication_manager_headers()
            )
        )
        assert run["status"] == "PASSED"
        assert run["punchlist_item_count"] == 0

        bay = validate_success(
            api.get_test_bay(
                state["test_bay"]["id"], make_fabrication_manager_headers()
            )
        )
        assert_bay_ledger(bay, 0)

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )
        assert package["status"] == "FAT_PASSED"

        project = validate_success(
            api.get_project(
                state["project"]["id"], make_contracts_administrator_headers()
            )
        )
        assert_project_state(project, status="COMMISSIONING")

    def test_a_demo_recorded_while_the_shop_is_still_building_is_refused(self, api):
        """With zero completed rounds the refusal is the prerequisite, not the round cap.

        The PRD says "only then is the prerequisite checked: the project must be in
        `COMMISSIONING`, the referenced skid's equipment package must be in `FAT_PASSED`
        or `SHIPPED`, and the skid must belong to the same project — any shortfall is
        `ERR_GUARANTEE_PREREQ_NOT_MET`."

        Design: Corner/endpoints/demo_recorded_before_fabrication_completes_is_rejected
        """
        state = fixtures.fat_ready_single_stage_project(api)

        response = api.create_performance_demo(
            factories.performance_demo_payload(
                state["project"]["id"],
                state["skid"]["id"],
                [{"parameter": "TURBIDITY_NTU", "measured_value": 0.250}],
                DEMO_WINDOW_START,
                DEMO_WINDOW_END,
            ),
            make_commissioning_engineer_headers(),
        )

        validate_error(response, ApiErrorId.GUARANTEE_PREREQ_NOT_MET.value, 422)

        project = validate_success(
            api.get_project(
                state["project"]["id"], make_contracts_administrator_headers()
            )
        )
        assert_project_state(project, status="IN_FABRICATION")
        assert project["guarantee_status"] != "MET"

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )
        assert package["status"] == "RELEASED_FOR_FAB"

        _, meta = validate_paginated(
            api.list_performance_demos(
                make_commissioning_engineer_headers(),
                {"project_id": state["project"]["id"]},
            )
        )
        assert meta["total_count"] == 0


class TestDeliverableAcceptance:
    """Three independent fields, and only acceptance is closed to further decisions."""

    def test_a_rejected_deliverable_can_still_be_accepted_later(self, api):
        """The O&M manual walks PENDING to REJECTED to ACCEPTED while the other two wait.

        The PRD says "an `ACCEPT` writes the addressed field to `ACCEPTED`; a `REJECT`
        writes it to `REJECTED`, from which it can be accepted later. A deliverable that
        is already `ACCEPTED` is closed to further decisions in either direction and the
        request is refused with `ERR_DELIVERABLE_ALREADY_ACCEPTED`: acceptance is not
        revocable." Also: "this operation reads no project lifecycle state, so a
        deliverable can be dispositioned at any point in the project's life."

        Design: Corner/endpoints/rejected_deliverable_can_be_accepted_on_a_second_pass
        """
        project = fixtures.create_draft_project(api)
        rejected = validate_success(
            api.accept_deliverable(
                project["id"],
                {"deliverable_type": "OM_MANUAL", "decision": "REJECT"},
                make_owner_representative_headers(),
            )
        )
        assert rejected["om_manual_status"] == "REJECTED"

        accepted = validate_success(
            api.accept_deliverable(
                project["id"],
                {"deliverable_type": "OM_MANUAL", "decision": "ACCEPT"},
                make_owner_representative_headers(),
            )
        )

        assert accepted["om_manual_status"] == "ACCEPTED"
        assert accepted["operator_training_status"] == "PENDING"
        assert accepted["spare_parts_list_status"] == "PENDING"
        assert_project_state(accepted, status="DRAFT")


class TestReworkRecovery:
    """Closing the rework cycle, in the declared order of side effects."""

    def _skid_returned_to_mech_complete(self, api):
        state = fixtures.scheduled_fat_run_project(api)
        fixtures.witness_run(api, state["fat_run"]["id"], "FAIL", 7)
        fixtures.advance_dimension(
            api,
            state["skid"]["id"],
            "MECHANICAL",
            ("REWORK", "PIPING_COMPLETE", "HYDROTEST_PASSED"),
        )
        return state

    def test_reaching_mech_complete_lifts_the_hold_before_readiness_is_folded(
        self, api
    ):
        """The package leaves REWORK_HOLD in the same request, so readiness lands on READY.

        The PRD says "when the mechanical axis reaches `MECH_COMPLETE` while the parent
        package is sitting in `REWORK_HOLD`, the package transitions
        `REWORK_HOLD → RELEASED_FOR_FAB`, the project's `delivery_posture` is recomputed,
        and the package's `version` advances by 1." Readiness is the fold that follows:
        "if `mechanical_status` is `MECH_COMPLETE` **and** `controls_status` is
        `CONTROLS_COMPLETE` **and** the parent package's status is `RELEASED_FOR_FAB`,
        readiness is `READY`."

        Design: Corner/endpoints/mech_complete_after_rework_lifts_the_package_hold_before_readiness_is_recomputed
        """
        state = self._skid_returned_to_mech_complete(api)

        skid = validate_success(
            api.record_skid_milestone(
                state["skid"]["id"],
                factories.milestone_payload("MECHANICAL", "MECH_COMPLETE"),
                make_fabrication_manager_headers(),
            )
        )

        assert_skid_state(
            skid,
            mechanical_status="MECH_COMPLETE",
            controls_status="CONTROLS_COMPLETE",
            fat_readiness="READY",
            rework_count=1,
        )

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )
        assert package["status"] == "RELEASED_FOR_FAB"

        run = validate_success(
            api.get_fat_run(
                state["fat_run"]["id"], make_fabrication_manager_headers()
            )
        )
        assert run["status"] == "FAILED"
        assert run["punchlist_item_count"] == 7

        project = validate_success(
            api.get_project(
                state["project"]["id"], make_contracts_administrator_headers()
            )
        )
        assert_project_state(
            project, status="IN_FABRICATION", delivery_posture="AT_RISK"
        )

        bay = validate_success(
            api.get_test_bay(
                state["test_bay"]["id"], make_fabrication_manager_headers()
            )
        )
        assert_bay_ledger(bay, 0)
