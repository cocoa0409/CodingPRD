"""A refused approval writes nothing: not the item, not the counters, not the facility version."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    setup_base, create_priced_item, item_lifecycle, read_item, read_facility, set_clock,
    ADMIN, APPROVER,
)

TIGHT = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-ATOMIC",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 20000,
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


def test_the_refused_approval_moves_no_observable_and_the_same_call_succeeds_once_the_limit_rises():
    """PRD §3.2: "The check passes when `projected_markup_ratio_bp` is at or below the facility's
    `aggregate_markup_limit_bp`; equality passes. Failure is `ERR_AGGREGATE_MARKUP_LIMIT` (HTTP 422)."
    PRD §3.2: "The ratio is computed before any field is written, and once the write does occur the stored
    facility aggregates are recomputed from the persisted items rather than from this projection."
    PRD §3.3: "`PENDING_REVIEW → APPROVED` is a `PricingCommitteeApprover` action, and here the two
    dimensions finally meet. Two additional preconditions apply beyond posture, evaluated in this order: the
    pricing dimension must already be settled, meaning `price_status` must equal `PRICED_CURRENT`, otherwise
    `ERR_ITEM_PRICE_NOT_CURRENT` (409); and the markup-compliance projection of §3.2 must land at or below
    the facility's `aggregate_markup_limit_bp`, otherwise `ERR_AGGREGATE_MARKUP_LIMIT` (422)."
    PRD §2.8: "The same field and the same error code apply to the facility configuration update endpoint,
    `PATCH /chargemaster/facilities/{facility_id}`, which also requires `expected_facility_version`."

    Design: Corner/consistency_model/a_rejected_write_leaves_no_partially_applied_state_visible_to_the_next_read
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**TIGHT)
    facility_id = base["facility"]["id"]
    item = create_priced_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                              code_type="CPT", code_value="93458", cost_basis_cents=100000,
                              medicare_rate_cents=50000, market_p75_cents=900000,
                              effective_from="2026-09-01T00:00:00Z")
    assert item["gross_charge_cents"] == 240000
    pending = item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW")
    assert pending["lifecycle_status"] == "PENDING_REVIEW"
    assert pending["version"] == 3, "create, reprice, submit"
    facility_before = read_facility(facility_id)

    validate_error(
        api_client.charge_item_lifecycle(item["id"], {"action": "APPROVE"}, APPROVER),
        ApiErrorId.ERR_AGGREGATE_MARKUP_LIMIT.value, 422,
    )

    unmoved = read_item(item["id"])
    assert unmoved["lifecycle_status"] == "PENDING_REVIEW", "nothing about the item moved"
    assert unmoved["version"] == pending["version"]
    assert unmoved["gross_charge_cents"] == 240000
    assert unmoved["price_status"] == "PRICED_CURRENT"
    assert unmoved["approved_by_user_id"] is None
    after_fail = read_facility(facility_id)
    assert after_fail["active_item_count"] == 0
    assert after_fail["aggregate_gross_charge_cents"] == 0
    assert after_fail["version"] == facility_before["version"], (
        "no counter and no version was touched by the rejected call"
    )

    raised = validate_success(api_client.update_facility(
        facility_id, {"expected_facility_version": facility_before["version"],
                      "aggregate_markup_limit_bp": 30000}, ADMIN), 200)
    assert raised["aggregate_markup_limit_bp"] == 30000
    assert raised["version"] == facility_before["version"] + 1

    approved = item_lifecycle(item["id"], "APPROVE")
    assert approved["lifecycle_status"] == "APPROVED", (
        "the identical call succeeds once the ceiling clears 24000 bp, so the refusal was a guard"
    )
    assert approved["version"] == 4
    activated = item_lifecycle(item["id"], "ACTIVATE")
    assert activated["lifecycle_status"] == "ACTIVE"
    final = read_facility(facility_id)
    assert final["active_item_count"] == 1
    assert final["aggregate_gross_charge_cents"] == 240000
    assert final["aggregate_markup_ratio_bp"] == 24000
