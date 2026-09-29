"""The two non-linear state machines: a bounded revision cycle and a two-axis home.

The underwriting case's ``SUBMITTED -> REVISION_REQUESTED -> DRAFT -> SUBMITTED`` loop is a
cycle with a hard bound of two traversals, and a Home carries two dimensions that a
portfolio-lot disposition moves independently of one another.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import ERR_REVISION_LIMIT_EXCEEDED
from test_helpers.assertions import (
    assert_fields,
    assert_home_dimensions,
    assert_money_group,
    failed,
    ok,
)
from test_helpers.constants import (
    ASSET_DISPOSITION_APPROVED,
    ASSET_PIPELINE,
    CASE_SUBMITTED,
    CLOCK_AUG_01,
    DISPOSITION_PORTFOLIO_LOT,
    LEASE_EXECUTED,
    OCC_OCCUPIED,
    POSTURE_OPEN,
)


def test_third_revision_request_is_refused_after_two_rounds(api):
    """Two loops are allowed; the third ``REQUEST_REVISION`` is refused at 422.

    PRD SS3.2: "A revision request moves the case `SUBMITTED -> REVISION_REQUESTED`, stores
    the `decision_note`, and deliberately leaves the home's `asset_status` alone. It is
    permitted only while `revision_round` is at most 1; once `revision_round` has reached 2 a
    third revision request is refused with `ERR_REVISION_LIMIT_EXCEEDED`."  PRD SS3.2 also
    fixes the loop's bookkeeping: "Reworking a returned case moves it `REVISION_REQUESTED ->
    DRAFT`, increments `revision_round` by 1, and clears `submitted_by_user_id` back to the
    empty string so the next submission re-stamps it. ... This closes the cycle `SUBMITTED ->
    REVISION_REQUESTED -> DRAFT -> SUBMITTED`, bounded to two loops."

    Design: Difficulty/non_linear_state_machine/underwriting_case_revision_cycle_bounded_at_two_rounds
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    templates = x.three_trade_catalogue(api)
    home = x.create_home(api, market["id"])
    case = get_success_data(
        api.create_underwriting_case(
            f.underwriting_case_payload(
                home["id"],
                home["version"],
                [
                    f.scope_line(templates.paint["id"], 1),
                    f.scope_line(templates.hvac["id"], 1),
                    f.scope_line(templates.floor["id"], 1150),
                ],
            ),
            x.ANALYST,
        )
    )
    case_id = case["id"]
    get_success_data(api.submit_underwriting_case(case_id, {}, x.ANALYST))
    get_success_data(
        api.decide_underwriting_case(
            case_id,
            f.decision_payload(
                "REQUEST_REVISION", decision_note="round one: tighten the rent estimate"
            ),
            x.COMMITTEE,
        )
    )
    get_success_data(
        api.revise_underwriting_case(case_id, {"estimated_monthly_rent_cents": 214000}, x.ANALYST)
    )
    get_success_data(api.submit_underwriting_case(case_id, {}, x.ANALYST))
    get_success_data(
        api.decide_underwriting_case(
            case_id,
            f.decision_payload(
                "REQUEST_REVISION", decision_note="round two: revisit the turn reserve"
            ),
            x.COMMITTEE,
        )
    )
    get_success_data(
        api.revise_underwriting_case(
            case_id,
            {"turn_reserve_annual_cents": 120000, "estimated_monthly_rent_cents": 215000},
            x.ANALYST,
        )
    )
    get_success_data(api.submit_underwriting_case(case_id, {}, x.ANALYST))

    failed(
        api.decide_underwriting_case(
            case_id,
            f.decision_payload("REQUEST_REVISION", decision_note="round three is refused"),
            x.COMMITTEE,
        ),
        ERR_REVISION_LIMIT_EXCEEDED,
    )

    stored = ok(api.get_underwriting_case(case_id, x.ANALYST))
    assert_fields(
        stored,
        status=CASE_SUBMITTED,
        revision_round=2,
        submitted_by_user_id="analyst-1",
        underwritten_yield_on_cost_bps=559,
    )
    assert_fields(ok(api.get_home(home["id"], x.ANALYST)), asset_status=ASSET_PIPELINE)


def test_portfolio_lot_approval_moves_asset_status_and_leaves_occupancy_occupied(api):
    """A lot sale of an occupied home advances one dimension only.

    PRD SS2.8: "A home carries **two independent state dimensions** that advance separately
    and must never be collapsed into one. ... A transition on one dimension never implicitly
    moves the other. A `RESERVED` home may still be `STABILIZED` or `DISPOSITION_APPROVED`,
    and a portfolio-lot sale of an `OCCUPIED` home is a legitimate, supported case."  PRD
    SS3.9: "`APPROVE_SALE` moves the home `STABILIZED -> DISPOSITION_APPROVED` and stores the
    payload's `disposition_mode` (`NONE`, `INDIVIDUAL` or `PORTFOLIO_LOT`), `bpo_value_cents`
    and `lot_code` ... whereas a `PORTFOLIO_LOT` sale is permitted at any `occupancy_status`
    including `RESERVED` and `OCCUPIED` ... Approval deliberately leaves `occupancy_status`
    alone -- an occupied home in a portfolio lot stays occupied."  PRD SS2.8 clause 6:
    "Otherwise -- which is to say when `asset_status` is `STABILIZED` or
    `DISPOSITION_APPROVED` and none of the earlier clauses matched -- the posture is `OPEN`."

    Design: Difficulty/non_linear_state_machine/home_asset_and_occupancy_dimensions_advance_independently
    """
    ctx = x.leased_home(api, general_template=False)

    ok(
        api.disposition_decision(
            ctx.home_id,
            f.approve_sale_payload(
                bpo_value_cents=30000000,
                disposition_mode=DISPOSITION_PORTFOLIO_LOT,
                lot_code="LOT-A",
            ),
            x.COMMITTEE,
        )
    )

    home = ok(api.get_home(ctx.home_id, x.ANALYST))
    assert_home_dimensions(
        home,
        ASSET_DISPOSITION_APPROVED,
        OCC_OCCUPIED,
        leasing_posture=POSTURE_OPEN,
    )
    assert_fields(
        home,
        disposition_mode=DISPOSITION_PORTFOLIO_LOT,
        lot_code="LOT-A",
        bpo_value_cents=30000000,
        hold_sell_score_bps=16,
        disposition_flagged=False,
    )
    assert_fields(ok(api.get_lease(ctx.lease_id, x.AGENT)), status=LEASE_EXECUTED)

    case = ok(api.get_underwriting_case(ctx.case_id, x.ANALYST))
    assert_money_group(
        case, realized_all_in_basis_cents=26050000, realized_noi_cents=1448541
    )
    assert_fields(case, realized_yield_on_cost_bps=556)
