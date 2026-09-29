"""Role authority on the plant contract: the seven roles of PRD §2.1, the 403 gate
of PRD §2.8 band 2, and the warranty duty split of PRD §2.11."""
from datetime import datetime

from test_helpers import (
    CLOCK_START_UTC,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_cents,
    assert_lot_counter_invariant,
    assert_unit_build,
    build_tow_kit,
    create_component_lot,
    create_dealer,
    create_floor_plan,
    file_claim,
    inject_delivered_unit,
    make_dealer_principal_headers,
    read_order,
    schedule_pdi,
    tow_released_build,
    validate_error,
    validate_paginated,
    validate_success,
)

SNEAK_FLOOR_PLAN = {
    "model_code": "FP-SNEAK",
    "chassis_class": "TOWABLE",
    "length_ft": 24,
    "base_msrp_cents": 7000000,
    "base_station_hours": 30.00,
    "base_dry_weight_lbs": 5000,
    "gvwr_lbs": 8000,
    "required_wheelbase_in": 170,
    "electrical_service_amps": 30,
    "fresh_water_capacity_gal": 40,
}


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so two spellings of one moment compare equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_each_plant_role_carries_out_the_operations_its_own_role_list_names(
    api,
    plant_admin_headers,
    scheduler_headers,
    supervisor_headers,
    inspector_headers,
    warranty_admin_headers,
    recall_coordinator_headers,
):
    """PRD §2.1: "`PlantAdmin` owns master data and plant finance — suppliers, floor plans, options, dealers, lines, booths, supply intake, floor-plan funding decisions, the logical clock, the daily-close checkpoint, and the test-driving injection capability — and is deliberately barred from acting inside the shop floor, quality, warranty, and recall workflows."

    PRD §2.1: "`DealerPrincipal` is the ordering dealer. `ProductionScheduler` owns capacity and the order-to-line handoff: slot reservation, chassis matching, release to line, and shipment. `LineSupervisor` runs the stations: advancement, component installation, and installation reversal. `QualityInspector` books booth windows and grades inspections. `WarrantyAdministrator` adjudicates claims. `RecallCoordinator` files, opens, expands, and closes recall campaigns and records remedies on affected installations."

    PRD §2.5: "A `PlantAdmin` moves it by supplying a `current_utc` instant; the response reports both the new `current_utc` and the `previous_utc` it replaced."

    PRD §3.5: "On success the lot's `quantity_available` decreases by the installed quantity and its `quantity_installed` increases by the same amount, conserving the piece total, and a lot whose `quantity_available` reaches exactly zero moves `AVAILABLE → DEPLETED`."

    PRD §3.8: "Multiply the billable hours by the flat rate for the claim's `claim_type` — 7800 cents per hour for `APPLIANCE`, 8600 for `PLUMBING`, 9200 for `ELECTRICAL`, 10400 for `STRUCTURAL`, and 11000 for `WATER_INTRUSION` — and round half up to whole cents."

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations_on_one_unit
    """
    # PlantAdmin owns the logical clock.
    clock = validate_success(
        api.set_clock({"current_utc": "2026-08-01T06:00:00Z"}, plant_admin_headers)
    )
    assert _instant(clock["current_utc"]) == _instant("2026-08-01T06:00:00Z")
    assert _instant(clock["previous_utc"]) == _instant(CLOCK_START_UTC)

    # PlantAdmin owns master data, supply intake and the delivered-unit injection.
    chassis_supplier = validate_success(
        api.create_supplier(
            {
                "supplier_code": "SUP-CH",
                "name": "Cascade Chassis Works",
                "component_categories": ["CHASSIS"],
            },
            plant_admin_headers,
        ),
        201,
    )
    appliance_supplier = validate_success(
        api.create_supplier(
            {
                "supplier_code": "SUP-AP",
                "name": "Northline Appliance",
                "component_categories": ["APPLIANCE"],
            },
            plant_admin_headers,
        ),
        201,
    )
    floor_plan = validate_success(
        api.create_floor_plan(
            {
                "model_code": "FP-TOW",
                "chassis_class": "TOWABLE",
                "length_ft": 28,
                "base_msrp_cents": 8000000,
                "base_station_hours": 40.00,
                "base_dry_weight_lbs": 6000,
                "gvwr_lbs": 9000,
                "required_wheelbase_in": 180,
                "electrical_service_amps": 50,
                "fresh_water_capacity_gal": 60,
            },
            plant_admin_headers,
        ),
        201,
    )
    option = validate_success(
        api.create_option_item(
            {
                "option_code": "OPT-E1",
                "category": "ELECTRICAL",
                "install_station": "ROUGH_IN",
                "price_cents": 100000,
                "weight_lbs": 0,
                "added_station_hours": 1.00,
                "amp_draw": 20,
                "water_demand_gal": 0,
            },
            plant_admin_headers,
        ),
        201,
    )
    dealer = validate_success(
        api.create_dealer(
            {
                "dealer_code": "D-TOW",
                "region": "CENTRAL",
                "allocation_share_bp": 1500,
                "floor_plan_credit_limit_cents": 100000000,
                "goodwill_budget_cents": 500000,
            },
            plant_admin_headers,
        ),
        201,
    )
    line = validate_success(
        api.create_production_line(
            {
                "line_code": "LINE-T",
                "chassis_class_supported": "TOWABLE",
                "daily_station_hour_capacity": 240.00,
                "max_units_per_day": 4,
            },
            plant_admin_headers,
        ),
        201,
    )
    chassis = validate_success(
        api.create_chassis_receipt(
            {
                "supplier_id": chassis_supplier["id"],
                "chassis_serial": "CH-T1",
                "chassis_class": "TOWABLE",
                "gvwr_lbs": 9000,
                "wheelbase_in": 180,
            },
            plant_admin_headers,
        ),
        201,
    )
    lot = validate_success(
        api.create_component_lot(
            {
                "supplier_id": appliance_supplier["id"],
                "part_number": "PN-FRIDGE",
                "lot_code": "LOT-A1",
                "category": "APPLIANCE",
                "quantity_received": 10,
            },
            plant_admin_headers,
        ),
        201,
    )
    delivered = validate_success(
        api.inject_delivered_unit(
            {"dealer_id": dealer["id"], "floor_plan_id": floor_plan["id"]},
            plant_admin_headers,
        ),
        201,
    )

    dealer_headers = make_dealer_principal_headers(dealer["id"])

    # DealerPrincipal opens and submits its own order.
    order = validate_success(
        api.create_unit_order(
            {
                "dealer_id": dealer["id"],
                "floor_plan_id": floor_plan["id"],
                "order_type": "SOLD",
                "selected_option_ids": [option["id"]],
                "requested_delivery_date": "2026-10-01T00:00:00Z",
            },
            dealer_headers,
        ),
        201,
    )
    submitted = validate_success(api.submit_order(order["id"], dealer_headers))
    assert submitted["status"] == "CONFIG_VALIDATED"
    assert submitted["version"] == 2

    # ProductionScheduler reserves the slot, matches the chassis and releases the build.
    slot = validate_success(
        api.reserve_production_slot(
            order["id"],
            {
                "line_id": line["id"],
                "slot_date": "2026-08-05T00:00:00Z",
                "expected_unit_order_version": submitted["version"],
            },
            scheduler_headers,
        ),
        201,
    )
    assert slot["status"] == "RESERVED"
    validate_success(api.match_chassis(order["id"], scheduler_headers))
    matched_chassis = validate_success(
        api.get_chassis_receipt(chassis["id"], scheduler_headers)
    )
    assert matched_chassis["status"] == "MATCHED"
    assert matched_chassis["matched_unit_order_id"] == order["id"]
    build = validate_success(api.release_to_line(order["id"], scheduler_headers), 201)
    assert build["id"] is not None
    assert_unit_build(build)

    # LineSupervisor advances the build and installs pieces.
    advanced = validate_success(
        api.advance_build(
            build["id"],
            {"to_station": "SIDEWALL_LAM", "station_hours_used": 6.00},
            supervisor_headers,
        )
    )
    assert advanced["current_station"] == "SIDEWALL_LAM"
    installation = validate_success(
        api.create_component_installation(
            {
                "unit_build_id": build["id"],
                "component_lot_id": lot["id"],
                "station": "SIDEWALL_LAM",
                "quantity": 2,
            },
            supervisor_headers,
        ),
        201,
    )
    assert installation["status"] == "INSTALLED"
    lot_after_install = validate_success(
        api.get_component_lot(lot["id"], supervisor_headers)
    )
    assert lot_after_install["quantity_available"] == 8
    assert_lot_counter_invariant(lot_after_install)

    # QualityInspector books the pre-delivery inspection.
    inspection = validate_success(
        api.create_quality_inspection(
            {"unit_build_id": build["id"], "inspection_type": "PDI"}, inspector_headers
        ),
        201,
    )
    assert inspection["status"] == "SCHEDULED"

    # RecallCoordinator drafts a campaign.
    campaign = validate_success(
        api.create_recall_campaign(
            {
                "supplier_id": appliance_supplier["id"],
                "campaign_code": "RC-1",
                "part_number": "PN-FRIDGE",
                "lot_codes": ["LOT-A1"],
                "severity": "ADVISORY",
            },
            recall_coordinator_headers,
        ),
        201,
    )
    assert campaign["status"] == "DRAFT"

    # DealerPrincipal files against its delivered coach; WarrantyAdministrator adjudicates.
    claim = validate_success(
        api.create_warranty_claim(
            {
                "unit_build_id": delivered["id"],
                "claim_type": "APPLIANCE",
                "labor_hours": 2.00,
                "parts_cost_cents": 0,
                "narrative": "refrigerator will not light on propane",
            },
            dealer_headers,
        ),
        201,
    )
    decided = validate_success(
        api.decide_claim(claim["id"], {"decision": "APPROVED"}, warranty_admin_headers)
    )
    assert decided["status"] == "APPROVED"
    assert_cents(decided["total_reimbursement_cents"], 15600)


def test_no_role_may_reach_an_operation_another_role_owns(
    api,
    plant_admin_headers,
    scheduler_headers,
    supervisor_headers,
    inspector_headers,
    warranty_admin_headers,
    recall_coordinator_headers,
):
    """PRD §2.1: "If the declared role is not one of the seven names below, or is a valid name that is not listed among the authorised roles for the target operation, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD §2.1: "None is a superset of another; the model is deliberately one of segregated duties."

    PRD §2.8: "Validation is a strictly ordered ladder, not a set of independent checks. The **first** violated rule determines the response; later rules are never reported even when they are also violated. Implementations must therefore evaluate in exactly this order."

    PRD §2.8: "**Authorisation.** The declared role is one of the seven names and appears in the target endpoint's role list, else `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD §3.1: "It is published with a `model_code` unique across floor plans, a `chassis_class`, an overall coach `length_ft` between 18 and 45 inclusive, a `base_msrp_cents` greater than zero, a `base_station_hours` figure greater than zero carrying at most two decimals, a `base_dry_weight_lbs` greater than zero, a `gvwr_lbs` strictly greater than `base_dry_weight_lbs`, an exact `required_wheelbase_in` greater than zero, an `electrical_service_amps` rating of either 30 or 50, a `fresh_water_capacity_gal` greater than zero, and optionally a `status` that defaults to `ACTIVE`."

    Design: Corner/rbac/roles_cannot_reach_other_roles_exclusive_operations
    """
    kit = build_tow_kit(with_booth=False)
    lot = create_component_lot(
        kit["supplier"]["id"],
        part_number="PN-AXLE",
        lot_code="LOT-X1",
        category="CHASSIS",
        quantity_received=10,
    )
    kit, order, build = tow_released_build(kit=kit, order_type="SOLD")
    inspection = schedule_pdi(build["id"])
    dealer_headers = make_dealer_principal_headers(kit["dealer"]["id"])
    order_version = read_order(order["id"])["version"]

    # Publishing a floor plan belongs to PlantAdmin alone.
    validate_error(
        api.create_floor_plan(SNEAK_FLOOR_PLAN, scheduler_headers),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    # The model code is unique across floor plans, so PlantAdmin still gets FP-SNEAK:
    # the refused call wrote nothing.
    validate_success(api.create_floor_plan(SNEAK_FLOOR_PLAN, plant_admin_headers), 201)

    # Slot reservation belongs to ProductionScheduler even on the dealer's own order,
    # so the role gate answers before the dealer-ownership gate could.
    validate_error(
        api.reserve_production_slot(
            order["id"],
            {
                "line_id": kit["line"]["id"],
                "slot_date": "2026-08-06T00:00:00Z",
                "expected_unit_order_version": order_version,
            },
            dealer_headers,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )

    # Grading an inspection belongs to QualityInspector.
    validate_error(
        api.complete_inspection(
            inspection["id"],
            {"defect_points": 0, "leak_detected": False},
            supervisor_headers,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    assert (
        validate_success(api.get_quality_inspection(inspection["id"], inspector_headers))[
            "status"
        ]
        == "SCHEDULED"
    )

    # Station advancement belongs to LineSupervisor.
    validate_error(
        api.advance_build(
            build["id"],
            {"to_station": "SIDEWALL_LAM", "station_hours_used": 6.00},
            inspector_headers,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    assert (
        validate_success(api.get_unit_build(build["id"], inspector_headers))[
            "current_station"
        ]
        == "CHASSIS_PREP"
    )

    # Drafting a recall campaign belongs to RecallCoordinator.
    validate_error(
        api.create_recall_campaign(
            {
                "supplier_id": kit["supplier"]["id"],
                "campaign_code": "RC-SNEAK",
                "part_number": "PN-AXLE",
                "lot_codes": ["LOT-X1"],
                "severity": "SAFETY",
            },
            warranty_admin_headers,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    campaigns, campaign_meta = validate_paginated(
        api.list_recall_campaigns(recall_coordinator_headers)
    )
    assert campaign_meta["total_count"] == 0
    assert campaigns == []
    lot_after_refusals = validate_success(
        api.get_component_lot(lot["id"], recall_coordinator_headers)
    )
    assert lot_after_refusals["status"] == "AVAILABLE"

    # A RecallCoordinator may remedy an installation but never record one.
    validate_error(
        api.create_component_installation(
            {
                "unit_build_id": build["id"],
                "component_lot_id": lot["id"],
                "station": "SIDEWALL_LAM",
                "quantity": 1,
            },
            recall_coordinator_headers,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    lot_final = validate_success(api.get_component_lot(lot["id"], plant_admin_headers))
    assert lot_final["quantity_available"] == 10
    assert_lot_counter_invariant(lot_final)

    # The role gate answers before path existence, so the refusal never reveals
    # whether that order identifier exists.
    validate_error(
        api.submit_order(NON_EXISTENT_UUID, plant_admin_headers),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )


def test_the_administrator_who_approved_a_claim_may_not_pay_it(
    api, warranty_admin_headers, warranty_admin_2_headers
):
    """PRD §2.11: "Two checks in this plant are not about which role acts but about which *person* acts, and both compare `X-User-ID` against an identifier the system recorded earlier. Both are reported as `ERR_SEGREGATION_OF_DUTIES` (409)."

    PRD §2.11: "The second governs warranty disbursement. When a `WarrantyAdministrator` pays an approved claim, their `X-User-ID` must differ from the claim's `approved_by_user_id`. The approver may not also pay."

    PRD §3.8: "Payment is the last step and the second duty split. A `WarrantyAdministrator` pays a claim whose `status` is `APPROVED`, driving it `APPROVED → PAID` and stamping `paid_by_user_id` from the acting `X-User-ID`, which must differ from `approved_by_user_id`."

    PRD §3.8: "Parts carry a handling uplift of 1500 basis points. Multiply `parts_cost_cents` by 11500, divide by 10000, and round half up to whole cents. That is `parts_reimbursement_cents`."

    PRD §3.8: "The schedule subtotal is `labor_reimbursement_cents` plus `parts_reimbursement_cents`."

    PRD §3.8: "The total paid to the dealer is the schedule subtotal plus `goodwill_authorized_cents` — under the in-warranty variant."

    PRD §3.8: "Approval drives `status` `SUBMITTED → APPROVED`, runs all seven waterfall steps in the pinned order and persists `labor_reimbursement_cents`, `parts_reimbursement_cents`, `authority_tier`, `goodwill_authorized_cents`, `total_reimbursement_cents`, and `supplier_chargeback_cents`, stamps `approved_by_user_id` from the acting `X-User-ID`, and adds the authorised goodwill to the dealer's `goodwill_used_cents`."

    Design: Corner/rbac/warranty_approver_must_not_also_pay_the_claim
    """
    floor_plan = create_floor_plan()
    dealer = create_dealer()
    delivered = inject_delivered_unit(dealer["id"], floor_plan["id"])
    claim = file_claim(
        dealer["id"],
        delivered["id"],
        "APPLIANCE",
        labor_hours=3.50,
        parts_cost_cents=68000,
        narrative="furnace blower seized",
    )

    approver_id = warranty_admin_headers["X-User-ID"]
    payer_id = warranty_admin_2_headers["X-User-ID"]

    approved = validate_success(
        api.decide_claim(claim["id"], {"decision": "APPROVED"}, warranty_admin_headers)
    )
    assert approved["status"] == "APPROVED"
    assert_cents(approved["total_reimbursement_cents"], 105500)
    assert_cents(approved["labor_reimbursement_cents"], 27300)
    assert_cents(approved["parts_reimbursement_cents"], 78200)
    assert approved["approved_by_user_id"] == approver_id

    # Both calls declare the same role, so the refusal is about the person and not
    # about the role: it is a 409 duty-split refusal, never a 403.
    assert (
        warranty_admin_headers["X-User-Role"] == warranty_admin_2_headers["X-User-Role"]
    )
    validate_error(
        api.pay_claim(claim["id"], warranty_admin_headers),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    unpaid = validate_success(api.get_warranty_claim(claim["id"], warranty_admin_headers))
    assert unpaid["status"] == "APPROVED"
    assert unpaid["paid_by_user_id"] is None

    paid = validate_success(api.pay_claim(claim["id"], warranty_admin_2_headers))
    assert paid["status"] == "PAID"
    assert paid["paid_by_user_id"] == payer_id
    assert paid["approved_by_user_id"] == approver_id
