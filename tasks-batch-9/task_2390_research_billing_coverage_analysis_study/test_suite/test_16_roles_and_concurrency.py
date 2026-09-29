"""Who may act, who may not act twice, and the three version guards that make a
stale writer's request fail instead of silently overwriting what it never saw.
"""

from test_helpers import (
    ANALYST_ONE,
    ANALYST_TWO,
    COORDINATOR_ONE,
    MANAGER_ONE,
    MANAGER_TWO,
    REVIEWER_ONE,
    ROLE_REVIEWER,
    api_client,
    build_user_headers,
    budget_build_payload,
    create_charge_payload,
    create_coverage_analysis_payload,
    create_coverage_item_payload,
    create_study_payload,
    determine_qct,
    item_spec,
    make_analyst_headers,
    make_coordinator_headers,
    make_manager_headers,
    make_reviewer_headers,
    qct_determination_payload,
    read_analysis,
    read_study,
    register_study,
    setup_study_with_analysis_under_review,
    setup_study_with_approved_analysis,
    submit_analysis,
    validate_error,
    validate_paginated,
    validate_success,
)

SPONSOR_INFUSION = item_spec(
    "J9999",
    classification="RESEARCH_PAID",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=55000,
    negotiated_unit_cents=40000,
    expected_occurrences=1,
)
ROUTINE_PANEL = item_spec(
    "80053",
    classification="ROUTINE_CARE",
    budget_category="PER_PATIENT",
    medicare_coverage_basis="STANDARD_OF_CARE",
    charge_master_unit_cents=9000,
    negotiated_unit_cents=9000,
    expected_occurrences=3,
)


class TestTheDeterminationBelongsToOneRoleOnly:
    """Reads are shared; this particular write is not."""

    def test_01_the_compliance_reviewer_records_the_medicare_determination(self):
        """The reviewer's identifier is stamped into the study, the reviewer can
        read both the study and the compliance dashboard, and the manager who
        registered the protocol cannot issue the same write.

        PRD §2.1: "The same holds for `CoverageAnalyst`, whose identifier is
        recorded as `prepared_by_user_id` on the analysis it opens; for
        `ComplianceReviewer`, whose identifier is recorded as
        `qct_determined_by_user_id` on a study, as `returned_by_user_id` or
        `approved_by_user_id` on an analysis, and as `reviewed_by_user_id` on a
        charge; for `StudyCoordinator`, whose identifier is recorded as
        `posted_by_user_id` on an interface-posted charge; and for `AuditLiaison`,
        whose identifier is recorded as `opened_by_user_id` and
        `responded_by_user_id` on an audit finding."

        Design: Corner/rbac/compliance_reviewer_performs_its_exclusive_determination
        """
        study = register_study(
            protocol_number="AMC-2390-C60",
            funding_source="INDUSTRY_SPONSORED",
            ind_ide_status="IND_HELD",
            therapeutic_intent=True,
            registry_number="NCT10000160",
        )

        determined = validate_success(
            api_client.record_qct_determination(
                study["id"],
                qct_determination_payload(basis="DEEMED_IND_IDE"),
                make_reviewer_headers(REVIEWER_ONE),
            ),
            200,
        )
        assert determined["qct_determination"] == "DEEMED_QUALIFYING"
        assert determined["qct_basis"] == "DEEMED_IND_IDE"
        assert determined["qct_determined_by_user_id"] == REVIEWER_ONE
        assert determined["billing_hold_posture"] == "OPEN"

        summary = validate_success(
            api_client.get_charge_review_summary(
                study["id"], make_reviewer_headers(REVIEWER_ONE)
            ),
            200,
        )
        assert summary["billing_hold_posture"] == "OPEN"
        # Every read is shared across the five roles.
        as_reviewer = validate_success(
            api_client.get_study(study["id"], make_reviewer_headers(REVIEWER_ONE)), 200
        )
        assert as_reviewer["id"] == study["id"]
        as_coordinator = validate_success(
            api_client.get_study(study["id"], make_coordinator_headers(COORDINATOR_ONE)),
            200,
        )
        assert as_coordinator["id"] == study["id"]

        # The manager registered the protocol and still may not determine it.
        validate_error(
            api_client.record_qct_determination(
                study["id"],
                qct_determination_payload(basis="DEEMED_IND_IDE"),
                make_manager_headers(MANAGER_ONE),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        assert read_study(study["id"])["qct_determined_by_user_id"] == REVIEWER_ONE


class TestApprovalIsNotAvailableToTheOtherRoles:
    """The authorization check runs before any state check."""

    def test_02_neither_the_coordinator_nor_the_preparer_may_approve(self):
        """The analysis is genuinely approvable, which is what makes the 403 an
        authorization answer rather than a state answer.

        PRD §2.1: "When the headers are well formed but the acting role is not
        listed as authorized for the endpoint being called, the rejection is
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/study_coordinator_cannot_approve_a_coverage_analysis
        """
        ctx = setup_study_with_analysis_under_review(
            [ROUTINE_PANEL],
            qct_basis=None,
            study_overrides={"protocol_number": "AMC-2390-C61"},
        )
        analysis_id = ctx["analysis"]["id"]
        assert ctx["analysis"]["status"] == "UNDER_REVIEW"
        assert ctx["analysis"]["version"] == 3

        validate_error(
            api_client.approve_coverage_analysis(
                analysis_id, make_coordinator_headers(COORDINATOR_ONE)
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        # Preparing the grid grants no right to bless it.
        validate_error(
            api_client.approve_coverage_analysis(
                analysis_id, make_analyst_headers(ANALYST_TWO)
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        untouched = read_analysis(analysis_id)
        assert untouched["status"] == "UNDER_REVIEW"
        assert untouched["approved_at"] is None
        assert untouched["approved_by_user_id"] is None
        assert untouched["version"] == 3

        # Posting a charge is the coordinator's exclusive operation, not the
        # manager's.
        validate_error(
            api_client.create_charge(
                create_charge_payload(ctx["study"]["id"]),
                make_manager_headers(MANAGER_ONE),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        _, meta = validate_paginated(
            api_client.list_charges(
                make_manager_headers(MANAGER_ONE),
                params={"study_id": ctx["study"]["id"]},
            )
        )
        assert meta["total_count"] == 0

        approved = validate_success(
            api_client.approve_coverage_analysis(
                analysis_id, make_reviewer_headers(REVIEWER_ONE)
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == REVIEWER_ONE
        assert read_study(ctx["study"]["id"])["lifecycle_status"] == "COVERAGE_APPROVED"


class TestTheSecondSignatureMustBeADifferentPerson:
    """The role is right; only the identifier collides."""

    def test_03_the_builder_may_not_execute_and_the_preparer_may_not_approve(self):
        """Both refusals are 403 on the acting identifier, and in both cases the
        artifact is left exactly where the first signature put it.

        PRD §2.5: "An analysis may not be approved by the user recorded in its
        `prepared_by_user_id`. A built budget may not be executed by the user
        recorded in the study's `budget_built_by_user_id`. An audit finding may not
        be responded to by the user recorded in its `opened_by_user_id`."

        Design: Corner/rbac/budget_executor_cannot_be_the_budget_builder
        """
        ctx = setup_study_with_approved_analysis(
            [SPONSOR_INFUSION],
            qct_basis=None,
            study_overrides={
                "protocol_number": "AMC-2390-C62",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        built = validate_success(
            api_client.build_budget(
                ctx["study"]["id"],
                budget_build_payload(
                    ctx["analysis"]["id"],
                    ctx["study"]["version"],
                    indirect_rate_pct=32.0,
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            200,
        )
        assert built["budget_status"] == "BUILT"
        assert built["budget_built_by_user_id"] == MANAGER_ONE
        assert built["version"] == 4

        validate_error(
            api_client.execute_budget(
                ctx["study"]["id"], make_manager_headers(MANAGER_ONE)
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )
        refused = read_study(ctx["study"]["id"])
        assert refused["budget_status"] == "BUILT"
        assert refused["budget_executed_by_user_id"] is None
        assert refused["version"] == 4

        executed = validate_success(
            api_client.execute_budget(
                ctx["study"]["id"], make_manager_headers(MANAGER_TWO)
            ),
            200,
        )
        assert executed["budget_status"] == "EXECUTED"
        assert executed["budget_executed_by_user_id"] == MANAGER_TWO
        assert executed["version"] == 5

        # The same rule guards the other signature: the reviewer role acting as
        # the analysis' preparer is refused too.
        other = setup_study_with_analysis_under_review(
            [ROUTINE_PANEL],
            qct_basis=None,
            analyst=ANALYST_ONE,
            study_overrides={"protocol_number": "AMC-2390-C62B"},
        )
        assert other["analysis"]["prepared_by_user_id"] == ANALYST_ONE
        validate_error(
            api_client.approve_coverage_analysis(
                other["analysis"]["id"],
                build_user_headers(ANALYST_ONE, ROLE_REVIEWER),
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )
        assert read_analysis(other["analysis"]["id"])["status"] == "UNDER_REVIEW"
        approved = validate_success(
            api_client.approve_coverage_analysis(
                other["analysis"]["id"], make_reviewer_headers(REVIEWER_ONE)
            ),
            200,
        )
        assert approved["status"] == "APPROVED"


class TestTheStudyVersionGuardOnAnalysisCreation:
    """A determination is a write, and it moves the guard the analyst quoted."""

    def test_04_a_stale_study_version_refuses_the_analysis_and_creates_nothing(self):
        """No analysis row is created and the study's lifecycle does not advance;
        re-quoting the current version accepts the identical body.

        PRD §2.6: "Raising a coverage analysis revision requires
        `expected_study_version` in the body, carrying the client's last observed
        `version` of the target study. If that number does not equal the study's
        current `version`, the create is rejected with `ERR_STALE_STUDY_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_study_version_blocks_analysis_creation
        """
        study = register_study(
            protocol_number="AMC-2390-C70",
            funding_source="INDUSTRY_SPONSORED",
            ind_ide_status="IND_HELD",
            therapeutic_intent=True,
            registry_number="NCT10000170",
        )
        assert study["version"] == 1
        after_determination = determine_qct(study["id"], basis="DEEMED_IND_IDE")
        assert after_determination["version"] == 2

        validate_error(
            api_client.create_coverage_analysis(
                create_coverage_analysis_payload(study["id"], 1),
                make_analyst_headers(ANALYST_ONE),
            ),
            "ERR_STALE_STUDY_VERSION",
            412,
        )
        _, meta = validate_paginated(
            api_client.list_coverage_analyses(
                make_analyst_headers(ANALYST_ONE), params={"study_id": study["id"]}
            )
        )
        assert meta["total_count"] == 0
        unmoved = read_study(study["id"])
        assert unmoved["lifecycle_status"] == "DRAFT"
        assert unmoved["version"] == 2

        analysis = validate_success(
            api_client.create_coverage_analysis(
                create_coverage_analysis_payload(study["id"], 2),
                make_analyst_headers(ANALYST_ONE),
            ),
            201,
        )
        assert analysis["revision_number"] == 1
        assert analysis["prepared_by_user_id"] == ANALYST_ONE
        moved = read_study(study["id"])
        assert moved["lifecycle_status"] == "COVERAGE_PENDING"
        assert moved["version"] == 3


class TestTheStudyVersionGuardOnBudgetBuild:
    """Same code, a different endpoint and a different cause of staleness."""

    def test_05_an_approval_in_between_invalidates_the_managers_build(self):
        """The budget figures the manager reasoned about are refused, and the
        budget is still unbuilt afterwards.

        PRD §2.6: "Building a study budget likewise requires
        `expected_study_version` matching the study's current `version`, and a
        mismatch is rejected with `ERR_STALE_STUDY_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_study_version_blocks_budget_build
        """
        study = register_study(
            protocol_number="AMC-2390-C71",
            funding_source="INDUSTRY_SPONSORED",
            ind_ide_status="IND_HELD",
            therapeutic_intent=True,
        )
        analysis = validate_success(
            api_client.create_coverage_analysis(
                create_coverage_analysis_payload(study["id"], study["version"]),
                make_analyst_headers(ANALYST_ONE),
            ),
            201,
        )
        # What the manager read before the reviewer approved anything.
        stale_version = read_study(study["id"])["version"]
        assert stale_version == 2

        validate_success(
            api_client.create_coverage_item(
                create_coverage_item_payload(
                    analysis["id"],
                    analysis["version"],
                    item_code="J9999",
                    description="Investigational infusion",
                    classification="RESEARCH_PAID",
                    medicare_coverage_basis="NOT_COVERED",
                    budget_category="PER_PATIENT",
                    charge_master_unit_cents=55000,
                    negotiated_unit_cents=40000,
                    expected_occurrences=1,
                ),
                make_analyst_headers(ANALYST_ONE),
            ),
            201,
        )
        submit_analysis(analysis["id"])
        validate_success(
            api_client.approve_coverage_analysis(
                analysis["id"], make_reviewer_headers(REVIEWER_ONE)
            ),
            200,
        )

        validate_error(
            api_client.build_budget(
                study["id"],
                budget_build_payload(
                    analysis["id"], stale_version, indirect_rate_pct=32.0
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            "ERR_STALE_STUDY_VERSION",
            412,
        )
        refused = read_study(study["id"])
        assert refused["budget_status"] == "NOT_BUILT"
        assert refused["lifecycle_status"] == "COVERAGE_APPROVED"
        assert refused["version"] == 3

        built = validate_success(
            api_client.build_budget(
                study["id"],
                budget_build_payload(
                    analysis["id"], refused["version"], indirect_rate_pct=32.0
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            200,
        )
        assert built["budget_status"] == "BUILT"
        # 40,000 cents of sponsor-borne work is a small industry study: the
        # surcharge is added first and then capped at 32.0.
        assert built["effective_indirect_rate_pct"] == 32.0
        assert built["per_patient_subtotal_cents"] == 40000
        assert built["per_patient_budget_cents"] == 52800
        assert built["version"] == 4


class TestTheAnalysisVersionGuardOnItemAdd:
    """A different parent entity guards this write, with its own error code."""

    def test_06_the_first_item_makes_the_second_item_s_guard_stale(self):
        """The counters the writer reasoned about are left exactly as they were,
        and no second item lands until the guard is re-quoted.

        PRD §2.6: "Adding an item to a coverage analysis requires
        `expected_coverage_analysis_version` in the body, carrying the client's
        last observed `version` of the owning analysis. If that number does not
        equal the analysis' current `version`, the add is rejected with
        `ERR_STALE_COVERAGE_ANALYSIS_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_analysis_version_blocks_item_add
        """
        study = validate_success(
            api_client.create_study(
                create_study_payload(
                    protocol_number="AMC-2390-C72",
                    funding_source="INDUSTRY_SPONSORED",
                    ind_ide_status="IND_HELD",
                    therapeutic_intent=True,
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            201,
        )
        analysis = validate_success(
            api_client.create_coverage_analysis(
                create_coverage_analysis_payload(study["id"], study["version"]),
                make_analyst_headers(ANALYST_ONE),
            ),
            201,
        )
        assert analysis["version"] == 1

        first_item = validate_success(
            api_client.create_coverage_item(
                create_coverage_item_payload(
                    analysis["id"],
                    1,
                    item_code="80053",
                    description="Comprehensive metabolic panel",
                    classification="ROUTINE_CARE",
                    medicare_coverage_basis="STANDARD_OF_CARE",
                    budget_category="PER_PATIENT",
                    charge_master_unit_cents=9000,
                    negotiated_unit_cents=9000,
                    expected_occurrences=3,
                ),
                make_analyst_headers(ANALYST_ONE),
            ),
            201,
        )
        assert read_analysis(analysis["id"])["version"] == 2

        second_item_body = create_coverage_item_payload(
            analysis["id"],
            1,
            item_code="J9999",
            description="Investigational infusion",
            classification="RESEARCH_PAID",
            medicare_coverage_basis="NOT_COVERED",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=55000,
            negotiated_unit_cents=40000,
            expected_occurrences=1,
        )
        validate_error(
            api_client.create_coverage_item(
                second_item_body, make_analyst_headers(ANALYST_ONE)
            ),
            "ERR_STALE_COVERAGE_ANALYSIS_VERSION",
            412,
        )
        unmoved = read_analysis(analysis["id"])
        assert unmoved["item_count"] == 1
        assert unmoved["routine_care_item_count"] == 1
        assert unmoved["research_paid_item_count"] == 0
        assert unmoved["status"] == "DRAFT"
        assert unmoved["version"] == 2

        rows, meta = validate_paginated(
            api_client.list_coverage_analysis_items(
                analysis["id"], make_analyst_headers(ANALYST_ONE)
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first_item["id"]

        second_item_body["expected_coverage_analysis_version"] = 2
        accepted = validate_success(
            api_client.create_coverage_item(
                second_item_body, make_analyst_headers(ANALYST_ONE)
            ),
            201,
        )
        assert accepted["item_code"] == "J9999"
        assert accepted["billable_to"] == "SPONSOR"
        landed = read_analysis(analysis["id"])
        assert landed["item_count"] == 2
        assert landed["research_paid_item_count"] == 1
        assert landed["version"] == 3
