"""One settlement, read back immediately from every aggregate it touches.

No expiration sweep is invoked and no read is retried between the write and the
reads: the first read after the settlement must already carry every derived
consequence. The harness restarts the server and empties the store before each
test, with the logical clock at 2026-08-01T00:00:00Z.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import assert_fields, bps_of, ratio_bps, round_half_up
from test_helpers.test_users import AGENT_HEADERS, SERVICING_AGENT_ID


def _settle_one_draw(api):
    """Request 1050000 against a VERIFIED 3000 bps milestone and settle it, returning the pieces."""
    scenario = S.project_with_milestones(api, releases=(3000,), verify=(0,))
    loan_version = S.loan_version(api, scenario.loan_id)
    draw = S.request_draw(api, scenario, 1050000, expected_version=loan_version)
    settled = validate_success(
        api.settle_funding_draw(draw["id"], F.settlement_payload("SETTLE"), AGENT_HEADERS)
    )
    return scenario, loan_version, settled


def test_the_settlement_response_carries_its_own_final_economics(api):
    """The settling write returns the billed discount, the withheld holdback and the net advance.

    PRD: "`net_settlement_cents`, the money that actually reaches the contractor, is `funded_amount_cents` reduced by `merchant_discount_cents` and reduced again by `holdback_withheld_cents`."

    Design: Corner/consistency_model/settlement_writes_are_visible_to_every_related_read_in_the_same_test
    """
    _scenario, _loan_version, settled = _settle_one_draw(api)

    discount = bps_of(1050000, C.NEGOTIATED_DISCOUNT_BPS)
    # min(base 52500, gap round_half_up(1050000 * 400 / 10000) - 0 = 42000, cap 157500).
    assert (discount, 42000) == (47145, 42000), "449 bps negotiated, 400 bps reserve target"
    assert_fields(
        settled,
        status="SETTLED",
        funded_amount_cents=1050000,
        effective_discount_bps=C.NEGOTIATED_DISCOUNT_BPS,
        merchant_discount_cents=discount,
        holdback_withheld_cents=42000,
        net_settlement_cents=1050000 - discount - 42000,
        settled_on=C.DEFAULT_CLOCK_DATE,
        released_by_user_id=SERVICING_AGENT_ID,
    )


def test_every_aggregate_the_settlement_touched_is_current_on_the_next_read(api):
    """The merchant, the account, the project and the draw all read back settled with no sweep.

    PRD: "There is no deferred settlement job and no eventual reconciliation: by the time a response is returned, every aggregate the write touches — a project's funded share, a merchant's reserve coverage, a consumer's program debt, a merchant's portfolio grade and termination recommendation — already reflects it."

    Design: Corner/consistency_model/settlement_writes_are_visible_to_every_related_read_in_the_same_test
    """
    scenario, loan_version, settled = _settle_one_draw(api)

    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        funded_volume_cents=1050000,
        holdback_reserve_cents=42000,
        holdback_target_cents=round_half_up(1050000 * 400, 10000),
        reserve_coverage_bps=C.FULL_COVERAGE_BPS,
        enrollment_status="APPROVED",
    )
    assert_fields(
        S.read_loan(api, scenario.loan_id),
        principal_balance_cents=1050000,
        total_funded_cents=1050000,
        first_funding_on=C.DEFAULT_CLOCK_DATE,
        version=loan_version + 1,
    )
    # The release cap is the lower of the 3000 bps verified share and the 7000 bps
    # pre-completion cap, so the whole 1050000 releasable amount is now consumed.
    assert_fields(
        S.read_project(api, scenario.project_id),
        settled_funded_cents=1050000,
        funded_pct_bps=ratio_bps(1050000, C.CANONICAL_TICKET_CENTS),
        max_fundable_now_cents=0,
    )
    assert_fields(
        S.read_draw(api, settled["id"]),
        status="SETTLED",
        merchant_discount_cents=47145,
        holdback_withheld_cents=42000,
        net_settlement_cents=960855,
        settled_on=C.DEFAULT_CLOCK_DATE,
    )


def test_the_filtered_merchant_collection_shows_the_settlement_derived_figures(api):
    """The same derived figures are visible through the filtered list read, not only the single read.

    PRD: "Consistency is immediate rather than eventual."

    Design: Corner/consistency_model/settlement_writes_are_visible_to_every_related_read_in_the_same_test
    """
    scenario, _loan_version, _settled = _settle_one_draw(api)

    rows, meta = validate_paginated(
        api.list_merchants(AGENT_HEADERS, {"risk_tier": "STANDARD"})
    )
    assert meta["total_count"] == 1, "One merchant, unseasoned and therefore STANDARD"
    assert rows[0]["id"] == scenario.merchant_id
    assert_fields(
        rows[0],
        funded_volume_cents=1050000,
        holdback_reserve_cents=42000,
        holdback_target_cents=42000,
        reserve_coverage_bps=C.FULL_COVERAGE_BPS,
        dispute_rate_bps=0,
        phantom_risk_score=0,
        portfolio_grade="A",
        termination_recommended=False,
    )
