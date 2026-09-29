"""Two rungs of the ladder colliding on one request: the lower-numbered wins."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money
from test_helpers.constants import ROLE_ACQUISITION_MANAGER
from test_helpers.test_users import (
    MANAGER_ALT_HEADERS,
    MANAGER_USER_ID,
    MANAGER_USER_ID_ALT,
    make_headers,
)


# --------------------------------------------------------------------------
# funding: state rung 27 versus fiscal rung 83
# --------------------------------------------------------------------------
def test_open_curative_period_masks_the_wrong_wire_amount(api):
    """The state rung fires even though the money is also wrong.

    PRD: "The curative dimension must already read `CURATIVE_CLOSED`; wiring
    against an agreement whose curative period is still open is
    `ERR_CURATIVE_PERIOD_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/fund_with_open_curative_and_wrong_wire_amount_yields_state_error_first
    """
    world = fx.psa_ready(api)

    response = api.fund_psa(
        world["psa"]["id"],
        f.fund_payload(wire_amount=45000.00, wire_reference="WIRE-9-BAD"),
        MANAGER_ALT_HEADERS,
    )
    validate_error(response, "ERR_CURATIVE_PERIOD_OPEN", 409)


def test_masked_funding_amount_rule_fires_once_curative_is_closed(api):
    """With the state rung satisfied the fiscal rung is real and rejects the wire.

    PRD: "And the money must be exact: a `wire_amount` that is not equal to the
    agreement's `adjusted_purchase_price` — the defect-adjusted figure, not the
    original `purchase_price` — is `ERR_FUNDING_AMOUNT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/fund_with_open_curative_and_wrong_wire_amount_yields_state_error_first
    """
    world = fx.psa_ready(api)
    closed = fx.close_curative(api, world["psa"]["id"])
    assert closed["curative_status"] == "CURATIVE_CLOSED"
    assert_money(closed["adjusted_purchase_price"], "48000.00", "adjusted_purchase_price")

    response = api.fund_psa(
        world["psa"]["id"],
        f.fund_payload(wire_amount=45000.00, wire_reference="WIRE-9-BAD"),
        MANAGER_ALT_HEADERS,
    )
    validate_error(response, "ERR_FUNDING_AMOUNT_MISMATCH", 422)

    psa = fx.read_psa(api, world["psa"]["id"])
    assert psa["funding_status"] == "UNFUNDED"
    assert psa["wire_reference"] is None


def test_exact_wire_amount_funds_the_agreement(api):
    """The correct wire clears both rungs.

    PRD: "On success `funding_status` becomes `FUNDED`, the supplied
    `wire_reference` is recorded, and `psa_status` is recomputed, remaining
    `EXECUTED` until the deed is on file."

    Design: Difficulty/priority_pair_validation_conflict/fund_with_open_curative_and_wrong_wire_amount_yields_state_error_first
    """
    world = fx.psa_ready(api)
    fx.close_curative(api, world["psa"]["id"])

    psa = fx.fund_psa(
        api, world["psa"]["id"], wire_amount=48000.00, wire_reference="WIRE-9-GOOD"
    )
    assert psa["funding_status"] == "FUNDED"
    assert psa["wire_reference"] == "WIRE-9-GOOD"


# --------------------------------------------------------------------------
# offer issuance: safety rung 50 versus fiscal rung 82
# --------------------------------------------------------------------------
def test_segregation_of_duties_masks_the_above_band_offer_amount(api):
    """The manager who priced the interest is refused before the band is checked.

    PRD: "The `X-User-ID` issuing an offer letter must differ from the
    `approved_by_user_id` recorded on the interest's live valuation."

    Design: Difficulty/priority_pair_validation_conflict/offer_by_valuation_approver_above_max_bid_yields_segregation_error_first
    """
    world = fx.valuation_ready(api, valuation_user_id=MANAGER_USER_ID)
    assert world["valuation"]["approved_by_user_id"] == MANAGER_USER_ID
    assert_money(world["valuation"]["bid_floor"], "37115.34", "bid_floor")
    assert_money(world["valuation"]["max_bid"], "55340.34", "max_bid")

    response = api.create_offer_letter(
        world["interest"]["id"],
        f.offer_letter_payload(offer_amount=60000.00, expires_on="2026-09-01"),
        make_headers(MANAGER_USER_ID, ROLE_ACQUISITION_MANAGER),
    )
    validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)


def test_masked_band_rule_fires_for_a_different_issuing_manager(api):
    """A second manager offering the same amount hits the band ceiling.

    PRD: "an `offer_amount` strictly above the valuation's `max_bid` is
    `ERR_OFFER_ABOVE_MAX_BID`, and an amount equal to either edge is accepted."

    Design: Difficulty/priority_pair_validation_conflict/offer_by_valuation_approver_above_max_bid_yields_segregation_error_first
    """
    world = fx.valuation_ready(api, valuation_user_id=MANAGER_USER_ID)

    response = api.create_offer_letter(
        world["interest"]["id"],
        f.offer_letter_payload(offer_amount=60000.00, expires_on="2026-09-01"),
        make_headers(MANAGER_USER_ID_ALT, ROLE_ACQUISITION_MANAGER),
    )
    validate_error(response, "ERR_OFFER_ABOVE_MAX_BID", 422)

    assert fx.read_interest(api, world["interest"]["id"])["interest_status"] == "PROSPECT"


def test_in_band_offer_from_the_second_manager_is_issued(api):
    """An in-band amount from a different manager clears both rungs.

    PRD: "On success the letter opens with `offer_status` of `SENT`, a
    `current_amount` equal to `offer_amount`, a `counter_round_count` of 0, a null
    `last_counter_amount`, a null `accepted_at`, and `issued_by_user_id` stamped
    with the issuing manager's `X-User-ID`."

    Design: Difficulty/priority_pair_validation_conflict/offer_by_valuation_approver_above_max_bid_yields_segregation_error_first
    """
    world = fx.valuation_ready(api, valuation_user_id=MANAGER_USER_ID)

    response = api.create_offer_letter(
        world["interest"]["id"],
        f.offer_letter_payload(offer_amount=48000.00, expires_on="2026-09-01"),
        make_headers(MANAGER_USER_ID_ALT, ROLE_ACQUISITION_MANAGER),
    )
    offer = validate_success(response, 201)
    assert offer["offer_status"] == "SENT"
    assert offer["issued_by_user_id"] == MANAGER_USER_ID_ALT
    assert fx.read_interest(api, world["interest"]["id"])["interest_status"] == "OFFERED"
