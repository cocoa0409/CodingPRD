"""Two boundaries: the thirtieth day on the floor, and a count that found everything."""

from test_helpers import (
    FLOOR_OPERATOR_ID,
    GALLERY_MANAGER,
    SCORES_GRADE_A,
    SCORES_GRADE_B,
    api_client,
    create_item,
    create_zone,
    fetch_consignor_ledger,
    fetch_item,
    fetch_zone,
    get_success_data,
    place_item,
    receive_item,
    run_markdown_epoch,
    screen_item,
    set_clock,
    setup_consignor_with_active_agreement,
    submit_shrinkage_audit,
    take_custody,
)

CAMELBACK = {
    "title": "Camelback sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 5,
    "volume_cuft": 55,
    "footprint_sqft": 24,
}
CHESTERFIELD = {
    "title": "Chesterfield sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 5,
    "volume_cuft": 65,
    "footprint_sqft": 24,
}
SIDEBOARD = {
    "title": "Walnut sideboard",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 20,
    "footprint_sqft": 18,
}
NIGHTSTAND = {
    "title": "Oak nightstand",
    "category": "CASEGOOD",
    "declared_value_cents": 20_000,
    "photo_count": 3,
    "volume_cuft": 13,
    "footprint_sqft": 12,
}


def _sofa_listed_on_the_first_of_august():
    """One grade-B sofa on the front showroom, listed while the clock reads 2026-08-01."""
    world = setup_consignor_with_active_agreement(
        consignor_overrides={"payout_method": "ACH"}
    )
    sofa = create_item(world["agreement"]["id"], **CAMELBACK)
    screen_item(sofa["id"], scores=SCORES_GRADE_B)
    take_custody(world["consignor"]["id"], [sofa["id"]])
    receive_item(sofa["id"], scores=SCORES_GRADE_B)
    world["zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    world["sofa"] = place_item(sofa["id"], world["zone"]["id"], tag_code="T-1001")
    return world


def test_the_twenty_ninth_day_is_still_the_first_step_and_the_thirtieth_is_not():
    """Tenure is floored whole days, so the second step bites on the boundary itself.

    PRD 3.7: "`days_on_floor` is the number of whole days between `listed_at` and the
    current logical clock: subtract `listed_at` from the clock, divide the elapsed
    seconds by 86,400, and discard the remainder"

    PRD 3.7: "The stepped price is `list_price_cents` multiplied by one minus the
    step's `markdown_pct`, rounded half up to a whole number of cents."

    PRD 2.4: "during the markdown epoch an item's `version` is incremented only when
    one of its fields actually changed"

    Design: Difficulty/boundary_precision_check/markdown_step_two_applies_at_exactly_day_thirty
    """
    world = _sofa_listed_on_the_first_of_august()
    item_id = world["sofa"]["id"]
    version_at_listing = world["sofa"]["version"]

    set_clock("2026-08-30T00:00:00Z")
    run_markdown_epoch()

    day_29 = fetch_item(item_id)
    assert day_29["markdown_sequence"] == 1, (
        f"Expected the first step still in force on day 29, "
        f"got {day_29['markdown_sequence']}"
    )
    assert day_29["current_price_cents"] == 126_317, (
        f"Expected an unmarked 126317 on day 29, "
        f"got {day_29['current_price_cents']}"
    )
    assert day_29["lifecycle_state"] == "ON_FLOOR", (
        f"Expected ON_FLOOR on day 29, got {day_29['lifecycle_state']}"
    )
    assert day_29["version"] == version_at_listing, (
        f"Expected version {version_at_listing} unchanged by a run that moved "
        f"nothing, got {day_29['version']}"
    )

    set_clock("2026-08-31T00:00:00Z")
    run_markdown_epoch()

    day_30 = fetch_item(item_id)
    assert day_30["markdown_sequence"] == 2, (
        f"Expected the second step on day 30, got {day_30['markdown_sequence']}"
    )
    assert day_30["current_price_cents"] == 107_369, (
        f"Expected round_half_up(126317 * 0.85) = 107369, "
        f"got {day_30['current_price_cents']}"
    )
    assert day_30["lifecycle_state"] == "MARKED_DOWN", (
        f"Expected MARKED_DOWN on day 30, got {day_30['lifecycle_state']}"
    )
    assert day_30["list_price_cents"] == 126_317, (
        f"Expected the ticket price to stay 126317, "
        f"got {day_30['list_price_cents']}"
    )


def test_the_thirty_first_day_changes_nothing_and_no_run_touches_the_ledger():
    """Past the boundary the piece sits still, and the epoch never books money.

    PRD 3.7: "A piece already in `MARKED_DOWN` whose governing step `sequence` is
    strictly greater than its stored `markdown_sequence` takes the self-loop"

    PRD 2.10: "`occupied_sqft` is the exact integer sum of `footprint_sqft` over every
    `ConsignmentItem` whose `placement_zone_id` names that zone"

    Design: Difficulty/boundary_precision_check/markdown_step_two_applies_at_exactly_day_thirty
    """
    world = _sofa_listed_on_the_first_of_august()
    item_id = world["sofa"]["id"]
    zone_id = world["zone"]["id"]

    set_clock("2026-08-31T00:00:00Z")
    run_markdown_epoch()
    at_boundary = fetch_item(item_id)

    set_clock("2026-09-01T00:00:00Z")
    run_markdown_epoch()

    day_31 = fetch_item(item_id)
    assert day_31["markdown_sequence"] == 2, (
        f"Expected the second step to hold on day 31, "
        f"got {day_31['markdown_sequence']}"
    )
    assert day_31["current_price_cents"] == 107_369, (
        f"Expected 107369 to hold on day 31, got {day_31['current_price_cents']}"
    )
    assert day_31["version"] == at_boundary["version"], (
        f"Expected version {at_boundary['version']} unchanged on day 31, "
        f"got {day_31['version']}"
    )
    assert day_31["list_price_cents"] == 126_317, (
        f"Expected the ticket price to stay 126317, "
        f"got {day_31['list_price_cents']}"
    )

    entries = fetch_consignor_ledger(world["consignor"]["id"])
    assert [e["amount_cents"] for e in entries] == [-27_000], (
        f"Expected only the collection surcharge, got "
        f"{[e['amount_cents'] for e in entries]}"
    )

    zone = fetch_zone(zone_id)
    assert zone["occupied_sqft"] == 24, (
        f"Expected the marked-down sofa to keep its 24 square feet, "
        f"got {zone['occupied_sqft']}"
    )


def _three_pieces_counted_in_the_front_showroom():
    """Sofa, sideboard and nightstand placed in one zone, ready to be counted."""
    world = setup_consignor_with_active_agreement(
        consignor_overrides={"payout_method": "ACH"}
    )
    agreement_id = world["agreement"]["id"]

    sofa = create_item(agreement_id, **CHESTERFIELD)
    sideboard = create_item(agreement_id, **SIDEBOARD)
    nightstand = create_item(agreement_id, **NIGHTSTAND)
    screen_item(sofa["id"], scores=SCORES_GRADE_B)
    screen_item(sideboard["id"], scores=SCORES_GRADE_A)
    screen_item(nightstand["id"], scores=SCORES_GRADE_A)

    take_custody(
        world["consignor"]["id"],
        [sofa["id"], sideboard["id"], nightstand["id"]],
        window_end="2026-08-01T12:00:00Z",
    )
    receive_item(sofa["id"], scores=SCORES_GRADE_B)
    receive_item(sideboard["id"], scores=SCORES_GRADE_A)
    receive_item(nightstand["id"], scores=SCORES_GRADE_A)

    world["zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    zone_id = world["zone"]["id"]
    world["sofa"] = place_item(sofa["id"], zone_id, tag_code="T-1001")
    world["sideboard"] = place_item(sideboard["id"], zone_id, tag_code="T-1002")
    world["nightstand"] = place_item(nightstand["id"], zone_id, tag_code="T-1003")
    return world


def test_a_count_that_finds_everything_reconciles_itself_and_books_nothing():
    """Zero variance closes the audit on the spot with no approval and no money.

    PRD 3.9: "When `variance_count` is 0, the audit is `RECONCILED` at the moment of
    creation: `write_off_total_cents` is 0, `approved_by_user_id` stays null because
    nobody needed to approve anything, and no ledger entry is minted."

    PRD 3.9: "`expected_item_count` is the number of pieces whose `placement_zone_id`
    names the counted zone and whose `inventory_state` is either `IN_CUSTODY` or
    `SHRINKAGE_MISSING`."

    PRD 3.9: "`counted_item_count` is the number of distinct entries in
    `counted_item_ids` that belong to that expected set."

    Design: Difficulty/boundary_precision_check/zero_variance_audit_reconciles_without_minting_any_ledger_entry
    """
    world = _three_pieces_counted_in_the_front_showroom()
    zone_id = world["zone"]["id"]

    audit = submit_shrinkage_audit(
        zone_id,
        [world["sofa"]["id"], world["sideboard"]["id"], world["nightstand"]["id"]],
    )

    assert audit["expected_item_count"] == 3, (
        f"Expected three pieces on the books, got {audit['expected_item_count']}"
    )
    assert audit["counted_item_count"] == 3, (
        f"Expected three pieces found, got {audit['counted_item_count']}"
    )
    assert audit["variance_count"] == 0, (
        f"Expected no variance, got {audit['variance_count']}"
    )
    assert audit["missing_item_ids"] == [], (
        f"Expected nothing missing, got {audit['missing_item_ids']}"
    )
    assert audit["status"] == "RECONCILED", (
        f"Expected RECONCILED at creation, got {audit['status']}"
    )
    assert audit["write_off_total_cents"] == 0, (
        f"Expected 0 written off, got {audit['write_off_total_cents']}"
    )
    assert audit["approved_by_user_id"] is None, (
        f"Expected no approver, got {audit['approved_by_user_id']}"
    )
    assert audit["counted_by_user_id"] == FLOOR_OPERATOR_ID, (
        f"Expected the counting operator recorded, "
        f"got {audit['counted_by_user_id']}"
    )

    entries = fetch_consignor_ledger(world["consignor"]["id"])
    assert [e["amount_cents"] for e in entries] == [-42_500], (
        f"Expected only the collection surcharge, got "
        f"{[e['amount_cents'] for e in entries]}"
    )

    for name in ("sofa", "sideboard", "nightstand"):
        piece = fetch_item(world[name]["id"])
        assert piece["inventory_state"] == "IN_CUSTODY", (
            f"Expected the {name} to stay IN_CUSTODY, "
            f"got {piece['inventory_state']}"
        )

    zone = fetch_zone(zone_id)
    assert zone["occupied_sqft"] == 54, (
        f"Expected 24 + 18 + 12 square feet, got {zone['occupied_sqft']}"
    )


def test_one_missing_piece_opens_a_counted_audit_and_still_books_nothing():
    """A variance of one waits for a manager and leaves the earlier count alone.

    PRD 3.9: "When `variance_count` is greater than 0, the audit opens in `status`
    `COUNTED` and waits for a manager."

    PRD 3.9: "Every expected piece absent from the count is immediately moved to
    `inventory_state` `SHRINKAGE_MISSING` with its `lifecycle_state` untouched."

    PRD 3.9: "A zone carries at most one non-terminal audit, so submitting a fresh
    count on a zone that already has an unreconciled one moves the older audit
    `COUNTED → ABANDONED`"

    Design: Difficulty/boundary_precision_check/zero_variance_audit_reconciles_without_minting_any_ledger_entry
    """
    world = _three_pieces_counted_in_the_front_showroom()
    zone_id = world["zone"]["id"]
    nightstand_id = world["nightstand"]["id"]

    first = submit_shrinkage_audit(
        zone_id,
        [world["sofa"]["id"], world["sideboard"]["id"], nightstand_id],
    )
    second = submit_shrinkage_audit(
        zone_id, [world["sofa"]["id"], world["sideboard"]["id"]]
    )

    assert second["variance_count"] == 1, (
        f"Expected a variance of one, got {second['variance_count']}"
    )
    assert second["status"] == "COUNTED", (
        f"Expected COUNTED while a manager is awaited, got {second['status']}"
    )
    assert second["missing_item_ids"] == [nightstand_id], (
        f"Expected the nightstand alone to be missing, "
        f"got {second['missing_item_ids']}"
    )
    assert second["write_off_total_cents"] == 0, (
        f"Expected nothing written off before approval, "
        f"got {second['write_off_total_cents']}"
    )
    assert second["approved_by_user_id"] is None, (
        f"Expected no approver yet, got {second['approved_by_user_id']}"
    )

    nightstand = fetch_item(nightstand_id)
    assert nightstand["inventory_state"] == "SHRINKAGE_MISSING", (
        f"Expected SHRINKAGE_MISSING, got {nightstand['inventory_state']}"
    )
    assert nightstand["lifecycle_state"] == "ON_FLOOR", (
        f"Expected the merchandising state untouched, "
        f"got {nightstand['lifecycle_state']}"
    )

    entries = fetch_consignor_ledger(world["consignor"]["id"])
    assert [e["amount_cents"] for e in entries] == [-42_500], (
        f"Expected the count to book nothing, got "
        f"{[e['amount_cents'] for e in entries]}"
    )

    zone = fetch_zone(zone_id)
    assert zone["occupied_sqft"] == 54, (
        f"Expected the mislaid nightstand to keep occupying its footage, "
        f"got {zone['occupied_sqft']}"
    )

    history = get_success_data(
        api_client.list_zone_shrinkage_audits(
            zone_id, GALLERY_MANAGER, params={"limit": 100}
        )
    )
    reread = {row["id"]: row for row in history}
    assert reread[first["id"]]["status"] == "RECONCILED", (
        f"Expected the reconciled count to survive the new one, "
        f"got {reread[first['id']]['status']}"
    )
    assert reread[second["id"]]["status"] == "COUNTED", (
        f"Expected the new count still open, got {reread[second['id']]['status']}"
    )
