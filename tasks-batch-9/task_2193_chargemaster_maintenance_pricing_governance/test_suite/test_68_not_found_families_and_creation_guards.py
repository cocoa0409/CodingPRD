"""Path resolution splits 404s by resource family, and the two creation guards on a charge item."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId, factories,
    create_facility, create_revenue_code, create_department, create_price_rule,
    read_facility, set_clock,
    ADMIN, ANALYST, COMPLIANCE, CONTRACT, MANAGER_USER_ID, NON_EXISTENT_UUID,
)

GHOST = NON_EXISTENT_UUID


def test_the_same_missing_uuid_yields_six_different_not_found_codes_by_family():
    """PRD §2.9: "4. `facility_id`, wherever it appears in a path or body, resolves to a `Facility` —
    `ERR_FACILITY_NOT_FOUND` (404)."
    PRD §2.9: "5. `charge_item_id` in the path resolves — `ERR_CHARGE_ITEM_NOT_FOUND` (404)."
    PRD §2.9: "6. `change_request_id` in the path resolves — `ERR_CHANGE_REQUEST_NOT_FOUND` (404)."
    PRD §2.9: "7. `cycle_id` resolves to a `CodeUpdateCycle` and `entry_id` resolves to a
    `CodeUpdateEntry` — `ERR_CODE_UPDATE_NOT_FOUND` (404)."
    PRD §2.9: "8. `batch_id` resolves to a `ChargeCaptureBatch`, `captured_charge_id` to a
    `CapturedCharge` and `finding_id` to a `MissingChargeFinding` — `ERR_CAPTURE_RESOURCE_NOT_FOUND`
    (404)."
    PRD §2.9: "9. `file_id` resolves to a `TransparencyFile`, `analysis_id` to a
    `PriceChangeImpactAnalysis`, `price_rule_id` to a `PriceRule`, `payer_contract_id` to a
    `PayerContract`, `department_id` to a `Department` and `revenue_code_id` to a `RevenueCode` —
    `ERR_GOVERNANCE_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/errors/every_resource_family_has_its_own_not_found_code_on_reads_and_writes
    """
    set_clock("2026-09-01T00:00:00Z")
    facility = create_facility(name="Mercy General",
                              cms_certification_number="CCN-2193-NOTFOUND")

    validate_error(api_client.get_facility(GHOST, ADMIN),
                   ApiErrorId.ERR_FACILITY_NOT_FOUND.value, 404)

    for response in (api_client.get_charge_item(GHOST, ANALYST),
                     api_client.reprice_charge_item(GHOST, ANALYST)):
        validate_error(response, ApiErrorId.ERR_CHARGE_ITEM_NOT_FOUND.value, 404)

    for response in (api_client.get_change_request(GHOST, ANALYST),
                     api_client.change_request_decision(GHOST, {"decision": "REVIEW"}, ANALYST)):
        validate_error(response, ApiErrorId.ERR_CHANGE_REQUEST_NOT_FOUND.value, 404)

    for response in (
        api_client.get_code_update_cycle(GHOST, ANALYST),
        api_client.create_code_update_entry(
            GHOST, {"action": "ADD", "old_code_value": None, "new_code_value": "0001U"}, ANALYST),
        api_client.get_code_update_entry(GHOST, ANALYST),
        api_client.disposition_code_update_entry(
            GHOST, {"action": "DEFER", "defer_reason": "No local target exists"}, ANALYST),
    ):
        validate_error(response, ApiErrorId.ERR_CODE_UPDATE_NOT_FOUND.value, 404)

    for response in (api_client.get_charge_capture_batch(GHOST, ANALYST),
                     api_client.get_missing_charge_finding(GHOST, ANALYST),
                     api_client.get_captured_charge(GHOST, ANALYST)):
        validate_error(response, ApiErrorId.ERR_CAPTURE_RESOURCE_NOT_FOUND.value, 404)

    for response in (api_client.get_transparency_file(GHOST, COMPLIANCE),
                     api_client.get_price_change_analysis(GHOST, CONTRACT),
                     api_client.get_price_rule(GHOST, ANALYST),
                     api_client.get_payer_contract(GHOST, CONTRACT),
                     api_client.get_department(GHOST, ADMIN),
                     api_client.get_revenue_code(GHOST, ADMIN)):
        validate_error(response, ApiErrorId.ERR_GOVERNANCE_RESOURCE_NOT_FOUND.value, 404)

    envelope = api_client.get_department(GHOST, ADMIN).json()
    assert envelope["data"]["error_id"] == ApiErrorId.ERR_GOVERNANCE_RESOURCE_NOT_FOUND.value
    assert envelope["data"]["message"], "every error body carries a message beside the error_id"

    assert read_facility(facility["id"])["version"] == 1, "no failed write mutated anything"
    _, meta = validate_paginated(api_client.list_charge_items(
        ANALYST, {"facility_id": facility["id"]}))
    assert meta["total_count"] == 0


def test_a_back_dated_creation_is_rejected_before_the_facility_scoped_cdm_collision():
    """PRD §3.3: "And `effective_from` must be at or after the logical now at creation time — a
    back-dated item is `ERR_EFFECTIVE_DATE_IN_PAST` (422). A colliding `cdm_number` within the facility
    is `ERR_DUPLICATE_CDM_NUMBER` (409)."
    PRD §2.9: "32–38. Temporal rules, in this order: `ERR_EFFECTIVE_DATE_IN_PAST` (422),
    `ERR_ITEM_NOT_YET_EFFECTIVE` (409), `ERR_PRICE_RULE_OVERLAP` (409), `ERR_CONTRACT_TERM_OVERLAP`
    (409), `ERR_CONTRACT_TERM_BUFFER_VIOLATION` (409), `ERR_BATCH_WINDOW_CAPACITY_EXCEEDED` (409),
    `ERR_SERVICE_DATE_OUTSIDE_WINDOW` (422)."
    PRD §3.3: "A newly created item lands in `DRAFT` in the lifecycle dimension and `PRICE_STALE` in the
    pricing dimension, with `gross_charge_cents` at 0"

    Design: Corner/errors/item_creation_with_a_past_effective_date_is_rejected_before_the_duplicate_cdm_check
    """
    set_clock("2026-09-01T00:00:00Z")
    south = create_facility(name="Mercy South", cms_certification_number="CCN-2193-SOUTH",
                           rounding_mode="NEAREST_CENT")
    north = create_facility(name="Mercy North", cms_certification_number="CCN-2193-NORTH",
                           rounding_mode="NEAREST_CENT")
    revenue_code = create_revenue_code(code="0300", description="Laboratory - general",
                                      requires_hcpcs=False, allowed_code_types=["CPT"],
                                      pricing_class="PROCEDURE")
    south_dept = create_department(south["id"], MANAGER_USER_ID, name="Cardiac Cath Lab",
                                  cost_center_code="CC-100")
    north_dept = create_department(north["id"], MANAGER_USER_ID, name="Cardiac Cath Lab",
                                  cost_center_code="CC-100")
    for facility_id in (south["id"], north["id"]):
        create_price_rule(facility_id, revenue_code["id"], pricing_method="COST_PLUS_MARKUP",
                         effective_from="2026-01-01T00:00:00Z")

    def body(facility_id, department_id, cdm_number, description, effective_from):
        return factories.create_charge_item_payload(
            facility_id, department_id, revenue_code["id"], cdm_number=cdm_number,
            description=description, code_type="CPT", code_value="93458",
            cost_basis_cents=100000, medicare_rate_cents=50000, market_p75_cents=900000,
            effective_from=effective_from)

    original = validate_success(api_client.create_charge_item(
        body(south["id"], south_dept["id"], "CDM-1001", "CARDIAC CATH BASIC",
             "2026-09-01T00:00:00Z"), ANALYST), 201)
    assert original["effective_from"].startswith("2026-09-01T00:00:00"), (
        "an effective_from equal to the logical now is accepted"
    )

    set_clock("2026-09-02T00:00:00Z")
    validate_error(
        api_client.create_charge_item(
            body(south["id"], south_dept["id"], "CDM-1001", "CARDIAC CATH BASIC COPY",
                 "2026-09-01T00:00:00Z"), ANALYST),
        ApiErrorId.ERR_EFFECTIVE_DATE_IN_PAST.value, 422,
    )
    validate_error(
        api_client.create_charge_item(
            body(south["id"], south_dept["id"], "CDM-1001", "CARDIAC CATH BASIC COPY",
                 "2026-09-02T00:00:00Z"), ANALYST),
        ApiErrorId.ERR_DUPLICATE_CDM_NUMBER.value, 409,
    )

    twin = validate_success(api_client.create_charge_item(
        body(north["id"], north_dept["id"], "CDM-1001", "NORTH CATH BASIC",
             "2026-09-02T00:00:00Z"), ANALYST), 201)
    assert twin["cdm_number"] == "CDM-1001", "uniqueness is scoped to the facility, not global"

    future = validate_success(api_client.create_charge_item(
        body(south["id"], south_dept["id"], "CDM-1002", "CARDIAC CATH COMPLEX",
             "2026-09-30T00:00:00Z"), ANALYST), 201)
    assert future["effective_from"].startswith("2026-09-30T00:00:00")
    assert future["lifecycle_status"] == "DRAFT"
    assert future["price_status"] == "PRICE_STALE"

    _, south_meta = validate_paginated(api_client.list_charge_items(
        ANALYST, {"facility_id": south["id"]}))
    assert south_meta["total_count"] == 2, "both refused creations stored nothing"
    _, north_meta = validate_paginated(api_client.list_charge_items(
        ANALYST, {"facility_id": north["id"]}))
    assert north_meta["total_count"] == 1
