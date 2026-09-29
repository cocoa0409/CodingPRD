"""The agreement's curative and funding dimensions advance independently."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money
from test_helpers.test_users import MANAGER_ALT_HEADERS


def test_funding_is_refused_while_the_curative_dimension_is_still_open(api):
    """A wire against an open curative period is rejected and funds nothing.

    PRD: "The curative dimension must already read `CURATIVE_CLOSED`; wiring
    against an agreement whose curative period is still open is
    `ERR_CURATIVE_PERIOD_OPEN`."

    Design: Difficulty/non_linear_state_machine/psa_curative_and_funding_dimensions_advance_independently
    """
    world = fx.psa_ready(api)

    response = api.fund_psa(
        world["psa"]["id"],
        f.fund_payload(wire_amount=48000.00, wire_reference="WIRE-6-A"),
        MANAGER_ALT_HEADERS,
    )
    validate_error(response, "ERR_CURATIVE_PERIOD_OPEN", 409)

    psa = fx.read_psa(api, world["psa"]["id"])
    assert psa["funding_status"] == "UNFUNDED"
    assert psa["curative_status"] == "CURATIVE_OPEN"


def test_closing_curative_then_funding_moves_one_dimension_at_a_time(api):
    """Neither the close nor the wire alone changes the derived psa_status.

    PRD: "The asymmetry between the two dimensions is intentional: funding is
    gated on the curative dimension, but the curative dimension is never gated on
    funding."

    Design: Difficulty/non_linear_state_machine/psa_curative_and_funding_dimensions_advance_independently
    """
    world = fx.psa_ready(api)

    closed = fx.close_curative(api, world["psa"]["id"])
    assert closed["curative_status"] == "CURATIVE_CLOSED"
    assert_money(closed["defect_adjustment_amount"], "0.00", "defect_adjustment_amount")
    assert_money(closed["adjusted_purchase_price"], "48000.00", "adjusted_purchase_price")
    assert closed["funding_status"] == "UNFUNDED"
    assert closed["psa_status"] == "EXECUTED"

    funded = fx.fund_psa(
        api, world["psa"]["id"], wire_amount=48000.00, wire_reference="WIRE-6-B"
    )
    assert funded["funding_status"] == "FUNDED"
    assert funded["wire_reference"] == "WIRE-6-B"
    assert funded["curative_status"] == "CURATIVE_CLOSED"
    assert funded["psa_status"] == "EXECUTED"


def test_only_the_recorded_deed_closes_the_agreement_and_acquires_the_interest(api):
    """psa_status reads CLOSED and the interest reads ACQUIRED only after recording.

    PRD: "The second hop drives the mineral interest `UNDER_PSA → ACQUIRED` — its
    terminal posture — copies the deed's `recorded_book_page` into the interest's
    `acquiring_deed_book_page`, and increments the interest's `version` by 1."

    Design: Difficulty/non_linear_state_machine/psa_curative_and_funding_dimensions_advance_independently
    """
    world = fx.psa_ready(api)
    fx.close_curative(api, world["psa"]["id"])
    fx.fund_psa(api, world["psa"]["id"], wire_amount=48000.00, wire_reference="WIRE-6-B")

    assert fx.read_interest(api, world["interest"]["id"])["interest_status"] == "UNDER_PSA"

    recorded = fx.record_deed(
        api,
        world["psa"]["id"],
        recording_county="Reeves",
        recorded_book_page="915/210",
        recording_date="2026-08-10",
    )
    assert recorded["psa_status"] == "CLOSED"
    assert recorded["recorded_book_page"] == "915/210"
    assert recorded["curative_status"] == "CURATIVE_CLOSED"
    assert recorded["funding_status"] == "FUNDED"

    interest = fx.read_interest(api, world["interest"]["id"])
    assert interest["interest_status"] == "ACQUIRED"
    assert interest["acquiring_deed_book_page"] == "915/210"
