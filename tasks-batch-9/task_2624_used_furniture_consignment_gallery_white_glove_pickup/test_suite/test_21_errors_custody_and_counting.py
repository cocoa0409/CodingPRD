"""What the truck will not carry, and what a count will not accept twice."""

from test_helpers import (
    FLOOR_OPERATOR,
    GALLERY_MANAGER,
    LOGISTICS_COORDINATOR,
    SCORES_GRADE_A,
    ApiErrorId,
    api_client,
    approve_audit_write_off,
    attach_item_payload,
    create_item,
    create_truck,
    create_zone,
    fetch_consignor,
    fetch_item,
    fetch_item_ledger,
    fetch_pickup_job,
    fetch_zone,
    get_success_data,
    place_item,
    receive_item,
    schedule_pickup,
    screen_item,
    setup_consignor_with_active_agreement,
    shrinkage_audit_payload,
    submit_shrinkage_audit,
    take_custody,
    total_count,
    validate_error,
)

ONE_STEP = [(1, 0, 0.00, 0)]

SMALL_BUREAU = {
    "title": "Bureau",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 5,
    "volume_cuft": 12,
    "footprint_sqft": 10,
}
TALL_ARMOIRE = {
    "title": "Armoire",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 5,
    "volume_cuft": 15,
    "footprint_sqft": 10,
}
COUNTED_BUREAU = {
    "title": "Bureau",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 5,
    "volume_cuft": 12,
    "footprint_sqft": 10,
}
MISSING_CREDENZA = {
    "title": "Credenza",
    "category": "CASEGOOD",
    "declared_value_cents": 80_000,
    "photo_count": 5,
    "volume_cuft": 20,
    "footprint_sqft": 10,
}


def test_attaching_a_piece_that_overflows_the_truck_is_refused():
    """Neither piece alone fills the box; together they do not fit.

    PRD 3.4: "The truck must also have room: if the job's recomputed `total_volume_cuft`
    including the piece being attached would exceed the truck's `capacity_volume_cuft`, the
    attach is refused with `ERR_TRUCK_CAPACITY_EXCEEDED`."

    PRD 3.4: "On success the piece moves `SCREEN_ACCEPTED → SCHEDULED_PICKUP`, the job's
    `item_count` and `total_volume_cuft` are recomputed, the quoted variant rewrites
    `quoted_surcharge_cents` against the enlarged load, and the job's `version` increments
    by 1."

    Design: Corner/errors/attaching_a_piece_that_overflows_the_truck_is_refused
    """
    world = setup_consignor_with_active_agreement(
        schedule_steps=ONE_STEP,
        consignor_overrides={"floor_number": 1, "has_elevator": False},
    )
    agreement_id = world["agreement"]["id"]

    bureau = create_item(agreement_id, **SMALL_BUREAU)
    armoire = create_item(agreement_id, **TALL_ARMOIRE)
    screen_item(bureau["id"], scores=SCORES_GRADE_A)
    screen_item(armoire["id"], scores=SCORES_GRADE_A)

    truck = create_truck(name="SMALL-1", capacity_volume_cuft=20)
    job = schedule_pickup(world["consignor"]["id"], truck["id"], [bureau["id"]])
    assert job["total_volume_cuft"] == 12, (
        f"Expected the bureau alone aboard, got {job['total_volume_cuft']}"
    )
    assert job["quoted_surcharge_cents"] == 17_000, (
        f"Expected 12000 plus two volume blocks, "
        f"got {job['quoted_surcharge_cents']}"
    )

    overflow = api_client.attach_pickup_item(
        job["id"], attach_item_payload(armoire["id"]), LOGISTICS_COORDINATOR
    )
    validate_error(overflow, ApiErrorId.ERR_TRUCK_CAPACITY_EXCEEDED, 409)

    after = fetch_pickup_job(job["id"])
    assert after["item_count"] == 1, (
        f"Expected one piece still aboard, got {after['item_count']}"
    )
    assert after["total_volume_cuft"] == 12, (
        f"Expected twelve cubic feet, got {after['total_volume_cuft']}"
    )
    assert after["quoted_surcharge_cents"] == 17_000, (
        f"Expected the quote unchanged by the refusal, "
        f"got {after['quoted_surcharge_cents']}"
    )
    assert after["version"] == job["version"], (
        f"Expected version {job['version']} unmoved, got {after['version']}"
    )

    left_behind = fetch_item(armoire["id"])
    assert left_behind["lifecycle_state"] == "SCREEN_ACCEPTED", (
        f"Expected the armoire still merely accepted, "
        f"got {left_behind['lifecycle_state']}"
    )
    assert left_behind["pickup_job_id"] is None, (
        f"Expected it on no job, got {left_behind['pickup_job_id']}"
    )


def _two_pieces_placed_in_the_front_showroom():
    """A bureau at 51,000 and a credenza at 68,000, both on the same twenty square feet."""
    world = setup_consignor_with_active_agreement(
        schedule_steps=ONE_STEP,
        consignor_overrides={"floor_number": 1, "has_elevator": False},
    )
    agreement_id = world["agreement"]["id"]

    bureau = create_item(agreement_id, **COUNTED_BUREAU)
    credenza = create_item(agreement_id, **MISSING_CREDENZA)
    screen_item(bureau["id"], scores=SCORES_GRADE_A)
    screen_item(credenza["id"], scores=SCORES_GRADE_A)

    take_custody(world["consignor"]["id"], [bureau["id"], credenza["id"]])
    receive_item(bureau["id"], scores=SCORES_GRADE_A)
    receive_item(credenza["id"], scores=SCORES_GRADE_A)

    world["zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    world["bureau"] = place_item(bureau["id"], world["zone"]["id"], tag_code="SHOWROOM-1")
    world["credenza"] = place_item(
        credenza["id"], world["zone"]["id"], tag_code="SHOWROOM-2"
    )
    return world


def test_counting_the_same_piece_twice_in_one_audit_is_refused():
    """A count is a set of pieces found, so naming one of them twice mints nothing.

    PRD 3.9: "`counted_item_ids` must contain no duplicates and every id in it must be a
    stored piece currently placed in the zone being counted, otherwise
    `ERR_AUDIT_COUNT_INVALID`; an id naming no stored piece at all is instead answered by
    `ERR_ITEM_NOT_FOUND` at the body-existence stage."

    PRD 2.9: "`counted_item_ids` contains no duplicates and every id in it is currently
    placed in the zone being counted, on shrinkage-audit submission — otherwise
    `ERR_AUDIT_COUNT_INVALID` (422)."

    Design: Corner/errors/counting_the_same_piece_twice_in_one_audit_is_refused
    """
    world = _two_pieces_placed_in_the_front_showroom()
    zone_id = world["zone"]["id"]
    bureau_id = world["bureau"]["id"]
    credenza_id = world["credenza"]["id"]

    doubled = api_client.create_shrinkage_audit(
        shrinkage_audit_payload(zone_id, [bureau_id, bureau_id]), FLOOR_OPERATOR
    )
    validate_error(doubled, ApiErrorId.ERR_AUDIT_COUNT_INVALID, 422)

    history = api_client.list_zone_shrinkage_audits(
        zone_id, GALLERY_MANAGER, params={"limit": 100}
    )
    assert total_count(history) == 0, (
        f"Expected no audit minted, got {total_count(history)}"
    )

    uncounted = fetch_item(credenza_id)
    assert uncounted["inventory_state"] == "IN_CUSTODY", (
        f"Expected the credenza untouched by the refusal, "
        f"got {uncounted['inventory_state']}"
    )

    honest = submit_shrinkage_audit(zone_id, [bureau_id, credenza_id])
    assert honest["expected_item_count"] == 2, (
        f"Expected two pieces expected, got {honest['expected_item_count']}"
    )
    assert honest["counted_item_count"] == 2, (
        f"Expected two pieces counted, got {honest['counted_item_count']}"
    )
    assert honest["variance_count"] == 0, (
        f"Expected no variance, got {honest['variance_count']}"
    )
    assert honest["write_off_total_cents"] == 0, (
        f"Expected nothing written off, got {honest['write_off_total_cents']}"
    )
    assert honest["status"] == "RECONCILED", (
        f"Expected a clean count to settle at once, got {honest['status']}"
    )


def test_approving_write_offs_on_an_already_reconciled_audit_is_refused():
    """The batch is not idempotent, and the lost piece is credited exactly once.

    PRD 3.9: "The audit must be in `status` `COUNTED`, otherwise `ERR_AUDIT_STATE_INVALID`
    — but the segregation check runs first, so the very operator recorded as
    `counted_by_user_id` receives `ERR_SEGREGATION_OF_DUTIES` even when the audit has
    already been reconciled."

    PRD 3.9: "The batch is walked in `missing_item_ids` order — the pieces' `created_at`
    ascending — and each piece produces its **own** `SHRINKAGE_CREDIT` ledger entry of that
    positive per-piece amount; a single merged entry for the batch is never minted."

    PRD 3.9: "The audit's `status` becomes `RECONCILED`, `approved_by_user_id` records the
    acting `X-User-ID`, its `version` increments by 1, and the zone's `occupied_sqft` and
    `utilization_state` are recomputed exactly **once** after the whole batch rather than
    once per piece."

    Design: Corner/errors/approving_write_offs_on_an_already_reconciled_audit_is_refused
    """
    world = _two_pieces_placed_in_the_front_showroom()
    zone_id = world["zone"]["id"]
    consignor_id = world["consignor"]["id"]
    credenza_id = world["credenza"]["id"]

    assert fetch_consignor(consignor_id)["unclaimed_balance_cents"] == -22_000, (
        "Expected the 22000 pickup surcharge alone on the account"
    )

    audit = submit_shrinkage_audit(zone_id, [world["bureau"]["id"]])
    assert audit["status"] == "COUNTED", (
        f"Expected a variance to wait for a manager, got {audit['status']}"
    )
    assert audit["variance_count"] == 1, (
        f"Expected one piece unaccounted for, got {audit['variance_count']}"
    )

    reconciled = approve_audit_write_off(audit["id"], GALLERY_MANAGER)
    assert reconciled["status"] == "RECONCILED", (
        f"Expected RECONCILED, got {reconciled['status']}"
    )
    assert reconciled["write_off_total_cents"] == 40_800, (
        f"Expected 68000 at sixty hundredths, "
        f"got {reconciled['write_off_total_cents']}"
    )

    again = api_client.approve_write_off(audit["id"], GALLERY_MANAGER)
    validate_error(again, ApiErrorId.ERR_AUDIT_STATE_INVALID, 409)

    history = get_success_data(
        api_client.list_zone_shrinkage_audits(
            zone_id, GALLERY_MANAGER, params={"limit": 100}
        )
    )
    assert len(history) == 1, (
        f"Expected the one audit, got {len(history)}"
    )
    assert history[0]["status"] == "RECONCILED", (
        f"Expected RECONCILED still, got {history[0]['status']}"
    )
    assert history[0]["variance_count"] == 1, (
        f"Expected one variance, got {history[0]['variance_count']}"
    )
    assert history[0]["write_off_total_cents"] == 40_800, (
        f"Expected 40800, got {history[0]['write_off_total_cents']}"
    )

    entries = fetch_item_ledger(credenza_id)
    assert len(entries) == 1, (
        f"Expected exactly one credit against the lost piece, "
        f"got {[e['entry_type'] for e in entries]}"
    )
    assert entries[0]["entry_type"] == "SHRINKAGE_CREDIT", (
        f"Expected a SHRINKAGE_CREDIT, got {entries[0]['entry_type']}"
    )
    assert entries[0]["amount_cents"] == 40_800, (
        f"Expected 40800, got {entries[0]['amount_cents']}"
    )

    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == 18_800, (
        f"Expected 40800 against the 22000 surcharge, "
        f"got {consignor['unclaimed_balance_cents']}"
    )

    zone = fetch_zone(zone_id)
    assert zone["occupied_sqft"] == 10, (
        f"Expected the ten square feet released once only, "
        f"got {zone['occupied_sqft']}"
    )
