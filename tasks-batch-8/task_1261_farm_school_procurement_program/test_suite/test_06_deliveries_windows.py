"""Receiving windows and the delivery workflow: interval overlap, state
guards, dispute resolution, sweeps, and aggregate delivery accounting."""
from test_helpers import (
    ApiErrorId,
    accept_delivery,
    advance_clock,
    api_client,
    assert_agreement,
    assert_delivery,
    assert_receiving_window,
    check_in_delivery,
    create_accepted_delivery,
    create_kitchen,
    create_receiving_window,
    make_farm_manager_headers,
    make_kitchen_manager_headers,
    schedule_delivery,
    setup_procurement_chain,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


def test_receiving_window_immutable_shape(api):
    """PRD section 2.4: "Receiving windows are the single exception: a
    receiving window is immutable after creation and carries only `id` and
    `created_at` — both `updated_at` and `version` are absent on that
    resource."

    Design: Corner/entities/ent_receiving_window_immutable_shape
    """
    kitchen = create_kitchen()
    window = create_receiving_window(kitchen["id"])
    assert_receiving_window(window)

    reread = validate_success(api.get_receiving_window(window["id"], ADMIN), 200)
    assert_receiving_window(reread)
    assert reread["id"] == window["id"]
    assert reread["created_at"] == window["created_at"]


def test_delivery_state_family_errors(api):
    """PRD section 3.5: "Acceptance records an `accepted_quantity` between 1
    and the delivery's full `quantity` inclusive — outside that range is
    `ERR_ACCEPTED_QUANTITY_OUT_OF_RANGE`, and a delivery not in `CHECKED_IN`
    draws `ERR_DELIVERY_NOT_CHECKED_IN`"
    PRD section 3.5: "the receiving kitchen's `KitchenManager` checks the
    delivery in (`SCHEDULED` → `CHECKED_IN`; from any other state,
    `ERR_DELIVERY_NOT_SCHEDULED`)"
    PRD section 3.5: "the farm's `FarmManager` moves a `REJECTED` delivery to
    `DISPUTED` (`ERR_DELIVERY_NOT_REJECTED` from any other state)."
    PRD section 3.5: "a delivery that is not `DISPUTED` draws
    `ERR_DELIVERY_NOT_DISPUTED`."

    Design: Corner/state_machines/sm_delivery_state_family_errors
    """
    chain = setup_procurement_chain()
    delivery = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 40,
        ),
        201,
    )
    did = delivery["id"]
    kit_headers = make_kitchen_manager_headers(chain.kitchen["id"])
    farm_headers = make_farm_manager_headers(chain.farm["id"])

    # From SCHEDULED: accept, dispute, resolve-dispute all mis-target the state.
    validate_error(
        api.accept_delivery(did, {"accepted_quantity": 40}, kit_headers),
        ApiErrorId.ERR_DELIVERY_NOT_CHECKED_IN,
    )
    validate_error(api.dispute_delivery(did, farm_headers), ApiErrorId.ERR_DELIVERY_NOT_REJECTED)
    validate_error(
        api.resolve_delivery_dispute(
            did, {"resolution": "ACCEPTED", "accepted_quantity": 40}, ADMIN
        ),
        ApiErrorId.ERR_DELIVERY_NOT_DISPUTED,
    )

    # Check-in is single-shot.
    validate_success(api.check_in_delivery(did, kit_headers), 200)
    validate_error(api.check_in_delivery(did, kit_headers), ApiErrorId.ERR_DELIVERY_NOT_SCHEDULED)

    # The accepted quantity range is 1..quantity inclusive.
    validate_error(
        api.accept_delivery(did, {"accepted_quantity": 0}, kit_headers),
        ApiErrorId.ERR_ACCEPTED_QUANTITY_OUT_OF_RANGE,
    )
    validate_error(
        api.accept_delivery(did, {"accepted_quantity": 41}, kit_headers),
        ApiErrorId.ERR_ACCEPTED_QUANTITY_OUT_OF_RANGE,
    )


def test_dispute_resolve_accept_applies_side_effects(api):
    """PRD section 3.5: "Resolving to `ACCEPTED` carries an `accepted_quantity`
    in the same 1-to-`quantity` range (`ERR_ACCEPTED_QUANTITY_OUT_OF_RANGE`)
    and produces exactly the same downstream effects as a kitchen acceptance —
    the delivered total is recomputed and a fully delivered agreement
    completes."

    Design: Corner/state_machines/sm_dispute_resolve_accept_applies_side_effects
    """
    chain = setup_procurement_chain()
    farm_headers = make_farm_manager_headers(chain.farm["id"])
    delivery = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 40,
        ),
        201,
    )
    did = delivery["id"]
    kit_headers = make_kitchen_manager_headers(chain.kitchen["id"])
    validate_success(api.check_in_delivery(did, kit_headers), 200)
    rejected = validate_success(
        api.reject_delivery(did, {"reason": "partial spoilage"}, kit_headers), 200
    )
    assert rejected["status"] == "REJECTED"
    disputed = validate_success(api.dispute_delivery(did, farm_headers), 200)
    assert disputed["status"] == "DISPUTED"

    resolved = validate_success(
        api.resolve_delivery_dispute(
            did, {"resolution": "ACCEPTED", "accepted_quantity": 25}, ADMIN
        ),
        200,
    )
    assert_delivery(resolved)
    assert resolved["status"] == "ACCEPTED"
    assert resolved["accepted_quantity"] == 25

    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["delivered_quantity"] == 25, (
        "dispute resolution applies the same delivered-total recompute"
    )


def test_clock_sweep_marks_delivery_no_show(api):
    """PRD section 2.8: "Deliveries still `SCHEDULED` whose `delivery_date` now
    lies in the past become `NO_SHOW`."

    Design: Corner/state_machines/sm_clock_sweep_marks_delivery_no_show
    """
    chain = setup_procurement_chain()
    delivery = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 40,
        ),
        201,
    )
    advance_clock("2026-08-11T00:00:00Z")
    after = validate_success(api.get_delivery(delivery["id"], ADMIN), 200)
    assert after["status"] == "NO_SHOW", (
        f"a SCHEDULED delivery whose date passes becomes NO_SHOW, got {after['status']}"
    )


def test_delivered_aggregation_order_independent(api):
    """PRD section 3.5: "Each acceptance recomputes the agreement's
    `delivered_quantity` as the sum of `accepted_quantity` over all of the
    agreement's `ACCEPTED` deliveries, evaluated in delivery-date order with
    creation time as the tie-break so the completion check is deterministic"

    Design: Corner/calculations/calc_delivered_aggregation_order_independent
    """
    chain = setup_procurement_chain()
    del_early = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 40,
        ),
        201,
    )
    del_late = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-17", 10,
        ),
        201,
    )
    # Accept the later-dated delivery first; the sum is order-insensitive.
    accept_delivery(del_late["id"], chain.kitchen["id"], 10)
    accept_delivery(del_early["id"], chain.kitchen["id"], 40)

    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["delivered_quantity"] == 50


def test_window_kitchen_mismatch(api):
    """PRD section 3.5: "The window must belong to the named kitchen
    (`ERR_WINDOW_KITCHEN_MISMATCH`)"

    Design: Corner/validations/val_window_kitchen_mismatch
    """
    chain = setup_procurement_chain()
    other_kitchen = create_kitchen(name="Washington MS")
    resp = schedule_delivery(
        chain.agreement["id"], other_kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 10,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_KITCHEN_MISMATCH)


def test_window_weekday_mismatch(api):
    """PRD section 3.5: "the window's weekday must equal the weekday of the
    `delivery_date` (`ERR_WINDOW_WEEKDAY_MISMATCH`)"

    Design: Corner/validations/val_window_weekday_mismatch
    """
    chain = setup_procurement_chain()
    # The window is MON; 2026-08-11 is a Tuesday.
    resp = schedule_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-11", 10,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_WEEKDAY_MISMATCH)


def test_delivery_outside_harvest_window(api):
    """PRD section 3.5: "the delivery's derived `week_number` must fall inside
    the agreement's harvest window and within the program year
    (`ERR_DELIVERY_OUTSIDE_HARVEST_WINDOW`)"

    Design: Corner/validations/val_delivery_outside_harvest_window
    """
    chain = setup_procurement_chain(agreement_window=(5, 6))
    # 2026-08-17 falls in week 7 of the year — outside the agreement's 5..6.
    resp = schedule_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-17", 10,
    )
    validate_error(resp, ApiErrorId.ERR_DELIVERY_OUTSIDE_HARVEST_WINDOW)


def test_delivery_date_in_past(api):
    """PRD section 3.5: "The date must not precede the current logical clock
    date (`ERR_DELIVERY_DATE_IN_PAST`)"

    Design: Corner/validations/val_delivery_date_in_past
    """
    chain = setup_procurement_chain()
    advance_clock("2026-08-05T00:00:00Z")
    resp = schedule_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-03", 10,
    )
    validate_error(resp, ApiErrorId.ERR_DELIVERY_DATE_IN_PAST)


def test_quantity_exceeds_remaining(api):
    """PRD section 3.5: "the `quantity` must be at least 1 and may not exceed
    the agreement's committed quantity minus what has been delivered and minus
    the quantities still held by that agreement's `SCHEDULED` and `CHECKED_IN`
    deliveries (`ERR_QUANTITY_EXCEEDS_REMAINING`)."

    Design: Corner/validations/val_quantity_exceeds_remaining
    """
    chain = setup_procurement_chain(committed_quantity=100)
    validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 60,
        ),
        201,
    )
    # Committed 100, delivered 0, scheduled 60 leaves 40.
    resp = schedule_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-17", 50,
    )
    validate_error(resp, ApiErrorId.ERR_QUANTITY_EXCEEDS_REMAINING)


def test_window_delete_guard_and_success(api):
    """PRD section 3.5: "Windows are immutable and deletable only while unused:
    deletion is blocked with `ERR_WINDOW_IN_USE` as long as any `SCHEDULED` or
    `CHECKED_IN` delivery references the window."
    PRD section 4: "Deleting a receiving window returns `204 No Content`"

    Design: Corner/endpoints/ep_window_delete_guard_and_success
    """
    chain = setup_procurement_chain()
    delivery = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 40,
        ),
        201,
    )
    kit_headers = make_kitchen_manager_headers(chain.kitchen["id"])

    resp = api.delete_receiving_window(chain.window["id"], kit_headers)
    validate_error(resp, ApiErrorId.ERR_WINDOW_IN_USE)

    validate_success(
        api.cancel_delivery(delivery["id"], make_farm_manager_headers(chain.farm["id"])),
        200,
    )
    resp = api.delete_receiving_window(chain.window["id"], kit_headers)
    assert resp.status_code == 204, (
        f"deleting an unused window must return 204, got {resp.status_code}"
    )
    validate_error(
        api.get_receiving_window(chain.window["id"], kit_headers),
        ApiErrorId.ERR_WINDOW_NOT_FOUND,
    )


def test_immediate_visibility_after_accept(api):
    """PRD section 2.10: "Derived values are never stale. A forecast line's
    `reserved_quantity` and `uncovered_quantity`, an agreement's
    `delivered_quantity`, a claim's totals, and a farm's `compliance_posture`
    are recomputed from their sources whenever the underlying data changes"

    Design: Corner/consistency_model/cons_immediate_visibility_after_accept
    """
    chain = setup_procurement_chain()
    delivery = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 40,
        ),
        201,
    )
    accepted = accept_delivery(delivery["id"], chain.kitchen["id"], 40)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_quantity"] == 40

    # The very next read already reflects the recomputed aggregate.
    agreement = validate_success(
        api.get_planting_agreement(
            chain.agreement["id"], make_kitchen_manager_headers(chain.kitchen["id"])
        ),
        200,
    )
    assert agreement["delivered_quantity"] == 40
    assert agreement["status"] == "FULFILLING"


def test_receiving_window_half_open_adjacency_allowed(api):
    """PRD section 3.5: "A window is a half-open interval — it admits
    deliveries from the start minute up to but not including the end minute —
    so two windows on the same kitchen and weekday may touch but never overlap:
    an incoming window whose interval intersects an existing one is rejected
    with `ERR_WINDOW_OVERLAP`, while one whose start equals the other's end is
    lawful adjacency."

    Design: Difficulty/resource_temporal_overlap/receiving_window_half_open_overlap
    """
    kitchen = create_kitchen()
    create_receiving_window(kitchen["id"], start_minute=480, end_minute=720)

    # 720 == existing end: lawful adjacency.
    adjacent = create_receiving_window(kitchen["id"], start_minute=720, end_minute=900)
    assert_receiving_window(adjacent)

    # 600 < 720 and 480 < 800: a true intersection.
    kit_headers = make_kitchen_manager_headers(kitchen["id"])
    resp = api.create_receiving_window(
        {
            "kitchen_id": kitchen["id"],
            "weekday": "MON",
            "start_minute": 600,
            "end_minute": 800,
            "capacity_deliveries": 1,
        },
        kit_headers,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


def test_receiving_window_half_open_containment_rejected(api):
    """PRD section 3.5: "an incoming window whose interval intersects an
    existing one is rejected with `ERR_WINDOW_OVERLAP`, while one whose start
    equals the other's end is lawful adjacency."

    Design: Difficulty/resource_temporal_overlap/receiving_window_half_open_overlap
    """
    kitchen = create_kitchen()
    create_receiving_window(kitchen["id"], start_minute=480, end_minute=720)
    kit_headers = make_kitchen_manager_headers(kitchen["id"])

    # Fully contained inside the existing window: intersects.
    resp = api.create_receiving_window(
        {
            "kitchen_id": kitchen["id"],
            "weekday": "MON",
            "start_minute": 500,
            "end_minute": 700,
            "capacity_deliveries": 1,
        },
        kit_headers,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)

    # Touching on the other side (end == existing start): lawful adjacency.
    before = create_receiving_window(kitchen["id"], start_minute=360, end_minute=480)
    assert_receiving_window(before)


def test_delivery_receipt_fork_divergence(api):
    """PRD section 3.5: "Each acceptance recomputes the agreement's
    `delivered_quantity` as the sum of `accepted_quantity` over all of the
    agreement's `ACCEPTED` deliveries"
    PRD section 3.5: "Rejection instead requires a `reason`, which is stored on
    the delivery as `rejection_reason`, moves the delivery to `REJECTED`, and
    leaves the agreement's delivered total unchanged."

    Design: Difficulty/non_linear_state_machine/delivery_receipt_fork_divergence
    """
    chain = setup_procurement_chain()
    del_ok = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 40,
        ),
        201,
    )
    del_bad = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 10,
        ),
        201,
    )
    kit_headers = make_kitchen_manager_headers(chain.kitchen["id"])

    accepted = accept_delivery(del_ok["id"], chain.kitchen["id"], 40)
    assert accepted["status"] == "ACCEPTED"

    check_in_delivery(del_bad["id"], chain.kitchen["id"])
    rejected = validate_success(
        api.reject_delivery(del_bad["id"], {"reason": "spoiled"}, kit_headers), 200
    )
    assert rejected["status"] == "REJECTED"

    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["delivered_quantity"] == 40, (
        "the rejected fork added nothing to the delivered total"
    )
    assert agreement["status"] == "FULFILLING"


def test_delivery_receipt_fork_rejection_leaves_total_unchanged(api):
    """PRD section 3.5: "Rejection instead requires a `reason`, which is stored
    on the delivery as `rejection_reason`, moves the delivery to `REJECTED`,
    and leaves the agreement's delivered total unchanged."

    Design: Difficulty/non_linear_state_machine/delivery_receipt_fork_divergence
    """
    chain = setup_procurement_chain()
    del_bad = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 10,
        ),
        201,
    )
    kit_headers = make_kitchen_manager_headers(chain.kitchen["id"])
    check_in_delivery(del_bad["id"], chain.kitchen["id"])
    rejected = validate_success(
        api.reject_delivery(del_bad["id"], {"reason": "spoiled"}, kit_headers), 200
    )
    assert rejected["rejection_reason"] == "spoiled"

    # The delivered total is exactly what it was before the rejection: zero.
    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert_agreement(agreement)
    assert agreement["delivered_quantity"] == 0
    assert agreement["status"] == "FULFILLING"
