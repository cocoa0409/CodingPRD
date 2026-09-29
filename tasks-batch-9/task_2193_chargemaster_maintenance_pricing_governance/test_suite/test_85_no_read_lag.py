"""Every write response already carries the recomputed state, and the next read agrees at once."""
from test_helpers import (
    api_client, validate_error, ApiErrorId, factories,
    setup_base, create_item, reprice_item, item_lifecycle, read_item, read_facility,
    build_transparency_file, file_lifecycle, read_file, create_payer_contract,
    set_clock, ANALYST,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-NOLAG",
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


def test_the_facility_is_already_frozen_on_the_call_that_follows_the_build():
    """PRD §2.11: "Aggregates in this system are always derived from persisted rows, never from
    projections."
    PRD §3.10: "On the `VALIDATED` branch, every charge item of the facility whose `lifecycle_status` is
    `ACTIVE` and whose `price_status` is `PRICED_CURRENT` transitions to `PRICE_FROZEN` with each item's
    `version` advancing by 1, and the facility's posture is re-derived to `FROZEN` with `Facility.version`
    advancing by 1."
    PRD §3.10: "Initiating the build creates a `TransparencyFile` in `BUILDING`, computes its contents,
    advances `Facility.version` by 1 and re-derives the facility's posture — which by the first derivation
    rule becomes `FROZEN`, sealing the chargemaster against the writes listed in §2.7 for the duration of
    the build."
    PRD §2.7: "A `FROZEN` posture rejects six write operations with `ERR_FACILITY_FROZEN` (HTTP 409):
    creating a charge item, driving a charge item's lifecycle, repricing a charge item, creating a price
    rule, implementing an approved change request, and — for the code-update cycle — the `ACTIVATE` and
    `ROLL_BACK` actions."
    PRD §3.3: "On success `lifecycle_status` becomes `ACTIVE`; the facility's `active_item_count` increases
    by 1, its `aggregate_gross_charge_cents` increases by the item's `gross_charge_cents`, its
    `aggregate_cost_basis_cents` increases by the item's `cost_basis_cents`, `aggregate_markup_ratio_bp` is
    recomputed, `transparency_status` is set to `NEEDS_REFRESH`, `chargemaster_posture` is re-derived, and
    `Facility.version` advances by 1."

    Design: Corner/consistency_model/every_write_response_already_carries_the_recomputed_derived_state_with_no_read_lag
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    item = create_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                       code_type="CPT", code_value="93458", cost_basis_cents=100000,
                       medicare_rate_cents=50000, market_p75_cents=900000,
                       effective_from="2026-09-01T00:00:00Z")
    priced = reprice_item(item["id"])
    assert priced["gross_charge_cents"] == 240000, "the reprice response carries the price itself"
    assert priced["price_status"] == "PRICED_CURRENT"
    immediate = read_item(item["id"])
    assert immediate["gross_charge_cents"] == priced["gross_charge_cents"]
    assert immediate["price_status"] == priced["price_status"]

    item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW")
    assert item_lifecycle(item["id"], "APPROVE")["lifecycle_status"] == "APPROVED"
    activated = item_lifecycle(item["id"], "ACTIVATE")
    assert activated["lifecycle_status"] == "ACTIVE"
    assert activated["version"] == 5

    contract = create_payer_contract(
        facility_id, payer_code="BCBS", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=6000,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2027-12-31T23:59:59Z",
        renegotiation_notice_days=30, trailing_units=100)
    assert contract["status"] == "ACTIVE", "one payer column, so validation has something to emit"

    after_activate = read_facility(facility_id)
    assert after_activate["active_item_count"] == 1, "the very next read already counts it"
    assert after_activate["aggregate_gross_charge_cents"] == 240000
    assert after_activate["chargemaster_posture"] == "OPEN"
    assert after_activate["transparency_status"] == "NEEDS_REFRESH"

    built = build_transparency_file(facility_id, after_activate["version"], file_format="CSV")
    assert built["status"] == "BUILDING", "the create response reports the build state"
    assert read_facility(facility_id)["chargemaster_posture"] == "FROZEN", (
        "the posture is already frozen on the call immediately after the build, with nothing between"
    )
    validate_error(
        api_client.create_charge_item(
            factories.create_charge_item_payload(
                facility_id, base["department"]["id"], base["revenue_code"]["id"],
                cdm_number="CDM-2002", description="CARDIAC CATH COMPLEX", code_type="CPT",
                code_value="93460", cost_basis_cents=100000, medicare_rate_cents=50000,
                market_p75_cents=900000, effective_from="2026-09-01T00:00:00Z"), ANALYST),
        ApiErrorId.ERR_FACILITY_FROZEN.value, 409,
    )
    assert read_file(built["id"])["status"] == "BUILDING"

    validated = file_lifecycle(built["id"], "VALIDATE")
    assert validated["status"] == "VALIDATED"
    assert validated["included_item_count"] == 1
    assert read_facility(facility_id)["chargemaster_posture"] == "FROZEN", (
        "VALIDATED freezes just as BUILDING does, so the read tracks the exact state"
    )

    published = file_lifecycle(built["id"], "PUBLISH")
    assert published["status"] == "PUBLISHED"
    thawed = read_facility(facility_id)
    assert thawed["chargemaster_posture"] == "OPEN", "the thaw is equally immediate"
    assert thawed["transparency_status"] == "CURRENT"
    assert thawed["published_transparency_file_id"] == built["id"]
