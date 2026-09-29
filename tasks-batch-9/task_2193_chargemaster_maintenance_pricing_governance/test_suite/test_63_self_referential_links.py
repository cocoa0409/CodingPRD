"""Companion and duplicate links: same facility, resolvable, and ACTIVE where the PRD says so."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId, factories,
    setup_base, create_item, create_active_item, item_lifecycle,
    read_item, read_facility, set_clock,
    ANALYST, APPROVER, NON_EXISTENT_UUID,
)

PRICING = dict(cost_basis_cents=100000, medicare_rate_cents=50000,
               market_p75_cents=900000, effective_from="2026-09-01T00:00:00Z")


def _scope(ccn: str, revenue_code: str, cost_center: str) -> dict:
    return setup_base(
        facility_overrides={"name": f"Hospital {ccn}", "cms_certification_number": ccn,
                            "rounding_mode": "NEAREST_CENT"},
        revenue_code_overrides={
            "code": revenue_code, "description": "Laboratory - general",
            "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": cost_center,
                             "allowed_revenue_code_values": []},
        price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
    )


def test_a_link_must_resolve_and_stay_inside_the_facility_and_a_duplicate_target_must_be_active():
    """PRD §3.3: "A supplied `companion_required_item_id` must reference a *different* charge item in
    the *same* facility whose `lifecycle_status` is not `ARCHIVED`; pointing at the item itself, at
    another facility's item, or at an archived item is `ERR_COMPANION_ITEM_INVALID` (422)."
    PRD §3.8: "The `duplicate_of_item_id` supplied in the payload must reference a *different* item in
    the *same* facility whose `lifecycle_status` is `ACTIVE` and which is not itself flagged as a
    duplicate — pointing at the item itself, at another facility's item, at a non-`ACTIVE` item, or at
    an already-flagged duplicate is `ERR_DUPLICATE_TARGET_INVALID` (422)."
    PRD §3.3: "The item's `duplicate_of_item_id` must be null — an item retired as a duplicate can
    never come back, and attempting it is `ERR_ITEM_RETIRED_AS_DUPLICATE` (409)."
    PRD §2.9: "10. Body foreign keys resolve, checked left to right in this declaration order:
    `department_id`, then `revenue_code_id` or `proposed_revenue_code_id`, then `charge_item_id`, then
    `companion_required_item_id`, then `duplicate_of_item_id`, then `recovery_captured_charge_id` —
    `ERR_REFERENCED_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/endpoints/companion_and_duplicate_links_require_a_same_facility_active_target
    """
    set_clock("2026-09-01T00:00:00Z")
    base = _scope("CCN-0001", "0300", "CC-100")
    facility_id = base["facility"]["id"]
    assert base["facility"]["duplicate_detection_mode"] == "STRICT_CODE"

    survivor = create_active_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                                 code_type="CPT", code_value="93458", **PRICING)
    twin = create_active_item(base, cdm_number="CDM-1002", description="CARDIAC CATH BASIC",
                              code_type="CPT", code_value="93458", **PRICING)
    draft = create_item(base, cdm_number="CDM-1003", description="CARDIAC CATH ADD ON",
                        code_type="CPT", code_value="93461", **PRICING)

    other = _scope("CCN-0002", "0301", "CC-900")
    foreign = create_item(other, cdm_number="CDM-8001", description="FOREIGN TRAY",
                          code_type="CPT", code_value="93462", **PRICING)

    def kit_body(companion_id):
        return factories.create_charge_item_payload(
            facility_id, base["department"]["id"], base["revenue_code"]["id"],
            cdm_number="CDM-1004", description="CATH KIT", code_type="CPT", code_value="93462",
            cost_basis_cents=40000, medicare_rate_cents=20000, market_p75_cents=300000,
            effective_from="2026-09-01T00:00:00Z",
            companion_required_item_id=companion_id, companion_window_hours=24,
        )

    validate_error(
        api_client.create_charge_item(kit_body(NON_EXISTENT_UUID), ANALYST),
        ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value, 404,
    )
    validate_error(
        api_client.create_charge_item(kit_body(foreign["id"]), ANALYST),
        ApiErrorId.ERR_COMPANION_ITEM_INVALID.value, 422,
    )
    kit = validate_success(api_client.create_charge_item(kit_body(survivor["id"]), ANALYST), 201)
    assert kit["companion_required_item_id"] == survivor["id"]
    assert kit["companion_window_hours"] == 24
    assert kit["lifecycle_status"] == "DRAFT"

    validate_error(
        api_client.charge_item_lifecycle(
            twin["id"], {"action": "MARK_DUPLICATE", "duplicate_of_item_id": draft["id"]},
            ANALYST),
        ApiErrorId.ERR_DUPLICATE_TARGET_INVALID.value, 422,
    )
    validate_error(
        api_client.charge_item_lifecycle(
            twin["id"], {"action": "MARK_DUPLICATE", "duplicate_of_item_id": twin["id"]},
            ANALYST),
        ApiErrorId.ERR_DUPLICATE_TARGET_INVALID.value, 422,
    )

    retired = item_lifecycle(twin["id"], "MARK_DUPLICATE", ANALYST,
                             duplicate_of_item_id=survivor["id"])
    assert retired["lifecycle_status"] == "INACTIVE"
    assert retired["duplicate_of_item_id"] == survivor["id"]

    rows, meta = validate_paginated(api_client.list_charge_items(
        ANALYST, {"facility_id": facility_id, "duplicate_of_item_id": survivor["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == twin["id"]

    validate_error(
        api_client.charge_item_lifecycle(twin["id"], {"action": "REACTIVATE"}, APPROVER),
        ApiErrorId.ERR_ITEM_RETIRED_AS_DUPLICATE.value, 409,
    )

    assert read_item(survivor["id"])["duplicate_of_item_id"] is None
    facility = read_facility(facility_id)
    assert facility["active_item_count"] == 1
    assert facility["aggregate_gross_charge_cents"] == 240000
    assert read_facility(other["facility"]["id"])["active_item_count"] == 0
