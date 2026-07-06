"""Escrow funding budget ceiling and close-time validation precedence."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    add_fee_owner,
    setup_agreed_negotiation, setup_funded_escrow,
    TEST_USERS,
)

AGENT = TEST_USERS["right_of_way_agent_headers"]
ESCROW = TEST_USERS["escrow_officer_headers"]


# ---- priority_pair_validation_conflict / close_referential_beats_temporal --

def test_close_with_incomplete_ownership_returns_ownership_error(api):
    """PRD §2.11: "9. **Ownership completeness** — where required, fee ownership
    must total 100 percent, else `ERR_OWNERSHIP_INCOMPLETE` (422). ... 11.
    **Temporal rules** — appraiser appointment overlap, crew buffer, and escrow
    waiting period (409)."
    PRD §3.8: "First, title must be whole: the sum of `ownership_pct` across the
    parcel's `FEE_OWNER` interests must equal 100, else `ERR_OWNERSHIP_INCOMPLETE`."

    Design: Difficulty/priority_pair_validation_conflict/close_referential_beats_temporal
    """
    ctx = setup_funded_escrow(api=api)
    add_fee_owner(ctx["parcel"]["id"], pct=50, holder="O2", api=api)  # sum now 150
    resp = api.close_escrow(ctx["escrow"]["id"], ESCROW)
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_INCOMPLETE)


def test_close_ownership_check_preempts_and_leaves_escrow_funded(api):
    """PRD §3.8: "Second, a statutory waiting period must have elapsed: the
    logical clock must be at or beyond `funded_at` plus the configured escrow
    waiting period (`ESCROW_WAITING_PERIOD_DAYS` days), else
    `ERR_WAITING_PERIOD_ACTIVE`."
    PRD §2.11: "9. **Ownership completeness** ... 11. **Temporal rules** ...".

    Design: Difficulty/priority_pair_validation_conflict/close_referential_beats_temporal
    """
    ctx = setup_funded_escrow(api=api)  # clock left at funded_at (waiting period not elapsed)
    add_fee_owner(ctx["parcel"]["id"], pct=50, holder="O2", api=api)
    resp = api.close_escrow(ctx["escrow"]["id"], ESCROW)
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_INCOMPLETE)
    escrow = validate_success(api.get_escrow(ctx["escrow"]["id"], AGENT))
    assert escrow["status"] == "FUNDED"


# ---- Corner: fund exceeding budget -----------------------------------------

def test_fund_exceeding_available_budget_returns_budget_exceeded(api):
    """PRD §3.8: "Funding is permitted only when the project's `available_cents`
    is at least the escrow's `agreed_amount_cents`; a fund that would overrun the
    budget is rejected with `ERR_BUDGET_EXCEEDED`."

    Design: Corner/validations/fund_exceeding_budget_returns_budget_exceeded
    """
    ctx = setup_agreed_negotiation(budget=20_000_000, offer=27_000_000, api=api)
    escrow = get_success_data(api.create_escrow(
        ctx["parcel"]["id"], {"source": "NEGOTIATED"}, ESCROW))
    resp = api.fund_escrow(escrow["id"], ESCROW)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
