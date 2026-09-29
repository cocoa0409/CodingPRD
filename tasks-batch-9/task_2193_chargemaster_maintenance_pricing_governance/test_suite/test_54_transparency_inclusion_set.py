"""The build's inclusion set, its payer columns, and the determinism of its content hash."""
from test_helpers import (
    api_client, validate_success,
    setup_base, create_revenue_code, create_price_rule, create_active_item, create_item,
    create_payer_contract, build_transparency_file, file_lifecycle,
    read_item, read_facility, set_clock,
    CONTRACT,
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


def _read_contract(contract_id: str) -> dict:
    return validate_success(api_client.get_payer_contract(contract_id, CONTRACT), 200)


def test_the_build_includes_only_publishable_rows_and_hashes_them_deterministically():
    """PRD §3.10: "**The build** captures `as_of_datetime` from the logical clock, and the inclusion
    set is evaluated at that instant: every `ChargeItem` of the file's facility whose
    `lifecycle_status` is `ACTIVE`, whose `price_status` is either `PRICED_CURRENT` or
    `PRICE_FROZEN`, and whose `duplicate_of_item_id` is null."
    PRD §3.10: "From that ordered set, `included_item_count` is the row count and
    `total_gross_charge_cents` is the sum of `gross_charge_cents` over the rows. `payer_column_count`
    is the number of distinct `payer_code` and `product_line` pairs among the facility's
    `PayerContract` rows whose `status` is `ACTIVE` and whose closed term contains `as_of_datetime`"
    PRD §3.10: "`content_hash` is a SHA-256 digest over the ordered rows, each serialized as its
    `cdm_number`, its revenue code, its `code_value` (or an empty string when null) and its
    `gross_charge_cents` joined by vertical bars, with rows joined by newlines — deterministic for a
    given inclusion set and ordering, and recomputed on every build."

    Design: Corner/calculations/transparency_build_inclusion_set_ordering_and_deterministic_content_hash
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    rc270 = create_revenue_code(
        code="0270", description="Medical/surgical supplies", requires_hcpcs=False,
        allowed_code_types=["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        pricing_class="SUPPLY",
    )
    create_price_rule(base["facility"]["id"], rc270["id"],
                      effective_from="2026-01-01T00:00:00Z")
    supply_base = {**base, "revenue_code": rc270}

    item_a = create_active_item(
        supply_base, cdm_number="CDM-300", description="STERILE DRESSING KIT",
        code_type="HCPCS", code_value="A4550", cost_basis_cents=50000,
        medicare_rate_cents=10000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    item_b = create_active_item(
        supply_base, cdm_number="CDM-100", description="SUPPLY BUNDLE REVENUE ONLY",
        code_type="REV_ONLY", code_value=None, cost_basis_cents=50000,
        medicare_rate_cents=10000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    item_c = create_active_item(
        base, cdm_number="CDM-200", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    item_d = create_active_item(
        base, cdm_number="CDM-050", description="CARDIAC CATH REPEAT",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    item_e = create_item(
        base, cdm_number="CDM-900", description="NEVER PRICED DRAFT",
        code_type="CDM_INTERNAL", code_value=None, cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    assert item_a["gross_charge_cents"] == 120000
    assert item_b["gross_charge_cents"] == 120000
    assert item_c["gross_charge_cents"] == 240000
    assert item_d["gross_charge_cents"] == 240000

    facility_id = base["facility"]["id"]
    create_payer_contract(
        facility_id, payer_code="BCBS", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=6000,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
    )
    create_payer_contract(
        facility_id, payer_code="AETNA", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=5000,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
    )
    uhc = create_payer_contract(
        facility_id, payer_code="UHC", product_line="MEDICAID_MCO",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=4000,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
    )
    validate_success(api_client.terminate_payer_contract(
        uhc["id"], CONTRACT, {"termination_note": "Network exit"}), 200)
    assert _read_contract(uhc["id"])["status"] == "TERMINATED"

    facility = read_facility(facility_id)
    building = build_transparency_file(facility_id, facility["version"], file_format="CSV")
    assert building["included_item_count"] == 4, "the DRAFT item is not publishable"
    assert building["total_gross_charge_cents"] == 720000
    assert building["payer_column_count"] == 2, "the terminated term adds no column"
    assert building["file_format"] == "CSV"
    assert building["as_of_datetime"].startswith("2026-09-01T00:00:00")
    first_hash = building["content_hash"]
    assert isinstance(first_hash, str) and first_hash != ""

    validated = file_lifecycle(building["id"], "VALIDATE")
    assert validated["status"] == "VALIDATED"
    assert validated["validation_errors"] == [], (
        "the never-priced item is DRAFT, not ACTIVE, so it blocks nothing"
    )
    assert validated["content_hash"] == first_hash, (
        "the same inclusion set in the same order hashes identically"
    )

    draft = read_item(item_e["id"])
    assert draft["lifecycle_status"] == "DRAFT"
    assert draft["price_status"] == "PRICE_STALE"

    for item in (item_a, item_b, item_c, item_d):
        assert read_item(item["id"])["price_status"] == "PRICE_FROZEN"
