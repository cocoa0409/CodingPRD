"""The FROZEN gate masks the frozen-price check, and RESTRICTED only gates coded creation."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId, factories,
    setup_base, create_active_item, create_payer_contract,
    build_transparency_file, file_lifecycle, read_file,
    create_cycle, create_entry, cycle_lifecycle, read_item, read_facility, set_clock,
    ANALYST,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-POSTURE",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={
        "name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
        "allowed_revenue_code_values": [],
    },
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)


def test_frozen_beats_the_item_price_frozen_check_and_restricted_spares_the_reprice():
    """PRD §2.7: "A `FROZEN` posture rejects six write operations with `ERR_FACILITY_FROZEN` (HTTP
    409): creating a charge item, driving a charge item's lifecycle, repricing a charge item, creating a
    price rule, implementing an approved change request, and — for the code-update cycle — the
    `ACTIVATE` and `ROLL_BACK` actions. A `RESTRICTED` posture rejects exactly two things with
    `ERR_FACILITY_RESTRICTED` (HTTP 409): creating a charge item whose `code_type` is `CPT` or `HCPCS`,
    and approving a change request whose `request_type` is `REVENUE_CODE_REMAP`."
    PRD §2.7: "1. `FROZEN`, when at least one `TransparencyFile` belonging to this facility has
    `status` of either `BUILDING` or `VALIDATED`."
    PRD §2.7: "2. `RESTRICTED`, when at least one `CodeUpdateCycle` belonging to this facility has
    `status` of either `MAPPING` or `CROSSWALK_APPROVED`."
    PRD §3.4: "While an item is `PRICE_FROZEN` its price cannot be rebuilt, which is where
    `ERR_ITEM_PRICE_FROZEN` comes from. The thaw, `PRICE_FROZEN → PRICED_CURRENT`, fires when the file
    moves `VALIDATED → PUBLISHED` or `VALIDATED → FAILED`, on the condition that the facility has no
    *other* transparency file still sitting in `BUILDING` or `VALIDATED`; each thawed item's `version`
    advances by 1."

    Design: Corner/validations/facility_frozen_masks_the_item_price_frozen_check_while_restricted_only_gates_coded_creation
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    item = create_active_item(
        base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    assert item["gross_charge_cents"] == 240000
    assert item["version"] == 5

    create_payer_contract(
        facility_id, payer_code="AETNA", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=4000,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
    )

    facility = read_facility(facility_id)
    building = build_transparency_file(facility_id, facility["version"])
    assert building["status"] == "BUILDING"
    assert building["included_item_count"] == 1
    assert read_facility(facility_id)["chargemaster_posture"] == "FROZEN"

    def coded_item_body(cdm_number, code_value, description):
        return factories.create_charge_item_payload(
            facility_id, base["department"]["id"], base["revenue_code"]["id"],
            cdm_number=cdm_number, description=description,
            code_type="CPT", code_value=code_value, cost_basis_cents=100000,
            medicare_rate_cents=50000, market_p75_cents=900000,
            effective_from="2026-09-01T00:00:00Z",
        )

    validate_error(
        api_client.reprice_charge_item(item["id"], ANALYST),
        ApiErrorId.ERR_FACILITY_FROZEN.value, 409,
    )
    validate_error(
        api_client.create_charge_item(
            coded_item_body("CDM-1002", "93460", "CARDIAC CATH COMPLEX"), ANALYST),
        ApiErrorId.ERR_FACILITY_FROZEN.value, 409,
    )

    validated = file_lifecycle(building["id"], "VALIDATE")
    assert validated["status"] == "VALIDATED"
    assert read_item(item["id"])["price_status"] == "PRICE_FROZEN"

    validate_error(
        api_client.reprice_charge_item(item["id"], ANALYST),
        ApiErrorId.ERR_FACILITY_FROZEN.value, 409,
    )

    published = file_lifecycle(building["id"], "PUBLISH")
    assert published["status"] == "PUBLISHED"
    assert read_item(item["id"])["price_status"] == "PRICED_CURRENT", "publication thaws the item"

    thawed = validate_success(api_client.reprice_charge_item(item["id"], ANALYST), 200)
    assert thawed["gross_charge_cents"] == 240000
    assert thawed["price_status"] == "PRICED_CURRENT"

    assert read_file(building["id"])["status"] == "SUPERSEDED", (
        "repricing an ACTIVE item supersedes the published file"
    )
    after_reprice = read_facility(facility_id)
    assert after_reprice["published_transparency_file_id"] is None
    assert after_reprice["transparency_status"] == "NEEDS_REFRESH"

    cycle = create_cycle(facility_id, cycle_year=2027, code_set="CPT")
    create_entry(cycle["id"], "REVISE", old_code_value="93458", new_code_value="93458A")
    mapping = cycle_lifecycle(cycle["id"], "START_MAPPING")
    assert mapping["status"] == "MAPPING"
    assert read_facility(facility_id)["chargemaster_posture"] == "RESTRICTED"

    validate_error(
        api_client.create_charge_item(
            coded_item_body("CDM-1003", "93461", "CARDIAC CATH ADD ON"), ANALYST),
        ApiErrorId.ERR_FACILITY_RESTRICTED.value, 409,
    )
    still_repriceable = validate_success(api_client.reprice_charge_item(item["id"], ANALYST), 200)
    assert still_repriceable["gross_charge_cents"] == 240000, (
        "reprice is gated by FROZEN only, never by RESTRICTED"
    )

    rows, meta = validate_paginated(
        api_client.list_charge_items(ANALYST, {"facility_id": facility_id})
    )
    assert meta["total_count"] == 1, "all three refused creations stored nothing"
    assert rows[0]["id"] == item["id"]
