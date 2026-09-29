"""The counter/revise negotiation loop and its three-round ceiling."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money
from test_helpers.test_users import MANAGER_ALT_HEADERS, make_royalty_owner_headers


def _negotiate_three_rounds(api):
    """Three owner counters, each answered by a firm revision."""
    world = fx.offer_ready(api)
    offer_id = world["offer"]["id"]
    owner_headers = make_royalty_owner_headers(world["owner"]["id"])

    for counter_amount, revised_amount in (
        (52000.00, 50000.00),
        (52500.00, 51000.00),
        (53000.00, 51500.00),
    ):
        validate_success(
            api.counter_offer_letter(
                offer_id, f.counter_payload(counter_amount=counter_amount), owner_headers
            )
        )
        validate_success(
            api.revise_offer_letter(
                offer_id,
                f.revise_payload(revised_amount=revised_amount, expires_on="2026-09-01"),
                MANAGER_ALT_HEADERS,
            )
        )
    return world


def test_three_full_rounds_leave_the_firms_number_on_the_table(api):
    """A counter records its amount but never moves current_amount.

    PRD: "It pointedly does *not* move `current_amount`: the number on the table
    is the firm's number, and only a revision moves it."

    Design: Difficulty/non_linear_state_machine/offer_letter_counter_revise_negotiation_cycle_bounded_at_three_rounds
    """
    world = _negotiate_three_rounds(api)

    offer = fx.read_offer(api, world["offer"]["id"])
    assert offer["offer_status"] == "REVISED"
    assert_money(offer["current_amount"], "51500.00", "current_amount")
    assert_money(offer["last_counter_amount"], "53000.00", "last_counter_amount")
    assert offer["counter_round_count"] == 3


def test_fourth_counter_is_refused_once_three_rounds_are_spent(api):
    """The fourth owner counter is rejected and changes nothing.

    PRD: "A fourth counter attempt once `counter_round_count` has reached three is
    `ERR_COUNTER_ROUNDS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/offer_letter_counter_revise_negotiation_cycle_bounded_at_three_rounds
    """
    world = _negotiate_three_rounds(api)
    owner_headers = make_royalty_owner_headers(world["owner"]["id"])

    response = api.counter_offer_letter(
        world["offer"]["id"], f.counter_payload(counter_amount=54000.00), owner_headers
    )
    validate_error(response, "ERR_COUNTER_ROUNDS_EXHAUSTED", 409)

    offer = fx.read_offer(api, world["offer"]["id"])
    assert offer["counter_round_count"] == 3
    assert offer["offer_status"] == "REVISED"
    assert_money(offer["current_amount"], "51500.00", "current_amount")


def test_interest_stays_offered_for_the_whole_negotiation(api):
    """The interest sits in OFFERED for every edge of the loop.

    PRD: "Issuing an offer letter drives the interest from `PROSPECT` to
    `OFFERED`, and it is the single most heavily guarded write on the buy side."

    Design: Difficulty/non_linear_state_machine/offer_letter_counter_revise_negotiation_cycle_bounded_at_three_rounds
    """
    world = fx.offer_ready(api)
    offer_id = world["offer"]["id"]
    owner_headers = make_royalty_owner_headers(world["owner"]["id"])

    assert fx.read_interest(api, world["interest"]["id"])["interest_status"] == "OFFERED"

    validate_success(
        api.counter_offer_letter(
            offer_id, f.counter_payload(counter_amount=52000.00), owner_headers
        )
    )
    assert fx.read_interest(api, world["interest"]["id"])["interest_status"] == "OFFERED"

    validate_success(
        api.revise_offer_letter(
            offer_id,
            f.revise_payload(revised_amount=50000.00, expires_on="2026-09-01"),
            MANAGER_ALT_HEADERS,
        )
    )
    assert fx.read_interest(api, world["interest"]["id"])["interest_status"] == "OFFERED"
