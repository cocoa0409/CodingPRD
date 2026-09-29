"""Budget arithmetic, the posture fixed point, and the content rules that guard
the coverage grid, the Medicare determination and an amendment's effective date.
"""

from test_helpers import (
    ANALYST_ONE,
    INITIAL_LOGICAL_CLOCK_STAMP,
    MANAGER_ONE,
    REVIEWER_ONE,
    api_client,
    assert_analysis_counters,
    assert_summary_matches_study,
    build_budget,
    create_coverage_item_payload,
    determine_qct,
    file_amendment,
    implement_amendment,
    item_spec,
    make_analyst_headers,
    make_manager_headers,
    make_reviewer_headers,
    open_finding,
    qct_determination_payload,
    read_analysis,
    read_study,
    read_summary,
    register_study,
    resolve_finding,
    respond_finding,
    set_clock,
    setup_study_with_approved_analysis,
    setup_study_with_draft_grid,
    submit_analysis,
    validate_error,
    validate_paginated,
    validate_success,
)

# 2 units x 2 occurrences x 40,000 = 160,000 cents of sponsor-borne per-patient
# work — deliberately below the 500,000-cent industry tier.
PER_PATIENT_INFUSION = item_spec(
    "J9999",
    classification="RESEARCH_PAID",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=55000,
    negotiated_unit_cents=40000,
    expected_occurrences=2,
    units_per_occurrence=2,
)
# 1 unit x 2 occurrences x 125,000 = 250,000 cents of invoiceable work.
INVOICEABLE_STARTUP_FEE = item_spec(
    "S9999",
    classification="RESEARCH_PAID",
    budget_category="INVOICEABLE",
    charge_master_unit_cents=125000,
    negotiated_unit_cents=125000,
    expected_occurrences=2,
    units_per_occurrence=1,
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
PROMOTIONAL_KIT = item_spec(
    "A9270",
    classification="PROMOTIONAL",
    budget_category="NOT_BUDGETED",
    charge_master_unit_cents=0,
    negotiated_unit_cents=0,
    expected_occurrences=1,
)
UNBUDGETED_TRAVEL = item_spec(
    "T1000",
    classification="RESEARCH_PAID",
    budget_category="NOT_BUDGETED",
    charge_master_unit_cents=77000,
    negotiated_unit_cents=77000,
    expected_occurrences=1,
)

CONDITIONAL_ROUTINE_FIELDS = {
    "item_code": "71046",
    "description": "Radiologic examination, chest, single view",
    "classification": "ROUTINE_CARE",
    "medicare_coverage_basis": "QCT_CONDITIONAL",
    "budget_category": "PER_PATIENT",
    "charge_master_unit_cents": 9000,
    "negotiated_unit_cents": 9000,
    "expected_occurrences": 2,
}


def _add_item_raw(analysis_id, expected_version, **fields):
    return api_client.create_coverage_item(
        create_coverage_item_payload(analysis_id, expected_version, **fields),
        make_analyst_headers(ANALYST_ONE),
    )


class TestBudgetSubtotalsAndTheDerivedRate:
    """Both subtotals ride one rate, and the rate is derived from one of them."""

    def test_01_both_subtotals_are_uplifted_once_at_the_derived_rate(self):
        """A small industry study requesting 20.0 percent lands on 23.0, and each
        subtotal is accumulated exactly before its single rounding.

        PRD §3.5: "`per_patient_budget_cents` is `per_patient_subtotal_cents` plus
        the subtotal multiplied by `effective_indirect_rate_pct` divided by 100
        and rounded half up to a whole cent. `invoiceable_budget_cents` is
        `invoiceable_subtotal_cents` plus that subtotal multiplied by the same
        rate divided by 100 and rounded half up to a whole cent."

        Design: Corner/calculations/budget_totals_correct_for_per_patient_and_invoiceable_subtotals
        """
        ctx = setup_study_with_approved_analysis(
            [PER_PATIENT_INFUSION, INVOICEABLE_STARTUP_FEE],
            qct_basis=None,
            study_overrides={
                "protocol_number": "AMC-2390-C22",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        assert ctx["study"]["lifecycle_status"] == "COVERAGE_APPROVED"
        assert ctx["study"]["budget_status"] == "NOT_BUILT"
        assert ctx["study"]["version"] == 3

        built = build_budget(
            ctx["study"]["id"],
            ctx["analysis"]["id"],
            expected_version=3,
            indirect_rate_pct=20.0,
        )

        # Exact accumulation: 2 x 2 x 40000 and 1 x 2 x 125000.
        assert built["per_patient_subtotal_cents"] == 160000
        assert built["invoiceable_subtotal_cents"] == 250000
        # 160000 is below the 500,000-cent tier: 20.0 + 3.0, capped at 32.0.
        assert built["effective_indirect_rate_pct"] == 23.0
        assert built["per_patient_budget_cents"] == 196800
        assert built["invoiceable_budget_cents"] == 307500

        assert built["budget_status"] == "BUILT"
        assert built["budget_basis"] == "COVERAGE_DRIVEN"
        assert built["indirect_rate_pct"] == 20.0
        assert built["budget_source_analysis_id"] == ctx["analysis"]["id"]
        assert built["budget_built_by_user_id"] == MANAGER_ONE
        assert built["budget_executed_by_user_id"] is None
        assert built["lifecycle_status"] == "COVERAGE_APPROVED"
        assert built["version"] == 4

    def test_02_payer_promotional_and_unbudgeted_items_never_enter_a_subtotal(self):
        """Three of the four grid rows are excluded for three different reasons,
        and the surviving row alone fixes both the subtotal and the rate.

        PRD §3.5: "Items whose `billable_to` is `PAYER` (the routine-care ones)
        and items whose `billable_to` is `NONE` (the promotional ones) are
        excluded from both subtotals, and items whose `budget_category` is
        `NOT_BUDGETED` are excluded even when the sponsor is the party of record."

        Design: Corner/calculations/budget_subtotals_exclude_payer_promotional_and_not_budgeted_items
        """
        ctx = setup_study_with_approved_analysis(
            [PER_PATIENT_INFUSION, ROUTINE_PANEL, PROMOTIONAL_KIT, UNBUDGETED_TRAVEL],
            qct_basis=None,
            study_overrides={
                "protocol_number": "AMC-2390-C23",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        assert_analysis_counters(
            ctx["analysis"],
            item_count=4,
            routine_care_item_count=1,
            research_paid_item_count=2,
            promotional_item_count=1,
            qct_conditional_item_count=0,
        )
        rows, meta = validate_paginated(
            api_client.list_coverage_analysis_items(
                ctx["analysis"]["id"], make_manager_headers(MANAGER_ONE)
            )
        )
        assert meta["total_count"] == 4
        assert {row["billable_to"] for row in rows} == {"PAYER", "SPONSOR", "NONE"}

        built = build_budget(
            ctx["study"]["id"],
            ctx["analysis"]["id"],
            expected_version=ctx["study"]["version"],
            indirect_rate_pct=20.0,
        )

        # The routine panel would have added 27000 and the travel row 77000.
        assert built["per_patient_subtotal_cents"] == 160000
        assert built["invoiceable_subtotal_cents"] == 0
        assert built["invoiceable_budget_cents"] == 0
        # The rate is tiered on the surviving 160000, not on 187000 or 264000.
        assert built["effective_indirect_rate_pct"] == 23.0
        assert built["per_patient_budget_cents"] == 196800
        assert built["budget_status"] == "BUILT"


class TestPostureReachesAFixedPoint:
    """Clause 1 dominates while a finding is live, and only while it is live."""

    def test_03_the_posture_follows_the_finding_from_open_to_closed_and_back(self):
        """Determination opens the study, a finding blocks it, a response leaves
        it blocked, closing restores `OPEN`, and a second finding blocks it again.

        PRD §2.9: "If `open_finding_count` is at least 1, the posture is
        `ALL_BLOCKED`." … "Otherwise, if `qct_determination` is either
        `UNDETERMINED` or `NON_QUALIFYING`, the posture is `PAYER_BLOCKED`."

        Design: Corner/calculations/posture_propagates_from_finding_open_through_close_to_a_fixed_point
        """
        study = register_study(
            protocol_number="AMC-2390-C25", funding_source="INDUSTRY_SPONSORED"
        )
        assert study["billing_hold_posture"] == "PAYER_BLOCKED"
        assert study["open_finding_count"] == 0

        determined = determine_qct(
            study["id"], basis="DEEMED_IND_IDE", registry_number="NCT10000125"
        )
        assert determined["qct_determination"] == "DEEMED_QUALIFYING"
        assert determined["billing_hold_posture"] == "OPEN"

        finding = open_finding(
            study["id"],
            finding_type="MISSING_REGISTRY_NUMBER",
            claimed_amount_cents=0,
        )
        assert finding["status"] == "OPEN"
        blocked = read_study(study["id"])
        assert blocked["open_finding_count"] == 1
        assert blocked["rebuild_required_calendar_count"] == 0
        assert blocked["billing_hold_posture"] == "ALL_BLOCKED"

        responded = respond_finding(finding["id"])
        assert responded["status"] == "RESPONDED"
        still_blocked = read_study(study["id"])
        # A RESPONDED finding still counts, so clause 1 still wins.
        assert still_blocked["open_finding_count"] == 1
        assert still_blocked["billing_hold_posture"] == "ALL_BLOCKED"

        resolved = resolve_finding(finding["id"], "NO_ACTION")
        assert resolved["status"] == "CLOSED_NO_ACTION"
        reopened = read_study(study["id"])
        assert reopened["open_finding_count"] == 0
        assert reopened["billing_hold_posture"] == "OPEN"
        # The recompute is a fixed point: reading again moves nothing.
        assert read_study(study["id"])["billing_hold_posture"] == "OPEN"
        assert_summary_matches_study(read_summary(study["id"]), reopened)

        open_finding(
            study["id"],
            finding_type="UNSUPPORTED_ROUTINE_CLASSIFICATION",
            claimed_amount_cents=9000,
        )
        again = read_study(study["id"])
        assert again["open_finding_count"] == 1
        assert again["billing_hold_posture"] == "ALL_BLOCKED"


class TestCoverageGridContentRules:
    """The two rules that guard what may be written onto a grid."""

    def test_04_a_promotional_item_must_be_free_on_both_axes(self):
        """A priced promotional row and a budgeted one are both refused, and the
        analysis is untouched until a genuinely free row arrives.

        PRD §3.2: "Separately, a `PROMOTIONAL` item is by definition free to
        everyone: it must carry `budget_category` `NOT_BUDGETED` and
        `negotiated_unit_cents` of exactly zero, or it is refused with
        `ERR_PROMOTIONAL_MUST_BE_ZERO_COST`."

        Design: Corner/validations/promotional_item_with_nonzero_negotiated_cost_is_rejected
        """
        ctx = setup_study_with_draft_grid(
            [], study_overrides={"protocol_number": "AMC-2390-C27"}
        )
        analysis_id = ctx["analysis"]["id"]
        assert ctx["analysis"]["version"] == 1

        validate_error(
            _add_item_raw(
                analysis_id,
                1,
                item_code="A9270",
                description="Patient education kit",
                classification="PROMOTIONAL",
                medicare_coverage_basis="NOT_COVERED",
                budget_category="NOT_BUDGETED",
                charge_master_unit_cents=12000,
                negotiated_unit_cents=12000,
                expected_occurrences=1,
            ),
            "ERR_PROMOTIONAL_MUST_BE_ZERO_COST",
            422,
        )
        untouched = read_analysis(analysis_id)
        assert_analysis_counters(untouched, item_count=0, promotional_item_count=0)
        assert untouched["version"] == 1

        # Zero-cost but budgeted is refused by the same rule.
        validate_error(
            _add_item_raw(
                analysis_id,
                1,
                item_code="A9270",
                description="Patient education kit",
                classification="PROMOTIONAL",
                medicare_coverage_basis="NOT_COVERED",
                budget_category="PER_PATIENT",
                charge_master_unit_cents=0,
                negotiated_unit_cents=0,
                expected_occurrences=1,
            ),
            "ERR_PROMOTIONAL_MUST_BE_ZERO_COST",
            422,
        )
        assert read_analysis(analysis_id)["version"] == 1

        free = validate_success(
            _add_item_raw(
                analysis_id,
                1,
                item_code="A9270",
                description="Patient education kit",
                classification="PROMOTIONAL",
                medicare_coverage_basis="NOT_COVERED",
                budget_category="NOT_BUDGETED",
                charge_master_unit_cents=12000,
                negotiated_unit_cents=0,
                expected_occurrences=1,
            ),
            201,
        )
        assert free["billable_to"] == "NONE"
        assert free["negotiated_unit_cents"] == 0
        assert_analysis_counters(
            read_analysis(analysis_id), item_count=1, promotional_item_count=1
        )

    def test_05_a_conditional_routine_item_is_blocked_only_by_a_non_qualifying_study(self):
        """The grid rule reads the study's determination, and the missing
        determination is caught later, at approval.

        PRD §3.2: "if it is `QCT_CONDITIONAL` then the study's
        `qct_determination` may not be `NON_QUALIFYING`. Either violation is
        `ERR_ROUTINE_CARE_REQUIRES_QCT`. Note deliberately what this rule does
        *not* demand: a study still at `UNDETERMINED` may draft a conditional
        routine-care item, because the qualifying determination is not enforced
        here but later, at approval, by the rule described in §3.3."

        Design: Corner/validations/qct_conditional_routine_item_rejected_only_when_study_is_non_qualifying
        """
        declared = setup_study_with_draft_grid(
            [],
            qct_basis="NOT_QUALIFYING_DECLARED",
            study_overrides={"protocol_number": "AMC-2390-C35"},
        )
        assert declared["study"]["qct_determination"] == "NON_QUALIFYING"
        assert declared["study"]["billing_hold_posture"] == "PAYER_BLOCKED"

        validate_error(
            _add_item_raw(declared["analysis"]["id"], 1, **CONDITIONAL_ROUTINE_FIELDS),
            "ERR_ROUTINE_CARE_REQUIRES_QCT",
            422,
        )
        refused = read_analysis(declared["analysis"]["id"])
        assert_analysis_counters(
            refused, item_count=0, routine_care_item_count=0, qct_conditional_item_count=0
        )
        assert refused["version"] == 1

        # The same routine row with Medicare support of its own is accepted on
        # the very same non-qualifying study.
        supported_fields = dict(CONDITIONAL_ROUTINE_FIELDS)
        supported_fields["medicare_coverage_basis"] = "STANDARD_OF_CARE"
        supported = validate_success(
            _add_item_raw(declared["analysis"]["id"], 1, **supported_fields), 201
        )
        assert supported["billable_to"] == "PAYER"
        assert_analysis_counters(
            read_analysis(declared["analysis"]["id"]),
            item_count=1,
            routine_care_item_count=1,
            qct_conditional_item_count=0,
        )

        undetermined = setup_study_with_draft_grid(
            [], study_overrides={"protocol_number": "AMC-2390-C36"}
        )
        assert undetermined["study"]["qct_determination"] == "UNDETERMINED"
        drafted = validate_success(
            _add_item_raw(undetermined["analysis"]["id"], 1, **CONDITIONAL_ROUTINE_FIELDS),
            201,
        )
        assert drafted["medicare_coverage_basis"] == "QCT_CONDITIONAL"
        assert drafted["billable_to"] == "PAYER"
        assert_analysis_counters(
            read_analysis(undetermined["analysis"]["id"]),
            item_count=1,
            qct_conditional_item_count=1,
        )

        # Enforcement lands at approval instead.
        submit_analysis(undetermined["analysis"]["id"])
        validate_error(
            api_client.approve_coverage_analysis(
                undetermined["analysis"]["id"], make_reviewer_headers(REVIEWER_ONE)
            ),
            "ERR_QCT_DETERMINATION_REQUIRED",
            409,
        )
        assert read_analysis(undetermined["analysis"]["id"])["status"] == "UNDER_REVIEW"


class TestGatesOnDeterminationAndAmendmentTiming:
    """Two preconditions that a later request can satisfy without being rewritten."""

    def test_06_a_qualifying_determination_accepts_the_registry_number_inline(self):
        """The registry number may arrive on the determination itself; without one
        anywhere the qualifying bases are refused, while the downgrade is not.

        PRD §3.1: "Any determination that would leave the study qualifying — that
        is, `DEEMED_QUALIFYING` or `SELF_CERTIFIED_QUALIFYING` — requires a
        registry number to be available, either supplied on this request or
        already stored on the study; absent one, the answer is
        `ERR_REGISTRY_NUMBER_REQUIRED`."

        Design: Corner/validations/qualifying_determination_passes_when_registry_number_is_supplied_inline
        """
        study = register_study(protocol_number="AMC-2390-C31")
        assert study["registry_number"] is None
        assert study["qct_basis"] is None
        assert study["billing_hold_posture"] == "PAYER_BLOCKED"

        determined = validate_success(
            api_client.record_qct_determination(
                study["id"],
                qct_determination_payload(
                    basis="DEEMED_IND_IDE", registry_number="NCT10000131"
                ),
                make_reviewer_headers(REVIEWER_ONE),
            ),
            200,
        )
        assert determined["qct_determination"] == "DEEMED_QUALIFYING"
        assert determined["qct_basis"] == "DEEMED_IND_IDE"
        assert determined["registry_number"] == "NCT10000131"
        assert determined["qct_determined_by_user_id"] == REVIEWER_ONE
        assert determined["qct_determined_at"] == INITIAL_LOGICAL_CLOCK_STAMP
        assert determined["billing_hold_posture"] == "OPEN"
        assert determined["version"] == 2

        bare = register_study(protocol_number="AMC-2390-C32")
        for basis in ("DEEMED_IND_IDE", "SELF_CERTIFIED"):
            validate_error(
                api_client.record_qct_determination(
                    bare["id"],
                    qct_determination_payload(basis=basis),
                    make_reviewer_headers(REVIEWER_ONE),
                ),
                "ERR_REGISTRY_NUMBER_REQUIRED",
                422,
            )
        unmoved = read_study(bare["id"])
        assert unmoved["qct_determination"] == "UNDETERMINED"
        assert unmoved["qct_basis"] is None
        assert unmoved["registry_number"] is None
        assert unmoved["billing_hold_posture"] == "PAYER_BLOCKED"
        assert unmoved["version"] == 1

        # The gate is scoped to qualifying outcomes only.
        downgraded = determine_qct(bare["id"], basis="NOT_QUALIFYING_DECLARED")
        assert downgraded["qct_determination"] == "NON_QUALIFYING"
        assert downgraded["registry_number"] is None
        assert downgraded["billing_hold_posture"] == "PAYER_BLOCKED"

    def test_07_a_future_dated_amendment_waits_for_the_clock_to_reach_it(self):
        """The identical implementation request is refused before the effective
        date and accepted on it, the boundary being inclusive.

        PRD §3.9: "the `effective_date` must be at or before the current logical
        clock's date — a future-dated amendment is refused with
        `ERR_AMENDMENT_NOT_YET_EFFECTIVE`."

        Design: Corner/validations/amendment_cannot_be_implemented_before_its_effective_date
        """
        ctx = setup_study_with_approved_analysis(
            [PER_PATIENT_INFUSION],
            clock="2026-09-01T00:00:00Z",
            qct_basis=None,
            study_overrides={"protocol_number": "AMC-2390-C33"},
        )
        assert ctx["study"]["lifecycle_status"] == "COVERAGE_APPROVED"

        amendment = file_amendment(
            ctx["study"]["id"], scope="ITEM_CHANGE", effective_date="2026-09-10"
        )
        assert amendment["status"] == "SUBMITTED"
        assert amendment["amendment_number"] == 1
        assert amendment["reanalysis_required"] is True
        assert amendment["calendar_rebuild_required"] is False
        assert amendment["version"] == 1

        validate_error(
            api_client.implement_amendment(
                amendment["id"], make_manager_headers(MANAGER_ONE)
            ),
            "ERR_AMENDMENT_NOT_YET_EFFECTIVE",
            409,
        )
        rows, meta = validate_paginated(
            api_client.list_study_amendments(
                ctx["study"]["id"], make_manager_headers(MANAGER_ONE)
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "SUBMITTED"
        assert rows[0]["version"] == 1
        assert read_study(ctx["study"]["id"])["lifecycle_status"] == "COVERAGE_APPROVED"

        # Only the clock moves, and only as far as the effective date itself.
        set_clock("2026-09-10T00:00:00Z")
        implemented = implement_amendment(amendment["id"])
        assert implemented["status"] == "IMPLEMENTED"
        assert implemented["version"] == 2
        assert read_study(ctx["study"]["id"])["lifecycle_status"] == "COVERAGE_PENDING"
