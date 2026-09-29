"""Corrected wage statements: box deltas, the reissue cycle and its conserved totals.

The statement chain is the only genuine cycle in the case lifecycle, so this file
walks it: an issued statement comes back undeliverable, is superseded, and the
successor restores every derived figure the predecessor had produced. It also
pins what the boxes say before and after a repayment is actually collected, and
the two refusals that guard statement creation.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CHANNEL_NOT_UNDELIVERABLE_CAPABLE,
    ERR_NO_REPORTABLE_DELTA,
    ERR_PRIOR_YEAR_WINDOW_CLOSED,
    ERR_SCOPE_MISMATCH,
    ERR_STALE_STATEMENT_VERSION,
)
from test_helpers.assertions import (
    assert_case_dimensions,
    assert_case_rollups,
    assert_pagination,
)
from test_helpers.constants import CANON_CLOCK
from test_helpers.test_users import ANALYST_HEADERS, PREPARER_HEADERS


def _statement_deltas(statement, wage, fica, withholding):
    assert statement["wage_delta_cents"] == wage, statement
    assert statement["fica_wage_delta_cents"] == fica, statement
    assert statement["withholding_delta_cents"] == withholding, statement


def _active_count(api, employee_id):
    return validate_success(api.get_employee(employee_id, ANALYST_HEADERS))[
        "active_statement_count"
    ]


class TestReissueCycle:
    def test_undeliverable_mail_reissued_retires_the_predecessor_and_reopens_the_case(self, api):
        """The successor is created inside the reissue call with its own sequence number and
        a link back, while the case is pulled out of `REMEDIATION_PENDING` again.

        PRD: "The predecessor transitions to `VOIDED`, which is terminal, and a successor is created in `status` `DRAFT` whose `supersedes_statement_id` names the predecessor, whose `sequence_no` is one greater than the predecessor's, and whose `correction_case_id`, `employee_id` and `tax_year` are copied from the predecessor; the successor's own box deltas are computed afresh."
        PRD: "When it fires while the case's overall `status` is `REMEDIATION_PENDING`, the case is reopened `REMEDIATION_PENDING → OPEN` and the employer's `open_exposure_cents` is recomputed, because the case re-enters the employer's open set and re-admits its whole `total_exposure_cents`."

        Design: Difficulty/non_linear_state_machine/statement_reissue_cycle_supersedes_prior_statement
        """
        ctx = fx.jurisdiction_issued_statement(api)
        first = ctx["statement"]
        assert first["sequence_no"] == 1
        assert first["supersedes_statement_id"] is None
        assert_case_dimensions(
            fx.read_case(api, ctx["case_id"]),
            status="REMEDIATION_PENDING",
            statement_status="STMT_ISSUED",
        )

        returned = validate_success(
            api.report_statement_undeliverable(
                first["id"],
                f.undeliverable_payload(
                    undeliverable_reason="Returned by carrier: addressee moved, no forwarding order."
                ),
                PREPARER_HEADERS,
            )
        )
        assert returned["status"] == "RETURNED_UNDELIVERABLE"

        successor = validate_success(
            api.reissue_statement(
                first["id"],
                f.reissue_payload(
                    returned["version"],
                    delivery_channel="PORTAL",
                    reissue_reason="Redelivered through the employee portal.",
                ),
                PREPARER_HEADERS,
            ),
            201,
        )

        assert successor["status"] == "DRAFT"
        assert successor["sequence_no"] == 2
        assert successor["supersedes_statement_id"] == first["id"]
        assert successor["delivery_channel"] == "PORTAL"
        assert successor["correction_case_id"] == ctx["case_id"]
        assert successor["employee_id"] == ctx["employee_id"]
        assert successor["tax_year"] == 2025
        _statement_deltas(successor, -400000, -400000, 0)

        retired = validate_success(api.get_statement(first["id"], PREPARER_HEADERS))
        assert retired["status"] == "VOIDED"
        assert_case_dimensions(
            fx.read_case(api, ctx["case_id"]),
            status="OPEN",
            statement_status="STMT_REISSUE_PENDING",
        )

    def test_issuing_the_successor_closes_the_cycle_back_into_remediation_pending(self, api):
        """The statement dimension re-enters `STMT_ISSUED` from the reissue-pending side and
        the case joins a second time, which is what makes this a cycle rather than a path.

        PRD: "In the same request the case's statement dimension advances — `STMT_PENDING → STMT_ISSUED` for a first statement, or `STMT_REISSUE_PENDING → STMT_ISSUED` for a successor — the employee's `active_statement_count` and the case's `corrected_wage_base_cents` are recomputed, the case's `version` is incremented by 1, and the statement's own `version` is incremented by 1."
        PRD: "The full cycle — `ISSUED → RETURNED_UNDELIVERABLE → VOIDED`, then a successor `DRAFT → ISSUED` — is traceable through the chain of `supersedes_statement_id` links."

        Design: Difficulty/non_linear_state_machine/statement_reissue_cycle_supersedes_prior_statement
        """
        ctx = fx.jurisdiction_issued_statement(api)
        first = ctx["statement"]
        returned = validate_success(
            api.report_statement_undeliverable(
                first["id"], f.undeliverable_payload(), PREPARER_HEADERS
            )
        )
        successor = validate_success(
            api.reissue_statement(
                first["id"],
                f.reissue_payload(returned["version"], delivery_channel="PORTAL"),
                PREPARER_HEADERS,
            ),
            201,
        )
        assert_case_dimensions(
            fx.read_case(api, ctx["case_id"]),
            status="OPEN",
            statement_status="STMT_REISSUE_PENDING",
        )

        issued = validate_success(api.issue_statement(successor["id"], {}, PREPARER_HEADERS))

        assert issued["status"] == "ISSUED"
        assert issued["issued_at"] == "2026-04-30T00:00:00.000Z"
        assert_case_dimensions(
            fx.read_case(api, ctx["case_id"]),
            status="REMEDIATION_PENDING",
            statement_status="STMT_ISSUED",
        )
        chain, meta = validate_paginated(
            api.list_statements({"supersedes_statement_id": first["id"]}, PREPARER_HEADERS)
        )
        assert_pagination(meta, total_count=1)
        assert chain[0]["id"] == successor["id"]


class TestWageBaseConservation:
    def test_taking_the_statement_out_of_the_issued_set_restores_the_register_total(self, api):
        """The wage base is a recount, not a running balance: once the mailed statement is
        `RETURNED_UNDELIVERABLE` its delta stops contributing and the raw register total
        of 1000000 cents comes back exactly.

        PRD: "The statement transitions `ISSUED → RETURNED_UNDELIVERABLE`, the reason is recorded, the employee's `active_statement_count` is recomputed because this statement has left the counted set, the case's `corrected_wage_base_cents` is recomputed because the statement has stopped contributing its wage delta, and the statement's `version` is incremented by 1."
        PRD: "Statements in `DRAFT`, `RETURNED_UNDELIVERABLE` or `VOIDED` contribute nothing to the adjustment term — which is precisely what allows a void paired with a successor issuance carrying the same wage delta to leave the corrected wage base exactly where it was."

        Design: Difficulty/compensating_invariant/reissue_conserves_case_corrected_wage_base
        """
        ctx = fx.jurisdiction_issued_statement(api)
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), corrected_wage_base_cents=600000)
        assert _active_count(api, ctx["employee_id"]) == 1

        returned = validate_success(
            api.report_statement_undeliverable(
                ctx["statement"]["id"],
                f.undeliverable_payload(
                    undeliverable_reason="Carrier returned the envelope: no such street number."
                ),
                PREPARER_HEADERS,
            )
        )

        assert returned["status"] == "RETURNED_UNDELIVERABLE"
        assert returned["wage_delta_cents"] == -400000
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), corrected_wage_base_cents=1000000)
        assert _active_count(api, ctx["employee_id"]) == 0

    def test_the_successor_restores_the_same_wage_base_and_redirects_future_paper(self, api):
        """A `DRAFT` successor contributes nothing, so the base holds at the register total
        until the successor issues — at which point it lands back on 600000 exactly.

        PRD: "The case's `corrected_wage_base_cents` is the base plus the adjustment, in whole cents, with no rounding."
        PRD: "Optional inputs shape the successor and its delivery: a replacement `delivery_channel`, a `reissue_reason` recorded with the act, and a `corrected_mailing_state_code` which, when supplied, updates the employee's `mailing_state_code` so future paper reaches them."

        Design: Difficulty/compensating_invariant/reissue_conserves_case_corrected_wage_base
        """
        ctx = fx.jurisdiction_issued_statement(api)
        first = ctx["statement"]
        returned = validate_success(
            api.report_statement_undeliverable(
                first["id"], f.undeliverable_payload(), PREPARER_HEADERS
            )
        )

        successor = validate_success(
            api.reissue_statement(
                first["id"],
                f.reissue_payload(
                    returned["version"],
                    delivery_channel="PORTAL",
                    reissue_reason="Switching to portal delivery.",
                    corrected_mailing_state_code="PA",
                ),
                PREPARER_HEADERS,
            ),
            201,
        )

        assert successor["status"] == "DRAFT"
        assert successor["wage_delta_cents"] == -400000
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), corrected_wage_base_cents=1000000)
        assert _active_count(api, ctx["employee_id"]) == 0
        employee = validate_success(api.get_employee(ctx["employee_id"], ANALYST_HEADERS))
        assert employee["mailing_state_code"] == "PA"

        validate_success(api.issue_statement(successor["id"], {}, PREPARER_HEADERS))

        assert_case_rollups(fx.read_case(api, ctx["case_id"]), corrected_wage_base_cents=600000)
        assert _active_count(api, ctx["employee_id"]) == 1
        rows, meta = validate_paginated(
            api.list_statements({"correction_case_id": ctx["case_id"]}, PREPARER_HEADERS)
        )
        assert_pagination(meta, total_count=2)
        assert [row["status"] for row in rows].count("ISSUED") == 1


def _no_delta_scenario(api):
    """A withholding-only case, whose statement boxes would all be zero, plus a valid
    employee belonging to a second employer."""
    fx.set_clock(api, CANON_CLOCK)
    acme = fx.make_employer(api, deposit_schedule="MONTHLY")
    beacon = fx.make_employer(
        api, legal_name="Beacon Foods", fein="98-7654321", deposit_schedule="MONTHLY"
    )
    agency = fx.make_federal_agency(api)
    dana = fx.make_employee(api, acme["id"])
    ivy = fx.make_employee(
        api, beacon["id"], full_name="Ivy Stone", national_id_last4="3390"
    )
    fx.make_register_line(
        api,
        acme["id"],
        dana["id"],
        agency["id"],
        taxable_wage_cents=1000000,
        withheld_cents=150000,
        work_jurisdiction_code="US",
    )
    fx.make_filed_return(
        api,
        acme["id"],
        agency["id"],
        reported_taxable_wage_cents=1000000,
        reported_withheld_cents=100000,
    )
    case = fx.make_correction_case(api, acme["id"], agency["id"])
    validate_success(api.reconcile_case(case["id"], {}, ANALYST_HEADERS))
    rows = fx.discrepancies_by_detected_category(api, case["id"])
    assert set(rows) == {"WITHHOLDING"}, rows
    fx.categorize_all(api, rows)
    return {
        "case_id": case["id"],
        "own_employee_id": dana["id"],
        "foreign_employee_id": ivy["id"],
    }


class TestStatementCreationLadder:
    def test_a_foreign_employee_is_a_scope_mismatch_before_the_delta_check_runs(self, api):
        """Both refusals apply to the same call and both are 422s, so only the error id
        distinguishes them: the referential rule is reported and the empty-delta rule is not.

        PRD: "The employee must belong to the case's employer or the request is refused with `ERR_SCOPE_MISMATCH`."
        PRD: "Business referential checks follow in this order: scope agreement (`ERR_SCOPE_MISMATCH`), registration coverage (`ERR_AGENCY_ACCOUNT_NOT_ACTIVE`), remediation completeness at closure (`ERR_REMEDIATION_NOT_VERIFIED`), the empty-case guard on amendment creation (`ERR_CASE_HAS_NO_DISCREPANCIES`), and repayment settlement at closure (`ERR_REPAYMENT_NOT_SETTLED`)."

        Design: Difficulty/priority_pair_validation_conflict/scope_mismatch_precedes_no_reportable_delta_on_statement_create
        """
        ctx = _no_delta_scenario(api)

        validate_error(
            api.create_statement(
                f.statement_payload(
                    ctx["case_id"], ctx["foreign_employee_id"], delivery_channel="PORTAL"
                ),
                PREPARER_HEADERS,
            ),
            ERR_SCOPE_MISMATCH,
            422,
        )

        _, meta = validate_paginated(
            api.list_statements({"correction_case_id": ctx["case_id"]}, PREPARER_HEADERS)
        )
        assert_pagination(meta, total_count=0)

    def test_the_correctly_scoped_employee_then_surfaces_the_empty_delta_refusal(self, api):
        """Swapping in the case's own employee removes the referential violation, and the
        business constraint that was hidden behind it becomes the answer.

        PRD: "A statement with nothing to say may not exist. If the computation yields 0 for all three of `wage_delta_cents`, `fica_wage_delta_cents` and `withholding_delta_cents`, the draft is refused with `ERR_NO_REPORTABLE_DELTA`."
        PRD: "Business constraints follow, in this order: the amendment slot rule (`ERR_AMENDMENT_SLOT_OCCUPIED`), the registration period overlap rule (`ERR_ACCOUNT_PERIOD_OVERLAP`), the uniqueness family (`ERR_DUPLICATE_FILED_RETURN`, `ERR_DUPLICATE_EMPLOYER_FEIN`, `ERR_DUPLICATE_NOTICE_NUMBER`, `ERR_DUPLICATE_AGENCY_CODE`), the zero-delta statement rule (`ERR_NO_REPORTABLE_DELTA`), the filed-return prerequisite for reconciliation (`ERR_NO_FILED_RETURN_FOR_PERIOD`), and the delivery-channel rule for undeliverable reports (`ERR_CHANNEL_NOT_UNDELIVERABLE_CAPABLE`)."

        Design: Difficulty/priority_pair_validation_conflict/scope_mismatch_precedes_no_reportable_delta_on_statement_create
        """
        ctx = _no_delta_scenario(api)
        validate_error(
            api.create_statement(
                f.statement_payload(
                    ctx["case_id"], ctx["foreign_employee_id"], delivery_channel="PORTAL"
                ),
                PREPARER_HEADERS,
            ),
            ERR_SCOPE_MISMATCH,
            422,
        )

        validate_error(
            api.create_statement(
                f.statement_payload(
                    ctx["case_id"], ctx["own_employee_id"], delivery_channel="PORTAL"
                ),
                PREPARER_HEADERS,
            ),
            ERR_NO_REPORTABLE_DELTA,
            422,
        )

        _, meta = validate_paginated(
            api.list_statements({"correction_case_id": ctx["case_id"]}, PREPARER_HEADERS)
        )
        assert_pagination(meta, total_count=0)
        assert_case_dimensions(
            fx.read_case(api, ctx["case_id"]), statement_status="STMT_NOT_REQUIRED"
        )


def _issued_statement_then_agreed_repayment(api):
    """A PORTAL statement issued while no repayment existed, followed by a same-year
    repayment of 400000/60000/30600 that the employee has agreed to."""
    ctx = fx.jurisdiction_issued_statement(api, delivery_channel="PORTAL")
    ctx["repayment"] = fx.agreed_repayment(api, ctx["case_id"], ctx["employee_id"])
    return ctx


class TestBoxDeltasFollowTheRepayment:
    def test_an_agreed_repayment_moves_no_box_and_no_rollup(self, api):
        """The recovery basis and both derived amounts are already fixed on the row, yet
        the statement in front of the employee still shows only the jurisdiction removal.

        PRD: "Repayments in `PROPOSED`, `AGREED`, `WRITTEN_OFF` or `CANCELLED` never move a box."
        PRD: "When `recovery_tax_year` equals `overpayment_tax_year`, the wage statement for the year is still open and the employer can still reverse income-tax withholding inside the same reporting year; the basis recorded is `SAME_YEAR_NET`, `employee_due_cents` is `overpaid_gross_cents` reduced by `overpaid_income_tax_withheld_cents` and further reduced by `overpaid_fica_withheld_cents` — the net the employee actually received — and `agency_recoverable_cents` is `overpaid_income_tax_withheld_cents` plus `overpaid_fica_withheld_cents`, since both are reclaimable from the agencies."

        Design: Difficulty/cross_entity_state_dependency/statement_box_deltas_depend_on_repayment_reaching_collected
        """
        ctx = _issued_statement_then_agreed_repayment(api)
        repayment = ctx["repayment"]

        assert repayment["status"] == "AGREED"
        assert repayment["recovery_basis"] == "SAME_YEAR_NET"
        assert repayment["employee_due_cents"] == 309400
        assert repayment["agency_recoverable_cents"] == 90600

        statement = validate_success(
            api.get_statement(ctx["statement"]["id"], PREPARER_HEADERS)
        )
        assert statement["status"] == "ISSUED"
        _statement_deltas(statement, -400000, -400000, 0)
        assert_case_rollups(
            fx.read_case(api, ctx["case_id"]),
            corrected_wage_base_cents=600000,
            repayment_recovered_cents=0,
        )

    def test_collection_voids_the_statement_and_the_successor_carries_the_net_boxes(self, api):
        """Nothing about the repayment's amounts changes; only its state does, and that alone
        pulls the repaid gross out of boxes 1 and 3/5 and the repaid income tax out of box 2.

        PRD: "**Link two:** every corrected wage statement belonging to the case whose `tax_year` equals this repayment's `overpayment_tax_year` and whose status is `ISSUED` or `ACKNOWLEDGED` transitions to `VOIDED` and spawns a successor in `DRAFT`, each successor carrying `supersedes_statement_id` pointing at its predecessor and a `sequence_no` one greater, with box deltas recomputed — and because a collected repayment is now in play, those recomputed deltas take the current-year or prior-year box treatment of §3.6 according to the repayment's `recovery_basis`."
        PRD: "If a collected repayment exists and its `recovery_basis` is `SAME_YEAR_NET` — the current-year box treatment, in which all three boxes are adjusted — then `wage_delta_cents` is the negation of the jurisdiction removal reduced further by the repayment's `overpaid_gross_cents`, `fica_wage_delta_cents` is that same figure, and `withholding_delta_cents` is the negation of the repayment's `overpaid_income_tax_withheld_cents`."
        PRD: "Statement lists can be narrowed by `correction_case_id`, `employee_id`, `supersedes_statement_id`, `tax_year`, `is_prior_year` and `status`; successor statements born inside a cascade are discoverable only there."

        Design: Difficulty/cross_entity_state_dependency/statement_box_deltas_depend_on_repayment_reaching_collected
        """
        ctx = _issued_statement_then_agreed_repayment(api)
        first_id = ctx["statement"]["id"]

        collected = validate_success(
            api.collect_wage_repayment(
                ctx["repayment"]["id"], f.collect_payload(309400), ANALYST_HEADERS
            )
        )

        assert collected["status"] == "COLLECTED"
        assert collected["collected_cents"] == 309400
        retired = validate_success(api.get_statement(first_id, PREPARER_HEADERS))
        assert retired["status"] == "VOIDED"

        successors, meta = validate_paginated(
            api.list_statements({"supersedes_statement_id": first_id}, PREPARER_HEADERS)
        )
        assert_pagination(meta, total_count=1)
        successor = successors[0]
        _statement_deltas(successor, -800000, -800000, -60000)
        assert successor["sequence_no"] == 2
        assert successor["is_prior_year"] is True
        assert successor["status"] == "DRAFT"
        assert_case_rollups(
            fx.read_case(api, ctx["case_id"]), repayment_recovered_cents=90600
        )

        validate_success(api.issue_statement(successor["id"], {}, PREPARER_HEADERS))

        case = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(case, status="REMEDIATION_PENDING", statement_status="STMT_ISSUED")
        assert_case_rollups(case, corrected_wage_base_cents=200000)
        assert _active_count(api, ctx["employee_id"]) == 1


class TestDeliveryChannelCapability:
    def test_a_portal_statement_can_never_be_reported_undeliverable(self, api):
        """Only physical mail comes back, so the refusal is a 422 and the statement is
        left exactly as issued — no reason recorded, no box touched, still counted.

        PRD: "Mail comes back. Reporting a statement undeliverable is available from `ISSUED` and requires an `undeliverable_reason`; it is available only when the statement's `delivery_channel` is `MAIL`, and an attempt on a `PORTAL` statement is refused with `ERR_CHANNEL_NOT_UNDELIVERABLE_CAPABLE`."

        Design: Corner/endpoints/report_undeliverable_on_a_portal_statement_is_refused
        """
        ctx = fx.jurisdiction_issued_statement(api, delivery_channel="PORTAL")
        statement_id = ctx["statement"]["id"]
        assert ctx["statement"]["delivery_channel"] == "PORTAL"

        validate_error(
            api.report_statement_undeliverable(
                statement_id,
                f.undeliverable_payload(undeliverable_reason="Returned by the postal service."),
                PREPARER_HEADERS,
            ),
            ERR_CHANNEL_NOT_UNDELIVERABLE_CAPABLE,
            422,
        )

        unchanged = validate_success(api.get_statement(statement_id, PREPARER_HEADERS))
        assert unchanged["status"] == "ISSUED"
        assert unchanged["undeliverable_reason"] is None
        _statement_deltas(unchanged, -400000, -400000, 0)
        assert _active_count(api, ctx["employee_id"]) == 1


class TestPriorYearWindow:
    def test_a_tax_year_four_calendar_years_back_may_not_be_drafted(self, api):
        """The window is measured against the logical clock rather than the case's own
        period: a 2022 statement drafted in logical 2026 is out of reach even though the
        same fixture would otherwise have produced a reportable delta.

        PRD: "Age also bounds the work: a statement whose `tax_year` is more than three calendar years before the current logical year may neither be drafted nor issued, and either attempt is refused with `ERR_PRIOR_YEAR_WINDOW_CLOSED`."

        Design: Corner/errors/statement_for_a_tax_year_outside_the_prior_year_window_is_rejected
        """
        ctx = fx.jurisdiction_scenario(api, clock="2026-08-01T00:00:00Z", tax_year=2022)
        assert_case_dimensions(fx.read_case(api, ctx["case_id"]), statement_status="STMT_PENDING")

        validate_error(
            api.create_statement(
                f.statement_payload(ctx["case_id"], ctx["employee_id"], tax_year=2022),
                PREPARER_HEADERS,
            ),
            ERR_PRIOR_YEAR_WINDOW_CLOSED,
            422,
        )

        _, meta = validate_paginated(
            api.list_statements({"correction_case_id": ctx["case_id"]}, PREPARER_HEADERS)
        )
        assert_pagination(meta, total_count=0)
        assert_case_dimensions(fx.read_case(api, ctx["case_id"]), statement_status="STMT_PENDING")
        assert _active_count(api, ctx["employee_id"]) == 0


class TestStatementVersionGuard:
    def test_a_version_captured_before_issuance_cannot_drive_a_reissue(self, api):
        """The statement's own issue transition bumps its `version`, so the number the
        client read at draft time is stale and the reissue is refused with 412 — leaving
        the predecessor whole rather than half-voided with no successor.

        PRD: "If the value does not equal that statement's current `version`, the reissue is rejected with `ERR_STALE_STATEMENT_VERSION` and HTTP 412."
        PRD: "A reissue supersedes the statement it names, so a client acting on a stale view would attach a second successor to the same predecessor and count that predecessor's wage delta twice in the case's corrected wage base."

        Design: Corner/cross-cutting complexity layers/stale_statement_version_blocks_reissue
        """
        ctx = fx.jurisdiction_drafted_statement(api)
        stale_version = ctx["statement"]["version"]
        issued = validate_success(api.issue_statement(ctx["statement_id"], {}, PREPARER_HEADERS))
        assert issued["status"] == "ISSUED"

        validate_error(
            api.reissue_statement(
                ctx["statement_id"],
                f.reissue_payload(
                    stale_version, delivery_channel="PORTAL", reissue_reason="Employee moved."
                ),
                PREPARER_HEADERS,
            ),
            ERR_STALE_STATEMENT_VERSION,
            412,
        )

        held = validate_success(api.get_statement(ctx["statement_id"], PREPARER_HEADERS))
        assert held["status"] == "ISSUED"
        assert held["version"] > stale_version
        _, meta = validate_paginated(
            api.list_statements(
                {"supersedes_statement_id": ctx["statement_id"]}, PREPARER_HEADERS
            )
        )
        assert_pagination(meta, total_count=0)

    def test_the_current_version_is_accepted_and_produces_exactly_one_successor(self, api):
        """Re-reading the row and resubmitting the same reissue succeeds with HTTP 201, and
        the successor is not counted until it is itself issued.

        PRD: "Because the response reports a newly created resource, reissue answers with HTTP 201."
        PRD: "The predecessor transitions to `VOIDED`, which is terminal, and a successor is created in `status` `DRAFT` whose `supersedes_statement_id` names the predecessor, whose `sequence_no` is one greater than the predecessor's, and whose `correction_case_id`, `employee_id` and `tax_year` are copied from the predecessor; the successor's own box deltas are computed afresh."

        Design: Corner/cross-cutting complexity layers/stale_statement_version_blocks_reissue
        """
        ctx = fx.jurisdiction_drafted_statement(api)
        stale_version = ctx["statement"]["version"]
        validate_success(api.issue_statement(ctx["statement_id"], {}, PREPARER_HEADERS))
        validate_error(
            api.reissue_statement(
                ctx["statement_id"],
                f.reissue_payload(
                    stale_version, delivery_channel="PORTAL", reissue_reason="Employee moved."
                ),
                PREPARER_HEADERS,
            ),
            ERR_STALE_STATEMENT_VERSION,
            412,
        )

        fresh_version = validate_success(
            api.get_statement(ctx["statement_id"], PREPARER_HEADERS)
        )["version"]
        assert fresh_version > stale_version

        successor = validate_success(
            api.reissue_statement(
                ctx["statement_id"],
                f.reissue_payload(
                    fresh_version, delivery_channel="PORTAL", reissue_reason="Employee moved."
                ),
                PREPARER_HEADERS,
            ),
            201,
        )

        assert successor["status"] == "DRAFT"
        assert successor["sequence_no"] == 2
        assert successor["wage_delta_cents"] == -400000
        assert successor["supersedes_statement_id"] == ctx["statement_id"]
        retired = validate_success(api.get_statement(ctx["statement_id"], PREPARER_HEADERS))
        assert retired["status"] == "VOIDED"
        assert _active_count(api, ctx["employee_id"]) == 0


class TestActiveStatementCountReconciliation:
    def test_the_count_and_the_wage_base_move_in_lockstep_through_the_statement_states(self, api):
        """`active_statement_count` is a recount over the statement set, not a counter, so it
        reads 0 at draft, 1 at issue and 0 again on return — and the wage base follows it
        while the statement's own delta never changes.

        PRD: "The case's `corrected_wage_base_cents` is the base plus the adjustment, in whole cents, with no rounding."
        PRD: "Note that `RETURNED_UNDELIVERABLE` still counts as an outstanding statement for the purposes of the acknowledgement completion test above — it blocks `STMT_COMPLETE` until it is dealt with."

        Design: Corner/cross-cutting complexity layers/employee_active_statement_count_reconciles_after_each_source_change
        """
        ctx = fx.jurisdiction_scenario(api)
        draft = fx.draft_statement(api, ctx["case_id"], ctx["employee_id"], tax_year=2025)

        assert draft["wage_delta_cents"] == -400000
        assert _active_count(api, ctx["employee_id"]) == 0
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), corrected_wage_base_cents=1000000)

        issued = validate_success(api.issue_statement(draft["id"], {}, PREPARER_HEADERS))

        assert issued["wage_delta_cents"] == -400000
        assert _active_count(api, ctx["employee_id"]) == 1
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), corrected_wage_base_cents=600000)
        assert_case_dimensions(fx.read_case(api, ctx["case_id"]), statement_status="STMT_ISSUED")

        returned = validate_success(
            api.report_statement_undeliverable(
                draft["id"],
                f.undeliverable_payload(undeliverable_reason="Returned by the postal service."),
                PREPARER_HEADERS,
            )
        )

        assert returned["wage_delta_cents"] == -400000
        assert _active_count(api, ctx["employee_id"]) == 0
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), corrected_wage_base_cents=1000000)
        assert_case_dimensions(fx.read_case(api, ctx["case_id"]), statement_status="STMT_ISSUED")
