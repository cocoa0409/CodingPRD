"""Disbursement: the four-step advance amount, the document gate and the capacity gates."""
from test_helpers import (
    CO,
    ApiErrorId,
    api_client,
    assert_credit_line_capacity_identity,
    assert_funding_advance,
    assert_utc_millisecond_timestamp,
    credit_line_version,
    file_covenant_test,
    floor_unit,
    fund_advance_payload,
    move_title_custody,
    read_credit_line,
    read_dealer,
    read_unit,
    register_unit,
    request_advance,
    setup_active_line,
    unit_schedule,
    validate_error,
    validate_success,
)

DEMO_TIER_2000 = {
    "inventory_class": "DEMONSTRATOR",
    "age_days_from": 90,
    "age_days_to": None,
    "cumulative_paydown_bps": 2000,
}
DEMO_TIER_1000 = {
    "inventory_class": "DEMONSTRATOR",
    "age_days_from": 90,
    "age_days_to": None,
    "cumulative_paydown_bps": 1000,
}
NEW_TIER_1000 = {
    "inventory_class": "NEW",
    "age_days_from": 90,
    "age_days_to": None,
    "cumulative_paydown_bps": 1000,
}


def _fund(advance_id, credit_line_id, reference):
    """Read the live line version and disburse, returning the raw response."""
    version = credit_line_version(credit_line_id)
    return api_client.fund_advance(
        advance_id, fund_advance_payload(version, reference), CO
    )


def test_a_demonstrator_stacks_both_rate_reductions_into_one_division():
    """3,001 miles and a 45-day-old invoice together strip 750 basis points before the single division.

    PRD: "Both reductions stack, so a demonstrator with 3,001 miles on a 45-day-old invoice loses 750 basis points in total."

    Design: Difficulty/combinatorial_formula/demonstrator_advance_stacks_mileage_and_aged_invoice_haircuts_mode_a
    """
    ctx = setup_active_line(tiers=[DEMO_TIER_2000])
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]
    unit = register_unit(
        dealer_id,
        line_id,
        "DEMOSTACK00000001",
        dealer_headers=ctx["dealer_headers"],
        inventory_class="DEMONSTRATOR",
        invoice_amount_cents=5000000,
        invoice_date="2026-06-17",
        odometer_miles=3001,
    )
    move_title_custody(unit["id"], "LENDER_HELD", "MSO-DEMOSTACK")
    advance = request_advance(
        unit["id"], ctx["dealer_headers"], 5000000, "INV-DEMOSTACK"
    )

    funded = validate_success(_fund(advance["id"], line_id, "WIRE-DEMOSTACK"))
    assert_funding_advance(funded)
    assert funded["status"] == "FUNDED"
    assert funded["invoice_age_days_at_funding"] == 45
    assert funded["effective_advance_rate_bps"] == 7750
    assert funded["rate_adjustment_codes"] == ["HIGH_MILEAGE_DEMO", "AGED_INVOICE"]
    assert funded["approved_advance_amount_cents"] == 3875000
    assert funded["funded_by_user_id"] == CO["X-User-ID"]
    assert_utc_millisecond_timestamp(funded["funded_at"], "funded_at")
    assert str(funded["funded_at"]).startswith("2026-08-01T00:00:00")


def test_the_stacked_demonstrator_advance_lands_in_the_class_aggregate_and_the_ladder():
    """The 3,875,000 cent advance drives the demonstrator class total and its projected rung.

    PRD: "`available_credit_cents` is `credit_limit_cents` reduced by `outstanding_principal_cents` and reduced again by `charged_off_principal_cents`."

    Design: Difficulty/combinatorial_formula/demonstrator_advance_stacks_mileage_and_aged_invoice_haircuts_mode_a
    """
    ctx = setup_active_line(tiers=[DEMO_TIER_2000])
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]
    floored = floor_unit(
        dealer_id,
        line_id,
        "DEMOSTACK00000001",
        dealer_headers=ctx["dealer_headers"],
        requested_amount_cents=5000000,
        document_reference="MSO-DEMOSTACK",
        inventory_class="DEMONSTRATOR",
        invoice_amount_cents=5000000,
        invoice_date="2026-06-17",
        odometer_miles=3001,
    )
    assert floored["advance"]["approved_advance_amount_cents"] == 3875000

    line = read_credit_line(line_id)
    assert line["outstanding_principal_cents"] == 3875000
    assert line["available_credit_cents"] == 496125000
    assert line["class_outstanding_cents_demonstrator"] == 3875000
    assert line["class_outstanding_cents_used"] == 0
    assert line["eligible_collateral_cents"] == 3875000
    assert line["borrowing_base_deficiency_cents"] == 0
    assert_credit_line_capacity_identity(line)

    schedule = unit_schedule(floored["unit"]["id"])
    assert schedule["basis"] == "FORWARD_PROJECTED"
    assert schedule["advance_amount_cents"] == 3875000
    assert len(schedule["projected_obligations"]) == 1
    rung = schedule["projected_obligations"][0]
    assert rung["projected_principal_cents"] == 775000
    assert str(rung["due_date"]).startswith("2026-10-30")
    assert schedule["projected_total_required_cents"] == 775000


def test_an_odometer_of_exactly_three_thousand_miles_triggers_no_haircut():
    """3,000 miles funds at the full demonstrator rate while 3,001 miles loses 500 basis points.

    PRD: "The boundaries are strict in opposite directions: an odometer reading of exactly 3,000 miles triggers nothing while 3,001 does, and an invoice age of exactly 45 days does trigger the aged-invoice reduction while 44 days does not."

    Design: Difficulty/boundary_precision_check/demonstrator_odometer_exactly_3000_versus_3001_flips_the_mileage_haircut
    """
    ctx = setup_active_line(tiers=[DEMO_TIER_1000])
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]

    at_threshold = floor_unit(
        dealer_id,
        line_id,
        "DEMOMILES30000001",
        dealer_headers=ctx["dealer_headers"],
        requested_amount_cents=5000000,
        document_reference="MSO-DEMO-3000",
        inventory_class="DEMONSTRATOR",
        invoice_amount_cents=5000000,
        invoice_date="2026-08-01",
        odometer_miles=3000,
    )
    over_threshold = floor_unit(
        dealer_id,
        line_id,
        "DEMOMILES30010001",
        dealer_headers=ctx["dealer_headers"],
        requested_amount_cents=5000000,
        document_reference="MSO-DEMO-3001",
        inventory_class="DEMONSTRATOR",
        invoice_amount_cents=5000000,
        invoice_date="2026-08-01",
        odometer_miles=3001,
    )

    clean = at_threshold["advance"]
    assert clean["invoice_age_days_at_funding"] == 0
    assert clean["effective_advance_rate_bps"] == 8500
    assert clean["rate_adjustment_codes"] == []
    assert clean["approved_advance_amount_cents"] == 4250000

    haircut = over_threshold["advance"]
    assert haircut["invoice_age_days_at_funding"] == 0
    assert haircut["effective_advance_rate_bps"] == 8000
    assert haircut["rate_adjustment_codes"] == ["HIGH_MILEAGE_DEMO"]
    assert haircut["approved_advance_amount_cents"] == 4000000

    assert clean["approved_advance_amount_cents"] - haircut["approved_advance_amount_cents"] == 250000


def test_the_mileage_boundary_moves_the_class_total_and_both_projected_ladders():
    """One mile of difference costs 250,000 cents of advance and shows up in every derived figure.

    PRD: "The two class aggregates, `class_outstanding_cents_used` and `class_outstanding_cents_demonstrator`, are the same outstanding-principal sum restricted to units whose `inventory_class` is `USED` and `DEMONSTRATOR` respectively."

    Design: Difficulty/boundary_precision_check/demonstrator_odometer_exactly_3000_versus_3001_flips_the_mileage_haircut
    """
    ctx = setup_active_line(tiers=[DEMO_TIER_1000])
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]

    at_threshold = floor_unit(
        dealer_id,
        line_id,
        "DEMOMILES30000001",
        dealer_headers=ctx["dealer_headers"],
        requested_amount_cents=5000000,
        document_reference="MSO-DEMO-3000",
        inventory_class="DEMONSTRATOR",
        invoice_amount_cents=5000000,
        invoice_date="2026-08-01",
        odometer_miles=3000,
    )
    over_threshold = floor_unit(
        dealer_id,
        line_id,
        "DEMOMILES30010001",
        dealer_headers=ctx["dealer_headers"],
        requested_amount_cents=5000000,
        document_reference="MSO-DEMO-3001",
        inventory_class="DEMONSTRATOR",
        invoice_amount_cents=5000000,
        invoice_date="2026-08-01",
        odometer_miles=3001,
    )

    line = read_credit_line(line_id)
    assert line["class_outstanding_cents_demonstrator"] == 8250000
    assert line["outstanding_principal_cents"] == 8250000
    assert line["available_credit_cents"] == 491750000
    assert line["eligible_collateral_cents"] == 8250000
    assert_credit_line_capacity_identity(line)

    clean_schedule = unit_schedule(at_threshold["unit"]["id"])
    assert clean_schedule["projected_obligations"][0]["projected_principal_cents"] == 425000
    assert clean_schedule["projected_total_required_cents"] == 425000

    haircut_schedule = unit_schedule(over_threshold["unit"]["id"])
    assert haircut_schedule["projected_obligations"][0]["projected_principal_cents"] == 400000
    assert haircut_schedule["projected_total_required_cents"] == 400000


def test_disbursement_is_blocked_while_the_document_is_not_in_lender_custody():
    """A unit whose title has never arrived cannot be funded, and nothing on the ledger moves.

    PRD: "Before any arithmetic runs, the operation requires the line to be `ACTIVE` and the dealership to be `ACTIVE`, the unit to be `PENDING_FUNDING`, the unit's `title_custody_status` to be exactly `LENDER_HELD` — `NOT_RECEIVED`, `LOST` and `RELEASED_FOR_SALE` all block disbursement with `ERR_TITLE_NOT_LENDER_HELD` — the unit's `eligibility_status` to be `ELIGIBLE` (`ERR_UNIT_INELIGIBLE`), the invoice to be young enough, and at least one ladder rung with a non-zero `cumulative_paydown_bps` to exist for the line and the unit's `inventory_class`."

    Design: Difficulty/cross_entity_state_dependency/advance_funding_blocked_until_the_unit_title_dimension_reaches_lender_held
    """
    ctx = setup_active_line(tiers=[NEW_TIER_1000])
    line_id = ctx["credit_line"]["id"]
    unit = register_unit(
        ctx["dealer"]["id"],
        line_id,
        "TITLEGATEUNIT001",
        dealer_headers=ctx["dealer_headers"],
        invoice_amount_cents=3000000,
    )
    assert unit["title_custody_status"] == "NOT_RECEIVED"
    advance = request_advance(
        unit["id"], ctx["dealer_headers"], 3000000, "INV-TITLEGATE"
    )
    assert advance["status"] == "REQUESTED"

    validate_error(
        _fund(advance["id"], line_id, "WIRE-TITLEGATE"),
        ApiErrorId.ERR_TITLE_NOT_LENDER_HELD,
        422,
    )

    assert validate_success(
        api_client.get_funding_advance(advance["id"], CO)
    )["status"] == "REQUESTED"
    blocked_unit = read_unit(unit["id"])
    assert blocked_unit["funding_status"] == "PENDING_FUNDING"
    assert blocked_unit["advance_amount_cents"] == 0
    line = read_credit_line(line_id)
    assert line["outstanding_principal_cents"] == 0
    assert line["available_credit_cents"] == 500000000


def test_vaulting_the_document_lets_the_same_advance_through_at_the_full_rate():
    """Moving custody to LENDER_HELD leaves the money dimension where it was and unblocks funding.

    PRD: "The document dimension advances on its own trigger set and gates the money dimension — a unit cannot be funded unless its document is in lender custody — but the money dimension never moves the document dimension."

    Design: Difficulty/cross_entity_state_dependency/advance_funding_blocked_until_the_unit_title_dimension_reaches_lender_held
    """
    ctx = setup_active_line(tiers=[NEW_TIER_1000])
    line_id = ctx["credit_line"]["id"]
    unit = register_unit(
        ctx["dealer"]["id"],
        line_id,
        "TITLEGATEUNIT001",
        dealer_headers=ctx["dealer_headers"],
        invoice_amount_cents=3000000,
    )
    advance = request_advance(
        unit["id"], ctx["dealer_headers"], 3000000, "INV-TITLEGATE"
    )
    validate_error(
        _fund(advance["id"], line_id, "WIRE-TITLEGATE"),
        ApiErrorId.ERR_TITLE_NOT_LENDER_HELD,
        422,
    )

    vaulted = move_title_custody(unit["id"], "LENDER_HELD", "MSO-TITLEGATE")
    assert vaulted["title_custody_status"] == "LENDER_HELD"
    assert vaulted["eligibility_status"] == "ELIGIBLE"
    assert vaulted["funding_status"] == "PENDING_FUNDING"

    funded = validate_success(_fund(advance["id"], line_id, "WIRE-TITLEGATE"))
    assert funded["status"] == "FUNDED"
    assert funded["approved_advance_amount_cents"] == 3000000
    assert funded["effective_advance_rate_bps"] == 10000

    unit_after = read_unit(unit["id"])
    assert unit_after["funding_status"] == "FLOORED"
    assert unit_after["advance_amount_cents"] == 3000000
    assert unit_after["outstanding_principal_cents"] == 3000000
    assert str(unit_after["floored_at"]).startswith("2026-08-01T00:00:00")
    assert unit_after["funded_by_user_id"] == CO["X-User-ID"]

    line = read_credit_line(line_id)
    assert line["outstanding_principal_cents"] == 3000000
    assert line["eligible_collateral_cents"] == 3000000
    assert line["available_credit_cents"] == 497000000
    assert_credit_line_capacity_identity(line)


def test_an_advance_larger_than_available_credit_is_refused_by_the_capacity_gate():
    """A 20,000,000 cent advance against a 5,000,000 cent facility is refused, not trimmed.

    PRD: "Fourth, two capacity gates apply, and only here can the amount cause a rejection rather than a reduction: the computed advance must not exceed the line's `available_credit_cents` (an advance exactly equal to available credit is permitted; only a strictly greater one is refused, with `ERR_CREDIT_LIMIT_EXCEEDED`), and for `USED` and `DEMONSTRATOR` units the class's current outstanding total plus the computed advance must not exceed that class's sublimit — `class_outstanding_cents_used` against `class_sublimit_cents_used`, `class_outstanding_cents_demonstrator` against `class_sublimit_cents_demonstrator` — with a breach refused as `ERR_CLASS_SUBLIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_line_state_error_beats_credit_limit_fiscal_error_on_the_same_fund_call
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        credit_limit_cents=5000000,
        max_unit_advance_cents_new=20000000,
        class_sublimit_cents_used=4000000,
        class_sublimit_cents_demonstrator=4000000,
    )
    line_id = ctx["credit_line"]["id"]
    unit = register_unit(
        ctx["dealer"]["id"],
        line_id,
        "TIGHTLINEUNIT001",
        dealer_headers=ctx["dealer_headers"],
        invoice_amount_cents=20000000,
    )
    move_title_custody(unit["id"], "LENDER_HELD", "MSO-TIGHTLINE")
    advance = request_advance(
        unit["id"], ctx["dealer_headers"], 20000000, "INV-TIGHTLINE"
    )

    validate_error(
        _fund(advance["id"], line_id, "WIRE-TIGHTLINE"),
        ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED,
        422,
    )

    assert validate_success(
        api_client.get_funding_advance(advance["id"], CO)
    )["status"] == "REQUESTED"
    line = read_credit_line(line_id)
    assert line["status"] == "ACTIVE"
    assert line["outstanding_principal_cents"] == 0
    assert line["available_credit_cents"] == 5000000


def test_the_second_covenant_failure_suspends_the_line_and_voids_the_open_request():
    """Two failed filings suspend the facility and sweep the still-requested advance away.

    PRD: "And when `covenant_breach_count` reaches 2, the second breach suspends the facility: the line moves `ACTIVE → SUSPENDED` with `suspension_reason_code` `COVENANT_BREACH_LIMIT`, which voids every advance still `REQUESTED` on the line in `created_at` ascending order with `reason_code` `LINE_SUSPENDED`, returns each of those units `PENDING_FUNDING → REGISTERED`, and moves the dealership `ACTIVE → SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_line_state_error_beats_credit_limit_fiscal_error_on_the_same_fund_call
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        credit_limit_cents=5000000,
        max_unit_advance_cents_new=20000000,
        class_sublimit_cents_used=4000000,
        class_sublimit_cents_demonstrator=4000000,
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]
    unit = register_unit(
        dealer_id,
        line_id,
        "TIGHTLINEUNIT001",
        dealer_headers=ctx["dealer_headers"],
        invoice_amount_cents=20000000,
    )
    move_title_custody(unit["id"], "LENDER_HELD", "MSO-TIGHTLINE")
    advance = request_advance(
        unit["id"], ctx["dealer_headers"], 20000000, "INV-TIGHTLINE"
    )
    assert advance["status"] == "REQUESTED"

    first = file_covenant_test(dealer_id, "2026-03-31", 100000, 1000000, 400000, 560000, 2000000)
    assert first["required_tangible_net_worth_cents"] == 500000
    assert first["failure_reason_codes"] == ["CAPITAL", "CASH_FLOW"]
    assert first["result"] == "FAIL"
    assert read_dealer(dealer_id)["covenant_breach_count"] == 1
    assert read_credit_line(line_id)["status"] == "ACTIVE"

    file_covenant_test(dealer_id, "2026-06-30", 100000, 1000000, 400000, 560000, 2000000)

    line = read_credit_line(line_id)
    assert line["status"] == "SUSPENDED"
    assert line["suspension_reason_code"] == "COVENANT_BREACH_LIMIT"
    dealer = read_dealer(dealer_id)
    assert dealer["status"] == "SUSPENDED"
    assert dealer["covenant_breach_count"] == 2

    voided = validate_success(api_client.get_funding_advance(advance["id"], CO))
    assert voided["status"] == "VOIDED"
    assert voided["reason_code"] == "LINE_SUSPENDED"
    assert read_unit(unit["id"])["funding_status"] == "REGISTERED"
