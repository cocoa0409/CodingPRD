"""Wage repayment recovery: the basis fork, the exact-collection rule and the cascade.

Recovery runs the error in the opposite direction — the employee was overpaid — and
the whole of it turns on one comparison between two years. This file pins both sides
of that fork from identical inputs, the renegotiation that re-derives it, the
exact-match collection rule, and the five-link cascade that collection heads, which
is the only chain in the system that drags its parent case backwards.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_RECOVERY_YEAR,
    ERR_OVERCOLLECTION,
)
from test_helpers.assertions import (
    assert_case_dimensions,
    assert_case_rollups,
    assert_pagination,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    OFFICER_HEADERS,
    PREPARER_HEADERS,
    make_employee_headers,
)


def _basis(repayment, basis, due, recoverable):
    assert repayment["recovery_basis"] == basis, repayment
    assert repayment["employee_due_cents"] == due, repayment
    assert repayment["agency_recoverable_cents"] == recoverable, repayment


class TestRecoveryBasisVariants:
    def test_a_same_year_recovery_nets_both_withheld_components_out_of_what_is_due(self, api):
        """The employee only ever received the net, so the same-year basis asks for 309400
        of the 400000 gross and books the remaining 90600 as reclaimable.

        PRD: "When `recovery_tax_year` equals `overpayment_tax_year`, the wage statement for the year is still open and the employer can still reverse income-tax withholding inside the same reporting year; the basis recorded is `SAME_YEAR_NET`, `employee_due_cents` is `overpaid_gross_cents` reduced by `overpaid_income_tax_withheld_cents` and further reduced by `overpaid_fica_withheld_cents` — the net the employee actually received — and `agency_recoverable_cents` is `overpaid_income_tax_withheld_cents` plus `overpaid_fica_withheld_cents`, since both are reclaimable from the agencies."
        PRD: "The row is written in `status` `PROPOSED` with `collected_cents` at 0 and `write_off_reason` at null."

        Design: Difficulty/dual_variant_calc/repayment_same_year_net_versus_prior_year_gross_recovery
        """
        ctx = fx.jurisdiction_scenario(api)

        same_year = validate_success(
            api.create_wage_repayment(
                f.wage_repayment_payload(
                    ctx["case_id"],
                    ctx["employee_id"],
                    recovery_tax_year=2025,
                    installment_count=1,
                ),
                ANALYST_HEADERS,
            ),
            201,
        )

        _basis(same_year, "SAME_YEAR_NET", 309400, 90600)
        assert same_year["status"] == "PROPOSED"
        assert same_year["collected_cents"] == 0
        assert same_year["write_off_reason"] is None
        assert (
            same_year["employee_due_cents"] + same_year["agency_recoverable_cents"] == 400000
        )

    def test_a_later_recovery_year_leaves_the_income_tax_credited_to_the_employee(self, api):
        """Identical amounts, one year later: the employee now owes the whole gross and only
        the social-insurance share is reclaimable, so the two figures no longer sum to the gross.

        PRD: "When `recovery_tax_year` is later than `overpayment_tax_year`, the prior year's statement has already been filed and the income tax withheld was already credited to the employee, so the employer cannot reclaim it; the basis recorded is `PRIOR_YEAR_GROSS`, `employee_due_cents` is the full `overpaid_gross_cents`, and `agency_recoverable_cents` is `overpaid_fica_withheld_cents` alone."
        PRD: "The divergence is substantial: for an overpaid gross of 400000 cents with 60000 cents of income tax and 30600 cents of social-insurance tax withheld, `SAME_YEAR_NET` yields an amount due of 309400 cents and an agency-recoverable amount of 90600 cents, while `PRIOR_YEAR_GROSS` on identical inputs yields 400000 cents and 30600 cents."

        Design: Difficulty/dual_variant_calc/repayment_same_year_net_versus_prior_year_gross_recovery
        """
        ctx = fx.jurisdiction_scenario(api)
        lee = fx.make_employee(
            api, ctx["employer_id"], full_name="Lee Park", national_id_last4="7130"
        )
        same_year = validate_success(
            api.create_wage_repayment(
                f.wage_repayment_payload(
                    ctx["case_id"],
                    ctx["employee_id"],
                    recovery_tax_year=2025,
                    installment_count=1,
                ),
                ANALYST_HEADERS,
            ),
            201,
        )

        prior_year = validate_success(
            api.create_wage_repayment(
                f.wage_repayment_payload(
                    ctx["case_id"], lee["id"], recovery_tax_year=2026, installment_count=1
                ),
                ANALYST_HEADERS,
            ),
            201,
        )

        _basis(prior_year, "PRIOR_YEAR_GROSS", 400000, 30600)
        assert (
            prior_year["employee_due_cents"] + prior_year["agency_recoverable_cents"] == 430600
        )
        _basis(same_year, "SAME_YEAR_NET", 309400, 90600)
        assert prior_year["overpaid_gross_cents"] == same_year["overpaid_gross_cents"]
        assert (
            prior_year["overpaid_income_tax_withheld_cents"]
            == same_year["overpaid_income_tax_withheld_cents"]
        )
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), repayment_recovered_cents=0)

    def test_renegotiating_the_recovery_year_re_derives_the_basis_and_clears_the_terms(self, api):
        """The client never supplies the basis, so moving recovery into the following year
        rewrites both derived amounts and puts the row back in front of the employee.

        PRD: "It may revise `overpaid_gross_cents`, `overpaid_income_tax_withheld_cents`, `overpaid_fica_withheld_cents`, `recovery_tax_year` and `installment_count`, and it re-runs the recovery-basis computation over the revised inputs — so a changed recovery year genuinely flips the basis and rewrites both `employee_due_cents` and `agency_recoverable_cents`."
        PRD: "The row transitions `AGREED → PROPOSED`, `installment_count` is cleared back to null, and the repayment's `version` is incremented by 1."

        Design: Corner/calculations/recovery_basis_is_selected_at_creation_and_reselected_on_renegotiate
        """
        ctx = fx.jurisdiction_scenario(api)
        agreed = fx.agreed_repayment(api, ctx["case_id"], ctx["employee_id"], installment_count=4)
        _basis(agreed, "SAME_YEAR_NET", 309400, 90600)
        assert agreed["status"] == "AGREED"
        assert agreed["installment_count"] == 4

        renegotiated = validate_success(
            api.renegotiate_wage_repayment(
                agreed["id"], f.renegotiate_payload(recovery_tax_year=2026), ANALYST_HEADERS
            )
        )

        _basis(renegotiated, "PRIOR_YEAR_GROSS", 400000, 30600)
        assert renegotiated["status"] == "PROPOSED"
        assert renegotiated["installment_count"] is None
        assert renegotiated["collected_cents"] == 0
        assert renegotiated["version"] == agreed["version"] + 1

    def test_recovering_before_the_overpayment_year_is_refused_before_any_basis_is_chosen(
        self, api
    ):
        """Money cannot come back before it went out, so the proposal is rejected outright
        and no row — and therefore no basis — is ever written.

        PRD: "Two arithmetic conditions are checked together: `recovery_tax_year` may not be earlier than `overpayment_tax_year`, and the two withheld components added together may not exceed `overpaid_gross_cents`."
        PRD: "Either violation is refused with `ERR_INVALID_RECOVERY_YEAR`."

        Design: Corner/validations/repayment_with_recovery_year_before_overpayment_year_returns_invalid_recovery_year
        """
        ctx = fx.jurisdiction_scenario(api)

        validate_error(
            api.create_wage_repayment(
                f.wage_repayment_payload(
                    ctx["case_id"],
                    ctx["employee_id"],
                    overpayment_tax_year=2025,
                    recovery_tax_year=2024,
                ),
                ANALYST_HEADERS,
            ),
            ERR_INVALID_RECOVERY_YEAR,
            400,
        )

        _, meta = validate_paginated(
            api.list_wage_repayments({"correction_case_id": ctx["case_id"]}, ANALYST_HEADERS)
        )
        assert_pagination(meta, total_count=0)


class TestExactCollection:
    def test_posting_the_gross_overpayment_is_an_over_collection(self, api):
        """400000 is the intuitive figure and the wrong one: the employee owes the net 309400,
        so the gross is refused and only the exact amount moves the row.

        PRD: "Collection is exact or it is nothing."
        PRD: "Available from `AGREED`, it posts a `collected_cents` figure that must equal `employee_due_cents` precisely; anything larger is an over-collection and anything smaller is an under-collection, and either is refused with `ERR_OVERCOLLECTION`."
        PRD: "On success the repayment transitions `AGREED → COLLECTED`, the posted amount is stored in `collected_cents`, the case's `repayment_recovered_cents` — defined as the sum of `agency_recoverable_cents` over every repayment on the case whose `status` is `COLLECTED` — is recomputed, and the repayment's `version` is incremented by 1."

        Design: Corner/errors/overcollection_of_a_repayment_is_rejected
        """
        ctx = fx.jurisdiction_scenario(api)
        agreed = fx.agreed_repayment(api, ctx["case_id"], ctx["employee_id"])
        _basis(agreed, "SAME_YEAR_NET", 309400, 90600)

        validate_error(
            api.collect_wage_repayment(
                agreed["id"], f.collect_payload(400000), ANALYST_HEADERS
            ),
            ERR_OVERCOLLECTION,
            422,
        )

        held = validate_success(api.get_wage_repayment(agreed["id"], ANALYST_HEADERS))
        assert held["status"] == "AGREED"
        assert held["collected_cents"] == 0
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), repayment_recovered_cents=0)

        collected = validate_success(
            api.collect_wage_repayment(
                agreed["id"], f.collect_payload(309400), ANALYST_HEADERS
            )
        )

        assert collected["status"] == "COLLECTED"
        assert collected["collected_cents"] == 309400
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), repayment_recovered_cents=90600)


def _issued_statement_then_prior_year_agreement(api):
    """A MAIL statement issued into a joined case, then a prior-year repayment agreed by
    the employee, so collection has something to un-do."""
    ctx = fx.jurisdiction_issued_statement(api)
    ctx["repayment"] = fx.agreed_repayment(
        api, ctx["case_id"], ctx["employee_id"], recovery_tax_year=2026
    )
    return ctx


class TestCollectionCascade:
    def test_collection_voids_the_issued_statement_and_spawns_a_prior_year_successor(self, api):
        """Links one through three: the row settles, the statement in the employee's hands is
        retired, and its replacement carries the prior-year box treatment — box 1 and box 2
        untouched by the repayment, only social-insurance wages reduced.

        PRD: "**Link two:** every corrected wage statement belonging to the case whose `tax_year` equals this repayment's `overpayment_tax_year` and whose status is `ISSUED` or `ACKNOWLEDGED` transitions to `VOIDED` and spawns a successor in `DRAFT`, each successor carrying `supersedes_statement_id` pointing at its predecessor and a `sequence_no` one greater, with box deltas recomputed — and because a collected repayment is now in play, those recomputed deltas take the current-year or prior-year box treatment of §3.6 according to the repayment's `recovery_basis`."
        PRD: "If instead the collected repayment's `recovery_basis` is `PRIOR_YEAR_GROSS` — the prior-year box treatment, in which box 1 taxable wages and box 2 withholding are left untouched and only the social-insurance wages move — then `wage_delta_cents` is the negation of the jurisdiction removal alone, `fica_wage_delta_cents` is the negation of the jurisdiction removal reduced further by the repayment's `overpaid_gross_cents`, and `withholding_delta_cents` is 0."

        Design: Difficulty/transitive_cascade/repayment_collection_cascade_depth_five
        """
        ctx = _issued_statement_then_prior_year_agreement(api)
        first_id = ctx["statement"]["id"]

        collected = validate_success(
            api.collect_wage_repayment(
                ctx["repayment"]["id"], f.collect_payload(400000), ANALYST_HEADERS
            )
        )

        assert collected["status"] == "COLLECTED"
        _basis(collected, "PRIOR_YEAR_GROSS", 400000, 30600)
        assert collected["collected_cents"] == 400000

        retired = validate_success(api.get_statement(first_id, PREPARER_HEADERS))
        assert retired["status"] == "VOIDED"

        successors, meta = validate_paginated(
            api.list_statements(
                {"correction_case_id": ctx["case_id"], "supersedes_statement_id": first_id},
                PREPARER_HEADERS,
            )
        )
        assert_pagination(meta, total_count=1)
        successor = successors[0]
        assert successor["sequence_no"] == 2
        assert successor["status"] == "DRAFT"
        assert successor["supersedes_statement_id"] == first_id
        assert successor["is_prior_year"] is True
        assert successor["wage_delta_cents"] == -400000
        assert successor["fica_wage_delta_cents"] == -800000
        assert successor["withholding_delta_cents"] == 0

    def test_the_cascade_drags_the_case_backwards_out_of_remediation(self, api):
        """Links four and five run the case in reverse: the statement dimension falls back to
        `STMT_REISSUE_PENDING`, the overall status un-joins to `OPEN`, and with no issued
        statement left the wage base reverts to the raw register total.

        PRD: "**Link four:** the case's statement dimension flips `STMT_ISSUED → STMT_REISSUE_PENDING`."
        PRD: "**Link five:** that flip reverts the case's overall `status` `REMEDIATION_PENDING → OPEN` and recomputes the employer's `open_exposure_cents`, re-admitting the case's full exposure."
        PRD: "A collection late in a case's life therefore reopens it, and the statement work has to be redone with the repayment folded in."

        Design: Difficulty/transitive_cascade/repayment_collection_cascade_depth_five
        """
        ctx = _issued_statement_then_prior_year_agreement(api)
        before = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(
            before,
            status="REMEDIATION_PENDING",
            filing_status="FILING_NOT_REQUIRED",
            statement_status="STMT_ISSUED",
        )
        assert_case_rollups(before, corrected_wage_base_cents=600000)

        validate_success(
            api.collect_wage_repayment(
                ctx["repayment"]["id"], f.collect_payload(400000), ANALYST_HEADERS
            )
        )

        after = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(
            after,
            status="OPEN",
            filing_status="FILING_NOT_REQUIRED",
            statement_status="STMT_REISSUE_PENDING",
        )
        assert_case_rollups(
            after, corrected_wage_base_cents=1000000, repayment_recovered_cents=30600
        )
        employee = validate_success(api.get_employee(ctx["employee_id"], ANALYST_HEADERS))
        assert employee["active_statement_count"] == 0


class TestWriteOffBranches:
    def test_writing_off_before_the_employee_agreed_cancels_the_proposal_instead(self, api):
        """One trigger, two targets chosen by the from-state: from `PROPOSED` there was never a
        balance to write off, so the terminal status records a cancellation.

        PRD: "The same act performed earlier means something different: from `PROPOSED`, where the employee never agreed to anything, the write-off cancels the proposal instead of writing off a balance, transitioning `PROPOSED → CANCELLED`, recording the `write_off_reason`, and incrementing `version` by 1."

        Design: Corner/state_machines/write_off_on_a_proposed_repayment_cancels_instead_of_writing_off
        """
        ctx = fx.jurisdiction_scenario(api)
        proposed = fx.proposed_repayment(api, ctx["case_id"], ctx["employee_id"])
        assert proposed["status"] == "PROPOSED"

        cancelled = validate_success(
            api.write_off_wage_repayment(
                proposed["id"],
                f.write_off_payload(
                    write_off_reason="Employee separated before any installment was agreed."
                ),
                OFFICER_HEADERS,
            )
        )

        assert cancelled["status"] == "CANCELLED"
        assert cancelled["status"] != "WRITTEN_OFF"
        assert cancelled["write_off_reason"]
        assert cancelled["collected_cents"] == 0
        assert cancelled["version"] == proposed["version"] + 1
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), repayment_recovered_cents=0)

    def test_the_employee_cannot_agree_to_a_cancelled_proposal(self, api):
        """The agree call is issued by exactly the right identity from what was a legal
        from-state, so nothing but terminality can refuse it — and terminality does.

        PRD: "`COLLECTED`, `WRITTEN_OFF` and `CANCELLED` are all terminal, and a further transition attempt out of any of them is refused with `ERR_ALREADY_TERMINAL`."
        PRD: "The acting `X-User-ID` must equal the repayment's `employee_id`, and the owning case's `status` must be `OPEN` or `REMEDIATION_PENDING` — a closed case cannot acquire new agreements."

        Design: Corner/state_machines/cancelled_repayment_cannot_be_agreed_returns_already_terminal
        """
        ctx = fx.jurisdiction_scenario(api)
        proposed = fx.proposed_repayment(api, ctx["case_id"], ctx["employee_id"])
        cancelled = validate_success(
            api.write_off_wage_repayment(
                proposed["id"],
                f.write_off_payload(
                    write_off_reason="Employee separated before any installment was agreed."
                ),
                OFFICER_HEADERS,
            )
        )
        assert cancelled["status"] == "CANCELLED"

        validate_error(
            api.agree_wage_repayment(
                proposed["id"],
                f.agree_payload(4),
                make_employee_headers(ctx["employee_id"]),
            ),
            ERR_ALREADY_TERMINAL,
            409,
        )

        unchanged = validate_success(api.get_wage_repayment(proposed["id"], ANALYST_HEADERS))
        assert unchanged["status"] == "CANCELLED"
        assert unchanged["installment_count"] is None
