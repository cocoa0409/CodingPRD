"""Endpoint-surface behaviour: reference-data CRUD, status actions, bulk expand,
cross-anchor claim listings, the computed supplier scorecard, the conditional
information request, and the filterable supply/quality collection reads.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_cents,
    assert_hours,
    assert_two_decimals,
    build_tow_kit,
    create_component_lot,
    create_dealer,
    create_floor_plan,
    create_supplier,
    draft_campaign,
    file_claim,
    inject_delivered_unit,
    install_pieces,
    make_dealer_principal_headers,
    open_campaign,
    read_build,
    schedule_booth_inspection,
    schedule_pdi,
    tow_build_at_station,
    tow_released_build,
    validate_error,
    validate_paginated,
    validate_success,
)

INSPECTOR_1_USER_ID = TEST_USERS["quality_inspector_headers"]["X-User-ID"]


def test_floor_plan_and_option_reads_and_edits_bump_version(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §3.1: "The plant derives `max_payload_lbs` as the gross vehicle weight rating minus the base dry weight, and re-derives it whenever the plan is edited."

    PRD §3.1: "A floor plan may later be repriced through `base_msrp_cents` or retired by setting `status` to `RETIRED`; either edit increments the plan's `version`, which invalidates the pinned reference on every already-submitted order that names it."
    PRD §3.1: "Repricing `price_cents` or setting `status` to `DISCONTINUED` increments the option's `version`, invalidating the matching pinned entry on every already-submitted order that selected it."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the row."

    Design: Corner/endpoints/floor_plan_and_option_crud_read_back_and_bump_version
    """
    created_plan = validate_success(
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
    assert created_plan["max_payload_lbs"] == 3000
    assert created_plan["version"] == 1
    assert created_plan["status"] == "ACTIVE"
    plan_id = created_plan["id"]

    created_option = validate_success(
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
    assert created_option["version"] == 1
    option_id = created_option["id"]

    # The ordering dealer may read the catalogue it orders from.
    dealer = create_dealer(dealer_code="D-ANY")
    read_back = validate_success(
        api.get_floor_plan(plan_id, make_dealer_principal_headers(dealer["id"]))
    )
    assert_cents(read_back["base_msrp_cents"], 8000000)
    assert_hours(read_back["base_station_hours"], "40.00")
    assert read_back["version"] == 1

    repriced = validate_success(
        api.patch_floor_plan(plan_id, {"base_msrp_cents": 8400000}, plant_admin_headers)
    )
    assert_cents(repriced["base_msrp_cents"], 8400000)
    assert repriced["version"] == 2
    assert repriced["max_payload_lbs"] == 3000

    retired = validate_success(
        api.patch_floor_plan(plan_id, {"status": "RETIRED"}, plant_admin_headers)
    )
    assert retired["status"] == "RETIRED"
    assert retired["version"] == 3
    assert_cents(retired["base_msrp_cents"], 8400000)

    option_repriced = validate_success(
        api.patch_option_item(option_id, {"price_cents": 120000}, plant_admin_headers)
    )
    assert_cents(option_repriced["price_cents"], 120000)
    assert option_repriced["version"] == 2
    assert option_repriced["amp_draw"] == 20

    # Retirement is a status, not a removal: the retired plan is still readable.
    still_there = validate_success(api.get_floor_plan(plan_id, scheduler_headers))
    assert still_there["status"] == "RETIRED"
    assert still_there["version"] == 3
    assert validate_success(api.get_option_item(option_id, scheduler_headers))["version"] == 2


def test_status_actions_move_dealer_booth_and_line(api, plant_admin_headers, scheduler_headers):
    """PRD §3.1: "A `PlantAdmin` may later flip a dealer's `status` between `ACTIVE` and `SUSPENDED`; a `SUSPENDED` dealer can no longer submit orders, reserve slots, request funding, be released to a line, or receive a shipment, and each of those attempts is rejected with `ERR_DEALER_SUSPENDED`."

    PRD §3.1: "A `PlantAdmin` may take a booth `DOWN`, after which new reservations are rejected with `ERR_BOOTH_NOT_OPEN` while already-`SCHEDULED` windows are left untouched."
    PRD §3.1: "A line may be paused and resumed by either a `PlantAdmin` or a `ProductionScheduler`; while `PAUSED` it blocks station advancement for every build occupying it with `ERR_LINE_NOT_RUNNING`, though slots already reserved on it keep their committed hours and continue to count toward capacity."
    PRD §3.3: "Sum the `daily_station_hour_capacity` of every commissioned line whose `status` is `RUNNING` or `PAUSED` — a paused line still counts toward the plant's nominal capacity — multiply by twenty working days per month, and round half up to two decimals: that is the plant's monthly hours."
    PRD §4: "Operations that modify an existing resource, drive a state transition, or read data return `200 OK`."

    Design: Corner/endpoints/status_action_endpoints_move_dealer_booth_and_line
    """
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
    booth = validate_success(
        api.create_test_booth(
            {
                "booth_code": "BOOTH-W",
                "booth_type": "WATER_TEST",
                "bay_count": 1,
                "turnaround_minutes": 30,
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
    assert dealer["status"] == "ACTIVE"
    assert booth["status"] == "OPEN"
    assert line["status"] == "RUNNING"

    suspended = validate_success(
        api.set_dealer_status(dealer["id"], {"status": "SUSPENDED"}, plant_admin_headers)
    )
    assert suspended["status"] == "SUSPENDED"
    assert_cents(suspended["floor_plan_credit_limit_cents"], 100000000)
    assert suspended["version"] == 2

    reinstated = validate_success(
        api.set_dealer_status(dealer["id"], {"status": "ACTIVE"}, plant_admin_headers)
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["version"] == 3

    booth_down = validate_success(
        api.set_test_booth_status(booth["id"], {"status": "DOWN"}, plant_admin_headers)
    )
    assert booth_down["status"] == "DOWN"
    assert booth_down["bay_count"] == 1

    line_paused = validate_success(
        api.set_production_line_status(line["id"], {"status": "PAUSED"}, scheduler_headers)
    )
    assert line_paused["status"] == "PAUSED"
    assert_hours(line_paused["daily_station_hour_capacity"], "240.00")

    # 240.00 hours a day over twenty working days is 4800.00 plant hours a month;
    # 1500 basis points of that is the dealer's entitlement even though the only
    # line in the plant is PAUSED.
    dealer_after = validate_success(api.get_dealer(dealer["id"], plant_admin_headers))
    assert_hours(dealer_after["entitlement_hours"], "720.00")


def test_campaign_expand_labels_two_additional_lots_in_one_write(
    api, plant_admin_headers, recall_coordinator_headers
):
    """PRD §3.9: "The campaign's `lot_codes` becomes the union of the old scope and the additional codes, and hops one through three run again for lots newly brought into scope only."

    PRD §3.9: "Hop one freezes supply. Every matching lot moves to `QUARANTINED` — from `AVAILABLE` or from `DEPLETED` alike — by adding its remaining `quantity_available` to its `quantity_quarantined` and then setting `quantity_available` to zero."
    PRD §3.9: "Every installation drawing from those lots whose `status` is `INSTALLED` moves `INSTALLED → RECALL_AFFECTED`, records the campaign as its `recall_campaign_id`, and increments the campaign's `affected_installation_count`. Each such labelling sets `recall_hold` to true on the build that received the pieces, which immediately blocks that build from advancing another station."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the row."

    Design: Corner/endpoints/campaign_expand_adds_two_lots_in_one_bulk_action
    """
    kit = build_tow_kit(
        with_booth=False,
        supplier={
            "supplier_code": "SUP-C",
            "name": "Cascade Components",
            "component_categories": ["APPLIANCE", "CHASSIS"],
        },
    )
    lots = [
        create_component_lot(
            kit["supplier"]["id"],
            part_number="PN-FRIDGE",
            lot_code=code,
            category="APPLIANCE",
            quantity_received=10,
        )
        for code in ("L-1", "L-2", "L-3")
    ]
    kit, _order, build = tow_build_at_station("ROUGH_IN", kit=kit)
    for lot in lots:
        install_pieces(build["id"], lot["id"], "ROUGH_IN", 1)

    campaign = draft_campaign(
        kit["supplier"]["id"],
        campaign_code="RC-FRIDGE",
        part_number="PN-FRIDGE",
        lot_codes=["L-1"],
        severity="COMPLIANCE",
    )
    opened = open_campaign(campaign["id"])
    assert opened["affected_installation_count"] == 1
    assert read_build(build["id"])["recall_hold"] is True

    expanded = validate_success(
        api.expand_recall_campaign(
            campaign["id"],
            {
                "additional_lot_codes": ["L-2", "L-3"],
                "expected_recall_campaign_version": opened["version"],
            },
            recall_coordinator_headers,
        )
    )
    assert expanded["affected_installation_count"] == 3
    assert list(expanded["lot_codes"]) == ["L-1", "L-2", "L-3"]
    assert expanded["version"] == 3

    rows, meta = validate_paginated(
        api.list_component_installations(
            recall_coordinator_headers,
            params={"recall_campaign_id": campaign["id"], "status": "RECALL_AFFECTED"},
        )
    )
    assert meta["total_count"] == 3
    assert rows[0]["status"] == "RECALL_AFFECTED"

    third_lot = validate_success(
        api.get_component_lot(lots[2]["id"], recall_coordinator_headers)
    )
    assert third_lot["status"] == "QUARANTINED"
    assert third_lot["quantity_quarantined"] == 9
    assert third_lot["quantity_available"] == 0

    assert validate_success(api.get_unit_build(build["id"], plant_admin_headers))["recall_hold"] is True


def test_warranty_claims_are_reachable_from_dealer_build_and_lot(api, warranty_admin_headers):
    """PRD §3.8: "Claims are listable with filters on `dealer_id`, `unit_build_id`, `component_lot_id`, `status`, and `claim_type`."

    PRD §2.1: "When `X-User-Role` is `DealerPrincipal`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a dealer compare that resource's dealer reference to `X-User-ID`."
    PRD §3.8: "The claim's `dealer_id` is taken from the submitting principal's `X-User-ID` and never from the body; filing against a build belonging to another dealer is `ERR_DEALER_SCOPE_VIOLATION`."
    PRD §2.3: "List results are ordered by `created_at` ascending unless a subsection below says otherwise, and that default applies to every collection in the API."

    Design: Corner/endpoints/warranty_claims_are_reachable_from_dealer_build_and_lot
    """
    supplier = create_supplier(
        supplier_code="SUP-C", name="Cascade Components", component_categories=["APPLIANCE"]
    )
    lot = create_component_lot(
        supplier["id"],
        part_number="PN-FRIDGE",
        lot_code="L-1",
        category="APPLIANCE",
        quantity_received=10,
    )
    floor_plan = create_floor_plan(model_code="FP-TOW")
    dealer_a = create_dealer(dealer_code="D-A", region="CENTRAL")
    dealer_b = create_dealer(dealer_code="D-B", region="EAST")
    build_a1 = inject_delivered_unit(dealer_a["id"], floor_plan["id"])
    build_a2 = inject_delivered_unit(dealer_a["id"], floor_plan["id"])
    build_b1 = inject_delivered_unit(dealer_b["id"], floor_plan["id"])

    claim_a1 = file_claim(
        dealer_a["id"],
        build_a1["id"],
        "APPLIANCE",
        labor_hours=2.00,
        parts_cost_cents=0,
        narrative="refrigerator cooling fault",
        component_lot_id=lot["id"],
    )
    claim_a2 = file_claim(
        dealer_a["id"],
        build_a2["id"],
        "ELECTRICAL",
        labor_hours=1.00,
        parts_cost_cents=0,
        narrative="converter fan noise",
    )
    claim_b1 = file_claim(
        dealer_b["id"],
        build_b1["id"],
        "PLUMBING",
        labor_hours=1.50,
        parts_cost_cents=0,
        narrative="grey tank valve leak",
    )

    by_dealer, by_dealer_meta = validate_paginated(
        api.list_warranty_claims(warranty_admin_headers, params={"dealer_id": dealer_a["id"]})
    )
    assert by_dealer_meta["total_count"] == 2
    assert by_dealer[0]["id"] == claim_a1["id"]
    assert [row["id"] for row in by_dealer] == [claim_a1["id"], claim_a2["id"]]

    by_build, by_build_meta = validate_paginated(
        api.list_warranty_claims(warranty_admin_headers, params={"unit_build_id": build_a1["id"]})
    )
    assert by_build_meta["total_count"] == 1
    assert by_build[0]["id"] == claim_a1["id"]

    by_lot, by_lot_meta = validate_paginated(
        api.list_warranty_claims(warranty_admin_headers, params={"component_lot_id": lot["id"]})
    )
    assert by_lot_meta["total_count"] == 1
    assert by_lot[0]["id"] == claim_a1["id"]

    as_dealer_b, as_dealer_b_meta = validate_paginated(
        api.list_warranty_claims(make_dealer_principal_headers(dealer_b["id"]))
    )
    assert as_dealer_b_meta["total_count"] == 1
    assert as_dealer_b[0]["id"] == claim_b1["id"]

    _all_rows, all_meta = validate_paginated(api.list_warranty_claims(warranty_admin_headers))
    assert all_meta["total_count"] == 3


def test_supplier_scorecard_recomputes_both_variants_and_persists_the_rolling_one(
    api, plant_admin_headers, recall_coordinator_headers
):
    """PRD §3.1: "On registration a supplier's derived trust fields start clean: `quality_score` is `100.00`, `supplier_status` is `ACTIVE`, `open_recall_count` is 0, and `penalty_event_count` is 0."

    PRD §3.9: "The campaign starts at `status` `DRAFT` with `opened_at` null, all three counters — `affected_installation_count`, `remedied_installation_count`, and `quarantined_piece_count` — at zero, and `ship_stop` derived from severity: it is true exactly when `severity` is `SAFETY` and false for `COMPLIANCE` and `ADVISORY`."
    PRD §3.9: "It requires at least one component lot to be in scope — matching means the lot's `supplier_id` equals the campaign's, the lot's `part_number` equals the campaign's, and the lot's `lot_code` is one of the campaign's `lot_codes`."
    PRD §3.9: "The event set is the same for both: every campaign of that supplier whose `status` is `OPEN` or `CLOSED` and whose `opened_at` is not null, weighted by severity at 15.0 for `SAFETY`, 10.0 for `COMPLIANCE`, and 4.0 for `ADVISORY`, timestamped at `opened_at`; plus every `APPROVED` or `PAID` warranty claim whose component lot belongs to that supplier and whose `supplier_chargeback_cents` is positive, weighted at 2.0 and timestamped at the claim's `created_at`."
    PRD §3.9: "Under the **rolling** variant there is a hard 90-day cutoff and no decay: the penalty is the sum of the weights of events whose age is strictly less than 90 days."
    PRD §3.9: "Under the **lifetime** variant nothing is ever dropped: events younger than 90 days count at full weight, and events at or past 90 days keep half their weight, so the lifetime figure is at or below the rolling figure whenever any event has aged out."
    PRD §3.9: "`Supplier.quality_score` always holds the **rolling** figure, and `supplier_status` is derived from it alone: a score of 70.00 or more is `ACTIVE`, a score from 50.00 up to but not including 70.00 is `PROBATION`, and anything below 50.00 is `SUSPENDED`."
    PRD §3.9: "The read is not passive: it recomputes and persists the supplier's `quality_score` and `supplier_status` from the rolling variant at the current logical clock, so a scorecard read after a clock advance is what promotes a supplier whose old penalties have finally aged out of the window."
    PRD §3.9: "**Closing** a campaign drives `status` `OPEN → CLOSED` and requires that `remedied_installation_count` equal `affected_installation_count` — an unfinished campaign is refused with `ERR_CAMPAIGN_NOT_CLOSEABLE`."
    PRD §3.9: "Closing decrements the supplier's `open_recall_count` by one and rescores it, but the penalty event itself survives the close: a closed campaign still weighs on the trust score."

    Design: Corner/endpoints/supplier_scorecard_is_a_computed_read_of_both_variants
    """
    supplier = validate_success(
        api.create_supplier(
            {
                "supplier_code": "SUP-C",
                "name": "Cascade Components",
                "component_categories": ["APPLIANCE"],
            },
            plant_admin_headers,
        ),
        201,
    )
    assert_two_decimals(supplier["quality_score"], "100.00")
    assert supplier["supplier_status"] == "ACTIVE"

    # Each campaign scopes one real lot of its own, so each open is legal and no
    # installation exists anywhere: the campaigns are pure penalty events.
    campaigns = []
    for index, (code, lot_code, severity) in enumerate(
        (("RC-1", "L-1", "COMPLIANCE"), ("RC-2", "L-2", "SAFETY"), ("RC-3", "L-3", "SAFETY")),
        start=1,
    ):
        create_component_lot(
            supplier["id"],
            part_number="PN-FRIDGE",
            lot_code=lot_code,
            category="APPLIANCE",
            quantity_received=index,
        )
        campaigns.append(
            draft_campaign(
                supplier["id"],
                campaign_code=code,
                part_number="PN-FRIDGE",
                lot_codes=[lot_code],
                severity=severity,
            )
        )

    card_0 = validate_success(api.get_supplier_scorecard(supplier["id"], plant_admin_headers))
    assert_two_decimals(card_0["rolling_quality_score"], "100.00")
    assert_two_decimals(card_0["lifetime_quality_score"], "100.00")
    assert card_0["supplier_status"] == "ACTIVE"
    assert card_0["open_recall_count"] == 0
    assert card_0["penalty_event_count"] == 0

    open_campaign(campaigns[0]["id"])
    open_campaign(campaigns[1]["id"])

    card_2 = validate_success(api.get_supplier_scorecard(supplier["id"], plant_admin_headers))
    assert_two_decimals(card_2["rolling_quality_score"], "75.00")
    assert_two_decimals(card_2["lifetime_quality_score"], "75.00")
    assert card_2["supplier_status"] == "ACTIVE"
    assert card_2["open_recall_count"] == 2
    assert card_2["penalty_event_count"] == 2

    open_campaign(campaigns[2]["id"])

    card_3 = validate_success(api.get_supplier_scorecard(supplier["id"], plant_admin_headers))
    assert_two_decimals(card_3["rolling_quality_score"], "60.00")
    assert_two_decimals(card_3["lifetime_quality_score"], "60.00")
    assert card_3["supplier_status"] == "PROBATION"
    assert card_3["open_recall_count"] == 3

    closed = validate_success(
        api.close_recall_campaign(campaigns[0]["id"], recall_coordinator_headers)
    )
    assert closed["status"] == "CLOSED"

    stored = validate_success(api.get_supplier(supplier["id"], plant_admin_headers))
    assert_two_decimals(stored["quality_score"], "60.00")
    assert stored["supplier_status"] == "PROBATION"
    assert stored["open_recall_count"] == 2


def test_information_requests_are_capped_at_two_and_pay_needs_an_approval(
    api, plant_admin_headers, warranty_admin_headers
):
    """PRD §3.8: "Each such action increments `info_request_count`, and the plant allows at most two: a third request against the same claim is refused with `ERR_INFO_REQUEST_LIMIT_REACHED`."

    PRD §3.8: "The owning dealer answers by resubmitting, driving `status` `INFO_REQUESTED → SUBMITTED`, optionally supplying revised `labor_hours`, `parts_cost_cents`, and `narrative` — any supplied value replaces the stored one, any omitted value stands."
    PRD §3.8: "Requesting information, resubmitting, or deciding from a status that does not allow it is refused with `ERR_CLAIM_NOT_DECIDABLE`."
    PRD §3.8: "A `WarrantyAdministrator` pays a claim whose `status` is `APPROVED`, driving it `APPROVED → PAID` and stamping `paid_by_user_id` from the acting `X-User-ID`, which must differ from `approved_by_user_id`."
    PRD §2.8: "The generic code is `ERR_INVALID_STATE` (409), but a specific code takes its place wherever one is defined: `ERR_ORDER_NOT_SUBMITTABLE`, `ERR_ORDER_NOT_SLOTTABLE`, `ERR_ORDER_ALREADY_MATCHED`, `ERR_CHASSIS_NOT_MATCHED`, `ERR_DEALER_SUSPENDED`, `ERR_FLOOR_PLAN_RETIRED`, `ERR_STATION_SEQUENCE_VIOLATION`, `ERR_LINE_NOT_RUNNING`, `ERR_BOOTH_NOT_OPEN`, `ERR_INSPECTION_STATION_MISMATCH`, `ERR_LOT_QUANTITY_INSUFFICIENT`, `ERR_CLAIM_NOT_DECIDABLE`, `ERR_INFO_REQUEST_LIMIT_REACHED`, `ERR_CAMPAIGN_NOT_CLOSEABLE`, `ERR_PAYMENT_EXCEEDS_PRINCIPAL`, and `ERR_QUALITY_HOLD`."
    PRD §3.8: "The billable hours are the lesser of the claimed `labor_hours` and 8.0 hours."
    PRD §3.8: "The `authority_tier` is chosen **from** that subtotal, so it can never be settled before labour and parts are known: a subtotal at or below 150000 cents is `TIER_A`, a subtotal above that but at or below 750000 cents is `TIER_B`, and anything above 750000 cents is `TIER_C`."
    PRD §3.8: "The total paid to the dealer is the schedule subtotal plus `goodwill_authorized_cents` — under the in-warranty variant."

    Design: Corner/endpoints/warranty_info_requests_are_a_conditional_action_capped_at_two
    """
    floor_plan = create_floor_plan(model_code="FP-TOW")
    dealer = create_dealer(dealer_code="D-TOW")
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    build = inject_delivered_unit(dealer["id"], floor_plan["id"])

    claim = validate_success(
        api.create_warranty_claim(
            {
                "unit_build_id": build["id"],
                "claim_type": "APPLIANCE",
                "labor_hours": 1.00,
                "parts_cost_cents": 0,
                "narrative": "range igniter fault",
            },
            dealer_headers,
        ),
        201,
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["info_request_count"] == 0
    claim_id = claim["id"]

    validate_error(
        api.pay_claim(claim_id, warranty_admin_headers), ApiErrorId.ERR_CLAIM_NOT_DECIDABLE
    )

    first_request = validate_success(
        api.request_claim_info(
            claim_id,
            warranty_admin_headers,
            {"info_request_note": "photographs of the burner assembly, please"},
        )
    )
    assert first_request["status"] == "INFO_REQUESTED"
    assert first_request["info_request_count"] == 1

    first_answer = validate_success(
        api.resubmit_claim(
            claim_id,
            {"labor_hours": 2.00, "narrative": "range igniter fault, photographs attached"},
            dealer_headers,
        )
    )
    assert first_answer["status"] == "SUBMITTED"
    assert_hours(first_answer["labor_hours"], "2.00")

    second_request = validate_success(
        api.request_claim_info(
            claim_id, warranty_admin_headers, {"info_request_note": "serial plate photograph, please"}
        )
    )
    assert second_request["status"] == "INFO_REQUESTED"
    assert second_request["info_request_count"] == 2

    second_answer = validate_success(
        api.resubmit_claim(
            claim_id, {"narrative": "range igniter fault, serial plate attached"}, dealer_headers
        )
    )
    assert second_answer["status"] == "SUBMITTED"

    validate_error(
        api.request_claim_info(
            claim_id, warranty_admin_headers, {"info_request_note": "one more thing"}
        ),
        ApiErrorId.ERR_INFO_REQUEST_LIMIT_REACHED,
    )

    approved = validate_success(
        api.decide_claim(claim_id, {"decision": "APPROVED"}, warranty_admin_headers)
    )
    assert approved["status"] == "APPROVED"
    assert approved["authority_tier"] == "TIER_A"
    assert_cents(approved["total_reimbursement_cents"], 15600)

    validate_error(
        api.decide_claim(
            claim_id, {"decision": "DENIED", "denial_reason": "changed my mind"}, warranty_admin_headers
        ),
        ApiErrorId.ERR_CLAIM_NOT_DECIDABLE,
    )
    assert validate_success(api.get_warranty_claim(claim_id, plant_admin_headers))["status"] == "APPROVED"


def test_supply_and_quality_collection_reads_are_filterable(
    api,
    plant_admin_headers,
    supervisor_headers,
    inspector_headers,
    inspector_2_headers,
    recall_coordinator_headers,
):
    """PRD §3.1: "Chassis receipts may be narrowed by `supplier_id`, `matched_unit_order_id`, `status`, and `chassis_class`; component lots by `supplier_id`, `part_number`, `lot_code`, and `status`."

    PRD §3.1: "On receipt `quantity_available` equals `quantity_received`, `quantity_installed` is 0, `quantity_quarantined` is 0, and `status` is `AVAILABLE`."
    PRD §3.6: "Inspections are listable with filters on `unit_build_id`, `test_booth_id`, `inspection_type`, `status`, and `result`."
    PRD §3.6: "The scheduled inspection records `inspector_user_id` from the acting `X-User-ID`, starts at `status` `SCHEDULED` with `result` null, `defect_points` 0, `leak_detected` false, and `completed_by_user_id` null."
    PRD §3.6: "A `WATER_TEST` or `FUNCTIONAL` inspection consumes a physical bay and therefore requires a `test_booth_id`, a `window_start`, and a `window_end`; a `PDI` inspection happens at the coach and requires all three to be omitted."
    PRD §3.9: "Campaigns are listable with filters on `supplier_id`, `part_number`, `severity`, and `status`."
    PRD §3.9: "The campaign starts at `status` `DRAFT` with `opened_at` null, all three counters — `affected_installation_count`, `remedied_installation_count`, and `quarantined_piece_count` — at zero, and `ship_stop` derived from severity: it is true exactly when `severity` is `SAFETY` and false for `COMPLIANCE` and `ADVISORY`. Nothing is quarantined while the campaign is a draft."
    PRD §2.3: "`limit` controls page size: it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100."
    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of rows matching the supplied filters before pagination is applied, and `has_more` is true exactly when rows matching the filters remain beyond the returned page."
    PRD §2.3: "List results are ordered by `created_at` ascending unless a subsection below says otherwise, and that default applies to every collection in the API."

    Design: Corner/endpoints/supply_and_quality_collection_reads_are_filterable
    """
    appliance_supplier = create_supplier(
        supplier_code="SUP-AP", name="Northline Appliance", component_categories=["APPLIANCE"]
    )
    lot_a1 = create_component_lot(
        appliance_supplier["id"],
        part_number="PN-FRIDGE",
        lot_code="LOT-A1",
        category="APPLIANCE",
        quantity_received=10,
    )
    lot_a2 = create_component_lot(
        appliance_supplier["id"],
        part_number="PN-FRIDGE",
        lot_code="LOT-A2",
        category="APPLIANCE",
        quantity_received=6,
    )
    kit = build_tow_kit(
        supplier={
            "supplier_code": "SUP-CH",
            "name": "Cascade Chassis Works",
            "component_categories": ["CHASSIS"],
        }
    )
    kit, _order, build = tow_released_build(kit=kit, order_type="SOLD")

    pdi = schedule_pdi(build["id"], headers=inspector_headers)
    water_test = schedule_booth_inspection(
        build["id"],
        kit["booth"]["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        headers=inspector_2_headers,
    )
    campaign = draft_campaign(
        appliance_supplier["id"],
        campaign_code="RC-1",
        part_number="PN-FRIDGE",
        lot_codes=["LOT-A2"],
        severity="ADVISORY",
    )

    lots, lots_meta = validate_paginated(
        api.list_component_lots(
            plant_admin_headers,
            params={"supplier_id": appliance_supplier["id"], "status": "AVAILABLE"},
        )
    )
    assert lots_meta["total_count"] == 2
    assert lots[0]["lot_code"] == "LOT-A1"

    one_lot, one_lot_meta = validate_paginated(
        api.list_component_lots(recall_coordinator_headers, params={"lot_code": "LOT-A2"})
    )
    assert one_lot_meta["total_count"] == 1
    assert one_lot[0]["id"] == lot_a2["id"]
    assert one_lot[0]["quantity_available"] == 6
    assert lot_a1["quantity_available"] == 10

    inspections, inspections_meta = validate_paginated(
        api.list_quality_inspections(inspector_headers, params={"unit_build_id": build["id"]})
    )
    assert inspections_meta["total_count"] == 2
    assert inspections[0]["id"] == pdi["id"]

    wet, wet_meta = validate_paginated(
        api.list_quality_inspections(
            supervisor_headers,
            params={
                "unit_build_id": build["id"],
                "inspection_type": "WATER_TEST",
                "status": "SCHEDULED",
            },
        )
    )
    assert wet_meta["total_count"] == 1
    assert wet[0]["id"] == water_test["id"]
    assert wet[0]["test_booth_id"] == kit["booth"]["id"]

    one_inspection = validate_success(api.get_quality_inspection(pdi["id"], inspector_headers))
    assert one_inspection["inspection_type"] == "PDI"
    assert one_inspection["test_booth_id"] is None
    assert one_inspection["inspector_user_id"] == INSPECTOR_1_USER_ID
    assert one_inspection["result"] is None

    drafts, drafts_meta = validate_paginated(
        api.list_recall_campaigns(
            recall_coordinator_headers,
            params={"supplier_id": appliance_supplier["id"], "status": "DRAFT"},
        )
    )
    assert drafts_meta["total_count"] == 1
    assert drafts[0]["id"] == campaign["id"]
    assert drafts[0]["ship_stop"] is False

    empty, empty_meta = validate_paginated(
        api.list_recall_campaigns(plant_admin_headers, params={"status": "OPEN"})
    )
    assert empty == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False
    assert empty_meta["limit"] == 10
