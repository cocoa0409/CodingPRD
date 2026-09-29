"""The compliance review loop, the approval gate on the Medicare question, and
the two coverage views that a superseding revision drives apart.
"""

from test_helpers import (
    ANALYST_ONE,
    REVIEWER_ONE,
    add_item,
    add_items,
    analysis_version,
    api_client,
    approve_analysis,
    determine_qct,
    file_amendment,
    implement_amendment,
    item_spec,
    make_reviewer_headers,
    open_analysis,
    post_charge,
    read_analysis,
    read_charge,
    read_study,
    return_analysis_payload,
    set_clock,
    setup_study_with_analysis_under_review,
    setup_study_with_approved_analysis,
    submit_analysis,
    validate_error,
    validate_success,
)

SCREENING_PANEL = item_spec(
    "80053",
    classification="ROUTINE_CARE",
    medicare_coverage_basis="STANDARD_OF_CARE",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=9000,
    negotiated_unit_cents=9000,
    expected_occurrences=1,
)


def _return_attempt(analysis_id, reason="Reclassify the screening laboratory panel."):
    return api_client.return_coverage_analysis(
        analysis_id,
        return_analysis_payload(return_reason=reason),
        make_reviewer_headers(REVIEWER_ONE),
    )


class TestReturnLoopIsBounded:
    """Two returns are allowed; the third is refused."""

    def _under_review(self):
        return setup_study_with_analysis_under_review(
            [item_spec("36415", negotiated_unit_cents=3000, charge_master_unit_cents=5000)],
            qct_basis=None,
            study_overrides={"protocol_number": "AMC-2390-K"},
        )

    def _cycle(self, analysis_id, item_code):
        """Return, reopen with a fresh item, and submit again."""
        returned = validate_success(_return_attempt(analysis_id), 200)
        add_item(analysis_id, item_code=item_code, negotiated_unit_cents=1000)
        submit_analysis(analysis_id)
        return returned

    def test_01_a_third_return_is_refused_once_the_budget_is_exhausted(self):
        """After two returns the counter has reached two and the loop closes.

        PRD §3.3: "A study's analysis may be returned at most twice: a return
        attempted when `return_count` has already reached two is refused with
        `ERR_RETURN_LIMIT_EXCEEDED`, and returning anything not currently
        `UNDER_REVIEW` is `ERR_ANALYSIS_NOT_UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/analysis_return_loop_closes_twice_then_is_bounded
        """
        ctx = self._under_review()
        analysis_id = ctx["analysis"]["id"]

        first = self._cycle(analysis_id, "85025")
        assert first["return_count"] == 1
        second = self._cycle(analysis_id, "84443")
        assert second["return_count"] == 2

        validate_error(_return_attempt(analysis_id), "ERR_RETURN_LIMIT_EXCEEDED", 409)

        analysis = read_analysis(analysis_id)
        assert analysis["status"] == "UNDER_REVIEW"
        assert analysis["return_count"] == 2
        assert analysis["item_count"] == 3

    def test_02_each_return_stamps_the_reviewer_and_reopening_flips_back_to_draft(self):
        """Adding an item to a returned analysis is what reopens it, and after
        the bounded loop the analysis can still be approved.

        PRD §3.2: "Adding an item to a `RETURNED` analysis is also how the
        analyst reopens it — the analysis moves `RETURNED → DRAFT` in the same
        request, which closes the review cycle and lets the analyst submit
        again."

        Design: Difficulty/non_linear_state_machine/analysis_return_loop_closes_twice_then_is_bounded
        """
        ctx = self._under_review()
        analysis_id = ctx["analysis"]["id"]

        returned = validate_success(_return_attempt(analysis_id), 200)
        assert returned["status"] == "RETURNED"
        assert returned["return_count"] == 1
        assert returned["returned_by_user_id"] == REVIEWER_ONE
        assert returned["return_reason"] == "Reclassify the screening laboratory panel."

        reopened_by = add_item(analysis_id, item_code="85025", negotiated_unit_cents=1000)
        assert reopened_by["item_code"] == "85025"
        assert read_analysis(analysis_id)["status"] == "DRAFT"

        assert submit_analysis(analysis_id)["status"] == "UNDER_REVIEW"
        self._cycle(analysis_id, "84443")

        approved = approve_analysis(analysis_id, user_id=REVIEWER_ONE)
        assert approved["status"] == "APPROVED"
        assert approved["return_count"] == 2
        assert read_study(ctx["study"]["id"])["lifecycle_status"] == "COVERAGE_APPROVED"


class TestApprovalBlockedByUndeterminedQct:
    """A conditional routine-care item may be drafted but not blessed."""

    CONDITIONAL_ITEM = item_spec(
        "78815",
        classification="ROUTINE_CARE",
        medicare_coverage_basis="QCT_CONDITIONAL",
        budget_category="PER_PATIENT",
        charge_master_unit_cents=470000,
        negotiated_unit_cents=470000,
        expected_occurrences=1,
    )

    def _under_review(self):
        return setup_study_with_analysis_under_review(
            [self.CONDITIONAL_ITEM],
            qct_basis=None,
            study_overrides={"protocol_number": "AMC-2390-V"},
        )

    def test_03_approval_is_refused_while_the_study_is_undetermined(self):
        """The draft was accepted at `UNDETERMINED`; the approval is not.

        PRD §3.3: "If the analysis carries at least one `QCT_CONDITIONAL`
        routine-care item — that is, `qct_conditional_item_count` is at least 1 —
        the study's `qct_determination` must be something other than
        `UNDETERMINED`, or the approval is refused with
        `ERR_QCT_DETERMINATION_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/analysis_approval_blocked_by_undetermined_study_qct
        """
        ctx = self._under_review()
        assert ctx["analysis"]["qct_conditional_item_count"] == 1
        assert ctx["study"]["qct_determination"] == "UNDETERMINED"

        validate_error(
            api_client.approve_coverage_analysis(
                ctx["analysis"]["id"], make_reviewer_headers(REVIEWER_ONE)
            ),
            "ERR_QCT_DETERMINATION_REQUIRED",
            409,
        )

        assert read_analysis(ctx["analysis"]["id"])["status"] == "UNDER_REVIEW"
        assert read_analysis(ctx["analysis"]["id"])["approved_at"] is None
        assert read_study(ctx["study"]["id"])["lifecycle_status"] == "COVERAGE_PENDING"

    def test_04_the_same_approval_succeeds_once_the_determination_exists(self):
        """Nothing about the analysis changes — only the study's determination.

        PRD §3.2: "Note deliberately what this rule does *not* demand: a study
        still at `UNDETERMINED` may draft a conditional routine-care item,
        because the qualifying determination is not enforced here but later, at
        approval, by the rule described in §3.3."

        Design: Difficulty/cross_entity_state_dependency/analysis_approval_blocked_by_undetermined_study_qct
        """
        ctx = self._under_review()
        validate_error(
            api_client.approve_coverage_analysis(
                ctx["analysis"]["id"], make_reviewer_headers(REVIEWER_ONE)
            ),
            "ERR_QCT_DETERMINATION_REQUIRED",
            409,
        )

        determined = determine_qct(
            ctx["study"]["id"], basis="DEEMED_IND_IDE", registry_number="NCT10000022"
        )
        assert determined["qct_determination"] == "DEEMED_QUALIFYING"

        approved = validate_success(
            api_client.approve_coverage_analysis(
                ctx["analysis"]["id"], make_reviewer_headers(REVIEWER_ONE)
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == REVIEWER_ONE
        assert read_study(ctx["study"]["id"])["lifecycle_status"] == "COVERAGE_APPROVED"


class TestOperationalAndAuditViewsDiverge:
    """A revision that reclassifies an item splits the two coverage answers."""

    def _setup(self):
        ctx = setup_study_with_approved_analysis(
            [SCREENING_PANEL],
            qct_basis="DEEMED_IND_IDE",
            qct_registry_number="NCT10000002",
            study_overrides={
                "protocol_number": "AMC-2390-B",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        # The charge happens while the first analysis is the one in force.
        set_clock("2026-08-05T00:00:00Z")
        ctx["charge"] = post_charge(
            ctx["study"]["id"],
            charge_code="80053",
            service_date="2026-08-05",
            amount_cents=9000,
        )
        assert ctx["charge"]["expected_routing_target"] == "PAYER"

        amendment = file_amendment(
            ctx["study"]["id"], scope="ITEM_CHANGE", effective_date="2026-08-05"
        )
        implement_amendment(amendment["id"])

        # Two weeks later the revision reclassifies the panel as sponsor-paid.
        set_clock("2026-08-20T00:00:00Z")
        revision = open_analysis(
            ctx["study"]["id"],
            user_id=ANALYST_ONE,
            supersedes_analysis_id=ctx["analysis"]["id"],
        )
        add_items(
            revision["id"],
            [
                item_spec(
                    "80053",
                    classification="RESEARCH_PAID",
                    medicare_coverage_basis="NOT_COVERED",
                    budget_category="PER_PATIENT",
                    charge_master_unit_cents=9000,
                    negotiated_unit_cents=9000,
                    expected_occurrences=1,
                )
            ],
        )
        submit_analysis(revision["id"])
        approve_analysis(revision["id"], user_id=REVIEWER_ONE)
        ctx["revision"] = read_analysis(revision["id"])
        ctx["charge"] = read_charge(ctx["charge"]["id"])
        ctx["study"] = read_study(ctx["study"]["id"])
        return ctx

    def test_05_review_time_routing_follows_the_analysis_in_force_on_the_service_date(self):
        """Clearing the charge to the payer is accepted because the operational
        view still resolves to the superseded analysis, whose panel was routine
        care on 2026-08-05.

        PRD §3.7: "The **operational view**, used at review time, keeps only
        those candidates whose `approved_at` falls at or before the very end of
        the charge's `service_date` — that is, at or before `23:59:59.999` UTC on
        that calendar date — and then takes the one with the latest
        `approved_at`, breaking a tie by the later `created_at`."

        Design: Difficulty/dual_variant_calc/routing_expectation_service_date_vs_current_effective_divergence
        """
        ctx = self._setup()
        assert ctx["revision"]["approved_at"] == "2026-08-20T00:00:00.000Z"
        assert read_analysis(ctx["analysis"]["id"])["status"] == "SUPERSEDED"
        # The persisted audit answer has already flipped to the sponsor.
        assert ctx["charge"]["expected_routing_target"] == "SPONSOR"

        cleared = validate_success(
            api_client.review_charge(
                ctx["charge"]["id"],
                {"decision": "CLEAR_TO_PAYER"},
                make_reviewer_headers(REVIEWER_ONE),
            ),
            200,
        )
        assert cleared["routing_state"] == "ROUTED_PAYER"
        assert cleared["billing_state"] == "BILLED_PAYER"
        assert cleared["reviewed_by_user_id"] == REVIEWER_ONE

    def test_06_the_persisted_audit_view_turns_the_same_charge_improper(self):
        """The two answers disagree on one row: correctly billed as of the
        service date, improperly billed today.

        PRD §3.7: "The two views deliberately disagree: a charge routed to the
        payer entirely correctly under the analysis in force on its service date
        becomes improper the moment a superseding analysis reclassifies its item
        code, and the study's `improper_payer_exposure_cents` picks that up with
        no request having touched the charge."

        Design: Difficulty/dual_variant_calc/routing_expectation_service_date_vs_current_effective_divergence
        """
        ctx = self._setup()
        validate_success(
            api_client.review_charge(
                ctx["charge"]["id"],
                {"decision": "CLEAR_TO_PAYER"},
                make_reviewer_headers(REVIEWER_ONE),
            ),
            200,
        )

        charge = read_charge(ctx["charge"]["id"])
        assert charge["expected_routing_target"] == "SPONSOR"
        assert charge["improper_flag"] is True

        study = read_study(ctx["study"]["id"])
        assert study["payer_billed_cents"] == 9000
        assert study["improper_payer_exposure_cents"] == 9000


class TestSupersedingApprovalReclassifiesInTheSameRequest:
    """Approval recomputes every charge's expectation before it answers."""

    def test_07_an_approval_reclassifies_existing_charges_with_no_charge_request(self):
        """A payer-billed charge becomes improper inside the approval request
        itself, while both of its state dimensions stay exactly where they were.

        PRD §3.3: "Every charge already on the study has its coverage
        expectation recomputed, and from those the study's improper-payer
        exposure is re-derived — which is how an approval that reclassifies an
        item can turn a previously compliant payer-billed charge into an improper
        one without any request touching that charge."

        Design: Corner/consistency_model/superseding_approval_reclassifies_existing_charges_within_the_same_request
        """
        ctx = setup_study_with_approved_analysis(
            [SCREENING_PANEL],
            qct_basis="DEEMED_IND_IDE",
            qct_registry_number="NCT10000080",
            study_overrides={"protocol_number": "AMC-2390-C80"},
        )
        charge = post_charge(
            ctx["study"]["id"],
            charge_code="80053",
            service_date="2026-08-01",
            amount_cents=9000,
        )
        billed = validate_success(
            api_client.review_charge(
                charge["id"],
                {"decision": "CLEAR_TO_PAYER"},
                make_reviewer_headers(REVIEWER_ONE),
            ),
            200,
        )
        assert billed["improper_flag"] is False
        assert read_study(ctx["study"]["id"])["improper_payer_exposure_cents"] == 0
        before_aging_days = billed["aging_days"]
        before_aging_bucket = billed["aging_bucket"]

        set_clock("2026-08-20T00:00:00Z")
        revision = open_analysis(
            ctx["study"]["id"],
            user_id=ANALYST_ONE,
            supersedes_analysis_id=ctx["analysis"]["id"],
        )
        add_item(
            revision["id"],
            analysis_version(revision["id"]),
            item_code="80053",
            classification="RESEARCH_PAID",
            medicare_coverage_basis="NOT_COVERED",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=9000,
            negotiated_unit_cents=9000,
            expected_occurrences=1,
        )
        submit_analysis(revision["id"])
        approved = approve_analysis(revision["id"], user_id=REVIEWER_ONE)

        assert approved["approved_at"] == "2026-08-20T00:00:00.000Z"
        assert read_analysis(ctx["analysis"]["id"])["status"] == "SUPERSEDED"

        after = read_charge(charge["id"])
        assert after["expected_routing_target"] == "SPONSOR"
        assert after["improper_flag"] is True
        assert after["routing_state"] == "ROUTED_PAYER"
        assert after["billing_state"] == "BILLED_PAYER"
        # The aging snapshot belongs to the epoch, not to this request.
        assert after["aging_days"] == before_aging_days
        assert after["aging_bucket"] == before_aging_bucket

        study = read_study(ctx["study"]["id"])
        assert study["payer_billed_cents"] == 9000
        assert study["improper_payer_exposure_cents"] == 9000
