"""Boundary precision (retail sample) and state-vs-fiscal priority ordering."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    admin_headers, make_author_headers,
    setup_accepted_contract, setup_provisional_statement, finalize_statement,
)


def test_retail_sample_at_max_length_accepted(api):
    """PRD §3.1: "The length must be strictly positive and at most
    `MAX_RETAIL_SAMPLE_SEC`, which is 300 seconds (five minutes); a length of zero
    or below, or one exceeding 300 seconds, is rejected with `ERR_SAMPLE_TOO_LONG`."

    Design: Difficulty/boundary_precision_check/retail_sample_length_at_and_over_max
    """
    ctx = setup_accepted_contract(api)  # title IN_PRODUCTION
    data = validate_success(
        api.set_retail_sample(
            ctx["title"]["id"], {"retail_sample_start_sec": 0, "retail_sample_end_sec": 300},
            make_author_headers(ctx["author"]["id"]),
        ), 200,
    )
    assert data["retail_sample_end_sec"] == 300


def test_retail_sample_over_max_length_rejected(api):
    """PRD §3.1: "a length of zero or below, or one exceeding 300 seconds, is
    rejected with `ERR_SAMPLE_TOO_LONG`."

    Design: Difficulty/boundary_precision_check/retail_sample_length_at_and_over_max
    """
    ctx = setup_accepted_contract(api)  # title IN_PRODUCTION
    resp = api.set_retail_sample(
        ctx["title"]["id"], {"retail_sample_start_sec": 0, "retail_sample_end_sec": 301},
        make_author_headers(ctx["author"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SAMPLE_TOO_LONG.value)


def test_pay_provisional_statement_reports_state_error(api):
    """PRD §2.9: the validation order places "(6) the target resource being in the
    correct state for the requested transition (the concretized invalid-state
    errors)" before "(12) the fiscal check that a payout has something to pay
    (`ERR_NOTHING_TO_PAY`)"; "An earlier check always masks a later one".
    PRD §3.8: "Paying requires the statement to be in `FINALIZED`, or it is refused
    with `ERR_STATEMENT_NOT_FINALIZED`".

    Design: Difficulty/priority_pair_validation_conflict/statement_state_beats_nothing_to_pay
    """
    ctx = setup_provisional_statement(api, sales=[])  # PROVISIONAL, net 0
    resp = api.pay_statement(ctx["statement"]["id"], admin_headers())
    validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_FINALIZED.value)


def test_pay_finalized_zero_net_reports_nothing_to_pay(api):
    """PRD §2.9: "An earlier check always masks a later one" — once the priority-6
    state precondition is satisfied (statement FINALIZED), the priority-12 fiscal
    check surfaces.
    PRD §3.8: "there must be something to distribute: if the sum of
    `narrator_royalty_cents` and `author_royalty_cents` is not greater than zero,
    the payment is refused with `ERR_NOTHING_TO_PAY`."

    Design: Difficulty/priority_pair_validation_conflict/statement_state_beats_nothing_to_pay
    """
    ctx = setup_provisional_statement(api, sales=[])  # net 0
    finalize_statement(api, ctx["statement"]["id"])  # now FINALIZED, still net 0
    resp = api.pay_statement(ctx["statement"]["id"], admin_headers())
    validate_error(resp, ApiErrorId.ERR_NOTHING_TO_PAY.value)
