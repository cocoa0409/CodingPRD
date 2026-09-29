"""One ACTIVATE call applies every mapped entry, skips the deferred one and snapshots the facility."""
from test_helpers import (
    api_client, validate_error, ApiErrorId,
    setup_base, create_active_item, create_cycle, create_entry, cycle_lifecycle,
    disposition_entry, read_cycle, read_entry, read_item, read_facility, set_clock,
    make_approver_headers, ANALYST, ANALYST_USER_ID, APPROVER, COMPLIANCE,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-CYCLE",
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
PRICING = dict(cost_basis_cents=100000, medicare_rate_cents=50000,
               market_p75_cents=900000, effective_from="2026-09-01T00:00:00Z")


def test_activation_applies_both_mapped_entries_and_leaves_the_deferred_one_alone():
    """PRD §3.7: "The cycle's `unmapped_entry_count` must be 0 — every entry must be either `MAPPED` or
    `DEFERRED` — otherwise `ERR_UNMAPPED_CODE_ENTRIES` (409). At least one entry must be in `MAPPED`
    status, so an all-deferred cycle cannot be approved, and that failure is
    `ERR_CYCLE_HAS_NO_MAPPED_ENTRIES` (422). And `X-User-ID` must differ from the `mapped_by_user_id`
    recorded on *every* entry of the cycle, otherwise `ERR_SEGREGATION_OF_DUTIES` (409)."
    PRD §3.7: "On success the cycle first snapshots the facility's state *before any child is mutated*:
    `pre_activation_active_item_count` takes the facility's `active_item_count` and
    `pre_activation_aggregate_gross_charge_cents` takes its `aggregate_gross_charge_cents`. Then
    `status` becomes `ACTIVATED`, `activated_at` takes the logical now, and the cycle's `version`
    advances by 1."
    PRD §3.7: "First, every entry whose `status` is `MAPPED` is processed **in order of `created_at`
    ascending**, transitions `MAPPED → APPLIED`, and snapshots four values from its target item for
    later rollback: `prior_code_value` from the item's `code_value`, `prior_revenue_code_id` from its
    `revenue_code_id`, `prior_gross_charge_cents` from its `gross_charge_cents`, and
    `prior_lifecycle_status` from its `lifecycle_status`; each entry's `version` advances by 1."
    PRD §3.7: "for `CROSSWALK` and `REVISE`, the item's `code_value` takes `new_code_value`, its
    `revenue_code_id` takes `new_revenue_code_id` when that field is non-null, its `gross_charge_cents`
    takes the entry's `carried_gross_charge_cents`, and its `price_status` moves to `PRICE_STALE`"

    Design: Corner/endpoints/cycle_activate_applies_every_mapped_entry_and_skips_the_deferred_one_in_a_single_call
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    item_one = create_active_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                                 code_type="CPT", code_value="93458", **PRICING)
    item_two = create_active_item(base, cdm_number="CDM-1002", description="CARDIAC CATH COMPLEX",
                                  code_type="CPT", code_value="93460", **PRICING)
    assert item_one["gross_charge_cents"] == 240000
    assert item_two["gross_charge_cents"] == 240000
    before = read_facility(facility_id)
    assert before["active_item_count"] == 2
    assert before["aggregate_gross_charge_cents"] == 480000

    cycle = create_cycle(facility_id, cycle_year=2027, code_set="CPT")
    assert cycle["cost_inflator_bp"] == 10300, "the omitted inflator defaults to 10300"
    assert cycle["status"] == "LOADED"
    entry_one = create_entry(cycle["id"], "REVISE", old_code_value="93458",
                             new_code_value="93458A")
    entry_two = create_entry(cycle["id"], "REVISE", old_code_value="93460",
                             new_code_value="93460A")
    entry_three = create_entry(cycle["id"], "ADD", old_code_value=None,
                               new_code_value="0001U")
    assert entry_one["status"] == "PENDING"

    mapping = cycle_lifecycle(cycle["id"], "START_MAPPING")
    assert mapping["status"] == "MAPPING"
    assert mapping["unmapped_entry_count"] == 3

    validate_error(
        api_client.code_update_cycle_lifecycle(
            cycle["id"], {"action": "APPROVE_CROSSWALK"}, APPROVER),
        ApiErrorId.ERR_UNMAPPED_CODE_ENTRIES.value, 409,
    )

    mapped_one = disposition_entry(entry_one["id"], "MAP")
    assert mapped_one["status"] == "MAPPED"
    assert mapped_one["target_charge_item_id"] == item_one["id"]
    assert mapped_one["carried_gross_charge_cents"] == 240000, (
        "the revenue code is unchanged, so the price carries and the inflator is never applied"
    )
    mapped_two = disposition_entry(entry_two["id"], "MAP")
    assert mapped_two["status"] == "MAPPED"
    assert mapped_two["carried_gross_charge_cents"] == 240000

    deferred = disposition_entry(entry_three["id"], "DEFER",
                                 defer_reason="No local item exists for the new code yet")
    assert deferred["status"] == "DEFERRED"
    assert read_cycle(cycle["id"])["unmapped_entry_count"] == 0

    validate_error(
        api_client.code_update_cycle_lifecycle(
            cycle["id"], {"action": "APPROVE_CROSSWALK"},
            make_approver_headers(ANALYST_USER_ID)),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409,
    )
    approved = cycle_lifecycle(cycle["id"], "APPROVE_CROSSWALK", APPROVER)
    assert approved["status"] == "CROSSWALK_APPROVED"

    activated = cycle_lifecycle(cycle["id"], "ACTIVATE", COMPLIANCE)
    assert activated["status"] == "ACTIVATED"
    assert activated["applied_entry_count"] == 2, "the deferred entry is skipped, not failed"
    assert activated["pre_activation_active_item_count"] == 2
    assert activated["pre_activation_aggregate_gross_charge_cents"] == 480000
    assert activated["activated_at"].startswith("2026-09-01T00:00:00")

    after_one = read_item(item_one["id"])
    assert after_one["code_value"] == "93458A"
    assert after_one["gross_charge_cents"] == 240000
    assert after_one["last_code_cycle_id"] == cycle["id"]
    after_two = read_item(item_two["id"])
    assert after_two["code_value"] == "93460A"
    assert after_two["gross_charge_cents"] == 240000
    assert after_two["last_code_cycle_id"] == cycle["id"]

    applied_one = read_entry(entry_one["id"])
    assert applied_one["status"] == "APPLIED"
    assert applied_one["prior_code_value"] == "93458"
    applied_two = read_entry(entry_two["id"])
    assert applied_two["status"] == "APPLIED"
    assert applied_two["prior_code_value"] == "93460"
    untouched = read_entry(entry_three["id"])
    assert untouched["status"] == "DEFERRED"
    assert untouched["target_charge_item_id"] is None

    facility = read_facility(facility_id)
    assert facility["active_item_count"] == 2
    assert facility["aggregate_gross_charge_cents"] == 480000
    assert facility["chargemaster_posture"] == "OPEN", "the cycle has left MAPPING"
