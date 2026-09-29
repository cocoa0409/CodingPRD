"""Agency disposition, the void compensation and the computed money views.

Acceptance is the deepest cascade in the system and rejection is the shallowest
possible write, so both are pinned here link by link. The same file covers the
two-dimension join that decides when a case may move on to remediation, the
prepare-then-void invariant on employer exposure, and the two computed reads
that have to agree with the rows they summarise.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_amendment_money,
    assert_case_dimensions,
    assert_case_rollups,
    assert_exposure_summary,
    assert_pagination,
)
from test_helpers.constants import CANON_CLOCK
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    AUDITOR_HEADERS,
    OFFICER_HEADERS,
    PREPARER_HEADERS,
    make_employer_rep_headers,
)


class TestAcceptanceCascade:
    def test_acceptance_freezes_the_money_resolves_every_row_and_amends_the_return(self, api):
        """The first two links of the cascade: the accepted amendment is stamped and
        frozen, all three discrepancies carry their own resolved amount, and the
        filed return the case was built on becomes an amended one.

        PRD: "**Link one:** the amendment's `accepted_at` is stamped from the logical clock and its `interest_cents` and `penalty_cents` are frozen at their prepared values, and the case's filed return transitions `FILED → AMENDED` with its own `version` incremented by 1 — a transition available only from `FILED`, and only when that return's employer, agency, tax year and quarter all equal the accepted amendment's case keys."
        PRD: "**Link two:** every discrepancy on the case whose status is `CATEGORIZED` transitions `CATEGORIZED → RESOLVED`, each one recording `resolved_amended_return_id` as the accepted amendment and freezing `resolved_amount_cents` at its own `amount_cents`, with each such discrepancy's `version` incremented by 1."

        Design: Difficulty/transitive_cascade/amended_return_acceptance_cascade_depth_five
        """
        ctx = fx.federal_submitted_amendment(api)
        amendment_id = ctx["amended_return_id"]

        accepted = validate_success(
            api.record_agency_outcome(
                amendment_id, f.agency_outcome_payload("ACCEPTED"), OFFICER_HEADERS
            )
        )

        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepted_at"] == "2026-04-30T00:00:00.000Z"
        assert_amendment_money(
            accepted,
            wage_delta_cents=250000,
            tax_delta_cents=250000,
            deposit_shortfall_cents=250000,
            days_late=365,
            interest_cents=20000,
            penalty_cents=65625,
        )

        rows = fx.case_discrepancies(api, ctx["case_id"])
        assert len(rows) == 3
        for row in rows:
            assert row["status"] == "RESOLVED", row
            assert row["resolved_amended_return_id"] == amendment_id
            assert row["resolved_amount_cents"] == row["amount_cents"]

        resolved, resolved_meta = validate_paginated(
            api.list_discrepancies(
                {"correction_case_id": ctx["case_id"], "status": "RESOLVED"}, ANALYST_HEADERS
            )
        )
        assert_pagination(resolved_meta, total_count=3)
        assert len(resolved) == 3

        filed = validate_success(
            api.get_filed_return(ctx["filed_return"]["id"], PREPARER_HEADERS)
        )
        assert filed["status"] == "AMENDED"

    def test_acceptance_joins_both_dimensions_and_opens_one_unowned_remediation(self, api):
        """Links three through five: the filing dimension completes, the join to
        `REMEDIATION_PENDING` fires against an untouched statement dimension, exactly
        one ownerless remediation appears, and both employer counters move.

        PRD: "**Link three:** those discrepancy transitions recompute the case's `open_discrepancy_count`, and when that count reaches 0 while `filing_status` is `FILING_IN_PROGRESS`, the case's filing dimension advances `FILING_IN_PROGRESS → FILING_COMPLETE` and the case's `version` is incremented by 1."
        PRD: "**Link four:** reaching `FILING_COMPLETE` while `statement_status` is `STMT_NOT_REQUIRED`, `STMT_ISSUED` or `STMT_COMPLETE` advances the case's overall `status` `OPEN → REMEDIATION_PENDING` — the join point of the filing and statement dimensions — and, provided no control remediation for this case already exists, auto-creates exactly one control remediation in `status` `OPEN` whose `correction_case_id` is this case, whose `root_cause_code` is the case's `dominant_root_cause_code`, whose `control_gap_class` is `PROCESS_CONTROL`, whose `owner_user_id` is null and whose `target_date` is the current logical instant advanced by 30 days."
        PRD: "**Link five:** when that remediation was in fact created, the employer's `open_remediation_count` is incremented by 1."
        PRD: "An employer's `open_exposure_cents` is the sum of `total_exposure_cents` over every case belonging to that employer whose `status` is `OPEN` or `REMEDIATION_PENDING`."

        Design: Difficulty/transitive_cascade/amended_return_acceptance_cascade_depth_five
        """
        ctx = fx.federal_submitted_amendment(api)
        validate_success(
            api.record_agency_outcome(
                ctx["amended_return_id"], f.agency_outcome_payload("ACCEPTED"), OFFICER_HEADERS
            )
        )

        case = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(
            case,
            status="REMEDIATION_PENDING",
            detection_status="VARIANCE_FOUND",
            filing_status="FILING_COMPLETE",
            statement_status="STMT_NOT_REQUIRED",
        )
        assert_case_rollups(case, open_discrepancy_count=0, total_exposure_cents=335625)
        assert case["dominant_root_cause_code"] is not None

        remediations, meta = validate_paginated(
            api.list_control_remediations({"correction_case_id": ctx["case_id"]}, AUDITOR_HEADERS)
        )
        assert_pagination(meta, total_count=1)
        created = remediations[0]
        assert created["correction_case_id"] == ctx["case_id"]
        assert created["status"] == "OPEN"
        assert created["control_gap_class"] == "PROCESS_CONTROL"
        assert created["owner_user_id"] is None
        assert created["root_cause_code"] == case["dominant_root_cause_code"]
        assert created["target_date"].startswith("2026-05-30")
        assert created["verification_round"] == 0
        for field in ("evidence_reference", "verified_by_user_id", "verified_at"):
            assert created[field] is None, field

        employer = validate_success(api.get_employer(ctx["employer_id"], ADMIN_HEADERS))
        assert employer["open_remediation_count"] == 1
        assert employer["open_exposure_cents"] == 335625


class TestAgencyRejection:
    def test_rejection_moves_the_amendment_and_nothing_else_in_the_system(self, api):
        """The rejecting branch is deliberately inert: the reason is stored, the filed
        return is still `FILED`, every discrepancy is still `CATEGORIZED`, and the
        exposure the preparation booked is left exactly where it was.

        PRD: "On `REJECTED` the amendment transitions `SUBMITTED → AGENCY_REJECTED`, the supplied `rejection_reason` is stored, and **nothing else in the system moves**: no discrepancy is resolved, the case's `filing_status` remains at `FILING_IN_PROGRESS`, and the only version that changes is the amendment's own, incremented by 1."
        PRD: "Amended returns in `DRAFT`, `AGENCY_REJECTED` or `VOID` are excluded from the first sum entirely, which is exactly why voiding a return removes its whole contribution and why a rejected return leaves exposure untouched."

        Design: Difficulty/non_linear_state_machine/amended_return_rejected_returns_to_draft_and_reprepares
        """
        ctx = fx.federal_submitted_amendment(api)
        submitted_version = ctx["amended_return"]["version"]

        rejected = validate_success(
            api.record_agency_outcome(
                ctx["amended_return_id"],
                f.agency_outcome_payload(
                    "REJECTED", rejection_reason="Schedule B totals did not tie to the deposits."
                ),
                OFFICER_HEADERS,
            )
        )

        assert rejected["status"] == "AGENCY_REJECTED"
        assert rejected["rejection_reason"] == "Schedule B totals did not tie to the deposits."
        assert rejected["accepted_at"] is None
        assert rejected["version"] == submitted_version + 1

        filed = validate_success(
            api.get_filed_return(ctx["filed_return"]["id"], PREPARER_HEADERS)
        )
        assert filed["status"] == "FILED"

        rows = fx.case_discrepancies(api, ctx["case_id"])
        assert len(rows) == 3
        for row in rows:
            assert row["status"] == "CATEGORIZED", row
            assert row["resolved_amended_return_id"] is None
            assert row["resolved_amount_cents"] is None

        case = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(case, status="OPEN", filing_status="FILING_IN_PROGRESS")
        assert_case_rollups(case, open_discrepancy_count=3, total_exposure_cents=335625)

    def test_re_preparing_a_rejected_amendment_recalls_it_to_draft_before_it_reprepares(
        self, api
    ):
        """Preparation is the recall lever, so the first call after a rejection lands in
        `DRAFT` with the signature, the transmission stamp and the reason all cleared;
        a second call walks the ordinary path again to the very same figures.

        PRD: "Similarly, an amendment the agency rejected may be prepared again, transitioning `AGENCY_REJECTED → DRAFT`, which clears `signed_by_user_id`, `submitted_at` and `rejection_reason` back to null and increments `version` by 1."
        PRD: "Both routes rejoin the ordinary `DRAFT → PREPARED → SIGNED` path, giving the amendment lifecycle two genuine cycles."

        Design: Difficulty/non_linear_state_machine/amended_return_rejected_returns_to_draft_and_reprepares
        """
        ctx = fx.federal_submitted_amendment(api)
        amendment_id = ctx["amended_return_id"]
        rejected = validate_success(
            api.record_agency_outcome(
                amendment_id,
                f.agency_outcome_payload(
                    "REJECTED", rejection_reason="Agency rejected the transmission."
                ),
                OFFICER_HEADERS,
            )
        )
        assert rejected["status"] == "AGENCY_REJECTED"

        recalled = validate_success(api.prepare_amended_return(amendment_id, {}, PREPARER_HEADERS))

        assert recalled["status"] == "DRAFT"
        assert recalled["signed_by_user_id"] is None
        assert recalled["submitted_at"] is None
        assert recalled["rejection_reason"] is None
        assert recalled["version"] == rejected["version"] + 1

        reprepared = validate_success(
            api.prepare_amended_return(amendment_id, {}, PREPARER_HEADERS)
        )

        assert reprepared["status"] == "PREPARED"
        assert_amendment_money(
            reprepared,
            tax_delta_cents=250000,
            days_late=365,
            interest_cents=20000,
            penalty_cents=65625,
        )
        case = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(case, status="OPEN", filing_status="FILING_IN_PROGRESS")
        assert_case_rollups(case, total_exposure_cents=335625)


def _two_dimension_scenario(api):
    """A 2025 Q1 federal case that owes both an amendment and a statement: one
    withholding variance of 50000 cents and one jurisdiction removal of 400000
    cents, carried to a transmitted amendment."""
    fx.set_clock(api, CANON_CLOCK)
    employer = fx.make_employer(api, deposit_schedule="MONTHLY")
    agency = fx.make_federal_agency(api)
    employee = fx.make_employee(api, employer["id"], mailing_state_code="NJ")
    fx.make_register_line(
        api,
        employer["id"],
        employee["id"],
        agency["id"],
        taxable_wage_cents=1000000,
        withheld_cents=150000,
        work_jurisdiction_code="NJ",
        workday_ratio_bps=4000,
    )
    fx.make_filed_return(
        api,
        employer["id"],
        agency["id"],
        reported_taxable_wage_cents=1000000,
        reported_withheld_cents=100000,
    )
    case = fx.make_correction_case(api, employer["id"], agency["id"])
    validate_success(api.reconcile_case(case["id"], {}, ANALYST_HEADERS))
    rows = fx.discrepancies_by_detected_category(api, case["id"])
    assert set(rows) == {"WITHHOLDING", "JURISDICTION_ASSIGNMENT"}, rows
    assert rows["WITHHOLDING"]["amount_cents"] == 50000
    assert rows["JURISDICTION_ASSIGNMENT"]["amount_cents"] == 400000
    fx.categorize_all(api, rows)
    amendment = fx.open_amendment(api, case["id"])
    validate_success(api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS))
    validate_success(api.sign_amended_return(amendment["id"], {}, OFFICER_HEADERS))
    validate_success(api.submit_amended_return(amendment["id"], {}, OFFICER_HEADERS))
    return {
        "employer_id": employer["id"],
        "agency_id": agency["id"],
        "employee_id": employee["id"],
        "case_id": case["id"],
        "amended_return_id": amendment["id"],
    }


class TestParallelDimensionJoin:
    def test_a_completed_filing_alone_will_not_join_while_a_statement_is_pending(self, api):
        """Acceptance completes the filing dimension, but the statement dimension is
        sitting in `STMT_PENDING`, so the case stays `OPEN` and no remediation is born.

        PRD: "In both directions the transition requires `filing_status` to be one of `FILING_NOT_REQUIRED` or `FILING_COMPLETE` **and** `statement_status` to be one of `STMT_NOT_REQUIRED`, `STMT_ISSUED` or `STMT_COMPLETE`; neither dimension alone is sufficient."
        PRD: "Two further dimensions may move in the same request, and they move on different triggers: `filing_status` is set to `FILING_PENDING` when any emitted discrepancy carries a `detected_category` of `TAXABLE_WAGE`, `WITHHOLDING` or `DEPOSIT_SHORTFALL`, and `statement_status` is set to `STMT_PENDING` when any emitted discrepancy carries a `detected_category` of `JURISDICTION_ASSIGNMENT`."

        Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_join_before_remediation
        """
        ctx = _two_dimension_scenario(api)

        accepted = validate_success(
            api.record_agency_outcome(
                ctx["amended_return_id"], f.agency_outcome_payload("ACCEPTED"), OFFICER_HEADERS
            )
        )

        assert accepted["status"] == "ACCEPTED"
        assert_amendment_money(
            accepted, tax_delta_cents=50000, interest_cents=4000, penalty_cents=9375
        )

        case = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(
            case,
            status="OPEN",
            filing_status="FILING_COMPLETE",
            statement_status="STMT_PENDING",
        )
        assert_case_rollups(case, total_exposure_cents=63375)

        _, meta = validate_paginated(
            api.list_control_remediations({"correction_case_id": ctx["case_id"]}, AUDITOR_HEADERS)
        )
        assert_pagination(meta, total_count=0)
        employer = validate_success(api.get_employer(ctx["employer_id"], ADMIN_HEADERS))
        assert employer["open_remediation_count"] == 0

    def test_issuing_the_statement_supplies_the_second_dimension_and_the_join_fires(self, api):
        """With the filing dimension already complete, the statement reaching `STMT_ISSUED`
        is what advances the case and creates the single remediation.

        PRD: "The same join rule applies from the other direction. Whenever the statement dimension reaches `STMT_ISSUED` or `STMT_COMPLETE` while `filing_status` is `FILING_NOT_REQUIRED` or `FILING_COMPLETE`, the case advances `OPEN → REMEDIATION_PENDING` with the identical remediation auto-creation and the identical employer counter increment."
        PRD: "If no such collected repayment exists, `wage_delta_cents` is the negation of the jurisdiction removal, `fica_wage_delta_cents` is likewise the negation of the jurisdiction removal, and `withholding_delta_cents` is 0."
        PRD: "The case's `corrected_wage_base_cents` is the base plus the adjustment, in whole cents, with no rounding."

        Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_join_before_remediation
        """
        ctx = _two_dimension_scenario(api)
        validate_success(
            api.record_agency_outcome(
                ctx["amended_return_id"], f.agency_outcome_payload("ACCEPTED"), OFFICER_HEADERS
            )
        )
        statement = fx.draft_statement(
            api, ctx["case_id"], ctx["employee_id"], delivery_channel="PORTAL"
        )
        assert statement["wage_delta_cents"] == -400000
        assert statement["fica_wage_delta_cents"] == -400000
        assert statement["withholding_delta_cents"] == 0

        issued = validate_success(api.issue_statement(statement["id"], {}, PREPARER_HEADERS))

        assert issued["status"] == "ISSUED"
        case = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(
            case,
            status="REMEDIATION_PENDING",
            filing_status="FILING_COMPLETE",
            statement_status="STMT_ISSUED",
        )
        assert_case_rollups(
            case, corrected_wage_base_cents=600000, total_exposure_cents=63375
        )

        remediations, meta = validate_paginated(
            api.list_control_remediations({"correction_case_id": ctx["case_id"]}, AUDITOR_HEADERS)
        )
        assert_pagination(meta, total_count=1)
        assert remediations[0]["status"] == "OPEN"
        assert remediations[0]["root_cause_code"] == "JURISDICTION_MAPPING_ERROR"
        employer = validate_success(api.get_employer(ctx["employer_id"], ADMIN_HEADERS))
        assert employer["open_remediation_count"] == 1


class TestVoidCompensation:
    def test_voiding_a_prepared_amendment_restores_the_pre_prepare_exposure(self, api):
        """A preparation books 335625 cents on the case and on the employer; voiding it
        removes the whole contribution, returns the filing dimension and leaves the
        triage work untouched.

        PRD: "Voiding a `PREPARED` amendment transitions `PREPARED → VOID`, records the `void_reason`, transitions every discrepancy whose `resolved_amended_return_id` names this amendment back `RESOLVED → CATEGORIZED` (clearing both `resolved_amended_return_id` and `resolved_amount_cents` to null, recomputing the case's `open_discrepancy_count`, and incrementing each such discrepancy's `version` by 1), recomputes the case's `total_exposure_cents` now that this amendment has left the summed set, recomputes the employer's `open_exposure_cents`, returns the case's `filing_status` `FILING_IN_PROGRESS → FILING_PENDING` provided no other amendment for the case sits in `PREPARED`, `SIGNED`, `SUBMITTED` or `ACCEPTED`, and increments the amendment's `version` by 1."
        PRD: "Across all three branches the invariant is the same: prepare-then-void restores the employer's `open_exposure_cents` to exactly the value it held before the preparation."

        Design: Difficulty/compensating_invariant/void_restores_employer_open_exposure_to_its_pre_prepare_value
        """
        ctx = fx.federal_categorized(api)
        before = validate_success(api.get_employer(ctx["employer_id"], ADMIN_HEADERS))
        assert before["open_exposure_cents"] == 0

        amendment = fx.open_amendment(api, ctx["case_id"])
        prepared = validate_success(
            api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS)
        )
        assert_amendment_money(prepared, interest_cents=20000, penalty_cents=65625)
        booked = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(booked, filing_status="FILING_IN_PROGRESS")
        assert_case_rollups(booked, total_exposure_cents=335625)
        assert (
            validate_success(api.get_employer(ctx["employer_id"], ADMIN_HEADERS))[
                "open_exposure_cents"
            ]
            == 335625
        )

        voided = validate_success(
            api.void_amended_return(
                amendment["id"],
                f.void_payload(void_reason="Prepared against the wrong accrual date."),
                OFFICER_HEADERS,
            )
        )

        assert voided["status"] == "VOID"
        assert voided["void_reason"] == "Prepared against the wrong accrual date."
        restored = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(restored, status="OPEN", filing_status="FILING_PENDING")
        assert_case_rollups(restored, total_exposure_cents=0, open_discrepancy_count=3)
        after = validate_success(api.get_employer(ctx["employer_id"], ADMIN_HEADERS))
        assert after["open_exposure_cents"] == before["open_exposure_cents"]
        for row in fx.case_discrepancies(api, ctx["case_id"]):
            assert row["status"] == "CATEGORIZED", row

    def test_a_replacement_preparation_books_exactly_the_same_figure_again(self, api):
        """The void is a compensation rather than a loss: a superseding draft prepared on
        the same inputs restores both rollups to the value the voided one held.

        PRD: "A case's `total_exposure_cents` is computed by first summing, over every amended return on the case whose `status` is `PREPARED`, `SIGNED`, `SUBMITTED` or `ACCEPTED`, that return's `tax_delta_cents` plus `interest_cents` plus `penalty_cents`; then summing, over every agency notice on the case whose `abatement_status` is `GRANTED` or `PARTIALLY_GRANTED`, that notice's `waived_penalty_cents` plus `waived_interest_cents`; and then taking the larger of zero and the first sum reduced by the second."
        PRD: "It is recomputed on every write that changes any of that employer's cases' `total_exposure_cents` or `status`, which is what makes signing authority responsive: a waiver granted on one case immediately widens the headroom available to a signature on another, and a void immediately restores it."

        Design: Difficulty/compensating_invariant/void_restores_employer_open_exposure_to_its_pre_prepare_value
        """
        ctx = fx.federal_prepared_amendment(api)
        first = ctx["amended_return_id"]
        validate_success(
            api.void_amended_return(
                first, f.void_payload(void_reason="Re-scoped."), OFFICER_HEADERS
            )
        )
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=0)

        replacement = fx.open_amendment(
            api, ctx["case_id"], supersedes_amended_return_id=first
        )
        reprepared = validate_success(
            api.prepare_amended_return(replacement["id"], {}, PREPARER_HEADERS)
        )

        assert reprepared["status"] == "PREPARED"
        assert reprepared["supersedes_amended_return_id"] == first
        assert_amendment_money(
            reprepared,
            tax_delta_cents=250000,
            interest_cents=20000,
            penalty_cents=65625,
        )
        case = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(case, filing_status="FILING_IN_PROGRESS")
        assert_case_rollups(case, total_exposure_cents=335625)
        employer = validate_success(api.get_employer(ctx["employer_id"], ADMIN_HEADERS))
        assert employer["open_exposure_cents"] == 335625


class TestComputedMoneyViews:
    def test_the_exposure_summary_reconciles_the_case_in_six_figures(self, api):
        """With one prepared amendment, no notice and no repayment, the summary reports the
        gross as the net, the untouched wage base and nothing recovered — and reading it
        changes nothing.

        PRD: "Finally, a case exposes a computed read that assembles the whole ledger in one place: `gross_exposure_cents` for the summed amendment exposure before waivers, `waived_cents` for the summed granted and partially granted waivers, `total_exposure_cents` for the floored net, `corrected_wage_base_cents` for the wage base as the issued statements now report it, `repayment_recovered_cents` for the agency-recoverable amounts actually collected back from employees, and `dominant_root_cause_code`, which is null when no discrepancy on the case has been categorized."
        PRD: "Together these six figures reconcile the case: what the amendments assessed, what the agencies forgave, what remains owed, what the statements now say, what came back from employees, and why it happened in the first place."

        Design: Corner/endpoints/exposure_summary_recomputes_the_case_money_view
        """
        ctx = fx.federal_prepared_amendment(api)
        case = fx.read_case(api, ctx["case_id"])
        assert_case_rollups(case, total_exposure_cents=335625)

        summary = validate_success(
            api.get_exposure_summary(
                ctx["case_id"], make_employer_rep_headers(ctx["employer_id"])
            )
        )

        assert_exposure_summary(
            summary,
            gross_exposure_cents=335625,
            waived_cents=0,
            total_exposure_cents=335625,
            corrected_wage_base_cents=5000000,
            repayment_recovered_cents=0,
        )
        assert summary["dominant_root_cause_code"] is not None
        assert summary["dominant_root_cause_code"] == case["dominant_root_cause_code"]
        assert fx.read_case(api, ctx["case_id"])["version"] == case["version"]

    def test_preparation_publishes_every_derived_rollup_inside_the_same_request(self, api):
        """The prepare response already carries the interest and the penalty, and the very
        first read of the case, of the employer and of the summary all agree with it.

        PRD: "Recomputation is immediate and transitive. When an operation changes a case's exposure, the owning employer's open exposure is recomputed in the same request."
        PRD: "A cascade that reaches five entities deep completes entirely before the response is returned; there is no eventual consistency anywhere in this API."

        Design: Corner/consistency model/derived_rollups_are_visible_in_the_same_response
        """
        ctx = fx.federal_categorized(api)
        amendment = fx.open_amendment(api, ctx["case_id"])

        prepared = validate_success(
            api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS)
        )

        assert prepared["interest_cents"] == 20000
        assert prepared["penalty_cents"] == 65625

        case = fx.read_case(api, ctx["case_id"])
        assert case["total_exposure_cents"] == 335625
        assert_case_dimensions(case, filing_status="FILING_IN_PROGRESS")

        employer = validate_success(api.get_employer(ctx["employer_id"], ADMIN_HEADERS))
        assert employer["open_exposure_cents"] == 335625

        summary = validate_success(api.get_exposure_summary(ctx["case_id"], PREPARER_HEADERS))
        assert_exposure_summary(
            summary,
            gross_exposure_cents=335625,
            waived_cents=0,
            total_exposure_cents=335625,
        )
