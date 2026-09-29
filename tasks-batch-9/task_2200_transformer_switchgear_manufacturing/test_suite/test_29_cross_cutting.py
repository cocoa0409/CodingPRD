"""Optimistic concurrency on both parents, the aggregate-guarded material
cascade, the two escalation variants and the approval pin."""

from test_helpers import (
    CONTRACT_ADMIN,
    CUSTOMER_REVIEWER,
    DESIGN_ENGINEER,
    MATERIALS_PLANNER,
    PLANT_ADMIN,
    USER_DESIGN_1,
    USER_REVIEWER_1,
    assert_component_buckets,
    attach_escalation_clause,
    commodity_index_point_payload,
    component_allocation_payload,
    create_component,
    create_order,
    create_supplier,
    escalation_adjustment_payload,
    order_version,
    read_component,
    read_order,
    release_design,
    set_clock,
    submittal_drawing_payload,
)
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId

_CLOCK = "2026-03-02T08:00:00Z"


def _order(api, order_number, **overrides):
    payload = dict(
        order_number=order_number,
        customer_name="Riverbend Utility",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=4000000,
        sold_at="2026-01-05T00:00:00Z",
        promised_ship_at="2026-10-01T00:00:00Z",
    )
    payload.update(overrides)
    return create_order(api, **payload)


def test_a_version_stale_by_one_patch_cannot_author_a_revision(api):
    """PRD 2.7: "Creating a new submittal drawing revision under an order requires
    `expected_engineered_order_version` to match the order's current `version`; a
    mismatch is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/submittal_drawing_create_with_version_stale_by_one_patch_returns_stale_order_version
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-CC1")
    stale_version = order["version"]
    patched = validate_success(
        api.patch_engineered_order(
            order["id"], {"customer_name": "Riverbend Utility District 4"}, CONTRACT_ADMIN
        )
    )
    fresh_version = patched["version"]
    assert fresh_version == stale_version + 1

    validate_error(
        api.create_submittal_drawing(
            order["id"],
            submittal_drawing_payload(
                stale_version,
                drawing_set_code="DS-CC1-A",
                authored_by_user_id=USER_DESIGN_1,
            ),
            DESIGN_ENGINEER,
        ),
        ApiErrorId.STALE_ORDER_VERSION,
        412,
    )
    assert api.list_order_submittal_drawings(order["id"], DESIGN_ENGINEER).json()["data"] == []

    accepted = validate_success(
        api.create_submittal_drawing(
            order["id"],
            submittal_drawing_payload(
                fresh_version,
                drawing_set_code="DS-CC1-A",
                authored_by_user_id=USER_DESIGN_1,
            ),
            DESIGN_ENGINEER,
        ),
        201,
    )
    assert accepted["revision_round"] == 1


def test_the_allocation_guard_pins_the_component_and_not_the_order(api):
    """PRD 2.7: "Creating a component allocation is the one rule whose parent is
    not the order. It requires `expected_component_version` to match the current
    `version` of the long-lead component named in the body, and a mismatch yields
    `ERR_STALE_COMPONENT_VERSION` (HTTP 412)"; PRD 3.4: a receipt "increases
    `quantity_on_hand` by that amount, re-derives the four unit buckets and
    increments the component's `version`."

    Design: Corner/cross_cutting_complexity_layers/allocation_create_with_version_stale_by_one_receipt_returns_stale_component_version
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-CC2")
    supplier = create_supplier(
        api,
        supplier_code="SUP-CC2",
        legal_name="Northline Copperworks GmbH",
        region="NA",
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="PN-CC2-1",
        category="VACUUM_INTERRUPTER",
        lead_time_days=120,
        quantity_on_hand=10,
        allocation_policy="PREEMPTIBLE",
    )
    stale_version = component["version"]
    validate_success(
        api.create_component_receipt(component["id"], {"quantity": 5}, MATERIALS_PLANNER)
    )
    fresh_version = read_component(api, component["id"])["version"]

    def body(version):
        return component_allocation_payload(
            component["id"],
            order["id"],
            version,
            quantity=4,
            priority_class=3,
            need_by_date="2026-06-01T00:00:00Z",
        )

    validate_error(
        api.create_component_allocation(body(stale_version), MATERIALS_PLANNER),
        ApiErrorId.STALE_COMPONENT_VERSION,
        412,
    )
    assert_component_buckets(
        read_component(api, component["id"]),
        quantity_on_hand=15,
        quantity_reserved=0,
    )

    accepted = validate_success(
        api.create_component_allocation(body(fresh_version), MATERIALS_PLANNER), 201
    )
    assert accepted["status"] == "RESERVED"


def test_the_material_cascade_is_guarded_on_the_aggregate_not_on_the_commit(api):
    """PRD 3.1: "`PLANNING` moves to `MATERIAL_ALLOCATED` automatically after any
    component allocation state change on the order, the moment the order holds at
    least one allocation in status `COMMITTED` and zero allocations in status
    `RESERVED`."

    Design: Corner/cross_cutting_complexity_layers/order_material_allocated_cascade_fires_only_on_the_last_reserved_allocation
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-CC3")
    # PRD 3.4: committing an allocation "requires... the order's
    # `engineering_status` to be `DESIGN_RELEASED`".
    release_design(api, order)
    supplier = create_supplier(
        api,
        supplier_code="SUP-CC3",
        legal_name="Northline Copperworks GmbH",
        region="NA",
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="PN-CC3-1",
        category="TAP_CHANGER",
        lead_time_days=90,
        quantity_on_hand=10,
        allocation_policy="PROTECTED",
    )
    alloc_a = validate_success(
        api.create_component_allocation(
            component_allocation_payload(
                component["id"],
                order["id"],
                component["version"],
                quantity=3,
                priority_class=2,
                need_by_date="2026-06-01T00:00:00Z",
            ),
            MATERIALS_PLANNER,
        ),
        201,
    )
    alloc_b = validate_success(
        api.create_component_allocation(
            component_allocation_payload(
                component["id"],
                order["id"],
                read_component(api, component["id"])["version"],
                quantity=4,
                priority_class=2,
                need_by_date="2026-06-01T00:00:00Z",
            ),
            MATERIALS_PLANNER,
        ),
        201,
    )

    validate_success(
        api.commit_component_allocation(alloc_a["id"], {}, MATERIALS_PLANNER)
    )
    assert read_order(api, order["id"])["fulfillment_status"] == "PLANNING"

    validate_success(
        api.commit_component_allocation(alloc_b["id"], {}, MATERIALS_PLANNER)
    )
    assert read_order(api, order["id"])["fulfillment_status"] == "MATERIAL_ALLOCATED"
    assert_component_buckets(
        read_component(api, component["id"]),
        quantity_reserved=0,
        quantity_committed=7,
    )


def test_the_two_variants_diverge_on_the_same_clause_and_the_same_clock(api):
    """PRD 3.3: "Under `FINAL`, the window is every usable non-provisional row whose
    `index_month` falls in the inclusive range beginning one month after
    `base_index_month` and ending at `final_window_end_month`, processed in ascending
    month order; if that window is empty for any weighted commodity the request fails
    with `ERR_INDEX_WINDOW_EMPTY`"; whereas under `PROVISIONAL` "the current level is
    the `index_value` of the usable row with the greatest `index_month` that is at or
    before `final_window_end_month`".

    Design: Corner/cross_cutting_complexity_layers/final_variant_rejected_where_provisional_variant_is_accepted_on_the_same_clause
    """
    set_clock(api, _CLOCK)
    for commodity in ("COPPER", "ALUMINUM", "CORE_STEEL"):
        validate_success(
            api.create_commodity_index_point(
                commodity_index_point_payload(
                    commodity=commodity,
                    index_month="2026-01",
                    index_value=10000,
                    published_at="2026-02-05T00:00:00Z",
                    is_provisional=False,
                ),
                CONTRACT_ADMIN,
            ),
            201,
        )
    order = _order(
        api,
        "ORD-CORNER-CC4",
        product_family="POWER_TRANSFORMER",
        rated_kv=69,
        contract_value_cents=9000000,
    )
    clause = attach_escalation_clause(
        api,
        order["id"],
        copper_weight_bp=6000,
        aluminum_weight_bp=2000,
        core_steel_weight_bp=2000,
        escalatable_base_cents=5000000,
        base_index_month="2026-01",
        cap_bp=1000,
        collar_bp=200,
        de_escalation_enabled=True,
        final_window_end_month="2026-06",
    )

    validate_error(
        api.create_escalation_adjustment(
            order["id"],
            escalation_adjustment_payload(
                clause["id"], order_version(api, order["id"]), variant="FINAL"
            ),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.INDEX_WINDOW_EMPTY,
        422,
    )

    provisional = validate_success(
        api.create_escalation_adjustment(
            order["id"],
            escalation_adjustment_payload(
                clause["id"], order_version(api, order["id"]), variant="PROVISIONAL"
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )
    assert provisional["variant"] == "PROVISIONAL"


def test_the_release_pin_records_what_was_approved_not_what_is_newest(api):
    """PRD 3.2: both approvals "pin `released_drawing_revision` to the approved
    drawing's `revision_round`"; and the server assigns `revision_round` itself —
    "1 for the first package on the order, and one greater than the highest existing
    round for every resubmission".

    Design: Corner/cross_cutting_complexity_layers/released_drawing_revision_stays_pinned_when_a_later_revision_is_submitted
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-CC5")
    first = validate_success(
        api.create_submittal_drawing(
            order["id"],
            submittal_drawing_payload(
                order["version"],
                drawing_set_code="DS-CC5-A",
                authored_by_user_id=USER_DESIGN_1,
            ),
            DESIGN_ENGINEER,
        ),
        201,
    )
    validate_success(api.submit_drawing(first["id"], {}, DESIGN_ENGINEER))
    validate_success(api.begin_review_drawing(first["id"], {}, CUSTOMER_REVIEWER))
    validate_success(
        api.disposition_drawing(
            first["id"],
            {"disposition": "APPROVED", "reviewed_by_user_id": USER_REVIEWER_1},
            CUSTOMER_REVIEWER,
        )
    )
    assert read_order(api, order["id"])["released_drawing_revision"] == 1

    second = validate_success(
        api.create_submittal_drawing(
            order["id"],
            submittal_drawing_payload(
                order_version(api, order["id"]),
                drawing_set_code="DS-CC5-B",
                authored_by_user_id=USER_DESIGN_1,
            ),
            DESIGN_ENGINEER,
        ),
        201,
    )
    assert second["revision_round"] == 2
    assert second["status"] == "DRAFT"
    validate_success(api.submit_drawing(second["id"], {}, DESIGN_ENGINEER))

    assert read_order(api, order["id"])["released_drawing_revision"] == 1
    pinned_source = validate_success(
        api.get_submittal_drawing(first["id"], PLANT_ADMIN)
    )
    assert pinned_source["status"] == "APPROVED"
    assert pinned_source["revision_round"] == 1
