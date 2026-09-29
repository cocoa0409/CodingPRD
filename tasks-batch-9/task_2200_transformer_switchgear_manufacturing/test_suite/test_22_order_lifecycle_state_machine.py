"""The order's two independent dimensions: derived advances, compensating
reverts, cancellation cascades and the cross-dimension guards."""

from test_helpers import (
    CONTRACT_ADMIN,
    FIELD_SERVICE_ENGINEER,
    LOGISTICS_COORDINATOR,
    MATERIALS_PLANNER,
    PLANT_ADMIN,
    TEST_ENGINEER,
    WITNESS_COORDINATOR,
    assert_component_buckets,
    assert_order_state,
    assert_instant_equals,
    assert_punch_aggregates,
    commit_allocation,
    create_allocation,
    create_component,
    create_drawing,
    create_fat,
    create_job,
    create_order,
    create_release,
    create_supplier,
    create_witness_party,
    make_customer_witness_headers,
    order_version,
    punch_list_item_payload,
    read_component,
    read_order,
    release_design,
    set_clock,
    shipment_release_payload,
    submit_drawing,
    witness_assignment_payload,
)
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId

_CLOCK = "2026-03-02T08:00:00Z"


def _order(api, order_number):
    return create_order(
        api,
        order_number=order_number,
        customer_name="Riverbend Utility",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=4000000,
        sold_at="2026-01-05T00:00:00Z",
        promised_ship_at="2026-10-01T00:00:00Z",
    )


def _protected_component(api, suffix):
    supplier = create_supplier(
        api,
        supplier_code="SUP-%s-01" % suffix,
        legal_name="Copperline Windings AG",
        region="NA",
    )
    return create_component(
        api,
        supplier["id"],
        part_number="PN-%s-01" % suffix,
        category="HV_BUSHING",
        lead_time_days=120,
        quantity_on_hand=10,
        allocation_policy="PROTECTED",
    )


def _committed_order(api, order_number, suffix):
    order = _order(api, order_number)
    # PRD 3.4: committing an allocation "requires the component to be `ACTIVE`,
    # the order's `engineering_status` to be `DESIGN_RELEASED`" — so the design is
    # released before any commit is attempted.
    release_design(api, order)
    component = _protected_component(api, suffix)
    allocation = create_allocation(
        api,
        component["id"],
        order["id"],
        quantity=4,
        priority_class=2,
        need_by_date="2026-09-01T00:00:00Z",
    )
    return order, component, allocation


def test_committing_the_last_reserved_row_derives_material_allocated(api):
    """PRD 3.1: "`PLANNING` moves to `MATERIAL_ALLOCATED` automatically after any
    component allocation state change on the order, the moment the order holds at
    least one allocation in status `COMMITTED` and zero allocations in status
    `RESERVED`."

    Design: Corner/state_machines/committing_the_only_reserved_allocation_derives_order_material_allocated
    """
    set_clock(api, _CLOCK)
    order, component, allocation = _committed_order(api, "ORD-CORNER-SM6", "SM6")
    committed = validate_success(
        api.commit_component_allocation(allocation["id"], {}, MATERIALS_PLANNER)
    )
    assert committed["status"] == "COMMITTED"
    assert_instant_equals(committed["committed_at"], _CLOCK)

    assert_order_state(
        read_order(api, order["id"]),
        engineering_status="DESIGN_RELEASED",
        fulfillment_status="MATERIAL_ALLOCATED",
        production_posture="OPEN",
        posture_reason_codes=[],
    )
    assert_component_buckets(
        read_component(api, component["id"]),
        quantity_reserved=0,
        quantity_committed=4,
        quantity_available=6,
    )


def test_releasing_the_last_committed_row_reverts_the_derived_advance(api):
    """PRD 3.1: "The reverse edge, `MATERIAL_ALLOCATED` back to `PLANNING`, fires
    whenever the order's count of `COMMITTED` allocations falls to zero; it adds
    `MATERIAL_INCOMPLETE` to the posture reason codes and recomputes the posture."

    Design: Corner/state_machines/releasing_the_only_committed_allocation_reverts_order_to_planning_restricted
    """
    set_clock(api, _CLOCK)
    order, component, allocation = _committed_order(api, "ORD-CORNER-SM7", "SM7")
    commit_allocation(api, allocation["id"])

    released = validate_success(
        api.release_component_allocation(
            allocation["id"], {"reason": "Customer deferred the BOM"}, MATERIALS_PLANNER
        )
    )
    assert released["status"] == "RELEASED"
    assert_instant_equals(released["released_at"], _CLOCK)

    assert_order_state(
        read_order(api, order["id"]),
        fulfillment_status="PLANNING",
        production_posture="RESTRICTED",
        posture_reason_codes=["MATERIAL_INCOMPLETE"],
    )
    assert_component_buckets(
        read_component(api, component["id"]),
        quantity_on_hand=10,
        quantity_reserved=0,
        quantity_committed=0,
        quantity_consumed=0,
        quantity_available=10,
    )


def test_cancelling_the_order_cancels_its_held_stage_and_seals_the_aggregate(api):
    """PRD 3.1: cancellation drives fulfilment to `CANCELLED` and "Every shipment
    release on the order in status `HELD`, `CLEARED`, `STAGED` or `SITE_STORAGE`
    becomes `CANCELLED`... Finally `production_posture` is set to `FROZEN` with
    `posture_reason_codes` containing exactly `ORDER_CANCELLED`"; PRD 2.11: "any
    child-creating or child-advancing write that resolves to an order whose
    `fulfillment_status` is `CANCELLED` yields `ERR_ORDER_CANCELLED` (HTTP 409)."

    Design: Corner/state_machines/cancel_order_cascades_held_shipment_release_to_cancelled
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-SM8")
    release = create_release(api, order["id"])
    assert release["status"] == "HELD"

    cancelled = validate_success(
        api.cancel_engineered_order(
            order["id"],
            {"cancelled_reason": "Customer terminated for convenience"},
            CONTRACT_ADMIN,
        )
    )
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["cancelled_reason"] == "Customer terminated for convenience"
    assert cancelled["production_posture"] == "FROZEN"
    assert cancelled["posture_reason_codes"] == ["ORDER_CANCELLED"]

    assert validate_success(
        api.get_shipment_release(release["id"], LOGISTICS_COORDINATOR)
    )["status"] == "CANCELLED"

    # The order version is fresh, so optimistic concurrency cannot mask the
    # cancelled-parent rung.
    validate_error(
        api.create_shipment_release(
            order["id"],
            shipment_release_payload(
                order_version(api, order["id"]), stage_index=2, is_final_stage=False
            ),
            LOGISTICS_COORDINATOR,
        ),
        ApiErrorId.ORDER_CANCELLED,
        409,
    )


def test_cancelling_a_job_rejects_its_open_punch_items_and_empties_the_ratio(api):
    """PRD 3.8: cancelling a non-terminal job "drives every punch item on the job
    in status `OPEN`, `ASSIGNED` or `RESOLVED` to the terminal `REJECTED` state,
    recomputes the job's aggregates"; and "When the total is zero the ratio is
    10000 basis points... Rejected items are therefore absent from both numerator
    and denominator."

    Design: Corner/state_machines/cancel_commissioning_job_rejects_its_open_punch_items
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-SM9")
    release = create_release(api, order["id"])
    job = create_job(
        api, order["id"], release["id"], mobilization_at="2026-06-01T08:00:00Z"
    )
    blocking = validate_success(
        api.create_punch_list_item(
            job["id"],
            punch_list_item_payload(
                severity="BLOCKING", description_text="Bushing torque out of spec"
            ),
            FIELD_SERVICE_ENGINEER,
        ),
        201,
    )
    minor = validate_success(
        api.create_punch_list_item(
            job["id"],
            punch_list_item_payload(
                severity="MINOR", description_text="Touch-up paint on cabinet door"
            ),
            FIELD_SERVICE_ENGINEER,
        ),
        201,
    )

    cancelled = validate_success(
        api.cancel_commissioning_job(
            job["id"],
            {"reason": "Site not ready; scope moved to a later outage"},
            PLANT_ADMIN,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert_punch_aggregates(
        cancelled,
        open_punch_count=0,
        blocking_punch_count=0,
        completion_ratio_bp=10000,
    )

    for item_id in (blocking["id"], minor["id"]):
        assert validate_success(
            api.get_punch_list_item(item_id, PLANT_ADMIN)
        )["status"] == "REJECTED"


def test_declining_an_invited_witness_never_decrements_below_zero(api):
    """PRD 3.5: "Declining from `INVITED` records the reason and leaves
    `confirmed_witness_count` untouched."

    Design: Corner/state_machines/decline_invited_witness_assignment_moves_to_declined_without_touching_counts
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-SM10")
    fat = create_fat(
        api,
        order["id"],
        test_duration_hours=12,
        witness_required=True,
        requires_impulse=False,
    )
    party = create_witness_party(
        api,
        party_code="WP-SM10-01",
        display_name="Riverbend Utility QA",
        party_type="CUSTOMER",
        home_region="NA",
        daily_witness_capacity=1,
        credential_expires_at="2030-01-01T00:00:00Z",
    )
    assignment = validate_success(
        api.create_witness_assignment(
            fat["id"],
            witness_assignment_payload(party["id"], travel_region="NA"),
            WITNESS_COORDINATOR,
        ),
        201,
    )
    assert assignment["status"] == "INVITED"

    declined = validate_success(
        api.decline_witness_assignment(
            assignment["id"],
            {"decline_reason": "Inspector reassigned to another outage"},
            make_customer_witness_headers(party["id"]),
        )
    )
    assert declined["status"] == "DECLINED"
    assert declined["decline_reason"] == "Inspector reassigned to another outage"
    assert declined["confirmed_at"] is None

    parent = validate_success(api.get_factory_acceptance_test(fat["id"], TEST_ENGINEER))
    assert parent["status"] == "REQUESTED"
    assert parent["confirmed_witness_count"] == 0


def test_a_legally_positioned_fulfilment_dimension_cannot_save_an_unreleased_design(api):
    """PRD 3.1: "Advancing `fulfillment_status` from `MATERIAL_ALLOCATED` to
    `IN_PRODUCTION`... `engineering_status` must be `DESIGN_RELEASED`, or the
    request fails with `ERR_DESIGN_NOT_RELEASED`."

    Design: Corner/state_machines/start_production_on_material_allocated_order_without_design_release_is_blocked
    """
    set_clock(api, _CLOCK)
    order, _component, allocation = _committed_order(api, "ORD-CORNER-SM11", "SM11")
    commit_allocation(api, allocation["id"])
    assert read_order(api, order["id"])["fulfillment_status"] == "MATERIAL_ALLOCATED"

    # PRD 3.2: "Submitting a revision whose `revision_round` is strictly greater
    # than the order's `released_drawing_revision` is the re-opening path: it
    # drives `engineering_status` from `DESIGN_RELEASED` back to
    # `SUBMITTAL_IN_REVIEW`." The fulfilment dimension is untouched by that move.
    reopened = create_drawing(api, order["id"], drawing_set_code="DS-SM11-B")
    submit_drawing(api, reopened["id"])
    assert_order_state(
        read_order(api, order["id"]),
        engineering_status="SUBMITTAL_IN_REVIEW",
        fulfillment_status="MATERIAL_ALLOCATED",
    )

    validate_error(
        api.start_production(order["id"], {}, MATERIALS_PLANNER),
        ApiErrorId.DESIGN_NOT_RELEASED,
        409,
    )
    assert_order_state(
        read_order(api, order["id"]),
        engineering_status="SUBMITTAL_IN_REVIEW",
        fulfillment_status="MATERIAL_ALLOCATED",
    )


def test_closing_engineering_from_the_opening_state_never_freezes_the_order(api):
    """PRD 3.1: closing engineering "advances `engineering_status` from
    `DESIGN_RELEASED` to `ENG_CLOSED`"; PRD 2.11: "a row whose current status is
    not a legal source for the requested transition yields
    `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/close_engineering_from_eng_open_returns_invalid_state_transition
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-SM12")
    validate_error(
        api.close_engineering(order["id"], {}, PLANT_ADMIN),
        ApiErrorId.INVALID_STATE_TRANSITION,
        409,
    )
    assert_order_state(
        read_order(api, order["id"]),
        engineering_status="ENG_OPEN",
        production_posture="OPEN",
        posture_reason_codes=[],
    )
