"""One sale walks through the ledger and re-opens a closed consignor account."""

from test_helpers import (
    FLOOR_OPERATOR,
    GALLERY_MANAGER,
    SCORES_GRADE_B,
    SCORES_GRADE_C,
    STD_SCHEDULE_STEPS,
    ApiErrorId,
    api_client,
    create_buyer,
    create_item,
    create_zone,
    fetch_consignor,
    fetch_consignor_ledger,
    fetch_item,
    fetch_pickup_job,
    fetch_zone,
    get_success_data,
    place_item,
    place_payload,
    receive_item,
    screen_item,
    sell_item,
    setup_consignor_with_active_agreement,
    take_custody,
    validate_error,
)

TWO_STEP_SCHEDULE = STD_SCHEDULE_STEPS[:2]

SECTIONAL = {
    "title": "Sectional sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 5,
    "volume_cuft": 65,
    "footprint_sqft": 24,
}
PATIO = {
    "title": "Teak patio set",
    "category": "OUTDOOR",
    "declared_value_cents": 30_000,
    "photo_count": 4,
    "volume_cuft": 90,
    "footprint_sqft": 10,
}


def _suspended_consignor_with_one_saleable_sofa():
    """Two collections drive the account under water; the sofa waits on the floor.

    The consignor moves from the third to the ninth floor between the two jobs, so
    the second job snapshots an eight-flight climb whose surcharge runs straight
    into the declared-value cap of a cheap patio set.
    """
    world = setup_consignor_with_active_agreement(
        schedule_steps=TWO_STEP_SCHEDULE,
        consignor_overrides={"floor_number": 3, "has_elevator": False},
    )
    consignor_id = world["consignor"]["id"]

    sofa = create_item(world["agreement"]["id"], **SECTIONAL)
    screen_item(sofa["id"], scores=SCORES_GRADE_B)
    first = take_custody(consignor_id, [sofa["id"]], actual_stair_flights=2)
    world["truck"] = first["truck"]
    world["job_one"] = first["pickup_job"]
    receive_item(sofa["id"], scores=SCORES_GRADE_B)
    world["zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    world["sofa"] = place_item(sofa["id"], world["zone"]["id"], tag_code="T-7001")

    get_success_data(
        api_client.patch_consignor(consignor_id, {"floor_number": 9}, GALLERY_MANAGER)
    )

    patio = create_item(world["agreement"]["id"], **PATIO)
    screen_item(patio["id"], scores=SCORES_GRADE_C)
    second = take_custody(
        consignor_id,
        [patio["id"]],
        truck=world["truck"],
        window_start="2026-08-02T09:00:00Z",
        window_end="2026-08-02T12:00:00Z",
        crew_size=4,
        actual_stair_flights=8,
        actual_crew_size=4,
    )
    world["job_two"] = second["pickup_job"]
    world["patio"] = receive_item(patio["id"], scores=SCORES_GRADE_C)

    world["buyer"] = create_buyer()
    return world


def test_capped_second_surcharge_suspends_the_account_and_bars_the_floor():
    """The eight-flight climb bills at the cap and the showroom closes to the patio set.

    PRD 3.4: "when the flight count is strictly greater than 6, add a further 8,000
    cents extreme-climb premium on top of the six charged flights"

    PRD 2.11: "Whenever a recomputed `unclaimed_balance_cents` falls below negative
    50,000 cents, the consignor's `status` becomes `SUSPENDED`"

    PRD 3.6: "the owning consignor must be `ACTIVE`, otherwise `ERR_CONSIGNOR_SUSPENDED`"

    Design: Difficulty/transitive_cascade/sale_credit_cascades_through_ledger_into_consignor_reinstatement
    """
    world = _suspended_consignor_with_one_saleable_sofa()

    job_one = fetch_pickup_job(world["job_one"]["id"])
    assert job_one["final_surcharge_cents"] == 44_000, (
        f"Expected 44000 for the two-flight sofa collection, "
        f"got {job_one['final_surcharge_cents']}"
    )

    job_two = fetch_pickup_job(world["job_two"]["id"])
    assert job_two["declared_stair_flights"] == 8, (
        f"Expected 8 declared flights from the ninth floor, "
        f"got {job_two['declared_stair_flights']}"
    )
    assert job_two["final_surcharge_cents"] == 10_500, (
        f"Expected the 10500 cap on 30000 declared cents, "
        f"got {job_two['final_surcharge_cents']}"
    )
    assert job_two["final_surcharge_cents"] != 100_775, (
        "The uncapped four-mover extreme climb must not be billed"
    )

    consignor = fetch_consignor(world["consignor"]["id"])
    assert consignor["unclaimed_balance_cents"] == -54_500, (
        f"Expected -54500 after both collections, "
        f"got {consignor['unclaimed_balance_cents']}"
    )
    assert consignor["status"] == "SUSPENDED", (
        f"Expected SUSPENDED below -50000, got {consignor['status']}"
    )

    refused = api_client.place_item(
        world["patio"]["id"],
        place_payload(world["zone"]["id"], "T-7002"),
        FLOOR_OPERATOR,
    )
    validate_error(refused, ApiErrorId.ERR_CONSIGNOR_SUSPENDED, 409)

    patio = fetch_item(world["patio"]["id"])
    assert patio["lifecycle_state"] == "AWAITING_PLACEMENT", (
        f"Expected the refused piece to stay AWAITING_PLACEMENT, "
        f"got {patio['lifecycle_state']}"
    )
    assert patio["placement_zone_id"] is None, (
        f"Expected no zone on the refused piece, got {patio['placement_zone_id']}"
    )


def test_sale_credit_lifts_the_balance_and_reinstates_the_consignor():
    """Selling the sofa mints one credit that carries the account back above zero.

    PRD 3.8: "Second, because the sale exists, one `SALE_CREDIT` ledger entry of
    positive `consignor_share_cents` is minted against the consignor."

    PRD 3.8: "a consignor whose `status` was `SUSPENDED` and whose recomputed balance
    is now greater than or equal to zero returns to `ACTIVE`"

    Design: Difficulty/transitive_cascade/sale_credit_cascades_through_ledger_into_consignor_reinstatement
    """
    world = _suspended_consignor_with_one_saleable_sofa()
    consignor_id = world["consignor"]["id"]

    sale = sell_item(world["sofa"]["id"], world["buyer"]["id"], 126_317)

    assert sale["split_pct_applied"] == 0.55, (
        f"Expected a 0.55 split on a first-step sofa at 126317, "
        f"got {sale['split_pct_applied']}"
    )
    assert sale["consignor_share_cents"] == 69_474, (
        f"Expected 69474, got {sale['consignor_share_cents']}"
    )
    assert sale["gallery_share_cents"] == 56_843, (
        f"Expected 56843, got {sale['gallery_share_cents']}"
    )
    assert (
        sale["consignor_share_cents"] + sale["gallery_share_cents"] == 126_317
    ), "The two shares must sum to the sale price exactly"

    entries = fetch_consignor_ledger(consignor_id)
    assert len(entries) == 3, (
        f"Expected three consignor entries, got {len(entries)}: "
        f"{[e['entry_type'] for e in entries]}"
    )
    credits = [e for e in entries if e["entry_type"] == "SALE_CREDIT"]
    assert len(credits) == 1, (
        f"Expected exactly one SALE_CREDIT, got {len(credits)}"
    )
    assert credits[0]["amount_cents"] == 69_474, (
        f"Expected +69474 on the credit, got {credits[0]['amount_cents']}"
    )
    assert credits[0]["balance_after_cents"] == 14_974, (
        f"Expected a running balance of 14974, "
        f"got {credits[0]['balance_after_cents']}"
    )
    assert credits[0]["item_id"] == world["sofa"]["id"], (
        f"Expected the credit to name the sofa, got {credits[0]['item_id']}"
    )
    debits = sorted(
        e["amount_cents"] for e in entries if e["entry_type"] != "SALE_CREDIT"
    )
    assert debits == [-44_000, -10_500], (
        f"Expected the two surcharge debits to survive untouched, got {debits}"
    )

    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == 14_974, (
        f"Expected -54500 + 69474 = 14974, "
        f"got {consignor['unclaimed_balance_cents']}"
    )
    assert consignor["lifetime_credits_cents"] == 69_474, (
        f"Expected 69474 of lifetime credits, "
        f"got {consignor['lifetime_credits_cents']}"
    )
    assert consignor["status"] == "ACTIVE", (
        f"Expected reinstatement to ACTIVE, got {consignor['status']}"
    )
    assert consignor["escheat_state"] == "NONE", (
        f"Expected escheat_state NONE, got {consignor['escheat_state']}"
    )


def test_reinstatement_unlocks_the_placement_the_suspension_refused():
    """With the account reopened the patio set reaches a floor and owes a relocation.

    PRD 3.8: "so a sold-but-undelivered piece keeps counting toward its zone's
    `occupied_sqft`"

    PRD 3.6: "When no clearance zone qualifies, nothing moves: the piece stays exactly
    where it is"

    Design: Difficulty/transitive_cascade/sale_credit_cascades_through_ledger_into_consignor_reinstatement
    """
    world = _suspended_consignor_with_one_saleable_sofa()
    zone_id = world["zone"]["id"]

    sell_item(world["sofa"]["id"], world["buyer"]["id"], 126_317)

    placed = place_item(world["patio"]["id"], zone_id, tag_code="T-7002")
    assert placed["lifecycle_state"] == "ON_FLOOR", (
        f"Expected ON_FLOOR once the consignor is ACTIVE again, "
        f"got {placed['lifecycle_state']}"
    )
    assert placed["current_price_cents"] == 14_025, (
        f"Expected a 14025 ticket on the grade-C patio set, "
        f"got {placed['current_price_cents']}"
    )
    assert placed["placement_zone_id"] == zone_id, (
        f"Expected the piece to stay in the front showroom for want of a clearance "
        f"zone, got {placed['placement_zone_id']}"
    )
    assert placed["clearance_relocation_pending"] is True, (
        f"Expected an unhonoured relocation to be recorded, "
        f"got {placed['clearance_relocation_pending']}"
    )

    sofa = fetch_item(world["sofa"]["id"])
    assert sofa["lifecycle_state"] == "SOLD", (
        f"Expected the sofa to read SOLD, got {sofa['lifecycle_state']}"
    )
    assert sofa["placement_zone_id"] == zone_id, (
        f"Expected the sold sofa to keep its zone until delivery, "
        f"got {sofa['placement_zone_id']}"
    )

    zone = fetch_zone(zone_id)
    assert zone["occupied_sqft"] == 34, (
        f"Expected 24 sold square feet plus 10 new ones, "
        f"got {zone['occupied_sqft']}"
    )
    assert zone["utilization_state"] == "NORMAL", (
        f"Expected NORMAL at 34 of 200 square feet, "
        f"got {zone['utilization_state']}"
    )
