"""Royalty statement computation: basis selection, pool splitting and reversal."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_statement_channels,
    assert_statement_line,
    assert_statement_money,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


def test_estimated_basis_holds_back_a_fifth_of_print_dm_while_settled_does_not():
    """An `ESTIMATED` statement reserves 20% of the `PRINT_DM` net; a `SETTLED` one does not.

    PRD: "On an `ESTIMATED` statement, and only for the `PRINT_DM` channel, twenty percent of that raw net is held back as a returns reserve: the `included_net_cents` becomes eighty percent of the raw net, floored to a whole cent."

    Design: Difficulty/dual_variant_calc/royalty_accrual_estimated_vs_settled_basis_diverges
    """
    state = fixtures.setup_royalty_revenue_ledger()
    title = state["title"]
    writer = state["creators"]["SCRIPT"]

    estimated = validate_success(
        api_client.create_royalty_statement(
            factories.statement_payload(
                title["id"], writer["id"], period="2026-12", basis="ESTIMATED"
            ),
            TEST_USERS["royalty_accountant_headers"],
        ),
        expected_status=201,
    )
    settled = validate_success(
        api_client.create_royalty_statement(
            factories.statement_payload(
                title["id"], writer["id"], period="2026-12", basis="SETTLED"
            ),
            TEST_USERS["royalty_accountant_headers"],
        ),
        expected_status=201,
    )

    # 328500 + 66000 = 394500 raw net; 80% of it, floored, is 315600.
    assert_statement_line(
        estimated,
        "PRINT_DM",
        included_net_cents=315600,
        channel_pool_cents=37872,
        creator_share_cents=20120,
    )
    # The settled basis sees only the 328500 ACTUAL row, with no holdback.
    assert_statement_line(
        settled,
        "PRINT_DM",
        included_net_cents=328500,
        channel_pool_cents=39420,
        creator_share_cents=20942,
    )


def test_settled_basis_drops_the_collected_channel_that_only_estimated_receipts_fed():
    """A channel fed only by `ESTIMATED` receipts emits no line on a `SETTLED` statement.

    PRD: "The contributing receipts are the revenue events belonging to any issue of that title whose `period` equals the statement's `period`, filtered by basis: an `ESTIMATED` statement includes both `ESTIMATED` and `ACTUAL` rows, while a `SETTLED` statement includes `ACTUAL` rows only."

    Design: Difficulty/dual_variant_calc/royalty_accrual_estimated_vs_settled_basis_diverges
    """
    state = fixtures.setup_royalty_revenue_ledger()
    title = state["title"]
    writer = state["creators"]["SCRIPT"]

    estimated = fixtures.create_statement(
        title["id"], writer["id"], period="2026-12", basis="ESTIMATED"
    )
    settled = fixtures.create_statement(
        title["id"], writer["id"], period="2026-12", basis="SETTLED"
    )

    assert_statement_channels(
        estimated, ["PRINT_DM", "DIGITAL", "COLLECTED", "SUBSIDIARY"]
    )
    assert_statement_channels(settled, ["PRINT_DM", "DIGITAL", "SUBSIDIARY"])
    assert_statement_line(estimated, "COLLECTED", creator_share_cents=7172)

    assert_statement_money(
        estimated,
        gross_royalty_cents=85432,
        recoupment_applied_cents=25000,
        payable_cents=60432,
    )
    assert_statement_money(
        settled,
        gross_royalty_cents=79082,
        recoupment_applied_cents=25000,
        payable_cents=54082,
    )
    assert estimated["gross_royalty_cents"] - settled["gross_royalty_cents"] == 6350


def test_two_draft_statements_on_the_same_period_leave_the_advance_untouched():
    """Both bases may be computed for one period without either reaching the ledger.

    PRD: "A `DRAFT` statement has not yet reached the ledger and a `REVERSED` statement has left it, which is what makes statement reversal restore the pre-issue figures exactly."

    Design: Difficulty/dual_variant_calc/royalty_accrual_estimated_vs_settled_basis_diverges
    """
    state = fixtures.setup_royalty_revenue_ledger()
    title = state["title"]
    writer = state["creators"]["SCRIPT"]

    estimated = fixtures.create_statement(
        title["id"], writer["id"], period="2026-12", basis="ESTIMATED"
    )
    settled = fixtures.create_statement(
        title["id"], writer["id"], period="2026-12", basis="SETTLED"
    )
    assert estimated["status"] == "DRAFT"
    assert settled["status"] == "DRAFT"

    assignment = fixtures.read_assignment(state["assignments"]["SCRIPT"]["id"])
    assert assignment["unrecouped_advance_cents"] == 25000
    assert fixtures.read_title(title["id"])["royalty_accrued_cents"] == 0


def test_channel_pool_strikes_the_cover_portion_before_the_prorata_remainder():
    """The `PRINT_DM` pool splits cover-first, then pro rata over what remains.

    PRD: "First, the cover portion is struck from the pool before any deduction: it is the pool multiplied by the title's `cover_participation_bps`, divided by 10000, and floored to a whole cent."

    Design: Difficulty/combinatorial_formula/royalty_pool_split_cover_first_then_prorata_remainder_mode_c
    """
    state = fixtures.setup_royalty_revenue_ledger(
        receipts=fixtures.ACTUAL_ONLY_RECEIPTS
    )
    title = state["title"]

    statements = {
        craft: fixtures.create_statement(
            title["id"], creator["id"], period="2026-12", basis="SETTLED"
        )
        for craft, creator in state["creators"].items()
    }

    # Pool 39420 = 5913 struck for cover + 33507 shared pro rata as 20942 / 12565.
    for craft in ("SCRIPT", "PENCILS", "COVER"):
        assert_statement_line(statements[craft], "PRINT_DM", channel_pool_cents=39420)
    assert_statement_line(statements["SCRIPT"], "PRINT_DM", creator_share_cents=20942)
    assert_statement_line(statements["PENCILS"], "PRINT_DM", creator_share_cents=12565)
    assert_statement_line(statements["COVER"], "PRINT_DM", creator_share_cents=5913)
    assert 20942 + 12565 + 5913 == 39420


def test_non_cover_shares_normalise_over_their_own_basis_point_total():
    """The 5000/3000 split is taken over 8000, not over 10000.

    PRD: "Non-cover participants normalise over their **own** basis-point total rather than over 10000: each receives the remainder multiplied by their own `royalty_share_bps`, divided by the sum of `royalty_share_bps` across all non-`COVER` participants, floored to a whole cent."

    Design: Difficulty/combinatorial_formula/royalty_pool_split_cover_first_then_prorata_remainder_mode_c
    """
    state = fixtures.setup_royalty_revenue_ledger(
        receipts=fixtures.ACTUAL_ONLY_RECEIPTS
    )
    title = state["title"]

    grosses = {}
    for craft, creator in state["creators"].items():
        statement = fixtures.create_statement(
            title["id"], creator["id"], period="2026-12", basis="SETTLED"
        )
        grosses[craft] = statement["gross_royalty_cents"]

    assert grosses["SCRIPT"] == 79082
    assert grosses["PENCILS"] == 47449
    assert grosses["COVER"] == 22329
    # The three participants exhaust the three channel pools with nothing left over.
    assert sum(grosses.values()) == 148860


def test_leftover_cents_land_on_the_earliest_created_non_cover_participant():
    """The one-cent top-up goes to the writer, whose assignment was created first.

    PRD: "Finally the floored shares are topped up: the difference between the remainder and the sum of the floored shares is distributed one cent at a time to the non-cover participants in ascending `created_at` order until it is exhausted, so the distributed shares add up to the remainder exactly."

    Design: Difficulty/combinatorial_formula/royalty_pool_split_cover_first_then_prorata_remainder_mode_c
    """
    state = fixtures.setup_royalty_revenue_ledger(
        receipts=fixtures.ACTUAL_ONLY_RECEIPTS
    )
    title = state["title"]

    writer_statement = fixtures.create_statement(
        title["id"], state["creators"]["SCRIPT"]["id"], period="2026-12", basis="SETTLED"
    )
    penciller_statement = fixtures.create_statement(
        title["id"], state["creators"]["PENCILS"]["id"], period="2026-12", basis="SETTLED"
    )

    # The remainder of 33507 floors to 20941 + 12565 = 33506, so one cent is owed.
    assert_statement_line(writer_statement, "PRINT_DM", creator_share_cents=20942)
    assert_statement_line(penciller_statement, "PRINT_DM", creator_share_cents=12565)

    # The writer's own payable reflects the recouped advance; the penciller has none.
    assert_statement_money(
        writer_statement, gross_royalty_cents=79082, payable_cents=54082
    )
    assert_statement_money(
        penciller_statement, gross_royalty_cents=47449, payable_cents=47449
    )


def test_segregation_of_duties_is_reported_before_the_zero_payable_guard():
    """The issuer paying their own zero-payable statement sees the duties refusal.

    PRD: "A royalty statement records the operator identifier that issued it in `issued_by_user_id`; when a statement is paid, the acting `X-User-ID` must differ from that recorded value, and an attempt by the same operator to pay a statement they themselves issued is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_11_beats_fiscal_priority_28_on_statement_pay
    """
    state = fixtures.setup_royalty_revenue_ledger(script_advance_cents=500000)
    accountant = TEST_USERS["royalty_accountant_headers"]

    statement = fixtures.create_statement(
        state["title"]["id"],
        state["creators"]["SCRIPT"]["id"],
        period="2026-12",
        basis="ESTIMATED",
    )
    assert_statement_money(
        statement,
        gross_royalty_cents=85432,
        recoupment_applied_cents=85432,
        payable_cents=0,
    )
    statement = fixtures.issue_statement(statement["id"], accountant)

    response = api_client.pay_royalty_statement(
        statement["id"], factories.pay_payload(), accountant
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    unchanged = fixtures.read_statement(statement["id"])
    assert unchanged["status"] == "ISSUED"
    assert unchanged["paid_by_user_id"] is None
    assert unchanged["payment_reference"] is None
    assignment = fixtures.read_assignment(state["assignments"]["SCRIPT"]["id"])
    assert assignment["unrecouped_advance_cents"] == 414568


def test_a_second_operator_paying_a_fully_recouped_statement_hits_the_fiscal_guard():
    """With the duties check satisfied, the zero payable is what refuses the payment.

    PRD: "And the statement's `payable_cents` must be strictly greater than 0: a statement whose entire accrual was absorbed by the advance may be issued for the record but never paid, and payment is refused with `ERR_ZERO_PAYABLE_STATEMENT` at HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_11_beats_fiscal_priority_28_on_statement_pay
    """
    state = fixtures.setup_royalty_revenue_ledger(script_advance_cents=500000)

    statement = fixtures.create_statement(
        state["title"]["id"],
        state["creators"]["SCRIPT"]["id"],
        period="2026-12",
        basis="ESTIMATED",
    )
    statement = fixtures.issue_statement(
        statement["id"], TEST_USERS["royalty_accountant_headers"]
    )

    response = api_client.pay_royalty_statement(
        statement["id"],
        factories.pay_payload(),
        TEST_USERS["royalty_accountant_2_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ZERO_PAYABLE_STATEMENT.value)
    assert fixtures.read_statement(statement["id"])["status"] == "ISSUED"


def test_reversal_restores_the_title_accrual_and_the_advance_balance_exactly():
    """Reversing an issued statement returns both ledgers to their pre-issue values.

    PRD: "A `RoyaltyAccountant` moves an `ISSUED` statement to `REVERSED`, capturing the supplied `reason` into `reversal_reason`; the title's `royalty_accrued_cents` shrinks by this statement's `payable_cents` and the assignment's `unrecouped_advance_cents` is restored by this statement's `recoupment_applied_cents`, returning both figures to exactly their pre-issue values."

    Design: Difficulty/compensating_invariant/statement_reversal_restores_the_royalty_accrual_and_advance_balance_without_drift
    """
    state = fixtures.setup_royalty_revenue_ledger()
    title_id = state["title"]["id"]
    assignment_id = state["assignments"]["SCRIPT"]["id"]

    statement = fixtures.create_statement(
        title_id, state["creators"]["SCRIPT"]["id"], period="2026-12", basis="ESTIMATED"
    )
    fixtures.issue_statement(statement["id"])
    assert fixtures.read_title(title_id)["royalty_accrued_cents"] == 60432
    assert fixtures.read_assignment(assignment_id)["unrecouped_advance_cents"] == 0

    reversed_statement = validate_success(
        api_client.reverse_royalty_statement(
            statement["id"],
            factories.reverse_payload(),
            TEST_USERS["royalty_accountant_headers"],
        )
    )
    assert reversed_statement["status"] == "REVERSED"
    assert reversed_statement["reversal_reason"] is not None
    assert fixtures.read_title(title_id)["royalty_accrued_cents"] == 0
    assert fixtures.read_assignment(assignment_id)["unrecouped_advance_cents"] == 25000


def test_a_reversed_statement_keeps_its_computed_figures_for_the_audit_trail():
    """The row that left the ledger still shows what it once carried.

    PRD: "A title's `royalty_accrued_cents` equals the sum of `payable_cents` over that title's royalty statements whose status is `ISSUED` or `PAID`."

    Design: Difficulty/compensating_invariant/statement_reversal_restores_the_royalty_accrual_and_advance_balance_without_drift
    """
    state = fixtures.setup_royalty_revenue_ledger()

    statement = fixtures.create_statement(
        state["title"]["id"],
        state["creators"]["SCRIPT"]["id"],
        period="2026-12",
        basis="ESTIMATED",
    )
    fixtures.issue_statement(statement["id"])
    fixtures.reverse_statement(statement["id"])

    stored = fixtures.read_statement(statement["id"])
    assert_statement_money(
        stored,
        gross_royalty_cents=85432,
        recoupment_applied_cents=25000,
        payable_cents=60432,
    )
    assert fixtures.read_title(state["title"]["id"])["royalty_accrued_cents"] == 0


def test_a_replacement_statement_recoups_the_restored_advance_again():
    """After a reversal the same period may be restated, recouping the same advance.

    PRD: "Advances are recouped next: `recoupment_applied_cents` is the smaller of the assignment's `unrecouped_advance_cents` and the `gross_royalty_cents`, and `payable_cents` is the gross royalty less that recoupment."

    Design: Difficulty/compensating_invariant/statement_reversal_restores_the_royalty_accrual_and_advance_balance_without_drift
    """
    state = fixtures.setup_royalty_revenue_ledger()
    title_id = state["title"]["id"]
    writer_id = state["creators"]["SCRIPT"]["id"]

    first = fixtures.create_statement(
        title_id, writer_id, period="2026-12", basis="ESTIMATED"
    )
    fixtures.issue_statement(first["id"])
    fixtures.reverse_statement(first["id"])

    second = fixtures.create_statement(
        title_id, writer_id, period="2026-12", basis="ESTIMATED"
    )
    assert_statement_money(
        second,
        gross_royalty_cents=85432,
        recoupment_applied_cents=25000,
        payable_cents=60432,
    )
    fixtures.issue_statement(second["id"])
    assert fixtures.read_title(title_id)["royalty_accrued_cents"] == 60432

    response = api_client.create_royalty_statement(
        factories.statement_payload(
            title_id, writer_id, period="2026-12", basis="ESTIMATED"
        ),
        TEST_USERS["royalty_accountant_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_STATEMENT_PERIOD.value)


def test_reversing_an_already_reversed_statement_is_refused():
    """`REVERSED` is terminal, so the compensation cannot be applied twice.

    PRD: "`PAID` and `REVERSED` are both terminal for a statement."

    Design: Difficulty/compensating_invariant/statement_reversal_restores_the_royalty_accrual_and_advance_balance_without_drift
    """
    state = fixtures.setup_royalty_revenue_ledger()

    statement = fixtures.create_statement(
        state["title"]["id"],
        state["creators"]["SCRIPT"]["id"],
        period="2026-12",
        basis="ESTIMATED",
    )
    fixtures.issue_statement(statement["id"])
    fixtures.reverse_statement(statement["id"])

    response = api_client.reverse_royalty_statement(
        statement["id"],
        factories.reverse_payload(),
        TEST_USERS["royalty_accountant_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert fixtures.read_title(state["title"]["id"])["royalty_accrued_cents"] == 0
