"""Negotiating a claim, capping a claim, and spending the discount budget."""

from test_helpers import (
    GALLERY_MANAGER,
    SCORES_GRADE_A,
    ApiErrorId,
    advance_to_markdown_step,
    api_client,
    complete_delivery,
    create_buyer,
    create_crew,
    create_item,
    create_zone,
    damage_claim_payload,
    elect_disposition,
    elect_disposition_payload,
    fetch_damage_claim,
    fetch_item,
    fetch_sale,
    file_damage_claim,
    make_buyer_headers,
    make_consignor_headers,
    place_item,
    receive_item,
    request_claim_info,
    request_info_payload,
    resubmit_claim,
    schedule_delivery,
    screen_item,
    sell_item,
    setup_consignor_with_active_agreement,
    take_custody,
    total_count,
    validate_error,
)

ONE_STEP = [(1, 0, 0.00, 0)]

SOLD_BUREAU = {
    "title": "Bureau",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 5,
    "volume_cuft": 12,
    "footprint_sqft": 10,
}
FIRST_NOTE = "Send photographs of the gouge"


def _a_bureau_delivered_to_nora_for_fifty_one_thousand():
    """One CASEGOOD sold at 51,000 and delivered, so a five-day claim window is open."""
    world = setup_consignor_with_active_agreement(
        schedule_steps=ONE_STEP,
        consignor_overrides={"floor_number": 1, "has_elevator": False},
    )
    bureau = create_item(world["agreement"]["id"], **SOLD_BUREAU)
    screen_item(bureau["id"], scores=SCORES_GRADE_A)
    take_custody(world["consignor"]["id"], [bureau["id"]])
    receive_item(bureau["id"], scores=SCORES_GRADE_A)

    world["zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    world["bureau"] = place_item(bureau["id"], world["zone"]["id"], tag_code="SHOWROOM-1")

    world["buyer"] = create_buyer(
        display_name="Nora Vance", floor_number=2, has_elevator=False
    )
    world["sale"] = sell_item(bureau["id"], world["buyer"]["id"], 51_000)
    world["crew"] = create_crew(name="WG-1", max_concurrent_jobs=2)
    world["order"] = schedule_delivery(world["sale"]["id"], world["crew"]["id"])
    world["order"] = complete_delivery(world["order"]["id"], outcome="DELIVERED")
    return world


def test_requesting_information_twice_in_a_row_on_one_claim_is_refused():
    """The block is the from-state, not an exhausted budget, and the resubmit proves it.

    PRD 3.8: "Requesting information on a claim that is not `SUBMITTED`, resubmitting one
    that is not `INFO_REQUESTED`, or adjudicating one that is not `SUBMITTED`, is refused
    with `ERR_CLAIM_STATE_INVALID`."

    PRD 3.8: "A `GalleryManager` may send a `SUBMITTED` claim back for more detail by
    supplying an `info_request_note`, which moves it `SUBMITTED → INFO_REQUESTED`, stores
    the note, leaves `resubmission_count` unchanged and does **not** extend the claim
    clock."

    PRD 3.8: "With `withdraw` false or absent, the claim moves `INFO_REQUESTED →
    SUBMITTED`, `resubmission_count` is incremented by 1, and the stored `description` is
    replaced by the resubmitted narrative."

    Design: Corner/errors/requesting_information_twice_in_a_row_on_one_claim_is_refused
    """
    world = _a_bureau_delivered_to_nora_for_fifty_one_thousand()
    claim = file_damage_claim(world["order"]["id"], world["buyer"]["id"], 20_000)
    assert claim["status"] == "SUBMITTED", (
        f"Expected a filed claim to open SUBMITTED, got {claim['status']}"
    )
    assert claim["resubmission_count"] == 0, (
        f"Expected an unspent budget, got {claim['resubmission_count']}"
    )

    asked = request_claim_info(claim["id"], FIRST_NOTE)
    assert asked["status"] == "INFO_REQUESTED", (
        f"Expected INFO_REQUESTED, got {asked['status']}"
    )
    assert asked["resubmission_count"] == 0, (
        f"Expected the request to leave the count alone, "
        f"got {asked['resubmission_count']}"
    )

    again = api_client.request_claim_info(
        claim["id"], request_info_payload("Send them again please"), GALLERY_MANAGER
    )
    validate_error(again, ApiErrorId.ERR_CLAIM_STATE_INVALID, 409)

    after = fetch_damage_claim(claim["id"])
    assert after["status"] == "INFO_REQUESTED", (
        f"Expected INFO_REQUESTED still, got {after['status']}"
    )
    assert after["resubmission_count"] == 0, (
        f"Expected the budget still unspent, got {after['resubmission_count']}"
    )
    assert after["info_request_note"] == FIRST_NOTE, (
        f"Expected the refused note never to land, got {after['info_request_note']}"
    )

    answered = resubmit_claim(
        claim["id"], world["buyer"]["id"], description="Photographs attached."
    )
    assert answered["status"] == "SUBMITTED", (
        f"Expected the buyer's answer to be accepted, got {answered['status']}"
    )
    assert answered["resubmission_count"] == 1, (
        f"Expected one pass spent, got {answered['resubmission_count']}"
    )


def test_a_claim_one_cent_above_the_sale_price_is_refused():
    """The ceiling is what the piece fetched, and the boundary is inclusive.

    PRD 3.8: "`claim_amount_cents` must not exceed the parent sale's `sale_price_cents`,
    otherwise `ERR_CLAIM_EXCEEDS_SALE`."

    PRD 3.8: "A filed claim opens in `status` `SUBMITTED` with `resubmission_count` at 0
    and has no ledger effect whatsoever."

    PRD 3.8: "`refund_cents` opens at 0 and accumulates only through damage adjudication."

    Design: Corner/errors/a_claim_one_cent_above_the_sale_price_is_refused
    """
    world = _a_bureau_delivered_to_nora_for_fifty_one_thousand()
    order_id = world["order"]["id"]
    buyer_headers = make_buyer_headers(world["buyer"]["id"])

    over = api_client.create_damage_claim(
        damage_claim_payload(
            order_id,
            51_001,
            description="Claiming a cent more than the piece fetched",
        ),
        buyer_headers,
    )
    validate_error(over, ApiErrorId.ERR_CLAIM_EXCEEDS_SALE, 422)

    filed = api_client.list_damage_claims(
        GALLERY_MANAGER, params={"delivery_order_id": order_id, "limit": 100}
    )
    assert total_count(filed) == 0, (
        f"Expected no claim on the order, got {total_count(filed)}"
    )

    sale = fetch_sale(world["sale"]["id"])
    assert sale["refund_cents"] == 0, (
        f"Expected nothing refunded, got {sale['refund_cents']}"
    )
    assert sale["status"] == "SETTLED", (
        f"Expected the delivered sale settled and untouched, got {sale['status']}"
    )

    exact = api_client.create_damage_claim(
        damage_claim_payload(
            order_id, 51_000, description="Claiming exactly what the piece fetched"
        ),
        buyer_headers,
    )
    assert exact.status_code == 201, (
        f"Expected the sale price itself to be claimable, "
        f"got {exact.status_code}: {exact.text}"
    )
    accepted = exact.json()["data"]
    assert accepted["status"] == "SUBMITTED", (
        f"Expected SUBMITTED, got {accepted['status']}"
    )
    assert accepted["claim_amount_cents"] == 51_000, (
        f"Expected 51000, got {accepted['claim_amount_cents']}"
    )


UNSOLD_HIGHBOY = {
    "title": "Highboy",
    "category": "CASEGOOD",
    "declared_value_cents": 100_000,
    "photo_count": 5,
    "volume_cuft": 12,
    "footprint_sqft": 10,
}


def test_a_third_discount_election_on_one_piece_is_refused():
    """Two discount rounds are the budget, and a return is still open afterwards.

    PRD 3.7: "That loop is bounded: `election_round` must be strictly below 2 when a
    `DISCOUNT` election is attempted, so a piece can be discounted back onto the floor at
    most twice, and a third attempt is refused with `ERR_ELECTION_ROUND_EXHAUSTED`."

    PRD 3.7: "multiply `list_price_cents` by one minus the step's `markdown_pct`, then
    multiply that by one minus ten hundredths, round the result half up to a whole number of
    cents, and only then raise it to the step's `min_price_cents` if it fell below."

    PRD 3.7: "Each piece carries an effective trigger day, `unsold_trigger_day_effective`,
    computed as the schedule's `unsold_trigger_day` plus 30 days for each discount round the
    consignor has already taken — that is, plus 30 multiplied by `election_round`."

    PRD 3.7: "Electing `DONATE` moves the piece `UNSOLD_PENDING_ELECTION →
    DONATION_SCHEDULED`, and electing `RETURN` moves it `UNSOLD_PENDING_ELECTION →
    RETURN_SCHEDULED`; both set `disposition_election` to the elected value and clear
    `election_deadline_at` to null, and both increment the piece's `version` by 1."

    Design: Corner/errors/a_third_discount_election_on_one_piece_is_refused
    """
    world = setup_consignor_with_active_agreement(
        schedule_steps=ONE_STEP,
        consignor_overrides={"floor_number": 1, "has_elevator": False},
    )
    consignor_id = world["consignor"]["id"]
    highboy = create_item(world["agreement"]["id"], **UNSOLD_HIGHBOY)
    screen_item(highboy["id"], scores=SCORES_GRADE_A)
    take_custody(consignor_id, [highboy["id"]])
    receive_item(highboy["id"], scores=SCORES_GRADE_A)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    listed = place_item(highboy["id"], zone["id"], tag_code="SHOWROOM-1")
    assert listed["list_price_cents"] == 85_000, (
        f"Expected 100000 at eighty-five hundredths, got {listed['list_price_cents']}"
    )

    advance_to_markdown_step("2026-11-29T00:00:00Z")
    flagged = fetch_item(highboy["id"])
    assert flagged["lifecycle_state"] == "UNSOLD_PENDING_ELECTION", (
        f"Expected the piece flagged on day 120, got {flagged['lifecycle_state']}"
    )
    assert flagged["election_deadline_at"] == "2026-12-13T00:00:00.000Z", (
        f"Expected a fourteen-day window, got {flagged['election_deadline_at']}"
    )

    first = elect_disposition(highboy["id"], "DISCOUNT", consignor_id)
    assert first["election_round"] == 1, (
        f"Expected one round spent, got {first['election_round']}"
    )
    assert first["current_price_cents"] == 76_500, (
        f"Expected 85000 at ninety hundredths, got {first['current_price_cents']}"
    )
    assert first["unsold_trigger_day_effective"] == 150, (
        f"Expected 120 pushed out by thirty days, "
        f"got {first['unsold_trigger_day_effective']}"
    )

    advance_to_markdown_step("2026-12-29T00:00:00Z")
    assert fetch_item(highboy["id"])["election_deadline_at"] == "2027-01-12T00:00:00.000Z", (
        "Expected a second fourteen-day window on day 150"
    )
    second = elect_disposition(highboy["id"], "DISCOUNT", consignor_id)
    assert second["election_round"] == 2, (
        f"Expected the budget spent, got {second['election_round']}"
    )
    assert second["unsold_trigger_day_effective"] == 180, (
        f"Expected 120 pushed out by sixty days, "
        f"got {second['unsold_trigger_day_effective']}"
    )

    advance_to_markdown_step("2027-01-28T00:00:00Z")
    third_time = fetch_item(highboy["id"])
    assert third_time["lifecycle_state"] == "UNSOLD_PENDING_ELECTION", (
        f"Expected a third flagging on day 180, got {third_time['lifecycle_state']}"
    )
    assert third_time["election_deadline_at"] == "2027-02-11T00:00:00.000Z", (
        f"Expected the window open, so only the round budget is spent, "
        f"got {third_time['election_deadline_at']}"
    )

    exhausted = api_client.elect_disposition(
        highboy["id"],
        elect_disposition_payload("DISCOUNT"),
        make_consignor_headers(consignor_id),
    )
    validate_error(exhausted, ApiErrorId.ERR_ELECTION_ROUND_EXHAUSTED, 409)

    unmoved = fetch_item(highboy["id"])
    assert unmoved["lifecycle_state"] == "UNSOLD_PENDING_ELECTION", (
        f"Expected the piece parked where it stood, got {unmoved['lifecycle_state']}"
    )
    assert unmoved["election_round"] == 2, (
        f"Expected two rounds, got {unmoved['election_round']}"
    )
    assert unmoved["current_price_cents"] == 76_500, (
        f"Expected the price unmoved, got {unmoved['current_price_cents']}"
    )
    assert unmoved["election_deadline_at"] == "2027-02-11T00:00:00.000Z", (
        f"Expected the deadline unmoved, got {unmoved['election_deadline_at']}"
    )

    returned = elect_disposition(highboy["id"], "RETURN", consignor_id)
    assert returned["lifecycle_state"] == "RETURN_SCHEDULED", (
        f"Expected a return to remain available, got {returned['lifecycle_state']}"
    )
    assert returned["disposition_election"] == "RETURN", (
        f"Expected RETURN recorded, got {returned['disposition_election']}"
    )
    assert returned["election_deadline_at"] is None, (
        f"Expected the deadline cleared, got {returned['election_deadline_at']}"
    )
