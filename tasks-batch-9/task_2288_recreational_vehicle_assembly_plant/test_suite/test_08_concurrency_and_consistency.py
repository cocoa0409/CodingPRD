"""Version pinning on the two write endpoints of PRD §2.7, filtered paging over
PRD §2.3, and the read-your-write behaviour of the derived dealer position."""
from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_hours,
    assert_lot_counter_invariant,
    create_component_lot,
    create_dealer,
    create_floor_plan,
    create_option_item,
    create_order,
    create_production_line,
    create_supplier,
    file_claim,
    inject_delivered_unit,
    make_dealer_principal_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

TOW_FLOOR_PLAN = {
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
}


def test_a_consumed_version_is_refused_on_slot_reservation_and_campaign_expansion(
    api, plant_admin_headers, scheduler_headers, recall_coordinator_headers
):
    """PRD §2.7: "`POST /unit-orders/{id}/production-slots` requires `expected_unit_order_version`, carrying the client's last observed `version` of the target `UnitOrder`. If that value does not equal the order's current `version`, the reservation is rejected with `ERR_STALE_UNIT_ORDER_VERSION` (412)."

    PRD §2.7: "`POST /recall-campaigns/{id}/expand` requires `expected_recall_campaign_version`, carrying the client's last observed `version` of the target `RecallCampaign`. If that value does not equal the campaign's current `version`, the expansion is rejected with `ERR_STALE_RECALL_CAMPAIGN_VERSION` (412)."

    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the row."

    PRD §2.8: "This band sits deliberately **after** the state gate, so reserving a slot for a `CANCELLED` order returns 409 even when the supplied version is also stale; and deliberately **before** every business rule, so a stale caller is never told about a capacity or credit problem it cannot yet see."

    PRD §3.3: "Re-slotting an order that already holds a reservation is therefore legitimate, and the mechanics of it matter: **the order's prior `RESERVED` slot transitions `RESERVED → RELEASED` first, before the capacity checks run**, so the hours it was holding are freed and excluded from every count the new request is measured against."

    PRD §3.3: "The created slot is stamped `RESERVED` with `station_hours_committed` copied from the order's `required_station_hours` at the moment of reservation, a one-based `sequence_position` equal to the day bucket's occupied-unit count plus one (which is the coach's build order on that line that day), and an `expires_at` exactly 72 hours after the slot's `created_at`."

    PRD §3.9: "Every matching lot moves to `QUARANTINED` — from `AVAILABLE` or from `DEPLETED` alike — by adding its remaining `quantity_available` to its `quantity_quarantined` and then setting `quantity_available` to zero."

    PRD §3.9: "**Expanding** it keeps `status` at `OPEN` and requires an `additional_lot_codes` array containing at least one code not already present in `lot_codes`, alongside the `expected_recall_campaign_version` demanded by §2.7."

    PRD §3.9: "The campaign's `lot_codes` becomes the union of the old scope and the additional codes, and hops one through three run again for lots newly brought into scope only."

    Design: Corner/cross-cutting complexity layers/stale_expected_versions_are_rejected_on_both_occ_write_endpoints
    """
    appliance_supplier = create_supplier(
        supplier_code="SUP-AP",
        name="Northline Appliance",
        component_categories=["APPLIANCE"],
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
    floor_plan = create_floor_plan(**TOW_FLOOR_PLAN)
    option = create_option_item()
    dealer = create_dealer()
    line = create_production_line()
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="SOLD",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )

    submitted = validate_success(api.submit_order(order["id"], dealer_headers))
    order_version_a = submitted["version"]
    assert order_version_a == 2
    first_slot = validate_success(
        api.reserve_production_slot(
            order["id"],
            {
                "line_id": line["id"],
                "slot_date": "2026-08-05T00:00:00Z",
                "expected_unit_order_version": order_version_a,
            },
            scheduler_headers,
        ),
        201,
    )
    assert first_slot["sequence_position"] == 1

    # Replaying the consumed order version is refused, and supersedes nothing.
    validate_error(
        api.reserve_production_slot(
            order["id"],
            {
                "line_id": line["id"],
                "slot_date": "2026-08-06T00:00:00Z",
                "expected_unit_order_version": order_version_a,
            },
            scheduler_headers,
        ),
        ApiErrorId.ERR_STALE_UNIT_ORDER_VERSION,
    )
    held_slot = validate_success(api.get_production_slot(first_slot["id"], scheduler_headers))
    assert held_slot["status"] == "RESERVED"
    assert held_slot["slot_date"].startswith("2026-08-05")

    # A refreshed read lets the same reservation through.
    order_version_b = validate_success(
        api.get_unit_order(order["id"], scheduler_headers)
    )["version"]
    assert order_version_b == 3
    second_slot = validate_success(
        api.reserve_production_slot(
            order["id"],
            {
                "line_id": line["id"],
                "slot_date": "2026-08-06T00:00:00Z",
                "expected_unit_order_version": order_version_b,
            },
            scheduler_headers,
        ),
        201,
    )
    assert second_slot["sequence_position"] == 1
    assert second_slot["slot_date"].startswith("2026-08-06")
    superseded_slot = validate_success(
        api.get_production_slot(first_slot["id"], scheduler_headers)
    )
    assert superseded_slot["status"] == "RELEASED"
    assert validate_success(api.get_unit_order(order["id"], scheduler_headers))["version"] == 4

    # The same three beats on the campaign endpoint.
    campaign = validate_success(
        api.create_recall_campaign(
            {
                "supplier_id": appliance_supplier["id"],
                "campaign_code": "RC-FRIDGE",
                "part_number": "PN-FRIDGE",
                "lot_codes": ["LOT-A1"],
                "severity": "ADVISORY",
            },
            recall_coordinator_headers,
        ),
        201,
    )
    campaign_version_a = campaign["version"]
    assert campaign_version_a == 1
    opened = validate_success(
        api.open_recall_campaign(campaign["id"], recall_coordinator_headers)
    )
    assert opened["status"] == "OPEN"

    validate_error(
        api.expand_recall_campaign(
            campaign["id"],
            {
                "additional_lot_codes": ["LOT-A2"],
                "expected_recall_campaign_version": campaign_version_a,
            },
            recall_coordinator_headers,
        ),
        ApiErrorId.ERR_STALE_RECALL_CAMPAIGN_VERSION,
    )
    unexpanded = validate_success(
        api.get_recall_campaign(campaign["id"], recall_coordinator_headers)
    )
    assert unexpanded["lot_codes"] == ["LOT-A1"]

    campaign_version_b = unexpanded["version"]
    assert campaign_version_b == 2
    expanded = validate_success(
        api.expand_recall_campaign(
            campaign["id"],
            {
                "additional_lot_codes": ["LOT-A2"],
                "expected_recall_campaign_version": campaign_version_b,
            },
            recall_coordinator_headers,
        )
    )
    assert expanded["version"] == 3
    assert expanded["lot_codes"] == ["LOT-A1", "LOT-A2"]
    assert expanded["quarantined_piece_count"] == 16

    # The just-refreshed version went stale the moment that expansion landed. The
    # additional code is one no lot in scope carries, so the version is the only defect.
    validate_error(
        api.expand_recall_campaign(
            campaign["id"],
            {
                "additional_lot_codes": ["LOT-A3"],
                "expected_recall_campaign_version": campaign_version_b,
            },
            recall_coordinator_headers,
        ),
        ApiErrorId.ERR_STALE_RECALL_CAMPAIGN_VERSION,
    )
    frozen_a2 = validate_success(api.get_component_lot(lot_a2["id"], plant_admin_headers))
    assert frozen_a2["quantity_quarantined"] == 6
    assert_lot_counter_invariant(frozen_a2)
    frozen_a1 = validate_success(api.get_component_lot(lot_a1["id"], plant_admin_headers))
    assert frozen_a1["quantity_quarantined"] == 10
    assert_lot_counter_invariant(frozen_a1)


def test_claim_listing_pages_a_three_filter_query_and_recounts_after_a_decision(
    api, warranty_admin_headers
):
    """PRD §2.3: "`limit` controls page size: it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100."

    PRD §2.3: "`offset` is the zero-based index of the first row returned and defaults to 0."

    PRD §2.3: "List results are ordered by `created_at` ascending unless a subsection below says otherwise, and that default applies to every collection in the API."

    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of rows matching the supplied filters before pagination is applied, and `has_more` is true exactly when rows matching the filters remain beyond the returned page."

    PRD §3.8: "Claims are listable with filters on `dealer_id`, `unit_build_id`, `component_lot_id`, `status`, and `claim_type`."

    PRD §3.8: "The claim starts at `status` `SUBMITTED` with `denial_reason` null, `info_request_count` 0, `resubmission_count` 0, and both `approved_by_user_id` and `paid_by_user_id` null."

    PRD §2.1: "When `X-User-Role` is `DealerPrincipal`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a dealer compare that resource's dealer reference to `X-User-ID`."

    Design: Corner/cross-cutting complexity layers/warranty_claim_listing_combines_three_filters_with_offset_paging
    """
    floor_plan = create_floor_plan(**TOW_FLOOR_PLAN)
    dealer_a = create_dealer(
        dealer_code="D-A",
        region="CENTRAL",
        allocation_share_bp=1000,
        floor_plan_credit_limit_cents=100000000,
        goodwill_budget_cents=500000,
    )
    dealer_b = create_dealer(
        dealer_code="D-B",
        region="EAST",
        allocation_share_bp=1000,
        floor_plan_credit_limit_cents=100000000,
        goodwill_budget_cents=500000,
    )
    builds_a = [
        inject_delivered_unit(dealer_a["id"], floor_plan["id"])["id"] for _ in range(5)
    ]
    build_b = inject_delivered_unit(dealer_b["id"], floor_plan["id"])["id"]

    appliance_1 = file_claim(
        dealer_a["id"], builds_a[0], "APPLIANCE", narrative="furnace fault one"
    )
    appliance_2 = file_claim(
        dealer_a["id"], builds_a[1], "APPLIANCE", narrative="furnace fault two"
    )
    appliance_3 = file_claim(
        dealer_a["id"], builds_a[2], "APPLIANCE", narrative="furnace fault three"
    )
    structural_1 = file_claim(
        dealer_a["id"], builds_a[3], "STRUCTURAL", narrative="roof seam one"
    )
    structural_2 = file_claim(
        dealer_a["id"], builds_a[4], "STRUCTURAL", narrative="roof seam two"
    )
    other_dealer_claim = file_claim(
        dealer_b["id"], build_b, "APPLIANCE", narrative="other dealer furnace"
    )

    filtered = {
        "dealer_id": dealer_a["id"],
        "claim_type": "APPLIANCE",
        "status": "SUBMITTED",
    }
    excluded_ids = {structural_1["id"], structural_2["id"], other_dealer_claim["id"]}

    page_1, meta_1 = validate_paginated(
        api.list_warranty_claims(
            warranty_admin_headers, params={**filtered, "limit": 2, "offset": 0}
        )
    )
    assert meta_1["total_count"] == 3
    assert meta_1["has_more"] is True
    assert meta_1["limit"] == 2
    assert meta_1["offset"] == 0
    assert len(page_1) == 2
    assert page_1[0]["id"] == appliance_1["id"]

    page_2, meta_2 = validate_paginated(
        api.list_warranty_claims(
            warranty_admin_headers, params={**filtered, "limit": 2, "offset": 2}
        )
    )
    assert meta_2["total_count"] == 3
    assert meta_2["has_more"] is False
    assert len(page_2) == 1
    assert page_2[0]["id"] == appliance_3["id"]

    page_1_ids = [row["id"] for row in page_1]
    page_2_ids = [row["id"] for row in page_2]
    assert set(page_1_ids).isdisjoint(page_2_ids)
    assert set(page_1_ids + page_2_ids) == {
        appliance_1["id"],
        appliance_2["id"],
        appliance_3["id"],
    }
    assert excluded_ids.isdisjoint(page_1_ids + page_2_ids)

    approved = validate_success(
        api.decide_claim(
            appliance_1["id"], {"decision": "APPROVED"}, warranty_admin_headers
        )
    )
    assert approved["status"] == "APPROVED"

    page_3, meta_3 = validate_paginated(
        api.list_warranty_claims(
            warranty_admin_headers, params={**filtered, "limit": 2, "offset": 0}
        )
    )
    assert meta_3["total_count"] == 2
    assert meta_3["has_more"] is False
    assert page_3[0]["id"] == appliance_2["id"]

    dealer_wide, meta_4 = validate_paginated(
        api.list_warranty_claims(warranty_admin_headers, params={"dealer_id": dealer_a["id"]})
    )
    assert meta_4["total_count"] == 5
    assert meta_4["limit"] == 10
    assert meta_4["offset"] == 0
    assert len(dealer_wide) == 5

    own_rows, meta_5 = validate_paginated(
        api.list_warranty_claims(make_dealer_principal_headers(dealer_b["id"]))
    )
    assert meta_5["total_count"] == 1
    assert own_rows[0]["id"] == other_dealer_claim["id"]


def test_every_derived_dealer_position_is_current_in_the_write_response_and_the_next_read(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §3.1: "A dealer's derived position — `financed_exposure_cents`, `credit_utilization_bp`, `credit_status` (initialised to `GOOD_STANDING`), `goodwill_used_cents`, `entitlement_hours`, `allocation_hours_consumed`, and `allocation_slots_reserved` — is recomputed whenever the dealer record is read, so a read is always current."

    PRD §3.3: "Sum the `daily_station_hour_capacity` of every commissioned line whose `status` is `RUNNING` or `PAUSED` — a paused line still counts toward the plant's nominal capacity — multiply by twenty working days per month, and round half up to two decimals: that is the plant's monthly hours. Multiply that by the dealer's `allocation_share_bp` and divide by 10000, rounding half up to two decimals: that is the dealer's `entitlement_hours`."

    PRD §3.3: "The dealer's `allocation_slots_reserved` — the count of that dealer's slots in `RESERVED` or `CONSUMED` — and `allocation_hours_consumed` are recomputed, and the order's `version` increments."

    PRD §3.7: "Under the **provisional variant**, computed at submit, no build exists yet, so the three build-derived adjustments are all zero and `provisional_invoice_cents` is simply the discounted subtotal plus freight."

    PRD §3.7: "A `DealerPrincipal` requests funding on its own order, driving `financing_status` `NOT_FINANCED → FUNDING_REQUESTED` while leaving `status` untouched; the request is admissible only while the order's `status` is `CONFIG_VALIDATED`, `SLOTTED`, `IN_PRODUCTION`, or `BUILT`, and only while the dealer's `status` is `ACTIVE`."

    PRD §3.7: "An approval requires a positive `provisional_invoice_cents` and advances `financing_status` `FUNDING_REQUESTED → FLOOR_PLAN_FUNDED`: the plant advances 9000 basis points of the provisional invoice, so `financed_principal_cents` is the provisional invoice multiplied by 9000, divided by 10000, and rounded half up to whole cents, and `funded_at` is stamped from the logical clock."

    PRD §3.7: "A dealer's `financed_exposure_cents` is the sum, across every one of its orders whose `financing_status` is `FLOOR_PLAN_FUNDED` or `CURTAILED`, of that order's `financed_principal_cents` minus its `curtailment_paid_cents`. Its `credit_utilization_bp` is that exposure multiplied by 10000 and divided by its `floor_plan_credit_limit_cents`, truncated toward zero to a whole number of basis points — and zero when the credit limit is zero."

    PRD §3.7: "A payment that leaves the paid total short of the full principal adds `amount_cents` to `curtailment_paid_cents` and recomputes `curtailment_due_cents`; if the order was `CURTAILED` and the recomputed amount due reaches zero, it returns `CURTAILED → FLOOR_PLAN_FUNDED`, where a later sweep may curtail it again — this is a genuine cycle, not a one-way door."

    Design: Corner/consistency model/derived_dealer_positions_are_readable_in_the_same_response_and_the_next_read
    """
    create_supplier()
    floor_plan = create_floor_plan(**TOW_FLOOR_PLAN)
    option = create_option_item()
    dealer = create_dealer()
    line = create_production_line()
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )

    # The provisional invoice is in the submit response itself.
    submitted = validate_success(api.submit_order(order["id"], dealer_headers))
    assert_cents(submitted["provisional_invoice_cents"], 6620350)

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
    assert_hours(slot["station_hours_committed"], "41.00")

    after_slot = validate_success(api.get_dealer(dealer["id"], plant_admin_headers))
    assert_hours(after_slot["allocation_hours_consumed"], "41.00")
    assert after_slot["allocation_slots_reserved"] == 1
    assert_hours(after_slot["entitlement_hours"], "720.00")

    requested = validate_success(api.request_funding(order["id"], dealer_headers))
    assert requested["financing_status"] == "FUNDING_REQUESTED"
    funded = validate_success(
        api.funding_decision(order["id"], {"decision": "APPROVED"}, plant_admin_headers)
    )
    assert funded["financing_status"] == "FLOOR_PLAN_FUNDED"
    assert_cents(funded["financed_principal_cents"], 5958315)

    after_funding = validate_success(api.get_dealer(dealer["id"], plant_admin_headers))
    assert_cents(after_funding["financed_exposure_cents"], 5958315)
    assert after_funding["credit_utilization_bp"] == 595
    assert after_funding["credit_status"] == "GOOD_STANDING"

    paid = validate_success(
        api.floor_plan_payment(order["id"], {"amount_cents": 1000000}, dealer_headers)
    )
    assert_cents(paid["curtailment_paid_cents"], 1000000)

    after_payment = validate_success(api.get_dealer(dealer["id"], plant_admin_headers))
    assert_cents(after_payment["financed_exposure_cents"], 4958315)
    assert after_payment["credit_utilization_bp"] == 495

    paused = validate_success(
        api.set_production_line_status(line["id"], {"status": "PAUSED"}, scheduler_headers)
    )
    assert paused["status"] == "PAUSED"

    after_pause = validate_success(api.get_dealer(dealer["id"], plant_admin_headers))
    assert_hours(after_pause["entitlement_hours"], "720.00")
