"""Consolidated forwarding: eligibility, the pinned rounding order, the discount and dispatch."""

from test_helpers import (
    CMRA_OPERATOR,
    ApiErrorId,
    assert_custody_cardinality,
    assert_forward_shipment,
    box_version,
    create_forward_shipment,
    forward_shipment_payload,
    log_and_match_flat,
    log_and_match_letter,
    lodge_disposition,
    open_compliance_review,
    read_mail_item,
    setup_box_with_forwardable_flats,
    setup_releasable_box,
    suspend_compliance_review,
    validate_error,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# Pricing: round per line item, then sum
# ==========================================================================
def test_three_priority_pieces_price_at_the_round_then_sum_total(api):
    """PRD §3.8: "Each piece's price is its bracket amount multiplied by that multiplier
    and **rounded half up to whole cents at that point**, and `base_price_cents` is the
    sum of those already-rounded per-item prices; the rounding order is the pinned one
    of §2.6 and summing first would give a different total."
    PRD §2.6: "Each piece on a consolidation is priced, rounded to a whole cent, and only
    then added into the shipment's `base_price_cents`."
    PRD §2.6: "Summing the unrounded per-item products and rounding once at the end is a
    different and incorrect answer: three `PRIORITY` pieces in the 1750-cent bracket give
    2538 cents each and 7614 cents in total under the pinned order, against 7613 cents
    under sum-then-round."

    Design: Difficulty/combinatorial_formula/forward_price_rounds_per_item_before_summing
    """
    ctx = setup_box_with_forwardable_flats(
        "C-301", "Fay Ward", 3, holder_email="fay@example.com"
    )

    response = api.create_forward_shipment(
        ctx["box_id"],
        forward_shipment_payload(
            "PRIORITY", "9 Elm Ave, Springfield", ctx["item_ids"], box_version(ctx["box_id"])
        ),
        ctx["holder_headers"],
    )
    shipment = validate_success(response, 201)
    assert_forward_shipment(shipment)
    assert shipment["item_count"] == 3
    assert shipment["excluded_item_count"] == 0
    assert shipment["base_price_cents"] == 7614
    assert shipment["status"] == "PRICED"


def test_the_consolidation_discount_applies_to_the_already_rounded_base_price(api):
    """PRD §3.8: "When `item_count` is **greater than or equal to** 3,
    `consolidation_discount_cents` is 15 percent of `base_price_cents`, rounded half up
    to whole cents; otherwise it is zero."
    PRD §3.8: "`total_price_cents` is `base_price_cents` less
    `consolidation_discount_cents`."

    Design: Difficulty/combinatorial_formula/forward_price_rounds_per_item_before_summing
    """
    ctx = setup_box_with_forwardable_flats(
        "C-301", "Fay Ward", 3, holder_email="fay@example.com"
    )

    shipment = create_forward_shipment(
        ctx, "PRIORITY", "9 Elm Ave, Springfield", ctx["item_ids"]
    )
    assert shipment["base_price_cents"] == 7614
    assert shipment["consolidation_discount_cents"] == 1142
    assert shipment["total_price_cents"] == 6472


def test_exactly_three_eligible_pieces_earn_the_volume_discount(api):
    """PRD §3.8: "When `item_count` is **greater than or equal to** 3,
    `consolidation_discount_cents` is 15 percent of `base_price_cents`, rounded half up
    to whole cents; otherwise it is zero."
    PRD §3.8: "Exactly three eligible pieces earn the discount; two eligible pieces plus
    one excluded piece do not, because excluded pieces never count toward the
    threshold."

    Three eligible pieces sits exactly ON the inclusive lower edge of the discount.

    Design: Difficulty/boundary_precision_check/consolidation_discount_exactly_three_eligible_items
    """
    ctx = setup_box_with_forwardable_flats(
        "M-1301", "Tia Bundle", 6, lodge_forward_on=5, holder_email="tia@example.com"
    )

    shipment = create_forward_shipment(
        ctx, "PRIORITY", "9 Elm Ave, Springfield", ctx["item_ids"][0:3]
    )
    assert shipment["item_count"] == 3
    assert shipment["excluded_item_count"] == 0
    assert shipment["base_price_cents"] == 7614
    assert shipment["consolidation_discount_cents"] == 1142
    assert shipment["total_price_cents"] == 6472


def test_two_eligible_pieces_plus_one_excluded_piece_earn_nothing(api):
    """PRD §3.8: "Eligible pieces are attached to the shipment and have their
    `forward_shipment_id` set to it; ineligible ones are silently left off."
    PRD §3.8: "`item_count` is the number attached and `excluded_item_count` the number
    of supplied ids that failed."
    PRD §3.8: "Exactly three eligible pieces earn the discount; two eligible pieces plus
    one excluded piece do not, because excluded pieces never count toward the
    threshold."

    Two eligible pieces sits one BELOW the inclusive lower edge of the discount.

    Design: Difficulty/boundary_precision_check/consolidation_discount_exactly_three_eligible_items
    """
    ctx = setup_box_with_forwardable_flats(
        "M-1301", "Tia Bundle", 6, lodge_forward_on=5, holder_email="tia@example.com"
    )

    shipment = create_forward_shipment(
        ctx, "PRIORITY", "9 Elm Ave, Springfield", ctx["item_ids"][3:6]
    )
    assert shipment["item_count"] == 2
    assert shipment["excluded_item_count"] == 1
    assert shipment["base_price_cents"] == 5076
    assert shipment["consolidation_discount_cents"] == 0
    assert shipment["total_price_cents"] == 5076

    left_off = read_mail_item(ctx["item_ids"][5])
    assert left_off["forward_shipment_id"] is None
    assert left_off["handling_status"] == "HELD"


def test_the_weight_bracket_upper_bound_is_inclusive(api):
    """PRD §3.8: "Each piece falls into a weight bracket keyed on its
    `billable_weight_lb`, and each bracket's upper bound is **inclusive**: at most 1.0 lb
    costs 850 cents, above that and at most 5.0 lb costs 1,750 cents, above that and at
    most 20.0 lb costs 3,900 cents, and anything heavier costs 7,200 cents."
    PRD §3.8: "Exactly 5.0 lb therefore sits in the 1,750-cent bracket and 5.1 lb in the
    3,900-cent one."
    PRD §3.8: "The service multiplier is 1.00 for `ECONOMY`, 1.45 for `PRIORITY` and
    2.20 for `EXPRESS`."

    5.0 lb sits exactly ON the inclusive upper edge of bracket two; 5.1 lb is one tenth
    of a pound above it.

    Design: Corner/calculations/forward_weight_bracket_upper_bound_is_inclusive
    """
    ctx = setup_releasable_box("Z-2006", "Xia Weigh", holder_email="xia@example.com")
    on_edge = log_and_match_flat(ctx, actual_weight_lb=5.0, height_in=2.0)
    lodge_disposition(ctx, on_edge["id"], "FORWARD")
    above_edge = log_and_match_flat(ctx, actual_weight_lb=5.1, height_in=2.0)
    lodge_disposition(ctx, above_edge["id"], "FORWARD")

    first = create_forward_shipment(ctx, "ECONOMY", "5 Bracket Rd", [on_edge["id"]])
    assert first["base_price_cents"] == 1750
    assert first["total_price_cents"] == 1750

    second = create_forward_shipment(ctx, "ECONOMY", "5 Bracket Rd", [above_edge["id"]])
    assert second["base_price_cents"] == 3900
    assert second["total_price_cents"] == 3900


def test_a_consolidation_whose_every_piece_is_ineligible_is_rejected(api):
    """PRD §3.8: "An ineligible piece does **not** abort the shipment."
    PRD §3.8: "Only when *every* supplied id fails is the whole request rejected, with
    `ERR_ITEM_NOT_CONSOLIDATABLE`."

    Design: Corner/validations/forward_shipment_with_no_eligible_item_is_rejected
    """
    ctx = setup_releasable_box("Z-3013", "Pam Empty", holder_email="pam@example.com")
    first = log_and_match_letter(ctx)
    second = log_and_match_letter(ctx)

    response = api.create_forward_shipment(
        ctx["box_id"],
        forward_shipment_payload(
            "ECONOMY", "0 Nowhere St", [first["id"], second["id"]], box_version(ctx["box_id"])
        ),
        ctx["holder_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_CONSOLIDATABLE.value)

    _, meta = validate_paginated(
        api.list_box_forward_shipments(ctx["box_id"], CMRA_OPERATOR)
    )
    assert meta["total_count"] == 0
    assert read_mail_item(first["id"])["forward_shipment_id"] is None
    assert read_mail_item(second["id"])["forward_shipment_id"] is None


# ==========================================================================
# Dispatch under the suspension gate
# ==========================================================================
def _setup_priced_shipment_then_suspend(api):
    ctx = setup_box_with_forwardable_flats(
        "P-1601", "Wes Ship", 1, holder_email="wes@example.com"
    )
    shipment = create_forward_shipment(
        ctx, "ECONOMY", "2 Maple Dr, Springfield", ctx["item_ids"]
    )
    review = open_compliance_review(ctx["box_id"], "PAYMENT", "co-1")
    suspend_compliance_review(review["id"], "co-1")
    ctx["shipment"] = shipment
    ctx["shipment_id"] = shipment["id"]
    ctx["review_id"] = review["id"]
    return ctx


def test_a_priced_shipment_cannot_be_dispatched_once_the_mailbox_is_suspended(api):
    """PRD §2.8: "Its condition is that the target mailbox has `service_status` equal to
    `SUSPENDED`. When it holds and the operation is on the list below, the request is
    rejected with `ERR_BOX_SUSPENDED` (HTTP 409)."
    PRD §3.8: "Creating a shipment is blocked by both the suspension gate and the Form
    1583 gate; dispatching one is blocked by the suspension gate."

    Design: Difficulty/cross_entity_state_dependency/forward_shipment_ship_gated_by_box_service_status
    """
    ctx = _setup_priced_shipment_then_suspend(api)

    response = api.ship_forward_shipment(ctx["shipment_id"], CMRA_OPERATOR)
    validate_error(response, ApiErrorId.ERR_BOX_SUSPENDED.value)

    assert validate_success(api.get_box(ctx["box_id"], CMRA_OPERATOR))["service_status"] == (
        "SUSPENDED"
    )


def test_the_pricing_of_a_blocked_shipment_survives_the_suspension_untouched(api):
    """PRD §3.8: "Dispatch is `CmraOperator` work and requires the shipment to be
    `PRICED` with `item_count` of at least 1. It moves the shipment `PRICED → SHIPPED`,
    stamps `shipped_at` from the clock, drives every attached piece
    `PENDING_DISPOSITION → FORWARDED` with the piece's winning `FORWARD` request moving
    to `EXECUTED` with `resolution_reason` `EXECUTED`, moves each piece's
    `storage_status` to `RELEASED` with `released_at` stamped, appends exactly one
    usage-ledger entry of `unit_type` `FORWARD` and `quantity` 1 through the metering
    rule of §3.12, increments the cycle's `forwards_consumed` by 1, and bumps
    `ForwardShipment.version` by one."
    PRD §3.11: "**Hop 7.** Because those members left `AUTHORIZED`, their
    `release_eligibility` re-derives `RELEASABLE → BLOCKED`, which moves every piece of
    theirs whose `handling_status` is `HELD` back to `AWAITING_CLEARANCE`, each such
    piece bumping its `version` by one."

    Design: Difficulty/cross_entity_state_dependency/forward_shipment_ship_gated_by_box_service_status
    """
    ctx = _setup_priced_shipment_then_suspend(api)
    api.ship_forward_shipment(ctx["shipment_id"], CMRA_OPERATOR)

    shipment = validate_success(
        api.get_forward_shipment(ctx["shipment_id"], CMRA_OPERATOR)
    )
    assert shipment["status"] == "PRICED"
    assert shipment["base_price_cents"] == 1750
    assert shipment["consolidation_discount_cents"] == 0
    assert shipment["total_price_cents"] == 1750
    assert shipment["shipped_at"] is None

    piece = read_mail_item(ctx["item_ids"][0])
    assert piece["handling_status"] == "AWAITING_CLEARANCE"
    assert piece["forward_shipment_id"] == ctx["shipment_id"]


# ==========================================================================
# Cancelling a consolidation
# ==========================================================================
def test_cancelling_a_consolidation_releases_every_piece_back_to_the_queue(api):
    """PRD §3.8: "Cancelling a priced shipment is the holder's privilege and moves it
    `PRICED → CANCELLED`, clears `forward_shipment_id` on every attached piece so they
    may be consolidated again later, sets `item_count` to 0, and bumps
    `ForwardShipment.version` by one; the pieces themselves stay in
    `PENDING_DISPOSITION` with their forward requests still `PENDING`."

    Design: Difficulty/compensating_invariant/forward_shipment_cancel_restores_custody_cardinality
    """
    ctx = setup_box_with_forwardable_flats(
        "W-2301", "Zoe Undo", 3, holder_email="zoe@example.com"
    )
    shipment = create_forward_shipment(
        ctx, "EXPRESS", "44 Return Rd, Springfield", ctx["item_ids"]
    )
    assert shipment["base_price_cents"] == 11550
    assert shipment["consolidation_discount_cents"] == 1733
    assert shipment["total_price_cents"] == 9817

    cancelled = validate_success(
        api.cancel_forward_shipment(shipment["id"], ctx["holder_headers"])
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["item_count"] == 0

    for item_id in ctx["item_ids"]:
        piece = read_mail_item(item_id)
        assert piece["forward_shipment_id"] is None
        assert piece["handling_status"] == "PENDING_DISPOSITION"
        assert piece["storage_status"] == "FREE_WINDOW"


def test_cancelling_a_consolidation_conserves_the_custody_cardinality(api):
    """PRD §2.11: "For one mailbox, the number of pieces whose `storage_status` is
    `FREE_WINDOW` or `ACCRUING`, plus the number whose `storage_status` is `RELEASED`,
    plus the number whose `storage_status` is `DESTROYED`, equals the total number of
    pieces on that mailbox."
    PRD §3.8: "Note that one shipment consumes one forward unit no matter how many
    pieces it carries — that is the whole point of consolidating."

    Design: Difficulty/compensating_invariant/forward_shipment_cancel_restores_custody_cardinality
    """
    ctx = setup_box_with_forwardable_flats(
        "W-2301", "Zoe Undo", 3, holder_email="zoe@example.com"
    )
    shipment = create_forward_shipment(
        ctx, "EXPRESS", "44 Return Rd, Springfield", ctx["item_ids"]
    )
    validate_success(api.cancel_forward_shipment(shipment["id"], ctx["holder_headers"]))

    summary = validate_success(api.get_box_summary(ctx["box_id"], CMRA_OPERATOR))
    assert summary["items_in_custody"] == 3
    assert summary["items_released"] == 0
    assert summary["items_destroyed"] == 0
    assert_custody_cardinality(summary, 3)
    assert summary["forwards_consumed"] == 0

    cycles, _ = validate_paginated(api.list_billing_cycles(ctx["box_id"], CMRA_OPERATOR))
    _, meta = validate_paginated(
        api.list_cycle_usage_entries(
            cycles[0]["id"], CMRA_OPERATOR, params={"unit_type": "FORWARD"}
        )
    )
    assert meta["total_count"] == 0
