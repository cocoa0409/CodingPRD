"""
Queue B — §1.9 section ``consistency_model``.

The declared consistency model is immediate, and these two cases are where a
deferred implementation would show: the disbursement waterfall must be complete
in the response that ran it, and the loan posture a covenant test derives must be
visible to the very next reader without a second test or a re-read.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers.assertions import (
    assert_commitment_conservation,
    assert_fields,
    assert_id_order,
    assert_integer_cents,
    assert_iso_equal,
    assert_loan_ledger,
    assert_pagination_meta,
    assert_ratio,
)
from test_helpers.factories import (
    covenant_test_payload,
    draw_disbursement_payload,
)
from test_helpers.fixtures import (
    build_approved_draw,
    build_covenant,
    chain_through_loan,
    reset_clock,
)
from test_helpers.test_users import COMMITTEE_MEMBER, LOAN_SERVICER

# The recipes in this section file no endowment figure.
BORROWER = {"endowment_market_value_cents": None}


def test_the_disburse_response_already_carries_the_whole_waterfall_and_the_moved_ledger(api):
    """
    A 50000000 foundation draw disbursed against a 225000000 commitment: all five
    waterfall figures are present and final in the disburse response itself, the next
    read by a different role agrees field for field, and the loan's ledger has already
    moved with its conservation identity intact on that first read.

    PRD §3.7: "Step one establishes the completion tier from the **post-draw** cumulative position — the tier this very draw creates, not the one it started from. Add the gross amount to the loan's `disbursed_principal_cents` as it stands immediately before this disbursement, multiply that post-draw total by 10000, divide by the loan's `principal_cents` discarding any remainder, then divide by 10000 again to express the result as a fraction floored to four decimal places."
    PRD §3.7: "Below a completion fraction of 0.5000 the rate is 10 percent; from 0.5000 up to but not including 0.9000 it is 5 percent; at 0.9000 and above it is 0 percent."
    PRD §3.7: "The first bucket sweeps the interest reserve: it takes whichever is smaller of the pool and the loan's `interest_reserve_shortfall_cents`, and that amount is stored as `interest_reserve_applied_cents` and removed from the pool. The second bucket takes the inspection fee: whichever is smaller of what remains in the pool and 45000 cents — a flat 450 dollars per disbursement — stored as `inspection_fee_cents` and removed from the pool. Whatever is left is the third bucket, `net_disbursed_cents`, the cash actually released to the institution."
    PRD §3.7: "A successful disbursement stores `completion_pct_at_disbursement`, `retainage_cents`, `interest_reserve_applied_cents`, `inspection_fee_cents` and `net_disbursed_cents` on the draw and moves it `APPROVED → DISBURSED`."
    PRD §3.7: "On the loan, `reserved_draw_cents` falls by the approved amount because the reservation has been consumed; `disbursed_principal_cents` rises by the approved amount and `undrawn_commitment_cents` falls by the same amount; `outstanding_principal_cents` rises by the approved amount; `retainage_held_cents` rises by `retainage_cents`; and `interest_reserve_shortfall_cents` falls by `interest_reserve_applied_cents`."
    PRD §3.7: "When this is the first disbursement on the loan — that is, when `disbursed_principal_cents` stood at 0 before it — the loan also moves `PENDING_FIRST_DRAW → CONSTRUCTION_DRAW` on its servicing dimension."
    PRD §3.7: "Note that the risk dimension is untouched: cash movement never changes `risk_posture`."
    PRD §2.11: "the sum of `disbursed_principal_cents`, `undrawn_commitment_cents` and `cancelled_commitment_cents` must always equal `principal_cents`."

    Design: Corner/consistency_model/disbursement_waterfall_and_loan_ledger_settle_inside_the_same_response
    """
    reset_clock(api)
    chain = chain_through_loan(api, institution_overrides=BORROWER)
    version_at_origination = chain.loan["version"]
    draw = build_approved_draw(
        api,
        chain.loan_id,
        50000000,
        project_phase="FOUNDATION",
        requested_amount_cents=50000000,
        percent_complete=0.2222,
    )
    assert draw["status"] == "APPROVED"

    disbursed = get_success_data(
        api.disburse_draw_request(draw["id"], draw_disbursement_payload(), LOAN_SERVICER)
    )
    waterfall_fields = (
        "retainage_cents",
        "interest_reserve_applied_cents",
        "inspection_fee_cents",
        "net_disbursed_cents",
    )
    for field in waterfall_fields + ("completion_pct_at_disbursement",):
        assert disbursed[field] is not None, (
            f"{field} must be final in the disburse response, not backfilled later"
        )
    assert_integer_cents(disbursed, *waterfall_fields)
    # floor(50000000 x 10000 / 225000000) == 2222, so 0.2222 — below 0.5000, the
    # 10 percent retainage tier. Pool 45000000, reserve sweep 1500000, fee 45000.
    assert_ratio(
        disbursed["completion_pct_at_disbursement"], 0.2222, "completion_pct_at_disbursement"
    )
    assert_fields(
        disbursed,
        status="DISBURSED",
        retainage_cents=5000000,
        interest_reserve_applied_cents=1500000,
        inspection_fee_cents=45000,
        net_disbursed_cents=43455000,
    )

    # The very next request, from a different role, sees the same six figures.
    echoed = get_success_data(api.get_draw_request(draw["id"], chain.rep_headers))
    assert_fields(
        echoed,
        status="DISBURSED",
        retainage_cents=5000000,
        interest_reserve_applied_cents=1500000,
        inspection_fee_cents=45000,
        net_disbursed_cents=43455000,
    )
    assert_ratio(
        echoed["completion_pct_at_disbursement"], 0.2222, "completion_pct_at_disbursement"
    )

    loan = get_success_data(api.get_loan(chain.loan_id, chain.rep_headers))
    assert_loan_ledger(
        loan,
        disbursed_principal_cents=50000000,
        outstanding_principal_cents=50000000,
        undrawn_commitment_cents=175000000,
        reserved_draw_cents=0,
        retainage_held_cents=5000000,
        interest_reserve_shortfall_cents=0,
        servicing_status="CONSTRUCTION_DRAW",
        risk_posture="OPEN",
    )
    # One bump at approval and one at disbursement.
    assert loan["version"] == version_at_origination + 2, (
        f"expected version {version_at_origination + 2}, got {loan['version']}"
    )
    assert_commitment_conservation(loan)


def test_one_covenant_test_writes_its_history_and_the_loans_posture_in_the_same_request(api):
    """
    A single failing test against a 1.3000 threshold: the test response already
    carries the whole recorded ratio and the soft-breach state, the immediately
    following loan read already shows WATCH with one version bump, and the covenant
    list projection agrees with it in the same instant.

    PRD §3.8: "The numerator is the net-available-for-debt-service figure of §3.5 in whole dollars, computed for the institution that borrowed — reached through the loan's application — under the basis frozen on the loan as `giving_basis`, with the four-period window selected as of the submitted `as_of_date` rather than the current clock."
    PRD §3.8: "The denominator is the loan's current `annual_debt_service_cents` divided by 100 and rounded half up to whole dollars; "current" matters, because an approved term-extension workout may have lowered it."
    PRD §3.8: "The test result is `PASS` when the ratio is greater than or equal to the covenant's `threshold_ratio` and `FAIL` otherwise — the boundary is inclusive, so a ratio landing exactly on the threshold passes."
    PRD §3.8: "Every test, whatever its result and whatever the covenant's state, stores `last_test_as_of` from the submitted date, `last_test_numerator_dollars`, `last_test_denominator_dollars`, `last_test_ratio` and `last_test_result`, and raises `test_count` by 1."
    PRD §3.8: "From `COMPLIANT`, a failing test moves the covenant `COMPLIANT → BREACH_PENDING_CURE` and sets `consecutive_fail_count` to 1. This is the soft-breach window, and it is what drives the loan `OPEN → WATCH` on the risk dimension."
    PRD §2.4: "When a covenant test drives a loan's risk posture, the loan's `version` increases and its `updated_at` is refreshed even though the client addressed the covenant."
    PRD §2.3: "Covenants accept `loan_id`, `covenant_type` and `status`."

    Design: Corner/consistency_model/covenant_test_and_derived_loan_posture_are_visible_in_one_request
    """
    reset_clock(api)
    chain = chain_through_loan(api, institution_overrides=BORROWER)
    version_at_origination = chain.loan["version"]
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.3000)
    assert covenant["status"] == "COMPLIANT"

    tested = get_success_data(
        api.run_covenant_test(covenant["id"], covenant_test_payload(), LOAN_SERVICER)
    )
    # 100001 + 110001 + 90001 + 131998 dollars of net available over 36000000
    # cents of annual debt service expressed in dollars.
    assert_fields(
        tested,
        status="BREACH_PENDING_CURE",
        last_test_result="FAIL",
        last_test_numerator_dollars=432001,
        last_test_denominator_dollars=360000,
        test_count=1,
        consecutive_fail_count=1,
        waiver_count=0,
    )
    assert_ratio(tested["last_test_ratio"], 1.2000, "last_test_ratio")
    assert_iso_equal(tested["last_test_as_of"], "2026-08-01T00:00:00Z", "last_test_as_of")

    # The very next request already sees the derived posture.
    loan = get_success_data(api.get_loan(chain.loan_id, COMMITTEE_MEMBER))
    assert_fields(loan, risk_posture="WATCH", servicing_status="PENDING_FIRST_DRAW")
    assert loan["version"] == version_at_origination + 1, (
        f"expected version {version_at_origination + 1}, got {loan['version']}"
    )

    rows, meta = validate_paginated(
        api.list_covenants(COMMITTEE_MEMBER, {"loan_id": chain.loan_id})
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)
    assert_id_order(rows, [covenant["id"]])
    assert rows[0]["status"] == "BREACH_PENDING_CURE"
