"""Facility configuration round trip, and the analysis endpoints under payer-contract churn."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId, factories,
    setup_base, create_facility, create_active_item, create_change_request,
    create_payer_contract, create_analysis, patch_facility, set_clock,
    ADMIN, ANALYST, COMPLIANCE, CONTRACT, COMPLIANCE_USER_ID,
)


def _read_facility_as(facility_id: str, headers) -> dict:
    return validate_success(api_client.get_facility(facility_id, headers), 200)


def _read_analysis(analysis_id: str) -> dict:
    return validate_success(api_client.get_price_change_analysis(analysis_id, CONTRACT), 200)


def test_a_minimal_facility_materialises_every_default_and_one_patch_rewrites_three():
    """PRD §3.1: "`rounding_mode` defaults to `NEAREST_DOLLAR` and may instead be `NEAREST_CENT` or
    `PSYCHOLOGICAL_99`; it controls the final rounding step of every gross-charge computation.
    `aggregate_markup_limit_bp` defaults to 40000 basis points — a facility-wide ceiling of four times
    cost. `volume_growth_bp` defaults to 10500 basis points, a projected annual volume growth of five
    percent, and is consulted only by the forward-projected impact variant. `impact_lookback_days`
    defaults to 90 days and is consulted only by the historical-replay impact variant.
    `duplicate_detection_mode` defaults to `STRICT_CODE` and may instead be `FUZZY_DESCRIPTION`"
    PRD §3.1: "A newly created facility has `version` 1, all aggregates at 0, `chargemaster_posture` of
    `OPEN` and `transparency_status` of `NEEDS_REFRESH`; `published_transparency_file_id` is null."
    PRD §3.1: "All six knobs may be adjusted later by a `SystemAdmin`, and any such adjustment must
    carry `expected_facility_version`; a successful adjustment advances `Facility.version` by 1 and
    re-derives `chargemaster_posture`. A collision on `cms_certification_number` is reported as
    `ERR_DUPLICATE_KEY`."

    Design: Corner/endpoints/facility_create_read_patch_and_list_round_trip_with_every_default_materialised
    """
    set_clock("2026-09-01T00:00:00Z")
    created = create_facility(name="Mercy General", cms_certification_number="CCN-0001")
    assert created["rounding_mode"] == "NEAREST_DOLLAR"
    assert created["aggregate_markup_limit_bp"] == 40000
    assert created["volume_growth_bp"] == 10500
    assert created["impact_lookback_days"] == 90
    assert created["duplicate_detection_mode"] == "STRICT_CODE"
    assert created["chargemaster_posture"] == "OPEN"
    assert created["version"] == 1

    read_back = _read_facility_as(created["id"], ANALYST)
    assert read_back["rounding_mode"] == "NEAREST_DOLLAR"
    assert read_back["version"] == 1
    assert read_back["transparency_status"] == "NEEDS_REFRESH"

    validate_error(
        api_client.create_facility(
            factories.create_facility_payload(
                name="Mercy General Annex", cms_certification_number="CCN-0001"), ADMIN),
        ApiErrorId.ERR_DUPLICATE_KEY.value, 409,
    )

    patched = patch_facility(
        created["id"], rounding_mode="PSYCHOLOGICAL_99",
        aggregate_markup_limit_bp=25000, duplicate_detection_mode="FUZZY_DESCRIPTION",
    )
    assert patched["rounding_mode"] == "PSYCHOLOGICAL_99"
    assert patched["aggregate_markup_limit_bp"] == 25000
    assert patched["duplicate_detection_mode"] == "FUZZY_DESCRIPTION"
    assert patched["version"] == 2, "one PATCH advances the version exactly once"

    reread = _read_facility_as(created["id"], COMPLIANCE)
    assert reread["rounding_mode"] == "PSYCHOLOGICAL_99"
    assert reread["volume_growth_bp"] == 10500, "an untouched knob keeps its default"
    assert reread["version"] == 2
    assert reread["active_item_count"] == 0
    assert reread["aggregate_markup_ratio_bp"] == 0
    assert reread["published_transparency_file_id"] is None


def test_every_contract_write_stales_the_computed_analyses_and_blocks_sign_off():
    """PRD §3.6: "Creating a contract also transitions every `PriceChangeImpactAnalysis` of that
    facility whose `status` is `COMPUTED` to `STALE`, since the payer mix has changed."
    PRD §3.6: "Termination, which accepts an optional `termination_note`, sets `status` to `TERMINATED`
    and advances the contract's `version` by 1, and likewise transitions every `COMPUTED` impact
    analysis of the facility to `STALE`."
    PRD §3.6: "A sign-off attempted on an analysis whose `status` is `STALE`, or on a `COMPUTED`
    analysis whose pinned item version has moved, is refused with `ERR_ANALYSIS_SIGNOFF_STALE` (409)"
    PRD §3.6: "Under `LESSER_OF_FEE_SCHEDULE`, that same percentage amount is computed and the smaller
    of it and the contract's `fee_schedule_cents` is taken."

    Design: Corner/endpoints/contract_creation_and_termination_both_stale_computed_analyses_and_signoff_needs_a_computed_one
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(
        facility_overrides={
            "name": "Mercy General", "cms_certification_number": "CCN-2193-ANALYSIS",
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
    facility_id = base["facility"]["id"]
    item = create_active_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                             code_type="CPT", code_value="93458", cost_basis_cents=100000,
                             medicare_rate_cents=50000, market_p75_cents=900000,
                             effective_from="2026-09-01T00:00:00Z")
    assert item["gross_charge_cents"] == 240000

    aetna = create_payer_contract(
        facility_id, payer_code="AETNA", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=4000,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
        trailing_units=100,
    )
    request = create_change_request(
        base, item["id"], "PRICE_CHANGE",
        justification="Supply cost increase effective November",
        proposed_cost_basis_cents=120000,
    )
    assert request["projected_gross_charge_cents"] == 288000

    first = create_analysis(request["id"], "FORWARD_PROJECTED")
    assert first["status"] == "COMPUTED"
    assert first["total_reimbursement_delta_cents"] == 2016000, (
        "115200 less 96000, at 105 projected units"
    )

    create_payer_contract(
        facility_id, payer_code="BCBS", product_line="COMMERCIAL",
        reimbursement_method="LESSER_OF_FEE_SCHEDULE", percent_of_charge_bp=5000,
        fee_schedule_cents=100000, term_start_date="2026-02-01T00:00:00Z",
        term_end_date="2026-12-31T00:00:00Z", trailing_units=20,
    )
    assert _read_analysis(first["id"])["status"] == "STALE"

    validate_error(
        api_client.sign_off_price_change_analysis(
            first["id"], COMPLIANCE, {"signoff_note": "Reviewed"}),
        ApiErrorId.ERR_ANALYSIS_SIGNOFF_STALE.value, 409,
    )

    second = create_analysis(request["id"], "FORWARD_PROJECTED")
    lines = second["payer_lines"]
    assert [line["payer_code"] for line in lines] == ["AETNA", "BCBS"]
    assert lines[0]["delta_cents"] == 2016000
    assert lines[1]["delta_cents"] == 0, (
        "both percentage amounts exceed the 100000 fee schedule, so the cap holds both sides"
    )
    assert second["total_reimbursement_delta_cents"] == 2016000

    terminated = validate_success(api_client.terminate_payer_contract(
        aetna["id"], CONTRACT, {"termination_note": "Payer exited the market"}), 200)
    assert terminated["status"] == "TERMINATED"
    assert _read_analysis(second["id"])["status"] == "STALE"

    third = create_analysis(request["id"], "FORWARD_PROJECTED")
    assert [line["payer_code"] for line in third["payer_lines"]] == ["BCBS"], (
        "a TERMINATED contract leaves the forward-projected set"
    )
    assert third["total_reimbursement_delta_cents"] == 0
    assert third["old_gross_charge_cents"] == 240000
    assert third["new_gross_charge_cents"] == 288000

    signed = validate_success(api_client.sign_off_price_change_analysis(
        third["id"], COMPLIANCE, {"signoff_note": "Impact accepted"}), 200)
    assert signed["status"] == "SIGNED_OFF"
    assert signed["signed_off_by_user_id"] == COMPLIANCE_USER_ID

    rows, meta = validate_paginated(api_client.list_price_change_analyses(
        CONTRACT, {"change_request_id": request["id"]}))
    assert meta["total_count"] == 3
    assert {row["id"] for row in rows} == {first["id"], second["id"], third["id"]}
