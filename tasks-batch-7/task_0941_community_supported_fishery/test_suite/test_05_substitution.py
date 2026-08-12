"""Making an under-filled box whole: the member-protection ladder and the value settlement."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    propose_substitution,
    read_delivery,
    read_lot,
    read_member,
    setup_under_filled_box_with_substitute_lot,
    substitution_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_a_substitute_species_on_the_allergy_list_is_hard_blocked(api):
    """PRD 3.5: "If the substitute species appears in the member's `allergy_exclusions`, the
    proposal is refused with `ERR_ALLERGY_EXCLUSION` — this block is absolute and has no
    override."
    PRD 3.2: "`allergy_exclusions` is an array of species codes that must never be placed in
    this member's box under any circumstance — a hard block."

    Design: Corner/validations/allergy_exclusion_hard_blocks_the_substitute_species
    """
    ctx = setup_under_filled_box_with_substitute_lot(member_overrides={"allergy_exclusions": ["COD"]})

    response = api.propose_substitution(
        ctx["delivery_id"], substitution_payload(ctx["cod_lot_id"], 2.00), ADMIN
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_ALLERGY_EXCLUSION.value)

    delivery = read_delivery(ctx["delivery_id"])
    assert float(delivery["allocated_pounds"]) == pytest.approx(3.00)
    assert delivery["fill_status"] == "UNDER_FILLED"

    _, meta = validate_paginated(
        api.list_substitutions(ADMIN, {"share_delivery_id": ctx["delivery_id"]})
    )
    assert meta["total_count"] == 0


def test_a_member_who_refuses_substitution_outright_blocks_the_offer(api):
    """PRD 3.5: "If the member has set `never_substitute` to true, it is refused with
    `ERR_NEVER_SUBSTITUTE`; such a member takes money rather than unfamiliar fish."
    PRD 3.2: "`never_substitute` is a boolean, false by default, that when true means the
    member refuses substitution outright and takes money instead."

    Design: Corner/validations/never_substitute_member_refuses_every_offer
    """
    ctx = setup_under_filled_box_with_substitute_lot(member_overrides={"never_substitute": True})

    response = api.propose_substitution(
        ctx["delivery_id"], substitution_payload(ctx["cod_lot_id"], 2.00), ADMIN
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_NEVER_SUBSTITUTE.value)

    delivery = read_delivery(ctx["delivery_id"])
    assert delivery["fill_status"] == "UNDER_FILLED"
    assert float(delivery["substituted_pounds"]) == pytest.approx(0.00)


def test_an_offer_larger_than_the_substitute_lots_uncommitted_pounds_is_refused(api):
    """PRD 3.5: "Finally the substitute lot must be able to supply what is being offered:
    `substitute_pounds` must be at most that lot's `landed_pounds_net`, less its
    `allocated_pounds_total`, less the pounds already committed to substitutions drawn from that
    lot which stand in `ACCEPTED` or `CREDIT_ISSUED`. A lot that cannot cover the offer produces
    `ERR_NO_SUBSTITUTE_AVAILABLE`."

    Design: Corner/validations/substitute_lot_cannot_supply_the_offered_pounds
    """
    ctx = setup_under_filled_box_with_substitute_lot()

    response = api.propose_substitution(
        ctx["delivery_id"], substitution_payload(ctx["cod_lot_id"], 6.01), ADMIN
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_NO_SUBSTITUTE_AVAILABLE.value)

    cod_lot = read_lot(ctx["cod_lot_id"])
    assert float(cod_lot["landed_pounds_net"]) == pytest.approx(6.00)
    assert float(cod_lot["allocated_pounds_total"]) == pytest.approx(0.00)


def test_a_disliked_species_is_refused_while_an_acceptable_alternative_is_landed(api):
    """PRD 3.5: "If the substitute species appears in the member's `dislikes`, the CSF looks for
    an alternative: the proposal is refused with `ERR_DISLIKE_ALTERNATIVE_AVAILABLE` when at
    least one other species in the season's `offered_species` is in neither the member's
    `allergy_exclusions` nor their `dislikes` and is actually carried by some landing lot of the
    same season whose `status` is `RECORDED`, `ALLOCATED` or `SPLIT` and whose `quality_status`
    is `CLEAR`."

    Design: Corner/errors/error_dislike_alternative_available_soft_blocks_the_offer
    """
    ctx = setup_under_filled_box_with_substitute_lot(
        member_overrides={"dislikes": ["COD"]},
        offered_species=("SALMON", "COD", "HADDOCK"),
        with_haddock_lot=True,
    )

    response = api.propose_substitution(
        ctx["delivery_id"], substitution_payload(ctx["cod_lot_id"], 2.00), ADMIN
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_DISLIKE_ALTERNATIVE_AVAILABLE.value)

    assert read_delivery(ctx["delivery_id"])["fill_status"] == "UNDER_FILLED"
    haddock_lot = read_lot(ctx["haddock_lot_id"])
    assert haddock_lot["species"] == "HADDOCK"
    assert haddock_lot["quality_status"] == "CLEAR"


def test_a_below_value_substitution_credits_the_exact_value_gap(api):
    """PRD 3.5: "The `shortfall_pounds` is the plan's `target_pounds_per_delivery` less the
    delivery's `allocated_pounds` at the moment of proposal — note that this measures the hole
    the allocation left, not any pounds a previous substitution added."
    PRD 3.5: "The `owed_value_cents` is that shortfall multiplied by the retail rate of the
    *plan's own* species tier, rounded half up once. The `substitute_value_cents` is
    `substitute_pounds` multiplied by the substitute lot's `retail_value_cents_per_lb`, rounded
    half up once."
    PRD 3.5: "When the substitute is worth strictly less, the variant is `BELOW_VALUE` and
    `member_credit_cents` is the value gap — `owed_value_cents` less `substitute_value_cents` —
    capped at the delivery's own `subtotal_cents`, so that a substitution can never refund more
    than the share charge itself."
    PRD 3.5: "Only the second issues money: `member_credit_cents` is added to the delivery's
    `credit_cents` and to the member's `credit_balance_cents`, and if the box has already been
    charged its money axis moves `CHARGED → PARTIALLY_CREDITED`."

    A 2.00 lb shortfall of PREMIUM_FINFISH owes 2.00 * 1850 = 3700 cents; 2.00 lb of COD is
    worth 2.00 * 1150 = 2300 cents, so the gap is 1400 cents. The box is packed first, so its
    own `subtotal_cents` stands at the 4500 cent unit price and the cap cannot bind.

    Design: Corner/validations/below_value_substitution_credits_the_exact_value_delta
    """
    ctx = setup_under_filled_box_with_substitute_lot(pack_the_box=True, paid_cents=90000)
    assert ctx["delivery"]["subtotal_cents"] == 4500
    assert ctx["delivery"]["billing_status"] == "CHARGED"

    offer = propose_substitution(ctx["delivery_id"], ctx["cod_lot_id"], 2.00)
    assert float(offer["shortfall_pounds"]) == pytest.approx(2.00)
    assert offer["owed_value_cents"] == 3700
    assert offer["substitute_value_cents"] == 2300
    assert offer["settlement_variant"] == "BELOW_VALUE"
    assert offer["member_credit_cents"] == 1400
    assert offer["status"] == "PROPOSED"

    accepted = validate_success(
        api.accept_substitution(offer["id"], make_member_headers(ctx["member_id"]))
    )
    assert accepted["status"] == "CREDIT_ISSUED"

    delivery = read_delivery(ctx["delivery_id"])
    assert delivery["fill_status"] == "SUBSTITUTED"
    assert float(delivery["substituted_pounds"]) == pytest.approx(2.00)
    assert delivery["credit_cents"] == 1400
    assert delivery["billing_status"] == "PARTIALLY_CREDITED"
    assert read_member(ctx["member_id"])["credit_balance_cents"] == 1400
