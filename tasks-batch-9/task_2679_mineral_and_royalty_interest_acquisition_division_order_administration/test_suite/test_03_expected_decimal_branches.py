"""The four-factor decimal: nested min/max plus the non-consent election factor."""

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_decimal_interest


def test_non_consent_election_applies_the_thirty_percent_penalty_factor(api):
    """A NON_CONSENT allocation multiplies the decimal by 0.7000.

    PRD: "Under `NON_CONSENT` the effective rate is likewise the lesser of
    `lease_royalty_rate` and `royalty_rate_cap`, but the election factor is one
    minus a non-consent penalty of thirty percent, rounded to 4 decimal places —
    that is, 0.7000."

    Design: Difficulty/combinatorial_formula/expected_decimal_nested_min_max_with_non_consent_branch
    """
    world = fx.division_order_ready(
        api, allocation_overrides={"pooling_election": "NON_CONSENT"}
    )

    assert_decimal_interest(
        world["order"]["expected_decimal"], "0.00136719", "expected_decimal"
    )


def test_pooled_election_on_the_same_dataset_keeps_the_full_decimal(api):
    """POOLED carries an election factor of 1, isolating the non-consent penalty.

    PRD: "Under `POOLED` the owner is a participant, so the effective rate is the
    lesser of the interest's `lease_royalty_rate` and the unit's
    `royalty_rate_cap`, and the election factor is 1."

    Design: Difficulty/combinatorial_formula/expected_decimal_nested_min_max_with_non_consent_branch
    """
    world = fx.division_order_ready(
        api, allocation_overrides={"pooling_election": "POOLED"}
    )

    assert_decimal_interest(
        world["order"]["expected_decimal"], "0.00195313", "expected_decimal"
    )


def test_new_order_derives_its_payee_allocation_and_opening_posture(api):
    """Everything but the three named inputs is derived on the new order.

    PRD: "The `royalty_owner_id` — the payee of record — is copied from the
    interest's `seller_owner_id` and is never client-supplied."

    Design: Difficulty/combinatorial_formula/expected_decimal_nested_min_max_with_non_consent_branch
    """
    world = fx.division_order_ready(
        api, allocation_overrides={"pooling_election": "NON_CONSENT"}
    )
    order = world["order"]

    assert order["allocation_id"] == world["allocation"]["id"]
    assert order["royalty_owner_id"] == world["owner"]["id"]
    assert order["do_status"] == "SENT"
    assert order["pinned_decimal"] is None
