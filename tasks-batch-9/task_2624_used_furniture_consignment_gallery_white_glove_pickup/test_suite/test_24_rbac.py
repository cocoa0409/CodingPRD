"""Which badge opens which door, and which badge is barred by its own signature."""

from test_helpers import (
    FLOOR_OPERATOR,
    FLOOR_OPERATOR_2_ID,
    GALLERY_MANAGER,
    GALLERY_MANAGER_ID,
    INTAKE_APPRAISER,
    LOGISTICS_COORDINATOR,
    LOGISTICS_COORDINATOR_2,
    LOGISTICS_COORDINATOR_2_ID,
    NON_EXISTENT_UUID,
    SCORES_GRADE_A,
    SCORES_GRADE_B,
    ApiErrorId,
    adjudicate_payload,
    api_client,
    create_buyer,
    create_crew,
    create_item,
    create_zone,
    fetch_consignor,
    fetch_damage_claim,
    fetch_item,
    fetch_item_ledger,
    fetch_sale,
    fetch_zone,
    file_damage_claim,
    get_success_data,
    make_headers,
    place_item,
    place_payload,
    receive_item,
    receive_payload,
    screen_item,
    screen_payload,
    sell_item,
    setup_consignor_with_active_agreement,
    submit_shrinkage_audit,
    take_custody,
    total_count,
    validate_error,
    validate_success,
)

ONE_STEP = [(1, 0, 0.00, 0)]

BUREAU = {
    "title": "Bureau",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 5,
    "volume_cuft": 12,
    "footprint_sqft": 10,
}
CREDENZA = {
    "title": "Credenza",
    "category": "CASEGOOD",
    "declared_value_cents": 80_000,
    "photo_count": 5,
    "volume_cuft": 20,
    "footprint_sqft": 10,
}


def test_an_intake_appraiser_cannot_place_a_piece_on_the_floor():
    """The badge is read before the shelf is searched, on an id that is not there.

    PRD 2.1: "If the headers are well formed but the presented role does not appear in the
    authorized-role list for the target endpoint given in §4, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD 2.1: "runs the physical floor: receiving inspection, placement and tagging,
    missing/recovered spot checks, releases out of the building, shrinkage counts and
    register sales."

    PRD 2.9: "Every `{id}` segment addressed in the URL resolves to a stored row, on every
    path-addressed endpoint."

    Design: Corner/rbac/an_intake_appraiser_cannot_place_a_piece_on_the_floor
    """
    body = place_payload(NON_EXISTENT_UUID, tag_code="FRONT-0001")

    refused = api_client.place_item(NON_EXISTENT_UUID, body, INTAKE_APPRAISER)
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, 403)

    allowed_role = api_client.place_item(NON_EXISTENT_UUID, body, FLOOR_OPERATOR)
    validate_error(allowed_role, ApiErrorId.ERR_ITEM_NOT_FOUND, 404)

    listed = api_client.list_items(GALLERY_MANAGER, params={"limit": 100})
    assert total_count(listed) == 0, (
        f"Expected an empty gallery throughout, got {total_count(listed)}"
    )


def test_the_floor_operator_alone_performs_receiving_and_placement():
    """One badge carries the inspection, the tag, the listing clock and the square feet.

    PRD 2.1: "runs the physical floor: receiving inspection, placement and tagging,
    missing/recovered spot checks, releases out of the building, shrinkage counts and
    register sales."

    PRD 3.5: "`current_price_cents` is refreshed from the recomputed ticket price,
    `received_by_user_id` records the acting `X-User-ID`, and the piece's `version`
    increments by 1."

    PRD 3.6: "On success the piece moves `AWAITING_PLACEMENT → ON_FLOOR`, its
    `placement_zone_id` and `tag_code` are written, and its `version` increments by 1."

    PRD 3.6: "on a first placement `days_on_floor` is 0, so the step in force is the
    sequence-1 step sitting at day offset 0, `markdown_sequence` becomes 1, and
    `current_price_cents` becomes `list_price_cents` reduced by that step's `markdown_pct`
    and then raised to that step's `min_price_cents` if the reduction landed below it."

    Design: Corner/rbac/the_floor_operator_alone_performs_receiving_and_placement
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    bureau = create_item(world["agreement"]["id"], **BUREAU)
    screen_item(bureau["id"], scores=SCORES_GRADE_A)
    take_custody(world["consignor"]["id"], [bureau["id"]])
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)

    inspected = api_client.receive_item(
        bureau["id"], receive_payload(SCORES_GRADE_A), FLOOR_OPERATOR
    )
    validate_success(inspected, 200)

    placed = api_client.place_item(
        bureau["id"], place_payload(zone["id"], tag_code="SHOWROOM-1"), FLOOR_OPERATOR
    )
    validate_success(placed, 200)

    piece = fetch_item(bureau["id"])
    assert piece["lifecycle_state"] == "ON_FLOOR", (
        f"Expected ON_FLOOR, got {piece['lifecycle_state']}"
    )
    assert piece["inventory_state"] == "IN_CUSTODY", (
        f"Expected IN_CUSTODY, got {piece['inventory_state']}"
    )
    assert piece["condition_grade"] == "A", (
        f"Expected A confirmed in the hand, got {piece['condition_grade']}"
    )
    assert piece["list_price_cents"] == 51_000, (
        f"Expected 60000 at eighty-five hundredths, got {piece['list_price_cents']}"
    )
    assert piece["current_price_cents"] == 51_000, (
        f"Expected the opening step to take nothing off, "
        f"got {piece['current_price_cents']}"
    )
    assert piece["markdown_sequence"] == 1, (
        f"Expected the sequence-1 step in force, got {piece['markdown_sequence']}"
    )
    assert piece["tag_code"] == "SHOWROOM-1", (
        f"Expected the printed tag, got {piece['tag_code']}"
    )
    assert piece["listed_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected the tenure clock started from the current instant, "
        f"got {piece['listed_at']}"
    )
    assert piece["received_by_user_id"] == "floor-1", (
        f"Expected the inspecting operator recorded, "
        f"got {piece['received_by_user_id']}"
    )

    front = fetch_zone(zone["id"])
    assert front["occupied_sqft"] == 10, (
        f"Expected the bureau's ten square feet charged, got {front['occupied_sqft']}"
    )
    assert front["utilization_state"] == "NORMAL", (
        f"Expected NORMAL at 10 of 200, got {front['utilization_state']}"
    )


SHARED_STAFF_ID = "staff-7"


def test_the_screening_appraiser_cannot_perform_the_receiving_inspection():
    """The bar is keyed on the person, not the badge: the same body succeeds for another.

    PRD 2.8: "The three barred pairings are: the `FloorOperator` recorded as
    `ShrinkageAudit.counted_by_user_id` may not be the `GalleryManager` `X-User-ID` that
    approves that audit's write-offs; the `LogisticsCoordinator` recorded as
    `DeliveryOrder.scheduled_by_user_id` may not be the `X-User-ID` that adjudicates a
    damage claim filed against that delivery order; and the `IntakeAppraiser` recorded as
    `ConsignmentItem.screened_by_user_id` may not be the `X-User-ID` that performs that
    item's receiving inspection."

    PRD 3.5: "The operator performing the inspection may not be the appraiser who screened
    the piece: when `X-User-ID` equals the piece's `screened_by_user_id`, the inspection is
    refused with `ERR_SEGREGATION_OF_DUTIES` before any state is even examined."

    PRD 3.5: "A distance of at most one grade — including no downgrade at all, and including
    an upgrade — moves the piece `RECEIVED → AWAITING_PLACEMENT` and the gallery simply
    absorbs the difference."

    Design: Corner/rbac/the_screening_appraiser_cannot_perform_the_receiving_inspection
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    bureau = create_item(world["agreement"]["id"], **BUREAU)
    screened = get_success_data(
        api_client.screen_item(
            bureau["id"],
            screen_payload(scores=SCORES_GRADE_A),
            make_headers(SHARED_STAFF_ID, "IntakeAppraiser"),
        )
    )
    assert screened["screened_by_user_id"] == SHARED_STAFF_ID, (
        f"Expected the screening appraiser recorded, "
        f"got {screened['screened_by_user_id']}"
    )
    take_custody(world["consignor"]["id"], [bureau["id"]])

    inspection = receive_payload(SCORES_GRADE_B)
    refused = api_client.receive_item(
        bureau["id"], inspection, make_headers(SHARED_STAFF_ID, "FloorOperator")
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    untouched = fetch_item(bureau["id"])
    assert untouched["lifecycle_state"] == "RECEIVED", (
        f"Expected the piece still awaiting inspection, "
        f"got {untouched['lifecycle_state']}"
    )
    assert untouched["condition_grade"] == "A", (
        f"Expected the screening grade intact, got {untouched['condition_grade']}"
    )
    assert untouched["list_price_cents"] == 51_000, (
        f"Expected the screening price intact, got {untouched['list_price_cents']}"
    )
    assert untouched["received_by_user_id"] is None, (
        f"Expected no inspector recorded, got {untouched['received_by_user_id']}"
    )

    accepted = api_client.receive_item(bureau["id"], inspection, FLOOR_OPERATOR)
    validate_success(accepted, 200)
    inspected = fetch_item(bureau["id"])
    assert inspected["lifecycle_state"] == "AWAITING_PLACEMENT", (
        f"Expected a one-grade slip absorbed, got {inspected['lifecycle_state']}"
    )
    assert inspected["photo_score"] == 6.60, (
        f"Expected 6.60 from the hands-on scores, got {inspected['photo_score']}"
    )
    assert inspected["condition_grade"] == "B", (
        f"Expected B in the hand, got {inspected['condition_grade']}"
    )
    assert inspected["list_price_cents"] == 42_000, (
        f"Expected 60000 at seventy hundredths, got {inspected['list_price_cents']}"
    )
    assert inspected["provisional_condition_grade"] == "A", (
        f"Expected the photographs' promise frozen at A, "
        f"got {inspected['provisional_condition_grade']}"
    )


def _a_bureau_and_a_credenza_on_the_same_twenty_square_feet():
    """Two casegoods above the clearance threshold, both placed in Front A."""
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    agreement_id = world["agreement"]["id"]
    bureau = create_item(agreement_id, **BUREAU)
    credenza = create_item(agreement_id, **CREDENZA)
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


def test_the_counting_operator_cannot_approve_its_own_write_offs():
    """Holding the manager's badge does not excuse the hand that wrote the count.

    PRD 2.8: "The rule is checked **before any resource state is inspected**, which means a
    stale or already-finished resource still answers with the segregation error rather than
    a state error."

    PRD 3.9: "The audit must be in `status` `COUNTED`, otherwise `ERR_AUDIT_STATE_INVALID` —
    but the segregation check runs first, so the very operator recorded as
    `counted_by_user_id` receives `ERR_SEGREGATION_OF_DUTIES` even when the audit has
    already been reconciled."

    PRD 3.9: "The credit for one piece is that piece's `current_price_cents` multiplied by
    60 hundredths and rounded half up to a whole number of cents; the gallery does not make
    a consignor whole for a lost piece, it settles at a fraction of the marked price."

    Design: Corner/rbac/the_counting_operator_cannot_approve_its_own_write_offs
    """
    world = _a_bureau_and_a_credenza_on_the_same_twenty_square_feet()
    zone_id = world["zone"]["id"]
    consignor_id = world["consignor"]["id"]
    credenza_id = world["credenza"]["id"]

    counter = make_headers(FLOOR_OPERATOR_2_ID, "FloorOperator")
    audit = submit_shrinkage_audit(zone_id, [world["bureau"]["id"]], headers=counter)
    assert audit["counted_by_user_id"] == FLOOR_OPERATOR_2_ID, (
        f"Expected the counting operator recorded, got {audit['counted_by_user_id']}"
    )
    assert audit["status"] == "COUNTED", (
        f"Expected COUNTED with something missing, got {audit['status']}"
    )
    assert audit["variance_count"] == 1, (
        f"Expected one piece unaccounted for, got {audit['variance_count']}"
    )

    refused = api_client.approve_write_off(
        audit["id"], make_headers(FLOOR_OPERATOR_2_ID, "GalleryManager")
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    history = get_success_data(
        api_client.list_zone_shrinkage_audits(
            zone_id, GALLERY_MANAGER, params={"limit": 100}
        )
    )
    assert history[0]["status"] == "COUNTED", (
        f"Expected the count still awaiting a second pair of eyes, "
        f"got {history[0]['status']}"
    )
    assert history[0]["write_off_total_cents"] == 0, (
        f"Expected nothing written off, got {history[0]['write_off_total_cents']}"
    )
    assert history[0]["approved_by_user_id"] is None, (
        f"Expected no approver recorded, got {history[0]['approved_by_user_id']}"
    )

    mislaid = fetch_item(credenza_id)
    assert mislaid["inventory_state"] == "SHRINKAGE_MISSING", (
        f"Expected the credenza still merely missing, got {mislaid['inventory_state']}"
    )
    assert mislaid["lifecycle_state"] == "ON_FLOOR", (
        f"Expected the merchandising story untouched, got {mislaid['lifecycle_state']}"
    )
    assert fetch_item_ledger(credenza_id) == [], (
        f"Expected no credit paid, got {fetch_item_ledger(credenza_id)}"
    )
    assert fetch_consignor(consignor_id)["unclaimed_balance_cents"] == -22_000, (
        f"Expected the surcharge alone, "
        f"got {fetch_consignor(consignor_id)['unclaimed_balance_cents']}"
    )

    approved = api_client.approve_write_off(audit["id"], GALLERY_MANAGER)
    validate_success(approved, 200)
    settled = get_success_data(approved)
    assert settled["status"] == "RECONCILED", (
        f"Expected RECONCILED once a different manager signs, got {settled['status']}"
    )
    assert settled["write_off_total_cents"] == 40_800, (
        f"Expected 68000 at sixty hundredths, got {settled['write_off_total_cents']}"
    )
    assert settled["approved_by_user_id"] == GALLERY_MANAGER_ID, (
        f"Expected the approving manager recorded, "
        f"got {settled['approved_by_user_id']}"
    )


def test_the_scheduling_coordinator_cannot_adjudicate_that_orders_claim():
    """The bar follows the delivery order across the aggregate and across a change of badge.

    PRD 3.8: "**Adjudication** is a `GalleryManager` decision carrying an `approve` boolean
    and a `fault_party` that must be one of `GALLERY`, `CONSIGNOR`, `BUYER` or
    `UNDETERMINED`. The claim must be in `SUBMITTED`, the `claim_amount_cents` must not
    exceed the parent sale's `sale_price_cents`, and the acting `X-User-ID` must not equal
    the `scheduled_by_user_id` of the delivery order the claim is filed against — the
    coordinator who booked the delivery does not get to rule on whether it went badly."

    PRD 2.1: "the server records it as `scheduled_by_user_id` on both the `PickupJob` and the
    `DeliveryOrder` it creates, but never compares it to any entity's `id`."

    PRD 3.8: "When `approve` is true the claim moves `SUBMITTED → APPROVED` and the
    allocation runs."

    Design: Corner/rbac/the_scheduling_coordinator_cannot_adjudicate_that_orders_claim
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    bureau = create_item(world["agreement"]["id"], **BUREAU)
    screen_item(bureau["id"], scores=SCORES_GRADE_A)
    take_custody(world["consignor"]["id"], [bureau["id"]])
    receive_item(bureau["id"], scores=SCORES_GRADE_A)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    place_item(bureau["id"], zone["id"], tag_code="SHOWROOM-1")

    buyer = create_buyer(display_name="Nora Vance", floor_number=2, has_elevator=False)
    sale = sell_item(bureau["id"], buyer["id"], 51_000)
    crew = create_crew(name="WG-1", max_concurrent_jobs=2)

    order = get_success_data(
        api_client.create_delivery_order(
            {
                "sale_id": sale["id"],
                "crew_id": crew["id"],
                "window_start": "2026-08-01T13:00:00Z",
                "window_end": "2026-08-01T15:00:00Z",
            },
            LOGISTICS_COORDINATOR_2,
        )
    )
    assert order["scheduled_by_user_id"] == LOGISTICS_COORDINATOR_2_ID, (
        f"Expected the booking coordinator recorded, "
        f"got {order['scheduled_by_user_id']}"
    )
    validate_success(
        api_client.complete_delivery_order(
            order["id"], {"outcome": "DELIVERED"}, LOGISTICS_COORDINATOR
        ),
        200,
    )

    claim = file_damage_claim(order["id"], buyer["id"], 20_000)
    assert claim["status"] == "SUBMITTED", (
        f"Expected a claim squarely open for decision, got {claim['status']}"
    )

    ruling = adjudicate_payload(True, "GALLERY")
    refused = api_client.adjudicate_claim(
        claim["id"], ruling, make_headers(LOGISTICS_COORDINATOR_2_ID, "GalleryManager")
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    undecided = fetch_damage_claim(claim["id"])
    assert undecided["status"] == "SUBMITTED", (
        f"Expected the claim still undecided, got {undecided['status']}"
    )
    assert undecided["adjudicated_by_user_id"] is None, (
        f"Expected no adjudicator recorded, got {undecided['adjudicated_by_user_id']}"
    )
    assert fetch_sale(sale["id"])["refund_cents"] == 0, (
        f"Expected no refund booked, got {fetch_sale(sale['id'])['refund_cents']}"
    )
    assert fetch_consignor(world["consignor"]["id"])["unclaimed_balance_cents"] == 13_600, (
        f"Expected 30600 of credit against 17000 of surcharge, got "
        f"{fetch_consignor(world['consignor']['id'])['unclaimed_balance_cents']}"
    )

    decided = api_client.adjudicate_claim(claim["id"], ruling, GALLERY_MANAGER)
    validate_success(decided, 200)
    ruled = get_success_data(decided)
    assert ruled["status"] == "APPROVED", (
        f"Expected APPROVED from a manager who did not book the van, "
        f"got {ruled['status']}"
    )
    assert ruled["adjudicated_by_user_id"] == GALLERY_MANAGER_ID, (
        f"Expected the deciding manager recorded, "
        f"got {ruled['adjudicated_by_user_id']}"
    )
