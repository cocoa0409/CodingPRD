"""One stale ACTIVE item is excluded from the file yet still routes validation to FAILED."""
from test_helpers import (
    api_client, validate_success, factories,
    setup_base, create_revenue_code, create_price_rule, create_active_item,
    create_payer_contract, build_transparency_file, file_lifecycle,
    read_item, read_facility, set_clock,
    ANALYST,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-MERCY",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={
        "name": "Cardiac Cath Lab", "cost_center_code": "CC-4100",
        "allowed_revenue_code_values": [],
    },
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)


def test_validation_fails_on_a_stale_active_item_and_freezes_nothing():
    """PRD §3.10: "It gains the string `'NO_PUBLISHABLE_ITEMS'` when `included_item_count` is 0, the
    string `'NO_ACTIVE_PAYER_COLUMNS'` when `payer_column_count` is 0, and the string
    `'STALE_PRICED_ITEMS'` when any charge item of the facility whose `lifecycle_status` is `ACTIVE`
    has `price_status` of `PRICE_STALE`. Note the asymmetry there: a stale-priced `ACTIVE` item is
    excluded from the file's inclusion set but still blocks validation, because a facility cannot
    honestly publish while part of its live chargemaster is unpriced."
    PRD §3.10: "On the `FAILED` branch, no item is frozen; the file's `status` becomes `FAILED`, the
    facility's posture is re-derived (this file no longer holds it `FROZEN`) and `Facility.version`
    advances by 1."
    PRD §2.7: "3. `RESTRICTED`, when the facility's `stale_price_item_count` is 5 or more (five
    exactly qualifies)."

    Design: Corner/state_machines/transparency_validate_with_one_stale_active_item_branches_to_failed
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    rc301 = create_revenue_code(
        code="0301", description="Laboratory - chemistry", requires_hcpcs=False,
        allowed_code_types=["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        pricing_class="PROCEDURE",
    )
    rule301 = create_price_rule(
        base["facility"]["id"], rc301["id"], effective_from="2026-01-01T00:00:00Z"
    )
    item1 = create_active_item(
        base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    item2 = create_active_item(
        {**base, "revenue_code": rc301, "price_rule": rule301},
        cdm_number="CDM-1002", description="CHEMISTRY PANEL",
        code_type="CPT", code_value="80053", cost_basis_cents=60000,
        medicare_rate_cents=20000, market_p75_cents=600000,
        effective_from="2026-09-01T00:00:00Z",
    )
    assert item1["gross_charge_cents"] == 240000
    assert item2["gross_charge_cents"] == 144000
    create_payer_contract(
        base["facility"]["id"], payer_code="BCBS", product_line="MEDICARE_ADVANTAGE",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=6000,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
    )

    validate_success(
        api_client.create_price_rule(
            factories.create_price_rule_payload(
                base["facility"]["id"], rc301["id"],
                effective_from="2026-10-01T00:00:00Z", effective_to=None,
                supersede_rule_id=rule301["id"],
            ),
            ANALYST,
        ),
        201,
    )
    assert read_item(item2["id"])["price_status"] == "PRICE_STALE"
    assert read_item(item1["id"])["price_status"] == "PRICED_CURRENT"

    facility = read_facility(base["facility"]["id"])
    assert facility["stale_price_item_count"] == 1
    building = build_transparency_file(facility["id"], facility["version"])
    assert building["included_item_count"] == 1, (
        "the stale ACTIVE item is excluded from the inclusion set"
    )
    assert building["total_gross_charge_cents"] == 240000
    assert building["payer_column_count"] == 1

    failed = file_lifecycle(building["id"], "VALIDATE")
    assert failed["status"] == "FAILED"
    assert failed["validation_errors"] == ["STALE_PRICED_ITEMS"], (
        "the only assembled error, since there is a publishable row and a payer column"
    )
    assert failed["version"] == 2

    frozen_nothing = read_item(item1["id"])
    assert frozen_nothing["price_status"] == "PRICED_CURRENT", "no item is frozen on this branch"
    assert frozen_nothing["version"] == 5
    stale = read_item(item2["id"])
    assert stale["price_status"] == "PRICE_STALE"
    assert stale["lifecycle_status"] == "ACTIVE"

    after = read_facility(base["facility"]["id"])
    assert after["chargemaster_posture"] == "OPEN", (
        "the FAILED file no longer holds the facility, and 1 stale item is short of 5"
    )
    assert after["stale_price_item_count"] == 1
    assert after["transparency_status"] == "NEEDS_REFRESH"
