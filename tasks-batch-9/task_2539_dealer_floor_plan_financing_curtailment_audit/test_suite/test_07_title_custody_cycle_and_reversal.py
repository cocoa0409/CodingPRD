"""The two unit dimensions in motion: a lost-and-recovered title and a reversed disbursement."""
from test_helpers import (
    CO,
    ApiErrorId,
    api_client,
    assert_credit_line_capacity_identity,
    assert_inventory_unit,
    credit_line_version,
    floor_unit,
    list_unit_obligations,
    move_title_custody,
    read_credit_line,
    read_unit,
    reverse_advance_payload,
    setup_active_line,
    unit_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)

NEW_TIER_1000 = {
    "inventory_class": "NEW",
    "age_days_from": 90,
    "age_days_to": None,
    "cumulative_paydown_bps": 1000,
}
USED_TIER_1500 = {
    "inventory_class": "USED",
    "age_days_from": 90,
    "age_days_to": None,
    "cumulative_paydown_bps": 1500,
}


def _floored_unit_with_a_vaulted_title():
    """One FLOORED unit of 3,000,000 cents whose document sits in lender custody."""
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={"legal_name": "Emerald Title Motors LLC", "state_code": "WA"},
    )
    unit = floor_unit(
        ctx["dealer"]["id"],
        ctx["credit_line"]["id"],
        "TITLEUNIT0000010",
        dealer_headers=ctx["dealer_headers"],
        requested_amount_cents=3000000,
        document_reference="MSO-0007",
        disbursement_reference="WIRE-0007",
        invoice_amount_cents=3000000,
        odometer_miles=14,
    )["unit"]
    assert unit["title_custody_status"] == "LENDER_HELD"
    assert unit["eligibility_status"] == "ELIGIBLE"
    assert unit["funding_status"] == "FLOORED"
    return {"line_id": ctx["credit_line"]["id"], "unit": unit}


def test_losing_the_document_drops_the_unit_out_of_the_borrowing_base():
    """The title dimension moves to LOST and drags eligibility with it, alone.

    PRD: "Whether the unit was `NOT_RECEIVED` or `LENDER_HELD`, moving to `LOST` sets `eligibility_status` to `INELIGIBLE_TITLE_DEFECT` and `ineligibility_reason_code` to `TITLE_DEFECT`, then recomputes the line's `eligible_collateral_cents` and `borrowing_base_deficiency_cents`."

    Design: Difficulty/non_linear_state_machine/unit_title_dimension_cycles_lost_and_back_while_funding_dimension_holds
    """
    ctx = _floored_unit_with_a_vaulted_title()
    lost = move_title_custody(ctx["unit"]["id"], "LOST", "LOSS-REPORT-0007")
    assert_inventory_unit(lost)
    assert lost["title_custody_status"] == "LOST"
    assert lost["funding_status"] == "FLOORED"
    assert lost["eligibility_status"] == "INELIGIBLE_TITLE_DEFECT"
    assert lost["ineligibility_reason_code"] == "TITLE_DEFECT"
    assert lost["outstanding_principal_cents"] == 3000000

    line = read_credit_line(ctx["line_id"])
    assert line["outstanding_principal_cents"] == 3000000
    assert line["eligible_collateral_cents"] == 0
    assert line["borrowing_base_deficiency_cents"] == 3000000
    assert line["available_credit_cents"] == 497000000
    assert_credit_line_capacity_identity(line)


def test_recovering_the_document_puts_the_unit_back_into_the_borrowing_base():
    """A duplicate document restores eligibility and clears the reason code.

    PRD: "Recovering the document — moving `LOST` back to `LENDER_HELD` — restores `eligibility_status` to `ELIGIBLE` and clears `ineligibility_reason_code` to null, **but only when the recorded reason was `TITLE_DEFECT`**: a unit that was also flagged for damage or wholesale disposal stays ineligible for that other reason, and the recovery does not launder it back into the borrowing base."

    Design: Difficulty/non_linear_state_machine/unit_title_dimension_cycles_lost_and_back_while_funding_dimension_holds
    """
    ctx = _floored_unit_with_a_vaulted_title()
    move_title_custody(ctx["unit"]["id"], "LOST", "LOSS-REPORT-0007")

    recovered = move_title_custody(
        ctx["unit"]["id"], "LENDER_HELD", "MSO-0007-REPLACEMENT"
    )
    assert recovered["title_custody_status"] == "LENDER_HELD"
    assert recovered["eligibility_status"] == "ELIGIBLE"
    assert recovered["ineligibility_reason_code"] is None
    assert recovered["funding_status"] == "FLOORED"

    line = read_credit_line(ctx["line_id"])
    assert line["eligible_collateral_cents"] == 3000000
    assert line["borrowing_base_deficiency_cents"] == 0
    assert line["available_credit_cents"] == 497000000
    assert_credit_line_capacity_identity(line)


def test_the_money_dimension_never_moves_while_the_document_travels():
    """funding_status stays FLOORED and available credit stays 497,000,000 across both hops.

    PRD: "A `FLOORED` unit may lose its title, and a merely `REGISTERED` unit may already be `LENDER_HELD`."

    Design: Difficulty/non_linear_state_machine/unit_title_dimension_cycles_lost_and_back_while_funding_dimension_holds
    """
    ctx = _floored_unit_with_a_vaulted_title()
    checkpoints = [read_unit(ctx["unit"]["id"])]
    availability = [read_credit_line(ctx["line_id"])["available_credit_cents"]]

    move_title_custody(ctx["unit"]["id"], "LOST", "LOSS-REPORT-0007")
    checkpoints.append(read_unit(ctx["unit"]["id"]))
    availability.append(read_credit_line(ctx["line_id"])["available_credit_cents"])

    move_title_custody(ctx["unit"]["id"], "LENDER_HELD", "MSO-0007-REPLACEMENT")
    checkpoints.append(read_unit(ctx["unit"]["id"]))
    availability.append(read_credit_line(ctx["line_id"])["available_credit_cents"])

    assert [unit["funding_status"] for unit in checkpoints] == [
        "FLOORED",
        "FLOORED",
        "FLOORED",
    ]
    assert [unit["outstanding_principal_cents"] for unit in checkpoints] == [
        3000000,
        3000000,
        3000000,
    ]
    assert availability == [497000000, 497000000, 497000000]
    assert [unit["title_custody_status"] for unit in checkpoints] == [
        "LENDER_HELD",
        "LOST",
        "LENDER_HELD",
    ]


def _two_funded_units_on_one_line():
    """A NEW unit at 3,000,000 and a USED unit at 1,800,000 sharing one facility."""
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000, USED_TIER_1500],
        dealer_overrides={"legal_name": "Ledger Drift Motors LLC", "state_code": "CO"},
    )
    line_id = ctx["credit_line"]["id"]
    unit_a = floor_unit(
        ctx["dealer"]["id"],
        line_id,
        "DRIFTUNITA000010",
        dealer_headers=ctx["dealer_headers"],
        requested_amount_cents=3000000,
        document_reference="MSO-0019A",
        disbursement_reference="WIRE-0019A",
        invoice_amount_cents=3000000,
        odometer_miles=6,
    )
    unit_b = floor_unit(
        ctx["dealer"]["id"],
        line_id,
        "DRIFTUNITB000010",
        dealer_headers=ctx["dealer_headers"],
        requested_amount_cents=2000000,
        document_reference="TITLE-0019B",
        disbursement_reference="WIRE-0019B",
        inventory_class="USED",
        invoice_amount_cents=2000000,
        odometer_miles=42000,
        title_document_type="TITLE",
    )
    assert unit_a["advance"]["approved_advance_amount_cents"] == 3000000
    assert unit_b["advance"]["approved_advance_amount_cents"] == 1800000
    return {"line_id": line_id, "unit_a": unit_a, "unit_b": unit_b}


def _reverse(advance_id, line_id):
    """Reverse a disbursement with the live line version, returning the raw response."""
    return api_client.reverse_advance(
        advance_id,
        reverse_advance_payload(credit_line_version(line_id), "FUNDING_ERROR"),
        CO,
    )


def test_reversing_one_disbursement_restores_capacity_without_drift():
    """4,800,000 outstanding falls back to 1,800,000 and availability returns exactly.

    PRD: "Reversal is the compensating action for a disbursement booked in error, and it is the only way out of `FUNDED`."

    Design: Difficulty/compensating_invariant/credit_limit_capacity_identity_survives_a_funding_reversal_without_drift
    """
    ctx = _two_funded_units_on_one_line()
    before = read_credit_line(ctx["line_id"])
    assert before["outstanding_principal_cents"] == 4800000
    assert before["available_credit_cents"] == 495200000
    assert before["charged_off_principal_cents"] == 0
    assert_credit_line_capacity_identity(before)

    reversed_advance = validate_success(
        _reverse(ctx["unit_a"]["advance"]["id"], ctx["line_id"])
    )
    assert reversed_advance["status"] == "REVERSED"
    assert reversed_advance["reason_code"] == "FUNDING_ERROR"

    after = read_credit_line(ctx["line_id"])
    assert after["outstanding_principal_cents"] == 1800000
    assert after["available_credit_cents"] == 498200000
    assert after["charged_off_principal_cents"] == 0
    assert after["class_outstanding_cents_used"] == 1800000
    assert after["class_outstanding_cents_demonstrator"] == 0
    assert_credit_line_capacity_identity(after)


def test_the_reversed_unit_is_zeroed_and_its_ladder_is_cancelled():
    """The unit goes back to REGISTERED with every scheduled obligation cancelled.

    PRD: "A reversal moves the advance `FUNDED → REVERSED`, returns the unit `FLOORED → REGISTERED` with `advance_amount_cents` and `outstanding_principal_cents` reset to 0, `floored_at` cleared to null and `funded_by_user_id` cleared to null, cancels every obligation of the unit still in `SCHEDULED` (processed in `due_date` ascending then `created_at` ascending order), and recomputes the line's capacity figures so that `available_credit_cents` reads exactly what it read before the disbursement."

    Design: Difficulty/compensating_invariant/credit_limit_capacity_identity_survives_a_funding_reversal_without_drift
    """
    ctx = _two_funded_units_on_one_line()
    unit_id = ctx["unit_a"]["unit"]["id"]
    assert len(list_unit_obligations(unit_id)) == 1

    _reverse(ctx["unit_a"]["advance"]["id"], ctx["line_id"])

    unit = read_unit(unit_id)
    assert unit["funding_status"] == "REGISTERED"
    assert unit["advance_amount_cents"] == 0
    assert unit["outstanding_principal_cents"] == 0
    assert unit["floored_at"] is None
    assert unit["funded_by_user_id"] is None

    obligations = list_unit_obligations(unit_id)
    assert obligations != []
    assert all(row["status"] == "CANCELLED" for row in obligations)
    scheduled, meta = validate_paginated(
        api_client.list_curtailment_obligations(
            CO, params={"unit_id": unit_id, "status": "SCHEDULED"}
        )
    )
    assert meta["total_count"] == 0
    assert scheduled == []


def test_the_other_unit_is_untouched_and_a_second_reversal_is_refused():
    """No second credit restoration, and the surviving unit keeps its own ladder.

    PRD: "The advance must be in `FUNDED` — anything else is `ERR_ADVANCE_NOT_PENDING` — and four conditions must all hold: the logical clock must be no later than `funded_at` plus 5 days, the unit's `principal_paid_cents` must be exactly 0, the unit must carry no observation on any audit, and no obligation of the unit may be in `DUE`, `DELINQUENT` or `PAID`."

    Design: Difficulty/compensating_invariant/credit_limit_capacity_identity_survives_a_funding_reversal_without_drift
    """
    ctx = _two_funded_units_on_one_line()
    _reverse(ctx["unit_a"]["advance"]["id"], ctx["line_id"])

    unit_b = read_unit(ctx["unit_b"]["unit"]["id"])
    assert unit_b["funding_status"] == "FLOORED"
    assert unit_b["advance_amount_cents"] == 1800000
    assert unit_b["outstanding_principal_cents"] == 1800000
    schedule = unit_schedule(ctx["unit_b"]["unit"]["id"])
    assert len(schedule["projected_obligations"]) == 1
    assert schedule["projected_obligations"][0]["projected_principal_cents"] == 270000
    surviving = list_unit_obligations(ctx["unit_b"]["unit"]["id"], status="SCHEDULED")
    assert len(surviving) == 1
    assert surviving[0]["projected_principal_cents"] == 270000

    line = read_credit_line(ctx["line_id"])
    assert line["eligible_collateral_cents"] == 1800000
    assert line["borrowing_base_deficiency_cents"] == 0

    validate_error(
        _reverse(ctx["unit_a"]["advance"]["id"], ctx["line_id"]),
        ApiErrorId.ERR_ADVANCE_NOT_PENDING,
        409,
    )
    unchanged = read_credit_line(ctx["line_id"])
    assert unchanged["outstanding_principal_cents"] == 1800000
    assert unchanged["available_credit_cents"] == 498200000
    assert_credit_line_capacity_identity(unchanged)
