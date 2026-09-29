"""Refusals a piece earns from the state of the paperwork and the order beside it."""

from test_helpers import (
    FLOOR_OPERATOR,
    GALLERY_MANAGER,
    SCORES_GRADE_A,
    SCORES_GRADE_B,
    STD_SCHEDULE_STEPS,
    ApiErrorId,
    api_client,
    complete_delivery,
    create_active_agreement,
    create_buyer,
    create_consignor,
    create_crew,
    create_item,
    create_price_schedule,
    create_zone,
    damage_claim_payload,
    fetch_agreement,
    fetch_consignor,
    fetch_consignor_ledger,
    fetch_delivery_order,
    fetch_item,
    fetch_sale,
    fetch_zone,
    file_damage_claim,
    make_buyer_headers,
    place_item,
    place_payload,
    receive_item,
    run_markdown_epoch,
    schedule_delivery,
    screen_item,
    sell_item,
    set_clock,
    take_custody,
    total_count,
    validate_error,
)

TWO_STEP_SCHEDULE = STD_SCHEDULE_STEPS[:2]

SLIPCOVER_SOFA = {
    "title": "Slipcover sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 5,
    "volume_cuft": 55,
    "footprint_sqft": 24,
}
BUREAU = {
    "title": "Cherry bureau",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 20,
    "footprint_sqft": 18,
}


def _two_agreements_one_of_which_has_run_out():
    """One consignor, a thirty-day agreement and a year-long one, both with a piece.

    The clock is pushed two months out and the markdown epoch expires the short
    agreement without anybody touching either piece.
    """
    schedule = create_price_schedule(steps=TWO_STEP_SCHEDULE)
    consignor = create_consignor(payout_method="ACH")
    short = create_active_agreement(consignor["id"], schedule["id"], term_days=30)
    long = create_active_agreement(consignor["id"], schedule["id"], term_days=365)

    sofa = create_item(short["id"], **SLIPCOVER_SOFA)
    bureau = create_item(long["id"], **BUREAU)
    screen_item(sofa["id"], scores=SCORES_GRADE_B)
    screen_item(bureau["id"], scores=SCORES_GRADE_A)
    take_custody(consignor["id"], [sofa["id"], bureau["id"]])
    receive_item(sofa["id"], scores=SCORES_GRADE_B)
    receive_item(bureau["id"], scores=SCORES_GRADE_A)

    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)

    set_clock("2026-09-30T00:00:00Z")
    run_markdown_epoch()

    return {
        "consignor": consignor,
        "short_agreement": short,
        "long_agreement": long,
        "sofa": sofa,
        "bureau": bureau,
        "zone": zone,
    }


def test_placement_is_refused_for_a_piece_whose_agreement_has_expired():
    """The piece is in a perfectly legal state; the paperwork behind it is not.

    PRD 2.9: "The governing agreement's `status` is `ACTIVE`, on item intake and item
    placement — otherwise `ERR_AGREEMENT_NOT_ACTIVE` (409)."

    PRD 3.2: "The markdown epoch moves `ACTIVE → EXPIRED` for any agreement whose
    `expires_at` is at or before the current clock"

    PRD 3.6: "The owning agreement must be in `status` `ACTIVE` with the logical clock
    still strictly before its `expires_at`, otherwise `ERR_AGREEMENT_NOT_ACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/placement_blocked_by_expired_governing_agreement
    """
    world = _two_agreements_one_of_which_has_run_out()
    sofa_id = world["sofa"]["id"]

    short = fetch_agreement(world["short_agreement"]["id"])
    assert short["status"] == "EXPIRED", (
        f"Expected the thirty-day agreement EXPIRED, got {short['status']}"
    )
    assert short["expires_at"].startswith("2026-08-31T00:00:00"), (
        f"Expected a 2026-08-31 expiry, got {short['expires_at']}"
    )
    long = fetch_agreement(world["long_agreement"]["id"])
    assert long["status"] == "ACTIVE", (
        f"Expected the year-long agreement still ACTIVE, got {long['status']}"
    )

    before = fetch_item(sofa_id)
    assert before["lifecycle_state"] == "AWAITING_PLACEMENT", (
        f"Expected a legal placement from-state, got {before['lifecycle_state']}"
    )
    assert before["inventory_state"] == "IN_CUSTODY", (
        f"Expected a legal custody from-state, got {before['inventory_state']}"
    )

    response = api_client.place_item(
        sofa_id, place_payload(world["zone"]["id"], "T-1101"), FLOOR_OPERATOR
    )
    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)

    after = fetch_item(sofa_id)
    assert after["placement_zone_id"] is None, (
        f"Expected no zone written, got {after['placement_zone_id']}"
    )
    assert after["tag_code"] is None, (
        f"Expected no tag written, got {after['tag_code']}"
    )
    assert after["listed_at"] is None, (
        f"Expected no floor tenure started, got {after['listed_at']}"
    )
    assert after["version"] == before["version"], (
        f"Expected version {before['version']} unchanged, got {after['version']}"
    )

    zone = fetch_zone(world["zone"]["id"])
    assert zone["occupied_sqft"] == 0, (
        f"Expected an empty zone, so capacity was not the obstacle, "
        f"got {zone['occupied_sqft']}"
    )
    assert zone["status"] == "OPEN", (
        f"Expected an open zone, so closure was not the obstacle, "
        f"got {zone['status']}"
    )


def test_the_identical_placement_succeeds_under_the_agreement_still_running():
    """Same operator, same zone, same instant: only the governing paperwork differs.

    PRD 3.6: "On success the piece moves `AWAITING_PLACEMENT → ON_FLOOR`, its
    `placement_zone_id` and `tag_code` are written, and its `version` increments by 1."

    PRD 2.10: "Both figures are recomputed on every event that changes a zone's
    membership: a placement, a release, a write-off, a recovery and a clearance
    relocation."

    Design: Difficulty/cross_entity_state_dependency/placement_blocked_by_expired_governing_agreement
    """
    world = _two_agreements_one_of_which_has_run_out()
    zone_id = world["zone"]["id"]

    placed = place_item(world["bureau"]["id"], zone_id, tag_code="T-1102")
    assert placed["lifecycle_state"] == "ON_FLOOR", (
        f"Expected ON_FLOOR, got {placed['lifecycle_state']}"
    )
    assert placed["listed_at"].startswith("2026-09-30T00:00:00"), (
        f"Expected floor tenure to start now, got {placed['listed_at']}"
    )
    assert placed["placement_zone_id"] == zone_id, (
        f"Expected the front showroom, got {placed['placement_zone_id']}"
    )

    zone = fetch_zone(zone_id)
    assert zone["occupied_sqft"] == 18, (
        f"Expected the bureau's 18 square feet, got {zone['occupied_sqft']}"
    )

    consignor = fetch_consignor(world["consignor"]["id"])
    assert consignor["unclaimed_balance_cents"] == -32_000, (
        f"Expected only the 32000 collection debit, "
        f"got {consignor['unclaimed_balance_cents']}"
    )
    entries = fetch_consignor_ledger(world["consignor"]["id"])
    assert len(entries) == 1, (
        f"Expected one ledger entry, got {len(entries)}: "
        f"{[e['entry_type'] for e in entries]}"
    )


LINEN_SOFA = {
    "title": "Linen sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 5,
    "volume_cuft": 55,
    "footprint_sqft": 24,
}
DRESSER = {
    "title": "Maple dresser",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 20,
    "footprint_sqft": 18,
}


def _one_refused_delivery_beside_one_that_landed():
    """Two sales to one buyer on one crew: the dresser arrives, the sofa comes back."""
    schedule = create_price_schedule(steps=TWO_STEP_SCHEDULE)
    consignor = create_consignor(payout_method="ACH")
    agreement = create_active_agreement(consignor["id"], schedule["id"], term_days=365)

    sofa = create_item(agreement["id"], **LINEN_SOFA)
    dresser = create_item(agreement["id"], **DRESSER)
    screen_item(sofa["id"], scores=SCORES_GRADE_B)
    screen_item(dresser["id"], scores=SCORES_GRADE_A)
    take_custody(
        consignor["id"],
        [sofa["id"], dresser["id"]],
        window_start="2026-08-01T07:00:00Z",
        window_end="2026-08-01T09:00:00Z",
    )
    receive_item(sofa["id"], scores=SCORES_GRADE_B)
    receive_item(dresser["id"], scores=SCORES_GRADE_A)

    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    place_item(sofa["id"], zone["id"], tag_code="T-1201")
    place_item(dresser["id"], zone["id"], tag_code="T-1202")

    buyer = create_buyer(floor_number=2, has_elevator=False)
    sofa_sale = sell_item(sofa["id"], buyer["id"], 126_317)
    dresser_sale = sell_item(dresser["id"], buyer["id"], 51_000)

    crew = create_crew(name="Crew 1", max_concurrent_jobs=2)
    sofa_order = schedule_delivery(sofa_sale["id"], crew["id"])
    dresser_order = schedule_delivery(dresser_sale["id"], crew["id"])

    complete_delivery(dresser_order["id"], outcome="DELIVERED")
    complete_delivery(sofa_order["id"], outcome="REFUSED")

    return {
        "consignor": consignor,
        "zone": zone,
        "sofa": sofa,
        "dresser": dresser,
        "buyer": buyer,
        "sofa_sale": sofa_sale,
        "dresser_sale": dresser_sale,
        "sofa_order": sofa_order,
        "dresser_order": dresser_order,
    }


def test_a_refused_delivery_leaves_no_window_for_a_damage_claim():
    """The buyer who turned the sofa away at the door has nothing to claim against.

    PRD 2.9: "`claim_window_ends_at` is not null and the logical clock is strictly
    before it, on damage-claim filing — otherwise `ERR_CLAIM_WINDOW_CLOSED` (409)."

    PRD 3.8: "which is the mechanism by which a refused delivery can never carry a
    damage claim"

    PRD 3.8: "The sale moves `COMPLETED → REVERSED`, a `SALE_REVERSAL_DEBIT` of the
    negated `consignor_share_cents` is minted"

    Design: Difficulty/cross_entity_state_dependency/claim_filing_blocked_by_refused_delivery_leaving_the_window_null
    """
    world = _one_refused_delivery_beside_one_that_landed()
    order_id = world["sofa_order"]["id"]

    order = fetch_delivery_order(order_id)
    assert order["status"] == "REFUSED", (
        f"Expected REFUSED, got {order['status']}"
    )
    assert order["delivery_fee_cents"] == 12_000, (
        f"Expected 7500 plus one flight of stairs, "
        f"got {order['delivery_fee_cents']}"
    )
    assert order["claim_window_ends_at"] is None, (
        f"Expected no claim window at all, got {order['claim_window_ends_at']}"
    )
    assert order["outcome_recorded_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected the outcome stamped from the clock, "
        f"got {order['outcome_recorded_at']}"
    )

    response = api_client.create_damage_claim(
        damage_claim_payload(
            order_id, 30_000, description="Frame cracked, refused at the door"
        ),
        make_buyer_headers(world["buyer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED, 409)

    listed = api_client.list_damage_claims(
        GALLERY_MANAGER, params={"delivery_order_id": order_id, "limit": 100}
    )
    assert total_count(listed) == 0, (
        f"Expected no claim row to survive the refusal, got {total_count(listed)}"
    )

    sale = fetch_sale(world["sofa_sale"]["id"])
    assert sale["status"] == "REVERSED", (
        f"Expected the sale reversed by the refusal, got {sale['status']}"
    )
    entries = fetch_consignor_ledger(world["consignor"]["id"])
    reversals = [e for e in entries if e["entry_type"] == "SALE_REVERSAL_DEBIT"]
    assert len(reversals) == 1, (
        f"Expected one reversal debit, got {len(reversals)}"
    )
    assert reversals[0]["amount_cents"] == -69_474, (
        f"Expected -69474, got {reversals[0]['amount_cents']}"
    )

    sofa = fetch_item(world["sofa"]["id"])
    assert sofa["lifecycle_state"] == "ON_FLOOR", (
        f"Expected the sofa back on the floor, got {sofa['lifecycle_state']}"
    )
    assert sofa["markdown_sequence"] == 1, (
        f"Expected the first step still in force, got {sofa['markdown_sequence']}"
    )
    assert sofa["placement_zone_id"] == world["zone"]["id"], (
        f"Expected the zone it never left, got {sofa['placement_zone_id']}"
    )


def test_the_delivered_sibling_opens_a_five_day_window_and_accepts_a_claim():
    """The dresser that arrived settles, frees its footage and can be claimed against.

    PRD 3.8: "`claim_window_ends_at` is set to the current clock advanced by five whole
    days, that is by 5 multiplied by 86,400 seconds"

    PRD 3.8: "the piece moves `SOLD → SETTLED` on the merchandising dimension and
    `IN_CUSTODY → RELEASED` on the custody dimension"

    PRD 3.8: "Add an assembly charge of 4,000 cents when the sold piece's `category` is
    `DINING` or `CASEGOOD`, and nothing otherwise"

    Design: Difficulty/cross_entity_state_dependency/claim_filing_blocked_by_refused_delivery_leaving_the_window_null
    """
    world = _one_refused_delivery_beside_one_that_landed()

    order = fetch_delivery_order(world["dresser_order"]["id"])
    assert order["status"] == "DELIVERED", (
        f"Expected DELIVERED, got {order['status']}"
    )
    assert order["delivery_fee_cents"] == 16_000, (
        f"Expected 7500 plus 4500 of stairs plus 4000 of assembly, "
        f"got {order['delivery_fee_cents']}"
    )
    assert order["claim_window_ends_at"].startswith("2026-08-06T00:00:00"), (
        f"Expected a window closing five days out, "
        f"got {order['claim_window_ends_at']}"
    )

    sale = fetch_sale(world["dresser_sale"]["id"])
    assert sale["status"] == "SETTLED", (
        f"Expected the sale settled, got {sale['status']}"
    )
    dresser = fetch_item(world["dresser"]["id"])
    assert dresser["lifecycle_state"] == "SETTLED", (
        f"Expected SETTLED, got {dresser['lifecycle_state']}"
    )
    assert dresser["inventory_state"] == "RELEASED", (
        f"Expected RELEASED, got {dresser['inventory_state']}"
    )
    assert dresser["placement_zone_id"] is None, (
        f"Expected the zone cleared, got {dresser['placement_zone_id']}"
    )

    claim = file_damage_claim(order["id"], world["buyer"]["id"], 20_000)
    assert claim["status"] == "SUBMITTED", (
        f"Expected SUBMITTED, got {claim['status']}"
    )
    assert claim["resubmission_count"] == 0, (
        f"Expected a fresh claim, got {claim['resubmission_count']}"
    )

    zone = fetch_zone(world["zone"]["id"])
    assert zone["occupied_sqft"] == 24, (
        f"Expected only the returned sofa on the floor, "
        f"got {zone['occupied_sqft']}"
    )

    entries = fetch_consignor_ledger(world["consignor"]["id"])
    assert [e["amount_cents"] for e in entries] == [
        -32_000,
        69_474,
        30_600,
        -69_474,
    ], f"Expected the four-entry history, got {[e['amount_cents'] for e in entries]}"
    consignor = fetch_consignor(world["consignor"]["id"])
    assert consignor["unclaimed_balance_cents"] == -1_400, (
        f"Expected -1400, got {consignor['unclaimed_balance_cents']}"
    )
