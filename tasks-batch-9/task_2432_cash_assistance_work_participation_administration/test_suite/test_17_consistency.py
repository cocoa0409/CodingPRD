"""Every derived figure is visible on the very next read, with no lag."""
from test_helpers import caseworker_headers
from test_helpers import assertions as asrt
from test_helpers import fixtures as fx


def test_the_reads_after_an_issuance_show_the_recomputed_rollups_at_once(api):
    """PRD §3.4: "Each issuance writes one **time-limit month** row, always with
    `assistance_issued` set to true, and that row is where the program's two lifetime
    clocks are evaluated."
    PRD §3.4: "The first successful issuance advances the case
    `PENDING_ISSUANCE → ACTIVE`; every subsequent issuance leaves it `ACTIVE`."
    PRD §3.4: "Four household rollups are recomputed after every issuance, every extension
    grant and every extension revocation, always across every time-limit month of every
    case belonging to that household."
    PRD §4: "Operations that create a new stand-alone resource or add a new resource to a
    collection — registering a household, filing an application, attaching an income source
    or resource item, issuing a month, requesting an extension, assigning an activity,
    filing a participation report, opening a compliance episode, requesting a supportive
    service, drafting an overpayment claim, posting a recovery entry, opening a reporting
    quarter, and approving an application, which mints a new assistance case — return
    `201 Created`."

    Design: Corner/consistency_model/issuance_response_already_reflects_the_recomputed_rollups
    """
    context = fx.build_approved_case(
        api,
        household_overrides={
            "head_of_household_name": "Corner Immediate Consistency Household"
        },
        incomes=(),
    )
    asrt.assert_case_state(
        context.case,
        benefit_status="PENDING_ISSUANCE",
        benefit_amount_cents=41650,
    )

    row = fx.issue_month(api, context.case_id, "2026-08")

    asrt.assert_time_limit_month(
        row,
        benefit_month="2026-08",
        assistance_issued=True,
        state_clock_countable=True,
        federal_clock_countable=True,
    )
    asrt.assert_case_state(
        fx.read_case(api, context.case_id),
        benefit_status="ACTIVE",
        benefit_amount_cents=41650,
    )
    asrt.assert_household_clocks(
        fx.read_household(api, context.household_id),
        state_clock_months_used=1,
        federal_clock_months_used=1,
    )
    asrt.assert_page(
        api.list_time_limit_months(context.case_id, caseworker_headers()),
        total_count=1,
        row_count=1,
    )
