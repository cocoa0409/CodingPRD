"""Inventory-lot lifecycle, SNS-cache vs mutual-aid allocation requests,
optimistic-concurrency version guards, the reserved/available conservation
invariant, and the priority_score calculation's pinned risk_tier read."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_activated_hazard_plan,
    create_pod,
    create_open_pod,
    close_pod,
    restrict_pod,
    get_pod_version,
    create_countermeasure,
    create_central_inventory_lot,
    create_pod_inventory_lot,
    get_lot_version,
    create_allocation_request,
    reserve_allocation_request,
    create_reserved_sns_allocation_request,
    create_reserved_mutual_aid_allocation_request,
    cancel_allocation_request,
    set_clock,
)


def test_inventory_lot_pod_id_null_means_central_cache(api, logistics_headers):
    """PRD §3.4: "`LogisticsCoordinator` receives physical stock by creating an
    `InventoryLot`: a `countermeasure_id`, an optional `pod_id` (omitted for a
    central SNS-cache lot, supplied for a POD-scoped lot), a `lot_number`, an
    `on_hand_quantity` (never negative), and an `expiration_date` that must be
    strictly later than the current logical clock time at the moment of
    creation..."
    PRD §2.9: "An `InventoryLot` with a null `pod_id` is the central SNS cache
    lot for its countermeasure; a lot with a non-null `pod_id` is scoped to
    that POD's own on-site stock."

    Design: Corner/entities/inventory_lot_pod_id_null_means_central_cache
    """
    cm = create_countermeasure(doses_required=1, unit_cost_cents=500, reorder_point_quantity=5)

    res = api.create_inventory_lot(
        {
            "countermeasure_id": cm["id"], "lot_number": "LOT-CACHE1",
            "on_hand_quantity": 1000, "expiration_date": "2027-01-01T00:00:00Z",
        },
        logistics_headers,
    )
    lot = validate_success(res, 201)
    assert lot["pod_id"] is None
    assert lot["available_quantity"] == 1000


def test_inventory_lot_invalid_expiration_in_past_rejected(api, logistics_headers):
    """PRD §3.4: "...and an `expiration_date` that must be strictly later than
    the current logical clock time at the moment of creation — a lot created
    with a quantity below zero or an expiration in the past or present is
    rejected with `ERR_INVALID_EXPIRATION`."

    Design: Corner/validations/inventory_lot_invalid_expiration_in_past_rejected
    """
    set_clock("2026-04-01T00:00:00Z")
    cm = create_countermeasure()

    res = api.create_inventory_lot(
        {
            "countermeasure_id": cm["id"], "lot_number": "LOT-EXPIRED1",
            "on_hand_quantity": 50, "expiration_date": "2026-01-01T00:00:00Z",
        },
        logistics_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_EXPIRATION)


def test_inventory_lots_filtered_list_by_pod_and_countermeasure(api, admin_headers, logistics_headers):
    """PRD §4 endpoint table: "List inventory lots, filtered by countermeasure
    and/or POD"

    Design: Corner/endpoints/inventory_lots_filtered_list_by_pod_and_countermeasure
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    create_central_inventory_lot(cm["id"], lot_number="LOT-CENTRAL")
    pod_lot = create_pod_inventory_lot(cm["id"], pod["id"], lot_number="LOT-POD")

    data, meta = validate_paginated(
        api.list_inventory_lots(
            logistics_headers, params={"pod_id": pod["id"], "countermeasure_id": cm["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == pod_lot["id"]


def test_allocation_request_invalid_source_configuration_rejected(api, admin_headers, logistics_headers):
    """PRD §3.5: "Two sourcing shapes are supported via `source_type`, which
    defaults to `SNS_CACHE`: when `source_type` is `SNS_CACHE`, `partner_pod_id`
    must be left null; when `source_type` is `MUTUAL_AID`, `partner_pod_id`
    must be supplied and must differ from `pod_id` — the lending POD or
    jurisdiction. Violating either pairing is rejected with
    `ERR_INVALID_SOURCE_CONFIGURATION`."

    Design: Corner/validations/allocation_request_invalid_source_configuration_rejected
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    other_pod = create_open_pod(hp["id"])
    cm = create_countermeasure()

    res = api.create_allocation_request(
        {
            "pod_id": pod["id"], "countermeasure_id": cm["id"], "source_type": "SNS_CACHE",
            "partner_pod_id": other_pod["id"], "requested_quantity": 10,
            "expected_pod_version": get_pod_version(pod["id"]),
        },
        logistics_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_SOURCE_CONFIGURATION)


def test_allocation_request_deny_from_wrong_state_rejected(api, logistics_headers):
    """PRD §2.6: "Only after both existence passes succeed does the system
    evaluate whether the target resource is in a state from which the
    requested trigger has a declared transition (`ERR_INVALID_STATE`, 409),
    followed by the endpoint's specific business-safety, business-temporal,
    business-referential, and business-constraint checks, each of which is
    scattered through §3 alongside the workflow it guards."
    PRD §3.5: "Denial, requiring only the state and role-match checks, moves
    the request straight to the terminal `DENIED` and likewise decrements
    `open_allocation_request_count`."

    Design: Corner/state_machines/allocation_request_deny_from_wrong_state_rejected
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    lot = create_central_inventory_lot(cm["id"], on_hand_quantity=50)
    reserved = create_reserved_sns_allocation_request(pod["id"], cm["id"], lot["id"], 10)

    res = api.deny_allocation_request(reserved["id"], logistics_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_allocation_request_reserve_blocked_by_hazard_plan_not_activated(api, admin_headers, logistics_headers):
    """PRD §3.1: "Activation is a prerequisite scattered throughout the rest of
    the system — opening a POD, and reserving or denying an allocation request
    against one of that plan's PODs, both require the owning `HazardPlan.status`
    to be `ACTIVATED` (rejected with `ERR_HAZARD_PLAN_NOT_ACTIVATED` when it is
    not)."

    Design: Corner/validations/allocation_request_reserve_blocked_by_hazard_plan_not_activated
    """
    # PRD §3.1 also gates AllocationRequest *creation* on an ACTIVATED plan, so
    # the reserve-time ACTIVATED check is only reachable by filing the request
    # while the plan is ACTIVATED, then standing the plan down (which requires
    # every child POD CLOSED) so it is no longer ACTIVATED at reserve time.
    hp = create_activated_hazard_plan(
        hazard_type="OUTBREAK_OTHER", title="Stood Down Plan",
        jurisdiction_code="CTY35", target_population=600,
    )
    assert hp["status"] == "ACTIVATED"

    pod = create_pod(
        hp["id"], site_name="Stood Down POD", site_type="FIXED_POD",
        address="37 Draft St", staffing_capacity_lanes=2, lane_throughput_rate_per_hour=10,
    )
    cm = create_countermeasure()
    lot = create_central_inventory_lot(cm["id"], on_hand_quantity=50)
    ar = create_allocation_request(pod["id"], cm["id"], requested_quantity=10)

    # Close the only child POD, then stand the plan down -> STOOD_DOWN (not ACTIVATED).
    close_pod(pod["id"])
    validate_success(api.stand_down_hazard_plan(hp["id"], admin_headers), 200)

    res = api.reserve_allocation_request(
        ar["id"], {"expected_inventory_lot_version": get_lot_version(lot["id"])}, logistics_headers
    )
    validate_error(res, ApiErrorId.ERR_HAZARD_PLAN_NOT_ACTIVATED)


def test_reserve_full_remaining_available_quantity_succeeds(api, admin_headers):
    """PRD §3.5: "...the resolved source lot — the central cache lot for
    `SNS_CACHE`, or the `partner_pod_id`'s own lot for `MUTUAL_AID`, in both
    cases matched on `countermeasure_id` — must have `available_quantity` at
    least equal to `requested_quantity` (`ERR_INSUFFICIENT_INVENTORY` if not,
    including the boundary case where the lot is already fully depleted)..."

    Design: Difficulty/boundary_precision_check/allocation_reserve_exact_zero_available_rejected
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    lot = create_central_inventory_lot(cm["id"], on_hand_quantity=100)

    reserved = create_reserved_sns_allocation_request(pod["id"], cm["id"], lot["id"], 100)
    assert reserved["status"] == "RESERVED"

    lot_after = validate_success(api.get_inventory_lot(lot["id"], admin_headers), 200)
    assert lot_after["available_quantity"] == 0, "reserving the full lot is a valid boundary, not rejected"


def test_reserve_after_available_quantity_reaches_zero_rejected(api, admin_headers, logistics_headers):
    """PRD §3.5: "...the resolved source lot — the central cache lot for
    `SNS_CACHE`, or the `partner_pod_id`'s own lot for `MUTUAL_AID`, in both
    cases matched on `countermeasure_id` — must have `available_quantity` at
    least equal to `requested_quantity` (`ERR_INSUFFICIENT_INVENTORY` if not,
    including the boundary case where the lot is already fully depleted)..."

    Design: Difficulty/boundary_precision_check/allocation_reserve_exact_zero_available_rejected
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    lot = create_central_inventory_lot(cm["id"], on_hand_quantity=100)
    create_reserved_sns_allocation_request(pod["id"], cm["id"], lot["id"], 100)

    lot_after = validate_success(api.get_inventory_lot(lot["id"], admin_headers), 200)
    assert lot_after["available_quantity"] == 0

    ar2 = create_allocation_request(pod["id"], cm["id"], requested_quantity=1)
    res = api.reserve_allocation_request(
        ar2["id"], {"expected_inventory_lot_version": lot_after["version"]}, logistics_headers
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)


def test_wrong_role_reserve_mutual_aid_returns_source_role_mismatch_not_insufficient_inventory(
    api, admin_headers, logistics_headers
):
    """PRD §3.5: "Reserving is checked in this order: the request must be
    `REQUESTED`; the owning hazard plan (resolved through `pod_id` → the
    POD's `hazard_plan_id`) must be `ACTIVATED`; the acting role must match
    `source_type` as just described; the resolved source lot — the central
    cache lot for `SNS_CACHE`, or the `partner_pod_id`'s own lot for
    `MUTUAL_AID`, in both cases matched on `countermeasure_id` — must have
    `available_quantity` at least equal to `requested_quantity`
    (`ERR_INSUFFICIENT_INVENTORY` if not, including the boundary case where
    the lot is already fully depleted); and finally, `expected_inventory_lot_version`
    in the payload must match that source lot's current `version`
    (`ERR_STALE_VERSION`, §2.8)."

    Design: Difficulty/priority_pair_validation_conflict/allocation_reserve_role_mismatch_beats_insufficient_inventory
    """
    hp = create_activated_hazard_plan()
    req_pod = create_open_pod(hp["id"])
    partner_pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    lot = create_pod_inventory_lot(cm["id"], partner_pod["id"], on_hand_quantity=10)
    ar = create_allocation_request(
        req_pod["id"], cm["id"], source_type="MUTUAL_AID",
        partner_pod_id=partner_pod["id"], requested_quantity=1000,
    )

    res = api.reserve_allocation_request(
        ar["id"], {"expected_inventory_lot_version": get_lot_version(lot["id"])}, logistics_headers
    )
    validate_error(res, ApiErrorId.ERR_SOURCE_ROLE_MISMATCH)


def test_correct_role_reserve_insufficient_inventory_returns_insufficient_inventory(
    api, admin_headers, partner_headers
):
    """PRD §3.5: "Reserving is checked in this order: the request must be
    `REQUESTED`; the owning hazard plan (resolved through `pod_id` → the
    POD's `hazard_plan_id`) must be `ACTIVATED`; the acting role must match
    `source_type` as just described; the resolved source lot — the central
    cache lot for `SNS_CACHE`, or the `partner_pod_id`'s own lot for
    `MUTUAL_AID`, in both cases matched on `countermeasure_id` — must have
    `available_quantity` at least equal to `requested_quantity`
    (`ERR_INSUFFICIENT_INVENTORY` if not, including the boundary case where
    the lot is already fully depleted); and finally, `expected_inventory_lot_version`
    in the payload must match that source lot's current `version`
    (`ERR_STALE_VERSION`, §2.8)."

    Design: Difficulty/priority_pair_validation_conflict/allocation_reserve_role_mismatch_beats_insufficient_inventory
    """
    hp = create_activated_hazard_plan()
    req_pod = create_open_pod(hp["id"])
    partner_pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    lot = create_pod_inventory_lot(cm["id"], partner_pod["id"], on_hand_quantity=10)
    ar = create_allocation_request(
        req_pod["id"], cm["id"], source_type="MUTUAL_AID",
        partner_pod_id=partner_pod["id"], requested_quantity=1000,
    )

    res = api.reserve_allocation_request(
        ar["id"], {"expected_inventory_lot_version": get_lot_version(lot["id"])}, partner_headers
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)


def test_allocation_request_create_stale_pod_version_rejected(api, admin_headers, logistics_headers):
    """PRD §2.8: "Creating an `AllocationRequest` (`POST /allocation-requests`)
    requires the request body to carry `expected_pod_version`, matching the
    target POD's current `version`. If another writer has advanced the POD's
    version — for instance, its operational posture or
    `open_allocation_request_count` changed — since the client last read it,
    the create is rejected with `ERR_STALE_VERSION` (HTTP 412)..."

    Design: Corner/complexity_layers/allocation_request_create_stale_pod_version_rejected
    """
    hp = create_activated_hazard_plan()
    pod = validate_success(
        api.create_pod(
            {
                "hazard_plan_id": hp["id"], "site_name": "Stale POD", "site_type": "FIXED_POD",
                "address": "41 Stale St", "staffing_capacity_lanes": 2, "lane_throughput_rate_per_hour": 10,
            },
            admin_headers,
        ),
        201,
    )
    pod_v_stale = pod["version"]
    validate_success(api.open_pod(pod["id"], admin_headers), 200)  # bumps POD.version
    cm = create_countermeasure()

    res = api.create_allocation_request(
        {
            "pod_id": pod["id"], "countermeasure_id": cm["id"], "source_type": "SNS_CACHE",
            "requested_quantity": 10, "expected_pod_version": pod_v_stale,
        },
        logistics_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


def test_allocation_request_reserve_stale_lot_version_rejected(api, admin_headers, logistics_headers):
    """PRD §2.8: "Reserving an `AllocationRequest`
    (`POST /allocation-requests/{id}/reserve`) requires the request body to
    carry `expected_inventory_lot_version`, matching the resolved source
    `InventoryLot`'s current `version`. If another writer has already reserved
    against, or cancelled a reservation against, that same lot since the
    client last observed it, the reserve is rejected with `ERR_STALE_VERSION`
    (HTTP 412)..."

    Design: Corner/complexity_layers/allocation_request_reserve_stale_lot_version_rejected
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    lot = create_central_inventory_lot(cm["id"], on_hand_quantity=100)
    lot_v_stale = lot["version"]

    ar1 = create_allocation_request(pod["id"], cm["id"], requested_quantity=10)
    reserve_allocation_request(ar1["id"], lot["id"], logistics_headers)  # bumps InventoryLot.version

    ar2 = create_allocation_request(pod["id"], cm["id"], requested_quantity=5)
    res = api.reserve_allocation_request(
        ar2["id"], {"expected_inventory_lot_version": lot_v_stale}, logistics_headers
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


def test_reserve_moves_quantity_from_available_to_reserved(api, admin_headers):
    """PRD §2.9: "`reserved_quantity` rises when an `AllocationRequest`
    reserves against the lot and falls when that reservation is cancelled or
    fulfilled." PRD §2.9: "Every lot's `available_quantity` is defined as
    `on_hand_quantity` minus `reserved_quantity`..."

    Design: Difficulty/compensating_invariant/allocation_reserve_then_cancel_restores_available_quantity
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    lot = create_central_inventory_lot(cm["id"], on_hand_quantity=200)

    create_reserved_sns_allocation_request(pod["id"], cm["id"], lot["id"], 50)

    lot_after = validate_success(api.get_inventory_lot(lot["id"], admin_headers), 200)
    assert lot_after["available_quantity"] == 150
    assert lot_after["reserved_quantity"] == 50


def test_cancel_reservation_restores_available_quantity(api, admin_headers, logistics_headers):
    """PRD §3.5: "Cancelling a `RESERVED` request, available to the same two
    roles that can reserve or deny, moves it to the terminal `CANCELLED` and
    releases the reservation by decreasing the source lot's
    `reserved_quantity` by `reserved_quantity` — restoring the invariant that
    `reserved_quantity` plus `available_quantity` equals `on_hand_quantity`."

    Design: Difficulty/compensating_invariant/allocation_reserve_then_cancel_restores_available_quantity
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    lot = create_central_inventory_lot(cm["id"], on_hand_quantity=200)

    reserved = create_reserved_sns_allocation_request(pod["id"], cm["id"], lot["id"], 50)
    cancel_allocation_request(reserved["id"], logistics_headers)

    lot_after = validate_success(api.get_inventory_lot(lot["id"], admin_headers), 200)
    assert lot_after["available_quantity"] == 200
    assert lot_after["reserved_quantity"] == 0


def test_allocation_priority_score_tie_break_by_created_at(api, admin_headers, logistics_headers):
    """PRD §3.5: "When a listing shows two requests with an equal
    `priority_score`, they are ordered by `created_at` ascending, never by
    `id`."

    Design: Corner/calculations/allocation_priority_score_tie_break_by_created_at
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    lot = create_central_inventory_lot(cm["id"], on_hand_quantity=1000)

    ar_a = create_reserved_sns_allocation_request(pod["id"], cm["id"], lot["id"], 100)
    ar_b_created = create_allocation_request(pod["id"], cm["id"], requested_quantity=100)
    reserve_allocation_request(ar_b_created["id"], lot["id"], logistics_headers)

    data, _ = validate_paginated(
        api.list_allocation_requests(admin_headers, params={"pod_id": pod["id"], "countermeasure_id": cm["id"]})
    )
    assert data[0]["priority_score"] == data[1]["priority_score"]
    assert data[0]["id"] == ar_a["id"], (
        "ar_a was created strictly before ar_b; tied priority_score orders by created_at ascending"
    )


def test_priority_score_reads_standard_risk_tier_at_reserve_time(api, admin_headers):
    """PRD §3.5: "`priority_score` is a weighted figure computed once, at
    reserve time, and never recalculated afterward. It is the sum of two
    terms, rounded to 2 decimal places: a quantity term equal to 0.01
    multiplied by the smaller of `requested_quantity` and a cap of 5,000
    doses, plus a risk-tier term drawn from the requesting POD's `risk_tier`
    at the moment reserve begins executing — `STANDARD` contributes 1,
    `ELEVATED` contributes 2, and `CRITICAL` contributes 3."

    Design: Difficulty/combinatorial_formula/allocation_priority_score_reads_stored_risk_tier_not_recomputed
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    assert pod["risk_tier"] == "STANDARD"
    cm = create_countermeasure(unit_cost_cents=1000, reorder_point_quantity=10)
    lot = create_central_inventory_lot(cm["id"], on_hand_quantity=10000)

    reserved = create_reserved_sns_allocation_request(pod["id"], cm["id"], lot["id"], 200)
    assert reserved["priority_score"] == 3.0


def test_priority_score_reads_updated_risk_tier_after_intervening_restrict(api, admin_headers, logistics_headers):
    """PRD §3.5: "That risk-tier read is pinned deliberately: `risk_tier` is
    read as whatever value is already stored on the POD and is never
    recomputed inline as part of this same reserve request, even though
    reserving also touches inventory state that could in principle influence
    risk. A later reserve request only ever sees an updated `risk_tier` once
    some other request — opening, restricting, resuming, or closing the POD,
    or a dispensing cascade — has actually recomputed it."

    Design: Difficulty/combinatorial_formula/allocation_priority_score_reads_stored_risk_tier_not_recomputed
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure(unit_cost_cents=1000, reorder_point_quantity=10)
    lot = create_central_inventory_lot(cm["id"], on_hand_quantity=10000)

    ar1 = create_reserved_sns_allocation_request(pod["id"], cm["id"], lot["id"], 200)
    assert ar1["priority_score"] == 3.0

    restricted = restrict_pod(pod["id"])
    assert restricted["risk_tier"] == "CRITICAL"

    ar2 = create_allocation_request(pod["id"], cm["id"], requested_quantity=200)
    ar2_reserved = reserve_allocation_request(ar2["id"], lot["id"], logistics_headers)

    assert ar2_reserved["priority_score"] == 5.0
    assert ar1["priority_score"] != ar2_reserved["priority_score"]
