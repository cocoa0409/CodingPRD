"""Replay of a token that was live one call earlier, on all three declared version surfaces."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, factories,
    setup_base, create_active_item, create_change_request, review_change_request,
    read_item, read_facility, set_clock,
    ADMIN, ANALYST2, APPROVER, COMPLIANCE,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-OCC",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
                         "allowed_revenue_code_values": []},
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)


def test_a_token_that_was_live_one_call_earlier_is_refused_on_every_version_surface():
    """PRD §2.8: "Two change requests may legitimately target the same charge item and both may reach
    `UNDER_REVIEW`; approving one is a valid supersede of the other's view of that item, because approving
    a `PRICE_CHANGE` or `NEW_ITEM` request advances the item's `version` when it moves `price_status` to
    `REPRICE_PENDING`."
    PRD §2.8: "If the supplied `expected_charge_item_version` does not equal the live
    `ChargeItem.version`, the approval is rejected with `ERR_STALE_ITEM_VERSION` (HTTP 412)."
    PRD §2.8: "instead, a build whose `expected_facility_version` does not equal the live
    `Facility.version` is rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412), because the facility's
    inclusion set has moved since the client last observed it."
    PRD §2.8: "The same field and the same error code apply to the facility configuration update endpoint,
    `PATCH /chargemaster/facilities/{facility_id}`, which also requires `expected_facility_version`."
    PRD §3.5: "For `PRICE_CHANGE` and `NEW_ITEM`, the target item's `price_status` moves to
    `REPRICE_PENDING` and `ChargeItem.version` advances by 1; `pinned_charge_item_version` is set to the
    *post-bump* version so that the later implementation can match it."

    Design: Corner/cross_cutting_complexity_layers/version_tokens_are_monotonic_so_a_formerly_valid_token_is_rejected_on_every_occ_surface
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    item = create_active_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                              code_type="CPT", code_value="93458", cost_basis_cents=100000,
                              medicare_rate_cents=50000, market_p75_cents=900000,
                              effective_from="2026-09-01T00:00:00Z")
    assert item["version"] == 5
    assert item["gross_charge_cents"] == 240000

    first = create_change_request(base, item["id"], "PRICE_CHANGE",
                                  justification="First request raises the tray cost",
                                  proposed_cost_basis_cents=150000)
    second = create_change_request(base, item["id"], "PRICE_CHANGE",
                                   justification="Second request raises it further",
                                   proposed_cost_basis_cents=200000)
    for request in (first, second):
        assert review_change_request(request["id"], ANALYST2,
                                     decision_note="Reviewed")["status"] == "UNDER_REVIEW"

    approved_first = validate_success(api_client.approve_change_request(
        first["id"], {"expected_charge_item_version": 5,
                      "decision_note": "Approved against the live item version"}, APPROVER), 200)
    assert approved_first["status"] == "APPROVED"
    assert approved_first["pinned_charge_item_version"] == 6, (
        "the approval bumped the item, so the approver's own token went stale as it answered"
    )

    validate_error(
        api_client.approve_change_request(
            second["id"], {"expected_charge_item_version": 5,
                           "decision_note": "Replaying the token that worked one call ago"},
            APPROVER),
        ApiErrorId.ERR_STALE_ITEM_VERSION.value, 412,
    )
    bumped = read_item(item["id"])
    assert bumped["version"] == 6
    assert bumped["price_status"] == "REPRICE_PENDING"
    assert bumped["gross_charge_cents"] == 240000, (
        "the approval pinned and flagged the item but did not reprice it"
    )

    approved_second = validate_success(api_client.approve_change_request(
        second["id"], {"expected_charge_item_version": 6,
                       "decision_note": "Approved against the version the first approval made"},
        APPROVER), 200)
    assert approved_second["status"] == "APPROVED"
    assert approved_second["pinned_charge_item_version"] == 7, (
        "each approval advances the item again, so every approver must read the version fresh"
    )
    assert read_item(item["id"])["version"] == 7

    live_facility_version = read_facility(facility_id)["version"]
    patched = validate_success(api_client.update_facility(
        facility_id, {"expected_facility_version": live_facility_version,
                      "aggregate_markup_limit_bp": 60000}, ADMIN), 200)
    assert patched["aggregate_markup_limit_bp"] == 60000
    assert patched["version"] == live_facility_version + 1
    next_facility_version = patched["version"]

    validate_error(
        api_client.update_facility(
            facility_id, {"expected_facility_version": live_facility_version,
                          "aggregate_markup_limit_bp": 70000}, ADMIN),
        ApiErrorId.ERR_STALE_FACILITY_VERSION.value, 412,
    )
    validate_error(
        api_client.create_transparency_file(
            factories.create_transparency_file_payload(facility_id, live_facility_version,
                                                       file_format="CSV"), COMPLIANCE),
        ApiErrorId.ERR_STALE_FACILITY_VERSION.value, 412,
    )
    built = validate_success(api_client.create_transparency_file(
        factories.create_transparency_file_payload(facility_id, next_facility_version,
                                                   file_format="CSV"), COMPLIANCE), 201)
    assert built["status"] == "BUILDING", "the freshly read token is the one that works"

    final = read_facility(facility_id)
    assert final["aggregate_markup_limit_bp"] == 60000, "the rejected patch changed nothing"
    assert final["version"] == next_facility_version + 1, (
        "only the successful build moved the facility past the patch, never the two 412s"
    )
