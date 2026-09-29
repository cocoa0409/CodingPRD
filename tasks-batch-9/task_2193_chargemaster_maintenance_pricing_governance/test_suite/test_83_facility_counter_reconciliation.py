"""One facility's derived block across create, reprice, activation and retirement."""
from test_helpers import (
    setup_base, create_item, reprice_item, item_lifecycle, read_item, read_facility, set_clock,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-COUNTERS",
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


def test_the_facility_counters_follow_the_active_set_and_nothing_else():
    """PRD §2.11: "The `Facility` row carries `active_item_count` (the number of its charge items whose
    `lifecycle_status` is `ACTIVE`), `aggregate_gross_charge_cents` (the sum of `gross_charge_cents` over
    those same `ACTIVE` items), `aggregate_cost_basis_cents` (the sum of `cost_basis_cents` over those same
    `ACTIVE` items), `aggregate_markup_ratio_bp` (the aggregate gross charge multiplied by 10000, divided by
    the aggregate cost basis, rounded half up — and defined as 0 when the aggregate cost basis is 0), and
    `stale_price_item_count` (the number of its charge items that are simultaneously `ACTIVE` in the
    lifecycle dimension and `PRICE_STALE` in the pricing dimension). Items in `DRAFT`, `PENDING_REVIEW`,
    `APPROVED`, `INACTIVE` or `ARCHIVED` never contribute to any facility aggregate."
    PRD §3.3: "On success `lifecycle_status` becomes `ACTIVE`; the facility's `active_item_count` increases
    by 1, its `aggregate_gross_charge_cents` increases by the item's `gross_charge_cents`, its
    `aggregate_cost_basis_cents` increases by the item's `cost_basis_cents`, `aggregate_markup_ratio_bp` is
    recomputed, `transparency_status` is set to `NEEDS_REFRESH`, `chargemaster_posture` is re-derived, and
    `Facility.version` advances by 1."
    PRD §3.8: "The facility then loses the item from its aggregates: `active_item_count` decreases by 1,
    `aggregate_gross_charge_cents` decreases by the item's `gross_charge_cents`,
    `aggregate_cost_basis_cents` decreases by the item's `cost_basis_cents`, and
    `aggregate_markup_ratio_bp` is recomputed, with `Facility.version` advancing by 1."
    PRD §3.4: "Two further cascades ride on a reprice. If — and only if — the item's `lifecycle_status` is
    `ACTIVE`, the facility's `aggregate_gross_charge_cents` and `aggregate_markup_ratio_bp` are recomputed,
    `stale_price_item_count` is recomputed, `transparency_status` is set to `NEEDS_REFRESH`,
    `chargemaster_posture` is re-derived, any `PUBLISHED` transparency file for that facility transitions
    to `SUPERSEDED`, and `Facility.version` advances by 1."
    PRD §3.2: "When `markup_tiers` is omitted the rule adopts the standard three-band ladder: a 3.20-times
    markup (32000 basis points) from zero cost, stepping down to 2.40 times (24000 basis points) once the
    cost basis reaches 500 dollars, and to 1.80 times (18000 basis points) once it reaches 2,500 dollars."

    Design: Corner/cross_cutting_complexity_layers/facility_derived_counters_reconcile_after_create_after_reprice_and_after_source_retirement
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    first = create_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                        code_type="CPT", code_value="93458", cost_basis_cents=100000,
                        medicare_rate_cents=50000, market_p75_cents=900000,
                        effective_from="2026-09-01T00:00:00Z")
    second = create_item(base, cdm_number="CDM-2002", description="CARDIAC CATH COMPLEX",
                         code_type="CPT", code_value="93460", cost_basis_cents=200000,
                         medicare_rate_cents=50000, market_p75_cents=900000,
                         effective_from="2026-09-01T00:00:00Z")
    assert first["lifecycle_status"] == "DRAFT" and second["lifecycle_status"] == "DRAFT"

    after_create = read_facility(facility_id)
    assert after_create["active_item_count"] == 0, "DRAFT items are invisible to every counter"
    assert after_create["aggregate_gross_charge_cents"] == 0
    assert after_create["aggregate_cost_basis_cents"] == 0
    assert after_create["stale_price_item_count"] == 0
    assert after_create["chargemaster_posture"] == "OPEN"

    assert reprice_item(first["id"])["gross_charge_cents"] == 240000, "24000 bp on 100000"
    assert reprice_item(second["id"])["gross_charge_cents"] == 480000, "24000 bp on 200000"
    after_price = read_facility(facility_id)
    assert after_price["active_item_count"] == 0
    assert after_price["aggregate_gross_charge_cents"] == 0, (
        "pricing a DRAFT item contributes nothing, because the reprice cascade is ACTIVE-only"
    )

    item_lifecycle(first["id"], "SUBMIT_FOR_REVIEW")
    item_lifecycle(first["id"], "APPROVE")
    assert item_lifecycle(first["id"], "ACTIVATE")["lifecycle_status"] == "ACTIVE"
    one_active = read_facility(facility_id)
    assert one_active["active_item_count"] == 1
    assert one_active["aggregate_gross_charge_cents"] == 240000
    assert one_active["aggregate_cost_basis_cents"] == 100000

    item_lifecycle(second["id"], "SUBMIT_FOR_REVIEW")
    item_lifecycle(second["id"], "APPROVE")
    assert item_lifecycle(second["id"], "ACTIVATE")["lifecycle_status"] == "ACTIVE"
    both = read_facility(facility_id)
    assert both["active_item_count"] == 2
    assert both["aggregate_gross_charge_cents"] == 720000, "each item counted exactly once"
    assert both["aggregate_cost_basis_cents"] == 300000
    assert both["aggregate_markup_ratio_bp"] == 24000
    assert both["transparency_status"] == "NEEDS_REFRESH"

    retired = item_lifecycle(first["id"], "DEACTIVATE")
    assert retired["lifecycle_status"] == "INACTIVE"
    assert retired["gross_charge_cents"] == 240000, "the retired item keeps its price"
    after_retire = read_facility(facility_id)
    assert after_retire["active_item_count"] == 1, "the counters drop by exactly the retired item"
    assert after_retire["aggregate_gross_charge_cents"] == 480000
    assert after_retire["aggregate_cost_basis_cents"] == 200000
    assert after_retire["stale_price_item_count"] == 0, (
        "an INACTIVE item is never counted as stale, whatever its price_status"
    )
    assert read_item(first["id"])["gross_charge_cents"] == 240000, (
        "the source row is still readable, so the counters are derived rather than destructive"
    )
