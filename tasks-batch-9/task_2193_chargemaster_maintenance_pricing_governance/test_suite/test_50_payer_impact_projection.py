"""The reimbursement helper, the unit bases of the two variants, and the payer-line ordering."""
from test_helpers import (
    api_client, validate_success,
    setup_base, create_active_item, create_payer_contract, create_change_request,
    create_analysis, create_batch, append_line, reconcile_batch, batch_lifecycle,
    read_facility, set_clock,
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

ITEM = dict(
    cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
    code_type="CPT", code_value="93458", cost_basis_cents=100000,
    medicare_rate_cents=50000, market_p75_cents=900000,
    effective_from="2026-09-01T00:00:00Z",
)


def _read_contract(contract_id: str) -> dict:
    return validate_success(api_client.get_payer_contract(contract_id, CONTRACT), 200)


def test_forward_projection_grows_units_and_prices_all_three_methods():
    """PRD §3.6: "Under `PERCENT_OF_CHARGE`, it is the charge multiplied by the contract's
    `percent_of_charge_bp`, divided by 10000, rounded half up. Under `LESSER_OF_FEE_SCHEDULE`, that
    same percentage amount is computed and the smaller of it and the contract's `fee_schedule_cents`
    is taken. Under `CASE_RATE`, it is the contract's `case_rate_cents` — which is charge-independent,
    so a case-rate payer's delta is always zero. The per-unit amount is rounded **first** and only
    then multiplied by the unit count; multiplying before rounding gives a different answer."
    PRD §3.6: "Under **`FORWARD_PROJECTED`**, the contract set is every `PayerContract` of the item's
    facility whose `status` is `ACTIVE` and whose closed term contains the logical now (its
    `term_start_date` at or before now and its `term_end_date` at or after now), ordered by
    `payer_code` ascending then `product_line` ascending, never by `id`. For each contract, the unit
    count is that contract's `trailing_units` multiplied by the facility's `volume_growth_bp`,
    divided by 10000, rounded half up."
    PRD §3.6: "A payer whose `trailing_units` is zero still emits a line, with `units` of 0."

    Design: Corner/calculations/payer_impact_forward_projected_scales_units_and_applies_all_three_reimbursement_methods
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    item = create_active_item(base, **ITEM)
    assert item["gross_charge_cents"] == 240000 and item["version"] == 5
    facility_id = base["facility"]["id"]
    assert read_facility(facility_id)["volume_growth_bp"] == 10500

    create_payer_contract(
        facility_id, payer_code="AETNA", product_line="COMMERCIAL",
        reimbursement_method="LESSER_OF_FEE_SCHEDULE", percent_of_charge_bp=6000,
        fee_schedule_cents=200000, trailing_units=50,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
    )
    bcbs = create_payer_contract(
        facility_id, payer_code="BCBS", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=6000,
        trailing_units=100,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
    )
    create_payer_contract(
        facility_id, payer_code="MCARE", product_line="MEDICARE_ADVANTAGE",
        reimbursement_method="CASE_RATE", percent_of_charge_bp=None,
        case_rate_cents=150000, trailing_units=10,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
    )
    create_payer_contract(
        facility_id, payer_code="UHC", product_line="MEDICAID_MCO",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=5000,
        trailing_units=0,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
    )
    cigna = create_payer_contract(
        facility_id, payer_code="CIGNA", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=7000,
        trailing_units=80,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-09-05T23:59:59Z",
    )

    set_clock("2026-09-06T00:00:00Z")
    assert _read_contract(cigna["id"])["status"] == "EXPIRED", "the clock passed its term end"
    assert _read_contract(bcbs["id"])["status"] == "ACTIVE"

    request = create_change_request(
        base, item["id"], "PRICE_CHANGE",
        justification="Supply cost increase from the new catheter contract",
        proposed_cost_basis_cents=300000,
    )
    assert request["projected_gross_charge_cents"] == 540000

    analysis = create_analysis(request["id"], "FORWARD_PROJECTED")
    assert analysis["status"] == "COMPUTED"
    assert analysis["variant"] == "FORWARD_PROJECTED"
    assert analysis["analysed_charge_item_version"] == 5
    assert analysis["old_gross_charge_cents"] == 240000
    assert analysis["new_gross_charge_cents"] == 540000

    lines = analysis["payer_lines"]
    assert len(lines) == 4, "the EXPIRED CIGNA term is excluded entirely"
    assert [line["payer_code"] for line in lines] == ["AETNA", "BCBS", "MCARE", "UHC"]

    assert lines[0]["units"] == 53, "50 grown by 10500 bp is 52.5, which rounds half up"
    assert lines[0]["old_reimbursement_cents"] == 7632000, "144000 per unit is under the 200000 fee"
    assert lines[0]["new_reimbursement_cents"] == 10600000, "324000 per unit is capped at 200000"
    assert lines[0]["delta_cents"] == 2968000

    assert lines[1]["units"] == 105
    assert lines[1]["delta_cents"] == 18900000, "the percentage payer scales freely"

    assert lines[2]["units"] == 11, "10 grown to 10.5 rounds half up"
    assert lines[2]["old_reimbursement_cents"] == 1650000
    assert lines[2]["delta_cents"] == 0, "a case rate is charge-independent"

    assert lines[3]["units"] == 0, "a zero-utilization payer still emits a line"
    assert lines[3]["delta_cents"] == 0

    assert analysis["total_reimbursement_delta_cents"] == 21868000


def test_the_two_variants_disagree_because_only_one_reads_captured_volume():
    """PRD §3.6: "Under **`HISTORICAL_REPLAY`**, the input is real captured volume rather than a
    projection. The line set is every `CapturedCharge` whose `charge_item_id` is the target item,
    whose owning batch has `status` of `RECONCILED` or `CLOSED`, whose `match_status` is `MATCHED` or
    `PRICE_VARIANCE`, and whose `service_datetime` falls inside the lookback window — from the
    logical now less the facility's `impact_lookback_days` days up to the logical now, with **both**
    ends inclusive."
    PRD §3.6: "Otherwise the line accumulates into a bucket keyed by `(payer_code, product_line)`:
    the bucket's `units` increases by the line's `quantity`, its old reimbursement increases by the
    helper applied to the old gross charge at that quantity, and its new reimbursement increases by
    the helper applied to the new gross charge at that quantity. One line is emitted per bucket,
    ordered by `payer_code` ascending then `product_line` ascending. A payer with no captured lines
    in the window emits no line at all."
    PRD §3.6: "`payer_lines` holds the emitted array in that order, and
    `total_reimbursement_delta_cents` is the sum of the per-line `delta_cents` values — each delta
    already rounded, so the rule is round per line and then sum."

    Design: Corner/calculations/payer_impact_two_variants_on_identical_data_return_25200000_and_540000
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    item = create_active_item(base, **ITEM)
    facility_id = base["facility"]["id"]
    assert read_facility(facility_id)["impact_lookback_days"] == 90

    create_payer_contract(
        facility_id, payer_code="BCBS", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=6000,
        trailing_units=100,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
    )
    create_payer_contract(
        facility_id, payer_code="AETNA", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=5000,
        trailing_units=40,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
    )

    set_clock("2026-09-10T00:00:00Z")
    batch = create_batch(base, window_start_date="2026-09-01T00:00:00Z",
                         window_end_date="2026-09-07T00:00:00Z")
    append_line(batch["id"], "CDM-1001", base["manager_headers"], encounter_id="ENC-1",
                payer_code="BCBS", service_datetime="2026-09-02T08:00:00Z", quantity=2,
                posted_charge_cents=480000)
    append_line(batch["id"], "CDM-1001", base["manager_headers"], encounter_id="ENC-2",
                payer_code="BCBS", service_datetime="2026-09-03T08:00:00Z", quantity=1,
                posted_charge_cents=240000)
    reconcile_batch(batch["id"])
    reconciled = batch_lifecycle(batch["id"], "FINALIZE")
    assert reconciled["status"] == "RECONCILED"

    request = create_change_request(
        base, item["id"], "PRICE_CHANGE",
        justification="Supply cost increase from the new catheter contract",
        proposed_cost_basis_cents=300000,
    )
    assert request["projected_gross_charge_cents"] == 540000

    forward = create_analysis(request["id"], "FORWARD_PROJECTED")
    replay = create_analysis(request["id"], "HISTORICAL_REPLAY")
    assert forward["status"] == "COMPUTED" and replay["status"] == "COMPUTED"

    forward_lines = forward["payer_lines"]
    assert len(forward_lines) == 2
    assert forward_lines[0]["payer_code"] == "AETNA"
    assert forward_lines[0]["units"] == 42, "40 grown by 10500 bp"
    assert forward_lines[0]["delta_cents"] == 6300000
    assert forward_lines[1]["units"] == 105
    assert forward_lines[1]["delta_cents"] == 18900000
    assert forward["total_reimbursement_delta_cents"] == 25200000

    replay_lines = replay["payer_lines"]
    assert len(replay_lines) == 1, "AETNA captured nothing, so it emits no line at all"
    assert replay_lines[0]["payer_code"] == "BCBS"
    assert replay_lines[0]["units"] == 3, "the two captured quantities accumulate"
    assert replay_lines[0]["old_reimbursement_cents"] == 432000
    assert replay_lines[0]["new_reimbursement_cents"] == 972000
    assert replay_lines[0]["delta_cents"] == 540000
    assert replay["total_reimbursement_delta_cents"] == 540000
    assert replay["analysed_charge_item_version"] == 5

    assert forward["total_reimbursement_delta_cents"] != replay["total_reimbursement_delta_cents"], (
        "the two variants deliberately disagree on identical data"
    )
