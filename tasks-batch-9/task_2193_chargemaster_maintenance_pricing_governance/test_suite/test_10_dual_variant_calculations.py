"""Dual-variant calculations: payer impact projection modes and duplicate scoring modes."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    setup_payer_impact_scenario, setup_duplicate_pair_scenario,
    set_duplicate_detection_mode, row_references,
    read_item, read_facility, create_analysis,
)

CONTRACT = TEST_USERS["contract_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_forward_projected_analysis_scales_trailing_units_by_volume_growth():
    """PRD §3.6: "For each contract, the unit count is that contract's `trailing_units`
    multiplied by the facility's `volume_growth_bp`, divided by 10000, rounded half up."
    PRD §3.6: "A payer whose `trailing_units` is zero still emits a line, with `units` of 0."
    PRD §3.6: "Under `PERCENT_OF_CHARGE`, it is the charge multiplied by the contract's
    `percent_of_charge_bp`, divided by 10000, rounded half up."
    PRD §3.6: "Under `LESSER_OF_FEE_SCHEDULE`, that same percentage amount is computed and
    the smaller of it and the contract's `fee_schedule_cents` is taken."
    PRD §3.6: "Under `CASE_RATE`, it is the contract's `case_rate_cents` — which is
    charge-independent, so a case-rate payer's delta is always zero."

    Design: Difficulty/dual_variant_calc/dual_variant_calc__payer_impact_forward_vs_historical_on_payer_contract_domain
    """
    s = setup_payer_impact_scenario()
    item = read_item(s["item"]["id"])
    assert item["gross_charge_cents"] == 128000, (
        f"Expected gross_charge_cents 128000, got {item['gross_charge_cents']}"
    )
    cr = s["change_request"]
    assert cr["projected_gross_charge_cents"] == 159680
    assert cr["projected_markup_ratio_bp"] == 32000

    resp = api_client.create_price_change_analysis(
        {"change_request_id": cr["id"], "variant": "FORWARD_PROJECTED"}, CONTRACT
    )
    fwd = validate_success(resp, 201)
    assert fwd["status"] == "COMPUTED"
    assert fwd["old_gross_charge_cents"] == 128000
    assert fwd["new_gross_charge_cents"] == 159680

    lines = fwd["payer_lines"]
    assert len(lines) == 3, f"FORWARD_PROJECTED must emit one line per in-term contract, got {len(lines)}"
    assert lines[0]["payer_code"] == "AETNA_COMM"
    assert lines[0]["product_line"] == "COMMERCIAL"
    assert lines[0]["units"] == 7
    assert lines[0]["old_reimbursement_cents"] == 403200
    assert lines[0]["new_reimbursement_cents"] == 502992
    assert lines[0]["delta_cents"] == 99792

    assert lines[1]["payer_code"] == "BCBS_STATE"
    assert lines[1]["product_line"] == "COMMERCIAL"
    assert lines[1]["units"] == 14
    assert lines[1]["old_reimbursement_cents"] == 1075200
    assert lines[1]["new_reimbursement_cents"] == 1120000
    assert lines[1]["delta_cents"] == 44800

    assert lines[2]["payer_code"] == "MEDICAID_MCO_A"
    assert lines[2]["product_line"] == "MEDICAID_MCO"
    assert lines[2]["units"] == 0
    assert lines[2]["old_reimbursement_cents"] == 0
    assert lines[2]["new_reimbursement_cents"] == 0
    assert lines[2]["delta_cents"] == 0

    assert fwd["total_reimbursement_delta_cents"] == 144592, (
        f"Expected total 144592, got {fwd['total_reimbursement_delta_cents']}"
    )


def test_historical_replay_analysis_uses_captured_quantities_and_diverges_from_projection():
    """PRD §3.6: "Otherwise the line accumulates into a bucket keyed by
    `(payer_code, product_line)`: the bucket's `units` increases by the line's `quantity`,
    its old reimbursement increases by the helper applied to the old gross charge at that
    quantity, and its new reimbursement increases by the helper applied to the new gross
    charge at that quantity."
    PRD §3.6: "A payer with no captured lines in the window emits no line at all."
    PRD §3.6: "The two variants deliberately disagree on identical data: the forward
    projection prices every unit under today's contract, while the historical replay prices
    each unit under the contract that governed its service date, so a payer whose term
    expired mid-window contributes different numbers and the two totals differ."

    Design: Difficulty/dual_variant_calc/dual_variant_calc__payer_impact_forward_vs_historical_on_payer_contract_domain
    """
    s = setup_payer_impact_scenario()
    cr = s["change_request"]

    fwd = validate_success(
        api_client.create_price_change_analysis(
            {"change_request_id": cr["id"], "variant": "FORWARD_PROJECTED"}, CONTRACT
        ),
        201,
    )
    hist = validate_success(
        api_client.create_price_change_analysis(
            {"change_request_id": cr["id"], "variant": "HISTORICAL_REPLAY"}, CONTRACT
        ),
        201,
    )
    assert hist["status"] == "COMPUTED"
    lines = hist["payer_lines"]
    assert len(lines) == 2, (
        f"HISTORICAL_REPLAY emits no line for the zero-capture payer, got {len(lines)} lines"
    )
    assert lines[0]["payer_code"] == "AETNA_COMM"
    assert lines[0]["units"] == 3
    assert lines[0]["old_reimbursement_cents"] == 172800
    assert lines[0]["new_reimbursement_cents"] == 215568
    assert lines[0]["delta_cents"] == 42768

    assert lines[1]["payer_code"] == "BCBS_STATE"
    assert lines[1]["units"] == 2
    assert lines[1]["old_reimbursement_cents"] == 153600
    assert lines[1]["new_reimbursement_cents"] == 160000
    assert lines[1]["delta_cents"] == 6400

    assert hist["total_reimbursement_delta_cents"] == 49168, (
        f"Expected total 49168, got {hist['total_reimbursement_delta_cents']}"
    )
    assert (
        fwd["total_reimbursement_delta_cents"] != hist["total_reimbursement_delta_cents"]
    ), "The two variants must disagree on identical data"


def test_fuzzy_description_mode_rejects_a_0_7750_pair_as_below_threshold():
    """PRD §3.8: "Under **`FUZZY_DESCRIPTION`**, the score is the weighted sum of the code
    signal at weight 0.5, the description similarity at weight 0.3, and the revenue signal
    at weight 0.2, rounded half up to four decimal places."
    PRD §3.8: "And the similarity score between the item being retired and the surviving
    item must reach the threshold of 0.8000 under the facility's `duplicate_detection_mode`;
    a score below it is `ERR_DUPLICATE_SIMILARITY_TOO_LOW` (422)."

    Design: Difficulty/dual_variant_calc/dual_variant_calc__duplicate_similarity_strict_vs_fuzzy_on_charge_item_domain
    """
    s = setup_duplicate_pair_scenario("FUZZY_DESCRIPTION")
    subject, survivor = s["subject"], s["survivor"]

    resp = api_client.charge_item_lifecycle(
        subject["id"],
        {"action": "MARK_DUPLICATE", "duplicate_of_item_id": survivor["id"],
         "note": "fuzzy attempt"},
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SIMILARITY_TOO_LOW.value)

    after = read_item(subject["id"])
    assert after["lifecycle_status"] == "ACTIVE", "A refused MARK_DUPLICATE must not deactivate"
    assert after["duplicate_of_item_id"] is None

    rows, _meta = validate_paginated(
        api_client.get_duplicate_candidates(
            subject["id"], ANALYST, params={"min_score": 0.8, "limit": 50, "offset": 0}
        )
    )
    assert len(rows) == 0, (
        f"No FUZZY_DESCRIPTION candidate reaches 0.8000 for this pair, got {len(rows)} rows"
    )


def test_strict_code_mode_admits_the_same_pair_at_score_one_and_retires_the_subject():
    """PRD §3.8: "Under **`STRICT_CODE`**, the score is exactly 1.0000 when the code signal
    is 1 *and* the revenue signal is 1 *and* the two items share the same `department_id`,
    and exactly 0.0000 in every other case; two items with identical descriptions but
    different `code_value` strings can therefore never be marked duplicates."
    PRD §3.8: "On success `lifecycle_status` becomes `INACTIVE` and the item's `version`
    advances by 1; on the duplicate path, `duplicate_of_item_id` is set to the surviving
    item's identifier."
    PRD §3.8: "The same pair of items can therefore be a duplicate under one facility's
    mode and not under another's."

    Design: Difficulty/dual_variant_calc/dual_variant_calc__duplicate_similarity_strict_vs_fuzzy_on_charge_item_domain
    """
    s = setup_duplicate_pair_scenario("FUZZY_DESCRIPTION")
    subject, survivor = s["subject"], s["survivor"]

    set_duplicate_detection_mode(s["facility"]["id"], "STRICT_CODE")

    rows, _meta = validate_paginated(
        api_client.get_duplicate_candidates(
            subject["id"], ANALYST, params={"min_score": 0.8, "limit": 50, "offset": 0}
        )
    )
    assert len(rows) == 1, (
        f"STRICT_CODE scores this pair 1.0000, so exactly one candidate is expected, got {len(rows)}"
    )
    assert row_references(rows[0], survivor["id"]), (
        f"The single candidate must be the survivor {survivor['id']}, got {rows[0]}"
    )

    resp = api_client.charge_item_lifecycle(
        subject["id"],
        {"action": "MARK_DUPLICATE", "duplicate_of_item_id": survivor["id"],
         "note": "strict retry"},
        ANALYST,
    )
    updated = validate_success(resp, 200)
    assert updated["lifecycle_status"] == "INACTIVE"
    assert updated["duplicate_of_item_id"] == survivor["id"]

    assert read_item(survivor["id"])["lifecycle_status"] == "ACTIVE"

    facility = read_facility(s["facility"]["id"])
    assert facility["active_item_count"] == 1
    assert facility["aggregate_gross_charge_cents"] == 128000
    assert facility["aggregate_cost_basis_cents"] == 40000
    assert facility["aggregate_markup_ratio_bp"] == 32000
