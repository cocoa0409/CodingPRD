"""Home assessment, condition score, repair line items, and the round-per-line
repair-credit aggregation (with its cap).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_seller_headers,
    set_clock,
    setup_accepted_transaction,
    setup_finalized_assessment,
    setup_scheduled_transaction,
    add_repair_line_items,
    finalize_assessment,
    schedule_close,
    create_repair_line_item_payload,
    STANDARD_REPAIR_LINES,
)

_ANALYST = TEST_USERS["pricing_analyst_headers"]
_ADMIN = TEST_USERS["operations_admin_headers"]


def test_repair_line_item_computes_rounded_amount(api):
    """PRD §3.4: "On creation the platform pins each line's `rounded_amount` as its
    `estimate_amount` rounded half-up to two decimal places; this per-line rounding
    is fixed before the line ever contributes to a repair-credit sum."

    Design: Corner/entities/repair_line_item_computes_rounded_amount
    """
    seller, prop, offer, txn, assessment = setup_accepted_transaction()
    data = validate_success(
        api.create_repair_line_item(
            assessment["id"],
            create_repair_line_item_payload("COSMETIC", 2500.555),
            _ADMIN,
        ),
        201,
    )
    assert data["rounded_amount"] == 2500.56, data["rounded_amount"]


def test_finalize_assessment_computes_worst_condition_score(api):
    """PRD §3.4: "the assessment computes its `condition_score` as the worst of the
    three component conditions — the lowest rank across roof, HVAC, and foundation,
    treating `POOR` as worst and `EXCELLENT` as best — and writes that same value
    back onto the property's `condition_score`."

    Design: Corner/entities/finalize_assessment_computes_worst_condition_score
    """
    seller, prop, offer, txn, assessment = setup_accepted_transaction()
    finalized = validate_success(
        api.finalize_assessment(
            assessment["id"],
            {
                "roof_condition": "GOOD",
                "hvac_condition": "POOR",
                "foundation_condition": "EXCELLENT",
            },
            _ADMIN,
        )
    )
    assert finalized["condition_score"] == "POOR", finalized["condition_score"]
    assert finalized["status"] == "FINALIZED"
    prop_after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert prop_after["condition_score"] == "POOR", prop_after["condition_score"]


def test_repair_credit_round_per_line_then_sum(api):
    """PRD §3.5: "the transaction sets its `repair_credit` to the sum of the
    `rounded_amount` of every repair line item belonging to the finalized assessment
    — each line already rounded to cents, then those rounded cents summed, with the
    total itself carried to two decimal places (round-per-line, then sum; line items
    belonging to a still-`DRAFT` assessment are excluded)."

    Design: Difficulty/combinatorial_formula/repair_credit_round_per_line_then_sum_mode_b
    """
    seller, prop, offer, txn, assessment, line_items = setup_scheduled_transaction(
        repair_lines=STANDARD_REPAIR_LINES,
        leaseback_days=0,
        final_concession=0,
    )
    # round-per-line: 1234.57 + 899.99 + 4500.01 = 6634.57 (sum-then-round would be 6634.56).
    assert txn["repair_credit"] == 6634.57, txn["repair_credit"]


def test_repair_line_first_item_rounded_to_cents(api):
    """PRD §3.4: "On creation the platform pins each line's `rounded_amount` as its
    `estimate_amount` rounded half-up to two decimal places; this per-line rounding
    is fixed before the line ever contributes to a repair-credit sum."

    Design: Difficulty/combinatorial_formula/repair_credit_round_per_line_then_sum_mode_b
    """
    seller, prop, offer, txn, assessment = setup_accepted_transaction()
    lines = add_repair_line_items(assessment["id"], STANDARD_REPAIR_LINES)
    # First line estimate 1234.567 rounds half-up to 1234.57.
    assert lines[0]["rounded_amount"] == 1234.57, lines[0]["rounded_amount"]


def test_repair_credit_exceeds_cap_rejected(api):
    """PRD §3.5: "Finally, the computed repair credit must not exceed ten percent of
    the offer's `avm_value_snapshot`; a credit above that cap is rejected with
    `ERR_REPAIR_CREDIT_EXCEEDS_CAP`."

    Design: Corner/calculations/repair_credit_exceeds_cap_rejected
    """
    seller, prop, offer, txn, assessment, _ = setup_finalized_assessment(
        repair_lines=[("FOUNDATION", 50000.00), ("ROOF", 1000.01)],
        roof_condition="POOR",
        hvac_condition="POOR",
        foundation_condition="POOR",
    )
    # avm=510000 -> cap=51000.00; lines sum to 51000.01 > cap.
    validate_error(
        api.schedule_close(
            txn["id"],
            {"close_date": "2026-03-15T00:00:00Z", "leaseback_days": 0, "final_concession": 0},
            make_seller_headers(seller["id"]),
        ),
        ApiErrorId.ERR_REPAIR_CREDIT_EXCEEDS_CAP,
    )


def test_finalize_already_finalized_returns_invalid_state(api):
    """PRD §3.4: "The assessment moves `DRAFT → FINALIZED`"
    PRD §3.7: "A close attempted on a transaction that is not in `INSPECTION`, like
    any other transition attempted from an invalid state, is rejected with
    `ERR_INVALID_STATE`"

    Design: Corner/state_machines/finalize_already_finalized_assessment_returns_invalid_state
    """
    seller, prop, offer, txn, assessment, _ = setup_finalized_assessment()
    validate_error(
        api.finalize_assessment(
            assessment["id"],
            {"roof_condition": "GOOD", "hvac_condition": "GOOD", "foundation_condition": "GOOD"},
            _ADMIN,
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )


def test_schedule_close_before_finalize_rejected(api):
    """PRD §3.5: "The linked assessment must already be `FINALIZED`; if it is not, the
    request is rejected with `ERR_ASSESSMENT_NOT_FINALIZED`."

    Design: Difficulty/cross_entity_state_dependency/schedule_close_depends_on_assessment_finalized_txn_vs_assessment
    """
    seller, prop, offer, txn, assessment = setup_accepted_transaction()
    # Assessment still DRAFT.
    validate_error(
        api.schedule_close(
            txn["id"],
            {"close_date": "2026-03-15T00:00:00Z", "leaseback_days": 0, "final_concession": 0},
            make_seller_headers(seller["id"]),
        ),
        ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZED,
    )


def test_schedule_close_after_finalize_succeeds(api):
    """PRD §3.4: "only at this point does the transaction's repair credit become
    computable from them."
    PRD §3.5: "The linked assessment must already be `FINALIZED`; if it is not, the
    request is rejected with `ERR_ASSESSMENT_NOT_FINALIZED`."

    Design: Difficulty/cross_entity_state_dependency/schedule_close_depends_on_assessment_finalized_txn_vs_assessment
    """
    seller, prop, offer, txn, assessment, _ = setup_finalized_assessment()
    scheduled = validate_success(
        api.schedule_close(
            txn["id"],
            {"close_date": "2026-03-15T00:00:00Z", "leaseback_days": 0, "final_concession": 0},
            make_seller_headers(seller["id"]),
        )
    )
    assert scheduled["status"] == "SCHEDULED", scheduled["status"]
