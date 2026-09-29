"""Sign-off needs a COMPUTED analysis whose pinned item version still matches, and happens once."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_base, create_active_item, create_change_request, create_payer_contract,
    create_analysis, item_lifecycle, read_facility, set_clock,
    ANALYST, COMPLIANCE, CONTRACT, COMPLIANCE_USER_ID,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-SIGNOFF",
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


def _read_analysis(analysis_id: str) -> dict:
    return validate_success(api_client.get_price_change_analysis(analysis_id, COMPLIANCE), 200)


def _sign_off(analysis_id: str, payload=None):
    return api_client.sign_off_price_change_analysis(analysis_id, COMPLIANCE, payload or {})


def test_every_item_mutation_stales_the_analysis_and_a_signed_off_row_refuses_a_second_pass():
    """PRD §3.6: "Computation snapshots three values on the analysis row —
    `analysed_charge_item_version` (the target item's `version` at computation time),
    `old_gross_charge_cents` (the item's current `gross_charge_cents`) and `new_gross_charge_cents` (the
    request's `projected_gross_charge_cents`) — and lands the analysis in `COMPUTED`."
    PRD §3.6: "Two preconditions apply: the `status` must be `COMPUTED`, and
    `analysed_charge_item_version` must still equal the target item's live `ChargeItem.version`."
    PRD §3.6: "A sign-off attempted on an analysis whose `status` is `STALE`, or on a `COMPUTED` analysis
    whose pinned item version has moved, is refused with `ERR_ANALYSIS_SIGNOFF_STALE` (409); an attempt
    against an analysis in any other status surfaces as `ERR_INVALID_ANALYSIS_STATE` (409)."
    PRD §3.6: "`SIGNED_OFF` is terminal. The system-driven transition `COMPUTED → STALE` fires whenever
    the target item is mutated or a payer contract for the facility is created or terminated."
    PRD §2.4: "Most entities additionally carry `updated_at` (same format as `created_at`, refreshed on
    every mutation) and `version` (an integer that starts at 1 on creation and increases by exactly 1 on
    every mutation of that row)."

    Design: Corner/endpoints/analysis_sign_off_only_while_computed_and_version_matched_and_never_twice
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

    contract = create_payer_contract(
        facility_id, payer_code="AETNA", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=6000,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2027-12-31T00:00:00Z",
        trailing_units=100,
    )
    assert contract["status"] == "ACTIVE"

    request = create_change_request(
        base, item["id"], "PRICE_CHANGE",
        justification="Reagent cost increase confirmed by supply chain",
        proposed_cost_basis_cents=200000,
    )
    assert request["projected_gross_charge_cents"] == 480000
    assert request["projected_markup_ratio_bp"] == 24000, (
        "the ACTIVE item leaves the snapshot before the proposal is added"
    )

    first = create_analysis(request["id"], "FORWARD_PROJECTED")
    assert first["status"] == "COMPUTED"
    assert first["analysed_charge_item_version"] == 5
    assert first["old_gross_charge_cents"] == 240000
    assert first["new_gross_charge_cents"] == 480000
    assert first["total_reimbursement_delta_cents"] == 15120000, (
        "105 projected units at a per-unit delta of 288000 less 144000"
    )

    repriced = validate_success(api_client.reprice_charge_item(item["id"], ANALYST), 200)
    assert repriced["version"] == 6, "an idempotent reprice still counts as a mutation"
    assert repriced["gross_charge_cents"] == 240000
    assert repriced["prior_gross_charge_cents"] == 240000

    staled = _read_analysis(first["id"])
    assert staled["status"] == "STALE"
    assert staled["analysed_charge_item_version"] == 5, "the pinned snapshot is never refreshed"
    validate_error(_sign_off(first["id"], {"signoff_note": "Reviewed against contract exposure"}),
                   ApiErrorId.ERR_ANALYSIS_SIGNOFF_STALE.value, 409)

    second = create_analysis(request["id"], "FORWARD_PROJECTED", headers=ANALYST)
    assert second["analysed_charge_item_version"] == 6
    assert second["total_reimbursement_delta_cents"] == 15120000

    signed = validate_success(_sign_off(second["id"], {"signoff_note": "Exposure accepted"}), 200)
    assert signed["status"] == "SIGNED_OFF"
    assert signed["signed_off_by_user_id"] == COMPLIANCE_USER_ID
    assert signed["version"] == 2

    validate_error(_sign_off(second["id"]),
                   ApiErrorId.ERR_INVALID_ANALYSIS_STATE.value, 409)
    assert _read_analysis(second["id"])["signed_off_by_user_id"] == COMPLIANCE_USER_ID, (
        "the refused second sign-off changed nothing"
    )

    third = create_analysis(request["id"], "FORWARD_PROJECTED", headers=CONTRACT)
    assert third["analysed_charge_item_version"] == 6

    deactivated = item_lifecycle(item["id"], "DEACTIVATE", ANALYST)
    assert deactivated["lifecycle_status"] == "INACTIVE"
    assert deactivated["version"] == 7

    assert _read_analysis(third["id"])["status"] == "STALE", (
        "the mutation that desynchronised the pinned version also flipped the status"
    )
    validate_error(_sign_off(third["id"]), ApiErrorId.ERR_ANALYSIS_SIGNOFF_STALE.value, 409)
    assert _read_analysis(second["id"])["status"] == "SIGNED_OFF", (
        "the cascade only touches COMPUTED rows"
    )

    rows, meta = validate_paginated(api_client.list_price_change_analyses(
        COMPLIANCE, {"change_request_id": request["id"], "status": "STALE"}))
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], third["id"]}

    facility = read_facility(facility_id)
    assert facility["active_item_count"] == 0
    assert facility["aggregate_gross_charge_cents"] == 0
    assert validate_success(
        api_client.get_change_request(request["id"], COMPLIANCE), 200)["status"] == "SUBMITTED"
